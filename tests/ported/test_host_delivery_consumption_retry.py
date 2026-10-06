"""Ported SOURCE M7 suite `tests/test_host_delivery_consumption_retry.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_delivery` shim
docstring names the routing): `HostDelivery`, `Releases`, `ReleaseQueue`, `ProcessHostTarget`, `GitHubDelivery`, the
canary and runtime helpers, `Fleet`, `organization`, `MemoryStore`, `GitWorkspace`, `MergeRefused`, `ContractError`,
`POLICY` and `digest` come from the shim over the S7 split objects and moved adapters; the domain names from
`delivery.domain.host_delivery`, the BUCKET_* names from `delivery.application.host_delivery.state`, the fleet names
from `coordination`, the observation names from `observation`. A name whose owner is in a later slice (the operator
CLI and lane resolution, S10; the release evaluator and `verification_fixtures`, S8; the Windows scheduled task,
W-B) is an `unavailable(slice, name)` placeholder, and only tests skipped whole and unrewritten (each with its owning
slice) name it.

S10 unit C8b-4 (R-c31) un-skipped the cases that name only the host-delivery CLI and composition functions (import lines, call names and patch targets only): `cli_host_delivery` is `composition.cli_host_delivery`, `execute` is `entry.cli.host_delivery._execute` and `add_parser` is `entry.cli.host_delivery.add_parser`; the production coordinator is the S7 split owners, so a patched `controller` returns them (`SimpleNamespace(recovery=..., resumption=...)`) and `controller(...)` reading M7's one object is the shim `HostDelivery` over `controller_ports`. 

M7 docstring follows.

The first-activation consumption retry (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended).

What is real: the `HostDelivery` lane code, the `Releases`/`ReleaseQueue` owners, the store (the
in-memory store, and an isolated PostgreSQL schema when `HARNESS_INTEGRATION=1`; without it that
parameter SKIPS and is not evidence), the organization and the REAL process host target that starts,
reports and is consumed.

What is a LABELLED FIXTURE: the GitHub port (`FakeGitHub`), the first-activation port (`FixedFacts`),
the counting verifier double, the owner canary double (`OwnerCanary`: a switchable pending/passed/
failed answer, never an actual fleet canary) and, where named, a host read wrapped to report a
missing, stopped, foreign or changed instance. Nothing here touches a production host.
"""
import threading

import pytest
from m7_delivery import ContractError, MemoryStore, digest
from test_host_delivery import (
    CANARY_FLEET,
    PROFILE,
    binds_a_runtime,
    build,
    descriptor_of,
    drive,
    intent_of,
    register_historical,
    stop_target,
)
from test_host_delivery_first_activation import (
    IMAGE_ID,
    ConductorFor,
    CountingVerifier,
    FixedFacts,
    snapshot,
)
from test_host_delivery_first_activation import document as binding_document

from codex_harness.delivery.application.host_delivery.state import BUCKET_DESCRIPTORS, BUCKET_PLANS
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    BLOCKED,
    CONSUMPTION_RETRY_SCHEMA,
    MERGED,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_FIRST_ACTIVATION,
    UNCHANGED,
    DeliveryRefused,
    consumption_retryable,
    validate_consumption_retry,
)

PENDING = "canary_owner_receipt_pending"
OTHER_INSTANCE = "0" * 32


class OwnerCanary:
    """LABELLED DOUBLE of the owner fleet canary: pending until switched; every call counted."""

    def __init__(self):
        self.answer = {"passed": False, "pending": True, "reason_code": PENDING, "evidence": None}
        self.calls = []

    def __call__(self, target, descriptor, startup, **kwargs):
        self.calls.append(startup.get("instance_id"))
        return dict(self.answer)


