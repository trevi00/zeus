"""The rehearsal R7a restore runner (RH-6a): the D0 archive restored onto a FRESH R7 copy with the PINNED rollback tooling.

Layer: harness (never shipped). Standard library plus the tooling modules (`copies`, `d0`, `evidence`). Rehearsal design
"9. R7" (R7a only), AC10 and critique #10 (`cutover-critique-rehearsal.json`: the fakebin docker shim).

The tooling is the rollback release's own: `<release>/.venv/bin/python -m codex_harness.adapters.host_migration pg-restore-db ...`
then `redis-copy ...` (`<release>` is a parameter recorded in the evidence). The tool runs OUTSIDE the bwrap namespace (docker exec
needs the host's docker): that is a DECLARED non-namespace step (`non_namespace_step: true` in the record), and the in-process
provider guard does not reach the pinned release's own process. The substitute isolation is the shim:

    ROOT/r7/fakebin/docker    generated here, mode 0700, placed FIRST on the PATH of the `pg-restore-db` child only

It forwards exactly `docker exec zeus-test-fixture-rh-<run8>-R7-pg {pg_restore | sha256sum} ...` (the forms of the tool's
`_docker_pg`/`_archive_facts`, with the docker guard's argument rules: `-U <ident> -h /var/run/postgresql` first, every path
`/dump/<name>`, no `..`) after reading that container's labels (`zeus.rehearsal.run=<run8>`, `zeus.test.fixture=1`), and refuses
everything else (another form, a production or another run's name, a missing label) with exit 97 and a logged line
(`ROOT/r7/fakebin.log`, one JSON object per call). The shim is never on any other child's PATH nor in this process's env.

Layout: `ROOT/r7/` holds the receipt, the source catalog and identity map handed to the tool, the shim and its log. The copy's
own directory is `ROOT/R7` (`copies.COPY_NAMES`); its containers are `zeus-test-fixture-rh-<run8>-R7-{pg,redis}`.

PASS = the receipt state is `renamed` and `verified`, the R7 catalog digest equals the D0 record's, and the R7 Redis facts equal
the D0 record's (`compare-redis` inside `redis-copy` must also have been ok). Anything else fails (record written first).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from . import Refused, check_run8, d0
from .copies import IDENT, Copies, catalog_sha256, fixture_name, pg_dsn
from .evidence import _utc_now, write_record

MAX_RECORD_ITEMS = 4096
SHIM_EXIT = 97
MODULE = "codex_harness.adapters.host_migration"
DSN_ENV = "RH_R7_PG_DSN"
BASE_PATH = "/usr/bin:/bin"
SOURCE_COPY, TARGET_COPY = "S", "R7"
PG_DEFAULT_DB = "zeus"  # the image creates the default database named after POSTGRES_USER

SHIM = r'''#!/usr/bin/python3
"""rehearsal docker shim (run %(run8)s): forwards `docker exec <R7 pg container> {pg_restore|sha256sum} ...` only."""
import json, os, re, subprocess, sys

RUN8, CONTAINER, REAL, LOG = %(run8)r, %(container)r, %(real)r, %(log)r
DUMP = re.compile(r"^/dump/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SOCKET_DIR = "/var/run/postgresql"
args = sys.argv[1:]


def record(verdict, reason):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": args, "verdict": verdict, "reason": reason}, sort_keys=True) + "\n")


def refuse(reason):
    record("refuse", reason)
    sys.stderr.write("rehearsal docker shim: refused (" + reason + ")\n")
    sys.exit(%(exit)d)


if len(args) < 3 or args[0] != "exec":
    refuse("form: only `docker exec <container> <tool> ...` is forwarded")
name, program, rest = args[1], args[2], args[3:]
if name != CONTAINER:
    refuse("container_name")
if program == "sha256sum":
    if len(rest) != 1 or not DUMP.match(rest[0]):
        refuse("sha256sum_operand")
elif program == "pg_restore":
    if len(rest) < 4 or rest[0] != "-U" or not IDENT.match(rest[1]) or rest[2:4] != ["-h", SOCKET_DIR]:
        refuse("pg_tool_prefix")
    for token in rest[4:]:
        value = token.partition("=")[2] if token.startswith("--") and "=" in token else token
        if value.startswith("/") and not DUMP.match(value):
            refuse("pg_tool_path")
        if ".." in value:
            refuse("pg_tool_dotdot")
else:
    refuse("program")
found = subprocess.run(
    [REAL, "inspect", "--format", '{{index .Config.Labels "zeus.rehearsal.run"}}|{{index .Config.Labels "zeus.test.fixture"}}',
     name], capture_output=True, text=True)
if found.returncode != 0 or found.stdout.strip() != RUN8 + "|1":
    refuse("label")
record("forward", program)
os.execv(REAL, [REAL, *args])
'''


def write_shim(directory: Path, run8: str, real_docker: str, log: Path) -> Path:
    """Generate `<directory>/docker` (0700, exclusive) for run `run8`; `real_docker` is the absolute docker it forwards to."""
    check_run8(run8)
    if not os.path.isabs(real_docker) or not os.path.isabs(log):
        raise Refused("shim_path_not_absolute")
    directory = Path(directory)
    directory.mkdir(mode=0o700)
    path = directory / "docker"
    text = SHIM % {"run8": run8, "container": fixture_name(run8, TARGET_COPY, "pg"), "real": real_docker, "log": str(log),
                   "exit": SHIM_EXIT}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def read_shim_log(log: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in Path(log).read_text(encoding="utf-8").splitlines() if line]
    except FileNotFoundError:
        return []


class R7aFailed(Refused):
    """The record was written with `status: failed`; `document` is that record and `failures` its reasons."""

    def __init__(self, document: dict):
        self.document, self.failures = document, document["facts"]["failures"]
        super().__init__("r7a_failed", "; ".join(self.failures[:8]))


def _spawn(argv: list[str], env: dict, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, cwd=env.get("PWD") or None, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, check=False)


def tool_env(work: Path, *, shim: Path | None, pg_dsn_value: str | None = None) -> dict:
    """The closed env of a pinned-tooling child: the shim directory leads PATH only when `shim` is given (pg-restore-db)."""
    path = f"{shim.parent}:{BASE_PATH}" if shim is not None else BASE_PATH
    env = {"PATH": path, "PWD": str(work), "LC_ALL": "C.UTF-8"}
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]  # the docker client reads its config from HOME; never recorded
    if pg_dsn_value is not None:
        env[DSN_ENV] = pg_dsn_value
    return env


def _digest(text: str) -> dict:
    return {"bytes": len(text.encode("utf-8")), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _refusal(stdout: str) -> str | None:
    """The tool's named refusal (`{"refused": code}`), the only part of its output the record keeps."""
    try:
        refused = json.loads(stdout.strip().splitlines()[-1]).get("refused")
    except (ValueError, IndexError, AttributeError):
        return None
    return refused if isinstance(refused, str) and IDENT.match(refused) else None


