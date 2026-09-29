"""Target driver: `host_os.git` on the target tree (local bare repository, no network, no `gh`)."""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s1_git  # noqa: E402
from codex_harness.host_os.adapters import git_workspace  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402

API = SimpleNamespace(GitWorkspace=git_workspace.GitWorkspace, GitCommandError=git_workspace.GitCommandError,
                      MergeRefused=git_workspace.MergeRefused, classify_push=git_workspace.classify_push,
                      canonical_remote=git_workspace.canonical_remote, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s1-git-") as raw:
        result = s1_git.run(API, Path(raw).resolve())
    driver.finish("target", "host_os.git", result)
