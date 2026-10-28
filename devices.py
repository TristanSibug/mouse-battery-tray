import time
import hid
from typing import Optional, Tuple, List

# =============================================================================
# Supported Standard Devices (Beken, CompX, Pulsar, etc.)
# =============================================================================
SUPPORTED_VIDS = {
    0x1D57,
    0x25A7,
    0x3710,
    0x258A,
    0x0C45,
    0x093A,
    0x24AE,
    0x1BCF,
    0x3554,
    0x320F,
    0x3537,
    0x3770,
    0x1532,
}

BEKEN_DEVICE_NAMES = {
    0x55: "Attack Shark X11",
    0x10: "Attack Shark R1",
    0x85: "Attack Shark X6",
    0x4D: "Attack Shark X3",
    0xBE: "Attack Shark X11 Pro",
    0x07: "Attack Shark X11 SE",
}

SUPPORTED_DEVICES = {
    # Attack Shark Series (Dynamic Device ID via packet)
    (0x1D57, 0xFA60): ("Attack Shark Mouse", "wireless"),
    (0x1D57, 0xFA55): ("Attack Shark X11", "wired"),
    0xFA60: ("Attack Shark Mouse", "wireless"),
    0xFA55: ("Attack Shark X11", "wired"),
    # Attack Shark R1
    (0x1D57, 0xFA61): ("Attack Shark R1", "wired"),
    0xFA61: ("Attack Shark R1", "wired"),
    # Attack Shark X3
    (0x1D57, 0xFA50): ("Attack Shark X3", "wired"),
    0xFA50: ("Attack Shark X3", "wired"),
    # Attack Shark X6
    (0x1D57, 0xFA62): ("Attack Shark X6", "wireless"),
    (0x1D57, 0xFA56): ("Attack Shark X6", "wired"),
    0xFA62: ("Attack Shark X6", "wireless"),
    0xFA56: ("Attack Shark X6", "wired"),
    # Pulsar Xlite / X2 Series (Thanks to u/djnemoson & TwistedVincenzo)
    # 2.4G RAKK Gahum (Compx): VID=0x25a7, PID=0xfa7c
    (0x25A7, 0xFA7C): ("RAKK Gahum", "wireless"),
    (0x25A7, 0xFA7B): ("Pulsar X2 / Xlite Series", "wired"),
    0xFA7C: ("RAKK Gahum", "wireless"),
    0xFA7B: ("Pulsar X2 / Xlite Series", "wired"),
    # Pulsar 8K Dongle Gen.2 (Thanks to @CptNinja)
    (0x3710, 0x5406): ("Pulsar 8K Dongle Gen.2", "wireless"),
    0x5406: ("Pulsar 8K Dongle Gen.2", "wireless"),
    # VXE R1 Series (R1 / SE / SE+) (Thanks to @nzeck1)
    (0x3554, 0xF58E): ("VXE R1 Series", "wireless"),
    (0x320F, 0x5055): ("VXE R1 Series", "wireless"),
    (0x3537, 0x2106): ("VXE R1 Series", "wireless"),
    0xF58E: ("VXE R1 Series", "wireless"),
    0x5055: ("VXE R1 Series", "wireless"),
    0x2106: ("VXE R1 Series", "wireless"),
    # Hitscan Hyperlight (Thanks to @Vinsmok3)
    (0x3770, 0x0300): ("Hitscan Hyperlight", "wireless"),
    0x0300: ("Hitscan Hyperlight", "wireless"),
    # Incott G24 Pro (Thanks to u/Monophonotronic)
    (0x093A, 0x522C): ("Incott G24 Pro", "wireless"),
    (0x093A, 0x622C): ("Incott G24 Pro", "wired"),
    0x522C: ("Incott G24 Pro", "wireless"),
    0x622C: ("Incott G24 Pro", "wired"),
    # Razer HyperPolling / Mouse Series (Thanks to u/MarcBelmaati)
    (0x1532, 0x00B3): ("Razer HyperPolling Dongle", "wireless"),
    (0x1532, 0x00A5): ("Razer Mouse", "wired"),
    0x00B3: ("Razer HyperPolling Dongle", "wireless"),
    0x00A5: ("Razer Mouse", "wired"),
}

