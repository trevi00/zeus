"""The fixed role-container specification: isolation configuration, the four profiles, the docker argv.

Layer: domain
Context: execution
Owns: the isolation configuration parse (`load_isolation`, `summary`), the container constants (mode,
    image/id shapes, labels, request protocols, mount targets, fixed limits), the four profile shapes
    (`PROFILES`), the fixed container environments (`worker_environment`, `codex_environment`), the
    read-only role binds (`read_only_mounts`), THE one docker `create` argv composer (`container_args`),
    the post-create inspection format and the forbidden-control rule (`forbidden_controls`)
Does not own: which profile a routing result maps to (routing.domain.profiles), the host uid/gid or
    operator home (read by execution.adapters.containers and passed in), running docker
    (execution.adapters.containers), credentials (credentials)
Entry points: load_isolation, summary, container_args, forbidden_controls, worker_environment,
    codex_environment, read_only_mounts, request_protocol, PROFILES, LIMITS, INSPECT_FORMAT, FORBIDDEN_SOURCES
Contracts: INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001

Moved from SOURCE M7 `adapters/isolated_worker` and `adapters/role_containers` (the pure halves), and
characterized first by the `containers.profiles` golden. Two inputs M7 read inside the composer are
parameters here (RESEARCH-S3 F-R6): `container_args(..., user=)` (M7 read `os.getuid()`/`os.getgid()`)
and `forbidden_controls(observed, home=)` (M7 read `Path.home()`); the adapter supplies both, with the
same values, so the argv and verdicts are unchanged. `load_isolation(..., driver_sha256=)` takes the
driver identity from the adapter that owns the container code (M7 hashed its own module file): the
identity string changes with the moved code, a declared identity change, never a behaviour change.
RESEARCH-S3 G1/R1: the argv is the declared boundary; the inspection rule re-checks what the daemon
actually applied. F-R1 (an inspected `seccomp=unconfined` is not refused) is preserved as characterized.
"""

from __future__ import annotations

import os
import re

from codex_harness.credentials.domain.codex_credential import CODEX_HOME, SETTLED_RUN_STATES
from codex_harness.kernel.errors import IsolationError, require
from codex_harness.kernel.ids import digest

MODE = "docker"
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
LABEL = "zeus.isolated.run"
ROLE_LABEL = "zeus.isolated.role"
PROTOCOL = "zeus-isolated-worker-v1"
# A request that carries a host project-evidence delivery names its own protocol, so an image whose
# entry predates delivery refuses it explicitly (`inner_refused`) instead of dropping the profile.
DELIVERY_PROTOCOL = "zeus-isolated-worker-v1-project-evidence"
# INV-WORKER-SESSION-001: a request that carries a task session names its own protocol.
SESSION_PROTOCOL = "zeus-isolated-worker-v1-task-session"
SESSION_DELIVERY_PROTOCOL = "zeus-isolated-worker-v1-project-evidence-task-session"
DELIVERY_PROTOCOLS = (DELIVERY_PROTOCOL, SESSION_DELIVERY_PROTOCOL)
SESSION_PROTOCOLS = (SESSION_PROTOCOL, SESSION_DELIVERY_PROTOCOL)
# INV-ROLE-CONTAINER-001: a read-only role request (claude-role-ro) names its own protocol.
READ_ONLY_PROTOCOL = "zeus-isolated-worker-v1-read-only"
PROTOCOLS = (PROTOCOL, DELIVERY_PROTOCOL, SESSION_PROTOCOL, SESSION_DELIVERY_PROTOCOL, READ_ONLY_PROTOCOL)
ENTRY_MODULE = "codex_harness.adapters.isolated_worker_entry"
TRUSTED_PYTHON = "/opt/zeus/bin/python"
WORKSPACE, EVIDENCE = "/workspace", "/evidence"
CONTAINER_HOME = "/home/worker"
RESULT = "/result"
MAX_FILES, MAX_TOTAL_BYTES, MAX_FILE_BYTES = 10000, 256 * 1024 * 1024, 16 * 1024 * 1024
# Fixed, recorded and bound into the operation and replay identities; not tunable per task.
LIMITS = {"memory": "4g", "cpus": "2", "pids": 512, "tmp_mb": 512, "home_mb": 256,
          "inner_grace_seconds": 45, "cleanup_seconds": 30, "docker_command_seconds": 60,
          "max_files": MAX_FILES, "max_total_bytes": MAX_TOTAL_BYTES, "max_file_bytes": MAX_FILE_BYTES}
DOCKER_CLIENT_ENVIRONMENT = ("PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "COMSPEC", "TEMP", "TMP", "HOME",
                             "USERPROFILE", "PROGRAMDATA", "ProgramData", "DOCKER_HOST", "DOCKER_CONTEXT",
                             "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")
# The run-record states that prove a container gone: the one definition, owned with the credential ledger
# that must read the same set (credentials.domain.codex_credential.SETTLED_RUN_STATES).
RESOLVED = SETTLED_RUN_STATES
# The uid:gid a container runs as when the broker itself runs as root (never root inside).
FALLBACK_USER = "10001:10001"

