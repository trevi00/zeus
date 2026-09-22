"""`zeus decision-feedback` adapter and CLI glue (INV-DECISION-FEEDBACK-001).

Git is real: the registry is committed into a disposable repository and read at an explicit commit.
The store is an in-memory Harness and no provider, bus, budget, observer, Redis or PostgreSQL client
exists in this environment, so a successful command is itself the evidence that none is built. The
council runs whose rows are collected come from `test_decision_feedback` (labelled fixtures).
"""
import json
import subprocess
from types import SimpleNamespace

import pytest
from test_decision_feedback import council, entry, harness

from codex_harness import cli
from codex_harness.adapters import decision_feedback_cli
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.decision_feedback import MAX_REGISTRY_BYTES, load_registry
from codex_harness.adapters.dge_cli import repository_identity
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.application.decision_feedback import CANDIDATES, OBSERVATIONS
from codex_harness.domain import decision_feedback as df
from codex_harness.domain.decision_feedback import DecisionFeedbackError, RegistryError
from codex_harness.domain.model import digest

CANARY = "CANARY-must-never-be-emitted"
REGISTRY_PATH = "docs/zeus/procedures.json"


def git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def repository(tmp_path, document, path=REGISTRY_PATH):
    root = tmp_path / "repo"
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(json.dumps(document, indent=2), encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    return root, commit(root, "registry")


def commit(root, message) -> str:
    git(root, "add", "--all")
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def registry_for(identity, **overrides) -> dict:
    return {"schema": df.REGISTRY_SCHEMA, "version": 1,
            "entries": [entry(repository=identity, **overrides)]}


def test_the_registry_is_read_at_the_pinned_commit_and_never_from_the_working_tree(tmp_path):
    root, head = repository(tmp_path, registry_for("repo-identity"))
    loaded = load_registry(GitSource(root), head, REGISTRY_PATH)
    assert loaded["registry"]["entries"][0]["id"] == "runbook-note" and loaded["entries"] == 1
    assert loaded["revision"] == head and loaded["digest"] == digest(loaded["registry"]) and loaded["bytes"] > 0
    (root / REGISTRY_PATH).write_text(json.dumps(registry_for("repo-identity", id="edited-in-worktree")), encoding="utf-8")
    assert load_registry(GitSource(root), head, REGISTRY_PATH)["registry"] == loaded["registry"], "the pin wins"
    moved = commit(root, "edit")
    assert load_registry(GitSource(root), moved, REGISTRY_PATH)["registry"]["entries"][0]["id"] == "edited-in-worktree"
    assert load_registry(GitSource(root), head, REGISTRY_PATH)["sha256"] == loaded["sha256"], "history stays readable"
    for revision, path, code in ((head, "docs/zeus/missing.json", "registry_missing_at_revision"),
                                 ("0" * 40, REGISTRY_PATH, "registry_revision_missing"),
                                 ("HEAD", REGISTRY_PATH, "registry_revision_invalid"),
                                 (head[:39], REGISTRY_PATH, "registry_revision_invalid"),
                                 (head, "../escape.json", "registry_path_invalid"),
                                 (head, "docs/../../etc/passwd", "registry_path_invalid")):
        with pytest.raises(DecisionFeedbackError) as info:
            load_registry(GitSource(root), revision, path)
        assert info.value.reason_code == code


def test_a_non_regular_oversized_malformed_or_invalid_registry_is_refused(tmp_path):
    root, head = repository(tmp_path, registry_for("repo-identity"))
    git(root, "update-index", "--chmod=+x", REGISTRY_PATH)  # an executable blob is not a registry file
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "chmod")
    executable = git(root, "rev-parse", "HEAD")
    with pytest.raises(DecisionFeedbackError) as info:
        load_registry(GitSource(root), executable, REGISTRY_PATH)
    assert info.value.reason_code == "registry_not_regular"
    (root / REGISTRY_PATH).write_text("{not json" + CANARY, encoding="utf-8")
    with pytest.raises(RegistryError) as info:
        load_registry(GitSource(root), commit(root, "broken"), REGISTRY_PATH)
    assert CANARY not in str(info.value) and "not valid JSON" in str(info.value)
    (root / REGISTRY_PATH).write_text('{"schema": "a", "schema": "b", "version": 1, "entries": []}', encoding="utf-8")
    with pytest.raises(RegistryError, match="duplicate JSON key"):
        load_registry(GitSource(root), commit(root, "duplicate"), REGISTRY_PATH)
    (root / REGISTRY_PATH).write_text(json.dumps(registry_for("repo-identity", source_kind="operation")), encoding="utf-8")
    with pytest.raises(RegistryError, match="source_kind"):
        load_registry(GitSource(root), commit(root, "unknown kind"), REGISTRY_PATH)
    (root / REGISTRY_PATH).write_text("[" + "0," * MAX_REGISTRY_BYTES + "0]", encoding="utf-8")
    with pytest.raises(DecisionFeedbackError) as info:
        load_registry(GitSource(root), commit(root, "oversized"), REGISTRY_PATH)
    assert info.value.reason_code == "registry_too_large", "the bytes are bounded before they are parsed"


