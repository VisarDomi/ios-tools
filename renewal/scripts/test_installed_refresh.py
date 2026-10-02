import importlib.util
from pathlib import Path
import plistlib
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('installed',Path(__file__).with_name('refresh-installed.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.STORE=Path('/nonexistent/ios-tools-test-store')  # never read this Mac's real registrations

class InstalledTests(unittest.TestCase):
    def test_installed_free_due_paid_not_due_deleted_skipped(self):
        now=200000
        configs={key:dict(root='/'+key,app='app',bundleIds=[key],team='FREE' if key=='free' else 'PAID',
                         interval='daily' if key=='free' else 'monthly') for key in ['free','paid','deleted']}
        items=[dict(config=key,runner=key+'-builder') for key in configs]
        profiles=lambda args,**kw: plistlib.dumps(dict(TeamIdentifier=['FREE' if '/free/' in args[-1] else 'PAID'],LocalProvision='/free/' in args[-1]))
        inventory={'apps':[dict(bundleIdentifier=key,name=key,builtByDeveloper=True) for key in ['free','paid']]}
        with patch.object(m,'state_for',side_effect=lambda item:(configs[item['config']],{'lastSuccess':100000})), \
             patch.object(m,'device_json',return_value=inventory), patch.object(m.time,'time',return_value=now), \
             patch.object(m.subprocess,'check_output',side_effect=profiles), \
             patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            m.refresh(dict(apps=items))
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0][1],'free-builder')

    def test_reports_installed_apps_no_repository_renews(self):
        import json, tempfile
        store=Path(tempfile.mkdtemp())
        other=store/'other'; other.mkdir()
        (other/'mine.json').write_text(json.dumps(dict(bundleIds=['other.app'])))
        (other/'apps.json').write_text(json.dumps(dict(apps=[dict(config=str(other/'mine.json'))])))
        inventory={'apps':[dict(bundleIdentifier=key,name=key,builtByDeveloper=True) for key in ['other.app','orphan.app']]}
        with patch.object(m,'STORE',store), patch.object(m,'device_json',return_value=inventory), \
             patch('builtins.print') as output:
            m.refresh(dict(apps=[]))
        printed=[call.args[0] for call in output.call_args_list]
        self.assertIn('No repository renews installed app: orphan.app',printed)
        self.assertNotIn('No repository renews installed app: other.app',printed)

    def test_changed_signing_account_is_not_silently_deployed(self):
        app=dict(root='/app',app='app',bundleIds=['app'],team='EXPECTED',interval='monthly')
        with patch.object(m,'state_for',return_value=(app,{})), \
             patch.object(m,'device_json',return_value={'apps':[dict(bundleIdentifier='app',name='app')]}), \
             patch.object(m.subprocess,'check_output',return_value=plistlib.dumps(dict(TeamIdentifier=['OTHER']))), \
             patch.object(m.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'account changed'):
                m.refresh(dict(apps=[dict(config='config',runner='builder')]))
            run.assert_not_called()

if __name__=='__main__': unittest.main(buffer=True)
