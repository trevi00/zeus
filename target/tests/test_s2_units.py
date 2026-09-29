"""S2 target checks: the SCC removal, the exact metadata command, overflow refusal, profile refusals."""

import json
import subprocess
import sys
from pathlib import Path

import import_rules
import pytest

from codex_harness.context.domain.packet import ContextItem, compile_context
from codex_harness.kernel.errors import ContractError
from codex_harness.routing.domain.profiles import IsolationError, select_profile

TARGET = Path(__file__).resolve().parents[1]
REQUIRED = {"role": "r", "objective": "o", "acceptance_criteria": ["a"], "policy": "p"}


def test_project_skills_and_skill_routing_share_no_import_cycle():
    tree = import_rules.Tree(TARGET / "src")
    cycles = import_rules.sccs(tree)
    assert cycles == []
    edges = {t for t, kind in import_rules.edges(tree, "codex_harness.context.adapters.skill_routing")[0]}
    assert "codex_harness.context.adapters.project_skills" not in edges
    assert "codex_harness.context.adapters.yaml_source" in edges


def test_exact_metadata_command_from_the_target_checkout_root(child_env):
    argv = [sys.executable, "-m", "codex_harness.adapters.worker_profile_metadata"]
    done = subprocess.run(argv, cwd=TARGET, env=child_env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    body = json.loads(done.stdout)
    assert body["status"] == "ok" and body["digest_matches"] and body["within_limit"]
    refused = subprocess.run([*argv, "--help"], cwd=TARGET, env=child_env, capture_output=True, text=True,
                             timeout=60)
    assert refused.returncode == 2 and json.loads(refused.stdout)["error"] == {"kind": "invalid_invocation"}


def test_overflow_refuses_and_optional_items_are_omitted_not_truncated():
    with pytest.raises(ContractError, match="Required contract exceeds budget; split task"):
        compile_context("a", "t", "s", {**REQUIRED, "objective": "x" * 5000}, [], 4000, 0)
    packet = compile_context("a", "t", "s", REQUIRED, [ContextItem("big", "y" * 5000, "ref", "rev", 1),
                                                        ContextItem("small", "z", "ref2", "rev", 0)], 4000, 0)
    assert [e["id"] for e in packet.evidence] == ["small"]
    assert packet.omitted == [{"id": "big", "reason": "budget", "source_ref": "ref"}]
    assert packet.estimated_tokens == len(packet.render().encode())


def test_profile_mapping_refuses_before_spawn_without_host_fallback():
    assert select_profile("claude", "claude_cli", "implement", False, codex_enabled=False) == "claude-impl-rw"
    with pytest.raises(IsolationError) as refused:
        select_profile("codex", "app_server", None, True, codex_enabled=False)
    assert refused.value.reason_code == "codex_profile_disabled"
    with pytest.raises(IsolationError) as shape:
        select_profile("codex", "app_server", "review", False, codex_enabled=True)
    assert shape.value.reason_code == "role_profile_refused"


def test_context_and_knowledge_declare_their_owned_buckets():
    from codex_harness.context import ports as context_ports
    from codex_harness.knowledge import ports as knowledge_ports

    assert set(context_ports.OWNED_BUCKETS) == {"skill_history", "skill_observations", "legacy_skill_imports"}
    assert set(knowledge_ports.OWNED_BUCKETS) == {
        "experience_claims", "profile_consents", "profile_runs", "promotions", "seam_comparisons",
        "seam_ledger_imports", "seam_observations", "seam_views", "snapshot_imports"}
