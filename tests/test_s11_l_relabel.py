"""S11 unit L: the maintained-ledger relabel (`coverage/relabel.py`, DESIGN-s11 §5 R-L1..R-L16).

Synthetic trees and bundles (built in `tmp_path`, never a real owner artifact) carry a negative control for each rule:
a skipped, xfail or teardown-error node is not passing; an unmatched testcase, an uncollected node, a duplicate node,
a compare report that is not ok and an unreadable owner-run artifact refuse the bundle; a missing evidence file is
unmet; `pending:` blocks `verified`; `module:` inherits; a bucket in two OWNED_BUCKETS is not verified; an unaccepted
slice is not verified; a changed evidence test module, conftest or `target/src` make the bundle stale and a new
unrelated test module does not. The last tests pin the committed ledger to the committed bundle (R-L12, R-L13).
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from _layout import REPO as ROOT
from _layout import TARGET_PREFIX as TP

sys.path.insert(0, str(ROOT / "coverage"))
try:
    import relabel
finally:
    sys.path.remove(str(ROOT / "coverage"))

HEAD = "a" * 40


# ------------------------------------------------------------------------------------------------ synthetic tree

def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


ARCH = """## Capabilities

| Capability | Label | Domain / use case | Port | Adapter / entry | Contracts | Tests |
|---|---|---|---|---|---|---|
| cap_a | TARGET | `codex_harness.research.mod:Thing` | `codex_harness.research.ports` |  | INV-X-001 | `target/tests/test_a.py` |
| cap_b | TARGET | `codex_harness.research.mod:Thing` | `codex_harness.research.ports` |  | INV-X-001 | `target/tests/test_a.py` |
| cap_b | PROPOSED | `codex_harness.research.later` |  |  |  | pending (S8) |

