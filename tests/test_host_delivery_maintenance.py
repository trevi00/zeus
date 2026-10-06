"""INV-HOST-DELIVERY-MAINTENANCE-001: restart, arm and bind of an ACTIVE, consumed managed delivery.

Real: `HostDelivery`, `Releases`, `ReleaseQueue` (maintenance hold), the owner canary check and receipt
files, the HME PR-2 predicates and (one test) the unchanged `OwnerActions`. LABELLED fakes only for the host
(`FakeManagedHost`), the Fleet maintenance seam, the one-job executor, the credential helper, the authority
and artifact stores (see `host_delivery_maintenance_fixtures`). Both executor transports are stubbed to
raise, although no maintenance path builds an executor. No model, provider, network, systemd unit, secret
or production store is touched."""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timedelta

import pytest
from host_delivery_maintenance_fixtures import (
    AUTHORITY_REF,
    BUCKET_ACTIONS,
    BUCKET_JOBS,
    SENTINEL,
    TARGET,
    CountingQueue,
    Crash,
    LossyFleet,
    RecordingExecutor,
    ScriptedLauncher,
    active_system,
    armed,
    authority_store,
    document_for,
    generation_of,
    hold_activation,
    hold_unit,
    intent_of,
    owner_completes,
    owner_requests,
    plan_row_of,
    put,
    read,
    restarted,
    row_of,
    snapshot,
    steal_lease,
    write_owner_file,
    write_request,
)

from codex_harness.adapters.host_delivery import (
    canary_receipt_file,
    canary_request_file,
    owner_qualified_canary,
)
from codex_harness.application.fleet import BUCKET_CONTROL, CONTROL_KEY
from codex_harness.application.host_delivery import (
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_TARGETS,
)
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    BLOCKED,
    EVENT_STAGE,
    KIND_MANAGED,
    MAINTENANCE_RESULT_SCHEMA,
    SWITCHING,
    DeliveryRefused,
)
from codex_harness.domain.host_migration import MigrationRefused
from codex_harness.domain.host_migration_evidence import (
    delivery_view,
    require_canary,
    require_consumption,
)
from codex_harness.domain.model import digest

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
    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Raising)
    monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", Raising)


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
    host, fleet = system["host"], system["fleet"]
    return {"calls": list(host.calls), "puts": system["artifacts"].puts, "fleet": list(fleet.calls),
            "executor": len(system["executor"].calls)}


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event_type, outcome, **fields):
        self.events.append((event_type, outcome, fields.get("attributes") or {}))


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


# ----- arm ----------------------------------------------------------------------------------------------------
def test_arm_refuses_before_started_and_without_verified_primary(tmp_path):
    system = active_system(tmp_path)
    document, evidence = document_for(system)
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_phase", "state")
    crash_before_stop(system)
    with pytest.raises(Crash):
        maintain(system, document, evidence, "restart")
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_phase", "state")
    system["host"].receipt_delay = 10 ** 6
    refused(lambda: maintain(system, document, evidence, "restart"))
    assert generation_of(system)["state"] == "launched"
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_phase", "state")
    system["host"].receipt_delay = 0
    assert maintain(system, document, evidence, "restart")["state"] == "started"
    credentials, host = system["credentials"], system["host"]
    cases = [
        ("secondary", lambda: setattr(credentials, "secondary", True), ("maintenance_primary_unverified", "supervisor")),
        ("not primary", lambda: setattr(credentials, "primary", False),
         ("maintenance_primary_unverified", "supervisor")),
        ("no token", lambda: setattr(credentials, "token", False), ("maintenance_primary_unverified", "supervisor")),
        ("stale identity", lambda: setattr(credentials, "stale", True),
         ("maintenance_primary_unverified", "supervisor")),
        ("truthy assertion", lambda: setattr(credentials, "override", lambda r: {
            **r, "entry": {**r["entry"], "is_primary": "yes"}}), ("maintenance_primary_unverified", "entry")),
        ("helper failed", lambda: setattr(credentials, "error", RuntimeError(SENTINEL)),
         ("maintenance_primary_unverified", "credentials")),
        ("missing helper", lambda: setattr(system["delivery"], "credentials", None),
         ("maintenance_primary_unverified", "credentials")),
        ("selection changed", lambda: setattr(host, "environment_sha256", "f" * 64),
         ("maintenance_primary_unverified", "selection")),
        ("reload pending", lambda: host.reload_pending(), ("maintenance_reload_pending", "unit")),
    ]
    for _name, inject, expected in cases:
        before, done = snapshot(system["store"], system["control"]), effects(system)
        inject()
        assert refused(lambda: maintain(system, document, evidence, "arm")) == expected
        assert snapshot(system["store"], system["control"]) == before and effects(system) == done
        credentials.primary, credentials.secondary, credentials.token, credentials.stale = True, False, True, False
        credentials.override = credentials.error = None
        system["delivery"].credentials = credentials
        host.environment_sha256, host.need_reload = "e" * 64, False
    assert generation_of(system)["arm"] is None and intent_of(system)["stage"] == ACTIVE


