"""Reference driver: the invocation ledger and the call budget (REBUILD-DESIGN-v2 §5.3 S4, RESEARCH-S4 D4/D5).

Scenario family `execution.ledger`. M7 `InvocationLedger` on `MemoryStore` and M7 `CallBudget` on a
disposable directory, with a fake clock and deterministic ids. No provider, no process. Each step
reports the returned row's non-identity fields or the refusal (exception type and message).

Invocation ledger steps: reserve; a second open reservation of the same attempt (refused); settle;
the identical settle again (idempotent); a conflicting settle (refused); a second invocation of the
attempt; a new attempt supersedes an unsettled reservation (`unsettled_unknown`, usage unknown);
capacity refusal; a dead execution's reservation reclaimed; abandon; the summary counts.
Call budget steps: finite ceilings per host and total; subscription mode never refuses on counts;
an unreadable slot counts as taken and refuses subscription accounting; settle; unknown slot.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402

from codex_harness.adapters.call_budget import CallBudget  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import invocation_ledger  # noqa: E402,F401
from codex_harness.application.invocation_ledger import InvocationLedger  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
ROW_FIELDS = ("status", "outcome", "usage", "reason", "invocation", "generation", "attempt", "stage",
              "owner", "request", "budget_seconds", "within_budget", "elapsed_seconds", "evidence_ref")


def attempt(call):
    try:
        value = call()
    except Exception as exc:  # the refusal itself is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)}
    if isinstance(value, dict):
        return {k: value.get(k) for k in ROW_FIELDS if k in value}
    return value


def task_row(tx, task_id, generation, attempt_no, owner, status="running", until="2026-01-01T01:00:00+00:00"):
    tx.put("tasks", task_id, {"id": task_id, "status": status, "generation": generation,
                              "attempt": attempt_no, "lease_owner": owner, "lease_until": until})


def ledger_steps() -> dict:
    store = MemoryStore()
    ledger = InvocationLedger(store, capacity=2)
    lease = {"id": "t1", "generation": 1, "attempt": 1, "lease_owner": "o1"}
    with store.transaction() as tx:
        task_row(tx, "t1", 1, 1, "o1")
    out = {}
    first = ledger.reserve(lease, request={"model": "m"}, budget_seconds=60, stage="final")
    out["reserve"] = attempt(lambda: first)
    out["reserve_same_attempt_open"] = attempt(lambda: ledger.reserve(lease, request={}, budget_seconds=60))
    CLOCK.advance(5)
    usage = {"source": "thread/tokenUsage/updated", "total_tokens": 10, "last_tokens": 10}
    out["settle"] = attempt(lambda: ledger.settle(first["id"], outcome="accepted", usage=usage,
                                                  evidence_ref="fixture:e"))
    out["settle_identical_again"] = attempt(lambda: ledger.settle(first["id"], outcome="accepted", usage=usage,
                                                                  evidence_ref="fixture:e"))
    out["settle_conflicting"] = attempt(lambda: ledger.settle(first["id"], outcome="provider_failure",
                                                              usage=usage))
    out["settle_unnamed_usage_source"] = attempt(lambda: ledger.settle(
        first["id"], outcome="accepted", usage={"source": "provider", "total_tokens": 1}))
    out["settle_unknown_usage_with_count"] = attempt(lambda: ledger.settle(
        first["id"], outcome="accepted", usage={"source": "unknown", "total_tokens": 3}))
    out["settle_bad_outcome"] = attempt(lambda: ledger.settle(first["id"], outcome="nonsense", usage=usage))
    second = ledger.reserve(lease, request={}, budget_seconds=1)
    out["reserve_second_invocation"] = attempt(lambda: second)
    CLOCK.advance(5)
    out["settle_over_budget"] = attempt(lambda: ledger.settle(
        second["id"], outcome="interrupted", usage={"source": "unknown", "total_tokens": None,
                                                    "last_tokens": None}))
    open_third = ledger.reserve(lease, request={}, budget_seconds=60)
    lease2 = {"id": "t1", "generation": 2, "attempt": 2, "lease_owner": "o2"}
    with store.transaction() as tx:
        task_row(tx, "t1", 2, 2, "o2")
    out["reserve_new_attempt"] = attempt(lambda: ledger.reserve(lease2, request={}, budget_seconds=60))
    with store.transaction() as tx:
        out["superseded_row"] = attempt(lambda: tx.get("invocation_reservations", open_third["id"]))
        task_row(tx, "t2", 1, 1, "p1")
        task_row(tx, "t3", 1, 1, "q1")
    out["reserve_t2"] = attempt(lambda: ledger.reserve({"id": "t2", "generation": 1, "attempt": 1,
                                                        "lease_owner": "p1"}, request={}, budget_seconds=60))
    out["reserve_t3_capacity"] = attempt(lambda: ledger.reserve({"id": "t3", "generation": 1, "attempt": 1,
                                                                 "lease_owner": "q1"}, request={},
                                                                budget_seconds=60))
    with store.transaction() as tx:
        task_row(tx, "t2", 1, 1, "p1", status="failed")
    out["reclaim"] = len(ledger.reclaim())
    out["reserve_t3_after_reclaim"] = attempt(lambda: ledger.reserve(
        {"id": "t3", "generation": 1, "attempt": 1, "lease_owner": "q1"}, request={}, budget_seconds=60))
    with store.transaction() as tx:
        rows = sorted(tx.scan("invocation_reservations"), key=lambda r: (r["task_id"], r["generation"],
                                                                         r["attempt"], r["invocation"]))
    out["reasons"] = [[r["task_id"], r["status"], r.get("reason")] for r in rows]
    t3 = next(r for r in rows if r["task_id"] == "t3")
    out["abandon"] = attempt(lambda: ledger.abandon(t3["id"], "fixture"))
    out["abandon_again"] = attempt(lambda: ledger.abandon(t3["id"], "fixture"))
    out["abandon_no_reason"] = attempt(lambda: ledger.abandon(t3["id"], ""))
    out["bad_lease"] = attempt(lambda: ledger.reserve({"id": "t9"}, request={}, budget_seconds=60))
    out["bad_budget"] = attempt(lambda: ledger.reserve(lease2, request={}, budget_seconds=0))
    summary = ledger.summary()
    out["summary"] = {k: summary[k] for k in ("reservations", "by_status", "by_outcome", "usage_unknown",
                                              "measured_total_tokens", "note")}
    out["reservation_key_is_tuple_digest"] = first["id"] == invocation_ledger.reservation_key(
        "tasks", "t1", 1, 1, 1)
    return out


def budget_steps(root: Path) -> dict:
    budget = CallBudget(root / "budget")
    out = {}
    args = dict(purpose="fixture", provider="claude", model="m")
    out["first"] = attempt(lambda: {k: v for k, v in budget.reserve(per_host=2, total=3, **args).items()
                                    if k in ("status", "purpose", "accounting_mode", "per_host_ceiling",
                                             "total_ceiling")})
    slot = budget.slots()[0]["id"]
    out["second"] = attempt(lambda: budget.reserve(per_host=2, total=3, **args)["status"])
    out["third_per_host_refused"] = attempt(lambda: budget.reserve(per_host=2, total=3, **args))
    out["subscription_not_refused"] = attempt(lambda: budget.reserve(per_host=2, total=3, mode="subscription",
                                                                     **args)["accounting_mode"])
    out["settle"] = attempt(lambda: {k: v for k, v in budget.settle(slot, outcome="ok").items()
                                     if k in ("status", "outcome", "detail")})
    out["settle_unknown"] = attempt(lambda: budget.settle("missing", outcome="ok"))
    (root / "budget" / "slots" / "broken.json").write_text("{", encoding="utf-8")
    out["counts_with_unreadable"] = {k: v for k, v in budget.counts().items() if k != "host"}
    out["subscription_unreadable_refused"] = attempt(lambda: budget.reserve(per_host=9, total=9,
                                                                            mode="subscription", **args))
    out["unknown_mode"] = attempt(lambda: budget.reserve(per_host=1, total=1, mode="x", **args))
    out["total_below_per_host"] = attempt(lambda: budget.reserve(per_host=2, total=1, **args))
    out["no_purpose"] = attempt(lambda: budget.reserve(per_host=1, total=1, purpose="", provider="p",
                                                       model="m"))
    return out


def scrub(value, root: str):
    """Rewrite the disposable directory to a symbolic root (mask kind 2: host-specific absolute paths)."""
    if isinstance(value, dict):
        return {k: scrub(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, root) for v in value]
    if isinstance(value, str):
        return value.replace(root, "<BUDGET_ROOT>")
    return value


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zeus-s4-ledger-") as raw:
        out = {"invocation_ledger": ledger_steps(), "call_budget": scrub(budget_steps(Path(raw)), raw)}
    driver.finish("reference", "execution.ledger", out)


if __name__ == "__main__":
    main()
