"""The first-activation generation restart (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended).

The observed instance of a halted, bound first activation POSITIVELY stopped (a host restart ended it and
left its receipt): the one consumption retry has nothing live to consume and refuses. The owner restarts the
SAME bound descriptor once through the target's own guarded lifecycle, and the one retry then consumes exactly
the linked new generation.

What is real: the `HostDelivery` lane code, the `Releases`/`ReleaseQueue` owners, the store (in memory, and an
isolated PostgreSQL schema when `HARNESS_INTEGRATION=1`; without it that parameter SKIPS and is not evidence),
the organization and the REAL process host target that is stopped, restarted, reports and is consumed.
What is a LABELLED FIXTURE: the GitHub port, the first-activation port, the counting verifier, the owner
canary double (`OwnerCanary`) and, where named, a host read wrapped to report a foreign or unobservable
target. Nothing here touches a production host.
"""
import threading

import pytest
from test_host_delivery import binds_a_runtime, descriptor_of, drive, intent_of, stop_target
from test_host_delivery_consumption_retry import document as retry_document
from test_host_delivery_consumption_retry import halted, refused, retry
from test_host_delivery_first_activation import snapshot

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import BUCKET_PLANS
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    BLOCKED,
    CONSUMPTION_RETRY_RESTART_FIELD,
    GENERATION_RESTART_SCHEMA,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_FIRST_ACTIVATION,
    RECOVERY_GENERATION_RESTART,
    DeliveryRefused,
    generation_restartable,
    validate_generation_restart,
)
from codex_harness.domain.model import digest

OTHER_INSTANCE = "0" * 32


def restart_document(system, **overrides):
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_PLANS, system["plan"]["plan_id"])
    intent = intent_of(system)
    body = {"schema": GENERATION_RESTART_SCHEMA, "kind": RECOVERY_GENERATION_RESTART,
            "plan_id": row["plan_id"], "plan_sha256": row["plan_sha256"], "pin_sha256": row["pin"]["sha256"],
            "target_id": row["target_id"], "release_id": system["release"]["id"],
            "candidate_revision": system["release"]["candidate"]["revision"],
            "candidate_tree": system["release"]["candidate"]["tree"],
            "halt": {key: intent[key] for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                   "stage_deadline")},
            "first_activation_evidence": system["binding_evidence"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "stopped_instance_id": intent["candidate_instance_id"], "reason": "host_restarted",
            "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + digest(body)


def restart(system, body=None, evidence=None, **kwargs):
    if body is None:
        body, evidence = restart_document(system)
    with system["store"].transaction() as tx:
        sha = tx.get(BUCKET_PLANS, system["plan"]["plan_id"])["plan_sha256"]
    return system["delivery"].resume_generation_restart(
        system["plan"]["plan_id"], sha, body, evidence or "sha256:" + digest(body),
        startup_seconds=kwargs.get("startup_seconds", 30.0), poll_seconds=0.05)


def restart_refused(system, code, **kwargs):
    before = snapshot(system)
    with pytest.raises(DeliveryRefused) as caught:
        restart(system, **kwargs)
    assert caught.value.reason_code == code, caught.value.reason_code
    assert snapshot(system) == before, "a refusal writes nothing"


def rebooted(system):
    """The host restart: the generation's process is gone, its own receipt and launch record remain."""
    before = system["host"].receipt(system["target"])
    stop_target(system)
    identity = system["host"].identity(system["target"])
    assert identity["running"] is False and identity["instance_id"] == before["instance_id"]
    assert system["host"].receipt(system["target"]) == before
    return before


@pytest.fixture
def system(tmp_path, monkeypatch):
    built = halted(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        stop_target(built)


# ----- domain ---------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("schema", "urn:zeus:host-delivery-generation-restart:2"), ("kind", RECOVERY_CONSUMPTION_RETRY),
    ("reason", "operator_wish"), ("stopped_instance_id", ""), ("approved_by", "x y"),
    ("first_activation_evidence", "sha256:short"), ("halt", {"stage": BLOCKED})])
def test_the_document_grammar_is_exact(field, value):
    body = {"schema": GENERATION_RESTART_SCHEMA, "kind": RECOVERY_GENERATION_RESTART, "plan_id": "own-p",
            "plan_sha256": "a" * 64, "pin_sha256": "b" * 64, "target_id": "t", "release_id": "r",
            "candidate_revision": "c" * 40, "candidate_tree": "7" * 40,
            "halt": {"stage": BLOCKED, "previous_stage": AWAITING_CONSUMPTION, "reason_code": "no_known_good_predecessor",
                     "updated_at": "2026-09-22T00:00:00+00:00", "stage_deadline": "2026-09-22T00:00:00+00:00"},
            "first_activation_evidence": "sha256:" + "e" * 64, "descriptor_sha256": "d" * 64,
            "stopped_instance_id": "i" * 32, "reason": "host_restarted", "approved_by": "conductor"}
    assert validate_generation_restart(body)["reason"] == "host_restarted"
    with pytest.raises(DeliveryRefused) as caught:
        validate_generation_restart({**body, field: value})
    assert caught.value.reason_code == "generation_restart_invalid"
    with pytest.raises(DeliveryRefused):
        validate_generation_restart({**body, "extra": 1})


