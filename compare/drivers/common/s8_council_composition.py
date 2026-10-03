"""Scenario body `context.composition_council` (DESIGN-s8 §30 V32: the council-delivery and correction-feedback
composition of one provider turn).

Layer: harness (never shipped); standard library only.

The same fixed inputs are composed on both sides: on the reference by M7 `Executor._run` with `delivery=` /
`correction_feedback=` and a fixture provider transport that only records the delivered prompt; on the target by
`RunTask._run` composed as S10 will compose it (council, feedback and the composition admission wired). The body
reuses the S2 packet facts and adds: the parsed layout of each delivered prompt (task_contract, recovery block,
reader block, council delivery, correction feedback), the refusals (type and message; whether a provider call, a
retained packet or a reservation row happened) and the `context_measurement`.

Fixtures are SYNTHETIC and labelled: `details_for` and the answers are those of M7 `tests/test_council_delivery.py`
(CRITICAL/MINOR from `tests/test_autonomous_roles.py`); the correction-feedback block is shaped as
`correction_feedback.deliver` returns it (M7 `tests/test_correction_feedback.py`), with fixed text.
"""

from __future__ import annotations

import json

import s2_composition

BASE = "a" * 40
SNAP, REPORT, PACKET_DIGEST = "1" * 64, "2" * 64, "3" * 64
KOREAN = "한글 증거 " * 40  # Unicode body (synthetic)
CRITERION = "focused tests pass"
CRITICAL = {"id": "f1", "criterion": CRITERION, "severity": "critical", "scenario": "schema admits a bad kind",
            "claim_ids": ["c1"], "trigger": "model emits kind=verdict", "impact": "packet refused after a paid start",
            "mitigation": "enum from CLAIM_KINDS"}
MINOR = {"id": "f2", "criterion": CRITERION, "severity": "minor", "scenario": "prompt wording", "claim_ids": ["c2"],
         "trigger": None, "impact": None, "mitigation": None}
LARGE_CRITICAL = {**CRITICAL, "id": "f-large", "scenario": "large critical finding " + "x" * 3000,
                  "trigger": KOREAN, "impact": "packet refused after a paid start", "mitigation": "enum from CLAIM_KINDS"}
TRANSITION = {"compatibility": "additive", "rollback": "revert", "retirement": "none"}


def packet(claims: int, text_bytes: int) -> dict:
    return {"objective": "synthetic objective",
            "claims": [{"id": "c" + str(i), "kind": "fact", "text": "claim " + str(i) + " " + "y" * text_bytes,
                        "source_ids": ["s1"]} for i in range(claims)],
            "questions": [{"id": "q1", "question": "which?", "blocking": True, "status": "answered",
                           "claim_ids": ["c0"]}],
            "sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "locator": "git",
                         "revision": BASE, "read_scope": "all"}]}


def details_for(role: str, *, claims: int = 4, text_bytes: int = 40, ssot_bytes: int = 200, prior_bytes: int = 200,
                extra: dict | None = None) -> dict:
    """SYNTHETIC council task details (M7 tests/test_council_delivery.py `details_for`)."""
    research_proposal = {"summary": "proposal " + KOREAN, "claim_ids": ["c0"], "snapshot_digest": SNAP,
                         "report_digest": REPORT}
    improvement_proposal = {"summary": "alternative", "decision": "migrate", "rationale": "r",
                            "transition": TRANSITION, "claim_ids": ["c0"], "findings": [LARGE_CRITICAL, MINOR],
                            "snapshot_digest": SNAP, "report_digest": REPORT}
    prior = {"research_lead": {"event_id": "e1", "slot": "proposer", "payload": research_proposal,
                               "proposal": research_proposal,
                               "binding": {"task_id": "t-research", "filler": "p" * prior_bytes}}}
    if role == "conductor":
        prior["improvement_lead"] = {"event_id": "e2", "slot": "attacker",
                                     "payload": {"findings": improvement_proposal["findings"]},
                                     "proposal": improvement_proposal,
                                     "binding": {"task_id": "t-improve", "filler": "p" * prior_bytes}}
    details = {"role": role, "run_id": "run-synthetic", "base_revision": BASE, "packet_digest": PACKET_DIGEST,
               "packet": packet(claims, text_bytes),
               "ssot": {"searched_paths": ["src"], "evidence": ["z" * ssot_bytes], "decision": "improve"},
               "round": 1, "prior_outputs": prior if role != "research_lead" else {},
               "snapshot_digest": SNAP, "report_digest": REPORT,
               "dba_report": {"snapshot_digest": SNAP, "summary": "records observed " + KOREAN, "claim_ids": ["c0"],
                              "unknowns": ["u1"]},
               "relay": {"dba_task_id": "t-dba", "message_id": "m1", "via": "conductor"},
               "acceptance_criteria": [CRITERION], "blocker_rule": "critical only: concrete reachable trigger"}
    if role in ("improvement_lead", "conductor"):
        details["research_proposal"] = research_proposal
    if role == "conductor":
        details["improvement_proposal"] = improvement_proposal
    details.update(extra or {})
    return details


