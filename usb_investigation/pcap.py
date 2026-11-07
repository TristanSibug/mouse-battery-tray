"""Bounded reader for USBPcap's classic PCAP files (DLT_USBPCAP 249).

Layout reference: desowin/usbpcap, USBPcapDriver/include/USBPcap.h.
No packets are transmitted, replayed, or interpreted as proven device support.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import struct

MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAGICS = {b'\xd4\xc3\xb2\xa1': ('<', 1e6), b'\xa1\xb2\xc3\xd4': ('>', 1e6),
          b'\x4d\x3c\xb2\xa1': ('<', 1e9), b'\xa1\xb2\x3c\x4d': ('>', 1e9)}


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def records(path):
    """Yield global header then complete records; a partial last write is explicit."""
    path = Path(path)
    if path.stat().st_size > MAX_CAPTURE_BYTES:
        raise ValueError('Capture exceeds the 64 MiB analysis limit.')
    with path.open('rb') as src:
        header = src.read(24)
        if len(header) != 24 or header[:4] not in MAGICS:
            raise ValueError('Not a classic USBPcap PCAP file; no valid capture header was written.')
        endian, scale = MAGICS[header[:4]]
        major, minor, _, _, snaplen, network = struct.unpack(endian + 'HHIIII', header[4:])
        if (major, minor) != (2, 4) or network != 249 or not 27 <= snaplen <= 1048576:
            raise ValueError('Expected PCAP 2.4 with USBPcap link type 249 and a valid snapshot length.')
        yield ('header', header)
        while True:
            raw = src.read(16)
            if not raw:
                return
            if len(raw) != 16:
                yield ('partial_tail', None)
                return
            sec, fraction, captured, original = struct.unpack(endian + 'IIII', raw)
            if captured > snaplen or captured > original or captured > 1048576 or fraction >= scale:
                raise ValueError('Invalid PCAP record lengths or timestamp.')
            packet = src.read(captured)
            if len(packet) != captured:
                yield ('partial_tail', None)
                return
            yield ('packet', (sec + fraction / scale, raw, packet, captured < original))


def read_usb_packet(data):
    if len(data) < 27:
        raise ValueError('Truncated USBPcap packet header.')
    header_len, irp, status, function, info, bus, address, endpoint, transfer, length = struct.unpack_from('<HQIHBHHBBI', data)
    if not 27 <= header_len <= len(data):
        raise ValueError('Invalid USBPcap header length.')
    payload = data[header_len:header_len + length]
    return {'irp': f'{irp:016x}', 'status': status, 'function': function, 'info': info,
            'bus': bus, 'address': address, 'endpoint': endpoint, 'transfer': transfer,
            'stage': data[27] if transfer == 2 and header_len >= 28 else None,
            'payload': payload, 'truncated': len(payload) < length}


def analyze_capture(source, destination, address, labels, expected_ids):
    """Keep only the selected address and complete records in the review copy.

    USB address filtering is repeated locally even though USBPcap was invoked
    with --devices. Descriptor VID/PID matching independently checks selection.
    Candidate byte correlations require multiple distinct labelled percentages.
    They are hints for manual investigation, never an auto-generated protocol.
    """
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError('The review copy must be separate from the raw capture.')
    summary = {'packets': 0, 'excluded_packets': 0, 'partial_tail': False,
               'truncated_packets': 0, 'endpoints': {}, 'descriptor_ids': [],
               'samples': [], 'control_transactions': [], 'battery_byte_hints': [],
               'limitations': ['Byte correlations may be coincidental; no protocol has been implemented or verified.']}
    endpoints = Counter()
    descriptor_ids = set()
    requests = {}
    # key=(endpoint, transfer, payload length, byte offset, encoding), values=label ids
    correlations = defaultdict(set)
    observations = sorted(labels, key=lambda item: item['timestamp'])
    last_timestamp = None
    with Path(destination).open('xb') as out:
        for kind, value in records(source):
            if kind == 'header':
                out.write(value)
                continue
            if kind == 'partial_tail':
                summary['partial_tail'] = True
                break
            stamp, raw, packet, truncated = value
            usb = read_usb_packet(packet)
            if usb['address'] != address:
                summary['excluded_packets'] += 1
                continue
            out.write(raw + packet)
            summary['packets'] += 1
            last_timestamp = stamp
            if 'first_packet_utc' not in summary:
                summary['first_packet_utc'] = utc(stamp)
            summary['last_packet_utc'] = utc(stamp)
            endpoints[f"0x{usb['endpoint']:02x}/transfer-{usb['transfer']}"] += 1
            payload = usb['payload']
            summary['truncated_packets'] += int(truncated or usb['truncated'])
            # Device descriptors start with bLength=18, bDescriptorType=1.
            if usb['transfer'] == 2 and usb['stage'] in (1, 3) and usb['status'] == 0 and len(payload) >= 18 and payload[:2] == b'\x12\x01':
                descriptor_ids.add(struct.unpack_from('<HH', payload, 8))
            if usb['transfer'] == 2 and usb['stage'] == 0 and len(payload) >= 8:
                if len(requests) >= 500:
                    requests.pop(next(iter(requests)))
                request = {'timestamp_utc': utc(stamp), 'irp': usb['irp'], 'setup_hex': payload[:8].hex(),
                           'out_data_hex': payload[8:136].hex()}
                requests[usb['irp']] = request
            elif usb['transfer'] == 2 and usb['stage'] in (1, 2, 3) and usb['irp'] in requests:
                request = requests.pop(usb['irp'])
                if len(summary['control_transactions']) < 200:
                    summary['control_transactions'].append({**request, 'response_utc': utc(stamp),
                        'status': usb['status'], 'in_data_hex': payload[:128].hex()})
            if payload and len(summary['samples']) < 200:
                summary['samples'].append({'timestamp_utc': utc(stamp), 'endpoint': usb['endpoint'],
                    'transfer': usb['transfer'], 'stage': usb['stage'], 'status': usb['status'], 'payload_hex': payload[:128].hex()})
            incoming = bool(usb['endpoint'] & 0x80) or (usb['transfer'] == 2 and usb['stage'] in (1, 3) and usb['info'] & 1)
            if not incoming or usb['status'] or truncated or usb['truncated'] or usb['stage'] == 0:
                continue
            index = next((i for i in range(len(observations) - 1, -1, -1) if observations[i]['timestamp'] <= stamp), None)
            if index is None:
                continue
            percentage = observations[index]['battery_percent']
            for offset, byte in enumerate(payload[:128]):
                for encoding, matches in [('percent', byte == percentage), ('0-255 scale', round(byte * 100 / 255) == percentage)]:
                    if matches:
                        key = (usb['endpoint'], usb['transfer'], len(payload), offset, encoding)
                        if key in correlations or len(correlations) < 4096:
                            correlations[key].add(index)
    summary['endpoints'] = dict(endpoints)
    summary['descriptor_ids'] = [f'{vid:04x}:{pid:04x}' for vid, pid in sorted(descriptor_ids)]
    expected = tuple(expected_ids)
    summary['device_identity'] = 'matched' if expected in descriptor_ids else ('mismatch' if descriptor_ids else 'unverified')
    if not summary['packets']:
        raise ValueError('No complete packets for the selected USB address. Choose the correct device and retry.')
    for key, indexes in correlations.items():
        percentages = {observations[i]['battery_percent'] for i in indexes}
        if len(percentages) >= 2 and len(summary['battery_byte_hints']) < 50:
            endpoint, transfer, length, offset, encoding = key
            summary['battery_byte_hints'].append({'endpoint': endpoint, 'transfer': transfer,
                'payload_length': length, 'offset': offset, 'encoding': encoding,
                'label_indexes': sorted(indexes), 'observed_percentages': sorted(percentages)})
    if len({o['battery_percent'] for o in observations}) < 2:
        summary['limitations'].append('Fewer than two distinct battery percentages were labelled; battery-byte correlations cannot be established.')
    if last_timestamp is not None and any(o['timestamp'] > last_timestamp for o in observations):
        summary['limitations'].append('Some labels are later than the final packet and have no following captured traffic.')
    if summary['device_identity'] != 'matched':
        summary['limitations'].append('The selected HID VID/PID was not confirmed by captured device descriptors; review USB target selection.')
    if summary['partial_tail']:
        summary['limitations'].append('Capture was interrupted during a record write; the review PCAP excludes the incomplete tail.')
    if summary['truncated_packets']:
        summary['limitations'].append('Some packets were truncated by the capture snapshot length.')
    summary['sha256'] = hashlib.sha256(Path(destination).read_bytes()).hexdigest()
    return summary
