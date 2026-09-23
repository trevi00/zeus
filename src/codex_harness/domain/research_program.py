"""Finite research program: strict config, deterministic relevance, selection, cycle receipts and
the read-only projections (INV-RESEARCH-PROGRAM-001).

A program (`urn:zeus:research-program:1`) is one operator authorization: a pinned base, an absolute
deadline, a bounded number of collection cycles, a smaller adoption cap, the machine call ceilings,
the topics whose keywords define relevance, the owner-authorized local candidates and one complete
`urn:zeus:autonomous:2` template the council manifests are derived from. Everything here is policy
over dictionaries: no store, network, Git, clock or provider access. Keyword relevance is a
deterministic lexical rule, never a semantic quality judgement, and a discovered candidate is an
untrusted lead, never approved knowledge. Values never enter error messages; field names do.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from codex_harness.domain.audit_progress import KIND as AUDIT_PROGRESS
from codex_harness.domain.audit_progress import ProgressRefused
from codex_harness.domain.audit_progress import validate_source as validate_progress_source
from codex_harness.domain.council import SCHEMA_AUTONOMOUS_V2, validate_council_manifest
from codex_harness.domain.dge import parse_deadline
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import ID, REVISION, SHA256, safe_relative_path
from codex_harness.domain.research_investigations import KIND as FAMILY
from codex_harness.domain.research_investigations import SOURCE as INVESTIGATION
from codex_harness.domain.research_investigations import (
    InvestigationRefused,
    dispatch_counts,
    recovery_view,
    validate_source,
)
from codex_harness.domain.usage_policy import NUMERIC_FIELDS, UsagePolicyError, accounting_mode
from codex_harness.domain.usage_policy import headroom as policy_headroom
from codex_harness.domain.usage_policy import validate_budget as policy_budget

CONFIG_SCHEMA = "urn:zeus:research-program:1"
STATUS_SCHEMA = "urn:zeus:research-program-status:1"
CAPTURE_SCHEMA = "urn:zeus:research-capture:1"
MONITOR_SCHEMA = "urn:zeus:research-program-monitor:1"
CONFIG_FIELDS = {"schema", "id", "base_revision", "deadline", "interval_seconds", "max_cycles", "max_adoptions",
                 "budget", "topics", "local_candidates", "template"}
# Opt-in only: an absent `investigation_source` or `audit_progress_source` keeps the legacy
# canonical config and digest exactly. Each authorizes ONE scoped source for this program's
# unchanged template plan; neither widens permissions, thresholds or the template.
OPTIONAL_CONFIG_FIELDS = {"investigation_source", "audit_progress_source"}
BUDGET_FIELDS = set(NUMERIC_FIELDS)  # the legacy finite shape; `mode` is optional (usage_policy)
TOPIC_FIELDS = {"id", "keywords"}
LOCAL_FIELDS = {"id", "topic", "path", "sha256", "rationale"}
MAX_CYCLES, MAX_LOCAL, MAX_TOPICS, MAX_KEYWORDS = 100, 100, 20, 50
TITLE_LIMIT, SUMMARY_LIMIT = 400, 1500
HEADROOM = 7             # one autonomous:2 council cycle: research, DBA, two leads, conductor, implement, review
MONITOR_SAMPLE = 20
CAPTURE_ROOT = "docs/zeus/research-captures"
PROGRAM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$")
KEYWORD = re.compile(r"^[a-z0-9][a-z0-9 ._+#/-]{0,63}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
EXTERNAL_SOURCES = ("github", "geeknews")
SOURCES = ("local", *EXTERNAL_SOURCES)   # the discovery feeds; investigations are not a fetched feed

PAUSED, ACTIVE, COMPLETED, BLOCKED = "paused", "active", "completed", "blocked"
STATES = frozenset({PAUSED, ACTIVE, COMPLETED, BLOCKED})
# Cycle stages: reserved before any I/O, then the observed facts, then one terminal state.
COLLECTING, SELECTED, NO_SELECTION, CAPTURED, COUNCIL, CYCLE_DONE, CYCLE_FAILED = (
    "collecting", "selected", "no_selection", "captured", "council", "completed", "failed")
RESULTS = ("accepted", "rejected", "failed", "unknown")
IGNORED, ELIGIBLE, CLAIMED = "ignored", "eligible", "claimed"
# Terminal autonomous_runs statuses (domain.autonomous.TERMINAL) folded to the four program results.
RUN_RESULT = {"accepted": "accepted", "rejected": "rejected", "failed": "failed", "exhausted": "failed",
              "needs_user": "failed", "needs_research": "failed", "expired": "failed", "unknown": "unknown"}


class ProgramRefused(ContractError):
    """Refused with a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("research program refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _integer(value) -> bool:
    return type(value) is int


def _text(value, limit=4000) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def _fields(document, expected, name):
    if not isinstance(document, dict):
        raise ProgramRefused("config_invalid", name)
    if set(document) != expected:
        raise ProgramRefused("config_fields", name)


# ----- configuration --------------------------------------------------------------------------------
def validate_budget(budget, name="budget") -> dict:
    """The shared usage policy decides the shape (finite legacy form or explicit subscription mode)."""
    try:
        return policy_budget(budget)
    except UsagePolicyError as exc:
        raise ProgramRefused("config_" + exc.reason_code, name) from exc


def _topic(topic, index: int) -> dict:
    name = "topics[" + str(index) + "]"
    _fields(topic, TOPIC_FIELDS, name)
    keywords = topic["keywords"]
    if not (type(topic["id"]) is str and TOKEN.fullmatch(topic["id"])):
        raise ProgramRefused("config_invalid", name + ".id")
    if not (isinstance(keywords, list) and 1 <= len(keywords) <= MAX_KEYWORDS
            and all(type(k) is str and KEYWORD.fullmatch(k) and k == k.strip() for k in keywords)
            and len(set(keywords)) == len(keywords)):
        raise ProgramRefused("config_invalid", name + ".keywords")
    return {"id": topic["id"], "keywords": list(keywords)}


def _local(candidate, index: int, topics: set) -> dict:
    name = "local_candidates[" + str(index) + "]"
    _fields(candidate, LOCAL_FIELDS, name)
    if not (type(candidate["id"]) is str and TOKEN.fullmatch(candidate["id"])):
        raise ProgramRefused("config_invalid", name + ".id")
    if candidate["topic"] not in topics:
        raise ProgramRefused("config_invalid", name + ".topic")
    if not safe_relative_path(candidate["path"]):
        raise ProgramRefused("config_invalid", name + ".path")
    if type(candidate["sha256"]) is not str or SHA256.fullmatch(candidate["sha256"]) is None:
        raise ProgramRefused("config_invalid", name + ".sha256")
    if not _text(candidate["rationale"], 2000):
        raise ProgramRefused("config_invalid", name + ".rationale")
    return {k: candidate[k] for k in sorted(LOCAL_FIELDS)}


def validate_config(document, policy) -> dict:
    """Strict validation; returns the canonical copy. The template is validated by the existing
    council validator (one copy of those rules) and must carry the SAME base and budget."""
    if not isinstance(document, dict) or document.get("schema") != CONFIG_SCHEMA:
        raise ProgramRefused("config_schema")
    if not CONFIG_FIELDS <= set(document) or set(document) - CONFIG_FIELDS - OPTIONAL_CONFIG_FIELDS:
        raise ProgramRefused("config_fields", "root")
    if type(document["id"]) is not str or PROGRAM_ID.fullmatch(document["id"]) is None:
        raise ProgramRefused("config_invalid", "id")
    if type(document["base_revision"]) is not str or REVISION.fullmatch(document["base_revision"]) is None:
        raise ProgramRefused("config_invalid", "base_revision")
    try:
        deadline = parse_deadline(document["deadline"], ProgramRefused)
    except ContractError as exc:
        raise ProgramRefused("config_invalid", "deadline") from exc
    interval, cycles, adoptions = document["interval_seconds"], document["max_cycles"], document["max_adoptions"]
    if not (_integer(interval) and interval > 0):
        raise ProgramRefused("config_invalid", "interval_seconds")
    if not (_integer(cycles) and 1 <= cycles <= MAX_CYCLES):
        raise ProgramRefused("config_invalid", "max_cycles")
    if not (_integer(adoptions) and 0 <= adoptions <= cycles):
        raise ProgramRefused("config_invalid", "max_adoptions")
    budget = validate_budget(document["budget"])
    topics = document["topics"]
    if not (isinstance(topics, list) and 1 <= len(topics) <= MAX_TOPICS):
        raise ProgramRefused("config_invalid", "topics")
    topics = [_topic(t, i) for i, t in enumerate(topics)]
    if len({t["id"] for t in topics}) != len(topics):
        raise ProgramRefused("config_duplicate", "topics[].id")
    locals_ = document["local_candidates"]
    if not (isinstance(locals_, list) and len(locals_) <= MAX_LOCAL):
        raise ProgramRefused("config_invalid", "local_candidates")
    locals_ = [_local(c, i, {t["id"] for t in topics}) for i, c in enumerate(locals_)]
    # One local candidate per source identity: distinct ids and distinct paths.
    if len({c["id"] for c in locals_}) != len(locals_) or len({c["path"] for c in locals_}) != len(locals_):
        raise ProgramRefused("config_duplicate", "local_candidates[].id/path")
    template = document["template"]
    if not isinstance(template, dict) or template.get("schema") != SCHEMA_AUTONOMOUS_V2:
        raise ProgramRefused("template_schema", "template")
    try:
        template = validate_council_manifest(template, policy)
    except ContractError as exc:
        raise ProgramRefused("template_invalid", "template") from exc
    if template["base_revision"] != document["base_revision"]:
        raise ProgramRefused("template_base_mismatch", "template.base_revision")
    if template["budget"] != budget:
        raise ProgramRefused("template_budget_mismatch", "template.budget")
    canonical = {"schema": CONFIG_SCHEMA, "id": document["id"], "base_revision": document["base_revision"],
                 "deadline": deadline, "interval_seconds": interval, "max_cycles": cycles, "max_adoptions": adoptions,
                 "budget": budget, "topics": topics, "local_candidates": locals_, "template": template}
    if "investigation_source" in document:
        # Opt-in portfolio consumption: it authorizes ONLY this program's unchanged template plan for
        # the named projects and fixed reason codes, never arbitrary repairs or a wider scope.
        try:
            canonical["investigation_source"] = validate_source(document["investigation_source"], {t["id"] for t in topics})
        except InvestigationRefused as exc:
            raise ProgramRefused(exc.reason_code, exc.field) from exc
    if "audit_progress_source" in document:
        # Opt-in audit-progress consumption: it authorizes ONLY this program's unchanged template
        # plan for the named audits. It grants no threshold, no audit action and no wider scope.
        try:
            canonical["audit_progress_source"] = validate_progress_source(
                document["audit_progress_source"], {t["id"] for t in topics})
        except ProgressRefused as exc:
            raise ProgramRefused(exc.reason_code, exc.field) from exc
    return canonical


def config_digest(config: dict, repository: str) -> str:
    """The immutable registration identity: canonical config plus the resolved repository identity."""
    return digest({"config": config, "repository": repository})


# A replacement program (research-dispatch-recovery-001) is a NEW authorization, so its identity, base
# and deadline are its own; every other field - topics, investigation source, caps, budget, template
# goal/plan/research/claude - must equal the failed program's, so a recovery never widens authority.
REPLACEMENT_OWN, REPLACEMENT_TEMPLATE_OWN = frozenset({"id", "base_revision", "deadline"}), frozenset({"base_revision", "deadline"})


def same_authority(failed: dict, replacement: dict) -> bool:
    def fixed(config):
        return {**{k: v for k, v in config.items() if k not in REPLACEMENT_OWN},
                "template": {k: v for k, v in config["template"].items() if k not in REPLACEMENT_TEMPLATE_OWN}}
    return ("investigation_source" in failed and isinstance(replacement, dict) and "template" in replacement
            and fixed(failed) == fixed(replacement))


# ----- identity and relevance -----------------------------------------------------------------------
def normalize_url(url) -> str | None:
    """https only, lowercase scheme and host, no fragment, no trailing slash; None when unusable."""
    if type(url) is not str or len(url) > 2048:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or not parts.hostname:
        return None
    netloc = parts.hostname.lower() + (":" + str(parts.port) if parts.port else "")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, parts.query, ""))


