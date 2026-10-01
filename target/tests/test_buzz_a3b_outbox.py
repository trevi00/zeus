"""Buzz A3b: the outbox (design §6.1 steps 1-6) over MemoryStore, a scripted fake relay, test custody and a fake clock."""

import pytest

from codex_harness.coordination.application.bridge_lease import BridgeLease
from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest
from codex_harness.observation.adapters.event_signer import NostrEventSigner
from codex_harness.observation.application.buzz_outbox import BuzzOutbox
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = 1_700_000_000
ROLE = "bridge"


class FakeRelay:
    """`publish` answers from a script (default OK true); `query` answers from `answers` (default empty EOSE)."""

    def __init__(self):
        self.published, self.queries, self.script, self.answers, self.query_error = [], [], [], [], False

    def publish(self, event):
        self.published.append(event)
        if self.script:
            accepted, prefix, message = self.script.pop(0)
        else:
            accepted, prefix, message = True, "none", ""
        return {"id": event["id"], "accepted": accepted, "prefix": prefix, "message": message}

    def query(self, filters):
        self.queries.append(filters)
        if self.query_error:
            raise ConnectionError("history unavailable")
        events = self.answers.pop(0) if self.answers else []
        return {"events": events, "ended": "eose", "unverified": 0, "received": len(events)}

    def query_all(self, filter, *, until=None): raise AssertionError("outbound never pages")
    def subscribe(self, sub_id, filters): raise AssertionError("not used")
    def close(self): pass


class World:
    def __init__(self, tmp_path, outbox_max=2000):
        keys = TestRoleKeys(tmp_path / "keys")
        keys.create(ROLE)
        self.signer = NostrEventSigner(keys.pubkey, keys.sign_id)
        self.now, self.relay, self.store, self.lease = NOW, FakeRelay(), MemoryStore(), BridgeLease()
        self.replans, self.plan = [], None
        with self.store.transaction() as tx:
            self.generation = self.lease.acquire(tx, "bridge-1", NOW, 60)
        self.outbox = BuzzOutbox(self.store, self.relay, self.signer, self.lease, lambda: self.now, role=ROLE,
                                 replan=self._replan, outbox_max=outbox_max)

    def _replan(self, subject):
        self.replans.append(subject)
        return self.plan

    def unsigned(self, content="c", tag=None, created_at=None):
        tags = [["zr-op", tag]] if tag else []
        return {"kind": 1, "created_at": self.now if created_at is None else created_at, "tags": tags,
                "content": content}

    def enqueue(self, subject, version, cls="state", **kwargs):
        with self.store.transaction() as tx:
            return self.outbox.enqueue(tx, self.generation, subject, version,
                                       self.unsigned(f"{subject}@{version}", **kwargs), cls)

    def rows(self, bucket="buzz_outbox"):
        with self.store.transaction() as tx:
            return sorted(tx.scan(bucket), key=lambda r: r.get("id"))

    def row(self, subject, version):
        with self.store.transaction() as tx:
            return tx.get("buzz_outbox", digest([subject, version]))

    def digest(self):
        return canonical(sorted(self.store.data.items(), key=str))


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def test_1_the_event_is_signed_and_stored_before_the_first_send(w):
    seen = []
    real = w.relay.publish

    def spying(event):
        seen.append(w.row("task:t1", 1)["event"])  # what is durably stored at the moment of the send
        return real(event)

    w.relay.publish = spying
    assert w.enqueue("task:t1", 1)["status"] == "enqueued"
    assert w.relay.published == []
    stored = w.row("task:t1", 1)
    assert stored["status"] == "pending" and stored["event"]["sig"] and stored["event"]["id"] == stored["event_id"]
    w.outbox.deliver(w.generation)
    assert seen == [stored["event"]] and w.relay.published == [stored["event"]]
    assert w.enqueue("task:t1", 1)["status"] == "duplicate"  # idempotent by op_id