CLAUDE_IMPL_RW, CLAUDE_ROLE_RO = "claude-impl-rw", "claude-role-ro"
CODEX_ROLE_RO, CODEX_IMPL_RW = "codex-role-ro", "codex-impl-rw"
PROFILES = {
    CLAUDE_IMPL_RW: {"provider": "claude", "transport": "claude_cli", "read_only": False, "workspace": "staging_rw",
                     "writable": (WORKSPACE, EVIDENCE), "credential": "CLAUDE_CODE_OAUTH_TOKEN by name"},
    CLAUDE_ROLE_RO: {"provider": "claude", "transport": "claude_cli", "read_only": True, "workspace": "checkout_ro",
                     "writable": (EVIDENCE,), "credential": "CLAUDE_CODE_OAUTH_TOKEN by name"},
    CODEX_ROLE_RO: {"provider": "codex", "transport": "app_server", "read_only": True, "workspace": "checkout_ro",
                    "writable": (RESULT, CODEX_HOME), "credential": "per-run CODEX_HOME copy of the store auth.json"},
    CODEX_IMPL_RW: {"provider": "codex", "transport": "app_server", "read_only": False, "workspace": "staging_rw",
                    "writable": (WORKSPACE, EVIDENCE, CODEX_HOME),
                    "credential": "per-run CODEX_HOME copy of the store auth.json"},
}
# The profiles whose prompts name container paths for the artifact reader (the existing worker is unchanged).
ROLE_PROFILES = (CLAUDE_ROLE_RO, CODEX_ROLE_RO, CODEX_IMPL_RW)
# The writers whose settled evidence is handed off to the content-addressed store (D4).
WRITABLE_PROFILES = (CLAUDE_IMPL_RW, CODEX_IMPL_RW)

INSPECT_FORMAT = ('{"image":{{json .Image}},"user":{{json .Config.User}},"network":{{json .HostConfig.NetworkMode}},'
                  '"read_only":{{json .HostConfig.ReadonlyRootfs}},"cap_drop":{{json .HostConfig.CapDrop}},'
                  '"security_opt":{{json .HostConfig.SecurityOpt}},"memory":{{json .HostConfig.Memory}},'
                  '"nano_cpus":{{json .HostConfig.NanoCpus}},"pids_limit":{{json .HostConfig.PidsLimit}},'
                  '"privileged":{{json .HostConfig.Privileged}},"ports":{{json .HostConfig.PortBindings}},'
                  '"mounts":{{json .Mounts}},"labels":{{json .Config.Labels}},'
                  '"pid_mode":{{json .HostConfig.PidMode}},"ipc_mode":{{json .HostConfig.IpcMode}},'
                  '"uts_mode":{{json .HostConfig.UTSMode}},"userns_mode":{{json .HostConfig.UsernsMode}},'
                  '"cap_add":{{json .HostConfig.CapAdd}},"devices":{{json .HostConfig.Devices}}}')
# INV-ROLE-CONTAINER-001: bind sources no profile may ever observe, whatever it declared.
FORBIDDEN_SOURCES = ("/var/run/docker.sock", "/run/docker.sock", "/")


def request_protocol(delivery: bool, session: bool, read_only: bool = False) -> str:
    """The request protocol names every optional section it carries, so an older entry refuses it."""
    if read_only:
        require(not delivery and not session, "A read-only role carries no project delivery or task session")
        return READ_ONLY_PROTOCOL
    return {(False, False): PROTOCOL, (True, False): DELIVERY_PROTOCOL,
            (False, True): SESSION_PROTOCOL, (True, True): SESSION_DELIVERY_PROTOCOL}[(delivery, session)]


def load_isolation(host_settings, *, driver_sha256: str) -> dict | None:
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
    body = {"mode": MODE, "image": image, "limits": dict(LIMITS), "driver_sha256": driver_sha256,
            "protocol": PROTOCOL, "network": {"worker": "bridge", "verifier": "none"}}
    # INV-CODEX-CREDENTIAL-001: the Codex role profiles exist only with a configured credential store.
    # Absent, a Codex selection under isolation refuses before spawn (never the host AppServer), and
    # the identity of an unchanged Claude-only configuration is exactly what it was.
    store = str(host_settings.get("ZEUS_CODEX_CREDENTIAL_STORE")
                or host_settings.get("HARNESS_CODEX_CREDENTIAL_STORE") or "").strip()
    store = store.rstrip("/") or store
    if store:
        if not os.path.isabs(store) or "," in store or store != os.path.normpath(store) or store == os.sep:
            raise IsolationError("isolation_config_invalid",
                                 "ZEUS_CODEX_CREDENTIAL_STORE must be a normalized absolute directory path")
        body["codex"] = {"credential_store": store}
    return {**body, "digest": digest(body)}


def summary(config: dict) -> dict:
    return {key: config[key] for key in ("mode", "image", "limits", "driver_sha256", "protocol", "network", "digest")}


