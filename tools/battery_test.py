# Import the hid library so we can talk to HID devices
import hid

# Import time so we can wait for the mouse to answer
import time

# The vendor ID of the RAKK mouse (Compx)
MY_VID = 0x25A7

# Find the interface with usage page FF02 (the one that held report 8)
target_path = None
for d in hid.enumerate(MY_VID):
    # We want usage page 0xFF02 and usage 0x0002
    if d.get("usage_page") == 0xFF02 and d.get("usage") == 0x0002:
        target_path = d["path"]
        break

# If we did not find it, tell the user and stop
if target_path is None:
    print("Could not find the FF02 interface. Is the dongle plugged in?")
    raise SystemExit

# Open that interface
dev = hid.device()
dev.open_path(target_path)
# Non-blocking means read() returns right away if nothing has arrived
dev.set_nonblocking(True)

# Build the 17-byte request: report ID 08, command 04, then zeros
request = [0x08, 0x04] + [0x00] * 15
# The last byte is the checksum: 0x55 minus the sum of the first 16 bytes
request[16] = (0x55 - sum(request[:16])) & 0xFF
# Print the request so we can compare it with the capture (should end in 49)
print("Sending:", " ".join(f"{b:02x}" for b in request))

# Send the request as a feature report (same as the RAKK software did)
dev.send_feature_report(request)

# Wait up to 2 seconds for the answer to arrive
end_time = time.time() + 2
got_answer = False
while time.time() < end_time:
    # Try to read up to 64 bytes
    data = dev.read(64)
    # If something arrived
    if data:
        # Turn it into a list and print it as hex
        d = list(data)
        print("Received:", " ".join(f"{b:02x}" for b in d))
        # Look for the pattern 09 04 (report ID 9, echo of command 4)
        for i in range(len(d) - 6):
            if d[i] == 0x09 and d[i + 1] == 0x04:
                # The battery value is 6 bytes after the report ID
                print("Battery:", d[i + 6], "%")
                got_answer = True
                break
    # Stop looping once we decoded an answer
    if got_answer:
        break
    # Short pause so we don't hog the CPU
    time.sleep(0.02)

# If nothing came back, say so
if not got_answer:
    print("No battery answer received.")

# Close the interface politely
dev.close()
