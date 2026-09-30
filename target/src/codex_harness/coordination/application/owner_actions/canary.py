"""G2 owner canary and its typed recovery.

Layer: application
Context: coordination
Owns: no bucket of its own (owner_actions through ActionStore)
Does not own: the canary job (Fleet), the target files (targets), the lane's HostDelivery (S7)
Entry points: CanaryFamily
Contracts: INV-OWNER-ACTIONS-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

import copy
from datetime import datetime

from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_POLICIES,
    FLEET_ADMISSION,
    FLEET_CONTROL,
    FLEET_JOBS,
    _job_snapshot,
    _request_of,
)
from codex_harness.coordination.domain.owner_actions import (
    CANARY_REARM_KIND,
    CANARY_RECOVERY_HALT_REASON,
    CANARY_RECOVERY_KIND,
    COMPLETED,
    DELIVERY_CANARY,
    DELIVERY_PLAN,
    EVIDENCE_REF,
    INTENDED,
    LANE_REARM_KIND,
    LANE_RETRY_KIND,
    REFUSED,
    REJECTED,
    REQUESTED,
    UNKNOWN,
    VERDICT_ACCEPTED,
    VERDICT_UNKNOWN,
    OwnerActionRefused,
    canary_binding,
    canary_job_id,
    canary_manifest,
    canary_outcome,
    canary_receipt,
    linked_restart,
    rearm_owed_canary,
    recovered_canary,
    restart_owed_canary,
    validate_canary_recovery,
    view,
)
from codex_harness.delivery.domain.host_delivery import (
    AWAITING_CONSUMPTION,
    TERMINAL_STAGES,
    consumption_verdict,
)
from codex_harness.kernel.ids import digest, utcnow


class CanaryFamily:
    """G2: the owner's actual canary of a registered fleet-canary plan, and its typed recovery."""

    def __init__(self, store, *, clock=utcnow, deliveries=None, fleet=None, lanes=None, org=None,
                 targets=None, validate=None, actions=None):
        self.store = store
        self.clock = clock
        self.deliveries = deliveries
        self.fleet = fleet
        self.lanes = lanes
        self.org = org
        self.targets = targets
        self.validate = validate
        self.actions = actions

    # ===== G2: the owner's actual canary ===========================================================
    def delivery_view(self, plan_action: dict) -> tuple:
        lane, plan = plan_action["subject"]["lane"], plan_action["plan"]
        delivery = self.deliveries(lane)
        with delivery.store.transaction() as tx:
            return (tx.get("host_delivery_intents", plan["plan_id"]),
                    tx.get("host_delivery_targets", plan["target_id"]))

    def refile_request(self, plan_action: dict) -> None:
        """Keep a registered plan's OWN canary request filed while its delivery is open.

        This is the explicit compatibility path for plans registered while the request was one
        target-global file, where a later registration replaced it (the actual own-a98e.../own-fe54...
        state). The document is exactly the one `_register` filed, rebuilt from the immutable action
        row; nothing is written when it is already there, for a finished or foreign delivery, or to
        the former global file, and no action row changes."""
        if self.deliveries is None or self.targets is None:
            return
        intent, target = self.delivery_view(plan_action)
        if not isinstance(target, dict) or (isinstance(intent, dict) and (
                intent.get("stage") in TERMINAL_STAGES or intent.get("plan_sha256") != plan_action["plan_sha256"])):
            return
        document = _request_of(plan_action)
        if self.targets.request(target, plan_action["plan_id"]) != document:
            self.targets.write_request(target, plan_action["plan_id"], document)

    def restart_owed(self, plan_action: dict, actions: list) -> bool:
        """True while a linked lane restart, or the lane's ONE consumption re-arm, leaves this plan's halted canary
        owed its typed recovery (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended)."""
        intent, _target = self.delivery_view(plan_action)
        restart = linked_restart(intent)
        return any((restart_owed_canary(a, restart) or rearm_owed_canary(a, intent))
                   and (a.get("binding") or {}).get("plan_id") == plan_action["plan_id"]
                   and (a.get("binding") or {}).get("plan_sha256") == plan_action["plan_sha256"] for a in actions)

    def canary_binding(self, plan_action: dict) -> dict | None:
        """Owed once the delivery of exactly this plan awaits consumption and its candidate instance has
        reported the switched descriptor; the binding names that instance."""
        if self.deliveries is None or self.targets is None:
            return None
        intent, target = self.delivery_view(plan_action)
        if not (isinstance(intent, dict) and intent.get("stage") == AWAITING_CONSUMPTION
                and intent.get("plan_sha256") == plan_action["plan_sha256"] and isinstance(target, dict)
                and isinstance(intent.get("descriptor"), dict)):
            return None
        verdict = consumption_verdict(intent["descriptor"], self.targets.startup(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if not verdict["consumed"]:
            return None
        return canary_binding(plan_action, intent, verdict["instance_id"])

    def advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        policy = policy_row["policy"]
        if self.fleet is None or self.lanes is None:
            raise OwnerActionRefused("canary_ports_unconfigured", "fleet")
        if action["state"] not in {INTENDED, REQUESTED}:
            return None
        with self.store.transaction() as tx:
            job = tx.get(FLEET_JOBS, action["job_id"]) if action["state"] == REQUESTED else None
            plan_action = next((r for r in tx.scan(BUCKET_ACTIONS) if r["kind"] == DELIVERY_PLAN
                                and r.get("plan_id") == action["binding"]["plan_id"]), None)
        if job is None and not self.still_bound(plan_action, action):
            # R2: a persisted intent whose plan, delivery, descriptor or candidate instance moved on
            # (deadline, rollback, replaced instance) admits no work, neither first nor on replay.
            return self.actions.effect(self.actions.move(action, REFUSED, "canary_delivery_moved"))
        if action["state"] == INTENDED:
            job_id = canary_job_id(action["id"])
            manifest = canary_manifest(policy, job_id)
            if self.validate is not None:
                manifest = self.validate(manifest)
            row = self.actions.move(action, REQUESTED, "canary_requested", job_id=job_id)
            self.fleet.enqueue(policy["canary"]["lane"], manifest, dict(policy["canary"]["goal"]), [])
            return self.actions.effect(row)
        if job is None:
            # The admission's response was lost before the row existed: the same id admits once.
            manifest = canary_manifest(policy, action["job_id"])
            self.fleet.enqueue(policy["canary"]["lane"], self.validate(manifest) if self.validate else manifest,
                               dict(policy["canary"]["goal"]), [])
            return None
        if not self.still_bound(plan_action, action):
            return self.actions.effect(self.actions.move(action, UNKNOWN, "canary_delivery_moved"))
        outcome = canary_outcome(job, self.lanes(job["lane"]).read(job) if job.get("status") not in {
            "queued", "dispatching"} else None)
        if outcome["state"] in {"running", "absent"}:
            return None
        if outcome["state"] == VERDICT_UNKNOWN:
            # No receipt: the delivery's own deadline rolls it back; the unknown effect stays named.
            return self.actions.effect(self.actions.move(action, UNKNOWN, outcome["reason_code"]))
        _, target = self.delivery_view(plan_action)
        self.targets.write_receipt(target, action["binding"]["plan_id"], canary_receipt(action, outcome, self.clock()))
        target_state = COMPLETED if outcome["state"] == VERDICT_ACCEPTED else REJECTED
        return self.actions.effect(self.actions.move(action, target_state, outcome["reason_code"],
                                       outcome={k: outcome.get(k) for k in ("state", "reason_code", "evidence")}))

    def still_bound(self, plan_action, action: dict) -> bool:
        """The same published plan's delivery still awaits consumption of the same descriptor and the SAME
        candidate instance is the one reporting it: work is admitted and an answer is written only for the
        instance it was taken against (R2 at admission, the result gate after it)."""
        binding = action["binding"]
        if plan_action is None or plan_action.get("plan_sha256") != binding["plan_sha256"]:
            return False
        intent, target = self.delivery_view(plan_action)
        if not (isinstance(intent, dict) and intent.get("stage") == AWAITING_CONSUMPTION
                and intent.get("plan_sha256") == binding["plan_sha256"]
                and intent.get("target_id") == binding["target_id"]
                and intent.get("descriptor_sha256") == binding["descriptor_sha256"] and isinstance(target, dict)):
            return False
        receipt = self.targets.startup(target)
        return isinstance(receipt, dict) and receipt.get("instance_id") == binding["instance_id"] \
            and receipt.get("descriptor_sha256") == binding["descriptor_sha256"]

    # ===== the typed owner canary recovery (INV-OWNER-ACTIONS-001, INV-HOST-DELIVERY-FIRST-ACTIVATION-001) ==
    # The OWNER half of the lane `first_activation_consumption_retry`. The lane retry re-arms the SAME
    # observed instance's consumption, but the REQUESTED canary was already moved to UNKNOWN
    # `canary_delivery_moved` by `_advance_canary`'s result gate, the tick skips UNKNOWN and discovery
    # dedupes the same binding: without this use case no owner receipt is ever written. It is ONE typed
    # control-store use case, not a generic UNKNOWN retry: `TRANSITIONS` is unchanged, the Fleet job is
    # never touched, and the lane store is only READ (there is NO cross-store transaction).
    def recover_canary(self, document, evidence_ref: str) -> dict:
        """Return exactly one halted canary action to REQUESTED under the SAME still-queued job.

        `evidence_ref` is `"sha256:" + digest(document)`. A read-only preflight first (each failure a
        named `OwnerActionRefused` with no write): the action (kind, UNKNOWN `canary_delivery_moved`
        from REQUESTED, version, exact binding and digest, policy row and pin, `canary_job_id`, no prior
        recovery); the Fleet job in this control store (same id/lane/operation, `queued`, never
        dispatched, no calls, execution, lease, attempt or evidence) and the paused Fleet; no canary
        receipt already written for the plan; the LANE through the `deliveries(lane)` port, READ ONLY
        (`awaiting_consumption`, its LATEST recovery the named consumption retry of the same instance and
        descriptor, `_canary_still_bound`, and at least `margin_seconds` left before the lane deadline);
        and a conductor approver who is not the candidate author. Then ONE control-store transaction
        compare-and-swaps the action row, the job snapshot, the Fleet control row and the policy row, and
        writes REQUESTED `canary_recovered` with the recovery appended. The lane may still change after
        that read: the existing `_advance_canary` result gate re-checks `_canary_still_bound` before any
        receipt, so a moved lane becomes UNKNOWN again with no work written. The same evidence answers
        `cached` at any later state; other evidence is `canary_recovery_conflict` (one per action)."""
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise OwnerActionRefused("canary_recovery_evidence_invalid", "evidence")
        recovery_doc = validate_canary_recovery(document)
        document_sha256 = digest(recovery_doc)
        if evidence_ref != "sha256:" + document_sha256:
            raise OwnerActionRefused("canary_recovery_evidence_mismatch", "evidence")
        with self.store.transaction() as tx:
            action = tx.get(BUCKET_ACTIONS, recovery_doc["action_id"])
            policy_row = tx.get(BUCKET_POLICIES, recovery_doc["policy_id"])
            job = tx.get(FLEET_JOBS, recovery_doc["job_id"])
            control = tx.get(FLEET_CONTROL, FLEET_ADMISSION)
            plan_action = None if not isinstance(action, dict) else next(
                (r for r in tx.scan(BUCKET_ACTIONS) if r["kind"] == DELIVERY_PLAN
                 and r.get("plan_id") == (action.get("binding") or {}).get("plan_id")), None)
        if not isinstance(action, dict) or action.get("kind") != DELIVERY_CANARY:
            raise OwnerActionRefused("canary_recovery_action_missing", "action_id")
        cached = self._recovery_replay(action, evidence_ref, recovery_doc["kind"])
        if cached is not None:
            return cached
        self._recovery_action(action, recovery_doc, policy_row)
        self._recovery_job(action, recovery_doc, policy_row, job, control)
        lane = self._recovery_lane(plan_action, action, recovery_doc)
        now = self.clock()
        recovery = {"kind": recovery_doc["kind"], "evidence_ref": evidence_ref, "document_sha256": document_sha256,
                    "approved_by": recovery_doc["approved_by"],
                    "halted": {"state": action["state"], "reason_code": action["reason_code"],
                               "updated_at": action["updated_at"], "version": action["version"]},
                    "job_snapshot": _job_snapshot(job), "lane": {k: v for k, v in lane.items() if k != "rebound"},
                    **({"rebound": lane["rebound"]} if "rebound" in lane else {}), "at": now}
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_ACTIONS, action["id"])
            if isinstance(current, dict) and any(r.get("evidence_ref") == evidence_ref
                                                 for r in current.get("recoveries") or []):
                written = None
            else:
                if current != action:
                    raise OwnerActionRefused("canary_recovery_action_changed", "action_version")
                if tx.get(FLEET_JOBS, job["id"]) != job:
                    raise OwnerActionRefused("canary_recovery_job_changed", "job_id")
                if tx.get(FLEET_CONTROL, FLEET_ADMISSION) != control:
                    raise OwnerActionRefused("canary_recovery_fleet_changed", "fleet")
                if tx.get(BUCKET_POLICIES, policy_row["id"]) != policy_row:
                    raise OwnerActionRefused("canary_recovery_policy_changed", "policy_sha256")
                written = recovered_canary(copy.deepcopy(current), recovery, now)
                tx.put(BUCKET_ACTIONS, written["id"], written)
        if written is None:
            return self._recovery_replay(current, evidence_ref)
        return {"recovered": True, "cached": False, "action_id": written["id"], "state": written["state"],
                "reason_code": written["reason_code"], "version": written["version"], "job_id": written["job_id"],
                "evidence_ref": evidence_ref, "recovery": view(written)["recoveries"][-1]}

    @staticmethod
    def _recovery_replay(action: dict, evidence_ref: str, kind: str = CANARY_RECOVERY_KIND) -> dict | None:
        """One recovery of each typed kind per action: the same evidence is `cached` at any later state; other
        evidence is a named conflict. The re-arm kind (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended) follows
        EXACTLY one retry-kind recovery and never repeats."""
        recorded = [r for r in action.get("recoveries") or [] if isinstance(r, dict)]
        if any(r.get("evidence_ref") == evidence_ref for r in recorded):
            return {"recovered": True, "cached": True, "action_id": action["id"], "state": action["state"],
                    "reason_code": action["reason_code"], "version": action["version"],
                    "job_id": action.get("job_id"), "evidence_ref": evidence_ref,
                    "recovery": next(r for r in view(action)["recoveries"] if r.get("evidence_ref") == evidence_ref)}
        if kind == CANARY_REARM_KIND and [r.get("kind") for r in recorded] == [CANARY_RECOVERY_KIND]:
            return None
        if not recorded:
            if kind == CANARY_REARM_KIND:
                raise OwnerActionRefused("canary_recovery_not_applicable", "recoveries")
            return None
        if recorded[-1].get("evidence_ref") != evidence_ref:
            raise OwnerActionRefused("canary_recovery_conflict", "evidence")
        return {"recovered": True, "cached": True, "action_id": action["id"], "state": action["state"],
                "reason_code": action["reason_code"], "version": action["version"], "job_id": action.get("job_id"),
                "evidence_ref": evidence_ref, "recovery": view(action)["recoveries"][-1]}

    @staticmethod
    def _recovery_action(action: dict, document: dict, policy_row) -> None:
        """The stored action is exactly the halted one the document names."""
        if action["state"] != UNKNOWN or action.get("reason_code") != CANARY_RECOVERY_HALT_REASON:
            raise OwnerActionRefused("canary_recovery_not_applicable", "state")
        history = [h for h in action.get("history") or [] if isinstance(h, dict)]
        if len(history) < 2 or history[-1].get("state") != UNKNOWN \
                or history[-1].get("reason_code") != CANARY_RECOVERY_HALT_REASON \
                or history[-2].get("state") != REQUESTED:
            raise OwnerActionRefused("canary_recovery_not_from_requested", "history")
        if action.get("version") != document["action_version"]:
            raise OwnerActionRefused("canary_recovery_version_mismatch", "action_version")
        halt = {"state": action["state"], "reason_code": action["reason_code"], "updated_at": action.get("updated_at")}
        if document["halt"] != halt:
            raise OwnerActionRefused("canary_recovery_halt_mismatch", "halt")
        if document["binding"] != action.get("binding") or document["binding_sha256"] != action.get("binding_sha256") \
                or digest(action.get("binding")) != document["binding_sha256"]:
            raise OwnerActionRefused("canary_recovery_binding_mismatch", "binding")
        if not isinstance(policy_row, dict) or action.get("policy_id") != document["policy_id"]:
            raise OwnerActionRefused("canary_recovery_policy_mismatch", "policy_id")
        if not (policy_row.get("policy_sha256") == action.get("policy_sha256") == document["policy_sha256"]):
            raise OwnerActionRefused("canary_recovery_policy_mismatch", "policy_sha256")
        if action.get("job_id") != canary_job_id(action["id"]) or document["job_id"] != action.get("job_id"):
            raise OwnerActionRefused("canary_recovery_job_mismatch", "job_id")

    def _recovery_job(self, action: dict, document: dict, policy_row: dict, job, control) -> None:
        """The SAME Fleet job, admitted but never dispatched, under a paused Fleet (control store)."""
        if not isinstance(job, dict):
            raise OwnerActionRefused("canary_recovery_job_missing", "job_id")
        lane = ((policy_row.get("policy") or {}).get("canary") or {}).get("lane")
        if job.get("id") != action["job_id"] or job.get("operation_id") != action["job_id"] or job.get("lane") != lane:
            raise OwnerActionRefused("canary_recovery_job_mismatch", "job_id")
        if job.get("status") != "queued":
            raise OwnerActionRefused("canary_recovery_job_" + str(job.get("status")), "job_id")
        if job.get("reason_code") not in {None, "paused"}:
            raise OwnerActionRefused("canary_recovery_job_reason", "job_id")
        if job.get("calls") != {"reserved": None, "settled": None}:
            raise OwnerActionRefused("canary_recovery_job_calls", "job_id")
        if any(job.get(key) for key in ("dispatched_at", "finished_at", "owner_token", "receipt", "exit_code",
                                        "error_type", "execution", "execution_ref", "lease", "lease_until",
                                        "attempt", "attempts", "evidence")):
            raise OwnerActionRefused("canary_recovery_job_started", "job_id")
        if not (isinstance(control, dict) and control.get("paused") is True):
            raise OwnerActionRefused("canary_recovery_fleet_not_paused", "fleet")

    def _recovery_lane(self, plan_action, action: dict, document: dict) -> dict:
        """The lane, READ ONLY through `deliveries(lane)`: the retried delivery of the same instance."""
        if self.deliveries is None or self.targets is None:
            raise OwnerActionRefused("canary_recovery_ports_unconfigured", "deliveries")
        binding = action["binding"]
        if not isinstance(plan_action, dict) or plan_action.get("plan_sha256") != binding["plan_sha256"]:
            raise OwnerActionRefused("canary_recovery_plan_missing", "plan_id")
        delivery = self.deliveries(plan_action["subject"]["lane"])
        with delivery.store.transaction() as tx:
            intent = tx.get("host_delivery_intents", binding["plan_id"])
            target = tx.get("host_delivery_targets", binding["target_id"])
            record = tx.get("releases", (plan_action.get("plan") or {}).get("release_id") or "")
        if not (isinstance(intent, dict) and intent.get("stage") == AWAITING_CONSUMPTION):
            raise OwnerActionRefused("canary_recovery_lane_not_awaiting", "stage")
        retry = ((intent.get("recoveries") or [None])[-1]) or {}
        rearm = document["kind"] == CANARY_REARM_KIND
        if rearm:
            # the lane's ONE re-arm, named by the document, of the EXPLICIT window the document binds
            if retry.get("kind") != LANE_REARM_KIND or retry.get("evidence_ref") != document["lane_rearm_evidence"]:
                raise OwnerActionRefused("canary_recovery_lane_not_rearmed", "lane_rearm_evidence")
            if retry.get("window_seconds") != document["lane_window_seconds"]:
                raise OwnerActionRefused("canary_recovery_lane_window_mismatch", "lane_window_seconds")
        elif retry.get("kind") != LANE_RETRY_KIND or retry.get("evidence_ref") != document["lane_retry_evidence"]:
            raise OwnerActionRefused("canary_recovery_lane_not_retried", "lane_retry_evidence")
        observed = retry.get("observed") or {}
        rebound = None
        if rearm and observed.get("observed_instance_id") != binding["instance_id"]:
            # the re-arm never re-binds: the retry already bound this action to the instance it observes
            raise OwnerActionRefused("canary_recovery_instance_mismatch", "instance_id")
        if observed.get("observed_instance_id") != binding["instance_id"]:
            # Only an EXPLICITLY linked lane restart of exactly this binding's instance moves the binding.
            restart = linked_restart(intent)
            if restart is None or restart["stopped_instance_id"] != binding["instance_id"] \
                    or restart["started_instance_id"] != observed.get("observed_instance_id"):
                raise OwnerActionRefused("canary_recovery_instance_mismatch", "instance_id")
            rebound = {"binding": {**binding, "instance_id": restart["started_instance_id"]},
                       "from_instance_id": binding["instance_id"], "to_instance_id": restart["started_instance_id"],
                       "restart_evidence": restart["evidence_ref"], "previous_binding_sha256": action["binding_sha256"]}
        if observed.get("descriptor_sha256") != binding["descriptor_sha256"]:
            raise OwnerActionRefused("canary_recovery_descriptor_mismatch", "descriptor_sha256")
        bound = action if rebound is None else {**action, "binding": rebound["binding"]}
        if not self.still_bound(plan_action, bound):
            raise OwnerActionRefused("canary_recovery_delivery_moved", "binding")
        reader = getattr(self.targets, "receipt", None)
        if reader is None:
            raise OwnerActionRefused("canary_recovery_receipt_unobservable", "targets")
        if reader(target, binding["plan_id"]) is not None:
            raise OwnerActionRefused("canary_recovery_receipt_exists", "plan_id")
        try:
            remaining = (datetime.fromisoformat(intent["stage_deadline"])
                         - datetime.fromisoformat(self.clock())).total_seconds()
        except (KeyError, TypeError, ValueError):
            raise OwnerActionRefused("canary_recovery_deadline_unobservable", "stage_deadline") from None
        if remaining < document["margin_seconds"]:
            raise OwnerActionRefused("canary_recovery_margin", "margin_seconds")
        self._recovery_approver(document["approved_by"], ((record or {}).get("candidate") or {}).get("author"))
        return {**({"rearm_evidence": document["lane_rearm_evidence"], "window_seconds": document["lane_window_seconds"]}
                   if rearm else {"retry_evidence": document["lane_retry_evidence"]}),
                "stage": intent["stage"],
                "stage_deadline": intent["stage_deadline"], "instance_id": bound["binding"]["instance_id"],
                "descriptor_sha256": binding["descriptor_sha256"],
                **({"rebound": rebound} if rebound is not None else {})}

    def _recovery_approver(self, approved_by: str, author) -> None:
        """A conductor of the existing organization who is not the candidate's own author."""
        if self.org is None:
            raise OwnerActionRefused("canary_recovery_approver_unavailable", "approved_by")
        try:
            self.org.actor(approved_by, "conductor")
        except Exception as exc:
            raise OwnerActionRefused("canary_recovery_approver_invalid", "approved_by") from exc
        if approved_by == author:
            raise OwnerActionRefused("canary_recovery_approver_author", "approved_by")
