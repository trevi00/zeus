"""research-dispatch-001: the owner's lease is checked THROUGH the evidence replay, not only before it.

The incident: the executor renewed the lease immediately after the provider returned and then replayed
the worker's claims synchronously with no check at all, so a host inspection finished at 05:21:35 UTC
under a task lease that had ended at 05:20:28 UTC and the final operation failed `execution_stale`.

Every ownership loss below is INJECTED - a second owner writes the row, the row is expired by hand, or
the callback simply refuses - and injected loss is never live recovery evidence. The child processes
are real, and short: nothing here waits for a real 600-second lease, and the only clocks that are
faked are named as such.
"""
import subprocess
import threading
import time
from inspect import signature
from types import SimpleNamespace

import pytest
from test_evidence_inspection import PY, policy, setup_implementation  # noqa: F401 - fixture import
from test_workflow import assignment

from codex_harness.adapters import evidence_inspection as ei
from codex_harness.adapters import executor as ex
from codex_harness.adapters import isolated_evidence as ie
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.evidence_inspection import EvidenceInspector, replay_environment
from codex_harness.adapters.executor import Executor, LeaseProgress
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.evidence_inspection import (
    BUCKET,
    NOTICES,
    EvidenceInspections,
    forwards_progress,
)
from codex_harness.application.execution_time import ExecutionTimeError
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
from codex_harness.domain.policy import POLICY

SLEEP = 'import time; time.sleep({})'
LOST = 'Stale or expired task execution'


def inspector(tmp_path, **replay):
    return EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), policy(**replay))


def command(code, expected_exit=0):
    return {'kind': 'command', 'argv': [PY, '-c', code], 'expected_exit': expected_exit}


def leased(store=None):
    """One real claimed execution; its lease and deadline are the workflow's own."""
    store = store if store is not None else MemoryStore()
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    return store, workflow, workflow.claim('worker:implementation', 'owner-1')


def taken_over(store, lease, owner='owner-2'):
    """INJECTED ownership loss: another owner holds the row the caller is still working under."""
    with store.transaction() as tx:
        row = tx.get('tasks', lease['id'])
        tx.put('tasks', lease['id'], {**row, 'lease_owner': owner})


class Recorder:
    """A progress callback that records its stages and may refuse at a chosen one."""

    def __init__(self, refuse_at=None, error=None, after=0):
        self.stages, self.refuse_at, self.error, self.after = [], refuse_at, error, after

    def __call__(self, stage=None):
        self.stages.append(stage)
        if stage == self.refuse_at and self.stages.count(stage) > self.after:
            raise self.error or ContractError(LOST)

    def count(self, stage):
        return self.stages.count(stage)


class FakeProcess:
    """A process whose wait is scripted; `exits_after` waits report the child as still running."""

    args = ['fake']

    def __init__(self, exits_after=0):
        self.exits_after, self.waits = exits_after, []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if len(self.waits) <= self.exits_after:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return 0


def test_without_a_callback_the_wait_is_exactly_the_bounded_wait_it_always_was():
    process = FakeProcess()
    ei._wait(process, 12.0, None)
    assert process.waits == [12.0], 'a caller that supplies nothing is not polled and not changed'


def test_the_callback_runs_between_bounded_polls_and_the_wait_still_ends_at_its_deadline(monkeypatch):
    monkeypatch.setattr(ei, 'POLL_SECONDS', 0.01)  # deterministic: the poll, not the clock, is shortened
    process, progress = FakeProcess(exits_after=3), Recorder()
    ei._wait(process, 5.0, progress)
    assert progress.stages == ['replay_wait'] * 3 and all(t <= 0.01 for t in process.waits)
    forever, progress = FakeProcess(exits_after=10**6), Recorder()
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        ei._wait(forever, 0.2, progress)
    assert 0.2 <= time.monotonic() - started < 5, 'the per-command deadline is not extended by polling'
    assert progress.count('replay_wait') > 1


def test_a_refusal_during_a_real_wait_reclaims_the_child_and_carries_its_cleanup(tmp_path):
    progress = Recorder(refuse_at='replay_wait')
    started = time.monotonic()
    with pytest.raises(ContractError, match=LOST) as raised:
        ei._capture([PY, '-c', SLEEP.format(120)], str(tmp_path), 120, 4096, replay_environment(), progress=progress)
    assert time.monotonic() - started < 30, 'the lost owner stopped waiting for a 120-second child'
    cleanup = raised.value.capture_cleanup
    assert cleanup['reason'] == 'ContractError' and cleanup['confirmed'] and cleanup['tree']['confirmed']
    assert cleanup['readers_alive'] == [] and sorted(cleanup['streams_closed']) == ['stderr', 'stdout']


