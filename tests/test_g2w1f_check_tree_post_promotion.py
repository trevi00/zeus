"""G2-W1 follow-up D: the post-promotion `check-tree` mode (DESIGN-s11 §20.5 post-promotion amendment, Codex ruling
FLEET-G2W1F-RULINGS D): rule (a) evaluated at the pinned promotion commit P, two additions-only classes, and the
append-only prefix proof for the ongoing log.

Behavioural: each test builds a fixture git repository (a SOURCE commit, a P commit holding the archive and the
allowance lines, then post-P commits and working-tree edits) and drives `compare/run.py::check_tree`.

Expected results come from the Codex ruling's acceptance list, not from the implementation.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

LOG = "LOG.md"
SOURCE_FILES = {"src/a.py": "A = 1\n", "docs/x.md": "# x\nl1\nl2\n", "deploy/r.md": "deploy\n", LOG: "h\n"}


def _run_module():
    spec = importlib.util.spec_from_file_location("compare_run_for_post_promotion", REPO / "compare" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _promote(root: Path, lose=(), docs_lines="pointer\n", docs_text=None, rebaseline=False) -> None:
    """The promotion edits: src/a.py archived, a new target file, one allowance line, one P-era log line."""
    _write(root, "reference/m7/src/a.py", SOURCE_FILES["src/a.py"])
    (root / "src/a.py").unlink()
    _write(root, "src/b.py", "B = 2\n")
    _write(root, "reference/README.md", "the archive\n")
    _write(root, "docs/x.md", docs_text or SOURCE_FILES["docs/x.md"] + docs_lines)
    _write(root, LOG, SOURCE_FILES[LOG] + "p1\n")
    for rel in lose:
        (root / rel).unlink()
    if rebaseline:
        _write(root, "reference/rb1/deploy/r.md", "rebased\n")


class Repo:
    def __init__(self, root: Path, source: str, tree: str, promotion: str, main: str, entry=None):
        self.root, self.source, self.tree, self.promotion, self.main, self.entry = root, source, tree, promotion, main, entry

    def baseline(self, **layout) -> dict:
        base_layout = {"mode": "promoted", "promotion_commit": self.promotion,
                       "promotion_allowances": {"docs/x.md": 1}, "append_only": {LOG: 10}, **layout}
        base_layout = {k: v for k, v in base_layout.items() if v is not None}
        return {"source": {"tree": self.tree}, "layout": base_layout,
                **({"approved_rebaselines": [self.entry]} if self.entry else {})}

    def check(self, **layout) -> dict:
        return _run_module().check_tree(root=self.root, source_commit=self.source, baseline=self.baseline(**layout))

    def log(self) -> dict:
        return self.check()["append_only"][LOG]


def _build(tmp_path, extra_source=(), lose=(), docs_lines="pointer\n", docs_text=None, rebaseline=False,
           side_p=False) -> Repo:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    files = {**SOURCE_FILES, **{f"many/f{n:02d}.txt": f"{n}\n" for n in extra_source}}
    for rel, text in files.items():
        _write(root, rel, text)
    source = _commit(root, "source")
    tree = _git(root, "rev-parse", f"{source}^{{tree}}")
    main = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    entry = None
    if rebaseline:
        _git(root, "checkout", "-q", "-b", "rb")
        _write(root, "deploy/r.md", "rebased\n")
        c1 = _commit(root, "rebaseline")
        _git(root, "checkout", "-q", main)
        entry = {"id": "rb1", "commit": c1, "tree": _git(root, "rev-parse", f"{c1}^{{tree}}"), "parent_source": source,
                 "delta_paths": ["deploy/r.md"], "archive_root": "reference/rb1"}
    pinned = None
    if side_p:  # the same valid edits on a commit that is not an ancestor of HEAD
        _git(root, "checkout", "-q", "-b", "side")
        _promote(root, lose, docs_lines, docs_text, rebaseline)
        pinned = _commit(root, "side promotion")
        _git(root, "checkout", "-q", main)
        _git(root, "clean", "-fdq")
        _git(root, "checkout", "-q", "--", ".")
    _promote(root, lose, docs_lines, docs_text, rebaseline)
    promotion = _commit(root, "promotion")
    return Repo(root, source, tree, pinned or promotion, main, entry)


@pytest.fixture
def repo(tmp_path):
    return _build(tmp_path)


def test_a_valid_promotion_with_an_unchanged_archive_is_ok(repo):
    report = repo.check()
    assert report["ok"] is True
    assert report["promotion_commit"] == repo.promotion
    assert report["promotion_commit_resolves"] is True and report["promotion_commit_is_ancestor"] is True
    assert report["missing_source_paths"] == [] and report["missing_source_paths_count"] == 0
    assert report["missing_archive_paths"] == [] and report["missing_archive_paths_count"] == 0
    assert report["promotion_allowances"] == {"docs/x.md": {"added": 1, "deleted": 0, "ok": True}}
    assert report["append_only"][LOG] == {"added": 1, "deleted": 0, "prefix_ok": True, "prefix_violations": [],
                                         "prefix_violations_count": 0, "ok": True}
    assert "additions_only" not in report


def test_a_post_promotion_edit_of_a_root_only_source_path_is_ok(repo):
    _write(repo.root, "deploy/r.md", "deploy\nedited later\n")
    _commit(repo.root, "edit")
    report = repo.check()
    assert report["ok"] is True and report["missing_source_paths_count"] == 0


def test_a_post_promotion_deletion_of_a_root_only_source_path_is_ok(repo):
    (repo.root / "deploy/r.md").unlink()
    _commit(repo.root, "delete")
    assert repo.check()["ok"] is True
    (repo.root / "docs/x.md").unlink()  # an uncommitted deletion too: the working tree plays no part in rule (a)
    assert repo.check()["ok"] is True


def test_a_promotion_that_lacks_a_source_blob_is_missing_and_not_ok(tmp_path):
    repo = _build(tmp_path, lose=["deploy/r.md"])
    report = repo.check()
    assert report["ok"] is False
    assert report["missing_source_paths"] == ["deploy/r.md"] and report["missing_source_paths_count"] == 1


def test_the_whole_source_inventory_is_checked_at_the_promotion(tmp_path):
    repo = _build(tmp_path, extra_source=range(60), lose=["many/f37.txt"])
    report = repo.check()
    assert report["ok"] is False
    assert report["missing_source_paths"] == ["many/f37.txt"] and report["missing_source_paths_count"] == 1


def test_an_unresolved_promotion_commit_is_not_ok(repo):
    report = repo.check(promotion_commit="0" * 40)
    assert report["ok"] is False
    assert report["promotion_commit_resolves"] is False and report["promotion_commit_is_ancestor"] is False


def test_a_non_ancestor_promotion_commit_is_not_ok_although_its_content_is_valid(tmp_path):
    repo = _build(tmp_path, side_p=True)
    assert repo.promotion != _git(repo.root, "rev-parse", "HEAD")
    report = repo.check()
    assert report["ok"] is False
    assert report["promotion_commit_resolves"] is True and report["promotion_commit_is_ancestor"] is False
    assert report["missing_source_paths"] is None  # not evaluated, never a pass


def test_an_invalid_promotion_commit_leaves_the_proofs_not_evaluated_without_an_exception(repo):
    _write(repo.root, LOG, _read(repo.root, LOG) + "later\n")
    _commit(repo.root, "later")
    report = repo.check(promotion_commit="not-a-commit")
    assert report["ok"] is False
    assert report["missing_source_paths"] is None and report["missing_source_paths_count"] is None
    assert report["missing_archive_paths"] is None and report["missing_archive_paths_count"] is None
    assert report["promotion_allowances"] is None
    entry = report["append_only"][LOG]
    assert entry["prefix_ok"] is None and entry["ok"] is False
    assert entry["added"] == 2 and entry["deleted"] == 0 and entry["prefix_violations"] == []


def test_an_allowance_over_its_cap_at_the_promotion_stays_refused_after_a_later_revert(tmp_path):
    repo = _build(tmp_path, docs_lines="one\ntwo\n")
    assert repo.check()["ok"] is False
    _write(repo.root, "docs/x.md", SOURCE_FILES["docs/x.md"])
    _commit(repo.root, "revert")
    report = repo.check()
    assert report["ok"] is False
    assert report["promotion_allowances"]["docs/x.md"] == {"added": 2, "deleted": 0, "ok": False}


def test_an_allowance_deletion_at_the_promotion_stays_refused_after_a_later_repair(tmp_path):
    repo = _build(tmp_path, docs_text="# x\nl2\npointer\n")  # P deletes the SOURCE line l1
    _write(repo.root, "docs/x.md", SOURCE_FILES["docs/x.md"] + "pointer\n")
    _commit(repo.root, "repair")
    report = repo.check()
    assert report["ok"] is False
    assert report["promotion_allowances"]["docs/x.md"] == {"added": 1, "deleted": 1, "ok": False}


def test_a_permitted_post_promotion_change_to_an_allowance_document_is_not_refused(repo):
    _write(repo.root, "docs/x.md", "# x\nl2\npointer\n")  # a SOURCE line (l1) deleted after P
    _commit(repo.root, "later edit")
    report = repo.check()
    assert report["ok"] is True
    assert report["promotion_allowances"]["docs/x.md"] == {"added": 1, "deleted": 0, "ok": True}


def test_b2_additions_totalling_the_cap_pass_and_the_eleventh_fails(repo):
    _write(repo.root, LOG, _read(repo.root, LOG) + "".join(f"a{n}\n" for n in range(9)))  # p1 + 9 = 10
    _commit(repo.root, "nine more")
    assert repo.log()["ok"] is True and repo.log()["added"] == 10
    _write(repo.root, LOG, _read(repo.root, LOG) + "a9\n")
    _commit(repo.root, "the eleventh")
    report = repo.log()
    assert report["added"] == 11 and report["ok"] is False and report["prefix_ok"] is True


def test_b2_deleting_a_promotion_era_line_fails(repo):
    _write(repo.root, LOG, SOURCE_FILES[LOG])
    commit = _commit(repo.root, "drop p1")
    report = repo.log()
    assert report["added"] == 0 and report["deleted"] == 0  # the SOURCE numstat alone is clean
    assert report["prefix_ok"] is False and report["prefix_violations"] == [commit] and report["ok"] is False


def test_b2_a_line_appended_then_rewritten_in_a_successor_fails(repo):
    _write(repo.root, LOG, _read(repo.root, LOG) + "L1\n")
    _commit(repo.root, "c1")
    _write(repo.root, LOG, SOURCE_FILES[LOG] + "p1\nL1x\n")
    c2 = _commit(repo.root, "c2")
    report = repo.log()
    assert report["added"] == 2 and report["deleted"] == 0
    assert report["prefix_ok"] is False and report["prefix_violations"] == [c2] and repo.check()["ok"] is False


def test_b2_a_line_appended_then_deleted_in_a_successor_fails(repo):
    _write(repo.root, LOG, _read(repo.root, LOG) + "L1\n")
    _commit(repo.root, "c1")
    _write(repo.root, LOG, SOURCE_FILES[LOG] + "p1\n")
    c2 = _commit(repo.root, "c2")
    report = repo.log()
    assert report["prefix_violations"] == [c2] and report["ok"] is False


def test_b2_deleting_the_log_file_in_a_commit_fails(repo):
    (repo.root / LOG).unlink()
    commit = _commit(repo.root, "remove the log")
    report = repo.log()
    assert report["prefix_violations"] == [commit] and report["ok"] is False


def test_b2_a_head_to_working_tree_rewrite_fails(repo):
    _write(repo.root, LOG, SOURCE_FILES[LOG] + "q1\n")  # uncommitted: p1 rewritten as q1
    report = repo.log()
    assert report["prefix_violations"] == ["working-tree"] and report["ok"] is False
    (repo.root / LOG).unlink()
    assert repo.log()["prefix_violations"] == ["working-tree"]


def test_b2_an_unchanged_successor_passes(repo):
    _write(repo.root, "deploy/r.md", "later\n")
    _commit(repo.root, "successor")
    _write(repo.root, LOG, _read(repo.root, LOG) + "uncommitted append\n")
    assert repo.log()["ok"] is True and repo.check()["ok"] is True


def test_an_edit_under_the_archive_still_fails_rule_b(repo):
    _write(repo.root, "reference/m7/src/a.py", "A = 99\n")
    _commit(repo.root, "edit the archive")
    report = repo.check()
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/m7/src/a.py"]


def test_foreign_archive_content_still_fails_rule_b(repo):
    _write(repo.root, "reference/m7/extra.py", "X = 1\n")
    _commit(repo.root, "foreign")
    report = repo.check()
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/m7/extra.py"]


def test_a_credential_shaped_string_in_a_post_promotion_changed_root_file_still_fails_rule_c(repo):
    _write(repo.root, "src/b.py", "TOKEN = '" + "gh" + "p_" + "A" * 24 + "'\n")  # built at runtime: this file is scanned
    _commit(repo.root, "secret")
    report = repo.check()
    assert report["ok"] is False
    assert [item["path"] for item in report["credential_shaped_strings"]] == ["src/b.py"]


def test_a_source_tree_mismatch_still_fails_rule_d(repo):
    repo.tree = "0" * 40
    report = repo.check()
    assert report["ok"] is False and report["source_tree_matches_baseline"] is False


@pytest.mark.parametrize("layout", [{"additions_only": {LOG: 10}}, {"promotion_allowances": None},
                                    {"append_only": None}])
def test_a_layout_with_a_promotion_commit_and_a_wrong_map_set_is_a_configuration_error(repo, layout):
    with pytest.raises(ValueError):
        repo.check(**layout)


def test_a_post_promotion_removal_of_an_archived_file_is_missing_archive_content(repo):
    (repo.root / "reference/m7/src/a.py").unlink()
    _commit(repo.root, "remove the archive file")
    report = repo.check()
    assert report["ok"] is False
    assert report["missing_archive_paths"] == ["reference/m7/src/a.py"] and report["missing_archive_paths_count"] == 1
    assert report["missing_source_paths_count"] == 0


def test_a_post_promotion_edit_of_an_archived_file_is_not_ok(repo):
    _write(repo.root, "reference/m7/src/a.py", "A = 2\n")
    _commit(repo.root, "edit the archive file")
    report = repo.check()
    assert report["ok"] is False and report["missing_archive_paths"] == ["reference/m7/src/a.py"]


def test_the_promotion_mode_still_checks_an_approved_rebaseline_archive(tmp_path):
    repo = _build(tmp_path, rebaseline=True)
    assert repo.check()["ok"] is True
    _write(repo.root, "reference/rb1/deploy/r.md", "tampered\n")
    _commit(repo.root, "edit the delta archive")
    edited = repo.check()
    assert edited["ok"] is False and edited["foreign_reference_paths"] == ["reference/rb1/deploy/r.md"]
    (repo.root / "reference/rb1/deploy/r.md").unlink()
    _commit(repo.root, "remove the delta archive")
    removed = repo.check()
    assert removed["ok"] is False and removed["foreign_reference_paths"] == ["reference/rb1/deploy/r.md"]


def test_a_merge_checks_every_changed_parent_edge_of_a_side_branch_rewrite(repo):
    root, main = repo.root, repo.main
    _write(root, "deploy/r.md", "m0\n")
    _commit(root, "m0")
    _git(root, "checkout", "-q", "-b", "side")
    _write(root, LOG, _read(root, LOG) + "L1\n")
    _commit(root, "c1")
    _write(root, LOG, SOURCE_FILES[LOG] + "p1\nL1x\n")
    c2 = _commit(root, "c2")
    _git(root, "checkout", "-q", main)
    _write(root, "deploy/r.md", "m1\n")
    _commit(root, "m1")
    _git(root, "merge", "--no-ff", "-q", "-m", "merge", "side")
    report = repo.log()
    assert report["ok"] is False and report["prefix_violations"] == [c2]


def test_a_merge_resolution_that_rewrites_a_side_branch_line_is_refused(repo):
    root, main = repo.root, repo.main
    _git(root, "checkout", "-q", "-b", "side")
    _write(root, LOG, _read(root, LOG) + "L1\n")
    _commit(root, "c1")
    _git(root, "checkout", "-q", main)
    _write(root, "deploy/r.md", "m1\n")
    _commit(root, "m1")
    _git(root, "merge", "--no-ff", "--no-commit", "-q", "side")
    _write(root, LOG, SOURCE_FILES[LOG] + "p1\nL1x\n")
    merge = _commit(root, "merge with a rewrite")
    report = repo.log()
    assert report["ok"] is False and report["prefix_violations"] == [merge]


def test_a_merge_with_a_parent_that_is_not_a_descendant_of_the_promotion_and_an_unchanged_log_is_ok(repo):
    root, main = repo.root, repo.main
    _git(root, "checkout", "-q", "-b", "old", repo.source)
    _write(root, "z.txt", "z\n")
    _commit(root, "old side")
    _git(root, "checkout", "-q", main)
    _git(root, "merge", "--no-ff", "-q", "-m", "merge old", "old")
    assert repo.log()["ok"] is True and repo.check()["ok"] is True