## Bucket ownership
"""
ARCH = ARCH.replace("`target/", "`" + TP)  # S11 unit P: the fixture follows the layout


def make_tree(root: Path) -> None:
    write(root, TP + "src/codex_harness/__init__.py")
    write(root, TP + "src/codex_harness/research/__init__.py")
    write(root, TP + "src/codex_harness/research/mod.py", "class Thing:\n    def go(self):\n        pass\n\nCONST = 1\n")
    write(root, TP + "src/codex_harness/research/ports.py", 'OWNED_BUCKETS = ("alpha", "beta")\n')
    write(root, TP + "src/codex_harness/coordination/__init__.py")
    write(root, TP + "src/codex_harness/coordination/ports.py", 'OWNED_BUCKETS = ("beta", "gamma")\n')
    write(root, TP + "pyproject.toml", '[project.scripts]\nharness = "codex_harness.research.mod:Thing"\n')
    write(root, TP + "uv.lock", "lock\n")
    write(root, "docs/contracts.md", "| ID | C |\n|---|---|\n| INV-X-001 | a |\n| INV-Y-001 | b |\n")
    write(root, "docs/context/ARCHITECTURE.md", ARCH)
    write(root, "compare/scenarios/fam.json", json.dumps({"family": "fam", "target_driver": "drivers/fam.py"}))
    write(root, "compare/scenarios/nodrv.json", json.dumps({"family": "nodrv", "target_driver": None}))
    write(root, TP + "tests/conftest.py", "# conftest\n")
    write(root, TP + "tests/test_a.py",
          '"""Cites INV-X-001 at module level only in this docstring."""\n\n\ndef test_one():\n    pass\n\n\n'
          'def test_two():\n    # INV-Y-001 is cited only here\n    pass\n')
    write(root, TP + "tests/test_b.py", "def test_other():\n    pass\n")
    write(root, TP + "tests/ported/test_old.py", "def test_p():\n    pass\n")
    write(root, TP + "tests/test_architecture.py", "def test_target_tree_has_no_violation_and_no_exception():\n    pass\n")


NODES = ["tests/test_a.py::test_one", "tests/test_a.py::test_two", "tests/test_b.py::test_other",
         "tests/ported/test_old.py::test_p", relabel.SINGLE_WRITER_NODE]


def bundle_for(not_passed=None, compare=None, owner_run=None, nodes=None):
    return {"schema": relabel.BUNDLE_SCHEMA, "head": HEAD, "ids": {}, "support": {}, "test_modules": {},
            "nodes": sorted(nodes or NODES), "not_passed": dict(not_passed or {}),
            "compare": compare if compare is not None else {
                "fam": {"target": "equal", "reference": "equal", "origin_ok": True, "target_origin_ok": True}},
            "owner_run": dict(owner_run or {}), "inputs": {}}


def row(kind="public_api", key="api:x.py::f", evidence=("target:tests/test_b.py",), symbol=("codex_harness.research.mod:Thing",),
        owner="research", slice_=None, status="designed", intent="preserve", **more):
    r = {"key": key, "kind": kind, "evidence": list(evidence), "target_symbol": list(symbol), "target_owner": owner,
         "status": status, "intent": intent, **more}
    if slice_:
        r["slice"] = slice_
    return r


def has_unmet(r, prefix):
    return any(u.startswith(prefix) for u in r["verification"]["unmet"])


def run(rows, root, bundle=None):
    ledger = {"rows": rows}
    new, engine = relabel.relabel(ledger, bundle or bundle_for(), root)
    return {r["key"]: r for r in new["rows"]}, engine


@pytest.fixture()
def tree(tmp_path):
    make_tree(tmp_path)
    return tmp_path


# --------------------------------------------------------------------------------------------- node mapping (L3)

def test_the_junit_mangling_maps_nodes_to_classname_and_name():
    assert relabel.mangle("tests/ported/test_x.py::test_f") == ("tests.ported.test_x", "test_f")
    assert relabel.mangle("tests/test_x.py::TestC::test_m[a::b-1]") == ("tests.test_x.TestC", "test_m[a::b-1]")


def junit(tmp_path, *cases, name="j.xml"):
    body = "".join(f'<testcase classname="{c}" name="{n}" time="0.0">{child}</testcase>' for c, n, child in cases)
    path = tmp_path / name
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite></testsuites>',
                    encoding="utf-8")
    return path


def test_a_skipped_an_xfail_and_a_teardown_error_duplicate_are_not_passing(tmp_path):
    path = junit(tmp_path,
                 ("tests.t", "test_pass", ""),
                 ("tests.t", "test_skip", '<skipped type="pytest.skip" message="x"/>'),
                 ("tests.t", "test_xfail", '<skipped type="pytest.xfail" message="x"/>'),
                 ("tests.t", "test_td", ""), ("tests.t", "test_td", '<error message="teardown"/>'),
                 ("tests.t", "test_fail", '<failure message="f"/>'))
    out = relabel.read_junit(path)
    assert out[("tests.t", "test_pass")] == "passed"
    assert out[("tests.t", "test_skip")] == "skipped" and out[("tests.t", "test_xfail")] == "xfail"
    assert out[("tests.t", "test_td")] == "error" and out[("tests.t", "test_fail")] == "failure"
    twin = junit(tmp_path, ("tests.t", "a", ""), ("tests.t", "a", ""))
    with pytest.raises(relabel.Refused, match="duplicate testcase"):
        relabel.read_junit(twin)


def git_repo(root: Path) -> None:
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, capture_output=True)


def commit(root: Path) -> None:
    git_repo_cmds = (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "y"])
    for cmd in git_repo_cmds:
        subprocess.run(["git", "-C", str(root), *cmd], check=True, capture_output=True)


COLLECTED = ["tests/test_a.py::test_one", "tests/test_a.py::test_two", "tests/test_b.py::test_other",
             "tests/ported/test_old.py::test_p", "tests/test_architecture.py::test_target_tree_has_no_violation_and_no_exception"]
CASES = [("tests.test_a", "test_one", ""), ("tests.test_a", "test_two", '<skipped type="pytest.skip"/>'),
         ("tests.test_b", "test_other", ""), ("tests.ported.test_old", "test_p", ""),
         ("tests.test_architecture", "test_target_tree_has_no_violation_and_no_exception", "")]


def build(tree, tmp_path, cases=CASES, collected=COLLECTED, compare=None, owner=(), exercise=None):
    if not (tree / ".git").exists():
        git_repo(tree)
    report = tmp_path / "c.json"
    report.write_text(json.dumps(compare or {"ok": True, "scenarios": {"fam": {
        "target": "equal", "reference": "equal", "origin_ok": True, "target_origin_ok": True}}}))
    return relabel.build_bundle(tree, junit(tmp_path, *cases), [report], list(owner), "HEAD", list(collected), None, exercise)


def test_the_bundle_records_the_outcomes_ids_and_compare_reports(tree, tmp_path):
    doc = build(tree, tmp_path)
    assert doc["head"] == subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True,
                                         text=True).stdout.strip()
    assert doc["not_passed"] == {"tests/test_a.py::test_two": "skipped"}
    assert doc["compare"]["fam"]["target"] == "equal" and set(doc["ids"]) == {
        TP + "src", "compare", TP + "pyproject.toml", TP + "uv.lock"}
    assert TP + "tests/conftest.py" in doc["support"] and TP + "tests/test_a.py" in doc["test_modules"]


# S11 RH-1 (R-L2f, R-L2c): several same-head JUnits merge per node; the owner run may cover a subset.
SKIP = '<skipped type="pytest.skip"/>'
OWNER_NODE = ("tests.test_a", "test_two")  # skipped in CASES (the TI)


def merged_bundle(tree, tmp_path, owner_cases, ti_cases=CASES):
    if not (tree / ".git").exists():
        git_repo(tree)
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"ok": True, "scenarios": {}}))
    paths = [junit(tmp_path, *ti_cases), junit(tmp_path, *owner_cases, name="owner.xml")]
    return relabel.build_bundle(tree, paths, [report], [], "HEAD", list(COLLECTED)), paths


def test_a_node_skipped_in_the_ti_and_passed_in_the_owner_run_is_passed_and_counted(tree, tmp_path):
    doc, paths = merged_bundle(tree, tmp_path, [(*OWNER_NODE, "")])
    assert doc["not_passed"] == {}
    assert list(doc["junit_upgrades"].values()) == [0, 1]
    assert {relabel.sha256_file(p) for p in paths} <= set(doc["inputs"].values())


def test_a_node_failed_in_the_owner_run_is_failed_even_when_the_ti_passed(tree, tmp_path):
    doc, _ = merged_bundle(tree, tmp_path, [("tests.test_b", "test_other", '<failure message="f"/>')])
    assert doc["not_passed"] == {"tests/test_a.py::test_two": "skipped", "tests/test_b.py::test_other": "failure"}
    assert list(doc["junit_upgrades"].values()) == [0, 0]


def test_a_node_skipped_in_both_runs_stays_skipped(tree, tmp_path):
    doc, _ = merged_bundle(tree, tmp_path, [(*OWNER_NODE, SKIP)])
    assert doc["not_passed"] == {"tests/test_a.py::test_two": "skipped"}
    assert list(doc["junit_upgrades"].values()) == [0, 0]


def test_a_failure_in_the_ti_is_not_rescued_by_an_owner_pass(tree, tmp_path):
    ti = [(*OWNER_NODE, '<error message="e"/>') if c[:2] == OWNER_NODE else c for c in CASES]
    doc, _ = merged_bundle(tree, tmp_path, [(*OWNER_NODE, "")], ti)
    assert doc["not_passed"] == {"tests/test_a.py::test_two": "error"}


def test_an_owner_run_naming_an_uncollected_node_refuses_the_bundle(tree, tmp_path):
    with pytest.raises(relabel.Refused, match="matches no collected node"):
        merged_bundle(tree, tmp_path, [("tests.test_b", "test_ghost", "")])


def test_a_single_junit_bundle_is_the_same_whether_given_as_a_path_or_a_list(tree, tmp_path):
    git_repo(tree)
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"ok": True, "scenarios": {}}))
    path = junit(tmp_path, *CASES)
    one = relabel.build_bundle(tree, path, [report], [], "HEAD", list(COLLECTED))
    listed = relabel.build_bundle(tree, [path], [report], [], "HEAD", list(COLLECTED))
    assert relabel.dump_json(one) == relabel.dump_json(listed) and "junit_upgrades" not in one


def test_an_unmatched_testcase_refuses_the_bundle(tree, tmp_path):
    with pytest.raises(relabel.Refused, match="matches no collected node"):
        build(tree, tmp_path, cases=[*CASES, ("tests.test_b", "test_ghost", "")])


def test_a_collected_node_without_a_testcase_refuses_the_bundle(tree, tmp_path):
    with pytest.raises(relabel.Refused, match="no testcase"):
        build(tree, tmp_path, cases=CASES[:-1])


def test_a_duplicate_node_refuses_the_bundle(tree, tmp_path):
    with pytest.raises(relabel.Refused, match="duplicate collected node"):
        build(tree, tmp_path, collected=[*COLLECTED, COLLECTED[0]])


def test_a_compare_report_that_is_not_ok_refuses_the_bundle(tree, tmp_path):
    with pytest.raises(relabel.Refused, match="ok is not true"):
        build(tree, tmp_path, compare={"ok": False, "scenarios": {}})


def test_an_unreadable_owner_run_artifact_refuses_the_bundle(tree, tmp_path):
    with pytest.raises(relabel.Refused, match="sha256 cannot be computed"):
        build(tree, tmp_path, owner=[tmp_path / "absent.txt"])


SCHEME = "postgresql:" + "//"  # split literals: check-tree's credential-shape scan reads this file
DSN_NODE = "tests/ported/test_old.py::test_p[--dsn-env-" + SCHEME + "zeus:pw" + "@[unterminated/zeus]"


def test_a_credential_shaped_node_id_is_stored_hashed_and_a_plain_id_never_is(tree, tmp_path):
    import hashlib

    plain = "tests/test_b.py::test_other"
    assert relabel.hashed_id(plain) == plain
    assert relabel.hashed_id(DSN_NODE) == "sha256:" + hashlib.sha256(DSN_NODE.encode()).hexdigest()
    collected = [*COLLECTED, DSN_NODE]
    cases = [*CASES, ("tests.ported.test_old", "test_p[--dsn-env-" + SCHEME + "zeus:pw" + "@[unterminated/zeus]",
                      '<skipped type="pytest.skip"/>')]
    doc = build(tree, tmp_path, cases=cases, collected=collected)
    hashed = relabel.hashed_id(DSN_NODE)
    assert doc["hashed_ids"]["count"] == 1 and doc["hashed_ids"]["paths"] == {hashed: "tests/ported/test_old.py"}
    assert hashed in doc["nodes"] and DSN_NODE not in doc["nodes"] and doc["not_passed"][hashed] == "skipped"
    assert "pw" + "@" not in json.dumps(doc) and plain in doc["nodes"]
    # the relabel keeps the hashed node in its file: a file item sees the skipped node (not a pass, not a failure)
    out, _ = run([row(slice_="S7", evidence=("reference:tests/test_old.py",))], tree, doc)
    assert out["api:x.py::f"]["status"] == "verified"
    doc["not_passed"][hashed] = "failure"
    out, _ = run([row(slice_="S7", evidence=("reference:tests/test_old.py",))], tree, doc)
    assert has_unmet(out["api:x.py::f"], "reference test not passing")


def test_the_secret_shapes_equal_compare_run():
    import ast

    tree = ast.parse((ROOT / "compare/run.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "SECRET_SHAPES")
    patterns = [c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    assert patterns == [p.pattern for p in relabel.SECRET_SHAPES]


def test_a_test_module_added_after_the_evidence_head_is_not_part_of_the_evidence(tree, tmp_path):
    git_repo(tree)
    write(tree, TP + "tests/test_new.py", "def test_new():\n    pass\n")
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"ok": True, "scenarios": {}}))
    doc = relabel.build_bundle(tree, junit(tmp_path, *CASES), [report], [], "HEAD", [*COLLECTED, "tests/test_new.py::test_new"])
    assert "tests/test_new.py::test_new" not in doc["nodes"]


def test_a_changed_bound_input_at_bundle_time_refuses(tree, tmp_path):
    git_repo(tree)
    write(tree, TP + "src/codex_harness/research/mod.py", "changed = 1\n")
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"ok": True, "scenarios": {}}))
    with pytest.raises(relabel.Refused, match="differs from the evidence head"):
        relabel.build_bundle(tree, junit(tmp_path, *CASES), [report], [], "HEAD", COLLECTED)


# ------------------------------------------------------------------------------- S11 §20: R-L17 and the R-P2 markers

U6A = "retire:U6(a) Windows scheduled-task host target (W-B; USER-APPROVED-U6-20261006)"


def retire_row(intent=U6A, symbol="codex_harness.research.gone:Thing"):
    return row(slice_="S7", intent=intent, symbol=(symbol,), evidence=("target:tests/test_b.py",))


def test_a_retire_intent_with_every_target_symbol_absent_is_retired_with_authority(tree):
    out, _ = run([retire_row()], tree)
    r = out["api:x.py::f"]
    assert r["status"] == "retired-with-authority"
    assert r["verification"] == {"head": HEAD, "authority": "USER-APPROVED-U6-20261006 U6(a)",
                                 "absent": ["codex_harness.research.gone:Thing"]}


def test_a_retire_intent_whose_target_symbol_is_present_is_not_retired_and_names_it(tree):
    out, _ = run([retire_row(symbol="codex_harness.research.mod:Thing")], tree)
    r = out["api:x.py::f"]
    assert r["status"] != "retired-with-authority"
    assert "retire:U6(a): target symbol still present: codex_harness.research.mod:Thing" in r["verification"]["unmet"]
    # one present symbol among absent ones keeps the row out of the retirement too
    out, _ = run([row(slice_="S7", intent=U6A, symbol=("codex_harness.research.gone:Thing", "codex_harness.research.mod:Thing"))],
                 tree)
    assert out["api:x.py::f"]["status"] != "retired-with-authority"


def test_a_previously_retired_row_is_measured_again_and_loses_the_status_when_the_symbol_is_present(tree):
    stale = {**retire_row(symbol="codex_harness.research.mod:Thing"), "status": "retired-with-authority"}
    out, _ = run([stale], tree)
    assert out["api:x.py::f"]["status"] != "retired-with-authority"


@pytest.mark.parametrize("granted", ["b", "c"])
def test_the_other_granted_u6_items_retire_too(tree, granted):
    out, _ = run([retire_row(intent=f"retire:U6({granted}) text")], tree)
    r = out["api:x.py::f"]
    assert r["status"] == "retired-with-authority"
    assert r["verification"]["authority"] == f"USER-APPROVED-U6-20261006 U6({granted})"


@pytest.mark.parametrize("item", ["d", "e", ""])
def test_a_retire_intent_for_an_ungranted_u6_item_refuses(tree, item):
    with pytest.raises(relabel.Refused, match="not granted"):
        run([retire_row(intent=f"retire:U6({item}) Codex legacy exec")], tree)


def test_the_check_exits_1_for_a_u6_d_retire_intent(tree, capsys):
    write(tree, "coverage/ledger-coverage.json", json.dumps({"rows": [retire_row(intent="retire:U6(d) x")]}))
    write(tree, "coverage/run-evidence.json", json.dumps(bundle_for()))
    assert relabel.main(["--root", str(tree), "--check"]) == 1
    assert "not granted" in capsys.readouterr().err


SOURCE_BARE = '"""A bare marker."""\n'
SOURCE_CODE = '"""Not a marker."""\n\n\ndef f():\n    pass\n'


@pytest.fixture()
def source_repo(tree, monkeypatch):
    """A git history whose first commit is the SOURCE (`relabel.SOURCE_COMMIT`); the working tree is the target."""
    def at_source(files):
        for rel, text in files.items():
            write(tree, rel, text)
        git_repo(tree)
        sha = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        monkeypatch.setattr(relabel, "SOURCE_COMMIT", sha)
        for rel in files:
            (tree / rel).unlink()
            parent = (tree / rel).parent  # S11 unit P: git keeps no empty SOURCE directory either
            while parent != tree and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    return at_source


def marker_row(path, symbol, intent="preserve"):
    return row(kind="module", key=f"module:{path}", slice_="S1", symbol=(symbol,), intent=intent,
               evidence=("target:tests/test_b.py",))


def test_a_marker_symbol_is_accepted_only_for_a_module_whose_source_file_is_also_a_bare_marker(tree, source_repo):
    source_repo({"src/codex_harness/pkgm/__init__.py": SOURCE_BARE, "src/codex_harness/pkgc/__init__.py": SOURCE_CODE})
    write(tree, TP + "src/codex_harness/pkgm/__init__.py", '"""Target marker."""\n')
    write(tree, TP + "src/codex_harness/pkgc/__init__.py", '"""Target marker."""\n')
    out, _ = run([marker_row("src/codex_harness/pkgm/__init__.py", "codex_harness.pkgm")], tree)
    assert out["module:src/codex_harness/pkgm/__init__.py"]["status"] == "verified"
    # a NON-marker SOURCE module whose target symbol is a bare marker is still refused (R-MC2-3)
    out, _ = run([marker_row("src/codex_harness/pkgc/__init__.py", "codex_harness.pkgc")], tree)
    r = out["module:src/codex_harness/pkgc/__init__.py"]
    assert r["status"] != "verified" and has_unmet(r, "target symbol is a package marker")


def test_a_marker_symbol_is_refused_when_the_source_file_is_missing_or_the_row_is_not_a_module(tree, source_repo):
    source_repo({"src/codex_harness/pkgm/__init__.py": SOURCE_BARE})
    write(tree, TP + "src/codex_harness/pkgm/__init__.py", '"""Target marker."""\n')
    out, _ = run([marker_row("src/codex_harness/nowhere/__init__.py", "codex_harness.pkgm")], tree)
    assert has_unmet(out["module:src/codex_harness/nowhere/__init__.py"], "target symbol is a package marker")
    out, _ = run([row(kind="public_api", key="api:src/codex_harness/pkgm/__init__.py::x", symbol=("codex_harness.pkgm",),
                      slice_="S1")], tree)
    assert has_unmet(out["api:src/codex_harness/pkgm/__init__.py::x"], "target symbol is a package marker")


REMOVED = "none: removed by design (S11 §20 R-P2)"
LAYER = "change:§4 Layer markers (empty M7 package replaced; S11 §20 R-P2)"


def test_a_removed_marker_is_accepted_only_when_the_source_is_bare_and_the_package_is_absent(tree, source_repo):
    source_repo({"src/codex_harness/gone/__init__.py": SOURCE_BARE, "src/codex_harness/gonec/__init__.py": SOURCE_CODE,
                 "src/codex_harness/kept/__init__.py": SOURCE_BARE})
    write(tree, TP + "src/codex_harness/kept/__init__.py", '"""Still here."""\n')
    out, _ = run([marker_row("src/codex_harness/gone/__init__.py", REMOVED, LAYER)], tree)
    assert out["module:src/codex_harness/gone/__init__.py"]["status"] == "verified"
    # the package is still present in the target: refused
    out, _ = run([marker_row("src/codex_harness/kept/__init__.py", REMOVED, LAYER)], tree)
    r = out["module:src/codex_harness/kept/__init__.py"]
    assert r["status"] != "verified" and has_unmet(r, "removed marker: the package is still present")
    # a SOURCE file that is not a bare marker: refused
    out, _ = run([marker_row("src/codex_harness/gonec/__init__.py", REMOVED, LAYER)], tree)
    assert has_unmet(out["module:src/codex_harness/gonec/__init__.py"], "removed marker: the SOURCE file is not")
    # without the Layer markers intent the `none:` symbol is not a code symbol
    out, _ = run([marker_row("src/codex_harness/gone/__init__.py", REMOVED, "preserve")], tree)
    assert has_unmet(out["module:src/codex_harness/gone/__init__.py"], "target symbol is not a code symbol")


# ---------------------------------------------------------------------------------------------- the rules per row

def test_a_row_with_a_passing_item_and_a_resolving_symbol_is_verified(tree):
    out, _ = run([row(slice_="S7", evidence=("target:tests/test_b.py", "compare:fam"))], tree)
    r = out["api:x.py::f"]
    assert r["status"] == "verified" and r["verification"] == {
        "head": HEAD, "passed": ["compare:fam", "target:tests/test_b.py"]}


def test_a_skipped_node_and_a_failing_node_are_not_passing_evidence(tree):
    bundle = bundle_for(not_passed={"tests/test_b.py::test_other": "skipped"})
    out, _ = run([row(slice_="S7")], tree, bundle)
    r = out["api:x.py::f"]
    assert r["status"] == "implemented" and "no passing executable item" in r["verification"]["unmet"]
    out, _ = run([row(slice_="S7", evidence=("target:tests/test_a.py::test_two",))], tree,
                 bundle_for(not_passed={"tests/test_a.py::test_two": "xfail"}))
    assert out["api:x.py::f"]["status"] == "implemented"
    out, _ = run([row(slice_="S7", evidence=("target:tests/test_b.py", "target:tests/test_a.py::test_two"))], tree,
                 bundle_for(not_passed={"tests/test_a.py::test_two": "error"}))
    assert out["api:x.py::f"]["status"] == "implemented"  # a named item that fails blocks `verified`


def test_a_missing_evidence_file_or_node_is_unmet(tree):
    out, _ = run([row(slice_="S7", evidence=("target:tests/test_gone.py",)),
                  row(key="api:y", slice_="S7", evidence=("target:tests/test_b.py::test_nope",))], tree)
    assert out["api:x.py::f"]["status"] == "implemented"
    assert any(u.startswith("target file absent") for u in out["api:x.py::f"]["verification"]["unmet"])
    assert any(u.startswith("target node not collected") for u in out["api:y"]["verification"]["unmet"])


def test_a_compare_family_without_a_target_driver_or_a_report_is_unmet(tree):
    out, engine = run([row(slice_="S7", evidence=("compare:nodrv",)),
                       row(key="api:y", slice_="S7", evidence=("compare:other",)),
                       row(key="api:z", slice_="S7", evidence=("compare:nodrv", "compare:fam"))], tree)
    # R-L2b: a family with no target driver is context: neither passing nor missing
    assert has_unmet(out["api:x.py::f"], "no passing executable item") and out["api:x.py::f"]["status"] == "designed"
    assert out["api:z"]["status"] == "verified" and engine.reference_only == {"nodrv"}
    assert has_unmet(out["api:y"], "compare scenario absent")
    out, _ = run([row(slice_="S7", evidence=("compare:fam#part (a note)",))], tree,
                 bundle_for(compare={"fam": {"target": "diverged", "reference": "equal", "origin_ok": True,
                                             "target_origin_ok": True}}))
    assert out["api:x.py::f"]["status"] == "implemented"
    assert has_unmet(out["api:x.py::f"], "compare not equal")


def test_a_pending_item_blocks_verified(tree):
    out, _ = run([row(slice_="S7", evidence=("target:tests/test_b.py", "pending: characterization before the S8 move (R-U)"))],
                 tree)
    r = out["api:x.py::f"]
    assert r["status"] == "implemented"
    assert r["verification"]["unmet"] == ["pending: characterization before the S8 move (R-U)"]
    out, _ = run([row(slice_="S7", evidence=("static:compare/x.json#a", "pending: recorder confirmation"))], tree)
    r = out["api:x.py::f"]
    assert r["status"] == "designed" and "no passing executable item" in r["verification"]["unmet"]


def test_an_unaccepted_slice_is_not_verified(tree):
    out, _ = run([row(slice_="S11"), row(key="api:y", owner="research", slice_=None), row(key="api:z", owner="nowhere")], tree)
    assert out["api:x.py::f"]["status"] == "implemented"
    assert "owning slice not accepted: S11" in out["api:x.py::f"]["verification"]["unmet"]
    assert out["api:y"]["status"] == "verified"  # research -> S8, accepted
    assert "owning slice not derivable" in out["api:z"]["verification"]["unmet"]


def test_a_symbol_that_does_not_resolve_is_designed_or_implemented_by_its_items(tree):
    out, _ = run([row(slice_="S7", symbol=("codex_harness.research.mod:Absent",)),
                  row(key="api:y", slice_="S7", symbol=("one Store.transaction() opened by the owning use case",),
                      evidence=("static:x",))], tree)
    assert out["api:x.py::f"]["status"] == "designed"
    assert out["api:y"]["status"] == "designed"
    assert any(u.startswith("target symbol is not a code symbol") for u in out["api:y"]["verification"]["unmet"])


def test_module_rows_come_first_and_their_rows_inherit_through_module_items(tree):
    module = row(kind="module", key="module:src/x.py", slice_="S7", evidence=("target:tests/test_b.py",))
    api = row(key="api:src/x.py::Thing", slice_="S7", evidence=("module:src/x.py",))
    out, _ = run([api, module], tree)  # the api row listed first: R-L4 still evaluates the module row first
    assert out["module:src/x.py"]["status"] == "verified" and out["api:src/x.py::Thing"]["status"] == "verified"
    assert out["api:src/x.py::Thing"]["verification"]["passed"] == ["module:src/x.py"]
    out, _ = run([api, {**module, "evidence": ["pending: later"]}], tree)
    assert out["module:src/x.py"]["status"] == "designed"
    assert out["api:src/x.py::Thing"]["status"] in {"designed", "implemented"}
    assert "module row not verified: module:src/x.py" in out["api:src/x.py::Thing"]["verification"]["unmet"]
    out, _ = run([api], tree)
    assert "module row absent: module:src/x.py" in out["api:src/x.py::Thing"]["verification"]["unmet"]


def test_a_reference_item_needs_the_same_name_ported_file_with_every_node_passing(tree):
    ok, _ = run([row(slice_="S7", evidence=("reference:tests/test_old.py",))], tree)
    assert ok["api:x.py::f"]["status"] == "verified"
    none, _ = run([row(slice_="S7", evidence=("reference:tests/test_nothere.py",)),
                   row(key="api:y", slice_="S7", evidence=("reference:+3 more test files", "target:tests/test_b.py"))], tree)
    assert has_unmet(none["api:x.py::f"], "reference has no same-name ported file")
    assert none["api:y"]["status"] == "verified"  # R-L2d: the unnamed truncation is context
    # R-L2c: a file item passes with >=1 passing node and none failed (skips are never passes)
    write(tree, TP + "tests/ported/test_two.py", "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    nodes = [*NODES, "tests/ported/test_two.py::test_a", "tests/ported/test_two.py::test_b"]
    item = ("reference:tests/test_two.py",)
    mixed, _ = run([row(slice_="S7", evidence=item)], tree,
                   bundle_for(nodes=nodes, not_passed={"tests/ported/test_two.py::test_b": "skipped"}))
    assert mixed["api:x.py::f"]["status"] == "verified"
    failed, _ = run([row(slice_="S7", evidence=item)], tree,
                    bundle_for(nodes=nodes, not_passed={"tests/ported/test_two.py::test_b": "failure"}))
    assert has_unmet(failed["api:x.py::f"], "reference test not passing")
    allskip, _ = run([row(slice_="S7", evidence=item)], tree, bundle_for(
        nodes=nodes, not_passed={"tests/ported/test_two.py::test_a": "skipped", "tests/ported/test_two.py::test_b": "skipped"}))
    assert has_unmet(allskip["api:x.py::f"], "reference test not passing")


def test_a_reference_conftest_is_fixture_context_only_when_its_ported_conftest_exists(tree):
    """S11 R-L2c-c (owner): a conftest holds fixtures, never test nodes, so it is context, not a missing test file."""
    item = ("reference:tests/conftest.py", "target:tests/test_b.py")
    write(tree, TP + "tests/ported/conftest.py", "import pytest\n")
    out, _ = run([row(slice_="S7", evidence=item)], tree)
    assert out["api:x.py::f"]["status"] == "verified"
    alone, _ = run([row(slice_="S7", evidence=item[:1])], tree)
    assert alone["api:x.py::f"]["status"] != "verified"  # context alone is no passing executable item
    (tree / (TP + "tests/ported/conftest.py")).unlink()
    gone, _ = run([row(slice_="S7", evidence=item)], tree)
    assert has_unmet(gone["api:x.py::f"], "reference conftest has no same-name ported conftest")


def test_an_owner_run_item_passes_only_when_the_bundle_lists_the_artifact(tree):
    item = "owner-run:promtool (A/evidence/x.txt)"
    out, _ = run([row(slice_="S7", evidence=(item,))], tree, bundle_for(owner_run={"A/evidence/x.txt": "ab" * 32}))
    assert out["api:x.py::f"]["status"] == "verified"
    out, _ = run([row(slice_="S7", evidence=(item,))], tree)
    assert has_unmet(out["api:x.py::f"], "owner-run artifact not in the bundle")


def test_an_unrecognised_evidence_form_is_refused(tree):
    with pytest.raises(relabel.Refused, match="unrecognised evidence form"):
        run([row(evidence=("mystery: x",))], tree)


# -------------------------------------------------------------------------------------- buckets, contracts, capabilities

def bucket(name, **more):
    return row(kind="bucket", key=f"bucket:{name}", evidence=("compare:static.source#bucket_candidates",),
               symbol=("codex_harness.research.ports.OWNED_BUCKETS",), slice_=None, **more)


def test_a_bucket_declared_once_with_the_single_writer_node_passing_is_verified(tree):
    out, _ = run([bucket("alpha")], tree)
    assert out["bucket:alpha"]["status"] == "verified"
    assert out["bucket:alpha"]["verification"]["passed"] == ["node:" + relabel.SINGLE_WRITER_NODE]


def test_a_bucket_in_two_owned_buckets_is_not_verified(tree):
    out, _ = run([bucket("beta")], tree)
    r = out["bucket:beta"]
    assert r["status"] == "designed" and has_unmet(r, "bucket declared in 2 OWNED_BUCKETS")
    out, _ = run([bucket("absent")], tree)
    assert has_unmet(out["bucket:absent"], "bucket declared in 0 OWNED_BUCKETS")


def test_a_bucket_whose_single_writer_node_did_not_pass_is_not_verified(tree):
    bundle = bundle_for(not_passed={relabel.SINGLE_WRITER_NODE: "failure"})
    out, _ = run([bucket("alpha")], tree, bundle)
    assert out["bucket:alpha"]["status"] == "implemented"
    assert has_unmet(out["bucket:alpha"], "single-writer node did not pass")


def test_the_four_unmapped_buckets_follow_the_s10_trace_and_the_rule_is_idempotent(tree):
    rows = [row(kind="bucket", key=k, status="unmapped", evidence=["ledger only (not a tx literal access)"], symbol=(),
                owner=None) for k in relabel.UNMAPPED_BUCKETS]
    write(tree, TP + "src/codex_harness/delivery/__init__.py")
    write(tree, TP + "src/codex_harness/delivery/adapters/__init__.py")
    write(tree, TP + "src/codex_harness/delivery/adapters/host_migration.py",
          'FLEET_OWNER_FILE = "fleet-owner.json"\nFLEET_OWNER_SCHEMA = "urn"\nSWITCH_UNITS = ("a",)\n')
    write(tree, TP + "tests/ported/test_host_migration_successor.py", "def test_h():\n    pass\n")
    write(tree, TP + "src/codex_harness/research/ports.py", 'OWNED_BUCKETS = ("alpha", "discovery_pressure")\n')
    bundle = bundle_for(nodes=[*NODES, "tests/ported/test_host_migration_successor.py::test_h"])
    out, _ = run(rows, tree, bundle)
    assert {r["status"] for r in out.values()} == {"verified"}
    assert out["bucket:fleet-owner.json"]["mapping_correction"].startswith("not a bucket (S10-PACKET §4b)")
    assert out["bucket:discovery_pressure"]["mapping_correction"].startswith("a real bucket")
    again, _ = relabel.relabel({"rows": list(out.values())}, bundle, tree)
    assert {r["key"]: r for r in again["rows"]} == out


def test_a_contract_needs_the_id_in_the_registry_and_a_passing_citing_test(tree):
    c = row(kind="contract", key="contract:INV-X-001", symbol=("docs/contracts.md#INV-X-001 enforced in x",),
            evidence=("compare:fam",), slice_="S7")
    gone = row(kind="contract", key="contract:INV-Z-001", symbol=("docs/contracts.md#INV-Z-001 enforced in x",),
               evidence=("compare:fam",), slice_="S7")
    out, engine = run([c, gone], tree)
    # INV-X-001 is cited by the module docstring of test_a.py: a module-level citation, so test_one passing is enough
    assert out["contract:INV-X-001"]["status"] == "verified"
    assert "cites:INV-X-001" in out["contract:INV-X-001"]["verification"]["passed"]
    assert has_unmet(out["contract:INV-Z-001"], "contract not in docs/contracts.md")
    # a function-level citation counts for that function's nodes only
    y = row(kind="contract", key="contract:INV-Y-001", symbol=("docs/contracts.md#INV-Y-001 enforced in x",),
            evidence=("compare:fam",), slice_="S7")
    out, _ = run([y], tree, bundle_for(not_passed={"tests/test_a.py::test_two": "skipped"}))
    assert out["contract:INV-Y-001"]["status"] == "implemented"
    assert has_unmet(out["contract:INV-Y-001"], "no passing target test cites the contract")


# S11 R-L9b: a citation counts only through a node with >=1 assert the FA-009 detector does not flag.
STRUCTURAL_NODE = (
    "def test_reads_source():\n"
    "    # INV-X-001 is cited in a node that only reads production source text\n"
    "    text = (ROOT / 'src/codex_harness/research/mod.py').read_text()\n"
    "    assert 'Thing' in text\n"
    "    assert 'class' in (ROOT / 'src/codex_harness/research/mod.py').read_text()\n")
BEHAVIOURAL_NODE = (
    "def test_runs_behaviour():\n"
    "    # INV-X-001 is cited in a node that asserts an executed result\n"
    "    assert service.go() == 1\n")
MIXED_NODE = (
    "def test_mixed():\n"
    "    # INV-X-001 is cited in a node with one structural and one behavioural assert\n"
    "    text = (ROOT / 'src/codex_harness/research/mod.py').read_text()\n"
    "    assert 'Thing' in text\n"
    "    assert service.go() == 1\n")
NO_ASSERT_NODE = (
    "def test_expects_a_refusal():\n"
    "    # INV-X-001 is cited in a node that asserts through pytest.raises only\n"
    "    with pytest.raises(ValueError):\n"
    "        service.go()\n")


def cited_by(tree, *nodes, module_doc=""):
    """Replace test_a.py with `nodes` (INV-X-001 cited inside each) and return (X's ledger row, bundle)."""
    write(tree, TP + "tests/test_a.py", module_doc + "\n\n".join(nodes))
    names = [n.split("(")[0][len("def "):] for node in nodes for n in node.split("\n") if n.startswith("def ")]
    bundle = bundle_for(nodes=[f"tests/test_a.py::{n}" for n in names] + NODES[2:])
    c = row(kind="contract", key="contract:INV-X-001", symbol=("docs/contracts.md#INV-X-001 enforced in x",),
            evidence=("compare:fam",), slice_="S7")
    return c, bundle


def test_a_contract_cited_only_by_a_structural_node_is_not_verified(tree):
    c, bundle = cited_by(tree, STRUCTURAL_NODE)
    out, _ = run([c], tree, bundle)
    r = out["contract:INV-X-001"]
    assert r["status"] == "implemented"
    assert r["verification"]["unmet"] == ["cited only by structural nodes: tests/test_a.py::test_reads_source"]
    assert "cites:INV-X-001" not in r["verification"].get("passed", [])


def test_a_contract_cited_by_a_node_with_a_behavioural_assert_is_verified(tree):
    c, bundle = cited_by(tree, BEHAVIOURAL_NODE)
    out, _ = run([c], tree, bundle)
    assert out["contract:INV-X-001"]["status"] == "verified"
    assert "cites:INV-X-001" in out["contract:INV-X-001"]["verification"]["passed"]


def test_a_mixed_node_with_one_behavioural_assert_counts(tree):
    c, bundle = cited_by(tree, MIXED_NODE)
    out, _ = run([c], tree, bundle)
    assert out["contract:INV-X-001"]["status"] == "verified"


def test_a_node_without_any_assert_is_not_structural(tree):
    c, bundle = cited_by(tree, NO_ASSERT_NODE)
    out, _ = run([c], tree, bundle)
    assert out["contract:INV-X-001"]["status"] == "verified"


def test_a_structural_node_does_not_count_beside_a_non_passing_behavioural_one(tree):
    c, bundle = cited_by(tree, STRUCTURAL_NODE, BEHAVIOURAL_NODE)
    bundle["not_passed"] = {"tests/test_a.py::test_runs_behaviour": "failure"}
    out, _ = run([c], tree, bundle)
    assert out["contract:INV-X-001"]["status"] == "implemented"
    assert has_unmet(out["contract:INV-X-001"], "cited only by structural nodes: tests/test_a.py::test_reads_source")


def test_a_module_level_citation_applies_per_node_under_the_same_rule(tree):
    doc = '"""Cites INV-X-001 at module level."""\n\n\n'
    structural_module = doc + "def test_s1():\n    text = (ROOT / 'src/codex_harness/a.py').read_text()\n    assert 'a' in text\n"
    c, bundle = cited_by(tree, structural_module.replace(doc, ""), module_doc=doc)
    out, _ = run([c], tree, bundle)
    assert out["contract:INV-X-001"]["status"] == "implemented"
    assert has_unmet(out["contract:INV-X-001"], "cited only by structural nodes: tests/test_a.py::test_s1")
    # one behavioural node in the module restores the citation
    c, bundle = cited_by(tree, "def test_s1():\n    text = (ROOT / 'src/codex_harness/a.py').read_text()\n    assert 'a' in text\n",
                         "def test_s2():\n    assert service.go() == 1\n", module_doc=doc)
    out, _ = run([c], tree, bundle)
    assert out["contract:INV-X-001"]["status"] == "verified"


FA009_PATH = Path(__file__).resolve().parent / "test_s11_fa009.py"
CLASSIFIER_FIXTURES = [
    # M7 and TQ-1 positive/negative controls, and the module-level / class-method / async / nested shapes
    "def test_x():\n    assert 'record_incident' in (ROOT / 'src/codex_harness/cli.py').read_text()\n"
    "    assert 'fence' in Path('scripts/check.py').read_bytes().decode()\n"
    "    tree = ast.parse((ROOT / 'src/codex_harness/x.py').read_text())\n"
    "    assert any(isinstance(n, ast.Call) for n in ast.walk(ast.parse(source_of('codex_harness.x'))))\n",
    "def test_y(tmp_path):\n    assert (tmp_path / 'lease.json').read_text() == '{}'\n"
    "    assert service.record_incident(message)['occurrences'] == 1\n"
    "    assert 'FASTAPI_ELIGIBLE' in prompts[0]['body']\n"
    "    body = (ROOT / 'src/codex_harness/cli.py').read_text()\n    assert service.version() == 1\n",
    "from codex_harness.storage.adapters.redis_bus import RedisBus\n"
    "def test_read_then_assert():\n    text = (ROOT / 'src/codex_harness/x.py').read_text()\n    assert 'needle' in text\n"
    "def test_parsed_then_asserted():\n    tree = ast.parse((ROOT / 'src/codex_harness/x.py').read_text())\n"
    "    names = [n.name for n in ast.walk(tree)]\n    assert names == ['a', 'b']\n"
    "def test_lua_order():\n    script = RedisBus._DEAD_LETTER_SCRIPT\n"
    "    assert script.index('XADD') < script.index('XACK')\n    assert 'KEYS[1]' in script\n"
    "def test_constant_in_the_assert():\n    assert 'XACK' in RedisBus._DEAD_LETTER_SCRIPT\n"
    "    assert RedisBus._PUBLISH_SCRIPT.startswith('local')\n",
    "from codex_harness.x import TEMPLATE_X_TEMPLATE\ndef test_template():\n    assert 'slot' in TEMPLATE_X_TEMPLATE\n",
    "from codex_harness.storage.adapters.redis_bus import RedisBus\nLEGACY_SOURCE = {'topic': 'storage'}\n"
    "def test_fixture(tmp_path):\n    text = (tmp_path / 'lease.json').read_text()\n    assert 'x' in text\n"
    "def test_runtime_output():\n    out = run_cli(['--help'])\n    assert 'XADD' in out\n"
    "def test_reads_here():\n    text = (ROOT / 'src/codex_harness/x.py').read_text()\n    return text\n"
    "def test_asserts_elsewhere(text):\n    assert 'needle' in text\n"
    "def test_own_data_constant():\n    assert 'topic' in LEGACY_SOURCE\n"
    "def test_recorded_sequence(bus):\n    assert bus.client.calls == [('eval', (RedisBus._DEAD_LETTER_SCRIPT, 2))]\n",
    "class TestC:\n    def test_m(self):\n        t = (ROOT / 'scripts/x.sh').read_text()\n        assert 'set -e' in t\n"
    "    def test_n(self):\n        assert run() == 0\n"
    "async def test_a():\n    t = Path('src/codex_harness/y.py').read_text()\n    assert t\n",
    # FA-009b: reads through a local helper (positive: `__doc__`, get_docstring, getsource, a production read_text, a
    # variable bound to the call; negative: object builders, fixture text, a helper that only calls a reader)
    "def header(m):\n    return m.__doc__\ndef header_lines(m):\n    return ast.get_docstring(ast.parse(text_of(m)))\n"
    "def source(m):\n    return inspect.getsource(m)\n"
    "def packaged():\n    body = (ROOT / 'src/codex_harness/x.py').read_text()\n    return body\n"
    "def test_direct():\n    assert 'INV-METRIC-001' in header(domain_module)\n"
    "def test_through_a_variable():\n    doc = header(domain_module)\n    assert 'Layer: domain' in doc\n"
    "def test_other_readers():\n    assert 'a' in header_lines(m)\n    assert 'b' in source(m)\n    assert 'c' in packaged()\n",
    "def build():\n    return Store()\ndef fixture(tmp_path):\n    return (tmp_path / 'lease.json').read_text()\n"
    "def header(m):\n    return m.__doc__\ndef outer(m):\n    return header(m)\n"
    "def test_a(tmp_path):\n    assert build().count() == 0\n    assert 'x' in fixture(tmp_path)\n    assert 'y' in outer(m)\n"
    "def test_b():\n    doc = header(m)\n    return doc\ndef test_c(doc):\n    assert 'z' in doc\n",
    # FA-009c: a packaged data golden compared with a target call result (behavioural; the two data-golden controls and
    # their flagged counterparts: source text, a docstring, a code suffix, a data read with no call result)
    "def load(name):\n    return load_yaml(files('codex_harness.resources').joinpath(name).read_text())\n"
    "def header(m):\n    return m.__doc__\n"
    "def test_golden_vs_call():\n    expected = load('stages.yaml')\n    assert len(merge(a, b)) == len(expected)\n"
    "def test_golden_through_a_variable():\n    merged = merge(load('a.yaml'), load('b.yaml'))\n"
    "    assert merged == load('stages.yaml')\n    assert load('stages.yaml')['k'] in merged\n"
    "def test_source_text():\n    text = Path('src/x.py').read_text()\n    assert 'def f' in text\n"
    "def test_docstring():\n    doc = header(module)\n    assert 'INV-1' in doc\n"
    "def test_data_without_a_call():\n    data = load('k.json')\n    assert data['k'] == 1\n"
    "def test_code_text_with_a_call():\n    text = (ROOT / 'src/codex_harness/x.py').read_text()\n"
    "    assert len(merge(a, b)) == len(text)\n    assert merge(a, b) == load('x.py')\n"
    "def test_mixed_leaves():\n    expected = load('stages.yaml')\n"
    "    assert len(merge(a, b)) == len(expected) and 'x' in header(module)\n",
    STRUCTURAL_NODE, BEHAVIOURAL_NODE, MIXED_NODE, NO_ASSERT_NODE,
]


def test_the_structural_classifier_equals_test_s11_fa009():
    """The copied detector (relabel.wiring_assertions) and test_s11_fa009.wiring_assertions classify one fixture set
    identically: the copy cannot diverge silently (RETRO-PROPOSALS row 3)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s11_fa009_for_relabel", FA009_PATH)
    fa009 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa009)
    flagged_somewhere = 0
    for source in CLASSIFIER_FIXTURES:
        assert relabel.wiring_assertions(source) == fa009.wiring_assertions(source), source
        flagged_somewhere += bool(fa009.wiring_assertions(source))
    assert flagged_somewhere >= 6  # the set is not vacuous: the structural shapes really are flagged
    assert relabel.SOURCE_TEXT_READERS.pattern == fa009.SOURCE_TEXT_READERS.pattern
    assert relabel.PRODUCTION_LOCATIONS.pattern == fa009.PRODUCTION_LOCATIONS.pattern
    assert relabel.CONSTANT_SUFFIXES == fa009.CONSTANT_SUFFIXES
    assert relabel.CODE_SUFFIXES == fa009.CODE_SUFFIXES and relabel.DATA_SUFFIXES == fa009.DATA_SUFFIXES
    assert relabel.DATA_PARSERS.pattern == fa009.DATA_PARSERS.pattern and relabel.NEUTRAL_CALLS == fa009.NEUTRAL_CALLS
    # FA-009c: the golden fixtures above are classified by the rule in both copies (flagged lines, not just equal)
    golden = CLASSIFIER_FIXTURES[-5]
    assert [line for line, _ in fa009.wiring_assertions(golden)] == [14, 17, 20, 23, 24, 27]


def test_a_capability_needs_its_target_symbols_and_a_passing_named_test_and_no_pending_proposed_row(tree):
    a = row(kind="capability", key="capability:cap_a", symbol=("codex_harness.research",), slice_="S7",
            evidence=("docs/context/ARCHITECTURE.md#capabilities",))
    b = row(kind="capability", key="capability:cap_b", symbol=("codex_harness.research",), slice_="S7",
            evidence=("docs/context/ARCHITECTURE.md#capabilities",))
    out, _ = run([a, b], tree)
    assert out["capability:cap_a"]["status"] == "verified"
    assert out["capability:cap_b"]["status"] == "implemented"
    assert has_unmet(out["capability:cap_b"], "pending: ARCHITECTURE.md PROPOSED row")
    out, _ = run([a], tree, bundle_for(not_passed={"tests/test_a.py::test_one": "failure", "tests/test_a.py::test_two": "failure"}))
    assert out["capability:cap_a"]["status"] == "implemented"


def test_console_script_rows_resolve_through_the_project_scripts_table(tree):
    ok = row(kind="console_script", key="script:harness", symbol=("codex_harness.research.mod:Thing (permanent shim)",),
             evidence=("target:tests/test_b.py",), slice_="S10")
    wrong = row(kind="console_script", key="script:other", symbol=("codex_harness.research.mod:Thing (x)",),
                evidence=("target:tests/test_b.py",), slice_="S10")
    out, _ = run([ok, wrong], tree)
    assert out["script:harness"]["status"] == "verified"
    assert out["script:other"]["status"] == "designed"  # the symbol does not resolve through [project.scripts]
    assert any("[project.scripts]" in u for u in out["script:other"]["verification"]["unmet"])


# ------------------------------------------------------------------------------------------------- freshness (R-L13)

def test_the_bundle_goes_stale_with_an_evidence_module_conftest_or_target_src_and_not_with_a_new_test_module(tree, tmp_path):
    doc = build(tree, tmp_path)
    supplying = {"tests/test_b.py"}
    assert relabel.freshness(tree, doc, supplying) == []
    write(tree, TP + "tests/test_unrelated_new.py", "def test_new():\n    pass\n")
    commit(tree)
    assert relabel.freshness(tree, doc, supplying) == []  # a new, unrelated test module
    write(tree, TP + "tests/test_a.py", "def test_one():\n    assert True\n")
    commit(tree)
    assert relabel.freshness(tree, doc, supplying) == []  # a changed module that supplies no evidence
    write(tree, TP + "tests/test_b.py", "def test_other():\n    assert 1\n")
    commit(tree)
    assert any("test_b.py" in p for p in relabel.freshness(tree, doc, supplying))  # a changed evidence module
    git_repo_reset = ["checkout", "-q", "HEAD~1", "--", TP + "tests/test_b.py"]
    subprocess.run(["git", "-C", str(tree), *git_repo_reset], check=True, capture_output=True)
    commit(tree)
    assert relabel.freshness(tree, doc, supplying) == []
    write(tree, TP + "tests/conftest.py", "# changed\n")
    commit(tree)
    assert any("conftest.py" in p for p in relabel.freshness(tree, doc, supplying))
    subprocess.run(["git", "-C", str(tree), "checkout", "-q", "HEAD~1", "--", TP + "tests/conftest.py"], check=True)
    write(tree, TP + "src/codex_harness/research/mod.py", "class Thing:\n    pass\n")
    commit(tree)
    assert any(p.startswith(TP + "src changed") for p in relabel.freshness(tree, doc, supplying))


def test_a_new_support_file_under_target_tests_makes_the_bundle_stale(tree, tmp_path):
    doc = build(tree, tmp_path)
    write(tree, TP + "tests/fixtures/extra.json", "{}")
    commit(tree)
    assert any("extra.json added" in p for p in relabel.freshness(tree, doc, set()))


# ------------------------------------------------------------------------------------- the committed ledger (R-L12/13)

@pytest.fixture(scope="module")
def ledger():
    return json.loads((ROOT / "coverage/ledger-coverage.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def committed():
    return json.loads((ROOT / "coverage/run-evidence.json").read_text(encoding="utf-8"))


def test_the_committed_ledger_is_exactly_the_relabel_output(capsys):
    assert relabel.main(["--check"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ledger_matches_relabel": True}


def test_a_hand_edited_status_fails_the_check(tmp_path, ledger):
    """R-L12: the guard recomputes every status; a hand edit (here a row flipped to verified) is not byte-equal."""
    edited = copy.deepcopy(ledger)
    victim = next(r for r in edited["rows"] if r["status"] != "verified")
    victim["status"] = "verified"
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage/ledger-coverage.json").write_text(relabel.generate.dump(edited), encoding="utf-8")
    (tmp_path / "coverage/run-evidence.json").write_text((ROOT / "coverage/run-evidence.json").read_text(encoding="utf-8"))
    (tmp_path / "target").mkdir()
    for rel in ("docs", "compare", TP + "src", TP + "tests", TP + "pyproject.toml"):
        (tmp_path / rel).symlink_to(ROOT / rel)
    assert relabel.main(["--root", str(tmp_path), "--check"]) == 1


def test_every_row_records_its_verification_at_the_bundle_head(ledger, committed):
    for r in ledger["rows"]:
        v = r["verification"]
        assert v["head"] == committed["head"], r["key"]
        assert bool(v.get("passed")) == (r["status"] == "verified"), r["key"]
        if r["status"] == "retired-with-authority":
            # S11 §20 R-L17: a retired row records its authority and the measured absence, not an unmet list.
            assert v["authority"].startswith("USER-APPROVED-U6-20261006 U6(") and v["absent"], r["key"]
            continue
        assert bool(v.get("unmet")) == (r["status"] != "verified"), r["key"]
        if r["status"] != "verified":
            assert r["status"] in {"unmapped", "designed", "implemented"}, r["key"]


def test_the_bundle_binds_the_evidence_inputs(committed):
    assert committed["schema"] == relabel.BUNDLE_SCHEMA and len(committed["head"]) == 40
    assert set(committed["ids"]) == {TP + "src", "compare", TP + "pyproject.toml", TP + "uv.lock"}
    assert TP + "tests/conftest.py" in committed["support"]
    assert not any(p.rsplit("/", 1)[-1].startswith("test_") for p in committed["support"])
    assert set(committed["not_passed"]) <= set(committed["nodes"])
    assert set(committed["not_passed"].values()) <= {"skipped", "xfail"}  # a failing evidence run is never bundled
    assert not any(p.startswith("/") for p in [*committed["owner_run"], *committed["inputs"]])


# ----------------------------------------------------------------------------- pending resolutions (S11 L2, R-L6)
PENDING = "pending: recorder confirmation in the owning slice"


def resolution(items=("compare:fam",), key="api:x.py::f", pending=PENDING, rule="G1", citation="compare/scenarios/fam.json"):
    return {"key": key, "pending": pending, "replaced_by": list(items), "rule": rule, "citation": citation}


def pending_row(**more):
    return row(slice_="S7", evidence=("target:tests/test_b.py", PENDING), **more)


def test_a_resolution_replaces_exactly_its_pending_item_and_the_row_can_verify(tree):
    frozen = pending_row()
    out, _ = run([frozen], tree)
    assert out["api:x.py::f"]["status"] == "implemented" and out["api:x.py::f"]["verification"]["unmet"] == [PENDING]
    new, _ = relabel.relabel({"rows": [pending_row()]}, bundle_for(), tree, [resolution()])
    r = new["rows"][0]
    assert r["status"] == "verified" and r["verification"] == {"head": HEAD, "passed": ["compare:fam", "target:tests/test_b.py"]}
    assert r["evidence"] == frozen["evidence"], "the row itself stays frozen: the pending text is still in it"


def test_a_resolution_never_sets_a_status_so_a_failing_replacement_leaves_the_row_unmet(tree):
    bundle = bundle_for(not_passed={"tests/test_a.py::test_one": "skipped"})
    new, _ = relabel.relabel({"rows": [pending_row()]}, bundle, tree,
                             [resolution(items=("target:tests/test_a.py::test_one",))])
    r = new["rows"][0]
    assert r["status"] == "implemented"
    assert r["verification"]["unmet"] == ["target test not passing: target:tests/test_a.py::test_one (skipped in test_one)"]
    new, _ = relabel.relabel({"rows": [pending_row()]}, bundle_for(compare={}), tree, [resolution()])
    assert new["rows"][0]["status"] == "implemented" and has_unmet(new["rows"][0], "compare report absent")


def test_an_unresolved_pending_item_still_blocks_and_an_unrelated_resolution_changes_nothing(tree):
    other = pending_row(key="api:y.py::g")
    new, _ = relabel.relabel({"rows": [pending_row(), other]}, bundle_for(), tree, [resolution()])
    assert [r["status"] for r in new["rows"]] == ["verified", "implemented"]
    assert new["rows"][1]["verification"]["unmet"] == [PENDING]


@pytest.mark.parametrize("entry, why", [
    (resolution(key="api:nope.py::f"), "unknown key"),
    (resolution(pending="pending: something the row never promised"), "not in the row"),
    (resolution(pending="target:tests/test_b.py"), "non-pending item"),
    (resolution(items=(PENDING,)), "none pending"),
    (resolution(items=()), "non-empty"),
    (resolution(rule="G9"), "rule"),
    (resolution(citation=" "), "citation"),
    ({"key": "api:x.py::f", "pending": PENDING}, "resolution entry is not"),
])
def test_a_malformed_resolution_is_refused(tree, entry, why):
    with pytest.raises(relabel.Refused, match=why):
        relabel.relabel({"rows": [pending_row()]}, bundle_for(), tree, [entry])


def test_a_duplicate_resolution_is_refused(tree):
    with pytest.raises(relabel.Refused, match="duplicate resolution"):
        relabel.relabel({"rows": [pending_row()]}, bundle_for(), tree, [resolution(), resolution(items=("target:tests/test_a.py",))])


def test_check_refuses_with_exit_1_on_a_bad_resolutions_file(tmp_path, ledger, capsys):
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage/ledger-coverage.json").write_text((ROOT / "coverage/ledger-coverage.json").read_text(encoding="utf-8"))
    (tmp_path / "coverage/run-evidence.json").write_text((ROOT / "coverage/run-evidence.json").read_text(encoding="utf-8"))
    (tmp_path / "target").mkdir()
    for rel in ("docs", "compare", TP + "src", TP + "tests", TP + "pyproject.toml"):
        (tmp_path / rel).symlink_to(ROOT / rel)
    doc = {"schema": relabel.RESOLUTIONS_SCHEMA, "resolutions": [resolution(key="api:nope.py::f")]}
    (tmp_path / "coverage/evidence-resolutions.json").write_text(json.dumps(doc), encoding="utf-8")
    assert relabel.main(["--root", str(tmp_path), "--check"]) == 1
    assert "unknown key" in capsys.readouterr().err


def test_the_committed_resolutions_are_cited_valid_and_all_applied(ledger):
    doc = json.loads((ROOT / "coverage/evidence-resolutions.json").read_text(encoding="utf-8"))
    assert doc["schema"] == relabel.RESOLUTIONS_SCHEMA
    rows = {r["key"]: r for r in ledger["rows"]}
    seen = set()
    for e in doc["resolutions"]:
        assert set(e) == {"key", "pending", "replaced_by", "rule", "citation"} and e["rule"] in relabel.RESOLUTION_RULES
        assert e["pending"] in rows[e["key"]]["evidence"] and e["pending"].startswith("pending:") and e["citation"].strip()
        assert (e["key"], e["pending"]) not in seen
        seen.add((e["key"], e["pending"]))
        if rows[e["key"]]["status"] == "verified":  # a verified row's passing items include the resolution's replacements
            assert set(e["replaced_by"]) <= set(rows[e["key"]]["verification"]["passed"]), e["key"]


# ------------------------------------------------------------------- S11 AU: `exercise:` (R-L2e) and G1b (R-AU4)

SYMBOL = "codex_harness.research.mod:Thing.go"
EXERCISE_FUNCTIONS = ["codex_harness.research.mod:Thing.go", "codex_harness.research.mod:CONST"]


def exercise_file(tmp_path, nodes, functions=None, root="/x/target/src", schema=None):
    import gzip
    path = tmp_path / "exercise.json.gz"
    doc = {"schema": schema or relabel.EXERCISE_SCHEMA, "root": root, "functions": functions or EXERCISE_FUNCTIONS, "nodes": nodes}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    return path


def build_exercised(tree, tmp_path, nodes, **more):
    write(tree, "coverage/ledger-coverage.json", json.dumps({"rows": [row(symbol=(SYMBOL,)), row(key="api:y", symbol=("one Store.transaction()",))]}))
    return build(tree, tmp_path, exercise=exercise_file(tmp_path, nodes, **more))


def test_the_bundle_stores_up_to_three_passing_nodes_per_symbol_and_the_artifact_identity(tree, tmp_path):
    nodes = {"tests/test_a.py::test_two": [0], "tests/test_b.py::test_other": [0], "tests/test_a.py::test_one": [0, 1],
             "tests/ported/test_old.py::test_p": [0], relabel.SINGLE_WRITER_NODE: [0]}
    doc = build_exercised(tree, tmp_path, nodes)
    ex = doc["exercise"]
    # test_two is skipped in CASES: not passing, so never stored; of the four passing nodes the first three sorted are kept
    assert ex["symbols"] == {SYMBOL: ["tests/ported/test_old.py::test_p", "tests/test_a.py::test_one", "tests/test_architecture.py::"
                                     "test_target_tree_has_no_violation_and_no_exception"]}
    assert ex["sha256"] == relabel.sha256_file(tmp_path / "exercise.json.gz") and ex["head"] == doc["head"]
    assert ex["functions"] == 2 and ex["nodes"] == 5


def test_a_class_symbol_counts_any_of_its_methods_and_a_constant_is_never_exercised(tree, tmp_path):
    write(tree, "coverage/ledger-coverage.json", json.dumps({"rows": [
        row(symbol=("codex_harness.research.mod:Thing",)), row(key="api:c", symbol=("codex_harness.research.mod:CONST",))]}))
    git_repo(tree)
    path = exercise_file(tmp_path, {"tests/test_b.py::test_other": [0]})
    doc = build(tree, tmp_path, exercise=path)
    assert doc["exercise"]["symbols"] == {"codex_harness.research.mod:Thing": ["tests/test_b.py::test_other"]}


def test_a_credential_shaped_exercise_node_is_stored_hashed(tree, tmp_path):
    secret = "tests/test_a.py::test_one[sk-ant-" + "A" * 12 + "]"
    write(tree, "coverage/ledger-coverage.json", json.dumps({"rows": [row(symbol=(SYMBOL,))]}))
    git_repo(tree)
    path = exercise_file(tmp_path, {secret: [0]})
    ex = relabel.build_exercise(tree, path, [secret], {}, HEAD, "A/x")
    assert ex["symbols"] == {SYMBOL: [relabel.hashed_id(secret)]} and ex["symbols"][SYMBOL][0].startswith("sha256:")


@pytest.mark.parametrize("kwargs, nodes, why", [
    ({"schema": "zeus:other:1"}, {}, "schema is not"),
    ({"root": "/x/target/tests"}, {}, "root is not the target source root"),
    ({"functions": ["codex_harness.absent.mod:f"]}, {}, "no function module is in " + TP + "src"),
    ({}, {"tests/test_a.py::test_ghost": [0]}, "matches no collected node"),
    ({}, {"tests/test_b.py::test_other": [7]}, "function index outside"),
])
def test_a_mismatching_exercise_record_refuses_the_bundle(tree, tmp_path, kwargs, nodes, why):
    with pytest.raises(relabel.Refused, match=why):
        build_exercised(tree, tmp_path, nodes, **kwargs)


def exercised_bundle(symbols, not_passed=None, nodes=None):
    return {**bundle_for(not_passed=not_passed, nodes=nodes), "exercise": {"symbols": symbols}}


def exercise_row(**more):
    return row(slice_="S7", evidence=("exercise:" + SYMBOL,), symbol=(SYMBOL,), **more)


def test_exercise_passes_iff_a_stored_node_is_collected_and_passing(tree):
    out, engine = run([exercise_row()], tree, exercised_bundle({SYMBOL: ["tests/test_b.py::test_other"]}))
    r = out["api:x.py::f"]
    assert r["status"] == "verified" and r["verification"]["passed"] == ["exercise:" + SYMBOL]
    assert "tests/test_b.py" in engine.supplying, "a changed evidence test module makes the bundle stale (R-L13)"


@pytest.mark.parametrize("bundle, why", [
    (bundle_for(), "no passing node exercised the symbol"),  # a bundle without an exercise record
    (exercised_bundle({}), "no passing node exercised the symbol"),
    (exercised_bundle({SYMBOL: []}), "no passing node exercised the symbol"),
    (exercised_bundle({SYMBOL: ["tests/test_b.py::test_other"]}, not_passed={"tests/test_b.py::test_other": "failure"}),
     "no passing node exercised the symbol"),
    (exercised_bundle({SYMBOL: ["tests/test_b.py::test_gone"]}), "no passing node exercised the symbol"),
])
def test_exercise_without_a_live_passing_node_is_unmet_and_the_row_stays_implemented(tree, bundle, why):
    out, _ = run([exercise_row()], tree, bundle)
    r = out["api:x.py::f"]
    assert r["status"] == "implemented" and has_unmet(r, why)


AU_KEY = "atomic_unit:codex_harness.application.svc:Svc.unit#1"
AU_NODE = f"target:tests/test_s11_atomic_units.py::test_unit_is_structurally_atomic[{AU_KEY[len('atomic_unit:'):]}]"


def au_row(**more):
    return row(kind="atomic_unit", key=AU_KEY, evidence=(PENDING,), symbol=(SYMBOL,), slice_="S7",
               mapping_correction=relabel.AU1_MARK + " symbol survey", **more)


def g1b(**more):
    return {"key": AU_KEY, "pending": PENDING, "replaced_by": ["exercise:" + SYMBOL, AU_NODE], "rule": "G1b",
            "citation": relabel.G1B_CITATION, **more}


def test_g1b_replaces_the_recorder_promise_with_the_exercise_and_the_unit_node(tree):
    unit = AU_NODE[len("target:"):]
    write(tree, TP + "tests/test_s11_atomic_units.py", "def test_unit_is_structurally_atomic():\n    pass\n")
    bundle = exercised_bundle({SYMBOL: ["tests/test_b.py::test_other"]}, nodes=[*NODES, unit])
    new, _ = relabel.relabel({"rows": [au_row()]}, bundle, tree, [g1b()])
    r = new["rows"][0]
    assert r["status"] == "verified" and r["verification"]["passed"] == sorted(["exercise:" + SYMBOL, AU_NODE])
    assert r["evidence"] == [PENDING], "the row stays frozen"
    failing = {**bundle, "not_passed": {unit: "xfail"}}  # a FINDING unit ends xfail: never a pass
    again, _ = relabel.relabel({"rows": [au_row()]}, failing, tree, [g1b()])
    assert again["rows"][0]["status"] == "implemented" and has_unmet(again["rows"][0], "target test not passing")
    absent, _ = relabel.relabel({"rows": [au_row()]}, exercised_bundle({}, nodes=[*NODES, unit]), tree, [g1b()])
    assert absent["rows"][0]["status"] == "implemented" and has_unmet(absent["rows"][0], "no passing node exercised")


@pytest.mark.parametrize("entry, why", [
    (g1b(replaced_by=["exercise:" + SYMBOL]), "exercise item and the unit node"),
    (g1b(replaced_by=["exercise:other:Sym", AU_NODE]), "exercise item and the unit node"),
    (g1b(citation="DESIGN-s11 §5.5"), "cites DESIGN-s11"),
])
def test_a_malformed_g1b_is_refused(tree, entry, why):
    with pytest.raises(relabel.Refused, match=why):
        relabel.relabel({"rows": [au_row()]}, bundle_for(), tree, [entry])


def test_g1b_is_refused_for_a_row_not_mapped_under_r_au1_or_not_an_atomic_unit(tree):
    unmapped = au_row()
    del unmapped["mapping_correction"]
    with pytest.raises(relabel.Refused, match="mapped under R-AU1"):
        relabel.relabel({"rows": [unmapped]}, bundle_for(), tree, [g1b()])
    other = pending_row(key=AU_KEY)
    with pytest.raises(relabel.Refused, match="mapped under R-AU1"):
        relabel.relabel({"rows": [other]}, bundle_for(), tree, [g1b()])


def test_a_transient_module_in_the_exercise_record_is_ignored_and_named(tree, tmp_path):
    write(tree, "coverage/ledger-coverage.json", json.dumps({"rows": [row(symbol=(SYMBOL,))]}))
    git_repo(tree)
    path = exercise_file(tmp_path, {"tests/test_b.py::test_other": [0, 2]}, functions=[*EXERCISE_FUNCTIONS, "codex_harness.adapters._probe:deep"])
    ex = relabel.build_exercise(tree, path, ["tests/test_b.py::test_other"], {}, HEAD, "A/x")
    assert ex["ignored_modules"] == ["codex_harness.adapters._probe"] and list(ex["symbols"]) == [SYMBOL]


# ------------------------------------------------------------- R-MC2-3: a package `__init__` is a marker only when bare

def module_rows(tree, **symbols):
    rows = [row(kind="module", key=f"module:{k}", slice_="S7", symbol=(v,)) for k, v in symbols.items()]
    out, _ = run(rows, tree)
    return {k: out[f"module:{k}"] for k in symbols}


def test_a_bare_package_init_is_still_refused_as_the_module(tree):
    """DESIGN-s11 §10 R-MC2-3 control: an `__init__` of a docstring, imports and `__all__` is a marker, not the module."""
    write(tree, TP + "src/codex_harness/research/__init__.py",
          '"""A layer."""\n\nfrom codex_harness.research import mod\n\n__all__ = ["mod"]\n')
    got = module_rows(tree, bare="codex_harness.research")["bare"]
    assert got["status"] == "designed"
    assert "target symbol is a package marker: codex_harness.research" in got["verification"]["unmet"]


def test_a_package_init_that_defines_behaviour_resolves_as_the_module(tree):
    """DESIGN-s11 §10 R-MC2-3 positive control (the `entry.cli` shape: `parser`/`main` defined in the `__init__`)."""
    write(tree, TP + "src/codex_harness/research/__init__.py", '"""Entry."""\n\n\ndef parser():\n    pass\n\n\ndef main():\n    pass\n')
    assert module_rows(tree, entry="codex_harness.research")["entry"]["status"] == "verified"


def test_the_dotless_top_level_package_resolves_and_a_nonexistent_dotless_name_does_not(tree):
    """DESIGN-s11 §10 R-MC2-3: `codex_harness` is the distribution package; an unknown dotless name is no symbol."""
    got = module_rows(tree, root="codex_harness", ghost="codex_ghost")
    assert got["root"]["status"] == "verified"
    assert got["ghost"]["status"] == "designed"
    assert any(u.startswith("target symbol is not a code symbol") for u in got["ghost"]["verification"]["unmet"])
    absent = module_rows(tree, nowhere="codex_harness.nowhere")["nowhere"]
    assert absent["status"] == "designed"


# ------------------------------------------------------------------------------------ flow rows (DESIGN-s11 §11 R-FLOW)

FLOW_STEPS = ("codex_harness.research.mod:Thing", "codex_harness.research.mod:Thing.go")
FLOW_ITEMS = ("compare:fam", "target:tests/test_b.py::test_other")


def flow(evidence=FLOW_ITEMS, symbol=FLOW_STEPS):
    return row(kind="flow", key="flow:a traced flow", evidence=evidence, symbol=symbol, owner="research", slice_="S7")


def test_a_flow_is_verified_when_every_step_symbol_resolves_and_every_item_passes(tree):
    out, _ = run([flow()], tree)
    assert out["flow:a traced flow"]["status"] == "verified"
    assert out["flow:a traced flow"]["verification"]["passed"] == sorted(FLOW_ITEMS)


@pytest.mark.parametrize("failed", FLOW_ITEMS)
def test_one_failing_item_leaves_the_flow_implemented_and_names_the_item(tree, failed):
    # R-FLOW: one passing family never verifies a whole flow.
    compare = {"fam": {"target": "equal", "reference": "equal", "origin_ok": True, "target_origin_ok": True}}
    if failed.startswith("compare:"):
        compare["fam"]["target"] = "differs"
        bundle = bundle_for(compare=compare)
    else:
        bundle = bundle_for(not_passed={"tests/test_b.py::test_other": "failure"})
    out, _ = run([flow()], tree, bundle)
    assert out["flow:a traced flow"]["status"] == "implemented"
    assert has_unmet(out["flow:a traced flow"], "compare not equal: compare:fam" if failed.startswith("compare:")
                     else "target test not passing: target:tests/test_b.py::test_other")


def test_a_missing_step_symbol_leaves_the_flow_unverified(tree):
    out, _ = run([flow(symbol=(*FLOW_STEPS, "codex_harness.research.mod:Absent"))], tree)
    assert out["flow:a traced flow"]["status"] == "designed"
    assert has_unmet(out["flow:a traced flow"], "target symbol does not resolve: codex_harness.research.mod:Absent")


@pytest.mark.parametrize("extra, prefix", [("compare:nodrv", "flow item is not an executable item: compare:nodrv"),
                                           ("static:compare/x.json#y", "flow item is not an executable item: static:"),
                                           ("pending: flow scenarios in the owning slices", "pending: flow scenarios")])
def test_a_context_or_pending_item_never_verifies_a_flow_step(tree, extra, prefix):
    out, _ = run([flow(evidence=(*FLOW_ITEMS, extra))], tree)
    assert out["flow:a traced flow"]["status"] != "verified"
    assert has_unmet(out["flow:a traced flow"], prefix)


def test_a_flow_with_no_listed_item_is_not_verified(tree):
    out, _ = run([flow(evidence=())], tree)
    assert out["flow:a traced flow"]["status"] == "designed"
    assert has_unmet(out["flow:a traced flow"], "no passing executable item")


def test_addition_contract_requires_registry_and_behavioural_citation(tree):
    c, bundle = cited_by(tree, BEHAVIOURAL_NODE)
    c.update(kind='addition', key='addition:delivery/contract/INV-X-001', intent='addition:owner')
    unknown = dict(c, key='addition:delivery/contract/INV-Z-001')
    uncited = dict(c, key='addition:delivery/contract/INV-Y-001')
    out, _ = run([c, unknown, uncited], tree, bundle)
    assert out[c['key']]['status'] == 'verified'
    assert 'cites:INV-X-001' in out[c['key']]['verification']['passed']
    assert has_unmet(out[unknown['key']], 'contract not in docs/contracts.md')
    assert has_unmet(out[uncited['key']], 'no passing target test cites the contract')
    c, bundle = cited_by(tree, STRUCTURAL_NODE)
    c.update(kind='addition', key='addition:delivery/contract/INV-X-001', intent='addition:owner')
    out, _ = run([c], tree, bundle)
    assert has_unmet(out[c['key']], 'cited only by structural nodes')


def test_real_addition_contract_passes_registry_and_citation_rule():
    ledger = json.loads((ROOT / 'coverage/ledger-coverage.json').read_text())
    r = next(r for r in ledger['rows'] if r['key'] ==
             'addition:delivery/contract/INV-HOST-DELIVERY-MAINTENANCE-001')
    bundle = json.loads((ROOT / 'coverage/run-evidence.json').read_text())
    engine = relabel.Relabel(ROOT, bundle)
    status, verification = engine.evaluate(r)
    assert engine.symbol(r)[0]
    assert 'cites:INV-HOST-DELIVERY-MAINTENANCE-001' in verification.get('passed', [])
    assert not any('contract not in' in u or 'test cites the contract' in u
                   for u in verification.get('unmet', []))
    assert status in {'implemented', 'verified'}
