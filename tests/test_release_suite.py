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
from codex_harness.adapters.release_suite import REPORT_ENV, SELECT_ENV, ReleaseSuite
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


def run_suite(root, *, batch_nodes=2, timeout=60, fence=None, extra=(), env=None):
    artifacts = FileArtifacts(root.parent / (root.name + "-artifacts"))
    suite = ReleaseSuite(artifacts, fence or (lambda: None), batch_nodes=batch_nodes)
    argv = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", *extra]
    return suite.check(argv, cwd=str(root), timeout=timeout, env=env, binding=BINDING), artifacts


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


# An outer suite whose selected test runs an inner ReleaseSuite from inside its batch process, so the
# inner suite starts with the outer batch's accounting environment (report and selection) inherited.
NESTED = {
    "test_outer_plain.py": "def test_plain():\n    pass\n",
    "test_outer_nested.py": "import json\nimport os\nfrom pathlib import Path\n\n"
                            "from codex_harness.adapters.artifacts import FileArtifacts\n"
                            "from codex_harness.adapters.release_suite import ReleaseSuite\n\n"
                            "def test_inner_suite():\n"
                            "    plan = json.loads(Path(__file__).with_name('nested.json').read_text('utf-8'))\n"
                            "    before = dict(os.environ)\n"
                            "    suite = ReleaseSuite(FileArtifacts(plan['store']), lambda: None, batch_nodes=2)\n"
                            "    result = suite.check(plan['argv'], cwd=plan['cwd'], timeout=60, env=None, binding={})\n"
                            "    Path(plan['out']).write_text(json.dumps(result), 'utf-8')\n"
                            "    assert dict(os.environ) == before\n"
                            "    assert result['passed'] is True, result\n",
}


def nested_suite(tmp_path, inner_files):
    import json

    from codex_harness.adapters import release_suite
    inner = suite_tree(tmp_path / "inner", inner_files)
    outer = suite_tree(tmp_path / "outer", NESTED)
    plan = {"store": str(tmp_path / "inner-store" / "artifacts"), "cwd": str(inner),
            "out": str(tmp_path / "inner-result.json"),
            "argv": [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]}
    (outer / "tests" / "nested.json").write_text(json.dumps(plan), encoding="utf-8")
    src = str(Path(release_suite.__file__).resolve().parents[2])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([src] + ([os.environ["PYTHONPATH"]]
                                                               if os.environ.get("PYTHONPATH") else []))}
    snapshot, caller = dict(env), dict(os.environ)
    result, artifacts = run_suite(outer, batch_nodes=10, timeout=120, env=env)
    assert env == snapshot and dict(os.environ) == caller, "the caller's environment is never mutated"
    out = Path(plan["out"])
    return result, artifacts, (json.loads(out.read_text("utf-8")) if out.exists() else None), FileArtifacts(plan["store"])


def test_nested_suite_accounts_outer_and_inner_nodes_with_separate_evidence(tmp_path):
    result, artifacts, inner, inner_store = nested_suite(tmp_path, PASSING)
    assert inner is not None and inner["passed"] is True and inner["outcome"] == "executed", inner
    d = inner["denominator"]
    assert (d["collected"], d["passed"], d["skipped"], d["xfailed"], d["failed"], d["not_run"], d["batches"]) == (
        7, 5, 1, 1, 0, 0, 4), "the inner suite collected and ran its own nodes, not the outer selection"
    assert result["passed"] is True and result["outcome"] == "executed", result
    d = result["denominator"]
    assert (d["collected"], d["passed"], d["failed"], d["not_run"], d["batches"]) == (2, 2, 0, 0, 1)
    outer_report = artifacts.document(result["evidence"])
    assert artifacts.document(outer_report["manifest"])["nodeids"] == [
        "tests/test_outer_nested.py::test_inner_suite", "tests/test_outer_plain.py::test_plain"]
    inner_report = inner_store.document(inner["evidence"])
    assert inner_store.document(inner_report["manifest"])["count"] == 7
    batch = artifacts.document(outer_report["batches"][0]["evidence"])
    assert "test_alpha.py" not in batch["events"]["text"], "the inner suite never wrote to the outer report"
    assert inner["evidence"] != result["evidence"] and inner_store.root != artifacts.root


def test_nested_failed_inner_suite_is_never_an_outer_pass(tmp_path):
    result, _, inner, _ = nested_suite(tmp_path, {"test_bad.py": "def test_ok():\n    pass\n\n"
                                                                 "def test_bad():\n    assert False\n"})
    assert inner is not None and inner["passed"] is False and inner["denominator"]["failed"] == 1, inner
    assert result["passed"] is False and result["outcome"] == "executed", result
    assert result["denominator"]["failed"] == 1 and result["denominator"]["passed"] == 1


def test_caller_supplied_stale_accounting_environment_is_not_inherited(tmp_path):
    import json
    stale_select, stale_report = tmp_path / "stale.select.json", tmp_path / "stale.jsonl"
    stale_select.write_text(json.dumps(["tests/elsewhere.py::test_gone"]), encoding="utf-8")
    env = {**os.environ, SELECT_ENV: str(stale_select), REPORT_ENV: str(stale_report)}
    snapshot = dict(env)
    result, artifacts = run_suite(suite_tree(tmp_path / "suite", PASSING), batch_nodes=2, env=env)
    assert result["passed"] is True and result["denominator"]["collected"] == 7, result
    assert not stale_report.exists() and env == snapshot
    report = artifacts.document(result["evidence"])
    assert report["accounting"]["inherited_removed"] == [REPORT_ENV, SELECT_ENV]
    assert SELECT_ENV in report["env_keys"], "the caller's key list is still recorded as supplied"


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


