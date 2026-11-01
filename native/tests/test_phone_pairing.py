import importlib.machinery
import importlib.util
import json
import fcntl
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

loader=importlib.machinery.SourceFileLoader('phone_pairing',str(Path(__file__).parents[1]/'scripts/phone-pairing'))
spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class PairingTests(unittest.TestCase):
    def setUp(self):
        self.real_host_network=m.host_network
        self.real_discovery_generation=m.discovery_generation
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/'state.json'
        (self.root/'ios-tools.local.json').write_text(json.dumps({'device':'a'*24}))
        self.patches=[patch.object(m,'STATE',self.state),patch.object(m,'ROOT',self.root),patch.object(m,'say'),
                      patch.object(m,'WORKLOAD_LOCK',self.root/'workload.lock'),patch.object(m,'tool_path',return_value='/fake/devicectl'),
                      patch.object(m,'host_network',return_value=None),
                      patch.object(m,'discovery_generation',return_value=None),
                      patch.object(m.os,'getloadavg',return_value=(1,1,1))]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def test_stale_connected_catalog_requires_real_request(self):
        def run(args,**kw):
            if 'list' in args:
                Path(args[args.index('--json-output')+1]).write_text(json.dumps({'result':{'devices':[{
                    'identifier':'device-id','hardwareProperties':{'udid':'a'*24},
                    'connectionProperties':{'tunnelState':'connected','potentialHostnames':[
                        'a'*24+'.coredevice.local','Visars-iPhone.coredevice.local']}}]}}))
                return subprocess.CompletedProcess(args,0,'','')
            self.assertIn('processes',args)
            return subprocess.CompletedProcess(args,1,'','unable to locate a device matching ecid_123')
        with patch.object(m.subprocess,'run',side_effect=run):
            visible,hosts,reason,recent=m.phone()
        self.assertFalse(visible);self.assertEqual(hosts,['Visars-iPhone.local'])
        self.assertIn('ecid_123',reason)

    def test_automatic_probe_yields_to_a_shared_mac_workload(self):
        with m.WORKLOAD_LOCK.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(m,'check') as check:
                self.assertEqual(m.locked_check(False),0)
            check.assert_not_called()

    def test_automatic_probe_yields_to_host_startup_pressure(self):
        with patch.object(m.os,'getloadavg',return_value=(7,7,7)),patch.object(m,'check') as check:
            self.assertEqual(m.locked_check(False),0)
        check.assert_not_called()

    def test_idle_monitor_releases_the_shared_lock_after_checking(self):
        with patch.object(m,'check',return_value=0) as check:
            self.assertEqual(m.locked_check(False),0)
        check.assert_called_once_with(False,False)
        with m.WORKLOAD_LOCK.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_ipv6_fallback_when_ipv4_address_is_stale(self):
        def run(args,**kw):
            if 'route' in args[0]:return subprocess.CompletedProcess(args,0,'gateway: 192.168.1.1\ninterface: en4','')
            if args[0].endswith('/ping'):return subprocess.CompletedProcess(args,1,'','Host is down')
            self.assertIn('en4',args)
            return subprocess.CompletedProcess(args,0,'PING6 fe80::mac%en4 --> fe80::phone%en4\n','')
        with patch.object(m.subprocess,'run',side_effect=run):
            self.assertIn('fe80::phone',m.reachable(['phone.local']))

    def test_missing_catalog_device_is_not_healthy(self):
        def run(args,**kw):
            if '--json-output' in args:
                Path(args[args.index('--json-output')+1]).write_text('{"result":{"devices":[]}}')
            return subprocess.CompletedProcess(args,1,'','not found')
        with patch.object(m.subprocess,'run',side_effect=run):self.assertFalse(m.phone()[0])

    def check(self,healthy=False,network='phone|192.168.1.54|wifi',now=False,force=False,recent=False):
        with patch.object(m,'phone',return_value=(healthy,['phone.local'],'stale tunnel',recent)), \
             patch.object(m,'reachable',return_value=network),patch.object(m,'restart',return_value=True) as restart:
            result=m.check(now,force)
            return result,restart.call_count

    def test_two_failures_recover_automatically(self):
        self.assertEqual(self.check(),(1,0));self.assertEqual(self.check(),(0,1))

    def test_wifi_change_bypasses_failed_retry_backoff(self):
        self.state.write_text(json.dumps({'network':'phone|192.168.1.45|wifi','fixed':m.time.time(),'failed':True}))
        self.assertEqual(self.check(),(0,1))

    def test_first_lan_reply_after_missing_phone_bypasses_backoff(self):
        self.state.write_text(json.dumps({'fixed':m.time.time(),'failed':True,'status':'unreachable'}))
        self.assertEqual(self.check(),(0,1))

    def test_same_network_retains_backoff(self):
        self.state.write_text(json.dumps({'network':'phone|192.168.1.54|wifi','fixed':m.time.time(),'failed':True,'misses':5}))
        self.assertEqual(self.check(),(1,0))

    def test_failed_probe_does_not_leave_an_old_healthy_label(self):
        self.state.write_text(json.dumps({'network':'phone|192.168.1.54|wifi','fixed':m.time.time(),
                                         'failed':True,'misses':5,'status':'healthy'}))
        self.assertEqual(self.check(),(1,0))
        self.assertEqual(json.loads(self.state.read_text())['status'],'unreachable')

    def test_failed_repair_does_not_report_healthy(self):
        self.state.write_text(json.dumps({'status':'healthy','seen':m.time.time()}))
        with patch.object(m,'phone',return_value=(False,[],'not found',True)), \
             patch.object(m,'reachable',return_value=None),patch.object(m,'restart',return_value=False):
            self.assertEqual(m.check(True),1)
        saved=json.loads(self.state.read_text())
        self.assertEqual(saved['status'],'unreachable')
        self.assertTrue(saved['failed'])

    def test_recovery_does_not_erase_restart_throttle(self):
        self.state.write_text(json.dumps({'fixed':123,'misses':2}))
        self.assertEqual(self.check(healthy=True),(0,0))
        self.assertEqual(json.loads(self.state.read_text())['fixed'],123)

    def test_installer_can_force_repair_of_stale_identity(self):
        self.assertEqual(self.check(healthy=True,now=True,force=True),(0,1))

    def test_recent_phone_disappears_without_ping_reply(self):
        self.assertEqual(self.check(network=None,recent=True),(1,0))
        self.assertEqual(self.check(network=None,recent=True),(0,1))

    def test_recent_phone_discovery_retries_obey_failed_backoff(self):
        self.state.write_text(json.dumps({'fixed':m.time.time(),'failed':True,'misses':2}))
        self.assertEqual(self.check(network=None,recent=True),(1,0))

    def test_network_change_resets_discovery_even_when_ping_works(self):
        self.state.write_text(json.dumps({'network':'phone|192.168.1.54|wifi','failed':True,'fixed':m.time.time()}))
        with patch.object(m,'phone',return_value=(False,['phone.local'],'stale tunnel',True)), \
             patch.object(m,'reachable',return_value='phone|192.168.1.45|wifi'), \
             patch.object(m,'restart',return_value=True) as restart:
            self.assertEqual(m.check(False),0)
            restart.assert_called_once_with(discovery=True,allow_services=False)

    def test_host_route_change_recovers_when_old_bonjour_name_is_silent(self):
        old={'interfaces':['en4|192.168.7.199|0xffffff00'],'route':'interface: en4'}
        new={'interfaces':old['interfaces']+['en0|192.168.7.198|0xffffff00'],'route':'interface: en0'}
        self.state.write_text(json.dumps({'hostNetwork':old,'fixed':m.time.time(),
                                         'seen':1,'failed':True,'status':'unreachable'}))
        with patch.object(m,'host_network',return_value=new), \
             patch.object(m,'phone',return_value=(False,['old-phone.local'],'not found',False)), \
             patch.object(m,'reachable',return_value=None),patch.object(m,'restart',return_value=True) as restart:
            self.assertEqual(m.check(False),0)
        restart.assert_called_once_with(discovery=True,allow_services=False)
        self.assertEqual(json.loads(self.state.read_text())['hostNetwork'],new)

    def test_missing_topology_sample_does_not_replace_previous_or_bypass_backoff(self):
        old={'interfaces':['en4|192.168.7.199|0xffffff00'],'route':'interface: en4'}
        self.state.write_text(json.dumps({'hostNetwork':old,'fixed':m.time.time(),
                                         'seen':1,'failed':True,'status':'unreachable'}))
        self.assertEqual(self.check(network=None),(1,0))
        self.assertEqual(json.loads(self.state.read_text())['hostNetwork'],old)

    def test_returning_authenticated_phone_bypasses_old_retry_delay_once(self):
        network='phone|192.168.1.54|wifi'
        generation=[123,'192.168.1.54','en4',64000]
        self.state.write_text(json.dumps({'network':network,'fixed':m.time.time(),'failed':True}))
        with patch.object(m,'discovery_generation',return_value=generation):
            self.assertEqual(self.check(network=network),(0,1))
        saved=json.loads(self.state.read_text())
        self.assertEqual(saved['discoveryGeneration'],generation)
        # Ongoing verification of the same endpoint must not continually reset
        # the throttle if native service repair itself continues to fail.
        saved.update(fixed=m.time.time(),failed=True)
        self.state.write_text(json.dumps(saved))
        with patch.object(m,'discovery_generation',return_value=generation):
            self.assertEqual(self.check(network=network),(1,0))

    def test_only_fresh_registered_discovery_can_bypass_retry_delay(self):
        path=self.root/('discovery-'+'a'*24+'.json')
        good={'registered':True,'registeredAt':123,'verified':m.time.time(),
              'address':'192.168.7.45','interface':'en4','port':64000}
        path.write_text(json.dumps(good))
        self.assertEqual(self.real_discovery_generation(),[123,'192.168.7.45','en4',64000])
        for bad in [dict(good,registered=False),dict(good,verified=m.time.time()-61),
                    dict(good,registeredAt=None),dict(good,verified='bad'),{},[]]:
            path.write_text(json.dumps(bad));self.assertIsNone(self.real_discovery_generation())

    def test_topology_does_not_depend_on_successful_phone_lookup(self):
        route='gateway: 192.168.7.1\ninterface: en4\n'
        links='''en0: flags=8863<UP,RUNNING>
    inet 192.168.7.198 netmask 0xffffff00
    status: inactive
en4: flags=8863<UP,RUNNING>
    inet 192.168.7.199 netmask 0xffffff00
    status: active
utun0: flags=8051<UP,RUNNING>
    inet 100.64.0.1 netmask 0xffffffff
    status: active
'''
        # Exercise the real function hidden by setUp's general network mock.
        with patch.object(m.subprocess,'run',side_effect=[
                subprocess.CompletedProcess([],0,route),subprocess.CompletedProcess([],0,links)]):
            self.assertEqual(self.real_host_network(),{'interfaces':['en4|192.168.7.199|0xffffff00'],
                                                       'route':'gateway: 192.168.7.1|interface: en4'})

    def test_basic_repair_escalates_before_entering_backoff(self):
        self.state.write_text(json.dumps({'network':'phone|192.168.1.45|wifi','misses':1}))
        with patch.object(m,'phone',return_value=(False,['phone.local'],'stale tunnel',True)), \
             patch.object(m,'reachable',return_value='phone|192.168.1.45|wifi'), \
             patch.object(m,'restart',side_effect=[False,True]) as restart:
            self.assertEqual(m.check(False),0)
            self.assertEqual([c.kwargs for c in restart.call_args_list],
                             [{'discovery':False,'allow_services':False},{'discovery':True,'allow_services':False}])

    def test_cold_cache_starts_unicast_without_blind_service_restarts(self):
        with patch.object(m,'phone',return_value=(False,[],'not found',False)), \
             patch.object(m,'reachable',return_value=None), \
             patch.object(m,'bootstrap_discovery',return_value=False) as discovery, \
             patch.object(m.subprocess,'run') as services:
            self.assertEqual(m.check(False),1)
            discovery.assert_not_called()
            self.assertEqual(m.check(False),1)
            discovery.assert_called_once()
            # An away or unreachable phone must not cause global daemon churn.
            services.assert_not_called()
            self.assertEqual(m.check(False),1)
            discovery.assert_called_once()

    def test_explicit_repair_refreshes_discovery_despite_stale_bonjour(self):
        self.state.write_text(json.dumps({'seen':1,'fixed':m.time.time(),'failed':True,'status':'unreachable'}))
        with patch.object(m,'phone',return_value=(False,['phone.local'],'stale discovery',False)), \
             patch.object(m,'reachable',return_value=None),patch.object(m,'restart',return_value=True) as restart:
            self.assertEqual(m.check(True,True),0)
            restart.assert_called_once_with(discovery=True,allow_services=True)

    def test_installer_check_repairs_without_a_ping_reply(self):
        self.assertEqual(self.check(network=None,now=True),(0,1))

    def test_known_phone_is_rediscovered_after_recent_window_expires(self):
        self.state.write_text(json.dumps({'seen':1,'fixed':m.time.time()-m.WAIT-1,'failed':True,'status':'unreachable'}))
        self.assertEqual(self.check(network=None),(1,0))
        self.assertEqual(self.check(network=None),(0,1))

    def test_stale_discovery_retries_keep_the_ten_minute_backoff(self):
        self.state.write_text(json.dumps({'seen':1,'fixed':m.time.time(),'failed':True,'status':'unreachable'}))
        self.assertEqual(self.check(network=None),(1,0))
        self.assertEqual(self.check(network=None),(1,0))

    def test_unicast_recovery_avoids_restarting_apple_services(self):
        with patch.object(m,'bootstrap_discovery',return_value=True), \
             patch.object(m,'phone',return_value=(True,[],'',True)), \
             patch.object(m.subprocess,'run') as services:
            self.assertTrue(m.restart(discovery=True))
            services.assert_not_called()

    def test_automatic_repair_can_refresh_services_after_authenticated_discovery(self):
        with patch.object(m,'bootstrap_discovery',return_value=True), \
             patch.object(m,'phone',side_effect=[(False,[],'stale native tunnel',False)]*3+[(True,[],'',True)]), \
             patch.object(m.time,'sleep'), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'')) as services:
            self.assertTrue(m.restart(discovery=True,allow_services=False))
        commands=[call.args[0] for call in services.call_args_list]
        self.assertIn(['/usr/bin/sudo','-n','/bin/launchctl','kill','SIGHUP','system/com.apple.mDNSResponder'],commands)
        for target in ['user/%s/com.apple.CoreDevice.remotepairingd' % m.os.getuid(),
                       'user/%s/com.apple.CoreDevice.CoreDeviceService' % m.os.getuid(),
                       'system/com.apple.remoted','system/com.apple.usbmuxd']:
            self.assertIn(['/usr/bin/sudo','-n','/bin/launchctl','kickstart','-k',target],commands)
        self.assertFalse(any('pgrep' in arg or 'killall' in arg for command in commands for arg in command))

    def test_published_endpoint_alone_is_not_a_healthy_connection(self):
        with patch.object(m,'bootstrap_discovery',return_value=True), \
             patch.object(m,'phone',return_value=(False,[],'not found',False)), \
             patch.object(m.time,'sleep'), patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'')) as services:
            self.assertFalse(m.restart(discovery=True))
            self.assertTrue(services.called)

    def test_reloaded_mdns_job_is_selected_by_exact_identity(self):
        def run(args,**kwargs):
            missing = 'print' in args and args[-1] == 'system/com.apple.mDNSResponder'
            return subprocess.CompletedProcess(args,1 if missing else 0,'','')
        with patch.object(m,'bootstrap_discovery',return_value=True), \
             patch.object(m,'phone',side_effect=[(False,[],'stale',False)]*3+[(True,[],'',True)]), \
             patch.object(m.time,'sleep'),patch.object(m.subprocess,'run',side_effect=run) as services:
            self.assertTrue(m.restart(discovery=True,allow_services=False))
        signals=[call.args[0] for call in services.call_args_list if 'SIGHUP' in call.args[0]]
        self.assertEqual(signals,[['/usr/bin/sudo','-n','/bin/launchctl','kill','SIGHUP','system/com.apple.mDNSResponder.reloaded']])

if __name__=='__main__':unittest.main()
