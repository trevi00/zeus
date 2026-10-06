"""Active-generation maintenance of an ACTIVE, consumed managed delivery: the owner's restart, arm and bind phases.

Layer: application
Context: delivery
Owns: no bucket of its own (the one new key `generations` of an intent is written through the maintenance hold, in the
same transaction that re-checks the hold)
Does not own: review's releases and release_queue rows and the controller lease (the MaintenanceLease port), the
Fleet's pause, held units and one-job permit (the FleetMaintenance port), the host target and its generation observation
(the host port), the authority, artifact, credential and owner-action stores and the canary executor (injected callables
and objects)
Entry points: DeliveryMaintenance.maintain, .maintain_restart, .maintain_arm, .maintain_bind
Contracts: INV-HOST-DELIVERY-MAINTENANCE-001

Ported from main b9d8f15 (S2R) `application/host_delivery.py` (the hunks after M7 e38aa722): the bodies are S2R's,
placed in the target's split HostDelivery as its own object (`maintain` is `Recovery`'s sibling); S2R's `self._host`,
`self._now`, `self._parent` are `DeliveryState.host`, `.now`, `.parent` and its `self.queue.*_maintenance` calls go
through the `MaintenanceLease` port. The target holds of the S2R guards (`_maintenance_held` and `_maintenance_hold_of`)
are `DeliveryState.maintenance_held` and `state.maintenance_hold_in`. PR-3 batch b (G1-14b) adds `arm` and `bind` with their
ports `credentials`, `canary_executor` and `qualification_deadline`: S2R's `self._emit`, `self._canary` and
`self._deadline_from` are `DeliveryState.emit`, `DeliveryState.canary` and `state.deadline_from`; the owner-action ids and
row states are `domain.maintenance`'s local copies (delivery imports no coordination), and a Fleet refusal is recognised by
shape (`_is_fleet_refusal`) because `FleetRefused` is coordination's.
"""

from __future__ import annotations

