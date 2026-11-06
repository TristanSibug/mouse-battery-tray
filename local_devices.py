"""Discover compatible HID mice and persist a user-local device selection.

The frozen executable cannot rewrite its bundled Python modules. This file is
the runtime equivalent of adding a mapping, without changing installed code.
"""
import json
import os
from pathlib import Path
import tempfile
import time

import hid
import devices


def settings_path():
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".config") / "MouseBatteryTray" / "device.json"


def _valid(profile):
    if not isinstance(profile, dict):
        return False
    if profile.get("protocol") not in ("standard", "wlmouse", "razer", "rakk"):
        return False
    if not isinstance(profile.get("name"), str) or not profile["name"].strip():
        return False
    for key in ("vid", "pid", "usage_page", "usage"):
        if type(profile.get(key)) is not int or not 0 <= profile[key] <= 65535:
            return False
    if type(profile.get("interface")) is not int:
        return False
    # Active queries are restricted to the vendor/protocol they were written for.
    protocol = profile["protocol"]
    return (
        protocol == "standard"
        or protocol == "wlmouse" and profile["vid"] == devices.WLMOUSE_VID
        or protocol == "razer" and profile["vid"] == devices.RAZER_VID
        or protocol == "rakk" and (profile["vid"], profile["pid"]) == (devices.RAKK_VID, devices.RAKK_PID)
    )


def load_profile():
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        profile = data.get("device") if data.get("version") == 1 else None
        return profile if _valid(profile) else None
    except (OSError, ValueError, AttributeError):
        return None


def save_profile(profile):
    if not _valid(profile):
        raise ValueError("Invalid device profile")
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            temporary = out.name
            json.dump({"version": 1, "device": profile}, out, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def resolve_profile(profile, endpoints=None):
    """Re-resolve paths after a restart/replug; never persist volatile HID paths."""
    if endpoints is None:
        endpoints = hid.enumerate(profile["vid"], profile["pid"])
    matches = [d for d in endpoints if
               d["vendor_id"] == profile["vid"] and d["product_id"] == profile["pid"]]
    if profile["protocol"] == "rakk":
        sender = next((d["path"] for d in matches if d.get("usage_page") == 0xFF02 and d.get("usage") == 2), None)
        listener = next((d["path"] for d in matches if d.get("usage_page") == 0xFF01 and d.get("usage") == 0), None)
        return (sender, listener) if sender and listener else (None, None)
    for d in matches:
        if (d.get("interface_number", -1), d.get("usage_page", 0), d.get("usage", 0)) == (
            profile["interface"], profile["usage_page"], profile["usage"]
        ):
            return d["path"], None
    return None, None


def read_standard_battery(path, seconds=2.0):
    """Listen only: don't send guessed feature commands to unknown hardware."""
    dev = hid.device()
    try:
        dev.open_path(path)
        dev.set_nonblocking(True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            data = dev.read(64)
            # Require the known battery-report signature, not a mouse input report.
            if len(data) >= 5 and data[0] == 3 and data[2] == 0x40 and 0 <= data[4] <= 100:
                battery = data[4]
                if data[1] == 0x85 and 0 < battery <= 10:
                    battery *= 10
                charging = data[3] in (2, 3, 0x80)
                if data[1] in devices.BEKEN_DEVICE_NAMES:
                    charging = charging or any(data[5:8])
                return battery, bool(charging)
            time.sleep(0.02)
        return None, None
    finally:
        dev.close()


def detect_mouse(cancelled=lambda: False):
    """Return the first battery-verified profile and reading, or (None, None, None).

    Only vendor endpoints of mouse-like devices are probed. Unknown vendors get
    passive reads only. Detection is bounded, and runs on the existing HID worker.
    """
    endpoints = hid.enumerate()
    mouse_ids = {(d["vendor_id"], d["product_id"]) for d in endpoints
                 if d.get("usage_page") == 1 and d.get("usage") == 2}
    deadline = time.monotonic() + 15
    for d in endpoints:
        if cancelled() or time.monotonic() >= deadline:
            break
        vid, pid = d["vendor_id"], d["product_id"]
        product = d.get("product_string") or ""
        if any(word in product.lower() for word in ("keyboard", "microphone", "audio", "headset")):
            continue
        if (vid, pid) not in mouse_ids and "mouse" not in product.lower() and vid not in devices.SUPPORTED_VIDS | {devices.WLMOUSE_VID}:
            continue
        page = d.get("usage_page", 0)
        # Never interpret ordinary keyboard/movement reports as battery packets.
        razer_feature = vid == devices.RAZER_VID and page == 1 and d.get("usage") in (2, 6)
        if page < 0xFF00 and page != 10 and not razer_feature:
            continue
        protocol = "standard"
        if vid == devices.WLMOUSE_VID:
            protocol = "wlmouse"
        elif vid == devices.RAZER_VID:
            protocol = "razer"
        elif (vid, pid) == (devices.RAKK_VID, devices.RAKK_PID) and page == 0xFF02:
            protocol = "rakk"
        profile = {"vid": vid, "pid": pid, "name": product or "Wireless Mouse",
                   "protocol": protocol, "interface": d.get("interface_number", -1),
                   "usage_page": page, "usage": d.get("usage", 0)}
        path, listener = resolve_profile(profile, endpoints)
        if path is None:
            continue
        try:
            if protocol == "wlmouse":
                battery, charging = devices._wlmouse_read_feature(path)
            elif protocol == "razer":
                battery, charging = devices.read_razer_battery(path)
            elif protocol == "rakk":
                battery, charging = devices.read_rakk_battery(path, listener)
            else:
                battery, charging = read_standard_battery(path)
        except OSError:
            continue
        if battery is not None:
            return profile, battery, bool(charging)
    return None, None, None
