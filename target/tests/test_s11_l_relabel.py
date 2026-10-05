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

ROOT = Path(__file__).resolve().parents[2]
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


def make_tree(root: Path) -> None:
    write(root, "target/src/codex_harness/__init__.py")
    write(root, "target/src/codex_harness/research/__init__.py")
    write(root, "target/src/codex_harness/research/mod.py", "class Thing:\n    def go(self):\n        pass\n\nCONST = 1\n")
    write(root, "target/src/codex_harness/research/ports.py", 'OWNED_BUCKETS = ("alpha", "beta")\n')
    write(root, "target/src/codex_harness/coordination/__init__.py")
    write(root, "target/src/codex_harness/coordination/ports.py", 'OWNED_BUCKETS = ("beta", "gamma")\n')
    write(root, "target/pyproject.toml", '[project.scripts]\nharness = "codex_harness.research.mod:Thing"\n')
    write(root, "target/uv.lock", "lock\n")
    write(root, "docs/contracts.md", "| ID | C |\n|---|---|\n| INV-X-001 | a |\n| INV-Y-001 | b |\n")
    write(root, "docs/context/ARCHITECTURE.md", ARCH)
    write(root, "compare/scenarios/fam.json", json.dumps({"family": "fam", "target_driver": "drivers/fam.py"}))
    write(root, "compare/scenarios/nodrv.json", json.dumps({"family": "nodrv", "target_driver": None}))
    write(root, "target/tests/conftest.py", "# conftest\n")
    write(root, "target/tests/test_a.py",
          '"""Cites INV-X-001 at module level only in this docstring."""\n\n\ndef test_one():\n    pass\n\n\n'
          'def test_two():\n    # INV-Y-001 is cited only here\n    pass\n')
    write(root, "target/tests/test_b.py", "def test_other():\n    pass\n")
    write(root, "target/tests/ported/test_old.py", "def test_p():\n    pass\n")
    write(root, "target/tests/test_architecture.py", "def test_target_tree_has_no_violation_and_no_exception():\n    pass\n")


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


def junit(tmp_path, *cases):
    body = "".join(f'<testcase classname="{c}" name="{n}" time="0.0">{child}</testcase>' for c, n, child in cases)
    path = tmp_path / "j.xml"
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


def build(tree, tmp_path, cases=CASES, collected=COLLECTED, compare=None, owner=()):
    git_repo(tree)
    report = tmp_path / "c.json"
    report.write_text(json.dumps(compare or {"ok": True, "scenarios": {"fam": {
        "target": "equal", "reference": "equal", "origin_ok": True, "target_origin_ok": True}}}))
    return relabel.build_bundle(tree, junit(tmp_path, *cases), [report], list(owner), "HEAD", list(collected), None)


def test_the_bundle_records_the_outcomes_ids_and_compare_reports(tree, tmp_path):
    doc = build(tree, tmp_path)
    assert doc["head"] == subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True,
                                         text=True).stdout.strip()
    assert doc["not_passed"] == {"tests/test_a.py::test_two": "skipped"}
    assert doc["compare"]["fam"]["target"] == "equal" and set(doc["ids"]) == {
        "target/src", "compare", "target/pyproject.toml", "target/uv.lock"}
    assert "target/tests/conftest.py" in doc["support"] and "target/tests/test_a.py" in doc["test_modules"]


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


def test_a_test_module_added_after_the_evidence_head_is_not_part_of_the_evidence(tree, tmp_path):
    git_repo(tree)
    write(tree, "target/tests/test_new.py", "def test_new():\n    pass\n")
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"ok": True, "scenarios": {}}))
    doc = relabel.build_bundle(tree, junit(tmp_path, *CASES), [report], [], "HEAD", [*COLLECTED, "tests/test_new.py::test_new"])
    assert "tests/test_new.py::test_new" not in doc["nodes"]


