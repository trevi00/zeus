import json
import subprocess
import sys
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices, verification_environment

out = Path.cwd() / '.runtime/review-101d'
services = VerificationServices(out / 'services', FileArtifacts(out / 'artifacts'))
with services as endpoints:
    result = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_verification.py', str(out / 'test_review.py'), str(out / 'test_owner.py'),
                             '-q', '--tb=short', '--junitxml=' + str(out / 'counterexamples.xml')],
                            env=verification_environment(endpoints), capture_output=True)
    data = (result.stdout + result.stderr).replace(services.password.encode(), b'[REDACTED]')
    (out / 'counterexamples.log').write_bytes(data)
    xml = out / 'counterexamples.xml'
    if xml.exists():
        xml.write_bytes(xml.read_bytes().replace(services.password.encode(), b'[REDACTED]'))
    print(data.decode('utf-8', errors='replace'))
left = subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + services.project],
                      capture_output=True, text=True)
(out / 'result.json').write_text(json.dumps({'pytest_exit': result.returncode,
    'project': services.project, 'remaining_containers': left.stdout.strip(),
    'model_calls': 0, 'transport': 'real PG/Redis, API boundary delay/error injection, no model'}, indent=2), encoding='utf-8')
print((out / 'result.json').read_text('utf-8'))
