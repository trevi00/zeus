"""The rehearsal R4 read-compat sweep (RH-4b): the reader catalog `r4-readers.json`, its coverage check and the A-vs-B runner.

Layer: harness (never shipped). Standard library plus the tooling modules (`r3.Side`/runners/`snapshot`, `evidence`).
Rehearsal design "6. R4: read-compat sweep" and AMD-1 A/B (the oracle A is the rebaseline wheel, b9d8f15's tree).

Catalog (`r4-readers.json`): every D0 bucket maps to its owning context (the target `OWNED_BUCKETS`) and, per column
(`A`, `B` and each R0 revision `D_rev`), a reader entry `{"reader": "<path>.py:<Class.>name", "call": "body" | "id_body"}`
(a pure single-record parse/validate/projection callable, traced in that column's tree; `path` is relative to
`src/codex_harness`) or `{"reader": null, "reason": "..."}`. Every Redis namespace class has a `prefix_re` (matched against
the D0 `redis_prefixes` second half) and a `key_re` (matched against each key) and the same per-column entries.

Coverage: D0's bucket set (every exported schema) and every D0 Redis prefix must be in the catalog, else the run FAILS with
`coverage_missing:<bucket>` before any child starts. A catalog bucket absent from this D0 is reported (`catalog_only`), never
a failure: one static catalog cannot equal every real D0.

Runner: per side, ONE child process (the injected `runner`, by default `r3.namespace_runner`) over the same copy. The child
imports the side's own `codex_harness` from its `src` (refused when it came from elsewhere), reads every row of every
cataloged bucket of every exported schema in one read-only transaction and calls the reader. A failure is a 5-tuple
`(schema, bucket, id, exception class name, code)`: the class is `type(exc).__name__` (never qualified: `ContractError` lives
in different modules on A and B) and `code` an attribute (`reason_code`/`code`) only, never `str(exc)` (a message may carry a
body value). A bucket whose entry on that column is `none` counts as the failure `(schema, bucket, "*", "NoReader", "none")`;
an unimportable reader as `(..., "*", "ReaderUnavailable", <class>)`: never a skip. D1 == D0 is checked around each child.

PASS = failures(candidate) == failures(base), after removing the declared intended differences (each names the AMD-1 section
that authorizes it, and is matched on side, bucket, class and code). Anything else fails.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import Refused, r3
from .evidence import _utc_now, check_facts, write_record

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
READERS = HERE / "r4-readers.json"
COVERAGE = HERE / "r4-coverage.json"
MAX_RECORD_ITEMS = 4096
CALLS = {"body": 1, "id_body": 2}
CITATION = re.compile(r"[\w/]+\.py:[A-Za-z_][\w.]*")
AMD1_SECTIONS = frozenset({"A", "B", "C", "D"})
NO_READER = ("*", "NoReader", "none")

SWEEPER = r'''
import json, re, sys
args = json.loads(sys.argv[1])
src = args["src"]
sys.path.insert(0, src)
import importlib
import codex_harness
from pathlib import Path
if not Path(codex_harness.__file__).resolve().is_relative_to(Path(src).resolve()):
    print(json.dumps({"origin_refused": True}))
    sys.exit(3)
failures, counts = [], {}
CODE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
def code_of(exc):
    for name in ("reason_code", "code"):
        value = getattr(exc, name, None)
        if isinstance(value, str) and CODE.fullmatch(value):
            return value
    return "-"
def fail(schema, bucket, ident, kind, code):
    failures.append([schema, bucket, str(ident)[:120], kind, code])
cache = {}
def reader_of(entry):
    cite = entry["reader"]
    if cite not in cache:
        try:
            path, _, dotted = cite.partition(":")
            name = "codex_harness." + path[:-3].replace("/", ".")
            if name.endswith(".__init__"):
                name = name[:-9]
            obj = importlib.import_module(name)
            for part in dotted.split("."):
                obj = getattr(obj, part)
            if not callable(obj):
                raise TypeError(cite)
            cache[cite] = (obj, None)
        except Exception as exc:  # noqa: BLE001 - class name only
            cache[cite] = (None, type(exc).__name__)
    return cache[cite]
def apply(entry, ident, body):
    fn, bad = reader_of(entry)
    if fn is None:
        return bad
    fn(body) if entry["call"] == "body" else fn(ident, body)
    return None
if args.get("dsn"):
    import psycopg
    from psycopg import sql
    with psycopg.connect(args["dsn"], connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        for schema, buckets in sorted(args["schemas"].items()):
            for bucket in buckets:
                entry = args["readers"].get(bucket)
                if not entry or not entry.get("reader"):
                    continue
                _, bad = reader_of(entry)
                if bad:
                    fail(schema, bucket, "*", "ReaderUnavailable", bad)
                    continue
                rows = conn.execute(sql.SQL("SELECT id, body FROM {}.documents WHERE bucket = %s ORDER BY id").format(
                    sql.Identifier(schema)), (bucket,)).fetchall()
                counts[schema + "|" + bucket] = len(rows)
                for ident, body in rows:
                    try:
                        apply(entry, ident, body)
                    except Exception as exc:  # noqa: BLE001 - class and code only, never a message or body
                        fail(schema, bucket, ident, type(exc).__name__, code_of(exc))
redis_cfg = args.get("redis")
if redis_cfg:
    import redis
    classes = [(name, re.compile(spec["key_re"]), spec) for name, spec in redis_cfg["classes"].items()]
    admin = redis.Redis(unix_socket_path=redis_cfg["socket"], socket_timeout=10)
    for db_name in sorted(admin.info("keyspace")):
        db = int(db_name[2:] if isinstance(db_name, str) else db_name.decode()[2:])
        client = redis.Redis(unix_socket_path=redis_cfg["socket"], db=db, socket_timeout=10)
        for raw in client.scan_iter(count=1000):
            key = raw.decode("utf-8", "replace")
            found = next(((n, s) for n, rx, s in classes if rx.fullmatch(key)), None)
            where = "redis|db%d" % db
            if found is None:
                fail(where, "redis:unclassified", key, "Unclassified", "coverage")
                continue
            name, spec = found
            entry = spec["entry"]
            if not entry.get("reader"):
                continue
            _, bad = reader_of(entry)
            if bad:
                fail(where, "redis:" + name, "*", "ReaderUnavailable", bad)
                continue
            if client.type(raw) != b"stream":
                fail(where, "redis:" + name, key, "WrongType", "type")
                continue
            for entry_id, fields in client.xrange(raw):
                ident = key + "@" + entry_id.decode()
                counts[where + "|redis:" + name] = counts.get(where + "|redis:" + name, 0) + 1
                try:
                    apply(entry, ident, json.loads(fields[b"body"]))
                except Exception as exc:  # noqa: BLE001
                    fail(where, "redis:" + name, ident, type(exc).__name__, code_of(exc))
print(json.dumps({"origin": codex_harness.__file__, "failures": failures, "counts": counts}))
'''


class R4Failed(Refused):
    """The record was written with `status: failed`; `document` is that record and `failures` its reasons."""

    def __init__(self, document: dict):
        self.document, self.failures = document, document["facts"]["failures"]
        super().__init__("r4_failed", "; ".join(self.failures[:8]))


# ---- the catalog ----

def load_catalog(path: Path | str = READERS) -> dict:
    try:
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("catalog_malformed", type(exc).__name__) from None
    return validate_catalog(catalog)


def _entry_ok(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("reader") is None:
        return bool(str(entry.get("reason", "")).strip())
    return bool(CITATION.fullmatch(str(entry["reader"]))) and entry.get("call") in CALLS


def validate_catalog(catalog: object) -> dict:
    """Refuse (`catalog_malformed`) a catalog with a wrong shape, an entry without a typed reader or a reason, a column
    missing for a bucket, or a declared difference that does not name the AMD-1 section authorizing it."""
    def bad(why: str):
        raise Refused("catalog_malformed", why)
    if not isinstance(catalog, dict) or catalog.get("version") != 1 or not isinstance(catalog.get("buckets"), dict) \
            or not isinstance(catalog.get("redis"), dict) or not isinstance(catalog.get("trees"), dict):
        bad("version/trees/buckets/redis")
    revisions = sorted(catalog["trees"].get("D", {}))
    columns = ["A", "B"]
    for name, row in [*catalog["buckets"].items(), *catalog["redis"].items()]:
        if not isinstance(row, dict) or not str(row.get("owner", "")).strip():
            bad(f"{name}: owner")
        for column in columns:
            if not _entry_ok(row.get(column)):
                bad(f"{name}: column {column}")
        if not isinstance(row.get("D"), dict) or sorted(row["D"]) != revisions or not all(
                _entry_ok(e) for e in row["D"].values()):
            bad(f"{name}: D columns must be exactly {revisions}")
    for name, row in catalog["redis"].items():
        for key in ("prefix_re", "key_re"):
            try:
                re.compile(row[key])
            except (KeyError, TypeError, re.error):
                bad(f"{name}: {key}")
    for item in catalog.get("declared", []):
        if not isinstance(item, dict) or item.get("side") not in ("A", "B") or item.get("amd1") not in AMD1_SECTIONS \
                or not all(str(item.get(k, "")).strip() for k in ("bucket", "class", "code", "reason")):
            bad("declared difference needs side, bucket, class, code, reason and the authorizing amd1 section")
    return catalog


def _source(tree: dict, relative: str) -> str | None:
    """The text of `relative` (under the tree's root) at the tree's commit, or in this checkout when `rev` is null."""
    where = f"{tree['root']}/{relative}"
    if tree.get("rev") is None:
        file = REPO / where
        return file.read_text(encoding="utf-8") if file.is_file() else None
    done = subprocess.run(["git", "show", f"{tree['rev']}:{where}"], cwd=REPO, capture_output=True, check=False)
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


def reader_signature(citation: str, tree: dict) -> dict | None:
    """Static facts of the cited def in `tree` (parsed, never imported): `{"kind": function | static | class | instance,
    "required": positional parameters without a default (self/cls excluded)}`; None when the def does not exist."""
    path, _, dotted = citation.partition(":")
    text = _source(tree, path)
    if text is None:
        return None
    scope, found = ast.parse(text).body, None
    for part in dotted.split("."):
        found = next((n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and n.name == part), None)
        if found is None:
            return None
        scope = found.body
    if not isinstance(found, ast.FunctionDef):
        return None
    decorators = {d.id for d in found.decorator_list if isinstance(d, ast.Name)}
    positional = [a.arg for a in [*found.args.posonlyargs, *found.args.args]]
    method = "." in dotted
    kind = "function" if not method else "static" if "staticmethod" in decorators else \
        "class" if "classmethod" in decorators else "instance"
    if kind in ("class", "instance") and positional:
        positional = positional[1:]
    required = len(positional) - len(found.args.defaults)
    if any(k is None for k in found.args.kw_defaults):
        required += 1  # a required keyword-only parameter can never be satisfied by the sweep
    return {"kind": kind, "required": max(required, 0)}


def reader_problem(entry: dict, tree: dict) -> str | None:
    """Why a typed entry cannot be called by the sweep in `tree` (None when it can): a missing def, a method needing
    an instance, or a signature that does not take exactly the declared inputs."""
    if entry.get("reader") is None:
        return None
    facts = reader_signature(entry["reader"], tree)
    if facts is None:
        return "unresolved"
    if facts["kind"] in ("instance", "class"):
        return "needs_instance" if facts["kind"] == "instance" else "classmethod_unsupported"
    return None if facts["required"] <= CALLS[entry["call"]] else "too_many_parameters"


# ---- the column scan (regenerates the columns of the catalog; never by hand) ----

# The cutover columns (owner decisions DD-19/DD-20, AMD-1 errata E2/E6): the oracle A is rebaseline entry 2, B the lane3
# head at CUT-INT, and the PR-3 release and the managed payload join the D columns.
CUTOVER_TREES = {
    "A": {"rev": "bb579d558cd5902fa9d6493fad9b92ebd5be4b68", "root": "src/codex_harness",
          "label": "the rebaseline wheel (AMD-1 A), rebaseline entry 2 (G1-09F): bb579d55"},
    "B": {"rev": "8be54d0a336bf0e8c7b609274ec1334e16468a37", "root": "src/codex_harness",
          "label": "final regeneration at CUT-INT on H: the lane3 head 8be54d0a (S2R port G1-13, PR-3 batch a G1-14a)"},
    "D": {"1b9d746c": {"rev": "1b9d746c52ab1a116beda5c72a23f86903aeb4f3", "root": "src/codex_harness",
                       "label": "the PR-3 release"},
          "ec8aa0a2": {"rev": "ec8aa0a2947f964eeb94faed20cb6cf05e0681f6", "root": "src/codex_harness",
                       "label": "the managed payload runtime"}},
}
# The PR-3 bucket: its row, and the reader traced in the PR-3 trees (`permit_view` projects one permit row).
PR3_BUCKET = "fleet_maintenance_admissions"
PR3_ROW = {"owner": "coordination", "amd1": "B", "reader": "domain/fleet_maintenance.py:permit_view", "call": "body"}
PR3_ABSENT = "bucket introduced by PR-3"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False)


def tree_files(tree: dict) -> list[str]:
    """The python files of a pinned tree, relative to its root."""
    done = _git("ls-tree", "-r", "--name-only", tree["rev"], "--", tree["root"])
    prefix = tree["root"] + "/"
    return sorted(f[len(prefix):] for f in done.stdout.decode().splitlines() if f.endswith(".py"))


def tree_mentions(tree: dict, text: str) -> bool:
    """Whether `text` occurs anywhere under the tree's root at its commit (`git grep -F`)."""
    return _git("grep", "-q", "-F", text, tree["rev"], "--", tree["root"]).returncode == 0


def locate(citation: str, tree: dict) -> str | None:
    """The citation itself when its def exists in `tree`, else the same def (file basename and dotted name) elsewhere in
    the tree (a context move), else None."""
    if reader_signature(citation, tree) is not None:
        return citation
    path, _, dotted = citation.partition(":")
    base = path.rsplit("/", 1)[-1]
    return next((f"{c}:{dotted}" for c in tree_files(tree)
                 if c.rsplit("/", 1)[-1] == base and reader_signature(f"{c}:{dotted}", tree)), None)


def trace_entry(seed: dict, tree: dict) -> dict:
    """The typed entry for the seed `{"reader", "call"}` traced in `tree`, or a `none` entry saying why it is not callable."""
    found = locate(seed["reader"], tree)
    if found is not None:
        entry = {"reader": found, "call": seed["call"]}
        problem = reader_problem(entry, tree)
        if problem is None:
            return entry
        return {"reader": None, "reason": f"the reader ({found}) is not callable in {tree['rev'][:8]}: {problem}"}
    return {"reader": None, "reason": f"the reader ({seed['reader']}) is not callable in {tree['rev'][:8]}: unresolved"}


def _column(old: dict | None, seeds: list[dict], tree: dict, *, gate: str | None, absent: str, default: str,
            carried_from: str | None) -> dict:
    """One regenerated column entry. `gate`: a bucket name that must occur in the tree, else the entry is `none` with
    `absent`. Seeds are traced in order (the first that resolves wins; none resolving leaves the last reason). With no
    typed seed the old untyped entry is carried (reason annotated with the scan it came from), else `default`."""
    if gate and not tree_mentions(tree, gate):
        return {"reader": None, "reason": absent}
    entry = None
    for seed in seeds:
        entry = trace_entry(seed, tree)
        if entry["reader"] is not None:
            return entry
    if entry is not None:
        return entry
    if old is None or carried_from is None:
        return {"reader": None, "reason": default}
    return {"reader": None, "reason": f"{old['reason']} [carried from the {carried_from} scan]"}


def _typed(entry: dict | None) -> list[dict]:
    return [entry] if entry and entry.get("reader") else []


def regenerate(catalog: dict, trees: dict = CUTOVER_TREES) -> dict:
    """The catalog with the cutover columns: A and B re-pinned with every typed reader re-traced in the new tree (the old
    citation, else the same def elsewhere in it; B also tries A's new citation, which is how the S2R readers move in),
    the new D columns traced from A's new citation, and the PR-3 bucket row added (a reader per column, or `none` +
    "bucket introduced by PR-3" where the tree lacks the bucket name). Untyped entries are carried with their reason.
    A column already pinned at its new rev is left as it is, so a second run changes nothing."""
    out = json.loads(json.dumps(catalog))
    old_trees = out["trees"]
    pin = {c: old_trees[c]["rev"] != trees[c]["rev"] for c in ("A", "B")}
    old_rev = {c: (old_trees[c]["rev"] or "")[:8] or "checkout" for c in ("A", "B")}
    new_d = [n for n in trees["D"] if n not in old_trees["D"]]
    out["trees"] = {"A": dict(trees["A"]) if pin["A"] else old_trees["A"], "B": dict(trees["B"]) if pin["B"] else old_trees["B"],
                    "D": {**old_trees["D"], **{n: dict(trees["D"][n]) for n in new_d}}}
    tree = {"A": out["trees"]["A"], "B": out["trees"]["B"], **out["trees"]["D"]}
    if PR3_BUCKET not in out["buckets"]:
        out["buckets"][PR3_BUCKET] = {"owner": PR3_ROW["owner"], "amd1": PR3_ROW["amd1"], "A": None, "B": None,
                                      "D": {n: None for n in old_trees["D"]}}
    permit = {"reader": PR3_ROW["reader"], "call": PR3_ROW["call"]}
    for name, row in {**out["buckets"], **out["redis"]}.items():
        pr3, fa = name == PR3_BUCKET, name == "fleet_admission_permits"
        gate = name if pr3 or fa else None
        gone = PR3_ABSENT if pr3 else "the bucket name does not occur in the pinned tree"
        seeds = [permit] if pr3 else None
        if pr3 or pin["A"]:
            row["A"] = _column(row["A"], seeds or _typed(row["A"]), tree["A"], gate=gate, default="",
                               absent=PR3_ABSENT if pr3 else (row["A"] or {}).get("reason", ""), carried_from=old_rev["A"])
        if pr3 or pin["B"]:
            row["B"] = _column(row["B"], seeds or _typed(row["B"]) + _typed(row["A"]), tree["B"], gate=gate, default="",
                               absent=gone, carried_from=old_rev["B"])
        for revname in [*old_trees["D"], *new_d]:
            if row["D"].get(revname) is not None:
                continue
            row["D"][revname] = _column(None, seeds or _typed(row["A"]), tree[revname], gate=gate, absent=gone,
                                        default="no typed reader on A for this bucket (same untyped-dict reading in "
                                                "the R0 release)", carried_from=None)
        row["D"] = {n: row["D"][n] for n in out["trees"]["D"]}
    if out["trees"]["B"]["rev"] == trees["B"]["rev"]:
        _s2r(out)
    return out


S2R_B = {  # the S2R shape rows' B texts, each citation verified in the B tree by `regenerate` (G1-13a placed them)
    "intent `generations`": ("delivery/domain/host_delivery.py:maintenance_of (and validate_active_generation for one row: "
                             "delivery/domain/maintenance.py:validate_active_generation)"),
    "maintenance rows": "delivery/domain/host_delivery.py:maintenance_of",
    "release-queue": ("review/application/release_queue.py:MAINTENANCE_SCOPE, read by ReleaseQueue.owned_maintenance "
                      "(needs a transaction: no single-record reader)"),
}


def _s2r(out: dict) -> None:
    """Set each S2R shape row's B text from `S2R_B`, refusing a citation that does not resolve in the B tree."""
    for item in out["s2r"]:
        key = next(k for k in S2R_B if item["shape"].startswith(k))
        text = S2R_B[key]
        cites = re.findall(r"[\w/]+\.py:[A-Za-z_][\w.]*", text)
        if any(reader_signature(c, out["trees"]["B"]) is None and not c.endswith("MAINTENANCE_SCOPE") for c in cites) \
                or not tree_mentions(out["trees"]["B"], "MAINTENANCE_SCOPE"):
            raise Refused("catalog_malformed", f"s2r B citation unresolved: {key}")
        item["B"] = text


def write_catalog(catalog: dict, path: Path | str = READERS) -> None:
    Path(path).write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")


# ---- the read-coverage map (RH-4c; DD-19, critic #14 / AC7) ----
#
# Per column and D0 bucket: `typed` (the column has a typed reader), `leaf_covered` (a read-only R3 leaf of that column was
# OBSERVED reading the bucket on a trace copy) or `uncovered`. `uncovered > 0` is reported and is never a PASS: the record
# has a `verdict` (`uncovered`, `complete` or `not_observed`), never `pass`. The statement log is parsed host-side from ROOT
# (`copies.Copy.trace_dir`); a statement on the records table that cannot be parsed fails the run closed.

RECORDS_TABLE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE|COPY)\s+(?:ONLY\s+)?(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:\"?\w+\"?\.)?\"?documents\b", re.I)
LOG_HEAD = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? \S+ \[\d+\] (\w+):  (.*)$")
LOG_SQL = re.compile(r"^(?:statement|execute [^:]*): (.*)$", re.S)
LOG_PARAM = re.compile(r"\$(\d+) = (NULL|'(?:[^']|'')*')(?:, |$)")
BUCKET_EQ = re.compile(r"\bbucket\s*=\s*(\$\d+|'(?:[^']|'')*')", re.I)
WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "TRUNCATE", "MERGE"})
DDL_VERBS = frozenset({"CREATE", "ALTER", "DROP", "COMMENT", "GRANT", "REVOKE"})
STATUSES = ("typed", "leaf_covered", "uncovered")


