"""CUT-INT WN-1 (cut-int-wn1-worker-network-binding): the production isolated worker is bound to the guarded
`zeus-workers` network or refused before any container create or provider call.

Behavioural: every check drives the public boundary (`load_isolation`, `preflight`, `OwnedContainer.verify`, the
runtimes' `__enter__`, `build_executor`) over an injected fake runner that records its argv. The expected network
identity and guard dependencies are parsed from the sealed producer record (I2 v2, tests/fixtures/worker_network/
i2-v2-producer.txt), never retyped; the observed shapes (observed-shapes.json) are real, the zeus-workers success
shapes below are SYNTHETIC (built from the observed zeus-aibox object and the producer constants).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

# git_workspace binds `process_groups.run_process` by name at its first import, so it must load before any patch of
# `process_groups.run_process`; first imported under a patch it keeps the fake for the rest of the session.
import codex_harness.host_os.adapters.git_workspace  # noqa: F401
from codex_harness.composition import configuration, operation
from codex_harness.execution.adapters.containers import launcher, owned_container
from codex_harness.execution.domain import container_spec as spec
from codex_harness.kernel.errors import IsolationError

FIXTURES = Path(__file__).parent / "fixtures" / "worker_network"
OBSERVED = json.loads((FIXTURES / "observed-shapes.json").read_text())
PRODUCER = (FIXTURES / "i2-v2-producer.txt").read_text()


def _producer_identity() -> dict:
    create = re.search(r"\[e1\.2-create\]\n(.*?)\n\[", PRODUCER, re.S).group(1).replace("\\\n", " ").split()
    unit = re.search(r"^After=(.*)$", PRODUCER, re.M).group(1).split()
    return {"name": create[-1], "subnet": create[create.index("--subnet") + 1],
            "bridge": next(w.split("=", 1)[1] for w in create if w.startswith("com.docker.network.bridge.name=")),
            "labels": dict(w.split("=", 1) for i, w in enumerate(create) if i and create[i - 1] == "--label"),
            "guard": re.search(r"/etc/systemd/system/([\w.-]+\.service)\n", PRODUCER).group(1), "after": unit}


IDENTITY = _producer_identity()
IMAGE = "sha256:" + "a" * 64
NET_ID = "c" * 64


def _network(**tamper) -> dict:
    """SYNTHETIC zeus-workers: the OBSERVED zeus-aibox object with the producer's identity applied."""
    body = json.loads(json.dumps(OBSERVED["network_inspect"]["zeus-aibox"]))
    body.update(Name=IDENTITY["name"], Id=NET_ID, Labels=dict(IDENTITY["labels"]),
                Options={"com.docker.network.bridge.name": IDENTITY["bridge"]})
    body["IPAM"]["Config"] = [{"Subnet": IDENTITY["subnet"], "Gateway": "10.231.65.1"}]
    return {**body, **tamper}


def _blocks(guard=None, **units) -> str:
    """SYNTHETIC ready `systemctl show` output in the observed block format (blocks bound by Id)."""
    def block(name, active="active", sub="running", load="loaded", result="success", stamp=100):
        return (f"Id={name}\nLoadState={load}\nActiveState={active}\nSubState={sub}\n"
                f"ActiveEnterTimestampMonotonic={stamp}\nResult={result}\n")
    wanted = {IDENTITY["guard"]: {"sub": "exited", "stamp": 300, **(guard or {})},
              **{name: {"stamp": 200, **units.get(name, {})} for name in IDENTITY["after"]}}
    # Deliberately not the producer's order: the guard block comes last.
    return "\n".join(block(name, **wanted[name]) for name in (*IDENTITY["after"], IDENTITY["guard"]))


def _done(args, out="", code=0, err=""):
    return subprocess.CompletedProcess(args, code, out, err)


