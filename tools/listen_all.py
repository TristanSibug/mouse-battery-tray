# Import the hid library so we can talk to HID devices
import hid

# Import time so we can wait and measure seconds
import time

# The vendor ID of the RAKK mouse (Compx)
MY_VID = 0x25A7
# How many seconds we listen for packets
LISTEN_SECONDS = 40
# Max packets to print per interface (mouse movement would flood the screen otherwise)
MAX_PRINTS = 15

# This list will hold every interface we manage to open
opened = []
# This dictionary counts how many packets each interface has sent
counts = {}

# Go through every HID interface that has our vendor ID
for d in hid.enumerate(MY_VID):
    # Build a short label so we know which interface each packet came from
    label = (
        f"PID={d['product_id']:04X} "
        f"if={d.get('interface_number')} "
        f"page={d.get('usage_page', 0):04X} "
        f"usage={d.get('usage', 0):04X}"
    )
    # Try to open this interface
    try:
        dev = hid.device()
        # d["path"] is the address Windows gave this interface
        dev.open_path(d["path"])
        # Non-blocking means read() returns right away instead of waiting
        dev.set_nonblocking(True)
        # Remember it so we can read from it later
        opened.append((label, dev))
        # Start its packet counter at zero
        counts[label] = 0
        print("OPENED:", label)
    except OSError as e:
        # Some interfaces (like the plain mouse one) can't be opened by Windows rules
        print("FAILED:", label, "->", e)

print()
print("Listening for", LISTEN_SECONDS, "seconds.")
print("Do this now: switch the mouse OFF then ON, press the DPI button,")
print("and unplug/replug the dongle. Avoid moving the mouse a lot.")
print()

# Work out when we should stop listening
end_time = time.time() + LISTEN_SECONDS

# Keep looping until time runs out
while time.time() < end_time:
    # Check every opened interface one by one
    for label, dev in opened:
        # Try to read up to 64 bytes
        try:
            data = dev.read(64)
        except OSError:
            # If the read fails, just skip this interface this time
            continue
        # If we actually got bytes (empty means nothing arrived)
        if data:
            # Count this packet for this interface
            counts[label] += 1
            # Only print the first few so the screen stays readable
            if counts[label] <= MAX_PRINTS:
                # Turn each byte into 2-digit hex, e.g. 03 55 40 01 4b
                hex_text = " ".join(f"{b:02x}" for b in data)
                print(label, "|", hex_text)
    # Short pause so we don't hog the CPU
    time.sleep(0.01)

# Print how many packets each interface sent in total
print()
print("Total packets per interface:")
for label, count in counts.items():
    print(" ", label, "->", count)

# Close everything politely
for label, dev in opened:
    dev.close()