class LogUnparseable(Refused):
    """A trace-log line or a records-table statement could not be parsed; carries a class and a line number, never text."""

    def __init__(self, why: str, line: int):
        super().__init__("coverage_log_unparseable", f"{why} at log line {line}")


def _unquote(literal: str) -> str:
    return literal[1:-1].replace("''", "'")


def _statements(text: str):
    """`(line, sql, parameters_text | None)` of every `statement:`/`execute` log entry of `text`; a line that is neither an
    entry header nor a continuation (tab/space-led) of one is a `LogUnparseable`."""
    entries: list[list] = []  # [line, level, message]
    for number, line in enumerate(text.splitlines(), 1):
        head = LOG_HEAD.match(line)
        if head:
            entries.append([number, head.group(1), head.group(2)])
        elif line[:1] in ("\t", " ") and entries:
            entries[-1][2] += "\n" + line.lstrip("\t")
        elif line.strip():
            raise LogUnparseable("line is not a log entry", number)
    for index, (number, level, message) in enumerate(entries):
        found = LOG_SQL.match(message) if level == "LOG" else None
        if found is None:
            continue
        nxt = entries[index + 1] if index + 1 < len(entries) else None
        # PostgreSQL 17 writes `Parameters:`, earlier releases `parameters:`
        params = nxt[2][len("parameters: "):] if nxt and nxt[1] == "DETAIL" and nxt[2].lower().startswith("parameters: ") \
            else None
        yield number, found.group(1), params


