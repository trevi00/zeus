"""S11 unit D: the dormant promoted-layout `check-tree` (DESIGN-s11 §20.5 archive rule) and the unchanged two-tree check.

Behavioural: each test builds a fixture git repository (a tiny SOURCE commit, then a working tree) and drives
`compare/run.py::check_tree(root, source_commit, baseline)`, the function the CLI calls with the module globals.

Expected results come from DESIGN-s11 §20.5, not from the implementation:
  (a) every SOURCE path has its SOURCE bytes at the root path or at `reference/m7/<path>` (additions-only paths aside);
  (b) every file under `reference/` is `reference/README.md` or a `reference/m7/<q>` equal to SOURCE's `<q>`;
  (c) the credential-shape scan over paths changed vs SOURCE; (d) the SOURCE tree id equals the baseline's.
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

SOURCE_FILES = {"src/a.py": "A = 1\n", "tests/test_a.py": "def test_a():\n    assert True\n",
                "docs/x.md": "# x\n", "pyproject.toml": "[project]\nname = 'm7'\n"}


def _run_module():
    spec = importlib.util.spec_from_file_location("compare_run_for_check_tree", REPO / "compare" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _baseline(source_tree: str, **layout) -> dict:
    return {"source": {"tree": source_tree}, "layout": {"additions_only": {"docs/x.md": 2}, **layout}}


@pytest.fixture
def fixture(tmp_path):
    """-> (root, source_commit, source_tree): a repository holding only the SOURCE commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for rel, text in SOURCE_FILES.items():
        _write(root, rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "source")
    return root, _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")


def _promote(root: Path) -> None:
    """A correct promotion in the working tree: src/tests archived, the replaced pyproject archived, a new target
    `src`/`tests`/`pyproject.toml` at the root, one allowed docs line added."""
    for rel in ("src/a.py", "tests/test_a.py"):
        _write(root, "reference/m7/" + rel, SOURCE_FILES[rel])
        (root / rel).unlink()
    _write(root, "reference/m7/pyproject.toml", SOURCE_FILES["pyproject.toml"])
    _write(root, "pyproject.toml", "[project]\nname = 'zeus'\n")
    _write(root, "src/b.py", "B = 2\n")
    _write(root, "tests/test_b.py", "def test_b():\n    assert True\n")
    _write(root, "reference/README.md", "the archive\n")
    _write(root, "docs/x.md", SOURCE_FILES["docs/x.md"] + "a pointer line\n")


def _check(fixture, promoted_mode=True):
    root, commit, tree = fixture
    layout = {"mode": "promoted"} if promoted_mode else {"allowed_changed_paths": ["target/"]}
    return _run_module().check_tree(root=root, source_commit=commit, baseline=_baseline(tree, **layout))


def test_a_correct_promotion_is_ok(fixture):
    _promote(fixture[0])
    report = _check(fixture)
    assert report["ok"] is True
    assert report["missing_source_paths"] == [] and report["foreign_reference_paths"] == []
    assert report["credential_shaped_strings"] == []
    assert report["additions_only"]["docs/x.md"] == {"added": 1, "deleted": 0, "ok": True}
    assert report["source_tree_matches_baseline"] is True


def test_a_tracked_archive_after_a_commit_is_still_ok(fixture):
    """The working tree decides, not the index: staged and committed promotions give the same verdict."""
    root = fixture[0]
    _promote(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "promoted")
    assert _check(fixture)["ok"] is True


def test_a_source_file_in_neither_place_is_missing(fixture):
    root = fixture[0]
    _promote(root)
    (root / "reference/m7/tests/test_a.py").unlink()
    report = _check(fixture)
    assert report["ok"] is False
    assert report["missing_source_paths"] == ["tests/test_a.py"] and report["missing_source_paths_count"] == 1
    assert report["foreign_reference_paths"] == []


def test_a_root_file_replaced_without_an_archive_copy_is_missing(fixture):
    root = fixture[0]
    _promote(root)
    (root / "reference/m7/pyproject.toml").unlink()
    report = _check(fixture)
    assert report["ok"] is False and report["missing_source_paths"] == ["pyproject.toml"]


