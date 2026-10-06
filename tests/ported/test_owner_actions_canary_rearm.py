"""Ported SOURCE M7 suite `tests/test_owner_actions_canary_rearm.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_coordination` and
`m7_delivery` shim docstrings name the routing): `OwnerActions` is the shim's facade over the split owner-action objects
(it also routes M7's private `_advance_canary`, `_plan_binding`, `_discover`, `_recovery_lane` and `_take_slot`, and the
one `clock`, to their split homes); `organization`, `packaged_policy`, `Workflow`, `unavailable`, `HostDelivery`,
`Releases`, `MemoryStore`, `GitPlanPublisher` (M7 `GitPlanPublisher(repository)` built through
`composition.owner_action_adapters.git_plan_publisher`, a named construction adaptation) and `TargetFiles`
(`delivery.adapters.target_files`) come from the shims; the owner-action BUCKET_* names, `CONTINUATION_BINDINGS`,
`lineage_of` and `plan_json` from `coordination.application.owner_actions.state`, the domain modules from
`coordination.domain` and `delivery.domain`, the adapter names from `delivery.adapters.host_delivery`, `digest` from
`kernel.ids`. 

M7 docstring follows.

The owner half of the ONE consumption re-arm (INV-OWNER-ACTIONS-001 x INV-HOST-DELIVERY-FIRST-ACTIVATION-001).

After the lane's one retry expired AGAIN, the SAME halted canary (same action, same still-queued job, binding already
re-bound by the retry) is recovered once more by its own typed kind, paired only with the lane's ONE
`first_activation_consumption_rearm` and its explicit window.

What is real: HostDelivery (first activation, pending-canary halts, the stopped generation, the ONE restart, the one
retry, the ONE re-arm) on its OWN store with a real process target and the incumbent `owner_qualified_canary`;
OwnerActions and the real Fleet on a SEPARATE control store. LABELLED: exactly the fixtures of
test_owner_actions_canary_recovery's end-to-end tests. Nothing here touches a production host.
"""
from __future__ import annotations

import pytest
from test_owner_actions_canary_recovery import _canaries

from codex_harness.coordination.domain import owner_actions as do
from codex_harness.kernel.ids import digest


def _recovery(canary, **extra):
    body = {"schema": do.CANARY_RECOVERY_SCHEMA, "kind": do.CANARY_RECOVERY_KIND, "action_id": canary["id"],
            "action_version": canary["version"], "binding_sha256": canary["binding_sha256"],
            "binding": dict(canary["binding"]), "policy_id": canary["policy_id"],
            "policy_sha256": canary["policy_sha256"], "job_id": canary["job_id"],
            "halt": {"state": canary["state"], "reason_code": canary["reason_code"],
                     "updated_at": canary["updated_at"]},
            "margin_seconds": 600, "approved_by": "conductor"}
    body.update(extra)
    return body


def test_the_rearm_document_grammar_is_exact():
    base = _recovery({"id": "a" * 64, "version": 3, "binding_sha256": "b" * 64,
                      "binding": {"plan_id": "p", "plan_sha256": "1" * 64, "target_id": "t", "descriptor_sha256": "2" * 64,
                                  "instance_id": "i"},
                      "policy_id": "aibox-owner-v1", "policy_sha256": "c" * 64, "job_id": "canary-x",
                      "state": do.UNKNOWN, "reason_code": do.CANARY_RECOVERY_HALT_REASON, "updated_at": "t"},
                     kind=do.CANARY_REARM_KIND, lane_rearm_evidence="sha256:" + "e" * 64, lane_window_seconds=3600)
    assert do.validate_canary_recovery(base)["lane_window_seconds"] == 3600
    for field, value in (("lane_window_seconds", 3601), ("lane_window_seconds", 0), ("lane_window_seconds", True),
                         ("lane_rearm_evidence", "sha256:x"), ("margin_seconds", 3600), ("kind", "other")):
        with pytest.raises(do.OwnerActionRefused) as caught:
            do.validate_canary_recovery({**base, field: value})
        assert caught.value.reason_code == "canary_recovery_invalid", (field, value)
    with pytest.raises(do.OwnerActionRefused):
        do.validate_canary_recovery({**base, "lane_retry_evidence": "sha256:" + "e" * 64})
    retry_kind = {k: v for k, v in base.items() if k not in ("lane_rearm_evidence", "lane_window_seconds")}
    with pytest.raises(do.OwnerActionRefused):
        do.validate_canary_recovery({**retry_kind, "kind": do.CANARY_RECOVERY_KIND})   # no lane_retry_evidence
    assert do.MAX_REARM_WINDOW == 3600


