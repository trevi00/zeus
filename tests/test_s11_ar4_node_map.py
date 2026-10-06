"""S11 unit M: completeness of the AR4 node map `coverage/test-node-map.json` (DESIGN-s11 §6).

Every M7 pytest node ID is a key; every `ported`/`architecture` target node exists in the target collection at HEAD; the
`pending_root_script` count is pinned; the generator reproduces the file byte for byte. Each check has a negative control.
"""

import importlib.util
import json
import re
import subprocess
import sys
import time
from collections import Counter

import pytest
from _layout import REPO, TARGET, TARGET_PREFIX

SPEC = importlib.util.spec_from_file_location("test_node_map", REPO / "coverage" / "test_node_map.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)

# Unit P (the root-script disposition, PREP-S11 §9 #3) resolves these nodes and makes this count 0.
PENDING_COUNT = 0  # S11 R-S4 (DESIGN-s11 §7): both root-script test files are ported; was 33
COLLECTION_SECONDS = 90


@pytest.fixture(scope="module")
def target_ids():
    """Target collection at HEAD, `target/`-prefixed; bounded."""
    start = time.monotonic()
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
                          cwd=TARGET, capture_output=True, text=True, check=True, timeout=COLLECTION_SECONDS)
    assert time.monotonic() - start < COLLECTION_SECONDS
    return sorted(TARGET_PREFIX + x for x in done.stdout.splitlines() if "::" in x)


@pytest.fixture(scope="module")
def mapping():
    return json.loads(gen.OUT.read_text(encoding="utf-8"))


def problems(mapping, m7_ids, target_ids):
    """Every way the map fails to be complete; [] means complete."""
    found = []
    missing, extra = sorted(set(m7_ids) - set(mapping)), sorted(set(mapping) - set(m7_ids))
    found += [f"missing key {k}" for k in missing[:5]] + [f"extra key {k}" for k in extra[:5]]
    target = set(target_ids)
    for node, entry in mapping.items():
        kind = entry["kind"]
        targets = [entry["target"]] if kind == "ported" else entry["targets"] if kind == "architecture" else []
        if kind not in ("ported", "architecture", "pending_root_script"):
            found.append(f"unknown kind {kind} for {node}")
        found += [f"missing target {t}" for t in targets if t not in target]
    pending = sum(v["kind"] == "pending_root_script" for v in mapping.values())
    if pending != PENDING_COUNT:
        found.append(f"pending_root_script count {pending} != {PENDING_COUNT}")
    return found


def test_map_is_complete_over_the_m7_nodes(mapping, target_ids):
    m7_ids = gen.read_m7_ids()
    assert len(m7_ids) == len(set(m7_ids)) == 6569
    assert problems(mapping, m7_ids, target_ids) == []
    assert Counter(v["kind"] for v in mapping.values()) == {"ported": 6565, "architecture": 4}  # S11 R-S4: +33 ported


def test_pending_nodes_are_exactly_the_two_root_script_files(mapping):
    # PREP-S11 §9 #3: probe_ownership 10 + runner_evidence 23; unit P makes PENDING_COUNT (and this set) 0.
    files = Counter(k.partition("::")[0] for k, v in mapping.items() if v["kind"] == "pending_root_script")
    assert files == {}  # S11 R-S4: probe_ownership and runner_evidence ported


def test_generator_regenerates_the_map_byte_equal(target_ids):
    assert gen.OUT.read_bytes() == gen.render(gen.build(gen.read_m7_ids(), target_ids)).encode("utf-8")


def test_negative_control_missing_key(mapping, target_ids):
    broken = dict(mapping)
    broken.pop(next(iter(broken)))
    assert any(p.startswith("missing key") for p in problems(broken, gen.read_m7_ids(), target_ids))


def test_negative_control_extra_key(mapping, target_ids):
    broken = {**mapping, "tests/test_none.py::test_extra": {"kind": "ported", "target": "target/tests/ported/x.py::y"}}
    assert any(p.startswith("extra key") for p in problems(broken, gen.read_m7_ids(), target_ids))


def test_negative_control_renamed_target_node(mapping, target_ids):
    node = next(k for k, v in mapping.items() if v["kind"] == "ported")
    broken = {**mapping, node: {"kind": "ported", "target": mapping[node]["target"] + "_renamed"}}
    assert any(p.startswith("missing target") for p in problems(broken, gen.read_m7_ids(), target_ids))
    arch = next(k for k, v in mapping.items() if v["kind"] == "architecture")
    broken = {**mapping, arch: {**mapping[arch], "targets": [mapping[arch]["targets"][0] + "_renamed"]}}
    assert any(p.startswith("missing target") for p in problems(broken, gen.read_m7_ids(), target_ids))


def test_negative_control_stale_pending_count(mapping, target_ids):
    # S11 R-S4: no node is pending now, so the control plants one (a ported node relabelled pending) against the pin 0.
    node = next(k for k, v in mapping.items() if v["kind"] == "ported")
    broken = {**mapping, node: {"kind": "pending_root_script", "reason": "planted"}}
    assert any(p.startswith("pending_root_script count") for p in problems(broken, gen.read_m7_ids(), target_ids))


def test_negative_control_generator_check_detects_a_stale_file(target_ids):
    stale = gen.render(gen.build(gen.read_m7_ids(), target_ids)).encode("utf-8").replace(b"ported", b"portee", 1)
    assert stale != gen.OUT.read_bytes()


def test_invariant_comments_resolve_to_contract_registry():
    # M7 tests/test_architecture.py::test_invariant_comments_resolve_to_contract_registry retargeted at target/src: no
    # earlier target test checked @invariant comments against docs/contracts.md (unit M finding); this one does.
    contracts = (REPO / "docs/contracts.md").read_text(encoding="utf-8")
    seen = 0
    for source in sorted((TARGET / "src").rglob("*.py")):
        for identifier in re.findall(r"@invariant\s+(INV-[A-Z0-9-]+)", source.read_text(encoding="utf-8")):
            seen += 1
            assert identifier in contracts, (source, identifier)
    assert seen > 0, "the control must see at least one @invariant comment"