def test_arm_requests_grants_acknowledges_then_arms_one_deadline(tmp_path):
    recorder = Recorder()
    system = active_system(tmp_path, observer=recorder)
    document, evidence, _ = restarted(system)
    before_intent = {key: value for key, value in intent_of(system).items() if key != "generations"}
    before_row, rows = row_of(system), lane_rows(system)
    fleet, order = system["fleet"], []
    grant = fleet.grant_maintenance_canary

    def observed_grant(permit):
        generation, intent = generation_of(system), intent_of(system)
        order.append(("grant", generation["state"], generation["arm"]["control"]["state"], intent["stage"]))
        return grant(permit)

    fleet.grant_maintenance_canary = observed_grant
    recorder.events.clear()
    requested_at = system["clock"]()
    result = maintain(system, document, evidence, "arm")
    assert (result["state"], result["pending"], result["reason_code"]) == ("armed", True, "maintenance_canary_pending")
    # Lane request (T1a) -> control grant (C1) -> lane acknowledgement and armed transform (T1b).
    assert order == [("grant", "started", "requested", ACTIVE)]
    generation, intent, row = generation_of(system), intent_of(system), row_of(system)
    arm, new = generation["arm"], generation["launched"]["receipt"]["instance_id"]
    assert arm["control"]["state"] == "acknowledged" and generation["state"] == "armed"
    assert arm["deadline"] == (datetime.fromisoformat(requested_at) + timedelta(seconds=600)).isoformat()
    assert result["deadline"] == arm["deadline"] and result["identities"]["action_id"] == arm["permit"]["action_id"]
    assert arm["permit"]["job_id"] == do.canary_job_id(arm["permit"]["action_id"])
    assert arm["permit"]["action_id"] == do.action_id(do.DELIVERY_CANARY, {
        "plan_id": system["plan_id"], "plan_sha256": system["plan_sha256"], "target_id": TARGET,
        "descriptor_sha256": before_intent["descriptor_sha256"], "instance_id": new})
    expected_intent = {**before_intent, "stage": AWAITING_CONSUMPTION, "previous_stage": ACTIVE,
                       "outcome": "pending", "reason_code": "maintenance_canary_pending", "error_type": None,
                       "attempts": 0, "instance_id": None, "canary": None, "candidate_instance_id": new,
                       "candidate_launch": generation["launched"]["launch"], "stage_entered_at": intent["updated_at"],
                       "stage_deadline": arm["deadline"], "updated_at": intent["updated_at"]}
    assert {key: value for key, value in intent.items() if key != "generations"} == expected_intent
    assert row == {**before_row, "consumed": False, "instance_id": None, "startup_observed": True,
                   "observed_instance_id": new, "observed_revision": generation["launched"]["receipt"]["revision"],
                   "observed_runtime_root": generation["launched"]["receipt"]["runtime_root"],
                   "history": [*(before_row.get("history") or [])[-9:], {
                       "descriptor_sha256": before_row["descriptor_sha256"], "at": before_row["updated_at"],
                       "consumed": True, "instance_id": before_row["instance_id"],
                       "maintenance_id": generation["id"]}], "updated_at": row["updated_at"]}
    assert arm["intent_sha256"] == digest({k: v for k, v in intent.items() if k != "generations"})
    assert arm["descriptor_row_sha256"] == digest(row) and lane_rows(system) == rows
    assert [e for e in recorder.events if e[0] == EVENT_STAGE] == [(EVENT_STAGE, "observed", {
        "plan_id": system["plan_id"], "release_id": system["release"]["id"], "target_id": TARGET,
        "stage": AWAITING_CONSUMPTION, "previous_stage": ACTIVE})]
    assert [entry["phase"] for entry in generation["credential_evidence"]] == ["arm"]
    # The ONE deadline is immutable on replay.
    system["clock"].advance(30)
    again = maintain(system, document, evidence, "arm")
    assert again["pending"] is True and generation_of(system)["arm"]["deadline"] == arm["deadline"]
    assert generation_of(system)["arm"]["permit"] == arm["permit"] and len(order) == 1