class Fake:
    """Records every argv; `network`/`guard` are the (stdout, returncode) the two read-only probes answer."""

    def __init__(self, network=None, guard=None, attached=None):
        self.calls = []
        self.network = (json.dumps(_network()) + "\n", 0) if network is None else network
        self.guard = (_blocks(), 0) if guard is None else guard
        self.attached = {spec.WORKER_NETWORK: {"NetworkID": ""}} if attached is None else attached
        self.inspect_body = None

    def __call__(self, argv, *, timeout, env=None):
        self.calls.append(list(argv))
        if argv[0] == "systemctl":
            return _done(argv, *self.guard[:1], code=self.guard[1])
        verb = argv[1]
        if verb == "version":
            return _done(argv, "29.8.1\n")
        if argv[1:3] == ["image", "inspect"]:
            return _done(argv, IMAGE + "\n")
        if argv[1:3] == ["network", "inspect"]:
            return _done(argv, *self.network[:1], code=self.network[1])
        if verb == "inspect" and "NetworkSettings" in argv[3]:
            return _done(argv, json.dumps(self.attached))
        if verb == "inspect":
            return _done(argv, json.dumps(self.inspect_body))
        raise AssertionError("unexpected docker call: " + " ".join(argv))

    def verbs(self):
        return [call[1] if call[0] == "docker" else call[0] for call in self.calls]


def config(settings=None):
    return spec.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE, **(settings or {})},
                               driver_sha256="d" * 64)


PRODUCTION = {"ZEUS_COMPOSITION_PROFILE": "production"}
FORBIDDEN_VERBS = ("create", "rm", "connect", "disconnect", "start", "restart", "sudo")


def assert_never_mutates(fake):
    for call in fake.calls:
        assert "sudo" not in call and not (call[0] == "docker" and call[1] == "network" and call[2] != "inspect")
        assert call[0] != "systemctl" or call[1] == "show"
        assert call[1:2] != ["create"]


# ---- the producer-derived constants ----------------------------------------------------------------------
def test_constants_equal_the_producer_record():
    assert (spec.WORKER_NETWORK, spec.WORKER_BRIDGE, spec.WORKER_SUBNET) == (
        IDENTITY["name"], IDENTITY["bridge"], IDENTITY["subnet"])
    assert spec.WORKER_LABELS == IDENTITY["labels"]
    assert (spec.GUARD_UNIT, list(spec.GUARD_AFTER)) == (IDENTITY["guard"], IDENTITY["after"])


# ---- decision 1: the profile-derived network -------------------------------------------------------------
@pytest.mark.parametrize("settings", [{}, {"ZEUS_COMPOSITION_PROFILE": "development"},
                                      {"ZEUS_COMPOSITION_PROFILE": "other"}])
def test_non_production_keeps_the_default_bridge_body_and_digest(settings):
    body = config(settings)
    assert body["network"] == {"worker": "bridge", "verifier": "none"}
    legacy = {key: body[key] for key in ("mode", "image", "limits", "driver_sha256", "protocol", "network")}
    assert body["digest"] == spec.digest(legacy) and body == config()


def test_production_selects_the_guarded_network_and_keeps_the_verifier_unreachable():
    assert config(PRODUCTION)["network"] == {"worker": "zeus-workers", "verifier": "none"}


# ---- decisions 3-4: launch-time preflight ----------------------------------------------------------------
def run_preflight(fake, settings=PRODUCTION, **kwargs):
    body = config(settings)
    return owned_container.preflight(body, environment={"PATH": "/bin"}, runner=fake, token=False,
                                     network=body["network"]["worker"], **kwargs)


def test_production_preflight_returns_the_network_and_guard_and_only_reads():
    fake = Fake()
    result = run_preflight(fake)
    assert result["network"] == {"name": "zeus-workers", "id": NET_ID}
    assert result["guard"] == {"unit": "zeus-aibox-network-guard.service", "ready": True}
    assert fake.verbs() == ["version", "image", "network", "systemctl"]
    assert fake.calls[2][1:] == ["network", "inspect", "--format", "{{json .}}", "zeus-workers"]
    assert_never_mutates(fake)


@pytest.mark.parametrize("settings", [{}, {"ZEUS_COMPOSITION_PROFILE": "development"}])
def test_default_bridge_preflight_issues_exactly_the_base_calls(settings):
    fake, body = Fake(), config(settings)
    result = owned_container.preflight(body, environment={"PATH": "/bin"}, runner=fake, token=False,
                                       network=body["network"]["worker"])
    assert fake.verbs() == ["version", "image"] and set(result) == {"docker_server", "image", "token"}


