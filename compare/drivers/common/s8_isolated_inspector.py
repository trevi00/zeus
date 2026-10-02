"""Shared S8 scenario steps (`evidence.isolated_inspector`): M7 `adapters/isolated_evidence.py` (`DockerEvidenceInspector`,
`IsolatedProjectEvidenceInspector`, `CONTAINER_ENVIRONMENT`, `container_environment`), characterized BEFORE the module moves into
`evidence.adapters` with its container replay in `execution.adapters.containers.evidence_replay` (DESIGN-s8 §27.1 V26 rules E-1..E-3; the
batch B5b spec). Mirrors the behaviours of M7 `tests/test_isolated_evidence.py` and `tests/test_isolated_project_evidence.py` that the
adapter itself decides (the `IsolatedWorker`, entry, bootstrap and executor tests are S3/S10 composition and stay out).

- **j1_identity_and_refusals**: `CONTAINER_ENVIRONMENT`, `container_environment`, `_trusted`/`_python`, the snapshot identity (image, limits, network,
  driver in the key), an image change that invalidates it, an unauthorized argv that never reaches docker.
- **j2_lifecycle**: an authorized replay over the injected capture: two fresh network-none containers, the create argv, the lifecycle record
  prepared -> created -> start_requested -> stop_confirmed -> evidence_retained -> removed, the snapshot copies removed, the progress callback
  forwarded as given, the container's own exit code.
- **j3_interruptions**: an interruption after start, a progress refusal inside the capture, an unconfirmed stop that leaves a recovery record (the next
  replay is refused by name, then reconciled), an unreclaimed capture debt.
- **j4_failures**: an unconfirmed stop after a returned capture, an unwritten observation, an unavailable container, a lost create id, a refused
  control, a capture failure, the unresolved-run refusal and the preparation OSError.
- **j5_real_capture**: the REAL `_capture` over real local children standing where `docker start --attach` would be: a normal exit, a timeout, an
  unconfirmed cleanup (injected at the tree), an interruption in wait, a missing or malformed proof, an unwritten observation.
- **j6_project_in_container**: `IsolatedProjectEvidenceInspector`: each declared check replayed in its own container context, the refusals that
  never reach a container, the identity, a lost owner, the constructor refusals.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. No docker daemon is contacted: `api.install_docker`
routes the one docker-call function of each side to the `ScriptedDocker` below. The only real children are this side's own interpreter running fixed
programs through the REAL `ProcessTree`. Masks, declared: durations, OS pids and group ids, record timestamps (`at`), the inspection id and the project digest (digests
over the host path); host roots become symbolic names; the isolation's `driver_sha256` is a fixed value so the isolation digest is the same on both sides."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from s1_common import relative

PY = sys.executable
IMAGE = "sha256:" + "a" * 64
OTHER_IMAGE = "sha256:" + "b" * 64
TOKEN = "sk" + "-ant-oat01-FIXTURE-SECRET-VALUE"  # assembled so the tree scan sees no credential-shaped literal
SIBLING = "f" * 64
UID = 4242
PIDISH = {"pid", "group", "pgid", "process_id", "leader"}
DURATIONS = {"duration_seconds", "elapsed_seconds", "seconds"}
HOSTDIGESTS = {"inspection_id"}
TIMES = {"at"}
HOLDER = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
          "print('started', flush=True); time.sleep(120)")
WATCHDOG_SECONDS = 60
PYTEST = ["python -m pytest -q"]
TASK = {"id": "task-1", "generation": 1, "attempt": 1, "lease_owner": "worker"}
CANDIDATE = {"revision": "a" * 40, "base": "b" * 40, "tree": "c" * 40}
UNIT = ["python", "-m", "pytest", "backend/probes", "-q"]
LINT = ["python", "-m", "ruff", "check", "."]


class Artifacts:
    """The M7 tests' artifact stub: a receipt named by the kind, nothing stored."""

    def put(self, body, kind):
        return {"ref": "sha256:" + kind}


class ScriptedDocker:
    """A scripted docker client answering the exact argv the adapter composes (the M7 `FakeDocker`, minus the inner-process script)."""

    def __init__(self, api):
        self.api = api
        self.calls = []
        self.containers = {SIBLING: {"name": "zeus-worker-sibling", "labels": {api.LABEL: "other"}, "status": "exited", "exit": 0}}
        self.kill_works = self.rm_works = True
        self.exit_on_capture = True
        self.create_fails = self.lose_create = self.controls_bad = False
        self.exit_code = 0
        self.image = IMAGE

    def __call__(self, args, env):
        args = [str(part) for part in args]
        self.calls.append({"args": args, "env_names": sorted(env or {})})
        verb = args[0]
        if verb == "create":
            if self.create_fails:
                return 125, ""
            identifier = format(len(self.containers), "x").rjust(64, "e")
            labels = dict(a.split("=", 1) for i, a in enumerate(args) if args[i - 1] == "--label")
            mounts = [dict(p.split("=", 1) for p in a.split(",")) for i, a in enumerate(args) if args[i - 1] == "--mount"]
            self.containers[identifier] = {"name": args[args.index("--name") + 1], "labels": labels, "mounts": mounts,
                                           "network": args[args.index("--network") + 1], "user": args[args.index("--user") + 1],
                                           "status": "created", "exit": self.exit_code}
            return (125, "") if self.lose_create else (0, identifier + "\n")
        if verb == "ps":
            name = [a for a in args if a.startswith("name=")][0][len("name=^/"):-1]
            label = [a for a in args if a.startswith("label=")]
            ids = [i for i, c in self.containers.items() if c["name"] == name
                   and (not label or c["labels"].get(self.api.LABEL) == label[0].split("=", 2)[2])]
            return 0, "\n".join(ids) + "\n"
        container = self.containers.get(args[-1])
        if container is None:
            return 1, ""
        if verb == "inspect" and args[2] == self.api.INSPECT_FORMAT:
            return 0, json.dumps({
                "image": self.image, "user": "0:0" if self.controls_bad else container["user"], "network": container["network"],
                "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges"], "memory": 1, "nano_cpus": 1,
                "pids_limit": 512, "privileged": False, "ports": {}, "labels": container["labels"],
                "mounts": [{"Type": "bind", "Source": m["source"], "Destination": m["target"], "RW": m.get("readonly") != "true"}
                           for m in container["mounts"]]})
        if verb == "inspect":
            return 0, f"{container['status']} {container['exit']} false\n"
        if verb == "kill":
            if self.kill_works:
                container["status"] = "exited"
            return 0, ""
        if verb == "rm":
            if self.rm_works and container["status"] != "running":
                del self.containers[args[-1]]
                return 0, ""
            return 1, ""
        raise AssertionError("unexpected docker argv: " + repr(args))