def test_a_window_beyond_the_qualification_deadline_is_refused(tmp_path):
    system = active_system(tmp_path)
    document, evidence, _ = restarted(system)
    system["delivery"].qualification_deadline = (system["clock"].at + timedelta(seconds=60)).isoformat()
    before, done = snapshot(system["store"], system["control"]), effects(system)
    assert refused(lambda: maintain(system, document, evidence, "arm")) == (
        "maintenance_invalid", "canary_window_seconds")
    assert snapshot(system["store"], system["control"]) == before and effects(system) == done
    system["delivery"].qualification_deadline = (system["clock"].at + timedelta(seconds=601)).isoformat()
    assert maintain(system, document, evidence, "arm")["state"] == "armed"


def test_unchanged_owner_actions_owe_exactly_one_new_instance_canary(tmp_path):
    from test_owner_delivery import canary_owner, rows

    system = active_system(tmp_path / "delivery")
    document, evidence, _ = restarted(system)
    world, owner = canary_owner(tmp_path, {"delivery": system["delivery"], "plan": system["plan"]})
    old = system["old_action"]
    old_job = {"id": old["job_id"], "status": "accepted", "lane": "a", "manifest_sha256": "6" * 64}
    with world.control.transaction() as tx:
        tx.put(BUCKET_ACTIONS, old["id"], old)
        tx.put(BUCKET_JOBS, old_job["id"], old_job)
    from host_delivery_maintenance_fixtures import action_reader

    fleet = LossyFleet(world.control, system["clock"])      # the world's registered Fleet, owner-paused
    fleet.pause()
    executor = RecordingExecutor(fleet, ScriptedLauncher())
    system["delivery"].maintenance_fleet, system["delivery"].canary_executor = fleet, executor
    system["delivery"].canary_records = action_reader(world.control)
    # While the generation only STARTED (intent still ACTIVE), owner-actions owes nothing.
    owner.tick("owners-1")
    assert [r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY] == [old]
    armed_result = maintain(system, document, evidence, "arm")
    assert armed_result["pending"] is True and executor.calls == []
    owner.tick("owners-1")
    canaries = [r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY and r["id"] != old["id"]]
    assert len(canaries) == 1
    [canary] = canaries
    permit = generation_of(system)["arm"]["permit"]
    assert canary["id"] == permit["action_id"] and canary["state"] == do.REQUESTED
    assert canary["binding"]["instance_id"] == generation_of(system)["launched"]["receipt"]["instance_id"]
    assert canary["job_id"] == permit["job_id"] and world.jobs()[canary["job_id"]]["status"] == "queued"
    owner.tick("owners-1")
    assert len([r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY]) == 2
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_ACTIONS, old["id"]) == old and tx.get(BUCKET_JOBS, old_job["id"]) == old_job
    dispatched = maintain(system, document, evidence, "arm")
    assert dispatched["pending"] is False and len(executor.calls) == 1
    assert world.jobs()[canary["job_id"]]["status"] == "accepted"


def short_steal(system, seconds=10):
    until = (system["clock"].at + timedelta(seconds=seconds)).isoformat()
    put(system["store"], "deployment_locks", "controller", {"owner": "labelled-successor", "lease_until": until})


