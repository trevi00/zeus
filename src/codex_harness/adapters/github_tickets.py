"""Explicit GitHub projection; external issue text never overwrites the ticket ledger."""
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import run_process
from codex_harness.application.tickets import render_ticket
from codex_harness.domain.model import canonical, digest, require, utcnow


class GitHubTickets:
    def __init__(self, tickets, artifacts):
        self.tickets, self.store, self.artifacts = tickets, tickets.store, artifacts

    @staticmethod
    def _repo(repository):
        require(isinstance(repository, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", repository),
                "GitHub repository must be owner/name")
        return repository

    def _call(self, args):
        result = run_process(["gh", *args], timeout=60)
        if result.returncode:
            raise RuntimeError("GitHub issue operation failed; local ticket retained")
        return result.stdout.strip()

    def _read(self, repository, number):
        require(type(number) is int and number > 0, "Invalid GitHub issue number")
        return json.loads(self._call(["issue", "view", str(number), "--repo", repository,
                                     "--json", "number,url,title,body,state,comments"]))

    def _claim(self, key):
        now = datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            old = tx.get("ticket_syncs", key) or {}
            require(not old.get("owner") or datetime.fromisoformat(old["lease_until"]) <= now,
                    "Ticket sync already running")
            claim = {**old, "id": key, "owner": str(uuid4()), "status": "running",
                     "lease_until": (now + timedelta(seconds=300)).isoformat()}
            tx.put("ticket_syncs", key, claim)
            return claim

    @staticmethod
    def _owned(tx, claim):
        row = tx.get("ticket_syncs", claim["id"])
        require(row and row.get("owner") == claim["owner"]
                and datetime.fromisoformat(row["lease_until"]) > datetime.now(timezone.utc), "Stale ticket sync")
        return row

    def sync(self, ticket_id, repository):
        repository = self._repo(repository)
        ticket = self.tickets.get(ticket_id)
        body = render_ticket(ticket)
        require(len(body.encode("utf-8")) <= 60000, "Ticket too large for GitHub; use evidence references")
        key = digest({"ticket_id": ticket_id, "repository": repository})
        claim = self._claim(key)
        try:
            with self.store.transaction() as tx:
                link = tx.get("ticket_github", key)
            if link:
                issue = self._read(repository, link["number"])
            else:
                marker = f'<!-- zeus-ticket:{ticket_id} -->'
                rows = json.loads(self._call(["issue", "list", "--repo", repository, "--state", "all",
                    "--search", f'"zeus-ticket:{ticket_id}" in:body', "--limit", "100", "--json", "number,url,body"]))
                matches = [row for row in rows if row.get("body", "").splitlines()[:1] == [marker]]
                require(len(matches) <= 1, "Multiple remote tickets; reconcile before syncing")
                issue = matches[0] if matches else None
                # INV-TICKET-001: a lost creation acknowledgement must not create a duplicate.
                require(issue is not None or not claim.get("creation_uncertain"),
                        "Remote creation is uncertain; retry discovery after GitHub indexing")
            if issue:
                remote_hash = digest(issue["body"])
                require(remote_hash in {digest(body), claim.get("pending_body_hash"), claim.get("observed_body_hash")}
                        or (link and remote_hash == link["body_hash"]),
                        "GitHub issue body changed externally; pull and reconcile before syncing")
            with self.store.transaction() as tx:
                current = self._owned(tx, claim)
                live = tx.get("tickets", ticket_id)
                require(live["revision"] == ticket["revision"], "Ticket changed before sync")
                tx.put("ticket_syncs", key, {**current, "pending_body_hash": digest(body),
                    "observed_body_hash": digest(issue["body"]) if issue else current.get("observed_body_hash"),
                    "creation_uncertain": issue is None or current.get("creation_uncertain", False)})
            if issue is None or digest(issue["body"]) != digest(body):
                # Only the canonical projection is written; GitHub comments are left intact.
                with tempfile.TemporaryDirectory(prefix="zeus-issue-") as directory:
                    path = Path(directory) / "issue.md"
                    # INV-TICKET-001: the uploaded bytes must match the hashed projection on Windows too.
                    path.write_text(body, encoding="utf-8", newline="\n")
                    args = (["issue", "edit", str(issue["number"])] if issue else ["issue", "create"])
                    output = self._call([*args, "--repo", repository, "--title", ticket["content"]["title"],
                                         "--body-file", str(path)])
                if issue is None:
                    match = re.fullmatch(r"https://github\.com/" + re.escape(repository) + r"/issues/([1-9][0-9]*)", output)
                    require(match is not None, "Unrecognized created issue receipt; retry discovery")
                    issue = {"number": int(match[1]), "url": output}
            record = {"id": key, "ticket_id": ticket_id, "repository": repository,
                      "number": issue["number"], "url": issue["url"], "synced_revision": ticket["revision"],
                      "content_hash": ticket["content_hash"], "body_hash": digest(body), "at": utcnow()}
            record["review_ids"] = sorted(row["id"] for row in ticket["reviews"])
            with self.store.transaction() as tx:
                current = self._owned(tx, claim)
                live = tx.get("tickets", ticket_id)
                review_ids = sorted(row["id"] for row in tx.scan("ticket_reviews")
                                    if row["ticket_id"] == ticket_id and row["revision"] == ticket["revision"])
                record["status"] = ("synced" if live["revision"] == ticket["revision"]
                                    and review_ids == record["review_ids"] else "outdated")
                tx.put("ticket_github", key, record)
                tx.put("ticket_syncs", key, {**current, "owner": None, "status": record["status"],
                                             "creation_uncertain": False, "pending_body_hash": None})
            return record
        except Exception as exc:
            with self.store.transaction() as tx:
                current = tx.get("ticket_syncs", key)
                if current and current.get("owner") == claim["owner"]:
                    tx.put("ticket_syncs", key, {**current, "owner": None, "status": "needs_attention",
                                                 "error_type": type(exc).__name__})
            raise

    def pull(self, ticket_id, repository):
        repository = self._repo(repository)
        key = digest({"ticket_id": ticket_id, "repository": repository})
        with self.store.transaction() as tx:
            link = tx.get("ticket_github", key)
        require(link is not None, "Ticket has no GitHub link")
        remote = self._read(repository, link["number"])
        receipt = self.artifacts.put(canonical(remote), "github-ticket-observation")
        observation = {"id": receipt["ref"], "ticket_id": ticket_id, "repository": repository,
            "number": link["number"], "url": remote["url"], "state": remote["state"],
            "evidence_ref": receipt["ref"], "authority": "external_observation_only", "at": utcnow()}
        with self.store.transaction() as tx:
            tx.put("ticket_remote_observations", receipt["ref"], observation)
        return observation
