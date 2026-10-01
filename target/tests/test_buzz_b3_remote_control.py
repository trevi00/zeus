"""Buzz Batch B3: `RemoteControl.admit` (admission, binding, transitions) over MemoryStore and doubles.

Contracts: Buzz DESIGN v3 §4.3/§4.4, §6.2.3, §6.4, §6.5; DESIGN-B §6 readings R1-R10. Test names carry the design §9
row-B matrix number (m1..m12).
"""
import ast
import json
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "ported"))
from m7_coordination import Fleet, Workflow, organization  # noqa: E402
from test_fleet import config  # noqa: E402
from test_workflow import assignment  # noqa: E402

from codex_harness.coordination.application.bridge_lease import LOST, BridgeLease  # noqa: E402
from codex_harness.coordination.application.fleet import state  # noqa: E402
from codex_harness.coordination.application.fleet.pause import FleetPause  # noqa: E402
from codex_harness.coordination.application.remote_control import RemoteControl  # noqa: E402
from codex_harness.coordination.application.remote_inbox import RemoteInbox  # noqa: E402
from codex_harness.coordination.domain import remote_control as rc  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.observation.application.buzz_inbound import InboundPass  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

NOW = 1_700_000_000
OWNER, STRANGER = "a" * 64, "b" * 64
CHANNEL = "c1"
ADMITTED, REFUSED = "command_admitted", "command_refused"


def cid(n=1):
    return str(uuid.UUID(int=(n << 8) | (4 << 76) | (2 << 62)))  # a canonical uuid v4


def fence(command):
    return "```zeus:command\n" + json.dumps(command) + "\n```"


def command(op="cancel_task", n=1, created_at=NOW, **fields):
    base = {"schema": "urn:zeus:buzz-command:1", "command_id": cid(n), "op": op, "task_id": None,
            "expected_generation": None, "expected_control": None, "reason": "operator asked", "desk": None,
            "issued_at": datetime.fromtimestamp(created_at, timezone.utc).isoformat()}
    return {**base, **fields}


def inbox_row(content, n=1, created_at=NOW, received_at=NOW, author=OWNER):
    event_id = f"{n:064x}"
    event = {"id": event_id, "pubkey": author, "created_at": created_at, "kind": 9, "content": content,
             "tags": [["h", CHANNEL]]}
    return {"id": event_id, "event_id": event_id, "author": author, "created_at": created_at,
            "received_at": received_at, "channel": CHANNEL, "state": "pending", "outcome": None, "event": event}


class World:
    def __init__(self, tmp_path, messages=None, store=None, fence_open=True):
        self.store = store or MemoryStore()
        self.workflow = Workflow(self.store, organization())
        self.task = self.workflow.submit(assignment())
        Fleet(self.store).register(config(tmp_path))
        self.pause, self.lease, self.now = FleetPause(self.store), BridgeLease(), NOW
        with self.store.transaction() as tx:
            self.generation = self.lease.acquire(tx, "bridge-1", NOW, 600)
        self.messages = messages or self.workflow.messages
        self.remote = RemoteControl(self.store, self.messages, self.pause, self.lease, [OWNER], lambda: self.now)

    def admit(self, row, generation=None):
        return self.remote.admit(row, self.generation if generation is None else generation)

    def cancel_cmd(self, n=1, **fields):
        fields.setdefault("task_id", self.task["id"])
        fields.setdefault("expected_generation", self.task["generation"])
        op = fields.pop("op", "cancel_task")
        return command(op, n, **fields)

    def snapshot(self):
        with self.store.transaction() as tx:
            return {(r["bucket"], r["id"]): r["body"] for r in tx.records()}

    def bucket(self, name):
        with self.store.transaction() as tx:
            return tx.scan(name)

    def get(self, bucket, key):
        with self.store.transaction() as tx:
            return tx.get(bucket, key)

    def task_row(self):
        return self.get("tasks", self.task["id"])

    def version(self):
        with self.store.transaction() as tx:
            return state.control_version(tx)

    def control(self):
        return self.get("fleet_control", "admission")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def result(outcome, n, disposition, reason_code=None):
    return {"outcome": outcome, "command_id": cid(n), "disposition": disposition, "reason_code": reason_code}


