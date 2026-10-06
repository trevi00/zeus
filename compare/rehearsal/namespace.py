"""The rehearsal namespace (RH-1b): a declarative `namespace.json` -> a validated bwrap argv, run and self-tested.

Layer: harness (never shipped). Standard library only. Nothing here reads a production path, a secrets file or the live
environment: every input is a parameter, the argv carries a closed env, and the child is started with a closed env.

Rehearsal design "Namespace spec", "Spec validation", "Namespace self-test" and critiques #2/#4/#6/#13
(`cutover-critique-rehearsal.json`). One deliberate difference from the design's listing: `--proc /proc --dev /dev`
follow `--ro-bind / /` (the listing puts them first). A recursive bind of `/` over the new root hides an earlier
`/proc`, which shows the HOST's pid 1; the self-test row `pid1_bwrap` proves the order, and `validate_spec` refuses a
spec where a later mount shadows an earlier one (`mount_shadowed`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import Refused, check_run8

PROD_SRV = "/srv/zeus"
SECRETS_DIR = PROD_SRV + "/secrets"
KINDS = frozenset({"ro-bind", "bind", "tmpfs", "dir", "overlay", "proc", "dev"})
MODES = frozenset({"ro", "rw"})
TAGS = frozenset({"base", "proc", "dev", "run", "tmp", "home", "journal", "ro", "srv-base", "secrets", "release-r0",
                  "release-b", "rw", "overlay", "socket", "mock", "config"})
RW_SRV_ROOTS = ("runtime", "managed-fleet", "repo", "worktrees")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PRODUCTION_SOCKET = re.compile(r"docker\.sock|systemd/private|[:@]\s*(?:55432|56379)\b")
CREDENTIAL_PART = re.compile(r"(^|/)\.(?:codex|claude)(/|$)")
CONFIG_KEYS = frozenset({"pg_dbname", "pg_user", "search_path", "redis_db"})
FIXED_ENV = ("PATH", "HOME")
PROBE_NAME = ".rehearsal-probe"
SPEC_VERSION = 1


class SpecRefused(Refused):
    """`validate_spec` refused the spec; `errors` lists every `(code, detail)` found, `code` is the first."""

    def __init__(self, errors: list[tuple[str, str]]):
        super().__init__(errors[0][0], errors[0][1])
        self.errors = errors


@dataclass(frozen=True)
class Mount:
    kind: str
    dest: str
    src: str | None = None
    mode: str | None = None  # "ro" | "rw" for binds and overlays; None otherwise
    tag: str = ""
    perms: str | None = None  # --perms for tmpfs/dir only (bwrap refuses it before a bind)
    upper: str | None = None  # overlay rw layer
    work: str | None = None  # overlay work dir


@dataclass(frozen=True)
class Release:
    """A release dir the self-test imports from: `python` defaults to `<dest>/.venv/bin/python` (resolving the
    editable `.pth` is the point of critique #2); `pythonpath` is only for a fixture without a venv."""

    rev: str
    dest: str
    python: str | None = None
    pythonpath: str | None = None


@dataclass(frozen=True)
class NamespaceSpec:
    run8: str
    root: str
    x: str
    mounts: tuple[Mount, ...]
    env: tuple[tuple[str, str], ...]
    releases: tuple[Release, ...] = ()
    expected_search_path: str | None = None  # the recorded production value (critique #4)
    probe_python: str = "/usr/bin/python3"  # runs the SHOW search_path probe; must import psycopg
    config_src: str | None = None  # the reviewed non-secret config copy (an input) and its recorded digest
    config_sha256: str | None = None
    version: int = SPEC_VERSION
    notes: dict = field(default_factory=dict)

    def env_dict(self) -> dict[str, str]:
        return dict(self.env)

    def to_json(self) -> dict:
        return {
            "version": self.version, "run8": self.run8, "root": self.root, "x": self.x,
            "mounts": [{k: v for k, v in vars(m).items() if v not in (None, "")} for m in self.mounts],
            "env": [list(pair) for pair in self.env],
            "releases": [{k: v for k, v in vars(r).items() if v is not None} for r in self.releases],
            "expected_search_path": self.expected_search_path, "probe_python": self.probe_python,
            "config_src": self.config_src, "config_sha256": self.config_sha256,
        }


_MOUNT_KEYS = frozenset({"kind", "dest", "src", "mode", "tag", "perms", "upper", "work"})
_SPEC_KEYS = frozenset({"version", "run8", "root", "x", "mounts", "env", "releases", "expected_search_path",
                        "probe_python", "config_src", "config_sha256"})


def load_spec(path: Path | str) -> NamespaceSpec:
    """Parse a `namespace.json`; an unknown key or a wrong type is refused (`spec_malformed`)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("spec_malformed", type(exc).__name__) from None
    return spec_from_json(raw)


def spec_from_json(raw: object) -> NamespaceSpec:
    if not isinstance(raw, dict) or set(raw) - _SPEC_KEYS or not {"run8", "root", "x", "mounts", "env"} <= set(raw):
        raise Refused("spec_malformed", "keys")
    if raw.get("version", SPEC_VERSION) != SPEC_VERSION:
        raise Refused("spec_malformed", "version")
    try:
        mounts = []
        for item in raw["mounts"]:
            if set(item) - _MOUNT_KEYS or not {"kind", "dest"} <= set(item):
                raise Refused("spec_malformed", "mount keys")
            mounts.append(Mount(**item))
        releases = [Release(**item) for item in raw.get("releases", [])]
        env = tuple((str(name), str(value)) for name, value in raw["env"])
        return NamespaceSpec(
            run8=check_run8(raw["run8"]), root=str(raw["root"]), x=str(raw["x"]), mounts=tuple(mounts), env=env,
            releases=tuple(releases), expected_search_path=raw.get("expected_search_path"),
            probe_python=raw.get("probe_python", "/usr/bin/python3"), config_src=raw.get("config_src"),
            config_sha256=raw.get("config_sha256"))
    except (TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, Refused):
            raise
        raise Refused("spec_malformed", type(exc).__name__) from None


def load_nonsecret_config(path: Path | str) -> dict:
    """The reviewed read-only copy of the non-secret config (critique #4): only the closed key set, no secret shape."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("config_malformed", type(exc).__name__) from None
    if not isinstance(data, dict) or set(data) != CONFIG_KEYS:
        raise Refused("config_malformed", "keys must be exactly " + ",".join(sorted(CONFIG_KEYS)))
    for key in ("pg_dbname", "pg_user", "search_path"):
        value = data[key]
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_,$.]+", value):
            raise Refused("config_malformed", f"{key} is not a plain identifier list")
    if not isinstance(data["redis_db"], int) or isinstance(data["redis_db"], bool) or data["redis_db"] < 0:
        raise Refused("config_malformed", "redis_db")
    return data


def _sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def default_spec(
    run8: str, root: Path | str, x: str, *, a_venv: str, uv_python: str, uv_cache: str, releases_r0: dict[str, str],
    b_rev: str, mocks: dict[str, str], env_names: list[str], config_copy: Path | str | None = None,
    recorded_search_path: str | None = None, pg_socket_dir: Path | str | None = None,
    redis_socket_dir: Path | str | None = None, artifacts_src: str = PROD_SRV + "/artifacts",
    release_python: dict[str, str] | None = None, release_pythonpath: dict[str, str] | None = None,
    probe_python: str = "/usr/bin/python3", extra_ro: tuple[str, ...] = (),
) -> NamespaceSpec:
    """The design's mount order for copy `x` (a directory name under ROOT). Reads only `config_copy` (a fixture input)."""
    root, x_dir = str(root), f"{root}/{x}"
    sock_dirs = [str(p) for p in (pg_socket_dir, redis_socket_dir) if p is not None]
    m: list[Mount] = [
        Mount("ro-bind", "/", "/", "ro", "base"), Mount("proc", "/proc", tag="proc"), Mount("dev", "/dev", tag="dev"),
        Mount("tmpfs", "/run", tag="run"),
        Mount("bind", "/tmp", f"{x_dir}/tmp", "rw", "tmp"),
        Mount("bind", "/home/trevi", f"{x_dir}/home", "rw", "home"),
        Mount("tmpfs", "/var/log/journal", tag="journal"),
        Mount("ro-bind", uv_python, uv_python, "ro", "ro"), Mount("ro-bind", a_venv, a_venv, "ro", "ro"),
        Mount("ro-bind", uv_cache, uv_cache, "ro", "ro"),
        *[Mount("ro-bind", p, p, "ro", "ro") for p in extra_ro],
        Mount("tmpfs", PROD_SRV, tag="srv-base"), Mount("dir", SECRETS_DIR, perms="0700", tag="secrets"),
    ]
    rel_list: list[Release] = []
    for rev, src in releases_r0.items():
        dest = f"{PROD_SRV}/releases/{rev}"
        m.append(Mount("ro-bind", dest, src, "ro", "release-r0"))
    b_dest = f"{PROD_SRV}/releases/{b_rev}"
    m.append(Mount("ro-bind", b_dest, f"{root}/rel/{b_rev}", "ro", "release-b"))
    for rev in [*releases_r0, b_rev]:
        rel_list.append(Release(rev, f"{PROD_SRV}/releases/{rev}", (release_python or {}).get(rev),
                                (release_pythonpath or {}).get(rev)))
    for name in RW_SRV_ROOTS:
        m.append(Mount("bind", f"{PROD_SRV}/{name}", f"{x_dir}/{name}", "rw", "rw"))
    m.append(Mount("bind", f"{PROD_SRV}/tmp", f"{x_dir}/zeus-tmp", "rw", "rw"))
    m.append(Mount("overlay", f"{PROD_SRV}/artifacts", artifacts_src, "rw", "overlay", upper=f"{x_dir}/art-up",
                   work=f"{x_dir}/art-wk"))
    m += [Mount("bind", d, d, "rw", "socket") for d in sock_dirs]
    for dest, src in mocks.items():
        m.append(Mount("ro-bind", dest, src, "ro", "mock"))
    config_src = config_sha = None
    env: dict[str, str] = {"PATH": "/usr/bin:/bin", "HOME": "/home/trevi"}
    if config_copy is not None:
        cfg = load_nonsecret_config(config_copy)
        config_src, config_sha = str(config_copy), _sha256(config_copy)
        m.append(Mount("ro-bind", f"{PROD_SRV}/config/nonsecret.json", config_src, "ro", "config"))
        if pg_socket_dir is not None:
            options = f"-c search_path={cfg['search_path']}"
            env["HARNESS_DATABASE_URL"] = (f"host={pg_socket_dir} dbname={cfg['pg_dbname']} user={cfg['pg_user']} "
                                           f"options='{options}'")
        if redis_socket_dir is not None:
            env["HARNESS_REDIS_URL"] = f"unix://{redis_socket_dir}/redis.sock?db={cfg['redis_db']}"
    env["ZEUS_COMPOSITION_PROFILE"] = "production"
    env["ZEUS_REHEARSAL_RUN"] = check_run8(run8)
    for name in env_names:
        if not ENV_NAME.fullmatch(name):
            raise Refused("env_name_bad", name)
        env.setdefault(name, f"rehearsal-{run8}")  # a rehearsal value, never read from the live environment
    return NamespaceSpec(
        run8=run8, root=root, x=x_dir, mounts=tuple(m), env=tuple(env.items()), releases=tuple(rel_list),
        expected_search_path=recorded_search_path, probe_python=probe_python, config_src=config_src,
        config_sha256=config_sha)


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def _is_rw(mount: Mount) -> bool:
    return mount.kind in ("bind", "overlay") and mount.mode == "rw"


def validate_spec(spec: NamespaceSpec) -> None:
    """Refuse before any argv exists; every failure carries a named code (SpecRefused.errors lists them all)."""
    errors: list[tuple[str, str]] = []

    def err(code: str, detail: str = "") -> None:
        errors.append((code, detail))

    try:
        check_run8(spec.run8)
    except Refused as exc:
        err(exc.code)
    root = os.path.realpath(spec.root) if os.path.isabs(spec.root) else ""
    if not root or not os.path.isdir(root):
        err("root_missing", "ROOT must be an existing absolute directory")
    if not _under(os.path.normpath(spec.x), os.path.normpath(spec.root)):
        err("x_outside_root", spec.x)
    mounts = spec.mounts
    if not mounts or (mounts[0].kind, mounts[0].dest, mounts[0].src) != ("ro-bind", "/", "/"):
        err("base_not_first", "the first mount must be --ro-bind / /")
    for text in _strings(spec.to_json()):
        if PRODUCTION_SOCKET.search(text):
            err("production_socket", "a production socket or DSN port is named in the spec")
            break
    for i, mount in enumerate(mounts):
        if mount.kind not in KINDS:
            err("bad_kind", mount.kind)
            continue
        if mount.tag and mount.tag not in TAGS:
            err("bad_tag", mount.tag)
        if not os.path.isabs(mount.dest) or os.path.normpath(mount.dest) != mount.dest.rstrip("/") and mount.dest != "/":
            err("dest_not_absolute", mount.dest)
        for path in (mount.src, mount.upper, mount.work):
            if path is not None and not os.path.isabs(path):
                err("src_not_absolute", path)
        if _touches_secrets(mount):
            err("secrets_bound", mount.dest)
        for path in (mount.src, mount.dest):
            if path and CREDENTIAL_PART.search(path):
                err("credential_path_bound", mount.dest)
        if mount.kind in ("ro-bind", "bind", "overlay"):
            want = {"ro-bind": "ro", "bind": "rw", "overlay": "rw"}[mount.kind]
            if mount.mode not in MODES:
                err("mode_missing", mount.dest)
            elif mount.kind == "ro-bind" and mount.mode != "ro":
                err("ro_bind_not_listed_ro", mount.dest)
            elif mount.mode != want:
                err("mode_mismatch", mount.dest)
            if mount.src is None:
                err("src_missing", mount.dest)
        if mount.kind in ("ro-bind", "bind", "overlay") and mount.src and not os.path.lexists(mount.src):
            err("bind_source_missing", mount.dest)
        if _is_rw(mount):
            for label, path in (("src", mount.src if mount.kind == "bind" else None), ("upper", mount.upper),
                                ("work", mount.work)):
                if path is not None:
                    _check_rw_source(path, spec.root, root, label, mount.dest, err)
            if mount.kind == "overlay" and (mount.upper is None or mount.work is None):
                err("overlay_layers_missing", mount.dest)
        if mount.kind == "overlay" and mount.work and mount.upper and mount.work == mount.upper:
            err("overlay_layers_equal", mount.dest)
        if mount.tag == "release-b" and not (mount.src and _under(os.path.normpath(mount.src), spec.root + "/rel")):
            err("release_b_outside_root_rel", mount.dest)
        if mount.kind in ("ro-bind", "bind", "tmpfs", "overlay", "proc", "dev"):
            for earlier in mounts[:i]:
                if earlier.kind != "dir" and _under(earlier.dest, mount.dest) and earlier.dest != "/":
                    err("mount_shadowed", f"{mount.dest} hides the earlier {earlier.dest}")
    dests = {m.dest for m in mounts}
    for release in spec.releases:
        if release.dest not in dests:
            err("release_not_mounted", release.rev)
    names = [n for n, _ in spec.env]
    if len(set(names)) != len(names):
        err("env_duplicate")
    for name, value in spec.env:
        if not ENV_NAME.fullmatch(name):
            err("env_name_bad", name)
    if "HARNESS_DATABASE_URL" in dict(spec.env) and not spec.expected_search_path:
        err("search_path_not_recorded", "a DSN needs the recorded production search_path")
    if spec.config_src is not None:
        try:
            if _sha256(spec.config_src) != spec.config_sha256:
                err("config_sha_mismatch", "")
        except OSError:
            err("config_unreadable", "")
    if errors:
        raise SpecRefused(errors)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _strings(value)


def _touches_secrets(mount: Mount) -> bool:
    if mount.kind == "dir" and mount.dest == SECRETS_DIR:
        return False  # the one tmpfs-backed empty dir the design creates
    for path in (mount.src, mount.dest, mount.upper, mount.work):
        if path and ("secrets" in Path(path).parts):
            return True
    return False


def _check_rw_source(path: str, lexical_root: str, real_root: str, label: str, dest: str, err) -> None:
    """The realpath under ROOT with no symlinked component below ROOT (rehearsal design 'Spec validation')."""
    norm = os.path.normpath(path)
    if not _under(norm, os.path.normpath(lexical_root)) or norm == os.path.normpath(lexical_root):
        err("rw_bind_outside_root" if label == "src" else f"overlay_{label}_outside_root", dest)
        return
    parts = Path(norm).relative_to(os.path.normpath(lexical_root)).parts
    probe = Path(lexical_root)
    for part in parts:
        probe = probe / part
        if probe.is_symlink():
            err("rw_bind_symlink", dest)
            return
    if not os.path.lexists(norm):
        err("bind_source_missing", dest)
        return
    if not _under(os.path.realpath(norm), real_root):
        err("rw_bind_outside_root" if label == "src" else f"overlay_{label}_outside_root", dest)


def bwrap_argv(spec: NamespaceSpec) -> list[str]:
    """The argv up to (excluding) the command. Validates first: no argv exists for a refused spec."""
    validate_spec(spec)
    argv = ["bwrap", "--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc"]
    for mount in spec.mounts:
        if mount.kind == "ro-bind":
            argv += ["--ro-bind", mount.src, mount.dest]
        elif mount.kind == "bind":
            argv += ["--bind", mount.src, mount.dest]
        elif mount.kind == "tmpfs":
            argv += (["--perms", mount.perms] if mount.perms else []) + ["--tmpfs", mount.dest]
        elif mount.kind == "dir":
            argv += (["--perms", mount.perms] if mount.perms else []) + ["--dir", mount.dest]
        elif mount.kind == "overlay":
            argv += ["--overlay-src", mount.src, "--overlay", mount.upper, mount.work, mount.dest]
        elif mount.kind == "proc":
            argv += ["--proc", mount.dest]
        elif mount.kind == "dev":
            argv += ["--dev", mount.dest]
    argv += ["--chdir", "/home/trevi", "--clearenv"]  # bwrap itself adds PWD to the cleared env
    for name, value in spec.env:
        argv += ["--setenv", name, value]
    return argv


def prepare_dirs(spec: NamespaceSpec) -> None:
    """Create the rw source dirs under ROOT (lexically checked first) and make `home` 0700 (bwrap's --perms does not
    apply to a bind)."""
    for mount in spec.mounts:
        if not _is_rw(mount):
            continue
        for path in (mount.src if mount.kind == "bind" else None, mount.upper, mount.work):
            if path is None:
                continue
            if not _under(os.path.normpath(path), os.path.normpath(spec.root)):
                raise SpecRefused([("rw_bind_outside_root", mount.dest)])
            Path(path).mkdir(parents=True, exist_ok=True)
        if mount.tag == "home":
            os.chmod(mount.src, 0o700)


@dataclass(frozen=True)
class NsRun:
    returncode: int
    stdout: str
    stderr: str
    maxrss_kb: int  # critique #13: ru_maxrss of the namespace child (Linux reports KiB)
    timed_out: bool = False


def run_in_namespace(spec: NamespaceSpec, command: list[str], *, timeout: float = 120.0) -> NsRun:
    """Run `command` inside the validated namespace; the child gets a closed env and its rusage is read with wait4."""
    argv = [*bwrap_argv(spec), "--", *command]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env={"PATH": "/usr/bin:/bin"})
        deadline, timed_out = time.monotonic() + timeout, False
        while True:
            pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() > deadline:
                timed_out = True
                proc.kill()
                pid, status, usage = os.wait4(proc.pid, 0)
                break
            time.sleep(0.02)
        proc.returncode = os.waitstatus_to_exitcode(status)
        out.seek(0)
        err.seek(0)
        return NsRun(proc.returncode, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace"),
                     int(usage.ru_maxrss), timed_out)


