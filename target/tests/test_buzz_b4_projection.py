"""Buzz Batch B4: `BuzzProjection` (plan, replan, regenerate) over MemoryStore, the real coordination read functions
and labelled doubles for org/tasks.

Contracts: Buzz DESIGN v3 §4.1-§4.5, §6.1, §6.3; DESIGN-B §7 readings Q1-Q7. Test names carry the design §9 row-B
matrix number (m1..m8).
"""
import ast
import json
import re
import uuid
from pathlib import Path

import pytest

from codex_harness.coordination.domain import remote_control as rc

SRC = Path(__file__).resolve().parents[1] / "src" / "codex_harness"


# ---- item 4: the id rule has one owner (the coordination domain) -------------------------------------------------
from test_buzz_b3_remote_control import NOW, OWNER, World, cid, command, fence, inbox_row  # noqa: E402


@pytest.mark.parametrize("content,expected", [
    (fence({"command_id": cid(1), "op": "nope"}), cid(1)),  # the schema is not this function's business
    (fence({"command_id": cid(1)}) + "\n", cid(1)),
    ("no fence", None),
    (fence({"command_id": cid(1)}) + fence({"command_id": cid(2)}), None),
    (fence({"command_id": "not-a-uuid"}), None),
    (fence({"command_id": cid(10).upper()}), None),  # one spelling per id
    (fence({"command_id": str(uuid.UUID(int=1 << 64 | 1))}), None),  # not version 4
    ("```zeus:command\n{\"command_id\": \"%s\", \"command_id\": \"%s\"}\n```" % (cid(1), cid(2)), None),
    ("```zeus:command\n{\"command_id\": \"%s\", \"x\": NaN}\n```" % cid(1), None),
    ("```zeus:command\n[1]\n```", None),
    ("```zeus:command\n{broken\n```", None),
    (None, None)])
def test_m0_extract_command_id_uses_the_domains_own_rules(content, expected):
    assert rc.extract_command_id(content) == expected


def test_m0_extract_command_id_honours_the_content_bound():
    padding = "x" * rc.MAX_COMMAND_CONTENT_BYTES
    assert rc.extract_command_id(fence({"command_id": cid(1), "p": padding})) is None


def test_m0_the_application_compiles_no_regex_and_defines_no_fence():
    text = (SRC / "coordination/application/remote_control.py").read_text()
    tree = ast.parse(text)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {"re", "json", "uuid"} & imported
    code = [n for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute, ast.Constant))]
    names = {n.id for n in code if isinstance(n, ast.Name)} | {n.attr for n in code if isinstance(n, ast.Attribute)}
    assert not {"re", "_FENCE", "compile", "findall", "fullmatch", "json", "uuid"} & names
    assert "```" not in "".join(n.value for n in code if isinstance(n, ast.Constant) and isinstance(n.value, str)
                                and n.value is not ast.get_docstring(tree, clean=False))
    assert not re.search(r"^\s*_?[A-Z_]*FENCE\w*\s*=", text, re.M)


# ---- Q2: the coordination read functions the projection plans from ------------------------------------------------
from codex_harness.coordination.application.fleet import state  # noqa: E402
from codex_harness.coordination.application.remote_control import transitions_after  # noqa: E402
from codex_harness.coordination.application.remote_inbox import RemoteInbox  # noqa: E402


def read(w, fn, *args):
    with w.store.transaction() as tx:
        return fn(tx, *args)


def admit_via_inbox(w, row):
    """The bridge's path: the inbox row is retained with its event, then admitted."""
    with w.store.transaction() as tx:
        RemoteInbox().insert_pending(tx, {name: row[name] for name in ("event_id", "author", "created_at", "received_at",
                                                                         "channel", "event")})
    return w.admit(row)


def test_q2_transitions_after_is_oldest_first_inclusive_and_enriched(tmp_path):
    w = World(tmp_path)
    admit_via_inbox(w, inbox_row(fence(w.cancel_cmd(1)), 1, received_at=NOW))
    w.now = NOW + 3
    pause = command("pause_fleet", 2, created_at=NOW + 3, expected_control={"paused": False, "version": 0})
    admit_via_inbox(w, inbox_row(fence(pause), 2, created_at=NOW + 3, received_at=NOW + 3))
    rows = read(w, transitions_after, None, 10)
    assert [(r["command_id"], r["at"], r["op"], r["command_author"], r["channel"]) for r in rows] == [
        (cid(1), NOW, "cancel_task", OWNER, "c1"), (cid(2), NOW + 3, "pause_fleet", OWNER, "c1")]
    assert [r["command_id"] for r in read(w, transitions_after, NOW + 3, 10)] == [cid(2)]  # inclusive bound
    assert [r["command_id"] for r in read(w, transitions_after, NOW + 1, 10)] == [cid(2)]
    assert [r["command_id"] for r in read(w, transitions_after, None, 1)] == [cid(1)]
    before = w.snapshot()
    read(w, transitions_after, None, 10)
    assert w.snapshot() == before  # read-only
    for bad in ((-1, 1), (None, 0), (True, 1), (None, True)):
        with pytest.raises(Exception, match="remote control"):
            read(w, transitions_after, *bad)


