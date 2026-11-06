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
from protocols import get_all_handlers
from protocols.beken import BekenProtocol, BEKEN_VIDS
from protocols.compx import CompxProtocol, COMPX_VIDS
from protocols.razer import RazerProtocol, RAZER_VID
from protocols.wlmouse import WLMouseProtocol, WLMOUSE_VID
from protocols.rakk import RakkProtocol, RAKK_VID, RAKK_PID, find_rakk_pairs
from protocols.utils import parse_battery_telemetry


def settings_path():
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".config") / "MouseBatteryTray" / "device.json"


def _valid(profile):
    if not isinstance(profile, dict):
        return False
    if profile.get("protocol") not in ("standard", "beken", "compx", "wlmouse", "razer", "rakk"):
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
        or protocol == "beken" and profile["vid"] in BEKEN_VIDS
        or protocol == "compx" and profile["vid"] in COMPX_VIDS
        or protocol == "wlmouse" and profile["vid"] == WLMOUSE_VID
        or protocol == "razer" and profile["vid"] == RAZER_VID
        or protocol == "rakk" and (profile["vid"], profile["pid"]) == (RAKK_VID, RAKK_PID)
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
        pairs = find_rakk_pairs(matches)
        return pairs[0] if pairs else (None, None)
    for d in matches:
        if (d.get("interface_number", -1), d.get("usage_page", 0), d.get("usage", 0)) == (
            profile["interface"], profile["usage_page"], profile["usage"]
        ):
            return d["path"], None
    return None, None


class LocalStandardProtocol(CompxProtocol):
    """Runtime mapping for unknown vendors: canonical packets, no active writes."""
    canonical_only = True
    allow_queries = False

    def __init__(self, profile):
        self.profile = profile
        self.supported_vids = {profile["vid"]}
        self.supported_devices = {(profile["vid"], profile["pid"]): (profile["name"], "wireless")}

    def find_all_devices(self):
        path, _ = resolve_profile(self.profile)
        return [(path, "wireless", self.profile["name"])] if path else []


def profile_handler(profile):
    protocol = profile["protocol"]
    if protocol == "standard":  # Migrate profiles written before the protocol refactor.
        if profile["vid"] in BEKEN_VIDS:
            protocol = "beken"
        elif profile["vid"] in COMPX_VIDS:
            protocol = "compx"
        else:
            return LocalStandardProtocol(profile)
    return {"beken": BekenProtocol, "compx": CompxProtocol,
            "razer": RazerProtocol, "wlmouse": WLMouseProtocol,
            "rakk": RakkProtocol}[protocol]()


class _BatteryProbe:
    """Run an existing handler until its first accepted battery reading."""
    def __init__(self, deadline, cancelled):
        self.deadline = deadline
        self.cancelled = cancelled
        self.running = True
        self.status = "disconnected"
        self.last_battery = -1
        self.current_model = "Mouse"
        self.reading = (None, None)

    def polling_active(self):
        return self.running and not self.cancelled() and time.monotonic() < self.deadline

    def wait_for_poll(self, seconds):
        until = min(self.deadline, time.monotonic() + seconds)
        while self.polling_active() and time.monotonic() < until:
            time.sleep(min(0.02, max(0, until - time.monotonic())))

    def update_tray(self):
        pass

    def update_device_state(self, path, model_name, battery, charging=False, activity=False):
        if battery >= 0:
            self.reading = (battery, bool(charging))
            self.running = False


def probe_handler(handler, path, mode, name, cancelled, deadline):
    probe = _BatteryProbe(min(deadline, time.monotonic() + 3), cancelled)
    handler.handle_device(probe, path, mode, name)
    return probe.reading


def read_standard_battery(path, seconds=2.0):
    """Listen only: don't send guessed feature commands to unknown hardware."""
    dev = hid.device()
    try:
        dev.open_path(path)
        dev.set_nonblocking(True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            data = dev.read(64)
            if len(data) >= 5 and data[0] == 3 and data[2] == 0x40:
                reading = parse_battery_telemetry(list(data), data[1])
                if reading[0] is not None:
                    return reading
            time.sleep(0.02)
        return None, None
    finally:
        dev.close()


def _profile(endpoint, protocol, name):
    return {"vid": endpoint["vendor_id"], "pid": endpoint["product_id"], "name": name,
            "protocol": protocol, "interface": endpoint.get("interface_number", -1),
            "usage_page": endpoint.get("usage_page", 0), "usage": endpoint.get("usage", 0)}


def detect_mouse(cancelled=lambda: False):
    """Verify using current protocol handlers; fall back to passive unknown OEMs."""
    endpoints = hid.enumerate()
    deadline = time.monotonic() + 15
    protocols = {"BekenProtocol": "beken", "CompxProtocol": "compx",
                 "WLMouseProtocol": "wlmouse", "RazerProtocol": "razer", "RakkProtocol": "rakk"}
    for handler in get_all_handlers():
        for path, mode, name in handler.find_all_devices():
            if cancelled() or time.monotonic() >= deadline:
                return None, None, None
            # A cable connection without a battery reply is not a verified setup.
            if mode == "wired":
                continue
            endpoint = next((d for d in endpoints if d["path"] == path), None)
            if endpoint is None:
                continue
            try:
                battery, charging = probe_handler(handler, path, mode, name, cancelled, deadline)
            except OSError:
                continue
            if battery is not None:
                return _profile(endpoint, protocols[type(handler).__name__], name), battery, bool(charging)

    mouse_ids = {(d["vendor_id"], d["product_id"]) for d in endpoints
                 if d.get("usage_page") == 1 and d.get("usage") == 2}
    known_vids = BEKEN_VIDS | COMPX_VIDS | {RAZER_VID, WLMOUSE_VID}
    for d in endpoints:
        if cancelled() or time.monotonic() >= deadline:
            break
        vid, pid = d["vendor_id"], d["product_id"]
        if vid in known_vids:
            continue  # Don't bypass the known handler's stricter validation.
        product = d.get("product_string") or ""
        if any(word in product.lower() for word in ("keyboard", "microphone", "audio", "headset")):
            continue
        if (vid, pid) not in mouse_ids and "mouse" not in product.lower():
            continue
        page = d.get("usage_page", 0)
        if page < 0xFF00 and page != 10:
            continue
        try:
            battery, charging = read_standard_battery(d["path"], min(2, max(0, deadline - time.monotonic())))
        except OSError:
            continue
        if battery is not None:
            return _profile(d, "standard", product or "Wireless Mouse"), battery, bool(charging)
    return None, None, None