# Runs INSIDE the namespace with /usr/bin/python3 (stdlib only); prints one JSON object of row -> {ok, ...facts}.
PROBE_SOURCE = r'''
import errno, json, os, socket, subprocess, sys
cfg = json.loads(sys.argv[1])
rows = {}
def row(name, ok, **facts):
    rows[name] = dict(facts, ok=bool(ok))
def writes(path):
    probe = os.path.join(path, cfg["probe_name"])
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        return "errno_" + errno.errorcode.get(exc.errno, str(exc.errno))
    os.close(fd)
    return "written"
for item in cfg["writes"]:
    got = writes(item["dest"])
    expect = item["expect"]
    row("write_" + item["tag"] + "_" + item["name"], got == "written" if expect == "written" else got == "errno_EROFS",
        result=got, expect=expect)
try:
    entries = os.listdir(cfg["secrets"])
    row("secrets_empty", not entries and (os.stat(cfg["secrets"]).st_mode & 0o777) == 0o700, entries=len(entries))
except OSError as exc:
    row("secrets_empty", False, error=errno.errorcode.get(exc.errno, "?"))
row("credentials_absent", not any(os.path.lexists(p) for p in cfg["credentials"]))
for port in cfg["ports"]:
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        row("unreachable_%d" % port, False, result="connected")
    except OSError as exc:
        row("unreachable_%d" % port, True, result=errno.errorcode.get(exc.errno, type(exc).__name__))
    finally:
        s.close()
row("net_isolated", [n for _, n in socket.if_nameindex()] == ["lo"])
row("sockets_absent", not any(os.path.lexists(p) for p in cfg["sockets"]))
try:
    r = subprocess.run(["docker", "version"], capture_output=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
    row("docker_fails", r.returncode != 0, rc=r.returncode)
except FileNotFoundError:
    row("docker_fails", True, rc="absent")
except subprocess.TimeoutExpired:
    row("docker_fails", False, rc="timeout")
import hashlib
for path, sha in cfg["mocks"].items():
    name = os.path.basename(path)
    got = hashlib.sha256(open(path, "rb").read()).hexdigest()
    r = subprocess.run([path], capture_output=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
    row("mock_" + name, got == sha, rc=r.returncode)
try:
    row("journal_empty", os.listdir("/var/log/journal") == [])
except OSError:
    row("journal_empty", False)
try:
    comm = open("/proc/1/comm").read().strip()
except OSError:
    comm = "?"
row("pid1_bwrap", comm == "bwrap", comm=comm)
# /proc/self/environ is the env this process was exec'd with (the interpreter's locale coercion edits os.environ)
names = sorted(e.split(b"=", 1)[0].decode() for e in open("/proc/self/environ", "rb").read().split(b"\0") if e)
row("env_closed", names == sorted(cfg["env_names"]), extra=len(set(names) - set(cfg["env_names"])))
CODE = "import importlib.util as u;s=u.find_spec('codex_harness');print(s.origin if s else '')"
for rel in cfg["releases"]:
    env = {"PATH": "/usr/bin:/bin"}
    if rel.get("pythonpath"):
        env["PYTHONPATH"] = rel["pythonpath"]
    try:
        r = subprocess.run([rel["python"], "-c", CODE], capture_output=True, timeout=60, env=env)
        origin = r.stdout.decode().strip()
    except (OSError, subprocess.SubprocessError) as exc:
        origin = ""
    row("release_origin_" + rel["rev"], origin.startswith(rel["dest"] + "/src/"), found=bool(origin))
if cfg.get("search_path") is not None:
    code = ("import os,psycopg;c=psycopg.connect(os.environ['HARNESS_DATABASE_URL'],connect_timeout=5);"
            "print(c.execute('SHOW search_path').fetchone()[0])")
    try:
        r = subprocess.run([cfg["probe_python"], "-c", code], capture_output=True, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "HARNESS_DATABASE_URL": cfg["dsn"]})
        got = r.stdout.decode().strip()
        row("search_path", r.returncode == 0 and got == cfg["search_path"], rc=r.returncode, matched=got == cfg["search_path"])
    except (OSError, subprocess.SubprocessError):
        row("search_path", False, rc="error")
print(json.dumps(rows))
'''


