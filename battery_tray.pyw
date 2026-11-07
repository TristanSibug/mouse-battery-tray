import sys

# The diagnostic helper owns its own Tk UI and does not start another tray or
# acquire the app mutex. This branch also works inside the frozen executable.
if __name__ == '__main__' and sys.argv[1:] == ['--usb-investigation']:
    from usb_investigation.wizard import main as investigation_main
    raise SystemExit(investigation_main())

import time
import threading
import urllib.request
import json
import webbrowser
import ctypes
from typing import Optional, Tuple, List

import pystray
from tray_icon import create_tray_icon
from device_names import device_info, specific_usb_name, identity, ask_device_name
from usb_investigation.capture import launch_helper

from config import (
    trim_memory,
    acquire_single_instance,
    is_startup_enabled,
    set_startup,
    get_alert_threshold,
    set_alert_threshold,
    get_show_estimate,
    set_show_estimate,
    is_light_mode,
    get_battery_history,
    get_device_name,
    set_device_name,
    set_battery_history,
)
from updater import (
    __version__,
    GITHUB_REPO_URL,
    GITHUB_RELEASES_API,
    GITHUB_RELEASES_URL,
    is_newer_version,
)
from protocols import get_all_handlers
from icon_drawer import get_icon_data


# =============================================================================
# Tray Application
# =============================================================================
class BatteryTrayApp:
    def __init__(self):
        self.icon = None
        self.running = True
        self.last_battery = -1
        self.status = "disconnected"
        self.charging = False
        self.current_model = "Mouse"
        self._stop_requested = threading.Event()
        self._poll_wakeup = threading.Event()
        self._capture_pause = threading.Event()
        self._protocol_idle = threading.Event()
        self._protocol_idle.set()
        self._capture_lock = threading.Lock()
        self._name_fix_lock = threading.Lock()
        self._active_device_info = None
        self._last_battery_read_at = 0
        self._display_alias = None

        # Alert threshold & state (saved in registry)
        self.alert_threshold: int = get_alert_threshold()
        self.has_alerted: bool = False

        # Hours Estimate state (saved in registry)
        self.show_estimate: bool = get_show_estimate()
        saved_history, saved_anchored = get_battery_history()
        self.battery_history: List[Tuple[float, int]] = saved_history
        self.is_anchored: bool = saved_anchored

        # Update checker state
        self.latest_version: Optional[str] = None
        self.update_url: str = GITHUB_RELEASES_URL
        self.update_status: str = (
            "idle"  # idle | checking | available | up_to_date | error
        )
        self.last_update_check_time: float = time.time()

        # Icon caching, theme & polling state
        self.last_theme: bool = is_light_mode()
        self._icon_cache = {}
        self.poll_thread = threading.Thread(target=self.poll_loop, daemon=True)

    def check_for_updates(self, manual: bool = False):
        """Asynchronously fetch the latest release tag from GitHub."""
        if self.update_status == "checking":
            return
        self.update_status = "checking"
        if self.icon:
            self.icon.menu = self.create_menu()

        def _worker():
            try:
                req = urllib.request.Request(
                    GITHUB_RELEASES_API,
                    headers={"User-Agent": "MouseBatteryTray-UpdateChecker"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        tag_name = data.get("tag_name", "")
                        html_url = data.get("html_url", GITHUB_RELEASES_URL)
                        self.update_url = html_url
                        if tag_name and is_newer_version(tag_name, __version__):
                            self.latest_version = tag_name
                            self.update_status = "available"
                        else:
                            self.update_status = "up_to_date"
                    else:
                        self.update_status = "error"
            except urllib.error.HTTPError as e:
                # Tags alone are not published GitHub Releases.
                if e.code == 404:
                    self.update_status = "no_release"
                else:
                    self.update_status = "error"
            except Exception:
                self.update_status = "error"

            if self.icon:
                self.icon.menu = self.create_menu()
                if manual:
                    if self.update_status == "no_release":
                        try:
                            self.icon.notify(
                                "No published release was found on GitHub. No update was installed.",
                                "Mouse Battery Tray",
                            )
                        except Exception:
                            pass
                    elif self.update_status == "up_to_date":
                        try:
                            self.icon.notify(
                                f"You are on the latest version ({__version__}).",
                                "Mouse Battery Tray",
                            )
                        except Exception:
                            pass
                    elif self.update_status == "error":
                        try:
                            self.icon.notify(
                                "Could not check for updates. Please try again later.",
                                "Mouse Battery Tray",
                            )
                        except Exception:
                            pass
                if self.update_status == "available":
                    try:
                        self.icon.notify(
                            f"New update {self.latest_version} available! Click menu to download.",
                            "Mouse Battery Tray",
                        )
                    except Exception:
                        pass
            trim_memory()

        threading.Thread(target=_worker, daemon=True).start()

    def open_update_url(self, icon, item):
        webbrowser.open(self.update_url)

    def open_repo_url(self, icon, item):
        webbrowser.open(GITHUB_REPO_URL)

    def on_check_updates_click(self, icon, item):
        self.check_for_updates(manual=True)

    def toggle_show_estimate(self, icon, item):
        self.show_estimate = not self.show_estimate
        set_show_estimate(self.show_estimate)
        self.update_tray()
        if self.icon:
            self.icon.menu = self.create_menu()

    def set_threshold(self, threshold: int):
        self.alert_threshold = threshold
        set_alert_threshold(threshold)
        if self.alert_threshold == 0 or self.last_battery > self.alert_threshold:
            self.has_alerted = False
        if self.icon:
            self.icon.menu = self.create_menu()

    def get_battery_estimate_str(self) -> Optional[str]:
        if not self.show_estimate or self.charging or self.last_battery <= 0:
            return None

        if len(self.battery_history) < 2:
            return None

        now = time.time()
        # Retain one anchor before the 48-hour window: slow mice may take
        # several hours to lose even one percent.
        recent_history = self._recent_history(now)
        if len(recent_history) < 2:
            return None

        t_first, b_first = recent_history[0]
        t_last, b_last = recent_history[-1]

        time_span = t_last - t_first
        pct_drop = b_first - b_last

        if time_span < 30 or pct_drop <= 0:
            return None

        drain_rate = pct_drop / time_span
        if drain_rate <= 0:
            return None

        remaining_seconds = self.last_battery / drain_rate
        hours = int(remaining_seconds // 3600)
        minutes = int((remaining_seconds % 3600) // 60)

        if hours >= 1:
            return f"~{hours}h {minutes}m" if minutes > 0 else f"~{hours}h"
        elif minutes > 0:
            return f"~{minutes}m"
        else:
            return "~<1m"

    def _recent_history(self, now):
        history = [(t, b) for t, b in self.battery_history if t <= now]
        first_recent = next((i for i, (t, _) in enumerate(history) if now - t <= 172800), len(history))
        return history[max(0, first_recent - 1):]

    def estimate_status(self):
        if self.status in ("disconnected", "unknown") or self.last_battery < 0:
            return "waiting for battery"
        if self.charging:
            return "paused while charging"
        estimate = self.get_battery_estimate_str()
        if estimate:
            return estimate
        return ("learning (needs battery drop)" if len(self.battery_history) < 2
                else "learning (needs more discharge data)")

    def can_fix_device_name(self):
        return (self.status in ("connected", "charging") and self.last_battery >= 0
                and self._active_device_info is not None
                and time.time() - self._last_battery_read_at <= 180)

    def on_fix_device_name(self, icon, item):
        if not self.can_fix_device_name():
            self._name_notice("A detected battery level is required. Renaming cannot fix missing battery support.")
            return
        if not self._name_fix_lock.acquire(blocking=False):
            return
        info = dict(self._active_device_info)
        path = self._active_device_path
        current_name = self.current_model
        def worker():
            try:
                # Read descriptors from this mouse only; do not run battery queries.
                connected = device_info(path)
                if connected is None or identity(connected, path) != identity(info, path):
                    self._name_notice("The mouse disconnected. Try again after its battery reading returns.")
                    return
                name = specific_usb_name(connected)
                if name is None:
                    name = ask_device_name(current_name)
                if name is None:
                    return  # Dialog cancelled.
                name = ' '.join(name.split())
                if not 0 < len(name) <= 80:
                    self._name_notice("Enter a model name between 1 and 80 characters.")
                    return
                if not self.can_fix_device_name() or self._active_device_path != path:
                    self._name_notice("The active mouse changed. Try again when its battery reading returns.")
                    return
                if not set_device_name(info['vendor_id'], info['product_id'], name):
                    self._name_notice("Could not save the device name. Your previous name was kept.")
                    return
                self._display_alias = name
                self.update_tray()
                self._name_notice(f"Displayed name saved: {name}. Battery support is unchanged.")
            except Exception as exc:
                self._name_notice(f"Could not change the displayed name: {exc}")
            finally:
                self._name_fix_lock.release()
        threading.Thread(target=worker, daemon=True).start()

    def _name_notice(self, message):
        if self.icon and self.running:
            try:
                self.icon.notify(message, "Fix Generic Device Name")
            except Exception:
                pass

    def update_battery_level(self, battery: int, charging: bool = False):
        self.last_battery = battery
        self.charging = charging
        self.status = "charging" if charging else "connected"

        now = time.time()
        first_read = not hasattr(self, '_last_update_call')
        time_since_last_poll = now - getattr(self, "_last_update_call", now)
        self._last_update_call = now
        pc_slept = time_since_last_poll > 1800

        if charging:
            self.battery_history = []
            self.is_anchored = False
        elif battery >= 0:
            # Missing polls invalidate the observed discharge interval, even if
            # the device reports the same percentage after waking.
            if pc_slept or (first_read and self.battery_history and now - self.battery_history[-1][0] > 172800):
                self.battery_history = []
            if not self.battery_history:
                self.battery_history = [(now, battery)]
            elif battery > self.battery_history[-1][1]:
                self.battery_history = [(now, battery)]
            elif battery < self.battery_history[-1][1]:
                self.battery_history.append((now, battery))
            self.battery_history = self._recent_history(now)
            self.is_anchored = len(self.battery_history) >= 2
        # Save on changes, not on every 100ms HID poll.
        history_state = (tuple(self.battery_history), self.is_anchored)
        if history_state != getattr(self, '_saved_history_state', None):
            set_battery_history(self.battery_history, self.is_anchored)
            self._saved_history_state = history_state

        self.update_tray()

        # Trigger Low Battery Toast Notification if below threshold
        threshold = self.alert_threshold
        if threshold > 0 and not charging:
            if battery <= threshold and not self.has_alerted:
                self.has_alerted = True
                if self.icon:
                    try:
                        model = self._display_alias or self.current_model or "Mouse"
                        self.icon.notify(
                            f"{model} battery level is low ({battery}%). Please connect charger.",
                            "Low Battery Alert",
                        )
                    except Exception:
                        pass
            elif battery > threshold + 5:
                self.has_alerted = False
        elif charging:
            self.has_alerted = False

    def on_investigate_mouse(self, icon, item):
        if sys.platform != 'win32':
            self._investigation_notice('Live USB capture requires Windows and USBPcap.')
            return
        if not self._capture_lock.acquire(blocking=False):
            return
        self._capture_pause.set()
        self._poll_wakeup.set()
        self.update_tray()
        def worker():
            try:
                if not self._protocol_idle.wait(timeout=15):
                    raise RuntimeError('The current HID operation did not release its handle. Close the app and run battery_tray.exe --usb-investigation directly.')
                if not self.running:
                    return
                helper = launch_helper()
                code = helper.wait()
                if code and self.running:
                    self._investigation_notice('The investigation window exited unexpectedly. Battery polling has resumed.')
            except Exception as exc:
                self._investigation_notice(f'Could not open USB investigation: {exc}')
            finally:
                self._capture_pause.clear()
                if self.running:
                    self._poll_wakeup.clear()
                self._capture_lock.release()
                self.update_tray()
        threading.Thread(target=worker, daemon=True).start()

    def _investigation_notice(self, message):
        if self.icon and self.running:
            try:
                self.icon.notify(message, 'Assisted USB Investigation')
            except Exception:
                pass

    def create_menu(self) -> pystray.Menu:
        items = []
        if self.update_status == "available" and self.latest_version:
            items.append(
                pystray.MenuItem(
                    f"🚀 Update Available ({self.latest_version})", self.open_update_url
                )
            )
            items.append(pystray.Menu.SEPARATOR)

        def _make_threshold_item(val: int, label: str):
            return pystray.MenuItem(
                label,
                lambda icon, item: self.set_threshold(val),
                checked=lambda item: self.alert_threshold == val,
                radio=True,
            )

        threshold_menu = pystray.Menu(
            _make_threshold_item(25, "25%"),
            _make_threshold_item(20, "20% (Default)"),
            _make_threshold_item(15, "15%"),
            _make_threshold_item(10, "10%"),
            pystray.Menu.SEPARATOR,
            _make_threshold_item(0, "Disabled"),
        )

        items.append(
            pystray.MenuItem(
                "Start with Windows",
                self.toggle_startup,
                checked=lambda item: is_startup_enabled(),
            )
        )
        items.append(
            pystray.MenuItem(
                "Show Hours Estimate",
                self.toggle_show_estimate,
                checked=lambda item: self.show_estimate,
            )
        )
        if self.show_estimate:
            items.append(pystray.MenuItem(
                lambda item: "Hours estimate: " + self.estimate_status(), None, enabled=False,
            ))
        items.append(pystray.MenuItem(
            "Fix Generic Device Name", self.on_fix_device_name,
            enabled=lambda item: self.can_fix_device_name(),
        ))
        if not self.can_fix_device_name():
            items.append(pystray.MenuItem("Name fix requires a detected battery level", None, enabled=False))
        items.append(pystray.MenuItem("Low Battery Alert", threshold_menu))
        items.append(pystray.MenuItem(
            'USB investigation in progress...' if self._capture_lock.locked() else 'Investigate Unsupported Mouse...',
            self.on_investigate_mouse,
            enabled=lambda item: sys.platform == 'win32' and not self._capture_lock.locked(),
        ))

        if self.update_status == "checking":
            items.append(
                pystray.MenuItem("🔄 Checking for updates...", None, enabled=False)
            )
        else:
            items.append(
                pystray.MenuItem("Check for Updates", self.on_check_updates_click)
            )

        items.append(pystray.Menu.SEPARATOR)
        items.append(
            pystray.MenuItem(f"Mouse Battery Tray {__version__}", self.open_repo_url)
        )
        items.append(pystray.MenuItem("Exit", self.on_exit, enabled=lambda item: not self._capture_lock.locked()))
        return pystray.Menu(*items)

    def update_tray(self):
        if not self.icon:
            return

        menu_state = (self.can_fix_device_name(), self.estimate_status(), self._capture_lock.locked())
        if menu_state != getattr(self, '_last_menu_state', None):
            self._last_menu_state = menu_state
            self.icon.menu = self.create_menu()
        self.last_theme = is_light_mode()
        self.icon.icon = get_icon_data(self.status, self.last_battery, self._icon_cache)

        model = self._display_alias or self.current_model or "Mouse"
        if self._capture_pause.is_set():
            self.icon.title = f'{model[:64]}: Battery polling paused for USB investigation'
        elif self.status == "disconnected":
            self.icon.title = f"{model}: Disconnected"
        elif self.status == "connected" and self.last_battery < 0:
            self.icon.title = f"{model}: Waiting for battery reading..."
        elif self.status == "charging" and self.last_battery < 0:
            self.icon.title = f"{model}: Charging/Wired"
        elif self.status == "charging":
            self.icon.title = f"{model}: {self.last_battery}% (charging)"
        elif self.status == "unknown":
            self.icon.title = f"{model}: detected (battery unavailable)"
        else:
            est_str = self.get_battery_estimate_str()
            if est_str:
                self.icon.title = f"{model}: {self.last_battery}% ({est_str})"
            elif self.show_estimate:
                self.icon.title = f"{model[:64]}: {self.last_battery}% (estimating...)"
            else:
                self.icon.title = f"{model}: {self.last_battery}%"

    def update_device_state(self, path, model_name, battery, charging=False, activity=False):
        """Bridge protocol updates to the tray, alerts, and discharge history."""
        previous_path = getattr(self, "_active_device_path", None)
        if previous_path != path or self._active_device_info is None:
            info = device_info(path)
            key = identity(info, path)
            previous_key = getattr(self, '_active_device_key', previous_path)
            if previous_key is not None and previous_key != key:
                self.battery_history = []
                self.is_anchored = False
                self.has_alerted = False
            self._active_device_path = path
            self._active_device_key = key
            self._active_device_info = info
            self._display_alias = get_device_name(info['vendor_id'], info['product_id']) if info else None
        self.current_model = model_name
        if battery >= 0:
            self._last_battery_read_at = time.time()
        if battery < 0:
            self.last_battery = battery
            self.charging = charging
            self.status = "charging" if charging else "unknown"
            self.update_tray()
        else:
            self.update_battery_level(battery, charging)

    def polling_active(self):
        if not self.running or self._stop_requested.is_set() or self._capture_pause.is_set():
            return False
        now = time.time()
        if now - getattr(self, "_last_trim", now) > 60:
            trim_memory()
            self._last_trim = now
        if is_light_mode() != self.last_theme:
            self.update_tray()
        if now - self.last_update_check_time >= 86400:
            self.last_update_check_time = now
            self.check_for_updates(manual=False)
        return True

    def wait_for_poll(self, seconds):
        self._poll_wakeup.wait(seconds)

    def poll_loop(self):
        self._last_trim = time.time()
        while self.running:
            if self._capture_pause.is_set():
                self._protocol_idle.set()
                self._stop_requested.wait(0.1)
                continue
            if not self.polling_active():
                continue
            handled = False
            for handler in get_all_handlers():
                path, mode, model_name = handler.find_device()
                if path:
                    self._protocol_idle.clear()
                    try:
                        if not self.polling_active():
                            break
                        handler.handle_device(self, path, mode, model_name)
                    finally:
                        self._protocol_idle.set()
                    handled = True
                    break
            if not handled:
                if self.status != "disconnected":
                    self.status = "disconnected"
                    self.update_tray()
                self.wait_for_poll(5)

    def on_exit(self, icon, item):
        if self._capture_lock.locked():
            self._investigation_notice('Close the USB investigation window to stop capture before exiting the tray.')
            return
        self.running = False
        self._stop_requested.set()
        self._poll_wakeup.set()
        self.icon.stop()

    def toggle_startup(self, icon, item):
        new_state = not item.checked
        set_startup(new_state)

    """
    def run(self):
        self.icon = pystray.Icon(
            "Mouse Battery Tray",
            get_icon_data(self.status, self.last_battery, self._icon_cache),
            "Mouse Battery Tray: Initializing...",
            self.create_menu(),
        )

        self.poll_thread.start()
        self.check_for_updates(manual=False)
        self.icon.run()
    """

    def _on_ready(self, icon):
        # pystray calls this once the tray icon exists and is ready
        # Make sure the icon is visible before we start changing it
        icon.visible = True
        # Only now start the thread that reads the battery
        self.poll_thread.start()
        # Check for updates once at startup (same as before)
        self.check_for_updates(manual=False)

    def run(self):
        # Create the tray icon with the starting "??" image and menu (unchanged)
        self.icon = create_tray_icon(
            "Mouse Battery Tray",
            get_icon_data(self.status, self.last_battery, self._icon_cache),
            "Mouse Battery Tray: Initializing...",
            self.create_menu(),
        )
        # Run the icon, and ask pystray to call _on_ready when it is ready
        # (this replaces the old poll_thread.start() and check_for_updates lines)
        self.icon.run(setup=self._on_ready)


if __name__ == "__main__":
    if not acquire_single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "Mouse Battery Tray is already running in the notification area.",
                "Mouse Battery Tray",
                0x40,  # MB_ICONINFORMATION
            )
        except Exception:
            pass
        sys.exit(0)
    app = BatteryTrayApp()
    app.run()
