"""The one usage-accounting policy over a `budget` dictionary (research program001 batch008).

Two explicit operator modes. `finite` is the legacy shape `{"per_host", "total"}`: positive
integer ceilings the machine ledger enforces; its canonical form is byte-for-byte the old one, so
every existing manifest, fleet configuration, program and grant keeps its digest. `subscription`
adds `"mode": "subscription"`; the two numbers stay as retained migration metadata and are NOT
ceilings, NOT a provider allowance and NOT a claim about remaining subscription usage. In that
mode every call is still reserved and recorded, but the lifetime count never refuses a start.
Unknown modes and extra fields are refused. Deadlines, start caps, cycle and adoption caps,
concurrency and ownership are other controls and are untouched by this module.

Nothing here detects a billing plan, infers quota from tokens or invents a reset time.
"""
from __future__ import annotations

from codex_harness.domain.model import ContractError

FINITE, SUBSCRIPTION = "finite", "subscription"
MODES = (FINITE, SUBSCRIPTION)
NUMERIC_FIELDS = frozenset({"per_host", "total"})
FIELDS = NUMERIC_FIELDS | {"mode"}
COUNT_FIELDS = ("this_host", "all_hosts")


class UsagePolicyError(ContractError):
    """`reason_code` is `fields` (unknown or missing keys) or `invalid` (types, values, mode)."""

    def __init__(self, reason_code: str):
        super().__init__("usage policy refused: " + reason_code)
        self.reason_code = reason_code


def _integer(value) -> bool:
    return type(value) is int  # bool is refused: its type is bool, not int


def validate_budget(budget) -> dict:
    """Strict validation; returns the canonical copy. The finite form never carries a mode key;
    an explicit `mode: finite` canonicalizes to that same legacy form."""
    if not isinstance(budget, dict):
        raise UsagePolicyError("invalid")
    if not (NUMERIC_FIELDS <= set(budget) <= FIELDS):
        raise UsagePolicyError("fields")
    per_host, total = budget["per_host"], budget["total"]
    if not (_integer(per_host) and _integer(total) and per_host > 0 and total >= per_host):
        raise UsagePolicyError("invalid")
    mode = budget.get("mode", FINITE)
    if type(mode) is not str or mode not in MODES:
        raise UsagePolicyError("invalid")
    canonical = {"per_host": per_host, "total": total}
    if mode == SUBSCRIPTION:
        canonical["mode"] = SUBSCRIPTION
    return canonical


def accounting_mode(budget) -> str:
    """The mode a canonical budget is bound to; unknown shapes are refused, never guessed."""
    if not isinstance(budget, dict):
        raise UsagePolicyError("invalid")
    mode = budget.get("mode", FINITE)
    if type(mode) is not str or mode not in MODES:
        raise UsagePolicyError("invalid")
    return mode


def readable_counts(counts) -> bool:
    """A ledger reading usable for admission: integer host/all counts. In finite mode unreadable
    slots are already counted as taken; the count itself must still be an observed integer."""
    return isinstance(counts, dict) and all(_integer(counts.get(k)) for k in COUNT_FIELDS)


def headroom(budget: dict, counts, required: int = 1) -> dict:
    """Admission headroom for `required` starts as `{"remaining", "ok", "required"}`.

    finite: the smaller of the per-host and total remainders; `ok` when it covers `required`.
    subscription: `remaining` is None (no ceiling, no allowance claim) and `ok` is True only when
    the ledger reading is readable with no unreadable slot: the record is the only control left,
    so a damaged ledger refuses instead of counting conservatively. `required` is shape
    information (how many starts one unit of work makes), never free provider quota.
    """
    mode = accounting_mode(budget)
    if not readable_counts(counts):
        return {"remaining": None, "ok": False, "required": required}
    if mode == FINITE:
        remaining = min(budget["per_host"] - counts["this_host"], budget["total"] - counts["all_hosts"])
        return {"remaining": remaining, "ok": remaining >= required, "required": required}
    unreadable = counts.get("unreadable")
    return {"remaining": None, "ok": _integer(unreadable) and unreadable == 0, "required": required}


def exhausted(budget: dict, counts) -> bool:
    """Fleet admission reading: no room for even one start under this mode."""
    return not headroom(budget, counts, 1)["ok"]


def validate_grant(prior: dict, requested) -> dict:
    """An explicit operator grant over the effective budget: numbers valid and nondecreasing
    (never a reset, in either mode) and something must change: a numeric increase or a mode
    change with unchanged numbers. Same mode with the same numbers is no grant."""
    new = validate_budget(requested)
    if new["per_host"] < prior["per_host"] or new["total"] < prior["total"]:
        raise UsagePolicyError("decrease")
    if new == validate_budget(prior):
        raise UsagePolicyError("no_change")
    return new


__all__ = ["FIELDS", "FINITE", "MODES", "NUMERIC_FIELDS", "SUBSCRIPTION", "UsagePolicyError", "accounting_mode",
           "exhausted", "headroom", "readable_counts", "validate_budget", "validate_grant"]
