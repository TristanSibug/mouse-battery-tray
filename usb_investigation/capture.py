"""USBPcap discovery and bounded, local capture sessions.

Options verified against USBPcapCMD/cmd.c in the official desowin/usbpcap
repository. USBPcapCMD handles its own UAC elevation; no driver is bundled.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

import hid

from .pcap import MAX_CAPTURE_BYTES, analyze_capture


def _options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def find_usbpcap():
    candidates = []
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'):
        if os.environ.get(variable):
            root = Path(os.environ[variable])
            candidates += [root / 'USBPcap/USBPcapCMD.exe', root / 'Wireshark/extcap/USBPcapCMD.exe']
    resolved = shutil.which('USBPcapCMD.exe')
    if resolved:
        candidates.append(Path(resolved))
    return next((str(p) for p in candidates if p.is_file()), '')


def hid_mice():
    grouped = {}
    devices = hid.enumerate()
    mouse_ids = {(d['vendor_id'], d['product_id']) for d in devices
                 if d.get('usage_page') == 1 and d.get('usage') == 2}
    for d in devices:
        product = d.get('product_string') or 'Unnamed HID device'
        key = d['vendor_id'], d['product_id']
        if key not in mouse_ids and not any(word in product.lower() for word in ('mouse', 'receiver', 'dongle')):
            continue
        group = grouped.setdefault(key, {'vid': key[0], 'pid': key[1], 'product': product,
            'manufacturer': d.get('manufacturer_string') or '', 'interfaces': []})
        interface = {k: d.get(k) for k in ('interface_number', 'usage_page', 'usage')}
        if interface not in group['interfaces']:
            group['interfaces'].append(interface)
    # Do not export HID paths or serial numbers. Exact USB address selection is
    # separate; identical VID/PID devices must be distinguished by their USB port.
    return list(grouped.values())


def _fields(line):
    return dict(re.findall(r'\{([\w-]+)=([^}]*)\}', line))


def valid_controller(value):
    return bool(re.fullmatch(r'\\\\\.\\USBPcap[0-9]+', value))


def parse_interfaces(output):
    result = []
    for line in output.splitlines():
        fields = _fields(line)
        if line.startswith('interface ') and valid_controller(fields.get('value', '')):
            result.append({'controller': fields['value'], 'label': fields.get('display', fields['value'])})
    return result


def parse_devices(output):
    entries = [_fields(line) for line in output.splitlines() if line.startswith('value ')]
    result = []
    for entry in entries:
        value = entry.get('value', '')
        if not value.isdecimal() or not 1 <= int(value) <= 127 or entry.get('enabled') != 'true':
            continue
        children = [e.get('display', '') for e in entries if e.get('value', '').startswith(value + '_')]
        result.append({'address': int(value), 'label': entry.get('display', value), 'interfaces': children})
    return result


def _metadata(executable, args):
    result = subprocess.run([str(executable), *args], capture_output=True, timeout=20, **_options())
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-1500:] or 'USBPcap discovery failed.')
    return result.stdout.decode('utf-8', errors='replace')


def list_targets(executable):
    targets = []
    for interface in parse_interfaces(_metadata(executable, ['--extcap-interfaces'])):
        output = _metadata(executable, ['--extcap-interface', interface['controller'], '--extcap-config'])
        targets.extend({**interface, **device} for device in parse_devices(output))
    return targets


def capture_command(executable, controller, address, destination):
    if not valid_controller(controller) or type(address) is not int or not 1 <= address <= 127:
        raise ValueError('Choose a USBPcap controller and exactly one USB device address (1–127).')
    return [str(executable), '-d', controller, '--devices', str(address), '--inject-descriptors',
            '-s', '65535', '-o', str(destination)]


class CaptureSession:
    def __init__(self, output_root, device, target, manufacturer_software, duration=60):
        if type(duration) is not int or not 10 <= duration <= 120:
            raise ValueError('Capture duration must be between 10 and 120 seconds.')
        self.directory = Path(output_root) / ('usb-investigation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.device = device
        self.target = target
        self.duration = duration
        self.process = None
        self.started = None
        self.launched = None
        self.finished = False
        self.finalized = False
        self.log = None
        self.labels = []
        self.manifest = {'schema_version': 1, 'purpose': 'Evidence collection only; no protocol changes',
            'created_utc': datetime.now(timezone.utc).isoformat(), 'hid_device': device,
            'usb_target': target, 'manufacturer_software': manufacturer_software.strip()[:120],
            'duration_limit_seconds': duration, 'status': 'created', 'observations': self.labels}
        self._save()

    def _save(self):
        path = self.directory / 'session.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    def start(self, executable):
        if self.process is not None or self.finished:
            raise RuntimeError('Create a new session for each capture attempt.')
        # A hot-plug can change USB addresses: confirm that selection still exists.
        capture_command(executable, self.target['controller'], self.target['address'], self.directory / 'capture.raw.pcap')
        targets = parse_devices(_metadata(executable, ['--extcap-interface', self.target['controller'], '--extcap-config']))
        if not any(t['address'] == self.target['address'] for t in targets):
            raise ValueError('The selected USB device disappeared. Refresh and choose its current address.')
        command = capture_command(executable, self.target['controller'], self.target['address'], self.directory / 'capture.raw.pcap')
        self.log = (self.directory / 'usbpcap.log').open('wb')
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT, **_options())
        except Exception:
            self.log.close()
            self.log = None
            self.manifest['status'] = 'start_failed'
            self._save()
            raise
        self.launched = time.monotonic()
        self.manifest['status'] = 'waiting_for_capture'
        self._save()

    def tick(self):
        if self.process is None or self.finished:
            return self.manifest['status']
        raw = self.directory / 'capture.raw.pcap'
        size = raw.stat().st_size if raw.exists() else 0
        if self.started is None and size >= 24:
            self.started = time.monotonic()
            self.manifest['status'] = 'capturing'
            self.manifest['capture_started_utc'] = datetime.now(timezone.utc).isoformat()
            self._save()
        if self.process.poll() is not None:
            self.stop('capture_process_exited')
        elif size >= MAX_CAPTURE_BYTES - 1048576:
            self.stop('size_limit')
        elif self.started is not None and time.monotonic() - self.started >= self.duration:
            self.stop('duration_limit')
        elif self.started is None and time.monotonic() - self.launched >= 60:
            self.stop('startup_timeout')
        return self.manifest['status']

    def observe(self, battery_percent, charging, note=''):
        if self.started is None or self.finished or self.process is None or self.process.poll() is not None:
            raise ValueError('Wait for capture to start before recording an observation.')
        if type(battery_percent) is not int or not 0 <= battery_percent <= 100 or type(charging) is not bool:
            raise ValueError('Enter a battery percentage from 0 to 100 and select the charging state.')
        if len(self.labels) >= 100:
            raise ValueError('This session already has 100 observations. Finish it and start another.')
        stamp = time.time()
        self.labels.append({'timestamp': stamp, 'timestamp_utc': datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
            'battery_percent': battery_percent, 'charging': charging, 'note': note.strip()[:200]})
        self._save()

    def stop(self, reason='user_stopped'):
        if self.finished:
            return
        forced = False
        if self.process is not None and self.process.poll() is None:
            # USBPcap's 'q' control uses ReadConsoleInput, not a stdin pipe. Its
            # own job object owns any elevated worker. Stop the owned process;
            # validate a complete-record review copy rather than claiming an
            # interrupted last write is a clean capture.
            self.process.terminate()
            forced = True
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        # Never let the UI close/finalize as if capture stopped when terminating
        # the owned process raised an error or timed out.
        self.finished = True
        if self.log:
            self.log.close()
            self.log = None
        self.manifest.update(status='stopped', stop_reason=reason, process_terminated=forced,
            process_exit_code=self.process.poll() if self.process else None,
            capture_stopped_utc=datetime.now(timezone.utc).isoformat())
        self._save()

    def finalize(self):
        if not self.finished:
            raise RuntimeError('Stop capture before creating a review bundle.')
        if self.finalized:
            raise RuntimeError('This session has already been finalized.')
        self.finalized = True
        try:
            summary = analyze_capture(self.directory / 'capture.raw.pcap', self.directory / 'capture.pcap',
                self.target['address'], self.labels, (self.device['vid'], self.device['pid']))
        except (OSError, ValueError) as exc:
            self.manifest.update(status='capture_invalid', error=str(exc))
            self._save()
            raise ValueError(f'{exc} The local session and USBPcap log were kept for diagnosis.') from exc
        self.manifest['status'] = 'evidence_collected' if summary['device_identity'] == 'matched' else 'selection_needs_review'
        self.manifest['analysis_summary'] = {k: summary[k] for k in ('packets', 'device_identity', 'sha256', 'partial_tail')}
        self._save()
        (self.directory / 'analysis.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        report = ["# Assisted USB investigation", '', '**Evidence only: no battery protocol was added or verified.**', '',
            f"Selected HID device: {self.device['product']} ({self.device['vid']:04x}:{self.device['pid']:04x})",
            f"USB address: {self.target['address']}; descriptor identity: {summary['device_identity']}",
            f"Complete selected-device packets: {summary['packets']}", f"Labelled observations: {len(self.labels)}", '',
            '## Limitations', *['- ' + value for value in summary['limitations']], '',
            'The raw capture was stopped by the app and may end mid-record. capture.pcap contains only validated complete records for the selected address.', '',
            '## Review', 'Open capture.pcap in Wireshark. Compare timestamps with session.json observations. '
            'analysis.json contains bounded payload examples, paired control requests/responses, and possible byte correlations. '
            'These hints can be coincidental; validate across more battery levels and charging states before implementing support.', '',
            '**Review before sharing:** USB packets can include input reports, device descriptors and identifying data. '
            'Nothing is uploaded automatically. The review ZIP excludes the raw capture and USBPcap log.', '']
        (self.directory / 'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
        archive = self.directory / 'review-bundle.zip'
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
            for name in ('capture.pcap', 'session.json', 'analysis.json', 'REPORT.md'):
                bundle.write(self.directory / name, name)
        return archive, summary


def helper_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--usb-investigation']
    return [sys.executable, str(Path(__file__).resolve().parents[1] / 'battery_tray.pyw'), '--usb-investigation']


def launch_helper():
    if sys.platform != 'win32':
        raise RuntimeError('USBPcap investigation requires Windows.')
    return subprocess.Popen(helper_command(), **_options())
