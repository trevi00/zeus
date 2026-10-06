"""The research package record, its research key and its exemption classes (GAP #20; DESIGN-s10 §14 G20-D1, D3, D4).

Layer: domain
Context: research
Owns: PACKAGE_SCHEMA, STATUSES, SOURCE_KINDS, EXEMPTION_CLASSES, RESEARCH_PACKAGE_MAX_AGE_DAYS, validate_package,
    research_key, exemption, ResearchExemptionRefused
Does not own: the package store (research.application.research_packages), the admission policy
    (research.application.research_package_policy), the intake field that declares an exemption (G20-1b)
Entry points: validate_package, research_key, exemption
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

A declared target addition (no M7 counterpart): the record is NEW data, because no role output carries sources with
opened/available flags (rf-rt-trace (a)). Everything here is pure and reads only the lease it is given.
- `research_key` re-implements the all-copies-equal rule of `intake.application.tickets.ticket_binding`
  (tickets.py:47-72) without its store checks, because a research domain may not import intake's application.
- `exemption` reads an explicit `research_exemption` at the three G20-D4 paths, and derives the two system classes
  from origin markers the producers already stamp (research/application/hooks.py:92-95 `{objective, hook,
  importance}`, research/application/scheduling.py:140-146 `{audit_id, audit_approval, proposal, importance}`), so no
  producer and no existing golden changes (G20-D4 refinement). An origin copied into an implement lease sits under
  `details.plan.origin`.
- An absent exemption means substantial work (CE-9: never an invented admission).
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime

from codex_harness.kernel.errors import ContractError, require

PACKAGE_SCHEMA = "urn:zeus:research-package:1"
STATUSES = ("draft", "accepted", "superseded", "withdrawn", "rejected")
SOURCE_KINDS = ("primary", "case", "counterexample", "test", "inference")
EXEMPTION_CLASSES = ("refactor-same-meaning", "bugfix-with-failing-test", "docs-only", "objective-quality",
                     "unchanged-accepted-procedure", "research-approved-audit")
# INITIAL value, labelled, not measured (S3: design documents decay). It is not in kernel.policy.POLICY because that
# snapshot is emitted by `status` and digested into operation identities (DESIGN-s10 §14 correction).
RESEARCH_PACKAGE_MAX_AGE_DAYS = 30

DOCUMENT_KEYS = frozenset({"key", "version", "status", "supersedes", "superseded_by", "question", "sources",
                           "source_gap", "contradictions", "decision_ref", "recorded_at", "recorded_by"})
SOURCE_KEYS = frozenset({"ref", "title", "retrieved_at", "kind", "applicable_version", "pin_ref", "claim_digest",
                         "opened", "available"})
CONTRADICTION_KEYS = frozenset({"material", "summary_digest", "resolved_ref"})
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ResearchExemptionRefused(ContractError):
    """An exemption declaration that cannot be honoured; `code` is `exemption_conflict` or `exemption_class_unknown`."""

    def __init__(self, code: str):
        super().__init__("research exemption refused: " + code)
        self.code = code


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _digest(value) -> bool:
    return isinstance(value, str) and DIGEST.fullmatch(value) is not None


def _version(value) -> bool:
    return type(value) is int and value >= 1


def validate_package(document) -> dict:
    """G20-D1: the closed record shape; returns a deep copy, or raises ContractError with a stable message."""
    require(isinstance(document, dict), "Research package must be an object")
    unknown = set(document) - DOCUMENT_KEYS
    require(not unknown, "Unknown research package key: " + ", ".join(sorted(map(str, unknown))))
    missing = DOCUMENT_KEYS - set(document)
    require(not missing, "Missing research package key: " + ", ".join(sorted(missing)))
    require(_text(document["key"]), "Invalid research package key")
    require(_version(document["version"]), "Invalid research package version")
    require(document["status"] in STATUSES, "Invalid research package status")
    supersedes = document["supersedes"]
    require(supersedes is None or (_version(supersedes) and supersedes < document["version"]),
            "Supersession needs a prior version")
    linked = document["superseded_by"]
    require(linked is None or (isinstance(linked, dict) and set(linked) == {"key", "version"}
                               and _text(linked["key"]) and _version(linked["version"])),
            "Invalid research package superseded_by")
    require(_text(document["question"]), "Invalid research package question")
    require(isinstance(document["sources"], list), "Invalid research package sources")
    for source in document["sources"]:
        require(isinstance(source, dict) and set(source) == SOURCE_KEYS, "Invalid research package source")
        require(_text(source["ref"]) and _text(source["title"]), "Invalid research package source")
        require(_timestamp(source["retrieved_at"]), "Invalid research package source retrieved_at")
        require(source["kind"] in SOURCE_KINDS, "Invalid research package source kind")
        require(all(source[name] is None or _text(source[name]) for name in ("applicable_version", "pin_ref")),
                "Invalid research package source version")
        require(_digest(source["claim_digest"]), "Invalid research package claim_digest")
        require(type(source["opened"]) is bool and type(source["available"]) is bool,
                "Invalid research package source flags")
    gap = document["source_gap"]
    require(gap is None or (isinstance(gap, dict) and set(gap) == {"searches", "reason"}
                            and isinstance(gap["searches"], list) and bool(gap["searches"])
                            and all(_text(item) for item in gap["searches"]) and _text(gap["reason"])),
            "Invalid research package source_gap")
    require(isinstance(document["contradictions"], list), "Invalid research package contradictions")
    for item in document["contradictions"]:
        require(isinstance(item, dict) and set(item) == CONTRADICTION_KEYS and type(item["material"]) is bool
                and _digest(item["summary_digest"])
                and (item["resolved_ref"] is None or _text(item["resolved_ref"])),
                "Invalid research package contradiction")
    require(document["decision_ref"] is None or _digest(document["decision_ref"]),
            "Invalid research package decision_ref")
    require(_timestamp(document["recorded_at"]), "Invalid research package recorded_at")
    require(_text(document["recorded_by"]), "Invalid research package recorded_by")
    return deepcopy(document)


def _details(lease) -> dict:
    message = lease.get("message") if isinstance(lease, dict) else None
    what = message.get("what") if isinstance(message, dict) else None
    details = what.get("details") if isinstance(what, dict) else None
    return details if isinstance(details, dict) else {}


def _origin(details: dict) -> dict:
    plan = details.get("plan")
    origin = plan.get("origin") if isinstance(plan, dict) else None
    return origin if isinstance(origin, dict) else {}


def research_key(lease) -> str:
    """G20-D3: `ticket:<id>`, else `operation:<id>`, else `correlation:<id>`; stable across retries and plan -> implement."""
    details = _details(lease)
    bindings = []

    def visit(item):
        # tickets.py:47-72 ticket_binding: any depth, every copy must be equal.
        if isinstance(item, dict):
            if "zeus_ticket" in item:
                bindings.append(item["zeus_ticket"])
            for name, child in item.items():
                if name != "zeus_ticket":
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(details)
    if bindings:
        require(all(row == bindings[0] for row in bindings), "Conflicting ticket revisions")
        require(isinstance(bindings[0], dict) and _text(bindings[0].get("id")), "Invalid Zeus ticket binding")
        return "ticket:" + bindings[0]["id"]
    for holder in (details, _origin(details)):
        operation = holder.get("operation")
        if isinstance(operation, dict) and _text(operation.get("id")):
            return "operation:" + operation["id"]
    message = lease.get("message") if isinstance(lease, dict) else None
    correlation = message.get("correlation_id") if isinstance(message, dict) else None
    require(_text(correlation), "Research key unavailable")
    return "correlation:" + correlation


def _explicit(details: dict) -> list:
    operation = details.get("operation")
    copies = [details.get("research_exemption"), _origin(details).get("research_exemption"),
              operation.get("research_exemption") if isinstance(operation, dict) else None]
    declared = []
    for copy in copies:
        if copy is None:
            continue
        # A malformed declaration is refused as an unknown class: nothing is guessed (CE-9).
        if not (isinstance(copy, dict) and set(copy) == {"class", "reason"} and _text(copy["reason"])
                and copy["class"] in EXEMPTION_CLASSES):
            raise ResearchExemptionRefused("exemption_class_unknown")
        declared.append({"class": copy["class"], "reason": copy["reason"]})
    return declared


def _derived(details: dict) -> list:
    derived = []
    for holder in (details, _origin(details)):
        hook = holder.get("hook")
        if isinstance(hook, dict) and _text(hook.get("id")) and "objective" in holder:
            derived.append({"class": "bugfix-with-failing-test", "reason": "hook:" + hook["id"]})
        if _text(holder.get("audit_approval")) and "audit_id" in holder:
            derived.append({"class": "research-approved-audit", "reason": "adopt:" + holder["audit_approval"]})
    return derived


def exemption(lease) -> dict | None:
    """G20-D4: `{class, reason}` when the work is exempt, None when it is substantial; refuses a conflict or unknown class."""
    details = _details(lease)
    explicit, derived = _explicit(details), _derived(details)
    if any(row != explicit[0] for row in explicit) or any(row != derived[0] for row in derived):
        raise ResearchExemptionRefused("exemption_conflict")
    if explicit and derived and explicit[0]["class"] != derived[0]["class"]:
        raise ResearchExemptionRefused("exemption_conflict")
    chosen = (explicit or derived or [None])[0]
    return dict(chosen) if chosen is not None else None
