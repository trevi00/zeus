"""INV-ISOLATED-WORKER-001: an opt-in, host-owned Docker boundary around the trusted Claude runtime.

The host selects isolation (`ZEUS_WORKER_ISOLATION=docker`, `ZEUS_WORKER_IMAGE=sha256:<64hex>`);
nothing here is read from an assignment or a model output, and a selected isolation never falls
back to host execution. The outer adapter owns the source staging, the container and the import of
results; the image's trusted entrypoint (`isolated_worker_entry`) reuses `ClaudeCodeRuntime`, so
schema, session, model, budget and terminal checks keep their one authority. An inner result is
returned only after the owned container is confirmed stopped, its output validated and imported,
and its evidence written outside the container.

Lifecycle: prepared -> created -> start_requested (external-effect boundary) -> running ->
stop_confirmed -> validated -> imported -> evidence_retained -> removed. A run record that stops
anywhere else stays on disk as the exact recovery reference and refuses the next run of that
workspace until `reconcile` proves the exact named, labelled container is gone.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import no_console_kwargs, run_process
from codex_harness.adapters.process_tree import ProcessTree
from codex_harness.adapters.worker_profile import hook_receipts, load_profile, profile_digest
from codex_harness.domain.model import ContractError, canonical, digest, require
from codex_harness.domain.policy import POLICY

DRIVER_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MODE = "docker"
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
LABEL = "zeus.isolated.run"
ROLE_LABEL = "zeus.isolated.role"
PROTOCOL = "zeus-isolated-worker-v1"
ENTRY_MODULE = "codex_harness.adapters.isolated_worker_entry"
TRUSTED_PYTHON = "/opt/zeus/bin/python"
WORKSPACE, EVIDENCE = "/workspace", "/evidence"
CONTAINER_HOME = "/home/worker"
MAX_FILES, MAX_TOTAL_BYTES, MAX_FILE_BYTES = 10000, 256 * 1024 * 1024, 16 * 1024 * 1024
# Fixed, recorded and bound into the operation and replay identities; not tunable per task.
LIMITS = {"memory": "4g", "cpus": "2", "pids": 512, "tmp_mb": 512, "home_mb": 256,
          "inner_grace_seconds": 45, "cleanup_seconds": 30, "docker_command_seconds": 60,
          "max_files": MAX_FILES, "max_total_bytes": MAX_TOTAL_BYTES, "max_file_bytes": MAX_FILE_BYTES}
GENERATED = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}
WINDOWS_UNSAFE = re.compile(r'[<>:"\\|?*\x00-\x1f]')
DOCKER_CLIENT_ENVIRONMENT = ("PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "COMSPEC", "TEMP", "TMP", "HOME",
                             "USERPROFILE", "PROGRAMDATA", "ProgramData", "DOCKER_HOST", "DOCKER_CONTEXT",
                             "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")
RESOLVED = ("removed", "refused")


class IsolationError(ContractError):
    """A refusal or failure of the isolated path; the code is printable, the detail never a secret."""

    def __init__(self, reason_code: str, detail: str = ""):
        super().__init__("isolated worker: " + reason_code + (": " + detail if detail else ""))
        self.reason_code = reason_code


# ---- configuration ------------------------------------------------------------------------------
def load_isolation(host_settings) -> dict | None:
    """The host's isolation selection, or None when neither name is set (exact host behaviour).
    Unknown or partial configuration refuses; it is never repaired and never ignored."""
    mode = str(host_settings.get("ZEUS_WORKER_ISOLATION") or host_settings.get("HARNESS_WORKER_ISOLATION") or "").strip()
    image = str(host_settings.get("ZEUS_WORKER_IMAGE") or host_settings.get("HARNESS_WORKER_IMAGE") or "").strip()
    if not mode and not image:
        return None
    if mode != MODE:
        raise IsolationError("isolation_config_invalid", "ZEUS_WORKER_ISOLATION must be 'docker' when a worker image is set")
    if IMAGE.fullmatch(image) is None:
        raise IsolationError("isolation_config_invalid", "ZEUS_WORKER_IMAGE must be an immutable sha256:<64hex> image id")
    body = {"mode": MODE, "image": image, "limits": dict(LIMITS), "driver_sha256": DRIVER_HASH,
            "protocol": PROTOCOL, "network": {"worker": "bridge", "verifier": "none"}}
    return {**body, "digest": digest(body)}


def summary(config: dict) -> dict:
    return {key: config[key] for key in ("mode", "image", "limits", "driver_sha256", "protocol", "network", "digest")}


def docker_environment(base=None, *, token: bool = False) -> dict:
    """The docker client's environment: an allow-list, with the worker token only for the one
    `create` that names it. The value never appears in an argv."""
    source = os.environ if base is None else base
    env = {name: source[name] for name in DOCKER_CLIENT_ENVIRONMENT if name in source}
    if token and source.get(TOKEN_NAME):
        env[TOKEN_NAME] = source[TOKEN_NAME]
    return env


def _docker(docker, args, *, timeout, env=None):
    try:
        return run_process([docker, *args], timeout=timeout, env=env if env is not None else docker_environment())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([docker, *args], None, "", type(exc).__name__)


def preflight(config: dict, docker: str = "docker", environment=None, *, token: bool = True) -> dict:
    """Refuse before any provider entry: no daemon, no such immutable image, or no worker token."""
    seconds = config["limits"]["docker_command_seconds"]
    env = docker_environment(environment)
    daemon = _docker(docker, ["version", "--format", "{{.Server.Version}}"], timeout=seconds, env=env)
    if daemon.returncode != 0 or not daemon.stdout.strip():
        raise IsolationError("docker_unavailable")
    image = _docker(docker, ["image", "inspect", "--format", "{{.Id}}", config["image"]], timeout=seconds, env=env)
    if image.returncode != 0 or image.stdout.strip() != config["image"]:
        raise IsolationError("worker_image_unavailable")
    source = os.environ if environment is None else environment
    if token and not source.get(TOKEN_NAME):
        raise IsolationError("worker_token_missing", TOKEN_NAME + " is not set for this process")
    return {"docker_server": daemon.stdout.strip(), "image": config["image"],
            "token": {"name": TOKEN_NAME, "present": bool(source.get(TOKEN_NAME))} if token else None}


def isolated_review_context(cwd, config: dict) -> dict:
    """What the host lead is told in this mode: review the diff and preserved observations only."""
    return {"cwd": str(Path(cwd).resolve()), "interpreter": None, "src": None, "isolation": summary(config),
            "instruction": "Worker and verifier ran in isolated containers. Do not run candidate code, tests or "
            "scripts on this host. Review the diff read-only together with the preserved evidence inspection; "
            "all executable evidence is supplied by the isolated inspector. Do not create files in the checkout. "
            "Record one concise frame and verdict in your response."}


# ---- safe paths and trees -----------------------------------------------------------------------
def check_relative_path(name: str) -> tuple:
    """A path that is safe on Linux and on a Windows host alike, or a refusal."""
    if type(name) is not str or not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise IsolationError("source_path_unsafe", repr(name)[:200])
    parts = tuple(name.split("/"))
    for part in parts:
        if (part in ("", ".", "..") or WINDOWS_UNSAFE.search(part) or part.endswith((".", " "))
                or part.split(".")[0].upper() in WINDOWS_RESERVED or part.lower() == ".git"):
            raise IsolationError("source_path_unsafe", repr(name)[:200])
    return parts


def check_bounds(entries) -> dict:
    """`entries` is [(path, bytes)]: counts, sizes and case collisions, files against directories too."""
    if len(entries) > MAX_FILES:
        raise IsolationError("source_too_many_files", str(len(entries)))
    seen, directories, total = set(), set(), 0
    for name, size in entries:
        parts = check_relative_path(name)
        if size > MAX_FILE_BYTES:
            raise IsolationError("source_file_too_large", repr(name)[:200])
        total += size
        if total > MAX_TOTAL_BYTES:
            raise IsolationError("source_too_large")
        folded = "/".join(parts).casefold()
        if folded in seen:
            raise IsolationError("source_case_collision", repr(name)[:200])
        seen.add(folded)
        for depth in range(1, len(parts)):
            directories.add(("/".join(parts[:depth]).casefold(), "/".join(parts[:depth])))
    spelled = {}
    for folded, actual in directories:
        if folded in seen or spelled.setdefault(folded, actual) != actual:
            raise IsolationError("source_case_collision", repr(actual)[:200])
    return {"files": len(entries), "bytes": total}


def list_revision(repository, revision: str) -> list:
    """[(mode, sha, size, path)] of the pinned candidate, read by host git from the REAL checkout."""
    listing = subprocess.run(["git", "-C", str(repository), "ls-tree", "-r", "-z", "-l", "--full-tree", revision],
                             capture_output=True, timeout=120, **no_console_kwargs())
    if listing.returncode != 0:
        raise IsolationError("source_revision_unavailable")
    entries = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, raw = record.partition(b"\t")
        mode, kind, sha, size = meta.decode("ascii").split()
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IsolationError("source_path_unsafe", "path is not UTF-8") from exc
        if kind != "blob" or mode not in ("100644", "100755"):
            # 120000 symlink, 160000 submodule and anything else: explicit refusal, never inert copies.
            raise IsolationError("source_entry_unsupported", mode + " " + repr(name)[:200])
        entries.append((mode, sha, int(size), name))
    return entries


def stage_source(repository, revision: str, destination: Path) -> dict:
    """Export the pinned revision into a fresh directory: validated first, materialized after."""
    entries = list_revision(repository, revision)
    bounds = check_bounds([(name, size) for _, _, size, name in entries])
    destination = Path(destination)
    require(not destination.exists(), "Staging directory must be fresh")
    destination.mkdir(parents=True)
    root = destination.resolve()
    reader = subprocess.Popen(["git", "-C", str(repository), "cat-file", "--batch"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **no_console_kwargs())

    def request():
        try:
            reader.stdin.write(b"".join(sha.encode("ascii") + b"\n" for _, sha, _, _ in entries))
            reader.stdin.close()
        except OSError:
            pass
    writer = threading.Thread(target=request, daemon=True)
    writer.start()
    manifest = {}
    try:
        for mode, sha, size, name in entries:
            header = reader.stdout.readline().split()
            if len(header) != 3 or header[0].decode("ascii") != sha or header[1] != b"blob" or int(header[2]) != size:
                raise IsolationError("source_read_failed", repr(name)[:200])
            data = reader.stdout.read(size)
            if len(data) != size or reader.stdout.read(1) != b"\n":
                raise IsolationError("source_read_failed", repr(name)[:200])
            target = root.joinpath(*name.split("/"))
            require(root in target.resolve().parents, "Unsafe source path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if mode == "100755":
                target.chmod(0o755)
            manifest[name] = hashlib.sha256(data).hexdigest()
    finally:
        reader.kill()
        reader.wait(timeout=20)
        writer.join(timeout=5)
        reader.stdout.close()
    return {"revision": revision, **bounds, "manifest": manifest, "manifest_sha256": digest(manifest)}


def init_standalone_git(staging: Path) -> dict:
    """A minimal repository for the worker's read-only git commands: no remote, no hook, nothing from
    the host's .git. Host git touches this directory only here, before the worker exists."""
    base = ["git", "-C", str(staging), "-c", "core.autocrlf=false", "-c", "core.hooksPath=", "-c", "core.fileMode=false",
            "-c", "user.name=Zeus Staging", "-c", "user.email=staging@localhost", "-c", "commit.gpgsign=false"]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    for args in (["init", "-q"], ["add", "-A", "-f"], ["commit", "-q", "--no-verify", "-m", "staged candidate"]):
        result = subprocess.run([*base, *args], capture_output=True, timeout=600, env=env, **no_console_kwargs())
        if result.returncode != 0:
            raise IsolationError("source_git_init_failed", args[0])
    return {"initialized": True, "remotes": 0, "hooks": "none", "note": "host git is never run here again"}


