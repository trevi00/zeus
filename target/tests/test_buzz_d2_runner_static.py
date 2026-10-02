"""Buzz D2: static guards on the owner-run isolated end-to-end runner and its compose file (no Docker, no network, no Node).

The runner (`fixtures/buzz_e2e/run_e2e.py`) is a standalone script the OWNER runs; this module only parses it (AST), reads
its compose/organization files and runs `--help`. Contracts: DESIGN-D §4, §6 rows 5-6; INV-EXECUTION-IDENTITY-001.
"""

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from codex_harness.composition.buzz_bridge import custody_name
from codex_harness.routing.domain.organization import Agent, Organization

FIXTURES = Path(__file__).resolve().parent / "fixtures"
E2E = FIXTURES / "buzz_e2e"
RUNNER, COMPOSE, ORG = E2E / "run_e2e.py", E2E / "compose.yaml", E2E / "organization.json"
A4_COMPOSE = FIXTURES / "buzz_conntest" / "compose.yaml"
A4_RUNNER = FIXTURES / "buzz_conntest" / "run_matrix.py"
RUN_MATRIX_SHA256 = "4627cb4d877baba8c0a11e1a36a18afa9501d404099142bc3bf1c9de73c845a5"  # run_matrix.py at 36874f4
PGVECTOR = "pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f"
FORBIDDEN_KEYS = ("privileged", "network_mode", "cap_add", "pid", "ipc", "devices", "security_opt")
SECRET_PARTS = ("dsn", "password", "secret", "private", "hex")
PATH_SUFFIXES = ("_file", "_path", "_dir")

TREE = ast.parse(RUNNER.read_text(encoding="utf-8"))


def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def functions():
    return {node.name: node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)}


def module_constant(name):
    for node in TREE.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no module constant {name}")


# -- the compose file -------------------------------------------------------------------------------------------------

def test_every_image_is_pinned_by_digest_and_the_a4_stack_digests_are_kept():
    services = compose()["services"]
    images = {name: service["image"] for name, service in services.items()}
    assert set(images) == {"relay", "postgres", "redis", "zeus-postgres"}
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in images.values()), images
    a4 = {name: service["image"] for name, service in yaml.safe_load(A4_COMPOSE.read_text("utf-8"))["services"].items()}
    assert {name: images[name] for name in a4} == a4, "the relay stack must keep the A4 digests"
    assert images["zeus-postgres"] == PGVECTOR
    assert yaml.safe_load(COMPOSE.read_text("utf-8"))["name"] == "zeus-buzz-e2e"


def test_ports_are_loopback_only_and_only_the_relay_and_zeus_postgres_publish():
    services = compose()["services"]
    published = {name: service["ports"] for name, service in services.items() if "ports" in service}
    assert set(published) == {"relay", "zeus-postgres"}
    for name, ports in published.items():
        assert all(port["host_ip"] == "127.0.0.1" and isinstance(port["published"], str) for port in ports), name
    code = "\n".join(line for line in COMPOSE.read_text("utf-8").splitlines() if not line.lstrip().startswith("#"))
    assert "0.0.0.0:" not in code.replace("BUZZ_BIND_ADDR: 0.0.0.0:3000", "")


def test_zeus_postgres_is_on_its_own_network_with_a_healthcheck():
    document = compose()
    services, networks = document["services"], document["networks"]
    assert services["zeus-postgres"]["networks"] == ["zeus-db"]
    assert "healthcheck" in services["zeus-postgres"]
    assert networks["zeus-db"].get("driver") == "bridge" and not networks["zeus-db"].get("internal")
    for name in ("relay", "postgres", "redis"):
        assert "zeus-db" not in services[name]["networks"], f"{name} shares the zeus-db network"
    assert not set(services["zeus-postgres"]["networks"]) & set(services["relay"]["networks"])


