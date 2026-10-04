"""Deploy-time approval checks using a fake signed app; no Mac or phone required."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import deliver  # noqa: E402
import refresh  # noqa: E402


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'source').write_text('delivered runtime')
        (self.root / 'App.app').mkdir()
        (self.root / 'App.app/binary').write_text('built from delivered runtime')
        self.config = dict(root=str(self.root), app='App.app', team='TEAM', bundleIds=['host'],
                           inputs=['source'], interval='monthly', stateDir='state')
        self.state_path = self.root / 'state/state.json'
        self.record = self.root / 'state/delivery.json'
        self.renewed = {'TEAM.host': dict(id='TEAM.*', expires=50000000)}
        self.profiles = self.renewed
        self.old_hash = refresh.fingerprint(self.root, ['source'])
        refresh.save(self.state_path, dict(inputHash=self.old_hash, installedProfiles=self.renewed,
                                          lastSuccess=1790000000, nextDue=1792600000))
        self.start_patch(patch.object(refresh.Path, 'home', return_value=self.root))
        self.start_patch(patch.object(refresh.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))
        self.start_patch(patch.object(refresh, 'app_profiles', side_effect=lambda *_: self.profiles))
        (self.root / 'source').write_text('changed runtime')

    def start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self):
        return json.loads(self.state_path.read_text())

    def build(self):
        deliver.deliver(self.config, 'begin', 'host')
        (self.root / 'App.app/binary').write_text('built from changed runtime')
        deliver.deliver(self.config, 'built', 'host')

    def test_installed_build_is_approved_and_keeps_the_schedule(self):
        self.build()
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['inputHash'], refresh.fingerprint(self.root, ['source']))
        self.assertEqual(self.state()['lastSuccess'], 1790000000)
        self.assertEqual(self.state()['nextDue'], refresh.next_due(self.config, 1790000000))
        self.assertFalse(self.record.exists())

    def test_first_approval_is_due_now(self):
        self.state_path.unlink()
        self.build()
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['lastSuccess'], 0)

    def test_earlier_delivered_profile_is_due_now(self):
        self.profiles = {'TEAM.host': dict(id='TEAM.*', expires=40000000)}
        self.build()
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['lastSuccess'], 0)
        self.assertEqual(self.state()['installedProfiles'], self.profiles)

    def test_inputs_changed_during_build_are_not_approved(self):
        deliver.deliver(self.config, 'begin', 'host')
        (self.root / 'source').write_text('another sync')
        deliver.deliver(self.config, 'built', 'host')
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['inputHash'], self.old_hash)

    def test_inputs_changed_after_build_are_not_approved(self):
        self.build()
        (self.root / 'source').write_text('another sync')
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['inputHash'], self.old_hash)
        self.assertFalse(self.record.exists())

    def test_replaced_app_is_not_approved(self):
        self.build()
        (self.root / 'App.app/binary').write_text('another build')
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['inputHash'], self.old_hash)

    def test_install_without_recorded_build_is_not_approved(self):
        deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['inputHash'], self.old_hash)

    def test_other_identity_is_not_approved_and_keeps_the_registered_record(self):
        self.build()
        for step in ['begin', 'built', 'installed']:
            deliver.deliver(self.config, step, 'host.unsuffixed')
        self.assertEqual(self.state()['inputHash'], self.old_hash)
        self.assertTrue(self.record.exists())

    def test_held_signing_lock_times_out_and_keeps_the_build_record(self):
        self.build()
        lock_path = self.root / 'Library/Caches/ios-app-refresh/signing.lock'
        lock_path.parent.mkdir(parents=True)
        with lock_path.open('a') as held, patch.object(deliver, 'LOCK_TIMEOUT', 0), \
                patch.object(deliver.time, 'sleep'):
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaisesRegex(RuntimeError, 'still signing'):
                deliver.deliver(self.config, 'installed', 'host')
        self.assertEqual(self.state()['inputHash'], self.old_hash)
        self.assertTrue(self.record.exists())
        deliver.deliver(self.config, 'installed', 'host')
        self.assertNotEqual(self.state()['inputHash'], self.old_hash)


if __name__ == '__main__':
    unittest.main(buffer=True)
