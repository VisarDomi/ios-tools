"""Diagnostic controls must be runnable and independent of routine JSC policy."""
import sys
import unittest
from pathlib import Path

NATIVE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(NATIVE/'scripts'))
from simulator_environment import diagnostic_environment,intel_wasm_overrides,CHECKED_WASM


class DiagnosticControls(unittest.TestCase):
    def test_every_saved_probe_compiles_without_running_or_contacting_devices(self):
        for path in (NATIVE/'simulator-health').glob('*.py'):
            with self.subTest(path=path.name):
                compile(path.read_text(),str(path),'exec')

    def test_default_control_removes_inherited_compat_and_unrelated_jsc_experiments(self):
        source=dict(intel_wasm_overrides(),PATH='/usr/bin',IOS_WORKLOAD_ACTIVE='123',
                    SIMCTL_CHILD___XPC_JSC_forceICFailure='true')
        result=diagnostic_environment(source,{'dumpOptions':'1'})
        self.assertEqual(result,{'PATH':'/usr/bin','IOS_WORKLOAD_ACTIVE':'123',
            'SIMCTL_CHILD_JSC_dumpOptions':'1','SIMCTL_CHILD___XPC_JSC_dumpOptions':'1'})
        self.assertIn('SIMCTL_CHILD_JSC_useWasmIPInt',source)

    def test_checked_nojit_control_sets_both_layers_without_retaining_bbq(self):
        result=diagnostic_environment(intel_wasm_overrides(),dict(CHECKED_WASM,useJIT='false'))
        for prefix in ('SIMCTL_CHILD_JSC_','SIMCTL_CHILD___XPC_JSC_'):
            self.assertEqual(result[prefix+'useJIT'],'false')
            self.assertEqual(result[prefix+'useWasmFaultSignalHandler'],'false')
            self.assertNotIn(prefix+'useBBQJIT',result)
            self.assertNotIn(prefix+'useWasmIPInt',result)


if __name__=='__main__':unittest.main()
