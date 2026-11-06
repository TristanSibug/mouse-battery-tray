"""RAKK Gahum's report-08 battery query, separate from generic CompX polling."""
import time

import hid

from .base import ProtocolHandler, get_physical_device_key, polling_active, wait_for_poll

RAKK_VID = 0x25A7
RAKK_PID = 0xFA7C  # Also used by Pulsar: IDs alone must never select this protocol.


def find_rakk_pairs(endpoints=None):
    groups = {}
    senders, listeners = {}, {}
    for d in hid.enumerate() if endpoints is None else endpoints:
        if (d['vendor_id'], d['product_id']) != (RAKK_VID, RAKK_PID):
            continue
        group = groups.setdefault(get_physical_device_key(d), {})
        if d.get('usage_page') == 0xFF02 and d.get('usage') == 2:
            group['sender'] = d['path']
            senders[d['path']] = d
        elif d.get('usage_page') == 0xFF01 and d.get('usage') == 0:
            group['listener'] = d['path']
            listeners[d['path']] = d
    pairs = [(g['sender'], g['listener']) for g in groups.values()
             if 'sender' in g and 'listener' in g]
    # Separate Windows USB interfaces can have different instance paths even
    # though they belong to one dongle. The original working scanner paired
    # these by their FF02/2 and FF01/0 roles. Retain that behavior when there is
    # exactly one possible pair; never guess between multiple receivers.
    if not pairs and len(senders) == len(listeners) == 1:
        sender = next(iter(senders.values()))
        listener = next(iter(listeners.values()))
        def serial(device):
            value = str(device.get('serial_number') or '').strip().lower()
            return '' if value in ('0', '00000000', '1.00', '0000') else value
        left, right = serial(sender), serial(listener)
        if not (left and right and left != right):
            pairs.append((sender['path'], listener['path']))
    return pairs


def read_rakk_battery(sender_path, listener_path, cancelled=lambda: False):
    opened = []
    try:
        for path in (sender_path, listener_path):
            dev = hid.device()
            opened.append(dev)
            dev.open_path(path.encode('utf-8') if isinstance(path, str) else path)
        sender, listener = opened
        listener.set_nonblocking(True)
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
    def find_all_devices(self):
        return [(sender, 'wireless', 'RAKK Gahum') for sender, _ in find_rakk_pairs()]

    def handle_device(self, app, path, mode, model_name):
        while polling_active(app):
            listener = next((other for sender, other in find_rakk_pairs() if sender == path), None)
            if listener is None:
                break
            # Discovery is based on the interface pair, like the working main
            # branch. A sleeping dongle or initial 0% reply must stay here and
            # retry, rather than becoming a Pulsar in the generic CompX loop.
            battery, charging = read_rakk_battery(path, listener, lambda: not polling_active(app))
            if battery is not None:
                app.update_device_state(path, model_name, battery, charging=bool(charging), activity=True)
            else:
                app.current_model = model_name
                app.status = 'unknown'
                app.update_tray()
            wait_for_poll(app, 60 if battery is not None else 10)