def halted(tmp_path, monkeypatch, store=None, answer=None, retryable=True):
    """The actual producer chain up to the halt: a historical unbound first activation, its binding,
    the real startup and an owner canary still PENDING when the consumption deadline expires."""
    monkeypatch.setenv("ZEUS_WORKER_IMAGE", IMAGE_ID)
    canary = OwnerCanary()
    if answer is not None:
        canary.answer = dict(answer)
    system = build(tmp_path, plan_overrides={"image": UNCHANGED, "profile": UNCHANGED, "canary": CANARY_FLEET,
                                             "consumption_timeout": 10},
                   register_plan=False, store=store, canaries={CANARY_FLEET: canary})
    register_historical(system)
    drive(system, until=MERGED, limit=8)
    assert system["delivery"].tick()["reason_code"] == "unchanged_without_predecessor"
    system["delivery"].first_activation = FixedFacts(profile=PROFILE)
    system["verifier"] = CountingVerifier()
    system["delivery"].verifier = system["verifier"]
    system["canary"] = canary
    body, evidence = binding_document(system, profile_digest=PROFILE)
    system["delivery"].resume_first_activation(system["plan"]["plan_id"], body["plan_sha256"], body, evidence)
    system["binding_evidence"] = evidence
    results = drive(system, until=ACTIVE, limit=40)
    assert results[-1]["reason_code"] == "no_known_good_predecessor", results[-1]
    intent = intent_of(system)
    assert consumption_retryable(intent) is retryable, intent
    return system


def document(system, **overrides):
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_PLANS, system["plan"]["plan_id"])
    intent = intent_of(system)
    body = {"schema": CONSUMPTION_RETRY_SCHEMA, "kind": RECOVERY_CONSUMPTION_RETRY,
            "plan_id": row["plan_id"], "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"],
            "target_id": row["target_id"], "release_id": system["release"]["id"],
            "candidate_revision": system["release"]["candidate"]["revision"],
            "candidate_tree": system["release"]["candidate"]["tree"],
            "halt": {key: intent[key] for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                  "stage_deadline")},
            "first_activation_evidence": system["binding_evidence"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "observed_instance_id": intent["candidate_instance_id"], "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + digest(body)


def retry(system, body=None, evidence=None, delivery=None):
    if body is None:
        body, evidence = document(system)
    with system["store"].transaction() as tx:
        sha = tx.get(BUCKET_PLANS, system["plan"]["plan_id"])["plan_sha256"]
    return (delivery or system["delivery"]).resume_consumption_retry(system["plan"]["plan_id"], sha, body,
                                                                     evidence or "sha256:" + digest(body))


def refused(system, code, **kwargs):
    before = snapshot(system)
    with pytest.raises(DeliveryRefused) as caught:
        retry(system, **kwargs)
    assert caught.value.reason_code == code, caught.value.reason_code
    assert snapshot(system) == before, "a refusal writes nothing"


@pytest.fixture
def system(tmp_path, monkeypatch):
    built = halted(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        stop_target(built)


# ----- domain ---------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("kind", RECOVERY_FIRST_ACTIVATION), ("schema", "urn:zeus:other:1"), ("observed_instance_id", ""),
    ("first_activation_evidence", "sha256:xyz"), ("descriptor_sha256", "nope"),
    ("halt", {"stage": BLOCKED, "previous_stage": MERGED, "reason_code": "no_known_good_predecessor",
              "updated_at": "t", "stage_deadline": "t"})])
def test_the_document_grammar_is_exact(field, value):
    body = {"schema": CONSUMPTION_RETRY_SCHEMA, "kind": RECOVERY_CONSUMPTION_RETRY, "plan_id": "p",
            "plan_sha256": "a" * 64, "pin_sha256": "b" * 64, "target_id": "t", "release_id": "r",
            "candidate_revision": "c" * 40, "candidate_tree": "d" * 40,
            "halt": {"stage": BLOCKED, "previous_stage": AWAITING_CONSUMPTION,
                     "reason_code": "no_known_good_predecessor", "updated_at": "t", "stage_deadline": "t"},
            "first_activation_evidence": "sha256:" + "e" * 64, "descriptor_sha256": "f" * 64,
            "observed_instance_id": "instance-1", "approved_by": "conductor"}
    assert validate_consumption_retry(body)["kind"] == RECOVERY_CONSUMPTION_RETRY
    with pytest.raises(DeliveryRefused) as caught:
        validate_consumption_retry({**body, field: value})
    assert caught.value.reason_code == "consumption_retry_invalid"
    with pytest.raises(DeliveryRefused):
        validate_consumption_retry({**body, "extra": 1})