# ----- the reboot case ------------------------------------------------------------------------
@binds_a_runtime
def test_a_stopped_generation_refuses_the_old_retry_then_restarts_once_and_the_one_retry_consumes_it(system):
    halted_intent = intent_of(system)
    old = halted_intent["candidate_instance_id"]
    old_receipt = rebooted(system)
    # The old D1 path has nothing live to consume: a named refusal, nothing written.
    refused(system, "consumption_retry_instance_stopped")
    before = snapshot(system)
    queue_before = len(before["queue"]["manual_retries"])
    body, evidence = restart_document(system)
    receipt = restart(system, body, evidence)
    assert receipt["cached"] is False and receipt["recovery"]["kind"] == RECOVERY_GENERATION_RESTART
    intent = intent_of(system)
    # The halt, its EXPIRED deadline and every earlier recovery stay exactly as they were.
    for key in ("stage", "previous_stage", "reason_code", "outcome", "updated_at", "stage_deadline",
                "stage_entered_at", "rollback", "canary", "candidate_instance_id", "descriptor"):
        assert intent[key] == halted_intent[key], key
    assert [row["kind"] for row in intent["recoveries"]] == [RECOVERY_FIRST_ACTIVATION, RECOVERY_GENERATION_RESTART]
    record = intent["recoveries"][-1]
    new = record["started"]["instance_id"]
    assert record["state"] == "started" and new not in (None, old)
    assert record["stopped"]["instance_id"] == old and record["halted"]["stage_deadline"] == halted_intent["stage_deadline"]
    assert record["launch"]["started"] is True and record["launch"]["record"] != record["stopped"]["observed_launch"]
    # The fresh startup receipt of the SAME descriptor names the new generation; the descriptor row is unchanged.
    fresh = system["host"].receipt(system["target"])
    assert fresh["instance_id"] == new != old_receipt["instance_id"]
    assert fresh["descriptor_sha256"] == old_receipt["descriptor_sha256"] == intent["descriptor_sha256"]
    after = snapshot(system)
    assert after["descriptors"] == before["descriptors"] and after["plan"] == before["plan"]
    assert after["release"] == before["release"]
    assert len(after["queue"]["manual_retries"]) == queue_before + 1 and after["queue"]["status"] == "blocked"
    assert not generation_restartable(intent), "one restart per delivery"
    shown = system["delivery"].status()["deliveries"][0]["recoveries"][-1]
    assert shown["kind"] == RECOVERY_GENERATION_RESTART and shown["state"] == "started"
    assert shown["stopped"]["instance_id"] == old and shown["started"]["instance_id"] == new
    assert shown["halted"]["stage_deadline"] == halted_intent["stage_deadline"]
    # The ONE consumption retry is EXPLICITLY linked and consumes exactly the new generation.
    retry_body, retry_evidence = retry_document(system, observed_instance_id=new,
                                                **{CONSUMPTION_RETRY_RESTART_FIELD: evidence})
    resumed = retry(system, retry_body, retry_evidence)
    assert resumed["stage"] == AWAITING_CONSUMPTION
    intent = intent_of(system)
    assert [row["kind"] for row in intent["recoveries"]] == [
        RECOVERY_FIRST_ACTIVATION, RECOVERY_GENERATION_RESTART, RECOVERY_CONSUMPTION_RETRY]
    assert intent["candidate_instance_id"] == new, "a rollback replaces the generation this delivery started"
    assert intent["recoveries"][-1]["observed"][CONSUMPTION_RETRY_RESTART_FIELD] == evidence
    shown = system["delivery"].status()["deliveries"][0]["recoveries"][-1]
    assert shown["observed"] == {"observed_instance_id": new, "descriptor_sha256": intent["descriptor_sha256"],
                                 CONSUMPTION_RETRY_RESTART_FIELD: evidence}
    asked_before = len(system["canary"].calls)   # the original attempt asked about the old generation
    system["canary"].answer = {"passed": True, "reason_code": None, "evidence": "sha256:" + "4" * 64}
    results = drive(system, until=ACTIVE, limit=10)
    assert results[-1]["stage"] == ACTIVE, results[-1]
    row = descriptor_of(system)
    assert row["consumed"] is True and row["instance_id"] == new
    assert set(system["canary"].calls[asked_before:]) == {new}, "after the restart only the new generation is asked"
    assert system["verifier"].calls == []