def _params(text: str | None, line: int) -> dict[str, str | None]:
    if text is None:
        raise LogUnparseable("statement parameters missing", line)
    out, position = {}, 0
    while position < len(text):
        found = LOG_PARAM.match(text, position)
        if found is None:
            raise LogUnparseable("parameters unparseable", line)
        out[found.group(1)] = None if found.group(2) == "NULL" else _unquote(found.group(2))
        position = found.end()
    return out


def parse_statement_log(text: str) -> dict:
    """What the statements of `text` did to the records table (`documents`): `{"buckets": sorted names read by a
    bucket predicate, "all_buckets_reads": n of whole-table reads (no WHERE; they name no bucket and cover none), "writes":
    n, "ddl": n, "statements": n}`. Fails closed (`LogUnparseable`): a line that is no log entry, a read whose `WHERE` has no
    `bucket = $n|'literal'` predicate, a predicate whose parameter is missing or unparseable, or a records-table
    statement of any other verb."""
    buckets: set[str] = set()
    whole = writes = ddl = total = 0
    for line, sql, param_text in _statements(text):
        total += 1
        if not RECORDS_TABLE.search(sql):
            continue
        verb = sql.lstrip("( \t\n").split(None, 1)[0].upper() if sql.strip() else ""
        if verb in WRITE_VERBS:
            writes += 1
        elif verb in DDL_VERBS:
            ddl += 1
        elif verb in ("SELECT", "WITH"):
            if not re.search(r"\bWHERE\b", sql, re.I):
                whole += 1
                continue
            predicates = BUCKET_EQ.findall(sql)
            if not predicates:
                raise LogUnparseable("records read without a bucket predicate", line)
            params = None
            for predicate in predicates:
                if predicate.startswith("$"):
                    params = params if params is not None else _params(param_text, line)
                    value = params.get(predicate[1:])
                    if value is None:
                        raise LogUnparseable("bucket parameter missing", line)
                else:
                    value = _unquote(predicate)
                buckets.add(value)
        else:
            raise LogUnparseable("records statement of an unknown kind", line)
    return {"buckets": sorted(buckets), "all_buckets_reads": whole, "writes": writes, "ddl": ddl, "statements": total}


