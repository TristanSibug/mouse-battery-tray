# Build on Windows: python -m PyInstaller --clean --noconfirm usb_investigation.spec
# USBPcap is installed separately at the user's request; it is not bundled.
a = Analysis(
    ['usb_investigator.pyw'],
    pathex=[], binaries=[], datas=[], hiddenimports=[], hookspath=[],
    hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='USBInvestigation', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None,
)
