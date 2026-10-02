"""Shared S8 scenario steps (`review.releases_audits`): M7 `Releases.reconcile_audits` and `Releases.request_reverification`, characterized
BEFORE the two methods move into the target review `Releases` (DESIGN-s8 §19.1: R-ra1..R-ra4). The golden is placement-neutral: it observes
SOURCE behaviour only; the move is a later commit of the same pilot.

Each case is labelled with the M7 test it mirrors (`m7_test`), or `none` (a branch no M7 test names). M7's `tests/test_release_reverification.py`
drives `request_reverification` through the whole propose/review/verify/queue/runner fixtures, and `tests/test_research_audits.py` drives
`reconcile_audits` through the audit lifecycle; the golden is APPLICATION-level instead: the release rows are PLANTED in the shape those
operations leave them. Left out (they need the runner, the queue, a real clock fault or PostgreSQL, other families' code): the normal
queue-and-runner re-execution of the successor (`test_normal_queue_and_runner_execute_every_check_for_the_successor`), the concurrent-request
and the transaction-fault tests (a thread race and a FaultStore), the PostgreSQL parametrizations and the ticket-binding cases (the ticket
binding is intake's, injected; the planted candidates carry no ticket).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. LABELLED plantings (nothing here is an actual
Codex, Git, Docker, model or production verification):
- the store is a `MemoryStore`; `releases`, `deployment`, `research_control`, `release_queue`, `deployment_locks` and `promotion_intents` rows
  are planted in the shape their owners write;
- `api.releases(store)` is the side's `Releases` over the packaged organization; `api.digest` and the three successor-id functions are the
  side's pure vocabulary;
- the clock is the harness's, advanced one millisecond after every call; an explicit `now` is passed except in the labelled default-clock case.
The whole-store digest (16 hex) is recorded before and after every call, with a `wrote` flag.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

REV = "a" * 40
CAND = "candidate"
CHECKS = ["tests", "cli_start", "cli_file_task"]
NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
REQUEST = {"actor": "conductor", "expected_revision": CAND, "reason": "fixture: short TEMP diagnosis", "evidence": "fixture:diagnosis-receipt"}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_digest(store) -> str:
    with store.transaction() as tx:
        return canonical_digest([[r["bucket"], r["id"], canonical_digest(r["body"])] for r in tx.records()])[:16]


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def outcome(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": value}


class World:
    def __init__(self, api):
        self.api = api
        self.store = api.MemoryStore()
        self.releases = api.releases(self.store)

    def call(self, fn, *args, **kwargs):
        """One call with the whole-store digest before and after, then one tick of the fake clock."""
        before = store_digest(self.store)
        out = outcome(fn, *args, **kwargs)
        after = store_digest(self.store)
        self.api.advance(0.001)
        return {**out, "store_before": before, "store_after": after, "wrote": before != after}

    def reconcile(self):
        return self.call(self.releases.reconcile_audits)

    def reverify(self, release_id="release-0001", actor="conductor", revision=CAND, policy_hash=None, reason=REQUEST["reason"],
                 evidence=REQUEST["evidence"], **kwargs):
        if policy_hash is None:
            source = get(self.store, "releases", release_id)
            policy_hash = source["policy_hash"] if source else "no-such-release"
        return self.call(self.releases.request_reverification, release_id, actor, revision, policy_hash, reason, evidence, **kwargs)

    def successor(self, release_id="release-0001"):
        return get(self.store, "releases", self.api.reverification_successor_id(release_id))

    def event(self, release_id="release-0001"):
        return get(self.store, "events", "release.reverification_requested:" + self.api.reverification_successor_id(release_id))

    def events(self):
        with self.store.transaction() as tx:
            return sorted(r["id"] for r in tx.records() if r["bucket"] == "events")


# ---- planted rows --------------------------------------------------------------------------------------------------------------
def active_release(w, *, lifecycle=1, policy_hash=None, reviews="complete", checks="complete", revision=REV, deployment_revision=REV,
                   status="active", author="worker:implementation"):
    """The ACTIVE audit-lifecycle release `release-0001` as M7's `Releases.promote` leaves it (LABELLED: planted)."""
    policy = {"checks": list(CHECKS)}
    candidate = {"revision": revision, "tree": "fixture-tree", "base": "fixture-base", "author": author}
    if lifecycle is not None:
        candidate["audit_lifecycle_version"] = lifecycle
    accepted = [{"actor": "lead:improvement", "accepted": True, "revision": revision, "evidence": "fixture-review"},
                {"actor": "conductor", "accepted": True, "revision": revision, "evidence": "fixture-review"}]
    if reviews == "missing_conductor":
        accepted = accepted[:1]
    elif reviews == "no_evidence":
        accepted = [{**r, "evidence": ""} for r in accepted]
    elif reviews == "other_revision":
        accepted = [{**r, "revision": "rev-other"} for r in accepted]
    elif reviews == "not_accepted":
        accepted = [{**r, "accepted": False} for r in accepted]
    results = {k: {"passed": True, "evidence": "fixture-canary-not-production"} for k in CHECKS}
    if checks == "failed":
        results["tests"] = {"passed": False, "evidence": "fixture"}
    elif checks == "no_evidence":
        results["cli_start"] = {"passed": True}
    elif checks == "missing":
        del results["cli_file_task"]
    put(w.store, "releases", "release-0001", {"id": "release-0001", "status": status, "candidate": candidate, "policy": policy,
                                              "policy_hash": policy_hash or w.api.digest(policy), "reviews": accepted, "checks": results})
    put(w.store, "deployment", "active", {"release_id": "release-0001", "revision": deployment_revision})


