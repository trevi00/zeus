"""AR4 node map of the two approved rebaselines: `coverage/rebaseline-node-map.json` (separate from the M7 map).

Expected results (spec cut-int-ar4-rebaseline-node-map): pr3-bb579d5 maps 412 ported nodes (RULE7-WRITER-FACTS: 413 target
nodes in the 13 ported files, one target-only); main-s2r-b9d8f15 maps every collected node (232), its two nodes replaced by
PR-3 are `superseded` by pr3-bb579d5, the rest `ported`. Every ported target is collected at HEAD. Each check has a control.
"""

import importlib.util
import json
import subprocess
import sys
from collections import Counter

import pytest
from _layout import REPO

SPEC = importlib.util.spec_from_file_location("test_node_map", REPO / "coverage" / "test_node_map.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)

MAIN, PR3 = "main-s2r-b9d8f15", "pr3-bb579d5"
COLLECTED = {MAIN: 232, PR3: 412}  # node counts collected at each entry's own commit (header of each ids file)
REPLACED = {
    "tests/test_host_delivery_maintenance.py::test_pr2_observer_refuses_during_the_open_maintenance",
    "tests/test_host_delivery_maintenance_e2e.py::test_one_active_generation_is_restarted_and_held_open_end_to_end",
}


@pytest.fixture(scope="module")
def target_ids():
    return gen.collect_target_ids()


@pytest.fixture(scope="module")
def mapping():
    return json.loads(gen.REBASELINE_OUT.read_text(encoding="utf-8"))


def problems(mapping, entry_ids, target_ids):
    found = []
    target = set(target_ids)
    if sorted(mapping) != sorted(entry_ids):
        found.append("entries differ")
    for entry, nodes in mapping.items():
        expected = set(entry_ids.get(entry, ()))
        found += [f"missing key {k}" for k in sorted(expected - set(nodes))[:5]]
        found += [f"extra key {k}" for k in sorted(set(nodes) - expected)[:5]]
        for node, item in nodes.items():
            kind = item.get("kind")
            if kind == "ported":
                if item["target"] not in target:
                    found.append(f"missing target {item['target']}")
            elif kind == "superseded":
                if item["by"] not in entry_ids or item["by"] == entry:
                    found.append(f"bad superseded.by {item['by']}")
            else:
                found.append(f"unknown kind {kind} for {node}")
    return found


@pytest.fixture(scope="module")
def entry_ids():
    return {e: gen.read_rebaseline_ids(e) for e in gen.rebaseline_entries()}


def test_entries_are_the_two_approved_rebaselines(mapping, entry_ids):
    assert gen.rebaseline_entries() == [MAIN, PR3]
    assert sorted(mapping) == [MAIN, PR3]
    assert {e: len(v) for e, v in entry_ids.items()} == COLLECTED


def test_per_entry_counts(mapping):
    assert Counter(v["kind"] for v in mapping[PR3].values()) == {"ported": 412}
    assert Counter(v["kind"] for v in mapping[MAIN].values()) == {"ported": 230, "superseded": 2}
    assert {k for k, v in mapping[MAIN].items() if v["kind"] == "superseded"} == REPLACED


def test_map_is_complete_and_every_target_is_collected(mapping, entry_ids, target_ids):
    assert problems(mapping, entry_ids, target_ids) == []
    assert all(v["by"] == PR3 for v in mapping[MAIN].values() if v["kind"] == "superseded")


def test_rebaseline_check_is_byte_equal():
    done = subprocess.run([sys.executable, "-B", str(REPO / "coverage" / "test_node_map.py"), "--rebaseline", "--check"],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout


def test_the_m7_map_is_not_changed_by_the_rebaseline_nodes(entry_ids):
    m7 = json.loads(gen.OUT.read_text(encoding="utf-8"))
    assert len(m7) == 6569
    assert not any(n in m7 for nodes in entry_ids.values() for n in nodes if n not in set(gen.read_m7_ids()))


def test_negative_control_extra_node(mapping, entry_ids, target_ids):
    broken = {**mapping, PR3: {**mapping[PR3], "tests/test_none.py::test_extra": {"kind": "ported", "target": "tests/ported/x.py::y"}}}
    assert any(p.startswith("extra key") for p in problems(broken, entry_ids, target_ids))


def test_negative_control_missing_target(mapping, entry_ids, target_ids):
    node = next(iter(mapping[PR3]))
    broken = {**mapping, PR3: {**mapping[PR3], node: {"kind": "ported", "target": mapping[PR3][node]["target"] + "_renamed"}}}
    assert any(p.startswith("missing target") for p in problems(broken, entry_ids, target_ids))


def test_negative_control_unknown_kind(mapping, entry_ids, target_ids):
    node = next(iter(mapping[PR3]))
    broken = {**mapping, PR3: {**mapping[PR3], node: {"kind": "pending_root_script"}}}
    assert any(p.startswith("unknown kind") for p in problems(broken, entry_ids, target_ids))


def test_negative_control_superseded_by_itself(mapping, entry_ids, target_ids):
    node = sorted(REPLACED)[0]
    broken = {**mapping, MAIN: {**mapping[MAIN], node: {"kind": "superseded", "by": MAIN}}}
    assert any(p.startswith("bad superseded.by") for p in problems(broken, entry_ids, target_ids))


def test_writer_refuses_an_unmapped_node(target_ids):
    with pytest.raises(SystemExit, match="unmapped_rebaseline_node"):
        gen.build_rebaseline({MAIN: ["tests/test_none.py::test_nothing"], PR3: []}, target_ids)
