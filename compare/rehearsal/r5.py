"""The rehearsal R5 bounded write scenario runner (RH-5): F-1 steps 1-12 (stop before publish) run by the oracle A and the
candidate B over identical clones of one rehearsal copy, with the write-set diff and the recorder unit boundaries.

Layer: harness (never shipped). Standard library plus `psycopg` (host side); product code runs only in the side drivers
(`r5_drivers/a.py`, `b.py`), one subprocess per side. Rehearsal design "7. R5", critique #14, AMD-1 A/B.

CRITIQUE #14: the side drivers are HARNESS drivers (use cases built with fixture transports); the production composition
profile is NOT set. The record carries `profile`.

Identical stores: the copy's database is cloned per side with `CREATE DATABASE ... TEMPLATE` on the SAME server, so A's
writes never reach B and both start from byte-identical data (the clone is checked: equal catalog digest before the run).
The Fleet in the copy is paused; each side resumes it IN THE COPY through the product use case (declared, step 1).

Write set (per side) = the store export diff before vs after, `(bucket, key, op, masked body sha256)` with op in
insert/update/delete, plus the file diffs of the artifacts overlay upper dir and the copy's runtime dir
(`(relpath, op, sha256 of masked content)`). PASS = A and B write sets equal except the declared differences
(`r5-declarations.json`) AND equal recorder unit boundaries AND every step ok on both sides AND no spawn on either side.

Also recorded (a G1 fact, never a pass/fail): whether the copy holds an open S2R maintenance intent that D's hold would
act on. D's code is not in this tree, so the refusal itself is `evaluated: false`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import Refused
from .copies import catalog_sha256, pg_dsn
from .evidence import _utc_now, write_record
from .r3 import _mask_value, snapshot

HERE = Path(__file__).resolve().parent
DECLARATIONS = HERE / "r5-declarations.json"
DRIVERS = HERE / "r5_drivers"
SIDES = ("A", "B")
MAX_RECORD_ITEMS = 4096
# An intended difference is tied to an AMD-1 section, an S2R hunk, or (owner-ratified 2026-10-06, RH-5 ruling 1) the
# accepted rebuild slice design that introduced it (`DESIGN-s9-X §1.3`).
SECTION = re.compile(r"AMD-1 [A-D]|S2R [0-9a-f]{7,40}:[\w/.\-]+|DESIGN-s[0-9]+(?:-[A-Z])? §[0-9]+(?:\.[0-9]+)*")
KINDS = frozenset({"only_a", "only_b", "changed"})
ROOT_TOKEN = "<ROOT>"
# Process identity facts are maskable (compare/masks.json: "Pids and OS temporary names are not injected; they are maskable");
# no owner, generation, attempt, lease, status, authorization result, digest or ref is ever masked (r3.NEVER_MASKED).
DEFAULT_MASKS = {"pid": "rehearsal.r5.process_id", "host": "rehearsal.r5.host_name"}


class R5Failed(Refused):
    """The record was written with `status: failed`; `document` is that record and `failures` its reasons."""

    def __init__(self, document: dict):
        self.document, self.failures = document, document["facts"]["failures"]
        super().__init__("r5_failed", "; ".join(self.failures[:8]))


@dataclass(frozen=True)
class SideSpec:
    """One revision's driver: `src` its package root, `script` its driver, `python` the interpreter (a venv with psycopg)."""
    name: str
    src: Path
    script: Path
    python: str = sys.executable


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---- declarations ----

def load_declarations(path: Path | str = DECLARATIONS) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("declarations_malformed", type(exc).__name__) from None
    return validate_declarations(document)