def candidate_key(source: str, identity: str) -> str:
    if source == "local":
        return "local:" + identity
    if source == INVESTIGATION:   # synthesized in the store transaction only, never from a feed item
        return INVESTIGATION + ":" + identity
    return "url:" + identity


def candidate_id(key: str) -> str:
    return "c-" + digest(key)[:24]


def bounded_text(value, limit: int) -> str:
    return (value if type(value) is str else "")[:limit]


def match_topics(topics: list, title, summary) -> dict:
    """Deterministic lexical relevance: the first topic (config order) with a keyword contained in
    the bounded lowercased title or summary. The reason names the field and keyword, nothing more.
    This is authorization-scoped relevance, not a quality or semantic evaluation."""
    fields = {"title": bounded_text(title, TITLE_LIMIT).lower(), "summary": bounded_text(summary, SUMMARY_LIMIT).lower()}
    for topic in topics:
        for keyword in topic["keywords"]:
            for name, text in fields.items():
                if keyword in text:
                    return {"topic": topic["id"], "eligible": True, "reason": "keyword:" + keyword + " in " + name}
    return {"topic": None, "eligible": False, "reason": "no_keyword_match"}


def order_key(entry: dict) -> tuple:
    """Stable order: authorized investigations first (repeated observed failures outrank new leads),
    then owner-authorized local, then external; inside a rank topic, id and url decide."""
    rank = {INVESTIGATION: 0, "local": 1}.get(entry["source"], 2)
    return (rank, entry.get("topic") or "", entry["id"], entry.get("url") or "")


