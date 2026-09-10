"""FA-025: a release check is bound to the tree it ran against and a test run passes only by its denominator
(INV-CHECK-001).

The upstream installer reported success into an unused hook directory, its pre-push checked the
working tree instead of the pushed ref, a missing coverage input was SKIP with rc 0, empty counters
were 100 % and a zero-check run was a pass. Every check below is a real child process in a real Git
worktree.
"""
import sys
from pathlib import Path

import pytest
from test_git_workspace import git, repository
from test_release_recovery import candidate_runner

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.check_results import (
    OUTCOMES,
    bind_revision,
    classify_test_run,
    is_test_run,
    pytest_summary,
)
from codex_harness.domain.model import ContractError

PY = sys.executable


def test_pytest_summaries_are_parsed_and_only_executed_passes_count():
    assert pytest_summary('....\n5 passed, 2 skipped in 1.02s\n') == {'passed': 5, 'failed': 0, 'skipped': 2, 'errors': 0, 'xfailed': 0,
                                                                        'xpassed': 0, 'deselected': 0, 'warnings': 0, 'parsed': True, 'no_tests_ran': False}
    assert pytest_summary('=== 1 failed, 4 passed, 3 warnings in 0.5s ===')['failed'] == 1
    assert pytest_summary('2 errors in 0.1s')['errors'] == 2
    assert pytest_summary('no tests ran in 0.01s')['no_tests_ran'] and pytest_summary('no tests ran in 0.01s')['parsed']
    assert not pytest_summary('Traceback ...\nModuleNotFoundError: x')['parsed']
    assert classify_test_run(0, '5 passed, 2 skipped in 1.0s')['passed'] is True
    all_skipped = classify_test_run(0, '3 skipped in 0.2s')
    assert all_skipped['passed'] is False and all_skipped['outcome'] == 'empty_check', 'exit 0 with nothing executed is not a pass'
    assert classify_test_run(5, 'no tests ran in 0.01s')['outcome'] == 'empty_check'
    assert classify_test_run(0, '2 deselected in 0.1s')['outcome'] == 'empty_check'
    failed = classify_test_run(1, '1 failed, 4 passed in 0.5s')
    assert failed['passed'] is False and failed['outcome'] == 'executed' and failed['denominator']['failed'] == 1
    liar = classify_test_run(0, '1 failed, 4 passed in 0.5s')
    assert liar['passed'] is False, 'the denominator outranks a zero exit status'
    unstructured = classify_test_run(0, 'ok\n')
    assert unstructured['passed'] is False and unstructured['outcome'] == 'unstructured_output'
    assert classify_test_run(0, '2 xfailed, 1 passed in 0.1s')['passed'] is True
    with pytest.raises(ContractError):
        classify_test_run('0', '1 passed')
    assert is_test_run([PY, '-m', 'pytest', '-q']) and is_test_run(['uv', 'run', 'pytest']) and not is_test_run(['uv', 'sync'])
    assert set(OUTCOMES) >= {'executed', 'observation_error', 'revision_mismatch', 'empty_check', 'unstructured_output'}
    assert bind_revision('a' * 40, 'a' * 40, False)['bound'] and not bind_revision('a' * 40, 'b' * 40, False)['bound']
    assert not bind_revision('a' * 40, 'a' * 40, True)['bound'] and not bind_revision(None, 'a' * 40, False)['bound']


def runner_with_real_git(tmp_path):
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    service = Harness(MemoryStore(), organization())
    runner = ReleaseRunner(service, adapter, FileArtifacts(tmp_path / 'artifacts'), 'unused')
    return runner, adapter, root


def test_checks_bind_to_the_candidate_revision_of_the_workspace_they_ran_in(tmp_path):
    runner, adapter, root = runner_with_real_git(tmp_path)
    head = adapter._git('rev-parse', 'HEAD')
    workspace = adapter.review_workspace(head, 'binding-fixture')
    ok = runner._check([PY, '-c', 'import sys; sys.exit(0)'], workspace, expected_revision=head)
    assert ok['passed'] and ok['outcome'] == 'executed' and ok['binding']['bound']
    assert ok['binding']['observed_head'] == head and ok['binding']['dirty'] is False
    assert Path(ok['binding']['cwd']).resolve() == Path(workspace).resolve()
    receipt = runner.artifacts.document(ok['evidence'])
    assert receipt['binding']['expected_revision'] == head and receipt['exit_code'] == 0
    # The same command under another expected revision is not evidence about that candidate.
    other = runner._check([PY, '-c', 'import sys; sys.exit(0)'], workspace, expected_revision='f' * 40)
    assert other['passed'] is False and other['outcome'] == 'revision_mismatch' and 'is not the candidate' in other['reason']
    assert runner.artifacts.document(other['evidence'])['executed'] is False, 'nothing ran against the wrong tree'
    # A dirty workspace is not the candidate tree either, even at the right HEAD.
    (Path(workspace) / 'scratch.txt').write_text('dirty', encoding='utf-8')
    dirty = runner._check([PY, '-c', 'import sys; sys.exit(0)'], workspace, expected_revision=head)
    assert dirty['outcome'] == 'revision_mismatch' and 'dirty' in dirty['reason']
    (Path(workspace) / 'scratch.txt').unlink()
    # Not a Git worktree: the revision cannot be observed, so the check is an observation error, not a verdict.
    plain = tmp_path / 'plain'
    plain.mkdir()
    unobservable = runner._check([PY, '-c', 'import sys; sys.exit(0)'], str(plain), expected_revision=head)
    assert unobservable['outcome'] == 'observation_error' and 'could not be observed' in unobservable['reason']
    # Without a declared revision the legacy shape is kept, but the receipt still says what was and was not bound.
    legacy = runner._check([PY, '-c', 'import sys; sys.exit(0)'], workspace)
    assert legacy['passed'] and legacy['binding']['expected_revision'] is None and 'bound' not in legacy['binding']


