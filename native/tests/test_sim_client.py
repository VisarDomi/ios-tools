"""Client command construction only; no SSH, simulator or phone operations."""
from pathlib import Path
import io,runpy,shlex,subprocess,sys,unittest
from unittest.mock import patch

SCRIPT=Path(__file__).parents[1]/'scripts/sim'
DEVICE='12345678-1234-1234-1234-123456789ABC'
class SimClientTests(unittest.TestCase):
    def invoke(self,action,args=(),options=()):
        calls=[]
        def run(command,**kwargs):
            calls.append((command,kwargs))
            return subprocess.CompletedProcess(command,0,stdout=b'',stderr=b'')
        output=io.TextIOWrapper(io.BytesIO())
        with patch.object(sys,'path',[str(SCRIPT.parent),*sys.path]),patch.object(sys,'argv',[str(SCRIPT),'--device',DEVICE,*options,action,*args]),patch.object(sys,'stdout',output),patch.object(subprocess,'run',side_effect=run):
            runpy.run_path(str(SCRIPT),run_name='__main__')
        return calls
    def remote_code(self,call):
        program=call[0][-1];tokens=shlex.split(program.split(' && ',1)[-1])
        self.assertEqual(tokens[:2],['python3','-c'])
        compile(tokens[2],'<remote-operation>','exec')
        return tokens[2]
    def test_installer_has_a_real_remote_deadline_and_safe_path_arguments(self):
        path="/tmp/QA app's $(do-not-execute).app"
        call=self.invoke('install',[path])[0];code=self.remote_code(call)
        self.assertIn(repr(path),code)
        self.assertIn('timeout=240',code)
        self.assertEqual(call[1]['timeout'],270)
    def test_launch_freshens_only_selected_app_and_honors_profile(self):
        call=self.invoke('launch',['com.visar.SimulatorHealth.QA'],['--wasm-compat'])[0]
        code=self.remote_code(call)
        self.assertIn("'terminate', '"+DEVICE+"', 'com.visar.SimulatorHealth.QA'",code)
        self.assertIn('intel_wasm_overrides()',code)
        self.assertIn("lease.get('wasmCompat',False)",code)
        self.assertLess(code.index("'terminate'"),code.index("p=subprocess.run"))
    def test_explicit_runtime_default_option_builds_valid_remote_code(self):
        code=self.remote_code(self.invoke('launch',['com.visar.SimulatorHealth.QA'],['--native-wasm'])[0])
        self.assertIn('env.update({} if True',code)
if __name__=='__main__':unittest.main()
