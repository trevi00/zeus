"""Mutable-binding mapping allowlist and delta receipts (SPEC §6 registry relocation, §8 PG).

This module only *plans and proves* binding changes: it maps a value found at an allowlisted
(bucket, field) through an allowlisted prefix rule and returns a before/after receipt. Applying the
change belongs to the coordinator's target-paused relocation use case; nothing here writes a
database. History/audit buckets are never mappable, and a value that no rule covers is refused
rather than passed through, so an unreviewed Windows path cannot silently reach the target.
"""
from __future__ import annotations

import hashlib
import re

from codex_harness.domain.model import canonical

ALLOWLIST_SCHEMA = "zeus.aibox-mapping-allowlist/1"
DRIVE = re.compile(r"^[A-Za-z]:/")


def normalize(value: str) -> str:
    """Windows paths compare with forward slashes and a lower-case drive letter."""
    text = value.replace("\\", "/")
    return text[0].lower() + text[1:] if DRIVE.match(text) else text


def _prefix_matches(value: str, prefix: str, windows: bool) -> bool:
    return value.casefold().startswith(prefix.casefold()) if windows else value.startswith(prefix)


def validate_allowlist(allowlist: dict) -> list[str]:
    problems = []
    if allowlist.get("schema") != ALLOWLIST_SCHEMA:
        problems.append("schema")
    fields = allowlist.get("fields")
    if not isinstance(fields, list) or not fields:
        problems.append("fields")
        fields = []
    for field in fields:
        if not (isinstance(field, dict) and isinstance(field.get("bucket"), str)
                and isinstance(field.get("path"), list) and field["path"]
                and all(isinstance(p, str) and p for p in field["path"])):
            problems.append(f"field:{field!r}")
    for bucket in allowlist.get("immutable_buckets", []):
        if any(isinstance(f, dict) and f.get("bucket") == bucket for f in fields):
            problems.append(f"immutable_bucket_mapped:{bucket}")
    rules = allowlist.get("prefix_rules")
    if not isinstance(rules, list) or not rules:
        problems.append("prefix_rules")
        rules = []
    for rule in rules:
        source, target = (rule.get("source"), rule.get("target")) if isinstance(rule, dict) else (None, None)
        if not (isinstance(source, str) and isinstance(target, str) and source.endswith("/")
                and target.endswith("/")):
            problems.append(f"rule:{rule!r}")
    sources = [normalize(r["source"]).casefold() for r in rules if isinstance(r, dict)
               and isinstance(r.get("source"), str)]
    if len(sources) != len(set(sources)):
        problems.append("duplicate_source_prefix")
    return problems


def map_value(value: str, rules: list[dict]) -> str:
    """Longest matching prefix wins; `..` after mapping is refused."""
    text = normalize(value)
    windows = bool(DRIVE.match(text))
    candidates = [r for r in rules if _prefix_matches(text, normalize(r["source"]), windows)]
    if not candidates:
        raise LookupError("no_prefix_rule")
    rule = max(candidates, key=lambda r: len(r["source"]))
    rest = text[len(normalize(rule["source"])):]
    if ".." in rest.split("/"):
        raise LookupError("parent_segment")
    return rule["target"] + rest


def reverse_rules(rules: list[dict]) -> list[dict]:
    return [{"source": r["target"], "target": r["source"]} for r in rules]


def _field(body: dict, path: list[str]):
    value = body
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def body_sha(body) -> str:
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def plan_binding_changes(rows: list[dict], allowlist: dict) -> dict:
    """Plan the allowlisted target binding changes for exported rows {bucket, id, body}.

    Returns the delta receipt the coordinator applies and the PG comparison accepts: per changed
    row the before/after canonical body sha256 and each field's before/after value. A mapped
    value must also survive the reverse rules byte-for-byte after normalization (R1 readiness).
    """
    problems = validate_allowlist(allowlist)
    if problems:
        return {"valid": False, "problems": problems, "changes": []}
    fields, rules = allowlist["fields"], allowlist["prefix_rules"]
    immutable = set(allowlist.get("immutable_buckets", []))
    changes, refused = [], []
    for row in rows:
        if row["bucket"] in immutable:
            continue
        after, edits = None, []
        for field in (f for f in fields if f["bucket"] == row["bucket"]):
            value = _field(row["body"], field["path"])
            if value is None:
                continue
            if not isinstance(value, str):
                refused.append({"bucket": row["bucket"], "id": row["id"], "path": field["path"],
                                "reason": "non_string_value"})
                continue
            try:
                mapped = map_value(value, rules)
                if normalize(map_value(mapped, reverse_rules(rules))).casefold() != normalize(value).casefold():
                    raise LookupError("reverse_mismatch")
            except LookupError as exc:
                refused.append({"bucket": row["bucket"], "id": row["id"], "path": field["path"],
                                "reason": str(exc).strip("'")})
                continue
            if mapped == value:
                continue
            after = after or _copy(row["body"])
            target = after
            for part in field["path"][:-1]:
                target = target[part]
            target[field["path"][-1]] = mapped
            edits.append({"path": field["path"], "before": value, "after": mapped})
        if edits:
            changes.append({"bucket": row["bucket"], "id": row["id"], "fields": edits,
                            "before_sha256": body_sha(row["body"]), "after_sha256": body_sha(after)})
    receipt = {"schema": "zeus.aibox-binding-delta/1", "allowlist_sha256": body_sha(allowlist),
               "changes": changes}
    receipt["digest"] = "sha256:" + body_sha(receipt)
    return {"valid": not refused, "problems": [], "refused": refused, "receipt": receipt}


def _copy(value):
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value
