#!/usr/bin/env python3
"""AR4 node-ID map: every M7 pytest node ID -> a ported target node, a named target architecture node, or a pending
root-script disposition (S11 unit M; DESIGN-s11 §4 R-M1..R-M4, §6).

Layer: harness (never shipped); standard library only. Reuses the exact-ID rule of the unit M preparation
(`evidence/rebuild/s11/m-prep-e8edcca1/gen_node_map.py`, `build`), reduced to the three kinds the owner defined.

    uv run python coverage/test_node_map.py            # write coverage/test-node-map.json
    uv run python coverage/test_node_map.py --check    # regenerate in memory; exit 0 only when byte-equal to the written file
    uv run python coverage/test_node_map.py --stats    # kind counts
    uv run python coverage/test_node_map.py --rebaseline          # write coverage/rebaseline-node-map.json
    uv run python coverage/test_node_map.py --rebaseline --check  # regenerate in memory; byte equality (--stats works too)

Rebaseline mode (AR4, the two approved rebaselines of compare/baseline.json): inputs are
`coverage/rebaseline-node-ids/<entry id>.txt`, the node IDs collected at that entry's own commit over its delta test
modules (command, commit and date in each header). Shape: {entry: {node: {kind: ported, target} | {kind: superseded, by}}}.
A node is `ported` when its `tests/ported/` twin is collected at HEAD, `superseded` by the other entry when it is one of
SUPERSEDED (REBASELINE facts: PR-3 replaced it), else the write fails (`unmapped_rebaseline_node`). The M7 map is not touched.

Inputs: `coverage/m7-node-ids.txt` (the SOURCE collection, command and commit in its header) and the target collection,
read live (`pytest --collect-only -q` in `target/`, node IDs gain the `target/` prefix). A node that fits no kind is an error.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
# the one layout constant per tool (DESIGN-s11 §20.5)
from layout import TARGET_DIR, TARGET_PREFIX  # noqa: E402

M7_IDS = HERE / "m7-node-ids.txt"
OUT = HERE / "test-node-map.json"
REBASELINE_IDS = HERE / "rebaseline-node-ids"
REBASELINE_OUT = HERE / "rebaseline-node-map.json"
SUPERSEDED_BY = "pr3-bb579d5"  # the entry whose tests replaced the nodes below
# The two main-s2r nodes PR-3 replaced (RULE7-WRITER-FACTS: not collected in pr3-bb579d5, no twin at HEAD).
SUPERSEDED = {
    "main-s2r-b9d8f15": (
        "tests/test_host_delivery_maintenance.py::test_pr2_observer_refuses_during_the_open_maintenance",
        "tests/test_host_delivery_maintenance_e2e.py::test_one_active_generation_is_restarted_and_held_open_end_to_end",
    ),
}

# R-M3: the 4 nodes of M7 tests/test_architecture.py, each mapped to the named target node(s) enforcing the same rule.
ARCHITECTURE = {
    "tests/test_architecture.py::test_inner_layers_do_not_import_adapters_or_sdk": {
        "targets": [TARGET_PREFIX + "tests/test_architecture.py::test_target_tree_has_no_violation_and_no_exception"],
        "reason": "target layer rule: import_rules.check over target/src (domain/application never reach adapters or SDKs)"},
    "tests/test_architecture.py::test_invariant_comments_resolve_to_contract_registry": {
        "targets": [TARGET_PREFIX + "tests/test_s11_ar4_node_map.py::test_invariant_comments_resolve_to_contract_registry"],
        "reason": "no pre-existing target test checked @invariant comments (finding); the same check is retargeted at target/src"},
    "tests/test_architecture.py::test_tests_assert_behavior_not_source_text": {
        "targets": [TARGET_PREFIX + "tests/test_s11_fa009.py::test_tests_assert_behavior_not_source_text"],
        "reason": "FA-009 detector retargeted at target/tests"},
    "tests/test_architecture.py::test_wiring_detector_has_positive_and_negative_controls": {
        "targets": [TARGET_PREFIX + "tests/test_s11_fa009.py::test_wiring_detector_has_positive_and_negative_controls"],
        "reason": "FA-009 detector controls retargeted at target/tests"},
}
# R-M4: PREP-S11 §9 #3. Emptied by DESIGN-s11 §7 R-S4: wsl_port_probe and claude_real_call are ported to target/scripts,
# and their M7 tests (test_probe_ownership 10, test_runner_evidence 23) are ported with identical node IDs.
PENDING_FILES: tuple[str, ...] = ()
PENDING_REASON = "PREP-S11 §9 #3: the root-script disposition at unit P"


# compare/run.py check-tree refuses any added file holding a URL with a password in its userinfo; 9 M7 parametrize IDs embed fake DSNs.
# On disk every `://` is written `:\x2f\x2f` (no M7 ID contains the backslash form), so the stored files stay clean while the
# keys and targets in memory are the exact node IDs.
ESCAPED_SLASHES = ":\\x2f\\x2f"


def read_m7_ids(path: Path = M7_IDS) -> list[str]:
    lines = path.read_text(encoding="utf-8").replace(ESCAPED_SLASHES, "://").splitlines()
    return [x for x in lines if x and not x.startswith("#")]


def read_rebaseline_ids(entry: str) -> list[str]:
    return read_m7_ids(REBASELINE_IDS / f"{entry}.txt")


def rebaseline_entries() -> list[str]:
    """Entry ids of compare/baseline.json `approved_rebaselines`, in file order."""
    data = json.loads((ROOT / "compare" / "baseline.json").read_text(encoding="utf-8"))
    return [e["id"] for e in data["approved_rebaselines"]]


def collect_target_ids(cwd: Path | None = None, timeout: float | None = None) -> list[str]:
    """Target collection at the working tree, IDs prefixed `target/` (nodeids are relative to `-c`'s directory).

    Never `uv`: the release evaluator runs this with a restricted PATH. `sys.executable` is the interpreter that holds the
    package under test; `-c` makes the tests' own tree the rootdir, so the ids are the same whatever the cwd is."""
    tree = ROOT / TARGET_DIR
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                           str(tree / "tests"), "-c", str(tree / "pyproject.toml")],
                          cwd=Path.cwd() if cwd is None else cwd, capture_output=True, text=True, check=True, timeout=timeout)
    return sorted(TARGET_PREFIX + x for x in done.stdout.splitlines() if "::" in x)


