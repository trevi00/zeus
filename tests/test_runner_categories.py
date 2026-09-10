"""FA-026: an isolated run is named by where it ended and what it produced, never by exit status alone
(INV-RUNNER-001).

The upstream runner accepted an empty rc 0 script and a stderr FAIL as passes, misread an assertion
message as a missing dependency, fell back from a failed pytest to a weaker manual main, and could
re-run in the original environment after an isolation exception.
"""
import os
import subprocess

import pytest
from test_research_audits import audit  # noqa: F401

from codex_harness.adapters.source_execution import DockerSourceRunner
from codex_harness.domain.check_results import RUN_CATEGORIES, classify_isolated_run
from codex_harness.domain.model import ContractError

IMAGE = 'sha256:' + 'a' * 64


def test_categories_come_from_stage_exit_and_output():
    assert classify_isolated_run(stage='materialize', exit_status=None, stdout='', stderr='', command=['x'], error='bad bytes') == {
        'category': 'isolation_unavailable', 'stage': 'materialize', 'passed': False, 'reason': 'bad bytes',
        'output_class': 'none', 'substitute_execution': False}
    assert classify_isolated_run(stage='spawn', exit_status=None, stdout='', stderr='', command=['x'])['category'] == 'isolation_unavailable'
    assert classify_isolated_run(stage='run', exit_status=None, stdout='', stderr='', command=['x'], client_timeout=True)['category'] == 'client_timeout'
    for status, category in ((124, 'timeout'), (137, 'timeout'), (125, 'runner_error'), (126, 'runner_error'), (127, 'runner_error')):
        verdict = classify_isolated_run(stage='run', exit_status=status, stdout='', stderr='boom', command=['x'])
        assert verdict['category'] == category and verdict['passed'] is False
    empty = classify_isolated_run(stage='run', exit_status=0, stdout='', stderr='', command=['python', 'script.py'])
    assert empty['category'] == 'executed' and empty['passed'] is False and empty['output_class'] == 'empty'
    diagnostic = classify_isolated_run(stage='run', exit_status=0, stdout='', stderr='FAIL: something', command=['python', 'script.py'])
    assert diagnostic['passed'] is False and diagnostic['output_class'] == 'stderr_only'
    ok = classify_isolated_run(stage='run', exit_status=0, stdout='ran 3 checks', stderr='', command=['python', 'script.py'])
    assert ok['passed'] is True and ok['mode'] == 'command'
    assert classify_isolated_run(stage='run', exit_status=2, stdout='out', stderr='', command=['python', 'script.py'])['passed'] is False
    # A pytest command is judged by its denominator, and an assertion message is never a missing dependency.
    skipped = classify_isolated_run(stage='run', exit_status=0, stdout='3 skipped in 0.1s', stderr='', command=['python', '-m', 'pytest'])
    assert skipped['mode'] == 'pytest' and skipped['passed'] is False and skipped['outcome'] == 'empty_check'
    failed = classify_isolated_run(stage='run', exit_status=1, stdout='AssertionError: No module named x\n1 failed in 0.1s', stderr='',
                                   command=['python', '-m', 'pytest'])
    assert failed['passed'] is False and failed['outcome'] == 'executed' and failed['denominator']['failed'] == 1
    passed = classify_isolated_run(stage='run', exit_status=0, stdout='4 passed in 0.2s', stderr='warnings', command=['pytest', '-q'])
    assert passed['passed'] is True and passed['denominator']['passed'] == 4
    assert set(RUN_CATEGORIES) == {'executed', 'isolation_unavailable', 'client_timeout', 'timeout', 'runner_error'}
    with pytest.raises(ContractError):
        classify_isolated_run(stage='host', exit_status=0, stdout='', stderr='', command=['x'])


def receipt_document(service, receipt):
    return service.artifacts.document(receipt.output_ref)


