"""Ported SOURCE main b9d8f15 (S2R) suite `tests/test_host_delivery_maintenance.py` run against the target (batch a).

Every assertion is S2R's, unchanged. Adaptations are import lines and patch targets only: the delivery, fleet and
evidence names come from their target homes (`delivery.domain.maintenance`, `delivery.domain.host_migration_evidence`,
`delivery.application.host_delivery.state`, `coordination.application.fleet.state`, `kernel.ids`), the real
`HostDelivery` and Fleet are the `m7_delivery` / `m7_coordination` shims (see `host_delivery_maintenance_fixtures`), and the
executor transports patched to raise are `m7_executor.AppServer` / `.ClaudeCodeRuntime`, the adapted form of
`codex_harness.adapters.executor.*`.

S2R docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001: restart, arm and bind of an ACTIVE, consumed managed delivery.

Real: `HostDelivery`, `Releases`, `ReleaseQueue` (maintenance hold), the owner canary check and receipt
files, the HME PR-2 predicates and (one test) the unchanged `OwnerActions`. LABELLED fakes only for the host
(`FakeManagedHost`), the Fleet maintenance seam, the one-job executor, the credential helper, the authority
and artifact stores (see `host_delivery_maintenance_fixtures`). Both executor transports are stubbed to
raise, although no maintenance path builds an executor. No model, provider, network, systemd unit, secret
or production store is touched."""
from __future__ import annotations

import copy
import json

import pytest
from host_delivery_maintenance_fixtures import (
    AUTHORITY_REF,
    BUCKET_ACTIONS,
    BUCKET_JOBS,
    SENTINEL,
    TARGET,
    CountingQueue,
    Crash,
    active_system,
    authority_store,
    document_for,
    generation_of,
    hold_activation,
    hold_unit,
    intent_of,
    plan_row_of,
    put,
    read,
    restarted,
    row_of,
    snapshot,
    steal_lease,
)

from codex_harness.coordination.application.fleet.state import BUCKET_CONTROL, CONTROL_KEY
from codex_harness.delivery.adapters.host_delivery import (
    canary_receipt_file,
    owner_qualified_canary,
)
from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_TARGETS,
)
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    BLOCKED,
    KIND_MANAGED,
    SWITCHING,
    DeliveryRefused,
)
from codex_harness.delivery.domain.host_migration import MigrationRefused
from codex_harness.delivery.domain.host_migration_evidence import (
    delivery_view,
    require_canary,
    require_consumption,
)
from codex_harness.delivery.domain.maintenance import MAINTENANCE_RESULT_SCHEMA
from codex_harness.kernel.ids import digest

RESULT_KEYS = {"schema", "maintenance_id", "phase", "check", "applicable", "state", "cached", "pending",
               "reason_code", "field", "identities", "deadline", "evidence", "authority"}
BINDING = ("stage", "outcome", "instance_id", "canary", "descriptor", "descriptor_sha256", "previous_descriptor",
           "previous_instance_id", "candidate_instance_id", "stage_deadline", "updated_at", "rollback")


