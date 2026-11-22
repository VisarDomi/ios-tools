import io
import json
import os
import shutil
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
    def test_upload_proceeds_while_another_job_holds_the_build_lock(self):
        status = {'booted': [], 'metrics': {'load': 3, 'diskGiB': 30, 'pressure': 1}}
        with common.locked(worker.SIGNING_LOCK), \
             mock.patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(status))):
            result = worker.receive('during-build', 'demo', 'demo')
        self.assertFalse(result['ready'])
        self.assertEqual(common.load(worker.paths('during-build')[0] / 'state.json')['phase'], 'receiving')

    def test_upload_admission_waits_for_guest_or_pressure_but_not_old_load(self):
        for status, reason in [
            ({'booted': [], 'metrics': {'load': 12.18, 'diskGiB': 30, 'pressure': 2}}, 'memory pressure'),
            ({'booted': [{'udid': 'guest'}], 'metrics': {'load': 2, 'diskGiB': 30}}, 'booted simulator'),
        ]:
            with self.subTest(status=status), mock.patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(status))), self.assertRaisesRegex(worker.Retry, reason):
                worker.receive('not-yet-admitted', 'demo', 'demo')
        self.assertTrue((worker.paths('not-yet-admitted')[0]/'incoming.json').exists())
        self.assertFalse(worker.paths('not-yet-admitted')[1].exists())
        status={'booted': [], 'metrics': {'load': 120, 'diskGiB': 30, 'pressure': 1}}
        with mock.patch.object(worker.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(status))):
            result=worker.receive('new-source','demo','demo')
        self.assertFalse(result['ready'])
        self.assertEqual(common.load(worker.paths('new-source')[0]/'state.json')['phase'],'receiving')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.store = self.base / 'queue'; self.checkpoints = self.base / 'checkpoints'
        self.renewal = self.base / 'renewal'; self.tools = self.base / 'tools'; self.tools.mkdir()
        common.save(self.tools / 'ios-tools.local.json', {'team': 'TEAM', 'device': 'PHONE'})
        self.patch = mock.patch.multiple(worker, STORE=self.store, CHECKPOINTS=self.checkpoints, MAC_HOME=self.base,
                                        RENEWAL=self.renewal, SIGNING_LOCK=self.base / 'signing.lock', TOOLS=self.tools,
                                        CHECKPOINT_LOCK=self.store / 'checkpoints.lock', KICK=self.store / 'kick')
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
        self.companion_patch = mock.patch.object(worker.refresh, 'companion_apps', return_value=None)
        self.companion_patch.start(); self.addCleanup(self.companion_patch.stop)

    def test_renewal_cache_validation_preserves_approved_product_and_state(self):
        common.save(worker.config_path('demo','demo'),self.config)
        common.save(self.state_path,dict(inputHash=worker.input_hash(self.config),lastSuccess=123,
                                         installedProfiles=self.profiles))
        before=self.app.joinpath('Demo').read_bytes();state=common.load(self.state_path)
        def clone(source,destination):
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(source,destination)
        def compile(config,*_):
            self.assertNotEqual(Path(config['root']),self.source)
            (Path(config['root'])/config['app']/'Demo').write_bytes(b'rebuilt preview')
            return 1.0,'stable-workspace+cas',[]
        with mock.patch.dict(os.environ,IOS_WORKLOAD_ACTIVE='1',IOS_REFRESH_LOCK_FD='0'), \
             mock.patch.object(worker,'clone',side_effect=clone), \
             mock.patch.object(worker,'compile_checkpoint',side_effect=compile):
            worker.renewal_build(worker.config_path('demo','demo'),validate_only=True)
        self.assertEqual(self.app.joinpath('Demo').read_bytes(),before)
        self.assertEqual(common.load(self.state_path),state)
        self.assertEqual(common.load(worker.config_path('demo','demo')),self.config)
        self.assertEqual(common.load(self.metadata/'build-receipt.json'),self.receipt)
        self.assertFalse(list((self.state_path.parent/'cache-validation').glob('renewal-source-*')))
        self.assertEqual(common.load(self.state_path.parent/'cache-validation/cache-report.json')['buildKind'],'renewal-validation')
        self.assertFalse(any('install' in str(c) or 'devicectl' in str(c) for c,_ in self.calls))

    def test_renewal_cache_rejects_pending_push_before_compilation(self):
        common.save(worker.config_path('demo','demo'),self.config)
        common.save(self.state_path,dict(inputHash=worker.input_hash(self.config),pendingPush={'id':'new'}))
        with mock.patch.dict(os.environ,IOS_WORKLOAD_ACTIVE='1',IOS_REFRESH_LOCK_FD='0'), \
             mock.patch.object(worker,'compile_checkpoint') as compile:
            with self.assertRaisesRegex(RuntimeError,'not currently approved'):
                worker.renewal_build(worker.config_path('demo','demo'))
            compile.assert_not_called()

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

    def test_first_verified_install_establishes_monthly_clock_and_scheduler(self):
        worker.config_path('demo', 'demo').unlink(); common.save(self.state_path, {})
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}]]):
            worker.deliver(self.job)
        state = common.load(self.state_path)
        self.assertGreater(state['lastSuccess'], time.time() - 5)
        self.assertGreater(state['nextDue'], time.time() + 27 * 86400)
        self.assertFalse(common.load(self.metadata / 'state.json')['renewalSchedulerPending'])
        self.assertTrue(common.load(worker.config_path('demo', 'demo'))['pushManagedScheduler'])

    def test_initial_scheduler_retry_does_not_reinstall_verified_phone_or_watch(self):
        self.enable_watch(); worker.config_path('demo', 'demo').unlink(); common.save(self.state_path, {})
        loaded = False; fail = True
        def schedule(command, **kwargs):
            nonlocal loaded
            self.calls.append((command, kwargs))
            if command[:2] == ['/bin/launchctl', 'print']: return subprocess.CompletedProcess(command, 0 if loaded else 1)
            if len(command) > 1 and command[1].endswith('refresh-installed.py'):
                if fail: raise subprocess.TimeoutExpired(command, 30)
                loaded = True
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(worker.subprocess, 'run', side_effect=schedule), mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}], [], [{'bundleIdentifier': 'com.test.Demo.watch', 'bundleVersion': '2'}]]):
            with self.assertRaises(worker.Retry): worker.deliver(self.job)
        self.assertTrue(common.load(self.metadata / 'state.json')['renewalSchedulerPending'])
        first_clock = common.load(self.state_path)['lastSuccess']; fail = False; self.calls.clear()
        with mock.patch.object(worker.subprocess, 'run', side_effect=schedule), mock.patch.object(worker, 'catalog') as catalog:
            worker.deliver(self.job)
        catalog.assert_not_called()
        self.assertFalse(any('devicectl' in command and 'install' in command for command, _ in self.calls))
        self.assertEqual(common.load(self.state_path)['lastSuccess'], first_clock)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'installed')

    def test_existing_paused_project_scheduler_is_not_resumed_by_an_update(self):
        old = common.load(worker.config_path('demo', 'demo')); old['pushManagedScheduler'] = True
        common.save(worker.config_path('demo', 'demo'), old)
        agent = self.base / 'Library/LaunchAgents/com.visar.renewal.demo.plist'
        agent.parent.mkdir(parents=True); agent.write_bytes(b'existing paused scheduler')
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}]]):
            worker.deliver(self.job)
        self.assertFalse(any(command[0] == '/bin/launchctl' for command, _ in self.calls))

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

    def test_companion_installs_exact_watch_artifact_before_approving_despite_native_discovery_failure(self):
        self.test_offline_watch_preserves_phone_delivery_and_defers_approval()
        self.calls.clear()
        actual = [{'bundleIdentifier': 'com.test.Demo.watch', 'bundleVersion': '2'}]
        with mock.patch.object(worker, 'catalog', return_value=None), \
                mock.patch.object(worker.refresh, 'companion_apps', return_value=actual) as proxy:
            worker.deliver(self.job)
        self.assertTrue(proxy.call_args.kwargs['install'])
        self.assertEqual(proxy.call_args.args[1]['app'], self.app / 'Watch/Demo.app')
        state = common.load(self.metadata / 'state.json')
        self.assertEqual((state['phase'], state['watchTransport']), ('installed', 'companion-lockdown'))
        self.assertFalse(any('install' in command or 'launch' in command for command, _ in self.calls))

    def test_wrong_companion_version_preserves_pending_delivery_and_old_renewal_root(self):
        self.test_offline_watch_preserves_phone_delivery_and_defers_approval()
        actual = [{'bundleIdentifier': 'com.test.Demo.watch', 'bundleVersion': 'old'}]
        with mock.patch.object(worker, 'catalog', return_value=None), \
                mock.patch.object(worker.refresh, 'companion_apps', return_value=actual):
            worker.deliver(self.job)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'awaiting_watch')
        self.assertEqual(common.load(worker.config_path('demo', 'demo'))['root'], self.old['root'])

    def test_companion_inventory_can_confirm_an_acknowledged_native_install(self):
        self.enable_watch()
        actual = [{'bundleIdentifier': 'com.test.Demo.watch', 'bundleVersion': '2'}]
        with mock.patch.object(worker, 'catalog', side_effect=[[], [{'bundleIdentifier': 'com.test.Demo', 'bundleVersion': '2'}], [], None]), \
                mock.patch.object(worker.refresh, 'companion_apps', return_value=actual) as proxy:
            worker.deliver(self.job)
        self.assertFalse(proxy.call_args.kwargs.get('install', False))
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'installed')

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

    def test_explicit_ota_skips_native_discovery_without_changing_frozen_source(self):
        before = (self.metadata / 'request.json').read_bytes()
        worker.control(self.job, 'ota')
        self.assertEqual((self.metadata / 'request.json').read_bytes(), before)
        self.run.stop()
        with mock.patch.object(worker.subprocess,'run',return_value=subprocess.CompletedProcess([],10)), \
             mock.patch.object(worker,'catalog',side_effect=AssertionError('No local device request for explicit OTA')):
            worker.deliver(self.job)
        self.assertEqual(common.load(self.metadata/'state.json')['phase'],'awaiting_ota')
        self.assertIn('pendingPush',common.load(self.state_path))
        self.assertEqual(common.load(worker.config_path('demo','demo'))['root'],self.old['root'])

    def test_new_builds_precede_already_published_transport_retries(self):
        common.update(self.metadata/'state.json','awaiting_ota',otaPublished=True,nextAttempt=0)
        new=self.store/'jobs'/'z-new';new.mkdir(parents=True)
        common.save(new/'ready.json',{})
        common.save(new/'state.json',{'phase':'queued'})
        order=[]
        with mock.patch.object(worker,'run_job',side_effect=order.append),mock.patch.object(worker,'prune'), \
             mock.patch.object(worker,'build_job',side_effect=lambda job: order.append(('build',job)) or True):
            worker.work()
        # The unbuilt job is built first (and, never completing here, not retried in this run).
        self.assertEqual(order,[('build','z-new'),self.job])

    def test_worker_sleeps_through_a_near_retry_and_exits_when_idle(self):
        common.update(self.metadata/'state.json','queued',nextAttempt=0)
        calls=[]
        def run(job):
            calls.append(job)
            if len(calls)==1: common.update(self.metadata/'state.json','waiting_mac',nextAttempt=time.time()+.3)
            else: common.update(self.metadata/'state.json','failed',nextAttempt=0)
        with mock.patch.object(worker,'run_job',side_effect=run),mock.patch.object(worker,'prune'):
            started=time.time(); worker.work()
        self.assertEqual(calls,[self.job,self.job])
        self.assertLess(time.time()-started,5)

    def test_job_left_due_by_its_run_is_not_rerun_by_the_same_worker(self):
        common.update(self.metadata/'state.json','queued',nextAttempt=0)
        with mock.patch.object(worker,'run_job') as run,mock.patch.object(worker,'prune'):
            worker.work()
        self.assertEqual(run.call_count,1)

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

    def test_failed_build_cache_cleanup_keeps_signed_app_source_and_reports(self):
        (self.metadata / 'config.json').unlink()
        common.update(self.metadata / 'state.json', 'failed')
        cache = self.source / 'build/Intermediates'; cache.mkdir(); (cache / 'objects').write_bytes(b'regenerable compiler data')
        (self.metadata / 'build.log').write_text('failure after signing')
        self.receipt['complete'] = False; common.save(self.metadata / 'build-receipt.json', self.receipt)
        worker.prune()
        self.assertFalse(cache.exists())
        self.assertEqual((self.app / 'Demo').read_bytes(), b'signed device binary')
        self.assertEqual((self.source / 'Sources/view.swift').read_text(), 'reviewed source')
        self.assertEqual((self.metadata / 'build.log').read_text(), 'failure after signing')

    def test_approved_roots_do_not_use_the_two_unreferenced_trial_slots(self):
        common.save(worker.config_path('demo', 'demo'), self.config)
        common.update(self.metadata / 'state.json', 'installed')
        for number in range(2):
            metadata, source = worker.paths('z-approved-' + str(number)); source.mkdir(parents=True)
            config = dict(self.config, root=str(source))
            common.save(worker.config_path('demo', 'approved-' + str(number)), config)
            common.save(metadata / 'state.json', {'phase': 'installed'})
            common.save(metadata / 'config.json', config)
        trials = []
        for number in range(2):
            metadata, source = worker.paths('a-trial-' + str(number)); source.mkdir(parents=True)
            common.save(metadata / 'state.json', {'phase': 'validated'}); trials.append(source)
        worker.prune()
        self.assertTrue(all(source.exists() for source in trials))
        self.assertTrue(self.source.exists())

    def test_pending_delivery_protects_its_matching_validated_artifact(self):
        common.update(self.metadata / 'state.json', 'validated')
        common.save(self.metadata / 'build-receipt.json', dict(self.receipt, sourceHash=self.request['sourceHash']))
        pending, source = worker.paths('zz-pending'); source.mkdir(parents=True)
        common.save(pending / 'state.json', {'phase': 'queued'})
        common.save(pending / 'request.json', {'repo': 'demo', 'app': 'demo'})
        common.save(pending / 'ready.json', {'sourceHash': self.request['sourceHash']})
        for number in range(2):
            metadata, recent = worker.paths('z-recent-' + str(number)); recent.mkdir(parents=True)
            common.save(metadata / 'state.json', {'phase': 'failed'})
        worker.prune()
        self.assertTrue(self.app.exists(), 'Do not delete the signed bytes a pending delivery can reuse')
        self.assertTrue(source.exists())

    def queue_second(self, job='job-2'):
        metadata, source = worker.paths(job); metadata.mkdir(parents=True)
        shutil.copytree(self.source / 'Sources', source / 'Sources')
        request = dict(self.request, id=job, files=common.manifest(source)); request['sourceHash'] = common.source_hash(request['files'])
        common.save(metadata / 'request.json', request); worker.ready(job)
        return metadata

    def complete_build(self, metadata):
        config = worker.configuration(worker.request_for(metadata), worker.paths(metadata.name)[1])
        common.save(metadata / 'config.json', config)
        common.save(metadata / 'build-receipt.json', dict(self.receipt, inputHash=worker.input_hash(config)))

    def test_delivery_overlaps_the_next_build_under_the_one_shared_lock(self):
        second = self.queue_second(); events = []; test = self
        common.update(self.metadata / 'state.json', 'queued', nextAttempt=0)
        class Build:
            def __init__(self, command, **kwargs):
                fd = int(kwargs['env']['IOS_REFRESH_LOCK_FD'])
                test.assertEqual(kwargs['pass_fds'], (fd,)); test.assertIn('build-one', command); test.assertIn('job-2', command)
                with test.assertRaises(BlockingIOError):  # renewal, simulator and pairing stay excluded
                    with common.locked(worker.SIGNING_LOCK): pass
                events.append('build started')
            def wait(self, timeout=None):
                events.append('build finished'); test.complete_build(second); return 0
        def deliver(job, allow_ota=False, lock_held=False):
            events.append(('deliver', job, lock_held))
            common.update(worker.paths(job)[0] / 'state.json', 'installed')
        with mock.patch.object(worker.subprocess, 'Popen', Build), mock.patch.object(worker, 'deliver', side_effect=deliver), \
             mock.patch.object(worker, 'prune'):
            worker.work()
        self.assertEqual(events, ['build started', ('deliver', self.job, True), 'build finished', ('deliver', 'job-2', False)])

    def test_two_unbuilt_jobs_build_then_overlap_the_install_with_the_next_build(self):
        second = self.queue_second(); events = []; test = self
        common.save(self.metadata / 'build-receipt.json', dict(self.receipt, complete=False))
        common.update(self.metadata / 'state.json', 'queued', nextAttempt=0)
        def build(command, **kwargs):
            if 'build-one' not in command: return subprocess.CompletedProcess(command, 0)
            events.append(('build', command[-1])); test.complete_build(test.metadata); return subprocess.CompletedProcess(command, 0)
        class Build:
            def __init__(self, command, **kwargs): events.append(('overlapped build', command[-1]))
            def wait(self, timeout=None): test.complete_build(second); return 0
        def deliver(job, allow_ota=False, lock_held=False):
            events.append(('deliver', job, lock_held)); common.update(worker.paths(job)[0] / 'state.json', 'installed')
        with mock.patch.object(worker.subprocess, 'run', side_effect=build), mock.patch.object(worker.subprocess, 'Popen', Build), \
             mock.patch.object(worker, 'deliver', side_effect=deliver), mock.patch.object(worker, 'prune'):
            worker.work()
        self.assertEqual(events, [('build', self.job), ('overlapped build', 'job-2'), ('deliver', self.job, True), ('deliver', 'job-2', False)])

    def test_job_arriving_during_a_build_compiles_while_that_build_installs(self):
        events = []; test = self; arrived = []
        common.save(self.metadata / 'build-receipt.json', dict(self.receipt, complete=False))
        common.update(self.metadata / 'state.json', 'queued', nextAttempt=0)
        def build(command, **kwargs):
            if 'build-one' not in command: return subprocess.CompletedProcess(command, 0)
            events.append(('build', command[-1]))
            arrived.append(test.queue_second())  # its upload finishes while this job compiles
            test.complete_build(test.metadata); return subprocess.CompletedProcess(command, 0)
        class Build:
            def __init__(self, command, **kwargs): events.append(('overlapped build', command[-1]))
            def wait(self, timeout=None): test.complete_build(arrived[0]); return 0
        def deliver(job, allow_ota=False, lock_held=False):
            events.append(('deliver', job, lock_held)); common.update(worker.paths(job)[0] / 'state.json', 'installed')
        with mock.patch.object(worker.subprocess, 'run', side_effect=build), mock.patch.object(worker.subprocess, 'Popen', Build), \
             mock.patch.object(worker, 'deliver', side_effect=deliver), mock.patch.object(worker, 'prune'):
            worker.work()
        self.assertEqual(events, [('build', self.job), ('overlapped build', 'job-2'), ('deliver', self.job, True), ('deliver', 'job-2', False)])

    def test_overlapped_delivery_defers_pairing_recovery_until_the_lock_is_free(self):
        with mock.patch.object(worker, 'deliver', side_effect=worker.RecoverTransport()), self.assertRaises(worker.Retry):
            worker.finish_job(self.job, lock_held=True)
        state = common.load(self.metadata / 'state.json')
        self.assertTrue(state['transportRecovery'])
        self.assertFalse(any('phone-pairing' in str(command) for command, _ in self.calls))
        self.assertFalse(worker.deliverable(self.metadata, state))  # its retry runs on its own, with recovery

    def test_busy_mac_lock_falls_back_without_starting_a_build(self):
        second = self.queue_second(); processed = {}
        common.update(self.metadata / 'state.json', 'queued', nextAttempt=0)
        first = (False, self.metadata, common.load(self.metadata / 'state.json'))
        with common.locked(worker.SIGNING_LOCK), mock.patch.object(worker.subprocess, 'Popen') as popen, \
             mock.patch.object(worker, 'catalog') as catalog:
            worker.run_overlapped(first, (False, second, common.load(second / 'state.json')), processed)
        popen.assert_not_called(); catalog.assert_not_called()
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'waiting_mac')
        self.assertNotIn('job-2', processed)

    def test_failed_overlapped_build_fails_only_its_own_job(self):
        second = self.queue_second(); processed = {}
        common.update(self.metadata / 'state.json', 'queued', nextAttempt=0)
        class Build:
            def __init__(self, command, **kwargs): kwargs['stdout'].write('Guarded build\nerror: compiler failed\n')
            def wait(self, timeout=None): return 1
        with mock.patch.object(worker.subprocess, 'Popen', Build), \
             mock.patch.object(worker, 'deliver', side_effect=lambda job, **_: common.update(self.metadata / 'state.json', 'installed')):
            worker.run_overlapped((False, self.metadata, common.load(self.metadata / 'state.json')),
                                  (False, second, common.load(second / 'state.json')), processed)
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'installed')
        failed = common.load(second / 'state.json')
        self.assertEqual(failed['phase'], 'failed'); self.assertIn('compiler failed', failed['message'])
        self.assertIn('job-2', processed)

    def test_pairing_recovery_runs_outside_the_signing_lock(self):
        self.run.stop()
        def repair(command, **kwargs):
            with common.locked(worker.SIGNING_LOCK): pass
            self.assertIn('phone-pairing', command[0]); return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(worker, 'deliver', side_effect=[worker.RecoverTransport(), None]) as delivery, mock.patch.object(worker.subprocess, 'run', side_effect=repair):
            worker.run_job(self.job)
        self.assertEqual(delivery.call_count, 2)
        self.assertTrue(delivery.call_args.kwargs['allow_ota'])

    def test_a_phone_proved_away_is_not_paired_again_by_every_waiting_job(self):
        self.run.stop()
        pairings = []
        def repair(command, **kwargs):
            pairings.append(command); return subprocess.CompletedProcess(command, 0)
        def still_away(job_id, allow_ota=False, lock_held=False):
            if not allow_ota: raise worker.RecoverTransport()
            common.update(self.metadata / 'state.json', 'awaiting_ota', otaPublished=True, nextAttempt=time.time() + 300)
        with mock.patch.object(worker, 'deliver', side_effect=still_away), mock.patch.object(worker.subprocess, 'run', side_effect=repair):
            worker.run_job(self.job)
            self.assertEqual(len(pairings), 1)
            away = worker.phone_away_until('PHONE')
            self.assertGreater(away, time.time())
            # The next waiting job (this one again, five minutes later) waits out the window.
            worker.run_job(self.job)
        self.assertEqual(len(pairings), 1, 'no second pairing recovery inside the window')
        self.assertEqual(common.load(self.metadata / 'state.json')['nextAttempt'], away)
        # Back home: an installation clears the record.
        worker.note_phone_away('PHONE', back=True)
        self.assertEqual(worker.phone_away_until('PHONE'), 0)

    def test_a_phone_the_hub_places_away_from_the_mac_is_never_paired(self):
        self.run.stop()
        pairings, deliveries = [], []
        def repair(command, **kwargs):
            pairings.append(command); return subprocess.CompletedProcess(command, 0)
        def away(job_id, allow_ota=False, lock_held=False):
            deliveries.append(allow_ota)
            if not allow_ota: raise worker.RecoverTransport()
            common.update(self.metadata / 'state.json', 'awaiting_ota', otaPublished=True, nextAttempt=time.time() + 300)
        with mock.patch.object(worker, 'deliver', side_effect=away), mock.patch.object(worker.subprocess, 'run', side_effect=repair), \
             mock.patch.object(worker, 'phone_route', return_value='page'):
            worker.run_job(self.job)
            self.assertEqual(deliveries, [False, True])  # published on the page at once
            worker.run_job(self.job)                     # five minutes later: still away, nothing to do
        self.assertEqual(pairings, [])
        self.assertEqual(deliveries, [False, True])      # not even a phone check under the Mac lock
        state = common.load(self.metadata / 'state.json')
        self.assertEqual(state['phase'], 'awaiting_ota'); self.assertGreater(state['nextAttempt'], time.time() + 200)
        # Next to the Mac again (or unknown): pairing recovery as before.
        with mock.patch.object(worker, 'deliver', side_effect=[worker.RecoverTransport(), None]), \
             mock.patch.object(worker.subprocess, 'run', side_effect=repair), mock.patch.object(worker, 'phone_route', return_value='try'), \
             mock.patch.object(worker, 'phone_away_until', return_value=0):
            worker.run_job(self.job)
        self.assertEqual(len(pairings), 1)

    def test_phone_route_needs_the_hub(self):
        self.assertIsNone(worker.phone_route())  # no sentinel config under this test's home

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

    def test_queue_guard_deferral_uses_only_the_current_attempt_not_old_build_history(self):
        receipt = dict(self.receipt, complete=False); common.save(self.metadata / 'build-receipt.json', receipt)
        (self.metadata / 'build.log').write_text('Guarded build; old attempt\nold completed compiler output\n')
        def refuse(command, **kwargs):
            kwargs['stdout'].write('MAC WORKLOAD STOPPED: load 7.49 > 6; less than 12 GiB free\n')
            return subprocess.CompletedProcess(command, 1)
        with mock.patch.object(worker.subprocess, 'run', side_effect=refuse), mock.patch.object(worker, 'catalog') as catalog:
            with self.assertRaisesRegex(worker.Retry, 'load 7.49'): worker.run_job(self.job)
        catalog.assert_not_called()

    def test_stable_compiler_workspace_keeps_the_frozen_checkpoint_authoritative(self):
        common.save(self.tools / 'push/projects.json', {'demo': {'persistentBuildCache': True}})
        lock = (self.base / 'signing.lock').open('a'); self.addCleanup(lock.close)
        def compile(command, **kwargs):
            if 'cwd' not in kwargs: return subprocess.CompletedProcess(command, 1)
            working = Path(kwargs['cwd'])
            self.assertNotEqual(working, self.source)
            self.assertEqual((working / 'Sources/view.swift').read_text(), 'reviewed source')
            app = working / self.config['app']; app.mkdir(parents=True, exist_ok=True)
            (app / 'Demo').write_bytes(b'compiled from stable verified inputs')
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.dict(os.environ, {'IOS_WORKLOAD_ACTIVE': '123', 'IOS_REFRESH_LOCK_FD': str(lock.fileno())}), mock.patch.object(worker.subprocess, 'run', side_effect=compile):
            worker.build_one(self.job)
        self.assertEqual((self.source / 'Sources/view.swift').read_text(), 'reviewed source')
        self.assertEqual((self.app / 'Demo').read_bytes(), b'compiled from stable verified inputs')
        self.assertTrue(common.load(self.metadata / 'build-receipt.json')['complete'])

    def test_per_provider_workspace_does_not_share_another_apps_mutable_build_tree(self):
        common.save(self.tools / 'push/projects.json', {'demo': {'persistentBuildCache': {
            'apps': ['demo'], 'cacheRoots': ['build/DerivedData'], 'maximumBytes': 2 << 30}}})
        lock = (self.base / 'signing.lock').open('a'); self.addCleanup(lock.close)
        def compile(command, **kwargs):
            if 'cwd' not in kwargs: return subprocess.CompletedProcess(command, 1)
            working = Path(kwargs['cwd'])
            self.assertEqual(working, self.base / 'Library/Caches/ios-tools/BuildWorkspaces/demo/demo/source')
            app = working / self.config['app']; app.mkdir(parents=True, exist_ok=True)
            (app / 'Demo').write_bytes(b'provider-isolated artifact')
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.dict(os.environ, {'IOS_WORKLOAD_ACTIVE': '123', 'IOS_REFRESH_LOCK_FD': str(lock.fileno())}), mock.patch.object(worker.subprocess, 'run', side_effect=compile):
            worker.build_one(self.job)
        report = common.load(self.metadata / 'cache-report.json')
        self.assertEqual(report['strategy'], 'stable-workspace+cas')
        self.assertTrue(report['success'])
        self.assertEqual((self.app / 'Demo').read_bytes(), b'provider-isolated artifact')

    def test_compiler_cannot_change_workspace_inputs_and_publish_an_artifact(self):
        common.save(self.tools / 'push/projects.json', {'demo': {'persistentBuildCache': True}})
        lock = (self.base / 'signing.lock').open('a'); self.addCleanup(lock.close)
        def mutate(command, **kwargs):
            if 'cwd' not in kwargs: return subprocess.CompletedProcess(command, 1)
            (Path(kwargs['cwd']) / 'Sources/view.swift').write_text('changed during compilation')
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.dict(os.environ, {'IOS_WORKLOAD_ACTIVE': '123', 'IOS_REFRESH_LOCK_FD': str(lock.fileno())}), mock.patch.object(worker.subprocess, 'run', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'Frozen source changed'):
                worker.build_one(self.job)
        self.assertEqual((self.source / 'Sources/view.swift').read_text(), 'reviewed source')
        self.assertFalse(common.load(self.metadata / 'build-receipt.json')['complete'])

    def test_actual_compiler_failure_is_not_retried_as_guard_contention(self):
        common.save(self.metadata / 'build-receipt.json', dict(self.receipt, complete=False))
        def fail(command, **kwargs):
            kwargs['stdout'].write('Guarded build; deadline 900s\nerror: compiler failed\nMAC WORKLOAD STOPPED: command failed\n')
            return subprocess.CompletedProcess(command, 1)
        with mock.patch.object(worker.subprocess, 'run', side_effect=fail), mock.patch.object(worker, 'catalog') as catalog:
            with self.assertRaisesRegex(RuntimeError, 'Build failed: error: compiler failed'): worker.run_job(self.job)
        catalog.assert_not_called()

    def test_log_excerpt_keeps_compiler_error_before_a_long_xcode_traceback(self):
        error = '/^src/MangaReader/SiteTransfers.swift:43:9: error: passing closure risks data races'
        output = 'ld: warning: ignoring duplicate libraries\n' + error + '\n' + 'unrelated compiler output\n' * 100 + 'BUILD FAILED\n'
        excerpt = worker.log_excerpt(output)
        self.assertIn(error, excerpt)
        self.assertEqual(worker.build_errors(output)[0], error)
        self.assertEqual(excerpt.count(error), 1)
        self.assertLess(len(excerpt.splitlines()), 27)

    def test_log_excerpt_keeps_a_swift_crash_when_no_source_error_was_emitted(self):
        crash = 'bad_optional_access was thrown in -fno-exceptions modePlease submit a bug report'
        output = crash + '\n' + 'compiler backtrace\n' * 100 + 'Command SwiftCompile failed with a nonzero exit code\nBUILD FAILED\n'
        self.assertEqual(worker.build_errors(output)[0], crash)
        self.assertIn(crash, worker.log_excerpt(output))

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


