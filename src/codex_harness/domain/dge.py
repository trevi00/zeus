"""Research-bound design control: packet, debate event and gate rules (INV-DGE-001).

Research comes before debate and an approved design comes before implementation. The meeting
packet (`urn:zeus:research-packet:1`) pins tracked source bytes at one base revision, names the
questions the debate must settle and carries the exact operation plan the approval will bind. Debate
events (`urn:zeus:debate-event:1`) are operator-submitted attestations for the fixed role order
proposer -> attacker -> arbiter; nothing here calls a model, verifies a citation's truth, or promotes
knowledge. Every check refuses on structure, sequence and the operator's recorded decision only.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import ID, REVISION, SHA256, safe_relative_path, validate_plan

PACKET_SCHEMA = "urn:zeus:research-packet:1"
EVENT_SCHEMA = "urn:zeus:debate-event:1"
PACKET_FIELDS = {"schema", "id", "base_revision", "topic", "objective", "exclusions", "plan", "questions",
                 "sources", "claims", "limits", "supersedes", "research_reason"}
QUESTION_FIELDS = {"id", "question", "blocking", "status", "claim_ids"}
SOURCE_FIELDS = {"id", "path", "sha256", "locator", "revision", "read_scope"}
CLAIM_FIELDS = {"id", "kind", "text", "source_ids"}
LIMIT_FIELDS = {"max_rounds", "deadline"}
EVENT_FIELDS = {"schema", "id", "expected_version", "packet_digest", "round", "role", "payload"}
FINDING_FIELDS = {"id", "criterion", "severity", "scenario", "claim_ids"}
DISPOSITION_FIELDS = {"finding_id", "decision", "reason"}
QUESTION_STATUSES = {"answered", "unknown"}
CLAIM_KINDS = {"fact", "inference", "unknown"}
SEVERITIES = {"critical", "minor"}
VERDICTS = {"accept", "revise", "needs_research", "reject"}
DECISIONS = {"resolved", "deferred", "blocking"}
ROLES = ("proposer", "attacker", "arbiter")
# Session phase -> the one role allowed to submit next; there is no critic bypass.
PHASE_ROLE = {"proposal": "proposer", "critique": "attacker", "arbitration": "arbiter"}
TERMINAL = {"design_approved", "rejected", "needs_research", "exhausted", "expired"}
MAX_ROUNDS = 4
ORIGIN = "operator_submitted"
TRUST = ("operator-submitted attestations; structure, sequence and the recorded operator decision "
         "are checked, not model execution, citation truth or implementation correctness")
TEXT_LIMIT = 12000


class PacketError(ContractError):
    """The packet is refused before any Git, PostgreSQL or provider access; no value is echoed."""


class EventError(ContractError):
    """The debate event is refused before any write; no payload text is echoed."""


def _text(value, limit=TEXT_LIMIT) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def _token(value) -> bool:
    return type(value) is str and ID.fullmatch(value) is not None


def _fields(document, expected, name, error):
    if not isinstance(document, dict):
        raise error(name + " must be an object")
    unknown, missing = sorted(set(document) - expected), sorted(expected - set(document))
    if unknown or missing:
        raise error(name + " has unknown or missing fields: "
                    + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))


def _id_list(value, known: set, name, error, nonempty=True) -> list:
    if not isinstance(value, list) or (nonempty and not value) or len(set(value)) != len(value):
        raise error(name + " must be a list of distinct ids")
    for item in value:
        if not (_token(item) and item in known):
            raise error(name + " references an unknown id")
    return list(value)


def parse_deadline(value, error=PacketError) -> str:
    """Timezone-aware ISO 8601 only, normalized to UTC; naive timestamps are refused."""
    if type(value) is not str or not value:
        raise error("limits.deadline must be an aware ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise error("limits.deadline must be an aware ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error("limits.deadline must carry a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat()


def expired(deadline: str, now: str) -> bool:
    """Aware UTC comparison; `now` is the caller's clock reading so the rule stays testable."""
    return datetime.fromisoformat(now).astimezone(timezone.utc) >= datetime.fromisoformat(deadline)


