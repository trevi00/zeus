"""INV-HOST-DELIVERY-MAINTENANCE-001: an open (or failed) maintenance generation holds its target.

Selection, `_act` (before the gate and the queue), `_advance`, `_prepare_switch`, registration, migration
staging, the first-activation/retry recoveries and the predecessor rule all respect the logical target
hold; an unrelated target keeps moving; legacy deliveries never gain a `generations` key. The old-code
hazard is proven (with the guards patched out, a refused gate or a missing queue row MUTATES the armed
intent), which is why the PR-3 controller must be deployed before any maintenance (a deployment
precondition, not a runtime probe). LABELLED fakes only; see `host_delivery_maintenance_fixtures`."""
from __future__ import annotations

from pathlib import Path

import pytest
from host_delivery_maintenance_fixtures import (
    TARGET,
    active_system,
    armed,
    generation_of,
    intent_of,
    put,
    read,
    restarted,
    row_of,
    snapshot,
)
from test_host_delivery import (
    SerialStore,
    binds_a_runtime,
    build,
    drive,
    pin,
    plan_document,
    reviewed_release,
    stop_target,
    successor_candidate,
)
from test_host_delivery_migration import rejected_merged

import codex_harness.application.host_delivery as application
from codex_harness.application.host_delivery import BUCKET_INTENTS, BUCKET_PLANS, HostDelivery
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    BLOCKED,
    PUBLISHING,
    REGISTERED,
    REGISTRY_SCHEMA,
    DeliveryRefused,
    new_intent,
)

ROOT = Path(__file__).resolve().parents[1]


class Raising:
    def __init__(self, *args, **kwargs):
        raise AssertionError("an executor transport was reached from a delivery path")


@pytest.fixture(autouse=True)
def no_executor_transports(monkeypatch):
    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Raising)
    monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", Raising)


def second_plan_on(system, *, plan_id="second-plan", target_id=TARGET, revision="5" * 40):
    release = reviewed_release(system["store"], system["org"], record_candidate={
        **successor_candidate({"github": system["delivery"].github}), "revision": revision,
        "branch": "harness/" + plan_id, "task_id": plan_id})
    expected = row_of(system)["descriptor_sha256"] if target_id == TARGET else None
    return plan_document(release, plan_id=plan_id, target_id=target_id, expected=expected,
                         image="zeus-worker@sha256:" + "d" * 64, profile="e" * 64, descriptor_revision="3" * 40)


def other_target(tmp_path):
    return {"schema": REGISTRY_SCHEMA, "targets": [{"target_id": "unrelated-host", "kind": "process",
                                                     "root": str(tmp_path / "unrelated-root"),
                                                     "state_dir": str(tmp_path / "unrelated-state"),
                                                     "service": "zeus-unrelated"}]}


def test_open_maintenance_holds_selection_registration_staging_and_resume_on_the_target(tmp_path):
    system = active_system(tmp_path / "held")
    delivery = system["delivery"]
    waiting = second_plan_on(system)
    delivery.register(waiting, pin(path="docs/zeus/operations/second.json"))
    delivery.register_targets(other_target(tmp_path))
    unrelated = second_plan_on(system, plan_id="unrelated-plan", target_id="unrelated-host", revision="6" * 40)
    delivery.register(unrelated, pin(path="docs/zeus/operations/unrelated.json"))
    restarted(system)
    # Selection: every plan of the held target waits; the unrelated target progresses.
    result = delivery.tick()
    assert result["blocked"]["second-plan"] == "maintenance_target_busy"
    assert result["blocked"][system["plan_id"]] == "maintenance_target_busy"
    assert result["plan_id"] == "unrelated-plan" and read(system["store"], BUCKET_INTENTS, "unrelated-plan")[
        "stage"] == PUBLISHING
    assert read(system["store"], BUCKET_INTENTS, "second-plan") is None
    focused = delivery.tick("second-plan")
    assert focused["blocked"].get("second-plan") == "maintenance_target_busy" and focused["plan_id"] is None
    # `_act`, `_advance` and `_prepare_switch` hold as well, whatever reaches them.
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_PLANS, "second-plan")
    state = snapshot(system["store"], system["control"])
    acted = delivery._act({"plan": row, "intent": None, "blocked": {}})
    assert (acted["outcome"], acted["reason_code"]) == ("controller_busy", "maintenance_target_busy")
    intent = {**new_intent(row["plan"], row["plan_sha256"], system["clock"]()), "stage": "merged"}
    assert delivery._advance(row, intent, None)["reason_code"] == "maintenance_target_busy"
    assert delivery._prepare_switch(row["plan"], intent, None)["reason_code"] == "maintenance_target_busy"
    assert snapshot(system["store"], system["control"]) == state
    # Registration of any other plan on the held target is refused; the identical replay stays cached.
    third = second_plan_on(system, plan_id="third-plan", revision="7" * 40)
    state = snapshot(system["store"], system["control"])      # the third plan's reviewed release now exists
    with pytest.raises(DeliveryRefused) as refused:
        delivery.register(third, pin(path="docs/zeus/operations/third.json"))
    assert (refused.value.reason_code, refused.value.field) == ("maintenance_target_busy", "target_id")
    assert delivery.register(waiting, pin(path="docs/zeus/operations/second.json"))["cached"] is True
    # The first-activation and retry recoveries, and the predecessor rule, see the hold too.
    with system["store"].transaction() as tx:
        others = tx.scan(BUCKET_INTENTS)
    for guard in (delivery._first_activation_host, delivery._retry_host):
        with pytest.raises(DeliveryRefused) as refused:
            guard(row["plan"], None, {}, others, {})
        assert refused.value.reason_code == "maintenance_target_busy"
    assert delivery._predecessor(row["plan"]) == "in_flight"
    assert snapshot(system["store"], system["control"]) == state


