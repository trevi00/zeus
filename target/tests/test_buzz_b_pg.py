"""Buzz B5: the MemoryStore / PostgresStore differential for Batch B (and the Batch A inbox and lease).

Each scenario is one function `scenario(store) -> records`, run once on a fresh `MemoryStore` and once on the
disposable `isolated_pgstore` (`HARNESS_INTEGRATION=1` plus a disposable `ZEUS_TEST_DSN`; skipped otherwise, DESIGN-B §2).
The scenario's own assertions run on BOTH stores, then the two canonical dumps of ALL records
(`sorted([bucket, id, canonical(body)])`) must be EQUAL. The PG risk is semantic drift between the two stores (a row
mutated without `put`, JSON number and tuple/list round trips, key order, absent-row reads), not locking (§2.9).

Determinism, never a masked field: the wall clock, the uuid4 draws, the fleet tokens and the role-key and BIP-340 aux
randomness are pinned for the duration of one run (`pinned`), so two runs on the same store type agree byte for byte.
The scenarios reuse the B2-B4 fixtures (imported, not copied). Scenario a replaces the A3a placeholder
`test_pg_inbox_and_lease_idempotency`.
"""
import hashlib
import secrets
import shutil
import sys
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent / "ported"))
import m7_coordination  # noqa: E402
import test_buzz_b4_projection as b4  # noqa: E402
from m7_coordination import Fleet, Workflow, organization  # noqa: E402
from test_buzz_a3a_inbound import CHANNEL as A3_CHANNEL  # noqa: E402
from test_buzz_a3a_inbound import OWNER as A3_OWNER  # noqa: E402
from test_buzz_a3a_inbound import FakeRelay, Sink, ev  # noqa: E402
from test_buzz_b3_remote_control import (  # noqa: E402
    ADMITTED,
    NOW,
    REFUSED,
    LostAck,
    World,
    cid,
    command,
    fence,
    inbox_row,
    result,
)
from test_fleet import config  # noqa: E402
from test_workflow import assignment  # noqa: E402

from codex_harness.coordination.application.bridge_lease import LOST, BridgeLease  # noqa: E402
from codex_harness.coordination.application.fleet import (  # noqa: E402
    admission,
    pause,
    recovery,
    registry,
    state,
)
from codex_harness.coordination.application.fleet.pause import FleetPause  # noqa: E402
from codex_harness.coordination.application.messages import TaskRefused  # noqa: E402
from codex_harness.coordination.application.remote_inbox import RemoteInbox  # noqa: E402
from codex_harness.coordination.domain import remote_control as rc  # noqa: E402
from codex_harness.coordination.domain.fleet import FleetRefused  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.observation.application.buzz_inbound import InboundPass  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

FIXTURE_ROOT = Path("/fixture")  # the fleet config only names paths; the same names on both stores


# ---- determinism --------------------------------------------------------------------------------------------------
@contextmanager
def pinned():
    """A 1 ms ticking clock, a counting uuid4 and counting random bytes, restarted for every run."""
    counter = {"clock": 0, "uuid": 0, "bytes": 0}
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def tick(self):
        counter["clock"] += 1
        return base + timedelta(milliseconds=counter["clock"])

    def draw(label, size):
        counter[label] += 1
        return hashlib.sha256(f"{label}:{counter[label]}".encode()).digest()[:size]

    def uuid4(self=None):
        return uuid.UUID(bytes=draw("uuid", 16), version=4)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(ids.SystemClock, "now", tick))
        stack.enter_context(mock.patch.object(ids.SystemIds, "uuid4", uuid4))
        for module in (m7_coordination, registry, admission, pause, recovery):
            stack.enter_context(mock.patch.object(module, "uuid4", uuid4))
        stack.enter_context(mock.patch.object(secrets, "token_bytes", lambda n=32: draw("bytes", n).ljust(n, b"\0")))
        yield


def dump(store):
    with store.transaction() as tx:
        records = tx.records()
    return sorted([r["bucket"], r["id"], canonical(r["body"])] for r in records)


def run(scenario, store):
    with pinned():
        scenario(store)
    return dump(store)


