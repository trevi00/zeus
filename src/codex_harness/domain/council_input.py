"""Bounded inline council input `urn:zeus:council-input:1` (research-program-001, delivery implementation011).

One module owns the byte policy every council producer and consumer applies: the caps are UTF-8 lengths of
the CANONICAL JSON of each value (`domain.model.canonical`: sorted keys, compact separators, `ensure_ascii`
off, so a multi-byte character counts its encoded bytes and JSON escaping of quotes, backslashes and control
characters counts too). They are explicit local byte policy values, never model tokens or capacity:

    packet                 <= 16384   frozen research packet (the whole `packet` object)
    dba_report             <=  4096   normalized DBA report (`report_from_dba` output)
    research_proposal      <=  4096   complete research-lead proposal
    improvement_proposal   <=  8192   complete improvement-lead proposal INCLUDING every finding
    delivery overhead      <=  4096   serialized `council_delivery` minus its present payload components
    host overhead          <=  4096   complete rendered ContextPacket outside the serialized delivery
    required total         <= 40960   = 32768 payload + 4096 + 4096; council window 49152, reserved 8192

Producers (`application/council.py`) refuse an oversized packet before the snapshot or the DBA, an oversized
DBA report before the relay, and an oversized lead proposal before `sessions.submit` or the next role.
Consumers (`adapters/autonomous_roles.py`, `adapters/executor.py`) recheck the full projection and the final
rendered prompt before any provider entry. An overflow is `CouncilInputOverflow`: a typed refusal whose text
is the fixed reason `needs_scope_split:<section>:<observed>/<limit>` and nothing of the content. Nothing here
truncates, summarizes, drops, resizes or retries; raw role evidence stays where the executor stored it.
A missing mandatory field is a different error (`ContractError` from the projection), never an overflow.
The legacy non-council compiler budget (28000 window, 6000 reserved) is recorded here only so the two policies
are named in one place; it is not applied by this module.
"""
from __future__ import annotations

from codex_harness.domain.model import ContractError, canonical

SCHEMA = "urn:zeus:council-input:1"
UNIT = "utf8_bytes_of_canonical_json"
REASON = "needs_scope_split"
PACKET, DBA_REPORT, RESEARCH_PROPOSAL, IMPROVEMENT_PROPOSAL = "packet", "dba_report", "research_proposal", "improvement_proposal"
DELIVERY_OVERHEAD, HOST_OVERHEAD, REQUIRED = "delivery_overhead", "host_overhead", "required"
PAYLOAD_LIMITS = {PACKET: 16384, DBA_REPORT: 4096, RESEARCH_PROPOSAL: 4096, IMPROVEMENT_PROPOSAL: 8192}
PAYLOAD_TOTAL = 32768
LIMITS = {**PAYLOAD_LIMITS, DELIVERY_OVERHEAD: 4096, HOST_OVERHEAD: 4096, REQUIRED: 40960}
COUNCIL_WINDOW, COUNCIL_RESERVED = 49152, 8192
LEGACY_WINDOW, LEGACY_RESERVED = 28000, 6000
MANDATORY_PAYLOAD = (PACKET, DBA_REPORT)
# Which producer role authors each bounded payload; the output instruction names the role's own limit.
PRODUCERS = {PACKET: "researcher", DBA_REPORT: "dba", RESEARCH_PROPOSAL: "research_lead", IMPROVEMENT_PROPOSAL: "improvement_lead"}
# Arithmetic identity of the policy (32768 + 4096 + 4096 = 40960 = 49152 - 8192); the contract test pins it.


class CouncilInputOverflow(ContractError):
    """A bounded section over its cap. `str(exc)` is the fixed reason code with section, observed and limit
    bytes only; the value itself never enters the message, a task error or a run receipt."""

    def __init__(self, section: str, observed: int, limit: int):
        if section not in LIMITS:
            raise ContractError("Unknown council input section")
        self.section, self.observed, self.limit = section, int(observed), int(limit)
        self.reason_code = REASON + ":" + section + ":" + str(self.observed) + "/" + str(self.limit)
        super().__init__(self.reason_code)

    def diagnostics(self) -> dict:
        return {"schema": SCHEMA, "reason": REASON, "section": self.section, "observed_bytes": self.observed,
                "limit_bytes": self.limit, "unit": UNIT}


def canonical_bytes(value) -> int:
    """The one measurement: UTF-8 length of the canonical JSON, escaping included."""
    return len(canonical(value).encode("utf-8"))


def admit(section: str, value) -> int:
    """Measure one payload section against its cap; returns the observed bytes or raises the typed overflow.
    The value is returned nowhere and never modified."""
    if section not in PAYLOAD_LIMITS:
        raise ContractError("Unknown council input section")
    observed = canonical_bytes(value)
    if observed > PAYLOAD_LIMITS[section]:
        raise CouncilInputOverflow(section, observed, PAYLOAD_LIMITS[section])
    return observed


def admit_delivery(delivery) -> dict:
    """Consumer recheck of a complete `council_delivery` projection: every present payload component within
    its cap and the wrapper (serialized projection minus the serialized present components) within the
    delivery overhead. Canonical JSON serializes a nested value byte-identically inside its parent, so the
    subtraction is exact. Missing packet/dba_report is a shape error, not an overflow."""
    if not isinstance(delivery, dict) or not isinstance(delivery.get("inline"), dict):
        raise ContractError("Council input delivery needs an inline object")
    inline = delivery["inline"]
    missing = [k for k in MANDATORY_PAYLOAD if k not in inline]
    if missing:
        raise ContractError("Council input missing: " + ", ".join(missing))
    sections = {k: admit(k, inline[k]) for k in PAYLOAD_LIMITS if k in inline}
    payload = sum(sections.values())
    if payload > PAYLOAD_TOTAL:  # unreachable while the per-section caps sum to the total; kept as the stated bound
        raise CouncilInputOverflow(REQUIRED, payload, PAYLOAD_TOTAL)
    total = canonical_bytes(delivery)
    overhead = total - payload
    if overhead > LIMITS[DELIVERY_OVERHEAD]:
        raise CouncilInputOverflow(DELIVERY_OVERHEAD, overhead, LIMITS[DELIVERY_OVERHEAD])
    return {"schema": SCHEMA, "unit": UNIT, "sections": sections, "payload_bytes": payload,
            "delivery_bytes": total, "delivery_overhead_bytes": overhead}


def admit_required(rendered_bytes: int, delivery_bytes: int) -> dict:
    """Final consumer gate on the COMPLETE rendered prompt (ids, paths, recovery, skills and evidence included):
    everything outside the serialized delivery is the host overhead, and the whole must fit the usable window."""
    if type(rendered_bytes) is not int or type(delivery_bytes) is not int or delivery_bytes < 0 or rendered_bytes < delivery_bytes:
        raise ContractError("Council input measurements must be non-negative integers with the delivery inside the prompt")
    host = rendered_bytes - delivery_bytes
    if host > LIMITS[HOST_OVERHEAD]:
        raise CouncilInputOverflow(HOST_OVERHEAD, host, LIMITS[HOST_OVERHEAD])
    if rendered_bytes > LIMITS[REQUIRED]:
        raise CouncilInputOverflow(REQUIRED, rendered_bytes, LIMITS[REQUIRED])
    return {"schema": SCHEMA, "unit": UNIT, "required_bytes": rendered_bytes, "delivery_bytes": delivery_bytes,
            "host_overhead_bytes": host, "limit_bytes": LIMITS[REQUIRED]}


def council_budget() -> tuple:
    """The council-only compiler budget `(window, reserved)`; the legacy pair stays with its callers."""
    return COUNCIL_WINDOW, COUNCIL_RESERVED


def policy_manifest() -> dict:
    """Additive, compatibility-safe statement of the policy for receipts and documentation."""
    return {"schema": SCHEMA, "unit": UNIT, "reason": REASON, "limits": dict(LIMITS), "payload_total": PAYLOAD_TOTAL,
            "window": COUNCIL_WINDOW, "reserved": COUNCIL_RESERVED, "usable": COUNCIL_WINDOW - COUNCIL_RESERVED,
            "legacy": {"window": LEGACY_WINDOW, "reserved": LEGACY_RESERVED},
            "note": "local byte policy values, not model tokens or capacity; raw originals are never truncated"}


def output_limit(section: str) -> str:
    """The producer-facing sentence for one bounded output: the limit, the unit and the rule that concision
    never drops a finding or an unknown."""
    if section not in PAYLOAD_LIMITS:
        raise ContractError("Unknown council input section")
    what = {PACKET: "The frozen packet built from your sources, claims and questions plus the host envelope",
            DBA_REPORT: "Your report", RESEARCH_PROPOSAL: "Your complete proposal",
            IMPROVEMENT_PROPOSAL: "Your complete proposal including every finding"}[section]
    return (what + " is admitted only up to " + str(PAYLOAD_LIMITS[section]) + " UTF-8 bytes of canonical JSON "
            "(escaping and multi-byte text count); an oversized output stops the council. Be concise and factual, "
            "and keep every finding and unknown: never drop or relabel one to fit.")


__all__ = ["COUNCIL_RESERVED", "COUNCIL_WINDOW", "DBA_REPORT", "DELIVERY_OVERHEAD", "HOST_OVERHEAD",
           "IMPROVEMENT_PROPOSAL", "LEGACY_RESERVED", "LEGACY_WINDOW", "LIMITS", "PACKET", "PAYLOAD_LIMITS", "PAYLOAD_TOTAL",
           "PRODUCERS", "REASON", "REQUIRED", "RESEARCH_PROPOSAL", "SCHEMA", "UNIT", "CouncilInputOverflow", "admit",
           "admit_delivery", "admit_required", "canonical_bytes", "council_budget", "output_limit", "policy_manifest"]
