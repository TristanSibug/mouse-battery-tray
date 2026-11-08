"""Prerequisite states and installer consent/integrity boundaries (no real installs)."""
import ast
import ctypes
import hashlib
import io
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from usb_investigation import setup
from usb_investigation.wizard import InvestigationWizard


class Response(io.BytesIO):
    def geturl(self):
        return setup.INSTALLER_URL


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tool = Path(self.directory.name) / 'USBPcapCMD.exe'
        self.tool.write_bytes(b'fixture')

    def check(self, path='', registered=False, output='', error=None):
        with patch.object(setup.sys, 'platform', 'win32'), \
             patch.object(setup, 'driver_registered', return_value=registered), \
             patch.object(setup, 'find_usbpcap', return_value=path), \
             patch.object(setup, '_metadata', return_value=output, side_effect=error):
            return setup.check_installation()

    def test_missing_tool_and_driver_are_offered_setup(self):
        self.assertEqual(self.check()['state'], 'missing')

    def test_existing_driver_without_tool_is_not_claimed_uninstalled(self):
        self.assertEqual(self.check(registered=True)['state'], 'installed_not_ready')

    def test_tool_without_controllers_requires_setup_or_restart(self):
        result = self.check(path=str(self.tool))
        self.assertEqual(result['state'], 'installed_not_ready')
        self.assertIn('restart', result['message'])

    def test_tool_with_active_controller_is_ready(self):
        result = self.check(path=str(self.tool), output=r'interface {value=\\.\USBPcap1}{display=USBPcap1}')
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['executable'], str(self.tool))

    def test_tool_failure_is_not_treated_as_missing(self):
        self.assertEqual(self.check(path=str(self.tool), error=OSError('blocked'))['state'], 'check_failed')

    def test_controller_probe_timeout_is_a_recoverable_failed_check(self):
        result = self.check(path=str(self.tool), error=subprocess.TimeoutExpired('USBPcapCMD.exe', 20))
        self.assertEqual(result['state'], 'check_failed')

    def test_non_usbpcap_program_is_not_run_as_a_prerequisite_check(self):
        path = Path(self.directory.name) / 'wrong.exe'
        path.write_bytes(b'other')
        with patch.object(setup.sys, 'platform', 'win32'), \
             patch.object(setup, 'driver_registered', return_value=False), \
             patch.object(setup, '_metadata') as metadata:
            result = setup.check_installation(str(path))
        self.assertEqual(result['state'], 'check_failed')
        metadata.assert_not_called()

    def test_other_platforms_or_arm_do_not_get_x64_driver_installer(self):
        with patch.object(setup.sys, 'platform', 'linux'):
            self.assertEqual(setup.check_installation()['state'], 'unsupported')
            self.assertFalse(setup.installer_supported())
        with patch.object(setup.sys, 'platform', 'win32'), \
             patch.object(setup.platform, 'machine', return_value='ARM64'), \
             patch.dict(setup.os.environ, {'PROCESSOR_ARCHITEW6432': ''}):
            self.assertFalse(setup.installer_supported())


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.payload = b'official installer test fixture'
        self.path = Path(self.directory.name) / f'USBPcapSetup-{setup.INSTALLER_VERSION}.exe'

    def test_exact_checksum_is_required(self):
        opener = Mock()
        opener.open.return_value = Response(self.payload)
        with patch.object(setup, 'INSTALLER_SHA256', hashlib.sha256(self.payload).hexdigest()):
            path = setup.download_installer(self.directory.name, opener)
        self.assertEqual(path.read_bytes(), self.payload)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, setup.INSTALLER_URL)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 30)

    def test_mismatch_is_deleted_and_not_executable(self):
        opener = Mock()
        opener.open.return_value = Response(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            setup.download_installer(self.directory.name, opener)
        self.assertFalse(self.path.exists())

    def test_existing_file_is_preserved(self):
        self.path.write_bytes(b'pre-existing user file')
        opener = Mock()
        with self.assertRaises(FileExistsError):
            setup.download_installer(self.directory.name, opener)
        self.assertEqual(self.path.read_bytes(), b'pre-existing user file')
        opener.open.assert_not_called()

    def test_oversized_response_is_rejected_and_removed(self):
        opener = Mock()
        opener.open.return_value = Response(self.payload)
        with patch.object(setup, 'MAX_INSTALLER_BYTES', 3), self.assertRaises(ValueError):
            setup.download_installer(self.directory.name, opener)
        self.assertFalse(self.path.exists())

    def test_unexpected_download_destination_is_rejected(self):
        opener = Mock()
        response = Response(self.payload)
        response.geturl = lambda: 'https://unrelated.example/installer.exe'
        opener.open.return_value = response
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            setup.download_installer(self.directory.name, opener)
        self.assertFalse(self.path.exists())

    def test_untrusted_or_plain_http_redirects_are_rejected(self):
        handler = setup._TrustedRedirects()
        for destination in ('http://github.com/file.exe', 'https://elsewhere.example/file.exe'):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, '', {}, destination)


class NativeInstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'setup.exe'
        self.path.write_bytes(b'verified fixture')
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_reverification_prevents_any_native_launch_of_tampered_file(self):
        with patch.object(setup, 'installer_supported', return_value=True), \
             patch.object(setup.ctypes, 'WinDLL', create=True) as native:
            with self.assertRaises(ValueError):
                setup.run_installer(self.path)
        native.assert_not_called()

    def test_native_installer_is_interactive_elevated_and_waited(self):
        shell, kernel = Mock(), Mock()
        def execute(pointer):
            info = pointer._obj
            self.assertEqual(info.lpVerb, 'runas')
            self.assertEqual(info.lpFile, str(self.path.resolve()))
            self.assertIsNone(info.lpParameters)  # No silent switch.
            self.assertEqual(info.nShow, 1)
            info.hProcess = 123
            return True
        shell.ShellExecuteExW.side_effect = execute
        kernel.WaitForSingleObject.return_value = 0
        kernel.GetExitCodeProcess.side_effect = lambda handle, pointer: (setattr(pointer._obj, 'value', 3010) or True)
        with patch.object(setup, 'installer_supported', return_value=True), \
             patch.object(setup, 'INSTALLER_SHA256', self.digest), \
             patch.object(setup.ctypes, 'WinDLL', side_effect=[shell, kernel], create=True):
            self.assertEqual(setup.run_installer(self.path), 3010)
        kernel.CloseHandle.assert_called_once_with(123)

    def test_uac_cancel_is_a_cancel_result_without_retry(self):
        shell, kernel = Mock(), Mock()
        shell.ShellExecuteExW.return_value = False
        with patch.object(setup, 'installer_supported', return_value=True), \
             patch.object(setup, 'INSTALLER_SHA256', self.digest), \
             patch.object(setup.ctypes, 'WinDLL', side_effect=[shell, kernel], create=True), \
             patch.object(setup.ctypes, 'get_last_error', return_value=1223, create=True):
            with self.assertRaises(setup.InstallationCancelled):
                setup.run_installer(self.path)
        kernel.WaitForSingleObject.assert_not_called()

    def install_result(self, code, status):
        with patch.object(setup, 'installer_supported', return_value=True), \
             patch.object(setup, 'download_installer', return_value=self.path), \
             patch.object(setup, 'run_installer', return_value=code), \
             patch.object(setup, 'check_installation', return_value=status):
            return setup.install_usbpcap()

    def test_zero_exit_is_not_assumed_ready(self):
        result = self.install_result(0, {'state':'installed_not_ready', 'executable':'', 'message':'Restart Windows.'})
        self.assertEqual(result['state'], 'installed_not_ready')

    def test_reboot_request_is_reported_without_rebooting(self):
        result = self.install_result(3010, {'state':'ready', 'executable':'tool', 'message':'ready'})
        self.assertEqual(result['state'], 'restart_required')
        self.assertIn('does not trigger a reboot', result['message'])

    def test_failed_installer_is_not_reported_as_installed(self):
        result = self.install_result(1, {'state':'ready', 'executable':'tool', 'message':'ready'})
        self.assertEqual(result['state'], 'installer_failed')


class InstallationConsentTests(unittest.TestCase):
    def test_declining_offer_does_not_download_or_start_installer(self):
        wizard = Mock()
        wizard.busy = False
        wizard.session = None
        with patch('usb_investigation.wizard.installer_supported', return_value=True), \
             patch('usb_investigation.wizard.messagebox.askyesno', return_value=False), \
             patch('usb_investigation.wizard.install_usbpcap') as installer:
            InvestigationWizard.offer_install(wizard)
        installer.assert_not_called()
        wizard._background.assert_not_called()
        self.assertIn('Nothing was downloaded', wizard.setup_status.set.call_args.args[0])

    def test_accepting_offer_schedules_setup_after_confirmation(self):
        wizard = Mock()
        wizard.busy = False
        wizard.session = None
        with patch('usb_investigation.wizard.installer_supported', return_value=True), \
             patch('usb_investigation.wizard.messagebox.askyesno', return_value=True), \
             patch('usb_investigation.wizard.install_usbpcap') as installer:
            InvestigationWizard.offer_install(wizard)
            self.assertTrue(wizard.installing)
            installer.assert_not_called()  # Work is scheduled, not run on Tk's thread.
            wizard._background.call_args.args[0]()
            installer.assert_called_once()

    def test_separate_entry_and_spec_do_not_import_tray(self):
        root = Path(__file__).resolve().parents[1]
        entry = (root / 'usb_investigator.pyw').read_text()
        self.assertNotIn('battery_tray', entry)
        spec = ast.parse((root / 'usb_investigation.spec').read_text())
        self.assertIn('USBInvestigation', ast.literal_eval(next(kw.value for node in ast.walk(spec)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'EXE'
                      for kw in node.keywords if kw.arg == 'name')))


if __name__ == '__main__':
    unittest.main()