@binds_a_runtime
def test_the_restart_replays_cached_and_another_evidence_conflicts(system):
    rebooted(system)
    body, evidence = restart_document(system)
    first = restart(system, body, evidence)
    launch = intent_of(system)["recoveries"][-1]["launch"]
    again = restart(system, body, evidence)
    assert again["cached"] is True and first["recovery"] == again["recovery"]
    assert intent_of(system)["recoveries"][-1]["launch"] == launch, "no second start"
    other, other_evidence = restart_document(system, approved_by="conductor", reason="generation_exited")
    with pytest.raises(DeliveryRefused) as caught:
        restart(system, other, other_evidence)
    assert caught.value.reason_code in {"resume_conflict", "generation_restart_halt_mismatch"}


@binds_a_runtime
def test_a_running_generation_is_the_retry_case_never_a_restart(system):
    restart_refused(system, "generation_restart_instance_running")


def _foreign_descriptor(host):
    real = host.identity
    host.identity = lambda target: {**real(target), "descriptor_sha256": "0" * 64}


def _unobservable(host):
    real = host.identity
    host.identity = lambda target: {**real(target), "running": None}


@binds_a_runtime
@pytest.mark.parametrize("fault,code", [(_foreign_descriptor, "generation_restart_host_descriptor_changed"),
                                        (_unobservable, "generation_restart_host_unobservable")])
def test_the_trusted_host_must_show_this_descriptor_positively_stopped(system, fault, code):
    rebooted(system)
    fault(system["host"])
    restart_refused(system, code)


@binds_a_runtime
@pytest.mark.parametrize("overrides,code", [
    ({"stopped_instance_id": OTHER_INSTANCE}, "generation_restart_instance_mismatch"),
    ({"approved_by": "worker:implementation"}, "generation_restart_approver_invalid"),
    ({"first_activation_evidence": "sha256:" + "0" * 64}, "generation_restart_first_activation_mismatch")])
def test_stale_or_foreign_claims_refuse_with_no_write(system, overrides, code):
    rebooted(system)
    body, _ = restart_document(system, **overrides)
    restart_refused(system, code, body=body, evidence="sha256:" + digest(body))


@binds_a_runtime
def test_the_old_deadline_cannot_be_rewritten(system):
    rebooted(system)
    body, _ = restart_document(system)
    body["halt"] = {**body["halt"], "stage_deadline": "2099-01-01T00:00:00+00:00"}
    restart_refused(system, "generation_restart_halt_mismatch", body=body, evidence="sha256:" + digest(body))


@binds_a_runtime
def test_the_one_retry_must_name_the_restart_and_consume_its_new_instance(system):
    rebooted(system)
    # before any restart, a retry naming one is refused
    fake_body, fake_evidence = retry_document(system, **{CONSUMPTION_RETRY_RESTART_FIELD: "sha256:" + "1" * 64})
    refused(system, "consumption_retry_restart_link_mismatch", body=fake_body, evidence=fake_evidence)
    body, evidence = restart_document(system)
    restart(system, body, evidence)
    new = intent_of(system)["recoveries"][-1]["started"]["instance_id"]
    unlinked, unlinked_evidence = retry_document(system, observed_instance_id=new)
    refused(system, "consumption_retry_restart_link_mismatch", body=unlinked, evidence=unlinked_evidence)
    wrong, wrong_evidence = retry_document(system, **{CONSUMPTION_RETRY_RESTART_FIELD: "sha256:" + "2" * 64},
                                           observed_instance_id=new)
    refused(system, "consumption_retry_restart_link_mismatch", body=wrong, evidence=wrong_evidence)
    stale, stale_evidence = retry_document(system, **{CONSUMPTION_RETRY_RESTART_FIELD: evidence})
    refused(system, "consumption_retry_instance_mismatch", body=stale, evidence=stale_evidence)


@binds_a_runtime
def test_a_lost_start_response_is_recognized_and_never_started_twice(system, monkeypatch):
    rebooted(system)
    starts = []
    real_start = system["host"].start

    def counted(*args, **kwargs):
        starts.append(1)
        return real_start(*args, **kwargs)
    system["host"].start = counted
    real_state = type(system["delivery"])._restart_state
    lost = {"once": True}

    def lose(self, plan, claim, evidence_ref, state, **fields):
        if lost["once"] and state == "launched":
            lost["once"] = False
            raise RuntimeError("response lost after the start (injected)")
        return real_state(self, plan, claim, evidence_ref, state, **fields)
    monkeypatch.setattr(type(system["delivery"]), "_restart_state", lose)
    body, evidence = restart_document(system)
    with pytest.raises(RuntimeError):
        restart(system, body, evidence)
    assert intent_of(system)["recoveries"][-1]["state"] == "requested" and starts == [1]
    resumed = restart(system, body, evidence)
    record = intent_of(system)["recoveries"][-1]
    assert resumed["cached"] is False and record["state"] == "started" and starts == [1]
    assert record["launch"]["recovered"] is True and record["launch"]["started"] is False