def read_trace_log(trace_dir: Path | str) -> str:
    """The whole statement log under ROOT (every `*.log` of the trace directory, in name order)."""
    directory = Path(trace_dir)
    if not directory.is_dir():
        raise Refused("trace_off", "the copy has no statement log directory (started without trace mode?)")
    return "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(directory.glob("*.log")))


def _mark(copy, database: str, marker: str, trace_dir: Path, *, wait: float = 30.0) -> None:
    """Run one marker statement over the copy and wait until the collector wrote it to the log (the log is asynchronous)."""
    import psycopg

    from .copies import pg_dsn

    with psycopg.connect(pg_dsn(copy.pg_socket, database), autocommit=True, connect_timeout=10) as conn:
        conn.execute("SELECT %s", (marker,))
    deadline = time.monotonic() + wait
    while marker not in read_trace_log(trace_dir):
        if time.monotonic() > deadline:
            raise Refused("trace_log_stalled", "a marker statement did not reach the statement log")
        time.sleep(0.1)


def _window(text: str, before: str, after: str) -> str:
    """The log lines between the two marker statements (whole lines; the marker lines themselves excluded)."""
    start = text.index(before)
    start = text.find("\n", start) + 1
    end = text.rfind("\n", 0, text.index(after)) + 1
    return text[start:end]