def scan_tree(root: Path, *, skip_top_git: bool = True) -> dict:
    """{relative path: sha256} of the regular files under `root`, or a refusal. Links, devices,
    hardlinks, nested .git, unsafe names, collisions and oversize all refuse; the staged top-level
    .git and generated caches are excluded and never read or executed."""
    root = Path(root)
    found, sizes, stack = {}, [], [(root, ())]
    while stack:
        directory, parts = stack.pop()
        with os.scandir(directory) as listing:
            for entry in listing:
                relative = (*parts, entry.name)
                if (skip_top_git and relative == (".git",)) or entry.name in GENERATED:
                    continue
                info = entry.stat(follow_symlinks=False)
                name = "/".join(relative)
                reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if entry.is_symlink() or stat.S_ISLNK(info.st_mode) or reparse:
                    raise IsolationError("output_link_refused", repr(name)[:200])
                if stat.S_ISDIR(info.st_mode):
                    check_relative_path(name)
                    stack.append((Path(entry.path), relative))
                    continue
                if entry.name.endswith((".pyc", ".pyo")):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise IsolationError("output_special_file_refused", repr(name)[:200])
                if info.st_nlink > 1:
                    raise IsolationError("output_hardlink_refused", repr(name)[:200])
                sizes.append((name, info.st_size))
                if len(sizes) > MAX_FILES:
                    raise IsolationError("source_too_many_files")
                found[name] = entry.path
    check_bounds(sizes)
    hashed = {}
    for name, path in found.items():
        data = Path(path).read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise IsolationError("source_file_too_large", repr(name)[:200])
        hashed[name] = hashlib.sha256(data).hexdigest()
    return hashed