def test_a_failed_maintenance_keeps_holding_and_a_bound_one_releases(tmp_path):
    system = active_system(tmp_path)
    restarted(system)
    assert generation_of(system)["state"] == "started"
    # `failed` and `bound` are contract states the arm/bind phases (PR-3's remainder) reach; this release
    # cannot, so each is a LABELLED injected generation state here.
    intent = intent_of(system)
    put(system["store"], BUCKET_INTENTS, system["plan_id"], {
        **intent, "generations": [{**intent["generations"][-1], "state": "failed"}]})
    waiting = second_plan_on(system)
    with pytest.raises(DeliveryRefused) as refused:
        system["delivery"].register(waiting, pin(path="docs/zeus/operations/second.json"))
    assert refused.value.reason_code == "maintenance_target_busy"
    # Bound: the logical hold ends and ordinary registration is possible again.
    intent = intent_of(system)
    put(system["store"], BUCKET_INTENTS, system["plan_id"], {
        **intent, "generations": [{**intent["generations"][-1], "state": "bound"}]})
    assert system["delivery"].register(waiting, pin(path="docs/zeus/operations/second.json"))["registered"] is True


def test_migration_staging_refuses_a_held_target(tmp_path):
    system = rejected_merged(tmp_path, SerialStore())
    target_id = system["plan"]["target_id"]
    with system["store"].transaction() as tx:
        tx.put(BUCKET_INTENTS, "maintained", {"id": "maintained", "plan_id": "maintained", "target_id": target_id,
                                              "stage": ACTIVE, "generations": [{"id": "g", "state": "armed"}]})
    with pytest.raises(DeliveryRefused) as refused:
        system["delivery"].stage_migration(system["request"])
    assert (refused.value.reason_code, refused.value.field) == ("maintenance_target_busy", "target_id")
    with system["store"].transaction() as tx:
        assert tx.scan(application.BUCKET_MIGRATIONS) == []
        assert tx.get(BUCKET_INTENTS, system["plan"]["plan_id"]) == system["halted"]


@pytest.mark.parametrize("trigger", ["missing queue row", "refused gate"])
def test_old_controller_hazard_is_real_and_the_new_controller_holds(tmp_path, monkeypatch, trigger):
    """The restart leaves the generation open (`started`) on an ACTIVE intent. A PR-3 controller holds the target
    whatever else changed; an old controller (the maintenance guards removed) accepts a competing plan on it, which
    would switch the target under an open maintenance: that is the deployment precondition."""
    system = active_system(tmp_path)
    restarted(system)
    release_id = system["release"]["id"]
    if trigger == "missing queue row":
        system["store"].data.pop(("release_queue", release_id))
    else:
        record = read(system["store"], "releases", release_id)
        put(system["store"], "releases", release_id, {**record, "candidate": {**record["candidate"],
                                                                                "tree": "0" * 64}})
    # PR-3 controller: the tick selects nothing on the held target and writes nothing at all.
    state = snapshot(system["store"], system["control"])
    tick = system["delivery"].tick()
    assert tick["blocked"][system["plan_id"]] == "maintenance_target_busy"
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_PLANS, system["plan_id"])
    acted = system["delivery"]._act({"plan": row, "intent": intent_of(system), "blocked": {}})
    assert (acted["outcome"], acted["reason_code"]) == ("controller_busy", "maintenance_target_busy")
    assert snapshot(system["store"], system["control"]) == state
    waiting = second_plan_on(system)
    with pytest.raises(DeliveryRefused) as refused:
        system["delivery"].register(waiting, pin(path="docs/zeus/operations/second.json"))
    assert refused.value.reason_code == "maintenance_target_busy"
    # "Old code": the same controller with the maintenance guards removed registers the competing plan.
    monkeypatch.setattr(HostDelivery, "_maintenance_held", lambda self, target_id: False)
    monkeypatch.setattr(application, "maintenance_open", lambda intent: False)
    monkeypatch.setattr(application, "maintenance_hold", lambda *args, **kwargs: None)
    assert system["delivery"].register(waiting, pin(path="docs/zeus/operations/second.json"))["registered"] is True


