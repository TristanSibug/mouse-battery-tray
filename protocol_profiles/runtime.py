"""Tray adapter for local verified bindings, with fallback to built-in handlers."""
import logging
import time

from protocols.base import ProtocolHandler, polling_active, wait_for_poll
from .templates import resolve_bindings, read_sample


class ProfileProtocol(ProtocolHandler):
    def __init__(self, profile):
        self.profile = profile
        self.cooldown_until = 0

    def find_device(self):
        if time.monotonic() < self.cooldown_until:
            return None, None, None
        try:
            path = resolve_bindings(self.profile)['primary']
            return path, 'wireless', self.profile['name']
        except (OSError, ValueError):
            return None, None, None

    def handle_device(self, app, path, mode, model_name):
        missed = 0
        while polling_active(app):
            try:
                battery, charging = read_sample(self.profile)
            except (OSError, ValueError):
                battery, charging = None, None
            if battery is None:
                missed += 1
                app.current_model = model_name
                app.status = 'unknown'
                app.update_tray()
                if missed >= 3:
                    self.cooldown_until = time.monotonic() + 60
                    logging.getLogger(__name__).warning('Local profile unavailable; trying built-in handlers: %s', model_name)
                    return
                wait_for_poll(app, 1)
            else:
                missed = 0
                app.update_device_state(path, model_name, battery, charging=bool(charging), activity=True)
                wait_for_poll(app, 10 if self.profile['variant'] != 'passive' else 1)
