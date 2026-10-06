"""The ONE consumption re-arm after an exhausted retry (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended).

The one consumption retry of a halted, bound first activation expired AGAIN with the owner canary still pending.
One explicit owner re-arm, bound to that exhausted halt, the spent retry, the linked restart (when recorded) and the
recorded user decision, opens ONE further interval of an EXPLICIT length for the SAME observed instance.

What is real: the `HostDelivery` lane code, the `Releases`/`ReleaseQueue` owners, the in-memory store, the
organization and the REAL process host target that starts, reports and is consumed.
What is a LABELLED FIXTURE: the GitHub port, the first-activation port, the counting verifier, the owner canary
double (`OwnerCanary`) and, where named, a host read wrapped to report another instance. Nothing here touches a
production host.
"""
from datetime import datetime, timedelta

import pytest
from test_host_delivery import binds_a_runtime, descriptor_of, drive, intent_of, stop_target
from test_host_delivery_consumption_retry import document as retry_document
from test_host_delivery_consumption_retry import halted, retry
from test_host_delivery_first_activation import snapshot

from codex_harness.application.host_delivery import BUCKET_PLANS
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    BLOCKED,
    CONSUMPTION_REARM_MAX_SECONDS,
    CONSUMPTION_REARM_SCHEMA,
    RECOVERY_CONSUMPTION_REARM,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_FIRST_ACTIVATION,
    DeliveryRefused,
    consumption_rearm_exhausted,
    consumption_rearmable,
    validate_consumption_rearm,
)
from codex_harness.domain.model import digest

AUTHORITY = "sha256:" + "a" * 64
OTHER_INSTANCE = "0" * 32


def rearm_document(system, **overrides):
    intent = intent_of(system)
    spent = [row for row in intent["recoveries"] if row["kind"] == RECOVERY_CONSUMPTION_RETRY][0]
    body, _ = retry_document(system, observed_instance_id=spent["observed"]["observed_instance_id"])
    body.update({"schema": CONSUMPTION_REARM_SCHEMA, "kind": RECOVERY_CONSUMPTION_REARM,
                 "retry_evidence": spent["evidence_ref"], "window_seconds": 3600, "authority": AUTHORITY})
    body.update(overrides)
    return body, "sha256:" + digest(body)


def rearm(system, body=None, evidence=None):
    if body is None:
        body, evidence = rearm_document(system)
    with system["store"].transaction() as tx:
        sha = tx.get(BUCKET_PLANS, system["plan"]["plan_id"])["plan_sha256"]
    return system["delivery"].resume_consumption_rearm(system["plan"]["plan_id"], sha, body,
                                                       evidence or "sha256:" + digest(body))


def rearm_refused(system, code, **kwargs):
    before = snapshot(system)
    with pytest.raises(DeliveryRefused) as caught:
        rearm(system, **kwargs)
    assert caught.value.reason_code == code, caught.value.reason_code
    assert snapshot(system) == before, "a refusal writes nothing"


def exhausted(system):
    """The one retry, then its window expires AGAIN with the canary still pending."""
    body, evidence = retry_document(system)
    retry(system, body, evidence)
    results = drive(system, until=ACTIVE, limit=40)
    assert results[-1]["reason_code"] == "no_known_good_predecessor", results[-1]
    return body, evidence


