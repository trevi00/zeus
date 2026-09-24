"""Investigation-to-research bridge: the opt-in source configuration, the eligibility rule, the
immutable bounded snapshot and the dispatch row shape (INV-RESEARCH-PROGRAM-001, research-dispatch-001).

Everything here is policy over dictionaries: no store, clock, Git, network or provider access, and no
portfolio row is ever written from this module. A candidate is one coarse triage family - the same
terminal status and the same fixed reason code observed on two or more distinct bound jobs - so an
eligible investigation is an UNTRUSTED hypothesis, never a cause, an incident or an approved repair.
The owner's `portfolio_investigations.state` is read only; the caller supplies the required state and
the family minimum so `application/portfolio.py` stays the single authority for those definitions.
Values never enter refusal messages; field names do.
"""
from __future__ import annotations

import re

from codex_harness.domain.autonomous import (
    CONDUCTOR,
    RESEARCHER,
    ROLE_ACTION,
    ROLE_AGENTS,
    correlation_id,
    evidence_ref_for,
    execution_evidence,
    role_binding,
)
from codex_harness.domain.continuation import accepted_candidate
from codex_harness.domain.council import (
    COUNCIL_AGENTS,
    COUNCIL_DEBATE,
    COUNCIL_ORDER,
    DBA,
    FIELD_CODE,
    FIELD_LIMITS,
    FIELD_REFUSED,
    IMPROVEMENT_LEAD,
    RESEARCH_LEAD,
    CouncilFieldRefused,
    council_output,
)
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import ID, SHA256

SOURCE = "investigation"
# The candidate kind THIS rule owns. A `portfolio_investigations` row without a kind is a legacy
# failure family; a row of another kind (audit-progress, see `domain.audit_progress`) has its own
# rule, its own counts and its own snapshot, and is never scanned, counted or dispatched here.
KIND = "failure_family"
SOURCE_FIELDS = {"topic", "project_ids", "reason_codes"}
SNAPSHOT_SCHEMA = "urn:zeus:research-investigation-snapshot:1"
DISPATCH_SCHEMA = "urn:zeus:research-investigation-dispatch:1"
MAX_PROJECTS, MAX_REASON_CODES, MAX_JOB_SAMPLE = 20, 50, 50
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REASON_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
INVESTIGATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# The fixed exclusion vocabulary: bounded counts only, never a row, a value or a derived cause.
EXCLUSIONS = ("malformed", "state", "reason_code", "insufficient_jobs", "claimed")
CLAIMED, DISPATCHED, RESOLVED = "claimed", "dispatched", "resolved"
TRUST = ("unverified failure-family symptom recorded by the operating portfolio; identical symptoms "
         "are a hypothesis, never a cause, an incident resolution or an approved repair")
AUTHORITY = ("research dispatch claim and council outcome only; it is not an owner disposition, not an "
             "incident resolution and not a promotion")


class InvestigationRefused(ContractError):
    """Refused with a fixed reason code and at most a field name, never a value. The research program
    converts this into its own `ProgramRefused` so one refusal vocabulary reaches the operator."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("investigation source refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _list(values, limit: int, pattern, field: str) -> list:
    """Nonempty, bounded, distinct, pattern-matched. `null`, `[]`, a wildcard `*` and any non-string
    fail the pattern or the bound, so no rule here can widen to "every project" or "every reason"."""
    if not (isinstance(values, list) and 1 <= len(values) <= limit):
        raise InvestigationRefused("config_invalid", field)
    for value in values:
        if type(value) is not str or pattern.fullmatch(value) is None:
            raise InvestigationRefused("config_invalid", field + "[]")
    if len(set(values)) != len(values):
        raise InvestigationRefused("config_duplicate", field)
    return list(values)


def validate_source(document, topic_ids) -> dict:
    """The optional `investigation_source` block of `urn:zeus:research-program:1`. Present means the
    owner authorized THIS program's unchanged template plan for those projects and reason codes;
    absent means disabled and leaves the legacy canonical config (and its digest) untouched."""
    name = "investigation_source"
    if not isinstance(document, dict):
        raise InvestigationRefused("config_invalid", name)
    if set(document) != SOURCE_FIELDS:
        raise InvestigationRefused("config_fields", name)
    if type(document["topic"]) is not str or document["topic"] not in set(topic_ids):
        raise InvestigationRefused("config_invalid", name + ".topic")
    return {"topic": document["topic"],
            "project_ids": _list(document["project_ids"], MAX_PROJECTS, PROJECT_ID, name + ".project_ids"),
            "reason_codes": _list(document["reason_codes"], MAX_REASON_CODES, REASON_CODE, name + ".reason_codes")}


def candidate_identity(investigation_id: str) -> str:
    """Deterministic, bounded candidate id for one investigation; the full id stays on the row."""
    return "inv-" + investigation_id[:24]


def candidate_key(investigation_id: str) -> str:
    return SOURCE + ":" + investigation_id


def scoped_job_ids(investigation: dict, jobs: dict, bindings: dict, project_ids: set) -> list | None:
    """ONLY the referenced jobs that still exist, still carry this family's exact status and reason
    code, and are immutably bound to an allowed project. `None` marks a malformed row. Unrelated
    members of the same family are never added: the investigation's own membership is the scope."""
    referenced = investigation.get("job_ids")
    if not isinstance(referenced, list):
        return None
    status, reason = investigation.get("family_status"), investigation.get("reason_code")
    if type(status) is not str or type(reason) is not str or REASON_CODE.fullmatch(reason) is None:
        return None
    scoped = set()
    for job_id in referenced:
        if type(job_id) is not str or not job_id:
            return None
        job, binding = jobs.get(job_id), bindings.get(job_id)
        if job is None or binding is None:
            continue
        if job.get("status") != status or job.get("reason_code") != reason:
            continue
        if binding.get("project_id") not in project_ids:
            continue
        scoped.add(job_id)
    return sorted(scoped)


def eligible_investigations(*, investigations, jobs, bindings, source: dict, claimed, required_state: str,
                            minimum: int) -> dict:
    """The deterministic eligibility rule over authoritative rows only, with bounded exclusion counts.

    Eligible: the row is well formed, its state is the owner's undecided `required_state`, its reason
    code is authorized by `source`, no dispatch claim exists for it (`claimed`, across ALL programs),
    and at least `minimum` distinct scoped jobs remain. No root cause is derived, no row is modified
    and a changed owner disposition simply stops being eligible. A row of another candidate kind is
    skipped before it is scanned: this rule's counts describe failure families only.
    """
    project_ids, reason_codes = set(source["project_ids"]), set(source["reason_codes"])
    job_rows = {j["id"]: j for j in jobs if isinstance(j, dict) and type(j.get("id")) is str}
    binding_rows = {b["job_id"]: b for b in bindings if isinstance(b, dict) and type(b.get("job_id")) is str}
    claimed_ids = set(claimed)
    counts = {"scanned": 0, "eligible": 0, **{name: 0 for name in EXCLUSIONS}}
    candidates = []
    for row in investigations:
        if isinstance(row, dict) and row.get("kind", KIND) != KIND:
            continue    # another candidate kind: not this family rule's population at all
        counts["scanned"] += 1
        if not isinstance(row, dict) or type(row.get("id")) is not str or INVESTIGATION_ID.fullmatch(row.get("id") or "") is None:
            counts["malformed"] += 1
            continue
        if row.get("state") != required_state:
            counts["state"] += 1
            continue
        if row.get("reason_code") not in reason_codes:
            counts["reason_code"] += 1
            continue
        if row["id"] in claimed_ids:
            counts["claimed"] += 1
            continue
        scoped = scoped_job_ids(row, job_rows, binding_rows, project_ids)
        if scoped is None:
            counts["malformed"] += 1
            continue
        if len(scoped) < minimum:
            counts["insufficient_jobs"] += 1
            continue
        counts["eligible"] += 1
        candidates.append({"investigation": row["id"], "family_status": row["family_status"],
                           "reason_code": row["reason_code"], "job_ids": scoped,
                           "projects": sorted({binding_rows[j]["project_id"] for j in scoped})})
    return {"candidates": sorted(candidates, key=lambda c: c["investigation"]), "counts": counts}


def snapshot(*, candidate: dict, program_id: str, cycle_number: int, topic: str, observed_at: str) -> dict:
    """The immutable bounded source snapshot the council receives: versioned schema, identities, the
    fixed codes, at most MAX_JOB_SAMPLE job ids with the complete count and the digest of the FULL
    scoped id set (so truncation is explicit), the observation time and the explicit unverified trust.
    No prompt, output, exception, error text, credential or provider stream is ever copied here."""
    ids = sorted(candidate["job_ids"])
    return {"schema": SNAPSHOT_SCHEMA, "investigation": candidate["investigation"], "program": program_id,
            "cycle": cycle_number, "topic": topic, "family_status": candidate["family_status"],
            "reason_code": candidate["reason_code"], "projects": list(candidate["projects"]),
            "job_ids": ids[:MAX_JOB_SAMPLE], "job_ids_total": len(ids), "job_ids_sha256": digest(ids),
            "job_ids_truncated": len(ids) > MAX_JOB_SAMPLE, "observed_at": observed_at, "trust": TRUST}


def dispatch_row(*, document: dict, candidate_id: str, cycle_ref: str, now: str) -> dict:
    """The `research_investigation_dispatches` claim, keyed SOLELY by investigation id: one claim
    across programs and across candidate kinds. It binds program, cycle, the snapshot digest, the
    kind and the fixed codes; run and manifest are bound when the council starts, never before.

    A failure family binds its scoped job ids. Another kind (audit progress) has no job membership
    at all, so the job fields are explicitly `null` and its own bounded scope travels in `scope`: an
    empty list would read as a failed-job family with no members, which it is not.
    """
    kind = document.get("kind", KIND)
    family = kind == KIND
    return {"schema": DISPATCH_SCHEMA, "id": document["investigation"], "investigation": document["investigation"],
            "kind": kind, "scope": None if family else scope_reference(document),
            "program": document["program"], "cycle": cycle_ref, "cycle_number": document["cycle"],
            "candidate": candidate_id, "state": CLAIMED, "snapshot_sha256": digest(document),
            "family_status": document.get("family_status"), "reason_code": document["reason_code"],
            "job_ids": list(document["job_ids"]) if family else None,
            "job_ids_total": document["job_ids_total"] if family else None,
            "job_ids_sha256": document["job_ids_sha256"] if family else None,
            "run_id": None, "manifest_sha256": None,
            "manifest_ref": None, "result": None, "result_reason": None, "row_status": None,
            "reported_result": None, "failure": None, "claimed_at": now, "started_at": None,
            "finished_at": None, "updated_at": now, "authority": AUTHORITY}


