import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime
from codex_harness.domain.invocation import classify_result

CHILD = '''import json,sys,subprocess
from pathlib import Path
sys.stdin.read()
mode=sys.argv[sys.argv.index('--model')+1]
session=sys.argv[sys.argv.index('--session-id')+1]
if mode=='orphan':
 p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 Path('child.pid').write_text(str(p.pid))
if mode=='wrong_session': session='00000000-0000-4000-8000-000000000001'
print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':session,'structured_output':{'ok':True}}),flush=True)
sys.exit(7 if mode=='nonzero' else 0)
'''
rows=[]
for mode in ('nonzero','wrong_session','orphan'):
 with tempfile.TemporaryDirectory(prefix='zeus-review72-') as name:
  root=Path(name); child=root/'child.py'; child.write_text(CHILD,encoding='utf-8')
  runtime=ClaudeCodeRuntime(model=mode,executable=str(child),launcher=[sys.executable],max_budget_usd=1)
  result=runtime.run('test',str(root),{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']},timeout=10)
  row={'mode':mode,'classification':classify_result(result),'termination':result['process'],'session':result['session']}
  if mode=='orphan':
   pid=int((root/'child.pid').read_text())
   try:
    if os.name=='nt':
     observed=subprocess.check_output(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH']).decode(errors='replace')
     row['descendant_alive']=str(pid) in observed
    else:
     os.kill(pid,0); row['descendant_alive']=True
   finally:
    if os.name=='nt': subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True)
    else: os.kill(pid,9)
  rows.append(row)
print(json.dumps(rows,indent=2))
