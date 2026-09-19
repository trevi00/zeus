"""Bounded inline council input `urn:zeus:council-input:2` (research-program-001, Implementation013: shared pool
with ordered future reservations; replaces the v1 isolated section ceilings of implementation011/012).

One module owns the byte policy every council producer and consumer applies. The unit is the UTF-8 length of the
CANONICAL JSON of each value (`domain.model.canonical`: sorted keys, compact separators, `ensure_ascii` off, so a
multi-byte character counts its encoded bytes and JSON escaping of quotes, backslashes and control characters
counts too). These are explicit local byte policy values, never model tokens or capacity.

The four payload components share ONE pool of 32768 bytes in a fixed production order, each with a default
RESERVATION (not a ceiling) that is held for it until it is actually produced:

    order      packet 16384 -> dba_report 4096 -> research_proposal 4096 -> improvement_proposal 8192
    rule       for every nonempty contiguous prefix of that order:
                   sum(canonical bytes of the actual prefix) + reservations of the absent later components <= 32768
    allowance  of the current component = 32768 - actual earlier bytes - reservations of the later components

Earlier unused capacity is therefore available downstream, while future capacity is never spent twice: a
producer's allowance depends only on the exact earlier values, never on a value that does not exist yet. A
missing earlier value is a contract error, never treated as empty; holes, unknown keys, out-of-order stage
arguments and components beyond a consumer role's prefix are contract errors too (`ContractError`, distinct
from overflow). The unchanged fixed ceilings are the delivery wrapper (serialized `council_delivery` minus its
present payload components) <= 4096, the host overhead (complete rendered ContextPacket outside the serialized
delivery) <= 4096 and the required total <= 40960 = 32768 + 4096 + 4096 = council window 49152 - reserved 8192.

Producers (`application/council.py`) admit the frozen packet before the snapshot or the DBA, the normalized DBA
report before the relay, and each lead's complete derived proposal before `sessions.submit` or the next role,
each against the prefix committed so far. Consumers (`adapters/autonomous_roles.py`, `adapters/executor.py`)
recheck the role's own contiguous prefix (research_lead: packet+report; improvement_lead adds the research
proposal; conductor the improvement proposal) under the SAME rule, future reservations included, plus the
wrapper and the final rendered prompt before any provider entry. An overflow is `CouncilInputOverflow`: a typed
refusal whose text is the fixed reason `needs_scope_split:<section>:<observed>/<allowance>` and nothing of the
content. Nothing here truncates, summarizes, drops, resizes or retries; raw role evidence stays where the
executor stored it. Historical v1 receipts keep their original meaning; this module names v2 in every new
manifest and receipt. The legacy non-council compiler budget (28000 window, 6000 reserved) is recorded here
only so the two policies are named in one place; it is not applied by this module.
"""
from __future__ import annotations

from codex_harness.domain.council import CONDUCTOR_ROLE, IMPROVEMENT_LEAD, RESEARCH_LEAD
from codex_harness.domain.model import ContractError, canonical

SCHEMA = "urn:zeus:council-input:2"
PREVIOUS_SCHEMA = "urn:zeus:council-input:1"   # historical receipts and files keep this name and its meaning
UNIT = "utf8_bytes_of_canonical_json"
REASON = "needs_scope_split"
PACKET, DBA_REPORT, RESEARCH_PROPOSAL, IMPROVEMENT_PROPOSAL = "packet", "dba_report", "research_proposal", "improvement_proposal"
DELIVERY_OVERHEAD, HOST_OVERHEAD, REQUIRED = "delivery_overhead", "host_overhead", "required"
# Declared production order and the default reservation each component holds until it is actually produced.
ORDER = (PACKET, DBA_REPORT, RESEARCH_PROPOSAL, IMPROVEMENT_PROPOSAL)
RESERVATIONS = {PACKET: 16384, DBA_REPORT: 4096, RESEARCH_PROPOSAL: 4096, IMPROVEMENT_PROPOSAL: 8192}
PAYLOAD_POOL = 32768
# Fixed ceilings outside the pool; the arithmetic identity (32768 + 4096 + 4096 = 40960 = 49152 - 8192) is pinned by test.
LIMITS = {DELIVERY_OVERHEAD: 4096, HOST_OVERHEAD: 4096, REQUIRED: 40960}
SECTIONS = ORDER + (DELIVERY_OVERHEAD, HOST_OVERHEAD, REQUIRED)
COUNCIL_WINDOW, COUNCIL_RESERVED = 49152, 8192
LEGACY_WINDOW, LEGACY_RESERVED = 28000, 6000
# Which producer role authors each bounded payload; the role's output instruction names its computed allowance.
PRODUCERS = {PACKET: "researcher", DBA_REPORT: "dba", RESEARCH_PROPOSAL: "research_lead", IMPROVEMENT_PROPOSAL: "improvement_lead"}
# The contiguous prefix each consumer role receives inline; anything beyond it is an injected future component.
ROLE_PREFIX = {RESEARCH_LEAD: ORDER[:2], IMPROVEMENT_LEAD: ORDER[:3], CONDUCTOR_ROLE: ORDER}