def leaves_of(leaf_catalog: dict, column: str) -> list[str]:
    """The read-only R3 leaf commands whose catalog entry lists the revision `column`, sorted."""
    return sorted(c for c, e in leaf_catalog["nodes"].items() if e["class"] == "read_only" and column in e["revisions"])


def observe_column(column: str, side: r3.Side, copy, database: str, leaf_catalog: dict, *, params: dict, runner: Callable,
                   timeout: float, repository: str | None = None, wait: float = 30.0) -> dict:
    """Run each read-only leaf of `column` on `side` over the trace `copy`, one marker-bounded log window per leaf, and
    return `{"leaves": n, "buckets": [...], "results": [{node, exit, buckets, all_buckets_reads}], "errors": [...]}`. Run
    errors (a leaf that timed out, wrote the records table or could not be bound, an unparseable log) go in `errors`; a
    window that cannot be parsed is an error for that leaf and its buckets are NOT counted."""
    trace_dir = copy.trace_dir
    if trace_dir is None:
        raise Refused("trace_off", "the copy was not started in trace mode")
    results, errors, seen = [], [], set()
    nonce = f"{time.time_ns():x}"  # a marker is unique to this observation, so an earlier run's marker never satisfies it
    for number, command in enumerate(leaves_of(leaf_catalog, column)):
        entry = leaf_catalog["nodes"][command]
        program = entry.get("program", "zeus")
        try:
            argv = r3.bind_argv(entry, params)
        except Refused as exc:
            errors.append(f"{command}:{exc.code}:{exc.detail}")
            continue
        if repository is not None and program == "zeus":
            argv = ["--repository", repository, *argv]
        pre, post = (f"rh-trace-{nonce}-{column}-{number}-{kind}" for kind in ("pre", "post"))
        _mark(copy, database, pre, trace_dir, wait=wait)
        result = runner(side, [*side.commands[program], *argv], timeout)
        _mark(copy, database, post, trace_dir, wait=wait)
        row = {"node": command, "exit": result.returncode}
        if result.timed_out:
            errors.append(f"{command}:timeout")
        try:
            seen_here = parse_statement_log(_window(read_trace_log(trace_dir), pre, post))
        except LogUnparseable as exc:
            errors.append(f"{command}:{exc.code}:{exc.detail}")
            results.append(row)
            continue
        if seen_here["writes"]:
            errors.append(f"{command}:leaf_wrote_records:{seen_here['writes']}")
        row |= {"buckets": seen_here["buckets"], "all_buckets_reads": seen_here["all_buckets_reads"]}
        seen |= set(seen_here["buckets"])
        results.append(row)
    return {"leaves": len(results), "buckets": sorted(seen), "results": results, "errors": errors}