def differential(request, scenario):
    """Memory twice (the pin holds), then the disposable PG store: the same dump."""
    memory = run(scenario, MemoryStore())
    assert memory == run(scenario, MemoryStore()), "the scenario is not deterministic on MemoryStore"
    assert memory, "a scenario must write records"
    postgres = run(scenario, request.getfixturevalue("isolated_pgstore"))  # skipped without the integration env
    assert postgres == memory


def snapshot(store):
    return {(r["bucket"], r["id"]): r["body"] for r in store_records(store)}


def store_records(store):
    with store.transaction() as tx:
        return tx.records()


# ---- a. inbox and lease (replaces the A3a placeholder) -------------------------------------------------------------
def scenario_inbox_and_lease(store):
    inbox, lease = RemoteInbox(), BridgeLease()

    def meta(n, author=A3_OWNER, received_at=NOW, **extra):
        return {"event_id": f"{n:064x}", "author": author, "created_at": NOW - n, "received_at": received_at,
                "channel": A3_CHANNEL, **extra}

    def row(n):
        with store.transaction() as tx:
            return tx.get("remote_inbox", f"{n:064x}")

    with store.transaction() as tx:
        generation = lease.acquire(tx, "bridge-1", NOW, 60)
    assert generation == 1

    # insert_pending twice -> duplicate, the row unchanged
    with store.transaction() as tx:
        assert inbox.insert_pending(tx, meta(1, event=ev(1, NOW - 1))) == "inserted"
    first = row(1)
    with store.transaction() as tx:
        assert inbox.insert_pending(tx, meta(1, author="d" * 64, received_at=NOW + 9)) == "duplicate"
    assert row(1) == first and first["state"] == "pending" and first["outcome"] is None and "event" in first

    # mark_processed (a command outcome keeps the event, a no-command one drops it), compact
    for n, author, outcome in ((2, "d" * 64, "ignored_not_owner"), (3, A3_OWNER, "stub_recorded")):
        with store.transaction() as tx:
            inbox.insert_pending(tx, meta(n, author, event=ev(n, NOW - n)))
        with store.transaction() as tx:
            assert inbox.mark_processed(tx, f"{n:064x}", outcome)["state"] == "processed"
    assert "event" not in row(2) and "event" in row(3) and row(3)["outcome"] == "stub_recorded"
    with pytest.raises(ContractError, match="Only a pending"), store.transaction() as tx:
        inbox.mark_processed(tx, f"{2:064x}", "stub_recorded")
    with store.transaction() as tx:  # a no-command row that still carries a body, as an older writer left it
        legacy = tx.get("remote_inbox", f"{2:064x}")
        legacy["event"] = ev(2, NOW - 2)
        tx.put("remote_inbox", legacy["id"], legacy)
    with store.transaction() as tx:
        assert inbox.compact(tx, NOW + 1) == 1
    with store.transaction() as tx:
        assert inbox.compact(tx, NOW + 1) == 0  # idempotent
    assert "event" not in row(2) and row(2)["compacted"] is True and "event" in row(3) and "event" in row(1)
    with store.transaction() as tx:
        assert inbox.insert_pending(tx, meta(2, "e" * 64)) == "duplicate"  # still a duplicate once compacted
        assert [r["event_id"] for r in inbox.pending(tx)] == [f"{1:064x}"]

    # BridgeLease acquire / renew / require_current
    with store.transaction() as tx:
        assert lease.acquire(tx, "bridge-2", NOW + 30, 60) is None  # live: the second bridge stays passive
        assert lease.renew(tx, "bridge-1", generation, NOW + 30, 60) == NOW + 90
        lease.require_current(tx, generation)
    with pytest.raises(ContractError, match=LOST), store.transaction() as tx:
        lease.renew(tx, "bridge-2", generation, NOW + 31, 60)
    with store.transaction() as tx:
        assert lease.acquire(tx, "bridge-2", NOW + 90, 60) == 2  # expired
    for stale in (lambda tx: lease.require_current(tx, generation),
                  lambda tx: lease.renew(tx, "bridge-1", generation, NOW + 100, 60)):
        with pytest.raises(ContractError, match=LOST), store.transaction() as tx:
            stale(tx)
    with store.transaction() as tx:
        lease.require_current(tx, 2)

    # a stale generation's InboundPass transaction commits nothing; the current one processes
    relay, sink = FakeRelay([ev(10, NOW - 10)]), Sink()
    stale_pass = InboundPass(store, relay, inbox, lease, sink, [A3_OWNER], [A3_CHANNEL], lambda: NOW + 100)
    before = dump(store)
    with pytest.raises(ContractError, match=LOST):
        stale_pass.run(generation)
    assert dump(store) == before and relay.queries == [] and sink.seen == []
    # the pending row 1 resumes from its retained event, and the relayed event 10 is inserted and processed
    assert stale_pass.run(2)[A3_CHANNEL]["sunk"] == 2 and sorted(sink.seen) == [ev(1, 0)["id"], ev(10, 0)["id"]]
    assert [(row(n)["state"], row(n)["outcome"]) for n in (1, 10)] == [("processed", "stub_recorded")] * 2


