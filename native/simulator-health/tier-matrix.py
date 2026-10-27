#!/usr/bin/env python3
"""Controlled app-only JSC tier comparisons in one guarded diagnostic session."""
import argparse,json,os,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--device',required=True);p.add_argument('--app',required=True);p.add_argument('--checker',required=True);p.add_argument('--save',required=True);p.add_argument('--scenario',required=True);p.add_argument('--out',required=True);a=p.parse_args()
tools=Path.home()/'Developer/ios-tools/native/scripts';subprocess.run([str(tools/'mac-workload'),'assert-simulator','--device',a.device],check=True)
out=Path(a.out);out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
subprocess.run([str(tools/'apple-tool'),'simctl','install',a.device,a.app],timeout=240,check=True)
variants={
 'js-interpreted':dict(useJIT='true',useBaselineJIT='false',useDFGJIT='false',useFTLJIT='false'),
 'wasm-ipint':dict(useJIT='true',useWasmIPInt='true',useBBQJIT='false',useOMGJIT='false'),
 'wasm-bbq':dict(useJIT='true',useWasmIPInt='false',useBBQJIT='true',useOMGJIT='false'),
}
report={}
for name,options in variants.items():
 env=dict(os.environ)
 for option,value in options.items():
  env['SIMCTL_CHILD_JSC_'+option]=value;env['SIMCTL_CHILD___XPC_JSC_'+option]=value
 command=['python3',a.checker,'--device',a.device,'--app',a.app,'--save',a.save,'--scenario',a.scenario,'--startup-timeout','100','--skip-install','--startup-only','--out',str(out/name)]
 print('Testing',name,options,flush=True);start=time.monotonic()
 with (out/(name+'.log')).open('w') as log:
  result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150)
 report[name]=dict(returncode=result.returncode,seconds=round(time.monotonic()-start,2),options=options)
 subprocess.run([str(tools/'apple-tool'),'simctl','terminate',a.device,'com.visar.MaidHeroes'],capture_output=True,timeout=20)
 (out/'report.json').write_text(json.dumps(report,indent=2))
 print(name,report[name],flush=True)
print('JSC tier comparison complete',flush=True)
