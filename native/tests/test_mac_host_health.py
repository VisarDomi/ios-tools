import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import mac_host_health as m

class MacEvidenceTests(unittest.TestCase):
 def test_console_shield_does_not_claim_authentication_or_offline(self):
  data=plistlib.dumps([dict(IOConsoleUsers=[dict(kCGSSessionUserNameKey='fixture',CGSSessionScreenIsLocked=True)])])
  row=m.console_sessions(data)[0]
  self.assertTrue(row['screenShieldFlag']);self.assertIsNone(row['authenticationRequired'])
  self.assertNotIn('offline',row)
 def test_missing_console_flags_stay_unknown(self):
  row=m.console_sessions(plistlib.dumps([dict(IOConsoleUsers=[{}])]))[0]
  self.assertIsNone(row['screenShieldFlag'])
 def test_crash_metadata_retains_original_date_guest_and_watchdog(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'fixture.ips';path.write_text('{}\n'+json.dumps(dict(procName='MobileCal',captureTime='2026-11-07',coalitionName='sim.fixture',termination=dict(namespace='FRONTBOARD',code=0x8badf00d))))
   result=m.crash_summary(path);self.assertEqual(result['captured'],'2026-11-07');self.assertEqual(result['coalition'],'sim.fixture')
   self.assertEqual(result['termination']['code'],0x8badf00d)
 def test_alerts_are_distinct_from_normal_windows(self):
  rows=[dict(process='Xcode',windows=[dict(name='project',role='AXWindow',subrole='AXStandardWindow')]),
        dict(process='CoreServicesUIAgent',windows=[dict(name='MobileCal quit unexpectedly',role='AXWindow')])]
  self.assertEqual([x['process'] for x in m.ui_blockers(rows)],['CoreServicesUIAgent'])
 def test_modal_sheets_are_detected_without_guessing_their_cause(self):
  self.assertEqual(len(m.ui_blockers([dict(process='Xcode',windows=[dict(name='project',sheets=[dict(name='alert')])])])),1)
 def test_noninteractive_configuration_preserves_first_backup_and_checks_readback(self):
  with tempfile.TemporaryDirectory() as td:
   receipt=Path(td)/'backup.json'
   with patch.object(m,'command',side_effect=[dict(ok=False,stdout='',stderr='The domain/default pair does not exist'),dict(ok=True),dict(ok=True,stdout='none')]):
    self.assertFalse(m.crash_dialogs('noninteractive',receipt)['crashCaptureDisabled'])
   self.assertIsNone(json.loads(receipt.read_text())['previous'])
   with patch.object(m,'command',side_effect=[dict(ok=True,stdout='none'),dict(ok=True),dict(ok=True,stdout='none')]):m.crash_dialogs('noninteractive',receipt)
   self.assertIsNone(json.loads(receipt.read_text())['previous'])
 def test_restore_returns_absent_preference_to_absent(self):
  with tempfile.TemporaryDirectory() as td:
   receipt=Path(td)/'backup.json';receipt.write_text('{"previous":null}')
   with patch.object(m,'command',side_effect=[dict(ok=True,stdout='none'),dict(ok=True),dict(ok=False,stdout='')]) as run:m.crash_dialogs('restore',receipt)
   self.assertEqual(run.call_args_list[1].args[0],['/usr/bin/defaults','delete','com.apple.CrashReporter','DialogType'])
 def test_unreadable_preferences_are_not_overwritten_as_missing(self):
  with tempfile.TemporaryDirectory() as td,patch.object(m,'command',return_value=dict(ok=False,error='timeout')):
   receipt=Path(td)/'backup.json'
   with self.assertRaisesRegex(RuntimeError,'Cannot establish'):m.crash_dialogs('noninteractive',receipt)
   self.assertFalse(receipt.exists())
 def test_ui_probe_failure_is_unknown_not_no_alerts(self):
  def fake(argv,timeout=8):
   if argv[0]=='/usr/bin/osascript':return dict(ok=False,error='permission denied')
   return dict(ok=False,stdout='',stderr='fixture')
  with patch.object(m,'command',side_effect=fake):report=m.collect(True)
  self.assertFalse(report['ui']['complete']);self.assertNotIn('blockers',report['ui'])

if __name__=='__main__':unittest.main()
