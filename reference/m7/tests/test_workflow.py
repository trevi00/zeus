from datetime import datetime, timedelta, timezone

import pytest

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.releases import Releases
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope


def assignment(action="implement", agent="worker:implementation"):
    parent = organization().actor(agent).parent
    return envelope("task.assign", parent, agent, action, {"objective": "fixture"}, "test")


def test_duplicate_delivery_and_expired_executor_cannot_commit():
    workflow = Workflow(MemoryStore(), organization())
    message = assignment()
    assert workflow.submit(message) == workflow.submit(message)
    task = workflow.claim("worker:implementation", "first", lease_seconds=1)
    assert workflow.claim("worker:implementation", "second") is None
    later = datetime.now(timezone.utc) + timedelta(seconds=2)
    replacement = workflow.claim("worker:implementation", "second", now=later)
    with pytest.raises(ContractError, match="Stale"):
        workflow.complete(task, {"summary": "old writer"})
    workflow.complete(replacement, {"summary": "accepted writer"})
    with workflow.store.transaction() as tx:
        assert len(tx.scan("outbox")) == 1


def test_dependencies_cancellation_deadline_and_attempt_exhaustion():
    workflow = Workflow(MemoryStore(), organization())
    first, second = assignment(), assignment()
    second["when"]["after"] = [first["message_id"]]
    workflow.submit(first)
    workflow.submit(second)
    task = workflow.claim("worker:implementation", "one")
    assert task["id"] == first["message_id"]
    assert workflow.claim("worker:implementation", "two") is None
    workflow.cancel(task["id"], "conductor", "cancel fixture")
    with pytest.raises(ContractError):
        workflow.complete(task, {})
    assert workflow.claim("worker:implementation", "two") is None
    with workflow.store.transaction() as tx:
        assert tx.get("tasks", second["message_id"])["status"] == "cancelled"
    expired = assignment()
    expired["when"]["deadline"] = "2020-01-01T00:00:00+00:00"
    workflow.submit(expired)
    assert workflow.claim("worker:implementation", "two") is None
    retry = assignment()
    workflow.submit(retry)
    for _ in range(3):
        task = workflow.claim("worker:implementation", "two")
        workflow.fail(task, "fixture error")
    assert workflow.claim("worker:implementation", "two") is None
    with workflow.store.transaction() as tx:
        assert tx.get("tasks", retry["message_id"])["status"] == "failed"


def test_report_requires_proven_result_and_only_queues_one_review():
    workflow = Workflow(MemoryStore(), organization())
    workflow.submit(assignment())
    task = workflow.claim("worker:implementation", "first")
    workflow.complete(task, {"candidate": {"revision": "abc"}})
    with workflow.store.transaction() as tx:
        report = tx.scan("outbox")[0]["message"]
    assert workflow.handle(report) == workflow.handle(report)
    with workflow.store.transaction() as tx:
        decisions = tx.scan("decisions_pending")
    assert len(decisions) == 1 and decisions[0]["actor"] == "lead:improvement"
    report["message_id"] = "unproven"
    report["what"]["details"]["result"] = {"candidate": {"revision": "forged"}}
    with pytest.raises(ContractError, match="Unproven"):
        workflow.handle(report)


def reviewed_release(service, revision="a"):
    candidate = {"revision": revision, "base": "base", "tree": "tree", "author": "worker:implementation"}
    release = service.propose(candidate, {"checks": ["live_cli"], "revision": "base"})
    service.review(release["id"], "lead:improvement", revision, True, "sha256:lead")
    service.review(release["id"], "conductor", revision, True, "sha256:conductor")
    return release


