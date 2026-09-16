"""Goal manifest denominator and read-only progress observation (INV-GOAL-PROGRESS-001).

A goal manifest lives in Git and pins each acceptance criterion to one ticket revision. Progress is
observed from the existing ticket closure chain only: no review vote, remote issue state, task
result, commit or PR counts as completion. Nothing here closes, signs, approves or deploys.
"""
from copy import deepcopy

from codex_harness.application.ticket_lifecycle import event_document, verify_chain
from codex_harness.domain.model import ContractError, digest, require

SCHEMA = "urn:zeus:goal-progress:1"
MANIFEST_FIELDS = {"version", "id", "objective", "non_goals", "criteria"}
CRITERION_FIELDS = {"id", "acceptance", "ticket_id", "revision", "content_hash"}
REPORT_FIELDS = {"schema", "authority", "goal_id", "definition_hash", "objective", "criteria", "metrics"}
STATUSES = {"resolved", "pending", "reopened", "missing", "stale", "unverified"}
COUNTED = ("resolved", "reopened", "missing", "stale", "unverified")


def _text(value, limit=12000):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _sha_ref(value):
    return isinstance(value, str) and value.startswith("sha256:") and _hex(value[7:])


def validate_manifest(manifest):
    require(isinstance(manifest, dict) and set(manifest) == MANIFEST_FIELDS,
            "Goal manifest needs version, id, objective, non_goals and criteria")
    require(type(manifest["version"]) is int and manifest["version"] == 1, "Unsupported goal manifest version")
    require(_text(manifest["id"], 200) and _text(manifest["objective"]), "Goal id and objective required")
    require(isinstance(manifest["non_goals"], list) and all(_text(v, 4000) for v in manifest["non_goals"]),
            "Goal non_goals must be a list of text")
    criteria = manifest["criteria"]
    require(isinstance(criteria, list) and 0 < len(criteria) <= 50, "Goal criteria must hold 1 to 50 entries")
    ids, tickets = set(), set()
    for criterion in criteria:
        require(isinstance(criterion, dict) and set(criterion) == CRITERION_FIELDS,
                "Goal criterion needs id, acceptance, ticket_id, revision and content_hash")
        require(_text(criterion["id"], 200) and _text(criterion["acceptance"]) and _text(criterion["ticket_id"], 200),
                "Goal criterion id, acceptance and ticket_id required")
        require(type(criterion["revision"]) is int and criterion["revision"] > 0,
                "Goal criterion revision must be a positive integer")
        require(_hex(criterion["content_hash"]), "Goal criterion content_hash must be 64 lowercase hex")
        require(criterion["id"] not in ids, "Duplicate goal criterion id")
        require(criterion["ticket_id"] not in tickets, "Duplicate goal criterion ticket binding")
        ids.add(criterion["id"])
        tickets.add(criterion["ticket_id"])
    return deepcopy(manifest)


def definition_hash(manifest):
    """Identity of the whole validated definition; a changed denominator is a new definition."""
    return digest(validate_manifest(manifest))


def _events(tx, ticket):
    verify_chain(tx, ticket)
    events, identity = [], ticket.get("lifecycle_event")
    while identity:
        event = event_document(tx, identity)
        events.append(event)
        identity = event["previous_event"]
    return events


def _closure(tx, ticket, events):
    event = events[0] if events else None
    if not (event and event["kind"] == "closed" and event["sequence"] == ticket.get("lifecycle_sequence")
            and event["revision"] == ticket["revision"] and event["content_hash"] == ticket["content_hash"]
            and _sha_ref(event.get("packet_ref")) and _sha_ref(event.get("proof_ref"))):
        return None
    closure = tx.get("ticket_closures", event["packet_ref"])
    if not (closure and closure.get("event_id") == event["id"] == ticket.get("lifecycle_event")):
        return None
    return {"event_id": event["id"], "packet_ref": event["packet_ref"], "proof_ref": event["proof_ref"]}


