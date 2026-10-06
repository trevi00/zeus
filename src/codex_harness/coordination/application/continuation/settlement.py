"""The conductor launch and its proof-only settlement.

Layer: application
Context: coordination
Owns: no bucket of its own (the intent move inside
    the Fleet unit's transaction)
Does not own: the Fleet unit (AdmissionControl), the guardian (ConductorLauncher)
Entry points: LaunchSettlement
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import (
    BUCKET_INTENTS,
    FLEET_JOBS,
    IntentChanged,
    guarded,
)
from codex_harness.coordination.domain.continuation import (
    AWAITING_OWNER,
    COMPLETED,
    CONDUCTOR,
    DISPATCHED,
    LAUNCH_ABSENT,
    LAUNCH_EXITED,
    LAUNCH_RUNNING,
    LAUNCH_TIMEOUT,
    LAUNCH_UNKNOWN,
    RECOVERY,
    RECOVERY_REQUIRED,
    RETURNED,
    ROUTE_OWNERS,
    TICK_SCHEMA,
    ContinuationRefused,
    launch_id,
    refuse,
)
from codex_harness.coordination.domain.fleet import UNIT_CONDUCTOR, FleetRefused


class LaunchSettlement:
    """The conductor launch: the Fleet unit reserved with the intent move before the guardian
    spawn, and its settlement only on the guardian's proof (admission closed drains only this)."""

    def __init__(self, store, *, conductor=None, fleet=None, lanes=None, frames=None, intents=None):
        self.store = store
        self.conductor = conductor
        self.fleet = fleet
        self.lanes = lanes
        self.frames = frames
        self.intents = intents

    def drain(self, policy_id: str) -> dict:
        """Admission closed (graceful stop, host pause, changed or unreadable pin): only launches
        already started are polled and settled under their original binding. Nothing new is bound,
        admitted or started, and with nothing dispatched this reads no lane and writes nothing."""
        result = {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "draining", "actions": [],
                  "skipped": [], "reason_code": None}
        with self.store.transaction() as tx:
            dispatched = [row for row in tx.scan(BUCKET_INTENTS)
                          if row.get("policy_id") == policy_id and row["state"] == DISPATCHED]
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)} if dispatched else {}
        for intent in sorted(dispatched, key=lambda r: (str(r.get("created_at")), r["id"])):
            guarded(result, intent["id"], lambda i=intent: self.reconcile_launch(i, jobs))
        return result

    def dispatch(self, ctx, intent: dict, job: dict) -> dict | None:
        """Guard, then ONE Fleet transaction reserves the shared execution unit and commits the
        launch identity with its token (`dispatched`) BEFORE the guardian is spawned, then the start
        returns without waiting for the decision. No local count authorizes it; a full fleet refuses
        (`conductor_capacity`) and the intent stays. A failed or lost start response is not retried
        here: reconciliation of this same launch identity decides whether a guardian entered."""
        if self.conductor is None:
            moved = self.intents.move(intent, AWAITING_OWNER, reason_code="conductor_port_unconfigured")
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        refuse(self.fleet is not None and getattr(self.fleet, "store", None) is self.store,
               "fleet_unconfigured", "fleet")
        intent = self.frames.authorize(ctx, intent)
        sequence = int((intent.get("launch") or {}).get("sequence") or 0) + 1
        launch = {"id": launch_id(intent["id"], sequence), "sequence": sequence, "state": "starting",
                  "exit_code": None, "error_type": None}
        moved = {}

        def dispatched(tx, unit):
            moved["previous"], moved["row"] = self.intents.apply(tx, intent, DISPATCHED, {"launch": {**launch, "token": unit["token"]}})
        try:
            self.fleet.reserve_unit(launch["id"], UNIT_CONDUCTOR, intent["lane"], intent["id"], within=dispatched)
        except FleetRefused as exc:
            raise ContinuationRefused("conductor_" + exc.reason_code, "fleet", exc.field) from exc
        if "row" not in moved:
            raise IntentChanged(intent["id"])  # the reservation already committed with its intent move
        intent = moved["row"]
        self.intents.emit(moved["previous"], intent)
        launch = intent["launch"]
        try:
            started = self.conductor.start(intent["lane"], job, launch["id"], launch["token"])
        except Exception as exc:
            try:
                self.intents.note(intent, launch={**launch, "state": "start_unconfirmed", "error_type": type(exc).__name__})
            except Exception:  # the next poll reconciles the same launch identity either way
                pass
            return {"subject": intent["id"], "effect": "launch_unconfirmed", "route": CONDUCTOR,
                    "error_type": type(exc).__name__}
        pid = (started or {}).get("pid") if isinstance(started, dict) else None
        intent = self.intents.note(intent, launch={**launch, "state": "started", "pid": pid if type(pid) is int else None})
        # One non-blocking observation: a child that already finished settles in this tick.
        return self.reconcile_launch(intent, ctx["jobs"]) or {"subject": intent["id"], "effect": "conductor_started",
                                                               "route": CONDUCTOR}

    def reconcile_launch(self, intent: dict, jobs: dict) -> dict | None:
        """Observe an already started launch and settle it from the committed decision row. Needs no
        eligibility: its outcome is retained under the binding it was started with."""
        job = jobs.get(intent["origin_job"])
        refuse(job is not None, "origin_job_missing", "fleet", "origin_job")
        launch = intent.get("launch") if isinstance(intent.get("launch"), dict) else None
        if launch is None:
            # A dispatch recorded without a launch identity: the decision row alone decides, and a
            # still running row becomes recovery work, never a relaunch.
            return self._settle_conductor(intent, job, {"state": LAUNCH_EXITED, "exit_code": None})
        refuse(self.conductor is not None, "conductor_port_unconfigured", "conductor")
        observed = self.conductor.poll(intent["lane"], launch["id"])
        observed = observed if isinstance(observed, dict) else {}
        state = observed.get("state")
        if state == LAUNCH_RUNNING:
            if observed.get("owned"):
                return None
            # Supervised by a guardian this process did not start (a previous controller's): only
            # this family waits, its unit stays held; never a second start.
            raise ContinuationRefused("conductor_owner_unknown", "conductor", "launch")
        if state == LAUNCH_ABSENT:
            # The fence proves the launch never entered and never will: the unit is released with it.
            moved = self._settle(intent, observed, AWAITING_OWNER, reason_code="conductor_not_launched",
                                 launch={**launch, "state": LAUNCH_ABSENT})
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        if state in {LAUNCH_EXITED, LAUNCH_TIMEOUT} and observed.get("cleanup_confirmed") is True:
            return self._settle_conductor(intent, job, observed)
        # Exited or timed out without a confirmed parent-and-tree receipt, a guardian that ended
        # without proof, or unreadable evidence: owned debt. The decision row is not even read - a
        # succeeded decision with unknown cleanup neither completes nor frees a retry.
        reason = "conductor_cleanup_unknown" if state in {LAUNCH_EXITED, LAUNCH_TIMEOUT, LAUNCH_UNKNOWN} \
            else "conductor_launch_unknown"
        if launch.get("state") != "cleanup_unknown":
            self.intents.note(intent, emit=True, launch={**launch, "state": "cleanup_unknown"},
                       hold={"reason_code": reason, "next_owner": ROUTE_OWNERS[RECOVERY], "field": "launch"})
        raise ContinuationRefused(reason, ROUTE_OWNERS[RECOVERY], "launch")

    def _settle(self, intent, observed, target, **fields) -> dict:
        """Leave `dispatched`: the intent move and the Fleet unit's release commit together, and only
        on the observed proof. A launch recorded before shared units existed has no token, and so
        no unit to release: its intent moves alone."""
        token = (intent.get("launch") or {}).get("token")
        if not token:
            return self.intents.move(intent, target, **fields)
        moved = {}

        def settled(tx, unit):
            moved["previous"], moved["row"] = self.intents.apply(tx, intent, target, fields)
        try:
            self.fleet.settle_unit(intent["launch"]["id"], token, observed.get("proof"), within=settled)
        except FleetRefused as exc:
            raise ContinuationRefused("conductor_settlement_" + exc.reason_code, ROUTE_OWNERS[RECOVERY],
                                      exc.field) from exc
        if "row" not in moved:
            raise IntentChanged(intent["id"])  # already settled together with its intent
        self.intents.emit(moved["previous"], moved["row"])
        return moved["row"]

    def _settle_conductor(self, intent, job, observed) -> dict | None:
        evidence = self.lanes(intent["lane"]).read(job)
        conductor = evidence.get("conductor") or {}
        status = conductor.get("status")
        fields = {}
        if isinstance(intent.get("launch"), dict):
            exit_code = observed.get("exit_code")
            fields["launch"] = {**intent["launch"], "state": observed.get("state"),
                                "exit_code": exit_code if type(exit_code) is int else None}
            if fields["launch"]["state"] is None:
                fields["launch"]["state"] = LAUNCH_EXITED
        if intent.get("hold") is not None:
            fields["hold"] = None
        if status == "succeeded":
            result = conductor.get("result") or {}
            decision = {"id": conductor.get("id"), "status": status, "accepted": result.get("accepted"),
                        "execution_ref": result.get("execution_ref")}
            moved = self._settle(intent, observed, RETURNED, decision=decision,
                                 evidence_refs=[ref for ref in (result.get("execution_ref"),) if ref], **fields)
            moved = self.intents.move(moved, COMPLETED)
            return {"subject": moved["id"], "effect": "conductor_decided", "route": CONDUCTOR}
        if status in {None, "pending"} and int(conductor.get("attempt") or 0) == 0:
            # Provably not entered (no attempt) AND the prior tree proven gone: a later launch of a NEW
            # identity may claim it.
            moved = self._settle(intent, observed, AWAITING_OWNER, reason_code="conductor_not_claimed", **fields)
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        reason = "conductor_timeout" if observed.get("state") == LAUNCH_TIMEOUT else "conductor_" + str(status)
        moved = self._settle(intent, observed, RECOVERY_REQUIRED, reason_code=reason,
                             next_owner=ROUTE_OWNERS[RECOVERY], **fields)
        return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