def rejected_release(w, *, release_id="release-0001", status="rejected", reviews="complete", checks="failed", policy_hash=None, base="base",
                     policy_revision=None, extra=None, author="worker:implementation"):
    """A check-rejected release as M7's `Releases.verify` leaves it: both reviews accepted, `tests` failed, the other checks skipped
    (LABELLED: planted, not driven through propose/review/verify)."""
    policy = {"checks": list(CHECKS)}
    if policy_revision is not None:
        policy["revision"] = policy_revision
    candidate = {"revision": CAND, "base": base, "tree": "tree", "author": author}
    accepted = [{"actor": a, "accepted": True, "revision": CAND, "evidence": "fixture:review"} for a in ("lead:improvement", "conductor")]
    if reviews == "missing_conductor":
        accepted = accepted[:1]
    elif reviews == "rejected":
        accepted = [{**accepted[0], "accepted": False}, accepted[1]]
    elif reviews == "other_revision":
        accepted = [{**r, "revision": "rev-other"} for r in accepted]
    elif reviews == "duplicate":
        accepted = accepted + [accepted[0]]
    results = {"tests": {"passed": False, "evidence": "fixture:tests-failed"},
               **{k: {"passed": False, "skipped": True, "evidence": "fixture:not-run"} for k in CHECKS[1:]}}
    if checks == "all_skipped":
        results["tests"] = {"passed": False, "skipped": True, "evidence": "fixture:not-run"}
    elif checks == "all_passed":
        results = {k: {"passed": True, "evidence": "fixture:ok"} for k in CHECKS}
    elif checks == "no_evidence":
        results["cli_start"] = {"passed": False, "skipped": True}
    elif checks == "missing":
        del results["cli_file_task"]
    body = {"id": release_id, "candidate": candidate, "policy": policy, "policy_hash": policy_hash or w.api.digest(policy), "status": status,
            "reviews": accepted, "checks": results, "created_at": "2026-09-22T00:00:00+00:00", **(extra or {})}
    put(w.store, "releases", release_id, body)
    return body


# ---- reconcile_audits ------------------------------------------------------------------------------------------------------------
def case_reconcile_nothing(api):
    """`none` (M7 `tests/test_research_audits.py` `releases.reconcile_audits()` first runs before any promotion): no active release,
    an inactive, a missing and a legacy record."""
    out = {"m7_test": "none"}
    w = World(api)
    out["no_deployment"] = w.reconcile()
    put(w.store, "deployment", "active", {"release_id": "release-ghost", "revision": REV})
    out["deployment_without_record"] = w.reconcile()
    for name, options in (("status_candidate", {"status": "candidate"}), ("status_rejected", {"status": "rejected"}),
                          ("status_superseded", {"status": "superseded_by_ticket_revision"}),
                          ("no_audit_lifecycle_version", {"lifecycle": None}), ("other_lifecycle_version", {"lifecycle": 2})):
        w = World(api)
        active_release(w, **options)
        out[name] = {"call": w.reconcile(), "control": get(w.store, "research_control", "activation"),
                     "graph": get(w.store, "research_control", "graph")}
    return out


