"""The ledger that limits real provider-call experiments, so the limit cannot be argued with.

A ceiling counted from whatever the caller named, in whatever directory the caller chose, is not a
ceiling: renaming the run or pointing it elsewhere starts the count at zero. This ledger takes both
away. It lives at one fixed place per machine, it identifies the host from the machine's own facts
rather than from a flag, and a slot is taken *before* a process can start, under a lock, so two
runs cannot both see the last slot free.

A slot that was reserved and never settled stays counted. An experiment that was interrupted may
well have reached the provider, and the conservative reading is the only safe one: the budget is
about what may already have been spent, not about what was tidily recorded.

`label` and output paths stay what they are, names for people and places for artifacts. They have
no authority here.
"""
from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from codex_harness.domain.model import ContractError, canonical, digest, require

LEDGER_TIMEOUT = 20.0
STATUSES = ("reserved", "used")


def host_identity() -> dict:
    """The machine, from the machine. No value here comes from an argument the caller chose."""
    facts = {"system": platform.system(), "machine": platform.machine(),
             "node_digest": digest(platform.node())}
    return {**facts, "id": digest(facts)}


def default_root() -> Path:
    """One place per machine, outside any repository, so a second checkout is the same budget."""
    return Path.home() / ".zeus" / "claude-call-budget"


class CallBudget:
    """Slots for real provider calls on this host. The policy supplies the ceilings."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else default_root()
        self.host = host_identity()

    # ---- reading ---------------------------------------------------------------------------------
    def _slot_files(self) -> list[Path]:
        directory = self.root / "slots"
        return sorted(directory.glob("*.json")) if directory.is_dir() else []

    def slots(self) -> list[dict]:
        rows = []
        for path in self._slot_files():
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                # An unreadable slot is a slot that was taken; it is never read as free space.
                rows.append({"id": path.stem, "host": None, "status": "reserved",
                             "unreadable": type(exc).__name__})
                continue
            rows.append(row)
        return rows

    def counts(self) -> dict:
        rows = self.slots()
        mine = [row for row in rows if row.get("host") in (None, self.host["id"])]
        return {"host": self.host["id"], "this_host": len(mine), "all_hosts": len(rows),
                "unreadable": sum(1 for row in rows if row.get("unreadable")),
                "note": "a slot that was reserved and never settled still counts"}

    # ---- taking a slot ---------------------------------------------------------------------------
    def reserve(self, *, per_host: int, total: int, purpose: str, provider: str, model: str) -> dict:
        """Take one slot before anything can spawn, or refuse. Raises ContractError when full."""
        require(type(per_host) is int and per_host > 0, "The per-host ceiling must be a positive count")
        require(type(total) is int and total >= per_host, "The overall ceiling cannot be below the per-host one")
        require(type(purpose) is str and bool(purpose), "A reserved call slot names its purpose")
        (self.root / "slots").mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.root / "budget.lock"), is_singleton=True)
        try:
            lock.acquire(timeout=LEDGER_TIMEOUT)
        except (Timeout, OSError) as exc:
            raise ContractError("The call budget ledger is busy; no slot was taken") from exc
        try:
            counts = self.counts()
            if counts["this_host"] >= per_host:
                raise ContractError(
                    f"{counts['this_host']} real calls are already recorded for this host "
                    f"(ceiling {per_host}); the ledger is at {self.root}")
            if counts["all_hosts"] >= total:
                raise ContractError(
                    f"{counts['all_hosts']} real calls are already recorded across hosts "
                    f"(ceiling {total}); the ledger is at {self.root}")
            slot = {"id": uuid4().hex, "host": self.host["id"], "host_facts": self.host,
                    "status": "reserved", "purpose": purpose, "provider": provider, "model": model,
                    "per_host_ceiling": per_host, "total_ceiling": total,
                    "counts_at_reservation": counts,
                    "reserved_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()}
            path = self.root / "slots" / (slot["id"] + ".json")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical(slot) + "\n")
            return slot
        finally:
            lock.release()

    def settle(self, slot_id: str, *, outcome: str, detail: dict | None = None) -> dict:
        """Record what the reserved slot turned into. It was already counted either way."""
        require(type(slot_id) is str and bool(slot_id), "Settling needs a slot id")
        path = self.root / "slots" / (slot_id + ".json")
        try:
            slot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError("Unknown call budget slot") from exc
        slot.update(status="used", outcome=outcome,
                    settled_at=datetime.now(timezone.utc).isoformat(), detail=detail or {})
        temporary = path.with_suffix(".tmp")
        temporary.write_text(canonical(slot) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
        return slot

    def summary(self) -> dict:
        return {"ledger": str(self.root), "host": self.host, **self.counts(),
                "slots": [{k: row.get(k) for k in ("id", "status", "purpose", "outcome", "reserved_at")}
                          for row in self.slots()]}