# =============================================================================
# WLMouse Beast X family (Protocol reverse-engineering by @len0c)
# =============================================================================
WLMOUSE_VID = 0x36A7

WLMOUSE_DEVICES = {
    0xA887: "WLMouse Beast X",
    0xA868: "WLMouse Beast X Mini Pro",
}

WLMOUSE_QUERY = [0x00, 0x00, 0x02, 0x02, 0x00, 0x83]


def _wlmouse_parse(resp: List[int]) -> Tuple[Optional[int], Optional[bool]]:
    """Parse a data reply 'a1 00 02 02 00 83 <charge> <batt>' -> (batt, charging)."""
    if not resp:
        return None, None
    for i in range(5, len(resp) - 2):
        if (
            resp[i] == 0x83
            and resp[i - 1] == 0x00
            and resp[i - 2] == 0x02
            and resp[i - 5] in (0xA1, 0xA2)
        ):
            charge = resp[i + 1]
            batt = resp[i + 2]
            if 0 <= batt <= 100:
                return batt, bool(charge)
    return None, None


def _wlmouse_read_feature(path: str) -> Tuple[Optional[int], Optional[bool]]:
    """Active: replay the HUB's 0x83 read, poll the feature report for the reply."""
    try:
        dev = hid.device()
        dev.open_path(path.encode("utf-8") if isinstance(path, str) else path)
    except OSError:
        return None, None
    try:
        report = [0x00] + WLMOUSE_QUERY + [0x00] * (64 - len(WLMOUSE_QUERY))
        try:
            dev.send_feature_report(report)
        except OSError:
            pass
        for _ in range(15):
            time.sleep(0.05)
            for length in (65, 64):
                try:
                    resp = dev.get_feature_report(0, length)
                except OSError:
                    resp = None
                if resp:
                    batt, charging = _wlmouse_parse(list(resp))
                    if batt is not None:
                        return batt, charging
        return None, None
    finally:
        try:
            dev.close()
        except Exception:
            pass


def _wlmouse_read_passive(
    path: str, seconds: float = 6.0
) -> Tuple[Optional[int], Optional[bool]]:
    """Fallback: catch the '03 00 <batt> <charge>' heartbeat. No writes at all."""
    try:
        dev = hid.device()
        dev.open_path(path.encode("utf-8") if isinstance(path, str) else path)
        dev.set_nonblocking(True)
    except OSError:
        return None, None
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            try:
                data = dev.read(64)
            except OSError:
                break
            if data:
                d = list(data)
                for off in (0, 1):
                    if len(d) >= off + 4 and d[off] == 0x03 and d[off + 1] == 0x00:
                        batt = d[off + 2]
                        if 0 <= batt <= 100:
                            return batt, bool(d[off + 3])
            time.sleep(0.02)
    finally:
        try:
            dev.close()
        except Exception:
            pass
    return None, None


