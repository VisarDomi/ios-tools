"""Behavior checks using fake Xcode/device boundaries; no Mac or phone required."""
import importlib.util
import json
import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('refresh', Path(__file__).with_name('refresh.py'))
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'source').write_text('approved runtime')
        (self.root / 'cache').mkdir()
        self.config = dict(root=str(self.root), app='app', team='TEAM', bundleIds=['host', 'host.extension'],
                           device='phone', profileCache=str(self.root / 'cache'), inputs=['source'], build=['fake-build'])
        self.before = {key: dict(id=key, uuid='old', expires=1000) for key in ['TEAM.host', 'TEAM.host.extension']}
        self.after = {key: dict(id=key, uuid='new', expires=1000000) for key in self.before}
        self.state_path = self.root / 'build/refresh/state.json'
        refresh.save(self.state_path, dict(inputHash=refresh.fingerprint(self.root, ['source']),
                                          installedProfiles=self.before, lastSuccess=0))
        self.device_calls = []
        self.process_calls = []
        self.locked = False
        self.offline = False
        self.install_failure = False
        self.build_failure = False
        self.source_change = False
        self.start_patch(patch.object(refresh.time, 'time', return_value=100000))
        self.start_patch(patch.object(refresh.Path, 'home', return_value=self.root))
        self.start_patch(patch.object(refresh, 'device_json', side_effect=self.device))
        self.start_patch(patch.object(refresh.subprocess, 'run', side_effect=self.process))
        self.start_patch(patch.object(refresh, 'app_profiles', side_effect=lambda *_: self.after))
        self.start_patch(patch.object(refresh, 'profile', return_value=self.before['TEAM.host']))
        self.start_patch(patch.object(refresh, 'companion_apps', return_value=None))

    def start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def device(self, config, arguments):
        self.device_calls.append(arguments)
        if self.offline:
            raise RuntimeError('Phone unavailable')
        if arguments == ['info', 'details']:
            return {'connectionProperties': {'transportType': 'localNetwork'}}
        if arguments == ['info', 'lockState']:
            return dict(passcodeRequired=self.locked, unlockedSinceBoot=True)
        if self.install_failure:
            raise RuntimeError('Phone disconnected during install')
        return {}

    def process(self, command, **kwargs):
        self.process_calls.append(command)
        if command == ['fake-build']:
            if self.source_change:
                (self.root / 'source').write_text('changed during build')
            return subprocess.CompletedProcess(command, int(self.build_failure))
        return subprocess.CompletedProcess(command, 1 if command[0] == '/usr/bin/pgrep' else 0)

    def state(self):
        return json.loads(self.state_path.read_text())

    def test_success_installs_then_daily_check_does_no_device_work(self):
        refresh.run(self.config, 'refresh', wireless=True)
        self.assertEqual(self.state()['lastSuccess'], 100000)
        self.assertEqual(self.state()['installedProfiles'], self.after)
        self.assertEqual(self.device_calls[-1][0:2], ['install', 'app'])
        self.device_calls.clear()
        self.process_calls.clear()
        refresh.run(self.config, 'refresh')
        self.assertEqual(self.device_calls, [])
        self.assertEqual(self.process_calls, [])

    def test_mac_renewal_wraps_the_builder_in_the_shared_workload_guard(self):
        with patch.object(refresh.sys, 'platform', 'darwin'):
            refresh.run(self.config, 'refresh')
        command=next(c for c in self.process_calls if 'build' in c and '--timeout' in c)
        self.assertTrue(command[1].endswith('native/scripts/mac-workload'))
        self.assertEqual(command[-1], 'fake-build')

    def test_approved_queue_checkpoint_renewal_uses_shared_cached_builder(self):
        source=self.root/'Developer/ios-push/checkpoints/job/source'
        source.mkdir(parents=True);(source/'source').write_text('approved runtime')
        self.config.update(root=str(source),stateDir=str(self.state_path.parent))
        registration=self.root/'registration.json';refresh.save(registration,self.config)
        refresh.save(self.state_path,dict(inputHash=refresh.fingerprint(source,['source']),
                                        installedProfiles=self.before,lastSuccess=0))
        with patch.object(refresh.sys,'platform','darwin'):
            refresh.run(self.config,'refresh',config_path=registration)
        command=next(c for c in self.process_calls if 'build' in c and '--timeout' in c)
        self.assertIn('renewal-build',command)
        self.assertTrue(command[command.index('renewal-build')-1].endswith('push/worker.py'))
        self.assertEqual(command[-2:],['--config',str(registration)])
        self.assertEqual(self.state()['lastSuccess'],100000)

    def test_recursive_profiles_include_watch_and_its_complication(self):
        root = self.root / 'ProfileHost.app'
        entries = [(root, 'host'), (root / 'Watch/Watch.app', 'watch'),
                   (root / 'Watch/Watch.app/PlugIns/Inbox.appex', 'widget')]
        for entry, bundle in entries:
            entry.mkdir(parents=True, exist_ok=True)
            (entry / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': bundle}))
            (entry / 'embedded.mobileprovision').write_text(bundle)
        # setUp replaces app_profiles at the device boundary; reload its real
        # implementation for this fixture-only profile inventory check.
        real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)
        with patch.object(real, 'profile', side_effect=lambda p: {'id': 'TEAM.' + p.read_text()}):
            result = real.app_profiles(root, ['TEAM.host', 'TEAM.watch', 'TEAM.widget'])
            self.assertEqual(set(result), {'TEAM.host', 'TEAM.watch', 'TEAM.widget'})
            with self.assertRaisesRegex(RuntimeError, 'identities'):
                real.app_profiles(root, ['TEAM.host', 'TEAM.watch'])

    def test_unavailable_paired_watch_does_not_start_a_renewal_build(self):
        self.config.update(watch={'app': 'Watch/Demo.app', 'device': 'watch', 'bundleId': 'host.extension'})
        def devices(config, arguments):
            if config['device'] == 'watch': raise RuntimeError('Watch unavailable')
            return self.device(config, arguments)
        with patch.object(refresh, 'device_json', side_effect=devices), self.assertRaisesRegex(RuntimeError, 'Watch unavailable'):
            refresh.run(self.config, 'refresh')
        self.assertNotIn(['fake-build'], self.process_calls)
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_watch_install_requires_both_actual_versions_before_renewal_success(self):
        self.config.update(watch={'app': 'Watch/Demo.app', 'device': 'watch', 'bundleId': 'host.extension'})
        for entry in [self.root / 'app', self.root / 'app/Watch/Demo.app']:
            entry.mkdir(parents=True, exist_ok=True)
            (entry / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': '2'}))
        calls = []
        def devices(config, arguments):
            calls.append((config['device'], arguments))
            if arguments == ['info', 'apps']:
                return {'apps': [{'bundleIdentifier': 'host' if config['device'] == 'phone' else 'host.extension',
                                  'bundleVersion': '2' if config['device'] == 'phone' else 'old'}]}
            return self.device(config, arguments)
        with patch.object(refresh, 'device_json', side_effect=devices), self.assertRaisesRegex(RuntimeError, 'every target'):
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 0)
        self.assertEqual([device for device, args in calls if args[0] == 'install'], ['phone', 'watch'])

    def test_phone_proxy_renews_when_only_direct_watch_developer_discovery_is_broken(self):
        self.config.update(watch={'app': 'Watch/Demo.app', 'device': 'watch', 'bundleId': 'host.extension'})
        for entry in [self.root / 'app', self.root / 'app/Watch/Demo.app']:
            entry.mkdir(parents=True, exist_ok=True)
            (entry / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': '2'}))
        def devices(config, arguments):
            if config['device'] == 'watch': raise RuntimeError('Native discovery unavailable')
            if arguments == ['info', 'apps']:
                return {'apps': [{'bundleIdentifier': 'host', 'bundleVersion': '2'}]}
            return self.device(config, arguments)
        actual = [{'bundleIdentifier': 'host.extension', 'bundleVersion': '2'}]
        with patch.object(refresh, 'device_json', side_effect=devices), \
                patch.object(refresh, 'companion_apps', return_value=actual) as proxy:
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 100000)
        self.assertEqual([call.kwargs.get('install', False) for call in proxy.call_args_list], [False, True])

    def test_companion_wrong_version_never_advances_renewal_deadline(self):
        self.config.update(watch={'app': 'Watch/Demo.app', 'device': 'watch', 'bundleId': 'host.extension'})
        for entry in [self.root / 'app', self.root / 'app/Watch/Demo.app']:
            entry.mkdir(parents=True, exist_ok=True)
            (entry / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': '2'}))
        def devices(config, arguments):
            if config['device'] == 'watch': raise RuntimeError('Native discovery unavailable')
            if arguments == ['info', 'apps']:
                return {'apps': [{'bundleIdentifier': 'host', 'bundleVersion': '2'}]}
            return self.device(config, arguments)
        with patch.object(refresh, 'device_json', side_effect=devices), \
                patch.object(refresh, 'companion_apps', return_value=[{'bundleIdentifier': 'host.extension', 'bundleVersion': 'old'}]), \
                self.assertRaisesRegex(RuntimeError, 'every target'):
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_next_day_is_due_even_with_six_days_remaining(self):
        refresh.run(self.config, 'refresh')
        self.after = {key: dict(value, expires=1100000) for key, value in self.after.items()}
        with patch.object(refresh.time, 'time', return_value=186400):
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 186400)
        self.assertEqual(sum(call == ['fake-build'] for call in self.process_calls), 2)

    def test_locked_does_not_build_or_claim_success(self):
        self.locked = True
        refresh.run(self.config, 'refresh')
        self.assertNotIn(['fake-build'], self.process_calls)
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_offline_does_not_build_or_claim_success(self):
        self.offline = True
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            refresh.run(self.config, 'refresh')
        self.assertNotIn(['fake-build'], self.process_calls)
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_failed_install_restores_cache_and_is_still_due(self):
        cached = self.root / 'cache/old.mobileprovision'
        cached.write_bytes(b'original cached profile')
        self.install_failure = True
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            refresh.run(self.config, 'refresh')
        self.assertEqual(cached.read_bytes(), b'original cached profile')
        self.assertEqual(self.state()['lastSuccess'], 0)
        self.install_failure = False
        refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 100000)

    def test_build_failure_restores_cache_without_installing(self):
        cached = self.root / 'cache/old.mobileprovision'
        cached.write_bytes(b'profile')
        self.build_failure = True
        with self.assertRaisesRegex(RuntimeError, 'build failed'):
            refresh.run(self.config, 'refresh')
        self.assertTrue(cached.exists())
        self.assertFalse(any(call[0] == 'install' for call in self.device_calls))
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_one_stale_extension_prevents_install_and_success(self):
        self.after['TEAM.host.extension'] = self.before['TEAM.host.extension']
        with self.assertRaisesRegex(RuntimeError, 'ALL'):
            refresh.run(self.config, 'refresh')
        self.assertFalse(any(call[0] == 'install' for call in self.device_calls))
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_changed_source_prevents_device_and_build_work(self):
        (self.root / 'source').write_text('unapproved')
        with self.assertRaisesRegex(RuntimeError, 'not approved'):
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.device_calls, [])
        self.assertEqual(self.process_calls, [])

    def test_pending_push_prevents_renewing_previous_code(self):
        state = self.state(); state['pendingPush'] = {'id': 'queued-update'}; refresh.save(self.state_path, state)
        refresh.run(self.config, 'refresh', force=True)
        self.assertEqual(self.device_calls, []); self.assertEqual(self.process_calls, [])

    def test_changed_registration_is_reloaded_instead_of_building_old_checkpoint(self):
        path = self.root / 'registration.json'
        refresh.save(path, {**self.config, 'root': str(self.root / 'new-checkpoint')})
        refresh.run(self.config, 'refresh', force=True, config_path=path)
        self.assertEqual(self.device_calls, []); self.assertEqual(self.process_calls, [])

    def test_changed_source_during_build_prevents_install(self):
        self.source_change = True
        with self.assertRaisesRegex(RuntimeError, 'changed during'):
            refresh.run(self.config, 'refresh')
        self.assertFalse(any(call[0] == 'install' for call in self.device_calls))

    def test_interrupted_cache_move_is_recovered(self):
        stash = self.root / 'stash'
        stash.mkdir()
        (stash / 'saved.mobileprovision').write_bytes(b'old profile')
        refresh.restore_cache(stash, self.root / 'cache')
        self.assertEqual((self.root / 'cache/saved.mobileprovision').read_bytes(), b'old profile')
        self.assertEqual(list(stash.iterdir()), [])

    def test_cache_collision_never_overwrites_other_contents(self):
        stash = self.root / 'stash'
        stash.mkdir()
        (stash / 'saved.mobileprovision').write_bytes(b'old')
        (self.root / 'cache/saved.mobileprovision').write_bytes(b'new')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            refresh.restore_cache(stash, self.root / 'cache')
        self.assertEqual((self.root / 'cache/saved.mobileprovision').read_bytes(), b'new')
        self.assertEqual((stash / 'saved.mobileprovision').read_bytes(), b'old')

    def test_unrelated_profile_untouched(self):
        cached = self.root / 'cache/unrelated.mobileprovision'
        cached.write_bytes(b'unrelated')
        with patch.object(refresh, 'profile', return_value=dict(id='OTHER.app')):
            refresh.run(self.config, 'refresh')
        self.assertEqual(cached.read_bytes(), b'unrelated')

    def test_paid_monthly_advances_profile_and_skips_until_next_month(self):
        self.config['interval'] = 'monthly'
        self.before = {key: dict(value, expires=10000000) for key, value in self.before.items()}
        self.after = {key: dict(value, expires=20000000) for key, value in self.before.items()}
        refresh.save(self.state_path, dict(inputHash=refresh.fingerprint(self.root, ['source']),
                                          installedProfiles=self.before, lastSuccess=0))
        cached = self.root / 'cache/paid.mobileprovision'
        cached.write_bytes(b'keep the valid wildcard profile')
        refresh.run(self.config, 'refresh')
        self.assertFalse(cached.exists())
        self.assertEqual(self.state()['lastSuccess'], 100000)
        self.device_calls.clear()
        with patch.object(refresh.time, 'time', return_value=186400):
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.device_calls, [])

    def test_monthly_reuses_shared_profile_already_renewed_in_this_batch(self):
        self.config['interval'] = 'monthly'
        self.after = {key: dict(value, expires=10000000) for key, value in self.after.items()}
        cached = self.root / 'cache/shared.mobileprovision'
        cached.write_bytes(b'new shared wildcard')
        with patch.object(refresh, 'profile', return_value=dict(id='TEAM.*', expires=10000000, created=100000)):
            refresh.run(self.config, 'refresh')
        self.assertEqual(cached.read_bytes(), b'new shared wildcard')
        self.assertEqual(self.state()['lastSuccess'], 100000)

    def test_monthly_unchanged_deadlines_are_not_a_renewal(self):
        self.config['interval'] = 'monthly'
        self.after = self.before
        with self.assertRaisesRegex(RuntimeError, 'later deadlines'):
            refresh.run(self.config, 'refresh')
        self.assertFalse(any(call[0] == 'install' for call in self.device_calls))

    def test_approve_keeps_schedule_only_when_asked_and_profiles_do_not_regress(self):
        self.config['interval'] = 'monthly'
        refresh.save(self.state_path, dict(inputHash='old', installedProfiles=self.before, lastSuccess=90000))
        refresh.run(self.config, 'approve', keep_schedule=True)
        self.assertEqual(self.state()['lastSuccess'], 90000)
        self.assertEqual(self.state()['installedProfiles'], self.after)
        refresh.run(self.config, 'approve')
        self.assertEqual(self.state()['lastSuccess'], 0)
        refresh.save(self.state_path, dict(inputHash='old', installedProfiles=self.after, lastSuccess=90000))
        self.after = self.before
        refresh.run(self.config, 'approve', keep_schedule=True)
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_guard_preflight_refusal_defers_without_claiming_a_build_or_renewal(self):
        cached = self.root / 'cache/old.mobileprovision'
        cached.write_bytes(b'approved profile')
        before = self.state()
        def refused(command, **kwargs):
            if command[-1] == 'fake-build':
                kwargs['stdout'].write('MAC WORKLOAD STOPPED: load 7.49 > 6; let the Mac settle; less than 12 GiB free\n')
                return subprocess.CompletedProcess(command, 1)
            return self.process(command, **kwargs)
        with patch.object(refresh.sys, 'platform', 'darwin'), patch.object(refresh.subprocess, 'run', side_effect=refused):
            refresh.run(self.config, 'refresh')
        after = self.state()
        self.assertEqual(after['lastSuccess'], before['lastSuccess'])
        self.assertEqual(after['installedProfiles'], before['installedProfiles'])
        self.assertEqual(after.get('nextDue'), before.get('nextDue'))
        self.assertIsNone(after['lastError'])
        self.assertIn('less than 12 GiB', after['lastDeferred'])
        self.assertEqual(cached.read_bytes(), b'approved profile')
        self.assertFalse(any(c[:2] == ['install', 'app'] for c in self.device_calls))

    def test_guard_stop_after_compilation_started_is_still_a_failed_build(self):
        def stopped(command, **kwargs):
            if command[-1] == 'fake-build':
                kwargs['stdout'].write('Guarded build; deadline 900s; telemetry x\nSwiftCompile file.swift\nMAC WORKLOAD STOPPED: free disk fell below 8 GiB\n')
                return subprocess.CompletedProcess(command, 1)
            return self.process(command, **kwargs)
        with patch.object(refresh.sys, 'platform', 'darwin'), patch.object(refresh.subprocess, 'run', side_effect=stopped):
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_completed_cache_cleanup_preserves_inputs_products_and_frozen_checkpoints(self):
        derived = self.root / 'build/DerivedData'
        derived.mkdir(parents=True)
        (derived / 'compiler-cache').write_bytes(b'disposable')
        app = self.root / self.config['app']; app.mkdir(); (app / 'product').write_text('signed app')
        preserved = self.root / 'build/protected/DerivedData'
        preserved.mkdir(parents=True); (preserved / 'input').write_text('approved source')
        self.config['inputs'].append('build/protected')
        before = refresh.fingerprint(self.root, self.config['inputs'])
        removed = refresh.prune_completed_caches(self.config)
        self.assertEqual(removed, [str(derived)])
        self.assertFalse(derived.exists())
        self.assertTrue((preserved / 'input').exists())
        self.assertTrue((app / 'product').exists())
        self.assertEqual(refresh.fingerprint(self.root, self.config['inputs']), before)
        frozen = self.root / 'Developer/ios-push/checkpoints/job/source'
        cache = frozen / 'build/DerivedData'; cache.mkdir(parents=True)
        (cache / 'pending').write_text('keep checkpoint intact')
        self.assertEqual(refresh.prune_completed_caches(dict(self.config, root=str(frozen))), [])
        self.assertTrue((cache / 'pending').exists())

    def test_optional_cache_cleanup_error_does_not_undo_confirmed_installation(self):
        with patch.object(refresh, 'prune_completed_caches', side_effect=ValueError('malformed unrelated registration')):
            refresh.run(self.config, 'refresh')
        self.assertEqual(self.state()['lastSuccess'], 100000)
        self.assertIsNone(self.state()['lastError'])

    def test_legacy_flat_compiler_caches_leave_inputs_and_all_app_products_intact(self):
        flat = self.root / 'build/asura.paid/SwiftExplicitPrecompiledModules'
        objects = self.root / 'build/asura.paid/SwiftSoup.build'
        root_objects = self.root / 'build/Reader.build'
        source = self.root / 'build/approved.build'
        product = self.root / 'build/asura.paid/Release-iphoneos/Reader.app'
        symbols = product.with_suffix('.app.dSYM')
        profiles = self.root / 'build/profiles.build'
        state_dir = self.root / 'build/state.build'
        for path in [flat, objects, root_objects, source, product, symbols, profiles, state_dir]:
            path.mkdir(parents=True); (path / 'payload').write_text(path.name)
        self.config['inputs'].append('build/approved.build')
        self.config['profileCache'] = str(profiles)
        self.config['stateDir'] = 'build/state.build'
        before = refresh.fingerprint(self.root, self.config['inputs'])
        removed = refresh.prune_completed_caches(self.config)
        self.assertEqual(set(removed), {str(flat), str(objects), str(root_objects)})
        self.assertTrue((source / 'payload').exists())
        self.assertTrue((product / 'payload').exists())
        self.assertTrue((symbols / 'payload').exists())
        self.assertTrue((profiles / 'payload').exists())
        self.assertTrue((state_dir / 'payload').exists())
        self.assertEqual(refresh.fingerprint(self.root, self.config['inputs']), before)

    def test_pending_delivery_and_symlinked_cache_are_preserved(self):
        derived = self.root / 'build/DerivedData'
        derived.mkdir(parents=True); (derived / 'cache').write_text('keep until delivery settles')
        state = self.state(); state['pendingPush'] = {'id': 'pending'}; refresh.save(self.state_path, state)
        self.assertEqual(refresh.prune_completed_caches(self.config), [])
        self.assertTrue(derived.exists())
        state.pop('pendingPush'); refresh.save(self.state_path, state)
        import shutil
        shutil.rmtree(derived)
        outside = self.root / 'outside'; outside.mkdir(); (outside / 'cache').write_text('not ours')
        derived.symlink_to(outside, target_is_directory=True)
        self.assertEqual(refresh.prune_completed_caches(self.config), [])
        self.assertTrue((outside / 'cache').exists())

    def test_calendar_month_clamps_at_month_end(self):
        import datetime as dt
        start = dt.datetime(2026, 1, 31, tzinfo=dt.timezone.utc).timestamp()
        expected = dt.datetime(2026, 2, 28, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(refresh.next_due({'interval': 'monthly'}, start), expected)

    def test_empty_profile_set_is_not_a_renewal(self):
        self.assertFalse(refresh.advanced({}, {}, 0))


class KitFingerprintTests(unittest.TestCase):
    def test_kit_tests_and_linux_support_are_not_app_inputs_but_old_hashes_still_match(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['apps/ios/Kit/Sources/KitCore/A.swift', 'apps/ios/Kit/Package.swift',
                         'apps/ios/Kit/Tests/KitCoreTests/T.swift', 'apps/ios/Kit/Linux/swift-env.sh',
                         'apps/ios/App/Tests/AppOwn.swift']:
                (root / name).parent.mkdir(parents=True, exist_ok=True); (root / name).write_text(name)
            inputs = ['apps/ios/Kit', 'apps/ios/App']
            new, old = refresh.fingerprint(root, inputs), refresh.fingerprint(root, inputs, legacy=True)
            self.assertNotEqual(new, old)
            self.assertTrue(refresh.inputs_match(root, inputs, new))
            self.assertTrue(refresh.inputs_match(root, inputs, old))     # approved before the change
            self.assertFalse(refresh.inputs_match(root, inputs, None))
            (root / 'apps/ios/Kit/Tests/KitCoreTests/T.swift').write_text('changed test')
            (root / 'apps/ios/Kit/Linux/swift-env.sh').write_text('changed helper')
            self.assertEqual(refresh.fingerprint(root, inputs), new)         # not an app change
            (root / 'apps/ios/App/Tests/AppOwn.swift').write_text('changed')
            self.assertNotEqual(refresh.fingerprint(root, inputs), new)      # only Kit's subtrees are skipped
            (root / 'apps/ios/App/Tests/AppOwn.swift').write_text('apps/ios/App/Tests/AppOwn.swift')
            (root / 'apps/ios/Kit/Sources/KitCore/A.swift').write_text('changed source')
            self.assertFalse(refresh.inputs_match(root, inputs, new))
            self.assertFalse(refresh.inputs_match(root, inputs, old))


if __name__ == '__main__':
    unittest.main(buffer=True)