def test_release_requires_current_policy_complete_checks_and_fenced_promotion():
    service = Releases(MemoryStore(), organization())
    release = reviewed_release(service)
    with pytest.raises(ContractError, match="Stale"):
        service.verify(release["id"], "a", "candidate-weakened-policy", {})
    with pytest.raises(ContractError, match="Missing"):
        service.verify(release["id"], "a", release["policy_hash"], {})
    service.verify(release["id"], "a", release["policy_hash"],
                   {"live_cli": {"passed": True, "evidence": "actual-fixture-execution"}})
    service.promote(release["id"], None)
    second = reviewed_release(service, "b")
    service.verify(second["id"], "b", second["policy_hash"],
                   {"live_cli": {"passed": True, "evidence": "actual-fixture-execution"}})
    with pytest.raises(ContractError, match="changed"):
        service.promote(second["id"], None)
    service.promote(second["id"], release["id"])
    assert service.rollback(second["id"], "regression")["release_id"] == release["id"]


def test_failed_canary_never_promotes():
    service = Releases(MemoryStore(), organization())
    release = reviewed_release(service)
    service.verify(release["id"], "a", release["policy_hash"],
                   {"live_cli": {"passed": False, "evidence": "failure-log"}})
    with pytest.raises(ContractError, match="not verified"):
        service.promote(release["id"], None)


def test_research_topics_deduplicate_across_scheduled_runs():
    workflow = Workflow(MemoryStore(), organization())
    for _ in range(2):
        task = workflow.submit(assignment("research", "worker:github"))
        claimed = workflow.claim("worker:github", "fixture")
        workflow.complete(claimed, {"source_url": "https://github.com/example/project",
                                   "source_details": {"revision": "source-commit"}})
        with workflow.store.transaction() as tx:
            message = next(row["message"] for row in tx.scan("outbox")
                           if row["message"]["what"]["details"].get("task_id") == task["id"])
        workflow.handle(message)
    with workflow.store.transaction() as tx:
        assert len(tx.scan("decisions_pending")) == 1
        decision = tx.scan("decisions_pending")[0]
        topic = tx.scan("research_topics")[0]
        assert topic['decision_id'] == decision['id']
        assert decision['status'] == 'deferred_pending_source_audit'
        assert len(tx.scan("research_discoveries")) == 1


@pytest.mark.parametrize('phase,actor', [('review_lead', 'lead:improvement'),
                                       ('review_conductor', 'conductor')])
@pytest.mark.parametrize('blocked', [True, False])
def test_executor_blocked_inspection_never_records_release_review(tmp_path, monkeypatch, phase, actor, blocked):
    from types import SimpleNamespace

    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import Executor
    from codex_harness.application.service import Harness

    service = Harness(MemoryStore(), organization())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *a: {},
                          review_workspace=lambda *a: str(tmp_path),
                          _git=lambda *a, **k: '' if a[0] == 'status' else 'revision')
    executor = Executor(service, git, FileArtifacts(str(tmp_path / 'artifacts')))
    candidate = {'revision': 'revision', 'base': 'base', 'tree': 'tree', 'author': 'worker:implementation'}
    data = {'candidate': candidate}
    if phase == 'review_conductor':
        release = executor.releases.propose(candidate, {'checks': ['tests'], 'revision': 'base'})
        executor.releases.review(release['id'], 'lead:improvement', 'revision', True, 'fixture:lead')
        data['release_id'] = release['id']
    message = assignment()
    with service.store.transaction() as tx:
        tx.put('decisions_pending', 'decision', {'id': 'decision', 'actor': actor, 'phase': phase,
               'input': data, 'message': message, 'status': 'pending', 'attempt': 0})
    monkeypatch.setattr(executor, '_run', lambda *a, **k: {
        'accepted': True, 'inspection_blocked': blocked,
        'reason': 'fixture accepted verdict despite inspection failure', 'execution_ref': 'fixture:commands'})
    result = executor.decide_one(actor)
    with service.store.transaction() as tx:
        releases = tx.scan('releases')
        queued = tx.scan('release_queue')
        outbox = tx.scan('outbox')
    if blocked:
        assert result['status'] == 'inspection_blocked'
        assert result['result']['execution_ref'] == 'fixture:commands'
        assert not queued
        assert len(outbox) == 1 and outbox[0]['message']['type'] == 'execution.notice'
        assert outbox[0]['message']['what']['details']['status'] == 'inspection_blocked'
        assert not releases if phase == 'review_lead' else len(releases[0]['reviews']) == 1
    else:
        assert result['status'] == 'succeeded'
        assert releases
        assert outbox if phase == 'review_lead' else queued


