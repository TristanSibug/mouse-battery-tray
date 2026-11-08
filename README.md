# Mouse Battery Tray Indicator

<img src="https://github.com/user-attachments/assets/4e384838-6073-4457-827c-737c18f909f2" alt="Mouse Battery Tray Screenshot" width="150" align="right">

A lightweight, standalone Windows system tray application that displays the live battery percentage of wireless gaming mice directly in the taskbar.

[<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 4px;"><path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/></svg> **View releases and downloads**](https://github.com/TristanSibug/mouse-battery-tray/releases/latest)

This tool serves as a lightweight alternative to resource-heavy official manufacturer hub software.

This is TristanSibug's fork of
[incconutwo/mouse-battery-tray](https://github.com/incconutwo/mouse-battery-tray).
See [CHANGELOG.md](CHANGELOG.md) for the release notes.

[![Platform](https://img.shields.io/badge/Platform-Windows_10_%7C_11-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/TristanSibug/mouse-battery-tray)
[![Release](https://img.shields.io/github/v/release/TristanSibug/mouse-battery-tray?style=for-the-badge&color=28a745)](https://github.com/TristanSibug/mouse-battery-tray/releases)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

---

## Supported Devices Status

The application officially recognizes the following models, with dynamic fallback support for compatible OEM mice:

| Brand | Model | 2.4G Wireless | Wired / Charging | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **WLMouse** | Beast X / Mini Pro | 🟢 | 🟢 | 8K Receiver (`VID 0x36a7`) |
| **Razer** | Universal Wireless / DeathAdder V3 | 🟢 | 🟢 | OpenRazer 90-Byte Query (`VID 0x1532`) |

<details>
<summary>Show all supported devices</summary>

| Brand | Model | 2.4G Wireless | Wired / Charging | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Razer** | HyperPolling Dongle | 🟢 | 🟢 | Dongle (`PID 0x00b3`) |
| **Attack Shark** | X11 / X6 / R1 / X3 / 8K Receiver | 🟢 | 🟢 | Dynamic Beken model resolution (`VID 0x1d57`) |
| **Pulsar** | Xlite / X2 Series | 🟢 | 🟢 | CompX OEM (`VID 0x25a7`) |
| | 8K Dongle Gen.2 | 🟢 | 🟡 | 8K Receiver (`VID 0x3710`) |
| | X2 & X2N CrazyLight | 🟢 | 🟢 | 8K Receiver & Wired (`VID 0x3710`) |
| **Rakk** | Gahum | 🟢 | 🟡 | Dedicated report-08 query (`VID 0x25a7`, `PID 0xfa7c`) |
| **VXE** | R1 Series (R1 / SE / SE+ / Pro / Pro Max) | 🟢 | 🟡 | Dongles (`VID 0x3554`, `0x320f`) |
| **Scyrox** | V6 8K | 🟢 | 🟡 | 8K Dongle (`VID 0x3554`) |
| **Lamzu** | Maya X 8K | 🟢 | 🟡 | 8K Dongle (`VID 0x373e`) |
| **G-Wolves** | Fenrir Pro 8K / HTX Ultra 8K | 🟢 | 🟢 | 8K Dongle & Wired (`VID 0x33e4`) |
| **MAMBASNAKE** | M5 Ultra | 🟢 | 🟢 | Dongle & Wired (`VID 0x373e`) |
| **Hitscan** | Hyperlight (1K / 8K) | 🟢 | 🟡 | 8K Dongles (`VID 0x3770`, PIDs `0x0300`, `0x0200`) |
| **Cherry Xtrfy** | M68 Wireless | 🟢 | 🟢 | 1K Dongle & Cable (`VID 0x046a`) |
| **Incott** | G24 Pro | 🟢 | 🟢 | PixArt 8K Dongle (`VID 0x093a`) |
| **Generic** | Other Beken / CompX / WLMouse / Razer | 🟡 | 🟡 | Dynamic OEM fallback |

</details>

> **Status Key:** 🟢 Supported & Verified &nbsp;|&nbsp; 🟡 Auto-Detected / Untested

---

## Fix Generic Device Name

**This works only when the app is already detecting your mouse's battery level.**
It changes the displayed name; it cannot fix missing battery readings, add a
battery protocol, or reverse-engineer an unsupported mouse.

If your mouse reports a battery level but has a generic or incorrect name:

1. Right-click the tray icon and choose **Fix Generic Device Name**.
2. The app reads that mouse's USB product name. If it is specific, it applies
   it automatically. If the hardware also reports a generic name, enter your
   mouse's model name in the dialog.
3. The name is saved on your PC and used after restarting. You do not need to
   edit source files, run a separate extractor, or submit an issue.

To reset a saved name, exit the tray app first. Names are stored as individual
values under `HKEY_CURRENT_USER\Software\MouseBatteryTray\DeviceNames`, using
`vid:pid` in lowercase hexadecimal as the value name. 

```powershell
Remove-ItemProperty -Path 'HKCU:\Software\MouseBatteryTray\DeviceNames' -Name 'vid:pid'
```

The action is disabled until a recent battery reading is available. If no
battery is detected, renaming is not a fix: that mouse may need additional
protocol support. The app never guesses a model name from hardware IDs alone.

## Hours estimate

Enable **Show Hours Estimate** in the tray menu. Hover over the tray icon to
see the estimate next to the battery percentage, or read the **Hours estimate**
line in the right-click menu.

An estimate needs observed battery discharge; it cannot be calculated from a
single percentage. Until enough data arrives, the tooltip says **estimating...**
and the menu shows **learning (needs battery drop)**. Slowly discharging mice
may need several hours before their first usable battery drop. Charging pauses
the estimate, and a long gap in polling restarts learning to avoid counting
sleep time as active discharge. The estimate is approximate and depends on use.

## USB Investigation: separate experimental application

`USBInvestigation.exe` is a separate tool for collecting evidence about an
unsupported USB mouse or wireless receiver. `battery_tray.exe` and its build
spec are unchanged. There is no investigation menu, launch hook, or installation
code inside the battery tray.

**This collects evidence; it does not automatically add battery support or
modify protocol code.** Native Bluetooth investigation is not supported.

### Build USBInvestigation.exe on Windows

1. Download the [standalone investigation branch](https://github.com/TristanSibug/mouse-battery-tray/archive/refs/heads/feature/standalone-usb-investigation.zip)
   and extract it. Open PowerShell in the folder containing `usb_investigation.spec`.
2. Install Python for Windows, including Tkinter, then run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install hidapi pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --workpath "$env:TEMP\USBInvestigation-build" usb_investigation.spec
```

3. The separate single-file output is **`dist\USBInvestigation.exe`**. Building
   it does not replace `dist\battery_tray.exe`. End users do not need Python.
   From source, run `py usb_investigator.pyw` instead.

### Detailed user workflow

1. **Open USBInvestigation.exe.** It checks for `USBPcapCMD.exe`, existing USBPcap
   driver registration, and active USB capture controllers. It distinguishes
   missing software, an installation that is not ready, and a working capture
   setup. An installed driver with a missing utility is not treated as absent.
2. **If USBPcap is missing, an installation offer appears.** Declining leaves
   the system unchanged. You can instead browse to an existing installation.
   The built-in installer offer supports x64 Windows; it does not install an
   x64 driver on ARM or other unsupported platforms.
3. **If you accept, the app downloads official USBPcap 1.5.4.0.** It preserves
   HTTPS verification and checks a pinned SHA-256 from Microsoft's
   [winget manifest](https://github.com/microsoft/winget-pkgs/blob/master/manifests/d/desowin/USBPcap/1.5.4.0/desowin.USBPcap.installer.yaml).
   An unexpected redirect, failed download, or checksum mismatch stops the
   process; unverified installers are deleted and never launched.
4. **The normal Windows USBPcap installer opens through UAC.** Approve the
   administrator prompt only if you want to proceed. Accept the installer’s
   license and choose its installation options yourself. This is not a silent
   installation. Cancelling UAC or setup is supported.
5. **Readiness is checked again.** A successful installer exit alone is not
   treated as proof that capture works. If a restart is needed, save your work,
   restart Windows when convenient, and reopen this app. USB Investigation does
   not request or trigger a reboot. Use **Check USBPcap** to retry the check.
6. **Close battery_tray.exe and other battery-polling tools yourself.** The
   standalone investigation app does not stop or control them. Keep the
   manufacturer's mouse software open so it can display and refresh the battery.
7. **Select the HID mouse and its matching USB capture address.** Use names and
   interface descriptions, or unplug/replug the receiver and refresh to identify
   the entry that changes. Addresses are not hardware IDs and can change when
   a device is reconnected. The app does not guess this match.
8. **Enter the manufacturer's software name and select an output folder.**
   Confirm that the battery tray is closed and that you consent to capturing
   the selected device. Packets may include device identifiers and input
   reports; do not select a keyboard or unrelated device. Nothing is uploaded.
9. **Start capture.** USBPcap may ask for administrator approval for recording,
   separately from installation. It captures only the chosen address, not all
   USB devices. The 10–120 second timer begins when data starts being written,
   with a separate startup timeout and a 64 MiB analysis limit.
10. **Record observations.** Enter the percentage shown in the manufacturer's
    software and select charging/not charging. Click **Record Observation**,
    then refresh the battery reading in that software and allow replies to
    arrive. Repeat when the percentage or charging state changes. Multiple
    distinct percentages are needed for battery-byte hints; one short recording
    will often be insufficient.
11. **Keep the same receiver connected.** A new USB address or a switch to wired
    mode requires a separate capture. Capture is never broadened automatically
    to every device on the controller or to newly connected devices.
12. **Stop and review.** Stop manually or let the timer finish. The app validates
    the captured records, compares descriptor VID/PID information when available,
    and saves local review files. Close USB Investigation and restart the battery
    tray manually when finished.

### Review files

Every session gets a new local folder. `review-bundle.zip` includes:

- `capture.pcap`: complete packets for the selected address, readable in Wireshark.
- `session.json`: device information and timestamped battery/charging observations.
- `analysis.json`: packet counts, descriptor identity comparison, bounded payload
  examples, paired control requests/responses, and possible byte correlations.
- `REPORT.md`: results and limitations, including missing labels, uncertain
  selection, or an incomplete final packet.

The original `capture.raw.pcap` and USBPcap log remain local but are excluded
from the ZIP. No report is described as verified protocol support. Invalid or
empty captures do not produce a success bundle. Byte correlations can be
coincidental and are never replayed or installed as a new protocol.

**Review before sharing. Nothing is uploaded automatically.** Wireshark is
optional for viewing the PCAP and is not bundled; download it from its
[official site](https://www.wireshark.org/download.html) if needed.

## Features

- **Fix Generic Device Name:** Automatically use a specific USB product name or enter the model name when needed. Requires existing battery detection and changes only the displayed name.
- **Live Numeric Percentage:** Displays the exact battery level directly on the tray icon as a colored number.
- **Color-Coded Status:**
  - 🟢 **Green** ($\ge 50\%$) - Healthy charge
  - 🟠 **Orange** ($20\% - 49\%$) - Moderate charge
  - 🔴 **Red** ($< 20\%$) - Low battery (time to charge)
- **Auto Taskbar Theme Detection:** Automatically adapts icon colors and contrast for Windows **Light Mode** and **Dark Mode** taskbars without extra configuration options.
- **Intelligent Hours Estimate:** Real-time battery discharge slope tracking with minimalistic tooltip predictions (e.g., `Mouse: 85% (~12h)` or `42% (~4h 30m)`), complete with a menu toggle.
- **Configurable Low Battery Alerts:** Sends a Windows toast notification when battery reaches your chosen threshold (25%, 20%, 15%, 10%, or Disabled).
- **Multi-Endpoint Candidate Discovery & Active Queries:** Automatically binds all HID sub-interfaces simultaneously and sends active Feature Report queries (including CompX/VXE Report `0x06`) for 8K receivers and silent feature-only endpoints.
- **Update Checker:** Asynchronously checks for new releases on GitHub directly from the right-click tray menu (`Check for Updates`).
- **Clean Connection & Charging States:** Displays **`Chg`** (blue) while charging, **`--`** (grey) while awaiting initial reading, and **`??`** when disconnected.
- **Start with Windows Toggle:** Right-click the icon to toggle startup behavior. It writes directly to your user registry (`HKCU`), requiring **zero Administrator (UAC) prompts**.
- **Multi-Brand Compatibility:** Supports Razer (`VID: 0x1532`), Beken-OEM firmware (`VID: 0x1d57`), CompX/Pulsar (`VID: 0x25a7`, `0x3710`), PixArt (`VID: 0x093a`), VXE/CompX (`VID: 0x3554`, `0x320f`), Cherry Xtrfy (`VID: 0x046a`), G-Wolves (`VID: 0x33e4`), Lamzu/Mambasnake (`VID: 0x373e`), Hitscan (`VID: 0x3770`), and WLMouse (`VID: 0x36a7`).


---

## Installation

### Prerequisites
For a published executable, download `battery_tray.exe` from this fork's
[releases](https://github.com/TristanSibug/mouse-battery-tray/releases) and double-click
it. End users do not need Python. A Git tag or source ZIP alone does not contain
a newly built executable.

For running from source or building, install [Python](https://www.python.org/)
on Windows. Python **3.12 (64-bit)** is recommended for the build instructions
below; source code requires Python 3.10+.

### Install Dependencies
Open your terminal (Command Prompt or PowerShell) and run:
```bash
pip install hidapi pystray pillow
```

### Build the Windows executable

1. Install Python for Windows, including the Python launcher (`py`).
2. Download and extract the [current main source ZIP](https://github.com/TristanSibug/mouse-battery-tray/archive/refs/heads/main.zip).
3. Exit the running tray app. Open **PowerShell** in the extracted folder that contains `battery_tray.pyw` and `battery_tray.spec`.
4. Run these commands one line at a time:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install hidapi pystray pillow pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --workpath "$env:TEMP\MouseBatteryTray-build" battery_tray.spec
```

5. Find the finished **single file** at `dist\battery_tray.exe`. The existing spec
   bundles the application, protocol modules, and dependencies
   into that executable and hides the console. You do not need to add `--onefile`
   when building from this spec, activate the virtual environment, or change
   PowerShell's execution policy.
6. Double-click the new executable, check the tray menu displays **v1.5.0**, and
   test automatic battery readings, charging, and restarting. Close it before rebuilding
   if Windows reports the file is in use.

Build on **Windows**: running PyInstaller on Linux will not produce a Windows
`.exe`. The intermediate build goes into the temporary directory, avoiding the
old tracked `build/` outputs. Existing executables are not updated by source edits.

---

## How to Run

1. **Run the executable (recommended):**
   Download `battery_tray.exe` from the [releases page](https://github.com/TristanSibug/mouse-battery-tray/releases),
   or use the copy you built in `dist`. Exit any older running instance, then
   double-click the executable. The app runs in the system tray without a console
   window; check the taskbar's hidden icons if you do not see it. No Python
   installation is required for the executable.

   You can also launch it from PowerShell in the folder containing the file:

   ```powershell
   .\battery_tray.exe
   ```

2. **Run from source in the background:**
   After installing Python and the source dependencies, use `pythonw` (or
   double-click `battery_tray.pyw` if `.pyw` files are associated with Python):

   ```powershell
   pythonw battery_tray.pyw
   ```

---

## Troubleshooting

### What Check for Updates does

The app checks this fork's latest published GitHub Release in the background at
startup and about once a day. **Check for Updates** runs that check manually.
It compares release versions and notifies you when a newer release is available;
**Update Available** opens the release page in your browser. Nothing is installed
automatically: download the new executable, exit the old app, and replace it.
Git tags alone are not published releases, so a repository with only tags may
report that no published release was found.

**Checking for updates...** means the request is still running. Other enabled
menu items should remain usable. An open menu keeps its current labels; reopen
it to see the completed result. Battery and update notifications continue in
the background.

- **Icon Stays on `??`:** 
  Ensure the mouse is turned on, in wireless mode (using the 2.4G adapter), and not asleep. Wake the mouse by moving it around for the first battery status packet to transmit.
- **Permissions Issue:**
  The app runs entirely in user-space and does not require admin rights. If the tray icon doesn't update, check if another exclusive tool (like the official software) is currently open and locking the USB receiver port.

---

## Acknowledgments & Credits

Special thanks to all community members who contributed device ID mappings, testing, pull requests, and hardware dumps *(if I accidentally missed your name, please open an issue or reply so I can add you!)*:

- **[@len0c](https://github.com/len0c)** – Reverse-engineered HID protocol handling and initial integration for the **WLMouse Beast X** series.
- **[@FeikoWielsma](https://github.com/FeikoWielsma)** – Contributed Pull Request #6 for **VXE R1 Pro** support & feature report `0x06` fallback polling.
- **[@HarukaYamamoto0](https://github.com/HarukaYamamoto0)** – Shared additional Beken OEM model device ID mappings ([attack-shark-x11-driver](https://github.com/HarukaYamamoto0/attack-shark-x11-driver)).
- **[@CptNinja](https://github.com/CptNinja)** – Provided hardware ID dump for the **Pulsar 8K Dongle Gen.2** (`VID 0x3710`, `PID 0x5406`).
- **[@nzeck1](https://github.com/nzeck1)** – Provided hardware ID dump for the **VXE R1 Series** (R1 / R1 SE / R1 SE+).
- **[@kidguyperson](https://github.com/kidguyperson)** – Provided hardware ID dump for the **VXE R1 Pro Max** (`VID 0x3554`, `PID 0xf58a`).
- **[@lilldizzy](https://github.com/lilldizzy)** – Reported & verified **Hitscan Hyperlight** (`PID 0x0200`) battery reading support.
- **[@Vinsmok3](https://github.com/Vinsmok3)** – Provided hardware ID dump for the **Hitscan Hyperlight** (`VID 0x3770`).
- **u/Truth_Lies** – Provided hardware ID dumps for **VXE R1 Pro** and **Cherry Xtrfy M68 Wireless**.
- **u/SadPeppermint** – Provided hardware ID dump for the **Scyrox V6 8K** (`VID 0x3554`, `PID 0xf5f7`).
- **u/kaklikesmilfs** – Provided hardware ID dump for the **Lamzu Maya X 8K** (`VID 0x373e`, `PID 0x001e`).
- **u/Kbphan** – Provided hardware ID dump for the **G-Wolves Fenrir Pro 8K** (`VID 0x33e4`, `PID 0x3854` / `0x3619`).
- **u/touholic** – Provided hardware ID dumps for **G-Wolves HTX Ultra 8K**, **MAMBASNAKE M5 Ultra**, and **Pulsar CrazyLight**.
- **u/guadygood** – Provided hardware ID dump for **Pulsar CrazyLight Series**.
- **u/Monophonotronic** – Provided hardware ID dump for the **Incott G24 Pro** (`VID 0x093a`, `PID 0x522c` / `0x622c`).
- **u/djnemoson** – Provided hardware ID dump for the **Pulsar X2 Wireless** (`VID 0x25a7`, `PID 0xfa7c` / `0xfa7b`).
- **u/MarcBelmaati** – Provided hardware ID dump for the **Razer Wireless / HyperPolling Dongle** (`VID 0x1532`, `PID 0x00b3` / `0x00a5`).
- **u/TwistedVincenzo** – Provided hardware ID dump for the **Pulsar Xlite Wireless**.
