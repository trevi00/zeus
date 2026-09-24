"""INV-CHECK-002: release suites are exact collected manifests run in bounded serial batches.

Every suite below is a real tiny pytest suite run by real child processes with the owner-written
accounting plugin. Faults are injected by fixture conftests and are labelled FAULT.
"""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.commands import ProcessCancelled, run_logged_process, run_process
from codex_harness.adapters.release_suite import SELECT_ENV, ReleaseSuite
from codex_harness.domain.check_results import (
    classify_batch,
    classify_collection,
    node_outcome,
    nodes_digest,
    plan_batches,
    reconcile_nodes,
)
from codex_harness.domain.model import ContractError

PY = sys.executable
BINDING = {"cwd": None, "expected_revision": None, "env_keys": None}


def suite_tree(root: Path, files: dict) -> Path:
    tests = root / "tests"
    tests.mkdir(parents=True)
    for name, body in files.items():
        (tests / name).write_text(body, encoding="utf-8")
    return root


def run_suite(root, *, batch_nodes=2, timeout=60, fence=None, extra=()):
    artifacts = FileArtifacts(root.parent / (root.name + "-artifacts"))
    suite = ReleaseSuite(artifacts, fence or (lambda: None), batch_nodes=batch_nodes)
    argv = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", *extra]
    return suite.check(argv, cwd=str(root), timeout=timeout, env=None, binding=BINDING), artifacts


PASSING = {
    "test_alpha.py": "import pytest\n\n"
                     "@pytest.mark.parametrize('value', [1, 'two words', 'a::b', '[x]'])\n"
                     "def test_param(value):\n    assert value\n\n"
                     "@pytest.mark.skip(reason='fixture skip')\ndef test_skipped():\n    pass\n",
    "test_beta.py": "import pytest\n\ndef test_plain():\n    assert True\n\n"
                    "@pytest.mark.xfail(reason='fixture xfail')\ndef test_expected_failure():\n    assert False\n",
}


def test_complete_manifest_runs_every_parameterized_node_in_bounded_batches(tmp_path):
    result, artifacts = run_suite(suite_tree(tmp_path / "suite", PASSING), batch_nodes=2)
    assert result["passed"] is True and result["outcome"] == "executed", result
    d = result["denominator"]
    assert (d["collected"], d["passed"], d["skipped"], d["xfailed"], d["failed"], d["not_run"]) == (7, 5, 1, 1, 0, 0)
    report = artifacts.document(result["evidence"])
    manifest = artifacts.document(report["manifest"])
    assert manifest["count"] == 7 and manifest["sha256"] == nodes_digest(manifest["nodeids"])
    assert "tests/test_alpha.py::test_param[a::b]" in manifest["nodeids"]
    assert "tests/test_alpha.py::test_param[two words]" in manifest["nodeids"]
    assert [b["count"] for b in manifest["batches"]] == [2, 2, 1, 2], "whole files packed, large files split"
    assert d["batches"] == d["batches_run"] == 4 and all(row["passed"] for row in report["batches"])
    assert report["exit_code"] == 0 and report["verdict"]["passed"] is True
    batch = artifacts.document(report["batches"][0]["evidence"])
    assert batch["verdict"]["reconciliation"]["complete"] and batch["planned"]["count"] == 2
    assert batch["manifest_sha256"] == manifest["sha256"]
    assert report["config"]["rootpath"] and report["accounting"]["env_keys"][1:] == ["RELEASE_ACCOUNTING_REPORT", SELECT_ENV]


