"""S8 batch B5b (DESIGN-s8 §27.1 V26 rules E-1..E-3, §27.2 E-4d, §27.3 E-5): M7 `adapters/isolated_evidence.py` and `adapters/project_evidence.py` move into
`evidence.adapters`, the container run of a replay (M7 `DockerEvidenceInspector._replay`) into `execution.adapters.containers.evidence_replay`, and the
shared container constants and environment into `evidence.adapters.container_contract`.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour over a
scripted docker, the real cleanup ledger and the real `ProcessTree` is compared by the recorded `evidence.isolated_inspector` and
`evidence.project_inspector` goldens; this file pins what a golden does not state as a rule: the structure, the import homes and the absence of an import
cycle, the one-function-object `_replay`, the delegate and its refusals before any container or snapshot, E-4d's port, and the V9 equalities.

M7 tests NOT ported here (their parts the adapters decide are the goldens' cases): `tests/test_isolated_project_evidence.py`
`test_the_delivery_travels_into_the_container_under_its_own_protocol`, `test_a_delivery_for_another_image_or_workspace_never_reaches_a_container`,
`test_the_entry_hands_the_delivery_to_the_runtime_and_refuses_a_disagreeing_request`,
`test_an_entry_that_predates_delivery_refuses_the_request_rather_than_dropping_the_profile` (the `IsolatedWorker`, runtime and entry: S3 accepted),
`test_the_container_profile_selects_the_isolated_check_runner_and_refuses_a_host_profile` (`IsolatedWorker.inspector`: S3),
`test_bootstrap_*` (bootstrap: S10), `test_the_executor_pairs_only_a_container_profile_with_isolation` and
`test_an_unprofiled_isolated_run_is_exactly_the_legacy_one` (the executor: S10), `test_the_python_only_check_restriction_still_holds_...` (the domain
`parse_profile`: `evidence.domain.project_evidence`); `tests/test_project_evidence.py` `test_operation_identity_binds_the_profile_...` (`operation_cli`: S10)
and `test_executor_gives_worker_and_reviewer_their_own_project_context` (the executor: S10).
"""

from __future__ import annotations

import ast
import copy
import functools
import inspect
import re
import subprocess
from pathlib import Path
from typing import Protocol, get_type_hints

import pytest
from _layout import REPO, TARGET

from codex_harness.evidence import ports
from codex_harness.evidence.adapters import container_contract as cc
from codex_harness.evidence.adapters import evidence_inspection as ei
from codex_harness.evidence.adapters import isolated_evidence as ie
from codex_harness.evidence.adapters import project_evidence as pe
from codex_harness.evidence.domain import project_evidence as domain
from codex_harness.execution.adapters.containers import evidence_replay as er
from codex_harness.execution.adapters.containers import owned_container as oc
from codex_harness.execution.domain import container_spec as spec
from codex_harness.kernel.errors import ContractError

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_ISOLATED = "src/codex_harness/adapters/isolated_evidence.py"
M7_PROJECT = "src/codex_harness/adapters/project_evidence.py"
IMAGE = "sha256:" + "a" * 64


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


def stmt(src):
    return ast.parse(src).body[0]


def method(src, cls, name):
    for node in ast.parse(src).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    raise AssertionError(cls + "." + name)


def import_map(src, lazy=False):
    """{module: names}; top-level imports, or only those nested in a function."""
    tree = ast.parse(src)
    top = {id(n) for n in tree.body}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and ((id(node) in top) != lazy):
            out.setdefault(node.module, []).extend(a.name for a in node.names)
    return {k: sorted(v) for k, v in out.items()}


DELEGATE = '''    def _replay(self, argv, cwd, timeout, max_bytes, env, progress=None, workdir=WORKSPACE):
        require(self.containers is not None, "containers is not wired")
        return self.containers.replay(argv, cwd, timeout, max_bytes, env, capture=self._capture_fn, progress=progress,
                                      workdir=workdir)
'''


