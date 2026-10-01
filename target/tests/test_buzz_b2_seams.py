"""Buzz Batch B2: the coordination seams `cancel_in` / `set_paused_in` and the P2 pause-authority version.

Contracts: Buzz DESIGN v3 §4.3 (refusal codes) and §5 P2, DESIGN-B §5 D-B2-1 (the version lives in its OWN
`fleet_control/authority_version` record; the `admission` row is never given a version field).
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "ported"))
from m7_coordination import Fleet, Workflow, organization  # noqa: E402
from test_fleet import config  # noqa: E402
from test_workflow import assignment  # noqa: E402

from codex_harness.coordination.application.fleet import state  # noqa: E402
from codex_harness.coordination.application.fleet.pause import FleetPause  # noqa: E402
from codex_harness.coordination.application.messages import TaskRefused  # noqa: E402
from codex_harness.coordination.domain import remote_control as rc  # noqa: E402
from codex_harness.coordination.domain.fleet import FleetRefused  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

VERSION = ("fleet_control", "authority_version")


def registered(tmp_path):
    store = MemoryStore()
    Fleet(store).register(config(tmp_path))
    return store, FleetPause(store)


def records(store):
    with store.transaction() as tx:
        return tx.records()


def snapshot(store):
    return {(r["bucket"], r["id"]): r["body"] for r in records(store)}


def version(store):
    with store.transaction() as tx:
        return state.control_version(tx)


def set_in(store, pause, paused, **kw):
    with store.transaction() as tx:
        return pause.set_paused_in(tx, paused, **kw)


# ---- the P2 version record -------------------------------------------------------------------------------------
def test_an_absent_version_record_reads_zero_and_registration_does_not_write_it(tmp_path):
    store, _ = registered(tmp_path)
    assert version(store) == 0 and VERSION not in snapshot(store)


def test_each_authority_change_adds_one_and_the_default_row_stays_without_a_version(tmp_path):
    store, pause = registered(tmp_path)
    pause.pause()
    assert snapshot(store)[VERSION] == {"control_version": 1}
    pause.resume()
    assert version(store) == 2
    pause.activation_gate("target-1", "d" * 64)  # creates a hold
    assert version(store) == 3
    pause.activation_gate("target-1", "e" * 64)  # replaces the same target's hold
    assert version(store) == 4
    assert pause.release_activation_hold("f" * 64) == {"released": False} and version(store) == 4
    assert pause.release_activation_hold("e" * 64) == {"released": True} and version(store) == 5
    assert all("control_version" not in body for key, body in snapshot(store).items() if key[1] == "admission")


def test_an_owner_pause_kept_by_the_gate_changes_nothing_and_a_budget_grant_keeps_the_version(tmp_path):
    store, pause = registered(tmp_path)
    pause.pause()
    pause.activation_gate("target-1", "d" * 64)  # not `ours` (owner pause, no matching hold): not a change
    assert version(store) == 1
    before = snapshot(store)[VERSION]
    pause.authorize_budget(5, 9, 8)
    assert snapshot(store)[VERSION] == before


def test_the_version_is_the_calling_transactions_and_a_rollback_leaves_nothing(tmp_path):
    store, pause = registered(tmp_path)
    before = snapshot(store)
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            pause.set_paused_in(tx, True, expected_control={"paused": False, "version": 0})
            raise RuntimeError("abort")
    assert snapshot(store) == before and version(store) == 0


# ---- set_paused_in ---------------------------------------------------------------------------------------------
def test_set_paused_in_applies_the_flag_and_bumps(tmp_path):
    store, pause = registered(tmp_path)
    before = snapshot(store)[("fleet_control", "admission")]
    row = set_in(store, pause, True, expected_control={"paused": False, "version": 0})
    after = snapshot(store)
    assert row == after[("fleet_control", "admission")] == {**before, "paused": True, "updated_at": row["updated_at"]}
    assert after[VERSION] == {"control_version": 1}


@pytest.mark.parametrize("expected", [{"paused": True, "version": 0}, {"paused": False, "version": 1},
                                      {"paused": False, "version": 0, }])
def test_set_paused_in_compares_each_field_in_the_transaction(tmp_path, expected):
    store, pause = registered(tmp_path)
    set_in(store, pause, True, expected_control={"paused": False, "version": 0})
    before = snapshot(store)
    with pytest.raises(FleetRefused) as refused:
        set_in(store, pause, True, expected_control=expected)  # the current state is paused / version 1
    assert refused.value.reason_code == rc.STALE_CONTROL and snapshot(store) == before


def test_set_paused_in_refuses_a_resume_over_a_hold_unless_allowed(tmp_path):
    store, pause = registered(tmp_path)
    pause.activation_gate("target-1", "d" * 64)
    held = snapshot(store)
    expected = {"paused": True, "version": 1}
    with pytest.raises(FleetRefused) as refused:
        set_in(store, pause, False, expected_control=expected)
    assert refused.value.reason_code == rc.ACTIVATION_HOLD_PRESENT and snapshot(store) == held
    set_in(store, pause, False, expected_control=expected, allow_hold_release=True)
    row = snapshot(store)[("fleet_control", "admission")]
    assert row["paused"] is False and "activation_hold" not in row and version(store) == 2


def test_set_paused_in_pause_over_a_hold_keeps_the_hold_unless_allowed(tmp_path):
    store, pause = registered(tmp_path)
    pause.activation_gate("target-1", "d" * 64)
    set_in(store, pause, True, expected_control={"paused": True, "version": 1})
    assert "activation_hold" in snapshot(store)[("fleet_control", "admission")]


def test_set_paused_in_refuses_an_unregistered_fleet_and_writes_nothing():
    store = MemoryStore()
    with pytest.raises(FleetRefused):
        set_in(store, FleetPause(store), True, expected_control=None)
    assert snapshot(store) == {}


# ---- the local wrappers are unchanged ---------------------------------------------------------------------------
def test_the_local_pause_and_resume_take_over_a_hold_and_return_the_row(tmp_path):
    store, pause = registered(tmp_path)
    pause.activation_gate("target-1", "d" * 64)
    row = pause.resume()  # an owner resume takes the pause over: the hold never outlives it
    assert row == snapshot(store)[("fleet_control", "admission")]
    assert set(row) == {"paused", "budget", "updated_at"} and row["paused"] is False
    row = pause.pause()
    assert set(row) == {"paused", "budget", "updated_at"} and row["paused"] is True
    assert [k for k in snapshot(store) if k[0] == "fleet_control"] == [
        ("fleet_control", "admission"), VERSION]


# ---- cancel_in -------------------------------------------------------------------------------------------------
def cancel_fixture():
    workflow = Workflow(MemoryStore(), organization())
    task = workflow.submit(assignment())
    return workflow, task


def test_cancel_in_runs_in_the_callers_transaction_and_a_rollback_leaves_nothing():
    workflow, task = cancel_fixture()
    store = workflow.store
    before = records(store)
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            workflow.messages.cancel_in(tx, task["id"], "conductor", "why", expected_generation=task["generation"])
            assert tx.get("tasks", task["id"])["status"] == "cancelled"
            raise RuntimeError("abort")
    assert records(store) == before
    with store.transaction() as tx:
        workflow.messages.cancel_in(tx, task["id"], "conductor", "why", expected_generation=task["generation"])
    with store.transaction() as tx:
        row = tx.get("tasks", task["id"])
    assert row["status"] == "cancelled" and row["generation"] == task["generation"] + 1


def test_cancel_in_refuses_a_stale_generation_and_writes_nothing():
    workflow, task = cancel_fixture()
    before = records(workflow.store)
    with pytest.raises(TaskRefused) as refused:
        with workflow.store.transaction() as tx:
            workflow.messages.cancel_in(tx, task["id"], "conductor", "why", expected_generation=task["generation"] + 1)
    assert refused.value.code == rc.STALE_GENERATION and records(workflow.store) == before


def test_cancel_in_on_a_terminal_task_is_not_applied_and_the_local_cancel_keeps_its_refusal():
    workflow, task = cancel_fixture()
    workflow.cancel(task["id"], "conductor", "first")
    before = records(workflow.store)
    with pytest.raises(TaskRefused) as refused:
        with workflow.store.transaction() as tx:
            workflow.messages.cancel_in(tx, task["id"], "conductor", "again", expected_generation=None)
    assert refused.value.code == rc.NOT_APPLIED and records(workflow.store) == before
    with pytest.raises(ContractError, match="Task already terminal") as local:
        workflow.cancel(task["id"], "conductor", "again")
    assert type(local.value) is ContractError  # the compare golden records the exception type
    assert records(workflow.store) == before


def test_the_local_cancel_effect_is_unchanged():
    workflow, task = cancel_fixture()
    workflow.cancel(task["id"], "conductor", "stop")
    with workflow.store.transaction() as tx:
        row = tx.get("tasks", task["id"])
        notices = tx.scan("execution_notices")
    assert (row["status"], row["error"], row["generation"]) == ("cancelled", "stop", task["generation"] + 1)
    assert notices and not any(r["bucket"] == "fleet_control" for r in records(workflow.store))
    with pytest.raises(ContractError):
        workflow.cancel(task["id"], "intruder", "x")
    with pytest.raises(ContractError):
        workflow.cancel("missing", "conductor", "x")


# ---- single-writer scan (P2) -----------------------------------------------------------------------------------
PACKAGE = Path(__file__).resolve().parents[1] / "src" / "codex_harness" / "coordination"
CONTROL_BUCKETS = {"BUCKET_CONTROL", "FLEET_CONTROL", "fleet_control"}
OWNER_PATHS = {"set_paused_in", "activation_gate", "release_activation_hold"}


def _name(node):
    return node.id if isinstance(node, ast.Name) else node.value if isinstance(node, ast.Constant) else None


def _walk(tree):
    """Yield (call, enclosing function name) for every Call in the module."""
    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            if isinstance(child, ast.Call):
                yield child, owner
            yield from visit(child, inner)
    yield from visit(tree, None)


def _scan():
    bumps, version_writers, control_puts = [], [], []
    for path in sorted(PACKAGE.rglob("*.py")):
        for call, owner in _walk(ast.parse(path.read_text())):
            func = call.func
            fname = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if fname == "bump_control_version":
                bumps.append((path.name, owner))
            if fname == "put" and call.args:
                names = [_name(a) for a in call.args[:2]]
                if "AUTHORITY_VERSION_KEY" in names or "authority_version" in names:
                    version_writers.append((path.name, owner))
                if names and names[0] in CONTROL_BUCKETS:
                    consts = {n.value for a in call.args[2:] for n in ast.walk(a) if isinstance(n, ast.Constant)}
                    keys = {n.arg for a in call.args[2:] for n in ast.walk(a) if isinstance(n, ast.keyword)}
                    control_puts.append((path.name, owner, names[1] if len(names) > 1 else None,
                                         "control_version" in consts | keys))
    return bumps, version_writers, control_puts


def test_the_bump_helper_is_the_only_version_writer_and_only_the_three_owner_paths_call_it():
    bumps, writers, _ = _scan()
    assert writers == [("state.py", "bump_control_version")]
    assert sorted(bumps) == sorted([("pause.py", name) for name in OWNER_PATHS])


def test_no_control_row_write_adds_a_control_version_field():
    _, _, puts = _scan()
    assert puts, "the scan must find the control writes"
    for filename, owner, key, has_field in puts:
        assert key == "AUTHORITY_VERSION_KEY" or not has_field, (filename, owner)
        assert key in {"CONTROL_KEY", "AUTHORITY_VERSION_KEY"}, (filename, owner, key)
    assert {(f, o) for f, o, k, _ in puts if k == "CONTROL_KEY"} == {
        ("pause.py", "set_paused_in"), ("pause.py", "activation_gate"), ("pause.py", "release_activation_hold"),
        ("pause.py", "authorize_budget"), ("registry.py", "register")}
    assert {(f, o) for f, o, k, _ in puts if k == "AUTHORITY_VERSION_KEY"} == {("state.py", "bump_control_version")}
