"""S8 pilot 88: the M7 reverse progress and source execution applications moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/reverse-source-apps-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparisons are the
`research.reverse_progress` and `research.source_execution` goldens.
"""
import ast
import importlib
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
MODULES = {"reverse_progress": "codex_harness.research.application.reverse_progress",
           "source_execution": "codex_harness.research.application.source_execution"}
NAMES = {"reverse_progress": [("STAGES",), ("STATUSES",), ("ReverseProgress",)], "source_execution": [("SourceExecutions",)]}
ENTRY_POINTS = {"reverse_progress": "Entry points: ReverseProgress, STAGES, STATUSES", "source_execution": "Entry points: SourceExecutions"}
OWN_BUCKETS = {"reverse_progress": {"reverse_requests", "reverse_progress", "reverse_history"},
               "source_execution": {"source_execution_requests", "source_execution_history"}}
R_IMPORTS = {
    "reverse_progress": {"codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["digest", "utcnow"],
                         "codex_harness.research.ports": ["AuditArtifacts"], "codex_harness.storage.ports": ["Store"]},
    "source_execution": {"codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["digest", "utcnow"],
                         "codex_harness.kernel.policy": ["POLICY"]}}
M7_IMPORTS = {
    "reverse_progress": {"codex_harness.domain.model": ["ContractError", "digest", "require", "utcnow"],
                         "codex_harness.ports": ["AuditArtifacts", "Store"]},
    "source_execution": {"codex_harness.domain.model": ["digest", "require", "utcnow"], "codex_harness.domain.policy": ["POLICY"]}}


def m7_text(name):
    path = f"src/codex_harness/application/{name}.py"
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True, text=True).stdout


def target_text(name):
    return Path(importlib.import_module(MODULES[name]).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


class FunctionLevelErrors(ast.NodeTransformer):
    """R-x1 applied to the M7 tree: a function-level `domain.model` import of ContractError reads `kernel.errors`."""

    def visit_ImportFrom(self, node):
        if node.module == "codex_harness.domain.model" and [a.name for a in node.names] == ["ContractError"]:
            node.module = "codex_harness.kernel.errors"
        return node


def statements(src, rewrite=False):
    tree = ast.parse(src)
    if rewrite:
        tree = FunctionLevelErrors().visit(tree)
    out = {}
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def top_imports(src):
    return {n.module: [a.name for a in n.names] for n in ast.parse(src).body if isinstance(n, ast.ImportFrom)}


def function_level_imports(src):
    return [(n.module, [a.name for a in n.names]) for f in ast.walk(ast.parse(src)) if isinstance(f, ast.FunctionDef)
            for n in ast.walk(f) if isinstance(n, ast.ImportFrom)]


@pytest.mark.parametrize("name", sorted(MODULES))
def test_every_statement_is_m7_s_by_ast_in_m7_order(name):
    ref, ours = statements(m7_text(name), rewrite=True), statements(target_text(name))
    assert list(ours) == list(ref) == NAMES[name]
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_reverse_progress_has_m7_s_methods():
    klass = statements(target_text("reverse_progress"))[("ReverseProgress",)]
    assert [n.name for n in klass.body if isinstance(n, ast.FunctionDef)] == ["__init__", "_source", "status", "record"]
    assert statements(target_text("reverse_progress"))[("STAGES",)].value.elts[0].value == "1-A"


def test_source_execution_has_m7_s_methods():
    klass = statements(target_text("source_execution"))[("SourceExecutions",)]
    assert [n.name for n in klass.body if isinstance(n, ast.FunctionDef)] == ["__init__", "_validate", "request", "claim", "result", "complete"]


@pytest.mark.parametrize("name", sorted(MODULES))
def test_the_only_changes_are_the_import_rules_and_the_header(name):
    old, new = top_imports(m7_text(name)), top_imports(target_text(name))
    assert {k: v for k, v in old.items() if k.startswith("codex_harness.")} == M7_IMPORTS[name]
    assert {k: v for k, v in new.items() if k.startswith("codex_harness.")} == R_IMPORTS[name]
    assert {k: v for k, v in new.items() if not k.startswith("codex_harness.")} == {k: v for k, v in old.items() if not k.startswith("codex_harness.")}
    doc = ast.get_docstring(ast.parse(target_text(name)))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text(name))))
    lines = doc.splitlines()
    assert "Layer: application" in lines and "Context: research" in lines
    assert any(line.startswith("Owns: ") for line in lines) and any(line.startswith("Does not own: ") for line in lines)
    assert "Contracts: INV-REVERSE-001" in lines if name == "reverse_progress" else "Contracts: INV-RESEARCH-003" in lines
    assert ENTRY_POINTS[name] in lines