def worker_environment() -> dict:
    """The fixed, value-free environment of every Claude profile container (the token goes by name)."""
    return {"HOME": CONTAINER_HOME, "DISABLE_AUTOUPDATER": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "PYTHONIOENCODING": "utf-8",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": WORKSPACE}


def codex_environment() -> dict:
    """The fixed, value-free environment of every Codex profile container: no provider token of any
    kind; the credential is the per-run CODEX_HOME copy only."""
    return {"HOME": CONTAINER_HOME, "CODEX_HOME": CODEX_HOME, "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": WORKSPACE}


def read_only_mounts(checkout: str, result: str, handoff: dict | None = None) -> tuple:
    """claude-role-ro binds (INV-ROLE-CONTAINER-001): the review checkout read-only, the run's own
    result directory writable, the hand-off copy read-only. Returns (mounts, {target: writable})."""
    mounts = [(checkout, WORKSPACE, True), (result, EVIDENCE)]
    expected = {WORKSPACE: False, EVIDENCE: True}
    if handoff is not None:
        mounts.append((handoff["source"], handoff["target"], True))
        expected[handoff["target"]] = False
    return mounts, expected


def container_user(uid: int | None, gid: int | None) -> str:
    """The container's uid:gid: the broker's own non-root ids, or the fixed non-root fallback when the
    broker is root or has no POSIX ids. Never root inside (RESEARCH-S3 G2)."""
    return f"{uid}:{gid}" if uid is not None and uid != 0 else FALLBACK_USER


def container_args(config: dict, *, name: str, run_id: str, role: str, network: str, mounts: list,
                   environment: dict, pass_names: tuple, entry: list, workdir: str, user: str) -> list:
    """The one place a container's controls are composed, for the worker and the verifier alike.
    `pass_names` are environment NAMES whose value the docker client forwards; no value is in argv."""
    limits = config["limits"]
    argv = ["create", "--name", name, "--label", LABEL + "=" + run_id, "--label", ROLE_LABEL + "=" + role,
            "--network", network, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", user, "--memory", limits["memory"], "--cpus", limits["cpus"],
            "--pids-limit", str(limits["pids"]), "--init", "--interactive",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,size={limits['tmp_mb']}m,mode=1777",
            "--tmpfs", f"{CONTAINER_HOME}:rw,nosuid,nodev,size={limits['home_mb']}m,mode=1777"]
    for mount in mounts:
        # (source, target) is the writable bind of the existing profile; (source, target, True) is a
        # read-only bind (INV-ROLE-CONTAINER-001). The --mount syntax is comma-separated, so a comma
        # in either path refuses rather than composing another option.
        source, target, readonly = mount[0], mount[1], len(mount) > 2 and mount[2] is True
        require("," not in str(source) and "," not in str(target), "A bind path must not contain a comma")
        argv += ["--mount", f"type=bind,source={source},target={target}" + (",readonly=true" if readonly else "")]
    for key, value in environment.items():
        argv += ["-e", key + "=" + value]
    for key in pass_names:
        argv += ["-e", key]
    return [*argv, "-w", workdir, "--entrypoint", entry[0], config["image"], *entry[1:]]


def forbidden_controls(observed: dict, *, home: str) -> list:
    """Every forbidden socket/home/host flag the inspected container shows; [] when none. A field the
    daemon does not report is its default, never a grant. `home` is the operator's home directory."""
    found = []
    for key in ("pid_mode", "ipc_mode", "uts_mode", "userns_mode", "network"):
        value = str(observed.get(key) or "")
        if value == "host" or value.startswith("container:"):
            found.append(key + "=" + value)
    if observed.get("cap_add"):
        found.append("cap_add")
    if observed.get("devices"):
        found.append("devices")
    user = str(observed.get("user") or "")
    if user in ("", "0", "root") or user.startswith(("0:", "root:")):
        found.append("user")
    for mount in observed.get("mounts") or []:
        source = str(mount.get("Source") or "")
        if source in FORBIDDEN_SOURCES or source.endswith("docker.sock") or source.rstrip("/") == home.rstrip("/"):
            found.append("mount:" + source)
    return found


def controls_mismatch(observed: dict | None, *, image: str, run_id: str, expected: dict, network: str,
                      home: str) -> bool:
    """True when the inspected container is not exactly what the host chose (checked before start):
    the image, exactly the expected bind targets in exactly those modes, no forbidden control, the
    hardening flags, the network, no published port, the run label and set limits."""
    return (observed is None or observed.get("image") != image
            or {mount["Destination"]: mount.get("RW") is True for mount in observed["mounts"]
                if mount["Type"] == "bind"} != expected
            or bool(forbidden_controls(observed, home=home))
            or "no-new-privileges" not in [str(option) for option in observed.get("security_opt") or []]
            or any(mount["Type"] not in ("bind", "tmpfs") for mount in observed["mounts"])
            or observed.get("network") != network or observed.get("read_only") is not True
            or observed.get("privileged") is not False or bool(observed.get("ports"))
            or "ALL" not in [str(cap).upper() for cap in observed.get("cap_drop") or []]
            or (observed.get("labels") or {}).get(LABEL) != run_id
            or not observed.get("memory") or not observed.get("pids_limit") or not observed.get("user"))