def test_runner_receipts_carry_category_denominator_and_attempt(audit, tmp_path, monkeypatch):  # noqa: F811
    service, _, source, _, _ = audit
    runner = DockerSourceRunner(tmp_path / 'host', service.artifacts)
    outcomes = {'empty': (0, '', ''), 'stderr_fail': (0, '', 'FAIL: x'), 'ok': (0, 'hello', ''), 'timeout': (137, '', ''),
                'runner': (125, '', 'docker: Error response from daemon'), 'skipped': (0, '2 skipped in 0.1s', '')}
    current = {'name': 'ok'}

    def run(argv, timeout):
        status, out, err = outcomes[current['name']]
        return subprocess.CompletedProcess(argv, status, out, err)
    monkeypatch.setattr('codex_harness.adapters.source_execution.bounded_command', run)
    monkeypatch.setattr('codex_harness.adapters.source_execution.run_process', run)
    seen = {}
    for name in outcomes:
        current['name'] = name
        command = ['python', '-m', 'pytest', '-q'] if name == 'skipped' else ['python', 'script.py']
        receipt = runner.execute(source, command, IMAGE, attempt={'request_id': 'r1', 'owner': 'o1', 'task_id': 't1', 'generation': 1})
        seen[name] = (receipt, receipt_document(service, receipt))
    receipt, doc = seen['ok']
    assert receipt.exit_status == 0 and not receipt.inspection_blocked and doc['verdict']['passed'] is True
    assert doc['attempt'] == {'request_id': 'r1', 'owner': 'o1', 'task_id': 't1', 'generation': 1}
    assert doc['stdout_sha256'] and doc['runner_mode'] == 'docker-networkless-readonly' and doc['command'] == ['python', 'script.py']
    receipt, doc = seen['empty']
    assert receipt.exit_status == 0 and doc['verdict']['passed'] is False and doc['verdict']['output_class'] == 'empty'
    receipt, doc = seen['stderr_fail']
    assert doc['verdict']['passed'] is False and doc['verdict']['output_class'] == 'stderr_only'
    receipt, doc = seen['timeout']
    assert receipt.inspection_blocked and doc['verdict']['category'] == 'timeout'
    receipt, doc = seen['runner']
    assert receipt.inspection_blocked and doc['verdict']['category'] == 'runner_error'
    receipt, doc = seen['skipped']
    assert receipt.exit_status == 0 and doc['verdict']['mode'] == 'pytest' and doc['verdict']['outcome'] == 'empty_check'
    assert not receipt.inspection_blocked, 'an executed-but-empty pytest run is not blocked; it is simply not a pass'


def test_isolation_failures_are_unavailable_and_never_rerun_on_the_host(audit, tmp_path, monkeypatch):  # noqa: F811
    service, _, source, _, _ = audit
    # No docker binary at the configured path and none on PATH: the spawn fails for real on every host
    # (CI Windows runners resolve a bare `docker` outside PATH), and nothing else is tried.
    runner = DockerSourceRunner(tmp_path / 'host', service.artifacts, docker=str(tmp_path / 'empty-path' / 'docker'))
    monkeypatch.setenv('PATH', str(tmp_path / 'empty-path'))
    monkeypatch.setattr('codex_harness.adapters.source_execution.run_process',
                        lambda argv, timeout: (_ for _ in ()).throw(OSError('no docker')))
    receipt = runner.execute(source, ['python', 'script.py'], IMAGE)
    doc = receipt_document(service, receipt)
    assert receipt.inspection_blocked and receipt.exit_status == 125
    assert doc['verdict']['category'] == 'isolation_unavailable' and doc['verdict']['stage'] == 'spawn'
    assert doc['verdict']['substitute_execution'] is False and 'FileNotFoundError' in doc['verdict']['reason']
    assert doc['error'] and 'attempt' in doc
    # Materialization failure (a source entry whose bytes do not match) ends before any runner starts.
    manifest = service.artifacts.document(source.manifest_ref)
    entry = dict(manifest['entries'][0])
    bad = {**service.artifacts.document(entry['artifact_ref']), 'bytes_sha256': 'f' * 64}
    entry['artifact_ref'] = service.artifacts.put(__import__('codex_harness.domain.model', fromlist=['canonical']).canonical(bad), 'corrupt')['ref']
    from dataclasses import replace

    from codex_harness.domain.model import canonical
    corrupt_source = replace(source, manifest_ref=service.artifacts.put(canonical({**manifest, 'entries': [entry] + manifest['entries'][1:]}), 'corrupt-manifest')['ref'])
    calls = []
    monkeypatch.setattr('codex_harness.adapters.source_execution.bounded_command', lambda argv, timeout: calls.append(argv))
    monkeypatch.setattr('codex_harness.adapters.source_execution.run_process', lambda argv, timeout: subprocess.CompletedProcess(argv, 0, '', ''))
    receipt = runner.execute(corrupt_source, ['python', 'script.py'], IMAGE)
    doc = receipt_document(service, receipt)
    assert doc['verdict']['category'] == 'isolation_unavailable' and doc['verdict']['stage'] == 'materialize'
    assert calls == [], 'no container ran on a source that could not be materialized'
    # Client timeout: the docker client outlived its deadline; the receipt says so and the container is removed.
    removed = []

    def slow(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr('codex_harness.adapters.source_execution.bounded_command', slow)
    monkeypatch.setattr('codex_harness.adapters.source_execution.run_process', lambda argv, timeout: removed.append(argv) or subprocess.CompletedProcess(argv, 0, '', ''))
    receipt = runner.execute(source, ['python', 'script.py'], IMAGE)
    doc = receipt_document(service, receipt)
    assert doc['verdict']['category'] == 'client_timeout' and receipt.inspection_blocked
    assert removed and removed[-1][:3] == [runner.docker, 'rm', '-f']
    assert os.name  # platform-neutral: no host rerun path exists to exercise