def test_the_function_level_contract_error_imports_read_the_kernel():
    assert function_level_imports(m7_text("source_execution")) == [("codex_harness.domain.model", ["ContractError"])] * 2
    assert function_level_imports(target_text("source_execution")) == [("codex_harness.kernel.errors", ["ContractError"])] * 2
    assert function_level_imports(m7_text("reverse_progress")) == function_level_imports(target_text("reverse_progress")) == []


@pytest.mark.parametrize("name", sorted(MODULES))
def test_imports_are_only_kernel_research_and_storage_ports_and_nothing_does_io(name):
    text = target_text(name)
    tree = ast.parse(text)
    mods = sorted({n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")})
    assert mods == sorted(R_IMPORTS[name])
    assert "codex_harness.domain" not in text.replace("codex_harness.research.domain", "")
    assert "codex_harness.ports" not in text
    body = text.split('"""', 2)[2]
    for word in ("subprocess", "psycopg", "open(", "os.", "docker"):
        assert word not in body, word


@pytest.mark.parametrize("name", sorted(MODULES))
def test_each_module_writes_only_its_own_buckets(name):
    tree = ast.parse(target_text(name))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    puts = {ast.literal_eval(n.args[0]) for n in calls if n.func.attr == "put"}
    assert puts == OWN_BUCKETS[name]


def test_source_execution_reads_the_audit_release_image_and_deployment_rows_by_literal():
    tree = ast.parse(target_text("source_execution"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    gets = {ast.literal_eval(n.args[0]) for n in calls if n.func.attr == "get" and ast.unparse(n.func.value) == "tx"}
    assert gets == {"research_audits", "research_control", "deployment", "images", "releases", "source_execution_requests"}
    assert {ast.literal_eval(n.args[0]) for n in calls if n.func.attr == "scan"} == {"source_execution_requests"}


def test_research_is_the_single_owner_of_the_five_buckets():
    from codex_harness.research import ports

    owned = OWN_BUCKETS["reverse_progress"] | OWN_BUCKETS["source_execution"]
    for bucket in owned:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    src = REPO / "target" / "src" / "codex_harness"
    for context in sorted(p.name for p in src.iterdir() if (p / "ports.py").is_file() and p.name != "research"):
        other = importlib.import_module(f"codex_harness.{context}.ports")
        assert not owned & set(getattr(other, "OWNED_BUCKETS", ())), context
    for name, buckets in OWN_BUCKETS.items():
        named = [path.relative_to(src).as_posix() for path in sorted(src.rglob("*.py"))
                 if any(f"'{b}'" in path.read_text() or f'"{b}"' in path.read_text() for b in buckets)]
        assert named == [f"research/application/{name}.py", "research/ports.py"], named


# ---- behaviour on the target, against literals -------------------------------------------------------------------------------
def source(commit="a"):
    return {"repository": "source-project", "commit": commit * 40, "tree": "b" * 40, "status": "clean"}


@pytest.fixture
def progress(tmp_path):
    from codex_harness.research.application.reverse_progress import ReverseProgress
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    from codex_harness.storage.adapters.memory_store import MemoryStore

    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    ref = artifacts.put("verified generated document", "fixture")["ref"]
    return ReverseProgress(MemoryStore(), artifacts), ref


def test_four_stages_are_recorded_with_a_generation_each(progress):
    app, ref = progress
    for generation, stage in enumerate(("1-A", "1-B", "1-C", "2")):
        row = app.record("p", stage, "complete", source(), [ref], generation, stage)
    assert row["generation"] == 4 and sorted(row["releases"]) == ["1-A", "1-B", "1-C", "2"]
    assert app.status("p", source())["source_state"] == "unchanged"
    assert app.status("p", source("c"))["source_state"] == "changed"
    assert app.status("q", source())["source_state"] == "not_started"
    with app.store.transaction() as tx:
        assert len(tx.scan("reverse_history")) == 4 and len(tx.scan("reverse_requests")) == 4


def test_a_modified_artifact_is_refused_and_the_store_is_unchanged(progress):
    from codex_harness.kernel.errors import ContractError

    app, ref = progress
    app.record("p", "1-A", "complete", source(), [ref], 0, "first")
    (app.artifacts.root / (ref[7:] + ".txt")).write_text("tampered content")
    before = dict(app.store.data)
    with pytest.raises(ContractError, match="Artifact modified"):
        app.record("p", "1-B", "partial", source(), [], 1, "tampered")
    assert app.store.data == before


def test_a_retry_is_the_original_and_a_conflicting_request_is_refused(progress):
    from codex_harness.kernel.errors import ContractError

    app, ref = progress
    original = app.record("p", "1-A", "complete", source(), [ref], 0, "r")
    assert app.record("p", "1-A", "complete", source(), [ref, ref], 0, "r") == original
    before = dict(app.store.data)
    with pytest.raises(ContractError, match="Conflicting reverse request"):
        app.record("p", "1-A", "partial", source(), [ref], 0, "r")
    assert app.store.data == before


def test_dirty_and_moved_sources_do_not_inherit_completion(progress):
    from codex_harness.kernel.errors import ContractError

    app, ref = progress
    app.record("p", "1-A", "complete", source(), [ref], 0, "first")
    assert app.status("p", {**source(), "status": "dirty"})["source_state"] == "dirty"
    assert app.status("p", {**source(), "status": "unknown"})["source_state"] == "unknown"
    with pytest.raises(ContractError, match="dirty or unknown"):
        app.record("p", "1-B", "partial", {**source(), "status": "dirty"}, [], 1, "dirty")
    with pytest.raises(ContractError, match="rebaseline required"):
        app.record("p", "1-B", "partial", source("c"), [], 1, "moved")
    row = app.record("p", "1-A", "partial", source("c"), [], 1, "restart", rebaseline=True)
    assert row["generation"] == 2 and list(row["releases"]) == ["1-A"]


def test_order_and_immutability_are_enforced(progress):
    from codex_harness.kernel.errors import ContractError

    app, ref = progress
    with pytest.raises(ContractError, match="Previous reverse stage is incomplete"):
        app.record("p", "1-B", "complete", source(), [ref], 0, "skip")
    app.record("p", "1-A", "complete", source(), [ref], 0, "first")
    with pytest.raises(ContractError, match="Completed stage is immutable"):
        app.record("p", "1-A", "pending", source(), [], 1, "downgrade")
    with pytest.raises(ContractError, match="Stale reverse progress"):
        app.record("p", "1-B", "partial", source(), [], 0, "late")


class Workflow:
    """The two members `SourceExecutions` reads from a coordination `Workflow`: `store` and `_owned(tx, task)`."""

    def __init__(self, store, audit_id="audit-1"):
        self.store, self.audit_id, self.valid = store, audit_id, True

    def _owned(self, tx, task, now=None):
        from codex_harness.kernel.errors import ContractError

        if not self.valid:
            raise ContractError("Stale or expired task execution")
        return {"id": task["id"], "message": {"what": {"details": {"audit_id": self.audit_id}}}}


def execution():
    from codex_harness.research.application.source_execution import SourceExecutions
    from codex_harness.research.domain.research import SourceIdentity
    from codex_harness.storage.adapters.memory_store import MemoryStore

    store, flow = MemoryStore(), Workflow(MemoryStore())
    flow.store = store
    identity = SourceIdentity("https://github.com/fixture/repo", "1" * 40, "2" * 40, "sha256:" + "0" * 64)
    with store.transaction() as tx:
        tx.put("research_audits", "audit-1", {"id": "audit-1", "source": asdict(identity)})
        tx.put("research_control", "activation", {"status": "active"})
        tx.put("releases", "rel-1", {"id": "rel-1", "status": "active"})
        tx.put("deployment", "active", {"release_id": "rel-1", "revision": "audit"})
        tx.put("images", "rel-1", {"id": "rel-1", "revision": "audit", "image": "sha256:" + "a" * 64})
    return SourceExecutions(flow), flow, identity, {"id": "task-1", "generation": 1}


def rows(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def test_a_claim_with_no_pending_request_is_the_empty_result():
    queue, flow, _, _ = execution()
    before = dict(flow.store.data)
    assert queue.claim() is None
    assert flow.store.data == before


def test_a_request_is_queued_once_claimed_with_the_verified_image_and_completed_under_the_deployment():
    from codex_harness.research.domain.research import ExecutionReceipt

    queue, flow, identity, task = execution()
    request = queue.request(task, identity, ["python", "--version"])
    assert request["status"] == "queued" and queue.request(task, identity, ["python", "--version"]) == request
    row = queue.claim()
    assert row["id"] == request["id"] and row["status"] == "running" and row["image"] == "sha256:" + "a" * 64 and row["release_id"] == "rel-1"
    assert queue.claim() is None
    receipt = ExecutionReceipt(identity, "fixture-env", ["python", "--version"], "fixture-isolation", 0, "sha256:" + "e" * 64, "fixture-runner",
                               passed=True, outcome="executed")
    queue.complete(row, receipt)
    assert queue.result(task, row["id"])["status"] == "succeeded"
    assert len(rows(flow.store, "source_execution_history")) == 1
    with flow.store.transaction() as tx:
        tx.put("deployment", "active", {"release_id": "changed"})
    from codex_harness.kernel.errors import ContractError

    with pytest.raises(ContractError, match="superseded before consumption"):
        queue.result(task, row["id"])


def test_a_refused_request_leaves_the_store_unchanged():
    from codex_harness.kernel.errors import ContractError

    queue, flow, identity, task = execution()
    before = dict(flow.store.data)
    for bad in ([], [""], [1], None):
        with pytest.raises(ContractError, match="Invalid command"):
            queue.request(task, identity, bad)
    from dataclasses import replace

    with pytest.raises(ContractError, match="assignment mismatch"):
        queue.request(task, replace(identity, repository="https://github.com/other/repo"), ["true"])
    flow.valid = False
    with pytest.raises(ContractError, match="Stale or expired task execution"):
        queue.request(task, identity, ["true"])
    assert flow.store.data == before


def test_a_pause_cancels_the_pending_request_with_its_reason_and_the_late_runner_is_fenced():
    from codex_harness.research.domain.research import ExecutionReceipt

    queue, flow, identity, task = execution()
    queue.request(task, identity, ["true"])
    with flow.store.transaction() as tx:
        tx.put("research_control", "activation", {"status": "paused"})
    assert queue.claim() is None
    (row,) = rows(flow.store, "source_execution_requests")
    assert row["status"] == "cancelled" and row["reason"] == "Source execution paused"
    receipt = ExecutionReceipt(identity, "fixture-env", ["true"], "fixture-isolation", 0, "sha256:" + "e" * 64, "fixture-runner", passed=True, outcome="executed")
    queue.complete({**row, "owner": "late-runner"}, receipt)
    assert rows(flow.store, "source_execution_requests") == [row] and len(rows(flow.store, "source_execution_history")) == 1