def test_lost_control_or_lane_acknowledgements_and_two_arms_spawn_once(tmp_path):
    system = active_system(tmp_path)
    fleet = system["fleet"]
    document, evidence, _ = restarted(system)
    # C1 committed, its response lost: the lane stays requested; the replay's grant is cached.
    fleet.commit_then_raise = {"grant"}
    assert refused(lambda: maintain(system, document, evidence, "arm")) == (
        "maintenance_reconciliation_required", "fleet")
    generation = generation_of(system)
    assert generation["state"] == "started" and generation["arm"]["control"]["state"] == "requested"
    assert intent_of(system)["stage"] == ACTIVE and len(fleet.permits()) == 1
    # The lane acknowledgement lost too (a successor held the lease across T1b).
    grant = fleet.grant_maintenance_canary

    def grant_then_lose_lane(permit):
        answer = grant(permit)
        short_steal(system)
        return answer

    fleet.grant_maintenance_canary = grant_then_lose_lane
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_stale", "controller")
    assert generation_of(system)["state"] == "started" and len(fleet.permits()) == 1
    fleet.grant_maintenance_canary = grant
    system["clock"].advance(20)
    result = maintain(system, document, evidence, "arm")
    assert result["state"] == "armed" and len(fleet.permits()) == 1
    assert [call for call in fleet.calls if call == "grant"] == ["grant", "grant", "grant"]
    deadline = generation_of(system)["arm"]["deadline"]
    owner_requests(system)
    # Two arm executors: the second runs while the first one's canary is admitted and still running.
    admitted, finished, answers = threading.Event(), threading.Event(), {}

    def hold_until_second_arm_ran():
        admitted.set()
        assert finished.wait(30)

    system["executor"].before_finish = hold_until_second_arm_ran

    def first():
        answers["first"] = maintain(system, document, evidence, "arm")

    def second():
        assert admitted.wait(30)
        try:
            maintain(system, document, evidence, "arm")
        except DeliveryRefused as exc:
            answers["second"] = (exc.reason_code, exc.field)
        finally:
            finished.set()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert answers["second"] == ("maintenance_reconciliation_required", "job")
    assert answers["first"]["pending"] is False and len(system["executor"].calls) == 1
    assert [call for call in fleet.calls if call == "admit"] == ["admit"]
    assert generation_of(system)["arm"]["deadline"] == deadline
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_already_used", "admission")
    assert len(system["executor"].calls) == 1


def test_an_unknown_dispatch_is_never_executed_again(tmp_path):
    system = active_system(tmp_path)
    system["executor"].outcome = "unknown"
    document, evidence, _ = armed(system)
    owner_requests(system)
    result = maintain(system, document, evidence, "arm")
    assert (result["pending"], result["reason_code"]) == (True, "maintenance_reconciliation_required")
    for phase in ("arm", "bind"):
        assert refused(lambda: maintain(system, document, evidence, phase)) == (
            "maintenance_reconciliation_required", "job")
    assert len(system["executor"].calls) == 1 and generation_of(system)["state"] == "armed"


# ----- expiry and failure ---------------------------------------------------------------------------------------
def test_expiry_before_admission_fails_without_launch_or_rollback(tmp_path):
    system = active_system(tmp_path)
    fleet, host = system["fleet"], system["host"]
    document, evidence, _ = armed(system)
    request = owner_requests(system)
    before_intent, before_row, calls = intent_of(system), row_of(system), list(host.calls)
    close, order = fleet.close_maintenance_canary, []

    def observed_close(permit, reason):
        order.append((reason, generation_of(system)["state"]))
        return close(permit, reason)

    fleet.close_maintenance_canary = observed_close
    system["clock"].advance(601)
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_expired", "deadline")
    assert order == [("maintenance_expired", "armed")]        # the control close BEFORE the lane failure
    job = read(system["control"], BUCKET_JOBS, request["job_id"])
    assert job["status"] == "failed" and job["reason_code"] == "maintenance_expired"
    assert job["maintenance"]["launched"] is False and system["executor"].calls == []
    permit = fleet.permits()[generation_of(system)["id"]]
    assert (permit["state"], permit["close_reason"], permit["launched"]) == ("closed", "maintenance_expired", False)
    intent, generation = intent_of(system), generation_of(system)
    assert (intent["stage"], intent["reason_code"], intent["outcome"]) == (BLOCKED, "maintenance_expired", "blocked")
    assert intent["stage_deadline"] == before_intent["stage_deadline"] and intent["rollback"] is None
    assert generation["state"] == "failed" and generation["failure"]["code"] == "maintenance_expired"
    assert row_of(system) == before_row and host.calls == calls
    # Later ticks, replays and a bind change nothing: the failed maintenance holds the target.
    state = snapshot(system["store"], system["control"])
    for _ in range(3):
        tick = system["delivery"].tick()
        assert tick["blocked"].get(system["plan_id"]) == "maintenance_target_busy"
    for phase in ("restart", "arm", "bind"):
        assert refused(lambda: maintain(system, document, evidence, phase)) == ("maintenance_failed", "state")
    assert snapshot(system["store"], system["control"]) == state and host.calls == calls