def test_a_changed_bound_input_at_bundle_time_refuses(tree, tmp_path):
    git_repo(tree)
    write(tree, "target/src/codex_harness/research/mod.py", "changed = 1\n")
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"ok": True, "scenarios": {}}))
    with pytest.raises(relabel.Refused, match="differs from the evidence head"):
        relabel.build_bundle(tree, junit(tmp_path, *CASES), [report], [], "HEAD", COLLECTED)


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
    out, _ = run([row(slice_="S7", evidence=("compare:nodrv",)), row(key="api:y", slice_="S7", evidence=("compare:other",))],
                 tree)
    assert has_unmet(out["api:x.py::f"], "compare family has no target driver")
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
                   row(key="api:y", slice_="S7", evidence=("reference:+3 more test files",))], tree)
    assert has_unmet(none["api:x.py::f"], "reference has no same-name ported file")
    assert has_unmet(none["api:y"], "unnamed reference test files")


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
    write(tree, "target/src/codex_harness/delivery/__init__.py")
    write(tree, "target/src/codex_harness/delivery/adapters/__init__.py")
    write(tree, "target/src/codex_harness/delivery/adapters/host_migration.py",
          'FLEET_OWNER_FILE = "fleet-owner.json"\nFLEET_OWNER_SCHEMA = "urn"\nSWITCH_UNITS = ("a",)\n')
    write(tree, "target/tests/ported/test_host_migration_successor.py", "def test_h():\n    pass\n")
    write(tree, "target/src/codex_harness/research/ports.py", 'OWNED_BUCKETS = ("alpha", "discovery_pressure")\n')
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
    write(tree, "target/tests/test_unrelated_new.py", "def test_new():\n    pass\n")
    commit(tree)
    assert relabel.freshness(tree, doc, supplying) == []  # a new, unrelated test module
    write(tree, "target/tests/test_a.py", "def test_one():\n    assert True\n")
    commit(tree)
    assert relabel.freshness(tree, doc, supplying) == []  # a changed module that supplies no evidence
    write(tree, "target/tests/test_b.py", "def test_other():\n    assert 1\n")
    commit(tree)
    assert any("test_b.py" in p for p in relabel.freshness(tree, doc, supplying))  # a changed evidence module
    git_repo_reset = ["checkout", "-q", "HEAD~1", "--", "target/tests/test_b.py"]
    subprocess.run(["git", "-C", str(tree), *git_repo_reset], check=True, capture_output=True)
    commit(tree)
    assert relabel.freshness(tree, doc, supplying) == []
    write(tree, "target/tests/conftest.py", "# changed\n")
    commit(tree)
    assert any("conftest.py" in p for p in relabel.freshness(tree, doc, supplying))
    subprocess.run(["git", "-C", str(tree), "checkout", "-q", "HEAD~1", "--", "target/tests/conftest.py"], check=True)
    write(tree, "target/src/codex_harness/research/mod.py", "class Thing:\n    pass\n")
    commit(tree)
    assert any(p.startswith("target/src changed") for p in relabel.freshness(tree, doc, supplying))


def test_a_new_support_file_under_target_tests_makes_the_bundle_stale(tree, tmp_path):
    doc = build(tree, tmp_path)
    write(tree, "target/tests/fixtures/extra.json", "{}")
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
    for rel in ("docs", "compare", "target/src", "target/tests", "target/pyproject.toml"):
        (tmp_path / rel).symlink_to(ROOT / rel)
    assert relabel.main(["--root", str(tmp_path), "--check"]) == 1


def test_every_row_records_its_verification_at_the_bundle_head(ledger, committed):
    for r in ledger["rows"]:
        v = r["verification"]
        assert v["head"] == committed["head"], r["key"]
        assert bool(v.get("passed")) == (r["status"] == "verified"), r["key"]
        assert bool(v.get("unmet")) == (r["status"] != "verified"), r["key"]
        if r["status"] != "verified":
            assert r["status"] in {"unmapped", "designed", "implemented"}, r["key"]


def test_the_bundle_binds_the_evidence_inputs(committed):
    assert committed["schema"] == relabel.BUNDLE_SCHEMA and len(committed["head"]) == 40
    assert set(committed["ids"]) == {"target/src", "compare", "target/pyproject.toml", "target/uv.lock"}
    assert "target/tests/conftest.py" in committed["support"]
    assert not any(p.rsplit("/", 1)[-1].startswith("test_") for p in committed["support"])
    assert set(committed["not_passed"]) <= set(committed["nodes"])
    assert set(committed["not_passed"].values()) <= {"skipped", "xfail"}  # a failing evidence run is never bundled
    assert not any(p.startswith("/") for p in [*committed["owner_run"], *committed["inputs"]])