def test_a_inbox_and_lease_differential(request):
    differential(request, scenario_inbox_and_lease)


# ---- b. B2 seams ---------------------------------------------------------------------------------------------------
VERSION = ("fleet_control", "authority_version")


def scenario_b2_seams(store):
    Fleet(store).register(config(FIXTURE_ROOT))
    control = FleetPause(store)
    workflow = Workflow(store, organization())
    task = workflow.submit(assignment())

    def row():
        return snapshot(store)[("fleet_control", "admission")]

    def set_in(paused, **kw):
        with store.transaction() as tx:
            return control.set_paused_in(tx, paused, **kw)

    assert VERSION not in snapshot(store)  # the absent version record reads zero and registration never writes it
    with store.transaction() as tx:
        assert state.control_version(tx) == 0

    # local pause / resume with the hold takeover
    control.activation_gate("target-1", "d" * 64)
    assert "activation_hold" in row() and snapshot(store)[VERSION] == {"control_version": 1}
    resumed = control.resume()  # an owner resume takes the pause over: the hold never outlives it
    assert resumed == row() and resumed["paused"] is False and "activation_hold" not in resumed
    paused = control.pause()
    assert paused == row() and set(paused) == {"paused", "budget", "updated_at"} and paused["paused"] is True
    assert snapshot(store)[VERSION] == {"control_version": 3}

    # set_paused_in: stale_control in either field, activation_hold_present, then the allowed release
    before = snapshot(store)
    for expected in ({"paused": False, "version": 3}, {"paused": True, "version": 2}):
        with pytest.raises(FleetRefused) as refused:
            set_in(True, expected_control=expected)
        assert refused.value.reason_code == rc.STALE_CONTROL and snapshot(store) == before
    set_in(False, expected_control={"paused": True, "version": 3})
    control.activation_gate("target-1", "e" * 64)  # paused again under a hold
    held = snapshot(store)
    assert held[VERSION] == {"control_version": 5} and "activation_hold" in row()
    with pytest.raises(FleetRefused) as refused:
        set_in(False, expected_control={"paused": True, "version": 5})
    assert refused.value.reason_code == rc.ACTIVATION_HOLD_PRESENT and snapshot(store) == held
    set_in(False, expected_control={"paused": True, "version": 5}, allow_hold_release=True)
    assert row()["paused"] is False and "activation_hold" not in row()
    assert snapshot(store)[VERSION] == {"control_version": 6}
    assert all("control_version" not in body for key, body in snapshot(store).items() if key[1] == "admission")

    # cancel_in: stale_generation, then applied, then not_applied
    before = snapshot(store)
    with pytest.raises(TaskRefused) as refused:
        with store.transaction() as tx:
            workflow.messages.cancel_in(tx, task["id"], "conductor", "why", expected_generation=task["generation"] + 1)
    assert refused.value.code == rc.STALE_GENERATION and snapshot(store) == before
    with store.transaction() as tx:
        workflow.messages.cancel_in(tx, task["id"], "conductor", "why", expected_generation=task["generation"])
    with store.transaction() as tx:
        cancelled = tx.get("tasks", task["id"])
    assert (cancelled["status"], cancelled["error"], cancelled["generation"]) == (
        "cancelled", "why", task["generation"] + 1)
    before = snapshot(store)
    with pytest.raises(TaskRefused) as refused:
        with store.transaction() as tx:
            workflow.messages.cancel_in(tx, task["id"], "conductor", "again", expected_generation=None)
    assert refused.value.code == rc.NOT_APPLIED and snapshot(store) == before


def test_b_b2_seams_differential(request):
    differential(request, scenario_b2_seams)


