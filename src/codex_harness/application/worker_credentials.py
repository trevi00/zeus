"""Named worker credential admission over the durable store (INV-WORKER-CREDENTIALS-001).

The ONE use case every dispatch path calls: `admit(owner)` selects a credential by the pure policy in
`domain.worker_credentials` and RESERVES it for exactly that owner in one transaction (serialized admission);
`release(owner, cause=...)` returns the reservation and applies what the finished worker's provider outcome
means (a usage limit cools the credential down until its reported reset, an authentication failure revokes the
generation); `observe(alias)` records one fresh provider usage observation through the telemetry port; `token`
hands the secret, through the secret port, ONLY to the caller building that one worker's environment.

Records hold aliases, generations, owners, codes, times and provider-reported percentages; never a secret, a
secret-derived digest or an account identifier. A new configured generation starts a clean state (the previous
generation's cooldown or revocation never leaks onto it); a crashed owner's reservation expires by its own
bounded lease, and an in-flight worker is never killed or replayed from here."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from codex_harness.domain.model import utcnow
from codex_harness.domain.worker_credentials import (
    ALIASES,
    AUTH_CAUSES,
    EFFECT_COOLDOWN,
    EFFECT_REVOKED,
    OWNER,
    SECRET_UNAVAILABLE,
    USAGE_LIMIT_CAUSES,
    CredentialRefused,
    credential,
    outcome_effect,
    refreshable,
    select,
    validate_config,
    validate_observation,
)

BUCKET = "worker_credentials"
SELECTION = "selection"   # the one record of which alias served the last grant, and every switch
AUDIT_LIMIT = 64


def _now(clock) -> datetime:
    return datetime.fromisoformat(clock())


class WorkerCredentials:
    def __init__(self, store, config: dict, *, clock=utcnow, telemetry=None, secrets=None):
        self.store, self.clock = store, clock
        self.config = validate_config(config)
        self.telemetry, self.secrets = telemetry, secrets

    # ----- state ---------------------------------------------------------------------------------
    def _state(self, tx, alias: str) -> dict:
        """The alias's durable state for the CONFIGURED generation; another generation starts clean."""
        row = credential(self.config, alias)
        stored = tx.get(BUCKET, alias)
        if row is None:
            return stored or {}
        if not isinstance(stored, dict) or stored.get("generation") != row["generation"]:
            return {"alias": alias, "generation": row["generation"], "reservations": {}, "cooldown": None,
                    "revoked": None, "observation": None,
                    "audit": list((stored or {}).get("audit") or [])[-AUDIT_LIMIT:],
                    "previous_generation": (stored or {}).get("generation")}
        return {"reservations": {}, "audit": [], **stored}

    def _audit(self, state: dict, event: str, **facts) -> dict:
        entry = {"at": self.clock(), "event": event, "alias": state.get("alias"), "generation": state.get("generation"),
                 **{k: v for k, v in facts.items() if v is not None}}
        return {**state, "audit": [*(state.get("audit") or []), entry][-AUDIT_LIMIT:]}

    # ----- observation ---------------------------------------------------------------------------
    def observe(self, alias: str) -> dict:
        """One fresh provider observation of the alias's configured generation, recorded as reported."""
        row = credential(self.config, alias)
        if row is None or row["telemetry"] is None:
            raise CredentialRefused("telemetry_unconfigured", "alias")
        if self.telemetry is None:
            raise CredentialRefused("telemetry_port_unconfigured", "telemetry")
        observation = validate_observation(self.telemetry(row))
        if (observation["alias"], observation["generation"]) != (alias, row["generation"]):
            raise CredentialRefused("observation_foreign", "generation")
        with self.store.transaction() as tx:
            state = self._state(tx, alias)
            state = self._audit({**state, "observation": observation}, "observed", status=observation["status"],
                                reason_code=observation["reason_code"],
                                weekly_used_percent=(observation.get("weekly") or {}).get("used_percent"),
                                five_hour_used_percent=(observation.get("five_hour") or {}).get("used_percent"))
            tx.put(BUCKET, alias, state)
        return self._observation_view(observation)

    @staticmethod
    def _observation_view(observation) -> dict | None:
        if not isinstance(observation, dict):
            return None
        return {k: observation.get(k) for k in ("alias", "generation", "observed_at", "status", "reason_code",
                                                "weekly", "five_hour")} | {"source": dict(observation.get("source") or {})}

    # ----- admission -----------------------------------------------------------------------------
    def admit(self, owner: str) -> dict:
        """Select and RESERVE one credential for exactly this owner, or hold. One transaction."""
        if not (isinstance(owner, str) and OWNER.fullmatch(owner)):
            raise CredentialRefused("owner_invalid", "owner")
        with self.store.transaction() as tx:
            states = {alias: self._state(tx, alias) for alias in ALIASES}
            for alias, state in states.items():
                if owner in (state.get("reservations") or {}):
                    # The same owner asking again (a lost response): the reservation it already holds.
                    row = credential(self.config, alias)
                    return {"granted": True, "cached": True, "owner": owner, "alias": alias,
                            "generation": row["generation"], "reason_code": "reservation_held"}
            now = _now(self.clock)
            decision = select(self.config, states, now)
            if not decision["granted"]:
                reasons = {"primary": decision["primary"]["reason_code"],
                           "secondary": decision["secondary"]["reason_code"]}
                for alias in ALIASES:
                    if credential(self.config, alias) is not None:
                        last = next((e for e in reversed(states[alias].get("audit") or [])
                                     if e.get("event") != "observed"), {})
                        if not (last.get("event") == "held" and last.get("reasons") == reasons):
                            tx.put(BUCKET, alias, self._audit(states[alias], "held", owner=owner, reasons=reasons))
                return {"granted": False, "owner": owner, "alias": None, "reason_code": decision["reason_code"],
                        "reasons": reasons, "secondary": _facts(decision.get("secondary"))}
            alias = decision["alias"]
            row = credential(self.config, alias)
            until = now + timedelta(seconds=self.config["policy"]["reservation_seconds"])
            state = states[alias]
            # A crashed owner's reservation ends at its own lease; it is dropped here, visibly.
            expired = sorted(k for k, v in (state.get("reservations") or {}).items()
                             if (_instant_of(v.get("until")) or now) <= now)
            if expired:
                # Kept (bounded) so a late release still applies its provider outcome to this credential.
                state = self._audit({**state, "expired": [*(state.get("expired") or []), *expired][-AUDIT_LIMIT:]},
                                    "reservations_expired", owners=expired)
            reservations = {**{k: v for k, v in (state.get("reservations") or {}).items() if k not in expired},
                            owner: {"at": now.isoformat(), "until": until.isoformat()}}
            state = {**state, "alias": alias, "generation": row["generation"], "reservations": reservations}
            if state.get("cooldown") is not None:
                # Granting proves the cooldown elapsed (and, for an unreported reset with telemetry, was confirmed).
                state = self._audit({**state, "cooldown": None}, "cooldown_cleared",
                                    reset_confirmed=decision[alias].get("reset_confirmed"))
            state = self._audit(state, "granted", owner=owner, reason_code=decision["reason_code"],
                                primary=decision["primary"]["reason_code"])
            tx.put(BUCKET, alias, state)
            selection = tx.get(BUCKET, SELECTION) or {"alias": None, "switches": []}
            if selection.get("alias") != alias:
                switch = {"at": now.isoformat(), "from": selection.get("alias"), "to": alias, "owner": owner,
                          "reason_code": decision["reason_code"], "primary": decision["primary"]["reason_code"]}
                tx.put(BUCKET, SELECTION, {"alias": alias, "at": now.isoformat(),
                                           "switches": [*(selection.get("switches") or []), switch][-AUDIT_LIMIT:]})
        return {"granted": True, "cached": False, "owner": owner, "alias": alias, "generation": row["generation"],
                "reason_code": decision["reason_code"], "primary": decision["primary"]["reason_code"],
                "secondary": _facts(decision.get("secondary"))}

    def admit_fresh(self, owner: str) -> dict:
        """`admit`, with at most ONE fresh provider observation per held alias when only its missing, stale or
        unknown telemetry held it, and its last observation (known or not) is older than the freshness bound.
        A persistent telemetry defect therefore costs one `/usage` read per bound, never one per tick; the
        observation is never a model call and a failed one is recorded as the named unknown it is."""
        grant = self._readable(self.admit(owner))
        if grant["granted"] or grant.get("cached") or self.telemetry is None:
            return grant
        refreshed = []
        with self.store.transaction() as tx:
            states = {alias: self._state(tx, alias) for alias in ALIASES}
        decision = select(self.config, states, _now(self.clock))
        bound = self.config["policy"]["telemetry_max_age_seconds"]
        for alias in refreshable(decision):
            last = _instant_of((states[alias].get("observation") or {}).get("observed_at"))
            refusal = _instant_of((states[alias].get("cooldown") or {}).get("at"))
            if last is not None and (_now(self.clock) - last).total_seconds() <= bound \
                    and (refusal is None or last > refusal):
                continue   # a recent attempt already answered (even as unknown): wait for the bound
            try:
                self.observe(alias)
            except CredentialRefused:
                continue
            refreshed.append(alias)
        return {**self._readable(self.admit(owner)), "refreshed": refreshed} if refreshed else grant

    def _readable(self, grant: dict, *, again: bool = True) -> dict:
        """A grant whose secret the port cannot read revokes that generation and admits once more (so the other
        credential may serve, or the work holds); the launch never discovers an unreadable secret first."""
        if not grant["granted"] or self.secrets is None:
            return grant
        try:
            self.token(grant)
        except CredentialRefused:
            self.release(grant["owner"], cause=SECRET_UNAVAILABLE)
            if not again:
                return {"granted": False, "owner": grant["owner"], "alias": None, "reason_code": "secret_unavailable"}
            return self._readable(self.admit(grant["owner"]), again=False)
        return grant

    def token(self, grant: dict) -> str:
        """The granted credential's secret, for the one worker environment being built; never recorded."""
        if not (isinstance(grant, dict) and grant.get("granted") and grant.get("alias") in ALIASES):
            raise CredentialRefused("grant_invalid", "grant")
        if self.secrets is None:
            raise CredentialRefused("secret_port_unconfigured", "secrets")
        with self.store.transaction() as tx:
            state = self._state(tx, grant["alias"])
        if grant.get("owner") not in (state.get("reservations") or {}) \
                or state.get("generation") != grant.get("generation"):
            raise CredentialRefused("grant_not_reserved", "owner")
        return self.secrets(credential(self.config, grant["alias"])["secret"])

    def release(self, owner: str, *, cause=None, resets_at=None, subject=None) -> dict:
        """Return the owner's reservation and apply its provider outcome; an unknown owner changes nothing."""
        with self.store.transaction() as tx:
            for alias in ALIASES:
                if credential(self.config, alias) is None:
                    continue
                state = self._state(tx, alias)
                late = owner in (state.get("expired") or [])
                if owner not in (state.get("reservations") or {}) and not late:
                    continue
                now = _now(self.clock)
                effect = outcome_effect(cause, resets_at=resets_at, now=now,
                                        unknown_reset_seconds=self.config["policy"]["unknown_reset_seconds"])
                reservations = {k: v for k, v in (state.get("reservations") or {}).items() if k != owner}
                state = {**state, "reservations": reservations,
                         "expired": [k for k in (state.get("expired") or []) if k != owner]}
                if effect["effect"] == EFFECT_COOLDOWN:
                    state["cooldown"] = {"until": effect["until"], "reason_code": effect["reason_code"],
                                         "reset_reported": effect["reset_reported"], "at": now.isoformat()}
                elif effect["effect"] == EFFECT_REVOKED:
                    state["revoked"] = {"reason_code": effect["reason_code"], "at": now.isoformat()}
                state = self._audit(state, "released", owner=owner, subject=subject, late=late or None,
                                    effect=effect["effect"],
                                    reason_code=effect["reason_code"], until=effect.get("until"))
                tx.put(BUCKET, alias, state)
                return {"released": True, "late": late, "owner": owner, "alias": alias, **effect}
        return {"released": False, "owner": owner, "alias": None, "effect": "none", "reason_code": "reservation_unknown"}

    def record_refusal(self, alias: str, *, cause: str, evidence_ref: str, resets_at=None) -> dict:
        """An owner records a provider refusal of this credential observed OUTSIDE a Fleet dispatch (for example by
        a managed generation's own worker), naming the evidence of that observation. It has the same effect as a
        released dispatch with that cause; it never calls a provider. The same evidence replays `cached`."""
        row = credential(self.config, alias)
        if row is None:
            raise CredentialRefused("credential_unconfigured", "alias")
        if cause not in (USAGE_LIMIT_CAUSES | AUTH_CAUSES) - {SECRET_UNAVAILABLE}:
            raise CredentialRefused("refusal_cause_invalid", "cause")
        if not (isinstance(evidence_ref, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", evidence_ref)):
            raise CredentialRefused("refusal_evidence_invalid", "evidence")
        with self.store.transaction() as tx:
            state = self._state(tx, alias)
            recorded = next((e for e in state.get("audit") or [] if e.get("event") == "refusal_recorded"
                             and e.get("evidence") == evidence_ref), None)
            if recorded is not None:
                return {"recorded": True, "cached": True, "alias": alias, "effect": recorded.get("effect"),
                        "reason_code": recorded.get("reason_code"), "until": recorded.get("until")}
            now = _now(self.clock)
            effect = outcome_effect(cause, resets_at=resets_at, now=now,
                                    unknown_reset_seconds=self.config["policy"]["unknown_reset_seconds"])
            state = {**state, "alias": alias, "generation": row["generation"]}
            if effect["effect"] == EFFECT_COOLDOWN:
                state["cooldown"] = {"until": effect["until"], "reason_code": effect["reason_code"],
                                     "reset_reported": effect["reset_reported"], "at": now.isoformat()}
            elif effect["effect"] == EFFECT_REVOKED:
                state["revoked"] = {"reason_code": effect["reason_code"], "at": now.isoformat()}
            tx.put(BUCKET, alias, self._audit(state, "refusal_recorded", evidence=evidence_ref, effect=effect["effect"],
                                              reason_code=effect["reason_code"], until=effect.get("until")))
        return {"recorded": True, "cached": False, "alias": alias, **effect}

    # ----- projection ----------------------------------------------------------------------------
    def status(self) -> dict:
        """Redacted: aliases, generations, eligibility codes, reservations by owner, cooldowns, observations."""
        from codex_harness.domain.worker_credentials import eligibility
        with self.store.transaction() as tx:
            states = {alias: self._state(tx, alias) for alias in ALIASES}
            selection = tx.get(BUCKET, SELECTION) or {}
        now = _now(self.clock)
        rows = []
        for alias in ALIASES:
            row = credential(self.config, alias)
            if row is None:
                continue
            state = states[alias]
            rows.append({"alias": alias, "generation": row["generation"], "secret_kind": row["secret"]["kind"],
                         "telemetry_kind": (row["telemetry"] or {}).get("kind"),
                         "eligibility": eligibility(self.config, alias, state, now),
                         "reservations": sorted((state.get("reservations") or {}).keys()),
                         "cooldown": state.get("cooldown"), "revoked": state.get("revoked"),
                         "observation": self._observation_view(state.get("observation")),
                         "audit": (state.get("audit") or [])[-8:]})
        return {"schema": "urn:zeus:worker-credentials-status:1", "policy": dict(self.config["policy"]),
                "credentials": rows, "selection": select(self.config, states, now)["reason_code"],
                "serving": selection.get("alias"), "switches": (selection.get("switches") or [])[-8:]}


def _instant_of(value):
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _facts(decision) -> dict | None:
    if not isinstance(decision, dict):
        return None
    return {k: decision.get(k) for k in ("reason_code", "weekly_used_percent", "five_hour_used_percent",
                                         "age_seconds", "until") if decision.get(k) is not None}


__all__ = ["BUCKET", "SELECTION", "WorkerCredentials"]
