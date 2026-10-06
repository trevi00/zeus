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
from test_project_evidence import POLICY as PROJECT_POLICY
from test_project_evidence import check as project_check
from test_project_evidence import document, executed
from test_project_evidence import policy as project_policy
from test_project_evidence import workspace as project_candidate
from test_workflow import assignment

from codex_harness.adapters import evidence_inspection as ei
from codex_harness.adapters import executor as ex
from codex_harness.adapters import isolated_evidence as ie
from codex_harness.adapters import project_evidence as pe
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.evidence_inspection import EvidenceInspector, replay_environment
from codex_harness.adapters.executor import Executor, LeaseProgress
from codex_harness.adapters.project_evidence import ProjectEvidenceInspector
from codex_harness.adapters.store import MemoryStore
from codex_harness.application import evidence_inspection as ledger
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
from codex_harness.domain.project_evidence import parse_profile

SLEEP = 'import time; time.sleep({})'
LOST = 'Stale or expired task execution'


def inspector(tmp_path, **replay):
    return EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), policy(**replay))


def project(tmp_path, seconds=0.1, name='candidate'):
    """An existing valid host project-evidence fixture, with one real check that sleeps briefly.

    The check is a real `python -m pytest` child of the profile's own interpreter in the profile's
    own context; only its duration is chosen here, so no test waits for a real lease."""
    root = project_candidate(tmp_path, name)
    (root / 'backend' / 'probes' / 'test_slow.py').write_text(
        f'import time\n\n\ndef test_slow():\n    time.sleep({seconds})\n', encoding='utf-8')
    return root


def project_inspector(tmp_path, doc=None, **replay):
    return ProjectEvidenceInspector(FileArtifacts(str(tmp_path / 'project-artifacts')),
                                    parse_profile(doc or document([project_check('slow', 'slow')]), PROJECT_POLICY),
                                    project_policy(**replay))


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


def test_the_profile_route_polls_a_real_child_and_a_live_owner_keeps_its_findings(tmp_path, monkeypatch):
    """R1: the third production inspector. Its host check is a real pytest child in the profile's own
    context, and the caller's turn comes between the bounded polls of that wait, as on the legacy route."""
    monkeypatch.setattr(ei, 'POLL_SECONDS', 0.05)  # the poll, not the clock, is shortened
    root = project(tmp_path, seconds=0.6)
    progress = Recorder()
    report = project_inspector(tmp_path, replays_per_claim=1).inspect(
        [executed('slow')], str(root), {'task_id': 't', 'attempt': 1}, progress=progress)
    finding = report['findings'][0]
    assert finding['state'] == 'checked', finding
    assert finding['check_id'] == 'slow' and finding['observed_exits'] == [0]
    assert progress.stages[0] == 'replay_start' and progress.stages[-1] == 'replay_end'
    assert progress.count('replay_wait') >= 2, 'the owner had its turn while the host check ran'


def test_the_profile_route_starts_no_further_check_after_the_owner_is_lost(tmp_path, monkeypatch):
    root = project(tmp_path)
    doc = document([project_check('first', 'slow'), project_check('second', 'slow')])
    spawned, capture = [], pe._capture

    def recorded(argv, *args, **kwargs):
        spawned.append(argv)
        return capture(argv, *args, **kwargs)
    monkeypatch.setattr(pe, '_capture', recorded)
    progress = Recorder(refuse_at='replay_start', after=1)  # INJECTED loss between the two host checks
    with pytest.raises(ContractError, match=LOST):
        project_inspector(tmp_path, doc, replays_per_claim=1).inspect(
            [executed('first'), executed('second')], str(root), {'task_id': 't', 'attempt': 1}, progress=progress)
    assert len(spawned) == 1, 'the second host check never started'


def test_a_refusal_during_a_profile_check_is_never_swallowed_into_a_state(tmp_path, monkeypatch):
    """A cancelled profile check is not classified: nothing returns, whatever the profile says."""
    monkeypatch.setattr(ei, 'POLL_SECONDS', 0.05)
    root = project(tmp_path, seconds=30)
    progress = Recorder(refuse_at='replay_wait')
    started = time.monotonic()
    with pytest.raises(ContractError, match=LOST):
        project_inspector(tmp_path, replays_per_claim=1).inspect(
            [executed('slow')], str(root), {'task_id': 't', 'attempt': 1}, progress=progress)
    assert time.monotonic() - started < 25, 'the lost owner stopped waiting for a 30-second host check'


