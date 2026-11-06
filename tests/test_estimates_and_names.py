import importlib.util
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import load_tray, endpoint
from device_names import specific_usb_name


class TrayFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tray = load_tray()

    def setUp(self):
        self.app = self.tray.BatteryTrayApp()
        self.app.icon = Mock()
        self.info = endpoint(vid=0x25A7, pid=0xFA7C)
        self.info['product_string'] = '2.4G Wireless Device'
        self.tray.get_device_name.reset_mock()
        self.tray.get_device_name.return_value = None
        self.tray.set_device_name.reset_mock(return_value=True)
        self.tray.set_battery_history.reset_mock()

    def reading(self, at, battery, path=b'vendor', charging=False):
        with patch.object(self.tray.time, 'time', return_value=at), \
             patch.object(self.tray, 'device_info', return_value=self.info):
            self.app.update_device_state(path, 'Wireless Mouse', battery, charging)

    def test_first_reading_shows_learning_instead_of_silently_hiding_estimate(self):
        self.reading(1000000, 85)
        self.assertIn('estimating...', self.app.icon.title)
        self.assertEqual(self.app.estimate_status(), 'learning (needs battery drop)')

    def test_slow_discharge_survives_four_hour_boundary_and_300_hour_limit(self):
        start = 1000000
        for offset in range(0, 6 * 3600 + 1, 60):
            self.reading(start + offset, 79 if offset == 6 * 3600 else 80)
        with patch.object(self.tray.time, 'time', return_value=start + 6 * 3600):
            self.assertEqual(self.app.get_battery_estimate_str(), '~474h')
        self.assertIn('~474h', self.app.icon.title)

    def test_sleep_with_unchanged_percentage_does_not_inflate_estimate(self):
        self.reading(1000000, 80)
        self.reading(1000060, 79)
        self.reading(1005000, 79)
        self.assertEqual(self.app.battery_history, [(1005000, 79)])
        self.assertIn('estimating...', self.app.icon.title)

    def test_charging_resets_history_and_hides_estimate(self):
        self.reading(1000000, 80)
        self.reading(1000060, 79)
        self.reading(1000120, 80, charging=True)
        self.assertEqual(self.app.battery_history, [])
        self.assertEqual(self.app.estimate_status(), 'paused while charging')
        self.assertNotIn('estimating...', self.app.icon.title)

    def test_same_mouse_different_interface_keeps_history(self):
        self.reading(1000000, 80)
        self.reading(1000060, 79, path=b'other-interface')
        self.assertEqual(len(self.app.battery_history), 2)

    def test_estimate_toggle_still_hides_estimate(self):
        self.app.show_estimate = False
        self.reading(1000000, 80)
        self.assertNotIn('estimating...', self.app.icon.title)
        self.assertIsNone(self.app.get_battery_estimate_str())

    def test_missing_battery_blocks_name_fix_and_does_not_open_dialog(self):
        with patch.object(self.tray, 'ask_device_name') as ask:
            self.app.on_fix_device_name(None, None)
        ask.assert_not_called()
        self.tray.set_device_name.assert_not_called()
        self.assertIn('cannot fix missing battery support', self.app.icon.notify.call_args.args[0])

    def name_fix(self, answer='RAKK Gahum', usb_name='2.4G Wireless Device'):
        now = time.time()
        self.info['product_string'] = usb_name
        self.reading(now, 72)
        # Execute the UI worker synchronously, testing the exact callback body.
        with patch.object(self.tray.threading, 'Thread') as thread, \
             patch.object(self.tray, 'device_info', return_value=self.info), \
             patch.object(self.tray, 'ask_device_name', return_value=answer) as ask:
            self.app.on_fix_device_name(None, None)
            worker = thread.call_args.kwargs['target']
            worker()
        return ask

    def test_generic_usb_name_prompts_saves_alias_and_keeps_battery(self):
        ask = self.name_fix()
        ask.assert_called_once()
        self.tray.set_device_name.assert_called_once_with(0x25A7, 0xFA7C, 'RAKK Gahum')
        self.assertIn('RAKK Gahum: 72%', self.app.icon.title)
        self.assertEqual(self.app.last_battery, 72)
        self.assertEqual(self.app.current_model, 'Wireless Mouse')
        self.reading(time.time(), 72)
        self.assertIn('RAKK Gahum: 72%', self.app.icon.title)

    def test_specific_usb_name_applied_without_prompt(self):
        ask = self.name_fix(usb_name='Pulsar X2 Receiver')
        ask.assert_not_called()
        self.tray.set_device_name.assert_called_once_with(0x25A7, 0xFA7C, 'Pulsar X2 Receiver')

    def test_cancel_leaves_previous_name(self):
        self.name_fix(answer=None)
        self.tray.set_device_name.assert_not_called()
        self.assertIsNone(self.app._display_alias)

    def test_failed_save_keeps_previous_name(self):
        self.tray.set_device_name.return_value = False
        # name_fix resets no configuration mocks; the failed save reaches the UI.
        self.name_fix()
        self.assertIsNone(self.app._display_alias)
        self.assertIn('Could not save', self.app.icon.notify.call_args.args[0])

    def test_stale_reading_or_unknown_state_blocks_rename(self):
        self.reading(time.time() - 181, 72)
        self.assertFalse(self.app.can_fix_device_name())
        self.reading(time.time(), 72)
        self.assertTrue(self.app.can_fix_device_name())
        self.app.status = 'unknown'
        self.assertFalse(self.app.can_fix_device_name())

    def test_menu_name_action_is_disabled_without_battery_and_enabled_with_reading(self):
        actions = {}
        def item(label, action, **kwargs):
            if isinstance(label, str):
                actions[label] = kwargs
            return label
        with patch.object(self.tray.pystray, 'MenuItem', side_effect=item):
            self.app.create_menu()
            self.assertFalse(actions['Fix Generic Device Name']['enabled'](None))
            self.assertIn('Name fix requires a detected battery level', actions)
            self.reading(time.time(), 72)
            self.assertTrue(actions['Fix Generic Device Name']['enabled'](None))

    def test_device_switch_during_name_prompt_does_not_save_alias_to_old_mouse(self):
        self.reading(time.time(), 72)
        def switch_mouse(name):
            self.reading(time.time(), 70, path=b'different-mouse')
            return 'Wrong Target'
        with patch.object(self.tray.threading, 'Thread') as thread, \
             patch.object(self.tray, 'device_info', return_value=self.info), \
             patch.object(self.tray, 'ask_device_name', side_effect=switch_mouse):
            self.app.on_fix_device_name(None, None)
            thread.call_args.kwargs['target']()
        self.tray.set_device_name.assert_not_called()

    def test_alias_loaded_on_startup_and_isolated_from_different_vid_pid(self):
        self.tray.get_device_name.return_value = 'My Mouse'
        self.reading(time.time(), 72)
        self.assertIn('My Mouse', self.app.icon.title)
        self.tray.get_device_name.return_value = None
        self.info = {**self.info, 'product_id': 2}
        self.reading(time.time(), 80, path=b'new-mouse')
        self.assertIsNone(self.app._display_alias)


