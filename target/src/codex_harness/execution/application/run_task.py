"""RunTask: claim one task, invoke its provider, and record the outcome (REBUILD-DESIGN-v2 §2.4, §2.9; S4).

Layer: application
Context: execution
Owns: RunTask.execute_one and the invocation core `_run` (M7 `adapters/executor.py` `Executor.execute_one/_run`
    and the helpers of one task execution: task sessions, the continued workspace, the output evaluation, the
    policy refusal, the failure disposition, the reconciliation block, the lost execution and the task failure),
    transcribed by script with a named substitution table (A/evidence/rebuild/s4/DESIGN-run-task.md §5, §8):
    every non-owner write, fence, clock, id and S8 collaborator goes through an injected port or object
Does not own: the lease rules and coordination writes (coordination, through TaskLedger/TaskLifecycle and
    ExecutionRecords), the breaker (InvocationAdmission), session checkpoints (SessionCheckpoint), the Observer,
    context composition (context.ContextComposer, the §5 seam), the transports (execution.adapters.transports)
    and result persistence (execution.adapters, injected); the S8 collaborators (council delivery, correction
    feedback, evidence inspection, project evidence, role/front-desk execution, research sources, audit
    execution, native hook candidates) refuse when absent; the S5 continuation lanes likewise
Entry points: RunTask.execute_one, ResearchRequired
Contracts: INV-INVOCATION-001, INV-SESSION-001, INV-OBSERVATION-001, INV-CONTEXT-001, INV-WORKER-SESSION-001,
    INV-CLAUDE-WORKER-001, INV-RELEASE-001, INV-RECURRENCE-001, INV-EVIDENCE-001

Declared boundaries (DESIGN-run-task §5/§8), each an explicit refusal before any reservation or provider, never a
silent skip: council delivery and correction-feedback composition (S8); a continuation lane binding (S5); an
evidence profile, evidence inspection, role/front-desk execution, research sources, audit execution and native
hook candidates without their port (S8). Everything else is M7's body with the substitutions.
"""

from __future__ import annotations

import re
from pathlib import Path

from codex_harness.context.domain.composition import CompositionRequest, evidence_json, recovery_bound
from codex_harness.execution.domain.container_spec import (
    CLAUDE_IMPL_RW,
    ROLE_PROFILES,
    TRUSTED_PYTHON,
    WRITABLE_PROFILES,
)
from codex_harness.execution.domain.invocation import classify_result, parse_request, usage_record
from codex_harness.execution.domain.invocation_outcomes import (
    FAILURE_OWNERS,
    INVOCATION_OUTCOMES,
    OUTPUT_REASONS,
    PROVIDER_CAUSES,
    STRUCTURAL_CHECKS,
    SUBTYPE_REASONS,
    TERMINAL_SUBTYPES,
    invocation_outcome,
)
from codex_harness.execution.domain.output_contracts import (
    ACTIVITY_LOCK_SECONDS,
    GITHUB_RESEARCH,
    IMPLEMENTATION,
    OUTPUT_SEVERITY,
    PLAN,
    RESEARCH,
    SHORTLIST,
    activity_basis,
    implementation_instruction,
    invocation_options,
    sync_activity,
)
from codex_harness.execution.domain.progress_activity import (
    activity_label,
    build_receipt,
    claude_result_status,
)
from codex_harness.execution.domain.provider_stream import stream_for
from codex_harness.execution.domain.worker_sessions import MODE_RESUME, usage_delta
from codex_harness.kernel.analysis import safe_code
from codex_harness.kernel.errors import ContractError, ExecutionFailure, require
from codex_harness.kernel.ids import SYSTEM_IDS, canonical, digest, utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.routing.domain.model_selection import select_model


class ResearchRequired(ContractError):
    """RF-RT: the research-first admission did not admit this design/implementation dispatch (no provider ran)."""

    def __init__(self, disposition: str, reason: str):
        super().__init__(f"Research-first admission: {disposition} ({reason})")
        self.disposition, self.reason = disposition, reason


