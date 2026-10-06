"""Opt-in autonomous v2: research -> read-only DB snapshot -> DBA report -> research lead -> improvement
lead -> conductor -> existing Operation v2 -> promotion (INV-COUNCIL-001).

`CouncilRun` is the v1 state machine (`AutonomousRun`) with the v2 profile threaded through: the same
`autonomous_runs` row, transitions, role dispatch (six-W outbox -> bus -> executor), execution
evidence binding, owned DGE session, child operation and promotion transaction. What is new is bounded:
one read-only repeatable-read observation through the injected snapshot port, persisted
content-addressed through the executor artifact store and frozen in the run row as reference,
digest and safe metadata; the DBA's report relayed to the leads through the conductor after the
workflow verified the persisted task result; a freshness and integrity guard on the SAME frozen
observation before every downstream role and before the implementation (no refresh mid-debate); and
a promotion recheck of the DBA binding, the snapshot and the report next to the unchanged worker and
reviewer gates. A v1 manifest handed to this class runs the v1 flow untouched.

Bounded inline input (`domain/council_input.py`, urn:zeus:council-input:2): the frozen packet is admitted
right after `_freeze_packet` and before the snapshot or the DBA, the normalized DBA report before the relay
and either lead, and each lead's complete derived proposal before `sessions.submit` or the next role, each
against the exact prefix committed so far (shared pool, ordered future reservations; a pure calculation with
no run-level credit). An overflow ends the run with the precise `needs_scope_split:<section>:<observed>/<limit>`
reason (status `failed`, the existing enum); the original role evidence, task rows and artifacts stay as
recorded and nothing is retried, summarized, dropped or resized.
"""
from __future__ import annotations

import re

from codex_harness.application.autonomous import (
    BLOCKER_RULE,
    BUCKET,
    AutonomousRefused,
    AutonomousRun,
    _safe_binding,
)
from codex_harness.application.dge import DgeRefused
from codex_harness.domain.autonomous import (
    CONDUCTOR,
    RESEARCHER,
    ROLE_ACTION,
    event_from_role,
    evidence_ref_for,
    independent_roles,
    role_binding,
    role_message_id,
)
from codex_harness.domain.council import (
    CONDUCTOR_ROLE,
    COUNCIL_AGENTS,
    COUNCIL_DEBATE,
    DBA,
    IMPROVEMENT_LEAD,
    INTERNAL_SLOT,
    RESEARCH_LEAD,
    CouncilFieldRefused,
    SnapshotError,
    check_snapshot,
    council_output,
    profile,
    report_digest,
    report_from_dba,
    snapshot_coverage,
    snapshot_digest,
    snapshot_selection,
    validate_snapshot,
)
from codex_harness.domain.council_input import (
    DBA_REPORT,
    IMPROVEMENT_PROPOSAL,
    PACKET,
    REASON,
    RESEARCH_PROPOSAL,
    CouncilInputOverflow,
    admit,
)
from codex_harness.domain.model import ContractError, canonical, require, utcnow

SNAPSHOT_SOURCE = "council-snapshot:"
SNAPSHOT_REFUSALS = {"snapshot_unavailable", "snapshot_corrupt", "snapshot_mismatch", "snapshot_stale"}
# urn:zeus:council-input:2 producer gates: which lead proposal is bounded before it is submitted or handed on.
PROPOSAL_SECTION = {RESEARCH_LEAD: RESEARCH_PROPOSAL, IMPROVEMENT_LEAD: IMPROVEMENT_PROPOSAL}
# A consumer-side overflow reaches the run as a role task whose error is the executor's typed refusal; only this
# exact safe shape (section, digits) is lifted into the run's reason code, never free text. The executor records
# its own pre-entry refusal through `Workflow.fail(..., retryable=True)` (the provider never started), so the row
# is `retry`; a failure the workflow settled as not retryable is `failed`. Both are legitimate carriers of the
# typed reason and neither is re-dispatched here.
CONSUMER_OVERFLOW = re.compile(r"^CouncilInputOverflow: (" + re.escape(REASON) + r":[a-z_]+:\d+/\d+)$")
CONSUMER_REFUSAL_OUTCOMES = {"role_failed", "role_retry"}