def test_a_real_command_is_polled_and_a_live_owner_keeps_its_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(ei, 'POLL_SECONDS', 0.05)
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    progress = Recorder()
    report = inspector(tmp_path, replays_per_claim=1).inspect([command(SLEEP.format(0.5))], workspace,
                                                              {'task_id': 't', 'attempt': 1}, progress=progress)
    assert report['findings'][0]['state'] == 'checked'
    assert progress.stages[0] == 'replay_start' and progress.stages[-1] == 'replay_end'
    assert progress.count('replay_wait') >= 2, 'the owner had its turn while the command ran'


def test_ownership_loss_starts_no_further_command_and_returns_no_findings(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    insp, spawned = inspector(tmp_path, replays_per_claim=2), []
    replay = insp._replay
    insp._replay = lambda *a, **k: (spawned.append(a[0]), replay(*a, **k))[1]
    progress = Recorder(refuse_at='replay_start', after=1)  # lost between the first and the second replay
    with pytest.raises(ContractError, match=LOST):
        insp.inspect([command('import sys; sys.exit(0)'), command('import sys; sys.exit(0)')], workspace,
                     {'task_id': 't', 'attempt': 1}, progress=progress)
    assert len(spawned) == 1, 'the second replay never started'


def test_a_failing_callback_is_raised_through_and_never_becomes_a_verdict(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    progress = Recorder(refuse_at='replay_end', error=RuntimeError('injected callback failure'))
    with pytest.raises(RuntimeError, match='injected callback failure'):
        inspector(tmp_path, replays_per_claim=2).inspect([command('import sys; sys.exit(0)')], workspace,
                                                         {'task_id': 't', 'attempt': 1}, progress=progress)


def test_no_thread_outlives_the_inspection_that_used_a_callback(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    before = set(threading.enumerate())
    progress = Recorder()
    inspector(tmp_path, replays_per_claim=1).inspect([command(SLEEP.format(0.3))], workspace,
                                                     {'task_id': 't', 'attempt': 1}, progress=progress)
    assert {t for t in threading.enumerate() if t.is_alive()} - before == set(), 'no renewer and no reader is left'


def test_the_ledger_checks_the_owner_before_it_reads_and_before_it_writes(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    store, _, lease = leased()
    candidate = {'revision': 'c' * 40}
    calls, insp = [], inspector(tmp_path, replays_per_claim=1)
    real = insp.inspect
    insp.inspect = lambda *a, **k: (calls.append(k.get('progress')), real(*a, **k))[1]
    start = Recorder(refuse_at='inspection_start')
    with pytest.raises(ContractError, match=LOST):
        EvidenceInspections(store, insp).inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace,
                                                 progress=start)
    assert calls == [], 'a lost owner does not even read the inspector'
    end = Recorder(refuse_at='inspection_end')
    with pytest.raises(ContractError, match=LOST):
        EvidenceInspections(store, insp).inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace,
                                                 progress=end)
    assert calls == [end], 'the callback reached the inspector as given, per call'
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [] and tx.scan(NOTICES) == [], 'a stale owner publishes no inspection'
    live = EvidenceInspections(store, insp).inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace,
                                                    progress=Recorder())
    assert live['verdict'] == 'all_checked'
    without = EvidenceInspections(store, insp).inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace)
    assert without == live, 'the identity and the row are the callback-free ones; nothing was added to the key'


class Legacy:
    """An inspector from before this batch: it takes no callback and must keep working untouched."""

    def __init__(self, inner):
        self.inner = inner

    def snapshot(self, cwd=None):
        return self.inner.snapshot(cwd)

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None):
        return self.inner.inspect(claims, cwd, binding, environment=environment, interpreter=interpreter)


