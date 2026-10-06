"""The rehearsal R6 rollback-read runner (RH-6a): each R0 release's own read-only leaves and its R4 column sweep over
copy B after R5 and over copy D at D0.

Layer: harness (never shipped). Standard library plus the tooling modules (`r3` leaf catalog/runners/`snapshot`, `r4`
sweep, `evidence`). Rehearsal design "8. R6", AMD-1 errata E6 (D_rev = the releases of the complete post-G1-10A R0) and AC9.

D_rev (`d_revs`): every `stable.releases` entry of the R0 record plus every managed payload directory it records
(`stable.managed_payload.releases`), one per catalog column (the first 8 hex digits of the revision). Nothing is hard-coded:
- a release directory (`.venv` shape) runs through its own `<dir>/.venv/bin/python` with `<dir>/src`. The recorded
  `interpreter_realpath` is the RESOLVED interpreter (a venv's symlink target: the base interpreter without the venv's
  site-packages), so it is carried as evidence, never executed;
- the managed payload's `runtime_dir` shape runs through its `payload_executable` (RH-7: the `entry` child's interpreter,
  as `<release>/.venv/bin/python` when the child belongs to a release, else its recorded realpath) with `<dir>/src`.
A shape that names no interpreter, or a duplicate column, is a failure (`r6_rev_unresolved`, `r6_rev_duplicate`): never a skip.

Per revision and per copy: (1) an origin probe (`codex_harness` must resolve under the revision's `src`); (2) every
read-only leaf of the R3 catalog that lists the revision (`r3.bind_argv`: a missing parameter is a failure, never a skip),
D1 == D0 checked after each; (3) the R4 sweep through that revision's catalog column. A revision whose column is missing
from the R3 or R4 catalog is the failure `r6_column_missing:<rev>`.

Failures are 5-field strings like R4's, `(schema, bucket, id, class, code)`; a failing leaf is `(leaf, <command>, *, LeafExit |
LeafTimeout, exit_<n> | timeout)`. A bucket the catalog declares beyond OWNED_BUCKETS (`amd1`: the FA permit bucket) has no
reader on a release that predates it; that `NoReader` is dropped on BOTH copies and counted (`ignored_unknown_buckets`).

PASS per revision = failures(rev | B) is a subset of failures(rev | D at D0), no run-level error, and D1 == D0 on D.
A B-only failure is named `<rev>:B_only:(...)`. Copy B must not change either (`not_read_only`). The M7 rollback-read over B
(`parity`) is recorded as extra parity only and never affects the verdict.

`FA_PERMIT_FIXTURE` / `seed_fa_permits`: the declared fixture of AMD-1 B (FA-IMPL's writer does not exist yet): one issued and
one consumed `fleet_admission_permits` row for the R6 fixture copy, so the readers of other revisions are proven to ignore it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import Refused, check_run8, d0, r3, r4
from .copies import Copy, fixture_name, pg_dsn
from .evidence import _utc_now, write_record

MAX_RECORD_ITEMS = 4096
SHA40 = re.compile(r"[0-9a-f]{40}")
COPY_ORDER = ("D", "B")  # D at D0 first: B is read only after the clean baseline
CHANGED = ("catalog_sha256", "redis_dbs", "redis_prefixes")
ORIGIN_PROBE = "import importlib.util as u;s=u.find_spec('codex_harness');print(s.origin if s else '')"
BUCKETS_SQL = "SELECT DISTINCT bucket FROM {}.documents ORDER BY 1"
SCHEMAS_SQL = ("SELECT table_schema FROM information_schema.tables WHERE table_name = 'documents' "
               "AND table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1")
# The declared AMD-1 B fixture (`urn:zeus:fleet-admission-permit:1`, FA-SPEC section 2): not FA-IMPL's writer.
FA_BUCKET = "fleet_admission_permits"
FA_PERMIT_FIXTURE = (
    ("rh-fixture-permit-issued", {"schema": "urn:zeus:fleet-admission-permit:1", "kind": "delivery_canary",
                                  "state": "granted", "fixture": "declared (AMD-1 B)"}),
    ("rh-fixture-permit-consumed", {"schema": "urn:zeus:fleet-admission-permit:1", "kind": "delivery_canary",
                                    "state": "closed", "outcome": "settled", "fixture": "declared (AMD-1 B)"}))


class R6Failed(Refused):
    """The record was written with `status: failed`; `document` is that record and `failures` its reasons."""

    def __init__(self, document: dict):
        self.document, self.failures = document, document["facts"]["failures"]
        super().__init__("r6_failed", "; ".join(self.failures[:8]))


@dataclass(frozen=True)
class Rev:
    """One D_rev: `column` its catalog column, `dir` its release/payload directory, `python` the interpreter that runs it,
    `src` its package root, `shape` `release` | `runtime_dir`."""
    column: str
    dir: str
    python: str
    src: str
    shape: str
    interpreter_realpath: str | None = None


def rev_commands(rev: Rev) -> dict:
    """The command prefixes of one revision's own interpreter (`zeus`, `zeus-monitor`, plain `python`)."""
    return {"zeus": [rev.python, "-m", "codex_harness.cli"], "monitor": [rev.python, "-m", "codex_harness.monitor"],
            "python": [rev.python]}