@dataclass(frozen=True)
class SelftestResult:
    ok: bool
    rows: dict
    maxrss_kb: int
    returncode: int


def _probe_config(spec: NamespaceSpec) -> dict:
    writes = []
    for mount in spec.mounts:
        if mount.tag in ("tmp", "home", "rw", "overlay", "socket"):
            writes.append({"tag": mount.tag, "name": _slug(mount.dest), "dest": mount.dest, "expect": "written"})
        elif mount.tag in ("ro", "release-r0", "release-b") and mount.kind == "ro-bind":
            writes.append({"tag": mount.tag, "name": _slug(mount.dest), "dest": mount.dest, "expect": "erofs"})
    mocks = {m.dest: _sha256(m.src) for m in spec.mounts if m.tag == "mock"}
    env = spec.env_dict()
    cfg = {
        "probe_name": f"{PROBE_NAME}-{spec.run8}", "writes": writes, "secrets": SECRETS_DIR, "mocks": mocks,
        "credentials": ["/home/trevi/.codex", "/home/trevi/.claude"], "ports": [55432, 56379],
        "sockets": ["/run/docker.sock", "/run/systemd/private", "/var/run/docker.sock"], "env_names": sorted([*env, "PWD"]),
        "releases": [{"rev": r.rev, "dest": r.dest, "python": r.python or f"{r.dest}/.venv/bin/python",
                      "pythonpath": r.pythonpath} for r in spec.releases],
        "probe_python": spec.probe_python,
    }
    if "HARNESS_DATABASE_URL" in env:
        cfg["search_path"], cfg["dsn"] = spec.expected_search_path, env["HARNESS_DATABASE_URL"]
    return cfg