# ----- the actual producer chain ----------------------------------------------------------------
@binds_a_runtime
def test_the_retry_consumes_the_same_instance_and_promotes(system):
    before = snapshot(system)
    halted_intent = intent_of(system)
    facts_calls = len(system["delivery"].first_activation.calls)
    observed = halted_intent["candidate_instance_id"]
    receipt_before = system["host"].receipt(system["target"])
    assert receipt_before["instance_id"] == observed
    receipt = retry(system)
    assert receipt["cached"] is False and receipt["stage"] == AWAITING_CONSUMPTION
    assert receipt["recovery"]["kind"] == RECOVERY_CONSUMPTION_RETRY
    intent = intent_of(system)
    assert (intent["stage"], intent["previous_stage"], intent["outcome"], intent["reason_code"],
            intent["attempts"], intent["rollback"], intent["canary"]) == (
        AWAITING_CONSUMPTION, BLOCKED, "pending", None, 0, None, None)
    recovery = intent["recoveries"][-1]
    assert recovery["halted"]["stage_deadline"] == halted_intent["stage_deadline"]
    assert recovery["halted"]["rollback"] == halted_intent["rollback"]
    assert recovery["interval"]["deadline"] == intent["stage_deadline"] != halted_intent["stage_deadline"]
    assert recovery["observed"]["observed_instance_id"] == observed
    # The descriptor row is never rewritten by the retry.
    assert snapshot(system)["descriptors"] == before["descriptors"]
    assert snapshot(system)["release"] == before["release"]
    assert snapshot(system)["plan"] == before["plan"]
    assert intent["descriptor"] == halted_intent["descriptor"], "the bound image/profile/revision are unchanged"
    assert len(system["delivery"].first_activation.calls) == facts_calls
    view = system["delivery"].status()["deliveries"][0]
    assert view["stage_deadline"] == intent["stage_deadline"]
    shown = view["recoveries"][-1]
    assert shown["kind"] == RECOVERY_CONSUMPTION_RETRY and shown["evidence_ref"] == recovery["evidence_ref"]
    assert shown["halted"]["stage_deadline"] == halted_intent["stage_deadline"]
    # the exact halt a document binds, and its pending-canary facts, are projected (no private store read)
    assert {k: shown["halted"][k] for k in ("stage", "previous_stage", "reason_code", "updated_at")} == {
        "stage": "blocked", "previous_stage": "awaiting_consumption", "reason_code": "no_known_good_predecessor",
        "updated_at": halted_intent["updated_at"]}
    assert shown["halted"]["rollback"] == {"requested": True, "restored": False, "verified": False,
                                           "reason_code": "canary_owner_receipt_pending"}
    assert shown["halted"]["canary"]["pending"] is True and shown["halted"]["canary"]["passed"] is False
    assert shown["interval"] == recovery["interval"]
    assert shown["observed"] == {"observed_instance_id": observed,
                                 "descriptor_sha256": intent["descriptor_sha256"]}
    assert view["recoveries"][0]["kind"] == RECOVERY_FIRST_ACTIVATION and "interval" not in view["recoveries"][0]
    # Pending once more, then the owner canary passes: the SAME instance is consumed and promoted.
    pending = system["delivery"].tick()
    assert (pending["stage"], pending["outcome"]) == (AWAITING_CONSUMPTION, "pending"), pending
    system["canary"].answer = {"passed": True, "reason_code": None, "evidence": "sha256:" + "4" * 64}
    results = drive(system, until=ACTIVE, limit=10)
    assert results[-1]["stage"] == ACTIVE, results[-1]
    row = descriptor_of(system)
    assert row["consumed"] is True and row["instance_id"] == observed
    assert set(system["canary"].calls) == {observed}
    with system["store"].transaction() as tx:
        assert tx.get("deployment", "active")["release_id"] == system["release"]["id"]
    assert system["verifier"].calls == []
    # The SAME process: no new receipt and no new launch between the halt and the activation.
    assert system["host"].receipt(system["target"]) == receipt_before
    assert intent_of(system)["recoveries"][-1]["halted"] == recovery["halted"], "the old halt is history"


@binds_a_runtime
def test_the_same_evidence_is_cached_at_every_later_stage_and_another_conflicts(system):
    body, evidence = document(system)
    first = retry(system, body, evidence)
    before = snapshot(system)
    assert retry(system, body, evidence)["cached"] is True and snapshot(system) == before
    system["canary"].answer = {"passed": True, "reason_code": None, "evidence": None}
    assert drive(system, until=ACTIVE, limit=10)[-1]["stage"] == ACTIVE
    before = snapshot(system)
    again = retry(system, body, evidence)
    assert again["cached"] is True and again["recovery"] == first["recovery"] and snapshot(system) == before
    other, other_evidence = document(system, halt=body["halt"], descriptor_sha256=body["descriptor_sha256"],
                                     observed_instance_id=body["observed_instance_id"],
                                     approved_by="conductor", first_activation_evidence="sha256:" + "0" * 64)
    refused(system, "resume_conflict", body=other, evidence=other_evidence)