def test_executor_persists_blocked_command_evidence_before_returning(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import VERDICT, Executor
    from codex_harness.application.service import Harness

    manifest = json.loads((Path(__file__).resolve().parents[1] /
                           'harness_hooks/hook-ab97ba09554daa5aec289867.json').read_text())
    failure = manifest['cases']['reproduction'][0]['input']
    runtime_result = {'answer': None, 'model_answer_text': '{"accepted":true}',
                      'events': [failure], 'thread_id': failure['params']['threadId'],
                      'usage': None, 'rotate': False, 'interrupted': False,
                      'inspection_blocked': True, 'inspection_failures': [failure]}

    class Runtime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, *args, **kwargs):
            assert kwargs['read_only']
            kwargs['on_event'](failure)
            return runtime_result

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    service = Harness(MemoryStore(), organization())
    artifacts = FileArtifacts(str(tmp_path))
    executor = Executor(service, SimpleNamespace(_git=lambda *a, **k: 'revision'), artifacts)
    result = executor._run('lead:improvement', 'review', 'Review candidate', {},
                           str(tmp_path), VERDICT, read_only=True)
    assert result['accepted'] is False and result['inspection_blocked']
    assert json.loads(artifacts.read(result['execution_ref'])) == runtime_result
    with service.store.transaction() as tx:
        progress = tx.get('execution_progress', 'review')
        assert json.loads(artifacts.read(progress['last_completed']['evidence']))['event'] == failure
        assert tx.get('sessions', 'lead:improvement')['checkpoint']['evidence_ref'] == result['execution_ref']
        # INV-RECURRENCE-001: symptoms alone do not report a confirmed cause.
        assert tx.scan('incidents') == []


@pytest.mark.parametrize('cleanup', ['normal', 'timeout', 'os_error', 'stream_error', 'sigterm'])
@pytest.mark.parametrize('ending', ['eof', 'receive_timeout', 'budget'])
@pytest.mark.parametrize('phase,actor', [('review_lead', 'lead:improvement'),
                                       ('review_conductor', 'conductor')])