import copy
import hashlib
import re
import time
from datetime import datetime

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
    LOGGER,
    deadline_from,
)
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AUTHORITY,
    AWAITING_CONSUMPTION,
    BLOCKED,
    DIGEST_HEX,
    EVENT_BLOCKED,
    EVENT_STAGE,
    EVIDENCE_REF,
    KIND_MANAGED_SYSTEMD,
    MANAGED_TARGET_FIELDS,
    MIGRATION_RESERVING,
    OUTCOME_ACTIVE,
    OUTCOME_BLOCKED,
    OUTCOME_PENDING,
    OWNER_CANARY_RECEIPT_SCHEMA,
    DeliveryRefused,
    LifecycleInterrupted,
    consumption_verdict,
    release_gate,
)
from codex_harness.delivery.domain.host_migration import MigrationRefused, validate_managed_lineage
from codex_harness.delivery.domain.host_migration_evidence import (
    CANARY_RECEIPT_FIELDS,
    COMPLETED,
    DELIVERY_CANARY,
    DESCRIPTOR_ROW_FIELDS,
    record_view,
    require_canary,
)
from codex_harness.delivery.domain.maintenance import (
    GENERATION_ARMED,
    GENERATION_BOUND,
    GENERATION_FAILED,
    GENERATION_LAUNCHED,
    GENERATION_REQUESTED,
    GENERATION_STARTED,
    MAINTENANCE_CODES,
    MAINTENANCE_PHASES,
    MAINTENANCE_RESULT_SCHEMA,
    OWNER_ACTION_REJECTED,
    OWNER_ACTION_REQUESTED,
    RESTART_REPLACE,
    canary_action_id,
    canary_job_id,
    classify_restart,
    competing_intent,
    fleet_ready_refusal,
    generation_id,
    maintenance_applicable,
    maintenance_of,
    maintenance_transition,
    new_generation_refusal,
    selection_of,
    validate_active_generation,
    validate_credential_evidence,
    validate_generation_observation,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest
from codex_harness.kernel.policy import POLICY

# INV-HOST-DELIVERY-MAINTENANCE-001: the prior ACTIVE binding fields a maintenance copies into `prior`, the
# authority bytes bound, and the one shape of a relayed field.
PRIOR_INTENT_FIELDS = ("stage", "outcome", "instance_id", "canary", "candidate_instance_id", "candidate_launch",
                       "previous_instance_id", "previous_launch", "stage_deadline", "stage_entered_at", "updated_at",
                       "descriptor_sha256")
MAINTENANCE_AUTHORITY_MAX_BYTES = 262144
SAFE_FIELD = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
# The Fleet job states that settle or reserve, and the permit close reasons that launched nothing
# (INV-FLEET-001 maintenance amendment; the values of `coordination.domain.fleet` / `fleet_maintenance`).
JOB_SETTLED = frozenset({"accepted", "rejected", "failed", "exhausted"})
JOB_FAILED = frozenset({"rejected", "failed", "exhausted"})
JOB_RESERVING = frozenset({"dispatching", "unknown"})
UNLAUNCHED_CLOSE_REASONS = frozenset({"maintenance_expired", "maintenance_cancelled"})
# The Fleet one-job permit schema (INV-FLEET-001 maintenance amendment); the permit dict is built here.
FLEET_PERMIT_SCHEMA = "urn:zeus:fleet-maintenance-permit:1"


class DeliveryMaintenance:
    """The restart, arm and bind phases of an active-generation maintenance (S2R `HostDelivery.maintain`, PR-3): one
    owner document, one short controller hold per write, and every external action strictly between short store
    transactions."""

    def __init__(self, store, *, org=None, clock=None, state=None, lease=None, authorities=None, artifacts=None,
                 canary_records=None, credentials=None, maintenance_fleet=None, canary_executor=None,
                 qualification_deadline=None):
        self.store, self.org, self.clock, self.state, self.lease = store, org, clock, state, lease
        # INV-HOST-DELIVERY-MAINTENANCE-001 ports, all absent by default (a missing one refuses by name):
        # `authorities(ref) -> bytes` the trusted read-only authority store; `artifacts.put(body, source)` the
        # content-addressed evidence store; `canary_records(action_id)` the control-store owner action row,
        # read only; `credentials(target, identity)` the pinned credential observation helper;
        # `maintenance_fleet` the control-store Fleet's narrow maintenance seam (readiness, the permit and the
        # job read); `canary_executor` its one-job executor; `qualification_deadline` the accepted
        # qualification deadline (aware ISO) or None.
        self.authorities, self.artifacts, self.canary_records = authorities, artifacts, canary_records
        self.credentials, self.maintenance_fleet = credentials, maintenance_fleet
        self.canary_executor, self.qualification_deadline = canary_executor, qualification_deadline

    # ----- active-generation maintenance (INV-HOST-DELIVERY-MAINTENANCE-001) -------------------------
    # Three separate owner phases over ONE ACTIVE, consumed managed delivery: `restart` records the request
    # BEFORE the one guarded graceful stop/start and records the new startup without claiming consumption;
    # `arm` binds the observed PRIMARY selection and creates the fresh instance-bound owner-canary
    # obligation (the unchanged owner-actions discovers it) and dispatches its one job; `bind` records
    # consumption only after that actual new-instance canary is accepted. Cross-store observations are NOT
    # one transaction: they are pinned, the target is held logically by the generation itself, the short
    # controller hold (`ReleaseQueue.hold_maintenance`) fences every lane write, and every phase revalidates
    # before its effect. No lease is held across the canary execution, and no store transaction is ever
    # open across a port call.
    def maintain(self, document, evidence_ref, phase, *, check=False, startup_seconds=120.0, poll_seconds=1.0,
                 canary_wait_seconds=None) -> dict:
        """One maintenance phase (`restart`, `arm` or `bind`) of one owner document. With `check` every
        refusal is RETURNED as `applicable: False` and nothing is held, put, written or started."""
        if phase == "restart":
            return self.maintain_restart(document, evidence_ref, check=check, startup_seconds=startup_seconds,
                                         poll_seconds=poll_seconds)
        if phase == "arm":
            return self.maintain_arm(document, evidence_ref, check=check, canary_wait_seconds=canary_wait_seconds)
        if phase == "bind":
            return self.maintain_bind(document, evidence_ref, check=check)
        refusal = DeliveryRefused("maintenance_phase", "phase")
        if check:
            return self._maintenance_result({"phase": None, "check": True}, refusal=refusal)
        raise refusal

    def maintain_restart(self, document, evidence_ref, *, check=False, startup_seconds=120.0,
                         poll_seconds=1.0) -> dict:
        return self._maintenance_run("restart", document, evidence_ref, check,
                                     lambda ctx: self._maintain_restart(ctx, startup_seconds, poll_seconds))

    def maintain_arm(self, document, evidence_ref, *, check=False, canary_wait_seconds=None) -> dict:
        # DN-8: the one-job wait is the operation's own allowance; the numbers live only in POLICY.
        wait = (POLICY.task_seconds + POLICY.decision_seconds if canary_wait_seconds is None
                else float(canary_wait_seconds))
        return self._maintenance_run("arm", document, evidence_ref, check, lambda ctx: self._maintain_arm(ctx, wait))

    def maintain_bind(self, document, evidence_ref, *, check=False) -> dict:
        return self._maintenance_run("bind", document, evidence_ref, check, self._maintain_bind)

    def _maintenance_run(self, phase: str, document, evidence_ref, check: bool, body) -> dict:
        ctx = {"phase": phase, "check": bool(check)}
        try:
            self._maintenance_inputs(ctx, document, evidence_ref)
            return body(ctx)
        except DeliveryRefused as exc:
            if not check:
                raise
            return self._maintenance_result(ctx, refusal=exc)

    # --- common inputs ------------------------------------------------------------------------------
    def _maintenance_inputs(self, ctx: dict, document, evidence_ref) -> None:
        """Document, evidence, authority bytes, one lane snapshot, approver and the recorded generation."""
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("maintenance_invalid", "evidence")
        doc = validate_active_generation(document)
        if evidence_ref != "sha256:" + digest(doc):
            raise DeliveryRefused("maintenance_invalid", "evidence")
        ctx.update(doc=doc, evidence_ref=evidence_ref, mid=generation_id(doc))
        self._maintenance_authority(doc)
        snap = self._maintenance_snapshot(doc["plan_id"])
        ctx.update(snap=snap, plan=snap["plan_row"]["plan"])
        self._maintenance_approver(doc, snap["release"])
        generation = maintenance_of(snap["intent"])
        if generation is not None and generation.get("id") != ctx["mid"]:
            # One maintenance generation per delivery in v1. The same retiring generation under another
            # document is the same request identity with different bytes; anything else is a new attempt.
            if (generation.get("document") or {}).get("retiring") == doc["retiring"]:
                raise DeliveryRefused("maintenance_conflict", "document")
            raise DeliveryRefused("maintenance_already_used", "document")
        ctx["g"] = generation
        if generation is not None and generation.get("state") == GENERATION_FAILED:
            if not ctx["check"]:
                self._settle_control(ctx, generation)
            raise DeliveryRefused("maintenance_failed", "state")

    def _maintenance_authority(self, doc: dict) -> None:
        """DN-1: the authority reference resolves through the trusted read-only store and its bytes verify.
        The bytes are never stored, printed or relayed; digest syntax alone is not authority."""
        port = self.authorities
        if port is None:
            raise DeliveryRefused("maintenance_authority_unverified", "authority")
        try:
            data = port(doc["authority"])
        except Exception:
            raise DeliveryRefused("maintenance_authority_unverified", "authority") from None
        if not (type(data) is bytes and 1 <= len(data) <= MAINTENANCE_AUTHORITY_MAX_BYTES
                and hashlib.sha256(data).hexdigest() == doc["authority"][len("sha256:"):]):
            raise DeliveryRefused("maintenance_authority_unverified", "authority")

    def _maintenance_approver(self, doc: dict, release) -> None:
        """An existing conductor of the organization who is not the candidate's author."""
        author = ((release or {}).get("candidate") or {}).get("author")
        if self.org is None:
            raise DeliveryRefused("maintenance_authority_unverified", "approved_by")
        try:
            self.org.actor(doc["approved_by"], "conductor")
        except Exception:
            raise DeliveryRefused("maintenance_authority_unverified", "approved_by") from None
        if doc["approved_by"] == author:
            raise DeliveryRefused("maintenance_authority_unverified", "approved_by")

    def _maintenance_snapshot(self, plan_id: str) -> dict:
        """ONE lane read transaction: every row a maintenance pins, as independent copies."""
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id)
                snap = None if row is None else self._snapshot_in(tx, row["plan"])
        except DeliveryRefused:
            raise
        except Exception:
            raise DeliveryRefused("maintenance_stale", "store") from None
        if snap is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        return snap

    @staticmethod
    def _snapshot_in(tx, plan: dict) -> dict:
        return copy.deepcopy({
            "plan_row": tx.get(BUCKET_PLANS, plan["plan_id"]), "intent": tx.get(BUCKET_INTENTS, plan["plan_id"]),
            "descriptor_row": tx.get(BUCKET_DESCRIPTORS, plan["target_id"]),
            "target": tx.get(BUCKET_TARGETS, plan["target_id"]), "release": tx.get("releases", plan["release_id"]),
            "pointer": tx.get("deployment", "active") or {}, "queue": tx.get("release_queue", plan["release_id"]),
            "intents": tx.scan(BUCKET_INTENTS), "migrations": tx.scan(BUCKET_MIGRATIONS),
            "lock": tx.get("deployment_locks", "controller") or {}})

    # --- restart ------------------------------------------------------------------------------------
    def _maintain_restart(self, ctx: dict, startup_seconds: float, poll_seconds: float) -> dict:
        generation = ctx["g"]
        if generation is None:
            return self._maintenance_request(ctx, startup_seconds, poll_seconds)
        state = generation.get("state")
        if state in (GENERATION_STARTED, GENERATION_ARMED, GENERATION_BOUND):
            return self._maintenance_result(ctx, cached=True)
        if state == GENERATION_REQUESTED:
            return self._maintenance_requested_replay(ctx, startup_seconds, poll_seconds)
        if state == GENERATION_LAUNCHED:
            return self._maintenance_launched_replay(ctx, startup_seconds, poll_seconds)
        raise DeliveryRefused("maintenance_phase", "state")

    def _maintenance_request(self, ctx: dict, startup_seconds: float, poll_seconds: float) -> dict:
        """The first request: every read-only check, then the durable `requested` record in the same
        transaction that takes the hold, and only then the one guarded start."""
        doc, snap, mid, plan = ctx["doc"], ctx["snap"], ctx["mid"], ctx["plan"]
        intent = snap["intent"]
        gate = release_gate(snap["release"], plan, self.state.parent(snap["release"]))
        refusal = maintenance_applicable(
            doc, plan_row=snap["plan_row"], intent=intent, descriptor_row=snap["descriptor_row"],
            target=snap["target"], release_record=snap["release"], gate=gate, pointer=snap["pointer"],
            queue_row=snap["queue"], intents=snap["intents"], migrations=snap["migrations"], lock=snap["lock"],
            now=self.state.now())
        if refusal is not None:
            raise DeliveryRefused(*refusal)
        self._fleet_ready(mid)
        host, target = self._maintenance_host(ctx)
        preview = self._restart_authority(doc, mid, self.clock())
        raw = self._observe_generation(host, target, "maintenance_invocation_mismatch")
        observed = validate_generation_observation(raw)
        decision = classify_restart(intent["descriptor"], raw, preview)
        if decision["path"] is None:
            raise DeliveryRefused(decision["reason_code"], decision["field"])
        if decision["path"] != RESTART_REPLACE:
            # The first request replaces the running recorded incumbent; nothing else is requested.
            raise DeliveryRefused("maintenance_invocation_mismatch", "running")
        receipt, action = self._old_canary(host, target, plan, intent, doc)
        if ctx["check"]:
            return self._maintenance_result(ctx)
        refs = self._maintenance_artifacts(mid, {"startup_receipt": observed["receipt"],
                                                 "owner_canary_receipt": receipt, "owner_canary_action": action,
                                                 "launch_record": observed["launch"]})
        now = self.clock()
        row = snap["descriptor_row"]
        generation = {
            "id": mid, "document": doc, "evidence_ref": ctx["evidence_ref"], "state": GENERATION_REQUESTED,
            "requested_at": now, "updated_at": now,
            "retiring": {**doc["retiring"], "observed": {
                "supervisor_pid": observed["supervisor"]["pid"],
                "supervisor_start_ticks": observed["supervisor"]["start_ticks"],
                "entry_pid": observed["entry"]["pid"], "entry_start_ticks": observed["entry"]["start_ticks"],
                "launch_request_sha256": observed["launch_request_sha256"],
                "control_group_sha256": observed["unit"]["control_group_sha256"],
                "observed_at": observed["observed_at"]}, "selection": selection_of(observed)},
            "prior": {"intent": {key: copy.deepcopy(intent.get(key)) for key in PRIOR_INTENT_FIELDS},
                      "intent_sha256": digest(_without_generations(intent)),
                      "descriptor_row": {**{key: copy.deepcopy(row.get(key)) for key in DESCRIPTOR_ROW_FIELDS},
                                         "history_count": len(row.get("history") or [])},
                      "descriptor_row_sha256": digest(row), "startup_receipt": observed["receipt"],
                      "owner_canary_receipt": receipt, "owner_canary_action": action,
                      "launch": {"launch_sha256": observed["launch_sha256"],
                                 "launch_request_sha256": observed["launch_request_sha256"],
                                 "invocation_id": observed["unit"]["invocation_id"]},
                      "release_sha256": digest(snap["release"]),
                      "pointer": {"release_id": snap["pointer"].get("release_id")},
                      "queue_sha256": digest(snap["queue"]), "evidence_refs": refs},
            "launched": None, "credential_evidence": [], "arm": None, "canary": None, "failure": None,
            "observations": [self._observation("restart", GENERATION_REQUESTED, None, None, now)]}
        holder = self._maintenance_hold(mid, lambda tx, claim: self._request_in(tx, snap, generation))
        LOGGER.warning("maintenance requested plan=%s id=%s", plan["plan_id"], mid)
        ctx["g"] = generation
        try:
            return self._maintenance_start(ctx, holder, generation, startup_seconds, poll_seconds)
        finally:
            self._maintenance_release(holder)

    def _request_in(self, tx, snap: dict, generation: dict) -> None:
        """Inside the hold's transaction: every pinned row is still exactly the snapshot, then the ONE
        new key `generations` is written. No other intent field changes, `updated_at` included."""
        plan = snap["plan_row"]["plan"]
        fresh = self._snapshot_in(tx, plan)
        for key, name in (("plan_row", "plan_id"), ("intent", "intent"), ("descriptor_row", "descriptor_row"),
                          ("target", "target_id"), ("release", "release_id"), ("pointer", "pointer"),
                          ("queue", "queue"), ("migrations", "migrations")):
            if fresh[key] != snap[key]:
                raise DeliveryRefused("maintenance_stale", name)
        if _by_id(fresh["intents"]) != _by_id(snap["intents"]):
            raise DeliveryRefused("maintenance_stale", "intents")
        if maintenance_of(fresh["intent"]) is not None:
            raise DeliveryRefused("maintenance_stale", "generation")
        tx.put(BUCKET_INTENTS, plan["plan_id"], {**fresh["intent"], "generations": [generation]})

    def _maintenance_requested_replay(self, ctx: dict, startup_seconds: float, poll_seconds: float) -> dict:
        """A recorded, not yet launched request: the same document reconciles its own effect only. The
        adapter classifies under its guard, so at most one new launch ever happens."""
        generation, snap, mid = ctx["g"], ctx["snap"], ctx["mid"]
        self._fleet_ready(mid)
        prior = generation.get("prior") or {}
        self._require_unchanged(generation, snap, prior.get("intent_sha256"), prior.get("descriptor_row_sha256"))
        host, target = self._maintenance_host(ctx)
        if ctx["check"]:
            raw = self._observe_generation(host, target, "maintenance_invocation_mismatch")
            decision = classify_restart(snap["intent"]["descriptor"], raw,
                                        self._restart_authority(ctx["doc"], mid, generation["requested_at"]))
            if decision["path"] is None:
                raise DeliveryRefused(decision["reason_code"], decision["field"])
            return self._maintenance_result(ctx)
        holder = self._maintenance_hold(mid, self._unchanged_in(ctx, generation, prior.get("intent_sha256"),
                                                                prior.get("descriptor_row_sha256")))
        try:
            return self._maintenance_start(ctx, holder, generation, startup_seconds, poll_seconds)
        finally:
            self._maintenance_release(holder)

    def _maintenance_launched_replay(self, ctx: dict, startup_seconds: float, poll_seconds: float) -> dict:
        """A recorded launch whose receipt was not confirmed yet: wait for it again; never start."""
        generation, mid = ctx["g"], ctx["mid"]
        host, target = self._maintenance_host(ctx)
        if ctx["check"]:
            return self._maintenance_result(ctx)
        prior = generation.get("prior") or {}
        holder = self._maintenance_hold(mid, self._unchanged_in(ctx, generation, prior.get("intent_sha256"),
                                                                prior.get("descriptor_row_sha256")))
        try:
            return self._maintenance_startup(ctx, holder, host, target, generation, startup_seconds, poll_seconds)
        finally:
            self._maintenance_release(holder)

    def _maintenance_start(self, ctx: dict, holder: dict, generation: dict, startup_seconds: float,
                           poll_seconds: float) -> dict:
        """The one guarded start under the hold; its outcome, then the new startup receipt, recorded."""
        doc, mid = ctx["doc"], ctx["mid"]
        descriptor = ctx["snap"]["intent"]["descriptor"]
        host, target = self._maintenance_host(ctx)
        restarts = self._restart_authority(doc, mid, generation["requested_at"])
        try:
            started = host.start(target, descriptor, authorize=self._maintenance_authorizer(holder),
                                 restarts=restarts)
        except DeliveryRefused as exc:
            # Refused before any effect: the refusal is a truthful observation of the recorded request.
            self._maintenance_observe(holder, ctx, exc.reason_code, exc.field)
            raise
        except LifecycleInterrupted:
            # The stop happened and then ownership or the gate was lost: an effect out in the world.
            self._maintenance_observe(holder, ctx, "maintenance_reconciliation_required", "effect")
            raise DeliveryRefused("maintenance_reconciliation_required", "effect") from None
        except ContractError:
            # The hold was lost at the guard's entry, before any effect: this controller records nothing.
            raise DeliveryRefused("maintenance_stale", "controller") from None
        except Exception:
            self._maintenance_observe(holder, ctx, "maintenance_reconciliation_required", "effect")
            raise DeliveryRefused("maintenance_reconciliation_required", "effect") from None
        launch = started.get("launch") if isinstance(started, dict) else None
        fresh = self._observe_quietly(host, target)
        if not isinstance(launch, dict) and fresh is not None:
            launch = fresh["launch"]
        if not isinstance(launch, dict):
            self._maintenance_observe(holder, ctx, "maintenance_launch_unconfirmed", "launch")
            raise DeliveryRefused("maintenance_launch_unconfirmed", "launch")
        now = self.clock()
        launched = {"request_sha256": digest(doc), "launch_sha256": digest(launch),
                    "invocation_id": launch.get("invocation_id"), "path": started.get("path"),
                    "launch": copy.deepcopy(launch), "selection": None if fresh is None else selection_of(fresh),
                    "at": now, "receipt": None}

        def record(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_REQUESTED)
            maintenance_transition(current, GENERATION_LAUNCHED)
            return self._with_generation(intent, {
                **current, "state": GENERATION_LAUNCHED, "updated_at": now, "launched": launched,
                "observations": [*current.get("observations", []),
                                 self._observation("restart", GENERATION_LAUNCHED, None, None, now)]}), None

        generation = self._maintenance_owned(holder, ctx, record)
        LOGGER.warning("maintenance launched plan=%s id=%s", ctx["plan"]["plan_id"], mid)
        return self._maintenance_startup(ctx, holder, host, target, generation, startup_seconds, poll_seconds)

    def _maintenance_startup(self, ctx: dict, holder: dict, host, target: dict, generation: dict,
                             startup_seconds: float, poll_seconds: float) -> dict:
        """The new generation's OWN startup receipt, bounded: this descriptor, not the retiring instance,
        running under the recorded invocation and launch with its process identity proven."""
        mid, launched = ctx["mid"], generation["launched"]
        descriptor = ctx["snap"]["intent"]["descriptor"]
        retiring = generation["retiring"]["instance_id"]
        deadline = time.monotonic() + max(0.0, float(startup_seconds))
        while True:
            observed = self._observe_quietly(host, target)
            if observed is not None and self._started_generation(descriptor, observed, retiring, launched):
                break
            if time.monotonic() >= deadline:
                self._maintenance_observe(holder, ctx, "maintenance_launch_unconfirmed", "receipt")
                raise DeliveryRefused("maintenance_launch_unconfirmed", "receipt")
            time.sleep(max(0.0, float(poll_seconds)))
        receipt, now = observed["receipt"], self.clock()
        startup = {**{key: receipt[key] for key in ("instance_id", "pid", "started_at", "revision", "runtime_root",
                                                    "module_root")},
                   "invocation_id": observed["unit"]["invocation_id"], "at": now}

        def record(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_LAUNCHED)
            maintenance_transition(current, GENERATION_STARTED)
            return self._with_generation(intent, {
                **current, "state": GENERATION_STARTED, "updated_at": now,
                "launched": {**current["launched"], "receipt": startup},
                "observations": [*current.get("observations", []),
                                 self._observation("restart", GENERATION_STARTED, None, None, now)]}), None

        generation = self._maintenance_owned(holder, ctx, record)
        ctx["g"] = generation
        LOGGER.warning("maintenance started plan=%s id=%s", ctx["plan"]["plan_id"], mid)
        return self._maintenance_result(ctx)

    @staticmethod
    def _started_generation(descriptor: dict, observed: dict, retiring: str, launched: dict) -> bool:
        verdict = consumption_verdict(descriptor, observed["receipt"], expected_instance=retiring)
        return (verdict["consumed"] and observed["running"] is True
                and observed["unit"]["invocation_id"] == launched.get("invocation_id")
                and observed["launch_sha256"] == launched.get("launch_sha256")
                and observed["supervisor"]["is_main_pid"] is True
                and all(observed["entry"][flag] is True
                        for flag in ("parent_is_supervisor", "in_unit_cgroup", "started_before_receipt")))

    def _old_canary(self, host, target: dict, plan: dict, intent: dict, doc: dict) -> tuple:
        """Typed copies of the retiring instance's accepted owner canary receipt and completed action; the
        old action is copied into `prior` and never changed."""
        evidence = (intent.get("canary") or {}).get("evidence") or {}
        identity = evidence.get("action_id") if isinstance(evidence, dict) else None
        reader = getattr(host, "owner_canary", None)
        if not (type(identity) is str and DIGEST_HEX.fullmatch(identity)) or reader is None \
                or self.canary_records is None:
            raise DeliveryRefused("maintenance_not_active", "canary")
        try:
            receipt, action = reader(target, plan["plan_id"]), self.canary_records(identity)
        except Exception:
            raise DeliveryRefused("maintenance_not_active", "canary") from None
        retiring = doc["retiring"]["instance_id"]
        if not (isinstance(receipt, dict) and set(receipt) == CANARY_RECEIPT_FIELDS
                and receipt["schema"] == OWNER_CANARY_RECEIPT_SCHEMA and receipt["passed"] is True
                and receipt["instance_id"] == retiring and receipt["descriptor_sha256"] == intent["descriptor_sha256"]
                and isinstance(receipt["evidence"], dict) and receipt["evidence"].get("action_id") == identity):
            raise DeliveryRefused("maintenance_not_active", "canary")
        view = record_view(action)
        binding = (view or {}).get("binding") or {}
        if not (view and view["id"] == identity and view["kind"] == DELIVERY_CANARY and view["state"] == COMPLETED
                and binding.get("instance_id") == retiring and binding.get("plan_id") == plan["plan_id"]
                and binding.get("descriptor_sha256") == intent["descriptor_sha256"]):
            raise DeliveryRefused("maintenance_not_active", "canary")
        return copy.deepcopy({key: receipt[key] for key in sorted(CANARY_RECEIPT_FIELDS)}), copy.deepcopy(view)

    def _maintenance_artifacts(self, mid: str, documents: dict) -> dict:
        """Content-addressed refs of the bounded validated originals, taken only after every read-only
        check passed and never in `check` mode."""
        port = self.artifacts
        if port is None:
            raise DeliveryRefused("host_port_unavailable", "artifacts")
        refs = {}
        for name in sorted(documents):
            try:
                ref = port.put(canonical(documents[name]), "host-delivery-maintenance:" + mid + ":" + name)["ref"]
            except Exception:
                raise DeliveryRefused("host_port_unavailable", "artifacts") from None
            if not (type(ref) is str and EVIDENCE_REF.fullmatch(ref)):
                raise DeliveryRefused("host_port_unavailable", "artifacts")
            refs[name] = ref
        return refs

    @staticmethod
    def _restart_authority(doc: dict, mid: str, requested_at: str) -> dict:
        retiring = doc["retiring"]
        return {"maintenance_id": mid, "instance_id": retiring["instance_id"],
                "invocation_id": retiring["invocation_id"], "launch_sha256": retiring["launch_sha256"],
                "requested_at": requested_at}

    # --- arm ----------------------------------------------------------------------------------------
    def _maintain_arm(self, ctx: dict, wait: float) -> dict:
        generation = ctx["g"]
        if generation is None or generation.get("state") not in (GENERATION_STARTED, GENERATION_ARMED):
            raise DeliveryRefused("maintenance_phase", "state")
        arm = generation.get("arm")
        if arm is not None and self._expired_at(arm.get("deadline")):
            # Expiry first; the ONE deadline is never recomputed.
            if ctx["check"]:
                raise DeliveryRefused("maintenance_expired", "deadline")
            self._maintenance_expire(ctx, generation)
        host, target = self._maintenance_host(ctx)
        observed = self._maintenance_identity(ctx, host, target, generation)
        credential = self._maintenance_credentials(target, observed, generation)
        if generation["state"] == GENERATION_STARTED and arm is None:
            return self._arm_first(ctx, credential, wait)
        if generation["state"] == GENERATION_STARTED:
            return self._arm_resume(ctx, credential, wait)
        return self._arm_replay(ctx, host, target, wait)

    def _arm_first(self, ctx: dict, credential: dict, wait: float) -> dict:
        doc, mid, plan, generation = ctx["doc"], ctx["mid"], ctx["plan"], ctx["g"]
        now = self.clock()
        deadline = deadline_from(now, doc["canary_window_seconds"])
        if self.qualification_deadline is not None:
            bound = self._aware(self.qualification_deadline)
            if bound is None or datetime.fromisoformat(deadline) > bound:
                raise DeliveryRefused("maintenance_invalid", "canary_window_seconds")
        self._fleet_ready(mid)
        binding = {"plan_id": plan["plan_id"], "plan_sha256": doc["plan_sha256"], "target_id": plan["target_id"],
                   "descriptor_sha256": doc["descriptor_sha256"],
                   "instance_id": generation["launched"]["receipt"]["instance_id"]}
        identity = canary_action_id(binding)
        permit = {"schema": FLEET_PERMIT_SCHEMA, "maintenance_id": mid,
                  "evidence_ref": ctx["evidence_ref"], **binding, "action_id": identity,
                  "job_id": canary_job_id(identity), "deadline": deadline}
        ctx.update(action_id=identity, job_id=permit["job_id"], deadline=deadline)
        if ctx["check"]:
            return self._maintenance_result(ctx)
        arm = {"deadline": deadline, "requested_at": now, "permit": permit, "permit_sha256": digest(permit),
               "intent_sha256": None, "descriptor_row_sha256": None, "control": {"state": "requested", "at": now},
               "dispatch": None}
        prior = generation.get("prior") or {}

        def request(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_STARTED)
            if current.get("arm") is not None:
                raise DeliveryRefused("maintenance_stale", "generation")
            return self._with_generation(intent, {
                **current, "arm": arm,
                "credential_evidence": [*current.get("credential_evidence", []),
                                        {**credential, "phase": "arm", "at": now}]}), None

        # T1a: the lane request, under the hold, CAS-pinned to the prior ACTIVE binding. The state stays
        # `started` and nothing but `generations` changes, so owner-actions can discover nothing yet.
        holder = self._maintenance_hold(mid, self._unchanged_in(ctx, generation, prior.get("intent_sha256"),
                                                                prior.get("descriptor_row_sha256"), request))
        try:
            return self._arm_grant(ctx, holder, permit, wait)
        finally:
            self._maintenance_release(holder)

    def _arm_resume(self, ctx: dict, credential: dict, wait: float) -> dict:
        """T1a committed, then the control grant or the lane acknowledgement was lost: the SAME permit and
        deadline are granted (cached) and acknowledged; nothing is recomputed."""
        mid, generation = ctx["mid"], ctx["g"]
        permit = generation["arm"]["permit"]
        ctx.update(action_id=permit["action_id"], job_id=permit["job_id"], deadline=generation["arm"]["deadline"])
        if ctx["check"]:
            return self._maintenance_result(ctx)
        prior, now = generation.get("prior") or {}, self.clock()

        def evidence(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_STARTED)
            return self._with_generation(intent, {
                **current, "credential_evidence": [*current.get("credential_evidence", []),
                                                   {**credential, "phase": "arm", "at": now}]}), None

        holder = self._maintenance_hold(mid, self._unchanged_in(ctx, generation, prior.get("intent_sha256"),
                                                                prior.get("descriptor_row_sha256"), evidence))
        try:
            return self._arm_grant(ctx, holder, permit, wait)
        finally:
            self._maintenance_release(holder)

    def _arm_grant(self, ctx: dict, holder: dict, permit: dict, wait: float) -> dict:
        """C1 (the idempotent control grant, no lane transaction open), then T1b, then the dispatch."""
        self._fleet_call(holder, ctx, lambda fleet: fleet.grant_maintenance_canary(permit))
        self._arm_acknowledge(ctx, holder)
        return self._dispatch_attempt(ctx, holder, wait)

    def _arm_acknowledge(self, ctx: dict, holder: dict) -> None:
        """T1b, ONE owned transaction: the control acknowledgement, `armed`, and the armed transform of
        the current binding (the new candidate awaits its own canary; the prior ACTIVE facts stay in
        `prior`). Release, queue and pointer are untouched; same-descriptor history is appended."""
        mid, plan = ctx["mid"], ctx["plan"]
        now = self.clock()

        def acknowledge(intent, row):
            current = self._expect_generation(intent, mid, GENERATION_STARTED)
            prior = current.get("prior") or {}
            if digest(_without_generations(intent)) != prior.get("intent_sha256"):
                raise DeliveryRefused("maintenance_stale", "intent")
            if digest(row) != prior.get("descriptor_row_sha256"):
                raise DeliveryRefused("maintenance_stale", "descriptor_row")
            maintenance_transition(current, GENERATION_ARMED)
            arm, launched = current["arm"], current["launched"]
            receipt = launched["receipt"]
            new = receipt["instance_id"]
            armed = {key: value for key, value in intent.items() if key != "generations"}
            armed.update({"stage": AWAITING_CONSUMPTION, "previous_stage": ACTIVE, "outcome": OUTCOME_PENDING,
                          "reason_code": "maintenance_canary_pending", "error_type": None, "attempts": 0,
                          "instance_id": None, "canary": None, "candidate_instance_id": new,
                          "candidate_launch": copy.deepcopy(launched["launch"]), "stage_entered_at": now,
                          "stage_deadline": arm["deadline"], "updated_at": now})
            history = list(row.get("history") or [])[-9:] + [{
                "descriptor_sha256": row.get("descriptor_sha256"), "at": row.get("updated_at"), "consumed": True,
                "instance_id": row.get("instance_id"), "maintenance_id": mid}]
            row2 = {**row, "consumed": False, "instance_id": None, "startup_observed": True,
                    "observed_instance_id": new, "observed_revision": receipt["revision"],
                    "observed_runtime_root": receipt["runtime_root"], "history": history, "updated_at": now}
            settled = {**current, "state": GENERATION_ARMED, "updated_at": now,
                       "arm": {**arm, "control": {"state": "acknowledged", "at": now},
                               "intent_sha256": digest(armed), "descriptor_row_sha256": digest(row2)},
                       "observations": [*current.get("observations", []),
                                        self._observation("arm", GENERATION_ARMED, None, None, now)]}
            return {**armed, "generations": [settled]}, row2

        generation = self._maintenance_owned(holder, ctx, acknowledge)
        ctx["g"] = generation
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": AWAITING_CONSUMPTION, "previous_stage": ACTIVE})
        LOGGER.warning("maintenance armed plan=%s id=%s", plan["plan_id"], mid)

    def _arm_replay(self, ctx: dict, host, target: dict, wait: float) -> dict:
        """An armed generation: reconcile a lost control grant, never respawn admitted work."""
        mid, generation = ctx["mid"], ctx["g"]
        arm = generation["arm"]
        permit = arm["permit"]
        ctx.update(action_id=permit["action_id"], job_id=permit["job_id"], deadline=arm["deadline"])
        fleet = self._maintenance_fleet_port()
        view = self._fleet_read(lambda: fleet.maintenance_permit(mid))
        state = (view or {}).get("state")
        if view is None or (arm.get("control") or {}).get("state") == "requested" or state == "granted":
            if ctx["check"]:
                return self._maintenance_result(ctx)
            holder = self._maintenance_hold(mid, self._unchanged_in(ctx, generation, arm.get("intent_sha256"),
                                                                    arm.get("descriptor_row_sha256")))
            try:
                if view is None or state != "granted":
                    # The control grant's response was lost: the same permit is granted again (cached).
                    self._fleet_call(holder, ctx, lambda port: port.grant_maintenance_canary(permit))
                return self._dispatch_attempt(ctx, holder, wait)
            finally:
                self._maintenance_release(holder)
        job = self._fleet_read(lambda: fleet.job(permit["job_id"])) or {}
        if job.get("status") in JOB_RESERVING:
            raise DeliveryRefused("maintenance_reconciliation_required", "job")
        if not ctx["check"] and arm.get("dispatch") is None:
            try:
                holder = self._maintenance_hold(mid, None)
            except DeliveryRefused:
                holder = None       # informational only; the control row stays the authority
            if holder is not None:
                try:
                    # Reconciled from the control row after a lost arm response; nothing is executed.
                    self._record_dispatch(ctx, holder, {"job_id": permit["job_id"], "state": "reconciled",
                                                        "job_status": job.get("status")})
                finally:
                    self._maintenance_release(holder)
        # A replayed arm never respawns: the admission is spent.
        raise DeliveryRefused("maintenance_already_used", "admission")

    def _dispatch_attempt(self, ctx: dict, holder: dict, wait: float) -> dict:
        """The ONE canary dispatch of this obligation. The owner action and its queued job must exist and
        be exactly this binding; the identity and PRIMARY evidence are re-proven immediately before; the
        proof is pinned from the lane, and the hold is RELEASED before the one-job executor runs."""
        mid = ctx["mid"]
        executor, records = self.canary_executor, self.canary_records
        if executor is None:
            raise DeliveryRefused("host_port_unavailable", "canary_executor")
        if records is None:
            raise DeliveryRefused("host_port_unavailable", "canary_records")
        fleet = self._maintenance_fleet_port()
        generation = ctx["g"]
        permit = generation["arm"]["permit"]
        try:
            action = records(permit["action_id"])
        except Exception:
            raise DeliveryRefused("host_port_unavailable", "canary_records") from None
        job = self._fleet_read(lambda: fleet.job(permit["job_id"]))
        if not isinstance(action, dict) or action.get("state") == "intended" or not isinstance(job, dict):
            # Owner-actions has not queued the obligation yet: pending, nothing written.
            self._maintenance_release(holder)
            return self._maintenance_result(ctx, pending=True, reason_code="maintenance_canary_pending")
        binding = {key: permit[key] for key in ("plan_id", "plan_sha256", "target_id", "descriptor_sha256",
                                                "instance_id")}
        if (action.get("kind") != DELIVERY_CANARY or action.get("state") != OWNER_ACTION_REQUESTED
                or action.get("binding") != binding or action.get("job_id") != permit["job_id"]):
            self._maintenance_observe(holder, ctx, "maintenance_admission_refused", "action")
            raise DeliveryRefused("maintenance_admission_refused", "action")
        if job.get("status") != "queued":
            code = ("maintenance_reconciliation_required" if job.get("status") in JOB_RESERVING
                    else "maintenance_already_used")
            self._maintenance_observe(holder, ctx, code, "job")
            raise DeliveryRefused(code, "job")
        host, target = self._maintenance_host(ctx)
        observed = self._maintenance_identity(ctx, host, target, generation, holder=holder)
        credential = self._maintenance_credentials(target, observed, generation)
        now = self.clock()

        def evidence(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_ARMED)
            return self._with_generation(intent, {
                **current, "credential_evidence": [*current.get("credential_evidence", []),
                                                   {**credential, "phase": "dispatch", "at": now}]}), None

        generation = self._maintenance_owned(holder, ctx, evidence)
        arm = generation["arm"]
        proof = {"maintenance_id": mid, "permit_sha256": arm["permit_sha256"],
                 "generation_state": generation["state"],
                 "acknowledged": (arm.get("control") or {}).get("state") == "acknowledged",
                 "deadline": arm["deadline"], "instance_id": arm["permit"]["instance_id"],
                 "descriptor_sha256": arm["permit"]["descriptor_sha256"]}
        # No controller lease across the canary execution (spec D2.3); the logical target hold remains.
        self._maintenance_release(holder)
        try:
            outcome = executor.execute(mid, permit_sha256=arm["permit_sha256"], proof=proof, max_wait_seconds=wait)
        except DeliveryRefused:
            raise
        except Exception as exc:
            if _is_fleet_refusal(exc):
                raise self._fleet_refusal(exc) from None
            raise DeliveryRefused("maintenance_reconciliation_required", "job") from None
        outcome = outcome if isinstance(outcome, dict) else {}
        status = outcome.get("job_status")
        dispatch = {"job_id": permit["job_id"], "state": outcome.get("state"),
                    "job_status": status if type(status) is str else None}
        try:
            after = self._maintenance_hold(mid, None)
        except DeliveryRefused:
            after = None      # the record is informational; bind reads the permit and the job itself
        if after is not None:
            try:
                self._record_dispatch(ctx, after, dispatch)
            finally:
                self._maintenance_release(after)
        if status in JOB_SETTLED:
            return self._maintenance_result(ctx)
        reason = "maintenance_reconciliation_required" if status == "unknown" else "maintenance_canary_pending"
        return self._maintenance_result(ctx, pending=True, reason_code=reason)

    def _record_dispatch(self, ctx: dict, holder: dict, dispatch: dict) -> None:
        mid, now = ctx["mid"], self.clock()

        def record(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_ARMED)
            return self._with_generation(intent, {
                **current, "arm": {**current["arm"], "dispatch": {**dispatch, "at": now}},
                "observations": [*current.get("observations", []),
                                 self._observation("arm", GENERATION_ARMED, None, None, now)]}), None

        try:
            ctx["g"] = self._maintenance_owned(holder, ctx, record)
        except DeliveryRefused:
            pass

    # --- bind ---------------------------------------------------------------------------------------
    def _maintain_bind(self, ctx: dict) -> dict:
        generation, mid, plan = ctx["g"], ctx["mid"], ctx["plan"]
        if generation is None:
            raise DeliveryRefused("maintenance_phase", "state")
        arm = generation.get("arm") or {}
        permit = arm.get("permit") or {}
        ctx.update(action_id=permit.get("action_id"), job_id=permit.get("job_id"), deadline=arm.get("deadline"))
        if generation.get("state") == GENERATION_BOUND:
            if (generation.get("canary") or {}).get("settlement") is None and not ctx["check"]:
                holder = self._maintenance_hold(mid, None)
                try:
                    settled = self._bind_settle(ctx, holder)
                finally:
                    self._maintenance_release(holder)
                if not settled:
                    return self._maintenance_result(ctx, cached=True, pending=True,
                                                    reason_code="maintenance_reconciliation_required")
            return self._maintenance_result(ctx, cached=True)
        if generation.get("state") != GENERATION_ARMED:
            raise DeliveryRefused("maintenance_phase", "state")
        if self._expired_at(arm.get("deadline")):
            if ctx["check"]:
                raise DeliveryRefused("maintenance_expired", "deadline")
            self._maintenance_expire(ctx, generation)
        host, target = self._maintenance_host(ctx)
        observed = self._maintenance_identity(ctx, host, target, generation)
        fleet = self._maintenance_fleet_port()
        view = self._fleet_read(lambda: fleet.maintenance_permit(mid))
        job = self._fleet_read(lambda: fleet.job(permit["job_id"]))
        status = (job or {}).get("status")
        if view is None or view.get("state") == "granted" or job is None or status in ("queued", "dispatching"):
            return self._maintenance_result(ctx, pending=True, reason_code="maintenance_canary_pending")
        if status == "unknown":
            raise DeliveryRefused("maintenance_reconciliation_required", "job")
        if status in JOB_FAILED:
            if ctx["check"]:
                raise DeliveryRefused("maintenance_failed", "job")
            self._maintenance_fail(ctx, generation, "maintenance_failed", "job")
        if not (view.get("state") == "admitted"
                or (view.get("state") == "closed" and view.get("close_reason") == "maintenance_settled")):
            raise DeliveryRefused("maintenance_canary_unbound", "admission")
        if self.canary_records is None:
            raise DeliveryRefused("maintenance_canary_unbound", "canary_records")
        try:
            action = self.canary_records(permit["action_id"])
        except Exception:
            raise DeliveryRefused("maintenance_canary_unbound", "canary_records") from None
        state = (action or {}).get("state") if isinstance(action, dict) else None
        if state == OWNER_ACTION_REQUESTED:
            return self._maintenance_result(ctx, pending=True, reason_code="maintenance_canary_pending")
        if state == OWNER_ACTION_REJECTED:
            if ctx["check"]:
                raise DeliveryRefused("maintenance_failed", "action")
            self._maintenance_fail(ctx, generation, "maintenance_failed", "action")
        if state != COMPLETED or action.get("id") != permit["action_id"]:
            raise DeliveryRefused("maintenance_canary_unbound", "action")
        incumbent, receipt = self._bind_validate(ctx, host, target, observed, generation, action)
        if ctx["check"]:
            return self._maintenance_result(ctx)
        now = self.clock()

        def bind_in(tx, _claim):
            fresh = self._snapshot_in(tx, plan)
            if maintenance_of(fresh["intent"]) != generation:
                raise DeliveryRefused("maintenance_stale", "generation")
            if self._expired_at(arm["deadline"]):
                raise DeliveryRefused("maintenance_stale", "deadline")
            self._require_unchanged(generation, fresh, arm.get("intent_sha256"), arm.get("descriptor_row_sha256"))
            maintenance_transition(generation, GENERATION_BOUND)
            new = generation["launched"]["receipt"]["instance_id"]
            bound = {**generation, "state": GENERATION_BOUND, "updated_at": now,
                     "canary": {"action_id": permit["action_id"], "job_id": permit["job_id"],
                                "receipt_sha256": digest(receipt),
                                "outcome": {"state": "accepted",
                                            "reason_code": (action.get("outcome") or {}).get("reason_code")},
                                "bound_at": now, "settlement": None},
                     "observations": [*generation.get("observations", []),
                                      self._observation("bind", GENERATION_BOUND, None, None, now)]}
            intent = fresh["intent"]
            tx.put(BUCKET_INTENTS, plan["plan_id"], {
                **intent, "stage": ACTIVE, "previous_stage": AWAITING_CONSUMPTION, "outcome": OUTCOME_ACTIVE,
                "reason_code": None, "error_type": None, "attempts": 0, "instance_id": new, "canary": incumbent,
                "stage_deadline": None, "stage_entered_at": now, "updated_at": now, "generations": [bound]})
            tx.put(BUCKET_DESCRIPTORS, plan["target_id"], {**fresh["descriptor_row"], "consumed": True,
                                                           "instance_id": new, "updated_at": now})
            ctx["g"] = bound

        # One lane transaction: ownership, generation, deadline and source hashes, then consumed/new
        # instance and `bound`. No promotion, queue or pointer write.
        holder = self._maintenance_hold(mid, bind_in)
        try:
            self.state.emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
                "stage": ACTIVE, "previous_stage": AWAITING_CONSUMPTION})
            LOGGER.warning("maintenance bound plan=%s id=%s", plan["plan_id"], mid)
            settled = self._bind_settle(ctx, holder)
        finally:
            self._maintenance_release(holder)
        if not settled:
            return self._maintenance_result(ctx, pending=True, reason_code="maintenance_reconciliation_required")
        return self._maintenance_result(ctx)

    def _bind_validate(self, ctx: dict, host, target: dict, observed: dict, generation: dict, action: dict) -> tuple:
        """The shared domain canary binding over a PROSPECTIVE consumed view, in memory only: nothing is
        stored as passed before it holds (HME `require_canary`, unchanged)."""
        plan, snap = ctx["plan"], ctx["snap"]
        intent = snap["intent"]
        reader, requests = getattr(host, "owner_canary", None), getattr(host, "owner_canary_request", None)
        if reader is None or requests is None:
            raise DeliveryRefused("maintenance_canary_unbound", "receipt")
        try:
            receipt = reader(target, plan["plan_id"])
        except Exception:
            raise DeliveryRefused("maintenance_canary_unbound", "receipt") from None
        try:
            request = requests(target, plan["plan_id"])
        except Exception:
            raise DeliveryRefused("maintenance_canary_unbound", "request") from None
        if not isinstance(receipt, dict) or receipt.get("unreadable") is True:
            raise DeliveryRefused("maintenance_canary_unbound", "receipt")
        if isinstance(request, dict) and request.get("unreadable") is True:
            raise DeliveryRefused("maintenance_canary_unbound", "request")
        live = observed["receipt"]
        startup = {key: live[key] for key in ("instance_id", "pid", "runtime_root", "module_root", "revision")}
        descriptor = intent["descriptor"]
        incumbent = self.state.canary(plan, target, descriptor, startup)
        try:
            lineage = validate_managed_lineage({"owner": "managed", "descriptor": descriptor,
                                                "instance_id": live["instance_id"], "plan_id": plan["plan_id"]})
            consumed = {"target": {key: target.get(key) for key in sorted(MANAGED_TARGET_FIELDS)}, "plan": plan,
                        "plan_sha256": snap["plan_row"]["plan_sha256"], "descriptor": descriptor,
                        "descriptor_sha256": intent["descriptor_sha256"], "instance_id": live["instance_id"],
                        "lineage": lineage}
            require_canary(consumed, incumbent, receipt, request, action, intent={"canary": incumbent},
                           started_at=generation["launched"]["receipt"]["started_at"])
        except MigrationRefused as exc:
            raise DeliveryRefused("maintenance_canary_unbound", _safe_field(exc.field) or "canary") from None
        return incumbent, copy.deepcopy(receipt)

    def _bind_settle(self, ctx: dict, holder: dict) -> bool:
        """Close the control permit (`maintenance_settled`), then acknowledge that in the lane. A failure
        leaves `settlement: None` for a bind replay; it never resumes the Fleet."""
        fleet, generation = self.maintenance_fleet, ctx["g"]
        if fleet is None:
            return False
        try:
            fleet.close_maintenance_canary(generation["arm"]["permit"], "maintenance_settled")
        except Exception:
            return False
        mid, now = ctx["mid"], self.clock()

        def acknowledge(intent, _row):
            current = self._expect_generation(intent, mid, GENERATION_BOUND)
            return self._with_generation(intent, {
                **current, "canary": {**current["canary"], "settlement": {"state": "closed", "at": now}}}), None

        try:
            ctx["g"] = self._maintenance_owned(holder, ctx, acknowledge)
        except DeliveryRefused:
            return False
        return True

    # --- failure, expiry and control settlement ------------------------------------------------------
    def _maintenance_fail(self, ctx: dict, generation: dict, code: str, field: str, holder=None):
        """Control first (a still-queued canary is cancelled without a spawn; settled admitted work is
        closed; admitted reserving work is left for a later settle), then the lane failure. No rollback,
        no host effect, no second generation."""
        self._fail_control(ctx, generation)
        self._record_failure(ctx, generation, code, field, holder)
        raise DeliveryRefused(code, field)

    def _fail_control(self, ctx: dict, generation: dict) -> None:
        arm, fleet = generation.get("arm"), self.maintenance_fleet
        if not isinstance(arm, dict) or fleet is None:
            return
        permit = arm["permit"]
        try:
            view = fleet.maintenance_permit(ctx["mid"])
            state = (view or {}).get("state")
            if view is None or state == "granted":
                fleet.close_maintenance_canary(permit, "maintenance_cancelled")
            elif state == "admitted" and ((fleet.job(permit["job_id"]) or {}).get("status")
                                          not in JOB_RESERVING | {None}):
                fleet.close_maintenance_canary(permit, "maintenance_settled")
            elif state == "closed" and view.get("close_reason") in UNLAUNCHED_CLOSE_REASONS:
                # INV-FLEET-001 maintenance amendment: owner-actions may have queued the canary AFTER the
                # unlaunched close (between the control close and the lane failure). The Fleet keeps such a
                # stale canary as open debt that blocks every ordinary resume; replaying the close (cached)
                # fails exactly that queued job without a launch. This replay is its only lane-side path.
                fleet.close_maintenance_canary(permit, view["close_reason"])
        except Exception:
            return    # the lane failure is still recorded; a later replay settles the control row

    def _record_failure(self, ctx: dict, generation: dict, code: str, field: str, holder=None) -> None:
        mid, plan, phase = ctx["mid"], ctx["plan"], ctx["phase"]
        now = self.clock()
        before = []

        def fail(intent, _row):
            current = self._expect_generation(intent, mid, generation.get("state"))
            maintenance_transition(current, GENERATION_FAILED)
            before.append(intent.get("stage"))
            failed = {**current, "state": GENERATION_FAILED, "updated_at": now,
                      "failure": {"code": code, "at": now},
                      "observations": [*current.get("observations", []),
                                       self._observation(phase, GENERATION_FAILED, code, field, now)]}
            # The current delivery is BLOCKED under the fixed code; its deadline, row, release, queue and
            # pointer stay; nothing is rolled back or superseded.
            return {**intent, "stage": BLOCKED, "previous_stage": intent.get("stage"), "outcome": OUTCOME_BLOCKED,
                    "reason_code": code, "error_type": None, "updated_at": now,
                    "generations": [*intent["generations"][:-1], failed]}, None

        if holder is not None:
            ctx["g"] = self._maintenance_owned(holder, ctx, fail)
        else:
            written = []
            own = self._maintenance_hold(mid, lambda tx, _claim: written.append(self._mutate_in(tx, plan, fail)))
            self._maintenance_release(own)
            ctx["g"] = maintenance_of(written[-1])
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": BLOCKED, "previous_stage": before[-1] if before else None})
        self.state.emit(EVENT_BLOCKED, "blocked", plan, severity="error", reason_code=code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "stage": before[-1] if before else None, "outcome": OUTCOME_BLOCKED,
                               "error_type": None, "attempts": 0})
        LOGGER.warning("maintenance failed plan=%s id=%s", plan["plan_id"], mid)

    def _maintenance_expire(self, ctx: dict, generation: dict):
        """The ONE arm deadline passed. An unadmitted canary is closed (its queued job failed, nothing
        launched) BEFORE the lane failure; admitted work that still reserves is never expired, only
        reconciled; settled admitted work fails the generation and then closes the permit."""
        fleet = self._maintenance_fleet_port()
        mid, permit = ctx["mid"], generation["arm"]["permit"]
        view = self._fleet_read(lambda: fleet.maintenance_permit(mid))
        state = (view or {}).get("state")
        if view is None or state == "granted":
            try:
                fleet.close_maintenance_canary(permit, "maintenance_expired")
            except Exception as exc:
                if _is_fleet_refusal(exc):
                    raise self._fleet_refusal(exc) from None
                raise DeliveryRefused("maintenance_reconciliation_required", "fleet") from None
            self._record_failure(ctx, generation, "maintenance_expired", "deadline")
            raise DeliveryRefused("maintenance_expired", "deadline")
        if state == "admitted":
            job = self._fleet_read(lambda: fleet.job(permit["job_id"]))
            if not isinstance(job, dict) or job.get("status") in JOB_RESERVING:
                raise DeliveryRefused("maintenance_reconciliation_required", "job")
            self._record_failure(ctx, generation, "maintenance_expired", "deadline")
            try:
                fleet.close_maintenance_canary(permit, "maintenance_settled")
            except Exception:
                pass      # settled later by `_settle_control` on a replay of the failed generation
            raise DeliveryRefused("maintenance_expired", "deadline")
        # Already closed (the lane failure after it was lost): a stale canary queued since then is failed
        # by the cached close replay before the lane records the failure.
        self._fail_control(ctx, generation)
        self._record_failure(ctx, generation, "maintenance_expired", "deadline")
        raise DeliveryRefused("maintenance_expired", "deadline")

    def _settle_control(self, ctx: dict, generation: dict) -> None:
        """An idempotent control close appropriate to the job's state; any error leaves it for later."""
        self._fail_control(ctx, generation)

    # --- ports, holds and owned writes --------------------------------------------------------------
    def _maintenance_host(self, ctx: dict):
        if "host" not in ctx:
            ctx["host"], ctx["target"] = self.state.host(ctx["plan"])
        if ctx["target"].get("kind") != KIND_MANAGED_SYSTEMD:
            raise DeliveryRefused("maintenance_not_active", "target_id")
        return ctx["host"], ctx["target"]

    def _maintenance_fleet_port(self):
        if self.maintenance_fleet is None:
            raise DeliveryRefused("host_port_unavailable", "maintenance_fleet")
        return self.maintenance_fleet

    def _fleet_ready(self, mid: str, own_job_id=None) -> None:
        fleet = self._maintenance_fleet_port()
        try:
            readiness = fleet.maintenance_readiness()
        except Exception:
            raise DeliveryRefused("maintenance_debt_unsettled", "fleet") from None
        refusal = fleet_ready_refusal(readiness, maintenance_id=mid, own_job_id=own_job_id)
        if refusal is not None:
            raise DeliveryRefused(*refusal)

    @staticmethod
    def _fleet_read(read):
        try:
            return read()
        except Exception:
            raise DeliveryRefused("maintenance_reconciliation_required", "fleet") from None

    def _fleet_call(self, holder: dict, ctx: dict, call):
        """One control-store call under the hold (no lane transaction open). A Fleet refusal maps to the
        same maintenance code; an unknown answer (a lost response) needs reconciliation by replay."""
        fleet = self._maintenance_fleet_port()
        try:
            return call(fleet)
        except Exception as exc:
            refusal = (self._fleet_refusal(exc) if _is_fleet_refusal(exc)
                       else DeliveryRefused("maintenance_reconciliation_required", "fleet"))
        self._maintenance_observe(holder, ctx, refusal.reason_code, refusal.field)
        raise refusal

    @staticmethod
    def _fleet_refusal(exc) -> DeliveryRefused:
        code = getattr(exc, "reason_code", None)
        if type(code) is str and code in MAINTENANCE_CODES:
            return DeliveryRefused(code, _safe_field(getattr(exc, "field", None)))
        return DeliveryRefused("maintenance_admission_refused", _safe_field(code) or "fleet")

    def _observe_generation(self, host, target: dict, code: str):
        reader = getattr(host, "generation_observation", None)
        if reader is None:
            raise DeliveryRefused("maintenance_not_active", "target_id")
        try:
            return reader(target)
        except DeliveryRefused:
            raise
        except Exception:
            raise DeliveryRefused(code, "observation") from None

    def _observe_quietly(self, host, target: dict):
        """A validated observation, or None when it could not be taken (a bounded wait retries)."""
        try:
            return validate_generation_observation(self._observe_generation(
                host, target, "maintenance_launch_unconfirmed"))
        except DeliveryRefused:
            return None

    def _maintenance_identity(self, ctx: dict, host, target: dict, generation: dict, holder=None) -> dict:
        """The live identity is exactly the started generation. A definite difference fails the
        generation; an unknown or a pending reload refuses with nothing written."""
        raw = self._observe_generation(host, target, "maintenance_launch_unconfirmed")
        refusal = new_generation_refusal(ctx["snap"]["intent"]["descriptor"], raw, generation)
        if refusal is not None:
            if refusal[0] == "maintenance_invocation_mismatch" and not ctx["check"]:
                self._maintenance_fail(ctx, generation, refusal[0], refusal[1], holder)
            raise DeliveryRefused(*refusal)
        return validate_generation_observation(raw)

    def _maintenance_credentials(self, target: dict, observed: dict, generation: dict) -> dict:
        """The pinned helper's safe PRIMARY evidence bound to the observed supervisor/entry and invocation,
        and the unchanged source selection. Never a bare boolean assertion; nothing is written on refusal."""
        port = self.credentials
        if port is None:
            raise DeliveryRefused("maintenance_primary_unverified", "credentials")
        identity = {"supervisor_pid": observed["supervisor"]["pid"], "entry_pid": observed["entry"]["pid"],
                    "invocation_id": observed["unit"]["invocation_id"]}
        try:
            record = port(target, identity)
        except DeliveryRefused as exc:
            if exc.reason_code == "maintenance_primary_unverified":
                raise
            raise DeliveryRefused("maintenance_primary_unverified", "credentials") from None
        except Exception:
            raise DeliveryRefused("maintenance_primary_unverified", "credentials") from None
        checked = validate_credential_evidence(record, observed)
        selection = selection_of(observed)
        if selection != (generation.get("retiring") or {}).get("selection") \
                or selection != (generation.get("launched") or {}).get("selection"):
            raise DeliveryRefused("maintenance_primary_unverified", "selection")
        return checked

    def _maintenance_hold(self, mid: str, within) -> dict:
        """The short controller hold (one transaction, `within` inside it); busy is a refusal."""
        try:
            claim = self.lease.hold_maintenance(mid, now=self.state.now(), within=within)
        except DeliveryRefused:
            raise
        except ContractError:
            raise DeliveryRefused("maintenance_controller_busy", "controller") from None
        if claim is None:
            raise DeliveryRefused("maintenance_controller_busy", "controller")
        return {"claim": claim}

    def _maintenance_release(self, holder) -> None:
        """Release in `finally`, only while still the exact owner; a successor's lease is never cleared."""
        if not holder:
            return
        try:
            self.lease.release_maintenance(holder["claim"], now=self.state.now())
        except Exception:
            pass

    def _maintenance_authorizer(self, holder: dict):
        """Handed to the adapter: renews the lease at the guard's entry and after the stop, or raises."""
        return lambda: holder.update(claim=self.lease.heartbeat_maintenance(holder["claim"], now=self.state.now()))

    def _unchanged_in(self, ctx: dict, generation: dict, intent_sha256, descriptor_row_sha256, mutate=None):
        """A `within` CAS: the generation and every pinned source are unchanged; then `mutate` (optional)."""
        plan = ctx["plan"]

        def within(tx, _claim):
            fresh = self._snapshot_in(tx, plan)
            if maintenance_of(fresh["intent"]) != generation:
                raise DeliveryRefused("maintenance_stale", "generation")
            self._require_unchanged(generation, fresh, intent_sha256, descriptor_row_sha256)
            if mutate is not None:
                ctx["g"] = maintenance_of(self._mutate_in(tx, plan, mutate))

        return within

    @staticmethod
    def _require_unchanged(generation: dict, snap: dict, intent_sha256, descriptor_row_sha256) -> None:
        refusal = _maintenance_unchanged(generation, snap, intent_sha256=intent_sha256,
                                         descriptor_row_sha256=descriptor_row_sha256)
        if refusal is not None:
            raise DeliveryRefused(*refusal)

    @staticmethod
    def _mutate_in(tx, plan: dict, mutate) -> dict:
        intent = copy.deepcopy(tx.get(BUCKET_INTENTS, plan["plan_id"]))
        row = copy.deepcopy(tx.get(BUCKET_DESCRIPTORS, plan["target_id"]))
        settled, row2 = mutate(intent, row)
        tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        if row2 is not None:
            tx.put(BUCKET_DESCRIPTORS, plan["target_id"], row2)
        return settled

    def _maintenance_owned(self, holder: dict, ctx: dict, mutate) -> dict:
        """ONE lane transaction that re-checks the hold (owner, fence, unexpired lease), re-reads and
        writes. A lost hold is `maintenance_stale(controller)`; the recorded generation is returned."""
        try:
            with self.store.transaction() as tx:
                self.lease.owned_maintenance(tx, holder["claim"], self.state.now())
                settled = self._mutate_in(tx, ctx["plan"], mutate)
        except DeliveryRefused:
            raise
        except ContractError:
            raise DeliveryRefused("maintenance_stale", "controller") from None
        return maintenance_of(settled)

    def _maintenance_observe(self, holder, ctx: dict, reason_code: str, field) -> None:
        """Append one truthful observation after a durable request, while the hold is still owned; a lost
        hold records nothing (the next owner observes for itself)."""
        if not holder or ctx.get("g") is None:
            return
        mid, now = ctx["mid"], self.clock()

        def observe(intent, _row):
            current = maintenance_of(intent)
            if current is None or current.get("id") != mid:
                raise DeliveryRefused("maintenance_stale", "generation")
            return self._with_generation(intent, {
                **current, "observations": [*current.get("observations", []), self._observation(
                    ctx["phase"], current.get("state"), reason_code, _safe_field(field), now)]}), None

        try:
            ctx["g"] = self._maintenance_owned(holder, ctx, observe)
        except Exception:
            pass

    @staticmethod
    def _observation(phase: str, state, reason_code, field, at: str) -> dict:
        return {"phase": phase, "state": state, "reason_code": reason_code, "field": field, "at": at}

    @staticmethod
    def _expect_generation(intent, mid: str, state) -> dict:
        current = maintenance_of(intent)
        if current is None or current.get("id") != mid or current.get("state") != state:
            raise DeliveryRefused("maintenance_stale", "generation")
        return current

    @staticmethod
    def _with_generation(intent: dict, generation: dict) -> dict:
        return {**intent, "generations": [*intent["generations"][:-1], generation]}

    @staticmethod
    def _aware(value):
        try:
            moment = datetime.fromisoformat(value) if type(value) is str else None
        except ValueError:
            return None
        return moment if moment is not None and moment.tzinfo is not None else None

    def _expired_at(self, deadline) -> bool:
        moment = self._aware(deadline)
        return moment is None or self.state.now() >= moment

    def _maintenance_result(self, ctx: dict, *, cached=False, pending=False, reason_code=None, field=None,
                            refusal=None) -> dict:
        """The typed `maintain` result: ids, digests, codes and times only; nothing else is relayed."""
        generation = ctx.get("g") if isinstance(ctx.get("g"), dict) else {}
        doc = ctx.get("doc") or {}
        retiring = doc.get("retiring") or {}
        launched = generation.get("launched") if isinstance(generation.get("launched"), dict) else {}
        arm = generation.get("arm") if isinstance(generation.get("arm"), dict) else {}
        permit = arm.get("permit") if isinstance(arm.get("permit"), dict) else {}
        refs = (generation.get("prior") or {}).get("evidence_refs")
        if refusal is not None:
            reason_code, field = refusal.reason_code, refusal.field
        return {"schema": MAINTENANCE_RESULT_SCHEMA, "maintenance_id": ctx.get("mid"),
                "phase": ctx.get("phase") if ctx.get("phase") in MAINTENANCE_PHASES else None,
                "check": bool(ctx.get("check")), "applicable": refusal is None,
                "state": generation.get("state"), "cached": bool(cached), "pending": bool(pending),
                "reason_code": reason_code, "field": _safe_field(field),
                "identities": {"plan_id": doc.get("plan_id"), "release_id": doc.get("release_id"),
                               "target_id": doc.get("target_id"), "descriptor_sha256": doc.get("descriptor_sha256"),
                               "retiring_instance_id": retiring.get("instance_id"),
                               "retiring_invocation_id": retiring.get("invocation_id"),
                               "new_instance_id": (launched.get("receipt") or {}).get("instance_id"),
                               "new_invocation_id": launched.get("invocation_id"),
                               "action_id": permit.get("action_id") or ctx.get("action_id"),
                               "job_id": permit.get("job_id") or ctx.get("job_id")},
                "deadline": arm.get("deadline") or ctx.get("deadline"),
                "evidence": {"document": ctx.get("evidence_ref"), "authority": doc.get("authority"),
                             "prior": dict(refs) if isinstance(refs, dict) else None},
                "authority": AUTHORITY}