@binds_a_runtime
def test_a_second_expiry_halts_again_and_is_exhausted(system):
    body, evidence = document(system)
    retry(system, body, evidence)
    results = drive(system, until=ACTIVE, limit=40)
    assert results[-1]["reason_code"] == "no_known_good_predecessor", results[-1]
    assert retry(system, body, evidence)["cached"] is True
    second, second_evidence = document(system)
    refused(system, "resume_exhausted", body=second, evidence=second_evidence)
    assert len([row for row in intent_of(system)["recoveries"] if row["kind"] == RECOVERY_CONSUMPTION_RETRY]) == 1


@binds_a_runtime
def test_a_different_instance_after_the_retry_halts_retry_instance_changed(system):
    retry(system)
    real = system["host"].receipt

    def foreign(target):
        return {**real(target), "instance_id": OTHER_INSTANCE}

    system["host"].receipt = foreign
    result = system["delivery"].tick()
    assert (result["stage"], result["reason_code"]) == (BLOCKED, "retry_instance_changed"), result
    row = descriptor_of(system)
    assert row["consumed"] is False and row["instance_id"] is None


# ----- refusals with no write ---------------------------------------------------------------------
def _missing(host):
    host.receipt = lambda target: None


def _stopped(host):
    real = host.identity
    host.identity = lambda target: {**real(target), "running": False}


def _foreign_descriptor(host):
    real = host.identity
    host.identity = lambda target: {**real(target), "descriptor_sha256": "0" * 64}


def _changed(host):
    real = host.receipt
    host.receipt = lambda target: {**real(target), "instance_id": OTHER_INSTANCE}


@binds_a_runtime
@pytest.mark.parametrize("fault,code", [
    (_missing, "consumption_retry_instance_missing"), (_stopped, "consumption_retry_instance_stopped"),
    (_foreign_descriptor, "consumption_retry_host_descriptor_changed"),
    (_changed, "consumption_retry_instance_changed")])
def test_the_live_host_must_show_the_same_alive_instance(system, fault, code):
    fault(system["host"])
    refused(system, code)


@binds_a_runtime
@pytest.mark.parametrize("field,value,code", [
    ("observed_instance_id", OTHER_INSTANCE, "consumption_retry_instance_mismatch"),
    ("descriptor_sha256", "0" * 64, "consumption_retry_descriptor_mismatch"),
    ("first_activation_evidence", "sha256:" + "0" * 64, "consumption_retry_first_activation_mismatch"),
    ("approved_by", "lead:improvement", "consumption_retry_approver_invalid"),
    ("candidate_tree", "0" * 40, "consumption_retry_candidate_tree_mismatch"),
    ("pin_sha256", "0" * 64, "consumption_retry_pin_mismatch")])
def test_stale_or_foreign_claims_refuse_with_no_write(system, field, value, code):
    body, evidence = document(system, **{field: value})
    refused(system, code, body=body, evidence=evidence)


@binds_a_runtime
def test_the_old_deadline_cannot_be_rewritten(system):
    body, _ = document(system)
    halt = {**body["halt"], "stage_deadline": "2999-01-01T00:00:00+00:00"}
    body, evidence = document(system, halt=halt)
    refused(system, "consumption_retry_halt_mismatch", body=body, evidence=evidence)


@binds_a_runtime
def test_the_author_cannot_approve(system):
    author = system["release"]["candidate"]["author"]
    system["delivery"].org = ConductorFor(system["org"], author)
    body, evidence = document(system, approved_by=author)
    refused(system, "consumption_retry_approver_author", body=body, evidence=evidence)


@binds_a_runtime
@pytest.mark.parametrize("change,code", [
    ({"consumed": True}, "consumption_retry_descriptor_state"),
    ({"startup_observed": False}, "consumption_retry_descriptor_state"),
    ({"observed_instance_id": OTHER_INSTANCE}, "consumption_retry_instance_mismatch")])
def test_a_changed_descriptor_row_refuses(system, change, code):
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_DESCRIPTORS, system["plan"]["target_id"])
        tx.put(BUCKET_DESCRIPTORS, system["plan"]["target_id"], {**row, **change})
    refused(system, code)


