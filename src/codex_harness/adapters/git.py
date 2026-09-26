from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.domain.model import ContractError, digest, require


class GitCommandError(RuntimeError):
    """Transport/tool failure, distinct from a violated candidate contract."""


class MergeRefused(ContractError):
    """A DEFINITE refusal of the mainline update: main was provably not changed by this merge.

    Only a positively recognized per-ref rejection of exactly `refs/heads/main` (or a refusal
    decided before any push was attempted) is one. Everything whose effect is not known - a remote
    failure, a missing or malformed status, a timeout, a transport error - is `GitCommandError`
    instead and is reconciled from the remote history before anything is retried or withdrawn.
    """

    def __init__(self, reason_code: str):
        super().__init__("merge refused: " + reason_code)
        self.reason_code = reason_code


MAIN_REF = "refs/heads/main"
# The per-ref reasons git reports when the remote main was not the expected old value, either on
# the client's lease check (`stale info`) or in receive-pack's own old-id check (`incorrect old
# value provided`), or as an ordinary non-fast-forward (`fetch first`, `non-fast-forward`).
BASE_MOVED_REASONS = frozenset({"stale info", "incorrect old value provided", "fetch first",
                                "non-fast-forward"})
PORCELAIN_STATUS = re.compile(r"^(?P<flag>[ +\-*=!])\t(?P<from>[^\t:]*):(?P<to>[^\t]+)\t(?P<summary>.*)$")
REJECTION = re.compile(r"^\[(?P<kind>rejected|remote rejected)\](?: \((?P<reason>[^()]*)\))?$")


def classify_push(stdout: str, revision: str) -> str:
    """The outcome of one `git push --porcelain` of `revision` to `refs/heads/main`.

    `pushed` (the ref is now the revision: a fast-forward or already up to date), `base_moved` and
    `refused` are the only definite answers, and each needs exactly ONE status line for exactly the
    main ref from exactly this revision. `[remote failure]`, any other flag, a second or foreign
    line, a malformed or missing status line are all `unknown`: the effect may or may not have
    happened, so the caller reconciles instead of concluding (git-push(1) OUTPUT).
    """
    rows = [line for line in (stdout or "").splitlines() if line and line[0] in " +-*=!" and "\t" in line]
    if len(rows) != 1:
        return "unknown"
    match = PORCELAIN_STATUS.match(rows[0])
    if match is None or match["to"] != MAIN_REF or match["from"] != revision:
        return "unknown"
    if match["flag"] in {" ", "="}:
        return "pushed"
    if match["flag"] != "!":
        return "unknown"
    rejection = REJECTION.match(match["summary"].strip())
    if rejection is None:
        return "unknown"   # `[remote failure]` and anything a future git reports: not a refusal
    return "base_moved" if (rejection["reason"] or "") in BASE_MOVED_REASONS else "refused"