def case_reconcile_kept(api):
    """`tests/test_research_audits.py` (a pause or rollback survives, :901-916): a paused control, a same-release control and a rolled-back
    control are returned unchanged with nothing written, even for a record that would otherwise be refused."""
    out = {"m7_test": "test_research_audits.py (reconcile_audits pause/rollback cases)"}
    controls = {"paused_other_release": {"status": "paused", "release_id": "release-other", "revision": REV},
                "paused_same_release": {"status": "paused", "release_id": "release-0001", "revision": REV},
                "same_release_inactive": {"status": "inactive", "release_id": "release-0001", "revision": REV},
                "same_release_active": {"status": "active", "release_id": "release-0001", "revision": REV},
                "rolled_back_legacy": {"status": "inactive", "rolled_back_release": "release-0001"},
                "rolled_back_with_release": {"status": "rolled_back", "release_id": "release-other", "rolled_back_release": "release-0001"}}
    for name, control in controls.items():
        for variant, options in (("valid", {}), ("invalid_record", {"policy_hash": "0" * 64})):
            w = World(api)
            active_release(w, **options)
            put(w.store, "research_control", "activation", control)
            out[name + ":" + variant] = {"call": w.reconcile(), "control": get(w.store, "research_control", "activation"),
                                         "graph": get(w.store, "research_control", "graph")}
    # a control of ANOTHER release that is not paused is replaced
    w = World(api)
    active_release(w)
    put(w.store, "research_control", "activation", {"status": "active", "release_id": "release-other", "revision": "rev-other"})
    out["other_release_active_is_replaced"] = {"call": w.reconcile(), "control": get(w.store, "research_control", "activation"),
                                               "graph": get(w.store, "research_control", "graph")}
    w = World(api)
    active_release(w)
    put(w.store, "research_control", "activation", {})
    out["empty_control_row_is_replaced"] = {"call": w.reconcile(), "control": get(w.store, "research_control", "activation")}
    return out


def case_reconcile_refused(api):
    """`none`: an invalid active release (the candidate revision against the deployment, the policy hash), incomplete reviews and incomplete
    checks are refused with nothing written; a refused call is repeatable."""
    out = {"m7_test": "none"}
    cases = {"revision_differs_from_deployment": {"deployment_revision": "rev-other"}, "policy_hash_differs": {"policy_hash": "0" * 64},
             "author_unknown": {"author": "worker:nobody"}, "author_not_a_worker": {"author": "conductor"},
             "reviews_missing_conductor": {"reviews": "missing_conductor"}, "reviews_without_evidence": {"reviews": "no_evidence"},
             "reviews_for_another_revision": {"reviews": "other_revision"}, "reviews_not_accepted": {"reviews": "not_accepted"},
             "checks_failed": {"checks": "failed"}, "checks_without_evidence": {"checks": "no_evidence"}, "checks_missing": {"checks": "missing"}}
    for name, options in cases.items():
        w = World(api)
        active_release(w, **options)
        out[name] = {"call": w.reconcile(), "again": w.reconcile(), "control": get(w.store, "research_control", "activation"),
                     "graph": get(w.store, "research_control", "graph")}
    # the policy names a check the record lacks: the record's own `policy.checks` extends the required set
    w = World(api)
    active_release(w)
    record = get(w.store, "releases", "release-0001")
    record["policy"] = {"checks": CHECKS + ["extra_check"]}
    record["policy_hash"] = api.digest(record["policy"])
    put(w.store, "releases", "release-0001", record)
    out["policy_check_without_result"] = {"call": w.reconcile(), "control": get(w.store, "research_control", "activation")}
    return out


def case_reconcile_activates(api):
    """`tests/test_research_audits.py` (`releases.reconcile_audits()['release_id'] == release['id']`, :901): the activation written with its
    `graph` row, the returned control, the idempotent second call (same control, no write) and a graph that digests the organization."""
    out = {"m7_test": "test_research_audits.py (reconcile_audits returns the activation)"}
    w = World(api)
    active_release(w)
    out["first"] = w.reconcile()
    out["control"] = get(w.store, "research_control", "activation")
    out["graph"] = get(w.store, "research_control", "graph")
    out["second"] = w.reconcile()
    out["third"] = w.reconcile()
    # the same record under a legacy-looking author: the lead parent is the reviewer
    w = World(api)
    active_release(w, author="worker:implementation")
    put(w.store, "research_control", "graph", {"stale": True})
    out["stale_graph_row_is_rewritten"] = {"call": w.reconcile(), "graph": get(w.store, "research_control", "graph")}
    return out