def test_an_archived_file_that_was_modified_is_foreign_and_leaves_its_source_path_missing(fixture):
    root = fixture[0]
    _promote(root)
    _write(root, "reference/m7/src/a.py", "A = 99\n")
    report = _check(fixture)
    assert report["ok"] is False
    assert report["foreign_reference_paths"] == ["reference/m7/src/a.py"]
    assert report["missing_source_paths"] == ["src/a.py"]


def test_a_foreign_file_under_the_archive_or_reference_is_refused(fixture):
    root = fixture[0]
    _promote(root)
    _write(root, "reference/m7/extra.py", "X = 1\n")
    _write(root, "reference/notes.md", "not allowed\n")
    report = _check(fixture)
    assert report["ok"] is False
    assert report["foreign_reference_paths"] == ["reference/m7/extra.py", "reference/notes.md"]
    assert report["foreign_reference_paths_count"] == 2 and report["missing_source_paths"] == []


def test_an_additions_only_path_over_its_limit_is_refused(fixture):
    root = fixture[0]
    _promote(root)
    _write(root, "docs/x.md", SOURCE_FILES["docs/x.md"] + "one\ntwo\nthree\n")
    report = _check(fixture)
    assert report["ok"] is False
    assert report["additions_only"]["docs/x.md"] == {"added": 3, "deleted": 0, "ok": False}
    assert report["missing_source_paths"] == []


def test_a_deletion_in_an_additions_only_path_is_refused(fixture):
    root = fixture[0]
    _promote(root)
    _write(root, "docs/x.md", "# changed\n")
    report = _check(fixture)
    assert report["ok"] is False and report["additions_only"]["docs/x.md"]["deleted"] == 1


def test_a_credential_shaped_string_in_a_changed_path_is_refused(fixture):
    root = fixture[0]
    _promote(root)
    _write(root, "src/b.py", "TOKEN = '" + "gh" + "p_" + "A" * 24 + "'\n")  # built at runtime: this file is scanned too
    report = _check(fixture)
    assert report["ok"] is False
    assert [item["path"] for item in report["credential_shaped_strings"]] == ["src/b.py"]


def test_a_source_tree_id_that_differs_from_the_baseline_is_refused(fixture):
    root, commit, _ = fixture
    _promote(root)
    report = _run_module().check_tree(root=root, source_commit=commit,
                                      baseline=_baseline("0" * 40, mode="promoted"))
    assert report["ok"] is False and report["source_tree_matches_baseline"] is False


def test_the_missing_list_is_bounded_and_its_count_is_exact(fixture):
    root = fixture[0]
    _promote(root)
    for n in range(80):
        _write(root, f"gone/f{n:02d}.txt", "x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "more source")
    commit, tree = _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")
    shutil.rmtree(root / "gone")
    report = _run_module().check_tree(root=root, source_commit=commit, baseline=_baseline(tree, mode="promoted"))
    assert report["ok"] is False and report["missing_source_paths_count"] == 80
    assert len(report["missing_source_paths"]) < 80 and report["missing_source_paths"][0] == "gone/f00.txt"


def test_an_unknown_layout_mode_is_refused(fixture):
    root, commit, tree = fixture
    with pytest.raises(ValueError):
        _run_module().check_tree(root=root, source_commit=commit, baseline=_baseline(tree, mode="sideways"))


def test_two_tree_mode_is_todays_check_on_the_same_fixture(fixture):
    root = fixture[0]
    _write(root, "target/x.py", "X = 1\n")  # an allowed path only
    report = _check(fixture, promoted_mode=False)
    assert report["ok"] is True and report["reference_paths_unchanged"] is True
    assert report["changed_outside_allowed"] == [] and "mode" not in report
    assert set(report) == {"source_commit", "source_tree", "source_tree_matches_baseline", "reference_paths_unchanged",
                           "changed_paths", "changed_outside_allowed", "credential_shaped_strings", "additions_only",
                           "ok"}


def test_two_tree_mode_refuses_a_promoted_tree(fixture):
    """The promoted working tree moved SOURCE paths out of place: today's rule (reference bytes unchanged) refuses it."""
    _promote(fixture[0])
    report = _check(fixture, promoted_mode=False)
    assert report["ok"] is False and report["reference_paths_unchanged"] is False
    assert "src/b.py" in report["changed_outside_allowed"]
