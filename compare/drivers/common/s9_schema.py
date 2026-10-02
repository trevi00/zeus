"""Shared S9 scenario steps (`observation.schema`): M7 `adapters/contracts.py::validate_observation` (INV-OBSERVATION-001).

Layer: harness (never shipped)

`api.validate` is the side's `validate_observation`; `api.REGISTRY`, `api.build_event` and `api.execution_identity` are the side's observation domain
(unchanged by S9: the events are built by it, never typed here, so the registry-derived valid records follow the registry). Valid events are reported
by event-id and body digest; every refusal by its exact `ContractError` text. The error text names the path and the failed keyword only: a canary
value planted in each refused field must appear in no message (`canary_absent`). Nothing is masked: no pid, path, time or id is nondeterministic here.
"""

from __future__ import annotations

import copy
import hashlib
import json

RUN = "0" * 31 + "1"
OTHER_RUN = "f" * 32
CANARY = "CANARY-123"
OBSERVED = "2026-01-01T00:00:00+00:00"


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def outcome(api, event) -> dict:
    try:
        returned = api.validate(event)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)}
    return {"accepted": True, "same_object": returned is event, "digest": canonical_digest(returned)}


def run(api) -> dict:
    def system(event_type="general.process_started", number=1, **extra):
        return api.build_event(
            event_type=event_type, outcome="started",
            execution=api.execution_identity("system", process_run_id=RUN, role="conductor"),
            sequence={"process_run_id": RUN, "number": number, "basis": "spool_append"},
            observed_at=OBSERVED, source={"component": "s9-schema", "host": "fixture-host", "pid": 1},
            attributes={}, **extra)

    def execution(**extra):
        return api.build_event(
            event_type="development.provider_started", outcome="succeeded",
            execution=api.execution_identity("execution", process_run_id=RUN, role="worker:implementation", bucket="tasks", task_id="task-1",
                                             generation=1, attempt=2, provider="codex-app-server", session_id="s-1", invocation_id="i-1",
                                             revision="r-1"),
            sequence={"process_run_id": RUN, "number": 2, "basis": "spool_append"}, observed_at=OBSERVED,
            source={"component": "s9-schema", "host": None, "pid": None}, attributes={"transport": "app-server", "read_only": True},
            occurred_at="2025-12-31T23:59:59+00:00", correlation_id="corr-1", causation_id="cause-1", reason_code="Reason_1",
            evidence_refs=["artifact:abc", "sha256:def"], severity="warning", **extra)

    base = system()
    decisions = api.build_event(
        event_type="general.process_idle_exit", outcome="observed",
        execution=api.execution_identity("execution", process_run_id=RUN, role="reviewer", bucket="decisions_pending", task_id="d-1", generation=0,
                                         attempt=0), sequence={"process_run_id": RUN, "number": None, "basis": "unassigned"},
        observed_at=OBSERVED, source={"component": "s9-schema", "host": "h", "pid": 0}, attributes={"agent": None, "idle_seconds": 5},
        severity="critical", identity=["unassigned", 1])
    out = {"registry_size": len(api.REGISTRY)}
    out["registry_valid"] = {name: outcome(api, system(name, number=index + 1))
                             for index, name in enumerate(sorted(api.REGISTRY))}
    out["valid"] = {"system": outcome(api, base), "execution": outcome(api, execution()), "decisions_pending_unassigned": outcome(api, decisions),
                    "oversize_attributes_are_not_bounded_by_the_schema": outcome(api, {**base, "attributes": {"blob": "x" * 20000, "n": [1, {"a": None}]}}),
                    "every_severity": {sev: outcome(api, {**base, "severity": sev}) for sev in ("debug", "info", "warning", "error", "critical")},
                    "every_outcome": {value: outcome(api, {**base, "outcome": value}) for value in
                                      ("started", "succeeded", "failed", "aborted", "blocked", "unknown", "observed")}}

    def with_path(event, path, value):
        copy_ = copy.deepcopy(event)
        node = copy_
        for key in path[:-1]:
            node = node[key]
        if value is _DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = value
        return copy_

    refused = {}
    # (name, path, value): each planted value is the canary where the field accepts a string/any type.
    cases = [
        ("missing_schema_version", ["schema_version"], _DELETE),
        ("schema_version_other", ["schema_version"], CANARY),
        ("event_id_not_hex", ["event_id"], CANARY),
        ("event_id_wrong_type", ["event_id"], [CANARY]),
        ("category_not_in_enum", ["category"], CANARY),
        ("event_type_pattern", ["event_type"], CANARY + ".x"),
        ("severity_not_in_enum", ["severity"], CANARY),
        ("outcome_not_in_enum", ["outcome"], CANARY),
        ("observed_at_not_a_time", ["observed_at"], CANARY),
        ("observed_at_wrong_type", ["observed_at"], {"v": CANARY}),
        ("occurred_at_not_a_time", ["occurred_at"], CANARY),
        ("correlation_id_empty", ["correlation_id"], ""),
        ("correlation_id_too_long", ["correlation_id"], CANARY + "x" * 300),
        ("causation_id_wrong_type", ["causation_id"], {"v": CANARY}),
        ("reason_code_pattern", ["reason_code"], CANARY),
        ("evidence_refs_wrong_type", ["evidence_refs"], CANARY),
        ("evidence_refs_item_empty", ["evidence_refs"], [CANARY, ""]),
        ("evidence_refs_too_many", ["evidence_refs"], [CANARY] * 33),
        ("attributes_wrong_type", ["attributes"], [CANARY]),
        ("redaction_applied_false", ["redaction", "applied"], False),
        ("redaction_findings_negative", ["redaction", "findings"], -1),
        ("redaction_extra_property", ["redaction", "note"], CANARY),
        ("source_component_empty", ["source", "component"], ""),
        ("source_component_wrong_type", ["source", "component"], {"v": CANARY}),
        ("source_pid_negative", ["source", "pid"], -1),
        ("source_extra_property", ["source", "summary"], CANARY),
        ("execution_process_run_id_pattern", ["execution", "process_run_id"], CANARY),
        ("execution_kind_not_in_enum", ["execution", "kind"], CANARY),
        ("execution_bucket_not_in_enum", ["execution", "bucket"], CANARY),
        ("execution_generation_wrong_type", ["execution", "generation"], CANARY),
        ("execution_extra_property", ["execution", "summary"], CANARY),
        ("system_branch_task_id_not_null", ["execution", "task_id"], CANARY),
        ("system_branch_session_id_not_null", ["execution", "session_id"], CANARY),
        ("system_branch_bucket_not_null", ["execution", "bucket"], "tasks"),
        ("system_branch_generation_not_null", ["execution", "generation"], 1),
        ("sequence_process_run_id_pattern", ["sequence", "process_run_id"], CANARY),
        ("sequence_number_zero", ["sequence", "number"], 0),
        ("sequence_basis_not_in_enum", ["sequence", "basis"], CANARY),
        ("extra_property_summary", ["summary"], CANARY),
        ("extra_property_nested_object", ["extra"], {"summary": CANARY}),
    ]
    for name, path, value in cases:
        refused[name] = outcome(api, with_path(base, path, value))
    execution_event = execution()
    refused["execution_branch_role_null"] = outcome(api, with_path(execution_event, ["execution", "role"], None))
    refused["execution_branch_task_id_null"] = outcome(api, with_path(execution_event, ["execution", "task_id"], None))
    refused["execution_branch_bucket_null"] = outcome(api, with_path(execution_event, ["execution", "bucket"], None))
    refused["execution_branch_generation_null"] = outcome(api, with_path(execution_event, ["execution", "generation"], None))
    refused["execution_branch_attempt_wrong_type"] = outcome(api, with_path(execution_event, ["execution", "attempt"], CANARY))
    missing = {key: outcome(api, with_path(base, [key], _DELETE)) for key in sorted(base)}
    non_objects = {name: outcome(api, value) for name, value in
                   (("none", None), ("string", CANARY), ("list", [CANARY]), ("integer", 7), ("empty_object", {}))}
    out["refused"] = refused
    out["missing_each_required_field"] = missing
    out["non_objects"] = non_objects

    # The five-error cap and the sort order: eight violations at once, reported in sorted-path order (by str(path)), at most five.
    many = copy.deepcopy(base)
    many.update({"event_id": CANARY, "severity": CANARY, "outcome": CANARY, "category": CANARY, "event_type": CANARY, "reason_code": CANARY,
                 "observed_at": CANARY, "summary": CANARY})
    many["execution"]["process_run_id"] = CANARY
    out["cap_and_order"] = {"eight_violations": outcome(api, many)}
    messages = {name: row["message"] for name, row in {**refused, **missing, **non_objects, **out["cap_and_order"]}.items() if "message" in row}
    out["cap_and_order"]["max_entries"] = max(message.count("; ") + 1 for message in messages.values())
    out["canary_absent"] = {"messages_checked": len(messages), "canary_in_any_message": any(CANARY in message for message in messages.values())}
    return out


class _Delete:
    pass


_DELETE = _Delete()