def test_collection_failure_and_empty_collection_are_never_passes(tmp_path):
    broken, artifacts = run_suite(suite_tree(tmp_path / "broken", {"test_ok.py": "def test_ok():\n    pass\n",
                                                                   "test_bad.py": "def broken(:\n"}))
    assert broken["passed"] is False and broken["outcome"] == "executed" and "collection failed" in broken["reason"]
    report = artifacts.document(broken["evidence"])
    assert "batches" not in report and "manifest" not in report, "no batch ran on a failed collection"
    assert "SyntaxError" in artifacts.document(report["collection"])["events"]["text"]
    empty, _ = run_suite(suite_tree(tmp_path / "empty", {"test_none.py": "VALUE = 1\n"}))
    assert empty["passed"] is False and empty["outcome"] == "empty_check"
    skipped, _ = run_suite(suite_tree(tmp_path / "skipped", {
        "test_s.py": "import pytest\n\n@pytest.mark.skip(reason='x')\ndef test_s():\n    pass\n"}))
    assert skipped["passed"] is False and skipped["outcome"] == "empty_check"
    assert skipped["denominator"]["skipped"] == 1 and skipped["denominator"]["passed"] == 0


def test_failed_batch_stops_the_remaining_batches_as_not_run(tmp_path):
    root = suite_tree(tmp_path / "suite", {"test_a.py": "def test_a1():\n    pass\n\ndef test_a2():\n    assert False\n",
                                           "test_b.py": "def test_b1():\n    pass\n",
                                           "test_c.py": "def test_c1():\n    pass\n"})
    result, artifacts = run_suite(root, batch_nodes=2)
    assert result["passed"] is False and result["outcome"] == "executed"
    assert result["denominator"]["failed"] == 1 and result["denominator"]["not_run"] == 2
    rows = artifacts.document(result["evidence"])["batches"]
    assert [row["outcome"] for row in rows] == ["executed", "not_run"]
    failed = artifacts.document(rows[0]["evidence"])
    assert "assert False" in failed["stdout"]["text"] and failed["exit_code"] == 1


# FAULT: a candidate conftest that only misbehaves inside batches (RELEASE_ACCOUNTING_SELECT set).
# Omission and duplication happen after selection; drift changes what the batch collected.
FAULTS = {
    "omitted": "import os\n\ndef pytest_collection_finish(session):\n"
               "    if os.environ.get('RELEASE_ACCOUNTING_SELECT'):\n"
               "        session.items[:] = [i for i in session.items if not i.name.endswith('b')]\n",
    "duplicate": "import os\n\ndef pytest_collection_finish(session):\n"
                 "    if os.environ.get('RELEASE_ACCOUNTING_SELECT'):\n        session.items.append(session.items[0])\n",
    "drift": "import os\n\ndef pytest_collection_modifyitems(items):\n"
             "    if os.environ.get('RELEASE_ACCOUNTING_SELECT'):\n        items.pop()\n",
}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_injected_omitted_duplicate_or_drifted_nodes_refuse(tmp_path, fault):
    root = suite_tree(tmp_path / "suite", {"conftest.py": FAULTS[fault],
                                           "test_x.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n"})
    result, artifacts = run_suite(root, batch_nodes=10)
    assert result["passed"] is False and result["outcome"] == "coverage_mismatch", result
    batch = artifacts.document(artifacts.document(result["evidence"])["batches"][0]["evidence"])["verdict"]
    if fault == "omitted":
        assert batch["reconciliation"]["missing"] == ["tests/test_x.py::test_b"]
    if fault == "duplicate":
        assert batch["reconciliation"]["duplicate"] == ["tests/test_x.py::test_a"]
    if fault == "drift":
        assert "drift" in batch["reason"]


