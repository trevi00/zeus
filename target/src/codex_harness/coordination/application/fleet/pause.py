"""Fleet admission pause, the managed-activation hold and the operator's budget grants.

Layer: application
Context: coordination
Owns: buckets fleet_control, fleet_budget_grants
Does not own: admission itself (fleet.admission); the delivery FleetDrain port it will implement (S7)
Entry points: FleetPause.pause, .resume, .activation_gate, .release_activation_hold, .authorize_budget, .budget_grants
Contracts: INV-FLEET-001

Moved from M7 `application/fleet.py` (SOURCE e38aa722) by the named split (DESIGN-s5 §F); the method
bodies are M7's.
"""

from __future__ import annotations

from uuid import uuid4

from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.state import (
    ACTIVATION_HOLD,
    BUCKET_CONTROL,
    BUCKET_GRANTS,
    BUCKET_JOBS,
    BUCKET_UNITS,
    CONTROL_KEY,
)
from codex_harness.coordination.domain.fleet import (
    QUEUED,
    RESERVING,
    FleetRefused,
    effective_config,
    held_units,
    safe_code,
    validate_grant,
)
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.usage import MODES, SUBSCRIPTION, accounting_mode


class FleetPause:
    """The durable admission pause, activation holds and budget grants (M7 `Fleet`, pause part)."""

    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

    # ----- admission control --------------------------------------------------------------
    def _set_paused(self, paused: bool) -> dict:
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            # Only the flag changes: a granted effective budget survives pause/resume. An owner pause
            # or resume takes the pause over, so a host activation hold never outlives it.
            control = {key: value for key, value in state.control(tx).items() if key != ACTIVATION_HOLD}
            row = {**control, "paused": paused, "updated_at": self.clock()}
            tx.put(BUCKET_CONTROL, CONTROL_KEY, row)
        return row

    def pause(self) -> dict:
        """Stops NEW admissions durably; dispatching work is allowed to finish."""
        return self._set_paused(True)

    def resume(self) -> dict:
        return self._set_paused(False)

    def activation_gate(self, target_id: str, descriptor_sha256: str) -> dict:
        """Commit a durable admission pause, THEN read the Fleet's execution debt in a second transaction.

        The managed host target calls this under its own lifecycle guard before it stops an
        instance and again before it launches one (HOST-RUNTIME.md "Activation gate"). Because every
        admission and unit reservation checks the pause under the same serialization, nothing can
        be reserved after the first transaction commits. That transaction scans no debt, so a failed
        debt read can never roll the pause back. The pause is left in place: a running fleet was not
        paused by an owner, so it carries an `activation_hold` naming the target and the descriptor
        being activated, which only that exact runtime may release (`release_activation_hold`); an
        owner pause is kept as it is.

        A failure of the pause transaction itself (write, commit or a lost acknowledgement) raises:
        no durable pause is claimed, and a retry reconciles the same hold. The debt read re-checks the
        pause authority in its own transaction: a failed read returns `reason_code` `debt_unknown`, a
        pause that changed between the two (an owner resume, pause or another hold) `control_changed`,
        both with unknown debt (None) and never `settled`. `settled` is True only when the pause is
        exactly the committed one, no worker job is reserving and no execution unit is held."""
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            control = state.control(tx)
            hold = control.get(ACTIVATION_HOLD)
            ours = not control.get("paused") or (isinstance(hold, dict) and hold.get("target_id") == target_id)
            if ours:
                hold = {"target_id": target_id, "descriptor_sha256": descriptor_sha256, "at": self.clock()}
                control = {**control, "paused": True, ACTIVATION_HOLD: hold, "updated_at": self.clock()}
                tx.put(BUCKET_CONTROL, CONTROL_KEY, control)
            committed = state.hold_key(control)
        unknown = {"paused": True, "hold": ours, "reserving": None, "units_held": None, "settled": False}
        try:
            with self.store.transaction() as tx:
                current = state.hold_key(state.control(tx))
                if current == committed:
                    reserving = sorted(row["id"] for row in tx.scan(BUCKET_JOBS) if row["status"] in RESERVING)
                    units = held_units(tx.scan(BUCKET_UNITS))
        except Exception as exc:
            return {**unknown, "reason_code": "debt_unknown", "error_type": safe_code(type(exc).__name__)}
        if current != committed:
            return {**unknown, "paused": current[0], "hold": False, "reason_code": "control_changed"}
        return {"paused": True, "hold": ours, "reserving": reserving, "units_held": units,
                "settled": not reserving and not units}

    def release_activation_hold(self, descriptor_sha256: str) -> dict:
        """Resume admission paused by `activation_gate`, only for the runtime it was held for.

        Called by a managed runtime that is running exactly that descriptor, so the code releasing
        the pause is code that counts execution units. A predecessor that predates this never calls
        it and stays paused for its owner. Any other pause (an owner's, another descriptor's hold)
        is left untouched."""
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            control = state.control(tx)
            hold = control.get(ACTIVATION_HOLD)
            if not (control.get("paused") and isinstance(hold, dict)
                    and hold.get("descriptor_sha256") == descriptor_sha256):
                return {"released": False}
            row = {key: value for key, value in control.items() if key != ACTIVATION_HOLD}
            tx.put(BUCKET_CONTROL, CONTROL_KEY, {**row, "paused": False, "updated_at": self.clock()})
        return {"released": True}

    def authorize_budget(self, per_host, total, expected_total, mode=None) -> dict:
        """Explicit operator grant over the effective budget, one transaction: the expected total
        must equal the current effective total, numbers valid and nondecreasing, either a number
        increases or the accounting `mode` changes (None keeps the current mode; unknown modes
        refuse), and no queued/dispatching/unknown job (queued work carries frozen budgets;
        reserving work holds the machine ledger). The registered config and digest stay immutable;
        the control row takes the new budget beside the untouched pause flag and an immutable
        `fleet_budget_grants` record keeps prior/new budget, both modes and time. No resume, and
        nothing here is called by the dispatcher or a model run."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = state.control(tx)
            prior = effective_config(registry["config"], control)["budget"]
            requested = {"per_host": per_host, "total": total}
            if mode is None:
                mode = accounting_mode(prior)
            if type(mode) is not str or mode not in MODES:
                raise FleetRefused("config_invalid", "mode")
            if mode == SUBSCRIPTION:
                requested["mode"] = mode
            budget = validate_grant(prior, requested, expected_total)
            if any(row["status"] == QUEUED or row["status"] in RESERVING for row in tx.scan(BUCKET_JOBS)) \
                    or held_units(tx.scan(BUCKET_UNITS)):
                raise FleetRefused("fleet_not_idle")
            now = self.clock()
            grant_id = "grant-%08d" % (len(tx.scan(BUCKET_GRANTS)) + 1)
            require(tx.get(BUCKET_GRANTS, grant_id) is None, "Fleet budget grant record already exists")
            grant = {"id": grant_id, "fleet": registry["id"], "config_sha256": registry["config_sha256"],
                     "prior": dict(prior), "budget": budget, "expected_total": expected_total,
                     "prior_mode": accounting_mode(prior), "mode": accounting_mode(budget), "granted_at": now}
            tx.put(BUCKET_GRANTS, grant_id, grant)
            row = {**control, "paused": bool(control.get("paused")), "budget": budget, "updated_at": now}
            tx.put(BUCKET_CONTROL, CONTROL_KEY, row)
        return {"granted": True, "grant_id": grant_id, "prior": grant["prior"], "budget": dict(budget),
                "prior_mode": grant["prior_mode"], "mode": grant["mode"], "paused": row["paused"], "granted_at": now}

    def budget_grants(self) -> list[dict]:
        with self.store.transaction() as tx:
            return tx.scan(BUCKET_GRANTS)