def evaluate_criterion(tx, criterion):
    """Observe one criterion against the rows as stored now; never emits raw records or errors."""
    view = {key: criterion[key] for key in ("id", "acceptance", "ticket_id", "revision", "content_hash")}
    ticket = tx.get("tickets", criterion["ticket_id"])
    revision = tx.get("ticket_revisions", f'{criterion["ticket_id"]}:{criterion["revision"]}')
    if ticket is None or revision is None:
        return {**view, "status": "missing"}
    if ticket.get("revision") != criterion["revision"] or ticket.get("content_hash") != criterion["content_hash"]:
        return {**view, "status": "stale"}
    if revision.get("content_hash") != criterion["content_hash"] or digest(revision.get("content")) != criterion["content_hash"]:
        return {**view, "status": "unverified"}
    try:
        events = _events(tx, ticket)
    except ContractError:
        return {**view, "status": "unverified"}
    if ticket.get("status") == "closed":
        closure = _closure(tx, ticket, events)
        if closure is None:
            return {**view, "status": "unverified"}
        return {**view, "status": "resolved", "closure": closure}
    if ticket.get("status") in {"open", "dispatched"}:
        reopened = any(event["kind"] == "closed" for event in events)
        return {**view, "status": "reopened" if reopened else "pending"}
    return {**view, "status": "unverified"}


def admit_dispatch(tx, manifest, criterion_id, bound):
    """Goal-bound work admission: the exact dispatched ticket binding must be a pending or reopened criterion."""
    require(_text(criterion_id, 200), "Goal criterion id required")
    selected = [c for c in manifest["criteria"] if c["id"] == criterion_id]
    require(selected, "Goal criterion not in manifest")
    criterion = selected[0]
    require(all(criterion[key] == bound[field] for key, field in
                (("ticket_id", "id"), ("revision", "revision"), ("content_hash", "content_hash"))),
            "Dispatch ticket does not match the goal criterion binding")
    status = evaluate_criterion(tx, criterion)["status"]
    require(status in {"pending", "reopened"}, "Goal criterion is " + status + "; dispatch refused")
    return {"id": manifest["id"], "definition_hash": digest(manifest), "criterion_id": criterion_id}


class GoalProgress:
    def __init__(self, store):
        self.store = store

    def report(self, manifest):
        manifest = validate_manifest(manifest)
        with self.store.transaction() as tx:
            criteria = [evaluate_criterion(tx, criterion) for criterion in manifest["criteria"]]
        total = len(criteria)
        counts = {status: sum(c["status"] == status for c in criteria) for status in COUNTED}
        metrics = {"total": total, **counts, "remaining": total - counts["resolved"],
                   "completion_ratio": counts["resolved"] / total}
        return {"schema": SCHEMA, "authority": "observation_only", "goal_id": manifest["id"],
                "definition_hash": digest(manifest), "objective": manifest["objective"],
                "criteria": criteria, "metrics": metrics}


def _validate_report(report):
    require(isinstance(report, dict) and set(report) == REPORT_FIELDS and report["schema"] == SCHEMA
            and report["authority"] == "observation_only", "Unknown goal progress report shape")
    require(_text(report["goal_id"], 200) and _hex(report["definition_hash"]), "Goal report identity required")
    criteria = report["criteria"]
    require(isinstance(criteria, list) and 0 < len(criteria) <= 50, "Goal report criteria required")
    bindings = {}
    for criterion in criteria:
        require(isinstance(criterion, dict) and CRITERION_FIELDS | {"status"} <= set(criterion)
                and set(criterion) <= CRITERION_FIELDS | {"status", "closure"}, "Invalid goal report criterion")
        require(criterion["status"] in STATUSES, "Invalid goal criterion status")
        require(criterion["id"] not in bindings, "Duplicate goal criterion id")
        bindings[criterion["id"]] = {key: criterion[key] for key in ("acceptance", "ticket_id", "revision", "content_hash")}
    return bindings


def compare_reports(before, after):
    """Pure same-definition comparison; derived from criterion statuses, never supplied metrics."""
    first, second = _validate_report(before), _validate_report(after)
    require(before["goal_id"] == after["goal_id"] and before["definition_hash"] == after["definition_hash"],
            "Goal definition changed; reports are not comparable")
    require(first == second, "Goal criterion identities or bindings differ between reports")
    resolved_before = {c["id"] for c in before["criteria"] if c["status"] == "resolved"}
    resolved_after = {c["id"] for c in after["criteria"] if c["status"] == "resolved"}
    return {"authority": "observation_only", "goal_id": after["goal_id"],
            "definition_hash": after["definition_hash"],
            "gained": sorted(resolved_after - resolved_before), "regressed": sorted(resolved_before - resolved_after),
            "net_resolved": len(resolved_after) - len(resolved_before)}
