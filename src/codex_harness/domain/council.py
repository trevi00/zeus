"""Topic-bound two-lead council (INV-COUNCIL-001): the opt-in `urn:zeus:autonomous:2` manifest, the
bounded read-only database snapshot envelope, the DBA report and the research-lead, improvement-lead
and conductor output shapes, plus the version-aware run profile the application threads through.

v1 (`domain.autonomous`) is untouched: its constants, role names and six-start cap stay the source of
truth for `urn:zeus:autonomous:1`; this module adds a second profile next to it and never mutates the
legacy constants. The council's debate events reuse the existing proposer/attacker/arbiter slots
INTERNALLY (one DGE validator, one session state machine); the real agent identities are
`lead:dba`, `lead:research`, `lead:improvement` and `conductor`, and the improvement lead's full
proposal is retained in its role output and handed to the conductor, never reduced to findings only.

The snapshot is an observation of explicitly selected PostgreSQL records at one repeatable-read
instant: per key found/missing/unknown, the SHA-256 of the canonical row when found and a small
whitelist of validated status fields. No row bodies, free text, credentials or DSNs leave the
adapter; the domain functions here receive bodies only to reduce them. A missing key means absent at
that snapshot in the explicit scope, nothing more. Nothing here connects, calls a model or writes.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from codex_harness.domain.autonomous import (
    ARBITER,
    ATTACKER,
    FIELDS,
    MAX_STARTS,
    PROMOTED_NAMESPACE,
    PROPOSER,
    RESEARCHER,
    ROLE_AGENTS,
    SCHEMA_AUTONOMOUS,
    SSOT_DECISIONS,
    STAGES,
    TERMINAL,
    AutonomousManifestError,
    attacker_findings,
    validate_autonomous_manifest,
)
from codex_harness.domain.dge import expired, parse_deadline
from codex_harness.domain.model import ContractError, conductor_self_arbitration, digest
from codex_harness.domain.operation import ID, REVISION

SCHEMA_AUTONOMOUS_V2 = "urn:zeus:autonomous:2"
SNAPSHOT_SCHEMA = "urn:zeus:db-snapshot:1"
ISOLATION = "repeatable read read only"
FIELDS_V2 = FIELDS | {"current_state"}
CURRENT_STATE_FIELDS = {"records", "max_age_seconds"}
BUCKETS = ("tasks", "operations", "autonomous_runs", "promotions")
MAX_RECORDS, MIN_AGE_SECONDS, MAX_AGE_SECONDS = 20, 60, 3600
# Council roles and the REAL agent that executes each; `researcher` is the unchanged packet author.
DBA, RESEARCH_LEAD, IMPROVEMENT_LEAD, CONDUCTOR_ROLE = "dba", "research_lead", "improvement_lead", "conductor"
COUNCIL_ORDER = (RESEARCHER, DBA, RESEARCH_LEAD, IMPROVEMENT_LEAD, CONDUCTOR_ROLE)
COUNCIL_DEBATE = (RESEARCH_LEAD, IMPROVEMENT_LEAD, CONDUCTOR_ROLE)
COUNCIL_AGENTS = {RESEARCHER: ROLE_AGENTS[RESEARCHER], DBA: "lead:dba", RESEARCH_LEAD: "lead:research",
                  IMPROVEMENT_LEAD: "lead:improvement", CONDUCTOR_ROLE: "conductor"}
AGENTS = {**ROLE_AGENTS, **COUNCIL_AGENTS}   # every role either profile may dispatch, by role name
# Internal DGE compatibility slot per council debate role: the session validator and state machine are reused.
INTERNAL_SLOT = {RESEARCH_LEAD: PROPOSER, IMPROVEMENT_LEAD: ATTACKER, CONDUCTOR_ROLE: ARBITER}
RESPONSIBILITY = {RESEARCHER: "SSOT research at base; frozen packet",
                  DBA: "interpret the read-only snapshot; report names snapshot_digest, claim_ids, unknowns",
                  RESEARCH_LEAD: "proposal from packet and frozen DBA report",
                  IMPROVEMENT_LEAD: "constructive alternative (reuse/improve/migrate/new, transition) plus findings",
                  CONDUCTOR_ROLE: "arbitration by the existing verdict and disposition rules"}
MAX_STARTS_V2 = 7        # research + DBA + two leads + conductor + implement + review
STAGES_V2 = ("research", "packet", "snapshot", DBA, RESEARCH_LEAD, IMPROVEMENT_LEAD, CONDUCTOR_ROLE,
             "implementation", "promotion")
# Whitelisted status/stage fields per bucket. Every field is REQUIRED and checked against a FINITE domain
# vocabulary or a known identity syntax, never "any token-shaped string": a row whose field is absent, null
# where not allowed or outside its vocabulary is reported unknown. Nothing else of a row is ever copied out.
STATUS_FIELDS = {"tasks": ("status", "agent"), "operations": ("status", "lead_accepted"),
                 "autonomous_runs": ("status", "stage"), "promotions": ("repository",)}
BOOLEAN_FIELDS = {"lead_accepted"}   # true / false / null (null: the operation is not decided yet)
TASK_STATUSES = frozenset({"queued", "pending", "retry", "running", "succeeded", "failed", "blocked", "expired",
                           "superseded", "inspection_blocked", "cancelled"})  # = local_cycle.EXECUTION_STATUSES
OPERATION_STATUSES = frozenset({"running", "accepted", "rejected", "failed", "unknown", "exhausted"})
RUN_STATUSES = frozenset({"running"} | TERMINAL)
RUN_STAGES = frozenset(STAGES) | frozenset(STAGES_V2)
# Known actor syntax: the conductor, or `<lead|worker>:<name>`; the colon is part of a normal identity.
ACTOR = re.compile(r"^(?:conductor|(?:lead|worker):[a-z][a-z0-9_-]{0,63})$")
# Known namespace syntax: a promoted repository is `verified:<run id>` and nothing else.
NAMESPACE_REF = re.compile("^" + re.escape(PROMOTED_NAMESPACE) + r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
FIELD_VALUES = {("tasks", "status"): TASK_STATUSES, ("tasks", "agent"): ACTOR,
                ("operations", "status"): OPERATION_STATUSES,
                ("autonomous_runs", "status"): RUN_STATUSES, ("autonomous_runs", "stage"): RUN_STAGES,
                ("promotions", "repository"): NAMESPACE_REF}
RECORD_STATES = ("found", "missing", "unknown")
DBA_REPORT_FIELDS = {"snapshot_digest", "summary", "claim_ids", "unknowns"}
RESEARCH_LEAD_FIELDS = {"summary", "claim_ids", "snapshot_digest", "report_digest"}
IMPROVEMENT_LEAD_FIELDS = {"summary", "decision", "rationale", "transition", "claim_ids", "findings",
                           "snapshot_digest", "report_digest"}
CONDUCTOR_FIELDS = {"verdict", "rationale", "dispositions", "research_question", "snapshot_digest", "report_digest"}
SNAPSHOT_FIELDS = {"schema", "topic", "run_id", "base_revision", "selection", "isolation", "observed_at", "expires_at",
                   "max_age_seconds", "database_identity", "records"}
SHA256_LENGTH = 64


class SnapshotError(ContractError):
    """A snapshot envelope that is not the frozen observation: `snapshot_corrupt`, `snapshot_mismatch`
    or `snapshot_stale`. The message is the code, never row content."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _text(value, limit=4000) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def _token(value) -> bool:
    return type(value) is str and ID.fullmatch(value) is not None


