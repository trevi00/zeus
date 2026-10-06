"""Cutover RH-5: the rehearsal R5 bounded write scenario (`compare/rehearsal/r5.py`, `r5_drivers/{a,b}.py`).

Layer: harness tooling tests (never shipped). Expected results come from the task spec's acceptance criteria and the rehearsal
design "7. R5" / critique #14 / AMD-1 A-B, never from the output of the implementation under test:
- PASS = the A and B write sets are equal except declared differences (each declared with an AMD-1 section or an S2R hunk) and
  the recorder unit boundaries are equal; an undeclared difference FAILS;
- both executor transports are stubbed and the unexpected one raises; no provider process is spawned; two runs are identical;
- the F-1 steps the scenario must complete are the spec's: register, admit, claim, run the task through the fixture transport,
  review with a fixture lead/conductor decision, enqueue in the release queue (stop before publish).
The pure tests need no Docker. The copy tests need `ZEUS_TEST_DOCKER=1` and `ZEUS_TEST_DOCKER_PGEXEC=1`, and a skip under those
opt-ins is a failure. A is `reference/m7/src` here; the live run points A at the rebaseline wheel's tree (AMD-1 A).

Structural check (named): `test_the_driver_environment_carries_no_production_profile` is a CONFIGURATION check of the closed
child env (critique #14), not behavioural acceptance; the behavioural proof is `production_profile_set` read back from each side.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import r5  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1" and os.environ.get(guard.DOCKER_PGEXEC_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
RUN8, DATABASE = "5b3d7f21", "zeus"
A_SRC, B_SRC = REPO / "reference" / "m7" / "src", REPO / "src"
DRIVERS = REPO / "compare" / "rehearsal" / "r5_drivers"
PYTHON = sys.executable
SPEC_STEPS = ["fleet_resume", "backlog_register", "backlog_admit", "fleet_admit", "operation_claim", "run_task",
              "review_lead", "review_conductor"]


# ---- pure: declarations, write sets, boundaries (no Docker) ----

def test_a_declaration_without_an_amd1_section_or_s2r_hunk_is_refused():
    base = {"id": "d1", "kind": "store", "bucket": "x", "key_pattern": ".*", "differs": ["changed"], "reason": "r"}
    for section in ("", "AMD-1 Z", "somewhere", "S2R nothex:path.py"):
        with pytest.raises(r5.Refused) as caught:
            r5.validate_declarations({"closed": True, "declared": [{**base, "section": section}]})
        assert caught.value.code == "declaration_uncited"
    r5.validate_declarations({"closed": True, "declared": [{**base, "section": "AMD-1 A"}]})
    r5.validate_declarations({"closed": True, "declared": [{**base, "id": "d2", "section": "S2R 9543ed19:src/codex_harness/x.py"}]})


def test_the_packaged_declarations_are_closed_and_every_entry_is_cited():
    document = r5.load_declarations()
    assert document["closed"] is True
    assert all(r5.SECTION.fullmatch(entry["section"]) for entry in document["declared"])


def test_store_write_set_reports_insert_update_delete_with_masked_body_digests():
    before = {("jobs", "j1"): {"n": 1, "at": "t0"}, ("jobs", "j2"): {"n": 2}, ("gone", "g"): {"n": 3}}
    after = {("jobs", "j1"): {"n": 1, "at": "t1"}, ("jobs", "j2"): {"n": 2}, ("new", "k"): {"n": 4, "at": "t9"}}
    plain = r5.store_write_set(before, after)
    assert [row[:3] for row in plain] == [["gone", "g", "delete"], ["jobs", "j1", "update"], ["new", "k", "insert"]]
    masked_a = r5.store_write_set(before, after, {"at": "rehearsal.r5.at"})
    other = {("jobs", "j1"): {"n": 1, "at": "OTHER"}, ("jobs", "j2"): {"n": 2}, ("new", "k"): {"n": 4, "at": "OTHER"}}
    assert masked_a == r5.store_write_set(before, other, {"at": "rehearsal.r5.at"}) != plain


def test_differences_are_found_in_both_directions_and_an_undeclared_one_is_reported():
    a = [["b", "k1", "insert", "s1"], ["b", "k2", "insert", "s2"]]
    b = [["b", "k1", "insert", "s1"], ["b", "k2", "insert", "OTHER"], ["b", "k3", "insert", "s3"]]
    diffs = r5.differences(a, b, 2)
    assert [(d["identity"], d["differs"]) for d in diffs] == [(["b", "k2"], "changed"), (["b", "k3"], "only_b")]
    declarations = {"closed": True, "declared": [{"id": "d", "kind": "store", "bucket": "b", "key_pattern": "k3",
                                                  "differs": ["only_b"], "section": "AMD-1 B", "reason": "r"}]}
    left, used = r5.undeclared(diffs, declarations, "store")
    assert [d["identity"] for d in left] == [["b", "k2"]] and used == ["d"]


def test_a_field_declaration_explains_only_its_field_and_never_another_change_in_the_row():
    declared = {"closed": True, "declared": [{"id": "d", "kind": "store", "bucket": "obs", "key_pattern": ".*", "differs": ["changed"],
                                              "ignore_fields": ["number"], "section": "DESIGN-s9-X §1.3", "reason": "r"}]}
    diff = [{"identity": ["obs", "k"], "differs": "changed", "a": ["insert", "x"], "b": ["insert", "y"]}]
    same_but_number = {"A": {("obs", "k"): {"seq": {"number": 6}, "kind": "k"}}, "B": {("obs", "k"): {"seq": {"number": 7}, "kind": "k"}}}
    other_change = {"A": {("obs", "k"): {"seq": {"number": 6}, "kind": "k"}}, "B": {("obs", "k"): {"seq": {"number": 7}, "kind": "OTHER"}}}
    assert r5.undeclared(diff, declared, "store", same_but_number) == ([], ["d"])
    assert r5.undeclared(diff, declared, "store", other_change)[0] == diff
    assert r5.undeclared(diff, declared, "store", None)[0] == diff  # no bodies: not explained


def test_a_unit_that_wrote_nothing_is_not_a_state_boundary_but_is_counted():
    def result(*units):
        return {"steps": {"s": {"units": list(units)}}}

    wrote = {"label": "", "outcome": "COMMIT", "writes": [["b", "k"]], "depth": 0}
    read = {"label": "", "outcome": "COMMIT", "writes": [], "depth": 0}
    assert r5.boundaries(result(wrote, read, read)) == r5.boundaries(result(read, wrote)) == [["s", "COMMIT", 0, "b/k"]]
    assert r5.readonly_units(result(wrote, read, read)) == {"s": 2}
    rolled = {"label": "", "outcome": "ROLLBACK", "writes": [], "depth": 0}
    assert r5.boundaries(result(rolled)) == [["s", "ROLLBACK", 0, ""]]  # a rollback is a boundary even without writes


def test_unit_boundaries_compare_outcome_depth_and_written_keys_not_ordinal_ids():
    def result(units):
        return {"steps": {"s": {"units": units}}}

    unit = {"label": "", "outcome": "COMMIT", "writes": [["b", "k"], ["a", "z"]], "depth": 0}
    same = {**unit, "label": "x", "writes": [["a", "z"], ["b", "k"]]}
    assert r5.boundaries(result([unit])) == r5.boundaries(result([same]))
    assert r5.boundaries(result([unit])) != r5.boundaries(result([{**unit, "outcome": "ROLLBACK"}]))
    assert r5.boundaries(result([unit])) != r5.boundaries(result([{**unit, "writes": [["b", "k"]]}]))


def test_file_write_sets_rewrite_the_root_and_see_inserts_updates_and_deletes(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "old.txt").write_text("v1")
    (tmp_path / "x" / "gone.txt").write_text("g")
    before = r5.file_tree(tmp_path / "x", (str(tmp_path),))
    (tmp_path / "x" / "old.txt").write_text(f"v2 {tmp_path}")
    (tmp_path / "x" / "gone.txt").unlink()
    (tmp_path / "x" / "new.txt").write_text("n")
    after = r5.file_tree(tmp_path / "x", (str(tmp_path),))
    assert [row[:2] for row in r5.file_write_set(before, after)] == [["gone.txt", "delete"], ["new.txt", "insert"], ["old.txt", "update"]]
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "old.txt").write_text(f"v2 {other}")
    assert r5.file_tree(other, (str(other),))["old.txt"] == r5.file_tree(tmp_path / "x", (str(tmp_path),))["old.txt"]


def test_the_driver_environment_carries_no_production_profile():
    env = r5.side_env()
    assert "ZEUS_COMPOSITION_PROFILE" not in env and set(env) == {"PATH", "PYTHONDONTWRITEBYTECODE", "LANG"}


def test_the_s2r_hold_fact_is_a_data_fact_never_an_evaluated_refusal():
    none = r5.s2r_hold_fact({("jobs", "j"): {"n": 1}})
    assert none["evaluated"] is False and none["maintenance_intent_rows"] == 0 and none["would_refuse"] == "no_open_intent_in_copy"
    found = r5.s2r_hold_fact({("maintenance_runs", "m"): {"status": "maintenance", "generations": [2]}})
    assert found["evaluated"] is False and found["maintenance_intent_rows"] == 1 and found["would_refuse"] == "unknown"


# ---- real copy: A and B over clones of one rehearsal copy ----

class World:
    pass


def _driver(spec_name, script):
    return r5.SideSpec(spec_name, A_SRC if spec_name == "A" else B_SRC, DRIVERS / script, PYTHON)


SIDES = {"A": _driver("A", "a.py"), "B": _driver("B", "b.py")}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    w = World()
    w.root, w.out, w.work = (tmp_path_factory.mktemp("r5"), tmp_path_factory.mktemp("r5out"), tmp_path_factory.mktemp("r5work"))
    w.copies = cp.Copies(RUN8, w.root)
    w.runs = 0
    try:
        w.handle = w.copies.start("S")
        seed = subprocess.run(
            [PYTHON, "-I", str(DRIVERS / "a.py"), "--mode", "seed", "--dsn", cp.pg_dsn(w.handle.pg_socket, DATABASE), "--run8", RUN8,
             "--src", str(A_SRC), "--scratch", str(w.work / "seed"), "--artifacts", str(w.work / "seed-art"),
             "--out", str(w.work / "seed.json")], capture_output=True, text=True, env=r5.side_env(), check=False)
        assert seed.returncode == 0, seed.stderr[-600:]
        w.baseline = cp.catalog_sha256(w.handle.pg_socket, DATABASE)
        yield w
    finally:
        sweep(RUN8, w.root)


def _run(world, **kwargs):
    world.runs += 1
    return r5.run_r5(SIDES, world.handle, DATABASE, world.work / f"run{world.runs}", world.out / f"r{world.runs}", run8=RUN8, **kwargs)


def _failed(world, **kwargs):
    with pytest.raises(r5.R5Failed) as caught:
        _run(world, **kwargs)
    return caught.value


@needs_docker
def test_a_and_b_write_the_same_records_or_every_difference_is_declared_and_the_boundaries_are_equal(world):
    document = _run(world)
    facts = document["facts"]
    assert document["status"] == "ok" and facts["failures"] == []
    assert facts["steps_completed_A"] == facts["steps_completed_B"] == SPEC_STEPS
    assert facts["unit_boundaries_equal"] is True and facts["units"]["A"] == facts["units"]["B"] > 0
    assert facts["store_declared_used"] == ["x1b2-observer-spool-sequence"]  # the one declared difference, and it was needed
    assert facts["store_undeclared"] == [] and facts["artifacts_undeclared"] == [] and facts["runtime_undeclared"] == []
    # the flow's authority writes are in BOTH write sets (the spec's example: fleet_control update, backlog insert, ...)
    for side in ("A", "B"):
        assert {"fleet_control", "release_queue", "releases", "operations", "tasks"} <= set(facts["buckets_written"][side]) | {"fleet_control"}
    assert facts["d1_equals_d0"] is True and facts["catalog_sha256_d0"] == world.baseline  # the copy itself is untouched
    assert facts["s2r_hold"]["evaluated"] is False and "ZEUS_COMPOSITION_PROFILE is not set" in facts["profile"]


@needs_docker
def test_without_the_declaration_the_only_difference_is_the_observer_spool_sequence_of_two_b_only_events(world):
    """Independent source: B's `run_task.py` emits `development.role_dispatch_decided` and `development.usage_split_recorded`
    (X1b-2, DESIGN-s9-X §1.3/§1.5) and M7's executor does not, so a later observation_audit row's spool sequence number is higher
    on B. With no declaration that single row must be the ONLY undeclared difference."""
    caught = _failed(world, declarations={"closed": True, "declared": []})
    assert [f.split(":")[0] for f in caught.failures] == ["store_undeclared"], caught.failures
    assert caught.failures[0].startswith("store_undeclared:observation_audit/") and caught.failures[0].endswith(":changed")
    assert caught.document["facts"]["unit_boundaries_equal"] is True


def _without_network(world):
    """The existing guard's namespace (`provider_guard.bwrap_prefix`: `--unshare-net`, credential dirs hidden, only the given
    paths writable), wrapped around each driver argv through `run_r5`'s `runner` hook."""
    if not guard.bwrap_available():
        pytest.fail("bwrap is required for the no-network run (a skip is a failure under the opt-ins)")
    prefix = guard.bwrap_prefix([world.root, world.work])
    return lambda argv, timeout: r5.subprocess_runner([*prefix, *argv], timeout)


