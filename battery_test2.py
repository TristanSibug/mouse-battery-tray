# Import the hid library so we can talk to HID devices
import hid

# Import time so we can wait for the mouse to answer
import time

# The vendor ID of the RAKK mouse (Compx)
MY_VID = 0x25A7

# This will hold the device we send the request through (FF02)
sender = None
# This list will hold (label, device) for every vendor collection we listen on
listeners = []

# Go through every HID collection of the dongle
for d in hid.enumerate(MY_VID):
    # Read the usage page and usage so we can label and filter it
    page = d.get("usage_page", 0)
    usage = d.get("usage", 0)
    # We only care about vendor-specific pages (0xFF00 and above)
    if page < 0xFF00:
        continue
    # Make a short label such as "FF03/0000"
    label = f"{page:04X}/{usage:04X}"
    # Try to open this collection
    try:
        dev = hid.device()
        dev.open_path(d["path"])
        # Non-blocking so read() returns right away
        dev.set_nonblocking(True)
    except OSError as e:
        print("Could not open", label, "->", e)
        continue
    # Add it to the list of devices we will listen on
    listeners.append((label, dev))
    # Remember the FF02 one, because that is where the software sent commands
    if page == 0xFF02 and usage == 0x0002:
        sender = dev

# If we never found FF02, stop here
if sender is None:
    print("Could not find the FF02 interface. Is the dongle plugged in?")
    raise SystemExit

# Build the 17-byte request: report ID 08, command 04, then zeros
request = [0x08, 0x04] + [0x00] * 15
# The last byte is the checksum: 0x55 minus the sum of the first 16 bytes
request[16] = (0x55 - sum(request[:16])) & 0xFF
# Print the request (it should end in 49, like the capture)
print("Sending:", " ".join(f"{b:02x}" for b in request))
# Send it as a feature report through FF02
sender.send_feature_report(request)

# Remember which listeners already failed so we only print the error once
failed = set()
# Remember whether we decoded a battery value
got_answer = False
# Listen for up to 3 seconds
end_time = time.time() + 3

while time.time() < end_time and not got_answer:
    # Check every collection one by one
    for label, dev in listeners:
        # Skip collections that already gave a read error
        if label in failed:
            continue
        # Try to read up to 64 bytes from this collection
        try:
            data = dev.read(64)
        except OSError:
            # This collection has no input reports, so ignore it from now on
            failed.add(label)
            continue
        # If something arrived, show where it came from
        if data:
            d = list(data)
            print("Received on", label, ":", " ".join(f"{b:02x}" for b in d))
            # Look for 09 04 (report ID 9 and the echo of command 4)
            for i in range(len(d) - 6):
                if d[i] == 0x09 and d[i + 1] == 0x04:
                    # The battery value is 6 bytes after the report ID
                    print("Battery:", d[i + 6], "%")
                    got_answer = True
                    break
    # Short pause so we don't hog the CPU
    time.sleep(0.02)

# Say which collections had no input reports (useful to know)
print("Collections with no readable input:", sorted(failed))
# If nothing came back, say so
if not got_answer:
    print("No battery answer received.")

# Close everything politely
for label, dev in listeners:
    dev.close()
