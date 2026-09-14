import json,sys,subprocess
from pathlib import Path
sys.stdin.read()
mode=sys.argv[sys.argv.index('--model')+1].removeprefix('claude-stub-')
session=sys.argv[sys.argv.index('--session-id')+1]
if mode=='orphan':
 p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 Path('child.pid').write_text(str(p.pid))
if mode=='wrong_session': session='00000000-0000-4000-8000-000000000001'
print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':session,'structured_output':{'summary':'review fixture','tests':[]}}),flush=True)
sys.exit(7 if mode=='nonzero' else 0)
