"""S8 batch B7a (DESIGN-s8 §32 V34a): M7 `adapters/verification.py` moves to `host_os.adapters.verification`, and R-v1 keeps `ENVIRONMENT_KEYS` defined
there (`VerificationServices._command` uses it; a host_os adapter may not import composition) with `composition.release_verification` re-importing it.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `host_os.verification_services` golden (the moved module is target-equal to it); the structural rules are pinned here.
"""

from __future__ import annotations

import ast
import difflib
import inspect
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from codex_harness.composition import release_verification
from codex_harness.host_os.adapters import port_diagnosis, process_groups, published_ports
from codex_harness.host_os.adapters import verification as module

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
BASE_HEAD = "fad804900d962dae723c60558dda191d83c3bfe3"
VERIFICATION_M7 = "src/codex_harness/adapters/verification.py"
COMPOSITION = "target/src/codex_harness/composition/release_verification.py"


def git_show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(mod):
    return Path(mod.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        names = (node.name,) if hasattr(node, "name") else tuple(n.id for t in getattr(node, "targets", []) for n in ast.walk(t) if isinstance(n, ast.Name))
        out[names[0] if names else i] = node
    return out


def import_modules(src):
    return sorted({n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in (n.names if isinstance(n, ast.Import) else [None])})


def segment_lines(src, name):
    return ast.get_source_segment(src, statements(src)[name]).splitlines()


# ----- the module is M7's modulo the named rules ------------------------------------------------------------------------------------------------
def test_verification_is_m7s_modulo_r_v0_and_r_v1():
    ours, theirs = statements(text_of(module)), statements(git_show(SOURCE, VERIFICATION_M7))
    assert [k for k in theirs if k != "verification_environment"] == list(ours)
    changed = {k for k in ours if ast.dump(ours[k]) != ast.dump(theirs[k])}
    assert changed == {"VerificationServices"}  # only the lazy `port_diagnosis` import inside `_diagnose` (R-v0b)


def test_the_only_changed_line_is_the_lazy_port_diagnosis_import():
    ours, theirs = segment_lines(text_of(module), "VerificationServices"), segment_lines(git_show(SOURCE, VERIFICATION_M7), "VerificationServices")
    diff = [line for line in difflib.unified_diff(theirs, ours, lineterm="", n=0) if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    assert diff == ["-            return {\"database_url\": f'postgresql://zeus:{self.password}@127.0.0.1:{ports[\"postgres\"]}/zeus',",
                    "+            return {\"database_url\": f'postgresql://zeus:{self.password}' f'@127.0.0.1:{ports[\"postgres\"]}/zeus',",
                    "-            dsn = f\"postgresql://zeus:{self.password}@127.0.0.1:{port}/zeus\"",
                    "+            dsn = f\"postgresql://zeus:{self.password}\" f\"@127.0.0.1:{port}/zeus\"",
                    "-        from codex_harness.adapters import port_diagnosis", "+        from codex_harness.host_os.adapters import port_diagnosis"]


def test_r_v2_the_two_dsn_literals_are_split_at_the_at_sign_and_the_code_is_m7s():
    # adjacent f-string literals are joined at parse time: the AST (and so the code) equals M7's, and the check-tree userinfo scan finds nothing
    source = text_of(module)
    assert source.count("f'postgresql://zeus:{self.password}' f'@127.0.0.1:{ports[\"postgres\"]}/zeus'") == 1
    assert source.count("f\"postgresql://zeus:{self.password}\" f\"@127.0.0.1:{port}/zeus\"") == 1
    assert not re.search(r"[a-z]+://[^\s/@:\"']+:[^\s/@\"']+@", source)
    theirs = git_show(SOURCE, VERIFICATION_M7)
    assert len(re.findall(r"[a-z]+://[^\s/@:\"']+:[^\s/@\"']+@", theirs)) == 2
    assert ast.dump(statements(source)["VerificationServices"]) == ast.dump(statements(theirs.replace("from codex_harness.adapters import port_diagnosis", "from codex_harness.host_os.adapters import port_diagnosis"))["VerificationServices"])


def test_verification_environment_is_not_redefined_here():
    assert "verification_environment" in statements(git_show(SOURCE, VERIFICATION_M7))
    assert "verification_environment" not in statements(text_of(module)) and not hasattr(module, "verification_environment")
    assert "verification_environment" in statements(Path(release_verification.__file__).read_text())
    assert not hasattr(module, "python_channel_environment")  # its only caller stayed in composition


def test_the_call_signatures_are_unchanged():
    assert str(inspect.signature(module.VerificationServices.__init__)) == "(self, root, artifacts, project=None)"
    assert str(inspect.signature(module.VerificationServices.collect_stale)) == "(root, artifacts, max_age=7200)"


def test_the_header_names_the_module_and_its_entry_points():
    doc = module.__doc__
    assert doc.splitlines()[0] == "Disposable PostgreSQL/Redis for incumbent and candidate release tests."
    for line in ("Layer: adapters", "Context: host_os", "Entry points: VerificationServices, ATTEMPTS, ENVIRONMENT_KEYS", "Contracts: INV-HOST-DELIVERY-VERIFY-001, INV-VERIFICATION-001",
                 "SOURCE " + SOURCE, "R-v0a", "R-v0b", "R-v0c", "R-v1", "R-v2"):
        assert line in doc
    for name in ("Owns:", "Does not own:"):
        assert name in doc
    for name in ("VerificationServices", "ATTEMPTS", "ENVIRONMENT_KEYS"):
        assert hasattr(module, name)


# ----- R-v1: one definition, in host_os, re-imported by composition -----------------------------------------------------------------------------
def test_environment_keys_is_defined_once_in_host_os_and_is_m7s():
    definitions = [n for n in ast.parse(text_of(module)).body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ENVIRONMENT_KEYS" for t in n.targets)]
    assert len(definitions) == 1
    theirs = statements(git_show(SOURCE, VERIFICATION_M7))["ENVIRONMENT_KEYS"]
    assert ast.dump(definitions[0]) == ast.dump(theirs)
    assert module.ENVIRONMENT_KEYS == set(ast.literal_eval(theirs.value))


def test_composition_reimports_environment_keys_and_does_not_define_it():
    assert release_verification.ENVIRONMENT_KEYS is module.ENVIRONMENT_KEYS
    tree = ast.parse(Path(release_verification.__file__).read_text())
    assert not [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ENVIRONMENT_KEYS" for t in n.targets)]
    imports = [(n.module, a.name) for n in tree.body if isinstance(n, ast.ImportFrom) for a in n.names if a.name == "ENVIRONMENT_KEYS"]
    assert imports == [("codex_harness.host_os.adapters.verification", "ENVIRONMENT_KEYS")]
    owns = [line for line in release_verification.__doc__.splitlines() if line.startswith("Owns:")][0]
    assert "`ENVIRONMENT_KEYS` (re-imported from `host_os.adapters.verification` (S8 B7a R-v1))" in owns
    assert "Entry points: ENVIRONMENT_KEYS, verification_environment, ExecutionContainerNaming, release_runner" in release_verification.__doc__


def test_composition_is_otherwise_the_base_heads_file():
    ours, base = statements(Path(release_verification.__file__).read_text()), statements(git_show(BASE_HEAD, COMPOSITION))
    assert [k for k in base if k != "ENVIRONMENT_KEYS"] == list(ours)
    assert all(ast.dump(ours[k]) == ast.dump(base[k]) for k in ours)
    assert set(import_modules(Path(release_verification.__file__).read_text())) - set(import_modules(git_show(BASE_HEAD, COMPOSITION))) == {
        "codex_harness.host_os.adapters.verification"}
    assert verification_environment_uses_the_shared_keys()


def verification_environment_uses_the_shared_keys():
    env = release_verification.verification_environment({"database_url": "d", "redis_url": "r"},
                                                        {"PATH": "p", "GH_TOKEN": "secret", "ZEUS_X": "y", "http_proxy": "proxy"})
    return env["PATH"] == "p" and env["http_proxy"] == "proxy" and "GH_TOKEN" not in env and "ZEUS_X" not in env


# ----- import homes and the spawn chokepoint ----------------------------------------------------------------------------------------------------
def test_the_import_homes_are_host_os_and_kernel_only():
    assert import_modules(text_of(module)) == sorted([
        "codex_harness.host_os.adapters", "codex_harness.host_os.adapters.process_groups", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
        "datetime", "json", "os", "pathlib", "re", "secrets", "socket", "threading", "time", "uuid", "psycopg", "redis"])
    assert module.published_ports is published_ports and module.run_process is process_groups.run_process
    for name in ("composition", "delivery", "execution", "intake", "coordination", "research", "review", "storage"):
        assert "codex_harness." + name not in text_of(module)


def test_the_lazy_port_diagnosis_is_the_host_os_adapter():
    nested = [n for n in ast.walk(ast.parse(text_of(module))) if isinstance(n, ast.ImportFrom) and any(a.name == "port_diagnosis" for a in n.names)]
    assert [(n.module, n.col_offset > 0) for n in nested] == [("codex_harness.host_os.adapters", True)]
    assert port_diagnosis.observe


def test_spawns_only_through_the_process_groups_run_process():
    source = text_of(module)
    tree = ast.parse(source)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not used & {"subprocess", "Popen", "system", "execv", "execvp", "spawnv", "create_subprocess_exec", "create_subprocess_shell"}
    calls = []
    for owner in ast.walk(tree):
        if isinstance(owner, ast.FunctionDef):
            calls += [owner.name for n in ast.walk(owner) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run_process"]
    assert calls == ["_command"]


def test_command_runs_the_modules_run_process_with_the_shared_allow_list(tmp_path, monkeypatch):
    seen = {}

    def fake(argv, cwd=None, env=None, timeout=None):
        seen.update(argv=argv, cwd=cwd, env=env, timeout=timeout)
        return SimpleNamespace(returncode=0, stdout=" ok \n")

    monkeypatch.setattr(module, "run_process", fake)
    for key, value in (("PATH", "/bin"), ("http_proxy", "proxy"), ("DOCKER_HOST", "unix:///x"), ("GH_TOKEN", "secret"), ("ZEUS_DATABASE_URL", "production")):
        monkeypatch.setenv(key, value)
    services = module.VerificationServices(tmp_path, SimpleNamespace(), "zeus-verify-" + "a" * 32)
    assert services._command("ps", "-q", "redis", timeout=0.2) == "ok"
    assert seen["argv"][:5] == ["docker", "compose", "--project-name", services.project, "--file"] and seen["argv"][6:] == ["ps", "-q", "redis"]
    assert seen["timeout"] == 1 and seen["cwd"] == str(services.directory)
    assert {"PATH", "http_proxy", "DOCKER_HOST", "ZEUS_VERIFY_PASSWORD"} <= set(seen["env"]) and not {"GH_TOKEN", "ZEUS_DATABASE_URL"} & set(seen["env"])
    assert seen["env"]["ZEUS_VERIFY_PASSWORD"] == services.password
