"""Autonomous research -> debate -> implementation -> promotion: manifest, role outputs, provenance
and the promoted graph shape (INV-AUTONOMOUS-001).

The manifest (`urn:zeus:autonomous:1`) is the operation manifest plus an aware absolute deadline and a
research brief (topic, questions, search scope). The operator supplies goal, criteria and allowed
paths, never role answers. Role outputs are turned into the existing research packet and debate
events by adding deterministic envelope fields only; a missing or malformed role conclusion is
refused, never repaired. Provenance binds each role answer to the persisted task execution that
produced it. Nothing here calls a model, verifies a citation's truth or writes a store.
"""
from __future__ import annotations

from uuid import UUID, uuid5

from codex_harness.domain.dge import PacketError, parse_deadline, validate_packet
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.operation import (
    ID,
    SCHEMA,
    SCHEMA_V2,
    safe_relative_path,
    validate_manifest,
)

SCHEMA_AUTONOMOUS = "urn:zeus:autonomous:1"
RECEIPT_SCHEMA = "urn:zeus:autonomous-receipt:1"
FIELDS = {"schema", "id", "base_revision", "goal", "plan", "budget", "claude", "deadline", "research"}
RESEARCH_FIELDS = {"topic", "questions", "search_scope"}
ROLE_ACTION = "dge_role"
RESEARCHER, PROPOSER, ATTACKER, ARBITER = "researcher", "proposer", "attacker", "arbiter"
ROLE_ORDER = (RESEARCHER, PROPOSER, ATTACKER, ARBITER)
DEBATE_ROLES = (PROPOSER, ATTACKER, ARBITER)
ROLE_AGENTS = {role: "lead:" + role for role in ROLE_ORDER}
CONDUCTOR = "conductor"
MAX_STARTS = 6           # research + three debate roles + implement + review
MAX_ROLE_ENTRIES = 1     # provider entries per role execution; no implicit context handoff retry
FIXED_ROUNDS = 1
ORIGIN_EXECUTOR = "executor_bound"
PROMOTED_NAMESPACE = "verified:"
SSOT_DECISIONS = {"reuse", "improve", "migrate", "new"}
SSOT_FIELDS = {"searched_paths", "searched_symbols", "authoritative_definition", "callers", "evidence",
               "unknowns", "decision", "rationale", "transition"}
RESEARCH_OUTPUT_FIELDS = {"sources", "claims", "questions", "ssot", "needs_user", "user_question"}
TRUST = ("executor-bound role outputs: the persisted task execution, its agent, stage, generation, attempt,"
         " base revision and output digest are checked; citation truth and design correctness are not")
NAMESPACE = UUID("2c0b4f0e-8a5d-4f6c-9c1b-6d2e3f4a5b6c")
TERMINAL = {"accepted", "rejected", "failed", "unknown", "exhausted", "needs_user", "needs_research", "expired"}
STAGES = ("research", "packet", "proposer", "attacker", "arbiter", "implementation", "promotion")


class AutonomousManifestError(ContractError):
    """Refused before any Git, PostgreSQL or provider access; the message names a field, never a value."""


