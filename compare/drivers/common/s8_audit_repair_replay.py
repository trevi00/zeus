"""Shared S8 scenario steps (`research.audit_repair_replay`): M7 `adapters/audit_repair.py` `replay_decode(partition, answer)` (the pure replay of the
content decode of ONE retained draft against its trusted assigned scope; `build_repair` is S10 composition and is not characterized here), characterized
BEFORE it moves into research (DESIGN-s8 §28.1 R-rd1, batch B3). The golden is placement-neutral: it observes SOURCE behaviour only.

`replay_decode` is pure: no store, lease, runner, artifact, transport or provider. It validates the trusted partition (a refusal there is raised, not
returned), runs `AuditExecution.proposed_checkpoint` against the answer, returns only the refusal's TYPE and the digest of its message (`refused` true), or
`refused` false when the draft now decodes cleanly; a failure that is not a `ContractError` propagates.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api` (`replay_decode`, `digest`, `canonical`). The partition is the
LABELLED shape of a stored `research_partitions` row (the fields of `PartitionCheckpoint`); the answers are plain model-answer shapes. Every case reports
whether the inputs were left unchanged; the module path that an interpreter TypeError message prints before `PartitionCheckpoint` is masked (the function repairs, normalizes and deduplicates nothing).
"""

from __future__ import annotations

import copy
import json
import re

SECRET = "password=hunter2-replay-canary-77d0"
PATHS = ["cGF0aC0w", "cGF0aC0x"]
REF = "sha256:" + "a" * 64


def partition(paths=PATHS, subsystems=(), **overrides):
    """LABELLED. The shape of a stored `research_partitions` row (`PartitionCheckpoint` fields)."""
    row = {"audit_id": "audit-fixture-001", "partition_id": "partition-fixture-001", "generation": 0, "paths": list(paths), "subsystems": list(subsystems),
           "evidence_refs": [], "remaining_paths": list(paths), "remaining_subsystems": list(subsystems), "open_questions": [], "cursor": "start", "version": 1}
    row.update(overrides)
    return row


def path_body(kind="semantic", **fields):
    body = {"disposition": kind, "evidence_refs": [REF], "symbols": ["symbol"], "justification": "traced", "links": [], "method": "", "receipt_ids": []}
    body.update(fields)
    return body


def subsystem_body(**fields):
    body = {"paths": [PATHS[0]], "contracts": ["contract"], "entry_points": ["main"], "implementations": ["impl"], "callers": ["caller"],
            "configuration": ["config"], "storage_authority": ["git"], "failure_paths": ["failure"], "tests": [], "receipt_ids": [], "evidence_refs": [REF],
            "contradictions": [], "unresolved_dependencies": [],
            "tests_not_run": [{"test": "upstream suite", "reason": "unavailable", "follow_up": "run in a verified runner"}]}
    body.update(fields)
    return body


def answer_for(part, paths=None, subsystems=None, **fields):
    return {"paths": {key: (paths or {}).get(key) for key in part["paths"]}, "subsystems": {key: (subsystems or {}).get(key) for key in part["subsystems"]},
            "open_questions": [], "cursor": "fixture-cursor", **fields}


def replay(api, part, answer, expected_message=None):
    before = copy.deepcopy((part, answer))
    try:
        value = api.replay_decode(part, answer)
    except Exception as exc:   # the refusal is the characterized result
        # MASKED: the module path the interpreter prints before `PartitionCheckpoint` differs between the trees
        out = {"raised": type(exc).__name__, "message": re.sub(r"codex_harness(\.\w+)*\.(?=PartitionCheckpoint)", "", str(exc))[:200]}
    else:
        out = {"result": value, "keys": sorted(value)}
        if expected_message is not None:
            out["error_digest_is_the_digest_of"] = expected_message if value["error_digest"] == api.digest(expected_message) else None
        out["canary_in_the_result"] = SECRET in api.canonical(value)
    out["inputs_unchanged"] = (part, answer) == before
    return out


