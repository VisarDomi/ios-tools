"""Safety regressions with fake Mac boundaries; no simulator or physical phone is booted."""
import argparse
import contextlib
import ctypes
import io
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
        for name, value in [('ROOT', self.root), ('LOCK', self.root / 'signing.lock'), ('POLICY', self.root / 'policy.json'),
                            ('SPEECH_MODEL_CACHE', self.root / 'speech'), ('DERIVED_DATA', self.root / 'DerivedData'),
                            ('PROFILE_STATE', self.root / 'profile'), ('SIM_LAUNCHD_STATE', self.root / 'launchd')]:
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

    def test_gui_quit_acknowledgment_is_not_exit_proof(self):
        owner=dict(pid=123,identity='owned simulator')
        with patch.object(m,'process_identity',side_effect=['owned simulator',None]), \
             patch.object(m.subprocess,'run'),patch.object(m.os,'kill') as kill:
            m.close_owned_simulator_gui(owner)
        kill.assert_not_called()

    def test_gui_cleanup_terminates_only_the_unchanged_owned_process(self):
        owner=dict(pid=123,identity='owned simulator')
        with patch.object(m,'process_identity',side_effect=['owned simulator']*12+[None]), \
             patch.object(m.subprocess,'run'),patch.object(m.time,'sleep'),patch.object(m.os,'kill') as kill:
            m.close_owned_simulator_gui(owner)
        kill.assert_called_once_with(123,m.signal.SIGTERM)

    def test_gui_cleanup_refuses_a_reused_pid_and_keeps_unknown_ownership_explicit(self):
        with patch.object(m,'process_identity',return_value='someone else'),patch.object(m.os,'kill') as kill:
            with self.assertRaisesRegex(m.UnsafeWorkload,'identity changed'):
                m.close_owned_simulator_gui(dict(pid=123,identity='owned simulator'))
        kill.assert_not_called()
        with self.assertRaisesRegex(m.UnsafeWorkload,'ownership was not established'):m.close_owned_simulator_gui(None)

    def test_gui_cleanup_failure_retains_recovery_lease(self):
        args=argparse.Namespace(kind='simulator',device=DEVICE,trial=False,timeout=10,command=['qa'],visible=True)
        with patch.object(m,'metrics',return_value=HEALTHY), \
             patch.object(m,'devices',return_value=[dict(udid=DEVICE,state='Shutdown',isAvailable=True)]), \
             patch.object(m,'metal_coalescing',return_value=1), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],1)), \
             patch.object(m,'monitor'),patch.object(m,'shutdown'), \
             patch.object(m,'simulator_gui_owner',return_value=dict(pid=123,identity='owned simulator')), \
             patch.object(m,'close_owned_simulator_gui',side_effect=m.UnsafeWorkload('GUI stuck')):
            with self.assertRaisesRegex(m.UnsafeWorkload,'GUI stuck'):m.run_workload(args)
        lease=json.loads((m.ROOT/'workload-current.json').read_text())
        self.assertEqual(lease['cleanupFailed'],'GUI stuck');self.assertEqual(lease['expiresAt'],0)

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


class RegenerableCacheTests(unittest.TestCase):
    def test_prunes_old_speech_models_and_idle_derived_data_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speech, derived = root / 'speech', root / 'DerivedData'
            speech.mkdir(); derived.mkdir()
            now = time.time()
            for i, (name, size) in enumerate([('new.bnnsir', 300), ('mid.bnnsir', 200), ('old.bnnsir', 300), ('other.txt', 900)]):
                f = speech / name; f.write_bytes(b'x' * size); os.utime(f, (now - i * 100, now - i * 100))
            partial = speech / 'old.bnnsir.123'; partial.write_bytes(b'z' * 40); os.utime(partial, (now - 2 * 86400, now - 2 * 86400))
            fresh = speech / 'new.bnnsir.456'; fresh.write_bytes(b'z' * 40)
            idle = derived / 'App-old'; (idle / 'Build').mkdir(parents=True); (idle / 'Build/a.o').write_bytes(b'y' * 50)
            busy = derived / 'App-new'; (busy / 'Build').mkdir(parents=True)
            cache = derived / 'ModuleCache.noindex'; cache.mkdir()
            for d in (idle, idle / 'Build', cache):
                os.utime(d, (now - 10 * 86400, now - 10 * 86400))
            with patch.object(m, 'SPEECH_MODEL_CACHE', speech), patch.object(m, 'SPEECH_MODEL_BUDGET', 500), \
                 patch.object(m, 'DERIVED_DATA', derived):
                removed = m.prune_regenerable_caches(now)
            self.assertEqual(sorted(x.name for x in speech.iterdir()), ['mid.bnnsir', 'new.bnnsir', 'new.bnnsir.456', 'other.txt'])
            self.assertEqual(sorted(x.name for x in derived.iterdir()), ['App-new', 'ModuleCache.noindex'])
            self.assertEqual(removed, 390)