# ---- request_reverification --------------------------------------------------------------------------------------------------------
def case_reverify_arguments(api):
    """`tests/test_release_reverification.py::test_actor_must_be_conductor_and_request_must_be_explained`: a missing reason or evidence, a
    non-conductor and an unknown actor are refused before any read of the store; an unknown release is `Release not found`."""
    out = {"m7_test": "test_actor_must_be_conductor_and_request_must_be_explained"}
    w = World(api)
    rejected_release(w)
    for name, kwargs in (("reason_empty", {"reason": ""}), ("reason_blank", {"reason": "   "}), ("reason_none", {"reason": None}),
                         ("reason_not_text", {"reason": 7}), ("evidence_empty", {"evidence": ""}), ("evidence_blank", {"evidence": "\n"}),
                         ("evidence_none", {"evidence": None}),
                         ("worker", {"actor": "worker:implementation"}), ("lead", {"actor": "lead:improvement"}),
                         ("unknown_actor", {"actor": "nobody"}), ("empty_actor", {"actor": ""})):
        out[name] = w.reverify(now=NOW, **kwargs)
    out["release_not_found"] = w.reverify(release_id="release-ghost", now=NOW)
    out["nothing_written"] = {"successor": w.successor(), "events": w.events()}
    return out


def case_reverify_written(api):
    """`test_check_rejected_release_gets_one_reviewed_successor_and_history_is_unchanged`: a check-rejected release and a valid conductor request
    write one successor with empty checks and one `release.reverification_requested` event; the source is unchanged."""
    out = {"m7_test": "test_check_rejected_release_gets_one_reviewed_successor_and_history_is_unchanged"}
    w = World(api)
    source = rejected_release(w)
    out["source_digest"] = canonical_digest(source)
    out["call"] = w.reverify(now=NOW)
    out["successor"] = w.successor()
    out["event"] = w.event()
    out["events"] = w.events()
    out["source_unchanged"] = get(w.store, "releases", "release-0001") == source
    out["successor_id_is_the_reverify_of_digest"] = w.successor()["id"] == api.reverification_successor_id("release-0001")
    # the default clock: `now=None` reads the harness clock (the receipt time is the fake clock's instant)
    w = World(api)
    rejected_release(w)
    out["default_clock"] = w.reverify()
    out["default_clock_successor"] = w.successor()
    out["default_clock_event"] = w.event()
    # a candidate whose policy.revision equals its base is not evaluator-migrated; a base-less candidate with no policy revision is not either
    w = World(api)
    rejected_release(w, policy_revision="base")
    out["policy_revision_equal_to_base"] = w.reverify(now=NOW)
    w = World(api)
    rejected_release(w, reviews="duplicate")
    out["duplicate_review_refused"] = w.reverify(now=NOW)
    return out


def case_reverify_replay(api):
    """`test_replay_is_idempotent_and_conflicting_request_refuses`: a replay returns the same successor with no write; a conflicting replay
    (another reason, evidence, actor receipt field or expected revision) is refused; a replay against a successor of another source conflicts."""
    out = {"m7_test": "test_replay_is_idempotent_and_conflicting_request_refuses"}
    w = World(api)
    rejected_release(w)
    out["first"] = w.reverify(now=NOW)
    first = w.successor()
    out["replay"] = w.reverify(now=NOW)
    out["replay_later_now"] = w.reverify(now=NOW + timedelta(hours=1))
    out["replay_default_clock"] = w.reverify()
    out["replay_returns_the_first_successor"] = w.successor() == first
    out["conflict_reason"] = w.reverify(now=NOW, reason="fixture: another diagnosis")
    out["conflict_evidence"] = w.reverify(now=NOW, evidence="fixture:another-receipt")
    out["conflict_policy_hash"] = w.reverify(now=NOW, policy_hash="f" * 64)
    out["conflict_expected_revision"] = w.reverify(now=NOW, revision="rev-other")
    out["after_conflicts"] = {"successor_unchanged": w.successor() == first, "events": w.events()}
    # an existing row at the successor id that is not a reverification of the source
    w = World(api)
    rejected_release(w)
    put(w.store, "releases", api.reverification_successor_id("release-0001"), {"id": "x", "reverify_of": "release-other"})
    out["successor_row_of_another_source"] = w.reverify(now=NOW)
    w = World(api)
    rejected_release(w)
    put(w.store, "releases", api.reverification_successor_id("release-0001"), {"id": "x", "reverify_of": "release-0001"})
    out["successor_row_without_receipt"] = w.reverify(now=NOW)
    return out


