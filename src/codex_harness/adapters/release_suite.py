"""Checklist-complete release test suites (INV-CHECK-002).

One pytest invocation for a whole suite had one deadline and lost its output when the deadline
killed it, so a timeout could not be told apart from a blocked test or a failure. A release suite
here is instead: one collection of exact node IDs under the check's own argv, config and import
semantics -> an immutable manifest -> deterministic serial batches, each its own owned process
under the per-process deadline -> per-node results reconciled against the plan. Output streams to
owner files, so a timeout keeps the log and the last observed test; every process leaves a
redacted receipt, and one suite report links the manifest, each batch and the verdict.

The accounting plugin is written by this controller into an owner temporary directory; it is not
taken from the candidate or the incumbent checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from codex_harness.adapters.commands import ProcessCancelled, run_logged_process
from codex_harness.domain.check_results import (
    NODE_OUTCOMES,
    classify_batch,
    classify_collection,
    last_event,
    node_results,
    nodes_digest,
    plan_batches,
    reconcile_nodes,
)
from codex_harness.domain.model import canonical
from codex_harness.domain.observation import redact_text

BATCH_NODES = 200
LOG_HEAD_BYTES = 16 * 1024
LOG_TAIL_BYTES = 240 * 1024
EVENTS_TAIL_BYTES = 1024 * 1024
PLUGIN_MODULE = "release_accounting_plugin"
REPORT_ENV = "RELEASE_ACCOUNTING_REPORT"
SELECT_ENV = "RELEASE_ACCOUNTING_SELECT"
LAST_TEST_NOTE = "last test observed before the process ended; not attributed as the cause"

PLUGIN_SOURCE = '''\
"""Release accounting: one flushed JSON line per collection, phase and finish (owner-written)."""
import hashlib
import json
import os

import pytest

_REPORT = os.environ["RELEASE_ACCOUNTING_REPORT"]
_SELECT = os.environ.get("RELEASE_ACCOUNTING_SELECT")
_stream = []


def _emit(event):
    if not _stream:
        _stream.append(open(_REPORT, "a", encoding="utf-8"))
    _stream[0].write(json.dumps(event, sort_keys=True) + "\\n")
    _stream[0].flush()


def pytest_configure(config):
    _emit({"event": "configure", "rootpath": str(config.rootpath),
           "inipath": str(config.inipath) if config.inipath else None})


def pytest_collectreport(report):
    if report.failed:
        _emit({"event": "collect_error", "nodeid": report.nodeid, "longrepr": str(report.longrepr)[-4000:]})


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    ids = [item.nodeid for item in items]
    digest = hashlib.sha256("\\n".join(ids).encode("utf-8")).hexdigest()
    _emit({"event": "collected", "count": len(ids), "sha256": digest, **({} if _SELECT else {"nodeids": ids})})
    if _SELECT:
        with open(_SELECT, encoding="utf-8") as handle:
            wanted = set(json.load(handle))
        keep = [item for item in items if item.nodeid in wanted]
        dropped = [item for item in items if item.nodeid not in wanted]
        if dropped:
            config.hook.pytest_deselected(items=dropped)
        items[:] = keep
        _emit({"event": "selected", "nodeids": [item.nodeid for item in keep]})


def pytest_runtest_logstart(nodeid, location):
    _emit({"event": "start", "nodeid": nodeid})


def pytest_runtest_logreport(report):
    event = {"event": "phase", "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
             "xfail": hasattr(report, "wasxfail"), "duration": round(report.duration, 3)}
    if report.outcome != "passed":
        event["longrepr"] = str(report.longrepr)[-4000:]
    _emit(event)


def pytest_runtest_logfinish(nodeid, location):
    _emit({"event": "finish", "nodeid": nodeid})


def pytest_sessionfinish(session, exitstatus):
    _emit({"event": "sessionfinish", "exitstatus": int(exitstatus)})
'''


def read_events(path: Path) -> tuple[list, int]:
    """Parsed accounting lines and the count of torn or foreign lines (counted, never dropped silently)."""
    if not path.exists():
        return [], 0
    events, torn = [], 0
    for line in path.read_text("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            torn += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            torn += 1
    return events, torn


def bounded_log(path: Path, head: int = LOG_HEAD_BYTES, tail: int = LOG_TAIL_BYTES) -> dict:
    """A redacted head+tail of one output file with its true size; the tail keeps the last progress."""
    data = path.read_bytes() if path.exists() else b""
    if len(data) <= head + tail:
        text, omitted = data.decode("utf-8", errors="replace"), 0
    else:
        omitted = len(data) - head - tail
        text = (data[:head].decode("utf-8", errors="replace") + f"\n...[{omitted} bytes omitted]...\n"
                + data[-tail:].decode("utf-8", errors="replace"))
    text, redactions = redact_text(text)
    return {"text": text, "bytes": len(data), "omitted_bytes": omitted, "redactions": redactions}


def _progress(events) -> dict:
    started = [e.get("nodeid") for e in events if e.get("event") == "start"]
    finished = [e.get("nodeid") for e in events if e.get("event") == "finish"]
    in_progress = started[-1] if started and (not finished or finished[-1] != started[-1]) else None
    return {"last_started": started[-1] if started else None, "last_finished": finished[-1] if finished else None,
            "unfinished": in_progress, "note": LAST_TEST_NOTE}


class ReleaseSuite:
    """Runs one pytest release check as a collected manifest and bounded serial batches."""

    def __init__(self, artifacts, fence, batch_nodes: int = BATCH_NODES):
        self.artifacts, self.fence, self.batch_nodes = artifacts, fence, batch_nodes

    def check(self, argv: list[str], *, cwd, timeout: int, env: dict | None, binding: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="zeus-release-suite-") as directory:
            root = Path(directory)
            (root / "plugin").mkdir()
            (root / "plugin" / (PLUGIN_MODULE + ".py")).write_text(PLUGIN_SOURCE, encoding="utf-8")
            base = dict(os.environ if env is None else env)
            base["PYTHONPATH"] = os.pathsep.join([str(root / "plugin")] + (
                [base["PYTHONPATH"]] if base.get("PYTHONPATH") else []))
            context = {"argv": argv, "binding": binding, "env_keys": sorted(env) if isinstance(env, dict) else None,
                       "accounting": {"plugin": PLUGIN_MODULE, "env_keys": ["PYTHONPATH", REPORT_ENV, SELECT_ENV]},
                       "timeout_seconds": timeout, "batch_nodes": self.batch_nodes}
            return self._suite(argv, cwd, timeout, base, root, context)

    def _run(self, label, argv, cwd, timeout, env, root, select=None):
        report = root / (label + ".jsonl")
        child = {**env, REPORT_ENV: str(report)}
        if select is not None:
            (root / (label + ".select.json")).write_text(json.dumps(select), encoding="utf-8")
            child[SELECT_ENV] = str(root / (label + ".select.json"))
        stdout, stderr = root / (label + ".stdout"), root / (label + ".stderr")
        try:
            observation = run_logged_process(argv, stdout_path=stdout, stderr_path=stderr, cwd=cwd,
                                             timeout=timeout, env=child)
        except ProcessCancelled as exc:
            observation = exc.observation
            events, torn = read_events(report)
            exc.receipt = self._receipt(label, argv, observation, events, torn, stdout, stderr, report,
                                        {"passed": False, "outcome": "observation_error", "reason": "cancelled"})
            raise
        except OSError as exc:
            observation = {"exit_code": None, "timed_out": False, "error": type(exc).__name__ + ": " + str(exc)[:300]}
        events, torn = read_events(report)
        return observation, events, torn, (stdout, stderr, report)

    def _receipt(self, label, argv, observation, events, torn, stdout, stderr, report, verdict, **extra):
        raw = report.read_bytes()[-EVENTS_TAIL_BYTES:] if report.exists() else b""
        text, redactions = redact_text(raw.decode("utf-8", errors="replace"))
        body = {"kind": "release-suite-process", "label": label, "argv": argv, **observation,
                "stdout": bounded_log(stdout), "stderr": bounded_log(stderr),
                "events": {"text": text, "bytes": report.stat().st_size if report.exists() else 0,
                           "parsed": len(events), "torn": torn, "redactions": redactions},
                "progress": _progress(events), "verdict": verdict, **extra}
        return self.artifacts.put(canonical(body), "canary-suite")["ref"]

    def _suite(self, argv, cwd, timeout, env, root, context):
        self.fence()
        collect = argv + ["--collect-only", "-p", PLUGIN_MODULE]
        observation, events, torn, files = self._run("collection", collect, cwd, timeout, env, root)
        collection = classify_collection(observation["exit_code"], events)
        if observation.get("timed_out"):
            collection = {**collection, "reason": f"collection timed out after {timeout}s"}
        nodeids = collection.pop("nodeids", None)
        collection_ref = self._receipt("collection", collect, observation, events, torn, *files, collection)
        self.fence()
        configured = last_event(events, "configure") or {}
        report = {**context, "kind": "release-suite", "collection": collection_ref,
                  "config": {"rootpath": configured.get("rootpath"), "inipath": configured.get("inipath"),
                             "inifile_sha256": _file_digest(configured.get("inipath"))}}
        if not collection["passed"]:
            return self._finish(report, collection, {"collected": len(nodeids or []), "batches": 0, "batches_run": 0,
                                                     **dict.fromkeys(NODE_OUTCOMES, 0), "not_run": 0, "finished": 0},
                                observation["exit_code"])
        manifest = {"count": len(nodeids), "sha256": nodes_digest(nodeids)}
        batches = plan_batches(nodeids, self.batch_nodes)
        redacted = [redact_text(nodeid)[0] for nodeid in nodeids]
        manifest_ref = self.artifacts.put(canonical({
            "kind": "release-suite-manifest", **manifest, "argv": argv, "binding": context["binding"],
            "config": report["config"], "nodeids": redacted,
            "redacted_nodeids": sum(a != b for a, b in zip(redacted, nodeids)),
            "batches": [{"index": i, "count": len(b), "sha256": nodes_digest(b)} for i, b in enumerate(batches)]}),
            "canary-suite-manifest")["ref"]
        report.update(manifest=manifest_ref, manifest_sha256=manifest["sha256"])
        counts, finished, rows, exit_code = dict.fromkeys(NODE_OUTCOMES, 0), [], [], 0
        verdict = None
        try:
            for index, planned in enumerate(batches):
                label = f"batch-{index:04d}"
                self.fence()
                run = argv + ["-p", PLUGIN_MODULE]
                observation, events, torn, files = self._run(label, run, cwd, timeout, env, root, select=planned)
                batch = classify_batch(planned, manifest, observation["exit_code"], events)
                if observation.get("timed_out"):
                    batch = {**batch, "reason": f"batch timed out after {timeout}s; " + batch["reason"]}
                ref = self._receipt(label, run, observation, events, torn, *files, batch,
                                    planned={"count": len(planned), "sha256": nodes_digest(planned)},
                                    manifest_sha256=manifest["sha256"])
                rows.append({"index": index, "count": len(planned), "evidence": ref, "passed": batch["passed"],
                             "outcome": batch["outcome"], "counts": batch["counts"], "exit_code": observation["exit_code"]})
                for key, value in batch["counts"].items():
                    counts[key] += value
                finished += [nodeid for nodeid, _ in node_results(events)]
                if observation["exit_code"] != 0 and exit_code == 0:
                    exit_code = observation["exit_code"]
                self.fence()
                if not batch["passed"]:
                    verdict = {"passed": False, "outcome": batch["outcome"],
                               "reason": f"batch {index} of {len(batches)}: {batch['reason']}"}
                    break
        except BaseException as exc:
            # Cancel or a lost fence: the partial report is kept; nothing here is a verdict.
            rows += [{"index": i, "count": len(b), "outcome": "not_run"} for i, b in enumerate(batches) if i >= len(rows)]
            self.artifacts.put(canonical({**report, "batches": rows, "interrupted": type(exc).__name__,
                                          "cancelled_process": getattr(exc, "receipt", None),
                                          "verdict": {"passed": False, "outcome": "observation_error",
                                                      "reason": "suite interrupted"}}), "canary-suite")
            raise
        rows += [{"index": i, "count": len(b), "outcome": "not_run"} for i, b in enumerate(batches) if i >= len(rows)]
        not_run = sum(row["count"] for row in rows if row["outcome"] == "not_run")
        denominator = {"collected": len(nodeids), "batches": len(batches),
                       "batches_run": sum(row["outcome"] != "not_run" for row in rows), **counts,
                       "not_run": not_run, "finished": sum(counts.values())}
        report["batches"] = rows
        if verdict is None:
            coverage = reconcile_nodes(nodeids, finished)
            executed = counts["passed"] + counts["xfailed"] + counts["xpassed"]
            if not coverage["complete"]:
                verdict = {"passed": False, "outcome": "coverage_mismatch",
                           "reason": "suite accounting does not cover the manifest exactly"}
            elif executed == 0:
                verdict = {"passed": False, "outcome": "empty_check",
                           "reason": f"nothing executed: {counts['skipped']} skipped of {len(nodeids)} collected"}
            else:
                verdict = {"passed": True, "outcome": "executed",
                           "reason": f"{counts['passed']} passed, {counts['skipped']} skipped, "
                                     f"{counts['xfailed']} xfailed of {len(nodeids)} collected in {len(batches)} batches"}
        return self._finish(report, verdict, denominator, exit_code if all(
            row.get("exit_code") is not None for row in rows if row["outcome"] != "not_run") else None)

    def _finish(self, report, verdict, denominator, exit_code):
        verdict = {key: verdict[key] for key in ("passed", "outcome", "reason")}
        ref = self.artifacts.put(canonical({**report, "denominator": denominator, "exit_code": exit_code,
                                            "verdict": verdict}), "canary-suite")["ref"]
        return {**verdict, "evidence": ref, "denominator": denominator, "binding": report["binding"]}


def _file_digest(path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
    except OSError:
        return None