def headroom(budget: dict, counts: dict) -> dict:
    """Machine ledger headroom for ONE council (HEADROOM starts) under the shared usage policy:
    finite, the smaller of the per-host and total remainders; subscription, `remaining` None and
    `ok` only for a readable ledger. Unreadable or missing counts are never free space, and
    `required` is the council's shape, not provider quota."""
    return policy_headroom(budget, counts, HEADROOM)


def select_candidate(eligible: list, adoptions: int, max_adoptions: int, room: dict) -> dict:
    """At most one eligible unclaimed candidate, in stable order, when the adoption cap and the
    machine headroom both allow a council; otherwise the deterministic no-selection reason."""
    ordered = sorted((c for c in eligible if c["status"] == ELIGIBLE), key=order_key)
    if not ordered:
        return {"candidate": None, "reason": "no_eligible_candidate"}
    if adoptions >= max_adoptions:
        return {"candidate": None, "reason": "adoption_cap_reached"}
    if not room["ok"]:
        return {"candidate": None, "reason": "machine_headroom_insufficient"}
    return {"candidate": ordered[0], "reason": "first_eligible_in_stable_order"}


def safe_code(reason) -> str:
    if not isinstance(reason, str):
        return "unknown"
    head = reason.partition(":")[0]
    return head if SAFE_CODE.fullmatch(head) else "unknown"


