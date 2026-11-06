import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_devices as local


def endpoint(vid=0x9999, pid=1, page=0xFF01, usage=1, path=b"vendor"):
    return dict(vendor_id=vid, product_id=pid, product_string="Test Mouse",
                interface_number=2, usage_page=page, usage=usage, path=path)


PROFILE = dict(vid=0x9999, pid=1, name="Test Mouse", protocol="standard",
               interface=2, usage_page=0xFF01, usage=1)


class DiscoveryTests(unittest.TestCase):
    def test_unknown_vendor_passive_detection_and_saved_endpoint(self):
        with patch.object(local.hid, "enumerate", return_value=[endpoint()]), \
             patch.object(local, "read_standard_battery", return_value=(75, False)) as read:
            self.assertEqual(local.detect_mouse(), (PROFILE, 75, False))
            read.assert_called_once_with(b"vendor")

    def test_no_battery_response_does_not_register_device(self):
        with patch.object(local.hid, "enumerate", return_value=[endpoint()]), \
             patch.object(local, "read_standard_battery", return_value=(None, None)):
            self.assertEqual(local.detect_mouse(), (None, None, None))

    def test_unnamed_non_mouse_device_is_not_probed(self):
        device = {**endpoint(), "product_string": None}
        with patch.object(local.hid, "enumerate", return_value=[device]), \
             patch.object(local, "read_standard_battery") as read:
            self.assertEqual(local.detect_mouse(), (None, None, None))
            read.assert_not_called()

    def test_razer_mouse_collection_can_be_queried_without_vendor_collection(self):
        device = endpoint(vid=local.devices.RAZER_VID, page=1, usage=2)
        with patch.object(local.hid, "enumerate", return_value=[device]), \
             patch.object(local.devices, "read_razer_battery", return_value=(60, False)):
            self.assertEqual(local.detect_mouse()[1], 60)

    def test_keyboard_and_movement_endpoints_are_not_probed(self):
        keyboard = endpoint()
        keyboard["product_string"] = "USB Keyboard"
        with patch.object(local.hid, "enumerate", return_value=[keyboard, endpoint(page=1, usage=2)]), \
             patch.object(local, "read_standard_battery") as read:
            self.assertEqual(local.detect_mouse(), (None, None, None))
            read.assert_not_called()

    def test_unknown_vendor_with_generic_name_uses_mouse_collection(self):
        mouse, vendor = endpoint(page=1, usage=2), endpoint()
        mouse["product_string"] = vendor["product_string"] = "USB Receiver"
        with patch.object(local.hid, "enumerate", return_value=[mouse, vendor]), \
             patch.object(local, "read_standard_battery", return_value=(50, True)):
            profile, battery, charging = local.detect_mouse()
            self.assertEqual((profile["name"], battery, charging), ("USB Receiver", 50, True))

    def test_inaccessible_endpoint_does_not_abort_other_candidates(self):
        with patch.object(local.hid, "enumerate", return_value=[endpoint(path=b"busy"), endpoint(path=b"ok")]), \
             patch.object(local, "read_standard_battery", side_effect=[OSError("busy"), (30, False)]):
            self.assertEqual(local.detect_mouse()[1], 30)

    def test_cancelled_scan_does_not_probe(self):
        with patch.object(local.hid, "enumerate", return_value=[endpoint()]), \
             patch.object(local, "read_standard_battery") as read:
            self.assertEqual(local.detect_mouse(lambda: True), (None, None, None))
            read.assert_not_called()

    def test_profile_persists_and_resolves_new_path_after_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local, "settings_path", return_value=Path(directory) / "device.json"):
            local.save_profile(PROFILE)
            loaded = local.load_profile()
            self.assertEqual(loaded, PROFILE)
            self.assertNotIn("path", loaded)
            self.assertEqual(local.resolve_profile(loaded, [endpoint(path=b"new-path")]), (b"new-path", None))
            self.assertEqual(local.resolve_profile(loaded, []), (None, None))

    def test_corrupt_or_wrong_vendor_profiles_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local, "settings_path", return_value=Path(directory) / "device.json"):
            path = local.settings_path()
            for content in ("broken", "[]", json.dumps({"version": 1, "device": {**PROFILE, "protocol": "razer"}})):
                path.write_text(content)
                self.assertIsNone(local.load_profile())

    def test_failed_save_preserves_previous_profile(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local, "settings_path", return_value=Path(directory) / "device.json"):
            local.save_profile(PROFILE)
            with patch.object(local.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    local.save_profile({**PROFILE, "name": "Replacement"})
            self.assertEqual(local.load_profile(), PROFILE)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_standard_reader_rejects_input_report_and_closes_handle(self):
        device = Mock()
        device.read.side_effect = [[3, 1, 0, 0, 75], [3, 0x85, 0x40, 2, 5]]
        with patch.object(local.hid, "device", return_value=device):
            self.assertEqual(local.read_standard_battery(b"vendor"), (50, True))
        device.close.assert_called_once()
        device.send_feature_report.assert_not_called()

    def test_razer_and_wlmouse_use_their_own_readers(self):
        for vid, protocol, reader in [(local.devices.RAZER_VID, "razer", "read_razer_battery"),
                                       (local.devices.WLMOUSE_VID, "wlmouse", "_wlmouse_read_feature")]:
            with self.subTest(protocol=protocol), \
                 patch.object(local.hid, "enumerate", return_value=[endpoint(vid=vid)]), \
                 patch.object(local.devices, reader, return_value=(80, False)) as read:
                self.assertEqual(local.detect_mouse()[0]["protocol"], protocol)
                read.assert_called_once()

    def test_rakk_resolves_both_interfaces_and_uses_active_reader(self):
        sender = endpoint(vid=local.devices.RAKK_VID, pid=local.devices.RAKK_PID, page=0xFF02, usage=2)
        listener = {**sender, "usage_page": 0xFF01, "usage": 0, "path": b"listener"}
        with patch.object(local.hid, "enumerate", return_value=[sender, listener]), \
             patch.object(local.devices, "read_rakk_battery", return_value=(42, False)) as read:
            self.assertEqual(local.detect_mouse()[0]["protocol"], "rakk")
            read.assert_called_once_with(b"vendor", b"listener")


class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolate Windows registry and GUI dependencies; these are integration
        # tests of control flow, not claims about the native Windows tray.
        config = types.ModuleType("config")
        for name, value in {"trim_memory": None, "acquire_single_instance": True,
                            "is_startup_enabled": False, "set_startup": True,
                            "get_alert_threshold": 20, "set_alert_threshold": True,
                            "get_show_estimate": True, "set_show_estimate": True,
                            "is_light_mode": False, "get_battery_history": ([], False),
                            "set_battery_history": True}.items():
            setattr(config, name, Mock(return_value=value))
        path = Path(__file__).resolve().parents[1] / "battery_tray.pyw"
        loader = importlib.machinery.SourceFileLoader("tray_under_test", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.tray = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"config": config, "pystray": Mock(), "icon_drawer": Mock()}):
            loader.exec_module(cls.tray)

    def setUp(self):
        with patch.object(self.tray, "load_profile", return_value=None):
            self.app = self.tray.BatteryTrayApp()
        self.app.icon = Mock()

    def test_click_requests_scan_without_hid_access_on_ui_thread(self):
        with patch.object(self.tray, "detect_mouse") as detect:
            self.app.on_detect_mouse(None, None)
            self.app.on_detect_mouse(None, None)
            self.assertTrue(self.app.detecting_mouse)
            self.assertTrue(self.app._rescan_requested.is_set())
            detect.assert_not_called()

    def test_successful_scan_saves_and_applies_battery_immediately(self):
        with patch.object(self.tray, "detect_mouse", return_value=(PROFILE, 75, False)), \
             patch.object(self.tray, "save_profile") as save:
            self.app.on_detect_mouse(None, None)
            self.app._detect_mouse()
            save.assert_called_once_with(PROFILE)
            self.assertEqual(self.app.local_device, PROFILE)
            self.assertEqual(self.app.last_battery, 75)
            self.assertFalse(self.app.detecting_mouse)
            self.assertFalse(self.app._rescan_requested.is_set())

    def test_failed_scan_or_save_preserves_previous_device(self):
        self.app.local_device = {**PROFILE, "name": "Previous"}
        for result, error in [((None, None, None), None), ((PROFILE, 75, False), OSError("read only"))]:
            with patch.object(self.tray, "detect_mouse", return_value=result), \
                 patch.object(self.tray, "save_profile", side_effect=error):
                self.app._detect_mouse()
                self.assertEqual(self.app.local_device["name"], "Previous")
                self.assertFalse(self.app.detecting_mouse)

    def test_saved_device_routes_to_selected_endpoint(self):
        self.app.local_device = PROFILE
        with patch.object(self.tray, "resolve_profile", return_value=(b"saved", None)), \
             patch.object(self.app, "_handle_standard_device") as handle:
            self.assertTrue(self.app._poll_local_device())
            handle.assert_called_once_with(b"saved", "wireless", "Test Mouse", PROFILE)

    def test_unplugged_device_allows_builtin_fallback(self):
        self.app.local_device = PROFILE
        with patch.object(self.tray, "resolve_profile", return_value=(None, None)):
            self.assertFalse(self.app._poll_local_device())

    def test_rescan_releases_standard_handle_before_discovery(self):
        self.app._rescan_requested.set()
        device = Mock()
        with patch.object(self.tray.hid, "device", return_value=device):
            self.app._handle_standard_device(b"current", "wireless", "Test")
        device.read.assert_not_called()
        self.assertTrue(device.close.called)

    def test_poll_worker_processes_requested_scan_before_device_polling(self):
        self.app._rescan_requested.set()
        order = []

        def detect():
            order.append("detect")
            self.app._rescan_requested.clear()

        def poll():
            order.append("poll")
            self.app.running = False
            return True

        with patch.object(self.app, "_detect_mouse", side_effect=detect), \
             patch.object(self.app, "_poll_local_device", side_effect=poll):
            self.app.poll_loop()
        self.assertEqual(order, ["detect", "poll"])


if __name__ == "__main__":
    unittest.main()