def test_expiry_without_any_grant_or_job_closes_the_permit_and_fails(tmp_path):
    system = active_system(tmp_path)
    fleet = system["fleet"]
    document, evidence, _ = restarted(system)

    def unreachable(permit):
        raise TimeoutError("control store unreachable before any commit (labelled injected fault)")

    fleet.grant_maintenance_canary = unreachable
    assert refused(lambda: maintain(system, document, evidence, "arm")) == (
        "maintenance_reconciliation_required", "fleet")
    assert fleet.permits() == {} and generation_of(system)["arm"]["control"]["state"] == "requested"
    system["clock"].advance(601)
    assert refused(lambda: maintain(system, document, evidence, "arm")) == ("maintenance_expired", "deadline")
    permit = fleet.permits()[generation_of(system)["id"]]
    assert (permit["state"], permit["close_reason"]) == ("closed", "maintenance_expired")
    assert generation_of(system)["state"] == "failed" and intent_of(system)["stage"] == BLOCKED


def test_admitted_reserving_job_is_never_expired(tmp_path):
    system = active_system(tmp_path)
    system["executor"].outcome = "running"
    document, evidence, _ = armed(system)
    owner_requests(system)
    result = maintain(system, document, evidence, "arm")
    assert (result["pending"], result["reason_code"]) == (True, "maintenance_canary_pending")
    system["clock"].advance(601)
    state = snapshot(system["store"], system["control"])
    for phase in ("arm", "bind"):
        assert refused(lambda: maintain(system, document, evidence, phase)) == (
            "maintenance_reconciliation_required", "job")
    assert snapshot(system["store"], system["control"]) == state
    permit = system["fleet"].permits()[generation_of(system)["id"]]
    assert permit["state"] == "admitted" and system["fleet"].job(permit["permit"]["job_id"])["status"] == "dispatching"


def test_a_canary_that_settles_after_the_deadline_fails_without_binding_or_rollback(tmp_path):
    """G1-03 critique #1 (S2M-13/S2M-16): the admitted canary is owned to its real settlement, but one that
    settles after the ONE deadline never binds: the generation fails, nothing rolls back or is consumed."""
    system = active_system(tmp_path)
    document, evidence = dispatched(system)
    before_row, calls = row_of(system), list(system["host"].calls)
    owner_completes(system)                                    # accepted, but only after the window
    system["clock"].advance(601)
    with pytest.raises(DeliveryRefused) as late:
        maintain(system, document, evidence, "bind")
    assert (late.value.reason_code, late.value.field) == ("maintenance_expired", "deadline")
    intent, generation = intent_of(system), generation_of(system)
    assert intent["instance_id"] != generation["launched"]["receipt"]["instance_id"]
    assert row_of(system)["consumed"] == before_row["consumed"] and row_of(system)["instance_id"] == before_row[
        "instance_id"]
    assert system["host"].calls == calls and len(system["executor"].calls) == 1 and intent["rollback"] is None
    assert generation["state"] == "failed" and generation["failure"]["code"] == "maintenance_expired"
    for phase in ("arm", "bind"):
        assert refused(lambda: maintain(system, document, evidence, phase)) == ("maintenance_failed", "state")


