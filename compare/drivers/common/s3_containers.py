"""Scenario body `containers.profiles` (REBUILD-DESIGN-v2 §5.3 S3: the exact docker argv per profile (4),
I1 (f)1/(f)2/(f)5 before-start refusals; RESEARCH-S3 D3/D4/D5, G1/G2/G7, F-R1/F-R6).

Layer: harness (never shipped); standard library only. No docker daemon is contacted: the driver
installs a scripted docker client (`api.install_docker(fake)`) in place of the ONE docker-call
function of its side, so every docker argv the implementation composes is recorded and answered
from this file. No provider CLI, credential file or network is used; the Codex credential store is
a dummy written here.

`api` provides:
- `load_isolation(settings)`, `container_args(config, **fields)`, `forbidden_controls(observed)`,
  `worker_environment()`, `codex_environment()`, `read_only_mounts(checkout, result, handoff)`;
- constants `PROFILES` (name -> declared shape), `LIMITS`, `INSPECT_FORMAT`, `FORBIDDEN_SOURCES`,
  `CODEX_CONFIG`, `CODEX_CONFIG_SHA256`, `CODEX_CLI_VERSION`, `TOKEN_NAME`, `DOCKER_CLIENT_ENVIRONMENT`;
- `claude_runtime(config, root, profile, environment)` and `codex_runtime(config, root, profile, store,
  environment)`: an unopened transport of that profile (its `run` is called here; `__enter__` is not,
  since preflight is a daemon call covered by `preflight`);
- `preflight(config, environment, token)`;
- `install_docker(fake)`: route every docker call of the side to `fake(args, env) -> (code, stdout)`;
- `set_ids(uid, gid)`: the host uid/gid the implementation sees; `set_uuid(prefix)`: deterministic run ids;
- `IsolationError` and `ContractError`.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from s1_common import outcome, relative, sha

IMAGE = "sha256:" + "ab" * 32
CONTAINER = "c0" * 32
TOKEN_VALUE = "fixture-claude-token-0123456789"


class FakeDocker:
    """A scripted docker client. `mode`: `create_fails` (exit 1, no id recoverable), `controls_bad`
    (created; inspect shows a root user, so verification refuses before start), `inspect_privileged`
    (created; inspect shows privileged=true), `inspect_unconfined` (created; inspect adds
    seccomp=unconfined, the F-R1 probe)."""

    def __init__(self, mode: str):
        self.mode, self.calls, self.created = mode, [], None

    def __call__(self, args, env):
        args = [str(part) for part in args]
        self.calls.append({"args": args, "env_names": sorted(env or {})})
        verb = args[0]
        if verb == "create":
            self.created = args
            return (1, "") if self.mode == "create_fails" else (0, CONTAINER + "\n")
        if verb == "ps":
            return 0, ""
        if verb == "inspect" and "--format" in args and args[args.index("--format") + 1].startswith('{"image"'):
            return 0, json.dumps(self.observed())
        if verb == "inspect":
            return 0, "created 0 false"
        if verb == "rm":
            return 0, CONTAINER
        return 1, ""

    def observed(self) -> dict:
        args = self.created
        value = {name: args[args.index(name) + 1] for name in ("--user", "--network")}
        mounts = []
        for index, part in enumerate(args):
            if part == "--mount":
                fields = dict(item.split("=", 1) for item in args[index + 1].split(","))
                mounts.append({"Type": "bind", "Source": fields["source"], "Destination": fields["target"],
                               "RW": fields.get("readonly") != "true"})
        labels = dict(args[i + 1].split("=", 1) for i, part in enumerate(args) if part == "--label")
        body = {"image": IMAGE, "user": value["--user"], "network": value["--network"], "read_only": True,
                "cap_drop": ["ALL"], "security_opt": ["no-new-privileges"], "memory": 1, "nano_cpus": 1,
                "pids_limit": 512, "privileged": False, "ports": {}, "mounts": mounts, "labels": labels,
                "pid_mode": "", "ipc_mode": "private", "uts_mode": "", "userns_mode": "", "cap_add": None,
                "devices": []}
        if self.mode == "controls_bad":
            body["user"] = "0:0"
        if self.mode == "inspect_privileged":
            body["privileged"] = True
        if self.mode == "inspect_unconfined":
            body["security_opt"] = ["no-new-privileges", "seccomp=unconfined"]
        return body


def _git(workspace: Path, *args) -> None:
    subprocess.run(["git", "-C", str(workspace), *args], check=True, capture_output=True, text=True,
                   env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(workspace),
                        "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
                        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})


def _checkout(root: Path) -> Path:
    workspace = root / "checkout"
    workspace.mkdir()
    _git(workspace, "init", "-q", "-b", "main")
    _git(workspace, "config", "user.email", "fixture@example.invalid")
    _git(workspace, "config", "user.name", "fixture")
    (workspace / "README.md").write_text("fixture\n", encoding="utf-8")
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "fixture")
    return workspace


def dummy_auth(account: str = "acct-fixture-0001", access: str = "access-fixture-token-000000000001") -> bytes:
    body = {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "last_refresh": "2026-01-01T00:00:00Z",
            "tokens": {"id_token": "id-fixture-token-000000000000000001", "access_token": access,
                       "refresh_token": "refresh-fixture-token-00000000000001", "account_id": account}}
    return json.dumps(body, sort_keys=True).encode("utf-8")


def write_store(store: Path, data: bytes | None = None) -> None:
    store.mkdir(mode=0o700, parents=True)
    os.chmod(store, 0o700)
    auth = store / "auth.json"
    auth.write_bytes(dummy_auth() if data is None else data)
    os.chmod(auth, 0o600)


def _tree(root: Path, roots: dict) -> list:
    rows = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        kind = "dir" if path.is_dir() else "file"
        rows.append(relative(f"{kind}:{path}", roots) + ("" if kind == "dir" else f":{oct(path.stat().st_mode & 0o777)}"))
    return rows


def _record(root: Path, roots: dict) -> list:
    out = []
    for path in sorted(root.glob("*/run.json")):
        body = json.loads(path.read_text("utf-8"))
        out.append(relative({"state": body.get("state"), "keys": sorted(body),
                             "lifecycle": [{k: v for k, v in step.items() if k != "at"} for step in body["lifecycle"]],
                             "container": body.get("container"), "container_name": body.get("container_name"),
                             "label": body.get("label"), "role": body.get("role"), "profile": body.get("profile")},
                            roots))
    return out


def _run_profile(api, profile: str, mode: str, base: Path, uid: int) -> dict:
    api.set_ids(uid, uid)
    api.set_uuid(profile + "-" + mode)
    work = Path(tempfile.mkdtemp(prefix="p-", dir=base))
    workspace = _checkout(work)
    store = work / "secrets" / "codex-store"
    write_store(store)
    root = work / "runs"
    root.mkdir()
    roots = {"WORK": str(work.resolve()), "WORKSPACE": str(workspace.resolve()), "RUNS": str(root.resolve())}
    config = api.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                                 "ZEUS_CODEX_CREDENTIAL_STORE": str(store)})
    environment = {"PATH": "/usr/bin:/bin", api.TOKEN_NAME: TOKEN_VALUE, "DOCKER_HOST": "unix:///fixture.sock",
                   "ANTHROPIC_API_KEY": "fixture-must-not-pass", "UNRELATED": "x"}
    fake = FakeDocker(mode)
    api.install_docker(fake)
    read_only = profile.endswith("-ro")
    if profile.startswith("claude"):
        runtime = api.claude_runtime(config, root, profile, environment)
    else:
        runtime = api.codex_runtime(config, root, profile, store, environment)
    result = outcome(lambda: runtime.run("fixture prompt", str(workspace), {"type": "object"}, 30,
                                         read_only=read_only))
    token_in_argv = any(TOKEN_VALUE in part for call in fake.calls for part in call["args"])
    return {
        "outcome": relative(result, roots),
        "docker_calls": relative([call["args"] if call["args"][0] != "inspect" or len(call["args"]) < 4
                                  else call["args"][:2] + ["<INSPECT_FORMAT>" if call["args"][2] == api.INSPECT_FORMAT
                                                           else call["args"][2]] + call["args"][3:]
                                  for call in fake.calls], roots),
        "docker_env_names": [call["env_names"] for call in fake.calls],
        "token_value_in_any_argv": token_in_argv,
        "records": _record(root, roots),
        "runs_tree": _tree(root, roots),
        "store_tree": _tree(store.parent, roots),
        "ledger": _ledger(store, roots),
        "store_sha256": sha((store / "auth.json").read_bytes()),
    }


def _ledger(store: Path, roots: dict) -> list:
    ledger = store.parent / (store.name + ".ledger")
    rows = []
    for path in sorted(ledger.glob("*.json")) if ledger.is_dir() else []:
        body = json.loads(path.read_text("utf-8"))
        rows.append(relative({"keys": sorted(body), "state": body.get("state"), "shape": body.get("shape"),
                              "issued_equals_store": body.get("issued_sha256") == body.get("store_sha256"),
                              "home": body.get("home"), "record": body.get("record")}, roots))
    return rows


def run_static(api) -> dict:
    """Constants, pure builders, configuration parse, forbidden-control probes and preflight."""
    out: dict = {}
    # -- the constants and pure builders ------------------------------------------------------------
    out["profiles"] = {name: {key: (list(value) if isinstance(value, tuple) else value)
                              for key, value in shape.items()} for name, shape in api.PROFILES.items()}
    out["limits"] = dict(api.LIMITS)
    out["inspect_format_sha256"] = sha(api.INSPECT_FORMAT)
    out["forbidden_sources"] = list(api.FORBIDDEN_SOURCES)
    out["codex"] = {"cli_version": api.CODEX_CLI_VERSION, "config": api.CODEX_CONFIG,
                    "config_sha256": api.CODEX_CONFIG_SHA256, "config_sha256_ok": sha(api.CODEX_CONFIG) == api.CODEX_CONFIG_SHA256}
    out["environments"] = {"claude": api.worker_environment(), "codex": api.codex_environment(),
                           "docker_client_names": list(api.DOCKER_CLIENT_ENVIRONMENT), "token_name": api.TOKEN_NAME}
    configs = {
        "none": {},
        "claude_only": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE},
        "with_store": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                       "ZEUS_CODEX_CREDENTIAL_STORE": "/srv/fixture/codex-store/"},
        "legacy_names": {"HARNESS_WORKER_ISOLATION": "docker", "HARNESS_WORKER_IMAGE": IMAGE},
        "mode_wrong": {"ZEUS_WORKER_ISOLATION": "podman", "ZEUS_WORKER_IMAGE": IMAGE},
        "image_tag": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "zeus-worker:latest"},
        "image_only": {"ZEUS_WORKER_IMAGE": IMAGE},
        "store_relative": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                           "ZEUS_CODEX_CREDENTIAL_STORE": "codex-store"},
        "store_comma": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                        "ZEUS_CODEX_CREDENTIAL_STORE": "/srv/a,b"},
        "store_root": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                       "ZEUS_CODEX_CREDENTIAL_STORE": "/"},
        "store_unnormalized": {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                               "ZEUS_CODEX_CREDENTIAL_STORE": "/srv/x/../codex"},
    }
    out["load_isolation"] = {}
    for name, settings in configs.items():
        row = outcome(lambda settings=settings: api.load_isolation(settings))
        if "ok" in row and row["ok"] is not None:
            row["ok"] = {key: row["ok"][key] for key in sorted(row["ok"]) if key != "driver_sha256"}
            row["ok"]["digest_len"] = len(row["ok"].pop("digest"))
        out["load_isolation"][name] = row
    config = api.load_isolation(configs["with_store"])
    fields = {"name": "zeus-worker-fixture", "run_id": "0" * 32, "role": "worker", "network": "bridge",
              "environment": {"HOME": "/home/worker"}, "pass_names": ("CLAUDE_CODE_OAUTH_TOKEN",),
              "entry": ["/opt/zeus/bin/python", "-I", "-m", "fixture"], "workdir": "/"}
    builds = {
        "rw_binds": [("/srv/stage", "/workspace"), ("/srv/evidence", "/evidence")],
        "ro_and_rw": [("/srv/checkout", "/workspace", True), ("/srv/result", "/result")],
        "readonly_flag_not_true": [("/srv/checkout", "/workspace", "yes")],
        "comma_source": [("/srv/a,b", "/workspace")],
        "comma_target": [("/srv/a", "/work,space")],
    }
    out["container_args"] = {}
    for uid in (1000, 0):
        api.set_ids(uid, uid)
        for name, mounts in builds.items():
            out["container_args"][f"uid{uid}:{name}"] = outcome(
                lambda mounts=mounts: api.container_args(config, mounts=mounts, **fields))
    out["read_only_mounts"] = {
        "no_handoff": [list(map(list, part)) if isinstance(part, (list, tuple)) else part
                       for part in [api.read_only_mounts("/srv/checkout", "/srv/result")[0]]]
        + [api.read_only_mounts("/srv/checkout", "/srv/result")[1]],
        "handoff": [list(map(list, api.read_only_mounts("/srv/c", "/srv/r", {"source": "/srv/h", "target": "/handoff"})[0])),
                    api.read_only_mounts("/srv/c", "/srv/r", {"source": "/srv/h", "target": "/handoff"})[1]],
    }
    home = str(Path.home())
    clean = {"user": "1000:1000", "network": "bridge", "pid_mode": "", "ipc_mode": "private", "uts_mode": "",
             "userns_mode": "", "cap_add": None, "devices": [], "mounts": [{"Source": "/srv/stage"}]}
    probes = {
        "clean": {},
        "host_pid": {"pid_mode": "host"}, "container_ipc": {"ipc_mode": "container:abc"}, "host_uts": {"uts_mode": "host"},
        "host_userns": {"userns_mode": "host"}, "host_network": {"network": "host"},
        "cap_add": {"cap_add": ["SYS_ADMIN"]}, "devices": {"devices": [{"PathOnHost": "/dev/kvm"}]},
        "user_empty": {"user": ""}, "user_zero": {"user": "0"}, "user_root": {"user": "root"},
        "user_zero_group": {"user": "0:1000"}, "user_root_group": {"user": "root:root"},
        "docker_sock": {"mounts": [{"Source": "/var/run/docker.sock"}]},
        "run_docker_sock": {"mounts": [{"Source": "/run/docker.sock"}]},
        "other_sock": {"mounts": [{"Source": "/srv/podman/docker.sock"}]},
        "root_bind": {"mounts": [{"Source": "/"}]},
        "operator_home": {"mounts": [{"Source": home}]},
        "operator_home_slash": {"mounts": [{"Source": home + "/"}]},
        "privileged_only": {"privileged": True},
        "seccomp_unconfined_only": {"security_opt": ["seccomp=unconfined"]},
        "several": {"pid_mode": "host", "user": "root", "cap_add": ["NET_ADMIN"]},
    }
    out["forbidden_controls"] = {name: relative(api.forbidden_controls({**clean, **change}), {"HOME": home})
                                 for name, change in probes.items()}
    out["preflight"] = _preflight(api, config)
    return out


def run(api) -> dict:
    """The whole family: the static part plus the four profiles through their real transports."""
    return {**run_static(api), "profile_runs": run_profiles(api)}


def run_profiles(api) -> dict:
    """The four profiles through their real transport up to the before-start refusal."""
    base = Path(tempfile.mkdtemp(prefix="zeus-s3-profiles-"))
    runs = {}
    for profile in ("claude-impl-rw", "claude-role-ro", "codex-role-ro", "codex-impl-rw"):
        for mode in ("create_fails", "controls_bad"):
            runs[f"{profile}:{mode}"] = _run_profile(api, profile, mode, base, 1000)
    runs["claude-role-ro:create_fails:uid0"] = _run_profile(api, "claude-role-ro", "create_fails", base, 0)
    runs["codex-role-ro:inspect_privileged"] = _run_profile(api, "codex-role-ro", "inspect_privileged", base, 1000)
    # F-R1 probe: recorded as observed; a changed disposition is a declared §4 change, never silent.
    runs["codex-role-ro:inspect_unconfined"] = _run_profile(api, "codex-role-ro", "inspect_unconfined", base, 1000)
    return runs


def _preflight(api, config) -> dict:
    """Daemon / image / token refusals of the preflight, over the scripted client."""
    pre = {}
    for name, (answers, environment, token) in {
        "ok_token": ({"version": (0, "27.0.0\n"), "image": (0, IMAGE + "\n")}, {api.TOKEN_NAME: "x"}, True),
        "ok_codex_no_token": ({"version": (0, "27.0.0\n"), "image": (0, IMAGE + "\n")}, {}, False),
        "no_daemon": ({"version": (1, "")}, {api.TOKEN_NAME: "x"}, True),
        "image_missing": ({"version": (0, "27.0.0\n"), "image": (1, "")}, {api.TOKEN_NAME: "x"}, True),
        "image_other": ({"version": (0, "27.0.0\n"), "image": (0, "sha256:" + "cd" * 32 + "\n")}, {api.TOKEN_NAME: "x"}, True),
        "token_missing": ({"version": (0, "27.0.0\n"), "image": (0, IMAGE + "\n")}, {}, True),
    }.items():
        calls = []

        def fake(args, env, answers=answers, calls=calls):
            calls.append({"args": [str(a) for a in args], "env_names": sorted(env or {})})
            return answers.get(args[0], (1, ""))

        api.install_docker(fake)
        pre[name] = {"outcome": outcome(lambda environment=environment, token=token:
                                        api.preflight(config, environment, token)), "calls": calls}
    return pre