def test_q2_a_missing_inbox_row_or_binding_enriches_with_none(tmp_path):
    w = World(tmp_path)
    w.admit(inbox_row(fence(w.cancel_cmd(1)), 1))
    row = read(w, transitions_after, None, 1)[0]
    assert row["op"] == "cancel_task"
    with w.store.transaction() as tx:  # the unit of the test only: drop the binding and the inbox row from view
        row = {**tx.get("remote_command_transitions", f"{cid(1)}:1"), "command_event_id": "f" * 64}
        tx.put("remote_command_transitions", f"{cid(1)}:1", row)
    enriched = read(w, transitions_after, None, 1)[0]
    assert enriched["command_author"] is None and enriched["channel"] is None


def test_q2_fleet_view_reads_the_pause_row_hold_and_version(tmp_path):
    w = World(tmp_path)
    assert read(w, state.fleet_view) == {"paused": False, "activation_hold": False, "control_version": 0}
    w.pause.pause()
    assert read(w, state.fleet_view) == {"paused": True, "activation_hold": False, "control_version": 1}
    w.pause.resume()
    w.pause.activation_gate("target-1", "d" * 64)
    assert read(w, state.fleet_view) == {"paused": True, "activation_hold": True, "control_version": 3}


# ---- the projection world ----------------------------------------------------------------------------------------
from test_buzz_a3b_outbox import FakeRelay  # noqa: E402

from codex_harness.credentials.adapters.role_keys import TestRoleKeys  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.observation.adapters.event_signer import NostrEventSigner  # noqa: E402
from codex_harness.observation.application.buzz_outbox import BuzzOutbox  # noqa: E402
from codex_harness.observation.application.buzz_projection import BuzzProjection  # noqa: E402
from codex_harness.observation.domain import buzz_projection as bp  # noqa: E402

ROLE = "conductor"
D_ORG = "4f1b7c52-9c0e-4f5a-8d1e-6a2b3c4d5e6f"
CONFLICT = (False, "none", "conflict: artifact head changed")  # A4 run 5, step 8 (`update_with_stale_prev`)


class HeadRelay(FakeRelay):
    """FakeRelay plus the `#d` query of A4 run 5 step 8 (it returns the current head alone): `heads[d] = event`."""

    def __init__(self):
        super().__init__()
        self.heads, self.d_queries, self.head_ended = {}, [], "eose"

    def query(self, filters):
        if "#d" in filters[0]:
            self.d_queries.append(filters)
            if self.query_error:
                raise ConnectionError("history unavailable")
            head = self.heads.get(filters[0]["#d"][0])
            events = [head] if head else []
            return {"events": events, "ended": self.head_ended, "unverified": 0, "received": len(events)}
        return super().query(filters)


class Models:
    """ZeusReadModels: the REAL coordination `fleet_view` and `transitions_after`; org and tasks are LABELLED DOUBLES
    (the composition that wires them from the Zeus rows is Batch D)."""

    def __init__(self, roles):
        self.views, self.roles = {}, roles

    def org(self, tx):
        if self.roles is None:
            raise RuntimeError("org unreadable")
        return {"roles": self.roles}

    def tasks(self, tx):
        return list(self.views.values())

    def task(self, tx, task_id):
        return self.views.get(task_id)

    def fleet(self, tx):
        return state.fleet_view(tx)

    def transitions_after(self, tx, after, limit):
        return transitions_after(tx, after, limit)


def view(task_id="t1", *, status="running", terminal=False, updated_at=NOW, team="core", **fields):
    base = {"task_id": task_id, "title": "Fix it", "team": team, "assignee": "worker:implementation",
            "sender": "lead:improvement", "generation": 0, "status": status, "stage": None, "terminal": terminal,
            "created_at": NOW - 100, "updated_at": updated_at, "observed_at": updated_at, "summary": "s",
            "evidence_refs": []}
    return {**base, **fields}


def role(rid, state_="idle"):
    return {"id": rid, "role": rid, "parent": None, "team": "core", "display": rid,
            "status": {"state": state_, "task_id": None, "last_activity_at": None, "observed_at": NOW}}


