"""Debate sessions: durable, operator-submitted, bounded design control (INV-DGE-001).

One `dge_sessions` row per meeting packet and one `dge_events` row per accepted event. Every
mutation runs in one store transaction: a refused or stale submission writes nothing except the
persisted `expired` state, which is itself the refusal's evidence. Nothing here calls a provider,
reserves budget, publishes to the bus or writes knowledge. An approved design authorizes exactly the
plan the packet carried; `design_gate` is evaluated inside the operation claim transaction.
"""
from __future__ import annotations

from codex_harness.domain.dge import (
    ORIGIN,
    PHASE_ROLE,
    TERMINAL,
    TRUST,
    design_gate_reason,
    event_digest,
    expired,
    packet_digest,
    validate_event,
    validate_payload,
    verdict_transition,
)
from codex_harness.domain.model import ContractError, utcnow

SESSIONS = "dge_sessions"
EVENTS = "dge_events"
STATUS_SCHEMA = "urn:zeus:debate-status:1"


class DgeRefused(ContractError):
    """Refused with a fixed reason code; the message never carries packet or payload text."""

    def __init__(self, reason_code: str):
        super().__init__("dge refused: " + reason_code)
        self.reason_code = reason_code


class DebateSessions:
    def __init__(self, store, clock=utcnow):
        self.store, self.clock = store, clock

    # ----- register -----------------------------------------------------------------------
    def register(self, packet: dict, repository: str, sources: list) -> dict:
        """`packet` is the validated normalized packet; `sources` are the Git-verified bindings the
        adapter produced for it. Same id, digest and repository replays the saved row."""
        digest_value = packet_digest(packet)
        verified = sorted((s["id"], s["sha256"]) for s in sources)
        if verified != sorted((s["id"], s["sha256"]) for s in packet["sources"]):
            raise DgeRefused("source_verification_incomplete")
        with self.store.transaction() as tx:
            old = tx.get(SESSIONS, packet["id"])
            if old is not None:
                # Exact replay returns the historical row without mutation, even past the deadline;
                # it reauthorizes nothing: submit and the claim gate check expiry themselves.
                if old["packet_digest"] == digest_value and old["repository"] == repository:
                    return {"session": old, "cached": True}
                raise DgeRefused("packet_conflict")
            # The clock is read inside the transaction, after any wait for the store lock and
            # immediately before the new row is written; a refusal here writes nothing.
            now = self.clock()
            if expired(packet["limits"]["deadline"], now):
                raise DgeRefused("packet_expired")
            if packet["supersedes"] is not None:
                self._check_replacement(tx, packet)
            row = {"id": packet["id"], "schema": packet["schema"], "packet_digest": digest_value,
                   "repository": repository, "base_revision": packet["base_revision"], "plan": packet["plan"],
                   "objective": packet["objective"], "packet": packet, "origin": ORIGIN,
                   "version": 0, "round": 1, "max_rounds": packet["limits"]["max_rounds"],
                   "deadline": packet["limits"]["deadline"], "state": "proposal",
                   "supersedes": packet["supersedes"], "research_reason": packet["research_reason"],
                   "rounds": {}, "findings": [], "deferred": [], "unresolved": [], "research_question": None,
                   "decision_event_id": None, "history": [],
                   "sources_verified": [{k: s[k] for k in ("id", "path", "sha256", "bytes")} for s in sources],
                   "registered_at": now, "updated_at": now, "finished_at": None}
            tx.put(SESSIONS, packet["id"], row)
        return {"session": row, "cached": False}

    @staticmethod
    def _check_replacement(tx, packet):
        prior = tx.get(SESSIONS, packet["supersedes"])
        if prior is None:
            raise DgeRefused("supersedes_unknown")
        if prior["state"] != "needs_research":
            raise DgeRefused("supersedes_not_needs_research")
        if prior["objective"] != packet["objective"] or prior["plan"] != packet["plan"]:
            raise DgeRefused("supersedes_plan_mismatch")
        # The replacement must answer the exact question that stopped the prior session.
        answered = any(q["status"] == "answered" and q["question"] == prior["research_question"]
                       for q in packet["questions"])
        if not answered:
            raise DgeRefused("supersedes_question_unanswered")
        if any(s.get("supersedes") == prior["id"] for s in tx.scan(SESSIONS)):
            raise DgeRefused("supersedes_already_replaced")

    # ----- submit ---------------------------------------------------------------------------
    def submit(self, session_id: str, document: dict) -> dict:
        """One transaction for the stage, event and history change. A refusal raised inside rolls
        everything back; the expiry refusal is the one committed write and is raised afterwards."""
        event = validate_event(document)
        with self.store.transaction() as tx:
            result = self._submit(tx, session_id, event, event_digest(event), self.clock())
        if isinstance(result, DgeRefused):
            raise result  # the expired state is committed; the deadline is never refreshed
        return result

    def _submit(self, tx, session_id, event, digest_value, now):
        session = tx.get(SESSIONS, session_id)
        if session is None:
            raise DgeRefused("unknown_session")
        existing = tx.get(EVENTS, self._event_key(session_id, event["id"]))
        if existing is not None:
            # Exact replay (interrupted client retry) is idempotent before any version check.
            if existing["digest"] == digest_value:
                return {"status": "duplicate", "event_id": event["id"], "event_digest": digest_value,
                        "session": self._safe(session)}
            raise DgeRefused("event_conflict")
        if session["state"] in TERMINAL:
            raise DgeRefused("session_terminal")
        if expired(session["deadline"], now):
            session.update(state="expired", updated_at=now, finished_at=now)
            session["history"].append({"at": now, "outcome": "expired", "event_id": None})
            tx.put(SESSIONS, session_id, session)
            return DgeRefused("packet_expired")
        if event["packet_digest"] != session["packet_digest"]:
            raise DgeRefused("packet_digest_mismatch")
        if event["round"] != session["round"]:
            raise DgeRefused("round_mismatch")
        if event["expected_version"] != session["version"]:
            raise DgeRefused("stale_version")
        if event["role"] != PHASE_ROLE[session["state"]]:
            raise DgeRefused("role_out_of_order")
        current = session["rounds"].setdefault(str(session["round"]), {})
        registry = session.setdefault("findings", [])
        # Unresolved findings persist into the next round even when its attacker omits them; the
        # arbiter must cover the union of carried and current findings (owner review R1).
        carried = [f for f in registry if f["status"] == "blocking"]
        payload = validate_payload(event["role"], event["payload"],
                                   claim_ids={c["id"] for c in session["packet"]["claims"]},
                                   criteria=session["plan"]["acceptance_criteria"],
                                   findings=carried + (current.get("findings") or []),
                                   known_finding_ids={f["id"] for f in registry})
        outcome = self._apply(session, event, payload, current, now)
        row = {"id": self._event_key(session_id, event["id"]), "event_id": event["id"], "session_id": session_id,
               "digest": digest_value, "event": event, "origin": ORIGIN, "round": event["round"],
               "role": event["role"], "version_before": event["expected_version"],
               "version_after": session["version"], "recorded_at": now}
        tx.put(EVENTS, row["id"], row)
        tx.put(SESSIONS, session_id, session)
        return {"status": "recorded", "event_id": event["id"], "event_digest": digest_value, "outcome": outcome,
                "session": self._safe(session)}

    @staticmethod
    def _event_key(session_id, event_id) -> str:
        return session_id + ":" + event_id

    @staticmethod
    def _apply(session, event, payload, current, now) -> dict:
        role, version = event["role"], session["version"] + 1
        entry = {"event_id": event["id"], "role": role, "round": event["round"], "version": version, "at": now}
        if role == "proposer":
            current["proposal"] = {"event_id": event["id"], "claim_ids": payload["claim_ids"]}
            session["state"] = "critique"
            entry["outcome"] = "critique"
        elif role == "attacker":
            current["findings"] = payload["findings"]
            # Session-wide registry: identity, criterion and severity are fixed at first record.
            session["findings"].extend({"id": f["id"], "round": event["round"], "criterion": f["criterion"],
                                        "severity": f["severity"], "status": "open", "decisions": []}
                                       for f in payload["findings"])
            session["state"] = "arbitration"
            entry["outcome"] = "arbitration"
        else:
            transition = verdict_transition(payload["verdict"], event["round"], session["max_rounds"])
            records = {f["id"]: f for f in session["findings"]}
            current["arbitration"] = {"event_id": event["id"], "verdict": payload["verdict"],
                                      "dispositions": payload["dispositions"],
                                      "carried": [f["id"] for f in session["findings"] if f["status"] == "blocking"]}
            for disposition in payload["dispositions"]:
                record = records[disposition["finding_id"]]
                record["status"] = disposition["decision"]  # every earlier decision stays in `decisions`
                record["decisions"].append({"round": event["round"], "event_id": event["id"],
                                            "decision": disposition["decision"]})
            session["deferred"] = _by_status(session["findings"], "deferred")
            session["unresolved"] = _by_status(session["findings"], "blocking")
            session["state"], session["round"] = transition["state"], transition["round"]
            if payload["verdict"] == "needs_research":
                session["research_question"] = payload["research_question"]
            if transition["state"] in TERMINAL:
                session["finished_at"] = now
                if transition["state"] == "design_approved":
                    session["decision_event_id"] = event["id"]
            entry["outcome"] = transition["state"]
        session["version"], session["updated_at"] = version, now
        session["history"].append(entry)
        return {"state": session["state"], "round": session["round"], "version": version}

    # ----- read-only ------------------------------------------------------------------------
    def status(self, session_id: str) -> dict:
        with self.store.transaction() as tx:
            session = tx.get(SESSIONS, session_id)
        if session is None:
            raise DgeRefused("unknown_session")
        return self._safe(session)

    @staticmethod
    def _safe(session) -> dict:
        """Digests, phase, counts and history identities; no packet body, payload or source text."""
        state = session["state"]
        return {"schema": STATUS_SCHEMA, "id": session["id"], "state": state,
                "phase": PHASE_ROLE.get(state), "terminal": state in TERMINAL,
                "round": session["round"], "max_rounds": session["max_rounds"], "deadline": session["deadline"],
                "version": session["version"], "packet_digest": session["packet_digest"],
                "repository": session["repository"], "base_revision": session["base_revision"],
                "origin": session["origin"], "supersedes": session["supersedes"],
                "counts": {"events": len([h for h in session["history"] if h.get("event_id")]),
                           "findings": len(session.get("findings") or []),
                           "resolved": len(_by_status(session.get("findings") or [], "resolved")),
                           "deferred": len(session["deferred"]), "unresolved": len(session["unresolved"]),
                           "sources_verified": len(session["sources_verified"])},
                "unresolved_finding_ids": [u["finding_id"] for u in session["unresolved"]],
                "research_question_present": session["research_question"] is not None,
                "decision_event_id": session["decision_event_id"],
                "history": [{k: h.get(k) for k in ("event_id", "role", "round", "version", "outcome", "at")}
                            for h in session["history"]],
                "trust": TRUST,
                "remaining": ("automated research/proposer/attacker/arbiter sessions, authenticated role "
                              "identities and formal knowledge promotion are not implemented"),
                "registered_at": session["registered_at"], "updated_at": session["updated_at"],
                "finished_at": session["finished_at"]}


def _by_status(findings: list, status: str) -> list:
    """Session-wide view of findings in one status; `round` is the round that raised the finding."""
    return [{"round": f["round"], "finding_id": f["id"], "severity": f["severity"]}
            for f in findings if f["status"] == status]


def design_gate(tx, design: dict, *, repository: str, base_revision: str, plan: dict, now: str) -> dict:
    """Inside the caller's transaction: the session must approve exactly this plan, or a fixed reason
    is raised before the caller writes anything. The session row is never mutated here."""
    session = tx.get(SESSIONS, design["session_id"])
    reason = design_gate_reason(session, design, repository=repository, base_revision=base_revision,
                                plan=plan, now=now)
    if reason is not None:
        raise DgeRefused(reason)
    return {"session_id": session["id"], "packet_digest": session["packet_digest"], "state": session["state"],
            "decision_event_id": session["decision_event_id"], "approved_at": session["finished_at"],
            "origin": session["origin"], "authority": "design_approved by operator-submitted arbitration; not verified knowledge"}