def plan_import(manifest: dict, staging: Path) -> dict:
    """Complete validation of the stopped container's output; nothing is written by this step."""
    after = scan_tree(staging)
    added = sorted(name for name in after if name not in manifest)
    modified = sorted(name for name in after if name in manifest and after[name] != manifest[name])
    deleted = sorted(name for name in manifest if name not in after)
    return {"added": added, "modified": modified, "deleted": deleted, "after_sha256": digest(after),
            "hashes": {name: after[name] for name in (*added, *modified)}}


def apply_import(plan: dict, staging: Path, candidate: Path) -> dict:
    """Copy validated regular bytes into the real candidate. Every target is contained and is never
    reached through a link; bytes are re-hashed so nothing that changed after validation enters."""
    staging, root = Path(staging), Path(candidate).resolve()
    for name in (*plan["added"], *plan["modified"], *plan["deleted"]):
        target = root.joinpath(*check_relative_path(name))
        if root not in target.resolve().parents or target.is_symlink():
            raise IsolationError("import_target_unsafe", repr(name)[:200])
    for name in (*plan["added"], *plan["modified"]):
        data = staging.joinpath(*name.split("/")).read_bytes()
        if hashlib.sha256(data).hexdigest() != plan["hashes"][name]:
            raise IsolationError("import_changed_after_validation", repr(name)[:200])
        target = root.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in plan["deleted"]:
        root.joinpath(*name.split("/")).unlink(missing_ok=True)
    return {key: plan[key] for key in ("added", "modified", "deleted", "after_sha256")}