# ---- m1 normal -------------------------------------------------------------------------------------------------
def test_m1_cancel_is_effect_done_with_generation_after_and_transition_r1(w):
    generation = w.task["generation"]
    assert w.admit(inbox_row(fence(w.cancel_cmd()))) == result(ADMITTED, 1, "effect_done")
    row = w.task_row()
    assert (row["status"], row["error"], row["generation"]) == ("cancelled", "operator asked", generation + 1)
    [transition] = w.bucket("remote_command_transitions")
    assert transition == {"id": f"{cid(1)}:1", "command_id": cid(1), "command_event_id": f"{1:064x}",
                          "transition_revision": 1, "disposition": "effect_done", "reason_code": None,
                          "task_id": w.task["id"], "generation_after": generation + 1, "work": None, "at": NOW}
    [binding] = w.bucket("remote_commands")
    assert binding["event_id"] == f"{1:064x}" and binding["op"] == "cancel_task" and binding["transition_revision"] == 1
    assert binding["aliases"] == [] and binding["conflicts"] == [] and binding["work"] is None
    assert binding["args"]["task_id"] == w.task["id"] and binding["created_at"] == NOW and binding["received_at"] == NOW


def test_m1_pause_then_resume_are_effect_done_and_each_adds_one_to_the_version(w):
    pause = command("pause_fleet", 1, expected_control={"paused": False, "version": 0})
    assert w.admit(inbox_row(fence(pause), 1)) == result(ADMITTED, 1, "effect_done")
    assert w.control()["paused"] is True and w.version() == 1
    resume = command("resume_fleet", 2, expected_control={"paused": True, "version": 1})
    assert w.admit(inbox_row(fence(resume), 2)) == result(ADMITTED, 2, "effect_done")
    assert w.control()["paused"] is False and w.version() == 2
    transitions = w.bucket("remote_command_transitions")
    assert [(t["id"], t["disposition"], t["task_id"], t["generation_after"]) for t in transitions] == [
        (f"{cid(1)}:1", "effect_done", None, None), (f"{cid(2)}:1", "effect_done", None, None)]


# ---- m2 denied author (R10) ------------------------------------------------------------------------------------
def test_m2_a_non_owner_is_ignored_with_no_binding_and_no_effect(w):
    before = w.snapshot()
    out = w.admit(inbox_row(fence(w.cancel_cmd()), author=STRANGER))
    assert out == {"outcome": "ignored_not_owner", "command_id": None, "disposition": None, "reason_code": None}
    assert w.snapshot() == before


# ---- m3 malformed / unknown version (R3) -----------------------------------------------------------------------
@pytest.mark.parametrize("fields,code", [({"schema": "urn:zeus:buzz-command:2"}, rc.UNSUPPORTED_VERSION),
                                         ({"op": "nope"}, rc.INVALID_COMMAND),
                                         ({"reason": "x" * 501}, rc.INVALID_COMMAND)])
def test_m3_an_extractable_unbound_id_is_bound_refused_at_revision_1(w, fields, code):
    before_task = w.task_row()
    out = w.admit(inbox_row(fence(w.cancel_cmd(**fields))))
    assert out == result(REFUSED, 1, "refused", code)
    [binding] = w.bucket("remote_commands")
    assert binding["disposition"] == "refused" and binding["reason_code"] == code and binding["args"] == {}
    [transition] = w.bucket("remote_command_transitions")
    assert transition["transition_revision"] == 1 and transition["task_id"] is None
    assert w.task_row() == before_task


@pytest.mark.parametrize("content", ["no fence at all", fence({"schema": "urn:zeus:buzz-command:1"}),
                                     fence(command(command_id="not-a-uuid")),
                                     "```zeus:command\n{broken\n```"])