class WorkerTestGateTests(WorkerTests):
    def require_tests(self):
        self.request.update(testsRequired=True, testsKey='k1', testsCommand=['true'])
        common.save(self.metadata / 'request.json', self.request)
        frozen = common.load(self.metadata / 'ready.json'); frozen['requestHash'] = common.digest(self.metadata / 'request.json')
        common.save(self.metadata / 'ready.json', frozen)

    def test_built_job_waits_for_the_pc_tests_then_installs(self):
        self.require_tests(); state = common.load(self.metadata / 'state.json')
        self.assertFalse(worker.deliverable(self.metadata, state))
        with mock.patch.object(worker, 'deliver') as deliver:
            worker.attempt(self.metadata, state, {}, lambda: worker.finish_job(self.job))
            deliver.assert_not_called()
        state = common.load(self.metadata / 'state.json')
        self.assertEqual(state['phase'], 'waiting_tests'); self.assertGreater(state['nextAttempt'], time.time())
        with self.assertRaisesRegex(RuntimeError, 'different source'): worker.record_tests(self.job, 'passed', 'other')
        processed = {self.job: time.time() - 1}     # this worker run already handled the job
        self.assertEqual(worker.scan(processed)[0], [])
        worker.record_tests(self.job, 'passed', 'k1')
        state = common.load(self.metadata / 'state.json')
        self.assertEqual([item[1] for item in worker.scan(processed)[0]], [self.metadata])   # due at once
        self.assertTrue(worker.deliverable(self.metadata, state))
        with mock.patch.object(worker, 'deliver') as deliver:
            worker.finish_job(self.job); deliver.assert_called_once()

    def test_failed_pc_tests_fail_the_job_and_nothing_installs(self):
        self.require_tests(); worker.record_tests(self.job, 'failed', 'k1')
        self.assertEqual(common.load(self.metadata / 'state.json')['phase'], 'failed')
        self.assertFalse(worker.runnable(self.job))
        with mock.patch.object(worker, 'deliver') as deliver:
            worker.finish_job(self.job); deliver.assert_not_called()

    def test_phone_answer_from_the_build_counts_once_and_only_while_fresh(self):
        fresh = {'at': time.time(), 'device': self.config['device'], 'reachable': True}
        with mock.patch.object(worker, 'catalog', return_value=None) as catalog:
            common.save(self.metadata / 'phone-prefetch.json', fresh)
            self.assertEqual(worker.phone_reachable(self.config, self.metadata, {}), [])
            catalog.assert_not_called()
            self.assertIsNone(worker.phone_reachable(self.config, self.metadata, {}))     # consumed: asks again
            common.save(self.metadata / 'phone-prefetch.json', fresh)
            self.assertIsNone(worker.phone_reachable(self.config, self.metadata, {'deliveryAttempts': 1}))   # retries ask
            common.save(self.metadata / 'phone-prefetch.json', dict(fresh, at=time.time() - worker.PREFETCH_FRESH - 1))
            self.assertIsNone(worker.phone_reachable(self.config, self.metadata, {}))     # stale
            common.save(self.metadata / 'phone-prefetch.json', dict(fresh, reachable=False))
            self.assertIsNone(worker.phone_reachable(self.config, self.metadata, {}))
            self.assertEqual(catalog.call_count, 4)


