"""The owner's recovery commands.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: review's releases and release_queue rows (the ReleaseAuthority/ReleaseClaims/ReleaseSettlement ports), the ticket binding (intake, injected), the runtime (the host port)
Entry points: Recovery
Contracts: INV-HOST-DELIVERY-FIRST-ACTIVATION-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime

from codex_harness.delivery.application.host_delivery.resumption import replay_of
from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    LOGGER,
    deadline_from,
    launch_record,
    lifecycle,
    record_effect,
    replaces,
)
from codex_harness.delivery.domain.host_delivery import (
    AWAITING_CONSUMPTION,
    CONSUMPTION_RETRY_RESTART_FIELD,
    EVENT_STAGE,
    EVIDENCE_REF,
    MERGED,
    OUTCOME_PENDING,
    OUTCOME_PROGRESSED,
    RECOVERY_CONSUMPTION_REARM,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_FIRST_ACTIVATION,
    RECOVERY_GENERATION_RESTART,
    RESTART_LAUNCHED,
    RESTART_REQUESTED,
    RESTART_STARTED,
    TERMINAL_STAGES,
    DeliveryRefused,
    consumption_rearmable,
    consumption_retryable,
    consumption_verdict,
    first_activation_resumable,
    first_activation_unbound,
    generation_restart_of,
    generation_restartable,
    recoveries_of,
    release_gate,
    validate_consumption_rearm,
    validate_consumption_retry,
    validate_first_activation,
    validate_generation_restart,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest, utcnow


def first_activation_gate(gate: dict) -> None:
    """The release must already be VERIFIED: this recovery never re-enters verification."""
    if gate["state"] == "approved" and gate["status"] == "verified":
        return
    code = gate.get("reason_code") or "release_" + str(gate.get("status"))
    raise DeliveryRefused("first_activation_" + (code if code.startswith("release_") else "release_" + code),
                          "release_id")


def rearm_descriptor(intent: dict, current_row, rearm: dict) -> None:
    """The descriptor row is the bound, never consumed one, and observes EXACTLY the spent retry's instance (the
    retry's ordinary consumption tick recorded its startup), which is also the intent's candidate."""
    row = current_row or {}
    if (row.get("descriptor") != intent["descriptor"]
            or row.get("descriptor_sha256") != intent["descriptor_sha256"]
            or rearm["descriptor_sha256"] != intent["descriptor_sha256"]):
        raise DeliveryRefused("consumption_rearm_descriptor_mismatch", "descriptor_sha256")
    if row.get("consumed") or row.get("instance_id") is not None or not row.get("startup_observed"):
        raise DeliveryRefused("consumption_rearm_descriptor_state", "descriptor_sha256")
    if not (row.get("observed_instance_id") == rearm["observed_instance_id"]
            == intent.get("candidate_instance_id")):
        raise DeliveryRefused("consumption_rearm_instance_mismatch", "observed_instance_id")


def restart_descriptor(intent: dict, current_row, restart: dict) -> None:
    """The recorded descriptor row is exactly the bound, observed, never consumed one of the STOPPED
    instance the document names (the same row the one consumption retry reads)."""
    row = current_row or {}
    if (row.get("descriptor") != intent["descriptor"]
            or row.get("descriptor_sha256") != intent["descriptor_sha256"]
            or restart["descriptor_sha256"] != intent["descriptor_sha256"]):
        raise DeliveryRefused("generation_restart_descriptor_mismatch", "descriptor_sha256")
    if row.get("consumed") or row.get("instance_id") is not None or not row.get("startup_observed"):
        raise DeliveryRefused("generation_restart_descriptor_state", "descriptor_sha256")
    if not (row.get("observed_instance_id") == restart["stopped_instance_id"]
            == intent.get("candidate_instance_id")):
        raise DeliveryRefused("generation_restart_instance_mismatch", "stopped_instance_id")


def restart_stopped(host, target: dict, intent: dict, restart: dict) -> dict:
    """The TRUSTED host shows THIS descriptor and the named instance POSITIVELY not running: its own
    receipt still names it, and nothing runs. A live instance is the consumption retry's case."""
    try:
        identity = host.identity(target)
    except Exception as exc:
        raise DeliveryRefused("generation_restart_host_unobservable", "target_id") from exc
    if identity.get("descriptor_sha256") != intent["descriptor_sha256"]:
        raise DeliveryRefused("generation_restart_host_descriptor_changed", "descriptor_sha256")
    if identity.get("running") is None:
        raise DeliveryRefused("generation_restart_host_unobservable", "target_id")
    if identity.get("running") is True:
        raise DeliveryRefused("generation_restart_instance_running", "stopped_instance_id")
    if identity.get("instance_id") != restart["stopped_instance_id"]:
        raise DeliveryRefused("generation_restart_instance_mismatch", "stopped_instance_id")
    return {"instance_id": restart["stopped_instance_id"], "descriptor_sha256": intent["descriptor_sha256"],
            "launch": intent.get("candidate_launch"), "observed_launch": identity.get("launch")}


def restart_receipt(host, target: dict, intent: dict, recorded: dict, startup_seconds: float,
                     poll_seconds: float):
    """The new generation's OWN fresh receipt: this descriptor, a running instance other than the stopped
    one. Bounded wait; None when it has not confirmed yet (the launch stays recorded, nothing restarts)."""
    stopped = (recorded.get("stopped") or {}).get("instance_id")
    deadline = time.monotonic() + max(0.0, startup_seconds)
    while True:
        try:
            receipt = host.receipt(target)
            verdict = consumption_verdict(intent["descriptor"], receipt)
            running = host.running(target)
        except Exception:
            receipt, verdict, running = None, {"consumed": False}, False
        if verdict.get("consumed") and verdict.get("instance_id") not in (None, stopped) and running:
            return {**{key: verdict.get(key) for key in ("instance_id", "pid", "revision", "runtime_root",
                                                         "module_root")},
                    "started_at": receipt.get("started_at") if isinstance(receipt, dict) else None}
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(0.0, poll_seconds))


