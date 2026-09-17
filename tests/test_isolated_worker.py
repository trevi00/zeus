"""INV-ISOLATED-WORKER-001. Everything here except the explicitly marked Docker test uses an
INJECTED fake Docker client (`FakeDocker`) and a real local child process that speaks the inner
protocol in place of the attached container. No model, provider or live service is called; none of
these results is an observation of a real container."""
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters import isolated_worker_entry as entry
from codex_harness.adapters import operation_cli
from codex_harness.domain.model import ContractError

IMAGE = "sha256:" + "a" * 64
TOKEN = "sk-ant-oat01-FIXTURE-SECRET-VALUE"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}

INNER = r'''
import json, os, sys, time
mode, staging = sys.argv[1], sys.argv[2]
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
def send(kind, **body):
    sys.stdout.write(json.dumps({"protocol": request["protocol"], "kind": kind, **body}) + "\n"); sys.stdout.flush()
send("entered")
send("event", event={"type": "system", "sequence": 1})
if mode == "sleep":
    time.sleep(120)
if mode == "garbage":
    sys.stdout.write("not json\n"); sys.stdout.flush(); sys.exit(0)
if mode == "truncated":
    sys.exit(0)
with open(os.path.join(staging, "kept.txt"), "w") as handle: handle.write("edited\n")
with open(os.path.join(staging, "new.txt"), "w") as handle: handle.write("added\n")
os.remove(os.path.join(staging, "gone.txt"))
os.makedirs(os.path.join(staging, "__pycache__")); open(os.path.join(staging, "__pycache__", "x.pyc"), "w").close()
if mode == "link":
    os.symlink("/etc/passwd", os.path.join(staging, "escape"))
send("result", result={"answer": {"summary": "done"}, "command": {"cli_version": "2.1.274 (fixture)"}, "thread_id": request["session_id"]})
'''


class FakeDocker:
    """Injected fault/fixture: answers the exact docker argv the adapter composes."""

    def __init__(self, tmp_path, mode="ok"):
        self.calls, self.containers, self.mode, self.process = [], {}, mode, None
        self.lose_create, self.kill_works = False, True
        self.daemon, self.image, self.rm_works = True, True, True
        self.script = tmp_path / "inner.py"
        self.script.write_text(INNER, encoding="utf-8")
        self.containers["f" * 64] = {"name": "zeus-worker-sibling", "labels": {iw.LABEL: "other"}, "status": "exited"}

    def __call__(self, docker, args, *, timeout, env=None):
        self.calls.append({"args": list(args), "env": dict(env or {})})
        done = lambda out="", code=0: subprocess.CompletedProcess(args, code, out, "")  # noqa: E731
        if args[0] == "version":
            return done("29.7.2\n") if self.daemon else done(code=1)
        if args[:2] == ["image", "inspect"]:
            return done(IMAGE + "\n") if self.image else done(code=1)
        if args[0] == "create":
            identifier = format(len(self.containers), "x").rjust(64, "e")
            labels = dict(a.split("=", 1) for i, a in enumerate(args) if args[i - 1] == "--label")
            mounts = [dict(p.split("=", 1) for p in a.split(",")) for i, a in enumerate(args) if args[i - 1] == "--mount"]
            self.containers[identifier] = {"name": args[args.index("--name") + 1], "labels": labels, "mounts": mounts,
                                           "network": args[args.index("--network") + 1], "status": "created", "args": list(args)}
            return done("" if self.lose_create else identifier + "\n", 125 if self.lose_create else 0)
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
            return done(json.dumps({"image": IMAGE, "user": "10001:10001", "network": container["network"], "read_only": True,
                                    "cap_drop": ["ALL"], "security_opt": ["no-new-privileges"], "memory": 1, "nano_cpus": 1,
                                    "pids_limit": 512, "privileged": False, "ports": {}, "labels": container["labels"],
                                    "mounts": [{"Type": "bind", "Source": m["source"], "Destination": m["target"], "RW": True,
                                                "Secret": "never kept"} for m in container["mounts"]]}))
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

    def tree(self):
        fake = self

        class Tree:
            @staticmethod
            def spawn(argv, **kwargs):
                container = fake.containers[argv[-1]]
                container["status"] = "running"
                staging = [m["source"] for m in container["mounts"] if m["target"] == iw.WORKSPACE][0]
                tree = iw_real_tree.spawn([sys.executable, str(fake.script), fake.mode, staging], **kwargs)
                fake.process = tree.process
                return tree
        return Tree