def run(api) -> dict:
    out = {}
    first, second = PATHS
    part = partition()
    # a refused draft: the type and the digest of the message, never the message (M7 test_audit_repair.py: the diagnosis digests)
    out["refused_generated_path_without_a_link"] = replay(api, part, answer_for(part, {first: path_body("generated")}), "Missing generator/original link")
    out["refused_foreign_key"] = replay(api, part, {**answer_for(part), "paths": {"Zm9yZWlnbg==": path_body()}}, "Assigned output identities changed")
    out["refused_missing_identity"] = replay(api, part, {**answer_for(part), "paths": {first: path_body()}}, "Assigned output identities changed")
    out["refused_unknown_disposition"] = replay(api, part, answer_for(part, {first: path_body("partial")}), "Unknown disposition")
    out["refused_a_body_carrying_its_identity"] = replay(api, part, answer_for(part, {first: {**path_body(), "path": first}}), "Invalid assigned output record")
    out["refused_invalid_cursor"] = replay(api, part, answer_for(part, cursor=""), "Invalid partition checkpoint")
    out["refused_cursor_not_a_string"] = replay(api, part, answer_for(part, cursor=7), "Invalid analysis cursor")
    out["refused_invalid_questions"] = replay(api, part, answer_for(part, open_questions=["", 7]), "Invalid analysis open questions")
    out["refused_missing_cursor"] = replay(api, part, {k: v for k, v in answer_for(part).items() if k != "cursor"}, "Invalid analysis cursor")
    sub = partition(paths=(), subsystems=["core"])
    out["refused_missing_test_disposition"] = replay(api, sub, answer_for(sub, subsystems={"core": subsystem_body(tests=[], tests_not_run=[])}),
                                                    "Missing subsystem trace: tests")
    out["refused_missing_contracts"] = replay(api, sub, answer_for(sub, subsystems={"core": subsystem_body(contracts=[])}), "Missing subsystem trace: contracts")
    # the canary lives in the refused draft; only the type and a digest leave the function
    out["the_draft_text_never_leaves_the_function"] = replay(api, part, answer_for(part, {first: path_body("generated", justification=SECRET)}),
                                                            "Missing generator/original link")
    # a draft that now decodes cleanly: not refused (a mismatch for the owner, never an eligibility)
    out["clean_all_null"] = replay(api, part, answer_for(part))
    out["clean_one_record"] = replay(api, part, answer_for(part, {first: path_body()}, open_questions=["q"], cursor="1"))
    out["clean_every_path_covered"] = replay(api, part, answer_for(part, {first: path_body(), second: path_body()}))
    out["clean_a_justified_unexecuted_subsystem"] = replay(api, sub, answer_for(sub, subsystems={"core": subsystem_body()}))
    out["an_executed_test_without_a_receipt_is_refused"] = replay(api, sub, answer_for(sub, subsystems={"core": subsystem_body(
        tests=[json.dumps(["fixture-inspection"])], tests_not_run=[])}))
    out["clean_an_executed_test_with_a_receipt_id"] = replay(api, sub, answer_for(sub, subsystems={"core": subsystem_body(
        tests=[json.dumps(["fixture-inspection"])], tests_not_run=[], receipt_ids=["receipt-1"])}))
    # an invalid trusted partition is raised, never returned as a diagnosis
    out["partition_not_a_mapping"] = replay(api, [], answer_for(part))
    out["partition_without_fields"] = replay(api, {}, answer_for(part))
    out["partition_with_an_unknown_field"] = replay(api, {**part, "extra": 1}, answer_for(part))
    out["partition_missing_the_cursor"] = replay(api, {k: v for k, v in part.items() if k != "cursor"}, answer_for(part))
    out["partition_empty_cursor"] = replay(api, partition(cursor=""), answer_for(part))
    out["partition_negative_generation"] = replay(api, partition(generation=-1), answer_for(part))
    out["partition_unsupported_version"] = replay(api, partition(version=2), answer_for(part))
    out["partition_empty_audit_id"] = replay(api, partition(audit_id=""), answer_for(part))
    out["partition_duplicate_paths"] = replay(api, partition(paths=[first, first]), answer_for(partition(paths=[first, first])))
    out["partition_remaining_outside_its_scope"] = replay(api, partition(remaining_paths=["Zm9yZWlnbg=="]), answer_for(part))
    out["partition_invalid_evidence_reference"] = replay(api, partition(evidence_refs=["not-a-reference"]), answer_for(part))
    # a failure that is not a ContractError propagates
    for label, bad in (("a_list", []), ("none", None), ("a_string", "answer")):
        out["answer_" + label + "_propagates"] = replay(api, part, bad)
    out["answer_paths_not_a_mapping"] = replay(api, part, {**answer_for(part), "paths": "x"}, "Assigned output identities changed")
    out["m7_tests"] = {
        "tests/test_audit_repair.py": "`replay_decode` is the default `replay` of `owner(ctx)` and `enabled_owner(...)`, and `repair_adapter.replay_decode` is wrapped by "
                                      "`moving_replay` and `pausing_replay`: every such test drives the AuditRepair owner (family research.audit_repair, whose "
                                      "golden uses a scripted replay) over the real ResearchAudits, a promoted release and the real executor fixtures, so none "
                                      "is reproduced here; the function's own behaviour is the cases above",
        "tests/test_audit_repair_cli.py, tests/test_scheduling.py": "import the fixtures of test_audit_repair.py only (the S10 CLI and the scheduling family)"}
    out["cases"] = len([k for k in out if k != "m7_tests"])
    return out
