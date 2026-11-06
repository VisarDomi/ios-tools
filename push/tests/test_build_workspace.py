import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
import build_workspace
from common import digest


class BuildWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'checkpoint'; (self.source / 'Sources').mkdir(parents=True)
        self.code = self.source / 'Sources/code.swift'; self.code.write_text('let value = 1')
        self.workspace = self.root / 'cache/source'

    def files(self): return {'Sources/code.swift': digest(self.code)}

    def test_stable_paths_keep_unchanged_inputs_and_invalidate_changed_bytes(self):
        build_workspace.prepare(self.source, self.files(), self.workspace)
        cached = self.workspace / 'Sources/code.swift'
        os.utime(cached, (1, 1)); old_time = cached.stat().st_mtime_ns
        output = self.workspace / 'build/DerivedData/demo/object'; output.parent.mkdir(parents=True); output.write_bytes(b'cached')
        build_workspace.prepare(self.source, self.files(), self.workspace)
        self.assertEqual(cached.stat().st_mtime_ns, old_time)
        self.code.write_text('let value = 2'); os.utime(self.code, (1, 1))
        build_workspace.prepare(self.source, self.files(), self.workspace)
        self.assertEqual(cached.read_text(), 'let value = 2')
        self.assertNotEqual(cached.stat().st_mtime_ns, old_time)
        self.assertEqual(output.read_bytes(), b'cached')

    def test_interrupted_copy_and_unsafe_cached_links_are_reconciled(self):
        outside = self.root / 'outside'; outside.mkdir(); (outside / 'code.swift').write_text('owner file')
        self.workspace.mkdir(parents=True); (self.workspace / 'Sources').symlink_to(outside, target_is_directory=True)
        (self.workspace / '.source-interrupted').write_text('partial')
        build_workspace.prepare(self.source, self.files(), self.workspace)
        self.assertFalse((self.workspace / 'Sources').is_symlink())
        self.assertFalse((self.workspace / '.source-interrupted').exists())
        self.assertEqual((outside / 'code.swift').read_text(), 'owner file')
        self.assertEqual((self.workspace / 'Sources/code.swift').read_text(), self.code.read_text())

    def test_changed_checkpoint_is_rejected_before_compilation(self):
        files = self.files(); self.code.write_text('unexpected mutation')
        with self.assertRaisesRegex(RuntimeError, 'Source changed'):
            build_workspace.prepare(self.source, files, self.workspace)
        self.assertFalse((self.workspace / 'Sources/code.swift').exists())

    def test_empty_declared_resource_directories_remain_available(self):
        (self.source / 'Native').mkdir()
        build_workspace.prepare(self.source, self.files(), self.workspace, input_directories=['Sources', 'Native'])
        self.assertTrue((self.workspace / 'Native').is_dir())

    def test_cache_budget_prunes_only_regenerable_compiler_outputs(self):
        build_workspace.prepare(self.source, self.files(), self.workspace)
        for name in ['older', 'current']:
            path = self.workspace / 'build/DerivedData' / name / 'object'
            path.parent.mkdir(parents=True); path.write_bytes(b'x' * 16)
        signed = self.root / 'signed.app'; signed.write_bytes(b'signed checkpoint')
        build_workspace.trim(self.workspace, 'current', maximum=30)
        self.assertFalse((self.workspace / 'build/DerivedData/older').exists())
        self.assertTrue((self.workspace / 'build/DerivedData/current/object').exists())
        self.assertEqual((self.workspace / 'Sources/code.swift').read_text(), self.code.read_text())
        self.assertEqual(signed.read_bytes(), b'signed checkpoint')
