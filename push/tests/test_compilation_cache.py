from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from compilation_cache import build_environment


class CompilationCacheTests(unittest.TestCase):
    def test_app_intents_keep_real_swift_sources_for_metadata_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'source'
            widget = source/'Sources/Widgets/Refresh.swift'
            widget.parent.mkdir(parents=True)
            widget.write_text('import AppIntents\nstruct Refresh: AppIntent {}\n')
            env = build_environment({}, root/'metadata', source, root/'cache')
            text = Path(env['XCODE_XCCONFIG_FILE']).read_text()
            self.assertIn('SWIFT_ENABLE_PREFIX_MAPPING = NO\n', text)
            self.assertIn('SWIFT_OTHER_PREFIX_MAPPINGS = $(inherited)\n', text)
            self.assertIn('COMPILATION_CACHE_ENABLE_CACHING = YES\n', text)
            self.assertIn('CLANG_ENABLE_PREFIX_MAPPING = YES\n', text)
            self.assertIn('CLANG_OTHER_PREFIX_MAPPINGS = $(inherited) "'+str(source)+'=/^src"', text)
            self.assertEqual(widget.read_text(),'import AppIntents\nstruct Refresh: AppIntent {}\n')
            self.assertNotIn('SWIFT_ENABLE_EMIT_CONST_VALUES', text)
            self.assertNotIn('LM_SKIP_METADATA_EXTRACTION', text)

    def test_sources_without_app_intents_skip_their_metadata_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'source'
            (source/'App').mkdir(parents=True)
            (source/'App/View.swift').write_text('import UIKit\n// AppIntents is mentioned only in a comment\n')
            text = Path(build_environment({}, root/'metadata', source, root/'cache')['XCODE_XCCONFIG_FILE']).read_text()
            self.assertIn('SWIFT_ENABLE_EMIT_CONST_VALUES = NO\n', text)
            self.assertIn('LM_SKIP_METADATA_EXTRACTION = YES\n', text)
            self.assertIn('SWIFT_ENABLE_PREFIX_MAPPING = YES\n', text)

    def test_every_provider_in_a_workspace_gets_identical_compiler_settings(self):
        # A provider switch must not change compiler settings, or Xcode re-plans and relinks every module.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'workspace'; source.mkdir()
            texts = [Path(build_environment({}, root / (provider + '-metadata'), source, root / 'cache')['XCODE_XCCONFIG_FILE']).read_text()
                     for provider in ['asura', 'lua']]
            self.assertEqual(texts[0], texts[1])
            self.assertIn('"' + str(source.resolve()) + '=/^src"', texts[0])

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
                self.assertIn('COMPILATION_CACHE_LIMIT_SIZE = 8G',contents)
                self.assertIn('COMPILATION_CACHE_CAS_PATH = '+str(cache)+'\n',contents)
                self.assertNotIn('SWIFT_OPTIMIZATION_LEVEL',contents)
                self.assertIn(str(source.resolve())+'=/^src',contents)
                self.assertIn('SWIFT_OTHER_PREFIX_MAPPINGS',contents)
                self.assertIn('CLANG_OTHER_PREFIX_MAPPINGS',contents)
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
