"""Decision feedback and recurring-work candidates: pure contracts, joins and grouping
(INV-DECISION-FEEDBACK-001).

A conductor decision and the actual outcome of the run that carried it are two facts other owners
already recorded: `dge_sessions`/`dge_events` hold the executor-bound decision event, `autonomous_runs`
holds the run's final status. Nothing here creates a decision, a task, an incident or a quality label;
it reads those facts, compares one run's work contract against an owner-authored procedure registry
and groups exact contract equality. Evidence credit needs the content-addressed execution artifact
those rows reference, not a matching reference string: the application reads it through the existing
execution-evidence port and checks it with the existing `execution_evidence` rule before any
observation exists here. Matching is exact: repository identity, the complete allowed-path
set and the acceptance-criteria digest, never a title, a family or a model-selected cause. An empty,
malformed or ambiguous match is unknown and never reaches a candidate threshold.

Successful repetition is not an incident: `INV-RECURRENCE-001` counting stays with `record_incident`
and is neither read nor written here.
"""
from __future__ import annotations

from codex_harness.domain.autonomous import ARBITER, ORIGIN_EXECUTOR, TERMINAL
from codex_harness.domain.council import CONDUCTOR_ROLE, COUNCIL_AGENTS
from codex_harness.domain.dge import VERDICTS
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import ID, REVISION, SHA256, safe_relative_path

REGISTRY_SCHEMA = "urn:zeus:procedure-registry:1"
OBSERVATION_SCHEMA = "urn:zeus:decision-observation:1"
CANDIDATE_SCHEMA = "urn:zeus:recurring-work-candidate:1"
COLLECTION_SCHEMA = "urn:zeus:decision-feedback-collection:1"
CONFLICT_SCHEMA = "urn:zeus:decision-feedback-conflict:1"
REPORT_SCHEMA = "urn:zeus:decision-feedback-report:1"
REGISTRY_VERSION = 1
REGISTRY_FIELDS = {"schema", "version", "entries"}
ENTRY_FIELDS = {"id", "source_kind", "repository", "allowed_paths", "acceptance_criteria_sha256", "remediation"}
# Version 1 reads council (autonomous v2) runs only; the conductor is the deciding role there.
SOURCE_KINDS = ("council",)
REMEDIATIONS = ("existing_owner_review", "script", "skill")
DECIDING_ROLE = CONDUCTOR_ROLE
DECIDING_AGENT = COUNCIL_AGENTS[CONDUCTOR_ROLE]
DECISION_SLOT = ARBITER          # the internal DGE slot the conductor's arbitration is recorded on
DEFAULT_SCAN, MAX_SCAN = 100, 500
MAX_OCCURRENCES = 50             # bounded immutable evidence references reported per contract group
MAX_MEMBERS = 1000               # durable exact distinct-run membership kept per contract group
OCCURRENCE_THRESHOLD = 2         # two distinct executed run identities, successes included
MAX_OUTCOME_HISTORY = 10
CANDIDATE_STATUS = "needs_analysis"
OUTCOME_STATES = ("pending", "accepted", "rejected", "failed", "cancelled", "unknown")
# Exact source status -> outcome state. Anything else (expired, exhausted, needs_user, needs_research,
# the run's own `unknown`, a missing status) stays `unknown`; the source status is preserved beside it.
OUTCOME_BY_STATUS = {"running": "pending", "accepted": "accepted", "rejected": "rejected",
                     "failed": "failed", "cancelled": "cancelled"}
TERMINAL_AUTHORITY = ("terminal accepted is operation acceptance only: not proof that the decision was "
                      "correct, that the change was deployed or that product acceptance passed")
QUALITY_BASIS = ("no independently reviewed diagnosis is linked to this decision; downstream success or "
                 "failure alone never establishes conductor decision quality")
CANDIDATE_AUTHORITY = ("advisory unverified candidate: it says needs_analysis, it is not a created skill, "
                       "verified knowledge, an incident occurrence or an activation")
COLLECTION_AUTHORITY = ("read-only join of existing executor-owned records; no model, no dispatch, no "
                        "source row is written and no promotion authority is granted")