def test_the_ledger_hands_the_callback_and_the_fence_to_the_profile_route(tmp_path):
    """R1 and R2 together on the profile route: the adapter declares the callback, so the ledger gives
    it one, and the caller's transaction guard fences both of that ledger's transactions."""
    root = project(tmp_path)
    store, workflow, lease = leased()
    assert forwards_progress(ProjectEvidenceInspector.inspect), 'the profile adapter declares the check'
    progress, fences = Recorder(), []

    def guard(tx):
        fences.append('fenced')
        return workflow._owned(tx, lease)
    row = EvidenceInspections(store, project_inspector(tmp_path, replays_per_claim=1)).inspect(
        lease, {'revision': 'c' * 40}, [executed('slow')], str(root), progress=progress, guard=guard)
    assert row['verdict'] == 'all_checked', row['findings']
    assert progress.stages[0] == 'inspection_start' and progress.stages[-1] == 'inspection_end'
    assert progress.count('replay_start') == progress.count('replay_end') == 1
    assert len(fences) == 2, 'the cache read and the publication are both fenced'
    assert row['context']['project_digest'] == row['inspector']['project']['digest'], 'the profile identity is unchanged'


def test_every_boundary_forces_a_fresh_read_and_only_the_poll_is_throttled():
    """R2: the cadence is for the polls of one wait. A boundary re-reads ownership whatever it says."""
    store, workflow, lease = leased()
    now = [1000.0]
    progress = LeaseProgress(workflow, lease, clock=lambda: now[0])
    assert (progress.check_seconds, progress.renew_seconds) == (5.0, 20.0), 'the default cadence, unchanged'
    for stage in ('inspection_start', 'replay_start', 'replay_end', 'inspection_end'):
        now[0] += 0.1  # every boundary is well inside the five-second window
        progress(stage)
    assert progress.checks == 4, 'no boundary reads a verdict the cadence cached'
    assert progress.renewals == 1, 'renewal keeps its own cadence; nothing lengthens the lease'
    now[0] += 0.1
    progress('replay_wait')
    assert progress.checks == 4, 'the intermediate polls are the only throttled checks'
    assert progress.refusal is None


def test_a_takeover_inside_the_default_cadence_window_still_refuses_at_the_next_boundary():
    store, workflow, lease = leased()
    now = [1000.0]
    progress = LeaseProgress(workflow, lease, clock=lambda: now[0])  # the DEFAULT five-second cadence
    progress('inspection_start')
    taken_over(store, lease)  # INJECTED 1.5s after that check: inside the window the old code trusted
    now[0] = 1001.5
    progress('replay_wait')
    assert progress.checks == 1 and progress.refusal is None, 'an intermediate poll is still throttled'
    with pytest.raises(ContractError, match=LOST):
        progress('replay_start')
    assert progress.checks == 1 and progress.refusal is not None, 'the boundary read refused the stale owner'


def test_ownership_lost_before_publication_writes_neither_a_row_nor_a_recording_notice(tmp_path):
    """R2: the guard runs in the write transaction itself, so the last moment is covered too - and a
    lost lease is not a failure of the ledger, so it never becomes an inspection-recording notice."""
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    store, workflow, lease = leased()

    def guard(tx):
        return workflow._owned(tx, lease)

    def losing(stage=None):  # INJECTED once the replays are done and the row is not yet written
        if stage == 'inspection_end':
            taken_over(store, lease)
    with pytest.raises(ContractError, match=LOST):
        EvidenceInspections(store, inspector(tmp_path, replays_per_claim=1)).inspect(
            lease, {'revision': 'c' * 40}, [command('import sys; sys.exit(0)')], workspace,
            progress=losing, guard=guard)
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [], 'a stale owner publishes no inspection'
        assert tx.scan(NOTICES) == [], 'and its refusal is not recorded as a recording failure'


class CountingStore:
    """Counts the ledger's OWN transactions: the guard must use the one it is handed, never open one."""

    def __init__(self, inner):
        self.inner, self.transactions = inner, 0

    def transaction(self):
        self.transactions += 1
        return self.inner.transaction()


