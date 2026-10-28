# Import the hid library so we can talk to HID devices
import hid

# Import time so we can pause between reads
import time

# The vendor ID of the RAKK mouse (Compx)
MY_VID = 0x25A7

# This will hold the path (address) of the interface we want
target_path = None

# Look through every interface of the mouse
for d in hid.enumerate(MY_VID):
    # We want the one with usage page FF04 (the one that answered with report 6)
    if d.get("usage_page") == 0xFF04:
        # Remember its path and stop looking
        target_path = d["path"]
        break

# If we didn't find it, tell the user and stop
if target_path is None:
    print("Could not find the FF04 interface. Is the dongle plugged in?")
    raise SystemExit

# Open that interface
dev = hid.device()
dev.open_path(target_path)

# This remembers the last reading so we only print when it changes
last = None

print("Reading report 6 every 2 seconds. Press Ctrl+C to stop.")
print(
    "Try: switching the mouse off/on, plugging in its charging cable, using it for a while."
)

# Keep reading until the user presses Ctrl+C
try:
    while True:
        # Ask the dongle for feature report 6 (read-only, nothing is written)
        data = dev.get_feature_report(6, 65)
        # Turn the bytes into a list so we can compare them easily
        current = list(data)
        # Only print when something is different from last time
        if current != last:
            # Show the bytes as 2-digit hex
            print(time.strftime("%H:%M:%S"), " ".join(f"{b:02x}" for b in current))
            # Save this reading for the next comparison
            last = current
        # Wait 2 seconds before asking again
        time.sleep(2)
except KeyboardInterrupt:
    # Ctrl+C was pressed, so we just fall out of the loop
    pass

# Close the interface politely
dev.close()