IOS_RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-26-3'


class SimulatorProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('PROFILE_STATE', self.root / 'profile'), ('SIM_LAUNCHD_STATE', self.root / 'launchd')]:
            p = patch.object(m, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.overrides = self.root / 'launchd' / ('com.apple.CoreSimulator.SimDevice.' + DEVICE) / 'disabled.plist'

    def write_overrides(self, values):
        self.overrides.parent.mkdir(parents=True, exist_ok=True)
        self.overrides.write_bytes(m.plistlib.dumps(values))

    def read_overrides(self):
        return m.plistlib.loads(self.overrides.read_bytes())

    def test_profiles_keep_only_the_groups_an_app_needs(self):
        profiles = json.loads(m.PROFILES.read_text())['platforms']['iOS']
        lean, name = m.simulator_profile(IOS_RUNTIME)
        self.assertEqual((lean, name), (profiles['lean'], 'lean'))
        self.assertEqual(len(lean), len(set(lean)))
        for need, jobs in profiles['needs'].items():
            with self.subTest(need=need):
                self.assertTrue(set(jobs) <= set(lean), 'a need may only keep jobs the lean profile disables')
        media, name = m.simulator_profile(IOS_RUNTIME, app='video-platform')
        self.assertEqual(name, 'lean +media')
        self.assertNotIn('com.apple.mediaremoted', media)
        self.assertIn('com.apple.assistantd', media)
        watch, name = m.simulator_profile(IOS_RUNTIME, ['push'], app='t3-watch')
        self.assertEqual(name, 'lean +push +watch +widgets')
        self.assertFalse({'com.apple.apsd', 'com.apple.nanotimekitcompaniond', 'com.apple.chronod'} & set(watch))
        self.assertEqual(m.simulator_profile(IOS_RUNTIME, ['siri'], full=True), ([], 'full'))
        self.assertEqual(m.simulator_profile('com.apple.CoreSimulator.SimRuntime.watchOS-26-2'), ([], 'full (no profile for this runtime)'))
        with self.assertRaisesRegex(m.UnsafeWorkload, 'Unknown simulator needs: bluetooth'):
            m.simulator_profile(IOS_RUNTIME, ['bluetooth'])
        with self.assertRaisesRegex(m.UnsafeWorkload, 'Unknown app'):
            m.simulator_profile(IOS_RUNTIME, app='nope')

    def test_the_app_comes_from_the_command_path_when_not_given(self):
        self.assertEqual(m.command_app(['/usr/bin/python3', '/Users/v/Developer/video-platform/apps/ios/scripts/check-zoom.py', '--device', DEVICE]), 'video-platform')
        self.assertEqual(m.command_app(['python3', '/Users/v/Developer/guidance-virtual/apps/ios/scripts/check.py']), 'guidance')
        self.assertEqual(m.command_app(['python3', '/Users/v/Developer/gallery-reader/x.py']), 'gallery-reader')
        self.assertIsNone(m.command_app(['/usr/bin/python3', '/tmp/simcheck.py', DEVICE]))

    def test_a_guest_booted_during_admission_is_refused_not_shut_down(self):
        args = argparse.Namespace(kind='simulator', device=DEVICE, trial=False, timeout=10, command=['qa'])
        states = iter([[dict(udid=DEVICE, state='Shutdown', isAvailable=True, runtime=IOS_RUNTIME)],
                       [dict(udid=DEVICE, state='Booted', isAvailable=True, runtime=IOS_RUNTIME)]])
        with patch.object(m, 'ROOT', self.root), patch.object(m, 'LOCK', self.root / 'signing.lock'), \
             patch.object(m, 'POLICY', self.root / 'policy.json'), patch.object(m, 'tool_path', return_value='/fake/simctl'), \
             patch.object(m, 'metrics', return_value=HEALTHY), patch.object(m, 'devices', side_effect=lambda: next(states)), \
             patch.object(m, 'metal_coalescing', return_value=1), \
             patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(m, 'apply_simulator_profile') as apply, patch.object(m, 'monitor') as monitor, \
             patch.object(m, 'shutdown') as shutdown, patch.object(m, 'prune_regenerable_caches'):
            with self.assertRaisesRegex(m.UnsafeWorkload, 'not shut down'):
                m.run_workload(args)
        apply.assert_not_called(); monitor.assert_not_called(); shutdown.assert_not_called()
        self.assertFalse((self.root / 'workload-current.json').exists())

    def test_overrides_round_trip_to_the_exact_original_state(self):
        original = {'com.apple.nanoappregistryd': False, 'com.apple.healthd': True, 'com.apple.pairedsyncd': False}
        self.write_overrides(original)
        m.apply_simulator_profile(DEVICE, ['com.apple.healthd', 'com.apple.homed', 'com.apple.nanoappregistryd'])
        self.assertEqual(self.read_overrides(), {'com.apple.nanoappregistryd': True, 'com.apple.healthd': True,
                                                 'com.apple.pairedsyncd': False, 'com.apple.homed': True})
        m.apply_simulator_profile(DEVICE, ['com.apple.homed'])
        self.assertEqual(self.read_overrides(), dict(original, **{'com.apple.homed': True}))
        m.apply_simulator_profile(DEVICE, [])
        self.assertEqual(self.read_overrides(), original)
        m.apply_simulator_profile(DEVICE, [])
        self.assertEqual(self.read_overrides(), original)

    def test_a_change_made_by_someone_else_is_adopted_not_reverted(self):
        self.write_overrides({})
        m.apply_simulator_profile(DEVICE, ['com.apple.wcd'])
        values = self.read_overrides(); values['com.apple.wcd'] = False  # e.g. pairing a watch enabled it
        self.write_overrides(values)
        m.apply_simulator_profile(DEVICE, [])
        self.assertEqual(self.read_overrides(), {'com.apple.wcd': False})

    def test_an_interrupted_apply_still_restores(self):
        self.write_overrides({'com.apple.wcd': False})
        m.apply_simulator_profile(DEVICE, ['com.apple.wcd', 'com.apple.homed'])
        sidecar = json.loads((self.root / 'profile' / (DEVICE + '.json')).read_text())
        self.assertEqual(sidecar, {'com.apple.homed': None, 'com.apple.wcd': False})
        # Power lost after the sidecar of a second apply but before its overrides: the next apply still restores.
        m.atomic_write(self.root / 'profile' / (DEVICE + '.json'), json.dumps(dict(sidecar, **{'com.apple.apsd': None})).encode())
        m.apply_simulator_profile(DEVICE, [])
        self.assertEqual(self.read_overrides(), {'com.apple.wcd': False})

    def test_full_profile_on_a_never_profiled_guest_writes_nothing(self):
        m.apply_simulator_profile(DEVICE, [])
        self.assertFalse(self.overrides.exists())
        self.assertFalse((self.root / 'profile').exists())

    def test_a_session_applies_the_profile_to_the_shut_down_guest_before_boot(self):
        args = argparse.Namespace(kind='simulator', device=DEVICE, trial=False, timeout=10, command=['qa'], app='video-platform')
        steps = []
        with patch.object(m, 'ROOT', self.root), patch.object(m, 'LOCK', self.root / 'signing.lock'), \
             patch.object(m, 'POLICY', self.root / 'policy.json'), patch.object(m, 'tool_path', return_value='/fake/simctl'), \
             patch.object(m, 'metrics', return_value=HEALTHY), \
             patch.object(m, 'devices', return_value=[dict(udid=DEVICE, state='Shutdown', isAvailable=True, runtime=IOS_RUNTIME)]), \
             patch.object(m, 'metal_coalescing', return_value=1), \
             patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(m, 'apply_simulator_profile', side_effect=lambda *a: steps.append(('apply',) + a)), \
             patch.object(m, 'monitor', side_effect=lambda command, *a, **k: steps.append((command[1 if len(command) > 1 else 0], json.loads((self.root / 'workload-current.json').read_text())))), \
             patch.object(m, 'shutdown'), patch.object(m, 'prune_regenerable_caches'):
            m.run_workload(args)
        self.assertEqual([step[0] for step in steps], ['apply', 'boot', 'bootstatus', 'qa'])
        disabled = steps[0][2]
        self.assertNotIn('com.apple.mediaremoted', disabled)
        self.assertEqual(steps[1][1]['profile'], 'lean +media (app video-platform)')
        self.assertEqual(steps[1][1]['disabledJobs'], disabled)
        self.assertNotIn('--disabledJob', ' '.join(map(str, steps)))


OTHER = '87654321-4321-4321-4321-CBA987654321'
REAL_MONITOR = m.monitor
BOOT = dict(pid=4242, identity='Wed Nov 11 16:00:00 2026 launchd_sim /Users/v/Library/Developer/CoreSimulator/Devices/%s/data/var/run/launchd_bootstrap.plist' % DEVICE)


class WarmHoldTests(unittest.TestCase):
    """A guarded session leaves its guest booted and idle for an hour; the next session reuses it."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('ROOT', self.root), ('LOCK', self.root / 'signing.lock'), ('POLICY', self.root / 'policy.json'),
                            ('WARM', self.root / 'simulator-warm.json'), ('PANIC_REPORTS', self.root / 'reports'),
                            ('PROFILE_STATE', self.root / 'profile'), ('SIM_LAUNCHD_STATE', self.root / 'launchd')]:
            p = patch.object(m, name, value)
            p.start()
            self.addCleanup(p.stop)
        (self.root / 'reports').mkdir()
        self.state = {DEVICE: 'Shutdown', OTHER: 'Shutdown'}
        self.running = []
        self.calls = []
        self.steps = []
        self.boot = dict(BOOT)
        for name, kwargs in [('tool_path', dict(return_value='/fake/simctl')), ('metal_coalescing', dict(return_value=1)),
                             ('metrics', dict(return_value=HEALTHY)), ('prune_regenerable_caches', {}),
                             ('devices', dict(side_effect=lambda: [dict(udid=u, state=s, isAvailable=True, runtime=IOS_RUNTIME) for u, s in self.state.items()])),
                             ('guest_boot_identity', dict(side_effect=lambda device: self.boot if self.state.get(device) == 'Booted' else None)),
                             ('shutdown', dict(side_effect=self.fake_shutdown)), ('start_warm_expiry', {}),
                             ('simulator_gui_owner', dict(return_value=dict(pid=99, identity='owned simulator'))),
                             ('close_owned_simulator_gui', dict(side_effect=lambda owner: self.steps.append('close-gui'))),
                             ('apply_simulator_profile', dict(side_effect=lambda device, jobs: self.steps.append('apply'))),
                             ('monitor', dict(side_effect=self.fake_monitor))]:
            p = patch.object(m, name, **kwargs)
            setattr(self, name, p.start())
            self.addCleanup(p.stop)
        p = patch.object(m.subprocess, 'run', side_effect=self.fake_run)
        p.start()
        self.addCleanup(p.stop)
        self.command_result = None

    def fake_shutdown(self, device):
        self.steps.append('shutdown ' + device)
        self.state[device] = 'Shutdown'

    def fake_monitor(self, command, *args, **kwargs):
        name = command[1] if command[0] == '/fake/simctl' else command[0]
        self.steps.append(name)
        if name == 'boot':
            self.state[command[2]] = 'Booted'
        if name == 'qa':
            self.running.append('com.example.qa')
            if self.command_result:
                raise self.command_result

    def fake_run(self, argv, *args, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:2] == ['/usr/bin/pgrep', '-x']:
            return subprocess.CompletedProcess(argv, 1, '', '')
        if argv[1:2] == ['spawn']:
            listing = '-\t0\tUIKitApplication:com.apple.Preferences[0x1][rb-legacy]\n' + ''.join(
                '123\t0\tUIKitApplication:%s[0x2][rb-legacy]\n' % bundle for bundle in self.running)
            return subprocess.CompletedProcess(argv, 0, listing, '')
        if argv[1:2] == ['terminate']:
            self.running.remove(argv[3])
        return subprocess.CompletedProcess(argv, 0, '', '')

    def session(self, device=DEVICE, **options):
        args = argparse.Namespace(kind='simulator', device=device, trial=False, timeout=60, command=['qa'], visible=True, **options)
        self.steps.clear()
        m.run_workload(args)
        return list(self.steps)

    def hold(self):
        return json.loads((self.root / 'simulator-warm.json').read_text())

    def test_a_finished_session_leaves_the_guest_idle_and_warm_for_an_hour(self):
        self.assertEqual(self.session(), ['apply', 'boot', 'bootstatus', 'qa', 'close-gui'])
        self.assertEqual(self.state[DEVICE], 'Booted')
        hold = self.hold()
        self.assertEqual((hold['device'], hold['boot'], hold['profile']), (DEVICE, BOOT, 'lean'))
        self.assertAlmostEqual(hold['until'] - hold['lastUsed'], 3600)
        self.assertEqual(self.running, [], 'the test app is stopped; Apple apps are left alone')
        self.assertIn(['/fake/simctl', 'terminate', DEVICE, 'com.example.qa'], self.calls)
        self.start_warm_expiry.assert_called_once_with(hold['token'])
        self.assertFalse((self.root / 'workload-current.json').exists())
        opened = next(c for c in self.calls if c[0] == '/usr/bin/open')
        self.assertEqual(opened[-2:], ['-DetachOnAppQuit', 'YES'], 'only the owned GUI leaves its guest running on quit')

    def test_the_next_session_reuses_the_warm_guest_without_a_boot(self):
        self.session()
        token = self.hold()['token']
        steps = self.session()
        self.assertEqual(steps, ['bootstatus', 'qa', 'close-gui'])
        self.assertNotEqual(self.hold()['token'], token, 'a new hour starts; the old timer stops on the token change')

    def test_a_failing_check_still_leaves_a_healthy_guest_warm(self):
        self.command_result = subprocess.CalledProcessError(1, ['qa'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.session()
        self.assertEqual(self.hold()['device'], DEVICE)

    def test_a_stopped_session_shuts_the_guest_down(self):
        for failure in (m.UnsafeWorkload('workload deadline expired'), KeyboardInterrupt()):
            with self.subTest(failure=failure):
                self.command_result = failure
                with self.assertRaises(type(failure)):
                    self.session()
                self.assertEqual(self.state[DEVICE], 'Shutdown')
                self.assertFalse((self.root / 'simulator-warm.json').exists())

    def test_a_new_graphics_report_during_the_session_shuts_the_guest_down(self):
        def crash(*args, **kwargs):
            self.steps.append('qa')
            (self.root / 'reports' / 'x.gpuRestart').write_text('')
        self.monitor.side_effect = lambda command, *a, **k: crash() if command == ['qa'] else self.fake_monitor(command)
        with self.assertRaisesRegex(m.UnsafeWorkload, 'graphics failure'):
            self.session()
        self.assertEqual(self.state[DEVICE], 'Shutdown')
        self.assertFalse((self.root / 'simulator-warm.json').exists())

    def test_a_cold_request_another_device_or_missing_services_end_the_hold_first(self):
        for options, device, expected in [(dict(cold=True), DEVICE, 'shutdown ' + DEVICE), (dict(), OTHER, 'shutdown ' + DEVICE),
                                          (dict(app='video-platform'), DEVICE, 'shutdown ' + DEVICE)]:
            with self.subTest(options=options, device=device):
                for udid in self.state: self.state[udid] = 'Shutdown'
                (self.root / 'simulator-warm.json').unlink(missing_ok=True)
                self.session()
                steps = self.session(device, **options)
                self.assertEqual(steps[:3], [expected, 'apply', 'boot'])
                self.assertEqual(self.hold()['device'], device)
                self.assertEqual([u for u, s in self.state.items() if s == 'Booted'], [device], 'one guest at a time')

    def test_a_guest_with_more_services_satisfies_a_leaner_check(self):
        self.session(app='video-platform')
        self.assertEqual(self.session(), ['bootstatus', 'qa', 'close-gui'])
        self.assertEqual(self.hold()['profile'], 'lean +media (app video-platform)')

    def test_builds_and_status_do_not_count_the_held_guest_as_busy(self):
        self.session()
        known = m.wait_for_idle(0, kind='build', warm=m.held_warm(None))
        self.assertIn(DEVICE, [x['udid'] for x in known])
        with self.assertRaisesRegex(m.UnsafeWorkload, 'already booted'):
            m.wait_for_idle(0, kind='build')

    def test_memory_pressure_ends_the_hold_before_a_build_starts(self):
        self.session()
        self.metrics.return_value = dict(HEALTHY, pressure=2)
        with self.assertRaisesRegex(m.UnsafeWorkload, 'memory pressure'), patch.object(m.time, 'sleep'):
            m.wait_for_idle(0, kind='build', warm=m.held_warm(None))
        self.assertEqual(self.state[DEVICE], 'Shutdown')

    def test_a_build_under_pressure_sheds_the_warm_guest_and_continues(self):
        self.session()
        self.monitor.side_effect = None
        samples = iter([dict(HEALTHY, pressure=2)] + [HEALTHY] * 50)
        self.metrics.side_effect = lambda: next(samples)
        with tempfile.TemporaryFile('w+') as log:
            REAL_MONITOR([sys.executable, '-c', 'import time; time.sleep(4.5)'], time.monotonic() + 20, log, 1, 'command', warm=m.held_warm(None))
        self.assertEqual(self.state[DEVICE], 'Shutdown')
        self.assertFalse((self.root / 'simulator-warm.json').exists())

    def test_an_expired_hold_is_ended_by_the_next_workload(self):
        self.session()
        hold = self.hold(); hold['until'] = time.time() - 1
        (self.root / 'simulator-warm.json').write_text(json.dumps(hold))
        steps = self.session()
        self.assertEqual(steps[:3], ['shutdown ' + DEVICE, 'apply', 'boot'])

    def test_a_stale_record_after_a_reboot_or_someone_elses_boot_is_dropped_not_acted_on(self):
        self.session()
        self.boot = dict(BOOT, pid=5151)  # the guest was booted again by someone else
        self.assertIsNone(m.held_warm(None))
        self.assertFalse((self.root / 'simulator-warm.json').exists())
        with self.assertRaisesRegex(m.UnsafeWorkload, 'already booted'):
            self.session()
        self.assertEqual(self.state[DEVICE], 'Booted')
        self.assertNotIn('shutdown ' + DEVICE, self.steps)
        self.state[DEVICE] = 'Shutdown'  # a reboot: the record outlives its guest
        self.boot = dict(BOOT)
        self.session()
        self.state[DEVICE] = 'Shutdown'
        self.assertIsNone(m.held_warm(None))

    def test_a_guest_whose_apps_cannot_be_stopped_is_shut_down(self):
        real = self.fake_run
        self.fake_run = None
        def stubborn(argv, *a, **k):
            if list(argv)[1:2] == ['terminate']: return subprocess.CompletedProcess(argv, 1, '', '')
            return real(argv, *a, **k)
        with patch.object(m.subprocess, 'run', side_effect=stubborn):
            self.session()
        self.assertEqual(self.state[DEVICE], 'Shutdown')
        self.assertFalse((self.root / 'simulator-warm.json').exists())

    def test_policy_can_turn_the_hold_off(self):
        (self.root / 'policy.json').write_text(json.dumps(dict(simulatorWarmSeconds=0)))
        self.session()
        self.assertEqual(self.state[DEVICE], 'Shutdown')
        self.assertFalse((self.root / 'simulator-warm.json').exists())

    def test_the_timer_ends_the_hold_at_expiry_or_on_a_graphics_report_and_stops_on_takeover(self):
        self.session()
        token = self.hold()['token']
        with patch.object(m, 'memory_pressure', return_value=1), patch.object(m.time, 'sleep'):
            self.assertIsNone(m.warm_expire('someone else'))
            self.assertEqual(self.state[DEVICE], 'Booted')
            (self.root / 'reports' / 'y.gpuRestart').write_text('')
            self.assertEqual(m.warm_expire(token), 'new Mac graphics failure report')
        self.assertEqual(self.state[DEVICE], 'Shutdown')
        (self.root / 'reports' / 'y.gpuRestart').unlink()
        self.session()
        hold = self.hold(); hold['until'] = time.time() - 1; hold['lastUsed'] = hold['until'] - 3600
        (self.root / 'simulator-warm.json').write_text(json.dumps(hold))
        with patch.object(m, 'memory_pressure', return_value=1), patch.object(m.time, 'sleep'):
            self.assertEqual(m.warm_expire(hold['token']), 'idle for 60 min')
        self.assertEqual(self.state[DEVICE], 'Shutdown')


    def test_the_timer_sheds_the_guest_after_two_strained_minutes(self):
        self.session()
        with patch.object(m, 'memory_pressure', side_effect=[2, 1, 2, 2]), patch.object(m.time, 'sleep') as sleep:
            self.assertEqual(m.warm_expire(self.hold()['token']), 'memory pressure')
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(self.state[DEVICE], 'Shutdown')

    def test_status_reports_the_held_guest_apart_from_busy_guests(self):
        self.session()
        out = io.StringIO()
        with patch.object(sys, 'argv', ['mac-workload', 'status']), patch.object(m.platform, 'system', return_value='Darwin'), \
             patch.object(m, 'policy', return_value={}), contextlib.redirect_stdout(out):
            m.main()
        status = json.loads(out.getvalue())
        self.assertEqual(status['booted'], [])
        self.assertEqual(status['warm']['device'], DEVICE)
        self.assertTrue((self.root / 'simulator-warm.json').exists(), 'status never changes the hold')


if __name__ == '__main__':
    unittest.main()
