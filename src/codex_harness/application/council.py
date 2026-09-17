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
"""
from __future__ import annotations

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
)
from codex_harness.domain.council import (
    CONDUCTOR_ROLE,
    COUNCIL_AGENTS,
    COUNCIL_DEBATE,
    DBA,
    IMPROVEMENT_LEAD,
    INTERNAL_SLOT,
    RESEARCH_LEAD,
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
from codex_harness.domain.model import ContractError, canonical, require, utcnow

SNAPSHOT_SOURCE = "council-snapshot:"
SNAPSHOT_REFUSALS = {"snapshot_unavailable", "snapshot_corrupt", "snapshot_mismatch", "snapshot_stale"}


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
                event = event_from_role(INTERNAL_SLOT[role], derived["event_payload"], digest_value, version, binding["task_id"])
                recorded = sessions.submit(row["session_id"], event, owner=run_id, binding=_safe_binding(binding))
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