def _entry_of(row: dict, column: str) -> dict:
    return row[column] if column in ("A", "B") else row["D"][column]


def coverage_map(catalog: dict, observed: dict[str, dict] | None = None, buckets: list[str] | None = None) -> dict:
    """The per-column classification (pure). `buckets` is the universe (default: every cataloged bucket; a D0 record's
    buckets when given); `observed[column]` the `observe_column` result (a column without one has `observation:
    "not_run"` and its untyped buckets are `uncovered`). Redis namespaces are not records-table buckets and are not
    classified. `verdict` is `uncovered` while any bucket of any column is, `not_observed` when the only gap is a
    column that was not observed, else `complete`; never a pass."""
    observed = observed or {}
    names = sorted(buckets if buckets is not None else catalog["buckets"])
    columns = {"A": "A", "B": "B", **{d: d for d in catalog["trees"]["D"]}}
    out: dict[str, dict] = {}
    for column in columns:
        seen = set((observed.get(column) or {}).get("buckets", ()))
        typed = [b for b in names if b in catalog["buckets"] and _entry_of(catalog["buckets"][b], column).get("reader")]
        leaf = [b for b in names if b not in typed and b in seen]
        gap = [b for b in names if b not in typed and b not in seen]
        out[column] = {"observation": "not_run" if column not in observed else
                       "observed" if observed[column].get("leaves") else "no_leaves",
                       "leaves": (observed.get(column) or {}).get("leaves", 0), "typed": len(typed),
                       "leaf_covered": len(leaf), "uncovered": len(gap), "leaf_covered_buckets": leaf,
                       "uncovered_buckets": gap}
    unobserved = [c for c, v in out.items() if v["observation"] == "not_run"]
    verdict = "complete" if not any(v["uncovered"] for v in out.values()) else \
        "uncovered" if len(unobserved) < len(out) else "not_observed"
    return {"universe": len(names), "columns": out, "verdict": verdict}


def _no_pass(document: dict) -> dict:
    check_facts(document["facts"], max_items=MAX_RECORD_ITEMS)
    return document


def run_coverage_map(sides: dict[str, r3.Side], copy, database: str, catalog: dict, leaf_catalog: dict, d0_record: dict,
                     out, *, params: dict | None = None, runner: Callable = r3.namespace_runner, timeout: float = 120.0,
                     repository: str | None = None, clock=_utc_now, wait: float = 30.0) -> dict:
    """Observe every column in `sides` (column name -> `r3.Side`; a column with no catalogued leaf is observed with zero
    leaves) over the trace `copy` and write `out/r4-coverage.json`. Raises `R4Failed` after writing when a run error
    occurred; `uncovered > 0` alone is reported in the record (`verdict: uncovered`) and is never a pass."""
    validate_catalog(catalog)
    observed, errors = {}, []
    for column, side in sides.items():
        observed[column] = observe_column(column, side, copy, database, leaf_catalog, params=dict(params or {}),
                                          runner=runner, timeout=timeout, repository=repository, wait=wait)
        errors += [f"{column}:{e}" for e in observed[column]["errors"]]
    universe = sorted({b for names in d0_buckets(d0_record["facts"]).values() for b in names})
    result = coverage_map(catalog, observed, universe)
    facts = {**result, "failures": sorted(errors),
             "observed_leaves": {c: [{k: v for k, v in r.items() if k != "buckets"} for r in o["results"]]
                                 for c, o in observed.items()}}
    document = _no_pass({"at": clock(), "status": "failed" if errors else "ok", "facts": facts})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_record(out / "r4-coverage.json", document, max_items=MAX_RECORD_ITEMS)
    if errors:
        raise R4Failed(document)
    return document