def find_wlmouse() -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Return (path, model_name, pid) for the WLMouse feature interface."""
    fallback = None
    for d in hid.enumerate(WLMOUSE_VID):
        pid = d["product_id"]
        name = WLMOUSE_DEVICES.get(pid) or d.get("product_string") or "WLMouse Device"
        if d.get("usage_page") == 0xFFFF and d.get("usage") == 0x00:
            return d["path"], name, pid
        if d.get("usage_page") == 0xFFFF and fallback is None:
            fallback = (d["path"], name, pid)
    return fallback if fallback else (None, None, None)


def read_wlmouse_battery(path: str) -> Tuple[Optional[int], Optional[bool]]:
    """Return (battery%, charging) or (None, None)."""
    batt, charging = _wlmouse_read_feature(path)
    if batt is not None:
        return batt, charging
    for d in hid.enumerate(WLMOUSE_VID):
        b, c = _wlmouse_read_passive(d["path"], seconds=4.0)
        if b is not None:
            return b, c
    return None, None


def find_device_path() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Scan HID devices for standard supported mice with prioritized endpoint matching."""
    p1_match = (
        None  # Interface 2 + usage_page 10 (Best match for Attack Shark X11/X6/X3/R1)
    )
    p2_match = None  # usage_page 10 or >= 0xff00 or interface 2
    p3_match = None  # interface 1
    fallback = None  # any matching VID endpoint

    for d in hid.enumerate():
        vid = d["vendor_id"]
        pid = d["product_id"]
        if vid in SUPPORTED_VIDS:
            prod_string = str(d.get("product_string", "")).lower()
            # Ignore keyboards, microphones, and audio peripherals sharing the same VID
            if any(
                k in prod_string
                for k in ["keyboard", "microphone", "audio", "headset", "sound"]
            ):
                continue

            if_num = d.get("interface_number", -1)
            usage_page = d.get("usage_page", 0)

            if (vid, pid) in SUPPORTED_DEVICES:
                model_name, mode = SUPPORTED_DEVICES[(vid, pid)]
            elif pid in SUPPORTED_DEVICES:
                model_name, mode = SUPPORTED_DEVICES[pid]
            else:
                mode = "wired" if "wired" in prod_string else "wireless"
                model_name = d.get("product_string", "Gaming Mouse")
                if model_name in ["2.4G Wireless Device", "2.4G Receiver"]:
                    model_name = "Wireless Mouse"

            item = (d["path"], mode, model_name)

            if if_num == 2 and usage_page == 10:
                p1_match = item
                break  # Perfect match — no need to scan further
            elif (
                usage_page == 10 or usage_page >= 0xFF00 or if_num == 2
            ) and p2_match is None:
                p2_match = item
            elif if_num == 1 and p3_match is None:
                p3_match = item
            elif fallback is None:
                fallback = item

        if p1_match:
            break

    if p1_match:
        return p1_match
    if p2_match:
        return p2_match
    if p3_match:
        return p3_match
    return fallback if fallback else (None, None, None)


# =============================================================================
# Razer Wireless Protocol (OpenRazer 90-Byte Feature Report Query)
# =============================================================================
RAZER_VID = 0x1532

RAZER_DEVICES = {
    0x00B3: "Razer HyperPolling Dongle",
    0x00A5: "Razer Mouse",
}


def _razer_crc(buf: List[int]) -> int:
    """Calculate Razer XOR checksum over bytes 2 to 88."""
    crc = 0
    for b in buf[2:89]:
        crc ^= b
    return crc


def _razer_get_battery_query() -> List[int]:
    """Construct 90-byte Razer 'Get Battery Level' Feature Report query."""
    buf = [0] * 90
    buf[0] = 0x00  # Report ID
    buf[1] = 0x00  # Status (New Command)
    buf[2] = 0x1F  # Transaction ID
    buf[3] = 0x00  # Data Length High
    buf[4] = 0x03  # Data Length Low
    buf[5] = 0x07  # Class: Battery
    buf[6] = 0x02  # Command: Get Battery Level
    buf[89] = _razer_crc(buf)
    return buf


