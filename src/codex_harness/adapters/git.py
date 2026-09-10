from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.domain.model import digest, require


class GitCommandError(RuntimeError):
    """Transport/tool failure, distinct from a violated candidate contract."""


class GitWorkspace:
    def __init__(self, repository: str, workspaces: str, remote: str | None = None):
        self.repository = Path(repository).resolve()
        self.workspaces = Path(workspaces).resolve()
        self.workspaces.mkdir(parents=True, exist_ok=True)
        self.remote = remote

    def _git(self, *args: str, cwd: str | None = None, strip: bool = True) -> str:
        result = run_process(["git", *args], cwd=cwd or str(self.repository), timeout=120)
        if result.returncode:
            raise GitCommandError("Git operation failed (" + (args[0] if args else '')
                + ", cwd=" + str(cwd or self.repository) + "): " + result.stderr[-2000:])
        return result.stdout.strip() if strip else result.stdout

    def target_identity(self) -> str:
        return self.remote or "local"

    def require_target(self, candidate: dict) -> None:
        """A candidate captured for one repository never merges or publishes into another."""
        recorded = candidate.get("repository")
        require(recorded is None or recorded == self.target_identity(),
                "Candidate target repository changed since review")

    def prepare(self, task_id: str, base: str = "HEAD") -> dict:
        require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", task_id)), "Invalid workspace ID")
        path = self.workspaces / task_id
        branch = "harness/" + task_id
        # INV-SESSION-001: retries keep their original base even when main advances.
        marker = path / '.git' / 'harness-assignment-base'
        pinned = marker.read_text('utf-8').strip() if marker.exists() else None
        revision = pinned if pinned and base == 'HEAD' else self._git(
            "rev-parse", "--verify", base + "^{commit}")
        require(not pinned or pinned == revision, 'Assignment base changed; use a new rebase task')
        if not path.exists():
            self._git("clone", "--no-hardlinks", str(self.repository), str(path))
            self._git("checkout", "-b", branch, revision, cwd=str(path))
        require(self._git("branch", "--show-current", cwd=str(path)) == branch, "Workspace branch mismatch")
        require(self._git("merge-base", revision, "HEAD", cwd=str(path)) == revision,
                "Workspace diverged from assignment base")
        if not pinned:
            marker.write_text(revision, encoding='utf-8')
        return {"path": str(path), "branch": branch, "base": revision, "task_id": task_id}

    def capture(self, workspace: dict) -> dict:
        path = str(Path(workspace["path"]).resolve())
        require(Path(path).parent == self.workspaces, "Workspace outside managed root")
        self._git("add", "--all", cwd=path)
        names = self._git("diff", "--cached", "--name-only", cwd=path).splitlines()
        require(not any(Path(n).name in {".env", "auth.json", "credentials.json"} for n in names),
                "Credential file cannot enter a candidate")
        if names:
            self._git("-c", "user.name=Codex Harness", "-c", "user.email=harness@localhost",
                      "commit", "-m", "Implement harness task " + workspace["task_id"], cwd=path)
        revision = self._git("rev-parse", "HEAD", cwd=path)
        require(revision != workspace["base"], "Task produced no code change")
        require(not self._git("status", "--porcelain", cwd=path), "Candidate workspace is dirty")
        self._git("fetch", path, "HEAD:refs/heads/" + workspace["branch"])
        # INV-RELEASE-001 (FA-015): the reviewed identity names its canonical target repository and
        # the exact patch (base -> revision) next to the preimage base and postimage tree.
        candidate = {**workspace, "revision": revision,
                     "tree": self._git("rev-parse", "HEAD^{tree}", cwd=path), "author": "worker:implementation",
                     "repository": self.target_identity(),
                     "diff_hash": digest(self._git("diff", "--no-ext-diff", workspace["base"], revision, "--",
                                                   cwd=path))}
        manifests = [name for name in self._git("diff", "--name-only", workspace["base"], revision, cwd=path).splitlines()
                     if name.startswith("harness_hooks/") and name.endswith(".json")]
        require(len(manifests) <= 1, "Split independent hook updates into separate candidates")
        if manifests:
            candidate["hook_id"] = Path(manifests[0]).stem
        definition = 'src/codex_harness/resources/audit-lifecycle.json'
        if definition in self._git('ls-tree', '-r', '--name-only', revision, cwd=path).splitlines():
            config = json.loads(self._git('show', revision + ':' + definition, cwd=path))
            require(config == {'version': 1}, 'Unsupported audit lifecycle definition')
            candidate['audit_lifecycle_version'] = 1
        return candidate

    def inspect(self, revision: str, base: str) -> dict:
        revision = self._git("rev-parse", "--verify", revision + "^{commit}")
        base = self._git("rev-parse", "--verify", base + "^{commit}")
        return {"revision": revision, "base": base,
                "tree": self._git("rev-parse", revision + "^{tree}"),
                "diff": self._git("diff", "--no-ext-diff", base, revision, "--"),
                "files": self._git("diff", "--name-only", base, revision, "--").splitlines()}

    def rebase(self, task_id: str, candidate: dict, new_base: str) -> dict:
        workspace = self.prepare(task_id, candidate["revision"])
        self._git("-c", "user.name=Codex Harness", "-c", "user.email=harness@localhost",
                  "rebase", "--onto", new_base, candidate["base"], cwd=workspace["path"])
        workspace["base"] = self._git("rev-parse", "--verify", new_base + "^{commit}")
        result = self.capture(workspace)
        if candidate.get("hook_id"):
            result["hook_id"] = candidate["hook_id"]
        if candidate.get("zeus_ticket"):
            result["zeus_ticket"] = candidate["zeus_ticket"]
        return result

    def review_workspace(self, revision: str, review_id: str) -> str:
        require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", review_id)), "Invalid review workspace ID")
        path = self.workspaces / ("review-" + review_id)
        if not path.exists():
            self._git("clone", "--no-hardlinks", str(self.repository), str(path))
            self._git("checkout", "--detach", revision, cwd=str(path))
        require(self._git("rev-parse", "HEAD", cwd=str(path)) == revision, "Stale review workspace")
        require(not self._git("status", "--porcelain", cwd=str(path)), "Review workspace is dirty")
        return str(path)

    def publish(self, candidate: dict, title: str, body: str) -> dict:
        require(bool(self.remote), "GitHub repository must be configured")
        self.require_target(candidate)
        require(bool(re.fullmatch(r"[\w.-]+/[\w.-]+", self.remote)), "Invalid GitHub repository")
        branch = candidate["branch"]
        self._git("push", "https://github.com/" + self.remote + ".git",
                  candidate["revision"] + ":refs/heads/" + branch)
        existing = run_process(["gh", "pr", "list", "--repo", self.remote, "--head", branch,
                                "--state", "all", "--json", "number,url,headRefOid,state"], timeout=60)
        if existing.returncode:
            raise GitCommandError("Cannot inspect GitHub PR")
        rows = json.loads(existing.stdout)
        matching = [row for row in rows if row["headRefOid"] == candidate["revision"]
                    and row["state"] in {"OPEN", "MERGED"}]
        if matching:
            return matching[0]
        require(not any(row["state"] == "OPEN" for row in rows), "PR head changed")
        with tempfile.TemporaryDirectory(prefix="harness-pr-") as directory:
            path = Path(directory) / "body.md"
            path.write_text(body, encoding="utf-8")
            result = run_process(["gh", "pr", "create", "--repo", self.remote, "--head", branch,
                                  "--base", "main", "--title", title, "--body-file", str(path)], timeout=60)
            if result.returncode:
                raise GitCommandError("PR creation failed: " + result.stderr[-1000:])
            return {"url": result.stdout.strip(), "headRefOid": candidate["revision"]}

    def is_ancestor(self, revision: str, descendant: str) -> bool:
        revision = self._git("rev-parse", "--verify", revision + "^{commit}")
        descendant = self._git("rev-parse", "--verify", descendant + "^{commit}")
        result = run_process(["git", "merge-base", "--is-ancestor", revision, descendant],
                             cwd=str(self.repository))
        if result.returncode not in {0, 1}:
            raise GitCommandError("Cannot establish candidate ancestry")
        return result.returncode == 0

    def merge(self, candidate: dict) -> dict:
        self.require_target(candidate)
        require(self._git("rev-parse", candidate["revision"] + "^{tree}") == candidate["tree"],
                "Candidate tree changed")
        if candidate.get("diff_hash"):
            require(digest(self._git("diff", "--no-ext-diff", candidate["base"], candidate["revision"], "--"))
                    == candidate["diff_hash"], "Candidate patch changed")
        if self.remote:
            result = run_process(["gh", "pr", "merge", candidate["branch"], "--repo", self.remote,
                                  "--merge", "--match-head-commit", candidate["revision"]], timeout=120)
            if result.returncode:
                raise GitCommandError("PR merge failed: " + result.stderr[-1000:])
            self._git("fetch", "https://github.com/" + self.remote + ".git", "main")
            merged_revision = self._git("rev-parse", "FETCH_HEAD")
            require(self._git("rev-parse", merged_revision + "^{tree}") == candidate["tree"],
                    "Merged tree differs from reviewed candidate")
            self._git("merge", "--ff-only", merged_revision)
            return {"merged": True, "revision": candidate["revision"], "merged_revision": merged_revision,
                    "transport": "github"}
        require(not self._git("status", "--porcelain"), "Main worktree is dirty")
        require(self._git("rev-parse", "HEAD") == candidate["base"], "Main changed; rebase and review again")
        self._git("merge", "--ff-only", candidate["revision"])
        return {"merged": True, "revision": candidate["revision"], "transport": "local"}
