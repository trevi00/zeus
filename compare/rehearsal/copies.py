"""Disposable rehearsal copies (RH-1a rule 3, 4, 6): one copy X = one PostgreSQL + one Redis container.

Every docker argv is checked with `provider_guard.docker_policy` (pure) before it is spawned. The containers
are labelled, network-less, run as the caller's uid, never pull (the pinned images must already be present),
publish no port and mount no named volume; all state lives in bind directories under ROOT:

    ROOT/p                 the source dump(s) and `ROOT/p/redis`, the AOF directory copy (read-only at /dump)
    ROOT/<X>/pgdata|pgsock|redis|redsock

Roles, catalog reads and the Redis inventory run HOST-SIDE over the copy's Unix sockets (`psycopg`, `redis`);
only `pg_restore` runs through `docker exec` (the guard's PGEXEC opt-in). Catalog digest: the product's own
`host_migration.pg_catalog` / `catalog_digest` (the same function on both sides).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import Refused, check_run8

COMPARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPARE / "guard"))
import provider_guard  # noqa: E402


def _load_run():
    spec = importlib.util.spec_from_file_location("rehearsal_compare_run", COMPARE / "run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_run()
PG_IMAGE, REDIS_IMAGE, OWNER_KEY = RUN.PG_IMAGE, RUN.REDIS_IMAGE, RUN.OWNER_KEY
COPY_NAMES = frozenset({"S", "A", "B", "D", "R7", "seal-b"})
PRODUCTION_PREFIX = "zeus-aibox-"
RUN_LABEL, COPY_LABEL = "zeus.rehearsal.run", "zeus.rehearsal.copy"
PG_USER, PG_SOCKET_DIR, REDIS_SOCKET_DIR = "zeus", "/var/run/postgresql", "/run/zeus-redis"
SOCKET_LIMIT = 107  # sun_path
MARKER = ".rehearsal-root"
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
TOC_LINE = re.compile(r"^\d+;\s+\d+\s+\d+\s+\S")
PGDATA = "/var/lib/postgresql/data"
TRACE_LOG_DIR = "rh-trace-log"  # inside the bind-mounted pgdata: the host reads it from ROOT, never `docker logs` (RH-4c)


def fixture_name(run8: str, copy: str, kind: str) -> str:
    return f"{provider_guard.FIXTURE_NAME_PREFIX}rh-{run8}-{copy}-{kind}"


def guarded_docker(args, *, root: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Spawn `docker <args>` only when `docker_policy` admits the exact argv (opt-ins set for this child only)."""
    env = {**os.environ, provider_guard.DOCKER_OPT_IN_ENV: "1", provider_guard.DOCKER_PGEXEC_ENV: "1"}
    if root is not None:
        env[provider_guard.DOCKER_BIND_ROOT_ENV] = str(root)
    argv = ["docker", *args]
    provider_guard.docker_policy(argv, env)
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)


def run_argv(name: str, *, image: str, labels, mounts, uid: int, gid: int, memory: str, memory_swap: str | None = None,
             env=(), command=(), publish=(), volumes=()) -> list[str]:
    """The `docker run` args of one rehearsal container; every refusal is raised here, before any docker call.

    `mounts` are `(host_dir, container_dir, read_only)` bind mounts. A production name, a published port and a
    named volume are each refused (AMD-1 C.3/C.4)."""
    if name.startswith(PRODUCTION_PREFIX):
        raise Refused("production_name", name)
    if not name.startswith(provider_guard.FIXTURE_NAME_PREFIX + "rh-"):
        raise Refused("not_fixture_name", name)
    if publish:
        raise Refused("published_port")
    if volumes:
        raise Refused("named_volume")
    args = ["run", "-d", "--rm", "--network", "none"]
    for label in labels:
        args += ["--label", label]
    args += ["--name", name, "--user", f"{uid}:{gid}", "--memory", memory]
    if memory_swap:
        args += ["--memory-swap", memory_swap]
    for source, target, read_only in mounts:
        if not Path(source).is_absolute():
            raise Refused("named_volume", "a mount source must be an absolute host directory")
        args += ["--mount", f"type=bind,src={source},dst={target}" + (",readonly" if read_only else "")]
    for item in env:
        args += ["-e", item]
    return [*args, image, *command]


