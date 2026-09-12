"""Behavior checks using fake Xcode/device boundaries; no Mac or phone required."""
import importlib.util
import json
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

    def test_calendar_month_clamps_at_month_end(self):
        import datetime as dt
        start = dt.datetime(2026, 1, 31, tzinfo=dt.timezone.utc).timestamp()
        expected = dt.datetime(2026, 2, 28, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(refresh.next_due({'interval': 'monthly'}, start), expected)

    def test_empty_profile_set_is_not_a_renewal(self):
        self.assertFalse(refresh.advanced({}, {}, 0))


if __name__ == '__main__':
    unittest.main(buffer=True)