# ---- E-1: the body is M7's `_replay` modulo the named rules ---------------------------------------------------------------------
class RewriteReplay(ast.NodeTransformer):
    def __init__(self):
        self.sites = []

    def visit_FunctionDef(self, node):
        node.name = "replay"
        a = node.args
        progress, workdir = a.args[6], a.args[7]
        defaults = a.defaults
        a.args, a.kwonlyargs, a.kw_defaults, a.defaults = a.args[:6], [ast.arg(arg="capture"), progress, workdir], [None, *defaults], []
        self.sites.append("E-1a")
        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        name = getattr(node.func, "id", None)
        if name == "OwnedContainer":
            node.keywords.append(ast.keyword(arg="runner", value=ast.parse("self.runner", mode="eval").body))
            self.sites.append("E-1c")
        if name == "_capture":
            node.func.id = "capture"
            self.sites.append("E-1d")
        if name == "container_args":
            node.keywords.append(ast.keyword(arg="user", value=ast.parse("host_user()", mode="eval").body))
            self.sites.append("E-1b")
        return node


def test_e1_replay_body_is_m7s_modulo_the_named_rules():
    m7 = method(show(SOURCE, M7_ISOLATED), "DockerEvidenceInspector", "_replay")
    rewrite = RewriteReplay()
    expected = rewrite.visit(copy.deepcopy(m7))
    assert sorted(rewrite.sites) == ["E-1a", "E-1b", "E-1c", "E-1d"], "each rule once"
    ours = method(text_of(er), "ContainerEvidenceReplay", "replay")
    assert ast.dump(ours) == ast.dump(ast.fix_missing_locations(expected))
    assert ast.get_docstring(ours) == ast.get_docstring(m7), "the method docstring is M7's"


def test_e1_class_shape_and_the_runner_is_keyword_only():
    cls = er.ContainerEvidenceReplay
    assert [n for n in vars(cls) if not n.startswith("__") or n == "__init__"] == ["__init__", "summary", "replay"]
    init = inspect.signature(cls.__init__).parameters
    assert list(init) == ["self", "isolation", "root", "docker", "runner"] and init["runner"].kind is init["runner"].KEYWORD_ONLY
    assert init["docker"].default == "docker" and init["runner"].default is init["runner"].empty
    replay = inspect.signature(cls.replay).parameters
    assert list(replay) == ["self", "argv", "cwd", "timeout", "max_bytes", "env", "capture", "progress", "workdir"]
    assert replay["capture"].kind is replay["capture"].KEYWORD_ONLY and replay["capture"].default is replay["capture"].empty
    assert replay["progress"].default is None and replay["workdir"].default == spec.WORKSPACE
    sentinel = object()
    one = cls({"image": IMAGE}, "/tmp/x", "d", runner=sentinel)
    assert (one.isolation, one.root, one.docker, one.runner) == ({"image": IMAGE}, Path("/tmp/x"), "d", sentinel)


def test_e1_user_is_the_hosts_as_launcher_does_and_the_imports_are_same_context():
    imports = import_map(text_of(er))
    assert imports["codex_harness.execution.adapters.containers.owned_container"] == ["OwnedContainer", "docker_environment", "host_user"]
    assert set(imports) == {"__future__", "pathlib", "uuid", "codex_harness.execution.adapters.containers.cleanup_ledger",
                            "codex_harness.execution.adapters.containers.owned_container", "codex_harness.execution.adapters.containers.staging",
                            "codex_harness.execution.domain.container_spec", "codex_harness.kernel.errors", "codex_harness.kernel.ids"}
    assert "subprocess" not in text_of(er) and "Popen" not in text_of(er)
    assert oc.host_user.__module__ == "codex_harness.execution.adapters.containers.owned_container"


