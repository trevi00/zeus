import json
import subprocess
import sys
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices, verification_environment

out = Path.cwd() / '.runtime/review-073b'
services = VerificationServices(out / 'services', FileArtifacts(out / 'artifacts'))
with services as endpoints:
    result = subprocess.run([sys.executable, '-m', 'pytest', str(out / 'test_adapted.py'),
                             '-q', '--tb=short', '--junitxml=' + str(out / 'adapted.xml')],
                            env=verification_environment(endpoints), capture_output=True)
    data = (result.stdout + result.stderr).replace(services.password.encode(), b'[REDACTED]')
    (out / 'adapted.log').write_bytes(data)
    xml = out / 'adapted.xml'
    if xml.exists():
        xml.write_bytes(xml.read_bytes().replace(services.password.encode(), b'[REDACTED]'))
    print(data.decode('utf-8', errors='replace'))
left = subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + services.project],
                      capture_output=True, text=True)
(out / 'adapted-result.json').write_text(json.dumps({'pytest_exit': result.returncode,
    'project': services.project, 'remaining_containers': left.stdout.strip(),
    'model_calls': 0, 'transport': 'protocol fixture, real PG/Redis/Git/process/filesystem'}, indent=2), encoding='utf-8')
print((out / 'adapted-result.json').read_text('utf-8'))