def validate_declarations(document: object) -> dict:
    if not isinstance(document, dict) or document.get("closed") is not True or not isinstance(document.get("declared"), list):
        raise Refused("declarations_malformed", "closed/declared")
    seen = set()
    for entry in document["declared"]:
        if not isinstance(entry, dict) or not str(entry.get("id", "")).strip() or entry["id"] in seen:
            raise Refused("declarations_malformed", "id")
        seen.add(entry["id"])
        if not SECTION.fullmatch(str(entry.get("section", ""))):
            raise Refused("declaration_uncited", f"{entry['id']}: section must cite an AMD-1 section or an S2R hunk")
        if not str(entry.get("reason", "")).strip():
            raise Refused("declarations_malformed", f"{entry['id']}: reason")
        if entry.get("kind") == "units":
            if (not str(entry.get("step", "")).strip() or entry.get("extra_in") not in SIDES
                    or not isinstance(entry.get("count"), int) or entry["count"] < 1):
                raise Refused("declarations_malformed", f"{entry['id']}: units step/extra_in/count")
            try:
                re.compile(str(entry.get("read_pattern", "")))
            except re.error:
                raise Refused("declarations_malformed", f"{entry['id']}: read_pattern") from None
            continue
        if entry.get("kind") not in ("store", "file"):
            raise Refused("declarations_malformed", f"{entry['id']}: kind")
        if not set(entry.get("differs", [])) or not set(entry["differs"]) <= KINDS:
            raise Refused("declarations_malformed", f"{entry['id']}: differs")
        try:
            re.compile(str(entry.get("key_pattern", "")))
        except re.error:
            raise Refused("declarations_malformed", f"{entry['id']}: key_pattern") from None
        if entry["kind"] == "store" and not str(entry.get("bucket", "")).strip():
            raise Refused("declarations_malformed", f"{entry['id']}: bucket")
    return document


# ---- the write set ----

def export_documents(dsn: str) -> dict[tuple[str, str], object]:
    """`{(bucket, key): body}` of the side's store (the generic `documents` table; read through a separate connection)."""
    import psycopg

    with psycopg.connect(dsn) as conn:
        return {(bucket, key): body for bucket, key, body in conn.execute("SELECT bucket, id, body FROM documents")}


def store_write_set(before: dict, after: dict, masks: dict[str, str] | None = None) -> list[list[str]]:
    """Sorted `[bucket, key, op, sha256 of the masked canonical body]` for every inserted, updated or deleted row."""
    masks = masks or {}
    out = []
    for (bucket, key), body in after.items():
        if (bucket, key) not in before:
            out.append([bucket, key, "insert", _sha(_canonical(_mask_value(body, masks)))])
        elif before[(bucket, key)] != body:
            out.append([bucket, key, "update", _sha(_canonical(_mask_value(body, masks)))])
    for (bucket, key) in before:
        if (bucket, key) not in after:
            out.append([bucket, key, "delete", ""])
    return sorted(out)


def before_differs(before: dict, bucket: str, key: str, body) -> bool:
    return before.get((bucket, key)) != body


def file_tree(root: Path, roots: tuple[str, ...] = ()) -> dict[str, str]:
    """`{relative path: sha256 of the content with each ROOT path rewritten to <ROOT>}` (symlinks recorded, not followed)."""
    tree: dict[str, str] = {}
    root = Path(root)
    if not root.exists():
        return tree
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            if path.is_symlink():
                tree[rel] = "symlink:" + _sha(os.readlink(path))
                continue
            text = path.read_bytes().decode("utf-8", "replace")
            for prefix in sorted((r for r in roots if r), key=len, reverse=True):
                text = text.replace(prefix, ROOT_TOKEN)
            tree[rel] = _sha(text)
    return tree


def file_write_set(before: dict[str, str], after: dict[str, str]) -> list[list[str]]:
    out = [[rel, "insert" if rel not in before else "update", sha] for rel, sha in after.items() if before.get(rel) != sha]
    out += [[rel, "delete", ""] for rel in before if rel not in after]
    return sorted(out)


def differences(a: list[list[str]], b: list[list[str]], width: int) -> list[dict]:
    """Rows that differ A vs B, keyed by their identity (`width` leading fields: bucket+key, or the relative path)."""
    index = lambda rows: {tuple(r[:width]): r for r in rows}  # noqa: E731
    ia, ib = index(a), index(b)
    out = []
    for identity in sorted(set(ia) | set(ib)):
        if identity not in ib:
            out.append({"identity": list(identity), "differs": "only_a", "a": ia[identity][width:], "b": None})
        elif identity not in ia:
            out.append({"identity": list(identity), "differs": "only_b", "a": None, "b": ib[identity][width:]})
        elif ia[identity] != ib[identity]:
            out.append({"identity": list(identity), "differs": "changed", "a": ia[identity][width:], "b": ib[identity][width:]})
    return out


