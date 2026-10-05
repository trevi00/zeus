"""S11 R-L3d-1: block selection by reference-side runtime evidence (DESIGN-s11 §17).

Expected results come from the design's rule (§17 item 4 (i)-(iii)) and its controls (§17 item 5), driven with SYNTHETIC records
(no product import), the way `test_s11_l3_unit_table.py` drives the table: an entry `basis: "block_exercise"` exists iff the block
is joined by no rules 1-3 entry, is recorded in a rule-6 case of the golden unit, and (when it lists non-`<dynamic>` literal
writes) one of them is among that case's durable buckets. The recorder is driven through its public window verbs on a synthetic
module file. The committed artifacts are checked against the committed goldens and catalogue (requirements, not the table).
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "coverage"), str(ROOT / "compare/harness")]
try:
    import block_exercise as be
    import effects_unit_table as eut
finally:
    del sys.path[:2]

DRIVER = '''
def run(api):
    return {"unit": {v: scenario(api, v) for v in ("success", "a_failure_at_row")}}

def scenario(api, variant):
    return api.store.unit(variant)
'''
MODULE = "codex_harness.application.svc"
JOINED = f"{MODULE}:Svc.unit#1"
HELPER = f"{MODULE}:Svc.helper#1"
CASE = {"durable_writes": [["research_rows", ""]], "effects": []}


def block(n, writes, scope="Svc.unit"):
    return {"key": f"{MODULE}:{scope}#{n}", "line": n * 10, "literal_writes": writes, "module": MODULE, "scope": scope}


def join(artifact, helper_writes=("research_rows",), case=CASE, golden=None):
    """The rules 1-3 join of `Svc.unit` plus a `Svc.helper` block that only the artifact can reach."""
    golden = {"unit": {"success": case, "a_failure_at_row": case}} if golden is None else golden
    blocks = [block(1, ["research_rows"]), block(1, list(helper_writes), scope="Svc.helper")]
    path = "compare/drivers/reference/d.py"
    driver = eut.Driver({path: "from codex_harness.application import svc\n" + DRIVER}, path)
    cases = None if artifact is None else {"schema": be.SCHEMA, "family": "effects.fam", "cases": artifact}
    return eut.join_family("effects.fam", driver, golden, blocks, cases)


def exercised(out):
    return [e for e in out["entries"] if e.get("basis") == "block_exercise"]


def test_an_executed_block_with_an_observed_literal_write_is_an_entry():
    out = join({"a_failure_at_row": [HELPER]})
    assert exercised(out) == [{"family": "effects.fam", "golden_unit": "unit", "atomic_unit": HELPER, "block": "#1",
                               "basis": "block_exercise", "cases": ["a"], "case": "a_failure_at_row",
                               "writes_observed": ["research_rows"]}]


def test_a_block_no_case_executed_is_no_entry():
    assert exercised(join({"a_failure_at_row": []})) == [] and exercised(join({})) == []


def test_negative_control_an_executed_block_whose_literal_writes_were_not_observed_is_no_entry():
    assert exercised(join({"a_failure_at_row": [HELPER]}, helper_writes=["other_rows"])) == []
    both = ["other_rows", "<dynamic>"]  # a `<dynamic>` write is never observable evidence
    assert exercised(join({"a_failure_at_row": [HELPER]}, helper_writes=both)) == []


def test_a_block_without_literal_writes_is_credited_on_execution_alone_and_says_so():
    for writes in ([], ["<dynamic>"]):
        (entry,) = exercised(join({"a_failure_at_row": [HELPER]}, helper_writes=writes))
        assert entry["writes_observed"] is None and entry["atomic_unit"] == HELPER


def test_the_rows_read_back_from_the_store_count_as_observed_buckets():
    case = {"durable_authority_writes": [], "durable_rows_changed": [["research_rows", "retry"]]}
    golden = {"unit": {"success": case, "a_failure_at_row": case}}
    (entry,) = exercised(join({"a_failure_at_row": [HELPER]}, case=case, golden=golden))
    assert entry["writes_observed"] == ["research_rows"]


def test_only_a_rule6_case_counts():
    assert exercised(join({"success": [HELPER]})) == []


def test_a_row_joined_by_rules_1_to_3_gets_no_second_resolution():
    out = join({"a_failure_at_row": [JOINED, HELPER]})
    rows = [(e["atomic_unit"], e.get("basis")) for e in out["entries"]]
    assert rows == [(JOINED, None), (HELPER, "block_exercise")]
    assert out["entries"][0]["driver_call"].endswith("d.py:7")


def test_a_family_without_a_blocks_artifact_gets_no_entry():
    out = join(None)
    assert exercised(out) == [] and [e["atomic_unit"] for e in out["entries"]] == [JOINED]


def test_the_letters_and_the_first_case_are_those_of_the_cases_that_executed_the_block():
    case = {"durable_writes": [["research_rows", ""]]}
    golden = {"unit": {"success": case, "a_x": case, "b_y": case, "c_z": case}}
    (entry,) = exercised(join({"a_x": [HELPER], "c_z": [HELPER], "success": [HELPER]}, golden=golden))
    assert (entry["cases"], entry["case"]) == (["a", "c"], "a_x")


# ---------------------------------------------------------------------------------------------------------- the recorder
SYNTHETIC = "def unit(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total\n\n\ndef other():\n    return 1\n"


def synthetic(tmp_path):
    package = tmp_path / "pkg" / "codex_harness"
    package.mkdir(parents=True)
    path = package / "svc.py"
    path.write_text(SYNTHETIC, encoding="utf-8")
    scope = {}
    exec(compile(SYNTHETIC, str(path), "exec"), scope)
    return scope


def test_the_recorder_unarmed_takes_no_tool_and_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv(be.ENV, raising=False)
    monkeypatch.setattr(be, "_recorder", None)
    before = sys.monitoring.get_tool(be.TOOL)
    be.open("case")
    be.close()
    be.assign(["case"])
    assert before is None and sys.monitoring.get_tool(be.TOOL) is None and be._recorder is None
    assert list(tmp_path.iterdir()) == []


def test_the_recorder_armed_records_the_blocks_executed_inside_a_window_only(monkeypatch, tmp_path):
    scope = synthetic(tmp_path)
    out = tmp_path / "out.json"
    monkeypatch.setenv(be.ENV, str(out))
    monkeypatch.setattr(be, "_recorder", be.Recorder({("codex_harness/svc.py", 4): "svc:unit#1", ("codex_harness/svc.py", 9): "svc:other#1"}, out))
    try:
        scope["unit"](1)  # before any window: not recorded
        be.open("first")
        scope["unit"](2)
        be.close()
        scope["other"]()  # between windows: not recorded
        be.open("second")  # restart_events: a location the first window already saw is seen again
        scope["unit"](2)
        scope["other"]()
        be.close()
        be.open("empty")
        be.close()
        assert json.loads(out.read_text(encoding="utf-8")) == {
            "empty": [], "first": ["svc:unit#1"], "second": ["svc:other#1", "svc:unit#1"]}
        be.assign(["a", "b", "c"])
        assert sorted(json.loads(out.read_text(encoding="utf-8"))) == ["a", "b", "c"]
        with pytest.raises(SystemExit):
            be.assign(["only-one"])
    finally:
        be._recorder.release()
    assert sys.monitoring.get_tool(be.TOOL) is None


def test_the_artifact_writer_is_deterministic_and_sorted():
    one = be.artifact("effects.fam", {"b": ["y", "x", "x"], "a": []})
    two = be.artifact("effects.fam", {"a": [], "b": ["x", "y"]})
    assert one == two == (
        '{\n "cases": {\n  "a": [],\n  "b": [\n   "x",\n   "y"\n  ]\n },\n "family": "effects.fam",\n'
        ' "schema": "zeus:s11-block-exercise:1"\n}\n')


def test_the_environment_variable_is_the_only_arming_route():
    assert be.ENV == "ZEUS_BLOCK_EXERCISE_OUT" and os.environ.get(be.ENV) is None


# --------------------------------------------------------------------------------------------- the committed artifacts
FAMILIES = ("effects.admission_unit", "effects.decision_unit")
REFERENCE = ROOT / "compare/goldens/reference"


@pytest.mark.parametrize("family", FAMILIES)
def test_the_committed_blocks_artifact_names_the_golden_cases_and_catalogue_blocks(family):
    artifact = json.loads((REFERENCE / f"{family}.blocks.json").read_text(encoding="utf-8"))
    golden = json.loads((REFERENCE / f"{family}.json").read_text(encoding="utf-8"))
    catalogue = {u["key"] for u in json.loads((REFERENCE / "static.source.json").read_text(encoding="utf-8"))
                 ["transaction_blocks"]["units"]}
    assert (artifact["schema"], artifact["family"]) == (be.SCHEMA, family)
    assert set(artifact["cases"]) == set(golden)
    assert all(v == sorted(set(v)) and set(v) <= catalogue for v in artifact["cases"].values())
    assert (REFERENCE / f"{family}.blocks.json").read_text(encoding="utf-8") == be.artifact(family, artifact["cases"])


def test_the_decide_one_example_of_the_design_executes_block_1_and_not_2_or_3():
    artifact = json.loads((REFERENCE / "effects.decision_unit.blocks.json").read_text(encoding="utf-8"))["cases"]
    table = json.loads((ROOT / "coverage/effects-unit-table.json").read_text(encoding="utf-8"))["entries"]
    base = "codex_harness.adapters.executor:Executor.decide_one"
    assert f"{base}#1" in artifact["a_failure_before_decision_review_lead"]
    assert not {f"{base}#2", f"{base}#3"} & {k for v in artifact.values() for k in v}
    (entry,) = [e for e in table if e["atomic_unit"] == f"{base}#1" and e["family"] == "effects.decision_unit"]
    assert entry["basis"] == "block_exercise" and entry["writes_observed"] == ["decisions_pending"]


def test_the_committed_exercise_entries_satisfy_the_rule_against_the_committed_records():
    table = json.loads((ROOT / "coverage/effects-unit-table.json").read_text(encoding="utf-8"))["entries"]
    catalogue = {u["key"]: u for u in json.loads((REFERENCE / "static.source.json").read_text(encoding="utf-8"))
                 ["transaction_blocks"]["units"]}
    rows = [e for e in table if e.get("basis") == "block_exercise"]
    assert rows and {e["family"] for e in rows} <= set(FAMILIES)
    for e in rows:
        artifact = json.loads((REFERENCE / f"{e['family']}.blocks.json").read_text(encoding="utf-8"))["cases"]
        golden = json.loads((REFERENCE / f"{e['family']}.json").read_text(encoding="utf-8"))
        assert e["atomic_unit"] in artifact[e["case"]] and eut.rule6_letter(e["case"]) in e["cases"]
        assert not [t for t in table if t["family"] == e["family"] and t["atomic_unit"] == e["atomic_unit"] and "basis" not in t]
        literal = [w for w in catalogue[e["atomic_unit"]]["literal_writes"] if w != "<dynamic>"]
        if literal:
            assert e["writes_observed"] and set(e["writes_observed"]) <= set(literal) & eut.observed_buckets(golden[e["case"]])
        else:
            assert e["writes_observed"] is None
    pg = [e for e in table if e["family"].endswith(".pg") and e.get("basis")]
    assert pg == []  # the `.pg` blocks artifacts are recorded by the owner at integration