class P:
    """The B3 world (store, tasks, fleet, lease) plus an outbox, a projection and a relay double."""

    def __init__(self, tmp_path, outbox_max=2000, roles=("conductor",)):
        self.w = World(tmp_path)
        self.keys = TestRoleKeys(tmp_path / "keys")
        for name in dict.fromkeys((ROLE, "intruder", *roles)):
            self.keys.create(name)
        self.signer = NostrEventSigner(self.keys.pubkey, self.keys.sign_id)
        self.signed = []
        real = self.signer.sign
        self.signer.sign = lambda r, unsigned: self.signed.append(unsigned) or real(r, unsigned)
        self.relay, self.now = HeadRelay(), NOW
        self.models = Models([role(r) for r in roles])
        self.outbox = BuzzOutbox(self.w.store, self.relay, self.signer, self.w.lease, lambda: self.now, role=ROLE,
                                 replan=lambda subject: self.proj.replan(subject), outbox_max=outbox_max)
        pubkeys = {name: self.keys.pubkey(name) for name in dict.fromkeys((ROLE, *roles))}
        self.proj = BuzzProjection(self.w.store, self.outbox, self.models, self.relay, pubkeys,
                                   {"commander": "cmd", "org_d": D_ORG, "teams": {"core": "c1"}}, lambda: self.now)
        self.gen = self.w.generation

    def tick(self, seconds=1):
        self.now += seconds
        self.w.now = self.now

    def plan(self):
        return self.proj.plan(self.gen)

    def deliver(self):
        return self.outbox.deliver(self.gen)

    def step(self):
        counts = self.plan()
        self.deliver()
        return counts

    def rows(self, prefix=None, bucket="buzz_outbox"):
        with self.w.store.transaction() as tx:
            rows = sorted(tx.scan(bucket), key=lambda r: (r.get("subject", ""), r.get("version", 0)))
        return [r for r in rows if prefix is None or r.get("subject", "").startswith(prefix)]

    def row(self, subject, version):
        with self.w.store.transaction() as tx:
            return tx.get("buzz_outbox", digest([subject, version]))

    def head(self, subject):
        with self.w.store.transaction() as tx:
            return tx.get("buzz_heads", subject)

    def binding(self, task_id):
        with self.w.store.transaction() as tx:
            return tx.get("buzz_bindings", task_id)

    def unsigned(self, prefix):
        return [u for u in self.signed if any(t[:1] == ["zr-op"] and t[1].startswith(prefix) for t in u["tags"])]

    def bind(self, task_id="t1"):
        """The task's root enqueued, sent and acknowledged, then bound; returns the next plan's counts."""
        self.models.views.setdefault(task_id, view(task_id))
        self.step()
        return self.plan()

    def foreign(self, d, op="update", version=99, created_at=None):
        tags = [["ar", "1"], ["d", d], ["h", "c1"], ["type", "zeus.task"], ["op", op]]
        return NostrEventSigner(self.keys.pubkey, self.keys.sign_id).sign("intruder", {
            "kind": 45010, "created_at": created_at or self.now, "tags": tags,
            "content": json.dumps({"version": version})})


@pytest.fixture
def p(tmp_path):
    return P(tmp_path)


def content(row):
    return json.loads(row["event"]["content"])


def tags(row, name):
    return [t[1:] for t in row["event"]["tags"] if t[0] == name]


# ---- m1 foreign 45010 revision (DESIGN-B Q1; the relay's wording is from A4 run 5 step 8) --------------------------
def lose_the_cas(p, status="blocked"):
    """A bound task with card v1 acknowledged; then v2 is planned and the relay answers `conflict:` to it."""
    assert p.bind()["cards"] == 1
    p.deliver()
    assert p.row("task:t1", 1)["status"] == "acknowledged"
    p.tick(5)
    p.models.views["t1"] = view("t1", status=status, updated_at=p.now)
    assert p.plan()["cards"] == 1
    assert tags(p.row("task:t1", 2), "prev") == [[p.row("task:t1", 1)["event_id"]]]
    p.relay.script = [CONFLICT]
    p.deliver()
    row = p.row("task:t1", 2)
    assert (row["status"], row["reconcile"]) == ("unknown", True)
    return bp.task_artifact_d("t1")


def test_m1_a_foreign_update_head_is_corrected_with_prev_the_foreign_head(p):
    d = lose_the_cas(p)
    foreign = p.relay.heads[d] = p.foreign(d, "update")
    counts = p.deliver()  # reconcile: `ids` finds nothing; re-plan reads the CURRENT head by `#d`
    assert counts["replanned"] == 1 and p.relay.d_queries[-1] == [{"kinds": [45010], "#d": [d]}]
    v3 = p.row("task:t1", 3)
    assert v3["status"] == "pending" and tags(v3, "prev") == [[foreign["id"]]] and tags(v3, "op") == [["update"]]
    assert content(v3)["version"] == 3 and content(v3)["status"] == "blocked"
    assert p.row("task:t1", 2)["status"] == "superseded"
    head = p.head("task:t1")
    assert head["condition"] == "foreign_revision_corrected" and head["version"] == 3
    assert head["foreign_head_id"] == foreign["id"]
    p.relay.script = []
    p.deliver()
    assert p.relay.published[-1]["id"] == v3["event_id"] and p.row("task:t1", 3)["status"] == "acknowledged"


def test_m1_a_foreign_delete_is_unverified_and_nothing_is_published_over_it(p):
    d = lose_the_cas(p)
    p.relay.heads[d] = p.foreign(d, "delete")
    published = len(p.relay.published)
    counts = p.deliver()
    assert counts["superseded"] == 1 and counts["replanned"] == 0
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2] and p.row("task:t1", 2)["status"] == "superseded"
    assert p.head("task:t1")["condition"] == "unverified_foreign_revision"
    assert len(p.relay.published) == published  # nothing went over the foreign head
    p.tick(5)
    p.models.views["t1"] = view("t1", status="running", updated_at=p.now)  # the state moves on; the head does not
    queries = len(p.relay.d_queries)
    counts = p.plan()
    assert counts["unverified"] == 1 and counts["cards"] == 0 and len(p.relay.d_queries) == queries + 1
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2]  # a later plan does not retry it
    p.relay.heads[d] = p.foreign(d, "update", created_at=p.now + 1)  # the head changed: now it is tried again
    assert p.plan()["cards"] == 1
    assert p.row("task:t1", 3)["status"] == "pending" and p.head("task:t1")["condition"] is None


def test_m1_a_foreign_move_is_unverified_too(p):
    d = lose_the_cas(p)
    p.relay.heads[d] = p.foreign(d, "move")
    p.deliver()
    assert p.head("task:t1")["condition"] == "unverified_foreign_revision"
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2]