# ----- capture and derived manifest -------------------------------------------------------------------
def capture_path(program_id: str, number: int) -> str:
    return CAPTURE_ROOT + "/" + program_id + "/" + cycle_label(number) + ".json"


def capture_ref(program_id: str, number: int) -> str:
    return "refs/zeus/research/" + program_id + "/" + cycle_label(number)


def cycle_label(number: int) -> str:
    return "%03d" % number


def cycle_id(program_id: str, number: int) -> str:
    return program_id + ":" + cycle_label(number)


def run_id(program_id: str, number: int) -> str:
    """Deterministic council run id per cycle: a replay names the same `autonomous_runs` row."""
    value = program_id + ".c" + cycle_label(number)
    if ID.fullmatch(value) is None:
        raise ProgramRefused("run_id_invalid")
    return value


def snapshot_document(*, program_id: str, number: int, base_revision: str, fetched_at: str, candidate: dict,
                      sources: dict, local_bytes_sha256: str | None, github_detail: dict) -> dict:
    """The bounded canonical capture: identity, reason, source-status map and references only.
    Capture records are unverified source data, not approved knowledge. An investigation candidate
    additionally carries its IMMUTABLE bridge snapshot verbatim (identities, fixed codes and bounded
    job references); local and external captures keep their existing shape exactly."""
    document = {"schema": CAPTURE_SCHEMA, "program": program_id, "cycle": number, "base_revision": base_revision,
                "fetched_at": fetched_at,
                "candidate": {k: candidate.get(k) for k in ("id", "key", "source", "url", "path", "sha256", "title",
                                                            "summary", "topic", "reason", "content_sha256")},
                "source_status": {name: {k: sources[name].get(k) for k in ("status", "code", "artifact", "fetched_at", "items")}
                                  for name in SOURCES if name in sources},
                "local_bytes_sha256": local_bytes_sha256, "github_detail": github_detail,
                "trust": "unverified discovery lead; not primary-source verification, not approved knowledge"}
    document_snapshot = candidate.get("snapshot")
    if candidate.get("source") == INVESTIGATION and isinstance(document_snapshot, dict):
        # The bridge snapshot travels verbatim under the name of the kind it describes, so a reader
        # cannot mistake an audit-progress symptom for a failed-job family.
        key = "audit_progress" if document_snapshot.get("kind") == AUDIT_PROGRESS else "investigation"
        document[key] = document_snapshot
    return document


