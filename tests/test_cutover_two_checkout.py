"""Cutover G2-W1: the suite passes the incumbent controller's two-checkout evaluation without weakening R-O.

The controller runs the INCUMBENT tests (checkout A) against the CANDIDATE package (checkout B, editable-installed,
the pytest cwd) with `-c A/pyproject.toml --import-mode=importlib` and `PYTHONPATH=A/tests`. Sources of the expected
results: the g2 critique #4 (ported helper imports under importlib) and #5 (a trusted audit root that does not come
from the import system), and the R-O contract (REBUILD-DESIGN-v2 §5.2): the audit refuses every other origin.

Behavioural: the anchor table drives `audit_root` with injected inputs; the miniature runs a real pytest subprocess
over a small copy of A against the checkout that holds the package under test as B, and each negative control applies the mutation its name states.
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import provider_guard
import pytest
from _audit_root import PACKAGE_SRC, audit_root
from _layout import TARGET

DEFAULT = Path("/x/tests-tree/src")
CWD = Path("/x/canary-7")
PYPROJECT = '[project]\nname = "zeus-harness"\n'


def editable(url: str) -> dict:
    return {"url": url, "dir_info": {"editable": True}}


@pytest.mark.parametrize(
    ("direct_url", "pyproject", "expected"),
    [
        (editable("file:///x/canary-7/src"), PYPROJECT, CWD / "src"),
        (editable("file:///x/canary-7"), PYPROJECT, CWD / "src"),
        (editable("file:///x/canary-7/reference/m7/src"), PYPROJECT, DEFAULT),
        ({"url": "file:///x/canary-7/src", "dir_info": {}}, PYPROJECT, DEFAULT),
        ({"url": "file:///x/canary-7.whl", "archive_info": {"hash": "sha256=0"}}, PYPROJECT, DEFAULT),
        (editable("file:///x/canary-8/src"), PYPROJECT, DEFAULT),
        (editable("file:///x/canary-7/src"), '[project]\nname = "another"\n', DEFAULT),
        (editable("file:///x/canary-7/src"), None, DEFAULT),
        (editable("https://example.invalid/x/canary-7/src"), PYPROJECT, DEFAULT),
        (None, PYPROJECT, DEFAULT),
    ],
    ids=["editable-src", "editable-project-dir", "reference-tree", "not-editable", "wheel", "third-directory",
         "other-project", "no-pyproject", "non-file-url", "missing-direct-url"],
)
def test_audit_root_anchor_table(direct_url, pyproject, expected):
    assert audit_root(direct_url, CWD, pyproject, DEFAULT) == expected


def test_audit_root_refuses_a_checkout_under_a_reference_path():
    cwd = Path("/x/reference/m7")
    assert audit_root(editable("file:///x/reference/m7/src"), cwd, PYPROJECT, DEFAULT) == DEFAULT


# --- the miniature two-checkout run -------------------------------------------------------------------------------

REAL_TEST = "test_s7_relocations.py"
PORTED_TEST = "test_pipeline.py"  # imports `ported_support`, a sibling helper
PORTED_LINE = "sys.path.insert(0, str(TESTS / \"ported\"))\n"


def copy_checkout_a(root: Path) -> Path:
    """A = the tests' tree reduced to what the session imports: both conftests, `_layout`, `_audit_root`, the helpers,
    two test files, the guard and harness modules and the root pyproject. A has no `src`: the package under test is B's
    (`PACKAGE_SRC`), which the ported conftest attests by copying the imported `codex_harness`."""
    a = root / "evaluator-1"
    (a / "tests" / "ported").mkdir(parents=True)
    for name in ("conftest.py", "_layout.py", "_audit_root.py", REAL_TEST):
        shutil.copy2(TARGET / "tests" / name, a / "tests" / name)
    for name in ("conftest.py", "ported_support.py", PORTED_TEST):
        shutil.copy2(TARGET / "tests" / "ported" / name, a / "tests" / "ported" / name)
    for part in ("guard", "harness"):
        shutil.copytree(TARGET / "compare" / part, a / "compare" / part, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(TARGET / "pyproject.toml", a / "pyproject.toml")
    return a


def run_incumbent(a: Path, root: Path, *, extra_pythonpath: Path | None = None):
    """The controller's incumbent run: cwd = B (the checkout holding the package under test), PYTHONPATH = A/tests, importlib mode."""
    pythonpath = str(a / "tests")
    if extra_pythonpath is not None:
        pythonpath = str(extra_pythonpath) + ":" + pythonpath
    env = provider_guard.child_environment(root / "child", extra={"PYTHONPATH": pythonpath})
    argv = [sys.executable, "-m", "pytest", str(a / "tests" / REAL_TEST), str(a / "tests" / "ported" / PORTED_TEST),
            "-c", str(a / "pyproject.toml"), "--import-mode=importlib", "-q", "-p", "no:cacheprovider",
            f"--basetemp={root / 'bt'}"]
    return subprocess.run(argv, cwd=PACKAGE_SRC.parent, env=env, capture_output=True, text=True, timeout=540)