def _explained_by_fields(entry: dict, identity: list[str], bodies: dict | None, masks: dict | None) -> bool:
    """A `changed` difference declared with `ignore_fields` holds only when the two bodies are EQUAL once those field names
    are masked: the declaration explains those fields, never a change to anything else in the row."""
    if not entry.get("ignore_fields"):
        return True
    if not bodies or tuple(identity) not in bodies["A"] or tuple(identity) not in bodies["B"]:
        return False
    mask = {**(masks or {}), **{f: "declared" for f in entry["ignore_fields"]}}
    return all(_canonical(_mask_value(bodies[n][tuple(identity)], mask)) == _canonical(_mask_value(bodies["A"][tuple(identity)], mask))
               for n in SIDES)


def undeclared(diffs: list[dict], declarations: dict, kind: str, bodies: dict | None = None, masks: dict | None = None) -> tuple[list[dict], list[str]]:
    """(the differences no declaration matches, the ids of the declarations that matched). `bodies` is `{side: {(bucket,
    key): body}}` for entries that declare `ignore_fields`."""
    left, used = [], set()
    for diff in diffs:
        identity = diff["identity"]
        bucket, key = (identity[0], identity[1]) if kind == "store" else (None, identity[0])
        for entry in declarations["declared"]:
            if (entry["kind"] == kind and diff["differs"] in entry["differs"]
                    and (kind == "file" or entry["bucket"] == bucket) and re.fullmatch(entry.get("key_pattern", ".*"), key)
                    and _explained_by_fields(entry, identity, bodies, masks)):
                used.add(entry["id"])
                break
        else:
            left.append(diff)
    return left, sorted(used)


# ---- unit boundaries ----

def signatures(step: dict) -> list[tuple]:
    """One step's units in order, ALL of them (read-only included): `(outcome, depth, sorted writes)`; labels and ordinal
    ids carry no information (design 7. R5: equal recorder unit boundaries)."""
    return [(u["outcome"], u["depth"], ",".join(sorted("/".join(w) for w in u["writes"]))) for u in step.get("units", [])]


def boundaries(result: dict) -> list[list]:
    return [[name, *sig] for name, step in result["steps"].items() for sig in signatures(step)]


def unit_differences(ra: dict, rb: dict) -> list[dict]:
    """Per step whose unit sequences differ: which side has extra units and which (ordinal, reads, writes). Extra units are
    found by removing `count` units of the longer side until the sequences are equal; `aligned: false` when no removal does."""
    from itertools import combinations

    out = []
    for name in ra["steps"]:
        a, b = signatures(ra["steps"][name]), signatures(rb["steps"].get(name, {}))
        if a == b:
            continue
        side, longer, shorter = ("A", ra, b) if len(a) > len(b) else ("B", rb, a)
        units = longer["steps"][name]["units"]
        sigs = signatures(longer["steps"][name])
        row = {"step": name, "a_units": len(a), "b_units": len(b), "extra_in": side, "aligned": False, "extra": []}
        if len(sigs) > len(shorter):
            for drop in combinations(range(len(sigs)), len(sigs) - len(shorter)):
                if [g for i, g in enumerate(sigs) if i not in drop] == shorter:
                    row["aligned"], row["extra"] = True, [
                        {"ordinal": i, "outcome": units[i]["outcome"], "writes": len(units[i]["writes"]),
                         "reads": units[i].get("reads", [])[:12]} for i in drop]
                    break
        out.append(row)
    return out


def undeclared_units(diffs: list[dict], declarations: dict) -> tuple[list[dict], list[str]]:
    left, used = [], set()
    for diff in diffs:
        for entry in declarations["declared"]:
            if (entry["kind"] == "units" and entry["step"] == diff["step"] and entry["extra_in"] == diff["extra_in"]
                    and diff["aligned"] and entry["count"] == len(diff["extra"])
                    and all(e["writes"] == 0 and e["outcome"] == "COMMIT"
                            and re.search(entry["read_pattern"], ",".join(e["reads"])) for e in diff["extra"])):
                used.add(entry["id"])
                break
        else:
            left.append(diff)
    return left, sorted(used)


def readonly_units(result: dict) -> dict[str, int]:
    return {name: sum(1 for u in step.get("units", []) if not u["writes"] and u["outcome"] == "COMMIT")
            for name, step in result["steps"].items()}


# ---- the S2R hold fact ----