def static_map(catalog: dict) -> dict:
    """The no-observation baseline record over the cataloged buckets: typed counts are exact, the rest is `uncovered`
    with `observation: "not_run"` until a trace copy run measures the leaves."""
    return _no_pass({"source": "catalog", "status": "ok", "facts": {**coverage_map(catalog), "failures": []}})


# ---- coverage ----

def d0_buckets(facts: dict) -> dict[str, list[str]]:
    """`{schema: [bucket, ...]}` of a D0 record's facts (`facts["buckets"]`)."""
    return {schema: sorted(buckets) for schema, buckets in facts.get("buckets", {}).items()}


def d0_redis_prefixes(facts: dict) -> list[str]:
    """The key prefixes of the D0 `redis_prefixes` (`db0|zeus:agent` -> `zeus:agent`), sorted and distinct."""
    return sorted({key.partition("|")[2] for key in facts.get("redis_prefixes", {})})


def coverage(catalog: dict, facts: dict) -> dict:
    """`{"missing": [...], "catalog_only": [...]}`: D0 buckets / Redis prefixes the catalog lacks (failures, as
    `coverage_missing:<name>` / `coverage_missing:redis:<prefix>`) and cataloged buckets this D0 does not have."""
    present = {b for buckets in d0_buckets(facts).values() for b in buckets}
    missing = sorted(present - set(catalog["buckets"]))
    patterns = [re.compile(row["prefix_re"]) for row in catalog["redis"].values()]
    missing_redis = [p for p in d0_redis_prefixes(facts) if not any(rx.fullmatch(p) for rx in patterns)]
    return {"missing": [f"coverage_missing:{b}" for b in missing] + [f"coverage_missing:redis:{p}" for p in missing_redis],
            "catalog_only": sorted(set(catalog["buckets"]) - present)}


# ---- the sweep ----

@dataclass(frozen=True)
class R4Side:
    """One column's sweep: `side` is the namespace side (its `commands["python"]` is the interpreter prefix of the
    revision), `src` the revision's `src` directory, `column` the catalog column (`A`, `B` or an R0 revision)."""
    column: str
    side: object
    src: str


def _entries(catalog: dict, column: str, names) -> dict:
    return {name: (catalog["buckets"][name][column] if column in ("A", "B") else catalog["buckets"][name]["D"][column])
            for name in names}


def _redis_classes(catalog: dict, column: str) -> dict:
    return {name: {"key_re": row["key_re"], "entry": row[column] if column in ("A", "B") else row["D"][column]}
            for name, row in catalog["redis"].items()}


def _dedup(items) -> list[list[str]]:
    return sorted({tuple(f) for f in items})


def sweep_side(r4side: R4Side, catalog: dict, facts: dict, dsn: str, redis_socket: str, *, runner: Callable,
               timeout: float) -> dict:
    """Run the sweep of one column; `{"failures": [...], "counts": {...}, "errors": [...]}`. Run-level errors (timeout,
    child exit, refused origin) are reported apart from the record failures: they always fail the run."""
    schemas = d0_buckets(facts)
    readers = _entries(catalog, r4side.column, {b for names in schemas.values() for b in names if b in catalog["buckets"]})
    args = {"src": r4side.src, "dsn": dsn, "schemas": {s: [b for b in names if b in readers] for s, names in schemas.items()},
            "readers": readers, "redis": {"socket": redis_socket, "classes": _redis_classes(catalog, r4side.column)}}
    command = [*r4side.side.commands["python"], "-I", "-c", SWEEPER, json.dumps(args)]
    result = runner(r4side.side, command, timeout)
    errors, failures, counts = [], [], {}
    if result.timed_out:
        errors.append(f"timeout:{r4side.column}")
    elif result.returncode != 0:
        refused = '"origin_refused"' in result.stdout
        errors.append(f"{'origin_refused' if refused else 'sweep_failed'}:{r4side.column}:{result.returncode}")
    else:
        try:
            report = json.loads(result.stdout.strip().splitlines()[-1])
            failures, counts = report["failures"], report["counts"]
        except (ValueError, KeyError, IndexError):
            errors.append(f"sweep_unparsable:{r4side.column}")
    for schema, names in schemas.items():
        for bucket in names:
            if bucket in readers and not readers[bucket].get("reader"):
                failures.append([schema, bucket, *NO_READER])
    prefixes = d0_redis_prefixes(facts)
    for name, row in catalog["redis"].items():
        entry = row[r4side.column] if r4side.column in ("A", "B") else row["D"][r4side.column]
        if not entry.get("reader") and any(re.fullmatch(row["prefix_re"], p) for p in prefixes):
            failures.append(["redis", f"redis:{name}", *NO_READER])
    return {"failures": _dedup(failures), "counts": counts, "errors": errors}