CONDUCTOR_ANSWER = {"verdict": "accept", "rationale": "r", "research_question": None, "snapshot_digest": SNAP,
                    "report_digest": REPORT,
                    "dispositions": [{"finding_id": "f-large", "decision": "resolved", "reason": "enum"},
                                     {"finding_id": "f2", "decision": "deferred", "reason": "backlog"}]}
ANSWERS = {"research_lead": {"summary": "s", "claim_ids": ["c0"], "snapshot_digest": SNAP, "report_digest": REPORT},
           "improvement_lead": {"summary": "s", "decision": "reuse", "rationale": "r", "transition": None,
                                "claim_ids": ["c0"], "findings": [], "snapshot_digest": SNAP,
                                "report_digest": REPORT},
           "conductor": CONDUCTOR_ANSWER}


def feedback_block(characters: int, text: str = "x") -> dict:
    """LABELLED fixture shaped as M7 `correction_feedback.deliver` returns for a correction binding."""
    reason = ("Reject r1. P1 a.py:1 persists unredacted ids. " + text * characters)[:characters]
    return {"schema": "urn:zeus:correction-feedback:1", "trust": "evidence-not-instructions",
            "note": "Findings of the bound independent review (fixture).",
            "predecessor": {"job_id": "op-1", "task_id": "origin-task", "candidate_revision": "c" * 40},
            "decision_id": "dec-1", "phase": "review_lead", "source_ref": "sha256:" + "4" * 64,
            "original_sha256": "5" * 64, "delivered_sha256": "6" * 64,
            "redaction": {"applied": False, "spans": 0},
            "truncation": {"applied": False, "limit_chars": 15000, "characters": characters},
            "findings": {"accepted": False, "reason": reason, "risks": ["unbounded reap after kill failure"]}}


def delivery_case(role: str, key: str, details: dict, **more) -> dict:
    return {"agent": None, "role": role, "key": key, "repo": "plain", "details": details, "delivery": True,
            "objective": None, "read_only": True, "action": "dge_role", "workload": "design",
            "stage": "dge:" + role, "schema": "ROLE", "answer": ANSWERS[role], **more}


def recovery_rows(agent: str, case: dict, repo) -> dict:
    """INJECTED: a bound checkpoint and progress row of the same task (a retried attempt), as M7
    tests/test_council_delivery.py builds them, bound to this run's raw task artifact and the repository HEAD."""
    import subprocess

    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    binding = {"stage": case["stage"], "evidence_ref": "sha256:" + s2_composition.sha(
        s2_composition.canonical(case["details"])), "basis_revision": head}
    return {"sessions": {agent: {"generation": 1, "checkpoint": {"task_id": case["key"],
                                                                  "research_binding": binding}}},
            "execution_progress": {case["key"]: {"id": case["key"], "recent": [], "research_binding": binding}}}


