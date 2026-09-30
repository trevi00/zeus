"""Shared S7 scenario steps (`review.releases_queue`): the release operations delivery calls, moved ahead in S7 V3
(DESIGN-s7 §1 V3): `ReleaseQueue` (enqueue, claim, owned, heartbeat, defer, finish, retry) and `Releases` (verify,
promote, rollback, request_evaluator_migration, request_environment_reverification).

- **queue** (M7 tests/test_release_recovery.py and tests/test_execution_fence.py, memory backend): enqueue refusals and
  the idempotent row; claim (held lease, `eligible`, `retry_at`, the `(at, id)` order, the attempt budget, a refused
  fence advance, the written row/lease/lock/fence); owned/heartbeat refusals and the extended lease; defer; finish with
  the backoff and the budget; retry; the fence surviving lock expiry and row recreation; a row restored behind the
  fence; a caller's transaction that raises.
- **verify**, **promote/rollback** (hook restore, research activation, events), **evaluator migration** (M7
  tests/test_release_evaluator_migration.py, memory cases) and **environment reverification** (M7
  tests/test_release_environment_reverification.py, memory cases).

Layer: harness (never shipped)

`api` supplies `MemoryStore`, `queue(store)`, `releases(store)`, `POLICY`, `TicketSuperseded`, the pure names
`evaluator_successor_id`, `reverification_successor_id`, `environment_successor_id`, `expected_evaluator_pin`,
`EnvironmentReverificationRefused`, `UnsupportedEvaluatorReverification`, and `advance(seconds)` (the only way the clock
moves). Every release, ticket, lock, fence, hook and receipt row is a LABELLED fixture of M7's shape; nothing claims an
actual Codex, GitHub or production verification. Where an M7 test calls `request_reverification` (it stays for S8 and is
not on the target) the plain reverification successor is written as a LABELLED row of M7's shape instead, and the
half of a test that needs the call itself is recorded as `{"unreachable": ...}`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)   # the reference/target fake clock starts here
AUTHOR = "worker:implementation"
CHECKS = ["tests", "cli_start", "cli_file_task"]
E = "e" * 40
CONTROLLER = "7" * 40
ENV_CHECKS = {"tests": {"passed": True, "evidence": "fixture:tests-passed"},
              "cli_start": {"passed": True, "evidence": "fixture:cli-start-passed"},
              "cli_file_task": {"passed": False, "evidence": "fixture:cli-file-task-environment-defect"}}
TICKET_CONTENT = {"title": "fixture ticket"}
UNREACHABLE_REVERIFY = {"unreachable": "Releases.request_reverification stays for S8 and is not on the target"}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


TICKET = {"id": "ticket-1", "revision": "r1", "content_hash": canonical_digest(TICKET_CONTENT)}


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "message": str(exc)[:200]}
        if hasattr(exc, "reason_code"):
            out["reason_code"] = exc.reason_code
        return out
    return {"value": value}


class Boom(Exception):
    """The caller's own failure inside its unit."""


class OrgProxy:
    """LABELLED: the M7 tests' `monkeypatch.setattr(releases.org, "actor", ...)` on a private proxy."""

    def __init__(self, org, actor):
        self._org, self.actor = org, actor

    def __getattr__(self, name):
        return getattr(self._org, name)


ELAPSED = [0]   # seconds the one process clock has advanced, across every case


