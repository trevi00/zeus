"""The research package store: append-only versions per research key (GAP #20; DESIGN-s10 §14 G20-D2).

Layer: application
Context: research
Owns: bucket research_packages (one row per `(key, version)`, row key `digest({"key", "version"})`), bucket research_exemptions
    (append-only rows per research key, row key `digest({"key", "seq"})`), PackageRefused
Does not own: the admission judgement over a package (research_package_policy), the release of a holding admission when
    a package is accepted (a composition/entry use case, G20-D6), the record shape (research.domain.research_package)
Entry points: ResearchPackages.record, ResearchPackages.accept, ResearchPackages.withdraw, ResearchPackages.current,
    ResearchPackages.exempt, ResearchPackages.unexempt, ResearchPackages.active_exemption
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

A declared target addition (no M7 counterpart). Every method joins the caller's transaction (§2.9).
- `record` only appends: it assigns version = latest + 1 for the key, never overwrites a `(key, version)` row, and
  starts the version as a `draft`. A `supersedes` link marks the earlier version `superseded` with `superseded_by`.
- The only updates to an existing row are the recorded lifecycle transitions: `accept`, `withdraw` and the
  supersession mark. Each appends an event (with its time) to the row's `history`, so the superseded record is KEPT
  (S4 Nygard: "it was the decision, but is no longer").
- `exempt` / `unexempt` append operator-recorded exemption rows `{key, seq, class, reason, recorded_by, recorded_at,
  active}` (G20-D4 revision); the latest row for a key wins, and `active_exemption` reads it (None when absent or
  unexempted). `seq` orders the rows; the row key is `digest({"key", "seq"})`.
- `current` follows `superseded_by` from the latest version to the head; a cycle or a missing target is a typed refusal.
"""
from __future__ import annotations

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest, utcnow
from codex_harness.research.domain.research_package import DIGEST, EXEMPTION_CLASSES, validate_package

BUCKET = "research_packages"
EXEMPTIONS = "research_exemptions"


class PackageRefused(ContractError):
    """A refusal with a stable `reason_code` (for example `package_supersession_cycle`)."""

    def __init__(self, reason_code: str):
        super().__init__("research package refused: " + reason_code)
        self.reason_code = reason_code


def row_key(key: str, version: int) -> str:
    return digest({"key": key, "version": version})


class ResearchPackages:
    def __init__(self, *, clock=None):
        self.clock = clock

    def versions(self, tx, key: str) -> list:
        return sorted((row for row in tx.scan("research_packages") if row.get("key") == key),
                      key=lambda row: row["version"])

    def get(self, tx, key: str, version: int) -> dict | None:
        return tx.get("research_packages", row_key(key, version))

    def record(self, tx, document: dict) -> dict:
        require(isinstance(document, dict) and isinstance(document.get("key"), str), "Invalid research package key")
        known = self.versions(tx, document["key"])
        version = known[-1]["version"] + 1 if known else 1
        at = utcnow(self.clock)
        full = {"version": version, "status": "draft", "superseded_by": None, "decision_ref": None,
                "recorded_at": at, **document}
        require(full["version"] == version and full["status"] == "draft" and full["superseded_by"] is None
                and full["decision_ref"] is None, "A new research package is a draft at the next version")
        full = validate_package(full)
        earlier = full["supersedes"]
        target = None
        if earlier is not None:
            target = self.get(tx, full["key"], earlier)
            if target is None:
                raise PackageRefused("package_supersession_missing")
            require(target["superseded_by"] is None, "Research package version is already superseded")
        row = {**full, "history": [{"event": "recorded", "at": at}]}
        # Append-only: the new `(key, version)` row cannot exist, because the version is latest + 1.
        require(self.get(tx, full["key"], version) is None, "Research package version already recorded")
        tx.put("research_packages", row_key(full["key"], version), row)
        if target is not None:
            target.update(status="superseded", superseded_by={"key": full["key"], "version": version})
            target["history"].append({"event": "superseded", "at": at, "by": version})
            tx.put("research_packages", row_key(full["key"], earlier), target)
        return row

    def _transition(self, tx, key: str, version: int, allowed: tuple, status: str, event: dict, **fields) -> dict:
        row = self.get(tx, key, version)
        if row is None:
            raise PackageRefused("package_missing")
        require(row["status"] in allowed, "Research package cannot move from " + row["status"] + " to " + status)
        at = utcnow(self.clock)
        row.update(status=status, **fields)
        row["history"].append({"at": at, **event})
        validate_package({name: value for name, value in row.items() if name != "history"})
        tx.put("research_packages", row_key(key, version), row)
        return row

    def accept(self, tx, key: str, version: int, decision_ref: str) -> dict:
        require(isinstance(decision_ref, str) and DIGEST.fullmatch(decision_ref) is not None,
                "Invalid research package decision_ref")
        return self._transition(tx, key, version, ("draft",), "accepted",
                                {"event": "accepted", "decision_ref": decision_ref}, decision_ref=decision_ref)

    def withdraw(self, tx, key: str, version: int, reason: str) -> dict:
        require(isinstance(reason, str) and bool(reason.strip()), "A withdrawal must name its reason")
        return self._transition(tx, key, version, ("draft", "accepted"), "withdrawn",
                                {"event": "withdrawn", "reason": reason})

    def current(self, tx, key: str) -> dict | None:
        """The head of the supersession chain that starts at the latest version of `key`."""
        known = self.versions(tx, key)
        if not known:
            return None
        row, seen = known[-1], set()
        while row["superseded_by"] is not None:
            link = row["superseded_by"]
            marker = (row["key"], row["version"])
            if marker in seen:
                raise PackageRefused("package_supersession_cycle")
            seen.add(marker)
            row = self.get(tx, link["key"], link["version"])
            if row is None:
                raise PackageRefused("package_supersession_missing")
        return row

    def _exemption_rows(self, tx, key: str) -> list:
        return sorted((row for row in tx.scan(EXEMPTIONS) if row.get("key") == key), key=lambda row: row["seq"])

    def _append_exemption(self, tx, key: str, cls: str, reason: str, recorded_by: str, active: bool) -> dict:
        require(isinstance(recorded_by, str) and bool(recorded_by.strip()), "A research exemption must name its recorder")
        rows = self._exemption_rows(tx, key)
        seq = rows[-1]["seq"] + 1 if rows else 1
        row = {"key": key, "seq": seq, "class": cls, "reason": reason, "recorded_by": recorded_by,
               "recorded_at": utcnow(self.clock), "active": active}
        tx.put(EXEMPTIONS, digest({"key": key, "seq": seq}), row)
        return row

    def exempt(self, tx, key: str, cls: str, reason: str, recorded_by: str) -> dict:
        """G20-D4 revision: declare `key` exempt from research-first admission; `cls` is one of EXEMPTION_CLASSES."""
        require(isinstance(key, str) and bool(key.strip()), "Invalid research package key")
        require(cls in EXEMPTION_CLASSES, "Unknown research exemption class")
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 500, "A research exemption must name its reason")
        return self._append_exemption(tx, key, cls, reason, recorded_by, True)

    def unexempt(self, tx, key: str, reason: str, recorded_by: str) -> dict:
        """Withdraw the active exemption of `key`; the history stays."""
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 500, "A research exemption must name its reason")
        active = self.active_exemption(tx, key)
        if active is None:
            raise PackageRefused("exemption_missing")
        return self._append_exemption(tx, key, active["class"], reason, recorded_by, False)

    def active_exemption(self, tx, key: str) -> dict | None:
        rows = self._exemption_rows(tx, key)
        return rows[-1] if rows and rows[-1]["active"] else None