def test_a_failed_maintenance_after_an_arm_failure_keeps_holding_and_a_bound_one_releases(tmp_path):
    system = active_system(tmp_path)
    document, evidence, _ = restarted(system)
    system["host"].n1(system["target"])
    with pytest.raises(DeliveryRefused):
        system["delivery"].maintain(document, evidence, "arm")
    assert generation_of(system)["state"] == "failed"
    waiting = second_plan_on(system)
    with pytest.raises(DeliveryRefused) as refused:
        system["delivery"].register(waiting, pin(path="docs/zeus/operations/second.json"))
    assert refused.value.reason_code == "maintenance_target_busy"
    # Bound: the logical hold ends and ordinary registration is possible again.
    intent = intent_of(system)
    put(system["store"], BUCKET_INTENTS, system["plan_id"], {
        **intent, "generations": [{**intent["generations"][-1], "state": "bound"}]})
    assert system["delivery"].register(waiting, pin(path="docs/zeus/operations/second.json"))["registered"] is True


def hazard_inputs(system):
    """An ARMED maintained intent (stage `awaiting_consumption`, the new candidate) with two old-code
    triggers available: its queue row missing, or its release gate refused."""
    armed(system)
    assert intent_of(system)["stage"] == AWAITING_CONSUMPTION
    return intent_of(system)


@pytest.mark.parametrize("trigger", ["missing queue row", "refused gate"])
def test_old_controller_hazard_on_an_armed_intent_is_real_and_the_new_controller_holds(tmp_path, monkeypatch, trigger):
    system = active_system(tmp_path)
    before = hazard_inputs(system)
    release_id = system["release"]["id"]
    if trigger == "missing queue row":
        system["store"].data.pop(("release_queue", release_id))
    else:
        record = read(system["store"], "releases", release_id)
        put(system["store"], "releases", release_id, {**record, "candidate": {**record["candidate"],
                                                                                "tree": "0" * 64}})
    # PR-3 controller: the tick selects nothing on the held target and writes nothing at all.
    state = snapshot(system["store"], system["control"])
    tick = system["delivery"].tick()
    assert tick["blocked"][system["plan_id"]] == "maintenance_target_busy"
    with system["store"].transaction() as tx:
        row = tx.get(BUCKET_PLANS, system["plan_id"])
    acted = system["delivery"]._act({"plan": row, "intent": before, "blocked": {}})
    assert (acted["outcome"], acted["reason_code"]) == ("controller_busy", "maintenance_target_busy")
    assert snapshot(system["store"], system["control"]) == state
    # "Old code": the same controller with the maintenance guards removed MUTATES the armed intent on a
    # refused gate or a missing queue row. That is the deployment hazard.
    monkeypatch.setattr(HostDelivery, "_maintenance_held", lambda self, target_id: False)
    monkeypatch.setattr(application, "maintenance_open", lambda intent: False)
    old = system["delivery"].tick()
    mutated = intent_of(system)
    assert old["plan_id"] == system["plan_id"] and mutated != before
    assert mutated["stage"] == BLOCKED and mutated["reason_code"] in {"queue_refused", "release_tree_mismatch"}


def test_the_deployment_precondition_is_the_documented_requirement():
    contracts = (ROOT / "docs" / "contracts.md").read_text(encoding="utf-8")
    section = contracts.split("## INV-HOST-DELIVERY-MAINTENANCE-001", 1)[1].split("\n## ", 1)[0]
    assert "DEPLOYMENT PRECONDITION" in section and "mixed" in section.lower()


def test_legacy_managed_paths_add_no_generations_key(tmp_path):
    system = active_system(tmp_path)
    with system["store"].transaction() as tx:
        intents = tx.scan(BUCKET_INTENTS)
    assert intents and all("generations" not in intent for intent in intents)
    status = system["delivery"].status()
    assert all("maintenance" not in view for view in status["deliveries"])
    assert all(row_of(system).get(key) is not None for key in ("descriptor_sha256", "instance_id"))
    for _ in range(3):
        assert system["delivery"].tick()["blocked"][system["plan_id"]] == ACTIVE
    assert all("generations" not in intent for intent in [intent_of(system)])
    assert intent_of(system)["stage"] != REGISTERED


@binds_a_runtime
def test_legacy_delivery_recovery_queue_paths_add_no_generations_key(tmp_path):
    system = build(tmp_path)
    try:
        results = drive(system)
        assert results[-1]["stage"] == ACTIVE
        with system["store"].transaction() as tx:
            intents = tx.scan(BUCKET_INTENTS)
            queued = tx.get("release_queue", system["release"]["id"])
        assert all("generations" not in intent for intent in intents)
        assert queued["status"] == "active" and "maintenance_id" not in str(queued)
        assert all("maintenance" not in view for view in system["delivery"].status()["deliveries"])
    finally:
        stop_target(system)