GITHUB_REMOTE = re.compile(r"(?:(?:https?://|ssh://git@|git@)(?:www\.)?github\.com[:/])?"
                           r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<repo>[A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?\Z")


def canonical_remote(remote: str) -> str:
    """One identity per GitHub repository, whatever spelling configured it (slug, https, ssh, .git)."""
    match = isinstance(remote, str) and GITHUB_REMOTE.fullmatch(remote.strip())
    require(bool(match), "Unsupported remote target; use a GitHub owner/repo slug or URL")
    return "github:" + match.group("owner").lower() + "/" + match.group("repo").lower()


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
        """Canonical target: the GitHub repository, or this exact local repository (its Git common
        directory, re-read from Git on every call). A clone or copy is a different target (PR #48)."""
        if self.remote:
            return canonical_remote(self.remote)
        common = Path(self._git("rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
        return "local:" + common.as_posix()

    def require_target(self, candidate: dict) -> str:
        """A candidate captured for one repository never merges or publishes into another.

        Candidates recorded before FA-015 carry no `repository`; they pass as `legacy_unverified`,
        an explicit exception to the target guarantee, never as a verified target.
        """
        recorded = candidate.get("repository")
        if recorded is None:
            return "legacy_unverified"
        require(recorded == self.target_identity(), "Candidate target repository changed since review")
        return "verified"

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

    def continue_workspace(self, origin_task_id: str, task_id: str, head: str, base: str) -> dict:
        """Reuse the ORIGINAL managed workspace for a continuation successor (INV-CONTINUATION-001).

        Only an owner-derived origin id under this managed root is accepted, never a path. The
        workspace must still be on the origin's own branch with its pinned assignment base, its
        HEAD must be exactly the last submitted candidate and it must be clean: a dirty or moved
        workspace is refused and never reset or cleaned. Whether an execution still owns it is the
        caller's store check. The successor's candidate is captured under its own task id while
        the branch, the pinned base and the rejected commits of the origin stay where they are."""
        require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", origin_task_id)), "Invalid workspace ID")
        require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", task_id)), "Invalid workspace ID")
        require(bool(re.fullmatch(r"[0-9a-f]{40}", str(head))) and bool(re.fullmatch(r"[0-9a-f]{40}", str(base))),
                "Continuation workspace needs exact head and base revisions")
        path = self.workspaces / origin_task_id
        require(path.is_dir() and not path.is_symlink() and path.resolve().parent == self.workspaces,
                "Continuation workspace missing from managed root")
        marker = path / ".git" / "harness-assignment-base"
        require(marker.is_file() and marker.read_text("utf-8").strip() == base,
                "Continuation workspace base changed")
        branch = "harness/" + origin_task_id
        require(self._git("branch", "--show-current", cwd=str(path)) == branch, "Workspace branch mismatch")
        require(self._git("rev-parse", "HEAD", cwd=str(path)) == head, "Continuation workspace moved from its candidate")
        require(not self._git("status", "--porcelain", cwd=str(path)), "Continuation workspace is dirty")
        return {"path": str(path), "branch": branch, "base": base, "task_id": task_id,
                "origin_task_id": origin_task_id, "continued_from": head}

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
        self._git("push", self._remote_url(), candidate["revision"] + ":refs/heads/" + branch)
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

    def qualify_merged(self, candidate: dict, merged_revision: str, *, fetch: bool = True) -> dict:
        """The merged commit really carries the REVIEWED tree (FA-015).

        One qualification for both paths: the merge this process performed and a merge it only
        observed after a lost response or a later tick. A merge that happened is not a qualified
        deployment, so a merged revision whose tree is not the reviewed one is refused here exactly
        as it is during the merge itself, however successfully the provider reports it.
        """
        require(bool(re.fullmatch(r"[0-9a-f]{40}", str(merged_revision or ""))),
                "Merged revision required")
        if fetch and self.remote:
            self._git("fetch", self._remote_url(), "main")
        tree = self._git("rev-parse", merged_revision + "^{tree}")
        require(tree == candidate["tree"], "Merged tree differs from reviewed candidate")
        return {"merged_revision": merged_revision, "tree": tree}

    def _remote_url(self) -> str:
        """The configured GitHub repository's transport URL: the one place a push or fetch names it."""
        return "https://github.com/" + self.remote + ".git"

    def remote_main(self) -> str:
        """The remote main's exact commit id, read with `ls-remote` (no fetch, no local ref moves).
        An unreadable or ambiguous answer is a transport failure, never a guessed revision."""
        require(bool(self.remote), "GitHub repository must be configured")
        rows = [line.split("\t") for line in self._git("ls-remote", self._remote_url(), MAIN_REF).splitlines()
                if line.strip()]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != MAIN_REF \
                or not re.fullmatch(r"[0-9a-f]{40}", rows[0][0]):
            raise GitCommandError("Remote main unreadable")
        return rows[0][0]

    def _on_mainline(self, revision: str, main: str) -> bool:
        """`revision` is on main's FIRST-PARENT history: main itself moved through exactly it (a
        fast-forward of it, by anyone). Reachable only through a merge commit's other parent is not
        this: that merge's own tree is what main carries, and it is recognized from the PR."""
        result = run_process(["git", "merge-base", "--is-ancestor", revision, main], cwd=str(self.repository))
        if result.returncode not in {0, 1}:
            raise GitCommandError("Cannot establish mainline ancestry")
        return result.returncode == 0 and revision in self._git("rev-list", "--first-parent", main).split()

    def merge_state(self, candidate: dict, observed=None) -> dict:
        """What the remote main says about this candidate NOW; read-only apart from the fetch.

        In this order: `merged` at the candidate revision when it is on main's first-parent history
        (R1, the lease fast-forward or anyone's fast-forward of exactly it); `merged` at the PR's
        merge commit when `observed` is this exact head's PR in state MERGED (R2); `unmerged` when
        main is still exactly the reviewed base (R3); `base_moved` otherwise (R4). A lost response
        of an effect that DID happen is therefore always recognized here before anything is
        refused, retried or withdrawn. A fetch that fails raises: unknown is never `unmerged`.
        """
        require(bool(self.remote), "GitHub repository must be configured")
        revision = candidate["revision"]
        self._git("fetch", self._remote_url(), "main")
        main = self._git("rev-parse", "FETCH_HEAD")
        state = {"main": main, "merged_revision": None, "recognized": None}
        if self._on_mainline(revision, main):
            return {**state, "state": "merged", "merged_revision": revision, "recognized": "mainline"}
        merged = (observed or {}).get("merged_revision") if isinstance(observed, dict) else None
        if isinstance(observed, dict) and observed.get("state") == "MERGED" and observed.get("head") == revision \
                and re.fullmatch(r"[0-9a-f]{40}", str(merged or "")):
            return {**state, "state": "merged", "merged_revision": merged, "recognized": "pull_request"}
        if main == candidate["base"]:
            return {**state, "state": "unmerged"}
        return {**state, "state": "base_moved"}

    def _lease_push(self, candidate: dict) -> None:
        """ONE server-side compare-and-swap of main from exactly the reviewed base to exactly the
        reviewed revision: the full ref and the explicit expected value, never a tracking-ref
        shorthand, `--force` or a permissive refspec. Its per-ref status decides (`classify_push`);
        a return code that disagrees with it is a conflict and therefore unknown."""
        revision, base = candidate["revision"], candidate["base"]
        argv = ["git", "push", "--porcelain", "--force-with-lease=" + MAIN_REF + ":" + base, self._remote_url(),
                revision + ":" + MAIN_REF]
        try:
            result = run_process(argv, cwd=str(self.repository), timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError("Mainline update outcome unknown (timeout)") from exc
        outcome = classify_push(result.stdout, revision)
        if outcome == "pushed" and result.returncode == 0:
            return
        if outcome == "base_moved" and result.returncode != 0:
            raise MergeRefused("reviewed_base_moved")
        if outcome == "refused" and result.returncode != 0:
            raise MergeRefused("merge_push_refused")
        raise GitCommandError("Mainline update outcome unknown")

    def merge(self, candidate: dict, observed=None) -> dict:
        target = self.require_target(candidate)
        require(self._git("rev-parse", candidate["revision"] + "^{tree}") == candidate["tree"],
                "Candidate tree changed")
        if candidate.get("diff_hash"):
            require(digest(self._git("diff", "--no-ext-diff", candidate["base"], candidate["revision"], "--"))
                    == candidate["diff_hash"], "Candidate patch changed")
        if self.remote:
            # INV-RELEASE-001: the GitHub merge is a fast-forward of main from the reviewed base to the
            # reviewed revision, so the merged tree IS the reviewed tree. An effect that already
            # happened is recognized first; a new one needs exact ancestry and the server-side
            # old-id compare-and-swap, never `gh pr merge` (which binds the head only).
            state = self.merge_state(candidate, observed)
            if state["state"] == "merged":
                merged_revision = state["merged_revision"]
                self.qualify_merged(candidate, merged_revision, fetch=False)
                self._git("merge", "--ff-only", merged_revision)
                return {"merged": True, "revision": candidate["revision"], "merged_revision": merged_revision,
                        "transport": "github", "target": target, "recovered": True}
            if not self.is_ancestor(candidate["base"], candidate["revision"]):
                raise MergeRefused("candidate_not_fast_forward")
            if state["state"] != "unmerged":
                raise MergeRefused("reviewed_base_moved")
            self._lease_push(candidate)
            self.qualify_merged(candidate, candidate["revision"], fetch=False)
            self._git("merge", "--ff-only", candidate["revision"])
            return {"merged": True, "revision": candidate["revision"], "merged_revision": candidate["revision"],
                    "transport": "github", "target": target}
        require(not self._git("status", "--porcelain"), "Main worktree is dirty")
        require(self._git("rev-parse", "HEAD") == candidate["base"], "Main changed; rebase and review again")
        self._git("merge", "--ff-only", candidate["revision"])
        return {"merged": True, "revision": candidate["revision"], "transport": "local", "target": target}