def validate_packet(document) -> dict:
    """Strict validation of a meeting packet; returns the normalized copy the digest is taken from."""
    _fields(document, PACKET_FIELDS, "Research packet", PacketError)
    if document["schema"] != PACKET_SCHEMA:
        raise PacketError("Research packet schema is not " + PACKET_SCHEMA)
    if not _token(document["id"]):
        raise PacketError("Research packet id must be a short safe token")
    if type(document["base_revision"]) is not str or REVISION.fullmatch(document["base_revision"]) is None:
        raise PacketError("Research packet base_revision must be a 40-hex commit id")
    if not (_text(document["topic"], 400) and _text(document["objective"])):
        raise PacketError("Research packet topic and objective are required text")
    exclusions = document["exclusions"]
    if not (isinstance(exclusions, list) and all(_text(e, 4000) for e in exclusions)):
        raise PacketError("Research packet exclusions must be a list of text")
    plan = validate_plan(document["plan"], PacketError)
    sources = _sources(document["sources"])
    claims = _claims(document["claims"], {s["id"] for s in sources})
    questions = _questions(document["questions"], claims)
    limits = document["limits"]
    _fields(limits, LIMIT_FIELDS, "Research packet limits", PacketError)
    rounds = limits["max_rounds"]
    if type(rounds) is not int or not 1 <= rounds <= MAX_ROUNDS:
        raise PacketError("Research packet limits.max_rounds must be an integer from 1 to " + str(MAX_ROUNDS))
    deadline = parse_deadline(limits["deadline"])
    supersedes, reason = document["supersedes"], document["research_reason"]
    if supersedes is not None and not _token(supersedes):
        raise PacketError("Research packet supersedes must be null or a session id")
    if reason is not None and not _text(reason, 4000):
        raise PacketError("Research packet research_reason must be null or text")
    if (supersedes is None) != (reason is None):
        raise PacketError("Research packet supersedes and research_reason come together")
    if supersedes == document["id"]:
        raise PacketError("Research packet cannot supersede itself")
    return {"schema": PACKET_SCHEMA, "id": document["id"], "base_revision": document["base_revision"],
            "topic": document["topic"], "objective": document["objective"], "exclusions": list(exclusions),
            "plan": plan, "questions": questions, "sources": sources, "claims": claims,
            "limits": {"max_rounds": rounds, "deadline": deadline},
            "supersedes": supersedes, "research_reason": reason}


def _sources(value) -> list:
    if not (isinstance(value, list) and value):
        raise PacketError("Research packet sources must be a non-empty list")
    out, ids, paths = [], set(), set()
    for source in value:
        _fields(source, SOURCE_FIELDS, "Research packet source", PacketError)
        if not _token(source["id"]) or source["id"] in ids:
            raise PacketError("Research packet source ids must be distinct safe tokens")
        if not safe_relative_path(source["path"]) or source["path"] in paths:
            raise PacketError("Research packet source paths must be distinct safe relative paths")
        if type(source["sha256"]) is not str or SHA256.fullmatch(source["sha256"]) is None:
            raise PacketError("Research packet source sha256 must be 64 lowercase hex")
        if not all(_text(source[k], 1024) for k in ("locator", "revision", "read_scope")):
            raise PacketError("Research packet source locator, revision and read_scope are required text")
        ids.add(source["id"])
        paths.add(source["path"])
        out.append({k: source[k] for k in sorted(SOURCE_FIELDS)})
    return out


def _claims(value, source_ids: set) -> list:
    if not isinstance(value, list):
        raise PacketError("Research packet claims must be a list")
    out, ids = [], set()
    for claim in value:
        _fields(claim, CLAIM_FIELDS, "Research packet claim", PacketError)
        if not _token(claim["id"]) or claim["id"] in ids:
            raise PacketError("Research packet claim ids must be distinct safe tokens")
        if claim["kind"] not in CLAIM_KINDS or not _text(claim["text"]):
            raise PacketError("Research packet claim needs a known kind and text")
        refs = _id_list(claim["source_ids"], source_ids, "Research packet claim source_ids", PacketError,
                        nonempty=claim["kind"] != "unknown")
        ids.add(claim["id"])
        out.append({"id": claim["id"], "kind": claim["kind"], "text": claim["text"], "source_ids": refs})
    return out


