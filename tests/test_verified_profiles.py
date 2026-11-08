"""Known-family capture -> live validation -> atomic profile -> tray loading."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import load_tray, TestApp
from test_usb_investigation import packet, descriptor, global_header, TARGET
from protocol_profiles.schema import valid_binding, valid_profile
from protocol_profiles import store, templates
from protocol_profiles.runtime import ProfileProtocol
from usb_investigation.capture import CaptureSession
from usb_investigation.profiles import match_capture, validate_and_save, query_signature
from protocols import get_all_handlers
from protocols.razer import _razer_get_battery_query, _razer_crc
from protocols.wlmouse import WLMOUSE_QUERY


def selector(number=2, page=0xFF02, usage=2):
    return {'interface_number': number, 'usage_page': page, 'usage': usage}


def setup_packet(payload, interface=2, report_id=8, get=False):
    setup = struct.pack('<BBHHH', 0xA1 if get else 0x21, 1 if get else 9, 0x0300 | report_id, interface, 64 if get else len(payload))
    return packet(setup + payload, stamp=1002, endpoint=0, transfer=2, stage=0, irp=22)


def family_fixture(template):
    primary = selector()
    variant = ''
    if template == 'rakk-v1':
        vid, pid = 0x25A7, 0xFA7C
        interfaces = [primary, selector(3, 0xFF01, 0)]
        query = setup_packet(bytes([8, 4] + [0] * 14 + [0x49]))
        payload = bytes([9, 4, 0, 0, 0, 0, 72, 0])
        reply = lambda stamp: packet(payload, stamp=stamp)
        variant = 'report08'
    elif template == 'beken-v1':
        vid, pid = 0x1D57, 0xFA60
        interfaces = [selector(2, 10, 0)]
        query = b''
        payload = bytes([3, 0x55, 0x40, 0, 72, 0, 0, 0])
        reply = lambda stamp: packet(payload, stamp=stamp)
        variant = 'passive'
    elif template == 'compx-v1':
        vid, pid = 0x3554, 0xF58A
        interfaces = [selector(2, 0xFF04, 1)]
        query = setup_packet(b'', report_id=6, get=True)
        payload = bytes([6, 0, 0, 0, 72, 0])
        reply = lambda stamp: packet(payload, stamp=stamp, transfer=2, stage=3)
        variant = 'get06'
    elif template == 'razer-v1':
        vid, pid = 0x1532, 0x00AA
        interfaces = [selector(3, 1, 6)]
        query = setup_packet(_razer_get_battery_query(), interface=3, report_id=0)
        data = [0] * 90
        data[0:2] = [2, 0x1F]
        data[5:10] = [2, 7, 2, 184, 0]
        data[88] = _razer_crc(data)
        payload = bytes(data)
        reply = lambda stamp: packet(payload, stamp=stamp, transfer=2, stage=3)
        variant = 'feature90'
    else:
        vid, pid = 0x36A7, 0xA887
        interfaces = [selector(0, 0xFFFF, 0)]
        query = setup_packet(bytes([0] + WLMOUSE_QUERY + [0] * (64-len(WLMOUSE_QUERY))), interface=0, report_id=0)
        payload = bytes([0xA1, 0, 2, 2, 0, 0x83, 0, 72])
        reply = lambda stamp: packet(payload, stamp=stamp, transfer=2, stage=3)
        variant = 'feature83'
    device = {'vid':vid, 'pid':pid, 'product':'Compatible Gaming Mouse', 'manufacturer':'Test', 'interfaces': interfaces}
    raw = global_header() + packet(descriptor(vid, pid), stamp=1000, transfer=2, stage=3) + query + reply(1003) + reply(1004)
    return device, raw, payload, variant


def verified_profile():
    return {'schema_version':1, 'vid':0x25A7, 'pid':0xFA7C, 'name':'Gaming Mouse',
            'template':'rakk-v1', 'variant':'report08',
            'interfaces': {'primary':selector(), 'reply':selector(3,0xFF01,0)},
            'validation': {'capture_sha256':'a'*64, 'capture_matches':2, 'capture_mismatches':0,
                'live_samples':[{'percent':72,'charging':False} for _ in range(3)],
                'reference_percent':72, 'reference_charging':False,
                'verified_at_utc':datetime.now(timezone.utc).isoformat()}}


def endpoints(profile):
    return [{**value, 'vendor_id':profile['vid'], 'product_id':profile['pid'],
             'path':role.encode(), 'serial_number':'', 'product_string':profile['name']}
            for role, value in profile['interfaces'].items()]


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name) / 'profiles'
        self.patch = patch.object(store, 'profile_directory', return_value=self.config)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def session(self, template='rakk-v1', modify=None):
        device, raw, _, _ = family_fixture(template)
        if modify:
            device, raw = modify(device, raw)
        session = CaptureSession(self.directory.name, device, TARGET, 'Official software', 10)
        session.labels.append({'timestamp':1001,'battery_percent':72,'charging':False})
        (session.directory/'capture.raw.pcap').write_bytes(raw)
        session.stop()
        _, summary = session.finalize()
        return session, summary

    def test_all_five_families_match_and_save_after_three_live_readings(self):
        for template in ('rakk-v1','beken-v1','compx-v1','razer-v1','wlmouse-v1'):
            with self.subTest(template=template):
                session, summary = self.session(template)
                match = match_capture(session,summary)
                self.assertEqual(match['state'],'candidate',match)
                self.assertEqual(match['template'],template)
                self.assertFalse((self.config / f"{session.device['vid']:04x}-{session.device['pid']:04x}.json").exists())
                result = validate_and_save(match,72,False,reader=Mock(return_value=(72,False)))
                self.assertTrue(result['saved'],result)
                profile = json.loads((self.config/result['profile_file']).read_text())
                self.assertTrue(valid_profile(profile))
                self.assertEqual(profile['template'],template)
                session.record_profile_result(result)
                self.assertEqual(json.loads((session.directory/'profile-result.json').read_text())['state'],'saved')

    def test_label_or_charging_mismatch_does_not_propose_profile(self):
        for reference, charging in ((20,False),(72,True)):
            session,summary = self.session()
            session.labels[0].update(battery_percent=reference,charging=charging)
            result = match_capture(session,summary)
            self.assertEqual(result['state'],'rejected')
        self.assertFalse(self.config.exists())

    def test_unknown_query_even_with_plausible_rakk_reply_is_rejected(self):
        def modify(device,raw):
            return device,raw.replace(bytes([8,4]+[0]*14+[0x49]),bytes([8,5]+[0]*14+[0x48]))
        session, summary = self.session(modify=modify)
        self.assertEqual(match_capture(session,summary)['state'],'rejected')

    def test_unconfirmed_identity_changed_capture_and_missing_labels_are_rejected(self):
        session,summary = self.session()
        self.assertEqual(match_capture(session,{**summary,'device_identity':'unverified'})['state'],'rejected')
        original = session.labels.pop()
        self.assertEqual(match_capture(session,summary)['state'],'rejected')
        session.labels.append(original)
        with (session.directory/'capture.pcap').open('ab') as output:
            output.write(b'changed')
        self.assertEqual(match_capture(session,summary)['state'],'rejected')

    def test_live_mismatch_never_overwrites_existing_profile(self):
        old = verified_profile()
        path = store.save_profile(old)
        before = path.read_bytes()
        session,summary = self.session()
        match = match_capture(session,summary)
        result = validate_and_save(match,72,False,reader=Mock(return_value=(50,False)))
        self.assertFalse(result['saved'])
        self.assertEqual(path.read_bytes(),before)

    def test_missing_live_readings_and_multiple_working_bindings_are_rejected(self):
        session,summary = self.session()
        match = match_capture(session,summary)
        result = validate_and_save(match,72,False,reader=Mock(return_value=(None,None)))
        self.assertFalse(result['saved'])
        match['candidates'].append(copy.deepcopy(match['candidates'][0]))
        result = validate_and_save(match,72,False,reader=Mock(return_value=(72,False)))
        self.assertFalse(result['saved'])
        self.assertFalse(self.config.exists())

    def test_one_missing_reading_can_be_retried_but_three_matches_are_required(self):
        session,summary = self.session()
        reader = Mock(side_effect=[(None,None),(72,False),(71,False),(72,False)])
        self.assertTrue(validate_and_save(match_capture(session,summary),72,False,reader=reader)['saved'])
        self.assertEqual(reader.call_count,4)

    def test_validation_deadline_cannot_leave_other_bindings_unchecked(self):
        session, summary = self.session()
        match = match_capture(session, summary)
        match['candidates'].append(copy.deepcopy(match['candidates'][0]))
        clock = [0]
        def reader(profile, timeout):
            clock[0] += 10
            return 72, False
        with patch('usb_investigation.profiles.time.monotonic', side_effect=lambda: clock[0]):
            result = validate_and_save(match, 72, False, reader=reader)
        self.assertFalse(result['saved'])
        self.assertFalse(self.config.exists())

    def test_compx_vendor_takes_priority_for_shared_passive_report(self):
        def modify(device, raw):
            device = {**device, 'vid': 0x3554}
            return device, raw.replace(descriptor(0x1D57, device['pid']), descriptor(device['vid'], device['pid']))
        session, summary = self.session('beken-v1', modify=modify)
        match = match_capture(session, summary)
        self.assertEqual(match['state'], 'candidate', match)
        self.assertEqual(match['template'], 'compx-v1')
        self.assertEqual(match['candidates'][0]['profile']['variant'], 'passive')

    def test_fixed_compx_active_variants_are_recognized(self):
        for report, payload in ((0, bytes([0, 6] + [0] * 62)), (6, bytes([6] + [0] * 63))):
            with self.subTest(report=report):
                def modify(device, raw):
                    original = setup_packet(b'', report_id=6, get=True)
                    return device, raw.replace(original, setup_packet(payload, report_id=report))
                session, summary = self.session('compx-v1', modify=modify)
                match = match_capture(session, summary)
                self.assertEqual(match['state'], 'candidate', match)
                self.assertEqual(match['candidates'][0]['profile']['variant'], f'query06-report{report}')

    def test_schema_and_disk_error_are_reported_without_success(self):
        session,summary = self.session()
        with patch('usb_investigation.profiles.save_profile',side_effect=OSError('read only')):
            result = validate_and_save(match_capture(session,summary),72,False,reader=Mock(return_value=(72,False)))
        self.assertFalse(result['saved'])
        self.assertIn('could not be saved',result['reason'])

    def test_arbitrary_feature_commands_cannot_become_template_queries(self):
        setup = struct.pack('<BBHHH',0x21,9,0x0308,2,17)
        self.assertIsNone(query_signature(setup,b'\x08\x99'+b'\x00'*15))
        self.assertIsNone(query_signature(bytes([0x21,9]),b''))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patch = patch.object(store,'profile_directory',return_value=Path(self.folder.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_rejects_code_commands_unknown_versions_and_unvalidated_profiles(self):
        for change in ({'schema_version':2},{'template':'custom-python'}, {'commands':['format']},
                       {'validation':{}}, {'variant':['bad']}, {'name':'bad\nname'}):
            with self.subTest(change=change):
                profile = {**verified_profile(),**change}
                self.assertFalse(valid_profile(profile))
                with self.assertRaises(ValueError):
                    store.save_profile(profile)
        self.assertEqual(store.load_profiles(),[])

    def test_roundtrip_disabled_corrupt_oversized_and_symlink_files(self):
        profile = verified_profile()
        path = store.save_profile(profile)
        self.assertEqual(store.load_profiles(),[profile])
        path.rename(path.with_suffix('.json.disabled'))
        root = Path(self.folder.name)
        (root/'broken.json').write_text('{')
        (root/'large.json').write_text(' '*(store.MAX_PROFILE_BYTES+1))
        if hasattr(Path,'symlink_to'):
            try:
                (root/'link.json').symlink_to(root/'broken.json')
            except OSError:
                pass
        with self.assertLogs('protocol_profiles.store',level='WARNING'):
            self.assertEqual(store.load_profiles(),[])

    def test_atomic_replace_failure_keeps_previous_profile(self):
        original = verified_profile()
        path = store.save_profile(original)
        modified = {**original,'name':'New Name'}
        with patch.object(Path,'replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                store.save_profile(modified)
        self.assertEqual(json.loads(path.read_text()),original)
        self.assertEqual(list(Path(self.folder.name).glob('*.tmp')),[])


class ReaderAndRuntimeTests(unittest.TestCase):
    def test_ambiguous_or_missing_devices_do_not_send_queries(self):
        profile = verified_profile()
        devices = endpoints(profile)
        devices.append({**devices[0],'path':b'another-mouse'})
        with patch.object(templates.hid,'enumerate',return_value=devices), \
             patch.object(templates.hid,'device') as opened:
            with self.assertRaises(ValueError):
                templates.read_sample(profile)
        opened.assert_not_called()

    def test_rakk_live_query_and_tray_use_same_template_then_close_handles(self):
        profile = verified_profile()
        class Bus:
            pending = False
            queries = []
            closed = []
        class Device:
            def open_path(self,path): self.path=path
            def set_nonblocking(self,value): pass
            def send_feature_report(self,data): Bus.queries.append(bytes(data)); Bus.pending=True
            def read(self,size):
                if self.path==b'reply' and Bus.pending:
                    Bus.pending=False
                    return [9,4,0,0,0,0,72,0]
                return []
            def close(self): Bus.closed.append(self.path)
        with patch.object(templates.hid,'enumerate',return_value=endpoints(profile)), \
             patch.object(templates.hid,'device',side_effect=Device), \
             patch('protocols.rakk.time.sleep'):
            self.assertEqual(templates.read_sample(profile),(72,False))
        self.assertEqual(Bus.queries,[bytes([8,4]+[0]*14+[0x49])])
        self.assertEqual(set(Bus.closed),{b'primary',b'reply'})

    def test_template_parsers_match_all_known_family_fixtures(self):
        for template in ('rakk-v1','beken-v1','compx-v1','razer-v1','wlmouse-v1'):
            _,_,payload,_ = family_fixture(template)
            self.assertEqual(templates.parse_report(template,payload),(72,False))
        self.assertEqual(templates.parse_report('compx-v1',bytes([6,0,0,100,100,100])),(None,None))

    def test_failure_cooldown_allows_builtin_fallback(self):
        handler = ProfileProtocol(verified_profile())
        app = TestApp()
        app.wait_for_poll = Mock()
        with patch('protocol_profiles.runtime.read_sample',return_value=(None,None)):
            handler.handle_device(app,b'primary','wireless','Mouse')
        self.assertGreater(handler.cooldown_until,time.monotonic())
        self.assertEqual(handler.find_device(),(None,None,None))

    def test_builtin_api_stays_unchanged_unless_profiles_requested(self):
        with patch.object(store,'load_profiles',return_value=[verified_profile()]):
            self.assertNotIsInstance(get_all_handlers()[0],ProfileProtocol)
            self.assertIsInstance(get_all_handlers(include_profiles=True)[0],ProfileProtocol)

    def test_saved_profile_is_loaded_on_tray_start_and_polls_before_builtins(self):
        tray = load_tray()
        app = tray.BatteryTrayApp()
        app.icon = Mock()
        real_update = app.update_device_state
        def update(path,name,battery,charging=False,activity=False):
            real_update(path,name,battery,charging,activity)
            app.on_exit(None,None)
        app.update_device_state = update
        with patch.object(store,'load_profiles',return_value=[verified_profile()]), \
             patch('protocol_profiles.runtime.resolve_bindings',return_value={'primary':b'primary','reply':b'reply'}), \
             patch('protocol_profiles.runtime.read_sample',return_value=(72,False)), \
             patch.object(tray,'device_info',return_value=None):
            app.poll_loop()
        self.assertEqual(app.last_battery,72)
        self.assertEqual(app.current_model,'Gaming Mouse')
        self.assertIsInstance(app._protocol_handlers[0],ProfileProtocol)

    def test_full_unknown_model_capture_validate_save_and_tray_sequence(self):
        device, raw, _, _ = family_fixture('rakk-v1')
        original_descriptor = descriptor(device['vid'],device['pid'])
        device.update(vid=0xABCD,pid=0x1234)
        raw = raw.replace(original_descriptor,descriptor(device['vid'],device['pid']))
        with tempfile.TemporaryDirectory() as root:
            session = CaptureSession(root,device,TARGET,'Manufacturer app',10)
            session.labels.append({'timestamp':1001,'battery_percent':72,'charging':False})
            (session.directory/'capture.raw.pcap').write_bytes(raw)
            session.stop()
            _, summary = session.finalize()
            match = match_capture(session,summary)
            self.assertEqual(match['state'],'candidate',match)
            candidate = match['candidates'][0]['profile']
            class Bus:
                pending = False
                queries = []
                closed = []
            class Device:
                def open_path(self,path): self.path=path
                def set_nonblocking(self,value): pass
                def send_feature_report(self,data): Bus.queries.append(bytes(data)); Bus.pending=True
                def read(self,size):
                    if self.path==b'reply' and Bus.pending:
                        Bus.pending=False
                        return [9,4,0,0,0,0,72,0]
                    return []
                def close(self): Bus.closed.append(self.path)
            def enumerate_hid(vid=0,pid=0):
                return [d for d in endpoints(candidate) if (not vid or d['vendor_id']==vid) and (not pid or d['product_id']==pid)]
            with patch.object(store,'profile_directory',return_value=Path(root)/'local-profiles'), \
                 patch.object(templates.hid,'enumerate',side_effect=enumerate_hid), \
                 patch.object(templates.hid,'device',side_effect=Device), patch('protocols.rakk.time.sleep'):
                self.assertTrue(all(h.find_device()[0] is None for h in get_all_handlers()))
                result = validate_and_save(match,72,False)
                self.assertTrue(result['saved'],result)
                session.record_profile_result(result)
                tray = load_tray()
                app = tray.BatteryTrayApp()
                app.icon = Mock()
                original_update = app.update_device_state
                def update(path,name,battery,charging=False,activity=False):
                    original_update(path,name,battery,charging,activity)
                    app.on_exit(None,None)
                app.update_device_state = update
                app.poll_loop()
                self.assertEqual(app.last_battery,72)
                self.assertTrue(app._using_local_profile)
                self.assertEqual(len(Bus.queries),4)  # Three live checks, one tray poll.
                self.assertEqual(len(Bus.closed),8)
                self.assertEqual(len(store.load_profiles()),1)
                self.assertTrue((session.directory/'profile-result.json').is_file())


if __name__ == '__main__':
    unittest.main()