SECRET_RUN, SECRET_OMITTED = "ghp_" + "A" * 24, "ghp_" + "B" * 24


def test_credential_shaped_parameter_ids_are_redacted_in_every_receipt_field(tmp_path):
    # FAULT: parameter IDs shaped like tokens; a batch conftest omits the second, so the
    # node ID reaches both the progress fields and the reconciliation's `missing` list.
    root = suite_tree(tmp_path / "suite", {
        "conftest.py": "import os\n\ndef pytest_collection_finish(session):\n"
                       "    if os.environ.get('RELEASE_ACCOUNTING_SELECT'):\n"
                       "        session.items[:] = [i for i in session.items if 'B' * 24 not in i.name]\n",
        "test_s.py": "import pytest\n\n"
                     f"@pytest.mark.parametrize('value', [{SECRET_RUN!r}, {SECRET_OMITTED!r}])\n"
                     "def test_p(value):\n    assert value\n"})
    result, artifacts = run_suite(root, batch_nodes=10)
    assert result["passed"] is False and result["outcome"] == "coverage_mismatch", result
    batch = artifacts.document(artifacts.document(result["evidence"])["batches"][0]["evidence"])
    assert batch["progress"]["last_finished"] == "tests/test_s.py::test_p[[REDACTED token]]"
    assert batch["verdict"]["reconciliation"]["missing"] == ["tests/test_s.py::test_p[[REDACTED token]]"]
    assert batch["redacted_fields"] >= 2
    stored = [p.read_text() for p in (tmp_path / "suite-artifacts").rglob("*") if p.is_file()]
    assert stored and not any(SECRET_RUN in text or SECRET_OMITTED in text for text in stored)


def test_failed_tree_kill_never_leaves_reaping_unbounded(tmp_path, monkeypatch):
    from codex_harness.adapters import commands

    def refuse(process):
        raise PermissionError("FAULT: tree kill refused")

    monkeypatch.setattr(commands, "_kill_tree", refuse)
    monkeypatch.setattr(commands, "REAP_SECONDS", 1)
    script = "import os, time; print(os.getpid(), flush=True); print('BEFORE', flush=True); time.sleep(60)"
    # The direct-child fallback reaps the child when only the tree kill failed.
    out = tmp_path / "fallback.out"
    observation = run_logged_process([PY, "-c", script], stdout_path=out, stderr_path=tmp_path / "e", timeout=2)
    assert observation["timed_out"] is True and "BEFORE" in out.read_text()
    assert observation["cleanup"]["error"] == "PermissionError" and observation["cleanup"]["fallback"] == "kill"
    assert observation["cleanup"]["reaped"] is True
    # FAULT: the fallback kill is also ineffective, so the child survives; cleanup must still return.
    import subprocess
    monkeypatch.setattr(subprocess.Popen, "kill", lambda self: None)
    out = tmp_path / "stuck.out"
    started = time.monotonic()
    try:
        observation = run_logged_process([PY, "-c", script], stdout_path=out, stderr_path=tmp_path / "e2", timeout=2)
        assert time.monotonic() - started < 20, "reaping is bounded, not a wait for the child's own exit"
        assert observation["timed_out"] is True and "BEFORE" in out.read_text()
        assert observation["cleanup"]["reaped"] is False and observation["cleanup"]["descendants_gone"] is None
    finally:
        pid = int(out.read_text().split()[0])
        try:
            os.kill(pid, 9)
        except OSError:
            pass


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


def test_lost_fence_or_cancel_around_collection_keeps_a_partial_report(tmp_path):
    root = suite_tree(tmp_path / "suite", {"test_a.py": "def test_a():\n    pass\n"})
    calls = []

    def fence():
        calls.append(1)
        if len(calls) > 1:
            raise ContractError("Stale release controller")

    with pytest.raises(ContractError, match="Stale"):
        run_suite(root, fence=fence)
    store = tmp_path / "suite-artifacts"
    reports = [p.read_text() for p in store.glob("*.txt") if '"interrupted":"ContractError"' in p.read_text()]
    assert len(reports) == 1 and '"passed":false' in reports[0] and '"collection":"' in reports[0]
    assert '"manifest"' not in reports[0], "no batch ran after the fence was lost"
    # FAULT: a conftest that blocks collection, so the cancel lands inside the collection process.
    slow = suite_tree(tmp_path / "slow", {"conftest.py": "import time\nprint('COLLECTING', flush=True)\ntime.sleep(60)\n",
                                          "test_a.py": "def test_a():\n    pass\n"})
    timer = interrupt_after(4)
    try:
        with pytest.raises(ProcessCancelled):
            run_suite(slow, timeout=60, extra=["-s"])
    finally:
        timer.cancel()
    store = tmp_path / "slow-artifacts"
    partial = [p.read_text() for p in store.glob("*.txt") if '"interrupted":"ProcessCancelled"' in p.read_text()]
    assert len(partial) == 1 and '"passed":false' in partial[0] and '"cancelled_process":"' in partial[0]
    process = [p.read_text() for p in store.glob("*.txt") if '"cancelled":true' in p.read_text()]
    assert len(process) == 1 and "COLLECTING" in process[0] and '"label":"collection"' in process[0]


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
