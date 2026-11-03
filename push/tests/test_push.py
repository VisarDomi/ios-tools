import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
import snapshot
import client
import worker


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / 'source'; self.source.mkdir()

    def test_freezes_working_edits_and_ignored_inputs_before_caller_continues(self):
        (self.source / 'Code').mkdir(); (self.source / 'Code/view.swift').write_text('accepted change')
        (self.source / 'Private').mkdir(); (self.source / 'Private/key').write_text('private input')
        captured = self.root / 'checkpoint'
        files, missing = snapshot.capture(self.source, captured, ['Code', 'Private'])
        self.assertFalse(missing); common.verify(captured, files)
        (self.source / 'Code/view.swift').write_text('subsequent work')
        self.assertEqual((captured / 'Code/view.swift').read_text(), 'accepted change')
        self.assertEqual(captured.stat().st_mode & 0o777, 0o700)
        (captured / 'Code/view.swift').write_text('unexpected mutation')
        with self.assertRaises(RuntimeError): common.verify(captured, files)

    def test_overlay_replaces_old_files_and_source_links_are_frozen(self):
        (self.source / 'Resources/Web').mkdir(parents=True)
        (self.source / 'Resources/Web/stale').write_text('stale')
        external = self.root / 'web'; external.mkdir(); (external / 'game').write_text('new game')
        (self.source / 'Link').symlink_to(external, target_is_directory=True)
        out = self.root / 'checkpoint'
        files, _ = snapshot.capture(self.source, out, ['Resources', 'Link'], overlays={'Resources/Web': external})
        self.assertFalse((out / 'Resources/Web/stale').exists())
        self.assertFalse((out / 'Link').is_symlink()); common.verify(out, files)
        (external / 'game').write_text('future game')
        self.assertEqual((out / 'Link/game').read_text(), 'new game')

    def test_source_change_during_capture_refuses_the_checkpoint(self):
        file = self.source / 'file'; file.write_text('before'); original = snapshot.stamp; calls = 0
        def changing(path):
            nonlocal calls
            calls += 1
            if calls == 2: file.write_text('changed while copying')
            return original(path)
        out = self.root / 'checkpoint'
        with mock.patch.object(snapshot, 'stamp', side_effect=changing), self.assertRaises(RuntimeError):
            snapshot.capture(self.source, out, ['file'])
        self.assertFalse(out.exists())

    def test_only_explicit_generated_inputs_can_be_inherited(self):
        out = self.root / 'checkpoint'
        with self.assertRaises(FileNotFoundError): snapshot.capture(self.source, out, ['missing'])
        files, missing = snapshot.capture(self.source, out, ['missing'], allow_missing=['missing'])
        self.assertEqual((files, missing), ({}, ['missing']))
        for item in ['/outside', '../outside', 'sub/../outside']:
            with self.assertRaises(ValueError): common.relative(item)

    def test_atomic_state_keeps_previous_record_after_interruption(self):
        file = self.root / 'state.json'; common.save(file, {'phase': 'queued'})
        with mock.patch.object(common.os, 'replace', side_effect=OSError('power cut')), self.assertRaises(OSError):
            common.save(file, {'phase': 'installed'})
        self.assertEqual(common.load(file), {'phase': 'queued'})
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob('.writing-*')))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.store = self.base / 'queue'; self.checkpoints = self.base / 'checkpoints'
        self.renewal = self.base / 'renewal'; self.tools = self.base / 'tools'; self.tools.mkdir()
        common.save(self.tools / 'ios-tools.local.json', {'team': 'TEAM', 'device': 'PHONE'})
        self.patch = mock.patch.multiple(worker, STORE=self.store, CHECKPOINTS=self.checkpoints,
                                        RENEWAL=self.renewal, SIGNING_LOCK=self.base / 'signing.lock', TOOLS=self.tools)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.job = 'job-1'; self.metadata, self.source = worker.paths(self.job)
        self.metadata.mkdir(parents=True); (self.source / 'Sources').mkdir(parents=True)
        (self.source / 'Sources/view.swift').write_text('reviewed source')
        config = {'name': 'demo', 'root': '/pc/demo', 'app': 'build/Demo.app', 'bundleIds': ['com.test.Demo'],
                  'inputs': ['Sources'], 'build': ['python3', 'build.py'],
                  'environment': {'DEVELOPMENT_TEAM': '__IOS_PUSH_TEAM__', 'SIGNING_DEVICE': '__IOS_PUSH_DEVICE__'}}
        self.request = {'version': 1, 'id': self.job, 'repo': 'demo', 'app': 'demo', 'createdAt': time.time(),
                        'sourceRoot': '/pc/demo', 'sourceRevision': 'abc123', 'config': config,
                        'files': common.manifest(self.source), 'carry': [], 'neverLaunch': True}
        self.request['sourceHash'] = common.source_hash(self.request['files'])
        common.save(self.metadata / 'request.json', self.request); worker.ready(self.job)
        self.config = worker.configuration(self.request, self.source)
        common.save(self.metadata / 'config.json', self.config)
        self.app = self.source / self.config['app']; self.app.mkdir(parents=True)
        (self.app / 'Demo').write_bytes(b'signed device binary')
        self.profiles = {'TEAM.com.test.Demo': {'expires': time.time() + 365 * 86400, 'uuid': 'PROFILE', 'id': 'TEAM.com.test.Demo'}}
        self.details = {'bundle': 'com.test.Demo', 'version': '2', 'profiles': self.profiles}
        self.receipt = {'complete': True, 'inputHash': worker.input_hash(self.config),
                        'appHash': worker.refresh.fingerprint(self.app.parent, [self.app.name]), **self.details}
        common.save(self.metadata / 'build-receipt.json', self.receipt)
        self.old = dict(self.config, root=str(self.base / 'old-source'))
        (Path(self.old['root']) / 'Sources').mkdir(parents=True)
        (Path(self.old['root']) / 'Sources/view.swift').write_text('previous source')
        common.save(worker.config_path('demo', 'demo'), self.old)
        self.state_path = Path(self.config['stateDir']) / 'state.json'
        common.save(self.state_path, {'inputHash': worker.input_hash(self.old), 'lastSuccess': time.time() - 86400,
                                      'installedProfiles': self.profiles})
        self.calls = []
        def run(command, **kwargs):
            self.calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout='')
        self.run = mock.patch.object(worker.subprocess, 'run', side_effect=run); self.run.start(); self.addCleanup(self.run.stop)
        self.verify = mock.patch.object(worker, 'verify_app', return_value=self.details); self.verify.start(); self.addCleanup(self.verify.stop)
        self.profile_patch = mock.patch.object(worker.refresh, 'app_profiles', return_value=self.profiles); self.profile_patch.start(); self.addCleanup(self.profile_patch.stop)

    def test_install_confirmation_moves_only_this_app_to_its_frozen_checkpoint(self):
        sibling = dict(self.old, name='other', bundleIds=['com.test.Other'])
        common.save(worker.config_path('demo', 'other'), sibling)
        previous_success = common.load(self.state_path)['lastSuccess']
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}]]):
            worker.deliver(self.job)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'installed')
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], str(self.source))
        self.assertEqual(common.load(worker.config_path('demo', 'other')), sibling)
        state = common.load(self.state_path)
        self.assertNotIn('pendingPush', state); self.assertEqual(state['lastSuccess'], previous_success)
        self.assertEqual(state['inputHash'], self.receipt['inputHash'])
        self.assertFalse(any('launch' in str(command) or 'uninstall' in str(command) for command, _ in self.calls))

    def enable_watch(self):
        common.save(self.tools / 'ios-tools.local.json', {'team': 'TEAM', 'device': 'PHONE', 'watchDevice': 'WATCH'})
        request = common.load(self.metadata / 'request.json')
        request['config']['bundleIds'].append('com.test.Demo.watch')
        request['config']['watch'] = {'app': 'Watch/Demo.app', 'bundleId': 'com.test.Demo.watch', 'device': '__IOS_PUSH_WATCH_DEVICE__'}
        common.save(self.metadata / 'request.json', request)
        frozen = common.load(self.metadata / 'ready.json'); frozen['requestHash'] = common.digest(self.metadata / 'request.json')
        common.save(self.metadata / 'ready.json', frozen)
        self.config = worker.configuration(request, self.source); common.save(self.metadata / 'config.json', self.config)
        watch = self.app / 'Watch/Demo.app'; watch.mkdir(parents=True); (watch / 'Demo').write_bytes(b'signed Watch binary')
        self.profiles['TEAM.com.test.Demo.watch'] = dict(self.profiles['TEAM.com.test.Demo'], id='TEAM.com.test.Demo.watch')
        self.receipt['appHash'] = worker.refresh.fingerprint(self.app.parent, [self.app.name])
        common.save(self.metadata / 'build-receipt.json', self.receipt)

    def test_offline_watch_preserves_phone_delivery_and_defers_approval(self):
        self.enable_watch()
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}], None]):
            worker.deliver(self.job)
        state = common.load(self.metadata / 'state.json')
        self.assertEqual(state['phase'], 'awaiting_watch'); self.assertIn('phoneDelivery', state)
        self.assertGreater(state['nextAttempt'], time.time())
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], self.old['root'])
        self.assertIn('pendingPush', common.load(self.state_path))
        self.assertEqual(sum('install' in command for command, _ in self.calls), 1)
        with common.locked(worker.SIGNING_LOCK): pass

    def test_watch_recovery_after_restart_does_not_reinstall_or_require_phone(self):
        self.test_offline_watch_preserves_phone_delivery_and_defers_approval()
        self.calls.clear()
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo.watch', 'bundleVersion': '2'}]]) as catalog:
            worker.deliver(self.job)
        self.assertTrue(all(call.args[0]['device'] == 'WATCH' for call in catalog.call_args_list))
        installs = [command for command, _ in self.calls if 'install' in command]
        self.assertEqual(len(installs), 1); self.assertIn('WATCH', installs[0])
        state = common.load(self.metadata / 'state.json')
        self.assertEqual((state['phase'], state['watchVersion']), ('installed', '2'))
        self.assertNotIn('pendingPush', common.load(self.state_path))
        self.assertFalse(any('launch' in command or 'uninstall' in command for command, _ in self.calls))

    def test_wrong_watch_version_never_approves_phone_only_delivery(self):
        self.enable_watch()
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}], [], [{'bundleIdentifier': 'com.test.Demo.watch', 'bundleVersion': 'old'}]]):
            worker.deliver(self.job)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'awaiting_watch')
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], self.old['root'])

    def test_watch_target_requires_a_distinct_configured_device_and_contained_app(self):
        self.enable_watch()
        request = common.load(self.metadata / 'request.json')
        common.save(self.tools / 'ios-tools.local.json', {'team': 'TEAM', 'device': 'PHONE'})
        with self.assertRaisesRegex(RuntimeError, 'watchDevice'): worker.configuration(request, self.source)
        common.save(self.tools / 'ios-tools.local.json', {'team': 'TEAM', 'device': 'PHONE', 'watchDevice': 'PHONE'})
        with self.assertRaisesRegex(RuntimeError, 'paired Watch'): worker.configuration(request, self.source)
        common.save(self.tools / 'ios-tools.local.json', {'team': 'TEAM', 'device': 'PHONE', 'watchDevice': 'WATCH'})
        request['config']['watch']['app'] = '../foreign.app'
        with self.assertRaisesRegex(RuntimeError, 'paired Watch'): worker.configuration(request, self.source)

    def test_native_watch_verification_requires_its_device_platform_and_app_group(self):
        self.enable_watch(); self.verify.stop()
        self.config['watch']['appGroups'] = ['group.test']
        entries = [(self.app, 'com.test.Demo', 'iPhoneOS'),
                   (self.app / 'Watch/Demo.app', 'com.test.Demo.watch', 'WatchOS')]
        for entry, bundle, platform in entries:
            (entry / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': bundle, 'CFBundleSupportedPlatforms': [platform],
                'CFBundleVersion': '2', 'CFBundleExecutable': 'Demo'}))
            (entry / 'embedded.mobileprovision').write_text('fixture profile')
        watch_device = 'WATCH'; groups = ['group.test']
        def signed(command, **kwargs):
            watch = '/Watch/' in str(command[-1]); bundle = entries[int(watch)][1]
            if command[0] == 'security':
                return plistlib.dumps({'TeamIdentifier': ['TEAM'], 'ProvisionedDevices': [watch_device if watch else 'PHONE'],
                    'Entitlements': {'com.apple.security.application-groups': groups if watch else []}})
            if command[0] == 'codesign':
                return plistlib.dumps({'application-identifier': 'TEAM.' + bundle,
                    'com.apple.security.application-groups': groups if watch else []})
            if command[0] == 'lipo': return 'arm64'
            raise AssertionError(command)
        with mock.patch.object(worker.subprocess, 'check_output', side_effect=signed):
            self.assertEqual(worker.verify_app(self.config, self.app)['version'], '2')
            watch_device = 'PHONE'
            with self.assertRaisesRegex(RuntimeError, 'target device'): worker.verify_app(self.config, self.app)
            watch_device = 'WATCH'; groups = []
            with self.assertRaisesRegex(RuntimeError, 'App Group'): worker.verify_app(self.config, self.app)

    def test_lost_confirmation_stays_pending_and_recovery_finishes_idempotently(self):
        with mock.patch.object(worker, 'catalog', side_effect=[[], None]), self.assertRaises(worker.Retry): worker.deliver(self.job)
        self.assertEqual(common.load(self.state_path)['pendingPush']['id'], self.job)
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], self.old['root'])
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}]]): worker.deliver(self.job)
        self.assertNotIn('pendingPush', common.load(self.state_path))

    def test_ota_is_not_an_installed_or_approved_result(self):
        self.run.stop()
        def publish(command, **kwargs):
            self.calls.append((command, kwargs)); return subprocess.CompletedProcess(command, 10)
        with mock.patch.object(worker.subprocess, 'run', side_effect=publish), mock.patch.object(worker, 'catalog', return_value=None):
            worker.deliver(self.job, allow_ota=True)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'awaiting_ota')
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], self.old['root'])
        self.assertIn('pendingPush', common.load(self.state_path))
        self.assertEqual(self.calls[-1][1]['env']['IOS_PUSH_JOB_ID'], self.job)

    def test_changed_source_and_request_never_reach_the_phone(self):
        (self.source / 'Sources/view.swift').write_text('unexpected source')
        with mock.patch.object(worker, 'catalog') as catalog, self.assertRaises(RuntimeError): worker.deliver(self.job)
        catalog.assert_not_called()
        request = common.load(self.metadata / 'request.json'); request['config']['bundleIds'] = ['com.test.Foreign']; common.save(self.metadata / 'request.json', request)
        with mock.patch.object(worker, 'catalog') as catalog, self.assertRaises(RuntimeError): worker.deliver(self.job)
        catalog.assert_not_called()

    def test_interrupted_artifact_requests_a_rebuild_before_device_work(self):
        (self.app / 'Demo').write_bytes(b'incomplete after power loss')
        with mock.patch.object(worker, 'catalog') as catalog, self.assertRaises(worker.Rebuild): worker.deliver(self.job)
        catalog.assert_not_called()

    def test_profile_deadlines_cannot_regress(self):
        state = common.load(self.state_path); state['installedProfiles']['TEAM.com.test.Demo']['expires'] += 86400; common.save(self.state_path, state)
        with mock.patch.object(worker, 'catalog') as catalog, self.assertRaises(worker.Rebuild): worker.deliver(self.job)
        catalog.assert_not_called()

    def test_signing_lock_prevents_install_and_device_queries(self):
        with common.locked(worker.SIGNING_LOCK), mock.patch.object(worker, 'catalog') as catalog, self.assertRaises(BlockingIOError):
            worker.deliver(self.job)
        catalog.assert_not_called()

    def test_newer_push_supersedes_old_delivery_without_phone_work(self):
        common.save(self.state_path, {'pendingPush': {'id': 'newer-job', 'createdAt': self.request['createdAt'] - 100, 'sequence': 999}})
        with mock.patch.object(worker, 'catalog') as catalog: worker.deliver(self.job)
        catalog.assert_not_called(); self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'superseded')

    def test_cancel_during_reachable_check_stops_before_install(self):
        def cancel(_config, _output): worker.control(self.job, 'cancel'); return []
        with mock.patch.object(worker, 'catalog', side_effect=cancel): worker.deliver(self.job)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'cancelled')
        self.assertFalse(any('install' in command for command, _ in self.calls))
        self.assertNotIn('pendingPush', common.load(self.state_path))

    def test_cancel_after_possible_delivery_is_refused(self):
        common.update(self.metadata / 'state.json', 'installing', installAttempted=True)
        with self.assertRaises(RuntimeError): worker.control(self.job, 'cancel')

    def test_diagnostic_environment_and_foreign_registration_are_refused(self):
        request = json.loads(json.dumps(self.request)); request['config']['environment']['SIMULATOR'] = '1'
        with self.assertRaises(ValueError): worker.configuration(request, self.source)
        common.save(worker.config_path('foreign', 'stolen'), dict(self.old, name='stolen'))
        with self.assertRaises(ValueError): worker.configuration(self.request, self.source)

    def test_unfinished_upload_is_not_ready(self):
        (self.metadata / 'ready.json').unlink(); (self.source / 'Sources/view.swift').write_text('partial upload')
        with self.assertRaises(RuntimeError): worker.ready(self.job)
        self.assertFalse((self.metadata / 'ready.json').exists())

    def test_pruning_keeps_all_registered_and_pending_source_checkpoints(self):
        common.save(worker.config_path('demo', 'demo'), self.config)
        for number in range(5):
            metadata, source = worker.paths('old-' + str(number)); source.mkdir(parents=True)
            common.save(metadata / 'state.json', {'phase': 'validated'})
        worker.prune()
        self.assertTrue(self.source.exists())
        self.assertLessEqual(len(list(self.checkpoints.iterdir())), 3)

    def test_pairing_recovery_runs_outside_the_signing_lock(self):
        self.run.stop()
        def repair(command, **kwargs):
            with common.locked(worker.SIGNING_LOCK): pass
            self.assertIn('phone-pairing', command[0]); return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(worker, 'deliver', side_effect=[worker.RecoverTransport(), None]) as delivery, mock.patch.object(worker.subprocess, 'run', side_effect=repair):
            worker.run_job(self.job)
        self.assertEqual(delivery.call_count, 2)
        self.assertTrue(delivery.call_args.kwargs['allow_ota'])

    def test_validate_only_never_contacts_the_phone(self):
        request = common.load(self.metadata / 'request.json'); request['validateOnly'] = True
        common.save(self.metadata / 'request.json', request)
        frozen = common.load(self.metadata / 'ready.json'); frozen['requestHash'] = common.digest(self.metadata / 'request.json'); common.save(self.metadata / 'ready.json', frozen)
        with mock.patch.object(worker, 'deliver') as delivery, mock.patch.object(worker, 'catalog') as catalog:
            worker.run_job(self.job)
        delivery.assert_not_called(); catalog.assert_not_called()
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'validated')

    def test_build_runs_from_snapshot_and_discards_inherited_diagnostic_flags(self):
        lock = (self.base / 'fd').open('a'); self.addCleanup(lock.close)
        with mock.patch.dict(os.environ, {'IOS_WORKLOAD_ACTIVE': '123', 'IOS_REFRESH_LOCK_FD': str(lock.fileno()), 'SIMULATOR': '1', 'DECODER_PROBE': '1'}):
            def building(command, **kwargs):
                self.assertEqual(kwargs['cwd'], self.source)
                self.assertNotIn('SIMULATOR', kwargs['env']); self.assertNotIn('DECODER_PROBE', kwargs['env'])
                self.assertEqual(kwargs['env']['SIGNING_DESTINATION'], 'generic/platform=iOS')
                self.app.mkdir(parents=True, exist_ok=True); (self.app / 'Demo').write_bytes(b'new product from snapshot')
                return subprocess.CompletedProcess(command, 0)
            with mock.patch.object(worker.subprocess, 'run', side_effect=building): worker.build_one(self.job)
        receipt = common.load(self.metadata / 'build-receipt.json')
        self.assertTrue(receipt['complete']); self.assertFalse(receipt['reused'])
        self.assertEqual(receipt['appHash'], worker.refresh.fingerprint(self.app.parent, [self.app.name]))

    def test_wrong_phone_version_cannot_approve_new_source(self):
        with mock.patch.object(worker, 'catalog', return_value=[{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': 'old'}]), self.assertRaises(worker.Retry):
            worker.deliver(self.job)
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], self.old['root'])
        self.assertIn('pendingPush', common.load(self.state_path))

    def test_retry_cannot_accept_mutated_frozen_sources(self):
        (self.source / 'Sources/view.swift').write_text('not the submitted source')
        with self.assertRaises(RuntimeError): worker.control(self.job, 'retry')

    def test_new_input_file_cannot_sneak_into_a_queued_build(self):
        (self.source / 'Sources/late.swift').write_text('not submitted')
        with self.assertRaises(RuntimeError): worker.verify_checkpoint(self.config, common.load(self.metadata / 'ready.json'))

    def test_queue_sequence_is_idempotent_and_does_not_use_sender_clock(self):
        first = common.load(self.metadata / 'ready.json')['sequence']
        worker.ready(self.job)
        self.assertEqual(common.load(self.metadata / 'ready.json')['sequence'], first)
        second_metadata, second_source = worker.paths('job-2'); (second_source / 'Sources').mkdir(parents=True)
        (second_source / 'Sources/view.swift').write_text('later accepted source')
        request = json.loads(json.dumps(self.request)); request.update(id='job-2', createdAt=1, files=common.manifest(second_source))
        request['sourceHash'] = common.source_hash(request['files']); common.save(second_metadata / 'request.json', request)
        worker.ready('job-2')
        self.assertGreater(common.load(second_metadata / 'ready.json')['sequence'], first)

    def test_identical_validation_build_is_reused_without_another_compile(self):
        second_metadata, second_source = worker.paths('job-2'); (second_source / 'Sources').mkdir(parents=True)
        (second_source / 'Sources/view.swift').write_text('reviewed source')
        request = json.loads(json.dumps(self.request)); request.update(id='job-2', files=common.manifest(second_source))
        request['sourceHash'] = common.source_hash(request['files']); common.save(second_metadata / 'request.json', request)
        worker.ready('job-2')
        import shutil
        def copy(source, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
        lock = (self.base / 'fd').open('a'); self.addCleanup(lock.close)
        with mock.patch.dict(os.environ, {'IOS_WORKLOAD_ACTIVE': '1', 'IOS_REFRESH_LOCK_FD': str(lock.fileno())}), mock.patch.object(worker, 'clone', side_effect=copy):
            worker.build_one('job-2')
        self.assertTrue(common.load(second_metadata / 'build-receipt.json')['reused'])
        self.assertFalse(any(command == ['python3', 'build.py'] for command, _ in self.calls))

    def test_cleanup_preserves_artifacts_and_declared_inputs(self):
        products = self.app.parent
        (products / 'Kit.o').write_text('compiler output')
        (products / 'Protected').mkdir(); (products / 'Protected/input').write_text('required input')
        config = dict(self.config, inputs=[*self.config['inputs'], 'build/Protected'])
        worker.cleanup_intermediates(config)
        self.assertTrue(self.app.exists()); self.assertTrue((products / 'Protected/input').exists())
        self.assertFalse((products / 'Kit.o').exists())


class WatchClientTests(unittest.TestCase):
    def test_project_tools_declaration_works_from_an_explicit_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'tools').mkdir()
            listing = {'repo': 't3-watch', 'apps': [{'name': 't3-watch'}]}
            (root / 'tools/renewal.py').write_text('print(' + repr(json.dumps(listing)) + ')')
            with mock.patch.object(client, 'projects', return_value={'t3-watch': {'root': str(root), 'declaration': 'tools/renewal.py'}}):
                repo, project, app = client.choose('t3-watch', source=str(root))
            self.assertEqual((repo, project['root'], app['name']), ('t3-watch', str(root), 't3-watch'))

    def test_follow_reports_pending_watch_without_waiting_for_physical_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); common.save(root / 'jobs/demo/state.json', {'phase': 'awaiting_watch'})
            with mock.patch.object(client, 'STORE', root), mock.patch.object(client.time, 'sleep') as sleep:
                with self.assertRaises(SystemExit) as result: client.show('demo', follow=True)
            self.assertEqual(result.exception.code, 10); sleep.assert_not_called()


if __name__ == '__main__': unittest.main()
