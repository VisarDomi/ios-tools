import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('watch_refresh', Path(__file__).with_name('refresh.py'))
refresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(refresh)


class CompanionProofChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['inspector/.venv/bin/python', 'native/scripts/watch-apps']:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
        self.output = self.root / 'actual.json'
        self.config = {'device': 'phone', 'team': 'TEAM'}
        self.target = {'device': 'watch', 'bundle': 'fixture.watch', 'app': self.root / 'Watch.app'}
        self.file = patch.object(refresh, '__file__', str(self.root / 'renewal/scripts/refresh.py'))
        self.file.start(); self.addCleanup(self.file.stop)

    def response(self, device='watch', installed=True):
        return {'device': device, 'installed': installed, 'transport': 'companion-lockdown',
                'apps': [{'bundleIdentifier': 'fixture.watch', 'bundleVersion': '10'}]}

    def invoke(self, report):
        def run(command, **kwargs):
            self.output.write_text(json.dumps(report))
            self.assertIn(str(self.target['app']), command)
            self.assertEqual(command[command.index('--phone') + 1], 'phone')
            self.assertNotIn('launch', command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(refresh.subprocess, 'run', side_effect=run):
            return refresh.companion_apps(self.config, self.target, self.output, install=True)

    def test_accepts_only_target_watch_inventory_after_installing_same_signed_path(self):
        self.assertEqual(self.invoke(self.response())[0]['bundleVersion'], '10')

    def test_other_watch_report_cannot_approve_target(self):
        self.assertIsNone(self.invoke(self.response(device='other-watch')))

    def test_read_only_inventory_cannot_acknowledge_same_version_renewal_install(self):
        self.assertIsNone(self.invoke(self.response(installed=False)))

    def test_timeout_discards_stale_previous_success(self):
        self.output.write_text(json.dumps(self.response()))
        with patch.object(refresh.subprocess, 'run', side_effect=subprocess.TimeoutExpired('watch-apps', 190)):
            self.assertIsNone(refresh.companion_apps(self.config, self.target, self.output, install=True))
        self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main()
