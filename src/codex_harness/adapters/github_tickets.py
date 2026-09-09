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
    def __init__(self, tickets, artifacts, lifecycle=None):
        self.tickets, self.store, self.artifacts = tickets, tickets.store, artifacts
        self.lifecycle = lifecycle

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
        remote = json.loads(self._call(["issue", "view", str(number), "--repo", repository,
                                       "--json", "number,url,title,body,state,comments"]))
        require(remote.get("number") == number and remote.get("state") in {"OPEN", "CLOSED"}
                and remote.get("url") == f"https://github.com/{repository}/issues/{number}"
                and all(isinstance(remote.get(k), str) for k in ("title", "body")),
                "Invalid GitHub issue readback")
        return remote

    def _observe(self, ticket_id, repository, remote, purpose):
        # INV-TICKET-001: preserve conflicts and late responses before interpreting them.
        receipt = self.artifacts.put(canonical(remote), "github-ticket-observation")
        identity = digest({"ticket_id": ticket_id, "repository": repository,
                           "evidence_ref": receipt["ref"], "purpose": purpose})
        observation = {"id": identity, "ticket_id": ticket_id, "repository": repository,
            "number": remote["number"], "url": remote["url"], "state": remote["state"],
            "title": remote["title"], "purpose": purpose, "evidence_ref": receipt["ref"],
            "marker_present": remote["body"].splitlines()[:1] == [f'<!-- zeus-ticket:{ticket_id} -->'],
            "authority": "external_observation_only", "at": utcnow()}
        with self.store.transaction() as tx:
            previous = tx.get("ticket_remote_observations", identity) or {}
            observation["first_seen"] = previous.get("first_seen", observation["at"])
            tx.put("ticket_remote_observations", observation["id"], observation)
        return observation

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

    def _renew(self, claim):
        with self.store.transaction() as tx:
            current = self._owned(tx, claim)
            tx.put("ticket_syncs", claim["id"], {**current,
                "lease_until": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()})

    def sync(self, ticket_id, repository, *, reconcile_observation=None, expected_revision=None):
        repository = self._repo(repository)
        ticket = self.tickets.get(ticket_id)
        desired_state, lifecycle_event = "OPEN", None
        require(expected_revision is None or expected_revision == ticket["revision"], "Stale ticket sync revision")
        require(reconcile_observation is None or expected_revision is not None,
                "Reconciliation requires the current ticket revision")
        body = render_ticket(ticket)
        require(len(body.encode("utf-8")) <= 60000, "Ticket too large for GitHub; use evidence references")
        key = digest({"ticket_id": ticket_id, "repository": repository})
        claim = self._claim(key)
        try:
            if ticket["status"] == "closed":
                require(self.lifecycle is not None, "Closure authority is required to project CLOSED")
                lifecycle_event = self.lifecycle.verify_closed(ticket, heartbeat=lambda: self._renew(claim))
                desired_state = "CLOSED"
            elif ticket.get("lifecycle_event"):
                from codex_harness.application.ticket_lifecycle import event_document, verify_chain
                with self.store.transaction() as tx:
                    verify_chain(tx, ticket)
                    event = event_document(tx, ticket["lifecycle_event"])
                require(event["ticket_id"] == ticket_id and event["sequence"] == ticket["lifecycle_sequence"],
                        "Invalid reopen authority")
                if event["kind"] == "reopened":
                    lifecycle_event = event
            self._renew(claim)
            with self.store.transaction() as tx:
                link = tx.get("ticket_github", key)
                previous = (tx.get("ticket_revisions", f'{ticket_id}:{link["synced_revision"]}')
                            if link else None)
                numbers = {r["number"] for r in tx.scan("ticket_remote_creations")
                           if r["ticket_id"] == ticket_id and r["repository"] == repository}
            numbers.update([link["number"]] if link else [])
            numbers.update([claim["created_number"]] if claim.get("created_number") else [])
            require(len(numbers) <= 1, "Multiple remote creation receipts; reconcile before syncing")
            if link:
                issue = self._read(repository, link["number"])
            elif numbers:
                issue = self._read(repository, next(iter(numbers)))
            else:
                marker = f'<!-- zeus-ticket:{ticket_id} -->'
                rows = json.loads(self._call(["issue", "list", "--repo", repository, "--state", "all",
                    "--search", f'"zeus-ticket:{ticket_id}" in:body', "--limit", "100", "--json", "number,url,body"]))
                matches = [row for row in rows if row.get("body", "").splitlines()[:1] == [marker]]
                require(len(matches) <= 1, "Multiple remote tickets; reconcile before syncing")
                issue = self._read(repository, matches[0]["number"]) if matches else None
                # INV-TICKET-001: a lost creation acknowledgement must not create a duplicate.
                require(issue is not None or not claim.get("creation_uncertain"),
                        "Remote creation is uncertain; retry discovery after GitHub indexing")
            reconciled = False
            if issue:
                self._observe(ticket_id, repository, issue, "pre_write")
                if reconcile_observation is not None:
                    with self.store.transaction() as tx:
                        observed = tx.get("ticket_remote_observations", reconcile_observation)
                    require(observed and observed["ticket_id"] == ticket_id
                            and observed["repository"] == repository and observed["number"] == issue["number"],
                            "Reconciliation observation belongs to another issue")
                    document = self.artifacts.document(observed["evidence_ref"])
                    require(all(document[k] == issue[k] for k in ("number", "url", "title", "body", "state")),
                            "Remote issue changed since reconciliation observation")
                    reconciled = True
                remote_hash = digest(issue["body"])
                require(reconciled or remote_hash in {digest(body), claim.get("pending_body_hash"), claim.get("observed_body_hash")}
                        or (link and remote_hash == link["body_hash"]),
                        "GitHub issue body changed externally; pull and reconcile before syncing")
                # Legacy links have a versioned local title, not an unknown title to trust blindly.
                previous_title_hash = (digest(previous["content"]["title"])
                                       if previous and link and "title_hash" not in link else None)
                require(reconciled or digest(issue["title"]) in {digest(ticket["content"]["title"]),
                        claim.get("pending_title_hash"), claim.get("observed_title_hash"),
                        (link or {}).get("title_hash"), previous_title_hash},
                        "GitHub issue title changed externally; pull and reconcile before syncing")
            else:
                require(reconcile_observation is None, "Cannot reconcile an undiscovered issue")
            state_authorized = lifecycle_event is not None and (link or {}).get("projected_lifecycle_event") != lifecycle_event["id"]
            state_conflict = issue is not None and issue["state"] != desired_state and not state_authorized
            with self.store.transaction() as tx:
                current = self._owned(tx, claim)
                live = tx.get("tickets", ticket_id)
                require(live["revision"] == ticket["revision"] and live["content_hash"] == ticket["content_hash"]
                        and live["status"] == ticket["status"]
                        and live.get("lifecycle_sequence", 0) == ticket["lifecycle_sequence"], "Ticket changed before sync")
                tx.put("ticket_syncs", key, {**current, "pending_body_hash": digest(body),
                    "lease_until": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
                    "pending_title_hash": digest(ticket["content"]["title"]),
                    # Explicit reconciliation is scoped to this attempt and revision, never a standing grant.
                    "observed_body_hash": digest(issue["body"]) if issue and not reconciled else current.get("observed_body_hash"),
                    "observed_title_hash": digest(issue["title"]) if issue and not reconciled else current.get("observed_title_hash"),
                    "reconcile_observation": reconcile_observation,
                    "creation_uncertain": issue is None or current.get("creation_uncertain", False)})
            if not state_conflict and (issue is None or digest(issue["body"]) != digest(body)
                                       or issue["title"] != ticket["content"]["title"]):
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
                    # A late response is an observation, not permission to finalize another owner's work.
                    creation = {"ticket_id": ticket_id, "repository": repository, **issue,
                                "claim_owner": claim["owner"], "authority": "external_observation_only"}
                    creation_ref = self.artifacts.put(canonical(creation), "github-ticket-creation")
                    with self.store.transaction() as tx:
                        tx.put("ticket_remote_creations", digest(creation),
                               {**creation, "evidence_ref": creation_ref["ref"], "at": utcnow()})
                    with self.store.transaction() as tx:
                        current = self._owned(tx, claim)
                        tx.put("ticket_syncs", key, {**current, "created_number": issue["number"]})
            state_attempted = not state_conflict and issue.get("state", "OPEN") != desired_state
            if state_attempted:
                require(lifecycle_event is not None, "State change requires a local lifecycle decision")
                args = ["issue", "close" if desired_state == "CLOSED" else "reopen", str(issue["number"]), "--repo", repository]
                if desired_state == "CLOSED":
                    args.extend(["--reason", "completed"])
                self._call(args)
            remote = self._read(repository, issue["number"])
            observation = self._observe(ticket_id, repository, remote, "post_write")
            if not state_conflict:
                require(remote["body"] == body and remote["title"] == ticket["content"]["title"],
                        "GitHub issue readback does not match the requested projection")
            if state_attempted:
                require(remote["state"] == desired_state, "GitHub state readback does not match lifecycle decision")
            state_conflict = remote["state"] != desired_state
            projection_matches = remote["body"] == body and remote["title"] == ticket["content"]["title"]
            record = {"id": key, "ticket_id": ticket_id, "repository": repository,
                      "number": issue["number"], "url": issue["url"], "attempted_revision": ticket["revision"],
                      "synced_revision": ticket["revision"] if projection_matches else (link or {}).get("synced_revision"),
                      "content_hash": ticket["content_hash"] if projection_matches else (link or {}).get("content_hash"),
                      "attempted_content_hash": ticket["content_hash"],
                      "body_hash": digest(remote["body"]) if projection_matches else (link or {}).get("body_hash"),
                      "title_hash": digest(remote["title"]) if projection_matches else (link or {}).get("title_hash"),
                      "observed_body_hash": digest(remote["body"]), "observed_title_hash": digest(remote["title"]),
                      "title": remote["title"],
                      "desired_state": desired_state, "observed_state": remote["state"],
                      "lifecycle_sequence": ticket["lifecycle_sequence"],
                      "lifecycle_event": lifecycle_event["id"] if lifecycle_event else None,
                      "observation_ref": observation["evidence_ref"], "observation_id": observation["id"], "at": utcnow()}
            record["review_ids"] = sorted(row["id"] for row in ticket["reviews"])
            with self.store.transaction() as tx:
                current = self._owned(tx, claim)
                live = tx.get("tickets", ticket_id)
                review_ids = sorted(row["id"] for row in tx.scan("ticket_reviews")
                                    if row["ticket_id"] == ticket_id and row["revision"] == ticket["revision"])
                current_snapshot = (live["revision"] == ticket["revision"]
                                    and live["content_hash"] == ticket["content_hash"]
                                    and live["status"] == ticket["status"]
                                    and live.get("lifecycle_sequence", 0) == ticket["lifecycle_sequence"]
                                    and review_ids == record["review_ids"])
                record["status"] = ("outdated" if not current_snapshot else "state_conflict" if state_conflict
                                    else "synced" if remote["body"] == body
                                    and remote["title"] == ticket["content"]["title"] else "outdated")
                record["projected_lifecycle_event"] = (lifecycle_event["id"] if lifecycle_event and record["status"] == "synced"
                                                      else (link or {}).get("projected_lifecycle_event"))
                tx.put("ticket_github", key, record)
                tx.put("ticket_syncs", key, {**current, "owner": None, "status": record["status"],
                    "creation_uncertain": False, "pending_body_hash": None, "pending_title_hash": None,
                    "observed_body_hash": digest(remote["body"]) if projection_matches else current.get("observed_body_hash"),
                    "observed_title_hash": digest(remote["title"]) if projection_matches else current.get("observed_title_hash")})
            return record
        except Exception as exc:
            with self.store.transaction() as tx:
                current = tx.get("ticket_syncs", key)
                if current and current.get("owner") == claim["owner"]:
                    tx.put("ticket_syncs", key, {**current, "owner": None, "status": "needs_attention",
                                                 "error_type": type(exc).__name__})
                    link = tx.get("ticket_github", key)
                    if link:
                        tx.put("ticket_github", key, {**link, "status": "needs_attention",
                                                     "error_type": type(exc).__name__})
            raise

    def pull(self, ticket_id, repository):
        repository = self._repo(repository)
        key = digest({"ticket_id": ticket_id, "repository": repository})
        with self.store.transaction() as tx:
            link = tx.get("ticket_github", key)
        require(link is not None, "Ticket has no GitHub link")
        remote = self._read(repository, link["number"])
        return self._observe(ticket_id, repository, remote, "pull")