def wired(tmp_path, monkeypatch, **overrides):
    """A repository whose registry names this checkout's own trusted identity, plus two real runs
    whose execution artifacts are materialized into the runtime artifact root the CLI itself reads
    through `FileArtifacts`: the bytes are the runs' own, and their content addresses are unchanged."""
    identity = repository_identity(tmp_path / "repo")
    root, head = repository(tmp_path, registry_for(identity, **overrides))
    monkeypatch.setattr("codex_harness.adapters.configuration.repository_root", lambda: root)
    svc = harness()
    bound = {"repository": identity, "runtime": "d", "runtime_policy": "p",
             "provider": {"policy_digest": "x", "config_digest": "y"}}
    council(svc, "council-001", identity=bound)
    council(svc, "council-002", identity=bound)
    artifacts = FileArtifacts(str(root / ".runtime" / "artifacts"))
    for body in list(svc.artifacts.bodies.values()):
        artifacts.put(body, "council-run-fixture")
    return svc, root, head, identity


def args(command, **fields):
    defaults = {"registry": REGISTRY_PATH, "revision": None, "limit": 100, "after": None, "collection": None}
    return SimpleNamespace(decision_feedback_command=command, **{**defaults, **fields})


def test_collect_status_and_report_are_read_only_and_bind_the_trusted_repository_identity(tmp_path, monkeypatch):
    svc, root, head, identity = wired(tmp_path, monkeypatch)
    receipt = decision_feedback_cli.execute(svc, args("collect", revision=head))
    assert receipt["exit_code"] == 0 and receipt["status"] == "collected"
    assert receipt["counts"]["eligible"] == 2 and receipt["counts"]["candidates_created"] == 1
    assert receipt["repository"] == identity and receipt["registry"]["revision"] == head
    assert receipt["registry"]["path"] == REGISTRY_PATH and receipt["truncated"] is False
    with svc.store.transaction() as tx:
        candidates = tx.scan(CANDIDATES)
        assert len(candidates) == 1 and candidates[0]["status"] == "needs_analysis" and candidates[0]["verified"] is False
        assert len(tx.scan(OBSERVATIONS)) == 2 and tx.scan("incidents") == []
    status = decision_feedback_cli.execute(svc, args("status"))
    assert status["exit_code"] == 0 and status["counts"][CANDIDATES]["counted"] == 1
    assert status["observed_outcomes"]["accepted"] == 2 and status["quality"]["label"] == "unknown"
    report = decision_feedback_cli.execute(svc, args("report", collection=receipt["id"]))
    assert report["exit_code"] == 0 and report["collection_found"] is True
    assert report["candidates"][0]["occurrences"][0]["run_id"] == "council-001"
    assert list(report["limits"]) == list(df.LIMITS) and report["conflicts"] == []
    again = decision_feedback_cli.execute(svc, args("collect", revision=head))
    assert again["counts"]["candidates_created"] == 0 and again["counts"]["observations_unchanged"] == 2
    assert again["id"] == receipt["id"], "the same pinned input is one collection, not two"