def test_m1_our_own_newer_head_supersedes_our_op(p):
    d = lose_the_cas(p)
    own = p.signer.sign(ROLE, {"kind": 45010, "created_at": p.now, "content": json.dumps({"version": 5}),
                               "tags": [["ar", "1"], ["d", d], ["op", "update"]]})
    p.relay.heads[d] = own
    published = len(p.relay.published)
    counts = p.deliver()
    assert counts["superseded"] == 1 and counts["replanned"] == 0
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2] and p.row("task:t1", 2)["status"] == "superseded"
    assert (p.head("task:t1") or {}).get("condition") is None and len(p.relay.published) == published


def test_m1_our_own_older_head_is_updated_over_not_dropped(p):
    d = lose_the_cas(p)
    p.relay.heads[d] = p.signer.sign(ROLE, {"kind": 45010, "created_at": p.now, "content": json.dumps({"version": 1}),
                                            "tags": [["ar", "1"], ["d", d], ["op", "create"]]})
    assert p.deliver()["replanned"] == 1
    v3 = p.row("task:t1", 3)
    assert tags(v3, "prev") == [[p.relay.heads[d]["id"]]] and p.head("task:t1")["condition"] is None


def test_m1_a_rejected_corrective_update_ends_unverified(p):
    d = lose_the_cas(p)
    foreign = p.relay.heads[d] = p.foreign(d, "update")
    p.deliver()  # v3 over the foreign head
    p.relay.script = [CONFLICT]
    p.deliver()  # the corrective update itself is refused, and the head is still the one we corrected over
    p.deliver()
    assert p.head("task:t1")["condition"] == "unverified_foreign_revision"
    assert p.head("task:t1")["foreign_head_id"] == foreign["id"] and p.row("task:t1", 3)["status"] == "superseded"
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2, 3]


def test_m1_replan_decides_nothing_without_a_generation_a_subject_or_a_positive_head(p, tmp_path):
    fresh = P(tmp_path / "other")
    assert fresh.proj.replan("task:t1") is None  # no lease generation known yet
    d = lose_the_cas(p)
    assert p.proj.replan("nonsense") is None and p.proj.replan("task:") is None
    p.relay.query_error = True
    assert p.proj.replan("task:t1") is None
    p.relay.query_error = False
    p.relay.heads[d] = p.foreign(d)
    p.relay.head_ended = "timeout"  # an answer that did not end in EOSE proves nothing (P1)
    assert p.proj.replan("task:t1") is None
    p.relay.head_ended = "eose"
    del p.relay.heads[d]
    assert p.proj.replan("task:t1") is None  # an empty answer is not absence either
    p.deliver()
    assert p.row("task:t1", 2)["status"] == "unknown"


# ---- m2 coalescing (§6.3, Q4) --------------------------------------------------------------------------------------
def test_m2_org_two_s_task_terminal_immediate_unchanged_nothing(tmp_path):
    p = P(tmp_path)
    counts = p.bind()  # the org needs no root, so it went out in the first plan
    assert (counts["cards"], [r["version"] for r in p.rows("org")]) == (1, [1]) and p.relay.d_queries == []
    assert content(p.row("task:t1", 1))["version"] == 1 and p.head("task:t1")["last_published_at"] == NOW
    p.deliver()
    p.tick(1)  # a changed non-terminal status inside the 2 s: no new version (the org is inside its 10 s too)
    p.models.views["t1"] = view("t1", status="blocked", updated_at=p.now)
    p.models.roles[0]["status"]["state"] = "busy"
    counts = p.plan()
    assert (counts["cards"], counts["org"], counts["coalesced"]) == (0, 0, 2)
    assert [r["version"] for r in p.rows("task:t1")] == [1] and [r["version"] for r in p.rows("org")] == [1]
    p.tick(1)  # 2 s: version 2
    counts = p.plan()
    assert (counts["cards"], counts["org"]) == (1, 0) and content(p.row("task:t1", 2))["status"] == "blocked"
    p.tick(1)  # a terminal transition is immediate, one second after the last revision
    p.models.views["t1"] = view("t1", status="succeeded", terminal=True, updated_at=p.now)
    assert p.plan()["cards"] == 1 and content(p.row("task:t1", 3))["status"] == "succeeded"
    p.tick(7)  # NOW + 10: the org's turn
    assert p.plan()["org"] == 1 and [r["version"] for r in p.rows("org")] == [1, 2]
    assert content(p.row("org", 2))["roles"][0]["status"]["state"] == "busy"
    p.tick(100)  # only `observed_at` moves: an unchanged rendering produces nothing
    p.models.views["t1"] = view("t1", status="succeeded", terminal=True, updated_at=NOW + 3, observed_at=p.now)
    p.models.roles[0]["status"]["observed_at"] = p.now
    counts = p.plan()
    assert (counts["cards"], counts["org"], counts["unchanged"]) == (0, 0, 2)
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2, 3]


def test_m2_a_card_follows_the_example_versions_at_100_101_102(tmp_path):
    p = P(tmp_path)
    p.now = 100
    p.bind()
    assert content(p.row("task:t1", 1))["version"] == 1
    p.tick(1)
    p.models.views["t1"] = view("t1", status="blocked", updated_at=p.now)
    assert p.plan()["cards"] == 0
    p.tick(1)
    assert p.plan()["cards"] == 1 and content(p.row("task:t1", 2))["version"] == 2