def _sha256(value) -> bool:
    return type(value) is str and len(value) == SHA256_LENGTH and all(c in "0123456789abcdef" for c in value)


def field_valid(bucket: str, name: str, value) -> bool:
    """One rule for the producer (`snapshot_records`) and the consumer (`validate_snapshot`): a boolean
    field is true/false/null; every other whitelisted field is a string of its finite vocabulary or known
    identity syntax. An arbitrary token-shaped string is not valid and neither is a missing value."""
    if name in BOOLEAN_FIELDS:
        return value is None or type(value) is bool
    allowed = FIELD_VALUES.get((bucket, name))
    if allowed is None or type(value) is not str:
        return False
    return value in allowed if isinstance(allowed, frozenset) else allowed.fullmatch(value) is not None


# ----- manifest -----------------------------------------------------------------------------------
def validate_current_state(value) -> dict:
    """1..20 unique explicit (bucket, id) records from the four observable buckets and an integer
    max age of 60..3600 seconds; refused before any provider or database access."""
    if not isinstance(value, dict) or set(value) != CURRENT_STATE_FIELDS:
        raise AutonomousManifestError("Autonomous manifest current_state needs records and max_age_seconds")
    records, age = value["records"], value["max_age_seconds"]
    if type(age) is not int or not MIN_AGE_SECONDS <= age <= MAX_AGE_SECONDS:
        raise AutonomousManifestError("Autonomous manifest current_state.max_age_seconds must be an integer of 60..3600")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise AutonomousManifestError("Autonomous manifest current_state.records must hold 1..20 records")
    keys, out = set(), []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"bucket", "id"}:
            raise AutonomousManifestError("Autonomous manifest current_state record needs bucket and id only")
        if record["bucket"] not in BUCKETS or not _token(record["id"]):
            raise AutonomousManifestError("Autonomous manifest current_state record needs a known bucket and a safe id")
        key = (record["bucket"], record["id"])
        if key in keys:
            raise AutonomousManifestError("Autonomous manifest current_state records must be unique")
        keys.add(key)
        out.append({"bucket": record["bucket"], "id": record["id"]})
    return {"records": out, "max_age_seconds": age}


