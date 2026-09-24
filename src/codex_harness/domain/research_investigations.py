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
from codex_harness.domain.council import COUNCIL_AGENTS, DBA
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


def successor_key(investigation: str, version: int) -> str:
    return investigation + ":" + str(version)


def successor_dispatch_id(investigation: str, version: int) -> str:
    """Version 1 is the original recovery's replacement (`replacement_dispatch_id`)."""
    return investigation + ".recovery-" + str(version)


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
    document or to a fixed unavailability code. Returns the fence targets and the bound evidence."""
    old = request["predecessor"]
    _refuse(isinstance(investigation, dict) and investigation.get("kind", KIND) == KIND
            and investigation.get("state") == required_state,
            "recovery_investigation_changed", "investigation")
    _refuse(isinstance(lineage, dict) and lineage.get("state") != "corrupt", "recovery_successor_corrupt", "predecessor")
    _refuse(lineage["version"] == old["lineage_version"] and lineage["request_sha256"] == old["lineage_request_sha256"]
            and lineage["dispatch"] == old["dispatch"], "recovery_successor_stale", "predecessor")
    _refuse(lineage["state"] == RECOVERED, "recovery_predecessor_active", "predecessor")
    _refuse(isinstance(dispatch, dict) and dispatch.get("id") == old["dispatch"]
            and dispatch.get("investigation") == request["investigation"] and dispatch.get("kind", KIND) == KIND
            and dispatch.get("program") == old["program"] and dispatch.get("cycle") == old["cycle"]
            and all(dispatch.get(k) == old[k] for k in ("run_id", "manifest_sha256", "snapshot_sha256")),
            "recovery_dispatch_mismatch", "predecessor")
    _refuse(dispatch.get("state") == RESOLVED, "recovery_predecessor_active", "predecessor")
    _refuse(dispatch.get("result") not in {"accepted", "rejected"}, "recovery_dispatch_not_failed", "predecessor")
    _refuse(dispatch.get("result") == "failed", "recovery_effect_unknown", "predecessor")
    _refuse(dispatch.get("result_reason") == READ_ONLY_FAILURE, "recovery_not_settled_read_only", "predecessor")
    _refuse(isinstance(program, dict) and program.get("id") == old["program"]
            and program.get("config_sha256") == old["config_sha256"], "recovery_dispatch_mismatch", "predecessor.program")
    _refuse(program.get("state") == "blocked" and program.get("active_cycle") is None,
            "recovery_program_not_blocked", "predecessor.program")
    council = (cycle or {}).get("council") if isinstance(cycle, dict) else None
    _refuse(isinstance(council, dict) and cycle.get("program") == old["program"] and cycle.get("result") == "failed"
            and cycle.get("status") == "completed" and council.get("run_id") == old["run_id"]
            and council.get("manifest_sha256") == old["manifest_sha256"] and council.get("status") == "failed",
            "recovery_cycle_mismatch", "predecessor.cycle")
    _refuse(run_result.get("result") == "failed" and run_result.get("reason_code") == READ_ONLY_FAILURE
            and isinstance(run, dict) and run.get("status") == "failed" and bool(run.get("finished_at")),
            "recovery_run_not_settled_read_only", "predecessor.run_id")
    _refuse(run.get("stage") in READ_ONLY_STAGES and run.get("operation") is None and run.get("promotion") is None
            and run.get("design") is None and not residue, "recovery_effect_outside_read_only", "predecessor.run_id")
    roles = run.get("roles") if isinstance(run.get("roles"), dict) else {}
    _refuse(bool(roles) and set(roles) <= set(READ_ONLY_ROLES), "recovery_effect_outside_read_only", "predecessor.run_id")
    _refuse(session is None or (isinstance(session, dict) and session.get("version") == 0
                                and session.get("decision_event_id") is None and not session.get("findings")),
            "recovery_effect_outside_read_only", "predecessor.run_id")
    starts = run.get("starts") if isinstance(run.get("starts"), dict) else {}
    slots = starts.get("slots") if isinstance(starts.get("slots"), list) else None
    _refuse(slots is not None and all(isinstance(s, dict) for s in slots), "recovery_invocation_unsettled", "predecessor.run_id")
    _refuse(all(s.get("kind") == "task" and s.get("agent") in READ_ONLY_ROLES.values() and s.get("operation") is None
                for s in slots), "recovery_effect_outside_read_only", "predecessor.run_id")
    _refuse(starts.get("reserved") == starts.get("settled") == len(slots) == len(roles)
            and all(s.get("settled") is True and s.get("settle_error") is None for s in slots),
            "recovery_invocation_unsettled", "predecessor.run_id")
    _refuse(not terminations, "recovery_effect_unknown", "predecessor.run_id")
    _refuse(all(r.get("status") == "settled" for r in reservations), "recovery_invocation_unsettled", "predecessor.run_id")
    correlation = correlation_id({"id": old["run_id"]})
    bound, reservation_ids = [], set()
    for task in sorted(tasks, key=lambda t: str(t.get("id"))):
        message = task.get("message") if isinstance(task.get("message"), dict) else {}
        details = (message.get("what") or {}).get("details") if isinstance(message.get("what"), dict) else None
        role = details.get("role") if isinstance(details, dict) else None
        _refuse(role in READ_ONLY_ROLES and task.get("agent") == READ_ONLY_ROLES[role]
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
            role_binding(task, role=role, base_revision=base, correlation=correlation, agent=READ_ONLY_ROLES[role])
            proof = execution_evidence(task, artifact, reservation, bucket="tasks", stage="dge:" + role,
                                       basis_revision=base, evidence_ref=evidence_ref_for(details), exact=True)
        except ContractError as exc:
            raise InvestigationRefused("recovery_evidence_mismatch", "predecessor.run_id") from exc
        reservation_ids.add(proof["reservation_id"])
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
        _refuse(message.get("correlation_id") == correlation and who.get("sender") in READ_ONLY_PARTIES
                and who.get("recipient") in READ_ONLY_PARTIES
                and (message.get("type") != "task.assign" or (details or {}).get("role") in READ_ONLY_ROLES),
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
    return {"fenced": fenced, "executions": bound,
            "calls": {"reserved": starts["reserved"], "settled": starts["settled"], "reservations": len(reservations)}}


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
    for version in range(2, current["version"] + 1):
        row = rows.get(version)
        if not (isinstance(row, dict) and row.get("id") == successor_key(investigation, version)
                and row.get("investigation") == investigation and type(row.get("request_sha256")) is str
                and row.get("request_sha256") == digest(row.get("request"))
                and (row.get("predecessor") or {}).get("lineage_version") == version - 1
                and (row.get("predecessor") or {}).get("dispatch") == successor_dispatch_id(investigation, version - 1)
                and row.get("state") in {AUTHORIZED, RECOVERED} and row.get("proof") == SUCCESSOR_PROOF):
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


def successor_view(row: dict) -> dict:
    """Bounded read-only projection of one successor authorization: identities, digests, fixed codes and
    counts only."""
    keys = ("id", "investigation", "version", "state", "predecessor", "replacement", "fence", "proof", "evidence",
            "request_sha256", "requested_at", "authorized_at", "claimed_at", "updated_at")
    return {**{k: row.get(k) for k in keys}, "mode": SUCCESSOR_MODE, "authority": SUCCESSOR_AUTHORITY}


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


__all__ = ["AUTHORITY", "AUTHORIZED", "CLAIMED", "DISPATCHED", "DISPATCH_SCHEMA", "EXCLUSIONS", "FENCED",
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
