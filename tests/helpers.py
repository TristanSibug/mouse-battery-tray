"""Platform-isolated fixtures for HID and Windows tray tests."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import time
import types
from unittest.mock import Mock, patch


def endpoint(vid=0x9999, pid=1, page=0xFF01, usage=1, path=b"vendor"):
    return dict(vendor_id=vid, product_id=pid, product_string="Test Mouse",
                interface_number=2, usage_page=page, usage=usage, path=path, serial_number="test-device")


def enumeration(endpoints):
    def enumerate_devices(vid=0, pid=0):
        return [d for d in endpoints if (not vid or d['vendor_id'] == vid)
                and (not pid or d['product_id'] == pid)]
    return enumerate_devices


class TestApp:
    """Bounded protocol runner; stops when a real handler accepts a reading."""
    def __init__(self, seconds=1):
        self.deadline = time.monotonic() + seconds
        self.running = True
        self.status = 'disconnected'
        self.last_battery = -1
        self.current_model = 'Mouse'
        self.reading = (None, None)

    def polling_active(self):
        return self.running and time.monotonic() < self.deadline

    def wait_for_poll(self, seconds):
        if self.polling_active():
            time.sleep(min(seconds, max(0, self.deadline - time.monotonic())))

    def update_tray(self):
        pass

    def update_device_state(self, path, model_name, battery, charging=False, activity=False):
        if battery >= 0:
            self.reading = battery, bool(charging)
            self.last_battery = battery
            self.running = False


def load_tray():
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
    tray = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"config": config, "pystray": Mock(), "icon_drawer": Mock()}):
        loader.exec_module(tray)
    return tray
