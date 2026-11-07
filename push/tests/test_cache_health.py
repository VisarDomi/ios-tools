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
