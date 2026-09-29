"""The role output schemas and request contracts every invocation carries (RESEARCH-S4 D7).

Layer: domain
Context: execution
Owns: the closed output schemas (VERDICT, PLAN, IMPLEMENTATION, RESEARCH, SHORTLIST, GITHUB_RESEARCH,
    DIAGNOSIS), OUTPUT_SEVERITY, the implementation instruction, the artifact-reader contracts, the
    per-transport invocation options, the activity ring counters and the lease cadence
    (M7 `adapters/executor.py` module level, moved unchanged out of the executor)
Does not own: schema preflight/validation (execution.adapters.output_schema, execution_output),
    the host-composed review context and reader handle (they read the host; they move with RunTask)
Entry points: object_schema, TEXT, STRINGS, VERDICT, PLAN, IMPLEMENTATION, RESEARCH, SHORTLIST,
    GITHUB_RESEARCH, DIAGNOSIS, OUTPUT_SEVERITY, implementation_instruction, ARTIFACT_READER,
    DELIVERY_ARTIFACT_READER, invocation_options, activity_basis, sync_activity,
    ACTIVITY_LOCK_SECONDS, LEASE_CHECK_SECONDS, LEASE_RENEW_SECONDS
Contracts: INV-INVOCATION-001, INV-EVIDENCE-001

Every schema is a closed object (`additionalProperties: false`, every property required): the provider's
own schema support is not trusted alone (older Claude CLIs ignored an invalid schema; `format` is not
enforced), so the answer is validated here too (RESEARCH-S4 R5/R6, CE-9). The Codex `outputSchema` is
per turn, so a caller passes the schema on every turn.
"""

from __future__ import annotations

# S2b (FLEET-S2B-SPEC §3): the display-only activity writes wait at most this long for the artifact lock, and use
# the store's fail-fast transaction, so a busy control plane drops a display record instead of stalling a run.
ACTIVITY_LOCK_SECONDS = 0.5


def activity_basis(row: dict):
    """The (activity_sequence, sequence) counters a compact write predicts from, or None when they are not
    non-negative integers (a start then waits for an authoritative write instead of guessing)."""
    counters = (row.get("activity_sequence", 0), row.get("sequence", 0))
    return counters if all(type(value) is int and value >= 0 for value in counters) else None


def sync_activity(row: dict, old_sequence, linked_ref, failed: bool, gap: bool) -> None:
    """Keep the compact ring truthful beside the raw progress it annotates (FLEET-S2B-SPEC §3, D11). A ring whose
    watermark does not equal the progress sequence it was synchronized at (an older producer ran, or a compact
    write was dropped), or that misses a record this run dropped without being able to null the watermark (`gap`:
    a tool start's own write failed), is cleared, never presented as continuous; a dropped compact write leaves
    the watermark null so no reader selects a ring that misses it."""
    ring, watermark = row.get("activity_recent"), row.get("activity_progress_sequence")
    synced = (not gap and isinstance(ring, list) and type(watermark) is int and type(old_sequence) is int
              and watermark == old_sequence)
    if not synced:
        ring = []
    row.setdefault("activity_sequence", 0)
    # Present means this producer wrote the row: zero recorded drops is a known 0, never the legacy "unknown".
    row.setdefault("activity_dropped", 0)
    if linked_ref is not None:
        ring = (ring + [linked_ref])[-6:]
        row["activity_sequence"] += 1
    row["activity_recent"] = ring
    row["activity_progress_sequence"] = None if failed else row.get("sequence", 0)


# Severity of one evaluated output (operating-portfolio-001): an accepted answer is information, a
# refusal is not. A structurally invalid answer and a provider failure both lose the run, so neither
# is a low-severity development note; an interruption or a blocked inspection is a warning.
OUTPUT_SEVERITY = {"accepted": "info", "empty_answer": "warning", "tool_only": "warning",
                   "interrupted": "warning", "inspection_blocked": "warning",
                   "invalid_output": "error", "provider_failure": "error"}


def object_schema(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties)}


TEXT = {"type": "string"}


STRINGS = {"type": "array", "items": TEXT}


VERDICT = object_schema({"accepted": {"type": "boolean"}, "reason": TEXT,
                         "blocked": {"type": "boolean", "description": "Environment prevents verification; this is not a code defect."},
                         "risks": STRINGS, "sre_assessment": TEXT, "arc42_assessment": TEXT})


PLAN = object_schema({"objective": TEXT, "acceptance_criteria": STRINGS, "allowed_paths": STRINGS})


# INV-EVIDENCE-001 / review-contract-001: `tests` is replayed token by token as argv, so it holds
# executed commands only; every description of an outcome belongs in `summary`.
IMPLEMENTATION = object_schema({
    "summary": {**TEXT, "description": "What changed and what was observed: actual results, failures, "
                "skipped tests with reasons, and what was not run. Never a restated expectation."},
    "tests": {**STRINGS, "description": "Only the exact commands you actually executed, one reproducible "
              "command per string, as typed (for example \"python -m pytest tests/test_x.py -q\"). No arrows, "
              "results, pass counts, prose, or commands you did not run; those belong in summary."}})