class CouncilInputOverflow(ContractError):
    """A section over its allowance. `str(exc)` is the fixed reason code with section, observed and allowance
    bytes only; the value itself never enters the message, a task error or a run receipt."""

    def __init__(self, section: str, observed: int, limit: int):
        if section not in SECTIONS:
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


def preceding(section: str) -> tuple:
    """The ordered components a producer must have committed before `section`."""
    if section not in ORDER:
        raise ContractError("Unknown council input section")
    return ORDER[:ORDER.index(section)]


def _later_reservation(section: str) -> int:
    return sum(RESERVATIONS[s] for s in ORDER[ORDER.index(section) + 1:])


def _prefix(values) -> tuple:
    """The ordered components of a nonempty contiguous prefix, or the contract error that names the defect:
    unknown keys, a hole (an earlier component missing) or nothing at all. Never fills a missing value."""
    if not isinstance(values, dict):
        raise ContractError("Council input prefix must be an object of ordered components")
    unknown = sorted(k for k in values if k not in ORDER)
    if unknown:
        raise ContractError("Unknown council input section: " + ", ".join(str(k) for k in unknown))
    if not values:
        raise ContractError("Council input prefix is empty")
    present = ORDER[:max(ORDER.index(k) for k in values) + 1]
    missing = [k for k in present if k not in values]
    if missing:
        raise ContractError("Council input missing: " + ", ".join(missing))
    return present


def admit_prefix(values: dict) -> dict:
    """The one admission rule, applied to a contiguous prefix in production order: each component in turn
    against its allowance (pool minus the actual earlier bytes minus the reservations of the later components),
    so an earlier stage is never trusted on a producer's word. Returns the measurements or raises the typed
    overflow naming the first component over its allowance. A pure calculation: no shared state, no credit
    carried between calls."""
    present = _prefix(values)
    sections, spent = {}, 0
    for section in present:
        observed = canonical_bytes(values[section])
        room = PAYLOAD_POOL - spent - _later_reservation(section)
        if observed > room:
            raise CouncilInputOverflow(section, observed, room)
        sections[section] = observed
        spent += observed
    reserved = _later_reservation(present[-1])
    return {"schema": SCHEMA, "unit": UNIT, "sections": sections, "payload_bytes": spent, "reserved_bytes": reserved,
            "payload_pool": PAYLOAD_POOL}


def _earlier(section: str, earlier) -> dict:
    """The exact earlier components a producer at `section` must hand in: no more, no less, no later one."""
    expected = preceding(section)
    if not isinstance(earlier, dict):
        raise ContractError("Council input earlier components must be an object")
    if tuple(k for k in ORDER if k in earlier) != expected or any(k not in ORDER for k in earlier):
        raise ContractError("Council input for " + section + " needs exactly the earlier components: "
                            + (", ".join(expected) or "none"))
    return {k: earlier[k] for k in expected}


def allowance(section: str, earlier) -> int:
    """The current-stage allowance from the exact earlier values (which are re-admitted, never trusted): pool minus
    their actual bytes minus the reservations of every later component. Future values play no part."""
    values = _earlier(section, earlier)
    spent = admit_prefix(values)["payload_bytes"] if values else 0
    return PAYLOAD_POOL - spent - _later_reservation(section)


def admit(section: str, value, earlier) -> int:
    """Producer admission of one component against the prefix committed so far; returns its observed bytes or
    raises the typed overflow. The value is returned nowhere and never modified."""
    return admit_prefix({**_earlier(section, earlier), section: value})["sections"][section]


