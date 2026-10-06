"""The owner-action scheduler.

Layer: application
Context: coordination
Owns: bucket owner_action_policies
Does not own: each family's effects (the families)
Entry points: OwnerActionScheduler
Contracts: INV-OWNER-ACTIONS-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_MIGRATIONS,
    BUCKET_POLICIES,
    CONTINUATION_INTENTS,
    CONTINUATION_RECEIPTS,
    ActionChanged,
    _migration_status,
)
from codex_harness.coordination.domain.continuation import (
    AWAITING_OWNER,
    DELIVERY,
    RESEARCH,
    RESEARCH_REQUIRED,
)
from codex_harness.coordination.domain.owner_actions import (
    AUTHORITY,
    COMPLETED,
    DELIVERY_CANARY,
    DELIVERY_PLAN,
    DELIVERY_REQUALIFY,
    MAX_ACTIONS_PER_TICK,
    REFUSED,
    REJECTED,
    RESEARCH_DISPATCH,
    RESEARCH_RECEIPT,
    STATUS_SCHEMA,
    TERMINAL,
    TICK_SCHEMA,
    UNKNOWN,
    OwnerActionRefused,
    policy_digest,
    requalification_policy,
    research_policy,
    validate_policy,
    view,
)
from codex_harness.delivery.domain.host_delivery import CANARY_FLEET
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow


class OwnerActionScheduler:
    """The owner-action policy registry, status projection and the bounded tick: discovery through
    each family, then at most MAX_ACTIONS_PER_TICK open actions advanced one step by their family."""

    def __init__(self, store, *, clock=utcnow, continuation=None, actions=None, canary=None,
                 delivery_plan=None, migration=None, requalify_family=None, research_acceptance=None,
                 research_dispatch=None, observer=None):
        self.store = store
        self.observer = observer  # optional (S10 A5-2): `path_declined` for a disabled policy
        self.clock = clock
        self.continuation = continuation
        self.actions = actions
        self.canary = canary
        self.delivery_plan = delivery_plan
        self.migration = migration
        self.requalify_family = requalify_family
        self.research_acceptance = research_acceptance
        self.research_dispatch = research_dispatch

    # ----- registry -------------------------------------------------------------------------------
    def register(self, document, pin: dict) -> dict:
        """Register the owner's Git-pinned policy once; the identical policy at the same pin replays."""
        policy = validate_policy(document)
        sha = policy_digest(policy)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_POLICIES, policy["id"])
            if old is not None:
                if not (old["policy_sha256"] == sha and old["pin"] == pin):
                    raise OwnerActionRefused("policy_conflict", "id")
                return {"registered": True, "cached": True, "id": policy["id"], "policy_sha256": sha}
            tx.put(BUCKET_POLICIES, policy["id"], {"id": policy["id"], "policy": policy, "policy_sha256": sha,
                                                   "pin": dict(pin), "registered_at": self.clock()})
        return {"registered": True, "cached": False, "id": policy["id"], "policy_sha256": sha}

    def status(self, policy_id: str | None = None) -> dict:
        """Read-only projection: every action's kind, state, reason and identities; store reads only."""
        with self.store.transaction() as tx:
            policies = tx.scan(BUCKET_POLICIES)
            rows = tx.scan(BUCKET_ACTIONS)
            migrations = tx.scan(BUCKET_MIGRATIONS)
        if policy_id is not None:
            policies = [row for row in policies if row["id"] == policy_id]
            rows = [row for row in rows if row.get("policy_id") == policy_id]
            migrations = [row for row in migrations if row.get("policy_id") == policy_id]
        views = [view(row) for row in sorted(rows, key=lambda r: (str(r.get("created_at")), r["id"]))]
        counts: dict = {}
        for row in views:
            counts[row["kind"] + ":" + row["state"]] = counts.get(row["kind"] + ":" + row["state"], 0) + 1
        return {"schema": STATUS_SCHEMA, "authority": AUTHORITY,
                "policies": [{"id": row["id"], "enabled": row["policy"]["enabled"],
                              "policy_sha256": row["policy_sha256"], "pin": row["pin"]} for row in policies],
                "actions": views[-200:], "truncated": len(views) > 200, "counts": counts,
                "held": [row for row in views if row["state"] in {UNKNOWN, REJECTED, REFUSED}][-50:],
                "migrations": [_migration_status(row) for row in
                               sorted(migrations, key=lambda r: (str(r.get("created_at")), r["id"]))][-50:]}

    def _declined(self, feature: str, reason: str) -> None:
        """`operations.path_declined` (DESIGN-s10 §17, R-a52); nothing without an observer."""
        if self.observer is not None:
            self.observer.emit("operations.path_declined", "observed",
                               attributes={"feature": feature, "decline_reason": reason})

    # ----- one bounded tick -------------------------------------------------------------------------
    def tick(self, policy_id: str, *, pin_sha256: str | None = None) -> dict:
        """Discover owed actions and advance at most `MAX_ACTIONS_PER_TICK` of them by one step each."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_POLICIES, policy_id)
        if row is None:
            return self._receipt(policy_id, "unregistered", reason_code="policy_unregistered")
        if pin_sha256 is not None and row["pin"].get("sha256") != pin_sha256:
            return self._receipt(policy_id, "refused", reason_code="policy_changed")
        if not row["policy"]["enabled"]:
            self._declined("owner_actions", "disabled")
            return self._receipt(policy_id, "disabled", reason_code="policy_disabled")
        continuation = None if self.continuation is None else self.continuation.policy(
            row["policy"]["continuation_policy"])
        if continuation is None:
            return self._receipt(policy_id, "refused", reason_code="continuation_policy_unregistered")
        if continuation["policy"]["delivery_target"] != row["policy"]["delivery"]["target_id"]:
            return self._receipt(policy_id, "refused", reason_code="delivery_target_mismatch")
        waits: dict = {}
        created = self._discover(row, continuation, waits)
        migrated = self.migration.advance(row, continuation, waits)
        with self.store.transaction() as tx:
            open_rows = sorted((r for r in tx.scan(BUCKET_ACTIONS)
                                if r.get("policy_id") == policy_id and r["state"] not in TERMINAL),
                               key=lambda r: (str(r.get("created_at")), r["id"]))
        actions = []
        for action in open_rows[:MAX_ACTIONS_PER_TICK]:
            try:
                effect = self._advance(row, continuation, action)
            except ActionChanged:
                effect = None
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                # An outage or a refused read of THIS step: the row stays where it is and says why.
                waits[action["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
                effect = None
            if effect is not None:
                actions.append(effect)
        actions = migrated + actions
        outcome = "progressed" if actions or created else "idle"
        return self._receipt(policy_id, outcome, actions=actions, created=created, waits=waits,
                             open=len(open_rows))

    def _receipt(self, policy_id, outcome, *, reason_code=None, actions=(), created=(), waits=None, open=0) -> dict:
        return {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": outcome, "reason_code": reason_code,
                "created": list(created), "actions": list(actions), "waits": dict(waits or {}), "open": open,
                "authority": AUTHORITY}

    # ----- discovery: the owed actions, from durable rows only ---------------------------------------
    def _discover(self, row: dict, continuation: dict, waits: dict) -> list:
        with self.store.transaction() as tx:
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == continuation["id"]]
            receipts = {r["id"] for r in tx.scan(CONTINUATION_RECEIPTS)}
            actions = [r for r in tx.scan(BUCKET_ACTIONS) if r.get("policy_id") == row["id"]]
            migrating = [r for r in tx.scan(BUCKET_MIGRATIONS) if r.get("policy_id") == row["id"]]
            dispatched = {(a.get("subject") or {}).get("intent_id") for a in tx.scan(BUCKET_ACTIONS)
                          if a.get("kind") == RESEARCH_DISPATCH}
        busy = {(a["kind"], (a.get("subject") or {}).get("intent_id")) for a in actions if a["state"] not in TERMINAL}
        # An intent under an open evaluator migration gets its plan ONLY from that migration.
        busy |= {(DELIVERY_PLAN, (m.get("subject") or {}).get("intent_id")) for m in migrating
                 if m["state"] not in TERMINAL}
        created = []
        research = research_policy(row["policy"])
        for intent in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"])):
            # ONE guarded dispatch per held intent, whatever its outcome: a refused, empty, rejected or
            # unknown one is the owner's named exception, never a second tick (no collection-only spin).
            if research is not None and intent.get("route") == RESEARCH and intent.get("state") == RESEARCH_REQUIRED \
                    and intent["id"] not in receipts and intent["id"] not in dispatched:
                try:
                    created += self.research_dispatch.discover(row, research, intent, intents)
                except (ContractError, OSError, RuntimeError, ValueError) as exc:
                    waits[RESEARCH_DISPATCH + ":" + intent["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
            try:
                if intent.get("route") == RESEARCH and intent.get("state") == RESEARCH_REQUIRED \
                        and intent["id"] not in receipts and (RESEARCH_RECEIPT, intent["id"]) not in busy:
                    found = self.research_acceptance.research_binding(continuation, intent, intents)
                    created += self.actions.create(row, RESEARCH_RECEIPT, found["binding"],
                                            {"intent_id": intent["id"], "lane": intent.get("lane")})
                elif intent.get("route") == DELIVERY and intent.get("state") == AWAITING_OWNER \
                        and (DELIVERY_PLAN, intent["id"]) not in busy:
                    binding = self.delivery_plan.plan_binding(row, intent)
                    if binding is not None:
                        created += self.actions.create(row, DELIVERY_PLAN, binding,
                                                {"intent_id": intent["id"], "lane": intent.get("lane")})
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                waits[intent["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
        for plan in [a for a in actions if a["kind"] == DELIVERY_PLAN and a["state"] == COMPLETED
                     and (a.get("plan") or {}).get("canary_check_id") == CANARY_FLEET]:
            try:
                self.canary.refile_request(plan)
                binding = self.canary.canary_binding(plan)
                if binding is not None and self.canary.restart_owed(plan, actions):
                    # INV-HOST-DELIVERY-FIRST-ACTIVATION-001: the lane restarted this plan's stopped generation and
                    # retried it; the halted canary of the stopped instance is owed its typed recovery onto the
                    # restarted one (same action, same job). A second canary is never created for it.
                    # (extended) After the lane's ONE re-arm the SAME halted canary is owed its typed re-arm recovery.
                    waits[plan["id"]] = "canary_recovery_owed"
                elif binding is not None and (DELIVERY_CANARY, plan["subject"]["intent_id"]) not in busy:
                    created += self.actions.create(row, DELIVERY_CANARY, binding, dict(plan["subject"]))
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                waits[plan["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
        block = requalification_policy(row["policy"])
        if block is not None:
            # A plan that already has its requalify action (in any state) is decided: no further read.
            decided = {a["binding"]["plan_id"] for a in actions if a["kind"] == DELIVERY_REQUALIFY}
            for plan in [a for a in actions if a["kind"] == DELIVERY_PLAN and a["state"] == COMPLETED]:
                if plan["plan_id"] in decided or (DELIVERY_REQUALIFY, plan["subject"]["intent_id"]) in busy:
                    continue
                try:
                    created += self.requalify_family.discover(row, block, plan)
                except (ContractError, OSError, RuntimeError, ValueError) as exc:
                    waits[DELIVERY_REQUALIFY + ":" + plan["id"]] = getattr(exc, "reason_code", None) \
                        or type(exc).__name__
        return created

    def _advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        handler = {RESEARCH_RECEIPT: self.research_acceptance.advance, DELIVERY_PLAN: self.delivery_plan.advance,
                   DELIVERY_CANARY: self.canary.advance, RESEARCH_DISPATCH: self.research_dispatch.advance,
                   DELIVERY_REQUALIFY: self.requalify_family.advance}[action["kind"]]
        return handler(policy_row, continuation, action)