def _is_fleet_refusal(exc) -> bool:
    """A Fleet refusal as the control port raises it: a fixed-code ContractError (coordination's `FleetRefused`;
    delivery imports no coordination). A delivery refusal is never one, and any other error is an unknown answer."""
    return (isinstance(exc, ContractError) and not isinstance(exc, DeliveryRefused)
            and type(getattr(exc, "reason_code", None)) is str)


def _safe_field(value) -> str | None:
    """A relayed field is a fixed identifier or nothing (INV-HOST-DELIVERY-MAINTENANCE-001)."""
    return value if type(value) is str and SAFE_FIELD.fullmatch(value) else None


def _without_generations(intent) -> dict:
    return {key: value for key, value in (intent or {}).items() if key != "generations"}


def _by_id(rows) -> dict:
    return {str((row or {}).get("id")): row for row in rows or []}


def _maintenance_unchanged(generation: dict, snap: dict, *, intent_sha256, descriptor_row_sha256) -> tuple | None:
    """The drift predicate every phase re-runs (INV-HOST-DELIVERY-MAINTENANCE-001): the intent minus its
    generations and the descriptor row still digest to the phase's pins, the release, pointer and queue are
    the prior ones, and no competing delivery or reserving migration appeared on the target."""
    prior = (generation or {}).get("prior") or {}
    doc = (generation or {}).get("document") or {}
    if (snap.get("plan_row") or {}).get("plan_sha256") != doc.get("plan_sha256"):
        return ("maintenance_stale", "plan_sha256")
    if intent_sha256 is None or digest(_without_generations(snap.get("intent"))) != intent_sha256:
        return ("maintenance_stale", "intent")
    if descriptor_row_sha256 is None or digest(snap.get("descriptor_row")) != descriptor_row_sha256:
        return ("maintenance_stale", "descriptor_row")
    if digest(snap.get("release")) != prior.get("release_sha256"):
        return ("maintenance_stale", "release_id")
    if (snap.get("pointer") or {}).get("release_id") != (prior.get("pointer") or {}).get("release_id"):
        return ("maintenance_stale", "pointer")
    if digest(snap.get("queue")) != prior.get("queue_sha256"):
        return ("maintenance_stale", "queue")
    target_id, plan_id = doc.get("target_id"), doc.get("plan_id")
    if any(competing_intent(other, target_id, plan_id) for other in snap.get("intents") or []) or any(
            isinstance(m, dict) and m.get("target_id") == target_id and m.get("state") in MIGRATION_RESERVING
            for m in snap.get("migrations") or []):
        return ("maintenance_target_busy", "target_id")
    return None


__all__ = ["FLEET_PERMIT_SCHEMA", "JOB_FAILED", "JOB_RESERVING", "JOB_SETTLED", "MAINTENANCE_AUTHORITY_MAX_BYTES",
           "PRIOR_INTENT_FIELDS", "DeliveryMaintenance"]
