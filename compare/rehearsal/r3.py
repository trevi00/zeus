"""The rehearsal R3 read-only parity runner (RH-4a): per-revision parser inventory, the cited leaf catalog, the closed
`rehearsal.r3.*` mask proposal and the A-vs-B runner with "D1 == D0 after every leaf".

Layer: harness (never shipped). Standard library plus the tooling modules; the host-side digests reuse part a/d0
(`copies.catalog_sha256`, `d0.redis_facts`). Rehearsal design "5. R3" and critique #15 (`cutover-critique-rehearsal.json`).

Inventory (critique #15): `parser_inventory(src)` walks the `--help`-level argparse tree of the revision whose `src` it is
given, in a child process with a closed env and `COLUMNS=100`, using the same node rule as the `cli.parser` compare driver
(`compare/drivers/*/cli_parser.py`: command path, root flag, sha256/bytes of each node's `--help`). The child inserts
`<src>` at `sys.path[0]` and the walk is refused (`inventory_origin`) unless `codex_harness` was imported from under that
`src`: an editable install of another tree never stands in for the revision. No handler runs.

Catalog (`r3-leaves.json`): every parser node of every revision is `read_only` (code-trace citations on A and B,
`path:Class.method`), `excluded` (reason) or `disputed` (reason; the OWNER decides, never defaulted to read-only).
`coverage` fails closed in both directions: an inventoried node without an entry listing that revision is
`unclassified`, an entry listing a revision whose inventory lacks the node is `stale`.

Runner: each read-only leaf present on BOTH A and B runs on each side (the injected `runner`, by default
`namespace.run_in_namespace` with a timeout) against the same copy. After every run the copy's catalog digest and Redis
facts (value-sensitive: `redis_inventory` digests DUMP) are recomputed; a change fails the leaf as `not_read_only`.
PASS = equal exits and equal masked digests A vs B for every read-only leaf, no skipped parameter, no disputed node.
Read-only leaves present on one side only are LOGGED (`skipped_one_side`), never dropped silently.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import Refused, d0
from .copies import catalog_sha256
from .evidence import _utc_now, write_record

HERE = Path(__file__).resolve().parent
LEAVES = HERE / "r3-leaves.json"
MASKS = HERE / "r3-masks.json"
MAX_RECORD_ITEMS = 4096
CLASSES = frozenset({"read_only", "excluded", "disputed"})
SIDES = ("A", "B")
# `python`: a release module run as `<python> -m <module>` (its argv starts with `-m`), e.g. the host-migration CLI, which is not
# a `zeus` parser node.
PROGRAMS = ("zeus", "monitor", "python")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
MASK_ID = re.compile(r"rehearsal\.r3\.[a-z_]+")
# masks.json: "Owners, generations, attempts, leases, statuses, authorization results, digests and refs are never masked."
NEVER_MASKED = re.compile(r"owner|generation|attempt|lease|status|authoriz|digest|sha256|hash|ref", re.I)
ROOT_TOKEN = "<ROOT>"

WALKER = r'''
import argparse, contextlib, hashlib, io, json, sys
src, module = sys.argv[1], sys.argv[2]
sys.path.insert(0, src)
import importlib
cli = importlib.import_module(module)
import codex_harness
root = cli.parser()
nodes = []
def help_of(path):
    stream = io.StringIO()
    code = None
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
        try:
            root.parse_args([*path, "--help"])
        except SystemExit as exc:
            code = exc.code
    text = stream.getvalue()
    return {"help_exit": code, "help_sha256": hashlib.sha256(text.encode()).hexdigest(), "help_bytes": len(text.encode())}
def walk(parser, path):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                here = [*path, name]
                nodes.append({"command": " ".join(["zeus", *here]), "root": len(here) == 1, **help_of(here)})
                walk(child, here)
walk(root, [])
print(json.dumps({"origin": codex_harness.__file__, "nodes": nodes}))
'''


class R3Failed(Refused):
    """The record was written with `status: failed`; `document` is that record and `failures` its reasons."""

    def __init__(self, document: dict):
        self.document, self.failures = document, document["facts"]["failures"]
        super().__init__("r3_failed", "; ".join(self.failures[:8]))


# ---- per-revision parser inventory (critique #15) ----

def parser_inventory(src: Path | str, *, module: str = "codex_harness.cli", python: str | None = None,
                     timeout: float = 120.0) -> list[dict]:
    """The `--help`-level node list of the revision whose package root is `src` (`<rev>/src`); nothing is executed
    beyond argparse construction. Raises `Refused("inventory_origin")` when `codex_harness` came from elsewhere."""
    root = Path(src).resolve()
    env = {"PATH": "/usr/bin:/bin", "COLUMNS": "100", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([python or sys.executable, "-I", "-c", WALKER, str(root), module], capture_output=True,
                          timeout=timeout, env=env, cwd=str(root), check=False)
    if done.returncode != 0:
        raise Refused("inventory_failed", done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:][0][:200]
                      if done.stderr.strip() else f"exit {done.returncode}")
    report = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
    if not Path(report["origin"]).resolve().is_relative_to(root):
        raise Refused("inventory_origin", "codex_harness was imported from outside the revision's src")
    return report["nodes"]


def commands(inventory: list[dict]) -> list[str]:
    return [node["command"] for node in inventory]


# ---- the catalog ----

def load_catalog(path: Path | str = LEAVES) -> dict:
    """Parse and validate `r3-leaves.json`; a malformed entry is refused (`catalog_malformed`)."""
    try:
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("catalog_malformed", type(exc).__name__) from None
    return validate_catalog(catalog)


def validate_catalog(catalog: object) -> dict:
    if not isinstance(catalog, dict) or catalog.get("version") != 1 or not isinstance(catalog.get("nodes"), dict):
        raise Refused("catalog_malformed", "version/nodes")
    for command, entry in catalog["nodes"].items():
        def bad(why: str, command=command):
            raise Refused("catalog_malformed", f"{command}: {why}")
        if not isinstance(entry, dict) or entry.get("class") not in CLASSES:
            bad("class")
        revisions = entry.get("revisions")
        if not isinstance(revisions, list) or not revisions or not all(isinstance(r, str) for r in revisions):
            bad("revisions")
        if entry.get("program", "zeus") not in PROGRAMS:
            bad("program")
        if entry["class"] in ("excluded", "disputed") and not str(entry.get("reason", "")).strip():
            bad("reason is required")
        if entry["class"] == "read_only":
            argv = entry.get("argv")
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                bad("argv")
            wanted = [side for side in SIDES if side in revisions]
            if entry.get("program", "zeus") != "zeus":
                # No parser inventory proves a monitor/module leaf is the same code in a release: every listed revision
                # carries its own citations (RH-4d).
                wanted = list(revisions)
            cites = entry.get("cites", {})
            for side in wanted:
                if not cites.get(side) or not all(re.fullmatch(r"[\w/.]+\.py:[A-Za-z_][\w.]*", c) for c in cites[side]):
                    bad(f"citations on {side}")
            if set(PLACEHOLDER.findall(" ".join(argv))) != set(entry.get("params", [])):
                bad("params must list exactly the argv placeholders")
    return catalog


def coverage(catalog: dict, inventories: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    """`{revision: {"unclassified": [...], "stale": [...]}}` for the revisions whose command list is given; empty
    lists everywhere mean every node of every revision is classified and no entry names a node a revision lacks."""
    nodes = catalog["nodes"]
    report = {}
    for revision, found in inventories.items():
        listed = {c for c, e in nodes.items() if revision in e["revisions"] and e.get("program", "zeus") == "zeus"}
        report[revision] = {"unclassified": sorted(set(found) - listed), "stale": sorted(listed - set(found))}
    return report


def assert_covered(catalog: dict, inventories: dict[str, list[str]]) -> None:
    gaps = {r: g for r, g in coverage(catalog, inventories).items() if g["unclassified"] or g["stale"]}
    if gaps:
        first = next(iter(gaps))
        raise Refused("coverage_failed", f"{first}: unclassified={gaps[first]['unclassified'][:3]} "
                      f"stale={gaps[first]['stale'][:3]} (revisions: {sorted(gaps)})")


def disputed(catalog: dict) -> list[str]:
    return sorted(c for c, e in catalog["nodes"].items() if e["class"] == "disputed")


def resolve_citation(citation: str, tree: Path) -> bool:
    """True when `path.py:Name` / `path.py:Class.method` names a def under `tree` (read, not imported)."""
    path, _, dotted = citation.partition(":")
    file = Path(tree) / path
    if not file.is_file():
        return False
    scope: list = ast.parse(file.read_text(encoding="utf-8")).body
    found = None
    for part in dotted.split("."):
        found = next((n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and n.name == part), None)
        if found is None:
            return False
        scope = found.body
    return True


# ---- the closed `rehearsal.r3.*` masks ----

def load_masks(path: Path | str = MASKS) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("masks_malformed", type(exc).__name__) from None
    return validate_masks(document)


def validate_masks(document: object) -> dict:
    """A mask names exact JSON field names (or the ROOT path rewrite); a name that is an owner, generation, attempt,
    lease, status, authorization result, digest, hash or ref is refused (`mask_forbidden_field`)."""
    if not isinstance(document, dict) or document.get("closed") is not True or not isinstance(document.get("masks"), list):
        raise Refused("masks_malformed", "closed/masks")
    seen = set()
    for mask in document["masks"]:
        if not isinstance(mask, dict) or not MASK_ID.fullmatch(str(mask.get("id", ""))) or mask["id"] in seen:
            raise Refused("masks_malformed", "id")
        seen.add(mask["id"])
        if not str(mask.get("reason", "")).strip():
            raise Refused("masks_malformed", f"{mask['id']}: reason")
        fields, rewrite = mask.get("fields"), mask.get("rewrite")
        if (fields is None) == (rewrite is None):
            raise Refused("masks_malformed", f"{mask['id']}: exactly one of fields/rewrite")
        if rewrite is not None and rewrite != "root":
            raise Refused("masks_malformed", f"{mask['id']}: rewrite")
        for field in fields or []:
            if not isinstance(field, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", field):
                raise Refused("masks_malformed", f"{mask['id']}: field name")
            if NEVER_MASKED.search(field):
                raise Refused("mask_forbidden_field", f"{mask['id']}: {field}")
    return document


def _mask_value(value, fields: dict[str, str]):
    if isinstance(value, dict):
        return {k: (f"<masked:{fields[k]}>" if k in fields else _mask_value(v, fields)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v, fields) for v in value]
    return value


def apply_masks(text: str, masks: dict, roots: tuple[str, ...] = ()) -> str:
    """Rewrite each ROOT path to `<ROOT>` (plain text), then, when the text is JSON, replace the value of exactly the
    declared field names; the result is canonical JSON (sorted keys), or the rewritten text when it is not JSON."""
    if any(m.get("rewrite") == "root" for m in masks["masks"]):
        for root in sorted((r for r in roots if r), key=len, reverse=True):
            text = text.replace(root, ROOT_TOKEN)
    fields = {f: m["id"] for m in masks["masks"] for f in m.get("fields", [])}
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    return json.dumps(_mask_value(parsed, fields), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---- the runner ----

@dataclass(frozen=True)
class Side:
    """One revision's way to run a leaf: `spec` is its namespace spec (A and B share the copy's sockets), `commands`
    maps a program (`zeus`, `monitor`) to the command prefix inside the namespace."""
    name: str
    spec: object
    commands: dict


def namespace_runner(side: Side, command: list[str], timeout: float):
    from .namespace import run_in_namespace

    return run_in_namespace(side.spec, command, timeout=timeout)


def snapshot(copy, database: str) -> dict:
    """The copy's D-facts: the whole-database catalog sha256 (rows included) and the Redis keyspace facts with the
    per-prefix digests (`redis_inventory` digests DUMP, so a changed value changes the digest)."""
    dbs, prefixes, failures = d0.redis_facts(Path(copy.redis_socket) / "redis.sock")
    return {"catalog_sha256": catalog_sha256(copy.pg_socket, database), "redis_dbs": dbs, "redis_prefixes": prefixes,
            "redis_failures": failures}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bind_argv(entry: dict, params: dict) -> list[str]:
    missing = [p for p in entry.get("params", []) if p not in params]
    if missing:
        raise Refused("param_missing", ",".join(missing))
    return [PLACEHOLDER.sub(lambda m: str(params[m.group(1)]), a) for a in entry["argv"]]


def read_only_leaves(catalog: dict) -> tuple[list[str], list[str]]:
    """(leaves present on BOTH A and B, read-only commands present on one of A/B only; D-revision-only leaves are R6's)."""
    both, one = [], []
    for command, entry in sorted(catalog["nodes"].items()):
        if entry["class"] != "read_only" or not any(side in entry["revisions"] for side in SIDES):
            continue  # a leaf of D revisions only belongs to R6, not to the A-vs-B parity run
        (both if all(s in entry["revisions"] for s in SIDES) else one).append(command)
    return both, one


def run_r3(sides: dict[str, Side], copy, database: str, catalog: dict, masks: dict, out, *,
           inventories: dict[str, list[str]], params: dict | None = None, timeout: float = 60.0,
           runner: Callable = namespace_runner, snap: Callable = snapshot, clock=_utc_now,
           repository: str | None = None) -> dict:
    """Run every read-only leaf on A and B over `copy`; write `out/r3.json`; raise `R3Failed` (after writing) on any
    failure. `inventories` are the command lists of every revision under test: coverage is checked BEFORE any leaf runs.

    D1 rule: the snapshot after each run must equal the snapshot before it (which equals D0 while every leaf passes).
    After a failing leaf the expectation moves to the new state, so one writer is blamed once, not for every later leaf."""
    params = dict(params or {})
    failures: list[str] = []
    assert_covered(catalog, inventories)
    both, one_side = read_only_leaves(catalog)
    baseline = expected = snap(copy, database)
    if baseline["redis_failures"]:
        failures += [f"d0_redis:{f}" for f in baseline["redis_failures"]]
    roots = (str(sides["A"].spec.root), str(sides["B"].spec.root), str(sides["A"].spec.x), str(sides["B"].spec.x))
    rows, drift = [], False
    for command in both:
        entry = catalog["nodes"][command]
        row = {"node": command}
        try:
            argv = bind_argv(entry, params)
        except Refused as exc:
            row |= {"verdict": "fail", "reason": f"{exc.code}:{exc.detail}"}
            failures.append(f"{command}:{exc.code}:{exc.detail}")
            rows.append(row)
            continue
        if repository is not None and entry.get("program", "zeus") == "zeus":
            argv = ["--repository", repository, *argv]
        reasons = []
        for name in SIDES:
            side = sides[name]
            result = runner(side, [*side.commands[entry.get("program", "zeus")], *argv], timeout)
            after = snap(copy, database)
            stdout = apply_masks(result.stdout, masks, roots)
            stderr = apply_masks(result.stderr, masks, roots)
            row[name] = {"exit": result.returncode, "timed_out": bool(result.timed_out),
                         "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(stderr), "stdout_bytes": len(stdout)}
            changed = [k for k in ("catalog_sha256", "redis_dbs", "redis_prefixes") if after[k] != expected[k]]
            if changed:
                reasons.append(f"not_read_only:{name}:{'+'.join(changed)}")
                expected = after
            if result.timed_out:
                reasons.append(f"timeout:{name}")
        a, b = row["A"], row["B"]
        if a["exit"] != b["exit"]:
            reasons.append(f"exit_differs:{a['exit']}!={b['exit']}")
        for stream in ("stdout_sha256", "stderr_sha256"):
            if a[stream] != b[stream]:
                reasons.append(f"{stream[:-7]}_differs")
        row |= {"verdict": "fail" if reasons else "pass", "reasons": reasons}
        failures += [f"{command}:{r}" for r in reasons]
        rows.append(row)
    drift = expected != baseline
    failures += [f"disputed_unresolved:{c}" for c in disputed(catalog)]
    facts = {"database": database, "catalog_sha256_d0": baseline["catalog_sha256"], "d1_equals_d0": not drift,
             "catalog_sha256_d1": expected["catalog_sha256"], "leaves": len(both), "passed": sum(r["verdict"] == "pass" for r in rows),
             "skipped_one_side": one_side, "disputed": disputed(catalog), "revisions": sorted(inventories),
             "results": rows, "failures": sorted(failures)}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    document = {"at": clock(), "status": "failed" if failures else "ok", "facts": facts}
    write_record(out / "r3.json", document, max_items=MAX_RECORD_ITEMS)
    if failures:
        raise R3Failed(document)
    return document


def host_runner(side: Side, command: list[str], timeout: float):
    """A host-side leaf runner (tests only, no namespace): `side.spec` is the closed env mapping the child gets."""
    from .namespace import NsRun

    env = {"PATH": "/usr/bin:/bin", **dict(side.spec)}
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return NsRun(124, "", "", 0, True)
    return NsRun(done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"), 0)


__all__ = ["R3Failed", "Side", "parser_inventory", "load_catalog", "coverage", "assert_covered", "load_masks",
           "apply_masks", "run_r3", "snapshot", "host_runner"]