@needs_docker
def test_the_fixture_provider_transport_ran_once_and_no_process_was_spawned_without_network(world):
    runner = _without_network(world)
    probe = runner([PYTHON, "-I", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"], 30)
    assert probe[0] != 0, "the wrapper did not remove the network"  # an independent proof that the namespace has none
    document = _run(world, runner=runner)
    facts = document["facts"]
    assert facts["provider_calls_A"] == facts["provider_calls_B"] == 1
    for side in ("A", "B"):
        result = json.loads((world.work / f"run{world.runs}" / side.lower() / "result.json").read_text())
        assert result["spawn_events"] == [] and result["production_profile_set"] is False
        assert result["steps"]["run_task"]["ok"] is True and result["recorder_violations"] == []


@needs_docker
def test_an_undeclared_injected_difference_fails_and_the_record_names_it(world):
    caught = _failed(world, inject={"A": "rh_injected/extra-1"})
    assert any(f.startswith("store_undeclared:rh_injected/extra-1:only_a") for f in caught.failures), caught.failures
    assert json.loads((world.out / f"r{world.runs}" / "r5.json").read_text())["status"] == "failed"  # evidence exists
    declared = r5.load_declarations()
    declared["declared"].append({"id": "inj", "kind": "store", "bucket": "rh_injected", "key_pattern": "extra-1",
                                 "differs": ["only_a"], "section": "AMD-1 A", "reason": "test declaration"})
    document = _run(world, inject={"A": "rh_injected/extra-1"}, declarations=declared)
    assert document["status"] == "ok" and "inj" in document["facts"]["store_declared_used"]


@needs_docker
@pytest.mark.parametrize("fault", ["codex_unstubbed", "claude_reached"])
def test_an_unstubbed_or_unexpected_transport_raises_and_fails_the_run(world, fault):
    """`codex_unstubbed`: B's REAL host App Server is left in place (the provider guard refuses it); `claude_reached`: the
    stubbed-loud Claude runtime is constructed by the fixture transport. Either way the task must NOT succeed and the scenario
    stops at that step, so no later step runs on a state the failed step did not make."""
    caught = _failed(world, faults={"B": fault})
    assert any(f.startswith("steps:B:") and "run_task" in f for f in caught.failures), caught.failures
    result = json.loads((world.work / f"run{world.runs}" / "b" / "result.json").read_text())
    step = result["steps"]["run_task"]
    assert step["ok"] is False and step["error"] == "RuntimeError" and step["message"].startswith("task ended ")
    assert "succeeded" not in step["message"].split(":")[0]
    assert result["spawn_events"] == [] and result["production_profile_set"] is False
    assert "review_lead" not in result["steps"]  # fail closed: later steps do not run on a state the failed step did not make


@needs_docker
def test_two_runs_give_identical_write_sets(world):
    first, second = _run(world), _run(world)
    assert first["facts"]["write_set_sha256"] == second["facts"]["write_set_sha256"]
    assert first["facts"]["write_set_sizes"] == second["facts"]["write_set_sizes"]