def test_after_the_retry_expires_again_the_same_canary_is_rearmed_once_and_the_delivery_is_consumed(tmp_path,
                                                                                                    monkeypatch):
    from test_host_delivery import (
        PROFILE,
        await_receipt,
        build,
        drive,
        intent_of,
        register_historical,
        stop_target,
    )
    from test_host_delivery_consumption_rearm import rearm, rearm_document
    from test_host_delivery_consumption_retry import document as retry_document
    from test_host_delivery_consumption_retry import retry
    from test_host_delivery_first_activation import IMAGE_ID, CountingVerifier, FixedFacts
    from test_host_delivery_first_activation import document as binding_document
    from test_host_delivery_generation_restart import restart, restart_document
    from test_owner_delivery import canary_owner

    from codex_harness.delivery.adapters.host_delivery import owner_qualified_canary
    from codex_harness.delivery.adapters.target_files import TargetFiles
    from codex_harness.delivery.domain.host_delivery import (
        ACTIVE,
        AWAITING_CONSUMPTION,
        BLOCKED,
        CANARY_FLEET,
        CANARY_REQUEST_SCHEMA,
        CONSUMPTION_RETRY_RESTART_FIELD,
        MERGED,
        UNCHANGED,
        plan_digest,
        validate_plan,
    )

    monkeypatch.setenv("ZEUS_WORKER_IMAGE", IMAGE_ID)
    system = build(tmp_path / "delivery", plan_overrides={"image": UNCHANGED, "profile": UNCHANGED,
                                                          "canary": CANARY_FLEET, "consumption_timeout": 900},
                   register_plan=False, canaries={CANARY_FLEET: owner_qualified_canary})
    try:
        register_historical(system)
        drive(system, until=MERGED, limit=8)
        assert system["delivery"].tick()["reason_code"] == "unchanged_without_predecessor"
        system["delivery"].first_activation = FixedFacts(profile=PROFILE)
        system["verifier"] = CountingVerifier()
        system["delivery"].verifier = system["verifier"]
        body, evidence = binding_document(system, profile_digest=PROFILE)
        system["delivery"].resume_first_activation(system["plan"]["plan_id"], body["plan_sha256"], body, evidence)
        system["binding_evidence"] = evidence
        plan = validate_plan(system["plan"])
        TargetFiles.write_request(system["target"], plan["plan_id"], {
            "schema": CANARY_REQUEST_SCHEMA, "action_id": "a" * 64, "plan_id": plan["plan_id"],
            "plan_sha256": plan_digest(plan), "target_id": plan["target_id"],
            "revision": plan["target_descriptor"]["revision"], "expected_descriptor": plan["expected_descriptor"],
            "requested_at": system["clock"]()})
        drive(system, until=AWAITING_CONSUMPTION, limit=40)
        await_receipt(system["target"], intent_of(system)["descriptor_sha256"], timeout=30.0)
        world, owner = canary_owner(tmp_path, system)
        owner.clock = system["clock"]
        world.fleet.pause()
        owner.tick("owners-1")
        [canary] = _canaries(world)
        system["clock"].advance(900)
        assert drive(system, until=ACTIVE, limit=40)[-1]["reason_code"] == "no_known_good_predecessor"
        owner.tick("owners-1")
        [canary] = _canaries(world)
        stop_target(system)   # the host restart
        restart_body, restart_evidence = restart_document(system)
        restart(system, restart_body, restart_evidence)
        new = intent_of(system)["recoveries"][-1]["started"]["instance_id"]
        retry_body, retry_evidence = retry_document(system, observed_instance_id=new,
                                                    **{CONSUMPTION_RETRY_RESTART_FIELD: restart_evidence})
        retry(system, retry_body, retry_evidence)
        first = _recovery(canary, lane_retry_evidence=retry_evidence)
        owner.recover_canary(first, "sha256:" + digest(first))
        [recovered] = _canaries(world)
        assert recovered["binding"]["instance_id"] == new
        # the ordinary tick records the new generation's startup; the Fleet never resumed: the window expires AGAIN
        system["clock"].advance(900)
        second = drive(system, until=ACTIVE, limit=40)[-1]
        assert (second["stage"], second["reason_code"]) == (BLOCKED, "no_known_good_predecessor"), second
        owner.tick("owners-1")
        [halted] = _canaries(world)
        assert (halted["state"], halted["reason_code"]) == (do.UNKNOWN, "canary_delivery_moved")
        jobs_before = dict(world.jobs())
        # the owner's rearm before the lane's is refused, nothing written
        early = _recovery(halted, kind=do.CANARY_REARM_KIND, lane_rearm_evidence="sha256:" + "9" * 64,
                          lane_window_seconds=3600)
        with pytest.raises(do.OwnerActionRefused) as caught:
            owner.recover_canary(early, "sha256:" + digest(early))
        assert caught.value.reason_code == "canary_recovery_lane_not_awaiting"
        # the lane's ONE re-arm (explicit 3600 s window) of the SAME instance, linked to the restart
        lane_body, lane_evidence = rearm_document(system, **{CONSUMPTION_RETRY_RESTART_FIELD: restart_evidence})
        rearm(system, lane_body, lane_evidence)
        lane_record = intent_of(system)["recoveries"][-1]
        assert lane_record["window_seconds"] == 3600 and lane_record["observed"]["observed_instance_id"] == new
        owner.tick("owners-1")
        assert len(_canaries(world)) == 1 and world.jobs() == jobs_before, "no second canary, no new job"
        # a second retry-kind recovery conflicts; a document naming another window refuses; nothing is written
        again = _recovery(halted, lane_retry_evidence=retry_evidence)
        with pytest.raises(do.OwnerActionRefused) as caught:
            owner.recover_canary(again, "sha256:" + digest(again))
        assert caught.value.reason_code == "canary_recovery_conflict"
        short = _recovery(halted, kind=do.CANARY_REARM_KIND, lane_rearm_evidence=lane_evidence,
                          lane_window_seconds=900)
        with pytest.raises(do.OwnerActionRefused) as caught:
            owner.recover_canary(short, "sha256:" + digest(short))
        assert caught.value.reason_code == "canary_recovery_lane_window_mismatch"
        assert _canaries(world) == [halted]
        rearmed = _recovery(halted, kind=do.CANARY_REARM_KIND, lane_rearm_evidence=lane_evidence,
                            lane_window_seconds=3600)
        receipt = owner.recover_canary(rearmed, "sha256:" + digest(rearmed))
        assert receipt["state"] == do.REQUESTED and receipt["job_id"] == canary["job_id"]
        [done] = _canaries(world)
        assert done["id"] == canary["id"] and done["binding"] == recovered["binding"], "same action, same binding"
        assert [r["kind"] for r in done["recoveries"]] == [do.CANARY_RECOVERY_KIND, do.CANARY_REARM_KIND]
        assert done["recoveries"][-1]["lane"]["window_seconds"] == 3600
        assert world.jobs() == jobs_before, "the SAME job, never re-enqueued"
        # the independent gates would resume the Fleet here; the canary runs and the delivery is consumed
        world.fleet.resume()
        job, outcome = world.run_next(verdict=True)
        assert job == canary["job_id"] and outcome["status"] == "accepted"
        owner.tick("owners-1")
        [final] = _canaries(world)
        assert final["state"] == do.COMPLETED
        written = TargetFiles.receipt(system["target"], plan["plan_id"])
        assert written["passed"] is True and written["instance_id"] == new
        assert drive(system, until=ACTIVE, limit=40)[-1]["stage"] == ACTIVE
        assert owner.recover_canary(rearmed, "sha256:" + digest(rearmed))["cached"] is True
        assert owner.recover_canary(first, "sha256:" + digest(first))["cached"] is True
    finally:
        stop_target(system)