def test_failure_never_rolls_back_resets_supersedes_or_consumes_twice(tmp_path):
    system = active_system(tmp_path)
    host = system["host"]
    document, evidence, _ = restarted(system)
    before_row, calls = row_of(system), list(host.calls)
    host.n1(system["target"])        # the started generation is definitely not the live one any more
    assert refused(lambda: maintain(system, document, evidence, "arm")) == (
        "maintenance_invocation_mismatch", "instance_id")
    intent, generation = intent_of(system), generation_of(system)
    assert (intent["stage"], intent["reason_code"]) == (BLOCKED, "maintenance_invocation_mismatch")
    assert generation["state"] == "failed" and generation["arm"] is None and len(intent["generations"]) == 1
    assert row_of(system) == before_row and intent["rollback"] is None
    state = snapshot(system["store"], system["control"])
    another, another_evidence = document_for(system, **{"from": document["from"]}, retiring={
        "instance_id": host.receipt(system["target"])["instance_id"], "invocation_id": host.invocation,
        "launch_sha256": digest(host.launch_record(system["target"]))})
    assert refused(lambda: maintain(system, another, another_evidence, "restart")) == (
        "maintenance_already_used", "document")
    for phase in ("restart", "arm", "bind"):
        assert refused(lambda: maintain(system, document, evidence, phase)) == ("maintenance_failed", "state")
    for _ in range(3):
        system["delivery"].tick()
    assert snapshot(system["store"], system["control"]) == state
    assert host.calls == calls and len(intent_of(system)["generations"]) == 1


# ----- bind ---------------------------------------------------------------------------------------------------
def dispatched(system, *, outcome="accepted"):
    system["executor"].outcome = outcome
    document, evidence, _ = armed(system)
    owner_requests(system)
    result = maintain(system, document, evidence, "arm")
    assert result["state"] == "armed"
    return document, evidence


def test_bind_binds_only_the_genuine_new_instance_receipt(tmp_path):
    system = active_system(tmp_path)
    rows = lane_rows(system)
    old_history = len(row_of(system).get("history") or [])
    document, evidence = dispatched(system)
    pending = maintain(system, document, evidence, "bind")
    assert (pending["pending"], pending["reason_code"], pending["state"]) == (True, "maintenance_canary_pending",
                                                                               "armed")
    action = owner_completes(system)
    result = maintain(system, document, evidence, "bind")
    assert (result["state"], result["pending"], result["cached"]) == ("bound", False, False)
    intent, row, generation = intent_of(system), row_of(system), generation_of(system)
    new = generation["launched"]["receipt"]["instance_id"]
    assert (intent["stage"], intent["outcome"], intent["instance_id"]) == (ACTIVE, "active", new)
    assert intent["canary"]["passed"] is True and intent["canary"]["evidence"]["action_id"] == action["id"]
    assert (row["consumed"], row["instance_id"], row["observed_instance_id"]) == (True, new, new)
    assert len(row["history"]) == old_history + 1 and row["history"][-1]["maintenance_id"] == generation["id"]
    assert generation["canary"]["settlement"]["state"] == "closed" and generation["state"] == "bound"
    assert generation["canary"]["action_id"] == action["id"]
    # PRIMARY evidence was re-proven immediately before the dispatch; booleans, pids and ticks only.
    assert [entry["phase"] for entry in generation["credential_evidence"]] == ["arm", "dispatch"]
    assert all(set(entry["supervisor"]) == {"pid", "start_ticks", "has_token", "is_primary", "is_secondary"}
               for entry in generation["credential_evidence"])
    assert str(tmp_path) not in json.dumps(result)
    permit = system["fleet"].permits()[generation["id"]]
    assert (permit["state"], permit["close_reason"]) == ("closed", "maintenance_settled")
    assert lane_rows(system) == rows
    assert read(system["control"], BUCKET_ACTIONS, system["old_action"]["id"]) == system["old_action"]
    view = system["delivery"].status(system["plan_id"])["deliveries"][0]
    assert view["maintenance"]["qualified"] is True and view["maintenance"]["open"] is False
    # The target is free again: an ordinary tick sees only the ACTIVE (terminal) delivery.
    assert system["delivery"].tick()["blocked"].get(system["plan_id"]) == ACTIVE


def receipt_case(**overrides):
    return lambda system: owner_completes(system, **overrides)


