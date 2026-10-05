"""S8 batch B7b (DESIGN-s8 §32 V34b): M7 `adapters/release_verifier.py` moves to `composition.release_verifier`, minus the S7-moved `HostFacts`.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is compared by
the recorded `review.release_verifier` golden (the moved module is target-equal to it); the structural rules R-rv0..R-rv4 are pinned here.
"""

from __future__ import annotations

import ast
import difflib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

from _layout import REPO

from codex_harness.composition import release_verification
from codex_harness.composition import release_verifier as module
from codex_harness.delivery.adapters import deployment
from codex_harness.execution.adapters.containers import cleanup_ledger, owned_container
from codex_harness.execution.domain import container_spec
from codex_harness.host_os.adapters import host_facts, process_groups
from codex_harness.host_os.adapters import verification as verification_module
from codex_harness.intake.application import tickets
from codex_harness.kernel import errors, ids

SOURCE = "e38aa722"
RELEASE_VERIFIER_M7 = "src/codex_harness/adapters/release_verifier.py"
RULE_SITES = {"docker_call": 1, "owned_container_runner": 1, "attempt_resources_naming": 3}


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
        out[names or i] = node
    return out


def imports(src):
    return sorted((n.module, a.name) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) for a in n.names)


def calls(src, name):
    return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]


def segment_lines(src, key):
    return ast.get_source_segment(src, statements(src)[key]).splitlines()


M7_TEXT = git_show(SOURCE, RELEASE_VERIFIER_M7)
OURS = text_of(module)


# ----- the module is M7's modulo the named rules --------------------------------------------------------------------------------------------------
def test_the_module_is_m7s_minus_hostfacts_and_modulo_the_rv_rules():
    ours, theirs = statements(OURS), statements(M7_TEXT)
    assert [k for k in theirs if k not in {("PRESENT", "ABSENT", "UNKNOWN"), ("HostFacts",)}] == list(ours)
    changed = [k for k in ours if ast.dump(ours[k]) != ast.dump(theirs[k])]
    assert changed == [("ReleaseVerifier",)]  # R-rv2, R-rv3 and R-rv4 only


def test_the_only_changed_lines_are_the_rv2_rv3_rv4_sites():
    ours, theirs = segment_lines(OURS, ("ReleaseVerifier",)), segment_lines(M7_TEXT, ("ReleaseVerifier",))
    diff = [line for line in difflib.unified_diff(theirs, ours, lineterm="", n=0) if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    assert [line[0] for line in diff].count("-") == 6 and [line[0] for line in diff].count("+") == 6
    assert sorted(line[1:].strip() for line in diff if line[0] == "-") == sorted([
        '"resources": attempt_resources(attempt["attempt_id"]), "children": [],',
        '"resources": attempt_resources(attempt_id), "children": [], "lifecycle": [],',
        "resources = attempt_resources(record[\"attempt_id\"])",
        'listed = _docker(self.docker, ["ps", "-a", "--no-trunc", *filters, "--format", "{{.ID}}"],',
        'timeout=LIMITS["docker_command_seconds"])',
        'container = OwnedContainer({"limits": LIMITS, "image": None}, self.docker, attempt_id, role)'])


def test_every_rule_site_is_counted_in_m7_and_here():
    assert (len(calls(M7_TEXT, "_docker")), len(calls(M7_TEXT, "OwnedContainer")), len(calls(M7_TEXT, "attempt_resources"))) == (1, 1, 3)
    docker = calls(OURS, "docker_call")
    assert len(docker) == RULE_SITES["docker_call"] and ast.unparse(docker[0].args[0]) == "run_process" and ast.unparse(docker[0].args[1]) == "self.docker"
    assert not calls(OURS, "_docker")
    owned = calls(OURS, "OwnedContainer")
    assert len(owned) == RULE_SITES["owned_container_runner"] and [(k.arg, ast.unparse(k.value)) for k in owned[0].keywords] == [("runner", "run_process")]
    resources = calls(OURS, "attempt_resources")
    assert len(resources) == RULE_SITES["attempt_resources_naming"]
    assert all([(k.arg, ast.unparse(k.value)) for k in c.keywords] == [("naming", "ExecutionContainerNaming()")] and len(c.args) == 1 for c in resources)
    assert len(calls(OURS, "ExecutionContainerNaming")) == 3
    # the verifier's own `runner` is the ReleaseRunner builder around a fence, never a process runner (R-rv2)
    assert "runner=run_process" not in ast.get_source_segment(OURS, statements(OURS)[("ReleaseVerifier",)].body[1])


def test_the_verifier_only_names_run_process_as_an_argument_never_calls_it():
    tree = ast.parse(OURS)
    assert not calls(OURS, "run_process")
    loads = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "run_process" and isinstance(n.ctx, ast.Load)]
    assert len(loads) == 2  # docker_call's runner argument and OwnedContainer's runner keyword