def test_m2_only_an_enqueued_op_moves_the_head(p):
    p.bind()
    head = p.head("task:t1")
    assert head["version"] == 1 and head["last_published_at"] == NOW and head["own_head_event_id"] is None
    p.deliver()
    p.tick(5)
    p.models.views["t1"] = view("t1", status="blocked", updated_at=p.now)
    p.outbox.outbox_max = 0  # no capacity: deferred, so no version and no publication time may be claimed
    assert p.plan()["deferred"] == 1
    head = p.head("task:t1")
    assert head["version"] == 1 and head["last_published_at"] == NOW


# ---- m3 overflow (§6.1.6, Q6) --------------------------------------------------------------------------------------
def fleet_commands(p, n):
    """`n` admitted fleet commands (pause, resume, ...), one second apart, each with its retained inbox row."""
    paused, version = False, 0
    for i in range(1, n + 1):
        p.w.now = NOW + i - 1
        cmd = command("resume_fleet" if paused else "pause_fleet", i, created_at=NOW + i - 1,
                      expected_control={"paused": paused, "version": version})
        out = admit_via_inbox(p.w, inbox_row(fence(cmd), i, created_at=NOW + i - 1, received_at=NOW + i - 1))
        assert out["disposition"] == "effect_done"
        paused, version = not paused, version + 1
    p.tick(10)


def test_m3_an_outbox_at_capacity_defers_with_one_alert_and_recovery_restores_oldest_first(tmp_path):
    p = P(tmp_path, outbox_max=3, roles=())
    p.models.roles = None  # the org is unreadable here: only append subjects compete for capacity
    p.models.views.update({"t1": view("t1"), "t2": view("t2")})
    fleet_commands(p, 4)
    receipts = [f"receipt:{cid(n)}:1" for n in (1, 2, 3, 4)]
    counts = p.plan()
    assert (counts["roots"], counts["receipts"], counts["deferred"]) == (2, 1, 1)
    p.plan()  # still full: still one coalesced alert, never one per event
    [alert] = p.rows(bucket="buzz_alerts")
    assert alert["kind"] == "outbox_capacity" and alert["state"] == "open" and alert["classes"] == ["append"]
    mark = p.rows(bucket="buzz_outbox_watermarks")[0]
    assert mark["deferred"] is True and mark["last"] == [receipts[0], 1]
    assert [r["subject"] for r in p.rows("receipt:")] == [receipts[0]]  # nothing was dropped silently: audit has all
    assert len(p.w.bucket("remote_command_transitions")) == 4
    p.deliver()  # all three are acknowledged: their rows no longer count
    del p.signed[:]
    assert p.outbox.recover_deferred(p.gen, p.proj.regenerate) == {"append": 3}
    assert [u["tags"][-1][1] for u in p.signed] == receipts[1:]  # oldest first, by (command_id, transition_revision)
    assert sorted(r["subject"] for r in p.rows("receipt:")) == sorted(receipts)  # no transition is omitted
    [alert] = p.rows(bucket="buzz_alerts")
    assert alert["state"] == "resolved"
    assert p.plan()["receipts"] == 0  # the plan finds nothing left to enqueue


def test_m3_a_deferred_state_is_regenerated_after_capacity_frees(tmp_path):
    p = P(tmp_path)
    p.bind()
    p.deliver()
    p.tick(10)
    p.models.views["t1"] = view("t1", status="blocked", updated_at=p.now)
    p.models.roles[0]["status"]["state"] = "busy"
    p.outbox.outbox_max = 1
    counts = p.plan()  # the org (first) takes the one slot; the card is deferred, not dropped
    assert (counts["org"], counts["cards"], counts["deferred"]) == (1, 0, 1)
    assert [r["version"] for r in p.rows("task:t1")] == [1]
    [alert] = p.rows(bucket="buzz_alerts")
    assert alert["state"] == "open" and alert["classes"] == ["state"]
    p.deliver()
    assert p.outbox.recover_deferred(p.gen, p.proj.regenerate) == {"state": 1}
    v2 = p.row("task:t1", 2)
    assert content(v2)["status"] == "blocked" and content(v2)["version"] == 2
    assert tags(v2, "prev") == [[p.row("task:t1", 1)["event_id"]]] and p.rows(bucket="buzz_alerts")[0]["state"] == "resolved"
    assert p.plan()["cards"] == 0  # the regenerated rendering is already queued: an unchanged state is nothing