def _fresh(copies: Copies) -> list[str]:
    """What a fresh R7 server must not hold: a database besides `postgres` and the image's empty default `zeus` (which
    must hold no user table), a database role-owned object or any Redis key."""
    import psycopg

    found = []
    socket = copies.copies[TARGET_COPY].pg_socket
    with psycopg.connect(pg_dsn(socket), autocommit=True) as conn:
        names = [n for (n,) in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'")]
    found += [f"database:{name}" for name in names if name != PG_DEFAULT_DB]
    if PG_DEFAULT_DB in names:
        with psycopg.connect(pg_dsn(socket, PG_DEFAULT_DB), autocommit=True) as conn:
            tables = conn.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE "
                                  "c.relkind IN ('r', 'p', 'v', 'm', 'S') AND n.nspname NOT IN ('pg_catalog', "
                                  "'information_schema', 'pg_toast')").fetchone()[0]
        found += [f"relations:{PG_DEFAULT_DB}"] if tables else []
    if copies.redis_inventory(TARGET_COPY)["keys"]:
        found.append("redis_keys")
    return found


def run_r7a(copies: Copies, *, release: Path | str, dump: str, database: str, d0_record: dict, out,
            archive_sha256: str | None = None, real_docker: str | None = None, spawn: Callable = _spawn,
            timeout: float = 900.0, clock=_utc_now) -> dict:
    """Restore `dump` (a file in `copies.source`) onto a fresh R7 copy with the pinned tooling of `release`, then verify;
    write `out/r7.json`; raise `R7aFailed` (after writing) on any failure. `copies` must hold the started source copy S
    (D0's source: the catalog handed to the tool is read from it and must equal the D0 record's)."""
    if not IDENT.match(dump) or not IDENT.match(database):
        raise Refused("bad_name", "dump/database")
    release = Path(release)
    python = release / ".venv" / "bin" / "python"
    if not os.access(python, os.X_OK):
        raise Refused("tooling_missing", "the pinned release has no .venv/bin/python")
    if SOURCE_COPY not in copies.copies:
        raise Refused("source_copy_missing", SOURCE_COPY)
    docker = real_docker or shutil.which("docker")
    if not docker:
        raise Refused("docker_missing")
    from codex_harness.delivery.adapters.host_migration import catalog_digest, pg_catalog
    from codex_harness.delivery.domain.host_migration import catalog_schemas

    facts0 = d0_record["facts"]
    failures: list[str] = []
    archive = copies.source / dump
    if not archive.is_file():
        raise Refused("dump_missing", dump)
    sha = archive_sha256 or hashlib.sha256(archive.read_bytes()).hexdigest()
    source = copies.copies[SOURCE_COPY]
    catalog = pg_catalog(pg_dsn(source.pg_socket, database), database)
    if catalog_digest(catalog) != facts0["catalog_sha256"]:
        failures.append("source_not_d0")
    work = copies.root / "r7"
    work.mkdir(mode=0o700)
    handle = copies.start(TARGET_COPY, empty_redis=True)
    facts: dict = {"database": database, "release": release.name, "release_dir": str(release), "tooling": python.name,
                   "tooling_module": MODULE, "non_namespace_step": True, "dump": dump, "archive_sha256": sha,
                   "container": handle.pg_name}
    stale = _fresh(copies)
    facts["r7_fresh"] = not stale
    failures += [f"r7a_not_fresh:{item}" for item in stale]
    facts["roles"] = copies.role_preflight(TARGET_COPY, dump)
    (work / "d0-catalog.json").write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    (work / "identity.json").write_text(json.dumps({s: s for s in catalog_schemas(catalog)}, sort_keys=True),
                                        encoding="utf-8")
    log = work / "fakebin.log"
    shim = write_shim(work / "fakebin", copies.run8, docker, log)
    base = [str(python), "-m", MODULE]
    restore = [*base, "pg-restore-db", "--container", handle.pg_name, "--user", "zeus", "--dsn-env", DSN_ENV, "--database",
               database, "--path", f"/dump/{dump}", "--archive-sha256", sha, "--source-catalog", str(work / "d0-catalog.json"),
               "--schema-map", str(work / "identity.json"), "--receipt", str(work / "receipt.json")]
    done = _run_step(spawn, restore, tool_env(work, shim=shim, pg_dsn_value=pg_dsn(handle.pg_socket)), timeout, failures,
                     "pg_restore_db")
    facts["pg_restore_db"] = {"exit": done.returncode, "stdout": _digest(done.stdout), "stderr": _digest(done.stderr),
                              "refused": _refusal(done.stdout)}
    receipt = _read_receipt(work / "receipt.json")
    facts["receipt"] = {k: receipt.get(k) for k in ("state", "verified", "renamed_catalog_sha256", "archive_sha256")
                        if isinstance(receipt.get(k), (str, bool))}
    if receipt.get("state") != "renamed" or receipt.get("verified") is not True:
        failures.append(f"r7a_receipt_state:{receipt.get('state')}")
    try:
        r7_digest = catalog_sha256(handle.pg_socket, database)
    except Exception as error:  # noqa: BLE001 - the class is the fact; a missing database is a failed restore
        r7_digest = None
        failures.append(f"r7a_catalog_unreadable:{type(error).__name__}")
    facts |= {"catalog_sha256_d0": facts0["catalog_sha256"], "catalog_sha256_r7": r7_digest,
              "catalog_equals_d0": r7_digest == facts0["catalog_sha256"]}
    if r7_digest is not None and r7_digest != facts0["catalog_sha256"]:
        failures.append("r7a_catalog_differs")
    prefixes = sorted({k.partition("|")[2] for k, _ in facts0["redis_prefixes"].items() if k.startswith("db0|")})
    other_dbs = sorted({k.partition("|")[0] for k in facts0["redis_prefixes"] if not k.startswith("db0|")})
    failures += [f"r7a_redis_db_not_copied:{name}" for name in other_dbs]  # `redis-copy` reads db 0 only
    copy = [*base, "redis-copy", "--source-socket", str(source.redis_socket / "redis.sock"), "--target-socket",
            str(handle.redis_socket / "redis.sock")]
    for namespace in prefixes:
        copy += ["--namespace", namespace]
    done = _run_step(spawn, copy, tool_env(work, shim=None), timeout, failures, "redis_copy")
    facts["redis_copy"] = {"exit": done.returncode, "stdout": _digest(done.stdout), "namespaces": len(prefixes)}
    dbs, redis_prefixes, redis_failures = d0.redis_facts(handle.redis_socket / "redis.sock")
    equal = dbs == facts0["redis_dbs"] and redis_prefixes == facts0["redis_prefixes"] and not redis_failures
    facts["redis"] = {"equals_d0": equal, "prefixes": len(redis_prefixes), "dbs": len(dbs)}
    if not equal:
        failures.append("r7a_redis_differs")
    log_rows = read_shim_log(log)
    counted = Counter(row["verdict"] for row in log_rows)
    facts["shim"] = {"declared_non_namespace": True, "forwarded": counted["forward"], "refused": counted["refuse"],
                     "programs": dict(sorted(Counter(r["reason"] for r in log_rows if r["verdict"] == "forward").items())),
                     "path_only_for": "pg_restore_db"}
    if counted["refuse"]:
        failures.append(f"r7a_shim_refused:{counted['refuse']}")
    facts["failures"] = sorted(failures)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    document = {"at": clock(), "status": "failed" if failures else "ok", "facts": facts}
    write_record(out / "r7.json", document, max_items=MAX_RECORD_ITEMS, mode=0o600)
    if failures:
        raise R7aFailed(document)
    return document


