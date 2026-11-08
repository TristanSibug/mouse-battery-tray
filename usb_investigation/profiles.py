"""Match captured evidence to fixed templates, then live-validate before saving."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import time

from protocol_profiles.schema import valid_binding
from protocol_profiles.store import save_profile
from protocol_profiles.templates import parse_report, read_sample
from protocols.beken import BEKEN_VIDS, BEKEN_DEVICE_NAMES
from protocols.compx import COMPX_VIDS
from protocols.razer import _razer_get_battery_query
from protocols.wlmouse import WLMOUSE_QUERY
from .pcap import records, read_usb_packet

TEMPLATES = ('rakk-v1', 'beken-v1', 'compx-v1', 'razer-v1', 'wlmouse-v1')


def query_signature(setup, payload):
    """Recognize only implemented HID feature requests, never arbitrary replay."""
    if len(setup) != 8 or setup[5] != 0:
        return None
    report_type, report_id = setup[3], setup[2]
    if report_type != 3:
        return None
    length = int.from_bytes(setup[6:8], 'little')
    if setup[:2] == b'\xa1\x01' and report_id == 6 and length in (64, 65):
        return 'compx-v1', 'get06'
    if setup[:2] != b'\x21\x09' or length != len(payload):
        return None
    rakk = bytes([8, 4] + [0] * 14 + [0x49])
    if report_id == 8 and payload in (rakk, rakk[1:]):
        return 'rakk-v1', 'report08'
    for tx in (0x1F, 0x3F, 0xFF):
        query = _razer_get_battery_query(tx)
        if report_id == 0 and payload in (query, query[1:]):
            return 'razer-v1', 'feature90'
    wlquery = bytes([0] + WLMOUSE_QUERY + [0] * (64 - len(WLMOUSE_QUERY)))
    if report_id == 0 and payload in (wlquery, wlquery[1:]):
        return 'wlmouse-v1', 'feature83'
    for report, query in ((0, bytes([0, 6] + [0] * 62)), (6, bytes([6] + [0] * 63))):
        if report_id == report and payload in (query, query[1:]):
            return 'compx-v1', f'query06-report{report}'
    return None


def _configuration_endpoints(payload):
    """Map captured configuration descriptor endpoints to interface numbers."""
    if len(payload) < 9 or payload[:2] != b'\x09\x02':
        return {}
    result, interface, offset = defaultdict(set), None, 0
    while offset + 2 <= len(payload):
        length, kind = payload[offset:offset+2]
        if length < 2 or offset + length > len(payload):
            break
        descriptor = payload[offset:offset+length]
        if kind == 4 and length >= 9:
            interface = descriptor[2]
        elif kind == 5 and length >= 7 and interface is not None:
            result[descriptor[2]].add(interface)
        offset += length
    return result


def _selectors(device, family, interface_numbers=None, role='primary'):
    found = []
    for original in device.get('interfaces', []):
        selector = {key: original.get(key) for key in ('interface_number', 'usage_page', 'usage')}
        if any(type(value) is not int for value in selector.values()):
            continue
        page, usage = selector['usage_page'], selector['usage']
        if interface_numbers and selector['interface_number'] not in interface_numbers and selector['interface_number'] != -1:
            continue
        eligible = (page == 0xFF02 and usage == 2) if family == 'rakk-v1' and role == 'primary' else (
            page == 0xFF01 and usage == 0) if family == 'rakk-v1' else (
            page >= 0xFF00 or page == 10) if family in ('beken-v1', 'compx-v1') else (
            page == 0xFFFF) if family == 'wlmouse-v1' else (
            page >= 0xFF00 or page == 1 and usage in (2, 6))
        if eligible and selector not in found:
            found.append(selector)
    return found[:8]


def match_capture(session, summary):
    if summary.get('device_identity') != 'matched':
        return {'state': 'rejected', 'reason': 'Captured USB descriptors did not confirm the selected HID VID/PID. No profile can be generated.'}
    if not session.labels:
        return {'state': 'rejected', 'reason': 'No battery observations were recorded. Record the manufacturer reading before refreshing it.'}
    source = session.directory / 'capture.pcap'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != summary.get('sha256'):
        return {'state': 'rejected', 'reason': 'The review capture changed after analysis. Capture again; no profile was saved.'}
    # Scan full capture rather than the bounded sample preview in analysis.json.
    queries = Counter()
    query_interfaces = defaultdict(set)
    interface_map = defaultdict(set)
    stats = {template: Counter() for template in TEMPLATES}
    response_endpoints = defaultdict(set)
    labels = sorted(session.labels, key=lambda item: item['timestamp'])
    label_index = -1
    for kind, record in records(source):
        if kind != 'packet':
            continue
        stamp, _, data, truncated = record
        usb = read_usb_packet(data)
        if usb['address'] != session.target['address'] or usb['status'] or truncated or usb['truncated']:
            continue
        payload = usb['payload']
        for endpoint, interfaces in _configuration_endpoints(payload).items():
            interface_map[endpoint].update(interfaces)
        if usb['transfer'] == 2 and usb['stage'] == 0 and len(payload) >= 8:
            signature = query_signature(payload[:8], payload[8:])
            if signature:
                queries[signature] += 1
                query_interfaces[signature].add(int.from_bytes(payload[4:6], 'little'))
            continue
        incoming = bool(usb['endpoint'] & 0x80) or usb['transfer'] == 2 and usb['stage'] in (1, 3) and usb['info'] & 1
        if not incoming:
            continue
        while label_index + 1 < len(labels) and labels[label_index + 1]['timestamp'] <= stamp:
            label_index += 1
        if label_index < 0:
            continue
        label = labels[label_index]
        for template in TEMPLATES:
            reading = parse_report(template, payload)
            if reading[0] is None:
                continue
            # The canonical Beken/CompX report is shared. Choose Beken only on
            # its vendor/device markers, otherwise the passive CompX template.
            canonical = len(payload) >= 5 and payload[0] == 3 and payload[2] == 0x40
            if canonical and template in ('beken-v1', 'compx-v1'):
                is_beken = (session.device['vid'] in BEKEN_VIDS or
                            session.device['vid'] not in COMPX_VIDS and payload[1] in BEKEN_DEVICE_NAMES)
                if is_beken != (template == 'beken-v1'):
                    continue
            match = abs(reading[0] - label['battery_percent']) <= 1 and reading[1] == label['charging']
            stats[template]['matches' if match else 'mismatches'] += 1
            if usb['transfer'] == 1:
                stats[template]['interrupt_matches'] += int(match)
                response_endpoints[template].add(usb['endpoint'])
    families = []
    candidates = []
    for template in TEMPLATES:
        counts = stats[template]
        if counts['matches'] < 2 or counts['matches'] / (counts['matches'] + counts['mismatches']) < 0.8:
            continue
        signatures = [signature for signature in queries if signature[0] == template]
        if signatures:
            # Prefer the observed active query over a GET that follows it;
            # otherwise a stale feature buffer might appear to be sufficient.
            signatures.sort(key=lambda s: (s[1] == 'get06', -queries[s], s[1]))
            signature = signatures[0]
            variant = signature[1]
            interfaces = query_interfaces[signature]
        elif template in ('beken-v1', 'compx-v1') and counts['interrupt_matches'] >= 2:
            variant = 'passive'
            interfaces = set().union(*(interface_map[e] for e in response_endpoints[template]))
        else:
            continue
        primary = _selectors(session.device, template, interfaces)
        replies = _selectors(session.device, template, role='reply') if template == 'rakk-v1' else [None]
        generated = []
        for selector in primary:
            for reply in replies:
                roles = {'primary': selector}
                if reply is not None:
                    roles['reply'] = reply
                profile = {'schema_version': 1, 'vid': session.device['vid'], 'pid': session.device['pid'],
                    'name': ' '.join(session.device['product'].split())[:80] or 'Compatible Mouse',
                    'template': template, 'variant': variant, 'interfaces': roles, 'validation': {}}
                if valid_binding(profile):
                    generated.append({'profile': profile, 'capture_sha256': digest,
                        'capture_matches': counts['matches'], 'capture_mismatches': counts['mismatches']})
        if generated:
            families.append(template)
            candidates.extend(generated)
    if len(families) != 1:
        return {'state': 'rejected', 'reason': 'No unique supported family had sufficient matching queries, labelled replies and HID interfaces. Refresh the manufacturer reading at least twice and recapture, or this firmware needs a new template.'}
    if len(candidates) > 6:
        return {'state': 'rejected', 'reason': 'Too many possible HID bindings. Capture only the intended receiver and disconnect identical devices.'}
    return {'state': 'candidate', 'template': families[0], 'candidates': candidates,
            'reason': 'Known-family evidence matched. Close the manufacturer software, confirm the current reading, and run live validation.'}


def validate_and_save(match, reference_percent, reference_charging, reader=read_sample):
    if match.get('state') != 'candidate' or type(reference_percent) is not int or not 0 <= reference_percent <= 100 or type(reference_charging) is not bool:
        raise ValueError('A recognized candidate and a current 0–100% reference with charging state are required.')
    verified = []
    deadline = time.monotonic() + 35
    failures = []
    incomplete = False
    for candidate in match['candidates']:
        profile = candidate['profile']
        samples = []
        try:
            for _ in range(5):
                if time.monotonic() >= deadline:
                    incomplete = True
                    break
                percent, charging = reader(profile, timeout=min(3, max(0.1, deadline - time.monotonic())))
                if percent is None:
                    continue
                if type(percent) is not int or not 0 <= percent <= 100 or type(charging) is not bool or abs(percent - reference_percent) > 1 or charging != reference_charging:
                    raise ValueError('Live reading did not match the reference. No profile was saved.')
                samples.append({'percent': percent, 'charging': charging})
                if len(samples) == 3:
                    break
            if len(samples) == 3:
                profile = {**profile, 'validation': {key: candidate[key] for key in ('capture_sha256', 'capture_matches', 'capture_mismatches')}}
                profile['validation'].update(live_samples=samples, reference_percent=reference_percent,
                    reference_charging=reference_charging, verified_at_utc=datetime.now(timezone.utc).isoformat())
                verified.append(profile)
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
    if incomplete or len(verified) != 1:
        return {'state': 'validation_failed', 'reason': 'Live validation did not produce exactly one binding with three matching readings. Close manufacturer software, wake the mouse, disconnect identical receivers, and retry. ' + (' '.join(failures[:2])), 'saved': False}
    try:
        path = save_profile(verified[0])
    except (OSError, ValueError) as exc:
        return {'state': 'validation_failed', 'saved': False, 'reason': f'Readings matched, but the profile could not be saved: {exc}. The previous profile was kept.'}
    return {'state': 'saved', 'saved': True, 'template': verified[0]['template'], 'profile_file': path.name,
            'reason': 'Three live readings matched. Profile saved automatically; close Investigator and start/restart the updated battery tray.'}
