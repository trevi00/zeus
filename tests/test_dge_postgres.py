"""INV-DGE-001 on an isolated PostgreSQL schema: transactional submissions, restart from PG and the
claim-time gate. Skipped unless HARNESS_INTEGRATION=1; the owner runs it, not the worker."""
import threading
from copy import deepcopy

import pytest

from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.dge import DebateSessions, DgeRefused
from codex_harness.application.operation import DesignGateRefused, Operation
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.dge import packet_digest, validate_packet
from codex_harness.domain.operation import validate_manifest

BASE = "a" * 40
PLAN = {"objective": "Implement the gate", "acceptance_criteria": ["focused tests pass"], "allowed_paths": ["src/x.py"]}
PACKET = {"schema": "urn:zeus:research-packet:1", "id": "sess-pg", "base_revision": BASE, "topic": "pg", "objective": "decide",
          "exclusions": [], "plan": deepcopy(PLAN),
          "questions": [{"id": "q1", "question": "serialized?", "blocking": True, "status": "answered", "claim_ids": ["c1"]}],
          "sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "locator": "git", "revision": BASE, "read_scope": "all"}],
          "claims": [{"id": "c1", "kind": "fact", "text": "advisory lock", "source_ids": ["s1"]}],
          "limits": {"max_rounds": 1, "deadline": "2030-01-01T00:00:00+00:00"}, "supersedes": None, "research_reason": None}
SOURCES = [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "bytes": 1}]  # fixture: Git-verified shape
IDENTITY = {"repository": "r", "runtime": "d", "runtime_policy": "p", "provider": {"policy_digest": "x", "config_digest": "y"}}
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "rationale": "r", "base_revision": BASE, "bytes": 3}


def event(digest_value, role, version, payload, event_id=None):
    return {"schema": "urn:zeus:debate-event:1", "id": event_id or role + "-1", "expected_version": version,
            "packet_digest": digest_value, "round": 1, "role": role, "payload": payload}


def test_postgres_submissions_have_one_winner_and_the_gate_binds_the_claim(isolated_pgstore):
    valid = validate_packet(PACKET)
    digest_value = packet_digest(valid)
    first = DebateSessions(isolated_pgstore)
    assert first.register(valid, "r", SOURCES)["cached"] is False
    assert DebateSessions(isolated_pgstore).register(valid, "r", SOURCES)["cached"] is True
    outcomes, barrier = [], threading.Barrier(3)

    def attempt(n):
        barrier.wait()
        try:
            outcomes.append(DebateSessions(isolated_pgstore).submit("sess-pg", event(
                digest_value, "proposer", 0, {"summary": "s", "claim_ids": ["c1"]}, "race-" + str(n)))["status"])
        except DgeRefused as exc:
            outcomes.append(exc.reason_code)
    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["recorded", "stale_version", "stale_version"]
    restarted = DebateSessions(isolated_pgstore)
    assert restarted.status("sess-pg")["state"] == "critique" and restarted.status("sess-pg")["version"] == 1
    with pytest.raises(DgeRefused, match="role_out_of_order"):
        restarted.submit("sess-pg", event(digest_value, "proposer", 1, {"summary": "s", "claim_ids": ["c1"]}, "late"))
    harness = Harness(isolated_pgstore, organization())
    manifest = validate_manifest({"schema": "urn:zeus:operation:2", "id": "op-pg", "base_revision": BASE,
                                  "goal": {k: GOAL[k] for k in ("path", "sha256", "criterion", "rationale")}, "plan": deepcopy(PLAN),
                                  "budget": {"per_host": 2, "total": 4},
                                  "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1},
                                  "design": {"session_id": "sess-pg", "packet_digest": digest_value}}, packaged_policy())
    with pytest.raises(DesignGateRefused, match="design_not_approved"):
        Operation(harness).claim(manifest, IDENTITY, GOAL)
    with isolated_pgstore.transaction() as tx:
        assert tx.get("operations", "op-pg") is None and tx.get("local_cycles", "operation:op-pg") is None
    restarted.submit("sess-pg", event(digest_value, "attacker", 1, {"findings": []}))
    restarted.submit("sess-pg", event(digest_value, "arbiter", 2, {"verdict": "accept", "rationale": "ok", "dispositions": [],
                                                                  "research_question": None}))
    claimed = Operation(harness).claim(manifest, IDENTITY, GOAL)
    assert claimed["cached"] is False and claimed["row"]["design"]["session_id"] == "sess-pg"
    with isolated_pgstore.transaction() as tx:
        assert tx.get("operations", "op-pg")["design"]["packet_digest"] == digest_value
        assert tx.get("dge_sessions", "sess-pg")["state"] == "design_approved"