# ---- D_rev from the R0 record ----

def _column(location: str, facts: dict) -> str | None:
    base = Path(location).name
    if SHA40.fullmatch(base):
        return base[:8]
    runtime = facts.get("runtime")
    revision = runtime.get("revision") if isinstance(runtime, dict) else None
    return revision[:8] if isinstance(revision, str) and SHA40.fullmatch(revision) else None


def _interpreter(location: str, facts: dict) -> tuple[str, str, str | None] | str:
    """`(python, shape, recorded realpath)` or the reason this directory names no interpreter."""
    shape = facts.get("shape")
    if shape == "runtime_dir":
        exe = facts.get("payload_executable")
        if not isinstance(exe, dict) or not str(exe.get("realpath", "")).startswith("/"):
            return "payload_executable"
        release = exe.get("release")
        python = f"{release}/.venv/bin/python" if isinstance(release, str) and release.startswith("/") else exe["realpath"]
        return python, "runtime_dir", exe["realpath"]
    if shape is not None:
        return f"shape:{shape}"
    real = facts.get("interpreter_realpath")
    if not isinstance(real, str) or not real.startswith("/"):
        return "interpreter_realpath"
    return f"{location}/.venv/bin/python", "release", real


def d_revs(r0: dict) -> tuple[list[Rev], list[str]]:
    """`(revisions, failures)` of an R0 record: the failures name every directory that could not become a revision."""
    stable = r0.get("stable") if isinstance(r0, dict) else None
    if not isinstance(stable, dict) or not isinstance(stable.get("releases"), dict):
        raise Refused("r0_malformed", "stable.releases")
    payload = (stable.get("managed_payload") or {}).get("releases") or {}
    revs: list[Rev] = []
    failures: list[str] = []
    seen_dirs: set[str] = set()
    for location, facts in [*sorted(stable["releases"].items()), *sorted(payload.items())]:
        if location in seen_dirs:
            continue  # the same directory is one revision (a payload that is also a release)
        seen_dirs.add(location)
        column = _column(location, facts if isinstance(facts, dict) else {})
        if column is None or not isinstance(facts, dict):
            failures.append(f"r6_rev_unresolved:{location}:revision")
            continue
        picked = _interpreter(location, facts)
        if isinstance(picked, str):
            failures.append(f"r6_rev_unresolved:{location}:{picked}")
            continue
        python, shape, real = picked
        if any(r.column == column for r in revs):
            failures.append(f"r6_rev_duplicate:{column}")
            continue
        revs.append(Rev(column, location, python, f"{location}/src", shape, real))
    return revs, failures


def namespace_side_factory(specs: dict) -> Callable:
    """`side_for(rev, copy_name)` for the real run: each copy's own namespace spec, the revision's own interpreter."""
    def side_for(rev: Rev, copy_name: str) -> r3.Side:
        return r3.Side(rev.column, specs[copy_name], rev_commands(rev))
    return side_for


# ---- the declared FA permit fixture ----