# ---- c. B3 RemoteControl -------------------------------------------------------------------------------------------
def scenario_remote_control(store):
    w = World(FIXTURE_ROOT, store=store)
    inbox = RemoteInbox()

    def deliver(row, generation=None):
        """The bridge's path: the inbox row is retained with its event, admitted, then marked with the outcome."""
        with store.transaction() as tx:
            inbox.insert_pending(tx, {name: row[name] for name in ("event_id", "author", "created_at", "received_at",
                                                                   "channel", "event")})
        out = w.admit(row, generation)
        with store.transaction() as tx:
            current = tx.get("remote_inbox", row["event_id"])
            if current["state"] == "pending":
                inbox.mark_processed(tx, row["event_id"], out["outcome"])
        return out

    second = w.workflow.submit(assignment("implement-second"))
    third = w.workflow.submit(assignment("implement-third"))
    fourth = w.workflow.submit(assignment("implement-fourth"))

    def cancel(n, task, **fields):
        op = fields.pop("op", "cancel_task")
        return command(op, n, task_id=task["id"], expected_generation=task["generation"], **fields)

    # normal cancel, then pause
    generation = w.task["generation"]
    first_row = inbox_row(fence(w.cancel_cmd(1)), 1)
    assert deliver(first_row) == result(ADMITTED, 1, "effect_done")
    assert (w.task_row()["status"], w.task_row()["generation"]) == ("cancelled", generation + 1)
    pause_cmd = command("pause_fleet", 2, expected_control={"paused": False, "version": 0})
    assert deliver(inbox_row(fence(pause_cmd), 2)) == result(ADMITTED, 2, "effect_done")
    assert w.control()["paused"] is True and w.version() == 1

    # replay, alias, conflict
    before = w.snapshot()
    assert deliver(first_row) == result(ADMITTED, 1, "effect_done") and w.snapshot() == before
    assert deliver(inbox_row(fence(w.cancel_cmd(1)), 3, received_at=NOW + 5)) == result(ADMITTED, 1, "effect_done")
    assert w.get("remote_commands", cid(1))["aliases"] == [{"event_id": f"{3:064x}", "received_at": NOW + 5}]
    other = fence(w.cancel_cmd(1, reason="a different reason"))
    out = deliver(inbox_row(other, 4))
    assert out == {"outcome": REFUSED, "command_id": cid(1), "disposition": None, "reason_code": rc.COMMAND_CONFLICT}
    assert [c["event_id"] for c in w.get("remote_commands", cid(1))["conflicts"]] == [f"{4:064x}"]

    # malformed with an extractable id, malformed without one
    assert deliver(inbox_row(fence(cancel(5, second, op="nope")), 5)) == result(
        REFUSED, 5, "refused", rc.INVALID_COMMAND)
    assert w.get("remote_commands", cid(5))["args"] == {} and w.get("tasks", second["id"])["status"] != "cancelled"
    assert deliver(inbox_row("no fence at all", 6))["command_id"] is None

    # expired (601 s), desk refusal, a stale control
    assert deliver(inbox_row(fence(cancel(7, second)), 7, received_at=NOW + 601)) == result(
        REFUSED, 7, "refused", rc.COMMAND_EXPIRED)
    desk = {"session_id": "s1", "title": "t", "intent": None, "text": None}
    assert deliver(inbox_row(fence(command("desk_open", 8, desk=desk)), 8)) == result(
        REFUSED, 8, "refused", rc.DESK_NOT_MIGRATED)
    stale = command("resume_fleet", 9, expected_control={"paused": False, "version": 0})
    assert deliver(inbox_row(fence(stale), 9)) == result(REFUSED, 9, "refused", rc.STALE_CONTROL)

    # a stale fence commits nothing in the admission transaction
    before = w.snapshot()
    with pytest.raises(ContractError, match=LOST):
        w.admit(inbox_row(fence(cancel(10, third)), 10), w.generation + 1)
    assert w.snapshot() == before and w.get("tasks", third["id"])["status"] != "cancelled"

    # R6: a store that commits and then raises; the settle finds the bound effect
    ack = LostAck(store)
    w.remote.store = ack
    ack.armed = 1
    notices = len(w.bucket("execution_notices"))
    assert deliver(inbox_row(fence(cancel(11, fourth)), 11)) == result(ADMITTED, 11, "effect_done")
    assert w.get("tasks", fourth["id"])["status"] == "cancelled"
    assert len(w.bucket("execution_notices")) == notices + 1  # the effect applied once
    assert w.get("remote_commands", cid(11))["disposition"] == "effect_done"
    assert len([t for t in w.bucket("remote_command_transitions") if t["command_id"] == cid(11)]) == 1
    w.remote.store = store

    # the dump covers every bucket this scenario touches
    names = {r["bucket"] for r in store_records(store)}
    assert {"remote_commands", "remote_command_transitions", "remote_inbox", "tasks", "fleet_control",
            "execution_fences"} <= names