def toc_roles(listing: str) -> list[str]:
    """Role names from the owner field of every `pg_restore -l` entry (the last field; empty/`-` = none).

    The TOC prints an entry's owner (ACL entries carry the owner too); the grantees of a GRANT are not in the
    TOC and are not guessed."""
    roles = []
    for line in listing.splitlines():
        if line.startswith(";") or not TOC_LINE.match(line) or line.endswith(" "):
            continue
        owner = line.rsplit(" ", 1)[1]
        if owner != "-" and IDENT.match(owner) and owner not in roles:
            roles.append(owner)
    return sorted(roles)


def pg_command(trace: bool = False) -> list[str]:
    """The postgres server arguments of a copy. `trace` (opt-in, RH-4c; OFF by default) adds the statement log the R4
    read-coverage map parses: the logging collector writing every statement under `TRACE_LOG_DIR` inside the pgdata."""
    command = ["-c", "listen_addresses="]
    if trace:
        command += ["-c", "logging_collector=on", "-c", f"log_directory={PGDATA}/{TRACE_LOG_DIR}", "-c", "log_statement=all"]
    return command


def key_pattern(key: str) -> str:
    """A key name with every digit run and long hex run replaced by `*` (no values, no ids)."""
    return re.sub(r"[0-9a-f]{12,}|[0-9]+", "*", key)


def redis_inventory(socket: Path) -> dict:
    """Key count, type histogram and stream lengths per key-name pattern of db 0; never a value."""
    import redis

    client = redis.Redis(unix_socket_path=str(socket), db=0, socket_timeout=10)
    types: dict[str, int] = {}
    streams: dict[str, dict[str, int]] = {}
    count = 0
    for key in client.scan_iter(count=1000):
        kind = client.type(key).decode()
        types[kind] = types.get(kind, 0) + 1
        count += 1
        if kind == "stream":
            entry = streams.setdefault(key_pattern(key.decode("utf-8", "replace")), {"keys": 0, "entries": 0})
            entry["keys"] += 1
            entry["entries"] += client.xlen(key)
    return {"keys": count, "types": dict(sorted(types.items())), "streams": dict(sorted(streams.items()))}


def pg_dsn(socket: Path, database: str = "postgres") -> str:
    return f"host={socket} port=5432 dbname={database} user={PG_USER} connect_timeout=5"


def catalog_sha256(socket: Path, database: str) -> str:
    """The product digest over the whole-database catalog (owners, ACLs, columns, row digests, ...)."""
    from codex_harness.delivery.adapters.host_migration import catalog_digest, pg_catalog

    return catalog_digest(pg_catalog(pg_dsn(socket, database), database))


def create_root(root: Path, run8: str) -> None:
    """Create ROOT itself, exclusively and umask-proof 0700, with the run marker (RH-8 F4); its parent may be created."""
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(root, 0o700)  # exclusive: FileExistsError if anything (even a symlink) is already there
    os.chmod(root, 0o700)  # the umask may have cleared bits mkdir would otherwise keep
    marker = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(marker, "w", encoding="ascii") as handle:
        handle.write(run8 + "\n")


