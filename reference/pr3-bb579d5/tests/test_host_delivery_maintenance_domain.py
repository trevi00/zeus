"""INV-HOST-DELIVERY-MAINTENANCE-001: the pure maintenance policy (document grammar, generation id,
transition table, restart classification, identity and credential binding, the allowlisted view).

Pure dictionaries only: no store, process, host, provider or model is touched."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from codex_harness.domain.host_delivery import (
    ACTIVE,
    CREDENTIAL_EVIDENCE_SCHEMA,
    DESCRIPTOR_SCHEMA,
    GENERATION_OBSERVATION_SCHEMA,
    GENERATION_STATES,
    GENERATION_TRANSITIONS,
    MAINTENANCE_CODES,
    MAINTENANCE_ID,
    MAINTENANCE_KIND,
    MAINTENANCE_REASON,
    MAINTENANCE_SCHEMA,
    RECEIPT_SCHEMA,
    DeliveryRefused,
    classify_restart,
    delivery_progress,
    descriptor_digest,
    fleet_ready_refusal,
    generation_id,
    maintenance_hold,
    maintenance_of,
    maintenance_open,
    maintenance_transition,
    maintenance_view,
    new_generation_refusal,
    selection_of,
    validate_active_generation,
    validate_credential_evidence,
    validate_generation_observation,
    validate_restart_authority,
)
from codex_harness.domain.model import canonical, digest

SENTINEL = "SENTINEL-must-never-leak"
REQUESTED_AT = "2026-09-22T00:00:10+00:00"
OLD_INVOCATION, NEW_INVOCATION = "1" * 32, "2" * 32
OLD_INSTANCE, NEW_INSTANCE = "a" * 32, "b" * 32


def document(**overrides) -> dict:
    base = {"schema": MAINTENANCE_SCHEMA, "kind": MAINTENANCE_KIND, "plan_id": "maintained-plan",
            "plan_sha256": "1" * 64, "pin_sha256": "2" * 64, "target_id": "fleet-host", "release_id": "r" * 8,
            "descriptor_sha256": "3" * 64, "from": {"stage": ACTIVE, "updated_at": "2026-09-22T00:00:05+00:00"},
            "retiring": {"instance_id": OLD_INSTANCE, "invocation_id": OLD_INVOCATION, "launch_sha256": "4" * 64},
            "reason": MAINTENANCE_REASON, "canary_window_seconds": 600, "authority": "sha256:" + "5" * 64,
            "approved_by": "conductor"}
    base.update(overrides)
    return base


def without(key):
    doc = document()
    doc.pop(key)
    return doc


DOCUMENT_DEFECTS = [
    ("document", "not a document"),
    ("document", {**document(), "token": "ghp_" + "x" * 36}),
    ("document", {**document(), "supersedes": "active_generation_1:" + "0" * 64}),
    ("document", {**document(), "command": ["systemctl", "restart"]}),
    ("document", {**document(), "environment": {"GH_TOKEN": "x"}}),
    ("document", without("approved_by")),
    ("schema", document(schema="urn:zeus:host-delivery-active-generation:2")),
    ("kind", document(kind="first_activation_generation_restart")),
    ("plan_id", document(plan_id="bad plan id")),
    ("release_id", document(release_id="")),
    ("target_id", document(target_id="../etc")),
    ("plan_sha256", document(plan_sha256="A" * 64)),
    ("pin_sha256", document(pin_sha256="2" * 63)),
    ("descriptor_sha256", document(descriptor_sha256=None)),
    ("from", document(**{"from": {"stage": "blocked", "updated_at": "2026-09-22T00:00:05+00:00"}})),
    ("from", document(**{"from": {"stage": ACTIVE, "updated_at": "2026-09-22T00:00:05"}})),
    ("from", document(**{"from": {"stage": ACTIVE, "updated_at": 5}})),
    ("from", document(**{"from": {"stage": ACTIVE, "updated_at": "x" * 65}})),
    ("from", document(**{"from": {"stage": ACTIVE, "updated_at": "2026-09-22T00:00:05+00:00", "extra": 1}})),
    ("retiring", document(retiring={"instance_id": "A" * 32, "invocation_id": OLD_INVOCATION,
                                    "launch_sha256": "4" * 64})),
    ("retiring", document(retiring={"instance_id": OLD_INSTANCE, "invocation_id": "1" * 31,
                                    "launch_sha256": "4" * 64})),
    ("retiring", document(retiring={"instance_id": OLD_INSTANCE, "invocation_id": OLD_INVOCATION,
                                    "launch_sha256": "F" * 64})),
    ("retiring", document(retiring={"instance_id": OLD_INSTANCE, "invocation_id": OLD_INVOCATION,
                                    "launch_sha256": "4" * 64, "pid": 1})),
    ("reason", document(reason="operator wants a restart")),
    ("canary_window_seconds", document(canary_window_seconds=True)),
    ("canary_window_seconds", document(canary_window_seconds=0)),
    ("canary_window_seconds", document(canary_window_seconds=3601)),
    ("canary_window_seconds", document(canary_window_seconds="600")),
    ("authority", document(authority="5" * 64)),
    ("authority", document(authority="sha256:" + "G" * 64)),
    ("approved_by", document(approved_by="bad approver!")),
]


@pytest.mark.parametrize("field,value", DOCUMENT_DEFECTS)
def test_the_document_grammar_is_exact(field, value):
    with pytest.raises(DeliveryRefused) as refused:
        validate_active_generation(value)
    assert (refused.value.reason_code, refused.value.field) == ("maintenance_invalid", field)
    assert "ghp_" not in str(refused.value) and "GH_TOKEN" not in str(refused.value)


def test_the_exact_document_is_accepted_as_a_copy_with_its_bounds():
    doc = document()
    checked = validate_active_generation(doc)
    assert checked == doc and checked["from"] is not doc["from"] and checked["retiring"] is not doc["retiring"]
    for window in (1, 3600):
        assert validate_active_generation(document(canary_window_seconds=window))["canary_window_seconds"] == window


def test_generation_id_and_evidence_follow_the_canonical_digest():
    doc = document()
    expected = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                              .encode("utf-8")).hexdigest()
    assert generation_id(doc) == "active_generation_1:" + expected
    assert MAINTENANCE_ID.fullmatch(generation_id(doc))
    assert "sha256:" + digest(doc) == "sha256:" + expected
    reordered = dict(reversed(list(doc.items())))
    assert generation_id(reordered) == generation_id(doc)
    assert generation_id(document(canary_window_seconds=601)) != generation_id(doc)
    with pytest.raises(DeliveryRefused):
        generation_id({**doc, "token": "x"})


def test_the_twenty_one_codes_are_exact():
    assert len(MAINTENANCE_CODES) == len(set(MAINTENANCE_CODES)) == 21
    assert all(code.startswith("maintenance_") for code in MAINTENANCE_CODES)


def generation(state="requested", **fields):
    return {"id": "active_generation_1:" + "0" * 64, "state": state, **fields}


def test_generation_transitions_are_a_closed_table():
    allowed = {("requested", "launched"), ("requested", "started"), ("requested", "failed"),
               ("launched", "started"), ("launched", "failed"), ("started", "armed"), ("started", "failed"),
               ("armed", "bound"), ("armed", "failed")}
    for source in GENERATION_STATES:
        for target in GENERATION_STATES:
            if (source, target) in allowed:
                maintenance_transition(generation(source), target)
            else:
                with pytest.raises(DeliveryRefused) as refused:
                    maintenance_transition(generation(source), target)
                assert (refused.value.reason_code, refused.value.field) == ("maintenance_phase", "state")
    assert GENERATION_TRANSITIONS["bound"] == GENERATION_TRANSITIONS["failed"] == frozenset()
    with pytest.raises(DeliveryRefused):
        maintenance_transition(generation("unknown"), "launched")


def test_open_failed_and_bound_generations_hold_and_release_exactly():
    legacy = {"plan_id": "p1", "target_id": "t", "stage": ACTIVE}
    assert maintenance_of(legacy) is None and maintenance_of({**legacy, "generations": []}) is None
    assert not maintenance_open(legacy)
    for state in GENERATION_STATES:
        intent = {**legacy, "generations": [generation(state)]}
        assert maintenance_open(intent) is (state != "bound")
    failed = {**legacy, "generations": [generation("failed")]}
    other = {"plan_id": "p2", "target_id": "t", "stage": ACTIVE}
    assert maintenance_hold([other, failed], "t") is failed
    assert maintenance_hold([other, failed], "t", exclude_plan_id="p1") is None
    assert maintenance_hold([failed], "another-target") is None


# ----- the restart classification ------------------------------------------------------------------------
DESCRIPTOR = {"schema": DESCRIPTOR_SCHEMA, "target_id": "fleet-host", "root": "/srv/managed/runtimes/" + "2" * 40,
              "revision": "2" * 40, "worker_image": "zeus-worker@sha256:" + "d" * 64, "profile_digest": "e" * 64,
              "predecessor": None}


def receipt(instance=OLD_INSTANCE, **overrides):
    return {"schema": RECEIPT_SCHEMA, "target_id": "fleet-host", "instance_id": instance, "pid": 2001,
            "started_at": "2026-09-22T00:00:01+00:00", "runtime_root": DESCRIPTOR["root"],
            "module_root": DESCRIPTOR["root"] + "/src/codex_harness", "descriptor_sha256": descriptor_digest(DESCRIPTOR),
            "revision": DESCRIPTOR["revision"], "worker_image": DESCRIPTOR["worker_image"],
            "profile_digest": DESCRIPTOR["profile_digest"], **overrides}


OLD_LAUNCH = {"pid": 1001, "service": "zeus-aibox-managed-fleet", "invocation_id": OLD_INVOCATION,
              "started_at": "2026-09-22T00:00:01+00:00", "descriptor_sha256": descriptor_digest(DESCRIPTOR),
              "manifest_sha256": "5" * 64}
NEW_LAUNCH = {**OLD_LAUNCH, "pid": 1002, "invocation_id": NEW_INVOCATION, "started_at": "2026-09-22T00:00:12+00:00"}


def observation(**overrides):
    base = {"schema": GENERATION_OBSERVATION_SCHEMA, "observed_at": "2026-09-22T00:00:11+00:00", "running": True,
            "receipt": receipt(), "receipt_present": True, "launch": OLD_LAUNCH, "launch_present": True,
            "launch_sha256": digest(OLD_LAUNCH), "launch_request_sha256": "6" * 64,
            "launch_request_requested_at": "2026-09-22T00:00:01+00:00", "target_file_matches": True,
            "control_user_matches": True,
            "unit": {"active_state": "active", "invocation_id": OLD_INVOCATION, "main_pid": 1001, "exec_main_pid": 1001,
                     "need_daemon_reload": False, "control_group_sha256": "c" * 64,
                     "environment_files_sha256": "e" * 64, "drop_in_count": 1},
            "supervisor": {"pid": 1001, "state": "present", "start_ticks": 50001, "is_main_pid": True},
            "entry": {"pid": 2001, "state": "present", "start_ticks": 60001, "parent_is_supervisor": True,
                      "in_unit_cgroup": True, "started_before_receipt": True},
            "work": {"state": "idle", "reason_code": None, "active": 0, "unresolved": 0}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict) and key not in ("receipt", "launch"):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def launched(**overrides):
    """The observation after the one launch: the new invocation, controller-state and receipt."""
    unit = {"invocation_id": NEW_INVOCATION, **overrides.pop("unit", {})}
    return observation(**{"launch": NEW_LAUNCH, "launch_sha256": digest(NEW_LAUNCH),
                          "launch_request_requested_at": REQUESTED_AT,
                          "receipt": receipt(NEW_INSTANCE), "unit": unit, **overrides})


RESTARTS = {"maintenance_id": "active_generation_1:" + "0" * 64, "instance_id": OLD_INSTANCE,
            "invocation_id": OLD_INVOCATION, "launch_sha256": digest(OLD_LAUNCH), "requested_at": REQUESTED_AT}

CLASSIFY_CASES = [
    ("replace", observation(), ("replace", None, None)),
    ("launch after a proved stop, receipt retained", observation(running=False, unit={"active_state": "inactive"}),
     ("launch", None, None)),
    ("launch after the retire, receipt absent", observation(running=False, receipt=None, receipt_present=False,
                                                          unit={"active_state": "inactive"}), ("launch", None, None)),
    ("recognized own request-bound launch", launched(), ("recognized", None, None)),
    ("N1: another invocation, same controller-state", observation(unit={"invocation_id": "9" * 32}),
     (None, "maintenance_invocation_mismatch", "invocation_id")),
    ("N1 with its own receipt", observation(unit={"invocation_id": "9" * 32}, receipt=receipt("9" * 32)),
     (None, "maintenance_invocation_mismatch", "invocation_id")),
    ("another incumbent receipt", observation(receipt=receipt("9" * 32)),
     (None, "maintenance_invocation_mismatch", "instance_id")),
    ("a foreign descriptor receipt", observation(receipt=receipt(revision="3" * 40)),
     (None, "maintenance_invocation_mismatch", "instance_id")),
    ("pid reuse", observation(entry={"started_before_receipt": False}),
     (None, "maintenance_invocation_mismatch", "entry")),
    ("wrong parent", observation(entry={"parent_is_supervisor": False}),
     (None, "maintenance_invocation_mismatch", "entry")),
    ("another cgroup", observation(entry={"in_unit_cgroup": None}), (None, "maintenance_invocation_mismatch", "entry")),
    ("supervisor is not the main pid", observation(supervisor={"is_main_pid": False}),
     (None, "maintenance_invocation_mismatch", "supervisor")),
    ("reload pending", observation(unit={"need_daemon_reload": True}), (None, "maintenance_reload_pending", "unit")),
    ("reload unknown", observation(unit={"need_daemon_reload": None}), (None, "maintenance_reload_pending", "unit")),
    ("target file differs", observation(target_file_matches=False), (None, "maintenance_stale", "target_file")),
    ("service user unknown", observation(control_user_matches=None), (None, "maintenance_invalid", "service_user")),
    ("liveness unknown", observation(running=None), (None, "maintenance_launch_unconfirmed", "running")),
    ("work busy", observation(work={"state": "busy", "active": 1}), (None, "maintenance_debt_unsettled", "work")),
    ("work unknown", observation(work={"state": "unknown", "active": None}),
     (None, "maintenance_debt_unsettled", "work")),
    ("stopped while another invocation is active", observation(running=False, unit={"invocation_id": "9" * 32}),
     (None, "maintenance_invocation_mismatch", "instance_id")),
    ("stopped with a foreign receipt", observation(running=False, receipt=receipt("9" * 32),
                                                   unit={"active_state": "inactive"}),
     (None, "maintenance_invocation_mismatch", "instance_id")),
    ("changed launch of another descriptor", launched(launch={**NEW_LAUNCH, "descriptor_sha256": "7" * 64},
                                                      launch_sha256=digest({**NEW_LAUNCH, "descriptor_sha256": "7" * 64})),
     (None, "maintenance_launch_unconfirmed", "launch")),
    ("changed launch before the request (reboot)", launched(
        launch={**NEW_LAUNCH, "started_at": "2026-09-22T00:00:09+00:00"},
        launch_sha256=digest({**NEW_LAUNCH, "started_at": "2026-09-22T00:00:09+00:00"})),
     (None, "maintenance_launch_unconfirmed", "launch")),
    ("launch request before the maintenance request", launched(
        launch_request_requested_at="2026-09-22T00:00:09+00:00"), (None, "maintenance_launch_unconfirmed", "launch")),
    ("launch request after the launch", launched(launch_request_requested_at="2026-09-22T00:00:13+00:00"),
     (None, "maintenance_launch_unconfirmed", "launch")),
    ("launch request inside the window but not this attempt's",
     launched(launch_request_requested_at="2026-09-22T00:00:11+00:00"), (None, "maintenance_launch_unconfirmed", "launch")),
    # S2R F1: the retiring controller-state and a stopped unit, but THIS attempt's launch request persisted: the
    # start's outcome is unproven, so a replay holds instead of launching again.
    ("stopped, but this attempt's launch request persisted", observation(
        running=False, receipt=None, receipt_present=False, unit={"active_state": "inactive", "invocation_id": None},
        launch_request_requested_at=REQUESTED_AT), (None, "maintenance_launch_unconfirmed", "launch")),
    ("stopped, a launch request after this request", observation(
        running=False, receipt=None, receipt_present=False, unit={"active_state": "inactive", "invocation_id": None},
        launch_request_requested_at="2026-09-22T00:00:12+00:00"), (None, "maintenance_launch_unconfirmed", "launch")),
    ("stopped, the launch request unreadable", observation(
        running=False, receipt=None, receipt_present=False, unit={"active_state": "inactive", "invocation_id": None},
        launch_request_requested_at=None, launch_request_sha256=None), (None, "maintenance_launch_unconfirmed", "launch")),
    ("no launch request", launched(launch_request_requested_at=None, launch_request_sha256=None),
     (None, "maintenance_launch_unconfirmed", "launch")),
    ("unit runs yet another invocation", launched(unit={"invocation_id": "9" * 32}),
     (None, "maintenance_launch_unconfirmed", "launch")),
    ("controller-state gone", observation(launch=None, launch_present=False, launch_sha256=None),
     (None, "maintenance_launch_unconfirmed", "launch")),
    ("malformed observation", {**observation(), "extra": SENTINEL},
     (None, "maintenance_invocation_mismatch", "observation")),
    ("inconsistent launch digest", observation(launch_sha256="8" * 64),
     (None, "maintenance_invocation_mismatch", "observation")),
    ("truthy non-bool flag", observation(entry={"in_unit_cgroup": "true"}),
     (None, "maintenance_invocation_mismatch", "observation")),
]


@pytest.mark.parametrize("case,observed,expected", CLASSIFY_CASES, ids=[case[0] for case in CLASSIFY_CASES])
def test_classify_restart_matrix(case, observed, expected):
    decision = classify_restart(DESCRIPTOR, observed, RESTARTS)
    assert (decision["path"], decision["reason_code"], decision["field"]) == expected
    assert SENTINEL not in json.dumps(decision)


@pytest.mark.parametrize("restarts", [
    {**RESTARTS, "extra": 1}, {**RESTARTS, "invocation_id": "X" * 32}, {**RESTARTS, "requested_at": "yesterday"},
    {**RESTARTS, "maintenance_id": "sha256:" + "0" * 64}, "restart-everything"])
def test_the_restart_authority_is_narrowly_typed(restarts):
    with pytest.raises(DeliveryRefused) as refused:
        validate_restart_authority(restarts)
    assert (refused.value.reason_code, refused.value.field) == ("maintenance_invalid", "restarts")
    decision = classify_restart(DESCRIPTOR, observation(), restarts)
    assert (decision["path"], decision["reason_code"]) == (None, "maintenance_invalid")


def test_the_observation_copy_replaces_the_receipt_by_its_validated_form():
    checked = validate_generation_observation(observation())
    assert checked["receipt_state"] == "valid" and checked["receipt"] == receipt()
    unreadable = validate_generation_observation(observation(receipt={"schema": "x", "note": SENTINEL}))
    assert unreadable["receipt"] is None and unreadable["receipt_state"] == "unreadable"
    absent = validate_generation_observation(observation(receipt=None, receipt_present=False))
    assert absent["receipt"] is None and absent["receipt_state"] == "absent"
    assert selection_of(checked) == {"environment_files_sha256": "e" * 64, "drop_in_count": 1}


STARTED = {"id": "active_generation_1:" + "0" * 64, "state": "started",
           "retiring": {"instance_id": OLD_INSTANCE, "invocation_id": OLD_INVOCATION},
           "launched": {"invocation_id": NEW_INVOCATION, "launch_sha256": digest(NEW_LAUNCH),
                        "receipt": {"instance_id": NEW_INSTANCE}}}


@pytest.mark.parametrize("observed,expected", [
    (launched(), None),
    (launched(running=False), ("maintenance_invocation_mismatch", "running")),
    (launched(running=None), ("maintenance_launch_unconfirmed", "running")),
    (launched(receipt=None, receipt_present=False), ("maintenance_launch_unconfirmed", "receipt")),
    (launched(receipt=receipt(OLD_INSTANCE)), ("maintenance_invocation_mismatch", "receipt")),
    (launched(receipt=receipt("9" * 32)), ("maintenance_invocation_mismatch", "instance_id")),
    (launched(unit={"invocation_id": "9" * 32}), ("maintenance_invocation_mismatch", "invocation_id")),
    (launched(unit={"invocation_id": None}), ("maintenance_launch_unconfirmed", "unit")),
    (launched(launch=OLD_LAUNCH, launch_sha256=digest(OLD_LAUNCH)), ("maintenance_invocation_mismatch", "launch")),
    (launched(entry={"started_before_receipt": False}), ("maintenance_invocation_mismatch", "entry")),
    (launched(entry={"in_unit_cgroup": None}), ("maintenance_launch_unconfirmed", "entry")),
    (launched(supervisor={"is_main_pid": False}), ("maintenance_invocation_mismatch", "supervisor")),
    (launched(unit={"need_daemon_reload": True}), ("maintenance_reload_pending", "unit")),
    ({"schema": "broken"}, ("maintenance_launch_unconfirmed", "observation")),
])
def test_the_live_identity_must_be_exactly_the_started_generation(observed, expected):
    assert new_generation_refusal(DESCRIPTOR, observed, STARTED) == expected


# ----- PRIMARY credential evidence ----------------------------------------------------------------------
def credential(**parts):
    record = {"schema": CREDENTIAL_EVIDENCE_SCHEMA, "observed_at": "2026-09-22T00:00:20+00:00",
              "invocation_id": NEW_INVOCATION, "helper_sha256": "4" * 64,
              "supervisor": {"pid": 1002, "start_ticks": 50002, "has_token": True, "is_primary": True,
                             "is_secondary": False},
              "entry": {"pid": 2002, "start_ticks": 60002, "has_token": True, "is_primary": True,
                        "is_secondary": False}}
    for key, value in parts.items():
        record[key] = {**record[key], **value} if isinstance(value, dict) and key in ("supervisor", "entry") else value
    return record


LIVE = validate_generation_observation(launched(unit={"invocation_id": NEW_INVOCATION},
                                                supervisor={"pid": 1002, "start_ticks": 50002},
                                                entry={"pid": 2002, "start_ticks": 60002}))


@pytest.mark.parametrize("record,field", [
    (credential(supervisor={"is_secondary": True}), "supervisor"),
    (credential(entry={"is_primary": False}), "entry"),
    (credential(entry={"has_token": False}), "entry"),
    (credential(supervisor={"is_primary": "true"}), "supervisor"),
    (credential(entry={"has_token": 1}), "entry"),
    (credential(supervisor={"pid": 1003}), "supervisor"),
    (credential(entry={"start_ticks": 60003}), "entry"),
    (credential(invocation_id="9" * 32), "record"),
    (credential(helper_sha256="sha256:" + "4" * 64), "record"),
    ({**credential(), "token_sha256": "0" * 64}, "record"),
    ({**credential(), "schema": "urn:zeus:other:1"}, "record"),
    (credential(entry={"secret": SENTINEL}), "entry"),
    ("PRIMARY", "record"),
])
def test_credential_evidence_is_strict_and_identity_bound(record, field):
    with pytest.raises(DeliveryRefused) as refused:
        validate_credential_evidence(record, LIVE)
    assert (refused.value.reason_code, refused.value.field) == ("maintenance_primary_unverified", field)
    assert SENTINEL not in str(refused.value)


def test_a_bound_primary_record_is_returned_as_booleans_and_ids_only():
    checked = validate_credential_evidence(credential(), LIVE)
    assert checked == credential()
    assert set(checked) == {"schema", "observed_at", "invocation_id", "helper_sha256", "supervisor", "entry"}


# ----- readiness, the view and the legacy projection ------------------------------------------------------
READY = {"registered": True, "paused": True, "owner_paused": True, "activation_hold": False, "reserving": [],
         "units_held": [], "open_permits": []}


@pytest.mark.parametrize("readiness,expected", [
    (READY, None),
    ({**READY, "open_permits": ["mid"]}, None),
    ({**READY, "reserving": ["own-job"]}, None),
    (None, ("maintenance_debt_unsettled", "fleet")),
    ({**READY, "registered": False}, ("maintenance_debt_unsettled", "fleet")),
    ({**READY, "owner_paused": False}, ("maintenance_pause_required", "fleet")),
    ({**READY, "activation_hold": True}, ("maintenance_pause_required", "fleet")),
    ({**READY, "reserving": ["another-job"]}, ("maintenance_debt_unsettled", "fleet")),
    ({**READY, "units_held": ["conductor"]}, ("maintenance_debt_unsettled", "fleet")),
    ({**READY, "open_permits": ["another-maintenance"]}, ("maintenance_debt_unsettled", "fleet")),
    ({**READY, "reserving": None}, ("maintenance_debt_unsettled", "fleet")),
])
def test_fleet_readiness_needs_the_owner_pause_and_settled_debt(readiness, expected):
    assert fleet_ready_refusal(readiness, maintenance_id="mid", own_job_id="own-job") == expected


def test_maintenance_view_is_an_allowlist():
    planted = {"id": "active_generation_1:" + "0" * 64, "state": "armed", "requested_at": "t0", "updated_at": "t1",
               "document": {"approved_by": SENTINEL}, "evidence_ref": "sha256:" + "0" * 64,
               "retiring": {"instance_id": OLD_INSTANCE, "invocation_id": OLD_INVOCATION, "note": SENTINEL,
                            "observed": {"path": "/" + SENTINEL}, "selection": {"env": SENTINEL}},
               "prior": {"startup_receipt": receipt(runtime_root="/" + SENTINEL)},
               "launched": {"invocation_id": NEW_INVOCATION, "launch": {"path": SENTINEL},
                            "receipt": {"instance_id": NEW_INSTANCE, "runtime_root": "/" + SENTINEL}},
               "credential_evidence": [{"helper": SENTINEL}],
               "arm": {"deadline": "t9", "permit": {"note": SENTINEL}, "control": {"state": "acknowledged",
                                                                                   "note": SENTINEL},
                       "dispatch": {"state": "finished", "note": SENTINEL}},
               "canary": None, "failure": None, "observations": [{"field": SENTINEL}]}
    view = maintenance_view(planted)
    assert SENTINEL not in json.dumps(view)
    assert view == {"maintenance_id": planted["id"], "state": "armed", "open": True, "qualified": False,
                    "requested_at": "t0", "updated_at": "t1",
                    "retiring": {"instance_id": OLD_INSTANCE, "invocation_id": OLD_INVOCATION},
                    "new": {"instance_id": NEW_INSTANCE, "invocation_id": NEW_INVOCATION}, "deadline": "t9",
                    "admission": "acknowledged", "dispatch": "finished", "canary": None, "failure": None,
                    "evidence_ref": planted["evidence_ref"], "next_phase": "bind"}
    assert maintenance_view({**planted, "state": "failed", "failure": {"code": "maintenance_expired", "at": "t"}})[
        "next_phase"] == "owner_review"
    assert maintenance_view(None) is None


def test_legacy_projection_is_unchanged_without_generations():
    plan = {"plan_id": "p1", "release_id": "r1", "target_id": "t", "revision": "a" * 40,
            "required_checks": ["ci"], "canary_check_id": "fleet_worker_operation"}
    row = {"plan": plan, "plan_sha256": "1" * 64, "pin": {"revision": "f" * 40, "path": "a.json", "sha256": "2" * 64}}
    intent = {"stage": ACTIVE, "outcome": "active", "instance_id": OLD_INSTANCE, "updated_at": "t"}
    legacy = delivery_progress(row, intent, None)
    assert "maintenance" not in legacy
    assert canonical(delivery_progress(row, {**intent, "generations": []}, None)) == canonical(legacy)
    maintained = delivery_progress(row, {**intent, "generations": [generation("started")]}, None)
    assert maintained["maintenance"]["open"] is True and maintained["maintenance"]["qualified"] is False
    assert {k: v for k, v in maintained.items() if k != "maintenance"} == legacy
    assert copy.deepcopy(legacy) == delivery_progress(row, intent, None)
