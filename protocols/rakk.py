"""RAKK Gahum's report-08 battery query, separate from generic CompX polling."""
import time

import hid

from .base import ProtocolHandler, get_physical_device_key, polling_active, wait_for_poll

RAKK_VID = 0x25A7
RAKK_PID = 0xFA7C  # Also used by Pulsar: IDs alone must never select this protocol.


def find_rakk_pairs(endpoints=None):
    groups = {}
    for d in hid.enumerate() if endpoints is None else endpoints:
        if (d['vendor_id'], d['product_id']) != (RAKK_VID, RAKK_PID):
            continue
        group = groups.setdefault(get_physical_device_key(d), {})
        if d.get('usage_page') == 0xFF02 and d.get('usage') == 2:
            group['sender'] = d['path']
        elif d.get('usage_page') == 0xFF01 and d.get('usage') == 0:
            group['listener'] = d['path']
    return [(g['sender'], g['listener']) for g in groups.values()
            if 'sender' in g and 'listener' in g]


def read_rakk_battery(sender_path, listener_path, cancelled=lambda: False):
    opened = []
    try:
        for path in (sender_path, listener_path):
            dev = hid.device()
            opened.append(dev)
            dev.open_path(path.encode('utf-8') if isinstance(path, str) else path)
            dev.set_nonblocking(True)
        sender, listener = opened
        for _ in range(20):
            if not listener.read(64):
                break
        request = [0x08, 0x04] + [0] * 15
        request[16] = (0x55 - sum(request[:16])) & 0xFF
        sender.send_feature_report(request)
        for _ in range(40):
            if cancelled():
                break
            time.sleep(0.05)
            data = listener.read(64)
            if len(data) >= 8 and data[0] == 9 and data[1] == 4 and 1 <= data[6] <= 100:
                return data[6], bool(data[7])
    except OSError:
        pass
    finally:
        for dev in opened:
            try:
                dev.close()
            except OSError:
                pass
    return None, None


class RakkProtocol(ProtocolHandler):
    def __init__(self):
        self._first_reading = {}

    def find_all_devices(self):
        return [(sender, 'wireless', 'RAKK Gahum') for sender, _ in find_rakk_pairs()]

    def find_device(self):
        # A valid RAKK reply distinguishes OEM receivers sharing Pulsar's IDs.
        for sender, listener in find_rakk_pairs():
            battery, charging = read_rakk_battery(sender, listener)
            if battery is not None:
                self._first_reading[sender] = (battery, charging)
                return sender, 'wireless', 'RAKK Gahum'
        return None, None, None

    def handle_device(self, app, path, mode, model_name):
        while polling_active(app):
            listener = next((other for sender, other in find_rakk_pairs() if sender == path), None)
            if listener is None:
                break
            reading = self._first_reading.pop(path, None)
            if reading is None:
                reading = read_rakk_battery(path, listener, lambda: not polling_active(app))
            battery, charging = reading
            if battery is not None:
                app.update_device_state(path, model_name, battery, charging=bool(charging), activity=True)
            else:
                app.current_model = model_name
                app.status = 'unknown'
                app.update_tray()
            wait_for_poll(app, 60 if battery is not None else 10)
