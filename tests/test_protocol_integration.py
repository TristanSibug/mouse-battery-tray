"""Regressions for combining upstream handlers with RAKK and local discovery."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_devices as local
from protocols import get_all_handlers, rakk
from protocols.beken import BekenProtocol
from protocols.compx import CompxProtocol
import test_local_devices as fixtures
from test_local_devices import PROFILE, endpoint, enumeration


def rakk_endpoints():
    sender = endpoint(vid=rakk.RAKK_VID, pid=rakk.RAKK_PID, page=0xFF02, usage=2, path=b"send")
    sender['product_string'] = "RAKK Gahum"
    listener = {**sender, 'path': b'listen', 'usage_page': 0xFF01, 'usage': 0}
    return [sender, listener]


class RakkTests(unittest.TestCase):
    def test_query_checksum_ignores_zero_startup_reply_and_accepts_charge(self):
        sender, listener = Mock(), Mock()
        listener.read.side_effect = [[], [9, 4, 0, 0, 0, 0, 0, 0], [9, 4, 0, 0, 0, 0, 72, 1]]
        with patch.object(rakk.hid, 'device', side_effect=[sender, listener]), patch.object(rakk.time, 'sleep'):
            self.assertEqual(rakk.read_rakk_battery(b'send', b'listen'), (72, True))
        request = sender.send_feature_report.call_args.args[0]
        self.assertEqual(request[:2], [8, 4])
        self.assertEqual(len(request), 17)
        self.assertEqual(sum(request) & 0xFF, 0x55)
        sender.close.assert_called_once()
        listener.close.assert_called_once()

    def test_only_zero_or_unrelated_reports_never_become_battery(self):
        for packet in ([9, 4, 0, 0, 0, 0, 0, 0], [9, 5, 0, 0, 0, 0, 80, 0]):
            with self.subTest(packet=packet):
                sender, listener = Mock(), Mock()
                listener.read.side_effect = [[], *[packet] * 40]
                with patch.object(rakk.hid, 'device', side_effect=[sender, listener]), patch.object(rakk.time, 'sleep'):
                    self.assertEqual(rakk.read_rakk_battery(b'send', b'listen'), (None, None))

    def test_partial_open_failure_closes_both_handles(self):
        sender, listener = Mock(), Mock()
        listener.open_path.side_effect = OSError('busy')
        with patch.object(rakk.hid, 'device', side_effect=[sender, listener]):
            self.assertEqual(rakk.read_rakk_battery(b'send', b'listen'), (None, None))
        sender.close.assert_called_once()
        listener.close.assert_called_once()

    def test_interfaces_from_different_receivers_are_not_paired(self):
        endpoints = rakk_endpoints()
        endpoints[1]['serial_number'] = 'different-physical-device'
        self.assertEqual(rakk.find_rakk_pairs(endpoints), [])

    def test_shared_pulsar_id_without_rakk_interfaces_keeps_compx_handler(self):
        pulsar = endpoint(vid=rakk.RAKK_VID, pid=rakk.RAKK_PID, page=10)
        pulsar['product_string'] = 'Pulsar Receiver'
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration([pulsar])), \
             patch.object(rakk, 'read_rakk_battery') as read:
            selected = next((h, d) for h in get_all_handlers() if (d := h.find_device())[0])
        self.assertIsInstance(selected[0], CompxProtocol)
        self.assertEqual(selected[1][2], 'Pulsar X2 / Xlite Series')
        read.assert_not_called()

    def test_matching_layout_requires_valid_reply_before_claiming_rakk(self):
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(rakk, 'read_rakk_battery', return_value=(None, None)):
            selected = next((h, d) for h in get_all_handlers() if (d := h.find_device())[0])
        self.assertIsInstance(selected[0], CompxProtocol)

    def test_verified_reply_selects_rakk_and_reuses_first_reading(self):
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(rakk, 'read_rakk_battery', return_value=(65, False)) as read:
            handler = rakk.RakkProtocol()
            path, mode, name = handler.find_device()
            probe = local._BatteryProbe(time.monotonic() + 1, lambda: False)
            handler.handle_device(probe, path, mode, name)
            self.assertEqual(probe.reading, (65, False))
            read.assert_called_once()


class MigrationTests(unittest.TestCase):
    def test_existing_standard_profiles_use_new_known_handlers(self):
        for vid, expected in [(0x1D57, BekenProtocol), (0x3554, CompxProtocol)]:
            profile = {**PROFILE, 'vid': vid}
            self.assertTrue(local._valid(profile))
            self.assertIsInstance(local.profile_handler(profile), expected)
        unknown = local.profile_handler(PROFILE)
        self.assertFalse(unknown.allow_queries)
        self.assertTrue(unknown.canonical_only)

    def test_compx_report_six_is_used_for_detection_and_old_profile_polling(self):
        device = endpoint(vid=0x3554, pid=0xF58A, page=0xFF04)
        fake = Mock()
        fake.read.return_value = []
        fake.get_feature_report.side_effect = lambda report, size: [6, 0, 0, 0, 85, 0] if report == 6 else []
        with patch.object(local.hid, 'enumerate', side_effect=enumeration([device])), \
             patch.object(local.hid, 'device', return_value=fake):
            profile, battery, charging = local.detect_mouse()
            self.assertEqual((profile['protocol'], battery, charging), ('compx', 85, False))
            legacy = {**profile, 'protocol': 'standard'}
            probe = local._BatteryProbe(time.monotonic() + 1, lambda: False)
            local.profile_handler(legacy).handle_device(probe, device['path'], 'wireless', profile['name'])
            self.assertEqual(probe.reading, (85, False))
        self.assertTrue(fake.close.called)

    def test_gwolves_requires_two_consistent_readings_and_rejects_config(self):
        device = endpoint(vid=0x33E4)
        handler = CompxProtocol()
        self.assertEqual(handler.parse_packet([3, 0, 0, 0, 48], 0, 0x33E4), (None, None))
        for packets, expected in [([[3, 0, 0x40, 0, 48]], (None, None)),
                                  ([[3, 0, 0x40, 0, 48]] * 2, (48, False))]:
            queue = list(packets)
            fake = Mock()
            fake.read.side_effect = lambda size: queue.pop(0) if queue else []
            fake.get_feature_report.return_value = []
            probe = local._BatteryProbe(time.monotonic() + 0.01, lambda: False)
            with patch.object(local.hid, 'enumerate', side_effect=enumeration([device])), \
                 patch.object(local.hid, 'device', return_value=fake), patch.object(probe, 'wait_for_poll'):
                handler.handle_device(probe, device['path'], 'wireless', 'G-Wolves')
            self.assertEqual(probe.reading, expected)

    def test_unknown_oem_uses_canonical_passive_reads_only(self):
        fake = Mock()
        fake.read.side_effect = [[3, 0, 0, 0, 55], [3, 0, 0x40, 0, 75]]
        device = endpoint()
        probe = local._BatteryProbe(time.monotonic() + 1, lambda: False)
        with patch.object(local.hid, 'enumerate', side_effect=enumeration([device])), \
             patch.object(local.hid, 'device', return_value=fake):
            local.profile_handler(PROFILE).handle_device(probe, device['path'], 'wireless', PROFILE['name'])
        self.assertEqual(probe.reading, (75, False))
        fake.send_feature_report.assert_not_called()
        fake.close.assert_called_once()


class TrayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the platform-isolated tray loader, without collecting its tests twice.
        fixtures.TrayTests.setUpClass()
        cls.tray = fixtures.TrayTests.tray

    def setUp(self):
        with patch.object(self.tray, 'load_profile', return_value=None):
            self.app = self.tray.BatteryTrayApp()
        self.app.icon = Mock()

    def test_protocol_bridge_resets_history_and_updates_battery(self):
        self.app.battery_history = [(1, 100)]
        self.app._active_device_path = b'previous'
        self.app.update_device_state(b'new', 'RAKK Gahum', 72, charging=False)
        self.assertEqual(self.app.current_model, 'RAKK Gahum')
        self.assertEqual(self.app.last_battery, 72)
        self.assertEqual(len(self.app.battery_history), 1)
        self.assertEqual(self.app.battery_history[0][1], 72)
        self.app.update_device_state(b'new', 'RAKK Gahum', -1, charging=True)
        self.assertEqual(self.app.status, 'charging')
        self.assertEqual(self.app.last_battery, -1)

    def test_first_reading_keeps_persisted_discharge_history(self):
        self.app.battery_history = [(time.time() - 60, 75)]
        self.app.update_device_state(b'first', 'Mouse', 75)
        self.assertEqual(len(self.app.battery_history), 1)
        self.assertLess(self.app.battery_history[0][0], time.time() - 50)

    def test_rescan_interrupts_compx_and_closes_handle(self):
        fake = Mock()
        def read(size):
            self.app.on_detect_mouse(None, None)
            return []
        fake.read.side_effect = read
        device = endpoint(vid=0x3554)
        with patch.object(local.hid, 'enumerate', side_effect=enumeration([device])), \
             patch.object(local.hid, 'device', return_value=fake):
            CompxProtocol().handle_device(self.app, device['path'], 'wireless', 'VXE')
        fake.close.assert_called_once()
        fake.send_feature_report.assert_not_called()
        self.assertTrue(self.app._rescan_requested.is_set())


if __name__ == '__main__':
    unittest.main()
