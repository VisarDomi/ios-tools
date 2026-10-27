#!/usr/bin/env python3
"""Guarded, simulator-only native/JS/Wasm checks. Never uses devicectl or a phone."""
import argparse,json,os,re,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--device',required=True);p.add_argument('--app',required=True);p.add_argument('--mode',choices=['default','checked','compare'],default='compare');p.add_argument('--no-jit',action='store_true');p.add_argument('--out',required=True);a=p.parse_args()
tools=Path.home()/'Developer/ios-tools/native/scripts';tool=str(tools/'apple-tool');bundle='com.visar.SimulatorHealth.QA'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from simulator_environment import diagnostic_environment,CHECKED_WASM
subprocess.run([str(tools/'mac-workload'),'assert-simulator','--device',a.device],check=True)
out=Path(a.out);out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
def sim(*args,timeout=30,check=True,env=None):
 return subprocess.run([tool,'simctl',*args],timeout=timeout,check=check,capture_output=True,text=True,env=env).stdout.strip()
t=time.monotonic();sim('install',a.device,a.app,timeout=180);print('Installed tiny probe in %.2fs'%(time.monotonic()-t),flush=True)
root=Path(sim('get_app_container',a.device,bundle,'data'))/'Documents';root.mkdir(exist_ok=True)
probe=json.loads((Path(__file__).parent/'wasm-probe.json').read_text())['wasm'];results={};sequence=int(time.time())
def command(action=None,script=None,timeout=30):
 global sequence
 sequence+=1;body=dict(sequence=sequence)
 if action:body['action']=action
 if script:body['script']=script
 temp=root/'command.tmp';temp.write_text(json.dumps(body));temp.replace(root/'command.json');end=time.monotonic()+timeout
 while time.monotonic()<end:
  try:
   r=json.loads((root/'response.json').read_text())
   if r.get('sequence')==sequence:return r
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.2)
 raise TimeoutError('No response to '+str(body)[:180])
def evaluate(script,timeout=30):
 r=command(script=script,timeout=timeout)
 if r['error']:raise RuntimeError(r['error'])
 return r['value']
def process_evidence(mode):
 # Never print complete process environments (which can contain unrelated secrets).
 lines=subprocess.check_output(['ps','-Ao','pid=,comm='],text=True).splitlines();items=[]
 for line in lines:
  if '/CoreSimulator/' not in line or 'com.apple.WebKit.WebContent' not in line:continue
  pid=int(line.split(None,1)[0]);text=subprocess.run(['ps','eww','-p',str(pid)],capture_output=True,text=True).stdout
  flags=re.findall(r'(?:__XPC_)?JSC_(?:dumpOptions|useJIT|useBBQJIT|useOMGJIT|useWasmIPInt|useWasmFastMemory|useWasmFaultSignalHandler|usePollingTraps|useSharedArrayBuffer)=[^\s]+',text)
  items.append(dict(pid=pid,flags=flags))
 (out/(mode+'-processes.json')).write_text(json.dumps(items,indent=2));return items
try:
 for mode in (['default','checked','checked-repeat'] if a.mode=='compare' else [a.mode]):
  sim('terminate',a.device,bundle,check=False)
  for file in ('command.json','response.json'):(root/file).unlink(missing_ok=True)
  flags={'dumpOptions':'1'}
  if a.no_jit:flags['useJIT']='false'
  if mode.startswith('checked'):flags.update(CHECKED_WASM)
  env=diagnostic_environment(os.environ,flags)
  sim('launch','--stdout='+str(out/(mode+'-stdout.log')),'--stderr='+str(out/(mode+'-stderr.log')),a.device,bundle,env=env)
  t=time.monotonic();native=command(action='native',timeout=60)
  assert native['value']['counter']==1 and native['value']['width']>0 and native['value']['labelHeight']>0,native
  print(mode,'native UIKit response %.3fs'%(time.monotonic()-t),flush=True)
  sim('io',a.device,'screenshot',str(out/(mode+'-native.png')))
  command(action='web',timeout=60)
  end=time.monotonic()+30
  while time.monotonic()<end:
   try:
    if evaluate('!!window.healthReady',timeout=5):break
   except (RuntimeError,TimeoutError):pass
   time.sleep(.3)
  else:raise RuntimeError('Plain WebKit page did not become ready')
  js=evaluate('({sum:8+13,canvas:!!document.getElementById("canvas").getContext("2d"),wasm:typeof WebAssembly})');assert js['sum']==21 and js['canvas'],js
  print(mode,'plain JS/canvas passed',flush=True);processes=process_evidence(mode)
  sim('io',a.device,'screenshot',str(out/(mode+'-web.png')))
  script='''(()=>{const b=Uint8Array.from(atob(%s),c=>c.charCodeAt(0));const e=new WebAssembly.Instance(new WebAssembly.Module(b)).exports;
  e.write(0,1234);const before=e.read(0),oldPages=e.grow();e.write(65536,88);let trapped=false,message='';try{e.read(e.memory.buffer.byteLength)}catch(x){trapped=x instanceof WebAssembly.RuntimeError;message=x.message}
  return {answer:e.answer(),before,oldPages,bytes:e.memory.buffer.byteLength,after:e.read(65536),trapped,message};})()'''%json.dumps(probe)
  try:
   wasm=evaluate(script,timeout=45);assert wasm['answer']==42 and wasm['before']==1234 and wasm['oldPages']==1 and wasm['after']==88 and wasm['bytes']==131072 and wasm['trapped'],wasm
   print(mode,'Wasm load/store/grow and caught bounds trap passed',flush=True)
  except Exception as error:
   wasm={'failure':str(error)};print(mode,'Wasm FAILED:',str(error),flush=True)
   if mode!='default':raise
  results[mode]={'native':native,'js':js,'wasm':wasm,'webContent':processes}
  (out/'report.json').write_text(json.dumps(results,indent=2))
finally:
 sim('terminate',a.device,bundle,check=False)
print('COMPLETE simulator-health report:',out/'report.json',flush=True)