LIMITS = (
    "replay, held-out evaluation and policy activation are not implemented in this delivery",
    "decision quality stays unknown until an independently reviewed diagnosis is linked",
    "execution identity is verified against the stored run, session, event and task rows and against the "
    "content-addressed execution artifact those rows reference; a matching reference string alone is not credit",
    "one collect scans a bounded page of run ids and reports a continuation cursor; counts describe that page",
    "candidate evidence reports at most " + str(MAX_OCCURRENCES) + " occurrence references per contract group; "
    "the distinct-run count stays exact and names the unreferenced remainder",
    "distinct-run membership is exact up to " + str(MAX_MEMBERS) + " runs per contract group; beyond that the "
    "group reports membership_capped and counts no further run",
    "successful repetition is grouped here and never added to incident recurrence counts (INV-RECURRENCE-001)",
    "skill or script extraction, promotion and knowledge verification stay with their existing owners",
)
# Fixed reason codes; a refusal names the missing binding, never a row body, packet, payload or path.
EVIDENCE_VERIFIED = "verified"
EVIDENCE_REASONS = ("verified", "run_identity_unknown", "foreign_repository", "source_kind_unknown",
                    "decision_session_unproven", "work_contract_unknown", "decision_event_unproven",
                    "decision_execution_unproven", "decision_artifact_missing", "decision_artifact_corrupt",
                    "decision_artifact_invalid", "decision_artifact_unproven")
# What the injected execution-evidence port reports -> this collector's own fixed code.
ARTIFACT_REASONS = {"evidence_missing": "decision_artifact_missing", "evidence_corrupt": "decision_artifact_corrupt",
                    "evidence_invalid": "decision_artifact_invalid"}
MATCH_REASONS = ("matched", "no_registry_match", "ambiguous_registry_match")
# Recording outcomes of one already proven observation against the authoritative source row.
RECORD_REASONS = ("source_history_conflict", "source_page_stale", "source_row_unavailable")


class RegistryError(ContractError):
    """The procedure registry is refused before any store read; the message names a field, never a value."""


class DecisionFeedbackError(ContractError):
    """A fixed reason code; the message never carries a row body, a payload or a path."""

    def __init__(self, reason_code: str):
        super().__init__("decision feedback refused: " + reason_code)
        self.reason_code = reason_code


def _token(value) -> bool:
    return type(value) is str and ID.fullmatch(value) is not None


def _text(value, limit) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def _sha256(value) -> bool:
    return type(value) is str and SHA256.fullmatch(value) is not None


def _fields(document, expected, name) -> None:
    if not isinstance(document, dict):
        raise RegistryError(name + " must be an object")
    unknown, missing = sorted(set(document) - expected), sorted(expected - set(document))
    if unknown or missing:
        raise RegistryError(name + " has unknown or missing fields: "
                            + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))