def old_receipt(system):
    owner_completes(system)
    write_owner_file(system, canary_receipt_file(system["plan_id"]), json.dumps(system["old_receipt"]))


def rejected_canary(system):
    owner_completes(system, verdict=False)


UNBOUND = {
    "old receipt": (old_receipt, "maintenance_canary_unbound"),
    "passed is a truthy string": (receipt_case(passed="true"), "maintenance_canary_unbound"),
    "passed is one": (receipt_case(passed=1), "maintenance_canary_unbound"),
    "wrong instance": (receipt_case(instance_id="9" * 32), "maintenance_canary_unbound"),
    "no instance": (receipt_case(instance_id=None), "maintenance_canary_unbound"),
    "wrong action": (receipt_case(evidence={"action_id": "9" * 64, "plan_id": "maintained-plan"}),
                     "maintenance_canary_unbound"),
    "wrong descriptor": (receipt_case(descriptor_sha256="9" * 64), "maintenance_canary_unbound"),
    "recorded before the startup": (receipt_case(recorded_at="2026-09-21T00:00:00+00:00"),
                                    "maintenance_canary_unbound"),
    "request mismatch": (lambda s: (owner_completes(s), write_request(s, revision="7" * 40)),
                         "maintenance_canary_unbound"),
    "unreadable receipt": (lambda s: (owner_completes(s), write_owner_file(
        s, canary_receipt_file(s["plan_id"]), SENTINEL + "{")), "maintenance_canary_unbound"),
    "unreadable request": (lambda s: (owner_completes(s), write_owner_file(
        s, canary_request_file(s["plan_id"]), "[" + SENTINEL)), "maintenance_canary_unbound"),
    "canary still requested": (lambda s: None, "pending"),
}


@pytest.mark.parametrize("case", sorted(UNBOUND))
def test_bind_refuses_every_unbound_receipt(tmp_path, case):
    system = active_system(tmp_path)
    document, evidence = dispatched(system)
    setup, expected = UNBOUND[case]
    setup(system)
    state = snapshot(system["store"], system["control"])
    if expected == "pending":
        result = maintain(system, document, evidence, "bind")
        assert (result["pending"], result["reason_code"]) == (True, "maintenance_canary_pending")
    else:
        code, field = refused(lambda: maintain(system, document, evidence, "bind"))
        assert code == expected and SENTINEL not in str(field)
        checked = maintain(system, document, evidence, "bind", check=True)
        assert checked["applicable"] is False and SENTINEL not in json.dumps(checked)
    # Nothing is stored as passed before the binding holds.
    assert snapshot(system["store"], system["control"]) == state
    assert generation_of(system)["state"] == "armed" and intent_of(system)["stage"] == AWAITING_CONSUMPTION


FAILURES = {
    "rejected job": ("rejected", lambda s: None, ("maintenance_failed", "job")),
    "rejected canary": ("accepted", rejected_canary, ("maintenance_failed", "action")),
    "changed live instance": ("accepted", lambda s: (owner_completes(s), s["host"].n1(s["target"])),
                              ("maintenance_invocation_mismatch", "instance_id")),
}


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_a_rejected_or_changed_canary_fails_the_generation_without_rollback(tmp_path, case):
    system = active_system(tmp_path)
    outcome, setup, expected = FAILURES[case]
    document, evidence = dispatched(system, outcome=outcome)
    setup(system)
    before_row, calls = row_of(system), list(system["host"].calls)
    assert refused(lambda: maintain(system, document, evidence, "bind")) == expected
    intent, generation = intent_of(system), generation_of(system)
    assert (intent["stage"], intent["reason_code"]) == (BLOCKED, expected[0])
    assert generation["state"] == "failed" and generation["canary"] is None
    assert row_of(system) == before_row and row_of(system)["consumed"] is False
    assert system["host"].calls == calls and intent["rollback"] is None


