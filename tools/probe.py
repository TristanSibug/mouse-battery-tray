# Import the hid library so we can talk to HID devices
import hid

# Import time so we can wait and measure seconds
import time

# The vendor ID of the RAKK mouse (Compx)
MY_VID = 0x25A7
# How many seconds we listen for packets
LISTEN_SECONDS = 20

# This list will hold (label, device) pairs for every interface we open
opened = []
# This dictionary counts packets per interface
counts = {}

# Go through every HID interface with our vendor ID
for d in hid.enumerate(MY_VID):
    # Build a short label so we know which interface is which
    label = (
        f"if={d.get('interface_number')} "
        f"page={d.get('usage_page', 0):04X} "
        f"usage={d.get('usage', 0):04X}"
    )
    # Try to open this interface
    try:
        dev = hid.device()
        dev.open_path(d["path"])
        dev.set_nonblocking(True)
        opened.append((label, dev, d.get("usage_page", 0)))
        counts[label] = 0
    except OSError as e:
        print("FAILED:", label, "->", e)

# ---------- PART 1: read-only feature report probe ----------
print("PART 1: asking each vendor interface for feature reports (read-only)")
for label, dev, page in opened:
    # Only probe vendor-specific pages (0xFF00 and above)
    if page < 0xFF00:
        continue
    # Try report IDs 0 to 16
    for report_id in range(0, 17):
        try:
            # Ask for up to 65 bytes of this feature report
            data = dev.get_feature_report(report_id, 65)
        except OSError:
            # This report ID isn't supported here, skip it
            continue
        # If something came back, print it as hex
        if data:
            hex_text = " ".join(f"{b:02x}" for b in data)
            print(label, "| report", report_id, "|", hex_text)

# ---------- PART 2: passive listening with the mouse moving ----------
print()
print("PART 2: listening", LISTEN_SECONDS, "seconds.")
print("MOVE THE MOUSE and click buttons now. Do NOT unplug anything.")
end_time = time.time() + LISTEN_SECONDS
while time.time() < end_time:
    for label, dev, page in opened:
        try:
            data = dev.read(64)
        except OSError:
            continue
        if data:
            counts[label] += 1
            # Print only the first 5 packets per interface
            if counts[label] <= 5:
                hex_text = " ".join(f"{b:02x}" for b in data)
                print(label, "|", hex_text)
    time.sleep(0.01)

# Print the packet totals
print()
print("Total packets per interface:")
for label, count in counts.items():
    print(" ", label, "->", count)

# Close everything
for label, dev, page in opened:
    dev.close()