class Raising:
    """LABELLED transport stub: any executor construction is a test failure, never a real call."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("an executor transport was reached from a maintenance path")


@pytest.fixture(autouse=True)
def no_executor_transports(monkeypatch):
    monkeypatch.setattr("m7_executor.AppServer", Raising)
    monkeypatch.setattr("m7_executor.ClaudeCodeRuntime", Raising)


def refused(call):
    with pytest.raises(DeliveryRefused) as caught:
        call()
    return caught.value.reason_code, caught.value.field


def maintain(system, document, evidence, phase, **kwargs):
    if phase == "restart":
        kwargs = {"startup_seconds": 0, "poll_seconds": 0, **kwargs}
    return system["delivery"].maintain(document, evidence, phase, **kwargs)


def lane_rows(system):
    with system["store"].transaction() as tx:
        return {"release": copy.deepcopy(tx.get("releases", system["release"]["id"])),
                "pointer": copy.deepcopy(tx.get("deployment", "active")),
                "queue": copy.deepcopy(tx.get("release_queue", system["release"]["id"]))}


def lock(system):
    return read(system["store"], "deployment_locks", "controller") or {}


def effects(system):
    """Host effects and artifact puts; the Fleet (read only by the restart phase) is covered by the control-store
    snapshots the tests compare."""
    return {"calls": list(system["host"].calls), "puts": system["artifacts"].puts}


# ----- restart ------------------------------------------------------------------------------------------------
def test_restart_records_requested_before_the_one_guarded_start(tmp_path):
    system = active_system(tmp_path)
    document, evidence = document_for(system)
    before, rows, calls = intent_of(system), lane_rows(system), len(system["host"].calls)
    descriptor_row = row_of(system)
    seen = []

    def on_start():
        # Opened here on purpose: no store transaction is open across the host effect.
        intent = intent_of(system)
        generation = intent["generations"][-1]
        seen.append((generation["state"], generation["prior"]["intent_sha256"],
                     {key: intent.get(key) for key in BINDING}, lock(system).get("maintenance_id")))

    system["host"].on_start = on_start
    result = maintain(system, document, evidence, "restart")
    assert set(result) == RESULT_KEYS and result["schema"] == MAINTENANCE_RESULT_SCHEMA
    assert (result["state"], result["cached"], result["pending"], result["applicable"]) == ("started", False, False,
                                                                                           True)
    assert seen == [("requested", digest(before), {key: before.get(key) for key in BINDING}, result["maintenance_id"])]
    new_calls = system["host"].calls[calls:]
    assert [call[0] for call in new_calls] == ["gate", "stop", "gate", "retire", "launch"]
    assert not any("signal" in call[0] or "kill" in call[0] for call in system["host"].calls)
    after = intent_of(system)
    # The current binding is untouched while the new generation only STARTED; nothing is consumed.
    assert {key: value for key, value in after.items() if key != "generations"} == before
    assert row_of(system) == descriptor_row and lane_rows(system) == rows
    generation = after["generations"][-1]
    assert generation["id"] == result["maintenance_id"] and generation["state"] == "started"
    assert generation["retiring"]["instance_id"] == before["instance_id"]
    assert generation["launched"]["receipt"]["instance_id"] not in (None, before["instance_id"])
    assert generation["launched"]["path"] == "replace" and generation["launched"]["request_sha256"] == digest(document)
    assert generation["prior"]["descriptor_row"]["history_count"] == len(descriptor_row.get("history") or [])
    assert set(generation["prior"]["evidence_refs"]) == {"startup_receipt", "owner_canary_receipt",
                                                        "owner_canary_action", "launch_record"}
    assert system["artifacts"].puts == 4 and result["evidence"]["prior"] == generation["prior"]["evidence_refs"]
    assert result["identities"]["new_instance_id"] == generation["launched"]["receipt"]["instance_id"]
    view = system["delivery"].status(system["plan_id"])["deliveries"][0]
    assert view["stage"] == ACTIVE and view["maintenance"]["open"] is True and view["maintenance"]["qualified"] is False
    assert lock(system).get("owner") is None
    assert read(system["control"], BUCKET_ACTIONS, system["old_action"]["id"]) == system["old_action"]


def mutate_intent(system, **fields):
    intent = intent_of(system)
    put(system["store"], BUCKET_INTENTS, system["plan_id"], {**intent, **fields})


def other_intent(system, **fields):
    put(system["store"], BUCKET_INTENTS, "other-plan", {"id": "other-plan", "plan_id": "other-plan",
                                                         "target_id": TARGET, "stage": "registered", **fields})


def unpause(system) -> None:
    """LABELLED injected fact: the Fleet control row not paused (the product's `admission` row shape)."""
    with system["control"].transaction() as tx:
        control = tx.get(BUCKET_CONTROL, CONTROL_KEY)
        tx.put(BUCKET_CONTROL, CONTROL_KEY, {**control, "paused": False})


APPLICABILITY = {
    "blocked first activation": (lambda s: mutate_intent(s, stage=BLOCKED), {},
                                 ("maintenance_not_active", "stage")),
    "canary not passed": (lambda s: mutate_intent(s, canary={"passed": False}), {},
                          ("maintenance_not_active", "canary")),
    "N1 via the document": (None, {"retiring": "other-instance"}, ("maintenance_invocation_mismatch", "instance_id")),
    "N1 on the host": (lambda s: s["host"].n1(s["target"]), {}, ("maintenance_invocation_mismatch", "invocation_id")),
    "foreign target": (None, {"target_id": "another-host"}, ("maintenance_stale", "target_id")),
    "foreign pin": (None, {"pin_sha256": "0" * 64}, ("maintenance_stale", "pin_sha256")),
    "foreign plan": (None, {"plan_sha256": "0" * 64}, ("maintenance_stale", "plan_sha256")),
    "foreign descriptor": (None, {"descriptor_sha256": "0" * 64}, ("maintenance_stale", "descriptor_sha256")),
    "from drift": (None, {"from": {"stage": "active", "updated_at": "2026-09-22T00:00:00+00:00"}},
                   ("maintenance_stale", "from")),
    "not a systemd target": (lambda s: put(s["store"], BUCKET_TARGETS, TARGET, {
        **read(s["store"], BUCKET_TARGETS, TARGET), "kind": KIND_MANAGED}), {}, ("maintenance_not_active", "target_id")),
    "descriptor row not consumed": (lambda s: put(s["store"], "host_delivery_descriptors", TARGET, {
        **row_of(s), "consumed": False}), {}, ("maintenance_not_active", "descriptor_row")),
    "release not active": (lambda s: put(s["store"], "releases", s["release"]["id"], {
        **read(s["store"], "releases", s["release"]["id"]), "status": "verified"}), {},
                           ("maintenance_not_active", "release_id")),
    "foreign pointer": (lambda s: put(s["store"], "deployment", "active", {"id": "active", "release_id": "other"}),
                        {}, ("maintenance_not_active", "pointer")),
    "queue row missing": (lambda s: s["store"].data.pop(("release_queue", s["release"]["id"])), {},
                          ("maintenance_not_active", "queue")),
    "competing intent": (lambda s: other_intent(s, stage=SWITCHING), {}, ("maintenance_target_busy", "target_id")),
    "held successor": (lambda s: other_intent(s, stage="verifying", held="migration_unacknowledged"), {},
                       ("maintenance_target_busy", "target_id")),
    "reserving migration": (lambda s: put(s["store"], BUCKET_MIGRATIONS, "m", {
        "id": "m", "target_id": TARGET, "state": "staged"}), {}, ("maintenance_target_busy", "target_id")),
    "controller lease": (lambda s: steal_lease(s), {}, ("maintenance_controller_busy", "controller")),
    "fleet not owner-paused": (lambda s: unpause(s), {}, ("maintenance_pause_required", "fleet")),
    "activation hold": (lambda s: hold_activation(s), {}, ("maintenance_pause_required", "fleet")),
    "reserving job": (lambda s: put(s["control"], BUCKET_JOBS, "job-x", {"id": "job-x", "status": "dispatching"}),
                      {}, ("maintenance_debt_unsettled", "fleet")),
    "held unit": (lambda s: hold_unit(s), {}, ("maintenance_debt_unsettled", "fleet")),
    "old canary action missing": (lambda s: s["control"].data.pop((BUCKET_ACTIONS, s["old_action"]["id"])), {},
                                  ("maintenance_not_active", "canary")),
    "old owner receipt missing": (lambda s: s["host"].path(s["target"], canary_receipt_file(s["plan_id"])).unlink(),
                                  {}, ("maintenance_not_active", "canary")),
}


@pytest.mark.parametrize("case", sorted(APPLICABILITY))
def test_applicability_refusals_write_nothing_before_any_effect(tmp_path, case):
    system = active_system(tmp_path)
    mutation, overrides, expected = APPLICABILITY[case]
    if overrides.get("retiring") == "other-instance":
        document, _ = document_for(system)
        overrides = {"retiring": {**document["retiring"], "instance_id": "9" * 32}}
    document, evidence = document_for(system, **overrides)
    if mutation is not None:
        mutation(system)
    before, done = snapshot(system["store"], system["control"]), effects(system)
    assert refused(lambda: maintain(system, document, evidence, "restart")) == expected
    assert snapshot(system["store"], system["control"]) == before and effects(system) == done
    checked = maintain(system, document, evidence, "restart", check=True)
    assert (checked["applicable"], checked["reason_code"], checked["field"]) == (False, *expected)
    assert snapshot(system["store"], system["control"]) == before and effects(system) == done


HOST_DRIFT = {
    "invocation": ({"invocation_id": "9" * 32}, None, ("maintenance_invocation_mismatch", "invocation_id")),
    "launch digest": ({"launch_sha256": "9" * 64}, None, ("maintenance_launch_unconfirmed", "launch")),
    "reload pending": ({}, lambda h: h.reload_pending(), ("maintenance_reload_pending", "unit")),
    "reload unknown": ({}, lambda h: h.reload_pending(None), ("maintenance_reload_pending", "unit")),
    "pid reuse": ({}, lambda h: h.pid_reuse(), ("maintenance_invocation_mismatch", "entry")),
    "not running": ({}, lambda h: (setattr(h, "alive", False), setattr(h, "active_state", "inactive")),
                    ("maintenance_invocation_mismatch", "running")),
    "stopped under an active unit": ({}, lambda h: setattr(h, "alive", False),
                                     ("maintenance_invocation_mismatch", "instance_id")),
    "liveness unknown": ({}, lambda h: setattr(h, "running_unknown", True),
                         ("maintenance_launch_unconfirmed", "running")),
    "work busy": ({}, lambda h: h.work_busy(), ("maintenance_debt_unsettled", "work")),
    "target file": ({}, lambda h: h.target_file_changed(), ("maintenance_stale", "target_file")),
    "service user": ({}, lambda h: setattr(h, "control_user", False), ("maintenance_invalid", "service_user")),
    "unobservable": ({}, lambda h: setattr(h, "observe_error", RuntimeError(SENTINEL)),
                     ("maintenance_invocation_mismatch", "observation")),
}


@pytest.mark.parametrize("case", sorted(HOST_DRIFT))
def test_host_identity_drift_refuses_before_stop(tmp_path, case):
    system = active_system(tmp_path)
    retiring, mutation, expected = HOST_DRIFT[case]
    document, _ = document_for(system)
    document, evidence = document_for(system, retiring={**document["retiring"], **retiring})
    if mutation is not None:
        mutation(system["host"])
    before, done = snapshot(system["store"], system["control"]), effects(system)
    assert refused(lambda: maintain(system, document, evidence, "restart")) == expected
    assert snapshot(system["store"], system["control"]) == before and effects(system) == done
    assert ("stop",) not in system["host"].calls


def test_document_authority_and_approver_refusals(tmp_path):
    system = active_system(tmp_path)
    delivery = system["delivery"]
    document, evidence = document_for(system)
    before = snapshot(system["store"], system["control"])
    assert refused(lambda: maintain(system, document, "sha256:" + "0" * 64, "restart")) == (
        "maintenance_invalid", "evidence")
    assert refused(lambda: maintain(system, document, "not-a-ref", "restart")) == ("maintenance_invalid", "evidence")
    forged, forged_evidence = document_for(system, authority="sha256:" + "0" * 64)
    assert refused(lambda: maintain(system, forged, forged_evidence, "restart")) == (
        "maintenance_authority_unverified", "authority")
    delivery.authorities = authority_store({AUTHORITY_REF: b"other bytes under the same reference"})
    assert refused(lambda: maintain(system, document, evidence, "restart")) == (
        "maintenance_authority_unverified", "authority")
    delivery.authorities = authority_store({AUTHORITY_REF: "not bytes"})
    assert refused(lambda: maintain(system, document, evidence, "restart"))[0] == "maintenance_authority_unverified"
    delivery.authorities = None
    assert refused(lambda: maintain(system, document, evidence, "restart"))[0] == "maintenance_authority_unverified"
    delivery.authorities = system["authorities"]
    for approver in ("lead:improvement", "nobody", "worker:implementation"):
        other, other_evidence = document_for(system, approved_by=approver)
        assert refused(lambda: maintain(system, other, other_evidence, "restart")) == (
            "maintenance_authority_unverified", "approved_by")
    record = read(system["store"], "releases", system["release"]["id"])
    put(system["store"], "releases", system["release"]["id"],
        {**record, "candidate": {**record["candidate"], "author": "conductor"}})
    assert refused(lambda: maintain(system, document, evidence, "restart")) == (
        "maintenance_authority_unverified", "approved_by")
    put(system["store"], "releases", system["release"]["id"], record)
    assert snapshot(system["store"], system["control"]) == before and system["artifacts"].puts == 0
    # One generation per delivery: the same retiring generation under other bytes conflicts; any other
    # document is a new attempt that is already used.
    document, evidence, _ = restarted(system)
    changed, changed_evidence = document_for(system, canary_window_seconds=601,
                                             retiring=document["retiring"], **{"from": document["from"]})
    state = snapshot(system["store"], system["control"])
    assert refused(lambda: maintain(system, changed, changed_evidence, "restart")) == (
        "maintenance_conflict", "document")
    fresh, fresh_evidence = document_for(system)
    assert refused(lambda: maintain(system, fresh, fresh_evidence, "restart")) == (
        "maintenance_already_used", "document")
    assert snapshot(system["store"], system["control"]) == state


def crash_before_stop(system):
    def crash():
        system["host"].on_start = None
        raise Crash("controller died before the stop (labelled injected fault)")
    system["host"].on_start = crash


LOSSES = {
    "before stop": (crash_before_stop, Crash, "requested"),
    "after stop": (lambda s: setattr(s["host"], "crash_after_stop", True), Crash, "requested"),
    "after launch before the record": (lambda s: setattr(s["host"], "raise_after_launch", 1),
                                       ("maintenance_reconciliation_required", "effect"), "requested"),
    "after the launch record, before the receipt": (lambda s: setattr(s["host"], "receipt_delay", 10 ** 6),
                                                    ("maintenance_launch_unconfirmed", "receipt"), "launched"),
    "after the durable result": (lambda s: None, None, "started"),
}


@pytest.mark.parametrize("case", sorted(LOSSES))
def test_response_loss_reconciles_with_at_most_one_launch(tmp_path, case):
    system = active_system(tmp_path)
    host = system["host"]
    inject, first, state = LOSSES[case]
    document, evidence = document_for(system)
    launches = host.launches
    inject(system)
    if first is Crash:
        with pytest.raises(Crash):
            maintain(system, document, evidence, "restart")
    elif first is not None:
        assert refused(lambda: maintain(system, document, evidence, "restart")) == first
    else:
        maintain(system, document, evidence, "restart")
    assert generation_of(system)["state"] == state
    assert lock(system).get("owner") is None
    if state == "launched":
        # An unproven launch HOLDS: launched, never adopted as started, never launched again.
        assert host.launches == launches + 1
        assert generation_of(system)["observations"][-1]["reason_code"] == "maintenance_launch_unconfirmed"
        host.receipt_delay = 0
    # The same document reconciles only its own effect.
    result = maintain(system, document, evidence, "restart")
    assert result["state"] == "started" and host.launches == launches + 1
    again = maintain(system, document, evidence, "restart")
    assert again["cached"] is True and host.launches == launches + 1
    assert intent_of(system)["stage"] == ACTIVE


def test_n1_after_the_request_is_an_observation_never_adopted(tmp_path):
    system = active_system(tmp_path)
    host = system["host"]
    document, evidence = document_for(system)
    crash_before_stop(system)
    with pytest.raises(Crash):
        maintain(system, document, evidence, "restart")
    launches = host.launches
    host.n1(system["target"])        # the unit restarted by itself after the request was recorded
    assert refused(lambda: maintain(system, document, evidence, "restart")) == (
        "maintenance_invocation_mismatch", "invocation_id")
    generation = generation_of(system)
    assert generation["state"] == "requested" and host.launches == launches and ("stop",) not in host.calls
    assert generation["observations"][-1] == {"phase": "restart", "state": "requested",
                                              "reason_code": "maintenance_invocation_mismatch",
                                              "field": "invocation_id", "at": generation["observations"][-1]["at"]}


def test_ownership_lost_after_the_stop_needs_reconciliation(tmp_path):
    system = active_system(tmp_path)
    document, evidence = document_for(system)
    system["host"].after_stop = lambda: steal_lease(system)
    assert refused(lambda: maintain(system, document, evidence, "restart")) == (
        "maintenance_reconciliation_required", "effect")
    # Nothing was launched after the lost fence, the successor's lease is intact, and the stale
    # controller recorded nothing over it.
    assert system["host"].calls[-1] == ("stop",) and lock(system)["owner"] == "labelled-successor-controller"
    assert generation_of(system)["state"] == "requested"
    assert generation_of(system)["observations"][-1]["reason_code"] is None


def test_restart_replay_after_started_is_cached(tmp_path):
    system = active_system(tmp_path)
    document, evidence, first = restarted(system)
    before, done = snapshot(system["store"], system["control"]), effects(system)
    for check in (False, True):
        again = maintain(system, document, evidence, "restart", check=check)
        assert (again["state"], again["cached"], again["applicable"]) == ("started", True, True)
        assert again["maintenance_id"] == first["maintenance_id"]
    assert snapshot(system["store"], system["control"]) == before and effects(system) == done


# ----- check mode ---------------------------------------------------------------------------------------------
def test_check_mode_has_zero_effects_across_phases(tmp_path):
    system = active_system(tmp_path)
    queue = CountingQueue(system["delivery"].queue)
    system["delivery"].queue = queue
    # Planted sentinels in host sources that a result must never relay.
    system["host"].work = {**system["host"].work, "reason_code": "SENTINEL-must-never-leak"}
    document, evidence = document_for(system)

    def checked(phase):
        before, done, holds = snapshot(system["store"], system["control"]), effects(system), queue.holds
        result = maintain(system, document, evidence, phase, check=True)
        assert snapshot(system["store"], system["control"]) == before and effects(system) == done
        assert queue.holds == holds and set(result) == RESULT_KEYS and SENTINEL not in json.dumps(result)
        assert str(tmp_path) not in json.dumps(result)          # no host path is ever relayed
        return result

    assert checked("restart")["applicable"] is True
    maintain(system, document, evidence, "restart")
    assert checked("restart")["cached"] is True
    # This release carries the restart phase only (ALL-PRIMARY-20260930): arm and bind refuse by name.
    for phase in ("arm", "bind"):
        refused = checked(phase)
        assert (refused["applicable"], refused["reason_code"], refused["field"]) == (
            False, "maintenance_phase", "phase")
    assert generation_of(system)["state"] == "started"
    bad = {**document, "note": SENTINEL}
    rejected = maintain(system, bad, "sha256:" + digest(bad), "restart", check=True)
    assert (rejected["applicable"], rejected["reason_code"], rejected["field"]) == (
        False, "maintenance_invalid", "document")
    assert SENTINEL not in json.dumps(rejected)
    unknown = system["delivery"].maintain(document, evidence, "rollback", check=True)
    assert (unknown["applicable"], unknown["reason_code"], unknown["phase"]) == (False, "maintenance_phase", None)


def test_every_lane_write_and_hold_is_one_transaction_never_nested(tmp_path):
    """LinkedStores raises on any transaction opened inside another one (the PG advisory lock)."""
    system = active_system(tmp_path)
    restarted(system)
    assert generation_of(system)["state"] == "started"
    assert system["store"].transactions > 0 and system["control"].transactions > 0


# ----- the PR-2 observer --------------------------------------------------------------------------------------
def pr2_observe(system):
    """The unchanged HME predicates over the REAL lane rows and host files."""
    target = system["target"]
    with system["store"].transaction() as tx:
        view = delivery_view(tx.get(BUCKET_TARGETS, TARGET), tx.get("host_delivery_plans", system["plan_id"]),
                             tx.get(BUCKET_INTENTS, system["plan_id"]), tx.get("host_delivery_descriptors", TARGET),
                             tx.scan(BUCKET_INTENTS), target_id=TARGET, plan_id=system["plan_id"])
    host = system["host"]
    descriptor = host.current(target)
    startup = host.receipt(target)
    consumed = require_consumption(view, descriptor, startup, {"image": descriptor["worker_image"],
                                                               "profile_sha256": descriptor["profile_digest"]},
                                   target_id=TARGET, plan_id=system["plan_id"], state_dir=target["state_dir"])
    plan = view["plan"]["plan"]
    incumbent = owner_qualified_canary(target, descriptor, {key: startup[key] for key in (
        "instance_id", "pid", "runtime_root", "module_root", "revision")}, plan=plan)
    receipt = host.owner_canary(target, system["plan_id"])
    record = read(system["control"], BUCKET_ACTIONS, receipt["evidence"]["action_id"])
    require_canary(consumed, incumbent, receipt, host.owner_canary_request(target, system["plan_id"]), record,
                   intent=intent_of(system), started_at=startup["started_at"])
    return consumed["instance_id"]


def test_pr2_observer_refuses_during_the_open_maintenance(tmp_path):
    system = active_system(tmp_path)
    assert pr2_observe(system) == intent_of(system)["instance_id"]
    restarted(system)
    # The started generation is not a consumption claim: the unchanged PR-2 predicates refuse the new instance
    # (they accept it only after the remainder's bind), and the historical binding is not relabelled.
    with pytest.raises(MigrationRefused) as during:
        pr2_observe(system)
    assert during.value.field == "instance_binding"
    assert plan_row_of(system)["plan_sha256"] == system["plan_sha256"]
