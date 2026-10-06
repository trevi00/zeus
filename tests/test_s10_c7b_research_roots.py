"""S10 unit C7b: the dge and decision-feedback roots and `composition.cli_research` (DESIGN-s10 §3 C7, R-c12).

Parity with M7 on a disposable PostgreSQL over a fixture git repository is the `entry.cli_research_gov.pg` compare family; these tests
cover the builders' wiring, `run`'s exit semantics, the verbatim source verification and the dispatch table.
"""

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.composition import cli_research
from codex_harness.entry import cli
from codex_harness.entry.cli import decision_feedback, dge
from codex_harness.research.application.decision_feedback import DecisionFeedback
from codex_harness.research.application.dge import DebateSessions, DgeRefused

CLI_DIR = Path(cli.__file__).resolve().parent


def dispatch_keys() -> list[str]:
    tree = ast.parse((CLI_DIR / "__init__.py").read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    return [key.value for key in tables[0].value.keys]


def args(**fields):
    return SimpleNamespace(**fields)


class FakeSource:
    def __init__(self, blobs, commits=("a" * 40,)):
        self.blobs, self.commits = blobs, set(commits)

    def commit_exists(self, revision):
        return revision in self.commits

    def blob(self, revision, path):
        return self.blobs.get(path, (None, b""))


def packet(sha256):
    return {"base_revision": "a" * 40, "sources": [{"id": "s1", "path": "docs/a.md", "sha256": sha256}]}


def test_the_dispatch_table_holds_both_roots():
    assert {"dge", "decision-feedback"} <= set(dispatch_keys())


def test_the_builders_wire_the_target_use_cases(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path))
    store = object()
    service = SimpleNamespace(store=store)
    sessions = cli_research.debate_sessions(service)
    assert isinstance(sessions, DebateSessions) and sessions.store is store
    plain = cli_research.decision_feedback(service)
    assert isinstance(plain, DecisionFeedback) and plain.store is store and plain.evidence is None
    evidence = cli_research.execution_evidence()
    assert Path(evidence.artifacts.root) == tmp_path.resolve() / "artifacts"
    wired = cli_research.decision_feedback(service, evidence)
    assert wired.evidence is evidence and wired.store is store
    assert cli_research.git_source(tmp_path).repository == str(tmp_path)


def test_load_registry_reads_through_the_injected_source():
    registry = {"schema": "urn:zeus:procedure-registry:1", "version": 1,
                "entries": [{"id": "runbook-note", "source_kind": "council", "repository": "repo-identity",
                             "allowed_paths": ["docs/a.md"], "acceptance_criteria_sha256": "c" * 64,
                             "remediation": "existing_owner_review"}]}
    data = json.dumps(registry).encode("utf-8")
    loaded = cli_research.load_registry(FakeSource({"docs/p.json": ("100644", data)}), "a" * 40, "docs/p.json")
    assert loaded["sha256"] == hashlib.sha256(data).hexdigest() and loaded["path"] == "docs/p.json" and loaded["entries"] == 1


def test_verify_sources_binds_regular_blobs_and_refuses_the_rest():
    data = b"text\n"
    good = packet(hashlib.sha256(data).hexdigest())
    assert len(cli_research.verify_sources(good, FakeSource({"docs/a.md": ("100644", data)}))) == 1
    for source, packet_, code in (
            (FakeSource({"docs/a.md": ("100644", data)}, commits=()), good, "base_revision_missing"),
            (FakeSource({}), good, "source_missing_at_base"),
            (FakeSource({"docs/a.md": ("120000", data)}), good, "source_not_regular"),
            (FakeSource({"docs/a.md": ("100644", data)}), packet("b" * 64), "source_digest_mismatch")):
        with pytest.raises(DgeRefused) as caught:
            cli_research.verify_sources(packet_, source)
        assert caught.value.reason_code == code


def test_repository_identity_is_the_digest_of_the_resolved_path(tmp_path):
    from codex_harness.kernel.ids import digest
    assert dge._repository_identity(tmp_path / ".") == digest(str(tmp_path.resolve()))


@pytest.mark.parametrize("module", [dge, decision_feedback])
def test_run_exits_one_iff_the_exit_code_is_not_zero(module, monkeypatch, capsys):
    monkeypatch.setattr("codex_harness.composition.build", lambda: SimpleNamespace(store=None))
    monkeypatch.setattr(module, "_execute", lambda service, namespace: {"status": "read", "exit_code": 0})
    assert module.run(args()) is None
    assert json.loads(capsys.readouterr().out) == {"status": "read", "exit_code": 0}
    for result in ({"status": "refused", "exit_code": 1}, {"status": "odd"}):
        monkeypatch.setattr(module, "_execute", lambda service, namespace, result=result: result)
        with pytest.raises(SystemExit) as caught:
            module.run(args())
        assert caught.value.code == 1
        assert json.loads(capsys.readouterr().out) == result


def test_execute_renders_a_failure_as_a_code_and_a_type(monkeypatch):
    def fail(service, namespace):
        raise RuntimeError("raw message must not leak")

    monkeypatch.setattr(dge, "_status", fail)
    assert dge._execute(None, args(dge_command="status")) == {
        "status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    monkeypatch.setattr(decision_feedback, "_report", fail)
    assert decision_feedback._execute(None, args(decision_feedback_command="report")) == {
        "status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}


def test_execute_routes_each_command(monkeypatch):
    seen = []
    for module, names, field in ((dge, ("register", "submit", "status"), "dge_command"),
                                 (decision_feedback, ("collect", "status", "report"), "decision_feedback_command")):
        for name in names:
            monkeypatch.setattr(module, "_" + name, lambda service, namespace, name=name: {"routed": name})
        for name in names:
            assert getattr(module, "_execute")(None, args(**{field: name})) == {"routed": name}
            seen.append(name)
    assert len(seen) == 6