@binds_a_runtime
def test_a_held_fence_keeps_the_recorded_request_and_the_same_evidence_completes_it(system, monkeypatch):
    rebooted(system)
    real_claim = system["delivery"].queue.claim
    held = {"once": True}

    def claim(*args, **kwargs):
        if held["once"]:
            held["once"] = False
            return None
        return real_claim(*args, **kwargs)
    monkeypatch.setattr(system["delivery"].queue, "claim", claim)
    body, evidence = restart_document(system)
    with pytest.raises(DeliveryRefused) as caught:
        restart(system, body, evidence)
    assert caught.value.reason_code == "resume_controller_running"
    assert intent_of(system)["recoveries"][-1]["state"] == "requested"
    assert system["host"].identity(system["target"])["running"] is False, "nothing started without the fence"
    assert restart(system, body, evidence)["cached"] is False
    assert intent_of(system)["recoveries"][-1]["state"] == "started"


@binds_a_runtime
def test_one_restart_per_delivery_even_after_the_retry_halts_again(system):
    rebooted(system)
    body, evidence = restart_document(system)
    restart(system, body, evidence)
    new = intent_of(system)["recoveries"][-1]["started"]["instance_id"]
    retry_body, retry_evidence = retry_document(system, observed_instance_id=new,
                                                **{CONSUMPTION_RETRY_RESTART_FIELD: evidence})
    retry(system, retry_body, retry_evidence)
    system["clock"].advance(20)
    halt = drive(system, until=ACTIVE, limit=20)[-1]
    assert (halt["stage"], halt["reason_code"]) == (BLOCKED, "no_known_good_predecessor"), halt
    stop_target(system)
    again, again_evidence = restart_document(system)
    with pytest.raises(DeliveryRefused) as caught:
        restart(system, again, again_evidence)
    assert caught.value.reason_code in {"resume_conflict", "resume_not_applicable",
                                        "generation_restart_instance_mismatch"}


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def concurrent_store(request):
    if request.param == "memory":
        return MemoryStore()
    return request.getfixturevalue("isolated_pgstore")


@binds_a_runtime
def test_two_concurrent_restarts_start_one_generation(tmp_path, monkeypatch, concurrent_store):
    system = halted(tmp_path, monkeypatch, store=concurrent_store)
    try:
        rebooted(system)
        body, evidence = restart_document(system)
        starts = []
        real_start = system["host"].start

        def counted(*args, **kwargs):
            starts.append(1)
            return real_start(*args, **kwargs)
        system["host"].start = counted
        barrier = threading.Barrier(2)
        real_identity = system["host"].identity

        def gated(target):
            if threading.current_thread() is not threading.main_thread():
                try:
                    barrier.wait(timeout=5)
                except threading.BrokenBarrierError:
                    pass
            return real_identity(target)
        system["host"].identity = gated
        results, errors = [], []

        def run():
            try:
                results.append(restart(system, body, evidence))
            except Exception as exc:  # recorded for the assertion below
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert starts == [1], "exactly one start"
        assert len(results) >= 1 and all(getattr(e, "reason_code", None) in {
            "resume_controller_running", "resume_intent_changed", "generation_restart_instance_running"}
            for e in errors), errors
        restarts = [row for row in intent_of(system)["recoveries"] if row["kind"] == RECOVERY_GENERATION_RESTART]
        assert len(restarts) == 1 and restarts[0]["state"] == "started"
    finally:
        stop_target(system)


def test_the_resume_command_routes_a_restart_document_to_the_generation_restart(tmp_path, monkeypatch):
    """`host-delivery resume --document FILE` routes a restart document to `resume_generation_restart`."""
    import json
    from types import SimpleNamespace

    from codex_harness import cli
    from codex_harness.adapters import host_delivery
    from codex_harness.bootstrap import organization

    body = {"kind": RECOVERY_GENERATION_RESTART}
    path = tmp_path / "restart.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    argv = ["host-delivery", "resume", "--lane", "harness", "--plan", "own-plan", "--plan-sha256", "c" * 64,
            "--evidence", "sha256:" + "e" * 64, "--document", str(path)]
    calls = []

    class Controller:
        def resume_generation_restart(self, *arguments):
            calls.append(("generation_restart", arguments))
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
    assert calls == [("generation_restart", ("own-plan", "c" * 64, body, "sha256:" + "e" * 64))]