def _questions(value, claims: list) -> list:
    if not (isinstance(value, list) and value):
        raise PacketError("Research packet questions must be a non-empty list")
    kinds = {c["id"]: c["kind"] for c in claims}
    out, ids = [], set()
    for question in value:
        _fields(question, QUESTION_FIELDS, "Research packet question", PacketError)
        if not _token(question["id"]) or question["id"] in ids:
            raise PacketError("Research packet question ids must be distinct safe tokens")
        if type(question["blocking"]) is not bool:  # an integer standing in for a boolean is refused
            raise PacketError("Research packet question blocking must be a boolean")
        if question["status"] not in QUESTION_STATUSES or not _text(question["question"], 4000):
            raise PacketError("Research packet question needs text and a status of answered or unknown")
        refs = _id_list(question["claim_ids"], set(kinds), "Research packet question claim_ids", PacketError,
                        nonempty=question["status"] == "answered")
        if question["status"] == "answered" and any(kinds[c] == "unknown" for c in refs):
            raise PacketError("Research packet answered question cites only non-unknown claims")
        if question["status"] == "unknown" and question["blocking"]:
            # Debate does not start on a blocking unknown; research first (INV-DGE-001).
            raise PacketError("Research packet has a blocking unresolved question")
        ids.add(question["id"])
        out.append({"id": question["id"], "question": question["question"], "blocking": question["blocking"],
                    "status": question["status"], "claim_ids": refs})
    return out


def packet_digest(packet: dict) -> str:
    return digest(packet)


def source_binding(source: dict, mode, data: bytes) -> dict:
    """One pinned source against the Git object at base: regular blob and exact bytes, or refusal.
    Matching bytes prove provenance of the text, not its truth or that any fetch was executed."""
    if mode != "100644":
        raise PacketError("Research packet source is not a regular tracked file at base")
    observed = hashlib.sha256(data).hexdigest()
    if observed != source["sha256"]:
        raise PacketError("Research packet source bytes at base do not match sha256")
    return {"id": source["id"], "path": source["path"], "sha256": observed, "bytes": len(data)}


# ----- events ------------------------------------------------------------------------------------
def validate_event(document) -> dict:
    """Envelope-level validation without session context; payload shape is checked per role."""
    _fields(document, EVENT_FIELDS, "Debate event", EventError)
    if document["schema"] != EVENT_SCHEMA:
        raise EventError("Debate event schema is not " + EVENT_SCHEMA)
    if not _token(document["id"]):
        raise EventError("Debate event id must be a short safe token")
    if type(document["expected_version"]) is not int or document["expected_version"] < 0:
        raise EventError("Debate event expected_version must be a non-negative integer")
    if type(document["packet_digest"]) is not str or SHA256.fullmatch(document["packet_digest"]) is None:
        raise EventError("Debate event packet_digest must be 64 lowercase hex")
    if type(document["round"]) is not int or not 1 <= document["round"] <= MAX_ROUNDS:
        raise EventError("Debate event round must be an integer from 1 to " + str(MAX_ROUNDS))
    if document["role"] not in ROLES:
        raise EventError("Debate event role must be proposer, attacker or arbiter")
    if not isinstance(document["payload"], dict):
        raise EventError("Debate event payload must be an object")
    return {"schema": EVENT_SCHEMA, "id": document["id"], "expected_version": document["expected_version"],
            "packet_digest": document["packet_digest"], "round": document["round"], "role": document["role"],
            "payload": document["payload"]}


def event_digest(event: dict) -> str:
    return digest(event)


