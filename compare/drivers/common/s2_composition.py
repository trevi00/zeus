"""Scenario body `context.composition` (REBUILD-DESIGN-v2 §2.7 F4, §5.3 S2; S1 acceptance "S2 entry
conditions": rendered context AND context artifact bytes/ref/omissions/manifest hash and consumer
bindings; overflow refusal).

Layer: harness (never shipped); standard library only.

The same fixed inputs are composed on both sides: on the reference by M7 `Executor._run` (the
composition lives inside it at M7) with a fixture provider transport that only records the delivered
prompt; on the target by `context.application.compose.ContextComposer`. `api.compose(case, world)`
returns the raw facts listed in `capture`; this body turns them into the compared result:
- the delivered/rendered input (sha256 and UTF-8 byte length; payloads are never printed);
- the retained `context:<key>` packet artifact: ref, byte length, sha256, canonical bytes, field set,
  compiler version, evidence ids, the omission list, `estimated_tokens` and `manifest_hash` (and
  whether it recomputes), per-key digests of `required`;
- every artifact the composition stored, in order (source label and ref);
- the context-owned consumer binding: the skill-history rows that carry the packet ref;
- the byte measurement (`context_measurement`);
- refusals: type and message, and that no provider call and no packet artifact happened.
The execution-record, checkpoint and observation bindings of the same ref belong to S4/S5 and stay in
the S0 family `effects.context_packet`.
"""

from __future__ import annotations

import hashlib
import json

OBJECTIVE_IMPL = "Implement bounded retry with backoff in src/app/retry.py and add pytest tests"
CASES = {
    "implementation": {
        "agent": "worker:implementation", "key": "task-impl-0001", "repo": "repo", "objective": OBJECTIVE_IMPL,
        "evidence": {"plan": {"objective": "Bounded retry", "acceptance_criteria": ["retry is bounded"],
                              "allowed_paths": ["src/app"], "origin": {"importance": "simple"}},
                     "notes": "N" * 23000},
        "read_only": False, "action": "implement", "workload": "implementation", "stage": None,
        "schema": "IMPLEMENTATION", "answer": {"summary": "fixture", "tests": []}},
    "plan": {
        "agent": "lead:improvement", "key": "task-plan-0001", "repo": "repo",
        "objective": "Create an implementable improvement plan for structured logging tests",
        "evidence": {"proposal": {"objective": "Improve logging", "acceptance_criteria": ["logs are structured"]}},
        "read_only": True, "action": "plan", "workload": "design", "stage": None,
        "schema": "PLAN", "answer": {"objective": "o", "acceptance_criteria": ["a"], "allowed_paths": ["src"]}},
    "decision": {
        "agent": "conductor", "key": "decision-0001", "repo": "repo",
        "objective": "Evaluate review. Assess the retry change and its tests.",
        "evidence": {"candidate": {"revision": "r" * 40, "base": "b" * 40, "tree": "t" * 40, "hook_id": None,
                                   "ignored": True},
                     "hook_contract": {"id": "hook-1", "event": "PreToolUse"},
                     "proposal": {"plan": {"objective": "Nested objective", "acceptance_criteria": ["x"]}}},
        "read_only": True, "action": None, "workload": "final_validation", "stage": "review",
        "schema": "VERDICT", "answer": {"accepted": True, "reason": "r", "blocked": False, "risks": [],
                                        "sre_assessment": "s", "arc42_assessment": "a"}},
    "plain_recovery_knowledge": {
        "agent": "lead:research", "key": "task-plain-0001", "repo": "plain",
        "objective": "Summarize the fixture project README",
        "evidence": {"objective": "Summarize", "acceptance_criteria": ["cites README"]},
        "read_only": True, "action": None, "workload": "design", "stage": None,
        "schema": "PLAN", "answer": {"objective": "o", "acceptance_criteria": ["a"], "allowed_paths": ["src"]},
        "seed": {"sessions": {"lead:research": {"generation": 3, "checkpoint": {
                     "task_id": "task-plain-0001", "provider": "codex", "summary": "earlier turn"}}},
                 "execution_progress": {"task-plain-0001": {"provider": "codex", "last_record": 7,
                                                            "research_binding": {}}}},
        "knowledge": "hits"},
    "knowledge_missing_path": {
        "agent": "lead:research", "key": "task-plain-0002", "repo": "plain",
        "objective": "Summarize the fixture project README again",
        "evidence": {"objective": "Summarize", "acceptance_criteria": ["cites README"]},
        "read_only": True, "action": None, "workload": "design", "stage": None,
        "schema": "PLAN", "answer": {"objective": "o", "acceptance_criteria": ["a"], "allowed_paths": ["src"]},
        "knowledge": "missing_path"},
    "overflow": {
        "agent": "worker:implementation", "key": "task-over-0001", "repo": "repo",
        "objective": "Implement " + ("an oversized objective " * 1100),
        "evidence": {"plan": {"objective": "Oversized", "acceptance_criteria": ["refused"]}},
        "read_only": False, "action": "implement", "workload": "implementation", "stage": None,
        "schema": "IMPLEMENTATION", "answer": {"summary": "never", "tests": []}},
}