def test_test_checks_pass_only_by_their_denominator_in_the_bound_workspace(tmp_path):
    runner, adapter, root = runner_with_real_git(tmp_path)
    tests = root / 'tests'
    tests.mkdir()
    (tests / 'test_skip.py').write_text('import pytest\n\n@pytest.mark.skip(reason="fixture")\ndef test_a():\n    assert True\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'skipped test')
    head = adapter._git('rev-parse', 'HEAD')
    workspace = adapter.review_workspace(head, 'denominator-fixture')
    argv = [PY, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests']
    skipped = runner._check(argv, workspace, expected_revision=head)
    assert skipped['passed'] is False and skipped['outcome'] == 'empty_check'
    assert skipped['denominator']['skipped'] == 1 and skipped['denominator']['passed'] == 0
    assert runner.artifacts.document(skipped['evidence'])['exit_code'] == 0, 'pytest exited 0; the check still did not pass'
    (tests / 'test_real.py').write_text('def test_b():\n    assert 1 + 1 == 2\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'real test')
    head2 = adapter._git('rev-parse', 'HEAD')
    workspace2 = adapter.review_workspace(head2, 'denominator-fixture-2')
    passed = runner._check(argv, workspace2, expected_revision=head2)
    assert passed['passed'] is True and passed['outcome'] == 'executed'
    assert passed['denominator']['passed'] == 1 and passed['denominator']['skipped'] == 1
    stale = runner._check(argv, workspace, expected_revision=head2)
    assert stale['outcome'] == 'revision_mismatch', 'the old workspace is not the new candidate'
    (tests / 'test_fail.py').write_text('def test_c():\n    assert False\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'failing test')
    head3 = adapter._git('rev-parse', 'HEAD')
    workspace3 = adapter.review_workspace(head3, 'denominator-fixture-3')
    failing = runner._check(argv, workspace3, expected_revision=head3)
    assert failing['passed'] is False and failing['denominator']['failed'] == 1 and failing['outcome'] == 'executed'


def test_isolation_failure_stops_the_runner_before_any_test_check(tmp_path, monkeypatch):
    runner, release, root = candidate_runner(tmp_path)
    with runner.service.store.transaction() as tx:
        record = tx.get('releases', release['id'])
        record.update(status='reviewed', checks={})
        tx.put('releases', release['id'], record)
    calls = []

    def fake_check(argv, cwd=None, timeout=None, env=None, expected_revision=None):
        calls.append(argv[:2])
        return {'passed': True, 'evidence': 'fixture:install', 'outcome': 'executed', 'binding': {}}

    class Unavailable:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self):
            raise ContractError('Explicit isolation failure fixture: compose unavailable')
        def __exit__(self, *args): pass

    monkeypatch.setattr(runner, '_check', fake_check)
    monkeypatch.setattr('codex_harness.adapters.deployment.VerificationServices', Unavailable)
    result = runner.run(release['id'])
    assert result['status'] == 'retry' and result['reason'] == 'verification observation unavailable'
    assert calls == [['uv', 'sync']], 'the install ran; no test check ran without isolation'
    with runner.service.store.transaction() as tx:
        current = tx.get('releases', release['id'])
    assert current['status'] == 'reviewed' and current['checks'] == {}
    assert 'isolation' in runner.artifacts.document(result['evidence'])['stage']


def test_timeout_receipt_keeps_the_binding(tmp_path, monkeypatch):
    runner, adapter, root = runner_with_real_git(tmp_path)
    head = adapter._git('rev-parse', 'HEAD')
    workspace = adapter.review_workspace(head, 'timeout-fixture')
    result = runner._check([PY, '-c', 'import time; time.sleep(30)'], workspace, timeout=1, expected_revision=head)
    assert result['passed'] is False and result['outcome'] == 'observation_error'
    receipt = runner.artifacts.document(result['evidence'])
    assert receipt['binding']['observed_head'] == head and 'timed out' in receipt['error']