# ----- R-rv0: HostFacts is the host_os class ------------------------------------------------------------------------------------------------------
def test_hostfacts_is_imported_from_host_os_and_not_redefined():
    assert isinstance(statements(M7_TEXT)[("HostFacts",)], ast.ClassDef)  # M7 defined it here; S7 moved it ahead
    assert ("HostFacts",) not in statements(OURS) and not [n for n in ast.walk(ast.parse(OURS)) if isinstance(n, ast.ClassDef) and n.name == "HostFacts"]
    assert module.HostFacts is host_facts.HostFacts
    assert ("codex_harness.host_os.adapters.host_facts", "HostFacts") in imports(OURS)
    for name in ("PRESENT", "ABSENT", "UNKNOWN"):
        assert getattr(module, name) is getattr(host_facts, name)
    assert ("PRESENT", "ABSENT", "UNKNOWN") not in statements(OURS)
    assert (module.PRESENT, module.ABSENT, module.UNKNOWN) == ("present", "absent", "unknown")


def test_the_default_facts_is_the_host_os_class():
    verifier = module.ReleaseVerifier(lambda fence: None, root="/nowhere", artifacts=lambda: None)
    assert type(verifier.facts) is host_facts.HostFacts


# ----- import homes -----------------------------------------------------------------------------------------------------------------------------
def test_the_import_homes():
    assert [p for p in imports(OURS) if p[0].startswith("codex_harness")] == sorted([
        ("codex_harness.composition.release_verification", "ExecutionContainerNaming"),
        ("codex_harness.delivery.adapters.deployment", "ATTEMPT_ID"), ("codex_harness.delivery.adapters.deployment", "RETRY_OBSERVATION"),
        ("codex_harness.delivery.adapters.deployment", "attempt_resources"),
        ("codex_harness.execution.adapters.containers.cleanup_ledger", "_write_record"),
        ("codex_harness.execution.adapters.containers.owned_container", "OwnedContainer"),
        ("codex_harness.execution.adapters.containers.owned_container", "docker_call"),
        ("codex_harness.execution.domain.container_spec", "CONTAINER_ID"), ("codex_harness.execution.domain.container_spec", "LABEL"),
        ("codex_harness.execution.domain.container_spec", "LIMITS"),
        ("codex_harness.host_os.adapters.host_facts", "ABSENT"), ("codex_harness.host_os.adapters.host_facts", "HostFacts"),
        ("codex_harness.host_os.adapters.host_facts", "PRESENT"), ("codex_harness.host_os.adapters.host_facts", "UNKNOWN"),
        ("codex_harness.host_os.adapters.process_groups", "_group_gone"), ("codex_harness.host_os.adapters.process_groups", "observe_spawns"),
        ("codex_harness.host_os.adapters.process_groups", "run_process"),
        ("codex_harness.host_os.adapters.verification", "VerificationServices"),
        ("codex_harness.intake.application.tickets", "TicketSuperseded"),
        ("codex_harness.kernel.errors", "ContractError"), ("codex_harness.kernel.ids", "canonical"), ("codex_harness.kernel.ids", "utcnow")])
    assert "from codex_harness.adapters" not in OURS and "from codex_harness.domain" not in OURS and "from codex_harness.application" not in OURS


def test_the_imported_names_are_the_homes_objects():
    assert module.ATTEMPT_ID is deployment.ATTEMPT_ID and module.RETRY_OBSERVATION == deployment.RETRY_OBSERVATION
    assert module.attempt_resources is deployment.attempt_resources
    assert module.OwnedContainer is owned_container.OwnedContainer and module.docker_call is owned_container.docker_call
    assert module._write_record is cleanup_ledger._write_record
    assert (module.CONTAINER_ID, module.LABEL, module.LIMITS) == (container_spec.CONTAINER_ID, container_spec.LABEL, container_spec.LIMITS)
    assert module.run_process is process_groups.run_process and module.observe_spawns is process_groups.observe_spawns
    assert module._group_gone is process_groups._group_gone
    assert module.VerificationServices is verification_module.VerificationServices
    assert module.TicketSuperseded is tickets.TicketSuperseded
    assert module.ContractError is errors.ContractError and module.canonical is ids.canonical and module.utcnow is ids.utcnow
    assert module.ExecutionContainerNaming is release_verification.ExecutionContainerNaming


