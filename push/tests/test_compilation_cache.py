from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from compilation_cache import build_environment


class CompilationCacheTests(unittest.TestCase):
    def test_frozen_jobs_share_a_bounded_cache_without_changing_source_or_optimisation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir()
            (source/'code.swift').write_text('let value = 1')
            cache=root/'shared cache'
            original={'DEVELOPMENT_TEAM':'TEAM'}
            for job in ['first','second']:
                env=build_environment(original,root/job,source,cache)
                contents=Path(env['XCODE_XCCONFIG_FILE']).read_text()
                self.assertIn('COMPILATION_CACHE_ENABLE_CACHING = YES',contents)
                self.assertIn('COMPILATION_CACHE_LIMIT_SIZE = 2G',contents)
                self.assertIn('COMPILATION_CACHE_CAS_PATH = "'+str(cache)+'"',contents)
                self.assertNotIn('SWIFT_OPTIMIZATION_LEVEL',contents)
                self.assertEqual(env['DEVELOPMENT_TEAM'],'TEAM')
            self.assertEqual(original,{'DEVELOPMENT_TEAM':'TEAM'})
            self.assertEqual(list(source.iterdir()),[source/'code.swift'])
            self.assertEqual((source/'code.swift').read_text(),'let value = 1')

    def test_existing_configuration_is_included_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=root/'provider settings.xcconfig';original.write_text('APP_SETTING = kept\n')
            env=build_environment({'XCODE_XCCONFIG_FILE':original.name},root/'metadata',root,root/'cache')
            text=Path(env['XCODE_XCCONFIG_FILE']).read_text()
            self.assertTrue(text.startswith('#include "'+str(original)+'"\n'))
            self.assertEqual(original.read_text(),'APP_SETTING = kept\n')

    def test_configuration_path_cannot_inject_another_build_setting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaises(ValueError):
                build_environment({'XCODE_XCCONFIG_FILE':'bad\nSETTING=bad'},root/'metadata',root,root/'cache')