def test_m3_without_an_extractable_id_nothing_is_bound(w, content):
    before = w.snapshot()
    out = w.admit(inbox_row(content))
    assert out["outcome"] == REFUSED and out["command_id"] is None and out["disposition"] is None
    assert out["reason_code"] == rc.INVALID_COMMAND
    assert w.snapshot() == before


def test_m3_an_already_bound_id_in_a_malformed_event_leaves_the_binding_untouched(w):
    assert w.admit(inbox_row(fence(w.cancel_cmd()), 1))["disposition"] == "effect_done"
    before = w.snapshot()
    out = w.admit(inbox_row(fence(w.cancel_cmd(op="nope")), 2))
    assert out == {"outcome": REFUSED, "command_id": cid(1), "disposition": None, "reason_code": rc.INVALID_COMMAND}
    assert w.snapshot() == before


# ---- m4 stale state ---------------------------------------------------------------------------------------------
def test_m4_a_stale_generation_binds_stale_generation_and_cancels_nothing(w):
    out = w.admit(inbox_row(fence(w.cancel_cmd(expected_generation=w.task["generation"] + 1))))
    assert out == result(REFUSED, 1, "refused", rc.STALE_GENERATION)
    assert w.task_row()["status"] != "cancelled"
    [transition] = w.bucket("remote_command_transitions")
    assert transition["disposition"] == "refused" and transition["task_id"] == w.task["id"]
    assert transition["generation_after"] is None


def test_m4_an_unknown_task_and_an_empty_reason_are_bound_refusals(w):
    assert w.admit(inbox_row(fence(w.cancel_cmd(1, task_id="missing")), 1)) == result(
        REFUSED, 1, "refused", rc.TASK_UNKNOWN)
    assert w.admit(inbox_row(fence(w.cancel_cmd(2, reason="")), 2)) == result(
        REFUSED, 2, "refused", rc.INVALID_COMMAND)  # R8: before the seam
    assert w.task_row()["status"] != "cancelled"


def test_m4_a_terminal_task_is_not_applied(w):
    w.workflow.cancel(w.task["id"], "conductor", "first")
    out = w.admit(inbox_row(fence(w.cancel_cmd(expected_generation=w.task_row()["generation"]))))
    assert out == result(REFUSED, 1, "refused", rc.NOT_APPLIED)


@pytest.mark.parametrize("expected", [{"paused": True, "version": 0}, {"paused": False, "version": 1}])
def test_m4_stale_control_in_either_field_is_refused_and_changes_nothing(w, expected):
    before = w.control(), w.version()
    out = w.admit(inbox_row(fence(command("pause_fleet", 1, expected_control=expected))))
    assert out == result(REFUSED, 1, "refused", rc.STALE_CONTROL)
    assert (w.control(), w.version()) == before


def test_m4_a_remote_resume_over_an_activation_hold_is_refused_and_the_hold_stays(w):
    w.pause.activation_gate("target-1", "d" * 64)
    before = w.control()
    assert "activation_hold" in before and w.version() == 1
    out = w.admit(inbox_row(fence(command("resume_fleet", 1, expected_control={"paused": True, "version": 1}))))
    assert out == result(REFUSED, 1, "refused", rc.ACTIVATION_HOLD_PRESENT)
    assert w.control() == before and w.version() == 1


# ---- m5 expiry --------------------------------------------------------------------------------------------------
def test_m5_exactly_600_seconds_is_admitted_and_601_is_refused_and_bound(w):
    assert w.admit(inbox_row(fence(w.cancel_cmd(1)), 1, received_at=NOW + 600)) == result(ADMITTED, 1, "effect_done")
    other = second_task(w)
    out = w.admit(inbox_row(fence(command("cancel_task", 2, task_id=other["id"],
                                          expected_generation=other["generation"])), 2, received_at=NOW + 601))
    assert out == result(REFUSED, 2, "refused", rc.COMMAND_EXPIRED)
    assert w.get("tasks", other["id"])["status"] != "cancelled"
    assert w.get("remote_commands", cid(2))["disposition"] == "refused"