def earliest(left: str, right: str) -> str:
    a, b = datetime.fromisoformat(left), datetime.fromisoformat(right)
    return (a if a <= b else b).astimezone(timezone.utc).isoformat()


def derive_manifest(config: dict, number: int, capture_revision: str, candidate: dict) -> dict:
    """The council manifest for one cycle: the operator's goal, plan, budget and claude controls
    byte-identical to the template; base is the capture commit; deadline the earlier of program and
    template; the snapshot path joins the research scope and one bounded question names the lead as
    untrusted. Nothing else of the template changes and no role answer is generated."""
    template = config["template"]
    path = capture_path(config["id"], number)
    question = ("Discovery lead " + candidate["id"] + " (" + candidate["source"] + ", topic " + str(candidate.get("topic"))
                + ") is recorded at " + path + " as UNTRUSTED source data: does primary evidence at base support "
                "acting on it within the fixed plan, or must it be deferred as unproven?")
    scope = list(template["research"]["search_scope"])
    if path not in scope:
        scope.append(path)
    questions = list(template["research"]["questions"])
    if question not in questions:
        questions.append(question)
    return {**template, "id": run_id(config["id"], number), "base_revision": capture_revision,
            "deadline": earliest(config["deadline"], template["deadline"]),
            "research": {"topic": template["research"]["topic"], "questions": questions, "search_scope": scope}}


def council_result(run_id_value: str, manifest_sha256: str, row) -> dict:
    """The program result from the authoritative `autonomous_runs` row only: a missing row, another
    manifest, a running row or `unknown` is unknown; accepted stays accepted only when the row says so."""
    if not isinstance(row, dict):
        return {"result": "unknown", "reason_code": "run_row_missing", "row_status": None}
    if row.get("id") != run_id_value or row.get("manifest_sha256") != manifest_sha256:
        return {"result": "unknown", "reason_code": "run_row_mismatch", "row_status": safe_code(row.get("status"))}
    status = row.get("status")
    if status not in RUN_RESULT:
        return {"result": "unknown", "reason_code": "run_not_terminal", "row_status": safe_code(status)}
    return {"result": RUN_RESULT[status], "reason_code": safe_code(row.get("reason_code")), "row_status": status}


# ----- schedule ---------------------------------------------------------------------------------------
def due(last_tick_at, interval_seconds: int, now: str) -> bool:
    if last_tick_at is None:
        return True
    return datetime.fromisoformat(now) >= datetime.fromisoformat(last_tick_at) + timedelta(seconds=interval_seconds)


def expired(deadline: str, now: str) -> bool:
    return datetime.fromisoformat(now) >= datetime.fromisoformat(deadline)


# ----- projections ------------------------------------------------------------------------------------
def cycle_view(cycle: dict) -> dict:
    """Legacy entries keep their keys; `investigations` and `audit_progress` are the additive bridge
    receipts (bounded counts, the claimed candidate id and its dispatch result), each None when that
    source is not configured. They are separate rows of evidence and are never merged."""
    keys = ("id", "number", "status", "counts", "sources", "selection", "budget", "capture", "council", "result",
            "failure", "stop_reason", "remaining", "started_at", "updated_at", "finished_at", "investigations",
            "audit_progress")
    return {k: cycle.get(k) for k in keys}


def candidate_view(candidate: dict) -> dict:
    keys = ("id", "source", "topic", "status", "reason", "url", "path", "first_cycle", "last_cycle", "seen",
            "claimed_cycle", "result", "investigation")
    return {k: candidate.get(k) for k in keys}