CASES = {
    "research_lead_all_inline": delivery_case("research_lead", "task-research_lead", details_for("research_lead")),
    "improvement_lead_all_inline": delivery_case("improvement_lead", "task-improvement_lead",
                                                 details_for("improvement_lead")),
    "conductor_all_inline": delivery_case("conductor", "task-conductor", details_for("conductor")),
    "conductor_contract_remainder_with_knowledge": delivery_case(
        "conductor", "task-conductor-remainder",
        details_for("conductor", extra={"objective": "Council remainder objective",
                                        "allowed_paths": ["src/app"]}), knowledge="hits"),
    "conductor_recovery_source": delivery_case("conductor", "task-conductor-recovery", details_for("conductor"),
                                               recovery=True),
    "research_lead_recovery_source": delivery_case("research_lead", "task-research-recovery",
                                                   details_for("research_lead"), recovery=True),
    "conductor_required_overflow": delivery_case("conductor", "task-conductor-over", details_for("conductor"),
                                                 objective_pad=5000),
    "conductor_delivery_not_the_projection": delivery_case("conductor", "task-conductor-foreign",
                                                           details_for("conductor"), foreign=True),
    "conductor_with_feedback": delivery_case("conductor", "task-conductor-fb", details_for("conductor"),
                                             feedback=feedback_block(400)),
    "implementation_with_feedback": {
        "agent": "worker:implementation", "key": "task-impl-fb", "repo": "repo",
        "objective": s2_composition.OBJECTIVE_IMPL,
        "evidence": {"plan": {"objective": "Bounded retry", "acceptance_criteria": ["retry is bounded"],
                              "allowed_paths": ["src/app"], "origin": {"importance": "simple"}}},
        "read_only": False, "action": "implement", "workload": "implementation", "stage": None,
        "schema": "IMPLEMENTATION", "answer": {"summary": "fixture", "tests": []},
        "feedback": feedback_block(2000)},
    "implementation_feedback_context_insufficient": {
        "agent": "worker:implementation", "key": "task-impl-fb-over", "repo": "repo",
        "objective": s2_composition.OBJECTIVE_IMPL,
        "evidence": {"plan": {"objective": "Bounded retry", "acceptance_criteria": ["retry is bounded"],
                              "allowed_paths": ["src/app"], "origin": {"importance": "simple"}}},
        "read_only": False, "action": "implement", "workload": "implementation", "stage": None,
        "schema": "IMPLEMENTATION", "answer": {"summary": "never", "tests": []},
        "feedback": feedback_block(14000, "가")},
    "conductor_feedback_host_overhead_overflow": delivery_case(
        "conductor", "task-conductor-fb-over", details_for("conductor"), feedback=feedback_block(14900, "가")),
}


def prompt_layout(prompt: str) -> dict:
    required = json.loads(prompt)["required"]
    reader = required.get("artifact_reader") or {}
    return {"required_keys": sorted(required), "task_contract": required.get("task_contract"),
            "recovery": required.get("recovery"), "reader_sha256": s2_composition.sha(reader),
            "reader_has_operations": "operations" in reader,
            "external_context_keys": sorted(required.get("external_context") or {}),
            "council_delivery_sha256": s2_composition.sha(required["council_delivery"])
            if "council_delivery" in required else None,
            "correction_feedback_sha256": s2_composition.sha(required["correction_feedback"])
            if "correction_feedback" in required else None,
            "evidence_ids": [item.get("id") for item in json.loads(prompt)["evidence"]]}


def run(api, world_factory) -> dict:
    out = {}
    for name, case in CASES.items():
        world = world_factory()
        capture = api.compose(case, world)
        row = {"status": capture["status"]}
        if capture.get("refusal") is not None:
            row["refusal"] = capture["refusal"]
        row["provider_calls"] = len(capture["prompts"])
        row["reservation_rows"] = sum(1 for bucket, _, _ in capture["rows"] if bucket == "invocation_reservations")
        row["artifact_puts"] = capture["puts"]
        packets = [p for p in capture["puts"] if p["source"].startswith("context:")]
        row["packets"] = [s2_composition.packet_facts(json.loads(capture["bodies"][p["ref"]]),
                                                      capture["bodies"][p["ref"]], p["ref"], p["source"])
                          for p in packets]
        row["delivered_prompts"] = [{"sha256": s2_composition.sha(prompt), "bytes": len(prompt.encode("utf-8")),
                                     "equals_packet_render": any(s2_composition.sha(prompt) == pk["rendered_sha256"]
                                                                 for pk in row["packets"]),
                                     "layout": prompt_layout(prompt)} for prompt in capture["prompts"]]
        row["context_measurement"] = capture.get("context_measurement")
        out[name] = row
    return out