# ---- run records: the recovery reference --------------------------------------------------------
def _write_record(path: Path, record: dict) -> dict:
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return {"file": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def new_record(directory: Path, *, role: str, workspace: str, config: dict, container, **extra) -> dict:
    """The durable owner of one container, worker or verifier: exact run, name and label from the
    first write, the exact id as soon as it is known."""
    return {"run_id": container.run_id, "role": role, "workspace": workspace, "image": config["image"],
            "isolation_digest": config["digest"], "container": None, "container_name": container.name,
            "label": LABEL + "=" + container.run_id, "record": str(Path(directory) / "run.json"), **extra,
            "lifecycle": [], "state": None}


def advance(record: dict, state: str, **detail) -> None:
    """One durable lifecycle step. A step that cannot be written is a named failure, never assumed."""
    previous = record["state"]
    record["lifecycle"].append({"state": state, "at": time.time(), **detail})
    record["state"] = state
    try:
        _write_record(Path(record["record"]), record)
    except OSError as exc:
        record["lifecycle"].pop()
        record["state"] = previous
        raise IsolationError("evidence_write_failed", state + " " + type(exc).__name__) from exc


def recovery_reference(container, record: dict) -> dict:
    return {"container": container.id, "name": container.name, "record": record["record"]}


def run_records(root: Path) -> list:
    records = []
    for path in sorted(Path(root).glob("*/run.json")) if Path(root).is_dir() else []:
        try:
            records.append(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            records.append({"run_id": path.parent.name, "state": "unreadable", "workspace": None,
                            "record": str(path)})
    return records


def unresolved_runs(root: Path, workspace: str | None = None) -> list:
    """Retained runs whose container is not proven gone. An unreadable record counts for every workspace."""
    return [{key: row.get(key) for key in ("run_id", "state", "container", "workspace", "record")}
            for row in run_records(root)
            if row.get("state") not in RESOLVED and (workspace is None or row.get("workspace") in (workspace, None))]


def container_args(config: dict, *, name: str, run_id: str, role: str, network: str, mounts: list,
                   environment: dict, pass_names: tuple, entry: list, workdir: str) -> list:
    """The one place a container's controls are composed, for the worker and the verifier alike.
    `pass_names` are environment NAMES whose value the docker client forwards; no value is in argv."""
    limits = config["limits"]
    user = (f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") and os.getuid() != 0 else "10001:10001")
    argv = ["create", "--name", name, "--label", LABEL + "=" + run_id, "--label", ROLE_LABEL + "=" + role,
            "--network", network, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", user, "--memory", limits["memory"], "--cpus", limits["cpus"],
            "--pids-limit", str(limits["pids"]), "--init", "--interactive",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,size={limits['tmp_mb']}m,mode=1777",
            "--tmpfs", f"{CONTAINER_HOME}:rw,nosuid,nodev,size={limits['home_mb']}m,mode=1777"]
    for source, target in mounts:
        argv += ["--mount", f"type=bind,source={source},target={target}"]
    for key, value in environment.items():
        argv += ["-e", key + "=" + value]
    for key in pass_names:
        argv += ["-e", key]
    return [*argv, "-w", workdir, "--entrypoint", entry[0], config["image"], *entry[1:]]


INSPECT_FORMAT = ('{"image":{{json .Image}},"user":{{json .Config.User}},"network":{{json .HostConfig.NetworkMode}},'
                  '"read_only":{{json .HostConfig.ReadonlyRootfs}},"cap_drop":{{json .HostConfig.CapDrop}},'
                  '"security_opt":{{json .HostConfig.SecurityOpt}},"memory":{{json .HostConfig.Memory}},'
                  '"nano_cpus":{{json .HostConfig.NanoCpus}},"pids_limit":{{json .HostConfig.PidsLimit}},'
                  '"privileged":{{json .HostConfig.Privileged}},"ports":{{json .HostConfig.PortBindings}},'
                  '"mounts":{{json .Mounts}},"labels":{{json .Config.Labels}}}')


class OwnedContainer:
    """One uniquely named, labelled container. Every command names the exact id; nothing here ever
    filters by a common prefix, and the environment (where the token lives) is never inspected."""

    def __init__(self, config: dict, docker: str, run_id: str, role: str):
        self.config, self.docker, self.run_id, self.role = config, docker, run_id, role
        self.name = "zeus-" + role + "-" + run_id
        self.id = None
        self.seconds = config["limits"]["docker_command_seconds"]

    def recover_id(self) -> str | None:
        """Exact name AND label, exactly one match; anything else is not ours to touch."""
        found = _docker(self.docker, ["ps", "-a", "--no-trunc", "--filter", "name=^/" + self.name + "$",
                                      "--filter", "label=" + LABEL + "=" + self.run_id, "--format", "{{.ID}}"],
                        timeout=self.seconds)
        ids = found.stdout.split() if found.returncode == 0 else []
        return ids[0] if len(ids) == 1 and CONTAINER_ID.fullmatch(ids[0]) else None

    def create(self, args: list, env: dict) -> str:
        created = _docker(self.docker, args, timeout=self.seconds, env=env)
        lines = created.stdout.split()
        candidate = lines[-1] if created.returncode == 0 and lines else ""
        self.id = candidate if CONTAINER_ID.fullmatch(candidate) else self.recover_id()
        if self.id is None:
            raise IsolationError("container_create_failed", "exit " + str(created.returncode))
        return self.id

    def inspect(self) -> dict | None:
        shown = _docker(self.docker, ["inspect", "--format", INSPECT_FORMAT, self.id], timeout=self.seconds)
        try:
            body = json.loads(shown.stdout) if shown.returncode == 0 else None
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        body["mounts"] = [{key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")}
                          for mount in body.get("mounts") or [] if isinstance(mount, dict)]
        return body

    def verify(self, expected_targets: set, network: str) -> dict:
        """Selected fields only, checked before start: the image and the mounts are what the host chose."""
        observed = self.inspect()
        bad = (observed is None or observed.get("image") != self.config["image"]
               or {mount["Destination"] for mount in observed["mounts"] if mount["Type"] == "bind"} != expected_targets
               or any(mount["Type"] not in ("bind", "tmpfs") for mount in observed["mounts"])
               or observed.get("network") != network or observed.get("read_only") is not True
               or observed.get("privileged") is not False or observed.get("ports")
               or "ALL" not in [str(cap).upper() for cap in observed.get("cap_drop") or []]
               or (observed.get("labels") or {}).get(LABEL) != self.run_id
               or not observed.get("memory") or not observed.get("pids_limit") or not observed.get("user"))
        if bad:
            raise IsolationError("container_controls_mismatch")
        return observed

    def state(self, timeout: float | None = None) -> dict | None:
        shown = _docker(self.docker, ["inspect", "--format", "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}",
                                      self.id], timeout=self.seconds if timeout is None else timeout)
        parts = shown.stdout.split()
        if shown.returncode != 0 or len(parts) != 3:
            return None
        return {"status": parts[0], "exit_code": int(parts[1]) if parts[1].lstrip("-").isdigit() else None,
                "oom_killed": parts[2] == "true"}

    def stop(self, window: float) -> dict:
        """Kill (when not seen stopped) and confirm by inspection within the cleanup window. Every
        Docker call here is bounded by what remains of that window, never by the general command limit."""
        deadline, killed, last = time.monotonic() + window, False, None
        while (remaining := deadline - time.monotonic()) > 0:
            last = self.state(min(self.seconds, remaining))
            if last is not None and last["status"] in ("exited", "dead", "created"):
                return {"confirmed": True, "killed": killed, **last}
            remaining = deadline - time.monotonic()
            if not killed and remaining > 0:
                _docker(self.docker, ["kill", self.id], timeout=min(self.seconds, remaining))
                killed = True
                continue
            time.sleep(max(0.0, min(0.5, deadline - time.monotonic())))
        return {"confirmed": False, "killed": killed, **(last or {"status": "unknown"})}

    def remove(self) -> dict:
        """Only this exact stopped container, never forced; absence afterwards is the proof."""
        removed = _docker(self.docker, ["rm", self.id], timeout=self.seconds)
        gone = removed.returncode == 0 and self.recover_id() is None
        return {"removed": gone, "exit_code": removed.returncode}


def join_cleanup(stop: dict, proofs: list) -> dict:
    """The one cleanup-proof join (C and P of the lifecycle table). C is the container's own stop
    confirmation; P is EVERY supplied client/capture proof being a record whose `confirmed` is exactly
    True. No proof, a missing one (None) or a malformed one is unknown, and no supplied false/unknown
    is ever overwritten by another true. The proofs themselves stay in the durable stop."""
    container = stop.get("confirmed") is True
    client = bool(proofs) and all(isinstance(proof, dict) and proof.get("confirmed") is True for proof in proofs)
    return {**stop, "confirmed": container and client, "container_confirmed": container, "client_confirmed": client}


def cleanup_debt(record: dict) -> str | None:
    """The same join read back from the durable record: None only when the last recorded stop is a
    full positive join, otherwise the named reason retirement (and, for client debt, reconcile) refuses."""
    stops = [step["stop"] for step in record.get("lifecycle") or [] if isinstance(step.get("stop"), dict)]
    if not stops:
        return "stop_unrecorded"
    if stops[-1].get("client_confirmed") is not True:
        return "client_cleanup_unconfirmed"
    return None if stops[-1].get("confirmed") is True else "container_stop_unconfirmed"


def retire(container, record: dict, result: dict, outcome: str, *, files: dict | None = None,
           removed: dict | None = None) -> dict:
    """Observations first, durably and outside the container; only then is the exact stopped container
    removed. An observation that cannot be written keeps the container and its recovery reference, and
    a record without a full positive cleanup join is never retired: nothing is written or removed."""
    reference = recovery_reference(container, record)
    debt = cleanup_debt(record)
    if debt is not None:
        return {"removed": False, "exit_code": None, "evidence_written": False, "recovery": reference, "refused": debt}
    try:
        record["retained_files"] = {name: _write_record(Path(record["record"]).with_name(name), body)
                                    for name, body in (files or {}).items()}
        record["result"] = result
        advance(record, "evidence_retained", outcome=outcome)
    except (IsolationError, OSError):
        return {"removed": False, "exit_code": None, "evidence_written": False, "recovery": reference}
    removal = container.remove()
    if removal["removed"]:
        advance(record, "removed", **(removed or {}))
    return {**removal, "evidence_written": True, "recovery": None if removal["removed"] else reference}


def hold(container, record: dict, body, *, client=None, proof=None, detail=None):
    """The one ownership rule of every started container, worker and verifier alike. The exact
    run/name/label/id is durable at `start_requested` before `body` may start anything; however `body`
    ends (return, cancel, deadline, observer failure, KeyboardInterrupt) the container gets one bounded
    stop and confirmation. Unconfirmed is recorded as `stop_unconfirmed` with its recovery reference.
    Returns (value, stop); an exception of `body` propagates after the record says what was confirmed.

    A return of `body` is not proof that its resources are gone. Positive cleanup proof comes from the
    `client` callback (the worker's own tree) and/or from `proof(value)` (the verifier capture's
    `cleanup` record), or the `capture_cleanup` of the exception that replaced the return; with `proof`
    given, an absent or malformed record is unknown. `join_cleanup` combines them with the stop."""
    try:
        advance(record, "start_requested", recovery=recovery_reference(container, record))
    except IsolationError:
        container.remove()  # never started and no durable owner: exact id, not forced
        raise
    value, interrupted, capture, supplied = None, None, None, proof is not None
    try:
        value = body()
        if proof is not None:
            try:
                capture = proof(value)
            except Exception:  # a value the proof cannot be read from is a missing proof
                capture = None
    except BaseException as exc:
        interrupted = type(exc).__name__
        # A body that reclaimed its own client tree before propagating says what it left (the shared
        # bounded capture does); unreclaimed client debt is never a confirmed stop.
        capture = getattr(exc, "capture_cleanup", None)
        supplied = supplied or capture is not None
        raise
    finally:
        stopped = container.stop(container.config["limits"]["cleanup_seconds"])
        proofs = [client()] if client is not None else []
        if supplied:
            proofs.append(capture)
            stopped = {**stopped, "capture_cleanup": capture}
        stopped = join_cleanup(stopped, proofs)
        if not stopped["confirmed"]:
            advance(record, "stop_unconfirmed", stop=stopped, interrupted=interrupted,
                    recovery=recovery_reference(container, record))
        else:
            described = detail(value) if detail is not None and interrupted is None else {}
            advance(record, "stop_confirmed", stop=stopped, interrupted=interrupted, **described)
            if interrupted is not None:
                retire(container, record, {"interrupted": interrupted, "stop": stopped}, "interrupted")
    return value, stopped


def reconcile(run_directory, docker: str = "docker") -> dict:
    """Operator step for a retained run: mark it removed only when the exact named, labelled
    container is absent. It never removes a container and never touches another run. Container
    absence says nothing about the host-side client/capture: recorded unconfirmed client debt is
    refused by name and the record stays unresolved until that debt is independently resolved."""
    path = Path(run_directory) / "run.json"
    record = json.loads(path.read_text("utf-8"))
    if cleanup_debt(record) == "client_cleanup_unconfirmed":
        return {"reconciled": False, "run_id": record["run_id"], "container": record.get("container"),
                "reason": "client_cleanup_unconfirmed"}
    probe = OwnedContainer({"limits": LIMITS, "image": record.get("image")}, docker, record["run_id"], record["role"])
    listed = _docker(docker, ["ps", "-a", "--no-trunc", "--filter", "name=^/" + probe.name + "$", "--format", "{{.ID}}"],
                     timeout=LIMITS["docker_command_seconds"])
    if listed.returncode != 0 or listed.stdout.split():
        return {"reconciled": False, "run_id": record["run_id"], "container": record.get("container"),
                "reason": "docker_unavailable" if listed.returncode != 0 else "container_still_present"}
    record["lifecycle"].append({"state": "removed", "at": time.time(), "by": "reconcile"})
    record["state"] = "removed"
    _write_record(path, record)
    return {"reconciled": True, "run_id": record["run_id"]}


# ---- the outer runtime --------------------------------------------------------------------------
def _scrub(value, secret: str | None):
    if not secret:
        return value
    text = json.dumps(value, ensure_ascii=False)
    return json.loads(text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "<redacted>")) if secret in text or \
        json.dumps(secret, ensure_ascii=False)[1:-1] in text else value


class IsolatedClaudeRuntime:
    """The executor's transport contract (context manager, `run`, `enters_on_open`) over an owned
    container. It parses no provider stream: events and the result are the inner runtime's."""

    enters_on_open = False

    def __init__(self, config: dict, root, *, model: str, runtime: dict | None = None,
                 max_budget_usd: float | None = None, settings_document: dict | None = None,
                 docker: str = "docker", environment: dict | None = None, watch: tuple = ()):
        require(isinstance(config, dict) and config.get("mode") == MODE and IMAGE.fullmatch(str(config.get("image"))),
                "Isolated runtime requires a validated isolation configuration")
        require(type(model) is str and bool(model.strip()), "Claude requires an explicit model name")
        self.config, self.root, self.docker = config, Path(root), docker
        self.watch = tuple(Path(other) for other in watch)  # sibling record roots: the verifier's replays
        self.model, self.max_budget_usd, self.settings_document = model.strip(), max_budget_usd, settings_document
        # Host paths never cross: the image's own interpreter, executable and evidence root apply.
        self.runtime = {key: value for key, value in dict(runtime or {}).items()
                        if key not in ("profile_interpreter", "profile_evidence_root")}
        self.environment_source = environment
        self.profile = load_profile(self.runtime["worker_profile"]) if self.runtime.get("worker_profile") is not None else None
        self.container, self.tree, self.record, self.record_path = None, None, None, None
        self.used = False

    def __enter__(self):
        self.preflight = preflight(self.config, self.docker, self.environment_source)
        return self

    def __exit__(self, *_):
        if self.tree is not None:
            self.tree.terminate("context_exit")
            self.tree.close()
            self.tree = None

    def _advance(self, state: str, **detail) -> None:
        advance(self.record, state, **detail)

    def _end_client(self) -> dict:
        if self.tree is None:
            return {"confirmed": True}
        ended = self.tree.terminate("container_stopped")
        self.tree.close()
        self.tree = None
        return ended

    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 240, *, on_event=None, on_tick=None,
            read_only: bool = False, model: str | None = None, on_enter=None, cancel=None,
            session_id: str | None = None) -> dict:
        require(type(timeout) in (int, float) and 0 < timeout < float("inf"), "Execution timeout must be finite and positive")
        require(type(prompt) is str and bool(prompt), "Claude execution requires a prompt")
        require(not read_only, "The isolated worker is not assigned reviews")
        require(not self.used, "This transport object already ran; every attempt builds its own")
        require(model is None or model == self.model, "The requested model differs from the configured Claude model")
        self.used = True
        workspace = str(Path(cwd).resolve())
        pending = [row for root in (self.root, *self.watch) for row in unresolved_runs(root, workspace)]
        if pending:
            # Visible and refused: no duplicate container, no implicit restart, no model retry.
            raise IsolationError("isolation_unresolved_run", json.dumps(pending, sort_keys=True))
        session_id = session_id or str(uuid4())
        run_id = uuid4().hex
        run_directory = self.root / run_id
        staging, evidence = run_directory / "workspace", run_directory / "evidence"
        evidence.mkdir(parents=True)
        self.record_path = run_directory / "run.json"
        self.container = OwnedContainer(self.config, self.docker, run_id, "worker")
        self.record = new_record(run_directory, role="worker", workspace=workspace, config=self.config,
                                 container=self.container, session_id=session_id, staging=str(staging),
                                 evidence=str(evidence))
        source_environment = os.environ if self.environment_source is None else self.environment_source
        secret = source_environment.get(TOKEN_NAME)
        try:
            revision = subprocess.run(["git", "-C", workspace, "rev-parse", "HEAD"], capture_output=True, text=True,
                                      timeout=60, **no_console_kwargs())
            if revision.returncode != 0:
                raise IsolationError("source_revision_unavailable")
            dirty = subprocess.run(["git", "-C", workspace, "status", "--porcelain"], capture_output=True, text=True,
                                   timeout=120, **no_console_kwargs())
            if dirty.returncode != 0 or dirty.stdout.strip():
                raise IsolationError("source_candidate_dirty")
            source = stage_source(workspace, revision.stdout.strip(), staging)
            git_report = init_standalone_git(staging)
            self._advance("prepared", source={key: source[key] for key in ("revision", "files", "bytes", "manifest_sha256")})
            entry = [TRUSTED_PYTHON, "-I", "-m", ENTRY_MODULE]
            environment = {"HOME": CONTAINER_HOME, "DISABLE_AUTOUPDATER": "1", "PYTHONDONTWRITEBYTECODE": "1",
                           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "PYTHONIOENCODING": "utf-8",
                           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": WORKSPACE}
            args = container_args(self.config, name=self.container.name, run_id=run_id, role="worker", network="bridge",
                                  mounts=[(str(staging.resolve()), WORKSPACE), (str(evidence.resolve()), EVIDENCE)],
                                  environment=environment, pass_names=(TOKEN_NAME,), entry=entry, workdir="/")
            require(secret is None or all(secret not in part for part in args), "A credential value reached an argv")
            try:
                container_id = self.container.create(args, docker_environment(self.environment_source, token=True))
            except IsolationError:
                self._advance("refused", reason="container_create_failed")
                raise
            self.record["container"] = container_id
            try:
                self._advance("created", container=container_id)
                controls = self.container.verify({WORKSPACE, EVIDENCE}, "bridge")
            except IsolationError as exc:
                removal = self.container.remove()  # never started: exact id, not forced
                self._advance("refused" if removal["removed"] else "created", reason=exc.reason_code)
                raise
        except IsolationError:
            if self.record["state"] is None:
                self._advance("refused", reason="before_container")
            raise
        request = {"protocol": PROTOCOL, "prompt": prompt, "schema": schema, "timeout": timeout, "model": self.model,
                   "session_id": session_id, "runtime": self.runtime, "max_budget_usd": self.max_budget_usd,
                   "settings_document": self.settings_document, "cwd": WORKSPACE, "evidence_root": EVIDENCE}
        started = time.monotonic()

        def converse():
            if on_enter is not None:
                on_enter()
            return self._converse(request, timeout, on_event=on_event, on_tick=on_tick, cancel=cancel)
        # External-effect boundary (`start_requested`, written by `hold`): from here on nothing is a
        # refusal that never ran, and the container is stopped however the conversation ends.
        stream, stopped = hold(self.container, self.record, converse, client=self._end_client, detail=lambda value: {
            "stream": {key: value[key] for key in ("reason", "violation", "lines")}})
        if not stopped["confirmed"]:
            raise ContractError("Isolated worker container termination could not be confirmed; the outcome is unknown; "
                                "recovery record " + str(self.record_path))
        inner = stream["result"]
        receipts = (hook_receipts(evidence / session_id, profile_digest(self.profile)) if self.profile is not None else None)
        isolation = {**summary(self.config), "run_id": run_id, "container": {"id": self.container.id, "name": self.container.name,
                                                                           "controls": controls, "stop": stopped},
                     "source": {key: source[key] for key in ("revision", "files", "bytes", "manifest_sha256")},
                     "staging_git": git_report, "preflight": self.preflight, "record": str(self.record_path),
                     "credential": {"name": TOKEN_NAME, "transport": "docker client environment by name; never argv"},
                     "cli_version": ((inner or {}).get("command") or {}).get("cli_version"),
                     "harness": {"profile_digest": profile_digest(self.profile) if self.profile is not None else None,
                                 "document_sha256": self.profile.get("document_sha256") if self.profile else None,
                                 "host_observed_hook_receipts": receipts,
                                 "note": "receipts are files the hook wrote into the mounted evidence directory, read "
                                         "by the host after the container stopped; absence is not observed, never assumed"},
                     "stream": {key: stream[key] for key in ("reason", "violation", "lines", "stderr_tail")},
                     "elapsed_seconds": time.monotonic() - started}
        failure = None
        try:
            if inner is None:
                failure = IsolationError("protocol_result_missing", str(stream["violation"] or stream["reason"]))
            else:
                plan = plan_import(source["manifest"], staging)
                self._advance("validated", changes={key: len(plan[key]) for key in ("added", "modified", "deleted")})
                isolation["import"] = apply_import(plan, staging, Path(workspace))
                self._advance("imported")
        except IsolationError as exc:
            failure = exc
        except OSError as exc:
            failure = IsolationError("import_failed", type(exc).__name__)
        isolation["outcome"] = "imported" if failure is None else failure.reason_code
        # The whole redacted inner result is retained beside the record before the container is removed.
        removal = retire(self.container, self.record,
                         _scrub({"isolation": isolation, "inner_failure": (inner or {}).get("failure"),
                                 "inner_terminal": (inner or {}).get("terminal")}, secret), isolation["outcome"],
                         files={"inner_result.json": _scrub(inner, secret)} if inner is not None else None,
                         removed={"staging_retained": failure is not None})
        isolation["cleanup"] = {**removal, "staging_retained": failure is not None or not removal["removed"]}
        if not removal["evidence_written"]:
            raise ContractError("Isolated worker evidence could not be written; the stopped container and staging are "
                                "retained; recovery record " + str(self.record_path))
        if removal["removed"] and failure is None:
            shutil.rmtree(staging, ignore_errors=True)  # this run's own staging; evidence and record stay
        if failure is not None:
            # Entered and not importable: never a success, never a partial import, staging preserved.
            raise ContractError(str(failure) + "; staging preserved; recovery record " + str(self.record_path)) from failure
        return _scrub({**inner, "isolation": isolation}, secret)

    def _converse(self, request: dict, timeout, *, on_event, on_tick, cancel) -> dict:
        """Start attached, send one request, forward tagged events; every irregularity is named."""
        limits = self.config["limits"]
        # An event is one inner line (already bounded by the runtime); the result carries no events.
        line_limit = max(4 * POLICY.claude_line_bytes + 65536, 16 * 1024 * 1024)
        self.tree = ProcessTree.spawn([self.docker, "start", "--attach", "--interactive", self.container.id],
                                      env=docker_environment(self.environment_source), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = self.tree.process
        self._advance("running", client_pid=process.pid)
        inbox: queue.Queue = queue.Queue(maxsize=POLICY.claude_event_queue)
        tail = [b""]

        def send():
            try:
                process.stdin.write(canonical(request).encode("utf-8") + b"\n")
                process.stdin.close()
            except OSError:
                pass

        def read():
            try:
                while line := process.stdout.readline(line_limit + 1):
                    inbox.put(line)
            except (OSError, ValueError):
                pass
            inbox.put(None)

        def errors():
            try:
                while block := process.stderr.read(4096):
                    tail[0] = (tail[0] + block)[-4096:]
            except (OSError, ValueError):
                pass
        threads = [threading.Thread(target=target, daemon=True) for target in (send, read, errors)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + float(timeout) + limits["inner_grace_seconds"]
        events, result, reason, violation, lines, dropped = [], None, None, None, 0, 0
        # A lease check or observer that raises here propagates to `hold`, which owns the stop.
        while reason is None:
            if cancel is not None and cancel():
                reason = "cancelled"
                break
            if on_tick is not None:
                on_tick()
            if time.monotonic() >= deadline:
                reason = "deadline"
                break
            try:
                line = inbox.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                reason = "stream_closed"
                break
            lines += 1
            message = parse_line(line, line_limit)
            if message is None or result is not None:
                violation = "invalid_line" if message is None else "output_after_result"
                reason, result = "protocol_violation", None
                break
            if message["kind"] == "event":
                if len(events) < POLICY.claude_events_retained:
                    events.append(message["event"])
                else:
                    dropped += 1
                if on_event is not None:
                    on_event(message["event"])
            elif message["kind"] == "result":
                result = message["result"]
            elif message["kind"] == "refused":
                violation, reason = "inner_refused:" + str(message.get("error_type")), "inner_refused"
        if result is not None and reason == "stream_closed":
            result = {**result, "events": events}
        else:
            violation = violation or ("truncated_before_result" if reason == "stream_closed" else reason)
            result = None
        return {"result": result, "reason": reason, "violation": violation, "lines": lines, "events_dropped": dropped,
                "stderr_tail": tail[0].decode("utf-8", errors="replace")}


def parse_line(line: bytes, limit: int) -> dict | None:
    """One tagged protocol line, or None for anything else: overlong, unterminated, untagged, mistyped."""
    if len(line) > limit or not line.endswith(b"\n"):
        return None
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(message, dict) or message.get("protocol") != PROTOCOL:
        return None
    kind = message.get("kind")
    if kind in ("entered", "refused"):
        return message
    if kind in ("event", "result") and isinstance(message.get(kind), dict):
        return message
    return None


class IsolatedWorker:
    """What bootstrap hands the executor: the validated selection and where its runs live."""

    def __init__(self, config: dict, root, docker: str = "docker"):
        self.config, self.root, self.docker = config, Path(root), docker

    def runtime(self, *, model, runtime, max_budget_usd, settings_document) -> IsolatedClaudeRuntime:
        return IsolatedClaudeRuntime(self.config, self.root / "runs", model=model, runtime=runtime,
                                     max_budget_usd=max_budget_usd, settings_document=settings_document,
                                     docker=self.docker, watch=(self.root / "replays",))

    def inspector(self, artifacts):
        from codex_harness.adapters.isolated_evidence import DockerEvidenceInspector
        return DockerEvidenceInspector(artifacts, self.config, self.root / "replays", docker=self.docker)


if __name__ == "__main__":  # python -m codex_harness.adapters.isolated_worker status <dir>...|reconcile <dir>
    if len(sys.argv) >= 3 and sys.argv[1] == "status":  # the worker's runs and the verifier's replays alike
        print(json.dumps([row for root in sys.argv[2:] for row in unresolved_runs(Path(root))], sort_keys=True))
    elif len(sys.argv) == 3 and sys.argv[1] == "reconcile":
        print(json.dumps(reconcile(sys.argv[2]), sort_keys=True))
    else:
        raise SystemExit(2)
