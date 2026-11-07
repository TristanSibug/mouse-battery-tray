"""Separate Tk process for user-guided, local USB capture on Windows."""
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .capture import CaptureSession, find_usbpcap, hid_mice, list_targets

USBPCAP_RELEASES = 'https://github.com/desowin/usbpcap/releases'


class InvestigationWizard:
    def __init__(self, root):
        self.root = root
        self.root.title('Investigate Unsupported Mouse - Assisted USB Capture')
        self.root.geometry('960x780')
        self.root.minsize(820, 650)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.session = None
        self.mice = []
        self.targets = []
        self.battery = tk.StringVar(value='')
        self.charging = tk.StringVar(value='Not charging')
        self.software = tk.StringVar(value='')
        self.note = tk.StringVar(value='')
        self.tool = tk.StringVar(value=find_usbpcap())
        self.output = tk.StringVar(value=str(Path.home() / 'Documents' / 'MouseBatteryTray Investigations'))
        self.duration = tk.StringVar(value='60')
        self.consent = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Install USBPcap, then refresh the device lists. The tray app is paused while this window is open.')
        self.observation_text = tk.StringVar(value='No observations recorded yet.')
        self._build()
        self.root.after(150, self._drain)

    def _build(self):
        # A scrollable body keeps all steps reachable at Windows display scaling.
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = ttk.Frame(canvas, padding=16)
        window = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text='Collect evidence for an unsupported mouse', font=('Segoe UI', 15, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(body, wraplength=830, text=(
            'This does not add battery support automatically. Keep the manufacturer\'s software open and use it to refresh the battery level. '
            'USBPcap must be installed separately; follow its installer\'s restart instructions. USBPcap may ask for administrator approval. '
            'No drivers are installed by this app. Use a USB mouse or USB wireless receiver, not native Bluetooth.')).grid(row=1, column=0, columnspan=3, sticky='ew', pady=(5, 12))
        ttk.Label(body, text='1. USBPcapCMD.exe').grid(row=2, column=0, sticky='w')
        ttk.Entry(body, textvariable=self.tool).grid(row=2, column=1, sticky='ew', padx=8)
        ttk.Button(body, text='Browse...', command=self.browse_tool).grid(row=2, column=2, sticky='ew')
        ttk.Button(body, text='Get USBPcap (official releases)', command=lambda: webbrowser.open(USBPCAP_RELEASES)).grid(row=3, column=1, sticky='w', padx=8, pady=5)
        self.refresh_button = ttk.Button(body, text='2. Refresh device lists', command=self.refresh)
        self.refresh_button.grid(row=4, column=0, columnspan=3, sticky='w', pady=(8, 4))
        ttk.Label(body, text='Select the HID mouse/receiver whose battery you are investigating:').grid(row=5, column=0, columnspan=3, sticky='w')
        self.mouse_choice = ttk.Combobox(body, state='readonly')
        self.mouse_choice.grid(row=6, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Label(body, text='Select its USB capture address (match the product/interface names below):').grid(row=7, column=0, columnspan=3, sticky='w')
        self.target_choice = ttk.Combobox(body, state='readonly')
        self.target_choice.grid(row=8, column=0, columnspan=3, sticky='ew', pady=4)
        self.target_choice.bind('<<ComboboxSelected>>', self.target_details)
        self.details = ttk.Label(body, text='If uncertain, unplug/replug the receiver and refresh to identify the entry that changes.', wraplength=830)
        self.details.grid(row=9, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Label(body, text='Manufacturer\'s software').grid(row=10, column=0, sticky='w')
        ttk.Entry(body, textvariable=self.software).grid(row=10, column=1, columnspan=2, sticky='ew', padx=8, pady=5)
        ttk.Label(body, text='Output folder').grid(row=11, column=0, sticky='w')
        ttk.Entry(body, textvariable=self.output).grid(row=11, column=1, sticky='ew', padx=8)
        ttk.Button(body, text='Choose...', command=self.browse_output).grid(row=11, column=2, sticky='ew')
        ttk.Label(body, text='Capture limit (seconds)').grid(row=12, column=0, sticky='w', pady=5)
        ttk.Spinbox(body, from_=10, to=120, textvariable=self.duration, width=8).grid(row=12, column=1, sticky='w', padx=8)
        ttk.Checkbutton(body, variable=self.consent, text='I selected the mouse\'s USB address and agree to capture its USB traffic locally.').grid(row=13, column=0, columnspan=3, sticky='w', pady=(8, 3))
        ttk.Label(body, wraplength=830, text=(
            'Capture is limited to that USB address, not the whole hub. Packets may include device identifiers, mouse buttons and other input reports. '
            'Do not select a keyboard or unrelated device. Nothing is uploaded. Review the files before sharing them.')).grid(row=14, column=0, columnspan=3, sticky='ew')
        ttk.Label(body, text='3. Label the manufacturer\'s battery reading', font=('Segoe UI', 11, 'bold')).grid(row=15, column=0, columnspan=3, sticky='w', pady=(14, 5))
        row = ttk.Frame(body)
        row.grid(row=16, column=0, columnspan=3, sticky='ew')
        ttk.Label(row, text='Battery %:').pack(side='left')
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.battery, width=6).pack(side='left', padx=8)
        ttk.Combobox(row, textvariable=self.charging, state='readonly', values=('Not charging', 'Charging'), width=18).pack(side='left')
        ttk.Label(row, text='Observation note:').pack(side='left', padx=(12, 5))
        ttk.Entry(row, textvariable=self.note).pack(side='left', fill='x', expand=True)
        ttk.Label(body, wraplength=830, text=(
            'Start capture, enter the percentage shown in the manufacturer\'s software, and click Record Observation. '
            'Then refresh that software\'s battery reading and wait for replies. Record another observation if the level or charging state changes. '
            'Keep the same receiver connected. A cable/replug may create a different USB address and requires a separate capture.')).grid(row=17, column=0, columnspan=3, sticky='ew', pady=6)
        buttons = ttk.Frame(body)
        buttons.grid(row=18, column=0, columnspan=3, sticky='ew', pady=6)
        self.start_button = ttk.Button(buttons, text='Start Capture', command=self.start)
        self.start_button.pack(side='left')
        self.observe_button = ttk.Button(buttons, text='Record Observation', command=self.observe, state='disabled')
        self.observe_button.pack(side='left', padx=8)
        self.stop_button = ttk.Button(buttons, text='Stop and Prepare Review Files', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        ttk.Label(body, textvariable=self.observation_text, wraplength=830).grid(row=19, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Label(body, textvariable=self.status, wraplength=830, foreground='#215080').grid(row=20, column=0, columnspan=3, sticky='ew', pady=8)
        self.open_button = ttk.Button(body, text='4. Open Local Review Folder', command=self.open_folder, state='disabled')
        self.open_button.grid(row=21, column=0, columnspan=2, sticky='w')
        ttk.Button(body, text='Close and Resume Tray', command=self.close).grid(row=21, column=2, sticky='e')

    def browse_tool(self):
        if self.busy or self.session and not self.session.finished:
            return
        path = filedialog.askopenfilename(parent=self.root, title='Select installed USBPcapCMD.exe', filetypes=[('USBPcap capture tool', 'USBPcapCMD.exe')])
        if path:
            self.tool.set(path)

    def browse_output(self):
        path = filedialog.askdirectory(parent=self.root, title='Choose a local diagnostic output folder')
        if path:
            self.output.set(path)

    def _background(self, work, success):
        self.busy = True
        def worker():
            try:
                self.events.put((success, work(), None))
            except Exception as exc:
                self.events.put((success, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        if self.busy or self.session and not self.session.finished:
            return
        executable = self.tool.get().strip()
        if not Path(executable).is_file() or Path(executable).name.lower() != 'usbpcapcmd.exe':
            messagebox.showinfo('USBPcap required', 'Install USBPcap from its official release page, then browse to USBPcapCMD.exe. Restart Windows if its installer requests it.', parent=self.root)
            return
        self.status.set('Reading installed USBPcap controllers and connected devices...')
        self.refresh_button.configure(state='disabled')
        self._background(lambda: (hid_mice(), list_targets(executable)), self.refreshed)

    def refreshed(self, value):
        self.mice, self.targets = value
        self.refresh_button.configure(state='normal')
        self.mouse_choice['values'] = [f"{d['product']} - {d['vid']:04x}:{d['pid']:04x}" for d in self.mice]
        self.target_choice['values'] = [f"{d['controller']} - {d['label']}" for d in self.targets]
        self.mouse_choice.set('')
        self.target_choice.set('')
        self.status.set('Choose both the HID mouse and its USB address. If names are generic, unplug/replug and refresh to identify the address.' if self.targets else 'No USBPcap targets found. Check driver installation, reboot if required, and reconnect the receiver.')

    def target_details(self, event=None):
        index = self.target_choice.current()
        if index >= 0:
            self.details.configure(text='USB interfaces: ' + '; '.join(self.targets[index]['interfaces']) + '\nIf uncertain, unplug/replug and refresh before capturing.')

    def start(self):
        if self.busy or self.session and not self.session.finished:
            return
        if sys.platform != 'win32':
            messagebox.showerror('Windows required', 'Live USBPcap capture requires Windows. This window can be inspected on other platforms, but cannot capture USB traffic there.', parent=self.root)
            return
        try:
            mouse, target = self.mouse_choice.current(), self.target_choice.current()
            if mouse < 0 or target < 0:
                raise ValueError('Select the HID mouse and the matching USB device address first.')
            if not self.consent.get():
                raise ValueError('Confirm the selected device and local USB capture using the checkbox.')
            if not self.software.get().strip():
                raise ValueError('Enter the name of the manufacturer\'s software you will use to refresh the battery reading.')
            if not self.output.get().strip():
                raise ValueError('Choose a local output folder.')
            duration = int(self.duration.get())
            session = CaptureSession(self.output.get(), self.mice[mouse], self.targets[target], self.software.get(), duration)
            self.session = session
            executable = self.tool.get().strip()
            self.start_button.configure(state='disabled')
            self.refresh_button.configure(state='disabled')
            self.mouse_choice.configure(state='disabled')
            self.target_choice.configure(state='disabled')
            self.open_button.configure(state='disabled')
            self.status.set('Starting USBPcap. Approve its administrator prompt if shown; capture time starts when data is written.')
            self._background(lambda: session.start(executable), self.started)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Cannot start capture', str(exc), parent=self.root)

    def started(self, _):
        self.stop_button.configure(state='normal')

    def observe(self):
        if self.busy or not self.session:
            return
        try:
            self.session.observe(int(self.battery.get()), self.charging.get() == 'Charging', self.note.get())
            self.observation_text.set(f'{len(self.session.labels)} observations recorded. Now refresh the manufacturer\'s battery reading and allow replies to arrive.')
        except (ValueError, OSError) as exc:
            messagebox.showerror('Observation not recorded', str(exc), parent=self.root)

    def stop(self):
        if self.busy or not self.session or self.session.finalized:
            return
        self.observe_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        self.status.set('Stopping capture and validating local review files...')
        session = self.session
        def work():
            session.stop()
            return session.finalize()
        self._background(work, self.finished)

    def finished(self, value):
        archive, summary = value
        identity = summary['device_identity']
        self.status.set(f"Review files saved: {archive}. {summary['packets']} packets, device identity {identity}. No support was added. "
                        + ('The selected HID and USB descriptors match.' if identity == 'matched' else 'Selection was not confirmed: inspect REPORT.md and consider repeating with the correct USB address.'))
        self.open_button.configure(state='normal')
        self.start_button.configure(state='normal')
        self.refresh_button.configure(state='normal')
        self.mouse_choice.configure(state='readonly')
        self.target_choice.configure(state='readonly')

    def _drain(self):
        while True:
            try:
                success, value, error = self.events.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            if error:
                self.status.set(error)
                self.refresh_button.configure(state='normal')
                self.start_button.configure(state='normal')
                self.mouse_choice.configure(state='readonly')
                self.target_choice.configure(state='readonly')
                if self.session and self.session.process is None:
                    self.session.stop('start_failed')
                self.open_button.configure(state='normal' if self.session else 'disabled')
                self.stop_button.configure(state='normal' if self.session and not self.session.finished else 'disabled')
            else:
                success(value)
        if self.session and not self.busy and not self.session.finalized:
            try:
                state = self.session.tick()
                self.observe_button.configure(state='normal' if state == 'capturing' else 'disabled')
                if state == 'capturing':
                    self.status.set('Capturing the selected USB address. Record observations, then refresh the battery reading in the manufacturer\'s software.')
                if self.session.finished:
                    self.stop()
            except Exception as exc:
                self.status.set(str(exc))
                self.stop()
        if not self.closing:
            self.root.after(200, self._drain)

    def open_folder(self):
        if self.session:
            if sys.platform == 'win32':
                os.startfile(self.session.directory)
            else:
                messagebox.showinfo('Review folder', str(self.session.directory), parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo('Please wait', 'Wait for device discovery or review-file preparation to finish, then close this window.', parent=self.root)
            return
        if self.session and not self.session.finished:
            if not messagebox.askyesno('Stop capture?', 'Stop USB capture and prepare local review files before closing?', parent=self.root):
                return
            self.stop()
            return
        self.closing = True
        self.root.destroy()


def main():
    root = tk.Tk()
    InvestigationWizard(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
