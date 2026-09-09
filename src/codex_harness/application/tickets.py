"""Versioned review topics. Ticket feedback is advisory, never release authority."""
from copy import deepcopy
from uuid import uuid4

from codex_harness.domain.model import ContractError, digest, envelope, require, utcnow

TEXT_FIELDS = ("title", "problem", "impact", "rollback")
LIST_FIELDS = ("evidence_refs", "scope", "acceptance_criteria", "verification")


class TicketSuperseded(ContractError):
    """The request changed; retain execution evidence without downstream authority."""


def validate_content(content):
    require(isinstance(content, dict) and set(content) == set(TEXT_FIELDS + LIST_FIELDS),
            "Ticket needs title, problem, impact, rollback, evidence_refs, scope, acceptance_criteria, verification")
    for name in TEXT_FIELDS:
        require(isinstance(content[name], str) and 0 < len(content[name].strip()) <= 12000,
                "Invalid ticket " + name)
    for name in LIST_FIELDS:
        require(isinstance(content[name], list) and 0 < len(content[name]) <= 50
                and all(isinstance(item, str) and 0 < len(item.strip()) <= 4000 for item in content[name]),
                "Invalid ticket " + name)
    return deepcopy(content)


def ticket_binding(tx, value):
    """INV-TICKET-001: find and validate the same provenance across plan/rework/review."""
    bindings = []
    def visit(item):
        if isinstance(item, dict):
            if "zeus_ticket" in item:
                bound = item["zeus_ticket"]
                require(isinstance(bound, dict) and set(bound) == {"id", "revision", "content_hash"},
                        "Invalid Zeus ticket binding")
                bindings.append(bound)
            for key, child in item.items():
                if key != "zeus_ticket":
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    if not bindings:
        return None
    require(all(row == bindings[0] for row in bindings), "Conflicting ticket revisions")
    bound = bindings[0]
    current = tx.get("tickets", bound["id"])
    require(current is not None, "Ticket missing")
    if current["revision"] != bound["revision"] or current["content_hash"] != bound["content_hash"]:
        raise TicketSuperseded("Ticket changed; reassessment required")
    revision = tx.get("ticket_revisions", f'{bound["id"]}:{bound["revision"]}')
    require(revision and digest(revision["content"]) == bound["content_hash"], "Ticket revision corrupted")
    return deepcopy(bound)