iw_real_tree = iw.ProcessTree


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def candidate(tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, body in (("kept.txt", "original\n"), ("gone.txt", "bye\n"), ("src/pkg/mod.py", "X = 1\n")):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


@pytest.fixture
def config():
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    config["limits"] = {**config["limits"], "inner_grace_seconds": 1, "cleanup_seconds": 2}
    return config


def runtime(config, tmp_path, monkeypatch, fake):
    monkeypatch.setattr(iw, "_docker", fake)
    monkeypatch.setattr(iw, "ProcessTree", fake.tree())
    return iw.IsolatedClaudeRuntime(config, tmp_path / "runs", model="fable", max_budget_usd=1.0,
                                    environment={**os.environ, iw.TOKEN_NAME: TOKEN})


def record(tmp_path):
    return iw.run_records(tmp_path / "runs")[-1]


# ---- configuration and refusals before entry ----------------------------------------------------
def test_absent_configuration_is_host_mode_and_partial_or_unknown_refuses():
    assert iw.load_isolation({}) is None
    for bad in ({"ZEUS_WORKER_ISOLATION": "docker"}, {"ZEUS_WORKER_IMAGE": IMAGE},
                {"ZEUS_WORKER_ISOLATION": "podman", "ZEUS_WORKER_IMAGE": IMAGE},
                {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "zeus-worker:latest"}):
        with pytest.raises(iw.IsolationError) as refused:
            iw.load_isolation(bad)
        assert refused.value.reason_code == "isolation_config_invalid"
    one = iw.load_isolation({"HARNESS_WORKER_ISOLATION": "docker", "HARNESS_WORKER_IMAGE": IMAGE})
    other = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "b" * 64})
    assert one["image"] == IMAGE and one["digest"] != other["digest"]


def test_identity_binds_isolation_only_when_selected(config, tmp_path):
    policy = SimpleNamespace(summary=lambda: {"policy_digest": "p", "config_digest": "c"})
    legacy = operation_cli.identity({}, tmp_path, policy, {}, tmp_path)
    bound = operation_cli.identity({}, tmp_path, policy, {}, tmp_path, isolation=config)
    assert "isolation" not in legacy and {k: v for k, v in bound.items() if k != "isolation"} == legacy
    assert bound["isolation"]["image"] == IMAGE and bound["isolation"]["limits"] == config["limits"]


def test_preflight_refuses_missing_daemon_image_and_token(config, tmp_path, monkeypatch):
    with pytest.raises(iw.IsolationError) as refused:  # real spawn failure of an absent client binary
        iw.preflight(config, str(tmp_path / "no-such-docker"), {iw.TOKEN_NAME: TOKEN})
    assert refused.value.reason_code == "docker_unavailable"
    fake = FakeDocker(tmp_path)
    monkeypatch.setattr(iw, "_docker", fake)
    for attribute, environment, code in (("image", {iw.TOKEN_NAME: TOKEN}, "worker_image_unavailable"),
                                         ("daemon", {iw.TOKEN_NAME: TOKEN}, "docker_unavailable"), (None, {}, "worker_token_missing")):
        fake.daemon = fake.image = True
        if attribute:
            setattr(fake, attribute, False)
        with pytest.raises(iw.IsolationError) as refused:
            iw.preflight(config, "docker", environment)
        assert refused.value.reason_code == code
    assert not any(TOKEN in json.dumps(call) for call in fake.calls)