def tail(result) -> str:
    return (result.stdout + result.stderr)[-3000:]


@pytest.fixture
def checkout_a(tmp_path):
    return copy_checkout_a(tmp_path)


def test_two_checkout_run_passes(checkout_a, tmp_path):
    result = run_incumbent(checkout_a, tmp_path)
    assert result.returncode == 0, tail(result)
    assert re.search(r"\b\d+ passed\b", result.stdout), tail(result)


def test_control_shadowing_path_entry_resolves_codex_harness_outside_b_src_and_fails_with_r_o(checkout_a, tmp_path):
    """Mutation: a rogue `codex_harness` package earlier on the path, outside B's `src`."""
    rogue = tmp_path / "rogue"
    (rogue / "codex_harness").mkdir(parents=True)
    (rogue / "codex_harness" / "__init__.py").write_text("")
    result = run_incumbent(checkout_a, tmp_path, extra_pythonpath=rogue)
    assert result.returncode != 0, tail(result)
    assert "R-O" in result.stdout + result.stderr, tail(result)


def test_control_without_the_ported_path_line_fails_collection_on_ported_support(checkout_a, tmp_path):
    """Mutation: A's `tests/conftest.py` with the `sys.path.insert(0, ... "ported")` line removed."""
    conftest = checkout_a / "tests" / "conftest.py"
    text = conftest.read_text(encoding="utf-8")
    assert PORTED_LINE in text
    conftest.write_text(text.replace(PORTED_LINE, ""), encoding="utf-8")
    result = run_incumbent(checkout_a, tmp_path)
    assert result.returncode != 0, tail(result)
    assert "No module named 'ported_support'" in result.stdout + result.stderr, tail(result)


# --- the evaluator layout, reproduced by a child session ------------------------------------------------------------

GIT_FIXED = {"GIT_AUTHOR_NAME": "Zeus Fixture", "GIT_AUTHOR_EMAIL": "fixture@zeus.invalid",
             "GIT_AUTHOR_DATE": "2026-09-22T00:00:00+00:00", "GIT_COMMITTER_NAME": "Zeus Fixture",
             "GIT_COMMITTER_EMAIL": "fixture@zeus.invalid", "GIT_COMMITTER_DATE": "2026-09-22T00:00:00+00:00"}
BINDER = "codex_harness.host_os.adapters.git_workspace"
EVALUATOR_PATH = "/usr/local/bin:/usr/bin:/bin"


def child_session(root: Path, nodes: list[str], *, tree: Path = TARGET, extra: dict | None = None):
    """A child pytest over `tree`'s own tests as the release evaluator runs them: `tree` is the incumbent (its `-c` and
    `PYTHONPATH`), the cwd is the checkout that holds the package under test (`PACKAGE_SRC.parent`), importlib mode."""
    env = provider_guard.child_environment(root / "child", extra={"PYTHONPATH": str(tree / "tests"), **(extra or {})})
    argv = [sys.executable, "-m", "pytest", *[str(tree / node) for node in nodes], "-c", str(tree / "pyproject.toml"),
            "--import-mode=importlib", "-q", "-rA", "-p", "no:cacheprovider", f"--basetemp={root / 'bt'}"]
    return subprocess.run(argv, cwd=PACKAGE_SRC.parent, env=env, capture_output=True, text=True, timeout=540)