def verify_root(root: Path) -> None:
    """Refuse (before any acquisition) a ROOT that is not a real directory owned by this uid with mode exactly 0700."""
    info = os.lstat(root)
    if stat.S_ISLNK(info.st_mode):
        raise Refused("root_symlink", "the rehearsal root is a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise Refused("root_not_directory", "the rehearsal root is not a directory")
    if info.st_uid != os.getuid():
        raise Refused("root_foreign_owner", "the rehearsal root is owned by another uid")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise Refused("root_mode", f"the rehearsal root mode is {stat.S_IMODE(info.st_mode):04o}, not 0700")


@dataclass(frozen=True)
class Copy:
    copy: str
    pg_name: str
    redis_name: str
    pg_socket: Path
    redis_socket: Path
    trace_dir: Path | None = None  # the host path of the statement log directory (trace copies only)


class Copies:
    def __init__(self, run8: str, root: Path, *, docker=None):
        self.run8, self.root = check_run8(run8), Path(root)
        self.docker = docker or (lambda *args, timeout=120: guarded_docker(args, root=self.root, timeout=timeout))
        self.copies: dict[str, Copy] = {}

    @property
    def source(self) -> Path:
        return self.root / "p"

    def _labels(self, copy: str, owner: str) -> list[str]:
        return [provider_guard.FIXTURE_LABEL, f"{RUN_LABEL}={self.run8}", f"{COPY_LABEL}={copy}",
                "zeus.rebuild=rehearsal", f"{OWNER_KEY}={owner}"]

    def prepare_root(self) -> None:
        """Create ROOT exclusively as 0700 (RH-8 F4), or attach to an existing owner-only run root; never adopt a
        permissive, symlinked or foreign one."""
        if os.path.lexists(self.root):
            verify_root(self.root)
            marker = self.root / MARKER
            if marker.exists():
                if marker.read_text(encoding="ascii").strip() != self.run8:
                    raise Refused("root_foreign", "the root belongs to another run")
            else:
                marker.write_text(self.run8 + "\n", encoding="ascii")
        else:
            create_root(self.root, self.run8)
        self.source.mkdir(exist_ok=True)
        self.source.chmod(0o700)

    def _require_image(self, image: str) -> None:
        found = self.docker("image", "inspect", "--format", "{{.Id}}", image)
        if found.returncode != 0:
            raise Refused("image_missing", "the pinned image is not present locally; never pulled")

    def start(self, copy: str, *, publish=(), volumes=(), empty_redis: bool = False, trace: bool = False) -> Copy:
        """Start one copy. `empty_redis` starts its Redis EMPTY instead of over a working copy of the source AOF directory
        (a restore target, `r7a`: the data must arrive through the restore tooling, never through the seed). `trace`
        (RH-4c, opt-in) starts PostgreSQL with statement logging into the bind-mounted pgdata for the coverage map."""
        if copy not in COPY_NAMES:
            raise Refused("unknown_copy", copy)
        if copy in self.copies:
            raise Refused("copy_exists", copy)
        if publish:
            raise Refused("published_port")
        if volumes:
            raise Refused("named_volume")
        base = self.root / copy
        sockets = {"pgsock": len("/.s.PGSQL.5432"), "redsock": len("/redis.sock")}
        for directory, tail in sockets.items():
            if len(str(base / directory)) + tail >= SOCKET_LIMIT:
                raise Refused("socket_path_too_long", directory)
        uid, gid = os.getuid(), os.getgid()
        owner = f"{os.getpid()}-{time.monotonic_ns()}"
        names = {kind: fixture_name(self.run8, copy, kind) for kind in ("pg", "redis")}
        labels = self._labels(copy, owner)
        pg = run_argv(names["pg"], image=PG_IMAGE, labels=labels, uid=uid, gid=gid, memory="4g", memory_swap="4g",
                      mounts=[(base / "pgdata", PGDATA, False),
                              (base / "pgsock", PG_SOCKET_DIR, False), (self.source, "/dump", True)],
                      env=[f"POSTGRES_USER={PG_USER}", "POSTGRES_HOST_AUTH_METHOD=trust"],
                      command=pg_command(trace), publish=publish, volumes=volumes)
        redis = run_argv(names["redis"], image=REDIS_IMAGE, labels=labels, uid=uid, gid=gid, memory="1g",
                         mounts=[(base / "redis", "/data", False), (base / "redsock", REDIS_SOCKET_DIR, False)],
                         command=["redis-server", "--port", "0", "--unixsocket", f"{REDIS_SOCKET_DIR}/redis.sock",
                                  "--unixsocketperm", "700", "--dir", "/data", "--appendonly", "yes", "--save", ""],
                         publish=publish, volumes=volumes)
        self.prepare_root()
        self._require_image(PG_IMAGE)
        self._require_image(REDIS_IMAGE)
        for name in names.values():
            if self.docker("inspect", "--format", "{{.Id}}", name).returncode == 0:
                raise Refused("name_taken", name)
        base.mkdir()
        for directory in ("pgdata", "pgsock", "redsock"):
            (base / directory).mkdir()
        (base / "pgdata").chmod(0o700)
        # This copy's OWN working copy of the AOF directory, never the source copy itself.
        if not empty_redis and (self.source / "redis").is_dir():
            shutil.copytree(self.source / "redis", base / "redis", symlinks=True)
        else:
            (base / "redis").mkdir()
        handle = Copy(copy, names["pg"], names["redis"], base / "pgsock", base / "redsock",
                      base / "pgdata" / TRACE_LOG_DIR if trace else None)
        self.copies[copy] = handle
        started = []
        try:
            for name, argv, ready in ((names["pg"], pg, self._pg_ready), (names["redis"], redis, self._redis_ready)):
                done = self.docker(*argv, timeout=300)
                if done.returncode != 0:
                    raise RuntimeError(f"{name} did not start: " + done.stderr.strip()[-300:])
                started.append(name)
                ready(handle)
        except BaseException:
            for name in started:
                self.docker("rm", "-f", name)
            del self.copies[copy]
            raise
        return handle

    def _wait_log(self, name: str, ready, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            logs = self.docker("logs", name)
            if ready(logs.stdout + logs.stderr):
                return
            time.sleep(1)
        raise RuntimeError(f"{name} did not become ready")

    def _pg_ready(self, handle: Copy) -> None:
        if handle.trace_dir is not None:
            # the collector moves the server log into the pgdata, so `docker logs` never shows "ready to accept
            # connections": after the entrypoint's init-complete line (its temp server is already stopped), the first
            # connection over the socket is the real server
            self._wait_log(handle.pg_name, lambda text: "PostgreSQL init process complete" in text, 120)
            import psycopg

            deadline = time.monotonic() + 60
            while True:
                try:
                    psycopg.connect(pg_dsn(handle.pg_socket), connect_timeout=2).close()
                    return
                except psycopg.OperationalError:
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"{handle.pg_name} did not become ready") from None
                    time.sleep(0.5)

        def ready(text: str) -> bool:
            done = text.find("PostgreSQL init process complete")
            return done >= 0 and "ready to accept connections" in text[done:]

        self._wait_log(handle.pg_name, ready, 120)

    def _redis_ready(self, handle: Copy) -> None:
        self._wait_log(handle.redis_name, lambda text: "Ready to accept connections" in text, 60)

    def pg_tool(self, copy: str, program: str, *args: str) -> subprocess.CompletedProcess:
        """`docker exec <pg container> <program> -U zeus -h /var/run/postgresql <args>` (the guard's tool form)."""
        return self.docker("exec", self.copies[copy].pg_name, program, "-U", PG_USER, "-h", PG_SOCKET_DIR, *args,
                           timeout=900)

    def role_preflight(self, copy: str, dump: str) -> dict:
        """Create every TOC owner role missing on this disposable server, NOLOGIN; return them as declared facts."""
        import psycopg
        from psycopg import sql

        if not IDENT.match(dump):
            raise Refused("bad_dump_name", dump)
        listing = self.pg_tool(copy, "pg_restore", "-l", f"/dump/{dump}")
        if listing.returncode != 0:
            raise RuntimeError("pg_restore -l failed: " + listing.stderr.strip()[-300:])
        wanted = toc_roles(listing.stdout)
        created = []
        with psycopg.connect(pg_dsn(self.copies[copy].pg_socket), autocommit=True) as conn:
            present = {row[0] for row in conn.execute("SELECT rolname FROM pg_roles")}
            for role in wanted:
                if role not in present:
                    conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
                    created.append(role)
        return {"roles_in_toc": wanted, "roles_created_nologin": created}

    def restore(self, copy: str, dump: str, database: str) -> dict:
        """Role preflight, then `pg_restore --exit-on-error --single-transaction -d <database>`, then the digest."""
        import psycopg
        from psycopg import sql

        if not IDENT.match(database):
            raise Refused("bad_database_name", database)
        if not (self.source / dump).is_file():
            raise Refused("dump_missing", dump)
        facts = self.role_preflight(copy, dump)
        with psycopg.connect(pg_dsn(self.copies[copy].pg_socket), autocommit=True) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone() is None:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        done = self.pg_tool(copy, "pg_restore", "--exit-on-error", "--single-transaction", "-d", database,
                            f"/dump/{dump}")
        if done.returncode != 0:
            raise RuntimeError("pg_restore failed: " + done.stderr.strip()[-300:])
        return {**facts, "database": database, "catalog_sha256": self.catalog_sha256(copy, database),
                "catalog_digest_source": "codex_harness.delivery.adapters.host_migration.catalog_digest"}

    def catalog_sha256(self, copy: str, database: str) -> str:
        return catalog_sha256(self.copies[copy].pg_socket, database)

    def redis_inventory(self, copy: str) -> dict:
        return redis_inventory(self.copies[copy].redis_socket / "redis.sock")


def _rel_parts(rel: str) -> tuple[str, ...]:
    parts = tuple(p for p in rel.split("/") if p)
    if not parts or ".." in parts or rel.startswith("/"):
        raise Refused("volatile_path_bad", rel)
    return parts


# Critique #5: the live roots are written continuously, so a sealed whole-tree copy would refuse; these paths are copied
# as point-in-time single-file snapshots instead. RH-1b: the list is `volatile.json`, derived from the WRITERS of the five
# R0 releases (each entry cites `file:line` at the revisions that write it) and from two read-only name/mtime listings of
# the live roots, and it is CLOSED: a path under `SCAN_ROOTS` that changes during the snapshot and is neither listed nor
# excluded refuses `volatile_undeclared` (RH-8 review: "RH integration must supply the actual paths ...").
VOLATILE_FILE = Path(__file__).with_name("volatile.json")
SCAN_ROOTS = ("runtime", "managed-fleet")  # the production roots the closed list covers, relative to the staged source


def load_volatile(path: Path = VOLATILE_FILE) -> dict:
    """The volatile document, validated: every entry is a safe relative path with at least one writer citation."""
    import json

    document = json.loads(Path(path).read_text(encoding="utf-8"))
    for entry in document["volatile"]:
        _rel_parts(entry["path"])
        if entry["kind"] not in ("file", "dir") or not entry["writers"]:
            raise Refused("volatile_entry_bad", entry["path"])
        for writer in entry["writers"]:
            if not (writer["rev"] in document["r0_revisions"] and writer["line"] >= 1 and writer["file"] and writer["text"]):
                raise Refused("volatile_entry_bad", entry["path"])
    for entry in document["excluded"]:
        _rel_parts(entry["path"])
        if not entry["reason"]:
            raise Refused("volatile_entry_bad", entry["path"])
    return document


_VOLATILE = load_volatile()
VOLATILE_PATHS = tuple(entry["path"] for entry in _VOLATILE["volatile"])
EXCLUDED_PATHS = tuple(entry["path"] for entry in _VOLATILE["excluded"])  # runtime/tokobs: not Zeus state


def scan_tree(source: Path, roots=SCAN_ROOTS, excluded=EXCLUDED_PATHS) -> dict[str, tuple[int, int]]:
    """`{relative path: (mtime_ns, size)}` of every non-directory entry under `roots` (lstat only: names, sizes and
    mtimes, never a content read; excluded subtrees are pruned). A directory's own mtime is a consequence of its entries
    and is not recorded."""
    source = Path(source)
    excl = [_rel_parts(e) for e in excluded]
    found: dict[str, tuple[int, int]] = {}
    pending = [source.joinpath(*_rel_parts(r)) for r in roots]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except FileNotFoundError:
            continue
        for entry in entries:
            rel = Path(entry.path).relative_to(source).as_posix()
            if any(tuple(rel.split("/"))[: len(e)] == e for e in excl):
                continue
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
            else:
                found[rel] = (info.st_mtime_ns, info.st_size)
    return found


def _covered(rel: str, listed) -> bool:
    parts = tuple(rel.split("/"))
    return any(parts[: len(p)] == p for p in map(_rel_parts, listed))


def undeclared_changes(before: dict, after: dict, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS) -> list[str]:
    """The paths that appeared, vanished or changed (mtime or size) between two scans and are neither volatile nor excluded."""
    changed = sorted(rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel))
    return [rel for rel in changed if not _covered(rel, volatile) and not _covered(rel, excluded)]