def test_a_cache_hit_is_fenced_and_the_guard_opens_no_transaction_of_its_own(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    store, workflow, lease = leased()
    counting = CountingStore(store)
    insp, inspected = inspector(tmp_path, replays_per_claim=1), []
    real = insp.inspect
    insp.inspect = lambda *a, **k: (inspected.append(True), real(*a, **k))[1]
    inspections = EvidenceInspections(counting, insp)
    candidate, claims = {'revision': 'c' * 40}, [command('import sys; sys.exit(0)')]

    def guard(tx):
        return workflow._owned(tx, lease)
    row = inspections.inspect(lease, candidate, claims, workspace, guard=guard)
    assert row['verdict'] == 'all_checked'
    assert counting.transactions == 2, 'one read and one write, exactly as a guardless caller makes'
    assert inspections.inspect(lease, candidate, claims, workspace, guard=guard) == row, 'a live owner reads its cache'
    assert len(inspected) == 1, 'the second call was the cached row'
    taken_over(store, lease)
    with pytest.raises(ContractError, match=LOST):
        inspections.inspect(lease, candidate, claims, workspace, guard=guard)
    assert len(inspected) == 1, 'the stale owner never reached the inspector'
    assert inspections.inspect(lease, candidate, claims, workspace) == row, 'a caller without a guard keeps its contract'


def test_the_executor_always_supplies_its_own_ownership_guard_to_the_ledger(tmp_path, monkeypatch):
    """Production route: the executor's guard is this lease's own `_owned`, taken in the ledger's
    transaction. A legacy caller may omit one; the executor never does."""
    store, workflow, lease = leased()
    executor = executor_with(tmp_path, store)
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    executor.evidence = EvidenceInspections(store, inspector(tmp_path, replays_per_claim=1))
    guards, real = [], EvidenceInspections.inspect
    monkeypatch.setattr(EvidenceInspections, 'inspect',
                        lambda self, *a, **k: (guards.append(k.get('guard')), real(self, *a, **k))[1])
    result = {'candidate': {'revision': 'c' * 40}, 'tests': [f'{PY} -c "import sys; sys.exit(0)"'],
              'execution_ref': None}
    assert executor._inspect_evidence(lease, result, str(workspace))['verdict'] == 'all_checked'
    guard = guards[0]
    with store.transaction() as tx:
        assert guard(tx)['id'] == lease['id'], 'it reads this very execution, in the transaction it is given'
    taken_over(store, lease)
    with store.transaction() as tx:
        with pytest.raises(ContractError, match=LOST):
            guard(tx)


def test_the_executor_publishes_nothing_when_the_lease_ends_after_the_last_boundary(tmp_path, monkeypatch):
    """The gap only the transaction fence can close: the takeover is INJECTED after the inspection-end
    boundary check, while the row is being built, so the write transaction is the one that refuses."""
    store, workflow, lease = leased()
    executor = executor_with(tmp_path, store)
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    executor.evidence = EvidenceInspections(store, inspector(tmp_path, replays_per_claim=1))
    recorded_at = ledger.utcnow
    monkeypatch.setattr(ledger, 'utcnow', lambda: (taken_over(store, lease), recorded_at())[1])
    result = {'candidate': {'revision': 'c' * 40}, 'tests': [f'{PY} -c "import sys; sys.exit(0)"'],
              'execution_ref': None}
    with pytest.raises(ContractError, match=LOST):
        executor._inspect_evidence(lease, result, str(workspace))
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [] and tx.scan(NOTICES) == [], 'no verdict and no notice from a stale owner'


def test_the_callback_is_a_parameter_of_every_hop_and_never_module_or_instance_state():
    """No mutable global callback and no detached renewer: each hop declares `progress` per call, its
    default is None, and the executor keeps the cadence the provider path already uses."""
    for call in (ei.EvidenceInspector.inspect, ei.EvidenceInspector.inspect_command, ei.EvidenceInspector._replay,
                 ei._capture, EvidenceInspections.inspect, ie.DockerEvidenceInspector._replay,
                 pe.ProjectEvidenceInspector.inspect, pe.ProjectEvidenceInspector._check):
        parameter = signature(call).parameters['progress']
        assert parameter.default is None, call
    assert signature(EvidenceInspections.inspect).parameters['guard'].default is None, 'the fence is per call too'
    assert not [name for name in vars(pe) if 'progress' in name.lower()], 'no module-level callback to share'
    assert not [name for name in vars(ei) if 'progress' in name.lower()], 'no module-level callback to share'
    insp = EvidenceInspector(FileArtifacts('unused'))
    assert not [name for name in vars(insp) if 'progress' in name.lower()], 'nothing is stored on the inspector'
    assert ex.LeaseProgress.CHECK_SECONDS == ex.LEASE_CHECK_SECONDS == 5.0
    assert ex.LeaseProgress.RENEW_SECONDS == ex.LEASE_RENEW_SECONDS == 20.0