def test_the_none_network_issues_exactly_the_base_calls():
    fake = Fake()
    owned_container.preflight(config(PRODUCTION), environment={"PATH": "/bin"}, runner=fake, token=False, network="none")
    assert fake.verbs() == ["version", "image"]


def test_absent_network_is_refused_with_the_observed_failure_shape():
    absent = OBSERVED["network_inspect_absent"]
    fake = Fake(network=(absent["stdout"], absent["returncode"]))
    with pytest.raises(IsolationError, match="worker_network_unavailable"):
        run_preflight(fake)
    assert fake.verbs() == ["version", "image", "network"]


def test_a_spawn_failure_of_the_network_call_is_a_refusal_not_an_exception():
    def runner(argv, *, timeout, env=None):
        if argv[1:3] == ["network", "inspect"]:
            raise subprocess.TimeoutExpired(argv, timeout)
        return Fake()(argv, timeout=timeout, env=env)
    with pytest.raises(IsolationError, match="worker_network_unavailable"):
        owned_container.preflight(config(PRODUCTION), environment={"PATH": "/bin"}, runner=runner, token=False,
                                  network="zeus-workers")


WRONG = [("bridge name option absent (as on zeus-aibox)", {"Options": {}}),
         ("another bridge name", {"Options": {"com.docker.network.bridge.name": "docker0"}}),
         ("name", {"Name": "zeus-aibox"}), ("short id", {"Id": "abc"}), ("driver", {"Driver": "overlay"}),
         ("ipv6", {"EnableIPv6": True}), ("internal", {"Internal": True}), ("no labels", {"Labels": {}}),
         ("wrong owner label", {"Labels": {"zeus.owner": "x", "zeus.role": "workers"}}),
         ("another subnet", {"IPAM": {"Config": [{"Subnet": "10.231.64.0/24"}]}}),
         ("two subnets", {"IPAM": {"Config": [{"Subnet": IDENTITY["subnet"]}, {"Subnet": "10.9.0.0/24"}]}})]


@pytest.mark.parametrize("label,tamper", WRONG, ids=[label for label, _ in WRONG])
def test_a_wrong_network_identity_is_refused(label, tamper):
    fake = Fake(network=(json.dumps(_network(**tamper)) + "\n", 0))
    with pytest.raises(IsolationError, match="worker_network_identity_mismatch"):
        run_preflight(fake)
    assert "systemctl" not in fake.verbs()


@pytest.mark.parametrize("stdout", ["not json\n", "[1]\n", json.dumps(_network()) + "\n" + json.dumps(_network()) + "\n",
                                    json.dumps(_network(IPAM=None)) + "\n", json.dumps(_network(Labels=[])) + "\n"])
def test_unparsable_or_multiple_network_output_is_an_identity_mismatch(stdout):
    with pytest.raises(IsolationError, match="worker_network_identity_mismatch"):
        run_preflight(Fake(network=(stdout, 0)))


def test_the_observed_unguarded_host_state_is_refused():
    fake = Fake(guard=(OBSERVED["systemctl_show_stdout"], 0))
    with pytest.raises(IsolationError, match="worker_network_guard_unready"):
        run_preflight(fake)


GUARD = [("not applied", {"guard": {"load": "not-found", "active": "inactive", "sub": "dead", "stamp": 0}}),
         ("failed result", {"guard": {"result": "exit-code"}}), ("running not exited", {"guard": {"sub": "running"}}),
         ("applied before docker restarted", {"guard": {"stamp": 150}}),
         ("docker inactive", {"docker.service": {"active": "inactive"}}),
         ("user-fw zero stamp", {"docker-user-fw.service": {"stamp": 0}})]


@pytest.mark.parametrize("label,states", GUARD, ids=[label for label, _ in GUARD])
def test_a_guard_that_is_not_applied_after_docker_is_refused(label, states):
    with pytest.raises(IsolationError, match="worker_network_guard_unready"):
        run_preflight(Fake(guard=(_blocks(**states), 0)))


@pytest.mark.parametrize("answer", [("", 1), ("", 0), ("Id=zeus-aibox-network-guard.service\n", 0),
                                    (_blocks().replace("ActiveEnterTimestampMonotonic=300", "ActiveEnterTimestampMonotonic=x"), 0)])