def test_no_privileged_host_network_socket_or_cap_add():
    document = compose()
    for name, service in document["services"].items():
        assert not set(FORBIDDEN_KEYS) & set(service), (name, set(FORBIDDEN_KEYS) & set(service))
        assert not any("docker.sock" in str(volume) for volume in service.get("volumes", [])), name
    code = "\n".join(line for line in COMPOSE.read_text("utf-8").splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("privileged", "network_mode", "cap_add", "docker.sock", "pid: host"):
        assert forbidden not in code, forbidden


def test_the_organization_is_one_conductor_two_leads_three_workers_in_two_teams_with_injective_custody_names():
    agents = json.loads(ORG.read_text("utf-8"))["agents"]
    organization = Organization({a["id"]: Agent(**a) for a in agents})
    organization.validate()
    roles = [a["role"] for a in agents]
    assert (roles.count("conductor"), roles.count("lead"), roles.count("worker")) == (1, 2, 3)
    assert len({a["team"] for a in agents if a["role"] == "lead"}) == 2
    assert any(":" in a["id"] for a in agents), "the packaged-style ids with ':' exercise custody_name"
    names = [custody_name(a["id"]) for a in agents]
    assert len(set(names)) == len(names)


# -- the runner -------------------------------------------------------------------------------------------------------

def test_the_work_dir_is_under_scratch_and_never_tmp():
    text = RUNNER.read_text("utf-8")
    assert re.search(r'SCRATCH = Path\("/home/trevi/workspaces/zeus/scratch/buzz-e2e"\)', text)
    literals = [n.value for n in ast.walk(TREE) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value is not ast.get_docstring(TREE, clean=False)]
    assert [v for v in literals if "/tmp" in v and len(v) > 5] == [], "a code literal names /tmp"
    assert "tempfile" not in text and "mkdtemp" not in text


def is_subprocess_attr(node, attrs=None):
    func = node.func
    return (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "subprocess"
            and (attrs is None or func.attr in attrs))


def test_every_subprocess_is_started_in_its_own_group_and_killed_in_finally():
    calls = [node for node in ast.walk(TREE) if isinstance(node, ast.Call)]
    popens = [node for node in calls if is_subprocess_attr(node, {"Popen"})]
    assert len(popens) == 2, "the only starters are Procs.spawn and Procs.run"
    for node in popens:
        flags = {kw.arg: kw.value for kw in node.keywords}
        assert isinstance(flags.get("start_new_session"), ast.Constant) and flags["start_new_session"].value is True
    other = [node.func.attr for node in calls if is_subprocess_attr(node) and node.func.attr not in ("Popen", "CompletedProcess")]
    assert not other, f"a subprocess started outside Procs: {other}"
    for node in calls:  # no shell escape hatches either
        func = node.func
        assert not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "os"
                    and (func.attr in ("system", "popen") or func.attr.startswith(("spawn", "exec")))), func.attr
    run_all = functions()["run_all"]
    tries = [node for node in ast.walk(run_all) if isinstance(node, ast.Try) and node.finalbody]
    assert len(tries) == 1
    first = tries[0].finalbody[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call) and first.value.func.attr == "kill_all", \
        "the first statement of the finally must kill every child process group"
    kill_all = ast.dump(functions()["kill_all"])
    assert "kill_group" in kill_all and "SIGTERM" in kill_all and "SIGKILL" in kill_all
    assert "killpg" in ast.dump(functions()["kill_group"])
    assert "kill_all" in ast.dump(functions()["step_cleanup"]) and "residue" in ast.dump(functions()["step_cleanup"])
    assert "rmtree" in ast.dump(functions()["remove_secrets"]) and "unlink" in ast.dump(functions()["remove_secrets"])


def call_form(node):
    """The docker argv form of a `.compose(...)` / `.docker([...])` call, with `<...>` placeholders, or None."""
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in ("compose", "docker"):
        return None
    labels = {"LABEL": "<label>", "STATE_FORMAT": "<state format>", "HARDENING_FORMAT": "<hardening format>"}

    def render(element, default):
        if isinstance(element, ast.Constant):
            return str(element.value)
        return labels.get(element.id, default) if isinstance(element, ast.Name) else default

    if node.func.attr == "compose":
        tail = []
        for arg in node.args:
            tail.append(render(arg, "<service>"))
        return "compose -p zeus-buzz-e2e -f <compose.yaml> --env-file <env file> " + " ".join(tail)
    if not node.args or not isinstance(node.args[0], ast.List) or any(isinstance(e, ast.Starred) for e in node.args[0].elts):
        return None  # the chokepoint's own forwarding call, not a form
    return " ".join(render(element, "<container id>") for element in node.args[0].elts)


