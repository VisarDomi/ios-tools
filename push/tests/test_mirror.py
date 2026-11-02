import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class MirrorTests(unittest.TestCase):
    def test_mirror_uses_committed_tools_without_working_edits_or_private_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); repository = root / 'repository'; repository.mkdir()
            script = Path(__file__).resolve().parents[2] / 'mac-sync'
            shutil.copy2(script, repository / 'mac-sync')
            (repository / 'tool.py').write_text('tested tool')
            subprocess.run(['git', 'init', '-q', str(repository)], check=True)
            subprocess.run(['git', '-C', str(repository), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repository), '-c', 'user.name=Queue Test', '-c', 'user.email=queue@example.invalid', 'commit', '-qm', 'tested tools'], check=True)
            (repository / 'tool.py').write_text('unfinished edit')
            (repository / 'private.local.json').write_text('private setting')
            (repository / 'untracked.py').write_text('unfinished new module')
            binary = root / 'bin'; binary.mkdir(); result = root / 'result'; result.mkdir()
            fake = binary / 'rsync'
            fake.write_text('#!/usr/bin/env python3\nimport os,pathlib,shutil,sys\nsource=pathlib.Path(sys.argv[-2]);out=pathlib.Path(os.environ["MIRROR_TEST_RESULT"])\nfor path in source.rglob("*"):\n if path.is_file():\n  target=out/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)\n')
            fake.chmod(0o755)
            environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'], MIRROR_TEST_RESULT=str(result))
            subprocess.run(['/bin/sh', str(repository / 'mac-sync')], env=environment, check=True)
            self.assertEqual((result / 'tool.py').read_text(), 'tested tool')
            self.assertFalse((result / 'private.local.json').exists())
            self.assertFalse((result / 'untracked.py').exists())


if __name__ == '__main__': unittest.main()
