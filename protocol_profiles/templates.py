"""Fixed battery templates shared by investigator validation and tray polling.

No request bytes, code, offsets, DLLs or executable paths come from JSON.
"""
import time

import hid

from .schema import valid_binding


def parse_report(template, payload):
    data = list(payload)
    if template == 'rakk-v1':
        if len(data) >= 8 and data[:2] == [9, 4] and 1 <= data[6] <= 100:
            return data[6], bool(data[7])
    elif template in ('beken-v1', 'compx-v1'):
        if len(data) >= 5 and data[0] == 3 and data[2] == 0x40:
            from protocols.utils import parse_battery_telemetry
            return parse_battery_telemetry(data, data[1], is_beken=template == 'beken-v1')
        if template == 'compx-v1' and len(data) >= 6 and data[:3] == [6, 0, 0] and data[3] in (0, 1, 2, 3, 0x80) and 0 <= data[4] <= 100:
            return data[4], data[3] in (2, 3, 0x80)
    elif template == 'razer-v1':
        from protocols.razer import _razer_crc
        if len(data) == 91 and data[0] == 0:
            data = data[1:]
        if len(data) == 90 and data[0] == 2 and data[5:8] == [2, 7, 2] and data[88] == _razer_crc(data) and data[8] > 0 and data[9] in (0, 1):
            return round(data[8] * 100 / 255), bool(data[9])
    elif template == 'wlmouse-v1':
        from protocols.wlmouse import _wlmouse_parse
        if any(data[i:i+6] in ([0xA1, 0, 2, 2, 0, 0x83], [0xA2, 0, 2, 2, 0, 0x83]) for i in range(max(0, len(data) - 7))):
            return _wlmouse_parse(data)
    return None, None


def resolve_bindings(profile):
    if not valid_binding(profile):
        raise ValueError('Unsupported binding. No HID request was sent.')
    endpoints = hid.enumerate(profile['vid'], profile['pid'])
    resolved, selected = {}, []
    for role, selector in profile['interfaces'].items():
        matches = {d['path']: d for d in endpoints if all(d.get(k, -1 if k == 'interface_number' else 0) == v for k, v in selector.items())}
        if len(matches) != 1:
            raise ValueError('HID interface missing or ambiguous. Connect only the intended mouse/receiver and retry.')
        device = next(iter(matches.values()))
        resolved[role] = device['path']
        selected.append(device)
    serials = {str(d.get('serial_number') or '').strip() for d in selected}
    serials -= {'', '0', '0000', '00000000', '1.00'}
    if len(serials) > 1:
        raise ValueError('The selected HID interfaces belong to different receivers.')
    return resolved


def read_sample(profile, timeout=3):
    paths = resolve_bindings(profile)
    template, variant = profile['template'], profile['variant']
    if template == 'rakk-v1':
        from protocols.rakk import read_rakk_battery
        deadline = time.monotonic() + timeout
        return read_rakk_battery(paths['primary'], paths['reply'], lambda: time.monotonic() >= deadline)
    device = hid.device()
    try:
        path = paths['primary']
        device.open_path(path.encode('utf-8') if isinstance(path, str) else path)
        device.set_nonblocking(True)
        if template in ('razer-v1', 'wlmouse-v1'):
            if template == 'razer-v1':
                from protocols.razer import _razer_get_battery_query
                queries = [_razer_get_battery_query(tx) for tx in (0x1F, 0x3F, 0xFF)]
                lengths = (91, 90)
            else:
                from protocols.wlmouse import WLMOUSE_QUERY
                queries = [bytes([0] + WLMOUSE_QUERY + [0] * (64 - len(WLMOUSE_QUERY)))]
                lengths = (65, 64)
            deadline = time.monotonic() + timeout
            for query in queries:
                if time.monotonic() >= deadline:
                    break
                device.send_feature_report(query)
                for _ in range(10):
                    if time.monotonic() >= deadline:
                        break
                    for length in lengths:
                        try:
                            reading = parse_report(template, device.get_feature_report(0, length))
                            if reading[0] is not None:
                                return reading
                        except OSError:
                            pass
                    time.sleep(0.05)
            return None, None
        if variant.startswith('query06-'):
            query = bytes(([0, 6] + [0] * 62) if variant.endswith('report0') else ([6] + [0] * 63))
            device.send_feature_report(query)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if template == 'compx-v1' and variant != 'passive':
                for report_id in (6, 0):
                    try:
                        reading = parse_report(template, device.get_feature_report(report_id, 64))
                        if reading[0] is not None:
                            return reading
                    except OSError:
                        pass
            try:
                reading = parse_report(template, device.read(64))
                if reading[0] is not None:
                    return reading
            except OSError:
                return None, None
            time.sleep(0.02)
        return None, None
    finally:
        try:
            device.close()
        except OSError:
            pass