# ---- E-2: the port, the delegate, the refusals ---------------------------------------------------------------------------------
def test_e2_the_port_has_exactly_summary_and_replay():
    assert issubclass(ports.ContainerReplay, Protocol)
    names = sorted(n for n in vars(ports.ContainerReplay) if not n.startswith("_"))
    assert names == ["replay", "summary"]
    signature = inspect.signature(ports.ContainerReplay.replay).parameters
    assert list(signature) == ["self", "argv", "cwd", "timeout", "max_bytes", "env", "capture", "progress", "workdir"]
    assert signature["capture"].kind is signature["capture"].KEYWORD_ONLY and signature["progress"].default is None
    ours = inspect.signature(er.ContainerEvidenceReplay.replay).parameters
    assert {k: v.kind for k, v in signature.items()} == {k: v.kind for k, v in ours.items()}, "the execution class satisfies the port"
    assert ports.OWNED_BUCKETS == ("evidence_inspections", "evidence_inspection_notices", "completion_verdicts", "completion_rejections")
    assert get_type_hints(ports.ContainerReplay.summary).get("return") is dict


def isolation():
    return oc.load_host_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})


class Port:
    pass


class RecordingContainers:
    def __init__(self):
        self.calls, self.isolation = [], isolation()

    def summary(self):
        return {"summary": True}

    def replay(self, argv, cwd, timeout, max_bytes, env, *, capture, progress=None, workdir="/workspace"):
        self.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "max_bytes": max_bytes, "env": env, "capture": capture,
                           "progress": progress, "workdir": workdir})
        return {"returncode": 0}


def test_e2_replay_is_the_one_delegate_and_both_classes_share_one_function_object():
    assert ie.IsolatedProjectEvidenceInspector._replay is ie.DockerEvidenceInspector._replay
    assert "_replay" not in vars(ie.IsolatedProjectEvidenceInspector) or vars(ie.IsolatedProjectEvidenceInspector)["_replay"] is ie.DockerEvidenceInspector._replay
    ours = method(text_of(ie), "DockerEvidenceInspector", "_replay")
    expected = ast.parse("class _D:\n" + DELEGATE).body[0].body[0]
    assert ast.dump(ours.args) == ast.dump(expected.args)
    assert [ast.dump(n) for n in ours.body[1:]] == [ast.dump(n) for n in expected.body], "the docstring, the require and the one return"
    m7 = method(show(SOURCE, M7_ISOLATED), "DockerEvidenceInspector", "_replay")
    assert ast.dump(ours.args) == ast.dump(m7.args), "the positional shape is M7's"


def test_e2_the_delegate_hands_the_inspectors_own_capture_and_the_port_through(tmp_path):
    containers, port = RecordingContainers(), Port()
    insp = ie.DockerEvidenceInspector(None, containers.isolation, tmp_path, containers=containers, process_tree=port)
    progress = lambda stage=None: None  # noqa: E731
    assert insp._replay(["a"], tmp_path, 3, 4, {"E": "1"}, progress=progress, workdir="/workspace/x") == {"returncode": 0}
    call, = containers.calls
    assert call["capture"] is insp._capture_fn and call["progress"] is progress and call["workdir"] == "/workspace/x"
    assert (call["argv"], call["cwd"], call["timeout"], call["max_bytes"], call["env"]) == (["a"], tmp_path, 3, 4, {"E": "1"})
    assert isinstance(insp._capture_fn, functools.partial) and insp._capture_fn.keywords == {"process_tree": port}
    insp._replay(["b"], tmp_path, 1, 1, {})
    assert containers.calls[1]["progress"] is None and containers.calls[1]["workdir"] == cc.WORKSPACE


def test_e2_unwired_containers_refuse_before_any_container_or_snapshot(tmp_path):
    root = tmp_path / "replays"
    config = isolation()
    docker = ie.DockerEvidenceInspector(None, config, root)
    with pytest.raises(ContractError, match="containers is not wired"):
        docker._replay(["python"], tmp_path, 1, 1, {})
    with pytest.raises(ContractError, match="containers is not wired"):
        docker.snapshot(tmp_path)
    assert not root.exists() and not list(tmp_path.glob("*/workspace"))
    profile = domain.parse_profile({"schema": domain.SCHEMA_V2, "execution": {"kind": "container", "image": IMAGE},
                                    "contexts": {"b": {"cwd": "b", "interpreter": cc.TRUSTED_PYTHON, "source_paths": ["b/src"],
                                                       "dependency_files": ["b/r.lock"]}},
                                    "checks": [{"id": "u", "context": "b", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0}]},
                                   ei.packaged_policy())
    project = ie.IsolatedProjectEvidenceInspector(None, profile, config, root)
    with pytest.raises(ContractError, match="containers is not wired"):
        project.snapshot(tmp_path)
    with pytest.raises(ContractError, match="containers is not wired"):
        project._execute_check(["python"], {"workspace": str(tmp_path), "environment": {}, "cwd": "/workspace/b"}, 1, 1)
    assert not root.exists()