def test_a_different_registry_revision_keeps_its_own_candidate_and_never_merges_scopes(tmp_path, monkeypatch):
    svc, root, head, identity = wired(tmp_path, monkeypatch)
    decision_feedback_cli.execute(svc, args("collect", revision=head))
    (root / REGISTRY_PATH).write_text(json.dumps(registry_for(identity, id="renamed-procedure")), encoding="utf-8")
    moved = commit(root, "rename")
    second = decision_feedback_cli.execute(svc, args("collect", revision=moved))
    assert second["counts"]["candidates_created"] == 1
    with svc.store.transaction() as tx:
        candidates = tx.scan(CANDIDATES)
    assert {c["procedure_id"] for c in candidates} == {"runbook-note", "renamed-procedure"}
    assert {c["registry"]["revision"] for c in candidates} == {head, moved}
    assert all(c["distinct_runs"] == 2 for c in candidates), "the same two runs, pinned twice; never four"


def test_a_registry_that_matches_nothing_is_a_measured_no_candidate_result(tmp_path, monkeypatch):
    svc, root, head, identity = wired(tmp_path, monkeypatch,
                                      allowed_paths=["docs/zeus/operations/other-001/RUNBOOK.md"])
    receipt = decision_feedback_cli.execute(svc, args("collect", revision=head))
    assert receipt["counts"]["eligible"] == 0 and receipt["reasons"]["no_registry_match"] == 2
    assert receipt["counts"]["observations_recorded"] == 2, "the decisions are still observed"
    with svc.store.transaction() as tx:
        assert tx.scan(CANDIDATES) == [], "no forged equivalence when two runs share no registry contract"


def test_failures_print_a_fixed_code_and_a_type_and_never_registry_or_row_content(tmp_path, monkeypatch):
    svc, root, head, identity = wired(tmp_path, monkeypatch)
    missing = decision_feedback_cli.execute(svc, args("collect", revision="0" * 40))
    assert missing == {"status": "refused", "reason_code": "registry_revision_missing",
                       "error_type": "DecisionFeedbackError", "exit_code": 1}
    assert decision_feedback_cli.execute(svc, args("collect", revision=head, limit=0))["reason_code"] == "invalid_scan_limit"
    assert decision_feedback_cli.execute(svc, args("status", limit=df.MAX_SCAN + 1))["reason_code"] == "invalid_scan_limit"
    (root / REGISTRY_PATH).write_text(json.dumps({"schema": df.REGISTRY_SCHEMA, "version": 1,
                                                  "entries": [entry(remediation=CANARY)]}), encoding="utf-8")
    refused = decision_feedback_cli.execute(svc, args("collect", revision=commit(root, "bad remediation")))
    assert refused["reason_code"] == "contract_refused" and refused["error_type"] == "RegistryError"
    assert CANARY not in json.dumps(refused), "a refusal never echoes registry content"
    with svc.store.transaction() as tx:
        assert tx.scan(CANDIDATES) == [] and tx.scan(OBSERVATIONS) == [], "a refused collection writes nothing"


def test_the_cli_registers_the_subcommands_and_requires_the_registry_pin():
    parsed = cli.parser().parse_args(["decision-feedback", "collect", "--registry", REGISTRY_PATH,
                                      "--revision", "a" * 40, "--limit", "25", "--after", "council-001"])
    assert (parsed.command, parsed.decision_feedback_command) == ("decision-feedback", "collect")
    assert (parsed.registry, parsed.revision, parsed.limit, parsed.after) == (REGISTRY_PATH, "a" * 40, 25, "council-001")
    report = cli.parser().parse_args(["decision-feedback", "report", "--collection", "collection:x"])
    assert (report.decision_feedback_command, report.collection, report.limit) == ("report", "collection:x", 100)
    assert cli.parser().parse_args(["decision-feedback", "status"]).limit == 100
    for argv in (["decision-feedback"], ["decision-feedback", "collect"],
                 ["decision-feedback", "collect", "--registry", REGISTRY_PATH],
                 ["decision-feedback", "collect", "--revision", "a" * 40]):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(argv)