def test_host_isolation_refuses_project_profile_and_never_builds_host_path(monkeypatch):
    from codex_harness import bootstrap
    monkeypatch.setattr(bootstrap, "settings", lambda: {})
    assert bootstrap.host_isolation() is None
    monkeypatch.setattr(bootstrap, "settings", lambda: {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    with pytest.raises(iw.IsolationError) as refused:
        bootstrap.host_isolation({"profile_digest": "x"})
    assert refused.value.reason_code == "isolation_refuses_project_evidence_profile"


# ---- source validation --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["../x", "/abs", "a\\b", "a/../b", "CON.txt", "dir/aux", "bad:name", "trail. ", "a/.git/config", ""])
def test_unsafe_paths_refuse(name):
    with pytest.raises(iw.IsolationError):
        iw.check_relative_path(name)


def test_bounds_and_case_collisions_refuse(monkeypatch):
    for entries in ([("a/File.txt", 1), ("a/file.TXT", 1)], [("Dir/x", 1), ("dir/y", 1)], [("name", 1), ("NAME/x", 1)]):
        with pytest.raises(iw.IsolationError) as refused:
            iw.check_bounds(entries)
        assert refused.value.reason_code == "source_case_collision"
    assert iw.check_bounds([("a/x", 2), ("a/y", 3)]) == {"files": 2, "bytes": 5}
    with pytest.raises(iw.IsolationError):
        iw.check_bounds([("big", iw.MAX_FILE_BYTES + 1)])
    monkeypatch.setattr(iw, "MAX_FILES", 1)
    with pytest.raises(iw.IsolationError):
        iw.check_bounds([("a", 1), ("b", 1)])
    monkeypatch.setattr(iw, "MAX_FILES", 10)
    monkeypatch.setattr(iw, "MAX_TOTAL_BYTES", 3)
    with pytest.raises(iw.IsolationError):
        iw.check_bounds([("a", 2), ("b", 2)])


def test_symlink_entry_in_the_pinned_tree_refuses_before_materializing(candidate, tmp_path):
    blob = subprocess.run(["git", "-C", str(candidate), "hash-object", "-w", "--stdin"], input=b"/etc/passwd",
                          capture_output=True, check=True).stdout.decode().strip()
    git(candidate, "update-index", "--add", "--cacheinfo", "120000," + blob + ",link")
    git(candidate, "commit", "-q", "-m", "link")
    with pytest.raises(iw.IsolationError) as refused:
        iw.stage_source(candidate, git(candidate, "rev-parse", "HEAD"), tmp_path / "stage")
    assert refused.value.reason_code == "source_entry_unsupported" and not (tmp_path / "stage").exists()


def test_staging_is_a_detached_export_with_a_standalone_repository(candidate, tmp_path):
    stage = tmp_path / "stage"
    source = iw.stage_source(candidate, git(candidate, "rev-parse", "HEAD"), stage)
    assert source["files"] == 3 and (stage / "src/pkg/mod.py").read_bytes() == b"X = 1\n" and not (stage / ".git").exists()
    iw.init_standalone_git(stage)
    assert (stage / ".git").is_dir() and git(stage, "remote") == "" and git(stage, "status", "--porcelain") == ""
    assert iw.plan_import(source["manifest"], stage)["added"] == []  # the staged .git is never an output


# ---- lifecycle ----------------------------------------------------------------------------------
def test_run_imports_additions_edits_deletions_after_confirmed_stop(config, candidate, tmp_path, monkeypatch):
    fake, events, entered = FakeDocker(tmp_path), [], []
    with runtime(config, tmp_path, monkeypatch, fake) as opened:
        result = opened.run("do it", str(candidate), SCHEMA, 20, on_event=events.append, on_enter=lambda: entered.append(
            [c["args"][0] for c in fake.calls]))
    assert result["answer"] == {"summary": "done"} and result["events"] == events and len(events) == 1
    assert entered and "start" not in entered[0] and "create" in entered[0]  # boundary: after create, before start
    assert (candidate / "kept.txt").read_text() == "edited\n" and (candidate / "new.txt").exists()
    assert not (candidate / "gone.txt").exists() and not (candidate / "__pycache__").exists()
    isolation = result["isolation"]
    assert isolation["import"]["added"] == ["new.txt"] and isolation["import"]["deleted"] == ["gone.txt"]
    assert isolation["image"] == IMAGE and isolation["cli_version"].startswith("2.1.274") and isolation["cleanup"]["removed"]
    assert all(set(mount) == {"Type", "Source", "Destination", "RW"} for mount in isolation["container"]["controls"]["mounts"])
    saved = record(tmp_path)
    assert [step["state"] for step in saved["lifecycle"]] == ["prepared", "created", "start_requested", "running",
                                                              "stop_confirmed", "validated", "imported", "evidence_retained", "removed"]
    create = [c for c in fake.calls if c["args"][0] == "create"][0]
    assert create["env"][iw.TOKEN_NAME] == TOKEN and iw.TOKEN_NAME in create["args"]
    assert all(iw.TOKEN_NAME not in c["env"] for c in fake.calls if c["args"][0] != "create")
    for flag in ("--read-only", "--cap-drop", "no-new-privileges", "--memory", "--cpus", "--pids-limit", "--user"):
        assert flag in create["args"]
    assert not any(flag in create["args"] for flag in ("-p", "--publish", "--privileged", "-v")) and "docker.sock" not in str(create)
    assert TOKEN not in json.dumps([c["args"] for c in fake.calls]) + json.dumps(saved) + json.dumps(result)
    assert list(fake.containers) == ["f" * 64]  # own container removed, the sibling untouched
    assert iw.unresolved_runs(tmp_path / "runs") == []


@pytest.mark.parametrize("mode", ["truncated", "garbage"])
def test_lost_protocol_is_never_success_and_imports_nothing(mode, config, candidate, tmp_path, monkeypatch):
    fake, entered = FakeDocker(tmp_path, mode), []
    with runtime(config, tmp_path, monkeypatch, fake) as opened, pytest.raises(ContractError) as failed:
        opened.run("do it", str(candidate), SCHEMA, 20, on_enter=lambda: entered.append(1))
    assert "protocol_result_missing" in str(failed.value) and entered == [1]
    assert (candidate / "kept.txt").read_text() == "original\n" and git(candidate, "status", "--porcelain") == ""
    saved = record(tmp_path)
    assert saved["state"] == "removed" and saved["result"]["isolation"]["outcome"] == "protocol_result_missing"
    assert Path(saved["staging"]).is_dir()  # failed staging preserved with its recovery record


def test_link_in_output_refuses_the_whole_import(config, candidate, tmp_path, monkeypatch):
    probe = tmp_path / "probe"
    try:
        os.symlink("target", probe)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create a symlink fixture")
    with runtime(config, tmp_path, monkeypatch, FakeDocker(tmp_path, "link")) as opened, pytest.raises(ContractError) as failed:
        opened.run("do it", str(candidate), SCHEMA, 20)
    assert "output_link_refused" in str(failed.value)
    assert (candidate / "kept.txt").read_text() == "original\n" and not (candidate / "new.txt").exists()


def test_deadline_kills_the_owned_container_within_the_cleanup_window(config, candidate, tmp_path, monkeypatch):
    fake = FakeDocker(tmp_path, "sleep")  # a real sleeping non-model process stands in for the container
    started = time.monotonic()
    with runtime(config, tmp_path, monkeypatch, fake) as opened, pytest.raises(ContractError):
        opened.run("do it", str(candidate), SCHEMA, 1)
    assert time.monotonic() - started < 1 + 1 + 2 + 30
    assert fake.process.poll() is not None and any(c["args"][0] == "kill" for c in fake.calls)
    assert record(tmp_path)["result"]["isolation"]["stream"]["reason"] == "deadline"


def test_unconfirmed_stop_blocks_and_refuses_the_next_run_until_reconciled(config, candidate, tmp_path, monkeypatch):
    fake = FakeDocker(tmp_path, "sleep")
    fake.kill_works = False  # injected: kill reports nothing and the container stays running
    monkeypatch.setattr(FakeDocker, "__call__", lambda self, docker, args, **kw: (
        subprocess.CompletedProcess(args, 0, "running 0 false\n", "") if args[0] == "inspect" and args[2] != iw.INSPECT_FORMAT
        and self.process is not None else FakeDocker_call(self, docker, args, **kw)))
    with runtime(config, tmp_path, monkeypatch, fake) as opened, pytest.raises(ContractError) as failed:
        opened.run("do it", str(candidate), SCHEMA, 1)
    assert "could not be confirmed" in str(failed.value)
    saved = record(tmp_path)
    assert saved["state"] == "stop_unconfirmed" and saved["lifecycle"][-1]["recovery"]["container"] == saved["container"]
    assert not any(c["args"][0] == "rm" for c in fake.calls)
    entered = []
    with runtime(config, tmp_path, monkeypatch, fake) as again, pytest.raises(iw.IsolationError) as refused:
        again.run("do it", str(candidate), SCHEMA, 1, on_enter=lambda: entered.append(1))
    assert refused.value.reason_code == "isolation_unresolved_run" and entered == []  # refused before entry: no retry
    assert iw.reconcile(Path(saved["record"]).parent)["reason"] == "container_still_present"
    del fake.containers[saved["container"]]
    assert iw.reconcile(Path(saved["record"]).parent) == {"reconciled": True, "run_id": saved["run_id"]}
    assert iw.unresolved_runs(tmp_path / "runs") == []


FakeDocker_call = FakeDocker.__call__


def test_lost_create_response_recovers_only_by_exact_name_and_label(config, tmp_path, monkeypatch):
    fake = FakeDocker(tmp_path)
    fake.lose_create = True
    monkeypatch.setattr(iw, "_docker", fake)
    owned = iw.OwnedContainer(config, "docker", "run1", "worker")
    fake.containers["d" * 64] = {"name": owned.name + "x", "labels": {iw.LABEL: "run1"}, "status": "exited"}
    fake.containers["c" * 64] = {"name": owned.name, "labels": {iw.LABEL: "other"}, "status": "exited"}
    assert owned.recover_id() is None  # same name under another label, or our label under another name: not ours
    args = iw.container_args(config, name=owned.name, run_id="run1", role="worker", network="bridge", mounts=[],
                             environment={}, pass_names=(), entry=["/bin/true"], workdir="/")
    recovered = owned.create(args, {})
    assert fake.containers[recovered]["labels"][iw.LABEL] == "run1" and fake.containers[recovered]["name"] == owned.name
    assert owned.remove()["removed"] and {"c" * 64, "d" * 64, "f" * 64} == set(fake.containers)


def test_failed_removal_keeps_an_exact_recovery_reference(config, candidate, tmp_path, monkeypatch):
    fake = FakeDocker(tmp_path)
    fake.rm_works = False
    with runtime(config, tmp_path, monkeypatch, fake) as opened:
        result = opened.run("do it", str(candidate), SCHEMA, 20)
    saved = record(tmp_path)
    assert result["isolation"]["cleanup"]["recovery"]["container"] == saved["container"]
    assert saved["state"] == "evidence_retained" and len(iw.unresolved_runs(tmp_path / "runs", str(candidate.resolve()))) == 1


# ---- inner entrypoint ---------------------------------------------------------------------------
class FixtureRuntime:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, prompt, cwd, schema, timeout, *, on_event, on_enter, session_id):
        on_enter()
        on_event({"type": "system", "cwd": cwd, "root": self.kwargs["runtime"]["profile_evidence_root"]})
        return {"answer": {"ok": True}, "events": [1, 2, 3], "thread_id": session_id}


def lines(output):
    return [iw.parse_line(line + b"\n", 1 << 20) for line in output.getvalue().splitlines()]


def test_entry_reuses_the_runtime_contract_and_tags_every_line():
    request = {"protocol": iw.PROTOCOL, "prompt": "p", "schema": SCHEMA, "timeout": 5, "model": "fable", "session_id": "s",
               "runtime": {"worker_profile": None}, "cwd": iw.WORKSPACE, "evidence_root": iw.EVIDENCE}
    output = io.BytesIO()
    assert entry.serve(io.BytesIO(json.dumps(request).encode()), output, FixtureRuntime) == 0
    kinds = lines(output)
    assert [m["kind"] for m in kinds] == ["entered", "event", "result"]
    assert kinds[1]["event"] == {"type": "system", "cwd": "/workspace", "root": "/evidence"} and "events" not in kinds[2]["result"]
    refused = io.BytesIO()
    assert entry.serve(io.BytesIO(b"{}"), refused, FixtureRuntime) == 1 and lines(refused)[0]["kind"] == "refused"


def test_protocol_lines_that_are_overlong_unterminated_or_untagged_are_invalid():
    good = json.dumps({"protocol": iw.PROTOCOL, "kind": "event", "event": {}}).encode() + b"\n"
    assert iw.parse_line(good, 1000)["kind"] == "event"
    for bad in (good[:-1], good * 50, b'{"kind":"result","result":{}}\n', b"\xff\n",
                json.dumps({"protocol": iw.PROTOCOL, "kind": "result", "result": "text"}).encode() + b"\n"):
        assert iw.parse_line(bad, 1000) is None


# ---- owner-run Docker check (explicit availability marker; never a model call) -------------------
REAL_IMAGE = os.environ.get("ZEUS_TEST_WORKER_IMAGE", "")
needs_docker = pytest.mark.skipif(shutil.which("docker") is None or not iw.IMAGE.fullmatch(REAL_IMAGE),
                                  reason="owner check: needs Docker and ZEUS_TEST_WORKER_IMAGE=sha256:<id>")


@needs_docker
def test_real_sleeping_container_is_killed_confirmed_and_removed(tmp_path):
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": REAL_IMAGE})
    iw.preflight(config, token=False)
    stage = tmp_path / "workspace"
    stage.mkdir()
    (tmp_path.parent / "sibling-sentinel").write_text("host only")
    owned = iw.OwnedContainer(config, "docker", os.urandom(8).hex(), "worker")
    args = iw.container_args(config, name=owned.name, run_id=owned.run_id, role="worker", network="none",
                             mounts=[(str(stage.resolve()), iw.WORKSPACE)], environment={}, pass_names=(),
                             entry=[iw.TRUSTED_PYTHON, "-c", "import time; time.sleep(600)"], workdir="/")
    owned.create(args, iw.docker_environment())
    try:
        controls = owned.verify({iw.WORKSPACE}, "none")
        assert [m["Destination"] for m in controls["mounts"] if m["Type"] == "bind"] == [iw.WORKSPACE]
        subprocess.run(["docker", "start", owned.id], capture_output=True, timeout=60, check=True)
        started = time.monotonic()
        assert owned.stop(config["limits"]["cleanup_seconds"])["confirmed"]
        assert time.monotonic() - started < config["limits"]["cleanup_seconds"]
    finally:
        assert owned.remove()["removed"]
