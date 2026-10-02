"""Shared S8 scenario steps (`research.threshold_approvals`): M7 `application/threshold_approvals.py` (`ThresholdApprovals`: `issue`, `_check`,
`consume`, `revoke`, `inspect`, `_event`; `parse_applied_policy`, `_time`), characterized BEFORE the module moves (DESIGN-s8 §6 V11; the branch
table `branch-table-research.txt` section `application/threshold_approvals.py`: every raise, every except and every `require` of this module is
covered, see `BRANCH_COVERAGE`).

Every case mirrors a test of M7 `tests/test_threshold_approvals.py` (the test name is the group label), plus LABELLED additions that reach the
branches of the module the tests do not:

- **c1_test_issue_binds_the_exact_assessed_change**: the refusals of `issue` (actor, environment, ttl, every precondition of the assessed
  request, its reviews, its row and its evidence), the issued record and its first event, the idempotent re-issue, another environment.
- **c2_test_consume_certifies_exactly_one_matching_change**: every refusal of `_check` in its order, each as a committed `refused` event
  with the approvals bucket unchanged, the expiry boundary, the malformed applied policies (refused before any transaction), the one
  certification, its generation, the repeat, the event sequence.
- **c3_test_revocation_and_degraded_states**: `revoke` (actor, reason, idempotent, consumed refused), `inspect` (every state: issued,
  consumed, revoked, expired, missing, corrupt, unreadable), the unknown approval, `parse_applied_policy`.
- **c4_test_concurrent_consumers_on_postgres_get_one_certification**: the part the application decides, over MemoryStore: eight
  sequential deliveries of different revisions certify one and refuse seven as `approval is consumed` (the threads and PostgreSQL of M7 are
  not scenario steps).

The two domain tests of M7 `tests/test_threshold_approvals.py` (`unique_events`, `admitted_entries`) exercise `domain.threshold_proposals`
and `domain.threshold_replay`, not this module; they are recorded in `M7_TESTS`.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api` (`MemoryStore`, `ThresholdApprovals`,
`parse_applied_policy`, `_time`, `BUCKET`, `EVENTS`, `STATES`, `ENVIRONMENT`, `REVISION`, `MAX_TTL_SECONDS`, `REGISTRY`, `ContractError`,
`digest`). M7's test builds the assessed request through the review executor; the scenario writes the rows the review chain leaves
(`threshold_review_requests`, `threshold_proposals`) directly, with the fields the module reads. The `artifacts` store is a LABELLED fake of
`FileArtifacts.document`. `now` is always passed (the module reads the real clock only without it); the events' `at` is the harness clock.
For every refusal the digest of each of the two owned buckets and of the whole store before and after is recorded."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

NAME = "skill_match.FULL_BODY_MIN_SCORE"
OTHER_NAME = "skill_telemetry_audit.FP_THIN_RATE"
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
REV_A, REV_B, REV_C = "a" * 40, "d" * 40, "c" * 40
OWNED = ("threshold_approvals", "threshold_approval_events")
UNSET = object()


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


class Artifacts:
    """LABELLED fake of `FileArtifacts.document(ref)`: a stored document under its reference, `FileNotFoundError` for an absent one, or the
    scripted fault of that reference."""

    def __init__(self):
        self.docs, self.faults, self.calls = {}, {}, []

    def put(self, document):
        ref = "sha256:" + sha(document).ljust(64, "0")
        self.docs[ref] = deepcopy(document)
        return ref

    def document(self, ref):
        self.calls.append(ref)
        if ref in self.faults:
            raise self.faults[ref]
        if ref not in self.docs:
            raise FileNotFoundError(ref)
        return deepcopy(self.docs[ref])


class Down:
    """LABELLED. A store that is unreachable (M7's `PostgresStore` on a closed port): every transaction raises."""

    def __init__(self, error):
        self.error = error

    def transaction(self, *args, **kwargs):
        raise self.error


def shape(value):
    """JSON-safe form of a result (non-finite numbers by name)."""
    if isinstance(value, dict):
        return {str(k): shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [shape(v) for v in value]
    if isinstance(value, float) and value != value:
        return "nan"
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        return repr(value)
    return value


class Case:
    """One assessed threshold review request in a MemoryStore, written the way the review chain leaves it, and the approvals use case over it."""

    def __init__(self, api, tag="1", store=None, artifacts=None):
        self.api, self.tag = api, tag
        self.store = api.MemoryStore() if store is None else store
        self.artifacts = Artifacts() if artifacts is None else artifacts
        self.approvals = api.ThresholdApprovals(self.store, self.artifacts)
        self.requests = {}

    # rows
    def put(self, bucket, row_id, body):
        with self.store.transaction() as tx:
            tx.put(bucket, row_id, body)

    def get(self, bucket, row_id):
        with self.store.transaction() as tx:
            return tx.get(bucket, row_id)

    def scan(self, bucket):
        with self.store.transaction() as tx:
            return tx.scan(bucket)

    def assess(self, tag=None, *, name=NAME, current=3, suggested=4, proposal=None, evidence_proposals=UNSET, row=None, request=None,
               reviews=UNSET, binding=UNSET, evidence_ref=UNSET, store_row=True):
        """The assessed request `req-<tag>` over the proposal row `row-<tag>` and its evaluation evidence."""
        tag = tag or self.tag
        body = {"name": name, "current": current, "suggested": suggested, "reference_accepted": True, "policy_revision": REV_A,
                "corpus_hash": "corpus-" + tag, "registry_hash": "registry-1", "sample_size": 40, **(proposal or {})}
        evidence = self.artifacts.put({"proposals": [body] if evidence_proposals is UNSET else evidence_proposals,
                                       "tag": tag}) if evidence_ref is UNSET else evidence_ref
        stored = {"id": "row-" + tag, "proposal": body, "evidence_ref": evidence, **(row or {})}
        if store_row:
            self.put("threshold_proposals", stored["id"], stored)
        if reviews is UNSET:
            reviews = [{"actor": "lead:improvement", "decision_id": "decision-1-" + tag, "generation": 1, "result": {"accepted": True}},
                       {"actor": "conductor", "decision_id": "decision-2-" + tag, "generation": 1, "result": {"accepted": True}}]
        req = {"id": "req-" + tag, "status": "assessed", "row_id": stored["id"], "reviews": reviews,
               "binding": self.api.digest(stored) if binding is UNSET else binding, **(request or {})}
        self.put("threshold_review_requests", req["id"], req)
        self.requests[tag] = req
        return req

    # observations
    def snapshot(self):
        with self.store.transaction() as tx:
            records = tx.records()
        out = {"store": sha(records)}
        for bucket in OWNED:
            out[bucket] = sha([r for r in records if r["bucket"] == bucket])
        out["events"] = sum(r["bucket"] == OWNED[1] for r in records)
        return out

    def observe(self, call):
        before = self.snapshot()
        try:
            out = {"outcome": "returned", "value": shape(call())}
        except BaseException as exc:  # noqa: BLE001 - what propagates is part of the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc),
                   "is_contract_error": isinstance(exc, self.api.ContractError), "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__,
                   "suppress_context": exc.__suppress_context__}
        after = self.snapshot()
        out.update(before=before, after=after, store_unchanged=before["store"] == after["store"],
                   approvals_unchanged=before[OWNED[0]] == after[OWNED[0]], events_unchanged=before[OWNED[1]] == after[OWNED[1]])
        return out

    def events(self, approval_id=None):
        rows = sorted(self.scan(OWNED[1]), key=lambda e: (e["approval_id"], e["sequence"]))
        return [shape(e) for e in rows if approval_id in (None, e["approval_id"])]

    def issue(self, request=None, *, actor="conductor", environment="staging", ttl_seconds=3600, now=T0, **over):
        request = request or self.requests[self.tag]
        return self.approvals.issue(request["id"], actor=actor, environment=environment, ttl_seconds=ttl_seconds, now=now, **over)

    def issued(self, request=None, **over):
        return self.issue(request, **over)


def change(proposal_current=3, proposal_suggested=4, **over):
    document = {"previous_revision": REV_A, "previous_values": {NAME: proposal_current}, "revision": REV_C,
                "values": {NAME: proposal_suggested}, "environment": "staging"}
    document.update(over)
    return document


def kinds(case, approval_id=None):
    return [e["kind"] for e in case.events(approval_id)]


# ---- c1: issue --------------------------------------------------------------------------------------------------------
def c1_issue(api):
    out = {}
    case = Case(api)
    pending = case.assess(request={"status": "pending"})
    out["not_assessed_pending"] = case.observe(lambda: case.issue(pending))
    out["unknown_request"] = case.observe(lambda: case.approvals.issue("req-none", actor="conductor", environment="staging", ttl_seconds=60, now=T0))
    request = case.assess("2")
    case.tag = "2"
    for label, actor in (("lead", "lead:improvement"), ("worker", "worker:implementation"), ("empty", ""), ("none", None), ("upper", "Conductor")):
        out["actor_" + label] = case.observe(lambda actor=actor: case.issue(request, actor=actor))
    for label, environment in (("upper", "Staging"), ("empty", ""), ("none", None), ("int", 5), ("leading_dash", "-x"), ("space", "a b"),
                               ("newline_tail", "staging\n"), ("too_long", "a" * 65), ("underscore", "a_b")):
        out["environment_" + label] = case.observe(lambda environment=environment: case.issue(request, environment=environment))
    for label, ttl in (("zero", 0), ("negative", -1), ("true", True), ("float", 60.0), ("str", "60"), ("none", None), ("over", 31 * 24 * 3600),
                       ("max_plus_one", 30 * 24 * 3600 + 1)):
        out["ttl_" + label] = case.observe(lambda ttl=ttl: case.issue(request, ttl_seconds=ttl))
    out["environment_exactly_64"] = case.observe(lambda: case.issue(request, environment="a" * 64, now=T0))
    out["ttl_exactly_max"] = case.observe(lambda: case.issue(request, environment="maxttl", ttl_seconds=30 * 24 * 3600))
    out["ttl_one"] = case.observe(lambda: case.issue(request, environment="onettl", ttl_seconds=1))
    out["environment_with_dots_dashes"] = case.observe(lambda: case.issue(request, environment="eu-west.1_a"))

    def refusal(label, tag, **kw):
        c = Case(api, tag=tag)
        req = c.assess(tag, **kw)
        out[label] = c.observe(lambda: c.issue(req))

    base = [{"actor": "lead:improvement", "decision_id": "d1", "generation": 1, "result": {"accepted": True}},
            {"actor": "conductor", "decision_id": "d2", "generation": 1, "result": {"accepted": True}}]

    def reviews(per):
        return [{**r, **per.get(i, {})} for i, r in enumerate(deepcopy(base))]
    refusal("reviews_single", "r1", reviews=base[:1])
    refusal("reviews_none", "r2", reviews=[])
    refusal("reviews_wrong_order", "r3", reviews=[base[1], base[0]])
    refusal("reviews_other_actor", "r4", reviews=[base[0], {**base[1], "actor": "lead:research"}])
    refusal("reviews_three", "r5", reviews=base + [base[1]])
    refusal("first_not_accepted", "r6", reviews=reviews({0: {"result": {"accepted": False}}}))
    refusal("second_not_accepted_truthy", "r7", reviews=reviews({1: {"result": {"accepted": "yes"}}}))
    refusal("second_accepted_missing", "r8", reviews=reviews({1: {"result": {}}}))
    refusal("first_blocked", "r9", reviews=reviews({0: {"result": {"accepted": True, "blocked": True}}}))
    refusal("second_inspection_blocked", "r10", reviews=reviews({1: {"result": {"accepted": True, "inspection_blocked": ["x"]}}}))
    refusal("blocked_false_is_fine", "r11", reviews=reviews({1: {"result": {"accepted": True, "blocked": False, "inspection_blocked": []}}}))
    refusal("binding_is_not_the_row", "r12", binding="0" * 64)
    refusal("row_missing", "r13", store_row=False)
    refusal("suggested_none", "r14", proposal={"suggested": None})
    refusal("not_reference_accepted", "r15", proposal={"reference_accepted": False})
    refusal("reference_accepted_missing", "r15b", proposal={"reference_accepted": 0})
    refusal("current_nan", "r16", proposal={"current": float("nan")})
    refusal("suggested_inf", "r17", proposal={"suggested": float("inf")})
    refusal("suggested_bool", "r18", proposal={"suggested": True})
    refusal("current_bool", "r19", proposal={"current": False, "suggested": 1})
    refusal("suggested_str", "r20", proposal={"suggested": "4"})
    refusal("suggested_equals_current", "r21", proposal={"suggested": 3})
    refusal("suggested_equals_current_int_float", "r22", proposal={"suggested": 3.0})
    refusal("evidence_lacks_the_proposal", "r23", evidence_proposals=[])
    refusal("evidence_proposal_differs", "r24", evidence_proposals=[{"name": NAME, "current": 3, "suggested": 5}])
    refusal("evidence_missing", "r25", evidence_ref="sha256:" + "e" * 64)
    refusal("evidence_ref_none", "r26", evidence_ref=None)
    c = Case(api, tag="r27")
    req = c.assess("r27")
    row = c.get("threshold_proposals", "row-r27")
    c.artifacts.faults[row["evidence_ref"]] = OSError("disk")
    out["evidence_unreadable_propagates"] = c.observe(lambda: c.issue(req))
    c = Case(api, tag="r28")
    req = c.assess("r28", evidence_proposals={"not": "a list"})
    out["evidence_proposals_not_a_list"] = c.observe(lambda: c.issue(req))
    c = Case(api, tag="r29")
    req = c.assess("r29")
    c.put("threshold_proposals", "row-r29", {**c.get("threshold_proposals", "row-r29"), "proposal": {"name": NAME}})
    out["row_without_proposal_fields"] = c.observe(lambda: c.issue(req))

    # the issued record and its idempotence (test_issue_binds_the_exact_assessed_change)
    c = Case(api, tag="ok")
    req = c.assess("ok")
    first = c.observe(lambda: c.issue(req))
    again = c.observe(lambda: c.issue(req, ttl_seconds=60, now=T0 + timedelta(hours=5)))
    other_env = c.observe(lambda: c.issue(req, environment="prod", ttl_seconds=60))
    out["issued"] = {"first": first, "event_after_first": c.events(), "reissue_same_binding_other_ttl_and_time": again,
                     "reissue_returns_the_first": first["value"] == again["value"], "other_environment": other_env,
                     "other_environment_is_another_id": first["value"]["id"] != other_env["value"]["id"],
                     "stored_equals_returned": shape(c.get(OWNED[0], first["value"]["id"])) == first["value"],
                     "inspect": c.approvals.inspect(first["value"]["id"], now=T0)}
    out["events_after_two_issues"] = kinds(c)
    out["expires_at_is_issued_at_plus_ttl"] = [first["value"]["issued_at"], first["value"]["expires_at"], other_env["value"]["expires_at"]]
    # a different request on the same name is another approval (the request binds the id)
    second = c.assess("ok2")
    out["another_request_another_approval"] = c.observe(lambda: c.issue(second))
    out["issue_with_the_real_clock_is_not_driven"] = "now is always passed"
    return out


# ---- c2: consume ------------------------------------------------------------------------------------------------------
def fresh(api, tag="c", **assess):
    case = Case(api, tag=tag)
    request = case.assess(tag, **assess)
    approval = case.issue(request, ttl_seconds=3600, now=T0)
    return case, request, approval


def c2_consume(api):
    out = {}
    case, request, approval = fresh(api)
    aid = approval["id"]
    minute = T0 + timedelta(minutes=1)
    refused = [
        ("applied_value_differs", change(values={NAME: 999})),
        ("applied_value_float_type", change(values={NAME: 4.0})),
        ("applied_value_missing", change(values={})),
        ("previous_value_differs", change(previous_values={NAME: 2})),
        ("previous_value_missing", change(previous_values={})),
        ("previous_revision_differs", change(previous_revision=REV_B)),
        ("environment_differs", change(environment="prod")),
        ("revision_equals_previous", change(revision=REV_A)),
        ("touches_other_threshold", change(values={NAME: 4, OTHER_NAME: 0.9}, previous_values={NAME: 3, OTHER_NAME: 0.8})),
        ("other_threshold_added", change(values={NAME: 4, OTHER_NAME: 0.9})),
        ("other_threshold_removed", change(previous_values={NAME: 3, OTHER_NAME: 0.8})),
        ("two_other_thresholds_sorted", change(values={NAME: 4, OTHER_NAME: 0.9, "ratio_tracker.WARN_THRESHOLD": 1},
                                              previous_values={NAME: 3, OTHER_NAME: 0.8, "ratio_tracker.WARN_THRESHOLD": 2})),
        ("other_threshold_unchanged_is_fine_but_the_revision_is_the_same", change(values={NAME: 4, OTHER_NAME: 0.8},
                                                                             previous_values={NAME: 3, OTHER_NAME: 0.8}, revision=REV_A)),
    ]
    out["refusals"] = {label: case.observe(lambda d=d: case.approvals.consume(aid, d, now=minute)) for label, d in refused}
    out["refusal_events"] = case.events(aid)
    out["refusal_events_are_all_refused"] = set(kinds(case, aid)[1:]) == {"refused"}
    # the order of the checks: several faults at once report the first in the order of `_check`
    out["order_environment_before_revision"] = case.observe(lambda: case.approvals.consume(
        aid, change(environment="prod", previous_revision=REV_B, values={NAME: 999}), now=minute))
    out["order_revision_before_value"] = case.observe(lambda: case.approvals.consume(aid, change(previous_revision=REV_B, values={NAME: 999}), now=minute))
    out["order_expired_before_environment"] = case.observe(lambda: case.approvals.consume(aid, change(environment="prod"), now=T0 + timedelta(hours=2)))
    # the expiry boundary
    out["expiry_one_microsecond_before"] = case.observe(lambda: case.approvals.consume(aid, change(values={NAME: 9}), now=T0 + timedelta(hours=1) - timedelta(microseconds=1)))
    out["expiry_exactly_at"] = case.observe(lambda: case.approvals.consume(aid, change(), now=T0 + timedelta(hours=1)))
    out["expired"] = case.observe(lambda: case.approvals.consume(aid, change(), now=T0 + timedelta(hours=2)))
    malformed = [
        ("not_a_dict", None), ("list", [1]), ("empty", {}), ("missing_environment", {k: v for k, v in change().items() if k != "environment"}),
        ("extra_key", change(extra=1)), ("values_nan", change(values={NAME: float("nan")})), ("values_inf", change(values={NAME: float("inf")})),
        ("values_bool", change(values={NAME: True})), ("values_str", change(values={NAME: "4"})), ("values_unknown_name", change(values={"unknown.NAME": 4})),
        ("values_list", change(values=[4])), ("previous_values_str", change(previous_values="none")), ("previous_values_unknown", change(previous_values={"x.Y": 1})),
        ("previous_values_nan", change(previous_values={NAME: float("nan")})),
        ("revision_head", change(revision="HEAD")), ("revision_uppercase", change(revision="C" * 40)), ("revision_short", change(revision="c" * 39)),
        ("revision_long", change(revision="c" * 41)), ("revision_trailing_newline", change(revision="c" * 40 + "\n")), ("revision_int", change(revision=5)),
        ("previous_revision_short", change(previous_revision="a" * 39)), ("previous_revision_none", change(previous_revision=None)),
        ("environment_upper", change(environment="Staging")), ("environment_int", change(environment=1)), ("environment_empty", change(environment="")),
        ("environment_leading_dot", change(environment=".x"))]
    out["malformed_policies"] = {label: case.observe(lambda d=d: case.approvals.consume(aid, d, now=minute)) for label, d in malformed}
    out["malformed_are_refused_before_any_transaction"] = all(r["store_unchanged"] for r in out["malformed_policies"].values())
    out["unknown_approval"] = case.observe(lambda: case.approvals.consume("nope", change(), now=minute))
    out["unknown_approval_with_a_malformed_policy_is_malformed_first"] = case.observe(lambda: case.approvals.consume("nope", {"x": 1}, now=minute))
    out["still_issued_after_every_refusal"] = case.approvals.inspect(aid, now=minute)["state"]
    # the one certification
    consumed = case.observe(lambda: case.approvals.consume(aid, change(), now=T0 + timedelta(minutes=2)))
    out["consumed"] = consumed
    out["consumed_stored_equals_returned"] = shape(case.get(OWNED[0], aid)) == consumed["value"]
    out["repeat_after_consumption"] = case.observe(lambda: case.approvals.consume(aid, change(), now=T0 + timedelta(minutes=3)))
    out["revoke_after_consumption"] = case.observe(lambda: case.approvals.revoke(aid, actor="conductor", reason="too late"))
    out["events"] = case.events(aid)
    out["kinds"] = kinds(case, aid)
    out["inspect_consumed"] = case.approvals.inspect(aid)
    # generation counts consumed approvals of the SAME name; another name does not count
    other = case.assess("c-other", name=OTHER_NAME, current=0.5, suggested=0.6)
    other_approval = case.issue(other, now=T0)
    out["other_name_first_generation"] = case.observe(lambda: case.approvals.consume(
        other_approval["id"], change(0.5, 0.6, values={OTHER_NAME: 0.6}, previous_values={OTHER_NAME: 0.5}, revision="e" * 40), now=minute))
    again = case.assess("c-again", current=4, suggested=5, proposal={"policy_revision": REV_C})
    again_approval = case.issue(again, environment="prod", now=T0)
    out["same_name_second_generation"] = case.observe(lambda: case.approvals.consume(
        again_approval["id"], change(4, 5, previous_revision=REV_C, revision="f" * 40, environment="prod"), now=minute))
    third = case.assess("c-third", current=5, suggested=6, proposal={"policy_revision": "f" * 40})
    third_approval = case.issue(third, environment="qa", now=T0)
    out["same_name_third_generation_application"] = shape(case.observe(lambda: case.approvals.consume(
        third_approval["id"], change(5, 6, previous_revision="f" * 40, revision="1" * 40, environment="qa"), now=minute))["value"]["application"])
    # an expires_at the module cannot read: the check raises inside the transaction, no refusal is recorded
    for label, value in (("garbage", "not a time"), ("naive", "2026-09-10T13:00:00"), ("int", 5), ("none", None), ("date_only", "2026-09-10")):
        c = Case(api, tag="bad-" + label)
        req = c.assess("bad-" + label)
        a = c.issue(req)
        c.put(OWNED[0], a["id"], {**c.get(OWNED[0], a["id"]), "expires_at": value})
        out["expires_at_" + label] = c.observe(lambda c=c, a=a: c.approvals.consume(a["id"], change(), now=minute))
    # a record whose status is not issued
    for status in ("revoked", "expired", "weird"):
        c, req, a = fresh(api, tag="status-" + status)
        c.put(OWNED[0], a["id"], {**c.get(OWNED[0], a["id"]), "status": status})
        out["status_" + status] = c.observe(lambda c=c, a=a: c.approvals.consume(a["id"], change(), now=minute))
        out["status_" + status + "_events"] = kinds(c, a["id"])
    # an approval record missing the fields `_check` reads propagates the KeyError (nothing is recorded)
    for field in ("environment", "policy_revision", "name", "current", "proposed"):
        c, req, a = fresh(api, tag="missing-" + field)
        body = c.get(OWNED[0], a["id"])
        del body[field]
        c.put(OWNED[0], a["id"], body)
        out["record_without_" + field] = c.observe(lambda c=c, a=a: c.approvals.consume(a["id"], change(), now=minute))
    # a consumed row of the same name with no `name` is skipped by the generation scan only when `name` differs; one without `status` raises
    c, req, a = fresh(api, tag="scan")
    c.put(OWNED[0], "stray", {"id": "stray", "status": "consumed", "name": OTHER_NAME})
    out["generation_ignores_other_names"] = c.observe(lambda: c.approvals.consume(a["id"], change(), now=minute))["value"]["application"]
    c, req, a = fresh(api, tag="scan2")
    c.put(OWNED[0], "stray", {"id": "stray", "name": NAME})
    out["generation_scan_row_without_status"] = c.observe(lambda: c.approvals.consume(a["id"], change(), now=minute))
    c, req, a = fresh(api, tag="scan3")
    c.put(OWNED[0], "stray", {"id": "stray", "status": "consumed"})
    out["generation_scan_row_without_name"] = c.observe(lambda: c.approvals.consume(a["id"], change(), now=minute))
    # the refusal's own transaction failing (the store goes down after the check) is not driven: MemoryStore
    return out


# ---- c3: revoke, inspect, degraded states -----------------------------------------------------------------------------
def c3_revoke_and_degraded(api):
    out = {}
    case, request, approval = fresh(api, tag="v", )
    aid = approval["id"]
    for label, actor in (("worker", "worker:implementation"), ("empty", ""), ("none", None), ("upper", "Conductor"), ("research", "lead:research")):
        out["actor_" + label] = case.observe(lambda actor=actor: case.approvals.revoke(aid, actor=actor, reason="no"))
    for label, reason in (("none", None), ("empty", ""), ("blank", "   "), ("int", 5), ("list", ["x"])):
        out["reason_" + label] = case.observe(lambda reason=reason: case.approvals.revoke(aid, actor="conductor", reason=reason))
    out["unknown"] = case.observe(lambda: case.approvals.revoke("nope", actor="conductor", reason="x"))
    revoked = case.observe(lambda: case.approvals.revoke(aid, actor="lead:improvement", reason="a later rejection"))
    out["revoked"] = revoked
    out["revoked_is_stored"] = shape(case.get(OWNED[0], aid)) == revoked["value"]
    out["again_is_idempotent"] = case.observe(lambda: case.approvals.revoke(aid, actor="conductor", reason="again"))
    out["again_returns_the_first"] = out["again_is_idempotent"]["value"] == revoked["value"]
    out["consume_after_revoke"] = case.observe(lambda: case.approvals.consume(aid, change(), now=T0))
    out["invalid_actor_on_a_revoked_one_is_refused_first"] = case.observe(lambda: case.approvals.revoke(aid, actor="worker:x", reason="r"))
    out["events"] = case.events(aid)
    out["inspect_revoked"] = case.approvals.inspect(aid)
    # an expired but still issued approval is revocable
    later = case.assess("v2")
    later_approval = case.issue(later, environment="prod", ttl_seconds=60, now=T0)
    out["inspect_expired"] = case.approvals.inspect(later_approval["id"], now=T0 + timedelta(seconds=61))
    out["inspect_at_expiry_is_expired"] = case.approvals.inspect(later_approval["id"], now=T0 + timedelta(seconds=60))["state"]
    out["inspect_just_before_expiry_is_issued"] = case.approvals.inspect(later_approval["id"], now=T0 + timedelta(seconds=59))["state"]
    out["revoke_an_expired_issued_one"] = case.observe(lambda: case.approvals.revoke(later_approval["id"], actor="conductor", reason="stale"))
    out["inspect_missing"] = case.approvals.inspect("nope", now=T0)
    # inspect over every degraded record
    good = case.assess("v3")
    good_approval = case.issue(good, environment="eu", ttl_seconds=3600, now=T0)
    base = case.get(OWNED[0], good_approval["id"])

    def degraded(label, **changes):
        c = Case(api, tag="d-" + label)
        req = c.assess("d-" + label)
        a = c.issue(req)
        body = {**c.get(OWNED[0], a["id"]), **changes}
        for k in [k for k, v in changes.items() if v is UNSET]:
            del body[k]
        c.put(OWNED[0], a["id"], body)
        return c.observe(lambda: c.approvals.inspect(a["id"], now=T0))
    out["inspect_corrupt"] = {
        "proposed_nan": degraded("1", proposed=float("nan")), "proposed_bool": degraded("2", proposed=True), "proposed_str": degraded("3", proposed="4"),
        "proposed_missing": degraded("4", proposed=UNSET), "current_inf": degraded("5", current=float("inf")), "current_none": degraded("6", current=None),
        "name_unknown": degraded("7", name="unknown.NAME"), "name_missing": degraded("8", name=UNSET), "name_unhashable": degraded("9", name=["x"]),
        "status_unknown": degraded("10", status="weird"), "status_missing": degraded("11", status=UNSET), "status_expired_is_not_stored": degraded("12", status="expired"),
        "expires_garbage": degraded("13", expires_at="soon"), "expires_naive": degraded("14", expires_at="2026-09-10T13:00:00"),
        "expires_int": degraded("15", expires_at=7), "expires_missing": degraded("16", expires_at=UNSET),
        "expires_none": degraded("17", expires_at=None), "policy_revision_missing": degraded("18", policy_revision=UNSET),
        "environment_missing": degraded("19", environment=UNSET), "authority_missing": degraded("20", authority=UNSET),
        "application_missing_is_none": degraded("21", application=UNSET), "consumed_state": degraded("22", status="consumed", application={"revision": REV_C}),
        "revoked_state_with_a_past_expiry": degraded("23", status="revoked", expires_at="2020-01-01T00:00:00+00:00"),
        "consumed_state_with_a_past_expiry": degraded("24", status="consumed", expires_at="2020-01-01T00:00:00+00:00"),
        "issued_with_a_past_expiry": degraded("25", expires_at="2020-01-01T00:00:00+00:00"),
        "expires_in_another_zone": degraded("26", expires_at="2026-09-10T20:00:00+09:00")}
    out["inspect_record_untouched"] = case.get(OWNED[0], good_approval["id"]) == base
    # an unreachable store is `unreadable`
    for label, error in (("operational", RuntimeError("closed port")), ("os_error", OSError("refused")), ("contract", api.ContractError("locked")),
                         ("key_error", KeyError("k")), ("value_error", ValueError("v"))):
        out["unreadable_" + label] = api.ThresholdApprovals(Down(error), Artifacts()).inspect("any", now=T0)
    for label, error in (("keyboard_interrupt", KeyboardInterrupt()), ("system_exit", SystemExit(3))):
        try:
            out["not_mapped_" + label] = api.ThresholdApprovals(Down(error), Artifacts()).inspect("any", now=T0)
        except BaseException as exc:  # noqa: BLE001
            out["not_mapped_" + label] = {"propagated": type(exc).__name__}
    out["inspect_does_not_write"] = case.observe(lambda: case.approvals.inspect(good_approval["id"], now=T0))["store_unchanged"]
    # the read-side fields of every inspected state
    out["inspect_issued"] = case.approvals.inspect(good_approval["id"], now=T0)
    out["inspect_exactly_the_keys"] = sorted(out["inspect_issued"])
    # `_time` directly
    times = {}
    for label, value in (("utc", "2026-09-10T12:00:00+00:00"), ("z_suffix", "2026-09-10T12:00:00Z"), ("offset", "2026-09-10T12:00:00+09:00"),
                         ("naive", "2026-09-10T12:00:00"), ("garbage", "xx"), ("empty", ""), ("date_only", "2026-09-10"), ("int", 5), ("none", None),
                         ("bytes", b"2026"), ("datetime_object", T0), ("trailing_space", "2026-09-10T12:00:00+00:00 ")):
        try:
            parsed = api._time(value, "field")
            times[label] = ["ok", parsed.isoformat()]
        except BaseException as exc:  # noqa: BLE001
            times[label] = [type(exc).__name__, str(exc), exc.__suppress_context__, exc.__cause__ is None]
    out["time"] = times
    # `parse_applied_policy` directly
    parsed = {}
    for label, document in (("good", change()), ("empty_values", change(values={}, previous_values={})), ("two_names", change(values={NAME: 4, OTHER_NAME: 0.1})),
                            ("float_values", change(values={NAME: 4.5})), ("not_a_dict", "x"), ("extra", change(x=1)), ("missing", {"revision": REV_C})):
        try:
            result = api.parse_applied_policy(document)
            parsed[label] = ["ok", result is document]
        except BaseException as exc:  # noqa: BLE001
            parsed[label] = [type(exc).__name__, str(exc)]
    out["parse_applied_policy"] = parsed
    out["registry_names"] = sorted(api.REGISTRY)
    return out


# ---- c4: concurrent consumers -----------------------------------------------------------------------------------------
def c4_concurrent(api):
    out = {}
    case, request, approval = fresh(api, tag="k")
    results = []
    for index in range(1, 9):
        revision = f"{index:040x}"[-40:]
        results.append(case.observe(lambda revision=revision: case.approvals.consume(approval["id"], change(revision=revision), now=T0 + timedelta(minutes=1))))
    out["results"] = [{"outcome": r["outcome"], "message": r.get("message"), "application": (r.get("value") or {}).get("application")} for r in results]
    out["one_certified"] = sum(r["outcome"] == "returned" for r in results)
    out["seven_refused_as_consumed"] = sum(r["outcome"] == "raised" and "approval is consumed" in r["message"] for r in results)
    stored = case.get(OWNED[0], approval["id"])
    out["row"] = {"status": stored["status"], "generation": stored["application"]["generation"], "revision": stored["application"]["revision"]}
    out["events"] = kinds(case, approval["id"])
    out["refused_events"] = sum(k == "refused" for k in kinds(case, approval["id"]))
    out["refusals_leave_the_approval_row_unchanged"] = all(r["approvals_unchanged"] for r in results[1:])
    out["each_refusal_adds_one_event"] = [r["after"]["events"] - r["before"]["events"] for r in results]
    # the same name consumed through two environments gets increasing generations
    generations = []
    previous = REV_C
    current = 4
    for index, environment in enumerate(("e1", "e2", "e3")):
        req = case.assess(f"g{index}", current=current, suggested=current + 1, proposal={"policy_revision": previous})
        approval_g = case.issue(req, environment=environment, now=T0)
        revision = f"{index + 2:040x}"
        result = case.observe(lambda: case.approvals.consume(approval_g["id"], change(current, current + 1, previous_revision=previous, revision=revision,
                                                                                      environment=environment), now=T0 + timedelta(minutes=1)))
        generations.append([result["outcome"], (result.get("value") or {}).get("application", {}).get("generation"), result.get("message")])
        previous, current = revision, current + 1
    out["increasing_generations"] = generations
    return out


GROUPS = [("c1_test_issue_binds_the_exact_assessed_change", c1_issue), ("c2_test_consume_certifies_exactly_one_matching_change", c2_consume),
          ("c3_test_revocation_and_degraded_states", c3_revoke_and_degraded),
          ("c4_test_concurrent_consumers_on_postgres_get_one_certification", c4_concurrent)]

M7_TESTS = {
    "test_duplicates_audit_rows_and_unscored_events_are_not_additional_executions": {"unreachable": "exercises domain.threshold_proposals.unique_events and propose_threshold_changes, not this module"},
    "test_a_value_that_admits_nothing_is_never_an_improvement": {"unreachable": "exercises domain.threshold_replay.admitted_entries and evaluate_threshold_change, not this module"},
    "test_issue_binds_the_exact_assessed_change": "c1_test_issue_binds_the_exact_assessed_change",
    "test_consume_certifies_exactly_one_matching_change": "c2_test_consume_certifies_exactly_one_matching_change",
    "test_revocation_and_degraded_states": "c3_test_revocation_and_degraded_states",
    "test_concurrent_consumers_on_postgres_get_one_certification": {"c4_test_concurrent_consumers_on_postgres_get_one_certification": "the sequential part; threads and PostgreSQL are not a scenario step"},
}

BRANCH_COVERAGE = {
    "_time raise ContractError('<name> must be ISO-8601 text') (require)": "c3 time: int, none, bytes, datetime_object; c2 expires_at_int/none",
    "_time except ValueError -> raise ContractError('<name> is not ISO-8601')": "c3 time: garbage, empty, date_only; c2 expires_at_garbage/date_only",
    "_time require tzinfo": "c3 time: naive; c2 expires_at_naive; c3 inspect_corrupt.expires_naive",
    "parse_applied_policy require key set": "c2 malformed_policies (not_a_dict, empty, missing_environment, extra_key); c3 parse_applied_policy",
    "parse_applied_policy require revisions": "c2 malformed_policies revision_*, previous_revision_*",
    "parse_applied_policy require values": "c2 malformed_policies values_*, previous_values_*",
    "parse_applied_policy require environment": "c2 malformed_policies environment_*",
    "ThresholdApprovals.__init__": "Case.approvals",
    "ThresholdApprovals._event": "c1 issued event; c2 refused/consumed events; c3 revoked event; sequence in c4.events",
    "issue require actor": "c1 actor_*", "issue require environment": "c1 environment_*", "issue require ttl_seconds": "c1 ttl_*",
    "issue require assessed request": "c1 not_assessed_pending, unknown_request",
    "issue require both independent assessments accepted": "c1 reviews_*, first_not_accepted, second_*, first_blocked, second_inspection_blocked, blocked_false_is_fine",
    "issue require row unchanged since review": "c1 binding_is_not_the_row, row_missing",
    "issue require reference-accepted suggestion": "c1 suggested_none, not_reference_accepted, reference_accepted_missing",
    "issue require finite different value": "c1 current_nan, suggested_inf, suggested_bool, current_bool, suggested_str, suggested_equals_current*",
    "issue require evidence still contains the proposal": "c1 evidence_lacks_the_proposal, evidence_proposal_differs, evidence_proposals_not_a_list",
    "issue artifacts.document": "c1 evidence_missing, evidence_ref_none, evidence_unreadable_propagates",
    "issue idempotent existing return": "c1 issued.reissue_same_binding_other_ttl_and_time",
    "issue put + issued event": "c1 issued",
    "_check not issued": "c2 status_*, repeat_after_consumption; c3 consume_after_revoke",
    "_check expired": "c2 expiry_exactly_at, expired, order_expired_before_environment",
    "_check environment": "c2 environment_differs", "_check previous revision": "c2 previous_revision_differs",
    "_check previous value": "c2 previous_value_differs, previous_value_missing", "_check applied value": "c2 applied_value_differs, applied_value_missing",
    "_check applied value type": "c2 applied_value_float_type", "_check unrelated thresholds": "c2 touches_other_threshold, other_threshold_added/removed",
    "_check revision equals previous": "c2 revision_equals_previous", "_check passes": "c2 consumed",
    "consume parse before the transaction": "c2 malformed_policies", "consume require approval": "c2 unknown_approval",
    "consume refusal event then ContractError": "c2 refusals, refusal_events", "consume generation": "c2 other_name_first_generation, same_name_*_generation; c4",
    "revoke require actor": "c3 actor_*", "revoke require reason": "c3 reason_*", "revoke require approval": "c3 unknown",
    "revoke already revoked": "c3 again_is_idempotent", "revoke require issued": "c2 revoke_after_consumption",
    "revoke put + revoked event": "c3 revoked, events",
    "inspect except Exception -> unreadable": "c3 unreadable_*; not_mapped_* (BaseException propagates)",
    "inspect missing": "c3 inspect_missing", "inspect except ContractError -> corrupt": "c3 inspect_corrupt",
    "inspect expired": "c3 inspect_expired, inspect_at_expiry_is_expired", "inspect fields": "c3 inspect_issued, inspect_exactly_the_keys",
}


def states_in(value, observed):
    if isinstance(value, dict):
        if isinstance(value.get("state"), str):
            observed.add(value["state"])
        for item in value.values():
            states_in(item, observed)
    elif isinstance(value, list):
        for item in value:
            states_in(item, observed)


def run(api) -> dict:
    result, counts, observed = {}, {}, set()
    for name, group in GROUPS:
        result[name] = group(api)
        counts[name] = len(result[name])
        states_in(result[name], observed)
    result["states_reached"] = {"reached": sorted(observed), "STATES": list(api.STATES), "equals_STATES_but_for_the_unstored": sorted(set(api.STATES) - observed)}
    result["constants"] = {"BUCKET": api.BUCKET, "EVENTS": api.EVENTS, "STATES": list(api.STATES), "ENVIRONMENT": api.ENVIRONMENT.pattern,
                           "REVISION": api.REVISION.pattern, "MAX_TTL_SECONDS": api.MAX_TTL_SECONDS}
    result["m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = counts
    return result