# ---- m4 the canonical root P1 (Q3) ---------------------------------------------------------------------------------
def test_m4_the_first_acknowledged_root_binds_a_later_attempt_is_an_alias_and_never_rebinds(p):
    p.models.roles = None  # no org snapshot competes for the scripted relay answers
    p.models.views["t1"] = view("t1")
    p.relay.script = [(None, "unknown", "timeout")]  # attempt A: the acknowledgement is lost
    counts = p.plan()
    assert (counts["roots"], counts["no_root"]) == (1, 1) and p.rows("task:") == [] and p.binding("t1") is None
    p.deliver()
    attempt_a = p.row("root:t1", 1)
    assert attempt_a["status"] == "unknown" and p.plan()["cards"] == 0 and p.binding("t1") is None  # no card yet
    second = bp.task_root(task_id="t1", title="Fix it", team="core", assignee="worker:implementation", channel="c1",
                          created_at=p.now + 1)
    with p.w.store.transaction() as tx:
        assert p.outbox.enqueue(tx, p.gen, "root:t1", 2, second, "append")["status"] == "enqueued"
    p.relay.script = [(None, "unknown", "timeout")]  # delivery order: A is lost again, B is acknowledged first
    p.deliver()
    attempt_b = p.row("root:t1", 2)
    assert (p.row("root:t1", 1)["status"], attempt_b["status"]) == ("unknown", "acknowledged")
    counts = p.plan()
    binding = p.binding("t1")
    assert binding["canonical_root_event_id"] == attempt_b["event_id"] and binding["aliases"] == []
    assert counts["cards"] == 1 and tags(p.row("task:t1", 1), "root") == [[attempt_b["event_id"]]]
    p.deliver()  # attempt A is acknowledged later: an alias, and the canonical root is not rebound
    assert p.row("root:t1", 1)["status"] == "acknowledged"
    p.plan()
    binding = p.binding("t1")
    assert binding["canonical_root_event_id"] == attempt_b["event_id"] and binding["aliases"] == [attempt_a["event_id"]]
    p.tick(100)
    p.models.views["t1"] = view("t1", status="blocked", updated_at=p.now)
    p.plan()
    assert p.binding("t1") == binding and tags(p.row("task:t1", 2), "root") == [[attempt_b["event_id"]]]


def test_m4_a_root_found_by_its_tag_after_the_window_binds_that_attempt_and_aliases_the_resent_one(p):
    p.models.roles = None
    p.models.views["t1"] = view("t1")
    p.relay.script = [(None, "unknown", "timeout")]
    p.plan()
    p.deliver()
    row = p.row("root:t1", 1)
    earlier = p.signer.sign(ROLE, {**row["unsigned"], "created_at": 1})  # an earlier attempt of the same logical root
    p.tick(700)
    p.relay.answers = [[earlier]]
    p.deliver()  # reconciled by the zr-op tag: the found attempt is the canonical one
    acked = p.row("root:t1", 1)
    assert acked["status"] == "acknowledged" and acked["canonical_event_id"] == earlier["id"]
    p.plan()
    binding = p.binding("t1")
    assert binding["canonical_root_event_id"] == earlier["id"] and binding["aliases"] == [row["event_id"]]


# ---- m5 regeneration from the transition rows only (Q5, P6) --------------------------------------------------------
def cancel_world(tmp_path):
    p = P(tmp_path)
    task_id = p.w.task["id"]
    p.models.views[task_id] = view(task_id, generation=p.w.task["generation"])
    p.w.now = NOW
    out = admit_via_inbox(p.w, inbox_row(fence(p.w.cancel_cmd(1)), 1))
    assert out["disposition"] == "effect_done"
    return p, task_id


def test_m5_a_receipt_waits_for_its_tasks_root_without_blocking_the_others(tmp_path):
    p, task_id = cancel_world(tmp_path)
    w = p.w
    w.now = NOW + 1
    pause = command("pause_fleet", 2, created_at=NOW + 1, expected_control={"paused": False, "version": 0})
    admit_via_inbox(w, inbox_row(fence(pause), 2, created_at=NOW + 1, received_at=NOW + 1))
    counts = p.plan()  # the cancel's root is not acknowledged yet; the fleet receipt behind it still goes
    assert (counts["roots"], counts["waiting"], counts["receipts"]) == (1, 1, 1)
    assert [r["subject"] for r in p.rows("receipt:")] == [f"receipt:{cid(2)}:1"]
    p.deliver()
    counts = p.plan()
    root = p.binding(task_id)["canonical_root_event_id"]
    assert (counts["waiting"], counts["receipts"]) == (0, 1)
    cancel = p.unsigned(f"receipt:{cid(1)}")[0]
    assert ["e", root, "", "root"] in cancel["tags"] and ["e", f"{1:064x}", "", "reply"] in cancel["tags"]
    assert ["p", OWNER] in cancel["tags"] and ["h", "c1"] in cancel["tags"]
    fleet = p.unsigned(f"receipt:{cid(2)}")[0]  # a fleet op threads under the command event itself (§4.3)
    assert ["e", f"{2:064x}", "", "root"] in fleet["tags"] and ["e", f"{2:064x}", "", "reply"] in fleet["tags"]