def test_2_a_resend_within_the_window_sends_the_same_bytes_and_duplicate_is_acknowledged(w):
    w.enqueue("task:t1", 1)
    w.relay.script = [(None, "unknown", "timeout"), (True, "duplicate", "duplicate: already have this event")]
    w.outbox.deliver(w.generation)
    assert w.row("task:t1", 1)["status"] == "unknown"
    w.now += 60
    w.outbox.deliver(w.generation)
    first, second = w.relay.published
    assert canonical(first) == canonical(second)
    row = w.row("task:t1", 1)
    assert row["status"] == "acknowledged" and row["relay_message"].startswith("duplicate:")
    assert row["first_sent_at"] == NOW and row["last_attempt_at"] == NOW + 60 and row["attempts"] == 2
    assert w.relay.queries == []


def test_3_after_the_window_an_empty_or_failing_query_never_proves_absence(w):
    w.enqueue("task:t1", 1)
    w.relay.script = [(None, "unknown", "timeout")]
    w.outbox.deliver(w.generation)
    w.now += 601
    for error in (False, True, False):
        w.relay.query_error = error
        counts = w.outbox.deliver(w.generation)
        assert counts["unknown"] == 1 and w.row("task:t1", 1)["status"] == "unknown"
    assert len(w.relay.published) == 1  # nothing was resent past the window
    assert w.relay.queries[0] == [{"ids": [w.row("task:t1", 1)["event_id"]]}]


def test_3b_a_timestamp_rejection_ends_the_window_for_that_event(w):
    w.enqueue("task:t1", 1)
    w.relay.script = [(False, "invalid", "invalid: event creation date is too far off from the current time")]
    w.outbox.deliver(w.generation)
    row = w.row("task:t1", 1)
    assert row["status"] == "unknown" and row["reconcile"] is True
    w.now += 5  # still inside the window by the clock, but reconciled, not resent
    w.outbox.deliver(w.generation)
    assert len(w.relay.published) == 1 and len(w.relay.queries) == 1


def test_4_an_append_subject_reconciles_by_its_tag(w):
    w.enqueue("receipt:c1:1", 1, "append", tag="receipt:c1:1")
    w.relay.script = [(None, "unknown", "timeout")]
    w.outbox.deliver(w.generation)
    original = w.row("receipt:c1:1", 1)["event"]
    w.now += 700
    other = w.signer.sign(ROLE, {**w.unsigned("other", tag="receipt:c1:1")})  # right signer, wrong content
    w.relay.answers = [[other]]
    w.outbox.deliver(w.generation)
    assert w.row("receipt:c1:1", 1)["status"] == "unknown"
    twin = w.signer.sign(ROLE, {**w.unsigned(original["content"], tag="receipt:c1:1"), "created_at": NOW + 5})
    w.relay.answers = [[twin]]
    w.outbox.deliver(w.generation)
    row = w.row("receipt:c1:1", 1)
    assert row["status"] == "acknowledged" and row["canonical_event_id"] == twin["id"]
    assert w.relay.queries[0] == [{"kinds": [1], "authors": [original["pubkey"]], "#zr-op": ["receipt:c1:1"]}]