def scope_reference(document: dict) -> dict:
    """The bounded scope of a non-family claim: identifiers and digests only, never a measurement,
    a path, a cursor or any source text."""
    return {key: document.get(key) for key in ("audit_id", "epoch", "policy_sha256")}


def dispatch_view(row: dict) -> dict:
    """The bounded read-only projection: identifiers, fixed codes and counts only. `kind` and
    `scope` are additive: a legacy row reads as the failure family it is."""
    keys = ("investigation", "program", "cycle", "cycle_number", "state", "result", "result_reason", "row_status",
            "reported_result", "run_id", "manifest_sha256", "snapshot_sha256", "family_status", "reason_code",
            "job_ids_total", "job_ids_sha256", "failure", "claimed_at", "started_at", "finished_at", "updated_at")
    # `id`, `recovery` and `supersedes` are additive: a replacement dispatch names the failed one it
    # replaced, and a legacy row reads as its own original (`id` = investigation, no lineage).
    return {**{k: row.get(k) for k in keys}, "kind": row.get("kind", KIND), "scope": row.get("scope"),
            "id": row.get("id", row.get("investigation")), "recovery": row.get("recovery"),
            "supersedes": row.get("supersedes")}


# ----- failed-dispatch recovery (research-dispatch-recovery-001) --------------------------------------
# ONE owner-authorized replacement of a failure-family dispatch whose council provably failed before
# any provider entry. The failed dispatch, its run, cycle and outbox record stay historical facts; the
# lineage row (`research_dispatch_recoveries`, keyed by investigation id, one per investigation ever)
# names the replacement dispatch key, so there is exactly one current dispatch per investigation.
RECOVERY_SCHEMA = "urn:zeus:research-dispatch-recovery:1"
RECOVERY_FIELDS = {"schema", "investigation", "failed", "replacement"}
RECOVERY_FAILED_FIELDS = {"program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256"}
RECOVERY_REPLACEMENT_FIELDS = {"program", "config_sha256"}
# The only qualifying failure: the council's own first assignment was never proven published, so the
# run stopped before any reservation, task admission or provider entry (INV-MESSAGE-001).
PRE_PROVIDER_FAILURE = "publication_incomplete"
FENCED, AUTHORIZED, RECOVERED, REFUSED = "fenced", "authorized", "claimed", "refused"
FENCE_REASON = "ResearchDispatchSuperseded"
PROGRAM_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$")
CYCLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}:[0-9]{3,}$")
# Attempt statuses recorded before any transport was handed the bytes: no probe is needed for them.
PRE_PUBLISH_ATTEMPTS = {"superseded_before_publish", "transport_unavailable", "transport_changed_before_publish"}
# A delivery error AFTER the publish call: the bytes may have landed on the attempt's bound transport,
# which the probe must prove absent on that SAME transport. Anything else is unknown.
EFFECT_POSSIBLE_ATTEMPTS = {"retry"}
UNSENT_ATTEMPTS = PRE_PUBLISH_ATTEMPTS | EFFECT_POSSIBLE_ATTEMPTS
RECOVERY_AUTHORITY = ("owner-authorized replacement of one proven pre-provider dispatch failure; the "
                      "failed dispatch, run and cycle are retained history, never accepted or deleted")
# Explicit execution revocation (SPEC "Actual legacy research recovery: execution revocation"): a
# SEPARATE request version for an attempt whose transport history is unknown. It never claims the old
# message was not delivered; it revokes that message's execution authority in THIS control store by
# advancing the existing task identity fence while the task is still absent, so a late delivery can
# never be admitted by `Workflow.submit`. Every other recovery precondition is unchanged.
REVOCATION_SCHEMA = "urn:zeus:research-dispatch-recovery:2"
REVOCATION_MODE = "execution_revocation"
REVOCATION_FIELDS = RECOVERY_FIELDS | {"mode", "revoke"}
REVOCATION_REVOKE_FIELDS = {"message_id", "source_sha256"}
REVOCATION_PROOF = "execution_revoked"
REVOCATION_BUCKET, REVOCATION_GENERATION = "tasks", 1
REVOCATION_AUTHORITY = ("execution authority of the named assignment revoked in this control store only; its "
                        "historical delivery stays unknown and is never reported as not delivered")


def revocation_owner(request_sha256: str) -> str:
    """The fence owner that marks THIS request's revocation; an arbitrary fence never carries it."""
    return "research-dispatch-recovery:" + request_sha256


def validate_recovery_request(document) -> dict:
    """Strict owner request; returns the canonical copy. It pins the investigation, the exact failed
    dispatch identity and the registered replacement program by its immutable config digest. Version 2
    is the explicit `execution_revocation` mode and additionally pins the exact assignment revoked."""
    def check(condition, field):
        if not condition:
            raise InvestigationRefused("recovery_request_invalid", field)
    check(isinstance(document, dict) and document.get("schema") in {RECOVERY_SCHEMA, REVOCATION_SCHEMA}, "schema")
    revocation = document["schema"] == REVOCATION_SCHEMA
    check(set(document) == (REVOCATION_FIELDS if revocation else RECOVERY_FIELDS), "root")
    if revocation:
        check(document["mode"] == REVOCATION_MODE, "mode")
        revoke = document["revoke"]
        check(isinstance(revoke, dict) and set(revoke) == REVOCATION_REVOKE_FIELDS, "revoke")
        check(type(revoke["message_id"]) is str and ID.fullmatch(revoke["message_id"]) is not None,
              "revoke.message_id")
        check(type(revoke["source_sha256"]) is str and SHA256.fullmatch(revoke["source_sha256"]) is not None,
              "revoke.source_sha256")
    check(type(document["investigation"]) is str and INVESTIGATION_ID.fullmatch(document["investigation"]) is not None,
          "investigation")
    failed, replacement = document["failed"], document["replacement"]
    check(isinstance(failed, dict) and set(failed) == RECOVERY_FAILED_FIELDS, "failed")
    check(type(failed["program"]) is str and PROGRAM_REF.fullmatch(failed["program"]) is not None, "failed.program")
    check(type(failed["cycle"]) is str and CYCLE_REF.fullmatch(failed["cycle"]) is not None, "failed.cycle")
    check(type(failed["run_id"]) is str and ID.fullmatch(failed["run_id"]) is not None, "failed.run_id")
    for key in ("manifest_sha256", "snapshot_sha256"):
        check(type(failed[key]) is str and SHA256.fullmatch(failed[key]) is not None, "failed." + key)
    check(isinstance(replacement, dict) and set(replacement) == RECOVERY_REPLACEMENT_FIELDS, "replacement")
    check(type(replacement["program"]) is str and PROGRAM_REF.fullmatch(replacement["program"]) is not None,
          "replacement.program")
    check(replacement["program"] != failed["program"], "replacement.program")
    check(type(replacement["config_sha256"]) is str and SHA256.fullmatch(replacement["config_sha256"]) is not None,
          "replacement.config_sha256")
    canonical = {"schema": document["schema"], "investigation": document["investigation"],
                 "failed": {k: failed[k] for k in sorted(RECOVERY_FAILED_FIELDS)},
                 "replacement": {k: replacement[k] for k in sorted(RECOVERY_REPLACEMENT_FIELDS)}}
    if revocation:
        canonical.update(mode=REVOCATION_MODE,
                         revoke={k: document["revoke"][k] for k in sorted(REVOCATION_REVOKE_FIELDS)})
    return canonical


def replacement_dispatch_id(investigation: str) -> str:
    """The deterministic key of the ONE replacement dispatch; the failed row keeps the plain id."""
    return investigation + ".recovery-1"


def current_dispatch_id(investigation: str, recovery, head=None) -> str:
    """The key of the dispatch that currently answers for `investigation`. Once a recovery is
    authorized the replacement is current - even before it is claimed, so the failed row can never
    answer again - and a fenced or refused recovery leaves the original row current. A successor head
    (written only when a settled read-only successor is authorized) names the current one after that;
    its integrity is judged by `successor_held`, which every consumer checks before trusting it."""
    if isinstance(head, dict) and type(head.get("dispatch")) is str:
        return head["dispatch"]
    if isinstance(recovery, dict) and recovery.get("state") in {AUTHORIZED, RECOVERED}:
        return (recovery.get("replacement") or {}).get("dispatch") or replacement_dispatch_id(investigation)
    return investigation