def retry_gate(gate: dict) -> None:
    """The release must be VERIFIED and not yet promoted: the retry never re-enters verification."""
    if gate["state"] == "approved" and gate["status"] == "verified":
        return
    code = gate.get("reason_code") or "release_" + str(gate.get("status"))
    raise DeliveryRefused("consumption_retry_" + (code if code.startswith("release_") else "release_" + code),
                          "release_id")


def retry_descriptor(intent: dict, current_row, retry: dict, restarted: dict | None = None) -> None:
    """The recorded descriptor row is exactly the bound, observed, never consumed one. After a linked
    generation restart the row still names the STOPPED instance (it is never rewritten), and the retry
    names exactly the instance the restart started."""
    row = current_row or {}
    if (row.get("descriptor") != intent["descriptor"]
            or row.get("descriptor_sha256") != intent["descriptor_sha256"]
            or retry["descriptor_sha256"] != intent["descriptor_sha256"]):
        raise DeliveryRefused("consumption_retry_descriptor_mismatch", "descriptor_sha256")
    if row.get("consumed") or row.get("instance_id") is not None or not row.get("startup_observed"):
        raise DeliveryRefused("consumption_retry_descriptor_state", "descriptor_sha256")
    if restarted is not None:
        stopped = (restarted.get("stopped") or {}).get("instance_id")
        started = (restarted.get("started") or {}).get("instance_id")
        if not (row.get("observed_instance_id") == stopped == intent.get("candidate_instance_id")
                and started not in (None, stopped) and retry["observed_instance_id"] == started):
            raise DeliveryRefused("consumption_retry_instance_mismatch", "observed_instance_id")
        return
    if not (row.get("observed_instance_id") == retry["observed_instance_id"]
            == intent.get("candidate_instance_id")):
        raise DeliveryRefused("consumption_retry_instance_mismatch", "observed_instance_id")


