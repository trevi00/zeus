"""Cutover G1-11: the first `approved_rebaselines` entry (main-s2r-b9d8f15) in the compare harness.

Behavioural: each test drives the public functions of `compare/run.py` (`check_tree`, `prepare_rebaseline`, `main`)
on the real tree or on a fixture git repository. Expected results come from AMD-1 section A and the decision record
REBASELINE-MAIN-S2R, not from the implementation:
  - rule (b) of the promoted archive rule also accepts `reference/<id>/<q>` for a delta path q whose blob equals the
    entry commit's blob; a missing delta file, an extra file and a differing blob are each `foreign_reference_paths`;
  - the entry's `delta_paths` equal `git diff --name-only parent_source commit` and `commit^{tree}` equals `tree`;
  - the overlay (SOURCE archive + delta archive) must reproduce the pinned tree BEFORE any build;
  - `run --record` with a rebaseline reference is refused (goldens stay M7's).
"""

import copy
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

ENTRY_ID = "main-s2r-b9d8f15"


def _run_module():
    spec = importlib.util.spec_from_file_location("compare_run_for_rebaseline", REPO / "compare" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _baseline() -> dict:
    return json.loads((REPO / "compare" / "baseline.json").read_text(encoding="utf-8"))


# --- the real tree -------------------------------------------------------------------------------------------------

def test_the_baseline_holds_the_one_entry_and_its_archive_is_exactly_the_delta():
    entry = _baseline()["approved_rebaselines"][0]
    assert entry["id"] == ENTRY_ID and entry["archive_root"] == f"reference/{ENTRY_ID}"
    delta = subprocess.run(["git", "diff", "--name-only", entry["parent_source"], entry["commit"]], cwd=REPO,
                           check=True, capture_output=True, text=True).stdout.split()
    assert entry["delta_paths"] == sorted(delta) and len(delta) == 19
    archived = sorted(str(p.relative_to(REPO / entry["archive_root"]))
                      for p in (REPO / entry["archive_root"]).rglob("*") if p.is_file())
    assert archived == entry["delta_paths"]
    for rel in entry["delta_paths"]:
        want = subprocess.run(["git", "show", f"{entry['commit']}:{rel}"], cwd=REPO, check=True,
                              capture_output=True).stdout
        assert (REPO / entry["archive_root"] / rel).read_bytes() == want


def test_check_tree_on_the_real_tree_accepts_the_archive():
    report = _run_module().check_tree()
    assert report["ok"] is True
    assert report["foreign_reference_paths"] == [] and report["credential_shaped_strings"] == []
    (row,) = report["rebaselines"]
    assert row == {"id": ENTRY_ID, "tree_matches": True, "delta_paths_match": True,
                   "delta_paths_in_commit": True, "ok": True}


# --- rule (b) with fixture repositories ----------------------------------------------------------------------------

@pytest.fixture
def fixture(tmp_path):
    """-> (root, baseline): SOURCE commit C0, a "main" commit C1 (one file modified, one added; C1 stays an object),
    the working tree at C0 with the delta archive of C1 under `reference/rb1/` and an entry describing it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, "src/a.py", "A = 1\n")
    _write(root, "docs/x.md", "# x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "source")
    c0 = _git(root, "rev-parse", "HEAD")
    _write(root, "src/a.py", "A = 2\n")
    _write(root, "src/new.py", "N = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "main")
    c1 = _git(root, "rev-parse", "HEAD")
    _git(root, "reset", "-q", "--hard", c0)
    for rel in ("src/a.py", "src/new.py"):
        _write(root, f"reference/rb1/{rel}", "")
        (root / "reference" / "rb1" / rel).write_bytes(
            subprocess.run(["git", "show", f"{c1}:{rel}"], cwd=root, check=True, capture_output=True).stdout)
    _write(root, "reference/README.md", "the archive\n")
    entry = {"id": "rb1", "commit": c1, "tree": _git(root, "rev-parse", f"{c1}^{{tree}}"), "parent_source": c0,
             "delta_paths": ["src/a.py", "src/new.py"], "archive_root": "reference/rb1"}
    baseline = {"source": {"tree": _git(root, "rev-parse", f"{c0}^{{tree}}")},
                "layout": {"mode": "promoted", "additions_only": {}}, "approved_rebaselines": [entry]}
    return root, c0, baseline


def _check(fixture, baseline=None):
    root, c0, base = fixture
    return _run_module().check_tree(root=root, source_commit=c0, baseline=base if baseline is None else baseline)


def test_a_faithful_delta_archive_is_ok(fixture):
    report = _check(fixture)
    assert report["ok"] is True and report["foreign_reference_paths"] == []
    assert report["rebaselines"][0]["ok"] is True


def test_an_appended_byte_is_foreign(fixture):
    with (fixture[0] / "reference/rb1/src/a.py").open("ab") as handle:
        handle.write(b"\n")
    report = _check(fixture)
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/rb1/src/a.py"]


def test_an_extra_file_is_foreign(fixture):
    _write(fixture[0], "reference/rb1/src/extra.py", "X = 1\n")
    report = _check(fixture)
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/rb1/src/extra.py"]


def test_a_missing_delta_file_is_foreign(fixture):
    (fixture[0] / "reference/rb1/src/new.py").unlink()
    report = _check(fixture)
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/rb1/src/new.py"]


def test_a_file_outside_the_delta_list_is_foreign_even_when_it_is_the_commits_blob(fixture):
    root, c0, base = fixture
    narrowed = copy.deepcopy(base)
    narrowed["approved_rebaselines"][0]["delta_paths"] = ["src/a.py"]
    report = _check(fixture, narrowed)
    assert report["ok"] is False and "reference/rb1/src/new.py" in report["foreign_reference_paths"]
    assert report["rebaselines"][0]["delta_paths_match"] is False


def test_a_wrong_delta_list_is_named(fixture):
    root, c0, base = fixture
    wrong = copy.deepcopy(base)
    wrong["approved_rebaselines"][0]["delta_paths"] = ["src/a.py", "src/new.py", "docs/x.md"]
    report = _check(fixture, wrong)
    assert report["ok"] is False and report["rebaselines"][0]["delta_paths_match"] is False


def test_a_wrong_tree_is_named(fixture):
    root, c0, base = fixture
    wrong = copy.deepcopy(base)
    wrong["approved_rebaselines"][0]["tree"] = "0" * 40
    report = _check(fixture, wrong)
    assert report["ok"] is False and report["rebaselines"][0]["tree_matches"] is False


def test_a_credential_shaped_string_in_a_modified_delta_file_is_still_scanned(fixture):
    _write(fixture[0], "reference/rb1/src/a.py", "KEY = 'ghp_" + "a" * 24 + "'\n")
    report = _check(fixture)
    assert report["ok"] is False
    assert [s["path"] for s in report["credential_shaped_strings"]] == ["reference/rb1/src/a.py"]


def test_without_entries_the_report_has_no_rebaselines_key(fixture):
    root, c0, base = fixture
    bare = copy.deepcopy(base)
    bare["approved_rebaselines"] = []
    shutil.rmtree(root / "reference" / "rb1")
    report = _check(fixture, bare)
    assert report["ok"] is True and "rebaselines" not in report


# --- the overlay proof and the run selector ------------------------------------------------------------------------

def test_a_differing_overlay_is_refused_before_any_build(tmp_path):
    entry = _baseline()["approved_rebaselines"][0]
    archive_base = tmp_path / "archive"
    shutil.copytree(REPO / entry["archive_root"], archive_base / entry["archive_root"])
    swapped = "src/codex_harness/adapters/host_delivery.py"  # modified by the delta: M7's bytes differ
    (archive_base / entry["archive_root"] / swapped).write_bytes(
        subprocess.run(["git", "show", f"{entry['parent_source']}:{swapped}"], cwd=REPO, check=True,
                       capture_output=True).stdout)
    scratch = tmp_path / "scratch"
    facts = _run_module().prepare_rebaseline(ENTRY_ID, scratch=scratch, archive_base=archive_base)
    assert facts["overlay_matches_tree"] is False and facts["differing_paths"] == [swapped]
    assert "nothing was built" in facts["refused"] and facts["wheel_record_matches_baseline"] is False
    assert not list((scratch / f"rebaseline-{ENTRY_ID}" / "dist").glob("*.whl"))
    assert not (scratch / f"venv-rb-{ENTRY_ID}").exists()


def test_a_missing_archive_file_is_refused_with_its_path(tmp_path):
    entry = _baseline()["approved_rebaselines"][0]
    archive_base = tmp_path / "archive"
    shutil.copytree(REPO / entry["archive_root"], archive_base / entry["archive_root"])
    (archive_base / entry["archive_root"] / entry["delta_paths"][0]).unlink()
    facts = _run_module().prepare_rebaseline(ENTRY_ID, scratch=tmp_path / "scratch", archive_base=archive_base)
    assert facts["differing_paths"] == [entry["delta_paths"][0]] and "refused" in facts


def test_run_record_with_a_rebaseline_reference_is_refused(capsys):
    module = _run_module()
    with pytest.raises(SystemExit) as refused:
        module.main(["run", "--record", "--reference", f"rebaseline:{ENTRY_ID}"])
    assert "refused" in str(refused.value.code) and "--record" in str(refused.value.code)


def test_an_unknown_reference_selector_is_refused():
    module = _run_module()
    for bad in ("rebaseline:nope", "other", "rebaseline:"):
        with pytest.raises(SystemExit):
            module.resolve_reference(bad, False)


def test_the_selector_picks_the_rebaseline_venv_and_overlay_and_the_default_stays_m7():
    module = _run_module()
    assert module.resolve_reference("m7", True) == (module.SCRATCH / "venv-ref", module.SCRATCH / "source", None)
    venv, source, entry_id = module.resolve_reference(f"rebaseline:{ENTRY_ID}", False)
    assert (venv, source, entry_id) == (module.SCRATCH / f"venv-rb-{ENTRY_ID}",
                                        module.SCRATCH / f"rebaseline-{ENTRY_ID}" / "source", ENTRY_ID)