def second_task(w):
    return w.workflow.submit(assignment("implement-second"))


# ---- m6 replay --------------------------------------------------------------------------------------------------
def test_m6_the_same_event_replays_the_identical_result_without_a_new_transition(w):
    row = inbox_row(fence(w.cancel_cmd()))
    first = w.admit(row)
    before = w.snapshot()
    assert w.admit(row) == first
    assert w.snapshot() == before and len(w.bucket("remote_command_transitions")) == 1


def test_m6_the_same_command_under_another_event_is_an_alias_with_no_second_effect(w):
    content = fence(w.cancel_cmd())
    first = w.admit(inbox_row(content, 1))
    generation = w.task_row()["generation"]
    again = w.admit(inbox_row(content, 2, received_at=NOW + 5))
    assert again == first == result(ADMITTED, 1, "effect_done")
    assert w.task_row()["generation"] == generation and len(w.bucket("remote_command_transitions")) == 1
    [binding] = w.bucket("remote_commands")
    assert binding["event_id"] == f"{1:064x}" and binding["aliases"] == [
        {"event_id": f"{2:064x}", "received_at": NOW + 5}]
    w.admit(inbox_row(content, 2, received_at=NOW + 5))  # the alias itself replays without a second entry
    assert len(w.bucket("remote_commands")[0]["aliases"]) == 1


def test_m6_different_content_under_the_same_id_is_a_conflict_with_the_original_untouched(w):
    w.admit(inbox_row(fence(w.cancel_cmd()), 1))
    [original] = w.bucket("remote_commands")
    transitions = w.bucket("remote_command_transitions")
    other = fence(w.cancel_cmd(reason="a different reason"))
    out = w.admit(inbox_row(other, 2))
    assert out == {"outcome": REFUSED, "command_id": cid(1), "disposition": None, "reason_code": rc.COMMAND_CONFLICT}
    [after] = w.bucket("remote_commands")
    assert {k: v for k, v in after.items() if k != "conflicts"} == {k: v for k, v in original.items() if k != "conflicts"}
    assert after["conflicts"] == [{"event_id": f"{2:064x}", "digest": rc.command_digest(json.loads(
        other.split("\n")[1]))}]
    assert w.bucket("remote_command_transitions") == transitions
    assert w.admit(inbox_row(other, 2)) == out and len(w.bucket("remote_commands")[0]["conflicts"]) == 1


def test_m6_a_terminal_replay_after_more_than_600_seconds_returns_the_bound_result(w):
    content = fence(w.cancel_cmd())
    w.admit(inbox_row(content, 1))
    assert w.admit(inbox_row(content, 2, received_at=NOW + 5000)) == result(ADMITTED, 1, "effect_done")
    assert w.admit(inbox_row(content, 1, received_at=NOW + 9000)) == result(ADMITTED, 1, "effect_done")
    refused = fence(w.cancel_cmd(2, expected_generation=99))
    assert w.admit(inbox_row(refused, 3)) == result(REFUSED, 2, "refused", rc.STALE_GENERATION)
    assert w.admit(inbox_row(refused, 4, received_at=NOW + 5000)) == result(REFUSED, 2, "refused", rc.STALE_GENERATION)
    assert len(w.bucket("remote_command_transitions")) == 2


# ---- m7 crash / atomicity (R6) ---------------------------------------------------------------------------------
class CrashAfterEffect:
    """The real cancel seam, then an exception before the transaction commits."""

    def __init__(self, real):
        self.real, self.armed = real, True

    def cancel_in(self, tx, *args, **kwargs):
        self.real.cancel_in(tx, *args, **kwargs)
        if self.armed:
            raise RuntimeError("crash after the effect")


