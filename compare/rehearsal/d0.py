"""The rehearsal R2 "D0" recorder (RH-3): a body-free, deterministic fact record of one disposable copy.

`record_d0(copy, b_release, out)` writes `out/d0.json` through the evidence writer (`evidence.write_record`, O_EXCL).
It holds names, counts and digests only; a record body never enters the document. Everything is read through the
product's read-only `host_migration` functions (`pg_catalog`/`catalog_digest`, `pg_export`, `redis_inventory`), run
host-side over the copy's Unix sockets, and the copy's catalog digest is taken before AND after: a change is a failure.

Fields (rehearsal design "4. R2: D0"): the catalog sha256; per schema and per bucket the row count and the sha256
of the sorted canonical body digests; the knowledge tables and `schema_migrations` versions; the Redis keyspace
coverage; the active hook count; the persisted `codex_harness.` argv modules and their resolution in B.

Redis prefix rule: for every key of a db (SCAN), the prefix is the key up to its first two `:`-separated segments
(`a:b:c:d` -> `a:b`, `a:b` -> `a:b`, `a` -> `a`); a prefix with a shorter prefix as ancestor is dropped (so the
inventoried sets are disjoint). The product `redis_inventory` runs over those prefixes, and per db the number of
distinct inventoried keys must equal DBSIZE (INFO keyspace); a shortfall FAILS the record with the uncovered count.

Persisted argv: every string (keys, values, ids, bucket names) of every exported document is searched for
`codex_harness.<dotted>` names. Each module must resolve inside B (`PathFinder.find_spec` over `<b_release>/src`,
nothing imported or executed) and be a section 3.5 shim (`import_rules.SHIMS`) or a target module (any other class
`import_rules.classify` knows). An unresolved or unclassified module FAILS the record. SH-c (the moved
`isolated_worker` entry, DESIGN-s11) and E5b (a shim name, the `ARGV_MAP` rows) are flagged on the module.

Failures never abort the read: the record is written with `status: failed` and `facts.failures`, then `D0Failed` is
raised, so the evidence exists and a caller cannot ignore it. Two runs over one copy differ only in `at`.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

from . import Refused
from .copies import COMPARE, pg_dsn
from .evidence import _utc_now, write_record

MAX_RECORD_ITEMS = 4096  # the per-container bound of the D0 record (it lists every schema, bucket and module)
KNOWLEDGE_TABLES = ("knowledge_nodes", "knowledge_edges")
MODULE = re.compile(r"codex_harness(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
SCHEMA_IDENT = re.compile(r"[a-z_][a-z0-9_]{0,62}")


class D0Failed(Refused):
    """The record was written with `status: failed`; `document` is that record and `failures` its reasons."""

    def __init__(self, document: dict):
        self.document, self.failures = document, document["facts"]["failures"]
        super().__init__("d0_failed", "; ".join(self.failures))


def _import_rules():
    spec = importlib.util.spec_from_file_location("rehearsal_import_rules", COMPARE.parent / "tests" / "import_rules.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest_of(digests: list[str]) -> str:
    return _sha("\n".join(sorted(digests)))


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def redis_prefix(key: str) -> str:
    """The key up to its first two `:`-separated segments."""
    return ":".join(key.split(":")[:2])


def minimal_prefixes(prefixes) -> list[str]:
    """Drop every prefix that has another prefix as an ancestor (`a` covers `a:*`, hence `a:b`)."""
    unique = sorted(set(prefixes))
    return [p for p in unique if not any(p != q and p.startswith(q + ":") for q in unique)]


def resolve_module(name: str, src: Path) -> bool:
    """True when the dotted `name` is a module or package whose files all lie under `src` (nothing is imported)."""
    root = Path(src).resolve()
    path = [str(root)]
    parts = name.split(".")
    for index in range(len(parts)):
        spec = importlib.machinery.PathFinder.find_spec(".".join(parts[: index + 1]), path)
        if spec is None:
            return False
        places = [spec.origin] if spec.origin not in (None, "namespace") else []
        places += list(spec.submodule_search_locations or [])
        if not places or not all(Path(p).resolve().is_relative_to(root) for p in places):
            return False
        path = list(spec.submodule_search_locations or [])
        if index < len(parts) - 1 and not path:
            return False
    return True


def _flag(module: str, rules) -> str | None:
    if module.rsplit(".", 1)[-1].startswith("isolated_worker"):
        return "SH-c"
    return "E5b" if module in rules.SHIMS else None


def _read_export(dsn: str, schema: str, work: Path) -> dict:
    """Export one schema through the product `pg_export` into `work` (bodies on disk only until the caller removes
    it); return per-bucket body digests, the hook status counts and the `codex_harness.` module counts."""
    from codex_harness.delivery.adapters.host_migration import pg_export

    rows_path = work / f"{schema}.jsonl"
    pg_export(dsn, schema, "source", work / f"{schema}.meta.json", rows_path)
    buckets: dict[str, list[str]] = {}
    hooks: Counter = Counter()
    modules: Counter = Counter()
    with open(rows_path, encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            buckets.setdefault(row["bucket"], []).append(_sha(_canonical(row["body"])))
            if row["bucket"] == "hooks":
                status = row["body"].get("status") if isinstance(row["body"], dict) else None
                hooks[status if isinstance(status, str) else "unknown"] += 1
            for text in _strings(row):
                modules.update(MODULE.findall(text))
    rows_path.unlink()
    return {"buckets": buckets, "hooks": hooks, "modules": modules}


def _schema_versions(dsn: str, schema: str) -> list[str]:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    with psycopg.connect(make_conninfo(dsn, options="-c search_path=pg_catalog"), connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        found = conn.execute(sql.SQL("SELECT module, version FROM {}.schema_migrations ORDER BY 1, 2").format(
            sql.Identifier(schema))).fetchall()
    return [f"{module}/{version}" for module, version in found]


def _redis_coverage(socket: Path, forced) -> tuple[dict, dict, list[str]]:
    """Per db: derive the prefixes (SCAN), run the product `redis_inventory`, compare against DBSIZE."""
    import redis
    from codex_harness.composition.canonical_tools import canonical_module
    from codex_harness.delivery.adapters.host_migration import redis_inventory

    dbs, prefixes_out, failures = {}, {}, []
    admin = redis.Redis(unix_socket_path=str(socket), socket_timeout=10)
    names = sorted(admin.info("keyspace"))
    admin.close()
    for name in names:
        db = int(name.removeprefix("db"))
        client = redis.Redis(unix_socket_path=str(socket), db=db, socket_timeout=10)
        dbsize = int(client.dbsize())
        derived = minimal_prefixes(redis_prefix(k.decode("utf-8", "replace")) for k in client.scan_iter(count=1000))
        prefixes = minimal_prefixes(forced) if forced is not None else derived
        inventory = redis_inventory(client, prefixes, canonical_module=canonical_module)
        covered = set(inventory["keys"])
        for prefix in prefixes:
            mine = {k: m for k, m in inventory["keys"].items() if k == prefix or k.startswith(prefix + ":")}
            streams = {k: v for k, v in inventory["streams"].items() if k in mine}
            types = Counter(m["type"] for m in mine.values())
            prefixes_out[f"{name}|{prefix}"] = {
                "keys": len(mine), "streams": len(streams),
                "stream_entries": sum(v["length"] for v in streams.values()),
                "types": _canonical(dict(sorted(types.items()))),
                "digest": _sha(_canonical({"keys": mine, "streams": streams}))}
        uncovered = dbsize - len(covered)
        dbs[name] = {"dbsize": dbsize, "inventoried": len(covered), "uncovered": uncovered,
                     "prefixes": len(prefixes)}
        if uncovered:
            failures.append(f"redis_uncovered:{name}:{uncovered}")
        client.close()
    return dbs, prefixes_out, failures


def redis_facts(socket: Path, prefixes=None) -> tuple[dict, dict, list[str]]:
    """The per-db DBSIZE coverage and the per-prefix key/stream digests of the copy's Redis (read-only; R3 compares them
    before and after every leaf). `prefixes` forces the list (tests only)."""
    return _redis_coverage(Path(socket), prefixes)


def collect(copy, b_release, database: str, *, prefixes=None, bracket=None) -> dict:
    """The D0 facts of `copy` (a `copies.Copy`); `facts["failures"]` is empty exactly when the record passes.

    `bracket` (RH-1b, `bracket.bracket`) is the d0a/d0b verdict; it is recorded as `facts.bracket` and D0 must BE d0a: a
    bracket whose d0a digest is not this copy's catalog fails the record. A skew is declared, not a failure."""
    from codex_harness.delivery.adapters.host_migration import catalog_digest, pg_catalog
    from codex_harness.delivery.domain.host_migration import catalog_schemas

    rules = _import_rules()
    dsn = pg_dsn(copy.pg_socket, database)
    failures: list[str] = []
    catalog = pg_catalog(dsn, database)
    before = catalog_digest(catalog)
    exported = [s for s in catalog_schemas(catalog) if "documents" in catalog["schemas"][s]["relations"]]
    without = [s for s in catalog_schemas(catalog) if s not in exported]
    buckets, schema_totals, knowledge, migrations = {}, {}, {}, {}
    hooks: Counter = Counter()
    modules: Counter = Counter()
    work = Path(tempfile.mkdtemp(prefix="rh-d0-"))
    try:
        work.chmod(0o700)
        for schema in exported:
            if not SCHEMA_IDENT.fullmatch(schema):
                failures.append(f"schema_unexportable:{schema}")
                continue
            try:
                found = _read_export(dsn, schema, work)
            except Exception as error:  # noqa: BLE001 - named in the record, never a body
                failures.append(f"export_failed:{schema}:{type(error).__name__}")
                continue
            buckets[schema] = {b: {"count": len(d), "digest": _digest_of(d)} for b, d in sorted(found["buckets"].items())}
            every = [x for d in found["buckets"].values() for x in d]
            schema_totals[schema] = {"count": len(every), "digest": _digest_of(every)}
            hooks.update(found["hooks"])
            modules.update(found["modules"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for schema in catalog_schemas(catalog):
        relations = catalog["schemas"][schema]["relations"]
        tables = {t: {"count": relations[t]["rows"], "digest": relations[t]["rows_sha256"]}
                  for t in KNOWLEDGE_TABLES if t in relations}
        if tables:
            knowledge[schema] = tables
        if "schema_migrations" in relations:
            migrations[schema] = _schema_versions(dsn, schema)
    redis_dbs, redis_prefixes, redis_failures = _redis_coverage(copy.redis_socket / "redis.sock", prefixes)
    failures += redis_failures
    src = Path(b_release) / "src"
    argv_modules, unresolved = {}, []
    for module, count in sorted(modules.items()):
        resolved = resolve_module(module, src)
        kind = rules.classify(module)[0]
        entry = {"count": count, "resolved": resolved, "class": "shim" if kind == "SHIM" else
                 "target" if kind != "UNCLASSIFIED" else "unclassified"}
        if _flag(module, rules):
            entry["flag"] = _flag(module, rules)
        argv_modules[module] = entry
        if not resolved or entry["class"] == "unclassified":
            unresolved.append(module)
            failures.append(f"argv_module_{'unresolved' if not resolved else 'unclassified'}:{module}")
    after = catalog_digest(pg_catalog(dsn, database))
    if after != before:
        failures.append("copy_changed_during_read")
    if bracket is not None and bracket["catalog_sha256"]["d0a"] != before:
        failures.append("bracket_d0a_is_not_this_copy")
    facts = {"database": database, "b_release": Path(b_release).name, "catalog_sha256": before,
            "catalog_sha256_after": after, "read_only": after == before, "schemas_exported": exported,
            "schemas_without_documents": without, "schema_totals": schema_totals, "buckets": buckets,
            "knowledge": knowledge, "migrations": migrations, "redis_dbs": redis_dbs,
            "redis_prefixes": redis_prefixes,
            "hooks": {"documents_present": bool(exported), "active": hooks.get("active", 0),
                      "by_status": dict(sorted(hooks.items()))},
            "argv_modules": argv_modules, "argv_unresolved": unresolved, "failures": sorted(failures)}
    if bracket is not None:
        facts["bracket"] = bracket
    return facts


def record_d0(copy, b_release, out, *, database: str, prefixes=None, bracket=None, clock=_utc_now) -> dict:
    """Write `out/d0.json` for `copy` and return the record; raise `D0Failed` (after writing it) on any failure.

    `prefixes` replaces the derived Redis prefix list (tests only: it proves the DBSIZE coverage check). `bracket` is the
    d0a/d0b verdict of `bracket.py`, stored under `facts.bracket`."""
    facts = collect(copy, b_release, database, prefixes=prefixes, bracket=bracket)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    document = {"at": clock(), "status": "failed" if facts["failures"] else "ok", "facts": facts}
    write_record(out / "d0.json", document, max_items=MAX_RECORD_ITEMS)
    if facts["failures"]:
        raise D0Failed(document)
    return document
