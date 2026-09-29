"""Shared S4 scenario steps (`execution.progress_activity`): the provider-stream activity projection RunTask writes
into execution_progress (M7 `domain/progress_activity.py`, moved in S4 unchanged).

Layer: harness (never shipped)

`api.pa` is the side's module and `api.ContractError` its contract error. Every function is called through `call`,
so a refusal is recorded by class and code (the message is `activity receipt invalid: <code>`).
"""

from __future__ import annotations


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "code": getattr(exc, "code", None), "message": str(exc)[:200]}


REF = "sha256:" + "a" * 64
NOW = "2026-01-01T00:00:00+00:00"


def receipt_args(**over):
    args = {"execution": "exec-1", "transport": "claude_cli", "event": {"type": "tool_started", "tool": "Bash"},
            "activity_sequence": 1, "progress_sequence": None, "generation": 1, "attempt": 1,
            "collected_at": NOW, "raw_ref": None}
    args.update(over)
    return args


def codex_event(item_type, status="completed", **extra):
    item = {"type": item_type}
    if status is not None:
        item["status"] = status
    return {"method": "item/completed", "params": {"item": item, **extra}}


def run(api) -> dict:
    pa = api.pa
    out = {}
    out["constants"] = {"schema": pa.ACTIVITY_SCHEMA, "ring": pa.ACTIVITY_RING, "body_bytes": pa.ACTIVITY_BODY_BYTES,
                        "builtin_tools": sorted(pa.BUILTIN_TOOLS)}

    labels = list(pa.CLAUDE_ACTIVITY) + ["item_completed", "message", "unknown_label"]
    out["label_claude"] = [call(pa.activity_label, pa.CLAUDE, {"type": v}) for v in labels]
    out["label_codex"] = [call(pa.activity_label, pa.CODEX, {"method": m}) for m in
                          ("item/completed", "thread/tokenUsage/updated", "item_completed", None)]
    out["label_odd"] = [call(pa.activity_label, pa.CLAUDE, e) for e in ("text", None, [], {}, {"type": 3},
                                                                        {"type": ["result"]})]
    out["label_odd"] += [call(pa.activity_label, pa.CODEX, e) for e in ("text", None, [], {})]
    out["label_transport"] = [call(pa.activity_label, t, {"type": "result", "method": "item/completed"})
                              for t in ("other", None, 5)]

    out["result_status"] = [call(pa.claude_result_status, e) for e in (
        {"raw": {}, "status": "success"}, {"raw": {"is_error": False}, "status": "success"},
        {"raw": {"is_error": True}, "status": "success"}, {"raw": {"is_error": 0}, "status": "error"},
        {"raw": {"is_error": 0}, "status": "odd"}, {"raw": {}, "status": None}, {"raw": {}},
        {"raw": [], "status": "success"}, {"status": "success"}, "text", None, [])]

    receipts = {}
    receipts["claude_tool_builtin"] = call(pa.build_receipt, **receipt_args())
    receipts["claude_tool_custom"] = call(pa.build_receipt, **receipt_args(
        event={"type": "tool_started", "tool": "mcp__x__custom"}))
    receipts["claude_tool_nonstring"] = call(pa.build_receipt, **receipt_args(
        event={"type": "tool_started", "tool": ["Bash"]}))
    receipts["claude_session_started"] = call(pa.build_receipt, **receipt_args(
        event={"type": "session_started"}, progress_sequence=2, raw_ref=REF))
    receipts["claude_tool_completed"] = [call(pa.build_receipt, **receipt_args(
        event={"type": "tool_completed", "status": s}, activity_sequence=3, progress_sequence=3, raw_ref=REF))
        for s in ("completed", "failed", "odd", None)]
    receipts["claude_permission_denied"] = call(pa.build_receipt, **receipt_args(
        event={"type": "permission_denied"}, progress_sequence=4, raw_ref=REF))
    receipts["claude_result"] = [call(pa.build_receipt, **receipt_args(
        event=e, progress_sequence=5, raw_ref=REF)) for e in (
        {"type": "result", "raw": {}, "status": "success"}, {"type": "result", "raw": {"is_error": True},
                                                            "status": "success"},
        {"type": "result", "raw": {}, "status": "failed"}, {"type": "result", "raw": [], "status": "success"},
        {"type": "result"})]
    receipts["claude_ignores_occurred"] = call(pa.build_receipt, **receipt_args(
        event={"type": "result", "raw": {}, "status": "success", "occurred_at_ms": 1767225600000},
        progress_sequence=5, raw_ref=REF))
    codex_kw = {"transport": "app_server"}
    receipts["codex_item_types"] = [call(pa.build_receipt, **receipt_args(
        event=codex_event(t, completedAtMs=1767225600000), progress_sequence=6, raw_ref=REF, **codex_kw))
        for t in sorted(pa.CODEX_ITEM_TYPES) + ["somethingNew", None, 7]]
    receipts["codex_statuses"] = [call(pa.build_receipt, **receipt_args(
        event=codex_event("commandExecution", s), progress_sequence=6, raw_ref=REF, **codex_kw))
        for s in ("completed", "failed", "odd", None, 4)]
    receipts["codex_item_missing"] = [call(pa.build_receipt, **receipt_args(
        event=e, progress_sequence=6, raw_ref=REF, **codex_kw)) for e in (
        {"method": "item/completed"}, {"method": "item/completed", "params": {}},
        {"method": "item/completed", "params": {"item": {}}})]
    receipts["codex_occurrence"] = [call(pa.build_receipt, **receipt_args(
        event=codex_event("reasoning", **extra), progress_sequence=6, raw_ref=REF, **codex_kw))
        for extra in ({"completedAtMs": 1767225600000}, {}, {"completedAtMs": "bad"})]
    receipts["not_activity"] = [call(pa.build_receipt, **receipt_args(event=e)) for e in (
        {"type": "message"}, {"method": "thread/tokenUsage/updated"}, "text", None)]
    receipts["not_activity"].append(call(pa.build_receipt, **receipt_args(
        transport="app_server", event={"method": "thread/tokenUsage/updated"})))
    receipts["bad_transport"] = call(pa.build_receipt, **receipt_args(transport="other"))
    receipts["bad_activity_sequence"] = [call(pa.build_receipt, **receipt_args(activity_sequence=v))
                                         for v in (-1, 0, True, "1", None, 1.0)]
    receipts["bad_counters"] = [call(pa.build_receipt, **receipt_args(**{f: v})) for f in ("generation", "attempt")
                                for v in (-1, "1", True, 1.5)]
    receipts["nullable_counters"] = call(pa.build_receipt, **receipt_args(generation=None, attempt=None))
    receipts["zero_counters"] = call(pa.build_receipt, **receipt_args(generation=0, attempt=0))
    receipts["bad_collected_at"] = [call(pa.build_receipt, **receipt_args(collected_at=v)) for v in (
        "2026-01-01T00:00:00", "not a time", None, 5, "")]
    receipts["offset_collected_at"] = call(pa.build_receipt, **receipt_args(collected_at="2026-01-01T09:00:00+09:00"))
    receipts["bad_raw_ref"] = [call(pa.build_receipt, **receipt_args(
        event={"type": "result", "raw": {}, "status": "success"}, progress_sequence=5, raw_ref=v)) for v in (
        "sha256:" + "A" * 64, "sha256:abc", "md5:" + "a" * 32, None, 5, REF + "0", " " + REF)]
    receipts["bad_progress_sequence"] = [call(pa.build_receipt, **receipt_args(
        event={"type": "result", "raw": {}, "status": "success"}, progress_sequence=v, raw_ref=REF))
        for v in (0, -1, None, "5", True)]
    receipts["start_with_raw"] = [
        call(pa.build_receipt, **receipt_args(progress_sequence=1)), call(pa.build_receipt, **receipt_args(raw_ref=REF))]
    receipts["bad_execution"] = [call(pa.build_receipt, **receipt_args(execution=v)) for v in ("", None, 5)]
    receipts["too_large"] = call(pa.build_receipt, **receipt_args(execution="x" * (pa.ACTIVITY_BODY_BYTES + 1)))
    out["build"] = receipts

    def flat(value):
        if isinstance(value, list):
            for item in value:
                yield from flat(item)
        elif isinstance(value, dict) and "value" in value:
            yield value["value"]

    valid = list(flat(list(receipts.values())))
    out["valid_count"] = len(valid)
    out["validate_valid"] = [call(pa.validate_receipt, r) for r in valid]
    base = call(pa.build_receipt, **receipt_args())["value"]
    done = call(pa.build_receipt, **receipt_args(event={"type": "result", "raw": {}, "status": "success"},
                                                 progress_sequence=5, raw_ref=REF))["value"]
    codex = call(pa.build_receipt, **receipt_args(event=codex_event("fileChange", completedAtMs=1767225600000),
                                                  transport="app_server", progress_sequence=6, raw_ref=REF))["value"]
    invalid = {
        "extra_key": {**base, "extra": 1},
        "missing_key": {k: v for k, v in base.items() if k != "raw_ref"},
        "not_dict": [base, "text", None],
        "wrong_schema": {**base, "schema": "urn:other"},
        "bad_status": {**base, "status": "bogus"},
        "status_none_claude": {**base, "status": None},
        "status_list": {**base, "status": ["started"]},
        "status_for_other_label": {**base, "status": "success"},
        "tool_on_result": {**done, "tool_name": "Bash"},
        "tool_custom": {**base, "tool_name": "custom"},
        "tool_list": {**base, "tool_name": ["Bash"]},
        "claude_item_type": {**base, "item_type": "reasoning"},
        "codex_item_type_bad": {**codex, "item_type": "other"},
        "codex_item_type_none": {**codex, "item_type": None},
        "codex_item_type_list": {**codex, "item_type": ["fileChange"]},
        "codex_status_none": {**codex, "status": None},
        "codex_status_bad": {**codex, "status": "started"},
        "bad_transport": {**base, "transport": "other"},
        "transport_list": {**base, "transport": ["claude_cli"]},
        "bad_label": {**base, "event_label": "item_completed"},
        "label_list": {**base, "event_label": ["result"]},
        "execution_empty": {**base, "execution": ""},
        "start_with_raw": {**base, "raw_ref": REF},
        "start_with_progress": {**base, "progress_sequence": 1},
        "result_no_raw": {**done, "raw_ref": None},
        "result_bad_progress": {**done, "progress_sequence": 0},
        "activity_zero": {**base, "activity_sequence": 0},
        "generation_bad": {**base, "generation": -1},
        "attempt_bad": {**base, "attempt": "1"},
        "collected_naive": {**base, "collected_at": "2026-01-01T00:00:00"},
        "collected_offset": {**base, "collected_at": "2026-01-01T09:00:00+09:00"},
        "collected_non_str": {**base, "collected_at": 5},
        "occurred_claude": {**base, "occurred_at": NOW},
        "occurred_codex_ok": {**codex, "occurred_at": NOW},
        "occurred_codex_naive": {**codex, "occurred_at": "2026-01-01T00:00:00"},
        "occurred_codex_non_str": {**codex, "occurred_at": 5},
        "occurred_codex_offset": {**codex, "occurred_at": "2026-01-01T09:00:00+09:00"},
        "too_large": {**base, "execution": "x" * (pa.ACTIVITY_BODY_BYTES + 1)},
    }
    out["validate_invalid"] = {k: (call(pa.validate_receipt, v) if not isinstance(v, list)
                                   else [call(pa.validate_receipt, i) for i in v]) for k, v in invalid.items()}

    values = (["item/completed", "thread/tokenUsage/updated", "claude/system/init", "claude/system/permission_denied"]
              + list(pa.CLAUDE_BASES) + [b + "/subtype" for b in pa.CLAUDE_BASES] + ["claude/systemx", "claude/other",
                                                                                      "claude/", "unknown", "", "text",
                                                                                      None, 3, [], {}, True])
    out["fixed_last_event"] = [call(pa.fixed_last_event, v) for v in values]
    types = sorted(pa.COMPLETED_TYPES) + ["claude/result", "other", "", None, 3, ["message"], True]
    out["fixed_completed_type"] = [call(pa.fixed_completed_type, v) for v in types]
    statuses = sorted(pa.COMPLETED_STATUSES) + ["error: boom", "error", "errored", "claude/result", "other", "", None,
                                                 3, ["error"], True]
    out["fixed_completed_status"] = [call(pa.fixed_completed_status, v) for v in statuses]
    out["vocabularies"] = {"last_event_exact": sorted(pa.LAST_EVENT_EXACT), "claude_bases": list(pa.CLAUDE_BASES),
                           "completed_types": sorted(pa.COMPLETED_TYPES),
                           "completed_statuses": sorted(pa.COMPLETED_STATUSES)}
    return out