def test_e2_summary_is_read_from_the_port_and_the_constructor_refuses_before_storing(tmp_path):
    containers = RecordingContainers()
    insp = ie.DockerEvidenceInspector(None, containers.isolation, tmp_path, containers=containers, process_tree=Port())
    assert insp.snapshot(tmp_path)["identity"]["container"]["summary"] is True
    host = domain.parse_profile({"schema": domain.SCHEMA, "contexts": {"b": {"cwd": "b", "interpreter": "/usr/bin/python3", "source_paths": ["b/src"],
                                                                         "dependency_files": ["b/r.lock"]}},
                                 "checks": [{"id": "u", "context": "b", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0}]},
                                ei.packaged_policy())
    with pytest.raises(ContractError, match="version 1 has no container execution"):
        ie.IsolatedProjectEvidenceInspector(None, host, containers.isolation, tmp_path / "x", containers=containers, process_tree=Port())
    assert not (tmp_path / "x").exists()


def test_e2_keyword_only_ports_and_unchanged_positional_shapes():
    for cls, positional in ((ie.DockerEvidenceInspector, ["self", "artifacts", "isolation", "root", "docker", "policy"]),
                            (ie.IsolatedProjectEvidenceInspector, ["self", "artifacts", "profile", "isolation", "root", "docker", "policy"])):
        parameters = inspect.signature(cls.__init__).parameters
        assert list(parameters)[:len(positional)] == positional and list(parameters)[len(positional):] == ["containers", "process_tree"]
        for name in ("containers", "process_tree"):
            assert parameters[name].kind is parameters[name].KEYWORD_ONLY and parameters[name].default is None
        assert parameters["docker"].default == "docker" and parameters["policy"].default is None


# ---- E-4d: the port reaches the host route ----------------------------------------------------------------------------------
def host_profile(tmp_path):
    return domain.parse_profile({"schema": domain.SCHEMA, "contexts": {"b": {"cwd": "b", "interpreter": str(Path(inspect.getfile(inspect)).resolve()),
                                                                         "source_paths": ["b/src"], "dependency_files": ["b/r.lock"]}},
                                 "checks": [{"id": "u", "context": "b", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0}]},
                                ei.packaged_policy())


def test_e4d_process_tree_is_forwarded_through_the_project_inspector_to_the_base(tmp_path):
    port = Port()
    insp = pe.ProjectEvidenceInspector(None, host_profile(tmp_path), None, None, process_tree=port)
    assert insp.process_tree is port and insp._capture_fn.keywords == {"process_tree": port}
    parameters = inspect.signature(pe.ProjectEvidenceInspector.__init__).parameters
    assert list(parameters) == ["self", "artifacts", "profile", "policy", "interpreter", "process_tree"]
    assert parameters["process_tree"].kind is parameters["process_tree"].KEYWORD_ONLY and parameters["process_tree"].default is None
    assert pe.ProjectEvidenceInspector(None, host_profile(tmp_path)).process_tree is None
    containers = RecordingContainers()
    isolated = ie.IsolatedProjectEvidenceInspector(None, domain.parse_profile(
        {"schema": domain.SCHEMA_V2, "execution": {"kind": "container", "image": IMAGE},
         "contexts": {"b": {"cwd": "b", "interpreter": cc.TRUSTED_PYTHON, "source_paths": ["b/src"], "dependency_files": ["b/r.lock"]}},
         "checks": [{"id": "u", "context": "b", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0}]}, ei.packaged_policy()),
        containers.isolation, "/nowhere", containers=containers, process_tree=port)
    assert isolated.process_tree is port and isolated.containers is containers


