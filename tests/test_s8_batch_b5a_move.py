"""S8 batch B5a (DESIGN-s8 §27.1 V26 rule E-4): M7 `adapters/evidence_inspection.py` moves into `evidence.adapters.evidence_inspection`, and
`TreeOwnershipError` moves into `host_os.ports`.

The module is M7's whole, in M7's order, with only its import block (R-ei0), the §3.2 header, `POLICY_FILE`'s one extra `parents` step (R-ei1, the
`runtime_thresholds` R-t2 precedent), the keyword-only `process_tree` port of `_capture` and `EvidenceInspector` (E-4b, E-4c) changed. M7 is read only as
text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour, with REAL child processes
through the real `ProcessTree` injected, is compared by the recorded `evidence.inspector` golden; this file pins what a golden does not state as a rule: the
structure, the import homes, the identity of `TreeOwnershipError` across ports, `process_tree` and the moved module, the refusal when the port is not
wired, and the `_capture_fn` the next batch hands to the execution port.

M7 tests of `tests/test_evidence_inspection.py` (15) NOT ported here: the policy/claim/verdict/denominator parts of
`test_policy_and_claims_are_closed_and_typed` are the `evidence.domain.evidence` family's (the adapter's own `packaged_policy` part is in the golden);
`test_the_profile_metadata_module_replays_only_as_its_exact_argv` replays the repository's profile-metadata module in the checkout (the golden keeps its
authorization half); `test_a_missing_trusted_interpreter_..._never_recorded_as_success`, `test_ledger_binds_...` (memory and PostgreSQL),
`test_recording_failure_is_a_named_notice_not_a_success` and `test_executor_inspects_implementation_claims_in_the_workspace` need the Workflow, the
ledger application (the `evidence.inspections` family) or the executor (S3/S10); `test_read_only_runs_receive_a_host_composed_review_context...` is the
executor's. The remaining adapter tests (file claims, command claims, python replays, deadlines, the four real `_capture` tests) are the golden's cases.
"""

from __future__ import annotations

import ast
import copy
import functools
import inspect
import subprocess
import sys
from pathlib import Path

import pytest
from _audit_root import PACKAGE_SRC
from _layout import REPO

from codex_harness.composition import guarded_launch
from codex_harness.evidence.adapters import evidence_inspection as module
from codex_harness.host_os import ports
from codex_harness.host_os.adapters import process_tree
from codex_harness.kernel.errors import ContractError
from codex_harness.storage.adapters.file_artifacts import FileArtifacts

