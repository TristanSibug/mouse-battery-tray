"""Read display-name information only; never query or change a battery protocol."""
import re

import hid


def device_info(path):
    def text(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value)
    try:
        for device in hid.enumerate():
            if text(device['path']).casefold() == text(path).casefold():
                return device
    except OSError:
        pass
    return None


def specific_usb_name(info):
    name = ' '.join((info.get('product_string') or '').split())
    if not name or len(name) > 80:
        return None
    words = re.sub(r'2[.,]4\s*g(?:hz)?', '', name.lower())
    for word in ('usb', 'hid', 'wireless', 'wired', 'gaming', 'mouse', 'receiver', 'dongle', 'device', 'generic', 'optical'):
        words = re.sub(r'\b' + word + r'\b', '', words)
    return name if re.search(r'[a-z0-9]', words) else None


def identity(info, path):
    if info is None:
        return path
    serial = str(info.get('serial_number') or '').strip()
    if serial.lower() in ('0', '0000', '00000000', '1.00'):
        serial = ''
    return info['vendor_id'], info['product_id'], serial


def ask_device_name(current_name):
    # This function runs on its own UI thread, owning its Tk instance completely.
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        return simpledialog.askstring(
            'Fix generic device name',
            'Enter your mouse model name (80 characters maximum).\n\n'
            'This changes the displayed name only. It requires a working battery\n'
            'reading and cannot fix missing battery support.',
            initialvalue=current_name, parent=root,
        )
    finally:
        root.destroy()
