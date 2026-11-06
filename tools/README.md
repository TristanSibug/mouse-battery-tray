# Development and hardware diagnostics

These scripts are for development; they are not needed to run `battery_tray.exe`.
Run them from the repository root with the project's Python dependencies installed.
Exit the tray app before running hardware probes so they do not compete for HID
handles. Hardware probes require a connected receiver; they are not automated tests.

| Script | Purpose |
| --- | --- |
| `battery_test.py` | Try the RAKK report-08 battery request on the FF02 interface. |
| `battery_test2.py` | Send the RAKK battery request and inspect replies across vendor interfaces. |
| `listen_all.py` | Listen for packets across RAKK/CompX vendor interfaces. |
| `probe.py` | Inspect incoming packets from RAKK/CompX interfaces. |
| `watch6.py` | Investigate report-06 responses on the FF04 interface. |
| `dump_devices.py` | Collect hardware IDs and interface information. |
| `dump_hid_reports.py` | Inspect HID reports for protocol investigation. |
| `dump_compx_packets.py` | Inspect CompX packets for protocol investigation. |
| `test_simulation.py` | Run protocol simulations without a physical receiver. |

For example, run the RAKK battery probe from the repository root:

```powershell
python tools/battery_test.py
```

Run the automated checks separately:

```powershell
python -B -m unittest discover -s tests -v
python -B tools/test_simulation.py
```