def program_view(row: dict, cycles: list, candidates: list, dispatches: list | None = None,
                 recoveries: list | None = None) -> dict:
    """`urn:zeus:research-program-status:1`: identities, state, counts, codes and per-cycle facts;
    never the template text, config bodies, exception text, DSNs or feed bodies."""
    config = row["config"]
    ordered = sorted(cycles, key=lambda c: c["number"])
    return {"schema": STATUS_SCHEMA, "id": row["id"], "state": row["state"], "config_sha256": row["config_sha256"],
            "base_revision": config["base_revision"], "deadline": config["deadline"],
            "interval_seconds": config["interval_seconds"],
            "cycles": {"completed": row["cycles"], "max": config["max_cycles"], "remaining": config["max_cycles"] - row["cycles"],
                       "active": row.get("active_cycle")},
            "adoptions": {"dispatched": row["adoptions"], "max": config["max_adoptions"],
                          "remaining": config["max_adoptions"] - row["adoptions"]},
            "budget": dict(config["budget"]), "accounting_mode": accounting_mode(config["budget"]),
            "stop_reason": row.get("stop_reason"), "blocked_reason": row.get("blocked_reason"),
            "last_tick_at": row.get("last_tick_at"), "registered_at": row["registered_at"], "updated_at": row["updated_at"],
            "candidates": {"total": len(candidates), "eligible": sum(c["status"] == ELIGIBLE for c in candidates),
                           "claimed": sum(c["status"] == CLAIMED for c in candidates),
                           "ignored": sum(c["status"] == IGNORED for c in candidates)},
            "cycle_receipts": [cycle_view(c) for c in ordered],
            # Dispatch is counted separately from acceptance: a claimed or dispatched candidate is
            # work in flight, and an accepted council is still not an owner disposition or a fix.
            # The two kinds are counted apart: an audit-progress claim is not a failure family.
            "investigations": dispatch_counts([d for d in (dispatches or [])
                                               if d.get("kind", FAMILY) == FAMILY]),
            "audit_progress": dispatch_counts([d for d in (dispatches or [])
                                               if d.get("kind") == AUDIT_PROGRESS]),
            # Additive lineage: a failed original and its owner-authorized replacement, read-only.
            "recoveries": [recovery_view(r) for r in sorted(recoveries or [], key=lambda r: r["investigation"])],
            "authority": "research program status; counts from the store, not model claims; no merge, deploy or truth"}


def monitor_projection(programs: list, cycles: list) -> dict:
    """Additive bounded monitor source: the last MONITOR_SAMPLE programs by update with their counts,
    outcomes and stop reasons; `truncated` is explicit."""
    by_program: dict = {}
    for cycle in cycles:
        by_program.setdefault(cycle["program"], []).append(cycle)
    ordered = sorted(programs, key=lambda p: (p["updated_at"], p["id"]), reverse=True)
    out = []
    for row in ordered[:MONITOR_SAMPLE]:
        mine = sorted(by_program.get(row["id"], []), key=lambda c: c["number"])
        last = mine[-1] if mine else None
        out.append({"id": row["id"], "state": row["state"], "cycles": row["cycles"], "max_cycles": row["config"]["max_cycles"],
                    "accounting_mode": accounting_mode(row["config"]["budget"]),
                    "adoptions": row["adoptions"], "max_adoptions": row["config"]["max_adoptions"],
                    "stop_reason": row.get("stop_reason"), "blocked_reason": row.get("blocked_reason"),
                    "outcomes": {r: sum(1 for c in mine if c.get("result") == r) for r in RESULTS},
                    "last_cycle": None if last is None else {
                        "number": last["number"], "status": last["status"], "result": last.get("result"),
                        "selection_reason": (last.get("selection") or {}).get("reason"),
                        "sources": {name: (last.get("sources") or {}).get(name, {}).get("status") for name in SOURCES}}})
    return {"schema": MONITOR_SCHEMA, "programs": out, "truncated": len(ordered) > MONITOR_SAMPLE}


__all__ = ["ACTIVE", "AUDIT_PROGRESS", "BLOCKED", "CAPTURE_SCHEMA", "CLAIMED", "COMPLETED", "CONFIG_SCHEMA",
           "ELIGIBLE", "FAMILY", "HEADROOM",
           "IGNORED", "INVESTIGATION", "MONITOR_SCHEMA", "PAUSED", "STATUS_SCHEMA", "ProgramRefused", "candidate_id",
           "candidate_key", "capture_path", "capture_ref", "config_digest", "council_result", "derive_manifest",
           "headroom", "match_topics", "monitor_projection", "normalize_url", "program_view", "same_authority",
           "select_candidate", "snapshot_document", "validate_config"]