def declared_split(catalog: dict, only: dict[str, list]) -> tuple[dict[str, list], list[dict]]:
    """Remove from `only[side]` (the failures only that side has) every one a declared intended difference matches
    (side, bucket, class, code; `schema` optionally); return the remainder and one `{declaration, absorbed}` per entry."""
    declared = catalog.get("declared", [])
    absorbed = [0] * len(declared)
    rest: dict[str, list] = {}
    for side, items in only.items():
        rest[side] = []
        for item in items:
            schema, bucket, _, kind, code = item
            hit = next((i for i, d in enumerate(declared) if d["side"] == side and d["bucket"] == bucket
                        and d["class"] == kind and d["code"] == code and d.get("schema", schema) == schema), None)
            if hit is None:
                rest[side].append(item)
            else:
                absorbed[hit] += 1
    return rest, [{"bucket": d["bucket"], "side": d["side"], "amd1": d["amd1"], "absorbed": n}
                  for d, n in zip(declared, absorbed)]


def _fmt(item) -> str:
    return "(" + ", ".join(item) + ")"


def run_r4(sides: dict[str, R4Side], copy, database: str, catalog: dict, d0_record: dict, out, *, base: str = "A",
           candidate: str = "B", timeout: float = 600.0, runner: Callable = r3.namespace_runner,
           snap: Callable = r3.snapshot, clock=_utc_now) -> dict:
    """Sweep `base` and `candidate` over `copy` and write `out/r4.json`; raise `R4Failed` (after writing) on any failure.
    `d0_record` is the `d0.json` document (its `facts` list the buckets and Redis prefixes to cover)."""
    validate_catalog(catalog)
    facts = d0_record["facts"]
    covered = coverage(catalog, facts)
    failures: list[str] = list(covered["missing"])
    results: dict[str, dict] = {}
    declared_report: list[dict] = []
    only: dict[str, list] = {"A": [], "B": []}
    if not failures:
        from .copies import pg_dsn

        dsn = pg_dsn(copy.pg_socket, database)
        socket = str(Path(copy.redis_socket) / "redis.sock")
        expected = snap(copy, database)
        for name in (base, candidate):
            results[name] = sweep_side(sides[name], catalog, facts, dsn, socket, runner=runner, timeout=timeout)
            failures += [f"{e}" for e in results[name]["errors"]]
            after = snap(copy, database)
            changed = [k for k in ("catalog_sha256", "redis_dbs", "redis_prefixes") if after[k] != expected[k]]
            if changed:
                failures.append(f"not_read_only:{name}:{'+'.join(changed)}")
                expected = after
        base_set = {tuple(f) for f in results[base]["failures"]}
        cand_set = {tuple(f) for f in results[candidate]["failures"]}
        only = {"A": sorted(base_set - cand_set), "B": sorted(cand_set - base_set)}
        rest, declared_report = declared_split(catalog, only)
        failures += [f"{base}_only:{_fmt(f)}" for f in rest["A"]] + [f"{candidate}_only:{_fmt(f)}" for f in rest["B"]]
    facts_out = {"database": database, "coverage_missing": covered["missing"], "catalog_only": covered["catalog_only"],
                 "base": base, "candidate": candidate, "buckets_in_d0": sum(len(v) for v in d0_buckets(facts).values()),
                 "rows_read": {n: sum(r["counts"].values()) for n, r in results.items()},
                 "failures_by_side": {n: len(r["failures"]) for n, r in results.items()},
                 "common_failures": len({tuple(f) for f in results[base]["failures"]} &
                                        {tuple(f) for f in results[candidate]["failures"]}) if results else 0,
                 "declared": declared_report, "failures": sorted(failures)}
    facts_out["only_listed"] = {"A": [list(f) for f in only["A"]][:40], "B": [list(f) for f in only["B"]][:40]}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    document = {"at": clock(), "status": "failed" if failures else "ok", "facts": facts_out}
    write_record(out / "r4.json", document, max_items=MAX_RECORD_ITEMS)
    if failures:
        raise R4Failed(document)
    return document


def main(argv: list[str] | None = None) -> int:
    """`regenerate`: rewrite `r4-readers.json` with the cutover columns (the AST scan of `regenerate`)."""
    import argparse

    parser = argparse.ArgumentParser(prog="r4", description=main.__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("regenerate", help="re-pin the catalog columns and re-trace every typed reader")
    sub.add_parser("coverage-map", help="write the no-observation baseline r4-coverage.json (typed counts exact; the rest "
                                        "uncovered until a trace-copy run observes the leaves: run_coverage_map)")
    args = parser.parse_args(argv)
    if args.command == "regenerate":
        write_catalog(regenerate(load_catalog()))
        load_catalog()
        print(f"wrote {READERS}")
    else:
        document = static_map(load_catalog())
        COVERAGE.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        counts = {c: {k: v[k] for k in STATUSES} for c, v in document["facts"]["columns"].items()}
        print(f"wrote {COVERAGE}: verdict {document['facts']['verdict']}: {json.dumps(counts, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["R4Failed", "R4Side", "load_catalog", "validate_catalog", "coverage", "reader_problem", "reader_signature",
           "sweep_side", "declared_split", "run_r4", "regenerate", "coverage_map", "run_coverage_map", "observe_column",
           "parse_statement_log", "static_map", "LogUnparseable"]
