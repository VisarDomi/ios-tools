"""Safety regressions with fake Mac boundaries; no simulator or physical phone is booted."""
import argparse
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
