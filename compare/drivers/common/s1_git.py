"""Scenario body `host_os.git` (REBUILD-DESIGN-v2 §5.3 S1: Git fast-forward CAS on a local bare repo).

Layer: harness (never shipped). `api` provides: GitWorkspace, GitCommandError, MergeRefused,
classify_push, canonical_remote, ContractError. Everything runs against real local Git: a bare
repository stands in for the remote through the one seam `_remote_url` (as the M7 CAS tests do);
nothing touches a network, `gh` or GitHub. Author/committer identities and dates are fixed in the
driver environment, so commit ids are equal on both sides. Paths are reported relative to the run
root.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from s1_common import outcome, relative

FIXED = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@localhost",
         "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@localhost",
         "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
         "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return done.stdout.strip()


def world(api, root: Path, name: str):
    base = root / name
    seed = base / "seed"
    seed.mkdir(parents=True)
    git(seed, "init", "-q", "-b", "main")
    (seed / "original.txt").write_text("original", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "first")
    (seed / "second.txt").write_text("second", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "second")
    remote = base / "remote.git"
    git(base, "clone", "-q", "--bare", str(seed), str(remote))
    lane = base / "lane"
    git(base, "clone", "-q", str(remote), str(lane))

    class BareRemote(api.GitWorkspace):
        def _remote_url(self) -> str:
            return str(remote)

    workspace = BareRemote(str(lane), str(base / "workspaces"), remote="owner/repo")
    prepared = workspace.prepare("task-one", "HEAD")
    (Path(prepared["path"]) / "change.txt").write_text("reviewed change", encoding="utf-8")
    candidate = workspace.capture(prepared)
    return {"seed": seed, "remote": remote, "lane": lane, "workspace": workspace, "prepared": prepared,
            "candidate": candidate}


def external_commit(w, name="external.txt") -> str:
    other = w["seed"]
    git(other, "pull", "-q", str(w["remote"]), "main")
    (other / name).write_text("external", encoding="utf-8")
    git(other, "add", ".")
    git(other, "commit", "-q", "-m", "external " + name)
    git(other, "push", "-q", str(w["remote"]), "HEAD:refs/heads/main")
    return git(other, "rev-parse", "HEAD")


def run(api, root: Path) -> dict:
    os.environ.update(FIXED)
    out: dict = {}
    rev = "a" * 40
    rows = {
        "fast_forward": f" \t{rev}:refs/heads/main\t1111111..aaaaaaa\n",
        "up_to_date": f"=\t{rev}:refs/heads/main\t[up to date]\n",
        "stale_info": f"!\t{rev}:refs/heads/main\t[rejected] (stale info)\n",
        "fetch_first": f"!\t{rev}:refs/heads/main\t[rejected] (fetch first)\n",
        "remote_rejected_hook": f"!\t{rev}:refs/heads/main\t[remote rejected] (pre-receive hook declined)\n",
        "incorrect_old": f"!\t{rev}:refs/heads/main\t[remote rejected] (incorrect old value provided)\n",
        "remote_failure": f"!\t{rev}:refs/heads/main\t[remote failure] (remote failed to report status)\n",
        "forced": f"+\t{rev}:refs/heads/main\t1111111...aaaaaaa (forced update)\n",
        "other_ref": f" \t{rev}:refs/heads/other\t1111111..aaaaaaa\n",
        "other_revision": f" \t{'b' * 40}:refs/heads/main\t1111111..bbbbbbb\n",
        "two_lines": f" \t{rev}:refs/heads/main\tx\n \t{rev}:refs/heads/main\ty\n",
        "empty": "", "malformed": "garbage\n", "with_header": f"To remote\n \t{rev}:refs/heads/main\tok\nDone\n",
    }
    out["classify_push"] = {k: api.classify_push(v, rev) for k, v in rows.items()}
    remotes = ["owner/repo", "Owner/Repo.git", "https://github.com/Owner/Repo", "https://github.com/owner/repo.git/",
               "git@github.com:owner/repo.git", "ssh://git@github.com/owner/repo", "https://gitlab.com/o/r",
               "../relative", "", None]
    out["canonical_remote"] = [outcome(lambda r=r: api.canonical_remote(r)) for r in remotes]

    roots = {"ROOT": str(root)}
    w = world(api, root, "cas")
    ws, candidate = w["workspace"], w["candidate"]
    out["prepared"] = relative(w["prepared"], roots)
    out["candidate"] = relative(candidate, roots)
    out["prepare_refusals"] = [outcome(lambda: ws.prepare("bad/id")),
                               outcome(lambda: ws.prepare("task-one", candidate["revision"]))]
    out["prepare_again"] = relative(outcome(lambda: ws.prepare("task-one", "HEAD")), roots)
    out["inspect"] = outcome(lambda: {k: v for k, v in ws.inspect(candidate["revision"], candidate["base"]).items()})
    out["parent"] = ws.parent(candidate["revision"])
    out["target_identity"] = ws.target_identity()
    out["require_target"] = [ws.require_target(candidate), ws.require_target({k: v for k, v in candidate.items()
                                                                              if k != "repository"}),
                             outcome(lambda: ws.require_target(dict(candidate, repository="github:x/y")))]
    review = ws.review_workspace(candidate["revision"], "review-one")
    out["review_workspace"] = relative(review, roots)
    out["merge_state_unmerged"] = ws.merge_state(candidate)
    out["remote_main_before"] = ws.remote_main()
    out["merge"] = outcome(lambda: ws.merge(candidate))
    out["remote_main_after"] = git(w["remote"], "rev-parse", "refs/heads/main")
    out["lane_main_after"] = git(w["lane"], "rev-parse", "HEAD")
    out["merge_state_merged"] = ws.merge_state(candidate)
    out["merge_recovered"] = outcome(lambda: ws.merge(candidate))
    out["qualify_merged"] = [outcome(lambda: ws.qualify_merged(candidate, candidate["revision"], fetch=False)),
                             outcome(lambda: ws.qualify_merged(candidate, "not-a-sha")),
                             outcome(lambda: ws.qualify_merged(dict(candidate, tree="0" * 40), candidate["revision"],
                                                               fetch=False))]
    out["is_ancestor"] = [ws.is_ancestor(candidate["base"], candidate["revision"]),
                          ws.is_ancestor(candidate["revision"], candidate["base"])]
    out["tampered"] = [outcome(lambda: ws.merge(dict(candidate, tree="0" * 40))),
                       outcome(lambda: ws.merge(dict(candidate, diff_hash="0" * 64)))]

    moved = world(api, root, "moved")
    external = external_commit(moved)
    out["base_moved"] = {"merge_state": moved["workspace"].merge_state(moved["candidate"])["state"],
                         "merge": outcome(lambda: moved["workspace"].merge(moved["candidate"])),
                         "remote_main_unchanged": git(moved["remote"], "rev-parse", "refs/heads/main") == external}

    lost = world(api, root, "lost")
    git(lost["lane"], "push", "-q", str(lost["remote"]), lost["candidate"]["revision"] + ":refs/heads/main")
    out["lost_response_recognized"] = outcome(lambda: lost["workspace"].merge(lost["candidate"]))

    unreachable = world(api, root, "unreachable")
    unreachable["workspace"]._remote_url = lambda: str(root / "missing.git")
    out["unreachable_remote"] = relative(outcome(lambda: unreachable["workspace"].merge(unreachable["candidate"])),
                                         roots)
    out["unreachable_error_is_transport"] = out["unreachable_remote"].get("error") == "GitCommandError"
    out["unreachable_remote"].pop("message", None)

    local = world(api, root, "local")
    plain = api.GitWorkspace(str(local["lane"]), str(root / "local" / "workspaces"))
    prepared = plain.prepare("task-local", "HEAD")
    (Path(prepared["path"]) / "local.txt").write_text("local change", encoding="utf-8")
    local_candidate = plain.capture(prepared)
    out["local_candidate"] = relative(local_candidate, roots)
    out["local_merge"] = relative(outcome(lambda: plain.merge(local_candidate)), roots)
    out["local_merge_again"] = relative(outcome(lambda: plain.merge(local_candidate)), roots)
    out["publish_without_remote"] = outcome(lambda: plain.publish(local_candidate, "t", "b"))
    empty = plain.prepare("task-empty", "HEAD")
    out["capture_no_change"] = outcome(lambda: plain.capture(empty))
    secret = plain.prepare("task-secret", "HEAD")
    (Path(secret["path"]) / ".env").write_text("X=1", encoding="utf-8")
    out["capture_credential_file"] = outcome(lambda: plain.capture(secret))
    out["continue_workspace"] = [
        relative(outcome(lambda: plain.continue_workspace("task-local", "task-next", local_candidate["revision"],
                                                          local_candidate["base"])), roots),
        outcome(lambda: plain.continue_workspace("task-local", "task-next", "0" * 40, local_candidate["base"])),
        outcome(lambda: plain.continue_workspace("../x", "task-next", "0" * 40, "0" * 40))]
    return out