def check_recovery(request: dict, *, investigation, required_state: str, dispatch, program, cycle, run_result: dict,
                   run, outbox: list, tasks: list, reservations: list, residue: list, delivery, attempts: list,
                   replacement, same_authority: bool, fence) -> dict:
    """Every precondition of one recovery against authoritative reads; the first gap refuses by name.

    Qualifies ONLY a failure-family dispatch resolved `failed` with `publication_incomplete`, whose run
    row is terminal `failed` at stage `research` with zero reserved starts, no invocation, no role, no
    packet, no task, no reservation and no session/operation residue, and whose single outbox record
    is the researcher assignment still unsent with no delivered, started or errored attempt. `fence`
    None expects the unfenced record; otherwise the delivery row must still be exactly that fence.
    The replacement program must be registered with the pinned digest, never ticked, in the same
    repository and carry the same authority. Returns the identities of the fenced assignment.

    An `execution_revocation` request skips ONLY the transport derivation: its assignment must be the
    exact message id and source digest it pinned (`recovery_message_changed`), and `transport` is
    returned None because its history stays unknown; every other check above still applies."""
    failed = request["failed"]
    revoke = request.get("revoke") if request.get("mode") == REVOCATION_MODE else None
    if not (isinstance(investigation, dict) and investigation.get("kind", KIND) == KIND
            and investigation.get("state") == required_state):
        raise InvestigationRefused("recovery_investigation_changed", "investigation")
    if not (isinstance(dispatch, dict) and dispatch.get("id") == request["investigation"]
            and dispatch.get("investigation") == request["investigation"] and dispatch.get("kind", KIND) == KIND
            and dispatch.get("program") == failed["program"] and dispatch.get("cycle") == failed["cycle"]
            and all(dispatch.get(key) == failed[key] for key in ("run_id", "manifest_sha256", "snapshot_sha256"))):
        raise InvestigationRefused("recovery_dispatch_mismatch", "failed")
    if dispatch.get("state") != RESOLVED or dispatch.get("result") != "failed":
        raise InvestigationRefused("recovery_dispatch_not_failed", "failed")
    if dispatch.get("result_reason") != PRE_PROVIDER_FAILURE:
        raise InvestigationRefused("recovery_not_pre_provider", "failed")
    if not (isinstance(program, dict) and program.get("state") == "blocked" and program.get("active_cycle") is None):
        raise InvestigationRefused("recovery_program_not_blocked", "failed.program")
    council = (cycle or {}).get("council") if isinstance(cycle, dict) else None
    if not (isinstance(council, dict) and cycle.get("program") == failed["program"] and cycle.get("result") == "failed"
            and cycle.get("status") == "completed" and council.get("run_id") == failed["run_id"]
            and council.get("manifest_sha256") == failed["manifest_sha256"] and council.get("status") == "failed"):
        raise InvestigationRefused("recovery_cycle_mismatch", "failed.cycle")
    if not (run_result.get("result") == "failed" and run_result.get("reason_code") == PRE_PROVIDER_FAILURE
            and isinstance(run, dict) and run.get("status") == "failed" and run.get("finished_at")):
        raise InvestigationRefused("recovery_run_not_pre_provider", "failed.run_id")
    starts = run.get("starts") if isinstance(run.get("starts"), dict) else {}
    if not (run.get("stage") == "research" and starts.get("reserved") == 0 and starts.get("settled") == 0
            and starts.get("slots") == [] and not run.get("invocations") and not run.get("roles")
            and run.get("packet_digest") is None):
        raise InvestigationRefused("recovery_provider_entered", "failed.run_id")
    if tasks:
        raise InvestigationRefused("recovery_task_exists", "failed.run_id")
    if reservations:
        raise InvestigationRefused("recovery_invocation_exists", "failed.run_id")
    if residue:
        raise InvestigationRefused("recovery_residue", "failed.run_id")
    agent, correlation = ROLE_AGENTS[RESEARCHER], correlation_id({"id": failed["run_id"]})
    message = outbox[0].get("message") if len(outbox) == 1 and isinstance(outbox[0], dict) else None
    if not (isinstance(message, dict) and message.get("type") == "task.assign" and message.get("correlation_id") == correlation
            and (message.get("who") or {}).get("recipient") == agent
            and ((message.get("what") or {}).get("details") or {}).get("role") == RESEARCHER
            and type(message.get("message_id")) is str):
        raise InvestigationRefused("recovery_outbox_unexpected", "failed.run_id")
    delivery = delivery if isinstance(delivery, dict) else None
    statuses = {a.get("status") for a in attempts}
    if outbox[0].get("sent") is not False or (delivery or {}).get("delivered_entry_id") or "delivered" in statuses:
        raise InvestigationRefused("recovery_message_delivered", "failed.run_id")
    if not statuses <= UNSENT_ATTEMPTS:
        raise InvestigationRefused("recovery_effect_unknown", "failed.run_id")
    if revoke is not None and (message["message_id"] != revoke["message_id"]
                               or digest(outbox[0]) != revoke["source_sha256"]):
        raise InvestigationRefused("recovery_message_changed", "revoke")
    transport = None if revoke is not None else attempted_transport(attempts)
    if fence is None:
        if delivery is not None and delivery.get("status") != "retry":
            raise InvestigationRefused("recovery_effect_unknown", "failed.run_id")
    elif not (delivery is not None and delivery.get("status") == "quarantined"
              and delivery.get("source_hash") == fence.get("source_hash") == digest(outbox[0])
              and len(attempts) == fence.get("attempts") and delivery.get("attempts", 0) == fence.get("attempts")
              and fence.get("transport") == transport):
        raise InvestigationRefused("recovery_publication_changed", "failed.run_id")
    new = request["replacement"]
    if not (isinstance(replacement, dict) and replacement.get("id") == new["program"]
            and replacement.get("config_sha256") == new["config_sha256"]):
        raise InvestigationRefused("recovery_replacement_mismatch", "replacement")
    if not (replacement.get("state") == "paused" and replacement.get("cycles") == 0 and replacement.get("adoptions") == 0
            and replacement.get("active_cycle") is None and replacement.get("next_cycle") == 1):
        raise InvestigationRefused("recovery_replacement_not_fresh", "replacement")
    if not (same_authority and replacement.get("repository") == program.get("repository")):
        raise InvestigationRefused("recovery_scope_changed", "replacement")
    return {"message_id": message["message_id"], "recipient": agent, "correlation_id": correlation,
            "source_hash": digest(outbox[0]), "attempts": len(attempts), "transport": transport}


def _binding(value) -> bool:
    return (isinstance(value, dict) and type(value.get("schema")) is str and bool(value["schema"])
            and all(value[key] is not None and value[key] != "" for key in value))


def attempted_transport(attempts: list):
    """The ONE transport the failed assignment may have reached, from the bindings its outbox
    attempts committed BEFORE publishing. None: no attempt ever called publish, so no transport can
    hold it. An effect-possible attempt without a binding (every attempt recorded before bindings
    existed) is `recovery_transport_unbound`: today's configuration or an owner assertion is never
    substituted for it. Two different bound transports are `recovery_transport_changed`: one probe
    cannot prove absence on both."""
    bindings = []
    for attempt in attempts:
        if attempt.get("status") not in EFFECT_POSSIBLE_ATTEMPTS:
            continue
        if not _binding(attempt.get("transport")):
            raise InvestigationRefused("recovery_transport_unbound", "failed.run_id")
        if attempt["transport"] not in bindings:
            bindings.append(attempt["transport"])
    if len(bindings) > 1:
        raise InvestigationRefused("recovery_transport_changed", "failed.run_id")
    return bindings[0] if bindings else None


def check_transport_proof(bound, observation) -> bool:
    """Absence counts ONLY on the bound transport: the probe's identity read before and after its
    complete stream read must both equal the committed binding. An unreadable identity is
    `recovery_transport_unavailable`; any other identity (another endpoint, database, namespace,
    server process or storage token) is `recovery_transport_changed`. Returns True when the message
    is absent there. Equality proves the same identity, not that no entry was ever deleted."""
    if not isinstance(observation, dict):
        raise InvestigationRefused("recovery_transport_unavailable", "transport")
    before, after = observation.get("before"), observation.get("after")
    if not (isinstance(before, dict) and isinstance(after, dict)):
        raise InvestigationRefused("recovery_transport_unavailable", "transport")
    # A probe never creates the storage token: a server without it reads `storage` None, never equal.
    if not (_binding(bound) and before == after == bound):
        raise InvestigationRefused("recovery_transport_changed", "transport")
    absent = observation.get("absent")
    if type(absent) is not bool:
        raise InvestigationRefused("recovery_transport_unavailable", "transport")
    return absent


def revocation_evidence(*, request_sha256: str, fence: dict, source_hash: str) -> dict:
    """The immutable revocation record, copied from the task identity fence written in the same
    transaction. `delivery` stays `unknown`: revocation is not a non-delivery claim."""
    return {"bucket": fence["bucket"], "row_id": fence["row_id"], "generation": fence["generation"],
            "owner": fence["owner"], "fenced_at": fence["at"], "message_sha256": source_hash,
            "request_sha256": request_sha256, "delivery": "unknown", "authority": REVOCATION_AUTHORITY}


def revocation_task_id(row) -> str | None:
    """The task identity a revocation-mode lineage row fenced; None for a transport-proof row."""
    if not (isinstance(row, dict) and row.get("proof") == REVOCATION_PROOF):
        return None
    revocation = row.get("revocation")
    task_id = revocation.get("row_id") if isinstance(revocation, dict) else None
    return task_id if type(task_id) is str and task_id else ""


def revocation_held(row, *, fence, task, delivery) -> str | None:
    """None when a revocation-mode lineage row still holds its OWN retained fence; otherwise the named
    held condition. A transport-proof row is not judged here (None). An existing fence is proof only
    when it is exactly the one this request wrote: same identity, generation, owner and time; a
    missing, changed or corrupt fence, a task that appeared, or a quarantine that moved never releases
    a replacement claim or a scoped receipt."""
    task_id = revocation_task_id(row)
    if task_id is None:
        return None
    revocation, request_sha = row.get("revocation"), row.get("request_sha256")
    source = (row.get("fence") or {}).get("source_hash") if isinstance(row.get("fence"), dict) else None
    if not (task_id and type(request_sha) is str and revocation.get("request_sha256") == request_sha
            and revocation.get("bucket") == REVOCATION_BUCKET
            and revocation.get("generation") == REVOCATION_GENERATION
            and revocation.get("owner") == revocation_owner(request_sha)
            and type(source) is str and revocation.get("message_sha256") == source
            and (row.get("fence") or {}).get("outbox") == task_id):
        return "recovery_revocation_corrupt"
    if task is not None:
        return "recovery_revocation_breached"
    if fence is None:
        return "recovery_revocation_fence_missing"
    expected = {"id": REVOCATION_BUCKET + ":" + task_id, "bucket": REVOCATION_BUCKET, "row_id": task_id,
                "generation": REVOCATION_GENERATION, "owner": revocation["owner"], "at": revocation.get("fenced_at")}
    if not (isinstance(fence, dict) and fence == expected):
        return "recovery_revocation_fence_changed"
    if not (isinstance(delivery, dict) and delivery.get("status") == "quarantined"
            and delivery.get("source_hash") == source):
        return "recovery_publication_changed"
    return None


