import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import job_launcher  # noqa: E402


class JobLauncherTest(unittest.TestCase):
    def test_named_launcher_runs_python_with_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = job_launcher.python_launcher('manga-reader renewal', directory, python=sys.executable)
            self.assertEqual(Path(path).name, 'manga-reader renewal')
            self.assertTrue(os.access(path, os.X_OK))
            out = subprocess.run([path, '-c', 'import sys; print(sys.argv[1:])', 'a b', 'c'],
                                 capture_output=True, text=True, check=True).stdout
            self.assertEqual(out.strip(), "['a b', 'c']")

    def test_is_idempotent_and_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(job_launcher.python_launcher('iPhone pairing', directory))
            stamp = path.stat().st_mtime_ns
            self.assertEqual(job_launcher.python_launcher('iPhone pairing', directory), str(path))
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            path.write_text('broken'); path.chmod(0o644)
            job_launcher.python_launcher('iPhone pairing', directory)
            self.assertEqual(path.read_bytes(), job_launcher.body())
            self.assertTrue(os.access(path, os.X_OK))

    def test_rejects_paths(self):
        for bad in ('', ' ', 'a/b', '.hidden'):
            with self.assertRaises(ValueError):
                job_launcher.python_launcher(bad, '/tmp')

    def test_renewal_name(self):
        self.assertEqual(job_launcher.renewal_name('deep-town'), 'deep-town renewal')


if __name__ == '__main__':
    unittest.main()