def test_bind_replay_cached_drift_refused_history_kept_settlement_held(tmp_path):
    system = active_system(tmp_path)
    fleet = system["fleet"]
    document, evidence = dispatched(system)
    owner_completes(system)
    # Concurrent drift of a pinned source refuses the bind with nothing written.
    record = read(system["store"], "releases", system["release"]["id"])
    put(system["store"], "releases", system["release"]["id"], {**record, "note": "labelled concurrent drift"})
    state = snapshot(system["store"], system["control"])
    assert refused(lambda: maintain(system, document, evidence, "bind")) == ("maintenance_stale", "release_id")
    assert snapshot(system["store"], system["control"]) == state
    put(system["store"], "releases", system["release"]["id"], record)
    # The control settlement is lost: bound, but the permit stays open and the lane says so.
    close = fleet.close_maintenance_canary

    def lost_close(permit, reason):
        fleet.close_maintenance_canary = close
        raise TimeoutError("close response lost before commit (labelled injected fault)")

    fleet.close_maintenance_canary = lost_close
    result = maintain(system, document, evidence, "bind")
    assert (result["state"], result["pending"], result["reason_code"]) == ("bound", True,
                                                                           "maintenance_reconciliation_required")
    generation = generation_of(system)
    assert generation["canary"]["settlement"] is None and fleet.permits()[generation["id"]]["state"] == "admitted"
    assert fleet.maintenance_readiness()["open_permits"] == [generation["id"]]
    # A bind replay settles it, then every further replay is cached with no write.
    settled = maintain(system, document, evidence, "bind")
    assert (settled["cached"], settled["pending"]) == (True, False)
    assert generation_of(system)["canary"]["settlement"]["state"] == "closed"
    state = snapshot(system["store"], system["control"])
    again = maintain(system, document, evidence, "bind")
    assert (again["cached"], again["state"]) == (True, "bound")
    assert snapshot(system["store"], system["control"]) == state
    history = row_of(system)["history"]
    assert history[-1]["descriptor_sha256"] == row_of(system)["descriptor_sha256"]      # same-digest history


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
    assert (checked("arm")["applicable"], checked("arm")["reason_code"]) == (False, "maintenance_phase")
    maintain(system, document, evidence, "restart")
    assert checked("restart")["cached"] is True
    first_arm = checked("arm")
    assert first_arm["applicable"] is True and first_arm["deadline"] is not None
    assert checked("bind")["reason_code"] == "maintenance_phase"
    maintain(system, document, evidence, "arm")
    owner_requests(system)
    assert checked("arm")["applicable"] is True and system["executor"].calls == []
    maintain(system, document, evidence, "arm")
    owner_completes(system)
    bind = checked("bind")
    assert (bind["applicable"], bind["pending"]) == (True, False)
    assert generation_of(system)["state"] == "armed"
    bad = {**document, "note": SENTINEL}
    rejected = maintain(system, bad, "sha256:" + digest(bad), "bind", check=True)
    assert (rejected["applicable"], rejected["reason_code"], rejected["field"]) == (
        False, "maintenance_invalid", "document")
    assert SENTINEL not in json.dumps(rejected)
    unknown = system["delivery"].maintain(document, evidence, "rollback", check=True)
    assert (unknown["applicable"], unknown["reason_code"], unknown["phase"]) == (False, "maintenance_phase", None)


def test_every_lane_write_and_hold_is_one_transaction_never_nested(tmp_path):
    """LinkedStores raises on any transaction opened inside another one (the PG advisory lock)."""
    system = active_system(tmp_path)
    document, evidence = dispatched(system)
    owner_completes(system)
    assert maintain(system, document, evidence, "bind")["state"] == "bound"
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


def test_pr2_observer_refuses_during_maintenance_and_accepts_after_bind(tmp_path):
    system = active_system(tmp_path)
    assert pr2_observe(system) == intent_of(system)["instance_id"]
    document, evidence, _ = restarted(system)
    with pytest.raises(MigrationRefused) as during:
        pr2_observe(system)
    assert during.value.field == "instance_binding"
    maintain(system, document, evidence, "arm")
    with pytest.raises(MigrationRefused) as armed_view:
        pr2_observe(system)
    assert armed_view.value.field == "delivery_not_active"
    owner_requests(system)
    maintain(system, document, evidence, "arm")
    owner_completes(system)
    assert maintain(system, document, evidence, "bind")["state"] == "bound"
    assert pr2_observe(system) == generation_of(system)["launched"]["receipt"]["instance_id"]
    assert plan_row_of(system)["plan_sha256"] == system["plan_sha256"]
