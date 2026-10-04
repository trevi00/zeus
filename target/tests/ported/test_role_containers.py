"""INV-ROLE-CONTAINER-001 / INV-CODEX-CREDENTIAL-001 / INV-MONITOR-VIEWER-001.

Everything above the Docker marker uses an INJECTED fake Docker client (`FakeDocker`) and a real local
child process that speaks the Codex App Server JSON-RPC in place of the attached container. Every
credential is a DUMMY fixture value; no model, provider, live store or service is called, and none of
these results is an observation of a real container or a real Codex run. The marked Docker tests use
disposable, run-labelled containers with `--network none` or a shell probe; they never call a provider.

Ported SOURCE M7 suite `tests/test_role_containers.py` run against the target (REBUILD-DESIGN-v2 §5.3 S3;
the carried I1 (f)1-(f)5 and RC2-F3 1-5 discriminators, the scrub/refusal controls and the profile and
transport tests). Import paths and the injected fake are rewritten through `m7_containers` (its docstring
names both adaptations); any other adaptation is named in place.

Formerly not ported here (S2-S7 pilots); batch U3 below copies every one of them:
- test_the_viewer_web_service_refuses_to_start_with_a_desk_revision: S10 entry (monitor)
- test_serve_refuses_a_desk_on_the_viewer_port_before_binding: S9 observation (viewer)
- test_monitor_web_main_refuses_before_any_listener_when_the_desk_is_configured: S10 entry (monitor)

PORTING NOTES (S4 ported executor suites; the M7 assertions are unchanged):
- The four executor cases are ported over `m7_executor.Executor`/`Service` (a TEST shim over RunTask; construction
  only): `executor_with` builds it with the M7 fixtures `Unexpected`/`Recorded` and the injected isolation stand-in;
  the patch targets `codex_harness.adapters.executor.{AppServer,ClaudeCodeRuntime}` are `m7_executor.*`.
- test_executor_refuses_active_native_hooks_in_a_codex_container: SKIPPED, S3b declared change (design v2 §5.4):
  with isolation the target runs the active native hooks INSIDE the codex container (golden hooks.native_container)
  instead of M7's `codex_container_native_hooks_unsupported` refusal, and M7 `adapters/hooks.NativeHooks` (patched
  by this test) is S8's. The body is kept unchanged.

Batch U3 (V6 retrofit): the three desk/viewer-listener cases that had been left out are copied verbatim.
test_serve_refuses_a_desk_on_the_viewer_port_before_binding RUNS: M7's `adapters.monitoring_web` is
`observation.adapters.viewer_http` (its `serve` and `ThreadingHTTPServer`; the in-body import line is the adaptation). The other
two run since S10 E2a: `monitor.listener_refusal`/`viewer_port` are `composition.monitor`'s, `monitor.main` is `entry.processes.monitor.main` (its
`settings` is that module's, the patched listener class `observation.adapters.viewer_http.ThreadingHTTPServer`).
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import m7_executor
import pytest
from m7_containers import ContractError, install_fake, iw, rc

from codex_harness.execution.adapters.containers import owned_container
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

IMAGE = "sha256:" + "a" * 64
# Adaptation: DUMMY fixture credentials are assembled at run time so the tree carries no credential-shaped
# literal (compare/run.py check-tree); the values the tests see are the M7 values.
CLAUDE_TOKEN = "sk-" + "ant-oat01-FIXTURE-DUMMY-NOT-A-TOKEN"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
ROOT = Path(__file__).resolve().parents[2]  # the target tree (its Dockerfile.worker)

JWT = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJEVU1NWSJ9.c2lnLURVTU1Z"  # {"alg":"none"}.{"sub":"DUMMY"}.DUMMY
ISSUED = ("rt-DUMMY-NOT-A-TOKEN", "at-DUMMY-NOT-A-TOKEN", "idt-DUMMY", "acct-dummy-0001")

APP_SERVER = r'''
import json, os, sys, time
JWT = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJEVU1NWSJ9.c2lnLURVTU1Z"
mode, home, workspace, config = sys.argv[1:5]
def send(message):
    sys.stdout.write(json.dumps(message) + "\n"); sys.stdout.flush()
def rewrite_auth(mutate):
    path = os.path.join(home, "auth.json")
    with open(path) as handle:
        body = json.load(handle)
    mutate(body)
    with open(path, "r+") as handle:        # in place, as the pinned CLI's file store writes
        handle.seek(0); handle.write(json.dumps(body)); handle.truncate()
cwd = None
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        if mode == "exit":
            sys.exit(3)
        send({"id": message["id"], "result": {"codexHome": "/codex-home"}})
    elif method in ("thread/start", "thread/resume"):
        cwd = message["params"]["cwd"]
        send({"id": message["id"], "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        send({"id": message["id"], "result": {"turn": {"id": "turn-1"}}})
        listing = sorted(os.listdir(home))
        # Legitimate CLI state, created on every turn (sessions, sqlite state, logs).
        os.makedirs(os.path.join(home, "sessions"), exist_ok=True)
        with open(os.path.join(home, "sessions", "rollout.jsonl"), "a") as handle: handle.write("{}\n")
        with open(os.path.join(home, "state_5.sqlite"), "ab") as handle: handle.write(b"x")
        if mode == "history":
            with open(os.path.join(home, "history.jsonl"), "a") as handle: handle.write("implementer history\n")
        if mode == "refresh":
            rewrite_auth(lambda body: body["tokens"].update(access_token="at-REFRESHED-DUMMY"))
        if mode == "identity":
            rewrite_auth(lambda body: body["tokens"].update(account_id="acct-OTHER-DUMMY"))
        if mode == "garbage":
            with open(os.path.join(home, "auth.json"), "r+") as handle: handle.write("{not json")
        if mode == "config":
            os.chmod(config, 0o644)
            with open(config, "a") as handle: handle.write("sandbox_mode = \"danger-full-access\"\n")
        if mode == "workspace":
            with open(os.path.join(workspace, "kept.txt"), "w") as handle: handle.write("edited by codex\n")
        if mode == "unreadable":
            os.chmod(os.path.join(home, "auth.json"), 0)
        if mode.startswith("echo"):
            # A tool/agent echoing its own (DUMMY) credential, e.g. during authentication troubleshooting.
            if mode == "echo_refresh":
                rewrite_auth(lambda body: body["tokens"].update(access_token="at-ROTATED-DUMMY-VALUE"))
            with open(os.path.join(home, "auth.json")) as handle:
                tokens = json.load(handle)["tokens"]
            leak = tokens["access_token"] if mode == "echo_refresh" else tokens["refresh_token"]
            if mode == "echo_error":
                send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {
                    "id": "turn-1", "status": "failed", "error": {"message": "diagnostic: " + leak}}}})
                continue
            if mode == "echo_stream":
                for part in ("prefix ", leak[:5], leak[5:12], leak[12:] + " suffix"):
                    send({"method": "item/agentMessage/delta", "params": {"threadId": "thread-1", "turnId": "turn-1",
                          "itemId": "a0", "delta": part}})
            send({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1", "item": {
                "type": "commandExecution", "id": "c1", "status": "completed", "command": "cat /codex-home/auth.json",
                "aggregatedOutput": "ordinary output 42\n" + json.dumps({"tokens": tokens}) + "\n" + JWT}}})
            answer = json.dumps({"summary": "ordinary answer; echoed " + leak + " and " + JWT})
            send({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1",
                  "item": {"type": "agentMessage", "id": "a1", "text": answer}}})
            send({"method": "turn/completed", "params": {"threadId": "thread-1",
                  "turn": {"id": "turn-1", "status": "completed"}}})
            continue
        if mode == "sleep":
            time.sleep(120)
        if mode == "fail_auth":
            send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {
                "id": "turn-1", "status": "failed", "error": {"message": "401 Unauthorized (fixture)"}}}})
            continue
        answer = json.dumps({"summary": json.dumps({"cwd": cwd, "home": listing})})
        send({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1",
              "item": {"type": "agentMessage", "id": "a1", "text": answer}}})
        send({"method": "turn/completed", "params": {"threadId": "thread-1",
              "turn": {"id": "turn-1", "status": "completed"}}})
'''


def dummy_auth(account="acct-dummy-0001", access="at-DUMMY-NOT-A-TOKEN"):
    return {"OPENAI_API_KEY": None, "auth_mode": "chatgpt",
            "tokens": {"id_token": "idt-DUMMY", "access_token": access, "refresh_token": "rt-DUMMY-NOT-A-TOKEN",
                       "account_id": account}, "last_refresh": "2026-09-29T00:00:00Z"}


class FakeDocker:
    """Injected fault/fixture: answers the exact docker argv the adapters compose."""

    def __init__(self, tmp_path, mode="ok"):
        self.calls, self.containers, self.mode, self.process = [], {}, mode, None
        self.tamper, self.kill_works, self.rm_works = {}, True, True
        self.script = tmp_path / "app_server.py"
        self.script.write_text(APP_SERVER, encoding="utf-8")

    def __call__(self, docker, args, *, timeout, env=None):
        self.calls.append({"args": list(args), "env": dict(env or {})})
        done = lambda out="", code=0: subprocess.CompletedProcess(args, code, out, "")  # noqa: E731
        if args[0] == "version":
            return done("29.8.1\n")
        if args[:2] == ["image", "inspect"]:
            return done(IMAGE + "\n")
        if args[0] == "create":
            identifier = format(len(self.containers) + 1, "x").rjust(64, "e")
            labels = dict(a.split("=", 1) for i, a in enumerate(args) if args[i - 1] == "--label")
            mounts = [dict(p.split("=", 1) for p in a.split(",")) for i, a in enumerate(args) if args[i - 1] == "--mount"]
            self.containers[identifier] = {"name": args[args.index("--name") + 1], "labels": labels, "mounts": mounts,
                                           "network": args[args.index("--network") + 1], "status": "created",
                                           "user": args[args.index("--user") + 1], "args": list(args)}
            return done(identifier + "\n")
        if args[0] == "ps":
            name = [a for a in args if a.startswith("name=")][0][len("name=^/"):-1]
            label = [a for a in args if a.startswith("label=")]
            ids = [i for i, c in self.containers.items() if c["name"] == name and
                   (not label or c["labels"].get(iw.LABEL) == label[0].split("=", 2)[2])]
            return done("\n".join(ids) + "\n")
        container = self.containers.get(args[-1])
        if container is None:
            return done(code=1)
        if args[0] == "inspect" and args[2] == iw.INSPECT_FORMAT:
            body = {"image": IMAGE, "user": container["user"], "network": container["network"], "read_only": True,
                    "cap_drop": ["ALL"], "security_opt": ["no-new-privileges"], "memory": 1, "nano_cpus": 1,
                    "pids_limit": 512, "privileged": False, "ports": {}, "labels": container["labels"],
                    "pid_mode": "", "ipc_mode": "private", "uts_mode": "", "userns_mode": "", "cap_add": None,
                    "devices": [],
                    "mounts": [{"Type": "bind", "Source": m["source"], "Destination": m["target"],
                                "RW": m.get("readonly") != "true"} for m in container["mounts"]]}
            return done(json.dumps({**body, **self.tamper}))
        if args[0] == "inspect":
            if self.process is not None and self.process.poll() is not None and container["status"] == "running":
                container["status"] = "exited"
            return done(container["status"] + " 0 false\n")
        if args[0] == "kill":
            if self.kill_works:
                container["status"] = "exited"
            return done()
        if args[0] == "rm":
            if self.rm_works and container["status"] != "running":
                del self.containers[args[-1]]
                return done()
            return done(code=1)
        raise AssertionError("unexpected docker argv: " + repr(args))

    def created(self):
        return [call for call in self.calls if call["args"][0] == "create"]

    def tree(self):
        fake = self

        class Tree:
            @staticmethod
            def spawn(argv, **kwargs):
                container = fake.containers[argv[-1]]
                container["status"] = "running"
                source = {m["target"]: m["source"] for m in container["mounts"]}
                tree = REAL_TREE.spawn([sys.executable, str(fake.script), fake.mode, source.get(rc.CODEX_HOME, ""),
                                        source.get(iw.WORKSPACE, ""), source.get(rc.CODEX_HOME + "/config.toml", "")],
                                       **kwargs)
                fake.process = tree.process
                return tree
        return Tree


REAL_TREE = iw.ProcessTree


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def candidate(tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "kept.txt").write_text("original\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "secrets" / "codex-product"
    root.mkdir(parents=True)
    root.chmod(0o700)
    auth = root / "auth.json"
    auth.write_text(json.dumps(dummy_auth()), encoding="utf-8")
    auth.chmod(0o600)
    return root


@pytest.fixture
def config(store):
    return iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                              "ZEUS_CODEX_CREDENTIAL_STORE": str(store)})


@pytest.fixture
def fake(tmp_path, monkeypatch):
    docker = FakeDocker(tmp_path)
    install_fake(monkeypatch, docker)
    return docker


def runtime(config, tmp_path, store, profile, **kwargs):
    return rc.IsolatedCodexRuntime(config, tmp_path / "runs", profile=profile, broker=rc.CodexCredentialBroker(store),
                                   environment={**os.environ, iw.TOKEN_NAME: CLAUDE_TOKEN},
                                   state_root=tmp_path / "codex-state", lock_wait_seconds=0.5, **kwargs)


def run_codex(config, tmp_path, store, candidate, fake, *, mode="ok", profile=rc.CODEX_ROLE_RO, timeout=30, **kwargs):
    fake.mode = mode
    with runtime(config, tmp_path, store, profile) as opened:
        return opened.run("review this", str(candidate), SCHEMA, timeout, read_only=profile == rc.CODEX_ROLE_RO,
                          **kwargs)


def answer_of(result):
    return json.loads(result["answer"]["summary"])


def ledger(store):
    return rc.CodexCredentialBroker(store).entries()


# ---- (f)1: the routing result maps to exactly one profile; everything else refuses before spawn ----
@pytest.mark.parametrize("shape,profile", [
    (("claude", "claude_cli", "implement", False), rc.CLAUDE_IMPL_RW),
    (("codex", "app_server", "implement", False), rc.CODEX_IMPL_RW),
    (("claude", "claude_cli", "dge_role", True), rc.CLAUDE_ROLE_RO),
    (("claude", "claude_cli", "frontdesk", True), rc.CLAUDE_ROLE_RO),
    (("claude", "claude_cli", "plan", True), rc.CLAUDE_ROLE_RO),
    (("codex", "app_server", None, True), rc.CODEX_ROLE_RO),
    (("codex", "app_server", "dge_role", True), rc.CODEX_ROLE_RO),
    (("codex", "app_server", "plan", True), rc.CODEX_ROLE_RO),
])
def test_every_routing_shape_maps_to_exactly_one_profile(shape, profile):
    assert rc.select_profile(*shape, codex_enabled=True) == profile


@pytest.mark.parametrize("shape", [
    ("codex", "app_server", "plan", False), ("codex", "app_server", None, False),
    ("claude", "claude_cli", "review_lead", False), ("claude", "claude_cli", None, False),
    ("claude", "app_server", "implement", False), ("codex", "claude_cli", None, True),
    ("gemini", "app_server", None, True), ("codex", "app_server", None, "yes"),
])
def test_any_other_shape_refuses_before_spawn(shape):
    with pytest.raises(iw.IsolationError) as refused:
        rc.select_profile(*shape, codex_enabled=True)
    assert refused.value.reason_code == "role_profile_refused"


def test_a_disabled_codex_profile_refuses_and_never_selects_the_host():
    for shape in (("codex", "app_server", None, True), ("codex", "app_server", "implement", False)):
        with pytest.raises(iw.IsolationError) as refused:
            rc.select_profile(*shape, codex_enabled=False)
        assert refused.value.reason_code == "codex_profile_disabled"
    # Claude profiles do not depend on the Codex store.
    assert rc.select_profile("claude", "claude_cli", "implement", False, codex_enabled=False) == rc.CLAUDE_IMPL_RW


def test_every_packaged_policy_pair_and_the_default_provider_have_a_profile():
    from codex_harness.routing.adapters.provider_policy import packaged_policy

    policy = packaged_policy()
    shapes = set()
    for rule in policy.assignments:
        provider = policy.providers[rule["provider"]]
        for action in rule["actions"]:
            shapes.add((rule["provider"], provider.transport, action, rule["read_only"]))
    default = policy.providers[policy.default_provider]
    # The default provider runs every read-only role and the writable implementation.
    shapes |= {(policy.default_provider, default.transport, None, True),
               (policy.default_provider, default.transport, "implement", False)}
    for provider, transport, action, read_only in sorted(shapes, key=repr):
        if not read_only and action != "implement":
            continue  # no writable non-implementation execution exists in the executor
        assert rc.select_profile(provider, transport, action, read_only, codex_enabled=True) in rc.PROFILES


def test_isolation_identity_is_unchanged_without_a_codex_store_and_binds_it_when_set(store):
    base = {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE}
    legacy = iw.load_isolation(base)
    assert "codex" not in legacy
    body = {key: legacy[key] for key in ("mode", "image", "limits", "driver_sha256", "protocol", "network")}
    from codex_harness.kernel.ids import digest
    assert legacy["digest"] == digest(body)
    bound = iw.load_isolation({**base, "ZEUS_CODEX_CREDENTIAL_STORE": str(store)})
    assert bound["codex"] == {"credential_store": str(store)} and bound["digest"] != legacy["digest"]
    for bad in ("relative/store", str(store) + "/../x", "/a,b"):
        with pytest.raises(iw.IsolationError):
            iw.load_isolation({**base, "ZEUS_CODEX_CREDENTIAL_STORE": bad})


# ---- (f)2: create -> inspect -> record -> start, per-profile control checks ----------------------
def controls(**tamper):
    body = {"image": IMAGE, "user": "1000:1000", "network": "bridge", "read_only": True, "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"], "memory": 1, "nano_cpus": 1, "pids_limit": 1, "privileged": False,
            "ports": {}, "labels": {iw.LABEL: "run1"}, "pid_mode": "", "ipc_mode": "private", "cap_add": None,
            "devices": [], "mounts": [{"Type": "bind", "Source": "/x/ws", "Destination": iw.WORKSPACE, "RW": False},
                                      {"Type": "bind", "Source": "/x/res", "Destination": rc.RESULT, "RW": True}]}
    return {**body, **tamper}


@pytest.mark.parametrize("tamper", [
    {"mounts": [{"Type": "bind", "Source": "/x/ws", "Destination": iw.WORKSPACE, "RW": True},
                {"Type": "bind", "Source": "/x/res", "Destination": rc.RESULT, "RW": True}]},
    {"mounts": controls()["mounts"] + [{"Type": "bind", "Source": "/var/run/docker.sock",
                                        "Destination": "/var/run/docker.sock", "RW": True}]},
    {"mounts": [{"Type": "bind", "Source": str(Path.home()), "Destination": iw.WORKSPACE, "RW": False},
                controls()["mounts"][1]]},
    {"pid_mode": "host"}, {"ipc_mode": "host"}, {"userns_mode": "host"}, {"network": "host"},
    {"cap_add": ["SYS_ADMIN"]}, {"devices": [{"PathOnHost": "/dev/kmsg"}]}, {"user": "0:0"}, {"user": ""},
    {"security_opt": []}, {"privileged": True}, {"read_only": False}, {"ports": {"80/tcp": [{}]}},
])
def test_inspect_refuses_any_mode_or_forbidden_socket_home_host_flag(tamper, monkeypatch):
    owned = iw.OwnedContainer({"image": IMAGE, "limits": iw.LIMITS}, "docker", "run1", "codex")
    owned.id = "e" * 64
    monkeypatch.setattr(owned, "inspect", lambda: controls(**tamper))
    with pytest.raises(iw.IsolationError, match="container_controls_mismatch"):
        owned.verify({iw.WORKSPACE: False, rc.RESULT: True}, "bridge")
    monkeypatch.setattr(owned, "inspect", lambda: controls())
    assert owned.verify({iw.WORKSPACE: False, rc.RESULT: True}, "bridge")["user"] == "1000:1000"


def test_bind_modes_are_explicit_and_a_comma_path_refuses():
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    args = iw.container_args(config, name="n", run_id="r", role="codex", network="bridge",
                             mounts=[("/src/a", "/workspace", True), ("/src/b", "/result")], environment={},
                             pass_names=(), entry=["/usr/local/bin/codex", "app-server"], workdir="/workspace")
    assert "type=bind,source=/src/a,target=/workspace,readonly=true" in args
    assert "type=bind,source=/src/b,target=/result" in args
    with pytest.raises(ContractError):
        iw.container_args(config, name="n", run_id="r", role="codex", network="bridge", mounts=[("/a,b", "/x")],
                          environment={}, pass_names=(), entry=["x"], workdir="/")


def test_codex_role_ro_runs_the_app_server_inside_its_verified_container(config, tmp_path, store, candidate, fake):
    result = run_codex(config, tmp_path, store, candidate, fake)
    [create] = fake.created()
    args = create["args"]
    # The protocol code is reused: schema-validated answer, thread cwd is the container workspace.
    assert answer_of(result)["cwd"] == iw.WORKSPACE and result["thread_id"] == "thread-1"
    # Entry is the pinned CLI's app-server; the checkout is read-only; only result and home are writable.
    assert args[args.index("--entrypoint") + 1] == rc.CODEX_EXECUTABLE and args[-1] == "app-server"
    assert f"type=bind,source={candidate.resolve()},target={iw.WORKSPACE},readonly=true" in args
    assert any(a.endswith(f"target={rc.CODEX_HOME}/config.toml,readonly=true") for a in args)
    modes = {m["Destination"]: m["RW"] for m in result["isolation"]["container"]["controls"]["mounts"]}
    assert modes == {iw.WORKSPACE: False, rc.RESULT: True, rc.CODEX_HOME: True, rc.CODEX_HOME + "/config.toml": False}
    # Hardening reused unchanged; no socket, no host namespaces, non-root.
    for flag in ("--read-only", "--init", "no-new-privileges"):
        assert flag in args
    assert args[args.index("--cap-drop") + 1] == "ALL" and args[args.index("--network") + 1] == "bridge"
    assert not {"-v", "--privileged", "-p", "--publish", "--pid", "--ipc"} & set(args) and "docker.sock" not in str(args)
    assert args[args.index("--user") + 1] not in ("0", "0:0", "root")
    # Exactly one provider credential: no Claude token by name, value, or in the docker client env.
    assert iw.TOKEN_NAME not in args and CLAUDE_TOKEN not in json.dumps(fake.calls)
    # Ownership lifecycle: durable record before start, confirmed stop, retained evidence, exact removal.
    record = iw.run_records(tmp_path / "runs")[-1]
    states = [step["state"] for step in record["lifecycle"]]
    assert states == ["prepared", "created", "start_requested", "running", "stop_confirmed", "evidence_retained",
                      "removed"]
    assert record["profile"] == rc.CODEX_ROLE_RO and not fake.containers
    isolation = result["isolation"]
    assert isolation["profile"] == rc.CODEX_ROLE_RO and isolation["cli"]["pinned_version"] == rc.CODEX_CLI_VERSION
    assert isolation["cli"]["config_sha256"] == rc.CODEX_CONFIG_SHA256 and isolation["task_state"] == "discarded"


def test_codex_impl_rw_stages_imports_and_keeps_the_same_task_scoped_policy(config, tmp_path, store, candidate, fake):
    result = run_codex(config, tmp_path, store, candidate, fake, mode="workspace", profile=rc.CODEX_IMPL_RW)
    assert (candidate / "kept.txt").read_text() == "edited by codex\n"
    assert result["isolation"]["import"]["modified"] == ["kept.txt"] and result["isolation"]["outcome"] == "imported"
    modes = {m["Destination"]: m["RW"] for m in result["isolation"]["container"]["controls"]["mounts"]}
    assert modes == {iw.WORKSPACE: True, iw.EVIDENCE: True, rc.CODEX_HOME: True, rc.CODEX_HOME + "/config.toml": False}
    [create] = fake.created()
    assert str(candidate.resolve()) not in " ".join(create["args"])  # a staged copy, never the real checkout


def test_a_turn_of_the_other_shape_refuses_before_anything_is_created(config, tmp_path, store, candidate, fake):
    for profile, read_only in ((rc.CODEX_ROLE_RO, False), (rc.CODEX_IMPL_RW, True)):
        with runtime(config, tmp_path, store, profile) as opened, pytest.raises(ContractError):
            opened.run("x", str(candidate), SCHEMA, 30, read_only=read_only)
    assert not fake.created() and not ledger(store)


# ---- (f)3: immutable evidence hand-off after settlement ------------------------------------------
def test_writer_evidence_is_copied_to_the_store_and_the_reviewer_mounts_only_a_verified_copy(tmp_path):
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    evidence = tmp_path / "run" / "evidence"
    (evidence / "session").mkdir(parents=True)
    (evidence / "session" / "receipt.json").write_text('{"hook": "ok"}', encoding="utf-8")
    (evidence / "blob.bin").write_bytes(b"\xff\x00binary")
    (tmp_path / "run" / "inner_result.json").write_text('{"answer": 1}', encoding="utf-8")
    handed = rc.retain_evidence_handoff(artifacts, evidence, "run-1")
    assert handed["files"] == 3 and handed["manifest"].startswith("sha256:")
    unrelated = artifacts.put("another task's artifact", "other")["ref"]
    # The reviewer's prompt names only the manifest; its files are expanded, nothing else is.
    refs = rc.handoff_refs(artifacts.root, ["review of " + handed["manifest"]])
    manifest = json.loads(artifacts._body(handed["manifest"]))
    assert set(refs) == {handed["manifest"], *(entry["ref"] for entry in manifest["files"].values())}
    assert unrelated not in refs
    copy = rc.materialize_handoff({"root": str(artifacts.root), "refs": refs}, tmp_path / "handoff")
    assert copy["target"] == str(artifacts.root) and copy["source"] != str(artifacts.root)
    assert stat.S_IMODE((tmp_path / "handoff").stat().st_mode) == 0o555
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o444 for p in (tmp_path / "handoff").iterdir())
    # A later change to the live store never reaches the reviewer's copy; a tampered source refuses.
    victim = artifacts.root / (refs[0][7:] + ".txt")
    victim.chmod(0o644)
    victim.write_text("tampered")
    with pytest.raises(iw.IsolationError, match="handoff_integrity_failed"):
        rc.materialize_handoff({"root": str(artifacts.root), "refs": refs}, tmp_path / "handoff-2")
    rc.discard_tree(tmp_path / "handoff")
    assert not (tmp_path / "handoff").exists()


def test_a_link_in_the_writer_evidence_refuses_the_handoff_without_escaping(tmp_path):
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    os.symlink("/etc/passwd", evidence / "escape")
    handed = rc.retain_evidence_handoff(FileArtifacts(str(tmp_path / "artifacts")), evidence, "run-2")
    assert handed == {"manifest": None, "refused": "output_link_refused"}


def test_the_reviewer_container_mounts_the_handoff_read_only_at_the_store_path(config, tmp_path, store, candidate,
                                                                                fake):
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    ref = artifacts.put("evidence", "t")["ref"]
    fake.mode = "ok"
    with rc.IsolatedCodexRuntime(config, tmp_path / "runs", profile=rc.CODEX_ROLE_RO,
                                 broker=rc.CodexCredentialBroker(store), state_root=tmp_path / "state",
                                 handoff={"root": str(artifacts.root), "refs": [ref]}) as opened:
        result = opened.run("x", str(candidate), SCHEMA, 30, read_only=True)
    modes = {m["Destination"]: (m["RW"], m["Source"]) for m in result["isolation"]["container"]["controls"]["mounts"]}
    rw, source = modes[str(artifacts.root)]
    assert rw is False and source != str(artifacts.root) and not Path(source).exists()  # per-run copy, discarded
    assert result["isolation"]["handoff"]["refs"] == 1


# ---- (f)4 and RC2-F3: credentials ---------------------------------------------------------------
def test_discriminator_1_writer_state_never_reaches_the_reviewer_and_the_config_is_digest_checked(
        config, tmp_path, store, candidate, fake):
    writer = run_codex(config, tmp_path, store, candidate, fake, mode="history", profile=rc.CODEX_IMPL_RW,
                       state_key="task-1")
    assert writer["isolation"]["task_state"] == "retained_for_same_task"
    reviewer = run_codex(config, tmp_path, store, candidate, fake, mode="ok")
    # A reviewer always starts from a fresh home: only its own credential copy exists at turn time.
    assert answer_of(reviewer)["home"] == ["auth.json"]
    # A mutation of the read-only configuration is a hold (quarantine), never a silent pass.
    with pytest.raises(iw.IsolationError, match="codex_credential_quarantined: config_digest_changed"):
        run_codex(config, tmp_path, store, candidate, fake, mode="config")
    assert rc.CodexCredentialBroker(store).quarantined()["reason"] == "config_digest_changed"


def test_discriminator_2_cli_state_is_no_hold_and_is_kept_only_for_the_same_writable_task(
        config, tmp_path, store, candidate, fake):
    first = run_codex(config, tmp_path, store, candidate, fake, mode="history", profile=rc.CODEX_IMPL_RW,
                      state_key="task-1")
    assert first["isolation"]["credential"]["settlement"] == "unchanged"
    again = run_codex(config, tmp_path, store, candidate, fake, mode="ok", profile=rc.CODEX_IMPL_RW, state_key="task-1")
    assert {"history.jsonl", "sessions", "state_5.sqlite"} <= set(answer_of(again)["home"])
    other = run_codex(config, tmp_path, store, candidate, fake, mode="ok", profile=rc.CODEX_IMPL_RW, state_key="task-2")
    assert answer_of(other)["home"] == ["auth.json"]
    fresh = run_codex(config, tmp_path, store, candidate, fake, mode="ok", profile=rc.CODEX_IMPL_RW)
    assert answer_of(fresh)["home"] == ["auth.json"] and fresh["isolation"]["task_state"] == "discarded"
    with runtime(config, tmp_path, store, rc.CODEX_ROLE_RO) as opened, pytest.raises(ContractError):
        opened.run("x", str(candidate), SCHEMA, 30, read_only=True, state_key="task-1")
    # No per-run home (and so no credential copy) survives any finished run.
    assert not list((tmp_path / "runs").glob("*/codex-home"))
    retained = list((tmp_path / "codex-state").rglob("auth.json"))
    assert retained == [] and all(entry["state"] == "unchanged" for entry in ledger(store))


def test_discriminator_3_a_valid_refresh_persists_atomically_and_is_used_by_the_next_run(
        config, tmp_path, store, candidate, fake):
    before = (store / "auth.json").stat().st_ino
    result = run_codex(config, tmp_path, store, candidate, fake, mode="refresh")
    assert result["isolation"]["credential"]["settlement"] == "written_back"
    body = json.loads((store / "auth.json").read_text())
    assert body["tokens"]["access_token"] == "at-REFRESHED-DUMMY" and body["tokens"]["account_id"] == "acct-dummy-0001"
    assert (store / "auth.json").stat().st_ino != before  # replaced by rename, never edited in place
    assert sorted(os.listdir(store)) == ["auth.json"] and stat.S_IMODE((store / "auth.json").stat().st_mode) == 0o600
    run_codex(config, tmp_path, store, candidate, fake, mode="ok")
    issued = sorted(ledger(store), key=lambda entry: entry["issued_at"])
    assert issued[-1]["issued_sha256"] != issued[0]["issued_sha256"]
    import hashlib
    assert issued[-1]["issued_sha256"] == hashlib.sha256((store / "auth.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("mode,reason", [("identity", "identity_changed"), ("garbage", "refreshed_credential_unparseable")])
def test_discriminator_4_invalid_or_foreign_credential_holds_before_any_next_run(
        mode, reason, config, tmp_path, store, candidate, fake, monkeypatch):
    home = tmp_path / "operator-home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("OPERATOR-SENTINEL")
    monkeypatch.setenv("HOME", str(home))
    original = (store / "auth.json").read_bytes()
    with pytest.raises(iw.IsolationError, match="codex_credential_quarantined: " + reason):
        run_codex(config, tmp_path, store, candidate, fake, mode=mode)
    assert (store / "auth.json").read_bytes() == original
    created = len(fake.created())
    with pytest.raises(iw.IsolationError, match="codex_credential_quarantined"):
        run_codex(config, tmp_path, store, candidate, fake, mode="ok")
    assert len(fake.created()) == created  # refused at admission: nothing created, nothing retried
    # The operator home is never mounted or read: HOME reaches only the docker client's own environment.
    assert "OPERATOR-SENTINEL" not in json.dumps(fake.calls)
    mounts = [a for call in fake.created() for a in call["args"] if a.startswith("type=bind")]
    assert mounts and not [a for a in mounts if str(home) in a or "/.codex" in a]
    assert (home / ".codex" / "auth.json").read_text() == "OPERATOR-SENTINEL"


def test_discriminator_5_broker_death_refuses_until_reconcile_then_settles_the_refresh(
        config, tmp_path, store, candidate, fake, monkeypatch):
    # A run dies after its container started: stop never confirmed, container alive, copy refreshed.
    fake.mode = "refresh"
    monkeypatch.setattr(owned_container.OwnedContainer, "stop", lambda self, window: {"confirmed": False, "killed": False,
                                                                          "status": "running"})
    with pytest.raises(ContractError, match="could not be confirmed"):
        run_codex(config, tmp_path, store, candidate, fake, mode="refresh")
    monkeypatch.undo()
    install_fake(monkeypatch, fake)
    original = (store / "auth.json").read_bytes()
    [entry] = ledger(store)
    assert entry["state"] == "issued"
    # A released lock is not admission: an unsettled prior run refuses EVERY Codex credential user of
    # the store (here a different checkout), and the store stays untouched.
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    (other / "a.txt").write_text("a")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "a")
    with pytest.raises(iw.IsolationError, match="codex_credential_prior_run_unsettled"):
        run_codex(config, tmp_path, store, other, fake, mode="ok")
    assert (store / "auth.json").read_bytes() == original
    # Reconcile refuses while the exact container is present, then proves it gone.
    run_directory = Path(entry["record"]).parent
    assert iw.reconcile(run_directory)["reason"] == "container_still_present"
    for identifier in list(fake.containers):
        fake.containers[identifier]["status"] = "exited"
        del fake.containers[identifier]
    assert iw.reconcile(run_directory)["reconciled"] is True
    result = run_codex(config, tmp_path, store, candidate, fake, mode="ok")
    assert json.loads((store / "auth.json").read_text())["tokens"]["access_token"] == "at-REFRESHED-DUMMY"
    first = [row for row in ledger(store) if row["run_id"] == entry["run_id"]][0]
    assert first["state"] == "written_back" and not Path(first["home"]).exists()
    assert result["isolation"]["credential"]["settlement"] == "unchanged"


def test_concurrent_admission_waits_bounded_then_refuses_without_touching_the_store(store):
    broker = rc.CodexCredentialBroker(store)
    held = broker.admit(wait_seconds=0)
    try:
        started = time.monotonic()
        with pytest.raises(iw.IsolationError, match="codex_credential_busy"):
            rc.CodexCredentialBroker(store).admit(wait_seconds=0.4)
        assert 0.35 <= time.monotonic() - started < 5
    finally:
        held.release()
    rc.CodexCredentialBroker(store).admit(wait_seconds=0).release()


@pytest.mark.parametrize("damage", ["extra_file", "mode", "link", "api_key", "no_tokens", "open_dir"])
def test_an_invalid_store_refuses_admission_by_name(store, damage, tmp_path):
    auth = store / "auth.json"
    if damage == "extra_file":
        (store / "config.toml").write_text("x")
    elif damage == "mode":
        auth.chmod(0o644)
    elif damage == "link":
        target = tmp_path / "elsewhere.json"
        target.write_bytes(auth.read_bytes())
        target.chmod(0o600)
        auth.unlink()
        os.symlink(target, auth)
    elif damage == "api_key":
        auth.write_text(json.dumps({**dummy_auth(), "OPENAI_API_KEY": "sk-DUMMY"}))
    elif damage == "no_tokens":
        auth.write_text(json.dumps({"OPENAI_API_KEY": None}))
    elif damage == "open_dir":
        store.chmod(0o755)
    with pytest.raises(iw.IsolationError):
        rc.CodexCredentialBroker(store).admit(wait_seconds=0)


def test_provider_refusal_is_a_failure_with_no_retry_and_no_fallback_credential(config, tmp_path, store, candidate,
                                                                                  fake):
    original = (store / "auth.json").read_bytes()
    with pytest.raises(ContractError, match="Codex turn failed"):
        run_codex(config, tmp_path, store, candidate, fake, mode="fail_auth")
    assert len(fake.created()) == 1 and not fake.containers
    [entry] = ledger(store)
    assert entry["state"] == "unchanged" and (store / "auth.json").read_bytes() == original
    assert iw.run_records(tmp_path / "runs")[-1]["state"] == "removed"


def test_no_token_reaches_an_argv_record_ledger_or_retained_result(config, tmp_path, store, candidate, fake):
    run_codex(config, tmp_path, store, candidate, fake, mode="refresh")
    secrets = ["rt-DUMMY-NOT-A-TOKEN", "at-DUMMY-NOT-A-TOKEN", "at-REFRESHED-DUMMY", "idt-DUMMY", CLAUDE_TOKEN]
    observed = json.dumps(fake.calls)
    for path in [*(tmp_path / "runs").rglob("*.json"), *rc.CodexCredentialBroker(store).ledger.glob("*.json")]:
        observed += path.read_text("utf-8")
    assert not [secret for secret in secrets if secret in observed]


# ---- F1: the Codex output boundary (DUMMY credentials; FakeDocker and the fake App Server child) ----
def retained_results(tmp_path) -> list:
    return [path.read_text("utf-8") for path in (tmp_path / "runs").rglob("codex_result.json")]


def test_an_echoed_credential_is_redacted_before_the_callback_the_return_and_the_retained_result(
        config, tmp_path, store, candidate, fake):
    events = []
    result = run_codex(config, tmp_path, store, candidate, fake, mode="echo", on_event=events.append)
    [kept] = retained_results(tmp_path)
    for channel in (json.dumps(events), json.dumps(result), kept):
        assert not [value for value in (*ISSUED, JWT) if value in channel]
    [command] = [event for event in events if event["params"].get("item", {}).get("type") == "commandExecution"]
    output = command["params"]["item"]["aggregatedOutput"]
    # Every credential leaf and the JWT-shaped string become fixed markers; ordinary text is untouched.
    assert output.startswith("ordinary output 42\n") and output.count(rc.REDACTED) == 4
    assert output.endswith("\n" + rc.REDACTED_JWT)
    assert result["answer"]["summary"] == f"ordinary answer; echoed {rc.REDACTED} and {rc.REDACTED_JWT}"
    assert json.loads(kept)["answer"] == result["answer"]
    assert result["events"] == events  # the returned events are exactly the forwarded ones


def test_a_credential_in_a_terminal_error_is_redacted_and_never_chained(config, tmp_path, store, candidate, fake):
    with pytest.raises(ContractError, match="Codex turn failed") as caught:
        run_codex(config, tmp_path, store, candidate, fake, mode="echo_error")
    assert rc.REDACTED in str(caught.value) and "rt-DUMMY-NOT-A-TOKEN" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    [entry] = ledger(store)
    assert entry["state"] == "unchanged" and iw.run_records(tmp_path / "runs")[-1]["state"] == "removed"


def test_a_credential_refreshed_during_the_run_is_redacted_when_emitted_afterwards(
        config, tmp_path, store, candidate, fake):
    events = []
    result = run_codex(config, tmp_path, store, candidate, fake, mode="echo_refresh", on_event=events.append)
    channels = json.dumps(events) + json.dumps(result) + "".join(retained_results(tmp_path))
    assert "at-ROTATED-DUMMY-VALUE" not in channels and rc.REDACTED in channels
    assert result["isolation"]["credential"]["settlement"] == "written_back"


def test_a_credential_split_across_streamed_fragments_is_never_forwarded_piecewise(
        config, tmp_path, store, candidate, fake):
    events = []
    result = run_codex(config, tmp_path, store, candidate, fake, mode="echo_stream", on_event=events.append)
    deltas = [event["params"]["delta"] for event in events if event["method"] == "item/agentMessage/delta"]
    assert deltas == ["prefix ", "", "", rc.REDACTED + " suffix"]
    assert [event for event in result["events"] if event["method"] == "item/agentMessage/delta"] == \
        [event for event in events if event["method"] == "item/agentMessage/delta"]


def test_ordinary_output_passes_the_boundary_unchanged(config, tmp_path, store, candidate, fake):
    events = []
    result = run_codex(config, tmp_path, store, candidate, fake, on_event=events.append)
    [message] = [event for event in events if event["method"] == "item/completed"]
    assert json.loads(message["params"]["item"]["text"]) == result["answer"]
    assert answer_of(result)["cwd"] == iw.WORKSPACE and result["events"] == events
    assert "REDACTED" not in json.dumps(events) + json.dumps(result) + "".join(retained_results(tmp_path))


def test_the_scrubber_redacts_jwt_shapes_keeps_ordinary_text_and_refuses_an_unreadable_set(tmp_path):
    path = tmp_path / "auth.json"
    issued = json.dumps(dummy_auth()).encode("utf-8")
    path.write_bytes(issued)
    path.chmod(0o600)
    scrubber = rc.CredentialScrubber(issued, path)
    ordinary = {"text": "ordinary e", "count": 1, "rows": ["eyJ is not a token", "a.b.c", "2026-09-29T00:00:00Z"]}
    assert scrubber.scrub(ordinary) == ordinary
    assert scrubber.text("token " + JWT + " end") == "token " + rc.REDACTED_JWT + " end"

    def delta(text):
        return scrubber.event({"method": "item/agentMessage/delta", "params": {"itemId": "m", "delta": text}})
    assert [delta(text)["params"]["delta"] for text in ("hello ", "world")] == ["hello ", "world"]
    assert [delta(text)["params"]["delta"] for text in (" " + JWT[:10], JWT[10:25], JWT[25:] + ".")] == \
        [" ", "", rc.REDACTED_JWT + "."]
    path.write_text("{not json")
    with pytest.raises(rc.OutputUnsanitizable, match="codex_output_secret_set_unavailable: credential_unparseable") as caught:
        delta("x")
    assert "not json" not in str(caught.value)


@pytest.mark.parametrize("mode,hold", [("garbage", "refreshed_credential_unparseable"),
                                       ("unreadable", "per_run_credential_file_mode")])
def test_an_unreadable_or_malformed_per_run_credential_refuses_without_persisting_output(
        mode, hold, config, tmp_path, store, candidate, fake):
    events = []
    original = (store / "auth.json").read_bytes()
    with pytest.raises(iw.IsolationError, match="codex_credential_quarantined: " + hold) as caught:
        run_codex(config, tmp_path, store, candidate, fake, mode=mode, on_event=events.append)
    assert isinstance(caught.value.__cause__, rc.OutputUnsanitizable)
    assert caught.value.__cause__.reason_code == "codex_output_secret_set_unavailable"
    # Nothing was forwarded, returned or retained; the store is held untouched.
    assert events == [] and retained_results(tmp_path) == []
    assert rc.CodexCredentialBroker(store).quarantined()["reason"] == hold
    assert (store / "auth.json").read_bytes() == original


def test_claude_profiles_never_mount_or_name_the_codex_credential(tmp_path, store):
    mounts, expected = iw.read_only_mounts("/review/checkout", "/run/evidence")
    environment = iw.worker_environment()
    assert expected == {iw.WORKSPACE: False, iw.EVIDENCE: True}
    assert not [m for m in mounts if str(store) in m[0] or m[1].startswith(rc.CODEX_HOME)]
    assert not [name for name in environment if "CODEX" in name or "OPENAI" in name]
    assert not [name for name in rc.codex_environment() if "CLAUDE" in name or "ANTHROPIC" in name]


def test_the_host_app_server_gets_an_allow_listed_environment_only(monkeypatch):
    from m7_containers import app_server

    spawned = {}

    class Popen:
        def __init__(self, argv, **kwargs):
            spawned.update(argv=argv, env=kwargs["env"])
            raise RuntimeError("stop before any process")
    # Adaptation: the target host App Server creates its process through the injected chokepoint port
    # (`processes.popen`), not `subprocess.Popen`; the fixture stands in for that port.
    processes = SimpleNamespace(popen=lambda argv, **kwargs: Popen(argv, **kwargs))
    for name, value in (("CLAUDE_CODE_OAUTH_TOKEN", CLAUDE_TOKEN), ("HARNESS_DATABASE_URL", "postgresql://u:" + "DUMMY@h/db"),
                        ("ZEUS_REDIS_URL", "redis://:" + "DUMMY@h"), ("GITHUB_TOKEN", "ghp_DUMMY"),
                        ("OPENAI_API_KEY", "sk-DUMMY"), ("ZEUS_CODEX_CREDENTIAL_STORE", "/srv/x")):
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        app_server.AppServer(executable="codex-fixture", processes=processes).__enter__()
    assert set(spawned["env"]) <= set(app_server.HOST_ENVIRONMENT) and "PATH" in spawned["env"]
    assert "DUMMY" not in json.dumps(spawned["env"]) and CLAUDE_TOKEN not in json.dumps(spawned["env"])


# ---- (f)5: failure, timeout, process death, partial spawn, resume --------------------------------
def test_timeout_stops_the_container_settles_the_copy_and_is_never_success(config, tmp_path, store, candidate, fake):
    started = time.monotonic()
    with pytest.raises(ContractError, match="budget exceeded"):
        run_codex(config, tmp_path, store, candidate, fake, mode="sleep", timeout=2)
    assert time.monotonic() - started < 60 and not fake.containers
    assert fake.process.poll() is not None  # the attached client tree is gone
    record = iw.run_records(tmp_path / "runs")[-1]
    assert record["state"] == "removed" and "stop_confirmed" in [s["state"] for s in record["lifecycle"]]
    assert ledger(store)[0]["state"] == "unchanged" and not list((tmp_path / "runs").glob("*/codex-home"))


def test_process_death_is_a_failure_after_entry_with_one_container(config, tmp_path, store, candidate, fake):
    with pytest.raises(ContractError, match="exited unexpectedly"):
        run_codex(config, tmp_path, store, candidate, fake, mode="exit")
    assert len(fake.created()) == 1 and not fake.containers and ledger(store)[0]["state"] == "unchanged"


def test_cancellation_by_the_lease_heartbeat_stops_the_container(config, tmp_path, store, candidate, fake):
    calls = []

    def tick():
        calls.append(1)
        if len(calls) > 3:
            raise ContractError("Execution lease lost (fixture)")
    with pytest.raises(ContractError, match="lease lost"):
        run_codex(config, tmp_path, store, candidate, fake, mode="sleep", on_tick=tick)
    assert not fake.containers and iw.run_records(tmp_path / "runs")[-1]["state"] == "removed"


def test_partial_spawn_refuses_settles_and_discards_the_copy(config, tmp_path, store, candidate, fake):
    fake.tamper = {"pid_mode": "host"}
    with pytest.raises(iw.IsolationError, match="container_controls_mismatch"):
        run_codex(config, tmp_path, store, candidate, fake)
    record = iw.run_records(tmp_path / "runs")[-1]
    assert record["state"] == "refused" and not fake.containers
    assert ledger(store)[0]["state"] == "unchanged" and not list((tmp_path / "runs").glob("*/codex-home"))
    fake.tamper = {}
    assert run_codex(config, tmp_path, store, candidate, fake)["isolation"]["outcome"] == "reviewed"


def test_an_unresolved_run_refuses_the_next_run_so_resume_never_duplicates(config, tmp_path, store, candidate, fake,
                                                                            monkeypatch):
    monkeypatch.setattr(owned_container.OwnedContainer, "remove", lambda self: {"removed": False, "exit_code": 1})
    run_codex(config, tmp_path, store, candidate, fake)
    monkeypatch.undo()
    install_fake(monkeypatch, fake)
    created = len(fake.created())
    with pytest.raises(iw.IsolationError, match="isolation_unresolved_run"):
        run_codex(config, tmp_path, store, candidate, fake)
    assert len(fake.created()) == created


def test_the_image_pins_both_clis_with_a_digest_check():
    text = (ROOT / "Dockerfile.worker").read_text("utf-8")
    assert f"@openai/codex@{rc.CODEX_CLI_VERSION}" in text and f"CODEX_CLI_SHA256={rc.CODEX_CLI_SHA256}" in text
    assert 'sha256sum -c -' in text and "@anthropic-ai/claude-code@2.1.280" in text
    copies = [line for line in text.splitlines() if line.startswith(("COPY", "ADD"))]
    assert not [line for line in copies if "auth.json" in line or "/.codex" in line or ".credentials" in line]


# ---- executor wiring: BOTH transports stubbed, the unexpected one raises ---------------------------
class Unexpected:
    def __init__(self, *args, **kwargs):
        pytest.fail("an unstubbed host transport would be a real provider call")


class Recorded:
    enters_on_open = False

    def __init__(self, sink, **kwargs):
        self.sink, self.kwargs = sink, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, prompt, cwd, schema, timeout, **kwargs):
        self.sink.append({"prompt": json.loads(prompt), "cwd": cwd, "kwargs": kwargs, "opened": self.kwargs})
        kwargs["on_enter"]()
        return {"answer": {"accepted": True}, "events": [], "thread_id": "t", "usage": None, "rotate": False,
                "interrupted": False, "requested_model": kwargs.get("model"),
                "isolation": {"profile": self.kwargs.get("profile"), "record": None}}


def executor_with(tmp_path, monkeypatch, config, sink):
    monkeypatch.setattr("m7_executor.AppServer", Unexpected)
    monkeypatch.setattr("m7_executor.ClaudeCodeRuntime", Unexpected)
    isolation = SimpleNamespace(config=config, inspector=lambda *a: None,
                                codex_runtime=lambda **kwargs: Recorded(sink, **kwargs),
                                runtime=lambda **kwargs: Recorded(sink, **kwargs))
    checkout = tmp_path / "review"
    checkout.mkdir(exist_ok=True)
    git = SimpleNamespace(repository=tmp_path, root=checkout,
                          _git=lambda *args, **kwargs: "" if args[:1] == ("status",) else "f" * 40)
    executor = m7_executor.Executor(m7_executor.Service(MemoryStore()), git, FileArtifacts(str(tmp_path / "artifacts")),
                        isolation=isolation)
    return executor, checkout


VERDICT_SCHEMA = {"type": "object", "properties": {"accepted": {"type": "boolean"}}, "required": ["accepted"]}


def test_executor_runs_a_codex_review_in_codex_role_ro_with_container_reader_paths(tmp_path, monkeypatch, config):
    sink = []
    executor, checkout = executor_with(tmp_path, monkeypatch, config, sink)
    manifest = executor.artifacts.put(json.dumps({"kind": rc.HANDOFF_KIND, "run_id": "w", "files": {}}), "m")["ref"]
    evidence = {"candidate": {"revision": "a" * 40}, "isolation": {"evidence_handoff": {"manifest": manifest}}}
    result = executor._run("lead:improvement", "review-1", "Evaluate review_lead", evidence, str(checkout),
                           VERDICT_SCHEMA, True, workload="final_validation")
    [call] = sink
    assert call["opened"]["profile"] == rc.CODEX_ROLE_RO and result["accepted"] is True
    receipt = json.loads(executor.artifacts._body(result["execution_ref"]))
    external = call["prompt"]["required"]["external_context"]
    assert external["reader_argv_prefix"][0] == iw.TRUSTED_PYTHON
    handoff = call["opened"]["handoff"]
    assert handoff["root"] == str(executor.artifacts.root)
    assert external["ref"] in handoff["refs"] and manifest in handoff["refs"]
    assert call["prompt"]["required"]["review_context"]["cwd"] == iw.WORKSPACE
    assert receipt["invocation"]["request"]["isolation"]["profile"] == rc.CODEX_ROLE_RO


def test_executor_refuses_codex_under_isolation_without_a_store_before_any_transport(tmp_path, monkeypatch):
    sink = []
    bare = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    executor, checkout = executor_with(tmp_path, monkeypatch, bare, sink)
    with pytest.raises(iw.IsolationError, match="codex_profile_disabled"):
        executor._run("lead:improvement", "review-2", "Evaluate", {"x": 1}, str(checkout), VERDICT_SCHEMA, True,
                      workload="final_validation")
    assert sink == []


def test_executor_refuses_active_native_hooks_in_a_codex_container(tmp_path, monkeypatch, config):
    pytest.skip("S3b declared change (design v2 §5.4): the target runs active native hooks in the codex container instead of the M7 refusal; M7 adapters/hooks.NativeHooks is S8")
    sink = []
    executor, checkout = executor_with(tmp_path, monkeypatch, config, sink)
    monkeypatch.setattr("codex_harness.adapters.executor.NativeHooks.configuration",
                        lambda self: {"PreToolUse": [{"matcher": "*", "hooks": []}]})
    with pytest.raises(iw.IsolationError, match="codex_container_native_hooks_unsupported"):
        executor._run("lead:improvement", "review-3", "Evaluate", {"x": 1}, str(checkout), VERDICT_SCHEMA, True,
                      workload="final_validation")
    assert sink == []


def test_executor_hands_off_writer_evidence_after_the_transport_returns(tmp_path, monkeypatch, config):
    sink = []
    executor, checkout = executor_with(tmp_path, monkeypatch, config, sink)
    run = tmp_path / "isolated" / "runs" / "r1"
    (run / "evidence").mkdir(parents=True)
    (run / "evidence" / "receipt.json").write_text("{}", encoding="utf-8")

    class Writer(Recorded):
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            result = super().run(prompt, cwd, schema, timeout, **kwargs)
            return {**result, "answer": {"summary": "done"},
                    "isolation": {"profile": rc.CODEX_IMPL_RW, "record": str(run / "run.json"), "run_id": "r1"}}
    executor.isolation.codex_runtime = lambda **kwargs: Writer(sink, **kwargs)
    result = executor._run("worker:implementation", "impl-1", "Implement", {"plan": {"objective": "o"}},
                           str(checkout), SCHEMA, False, workload="implementation", action="implement")
    assert sink[0]["opened"]["profile"] == rc.CODEX_IMPL_RW
    receipt = executor.artifacts._body(result["execution_ref"])
    handed = json.loads(receipt)["isolation"]["evidence_handoff"]
    assert handed["files"] == 1 and executor.artifacts._body(handed["manifest"])
    # The reviewer that later names only this writer's receipt receives the manifest and its files.
    refs = rc.handoff_refs(executor.artifacts.root, ["worker result " + result["execution_ref"]])
    assert handed["manifest"] in refs and len(refs) == 3


# ---- (f)6: the viewer listener never serves the desk ---------------------------------------------
def test_the_viewer_web_service_refuses_to_start_with_a_desk_revision():
    from codex_harness.composition import monitor

    assert monitor.listener_refusal("web", None, "a" * 40, viewer=8787).startswith("monitor web refuses")
    assert monitor.listener_refusal("web", None, None, viewer=8787) is None
    assert monitor.listener_refusal("desk", 8788, "a" * 40, viewer=8787) is None
    for port, viewer in ((None, 8787), (8787, 8787), (8790, 8790), (8787, 8790)):
        assert "own --port" in monitor.listener_refusal("desk", port, "a" * 40, viewer=viewer)
    assert "needs ZEUS_DESK_REVISION" in monitor.listener_refusal("desk", 8788, "", viewer=8787)
    assert monitor.viewer_port({"ZEUS_AIBOX_WEB_PORT": "8790"}) == 8790 and monitor.viewer_port({}) == 8787


def test_serve_refuses_a_desk_on_the_viewer_port_before_binding(tmp_path, monkeypatch):
    from codex_harness.observation.adapters import viewer_http as monitoring_web

    monkeypatch.setattr(monitoring_web, "ThreadingHTTPServer", Unexpected)
    with pytest.raises(ValueError, match="never served on the viewer listener"):
        monitoring_web.serve(tmp_path / "snapshot.json", 8787, desk=object())
    with pytest.raises(ValueError):
        monitoring_web.serve(tmp_path / "snapshot.json", 8790, desk=object(), viewer_port=8790)


def test_monitor_web_main_refuses_before_any_listener_when_the_desk_is_configured(tmp_path, monkeypatch):
    from codex_harness.entry.processes import monitor

    monkeypatch.setattr(monitor, "settings", lambda: {"ZEUS_DESK_REVISION": "a" * 40})
    monkeypatch.setattr(sys, "argv", ["zeus-monitor", "web"])
    monkeypatch.setattr("codex_harness.observation.adapters.viewer_http.ThreadingHTTPServer", Unexpected)
    with pytest.raises(SystemExit, match="refuses to start"):
        monitor.main()


# ---- Docker-backed denial fixtures (disposable, labelled, never a provider) -----------------------
REAL_IMAGE = os.environ.get("ZEUS_TEST_WORKER_IMAGE", "")
REAL_CODEX_IMAGE = os.environ.get("ZEUS_TEST_CODEX_IMAGE", "")
needs_docker = pytest.mark.skipif(shutil.which("docker") is None or not iw.IMAGE.fullmatch(REAL_IMAGE),
                                  reason="owner check: needs Docker and ZEUS_TEST_WORKER_IMAGE=sha256:<id>")
needs_codex_image = pytest.mark.skipif(shutil.which("docker") is None or not iw.IMAGE.fullmatch(REAL_CODEX_IMAGE),
                                       reason="owner check: needs Docker and ZEUS_TEST_CODEX_IMAGE=sha256:<id> "
                                              "(an image with the pinned codex at /usr/local/bin/codex)")
PROBE = r'''
out() { printf '%s=%s\n' "$1" "$2"; }
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && out claude_token present || out claude_token absent
env | grep -q DUMMY-STORE-SECRET && out store_secret_env present || out store_secret_env absent
[ -e "$STORE_PATH" ] && out store_path visible || out store_path absent
grep -rqs DUMMY-STORE-SECRET /workspace /result /evidence /codex-home /home /tmp /srv /root /mnt /run /var 2>/dev/null && out store_secret_bytes found || out store_secret_bytes absent
[ -e /codex-home/auth.json ] && out codex_auth present || out codex_auth absent
(echo x > /workspace/probe) 2>/dev/null && out workspace_write allowed || out workspace_write denied
(echo x > /codex-home/config.toml) 2>/dev/null && out config_write allowed || out config_write denied
[ -S /var/run/docker.sock ] || [ -S /run/docker.sock ] && out socket present || out socket absent
[ -e "$HOST_HOME/.claude" ] || [ -e "$HOST_HOME/.codex" ] && out host_home visible || out host_home absent
out uid "$(id -u)"
'''


def probe(config, tmp_path, run_id, role, mounts, expected, environment, pass_names, client_env):
    owned = iw.OwnedContainer(config, "docker", run_id, role)
    args = iw.container_args(config, name=owned.name, run_id=run_id, role=role, network="none", mounts=mounts,
                             environment=environment, pass_names=pass_names, entry=["/bin/sh", "-c", PROBE],
                             workdir="/")
    owned.create(args, client_env)
    try:
        owned.verify(expected, "none")
        shown = subprocess.run(["docker", "start", "--attach", owned.id], capture_output=True, text=True, timeout=120)
        assert owned.stop(30)["confirmed"]
        return dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
    finally:
        assert owned.remove()["removed"]


@needs_docker
def test_real_codex_role_ro_cannot_read_claude_or_store_secrets_write_its_checkout_or_reach_a_socket(
        tmp_path, store, candidate):
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": REAL_IMAGE,
                                "ZEUS_CODEX_CREDENTIAL_STORE": str(store)})
    secrets = tmp_path / "srv-secrets"
    secrets.mkdir()
    (secrets / "pg_password").write_text("DUMMY-STORE-SECRET")
    opened = rc.IsolatedCodexRuntime(config, tmp_path / "runs", profile=rc.CODEX_ROLE_RO,
                                     broker=rc.CodexCredentialBroker(store))
    admission = opened.broker.admit(wait_seconds=0)
    try:
        run_id = os.urandom(16).hex()
        run_directory = tmp_path / "runs" / run_id
        run_directory.mkdir(parents=True)
        opened.container = iw.OwnedContainer(config, "docker", run_id, "codex")
        opened.record_path = run_directory / "run.json"
        prepared = opened._prepare(admission, str(candidate.resolve()), run_directory, True, None, None)
        environment = {**rc.codex_environment(), "STORE_PATH": str(secrets), "HOST_HOME": str(Path.home())}
        client = iw.docker_environment({**os.environ, iw.TOKEN_NAME: CLAUDE_TOKEN})
        seen = probe(config, tmp_path, run_id, "codex", prepared["mounts"], prepared["expected"], environment, (),
                     client)
    finally:
        admission.settle()
        admission.release()
        rc.discard_tree(tmp_path / "runs" / run_id / "codex-home")
    assert seen == {"claude_token": "absent", "store_secret_env": "absent", "store_path": "absent",
                    "store_secret_bytes": "absent", "codex_auth": "present", "workspace_write": "denied",
                    "config_write": "denied", "socket": "absent", "host_home": "absent", "uid": str(os.getuid())}
    assert git(candidate, "status", "--porcelain") == ""


@needs_docker
def test_real_claude_profiles_cannot_read_the_codex_auth(tmp_path, store, candidate):
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": REAL_IMAGE})
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    environment = {**iw.worker_environment(), "STORE_PATH": str(store), "HOST_HOME": str(Path.home())}
    client = iw.docker_environment({**os.environ, iw.TOKEN_NAME: CLAUDE_TOKEN}, token=True)
    mounts, expected = iw.read_only_mounts(str(candidate.resolve()), str(evidence.resolve()))
    role = probe(config, tmp_path, os.urandom(16).hex(), "worker", mounts, expected, environment, (iw.TOKEN_NAME,),
                 client)
    staging = tmp_path / "staging"
    staging.mkdir()
    impl = probe(config, tmp_path, os.urandom(16).hex(), "worker",
                 [(str(staging.resolve()), iw.WORKSPACE), (str(evidence.resolve()), iw.EVIDENCE)],
                 {iw.WORKSPACE: True, iw.EVIDENCE: True}, environment, (iw.TOKEN_NAME,), client)
    for seen, writable in ((role, "denied"), (impl, "allowed")):
        # Exactly one provider credential (the Claude token by name); the Codex store and auth are absent.
        assert seen["claude_token"] == "present" and seen["codex_auth"] == "absent"
        assert seen["store_path"] == "absent" and seen["socket"] == "absent" and seen["host_home"] == "absent"
        assert seen["workspace_write"] == writable


@needs_codex_image
def test_real_codex_app_server_starts_in_its_container_and_cleans_up_without_any_network(tmp_path, store, candidate):
    """No provider: `--network none`, a DUMMY auth copy and a turn that cannot reach anything. The run must
    end as a failure (never success) with the container removed and the copy settled unchanged."""
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": REAL_CODEX_IMAGE,
                                "ZEUS_CODEX_CREDENTIAL_STORE": str(store)})
    opened = rc.IsolatedCodexRuntime(config, tmp_path / "runs", profile=rc.CODEX_ROLE_RO,
                                     broker=rc.CodexCredentialBroker(store), network="none")
    entered = []
    original = (store / "auth.json").read_bytes()
    with opened, pytest.raises(ContractError):
        opened.run("Reply with a summary.", str(candidate), SCHEMA, 20, read_only=True,
                   on_enter=lambda: entered.append(1))
    record = iw.run_records(tmp_path / "runs")[-1]
    states = [step["state"] for step in record["lifecycle"]]
    assert entered == [1] and states[:4] == ["prepared", "created", "start_requested", "running"]
    assert record["state"] == "removed"
    listed = subprocess.run(["docker", "ps", "-a", "--filter", "label=" + iw.LABEL + "=" + record["run_id"],
                             "--format", "{{.ID}}"], capture_output=True, text=True, timeout=60).stdout.split()
    assert listed == []
    [entry] = rc.CodexCredentialBroker(store).entries()
    assert entry["state"] == "unchanged" and (store / "auth.json").read_bytes() == original
    assert not list((tmp_path / "runs").glob("*/codex-home"))


def test_nothing_here_used_a_thread_that_outlived_its_test():
    assert all(thread.daemon or thread is threading.main_thread() for thread in threading.enumerate())
