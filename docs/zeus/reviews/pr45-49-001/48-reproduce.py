import json, sys, tempfile, subprocess
from pathlib import Path
sys.path[:0] = ['C:/Users/rudtn/zeus-pr-review-48/src', 'C:/Users/rudtn/zeus-pr-review-48/tests']
from test_git_workspace import repository
from codex_harness.adapters.git import GitWorkspace
with tempfile.TemporaryDirectory() as d:
    p=Path(d); root=repository(p)
    first=GitWorkspace(str(root),str(p/'workspaces'))
    workspace=first.prepare('counterexample')
    (Path(workspace['path'])/'change.txt').write_text('reviewed for repository A','utf-8')
    candidate=first.capture(workspace)
    subprocess.run(['git','clone','--quiet',str(root),str(p/'other-repo')],check=True,capture_output=True)
    other=GitWorkspace(str(p/'other-repo'),str(p/'other-workspaces'))
    other._git('config','user.name','Review Fixture'); other._git('config','user.email','review@example.invalid')
    result=other.merge(candidate)
    print(json.dumps({'scope':'two actual isolated local Git repositories, no GitHub mutation','target_identity':candidate['repository'],'different_repository':first.repository!=other.repository,'merged_into_second':result,'second_file_exists':(p/'other-repo/change.txt').exists()}))