def test_a_ticket_recorder_does_not_rebind_git_workspace(tmp_path):
    """Family J: a fresh interpreter runs the test that patches `process_groups.run_process` and then the one that
    reaches `git_workspace` through the real evidence gate."""
    nodes = ["tests/test_s10_c2c_ticket_sdd_roots.py::test_ticket_sync_reaches_github_through_the_injected_run_process_r_c10",
             "tests/test_s10_c5b1_executor.py::test_an_implementation_runs_end_to_end_through_the_real_evidence_gate"]
    result = child_session(tmp_path, nodes)
    assert result.returncode == 0, tail(result)
    assert all(any(line.startswith("PASSED ") and line.endswith(node) for line in result.stdout.splitlines()) for node in nodes), tail(result)


def test_integration_dsn_precedence(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("w1a_ported_test_integration", TARGET / "tests" / "ported" / "test_integration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ZEUS_TEST_DSN", "postgresql://u@h:5432/zeus_test")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql://u@h:5433/harness")
    assert module.database_url() == "postgresql://u@h:5432/zeus_test"
    monkeypatch.delenv("ZEUS_TEST_DSN")
    assert module.database_url() == "postgresql://u@h:5433/harness"
    monkeypatch.delenv("HARNESS_DATABASE_URL")
    with pytest.raises(RuntimeError) as caught:
        module.database_url()
    assert "ZEUS_TEST_DSN" in str(caught.value) and "HARNESS_DATABASE_URL" in str(caught.value)
    result = child_session(tmp_path, ["tests/test_cutover_two_checkout.py::test_audit_root_refuses_a_checkout_under_a_reference_path"],
                           extra={"HARNESS_DATABASE_URL": "postgresql://u@127.0.0.1:55432/x"})
    output = result.stdout + result.stderr
    assert result.returncode == 4, tail(result)
    assert "R-X" in output and "R-O" not in output, tail(result)


# --- the static guard of family J -------------------------------------------------------------------------------------


def patches_run_process(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr" and node.args):
            continue
        target = node.args[0]
        name = ast.unparse(target)
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            if target.value.endswith("process_groups.run_process"):
                return True
        elif (len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "run_process"
              and name.split(".")[-1] == "process_groups"):
            return True
    return False


def imports_binder(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == BINDER for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == BINDER.rpartition(".")[0] and any(
                alias.name == "git_workspace" for alias in node.names):
            return True
    return False


def unguarded(text: str) -> bool:
    tree = ast.parse(text)
    return patches_run_process(tree) and not imports_binder(tree)


def test_a_module_that_patches_run_process_imports_the_by_name_binders_at_module_top():
    """Cutover W1a family J: `git_workspace` binds `process_groups.run_process` by name at its first import, so a module
    that patches it must import the binder first, however the batches are split."""
    offenders = [str(path.relative_to(TARGET)) for path in sorted((TARGET / "tests").rglob("*.py"))
                 if unguarded(path.read_text(encoding="utf-8-sig"))]
    assert offenders == []


@pytest.mark.parametrize(("text", "expected"), [
    ("from codex_harness.host_os.adapters import process_groups\n\ndef t(monkeypatch):\n"
     "    monkeypatch.setattr(process_groups, 'run_process', None)\n", True),
    ("import codex_harness.host_os.adapters.git_workspace\nfrom codex_harness.host_os.adapters import process_groups\n\n"
     "def t(monkeypatch):\n    monkeypatch.setattr(process_groups, 'run_process', None)\n", False),
    ("from codex_harness.host_os.adapters import git_workspace, process_groups\n\ndef t(monkeypatch):\n"
     "    monkeypatch.setattr(process_groups, 'run_process', None)\n", False),
    ("def t(monkeypatch):\n    import codex_harness.host_os.adapters.git_workspace\n"
     "    monkeypatch.setattr('codex_harness.host_os.adapters.process_groups.run_process', None)\n", True),
    ("def t(monkeypatch):\n    monkeypatch.setattr(other, 'run_process', None)\n", False),
], ids=["unguarded", "import-at-top", "from-import-at-top", "import-inside-the-function", "another-target"])
def test_the_static_guard_tells_a_guarded_module_from_an_unguarded_one(text, expected):
    assert unguarded(text) is expected


# --- the evaluator layout with a worker-profile delta (G2-R1: the candidate's package differs from the incumbent's) ------

R1_NODES = [
    "tests/ported/test_host_delivery.py::test_normal_path_publishes_observes_ci_merges_switches_and_proves_consumption",
    "tests/ported/test_host_delivery_first_activation.py::test_the_committed_profile_digest_equals_the_incumbent_packaged_digest",
    "tests/test_s11_ar4_node_map.py::test_map_is_complete_over_the_m7_nodes",
    "tests/test_s11_ar4_rebaseline_map.py::test_map_is_complete_and_every_target_is_collected",
    "tests/test_s11_ar4_rebaseline_map.py::test_rebaseline_check_is_byte_equal",
    "tests/test_compare_harness.py::test_loaded_target_modules_come_from_the_target_tree",
    "tests/test_s8_batch_b3_move.py::test_r_ae5_research_proposal_runs_is_a_research_bucket_with_a_single_writer",
    "tests/test_s8_batch_b4_move.py::test_sdd_is_m7s_modulo_r_sdd1_and_r_sdd2",
]
R1_TREES = ("tests", "src", "compare", "coverage", "scripts", "deploy", "harness_hooks", "frontend", "examples", ".github", "skills")
R1_FILES = ("pyproject.toml", "uv.lock", "compose.yaml", "Dockerfile", "Dockerfile.worker", "AGENTS.md", "README.md")
R1_LINKED = ("docs", "reference")  # large read-only trees, linked rather than copied


def build_delta_checkout(root: Path) -> Path:
    """A = the tests' tree, its `src` and the trees the suite collects over (the large read-only ones linked), with one line appended to the worker profile
    and the manifest digest recomputed by the profile's own metadata command; committed under pinned git settings."""
    a = root / "evaluator-r1"
    for tree in R1_TREES:
        shutil.copytree(TARGET / tree, a / tree, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    for name in R1_FILES:
        shutil.copy2(TARGET / name, a / name)
    for name in R1_LINKED:
        (a / name).symlink_to(TARGET / name)
    resources = a / "src" / "codex_harness" / "resources"
    with (resources / "worker-profile-v1.md").open("a", encoding="utf-8") as handle:
        handle.write("\nA worker-profile delta carried by the candidate delivery.\n")
    observed = subprocess.run([sys.executable, "-m", "codex_harness.adapters.worker_profile_metadata"], cwd=a, capture_output=True,
                              text=True, env={**os.environ, "PYTHONPATH": str(a / "src")}, timeout=120)
    digest = json.loads(observed.stdout)["document_sha256"]
    manifest = resources / "worker-profile-v1.json"
    manifest.write_text(re.sub(r'("document_sha256": ")[0-9a-f]{64}', lambda m: m.group(1) + digest,
                               manifest.read_text(encoding="utf-8"), count=1), encoding="utf-8")
    empty = root / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    environment = {**os.environ, **GIT_FIXED, "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_SYSTEM": str(empty)}
    objects = subprocess.run(["git", "-C", str(PACKAGE_SRC.parent), "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                             capture_output=True, text=True, timeout=120, check=True).stdout.strip()
    for args in (("init", "-q", "-b", "main"), None, ("add", "--all"), ("commit", "-q", "--no-verify", "-m", "evaluator checkout A")):
        if args is None:  # the suite reads SOURCE commits at import, so A borrows the objects of the checkout that has them
            (a / ".git" / "objects" / "info").mkdir(parents=True, exist_ok=True)
            (a / ".git" / "objects" / "info" / "alternates").write_text(objects + "\n", encoding="utf-8")
            continue
        done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=a, env=environment, capture_output=True,
                              text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-500:]
    return a


def tripwire_environment(root: Path) -> tuple[dict, Path]:
    """The evaluator's PATH with a `uv` ahead of it that records the call and fails: the evaluator runs without uv."""
    fake = root / "tripwire"
    fake.mkdir()
    marker = root / "uv-was-called"
    (fake / "uv").write_text(f"#!/bin/sh\necho called > {marker}\nexit 127\n", encoding="utf-8")
    (fake / "uv").chmod(0o755)
    return {"PATH": f"{fake}:{EVALUATOR_PATH}"}, marker


def free_resources() -> tuple[int, int]:
    state = os.statvfs("/tmp")
    return state.f_bavail * state.f_frsize, state.f_favail


@pytest.fixture
def delta_checkout(tmp_path):
    return build_delta_checkout(tmp_path)


def test_evaluator_layout_with_a_worker_profile_delta_passes(delta_checkout, tmp_path):
    before = free_resources()
    extra, marker = tripwire_environment(tmp_path)
    result = child_session(tmp_path, R1_NODES, tree=delta_checkout, extra=extra)
    after = free_resources()
    message = f"{tail(result)}\n/tmp bytes delta {before[0] - after[0]}, inode delta {before[1] - after[1]}"
    assert result.returncode == 0, message
    passed = [line.removeprefix("PASSED ") for line in result.stdout.splitlines() if line.startswith("PASSED ")]
    missing = [node for node in R1_NODES if not any(line.endswith(f"{delta_checkout.name}/{node}") for line in passed)]
    assert missing == [], message
    assert not marker.exists(), message


def test_control_the_ported_conftest_attesting_its_own_src_fails_with_a_profile_digest_mismatch(delta_checkout, tmp_path):
    """Mutation: A's ported conftest copies A's own `src/codex_harness` (the pre-fix behaviour) instead of the package under test."""
    conftest = delta_checkout / "tests" / "ported" / "conftest.py"
    text = conftest.read_text(encoding="utf-8")
    old = "    assert PACKAGE.parent == PACKAGE_SRC, (PACKAGE, PACKAGE_SRC)\n    shutil.copytree(PACKAGE, root"
    assert old in text
    new = '    shutil.copytree(Path(__file__).resolve().parents[2] / "src" / "codex_harness", root'
    conftest.write_text("from pathlib import Path\n" + text.replace(old, new), encoding="utf-8")
    result = child_session(tmp_path, R1_NODES[:1], tree=delta_checkout)
    assert result.returncode != 0, tail(result)
    assert "host delivery halted" in result.stdout + result.stderr and "no_known_good_predecessor" in result.stdout + result.stderr, tail(result)


def test_control_a_node_map_collecting_through_uv_calls_the_tripwire(delta_checkout, tmp_path):
    """Mutation: A's `coverage/test_node_map.py` collects through `uv run` again (the evaluator has no uv)."""
    path = delta_checkout / "coverage" / "test_node_map.py"
    text = path.read_text(encoding="utf-8")
    old = '[sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",\n                           str(tree / "tests"), "-c", str(tree / "pyproject.toml")]'
    assert old in text
    path.write_text(text.replace(old, '["uv", "run", "--frozen", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"]')
                    .replace("cwd=Path.cwd() if cwd is None else cwd", "cwd=tree"), encoding="utf-8")
    extra, marker = tripwire_environment(tmp_path)
    result = child_session(tmp_path, R1_NODES[2:3], tree=delta_checkout, extra=extra)
    assert result.returncode != 0, tail(result)
    assert marker.exists(), tail(result)