# ----- settled read-only successor (SPEC "Real council progress: ... settled-read-only successor") --------------
# A CURRENT replacement dispatch whose council actually completed ONLY the read-only researcher and DBA
# roles (every task succeeded, every invocation settled and bound to its own execution artifact) and then
# stopped `foreign_message` may be succeeded ONCE per exact head by a new registered program with the same
# authority, on the owner's explicit version-3 request. The original recovery row stays the sole record of
# the first recovery; every successor is an immutable authorization row (`research_dispatch_successors`,
# keyed `<investigation>:<version>`) and the versioned head (`research_dispatch_heads`) points at the
# current one. The predecessor's two calls stay counted as two: nothing is relabelled or reused.
SUCCESSOR_SCHEMA = "urn:zeus:research-dispatch-recovery:3"
SUCCESSOR_MODE = "settled_read_only_successor"
SUCCESSOR_FIELDS = {"schema", "mode", "investigation", "predecessor", "replacement"}
SUCCESSOR_PREDECESSOR_FIELDS = {"dispatch", "lineage_version", "lineage_request_sha256", "program", "config_sha256",
                                "cycle", "run_id", "manifest_sha256", "snapshot_sha256"}
SUCCESSOR_PROOF = "settled_read_only"
# The only qualifying stop: an exact-correlation drain refused a message of another run.
READ_ONLY_FAILURE = "foreign_message"
READ_ONLY_ROLES = {RESEARCHER: ROLE_AGENTS[RESEARCHER], DBA: COUNCIL_AGENTS[DBA]}
READ_ONLY_STAGES = {"research", "packet", "snapshot", DBA}
READ_ONLY_PARTIES = {CONDUCTOR, *READ_ONLY_ROLES.values()}
SUCCESSOR_AUTHORITY = ("owner-authorized successor of one failed dispatch whose council settled only read-only "
                       "researcher/DBA executions; the predecessor's calls stay counted and its outputs are never "
                       "reused as an accepted council")
# ----- settled council contract failure successor (SPEC "Settled council contract failure recovery") ----------
# The INITIAL or CURRENT dispatch whose council settled only read-only researcher/DBA/research-lead/
# improvement-lead executions and then stopped because one role output failed a NAMED council field check
# (`domain.council.FIELD_CODE`) may be succeeded ONCE per exact head, on the owner's explicit version-4
# request, through the SAME successor rows and versioned head as version 3. The failure is never taken from
# the recorded reason alone: the pinned role's bound execution artifact is re-derived through the consumer
# and must raise exactly the pinned code. Version 1 stays reserved for the original recovery's replacement,
# so the successor of an initial dispatch (lineage version 0) is version 2 and `.recovery-1` stays unused.
CONTRACT_SCHEMA = "urn:zeus:research-dispatch-recovery:4"
CONTRACT_MODE = "settled_contract_failure_successor"
CONTRACT_FIELDS = SUCCESSOR_FIELDS | {"failure"}
CONTRACT_FAILURE_FIELDS = {"role", "task_id", "execution_ref", "check"}
CONTRACT_PROOF = "settled_contract_failure"
# The run reason of a council that refused a field: the exact typed code, or the legacy generic mapping
# recorded before the typed code existed (release-checklist-research-001.c001). Both need the re-derivation.
LEGACY_CONTRACT_FAILURE = "debate_refused:ContractError"
CONTRACT_RESULT_REASONS = {FIELD_REFUSED, LEGACY_CONTRACT_FAILURE.partition(":")[0]}
# Debate roles whose output carries council-owned bounded fields; the conductor never qualifies.
CONTRACT_ROLES = {role: COUNCIL_AGENTS[role] for role in (RESEARCH_LEAD, IMPROVEMENT_LEAD)
                  if role in FIELD_LIMITS}
CONTRACT_READ_ROLES = {**READ_ONLY_ROLES, RESEARCH_LEAD: COUNCIL_AGENTS[RESEARCH_LEAD],
                       IMPROVEMENT_LEAD: COUNCIL_AGENTS[IMPROVEMENT_LEAD]}
EXECUTION_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
INITIAL_VERSION, FIRST_SUCCESSOR = 0, 2
CONTRACT_AUTHORITY = ("owner-authorized successor of one failed dispatch whose council settled only read-only role "
                      "executions and refused a named output field; the predecessor's calls stay counted and its "
                      "outputs are never rewritten or reused as an accepted council")


def successor_key(investigation: str, version: int) -> str:
    return investigation + ":" + str(version)


def successor_dispatch_id(investigation: str, version: int) -> str:
    """Version 1 is the original recovery's replacement (`replacement_dispatch_id`)."""
    return investigation + ".recovery-" + str(version)


def lineage_dispatch_id(investigation: str, version: int) -> str:
    """The dispatch key a lineage version names: version 0 is the initial dispatch itself."""
    return investigation if version == INITIAL_VERSION else successor_dispatch_id(investigation, version)


def successor_version(lineage_version: int) -> int:
    """The version of the successor of `lineage_version`; version 1 is never a successor."""
    return max(lineage_version + 1, FIRST_SUCCESSOR)


def validate_contract_request(document) -> dict:
    """Strict version-4 owner request; returns the canonical copy. The predecessor pins the same identities
    as version 3, but its lineage version may be 0 (the initial dispatch, no lineage request digest); the
    failure pins the role, its task, its execution artifact and the exact safe field code."""
    def check(condition, field):
        if not condition:
            raise InvestigationRefused("recovery_request_invalid", field)
    check(isinstance(document, dict) and document.get("schema") == CONTRACT_SCHEMA, "schema")
    check(set(document) == CONTRACT_FIELDS, "root")
    check(document["mode"] == CONTRACT_MODE, "mode")
    investigation = document["investigation"]
    check(type(investigation) is str and INVESTIGATION_ID.fullmatch(investigation) is not None, "investigation")
    old, new, failure = document["predecessor"], document["replacement"], document["failure"]
    check(isinstance(old, dict) and set(old) == SUCCESSOR_PREDECESSOR_FIELDS, "predecessor")
    version = old["lineage_version"]
    check(type(version) is int and 0 <= version < 1000, "predecessor.lineage_version")
    check(old["dispatch"] == lineage_dispatch_id(investigation, version), "predecessor.dispatch")
    check(old["lineage_request_sha256"] is None if version == INITIAL_VERSION
          else type(old["lineage_request_sha256"]) is str and SHA256.fullmatch(old["lineage_request_sha256"]) is not None,
          "predecessor.lineage_request_sha256")
    check(type(old["program"]) is str and PROGRAM_REF.fullmatch(old["program"]) is not None, "predecessor.program")
    check(type(old["cycle"]) is str and CYCLE_REF.fullmatch(old["cycle"]) is not None, "predecessor.cycle")
    check(type(old["run_id"]) is str and ID.fullmatch(old["run_id"]) is not None, "predecessor.run_id")
    for key in ("config_sha256", "manifest_sha256", "snapshot_sha256"):
        check(type(old[key]) is str and SHA256.fullmatch(old[key]) is not None, "predecessor." + key)
    check(isinstance(failure, dict) and set(failure) == CONTRACT_FAILURE_FIELDS, "failure")
    check(failure["role"] in CONTRACT_ROLES, "failure.role")
    check(type(failure["task_id"]) is str and ID.fullmatch(failure["task_id"]) is not None, "failure.task_id")
    check(type(failure["execution_ref"]) is str and EXECUTION_REF.fullmatch(failure["execution_ref"]) is not None,
          "failure.execution_ref")
    code = FIELD_CODE.fullmatch(failure["check"]) if type(failure["check"]) is str else None
    check(code is not None and code.group(1) == failure["role"], "failure.check")
    check(isinstance(new, dict) and set(new) == RECOVERY_REPLACEMENT_FIELDS, "replacement")
    check(type(new["program"]) is str and PROGRAM_REF.fullmatch(new["program"]) is not None
          and new["program"] != old["program"], "replacement.program")
    check(type(new["config_sha256"]) is str and SHA256.fullmatch(new["config_sha256"]) is not None,
          "replacement.config_sha256")
    return {"schema": CONTRACT_SCHEMA, "mode": CONTRACT_MODE, "investigation": investigation,
            "predecessor": {k: old[k] for k in sorted(SUCCESSOR_PREDECESSOR_FIELDS)},
            "failure": {k: failure[k] for k in sorted(CONTRACT_FAILURE_FIELDS)},
            "replacement": {k: new[k] for k in sorted(RECOVERY_REPLACEMENT_FIELDS)}}


def validate_any_successor(document) -> dict:
    """Version dispatch for the owner: version 3 and version 4 each keep their own strict validator."""
    if isinstance(document, dict) and document.get("schema") == CONTRACT_SCHEMA:
        return validate_contract_request(document)
    return validate_successor_request(document)


CONTRACT_OTHER = "contract_other"


def contract_failure(role: str, answer, details) -> str | None:
    """Replay `council_output` for `answer` under the identities and packet claims the role was actually
    given (its immutable task details): None when it derives, the safe field code when a bounded field is
    refused, `contract_other` for any other refusal. Pure: no model call, nothing is repaired or kept."""
    if not isinstance(details, dict) or not isinstance(details.get("packet"), dict):
        return CONTRACT_OTHER
    claims = details["packet"].get("claims")
    claim_ids = {c.get("id") for c in claims if isinstance(c, dict)} if isinstance(claims, list) else set()
    identities = {"snapshot_digest": details.get("snapshot_digest"), "report_digest": details.get("report_digest")}
    try:
        council_output(role, answer, identities, claim_ids)
    except CouncilFieldRefused as exc:
        return exc.reason_code
    except ContractError:
        return CONTRACT_OTHER
    return None


