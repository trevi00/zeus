"""S3 labelled Docker fixture suite (REBUILD-DESIGN-v2 §5.3 S3 slice exit: "labelled Docker fixture suite
green (fixture binaries, --network none)").

The target's ONE docker create composer (`execution.domain.container_spec.container_args`) builds the
controls of each role-profile mount layout; the fixture container runs a shell probe from the admitted
fixture image instead of a provider CLI, under a guard-admitted name and the owned-fixture label, with
`--network none`, binds only under the fixture bind root, and is removed by name. The kernel's and the
daemon's view is then checked: non-root, no capabilities, no-new-privileges, read-only rootfs, exactly
the declared bind modes, no socket, no host network, no operator home, and the inspected controls pass the
target's forbidden-control rule. No provider, credential or network is used; DUMMY bytes only.

Runs only when the default-deny guard admits Docker (`ZEUS_TEST_DOCKER=1`, a bind root, the fixture
image present): `python compare/run.py docker-fixture` (and the CI integration job) sets that up.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from codex_harness.execution.adapters.containers import owned_container as oc
from codex_harness.execution.domain import container_spec as spec

IMAGE = os.environ.get("ZEUS_TEST_S3_FIXTURE_IMAGE", "redis:7.4-alpine")
BIND_ROOT = os.environ.get("ZEUS_TEST_DOCKER_BIND_ROOT", "")
FIXTURE_LABEL = "zeus.test.fixture=1"


def _image_present() -> bool:
    if os.environ.get("ZEUS_TEST_DOCKER") != "1" or not BIND_ROOT or shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], capture_output=True,
                              text=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _image_present(),
                                reason="needs ZEUS_TEST_DOCKER=1, ZEUS_TEST_DOCKER_BIND_ROOT and the fixture image "
                                       "(python compare/run.py docker-fixture)")

PROBE = r'''
out() { printf '%s=%s\n' "$1" "$2"; }
out uid "$(id -u)"
out cap_eff "$(awk '/^CapEff/ {print $2}' /proc/self/status)"
out no_new_privs "$(awk '/^NoNewPrivs/ {print $2}' /proc/self/status)"
(echo x > /rootfs-probe) 2>/dev/null && out rootfs_write allowed || out rootfs_write denied
(echo x > /tmp/probe) 2>/dev/null && out tmp_write allowed || out tmp_write denied
(echo x > /workspace/probe) 2>/dev/null && out workspace_write allowed || out workspace_write denied
(echo x > "$WRITABLE/probe") 2>/dev/null && out writable_write allowed || out writable_write denied
(echo x > "$READONLY/probe") 2>/dev/null && out readonly_write allowed || out readonly_write denied
[ -S /var/run/docker.sock ] || [ -S /run/docker.sock ] && out socket present || out socket absent
out interfaces "$(ls /sys/class/net | tr '\n' ',')"
[ -e "$HOST_HOME" ] && out host_home visible || out host_home absent
cat /workspace/dummy.txt >/dev/null 2>&1 && out workspace_read allowed || out workspace_read denied
'''


def _argv(config, name, run_id, mounts, environment):
    argv = spec.container_args(config, name=name, run_id=run_id, role="codex", network="none", mounts=mounts,
                               environment=environment, pass_names=(), entry=["/bin/sh", "-c", PROBE], workdir="/",
                               user=oc.host_user())
    assert argv[0] == "create"
    # A fixture run: the same controls, under the guard's owned-fixture name and label, attached.
    return ["run", "--label", FIXTURE_LABEL, *argv[1:]]


def _run_probe(tmp_path, layout):
    root = Path(BIND_ROOT).resolve()
    work = root / ("s3-" + uuid.uuid4().hex[:12])
    (work / "checkout").mkdir(parents=True)
    (work / "checkout" / "dummy.txt").write_text("DUMMY\n", encoding="utf-8")
    (work / "writable").mkdir()
    (work / "readonly").mkdir()
    for path in (work / "checkout", work / "writable", work / "readonly"):
        path.chmod(0o777 if path.name == "writable" else 0o755)
    config = oc.load_host_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "0" * 64})
    config = {**config, "image": IMAGE}
    run_id = uuid.uuid4().hex
    name = "zeus-test-fixture-s3-" + run_id[:16]
    checkout_ro = layout == "checkout_ro"
    mounts = [(str(work / "checkout"), spec.WORKSPACE, True) if checkout_ro else (str(work / "checkout"), spec.WORKSPACE),
              (str(work / "writable"), "/rw"), (str(work / "readonly"), "/ro", True)]
    expected = {spec.WORKSPACE: not checkout_ro, "/rw": True, "/ro": False}
    environment = {"HOME": spec.CONTAINER_HOME, "WRITABLE": "/rw", "READONLY": "/ro", "HOST_HOME": str(Path.home())}
    argv = _argv(config, name, run_id, mounts, environment)
    try:
        shown = subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=180,
                               stdin=subprocess.DEVNULL)
        assert shown.returncode == 0, shown.stderr[-2000:]
        seen = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        inspected = subprocess.run(["docker", "inspect", "--format", spec.INSPECT_FORMAT, name], capture_output=True,
                                   text=True, timeout=60)
        assert inspected.returncode == 0, inspected.stderr[-2000:]
        observed = json.loads(inspected.stdout)
    finally:
        removed = subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)
    assert removed.returncode == 0
    gone = subprocess.run(["docker", "inspect", "--format", "{{.Id}}", name], capture_output=True, text=True, timeout=60)
    assert gone.returncode != 0, "the fixture container must be gone"
    return seen, observed, expected


@pytest.mark.parametrize("layout", ["checkout_ro", "staging_rw"])
def test_the_composed_controls_hold_in_a_real_container(tmp_path, layout):
    seen, observed, expected = _run_probe(tmp_path, layout)
    assert seen["uid"] == oc.host_user().split(":")[0] and seen["uid"] != "0"
    assert int(seen["cap_eff"], 16) == 0 and seen["no_new_privs"] == "1"
    assert seen["rootfs_write"] == "denied" and seen["tmp_write"] == "allowed"
    assert seen["workspace_write"] == ("denied" if layout == "checkout_ro" else "allowed")
    assert seen["workspace_read"] == "allowed" and seen["writable_write"] == "allowed"
    assert seen["readonly_write"] == "denied" and seen["socket"] == "absent" and seen["host_home"] == "absent"
    assert seen["interfaces"].strip(",").split(",") == ["lo"]
    # The daemon applied exactly what the composer declared; the target's rule finds nothing forbidden.
    mounts = [{key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")} for mount in observed["mounts"]]
    assert {m["Destination"]: m["RW"] for m in mounts if m["Type"] == "bind"} == expected
    assert spec.forbidden_controls({**observed, "mounts": mounts}, home=oc.operator_home()) == []
    assert observed["read_only"] is True and observed["network"] == "none" and observed["privileged"] is False
    assert [str(cap).upper() for cap in observed["cap_drop"]] == ["ALL"] and not observed["cap_add"]
    assert "no-new-privileges" in observed["security_opt"] and observed["pids_limit"] == spec.LIMITS["pids"]
    assert observed["labels"][spec.LABEL] and observed["labels"]["zeus.test.fixture"] == "1"


# ---- fix F2 (S3 round 1): the S3b command and mount path, behaviourally, in labelled fixture containers ----
# FIXTURE PROOF ONLY: the image is a labelled fixture (target/tests/fixtures/s3_hook_peer), its `codex` is a
# provider-free peer that runs trusted hooks as the pinned CLI does. This is not a real Codex run, not the
# worker image and not a real-provider verification (that remains later, authorized verification).
PEER_IMAGE = "zeus-test-fixture/s3-hook-peer:1"
PEER_CONTEXT = Path(__file__).resolve().parent / "fixtures" / "s3_hook_peer"
SUCCESS_HOOK = r'''import json, os, socket, sys
event = json.load(sys.stdin)
marker = {"in_container": os.path.exists("/.dockerenv"), "hostname": socket.gethostname(), "cwd": os.getcwd(),
          "interpreter": sys.executable, "script": __file__, "event": event.get("hook_event_name"), "uid": os.getuid()}
open("/result/hook-ran.json", "w").write(json.dumps(marker))
print(json.dumps({"ok": True}))
'''
SLOW_HOOK = r'''import json, sys, time
json.load(sys.stdin)
open("/result/hook-started.json", "w").write("{}")
time.sleep(600)
open("/result/hook-finished.json", "w").write("{}")
'''
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


@pytest.fixture(scope="module")
def peer_image():
    built = subprocess.run(["docker", "build", "--network", "none", "--label", FIXTURE_LABEL, "-t", PEER_IMAGE,
                            str(PEER_CONTEXT)], capture_output=True, text=True, timeout=600)
    assert built.returncode == 0, built.stderr[-3000:]
    return PEER_IMAGE


def _s3b_run(script, *, hook_timeout, budget, monkeypatch):
    from codex_harness.credentials.adapters.codex_custody import CodexCredentialBroker
    from codex_harness.credentials.domain import codex_credential as cc
    from codex_harness.execution.adapters.containers.launcher import AttachedAppServer
    from codex_harness.execution.adapters.providers import native_hooks as nh
    from codex_harness.execution.adapters.providers.codex_app_server import AppServer

    monkeypatch.setattr(nh, "HOOK_TIMEOUT_SECONDS", hook_timeout)  # bounded fixture; production keeps 30 s
    work = Path(BIND_ROOT).resolve() / ("s3b-" + uuid.uuid4().hex[:12])
    workspace, result, home = work / "checkout", work / "result", work / "codex-home"
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("fixture\n", encoding="utf-8")
    result.mkdir()
    result.chmod(0o777)
    store = work / "secrets" / "codex-store"
    store.mkdir(parents=True, mode=0o700)
    auth = {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": {
        "id_token": "idt-DUMMY-FIXTURE", "access_token": "at-DUMMY-FIXTURE", "refresh_token": "rt-DUMMY-FIXTURE",
        "account_id": "acct-dummy-fixture"}}
    (store / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    (store / "auth.json").chmod(0o600)
    original = (store / "auth.json").read_bytes()
    broker = CodexCredentialBroker(store)
    admission = broker.admit(wait_seconds=0)
    record = work / "run.json"
    admission.issue(uuid.uuid4().hex, record, home)
    config_file = work / "codex-config.toml"
    config_file.write_text(cc.CODEX_CONFIG, encoding="utf-8")
    config_file.chmod(0o444)
    digest = __import__("hashlib").sha256(script.encode()).hexdigest()
    hook_set = nh.container_hooks([{"id": "hook-1", "status": "active", "revision": "r" * 40, "spec": {
        "kind": "native_hook", "event": "PreToolUse", "matcher": "shell", "script_path": "harness_hooks/h.py",
        "script_sha256": digest}}], lambda revision, path: script, work / "hooks")
    mounts = [(str(workspace), spec.WORKSPACE, True), (str(result), spec.RESULT), (str(home), cc.CODEX_HOME),
              (str(config_file), cc.CODEX_HOME + "/config.toml", True), (hook_set.source, nh.HOOK_MOUNT, True)]
    config = {**oc.load_host_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "0" * 64}),
              "image": PEER_IMAGE}
    names, observed = [], {}

    def start(state):
        probe = AppServer(executable=cc.CODEX_EXECUTABLE, hooks=hook_set.configuration)
        probe.hook_state = state
        run_id = uuid.uuid4().hex
        name = "zeus-test-fixture-s3b-" + run_id[:16]
        argv = spec.container_args(config, name=name, run_id=run_id, role="codex", network="none", mounts=mounts,
                                   environment=spec.codex_environment(), pass_names=(),
                                   entry=[cc.CODEX_EXECUTABLE, *probe.server_arguments()], workdir=spec.WORKSPACE,
                                   user=oc.host_user())
        names.append(name)
        process = subprocess.Popen(["docker", "run", "--label", FIXTURE_LABEL, *argv[1:]], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        server = AttachedAppServer(process, spec.WORKSPACE)
        server.hooks, server.hook_state = hook_set.configuration, dict(state)
        return name, process, server

    try:
        name, process, server = start({})
        with server:
            state = nh.bound_state(server.request("hooks/list", {"cwds": [spec.WORKSPACE]}, 60)["data"], hook_set)
        process.wait(timeout=60)
        name, process, server = start(state)
        observed["hostname"] = None
        with server:
            rows = server.request("hooks/list", {"cwds": [spec.WORKSPACE]}, 60)["data"]
            observed["statuses"] = nh.verify_bound(rows, hook_set, state)
            shown = subprocess.run(["docker", "inspect", "--format", "{{.Config.Hostname}}", name],
                                   capture_output=True, text=True, timeout=60)
            observed["hostname"] = shown.stdout.strip()
            events = []
            try:
                observed["value"] = server.run("fixture turn", spec.WORKSPACE, SCHEMA, budget, read_only=True,
                                               on_event=events.append)
            except Exception as exc:  # noqa: BLE001 - the refusal is the observation
                observed["failure"] = str(exc)
            observed["hook_events"] = [event["params"] for event in events if event.get("method") == "hook/completed"]
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)
        observed["gone"] = all(subprocess.run(["docker", "inspect", "--format", "{{.Id}}", name], capture_output=True,
                                              text=True, timeout=60).returncode != 0 for name in names)
        record.write_text(json.dumps({"state": "removed"}), encoding="utf-8")
        observed["settlement"] = admission.settle()["state"]
        admission.release()
        observed["store_unchanged"] = (store / "auth.json").read_bytes() == original
        (work / "hooks").chmod(0o755)
    observed["result_files"] = sorted(path.name for path in result.iterdir())
    marker = result / "hook-ran.json"
    observed["marker"] = json.loads(marker.read_text()) if marker.exists() else None
    observed["hook_path"] = hook_set.configuration["PreToolUse"][0]["hooks"][0]["command"]
    return observed


def test_f2_a_bound_hook_runs_inside_the_container_from_the_read_only_digest_path(peer_image, monkeypatch):
    seen = _s3b_run(SUCCESS_HOOK, hook_timeout=20, budget=60, monkeypatch=monkeypatch)
    assert "failure" not in seen and json.loads(seen["value"]["answer"]["summary"])["hooks"][0]["status"] == "completed"
    assert [event["run"]["status"] for event in seen["hook_events"]] == ["completed"]
    assert set(seen["statuses"].values()) == {"trusted"}
    marker = seen["marker"]
    # Container-only: the hook ran in the container (its /.dockerenv, its hostname), under the image's
    # trusted interpreter, from the read-only digest-addressed mount, in the session cwd, as the non-root uid.
    assert marker["in_container"] is True and marker["hostname"] == seen["hostname"]
    assert marker["interpreter"] == spec.TRUSTED_PYTHON and marker["script"].startswith("/zeus-hooks/")
    assert seen["hook_path"].split()[-1] == marker["script"] and marker["cwd"] == spec.WORKSPACE
    assert marker["event"] == "PreToolUse" and str(marker["uid"]) == oc.host_user().split(":")[0]
    # No host invocation: the host has no such interpreter path and no marker was written on the host.
    assert not Path(marker["script"]).exists() and not Path("/result/hook-ran.json").exists()
    assert seen["gone"] and seen["settlement"] == "unchanged" and seen["store_unchanged"]


def test_f2_a_timed_out_hook_never_completes_the_turn_and_the_copy_settles_unchanged(peer_image, monkeypatch):
    seen = _s3b_run(SLOW_HOOK, hook_timeout=2, budget=60, monkeypatch=monkeypatch)
    assert "value" not in seen and "Codex turn failed" in seen["failure"] and "timedOut" in seen["failure"]
    assert [event["run"]["status"] for event in seen["hook_events"]] == ["timedOut"]
    # The hook started inside the container and was killed at its timeout: it never finished.
    assert seen["result_files"] == ["hook-started.json"]
    assert seen["gone"] and seen["settlement"] == "unchanged" and seen["store_unchanged"]