@binds_a_runtime
def test_a_live_lease_or_an_active_pointer_refuses(system):
    with system["store"].transaction() as tx:
        tx.put("deployment_locks", "controller", {"id": "controller", "lease_until": "2999-01-01T00:00:00+00:00"})
    refused(system, "resume_controller_running")
    with system["store"].transaction() as tx:
        tx.put("deployment_locks", "controller", {"id": "controller", "lease_until": "2000-01-01T00:00:00+00:00"})
        tx.put("deployment", "active", {"id": "active", "release_id": system["release"]["id"]})
    refused(system, "consumption_retry_release_active")


def test_an_actually_failed_canary_never_qualifies():
    intent = {"stage": BLOCKED, "reason_code": "no_known_good_predecessor",
              "previous_stage": AWAITING_CONSUMPTION, "previous_descriptor": None,
              "descriptor": {"revision": "a" * 40}, "descriptor_sha256": "f" * 64,
              "rollback": {"requested": True, "restored": False, "verified": False, "reason_code": PENDING},
              "canary": {"passed": False, "pending": True, "check_id": CANARY_FLEET, "evidence": None,
                         "reason_code": PENDING},
              "recoveries": [{"kind": RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "1" * 64}]}
    assert consumption_retryable(intent)
    failed = {**intent, "canary": {"passed": False, "check_id": CANARY_FLEET, "evidence": None,
                                   "reason_code": "canary_failed"},
              "rollback": {**intent["rollback"], "reason_code": "canary_failed"}}
    assert not consumption_retryable(failed)
    assert not consumption_retryable({**intent, "recoveries": []})
    assert not consumption_retryable({**intent, "previous_descriptor": {"revision": "b" * 40}})
    assert not consumption_retryable({**intent, "recoveries": [*intent["recoveries"],
                                                               {"kind": RECOVERY_CONSUMPTION_RETRY}]})


@binds_a_runtime
def test_a_failed_transaction_writes_nothing(system):
    queue = system["delivery"].queue
    real = queue.retry

    def failing(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("injected inside the transaction")

    queue.retry = failing
    body, evidence = document(system)
    before = snapshot(system)
    with pytest.raises(DeliveryRefused) as caught:
        retry(system, body, evidence)
    assert caught.value.reason_code == "resume_unobservable"
    assert snapshot(system) == before
    queue.retry = real
    assert retry(system, body, evidence)["queue"]["manual_retries"] == len(before["queue"]["manual_retries"]) + 1


@binds_a_runtime
def test_a_promotion_refusal_after_the_retry_is_unchanged(system):
    retry(system)
    system["canary"].answer = {"passed": True, "reason_code": None, "evidence": None}

    def refuse(*args, **kwargs):
        raise ContractError("injected promotion refusal")

    system["delivery"].releases.promote = refuse
    results = drive(system, until=ACTIVE, limit=10)
    assert (results[-1]["stage"], results[-1]["reason_code"]) == (BLOCKED, "release_promotion_refused")
    assert descriptor_of(system)["consumed"] is True


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def concurrent_store(request):
    if request.param == "memory":
        return MemoryStore()
    return request.getfixturevalue("isolated_pgstore")


@binds_a_runtime
def test_two_concurrent_retries_retry_the_queue_once(tmp_path, monkeypatch, concurrent_store):
    system = halted(tmp_path, monkeypatch, store=concurrent_store)
    try:
        body, evidence = document(system)
        barrier = threading.Barrier(2)
        real = system["host"].identity

        def gated(target):
            barrier.wait(timeout=10)
            return real(target)

        system["host"].identity = gated
        before = len(snapshot(system)["queue"]["manual_retries"])
        results, errors = [], []

        def run():
            try:
                results.append(retry(system, body, evidence))
            except Exception as exc:  # recorded for the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert errors == [] and sorted(result["cached"] for result in results) == [False, True]
        assert len(snapshot(system)["queue"]["manual_retries"]) == before + 1
        assert len([row for row in intent_of(system)["recoveries"]
                    if row["kind"] == RECOVERY_CONSUMPTION_RETRY]) == 1
    finally:
        stop_target(system)


def test_the_resume_command_dispatches_on_the_document_kind(tmp_path, monkeypatch):
    """`host-delivery resume --document FILE` routes a retry document to `resume_consumption_retry`."""
    import json
    from types import SimpleNamespace

    from m7_delivery import organization

    from codex_harness.composition import cli_host_delivery as host_delivery
    from codex_harness.entry import cli
    from codex_harness.entry.cli.host_delivery import _execute as execute

    body = {"kind": RECOVERY_CONSUMPTION_RETRY}
    path = tmp_path / "retry.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    argv = ["host-delivery", "resume", "--lane", "harness", "--plan", "own-plan", "--plan-sha256", "c" * 64,
            "--evidence", "sha256:" + "e" * 64, "--document", str(path)]
    calls = []

    class Controller:
        def resume_first_activation(self, *arguments):
            calls.append(("first_activation", arguments))
            return {"resumed": True}

        def resume_consumption_retry(self, *arguments):
            calls.append(("consumption_retry", arguments))
            return {"resumed": True}

    route = {"lane": {"id": "harness", "repository": str(tmp_path), "runtime": str(tmp_path / "rt")},
             "store": MemoryStore()}
    monkeypatch.setattr(host_delivery, "resolve_lane", lambda _service, lane_id: route)
    monkeypatch.setattr(host_delivery, "lane_git", lambda lane, host: SimpleNamespace(remote="zeus-owner/zeus-harness"))
    monkeypatch.setattr(host_delivery, "_lane_observer", lambda _route: None)
    monkeypatch.setattr(host_delivery, "_settings", lambda: {})
    monkeypatch.setattr(host_delivery, "controller", lambda _service, **kwargs: SimpleNamespace(recovery=Controller(), resumption=Controller()))
    service = SimpleNamespace(store=MemoryStore(), org=organization())
    assert execute(service, cli.parser().parse_args(argv))["exit_code"] == 0
    assert calls == [("consumption_retry", ("own-plan", "c" * 64, body, "sha256:" + "e" * 64))]
    path.write_text(json.dumps({"kind": RECOVERY_FIRST_ACTIVATION}), encoding="utf-8")
    calls.clear()
    execute(service, cli.parser().parse_args(argv))
    assert calls[0][0] == "first_activation"


