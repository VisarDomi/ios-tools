import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent


def app(name, **extra):
    return dict(dict(name=name, root='/mirror', app='build/' + name + '.app', bundleIds=['com.example.' + name],
                     inputs=['Sources'], build=['/bin/true'], environment={}), **extra)


class ConfigureRefreshTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()  # macOS temp paths are symlinks
        self.addCleanup(shutil.rmtree, self.home)
        (self.home / 'renewal/scripts').mkdir(parents=True)
        for name in ['configure-refresh.py', 'refresh.py']:
            shutil.copy(SCRIPTS / name, self.home / 'renewal/scripts' / name)
        self.store = self.home / 'Library/Application Support/ios-tools/renewal'

    def source(self, name, repo, apps):
        scripts = self.home / name / 'scripts'
        scripts.mkdir(parents=True)
        (scripts / 'renewal.py').write_text('import json\nprint(json.dumps(' + repr(dict(repo=repo, apps=apps)) + '))\n')
        return str(self.home / name)

    def configure(self, source, settings=True):
        if settings:
            (self.home / 'ios-tools.local.json').write_text(json.dumps(dict(team='TEAM', device='DEVICE')))
        return subprocess.run([sys.executable, str(self.home / 'renewal/scripts/configure-refresh.py'), source],
                              capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))

    def test_writes_the_repository_apps_into_its_own_store(self):
        result = self.configure(self.source('a', 'repo-a', [app('one'), app('two')]))
        self.assertEqual(result.returncode, 0, result.stderr)
        index = json.loads((self.store / 'repo-a/apps.json').read_text())
        self.assertEqual(index['repo'], 'repo-a')
        self.assertEqual([Path(item['config']).stem for item in index['apps']], ['one', 'two'])
        config = json.loads(Path(index['apps'][0]['config']).read_text())
        self.assertEqual(list(config)[:7], ['name', 'root', 'app', 'bundleIds', 'inputs', 'build', 'environment'])
        self.assertEqual((config['team'], config['device'], config['interval']), ('TEAM', 'DEVICE', 'monthly'))
        self.assertEqual(config['stateDir'], str(self.store / 'repo-a/one'))

    def test_drops_configs_of_apps_the_repository_no_longer_lists(self):
        self.configure(self.source('a', 'repo-a', [app('one'), app('two')]))
        (self.home / 'a/scripts/renewal.py').write_text(
            'import json\nprint(json.dumps(' + repr(dict(repo='repo-a', apps=[app('one')])) + '))\n')
        self.assertEqual(self.configure(str(self.home / 'a')).returncode, 0)
        self.assertEqual(sorted(p.stem for p in (self.store / 'repo-a/config').glob('*.json')), ['one'])

    def test_rejects_an_app_another_repository_renews(self):
        self.assertEqual(self.configure(self.source('a', 'repo-a', [app('one')])).returncode, 0)
        result = self.configure(self.source('b', 'repo-b', [app('copy', bundleIds=['com.example.one'])]))
        self.assertIn('repo-a already renews com.example.one', result.stderr)
        self.assertFalse((self.store / 'repo-b').exists())

    def test_rejects_duplicates_unknown_fields_and_unnamed_repositories(self):
        self.assertIn('Duplicate app names: one', self.configure(self.source('a', 'repo-a', [app('one'), app('one')])).stderr)
        self.assertIn('without exactly these fields', self.configure(self.source('b', 'repo-b', [app('two', team='X')])).stderr)
        self.assertIn('must name its repository', self.configure(self.source('c', '', [app('three')])).stderr)

    def test_explains_missing_local_config(self):
        self.assertIn('copy ios-tools.example.json', self.configure(self.source('a', 'repo-a', []), settings=False).stderr)

    def test_example_config_has_every_setting(self):
        example = json.loads((SCRIPTS.parents[1] / 'ios-tools.example.json').read_text())
        self.assertEqual(sorted(example), ['device', 'team'])


if __name__ == '__main__':
    unittest.main()