def validate_successor_request(document) -> dict:
    """Strict version-3 owner request; returns the canonical copy. It pins the investigation, the exact
    current head (lineage version and the request digest that authorized it), the failed current
    dispatch with its program config, cycle, run, manifest and snapshot, and the new program."""
    def check(condition, field):
        if not condition:
            raise InvestigationRefused("recovery_request_invalid", field)
    check(isinstance(document, dict) and document.get("schema") == SUCCESSOR_SCHEMA, "schema")
    check(set(document) == SUCCESSOR_FIELDS, "root")
    check(document["mode"] == SUCCESSOR_MODE, "mode")
    check(type(document["investigation"]) is str and INVESTIGATION_ID.fullmatch(document["investigation"]) is not None,
          "investigation")
    old, new = document["predecessor"], document["replacement"]
    check(isinstance(old, dict) and set(old) == SUCCESSOR_PREDECESSOR_FIELDS, "predecessor")
    check(type(old["lineage_version"]) is int and 1 <= old["lineage_version"] < 1000, "predecessor.lineage_version")
    check(old["dispatch"] == successor_dispatch_id(document["investigation"], old["lineage_version"]),
          "predecessor.dispatch")
    check(type(old["program"]) is str and PROGRAM_REF.fullmatch(old["program"]) is not None, "predecessor.program")
    check(type(old["cycle"]) is str and CYCLE_REF.fullmatch(old["cycle"]) is not None, "predecessor.cycle")
    check(type(old["run_id"]) is str and ID.fullmatch(old["run_id"]) is not None, "predecessor.run_id")
    for key in ("lineage_request_sha256", "config_sha256", "manifest_sha256", "snapshot_sha256"):
        check(type(old[key]) is str and SHA256.fullmatch(old[key]) is not None, "predecessor." + key)
    check(isinstance(new, dict) and set(new) == RECOVERY_REPLACEMENT_FIELDS, "replacement")
    check(type(new["program"]) is str and PROGRAM_REF.fullmatch(new["program"]) is not None
          and new["program"] != old["program"], "replacement.program")
    check(type(new["config_sha256"]) is str and SHA256.fullmatch(new["config_sha256"]) is not None,
          "replacement.config_sha256")
    return {"schema": SUCCESSOR_SCHEMA, "mode": SUCCESSOR_MODE, "investigation": document["investigation"],
            "predecessor": {k: old[k] for k in sorted(SUCCESSOR_PREDECESSOR_FIELDS)},
            "replacement": {k: new[k] for k in sorted(RECOVERY_REPLACEMENT_FIELDS)}}


def lineage_head(investigation: str, recovery, head, successor) -> dict | None:
    """The current authorization of `investigation`: version, request digest, dispatch and state of
    either the head successor or (no head) the original recovery row. None when neither exists. A
    head whose successor row does not match it reads `corrupt` and never answers as current."""
    if isinstance(head, dict):
        version = head.get("version")
        if not (isinstance(successor, dict) and type(version) is int and successor.get("version") == version
                and successor.get("id") == head.get("successor") == successor_key(investigation, version)
                and successor.get("request_sha256") == head.get("request_sha256")
                and (successor.get("replacement") or {}).get("dispatch") == head.get("dispatch")
                == successor_dispatch_id(investigation, version)):
            return {"version": version, "request_sha256": None, "dispatch": None, "state": "corrupt"}
        return {"version": version, "request_sha256": successor["request_sha256"], "dispatch": head["dispatch"],
                "state": successor.get("state")}
    if isinstance(recovery, dict) and recovery.get("state") in {AUTHORIZED, RECOVERED}:
        return {"version": 1, "request_sha256": recovery.get("request_sha256"),
                "dispatch": (recovery.get("replacement") or {}).get("dispatch") or replacement_dispatch_id(investigation),
                "state": recovery.get("state")}
    return None


def _refuse(condition, code: str, field: str) -> None:
    if not condition:
        raise InvestigationRefused(code, field)


