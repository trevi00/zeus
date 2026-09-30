"""The pinned policy registry and the one eligibility guard.

Layer: application
Context: coordination
Owns: bucket continuation_policies
Does not own: the intent rows (IntentStore), grants and requalifications (their objects)
Entry points: PolicyFrames
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import (
    BUCKET_CAPACITY_GRANTS,
    BUCKET_INTENTS,
    BUCKET_POLICIES,
    BUCKET_REQUALIFICATIONS,
    BUCKET_RESEARCH_RECEIPTS,
    BUCKET_RESEARCH_SUPPLEMENTS,
    FLEET_UNITS,
)
from codex_harness.coordination.domain.continuation import (
    AUTHORITY,
    DISPATCHED,
    REQUALIFICATION,
    RESEARCH,
    ROUTE_OWNERS,
    STATUS_SCHEMA,
    ContinuationRefused,
    authorization,
    blocked_families,
    capacity_count,
    capacity_view,
    check_authorization,
    check_scope,
    policy_digest,
    receipt_view,
    refuse,
    requalification_view,
    research_attempts,
    supplement_view,
    validate_policy,
    view,
)
from codex_harness.coordination.domain.fleet import UNIT_CONDUCTOR, held_units
from codex_harness.kernel.ids import utcnow


class PolicyFrames:
    """The Git-pinned policy registry, its status projection and the one eligibility guard
    (`authorize`) every NEW effect passes (M7 `Continuation` registry part)."""

    def __init__(self, store, *, clock=utcnow, grants=None, intents=None, requalification=None):
        self.store = store
        self.clock = clock
        self.grants = grants
        self.intents = intents
        self.requalification = requalification

    # ----- registry -----------------------------------------------------------------------
    def register(self, document, pin: dict) -> dict:
        policy = validate_policy(document)
        sha = policy_digest(policy)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_POLICIES, policy["id"])
            if old is not None:
                refuse(old["policy_sha256"] == sha and old["pin"] == pin, "policy_conflict", field="id")
                return {"registered": True, "cached": True, "id": policy["id"], "policy_sha256": sha}
            tx.put(BUCKET_POLICIES, policy["id"], {"id": policy["id"], "policy": policy, "policy_sha256": sha,
                                                   "pin": dict(pin), "registered_at": self.clock()})
        return {"registered": True, "cached": False, "id": policy["id"], "policy_sha256": sha}

    def policy(self, policy_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(BUCKET_POLICIES, policy_id)

    def status(self, policy_id: str | None = None) -> dict:
        """Read-only projection: intents with route, state, cause, next owner/action, evidence
        references and predecessor/successor links. No manifest text, transcript or credential."""
        with self.store.transaction() as tx:
            policies = tx.scan(BUCKET_POLICIES)
            intents = tx.scan(BUCKET_INTENTS)
            receipts = tx.scan(BUCKET_RESEARCH_RECEIPTS)
            supplements = tx.scan(BUCKET_RESEARCH_SUPPLEMENTS)
            grants = tx.scan(BUCKET_CAPACITY_GRANTS)
            requalifications = tx.scan(BUCKET_REQUALIFICATIONS)
        if policy_id is not None:
            policies = [row for row in policies if row["id"] == policy_id]
            intents = [row for row in intents if row.get("policy_id") == policy_id]
            grants = [row for row in grants if (row.get("grant") or {}).get("policy_id") == policy_id]
            requalifications = [row for row in requalifications
                                if (row.get("document") or {}).get("policy_id") == policy_id]
        # Explicit capacity is shown beside, never merged into, each family's original cap and count.
        by_id = {row["id"]: row for row in intents}
        grants = [capacity_view(row, by_id.get(row["id"])) for row in sorted(grants, key=lambda r: r["id"])]
        caps = {row["id"]: row["policy"]["max_corrections"] for row in policies}
        families = []
        for owner, family in sorted({(g["policy_id"], g["family"]) for g in grants}):
            mine = [g for g in grants if (g["policy_id"], g["family"]) == (owner, family)]
            cap, counted = caps.get(owner), capacity_count(intents, owner, family)
            extra = sum(g["explicit_capacity"] or 0 for g in mine)
            families.append({"policy_id": owner, "family": family, "original_cap": cap, "counted": counted,
                             "explicit_capacity": extra, "grants": [g["grant_sha256"] for g in mine],
                             "remaining": None if cap is None else max(0, cap + extra - counted)})
        # A research intent shows the exact attempt set an owner receipt must cover, and the stored
        # receipt (covered jobs, inspections, dispatch, evidence) once the owner recorded one. An owner
        # scope supplement is shown beside it, never merged into the original capture.
        receipts = {row["id"]: receipt_view(row) for row in receipts}
        supplements = {row["id"]: supplement_view(row) for row in supplements}
        views = [{**view(row), "attempts": research_attempts(intents, row), "receipt": receipts.get(row["id"]),
                  "supplement": supplements.get(row["id"])}
                 if row["route"] == RESEARCH else view(row)
                 for row in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"]))]
        counts: dict = {}
        for row in views:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return {"schema": STATUS_SCHEMA, "authority": AUTHORITY,
                "policies": [{"id": row["id"], "enabled": row["policy"]["enabled"], "policy_sha256": row["policy_sha256"],
                              "pin": row["pin"]} for row in policies],
                "intents": views[-200:], "truncated": len(views) > 200, "counts": counts,
                "held_families": blocked_families(intents), "capacity": {"grants": grants, "families": families},
                "requalifications": [requalification_view(row) for row in sorted(requalifications, key=lambda r: r["id"])]}

    def unresolved(self, policy_id: str, owned=()) -> list:
        """Conductor work of this policy no guardian of THIS process supervises: dispatched launches
        and every Fleet execution unit still held for one of its intents (a previous controller's
        guardian, an unconfirmed start, cleanup unknown or settlement pending). A heartbeat reports
        them as unresolved, never as idle."""
        owned = set(owned)
        with self.store.transaction() as tx:
            intents = [row for row in tx.scan(BUCKET_INTENTS) if row.get("policy_id") == policy_id]
            units = [row for row in tx.scan(FLEET_UNITS) if row.get("kind") == UNIT_CONDUCTOR]
        mine = {row["id"] for row in intents}
        refs = {(row.get("launch") or {}).get("id") or row["id"] for row in intents if row["state"] == DISPATCHED}
        refs |= set(held_units(unit for unit in units if unit.get("subject") in mine))
        return sorted(ref for ref in refs if ref not in owned)

    # ----- the one eligibility guard ------------------------------------------------------
    def authorize(self, ctx, intent: dict) -> dict:
        """Before every NEW effect (lane binding, Fleet admission, conductor start): the current
        pinned policy, frame, model and runtime identity must equal the intent's stored authorization.

        Drift refuses the effect and records the exact reason and next owner on the intent as a
        `hold` (written once, not on every idle tick); the state, the stored authorization and all
        evidence stay as they were. A hold clears only when the current binding equals the stored
        one again - it is never resolved by adopting the changed binding."""
        job = ctx["jobs"].get(intent["origin_job"])
        try:
            refuse(job is not None, "origin_job_missing", "fleet", "origin_job")
            refuse(intent.get("policy_sha256") == ctx["sha"], "policy_changed", field="policy_sha256")
            current = ctx["runtime"](job["lane"]) if ctx["runtime"] else None
            check_scope(ctx["policy"], job, current)
            check_authorization(intent.get("authorization"), authorization(ctx["sha"], ctx["pin"], job, current))
            if intent.get("capacity_grant") is not None:
                self.grants.check(ctx, intent)   # a granted repair: the grant and its bindings again
            if intent.get("route") == REQUALIFICATION:
                self.requalification.check(ctx, intent)   # the owner's stored document, intact
        except ContinuationRefused as exc:
            hold = {"reason_code": exc.reason_code, "next_owner": exc.owner, "field": exc.field}
            if intent.get("hold") != hold:
                self.intents.note(intent, emit=True, hold=hold, next_owner=exc.owner)
            raise
        if intent.get("hold") is not None:
            intent = self.intents.note(intent, emit=True, hold=None, next_owner=ROUTE_OWNERS.get(intent["route"], "operator"))
        return intent