def test_4b_republication_is_throttled_by_passes_and_by_ten_minutes(w):
    w.enqueue("receipt:c1:1", 1, "append", tag="receipt:c1:1")
    w.relay.script = [(None, "unknown", "timeout")]
    w.outbox.deliver(w.generation)
    original = w.row("receipt:c1:1", 1)["event"]
    w.now += 700  # example 2: outside the window, the tag query is empty
    for _ in range(2):
        w.now += 30
        w.outbox.deliver(w.generation)
    assert len(w.relay.published) == 1 and w.row("receipt:c1:1", 1)["status"] == "unknown"
    w.relay.script = [(None, "unknown", "timeout")]
    w.now += 30
    counts = w.outbox.deliver(w.generation)  # third pass and more than 600 s: one fresh copy of the same op
    assert counts["republished"] == 1 and len(w.relay.published) == 2
    fresh = w.relay.published[1]
    assert fresh["id"] != original["id"] and fresh["tags"] == original["tags"] and fresh["content"] == original["content"]
    assert fresh["created_at"] == w.now and w.row("receipt:c1:1", 1)["event"] == fresh
    for _ in range(3):  # inside its new window the fresh copy is resent as-is; no second re-publication
        w.now += 100
        w.relay.script = [(None, "unknown", "timeout")]
        w.outbox.deliver(w.generation)
    assert all(e == fresh for e in w.relay.published[2:])
    w.now += 700  # outside again: three passes AND ten minutes since the last re-publication are both needed
    for _ in range(2):
        w.outbox.deliver(w.generation)
    published = len(w.relay.published)
    w.now += 700
    w.outbox.deliver(w.generation)
    assert len(w.relay.published) == published + 1  # third stalled pass and the gap is met
    w.relay.answers = [[w.signer.sign(ROLE, {**w.unsigned(original["content"], tag="receipt:c1:1"),
                                               "created_at": 1})]]
    w.now += 700
    w.outbox.deliver(w.generation)
    assert w.row("receipt:c1:1", 1)["status"] == "acknowledged"


def test_5_a_state_subject_without_a_match_is_replanned_and_the_old_version_superseded(w):
    w.enqueue("task:t1", 3)
    w.relay.script = [(None, "unknown", "timeout")]
    w.outbox.deliver(w.generation)
    old_id = w.row("task:t1", 3)["event_id"]
    w.now += 700
    w.plan = {"version": 4, "unsigned": w.unsigned("task:t1@4")}
    counts = w.outbox.deliver(w.generation)
    assert w.replans == ["task:t1"] and counts["replanned"] == 1 and counts["superseded"] == 1
    old, new = w.row("task:t1", 3), w.row("task:t1", 4)
    assert old["status"] == "superseded" and old["reclaimed"] and "event" not in old and old["event_id"] == old_id
    assert new["status"] == "pending" and new["event"]["content"] == "task:t1@4"
    assert w.relay.queries == [[{"ids": [old_id]}]]
    w.outbox.deliver(w.generation)  # the new version goes out; a positive `ids` match would have been enough alone
    assert w.relay.published[-1]["id"] == new["event_id"]


def test_5b_a_positive_ids_match_acknowledges_without_replanning(w):
    w.enqueue("task:t1", 1)
    w.relay.script = [(None, "unknown", "timeout")]
    w.outbox.deliver(w.generation)
    w.now += 700
    w.relay.answers = [[w.row("task:t1", 1)["event"]]]
    w.outbox.deliver(w.generation)
    assert w.row("task:t1", 1)["status"] == "acknowledged" and w.replans == []


def test_6_coalescing_sends_only_the_newest_pending_version(w):
    assert w.enqueue("task:t1", 1)["status"] == "enqueued"
    w.enqueue("task:t1", 2)
    w.enqueue("task:t1", 3)  # example 1
    assert [w.row("task:t1", v)["status"] for v in (1, 2, 3)] == ["superseded", "superseded", "pending"]
    assert w.enqueue("task:t1", 2)["status"] == "duplicate"
    assert w.enqueue("task:t1", 0)["status"] == "stale"
    w.outbox.deliver(w.generation)
    assert [e["content"] for e in w.relay.published] == ["task:t1@3"]
    assert w.enqueue("receipt:c", 1, "append", tag="a")["status"] == "enqueued"
    w.enqueue("receipt:c", 2, "append", tag="b")
    assert [w.row("receipt:c", v)["status"] for v in (1, 2)] == ["pending", "pending"]  # append is never coalesced