class Recovery:
    """The owner's recovery commands: the first-activation binding, the consumption retry and re-arm, and the
    generation restart."""

    def __init__(self, store, *, org=None, clock=utcnow, claims=None, settlement=None, first_activation=None,
                 ticket_binding, resumption=None, state=None):
        self.store = store
        self.org = org
        self.clock = clock
        self.claims = claims
        self.settlement = settlement
        self.first_activation = first_activation
        self.ticket_binding = ticket_binding
        self.resumption = resumption
        self.state = state

    # ----- first activation binding (INV-HOST-DELIVERY-FIRST-ACTIVATION-001) ---------------------
    def resume_first_activation(self, plan_id: str, plan_sha256: str, document, evidence_ref: str) -> dict:
        """Bind a FIRST managed deployment's concrete tuple and move it from `blocked` back to `merged`.

        `evidence_ref` is exactly `"sha256:" + digest(document)`: the SHA-256 of the document's
        canonical JSON (sorted keys, `,`/`:` separators, UTF-8, no ASCII escaping) as
        `domain.model.canonical` writes it. Any other reference is refused before anything is read.

        Read-only first: the plan, its digest and pin digest, the `first_activation_resumable` shape,
        the recorded halt, the VERIFIED release and its candidate identity, the absence of any
        predecessor descriptor, active deployment of this release or other open delivery of the target,
        a free controller lease, a conductor approver who is not the candidate author, and the trusted
        port's re-derived image, image source revision and committed profile digest. Approval strings
        are never evidence: the document's values must EQUAL the port's. Then ONE transaction re-checks
        all of it (CAS), re-arms the stopped queue row through `ReleaseQueue.retry` exactly as `resume`
        does and writes `merged` with the binding recorded in `recoveries`. It never re-enters
        `verifying` and creates no claim, lease or generation; the next ordinary tick binds the
        descriptor in `_prepare_switch`, and everything after it is unchanged.

        The same evidence answers `cached` at any later stage; a different one is `resume_conflict`.
        """
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("resume_evidence_invalid", "evidence")
        binding = validate_first_activation(document)
        document_sha256 = digest(binding)
        if evidence_ref != "sha256:" + document_sha256:
            raise DeliveryRefused("first_activation_evidence_mismatch", "evidence")
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
                intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
                queued = tx.get("release_queue", row["plan"]["release_id"]) if row is not None else None
                current_row = tx.get(BUCKET_DESCRIPTORS, row["plan"]["target_id"]) if row is not None else None
                active = tx.get("deployment", "active") or {}
                others = [other for other in tx.scan(BUCKET_INTENTS)] if row is not None else []
                lock = tx.get("deployment_locks", "controller") or {}
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256 or binding["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("resume_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        if binding["plan_id"] != plan["plan_id"]:
            raise DeliveryRefused("first_activation_plan_mismatch", "plan_id")
        if (row.get("pin") or {}).get("sha256") != binding["pin_sha256"]:
            raise DeliveryRefused("first_activation_pin_mismatch", "pin_sha256")
        replayed = self.resumption.resume_replay(plan, intent, evidence_ref, RECOVERY_FIRST_ACTIVATION)
        if replayed is not None:
            return replayed
        if not first_activation_resumable(intent) or not first_activation_unbound(plan):
            raise DeliveryRefused("resume_not_applicable", "stage")
        halted = {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code", "updated_at")}
        if binding["halt"] != halted:
            raise DeliveryRefused("first_activation_halt_mismatch", "halt")
        for key, expected in (("release_id", plan["release_id"]), ("target_id", plan["target_id"]),
                              ("candidate_revision", plan["revision"]), ("candidate_tree", plan["tree"])):
            if binding[key] != expected:
                raise DeliveryRefused("first_activation_" + key + "_mismatch", key)
        try:
            with self.store.transaction() as tx:
                record = tx.get("releases", plan["release_id"])
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        first_activation_gate(release_gate(record, plan, self.state.parent(record)))
        candidate = (record or {}).get("candidate") or {}
        if (candidate.get("revision"), candidate.get("tree")) != (binding["candidate_revision"],
                                                                   binding["candidate_tree"]):
            raise DeliveryRefused("first_activation_candidate_mismatch", "candidate_revision")
        self._first_activation_host(plan, current_row, active, others, lock)
        self._first_activation_approver(binding["approved_by"], candidate.get("author"))
        observed = self._first_activation_facts(plan, binding)
        now = self.clock()
        recovery = {"kind": RECOVERY_FIRST_ACTIVATION, "evidence_ref": evidence_ref,
                    "binding": {"worker_image": binding["worker_image"],
                                "profile_digest": binding["profile_digest"],
                                "image_source_revision": binding["qualification"]["image_source_revision"],
                                "qualification_evidence": binding["qualification"]["evidence"]},
                    "halted": {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code",
                                                                "outcome", "attempts", "error_type",
                                                                "updated_at")},
                    "observed": observed, "approved_by": binding["approved_by"],
                    "document_sha256": document_sha256, "at": now}
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_INTENTS, plan["plan_id"])
                settled = (None if replay_of(current, evidence_ref, RECOVERY_FIRST_ACTIVATION)
                           else self._first_activation_in(tx, row, intent, queued, current, recovery, now))
        except DeliveryRefused:
            raise
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if settled is None:
            # A concurrent same-evidence resume committed first: its record answers, nothing written.
            return self.resumption.resumed(plan, current, cached=True, evidence_ref=evidence_ref,
                                 kind=RECOVERY_FIRST_ACTIVATION)
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": MERGED, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery first activation bound plan=%s from=%s", plan["plan_id"], intent["stage"])
        return self.resumption.resumed(plan, settled, cached=False, kind=RECOVERY_FIRST_ACTIVATION)

    def _first_activation_host(self, plan: dict, current_row, active: dict, others: list, lock: dict) -> None:
        """No predecessor descriptor, no active deployment of this release, no other open delivery of
        the target and no running controller: a first activation replaces nothing and races nothing."""
        if current_row is not None:
            raise DeliveryRefused("first_activation_predecessor_present", "target_id")
        if active.get("release_id") == plan["release_id"]:
            raise DeliveryRefused("first_activation_release_active", "release_id")
        for other in others:
            if (other.get("target_id") == plan["target_id"] and other.get("plan_id") != plan["plan_id"]
                    and other.get("stage") not in TERMINAL_STAGES):
                raise DeliveryRefused("first_activation_target_in_flight", "target_id")
        if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self.state.now():
            raise DeliveryRefused("resume_controller_running", "release_id")

    def _first_activation_approver(self, approved_by: str, author, prefix: str = "first_activation") -> None:
        """A conductor of the existing organization who is not the candidate's own author."""
        if self.org is None:
            raise DeliveryRefused(prefix + "_approver_unavailable", "approved_by")
        try:
            self.org.actor(approved_by, "conductor")
        except Exception as exc:
            raise DeliveryRefused(prefix + "_approver_invalid", "approved_by") from exc
        if approved_by == author:
            raise DeliveryRefused(prefix + "_approver_author", "approved_by")

    def _first_activation_facts(self, plan: dict, binding: dict) -> dict:
        """The trusted port's re-derivation must equal the document; a claim alone binds nothing."""
        port = self.first_activation
        if port is None:
            raise DeliveryRefused("first_activation_unavailable", "first_activation")
        try:
            facts = port(plan["revision"])
        except DeliveryRefused:
            raise
        except Exception as exc:
            raise DeliveryRefused("first_activation_unavailable", "first_activation") from exc
        if not isinstance(facts, dict):
            raise DeliveryRefused("first_activation_unavailable", "first_activation")
        for key, value, code in (
                ("worker_image", binding["worker_image"], "first_activation_image_mismatch"),
                ("profile_digest", binding["profile_digest"], "first_activation_profile_mismatch"),
                ("image_source_revision", binding["qualification"]["image_source_revision"],
                 "first_activation_qualification_mismatch")):
            if facts.get(key) != value:
                raise DeliveryRefused(code, key)
        return {key: facts[key] for key in ("worker_image", "profile_digest", "image_source_revision")}

    def _first_activation_in(self, tx, row: dict, intent: dict, queued, current, recovery: dict,
                             now: str) -> dict:
        """Phase 2, inside the one transaction (modelled on `_resume_in`); any refusal rolls it back."""
        plan = row["plan"]
        if current != intent or tx.get(BUCKET_PLANS, plan["plan_id"]) != row:
            raise DeliveryRefused("resume_intent_changed", "plan_id")
        lock = tx.get("deployment_locks", "controller") or {}
        if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self.state.now():
            raise DeliveryRefused("resume_controller_running", "release_id")
        if tx.get("release_queue", plan["release_id"]) != queued:
            raise DeliveryRefused("resume_queue_changed", "release_id")
        self._first_activation_host(plan, tx.get(BUCKET_DESCRIPTORS, plan["target_id"]),
                                    tx.get("deployment", "active") or {}, tx.scan(BUCKET_INTENTS), lock)
        record = tx.get("releases", plan["release_id"])
        first_activation_gate(release_gate(record, plan, self.state.parent(record)))
        try:
            self.ticket_binding(tx, record["candidate"])
        except ContractError as exc:
            raise DeliveryRefused("resume_release_ticket_changed", "release_id") from exc
        status = (queued or {}).get("status")
        if status in {"blocked", "failed"}:
            try:
                self.claims.retry(plan["release_id"], "host delivery first activation " + plan["plan_id"] + " "
                                 + recovery["evidence_ref"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        elif not (queued is None or status in {"queued", "retry"}
                  or (status == "running" and not self.state.leased(queued))):
            raise DeliveryRefused("resume_queue_" + str(status), "release_id")
        settled = {**current, "stage": MERGED, "previous_stage": current["stage"],
                   "outcome": OUTCOME_PROGRESSED, "reason_code": None, "error_type": None, "attempts": 0,
                   "recoveries": [*(current.get("recoveries") or []), recovery],
                   "stage_entered_at": now, "updated_at": now}
        tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled

    # ----- first-activation consumption retry (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended) ----
    def resume_consumption_retry(self, plan_id: str, plan_sha256: str, document, evidence_ref: str) -> dict:
        """Retry consumption of the SAME observed instance once, after a pending-canary expiry.

        `evidence_ref` is exactly `"sha256:" + digest(document)`, as for the first-activation binding.
        Read-only first: the plan, its digests, the `consumption_retryable` shape, the recorded halt
        including its EXPIRED deadline, the VERIFIED release and its candidate, a conductor approver who
        is not the author, the recorded binding's evidence, the descriptor row (bound, observed, never
        consumed) and the TRUSTED LIVE HOST: the host port must show the same instance, alive, reporting
        exactly this descriptor. Then ONE transaction re-checks it (CAS), re-arms the queue row through
        `ReleaseQueue.retry` and writes `awaiting_consumption` with a fresh interval derived from the
        plan's `consumption_timeout_seconds`; the original halt is kept only in the recovery record, and
        the descriptor row is never rewritten. The same evidence answers `cached` at any later stage.
        """
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("resume_evidence_invalid", "evidence")
        retry = validate_consumption_retry(document)
        document_sha256 = digest(retry)
        if evidence_ref != "sha256:" + document_sha256:
            raise DeliveryRefused("consumption_retry_evidence_mismatch", "evidence")
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
                intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
                queued = tx.get("release_queue", row["plan"]["release_id"]) if row is not None else None
                current_row = tx.get(BUCKET_DESCRIPTORS, row["plan"]["target_id"]) if row is not None else None
                active = tx.get("deployment", "active") or {}
                others = [other for other in tx.scan(BUCKET_INTENTS)] if row is not None else []
                lock = tx.get("deployment_locks", "controller") or {}
                record = tx.get("releases", row["plan"]["release_id"]) if row is not None else None
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256 or retry["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("resume_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        if retry["plan_id"] != plan["plan_id"]:
            raise DeliveryRefused("consumption_retry_plan_mismatch", "plan_id")
        if (row.get("pin") or {}).get("sha256") != retry["pin_sha256"]:
            raise DeliveryRefused("consumption_retry_pin_mismatch", "pin_sha256")
        replayed = self.resumption.resume_replay(plan, intent, evidence_ref, RECOVERY_CONSUMPTION_RETRY)
        if replayed is not None:
            return replayed
        if not consumption_retryable(intent):
            raise DeliveryRefused("resume_not_applicable", "stage")
        halted = {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                    "stage_deadline")}
        if retry["halt"] != halted:
            raise DeliveryRefused("consumption_retry_halt_mismatch", "halt")
        for key, expected in (("release_id", plan["release_id"]), ("target_id", plan["target_id"]),
                              ("candidate_revision", plan["revision"]), ("candidate_tree", plan["tree"])):
            if retry[key] != expected:
                raise DeliveryRefused("consumption_retry_" + key + "_mismatch", key)
        retry_gate(release_gate(record, plan, self.state.parent(record)))
        candidate = (record or {}).get("candidate") or {}
        if (candidate.get("revision"), candidate.get("tree")) != (retry["candidate_revision"],
                                                                   retry["candidate_tree"]):
            raise DeliveryRefused("consumption_retry_candidate_mismatch", "candidate_revision")
        self._first_activation_approver(retry["approved_by"], candidate.get("author"), "consumption_retry")
        binding = recoveries_of(intent, RECOVERY_FIRST_ACTIVATION)[0]
        if binding.get("evidence_ref") != retry["first_activation_evidence"]:
            raise DeliveryRefused("consumption_retry_first_activation_mismatch", "first_activation_evidence")
        # A recorded generation restart is EXPLICITLY linked: the document names its evidence, and the one retry
        # consumes exactly the instance that restart started (never a weaker same-instance check).
        restarted = generation_restart_of(intent)
        if (restarted is None) != (CONSUMPTION_RETRY_RESTART_FIELD not in retry):
            raise DeliveryRefused("consumption_retry_restart_link_mismatch", CONSUMPTION_RETRY_RESTART_FIELD)
        if restarted is not None and restarted.get("evidence_ref") != retry[CONSUMPTION_RETRY_RESTART_FIELD]:
            raise DeliveryRefused("consumption_retry_restart_link_mismatch", CONSUMPTION_RETRY_RESTART_FIELD)
        retry_descriptor(intent, current_row, retry, restarted)
        self._retry_host(plan, record, active, others, lock)
        receipt = self._retry_live(plan, intent, retry)
        # ONE authoritative time anchor (INV-HOST-DELIVERY-FIRST-ACTIVATION-001): the clock is read ONCE and the
        # new interval is exactly that instant + the plan's immutable timeout, so the recorded interval, the
        # intent's stage entry and deadline, and every exact-interval gate agree however the clock advances.
        now = self.clock()
        deadline = deadline_from(now, plan["consumption_timeout_seconds"])
        recovery = {"kind": RECOVERY_CONSUMPTION_RETRY, "evidence_ref": evidence_ref,
                    "document_sha256": document_sha256, "approved_by": retry["approved_by"],
                    "halted": copy.deepcopy({key: intent.get(key) for key in (
                        "stage", "previous_stage", "reason_code", "outcome", "updated_at", "stage_entered_at",
                        "stage_deadline", "rollback", "canary", "candidate_instance_id", "attempts")}),
                    "observed": {"descriptor_sha256": intent["descriptor_sha256"],
                                 "observed_instance_id": retry["observed_instance_id"], "receipt": receipt,
                                 **({CONSUMPTION_RETRY_RESTART_FIELD: restarted["evidence_ref"]}
                                    if restarted is not None else {})},
                    "interval": {"started_at": now, "deadline": deadline}, "at": now}
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_INTENTS, plan["plan_id"])
                settled = (None if replay_of(current, evidence_ref, RECOVERY_CONSUMPTION_RETRY)
                           else self._consumption_retry_in(tx, row, intent, queued, current_row, record,
                                                           current, recovery, now))
        except DeliveryRefused:
            raise
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if settled is None:
            return self.resumption.resumed(plan, current, cached=True, evidence_ref=evidence_ref,
                                 kind=RECOVERY_CONSUMPTION_RETRY)
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": AWAITING_CONSUMPTION, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery consumption retry plan=%s from=%s", plan["plan_id"], intent["stage"])
        return self.resumption.resumed(plan, settled, cached=False, kind=RECOVERY_CONSUMPTION_RETRY)

    # ----- the ONE consumption re-arm after an exhausted retry (INV-HOST-DELIVERY-FIRST-ACTIVATION-001) ----
    def resume_consumption_rearm(self, plan_id: str, plan_sha256: str, document, evidence_ref: str) -> dict:
        """Re-arm consumption of the SAME observed instance ONCE more, after the one retry expired again.

        Every read-only check of `resume_consumption_retry`, on the `consumption_rearmable` shape: the plan, pin,
        the recorded halt INCLUDING its expired deadline, the VERIFIED release and candidate, a conductor approver
        who is not the author, the first-activation evidence, the SPENT retry (the document names its evidence and
        its observed instance), the restart link when one is recorded, the descriptor row (bound, observed, never
        consumed, observing that SAME instance: the retry's ordinary consumption tick recorded it) and the TRUSTED
        live host showing that instance alive with this descriptor. The interval is the document's explicit
        `window_seconds` (bounded by CONSUMPTION_REARM_MAX_SECONDS) from ONE clock read. ONE transaction re-checks
        all of it (CAS), re-arms the queue row and writes `awaiting_consumption`; every earlier halt, deadline and
        recovery is kept. The same evidence answers `cached`; another is `resume_conflict`, and after a further
        expiry `resume_exhausted` (final).
        """
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("resume_evidence_invalid", "evidence")
        rearm = validate_consumption_rearm(document)
        document_sha256 = digest(rearm)
        if evidence_ref != "sha256:" + document_sha256:
            raise DeliveryRefused("consumption_rearm_evidence_mismatch", "evidence")
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
                intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
                queued = tx.get("release_queue", row["plan"]["release_id"]) if row is not None else None
                current_row = tx.get(BUCKET_DESCRIPTORS, row["plan"]["target_id"]) if row is not None else None
                active = tx.get("deployment", "active") or {}
                others = [other for other in tx.scan(BUCKET_INTENTS)] if row is not None else []
                lock = tx.get("deployment_locks", "controller") or {}
                record = tx.get("releases", row["plan"]["release_id"]) if row is not None else None
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256 or rearm["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("resume_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        if rearm["plan_id"] != plan["plan_id"]:
            raise DeliveryRefused("consumption_rearm_plan_mismatch", "plan_id")
        if (row.get("pin") or {}).get("sha256") != rearm["pin_sha256"]:
            raise DeliveryRefused("consumption_rearm_pin_mismatch", "pin_sha256")
        replayed = self.resumption.resume_replay(plan, intent, evidence_ref, RECOVERY_CONSUMPTION_REARM)
        if replayed is not None:
            return replayed
        if not consumption_rearmable(intent):
            raise DeliveryRefused("resume_not_applicable", "stage")
        halted = {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                    "stage_deadline")}
        if rearm["halt"] != halted:
            raise DeliveryRefused("consumption_rearm_halt_mismatch", "halt")
        for key, expected in (("release_id", plan["release_id"]), ("target_id", plan["target_id"]),
                              ("candidate_revision", plan["revision"]), ("candidate_tree", plan["tree"])):
            if rearm[key] != expected:
                raise DeliveryRefused("consumption_rearm_" + key + "_mismatch", key)
        retry_gate(release_gate(record, plan, self.state.parent(record)))
        candidate = (record or {}).get("candidate") or {}
        if (candidate.get("revision"), candidate.get("tree")) != (rearm["candidate_revision"],
                                                                   rearm["candidate_tree"]):
            raise DeliveryRefused("consumption_rearm_candidate_mismatch", "candidate_revision")
        self._first_activation_approver(rearm["approved_by"], candidate.get("author"), "consumption_rearm")
        binding = recoveries_of(intent, RECOVERY_FIRST_ACTIVATION)[0]
        if binding.get("evidence_ref") != rearm["first_activation_evidence"]:
            raise DeliveryRefused("consumption_rearm_first_activation_mismatch", "first_activation_evidence")
        spent = recoveries_of(intent, RECOVERY_CONSUMPTION_RETRY)[0]
        spent_instance = (spent.get("observed") or {}).get("observed_instance_id")
        if spent.get("evidence_ref") != rearm["retry_evidence"] or rearm["observed_instance_id"] != spent_instance:
            raise DeliveryRefused("consumption_rearm_retry_mismatch", "retry_evidence")
        restarted = generation_restart_of(intent)
        if (restarted is None) != (CONSUMPTION_RETRY_RESTART_FIELD not in rearm) or (
                restarted is not None and restarted.get("evidence_ref") != rearm[CONSUMPTION_RETRY_RESTART_FIELD]):
            raise DeliveryRefused("consumption_rearm_restart_link_mismatch", CONSUMPTION_RETRY_RESTART_FIELD)
        rearm_descriptor(intent, current_row, rearm)
        self._retry_host(plan, record, active, others, lock)
        receipt = self._retry_live(plan, intent, rearm)
        # ONE authoritative time anchor, as the retry: the interval is exactly that instant + the EXPLICIT window.
        now = self.clock()
        deadline = deadline_from(now, rearm["window_seconds"])
        recovery = {"kind": RECOVERY_CONSUMPTION_REARM, "evidence_ref": evidence_ref,
                    "document_sha256": document_sha256, "approved_by": rearm["approved_by"],
                    "authority": rearm["authority"], "retry_evidence": rearm["retry_evidence"],
                    "window_seconds": rearm["window_seconds"],
                    "halted": copy.deepcopy({key: intent.get(key) for key in (
                        "stage", "previous_stage", "reason_code", "outcome", "updated_at", "stage_entered_at",
                        "stage_deadline", "rollback", "canary", "candidate_instance_id", "attempts")}),
                    "observed": {"descriptor_sha256": intent["descriptor_sha256"],
                                 "observed_instance_id": rearm["observed_instance_id"], "receipt": receipt,
                                 **({CONSUMPTION_RETRY_RESTART_FIELD: restarted["evidence_ref"]}
                                    if restarted is not None else {})},
                    "interval": {"started_at": now, "deadline": deadline}, "at": now}
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_INTENTS, plan["plan_id"])
                settled = (None if replay_of(current, evidence_ref, RECOVERY_CONSUMPTION_REARM)
                           else self._consumption_retry_in(tx, row, intent, queued, current_row, record,
                                                           current, recovery, now, label="consumption re-arm"))
        except DeliveryRefused:
            raise
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if settled is None:
            return self.resumption.resumed(plan, current, cached=True, evidence_ref=evidence_ref,
                                 kind=RECOVERY_CONSUMPTION_REARM)
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": AWAITING_CONSUMPTION, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery consumption re-arm plan=%s from=%s window=%s", plan["plan_id"],
                       intent["stage"], rearm["window_seconds"])
        return self.resumption.resumed(plan, settled, cached=False, kind=RECOVERY_CONSUMPTION_REARM)

    # ----- generation restart of a stopped first activation (INV-HOST-DELIVERY-FIRST-ACTIVATION-001) ----
    def resume_generation_restart(self, plan_id: str, plan_sha256: str, document, evidence_ref: str, *,
                                  startup_seconds: float = 120.0, poll_seconds: float = 1.0) -> dict:
        """Restart the SAME bound descriptor ONCE after its observed generation positively stopped.

        The consumption-retry halt of a bound first activation whose observed instance is no longer running
        (a host restart ended it; its receipt remains) has nothing live for the one consumption retry. Read-only
        first, exactly as that retry: the plan, pin, halt INCLUDING its expired deadline, the VERIFIED release
        and candidate, a conductor approver who is not the author, the first-activation evidence, the bound,
        observed, never consumed descriptor row naming the stopped instance, no competing delivery or active
        pointer, and the TRUSTED host showing this descriptor with that instance NOT running. Then ONE
        transaction records the restart `requested` BEFORE any effect (the halt and deadline are kept
        unchanged; only `recoveries` grows) and re-arms the queue row; the ONE start runs under the single
        release fence through the target's own guarded lifecycle (its Fleet activation gate, reconciliation and
        one launch), authorized to replace only this delivery's own candidate. The fresh startup receipt names
        the new generation and the record becomes `started`. A lost response or a replay never starts twice:
        a launch newer than the stopped one is recognized, a live instance of this descriptor is recognized,
        and an unconfirmed launch refuses for the owner. The same evidence answers `cached` once started.
        """
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("resume_evidence_invalid", "evidence")
        restart = validate_generation_restart(document)
        document_sha256 = digest(restart)
        if evidence_ref != "sha256:" + document_sha256:
            raise DeliveryRefused("generation_restart_evidence_mismatch", "evidence")
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
                intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
                queued = tx.get("release_queue", row["plan"]["release_id"]) if row is not None else None
                current_row = tx.get(BUCKET_DESCRIPTORS, row["plan"]["target_id"]) if row is not None else None
                active = tx.get("deployment", "active") or {}
                others = [other for other in tx.scan(BUCKET_INTENTS)] if row is not None else []
                lock = tx.get("deployment_locks", "controller") or {}
                record = tx.get("releases", row["plan"]["release_id"]) if row is not None else None
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256 or restart["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("resume_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        if restart["plan_id"] != plan["plan_id"]:
            raise DeliveryRefused("generation_restart_plan_mismatch", "plan_id")
        if (row.get("pin") or {}).get("sha256") != restart["pin_sha256"]:
            raise DeliveryRefused("generation_restart_pin_mismatch", "pin_sha256")
        recorded = generation_restart_of(intent)
        if recorded is not None:
            if recorded.get("evidence_ref") != evidence_ref:
                raise DeliveryRefused("resume_conflict", "evidence")
            if recorded.get("state") == RESTART_STARTED:
                return self.resumption.resumed(plan, intent, cached=True, evidence_ref=evidence_ref,
                                     kind=RECOVERY_GENERATION_RESTART)
        elif not generation_restartable(intent):
            raise DeliveryRefused("resume_not_applicable", "stage")
        halted = {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code", "updated_at",
                                                    "stage_deadline")}
        if restart["halt"] != halted:
            raise DeliveryRefused("generation_restart_halt_mismatch", "halt")
        for key, expected in (("release_id", plan["release_id"]), ("target_id", plan["target_id"]),
                              ("candidate_revision", plan["revision"]), ("candidate_tree", plan["tree"])):
            if restart[key] != expected:
                raise DeliveryRefused("generation_restart_" + key + "_mismatch", key)
        retry_gate(release_gate(record, plan, self.state.parent(record)))
        candidate = (record or {}).get("candidate") or {}
        if (candidate.get("revision"), candidate.get("tree")) != (restart["candidate_revision"],
                                                                   restart["candidate_tree"]):
            raise DeliveryRefused("generation_restart_candidate_mismatch", "candidate_revision")
        self._first_activation_approver(restart["approved_by"], candidate.get("author"), "generation_restart")
        binding = recoveries_of(intent, RECOVERY_FIRST_ACTIVATION)[0]
        if binding.get("evidence_ref") != restart["first_activation_evidence"]:
            raise DeliveryRefused("generation_restart_first_activation_mismatch", "first_activation_evidence")
        restart_descriptor(intent, current_row, restart)
        self._retry_host(plan, record, active, others, lock)
        host, target = self.state.host(plan)
        if recorded is None:
            stopped = restart_stopped(host, target, intent, restart)
            now = self.clock()
            recovery = {"kind": RECOVERY_GENERATION_RESTART, "evidence_ref": evidence_ref,
                        "document_sha256": document_sha256, "approved_by": restart["approved_by"],
                        "reason": restart["reason"], "state": RESTART_REQUESTED,
                        "halted": copy.deepcopy({key: intent.get(key) for key in (
                            "stage", "previous_stage", "reason_code", "outcome", "updated_at", "stage_entered_at",
                            "stage_deadline", "rollback", "canary", "candidate_instance_id", "attempts")}),
                        "stopped": stopped, "at": now}
            try:
                with self.store.transaction() as tx:
                    current = tx.get(BUCKET_INTENTS, plan["plan_id"])
                    if replay_of(current, evidence_ref, RECOVERY_GENERATION_RESTART):
                        intent = current
                    else:
                        intent = self._restart_request_in(tx, row, intent, queued, current_row, record, current,
                                                          recovery)
            except DeliveryRefused:
                raise
            except Exception as exc:
                raise DeliveryRefused("resume_unobservable", "store") from exc
            LOGGER.warning("host delivery generation restart requested plan=%s stopped=%s", plan["plan_id"],
                           restart["stopped_instance_id"])
        else:
            # A recorded, not yet started restart (a held fence, a lost response or a crash): the same evidence
            # re-arms the stopped queue row under the same checks and completes it; it never starts twice.
            self._restart_rearm(plan, row, intent, queued, evidence_ref)
        return self._restart_effect(plan, host, target, evidence_ref, startup_seconds, poll_seconds)

    def _restart_rearm(self, plan: dict, row: dict, intent: dict, queued, evidence_ref: str) -> None:
        """Re-arm the queue row a recorded restart left `blocked`, in ONE transaction re-checking the intent."""
        try:
            with self.store.transaction() as tx:
                if tx.get(BUCKET_INTENTS, plan["plan_id"]) != intent or tx.get(BUCKET_PLANS, plan["plan_id"]) != row:
                    raise DeliveryRefused("resume_intent_changed", "plan_id")
                current = tx.get("release_queue", plan["release_id"])
                if current != queued:
                    raise DeliveryRefused("resume_queue_changed", "release_id")
                status = (current or {}).get("status")
                if status in {"blocked", "failed"}:
                    self.claims.retry(plan["release_id"], "host delivery generation restart " + plan["plan_id"] + " "
                                     + evidence_ref, transaction=tx)
                elif not (current is None or status in {"queued", "retry"}
                          or (status == "running" and not self.state.leased(current))):
                    raise DeliveryRefused("resume_queue_" + str(status), "release_id")
        except DeliveryRefused:
            raise
        except ContractError as exc:
            raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc

    def _restart_request_in(self, tx, row: dict, intent: dict, queued, current_row, record, current,
                            recovery: dict) -> dict:
        """Phase 2, inside ONE transaction: every read re-checked (CAS), the queue row re-armed, the restart
        recorded `requested` BEFORE any effect. The halt, its deadline and every earlier recovery are kept."""
        plan = row["plan"]
        if current != intent or tx.get(BUCKET_PLANS, plan["plan_id"]) != row:
            raise DeliveryRefused("resume_intent_changed", "plan_id")
        if tx.get(BUCKET_DESCRIPTORS, plan["target_id"]) != current_row:
            raise DeliveryRefused("generation_restart_descriptor_changed", "descriptor_sha256")
        if tx.get("releases", plan["release_id"]) != record:
            raise DeliveryRefused("generation_restart_release_changed", "release_id")
        if tx.get("release_queue", plan["release_id"]) != queued:
            raise DeliveryRefused("resume_queue_changed", "release_id")
        lock = tx.get("deployment_locks", "controller") or {}
        self._retry_host(plan, record, tx.get("deployment", "active") or {}, tx.scan(BUCKET_INTENTS), lock)
        retry_gate(release_gate(record, plan, self.state.parent(record)))
        status = (queued or {}).get("status")
        if status in {"blocked", "failed"}:
            try:
                self.claims.retry(plan["release_id"], "host delivery generation restart " + plan["plan_id"] + " "
                                 + recovery["evidence_ref"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        elif not (queued is None or status in {"queued", "retry"}
                  or (status == "running" and not self.state.leased(queued))):
            raise DeliveryRefused("resume_queue_" + str(status), "release_id")
        settled = {**current, "recoveries": [*(current.get("recoveries") or []), recovery]}
        tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled

    def _restart_effect(self, plan: dict, host, target: dict, evidence_ref: str, startup_seconds: float,
                        poll_seconds: float) -> dict:
        """The ONE start of the restart, under the single release fence, then the fresh receipt."""
        try:
            claim = self.claims.claim(now=self.state.now(), eligible=lambda queued: queued["id"] == plan["release_id"])
        except ContractError as exc:
            raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        if claim is None:
            # Another controller holds the host lease (or the row is not runnable): the recorded request
            # stays, and the same evidence completes it later; nothing was started here.
            raise DeliveryRefused("resume_controller_running", "release_id")
        self.state.emit_queue_wait(claim)
        state = "unconfirmed"
        try:
            with self.store.transaction() as tx:
                self.claims.owned(tx, claim, self.state.now())
                intent = tx.get(BUCKET_INTENTS, plan["plan_id"])
            recorded = generation_restart_of(intent)
            if recorded is None or recorded.get("evidence_ref") != evidence_ref:
                raise DeliveryRefused("resume_intent_changed", "plan_id")
            if recorded.get("state") == RESTART_REQUESTED:
                launch = launch_record(host, target)
                if launch is not None and launch != (recorded.get("stopped") or {}).get("observed_launch"):
                    # A launch newer than the stopped generation's: this restart already started it and lost
                    # the response. It is recognized, never started a second time.
                    started = {"started": False, "recovered": True, "launch": launch}
                else:
                    self.state.owned_now(claim)
                    started = lifecycle(lambda: host.start(
                        target, intent["descriptor"], authorize=self.state.authorizer(claim),
                        replaces=replaces(intent, forward=False)))
                intent = record_effect("generation_restart_launched", lambda: self._restart_state(
                    plan, claim, evidence_ref, RESTART_LAUNCHED,
                    launch={"record": started.get("launch") or launch_record(host, target),
                            "started": bool(started.get("started")), "recovered": bool(started.get("recovered"))}))
                recorded = generation_restart_of(intent)
            receipt = restart_receipt(host, target, intent, recorded, startup_seconds, poll_seconds)
            if receipt is None:
                state = RESTART_LAUNCHED
            else:
                intent = record_effect("generation_restart_started", lambda: self._restart_state(
                    plan, claim, evidence_ref, RESTART_STARTED, started=receipt))
                state = RESTART_STARTED
                LOGGER.warning("host delivery generation restart started plan=%s instance=%s", plan["plan_id"],
                               receipt["instance_id"])
        finally:
            try:
                self.settlement.finish(claim, {"status": "blocked", "reason": "generation_restart_" + state}, self.state.now())
            except ContractError:
                pass
        if state != RESTART_STARTED:
            raise DeliveryRefused("generation_restart_launch_unconfirmed", "target_id")
        return self.resumption.resumed(plan, intent, cached=False, evidence_ref=evidence_ref, kind=RECOVERY_GENERATION_RESTART)

    def _restart_state(self, plan: dict, claim, evidence_ref: str, state: str, **fields) -> dict:
        """One owned transaction: the restart record advances; nothing else on the intent changes."""
        with self.store.transaction() as tx:
            self.claims.owned(tx, claim, self.state.now())
            intent = tx.get(BUCKET_INTENTS, plan["plan_id"])
            recoveries = list(intent.get("recoveries") or [])
            index = next(i for i, rec in enumerate(recoveries)
                         if rec.get("kind") == RECOVERY_GENERATION_RESTART and rec.get("evidence_ref") == evidence_ref)
            recoveries[index] = {**recoveries[index], "state": state, **fields, state + "_at": self.clock()}
            settled = {**intent, "recoveries": recoveries}
            tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
            return settled

    def _retry_host(self, plan: dict, record, active: dict, others: list, lock: dict) -> None:
        """No active pointer or promotion of this release, no competing delivery, no running controller."""
        if active.get("release_id") == plan["release_id"] or (record or {}).get("status") == "active":
            raise DeliveryRefused("consumption_retry_release_active", "release_id")
        for other in others:
            if (other.get("target_id") == plan["target_id"] and other.get("plan_id") != plan["plan_id"]
                    and other.get("stage") not in TERMINAL_STAGES):
                raise DeliveryRefused("consumption_retry_target_in_flight", "target_id")
        if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self.state.now():
            raise DeliveryRefused("resume_controller_running", "release_id")

    def _retry_live(self, plan: dict, intent: dict, retry: dict) -> dict:
        """The TRUSTED live host, through the same port `_consume` reads: the same instance, alive,
        reporting exactly this descriptor. Anything else is a named refusal and nothing is written."""
        host, target = self.state.host(plan)
        try:
            identity = host.identity(target)
            verdict = consumption_verdict(intent["descriptor"], host.receipt(target))
        except Exception as exc:
            raise DeliveryRefused("consumption_retry_host_unobservable", "target_id") from exc
        if identity.get("descriptor_sha256") != intent["descriptor_sha256"]:
            raise DeliveryRefused("consumption_retry_host_descriptor_changed", "descriptor_sha256")
        if not verdict["consumed"] or identity.get("instance_id") is None:
            raise DeliveryRefused("consumption_retry_instance_missing", "observed_instance_id")
        if verdict["instance_id"] != retry["observed_instance_id"] \
                or identity.get("instance_id") != retry["observed_instance_id"]:
            raise DeliveryRefused("consumption_retry_instance_changed", "observed_instance_id")
        if identity.get("running") is not True:
            raise DeliveryRefused("consumption_retry_instance_stopped", "observed_instance_id")
        return {key: verdict.get(key) for key in ("instance_id", "pid", "revision")}

    def _consumption_retry_in(self, tx, row: dict, intent: dict, queued, current_row, record, current,
                              recovery: dict, now: str, label: str = "consumption retry") -> dict:
        """Phase 2, inside the one transaction (modelled on `_first_activation_in`)."""
        plan = row["plan"]
        if current != intent or tx.get(BUCKET_PLANS, plan["plan_id"]) != row:
            raise DeliveryRefused("resume_intent_changed", "plan_id")
        if tx.get(BUCKET_DESCRIPTORS, plan["target_id"]) != current_row:
            raise DeliveryRefused("consumption_retry_descriptor_changed", "descriptor_sha256")
        if tx.get("releases", plan["release_id"]) != record:
            raise DeliveryRefused("consumption_retry_release_changed", "release_id")
        if tx.get("release_queue", plan["release_id"]) != queued:
            raise DeliveryRefused("resume_queue_changed", "release_id")
        lock = tx.get("deployment_locks", "controller") or {}
        self._retry_host(plan, record, tx.get("deployment", "active") or {}, tx.scan(BUCKET_INTENTS), lock)
        retry_gate(release_gate(record, plan, self.state.parent(record)))
        try:
            self.ticket_binding(tx, record["candidate"])
        except ContractError as exc:
            raise DeliveryRefused("resume_release_ticket_changed", "release_id") from exc
        status = (queued or {}).get("status")
        if status in {"blocked", "failed"}:
            try:
                self.claims.retry(plan["release_id"], "host delivery " + label + " " + plan["plan_id"] + " "
                                 + recovery["evidence_ref"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        elif not (queued is None or status in {"queued", "retry"}
                  or (status == "running" and not self.state.leased(queued))):
            raise DeliveryRefused("resume_queue_" + str(status), "release_id")
        restarted = generation_restart_of(current)
        candidate = {} if restarted is None else {
            # The linked restart's generation is now this delivery's own candidate: a rollback replaces it.
            "candidate_instance_id": (restarted.get("started") or {}).get("instance_id"),
            "candidate_launch": (restarted.get("launch") or {}).get("record") or current.get("candidate_launch")}
        settled = {**current, "stage": AWAITING_CONSUMPTION, "previous_stage": current["stage"],
                   "outcome": OUTCOME_PENDING, "reason_code": None, "error_type": None, "attempts": 0,
                   "rollback": None, "canary": None, **candidate,
                   "recoveries": [*(current.get("recoveries") or []), recovery],
                   "stage_entered_at": now, "stage_deadline": recovery["interval"]["deadline"],
                   "updated_at": now}
        tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled
