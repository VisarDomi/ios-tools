import importlib.machinery
import importlib.util
import json
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
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/'state.json'
        (self.root/'ios-tools.local.json').write_text(json.dumps({'device':'a'*24}))
        self.patches=[patch.object(m,'STATE',self.state),patch.object(m,'ROOT',self.root),patch.object(m,'say')]
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

    def test_same_network_retains_backoff(self):
        self.state.write_text(json.dumps({'network':'phone|192.168.1.54|wifi','fixed':m.time.time(),'failed':True,'misses':5}))
        self.assertEqual(self.check(),(1,0))

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

    def test_away_phone_never_restarts_pairing(self):
        self.assertEqual(self.check(network=None,now=True,force=True),(1,0))

if __name__=='__main__':unittest.main()