def test_an_inspector_that_takes_no_callback_is_not_handed_one_and_still_runs(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    store, _, lease = leased()
    assert forwards_progress(EvidenceInspector.inspect) and not forwards_progress(Legacy.inspect)
    assert not forwards_progress('not a callable')
    progress = Recorder()
    row = EvidenceInspections(store, Legacy(inspector(tmp_path, replays_per_claim=1))).inspect(
        lease, {'revision': 'c' * 40}, [command('import sys; sys.exit(0)')], workspace, progress=progress)
    assert row['verdict'] == 'all_checked'
    assert progress.stages == ['inspection_start', 'inspection_end'], 'the boundary checks still bound it'


def test_the_owner_check_renews_on_its_cadence_and_never_lengthens_the_lease():
    store, workflow, lease = leased()
    now = [1000.0]
    progress = LeaseProgress(workflow, lease, clock=lambda: now[0], check_seconds=5.0, renew_seconds=20.0)

    def lease_window():
        with store.transaction() as tx:
            row = tx.get('tasks', lease['id'])
        return row['execution_clock']['lease_seconds'], row['lease_until']

    progress('inspection_start')
    assert (progress.checks, progress.renewals) == (1, 1)
    seconds, first = lease_window()
    assert seconds <= POLICY.task_lease_seconds
    for moment in (1001.0, 1002.0, 1004.9):
        now[0] = moment
        progress('replay_wait')
    assert (progress.checks, progress.renewals) == (1, 1), 'between the cadences nothing is re-read'
    now[0] = 1006.0
    progress('replay_wait')
    assert (progress.checks, progress.renewals) == (2, 1), 'the deadline is re-read on its own cadence'
    now[0] = 1021.0
    progress('replay_wait')
    assert (progress.checks, progress.renewals) == (3, 2)
    seconds, renewed = lease_window()
    assert seconds <= POLICY.task_lease_seconds, 'a renewal restates the same lease duration, never a longer one'
    assert renewed >= first and progress.refusal is None


def test_the_owner_check_refuses_a_taken_over_or_expired_execution():
    store, workflow, lease = leased()
    progress = LeaseProgress(workflow, lease)
    progress('inspection_start')
    taken_over(store, lease)
    with pytest.raises(ContractError, match=LOST) as raised:
        LeaseProgress(workflow, lease)('replay_wait')
    assert isinstance(raised.value, ContractError)
    store, workflow, lease = leased()
    with store.transaction() as tx:  # INJECTED: the execution deadline has passed
        row = tx.get('tasks', lease['id'])
        tx.put('tasks', lease['id'], {**row, 'execution_deadline': '2020-01-01T00:00:00+00:00'})
    expired = LeaseProgress(workflow, lease)
    with pytest.raises(ExecutionTimeError):
        expired('replay_wait')
    assert expired.refusal is not None and expired.renewals == 0


def executor_with(tmp_path, store):
    """A real executor over a real store; only the git port is a stand-in - no git call is made here."""
    service = Harness(store, organization())
    return Executor(service, SimpleNamespace(_git=lambda *a, **k: 'revision', repository=tmp_path),
                    FileArtifacts(str(tmp_path / 'artifacts')))


def test_the_executor_stops_a_replay_whose_execution_was_taken_over_and_publishes_no_verdict(tmp_path, monkeypatch):
    """The affected path itself: `_inspect_evidence` under a real claimed lease, with the takeover
    INJECTED at the moment the replay starts."""
    monkeypatch.setattr(ei, 'POLL_SECONDS', 0.05)
    monkeypatch.setattr(LeaseProgress, 'CHECK_SECONDS', 0.0)  # every call re-reads; no ten-minute wait
    store, workflow, lease = leased()
    executor = executor_with(tmp_path, store)
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    trees, spawn = [], ei.ProcessTree.spawn

    def recorded(argv, **kwargs):
        tree = spawn(argv, **kwargs)
        trees.append(tree)
        taken_over(store, lease)  # INJECTED: another owner takes the row while this child runs
        return tree
    monkeypatch.setattr(ei.ProcessTree, 'spawn', staticmethod(recorded))
    executor.evidence = EvidenceInspections(store, inspector(tmp_path, replays_per_claim=1))
    result = {'candidate': {'revision': 'c' * 40}, 'tests': [f'{PY} -c "{SLEEP.format(30)}"'], 'execution_ref': None}
    started = time.monotonic()
    with pytest.raises(ContractError, match=LOST):
        executor._inspect_evidence(lease, result, str(workspace))
    assert time.monotonic() - started < 30 and len(trees) == 1
    assert trees[0].process.poll() is not None, 'the child of the lost owner was reclaimed, not left running'
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [] and tx.scan(NOTICES) == [], 'no verdict is published from a stale owner'


def test_the_implement_path_still_inspects_and_completes_with_a_live_lease(setup_implementation):  # noqa: F811
    """No-callback compatibility end to end: the same `execute_one` as before, now carrying a live
    per-call check, still records the inspection and succeeds."""
    row = setup_implementation.executor.execute_one('worker:implementation')
    assert row['status'] == 'succeeded', row.get('error')
    inspection = row['result']['evidence_inspection']
    assert inspection['verdict'] == 'incomplete' and inspection['denominator']['checked'] == 1
    with setup_implementation.service.store.transaction() as tx:
        assert [r['id'] for r in tx.scan(BUCKET)] == [inspection['inspection_id']]


def test_the_callback_is_a_parameter_of_every_hop_and_never_module_or_instance_state():
    """No mutable global callback and no detached renewer: each hop declares `progress` per call, its
    default is None, and the executor keeps the cadence the provider path already uses."""
    for call in (ei.EvidenceInspector.inspect, ei.EvidenceInspector.inspect_command, ei.EvidenceInspector._replay,
                 ei._capture, EvidenceInspections.inspect, ie.DockerEvidenceInspector._replay):
        parameter = signature(call).parameters['progress']
        assert parameter.default is None, call
    assert not [name for name in vars(ei) if 'progress' in name.lower()], 'no module-level callback to share'
    insp = EvidenceInspector(FileArtifacts('unused'))
    assert not [name for name in vars(insp) if 'progress' in name.lower()], 'nothing is stored on the inspector'
    assert ex.LeaseProgress.CHECK_SECONDS == ex.LEASE_CHECK_SECONDS == 5.0
    assert ex.LeaseProgress.RENEW_SECONDS == ex.LEASE_RENEW_SECONDS == 20.0
