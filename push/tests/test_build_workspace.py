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

    def test_filehost_policy_is_scoped_to_its_own_provider(self):
        project={'persistentBuildCache':{'apps':['filehost-local'],'cacheRoots':['build/filehost/native','build/filehost/DerivedData']}}
        self.assertIsNone(build_workspace.policy(project,'fmp4-local'))
        self.assertTrue(build_workspace.policy(project,'filehost-local')['perApp'])
        self.assertFalse(build_workspace.policy({'persistentBuildCache':True},'lua')['perApp'])
        with self.assertRaises(ValueError):build_workspace.policy({'persistentBuildCache':{'apps':['filehost-local'],'cacheRoots':['Sources']}},'filehost-local')

    def test_provider_layout_budget_excludes_large_frozen_inputs(self):
        self.workspace.mkdir(parents=True);(self.workspace/'source-binary').write_bytes(b'x'*100)
        for name in ['native','DerivedData']:
            p=self.workspace/'build/filehost'/name/'object';p.parent.mkdir(parents=True);p.write_bytes(b'x'*16)
        removed=build_workspace.trim(self.workspace,'filehost-local',maximum=30,cache_roots=['build/filehost/native','build/filehost/DerivedData'])
        self.assertEqual(removed,['build/filehost/native'])
        self.assertTrue((self.workspace/'build/filehost/DerivedData/object').exists())
        self.assertTrue((self.workspace/'source-binary').exists())

    def test_provider_cache_cannot_follow_an_external_parent_link(self):
        outside=self.root/'outside';outside.mkdir();(outside/'file').write_text('owner data')
        (self.workspace/'build').mkdir(parents=True);(self.workspace/'build/filehost').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):build_workspace.trim(self.workspace,'filehost-local',cache_roots=['build/filehost/DerivedData'])
        self.assertEqual((outside/'file').read_text(),'owner data')

    def test_repository_rooted_ios_cache_preserves_sources_and_signed_checkpoints(self):
        project={'persistentBuildCache':{'apps':['gallery'],'cacheRoots':['apps/ios/build/DerivedData']}}
        selected=build_workspace.policy(project,'gallery')
        cache=self.workspace/'apps/ios/build/DerivedData/object';cache.parent.mkdir(parents=True);cache.write_bytes(b'x'*32)
        source=self.workspace/'apps/ios/GalleryReader/source.swift';source.parent.mkdir();source.write_text('source')
        signed=self.root/'signed.app';signed.write_bytes(b'signed')
        self.assertEqual(build_workspace.trim(self.workspace,'gallery',maximum=16,cache_roots=selected['cacheRoots']),['apps/ios/build/DerivedData'])
        self.assertEqual(source.read_text(),'source');self.assertEqual(signed.read_bytes(),b'signed')
        with self.assertRaises(ValueError):build_workspace.cache_path('apps/ios/GalleryReader')

    def test_nested_ios_cache_cannot_follow_external_parent(self):
        outside=self.root/'outside';outside.mkdir();(outside/'owner').write_text('keep')
        self.workspace.mkdir(parents=True);(self.workspace/'apps').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):build_workspace.trim(self.workspace,'gallery',cache_roots=['apps/ios/build/DerivedData'])
        self.assertEqual((outside/'owner').read_text(),'keep')