def test_7_capacity_defers_without_a_row_and_raises_one_alert_then_recovers_oldest_first(tmp_path):
    w = World(tmp_path, outbox_max=2)
    w.relay.script = [(None, "unknown", "timeout")] * 2
    assert [w.enqueue(f"receipt:c:{n}", 1, "append", tag=f"r{n}")["status"] for n in (1, 2)] == ["enqueued"] * 2
    w.outbox.deliver(w.generation)  # both are now `unknown`: still nonterminal
    for n in (3, 4, 5, 6):
        assert w.enqueue(f"receipt:c:{n}", 1, "append", tag=f"r{n}")["status"] == "deferred"
    assert w.enqueue("task:new", 1)["status"] == "deferred"  # the bound is global; the state class has its own mark
    assert sorted(r["subject"] for r in w.rows()) == ["receipt:c:1", "receipt:c:2"]  # deferred work made no row
    [alert] = w.rows("buzz_alerts")
    assert alert["id"] == "outbox_capacity" and alert["state"] == "open" and alert["deferrals"] >= 4
    [mark] = [m for m in w.rows("buzz_outbox_watermarks") if m["cls"] == "append"]
    assert mark["deferred"] is True and mark["last"] == ["receipt:c:2", 1]
    assert w.enqueue("receipt:c:7", 1, "append", tag="r7")["status"] == "deferred"  # still full, still one alert
    assert len(w.rows("buzz_alerts")) == 1
    audit = [{"subject": f"receipt:c:{n}", "version": 1, "unsigned": w.unsigned(f"m{n}", tag=f"r{n}")}
             for n in (3, 4, 5, 6, 7)]
    calls = []

    def regenerate(cls, after):  # the audit stand-in: items after the watermark, oldest first
        calls.append((cls, after))
        if cls == "state":
            return []
        return [item for item in audit if after is None or item["subject"] > after[0]]

    assert w.outbox.recover_deferred(w.generation, regenerate) == {"append": 0, "state": 0}  # no capacity yet
    assert calls == [("append", ["receipt:c:2", 1]), ("state", None)]
    assert w.enqueue("receipt:c:8", 1, "append", tag="r8")["status"] == "deferred"  # order is preserved meanwhile
    w.relay.script = []
    for expected, last in (({"append": 2}, "receipt:c:4"), ({"append": 2}, "receipt:c:6"), ({"append": 1}, "receipt:c:7")):
        w.outbox.deliver(w.generation)  # the resident rows are acknowledged: capacity frees
        assert w.outbox.recover_deferred(w.generation, regenerate) == expected
        [mark] = [m for m in w.rows("buzz_outbox_watermarks") if m["cls"] == "append"]
        assert mark["last"] == [last, 1]
    assert [r["subject"] for r in w.rows() if r["status"] == "pending"] == ["receipt:c:7"]  # oldest first
    assert [(r["subject"], r["status"]) for r in sorted(w.rows(), key=lambda r: r["subject"])][:6] == [(f"receipt:c:{n}", "acknowledged") for n in range(1, 7)]
    assert mark["deferred"] is False
    [alert] = w.rows("buzz_alerts")
    assert alert["state"] == "resolved" and len(w.rows("buzz_alerts")) == 1
    assert w.enqueue("receipt:c:8", 1, "append", tag="r8")["status"] == "enqueued"


def test_8_payload_is_reclaimed_after_ack_and_capacity_counts_only_nonterminal_rows(tmp_path):
    w = World(tmp_path, outbox_max=1)
    w.enqueue("receipt:c:1", 1, "append", tag="r1")
    assert w.enqueue("receipt:c:2", 1, "append", tag="r2")["status"] == "deferred"
    w.outbox.deliver(w.generation)
    row = w.row("receipt:c:1", 1)
    assert row["status"] == "acknowledged" and row["reclaimed"] is True
    assert "event" not in row and "unsigned" not in row
    assert {"id", "event_id", "status", "first_sent_at", "last_attempt_at", "created_at"} <= set(row)
    w.outbox.recover_deferred(w.generation, lambda cls, after: [
        {"subject": "receipt:c:2", "version": 1, "unsigned": w.unsigned("m2", tag="r2")}])
    assert w.row("receipt:c:2", 1)["status"] == "pending"  # the acknowledged row no longer counts