@binds_a_runtime
def test_an_actually_failed_canary_halt_is_not_retryable(tmp_path, monkeypatch):
    failed = {"passed": False, "reason_code": "canary_owner_rejected", "evidence": None}
    system = halted(tmp_path, monkeypatch, answer=failed, retryable=False)
    try:
        assert intent_of(system)["rollback"]["reason_code"] == "canary_owner_rejected"
        refused(system, "resume_not_applicable")
    finally:
        stop_target(system)


class AdvancingClock:
    """LABELLED: a production-like clock that advances one microsecond on EVERY read (frozen fixture clocks hid F1)."""

    def __init__(self, start: str):
        from datetime import datetime
        self.at, self.reads = datetime.fromisoformat(start), 0

    def __call__(self) -> str:
        from datetime import timedelta
        self.reads += 1
        self.at += timedelta(microseconds=1)
        return self.at.isoformat()


def test_an_advancing_clock_still_records_exactly_the_plan_window_from_one_anchor(system):
    """PR216 review F1: the interval is ONE clock read + the plan's immutable timeout; the recovery, the intent's
    stage entry/deadline and the status projection agree to the microsecond, and the old deadline stays history."""
    from datetime import datetime, timedelta
    delivery = system["delivery"]
    halted_intent = intent_of(system)
    delivery.clock = AdvancingClock(system["clock"]())
    # retained control: a SECOND read (the pre-fix code path) drifts past the plan window
    anchor = delivery.clock()
    assert datetime.fromisoformat(delivery._deadline(10)) - datetime.fromisoformat(anchor) > timedelta(seconds=10)
    retry(system)
    intent = intent_of(system)
    recovery = intent["recoveries"][-1]
    started, deadline = (datetime.fromisoformat(recovery["interval"][k]) for k in ("started_at", "deadline"))
    assert deadline - started == timedelta(seconds=10), (started, deadline)
    assert (intent["stage_entered_at"], intent["stage_deadline"]) == (recovery["interval"]["started_at"],
                                                                      recovery["interval"]["deadline"])
    assert recovery["halted"]["stage_deadline"] == halted_intent["stage_deadline"], "the expired deadline is history"
    view = delivery.status()["deliveries"][0]
    assert view["stage_deadline"] == recovery["interval"]["deadline"]
    assert view["recoveries"][-1]["interval"] == recovery["interval"]
