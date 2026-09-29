"""Ported SOURCE M7 suite `tests/test_evidence_lease.py`: ONLY its LeaseProgress and executor cases (S4).

research-dispatch-001: the owner's lease is checked THROUGH the evidence replay, not only before it. The
executor renewed the lease immediately after the provider returned and then replayed the worker's claims
synchronously with no check at all. Every ownership loss below is INJECTED (a second owner writes the row, or the
row is expired by hand), and injected loss is never live recovery evidence; the only clock faked is named as such.

PORTING NOTES (S4 ported executor suites; the M7 assertions are unchanged):
- `LeaseProgress` is `execution.application.lease_progress.LeaseProgress` (M7 `adapters.executor.LeaseProgress`,
  moved unchanged). `leased()` builds its real claimed execution over the target Workflow (`m7_executor.make_workflow`,
  the same composition the executor shim uses) and the target `packaged_organization()`; `assignment()` is copied
  from M7 `tests/test_workflow.py`. The `Executor`/`Harness` of `executor_with` are `m7_executor.Executor`/`Service`.
- Ported and run: the four LeaseProgress cases (cadence/renewal, taken-over or expired refusal, boundary reads,
  takeover inside the cadence window).
- SKIPPED (each carries its owner reason at the top): test_the_executor_stops_a_replay_..., 
  test_the_implement_path_still_inspects_..., test_the_executor_always_supplies_its_own_ownership_guard_...,
  test_the_executor_publishes_nothing_when_the_lease_ends_..., test_the_callback_is_a_parameter_of_every_hop_...:
  S8 evidence inspection. The Executor cases need `EvidenceInspections` and the inspectors; the shim's
  `_inspect_evidence` raises "Evidence inspection is not wired (S8)". Their bodies are kept unchanged, so the
  names that exist only there are unresolved by design (file-level `# ruff: noqa: F821`). The implement case's
  `setup_implementation` fixture (M7 `test_evidence_inspection`, S8's suite) is a local placeholder that skips.

not ported: S8 evidence inspection: the ledger/inspector cases (`EvidenceInspections`, `EvidenceInspector`,
`ProjectEvidenceInspector`: every M7 case of this file that uses none of `LeaseProgress`, `Executor` or
`execute_one`, and the two ledger cases that use only `EvidenceInspections`).
"""
# ruff: noqa: F821
import m7_executor
import pytest

from codex_harness.coordination.application.execution_time import ExecutionTimeError
from codex_harness.execution.application.lease_progress import LeaseProgress
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.kernel.policy import POLICY
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

LOST = 'Stale or expired task execution'


def assignment(action="implement", agent="worker:implementation"):
    parent = packaged_organization().actor(agent).parent
    return envelope("task.assign", parent, agent, action, {"objective": "fixture"}, "test")


@pytest.fixture
def setup_implementation():
    pytest.skip("S8: evidence inspection (M7 tests/test_evidence_inspection.setup_implementation fixture) is not in the target")


def leased(store=None):
    """One real claimed execution; its lease and deadline are the workflow's own."""
    store = store if store is not None else MemoryStore()
    workflow = m7_executor.make_workflow(store)
    workflow.submit(assignment())
    return store, workflow, workflow.claim('worker:implementation', 'owner-1')


def taken_over(store, lease, owner='owner-2'):
    """INJECTED ownership loss: another owner holds the row the caller is still working under."""
    with store.transaction() as tx:
        row = tx.get('tasks', lease['id'])
        tx.put('tasks', lease['id'], {**row, 'lease_owner': owner})


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
    service = m7_executor.Service(store)
    return m7_executor.Executor(service, SimpleNamespace(_git=lambda *a, **k: 'revision', repository=tmp_path),
                    FileArtifacts(str(tmp_path / 'artifacts')))


def test_the_executor_stops_a_replay_whose_execution_was_taken_over_and_publishes_no_verdict(tmp_path, monkeypatch):
    pytest.skip("S8: evidence inspection (M7 adapters.evidence_inspection.ProcessTree replay, application.evidence_inspection.EvidenceInspections) is not in the target")
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
    pytest.skip("S8: evidence inspection (the implement path's M7 Executor._inspect_evidence / EvidenceInspections) is not wired in the target")
    """No-callback compatibility end to end: the same `execute_one` as before, now carrying a live
    per-call check, still records the inspection and succeeds."""
    row = setup_implementation.executor.execute_one('worker:implementation')
    assert row['status'] == 'succeeded', row.get('error')
    inspection = row['result']['evidence_inspection']
    assert inspection['verdict'] == 'incomplete' and inspection['denominator']['checked'] == 1
    with setup_implementation.service.store.transaction() as tx:
        assert [r['id'] for r in tx.scan(BUCKET)] == [inspection['inspection_id']]


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


def test_the_executor_always_supplies_its_own_ownership_guard_to_the_ledger(tmp_path, monkeypatch):
    pytest.skip("S8: evidence inspection (application.evidence_inspection.EvidenceInspections) is not in the target")
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
    pytest.skip("S8: evidence inspection (application.evidence_inspection.EvidenceInspections) is not in the target")
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
    pytest.skip("S8: evidence inspection (adapters.evidence_inspection, isolated_evidence, project_evidence, EvidenceInspections) is not in the target")
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