def test_m7_an_exception_after_the_effect_commits_nothing_and_the_settle_writes_not_applied(tmp_path):
    w = World(tmp_path)
    w.remote.messages = CrashAfterEffect(w.workflow.messages)
    generation = w.task_row()["generation"]
    out = w.admit(inbox_row(fence(w.cancel_cmd())))
    assert out == result(REFUSED, 1, "refused", rc.NOT_APPLIED)
    row = w.task_row()
    assert row["status"] != "cancelled" and row["generation"] == generation  # no effect
    [binding] = w.bucket("remote_commands")
    assert (binding["disposition"], binding["reason_code"]) == ("refused", rc.NOT_APPLIED)
    [transition] = w.bucket("remote_command_transitions")
    assert (transition["transition_revision"], transition["disposition"]) == (1, "refused")
    assert w.admit(inbox_row(fence(w.cancel_cmd()))) == out  # a later pass replays the bound result


# ---- m8 lost acknowledgement -------------------------------------------------------------------------------------
class LostAck:
    """A store that commits and then raises: the caller cannot tell whether the unit committed."""

    def __init__(self, store):
        self.store, self.armed = store, 0

    @contextmanager
    def transaction(self, *args, **kwargs):
        with self.store.transaction(*args, **kwargs) as tx:
            yield tx
        if self.armed:
            self.armed -= 1
            raise RuntimeError("acknowledgement lost")


def test_m8_a_lost_acknowledgement_settles_to_effect_done_with_the_effect_applied_once(tmp_path):
    w = World(tmp_path)
    generation = w.task_row()["generation"]
    ack = LostAck(w.store)
    w.remote.store = ack
    ack.armed = 1
    out = w.admit(inbox_row(fence(w.cancel_cmd())))
    assert out == result(ADMITTED, 1, "effect_done")
    assert w.task_row()["generation"] == generation + 1 and w.task_row()["status"] == "cancelled"
    assert len(w.bucket("remote_command_transitions")) == 1 and len(w.bucket("execution_notices")) == 1
    assert w.get("remote_commands", cid(1))["disposition"] == "effect_done"


# ---- m9 bridge fence ---------------------------------------------------------------------------------------------
def test_m9_a_stale_generation_commits_nothing_in_the_admission_transaction(w):
    before = w.snapshot()
    with pytest.raises(ContractError, match=LOST):
        w.admit(inbox_row(fence(w.cancel_cmd())), w.generation + 1)
    assert w.snapshot() == before


class FailingAdmission:
    """The admission transaction fails with an unexpected error (so the settle runs)."""

    def cancel_in(self, tx, *args, **kwargs):
        raise RuntimeError("admission failed")


def test_m9_a_stale_generation_commits_nothing_in_the_settle_transaction(tmp_path):
    w = World(tmp_path)
    steal = {"done": False}
    real_require = w.lease.require_current

    class Lease:
        def require_current(self, tx, generation):
            if steal["done"]:
                raise ContractError(LOST)  # the second call (the settle) finds a new generation
            steal["done"] = True
            real_require(tx, generation)

    w.remote.lease = Lease()
    w.remote.messages = FailingAdmission()
    before = w.snapshot()
    with pytest.raises(ContractError, match=LOST):
        w.admit(inbox_row(fence(w.cancel_cmd())))
    assert w.snapshot() == before


def test_m9_an_inbound_pass_with_a_stale_generation_leaves_the_row_pending(tmp_path):
    w = World(tmp_path)
    inbox = RemoteInbox()
    event = inbox_row(fence(w.cancel_cmd()))["event"]
    relay = type("Relay", (), {"query_all": lambda self, f, **k: {"events": [event], "ended": "eose", "pages": 1,
                                                                  "unverified": 0}})()
    sink = admit_outcome(w)
    pass_ = InboundPass(w.store, relay, inbox, w.lease, sink, [OWNER], [CHANNEL], lambda: NOW)
    with w.store.transaction() as tx:
        newer = w.lease.acquire(tx, "bridge-2", NOW + 1000, 600)  # the lease expired: a new bridge fences us out
    assert newer == w.generation + 1
    with pytest.raises(ContractError, match=LOST):
        pass_.run(w.generation)
    assert w.bucket("remote_commands") == [] and w.task_row()["status"] != "cancelled"


