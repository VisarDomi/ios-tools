"""Safety regressions with fake Mac boundaries; no simulator or physical phone is booted."""
import argparse
import ctypes
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('mac_workload', str(Path(__file__).parents[1] / 'scripts/mac-workload'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
DEVICE = '12345678-1234-1234-1234-123456789ABC'
HEALTHY = dict(load=1, pressure=1, diskGiB=20)


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('ROOT', self.root), ('LOCK', self.root / 'signing.lock'), ('POLICY', self.root / 'policy.json')]:
            p = patch.object(m, name, value)
            p.start()
            self.addCleanup(p.stop)
        p=patch.object(m,'tool_path',return_value='/fake/simctl')
        p.start();self.addCleanup(p.stop)

    def test_preflight_rejects_every_unsafe_start(self):
        for sample in [dict(HEALTHY, load=7), dict(HEALTHY, pressure=2), dict(HEALTHY, diskGiB=11)]:
            with self.subTest(sample=sample), self.assertRaises(m.UnsafeWorkload):
                m.preflight(sample, [])
        with self.assertRaises(m.UnsafeWorkload):
            m.preflight(HEALTHY, [DEVICE])
        with self.assertRaises(m.UnsafeWorkload):
            m.preflight(HEALTHY, [], True)

    def test_admission_wait_starts_nothing_until_unchanged_limits_are_met(self):
        with patch.object(m,'devices',return_value=[]),patch.object(m,'metrics',side_effect=[dict(HEALTHY,load=20),HEALTHY]), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),patch.object(m.time,'sleep') as sleep:
            self.assertEqual(m.wait_for_idle(10),[])
            sleep.assert_called_once()

    def test_admission_wait_does_not_take_over_busy_guests_or_critical_pressure(self):
        for sample,guests in [(dict(HEALTHY,pressure=4),[]),(HEALTHY,[dict(udid=DEVICE,state='Booted')])]:
            with patch.object(m,'devices',return_value=guests),patch.object(m,'metrics',return_value=sample), \
                 patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),patch.object(m.time,'sleep') as sleep:
                with self.assertRaises(m.UnsafeWorkload):m.wait_for_idle(10)
                sleep.assert_not_called()

    def test_build_admission_uses_three_idle_samples_despite_residual_load(self):
        sample=dict(HEALTHY,load=100,cpuIdle=85,probeSeconds=.01)
        with patch.object(m,'devices',return_value=[]),patch.object(m,'metrics',return_value=sample), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),patch.object(m.time,'sleep') as sleep:
            self.assertEqual(m.wait_for_idle(10,kind='build'),[])
            self.assertEqual(sleep.call_count,2)
        with self.assertRaises(m.UnsafeWorkload): m.preflight(sample,[])

    def test_build_idle_exception_cannot_bypass_other_resource_checks(self):
        for sample in [dict(HEALTHY,load=100,cpuIdle=10,probeSeconds=.01),
                       dict(HEALTHY,load=100,cpuIdle=90,probeSeconds=2),
                       dict(HEALTHY,load=100,cpuIdle=90,probeSeconds=.01,pressure=2)]:
            with self.subTest(sample=sample),patch.object(m,'devices',return_value=[]),patch.object(m,'metrics',return_value=sample), \
                 patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),patch.object(m.time,'monotonic',side_effect=[0,20]), \
                 self.assertRaises(m.UnsafeWorkload): m.wait_for_idle(0,kind='build')

    def test_simulator_gives_queued_builds_admission_priority(self):
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'])
        with patch.object(m,'queued_delivery',return_value='pending-app'),patch.object(m,'devices') as devices, \
             self.assertRaisesRegex(m.UnsafeWorkload,'deferred to queued'):
            m.run_workload(args)
        devices.assert_not_called()

    def test_running_simulator_command_yields_to_new_delivery(self):
        with (self.root/'yield.jsonl').open('w') as stream,patch.object(m,'metrics',return_value=HEALTHY), \
             patch.object(m,'queued_delivery',return_value='new-app'),self.assertRaisesRegex(m.UnsafeWorkload,'yielding to queued'):
            m.monitor([sys.executable,'-c','import time; time.sleep(30)'],time.monotonic()+10,stream,1,'command',yield_to_builds=True)

    def test_quarantine_requires_fresh_recorded_matching_driver_trial(self):
        p = dict(simulatorBlockedReason='GPU panic')
        with self.assertRaises(m.UnsafeWorkload):
            m.simulator_policy(p, False, 0, now=100)
        p.update(trialUntil=200, trialChange='queue patch', requiredMetalCoalesce=0)
        with self.assertRaises(m.UnsafeWorkload):
            m.simulator_policy(p, True, 1, now=100)
        with self.assertRaises(m.UnsafeWorkload):
            m.simulator_policy(p, True, 0, now=201)
        m.simulator_policy(p, True, 0, now=100)

    def test_sustained_pressure_resets_after_a_good_sample(self):
        bad = dict(HEALTHY, load=20)
        self.assertEqual(m.pressure_failure(bad, None, 100), (None, 100))
        self.assertIsNotNone(m.pressure_failure(bad, 100, 112)[0])
        self.assertEqual(m.pressure_failure(HEALTHY, 100, 110), (None, None))

    def test_queued_boot_load_is_not_treated_as_an_unresponsive_host(self):
        sample=dict(HEALTHY,load=150,cpuIdle=30,probeSeconds=.03)
        self.assertEqual(m.pressure_failure(sample,None,100),(None,None))
        sample['probeSeconds']=4
        self.assertIsNotNone(m.pressure_failure(sample,None,100)[0])

    def test_slow_control_probe_aborts_even_without_a_large_load_number(self):
        sample=dict(HEALTHY,probeSeconds=2.5)
        self.assertEqual(m.pressure_failure(sample,None,100),(None,100))
        self.assertIsNotNone(m.pressure_failure(sample,100,112)[0])

    def test_pressure_probe_reads_kernel_in_process_and_validates_shape(self):
        class Kernel:
            class Call:
                def __call__(self,name,value,size,new,new_size):
                    self.name=name
                    ctypes.cast(value,ctypes.POINTER(ctypes.c_uint32))[0]=self.pressure
                    ctypes.cast(size,ctypes.POINTER(ctypes.c_size_t))[0]=self.size
                    return 0
            sysctlbyname=Call()
        kernel=Kernel()
        for value in (1,2,4):
            kernel.sysctlbyname.pressure=value;kernel.sysctlbyname.size=4
            with patch.object(m,'_MACH',kernel),patch.object(m,'capture',side_effect=AssertionError('probe must not spawn a process')):
                self.assertEqual(m.memory_pressure(),value)
                self.assertEqual(kernel.sysctlbyname.name,b'kern.memorystatus_vm_pressure_level')
        for value,size in ((8,4),(1,8)):
            kernel.sysctlbyname.pressure=value;kernel.sysctlbyname.size=size
            with patch.object(m,'_MACH',kernel),self.assertRaises(m.UnsafeWorkload):m.memory_pressure()

    def test_metrics_does_not_spawn_a_health_check_process(self):
        with patch.object(m,'cpu_idle',return_value=50),patch.object(m,'memory_pressure',return_value=1), \
             patch.object(m,'capture',side_effect=AssertionError('metrics must stay in process')):
            sample=m.metrics()
            self.assertEqual(sample['pressure'],1)
            self.assertEqual(sample['cpuIdle'],50)
            self.assertGreaterEqual(sample['probeSeconds'],0)

    def test_owned_webcontent_crash_is_detected_but_old_and_other_guests_are_not(self):
        root=self.root/'crashes';root.mkdir()
        watch=m.WebContentCrashWatch(DEVICE,root,started=100)
        def write(name,device,launch):
            report=dict(coalitionName='com.apple.CoreSimulator.SimDevice.'+device,procLaunch=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(launch))+'.0000 +0000')
            (root/name).write_text(json.dumps({'metadata':True})+'\n'+json.dumps(report))
        write('com.apple.WebKit.WebContent-old.ips',DEVICE,90)
        write('com.apple.WebKit.WebContent-other.ips','OTHER',110)
        self.assertIsNone(watch.failure())
        (root/'com.apple.WebKit.WebContent-new.ips').write_text('{partial')
        self.assertIsNone(watch.failure())
        write('com.apple.WebKit.WebContent-new.ips',DEVICE,110)
        self.assertIn('new.ips',watch.failure())

    def test_cpu_idle_delta_handles_counter_wrap(self):
        self.assertEqual(m.idle_delta([10,10,10,10],[20,20,40,20]),50)
        self.assertEqual(m.idle_delta([0xfffffffe,0,0xfffffffe,0],[0,0,0,0]),50)

    def test_critical_signals_abort_without_grace(self):
        for sample in [dict(HEALTHY, load=41), dict(HEALTHY, pressure=4), dict(HEALTHY, diskGiB=7)]:
            self.assertIsNotNone(m.pressure_failure(sample, None, 100)[0])

    def test_driver_trial_cannot_remove_absolute_load_or_memory_limits(self):
        settings=dict(trialSoftLoad=999,trialHardLoad=999)
        self.assertEqual(m.trial_limits(settings,False),dict(soft=16,hard=40))
        limits=m.trial_limits(settings,True)
        self.assertEqual(limits,dict(soft=40,hard=80))
        self.assertIsNotNone(m.pressure_failure(dict(HEALTHY,load=81),None,100,limits)[0])
        self.assertIsNotNone(m.pressure_failure(dict(HEALTHY,pressure=4),None,100,limits)[0])

    def test_accepted_simulator_profile_still_requires_its_graphics_patch(self):
        settings=dict(requiredMetalCoalesce=0,simulatorSoftLoad=40,simulatorHardLoad=80)
        with self.assertRaises(m.UnsafeWorkload):m.simulator_policy(settings,False,1)
        m.simulator_policy(settings,False,0)
        self.assertEqual(m.trial_limits(settings,False,'build'),dict(soft=16,hard=40))
        self.assertEqual(m.trial_limits(settings,False,'simulator'),dict(soft=40,hard=80))

    def test_shared_lock_blocks_an_independent_builder(self):
        with m.signing_lock():
            code = 'import fcntl,sys; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
            p = subprocess.run([sys.executable, '-c', code, str(m.LOCK)], capture_output=True)
            self.assertNotEqual(p.returncode, 0)

    def test_inherited_lock_survives_child_and_cannot_point_to_another_file(self):
        with m.signing_lock() as fd:
            with patch.dict(os.environ, IOS_REFRESH_LOCK_FD=str(fd)):
                with m.signing_lock() as inherited:
                    self.assertEqual(inherited, fd)
        wrong = self.root / 'wrong'
        with wrong.open('w') as f, patch.dict(os.environ, IOS_REFRESH_LOCK_FD=str(f.fileno())):
            with self.assertRaises(m.UnsafeWorkload):
                with m.signing_lock():
                    self.fail('Wrong lock accepted')

    def test_deadline_terminates_the_owned_child(self):
        child = self.root / 'child.pid'
        command = [sys.executable, '-c', 'import os,time,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)', str(child)]
        with m.signing_lock() as fd, (self.root / 'log').open('w') as log, patch.object(m, 'metrics', return_value=HEALTHY):
            with self.assertRaisesRegex(m.UnsafeWorkload, 'deadline'):
                m.monitor(command, time.monotonic() + .4, log, fd, 'test')
        with self.assertRaises(ProcessLookupError):
            os.kill(int(child.read_text()), 0)

    def test_compiler_child_receives_the_real_inherited_lock_descriptor(self):
        marker=self.root/'inherited.json'
        code='import os,fcntl,json,sys; fd=int(os.environ["IOS_REFRESH_LOCK_FD"]); fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); open(sys.argv[1],"w").write(json.dumps(os.fstat(fd).st_ino))'
        with m.signing_lock() as fd,(self.root/'log').open('w') as log,patch.object(m,'metrics',return_value=HEALTHY):
            m.monitor([sys.executable,'-c',code,str(marker)],time.monotonic()+2,log,fd,'test')
            self.assertEqual(json.loads(marker.read_text()),m.LOCK.stat().st_ino)

    def test_launch_configuration_reaches_child_without_changing_parent(self):
        marker=self.root/'launch-environment.json'
        flags=m.checked_wasm_overrides()
        code='import os,json,sys; open(sys.argv[1],"w").write(json.dumps({k:os.environ.get(k) for k in json.loads(sys.argv[2])}))'
        before={k:os.environ.get(k) for k in flags}
        with m.signing_lock() as fd,(self.root/'log').open('w') as log,patch.object(m,'metrics',return_value=HEALTHY):
            m.monitor([sys.executable,'-c',code,str(marker),json.dumps(list(flags))],time.monotonic()+4,log,fd,'test',extra_env=flags)
        self.assertEqual(json.loads(marker.read_text()),flags)
        self.assertEqual({k:os.environ.get(k) for k in flags},before)

    def test_checked_mode_is_recorded_in_session_and_sent_only_to_test_command(self):
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'],checked_wasm=True)
        observed=[]
        def monitor(*arguments,**kwargs):
            observed.append((arguments,json.loads((m.ROOT/'workload-current.json').read_text())))
        with patch.object(m,'metrics',return_value=HEALTHY), \
             patch.object(m,'devices',return_value=[dict(udid=DEVICE,state='Shutdown',isAvailable=True)]), \
             patch.object(m,'metal_coalescing',return_value=1), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)), \
             patch.object(m,'monitor',side_effect=monitor),patch.object(m,'shutdown'):
            m.run_workload(args)
        self.assertTrue(all(lease['checkedWasm'] for _,lease in observed))
        self.assertEqual(observed[-1][0][-1],m.checked_wasm_overrides())
        self.assertEqual(len(observed[0][0]),6) # boot receives no JSC overrides

    def test_cleanup_failure_keeps_the_explicit_recovery_lease(self):
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'])
        with patch.object(m,'metrics',return_value=HEALTHY), \
             patch.object(m,'devices',return_value=[dict(udid=DEVICE,state='Shutdown',isAvailable=True)]), \
             patch.object(m,'metal_coalescing',return_value=1), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)), \
             patch.object(m,'monitor'),patch.object(m,'shutdown',side_effect=m.UnsafeWorkload('shutdown stuck')):
            with self.assertRaisesRegex(m.UnsafeWorkload,'shutdown stuck'):m.run_workload(args)
        lease=json.loads((m.ROOT/'workload-current.json').read_text())
        self.assertEqual(lease['device'],DEVICE)
        self.assertEqual(lease['expiresAt'],0)
        self.assertIn('shutdown stuck',lease['cleanupFailed'])

    def test_failed_boot_always_shuts_down_only_the_explicit_guest(self):
        args = argparse.Namespace(kind='simulator', device=DEVICE, trial=False, timeout=10, command=['qa'])
        with patch.object(m, 'metrics', return_value=HEALTHY), \
             patch.object(m, 'devices', return_value=[dict(udid=DEVICE, state='Shutdown', isAvailable=True)]), \
             patch.object(m, 'metal_coalescing', return_value=1), \
             patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(m, 'monitor', side_effect=m.UnsafeWorkload('boot failed')), \
             patch.object(m, 'shutdown') as shutdown:
            with self.assertRaises(m.UnsafeWorkload):
                m.run_workload(args)
        shutdown.assert_called_once_with(DEVICE)
        self.assertFalse((m.ROOT / 'workload-current.json').exists())

    def test_already_booted_device_is_not_claimed_or_shutdown(self):
        args = argparse.Namespace(kind='simulator', device=DEVICE, trial=False, timeout=10, command=['qa'])
        with patch.object(m, 'metrics', return_value=HEALTHY), \
             patch.object(m, 'devices', return_value=[dict(udid=DEVICE, state='Booted', isAvailable=True)]), \
             patch.object(m, 'metal_coalescing', return_value=1), \
             patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(m, 'monitor') as monitor, patch.object(m, 'shutdown') as shutdown:
            with self.assertRaises(m.UnsafeWorkload):
                m.run_workload(args)
        monitor.assert_not_called()
        shutdown.assert_not_called()

    def test_existing_gui_is_not_taken_over_before_a_boot(self):
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'])
        with patch.object(m,'metal_coalescing',return_value=1), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(m,'devices') as devices:
            with self.assertRaisesRegex(m.UnsafeWorkload,'already open'):
                m.run_workload(args)
        devices.assert_not_called()

    def test_host_gui_requirement_is_checked_before_boot(self):
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'])
        with patch.object(m,'policy',return_value={'simulatorRequiresGUI':True}),patch.object(m,'metal_coalescing',return_value=1), \
             patch.object(m,'devices') as devices:
            with self.assertRaisesRegex(m.UnsafeWorkload,'requires --visible'):m.run_workload(args)
        devices.assert_not_called()

    def test_new_kernel_panic_requires_review_but_acknowledged_history_does_not(self):
        folder=self.root/'reports';folder.mkdir()
        (folder/'Kernel-old.panic').write_text('history')
        (folder/'.contents.panic').write_text('duplicate metadata')
        with patch.object(m,'PANIC_REPORTS',folder):
            m.check_panic_reports({'acknowledgedPanicReports':['Kernel-old.panic']})
            (folder/'Kernel-new.panic').write_text('new incident')
            with self.assertRaisesRegex(m.UnsafeWorkload,'Kernel-new.panic'):
                m.check_panic_reports({'acknowledgedPanicReports':['Kernel-old.panic']})

    def test_gpu_reset_requires_its_own_review_even_with_no_new_kernel_panic(self):
        folder=self.root/'reports';folder.mkdir()
        (folder/'Kernel-history.gpuRestart').write_text('GPU Reset')
        with patch.object(m,'PANIC_REPORTS',folder):
            settings={'acknowledgedPanicReports':[],'acknowledgedGpuResetReports':[]}
            with self.assertRaisesRegex(m.UnsafeWorkload,'GPU reset'):
                m.check_panic_reports(settings)
            settings['acknowledgedGpuResetReports']=['Kernel-history.gpuRestart']
            m.check_panic_reports(settings)

    def test_gpu_watch_ignores_history_but_cannot_be_bypassed_by_webcontent_diagnostics(self):
        folder=self.root/'reports';folder.mkdir()
        (folder/'history.gpuRestart').write_text('history')
        with patch.object(m,'PANIC_REPORTS',folder):
            watch=m.SimulatorFailureWatch(DEVICE,allow_webcontent_crash=True)
            self.assertIsNone(watch.failure())
            (folder/'new.gpuRestart').touch() # Detect immediately, even before report contents finish.
            self.assertIn('new.gpuRestart',watch.failure())
            self.assertIsNone(watch.web)

    def test_report_published_at_child_exit_prevents_false_success(self):
        class Finished:
            returncode=0
            def poll(self):return 0
        class Watch:
            def failure(self):return 'new GPU reset'
        with (self.root/'log').open('w') as log,patch.object(m.subprocess,'Popen',return_value=Finished()), \
             patch.object(m,'stop_owned_process') as stop:
            with self.assertRaisesRegex(m.UnsafeWorkload,'GPU reset'):
                m.monitor(['qa'],time.monotonic()+10,log,1,'command',crash_watch=Watch())
            stop.assert_called_once()

    def test_graphics_failure_at_shutdown_is_reported_after_owned_cleanup(self):
        class Watch:
            def failure(self):return 'GPU reset during shutdown'
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'])
        with patch.object(m,'metrics',return_value=HEALTHY), \
             patch.object(m,'devices',return_value=[dict(udid=DEVICE,state='Shutdown',isAvailable=True)]), \
             patch.object(m,'metal_coalescing',return_value=1), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)), \
             patch.object(m,'SimulatorFailureWatch',return_value=Watch()), \
             patch.object(m,'monitor'),patch.object(m,'shutdown') as shutdown:
            with self.assertRaisesRegex(m.UnsafeWorkload,'GPU reset during shutdown'):
                m.run_workload(args)
        shutdown.assert_called_once_with(DEVICE)
        self.assertFalse((m.ROOT/'workload-current.json').exists())

    def test_install_timeout_covers_observed_cold_registration(self):
        from simulator_environment import operation_timeout
        self.assertGreaterEqual(operation_timeout('install'),180)
        self.assertEqual(operation_timeout('launch'),45)

    def test_recorded_wasm_mode_is_simulator_only_and_has_explicit_controls(self):
        a=argparse.Namespace(kind='simulator')
        self.assertEqual(m.wasm_mode(a,{'simulatorWasmMode':'compat'}),'compat')
        a.native_wasm=True
        self.assertEqual(m.wasm_mode(a,{'simulatorWasmMode':'compat'}),'default')
        a=argparse.Namespace(kind='build')
        self.assertEqual(m.wasm_mode(a,{'simulatorWasmMode':'compat'}),'default')
        with self.assertRaises(m.UnsafeWorkload):m.wasm_mode(a,{'simulatorWasmMode':'unknown'})

    def test_intel_wasm_profile_keeps_jit_but_avoids_the_failed_interpreter_tier(self):
        flags=m.intel_wasm_overrides()
        for prefix in ('SIMCTL_CHILD_JSC_','SIMCTL_CHILD___XPC_JSC_'):
            self.assertEqual(flags[prefix+'useJIT'],'true')
            self.assertEqual(flags[prefix+'useWasmIPInt'],'false')
            self.assertEqual(flags[prefix+'useBBQJIT'],'true')
            self.assertEqual(flags[prefix+'useOMGJIT'],'false')
            self.assertEqual(flags[prefix+'useWasmFaultSignalHandler'],'false')

    def test_checked_wasm_flags_target_only_simctl_children_and_xpc(self):
        flags=m.checked_wasm_overrides()
        self.assertEqual(len(flags),8)
        self.assertTrue(all(k.startswith('SIMCTL_CHILD_') for k in flags))
        for prefix in ('SIMCTL_CHILD_JSC_','SIMCTL_CHILD___XPC_JSC_'):
            self.assertEqual(flags[prefix+'useWasmFastMemory'],'false')
            self.assertEqual(flags[prefix+'useWasmFaultSignalHandler'],'false')
            self.assertEqual(flags[prefix+'usePollingTraps'],'true')

    def test_direct_compiler_commands_are_capped_at_two_jobs(self):
        self.assertIn('2', m.bounded_jobs(['xcodebuild', '-jobs', '30', 'build']))
        self.assertEqual(m.bounded_jobs(['xcrun', 'swift', 'test'])[-2:], ['--jobs', '2'])

    def test_simulator_session_is_device_scoped_and_expiring(self):
        lease = dict(pid=os.getpid(), device=DEVICE, expiresAt=time.time()+10, trial=False)
        (self.root / 'workload-current.json').write_text(json.dumps(lease))
        with patch.object(m, 'metal_coalescing', return_value=1):
            m.assert_session(DEVICE)
            with self.assertRaises(m.UnsafeWorkload):
                m.assert_session('OTHER')
            lease['expiresAt'] = 0
            (self.root / 'workload-current.json').write_text(json.dumps(lease))
            with self.assertRaises(m.UnsafeWorkload):
                m.assert_session(DEVICE)


if __name__ == '__main__':
    unittest.main()