def _text(value, limit=4000) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def validate_autonomous_manifest(document, policy) -> dict:
    """The operation fields are validated by the operation validator (one copy of those rules); the
    deadline by the packet deadline parser; the research brief here. Returns a canonical copy."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_AUTONOMOUS:
        raise AutonomousManifestError("Autonomous manifest schema is not " + SCHEMA_AUTONOMOUS)
    unknown, missing = sorted(set(document) - FIELDS), sorted(FIELDS - set(document))
    if unknown or missing:
        raise AutonomousManifestError("Autonomous manifest has unknown or missing fields: "
                                      + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))
    try:
        operation = validate_manifest({**{k: document[k] for k in FIELDS - {"deadline", "research", "schema"}},
                                       "schema": SCHEMA}, policy)
    except ContractError as exc:
        raise AutonomousManifestError(str(exc)) from exc
    try:
        deadline = parse_deadline(document["deadline"], AutonomousManifestError)
    except ContractError as exc:
        raise AutonomousManifestError("Autonomous manifest deadline must be an aware ISO 8601 timestamp") from exc
    research = document["research"]
    if not isinstance(research, dict) or set(research) != RESEARCH_FIELDS:
        raise AutonomousManifestError("Autonomous manifest research needs topic, questions and search_scope")
    questions, scope = research["questions"], research["search_scope"]
    if not (_text(research["topic"], 400) and isinstance(questions, list) and questions
            and all(_text(q) for q in questions) and len(set(questions)) == len(questions)):
        raise AutonomousManifestError("Autonomous manifest research.topic and distinct questions are required")
    if not (isinstance(scope, list) and scope and all(safe_relative_path(p) for p in scope) and len(set(scope)) == len(scope)):
        raise AutonomousManifestError("Autonomous manifest research.search_scope must be distinct safe relative paths")
    return {**{k: operation[k] for k in ("id", "base_revision", "goal", "plan", "budget", "claude")},
            "schema": SCHEMA_AUTONOMOUS, "deadline": deadline,
            "research": {"topic": research["topic"], "questions": list(questions), "search_scope": list(scope)}}


def manifest_digest(manifest) -> str:
    return digest(manifest)


def correlation_id(manifest) -> str:
    return "autonomous:" + manifest["id"]


def session_id(manifest) -> str:
    return manifest["id"] + ".design"


def operation_manifest(manifest, packet_digest_value: str) -> dict:
    """The exact v2 operation manifest the approved design authorizes; the plan is byte-identical."""
    return {"schema": SCHEMA_V2, "id": manifest["id"] + ".impl", "base_revision": manifest["base_revision"],
            "goal": dict(manifest["goal"]), "plan": {k: manifest["plan"][k] for k in ("objective", "acceptance_criteria", "allowed_paths")},
            "budget": dict(manifest["budget"]), "claude": dict(manifest["claude"]),
            "design": {"session_id": session_id(manifest), "packet_digest": packet_digest_value}}


def role_message_id(manifest, role: str, round_number: int = FIXED_ROUNDS) -> str:
    """Deterministic six-W identity per run, role and round: a restart never dispatches twice."""
    return str(uuid5(NAMESPACE, ":".join((manifest_digest(manifest), role, str(round_number)))))


# ----- role outputs -> existing packet / events --------------------------------------------------
def packet_from_research(manifest, output) -> dict:
    """Freeze the researcher output as a `urn:zeus:research-packet:1` packet. The host adds only
    deterministic envelope fields (schema, id, base, topic, objective, exclusions, plan, limits); the
    sources, claims, questions and SSOT findings come from the role output and are validated by the
    existing packet validator, never authored or repaired here."""
    if not isinstance(output, dict) or set(output) != RESEARCH_OUTPUT_FIELDS:
        raise PacketError("Researcher output lacks the required fields")
    ssot = validate_ssot(output["ssot"])
    if type(output["needs_user"]) is not bool:
        raise PacketError("Researcher needs_user must be a boolean")
    if output["needs_user"] and not _text(output["user_question"]):
        raise PacketError("Researcher needs_user requires a concrete user_question")
    packet = validate_packet({"schema": "urn:zeus:research-packet:1", "id": session_id(manifest),
                              "base_revision": manifest["base_revision"], "topic": manifest["research"]["topic"],
                              "objective": manifest["plan"]["objective"],
                              "exclusions": ["no automatic merge, release, ticket closure or rework",
                                             "SSOT decision: " + ssot["decision"]],
                              "plan": manifest["plan"], "questions": output["questions"], "sources": output["sources"],
                              "claims": output["claims"], "limits": {"max_rounds": FIXED_ROUNDS, "deadline": manifest["deadline"]},
                              "supersedes": None, "research_reason": None})
    return {"packet": packet, "ssot": ssot, "needs_user": output["needs_user"],
            "user_question": output["user_question"] if output["needs_user"] else None}


def validate_ssot(value) -> dict:
    """SSOT-first findings: an unfound symbol is recorded as unknown, never as absence."""
    if not isinstance(value, dict) or set(value) != SSOT_FIELDS:
        raise PacketError("Researcher ssot findings lack the required fields")
    lists = ("searched_paths", "searched_symbols", "callers", "evidence", "unknowns")
    if not all(isinstance(value[k], list) and all(_text(v, 1024) for v in value[k]) for k in lists):
        raise PacketError("Researcher ssot lists must hold text")
    if not value["searched_paths"]:
        raise PacketError("Researcher ssot must name the searched paths")
    if value["decision"] not in SSOT_DECISIONS or not _text(value["rationale"]):
        raise PacketError("Researcher ssot decision must be reuse, improve, migrate or new with a rationale")
    definition = value["authoritative_definition"]
    if definition is not None and not _text(definition, 1024):
        raise PacketError("Researcher ssot authoritative_definition must be null or text")
    if definition is None and value["decision"] != "new":
        raise PacketError("Researcher ssot reuse, improve or migrate requires an authoritative definition")
    transition = value["transition"]
    if value["decision"] in {"improve", "migrate"}:
        # An existing implementation is changed only with compatibility, rollback and retirement thought through.
        if not (isinstance(transition, dict) and set(transition) == {"compatibility", "rollback", "retirement"}
                and all(_text(transition[k]) for k in transition)):
            raise PacketError("Researcher ssot improve or migrate requires compatibility, rollback and retirement")
    elif transition is not None:
        raise PacketError("Researcher ssot transition must be null unless the decision is improve or migrate")
    return {k: value[k] for k in sorted(SSOT_FIELDS)}


def event_from_role(role: str, output, packet_digest_value: str, version: int, task_id: str,
                    round_number: int = FIXED_ROUNDS) -> dict:
    """Wrap a debate role output as a `urn:zeus:debate-event:1`; the payload is the output itself and
    is validated by the existing per-role validator on submit."""
    if role not in DEBATE_ROLES:
        raise ContractError("Unknown debate role")
    if not isinstance(output, dict):
        raise ContractError("Debate role output must be an object")
    if role == ATTACKER:
        output = attacker_findings(output)
    return {"schema": "urn:zeus:debate-event:1", "id": role + "-" + _event_token(task_id), "expected_version": version,
            "packet_digest": packet_digest_value, "round": round_number, "role": role, "payload": output}


def _event_token(task_id: str) -> str:
    token = "".join(c for c in str(task_id) if c.isalnum() or c in "._-")[:80]
    if not token or ID.fullmatch("x-" + token) is None:
        raise ContractError("Debate event id cannot be derived from the task id")
    return token


def attacker_findings(output) -> dict:
    """Critical-only blocker rule: a critical finding must carry a concrete trigger, impact and
    mitigation next to the packet citation; anything else is a minor backlog item. The materiality
    fields are host-required, the existing event validator checks the rest."""
    if set(output) != {"findings"} or not isinstance(output["findings"], list):
        raise ContractError("Attacker output must be a findings list")
    findings = []
    for finding in output["findings"]:
        if not isinstance(finding, dict) or not {"id", "criterion", "severity", "scenario", "claim_ids"} <= set(finding):
            raise ContractError("Attacker finding lacks the required fields")
        extra = {k: finding.get(k) for k in ("trigger", "impact", "mitigation")}
        if finding["severity"] == "critical" and not all(_text(v) for v in extra.values()):
            raise ContractError("Attacker critical finding needs a concrete trigger, impact and mitigation")
        scenario = finding["scenario"]
        if finding["severity"] == "critical":
            scenario = "\n".join((str(scenario), "trigger: " + extra["trigger"], "impact: " + extra["impact"],
                                  "mitigation: " + extra["mitigation"]))
        findings.append({"id": finding["id"], "criterion": finding["criterion"], "severity": finding["severity"],
                         "scenario": scenario, "claim_ids": finding["claim_ids"]})
    return {"findings": findings}


# ----- provenance ---------------------------------------------------------------------------------
def role_binding(task: dict, *, role: str, base_revision: str, correlation: str) -> dict:
    """Bind the answer to the persisted execution row itself, or refuse with a fixed reason. Operator
    submitted sessions, another agent, another correlation, another base or a non-succeeded row never
    bind. Provenance is proof of which execution produced the bytes, not of what they claim."""
    if not isinstance(task, dict):
        raise ContractError("role_task_missing")
    result = task.get("result")
    message = task.get("message") if isinstance(task.get("message"), dict) else {}
    if task.get("status") != "succeeded" or not isinstance(result, dict):
        raise ContractError("role_task_not_succeeded")
    if task.get("agent") != ROLE_AGENTS[role] or message.get("correlation_id") != correlation:
        raise ContractError("role_task_unbound")
    if (message.get("what") or {}).get("action") != ROLE_ACTION or ((message.get("what") or {}).get("details") or {}).get("role") != role:
        raise ContractError("role_task_unbound")
    if result.get("basis_revision") != base_revision or not isinstance(result.get("execution_ref"), str):
        raise ContractError("role_task_base_mismatch")
    if type(task.get("generation")) is not int or type(task.get("attempt")) is not int:
        raise ContractError("role_task_unbound")
    answer = {k: v for k, v in result.items() if k not in HOST_RESULT_FIELDS}
    return {"origin": ORIGIN_EXECUTOR, "task_id": task["id"], "generation": task["generation"], "attempt": task["attempt"],
            "agent": task["agent"], "stage": "dge:" + role, "base_revision": base_revision,
            "execution_ref": result["execution_ref"], "output_sha256": digest(answer), "answer": answer}


HOST_RESULT_FIELDS = {"execution_ref", "basis_revision", "role_execution", "candidate", "origin", "evidence_inspection",
                      "release_id", "shortlist_execution_ref"}
ACCEPTED_INVOCATION = "accepted"


def execution_evidence(record: dict, artifact, reservation, *, bucket: str, stage: str | None, basis_revision: str | None,
                       evidence_ref: str | None = None, exact: bool = False) -> dict:
    """The persisted execution artifact (what the executor stored under `execution_ref`) must be the
    execution that produced the stored answer: its `answer` is the record's result (exactly, for role
    outputs), its invocation names an authoritative settled `accepted` reservation of this record's
    bucket, id, generation, attempt and stage, and its context binding names the base revision and the
    exact input evidence. A row, an accepted flag or a matching revision alone never proves this. Raised
    codes are fixed; nothing here reads files or a store."""
    if not isinstance(artifact, dict) or not isinstance(artifact.get("answer"), dict):
        raise ContractError("evidence_artifact_invalid")
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    answer = artifact["answer"]
    stored = {k: v for k, v in result.items() if k not in HOST_RESULT_FIELDS} if exact else {k: result.get(k) for k in answer}
    if stored != answer:
        raise ContractError("evidence_answer_mismatch")
    invocation = artifact.get("invocation") if isinstance(artifact.get("invocation"), dict) else {}
    reservation_id = invocation.get("reservation")
    if not (isinstance(reservation_id, str) and isinstance(reservation, dict) and reservation.get("id") == reservation_id):
        raise ContractError("evidence_reservation_unbound")
    identity = (reservation.get("bucket"), reservation.get("task_id"), reservation.get("generation"), reservation.get("attempt"))
    if identity != (bucket, record.get("id"), record.get("generation"), record.get("attempt")) or reservation.get("stage") != stage:
        raise ContractError("evidence_reservation_unbound")
    if reservation.get("status") != "settled" or reservation.get("outcome") != ACCEPTED_INVOCATION \
            or invocation.get("outcome") != ACCEPTED_INVOCATION:
        raise ContractError("evidence_reservation_unsettled")
    binding = artifact.get("research_binding")
    if stage is not None or binding is not None:
        if not (isinstance(binding, dict) and binding.get("stage") == stage and binding.get("basis_revision") == basis_revision
                and (evidence_ref is None or binding.get("evidence_ref") == evidence_ref)):
            raise ContractError("evidence_basis_mismatch")
    assignment = artifact.get("execution_assignment") if isinstance(artifact.get("execution_assignment"), dict) else {}
    thread = artifact.get("thread_id")
    return {"reservation_id": reservation_id, "invocation": reservation.get("invocation"),
            "thread_id": thread if isinstance(thread, str) else None,
            "provider": assignment.get("provider") if isinstance(assignment.get("provider"), str) else None,
            "output_sha256": digest(answer)}


def evidence_ref_for(details) -> str:
    """The content address the executor gives the input evidence it compiled the context from."""
    return "sha256:" + digest(details)


def independent_roles(bindings: dict) -> None:
    """Fresh sessions per role: two roles sharing one provider thread means one resumed the other."""
    threads = [b.get("evidence", {}).get("thread_id") for b in bindings.values()]
    threads = [t for t in threads if isinstance(t, str)]
    if len(threads) != len(set(threads)):
        raise ContractError("role_session_shared")


# ----- promoted graph -----------------------------------------------------------------------------
def verified_graph(run_id: str, refs: dict) -> dict:
    """Bounded typed graph in `verified:<run>`: goal, research, design, candidate and verification
    nodes joined by derived_from / implements / verified_by. Bodies are immutable references and
    digests, never prose; the namespace names verified execution and review provenance only."""
    repository = PROMOTED_NAMESPACE + run_id
    scope = {"authority": "verified_execution_review_provenance", "not": ["truth of prose", "merged or deployed code",
             "product acceptance"], "verification_scope": refs["verification_scope"]}

    def node(kind, body):
        return {"id": repository + ":" + kind, "repository": repository, "kind": kind, "body": body,
                "source_ref": body.get("ref") or body.get("execution_ref") or "postgres:autonomous_runs/" + run_id,
                "revision": body.get("sha256") or body.get("revision") or digest(body), "properties": dict(scope)}
    nodes = [node("goal", {"path": refs["goal"]["path"], "sha256": refs["goal"]["sha256"], "base_revision": refs["base_revision"],
                           "ref": "git:" + refs["base_revision"] + ":" + refs["goal"]["path"]}),
             node("research", {"packet_digest": refs["packet_digest"], "execution_ref": refs["research_execution_ref"],
                               "task_id": refs["research_task_id"], "sha256": refs["packet_digest"]}),
             node("design", {"session_id": refs["session_id"], "packet_digest": refs["packet_digest"],
                             "decision_event_id": refs["decision_event_id"], "role_bindings": refs["role_bindings"],
                             "sha256": digest(refs["role_bindings"])}),
             node("candidate", {"revision": refs["candidate"]["revision"], "base": refs["candidate"]["base"],
                                "tree": refs["candidate"]["tree"], "diff_hash": refs["candidate"]["diff_hash"],
                                "task_id": refs["implementation_task_id"], "execution_ref": refs["implementation_execution_ref"],
                                "reservation_id": refs.get("implementation_reservation_id")}),
             node("verification", {"decision_id": refs["decision_id"], "review_execution_ref": refs["review_execution_ref"],
                                   "review_reservation_id": refs.get("review_reservation_id"),
                                   "inspection_id": refs["inspection_id"], "operation_id": refs["operation_id"],
                                   "sha256": digest([refs["decision_id"], refs["review_execution_ref"], refs["inspection_id"]])})]
    ids = [n["id"] for n in nodes]
    edges = [(ids[1], ids[0], "derived_from"), (ids[2], ids[1], "derived_from"), (ids[3], ids[2], "implements"),
             (ids[3], ids[4], "verified_by")]
    return {"repository": repository, "nodes": nodes, "edges": [{"source": s, "target": t, "kind": k} for s, t, k in edges]}
