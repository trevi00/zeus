import json
import subprocess
import sys
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices, verification_environment

root = Path.cwd()
out = root / '.runtime' / 'review-071c'
services = VerificationServices(out / 'services', FileArtifacts(out / 'artifacts'))
with services as endpoints:
    env = verification_environment(endpoints)
    command = [sys.executable, '-m', 'pytest', 'tests/test_observation_contract.py',
               'tests/test_observation_spool.py', 'tests/test_observations.py',
               'tests/test_observation_wiring.py', 'tests/test_observation_review.py', 'tests/test_observation_review2.py', '-q',
               '--junitxml=.runtime/review-071c/integration.xml']
    result = subprocess.run(command, cwd=root, env=env, capture_output=True)
    data = (result.stdout + result.stderr).replace(services.password.encode(), b'[REDACTED]')
    (out / 'integration.log').write_bytes(data)
    junit = out / 'integration.xml'
    if junit.exists():
        junit.write_bytes(junit.read_bytes().replace(services.password.encode(), b'[REDACTED]'))
    print(data.decode('utf-8', errors='replace'))
    code = result.returncode
(out / 'integration-result.json').write_text(json.dumps({
    'exit_code': code, 'project': services.project, 'cleanup': 'completed',
    'scope': 'Windows isolated PostgreSQL + Redis; fake model transport'}, indent=2), encoding='utf-8')
raise SystemExit(code)