def test_9_a_stale_generation_commits_nothing(w):
    w.enqueue("task:t1", 1)
    with w.store.transaction() as tx:
        w.lease.acquire(tx, "bridge-1", NOW + 1, 60)  # a restarted bridge fences its predecessor
    before = w.digest()
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.enqueue("task:t1", 2)
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.outbox.deliver(w.generation)
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.outbox.recover_deferred(w.generation, lambda cls, after: [])
    assert w.digest() == before and w.relay.published == [] and w.relay.queries == []


def test_9b_a_lease_lost_mid_pass_stops_before_committing_the_outcome(w):
    w.enqueue("task:t1", 1)
    real = w.relay.publish

    def fenced(event):
        with w.store.transaction() as tx:
            w.lease.acquire(tx, "bridge-1", NOW + 1, 60)
        return real(event)

    w.relay.publish = fenced
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.outbox.deliver(w.generation)
    assert w.row("task:t1", 1)["status"] == "pending"


# -- A3c F1: a standing deferral must not block the capacity-neutral replacement of a resident state row --------

def _full_unknown_with_a_deferral(tmp_path, outbox_max=1):
    """task:one v1 is `unknown` (the relay timed out) and fills the outbox; task:two is deferred; the drift window passed."""
    w = World(tmp_path, outbox_max=outbox_max)
    w.relay.script = [(None, "unknown", "timeout")]
    assert w.enqueue("task:one", 1)["status"] == "enqueued"
    w.outbox.deliver(w.generation)
    assert w.row("task:one", 1)["status"] == "unknown"
    if outbox_max == 2:
        assert w.enqueue("task:filler", 1)["status"] == "enqueued"
    assert w.enqueue("task:two", 1)["status"] == "deferred"
    w.now += 700
    w.plan = {"version": 2, "unsigned": w.unsigned("task:one@2", created_at=w.now)}
    w.outbox.replan = lambda subject: w.plan if subject == "task:one" else None  # nothing new for the filler
    return w


def _resident(w):
    return [r for r in w.rows() if r["status"] in ("pending", "in_flight", "unknown")]


def _state_mark(w):
    [mark] = [m for m in w.rows("buzz_outbox_watermarks") if m["cls"] == "state"]
    return mark


def test_a3c_1_a_same_subject_replacement_passes_a_standing_deferral_within_capacity(tmp_path):
    w = _full_unknown_with_a_deferral(tmp_path)
    mark = _state_mark(w)
    assert mark["deferred"] is True and mark["last"] == ["task:one", 1]
    seen = []
    real = w.relay.publish

    def spying(event):
        row = w.row("task:one", 2)  # what is durably stored at the moment of the send
        seen.append((row["status"], row["event"]))
        return real(event)

    w.relay.publish = spying
    counts = w.outbox.deliver(w.generation)  # v1 is unknown past the window: no match, so v2 replaces it
    assert counts["replanned"] == 1 and counts["superseded"] == 1
    assert [(r["subject"], r["version"], r["status"]) for r in _resident(w)] == [("task:one", 2, "pending")]
    assert len(_resident(w)) <= w.outbox.outbox_max  # the replacement did not exceed the bound
    assert w.row("task:one", 1)["status"] == "superseded" and w.row("task:one", 1)["reclaimed"] is True
    assert _state_mark(w) == mark  # the watermark neither advanced nor cleared
    assert w.relay.published == [w.relay.published[0]] and seen == []  # stored, not yet sent in that pass
    w.outbox.deliver(w.generation)
    assert seen == [("pending", w.relay.published[-1])] and w.relay.published[-1]["content"] == "task:one@2"
    assert w.row("task:one", 2)["status"] == "acknowledged"
    assert _state_mark(w) == mark and w.row("task:two", 1) is None  # deferred work is still only identified