class ClientStatusTests(unittest.TestCase):
    def test_transfer_replaces_a_stale_busy_message(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(client, 'STORE', Path(temporary)):
            job = Path(temporary) / 'jobs' / 'job-1'
            common.save(job / 'request.json', {'id': 'job-1'})
            common.save(job / 'state.json', {'phase': 'queued', 'message': 'old busy reason'})
            def transfer(_, checksum=False):
                state = common.load(job / 'state.json')
                self.assertEqual(state['phase'], 'uploading')
                self.assertEqual(state['message'], 'Transferring the frozen source checkpoint')
            with mock.patch.object(client, 'transfer', side_effect=transfer), mock.patch.object(client, 'remote', return_value=subprocess.CompletedProcess([], 0, '{}')):
                client.pump()
            self.assertEqual(common.load(job / 'state.json')['message'], 'Source transferred; waiting for guarded build')

    def test_status_timeout_with_partial_stderr_backs_off_and_continues(self):
        # subprocess.TimeoutExpired keeps captured stderr as bytes even with text=True.
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(client, 'STORE', Path(temporary)):
            jobs = []
            for name in ('job-1', 'job-2'):
                job = Path(temporary) / 'jobs' / name
                common.save(job / 'request.json', {'id': name}); common.save(job / 'state.json', {'phase': 'submitted'})
                common.save(job / 'uploaded.json', {'at': 1}); jobs.append(job)
            timeout = subprocess.TimeoutExpired(['ssh', 'mac'], 45, output=b'', stderr=b'Connection to mac timed out\n')
            remote = mock.Mock(side_effect=[timeout, subprocess.CompletedProcess([], 0, '{"phase": "building"}')])
            with mock.patch.object(client, 'remote', remote):
                client.pump()
            state = common.load(jobs[0] / 'state.json')
            self.assertEqual((state['transportAttempts'], state['transportError']), (1, 'Connection to mac timed out'))
            self.assertGreater(state['transportNextAttempt'], time.time())
            self.assertEqual(common.load(jobs[1] / 'state.json')['phase'], 'building')


class PushTestGateTests(unittest.TestCase):
    """PC tests run on a frozen copy of their inputs while the Mac builds; the uploader reports them."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.repo = self.base / 'repo'; (self.repo / 'apps/ios/scripts').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.counter = self.base / 'runs'
        (self.repo / 'apps/ios/scripts/test.sh').write_text(
            'echo run >> "%s"\n[ -e apps/ios/broken ] && { echo FAIL: broken; exit 1; }\necho PASS\n' % self.counter)
        (self.repo / 'apps/ios/App.swift').write_text('v1')
        self.project = {'root': str(self.repo), 'tests': ['bash', 'apps/ios/scripts/test.sh']}
        for patch in (mock.patch.object(client, 'STORE', self.base / 'store'), mock.patch.object(client, 'ON_MAC', False)):
            patch.start(); self.addCleanup(patch.stop)

    def runs(self): return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0

    def job(self, name):
        directory = client.STORE / 'jobs' / name
        key = client.tests_key(self.repo, self.project, copy_to=directory / 'tests-source')
        common.save(directory / 'request.json', {'id': name, 'repo': 'demo', 'testsRequired': True, 'testsKey': key,
                                                 'testsCommand': self.project['tests']})
        common.save(directory / 'state.json', {'phase': 'queued'})
        return directory, key

    def test_tests_run_on_the_frozen_copy_once_per_source_and_failures_are_never_cached(self):
        self.assertEqual(client.tests_key(self.repo, self.project), client.tests_key(self.repo, self.project, copy_to=self.base / 'copy'))
        first, key = self.job('job-1')
        (self.repo / 'apps/ios/broken').write_text('x')       # an edit after queueing does not reach its tests
        real = subprocess.run
        with mock.patch.object(client.subprocess, 'run', side_effect=lambda c, **k: subprocess.CompletedProcess(c, 0) if c[0] == 'systemctl' else real(c, **k)):
            client.test_job('job-1')
            self.assertEqual(common.load(first / 'tests.json')['result'], 'passed')
            (self.repo / 'apps/ios/broken').unlink()
            second, same = self.job('job-2')
            client.test_job('job-2')                          # identical inputs: the first pass counts
            self.assertEqual((same, self.runs()), (key, 1))
            (self.repo / 'apps/ios/broken').write_text('x')
            third, _ = self.job('job-3')                       # this one froze the broken tree
            client.test_job('job-3'); client.test_job('job-3')
            self.assertEqual(common.load(third / 'tests.json')['result'], 'failed')
            self.assertEqual(self.runs(), 2)                   # a result is final for its job
            fourth, _ = self.job('job-4'); client.test_job('job-4')
            self.assertEqual((common.load(fourth / 'tests.json')['result'], self.runs()), ('failed', 3))   # failures are not cached
            self.assertIn('FAIL: broken', Path(common.load(fourth / 'tests.json')['log']).read_text())

    def test_uploader_reports_results_starts_missing_runs_and_never_uploads_a_failed_job(self):
        failed, _ = self.job('job-1'); common.save(failed / 'tests.json', {'result': 'failed', 'key': 'x', 'log': '/log'})
        passed, key = self.job('job-2'); common.save(passed / 'tests.json', {'result': 'passed', 'key': key, 'reported': False})
        common.save(passed / 'uploaded.json', {'at': 1})
        running, _ = self.job('job-3'); common.save(running / 'uploaded.json', {'at': 1})
        remote = mock.Mock(return_value=subprocess.CompletedProcess([], 0, '{}'))
        with mock.patch.object(client, 'transfer') as transfer, mock.patch.object(client, 'remote', remote), \
             mock.patch.object(client, 'start_tests') as start:
            client.pump()
        transfer.assert_not_called()
        self.assertEqual(common.load(failed / 'state.json')['phase'], 'failed')
        self.assertIn(mock.call(['tests', '--id', 'job-2', '--result', 'passed', '--key', key], timeout=45), remote.call_args_list)
        self.assertTrue(common.load(passed / 'tests.json')['reported'])
        start.assert_called_once_with('job-3')


class WatchClientTests(unittest.TestCase):
    def test_root_scripts_declaration_works_from_checkout_and_explicit_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'scripts').mkdir()
            listing = {'repo': 'custom-twitter', 'apps': [{'name': 'twitter'}]}
            (root / 'scripts/renewal.py').write_text('print(' + repr(json.dumps(listing)) + ')')
            with mock.patch.object(client, 'projects', return_value={'custom-twitter': {'root': str(root), 'declaration': 'scripts/renewal.py'}}):
                for source in [str(root), None]:
                    with mock.patch.object(client.Path, 'cwd', return_value=root):
                        repo, project, app = client.choose('twitter', source=source)
                    self.assertEqual((repo, project['root'], app['name']), ('custom-twitter', str(root), 'twitter'))

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

    def test_an_away_delivery_says_it_is_not_installed_and_names_the_install_page(self):
        # 2026-11-22: the Mac was at the office and the phone at home; status said only "Signed update published".
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common.save(root / 'jobs/demo/state.json', {'id': 'demo', 'repo': 'trader', 'app': 'trader', 'phase': 'awaiting_ota',
                                                        'message': 'Signed update published; the phone is away from the Mac'})
            common.save(root / 'jobs/done/state.json', {'id': 'done', 'phase': 'installed', 'message': 'Installed'})
            with mock.patch.object(client, 'STORE', root), mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                client.show('demo')
                client.show('done')
            text = out.getvalue()
            self.assertIn('NOT INSTALLED', text); self.assertIn(common.OTA_PAGE, text)
            self.assertEqual(text.count(common.OTA_PAGE), 1)   # an installed job carries no install page
            with mock.patch.object(client, 'STORE', root), mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                client.show('demo', as_json=True)
            value = json.loads(out.getvalue())
            self.assertEqual((value['installed'], value['installUrl']), (False, common.OTA_PAGE))
            with mock.patch.object(client, 'STORE', root), mock.patch.object(client.time, 'sleep'), mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                with self.assertRaises(SystemExit) as result: client.show('demo', follow=True)
            self.assertEqual(result.exception.code, 10); self.assertIn(common.OTA_PAGE, out.getvalue())


if __name__ == '__main__': unittest.main()
