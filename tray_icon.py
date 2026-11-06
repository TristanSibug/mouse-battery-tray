"""Keep a Windows popup menu alive until its interaction has finished."""
import sys

import pystray


class StableWindowsMenu:
    # WM_RBUTTONUP, the notification pystray uses to open its Windows menu.
    _RIGHT_BUTTON_UP = 0x0205

    def _update_menu(self):
        """Defer native rebuilds requested by workers or menu callbacks.

        pystray's Windows backend destroys the previous HMENU in this method.
        Doing that from the update/battery worker while TrackPopupMenuEx owns
        it breaks hover highlighting and selection. The descriptor still gets
        updated by the public menu setter; materialize it at the next open.
        """
        if not hasattr(self, '_menu_handle'):
            self._menu_handle = None

    def _on_notify(self, wparam, lparam):
        if lparam != self._RIGHT_BUTTON_UP:
            return super()._on_notify(wparam, lparam)
        if getattr(self, '_native_menu_open', False):
            return  # A second right-click must not replace the tracked menu.
        self._native_menu_open = True
        try:
            # Runs on the Windows event-loop thread before tracking starts.
            # The base handler retains this menu's callback table until close.
            super()._update_menu()
            return super()._on_notify(wparam, lparam)
        finally:
            self._native_menu_open = False


def create_tray_icon(*args, **kwargs):
    if sys.platform == 'win32':
        # Scope the private-backend override to Windows. Other platforms retain
        # their existing pystray implementation and public update behavior.
        class WindowsIcon(StableWindowsMenu, pystray.Icon):
            pass
        return WindowsIcon(*args, **kwargs)
    return pystray.Icon(*args, **kwargs)