def _has_field(value, names: set[str], found: set[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k in names:
                found.add(k)
            _has_field(v, names, found)
    elif isinstance(value, list):
        for v in value:
            _has_field(v, names, found)


def mask_reach(rows: list[list[str]], bodies: dict, masks: dict[str, str]) -> dict[str, dict[str, int]]:
    """For each masked field name, the buckets of the WRITTEN rows whose body carries that field and how many rows: the reach
    of a field-name mask, so a reviewer can see what it could have hidden."""
    reach: dict[str, dict[str, int]] = {name: {} for name in masks}
    for bucket, key, op, _ in rows:
        found: set[str] = set()
        _has_field(bodies.get((bucket, key)), set(masks), found)
        for name in found:
            reach[name][bucket] = reach[name].get(bucket, 0) + 1
    return reach


# F-1 rows this scenario does not exercise (owner ruling 3): reason and the rehearsal row that covers each.
NOT_EXERCISED = {
    "row 2 lane launcher (fleet_runtime: builds the lane env/schema and `operate run` argv)": {
        "reason": "launching a lane starts a child process (guarded launch); R5 runs with no process spawn",
        "covered_by": "uncovered (argv byte-identity is a compare golden, not an R-row)"},
    "row 4 operate-run argv (adapters/operation_cli)": {
        "reason": "the CLI wiring builds RedisBus/CallBudget/Executor for a real lane and spawns it; R5 builds the use cases in-process",
        "covered_by": "R3 (read-only parser inventory of `zeus operate` nodes); the write path is uncovered"},
    "row 11 owner-action delivery registration (OwnerActionScheduler)": {
        "reason": "discovery runs the live scheduler over host/delivery state and launches guarded children; no fixture-transport form",
        "covered_by": "uncovered"},
    "rows 13-15 publish, CI, merge, switch, consume": {
        "reason": "R5 stops before publish by design", "covered_by": "R7b (HostDelivery rollback stage) and C"},
}


def s2r_hold_fact(documents: dict) -> dict:
    """G1 fact (not a pass/fail): rows of the copy that look like an open S2R maintenance intent (a body carrying
    `generations`). D's own hold predicate is deployed code this tree does not hold, so `evaluated` is false."""
    rows = sorted([bucket, key] for (bucket, key), body in documents.items()
                  if isinstance(body, dict) and "generations" in body and "maintenance" in _canonical(body).lower())
    return {"evaluated": False, "reason": "D's deployed S2R hold code is not in this tree; recorded from the copy's data only",
            "maintenance_intent_rows": len(rows), "buckets": sorted({r[0] for r in rows}),
            "would_refuse": "unknown" if rows else "no_open_intent_in_copy"}


# ---- running a side ----

def side_env() -> dict[str, str]:
    """The closed child env: no `ZEUS_COMPOSITION_PROFILE` (critique #14), no credentials, no network settings."""
    return {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}


def subprocess_runner(argv: list[str], timeout: float):
    done = subprocess.run(argv, capture_output=True, timeout=timeout, env=side_env(), stdin=subprocess.DEVNULL, check=False)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def clone_database(socket: Path, source: str, target: str) -> None:
    """`CREATE DATABASE <target> TEMPLATE <source>` on the copy's own server (the source must have no open connection)."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(pg_dsn(socket), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target)))
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(target), sql.Identifier(source)))


def drop_database(socket: Path, name: str) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(pg_dsn(socket), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def run_r5(sides: dict[str, SideSpec], copy, database: str, work: Path, out, *, run8: str, declarations: dict | None = None,
           masks: dict[str, str] | None = DEFAULT_MASKS, runtime_dir: Path | None = None, timeout: float = 300.0,
           runner: Callable = subprocess_runner, extra: dict[str, list[str]] | None = None, clock=_utc_now,
           faults: dict[str, str] | None = None, shared: Path | None = None, inject: dict[str, str] | None = None,
           inject_readonly: tuple[str, ...] = ()) -> dict:
    """Run the scenario on A and B over clones of `copy`'s `database`; write `out/r5.json`; raise `R5Failed` after writing
    on any failure. `extra` adds per-side driver argv (tests), `faults`/`inject` are the TEST-ONLY driver flags."""
    declarations = declarations if declarations is not None else load_declarations()
    work = Path(work)
    # Stable across runs: the composed context embeds these paths and the store records its digest, so run-to-run
    # determinism needs the same path every time (a per-run work dir would differ).
    shared = Path(shared) if shared is not None else work.parent / f"r5-shared-{run8}"
    failures: list[str] = []
    baseline = snapshot(copy, database)
    clones = {name: f"{database}_r5{name.lower()}" for name in SIDES}
    facts: dict = {"database": database, "run8": run8, "nonce": "rh-" + run8,
                   "profile": "harness-fixture: ZEUS_COMPOSITION_PROFILE is not set (critique #14); R3/R6 keep production",
                   "fleet_resume": "each side resumes the Fleet IN THE COPY through the product use case (step 1)",
                   "catalog_sha256_d0": baseline["catalog_sha256"]}
    runs: dict[str, dict] = {}
    try:
        for name in SIDES:
            clone_database(copy.pg_socket, database, clones[name])
        clone_digests = {n: catalog_sha256(copy.pg_socket, clones[n]) for n in SIDES}
        facts["clone_catalog_sha256"] = clone_digests
        if clone_digests["A"] != clone_digests["B"]:
            failures.append("clones_differ")
        s2r = None
        for name in SIDES:
            spec, dsn = sides[name], pg_dsn(copy.pg_socket, clones[name])
            side_dir = work / name.lower()
            # One scratch path for both sides, emptied between them: the composed context embeds the workspace path, so a
            # per-side path would put a path difference into every context digest the store records.
            # The same holds for the artifacts dir (the context's artifact-reader argv embeds it): it is shared, emptied before
            # each side and moved to `<side>/artifacts-after` once its write set is read.
            artifacts, scratch, runtime = shared / "artifacts", shared / "scratch", side_dir / "runtime"
            for directory in (artifacts, scratch):
                shutil.rmtree(directory, ignore_errors=True)
                directory.mkdir(parents=True, exist_ok=True)
            if runtime_dir is not None and not runtime.exists():
                shutil.copytree(runtime_dir, runtime, symlinks=True)
            roots = (str(side_dir) + "/", str(shared), str(work))  # `<work>/a/` first: a bare `<work>/a` would also eat `<work>/artifacts`
            side_dir.mkdir(parents=True, exist_ok=True)
            doc_before, art_before, rt_before = export_documents(dsn), file_tree(artifacts, roots), file_tree(runtime, roots)
            if s2r is None:
                s2r = s2r_hold_fact(doc_before)
            result_path = side_dir / "result.json"
            argv = [spec.python, "-I", str(spec.script), "--dsn", dsn, "--run8", run8, "--src", str(spec.src), "--scratch",
                    str(scratch), "--artifacts", str(artifacts), "--out", str(result_path), *(extra or {}).get(name, [])]
            if faults and name in faults:
                argv += ["--fault", faults[name]]
            if name in inject_readonly:
                argv += ["--inject-readonly"]
            if inject and name in inject:
                argv += ["--inject-extra", inject[name]]
            code, stdout, stderr = runner(argv, timeout)
            run: dict = {"exit": code}
            if result_path.exists():
                run["result"] = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                failures.append(f"driver_no_result:{name}:exit {code}:{(stderr.strip().splitlines() or [''])[-1][:120]}")
            doc_after, art_after, rt_after = export_documents(dsn), file_tree(artifacts, roots), file_tree(runtime, roots)
            shutil.move(str(artifacts), str(side_dir / "artifacts-after"))
            # Raw bodies stay under the run's work dir (never in the evidence record), for tracing a difference.
            (side_dir / "store-write-bodies.json").write_text(json.dumps(
                {f"{b}/{k}": body for (b, k), body in doc_after.items() if before_differs(doc_before, b, k, body)},
                sort_keys=True, indent=1, default=str), encoding="utf-8")
            run |= {"store": store_write_set(doc_before, doc_after, masks), "artifacts": file_write_set(art_before, art_after),
                    "runtime": file_write_set(rt_before, rt_after)}
            run["bodies"] = doc_after
            runs[name] = run
        facts["s2r_hold"] = s2r
        _judge(runs, sides, declarations, facts, failures, masks)
        after = snapshot(copy, database)
        drift = [k for k in ("catalog_sha256", "redis_dbs", "redis_prefixes") if after[k] != baseline[k]]
        facts["d1_equals_d0"] = not drift
        if drift:
            failures.append("copy_changed:" + "+".join(drift))
    finally:
        for name in SIDES:
            drop_database(copy.pg_socket, clones[name])
    facts["failures"] = sorted(failures)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    document = {"at": clock(), "status": "failed" if failures else "ok", "facts": facts}
    write_record(out / "r5.json", document, max_items=MAX_RECORD_ITEMS)
    if failures:
        raise R5Failed(document)
    return document


def _judge(runs: dict, sides: dict, declarations: dict, facts: dict, failures: list[str], facts_masks: dict | None = None) -> None:
    masks_arg = facts_masks
    results = {n: r.get("result") for n, r in runs.items()}
    for name, result in results.items():
        if result is None:
            continue
        if not Path(result["origin"]["package"]).resolve().is_relative_to(Path(sides[name].src).resolve()):
            failures.append(f"origin:{name}")
        if result.get("production_profile_set"):
            failures.append(f"production_profile_set:{name}")
        if result["spawn_events"]:
            failures.append(f"spawn:{name}:{len(result['spawn_events'])}")
        if result["recorder_violations"]:
            failures.append(f"recorder_violation:{name}:{[v['kind'] for v in result['recorder_violations']]}")
        bad = {s: v.get("error") for s, v in result["steps"].items() if not v["ok"]}
        if bad or len(result["completed"]) != len(result["steps"]) or runs[name]["exit"] != 0:
            failures.append(f"steps:{name}:{bad or 'exit ' + str(runs[name]['exit'])}")
        facts[f"steps_completed_{name}"] = result["completed"]
        facts[f"provider_calls_{name}"] = result.get("provider_calls")
    facts["write_set_sizes"] = {n: {"store": len(r["store"]), "artifacts": len(r["artifacts"]), "runtime": len(r["runtime"])}
                                for n, r in runs.items()}
    facts["mask_reach"] = {n: mask_reach(r["store"], r["bodies"], DEFAULT_MASKS if masks_arg is None else masks_arg)
                           for n, r in runs.items()}
    facts["not_exercised"] = NOT_EXERCISED
    facts["write_set_sha256"] = {n: _sha(_canonical([r["store"], r["artifacts"], r["runtime"]])) for n, r in runs.items()}
    facts["buckets_written"] = {n: sorted({row[0] for row in r["store"]}) for n, r in runs.items()}
    for kind, key, width in (("store", "store", 2), ("file", "artifacts", 1), ("file", "runtime", 1)):
        diffs = differences(runs["A"][key], runs["B"][key], width)
        left, used = undeclared(diffs, declarations, kind, {n: runs[n]["bodies"] for n in SIDES} if kind == "store" else None,
                                masks=facts_masks)
        facts[f"{key}_differences"] = len(diffs)
        facts[f"{key}_declared_used"] = used
        facts[f"{key}_undeclared"] = [{"identity": d["identity"], "differs": d["differs"], "a": d["a"], "b": d["b"]}
                                     for d in left[:32]]
        failures += [f"{key}_undeclared:{'/'.join(d['identity'])}:{d['differs']}" for d in left]
    if all(results.values()):
        ba, bb = boundaries(results["A"]), boundaries(results["B"])
        facts["readonly_units"] = {n: readonly_units(results[n]) for n in SIDES}
        facts["units"] = {"A": len(ba), "B": len(bb)}
        diffs = unit_differences(results["A"], results["B"])
        left, used = undeclared_units(diffs, declarations)
        facts["unit_differences"] = [  # flattened: the evidence writer bounds nesting depth
            {"step": d["step"], "extra_in": d["extra_in"], "a_units": d["a_units"], "b_units": d["b_units"], "aligned": d["aligned"],
             "extra": [f"ordinal {e['ordinal']} {e['outcome']} writes={e['writes']} reads=" + ",".join(e["reads"])[:300]
                       for e in d["extra"]]} for d in diffs[:16]]
        facts["units_declared_used"] = used
        facts["unit_boundaries_equal"] = ba == bb  # raw; the verdict is `unit_boundaries_pass` (declared extras removed)
        facts["unit_boundaries_pass"] = not left
        failures += [f"units_undeclared:{d['step']}:{d['extra_in']}+{len(d['extra']) or d['a_units'] - d['b_units']}" for d in left]