def admit_delivery(delivery, role: str) -> dict:
    """Consumer recheck of a complete `council_delivery` projection for one debate role: the inline components
    must be exactly the role's contiguous prefix (a missing one is a shape error, one beyond the prefix an
    injected future component), that prefix passes the same reservation rule (future reservations included),
    and the wrapper (serialized projection minus the serialized present components) fits the delivery overhead.
    Canonical JSON serializes a nested value byte-identically inside its parent, so the subtraction is exact."""
    if role not in ROLE_PREFIX:
        raise ContractError("Council input delivery names no debate role")
    if not isinstance(delivery, dict) or not isinstance(delivery.get("inline"), dict):
        raise ContractError("Council input delivery needs an inline object")
    inline = delivery["inline"]
    if inline.get("role") != role:
        raise ContractError("Council input delivery role mismatch")
    prefix = ROLE_PREFIX[role]
    missing = [k for k in prefix if k not in inline]
    if missing:
        raise ContractError("Council input missing: " + ", ".join(missing))
    beyond = [k for k in ORDER if k in inline and k not in prefix]
    if beyond:
        raise ContractError("Council input beyond the " + role + " prefix: " + ", ".join(beyond))
    measured = admit_prefix({k: inline[k] for k in prefix})
    total = canonical_bytes(delivery)
    overhead = total - measured["payload_bytes"]
    if overhead > LIMITS[DELIVERY_OVERHEAD]:
        raise CouncilInputOverflow(DELIVERY_OVERHEAD, overhead, LIMITS[DELIVERY_OVERHEAD])
    return {**measured, "role": role, "delivery_bytes": total, "delivery_overhead_bytes": overhead}


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
    """Additive, compatibility-safe statement of the policy for receipts and documentation: the payload numbers
    are reservations inside one shared pool, not limits; only the overheads and the required total are limits."""
    return {"schema": SCHEMA, "unit": UNIT, "reason": REASON, "order": list(ORDER), "reservations": dict(RESERVATIONS),
            "payload_pool": PAYLOAD_POOL, "limits": dict(LIMITS), "window": COUNCIL_WINDOW, "reserved": COUNCIL_RESERVED,
            "usable": COUNCIL_WINDOW - COUNCIL_RESERVED, "legacy": {"window": LEGACY_WINDOW, "reserved": LEGACY_RESERVED},
            "previous": PREVIOUS_SCHEMA,
            "note": "local byte policy values, not model tokens or capacity; payload numbers are reservations in one "
                    "shared pool, not per-section limits; raw originals are never truncated"}


def output_limit(section: str, earlier) -> str:
    """The producer-facing sentence for one bounded output: the allowance computed by the same rule from the exact
    earlier values, the unit, what the limit covers (the normalized or derived value, not raw prose alone) and the
    rule that concision never drops a finding or an unknown."""
    room = allowance(section, earlier)
    spent = PAYLOAD_POOL - room - _later_reservation(section)
    what = {PACKET: "The frozen packet the council derives from your sources, claims, questions and the host envelope",
            DBA_REPORT: "Your report as the council normalizes it (snapshot_digest, summary, claim_ids, unknowns)",
            RESEARCH_PROPOSAL: "Your complete proposal as the council derives it",
            IMPROVEMENT_PROPOSAL: "Your complete proposal as the council derives it, every finding included"}[section]
    return (what + " is admitted only up to " + str(room) + " UTF-8 bytes of canonical JSON (escaping and multi-byte "
            "text count): the shared council pool of " + str(PAYLOAD_POOL) + " bytes minus " + str(spent) + " bytes "
            "committed by earlier stages and " + str(_later_reservation(section)) + " bytes reserved for later stages. "
            "The limit covers that normalized or derived value, not merely your raw prose; an oversized output stops "
            "the council. Be concise and factual, and keep every finding and unknown: never drop or relabel one to fit.")


__all__ = ["COUNCIL_RESERVED", "COUNCIL_WINDOW", "DBA_REPORT", "DELIVERY_OVERHEAD", "HOST_OVERHEAD",
           "IMPROVEMENT_PROPOSAL", "LEGACY_RESERVED", "LEGACY_WINDOW", "LIMITS", "ORDER", "PACKET", "PAYLOAD_POOL",
           "PREVIOUS_SCHEMA", "PRODUCERS", "REASON", "REQUIRED", "RESEARCH_PROPOSAL", "RESERVATIONS", "ROLE_PREFIX",
           "SCHEMA", "SECTIONS", "UNIT", "CouncilInputOverflow", "admit", "admit_delivery", "admit_prefix",
           "admit_required", "allowance", "canonical_bytes", "council_budget", "output_limit", "policy_manifest",
           "preceding"]