def test_m5_receipts_come_only_from_transition_rows_one_per_command_and_revision(tmp_path):
    p, task_id = cancel_world(tmp_path)
    p.bind(task_id)
    [first] = p.unsigned("receipt:")
    assert json.loads(first["content"].split("\n")[1])["disposition"] == "effect_done"
    assert ["zr-op", f"receipt:{cid(1)}:1"] in first["tags"]
    with p.w.store.transaction() as tx:  # the command row's disposition is mutated afterwards: a receipt is unmoved
        binding = tx.get("remote_commands", cid(1))
        tx.put("remote_commands", cid(1), {**binding, "disposition": "refused", "reason_code": "not_applied"})
    again = p.proj.regenerate("append", None)
    receipt = next(i for i in again if i["subject"] == f"receipt:{cid(1)}:1")
    assert receipt["unsigned"]["content"] == first["content"] and receipt["version"] == 1
    p.plan()
    assert len(p.rows("receipt:")) == 1  # one receipt per (command_id, revision), however often it is planned
    with p.w.store.transaction() as tx:  # a second transition of the same command: a second, distinct receipt
        row = tx.get("remote_command_transitions", f"{cid(1)}:1")
        tx.put("remote_command_transitions", f"{cid(1)}:2", {
            **row, "id": f"{cid(1)}:2", "transition_revision": 2, "at": NOW + 5,
            "work": {"state": "queued", "result": None, "evidence_at": None}})
    assert p.plan()["receipts"] == 1
    assert [(r["subject"], r["version"]) for r in p.rows("receipt:")] == [
        (f"receipt:{cid(1)}:1", 1), (f"receipt:{cid(1)}:2", 2)]
    second = p.unsigned(f"receipt:{cid(1)}:2")[0]
    assert ["zr-op", f"receipt:{cid(1)}:2"] in second["tags"]
    assert json.loads(second["content"].split("\n")[1])["work"]["state"] == "queued"


def test_m5_a_receipt_without_a_retained_command_event_is_counted_not_guessed(tmp_path):
    p = P(tmp_path)
    p.w.now = NOW
    cmd = command("pause_fleet", 1, expected_control={"paused": False, "version": 0})
    assert p.w.admit(inbox_row(fence(cmd), 1))["disposition"] == "effect_done"  # no inbox row retained for it
    counts = p.plan()
    assert counts["invalid"] == 1 and counts["receipts"] == 0 and p.rows("receipt:") == []


# ---- m6 thread tags (RESEARCH-B QB1, QB2) ---------------------------------------------------------------------------
def test_m6_every_in_thread_post_has_a_reply_marker_receipts_root_and_reply_and_no_lone_root(tmp_path):
    p, task_id = cancel_world(tmp_path)
    p.w.now = NOW + 1
    pause = command("pause_fleet", 2, created_at=NOW + 1, expected_control={"paused": False, "version": 0})
    admit_via_inbox(p.w, inbox_row(fence(pause), 2, created_at=NOW + 1, received_at=NOW + 1))
    p.bind(task_id)
    posts = [u for u in p.signed if u["kind"] == 9]
    assert len(posts) == 3  # the task root and the two receipts
    root = p.binding(task_id)["canonical_root_event_id"]
    for post in posts:
        markers = [t[3] for t in post["tags"] if t[0] == "e"]
        assert "root" not in markers or "reply" in markers  # a lone `root` never appears (Buzz reads it as top-level)
        assert ["h", "c1"] in post["tags"] and any(t[0] == "h" for t in post["tags"])
        if markers:
            assert "reply" in markers and any(t[0] == "p" and len(t[1]) == 64 for t in post["tags"])
    [thread_root] = [u for u in posts if any(t[:2] == ["zr-op", "root:" + task_id] for t in u["tags"])]
    assert not any(t[0] == "e" for t in thread_root["tags"]) and bp.resolve_thread(thread_root["tags"]) is None
    receipts = [u for u in posts if u is not thread_root]
    for receipt in receipts:
        assert sorted(t[3] for t in receipt["tags"] if t[0] == "e") == ["reply", "root"]
        assert bp.resolve_thread(receipt["tags"]) is not None
    cancel = next(u for u in receipts if ["zr-op", f"receipt:{cid(1)}:1"] in u["tags"])
    assert bp.resolve_thread(cancel["tags"]) == (root, f"{1:064x}")
    fleet = next(u for u in receipts if ["zr-op", f"receipt:{cid(2)}:1"] in u["tags"])
    assert bp.resolve_thread(fleet["tags"]) == (f"{2:064x}", f"{2:064x}")
    cards = [u for u in p.signed if u["kind"] == 45010]
    assert cards and all(["h", "c1"] in c["tags"] or ["h", "cmd"] in c["tags"] for c in cards)


# ---- m7 interventions (Q7) ------------------------------------------------------------------------------------------
def interventions_of(p, subject="task:t1", version=1):
    return {i["op"]: (i["available"], i["reason_code"]) for i in content(p.row(subject, version))["interventions"]}


def test_m7_a_card_carries_its_interventions_from_the_task_and_fleet_views_and_desk_ops_are_unmigrated(p):
    p.bind()
    assert [i["op"] for i in content(p.row("task:t1", 1))["interventions"]] == list(rc.OPS)
    assert interventions_of(p) == {
        "cancel_task": (True, None), "pause_fleet": (True, None), "resume_fleet": (False, "not_applied"),
        "desk_open": (False, "desk_not_migrated"), "desk_turn": (False, "desk_not_migrated")}
    p.deliver()
    p.w.pause.pause()  # a fleet change republishes the card (and the org) with the new states
    p.tick(10)
    assert p.plan()["cards"] == 1
    assert interventions_of(p, version=2) == {
        "cancel_task": (True, None), "pause_fleet": (False, "not_applied"), "resume_fleet": (True, None),
        "desk_open": (False, "desk_not_migrated"), "desk_turn": (False, "desk_not_migrated")}
    assert content(p.row("org", 2))["fleet"] == {"paused": True, "version": 1, "activation_hold": False}
    p.tick(5)
    p.models.views["t1"] = view("t1", status="succeeded", terminal=True, updated_at=p.now)
    p.plan()
    assert interventions_of(p, version=3)["cancel_task"] == (False, "not_applied")