class Case:
    def __init__(self, api, children=None):
        self.api = api
        self.store = api.MemoryStore()
        self.queue = api.queue(self.store)
        self.rel = api.releases(self.store)
        self.children = children if children is not None else []

    def spawn(self):
        """A second store within this case; its records are digested with the case's."""
        child = Case(self.api, self.children)
        self.children.append(child)
        return child

    # -- time: only `api.advance` moves the clock; `at` names an instant of it as M7 writes it
    def advance(self, seconds):
        self.api.advance(seconds)
        ELAPSED[0] += seconds

    def at(self, seconds=0) -> str:
        return self.when(seconds).isoformat()

    def when(self, seconds=0) -> datetime:
        return EPOCH + timedelta(seconds=ELAPSED[0] + seconds)

    # -- rows
    def put(self, bucket, key, body):
        with self.store.transaction() as tx:
            tx.put(bucket, key, body)

    def get(self, bucket, key):
        with self.store.transaction() as tx:
            return tx.get(bucket, key)

    def scan(self, bucket):
        with self.store.transaction() as tx:
            return tx.scan(bucket)

    def state(self) -> dict:
        with self.store.transaction() as tx:
            return {r["bucket"] + "/" + r["id"]: canonical_digest(r["body"]) for r in tx.records()}

    def unit(self, fn):
        """Run `fn(tx)` inside this caller's unit, then raise: nothing it did may survive."""
        before, box = self.state(), {}

        def body():
            with self.store.transaction() as tx:
                box["result"] = call(fn, tx)
                raise Boom()

        try:
            body()
        except Boom:
            pass
        return {"result": box["result"], "written": self.state() != before}

    def guarded(self, fn, *args, **kwargs):
        """A step and whether it wrote anything (a refusal must write nothing)."""
        before = self.state()
        out = call(fn, *args, **kwargs)
        return {**out, "wrote": self.state() != before}

    def lock(self, **body):
        self.put("deployment_locks", "controller", body)

    def queued(self, rid, **body):
        self.put("release_queue", rid, {"id": rid, "status": "queued", **body})

    def org_as(self, actor):
        self.rel.org = OrgProxy(self.rel.org, actor)

    def author_approves(self):
        org, original = self.rel.org, self.rel.org.actor
        author = org.agents[AUTHOR]
        self.org_as(lambda actor_id, role=None: author if actor_id == AUTHOR and role == "conductor"
                    else original(actor_id, role))

    # -- releases through the pinned S4 operations
    def seed_ticket(self, status="open", revision="r1"):
        self.put("tickets", TICKET["id"], {**TICKET, "status": status, "lifecycle_sequence": 0})
        self.put("ticket_revisions", TICKET["id"] + ":r1", {"content": TICKET_CONTENT})
        if revision != "r1":
            self.put("tickets", TICKET["id"], {**TICKET, "status": status, "revision": revision,
                                              "lifecycle_sequence": 0})

    def reviewed(self, tree="tree", checks=None, ticket=False, **extra):
        candidate = {"revision": "candidate", "base": "base", "tree": tree, "author": AUTHOR, **extra}
        if ticket:
            self.seed_ticket()
            candidate["zeus_ticket"] = TICKET
        release = self.rel.propose(candidate, {"checks": checks or CHECKS})
        for actor in ("lead:improvement", "conductor"):
            self.rel.review(release["id"], actor, "candidate", True, "fixture:review")
        return self.get("releases", release["id"])

    def verified(self, **kwargs):
        release = self.reviewed(**kwargs)
        passed = {name: {"passed": True, "evidence": "fixture:" + name} for name in release["policy"]["checks"]}
        return self.rel.verify(release["id"], "candidate", release["policy_hash"], passed)

    def rejected(self):
        release = self.reviewed()
        failed = {"tests": {"passed": False, "evidence": "fixture:tests-failed"},
                  **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"} for name in CHECKS[1:]}}
        release = self.rel.verify(release["id"], "candidate", release["policy_hash"], failed)
        assert release["status"] == "rejected"
        return release

    def migrated(self, source, **overrides):
        approval = overrides.pop("approval", None) or approval_for(source)
        resolved = overrides.pop("resolved_pin", None) or self.api.expected_evaluator_pin(approval)
        return self.rel.request_evaluator_migration(
            source["id"], overrides.pop("actor", "conductor"),
            expected_revision=overrides.pop("expected_revision", "candidate"),
            expected_policy_hash=overrides.pop("expected_policy_hash", source["policy_hash"]),
            approval=approval, resolved_pin=resolved, **overrides)

    def migrated_rejected(self, checks=None):
        child = self.migrated(self.rejected())
        return self.rel.verify(child["id"], "candidate", child["policy_hash"], checks or ENV_CHECKS)

    def env_reverify(self, source, **overrides):
        approval = overrides.pop("approval", None) or env_approval_for(source)
        resolved = overrides.pop("resolved_pin", None) or self.api.expected_evaluator_pin(
            source["evaluator_migration"])
        return self.rel.request_environment_reverification(
            source["id"], overrides.pop("actor", "conductor"),
            expected_revision=overrides.pop("expected_revision", "candidate"),
            expected_policy_hash=overrides.pop("expected_policy_hash", source["policy_hash"]),
            approval=approval, resolved_pin=resolved,
            resolved_controller=overrides.pop("resolved_controller", CONTROLLER), **overrides)

    def plain_successor_row(self, source):
        """LABELLED row of the shape M7 `request_reverification` writes (INV-RELEASE-REVERIFY-001)."""
        key = self.api.reverification_successor_id(source["id"])
        self.put("releases", key, {
            "id": key, "candidate": source["candidate"], "policy": source["policy"],
            "policy_hash": source["policy_hash"], "status": "reviewed", "reviews": source["reviews"], "checks": {},
            "created_at": self.at(), "reverify_of": source["id"],
            "inherited_reviews": {"release_id": source["id"], "digest": canonical_digest(source["reviews"])},
            "reverification": {"actor": "conductor", "reason": "fixture: short TEMP diagnosis",
                               "evidence": "fixture:diagnosis-receipt", "expected_revision": "candidate",
                               "expected_policy_hash": source["policy_hash"],
                               "source_checks_digest": canonical_digest(source["checks"]),
                               "source_digest": canonical_digest(source), "at": self.at()}})
        return key

    def successors(self, source):
        return [r["id"] for r in self.scan("releases") if r.get("reverify_of") == source["id"]]


def approval_for(release, **overrides):
    return {"source_release_id": release["id"], "base": release["candidate"]["base"], "evaluator_revision": E,
            "evaluator_tree": "f" * 40, "patch_sha256": "a" * 64, "paths": ["tests/test_fixture.py"],
            "evidence": "sha256:" + "b" * 64, "approved_by": "conductor", **overrides}


def env_approval_for(source, **overrides):
    return {"kind": "environment_reverification", "source_release_id": source["id"],
            "source_policy_hash": source["policy_hash"], "old_plan_id": "delivery-plan-migrated",
            "old_plan_sha256": "c" * 64, "intent_id": "control-intent-1", "policy_id": "control-policy-1",
            "target_id": "canary-service", "lane": "h1-file-canary", "fix_evidence": "sha256:" + "d" * 64,
            "controller_revision": CONTROLLER, "approved_by": "conductor", **overrides}


# ---- group 1: queue ----------------------------------------------------------------------------------------

def enqueue_cases(c: Case) -> dict:
    out = {"empty_reason": c.guarded(c.queue.enqueue, "r1", "  "), "non_string_reason": c.guarded(c.queue.enqueue, "r1", None)}
    out["unknown_release"] = c.guarded(c.queue.enqueue, "nope", "fixture: owner queued it")
    candidate = c.rel.propose({"revision": "candidate", "base": "base", "tree": "t0", "author": AUTHOR},
                              {"checks": CHECKS})
    out["not_reviewed"] = c.guarded(c.queue.enqueue, candidate["id"], "fixture: owner queued it")
    for status in ("rejected", "active"):
        c.put("releases", "st-" + status, {"id": "st-" + status, "status": status, "candidate": {}})
        out["status_" + status] = c.guarded(c.queue.enqueue, "st-" + status, "fixture: owner queued it")
    superseded = c.reviewed(tree="t-ticket", ticket=True)
    c.seed_ticket(revision="r2")
    out["superseded_ticket"] = c.guarded(c.queue.enqueue, superseded["id"], "fixture: owner queued it")
    reviewed = c.reviewed(tree="t1")
    out["new_row"] = c.guarded(c.queue.enqueue, reviewed["id"], "fixture: owner queued it")
    out["again_same"] = c.guarded(c.queue.enqueue, reviewed["id"], "fixture: another reason")
    c.put("releases", "v1", {"id": "v1", "status": "verified", "candidate": {}})
    out["verified_release"] = c.guarded(c.queue.enqueue, "v1", "fixture: verified one")
    for status in ("failed", "cancelled", "running", "done"):
        c.put("release_queue", "x-" + status, {"id": "x-" + status, "status": status, "reason": "fixture", "attempt": 2})
        out["existing_" + status] = c.guarded(c.queue.enqueue, "x-" + status, "fixture: re-arm me")
    second = c.reviewed(tree="t2")
    out["in_unit_raises"] = c.unit(lambda tx: c.queue.enqueue(second["id"], "fixture: in a unit", transaction=tx))
    out["in_unit_not_queued"] = c.get("release_queue", second["id"])
    with c.store.transaction() as tx:
        joined = c.queue.enqueue(second["id"], "fixture: joined", transaction=tx)
    out["in_unit_committed"] = {"value": joined, "stored": c.get("release_queue", second["id"])}
    return out


def claim_cases(c: Case) -> dict:
    out = {"empty": c.guarded(c.queue.claim)}
    c.queued("r1", at="2026-01-01T00:00:01+00:00")
    c.lock(owner="someone", lease_until=c.at(50))
    out["held_lease"] = c.guarded(c.queue.claim)
    c.lock(owner="someone", lease_until=c.at(0))
    out["lease_expiring_now_is_free"] = c.guarded(c.queue.claim)
    out["lock_after"] = c.get("deployment_locks", "controller")
    out["second_claim_under_one_lease"] = c.guarded(c.queue.claim)
    out["fence_row"] = c.get("execution_fences", "release_queue:r1")
    return out


def claim_order_cases(c: Case) -> dict:
    out = {}
    for rid, at in (("c", "2026-01-01T00:00:02+00:00"), ("b", "2026-01-01T00:00:02+00:00"),
                    ("a", "2026-01-01T00:00:03+00:00"), ("z", None)):
        c.put("release_queue", rid, {"id": rid, "status": "queued", **({"at": at} if at else {})})
    order = []
    for _ in range(4):
        row = c.queue.claim()
        order.append(row["id"] if row else None)
        if row:
            c.queue.finish(row, {"status": "active"})
    out["order_by_at_then_id"] = order
    out["states"] = {r["id"]: r["status"] for r in c.scan("release_queue")}
    c2 = c.spawn()
    for rid in ("a", "b", "c"):
        c2.queued(rid, at="2026-01-01T00:00:0%s+00:00" % (1 + "abc".index(rid)))
    out["eligible_only_b"] = c2.guarded(c2.queue.claim, eligible=lambda row: row["id"] == "b")
    out["others_untouched"] = {r["id"]: r["status"] for r in c2.scan("release_queue")}
    c2.lock(owner=None, lease_until=None)
    out["eligible_none"] = c2.guarded(c2.queue.claim, eligible=lambda row: False)
    return out


def claim_skips(c: Case) -> dict:
    out = {}
    c.queued("future", at="1", retry_at=c.at(60))
    out["future_retry_at_skipped"] = c.guarded(c.queue.claim)
    c.queued("due", at="2", retry_at=c.at(0))
    out["due_retry_at_claimed"] = c.guarded(c.queue.claim)
    c.lock(owner=None, lease_until=None)
    c.advance(61)
    out["after_the_backoff"] = c.guarded(c.queue.claim)
    k = c.spawn()
    for status in ("failed", "cancelled", "done", "active", "rejected", "blocked"):
        k.put("release_queue", "s-" + status, {"id": "s-" + status, "status": status})
    out["terminal_rows_never_claimed"] = k.guarded(k.queue.claim, k.when(10**6))
    k.queued("s-queued")
    out["explicit_now_claims_the_queued_one"] = k.guarded(k.queue.claim, k.when(10**6))
    return out


def claim_budget_and_fence(c: Case) -> dict:
    out = {}
    c.queued("spent", at="1", attempt=c.api.POLICY.release_max_attempts)
    c.queued("next", at="2")
    out["budget_exhausted_then_next"] = c.guarded(c.queue.claim)
    out["spent_row"] = c.get("release_queue", "spent")
    for label, fence in (("regressed", {"generation": 5, "owner": None}), ("corrupted", {"generation": "x"})):
        c2 = c.spawn()
        c2.queued("r1", at="1")
        c2.put("execution_fences", "release_queue:r1", {"id": "release_queue:r1", **fence})
        out["fence_" + label] = c2.guarded(c2.queue.claim)
        out["fence_" + label + "_row"] = c2.get("release_queue", "r1")
        out["fence_" + label + "_lock"] = c2.get("deployment_locks", "controller")
    return out


def owned_cases(c: Case) -> dict:
    out = {}
    c.queued("r1", at="1")
    claim = c.queue.claim()
    out["claim"] = claim
    out["owned_current"] = c.unit(lambda tx: c.queue.owned(tx, claim))
    with c.store.transaction() as tx:
        out["owned_value"] = call(c.queue.owned, tx, claim)
    out["stale_owner"] = c.guarded(c.queue.heartbeat, {**claim, "owner": "other"})
    out["stale_generation"] = c.guarded(c.queue.heartbeat, {**claim, "generation": 2})
    out["stale_id"] = c.guarded(c.queue.heartbeat, {**claim, "id": "nope"})
    c.lock(release_id="r1", owner="foreign", lease_until=c.at(1200))
    out["foreign_lock_owner"] = c.guarded(c.queue.heartbeat, claim)
    c.lock(release_id="r1", owner=claim["owner"], lease_until=claim["lease_until"])
    c.put("execution_fences", "release_queue:r1", {"id": "release_queue:r1", "generation": 2, "owner": claim["owner"]})
    out["fence_ahead_of_row"] = c.guarded(c.queue.heartbeat, claim)
    c.put("execution_fences", "release_queue:r1", {"id": "release_queue:r1", "generation": 1, "owner": claim["owner"]})
    c.advance(100)
    out["heartbeat_extends"] = c.guarded(c.queue.heartbeat, claim)
    out["after_heartbeat"] = {"row": c.get("release_queue", "r1"), "lock": c.get("deployment_locks", "controller")}
    c.advance(200)
    out["heartbeat_explicit_now"] = c.guarded(c.queue.heartbeat, claim, c.when(10))
    out["after_explicit"] = c.get("release_queue", "r1")
    c.advance(1300)
    out["expired_lease"] = c.guarded(c.queue.heartbeat, claim)
    with c.store.transaction() as tx:
        out["owned_expired"] = call(c.queue.owned, tx, claim)
    return out


def defer_cases(c: Case) -> dict:
    out = {}
    c.queued("r1", at="1")
    claim = c.queue.claim()
    out["defer"] = c.guarded(c.queue.defer, claim, {"status": "waiting", "evidence": "fixture:ci"}, resume_after_seconds=90)
    out["lock_cleared"] = c.get("deployment_locks", "controller")
    out["claim_before_resume"] = c.guarded(c.queue.claim)
    out["stale_defer"] = c.guarded(c.queue.defer, claim, {"status": "waiting"}, resume_after_seconds=90)
    c.advance(90)
    second = c.queue.claim()
    out["claim_after_resume"] = second
    out["defer_again_zero_resume"] = c.guarded(c.queue.defer, second, {"status": "waiting"})
    out["after_zero_resume"] = c.get("release_queue", "r1")
    third = c.queue.claim()
    out["negative_string_resume"] = c.guarded(c.queue.defer, third, {"status": "waiting"}, resume_after_seconds="-5")
    fourth = c.queue.claim()
    out["string_resume"] = c.guarded(c.queue.defer, fourth, {"status": "waiting"}, resume_after_seconds="5")
    out["after_string_resume"] = c.get("release_queue", "r1")
    return out


def finish_cases(c: Case) -> dict:
    out = {}
    c.queued("r1", at="1", preserve="metadata")
    claim = c.queue.claim()
    out["success"] = c.guarded(c.queue.finish, claim, {"status": "active", "evidence": "fixture:ok"})
    out["lock_cleared"] = c.get("deployment_locks", "controller")
    out["stale_after_finish"] = c.guarded(c.queue.finish, claim, {"status": "active"})
    out["nothing_left"] = c.guarded(c.queue.claim)
    c2 = c.spawn()
    c2.queued("r1", at="1", preserve="metadata")
    steps = []
    for attempt in range(1, c.api.POLICY.release_max_attempts + 1):
        claim = c2.queue.claim()
        retry = c2.queue.finish(claim, {"status": "retry", "evidence": "fixture:infra"})
        steps.append({"attempt": claim["attempt"], "claim_again": c2.queue.claim(), "row": retry,
                      "backoff": c.api.POLICY.release_retry_seconds * 2 ** (attempt - 1)})
        c2.advance(c.api.POLICY.release_retry_seconds * 2 ** (attempt - 1))
    out["retry_to_budget"] = steps
    out["after_budget"] = {"row": c2.get("release_queue", "r1"), "claim": c2.queue.claim()}
    # The explicit-`now` walk of M7 test_queue_backoff_budget_terminal_checks_and_stale_controller.
    c3 = c.spawn()
    c3.queued("release", preserve="metadata")
    now, walk = c3.when(0), []
    for attempt in range(1, c.api.POLICY.release_max_attempts + 1):
        claim = c3.queue.claim(now)
        walk.append({"attempt": claim["attempt"], "again": c3.queue.claim(now)})
        finished = c3.queue.finish(claim, {"status": "retry", "evidence": "fixture:infra"}, now)
        walk.append({"claim_during_backoff": c3.queue.claim(now), "status": finished["status"]})
        now += timedelta(seconds=c.api.POLICY.release_retry_seconds * 2 ** (attempt - 1))
    out["explicit_now_walk"] = {"steps": walk, "final": finished, "claim": c3.queue.claim(now)}
    c3.queued("new")
    stale = c3.queue.claim(now)
    later = now + timedelta(seconds=c.api.POLICY.release_lease_seconds + 1)
    replacement = c3.queue.claim(later)
    out["stale_controller"] = c3.guarded(c3.queue.finish, stale, {"status": "active"}, later)
    checks = {"tests": {"passed": False, "evidence": "fixture:real-failure"}}
    out["replacement_finishes"] = c3.guarded(c3.queue.finish, replacement, {"status": "rejected", "checks": checks}, later)
    out["nothing_after"] = c3.queue.claim(later)
    # M7 test_queue_transient_errors_then_success.
    c4 = c.spawn()
    c4.queued("release")
    now, seen = c4.when(0), []
    for status in ("retry", "retry", "active"):
        claim = c4.queue.claim(now)
        row = c4.queue.finish(claim, {"status": status}, now)
        seen.append(row)
        now += timedelta(seconds=120)
    out["transient_then_success"] = {"rows": seen, "claim": c4.queue.claim(now)}
    # The missing `status` of a result is the caller's error, reported as raised.
    c5 = c.spawn()
    c5.queued("r1")
    claim = c5.queue.claim()
    out["result_without_status"] = c5.guarded(c5.queue.finish, claim, {})
    return out


def retry_cases(c: Case) -> dict:
    out = {"empty_reason": c.guarded(c.queue.retry, "r1", " "), "non_string_reason": c.guarded(c.queue.retry, "r1", 3)}
    c.lock(owner="someone", lease_until=c.at(60))
    out["running_controller"] = c.guarded(c.queue.retry, "r1", "fixture: owner retry")
    c.lock(owner=None, lease_until=None)
    out["unknown_release"] = c.guarded(c.queue.retry, "nope", "fixture: owner retry")
    candidate = c.rel.propose({"revision": "candidate", "base": "base", "tree": "t0", "author": AUTHOR},
                              {"checks": CHECKS})
    out["candidate_not_recoverable"] = c.guarded(c.queue.retry, candidate["id"], "fixture: owner retry")
    reviewed = c.reviewed(tree="t1")
    out["no_row_yet"] = c.guarded(c.queue.retry, reviewed["id"], "fixture: first re-arm")
    c.put("release_queue", reviewed["id"], {"id": reviewed["id"], "status": "failed", "attempt": 3, "at": "1",
                                            "owner": "x", "lease_until": c.at(-5), "retry_at": c.at(5), "reason": "fixture"})
    out["re_arm_failed"] = c.guarded(c.queue.retry, reviewed["id"], "fixture: second re-arm")
    out["claim_after"] = c.guarded(c.queue.claim)
    c.lock(owner=None, lease_until=None)
    out["lease_expired_lock_passes"] = c.guarded(c.queue.retry, reviewed["id"], "fixture: third")
    c.lock(owner="someone", lease_until=c.at(0))
    out["lease_expiring_now_passes"] = c.guarded(c.queue.retry, reviewed["id"], "fixture: fourth")
    tick = c.reviewed(tree="t-ticket", ticket=True)
    c.seed_ticket(revision="r2")
    out["superseded_ticket"] = c.guarded(c.queue.retry, tick["id"], "fixture: owner retry")
    other = c.reviewed(tree="t2")
    out["in_unit_raises"] = c.unit(lambda tx: c.queue.retry(other["id"], "fixture: in a unit", transaction=tx))
    with c.store.transaction() as tx:
        joined = c.queue.retry(other["id"], "fixture: joined", transaction=tx)
    out["in_unit_committed"] = {"value": joined, "stored": c.get("release_queue", other["id"])}
    return out


def fence_cases(c: Case) -> dict:
    """M7 tests/test_execution_fence.py (memory) for the release controller."""
    out = {}
    c.queued("r1", at="1")
    first = c.queue.claim()
    out["first"] = first
    c.advance(c.api.POLICY.release_lease_seconds + 1)
    second = c.queue.claim()
    out["second"] = second
    before = c.state()
    stale = {}
    for label, handle in (("first", first), ("first_generation_2", {**first, "generation": 2}),
                          ("second_with_first_owner", {**second, "owner": first["owner"]})):
        stale[label] = {"heartbeat": call(c.queue.heartbeat, handle), "finish": call(c.queue.finish, handle, {"status": "complete"})}
    out["stale_handles"] = {"results": stale, "wrote": c.state() != before}
    out["heartbeat_current"] = c.guarded(c.queue.heartbeat, second)
    out["finish_current"] = c.guarded(c.queue.finish, second, {"status": "complete"})
    c.put("release_queue", "r1", {"id": "r1", "status": "queued", "at": "1"})
    out["recreated_row_claim"] = c.guarded(c.queue.claim)
    out["recreated_row"] = c.get("release_queue", "r1")
    out["fence_generation"] = c.get("execution_fences", "release_queue:r1")["generation"]
    # A row restored behind the fence cannot re-arm its old holder.
    c2 = c.spawn()
    c2.queued("r1", at="1")
    old = c2.queue.claim()
    running_row = c2.get("release_queue", "r1")
    c2.advance(c.api.POLICY.release_lease_seconds + 1)
    new = c2.queue.claim()
    out["reclaimed_generation"] = new["generation"]
    c2.put("release_queue", "r1", {**running_row, "lease_until": c2.at(5000)})
    c2.lock(release_id="r1", owner=old["owner"], lease_until=c2.at(5000))
    before = c2.state()
    out["restored_behind_fence"] = {"heartbeat": call(c2.queue.heartbeat, old), "finish": call(c2.queue.finish, old, {"status": "x"}),
                                    "wrote": c2.state() != before}
    c2.put("execution_fences", "release_queue:r1", {"id": "release_queue:r1", "generation": 1, "owner": "someone-else"})
    out["fence_owner_differs"] = c2.guarded(c2.queue.heartbeat, old)
    c2.put("execution_fences", "release_queue:r1", {"id": "release_queue:r1", "generation": 1, "owner": old["owner"]})
    out["fence_matches_again"] = c2.guarded(c2.queue.heartbeat, old)
    # The fence `owner` may be None (legacy) and an absent fence passes.
    c3 = c.spawn()
    c3.queued("r1", at="1")
    claim = c3.queue.claim()
    c3.put("execution_fences", "release_queue:r1", {"id": "release_queue:r1", "generation": 1, "owner": None})
    out["fence_owner_none"] = c3.guarded(c3.queue.heartbeat, claim)
    del c3.store.data["execution_fences", "release_queue:r1"]
    out["fence_absent_legacy"] = c3.guarded(c3.queue.heartbeat, claim)
    return out


def sequential_claims(c: Case) -> dict:
    """M7 test_concurrent_controllers_claim_only_one_release, sequentially on the memory store."""
    for name in ("one", "two"):
        c.queued(name, at=name)
    claims = [c.api.queue(c.store).claim() for _ in range(4)]
    return {"claims": claims, "claimed": sum(claim is not None for claim in claims),
            "lock": c.get("deployment_locks", "controller")}


# ---- group 2: verify ---------------------------------------------------------------------------------------

def verify_cases(c: Case) -> dict:
    out = {}
    passed = {name: {"passed": True, "evidence": "fixture:" + name} for name in CHECKS}
    candidate = c.rel.propose({"revision": "candidate", "base": "base", "tree": "t0", "author": AUTHOR}, {"checks": CHECKS})
    out["reviews_incomplete"] = c.guarded(c.rel.verify, candidate["id"], "candidate", candidate["policy_hash"], passed)
    out["unknown_release"] = c.guarded(c.rel.verify, "nope", "candidate", "x", passed)
    release = c.reviewed(tree="t1")
    rid, ph = release["id"], release["policy_hash"]
    out["stale_revision"] = c.guarded(c.rel.verify, rid, "other", ph, passed)
    out["stale_evaluator"] = c.guarded(c.rel.verify, rid, "candidate", "other", passed)
    out["missing_check"] = c.guarded(c.rel.verify, rid, "candidate", ph, {k: passed[k] for k in CHECKS[:2]})
    out["extra_check"] = c.guarded(c.rel.verify, rid, "candidate", ph, {**passed, "lint": passed["tests"]})
    for label, bad in (("not_a_dict", 1), ("passed_not_bool", {"passed": 1, "evidence": "e"}),
                       ("no_evidence", {"passed": True}), ("empty_evidence", {"passed": True, "evidence": ""})):
        out["check_" + label] = c.guarded(c.rel.verify, rid, "candidate", ph, {**passed, "tests": bad})
    out["in_unit_raises"] = c.unit(lambda tx: c.rel.verify(rid, "candidate", ph, passed, transaction=tx))
    out["verified"] = c.guarded(c.rel.verify, rid, "candidate", ph, passed)
    out["verify_again"] = c.guarded(c.rel.verify, rid, "candidate", ph, passed)
    failed = c.reviewed(tree="t2")
    out["one_failed_rejected"] = c.guarded(c.rel.verify, failed["id"], "candidate", failed["policy_hash"],
                                           {**passed, "cli_start": {"passed": False, "evidence": "fixture:failed"}})
    skipped = c.reviewed(tree="t3")
    out["skipped_check_rejected"] = c.guarded(
        c.rel.verify, skipped["id"], "candidate", skipped["policy_hash"],
        {**passed, "cli_file_task": {"passed": False, "skipped": True, "evidence": "fixture:not-run"}})
    tick = c.reviewed(tree="t-ticket", ticket=True)
    c.seed_ticket(revision="r2")
    out["superseded_ticket"] = c.guarded(c.rel.verify, tick["id"], "candidate", tick["policy_hash"], passed)
    joined = c.reviewed(tree="t4")
    with c.store.transaction() as tx:
        out["in_unit_commits"] = call(c.rel.verify, joined["id"], "candidate", joined["policy_hash"], passed, transaction=tx)
    out["in_unit_stored"] = c.get("releases", joined["id"])["status"]
    return out


# ---- group 3: promote / rollback ---------------------------------------------------------------------------

def promote_cases(c: Case) -> dict:
    out = {}
    out["unknown"] = c.guarded(c.rel.promote, "nope", None)
    reviewed = c.reviewed(tree="t0")
    out["not_verified"] = c.guarded(c.rel.promote, reviewed["id"], None)
    a = c.verified(tree="ta")
    out["active_changed_expected_other"] = c.guarded(c.rel.promote, a["id"], "someone")
    tampered = c.verified(tree="tt")
    c.put("releases", tampered["id"], {**tampered, "policy_hash": "tampered"})
    out["evaluator_changed"] = c.guarded(c.rel.promote, tampered["id"], None)
    out["first_promotion"] = c.guarded(c.rel.promote, a["id"], None)
    out["first_state"] = {"active": c.get("deployment", "active"), "release": c.get("releases", a["id"])["status"],
                          "history": c.get("deployment_history", a["id"]), "control": c.get("research_control", "activation")}
    b = c.verified(tree="tb")
    out["active_changed_expected_none"] = c.guarded(c.rel.promote, b["id"], None)
    c.advance(10)
    out["second_promotion"] = c.guarded(c.rel.promote, b["id"], a["id"])
    out["second_state"] = {"active": c.get("deployment", "active"), "history": c.get("deployment_history", a["id"]),
                           "previous": c.get("releases", a["id"])["status"], "release": c.get("releases", b["id"])["status"]}
    out["events"] = sorted((e["type"], e["release_id"]) for e in c.scan("events"))
    out["already_active"] = c.guarded(c.rel.promote, b["id"], b["id"])
    tick = c.verified(tree="t-ticket", ticket=True)
    c.seed_ticket(revision="r2")
    out["superseded_ticket"] = c.guarded(c.rel.promote, tick["id"], b["id"])
    j = c.verified(tree="tj")
    out["in_unit_raises"] = c.unit(lambda tx: c.rel.promote(j["id"], b["id"], transaction=tx))
    with c.store.transaction() as tx:
        out["in_unit_commits"] = call(c.rel.promote, j["id"], b["id"], transaction=tx)
    out["in_unit_active"] = c.get("deployment", "active")
    return out


def promote_audit_cases(c: Case) -> dict:
    out = {}
    audit = c.verified(tree="tau", audit_lifecycle_version=1)
    out["audit_with_canary"] = c.guarded(c.rel.promote, audit["id"], None)
    out["audit_state"] = {"graph": c.get("research_control", "graph"), "activation": c.get("research_control", "activation")}
    c2 = c.spawn()
    bare = c2.verified(tree="tbare", audit_lifecycle_version=1, checks=["tests"])
    out["audit_without_canary_checks"] = c2.guarded(c2.rel.promote, bare["id"], None)
    out["audit_without_canary_state"] = {"active": c2.get("deployment", "active"), "graph": c2.get("research_control", "graph")}
    failing = c2.reviewed(tree="tfail", audit_lifecycle_version=2)
    verdict = c2.rel.verify(failing["id"], "candidate", failing["policy_hash"],
                            {"tests": {"passed": True, "evidence": "e"}, "cli_start": {"passed": True, "evidence": "e"},
                             "cli_file_task": {"passed": True, "evidence": "e"}})
    out["audit_version_2_is_not_audit"] = c2.guarded(c2.rel.promote, verdict["id"], None)
    out["version_2_state"] = c2.get("research_control", "activation")
    # A paused activation when the candidate declares no audit lifecycle.
    c3 = c.spawn()
    c3.put("research_control", "activation", {"status": "active", "release_id": "old", "revision": "old"})
    plain = c3.verified(tree="tplain")
    out["plain_pauses_activation"] = c3.guarded(c3.rel.promote, plain["id"], None)
    out["paused_activation"] = c3.get("research_control", "activation")
    c4 = c.spawn()
    plain = c4.verified(tree="tplain")
    c4.guarded(c4.rel.promote, plain["id"], None)
    out["no_activation_row_stays_none"] = c4.get("research_control", "activation")
    return out


def two_active(c: Case, **second):
    a = c.verified(tree="ta")
    c.rel.promote(a["id"], None)
    c.advance(10)
    b = c.verified(tree="tb", **second)
    c.rel.promote(b["id"], a["id"])
    c.advance(10)
    return a, b


def rollback_cases(c: Case) -> dict:
    out = {"empty_reason": c.guarded(c.rel.rollback, "x", ""), "no_active": c.guarded(c.rel.rollback, "x", "fixture: bad")}
    a = c.verified(tree="ta")
    c.rel.promote(a["id"], None)
    out["stale"] = c.guarded(c.rel.rollback, "other", "fixture: bad")
    out["no_known_good_previous"] = c.guarded(c.rel.rollback, a["id"], "fixture: bad")
    c.advance(10)
    b = c.verified(tree="tb")
    c.rel.promote(b["id"], a["id"])
    c.advance(10)
    out["rollback"] = c.guarded(c.rel.rollback, b["id"], "fixture: bad release")
    out["state"] = {"active": c.get("deployment", "active"), "a": c.get("releases", a["id"])["status"],
                    "b": c.get("releases", b["id"]), "control": c.get("research_control", "activation")}
    out["events"] = sorted((e["type"], e["release_id"], e.get("reason")) for e in c.scan("events"))
    out["rollback_again"] = c.guarded(c.rel.rollback, b["id"], "fixture: bad release")
    c2 = c.spawn()
    c2.put("deployment", "active", {"release_id": "ghost", "revision": "r", "previous": {"release_id": "older"}, "at": c2.at()})
    out["active_record_missing"] = c2.guarded(c2.rel.rollback, "ghost", "fixture: bad")
    # No history row: the pointer's own `previous` is what is restored; the previous release row may be absent.
    c3 = c.spawn()
    rel = c3.verified(tree="tb")
    c3.rel.promote(rel["id"], None)
    c3.put("deployment", "active", {**c3.get("deployment", "active"), "previous": {"release_id": "older"}})
    out["no_history_row"] = c3.guarded(c3.rel.rollback, rel["id"], "fixture: bad")
    out["no_history_state"] = c3.get("deployment", "active")
    return out


def rollback_hook_cases(c: Case) -> dict:
    out = {}
    previous = {"id": "h1", "revision": "older", "status": "active", "marker": "previous_active"}
    for label, hook in (
        ("previous_active_restored", {"id": "h1", "revision": "candidate", "status": "active", "previous_active": previous}),
        ("no_previous_active", {"id": "h1", "revision": "candidate", "status": "active"}),
        ("other_revision_untouched", {"id": "h1", "revision": "other", "status": "active", "previous_active": previous}),
        ("empty_previous_active", {"id": "h1", "revision": "candidate", "status": "active", "previous_active": {}}),
        ("hook_row_missing", None),
    ):
        k = c.spawn()
        a, b = two_active(k, hook_id="h1")
        if hook is not None:
            k.put("hooks", "h1", hook)
        out[label] = {"rollback": k.guarded(k.rel.rollback, b["id"], "fixture: bad hook"), "hook": k.get("hooks", "h1")}
    k = c.spawn()
    a, b = two_active(k)
    k.put("hooks", "h1", {"id": "h1", "revision": "candidate", "status": "active"})
    out["candidate_without_hook_id"] = {"rollback": k.guarded(k.rel.rollback, b["id"], "fixture: bad"), "hook": k.get("hooks", "h1")}
    # The research activation is paused and bound to the restored deployment.
    k = c.spawn()
    audit_a = k.verified(tree="ta")
    k.rel.promote(audit_a["id"], None)
    audit_b = k.verified(tree="tb", audit_lifecycle_version=1)
    k.rel.promote(audit_b["id"], audit_a["id"])
    out["activation_before"] = k.get("research_control", "activation")
    out["activation_paused"] = k.guarded(k.rel.rollback, audit_b["id"], "fixture: audit regression")
    out["activation_after"] = {"activation": k.get("research_control", "activation"), "graph": k.get("research_control", "graph")}
    return out


# ---- group 4: evaluator migration --------------------------------------------------------------------------

def migration_success(c: Case) -> dict:
    out = {}
    source = c.rejected()
    before = c.state()
    child = c.migrated(source)
    after = c.state()
    out["child"] = child
    out["new_records"] = sorted(set(after) - set(before))
    out["source_untouched"] = {k: after[k] for k in before} == before
    out["ids"] = {"successor": child["id"] == c.api.evaluator_successor_id(source["id"]), "differs": child["id"] != source["id"]}
    out["policy_hash_changed"] = child["policy_hash"] != source["policy_hash"]
    out["no_queue_or_deployment_rows"] = not any(k.split("/")[0] in {"release_queue", "images", "promotion_intents", "deployment"}
                                                 for k in set(after) - set(before))
    out["event"] = c.get("events", "release.evaluator_migration_requested:" + child["id"])
    out["verify_with_source_hash"] = c.guarded(c.rel.verify, child["id"], "candidate", source["policy_hash"],
                                               {n: {"passed": True, "evidence": "fixture:" + n} for n in source["checks"]})
    out["verify_with_successor_hash"] = c.guarded(c.rel.verify, child["id"], "candidate", child["policy_hash"],
                                                  {n: {"passed": True, "evidence": "fixture:" + n} for n in CHECKS})
    return out


def migration_replay(c: Case) -> dict:
    out = {}
    source = c.rejected()
    child = c.migrated(source)
    out["replay"] = c.guarded(c.migrated, source)
    out["replay_equal"] = c.migrated(source) == child
    for label, changed in (("revision", {"evaluator_revision": "d" * 40}), ("evidence", {"evidence": "sha256:" + "c" * 64}),
                           ("patch", {"patch_sha256": "c" * 64}), ("paths", {"paths": ["tests/other.py"]})):
        out["changed_" + label] = c.guarded(c.migrated, source, approval=approval_for(source, **changed))
    out["expected_policy_hash_other"] = c.guarded(c.migrated, source, expected_policy_hash="other")
    out["expected_revision_other"] = c.guarded(c.migrated, source, expected_revision="other")
    org = c.rel.org
    second = next(a for a in org.agents.values() if a.role == "conductor")
    c.org_as(lambda actor_id, role=None: second)
    out["conflicting_actor_replay"] = c.guarded(c.migrated, source, actor="conductor-replacement")
    return out


def migration_blocks(c: Case) -> dict:
    out = {}
    source = c.rejected()
    c.plain_successor_row(source)
    before = c.state()
    out["plain_blocks_migration"] = c.guarded(c.migrated, source)
    out["unchanged"] = c.state() == before
    out["reverify_replay"] = UNREACHABLE_REVERIFY
    c2 = c.spawn()
    source = c2.rejected()
    child = c2.migrated(source)
    before = c2.state()
    out["migration_blocks_plain"] = UNREACHABLE_REVERIFY
    out["migration_replay_after"] = {"same": call(c2.migrated, source) == {"value": child}, "unchanged": c2.state() == before}
    return out


def migration_sources(c: Case) -> dict:
    out = {}
    source = c.rejected()
    out["stale_revision"] = c.guarded(c.migrated, source, expected_revision="other")
    out["stale_policy_hash"] = c.guarded(c.migrated, source, expected_policy_hash="other")
    reviewed = c.reviewed(tree="tree-2")
    out["not_check_rejected"] = c.guarded(c.migrated, reviewed, approval=approval_for(reviewed))
    out["unknown_source"] = c.guarded(c.rel.request_evaluator_migration, "nope", "conductor", expected_revision="candidate",
                                      expected_policy_hash="x", approval=approval_for({"id": "nope", "candidate": {"base": "base"}}),
                                      resolved_pin=c.api.expected_evaluator_pin(approval_for({"id": "nope", "candidate": {"base": "base"}})))
    c.lock(lease_until=c.at(300))
    out["controller_running"] = c.guarded(c.migrated, source)
    c.lock(owner=None, lease_until=None)
    c.put("release_queue", source["id"], {"id": source["id"], "status": "running"})
    out["queue_row_running"] = c.guarded(c.migrated, source)
    c.put("release_queue", source["id"], {"id": source["id"], "status": "failed"})
    c.put("promotion_intents", source["id"], {"id": source["id"]})
    out["promotion_effects"] = c.guarded(c.migrated, source)
    return out


APPROVAL_CASES = [
    ("lead:improvement", {}), ("conductor", {"approved_by": AUTHOR}), ("conductor", {"approved_by": "nobody"}),
    ("conductor", {"source_release_id": "other"}), ("conductor", {"base": "other-base"}),
    ("conductor", {"paths": ["src/app.py"]}), ("conductor", {"paths": ["tests/../src/app.py"]}),
    ("conductor", {"paths": []}), ("conductor", {"paths": ["tests/b.py", "tests/a.py"]}),
    ("conductor", {"paths": ["tests/a.py", "tests/a.py"]}), ("conductor", {"paths": "tests/a.py"}),
    ("conductor", {"evaluator_revision": "E"}), ("conductor", {"evaluator_tree": "f" * 39}),
    ("conductor", {"patch_sha256": "a" * 63}), ("conductor", {"evidence": "fixture:evidence"}),
    ("conductor", {"evidence": "sha256:xyz"}), ("conductor", {"patch_sha256": 7}),
    ("conductor", {"approved_by": ""}), ("conductor", {"base": ""}),
]


def migration_approvals(c: Case) -> dict:
    out = {}
    source = c.rejected()
    before = c.state()
    for index, (actor, overrides) in enumerate(APPROVAL_CASES):
        out["approval_%02d" % index] = call(c.migrated, source, actor=actor, approval=approval_for(source, **overrides))
    out["extra_key"] = call(c.migrated, source, approval={**approval_for(source), "note": "extra"})
    out["missing_key"] = call(c.migrated, source, approval={k: v for k, v in approval_for(source).items() if k != "evidence"})
    out["not_a_dict"] = call(c.migrated, source, approval=["x"])
    out["nothing_written"] = c.state() == before
    return out


def migration_evaluator_rules(c: Case) -> dict:
    out = {}
    source = c.rejected()
    hexed = {"revision": "c" * 40, "base": "d" * 40, "tree": "tree-hex", "author": AUTHOR}
    other = c.rel.propose(hexed, {"checks": CHECKS})
    for actor in ("lead:improvement", "conductor"):
        c.rel.review(other["id"], actor, "c" * 40, True, "fixture:review")
    checks = {"tests": {"passed": False, "evidence": "fixture:failed"},
              **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"} for name in CHECKS[1:]}}
    other = c.rel.verify(other["id"], "c" * 40, other["policy_hash"], checks)
    for evaluator in ("c" * 40, "d" * 40):
        out["evaluator_" + evaluator[0]] = c.guarded(c.migrated, other, expected_revision="c" * 40,
                                                     approval=approval_for(other, evaluator_revision=evaluator))
    c.author_approves()
    out["author_cannot_approve"] = c.guarded(c.migrated, source, approval=approval_for(source, approved_by=AUTHOR))
    return out


def migration_unit(c: Case) -> dict:
    out = {}
    source = c.rejected()
    out["in_unit_raises"] = c.unit(lambda tx: c.migrated(source, transaction=tx))
    with c.store.transaction() as tx:
        child = c.migrated(source, transaction=tx)
        out["visible_inside"] = tx.get("releases", child["id"]) == child
    out["committed"] = c.get("releases", child["id"]) == child
    return out


def failed_migrated(c: Case):
    source = c.rejected()
    child = c.migrated(source)
    failed = c.rel.verify(child["id"], "candidate", child["policy_hash"], {
        "tests": {"passed": False, "evidence": "fixture:evaluator-tests-failed"},
        **{name: {"passed": False, "skipped": True, "evidence": "fixture:not-run"} for name in ("cli_start", "cli_file_task")}})
    assert failed["status"] == "rejected"
    return source, failed


def migration_not_again(c: Case) -> dict:
    out = {}
    source, failed = failed_migrated(c)
    before = c.state()
    out["reverify_again"] = UNREACHABLE_REVERIFY
    out["migrate_again"] = call(c.migrated, failed, approval=approval_for(failed, base=failed["candidate"]["base"], evaluator_revision="d" * 40))
    out["migrated_source_not_again"] = call(c.migrated, source)
    out["unchanged_after"] = c.state() == before or {"differs": True}
    c2 = c.spawn()
    _, failed = failed_migrated(c2)
    legacy = {k: v for k, v in c2.get("releases", failed["id"]).items() if k != "evaluator_migration"}
    c2.put("releases", failed["id"], legacy)
    before = c2.state()
    out["non_base_policy_without_receipt"] = call(c2.migrated, legacy, approval=approval_for(legacy))
    out["without_receipt_unchanged"] = c2.state() == before
    return out


def migration_pins(c: Case) -> dict:
    out = {}
    source = c.rejected()
    base = c.api.expected_evaluator_pin(approval_for(source))
    before = c.state()
    for field in ("evaluator_revision", "parent", "base", "evaluator_tree", "paths", "patch_sha256", "missing", "extra"):
        resolved = dict(base)
        if field == "missing":
            del resolved["patch_sha256"]
        elif field == "extra":
            resolved["files"] = []
        else:
            resolved[field] = ["tests/other.py"] if field == "paths" else "0" * 40
        out["pin_" + field] = call(c.migrated, source, resolved_pin=resolved)
    out["nothing_written"] = c.state() == before
    out["then_migrates"] = call(c.migrated, source)["value"]["status"]
    c2 = c.spawn()
    source = c2.rejected()
    before = c2.state()
    out["resolved_pin_required"] = call(c2.rel.request_evaluator_migration, source["id"], "conductor", expected_revision="candidate",
                                        expected_policy_hash=source["policy_hash"], approval=approval_for(source))
    out["required_unchanged"] = c2.state() == before
    return out


def migration_either_order(c: Case) -> dict:
    out = {}
    source = c.rejected()
    c.plain_successor_row(source)
    out["plain_first_then_migrate"] = {"migrate": call(c.migrated, source), "successors": c.successors(source)}
    c2 = c.spawn()
    source = c2.rejected()
    out["migrate_first_then_plain"] = {"migrate": call(c2.migrated, source)["value"]["status"], "plain": UNREACHABLE_REVERIFY,
                                       "successors": c2.successors(source)}
    return out


# ---- group 5: environment reverification -------------------------------------------------------------------

def env_success(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    before = c.state()
    child = c.env_reverify(source)
    after = c.state()
    out["child"] = child
    out["new_records"] = sorted(set(after) - set(before))
    out["source_untouched"] = {k: after[k] for k in before} == before
    out["id_is_environment_successor"] = child["id"] == c.api.environment_successor_id(source["id"])
    out["event"] = c.get("events", "release.environment_reverification_requested:" + child["id"])
    out["verify_empty"] = c.guarded(c.rel.verify, child["id"], "candidate", child["policy_hash"], {})
    return out


def env_replay(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    child = c.env_reverify(source)
    before = c.state()
    out["replay_equal"] = c.env_reverify(source) == child
    out["replay_wrote"] = c.state() != before
    for label, changed in (("controller", {"controller_revision": "8" * 40}), ("fix_evidence", {"fix_evidence": "sha256:" + "e" * 64}),
                           ("lane", {"lane": "other-lane"}), ("intent", {"intent_id": "control-intent-2"})):
        out["changed_" + label] = call(c.env_reverify, source, approval=env_approval_for(source, **changed),
                                       resolved_controller=changed.get("controller_revision", CONTROLLER))
    out["other_policy_hash"] = call(c.env_reverify, source, approval=env_approval_for(source, source_policy_hash="other"))
    out["nothing_written"] = c.state() == before
    return out


def env_blocks(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    child = c.env_reverify(source)
    before = c.state()
    out["plain_blocked"] = UNREACHABLE_REVERIFY
    out["evaluator_blocked"] = call(c.migrated, source)
    out["replay"] = c.env_reverify(source) == child
    out["unchanged"] = c.state() == before
    # Labelled crafted record: the source-key block holds even where the source shape would allow it.
    k = c.spawn()
    plain = k.rejected()
    key = c.api.environment_successor_id(plain["id"])
    k.put("releases", key, {"id": key, "reverify_of": plain["id"], "fixture": True})
    before = k.state()
    out["injected_env_blocks_evaluator"] = call(k.migrated, plain)
    out["injected_env_blocks_plain"] = UNREACHABLE_REVERIFY
    out["injected_unchanged"] = k.state() == before
    for kind, builder in (("plain", c.api.reverification_successor_id), ("evaluator", c.api.evaluator_successor_id)):
        k = c.spawn()
        source = k.migrated_rejected()
        key = builder(source["id"])
        k.put("releases", key, {"id": key, "reverify_of": source["id"], "fixture": True})
        before = k.state()
        out["existing_" + kind + "_blocks_environment"] = call(k.env_reverify, source)
        out["existing_" + kind + "_unchanged"] = k.state() == before
    return out


def env_approvals(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    wrong = env_approval_for(source)
    cases = [("short_controller", {**wrong, "controller_revision": "7" * 39}), ("non_hex_controller", {**wrong, "controller_revision": "G" * 40}),
             ("upper_controller", {**wrong, "controller_revision": "A" * 40}), ("int_controller", {**wrong, "controller_revision": 7}),
             ("fix_evidence_no_prefix", {**wrong, "fix_evidence": "d" * 64}), ("fix_evidence_short", {**wrong, "fix_evidence": "sha256:dd"}),
             ("old_plan_sha_short", {**wrong, "old_plan_sha256": "c" * 10}), ("kind", {**wrong, "kind": "evaluator_migration"}),
             ("other_release", {**wrong, "source_release_id": "other"}), ("extra_key", {**wrong, "extra": "x"}),
             ("missing_lane", {k: v for k, v in wrong.items() if k != "lane"}), ("empty_lane", {**wrong, "lane": ""}),
             ("not_a_dict", ["x"])]
    before = c.state()
    for label, approval in cases:
        out[label] = call(c.env_reverify, source, approval=approval)
    out["nothing_written"] = c.state() == before
    return out


def env_pins_and_controller(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    before = c.state()
    pinned = c.api.expected_evaluator_pin(source["evaluator_migration"])
    for field in ("evaluator_revision", "evaluator_tree", "patch_sha256", "paths", "parent"):
        out["pin_" + field] = call(c.env_reverify, source,
                                   resolved_pin={**pinned, field: ["tests/other.py"] if field == "paths" else "0" * len(pinned[field])})
    out["pin_missing"] = call(c.env_reverify, source, resolved_pin={})
    for label, resolved in (("unavailable_none", None), ("unavailable_short", "7" * 39), ("unavailable_int", 7),
                            ("unavailable_upper", "A" * 40), ("mismatch", "8" * 40)):
        out["controller_" + label] = call(c.env_reverify, source, resolved_controller=resolved)
    out["nothing_written"] = c.state() == before
    plain = c.spawn()
    base = plain.rejected()
    before = plain.state()
    out["not_migrated_source"] = call(plain.rel.request_environment_reverification, base["id"], "conductor",
                                      expected_revision="candidate", expected_policy_hash=base["policy_hash"],
                                      approval=env_approval_for(base), resolved_pin={}, resolved_controller=CONTROLLER)
    out["not_migrated_unchanged"] = plain.state() == before
    return out


def env_depth_and_checks(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    child = c.env_reverify(source)
    again = c.rel.verify(child["id"], "candidate", child["policy_hash"], ENV_CHECKS)
    before = c.state()
    out["again_status"] = again["status"]
    out["depth"] = call(c.env_reverify, again)
    out["migrate_again"] = call(c.migrated, again)
    out["reverify_again"] = UNREACHABLE_REVERIFY
    out["unchanged"] = c.state() == before
    for label, tests in (("failed", {"passed": False, "evidence": "fixture:tests-failed"}),
                         ("skipped", {"passed": True, "skipped": True, "evidence": "fixture:not-run"})):
        k = c.spawn()
        src = k.migrated_rejected({**ENV_CHECKS, "tests": tests})
        before = k.state()
        out["tests_" + label] = call(k.env_reverify, src)
        out["tests_" + label + "_unchanged"] = k.state() == before
    k = c.spawn()
    src = k.migrated_rejected({**ENV_CHECKS, "cli_file_task": {"passed": False, "skipped": True, "evidence": "fixture:not-run"}})
    out["skipped_only_environment_failure"] = call(k.env_reverify, src)
    k = c.spawn()
    src = k.migrated_rejected({**ENV_CHECKS, "cli_file_task": {"passed": True, "evidence": "fixture:ok"}})
    out["no_failed_check_at_all"] = call(k.env_reverify, src)
    return out


def env_authority(c: Case) -> dict:
    out = {}
    source = c.migrated_rejected()
    before = c.state()
    out["actor"] = call(c.env_reverify, source, actor="lead:improvement")
    out["unknown_actor"] = call(c.env_reverify, source, actor="nobody")
    out["approver_not_conductor"] = call(c.env_reverify, source, approval=env_approval_for(source, approved_by=AUTHOR))
    out["approval_policy_hash"] = call(c.env_reverify, source, approval=env_approval_for(source, source_policy_hash="other"))
    out["expected_hash"] = call(c.env_reverify, source, expected_policy_hash="other")
    out["expected_revision"] = call(c.env_reverify, source, expected_revision="other")
    out["unknown_source"] = call(c.rel.request_environment_reverification, "nope", "conductor", expected_revision="candidate",
                                 expected_policy_hash="x", approval=env_approval_for({"id": "nope", "policy_hash": "x"}),
                                 resolved_pin={}, resolved_controller=CONTROLLER)
    c.lock(lease_until=c.at(300))
    out["controller_running"] = call(c.env_reverify, source)
    out["nothing_written"] = c.state() == before or {"lock_only": True}
    c2 = c.spawn()
    src = c2.migrated_rejected()
    c2.author_approves()
    before = c2.state()
    out["author_cannot_approve"] = call(c2.env_reverify, src, approval=env_approval_for(src, approved_by=AUTHOR))
    out["author_unchanged"] = c2.state() == before
    return out


def env_sequential_conflict(c: Case) -> dict:
    source = c.migrated_rejected()
    results = {}
    for name, revision in (("first", CONTROLLER), ("second", "8" * 40)):
        results[name] = call(c.env_reverify, source, resolved_controller=revision,
                             approval=env_approval_for(source, controller_revision=revision))
    return {"results": results, "successors": c.successors(source)}


# ---- run ---------------------------------------------------------------------------------------------------

GROUPS = {
    "queue": [("enqueue", enqueue_cases), ("claim", claim_cases), ("claim_order_and_eligible", claim_order_cases),
              ("claim_skips", claim_skips), ("claim_budget_and_fence", claim_budget_and_fence),
              ("owned_and_heartbeat", owned_cases), ("defer", defer_cases), ("finish", finish_cases),
              ("retry", retry_cases), ("fence", fence_cases), ("sequential_claims", sequential_claims)],
    "verify": [("verify", verify_cases)],
    "promote_rollback": [("promote", promote_cases), ("promote_audit", promote_audit_cases),
                         ("rollback", rollback_cases), ("rollback_hooks", rollback_hook_cases)],
    "evaluator_migration": [("success", migration_success), ("replay", migration_replay), ("blocks", migration_blocks),
                            ("sources", migration_sources), ("approvals", migration_approvals),
                            ("evaluator_rules", migration_evaluator_rules), ("unit", migration_unit),
                            ("not_again", migration_not_again), ("pins", migration_pins),
                            ("either_order", migration_either_order)],
    "environment_reverification": [("success", env_success), ("replay", env_replay), ("blocks", env_blocks),
                                   ("approvals", env_approvals), ("pins_and_controller", env_pins_and_controller),
                                   ("depth_and_checks", env_depth_and_checks), ("authority", env_authority),
                                   ("sequential_conflict", env_sequential_conflict)],
}


def run(api) -> dict:
    out = {}
    for group, cases in GROUPS.items():
        out[group] = {}
        for name, fn in cases:
            c = Case(api)
            c.children.append(c)
            try:
                result = fn(c)
            except Exception as exc:  # an unexpected failure of the characterized operation is itself compared
                result = {"case_error": type(exc).__name__, "message": str(exc)[:200]}
            out[group][name] = {"steps": result, "stores": [sorted([k, v] for k, v in k.state().items())
                                                            for k in c.children]}
    return out