def seed_fa_permits(copy: Copy, database: str, schema: str) -> list[str]:
    """Insert the declared AMD-1 B fixture rows (one issued, one consumed) into `<schema>.documents` of `copy`."""
    import psycopg

    from .copies import IDENT

    if not IDENT.match(schema):
        raise Refused("bad_schema_name", schema)
    with psycopg.connect(pg_dsn(copy.pg_socket, database), autocommit=True) as conn:
        for ident, body in FA_PERMIT_FIXTURE:
            conn.execute(f'INSERT INTO "{schema}".documents (bucket, id, body) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                         (FA_BUCKET, ident, json.dumps(body)))
    return [ident for ident, _ in FA_PERMIT_FIXTURE]


# ---- one revision over one copy ----

def copy_facts(copy: Copy, database: str) -> dict:
    """The buckets and Redis prefixes the copy holds NOW, in the shape `r4.coverage`/`sweep_side` read (names only)."""
    import psycopg
    from psycopg import sql

    buckets: dict[str, dict] = {}
    with psycopg.connect(pg_dsn(copy.pg_socket, database), connect_timeout=5) as conn:
        for (schema,) in conn.execute(SCHEMAS_SQL).fetchall():
            names = conn.execute(sql.SQL(BUCKETS_SQL).format(sql.Identifier(schema))).fetchall()
            buckets[schema] = {name: {} for (name,) in names}
    _, prefixes, _ = d0.redis_facts(Path(copy.redis_socket) / "redis.sock")
    return {"buckets": buckets, "redis_prefixes": prefixes}


def _fmt(item) -> str:
    return "(" + ", ".join(item) + ")"


def _drift(after: dict, expected: dict) -> list[str]:
    return [key for key in CHANGED if after[key] != expected[key]]


def run_rev_on_copy(rev: Rev, copy_name: str, copy: Copy, database: str, side: r3.Side, leaf_catalog: dict,
                    reader_catalog: dict, expected: dict, *, params: dict, runner: Callable, snap: Callable,
                    timeout: float, leaf_timeout: float, repository: str | None) -> dict:
    """Run revision `rev` over `copy`: origin probe, its read-only leaves, its R4 sweep. `expected` is the copy's state
    that every step must leave unchanged (D0 for D). Returns `{failures, errors, leaves, drift, ignored, rows_read}`."""
    out = {"failures": set(), "errors": [], "leaves": 0, "drift": False, "ignored": {}, "rows_read": 0}
    tag = f"{rev.column}:{copy_name}"
    state = [expected]

    def check_state(label: str) -> None:
        after = snap(copy, database)
        changed = _drift(after, state[0])
        if changed:
            out["errors"].append(f"not_read_only:{tag}:{label}:{'+'.join(changed)}")
            out["drift"] = True
            state[0] = after  # one writer is blamed once, not for every later step

    probe = runner(side, [*side.commands["python"], "-c", ORIGIN_PROBE], leaf_timeout)
    origin = probe.stdout.strip().splitlines()[-1:] or [""]
    if probe.timed_out or probe.returncode != 0 or not Path(origin[0]).resolve().is_relative_to(Path(rev.src).resolve()):
        out["errors"].append(f"origin_refused:{tag}")
        return out
    for command, entry in sorted(leaf_catalog["nodes"].items()):
        if entry["class"] != "read_only" or rev.column not in entry["revisions"]:
            continue
        out["leaves"] += 1
        program = entry.get("program", "zeus")
        try:
            argv = r3.bind_argv(entry, params)
        except Refused as exc:
            out["errors"].append(f"{command}:{tag}:{exc.code}:{exc.detail}")
            continue
        if repository is not None and program == "zeus":
            argv = ["--repository", repository, *argv]
        result = runner(side, [*side.commands[program], *argv], leaf_timeout)
        if result.timed_out:
            out["failures"].add(_fmt(["leaf", command, "*", "LeafTimeout", "timeout"]))
        elif result.returncode != 0:
            out["failures"].add(_fmt(["leaf", command, "*", "LeafExit", f"exit_{result.returncode}"]))
        check_state(command)
    facts = copy_facts(copy, database)
    covered = r4.coverage(reader_catalog, facts)
    if covered["missing"]:
        out["errors"] += [f"{m}:{tag}" for m in covered["missing"]]
        return out
    swept = r4.sweep_side(r4.R4Side(rev.column, side, rev.src), reader_catalog, facts, pg_dsn(copy.pg_socket, database),
                          str(Path(copy.redis_socket) / "redis.sock"), runner=runner, timeout=timeout)
    out["errors"] += swept["errors"]
    out["rows_read"] = sum(swept["counts"].values())
    unknown = {b for b, row in reader_catalog["buckets"].items() if "amd1" in row}
    for item in swept["failures"]:
        if item[3] == "NoReader" and item[1] in unknown:
            out["ignored"][item[1]] = out["ignored"].get(item[1], 0) + 1  # the release predates the bucket
        else:
            out["failures"].add(_fmt(item))
    check_state("sweep")
    return out


# ---- the runner ----

def run_r6(revs: list[Rev], copies: dict[str, Copy], database: str, leaf_catalog: dict, reader_catalog: dict,
           d0_record: dict, out, *, side_for: Callable, params: dict | None = None, r0_failures=(), runner: Callable =
           r3.namespace_runner, snap: Callable = r3.snapshot, timeout: float = 600.0, leaf_timeout: float = 60.0,
           repository: str | None = None, parity: tuple | None = None, clock=_utc_now) -> dict:
    """Run every revision over copy D (at D0) then copy B (after R5); write `out/r6.json`; raise `R6Failed` (after writing)
    on any failure. `copies` holds `B` and `D`; `side_for(rev, copy_name)` is the revision's `r3.Side` on that copy;
    `r0_failures` are the `d_revs` failures. `parity = (rev, side)` runs the M7 rollback-read (`r4.R4Side` of the A column)
    over B as extra parity only."""
    r3.validate_catalog(leaf_catalog)
    r4.validate_catalog(reader_catalog)
    params = dict(params or {})
    facts0 = d0_record["facts"]
    failures: list[str] = list(r0_failures)
    expected = {"D": {k: facts0[k] for k in CHANGED}, "B": snap(copies["B"], database)}
    start_d = snap(copies["D"], database)
    if _drift(start_d, expected["D"]):
        failures.append(f"d_not_at_d0:{'+'.join(_drift(start_d, expected['D']))}")
    revisions: dict[str, dict] = {}
    for rev in revs:
        row = {"dir": rev.dir, "shape": rev.shape, "interpreter_realpath": rev.interpreter_realpath}
        missing = [name for name, found in (("r3", rev.column in leaf_catalog.get("revisions", {})),
                                            ("r4", rev.column in reader_catalog["trees"].get("D", {}))) if not found]
        if missing:
            failures.append(f"r6_column_missing:{rev.column}:{'+'.join(missing)}")
            revisions[rev.column] = {**row, "verdict": "fail", "reasons": [f"r6_column_missing:{'+'.join(missing)}"]}
            continue
        ran = {name: run_rev_on_copy(rev, name, copies[name], database, side_for(rev, name), leaf_catalog,
                                     reader_catalog, expected[name], params=params, runner=runner, snap=snap,
                                     timeout=timeout, leaf_timeout=leaf_timeout, repository=repository)
               for name in COPY_ORDER}
        if ran["B"]["drift"]:
            expected["B"] = snap(copies["B"], database)  # a writer is blamed once, not for every later revision
        reasons = [f"{rev.column}:{e}" for name in COPY_ORDER for e in ran[name]["errors"]]
        b_only = sorted(ran["B"]["failures"] - ran["D"]["failures"])
        reasons += [f"{rev.column}:B_only:{item}" for item in b_only]
        failures += reasons
        revisions[rev.column] = {
            **row, "leaves": ran["D"]["leaves"], "failures_d0": len(ran["D"]["failures"]),
            "failures_b": len(ran["B"]["failures"]), "common": len(ran["B"]["failures"] & ran["D"]["failures"]),
            "b_only": b_only[:40], "d_equals_d0": not ran["D"]["drift"], "b_unchanged": not ran["B"]["drift"],
            "ignored_unknown_buckets": {f"{n}|{b}": c for n in COPY_ORDER for b, c in sorted(ran[n]["ignored"].items())},
            "rows_read": {n: ran[n]["rows_read"] for n in COPY_ORDER}, "verdict": "fail" if reasons else "pass",
            "reasons": reasons[:40]}
    parity_facts = None
    if parity is not None:
        rev, side = parity
        ran = run_rev_on_copy(rev, "B", copies["B"], database, side, {"nodes": {}}, reader_catalog,
                              snap(copies["B"], database), params=params, runner=runner, snap=snap, timeout=timeout,
                              leaf_timeout=leaf_timeout, repository=repository)
        parity_facts = {"column": rev.column, "failures": len(ran["failures"]), "rows_read": ran["rows_read"],
                        "errors": len(ran["errors"]), "counted_in_verdict": False}
    end_d = snap(copies["D"], database)
    d1_equals_d0 = not _drift(end_d, expected["D"])
    if not d1_equals_d0 and not any(r.get("d_equals_d0") is False for r in revisions.values()):
        failures.append(f"d1_not_d0:{'+'.join(_drift(end_d, expected['D']))}")
    facts = {"database": database, "revisions_run": sorted(revisions), "d1_equals_d0": d1_equals_d0,
             "catalog_sha256_d0": facts0["catalog_sha256"], "catalog_sha256_d1": end_d["catalog_sha256"],
             "results": revisions, "parity": parity_facts, "r0_failures": list(r0_failures),
             "failures": sorted(failures)}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    document = {"at": clock(), "status": "failed" if failures else "ok", "facts": facts}
    write_record(out / "r6.json", document, max_items=MAX_RECORD_ITEMS, mode=0o600)
    if failures:
        raise R6Failed(document)
    return document


# ---- the operator command (cwd compare/: python3 -m rehearsal.r6 ...) ----

def attach(run8: str, root: Path, name: str) -> Copy:
    """The handle of an already started copy (its names and socket directories are fixed by `copies.Copies.start`)."""
    base = Path(root) / name
    for directory in ("pgsock", "redsock"):
        if not (base / directory).is_dir():
            raise Refused("copy_not_started", f"{name}/{directory}")
    return Copy(name, fixture_name(run8, name, "pg"), fixture_name(run8, name, "redis"), base / "pgsock", base / "redsock")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rehearsal.r6")
    for flag in ("run8", "root", "r0", "d0", "spec-b", "spec-d", "out", "database"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--params", help="JSON object: the leaf catalog's placeholder values")
    parser.add_argument("--repository")
    args = parser.parse_args(argv)
    from . import namespace

    try:
        run8 = check_run8(args.run8)
        r0 = json.loads(Path(args.r0).read_text(encoding="utf-8"))
        d0_record = json.loads(Path(args.d0).read_text(encoding="utf-8"))
        params = json.loads(Path(args.params).read_text(encoding="utf-8")) if args.params else {}
        revs, bad = d_revs(r0)
        copies = {name: attach(run8, Path(args.root), name) for name in COPY_ORDER}
        specs = {"B": namespace.load_spec(args.spec_b), "D": namespace.load_spec(args.spec_d)}
        document = run_r6(revs, copies, args.database, r3.load_catalog(), r4.load_catalog(), d0_record, args.out,
                          side_for=namespace_side_factory(specs), params=params, r0_failures=bad,
                          repository=args.repository)
    except R6Failed as failed:
        print(json.dumps({"status": "failed", "failures": failed.failures[:20]}, sort_keys=True))
        return 1
    except (Refused, OSError, ValueError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)[:200]}, sort_keys=True))
        return 2
    print(json.dumps({"status": document["status"], "revisions": document["facts"]["revisions_run"]}, sort_keys=True))
    return 0


__all__ = ["R6Failed", "Rev", "rev_commands", "d_revs", "namespace_side_factory", "seed_fa_permits", "FA_PERMIT_FIXTURE",
           "copy_facts", "run_rev_on_copy", "run_r6", "attach", "main"]


if __name__ == "__main__":
    sys.exit(main())