def stable_sha256(scan: dict, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS) -> str:
    """One digest over the (path, mtime_ns, size) of every stable file of a scan: what `verify-staged` must see unchanged."""
    lines = [f"{rel} {m} {n}\n" for rel, (m, n) in sorted(scan.items())
             if not _covered(rel, volatile) and not _covered(rel, excluded)]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def snapshot_volatile(source: Path, dest: Path, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS, *,
                      scan_roots=SCAN_ROOTS, during=None) -> dict:
    """Copy each declared volatile file (or the regular files of a declared directory) from `source` to `dest` once,
    reading it a single time so the recorded size/mtime/sha256 describe exactly the bytes written; the copy is a new
    inode, so a later change on either side never reaches the other. Symlinks and excluded paths are refused/skipped.

    Fail closed (RH-1b): `scan_roots` are listed (names, sizes, mtimes) before the reads and again after `during()` (the
    staging of the stable subtrees in the real flow, a writer in tests); any other path that changed refuses
    `volatile_undeclared`; the stable files' digest before and after is recorded (`stable`)."""
    source, dest = Path(source), Path(dest)
    before = scan_tree(source, scan_roots, excluded) if scan_roots else {}
    excl = [_rel_parts(e) for e in excluded]
    files, skipped = [], []
    for rel in volatile:
        parts = _rel_parts(rel)
        if any(parts[: len(e)] == e or e[: len(parts)] == parts for e in excl):
            raise Refused("volatile_excluded", rel)
        base = source.joinpath(*parts)
        if any(source.joinpath(*parts[: i + 1]).is_symlink() for i in range(len(parts))):
            raise Refused("volatile_symlink", rel)
        if base.is_dir():
            files += [(rel_file, f) for rel_file, f in _walk(source, base)]
        elif base.is_file():
            files.append((rel, base))
        else:
            skipped.append(rel)
    entries = []
    for rel, path in sorted(files):
        if any(tuple(rel.split("/"))[: len(e)] == e for e in excl):
            skipped.append(rel)
            continue
        before_stat = path.stat()
        data = path.read_bytes()
        read_at = time.time_ns()
        target = dest.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as handle:
            handle.write(data)
        entries.append({"path": rel, "size": len(data), "mtime_ns": before_stat.st_mtime_ns, "read_at_ns": read_at,
                        "sha256": hashlib.sha256(data).hexdigest()})
    if during is not None:
        during()
    reads = [e["read_at_ns"] for e in entries]
    manifest = {"files": entries, "skipped": sorted(set(skipped)), "excluded": list(excluded),
                "skew_ns": (max(reads) - min(reads)) if reads else 0}
    if scan_roots:
        after = scan_tree(source, scan_roots, excluded)
        undeclared = undeclared_changes(before, after, volatile, excluded)
        if undeclared:
            raise Refused("volatile_undeclared", f"{len(undeclared)} path(s) changed outside the closed list: "
                          + ", ".join(undeclared[:5]))
        manifest["stable"] = {"files": sum(1 for r in before if not _covered(r, volatile) and not _covered(r, excluded)),
                              "sha256": stable_sha256(before, volatile, excluded),
                              "sha256_after": stable_sha256(after, volatile, excluded), "unchanged": True}
    return manifest


def _walk(source: Path, base: Path):
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                raise Refused("volatile_symlink", name)
            yield full.relative_to(source).as_posix(), full