def test_the_call_signatures_are_unchanged():
    assert str(inspect.signature(module.ReleaseVerifier.__init__)) == (
        "(self, runner, *, root, artifacts, docker: 'str' = 'docker', facts=None, fence_seconds: 'float' = 30, boundary=None)")
    assert str(inspect.signature(module.bounded_fence)) == "(heartbeat, seconds: 'float' = 30)"
    assert module.FENCE_SECONDS == 30


def test_the_header_names_the_module_its_rules_and_the_follow_up():
    doc = module.__doc__
    assert doc.splitlines()[0] == "The owned-attempt verification port of host delivery (INV-HOST-DELIVERY-VERIFY-001)."
    for line in ("Layer: composition", "Entry points: ReleaseVerifier, CancellationBoundary, bounded_fence, EvaluationCancelled, FenceLost, FenceUnobservable, FENCE_SECONDS",
                 "Contracts: INV-HOST-DELIVERY-VERIFY-001", "SOURCE " + SOURCE, "R-rv0", "R-rv1", "R-rv2", "R-rv3", "R-rv4", "R-rv5", "V34b", "post-cutover", "Owns:", "Does not own:"):
        assert line in doc
    assert sorted(module.__all__) == sorted(["ABSENT", "ATTEMPTS_DIR", "FENCE_SECONDS", "PRESENT", "UNKNOWN", "CancellationBoundary", "EvaluationCancelled", "FenceLost",
                                             "FenceUnobservable", "HostFacts", "ReleaseVerifier", "bounded_fence"])
    assert all(hasattr(module, name) for name in module.__all__)


# ----- the spawn chokepoint ---------------------------------------------------------------------------------------------------------------------
def test_no_process_is_spawned_outside_the_chokepoint():
    tree = ast.parse(OURS)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not used & {"subprocess", "Popen", "system", "execv", "execvp", "spawnv", "create_subprocess_exec", "create_subprocess_shell", "run", "check_output"}
    assert "subprocess" not in {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert module.run_process is process_groups.run_process  # the one chokepoint runner, handed to docker_call and to OwnedContainer


def test_the_listing_and_the_owned_container_use_the_modules_process_runner(tmp_path, monkeypatch):
    seen = []

    def fake(argv, cwd=None, timeout=120, input_text=None, env=None):
        seen.append((list(argv), timeout, env is not None))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_process", fake)
    verifier = module.ReleaseVerifier(lambda fence: None, root=tmp_path, artifacts=lambda: None, docker="/scripted/docker")
    assert verifier._listing(["--filter", "name=x"])["state"] == "absent"
    assert verifier._container_gone("a" * 32, "release-start")["state"] == "confirmed"
    assert [row[0][0] for row in seen] == ["/scripted/docker", "/scripted/docker"]
    assert seen[0][0] == ["/scripted/docker", "ps", "-a", "--no-trunc", "--filter", "name=x", "--format", "{{.ID}}"]
    assert seen[1][0][:2] == ["/scripted/docker", "ps"] and "name=^/zeus-release-start-" + "a" * 32 + "$" in seen[1][0]
    assert all(row[1] == module.LIMITS["docker_command_seconds"] and row[2] for row in seen)


def test_attempt_resources_carry_the_s7_naming_and_equal_the_owned_container_names():
    resources = deployment.attempt_resources("a" * 32, naming=release_verification.ExecutionContainerNaming())
    owned = {role: owned_container.OwnedContainer({"limits": module.LIMITS, "image": None}, "docker", "a" * 32, role, runner=process_groups.run_process).name
             for role in resources["containers"]}
    assert resources["containers"] == owned
    verifier = module.ReleaseVerifier(lambda fence: None, root="/nowhere", artifacts=lambda: None)
    assert verifier._path("b" * 32).parts[-3:] == ("attempts", "b" * 32, "run.json")
