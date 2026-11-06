"""Regressions for combining upstream handlers with RAKK support."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hid
from protocols.utils import parse_battery_telemetry
from protocols import get_all_handlers, rakk
from protocols.beken import BekenProtocol
from protocols.compx import CompxProtocol
from helpers import TestApp, load_tray, endpoint, enumeration


def rakk_endpoints():
    sender = endpoint(vid=rakk.RAKK_VID, pid=rakk.RAKK_PID, page=0xFF02, usage=2, path=b"send")
    sender['product_string'] = "RAKK Gahum"
    listener = {**sender, 'path': b'listen', 'usage_page': 0xFF01, 'usage': 0}
    return [sender, listener]


class RakkTests(unittest.TestCase):
    def test_single_receiver_without_serial_pairs_distinct_windows_interface_paths(self):
        endpoints = rakk_endpoints()
        endpoints[0].update(serial_number='', path=br'\\?\hid#vid_25a7&pid_fa7c&mi_01#8&111111&0&0000#{hid}')
        endpoints[1].update(serial_number='', path=br'\\?\hid#vid_25a7&pid_fa7c&mi_02#8&222222&0&0000#{hid}')
        self.assertEqual(rakk.find_rakk_pairs(endpoints), [(endpoints[0]['path'], endpoints[1]['path'])])

    def test_startup_without_battery_does_not_fall_through_to_pulsar(self):
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(rakk, 'read_rakk_battery', return_value=(None, None)):
            selected = next((h, d) for h in get_all_handlers() if (d := h.find_device())[0])
        self.assertIsInstance(selected[0], rakk.RakkProtocol)

    def test_missing_startup_reading_is_retried_until_valid(self):
        probe = TestApp()
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(rakk, 'read_rakk_battery', side_effect=[(None, None), (65, False)]) as read, \
             patch.object(probe, 'wait_for_poll') as wait:
            rakk.RakkProtocol().handle_device(probe, b'send', 'wireless', 'RAKK Gahum')
        self.assertEqual(probe.reading, (65, False))
        self.assertEqual(read.call_count, 2)
        self.assertEqual(wait.call_args_list[0].args, (10,))

    def test_multiple_unidentified_receivers_are_not_cross_paired(self):
        endpoints = []
        for number in (1, 2):
            pair = rakk_endpoints()
            for role, device in enumerate(pair):
                device.update(serial_number='', path=f'interface-{number}-{role}'.encode())
            endpoints.extend(pair)
        self.assertEqual(rakk.find_rakk_pairs(endpoints), [])

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
        sender.set_nonblocking.assert_not_called()
        listener.set_nonblocking.assert_called_once_with(True)

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

    def test_matching_layout_stays_on_rakk_while_battery_is_unavailable(self):
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(rakk, 'read_rakk_battery', return_value=(None, None)):
            selected = next((h, d) for h in get_all_handlers() if (d := h.find_device())[0])
        self.assertIsInstance(selected[0], rakk.RakkProtocol)

    def test_discovery_does_not_consume_first_reading(self):
        with patch.object(rakk.hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(rakk, 'read_rakk_battery', return_value=(65, False)) as read:
            handler = rakk.RakkProtocol()
            path, mode, name = handler.find_device()
            probe = TestApp()
            handler.handle_device(probe, path, mode, name)
            self.assertEqual(probe.reading, (65, False))
            read.assert_called_once()


class ProtocolTests(unittest.TestCase):
    def test_compx_reads_report_six_on_silent_receiver(self):
        device = endpoint(vid=0x3554, pid=0xF58A, page=0xFF04)
        fake = Mock()
        fake.read.return_value = []
        fake.get_feature_report.side_effect = lambda report, size: [6, 0, 0, 0, 85, 0] if report == 6 else []
        app = TestApp()
        with patch.object(hid, 'enumerate', side_effect=enumeration([device])), \
             patch.object(hid, 'device', return_value=fake):
            CompxProtocol().handle_device(app, device['path'], 'wireless', 'VXE R1 Pro')
        self.assertEqual(app.reading, (85, False))
        fake.close.assert_called_once()

    def test_gwolves_requires_two_consistent_readings_and_rejects_config(self):
        device = endpoint(vid=0x33E4)
        handler = CompxProtocol()
        self.assertEqual(parse_battery_telemetry([3, 0, 0, 0, 48], 0, vid=0x33E4), (None, None))
        for packets, expected in [([[3, 0, 0x40, 0, 48]], (None, None)),
                                  ([[3, 0, 0x40, 0, 48]] * 2, (48, False))]:
            queue = list(packets)
            fake = Mock()
            fake.read.side_effect = lambda size: queue.pop(0) if queue else []
            fake.get_feature_report.return_value = []
            probe = TestApp(seconds=0.01)
            with patch.object(hid, 'enumerate', side_effect=enumeration([device])), \
                 patch.object(hid, 'device', return_value=fake), patch.object(probe, 'wait_for_poll'):
                handler.handle_device(probe, device['path'], 'wireless', 'G-Wolves')
            self.assertEqual(probe.reading, expected)


class TrayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tray = load_tray()

    def setUp(self):
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

    def test_exit_interrupts_compx_and_closes_handle(self):
        fake = Mock()
        def read(size):
            self.app.on_exit(None, None)
            return []
        fake.read.side_effect = read
        device = endpoint(vid=0x3554)
        with patch.object(hid, 'enumerate', side_effect=enumeration([device])), \
             patch.object(hid, 'device', return_value=fake):
            CompxProtocol().handle_device(self.app, device['path'], 'wireless', 'VXE')
        fake.close.assert_called_once()
        fake.send_feature_report.assert_not_called()
        self.assertTrue(self.app._stop_requested.is_set())

    def test_menu_contains_normal_controls_without_discovery_or_donation(self):
        items = []
        def menu_item(label, action, **kwargs):
            items.append(label)
            return label
        with patch.object(self.tray.pystray, 'MenuItem', side_effect=menu_item):
            self.app.create_menu()
        for label in ('Start with Windows', 'Show Hours Estimate', 'Low Battery Alert', 'Check for Updates', 'Exit'):
            self.assertIn(label, items)
        self.assertNotIn('Detect my mouse', items)
        self.assertNotIn('Donate / Support', items)

    def test_poll_loop_automatically_selects_rakk_without_profile(self):
        handler = rakk.RakkProtocol()
        def finish(app, path, mode, name):
            app.update_device_state(path, name, 72)
            app.running = False
        with patch.object(hid, 'enumerate', side_effect=enumeration(rakk_endpoints())), \
             patch.object(self.tray, 'get_all_handlers', return_value=[handler]), \
             patch.object(handler, 'handle_device', side_effect=finish):
            self.app.poll_loop()
        self.assertEqual((self.app.current_model, self.app.last_battery), ('RAKK Gahum', 72))


if __name__ == '__main__':
    unittest.main()
