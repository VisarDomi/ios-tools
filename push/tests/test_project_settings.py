import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import client
import worker


class ProjectSettings(unittest.TestCase):
    """A project may declare its own push settings in ios-push.json at its root (its short
    names, cache policy, preparation and tests), so its app names need not live here."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.tools = Path(self.temp.name) / 'tools'; (self.tools / 'push').mkdir(parents=True)
        self.work = Path(self.temp.name) / 'work'; (self.work / 'demo').mkdir(parents=True)
        (self.tools / 'push/projects.json').write_text(json.dumps({'demo': {'path': 'demo', 'tests': ['bash', 'old.sh']}}))

    def registry(self):
        with mock.patch.object(client, 'TOOLS', self.tools), mock.patch.object(client, 'ON_MAC', False), \
                mock.patch.dict(os.environ, {'IOS_PUSH_WORKSPACE': str(self.work)}):
            return client.projects()['demo']

    def test_the_project_file_is_merged_over_the_registry_entry(self):
        (self.work / 'demo/ios-push.json').write_text(json.dumps({
            'aliases': {'a': 'app-a'}, 'tests': ['bash', 'new.sh'], 'root': '/elsewhere', 'path': 'other',
            'persistentBuildCache': {'apps': ['app-a'], 'cacheRoots': ['build/a']}}))
        project = self.registry()
        self.assertEqual(project['aliases'], {'a': 'app-a'})
        self.assertEqual(project['tests'], ['bash', 'new.sh'])
        self.assertEqual(project['persistentBuildCache']['apps'], ['app-a'])
        # Where the project is stays the registry's.
        self.assertEqual((project['root'], project['path']), (str(self.work / 'demo'), 'demo'))

    def test_without_a_project_file_the_registry_entry_stands(self):
        self.assertEqual(self.registry()['tests'], ['bash', 'old.sh'])

    def test_the_worker_takes_the_cache_policy_from_the_request_else_the_registry(self):
        policy = {'apps': ['app-a'], 'cacheRoots': ['build/a/DerivedData']}
        self.assertTrue(worker.cache_policy_for({'repo': 'demo', 'persistentBuildCache': policy}, 'app-a')['perApp'])
        self.assertIsNone(worker.cache_policy_for({'repo': 'demo', 'persistentBuildCache': policy}, 'app-b'))
        (self.tools / 'push/projects.json').write_text(json.dumps({'demo': {'path': 'demo', 'persistentBuildCache': policy}}))
        with mock.patch.object(worker, 'TOOLS', self.tools):
            self.assertTrue(worker.cache_policy_for({'repo': 'demo'}, 'app-a')['perApp'])


if __name__ == '__main__':
    unittest.main()
