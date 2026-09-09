"""Reviewer receipt capture; no production state mount, no upstream installation."""
import base64
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
image = 'sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a'
for test in ['test_action_evolver_selfcheck.py', 'test_agents_capability.py', 'test_agents_normalize.py']:
    argv = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64', '--memory', '256m', '--cpus', '1', '--user', '65534:65534', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', '--env', 'HOME=/tmp', '--env', 'PYTHONDONTWRITEBYTECODE=1', '--mount', 'type=bind,source=' + str(ROOT / '.runtime/absorption/sources/baldrix/pinned/scripts') + ',target=/source/scripts,readonly', '--workdir', '/source/scripts', image, 'timeout', '50', 'python', '-B', 'tests/' + test]
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    p = subprocess.run(argv, capture_output=True, timeout=60)
    rec = dict(kind='actual_isolated_upstream_test', source='baldrix', revision='cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2', image=image, argv=argv, started_at=start, completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), returncode=p.returncode, stdout=p.stdout.decode('utf-8', 'replace'), stderr=p.stderr.decode('utf-8', 'replace'), stdout_base64=base64.b64encode(p.stdout).decode(), stderr_base64=base64.b64encode(p.stderr).decode(), stdout_sha256=hashlib.sha256(p.stdout).hexdigest(), stderr_sha256=hashlib.sha256(p.stderr).hexdigest(), limitations='Linux isolated reviewer execution only; not Windows/WSL or live Claude or Zeus fenced-runner authority. No state/assets/home/credentials mount. Entire imported source and test body reviewed first.')
    (OUT / (test + '.receipt.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(test, p.returncode, rec['stdout'][-220:], rec['stderr'][-220:])