def test_m7_an_activation_hold_and_an_unreadable_fleet_are_never_optimistic(tmp_path):
    p = P(tmp_path)
    p.w.pause.activation_gate("target-1", "d" * 64)
    p.bind()
    assert interventions_of(p)["resume_fleet"] == (False, "activation_hold_present")
    [org] = [u for u in p.signed if ["d", D_ORG] in u["tags"]]
    assert json.loads(org["content"])["fleet"]["activation_hold"] is True
    q = P(tmp_path / "second")
    q.models.fleet = lambda tx: (_ for _ in ()).throw(RuntimeError("fleet row unreadable"))
    q.bind()
    got = interventions_of(q)
    assert got["pause_fleet"][0] is False and got["resume_fleet"][0] is False
    [org] = [u for u in q.signed if ["d", D_ORG] in u["tags"]]
    assert json.loads(org["content"])["fleet"] == {"paused": None, "version": None, "activation_hold": None}


# ---- the rest of the contract --------------------------------------------------------------------------------------
def test_a_card_is_not_planned_before_its_root_and_never_without_a_team_channel(p):
    p.models.views["t1"] = view("t1")
    p.models.views["t2"] = view("t2", team="elsewhere")
    counts = p.plan()
    assert (counts["roots"], counts["no_root"], counts["no_channel"]) == (1, 2, 1) and p.rows("task:") == []


def test_a_malformed_view_is_counted_invalid_and_planning_goes_on(p):
    p.models.views["t1"] = view("t1")
    p.models.views["bad"] = view("bad", evidence_refs=["/etc/passwd"])
    p.models.views["worse"] = {"task_id": "worse", "created_at": NOW}
    p.step()
    counts = p.plan()
    assert counts["cards"] == 1 and counts["invalid"] >= 1 and [r["subject"] for r in p.rows("task:")] == ["task:t1"]


def test_an_org_naming_a_role_without_a_key_is_not_published(tmp_path):
    p = P(tmp_path)
    p.models.roles = [role("conductor"), role("lead:unkeyed")]
    counts = p.plan()
    assert counts["invalid"] == 1 and p.rows("org") == []


def test_versions_strictly_increase_and_every_op_stays_unique_per_subject(p):
    p.bind()
    for step in range(1, 6):
        p.tick(3)
        p.models.views["t1"] = view("t1", status=f"s{step}", updated_at=p.now)
        p.plan()
    assert [r["version"] for r in p.rows("task:t1")] == [1, 2, 3, 4, 5, 6]
    assert len({r["id"] for r in p.rows("task:t1")}) == 6


def test_a_stale_generation_commits_nothing(p):
    p.models.views["t1"] = view("t1")
    with p.w.store.transaction() as tx:  # a newer bridge takes the lease after the old one expired
        newer = p.w.lease.acquire(tx, "bridge-2", NOW + 10_000, 600)
    assert newer != p.gen
    before = p.w.snapshot()
    with pytest.raises(ContractError):
        p.plan()
    assert p.w.snapshot() == before
    p.proj.use_generation(p.gen)
    with pytest.raises(ContractError):
        p.proj.regenerate("append", None)
    assert p.proj.regenerate("nonsense", None) == []


def test_regenerate_needs_a_generation_and_replays_a_watermark_exactly(p):
    p.models.views.update({"t1": view("t1"), "t2": view("t2")})
    assert p.proj.regenerate("append", None) == []  # no generation known yet
    p.proj.use_generation(p.gen)
    everything = p.proj.regenerate("append", None)
    assert [i["subject"] for i in everything] == ["root:t1", "root:t2"]
    assert [i["subject"] for i in p.proj.regenerate("append", ["root:t1", 1])] == ["root:t2"]
    assert [i["subject"] for i in p.proj.regenerate("append", ["unknown", 1])] == ["root:t1", "root:t2"]
    assert p.proj.regenerate("append", ["root:t2", 1]) == []
    assert all(set(i) == {"subject", "version", "unsigned"} for i in everything)


# ---- m8 single writer and the ports --------------------------------------------------------------------------------
def test_m8_the_two_buckets_are_declared_and_written_only_by_the_projection():
    ports = (SRC / "observation/ports.py").read_text()
    assert '"buzz_bindings"' in ports and '"buzz_heads"' in ports
    writers = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        if re.search(r"""\.put\(\s*(["']buzz_(bindings|heads)["']|BINDINGS|HEADS)\b""", text):
            writers.add(path.name)
    assert writers == {"buzz_projection.py"}


def test_m8_the_projection_reads_zeus_only_through_the_port_and_imports_no_coordination_application():
    tree = ast.parse((SRC / "observation/application/buzz_projection.py").read_text())
    modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith("codex_harness.coordination")]
    assert not [m for m in modules if ".adapters." in m or m.endswith(".adapters")]


def test_m8_the_read_port_stays_within_six_methods():
    from codex_harness.observation.ports import ZeusReadModels
    methods = [name for name in vars(ZeusReadModels) if not name.startswith("_") and callable(getattr(ZeusReadModels, name))]
    assert sorted(methods) == ["fleet", "org", "task", "tasks", "transitions_after"] and len(methods) <= 6