@pytest.fixture
def system(tmp_path, monkeypatch):
    built = halted(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        stop_target(built)


# ----- domain ---------------------------------------------------------------------------------
def _body():
    return {"schema": CONSUMPTION_REARM_SCHEMA, "kind": RECOVERY_CONSUMPTION_REARM, "plan_id": "own-p",
            "plan_sha256": "a" * 64, "pin_sha256": "b" * 64, "target_id": "t", "release_id": "r",
            "candidate_revision": "c" * 40, "candidate_tree": "7" * 40,
            "halt": {"stage": BLOCKED, "previous_stage": AWAITING_CONSUMPTION,
                     "reason_code": "no_known_good_predecessor", "updated_at": "2026-09-27T12:24:42+00:00",
                     "stage_deadline": "2026-09-27T12:24:37+00:00"},
            "first_activation_evidence": "sha256:" + "e" * 64, "descriptor_sha256": "d" * 64,
            "observed_instance_id": "i" * 32, "approved_by": "conductor", "retry_evidence": "sha256:" + "f" * 64,
            "window_seconds": 3600, "authority": AUTHORITY}


@pytest.mark.parametrize("field,value", [
    ("schema", "urn:zeus:host-delivery-consumption-retry:1"), ("kind", RECOVERY_CONSUMPTION_RETRY),
    ("window_seconds", 0), ("window_seconds", CONSUMPTION_REARM_MAX_SECONDS + 1), ("window_seconds", True),
    ("window_seconds", "3600"), ("window_seconds", 3600.0), ("retry_evidence", "sha256:short"),
    ("authority", ""), ("observed_instance_id", ""), ("approved_by", "x y"),
    ("halt", {"stage": BLOCKED})])
def test_the_document_grammar_is_exact(field, value):
    assert validate_consumption_rearm(_body())["window_seconds"] == 3600
    assert CONSUMPTION_REARM_MAX_SECONDS == 3600
    with pytest.raises(DeliveryRefused) as caught:
        validate_consumption_rearm({**_body(), field: value})
    assert caught.value.reason_code == "consumption_rearm_invalid"
    with pytest.raises(DeliveryRefused):
        validate_consumption_rearm({**_body(), "extra": 1})
    missing = _body()
    del missing["authority"]
    with pytest.raises(DeliveryRefused):
        validate_consumption_rearm(missing)


# ----- the re-arm -----------------------------------------------------------------------------
@binds_a_runtime
def test_after_the_retry_expires_again_one_rearm_opens_the_explicit_window_and_consumes_the_same_instance(system):
    retry_body, retry_evidence = exhausted(system)
    halted_intent = intent_of(system)
    spent = halted_intent["recoveries"][-1]
    instance = spent["observed"]["observed_instance_id"]
    assert consumption_rearmable(halted_intent) and not consumption_rearm_exhausted(halted_intent)
    # the one retry itself stays exhausted
    with pytest.raises(DeliveryRefused) as caught:
        retry(system, *retry_document(system))
    assert caught.value.reason_code == "resume_exhausted"
    before = snapshot(system)
    body, evidence = rearm_document(system)
    resumed = rearm(system, body, evidence)
    assert resumed["cached"] is False and resumed["stage"] == AWAITING_CONSUMPTION
    intent = intent_of(system)
    assert [row["kind"] for row in intent["recoveries"]] == [
        RECOVERY_FIRST_ACTIVATION, RECOVERY_CONSUMPTION_RETRY, RECOVERY_CONSUMPTION_REARM]
    record = intent["recoveries"][-1]
    # the window is the document's EXPLICIT 3600 s from one anchor, never the plan's timeout (10 s here)
    start, end = (datetime.fromisoformat(record["interval"][k]) for k in ("started_at", "deadline"))
    assert end - start == timedelta(seconds=3600) and intent["stage_deadline"] == record["interval"]["deadline"]
    assert record["window_seconds"] == 3600 and record["authority"] == AUTHORITY
    assert record["retry_evidence"] == retry_evidence and record["observed"]["observed_instance_id"] == instance
    # every earlier halt, deadline and recovery is kept unchanged
    assert intent["recoveries"][:2] == halted_intent["recoveries"]
    for key in ("stage", "previous_stage", "reason_code", "updated_at", "stage_deadline", "rollback", "canary"):
        assert record["halted"][key] == halted_intent[key], key
    after = snapshot(system)
    assert after["descriptors"] == before["descriptors"] and after["release"] == before["release"]
    assert len(after["queue"]["manual_retries"]) == len(before["queue"]["manual_retries"]) + 1
    shown = system["delivery"].status()["deliveries"][0]["recoveries"][-1]
    assert (shown["kind"], shown["window_seconds"], shown["retry_evidence"], shown["authority"]) == (
        RECOVERY_CONSUMPTION_REARM, 3600, retry_evidence, AUTHORITY)
    assert shown["interval"] == record["interval"]
    # well inside the window the pending canary only waits (the plan's 10 s no longer caps it)
    system["clock"].advance(1200)
    assert system["delivery"].tick()["stage"] == AWAITING_CONSUMPTION
    asked = len(system["canary"].calls)
    system["canary"].answer = {"passed": True, "reason_code": None, "evidence": "sha256:" + "4" * 64}
    assert drive(system, until=ACTIVE, limit=10)[-1]["stage"] == ACTIVE
    row = descriptor_of(system)
    assert row["consumed"] is True and row["instance_id"] == instance
    assert set(system["canary"].calls[asked:]) == {instance}
    assert rearm(system, body, evidence)["cached"] is True
    assert system["verifier"].calls == []


@binds_a_runtime
def test_the_rearm_window_expires_exactly_at_its_own_deadline_and_is_then_final(system):
    exhausted(system)
    body, evidence = rearm_document(system)
    rearm(system, body, evidence)
    deadline = datetime.fromisoformat(intent_of(system)["stage_deadline"])
    now = datetime.fromisoformat(system["clock"]())
    system["clock"].advance((deadline - now).total_seconds() - 2)
    assert system["delivery"].tick()["stage"] == AWAITING_CONSUMPTION, "one second before: still waiting"
    system["clock"].advance(2)
    result = system["delivery"].tick()
    assert (result["stage"], result["reason_code"]) == (BLOCKED, "no_known_good_predecessor"), result
    final = intent_of(system)
    assert consumption_rearm_exhausted(final) and not consumption_rearmable(final)
    assert rearm(system, body, evidence)["cached"] is True
    other, other_evidence = rearm_document(system, authority="sha256:" + "b" * 64)
    rearm_refused(system, "resume_exhausted", body=other, evidence=other_evidence)
    with pytest.raises(DeliveryRefused) as caught:
        retry(system, *retry_document(system))
    assert caught.value.reason_code == "resume_exhausted"
    kinds = [row["kind"] for row in final["recoveries"]]
    assert kinds.count(RECOVERY_CONSUMPTION_REARM) == 1 and kinds.count(RECOVERY_CONSUMPTION_RETRY) == 1


@binds_a_runtime
def test_one_rearm_per_delivery_another_evidence_conflicts(system):
    exhausted(system)
    body, evidence = rearm_document(system)
    rearm(system, body, evidence)
    other = {**body, "authority": "sha256:" + "b" * 64}
    rearm_refused(system, "resume_conflict", body=other, evidence="sha256:" + digest(other))


@binds_a_runtime
def test_no_rearm_before_the_retry_is_spent_and_exhausted(system):
    intent = intent_of(system)
    assert not consumption_rearmable(intent)
    retry_body, _ = retry_document(system)
    fake = {**retry_body, "schema": CONSUMPTION_REARM_SCHEMA, "kind": RECOVERY_CONSUMPTION_REARM,
            "retry_evidence": "sha256:" + "f" * 64, "window_seconds": 3600, "authority": AUTHORITY}
    rearm_refused(system, "resume_not_applicable", body=fake, evidence="sha256:" + digest(fake))
    retry(system)
    spent = intent_of(system)["recoveries"][-1]
    live = {**fake, "retry_evidence": spent["evidence_ref"],
            "observed_instance_id": spent["observed"]["observed_instance_id"]}
    rearm_refused(system, "resume_not_applicable", body=live, evidence="sha256:" + digest(live))


@binds_a_runtime
@pytest.mark.parametrize("overrides,code", [
    ({"retry_evidence": "sha256:" + "0" * 64}, "consumption_rearm_retry_mismatch"),
    ({"observed_instance_id": OTHER_INSTANCE}, "consumption_rearm_retry_mismatch"),
    ({"first_activation_evidence": "sha256:" + "0" * 64}, "consumption_rearm_first_activation_mismatch"),
    ({"descriptor_sha256": "0" * 64}, "consumption_rearm_descriptor_mismatch"),
    ({"approved_by": "worker:improvement-1"}, None),
    ({"generation_restart_evidence": "sha256:" + "0" * 64}, "consumption_rearm_restart_link_mismatch")])
def test_stale_or_foreign_claims_refuse_with_no_write(system, overrides, code):
    exhausted(system)
    body, evidence = rearm_document(system, **overrides)
    before = snapshot(system)
    with pytest.raises(DeliveryRefused) as caught:
        rearm(system, body, evidence)
    if code is not None:
        assert caught.value.reason_code == code, caught.value.reason_code
    assert snapshot(system) == before


@binds_a_runtime
def test_the_expired_halt_cannot_be_rewritten(system):
    exhausted(system)
    body, evidence = rearm_document(system)
    body["halt"] = {**body["halt"], "stage_deadline": "2099-01-01T00:00:00+00:00"}
    rearm_refused(system, "consumption_rearm_halt_mismatch", body=body, evidence="sha256:" + digest(body))


@binds_a_runtime
def test_the_live_host_must_show_the_same_alive_instance(system):
    exhausted(system)
    stop_target(system)
    rearm_refused(system, "consumption_retry_instance_stopped")


@binds_a_runtime
def test_a_different_instance_after_the_rearm_halts_retry_instance_changed(system):
    exhausted(system)
    rearm(system)
    real = system["host"].receipt

    def foreign(target):
        return {**real(target), "instance_id": OTHER_INSTANCE}

    system["host"].receipt = foreign
    result = system["delivery"].tick()
    assert (result["stage"], result["reason_code"]) == (BLOCKED, "retry_instance_changed"), result
    row = descriptor_of(system)
    assert row["consumed"] is False and row["instance_id"] is None


def test_the_resume_command_dispatches_a_rearm_document(tmp_path, monkeypatch):
    """`host-delivery resume --document FILE` routes a re-arm document to `resume_consumption_rearm` only."""
    import json
    from types import SimpleNamespace

    from codex_harness import cli
    from codex_harness.adapters import host_delivery
    from codex_harness.adapters.store import MemoryStore
    from codex_harness.bootstrap import organization

    body = {"kind": RECOVERY_CONSUMPTION_REARM}
    path = tmp_path / "rearm.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    argv = ["host-delivery", "resume", "--lane", "harness", "--plan", "own-plan", "--plan-sha256", "c" * 64,
            "--evidence", "sha256:" + "e" * 64, "--document", str(path)]
    calls = []

    class Controller:
        def resume_consumption_retry(self, *arguments):
            calls.append(("consumption_retry", arguments))
            return {"resumed": True}

        def resume_consumption_rearm(self, *arguments):
            calls.append(("consumption_rearm", arguments))
            return {"resumed": True}

    route = {"lane": {"id": "harness", "repository": str(tmp_path), "runtime": str(tmp_path / "rt")},
             "store": MemoryStore()}
    monkeypatch.setattr(host_delivery, "resolve_lane", lambda _service, lane_id: route)
    monkeypatch.setattr(host_delivery, "lane_git", lambda lane, host: SimpleNamespace(remote="zeus-owner/zeus-harness"))
    monkeypatch.setattr(host_delivery, "_lane_observer", lambda _route: None)
    monkeypatch.setattr(host_delivery, "_settings", lambda: {})
    monkeypatch.setattr(host_delivery, "controller", lambda _service, **kwargs: Controller())
    service = SimpleNamespace(store=MemoryStore(), org=organization())
    assert host_delivery.execute(service, cli.parser().parse_args(argv))["exit_code"] == 0
    assert calls == [("consumption_rearm", ("own-plan", "c" * 64, body, "sha256:" + "e" * 64))]
    path.write_text(json.dumps({"kind": RECOVERY_CONSUMPTION_RETRY}), encoding="utf-8")
    calls.clear()
    host_delivery.execute(service, cli.parser().parse_args(argv))
    assert calls[0][0] == "consumption_retry"