class Tickets:
    def __init__(self, store, organization):
        self.store, self.org = store, organization

    def create(self, content, author="operator"):
        content = validate_content(content)
        require(isinstance(author, str) and bool(author.strip()), "Ticket author required")
        row = {"id": "ZEUS-" + uuid4().hex[:12], "revision": 1,
               "content_hash": digest(content), "status": "open", "created_at": utcnow()}
        with self.store.transaction() as tx:
            tx.put("tickets", row["id"], row)
            tx.put("ticket_revisions", row["id"] + ":1", {**row, "content": content,
                    "claimed_author": author, "reason": "created"})
        return row

    def update(self, ticket_id, expected_revision, content, reason, author="operator"):
        content = validate_content(content)
        require(isinstance(reason, str) and bool(reason.strip()), "Revision reason required")
        require(isinstance(author, str) and bool(author.strip()), "Ticket author required")
        with self.store.transaction() as tx:
            row = tx.get("tickets", ticket_id)
            require(row and row["revision"] == expected_revision, "Stale ticket edit")
            for intent in tx.scan("promotion_intents"):
                if intent.get("candidate", {}).get("zeus_ticket", {}).get("id") == ticket_id:
                    require(intent["status"] in {"completed", "abandoned"},
                            "Ticket promotion unresolved; resume release or release-abandon before editing")
            require(row["content_hash"] != digest(content), "Ticket content unchanged")
            row.update(revision=row["revision"] + 1, content_hash=digest(content),
                       status="open", updated_at=utcnow())
            tx.put("tickets", ticket_id, row)
            tx.put("ticket_revisions", f'{ticket_id}:{row["revision"]}',
                   {**row, "content": content, "claimed_author": author, "reason": reason})
            for dispatch in tx.scan("ticket_dispatches"):
                if dispatch["ticket_id"] == ticket_id and dispatch["status"] != "superseded":
                    tx.put("ticket_dispatches", dispatch["id"], {**dispatch, "status": "superseded",
                        "superseded_by_revision": row["revision"]})
            return row

    def get(self, ticket_id, revision=None):
        with self.store.transaction() as tx:
            current = tx.get("tickets", ticket_id)
            require(current is not None, "Ticket not found")
            row = tx.get("ticket_revisions", f'{ticket_id}:{revision or current["revision"]}')
            require(row and digest(row["content"]) == row["content_hash"], "Ticket revision unavailable or corrupted")
            reviews = [r for r in tx.scan("ticket_reviews") if r["ticket_id"] == ticket_id
                       and r["revision"] == row["revision"]]
            links = [r for r in tx.scan("ticket_github") if r["ticket_id"] == ticket_id]
            observations = [r for r in tx.scan("ticket_remote_observations") if r["ticket_id"] == ticket_id]
        return {**row, "current_revision": current["revision"], "status": current["status"],
                "reviews": sorted(reviews, key=lambda r: (r["at"], r["id"])),
                "github": sorted(links, key=lambda r: r["id"]),
                "external_observations": sorted(observations, key=lambda r: (r["at"], r["id"]))}

    def list(self):
        with self.store.transaction() as tx:
            rows = tx.scan("tickets")
        return [self.get(row["id"]) for row in sorted(rows, key=lambda row: row["created_at"])]

    def review(self, ticket_id, revision, reviewer, claimed_provider, verdict, summary, evidence_refs):
        require(verdict in {"support", "changes_requested", "question"}, "Invalid advisory verdict")
        require(all(isinstance(v, str) and 0 < len(v.strip()) <= 12000 for v in
                    (reviewer, claimed_provider, summary)), "Reviewer, provider and findings required")
        require(isinstance(evidence_refs, list) and evidence_refs
                and all(isinstance(v, str) and v.strip() for v in evidence_refs), "Review evidence required")
        with self.store.transaction() as tx:
            ticket = tx.get("tickets", ticket_id)
            require(ticket and ticket["revision"] == revision, "Stale ticket review")
            row = {"ticket_id": ticket_id, "revision": revision, "content_hash": ticket["content_hash"],
                   "claimed_reviewer": reviewer, "claimed_provider": claimed_provider, "verdict": verdict,
                   "summary": summary, "evidence_refs": evidence_refs, "authority": "advisory_only"}
            identity = digest(row)
            existing = tx.get("ticket_reviews", identity)
            if existing:
                return existing
            require(sum(r["ticket_id"] == ticket_id and r["revision"] == revision
                        for r in tx.scan("ticket_reviews")) < 20, "Ticket revision review budget exhausted")
            row.update(id=identity, at=utcnow())
            tx.put("ticket_reviews", identity, row)
            return row

    def dispatch(self, ticket_id, expected_revision, repository_revision):
        require(bool(repository_revision), "Repository revision required")
        with self.store.transaction() as tx:
            ticket = tx.get("tickets", ticket_id)
            require(ticket and ticket["revision"] == expected_revision, "Stale ticket dispatch")
            bound = {key: ticket[key] for key in ("id", "revision", "content_hash")}
            ticket_binding(tx, {"zeus_ticket": bound})
            key = digest(bound)
            previous = tx.get("ticket_dispatches", key)
            if previous:
                return previous
            content = tx.get("ticket_revisions", f'{ticket_id}:{expected_revision}')["content"]
            reviews = [r for r in tx.scan("ticket_reviews") if r["ticket_id"] == ticket_id
                       and r["revision"] == expected_revision]
            details = {"objective": content["title"] + "\n" + content["problem"],
                       "acceptance_criteria": content["acceptance_criteria"], "zeus_ticket": bound,
                       "ticket_context": content, "ticket_reviews": reviews}
            observations = sorted((r for r in tx.scan("ticket_remote_observations")
                                   if r["ticket_id"] == ticket_id), key=lambda r: (r["at"], r["id"]))
            details["external_ticket_observations"] = observations[-10:]
            details["external_ticket_observations_total"] = len(observations)
            details["external_ticket_observations_omitted"] = max(0, len(observations) - 10)
            message = envelope("task.assign", "conductor", "lead:improvement", "plan", details,
                               "ticket:" + ticket_id + ":" + str(expected_revision))
            message["where"]["revision"] = repository_revision
            message["how"]["acceptance_criteria"] = content["acceptance_criteria"]
            self.org.authorize(message)
            tx.put("outbox", message["message_id"], {"message": message, "sent": False})
            result = {"id": key, "ticket_id": ticket_id, "revision": expected_revision,
                      "message_id": message["message_id"], "status": "queued_for_planning"}
            tx.put("ticket_dispatches", key, result)
            tx.put("tickets", ticket_id, {**ticket, "status": "dispatched"})
            return result


def render_ticket(ticket):
    content = ticket["content"]
    sections = [f'<!-- zeus-ticket:{ticket["id"]} -->',
                f'# {content["title"]}',
                f'Zeus `{ticket["id"]}` · revision {ticket["revision"]} · `{ticket["content_hash"]}`',
                '> Local ledger is authoritative. Reviews below are advisory, not deployment approval.']
    for name in TEXT_FIELDS[1:] + LIST_FIELDS:
        value = content[name]
        sections.append("## " + name.replace("_", " ").title() + "\n\n" +
                        ("\n".join("- " + line for line in value) if isinstance(value, list) else value))
    sections.append("## Reviewer findings")
    for row in ticket["reviews"]:
        sections.append(f'### {row["claimed_reviewer"]} ({row["claimed_provider"]}) — {row["verdict"]}\n\n'
                        + row["summary"] + "\n\nEvidence: " + ", ".join(row["evidence_refs"]))
    if not ticket["reviews"]:
        sections.append("No review recorded for this revision.")
    return "\n\n".join(sections) + "\n"