def validate_council_manifest(document, policy) -> dict:
    """`urn:zeus:autonomous:2`: the v1 fields validated by the v1 validator (one copy of those rules)
    plus `current_state`. The canonical form of the v1 part is unchanged."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_AUTONOMOUS_V2:
        raise AutonomousManifestError("Autonomous manifest schema is not " + SCHEMA_AUTONOMOUS_V2)
    unknown, missing = sorted(set(document) - FIELDS_V2), sorted(FIELDS_V2 - set(document))
    if unknown or missing:
        raise AutonomousManifestError("Autonomous manifest has unknown or missing fields: "
                                      + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))
    base = validate_autonomous_manifest({**{k: document[k] for k in FIELDS - {"schema"}}, "schema": SCHEMA_AUTONOMOUS}, policy)
    return {**base, "schema": SCHEMA_AUTONOMOUS_V2, "current_state": validate_current_state(document["current_state"])}


def validate_any_manifest(document, policy) -> dict:
    """Version dispatch for the CLI: v1 and v2 each keep their own validator; anything else is refused."""
    schema = document.get("schema") if isinstance(document, dict) else None
    if schema == SCHEMA_AUTONOMOUS:
        return validate_autonomous_manifest(document, policy)
    if schema == SCHEMA_AUTONOMOUS_V2:
        return validate_council_manifest(document, policy)
    raise AutonomousManifestError("Autonomous manifest schema must be " + SCHEMA_AUTONOMOUS + " or " + SCHEMA_AUTONOMOUS_V2)


def profile(manifest) -> dict:
    """Version-aware role mapping and caps, threaded explicitly instead of mutating legacy constants."""
    if manifest.get("schema") == SCHEMA_AUTONOMOUS_V2:
        return {"version": 2, "max_starts": MAX_STARTS_V2, "agents": dict(COUNCIL_AGENTS), "debate_roles": COUNCIL_DEBATE,
                "slots": dict(INTERNAL_SLOT), "topology": topology()}
    return {"version": 1, "max_starts": MAX_STARTS, "agents": dict(ROLE_AGENTS), "debate_roles": (PROPOSER, ATTACKER, ARBITER),
            "slots": {PROPOSER: PROPOSER, ATTACKER: ATTACKER, ARBITER: ARBITER},
            "topology": {"version": 1, "roles": {r: {"agent": a, "slot": r} for r, a in ROLE_AGENTS.items()}}}


def topology() -> dict:
    """Actual agent and responsibility mapping the receipt, CLI and runbook expose."""
    return {"version": 2, "roles": {role: {"agent": COUNCIL_AGENTS[role], "slot": INTERNAL_SLOT.get(role, role),
                                           "responsibility": RESPONSIBILITY[role]} for role in COUNCIL_ORDER},
            "relay": "lead:dba reports to conductor; the conductor hands the verified report to lead:research and lead:improvement",
            "self_arbitration": "conductor -> conductor dge_role/conductor task and its result only"}


# ----- snapshot -----------------------------------------------------------------------------------
def snapshot_selection(manifest) -> list:
    return [dict(r) for r in manifest["current_state"]["records"]]


def snapshot_records(selection: list, bodies: dict) -> list:
    """Reduce fetched rows to the redacted per-key observation. `bodies` maps (bucket, id) -> row body
    for the keys the read-only transaction returned; a selected key without a row is `missing`, a row
    with a whitelisted field absent or outside its finite vocabulary is `unknown` (never guessed
    successful) and exports its digest only."""
    out = []
    for record in selection:
        key = (record["bucket"], record["id"])
        entry = {"bucket": record["bucket"], "id": record["id"], "state": "missing", "sha256": None, "fields": {}}
        if key in bodies:
            body = bodies[key]
            if not isinstance(body, dict):
                entry["state"] = "unknown"
            else:
                fields = {name: body.get(name) for name in STATUS_FIELDS[record["bucket"]]}
                # Presence is its own requirement: `body.get` turns an absent key into None, which a nullable field accepts.
                valid = all(name in body and field_valid(record["bucket"], name, value) for name, value in fields.items())
                entry.update(state="found" if valid else "unknown", sha256=digest(body), fields=fields if valid else {})
        out.append(entry)
    return out


def snapshot_envelope(*, topic: str, run_id: str, base_revision: str, selection: list, records: list,
                      database_identity: str, observed_at: str, max_age_seconds: int) -> dict:
    """The frozen envelope: topic/run/base bound, selection echoed, one observed_at, an absolute expiry
    and the schema-aware endpoint digest. Content-addressed by `snapshot_digest`."""
    observed = datetime.fromisoformat(parse_deadline(observed_at, SnapshotError))
    expires = (observed + timedelta(seconds=max_age_seconds)).astimezone(timezone.utc).isoformat()
    return validate_snapshot({"schema": SNAPSHOT_SCHEMA, "topic": topic, "run_id": run_id, "base_revision": base_revision,
                              "selection": [dict(r) for r in selection], "isolation": ISOLATION,
                              "observed_at": observed.isoformat(), "expires_at": expires, "max_age_seconds": max_age_seconds,
                              "database_identity": database_identity, "records": records})


def validate_snapshot(document) -> dict:
    """Shape only; refuses anything beyond the redacted fields (no bodies, no free text)."""
    if not isinstance(document, dict) or set(document) != SNAPSHOT_FIELDS or document["schema"] != SNAPSHOT_SCHEMA:
        raise SnapshotError("snapshot_corrupt")
    if not (_text(document["topic"], 400) and _token(document["run_id"]) and type(document["base_revision"]) is str
            and REVISION.fullmatch(document["base_revision"]) and document["isolation"] == ISOLATION
            and _sha256(document["database_identity"]) and type(document["max_age_seconds"]) is int):
        raise SnapshotError("snapshot_corrupt")
    try:
        selection = validate_current_state({"records": document["selection"], "max_age_seconds": document["max_age_seconds"]})
        observed, expires = parse_deadline(document["observed_at"], SnapshotError), parse_deadline(document["expires_at"], SnapshotError)
    except ContractError as exc:
        raise SnapshotError("snapshot_corrupt") from exc
    records = document["records"]
    if not isinstance(records, list) or [(r.get("bucket"), r.get("id")) for r in records if isinstance(r, dict)] \
            != [(r["bucket"], r["id"]) for r in selection["records"]]:
        raise SnapshotError("snapshot_corrupt")
    out = []
    for record in records:
        if set(record) != {"bucket", "id", "state", "sha256", "fields"} or record["state"] not in RECORD_STATES:
            raise SnapshotError("snapshot_corrupt")
        sha, fields = record["sha256"], record["fields"]
        if record["state"] == "missing" and (sha is not None or fields != {}):
            raise SnapshotError("snapshot_corrupt")
        if record["state"] == "found" and not _sha256(sha):
            raise SnapshotError("snapshot_corrupt")
        if record["state"] == "unknown" and (fields != {} or not (sha is None or _sha256(sha))):
            raise SnapshotError("snapshot_corrupt")  # an unknown record exports no field at all
        if not isinstance(fields, dict) or (record["state"] == "found" and set(fields) != set(STATUS_FIELDS[record["bucket"]])):
            raise SnapshotError("snapshot_corrupt")
        if not all(field_valid(record["bucket"], name, value) for name, value in fields.items()):
            raise SnapshotError("snapshot_corrupt")
        out.append({"bucket": record["bucket"], "id": record["id"], "state": record["state"], "sha256": sha, "fields": dict(fields)})
    return {"schema": SNAPSHOT_SCHEMA, "topic": document["topic"], "run_id": document["run_id"],
            "base_revision": document["base_revision"], "selection": selection["records"], "isolation": ISOLATION,
            "observed_at": observed, "expires_at": expires, "max_age_seconds": selection["max_age_seconds"],
            "database_identity": document["database_identity"], "records": out}


def snapshot_digest(envelope: dict) -> str:
    return digest(envelope)


def snapshot_coverage(envelope: dict) -> dict:
    counts = {state: 0 for state in RECORD_STATES}
    for record in envelope["records"]:
        counts[record["state"]] += 1
    return {"selected": len(envelope["records"]), **counts}


def check_snapshot(document, *, expected_digest: str, topic: str, run_id: str, base_revision: str, selection: list,
                   now: str | None) -> dict:
    """The SAME frozen observation, still fresh: shape (`snapshot_corrupt`), digest and topic/run/base/
    selection binding (`snapshot_mismatch`), then age against the frozen expiry (`snapshot_stale`).
    `now=None` is the promotion integrity recheck (age was checked before the implementation started).
    No verdict, refresh or repair is possible here."""
    envelope = validate_snapshot(document)
    if snapshot_digest(envelope) != expected_digest or (envelope["topic"], envelope["run_id"], envelope["base_revision"]) \
            != (topic, run_id, base_revision) or envelope["selection"] != [dict(r) for r in selection]:
        raise SnapshotError("snapshot_mismatch")
    if now is not None and expired(envelope["expires_at"], now):
        raise SnapshotError("snapshot_stale")
    return envelope


# ----- role outputs -------------------------------------------------------------------------------
def _identities(output: dict, identities: dict) -> None:
    """Every downstream role names the exact snapshot (and report) it was given; a swapped or missing
    identity is refused before any event is derived."""
    for key, expected in identities.items():
        if output.get(key) != expected:
            raise ContractError("council_identity_mismatch")


def _claim_refs(value, claim_ids: set, name: str) -> list:
    if not isinstance(value, list) or not all(_token(v) for v in value) or len(set(value)) != len(value) \
            or not set(value) <= set(claim_ids):
        raise ContractError(name + " claim_ids must be distinct known packet claim ids")
    return list(value)


def report_from_dba(output, *, snapshot_digest_value: str, claim_ids: set) -> dict:
    """The DBA report: interpretation bound to the snapshot digest and to known packet claims. It is
    never a new Git-supported fact and never replaces the observation it names."""
    if not isinstance(output, dict) or set(output) != DBA_REPORT_FIELDS:
        raise ContractError("DBA report lacks the required fields")
    _identities(output, {"snapshot_digest": snapshot_digest_value})
    if not _text(output["summary"]):
        raise ContractError("DBA report summary is required text")
    unknowns = output["unknowns"]
    if not isinstance(unknowns, list) or not all(_text(u, 1024) for u in unknowns):
        raise ContractError("DBA report unknowns must hold text")
    return {"snapshot_digest": snapshot_digest_value, "summary": output["summary"],
            "claim_ids": _claim_refs(output["claim_ids"], claim_ids, "DBA report"), "unknowns": list(unknowns)}


def report_digest(report: dict) -> str:
    return digest(report)


def proposal_from_research_lead(output, identities: dict, claim_ids: set) -> dict:
    """Research lead: the proposer payload plus the identities it worked from."""
    if not isinstance(output, dict) or set(output) != RESEARCH_LEAD_FIELDS:
        raise ContractError("Research lead proposal lacks the required fields")
    _identities(output, identities)
    _claim_refs(output["claim_ids"], claim_ids, "Research lead proposal")
    return {"proposal": {k: output[k] for k in sorted(RESEARCH_LEAD_FIELDS)},
            "event_payload": {"summary": output["summary"], "claim_ids": output["claim_ids"]}}


def proposal_from_improvement_lead(output, identities: dict, claim_ids: set) -> dict:
    """Improvement lead: a constructive alternative (summary, reuse/improve/migrate/new, rationale,
    transition for improve/migrate, KNOWN packet claim ids) AND the existing findings. The findings
    become the internal attacker event under the critical-only rule; the full proposal is kept for the
    conductor. The event payload is the RAW findings list: `event_from_role` owns the one conversion
    that folds trigger/impact/mitigation into the scenario, so it is only checked here, never applied
    twice (a converted critical finding has lost the very fields the rule requires)."""
    if not isinstance(output, dict) or set(output) != IMPROVEMENT_LEAD_FIELDS:
        raise ContractError("Improvement lead proposal lacks the required fields")
    _identities(output, identities)
    if output["decision"] not in SSOT_DECISIONS or not _text(output["summary"]) or not _text(output["rationale"]):
        raise ContractError("Improvement lead proposal needs a summary, a rationale and a decision of reuse, improve, migrate or new")
    transition = output["transition"]
    if output["decision"] in {"improve", "migrate"}:
        if not (isinstance(transition, dict) and set(transition) == {"compatibility", "rollback", "retirement"}
                and all(_text(transition[k]) for k in transition)):
            raise ContractError("Improvement lead improve or migrate requires compatibility, rollback and retirement")
    elif transition is not None:
        raise ContractError("Improvement lead transition must be null unless the decision is improve or migrate")
    # The alternative never reaches the DGE validator (only its findings do), so its citations are bound here.
    _claim_refs(output["claim_ids"], claim_ids, "Improvement lead proposal")
    attacker_findings({"findings": output["findings"]})  # refuse early; the result is deliberately not used
    return {"proposal": {k: output[k] for k in sorted(IMPROVEMENT_LEAD_FIELDS)},
            "event_payload": {"findings": [dict(f) for f in output["findings"]]}}


def verdict_from_conductor(output, identities: dict, claim_ids: set | None = None) -> dict:
    """Conductor: the existing arbiter payload plus the identities it arbitrated over."""
    if not isinstance(output, dict) or set(output) != CONDUCTOR_FIELDS:
        raise ContractError("Conductor verdict lacks the required fields")
    _identities(output, identities)
    return {"proposal": {k: output[k] for k in sorted(CONDUCTOR_FIELDS)},
            "event_payload": {k: output[k] for k in ("verdict", "rationale", "dispositions", "research_question")}}


COUNCIL_OUTPUTS = {RESEARCH_LEAD: proposal_from_research_lead, IMPROVEMENT_LEAD: proposal_from_improvement_lead,
                   CONDUCTOR_ROLE: verdict_from_conductor}


def council_output(role: str, output, identities: dict, claim_ids: set) -> dict:
    """`claim_ids` are the frozen packet's claim ids: a lead citing an id the packet does not hold is refused."""
    if role not in COUNCIL_OUTPUTS:
        raise ContractError("Unknown council role")
    return COUNCIL_OUTPUTS[role](output, identities, set(claim_ids))


__all__ = ["AGENTS", "COUNCIL_AGENTS", "COUNCIL_DEBATE", "COUNCIL_ORDER", "CONDUCTOR_ROLE", "DBA", "IMPROVEMENT_LEAD",
           "INTERNAL_SLOT", "MAX_STARTS_V2", "RESEARCH_LEAD", "SCHEMA_AUTONOMOUS_V2", "SNAPSHOT_SCHEMA", "STAGES_V2",
           "SnapshotError", "check_snapshot", "conductor_self_arbitration", "council_output", "field_valid", "profile", "report_digest",
           "report_from_dba", "snapshot_coverage", "snapshot_digest", "snapshot_envelope", "snapshot_records",
           "snapshot_selection", "topology", "validate_any_manifest", "validate_council_manifest",
           "validate_current_state", "validate_snapshot"]