# ----- trusted registry ---------------------------------------------------------------------------
def validate_registry(document) -> dict:
    """Strict owner-authored registry (version 1). Every entry pins one exact contract; there is no
    fuzzy title, substring family, regular expression or executable rule anywhere in this format."""
    _fields(document, REGISTRY_FIELDS, "Procedure registry")
    if document["schema"] != REGISTRY_SCHEMA:
        raise RegistryError("Procedure registry schema is not " + REGISTRY_SCHEMA)
    if type(document["version"]) is not int or document["version"] != REGISTRY_VERSION:
        raise RegistryError("Procedure registry version must be " + str(REGISTRY_VERSION))
    entries = document["entries"]
    if not (isinstance(entries, list) and entries):
        raise RegistryError("Procedure registry entries must be a non-empty list")
    out, ids = [], set()
    for entry in entries:
        _fields(entry, ENTRY_FIELDS, "Procedure registry entry")
        if not _token(entry["id"]) or entry["id"] in ids:
            raise RegistryError("Procedure registry entry ids must be distinct safe tokens")
        if entry["source_kind"] not in SOURCE_KINDS:
            raise RegistryError("Procedure registry entry source_kind must be one of " + ", ".join(SOURCE_KINDS))
        if not _text(entry["repository"], 1024):
            raise RegistryError("Procedure registry entry repository must be an exact repository identity")
        paths = entry["allowed_paths"]
        if not (isinstance(paths, list) and paths and len(set(paths)) == len(paths)
                and all(safe_relative_path(p) for p in paths)):
            raise RegistryError("Procedure registry entry allowed_paths must be a non-empty set of safe relative paths")
        if not _sha256(entry["acceptance_criteria_sha256"]):
            raise RegistryError("Procedure registry entry acceptance_criteria_sha256 must be 64 lowercase hex")
        if entry["remediation"] not in REMEDIATIONS:
            raise RegistryError("Procedure registry entry remediation must be one of " + ", ".join(REMEDIATIONS))
        ids.add(entry["id"])
        out.append({"id": entry["id"], "source_kind": entry["source_kind"], "repository": entry["repository"],
                    "allowed_paths": sorted(paths), "acceptance_criteria_sha256": entry["acceptance_criteria_sha256"],
                    "remediation": entry["remediation"]})
    return {"schema": REGISTRY_SCHEMA, "version": REGISTRY_VERSION, "entries": sorted(out, key=lambda e: e["id"])}


def criteria_digest(criteria) -> str:
    """The digest an owner writes into a registry entry: sha256 of the canonical JSON of the exact
    acceptance-criteria list, in the plan's own order. A reordered or edited list is another contract."""
    if not (isinstance(criteria, list) and criteria and all(_text(c, 12000) for c in criteria)):
        raise DecisionFeedbackError("work_contract_unknown")
    return digest(list(criteria))


def work_contract(repository: str, source_kind: str, plan) -> dict:
    """The comparable contract of one run, taken from the executor-owned plan the design approved."""
    if not isinstance(plan, dict):
        raise DecisionFeedbackError("work_contract_unknown")
    paths = plan.get("allowed_paths")
    if not (isinstance(paths, list) and paths and len(set(paths)) == len(paths) and all(safe_relative_path(p) for p in paths)):
        raise DecisionFeedbackError("work_contract_unknown")
    return {"repository": repository, "source_kind": source_kind, "allowed_paths": sorted(paths),
            "acceptance_criteria_sha256": criteria_digest(plan.get("acceptance_criteria"))}


def group_id(contract: dict) -> str:
    """One deterministic group per exact contract; different repositories, scopes or criteria never merge."""
    return "group:" + digest(contract)


def match_registry(contract: dict, registry: dict) -> dict:
    """Exact equality on the four contract fields. No match and more than one match are both unknown."""
    matches = [e for e in registry["entries"]
               if e["source_kind"] == contract["source_kind"] and e["repository"] == contract["repository"]
               and e["allowed_paths"] == contract["allowed_paths"]
               and e["acceptance_criteria_sha256"] == contract["acceptance_criteria_sha256"]]
    if len(matches) == 1:
        return {"matched": True, "reason": "matched", "procedure_id": matches[0]["id"],
                "remediation": matches[0]["remediation"]}
    return {"matched": False, "reason": "ambiguous_registry_match" if matches else "no_registry_match",
            "procedure_id": None, "remediation": None}


def add_member(run_ids, run_id: str) -> dict:
    """Durable exact membership of distinct run identities, kept apart from the bounded evidence the
    candidate reports. A run identity already recorded adds nothing, so a re-collection of a group
    that is larger than the reported cap changes no count. Past `MAX_MEMBERS` the group stops
    counting and says so once; it never counts the same run twice to stay inside the bound."""
    members = list(run_ids)
    if run_id in members:
        return {"run_ids": members, "capped": False}
    if len(members) >= MAX_MEMBERS:
        return {"run_ids": members, "capped": True}
    return {"run_ids": sorted(members + [run_id]), "capped": False}


def occurrence_window(run_ids) -> dict:
    """The bounded presentation: the referenced run identities and the exact unreferenced remainder."""
    members = list(run_ids)
    return {"referenced": members[:MAX_OCCURRENCES], "unreferenced": max(0, len(members) - MAX_OCCURRENCES)}


