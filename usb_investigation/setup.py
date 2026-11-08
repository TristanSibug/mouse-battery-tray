"""USBPcap prerequisite checks and a verified, explicitly requested installer.

Pinned URL/hash source: Microsoft's winget-pkgs catalog,
manifest desowin.USBPcap/1.5.4.0/desowin.USBPcap.installer.yaml.
The downloaded official installer was independently checked against this digest.
No silent install, TLS bypass, arbitrary download URL, or automatic reboot.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from .capture import _metadata, find_usbpcap, parse_interfaces

INSTALLER_VERSION = '1.5.4.0'
INSTALLER_URL = 'https://github.com/desowin/usbpcap/releases/download/1.5.4.0/USBPcapSetup-1.5.4.0.exe'
INSTALLER_SHA256 = '87a7edf9bbbcf07b5f4373d9a192a6770d2ff3add7aa1e276e82e38582ccb622'
MAX_INSTALLER_BYTES = 32 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


class InstallationCancelled(Exception):
    pass


def installer_supported():
    machine = os.environ.get('PROCESSOR_ARCHITEW6432') or platform.machine()
    return sys.platform == 'win32' and machine.upper() in ('AMD64', 'X86_64')


def driver_registered():
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\USBPcap'):
            return True
    except OSError:
        return False


def check_installation(executable=''):
    """Installed files/service registration and usable controllers are separate."""
    if sys.platform != 'win32':
        return {'state': 'unsupported', 'executable': '', 'message': 'Live USB capture requires Windows.'}
    tool = executable.strip() or find_usbpcap()
    registered = driver_registered()
    if not tool or not Path(tool).is_file():
        if registered:
            return {'state': 'installed_not_ready', 'executable': '', 'message':
                    'USBPcap driver registration exists, but USBPcapCMD.exe was not found. Browse to the installed tool, or repair its installation.'}
        return {'state': 'missing', 'executable': '', 'message': 'USBPcap was not found. Install it or browse to an existing USBPcapCMD.exe.'}
    if Path(tool).name.lower() != 'usbpcapcmd.exe':
        return {'state': 'check_failed', 'executable': '', 'message': 'Select USBPcapCMD.exe, not an installer or a different executable.'}
    try:
        interfaces = parse_interfaces(_metadata(tool, ['--extcap-interfaces']))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {'state': 'check_failed', 'executable': tool, 'message': f'USBPcap exists, but checking its controllers failed: {exc}'}
    if not interfaces:
        return {'state': 'installed_not_ready', 'executable': tool, 'message':
                'USBPcapCMD.exe is present, but no capture controllers are active. Complete driver setup and restart Windows if requested, then check again.'}
    return {'state': 'ready', 'executable': tool, 'message':
            f'USBPcap is ready: {len(interfaces)} capture controller(s) found. Refresh the device lists to continue.'}


class _TrustedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise ValueError('Installer download redirected to an unexpected destination.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_installer(directory, opener=None):
    """Return a checksum-verified official installer, or delete the failed download."""
    destination = Path(directory) / f'USBPcapSetup-{INSTALLER_VERSION}.exe'
    if destination.exists():
        raise FileExistsError('Installer destination already exists; refusing to replace it.')
    opener = opener or urllib.request.build_opener(_TrustedRedirects())
    started = time.monotonic()
    try:
        request = urllib.request.Request(INSTALLER_URL, headers={'User-Agent': 'USBInvestigation-Setup'})
        with opener.open(request, timeout=30) as response, destination.open('xb') as output:
            parsed = urllib.parse.urlsplit(response.geturl())
            if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise ValueError('Installer response came from an unexpected destination.')
            size = 0
            digest = hashlib.sha256()
            while True:
                if time.monotonic() - started > 90:
                    raise TimeoutError('USBPcap download timed out. Try again when the connection is stable.')
                block = response.read(65536)
                if not block:
                    break
                size += len(block)
                if size > MAX_INSTALLER_BYTES:
                    raise ValueError('Installer download exceeded its size limit.')
                output.write(block)
                digest.update(block)
            if digest.hexdigest() != INSTALLER_SHA256:
                raise ValueError('USBPcap installer checksum did not match. It was deleted and will not be launched.')
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def run_installer(path):
    """Launch only the pinned verified installer through interactive Windows UAC."""
    if not installer_supported():
        raise RuntimeError('The offered USBPcap installer requires x64 Windows. Use the official project for other supported platforms.')
    path = Path(path).resolve()
    if path.stat().st_size > MAX_INSTALLER_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != INSTALLER_SHA256:
        raise ValueError('Installer verification failed before launch. Nothing was executed.')

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG),
                    ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int),
                    ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                    ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE),
                    ('hProcess', wintypes.HANDLE)]

    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = 'runas'
    info.lpFile = str(path)
    info.lpDirectory = str(path.parent)
    info.nShow = 1  # SW_SHOWNORMAL: the installer is interactive, not silent.
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:
            raise InstallationCancelled('Administrator approval was cancelled. USBPcap was not installed by this app.')
        raise ctypes.WinError(error)
    try:
        if not info.hProcess:
            raise RuntimeError('Windows did not return an installer process handle.')
        if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        if info.hProcess:
            kernel.CloseHandle(info.hProcess)


def install_usbpcap(progress=lambda message: None):
    """Call only after the UI's explicit installation confirmation."""
    if not installer_supported():
        raise RuntimeError('The offered installer is for x64 Windows only.')
    with tempfile.TemporaryDirectory(prefix='usb-investigation-setup-') as folder:
        progress(f'Downloading official USBPcap {INSTALLER_VERSION} and verifying its checksum...')
        installer = download_installer(folder)
        progress('Installer verified. Approve Windows UAC if you want to proceed, then finish or cancel the official USBPcap setup window.')
        code = run_installer(installer)
    if code not in (0, 3010, 1641):
        return {'state': 'installer_failed', 'executable': '', 'message':
                f'USBPcap setup exited with code {code}. Installation may have been cancelled or failed; it has not been marked ready.'}
    progress('USBPcap setup finished. Checking whether capture controllers are ready...')
    result = check_installation()
    if code in (3010, 1641):
        result.update(state='restart_required', message='USBPcap setup requested a Windows restart. Save your work and restart when convenient, then reopen USB Investigation. This app does not trigger a reboot.')
    elif result['state'] != 'ready':
        result['message'] = 'USBPcap setup finished. ' + result['message']
    return result