def test_unexpected_or_unfinished_accounting_is_not_a_pass():
    planned = ["t.py::a"]
    manifest = {"count": 1, "sha256": nodes_digest(planned)}
    def events(*ids, finish=True):
        out = [{"event": "collected", "count": 1, "sha256": manifest["sha256"]},
               {"event": "selected", "nodeids": planned}]
        for nodeid in ids:
            out += [{"event": "phase", "nodeid": nodeid, "when": "call", "outcome": "passed"},
                    {"event": "finish", "nodeid": nodeid}]
        return out + ([{"event": "sessionfinish", "exitstatus": 0}] if finish else [])
    assert classify_batch(planned, manifest, 0, events("t.py::a"))["passed"] is True
    # FAULT: synthetic events naming a node that was never planned.
    unexpected = classify_batch(planned, manifest, 0, events("t.py::a", "t.py::zz"))
    assert unexpected["outcome"] == "coverage_mismatch" and unexpected["reconciliation"]["unexpected"] == ["t.py::zz"]
    assert classify_batch(planned, manifest, 0, events("t.py::a", finish=False))["outcome"] == "observation_error"
    assert classify_batch(planned, manifest, None, events("t.py::a"))["outcome"] == "observation_error"
    assert classify_collection(0, [])["outcome"] == "observation_error", "no report is unobserved, not empty"
    assert classify_collection(5, [{"event": "collected", "count": 0, "nodeids": []}])["outcome"] == "empty_check"
    assert classify_collection(0, [{"event": "collected", "count": 2, "nodeids": ["a", "a"]}])["outcome"] == "coverage_mismatch"
    assert node_outcome([{"when": "setup", "outcome": "passed"}]) == "unknown", "no call phase is never a pass"
    assert node_outcome([{"when": "setup", "outcome": "failed"}]) == "errors"
    assert reconcile_nodes(["a", "b"], ["a", "a"]) == {"complete": False, "planned": 2, "observed": 2,
                                                       "missing": ["b"], "duplicate": ["a"], "unexpected": []}


def test_batch_plan_is_deterministic_and_portable():
    ids = ["tests/a.py::t[x::y]", "tests/a.py::u", "tests/b/c.py::C::t", "tests/d.py::t1", "tests/d.py::t2", "tests/d.py::t3"]
    assert plan_batches(ids, 2) == [["tests/a.py::t[x::y]", "tests/a.py::u"], ["tests/b/c.py::C::t"],
                                    ["tests/d.py::t1", "tests/d.py::t2"], ["tests/d.py::t3"]]
    assert plan_batches(ids, 100) == [ids] and plan_batches(ids, 2) == plan_batches(list(ids), 2)
    for bad in ([], ["a", "a"]):
        with pytest.raises(ContractError):
            plan_batches(bad, 2)


SLOW = {"test_slow.py": "import subprocess, sys, time\n\n"
                        "def test_first():\n    print('FIRST-PROGRESS', flush=True)\n\n"
                        "def test_hangs():\n"
                        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                        "    open('grandchild.pid', 'w').write(str(child.pid))\n"
                        "    print('HANG-PROGRESS', flush=True)\n    time.sleep(120)\n"}


def test_timeout_keeps_partial_log_last_test_and_owned_cleanup(tmp_path):
    root = suite_tree(tmp_path / "suite", SLOW)
    started = time.monotonic()
    result, artifacts = run_suite(root, batch_nodes=10, timeout=8, extra=["-s"])
    assert time.monotonic() - started < 60, "the per-process deadline bounded the batch"
    assert result["passed"] is False and result["outcome"] == "observation_error"
    assert "timed out after 8s" in result["reason"] and result["denominator"]["passed"] == 1
    batch = artifacts.document(artifacts.document(result["evidence"])["batches"][0]["evidence"])
    assert batch["timed_out"] is True and batch["exit_code"] is None
    assert "FIRST-PROGRESS" in batch["stdout"]["text"] and "HANG-PROGRESS" in batch["stdout"]["text"]
    assert batch["progress"]["unfinished"] == "tests/test_slow.py::test_hangs"
    assert "not attributed" in batch["progress"]["note"]
    if os.name != "nt":
        assert batch["cleanup"]["method"] == "killpg"
        assert batch["cleanup"]["descendants_gone"] is True, batch["cleanup"]
        with pytest.raises(ProcessLookupError):
            os.kill(int((root / "grandchild.pid").read_text()), 0)


def interrupt_after(seconds):
    import _thread
    timer = threading.Timer(seconds, _thread.interrupt_main)
    timer.start()
    return timer