def sha(value) -> str:
    data = value if isinstance(value, (bytes, str)) else json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def packet_facts(stored: dict, body: str, ref: str, label: str) -> dict:
    rendered = canonical({"agent_id": stored["agent_id"], "task_id": stored["task_id"],
                          "snapshot": stored["snapshot"], "required": stored["required"],
                          "evidence": stored["evidence"]})
    recomputed = sha({"rendered": rendered, "omitted": stored["omitted"], "compiler": stored["compiler_version"]})
    return {"source_label": label, "ref": ref, "bytes": len(body.encode("utf-8")), "sha256": sha(body),
            "ref_is_sha256_of_bytes": ref == "sha256:" + sha(body), "canonical_bytes": canonical(stored) == body,
            "fields": sorted(stored), "compiler_version": stored["compiler_version"],
            "agent_id": stored["agent_id"], "task_id": stored["task_id"], "snapshot": stored["snapshot"],
            "evidence_ids": [item.get("id") for item in stored["evidence"]],
            "evidence_priorities_trust": sorted({item.get("trust") for item in stored["evidence"]}),
            "omitted": stored["omitted"], "estimated_tokens": stored["estimated_tokens"],
            "estimated_tokens_is_rendered_utf8_bytes": stored["estimated_tokens"] == len(rendered.encode("utf-8")),
            "manifest_hash": stored["manifest_hash"], "manifest_hash_recomputes": recomputed == stored["manifest_hash"],
            "required_keys": sorted(stored["required"]),
            "required_digests": {k: sha(v) for k, v in sorted(stored["required"].items())},
            "project_skills": {k: stored["required"].get("project_skills", {}).get(k)
                               for k in ("status", "selected", "included", "omitted", "project_id")},
            "rendered_sha256": sha(rendered), "rendered_bytes": len(rendered.encode("utf-8"))}


def run(api, world_factory) -> dict:
    out = {}
    for name, case in CASES.items():
        world = world_factory()
        capture = api.compose(case, world)
        row = {"status": capture["status"]}
        if capture.get("refusal") is not None:
            row["refusal"] = capture["refusal"]
        row["provider_calls"] = len(capture["prompts"])
        row["artifact_puts"] = capture["puts"]
        packets = [p for p in capture["puts"] if p["source"].startswith("context:")]
        row["packets"] = [packet_facts(json.loads(capture["bodies"][p["ref"]]), capture["bodies"][p["ref"]],
                                       p["ref"], p["source"]) for p in packets]
        row["delivered_prompts"] = [{"sha256": sha(prompt), "bytes": len(prompt.encode("utf-8")),
                                     "equals_packet_render": any(sha(prompt) == pk["rendered_sha256"]
                                                                 for pk in row["packets"])}
                                    for prompt in capture["prompts"]]
        row["context_measurement"] = capture.get("context_measurement")
        refs = {p["ref"] for p in packets}
        bound = []
        for bucket, key, body in capture["rows"]:
            text = canonical(body)
            hits = sorted(ref for ref in refs if ref in text)
            if bucket in {"skill_history", "skill_observations"}:
                bound.append({"bucket": bucket, "key": key, "context_ref_bound": bool(hits),
                              "body_sha256": sha(body)})
        row["skill_history_rows"] = sorted(bound, key=lambda b: (b["bucket"], b["key"]))
        out[name] = row
    return out
