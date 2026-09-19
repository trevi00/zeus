"""Shared fixtures for the research-program tests (no tests here). Every stand-in is LABELLED: the
feeds, the machine ledger reading, the clock and the council are synthetic; the Git repository is real."""
import hashlib
import json
import subprocess
from pathlib import Path

from codex_harness.adapters.providers import packaged_policy
from codex_harness.domain.autonomous import manifest_digest
from codex_harness.domain.council import validate_any_manifest

CANARY = "CANARY-must-never-be-emitted"
NOTE = b"# local residual\nPG store serializes writers with one advisory lock.\n"
GOAL = b"# goal\n"
BASE_CLOCK = "2028-01-01T00:00:00+00:00"


def git(root, *argv, **kwargs):
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True, text=True, **kwargs)


def repository(tmp_path):
    """Real temporary Git repository with the goal, one local note and a dirty untracked file."""
    root = tmp_path / "repo"
    (root / "docs" / "research").mkdir(parents=True)
    (root / "docs" / "research" / "note.md").write_bytes(NOTE)
    (root / "docs" / "GOAL.md").write_bytes(GOAL)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--all")
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "base")
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "dirty.txt").write_text("uncommitted work stays untouched\n", encoding="utf-8")
    (root / "docs" / "GOAL.md").write_bytes(GOAL + b"working tree edit\n")
    return root, head


def template(head, deadline="2030-01-01T00:00:00+00:00"):
    return {"schema": "urn:zeus:autonomous:2", "id": "council-template", "base_revision": head,
            "goal": {"path": "docs/GOAL.md", "sha256": hashlib.sha256(GOAL).hexdigest(), "criterion": "c", "rationale": "r"},
            "plan": {"objective": "improve the research report " + CANARY, "acceptance_criteria": ["focused tests pass"],
                     "allowed_paths": ["docs/RUNBOOK.md"]},
            "budget": {"per_host": 10, "total": 20},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1},
            "deadline": deadline,
            "research": {"topic": "research report", "questions": ["What is the SSOT?"], "search_scope": ["docs"]},
            "current_state": {"records": [{"bucket": "tasks", "id": "t-1"}], "max_age_seconds": 600}}


def config(head, **overrides):
    document = {"schema": "urn:zeus:research-program:1", "id": "rp-001", "base_revision": head,
                "deadline": "2029-06-01T00:00:00+00:00", "interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
                "budget": {"per_host": 10, "total": 20},
                "topics": [{"id": "storage", "keywords": ["advisory lock", "postgres"]}],
                "local_candidates": [{"id": "local-note", "topic": "storage", "path": "docs/research/note.md",
                                      "sha256": hashlib.sha256(NOTE).hexdigest(), "rationale": "sterk residual " + CANARY}],
                "template": template(head)}
    document.update(overrides)
    return document


class FakeSources:
    """LABELLED synthetic feeds: no network. `outages` names sources that raise on collect."""

    def __init__(self, artifacts, outages=(), items=None):
        self.artifacts, self.outages, self.calls = artifacts, set(outages), []
        self.items = items if items is not None else {
            "github": [{"url": "https://github.com/acme/pgtool#readme", "title": "acme/pgtool", "summary": "Postgres tooling"},
                       {"url": "https://github.com/acme/unrelated", "title": "acme/unrelated", "summary": "a game engine"}],
            "geeknews": [{"url": "https://news.hada.io/topic?id=1", "title": "Advisory lock patterns", "summary": "<p>x</p>"}]}

    def collect(self, source):
        self.calls.append(source)
        if source in self.outages:
            raise OSError("fixture outage " + CANARY)
        receipt = self.artifacts.put("<html>fixture body " + source + "</html>", "fixture:" + source)
        return {"source": source, "fetched_at": BASE_CLOCK, "artifact": receipt["ref"], "items": list(self.items[source])}

    def github_detail(self, url):
        raise RuntimeError("fixture: no GitHub API " + CANARY)


class FakeBudget:
    """LABELLED synthetic machine ledger reading; the real CallBudget is never touched."""

    def __init__(self, this_host=0, all_hosts=0):
        self.this_host, self.all_hosts = this_host, all_hosts

    def counts(self):
        return {"host": "fixture", "this_host": self.this_host, "all_hosts": self.all_hosts, "unreadable": 0}


class FakeCouncil:
    """LABELLED council stand-in: validates the persisted manifest with the real validator and writes
    the `autonomous_runs` row the runner must read; no provider is called. `status` None writes no row
    and raises (a refusal before any claim); `raise_after_row` raises after writing the row."""

    def __init__(self, store, status="rejected", raise_after_row=False):
        self.store, self.status, self.raise_after_row, self.manifests = store, status, raise_after_row, []

    def __call__(self, service, args):
        manifest = validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), packaged_policy())
        self.manifests.append(manifest)
        if self.status is None:
            raise RuntimeError("fixture refusal before claim " + CANARY)
        with self.store.transaction() as tx:
            tx.put("autonomous_runs", manifest["id"], {"id": manifest["id"], "status": self.status, "stage": "promotion",
                                                       "manifest_sha256": manifest_digest(manifest),
                                                       "reason_code": "fixture_" + self.status})
        if self.raise_after_row:
            raise RuntimeError("fixture crash after the row " + CANARY)
        return {"status": self.status, "exit_code": 0}