def find_razer() -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Return (path, model_name, pid) for Razer feature interface."""
    fallback = None
    for d in hid.enumerate(RAZER_VID):
        pid = d["product_id"]
        name = RAZER_DEVICES.get(pid) or d.get("product_string") or "Razer Device"
        usage_page = d.get("usage_page", 0)
        usage = d.get("usage", 0)
        if usage_page == 0xFF00 or (usage_page == 0x0001 and usage in (0x02, 0x06)):
            return d["path"], name, pid
        if fallback is None:
            fallback = (d["path"], name, pid)
    return fallback if fallback else (None, None, None)


def read_razer_battery(path: str) -> Tuple[Optional[int], Optional[bool]]:
    """Active: query Razer 90-byte feature report for battery % and charging status."""
    try:
        dev = hid.device()
        dev.open_path(path.encode("utf-8") if isinstance(path, str) else path)
        dev.set_nonblocking(True)
    except OSError:
        return None, None

    try:
        query = _razer_get_battery_query()
        try:
            dev.send_feature_report(bytes(query))
        except OSError:
            try:
                dev.write(bytes(query))
            except OSError:
                pass

        time.sleep(0.05)
        for _ in range(5):
            try:
                resp = dev.get_feature_report(0, 90)
            except OSError:
                try:
                    resp = dev.read(90)
                except OSError:
                    resp = None

            if resp and len(resp) >= 10:
                d = list(resp)
                # Verify response header (Class 0x07, Command 0x02)
                for idx in range(len(d) - 9):
                    if (
                        d[idx + 1] in (0x02, 0x00)
                        and d[idx + 5] == 0x07
                        and d[idx + 6] == 0x02
                    ):
                        raw_batt = d[idx + 8]
                        charging_flag = d[idx + 9]
                        charging = bool(charging_flag in (1, 0x01))

                        if 0 <= raw_batt <= 100:
                            batt = raw_batt
                        elif 100 < raw_batt <= 255:
                            batt = int(round((raw_batt / 255.0) * 100))
                        else:
                            batt = None

                        if batt is not None:
                            return batt, charging
            time.sleep(0.03)
        return None, None
    finally:
        try:
            dev.close()
        except Exception:
            pass


# =============================================================================
# RAKK Gahum (Compx dongle) - battery is ASKED for, not just listened for
# Protocol found by capturing the RAKK software with USBPcap
# =============================================================================

# The vendor ID and product ID of the RAKK dongle (wireless mode)
RAKK_VID = 0x25A7
RAKK_PID = 0xFA7C


def find_rakk() -> Tuple[Optional[str], Optional[str]]:
    """Return (send_path, listen_path) for the RAKK dongle, or (None, None)."""
    # These will hold the two HID paths we need
    send_path = None  # the FF02 collection, where we write the request
    listen_path = None  # the FF01 collection, where the answer arrives

    # Look through every HID collection that belongs to the RAKK dongle
    for d in hid.enumerate(RAKK_VID, RAKK_PID):
        # Read the usage page and usage so we can tell the collections apart
        page = d.get("usage_page", 0)
        usage = d.get("usage", 0)
        # FF02 with usage 2 is where the RAKK software wrote its commands
        if page == 0xFF02 and usage == 0x0002:
            send_path = d["path"]
        # FF01 with usage 0 is where the battery answer showed up
        elif page == 0xFF01 and usage == 0x0000:
            listen_path = d["path"]

    # If we found both, return them. Otherwise report "not found".
    if send_path and listen_path:
        return send_path, listen_path
    return None, None


def read_rakk_battery(
    send_path: str, listen_path: str
) -> Tuple[Optional[int], Optional[bool]]:
    """Ask the dongle for the battery. Return (battery%, charging) or (None, None)."""
    # Open both collections. If Windows refuses, give up for this round.
    try:
        sender = hid.device()
        sender.open_path(send_path)
        listener = hid.device()
        listener.open_path(listen_path)
        # Non-blocking so read() returns right away instead of freezing
        listener.set_nonblocking(True)
    except OSError:
        return None, None

    try:
        # Throw away any old packets waiting in the listener
        for _ in range(20):
            if not listener.read(64):
                break

        # Build the 17-byte request: report ID 08, command 04, then zeros
        request = [0x08, 0x04] + [0x00] * 15
        # Last byte is the checksum: 0x55 minus the sum of the first 16 bytes
        request[16] = (0x55 - sum(request[:16])) & 0xFF
        # Send the request as a feature report
        sender.send_feature_report(request)

        # Wait up to about 2 seconds for the answer (40 tries x 0.05 s)
        for _ in range(40):
            time.sleep(0.05)
            data = listener.read(64)
            if data:
                d = list(data)
                # The answer starts with 09 04 (report ID 9, echo of command 4)
                if len(d) >= 8 and d[0] == 0x09 and d[1] == 0x04:
                    # Byte 6 is the battery percentage
                    battery = d[6]
                    # Only accept sensible values from 0 to 100
                    if 0 <= battery <= 100:
                        # Byte 7 is the charging flag: 00 = not charging, 01 = charging
                        # (found by comparing replies with the cable unplugged and plugged in)
                        charging = d[7] != 0
                        # Return the battery percentage and whether it is charging
                        return battery, charging
        # No valid answer in time
        return None, None
    except OSError:
        # Any read/write problem: treat it as "no reading this time"
        return None, None
    finally:
        # Always close both handles, even if something went wrong
        for dev in (sender, listener):
            try:
                dev.close()
            except Exception:
                pass