def case_reverify_blocked(api):
    """`none` (INV-RELEASE-EVALUATOR-MIGRATION-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001): an evaluator-migrated source (a receipt, or a policy
    revision other than the base) is refused; an existing evaluator or environment successor blocks the request; nothing is written."""
    out = {"m7_test": "none"}
    for name, kwargs in (("migrated_by_receipt", {"extra": {"evaluator_migration": {"approved_by": "conductor"}}}),
                         ("migrated_by_policy_revision", {"policy_revision": "evaluator-rev"})):
        w = World(api)
        rejected_release(w, **kwargs)
        out[name] = w.reverify(now=NOW)
    w = World(api)
    rejected_release(w, extra={"evaluator_migration": {}})
    out["migrated_before_existing_successor"] = {"call": w.reverify(now=NOW)}
    w = World(api)
    rejected_release(w)
    put(w.store, "releases", api.evaluator_successor_id("release-0001"), {"id": "evaluator-successor", "reverify_of": "release-0001"})
    out["evaluator_successor_blocks"] = w.reverify(now=NOW)
    w = World(api)
    rejected_release(w)
    put(w.store, "releases", api.environment_successor_id("release-0001"), {"id": "environment-successor", "reverify_of": "release-0001"})
    out["environment_successor_blocks"] = w.reverify(now=NOW)
    out["environment_view"] = {"successor": w.successor(), "events": w.events()}
    return out


def case_reverify_source(api):
    """`test_ineligible_source_refuses_without_writes`, `test_review_rejected_release_is_not_reverifiable` and
    `test_active_lease_or_promotion_effect_refuses_without_writes` (via `_check_rejected_source`): every ineligible source refuses with the
    store unchanged."""
    out = {"m7_test": "test_ineligible_source_refuses_without_writes, test_review_rejected_release_is_not_reverifiable, "
                      "test_active_lease_or_promotion_effect_refuses_without_writes"}
    for status in ("candidate", "reviewed", "verified", "active", "cancelled", "superseded_by_ticket_revision"):
        w = World(api)
        rejected_release(w, status=status)
        out["status_" + status] = w.reverify(now=NOW)
    for name, kwargs in (("review_rejected", {"reviews": "rejected"}), ("reviews_missing_conductor", {"reviews": "missing_conductor"}),
                         ("reviews_for_another_revision", {"reviews": "other_revision"}), ("evaluator_changed", {"policy_hash": "0" * 64}),
                         ("no_executed_failed_check", {"checks": "all_skipped"}), ("every_check_passed", {"checks": "all_passed"}),
                         ("check_without_evidence", {"checks": "no_evidence"}), ("check_missing", {"checks": "missing"}),
                         ("author_unknown", {"author": "worker:nobody"})):
        w = World(api)
        rejected_release(w, **kwargs)
        out[name] = w.reverify(now=NOW)
    w = World(api)
    rejected_release(w)
    out["stale_revision"] = w.reverify(now=NOW, revision="rev-other")
    out["stale_policy_hash"] = w.reverify(now=NOW, policy_hash="f" * 64)
    for name, rows in (("lease_active", [("deployment_locks", "controller", {"lease_until": (NOW + timedelta(minutes=5)).isoformat()})]),
                       ("lease_expired_allowed", [("deployment_locks", "controller", {"lease_until": (NOW - timedelta(minutes=5)).isoformat()})]),
                       ("queue_running", [("release_queue", "release-0001", {"status": "running"})]),
                       ("queue_done_allowed", [("release_queue", "release-0001", {"status": "done"})]),
                       ("promotion_intent", [("promotion_intents", "release-0001", {"release_id": "release-0001"})]),
                       ("deployed_release", [("deployment", "active", {"release_id": "release-0001", "revision": CAND})]),
                       ("another_deployed_release_allowed", [("deployment", "active", {"release_id": "release-other", "revision": CAND})])):
        w = World(api)
        rejected_release(w)
        for bucket, key, body in rows:
            put(w.store, bucket, key, body)
        out[name] = w.reverify(now=NOW)
    return out


CASES = (case_reconcile_nothing, case_reconcile_kept, case_reconcile_refused, case_reconcile_activates, case_reverify_arguments,
         case_reverify_written, case_reverify_replay, case_reverify_blocked, case_reverify_source)


def run(api) -> dict:
    return {fn.__name__[len("case_"):]: fn(api) for fn in CASES}
