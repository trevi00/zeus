"""The single owner of the proactive discovery pressure row (INV-DISCOVERY-PRESSURE-001).

`admit()` is the only writer. In ONE store transaction it reads the authoritative Fleet, backlog and
continuation rows and the prior row, decides, writes the row and, on a transition, appends the mandatory
audit event. Concurrent evaluators serialize on the store's transaction, so two equal crossings make one
transition and one event. Nothing here fetches, admits, ticks or pauses the Fleet: it only answers whether ONE
proactive fetch may start now; each admitted fetch then runs once, outside the transaction, and is never
cancelled by a later evaluation.
"""
from __future__ import annotations

from codex_harness.application.continuation import BUCKET_INTENTS as CONTINUATION_INTENTS
from codex_harness.application.fleet import BUCKET_JOBS, BUCKET_UNITS, Fleet
from codex_harness.application.fleet_backlog import BUCKET_INTENTS as BACKLOG_INTENTS
from codex_harness.application.fleet_backlog import BUCKET_PLANS
from codex_harness.domain.discovery_pressure import (
    BUCKET,
    EVENT_CHANGED,
    KEY,
    ROW_SCHEMA,
    DiscoveryRefused,
    census,
    decide,
    validate_policy,
)
from codex_harness.domain.fleet import effective_config
from codex_harness.domain.model import digest, require, utcnow

AUTHORITY = ("proactive discovery admission only; never a Fleet pause, an admission, a tick or a verdict about "
             "any job, and the thresholds are the policy document's own (suggested_unconfirmed until confirmed)")


class DiscoveryPressure:
    def __init__(self, store, policy_document, observer, clock=utcnow, ledger=None):
        require(observer is not None, "Discovery pressure transitions need the mandatory audit observer")
        # `ledger()` returns the call-ledger counts the Fleet runner admits against (read-only, taken just before
        # the transaction); None or a failing reader is unreadable, never an empty ledger.
        self.store, self.observer, self.clock, self.ledger = store, observer, clock, ledger
        if policy_document is None:
            self.policy, self.policy_problem = None, "config_missing"
        else:
            try:
                self.policy, self.policy_problem = validate_policy(policy_document), None
            except DiscoveryRefused:
                self.policy, self.policy_problem = None, "config_invalid"

    def admit(self) -> dict:
        """Decide whether ONE proactive fetch may start now, recording the evaluation."""
        try:
            ledger = self.ledger() if self.ledger is not None else None
        except Exception:
            ledger = None
        with self.store.transaction() as tx:
            registry = Fleet._registry(tx)
            control = Fleet._control(tx)
            config = effective_config(registry["config"], control) if registry is not None else None
            jobs = {job["id"]: job for job in tx.scan(BUCKET_JOBS)}
            observed = census(config=config, control=control, jobs=jobs, units=tx.scan(BUCKET_UNITS),
                              plans=tx.scan(BUCKET_PLANS), intents=tx.scan(BACKLOG_INTENTS),
                              continuation_intents=tx.scan(CONTINUATION_INTENTS),
                              aliases=Fleet._repository_aliases(tx) if registry is not None else None, ledger=ledger)
            prior = tx.get(BUCKET, KEY)
            outcome = decide(prior, observed, self.policy)
            now = self.clock()
            known = observed.get("registered") and observed.get("complete")
            key = (outcome["hysteresis_state"], outcome["decision"], outcome["reason_code"])
            transition = prior is None or (prior.get("hysteresis_state"), prior.get("decision"),
                                           prior.get("reason_code")) != key
            version = (prior or {}).get("version", 0) + (1 if transition else 0)
            row = {
                "id": KEY, "schema": ROW_SCHEMA, "version": version,
                "evaluation_sequence": (prior or {}).get("evaluation_sequence", 0) + 1,
                **outcome,
                "detail": self.policy_problem if self.policy is None else None,
                # W is null whenever it is not complete: a jobs-only count is a lower bound, never W.
                "waiting": observed.get("waiting") if known else None,
                "waiting_jobs_lower_bound": observed.get("waiting") if observed.get("registered") else None,
                "capacity": observed.get("capacity") if observed.get("registered") else None,
                "occupancy": observed.get("occupancy"),
                "basis": {"registered": bool(observed.get("registered")), "paused": observed.get("paused"),
                          "complete": observed.get("complete"), "unknown_counts": observed.get("unknown"),
                          "excluded_counts": observed.get("excluded"),
                          "fleet_config_sha256": digest(registry["config"]) if registry is not None else None},
                "policy": None if self.policy is None else {
                    key_: self.policy[key_] for key_ in ("id", "k_pause", "k_resume", "threshold_status", "digest")},
                "evaluated_at": now,
                "transitioned_at": now if transition else (prior or {}).get("transitioned_at"),
                "authority": AUTHORITY,
            }
            tx.put(BUCKET, KEY, row)
            if transition:
                self.observer.audit(
                    tx, EVENT_CHANGED, "observed", identity=[BUCKET, KEY, version], reason_code=row["reason_code"],
                    attributes={"version": version, "from_state": (prior or {}).get("hysteresis_state"),
                                "to_state": row["hysteresis_state"], "from_decision": (prior or {}).get("decision"),
                                "to_decision": row["decision"], "waiting": row["waiting"], "capacity": row["capacity"],
                                "complete": bool(observed.get("complete")),
                                "policy_digest": (row["policy"] or {}).get("digest"), "evaluated_at": now})
        return view(row)


def view(row: dict | None) -> dict | None:
    """The bounded projection of the row (the monitor and the callers read this, never the raw row)."""
    if row is None:
        return None
    return {key: row.get(key) for key in (
        "schema", "version", "evaluation_sequence", "hysteresis_state", "decision", "reason_code", "detail",
        "waiting", "waiting_jobs_lower_bound", "capacity", "occupancy", "basis", "policy", "evaluated_at",
        "transitioned_at", "authority")}


def status(store) -> dict:
    """Read-only: the recorded row, or `evaluated: false` when no evaluator has ever run. Nothing is evaluated,
    initialized or written by reading it."""
    with store.transaction() as tx:
        row = tx.get(BUCKET, KEY)
    return {"schema": ROW_SCHEMA, "evaluated": row is not None, "row": view(row)}


__all__ = ["AUTHORITY", "DiscoveryPressure", "status", "view"]