def test_cancel_keeps_partial_log_and_cleans_up(tmp_path):
    out, err = tmp_path / "out.log", tmp_path / "err.log"
    timer = interrupt_after(2)
    try:
        with pytest.raises(ProcessCancelled) as cancelled:
            run_logged_process([PY, "-c", "import time; print('BEFORE', flush=True); time.sleep(60)"],
                               stdout_path=out, stderr_path=err, timeout=60)
    finally:
        timer.cancel()
    assert cancelled.value.observation["cancelled"] is True and "BEFORE" in out.read_text()
    if os.name != "nt":
        assert cancelled.value.observation["cleanup"]["descendants_gone"] is True
    # The suite keeps its partial report on cancel and re-raises: nothing becomes a verdict.
    root = suite_tree(tmp_path / "suite", SLOW)
    timer = interrupt_after(4)
    try:
        with pytest.raises(ProcessCancelled):
            run_suite(root, batch_nodes=10, timeout=60, extra=["-s"])
    finally:
        timer.cancel()
    store = tmp_path / "suite-artifacts"
    partial = [p.read_text() for p in store.glob("*.txt") if '"interrupted":"ProcessCancelled"' in p.read_text()]
    assert len(partial) == 1 and '"passed":false' in partial[0]
    batch = [p.read_text() for p in store.glob("*.txt") if '"cancelled":true' in p.read_text()]
    assert len(batch) == 1 and "HANG-PROGRESS" in batch[0] and "test_hangs" in batch[0]
    if os.name != "nt":
        assert '"descendants_gone":true' in batch[0]


def test_lost_fence_between_batches_refuses_and_grants_nothing(tmp_path):
    root = suite_tree(tmp_path / "suite", {"test_a.py": "def test_a():\n    pass\n",
                                           "test_b.py": "def test_b():\n    pass\n"})
    calls = []

    def fence():
        calls.append(1)
        if len(calls) > 4:
            raise ContractError("Stale release controller")

    with pytest.raises(ContractError, match="Stale"):
        run_suite(root, batch_nodes=1, fence=fence)
    reports = [p for p in (tmp_path / "suite-artifacts").glob("*.txt") if '"interrupted":"ContractError"' in p.read_text()]
    assert len(reports) == 1 and '"passed":false' in reports[0].read_text()


def test_incumbent_tests_run_against_candidate_code_with_incumbent_config(tmp_path):
    incumbent = suite_tree(tmp_path / "incumbent", {"test_contract.py": "import product\n\n"
                                                    "def test_value():\n    assert product.VALUE == 2\n"})
    (incumbent / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    candidate = suite_tree(tmp_path / "candidate", {"test_own.py": "def test_own():\n    pass\n"})
    (candidate / "product.py").write_text("VALUE = 2\n", encoding="utf-8")
    artifacts = FileArtifacts(tmp_path / "artifacts")
    suite = ReleaseSuite(artifacts, lambda: None)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(candidate), os.environ.get("PYTHONPATH", "")])}
    argv = [PY, "-m", "pytest", str(incumbent / "tests"), "-c", str(incumbent / "pyproject.toml"),
            "--import-mode=importlib", "-p", "no:cacheprovider"]
    result = suite.check(argv, cwd=str(candidate), timeout=60, env=env, binding=BINDING)
    assert result["passed"] is True, result
    report = artifacts.document(result["evidence"])
    assert Path(report["config"]["inipath"]) == incumbent / "pyproject.toml"
    assert report["config"]["inifile_sha256"] and "PYTHONPATH" in report["env_keys"]
    manifest = artifacts.document(report["manifest"])
    assert manifest["nodeids"] == ["tests/test_contract.py::test_value"], "incumbent definitions, not candidate's"
    (candidate / "product.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert suite.check(argv, cwd=str(candidate), timeout=60, env=env, binding=BINDING)["passed"] is False


def test_run_process_default_behavior_is_unchanged(tmp_path):
    done = run_process([PY, "-c", "import sys; print('out'); print('err', file=sys.stderr)"])
    assert (done.returncode, done.stdout.strip(), done.stderr.strip()) == (0, "out", "err")
    import subprocess
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([PY, "-c", "import time; time.sleep(30)"], timeout=1)
    logged = run_logged_process([PY, "-c", "print('ok')"], stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert logged == {"exit_code": 0, "timed_out": False} and (tmp_path / "o").read_text().strip() == "ok"
