import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters.app_server import namespace_failure

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'harness_hooks/codex_namespace_guard.py'
MANIFEST = json.loads((ROOT / 'harness_hooks/hook-ab97ba09554daa5aec289867.json').read_text())


def test_exact_script_hash_and_incident_threads():
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == MANIFEST['spec']['script_sha256']
    cases = MANIFEST['cases']['reproduction']
    assert len(cases) == 4
    assert len({c['input']['params']['threadId'] for c in cases}) == 2
    assert all(namespace_failure(c['input']) for c in cases)


@pytest.mark.parametrize('case', sum(MANIFEST['cases'].values(), []))
def test_standalone_fixtures(case):
    result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(case['input']),
                            text=True, capture_output=True, timeout=5)
    assert result.returncode == case['exit_code']
    assert (json.loads(result.stdout) if result.stdout else None) == case['output']
    if case in MANIFEST['cases']['normal_case']:
        assert not namespace_failure(case['input'])


@pytest.mark.parametrize('raw', ['{', '', '[', 'null', '"bwrap: No permissions to create a new namespace"'])
def test_malformed_native_input_has_no_recurrence(raw):
    result = subprocess.run([sys.executable, str(SCRIPT)], input=raw, text=True,
                            capture_output=True, timeout=5)
    assert result.returncode == 0 and not result.stdout


@pytest.mark.parametrize('field', ['status', 'exitCode', 'aggregatedOutput', 'type', 'id'])
def test_missing_execution_fields_do_not_match(field):
    event = copy.deepcopy(MANIFEST['cases']['reproduction'][0]['input'])
    del event['params']['item'][field]
    assert not namespace_failure(event)


@pytest.mark.parametrize('field', ['threadId', 'turnId'])
def test_missing_execution_identity_does_not_match(field):
    event = copy.deepcopy(MANIFEST['cases']['reproduction'][0]['input'])
    del event['params'][field]
    assert not namespace_failure(event)