def test_blocked_transport_end_to_end(tmp_path, monkeypatch, ending, phase, actor, cleanup):
    import json
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from codex_harness.adapters.app_server import AppServer
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import Executor
    from codex_harness.application.service import Harness

    manifest = json.loads((Path(__file__).resolve().parents[1] /
                           'harness_hooks/hook-ab97ba09554daa5aec289867.json').read_text())
    failure = manifest['cases']['reproduction'][0]['input']
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr('codex_harness.adapters.app_server.time',
                        SimpleNamespace(monotonic=lambda: clock.now))

    if cleanup == 'sigterm' and os.name == 'nt':
        pytest.skip('POSIX process group fixture')
    processes = []

    class Runtime(AppServer):
        def __init__(self, **kwargs):
            super().__init__(executable='fixture', **kwargs)
            self.incoming.put(failure)
            if ending == 'eof':
                self.incoming.put(None)

        def __enter__(self):
            if cleanup == 'sigterm':
                self.process = subprocess.Popen(
                    [sys.executable, '-u', '-c',
                     'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                     'print("ready", flush=True); time.sleep(60)'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, start_new_session=True)
                processes.append(self.process)
                assert self.process.stdout.readline().strip() == 'ready'
                wait = self.process.wait
                monkeypatch.setattr(self.process, 'wait', lambda timeout: wait(timeout=0.05))
            return self

        def __exit__(self, *args):
            super().__exit__(*args)
            if cleanup == 'timeout':
                raise subprocess.TimeoutExpired('fixture', 20)
            if cleanup == 'os_error':
                raise OSError('fixture cleanup failed')
            if cleanup == 'stream_error':
                raise ValueError('fixture stream close failed')

        def request(self, method, params, *args):
            return {'thread': {'id': failure['params']['threadId']},
                    'turn': {'id': failure['params']['turnId']}}

        def _receive(self, *args, **kwargs):
            if ending == 'budget' and self.incoming.empty():
                clock.now = 1000
                return {}
            return super()._receive(0.01, poll=False)

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    service = Harness(MemoryStore(), organization())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *a: {},
                          review_workspace=lambda *a: str(tmp_path),
                          _git=lambda *a, **k: '' if a[0] == 'status' else 'revision')
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    executor = Executor(service, git, artifacts)
    candidate = {'revision': 'revision', 'base': 'base', 'tree': 'tree',
                 'author': 'worker:implementation'}
    data = {'candidate': candidate}
    if phase == 'review_conductor':
        release = executor.releases.propose(candidate, {'checks': ['tests'], 'revision': 'base'})
        executor.releases.review(release['id'], 'lead:improvement', 'revision', True, 'fixture')
        data['release_id'] = release['id']
    with service.store.transaction() as tx:
        tx.put('decisions_pending', 'decision', {'id': 'decision', 'actor': actor, 'phase': phase,
               'input': data, 'message': assignment(), 'status': 'pending', 'attempt': 0})
    try:
        result = executor.decide_one(actor)
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
    if processes:
        assert processes[0].returncode == -signal.SIGKILL
        assert all(stream.closed for stream in
                   (processes[0].stdin, processes[0].stdout, processes[0].stderr))
    assert result['status'] == 'inspection_blocked'
    assert result['result']['accepted'] is False
    ref = result['result']['execution_ref']
    evidence = json.loads(artifacts.read(ref))
    assert evidence['inspection_failures'] == [failure]
    assert evidence['termination_error']
    if cleanup in {'timeout', 'os_error', 'stream_error'}:
        assert evidence['cleanup_error']['type'] == {
            'timeout': 'TimeoutExpired', 'os_error': 'OSError', 'stream_error': 'ValueError'}[cleanup]
    else:
        assert 'cleanup_error' not in evidence
    assert executor.decide_one(actor) is None
    with service.store.transaction() as tx:
        assert tx.get('decisions_pending', 'decision')['attempt'] == 1
        assert tx.get('sessions', actor)['checkpoint']['evidence_ref'] == ref
        progress = tx.get('execution_progress', 'decision')
        assert json.loads(artifacts.read(progress['last_completed']['evidence']))['event'] == failure
        assert not tx.scan('release_queue')
        messages = [r['message'] for r in tx.scan('outbox')]
        assert len(messages) == 1 and messages[0]['type'] == 'execution.notice'
        assert messages[0]['what']['details']['status'] == 'inspection_blocked'
        assert not tx.scan('improvement_loops') and not tx.scan('incidents')
        releases = tx.scan('releases')
        assert not releases if phase == 'review_lead' else len(releases[0]['reviews']) == 1


@pytest.mark.parametrize('run_fails', [False, True])
def test_cleanup_error_without_blocked_result_still_propagates(tmp_path, monkeypatch, run_fails):
    from types import SimpleNamespace

    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import VERDICT, Executor
    from codex_harness.application.service import Harness

    class Runtime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def run(self, *args, **kwargs):
            if run_fails:
                raise ContractError('fixture callback/lease failure')
            return {'answer': {'accepted': True}, 'events': [], 'thread_id': 'fixture',
                    'usage': None, 'rotate': False, 'interrupted': False}

        def __exit__(self, *args):
            raise OSError('fixture cleanup failure')

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    service = Harness(MemoryStore(), organization())
    executor = Executor(service, SimpleNamespace(_git=lambda *a, **k: 'revision'),
                        FileArtifacts(str(tmp_path)))
    with pytest.raises(OSError, match='cleanup failure') as raised:
        executor._run('lead:improvement', 'review', 'Review', {}, str(tmp_path), VERDICT, True)
    if run_fails:
        assert isinstance(raised.value.__context__, ContractError)
    with service.store.transaction() as tx:
        assert tx.get('sessions', 'lead:improvement') is None