def test_e4d_the_host_check_passes_the_port_to_the_module_level_capture_and_the_patch_seam_remains(tmp_path, monkeypatch):
    port, seen = Port(), []
    monkeypatch.setattr(pe, "_capture", lambda *a, **k: seen.append((a, k)) or {"returncode": 0})
    insp = pe.ProjectEvidenceInspector(None, host_profile(tmp_path), process_tree=port)
    context = {"cwd": "/c", "environment": {"A": "1"}}
    assert insp._execute_check(["x"], context, 2, 3, progress=print) == {"returncode": 0}
    (args, kwargs), = seen
    assert args == (["x"], "/c", 2, 3, {"A": "1"}) and kwargs == {"progress": print, "process_tree": port}


def test_e4d_unwired_host_route_refuses_before_any_spawn(tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
    insp = pe.ProjectEvidenceInspector(None, host_profile(tmp_path))
    with pytest.raises(ContractError, match="process_tree is not wired"):
        insp._execute_check([ "python", "-c", "pass"], {"cwd": str(tmp_path), "environment": {}}, 1, 1)
    assert spawned == []
    assert "process_tree is not wired" not in text_of(pe), "no new require in the project module: E-4b refuses at _capture's head"


# ---- E-3 / E-5: the V9 equalities and the one declaration ---------------------------------------------------------------------
def test_e3_the_constants_equal_the_execution_published_language_and_are_not_the_domain_image():
    assert (cc.MODE, cc.TRUSTED_PYTHON, cc.WORKSPACE) == (spec.MODE, spec.TRUSTED_PYTHON, spec.WORKSPACE)
    assert cc.IMAGE.pattern == spec.IMAGE.pattern and cc.IMAGE.flags == spec.IMAGE.flags
    assert cc.IMAGE.pattern == "sha256:[0-9a-f]{64}"
    assert domain.IMAGE.pattern == r"sha256:[0-9a-f]{64}\Z" != cc.IMAGE.pattern and domain.IMAGE is not cc.IMAGE
    assert domain.CONTAINER_INTERPRETER == cc.TRUSTED_PYTHON
    assert cc.IMAGE.fullmatch(IMAGE) and not cc.IMAGE.fullmatch(IMAGE + "\n") and not cc.IMAGE.fullmatch("latin")


def test_e3_each_constant_is_declared_once_in_evidence():
    declared = {n: [p.name for p in (SRC / "evidence").rglob("*.py") if re.search(rf"^{n}\s*=", p.read_text(), re.M)]
                for n in ("MODE", "TRUSTED_PYTHON", "WORKSPACE", "CONTAINER_ENVIRONMENT")}
    assert declared == {"MODE": ["container_contract.py"], "TRUSTED_PYTHON": ["container_contract.py"], "WORKSPACE": ["container_contract.py"],
                        "CONTAINER_ENVIRONMENT": ["container_contract.py"]}
    assert sorted(p.name for p in (SRC / "evidence").rglob("*.py") if re.search(r"^IMAGE\s*=", p.read_text(), re.M)) == [
        "container_contract.py", "project_evidence.py"]


def test_e3_container_binding_uses_the_local_constants(tmp_path):
    config = isolation()
    profile = domain.parse_profile({"schema": domain.SCHEMA_V2, "execution": {"kind": "container", "image": IMAGE},
                                    "contexts": {"b": {"cwd": "b", "interpreter": cc.TRUSTED_PYTHON, "source_paths": ["b/src"],
                                                       "dependency_files": ["b/r.lock"]}},
                                    "checks": [{"id": "u", "context": "b", "argv": ["python", "-m", "pytest", "-q"], "expected_exit": 0}]},
                                   ei.packaged_policy())
    assert pe.container_binding(profile, config) == {"kind": "container", "image": IMAGE, "mode": "docker", "limits": config["limits"],
                                                     "isolation_digest": config["digest"]}
    assert pe._container_path(".") == "/workspace" and pe._container_path("a/b") == "/workspace/a/b"
    with pytest.raises(ContractError, match="requires the host isolation selection"):
        pe.container_binding(profile, {**config, "image": IMAGE + "\n"})
    assert "TRUSTED_PYTHON == CONTAINER_INTERPRETER" in text_of(pe), "M7's equality assertion is kept"


def test_e5_the_container_environment_moved_verbatim_and_the_adapters_form_no_cycle():
    theirs = statements(show(SOURCE, M7_ISOLATED))
    ours = statements(text_of(cc))
    for name in ("CONTAINER_ENVIRONMENT", "container_environment"):
        assert ast.dump(ours[name]) == ast.dump(theirs[name]), name
    assert ie.CONTAINER_ENVIRONMENT is cc.CONTAINER_ENVIRONMENT and ie.container_environment is cc.container_environment
    graph = {}
    for mod in (cc, ei, ie, pe):
        found = {*import_map(text_of(mod)), *import_map(text_of(mod), lazy=True)}
        graph[mod.__name__] = {m for m in found if m.startswith("codex_harness.evidence.adapters.")}
    assert graph[pe.__name__] == {cc.__name__, ei.__name__} and graph[ie.__name__] == {cc.__name__, ei.__name__, pe.__name__}
    assert graph[cc.__name__] == set()

    def acyclic(node, path=()):
        assert node not in path, path
        for nxt in graph.get(node, ()):
            acyclic(nxt, (*path, node))
    for start in graph:
        acyclic(start)


# ---- AST against M7 for the two modules ------------------------------------------------------------------------------------
class RewriteIsolated(ast.NodeTransformer):
    def __init__(self):
        self.sites, self.cls = [], None

    def visit_ClassDef(self, node):
        self.cls = node.name
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        if node.name == "__init__":
            node.args.kwonlyargs = [ast.arg(arg="containers"), ast.arg(arg="process_tree")]
            node.args.kw_defaults = [ast.Constant(value=None), ast.Constant(value=None)]
            node.body[0].value.keywords.append(ast.keyword(arg="process_tree", value=ast.Name(id="process_tree", ctx=ast.Load())))
            node.body.append(stmt("self.containers = containers"))
            self.sites.append("E-2a")
        if node.name == "snapshot":
            node.body.insert(1, stmt('require(self.containers is not None, "containers is not wired")'))
            self.sites.append("E-2c-require")
        if node.name == "_replay" and self.cls == "DockerEvidenceInspector":
            doc = method(text_of(ie), "DockerEvidenceInspector", "_replay").body[0]
            node.body = [doc, *ast.parse("class _D:\n" + DELEGATE).body[0].body[0].body]
            self.sites.append("E-2b")
        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "summary":
            self.sites.append("E-2c-summary")
            return ast.parse("self.containers.summary()", mode="eval").body
        return node


def test_isolated_evidence_is_m7s_modulo_the_named_rules():
    ours, theirs = statements(text_of(ie)), statements(show(SOURCE, M7_ISOLATED))
    assert list(theirs) == ["CONTAINER_ENVIRONMENT", "container_environment", "DockerEvidenceInspector", "IsolatedProjectEvidenceInspector"]
    assert list(ours) == ["DockerEvidenceInspector", "IsolatedProjectEvidenceInspector"], "E-5 moved the two environment statements out"
    sites = []
    for name in ours:
        rewrite = RewriteIsolated()
        expected = rewrite.visit(copy.deepcopy(theirs[name]))
        sites += rewrite.sites
        assert ast.dump(ours[name]) == ast.dump(ast.fix_missing_locations(expected)), name
    assert sorted(sites) == ["E-2a", "E-2a", "E-2b", "E-2c-require", "E-2c-require", "E-2c-summary", "E-2c-summary"]


class RewriteProject(ast.NodeTransformer):
    def __init__(self):
        self.sites = []

    def visit_ImportFrom(self, node):
        if node.module in ("codex_harness.adapters.isolated_worker", "codex_harness.adapters.isolated_evidence"):
            node.module = "codex_harness.evidence.adapters.container_contract"
            self.sites.append("R-pe0")
        return node

    def visit_FunctionDef(self, node):
        if node.name == "__init__":
            node.args.kwonlyargs = [ast.arg(arg="process_tree")]
            node.args.kw_defaults = [ast.Constant(value=None)]
            node.body[0].value.keywords.append(ast.keyword(arg="process_tree", value=ast.Name(id="process_tree", ctx=ast.Load())))
            self.sites.append("E-4d-init")
        self.generic_visit(node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "_capture":
            node.keywords.append(ast.keyword(arg="process_tree", value=ast.parse("self.process_tree", mode="eval").body))
            self.sites.append("E-4d-capture")
        return node


def test_project_evidence_is_m7s_modulo_the_named_rules():
    ours, theirs = statements(text_of(pe)), statements(show(SOURCE, M7_PROJECT))
    assert list(ours) == list(theirs) and len(theirs) == 19
    sites = []
    for name, node in theirs.items():
        rewrite = RewriteProject()
        expected = rewrite.visit(copy.deepcopy(node))
        sites += rewrite.sites
        assert ast.dump(ours[name]) == ast.dump(ast.fix_missing_locations(expected)), name
    assert sorted(sites) == ["E-4d-capture", "E-4d-init"] + ["R-pe0"] * 6


def test_import_homes_headers_and_the_layer_rules():
    homes = {
        ie: ({"__future__", "pathlib", "codex_harness.evidence.adapters.container_contract", "codex_harness.evidence.adapters.evidence_inspection",
              "codex_harness.evidence.adapters.project_evidence", "codex_harness.kernel.errors", "codex_harness.kernel.ids"}, set()),
        pe: ({"pathlib", "codex_harness.evidence.adapters.evidence_inspection", "codex_harness.evidence.domain.evidence",
              "codex_harness.evidence.domain.project_evidence", "codex_harness.kernel.errors", "codex_harness.kernel.ids"},
             {"codex_harness.evidence.adapters.container_contract"}),
        cc: ({"pathlib"}, set()), er: (None, None)}
    for mod, (top, lazy) in homes.items():
        text = text_of(mod)
        if top is not None:
            assert set(import_map(text)) == top, mod.__name__
            assert set(import_map(text, lazy=True)) == lazy, mod.__name__
        forbidden = ("codex_harness.adapters", "codex_harness.host_os", "codex_harness.coordination", "codex_harness.composition")
        assert not [m for m in {*import_map(text), *import_map(text, lazy=True)} if m.startswith(forbidden)]
        doc = ast.get_docstring(ast.parse(text))
        for field in ("Layer:", "Context:", "Owns:", "Does not own:", "Entry points:", "Contracts:", SOURCE):
            assert field in doc, (mod.__name__, field)
    assert "Layer: adapters\nContext: evidence" in ast.get_docstring(ast.parse(text_of(cc)))
    assert "Layer: adapters\nContext: execution" in ast.get_docstring(ast.parse(text_of(er)))
    for mod, original in ((ie, M7_ISOLATED), (pe, M7_PROJECT)):
        assert ast.get_docstring(ast.parse(text_of(mod))).startswith(ast.get_docstring(ast.parse(show(SOURCE, original))))


def test_no_spawn_site_and_no_bucket_writer_in_the_moved_modules():
    for mod in (ie, pe, cc, er):
        text = text_of(mod)
        for token in ("subprocess", "Popen", "os.system", "ProcessTree", "isolated_worker"):
            assert token not in ast.unparse(ast.parse(text).body[1:]), (mod.__name__, token)
        assert not re.search(r"\.put\(\s*['\"](evidence_inspections|evidence_inspection_notices|completion_verdicts|completion_rejections)", text)
        assert "OWNED_BUCKETS" not in text