def test_a3c_2_after_the_replacement_the_deferred_subject_regenerates_oldest_first_without_duplicates(tmp_path):
    w = _full_unknown_with_a_deferral(tmp_path)
    w.outbox.deliver(w.generation)
    w.outbox.deliver(w.generation)  # v2 acknowledged: capacity is free
    calls = []

    def regenerate(cls, after):
        calls.append((cls, after))
        if cls != "state":
            return []
        assert after == ["task:one", 1]  # the watermark still names the last op enqueued before the deferral
        return [{"subject": "task:two", "version": 1, "unsigned": w.unsigned("task:two@1")}]

    assert w.outbox.recover_deferred(w.generation, regenerate) == {"state": 1}
    assert _state_mark(w)["deferred"] is False
    w.outbox.deliver(w.generation)
    assert w.row("task:two", 1)["status"] == "acknowledged"
    assert w.relay.published[-1]["content"] == "task:two@1"
    assert w.outbox.recover_deferred(w.generation, regenerate) == {}  # replay: nothing deferred, nothing repeated
    for subject, version in (("task:one", 2), ("task:two", 1)):  # each logical subject was sent exactly once
        assert sum(e["content"] == f"{subject}@{version}" for e in w.relay.published) == 1
    assert sorted((r["subject"], r["version"]) for r in w.rows()) == [("task:one", 1), ("task:one", 2), ("task:two", 1)]


def test_a3c_3_the_exception_is_a_replacement_not_admission_through_a_full_outbox(tmp_path):
    w = _full_unknown_with_a_deferral(tmp_path, outbox_max=2)
    w.outbox.deliver(w.generation)  # replaces task:one v1 (resident 2 -> 2)
    assert sorted((r["subject"], r["version"]) for r in _resident(w)) == [("task:filler", 1), ("task:one", 2)]
    assert w.enqueue("task:three", 1)["status"] == "deferred"  # an unrelated new subject stays deferred
    assert w.enqueue("task:two", 1)["status"] == "deferred"
    assert w.enqueue("task:one", 3)["status"] == "enqueued"  # the pending v2 is replaced by v3: still capacity-neutral
    assert len(_resident(w)) == 2 and _state_mark(w)["deferred"] is True and _state_mark(w)["last"] == ["task:filler", 1]
    assert w.enqueue("task:one", 0)["status"] == "stale"
    assert w.row("task:three", 1) is None and w.row("task:two", 1) is None
    assert w.outbox.outbox_max == 2


def test_a3c_4_the_default_capacity_bound_still_applies_to_a_replacement(tmp_path):
    w = World(tmp_path)  # the default bound
    assert w.outbox.outbox_max == 2000
    w.outbox.outbox_max = 2  # the same branch at a small bound: the resident count never exceeds it
    w.relay.script = [(None, "unknown", "timeout")]
    w.enqueue("task:one", 1)
    w.outbox.deliver(w.generation)
    w.enqueue("task:filler", 1)
    assert w.enqueue("task:two", 1)["status"] == "deferred"
    w.now += 700
    w.outbox.replan = lambda subject: {"version": 2, "unsigned": w.unsigned("task:one@2", created_at=w.now)} \
        if subject == "task:one" else None
    w.outbox.deliver(w.generation)
    assert sorted((r["subject"], r["version"]) for r in _resident(w)) == [("task:filler", 1), ("task:one", 2)]