def check_successor(request: dict, *, investigation, required_state: str, lineage, dispatch, program, cycle,
                    run_result: dict, run,
                    tasks: list, reservations: list, artifacts: dict, outbox: list, deliveries: dict, attempts: list,
                    terminations: list, session, residue: list, replacement, same_authority: bool) -> dict:
    """Every precondition of one settled read-only successor against authoritative reads; the first gap
    refuses by name. `lineage` is `lineage_head` of the CURRENT authorization: it must be exactly the
    pinned version and request, already claimed by the pinned failed dispatch. That dispatch, its
    program (blocked, pinned config), cycle and run must be the terminal `failed:foreign_message` of a
    council whose run row, task rows, reservations and execution artifacts show ONLY succeeded
    researcher/DBA executions, each bound to its own settled accepted invocation, with nothing running,
    unknown, terminated, implemented or promoted. `artifacts` maps each execution_ref to its loaded
    document or to a fixed unavailability code. Returns the fence targets and the bound evidence.

    A version-4 `settled_contract_failure_successor` request applies the same rule to a wider read-only
    prefix: the pinned predecessor may be the INITIAL dispatch (lineage version 0: no recovery and no head,
    `lineage` None) or the current head; its council settled exactly researcher, DBA and the debate roles up
    to the pinned failed role (never the conductor), stopped at that role with the typed field code or the
    legacy generic mapping, recorded only the earlier debate events, and the failed role's bound artifact
    re-derives exactly the pinned field code. Returns the re-derived failure as evidence too."""
    old = request["predecessor"]
    failure = request.get("failure") if request.get("mode") == CONTRACT_MODE else None
    _refuse(isinstance(investigation, dict) and investigation.get("kind", KIND) == KIND
            and investigation.get("state") == required_state,
            "recovery_investigation_changed", "investigation")
    if failure is not None and old["lineage_version"] == INITIAL_VERSION:
        _refuse(lineage is None, "recovery_successor_stale", "predecessor")   # a lineage exists: not initial
    else:
        _refuse(isinstance(lineage, dict) and lineage.get("state") != "corrupt", "recovery_successor_corrupt", "predecessor")
        _refuse(lineage["version"] == old["lineage_version"] and lineage["request_sha256"] == old["lineage_request_sha256"]
                and lineage["dispatch"] == old["dispatch"], "recovery_successor_stale", "predecessor")
        _refuse(lineage["state"] == RECOVERED, "recovery_predecessor_active", "predecessor")
    _refuse(isinstance(dispatch, dict) and dispatch.get("id", dispatch.get("investigation")) == old["dispatch"]
            and dispatch.get("investigation") == request["investigation"] and dispatch.get("kind", KIND) == KIND
            and dispatch.get("program") == old["program"] and dispatch.get("cycle") == old["cycle"]
            and all(dispatch.get(k) == old[k] for k in ("run_id", "manifest_sha256", "snapshot_sha256")),
            "recovery_dispatch_mismatch", "predecessor")
    _refuse(dispatch.get("state") == RESOLVED, "recovery_predecessor_active", "predecessor")
    _refuse(dispatch.get("result") not in {"accepted", "rejected"}, "recovery_dispatch_not_failed", "predecessor")
    _refuse(dispatch.get("result") == "failed", "recovery_effect_unknown", "predecessor")
    if failure is None:
        allowed, prefix, stages, events = READ_ONLY_ROLES, None, READ_ONLY_STAGES, 0
        reasons, run_reasons = {READ_ONLY_FAILURE}, None   # version 3 unchanged: the safe reason head only
    else:
        # Exactly the council prefix up to the failed role; the debate events recorded are the earlier ones.
        prefix = COUNCIL_ORDER[:COUNCIL_ORDER.index(failure["role"]) + 1]
        allowed, stages = {r: CONTRACT_READ_ROLES[r] for r in prefix}, {failure["role"]}
        events = len([r for r in prefix if r in COUNCIL_DEBATE]) - 1
        # Any typed field code or the legacy mapping stops here; WHICH field is the proof step's question.
        recorded = run.get("reason_code") if isinstance(run, dict) and type(run.get("reason_code")) is str else ""
        reasons = CONTRACT_RESULT_REASONS
        run_reasons = {recorded} if recorded == LEGACY_CONTRACT_FAILURE or FIELD_CODE.fullmatch(recorded) else set()
    parties = {CONDUCTOR, *allowed.values()}
    _refuse(dispatch.get("result_reason") in reasons, "recovery_not_settled_read_only", "predecessor")
    _refuse(isinstance(program, dict) and program.get("id") == old["program"]
            and program.get("config_sha256") == old["config_sha256"], "recovery_dispatch_mismatch", "predecessor.program")
    _refuse(program.get("state") == "blocked" and program.get("active_cycle") is None,
            "recovery_program_not_blocked", "predecessor.program")
    council = (cycle or {}).get("council") if isinstance(cycle, dict) else None
    _refuse(isinstance(council, dict) and cycle.get("program") == old["program"] and cycle.get("result") == "failed"
            and cycle.get("status") == "completed" and council.get("run_id") == old["run_id"]
            and council.get("manifest_sha256") == old["manifest_sha256"] and council.get("status") == "failed",
            "recovery_cycle_mismatch", "predecessor.cycle")
    _refuse(run_result.get("result") == "failed" and run_result.get("reason_code") in reasons
            and isinstance(run, dict) and run.get("status") == "failed" and bool(run.get("finished_at"))
            and (run_reasons is None or run.get("reason_code") in run_reasons),
            "recovery_run_not_settled_read_only", "predecessor.run_id")
    _refuse(run.get("stage") in stages and run.get("operation") is None and run.get("promotion") is None
            and run.get("design") is None and not residue, "recovery_effect_outside_read_only", "predecessor.run_id")
    roles = run.get("roles") if isinstance(run.get("roles"), dict) else {}
    _refuse(bool(roles) and set(roles) <= set(allowed) and (prefix is None or set(roles) == set(prefix)),
            "recovery_effect_outside_read_only", "predecessor.run_id")
    _refuse((session is None and events == 0)
            or (isinstance(session, dict) and session.get("version") == events
                and session.get("decision_event_id") is None and not session.get("findings")),
            "recovery_effect_outside_read_only", "predecessor.run_id")
    starts = run.get("starts") if isinstance(run.get("starts"), dict) else {}
    slots = starts.get("slots") if isinstance(starts.get("slots"), list) else None
    _refuse(slots is not None and all(isinstance(s, dict) for s in slots), "recovery_invocation_unsettled", "predecessor.run_id")
    _refuse(all(s.get("kind") == "task" and s.get("agent") in allowed.values() and s.get("operation") is None
                for s in slots), "recovery_effect_outside_read_only", "predecessor.run_id")
    _refuse(starts.get("reserved") == starts.get("settled") == len(slots) == len(roles)
            and all(s.get("settled") is True and s.get("settle_error") is None for s in slots),
            "recovery_invocation_unsettled", "predecessor.run_id")
    _refuse(not terminations, "recovery_effect_unknown", "predecessor.run_id")
    _refuse(all(r.get("status") == "settled" for r in reservations), "recovery_invocation_unsettled", "predecessor.run_id")
    correlation = correlation_id({"id": old["run_id"]})
    bound, reservation_ids, threads, failed = [], set(), [], None
    for task in sorted(tasks, key=lambda t: str(t.get("id"))):
        message = task.get("message") if isinstance(task.get("message"), dict) else {}
        details = (message.get("what") or {}).get("details") if isinstance(message.get("what"), dict) else None
        role = details.get("role") if isinstance(details, dict) else None
        _refuse(role in allowed and task.get("agent") == allowed[role]
                and (message.get("what") or {}).get("action") == ROLE_ACTION,
                "recovery_effect_outside_read_only", "predecessor.run_id")
        _refuse(task.get("status") not in {"queued", "running", "retry", "dispatching"},
                "recovery_predecessor_active", "predecessor.run_id")
        _refuse(task.get("status") == "succeeded", "recovery_effect_unknown", "predecessor.run_id")
        recorded = roles.get(role) if isinstance(roles.get(role), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        ref = result.get("execution_ref")
        _refuse(recorded.get("task_id") == task.get("id") and recorded.get("execution_ref") == ref,
                "recovery_evidence_mismatch", "predecessor.run_id")
        artifact = artifacts.get(ref) if isinstance(ref, str) else "evidence_missing"
        if not isinstance(artifact, dict):
            code = artifact if artifact in {"evidence_missing", "evidence_corrupt"} else "evidence_unavailable"
            raise InvestigationRefused("recovery_" + code, "predecessor.run_id")
        base = (message.get("where") or {}).get("revision") if isinstance(message.get("where"), dict) else None
        reservation_id = (artifact.get("invocation") or {}).get("reservation") if isinstance(artifact.get("invocation"), dict) else None
        reservation = next((r for r in reservations if r.get("id") == reservation_id), None)
        try:
            role_binding(task, role=role, base_revision=base, correlation=correlation, agent=allowed[role])
            proof = execution_evidence(task, artifact, reservation, bucket="tasks", stage="dge:" + role,
                                       basis_revision=base, evidence_ref=evidence_ref_for(details), exact=True)
        except ContractError as exc:
            raise InvestigationRefused("recovery_evidence_mismatch", "predecessor.run_id") from exc
        reservation_ids.add(proof["reservation_id"])
        threads.append(proof["thread_id"])
        if failure is not None and role == failure["role"]:
            _refuse(task.get("id") == failure["task_id"] and ref == failure["execution_ref"],
                    "recovery_evidence_mismatch", "failure")
            failed = (details, artifact["answer"])
        elif failure is not None and role in COUNCIL_DEBATE:
            # An earlier debate role was derived and recorded: its bound output must still derive cleanly.
            _refuse(contract_failure(role, artifact["answer"], details) is None,
                    "recovery_failure_not_proven", "failure")
        bound.append({"task_id": task["id"], "role": role, "agent": task["agent"], "generation": task.get("generation"),
                      "attempt": task.get("attempt"), "execution_ref": ref, "reservation_id": proof["reservation_id"],
                      "output_sha256": proof["output_sha256"]})
    _refuse(sorted(b["role"] for b in bound) == sorted(roles), "recovery_evidence_mismatch", "predecessor.run_id")
    _refuse(all(r.get("status") == "settled" and r.get("id") in reservation_ids for r in reservations)
            and len(reservations) == len(bound), "recovery_invocation_unsettled", "predecessor.run_id")
    fenced = []
    for item in sorted(outbox, key=lambda i: str((i.get("message") or {}).get("message_id"))):
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        who = message.get("who") if isinstance(message.get("who"), dict) else {}
        details = (message.get("what") or {}).get("details") if isinstance(message.get("what"), dict) else {}
        _refuse(message.get("correlation_id") == correlation and who.get("sender") in parties
                and who.get("recipient") in parties
                and (message.get("type") != "task.assign" or (details or {}).get("role") in allowed),
                "recovery_effect_outside_read_only", "predecessor.run_id")
        message_id = message.get("message_id")
        delivery = deliveries.get(message_id)
        own = [a for a in attempts if a.get("outbox_id") == message_id]
        statuses = {a.get("status") for a in own}
        if item.get("sent") is True:
            continue    # delivered history: kept, never republished or deleted
        _refuse(item.get("sent") is False and type(message_id) is str and not (delivery or {}).get("delivered_entry_id")
                and "delivered" not in statuses and statuses <= UNSENT_ATTEMPTS
                and (delivery is None or delivery.get("status") == "retry"
                     or (delivery.get("status") == "quarantined" and delivery.get("source_hash") == digest(item))),
                "recovery_effect_unknown", "predecessor.run_id")
        fenced.append({"outbox": message_id, "source_hash": digest(item), "attempts": len(own)})
    new = request["replacement"]
    _refuse(isinstance(replacement, dict) and replacement.get("id") == new["program"]
            and replacement.get("config_sha256") == new["config_sha256"], "recovery_replacement_mismatch", "replacement")
    _refuse(replacement.get("state") == "paused" and replacement.get("cycles") == 0 and replacement.get("adoptions") == 0
            and replacement.get("active_cycle") is None and replacement.get("next_cycle") == 1,
            "recovery_replacement_not_fresh", "replacement")
    _refuse(same_authority and replacement.get("repository") == program.get("repository"),
            "recovery_scope_changed", "replacement")
    proof = {"fenced": fenced, "executions": bound,
             "calls": {"reserved": starts["reserved"], "settled": starts["settled"], "reservations": len(reservations)}}
    if failure is None:
        return proof
    # The recorded reason is never the proof: the failed role's OWN bound output, under the identities and
    # packet claims its immutable task carried (the ones the run froze), must raise exactly the pinned code.
    _refuse(failed is not None, "recovery_evidence_mismatch", "failure")
    details, answer = failed
    snapshot, report = run.get("snapshot"), run.get("report")
    frozen = {"snapshot_digest": snapshot.get("sha256") if isinstance(snapshot, dict) else None,
              "report_digest": report.get("sha256") if isinstance(report, dict) else None,
              "packet_digest": run.get("packet_digest")}
    _refuse(all(v is not None and details.get(k) == v for k, v in frozen.items()), "recovery_evidence_mismatch", "failure")
    _refuse(run.get("reason_code") in {failure["check"], LEGACY_CONTRACT_FAILURE}, "recovery_failure_not_proven", "failure")
    named = [t for t in threads if isinstance(t, str)]
    _refuse(len(named) == len(set(named)), "recovery_failure_not_proven", "failure")   # would have stopped earlier
    _refuse(contract_failure(failure["role"], answer, details) == failure["check"], "recovery_failure_not_proven", "failure")
    return {**proof, "failure": {**failure, "output_sha256": digest(answer)}}


def successor_held(investigation: str, head, chain: list, *, deliveries: dict, tasks: dict) -> str | None:
    """None while every successor authorization on the head's chain still holds; otherwise the named
    held condition. Each row must be the exact immutable authorization its key names, each version
    must follow its predecessor, every predecessor publication it fenced must still be quarantined with
    the same bytes, and every predecessor execution it bound must still be the same succeeded task."""
    if head is None:
        return None
    rows = {row.get("version"): row for row in chain if isinstance(row, dict)}
    current = lineage_head(investigation, None, head, rows.get(head.get("version") if isinstance(head, dict) else None))
    if current is None or current["state"] == "corrupt":
        return "recovery_successor_corrupt"
    for version in range(FIRST_SUCCESSOR, current["version"] + 1):
        row = rows.get(version)
        predecessor = (row.get("predecessor") or {}) if isinstance(row, dict) else {}
        # The previous version is `version - 1`, except that a version-4 successor or an accepted follow-up of
        # the INITIAL dispatch (lineage version 0) is the first row of its chain: version 1 belongs to the
        # original recovery only.
        previous = INITIAL_VERSION if (version == FIRST_SUCCESSOR and predecessor.get("lineage_version") == INITIAL_VERSION
                                       and row.get("proof") in INITIAL_PROOFS) else version - 1
        if not (isinstance(row, dict) and row.get("id") == successor_key(investigation, version)
                and row.get("investigation") == investigation and type(row.get("request_sha256")) is str
                and row.get("request_sha256") == digest(row.get("request"))
                and predecessor.get("lineage_version") == previous
                and predecessor.get("dispatch") == lineage_dispatch_id(investigation, previous)
                and row.get("state") in {AUTHORIZED, RECOVERED}
                and row.get("proof") == MODE_PROOF.get((row.get("request") or {}).get("mode"))):
            return "recovery_successor_corrupt"
        for fence in row.get("fence") or []:
            delivery = deliveries.get(fence.get("outbox"))
            if not (isinstance(delivery, dict) and delivery.get("status") == "quarantined"
                    and delivery.get("source_hash") == fence.get("source_hash")):
                return "recovery_publication_changed"
        for execution in (row.get("evidence") or {}).get("executions") or []:
            task = tasks.get(execution.get("task_id"))
            result = task.get("result") if isinstance(task, dict) and isinstance(task.get("result"), dict) else {}
            if not (isinstance(task, dict) and task.get("status") == "succeeded"
                    and result.get("execution_ref") == execution.get("execution_ref")
                    and (task.get("generation"), task.get("attempt")) == (execution.get("generation"), execution.get("attempt"))):
                return "recovery_successor_history_changed"
    return None


def successor_reads(chain: list) -> tuple[set, set]:
    """The outbox delivery ids and task ids `successor_held` must be given for `chain`."""
    deliveries, tasks = set(), set()
    for row in chain:
        if isinstance(row, dict):
            deliveries |= {f.get("outbox") for f in row.get("fence") or [] if type(f.get("outbox")) is str}
            tasks |= {e.get("task_id") for e in (row.get("evidence") or {}).get("executions") or []
                      if type(e.get("task_id")) is str}
    return deliveries, tasks


# ----- accepted investigation follow-up (SPEC "Accepted investigation follow-up for newly observed evidence") ----
# An ACCEPTED current dispatch of a report-only program (its template may write docs only) whose run is proven
# terminal and settled - every start, reservation and role task, the approved design, the accepted operation and
# the promotion receipt with its accepting independent review - may be followed up ONCE per exact head when the
# investigation's authoritative scoped membership (Portfolio jobs and bindings, read now) gained a member the
# accepted snapshot never captured. It is NOT a failure recovery: its own schema and mode, the same successor rows
# and versioned head, no fence (an accepted run has no unsent publication) and no reuse of the accepted council,
# its receipts or its calls. The owner pins the exact new membership; any drift before the claim refuses.
FOLLOWUP_SCHEMA = "urn:zeus:research-dispatch-followup:1"
FOLLOWUP_MODE = "accepted_evidence_followup"
FOLLOWUP_FIELDS = {"schema", "mode", "investigation", "predecessor", "members", "replacement"}
FOLLOWUP_MEMBER_FIELDS = {"previous_sha256", "job_ids", "sha256"}
FOLLOWUP_PROOF = "accepted_report_followup"
# The accepted run's starts: the five council roles, the implementation worker and its independent review.
ACCEPTED_STARTS = len(COUNCIL_ORDER) + 2
REPORT_ONLY_ROOT = "docs/"
ACTIVE_TASKS = {"queued", "running", "retry", "dispatching"}
FOLLOWUP_AUTHORITY = ("owner-authorized follow-up of one accepted report-only research dispatch for newly observed "
                      "authoritative member evidence; the accepted predecessor, its calls and its receipts stay "
                      "historical and are never reinterpreted as acceptance of the new snapshot")
MODE_PROOF = {SUCCESSOR_MODE: SUCCESSOR_PROOF, CONTRACT_MODE: CONTRACT_PROOF, FOLLOWUP_MODE: FOLLOWUP_PROOF}
INITIAL_PROOFS = {CONTRACT_PROOF, FOLLOWUP_PROOF}


def validate_followup_request(document) -> dict:
    """Strict owner follow-up request; returns the canonical copy. The predecessor pins the exact accepted
    current dispatch as in version 4 (lineage version 0 is the initial dispatch); `members` pins the digest of
    the accepted snapshot's captured ids and the exact intended new scoped ids with their digest."""
    def check(condition, field):
        if not condition:
            raise InvestigationRefused("followup_request_invalid", field)
    check(isinstance(document, dict) and document.get("schema") == FOLLOWUP_SCHEMA, "schema")
    check(set(document) == FOLLOWUP_FIELDS, "root")
    check(document["mode"] == FOLLOWUP_MODE, "mode")
    investigation = document["investigation"]
    check(type(investigation) is str and INVESTIGATION_ID.fullmatch(investigation) is not None, "investigation")
    old, members, new = document["predecessor"], document["members"], document["replacement"]
    check(isinstance(old, dict) and set(old) == SUCCESSOR_PREDECESSOR_FIELDS, "predecessor")
    version = old["lineage_version"]
    check(type(version) is int and 0 <= version < 1000, "predecessor.lineage_version")
    check(old["dispatch"] == lineage_dispatch_id(investigation, version), "predecessor.dispatch")
    check(old["lineage_request_sha256"] is None if version == INITIAL_VERSION
          else type(old["lineage_request_sha256"]) is str and SHA256.fullmatch(old["lineage_request_sha256"]) is not None,
          "predecessor.lineage_request_sha256")
    check(type(old["program"]) is str and PROGRAM_REF.fullmatch(old["program"]) is not None, "predecessor.program")
    check(type(old["cycle"]) is str and CYCLE_REF.fullmatch(old["cycle"]) is not None, "predecessor.cycle")
    check(type(old["run_id"]) is str and ID.fullmatch(old["run_id"]) is not None, "predecessor.run_id")
    for key in ("config_sha256", "manifest_sha256", "snapshot_sha256"):
        check(type(old[key]) is str and SHA256.fullmatch(old[key]) is not None, "predecessor." + key)
    check(isinstance(members, dict) and set(members) == FOLLOWUP_MEMBER_FIELDS, "members")
    ids = members["job_ids"]
    check(isinstance(ids, list) and 1 <= len(ids) <= MAX_JOB_SAMPLE
          and all(type(j) is str and INVESTIGATION_ID.fullmatch(j) is not None for j in ids)
          and len(set(ids)) == len(ids), "members.job_ids")
    for key in ("previous_sha256", "sha256"):
        check(type(members[key]) is str and SHA256.fullmatch(members[key]) is not None, "members." + key)
    check(members["sha256"] == digest(sorted(ids)), "members.sha256")
    check(isinstance(new, dict) and set(new) == RECOVERY_REPLACEMENT_FIELDS, "replacement")
    check(type(new["program"]) is str and PROGRAM_REF.fullmatch(new["program"]) is not None
          and new["program"] != old["program"], "replacement.program")
    check(type(new["config_sha256"]) is str and SHA256.fullmatch(new["config_sha256"]) is not None,
          "replacement.config_sha256")
    return {"schema": FOLLOWUP_SCHEMA, "mode": FOLLOWUP_MODE, "investigation": investigation,
            "predecessor": {k: old[k] for k in sorted(SUCCESSOR_PREDECESSOR_FIELDS)},
            "members": {"previous_sha256": members["previous_sha256"], "job_ids": sorted(ids),
                        "sha256": members["sha256"]},
            "replacement": {k: new[k] for k in sorted(RECOVERY_REPLACEMENT_FIELDS)}}


def report_only(config) -> bool:
    """The program's template may write docs only: every allowed path is a plain path under `docs/`."""
    plan = ((config or {}).get("template") or {}).get("plan") if isinstance(config, dict) else None
    paths = plan.get("allowed_paths") if isinstance(plan, dict) else None
    return (isinstance(paths, list) and bool(paths)
            and all(type(p) is str and p.startswith(REPORT_ONLY_ROOT) and "\\" not in p
                    and ".." not in p.split("/") for p in paths))


def followup_members(investigation, *, jobs: dict, bindings: dict, project_ids, required_state: str) -> list | None:
    """The investigation's authoritative scoped membership NOW (`scoped_job_ids` over fresh Portfolio jobs and
    bindings under the program's own project authority); None when the row is no longer this undecided
    failure family or is malformed."""
    if not (isinstance(investigation, dict) and investigation.get("kind", KIND) == KIND
            and investigation.get("state") == required_state):
        return None
    return scoped_job_ids(investigation, jobs, bindings, set(project_ids))


def check_followup(request: dict, *, investigation, required_state: str, minimum: int, lineage, dispatch, program,
                   cycle, run_result: dict, run, tasks: list, reservations: list, terminations: list, outbox: list,
                   acceptance: dict, jobs: dict, bindings: dict, replacement, same_authority: bool) -> dict:
    """Every precondition of one accepted follow-up against authoritative reads; the first gap refuses by name.

    `lineage` is `lineage_head` of the current authorization (None for the initial dispatch, lineage version 0).
    The pinned dispatch must be resolved `accepted` from its own run row; its program registered with the pinned
    config, report-only and idle; its cycle completed `accepted` for that run and manifest; its run row
    `accepted` with an approved design, an accepted operation, a promotion, exactly ACCEPTED_STARTS settled
    starts, every reservation settled, no termination, every task succeeded and bound to its recorded role, every
    publication sent; and its promotion receipt must be the accepted candidate of the accepting review
    (`domain.continuation.accepted_candidate`). The fresh scoped membership must equal the pinned ids and add a
    member the accepted, untruncated snapshot never captured. Returns the bound evidence; nothing is fenced."""
    old, members = request["predecessor"], request["members"]
    _refuse(isinstance(investigation, dict) and investigation.get("kind", KIND) == KIND
            and investigation.get("state") == required_state, "recovery_investigation_changed", "investigation")
    if old["lineage_version"] == INITIAL_VERSION:
        _refuse(lineage is None, "recovery_successor_stale", "predecessor")
    else:
        _refuse(isinstance(lineage, dict) and lineage.get("state") != "corrupt", "recovery_successor_corrupt", "predecessor")
        _refuse(lineage["version"] == old["lineage_version"] and lineage["request_sha256"] == old["lineage_request_sha256"]
                and lineage["dispatch"] == old["dispatch"], "recovery_successor_stale", "predecessor")
        _refuse(lineage["state"] == RECOVERED, "recovery_predecessor_active", "predecessor")
    _refuse(isinstance(dispatch, dict) and dispatch.get("id", dispatch.get("investigation")) == old["dispatch"]
            and dispatch.get("investigation") == request["investigation"] and dispatch.get("kind", KIND) == KIND
            and dispatch.get("program") == old["program"] and dispatch.get("cycle") == old["cycle"]
            and all(dispatch.get(k) == old[k] for k in ("run_id", "manifest_sha256", "snapshot_sha256")),
            "recovery_dispatch_mismatch", "predecessor")
    _refuse(dispatch.get("state") == RESOLVED, "recovery_predecessor_active", "predecessor")
    _refuse(dispatch.get("result") == "accepted", "followup_predecessor_not_accepted", "predecessor")
    _refuse(isinstance(program, dict) and program.get("id") == old["program"]
            and program.get("config_sha256") == old["config_sha256"], "recovery_dispatch_mismatch", "predecessor.program")
    _refuse(program.get("active_cycle") is None, "recovery_predecessor_active", "predecessor.program")
    _refuse(report_only(program.get("config")), "followup_not_report_only", "predecessor.program")
    council = (cycle or {}).get("council") if isinstance(cycle, dict) else None
    _refuse(isinstance(council, dict) and cycle.get("program") == old["program"] and cycle.get("result") == "accepted"
            and cycle.get("status") == "completed" and council.get("run_id") == old["run_id"]
            and council.get("manifest_sha256") == old["manifest_sha256"] and council.get("status") == "accepted",
            "recovery_cycle_mismatch", "predecessor.cycle")
    _refuse(run_result.get("result") == "accepted" and isinstance(run, dict) and run.get("status") == "accepted"
            and bool(run.get("finished_at")), "followup_predecessor_not_accepted", "predecessor.run_id")
    design, operation = run.get("design"), run.get("operation")
    _refuse(isinstance(design, dict) and design.get("state") == "design_approved"
            and isinstance(operation, dict) and operation.get("status") == "accepted"
            and isinstance(run.get("promotion"), dict), "followup_acceptance_unproven", "predecessor.run_id")
    starts = run.get("starts") if isinstance(run.get("starts"), dict) else {}
    slots = starts.get("slots") if isinstance(starts.get("slots"), list) else None
    _refuse(slots is not None and all(isinstance(s, dict) for s in slots)
            and starts.get("reserved") == starts.get("settled") == len(slots) == ACCEPTED_STARTS
            and all(s.get("settled") is True and s.get("settle_error") is None for s in slots),
            "recovery_invocation_unsettled", "predecessor.run_id")
    _refuse(not terminations, "recovery_effect_unknown", "predecessor.run_id")
    _refuse(all(r.get("status") == "settled" for r in reservations), "recovery_invocation_unsettled", "predecessor.run_id")
    roles = run.get("roles") if isinstance(run.get("roles"), dict) else {}
    _refuse(bool(roles) and set(roles) <= set(COUNCIL_ORDER), "followup_acceptance_unproven", "predecessor.run_id")
    by_id, bound = {t.get("id"): t for t in tasks if isinstance(t, dict)}, []
    for task in sorted(by_id.values(), key=lambda t: str(t.get("id"))):
        _refuse(task.get("status") not in ACTIVE_TASKS, "recovery_predecessor_active", "predecessor.run_id")
        _refuse(task.get("status") == "succeeded", "recovery_effect_unknown", "predecessor.run_id")
    for role in sorted(roles):
        recorded = roles[role] if isinstance(roles[role], dict) else {}
        task = by_id.get(recorded.get("task_id"))
        result = task.get("result") if isinstance(task, dict) and isinstance(task.get("result"), dict) else {}
        _refuse(isinstance(task, dict) and type(recorded.get("execution_ref")) is str
                and result.get("execution_ref") == recorded["execution_ref"], "recovery_evidence_mismatch",
                "predecessor.run_id")
        bound.append({"task_id": task["id"], "role": role, "agent": task.get("agent"), "generation": task.get("generation"),
                      "attempt": task.get("attempt"), "execution_ref": recorded["execution_ref"]})
    _refuse(all(isinstance(i, dict) and i.get("sent") is True for i in outbox), "recovery_effect_unknown", "predecessor.run_id")
    promotion, task = acceptance.get("promotion"), acceptance.get("task")
    proof = promotion.get("evidence") if isinstance(promotion, dict) and isinstance(promotion.get("evidence"), dict) else {}
    candidate = ((task.get("result") or {}).get("candidate") or {}) if isinstance(task, dict) and isinstance(task.get("result"), dict) else {}
    binding = {"graph_sha256": run["promotion"].get("graph_sha256"), "decision_id": proof.get("decision_id"),
               "candidate_revision": candidate.get("revision")}
    _refuse(all(type(v) is str and v for v in binding.values())
            and operation.get("task_id") == proof.get("implementation_task_id")
            and operation.get("decision_id") == proof.get("decision_id")
            and accepted_candidate(binding, old["run_id"], {**acceptance, "run": run}),
            "followup_acceptance_unproven", "predecessor.run_id")
    captured = dispatch.get("job_ids") if isinstance(dispatch.get("job_ids"), list) else None
    _refuse(dispatch.get("job_ids_sha256") == members["previous_sha256"], "recovery_dispatch_mismatch",
            "members.previous_sha256")
    _refuse(captured is not None and dispatch.get("job_ids_total") == len(captured)
            and digest(sorted(captured)) == members["previous_sha256"], "followup_membership_unverifiable",
            "members.previous_sha256")
    source = (program.get("config") or {}).get("investigation_source") or {}
    fresh = followup_members(investigation, jobs=jobs, bindings=bindings, project_ids=source.get("project_ids") or [],
                             required_state=required_state)
    _refuse(fresh is not None, "followup_membership_unverifiable", "members.job_ids")
    _refuse(fresh == members["job_ids"], "followup_membership_mismatch", "members.job_ids")
    _refuse(len(fresh) >= minimum, "followup_membership_mismatch", "members.job_ids")
    _refuse(not set(fresh) <= set(captured), "followup_membership_unchanged", "members.job_ids")
    new = request["replacement"]
    _refuse(isinstance(replacement, dict) and replacement.get("id") == new["program"]
            and replacement.get("config_sha256") == new["config_sha256"], "recovery_replacement_mismatch", "replacement")
    _refuse(replacement.get("state") == "paused" and replacement.get("cycles") == 0 and replacement.get("adoptions") == 0
            and replacement.get("active_cycle") is None and replacement.get("next_cycle") == 1,
            "recovery_replacement_not_fresh", "replacement")
    _refuse(same_authority and replacement.get("repository") == program.get("repository"),
            "recovery_scope_changed", "replacement")
    return {"fenced": [], "executions": bound,
            "calls": {"reserved": starts["reserved"], "settled": starts["settled"], "reservations": len(reservations)},
            "acceptance": binding,
            "members": {"previous_sha256": members["previous_sha256"], "previous_total": len(captured),
                        "job_ids": list(fresh), "sha256": members["sha256"],
                        "added": sorted(set(fresh) - set(captured))}}


def followup_drift(row, *, investigation, jobs: dict, bindings: dict, project_ids, required_state: str) -> str | None:
    """None while an authorized follow-up's pinned membership is still exactly the authoritative scoped
    membership; otherwise `followup_membership_drift`. Never recaptured silently: the owner re-requests."""
    members = (row or {}).get("members") if isinstance(row, dict) else None
    fresh = followup_members(investigation, jobs=jobs, bindings=bindings, project_ids=project_ids,
                             required_state=required_state)
    if not (isinstance(members, dict) and fresh is not None and fresh == members.get("job_ids")
            and digest(fresh) == members.get("sha256")):
        return "followup_membership_drift"
    return None


def successor_view(row: dict) -> dict:
    """Bounded read-only projection of one successor authorization: identities, digests, fixed codes and
    counts only."""
    keys = ("id", "investigation", "version", "state", "predecessor", "replacement", "fence", "proof", "evidence",
            "request_sha256", "requested_at", "authorized_at", "claimed_at", "updated_at")
    mode = (row.get("request") or {}).get("mode")
    # `failure` is additive: a version-3 row reads None; a version-4 row names its re-derived field code.
    if mode == CONTRACT_MODE:
        return {**{k: row.get(k) for k in keys}, "mode": CONTRACT_MODE, "failure": row.get("failure"),
                "authority": CONTRACT_AUTHORITY}
    # `members` is additive on a follow-up: the pinned new scoped membership and the captured digest it extends.
    if mode == FOLLOWUP_MODE:
        return {**{k: row.get(k) for k in keys}, "mode": FOLLOWUP_MODE, "failure": None, "members": row.get("members"),
                "authority": FOLLOWUP_AUTHORITY}
    return {**{k: row.get(k) for k in keys}, "mode": SUCCESSOR_MODE, "failure": None, "authority": SUCCESSOR_AUTHORITY}


def recovery_view(row: dict) -> dict:
    """Bounded read-only projection of one lineage row: identities, state and fixed codes only.
    `mode` and `revocation` are additive: a transport-proof row reads `transport_proof`, None."""
    keys = ("investigation", "state", "reason_code", "failed", "replacement", "fence", "proof", "request_sha256",
            "requested_at", "authorized_at", "claimed_at", "updated_at")
    mode = (row.get("request") or {}).get("mode") or "transport_proof"
    return {**{k: row.get(k) for k in keys}, "mode": mode, "revocation": row.get("revocation"),
            "authority": RECOVERY_AUTHORITY}


def dispatch_counts(rows: list) -> dict:
    """Dispatch is counted separately from acceptance: claimed and dispatched are work in flight."""
    counts = {"total": len(rows), "claimed": 0, "dispatched": 0, "accepted": 0, "rejected": 0, "failed": 0, "unknown": 0}
    for row in rows:
        result = row.get("result")
        if result in counts:
            counts[result] += 1
        elif row.get("state") == DISPATCHED:
            counts["dispatched"] += 1
        else:
            counts["claimed"] += 1
    return counts


__all__ = ["AUTHORITY", "AUTHORIZED", "CLAIMED", "CONTRACT_MODE", "CONTRACT_PROOF", "CONTRACT_SCHEMA",
           "DISPATCHED", "DISPATCH_SCHEMA", "EXCLUSIONS", "FENCED", "INITIAL_VERSION", "contract_failure",
           "FOLLOWUP_MODE", "FOLLOWUP_PROOF", "FOLLOWUP_SCHEMA", "check_followup", "followup_drift",
           "followup_members", "report_only", "validate_followup_request",
           "lineage_dispatch_id", "successor_version", "validate_any_successor", "validate_contract_request",
           "FENCE_REASON", "KIND", "MAX_JOB_SAMPLE", "MAX_PROJECTS", "MAX_REASON_CODES", "PRE_PROVIDER_FAILURE",
           "RECOVERED", "RECOVERY_SCHEMA", "REFUSED", "RESOLVED", "REVOCATION_BUCKET", "REVOCATION_GENERATION",
           "REVOCATION_MODE", "REVOCATION_PROOF", "REVOCATION_SCHEMA", "SNAPSHOT_SCHEMA", "SOURCE", "SUCCESSOR_MODE",
           "SUCCESSOR_PROOF", "SUCCESSOR_SCHEMA", "TRUST",
           "InvestigationRefused", "attempted_transport", "candidate_identity", "candidate_key", "check_recovery",
           "check_successor", "check_transport_proof", "current_dispatch_id",
           "dispatch_counts", "dispatch_row", "dispatch_view", "eligible_investigations", "lineage_head", "recovery_view",
           "replacement_dispatch_id", "revocation_evidence", "revocation_held", "revocation_owner",
           "revocation_task_id", "scope_reference", "scoped_job_ids", "snapshot", "successor_dispatch_id",
           "successor_held", "successor_key", "successor_reads", "successor_view", "validate_recovery_request",
           "validate_source", "validate_successor_request"]