def candidate_id(repository: str, procedure_id: str, registry_revision: str) -> str:
    """One advisory candidate per repository + procedure + registry revision."""
    return "candidate:" + digest({"repository": repository, "procedure_id": procedure_id,
                                  "registry_revision": registry_revision})


# ----- decision and outcome -----------------------------------------------------------------------
def decision_facts(session: dict, event: dict, binding: dict) -> dict:
    """Identities and a closed verdict vocabulary only: no rationale, scenario, packet or payload text."""
    payload = (event.get("event") or {}).get("payload")
    verdict = payload.get("verdict") if isinstance(payload, dict) else None
    dispositions = payload.get("dispositions") if isinstance(payload, dict) else None
    return {"role": DECIDING_ROLE, "slot": event.get("role"), "agent": binding.get("agent"),
            "session_id": session["id"], "event_id": event.get("event_id"), "event_digest": event.get("digest"),
            "round": event.get("round"), "origin": event.get("origin"), "recorded_at": event.get("recorded_at"),
            "packet_digest": session.get("packet_digest"), "design_state": session.get("state"),
            "decision_event_id": session.get("decision_event_id"),
            "verdict": verdict if verdict in VERDICTS else None,
            "dispositions": len(dispositions) if isinstance(dispositions, list) else None,
            "task_id": binding.get("task_id"), "execution_ref": binding.get("execution_ref"),
            "output_sha256": binding.get("output_sha256"), "stage": binding.get("stage"),
            "generation": binding.get("generation"), "attempt": binding.get("attempt")}


def outcome_facts(run: dict) -> dict:
    """The run's own final state, preserved exactly, with its provenance. Never inferred, never scored."""
    status = run.get("status") if isinstance(run.get("status"), str) else None
    operation = run.get("operation") if isinstance(run.get("operation"), dict) else {}
    promotion = run.get("promotion") if isinstance(run.get("promotion"), dict) else {}
    return {"state": OUTCOME_BY_STATUS.get(status, "unknown"), "source_status": status,
            "reason_code": run.get("reason_code") if isinstance(run.get("reason_code"), str) else None,
            "terminal": status in TERMINAL if status is not None else False,
            "stage": run.get("stage") if isinstance(run.get("stage"), str) else None,
            "operation": {"id": operation.get("id"), "status": operation.get("status"),
                          "reason_code": operation.get("reason_code")},
            "promoted": bool(promotion.get("id")),
            "provenance": {"bucket": "autonomous_runs", "id": run.get("id"),
                           "finished_at": run.get("finished_at"), "updated_at": run.get("updated_at")},
            "authority": TERMINAL_AUTHORITY}


def quality_facts() -> dict:
    """This delivery never manufactures a judgment label from downstream success or failure."""
    return {"label": "unknown", "basis": QUALITY_BASIS,
            "requires": "an independently reviewed diagnosis linked to this decision"}


def observation_body(run: dict, session: dict, event: dict, binding: dict, contract: dict, *,
                     source_kind: str, artifact: dict) -> dict:
    """The joined read-only observation. Identities, digests and closed vocabularies only.
    `artifact` is what the execution-evidence port proved about the bytes behind `execution_ref`."""
    identity = run.get("identity") if isinstance(run.get("identity"), dict) else {}
    goal = run.get("goal") if isinstance(run.get("goal"), dict) else {}
    decision = decision_facts(session, event, binding)
    outcome = outcome_facts(run)
    body = {"schema": OBSERVATION_SCHEMA, "id": run["id"], "run_id": run["id"],
            "repository": contract["repository"], "source_kind": source_kind,
            "source_revision": session.get("base_revision"), "manifest_sha256": run.get("manifest_sha256"),
            "policy_identity": {"runtime_policy": identity.get("runtime_policy"),
                                "provider": identity.get("provider"), "evidence_profile": identity.get("evidence_profile")},
            "goal": {"path": goal.get("path"), "sha256": goal.get("sha256")},
            "contract": contract, "group_id": group_id(contract),
            "decision": decision, "outcome": outcome, "quality": quality_facts(),
            "evidence": {"status": EVIDENCE_VERIFIED, "artifact": dict(artifact), "scope": (
                "run, session, event and task rows bind the same execution identity, and the stored "
                "execution artifact behind execution_ref is that execution's own answer")}}
    body["decision_sha256"] = digest({k: body[k] for k in ("run_id", "repository", "source_kind", "source_revision",
                                                           "manifest_sha256", "contract", "decision", "goal")})
    body["outcome_sha256"] = digest(outcome)
    return body


