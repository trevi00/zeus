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

import importlib.util
import os
import re
import shutil
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


@dataclass(frozen=True)
class Copy:
    copy: str
    pg_name: str
    redis_name: str
    pg_socket: Path
    redis_socket: Path


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
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / MARKER
        if marker.exists():
            if marker.read_text(encoding="ascii").strip() != self.run8:
                raise Refused("root_foreign", "the root belongs to another run")
        else:
            marker.write_text(self.run8 + "\n", encoding="ascii")
        self.source.mkdir(exist_ok=True)

    def _require_image(self, image: str) -> None:
        found = self.docker("image", "inspect", "--format", "{{.Id}}", image)
        if found.returncode != 0:
            raise Refused("image_missing", "the pinned image is not present locally; never pulled")

    def start(self, copy: str, *, publish=(), volumes=()) -> Copy:
        if copy not in COPY_NAMES:
            raise Refused("unknown_copy", copy)
        if copy in self.copies:
            raise Refused("copy_exists", copy)
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
                      mounts=[(base / "pgdata", "/var/lib/postgresql/data", False),
                              (base / "pgsock", PG_SOCKET_DIR, False), (self.source, "/dump", True)],
                      env=[f"POSTGRES_USER={PG_USER}", "POSTGRES_HOST_AUTH_METHOD=trust"],
                      command=["-c", "listen_addresses="], publish=publish, volumes=volumes)
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
        if (self.source / "redis").is_dir():
            shutil.copytree(self.source / "redis", base / "redis", symlinks=True)
        else:
            (base / "redis").mkdir()
        handle = Copy(copy, names["pg"], names["redis"], base / "pgsock", base / "redsock")
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