def test_missing_failed_or_unparsable_guard_output_is_refused(answer):
    with pytest.raises(IsolationError, match="worker_network_guard_unready"):
        run_preflight(Fake(guard=answer))


def test_an_equal_guard_stamp_is_ready_and_block_order_is_irrelevant():
    stamps = {name: {"stamp": 300} for name in IDENTITY["after"]}
    assert run_preflight(Fake(guard=(_blocks(**stamps), 0)))["guard"]["ready"] is True


def test_a_systemctl_spawn_failure_is_a_refusal_not_an_exception():
    def runner(argv, *, timeout, env=None):
        if argv[0] == "systemctl":
            raise FileNotFoundError("systemctl")
        return Fake()(argv, timeout=timeout, env=env)
    with pytest.raises(IsolationError, match="worker_network_guard_unready"):
        owned_container.preflight(config(PRODUCTION), environment={"PATH": "/bin"}, runner=runner, token=False,
                                  network="zeus-workers")


def test_the_guard_probe_never_receives_the_worker_token():
    seen = []

    def runner(argv, *, timeout, env=None):
        seen.append((argv[0], dict(env or {})))
        return Fake()(argv, timeout=timeout, env=env)
    environment = {"PATH": "/bin", spec.TOKEN_NAME: "secret-value"}
    owned_container.preflight(config(PRODUCTION), environment=environment, runner=runner, token=True,
                              network="zeus-workers")
    assert all(spec.TOKEN_NAME not in env for _, env in seen) and any(name == "systemctl" for name, _ in seen)


# ---- decision 2/3: the runtimes' launch ------------------------------------------------------------------
def codex_runtime(fake, body, network=None):
    host = SimpleNamespace(runner=fake)
    kwargs = {} if network is None else {"network": network}
    return launcher.IsolatedCodexRuntime(body, "/tmp/unused", profile="codex-role-ro", broker=object(), host=host,
                                         credentials=object(), **kwargs)


def test_production_codex_launch_refuses_before_anything_else_when_the_network_is_absent(monkeypatch):
    fake = Fake(network=("\n", 1))
    body = config(PRODUCTION)
    runtime = codex_runtime(fake, body, body["network"]["worker"])
    with pytest.raises(IsolationError, match="worker_network_unavailable"):
        runtime.__enter__()
    assert set(fake.verbs()) <= {"version", "image", "network"}


def test_production_codex_launch_passes_with_a_healthy_guarded_network():
    fake, body = Fake(), config(PRODUCTION)
    runtime = codex_runtime(fake, body, body["network"]["worker"])
    assert runtime.__enter__() is runtime and runtime.preflight["network"]["id"] == NET_ID
    assert runtime.preflight["token"] is None


def test_claude_launch_refuses_an_unguarded_network_and_is_otherwise_the_base_calls():
    body = config(PRODUCTION)
    host = SimpleNamespace(runner=Fake(guard=(OBSERVED["systemctl_show_stdout"], 0)))
    runtime = launcher.IsolatedClaudeRuntime.__new__(launcher.IsolatedClaudeRuntime)
    runtime.config, runtime.docker, runtime.environment_source, runtime.host = body, "docker", {spec.TOKEN_NAME: "t"}, host
    with pytest.raises(IsolationError, match="worker_network_guard_unready"):
        runtime.__enter__()
    plain = config()
    ok = SimpleNamespace(runner=Fake())
    runtime.config, runtime.host = plain, ok
    assert runtime.__enter__() is runtime and ok.runner.verbs() == ["version", "image"]


def test_codex_launch_on_the_default_bridge_issues_the_base_calls():
    fake = Fake()
    codex_runtime(fake, config()).__enter__()
    assert fake.verbs() == ["version", "image"]