def conflict_body(stored: dict, observed: dict, kind: str) -> dict:
    """A changed terminal source history is an owner question, never a better outcome to overwrite."""
    return {"schema": CONFLICT_SCHEMA,
            "id": "conflict:" + digest({"run_id": stored["run_id"], "kind": kind,
                                        "stored": [stored["decision_sha256"], stored["outcome_sha256"]],
                                        "observed": [observed["decision_sha256"], observed["outcome_sha256"]]}),
            "run_id": stored["run_id"], "kind": kind,
            "stored": {"decision_sha256": stored["decision_sha256"], "outcome_sha256": stored["outcome_sha256"],
                       "outcome_state": stored["outcome"]["state"], "source_status": stored["outcome"]["source_status"]},
            "observed": {"decision_sha256": observed["decision_sha256"], "outcome_sha256": observed["outcome_sha256"],
                         "outcome_state": observed["outcome"]["state"], "source_status": observed["outcome"]["source_status"]},
            "disposition": "owner_inspection_required; the recorded observation is unchanged"}


def candidate_body(*, repository: str, procedure_id: str, remediation: str, registry_revision: str,
                   registry_path: str, registry_sha256: str, source_kind: str, occurrences: list,
                   outcomes: dict, group: dict) -> dict:
    """One advisory candidate. `occurrences` are bounded immutable evidence references, one per
    distinct run identity; a retry, replay, receipt copy or repeated collection is not another one.
    `distinct_runs` counts the group's durable membership exactly, and `unrecorded_runs` is derived
    from that membership, so re-collecting a group larger than the reported cap inflates nothing."""
    window = occurrence_window(group["run_ids"])
    return {"schema": CANDIDATE_SCHEMA,
            "id": candidate_id(repository, procedure_id, registry_revision),
            "repository": repository, "procedure_id": procedure_id, "source_kind": source_kind,
            "registry": {"revision": registry_revision, "path": registry_path, "sha256": registry_sha256},
            "remediation": remediation, "status": CANDIDATE_STATUS, "verified": False,
            "group_id": group["id"], "contract": group["contract"],
            "distinct_runs": len(group["run_ids"]),
            "unrecorded_runs": window["unreferenced"],
            "membership_capped": bool(group.get("membership_capped")),
            "occurrences": occurrences, "outcomes": outcomes,
            "outcomes_scope": "the occurrence references reported above, not the unreferenced remainder",
            "quality": quality_facts(), "authority": CANDIDATE_AUTHORITY, "limits": list(LIMITS)}