def mask(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in PIDISH and isinstance(item, int) and not isinstance(item, bool):
                out[key] = "<pid>"
            elif key in DURATIONS and isinstance(item, (int, float)) and not isinstance(item, bool):
                out[key] = "<duration>"
            elif key in TIMES and isinstance(item, (int, float)) and not isinstance(item, bool):
                out[key] = "<time>"
            elif key in HOSTDIGESTS and isinstance(item, str) and len(item) == 64:
                out[key] = "<host-path digest>"
            else:
                out[key] = mask(item)
        return out
    if isinstance(value, (list, tuple)):
        return [mask(v) for v in value]
    return value


def expect(action):
    """The value, or the raised exception's type, message and attached capture cleanup (a KeyboardInterrupt is a result here)."""
    try:
        return {"ok": action()}
    except BaseException as exc:  # noqa: BLE001 - the refusal is the result
        row = {"raised": type(exc).__name__, "message": str(exc)[:300]}
        for attr in ("reason_code", "capture_cleanup"):
            if hasattr(exc, attr):
                row[attr] = getattr(exc, attr)
        return row


class Ctx:
    def __init__(self, api, root: Path):
        self.api, self.root = api, root
        self.roots = {"ROOT": str(root)}
        self.n = 0

    def fresh(self, name):
        self.n += 1
        path = self.root / f"{self.n:02d}-{name}"
        path.mkdir()
        return path

    def show(self, value):
        return relative(mask(value), self.roots)

    def isolation(self, cleanup_seconds=2, image=IMAGE):
        api = self.api
        config = api.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": image})
        body = {k: v for k, v in config.items() if k != "digest"}
        body["driver_sha256"] = "d" * 64
        body["limits"] = {**body["limits"], "inner_grace_seconds": 1, "cleanup_seconds": cleanup_seconds}
        return {**body, "digest": api.digest(body)}

    def case(self, name, project=False, parsed=None, cleanup_seconds=2):
        """One fresh candidate, replay root, scripted docker and inspector, with deterministic run ids and host ids."""
        api = self.api
        tmp = self.fresh(name)
        workspace = tmp / "candidate"
        if project:
            tree(workspace)
        else:
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "mod.py").write_text("X = 1\n", encoding="utf-8")
            (workspace / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        fake = ScriptedDocker(api)
        api.install_docker(fake)
        api.set_ids(UID, UID)
        api.set_uuid(name)
        isolation = self.isolation(cleanup_seconds)
        artifacts = api.FileArtifacts(str(tmp / "artifacts")) if project else Artifacts()
        if project:
            insp = api.make_project(artifacts, parsed or profile(api), isolation, tmp / "replays")
        else:
            insp = api.make_docker(artifacts, isolation, tmp / "replays")
        return SimpleCase(self, tmp, workspace, fake, insp)


class SimpleCase:
    def __init__(self, ctx, tmp, workspace, fake, insp):
        self.ctx, self.tmp, self.workspace, self.fake, self.insp = ctx, tmp, workspace, fake, insp
        self.api = ctx.api

    def inspect(self, claims, progress=None):
        snapshot = self.insp.snapshot(self.workspace)
        extra = {"project": snapshot["project"]} if "project" in snapshot else {}
        report = self.insp.inspect(claims, self.workspace, {"task_id": "t"}, environment=snapshot["environment"],
                                   interpreter=snapshot["identity"]["interpreter"], progress=progress, **extra)
        return report, snapshot

    def records(self):
        return self.ctx.show(self.api.run_records(self.insp.root))

    def unresolved(self):
        return self.ctx.show(self.api.unresolved_runs(self.insp.root, str(self.workspace.resolve())))

    def creates(self):
        return [call["args"] for call in self.fake.calls if call["args"][0] == "create"]

    def verbs(self):
        return [call["args"][0] for call in self.fake.calls]

    def snapshots_left(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.insp.root.glob("*/workspace")) if self.insp.root.is_dir() else []

    def finding(self, report, index=0):
        return self.ctx.show(report["findings"][index])


# ---- the project fixtures (the M7 isolated project tests' tree and profile) ---------------------------------------------------
def tree(root: Path) -> Path:
    (root / "backend" / "src").mkdir(parents=True)
    (root / "backend" / "probes").mkdir()
    (root / "backend" / "requirements.lock").write_bytes(b"example==1.0\n")
    (root / "backend" / "src" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    return root


def document(api, schema=None, image=IMAGE, interpreter=None, checks=None):
    schema = schema or api.SCHEMA_V2
    interpreter = interpreter or api.TRUSTED_PYTHON
    doc = {"schema": schema,
           "contexts": {"backend": {"cwd": "backend", "interpreter": interpreter, "source_paths": ["backend/src"],
                                    "dependency_files": ["backend/requirements.lock"]}},
           "checks": checks if checks is not None else [
               {"id": "unit", "context": "backend", "argv": UNIT, "expected_exit": 0},
               {"id": "lint", "context": "backend", "argv": LINT, "expected_exit": 0}]}
    if schema == api.SCHEMA_V2:
        doc["execution"] = {"kind": "container", "image": image}
    return doc


def profile(api, **kwargs):
    return api.parse_profile(document(api, **kwargs), api.packaged_policy())


def observed(check_id, code=0, status="executed"):
    return {"check_id": check_id, "status": status, "exit_code": code}


# ---- injected and real captures -----------------------------------------------------------------------------------------------
def accepting(fake, captured):
    def capture(argv, cwd, timeout, max_bytes, env, progress=None):  # the container "ran" and exited
        captured.append({"argv": list(argv), "cwd": cwd, "timeout": timeout, "max_bytes": max_bytes, "env_names": sorted(env),
                         "progress": progress})
        fake.containers[argv[-1]]["status"] = "exited" if fake.exit_on_capture else "running"
        return {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.1,
                "cleanup": {"reason": "exited", "confirmed": True, "injected": True}}
    return capture


def interrupting(case, seen, debt=None):
    def capture(argv, cwd, timeout, max_bytes, env, progress=None):  # cancellation right after a (scripted) docker start
        case.fake.containers[argv[-1]]["status"] = "running"
        seen.append({"id": argv[-1], "records": case.api.run_records(case.insp.root)})
        error = KeyboardInterrupt()
        error.capture_cleanup = debt or {"reason": "KeyboardInterrupt", "confirmed": True, "injected": True}
        raise error
    return capture


def refusing_at_wait(case, seen):
    def capture(argv, cwd, timeout, max_bytes, env, progress=None):
        case.fake.containers[argv[-1]]["status"] = "running"
        seen.append(argv[-1])
        try:
            progress("replay_wait")
        except BaseException as exc:  # what the real capture does: reclaim, then carry the proof
            exc.capture_cleanup = {"reason": type(exc).__name__, "confirmed": True, "injected": True}
            raise
        raise AssertionError("the refusal never reached the capture")
    return capture


def local_client(api, fake, code, status, spawned, interrupt=False, break_termination=False):
    """The `spawn` replacing `docker start --attach <id>`: the REAL tree over a real local child of this side's interpreter."""
    real = api.real_spawn()

    def spawn(argv, **kwargs):
        fake.containers[argv[-1]]["status"] = status
        tree_ = real([PY, "-c", code], **kwargs)
        fired = []
        if interrupt:
            wait, calls = tree_.process.wait, []

            def interrupted(timeout=None):
                calls.append(timeout)
                if len(calls) == 1:
                    time.sleep(1.5)
                    raise KeyboardInterrupt
                return wait(timeout=timeout)
            tree_.process.wait = interrupted
        original = (tree_.terminate, tree_.close)
        if break_termination:
            tree_.terminate = lambda reason, **_: {"reason": reason, "confirmed": False, "injected": True}
            tree_.close = lambda: None
        watchdog = threading.Timer(WATCHDOG_SECONDS, lambda: (fired.append(tree_.process.pid), original[1](), tree_.process.kill()))
        watchdog.daemon = True
        watchdog.start()
        spawned.append({"tree": tree_, "watchdog": watchdog, "original": original, "fired": fired})
        return tree_
    return spawn


def reclaim(spawned):
    """The scenario cleans its own children; never the mechanism that makes a step pass."""
    for item in spawned:
        item["watchdog"].cancel()
        item["original"][0]("scenario cleanup")
        item["original"][1]()


def packaged_with(case, **replay):
    case.insp.policy = {**case.insp.policy, "replay": {**case.insp.policy["replay"], **replay}}


# ---- j1 -------------------------------------------------------------------------------------------------------------------
def j1_identity_and_refusals(ctx):
    api, out = ctx.api, {}
    out["container_environment_constant"] = api.CONTAINER_ENVIRONMENT
    plain = ctx.fresh("plain")
    with_src = ctx.fresh("with-src")
    (with_src / "src").mkdir()
    src_file = ctx.fresh("src-file")
    (src_file / "src").write_text("x", encoding="utf-8")
    out["container_environment"] = {"none": api.container_environment(), "no_src": api.container_environment(plain),
                                    "with_src": api.container_environment(with_src), "src_is_file": api.container_environment(src_file),
                                    "copy_each_call": api.container_environment() is not api.container_environment()}
    case = ctx.case("identity")
    insp = case.insp
    out["trusted_and_python"] = {"trusted_none": insp._trusted(None), "trusted_other": insp._trusted("/usr/bin/python3"),
                                 "python": insp._python(), "root_is_path": type(insp.root).__name__,
                                 "docker": insp.docker, "interpreter": insp._interpreter}
    snapshot = insp.snapshot(case.workspace)
    out["snapshot"] = ctx.show(snapshot)
    out["snapshot_no_cwd"] = ctx.show(insp.snapshot())
    out["snapshot_keys"] = {"top": sorted(snapshot), "identity": sorted(snapshot["identity"]),
                            "same_twice": insp.snapshot(case.workspace) == snapshot}
    other = api.make_docker(Artifacts(), ctx.isolation(image=OTHER_IMAGE), case.tmp / "replays")
    first, second = insp.identity(case.workspace), other.identity(case.workspace)
    out["image_change"] = {"differs": first != second, "first_image": first["container"]["image"], "second_image": second["container"]["image"],
                           "platform": first["platform"], "credentials": first["container"]["credentials"],
                           "network": first["container"]["network"], "workspace": first["container"]["workspace"],
                           "snapshot": first["container"]["snapshot"]}
    report, _ = case.inspect([{"kind": "command", "argv": ["python", "-c", "print(1)"], "expected_exit": 0}])
    out["unauthorized"] = {"finding": case.finding(report), "docker_calls": case.fake.calls, "records": case.records(),
                           "context_python": report["context"]["python"], "context_interpreter": report["context"]["interpreter"]}
    out["no_workspace"] = ctx.show(insp.inspect(PYTEST, ctx.root / "absent", {"task_id": "t"}))
    return out


# ---- j2 -------------------------------------------------------------------------------------------------------------------
def j2_lifecycle(ctx):
    api, out = ctx.api, {}
    case = ctx.case("lifecycle")
    captured = []
    stages = []
    progress = lambda stage=None: stages.append(stage)  # noqa: E731 - one recorder, per call
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, snapshot = case.inspect(PYTEST, progress=progress)
    finding = report["findings"][0]
    out["report"] = {"state": finding["state"], "replay_argv": finding["replay_argv"][:1], "runs": ctx.show(finding["runs"]),
                     "context_python": report["context"]["python"], "context_interpreter": report["context"]["interpreter"],
                     "network": [run["container"]["network"] for run in finding["runs"]]}
    out["creates"] = ctx.show(case.creates())
    out["create_flags"] = [{"network": args[args.index("--network") + 1], "entrypoint": args[args.index("--entrypoint") + 1],
                            "read_only": "--read-only" in args, "token_name": api.TOKEN_NAME in args, "user": args[args.index("--user") + 1],
                            "workdir": args[args.index("-w") + 1], "tail": args[-3:], "pythonpath": "PYTHONPATH=/workspace/src" in args,
                            "name": args[args.index("--name") + 1]} for args in case.creates()]
    out["docker_verbs"] = case.verbs()
    out["docker_env_names"] = [call["env_names"] for call in case.fake.calls]
    out["token_in_calls"] = TOKEN in json.dumps(case.fake.calls) + json.dumps(report, default=str)
    out["captured"] = ctx.show([{**c, "progress": c["progress"] is progress} for c in captured])
    out["progress_stages"] = stages
    out["containers_left"] = list(case.fake.containers)
    out["snapshots_left"] = case.snapshots_left()
    out["records"] = case.records()
    out["unresolved"] = case.unresolved()
    out["rm_after_create"] = case.verbs().index("rm") > case.verbs().index("create")
    # the container's own exit replaces the client's
    case = ctx.case("own-exit")
    case.fake.exit_code = 3
    captured = []
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, _ = case.inspect(PYTEST)
    out["container_exit"] = {"finding": case.finding(report), "records": case.records()}
    return out


# ---- j3 -------------------------------------------------------------------------------------------------------------------
def j3_interruptions(ctx):
    api, out = ctx.api, {}
    case = ctx.case("progress-refusal")
    seen = []

    def lost(stage=None):
        if stage == "replay_wait":
            raise api.ContractError("Stale or expired task execution")
    with api.injected_capture(case.insp, refusing_at_wait(case, seen)):
        raised = expect(lambda: case.inspect(PYTEST, progress=lost))
    out["progress_refusal"] = {"raised": ctx.show(raised), "records": case.records(),
                               "kills": [c["args"] for c in case.fake.calls if c["args"][0] == "kill"] == [["kill", seen[0]]],
                               "unresolved": case.unresolved(), "replays_started": len(seen)}

    case = ctx.case("interrupted")
    seen = []
    with api.injected_capture(case.insp, interrupting(case, seen)):
        raised = expect(lambda: case.inspect(PYTEST))
    out["interrupted"] = {"raised": ctx.show(raised), "owner_before_start": ctx.show(seen[0]["records"]),
                          "records": case.records(), "kills": [c["args"] for c in case.fake.calls if c["args"][0] == "kill"],
                          "containers_left": list(case.fake.containers), "unresolved": case.unresolved()}

    case = ctx.case("unconfirmed", cleanup_seconds=1)
    case.fake.kill_works = False
    seen = []
    with api.injected_capture(case.insp, interrupting(case, seen)):
        raised = expect(lambda: case.inspect(PYTEST))
    saved = api.run_records(case.insp.root)[0]
    created = len(case.creates())
    with api.injected_capture(case.insp, accepting(case.fake, [])):
        report, _ = case.inspect(PYTEST)
    out["unconfirmed_stop"] = {"raised": ctx.show(raised), "state": saved["state"], "last_step": ctx.show(saved["lifecycle"][-1]),
                               "id_still_there": seen[0]["id"] in case.fake.containers,
                               "rm_calls": [c for c in case.fake.calls if c["args"][0] == "rm"],
                               "unresolved": case.unresolved(), "next_replay": case.finding(report),
                               "creates_unchanged": len(case.creates()) == created}
    del case.fake.containers[seen[0]["id"]]  # the owner removed the exact container
    out["unconfirmed_stop"]["reconcile"] = ctx.show(api.reconcile(case.insp.root / saved["run_id"]))
    out["unconfirmed_stop"]["unresolved_after"] = case.unresolved()

    case = ctx.case("capture-debt", cleanup_seconds=1)
    debt = {"reason": "KeyboardInterrupt", "confirmed": False, "readers_alive": ["stdout"], "injected": True}
    seen = []
    with api.injected_capture(case.insp, interrupting(case, seen, debt)):
        raised = expect(lambda: case.inspect(PYTEST))
    saved = api.run_records(case.insp.root)[0]
    out["capture_debt"] = {"raised": ctx.show(raised), "state": saved["state"], "stop": ctx.show(saved["lifecycle"][-1]["stop"]),
                           "kill_called": any(c["args"][0] == "kill" for c in case.fake.calls),
                           "rm_called": any(c["args"][0] == "rm" for c in case.fake.calls), "unresolved": case.unresolved()}
    return out


# ---- j4 -------------------------------------------------------------------------------------------------------------------
def j4_failures(ctx):
    api, out = ctx.api, {}
    case = ctx.case("stop-unconfirmed", cleanup_seconds=1)
    case.fake.kill_works = False
    case.fake.exit_on_capture = False
    with api.injected_capture(case.insp, accepting(case.fake, [])):
        report, _ = case.inspect(PYTEST)
    out["unconfirmed_after_return"] = {"finding": case.finding(report), "records": case.records(), "containers": len(case.fake.containers)}

    case = ctx.case("unwritten")
    real = api.ledger_get("_write_record")

    def failing(path, record):  # injected fault: the observation cannot be written
        if record.get("state") == "evidence_retained":
            raise OSError("injected: disk full")
        return real(path, record)
    api.ledger_set("_write_record", failing)
    try:
        with api.injected_capture(case.insp, accepting(case.fake, [])):
            report, _ = case.inspect(PYTEST)
    finally:
        api.ledger_set("_write_record", real)
    out["unwritten"] = {"finding": case.finding(report), "rm_called": any(c["args"][0] == "rm" for c in case.fake.calls),
                        "containers": len(case.fake.containers), "records": case.records(), "unresolved": case.unresolved()}

    case = ctx.case("unavailable")
    captured = []
    create = api.OwnedContainer.create

    def unavailable(self, args, env):  # injected fault: the daemon creates nothing
        raise api.IsolationError("container_create_failed")
    api.OwnedContainer.create = unavailable
    try:
        with api.injected_capture(case.insp, accepting(case.fake, captured)):
            report, _ = case.inspect(PYTEST)
    finally:
        api.OwnedContainer.create = create
    out["unavailable"] = {"finding": case.finding(report), "captured": captured, "records": case.records(), "snapshots": case.snapshots_left()}

    case = ctx.case("create-refused")
    case.fake.create_fails = True
    captured = []
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, _ = case.inspect(PYTEST)
    out["create_refused"] = {"finding": case.finding(report), "captured": captured, "records": case.records(), "snapshots": case.snapshots_left(),
                             "verbs": case.verbs()}

    case = ctx.case("lost-create-id")
    case.fake.lose_create = True
    with api.injected_capture(case.insp, accepting(case.fake, [])):
        report, _ = case.inspect(PYTEST)
    out["lost_create_id"] = {"state": report["findings"][0]["state"], "verbs": case.verbs()[:4], "records": case.records()}

    case = ctx.case("controls-refused")
    case.fake.controls_bad = True
    captured = []
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, _ = case.inspect(PYTEST)
    out["controls_refused"] = {"finding": case.finding(report), "captured": captured, "records": case.records(),
                               "containers": len(case.fake.containers), "snapshots": case.snapshots_left(), "unresolved": case.unresolved()}

    case = ctx.case("controls-refused-kept")
    case.fake.controls_bad = True
    case.fake.rm_works = False
    with api.injected_capture(case.insp, accepting(case.fake, [])):
        report, _ = case.inspect(PYTEST)
    out["controls_refused_not_removed"] = {"finding": case.finding(report), "records": case.records(), "snapshots": case.snapshots_left(),
                                           "unresolved": case.unresolved()}

    case = ctx.case("capture-failure")

    def failed(argv, cwd, timeout, max_bytes, env, progress=None):
        case.fake.containers[argv[-1]]["status"] = "exited"
        return {"failure": "timeout after 2s", "terminated": True, "returncode": -9, "duration_seconds": 2.0,
                "cleanup": {"reason": "timeout", "confirmed": True, "injected": True}}
    with api.injected_capture(case.insp, failed):
        report, _ = case.inspect(PYTEST)
    out["capture_failure"] = {"finding": case.finding(report), "records": case.records(), "unresolved": case.unresolved()}

    case = ctx.case("preparation-oserror")
    blocker = case.tmp / "blocker"
    blocker.write_text("a file where the replay root's parent should be", encoding="utf-8")
    case.insp.root = blocker / "replays"
    captured = []
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, _ = case.inspect(PYTEST)
    out["preparation_oserror"] = {"finding": case.finding(report), "captured": captured, "creates": len(case.creates()),
                                  "verbs": case.verbs()}
    return out


# ---- j5 -------------------------------------------------------------------------------------------------------------------
def retained_with_client_debt(ctx, case):
    api = ctx.api
    saved, = api.run_records(case.insp.root)
    stop = saved["lifecycle"][-1]["stop"]
    probe = api.new_container(case.insp.isolation, saved["run_id"])
    refusal = api.retire(probe, saved, {}, "replayed")
    return saved, {"state": saved["state"], "has_result": "result" in saved, "stop": ctx.show(stop),
                   "recovery_matches": saved["lifecycle"][-1]["recovery"]["container"] == saved["container"],
                   "rm_called": any(c["args"][0] == "rm" for c in case.fake.calls), "id_present": saved["container"] in case.fake.containers,
                   "unresolved": case.unresolved(), "refusal": ctx.show(refusal)}


def reconcile_keeps_debt(ctx, case, saved):
    del case.fake.containers[saved["container"]]  # the container is gone; the host-side client debt is not
    refused = ctx.api.reconcile(case.insp.root / saved["run_id"])
    return {"refused": ctx.show(refused), "records": case.records(), "unresolved": len(case.unresolved())}


def j5_real_capture(ctx):
    api, out = ctx.api, {}

    case = ctx.case("real-normal")
    spawned = []
    with api.spawning(local_client(api, case.fake, "print('ok')", "exited", spawned)):
        report, _ = case.inspect(PYTEST)
    out["normal_exit"] = {"state": report["findings"][0]["state"], "spawned": len(spawned),
                          "exits": [item["tree"].process.poll() for item in spawned], "records": case.records(),
                          "unresolved": case.unresolved(), "containers": list(case.fake.containers)}
    reclaim(spawned)

    case = ctx.case("real-timeout")
    packaged_with(case, per_command_seconds=2)
    spawned = []
    with api.spawning(local_client(api, case.fake, HOLDER, "running", spawned)):
        report, _ = case.inspect(PYTEST)
    out["known_failure"] = {"finding": case.finding(report), "records": case.records(), "unresolved": case.unresolved(),
                            "child_gone": spawned[0]["tree"].process.poll() is not None}
    reclaim(spawned)

    case = ctx.case("real-unconfirmed", cleanup_seconds=1)
    packaged_with(case, per_command_seconds=2)
    spawned = []
    try:
        with api.patched("READER_JOIN_SECONDS", 1.0), api.spawning(local_client(api, case.fake, HOLDER, "running", spawned, break_termination=True)):
            report, _ = case.inspect(PYTEST)
            alive = spawned[0]["tree"].process.poll() is None
            saved, view = retained_with_client_debt(ctx, case)
            created = len(case.creates())
            again, _ = case.inspect(PYTEST)
            out["returned_unconfirmed"] = {"child_alive_on_return": alive, "finding": case.finding(report), "spawned": len(spawned),
                                           "retained": view, "next_replay": case.finding(again),
                                           "creates_unchanged": len(case.creates()) == created,
                                           "reconcile": reconcile_keeps_debt(ctx, case, saved)}
    finally:
        reclaim(spawned)

    case = ctx.case("real-interrupt", cleanup_seconds=1)
    spawned = []
    started = time.monotonic()
    stops = []
    stop = api.OwnedContainer.stop

    def timed_stop(self, seconds):
        stops.append({"at": time.monotonic(), "child_gone": bool(spawned) and spawned[0]["tree"].process.poll() is not None})
        return stop(self, seconds)
    api.OwnedContainer.stop = timed_stop
    try:
        with api.spawning(local_client(api, case.fake, HOLDER, "running", spawned, interrupt=True)):
            raised = expect(lambda: case.inspect(PYTEST))
        item = spawned[0]
        saved, = api.run_records(case.insp.root)
        out["interrupted_in_wait"] = {
            "raised": ctx.show(raised), "watchdog_fired": item["fired"] != [], "stop_calls": len(stops),
            "stop_before_watchdog": stops[0]["at"] - started < WATCHDOG_SECONDS / 2, "child_gone_at_stop": stops[0]["child_gone"],
            "streams_closed": item["tree"].process.stdout.closed and item["tree"].process.stderr.closed,
            "state": saved["state"], "result": ctx.show(saved.get("result", {}).get("interrupted")),
            "stop": ctx.show(saved["result"]["stop"]), "containers_left": list(case.fake.containers), "unresolved": case.unresolved()}
    finally:
        api.OwnedContainer.stop = stop
        reclaim(spawned)

    case = ctx.case("real-interrupt-unconfirmed", cleanup_seconds=1)
    spawned = []
    try:
        with api.patched("READER_JOIN_SECONDS", 1.0), api.spawning(
                local_client(api, case.fake, HOLDER, "running", spawned, interrupt=True, break_termination=True)):
            raised = expect(lambda: case.inspect(PYTEST))
        saved, view = retained_with_client_debt(ctx, case)
        out["raised_interruption_unconfirmed"] = {"raised": ctx.show(raised), "child_alive": spawned[0]["tree"].process.poll() is None,
                                                  "interrupted_step": saved["lifecycle"][-1]["interrupted"], "retained": view,
                                                  "reconcile": reconcile_keeps_debt(ctx, case, saved)}
    finally:
        reclaim(spawned)

    for label, proof in (("absent", "absent"), ("none", None), ("string", "yes"), ("string_confirmed", {"confirmed": "true"}),
                         ("no_confirmed", {"reason": "exited"})):
        case = ctx.case("real-proof-" + label, cleanup_seconds=1)
        spawned = []

        def stripped(*args, _case=case, _proof=proof, **kwargs):  # the real capture ran and cleaned up, but its proof does not arrive
            run = api.real_capture(_case.insp)(*args, **kwargs)
            assert run.pop("cleanup")["confirmed"] is True
            return run if _proof == "absent" else {**run, "cleanup": _proof}
        try:
            with api.spawning(local_client(api, case.fake, "print('ok')", "exited", spawned)), api.injected_capture(case.insp, stripped):
                report, _ = case.inspect(PYTEST)
            saved, view = retained_with_client_debt(ctx, case)
            out["proof_" + label] = {"finding": case.finding(report), "spawned": len(spawned), "retained": view,
                                     "capture_cleanup": ctx.show(saved["lifecycle"][-1]["stop"]["capture_cleanup"]),
                                     "reconcile": reconcile_keeps_debt(ctx, case, saved)}
        finally:
            reclaim(spawned)

    case = ctx.case("real-unwritten")
    spawned = []
    real = api.ledger_get("_write_record")

    def failing(path, record):  # injected fault: the observation cannot be written
        if record.get("state") == "evidence_retained":
            raise OSError("injected: disk full")
        return real(path, record)
    api.ledger_set("_write_record", failing)
    try:
        with api.spawning(local_client(api, case.fake, "print('ok')", "exited", spawned)):
            report, _ = case.inspect(PYTEST)
    finally:
        api.ledger_set("_write_record", real)
    saved, = api.run_records(case.insp.root)
    out["unwritten_evidence"] = {"finding": case.finding(report), "state": saved["state"], "stop_confirmed": saved["lifecycle"][-1]["stop"]["confirmed"],
                                 "rm_called": any(c["args"][0] == "rm" for c in case.fake.calls), "id_present": saved["container"] in case.fake.containers,
                                 "unresolved": len(case.unresolved()), "child_exit": spawned[0]["tree"].process.poll()}
    reclaim(spawned)
    return out


# ---- j6 -------------------------------------------------------------------------------------------------------------------
def j6_project_in_container(ctx):
    api, out = ctx.api, {}
    case = ctx.case("project-checks", project=True)
    captured = []
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, snapshot = case.inspect([observed("unit"), observed("lint")])
    creates = case.creates()
    passed = {args[index + 1].split("=", 1)[0] for args in creates for index, token in enumerate(args) if token == "-e"}
    out["each_check_in_its_context"] = {
        "states": [f["state"] for f in report["findings"]], "check_ids": [f["check_id"] for f in report["findings"]],
        "context_python": report["context"]["python"], "context_interpreter": report["context"]["interpreter"],
        "project_digest_matches": report["context"]["project_digest"] == snapshot["project"]["digest"],
        "creates": len(creates), "distinct_names": len({args[args.index("--name") + 1] for args in creates}),
        "workdirs": [args[args.index("-w") + 1] for args in creates], "networks": [args[args.index("--network") + 1] for args in creates],
        "read_only": ["--read-only" in args for args in creates], "entrypoints": [args[args.index("--entrypoint") + 1] for args in creates],
        "pythonpath": ["PYTHONPATH=/workspace/backend/src" in args for args in creates], "token_name": [api.TOKEN_NAME in args for args in creates],
        "host_path_in_argv": [str(case.workspace.resolve()) in " ".join(args) for args in creates],
        "first_tail": creates[0][-4:], "last_tail": creates[-1][-4:], "environment_names": sorted(passed),
        "token_in_calls": TOKEN in json.dumps(case.fake.calls) + json.dumps(report, default=str),
        "unresolved": case.unresolved(), "snapshots_left": case.snapshots_left(), "captured": len(captured),
        "findings": ctx.show([{k: v for k, v in f.items() if k != "runs"} for f in report["findings"]]),
        "snapshot_identity": ctx.show({**snapshot["identity"], "project": {**snapshot["identity"]["project"], "digest": "<host-path digest>"}}),
        "snapshot_environment": snapshot["environment"]}

    case = ctx.case("project-ledger", project=True)
    captured = []
    store = api.MemoryStore()
    ledger = api.EvidenceInspections(store, case.insp)
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        row = ledger.inspect(TASK, CANDIDATE, [observed("unit", None, "not_run"), observed("invented"), observed("unit")], str(case.workspace))
        refused = {"verdict": row["verdict"], "states": [f["state"] for f in row["findings"]],
                   "claim_states": {f["claim"]["check_id"]: f["state"] for f in row["findings"] if (f.get("claim") or {}).get("check_id")},
                   "creates": len(case.creates()), "captured": len(captured)}
        mismatch = ledger.inspect(TASK, CANDIDATE, [observed("unit", 1), observed("lint")], str(case.workspace))
        unit = mismatch["findings"][0]
        out["refusals_and_mismatch"] = {
            "refused": refused, "mismatch_state": unit["state"], "observed_exits": unit["observed_exits"], "reported_exit": unit["reported_exit"],
            "mismatch_verdict": mismatch["verdict"], "empty_verdict": ledger.inspect(TASK, CANDIDATE, [], str(case.workspace))["verdict"]}
        first = ledger.inspect(TASK, CANDIDATE, [observed("unit"), observed("lint")], str(case.workspace))
        again = api.EvidenceInspections(store, api.make_project(Artifacts(), profile(api), ctx.isolation(), case.tmp / "replays")).inspect(
            TASK, CANDIDATE, [observed("unit"), observed("lint")], str(case.workspace))
        (case.workspace / "backend" / "requirements.lock").write_bytes(b"example==2.0\n")
        changed = api.EvidenceInspections(store, api.make_project(Artifacts(), profile(api), ctx.isolation(), case.tmp / "replays")).inspect(
            TASK, CANDIDATE, [observed("unit"), observed("lint")], str(case.workspace))
        fewer = api.parse_profile(document(api, checks=[{"id": "unit", "context": "backend", "argv": UNIT, "expected_exit": 0}]), api.packaged_policy())
        narrowed = api.EvidenceInspections(store, api.make_project(Artifacts(), fewer, ctx.isolation(), case.tmp / "replays")).inspect(
            TASK, CANDIDATE, [observed("unit")], str(case.workspace))
    out["identity"] = {"first_verdict": first["verdict"], "project_digest_present": bool(first["context"]["project_digest"]),
                       "same_proof_read_back": again["id"] == first["id"], "dependency_change_is_new": changed["id"] != first["id"],
                       "narrowed_is_new": narrowed["id"] != first["id"], "narrowed_claims": narrowed["denominator"]["claims"]}

    case = ctx.case("project-summary", project=True)
    captured = []
    with api.injected_capture(case.insp, accepting(case.fake, captured)):
        report, _ = case.inspect(["python -m pytest backend/probes -q", {"summary": "all green"}])
        states = [f["state"] for f in report["findings"]]
        bypass = api.make_project(Artifacts(), profile(api), ctx.isolation(), case.tmp / "replays")
        bypass.profile = {**bypass.profile, "checks": [{**bypass.profile["checks"][0], "argv": ["uv", "run", "pytest"]}]}
        snapshot = bypass.snapshot(case.workspace)
        found = bypass.inspect([observed("unit")], str(case.workspace), {}, environment=snapshot["environment"],
                               interpreter=api.TRUSTED_PYTHON, project=snapshot["project"])
    out["never_reaches_a_container"] = {"states": states, "creates": len(case.creates()), "captured": len(captured),
                                        "bypass_state": found["findings"][0]["state"]}

    case = ctx.case("project-lost-owner", project=True)
    seen = []

    def lost(stage=None):
        if stage == "replay_wait":
            raise api.ContractError("Stale or expired task execution")
    with api.injected_capture(case.insp, refusing_at_wait(case, seen)):
        raised = expect(lambda: case.inspect([observed("unit"), observed("lint")], progress=lost))
    out["lost_owner"] = {"raised": ctx.show(raised), "records": case.records(),
                         "kills": [c["args"] for c in case.fake.calls if c["args"][0] == "kill"] == [["kill", seen[0]]],
                         "replays_started": len(seen), "unresolved": case.unresolved()}

    case = ctx.case("project-ctor", project=True)
    isolation = ctx.isolation()
    host = api.parse_profile(document(api, schema=api.SCHEMA, interpreter=PY), api.packaged_policy())
    out["constructor_refusals"] = {
        "host_profile": ctx.show(expect(lambda: api.make_project(Artifacts(), host, isolation, case.tmp / "r1"))),
        "other_image": ctx.show(expect(lambda: api.make_project(Artifacts(), profile(api), ctx.isolation(image=OTHER_IMAGE), case.tmp / "r2"))),
        "no_isolation": ctx.show(expect(lambda: api.make_project(Artifacts(), profile(api), None, case.tmp / "r3"))),
        "not_a_profile": ctx.show(expect(lambda: api.make_project(Artifacts(), {"profile_digest": 1}, isolation, case.tmp / "r4"))),
        "roots_created": sorted(p.name for p in case.tmp.iterdir())}
    insp = api.make_project(Artifacts(), profile(api), isolation, case.tmp / "replays")
    out["project_inspector"] = {"trusted_none": insp._trusted(None), "trusted_image": insp._trusted(api.TRUSTED_PYTHON),
                                "trusted_other": ctx.show(expect(lambda: insp._trusted("/usr/bin/python3"))), "python": insp._python(),
                                "execution": ctx.show(insp.execution), "snapshot_needs_cwd": ctx.show(expect(lambda: insp.snapshot())),
                                "replay_is_the_docker_one": type(insp)._replay is api.DockerEvidenceInspector._replay}
    return out


def run(api, root: Path) -> dict:
    ctx = Ctx(api, root.resolve())
    os.umask(0o022)
    return {"j1_identity_and_refusals": j1_identity_and_refusals(ctx), "j2_lifecycle": j2_lifecycle(ctx),
            "j3_interruptions": j3_interruptions(ctx), "j4_failures": j4_failures(ctx), "j5_real_capture": j5_real_capture(ctx),
            "j6_project_in_container": j6_project_in_container(ctx)}