def _run_step(spawn: Callable, argv: list[str], env: dict, timeout: float, failures: list[str], name: str):
    try:
        done = spawn(argv, env, timeout)
    except (OSError, subprocess.SubprocessError) as error:
        failures.append(f"r7a_{name}_{type(error).__name__}")
        return subprocess.CompletedProcess(argv, 124, "", "")
    if done.returncode != 0:
        failures.append(f"r7a_{name}_exit:{done.returncode}")
    return done


def _read_receipt(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


# ---- the operator command (cwd compare/: python3 -m rehearsal.r7a ...) ----

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rehearsal.r7a")
    for flag in ("run8", "root", "release", "dump", "database", "d0", "out"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--archive-sha256")
    args = parser.parse_args(argv)
    from .r6 import attach

    try:
        run8 = check_run8(args.run8)
        copies = Copies(run8, Path(args.root))
        copies.copies[SOURCE_COPY] = attach(run8, Path(args.root), SOURCE_COPY)
        d0_record = json.loads(Path(args.d0).read_text(encoding="utf-8"))
        document = run_r7a(copies, release=args.release, dump=args.dump, database=args.database, d0_record=d0_record,
                           out=args.out, archive_sha256=args.archive_sha256)
    except R7aFailed as failed:
        print(json.dumps({"status": "failed", "failures": failed.failures[:20]}, sort_keys=True))
        return 1
    except (Refused, OSError, ValueError, FileExistsError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)[:200]}, sort_keys=True))
        return 2
    print(json.dumps({"status": document["status"], "release": document["facts"]["release"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["R7aFailed", "write_shim", "read_shim_log", "tool_env", "run_r7a", "main"]
