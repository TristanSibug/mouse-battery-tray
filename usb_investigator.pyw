"""Standalone USB Investigation entry point; independent of the battery tray."""
from usb_investigation.wizard import main

if __name__ == '__main__':
    raise SystemExit(main())