# ---- m10 desk (R9) ----------------------------------------------------------------------------------------------
class Raising:
    def __getattr__(self, name):
        raise AssertionError(f"a desk-op admission must not call {name}")


@pytest.mark.parametrize("op,desk", [
    ("desk_open", {"session_id": "s1", "title": "t", "intent": None, "text": None}),
    ("desk_turn", {"session_id": "s1", "title": None, "intent": "consult", "text": "hello"})])
def test_m10_desk_ops_are_refused_desk_not_migrated_without_any_call(tmp_path, op, desk):
    w = World(tmp_path)
    w.remote.messages, w.remote.fleet_pause = Raising(), Raising()
    out = w.admit(inbox_row(fence(command(op, 1, desk=desk))))
    assert out == result(REFUSED, 1, "refused", rc.DESK_NOT_MIGRATED)
    assert w.get("remote_commands", cid(1))["args"]["desk"] == desk


def test_m10_the_module_never_calls_the_desk_port():
    tree = ast.parse((SRC / "coordination/application/remote_control.py").read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"open_session", "submit", "request", "session"}
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and "DeskTurns" in ast.dump(n) for n in ast.walk(tree))


# ---- m11 single writer and DAG ------------------------------------------------------------------------------------
SRC = Path(__file__).resolve().parents[1] / "src" / "codex_harness"


def test_m11_the_two_buckets_are_written_only_by_remote_control():
    writers = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        if re.search(r"""\.put\(\s*(["']remote_command(s|_transitions)["']|COMMANDS|TRANSITIONS)""", text):
            writers.add(path.name)
    assert writers == {"remote_control.py"}
    ports = (SRC / "coordination/ports.py").read_text()
    assert '"remote_commands"' in ports and '"remote_command_transitions"' in ports


# ---- m12 InboundPass + RemoteControl end to end --------------------------------------------------------------------
def admit_outcome(w):
    """The composition's sink: `InboundPass` marks the row processed with the admission's inbox outcome."""
    return lambda row, generation: w.remote.admit(row, generation)["outcome"]


class Relay:
    def __init__(self, events):
        self.events = events

    def query_all(self, filter, **kwargs):  # noqa: A002
        return {"events": list(self.events), "ended": "eose", "pages": 1, "unverified": 0}


def test_m12_an_owner_command_is_admitted_and_the_inbox_row_processed(w):
    event = inbox_row(fence(w.cancel_cmd()))["event"]
    pass_ = InboundPass(w.store, Relay([event]), RemoteInbox(), w.lease, admit_outcome(w), [OWNER], [CHANNEL],
                        lambda: NOW)
    out = pass_.run(w.generation)[CHANNEL]
    assert (out["sunk"], out["sink_failed"]) == (1, 0)
    [inbox] = w.bucket("remote_inbox")
    assert (inbox["state"], inbox["outcome"]) == ("processed", ADMITTED) and "event" in inbox
    assert w.task_row()["status"] == "cancelled" and w.get("remote_commands", cid(1))["disposition"] == "effect_done"


def test_m12_a_sink_exception_leaves_the_row_pending_and_the_next_pass_resumes_it(w):
    event = inbox_row(fence(w.cancel_cmd()))["event"]
    failing = {"on": True}

    def sink(row, generation):
        if failing["on"]:
            raise RuntimeError("sink down")
        return w.remote.admit(row, generation)["outcome"]

    pass_ = InboundPass(w.store, Relay([event]), RemoteInbox(), w.lease, sink, [OWNER], [CHANNEL], lambda: NOW)
    first = pass_.run(w.generation)[CHANNEL]
    assert (first["sunk"], first["sink_failed"]) == (0, 1)
    assert w.bucket("remote_inbox")[0]["state"] == "pending" and w.bucket("remote_commands") == []
    failing["on"] = False
    second = pass_.run(w.generation)[CHANNEL]
    assert (second["sunk"], second["sink_failed"]) == (1, 0)
    assert w.bucket("remote_inbox")[0]["outcome"] == ADMITTED and len(w.bucket("remote_command_transitions")) == 1
