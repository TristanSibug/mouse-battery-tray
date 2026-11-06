# Mouse Battery Tray Indicator

<img src="https://github.com/user-attachments/assets/4e384838-6073-4457-827c-737c18f909f2" alt="Mouse Battery Tray Screenshot" width="150" align="right">

A lightweight, standalone Windows system tray application that displays the live battery percentage of wireless gaming mice directly in the taskbar.

[<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle; margin-right: 4px;"><path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/></svg> **View releases and downloads**](https://github.com/TristanSibug/mouse-battery-tray/releases/latest)

This tool serves as a lightweight alternative to resource-heavy official manufacturer hub software.


This fork combines the working RAKK Gahum implementation from the fork's main
branch with the upstream `v1.2.2-dev` modular protocol engines and expanded device
support. Supported mice are detected automatically when the app starts.
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
| | HyperPolling Dongle | 🟢 | 🟢 | Dongle (`PID 0x00b3`) |
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

> **Status Key:** 🟢 Supported & Verified &nbsp;|&nbsp; 🟡 Auto-Detected / Untested

---

## Contributing & Adding New Models

The app automatically discovers connected mice using its implemented Beken,
CompX, Razer, WLMouse, and RAKK protocols. There is no manual detection menu or
local device-profile feature.

Hardware-ID extraction identifies a device and its interfaces. It does not
capture USB traffic or discover unknown battery commands. Adding an ID may be
enough for a mouse using an existing protocol; a different protocol needs a
reader implementation based on documentation or protocol investigation.

### Sharing hardware IDs

If your mouse is not fully recognized or is displayed as a generic device, we would love to add official support for it! 

We've made this process incredibly easy by including a standalone **Hardware ID Extractor wizard** (`dump_devices.exe`):

1. Go to the [Releases page](https://github.com/TristanSibug/mouse-battery-tray/releases) and download **`dump_devices.exe`** (or run `python tools/dump_devices.py`).
2. Run it and follow the simple 2-step prompt to scan your mouse in **Wireless (2.4G)** and **Wired** modes.
3. The wizard will automatically generate the clean Python dictionary configuration lines for your device.
4. Copy the generated block and paste it into a GitHub issue or Reddit reply!

To contribute built-in support, add the VID/PID mapping to the relevant dictionary
in `protocols/beken.py`, `protocols/compx.py`, `protocols/wlmouse.py`, or
`protocols/razer.py`. Protocol logic now lives in `protocols/`; `devices.py` has
been removed. For example, a CompX mapping belongs in `COMPX_DEVICES`:

```python
COMPX_DEVICES = {
    (0xYOUR_VID_HEX, 0xYOUR_PID_HEX): ("Your Mouse Name", "wireless"),
}
```

---

## Features

- **RAKK Gahum polling:** Uses the dedicated battery request, retries missing startup readings, and supports receivers without serial numbers. Invalid initial 0% replies are ignored.
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

1. Install Python 3.12 for Windows, including the Python launcher (`py`).
2. Download and extract the [current main source ZIP](https://github.com/TristanSibug/mouse-battery-tray/archive/refs/heads/main.zip).
3. Exit the running tray app. Open **PowerShell** in the extracted folder that
   contains `battery_tray.pyw` and `battery_tray.spec`.
4. Run these commands one line at a time:

```powershell
py -3.12 -m venv .venv
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

To distribute it, create a new version tag from the tested commit, create a
GitHub Release for that tag, upload `dist\battery_tray.exe`, and publish the
release. Update `__version__` in `updater.py` when preparing the next release.
The existing `v1.5.0` tag preserves the earlier release, including the retired
local-setup feature; use current `main` for these changes. The app's update
checker uses this fork's published releases. Recipients need only the executable.

The protocol and tray-control tests can run without Windows or a USB receiver:

```bash
python -B -m unittest discover -s tests -v
python -B tools/test_simulation.py
```

RAKK Gahum support is implemented in `protocols/rakk.py`. Because its receiver
shares VID/PID `25a7:fa7c` with Pulsar devices, automatic polling selects RAKK
by its FF02/2 send and FF01/0 receive interface pair, rather than by IDs alone.
A single pair can be matched even when Windows exposes different instance
paths without a serial number. Ambiguous pairs from multiple receivers are
not guessed. Devices without this interface pair keep their CompX handling.
Missing or invalid 0% RAKK startup replies are retried in the RAKK handler.

---

## How to Run

1. **Run in Background (Recommended):**
   Run the file using `pythonw` (or double-click the `.pyw` extension) to start it silently in the background:
   ```bash
   pythonw battery_tray.pyw
   ```
2. **Run in Terminal (Debugging):**
   If you want to view console logs:
   ```bash
   python battery_tray.pyw
   ```

---

## Troubleshooting

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
