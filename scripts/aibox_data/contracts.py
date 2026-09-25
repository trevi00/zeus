"""PostgreSQL and Redis inventory contracts and source/target comparison (SPEC §8, A2).

The inventories are produced by a read-only source export (see RUNBOOK.md "Source-export
requirements") and by the same export against the paused target. This module never connects to a
server; it validates the exported documents and compares them.

PG rows are the `documents` table of each Zeus schema ({bucket, id, body}); a row hash is the
sha256 of the canonical JSON body (codex_harness.domain.model.canonical), so jsonb text formatting
never affects identity. A bucket digest is the sha256 over its sorted "id<TAB>row-hash" lines.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from codex_harness.domain.model import canonical

PG_SCHEMA = "zeus.aibox-pg-inventory/1"
REDIS_SCHEMA = "zeus.aibox-redis-inventory/1"
STREAM_ID = re.compile(r"\d+-\d+")
HEX64 = re.compile(r"[0-9a-f]{64}")
IDENT = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def row_hash(body) -> str:
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def bucket_digest(rows: dict[str, str]) -> str:
    lines = "".join(f"{row_id}\t{rows[row_id]}\n" for row_id in sorted(rows))
    return hashlib.sha256(lines.encode()).hexdigest()


def pg_schema_from_export(jsonl: str | Path) -> dict:
    """Bucket counts, digests and row hashes from one schema's `documents` JSONL export."""
    buckets: dict[str, dict[str, str]] = {}
    with open(jsonl, encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not (isinstance(row, dict) and isinstance(row.get("bucket"), str)
                    and isinstance(row.get("id"), str) and "body" in row):
                raise ValueError(f"line {number}: expected {{bucket, id, body}}")
            rows = buckets.setdefault(row["bucket"], {})
            if row["id"] in rows:
                raise ValueError(f"line {number}: duplicate {row['bucket']}/{row['id']}")
            rows[row["id"]] = row_hash(row["body"])
    return {name: {"count": len(rows), "digest": bucket_digest(rows), "rows": rows}
            for name, rows in sorted(buckets.items())}


def _version_major(value) -> int | None:
    return value // 10000 if type(value) is int and value >= 100000 else None


def validate_pg(inventory: dict, role: str) -> list[str]:
    """`role` is "source" or "target". The Windows source keeps its control ledger in `public`
    (source-inventory.json, 2026-09-25), so an explicitly inventoried source `public` schema is
    valid; a target schema named `public` is refused because lane/control connections must never
    fall back to it (SPEC §8)."""
    if role not in {"source", "target"}:
        raise ValueError("role must be source or target")
    problems = []
    if inventory.get("schema") != PG_SCHEMA:
        problems.append("schema")
    if _version_major(inventory.get("server_version_num")) is None:
        problems.append("server_version_num")
    if not isinstance(inventory.get("extensions"), dict):
        problems.append("extensions")
    schemas = inventory.get("schemas")
    if not isinstance(schemas, dict) or not schemas:
        return problems + ["schemas"]
    for name, schema in schemas.items():
        if (name == "public" and role == "target") or not IDENT.fullmatch(name):
            problems.append(f"schema_name:{name}")
        if not isinstance(schema, dict):
            problems.append(f"schema_body:{name}")
            continue
        for key in ("tables", "sequences", "buckets"):
            if not isinstance(schema.get(key), (list if key == "tables" else dict)):
                problems.append(f"{name}.{key}")
        if "documents" not in (schema.get("tables") or []):
            problems.append(f"{name}.documents_missing")
        for bucket, body in (schema.get("buckets") or {}).items():
            rows = body.get("rows") if isinstance(body, dict) else None
            if not (isinstance(rows, dict) and all(HEX64.fullmatch(h or "") for h in rows.values())):
                problems.append(f"{name}.{bucket}.rows")
            elif body.get("count") != len(rows) or body.get("digest") != bucket_digest(rows):
                problems.append(f"{name}.{bucket}.digest")
    return problems


def compare_pg(source: dict, target: dict, schema_map: dict[str, str], delta: dict | None = None) -> dict:
    """A2 PG row: same major/extensions, a total injective schema map, identical rows except the
    changes listed in the binding delta receipt, whose before/after hashes must both hold."""
    problems = ([f"source:{p}" for p in validate_pg(source, "source")]
                + [f"target:{p}" for p in validate_pg(target, "target")])
    if problems:
        return {"match": False, "problems": problems}
    if _version_major(source["server_version_num"]) != _version_major(target["server_version_num"]):
        problems.append("server_major_mismatch")
    if source["extensions"] != target["extensions"]:
        problems.append("extensions_mismatch")
    if set(schema_map) != set(source["schemas"]):
        problems.append("schema_map_not_total")
    if len(set(schema_map.values())) != len(schema_map) or "public" in schema_map.values():
        problems.append("schema_map_not_injective_or_public")
    changes = {(c["bucket"], c["id"]): c for c in (delta or {}).get("changes", [])}
    used, rows = set(), []
    for src_name, tgt_name in sorted(schema_map.items()):
        src, tgt = source["schemas"].get(src_name), target["schemas"].get(tgt_name)
        if src is None or tgt is None:
            problems.append(f"schema_missing:{src_name}->{tgt_name}")
            continue
        if sorted(src["tables"]) != sorted(tgt["tables"]):
            problems.append(f"tables_mismatch:{src_name}")
        for seq, value in src["sequences"].items():
            if type(tgt["sequences"].get(seq)) is not int or tgt["sequences"][seq] < value:
                problems.append(f"sequence_behind:{src_name}.{seq}")
        for bucket in sorted(set(src["buckets"]) | set(tgt["buckets"])):
            want = src["buckets"].get(bucket, {}).get("rows", {})
            have = tgt["buckets"].get(bucket, {}).get("rows", {})
            for row_id in sorted(set(want) | set(have)):
                change = changes.get((bucket, row_id))
                if change:
                    used.add((bucket, row_id))
                    if want.get(row_id) != change["before_sha256"] or have.get(row_id) != change["after_sha256"]:
                        rows.append({"schema": src_name, "bucket": bucket, "id": row_id,
                                     "problem": "delta_hash_mismatch"})
                elif row_id not in have:
                    rows.append({"schema": src_name, "bucket": bucket, "id": row_id, "problem": "missing"})
                elif row_id not in want:
                    rows.append({"schema": src_name, "bucket": bucket, "id": row_id, "problem": "extra"})
                elif want[row_id] != have[row_id]:
                    rows.append({"schema": src_name, "bucket": bucket, "id": row_id, "problem": "changed"})
    unused = sorted(set(changes) - used)
    if unused:
        problems.append(f"delta_rows_not_found:{len(unused)}")
    return {"match": not problems and not rows, "problems": problems, "rows": rows[:200],
            "row_problem_count": len(rows)}


def stream_entries_sha256(entries: list) -> str:
    """The E4 `entries_sha256`: canonical JSON of the XRANGE - + result as [[id, {field: value}]]."""
    return hashlib.sha256(canonical([[entry_id, dict(fields)] for entry_id, fields in entries]).encode()).hexdigest()


def _sid(value: str) -> tuple[int, int]:
    ms, seq = value.split("-")
    return int(ms), int(seq)


def validate_redis(inventory: dict) -> list[str]:
    problems = []
    if inventory.get("schema") != REDIS_SCHEMA:
        problems.append("schema")
    if type(inventory.get("captured_at_ms")) is not int:
        problems.append("captured_at_ms")
    prefixes = inventory.get("namespace_prefixes")
    if not (isinstance(prefixes, list) and prefixes and all(isinstance(p, str) and p for p in prefixes)):
        return problems + ["namespace_prefixes"]
    keys, streams = inventory.get("keys"), inventory.get("streams")
    if not isinstance(keys, dict) or not isinstance(streams, dict):
        return problems + ["keys_or_streams"]
    for key, meta in keys.items():
        if not any(key.startswith(p + ":") or key == p for p in prefixes):
            problems.append(f"key_outside_allowlist:{key}")
        if not isinstance(meta, dict) or not isinstance(meta.get("type"), str):
            problems.append(f"key_meta:{key}")
            continue
        expire = meta.get("expire_at_ms")
        if expire is not None and type(expire) is not int:
            problems.append(f"expire_at_ms:{key}")
        if meta["type"] == "stream" and key not in streams:
            problems.append(f"stream_missing_detail:{key}")
        if meta["type"] != "stream" and not HEX64.fullmatch(str(meta.get("dump_sha256", ""))):
            problems.append(f"dump_sha256:{key}")
    for key, stream in streams.items():
        try:
            last = _sid(stream["last_generated_id"])
            if type(stream["length"]) is not int or not HEX64.fullmatch(stream["entries_sha256"]):
                raise ValueError
            for name, group in stream["groups"].items():
                delivered = _sid(group["last_delivered_id"])
                if delivered > last:
                    problems.append(f"group_ahead_of_stream:{key}/{name}")
                pending = group["pending"]
                if sum(group["consumers"].values()) != len(pending):
                    problems.append(f"pel_consumer_count:{key}/{name}")
                for item in pending:
                    if not STREAM_ID.fullmatch(item["id"]) or _sid(item["id"]) > delivered:
                        problems.append(f"pel_id:{key}/{name}/{item['id']}")
                    if item["consumer"] not in group["consumers"]:
                        problems.append(f"pel_consumer:{key}/{name}/{item['id']}")
        except (KeyError, TypeError, ValueError, AttributeError):
            problems.append(f"stream_shape:{key}")
    return problems


def _pel(group: dict) -> list[tuple]:
    return sorted((p["id"], p["consumer"], p.get("deliveries")) for p in group["pending"])


def compare_redis(source: dict, target: dict, tolerance_ms: int = 0) -> dict:
    """A2 Redis row: every allowlisted key restored with the same absolute expiry (never extended),
    streams with the same entries/last-generated id, groups, consumers and complete PEL. Keys
    whose absolute expiry passed before the target capture are reported as expired, not missing."""
    problems = [f"source:{p}" for p in validate_redis(source)] + [f"target:{p}" for p in validate_redis(target)]
    if problems:
        return {"match": False, "problems": problems}
    if source["namespace_prefixes"] != target["namespace_prefixes"]:
        problems.append("namespace_prefixes_changed")
    expired, diffs = [], []
    for key, meta in sorted(source["keys"].items()):
        other = target["keys"].get(key)
        expire = meta.get("expire_at_ms")
        if other is None:
            if expire is not None and expire <= target["captured_at_ms"]:
                expired.append(key)
            else:
                diffs.append({"key": key, "problem": "missing"})
            continue
        if other["type"] != meta["type"]:
            diffs.append({"key": key, "problem": "type"})
        if meta["type"] != "stream" and other.get("dump_sha256") != meta.get("dump_sha256"):
            diffs.append({"key": key, "problem": "value"})
        target_expire = other.get("expire_at_ms")
        if (expire is None) != (target_expire is None):
            diffs.append({"key": key, "problem": "persistence_changed"})
        elif expire is not None and target_expire > expire + tolerance_ms:
            diffs.append({"key": key, "problem": "ttl_extended"})
        elif expire is not None and target_expire < expire - tolerance_ms:
            diffs.append({"key": key, "problem": "ttl_shortened"})
    diffs += [{"key": key, "problem": "extra"} for key in sorted(set(target["keys"]) - set(source["keys"]))]
    for key, stream in sorted(source["streams"].items()):
        other = target["streams"].get(key)
        if other is None:
            if key not in expired:
                diffs.append({"key": key, "problem": "stream_missing"})
            continue
        for field in ("length", "last_generated_id", "entries_sha256"):
            if stream[field] != other[field]:
                diffs.append({"key": key, "problem": f"stream_{field}"})
        if set(stream["groups"]) != set(other["groups"]):
            diffs.append({"key": key, "problem": "groups"})
        for name, group in stream["groups"].items():
            tgt = other["groups"].get(name)
            if tgt is None:
                continue
            if group["last_delivered_id"] != tgt["last_delivered_id"]:
                diffs.append({"key": key, "group": name, "problem": "last_delivered_id"})
            if group["consumers"] != tgt["consumers"]:
                diffs.append({"key": key, "group": name, "problem": "consumers"})
            if _pel(group) != _pel(tgt):
                diffs.append({"key": key, "group": name,
                              "problem": "pel_dropped" if len(tgt["pending"]) < len(group["pending"])
                              else "pel_changed"})
    return {"match": not problems and not diffs, "problems": problems, "diffs": diffs,
            "expired_during_downtime": expired}


def check_pel_owners(inventory: dict, owners: dict[str, dict]) -> dict:
    """SPEC §8: PEL is empty or every pending entry maps to a PG effect/owner record.

    `owners` maps "<stream>/<group>/<entry-id>" to the exported PG record that owns it."""
    unowned = []
    for key, stream in sorted(inventory["streams"].items()):
        for name, group in sorted(stream["groups"].items()):
            for item in group["pending"]:
                ref = f"{key}/{name}/{item['id']}"
                owner = owners.get(ref)
                if not (isinstance(owner, dict) and owner.get("bucket") and owner.get("id")):
                    unowned.append(ref)
    return {"pending_total": sum(len(g["pending"]) for s in inventory["streams"].values()
                                 for g in s["groups"].values()),
            "unowned": unowned, "valid": not unowned}
