import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent


def listing(apps):
    return 'import json\nprint(json.dumps(' + repr(apps) + '))\n'


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

    def source(self, name, apps):
        scripts = self.home / name / 'scripts'
        scripts.mkdir(parents=True)
        (scripts / 'renewal.py').write_text(listing(apps))
        return str(self.home / name)

    def configure(self, *sources):
        return subprocess.run([sys.executable, str(self.home / 'renewal/scripts/configure-refresh.py'), *sources,
                               '--team', 'TEAM', '--device', 'DEVICE'], capture_output=True, text=True)

    def test_writes_each_listed_app_in_source_order(self):
        result = self.configure(self.source('a', [app('one'), app('two')]), self.source('b', [app('three')]))
        self.assertEqual(result.returncode, 0, result.stderr)
        index = json.loads((self.home / 'renewal/refresh-apps.local.json').read_text())
        self.assertEqual([Path(item['config']).stem for item in index['apps']], ['one', 'two', 'three'])
        config = json.loads(Path(index['apps'][0]['config']).read_text())
        self.assertEqual(list(config)[:7], ['name', 'root', 'app', 'bundleIds', 'inputs', 'build', 'environment'])
        self.assertEqual((config['team'], config['device'], config['interval']), ('TEAM', 'DEVICE', 'monthly'))
        self.assertEqual(config['stateDir'], str(self.home / 'renewal/build/installed-refresh/one'))

    def test_rejects_duplicate_names_and_unknown_fields(self):
        duplicate = self.configure(self.source('a', [app('one')]), self.source('b', [app('one')]))
        self.assertIn('Duplicate app names: one', duplicate.stderr)
        extra = self.configure(self.source('c', [app('two', team='OTHER')]))
        self.assertIn('without exactly these fields', extra.stderr)
        self.assertFalse((self.home / 'renewal/refresh-apps.local.json').exists())


if __name__ == '__main__':
    unittest.main()