def verified_binding(run: dict, session: dict, event: dict, task: dict, run_binding, source_kind: str) -> dict:
    """The one evidence gate: the decision event, the run row and the task row must carry the SAME
    execution identity, executor-bound and owned by this run. Returns a fixed reason code, or the
    event binding that was proven. Nothing here is repaired, defaulted or inferred."""
    run_id = run.get("id")
    if not isinstance(session, dict) or session.get("owner") != run_id or session.get("origin") != ORIGIN_EXECUTOR \
            or session.get("id") != run.get("session_id") or session.get("packet_digest") != run.get("packet_digest") \
            or not _sha256(session.get("packet_digest") or ""):
        return {"reason": "decision_session_unproven", "binding": None}
    if not isinstance(event, dict) or event.get("session_id") != session["id"] or event.get("role") != DECISION_SLOT \
            or event.get("origin") != ORIGIN_EXECUTOR or (event.get("event") or {}).get("packet_digest") != session["packet_digest"]:
        return {"reason": "decision_event_unproven", "binding": None}
    binding = event.get("binding")
    if not isinstance(binding, dict) or not isinstance(binding.get("task_id"), str) \
            or not isinstance(binding.get("execution_ref"), str) or binding.get("agent") != DECIDING_AGENT \
            or binding.get("stage") != "dge:" + DECIDING_ROLE or binding.get("origin") != ORIGIN_EXECUTOR:
        return {"reason": "decision_event_unproven", "binding": None}
    result = task.get("result") if isinstance(task, dict) and isinstance(task.get("result"), dict) else None
    if not (result and task.get("id") == binding["task_id"] and task.get("status") == "succeeded"
            and task.get("agent") == DECIDING_AGENT and result.get("execution_ref") == binding["execution_ref"]
            and task.get("generation") == binding.get("generation") and task.get("attempt") == binding.get("attempt")):
        return {"reason": "decision_execution_unproven", "binding": None}
    if not isinstance(run_binding, dict) or run_binding.get("task_id") != binding["task_id"] \
            or run_binding.get("execution_ref") != binding["execution_ref"] \
            or run_binding.get("output_sha256") != binding.get("output_sha256"):
        return {"reason": "decision_execution_unproven", "binding": None}
    if source_kind not in SOURCE_KINDS:
        return {"reason": "source_kind_unknown", "binding": None}
    return {"reason": EVIDENCE_VERIFIED, "binding": binding}


def source_kind_of(run: dict):
    """Council (autonomous v2) runs only in version 1: the conductor is the deciding role there."""
    topology = run.get("topology") if isinstance(run.get("topology"), dict) else {}
    roles = topology.get("roles") if isinstance(topology.get("roles"), dict) else {}
    deciding = roles.get(DECIDING_ROLE) if isinstance(roles.get(DECIDING_ROLE), dict) else {}
    if topology.get("version") == 2 and deciding.get("agent") == DECIDING_AGENT and deciding.get("slot") == DECISION_SLOT:
        return "council"
    return None


def scan_limit(limit) -> int:
    if type(limit) is not int or isinstance(limit, bool) or not 1 <= limit <= MAX_SCAN:
        raise DecisionFeedbackError("invalid_scan_limit")
    return limit


def registry_pin(revision, path, sha256=None) -> dict:
    """The Git pin the candidate evidence records: a full commit id, a safe repository-relative path
    and, when the caller has read the bytes, their exact digest."""
    if type(revision) is not str or REVISION.fullmatch(revision) is None:
        raise DecisionFeedbackError("registry_revision_invalid")
    if not safe_relative_path(path):
        raise DecisionFeedbackError("registry_path_invalid")
    if sha256 is not None and not _sha256(sha256):
        raise DecisionFeedbackError("registry_sha256_invalid")
    return {"revision": revision, "path": path}


__all__ = ["ARTIFACT_REASONS", "CANDIDATE_SCHEMA", "CANDIDATE_STATUS", "COLLECTION_AUTHORITY",
           "COLLECTION_SCHEMA", "CONFLICT_SCHEMA", "DECIDING_ROLE", "DECISION_SLOT", "DEFAULT_SCAN",
           "EVIDENCE_REASONS", "EVIDENCE_VERIFIED", "LIMITS", "MAX_MEMBERS", "MAX_OCCURRENCES",
           "MAX_OUTCOME_HISTORY", "MAX_SCAN", "OBSERVATION_SCHEMA", "OCCURRENCE_THRESHOLD",
           "OUTCOME_STATES", "RECORD_REASONS", "REGISTRY_SCHEMA", "REPORT_SCHEMA",
           "DecisionFeedbackError", "RegistryError", "add_member", "candidate_body", "candidate_id",
           "conflict_body", "criteria_digest", "decision_facts", "group_id", "match_registry",
           "observation_body", "occurrence_window", "outcome_facts", "quality_facts", "registry_pin",
           "scan_limit", "source_kind_of", "validate_registry", "verified_binding", "work_contract"]