def test_the_docker_argv_forms_list_matches_the_calls():
    forms = module_constant("DOCKER_FORMS")
    used = [form for node in ast.walk(TREE) if isinstance(node, ast.Call) and (form := call_form(node)) is not None]
    assert used, "no docker call found"
    assert set(used) == set(forms), (sorted(set(used) - set(forms)), sorted(set(forms) - set(used)))
    assert len(forms) == len(set(forms))
    assert not any(form.startswith(("run", "exec", "cp", "build", "pull", "kill", "rm")) for form in forms)
    assert all("--privileged" not in form and "--network host" not in form for form in forms)
    save = functions()["save"]  # the report stores the same list
    assert "DOCKER_FORMS" in ast.dump(save) and "docker_forms" in ast.dump(save)
    assert "DOCKER_FORMS" in ast.dump(functions()["run_all"]), "the header prints the forms"


def secret_names_in(node):
    """Identifiers (names and attributes) in `node` that look like secret values (a path-typed name is fine)."""
    found = []
    for child in ast.walk(node):
        name = child.id if isinstance(child, ast.Name) else child.attr if isinstance(child, ast.Attribute) else None
        if name and any(part in name.lower() for part in SECRET_PARTS) and not name.endswith(PATH_SUFFIXES):
            found.append(name)
    return found


def printing_or_raising(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in ("print", "log", "info", "warning", "error", "debug"):
                yield node
        elif isinstance(node, ast.Raise) and node.exc is not None:
            yield node


def test_no_key_dsn_or_password_value_is_printed_logged_or_raised():
    nodes = list(printing_or_raising(TREE))
    assert len([n for n in nodes if isinstance(n, ast.Call)]) >= 5, "the scan found too few prints (a vacuous check)"
    bad = [(node.lineno, secret_names_in(node)) for node in nodes if secret_names_in(node)]
    assert not bad, f"secret-looking names reach a print/log/raise: {bad}"
    sample = ast.parse('print(f"x {dsn_text}")\nraise ValueError(password)\nprint(dsn_file)')
    flagged = sorted(secret_names_in(node) for node in printing_or_raising(sample))
    assert flagged == [[], ["dsn_text"], ["password"]], flagged  # the checker bites; a path-typed name is allowed
    argv_text = RUNNER.read_text("utf-8")
    assert "def scan_argv" in argv_text and "a secret value is on the argv" in argv_text


def test_the_runner_starts_the_bridge_workers_and_the_driver_as_specified():
    text = RUNNER.read_text("utf-8")
    assert '"-m", "codex_harness.entry.processes.buzz_bridge", "--config"' in text
    assert 'NODE = "/home/trevi/.local/share/fnm/node-versions/v24.21.0/installation/bin/node"' in text
    assert '"--import", "./test-loader.mjs", "--experimental-strip-types", DRIVER, op' in text
    assert 'DRIVER = "src/features/zeus/e2e/driver.mjs"' in text
    for name in ("ZEUS_E2E_CONFIG", "ZEUS_E2E_OWNER_KEY", "ZEUS_E2E_STORAGE"):
        assert f"{name}=str(" in text, name
    assert 'cwd=str(self.desktop / "desktop")' in text
    assert "execution_fence.require_current" in (E2E / "attempt_worker.py").read_text("utf-8")
    assert "complete_on" in (E2E / "attempt_worker.py").read_text("utf-8")
    assert "def step_" in text and text.count("report.step(") >= 12
    worker_tree = ast.parse((E2E / "attempt_worker.py").read_text("utf-8"))
    assert not any(isinstance(n, ast.Call) and is_subprocess_attr(n) for n in ast.walk(worker_tree))


def test_run_matrix_is_unchanged():
    assert hashlib.sha256(A4_RUNNER.read_bytes()).hexdigest() == RUN_MATRIX_SHA256


def test_help_exits_zero_and_lists_the_flags_and_lint_templates_is_reserved():
    helped = subprocess.run([sys.executable, "-B", str(RUNNER), "--help"], capture_output=True, text=True, check=False,
                            timeout=120)
    assert helped.returncode == 0, helped.stderr[-300:]
    for flag in ("--report", "--keep-on-failure", "--desktop", "--lint-templates"):
        assert flag in helped.stdout
    linted = subprocess.run([sys.executable, "-B", str(RUNNER), "--lint-templates"], capture_output=True, text=True,
                            check=False, timeout=120)
    assert linted.returncode == 0 and "not yet" in linted.stdout