def implementation_instruction(profiled: bool) -> str:
    """The objective an implementation worker receives, on both paths (operating-portfolio-001).

    Run 5b6a3b1cc9f249dfbbc0b2c8f5407e50 spent 647s and five StructuredOutput attempts, every one
    refused because the required `tests` field was absent; the schema enforcement was right and the
    run was still lost. So the envelope is stated in the instruction as well: BOTH top-level fields
    every time, in the shape this path's schema declares. The shapes below are shapes only - they
    are never a claim that such a check ran, and an empty `tests` stays honest but never becomes
    acceptance on its own. The schema itself is unchanged; this text does not relax it.
    """
    field = ("holds exactly one observation per host-declared check in project_evidence: "
             "{check_id, status, exit_code} with status executed and the integer exit code you "
             "observed (a failure stays a failure), or not_run with null; diagnostic attempts and "
             "everything else belong in `summary`"
             if profiled else
             "lists only the exact commands you executed, one per string, with no arrows, results, "
             "pass counts, descriptions or unexecuted commands")
    shape = ('{"summary": "<concise observed results>", "tests": '
             + ('[{"check_id": "<a declared check_id>", "status": "executed", "exit_code": 0}]}'
                if profiled else '["python -m pytest tests/test_x.py -q"]}'))
    return ("Implement the assigned plan, run meaningful tests, and leave changes ready for "
            "independent review. Answer with the structured output envelope and ALWAYS include "
            "BOTH top-level fields, `summary` and `tests`: neither is optional, an answer that "
            "omits one is refused, and prose instead of the envelope loses the run. `summary` is "
            "concise observed fact - actual results, failures, skips and what was not run, never a "
            "restated expectation. `tests` " + field + ". If you truly executed nothing, an empty "
            "`tests` with the reason in `summary` is honest, but it is never by itself sufficient "
            "for acceptance. Shape only, not an example of work that was done: " + shape)


RESEARCH = object_schema({"title": TEXT, "objective": TEXT, "source_url": TEXT,
                          "evidence": TEXT, "acceptance_criteria": STRINGS})


SHORTLIST = object_schema({"source_url": TEXT})


GITHUB_RESEARCH = object_schema({**RESEARCH["properties"], "source_revision": TEXT})


DIAGNOSIS = object_schema({"confirmed": {"type": "boolean"}, "root_cause": TEXT,
                          "scope": TEXT, "reason": TEXT})


# The reader contract of every generic (non-delivery) prompt: rules plus the exact operation argv catalogue.
ARTIFACT_READER = {
    "instruction": "Preserve reader_argv_prefix and operation argv boundaries; if a shell-backed tool is "
                   "required, quote each element rather than interpolating paths or values. Prefer index, then "
                   "an exact RFC 6901 pointer; continue that operation with next_cursor. Use raw page or search "
                   "only when needed.",
    "operations": {
        "index": ["index", "--limit", "8000"],
        "pointer": ["pointer", "--pointer", "<RFC6901>", "--cursor", "<cursor>", "--limit", "8000"],
        "page": ["page", "--cursor", "<next_cursor>", "--limit", "8000"],
        "search": ["search", "--query", "<text>", "--limit", "8000"],
    },
    "output": "JSON; the total successful stdout is at most --limit characters. Use content, truncated and "
              "next_cursor.",
}


# Council delivery (research-program-001): the exact operation argv arrays already live in
# council_delivery.not_inline, so the prompt states the argv, quoting, cursor and output rules once, without
# the generic catalogue. Recovery sources name no operation, so a delivery prompt that carries any falls back
# to the full contract above.
DELIVERY_ARTIFACT_READER = {
    "instruction": "Run external_context.reader_argv_prefix followed by one not_inline operation as a single "
                   "argv list, never a shell string; if a shell is unavoidable, quote every element. To "
                   "continue, repeat the operation with --cursor set to next_cursor.",
    "output": "JSON of at most --limit characters: content, truncated, next_cursor.",
}


def invocation_options(assignment, *, model, timeout, schema, read_only: bool) -> dict:
    """INV-INVOCATION-001: the request options for this assignment's transport.

    The claude_cli dollar cap travels only when the selected configuration carries the control. Under
    subscription accounting (domain.providers, research program001 batch008) the control is absent
    and the option is omitted rather than sent as null, so the request never declares a ceiling the
    command will not pass and the receipt's `effect_left_to_provider` stays truthful.
    """
    options = {"model": model, "timeout": timeout, "output_schema": schema, "read_only": read_only}
    if assignment.transport == "claude_cli":
        if "max_budget_usd" in assignment.controls:
            options["max_budget_usd"] = assignment.controls["max_budget_usd"]
        options["permission_mode"] = assignment.runtime.get("permission_mode")
    return options


# The cadence the provider path already uses inside `_run`: the remaining deadline is re-read every
# five seconds and the lease renewed every twenty. `LeaseProgress` carries exactly these to the work
# that happens after the provider returned, so one owner keeps one rhythm.
LEASE_CHECK_SECONDS = 5.0


LEASE_RENEW_SECONDS = 20.0