class CouncilRun(AutonomousRun):
    def __init__(self, service, executor=None, bus=None, workflow=None, budget=None, collector=None, verify_sources=None,
                 repository=None, observer=None, clock=utcnow, evidence=None, snapshot=None, artifacts=None):
        super().__init__(service, executor, bus, workflow, budget, collector, verify_sources, repository, observer, clock, evidence)
        # `snapshot.observe(...)` is the read-only port; `artifacts.put(body, source)` the executor's content store.
        self.snapshot, self.artifacts = snapshot, artifacts

    def _pipeline(self, manifest, identity, goal, row, wrapped) -> dict:
        if profile(manifest)["version"] != 2:
            return super()._pipeline(manifest, identity, goal, row, wrapped)
        require(self.snapshot is not None and self.artifacts is not None, "Council run needs a snapshot port and an artifact store")
        run_id, base, correlation = row["id"], manifest["base_revision"], row["correlation_id"]
        research, frozen, sessions, digest_value = self._freeze_packet(manifest, goal, row, wrapped)
        packet = frozen["packet"]
        # urn:zeus:council-input:2: the frozen packet is admitted BEFORE the snapshot or any DBA start; the
        # researcher's raw evidence and the packet itself stay exactly as recorded, the run stops with the reason.
        # `committed` is the exact ordered prefix every later admission is measured against: the very values
        # the downstream roles receive inline, extended only after each one is admitted.
        committed = {}
        self._admit(PACKET, packet, committed)
        committed[PACKET] = packet
        claim_ids = {c["id"] for c in packet["claims"]}
        # ----- one read-only observation, frozen before any DBA start ----------------------------------
        self._transition(run_id, "packet", "snapshot")
        observed = self._observe(manifest, row)
        # ----- DBA: interpretation of the frozen snapshot, bound like every role ----------------------
        self._guard(manifest, row, observed)
        self._transition(run_id, "snapshot", DBA)
        dba_details = {"role": DBA, "run_id": run_id, "base_revision": base, "packet_digest": digest_value, "packet": packet,
                       "ssot": frozen["ssot"], "snapshot_digest": observed["sha256"], "snapshot": observed["envelope"],
                       "deadline": manifest["deadline"]}
        dba = self._role(manifest, row, wrapped, DBA, dba_details)
        try:
            report = report_from_dba(dba["answer"], snapshot_digest_value=observed["sha256"], claim_ids=claim_ids)
        except ContractError as exc:
            raise AutonomousRefused("report_invalid") from exc
        self._admit(DBA_REPORT, report, committed)  # the normalized report, before the relay and before either lead
        committed[DBA_REPORT] = report
        relay = self._relay(correlation, dba["task_id"], COUNCIL_AGENTS[DBA])
        frozen_report = {"task_id": dba["task_id"], "sha256": report_digest(report), "snapshot_digest": observed["sha256"],
                         "execution_ref": dba["execution_ref"], "input_ref": evidence_ref_for(dba_details), "relay_message_id": relay}
        self._transition(run_id, DBA, None, report=frozen_report)
        identities = {"snapshot_digest": observed["sha256"], "report_digest": frozen_report["sha256"]}
        # ----- research lead -> improvement lead -> conductor on the internal proposer/attacker/arbiter slots -----
        prior, version, bindings, previous = {}, 0, {RESEARCHER: research, DBA: dba}, DBA
        for role in COUNCIL_DEBATE:
            self._guard(manifest, row, observed)
            self._transition(run_id, previous, role)
            details = {"role": role, "run_id": run_id, "base_revision": base, "packet_digest": digest_value, "packet": packet,
                       "ssot": frozen["ssot"], "round": 1, "prior_outputs": prior, **identities, "dba_report": report,
                       "relay": {"dba_task_id": dba["task_id"], "message_id": relay, "via": CONDUCTOR},
                       "acceptance_criteria": manifest["plan"]["acceptance_criteria"], "blocker_rule": BLOCKER_RULE}
            if role in (IMPROVEMENT_LEAD, CONDUCTOR_ROLE):
                details["research_proposal"] = prior[RESEARCH_LEAD]["proposal"]
            if role == CONDUCTOR_ROLE:
                details["improvement_proposal"] = prior[IMPROVEMENT_LEAD]["proposal"]  # the full alternative, not findings only
            binding = self._role(manifest, row, wrapped, role, details)
            bindings[role] = binding
            try:
                independent_roles(bindings)
                derived = council_output(role, binding["answer"], identities, claim_ids)
                if role in PROPOSAL_SECTION:
                    # The complete derived proposal (the value the next role receives inline) is admitted
                    # against the committed prefix before sessions.submit and before any downstream role; the
                    # typed overflow is caught ahead of the generic ContractError mapping so the run names
                    # needs_scope_split. The prefix grows only once the proposal is admitted.
                    admit(PROPOSAL_SECTION[role], derived["proposal"], committed)
                    committed[PROPOSAL_SECTION[role]] = derived["proposal"]
                event = event_from_role(INTERNAL_SLOT[role], derived["event_payload"], digest_value, version, binding["task_id"])
                recorded = sessions.submit(row["session_id"], event, owner=run_id, binding=_safe_binding(binding))
            except CouncilInputOverflow as exc:
                raise AutonomousRefused(exc.reason_code) from exc
            except CouncilFieldRefused as exc:
                # The fixed `council_field_invalid:<role>.<field>:<problem>` code, never the text; the output
                # and its artifact stay as recorded (no truncation, retry or relaxed bound).
                raise AutonomousRefused(exc.reason_code) from exc
            except DgeRefused as exc:
                raise AutonomousRefused("debate_refused:" + exc.reason_code) from exc
            except ContractError as exc:
                code = str(exc)
                raise AutonomousRefused(code if code in {"role_session_shared", "council_identity_mismatch"}
                                        else "debate_refused:" + type(exc).__name__) from exc
            if role == CONDUCTOR_ROLE:
                self._relay(correlation, binding["task_id"], CONDUCTOR)  # the self-arbitration result goes through the workflow too
            prior[role] = {"event_id": event["id"], "slot": INTERNAL_SLOT[role], "payload": event["payload"],
                           "proposal": derived["proposal"], "binding": _safe_binding(binding)}
            version, previous = recorded["session"]["version"], role
        return self._implement_and_promote(
            manifest, identity, goal, row, wrapped, research, prior, recorded["session"], CONDUCTOR_ROLE,
            council=lambda tx: self._recheck(tx, manifest, row, observed, frozen_report, claim_ids),
            before_implementation=lambda: self._guard(manifest, row, observed))

    # ----- bounded input (urn:zeus:council-input:2) -----------------------------------------
    @staticmethod
    def _admit(section: str, value, committed: dict) -> int:
        """Producer gate: the section's canonical UTF-8 bytes against its allowance after the exact committed
        prefix (future reservations held), or the run ends with the precise `needs_scope_split:<section>:
        <observed>/<allowance>` reason. No retry, summary, drop or resize."""
        try:
            return admit(section, value, committed)
        except CouncilInputOverflow as exc:
            raise AutonomousRefused(exc.reason_code) from exc

    def _role(self, manifest, row, wrapped, role, details) -> dict:
        """The executor's own consumer gate (projection or final prompt over the policy) refuses the role task
        before any provider entry (`retry`, or `failed` once settled as not retryable); the run reports that exact
        needs_scope_split reason instead of `role_retry`/`role_failed` and never retries the role. Any other
        outcome, and any error text outside the safe shape, keeps the unchanged code."""
        try:
            return super()._role(manifest, row, wrapped, role, details)
        except AutonomousRefused as exc:
            if exc.reason_code not in CONSUMER_REFUSAL_OUTCOMES:
                raise
            with self.service.store.transaction() as tx:
                task = tx.get("tasks", role_message_id(manifest, role)) or {}
            matched = CONSUMER_OVERFLOW.match(task.get("error") or "") if isinstance(task.get("error"), str) else None
            if matched is None:
                raise
            raise AutonomousRefused(matched.group(1)) from exc

    # ----- snapshot -----------------------------------------------------------------------
    def _observe(self, manifest, row) -> dict:
        """One observation through the port; a connection or read failure refuses the run (never an
        empty observation). The envelope is persisted content-addressed and only references, digests
        and safe metadata enter the run row."""
        run_id, base, topic = row["id"], manifest["base_revision"], manifest["research"]["topic"]
        selection, max_age = snapshot_selection(manifest), manifest["current_state"]["max_age_seconds"]
        self._log("snapshot", run_id, "started")
        self._check_deadline(manifest)
        envelope, refused = None, None
        try:
            envelope = validate_snapshot(self.snapshot.observe(selection, topic=topic, run_id=run_id, base_revision=base,
                                                               max_age_seconds=max_age))
        except ContractError as exc:
            refused = getattr(exc, "reason_code", "snapshot_unavailable")
        except Exception:  # the adapter maps its own failures; anything else is still not an observation
            refused = "snapshot_unavailable"
        if refused is not None:
            # Raised OUTSIDE the handler: neither __cause__ nor __context__ keeps the port's exception
            # (a driver error can carry the DSN or row text), so no traceback chain can print it.
            raise AutonomousRefused(refused if refused in SNAPSHOT_REFUSALS else "snapshot_unavailable")
        if (envelope["topic"], envelope["run_id"], envelope["base_revision"], envelope["selection"]) != (topic, run_id, base, selection):
            raise AutonomousRefused("snapshot_mismatch")
        stored = self.artifacts.put(canonical(envelope), SNAPSHOT_SOURCE + run_id)
        frozen = {"ref": stored["ref"], "sha256": snapshot_digest(envelope), "observed_at": envelope["observed_at"],
                  "expires_at": envelope["expires_at"], "database_identity": envelope["database_identity"],
                  "coverage": snapshot_coverage(envelope)}
        self._transition(run_id, "snapshot", None, snapshot=frozen)
        self._log("snapshot", run_id, "succeeded")
        return {**frozen, "envelope": envelope, "selection": selection}

    def _guard(self, manifest, row, observed) -> dict:
        """Before each downstream role and the implementation: absolute deadline, then the SAME frozen
        observation re-read from the artifact store and checked for integrity, binding and age. A
        missing, corrupt, swapped or stale snapshot stops with its code; nothing refreshes it."""
        self._check_deadline(manifest)
        with self.service.store.transaction() as tx:
            current = tx.get(BUCKET, row["id"]) or {}
        recorded = current.get("snapshot")
        if not recorded or recorded != {k: observed[k] for k in recorded}:
            raise AutonomousRefused("snapshot_missing")
        document = self._frozen_document(recorded["ref"])
        try:
            return check_snapshot(document, expected_digest=recorded["sha256"], topic=manifest["research"]["topic"], run_id=row["id"],
                                  base_revision=manifest["base_revision"], selection=observed["selection"], now=self.clock())
        except SnapshotError as exc:
            raise AutonomousRefused(exc.reason_code) from exc

    def _frozen_document(self, ref: str):
        """The persisted envelope through the evidence port, or a fixed snapshot code: bytes that no longer
        hash to the reference or do not parse are `snapshot_corrupt`, anything else `snapshot_missing`."""
        try:
            return self.evidence.document(ref)
        except ContractError as exc:
            code = getattr(exc, "reason_code", "")
            raise AutonomousRefused("snapshot_corrupt" if code in {"evidence_corrupt", "evidence_invalid"} else "snapshot_missing") from exc
        except Exception as exc:
            raise AutonomousRefused("snapshot_missing") from exc

    # ----- relay --------------------------------------------------------------------------
    def _relay(self, correlation: str, task_id: str, sender: str) -> str:
        """The conductor consumes its stream: the role's `task.result` must reach the workflow (which
        re-verifies the persisted task row) before its content is handed on to the next lead."""
        handled = self._deliver(CONDUCTOR, correlation)
        for message in handled:
            if message["type"] == "task.result" and message["who"]["sender"] == sender \
                    and message["what"]["action"] == ROLE_ACTION and message["what"]["details"].get("task_id") == task_id:
                return message["message_id"]
        raise AutonomousRefused("report_not_relayed")

    # ----- promotion recheck --------------------------------------------------------------
    def _recheck(self, tx, manifest, row, observed, frozen_report, claim_ids) -> dict:
        """Inside the promotion transaction: the DBA task row and artifact bind again, the report
        re-derives to the frozen digest and the snapshot document is still the frozen observation."""
        base, correlation = manifest["base_revision"], row["correlation_id"]
        task = tx.get("tasks", frozen_report["task_id"])
        try:
            binding = role_binding(task, role=DBA, base_revision=base, correlation=correlation, agent=COUNCIL_AGENTS[DBA])
            evidence = self._verify_execution(tx, task, "tasks", "dge:" + DBA, base, frozen_report["input_ref"], exact=True)
            report = report_from_dba(binding["answer"], snapshot_digest_value=observed["sha256"], claim_ids=claim_ids)
            if report_digest(report) != frozen_report["sha256"] or binding["execution_ref"] != frozen_report["execution_ref"]:
                raise ContractError("report_mismatch")
        except ContractError as exc:
            raise AutonomousRefused("promotion_report_unproven:" + str(exc).split(":")[-1].strip()) from exc
        try:
            check_snapshot(self._frozen_document(observed["ref"]), expected_digest=observed["sha256"],
                           topic=manifest["research"]["topic"], run_id=row["id"], base_revision=base,
                           selection=observed["selection"], now=None)
        except (AutonomousRefused, SnapshotError) as exc:  # both carry a fixed snapshot_* code, never content
            raise AutonomousRefused("promotion_snapshot_unproven:" + exc.reason_code) from exc
        refs = {"version": 2, "topology": row["topology"],
                "dba": {"task_id": task["id"], "execution_ref": binding["execution_ref"], "output_sha256": binding["output_sha256"],
                        "reservation_id": evidence["reservation_id"]},
                "snapshot": {k: observed[k] for k in ("ref", "sha256", "observed_at", "expires_at", "database_identity", "coverage")},
                "report": {"sha256": frozen_report["sha256"], "snapshot_digest": frozen_report["snapshot_digest"]}}
        return {"refs": refs, "evidence": {"dba_task_id": task["id"], "dba_reservation_id": evidence["reservation_id"],
                                           "snapshot_sha256": observed["sha256"], "report_sha256": frozen_report["sha256"]}}


__all__ = ["CouncilRun"]
