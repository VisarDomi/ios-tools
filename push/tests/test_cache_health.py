from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
import cache_health
from common import load

class CacheHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.request={'id':'one','repo':'video-platform','app':'filehost-local'}
        self.files={'ThirdParty/AetherCore/Sources/core.swift':'core1','VideoApp/ViewerController.swift':'ui1'}
    def record(self,output,**kwargs):
        return cache_health.record(self.root,self.root/'job',self.request,self.files,output,seconds=12,strategy='stable-workspace+cas',toolchain='sdk1',success=True,**kwargs)
    def test_target_misses_and_aggregate_metrics_are_distinct(self):
        output="SwiftCompile normal arm64 file (in target 'AetherEngine' from project 'AetherEngine')\nnote: Local cache miss for key: llvmcas://abc (in target 'AetherEngine' from project 'AetherEngine')\nnote: Replay cache miss (in target 'AetherEngine' from project 'AetherEngine')\nnote: 173 hits / 181 cacheable tasks (96%)\n"
        data=cache_health.analyse(output,self.files)
        self.assertEqual((data['hits'],data['cacheableTasks']),(173,181));self.assertEqual(data['modules']['AetherEngine']['misses'],1)
    def test_app_only_edit_does_not_hide_an_unchanged_core_recompile(self):
        miss="note: Local cache miss for key: llvmcas://abc (in target 'AetherEngine' from project 'AetherEngine')"
        self.assertEqual(self.record(miss)['warnings'],[])
        self.files['VideoApp/ViewerController.swift']='ui2'
        self.assertEqual(self.record(miss)['warnings'],['Unchanged module recompiled: AetherEngine'])
        self.files['ThirdParty/AetherCore/Sources/core.swift']='core2'
        self.assertEqual(self.record(miss)['warnings'],[])
    def test_ffmpeg_wrapper_has_its_own_dependency_fingerprint(self):
        self.files['ThirdParty/FFmpegBuild/Package.swift']='ffmpeg1'
        miss="note: Local cache miss for key: llvmcas://abc (in target 'AetherFFmpegBuild' from project 'FFmpegBuild')"
        self.record(miss)
        self.files['VideoApp/ViewerController.swift']='ui2'
        self.assertEqual(self.record(miss)['warnings'],['Unchanged module recompiled: AetherFFmpegBuild'])
        self.files['ThirdParty/FFmpegBuild/Package.swift']='ffmpeg2'
        self.assertEqual(self.record(miss)['warnings'],[])
    def test_toolchain_signature_tracks_the_actual_swift_compiler(self):
        developer=self.root/'Xcode.app/Contents/Developer'
        compiler=developer/'Toolchains/XcodeDefault.xctoolchain/usr/bin/swift-frontend'
        compiler.parent.mkdir(parents=True);compiler.write_bytes(b'compiler-one')
        environment={'DEVELOPER_DIR':str(developer)}
        before=cache_health.toolchain_signature(environment)
        compiler.write_bytes(b'compiler-two-updated')
        self.assertNotEqual(cache_health.toolchain_signature(environment),before)
    def test_repository_rooted_kit_changes_are_not_reported_as_unchanged(self):
        self.files={'apps/ios/Kit/Sources/KitReader/StripReaderView.swift':'reader1',
                    'apps/ios/GalleryReader/ReaderScreen.swift':'ui1'}
        miss="note: Local cache miss for key: llvmcas://abc (in target 'KitReader' from project 'NativeKit')"
        self.record(miss)
        self.files['apps/ios/Kit/Sources/KitReader/StripReaderView.swift']='reader2'
        self.assertEqual(self.record(miss)['warnings'],[])
        self.files['apps/ios/GalleryReader/ReaderScreen.swift']='ui2'
        self.assertEqual(self.record(miss)['warnings'],['Unchanged module recompiled: KitReader'])
    def test_unknown_layout_falls_back_to_all_declared_inputs(self):
        first=cache_health.module_inputs('KitReader',{'vendor/reader.swift':'one'})
        self.assertNotEqual(first,cache_health.module_inputs('KitReader',{'vendor/reader.swift':'two'}))
    def test_artifact_reuse_does_not_erase_compiler_baseline(self):
        miss="note: Local cache miss for key: llvmcas://abc (in target 'AetherEngine' from project 'AetherEngine')"
        self.record(miss);self.record('',reused=True)
        self.assertTrue(cache_health.status(self.root)['apps'][0]['artifactReused'])
        self.assertEqual(self.record(miss)['health'],'regression')
    def test_failed_attempt_and_known_eviction_do_not_create_false_regressions(self):
        miss="note: Local cache miss for key: llvmcas://abc (in target 'AetherEngine' from project 'AetherEngine')"
        self.record(miss,evicted=['build/filehost/DerivedData'])
        self.assertEqual(self.record(miss)['warnings'],[])
        previous=load(self.root/'cache-health/video-platform/filehost-local.json')
        cache_health.record(self.root,self.root/'failed',self.request,self.files,miss,seconds=1,strategy='stable-workspace+cas',toolchain='sdk1',success=False)
        current=load(self.root/'cache-health/video-platform/filehost-local.json')
        self.assertEqual(current['baseline'],previous['baseline'])
        self.assertEqual(current['latest']['health'],'build-failed')
    def test_sdk_change_resets_comparison(self):
        miss="note: Local cache miss for key: llvmcas://abc (in target 'AetherEngine' from project 'AetherEngine')"
        self.record(miss)
        data=cache_health.record(self.root,self.root/'job2',self.request,self.files,miss,seconds=1,strategy='stable-workspace+cas',toolchain='sdk2',success=True)
        self.assertEqual(data['warnings'],[])

    def test_skipped_module_remains_in_comparison_baseline(self):
        miss="note: Local cache miss for key: llvmcas://abc (in target 'AetherEngine' from project 'AetherEngine')"
        self.record(miss)
        warm=self.record('')
        self.assertFalse(warm['modules']['AetherEngine']['scheduled'])
        self.assertEqual(self.record(miss)['warnings'],['Unchanged module recompiled: AetherEngine'])
