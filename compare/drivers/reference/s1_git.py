"""Reference driver: `host_os.git` on SOURCE M7 (local bare repository, no network, no `gh`).

M7 `adapters.git` (`GitWorkspace` prepare/capture/inspect/review/merge_state/merge with the
server-side `--force-with-lease` compare-and-swap, `classify_push`, `canonical_remote`).
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s1_git  # noqa: E402

from codex_harness.adapters import git as git_module  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(GitWorkspace=git_module.GitWorkspace, GitCommandError=git_module.GitCommandError,
                      MergeRefused=git_module.MergeRefused, classify_push=git_module.classify_push,
                      canonical_remote=git_module.canonical_remote, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s1-git-") as raw:
        result = s1_git.run(API, Path(raw).resolve())
    driver.finish("reference", "host_os.git", result)