class RegistryNameTests(unittest.TestCase):
    def setUp(self):
        self.registry = Mock()
        spec = importlib.util.spec_from_file_location('config_names_test', Path(__file__).resolve().parents[1] / 'config.py')
        self.config = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'winreg': self.registry}):
            spec.loader.exec_module(self.config)

    def test_name_roundtrip_uses_only_display_alias_registry_key(self):
        self.registry.CreateKey.return_value = self.registry.OpenKey.return_value = manager = Mock()
        manager.__enter__ = Mock(return_value='key')
        manager.__exit__ = Mock(return_value=False)
        self.assertTrue(self.config.set_device_name(0x25A7, 0xFA7C, ' RAKK  Gahum '))
        self.registry.SetValueEx.assert_called_once_with('key', '25a7:fa7c', 0, self.registry.REG_SZ, 'RAKK Gahum')
        self.registry.QueryValueEx.return_value = ('RAKK Gahum', self.registry.REG_SZ)
        self.assertEqual(self.config.get_device_name(0x25A7, 0xFA7C), 'RAKK Gahum')

    def test_invalid_name_or_registry_failure_is_handled(self):
        self.assertFalse(self.config.set_device_name(1, 2, ' '))
        self.assertFalse(self.config.set_device_name(1, 2, 'x' * 81))
        self.registry.CreateKey.side_effect = OSError('read only')
        self.assertFalse(self.config.set_device_name(1, 2, 'Mouse'))
        self.registry.OpenKey.side_effect = OSError('missing')
        self.assertIsNone(self.config.get_device_name(1, 2))

    def test_generic_descriptors_do_not_invent_model_names(self):
        for product in ('USB Receiver', '2.4G Wireless Device', 'Gaming Mouse', None):
            self.assertIsNone(specific_usb_name({'product_string': product}))
        self.assertEqual(specific_usb_name({'product_string': 'RAKK Gahum'}), 'RAKK Gahum')


if __name__ == '__main__':
    unittest.main()