class RunTask:
    """The task-execution use case. Constructor-injected owners and ports only; no per-run state on the object."""

    def __init__(self, store, organization, git, artifacts, *, ledger, admission, invocations, sessions, records,
                 observer, composer, transports, results, execution_policy, review_context, host_python, ticket_binding,
                 inspect_approval, ReconciliationRequired, PostExecutionRecordFailure, policy_refusals=(),
                 worker_sessions=None, isolation=None, evidence_profile=None, knowledge=None, research=None,
                 audit_execution=None, roles=None, council=None, feedback=None, evidence_gate=None,
                 project_evidence=None, hook_candidates=None, continuations=None, research_admission=None,
                 clock=None, ids=None,
                 monotonic=None):
        # `ledger` satisfies execution.ports TaskLedger + TaskLifecycle (coordination TaskOwnership); `observer`
        # satisfies ObservationEvents + ObservationMarkers (one Observer); `results` carries the execution adapters
        # persist/tool_usage/preflight/handoff_refs/retain_evidence_handoff (an application never imports them).
        self.store, self.organization, self.git, self.artifacts = store, organization, git, artifacts
        self.ledger, self.admission, self.invocations, self.sessions = ledger, admission, invocations, sessions
        self.records, self.observer, self.composer, self.transports = records, observer, composer, transports
        self.results, self.execution_policy, self.review_context = results, execution_policy, review_context
        # The host interpreter a reader/reviewer argv names outside a role container (M7 `sys.executable`): a
        # host fact the composition supplies (context.domain.composition.artifact_reader_handle).
        self.host_python = host_python
        self.ticket_binding, self.inspect_approval = ticket_binding, inspect_approval
        self.ReconciliationRequired, self.PostExecutionRecordFailure = ReconciliationRequired, PostExecutionRecordFailure
        # A tuple of the research discovery-policy refusal types (S8); an empty tuple matches nothing.
        self.policy_refusals = tuple(policy_refusals)
        self.worker_sessions, self.isolation, self.evidence_profile = worker_sessions, isolation, evidence_profile
        self.knowledge, self.research, self.audit_execution = knowledge, research, audit_execution
        self.roles, self.council, self.feedback, self.evidence_gate = roles, council, feedback, evidence_gate
        self.project_evidence, self.hook_candidates, self.continuations = project_evidence, hook_candidates, continuations
        # RF-RT (addendum A1 v2), S4 part: consulted before a plan/implement dispatch when supplied. S8 owns the
        # package store, S5 persists the disposition, and S10 composition must wire it (PLANNED; test double only).
        self.research_admission = research_admission
        self.clock, self.ids = clock, ids or SYSTEM_IDS
        self.monotonic = monotonic or __import__("time").monotonic

    # ---- declared S5/S8 boundaries: an absent port refuses, never a silent skip (DESIGN-run-task §8) ----------
    def _require_wired(self, action: str, details) -> None:
        """S4 round-1 F1: an action whose required collaborator is absent refuses BEFORE any provider, Git,
        workspace or research-fetch effect (CE-9), instead of after them. Only presence is checked here; the
        evidence inspection and the hook candidate still run after the result exists, as in M7."""
        details = details if isinstance(details, dict) else {}
        plan = details.get("plan") if isinstance(details.get("plan"), dict) else {}
        origin = plan.get("origin") if isinstance(plan.get("origin"), dict) else {}
        if self.evidence_profile is not None:
            self._project_evidence()  # a host evidence profile needs its port for every provider action
        if action == "implement":
            self._evidence_gate()  # M7 inspects every implementation's claims after the provider returns
            if origin.get("hook"):
                self._hook_candidates()
        candidate = details.get("candidate") if isinstance(details.get("candidate"), dict) else {}
        if action == "rebase" and candidate.get("hook_id"):
            self._hook_candidates()

    def _continuation(self, details) -> dict | None:
        """The trusted continuation binding of this assignment, or None for the legacy path (M7 `_continuation`).
        The lane-store validation is S5's; without its port an attached binding refuses."""
        attached = details.get("continuation") if isinstance(details, dict) else None
        if attached is None:
            return None
        require(self.continuations is not None, "Continuation lanes are not wired")
        return self.continuations.binding(details)

    def _correction_feedback(self, continuation) -> dict | None:
        # M7 `correction_feedback.deliver(store, artifacts, None)` is None; any binding needs the S8 port.
        if continuation is None:
            return None
        require(self.feedback is not None, "Correction feedback is not wired")
        return self.feedback.deliver(self.store, self.artifacts, continuation)

    def _project_instructions(self, cwd) -> dict:
        return self._project_evidence().instructions(self.evidence_profile, cwd)

    def _project_evidence(self):
        require(self.project_evidence is not None, "Project evidence profiles are not wired")
        return self.project_evidence

    def _evidence_gate(self):
        require(self.evidence_gate is not None, "Evidence inspection is not wired")
        return self.evidence_gate

    def _roles(self):
        require(self.roles is not None, "Role execution is not wired")
        return self.roles

    def _hook_candidates(self):
        require(self.hook_candidates is not None, "Native hook candidates are not wired")
        return self.hook_candidates

    def execute_one(self, agent: str, expected: dict | None = None) -> dict | None:
        task = self.ledger.claim(agent, str(self.ids.uuid4()), expected=expected)
        if not task:
            return None
        try:
            message = task["message"]
            commands = []
            action, details = message["what"]["action"], message["what"]["details"]
            self._require_wired(action, details)
            with self.store.transaction() as tx:
                bound_ticket = self.ticket_binding(tx, details)
            if action in {"plan", "implement"}:
                with self.store.transaction() as tx:
                    self.inspect_approval(tx, details, self.artifacts)
                if self.research_admission is not None:
                    # RF-RT: research first before a design/implementation dispatch; S5 persists the disposition.
                    with self.store.transaction() as tx:
                        admitted = self.research_admission.admit(tx, task, action)
                    if admitted.get("disposition") not in {"admit", "exempt"}:
                        raise ResearchRequired(str(admitted.get("disposition")), str(admitted.get("reason")))
            def heartbeat():
                current = self.ledger.heartbeat(task)
                self.observer.emit("operations.lease_renewed", "observed", severity="debug",
                                   execution=self.observer.for_lease(task), correlation_id=self.observer.correlation(task),
                                   causation_id=task["id"], attributes={"lease_until": str(current.get("lease_until"))})
            if action in {'audit_discovery', 'audit_acquire', 'audit_partition', 'audit_propose'}:
                require(self.audit_execution is not None, 'Audit executor unavailable')
                result = self.audit_execution.execute(task)
            elif action == "research":
                require(self.research is not None, "Research provider unavailable")
                # INV-DISCOVERY-PRESSURE-001: the task states its intent; a missing one refuses before any fetch.
                sources = self.research.collect(details.get("source", "github"), intent=details.get("intent"))
                if details.get("source", "github") == "github":
                    shortlist = self._run(agent, task["id"],
                        "Shortlist exactly one repository URL from the collected entries for detailed evaluation",
                        sources, str(self.git.repository), SHORTLIST, True, heartbeat, task,
                        stage="shortlist", workload="design")
                    selected = shortlist.get("source_url")
                    require(selected in {s["url"] for s in sources["items"]},
                            "Unfetched shortlist citation")
                    detail = self.research.github_detail(selected)
                    require(detail.get("url") == selected, "Mismatched repository details")
                    require(bool(re.fullmatch(r"[0-9a-f]{40}", detail.get("revision", ""))),
                            "Invalid source revision")
                    # INV-CONTEXT-001: immutable handles and compact provenance stay
                    # required even when the compiler externalizes the README evidence.
                    readme_ref = detail.get("readme_ref", "")
                    excerpt = self.artifacts.read(readme_ref, length=10000)
                    self.artifacts.inspect(sources["artifact"])
                    provenance = {"source_url": selected, "source_revision": detail["revision"],
                        "readme_ref": readme_ref,
                        "readme_file": str(self.artifacts.root / (readme_ref[7:] + ".txt")),
                        "source_artifact": sources["artifact"],
                        "source_file": str(self.artifacts.root / (sources["artifact"][7:] + ".txt"))}
                    evidence = {"provenance": provenance, "selected_repository": next(
                        s for s in sources["items"] if s["url"] == selected),
                        "readme_excerpt": excerpt.encode("utf-8")[:10000].decode("utf-8", errors="ignore")}
                    result = self._run(agent, task["id"],
                        "Record a discovery-only candidate requiring exhaustive source audit before adoption. "
                        "Declare the exact source_url and source_revision from research_context.",
                        evidence, str(self.git.repository), GITHUB_RESEARCH, True, heartbeat, task,
                        stage="final", workload="design")
                    require(result.get("source_url") == selected, "Mismatched final research citation")
                    require(result.get("source_revision") == detail["revision"],
                            "Mismatched final source revision")
                    result["source_details"] = detail
                    result["research_provenance"] = provenance
                    result["shortlist_execution_ref"] = shortlist["execution_ref"]
                    result["research_attempt"] = task["attempt"]
                else:
                    result = self._run(agent, task["id"], "Record one discovery-only candidate; primary-source mapping and audit remain required", sources,
                                       str(self.git.repository), RESEARCH, True, heartbeat, task,
                                       workload="design")
                    require(result["source_url"] in {s["url"] for s in sources["items"]}, "Unfetched research citation")
                result["source_artifact"] = sources["artifact"]
                result["coverage_status"] = "discovery_only"
                result["adoption_eligible"] = False
            elif action == "plan":
                result = self._run(agent, task["id"], "Create an implementable improvement plan. "
                                   "Describe the future implementer's authorized changes. Current-turn "
                                   "review/planning restrictions do not prohibit the downstream implementer "
                                   "from editing its assigned workspace; do not copy them into the objective.", details,
                                   str(self.git.repository), PLAN, True, heartbeat, task,
                                   workload="design", action="plan")
                result["origin"] = details
                if details.get("plan", {}).get("origin", {}).get("hook"):
                    result["origin"]["hook"] = details["plan"]["origin"]["hook"]
                assignment = self.ledger.next_message(message, agent, "worker:implementation", "implement", {"plan": result})
                self.organization.authorize(assignment)
                commands.append(assignment)
            elif action == "implement":
                # INV-CONTINUATION-001: only the trusted lane binding an Operation claim attached
                # (never plan or model text) selects a continued workspace or a task session.
                continuation = self._continuation(details)
                # SPEC "Readable correction evidence delivery": a correction binding carries identities
                # only; its bound review findings are verified and extracted here, before any workspace
                # or provider effect, and travel inline as required context. Unusable feedback refuses.
                # The first successor after a completed research intent gets that receipt's evidence here too.
                feedback = self._correction_feedback(continuation)
                if continuation is not None and continuation["workspace"] is not None:
                    workspace = self._continued_workspace(task, continuation["workspace"])
                else:
                    workspace = self.git.prepare(task["id"], message["where"]["revision"]
                                                 if message["where"]["revision"] != "bootstrap" else "HEAD")
                task_session = continuation["session"] if continuation is not None else None
                hook = details.get("plan", {}).get("origin", {}).get("hook")
                if hook:
                    details["hook_contract"] = {"manifest": "harness_hooks/" + hook["id"] + ".json",
                        "required": "Create a standalone stdlib Python lifecycle hook. Manifest has spec "
                        "{kind:native_hook,event:PreToolUse|PostToolUse|Stop|SessionStart,matcher:string,"
                        "script_path:relative_path,script_sha256:sha256 of exact UTF-8 Git content}, "
                        "cases:{reproduction:[{input:JSON,output:JSON or null,exit_code:int}],"
                        "normal_case:[same]}. Use Codex native hook input/output contracts. "
                        "Include negative cases and actual incident reproductions; never fabricate a fix."}
                profiled = self.evidence_profile is not None
                result = self._run(agent, task["id"], implementation_instruction(profiled), details,
                                   workspace["path"], self._project_evidence().worker_schema(self.evidence_profile) if profiled else IMPLEMENTATION,
                                   False, heartbeat, task,
                                   workload="implementation", action="implement",
                                   importance=details.get("plan", {}).get("origin", {}).get("importance"),
                                   # A task-session turn is exactly one provider call (INV-WORKER-SESSION-001).
                                   **({"task_session": task_session, "max_handoffs": 1} if task_session else {}),
                                   **({"correction_feedback": feedback} if feedback is not None else {}))
                heartbeat()
                result["candidate"] = self.git.capture(workspace)
                if task_session and (result.get("task_session") or {}).get("adopted"):
                    # The exact candidate this adopted turn produced is frozen on the session; the
                    # review wait that follows holds no owner and calls nothing.
                    self.worker_sessions.submit(task_session["task_id"], {
                        key: result["candidate"][key] for key in ("revision", "tree", "base")})
                if bound_ticket:
                    result["candidate"]["zeus_ticket"] = bound_ticket
                if hook:
                    result["candidate"]["hook_id"] = hook["id"]
                if result["candidate"].get("hook_id"):
                    self._hook_candidates().candidate(result["candidate"]["hook_id"], result["candidate"])
                result["origin"] = details
                # INV-EVIDENCE-001: the worker's test claims are inspected in the workspace they came from;
                # a claim is never authority, an uninspected claim is never success.
                result["evidence_inspection"] = self._evidence_gate().inspect(task, result, workspace["path"], heartbeat)
            elif action == "dge_role":
                # INV-AUTONOMOUS-001: read-only role execution in a clean checkout at base, one entry.
                result = self._roles().execute_role(task, heartbeat)
            elif action == "frontdesk":
                # local-operations-desk-001: one read-only conversational turn in a clean checkout
                # at the request's base, with the sanitized owner-runtime monitoring capture as
                # evidence. The answer is conversation content; no candidate, approval, knowledge
                # write or follow-up assignment comes out of it.
                result = self._roles().execute_frontdesk(task, heartbeat)
            elif action == "rebase":
                heartbeat()
                candidate = self.git.rebase(task["id"], details["candidate"], details["new_base"])
                if candidate.get("hook_id"):
                    self._hook_candidates().candidate(candidate["hook_id"], candidate)
                result = {"candidate": candidate, "summary": "Rebased onto current main; approvals must be repeated",
                          "origin": details, "execution_ref": self.artifacts.put(canonical(candidate), "git-rebase")["ref"]}
            else:
                raise ValueError("Unsupported task action: " + action)
            # INV-OBSERVATION-001: the outcome and the clearing of this attempt's unconfirmed marker
            # commit together; a failed acceptance write leaves the marker, and the task blocked.
            current = self.ledger.complete(task, result, commands,
                                             accept=lambda tx, row: self.observer.close_unconfirmed(tx, task, "accepted"))
            self.observer.emit("development.task_completed", "succeeded" if current["status"] == "succeeded" else "blocked",
                               execution=self.observer.for_lease(task), correlation_id=self.observer.correlation(task),
                               causation_id=task["id"], evidence_refs=[result["execution_ref"]] if result.get("execution_ref") else [],
                               attributes={"status": current["status"], "commands": len(commands)})
            return current
        except self.ReconciliationRequired as exc:
            return self._block_for_reconciliation(task, agent, exc)
        except self.PostExecutionRecordFailure as exc:
            return self._fail_task(task, agent, exc, block=[exc.record_id])
        except self.policy_refusals as exc:
            return self._policy_refusal(task, agent, exc)
        except Exception as exc:
            error, disposition = self._failure_disposition(task, exc)
            return self._fail_task(task, agent, error, **disposition)

    def _run(self, agent: str, key: str, objective: str, evidence: dict, cwd: str,
             schema: dict, read_only: bool = False, heartbeat=None, lease=None, stage=None,
             workload: str = "final_validation", importance: str | None = None,
             action: str | None = None, max_handoffs: int = 4, delivery: dict | None = None,
             task_session: dict | None = None, correction_feedback: dict | None = None) -> dict:
        # Codex model routing still decides every Codex model and names no other provider's model.
        # Which provider runs at all comes from the packaged policy and the host configuration;
        # the assignment message and the task details never take part (INV-CLAUDE-WORKER-001).
        selection = select_model(workload, importance)
        assignment = self.execution_policy.select(role=agent, action=action, workload=workload,
                                                  read_only=read_only)
        role_profile = self.transports.profile(assignment, action, read_only)
        # A role container reads artifacts through the image's interpreter at the hand-off copy.
        reader_python = TRUSTED_PYTHON if role_profile in ROLE_PROFILES else None
        stream = stream_for(assignment.transport)
        # INV-WORKER-SESSION-001: an explicit task session is refused here, before any context work,
        # reservation or provider, unless every condition of the native path holds.
        session_owner = self._task_session_owner(task_session, assignment, read_only, lease, max_handoffs)
        if assignment.model_source == "explicit_setting":
            requested_model = assignment.configured_model
            model_receipt = {"policy": assignment.policy_version, "workload": workload,
                             "importance": selection.importance, "requested_model": requested_model,
                             "model_source": "explicit_setting",
                             "note": "configured explicitly; Codex routing never names this provider's model"}
        else:
            requested_model = selection.requested_model
            model_receipt = selection.receipt()
        # DESIGN-run-task §5 composition seam: the legacy composition is the S2 ContextComposer (compare:
        # context.composition), turn >= 2 through its D7 fields. Council delivery and correction feedback are
        # composed by S8; until then they refuse here, before any reservation or provider (never a silent drop).
        require(delivery is None, "Council delivery composition is not wired")
        require(correction_feedback is None, "Correction feedback composition is not wired")
        with self.store.transaction() as tx:
            deployed = tx.get("deployment", "active")
        review = role = project = None
        if read_only and action == "dge_role":
            require(self.council is not None, "Council role context is not wired")
            role = self.council.role_context(self.isolation.config if self.isolation is not None else None)
        elif read_only:
            review = (self.review_context(cwd) if self.isolation is None
                      else self.isolation.review_context(cwd, role_profile))
            if self.evidence_profile is not None:
                project = self._project_instructions(cwd)
        elif action == "implement" and self.evidence_profile is not None:
            project = self._project_instructions(cwd)
        with self.store.transaction() as tx:
            checkpoint = tx.get("sessions", agent)
            progress = tx.get("execution_progress", key)
        generation = (checkpoint or {}).get("generation", 0)

        def compose(recovery_sources=None, basis=None):
            return self.composer.compose(CompositionRequest(
                agent=agent, key=key, objective=objective, evidence=evidence, cwd=cwd,
                snapshot=self.ledger.snapshot(), runtime_policy_digest=digest(POLICY.snapshot()),
                reader_python=reader_python or self.host_python, provider=assignment.provider,  # M7: python or sys.executable
                default_provider=self.execution_policy.policy.default_provider, read_only=read_only,
                action=action, stage=stage, deployed_revision=(deployed or {}).get("revision"),
                checkpoint=checkpoint, progress=progress, review_context=review, role_context=role,
                project_evidence=project, recovery=recovery_sources, basis_revision=basis))

        composed = compose()
        binding, context_bound, basis_revision = composed.binding, composed.context_bound, composed.basis_revision
        workspace_identity = digest({"worktree": cwd, "basis_revision": basis_revision})

        def bound(value):
            """INV-CLAUDE-WORKER-001 / INV-SESSION-001: M7's `matches` + `bound`, as S2 extracted them."""
            return recovery_bound(value, binding=binding, context_bound=context_bound, provider=assignment.provider,
                                  default_provider=self.execution_policy.policy.default_provider, worktree=cwd)

        # S2b: the start-only prediction cache, refreshed by every authoritative progress write, and the activity
        # drops not yet persisted (FLEET-S2B-SPEC §3).
        activity_state = {"cache": activity_basis(progress if progress and bound(progress) else {}), "pending": 0,
                          "gap": False}
        require(type(max_handoffs) is int and 1 <= max_handoffs <= 4, "Handoff cap must be 1..4")
        recovery = None
        for handoff in range(max_handoffs):
            if handoff:
                composed = compose(recovery, basis_revision)  # D7: the run's own recovery, the fixed basis
            packet, context_measurement = composed.packet, composed.measurement
            retained = self.composer.retain(composed, key, (lambda tx: self.ledger.owned(tx, lease)) if lease else None)
            context_ref = {"ref": retained["context_ref"]}
            history_recording = retained["history"]
            prompt = composed.rendered
            if heartbeat:
                heartbeat()
            last_beat = self.monotonic()
            last_time_check = last_beat
            time_limit = POLICY.task_seconds if agent.startswith('worker:') else POLICY.decision_seconds

            def observe(event):
                nonlocal last_beat, last_time_check
                if event is None and lease and self.monotonic() - last_time_check >= 5:
                    self.ledger.remaining_seconds(lease, time_limit)
                    last_time_check = self.monotonic()
                if heartbeat and self.monotonic() - last_beat > 20:
                    heartbeat()
                    last_beat = self.monotonic()
                if event is None:
                    return
                # FA-016: a malformed runtime event is retained as evidence and counted, never
                # dropped, and never allowed to overwrite the well-formed progress state. The shape
                # is checked before any field is read (review, PR #49).
                defect = stream.shape(event)
                malformed = defect is not None
                label = None if malformed else activity_label(assignment.transport, event)
                if not (malformed or stream.is_progress(event)):
                    if label is not None:
                        record_start(event)
                    return
                # Occurrence time comes from the event itself; collection time is ours, read ONCE when the event
                # is accepted (S2b D7). They are kept apart so replay never reorders by the merge moment.
                collected = utcnow(self.clock)
                with self.store.transaction() as tx:
                    prior = tx.get("execution_progress", key) or {}
                prior_bound = bound(prior)
                receipt = self.artifacts.put(evidence_json({"event": event if not malformed else repr(event),
                                                            "malformed": malformed, "defect": defect,
                                                            "previous": prior.get("last_record") if prior_bound else None}),
                                             "runtime-event:" + key)
                # S2b: the compact display record of an activity event; any failure drops only the activity.
                predicted = activity_basis(prior if prior_bound else {}) if label is not None else None
                compact = put_activity(event, predicted, receipt["ref"], collected) if predicted else None
                def note_progress(progress_sequence):
                    self.observer.emit("development.progress_recorded", "observed",
                                       execution=observed_execution(reservation_id), correlation_id=correlation,
                                       causation_id=key, occurred_at=None if malformed else stream.occurrence(event),
                                       severity="warning" if malformed else "debug", evidence_refs=[receipt["ref"]],
                                       attributes={"progress_sequence": progress_sequence,
                                                   "method": stream.label(event),
                                                   "item_type": stream.item_type(event),
                                                   "item_status": stream.item_status(event),
                                                   "receipt_ref": receipt["ref"], "malformed": malformed, "defect": defect})
                with self.store.transaction() as tx:
                    if lease:
                        self.ledger.owned(tx, lease)
                    previous = tx.get("execution_progress", key) or {"id": key, "recent": []}
                    current_bound = bound(previous)
                    if not current_bound:
                        previous = {"id": key, "recent": []}
                    previous["provider"] = assignment.provider
                    if context_bound:
                        previous["research_binding"] = binding
                    if malformed:
                        previous["malformed_events"] = previous.get("malformed_events", 0) + 1
                        previous.setdefault("malformed_recent", [])
                        previous["malformed_recent"] = (previous["malformed_recent"] + [receipt["ref"]])[-6:]
                        previous.setdefault("malformed_defects", {})
                        previous["malformed_defects"][defect] = previous["malformed_defects"].get(defect, 0) + 1
                        if activity_state["gap"]:
                            # The drop is counted here, but the ring still misses a record: invalidate it durably so
                            # no reader (or a restarted run) selects it; malformed events never take a slot.
                            previous["activity_progress_sequence"] = None
                        flushed = flush_drops(previous)
                        tx.put("execution_progress", key, previous)
                    else:
                        occurred = stream.occurrence(event)
                        observed = activity_basis(previous)
                        previous["sequence"] = previous.get("sequence", 0) + 1
                        previous["recent"] = (previous["recent"] + [receipt["ref"]])[-6:]
                        previous["last_record"] = receipt["ref"]
                        previous.update(agent=agent, context_ref=context_ref["ref"], at=collected,
                                        collected_at=collected, occurred_at=occurred,
                                        event_id=stream.event_id(event, receipt["ref"]),
                                        generation=lease.get("generation") if lease else None,
                                        attempt=lease.get("attempt") if lease else None,
                                        last_event=stream.label(event), worktree=cwd)
                        item = stream.completed_item(event)
                        if item is not None:
                            if label == "result" and assignment.transport == "claude_cli":
                                # S2b D9: the adapter's own failure rule, so S1a agrees with the activity entry.
                                item = {**item, "status": claude_result_status(event)}
                            previous["last_completed"] = {**item, "evidence": receipt["ref"],
                                                          "sequence": previous["sequence"], "occurred_at": occurred}
                        # The compact record links only when the row is still the one it was predicted from.
                        linked = (compact is not None and prior_bound == current_bound and observed == predicted)
                        gap = activity_state["gap"]  # an earlier drop this run left the ring incomplete
                        if label is not None and not linked:
                            activity_state["pending"] += 1
                            activity_state["gap"] = True
                        sync_activity(previous, observed[1] if observed else None, compact if linked else None,
                                      failed=label is not None and not linked, gap=gap)
                        flushed = flush_drops(previous)
                        tx.put("execution_progress", key, previous)
                activity_state["pending"] -= flushed
                # Committed: the ring was cleared, re-synchronized or its watermark nulled, so no gap is left open.
                activity_state["gap"] = False
                activity_state["cache"] = activity_basis(previous)
                note_progress(None if malformed else previous.get("sequence"))

            def flush_drops(row):
                """Persist the activity drops known so far in this successful owned write; the caller clears them
                only after the commit, so a failed commit keeps them pending."""
                pending = activity_state["pending"]
                if pending:
                    current = row.get("activity_dropped", 0)
                    row["activity_dropped"] = (current if type(current) is int and current >= 0 else 0) + pending
                return pending

            def put_activity(event, basis, raw_ref, collected):
                """Build and store ONE compact record for a raw-backed event; None drops the activity only."""
                try:
                    document = build_receipt(
                        execution=key, transport=assignment.transport, event=event, activity_sequence=basis[0] + 1,
                        progress_sequence=basis[1] + 1, generation=lease.get("generation") if lease else None,
                        attempt=lease.get("attempt") if lease else None, collected_at=collected, raw_ref=raw_ref)
                    return self.artifacts.put(evidence_json(document), "runtime-activity:" + key,
                                              lock_timeout=ACTIVITY_LOCK_SECONDS)["ref"]
                except Exception:
                    return None

            def record_start(event):
                """A Claude tool start: ONE compact record and ONE fail-fast owned transaction, no raw receipt and
                no legacy progress field (S2b D4/D5). Every failure drops only this activity, except the
                `_owned` fence refusal, which ends the run exactly as a progress write would."""
                basis = activity_state["cache"]
                if basis is None:
                    activity_state["pending"] += 1
                    activity_state["gap"] = True
                    return
                try:
                    document = build_receipt(
                        execution=key, transport=assignment.transport, event=event, activity_sequence=basis[0] + 1,
                        progress_sequence=None, generation=lease.get("generation") if lease else None,
                        attempt=lease.get("attempt") if lease else None, collected_at=utcnow(self.clock), raw_ref=None)
                    compact = self.artifacts.put(evidence_json(document), "runtime-activity:" + key,
                                                 lock_timeout=ACTIVITY_LOCK_SECONDS)["ref"]
                except Exception:
                    activity_state["pending"] += 1
                    activity_state["gap"] = True
                    return
                written, observed, flushed, refused = None, None, 0, False
                try:
                    with self.store.transaction(fail_fast=True) as tx:
                        if lease:
                            try:
                                self.ledger.owned(tx, lease)
                            except ContractError:
                                refused = True  # the fence refusal is never contained (re-raised below as is)
                                raise
                        previous = tx.get("execution_progress", key) or {"id": key, "recent": []}
                        if not bound(previous):
                            previous = {"id": key, "recent": []}
                        observed = activity_basis(previous)
                        if observed == basis:
                            previous["provider"] = assignment.provider
                            if context_bound:
                                previous["research_binding"] = binding
                            previous["worktree"] = cwd
                            sync_activity(previous, previous.get("sequence", 0), compact, failed=False,
                                          gap=activity_state["gap"])
                            flushed = flush_drops(previous)
                            tx.put("execution_progress", key, previous)
                            written = previous
                except Exception:
                    if refused:
                        raise
                    activity_state["pending"] += 1
                    activity_state["gap"] = True
                    activity_state["cache"] = None
                    return
                if written is None:
                    # Compare-and-set mismatch: nothing written, no retry; the observed row is the new prediction.
                    activity_state["pending"] += 1
                    activity_state["gap"] = True
                    activity_state["cache"] = observed
                    return
                activity_state["pending"] -= flushed
                activity_state["gap"] = False
                activity_state["cache"] = activity_basis(written)

            started = self.monotonic()
            result = None
            timeout = time_limit
            if lease:
                timeout = self.ledger.remaining_seconds(lease, timeout)
            # INV-INVOCATION-001: the request is checked against the transport's support matrix and
            # the attempt is reserved (ownership re-proven in the same transaction) before any call.
            if assignment.transport == "claude_cli":
                ceiling = assignment.controls.get("timeout_seconds")
                timeout = min(timeout, ceiling) if ceiling else timeout
            options = invocation_options(assignment, model=requested_model, timeout=timeout, schema=schema,
                                         read_only=read_only)
            # The reservation carries which policy chose this provider, so a receipt can be read back
            # to the configuration that produced it.
            request = {**parse_request(assignment.transport, options), "assignment": assignment.receipt()}
            if role_profile == CLAUDE_IMPL_RW:
                request["isolation"] = self.isolation.summary()
            elif role_profile is not None:
                request["isolation"] = {**self.isolation.summary(), "profile": role_profile}
            # INV-OUTPUT-001 / INV-OBSERVATION-001: a schema the subset refuses is a configuration
            # error; it is refused here, before any provider is entered, so it never needs a
            # termination record.
            self.results.preflight(schema)
            # INV-OBSERVATION-001: a provider never starts for a task whose earlier run left
            # termination evidence that was not reconciled; the reservation and its audit record
            # commit together, and a failed audit means no reservation and no provider.
            if lease:
                # Early, strict pre-check (a failed sink read raises; it never reads as "none").
                # The authoritative check is `guard_reservation` inside the reservation transaction.
                # This attempt's own unconfirmed marker (a second stage or a handoff) is expected.
                pending = [row for row in self.observer.pending_terminations(key, strict=True)
                           if not (row.get("status") == "unconfirmed"
                                   and (row.get("generation"), row.get("attempt")) == (lease.get("generation"), lease.get("attempt")))]
                if pending:
                    raise self.ReconciliationRequired(key, pending)
            correlation = self.observer.correlation(lease)

            def observed_execution(invocation_id=None):
                if lease:
                    return self.observer.for_lease(lease, provider=assignment.identity, invocation_id=invocation_id,
                                                   revision=basis_revision)
                return self.observer.system(revision=basis_revision, role=agent)
            reservation = (self.invocations.reserve(
                lease, request=request, budget_seconds=timeout, stage=stage,
                guard=lambda tx: self.ledger.owned(tx, lease),
                audit=lambda tx, row: (self.observer.guard_reservation(tx, lease),
                    self.observer.mark_unconfirmed(tx, lease, reservation_id=row["id"]),
                    self.observer.audit(
                    tx, "development.invocation_reserved", "started", identity=["reservation", row["id"], "reserved"],
                    execution=observed_execution(row["id"]), correlation_id=correlation, causation_id=key,
                    attributes={"reservation_id": row["id"], "stage": stage, "transport": assignment.transport,
                                "requested_model": requested_model, "budget_seconds": float(timeout),
                                "workload": workload})))
                if lease else None)
            reservation_id = reservation["id"] if reservation else None
            admission = None
            # INV-OBSERVATION-001: `provider_entered` marks the external-effect boundary. Before it,
            # a failure is a refusal that never started the provider and may be retried. After it,
            # every failure up to the durable checkpoint (transport, progress, cleanup, settlement,
            # breaker report, result persistence, checkpoint) leaves termination evidence and
            # refuses a new run of this task until an operator reconciles. The one exception is a
            # runner-observed output failure, whose evidence is persisted before it is raised.
            provider_entered = False
            session_plan = None

            def terminated(exc, boundary, classification="unknown", stream_hash=None):
                if not lease:
                    return exc
                record_id = self.observer.record_termination(
                    lease, reservation_id=reservation_id, classification=classification, stream_hash=stream_hash,
                    error=exc, boundary=boundary)
                return self.PostExecutionRecordFailure(record_id, exc, boundary)
            def mark_entered():
                # Initialization inside a provider can already touch the workspace, so from here on
                # nothing is a refusal that never ran: it is an execution whose effect is unknown.
                nonlocal provider_entered
                if provider_entered:
                    return
                provider_entered = True
                self.observer.emit("development.provider_started", "started",
                                   execution=observed_execution(reservation_id),
                                   correlation_id=correlation, causation_id=key,
                                   # The registered log schema exactly (domain.observation REGISTRY): an undeclared
                                   # attribute makes the observer refuse the whole start event. The byte
                                   # telemetry is additive in the execution receipt's context_measurement only.
                                   attributes={"reservation_id": reservation_id, "transport": assignment.transport,
                                               "requested_model": requested_model, "read_only": read_only,
                                               "timeout_seconds": float(timeout), "context_ref": context_ref["ref"]})

            try:
                # INV-INVOCATION-001 / INV-BREAKER-001: capacity refusal must not take a
                # probe slot; breaker refusal must release the invocation reservation.
                admission = self.admission.admit(self.admission.key(assignment.identity, workload), lease) if lease else None
                session_arguments = {}
                if session_owner is not None:
                    # Exclusive claim of the logical session for this execution; a refusal (owned,
                    # foreign, incompatible, missing/corrupt archive) is a refusal before entry.
                    session_plan = self.worker_sessions.begin(
                        task_session["task_id"], self._task_session_identity(task_session, assignment,
                                                                            requested_model, cwd),
                        session_owner)
                    plan = session_plan
                    session_arguments = {"session_id": plan["session_id"], "task_session": {
                        "mode": plan["mode"], "session_id": plan["session_id"],
                        "stage": lambda destination: self.worker_sessions.stage(plan, destination)}}
                # INV-ROLE-CONTAINER-001 (D4): a role container mounts read-only copies of exactly the
                # artifacts this prompt and its evidence name (hand-off manifests expanded), never the store.
                handoff = ({"root": str(self.artifacts.root),
                            "refs": self.results.handoff_refs(self.artifacts.root, [prompt, canonical(evidence)])}
                           if role_profile in ROLE_PROFILES else None)
                opened = self.transports.open(assignment, requested_model, cwd, action, read_only, handoff)
                # A transport whose construction is itself the external effect says so; one that
                # starts its process later reports the exact moment through `on_enter`.
                entry_on_open = getattr(opened, "enters_on_open", True)
                with opened as runtime:
                    if entry_on_open:
                        mark_entered()
                    result = runtime.run(prompt, cwd, schema, timeout,
                                         on_event=observe, read_only=read_only, on_tick=lambda: observe(None),
                                         model=requested_model,
                                         **({} if entry_on_open else {"on_enter": mark_entered}),
                                         **session_arguments)
                if role_profile in WRITABLE_PROFILES:
                    # INV-ROLE-CONTAINER-001 (D4): the transport returns only after the writer's container
                    # is confirmed stopped and its observations retained; only now is its evidence copied
                    # into the content-addressed store, the one source a reviewer container later mounts.
                    retained = (result.get("isolation") or {}) if isinstance(result, dict) else {}
                    if retained.get("record"):
                        retained["evidence_handoff"] = self.results.retain_evidence_handoff(
                            self.artifacts, Path(retained["record"]).parent / "evidence", str(retained.get("run_id")))
            except Exception as exc:
                if session_plan is not None and (result is None or not (result.get("inspection_blocked")
                                                                        or result.get("failure"))):
                    self._task_session_ended(task_session, session_owner, provider_entered, exc)
                if result is None or not (result.get("inspection_blocked") or result.get("failure")):
                    self.observer.emit("development.provider_failed", "failed", severity="error",
                                       execution=observed_execution(reservation_id), correlation_id=correlation,
                                       causation_id=key, reason_code=type(exc).__name__,
                                       attributes={"reservation_id": reservation_id, "error_type": type(exc).__name__,
                                                   "elapsed_seconds": self.monotonic() - started,
                                                   "provider_entered": provider_entered})
                    try:
                        if reservation is not None:
                            error_type = type(exc).__name__
                            reason = 'exception:' + error_type

                            def abandoned(tx, row):
                                self.observer.audit(tx, "development.invocation_abandoned", "aborted",
                                                    identity=["reservation", row["id"], "abandoned"],
                                                    execution=observed_execution(row["id"]), correlation_id=correlation,
                                                    causation_id=key, reason_code=error_type,
                                                    attributes={"reservation_id": row["id"], "reason": reason})
                                if not provider_entered:
                                    # Proven never to have entered: the unconfirmed marker closes with
                                    # the abandonment, in the same transaction.
                                    self.observer.close_unconfirmed(tx, lease, "not_entered")
                            self.invocations.abandon(reservation['id'], reason, audit=abandoned)
                        if admission is not None:
                            self.admission.report(admission, self.admission.verdict_of_exception(exc))
                    except Exception:
                        if not provider_entered:
                            raise
                        # Bookkeeping failed after the provider was entered: the termination
                        # record below is what must survive, not this secondary failure.
                    if provider_entered:
                        raise terminated(exc, "transport") from exc
                    raise
                # INV-RELEASE-001 / INV-SESSION-001: cleanup cannot erase a known
                # blocked result before its artifact and fenced checkpoint are saved.
                result["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
            boundary = "classification"
            try:
                if session_plan is not None:
                    # Resumed headless usage is cumulative: only this turn's delta against the same
                    # session's recorded baseline is counted, otherwise the turn's usage is unknown.
                    session_usage = usage_delta(mode=session_plan["mode"], session_id=session_plan["session_id"],
                                                baseline=session_plan.get("usage_baseline"), raw=result.get("usage"))
                    result["session_usage"] = session_usage
                    result["usage"] = session_usage["delta"] if session_usage["delta"] else None
                    if session_plan["mode"] == MODE_RESUME:
                        result["cost"] = {**(result.get("cost") or {}), "reported_usd": None, "source": "unknown",
                                          "note": "a resumed session reports a cumulative estimate; not attributed to this turn"}
                if context_bound:
                    result.update(elapsed_seconds=self.monotonic() - started,
                                  context_ref=context_ref["ref"], research_binding=binding)
                result["model_selection"] = model_receipt
                result["execution_assignment"] = assignment.receipt()
                result["context_measurement"] = context_measurement  # persisted in the execution receipt below
                result['invocation'] = {'request': request, 'outcome': classify_result(result),
                                        'usage': usage_record({**result, 'requested_model': requested_model},
                                                              assignment.transport),
                                        'reservation': reservation['id'] if reservation else None}
                usage = result['invocation']['usage']
                classification = result['invocation']['outcome']
                self.observer.emit("development.provider_finished", invocation_outcome(classification),
                                   execution=observed_execution(reservation_id), correlation_id=correlation, causation_id=key,
                                   attributes={"reservation_id": reservation_id, "invocation_outcome": classification,
                                               "elapsed_seconds": self.monotonic() - started,
                                               "event_count": usage["event_count"], "stream_hash": usage["stream_hash"],
                                               "confirmed_model": usage["confirmed_model"], "usage_source": usage["source"],
                                               "total_tokens": usage["total_tokens"], "thread_id": result.get("thread_id")})
                boundary = "settlement"
                if reservation is not None:
                    self.invocations.settle(
                        reservation['id'], outcome=classification, usage=usage,
                        audit=lambda tx, row: self.observer.audit(
                            tx, "development.invocation_settled", invocation_outcome(row["outcome"]),
                            identity=["reservation", row["id"], "settled"], execution=observed_execution(row["id"]),
                            correlation_id=correlation, causation_id=key,
                            attributes={"reservation_id": row["id"], "invocation_outcome": row["outcome"],
                                        "usage_source": row["usage"]["source"], "total_tokens": row["usage"]["total_tokens"],
                                        "within_budget": bool(row.get("within_budget"))}))
                boundary = "breaker_report"
                if admission is not None:
                    verdict = self.admission.verdict(result)
                    result['breaker'] = {**self.admission.report(admission, verdict), 'verdict': verdict,
                                         'key': admission['key'], 'admitted_generation': admission['generation'],
                                         'probe': admission['probe'], 'policy_revision': admission['policy_revision']}
                result['tool_usage'] = self.results.tool_usage(result)  # INV-OUTPUT-001: observed, beside any self-report
                if history_recording:
                    result['skill_history_recording'] = history_recording
                if session_plan is not None:
                    boundary = "task_session"
                    result["task_session"] = self._task_session_turn(task_session, session_owner, session_plan, result)
                boundary = "result_persistence"
                # INV-OBSERVATION-001: the evaluation of this output is recorded only once its
                # durable receipt exists, on both exits of `persist_result` — the receipt it returns,
                # and the one its ExecutionFailure carries after having written it. A refused output
                # stays refused; the event explains it, it never re-decides it.
                try:
                    evidence_ref = self.results.persist(self.artifacts, result, key=key, agent=agent, lease=lease,
                                                  basis_revision=basis_revision, context_ref=context_ref['ref'])
                except ExecutionFailure as failure:
                    self._output_evaluated(result, execution=observed_execution(reservation_id),
                                           correlation_id=correlation, causation_id=key,
                                           reservation_id=reservation_id,
                                           evidence_ref=(failure.evidence or {}).get("execution_ref"),
                                           execution_failure=True)
                    raise
                self._output_evaluated(result, execution=observed_execution(reservation_id),
                                       correlation_id=correlation, causation_id=key,
                                       reservation_id=reservation_id, evidence_ref=evidence_ref["ref"],
                                       execution_failure=False)
                boundary = "checkpoint"
                graph = ({"code": self.knowledge.index_python(cwd),
                          "runtime": self.knowledge.project_runtime(self.store, self.organization)}
                         if self.knowledge and result["rotate"] else None)
                state = {"next_action": "continue interrupted assignment" if result["interrupted"] else "await next assignment",
                         "task_id": key, "source_revision": self.git._git("rev-parse", "HEAD", cwd=cwd),
                         "graph_snapshot": graph or packet.snapshot, "worktree": cwd,
                         "context_ref": context_ref["ref"], "evidence_ref": evidence_ref["ref"],
                         "thread_id": result["thread_id"], "usage": result["usage"],
                         "message_cursor": key, "decisions": result["answer"],
                         "handoff_reason": "context_threshold" if result["rotate"] else "task_boundary",
                         # INV-CLAUDE-WORKER-001: what this session was, so a later attempt can tell
                         # whether the record it found belongs to the execution it is about to run.
                         "provider": assignment.provider, "provider_identity": assignment.identity,
                         "provider_session_id": result["thread_id"], "transport": assignment.transport,
                         "agent": agent, "generation": lease.get("generation") if lease else None,
                         "attempt": lease.get("attempt") if lease else None,
                         "invocation": reservation_id, "workspace_identity": workspace_identity,
                         "policy_digest": assignment.policy_digest, "config_digest": assignment.config_digest,
                         "session_resume": assignment.session_resume}
                if context_bound:
                    state["research_binding"] = binding
                session = self.sessions.checkpoint(agent, generation, state, execution=lease)
                generation = session["generation"]
                self.observer.emit("development.checkpoint_recorded", "observed", execution=observed_execution(reservation_id),
                                   correlation_id=correlation, causation_id=key,
                                   evidence_refs=[evidence_ref["ref"], context_ref["ref"]],
                                   attributes={"session_generation": generation, "session_id": session["session_id"],
                                               "handoff_reason": state["handoff_reason"], "evidence_ref": evidence_ref["ref"],
                                               "context_ref": context_ref["ref"]})
            except ExecutionFailure:
                # Runner-observed output failure: its evidence artifact is persisted before the raise
                # and the settlement is recorded, so this is an observed outcome, not an unknown one.
                raise
            except Exception as exc:
                invocation = result.get('invocation') if isinstance(result, dict) else None
                raise terminated(exc, boundary, (invocation or {}).get('outcome', 'unknown'),
                                 ((invocation or {}).get('usage') or {}).get('stream_hash')) from exc
            if result.get("inspection_blocked"):
                return {"accepted": False, "inspection_blocked": True,
                        "reason": "inspection-blocked: bubblewrap namespace creation denied; "
                                  "required command inspection failed; host cause unconfirmed",
                        "execution_ref": evidence_ref["ref"], "basis_revision": basis_revision}
            if not result["interrupted"]:
                return {**result["answer"], "execution_ref": evidence_ref["ref"], "basis_revision": basis_revision}
            completed = [event for event in result["events"] if event.get("method") == "item/completed"]
            recovery = {"checkpoint": state, "completed": completed[-4:]}
        raise RuntimeError("Session handoff budget exhausted; task remains resumable from checkpoint")

    def _task_session_owner(self, task_session, assignment, read_only, lease, max_handoffs) -> dict | None:
        """None for the default fresh path; otherwise the exclusive owner, after refusing every
        unsupported combination before any provider entry."""
        if task_session is None:
            return None
        require(self.worker_sessions is not None, "Task sessions are not configured on this host")
        require(isinstance(task_session, dict) and set(task_session) == {"task_id", "repository"}
                and all(type(task_session[k]) is str and task_session[k] for k in task_session),
                "Task session binding must name exactly task_id and repository")
        require(assignment.transport == "claude_cli" and self.isolation is not None,
                "Native task sessions run only in the isolated Claude worker; the host home is never resumed")
        require(not read_only, "A review never opens or resumes a worker session")
        require(bool(lease), "A task session is owned by a leased execution")
        require(max_handoffs == 1, "A task session turn is one provider call; handoffs are the owner's decision")
        return {"execution": str(lease["id"]), "generation": int(lease.get("generation") or 0),
                "attempt": int(lease.get("attempt") or 0)}

    def _task_session_identity(self, task_session, assignment, requested_model, cwd) -> dict:
        return {"task_id": task_session["task_id"], "repository": task_session["repository"],
                "workspace": digest({"worktree": str(cwd)}), "provider": assignment.provider,
                "model": requested_model, "runtime_image": self.isolation.config["image"],
                "runtime_digest": digest(assignment.runtime), "policy_digest": assignment.policy_digest,
                "config_digest": assignment.config_digest}

    def _task_session_turn(self, task_session, owner, plan, result) -> dict:
        """Adopt the finished turn's exported transcript, or release the claim when there is none to
        adopt. Only references and hashes travel on in the result; the bytes stay restricted."""
        reported = result.get("task_session") if isinstance(result.get("task_session"), dict) else {}
        adoptable = (not result.get("failure") and result.get("answer") is not None and reported.get("exported")
                     and reported.get("session_id") == plan["session_id"])
        if not adoptable:
            reason = "turn_failed" if result.get("failure") or result.get("answer") is None else "export_unavailable"
            self.worker_sessions.release(task_session["task_id"], owner, reason)
            return {"mode": plan["mode"], "session_id": plan["session_id"], "adopted": False, "reason": reason}
        try:
            row = self.worker_sessions.checkpoint(task_session["task_id"], owner, reported["export"],
                                                  usage=result.get("session_usage"),
                                                  cli_version=(result.get("command") or {}).get("cli_version"))
        except Exception as exc:
            # The retained export stays on disk for `reconcile`; the claim never silently survives.
            self._task_session_ended(task_session, owner, True, exc)
            raise
        last = row["checkpoints"][-1]
        return {"mode": plan["mode"], "session_id": plan["session_id"], "adopted": True, "state": row["state"],
                "archive": {key: last["archive"][key] for key in ("ref", "transcript_sha256", "files")},
                "continuity": last["continuity"]}

    def _task_session_ended(self, task_session, owner, entered: bool, exc) -> None:
        """A turn that raised. Not entered: the claim is released unchanged. Entered: its effect is
        unknown, so the session is unresolved rather than resumable. Best effort: the termination
        evidence of the caller is what must survive, never this bookkeeping."""
        try:
            if entered:
                self.worker_sessions.mark_unresolved(task_session["task_id"], owner, "turn_" + type(exc).__name__)
            else:
                self.worker_sessions.release(task_session["task_id"], owner, "not_entered")
        except Exception:
            pass

    def _continued_workspace(self, task, workspace) -> dict:
        """The origin workspace, only when no execution of the origin task can still own it. A
        blocked origin (reconciliation required) has unconfirmed effects: its workspace is evidence
        for recovery, never a place to continue."""
        with self.store.transaction() as tx:
            origin = tx.get("tasks", workspace["origin_task_id"])
        require(origin is not None and origin.get("status") not in {"queued", "retry", "running", "blocked"},
                "Continuation workspace still has an active or unresolved owner")
        return self.git.continue_workspace(workspace["origin_task_id"], task["id"], workspace["head"],
                                           workspace["base"])

    def _output_evaluated(self, result, *, execution, correlation_id, causation_id, reservation_id,
                          evidence_ref, execution_failure: bool) -> None:
        """What this attempt's output was judged to be, at the boundary where its receipt is durable.

        The classification is the ledger's own (INV-INVOCATION-001) and is not recomputed here. Every
        other field is a declared code: the structural output reason and its owner, the provider's own
        failure cause and reported result subtype, and which structural checks ran. A value outside
        the declared vocabulary becomes `unknown` and an absent one `none`, so no missing field is
        inferred from a provider subtype; the prompt, the answer, schema property names, commands,
        stdout and exception text stay out by construction. The durable artifact is linked, not copied.
        """
        failure = result.get("failure") if isinstance(result, dict) else None
        failure = failure if isinstance(failure, dict) else {}
        structural = result.get("structural") if isinstance(result, dict) else None
        checks = structural.get("checks") if isinstance(structural, dict) and isinstance(structural.get("checks"), dict) else {}
        classification = (result.get("invocation") or {}).get("outcome") if isinstance(result, dict) else None
        outcome_code = safe_code(classification, tuple(INVOCATION_OUTCOMES))
        reason = safe_code(failure.get("output_reason"), OUTPUT_REASONS)
        subtype = safe_code(failure.get("result_subtype"), TERMINAL_SUBTYPES)
        # A structurally invalid answer is not a provider failure: its cause names the output, and
        # the provider cause stays absent rather than being filled with the output label.
        cause = safe_code(failure.get("cause"), PROVIDER_CAUSES) if reason == "none" else "none"
        # The output's own structural defect names the reason when there is one. Otherwise a declared
        # terminal subtype that names its own failure does (a retry-exhausted structured output is not
        # the same operator problem as any other provider failure), and the ledger's classification
        # names it when neither does; an unknown subtype reaches no reason of its own.
        projected = "output_" + reason if reason != "none" else SUBTYPE_REASONS.get(subtype)
        self.observer.emit("development.output_evaluated",
                           invocation_outcome(classification) if classification in INVOCATION_OUTCOMES else "unknown",
                           execution=execution, correlation_id=correlation_id, causation_id=causation_id,
                           reason_code=projected or "output_" + outcome_code,
                           severity=OUTPUT_SEVERITY.get(outcome_code, "warning"),
                           evidence_refs=[evidence_ref] if type(evidence_ref) is str else [],
                           attributes={"reservation_id": reservation_id, "invocation_outcome": outcome_code,
                                       "output_reason": reason, "provider_cause": cause,
                                       "terminal_subtype": subtype,
                                       "failure_owner": safe_code(failure.get("owner"), FAILURE_OWNERS),
                                       "json_check": safe_code(checks.get("json"), STRUCTURAL_CHECKS, absent="unreported"),
                                       "schema_check": safe_code(checks.get("schema"), STRUCTURAL_CHECKS, absent="unreported"),
                                       "execution_failure": bool(execution_failure)})

    def _policy_refusal(self, task, agent, refusal):
        """INV-DISCOVERY-PRESSURE-001: a held or intent-less research fetch is a named policy decision, not a
        provider or code failure. The task ends `failed` WITHOUT replay (a retry would only meet the same
        policy) and WITHOUT a model diagnosis (it would spend a real call on a known reason). Nothing was fetched
        and no provider ran."""
        try:
            current = self.ledger.fail(task, "discovery_policy: " + str(refusal.reason_code), retryable=False)
        except ContractError as exc:
            return self._lost_execution(task, refusal, exc)
        self.observer.emit("development.task_failed", "failed", severity="warning",
                           execution=self.observer.for_lease(task, role=agent), correlation_id=self.observer.correlation(task),
                           causation_id=task["id"], reason_code=str(refusal.reason_code),
                           attributes={"status": current["status"], "error_type": type(refusal).__name__,
                                       "failure_receipt": current.get("failure_receipt")})
        return current

    def _failure_disposition(self, lease, exc):
        """INV-OBSERVATION-001: how a failure outside `_run` closes or keeps this attempt's marker.

        No open marker: nothing was reserved, an ordinary retry. An open marker with a
        runner-observed output failure or a contract rejection of an already persisted answer:
        the outcome was observed, the marker closes with the failure record and the retry stays.
        Anything else with an open marker (an acceptance write, a workspace capture, a decision
        commit that failed) cannot prove the effects were accepted: the attempt is blocked, and the
        failure is published under the same boundary/type/digest wording as failures inside `_run`;
        the foreign exception text never reaches the task row, the CLI or the diagnosis request.
        A sink read that fails here is treated as unknown, which blocks.
        """
        try:
            pending = self.observer.pending_terminations(lease["id"], strict=True)
        except Exception:
            pending = [{"record_id": self.observer.termination_id(lease)}]
        if not pending:
            return exc, {}
        if isinstance(exc, (ExecutionFailure, ContractError)):
            return exc, {"closure": "observed_failure"}
        record_id = self.observer.record_termination(
            lease, reservation_id=None, classification="unknown", stream_hash=None, error=exc, boundary="acceptance")
        return self.PostExecutionRecordFailure(record_id, exc, "acceptance"), {"block": [record_id]}

    def _record_reconciliation_block(self, tx, bucket, lease, agent, current, record_ids):
        event = {"type": "execution.reconciliation_required", "bucket": bucket, "task_id": lease["id"],
                 "generation": current.get("generation", 0), "attempt": current.get("attempt"),
                 "records": list(record_ids)}
        identity = digest(event)
        if tx.get("events", identity) is None:
            self.records.append_event(tx, identity, {**event, "at": utcnow(self.clock)})
        # The lead learns about the block through the existing informational notice path
        # (execution.notice → outbox), not through the observation record.
        self.records.notice(tx, current, bucket, 'reconciliation_required', utcnow(self.clock), identity)
        self.observer.audit(tx, "development.reconciliation_required", "blocked",
                            identity=["reconciliation_required", bucket, lease["id"], current.get("generation"),
                                      current.get("attempt")],
                            execution=self.observer.for_lease(lease, role=agent),
                            correlation_id=self.observer.correlation(lease), causation_id=lease["id"],
                            reason_code="reconciliation_required", severity="critical",
                            attributes={"terminations": len(record_ids), "record_id": str(record_ids[0])})

    def _block_for_reconciliation(self, lease, agent, exc):
        """INV-OBSERVATION-001: no provider ran; the execution stops until an operator reconciles."""
        bucket = lease.get("_bucket", "tasks")
        try:
            with self.store.transaction() as tx:
                current = self.ledger.owned(tx, lease)
                current.update(status="blocked", error="reconciliation_required", lease_until=None, lease_owner=None)
                self.records.record_row(tx, bucket, current)
                self._record_reconciliation_block(tx, bucket, lease, agent, current,
                                                  [row.get("record_id") for row in exc.records])
                return current
        except ContractError as failure:
            return self._lost_execution(lease, exc, failure)

    def _lost_execution(self, lease, error, rejection_error=None):
        # INV-SESSION-001: a stale executor cannot publish failure or diagnosis.
        contained = self.ledger.contain_time(lease, rejection_error) or self.ledger.contain_time(lease, error)
        if contained is not None:
            return contained
        return self.ledger.reconcile(lease, error, rejection_error)

    def _fail_task(self, task, agent, error, *, block=None, closure=None):
        """Record the failure; with `block`, also block the task in the same transaction; with
        `closure`, close the attempt's unconfirmed marker as an observed failure (INV-OBSERVATION-001)."""
        try:
            # INV-RECURRENCE-001: committing failure must also retain its diagnosis request.
            with self.store.transaction() as tx:
                current = self.ledger.fail_execution(task, error, transaction=tx)
                if closure:
                    self.observer.close_unconfirmed(tx, task, closure)
                if block and current.get("status") == "retry":
                    current.update(status="blocked", error="reconciliation_required")
                    self.records.record_row(tx, task.get("_bucket", "tasks"), current)
                    self._record_reconciliation_block(tx, task.get("_bucket", "tasks"), task, agent, current, block)
                actor = self.organization.actor(agent)
                if actor.parent:
                    self.records.request_diagnosis(tx, task, agent, error, current, actor.parent, lambda: self.artifacts.put(
                        canonical({"task_id": task["id"], "attempt": task["attempt"], "error": str(error),
                                   "agent": agent, "failure": current.get("failure")}), "execution-failure")["ref"])
            self.observer.emit("development.task_failed", "failed", severity="error",
                               execution=self.observer.for_lease(task, role=agent), correlation_id=self.observer.correlation(task),
                               causation_id=task["id"], reason_code=type(error).__name__,
                               attributes={"status": current["status"], "error_type": type(error).__name__,
                                           "failure_receipt": current.get("failure_receipt")})
            return current
        except ContractError as exc:
            return self._lost_execution(task, error, exc)

