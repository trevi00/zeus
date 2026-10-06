"""Active-generation maintenance of an ACTIVE, consumed managed delivery: the owner's restart phase.

Layer: application
Context: delivery
Owns: no bucket of its own (the one new key `generations` of an intent is written through the maintenance hold, in the
same transaction that re-checks the hold)
Does not own: review's releases and release_queue rows and the controller lease (the MaintenanceLease port), the
Fleet's pause and held units (the FleetReadiness port, read only), the host target and its generation observation
(the host port), the authority, artifact and owner-action stores (injected callables and objects)
Entry points: DeliveryMaintenance.maintain, .maintain_restart
Contracts: INV-HOST-DELIVERY-MAINTENANCE-001

Ported from main b9d8f15 (S2R) `application/host_delivery.py` (the hunks after M7 e38aa722): the bodies are S2R's,
placed in the target's split HostDelivery as its own object (`maintain` is `Recovery`'s sibling); S2R's `self._host`,
`self._now`, `self._parent` are `DeliveryState.host`, `.now`, `.parent` and its `self.queue.*_maintenance` calls go
through the `MaintenanceLease` port. The target holds of the S2R guards (`_maintenance_held` and `_maintenance_hold_of`)
are `DeliveryState.maintenance_held` and `state.maintenance_hold_in`. This release carries the restart phase only:
`arm` and `bind` are PR-3's remainder (G1-14).
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
)
from codex_harness.delivery.domain.host_delivery import (
    AUTHORITY,
    DIGEST_HEX,
    EVIDENCE_REF,
    KIND_MANAGED_SYSTEMD,
    MIGRATION_RESERVING,
    OWNER_CANARY_RECEIPT_SCHEMA,
    DeliveryRefused,
    LifecycleInterrupted,
    consumption_verdict,
    release_gate,
)
from codex_harness.delivery.domain.host_migration_evidence import (
    CANARY_RECEIPT_FIELDS,
    COMPLETED,
    DELIVERY_CANARY,
    DESCRIPTOR_ROW_FIELDS,
    record_view,
)
from codex_harness.delivery.domain.maintenance import (
    GENERATION_ARMED,
    GENERATION_BOUND,
    GENERATION_FAILED,
    GENERATION_LAUNCHED,
    GENERATION_REQUESTED,
    GENERATION_STARTED,
    MAINTENANCE_PHASES,
    MAINTENANCE_RESULT_SCHEMA,
    RESTART_REPLACE,
    classify_restart,
    competing_intent,
    fleet_ready_refusal,
    generation_id,
    maintenance_applicable,
    maintenance_of,
    maintenance_transition,
    selection_of,
    validate_active_generation,
    validate_generation_observation,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest

# INV-HOST-DELIVERY-MAINTENANCE-001: the prior ACTIVE binding fields a maintenance copies into `prior`, the
# authority bytes bound, and the one shape of a relayed field.
PRIOR_INTENT_FIELDS = ("stage", "outcome", "instance_id", "canary", "candidate_instance_id", "candidate_launch",
                       "previous_instance_id", "previous_launch", "stage_deadline", "stage_entered_at", "updated_at",
                       "descriptor_sha256")
MAINTENANCE_AUTHORITY_MAX_BYTES = 262144
SAFE_FIELD = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


class DeliveryMaintenance:
    """The restart phase of an active-generation maintenance (S2R `HostDelivery.maintain`): one owner document, one
    short controller hold per write, and every external action strictly between short store transactions."""

    def __init__(self, store, *, org=None, clock=None, state=None, lease=None, authorities=None, artifacts=None,
                 canary_records=None, maintenance_fleet=None):
        self.store, self.org, self.clock, self.state, self.lease = store, org, clock, state, lease
        # INV-HOST-DELIVERY-MAINTENANCE-001 ports of the restart phase, all absent by default (a missing one
        # refuses by name): `authorities(ref) -> bytes` the trusted read-only authority store;
        # `artifacts.put(body, source)` the content-addressed evidence store; `canary_records(action_id)` the
        # control-store owner action row, read only; `maintenance_fleet` the control-store Fleet's read-only
        # maintenance readiness.
        self.authorities, self.artifacts, self.canary_records = authorities, artifacts, canary_records
        self.maintenance_fleet = maintenance_fleet

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
    def maintain(self, document, evidence_ref, phase, *, check=False, startup_seconds=120.0, poll_seconds=1.0) -> dict:
        """One maintenance phase of one owner document (this release: `restart`). With `check` every refusal is
        RETURNED as `applicable: False` and nothing is held, put, written or started."""
        if phase == "restart":
            return self.maintain_restart(document, evidence_ref, check=check, startup_seconds=startup_seconds,
                                         poll_seconds=poll_seconds)
        # ALL-PRIMARY-20260930: this release carries the restart phase only. `arm` and `bind` (the paused
        # one-canary admission and the new-instance consumption) are the named remainder of PR-3; the
        # generation stays open (`started`, not re-qualified) and every hold stays in force until then.
        refusal = DeliveryRefused("maintenance_phase", "phase")
        if check:
            return self._maintenance_result({"phase": None, "check": True}, refusal=refusal)
        raise refusal

    def maintain_restart(self, document, evidence_ref, *, check=False, startup_seconds=120.0,
                         poll_seconds=1.0) -> dict:
        return self._maintenance_run("restart", document, evidence_ref, check,
                                     lambda ctx: self._maintain_restart(ctx, startup_seconds, poll_seconds))

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


__all__ = ["MAINTENANCE_AUTHORITY_MAX_BYTES", "PRIOR_INTENT_FIELDS", "DeliveryMaintenance"]