def build(m7_ids: list[str], target_ids: list[str]) -> dict[str, dict]:
    target = set(target_ids)
    result: dict[str, dict] = {}
    bad: list[str] = []
    for node in m7_ids:
        file = node.partition("::")[0]
        twin = TARGET_PREFIX + "tests/ported/" + node[len("tests/"):]
        if file in PENDING_FILES:
            result[node] = {"kind": "pending_root_script", "reason": PENDING_REASON}
        elif node in ARCHITECTURE:
            entry = ARCHITECTURE[node]
            if not all(t in target for t in entry["targets"]):
                bad.append(node)
            result[node] = {"kind": "architecture", "targets": entry["targets"], "reason": entry["reason"]}
        elif twin in target:
            result[node] = {"kind": "ported", "target": twin}
        else:
            bad.append(node)
    if bad:
        raise SystemExit(f"{len(bad)} M7 nodes fit no kind or name a missing target node, first: {bad[0]}")
    return {k: result[k] for k in sorted(result)}


def build_rebaseline(entry_ids: dict[str, list[str]], target_ids: list[str]) -> dict[str, dict[str, dict]]:
    target = set(target_ids)
    result: dict[str, dict[str, dict]] = {}
    bad: list[str] = []
    for entry, nodes in entry_ids.items():
        other = [e for e in entry_ids if e != entry]
        mapped: dict[str, dict] = {}
        for node in nodes:
            twin = TARGET_PREFIX + "tests/ported/" + node[len("tests/"):]
            if twin in target:
                mapped[node] = {"kind": "ported", "target": twin}
            elif node in SUPERSEDED.get(entry, ()) and other == [SUPERSEDED_BY]:
                mapped[node] = {"kind": "superseded", "by": SUPERSEDED_BY}
            else:
                bad.append(f"{entry} {node}")
        result[entry] = {k: mapped[k] for k in sorted(mapped)}
    if bad:
        raise SystemExit(f"unmapped_rebaseline_node: {len(bad)} nodes are neither ported nor superseded, first: {bad[0]}")
    return {k: result[k] for k in sorted(result)}


def render(data: dict) -> str:
    text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    return text.replace("://", ESCAPED_SLASHES.replace("\\x2f", "\\u002f"))  # a valid JSON escape of the same two slashes


def generate() -> str:
    return render(build(read_m7_ids(), collect_target_ids()))


def generate_rebaseline() -> str:
    ids = {e: read_rebaseline_ids(e) for e in rebaseline_entries()}
    return render(build_rebaseline(ids, collect_target_ids()))


def main(argv: list[str]) -> int:
    if "--rebaseline" in argv:
        text = generate_rebaseline()
        if "--stats" in argv:
            print(json.dumps({e: dict(Counter(v["kind"] for v in nodes.values())) for e, nodes in json.loads(text).items()},
                             sort_keys=True))
            return 0
        if "--check" in argv:
            same = REBASELINE_OUT.exists() and REBASELINE_OUT.read_bytes() == text.encode("utf-8")
            print("rebaseline-node-map.json is byte-equal" if same else "rebaseline-node-map.json DIFFERS from the regenerated map")
            return 0 if same else 1
        REBASELINE_OUT.write_bytes(text.encode("utf-8"))
        return 0
    if "--stats" in argv:
        print(json.dumps(Counter(v["kind"] for v in json.loads(generate()).values()), sort_keys=True))
        return 0
    text = generate()
    if "--check" in argv:
        same = OUT.exists() and OUT.read_bytes() == text.encode("utf-8")
        print("test-node-map.json is byte-equal" if same else "test-node-map.json DIFFERS from the regenerated map")
        return 0 if same else 1
    OUT.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
