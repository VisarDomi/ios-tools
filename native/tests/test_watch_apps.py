import importlib.machinery
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('watch_apps', str(Path(__file__).parents[1] / 'scripts/watch-apps'))
spec = importlib.util.spec_from_loader(loader.name, loader)
apps = importlib.util.module_from_spec(spec); loader.exec_module(apps)


class WatchArtifactChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / 'Watch.app'; self.app.mkdir()
        self.info = {'CFBundleIdentifier': 'fixture.watch', 'CFBundleSupportedPlatforms': ['WatchOS'], 'CFBundleVersion': '10'}
        (self.app / 'Info.plist').write_bytes(plistlib.dumps(self.info))
        self.profile = {'ProvisionedDevices': ['WATCH'], 'TeamIdentifier': ['TEAM'],
                        'Entitlements': {'application-identifier': 'TEAM.fixture.watch'}}

    def test_expected_signed_watch_bundle_is_checked_without_launching(self):
        with patch.object(apps.subprocess, 'check_output', return_value=plistlib.dumps(self.profile)), \
                patch.object(apps.subprocess, 'run') as run:
            self.assertEqual(apps.validate_app(self.app, 'WATCH', 'fixture.watch', 'TEAM'), '10')
        self.assertEqual(run.call_args.args[0][:4], ['/usr/bin/codesign', '--verify', '--deep', '--strict'])

    def test_wrong_device_or_signing_team_never_reaches_installation(self):
        for watch, team in [('OTHER-WATCH', 'TEAM'), ('WATCH', 'OTHER-TEAM')]:
            with patch.object(apps.subprocess, 'check_output', return_value=plistlib.dumps(self.profile)), \
                    patch.object(apps.subprocess, 'run') as run:
                with self.assertRaises(RuntimeError): apps.validate_app(self.app, watch, 'fixture.watch', team)
            run.assert_not_called()

    def test_iphone_bundle_cannot_be_sent_to_watch(self):
        self.info['CFBundleSupportedPlatforms'] = ['iPhoneOS']
        (self.app / 'Info.plist').write_bytes(plistlib.dumps(self.info))
        with patch.object(apps.subprocess, 'check_output') as read:
            with self.assertRaises(RuntimeError): apps.validate_app(self.app, 'WATCH', 'fixture.watch', 'TEAM')
        read.assert_not_called()


if __name__ == '__main__': unittest.main()