def test_a3c_5_a_replacement_under_a_stale_generation_commits_nothing(tmp_path):
    w = _full_unknown_with_a_deferral(tmp_path)
    with w.store.transaction() as tx:
        w.lease.acquire(tx, "bridge-1", w.now + 1, 60)  # a restarted bridge fences its predecessor
    before = w.digest()
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.outbox.deliver(w.generation)
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        with w.store.transaction() as tx:
            w.outbox.enqueue(tx, w.generation, "task:one", 2, w.unsigned("task:one@2"), "state")
    assert w.digest() == before and w.row("task:one", 2) is None
    assert w.row("task:one", 1)["status"] == "unknown" and _state_mark(w)["deferred"] is True


def test_a3c_6_without_a_deferral_the_unknown_state_still_replans_and_delivers(tmp_path):
    w = World(tmp_path, outbox_max=1)  # the positive control: no deferral outstanding
    w.relay.script = [(None, "unknown", "timeout")]
    w.enqueue("task:one", 1)
    w.outbox.deliver(w.generation)
    w.now += 700
    w.plan = {"version": 2, "unsigned": w.unsigned("task:one@2", created_at=w.now)}
    w.outbox.deliver(w.generation)
    w.outbox.deliver(w.generation)
    assert w.row("task:one", 1)["status"] == "superseded" and w.row("task:one", 2)["status"] == "acknowledged"


# ---- B4 (DESIGN-B Q1): the CAS conflict of a state row, and a replan that answers `superseded` ---------------------
CONFLICT = (False, "none", "conflict: artifact head changed")  # the relay's wording, A4 run 5 step 8


def test_7a_a_conflict_rejection_of_a_state_row_ends_its_window_like_a_timestamp_rejection(w):
    w.enqueue("task:t1", 1)
    w.relay.script = [CONFLICT]
    w.outbox.deliver(w.generation)
    row = w.row("task:t1", 1)
    assert (row["status"], row["reconcile"], row["relay_message"]) == ("unknown", True, "conflict: artifact head changed")
    w.plan = {"version": 2, "unsigned": w.unsigned("task:t1@2")}
    counts = w.outbox.deliver(w.generation)  # inside the window, yet it reconciles and re-plans (never a resend)
    assert w.relay.published == [row["event"]] and w.replans == ["task:t1"] and counts["replanned"] == 1
    assert w.row("task:t1", 1)["status"] == "superseded" and w.row("task:t1", 2)["status"] == "pending"


def test_7b_other_explicit_rejections_and_append_rows_keep_the_existing_behaviour(w):
    w.enqueue("task:t1", 1)
    w.enqueue("receipt:c:1", 1, "append", tag="receipt:c:1")
    w.relay.script = [CONFLICT, (False, "none", "blocked: not a member")]  # delivery order: the receipt, then the task
    w.outbox.deliver(w.generation)
    assert [w.row(s, 1)["status"] for s in ("task:t1", "receipt:c:1")] == ["pending", "pending"]
    assert not any(w.row(s, 1)["reconcile"] for s in ("task:t1", "receipt:c:1"))
    assert w.relay.queries == [] and w.replans == []


def test_7c_a_replan_that_answers_superseded_retires_the_op_and_frees_its_capacity(tmp_path):
    w = World(tmp_path, outbox_max=1)
    w.enqueue("task:t1", 1)
    w.relay.script = [CONFLICT]
    w.outbox.deliver(w.generation)
    original = w.row("task:t1", 1)["event_id"]
    w.plan = {"superseded": True}
    counts = w.outbox.deliver(w.generation)
    row = w.row("task:t1", 1)
    assert counts["superseded"] == 1 and counts["replanned"] == 0 and w.replans == ["task:t1"]
    assert row["status"] == "superseded" and row["reclaimed"] and "event" not in row and "unsigned" not in row
    assert row["event_id"] == original and w.relay.queries == [[{"ids": [original]}]]
    assert w.enqueue("task:t2", 1)["status"] == "enqueued"  # a superseded row no longer counts against the bound
    assert w.outbox.deliver(w.generation)["sent"] == 1  # and is never sent again