def test_c_remote_control_differential(request):
    differential(request, scenario_remote_control)


# ---- d. B4 BuzzProjection ------------------------------------------------------------------------------------------
class StoreWorld(World):
    """The B3 world over the given store: `P` builds `World(tmp_path)`, which would otherwise take a MemoryStore."""

    store_under_test = None

    def __init__(self, tmp_path, **kw):
        super().__init__(tmp_path, store=type(self).store_under_test, **kw)


def scenario_projection(store, keys):
    shutil.rmtree(keys / "keys", ignore_errors=True)  # the same directory names each run (they are in the fleet rows)
    StoreWorld.store_under_test = store
    try:
        with mock.patch.object(b4, "World", StoreWorld):
            p, task_id = b4.cancel_world(keys)
            # a bound root with a card, and the receipt of the cancel transition
            assert p.bind(task_id)["cards"] == 1
            assert [r["subject"] for r in p.rows("receipt:")] == [f"receipt:{cid(1)}:1"]
            assert p.binding(task_id)["canonical_root_event_id"] == p.row(f"root:{task_id}", 1)["event_id"]
            p.deliver()
            assert p.rows("receipt:")[0]["status"] == "acknowledged"
            # coalescing: a changed non-terminal status inside the 2 s makes no version, the next second does
            p.tick(1)
            p.models.views[task_id] = b4.view(task_id, status="blocked", updated_at=p.now)
            counts = p.plan()
            assert (counts["cards"], counts["coalesced"] >= 1) == (0, True)
            p.tick(1)
            assert p.plan()["cards"] == 1 and b4.content(p.row(f"task:{task_id}", 2))["status"] == "blocked"
            p.deliver()
            # the CAS replan: a lost compare-and-set re-plans over the foreign head read by `#d`
            d = b4.lose_the_cas(p)
            foreign = p.relay.heads[d] = p.foreign(d, "update")
            assert p.deliver()["replanned"] == 1
            v3 = p.row("task:t1", 3)
            assert b4.tags(v3, "prev") == [[foreign["id"]]] and p.row("task:t1", 2)["status"] == "superseded"
            assert p.head("task:t1")["condition"] == "foreign_revision_corrected"
            p.relay.script = []
            p.deliver()
            assert p.row("task:t1", 3)["status"] == "acknowledged"
    finally:
        StoreWorld.store_under_test = None


def test_d_projection_differential(request, tmp_path):
    differential(request, lambda store: scenario_projection(store, tmp_path))


# ---- e. B6 F2: the acknowledgement order picks the canonical root -------------------------------------------------
def scenario_root_order(store, keys):
    """Root attempts A (v1) and B (v2) acknowledged B then A at one fixed clock value, before any binding: the
    canonical root is B and A its alias, on both stores (the `ack_seq` ordinal and its counter bucket round-trip)."""
    shutil.rmtree(keys / "keys", ignore_errors=True)
    StoreWorld.store_under_test = store
    try:
        with mock.patch.object(b4, "World", StoreWorld):
            p = b4.P(keys)
            a, b = b4.acknowledge_two_root_attempts(p, "ba")
            b4.reconstructed(p).plan(p.gen)
            binding = p.binding("t1")
            assert binding["canonical_root_event_id"] == b["event_id"] and binding["aliases"] == [a["event_id"]]
            assert (p.row("root:t1", 2)["ack_seq"], p.row("root:t1", 1)["ack_seq"]) == (1, 2)
            assert p.rows(bucket="buzz_outbox_acks") == [{"id": "seq", "seq": 2}]
    finally:
        StoreWorld.store_under_test = None


def test_e_root_order_differential(request, tmp_path):
    differential(request, lambda store: scenario_root_order(store, tmp_path))