def _slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root"


def selftest(spec: NamespaceSpec, evidence=None, *, timeout: float = 240.0) -> SelftestResult:
    """Run the probe INSIDE the namespace, verify on the host that each written probe landed under ROOT, and record one
    evidence step per row (plus the peak memory). A row the probe did not report is a failure, never a skip."""
    cfg = _probe_config(spec)
    run = run_in_namespace(spec, ["/usr/bin/python3", "-I", "-c", PROBE_SOURCE, json.dumps(cfg)], timeout=timeout)
    try:
        rows = json.loads(run.stdout.strip().splitlines()[-1]) if run.stdout.strip() else {}
    except ValueError:
        rows = {}
    expected = {"secrets_empty", "credentials_absent", "unreachable_55432", "unreachable_56379", "net_isolated",
                "sockets_absent", "docker_fails", "journal_empty", "pid1_bwrap", "env_closed"}
    expected |= {f"write_{w['tag']}_{w['name']}" for w in cfg["writes"]}
    expected |= {f"mock_{os.path.basename(p)}" for p in cfg["mocks"]}
    expected |= {f"release_origin_{r.rev}" for r in spec.releases}
    if "search_path" in cfg:
        expected.add("search_path")
    sources = {}
    for mount in spec.mounts:
        if mount.tag in ("tmp", "home", "rw", "socket"):
            sources[f"write_{mount.tag}_{_slug(mount.dest)}"] = mount.src
        elif mount.tag == "overlay":
            sources[f"write_{mount.tag}_{_slug(mount.dest)}"] = mount.upper
    for name, source in sources.items():
        probe = Path(source) / cfg["probe_name"]
        if name in rows and rows[name].get("result") == "written":
            rows[name]["ok"] = probe.exists()  # the write must be visible at its ROOT source
            rows[name]["landed_under_root"] = probe.exists()
            if probe.exists():
                probe.unlink()
    for name in sorted(expected):
        rows.setdefault(name, {"ok": False, "result": "missing"})
    rows = {k: rows[k] for k in sorted(rows)}
    ok = run.returncode == 0 and not run.timed_out and all(r["ok"] for r in rows.values())
    if evidence is not None:
        for name, facts in rows.items():
            evidence.step(f"selftest_{name}", "pass" if facts["ok"] else "fail",
                          {k: v for k, v in facts.items() if k != "ok"})
        evidence.step("selftest_run", "pass" if ok else "fail",
                      {"returncode": run.returncode, "maxrss_kb": run.maxrss_kb, "timed_out": run.timed_out})
    return SelftestResult(ok, rows, run.maxrss_kb, run.returncode)