SRC = PACKAGE_SRC / "codex_harness"
SOURCE = "e38aa722"
M7 = "src/codex_harness/adapters/evidence_inspection.py"
PY = sys.executable
HOMES = {"codex_harness.evidence.domain.evidence", "codex_harness.host_os.ports", "codex_harness.kernel.errors", "codex_harness.kernel.ids", "pathlib"}
REQUIRE_TEXT = "process_tree is not wired"


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(mod):
    return Path(mod.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        name = getattr(node, "name", None) or (node.targets[0].id if isinstance(node, ast.Assign) else i)
        out[name] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def stmt(src):
    return ast.parse(src).body[0]


class Rewrite(ast.NodeTransformer):
    """M7's module with E-4b and E-4c applied to its AST: the structural definition the target is compared against."""

    def __init__(self):
        self.sites = []

    def visit_FunctionDef(self, node):
        if node.name in {"_capture", "__init__"}:
            node.args.kwonlyargs.append(ast.arg(arg="process_tree"))
            node.args.kw_defaults.append(ast.Constant(value=None))
        if node.name == "_capture":
            node.body.insert(1, stmt('require(process_tree is not None, "' + REQUIRE_TEXT + '")'))
            self.sites.append("_capture")
        if node.name == "__init__":
            node.body.append(stmt("self.process_tree = process_tree"))
            node.body.append(stmt("self._capture_fn = functools.partial(_capture, process_tree=self.process_tree)"))
            self.sites.append("__init__")
        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "spawn" and getattr(node.func.value, "id", None) == "ProcessTree":
            node.func.value = ast.Name(id="process_tree", ctx=ast.Load())
            self.sites.append("spawn")
        if isinstance(node.func, ast.Name) and node.func.id == "_capture":
            node.keywords.append(ast.keyword(arg="process_tree", value=ast.parse("self.process_tree", mode="eval").body))
            self.sites.append("_replay call")
        return node


def test_the_module_is_m7s_in_m7s_order_modulo_the_named_rules():
    ours, theirs = statements(text_of(module)), statements(show(SOURCE, M7))
    assert list(ours) == list(theirs) == ["CLEANUP_SECONDS", "READER_JOIN_SECONDS", "POLL_SECONDS", "POLICY_FILE", "KEEP_ENV", "packaged_policy",
                                          "replay_environment", "trusted_interpreter", "replay_argv", "_reclaim", "_unspawned", "_wait", "_capture",
                                          "EvidenceInspector"]
    changed = []
    for name, node in theirs.items():
        rewrite = Rewrite()
        expected = rewrite.visit(copy.deepcopy(node))
        if name == "POLICY_FILE":
            expected = ast.parse(ast.unparse(node).replace("parents[1]", "parents[2]")).body[0]
        assert ast.dump(ours[name]) == ast.dump(expected), name
        if ast.dump(ours[name]) != ast.dump(node):
            changed.append((name, rewrite.sites))
    assert sorted(n for n, _ in changed) == ["EvidenceInspector", "POLICY_FILE", "_capture"]
    sites = sorted(site for _, found in changed for site in found)
    assert sites == ["__init__", "_capture", "_replay call", "spawn"], "each of E-4b (the require and the spawn) and E-4c (init, replay) once"


def test_the_first_header_paragraphs_are_m7s_module_docstring_and_the_fields_are_there():
    doc = ast.get_docstring(ast.parse(text_of(module)))
    m7 = ast.get_docstring(ast.parse(show(SOURCE, M7)))
    assert doc.startswith(m7)
    for field in ("Layer: adapters", "Context: evidence", "Owns:", "Does not own:", "Entry points:", "Contracts:", "Moved from M7", SOURCE,
                  "named rules", "R-ei0", "R-ei1", "E-4b", "E-4c", "V26"):
        assert field in doc, field
    entry = doc.split("Entry points:")[1].split("\n")[0]
    for name in ("EvidenceInspector", "packaged_policy", "replay_environment", "trusted_interpreter", "replay_argv"):
        assert name in entry
    assert "INV-EVIDENCE-001" in doc and "INV-ISOLATED-WORKER-001" in doc


def test_import_homes_and_the_layer_rules():
    text = text_of(module)
    assert set(import_modules(text)) == HOMES
    assert sorted(a.name for n in ast.parse(text).body if isinstance(n, ast.Import) for a in n.names) == [
        "functools", "hashlib", "json", "os", "platform", "subprocess", "sys", "threading", "time"]
    imported = {a.name for n in ast.parse(text).body if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "ProcessTree" not in imported and "TreeOwnershipLeak" not in imported and "TreeOwnershipError" in imported
    assert not [m for m in import_modules(text) if m.startswith(("codex_harness.adapters", "codex_harness.domain", "codex_harness.application"))]
    assert not [m for m in import_modules(text) if m.startswith("codex_harness.host_os") and m != "codex_harness.host_os.ports"], "host_os PORTS only"
    assert "Popen" not in text, "the module creates no process itself: the injected port does"
    import import_rules

    importer = "codex_harness.evidence.adapters.evidence_inspection"
    assert all(import_rules.allowed(importer, m) for m in import_modules(text) if m.startswith("codex_harness."))
    assert module.packaged_policy.__module__ == importer and module.EvidenceInspector.__module__ == importer
    assert module.TreeOwnershipError is ports.TreeOwnershipError
    assert module.ContractError is ContractError


def test_tree_ownership_error_is_one_class_across_ports_process_tree_the_moved_module_and_composition():
    assert process_tree.TreeOwnershipError is ports.TreeOwnershipError is module.TreeOwnershipError is guarded_launch.TreeOwnershipError
    assert ports.TreeOwnershipError.__module__ == "codex_harness.host_os.ports" and ports.TreeOwnershipError.__bases__ == (RuntimeError,)
    assert ports.TreeOwnershipError.__doc__ == "The boundary could not be established, and nothing this harness created is still there."
    assert process_tree.TreeOwnershipLeak.__bases__ == (ports.TreeOwnershipError,) and guarded_launch.TreeOwnershipLeak is process_tree.TreeOwnershipLeak
    assert "TreeOwnershipError" not in [n.name for n in ast.parse(Path(process_tree.__file__).read_text()).body if isinstance(n, ast.ClassDef)]
    assert "TreeOwnershipLeak" not in [n.name for n in ast.parse(Path(ports.__file__).read_text()).body if isinstance(n, ast.ClassDef)]
    assert "TreeOwnershipError" in ports.__doc__.split("Entry points:")[1].split("Contracts:")[0]
    leak = process_tree.TreeOwnershipLeak("left behind", detail={"exit_code": None})
    assert isinstance(leak, ports.TreeOwnershipError) and leak.detail == {"exit_code": None}


def test_the_call_shapes_keep_m7s_positions_and_add_only_the_keyword_only_port():
    init = inspect.signature(module.EvidenceInspector.__init__).parameters
    assert [(p.name, p.kind.name) for p in init.values()] == [
        ("self", "POSITIONAL_OR_KEYWORD"), ("artifacts", "POSITIONAL_OR_KEYWORD"), ("policy", "POSITIONAL_OR_KEYWORD"),
        ("interpreter", "POSITIONAL_OR_KEYWORD"), ("process_tree", "KEYWORD_ONLY")]
    assert init["policy"].default is None and init["interpreter"].default is None and init["process_tree"].default is None
    capture = inspect.signature(module._capture).parameters
    assert [p.name for p in capture.values()] == ["argv", "cwd", "timeout", "max_bytes", "env", "progress", "process_tree"]
    assert capture["process_tree"].kind.name == "KEYWORD_ONLY" and capture["process_tree"].default is None and capture["progress"].default is None
    replay = inspect.signature(module.EvidenceInspector._replay).parameters
    assert [p.name for p in replay.values()] == ["self", "argv", "cwd", "timeout", "max_bytes", "env", "progress"], "the backend seam is M7's"
    for name in ("_trusted", "_python", "_archive", "inspect_file", "inspect_command", "snapshot", "identity", "inspect"):
        theirs = [n for n in statements(show(SOURCE, M7))["EvidenceInspector"].body if isinstance(n, ast.FunctionDef) and n.name == name][0]
        assert [p.name for p in inspect.signature(getattr(module.EvidenceInspector, name)).parameters.values()] == [
            a.arg for a in theirs.args.args + theirs.args.kwonlyargs], name


def test_the_policy_resource_is_found_and_is_m7s_file():
    assert module.POLICY_FILE == SRC / "resources" / "evidence-policy.json" and module.POLICY_FILE.is_file()
    assert module.POLICY_FILE.read_text("utf-8") == show(SOURCE, "src/codex_harness/resources/evidence-policy.json")
    assert module.packaged_policy()["replay"]["allowed_argv_prefixes"][0] == ["python", "-m", "pytest"]


class Port:
    """LABELLED. A process-tree port that records its `spawn` calls and raises what it is told to."""

    def __init__(self, error=None):
        self.calls, self.error = [], error

    def spawn(self, argv, **kwargs):
        self.calls.append((list(argv), sorted(kwargs)))
        raise self.error


def test_no_port_is_refused_before_any_spawn(tmp_path, monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("a child was started")

    monkeypatch.setattr(process_tree, "popen", never)
    with pytest.raises(ContractError, match=REQUIRE_TEXT):
        module._capture([PY, "-c", "pass"], str(tmp_path), 5, 100, {})
    with pytest.raises(ContractError, match=REQUIRE_TEXT):
        module._capture([PY, "-c", "pass"], str(tmp_path), 5, 100, {}, progress=None, process_tree=None)
    # The refusal precedes even the spawn failures the capture turns into outcomes: it is raised, never recorded as a run.
    inspector = module.EvidenceInspector(FileArtifacts(str(tmp_path / "artifacts")), {
        "version": 1, "replay": {"allowed_argv_prefixes": [[PY, "-c"]], "per_command_seconds": 20, "total_seconds": 60, "max_claims": 4,
                                 "max_output_bytes": 4096, "replays_per_claim": 1}, "files": {"max_bytes": 1024}})
    assert inspector.process_tree is None
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ContractError, match=REQUIRE_TEXT):
        inspector.inspect([{"kind": "command", "argv": [PY, "-c", "pass"], "expected_exit": 0}], workspace, {"task_id": "t"})
    with pytest.raises(ContractError, match=REQUIRE_TEXT):
        inspector._capture_fn([PY, "-c", "pass"], str(tmp_path), 5, 100, {})
    # File claims and the snapshot never touch the port, so an unwired inspector still answers them.
    assert inspector.snapshot(workspace)["identity"]["cwd"] == str(workspace.resolve())
    (workspace / "a.txt").write_text("x", encoding="utf-8")
    assert inspector.inspect([{"kind": "file", "path": "a.txt"}], workspace, {"task_id": "t"})["findings"][0]["state"] == "checked"


def test_the_ownership_error_the_capture_catches_is_the_one_host_os_ports_publishes(tmp_path):
    port = Port(ports.TreeOwnershipError("no boundary"))
    run = module._capture([PY], str(tmp_path), 5, 100, {}, process_tree=port)
    assert run["failure"] == "spawn_error: TreeOwnershipError: no boundary" and run["returncode"] is None
    assert run["cleanup"] == {"reason": "spawn_error", "tree": None, "readers_alive": [], "streams_closed": [], "error": None, "confirmed": True}
    assert len(port.calls) == 1 and port.calls[0][0] == [PY] and port.calls[0][1] == ["cwd", "env", "stderr", "stdin", "stdout"]
    # The adapter's own subclass is caught by the same clause and carries its detail into the cleanup proof.
    leak = Port(process_tree.TreeOwnershipLeak("left behind", detail={"exit_code": None, "reason": "fixture"}))
    run = module._capture([PY], str(tmp_path), 5, 100, {}, process_tree=leak)
    assert run["failure"] == "spawn_error: TreeOwnershipLeak: left behind" and run["cleanup"]["confirmed"] is False
    assert run["cleanup"]["leak"] == {"exit_code": None, "reason": "fixture"}
    # Other spawn failures keep their M7 mapping.
    assert module._capture([PY], str(tmp_path), 5, 100, {}, process_tree=Port(FileNotFoundError("x")))["cleanup"]["reason"] == "executable_missing"
    assert module._capture([PY], str(tmp_path), 5, 100, {}, process_tree=Port(PermissionError("x")))["cleanup"]["reason"] == "permission_denied"
    assert module._capture([PY], str(tmp_path), 5, 100, {}, process_tree=Port(OSError("x")))["cleanup"]["reason"] == "spawn_error"


def test_the_inspector_stores_the_port_passes_it_from_replay_and_exposes_the_capture_fn(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    port = Port(ports.TreeOwnershipError("no boundary"))
    inspector = module.EvidenceInspector(artifacts, None, None, process_tree=port)
    assert inspector.process_tree is port
    assert isinstance(inspector._capture_fn, functools.partial)
    assert inspector._capture_fn.func is module._capture and inspector._capture_fn.args == ()
    assert inspector._capture_fn.keywords == {"process_tree": port}
    run = inspector._capture_fn([PY], str(tmp_path), 5, 100, {})
    assert run["failure"].startswith("spawn_error: TreeOwnershipError") and len(port.calls) == 1
    assert inspector._replay([PY], str(tmp_path), 5, 100, {}, progress=None)["failure"].startswith("spawn_error")
    assert len(port.calls) == 2, "_replay spawns through the stored port"
    # The class itself is the port composition passes: its `spawn` is a classmethod, so the class needs no instance.
    assert isinstance(process_tree.ProcessTree.__dict__["spawn"], classmethod)
    real = module.EvidenceInspector(artifacts, None, None, process_tree=process_tree.ProcessTree)
    run = real._capture_fn([PY, "-c", "import sys; sys.stdout.write('ok'); sys.exit(4)"], str(tmp_path), 20, 100, module.replay_environment())
    assert run["returncode"] == 4 and run["stdout"]["raw"] == "ok" and run["cleanup"]["confirmed"] is True and run["failure"] is None
    # Each inspector binds its own port: the partial is per instance.
    other = module.EvidenceInspector(artifacts, process_tree=port)
    assert other._capture_fn is not inspector._capture_fn and other._capture_fn.keywords == {"process_tree": port}


def test_a_subclass_seam_keeps_working_without_a_port(tmp_path):
    """INV-ISOLATED-WORKER-001: a backend that overrides `_replay` (the isolated inspector) never reaches `_capture`, so it needs no port."""
    calls = []

    class Backend(module.EvidenceInspector):
        def _replay(self, argv, cwd, timeout, max_bytes, env, progress=None):
            calls.append(argv)
            return {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.0, "cleanup": {"confirmed": True}}

    backend = Backend(FileArtifacts(str(tmp_path / "artifacts")), {
        "version": 1, "replay": {"allowed_argv_prefixes": [[PY, "-c"]], "per_command_seconds": 20, "total_seconds": 60, "max_claims": 4,
                                 "max_output_bytes": 4096, "replays_per_claim": 1}, "files": {"max_bytes": 1024}})
    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = backend.inspect([{"kind": "command", "argv": [PY, "-c", "pass"], "expected_exit": 0}], workspace, {"task_id": "t"})
    assert report["findings"][0]["state"] == "checked" and calls == [[PY, "-c", "pass"]]
