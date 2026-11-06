"""Exercise popup-menu lifetime and background update completion without Win32."""
import sys
import types
import unittest
import urllib.error
from unittest.mock import Mock, patch

from helpers import load_tray

# The tests exercise backend control flow, not a native desktop session.
with patch.dict(sys.modules, {'pystray': Mock()}):
    import tray_icon


class FakeNativeIcon:
    def __init__(self):
        self.descriptor = 'initial'
        self.rebuilds = []
        self.during_popup = lambda: None
        self.selected = None

    def _update_menu(self):
        self._menu_handle = (self.descriptor, [self.descriptor + ' callback'])
        self.rebuilds.append(self.descriptor)

    def _on_notify(self, wparam, lparam):
        if lparam != 0x0205:
            return 'other notification'
        handle, callbacks = self._menu_handle
        self.during_popup()
        # Model TrackPopupMenuEx returning a selection from the original menu.
        self.selected = callbacks[0]
        return handle


class SafeFakeIcon(tray_icon.StableWindowsMenu, FakeNativeIcon):
    pass


class MenuLifetimeTests(unittest.TestCase):
    def test_first_right_click_builds_menu_even_when_startup_update_is_pending(self):
        icon = SafeFakeIcon()
        icon._update_menu()  # pystray's startup _mark_ready call.
        self.assertIsNone(icon._menu_handle)
        self.assertEqual(icon.rebuilds, [])
        self.assertEqual(icon._on_notify(0, 0x0205), 'initial')
        self.assertEqual(icon.selected, 'initial callback')

    def test_background_rebuild_during_open_menu_preserves_handle_and_callbacks(self):
        icon = SafeFakeIcon()
        def worker_finishes():
            old_handle = icon._menu_handle
            icon.descriptor = 'updated'
            icon._update_menu()
            self.assertIs(icon._menu_handle, old_handle)
        icon.during_popup = worker_finishes
        icon._on_notify(0, 0x0205)
        self.assertEqual(icon.selected, 'initial callback')
        self.assertEqual(icon.rebuilds, ['initial'])
        icon.during_popup = lambda: None
        icon._on_notify(0, 0x0205)
        self.assertEqual(icon.selected, 'updated callback')
        self.assertEqual(icon.rebuilds, ['initial', 'updated'])

    def test_nested_right_click_cannot_destroy_open_menu(self):
        icon = SafeFakeIcon()
        icon.during_popup = lambda: icon._on_notify(0, 0x0205)
        icon._on_notify(0, 0x0205)
        self.assertEqual(icon.rebuilds, ['initial'])
        self.assertFalse(icon._native_menu_open)

    def test_other_notifications_are_forwarded(self):
        self.assertEqual(SafeFakeIcon()._on_notify(0, 0x0202), 'other notification')

    def test_menu_tracking_error_does_not_leave_open_flag_stuck(self):
        icon = SafeFakeIcon()
        icon.during_popup = Mock(side_effect=RuntimeError('popup failure'))
        with self.assertRaises(RuntimeError):
            icon._on_notify(0, 0x0205)
        self.assertFalse(icon._native_menu_open)
        icon.during_popup = lambda: None
        self.assertEqual(icon._on_notify(0, 0x0205), 'initial')

    def test_windows_factory_selects_safe_backend(self):
        with patch.object(tray_icon.sys, 'platform', 'win32'), \
             patch.object(tray_icon, 'pystray', types.SimpleNamespace(Icon=FakeNativeIcon)):
            icon = tray_icon.create_tray_icon()
        self.assertIsInstance(icon, tray_icon.StableWindowsMenu)

    def test_non_windows_factory_keeps_original_backend(self):
        backend = Mock()
        with patch.object(tray_icon.sys, 'platform', 'linux'), \
             patch.object(tray_icon, 'pystray', types.SimpleNamespace(Icon=backend)):
            result = tray_icon.create_tray_icon('name')
        backend.assert_called_once_with('name')
        self.assertIs(result, backend.return_value)


class UpdateCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tray = load_tray()

    def setUp(self):
        self.app = self.tray.BatteryTrayApp()
        self.app.icon = Mock()

    def check(self, tag=None, error=None, manual=True):
        response = Mock()
        response.status = 200
        response.read.return_value = ('{"tag_name": "' + (tag or '') + '", "html_url": "https://github.com/TristanSibug/mouse-battery-tray/releases"}').encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(self.tray.threading, 'Thread') as thread, \
             patch.object(self.tray.urllib.request, 'urlopen', return_value=response, side_effect=error):
            self.app.check_for_updates(manual=manual)
            self.assertEqual(self.app.update_status, 'checking')
            thread.call_args.kwargs['target']()

    def test_new_release_is_offered_without_installing(self):
        self.check(tag='v1.6.0')
        self.assertEqual(self.app.update_status, 'available')
        self.assertEqual(self.app.latest_version, 'v1.6.0')
        self.assertIn('New update', self.app.icon.notify.call_args.args[0])

    def test_current_version_message(self):
        self.check(tag=self.tray.__version__)
        self.assertEqual(self.app.update_status, 'up_to_date')
        self.assertIn('latest version', self.app.icon.notify.call_args.args[0])

    def test_missing_github_release_is_not_claimed_as_up_to_date(self):
        self.check(error=urllib.error.HTTPError('https://api.github.com', 404, 'Not Found', {}, None))
        self.assertEqual(self.app.update_status, 'no_release')
        self.assertIn('No published release', self.app.icon.notify.call_args.args[0])

    def test_network_failure_remains_retryable(self):
        self.check(error=OSError('network unavailable'))
        self.assertEqual(self.app.update_status, 'error')
        self.assertIn('Could not check', self.app.icon.notify.call_args.args[0])

    def test_second_check_does_not_spawn_duplicate_worker(self):
        self.app.update_status = 'checking'
        with patch.object(self.tray.threading, 'Thread') as thread:
            self.app.check_for_updates(manual=True)
        thread.assert_not_called()

    def test_startup_check_stays_silent_when_no_new_release(self):
        self.check(tag=self.tray.__version__, manual=False)
        self.app.icon.notify.assert_not_called()

    def test_app_run_uses_safe_icon_factory(self):
        with patch.object(self.tray, 'create_tray_icon') as factory:
            self.app.run()
        self.assertIs(self.app.icon, factory.return_value)
        factory.return_value.run.assert_called_once_with(setup=self.app._on_ready)


if __name__ == '__main__':
    unittest.main()
