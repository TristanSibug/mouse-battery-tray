"""Synthetic USBPcap fixtures and an actual owned capture-process lifecycle."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usb_investigation import capture, pcap

CONTROLLER = r'\\.\USBPcap1'
TARGET = {'controller': CONTROLLER, 'address': 4, 'label': '[4] USB Receiver', 'interfaces': ['HID-compliant mouse']}
DEVICE = {'vid': 0x25A7, 'pid': 0xFA7C, 'product': 'Test Mouse', 'manufacturer': 'Test', 'interfaces': []}
INTERFACES = f'interface {{value={CONTROLLER}}}{{display=USBPcap1}}\n'
DEVICES = ('arg {number=5}{call=--devices}\n'
           'value {arg=5}{value=0}{display=Root Hub}{enabled=true}\n'
           'value {arg=5}{value=4}{display=[4] USB Receiver}{enabled=true}\n'
           'value {arg=5}{value=4_1}{display=HID-compliant mouse}{enabled=false}{parent=4}\n'
           'value {arg=5}{value=4_2}{display=USB Input Device}{enabled=false}{parent=4}\n'
           'value {arg=5}{value=5}{display=[5] Keyboard}{enabled=true}\n')


def global_header(endian='<', nanos=False):
    magic = 0xA1B23C4D if nanos else 0xA1B2C3D4
    return struct.pack(endian + 'IHHIIII', magic, 2, 4, 0, 0, 65535, 249)


def packet(payload, stamp=1000, address=4, endpoint=0x81, transfer=1, stage=None, irp=1, endian='<'):
    header_size = 28 if stage is not None else 27
    usb = struct.pack('<HQIHBHHBBI', header_size, irp, 0, 0, 1 if endpoint & 0x80 else 0,
                      1, address, endpoint, transfer, len(payload))
    if stage is not None:
        usb += bytes([stage])
    data = usb + payload
    sec = int(stamp)
    return struct.pack(endian + 'IIII', sec, int((stamp-sec)*1e6), len(data), len(data)) + data


def descriptor(vid=0x25A7, pid=0xFA7C):
    data = bytearray(18)
    data[:2] = b'\x12\x01'
    struct.pack_into('<HH', data, 8, vid, pid)
    return bytes(data)


def sample_capture():
    return (global_header() + packet(descriptor(), transfer=2, stage=3, stamp=1000)
            + packet(b'\x03\x00\x40\x00\x48', stamp=1002)
            + packet(b'\x03\x00\x40\x00\x47', stamp=1012))


def labels():
    return [{'timestamp': 1001, 'battery_percent': 72, 'charging': False},
            {'timestamp': 1011, 'battery_percent': 71, 'charging': True}]


class DiscoveryTests(unittest.TestCase):
    def test_parse_real_extcap_shapes_including_children(self):
        self.assertEqual(capture.parse_interfaces(INTERFACES), [{'controller': CONTROLLER, 'label': 'USBPcap1'}])
        devices = capture.parse_devices(DEVICES)
        self.assertEqual([d['address'] for d in devices], [4, 5])
        self.assertEqual(devices[0]['interfaces'], ['HID-compliant mouse', 'USB Input Device'])

    def test_invalid_controller_or_address_is_never_used_as_a_command(self):
        for controller, address in [('USBPcap1 & calc', 4), (CONTROLLER, '4,5'), (CONTROLLER, 0), (CONTROLLER, 128), (CONTROLLER, True)]:
            with self.subTest(controller=controller, address=address), self.assertRaises(ValueError):
                capture.capture_command('USBPcapCMD.exe', controller, address, 'out.pcap')

    def test_capture_command_is_scoped_to_one_address(self):
        command = capture.capture_command('USBPcapCMD.exe', CONTROLLER, 4, 'out.pcap')
        self.assertEqual(command[command.index('--devices') + 1], '4')
        self.assertNotIn('-A', command)
        self.assertNotIn('--capture-from-new-devices', command)
        self.assertIn('--inject-descriptors', command)

    def test_hid_metadata_omits_serial_numbers_and_paths(self):
        endpoint = {'vendor_id': 1, 'product_id': 2, 'product_string': 'Mouse', 'path': b'private-path', 'serial_number': 'private-serial', 'usage_page': 1, 'usage': 2}
        with patch.object(capture.hid, 'enumerate', return_value=[endpoint, endpoint]):
            data = capture.hid_mice()
        self.assertEqual(len(data), 1)
        self.assertNotIn('private', json.dumps(data))



class PcapTests(unittest.TestCase):
    def analyze(self, raw, observations=None, expected=(0x25A7, 0xFA7C)):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        source, review = root / 'raw.pcap', root / 'review.pcap'
        source.write_bytes(raw)
        summary = pcap.analyze_capture(source, review, 4, labels() if observations is None else observations, expected)
        return summary, review, source

    def test_descriptor_identity_and_labelled_byte_correlation(self):
        summary, review, _ = self.analyze(sample_capture())
        self.assertEqual(summary['packets'], 3)
        self.assertEqual(summary['device_identity'], 'matched')
        hint = next(h for h in summary['battery_byte_hints'] if h['offset'] == 4 and h['encoding'] == 'percent')
        self.assertEqual(hint['observed_percentages'], [71, 72])
        self.assertEqual(summary['sha256'], hashlib.sha256(review.read_bytes()).hexdigest())

    def test_control_request_and_response_are_paired_by_irp(self):
        request = packet(bytes.fromhex('a101000304000800'), transfer=2, stage=0, endpoint=0, irp=99)
        response = packet(b'\x09\x04\x00\x00\x00\x00\x48\x00', transfer=2, stage=3, irp=99)
        summary, _, _ = self.analyze(global_header() + request + response)
        transaction = summary['control_transactions'][0]
        self.assertEqual(transaction['setup_hex'], 'a101000304000800')
        self.assertTrue(transaction['in_data_hex'].startswith('0904'))

    def test_other_devices_are_excluded_from_review_copy(self):
        raw = sample_capture() + packet(b'PRIVATE KEYBOARD', address=5)
        summary, review, _ = self.analyze(raw)
        self.assertEqual(summary['excluded_packets'], 1)
        self.assertNotIn(b'PRIVATE KEYBOARD', review.read_bytes())

    def test_partial_tail_is_reported_and_raw_is_preserved(self):
        raw = sample_capture() + packet(b'incomplete')[:-3]
        summary, review, source = self.analyze(raw)
        self.assertTrue(summary['partial_tail'])
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(review.read_bytes(), sample_capture())

    def test_mismatched_or_missing_descriptors_are_not_claimed_matched(self):
        summary, _, _ = self.analyze(sample_capture(), expected=(1, 2))
        self.assertEqual(summary['device_identity'], 'mismatch')
        summary, _, _ = self.analyze(global_header() + packet(b'\x03\x00\x40\x00\x48'))
        self.assertEqual(summary['device_identity'], 'unverified')

    def test_single_battery_level_does_not_produce_byte_hints(self):
        summary, _, _ = self.analyze(sample_capture(), observations=[labels()[0]])
        self.assertEqual(summary['battery_byte_hints'], [])
        self.assertTrue(any('Fewer than two' in line for line in summary['limitations']))

    def test_big_endian_pcap_header_and_records(self):
        raw = global_header('>') + packet(descriptor(), transfer=2, stage=3, endian='>')
        summary, _, _ = self.analyze(raw, observations=[])
        self.assertEqual(summary['device_identity'], 'matched')

    def test_invalid_headers_records_and_empty_device_capture_are_rejected(self):
        bad_record = struct.pack('<IIII', 1, 0, 0xFFFFFFFF, 0xFFFFFFFF)
        bad_usb = packet(b'')[:16] + b'\x00' * 27
        for raw in (b'not pcap', global_header()[:20], global_header() + bad_record, global_header() + bad_usb,
                    global_header() + packet(b'other', address=5)):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                self.analyze(raw)

    def test_payload_snapshot_truncation_is_reported(self):
        data = bytearray(packet(b'abc'))
        struct.pack_into('<I', data, 16 + 23, 50)
        summary, _, _ = self.analyze(global_header() + data, observations=[])
        self.assertEqual(summary['truncated_packets'], 1)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.session = capture.CaptureSession(self.folder.name, DEVICE, TARGET, 'Manufacturer app', duration=10)

    def test_invalid_observation_rejected_and_labels_are_saved_locally(self):
        self.session.process = Mock()
        self.session.process.poll.return_value = None
        with self.assertRaises(ValueError):
            self.session.observe(72, False)
        self.session.started = time.monotonic()
        for value, charging in [(101, False), (-1, False), (72.0, False), (72, 'yes')]:
            with self.assertRaises(ValueError):
                self.session.observe(value, charging)
        self.session.observe(72, False, 'refresh now')
        saved = json.loads((self.session.directory / 'session.json').read_text())
        self.assertEqual(saved['observations'][0]['battery_percent'], 72)
        self.assertEqual(saved['observations'][0]['note'], 'refresh now')

    def test_stopped_capture_exports_only_review_files(self):
        (self.session.directory / 'capture.raw.pcap').write_bytes(sample_capture())
        self.session.labels.extend(labels())
        self.session.stop()
        archive, summary = self.session.finalize()
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(set(bundle.namelist()), {'capture.pcap', 'analysis.json', 'session.json', 'REPORT.md'})
        self.assertEqual(summary['device_identity'], 'matched')
        self.assertEqual(self.session.manifest['status'], 'evidence_collected')
        with self.assertRaises(RuntimeError):
            self.session.finalize()

    def test_invalid_capture_never_produces_success_bundle(self):
        (self.session.directory / 'capture.raw.pcap').write_bytes(b'broken')
        self.session.stop()
        with self.assertRaises(ValueError):
            self.session.finalize()
        self.assertEqual(self.session.manifest['status'], 'capture_invalid')
        self.assertFalse((self.session.directory / 'review-bundle.zip').exists())

    def test_stale_target_does_not_launch_process(self):
        with patch.object(capture, '_metadata', return_value=''), patch.object(capture.subprocess, 'Popen') as process:
            with self.assertRaises(ValueError):
                self.session.start('USBPcapCMD.exe')
        process.assert_not_called()

    def test_uac_wait_does_not_consume_capture_duration_and_has_timeout(self):
        self.session.process = Mock()
        self.session.process.poll.return_value = None
        self.session.launched = time.monotonic() - 61
        self.session.tick()
        self.assertEqual(self.session.manifest['stop_reason'], 'startup_timeout')
        self.session.process.terminate.assert_called_once()
        self.assertIsNone(self.session.started)

    def test_capture_limit_terminates_and_waits_for_owned_process(self):
        self.session.process = Mock()
        self.session.process.poll.return_value = None
        self.session.launched = time.monotonic()
        self.session.started = time.monotonic() - 11
        self.session.tick()
        self.assertEqual(self.session.manifest['stop_reason'], 'duration_limit')
        self.session.process.terminate.assert_called_once()
        self.session.process.wait.assert_called_once_with(timeout=8)

    def test_stop_failure_is_not_claimed_stopped_or_exportable(self):
        self.session.process = Mock()
        self.session.process.poll.return_value = None
        self.session.process.terminate.side_effect = PermissionError('cannot stop process')
        with self.assertRaises(PermissionError):
            self.session.stop()
        self.assertFalse(self.session.finished)
        with self.assertRaises(RuntimeError):
            self.session.finalize()

    def test_mismatched_target_bundle_is_explicitly_marked_for_review(self):
        raw = global_header() + packet(descriptor(1, 2), transfer=2, stage=3)
        (self.session.directory / 'capture.raw.pcap').write_bytes(raw)
        self.session.stop()
        self.session.finalize()
        self.assertEqual(self.session.manifest['status'], 'selection_needs_review')

    @unittest.skipIf(os.name == 'nt', 'POSIX fixture executable; Windows live capture is tested manually')
    def test_real_child_process_capture_stop_and_export(self):
        executable = Path(self.folder.name) / 'USBPcapCMD.exe'
        script = ('#!/usr/bin/env python3\nimport sys,time\nfrom pathlib import Path\n'
                  f'if "--extcap-config" in sys.argv:\n print({DEVICES!r})\n'
                  'else:\n'
                  f' Path(sys.argv[sys.argv.index("-o")+1]).write_bytes({sample_capture()!r})\n'
                  ' while True: time.sleep(0.1)\n')
        executable.write_text(script)
        executable.chmod(0o700)
        try:
            self.session.start(executable)
            deadline = time.monotonic() + 3
            while self.session.started is None and time.monotonic() < deadline:
                self.session.tick()
                time.sleep(0.01)
            self.assertEqual(self.session.manifest['status'], 'capturing')
            self.session.observe(72, False)
        finally:
            self.session.stop()
        self.assertIsNotNone(self.session.process.poll())
        archive, summary = self.session.finalize()
        self.assertTrue(archive.is_file())
        self.assertEqual(summary['device_identity'], 'matched')


if __name__ == '__main__':
    unittest.main()
