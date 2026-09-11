import hashlib
import json
import subprocess
from pathlib import Path

root = Path('docs/zeus/evidence/environment-runs-004')
rows = []
def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()
for label in ('windows-11', 'wsl-ubuntu-26.04'):
    receipt = json.loads((root / (label + '-receipt.json')).read_text('utf-8'))
    checks = []
    for step in receipt['steps']:
        text = (root / step['log']).read_text('utf-8')
        stdout, separator, stderr = text.partition('\n--- stderr ---\n')
        checks.append({'step': step['name'], 'exit_code': step['exit_code'],
                       'stdout_matches': digest(stdout.encode()) == step['stdout_sha256'],
                       'stderr_matches': digest(stderr.encode()) == step['stderr_sha256']})
    junit = root / (label + '-full-suite.junit.xml')
    delta = subprocess.check_output(['git', 'diff', '--name-only', receipt['head'], '18df1c3', '--', 'src', 'scripts', 'uv.lock'])
    row = {'label': label, 'head': receipt['head'], 'checks': checks,
           'junit_matches': digest(junit.read_bytes()) == receipt['junit_sha256'],
           'runtime_delta_empty': not delta.strip(), 'pyproject_delta': 'two-line review archive lint exemption',
           'identity_stable': receipt['phases']['identity_stable']['ok'],
           'summaries': [s['summary'] for s in receipt['steps']]}
    rows.append(row)
Path('.runtime/review-071b/receipt-check.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(json.dumps(rows, indent=2))
assert all(r['junit_matches'] and r['runtime_delta_empty'] and r['identity_stable'] and
           all(c['stdout_matches'] and c['stderr_matches'] and c['exit_code'] == 0 for c in r['checks']) for r in rows)