def validate_payload(role: str, payload: dict, *, claim_ids: set, criteria: list, findings: list,
                     known_finding_ids: set = frozenset()) -> dict:
    """Strict per-role payload. `known_finding_ids` are every finding id already recorded in the
    session (attacker only): a finding's identity, content and severity are fixed for the session, so
    no later round may reuse an id to replace or downgrade it. `findings` are the open findings the
    arbiter must cover (arbiter only): the unresolved findings carried from earlier rounds plus the
    current round's findings, each named exactly once."""
    if role == "proposer":
        _fields(payload, {"summary", "claim_ids"}, "Proposer payload", EventError)
        if not _text(payload["summary"]):
            raise EventError("Proposer payload summary is required text")
        refs = _id_list(payload["claim_ids"], claim_ids, "Proposer payload claim_ids", EventError)
        return {"summary": payload["summary"], "claim_ids": refs}
    if role == "attacker":
        _fields(payload, {"findings"}, "Attacker payload", EventError)
        if not isinstance(payload["findings"], list):
            raise EventError("Attacker payload findings must be a list")
        out, ids = [], set()
        for finding in payload["findings"]:
            _fields(finding, FINDING_FIELDS, "Attacker finding", EventError)
            if not _token(finding["id"]) or finding["id"] in ids:
                raise EventError("Attacker finding ids must be distinct safe tokens")
            if finding["id"] in known_finding_ids:
                raise EventError("Attacker finding id reuses a finding already recorded in this session")
            if finding["criterion"] not in criteria:
                raise EventError("Attacker finding criterion must be an exact plan acceptance item")
            if finding["severity"] not in SEVERITIES or not _text(finding["scenario"]):
                raise EventError("Attacker finding needs a severity of critical or minor and a scenario")
            refs = _id_list(finding["claim_ids"], claim_ids, "Attacker finding claim_ids", EventError)
            ids.add(finding["id"])
            out.append({"id": finding["id"], "criterion": finding["criterion"], "severity": finding["severity"],
                        "scenario": finding["scenario"], "claim_ids": refs})
        return {"findings": out}
    _fields(payload, {"verdict", "rationale", "dispositions", "research_question"}, "Arbiter payload", EventError)
    if payload["verdict"] not in VERDICTS or not _text(payload["rationale"]):
        raise EventError("Arbiter payload needs a known verdict and a rationale")
    question = payload["research_question"]
    if payload["verdict"] == "needs_research":
        if not _text(question, 4000):
            raise EventError("Arbiter needs_research requires a concrete research_question")
    elif question is not None:
        raise EventError("Arbiter research_question must be null unless the verdict is needs_research")
    if not isinstance(payload["dispositions"], list):
        raise EventError("Arbiter dispositions must be a list")
    severity = {f["id"]: f["severity"] for f in findings}
    seen, out = set(), []
    for disposition in payload["dispositions"]:
        _fields(disposition, DISPOSITION_FIELDS, "Arbiter disposition", EventError)
        finding_id = disposition["finding_id"]
        if finding_id not in severity or finding_id in seen:
            raise EventError("Arbiter dispositions must name each open finding (carried and current) exactly once")
        if disposition["decision"] not in DECISIONS or not _text(disposition["reason"], 4000):
            raise EventError("Arbiter disposition needs a decision of resolved, deferred or blocking and a reason")
        if disposition["decision"] == "deferred" and severity[finding_id] == "critical":
            raise EventError("Arbiter cannot defer a critical finding")
        seen.add(finding_id)
        out.append({"finding_id": finding_id, "decision": disposition["decision"], "reason": disposition["reason"]})
    if seen != set(severity):
        # A carried unresolved finding the current attacker omitted still needs an explicit decision.
        raise EventError("Arbiter dispositions must name each open finding (carried and current) exactly once")
    if payload["verdict"] == "accept" and any(d["decision"] == "blocking" for d in out):
        raise EventError("Arbiter cannot accept with a blocking finding")
    return {"verdict": payload["verdict"], "rationale": payload["rationale"], "dispositions": out,
            "research_question": question}


def verdict_transition(verdict: str, round_number: int, max_rounds: int) -> dict:
    """Terminal or next-round state for an arbiter verdict; the cap ends the session, never retries."""
    if verdict == "accept":
        return {"state": "design_approved", "round": round_number}
    if verdict == "reject":
        return {"state": "rejected", "round": round_number}
    if verdict == "needs_research":
        return {"state": "needs_research", "round": round_number}
    if round_number >= max_rounds:
        return {"state": "exhausted", "round": round_number}
    return {"state": "proposal", "round": round_number + 1}


# ----- implementation gate ----------------------------------------------------------------------
def design_gate_reason(session, design: dict, *, repository: str, base_revision: str, plan: dict, now: str):
    """Fixed reason code, or None when the session authorizes exactly this plan (INV-DGE-001)."""
    if not isinstance(session, dict):
        return "design_missing"
    if session.get("packet_digest") != design["packet_digest"]:
        return "design_digest_mismatch"
    if session.get("state") == "needs_research":
        return "design_needs_research"
    if session.get("state") != "design_approved":
        return "design_not_approved"
    if session.get("unresolved"):
        # Defence in depth: an approved row that still carries an unresolved finding never authorizes.
        return "design_unresolved"
    if session.get("repository") != repository:
        return "design_repository_mismatch"
    if session.get("base_revision") != base_revision:
        return "design_base_mismatch"
    if session.get("plan") != plan:
        return "design_plan_mismatch"
    if not isinstance(session.get("deadline"), str) or expired(session["deadline"], now):
        return "design_expired"
    return None