def test_isolated_worker_hands_the_configured_network_to_the_codex_runtime(monkeypatch, tmp_path):
    seen = {}

    class Recorder:
        def __init__(self, selection, root, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(launcher, "IsolatedCodexRuntime", Recorder)
    body = {**config(PRODUCTION), "codex": {"credential_store": "/store"}}
    worker = launcher.IsolatedWorker(body, tmp_path, host="host", broker_factory=lambda path: path, credentials="c")
    worker.codex_runtime(profile="codex-role-ro")
    assert seen["network"] == "zeus-workers"


# ---- every profile's create argv carries the configured network ------------------------------------------
@pytest.mark.parametrize("profile", sorted(spec.PROFILES))
def test_create_argv_carries_the_configured_network_for_every_profile(profile):
    for settings, network in ((PRODUCTION, "zeus-workers"), ({}, "bridge")):
        body = config(settings)
        argv = spec.container_args(body, name="n", run_id="r", role="worker", network=body["network"]["worker"],
                                   mounts=[], environment={}, pass_names=(), entry=["x"], workdir="/", user="1:1")
        assert argv[argv.index("--network") + 1] == network


# ---- decision 5: exactly one attached network ------------------------------------------------------------
def verified(fake, network):
    body = {"image": IMAGE, "user": "1:1", "network": network, "read_only": True, "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"], "memory": 1, "nano_cpus": 1, "pids_limit": 1, "privileged": False,
            "ports": {}, "labels": {spec.LABEL: "run1"}, "pid_mode": "", "ipc_mode": "private", "cap_add": None,
            "devices": [], "mounts": [{"Type": "bind", "Source": "/x/ws", "Destination": spec.WORKSPACE, "RW": True}]}
    fake.inspect_body = body
    container = owned_container.OwnedContainer(config(PRODUCTION), "docker", "run1", "worker", runner=fake)
    container.id = "e" * 64
    return container.verify({spec.WORKSPACE}, network)


def test_verify_on_the_guarded_network_checks_exactly_one_attached_network():
    fake = Fake()
    verified(fake, "zeus-workers")
    assert fake.calls[-1][1:4] == ["inspect", "--format", "{{json .NetworkSettings.Networks}}"]
    assert fake.calls[-1][-1] == "e" * 64 and len(fake.calls) == 2


@pytest.mark.parametrize("attached", [{"zeus-workers": {}, "bridge": {}}, {"bridge": {}}, {}, [], "garbage"])
def test_verify_refuses_any_other_attached_network_set(attached):
    fake = Fake(attached=attached)
    with pytest.raises(IsolationError, match="container_controls_mismatch"):
        verified(fake, "zeus-workers")


@pytest.mark.parametrize("network", ["bridge", "none"])
def test_verify_on_bridge_or_none_issues_no_extra_call(network):
    fake = Fake()
    verified(fake, network)
    assert len(fake.calls) == 1


# ---- decision 6: production consistency ------------------------------------------------------------------
@pytest.fixture
def host_settings(monkeypatch):
    values = {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    return values


def test_a_production_override_of_a_non_production_host_refuses_before_any_preflight(host_settings, monkeypatch):
    from codex_harness.composition import isolation
    monkeypatch.setattr(isolation, "isolated_worker", lambda config: pytest.fail("composed isolation"))
    for value in (None, "development"):
        host_settings.pop("ZEUS_COMPOSITION_PROFILE", None)
        if value:
            host_settings["ZEUS_COMPOSITION_PROFILE"] = value
        with pytest.raises(IsolationError, match="worker_network_required"):
            operation.build_executor(profile="production")


def test_production_composition_makes_no_network_or_systemctl_call(host_settings, monkeypatch):
    """Composition-time preflight is unchanged: it passes no network, so a production composition probes neither."""
    from codex_harness.composition import isolation
    from codex_harness.host_os.adapters import process_groups
    fake = Fake()
    monkeypatch.setattr(process_groups, "run_process", fake)
    monkeypatch.setattr(isolation, "IsolatedWorker", lambda *a, **k: SimpleNamespace(), raising=False)
    monkeypatch.setattr("codex_harness.execution.adapters.containers.launcher.IsolatedWorker",
                        lambda *a, **k: SimpleNamespace(config=a[0], root=a[1], docker=None))
    host_settings["ZEUS_COMPOSITION_PROFILE"] = "production"
    isolation.isolated_worker(owned_container.load_host_isolation(host_settings),
                              environment={"PATH": "/bin", spec.TOKEN_NAME: "t"})
    assert fake.verbs() == ["version", "image"]
    assert "network" not in fake.verbs() and "systemctl" not in fake.verbs()
