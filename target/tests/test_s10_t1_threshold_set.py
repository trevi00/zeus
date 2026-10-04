"""S10 unit T1: the threshold set (`entry.cli.threshold_proposals`, `composition.thresholds`, `research.adapters.threshold_policy`
and `threshold_reviews`), DESIGN-s8 section 18 (V20) and section 26 (V27).

The policy binding runs over a REAL temporary Git repository built from the 32 target files at `target/src/`; the proposal main runs over a
`MemoryStore`, the real `ThresholdProposals` and a monkeypatched `composition.thresholds.current_policy`; `review_threshold` is checked for
the V22 ports it hands to `ThresholdReviews`.
"""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.entry.cli import threshold_proposals
from codex_harness.host_os.adapters.git_workspace import GitWorkspace
from codex_harness.kernel.errors import ContractError
from codex_harness.research.adapters import threshold_policy, threshold_reviews
from codex_harness.research.adapters.runtime_thresholds import effective_policy
from codex_harness.storage.adapters.memory_store import MemoryStore

PACKAGE = Path(threshold_policy.__file__).resolve().parents[2]
REPO = PACKAGE.parents[2]
PROJECT_ID = "2f6f5f64-8d3c-4c6e-9b1e-1f0a5f3e7a11"


def test_policy_paths_are_the_32_target_files():
    paths = threshold_policy.POLICY_PATHS
    assert len(paths) == 32 and len(set(paths)) == 32
    for entry in paths:
        assert entry.startswith("codex_harness/")
        assert (PACKAGE.parent / entry).is_file(), entry


def test_policy_paths_are_tracked_at_head():
    tracked = set(subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n"))
    for entry in threshold_policy.POLICY_PATHS:
        assert threshold_policy.GIT_PREFIX + entry in tracked, entry


@pytest.fixture
def policy_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    git._git("init", "-q")
    git._git("config", "user.name", "Fixture")
    git._git("config", "user.email", "fixture@localhost")
    for entry in threshold_policy.POLICY_PATHS:
        target = root / (threshold_policy.GIT_PREFIX + entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PACKAGE.parent / entry, target)
    git._git("add", ".")
    git._git("commit", "-qm", "policy fixture")
    return root, git


def test_current_policy_binds_the_loaded_values_to_the_committed_sources(policy_repo):
    _, git = policy_repo
    policy = threshold_policy.current_policy(git)
    assert policy["values"] == effective_policy()["values"] == {"skill_match.FULL_BODY_MIN_SCORE": 3}
    assert policy["kind"] == "current_native_git_policy"
    assert policy["encoding"] == "UTF-8 text with normalized newlines"
    assert policy["revision"] == git._git("rev-parse", "HEAD")
    assert list(policy["sources"]) == list(threshold_policy.POLICY_PATHS)
    for entry, source in policy["sources"].items():
        assert source["text"] == (PACKAGE.parent / entry).read_text(encoding="utf-8")


def test_an_edited_loaded_source_differs_from_the_selected_revision(policy_repo, tmp_path, monkeypatch):
    _, git = policy_repo
    loaded = tmp_path / "loaded"
    for entry in threshold_policy.POLICY_PATHS:
        (loaded / entry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PACKAGE.parent / entry, loaded / entry)
    edited = loaded / threshold_policy.POLICY_PATHS[0]
    edited.write_text(edited.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    # `current_policy` climbs `parents[3]` from its own file to the root holding `codex_harness/`
    monkeypatch.setattr(threshold_policy, "__file__", str(loaded / "codex_harness/research/adapters/threshold_policy.py"))
    with pytest.raises(ContractError, match="Loaded threshold source differs from selected Git revision"):
        threshold_policy.current_policy(git)


def test_a_missing_source_is_refused(policy_repo):
    root, git = policy_repo
    git._git("rm", "-q", threshold_policy.GIT_PREFIX + threshold_policy.POLICY_PATHS[0])
    git._git("commit", "-qm", "drop a source")
    with pytest.raises(ContractError, match="Missing regular policy source"):
        threshold_policy.current_policy(git)


def test_a_revision_starting_with_a_dash_is_refused(policy_repo):
    _, git = policy_repo
    with pytest.raises(ContractError, match="Invalid policy revision"):
        threshold_policy.current_policy(git, "-x")


def fake_policy():
    return {"revision": "a" * 40, "values": effective_policy()["values"], "sources": {},
            "kind": "current_native_git_policy", "encoding": "UTF-8 text with normalized newlines"}


def events():  # the M7 `test_threshold_collection.events` shape
    return [{"at": f"2026-01-01T00:00:{i:02d}Z", "top": [{"score": score, "body_chars": 500} for score in [3, 5]]} for i in range(40)]


def run_main(monkeypatch, tmp_path, *extra, store=None):
    from codex_harness.composition import thresholds

    monkeypatch.setattr(thresholds, "current_policy", lambda git, revision="HEAD": fake_policy())
    return threshold_proposals.main(["--project-id", PROJECT_ID, "--harness-repo", str(tmp_path), "--artifacts", str(tmp_path / "artifacts"), *extra],
                                    store=store)


def test_main_archives_a_run_and_prints_one_json_line(monkeypatch, tmp_path, capsys):
    store = MemoryStore()
    with store.transaction() as tx:
        from codex_harness.composition import thresholds
        profile = thresholds.project_identity({"project_id": PROJECT_ID}, SimpleNamespace(remote=None))
        from codex_harness.kernel.ids import digest
        tx.put("skill_history", digest(profile), {"events": events()})
    assert run_main(monkeypatch, tmp_path, store=store) == 0
    out = capsys.readouterr()
    run = json.loads(out.out)
    assert out.out.count("\n") == 1 and run["proposals"]
    assert out.err == ""


def test_main_maps_a_contract_error_to_exit_2(monkeypatch, tmp_path, capsys):
    assert run_main(monkeypatch, tmp_path, "--min-sample", "0", store=MemoryStore()) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "Invalid or stale proposal input"}


def test_main_maps_any_other_error_to_exit_1(monkeypatch, tmp_path, capsys):
    class Broken:
        def transaction(self):
            raise OSError("down")

    assert run_main(monkeypatch, tmp_path, store=Broken()) == 1
    assert json.loads(capsys.readouterr().err) == {"error": "Proposal calculation unavailable", "type": "OSError"}


def test_review_threshold_hands_the_v22_ports_to_threshold_reviews(monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    class Recorder:
        def __init__(self, workflow, artifacts, **ports):
            seen.update(workflow=workflow, artifacts=artifacts, ports=ports)
            raise Stop

    monkeypatch.setattr(threshold_reviews, "ThresholdReviews", Recorder)
    validation, decisions = object(), object()
    executor = SimpleNamespace(workflow="workflow", artifacts="artifacts")
    with pytest.raises(Stop):
        threshold_reviews.review_threshold(executor, {}, {}, decision_validation=validation, decisions=decisions)
    assert seen == {"workflow": "workflow", "artifacts": "artifacts",
                    "ports": {"decision_validation": validation, "decisions": decisions}}
    with pytest.raises(TypeError):
        threshold_reviews.review_threshold(executor, {}, {}, validation, decisions)
