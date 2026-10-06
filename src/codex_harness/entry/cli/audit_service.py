"""The `zeus audit-service` argument parser and command bodies (M7 adapters/audit_service.py, cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus audit-service`), run (its body: M7 audit_service_command), _status (M7 audit_service.status) and _execute (M7 audit_service.execute)
Does not own: dispatch (entry.cli main), the runner and the run gate (coordination.application.audit_service) and the host lock and runner wiring (composition.cli_audit_service)
Entry points: add_parser, run
Contracts: INV-AUDIT-SERVICE-001

Moved from M7 adapters/audit_service.py:221-236 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `cli.py` `audit_service_command` (:588-599), `_status` is `adapters/audit_service.py:940-999` (`status`) and `_execute` is :1002-1008 (`execute`), all verbatim except that the service is built first (as M7 `main()` did), `refusal` is `entry.cli.operation.refusal`, `run` of `_execute` is `composition.cli_audit_service.run_service` and the names come from their target homes (S10 unit C6b, R-c25): `ACTION`, `STATE_BUCKET`, `block_reason` and `analysis_facts` from `coordination.application.audit_service`, `ANALYSIS_REJECTED` from `kernel.analysis`, `PROGRESS_BUCKET`/`progress_view` from `research.application.audit_progress` and `REPAIR_ACTIVATION`, `REPAIR_CORRECTIONS` and `repair_view` from `research.application.audit_repair`.
"""


def add_parser(commands) -> None:
    service = commands.add_parser("audit-service", help="Run ONE selected source audit through the "
                                  "existing scheduler, Workflow and executor; no release activation")
    sub = service.add_subparsers(dest="audit_service_command", required=True)
    run_command = sub.add_parser("run", help="Own this runtime and execute the selected audit's "
                                 "partition assignments one at a time")
    run_command.add_argument("--audit-id", required=True, dest="audit_id",
                             help="The explicitly selected audit; unrelated audits are never executed")
    run_command.add_argument("--max-tasks", type=int, default=None, dest="max_tasks",
                             help="Finite acceptance mode: stop after N successful task completions "
                                  "(1..100). Not a subscription call cap; queued successors are kept")
    run_command.add_argument("--once", action="store_true",
                             help="Do the work that is ready now, then exit instead of waiting")
    status_command = sub.add_parser("status", help="Read the service state and the durable audit "
                                    "records; store read only")
    status_command.add_argument("--audit-id", required=True, dest="audit_id")


def run(args) -> None:
    """INV-AUDIT-SERVICE-001: exit 0 only for a completed command; refusals print a code and a type,
    never prompts, source text, partition scope, credentials, DSNs or raw exceptions."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.operation import refusal
    from codex_harness.entry.cli.output import emit
    service = build()
    try:
        result = _execute(service, args)
    except Exception as exc:
        emit(refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _status(service, args) -> dict:
    """Store read only: no executor, observer, bus, collector or provider is built."""
    from codex_harness.coordination.application.audit_service import (
        ACTION,
        STATE_BUCKET,
        _default_state,
        analysis_facts,
        block_reason,
    )
    from codex_harness.kernel.analysis import ANALYSIS_REJECTED
    from codex_harness.research.application.audit_progress import BUCKET_STATE as PROGRESS_BUCKET
    from codex_harness.research.application.audit_progress import status_view as progress_view
    from codex_harness.research.application.audit_repair import BUCKET_ACTIVATION as REPAIR_ACTIVATION
    from codex_harness.research.application.audit_repair import BUCKET_CORRECTIONS as REPAIR_CORRECTIONS
    from codex_harness.research.application.audit_repair import repair_view
    audit_id = args.audit_id
    with service.store.transaction() as tx:
        state = tx.get(STATE_BUCKET, audit_id) or _default_state(audit_id)
        control = tx.get("research_control", "activation") or {}
        audit = tx.get("research_audits", audit_id)
        predecessor = tx.get("tasks", (state.get("last_task") or {}).get("task_id") or "")
        progress_state = tx.get(PROGRESS_BUCKET, audit_id)
        repair_activation = tx.get(REPAIR_ACTIVATION, audit_id)
        repair_rows = [row for row in tx.scan(REPAIR_CORRECTIONS)
                       if isinstance(row, dict) and row.get("audit_id") == audit_id]
        partitions = [p for p in tx.scan("research_partitions") if p["audit_id"] == audit_id]
        known = {p["partition_id"]: p for p in partitions}
        assignments, outcomes, held = {}, {}, []
        for row in tx.scan("schedule"):
            if row.get("partition_id") not in known or not row.get("task_id"):
                continue
            task = tx.get("tasks", row["task_id"])
            name = task.get("status", "queued") if isinstance(task, dict) else "not_submitted"
            assignments[name] = assignments.get(name, 0) + 1
            if name != "succeeded":
                continue
            facts = analysis_facts(task.get("result"))
            outcome = facts["analysis_outcome"]
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            # A rejected draft whose partition still stands at the generation it was assigned is
            # HELD: its scope is intact and waiting for an explicit, reviewed decision. This read
            # states that fact; it never retries, reassigns, completes or rewrites the history.
            if outcome == ANALYSIS_REJECTED and (
                    known[row["partition_id"]].get("generation") == facts["analysis_generation"]):
                held.append({"partition_id": row["partition_id"], "task_id": task["id"],
                             "partition_generation": facts["analysis_generation"],
                             "execution_ref": facts["analysis_ref"],
                             "reason_code": facts["analysis_reason"]})
    scope = {"total": len(partitions),
             "with_remaining_work": sum(1 for p in partitions if p["remaining_paths"]
                                        or p["remaining_subsystems"] or p["open_questions"]),
             "remaining_paths": sum(len(p["remaining_paths"]) for p in partitions),
             "remaining_subsystems": sum(len(p["remaining_subsystems"]) for p in partitions),
             "open_questions": sum(len(p["open_questions"]) for p in partitions),
             "max_generation": max((p["generation"] for p in partitions), default=None)}
    analysis = {"outcomes": outcomes, "held_partitions": len(held),
                "held": sorted(held, key=lambda row: (row["partition_id"], row["task_id"]))}
    return {"audit_service": ACTION, "audit_id": audit_id, "known_audit": audit is not None,
            "activation": {key: control.get(key) for key in ("status", "release_id", "revision")},
            "supported_actions": [ACTION], "partitions": scope, "assignments": assignments,
            "analysis": analysis,
            # The observer's own durable state, read only: a dated observation of this audit's
            # records, never a completion, a cause or a promise about the current run.
            "progress": progress_view(progress_state),
            # The bounded repair lineage, read only: the opt-in, each source task -> diagnosis ->
            # successor -> settlement, and the separate counts. A held rejection above stays held
            # until a lineage of its own reports `repaired`; nothing here rewrites that history.
            "repair": repair_view(repair_activation, repair_rows),
            "admission_blocked": block_reason(state, predecessor),
            **{key: state.get(key) for key in ("owner", "current_task", "last_task", "stop_reason",
                                               "completed_tasks", "last_collection", "last_progress",
                                               "last_repair", "started_at", "updated_at")},
            "exit_code": 0}


def _execute(service, args) -> dict:
    from codex_harness.composition.cli_audit_service import run_service as run
    from codex_harness.entry.cli.operation import refusal

    try:
        if args.audit_service_command == "run":
            return run(service, args)
        return _status(service, args)
    except Exception as exc:
        return refusal(exc)
