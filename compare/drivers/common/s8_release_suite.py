"""Shared S8 scenario steps for `review.release_suite`, characterized BEFORE pilot 95 moves M7 `adapters/release_suite.py`
(DESIGN-s8 §14 V19 R-rs0..R-rs2), mirroring M7 `tests/test_release_suite.py`:

- `ReleaseSuite.check` over a LABELLED fake `run_logged_process` (`FakeRunner`): a pass in bounded batches, a failed batch that stops the rest,
  collection failures, an empty collection, an all-skipped suite, collection and batch timeouts, a spawn `OSError`, a torn event file, a collected
  manifest that drifts, an omitted and a duplicated node, a cancellation (`ProcessCancelled`) around collection and inside a batch, a lost fence
  around collection and between batches, a stale accounting environment, credential-shaped node ids (the receipts' redaction counts), the default
  batch size, the caller's environment left unmutated;
- `bounded_log` (head/tail bounds, the omitted marker, redaction after the cut, a missing file, bytes that are not UTF-8);
- `read_events` (missing file, blank/torn/foreign lines, invalid bytes);
- the module constants and the accounting plugin's digest.

No real pytest child runs: M7's cases that start real child processes are mapped to the scripted cases in `M7_TESTS`. The artifact store is a LABELLED
fake (`FakeArtifacts.put`): every stored document is recorded decoded, its ref a function of its kind and position.

Documented normalization rule (the only one): the suite writes into a `tempfile.TemporaryDirectory(prefix="zeus-release-suite-")` and the
driver into one scratch directory; every string in a recorded result has each such root replaced by `<root>` / `<scratch>` (`normalize`). Nothing else is
rewritten: no id, clock, pid or digest is masked (none is drawn).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `make_suite(artifacts, fence, runner, batch_nodes=None)`, `bounded_log`,
`read_events`, `ProcessCancelled`, `ContractError`, `constants` and `PLUGIN_SOURCE`."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

# Credential-shaped values are assembled from fragments so no complete credential-shaped literal is committed.
GH = "gh" + "p_" + "A" * 24
GH_OMITTED = "gh" + "p_" + "B" * 24
ASSIGNED = "pass" + "word=" + "hunter2-CANARY"
BEARER = "Bear" + "er " + "abcdefgh12345678"

ROOTPATH = "/work/repo"
ARGV = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
BINDING = {"cwd": None, "expected_revision": None, "env_keys": None}
NODES = ["tests/test_a.py::test_one", "tests/test_a.py::test_two", "tests/test_b.py::test_p[1]", "tests/test_b.py::test_p[a::b]",
         "tests/test_c.py::test_skip"]
OK = {"exit_code": 0, "timed_out": False}
M7_TESTS = {
    "test_complete_manifest_runs_every_parameterized_node_in_bounded_batches": "passes_in_batches",
    "test_nested_suite_accounts_outer_and_inner_nodes_with_separate_evidence": "stale_accounting_environment (the inherited accounting variables)",
    "test_nested_failed_inner_suite_is_never_an_outer_pass": "failed_batch_stops_the_rest",
    "test_caller_supplied_stale_accounting_environment_is_not_inherited": "stale_accounting_environment",
    "test_collection_failure_and_empty_collection_are_never_passes": "collection_failure, empty_collection, all_skipped",
    "test_failed_batch_stops_the_remaining_batches_as_not_run": "failed_batch_stops_the_rest",
    "test_injected_omitted_duplicate_or_drifted_nodes_refuse": "omitted_node, duplicate_node, drifted_collection",
    "test_unexpected_or_unfinished_accounting_is_not_a_pass": "(domain.check_results; not this module)",
    "test_credential_shaped_parameter_ids_are_redacted_in_every_receipt_field": "credential_shaped_node_ids",
    "test_failed_tree_kill_never_leaves_reaping_unbounded": "(adapters.commands; host_os.process)",
    "test_batch_plan_is_deterministic_and_portable": "(domain.check_results; not this module)",
    "test_timeout_keeps_partial_log_last_test_and_owned_cleanup": "batch_timeout",
    "test_cancel_keeps_partial_log_and_cleans_up": "cancel_in_batch, cancel_in_collection",
    "test_lost_fence_between_batches_refuses_and_grants_nothing": "lost_fence_between_batches",
    "test_lost_fence_or_cancel_around_collection_keeps_a_partial_report": "lost_fence_around_collection, cancel_in_collection",
    "test_incumbent_tests_run_against_candidate_code_with_incumbent_config": "config_file_digest (inipath of a real file)",
    "test_run_process_default_behavior_is_unchanged": "(adapters.commands; host_os.process)",
}


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    return value


def normalize(value, roots):
    """The documented rule: every root directory string becomes its symbolic name."""
    if isinstance(value, str):
        for root, name in roots:
            value = value.replace(root, name)
        return value
    if isinstance(value, dict):
        return {normalize(k, roots): normalize(v, roots) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v, roots) for v in value]
    return value


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_of(nodeids) -> str:
    return sha("\n".join(nodeids))


# ---- scripted accounting events -------------------------------------------------------------------------------------------------------------

def collected(nodeids, *, count=None, digest=None, with_ids=True):
    event = {"event": "collected", "count": len(nodeids) if count is None else count, "sha256": digest_of(nodeids) if digest is None else digest}
    if with_ids:
        event["nodeids"] = list(nodeids)
    return event


def node_events(nodeid, kind):
    start, finish = {"event": "start", "nodeid": nodeid}, {"event": "finish", "nodeid": nodeid}

    def phase(when, outcome, **extra):
        return {"event": "phase", "nodeid": nodeid, "when": when, "outcome": outcome, "xfail": extra.get("xfail", False), "duration": 0.001,
                **({"longrepr": extra["longrepr"]} if "longrepr" in extra else {})}

    if kind == "hang":
        return [start]
    body = {"passed": [phase("call", "passed")], "failed": [phase("call", "failed", longrepr="assert False")],
            "skipped": [phase("setup", "skipped", longrepr="skipped")], "xfailed": [phase("call", "skipped", xfail=True)],
            "xpassed": [phase("call", "passed", xfail=True)], "errors": [phase("setup", "failed", longrepr="fixture error")],
            "unknown": [phase("setup", "passed")]}[kind]
    return [start, *body, finish]


def collection_call(nodeids, *, inipath=None, obs=None, **extra):
    return {"obs": obs or dict(OK), "events": [{"event": "configure", "rootpath": ROOTPATH, "inipath": inipath}, collected(nodeids)], **extra}


def batch_call(planned, manifest, outcomes=None, *, obs=None, collected_event=None, selected=None, finish=True, **extra):
    """One batch child's report: the re-collection, the selection, each planned node's phases and the session finish."""
    outcomes = outcomes or {}
    events = [{"event": "configure", "rootpath": ROOTPATH, "inipath": None},
              collected_event or collected(manifest, with_ids=False), {"event": "selected", "nodeids": list(planned if selected is None else selected)}]
    for nodeid in planned:
        events += node_events(nodeid, outcomes.get(nodeid, "passed"))
    if finish:
        events.append({"event": "sessionfinish", "exitstatus": 0})
    return {"obs": obs or dict(OK), "events": events, **extra}


# ---- the labelled doubles -------------------------------------------------------------------------------------------------------------------

class FakeArtifacts:
    """LABELLED double of `FileArtifacts.put` as the suite calls it: the canonical bytes are recorded decoded, the ref is its kind and position (the stored bytes carry host paths, so no digest of them is part of a ref)."""

    def __init__(self):
        self.records = []

    def put(self, data, kind):
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        ref = f"fake:{kind}:{len(self.records) + 1}"
        self.records.append({"ref": ref, "kind": kind, "document": json.loads(text)})
        return {"ref": ref}


class FakeRunner:
    """LABELLED double of `run_logged_process`: each call consumes the next script entry, writes the scripted stdout/stderr and accounting lines
    into the owner files the suite named, records the call (labels, argv, timeout, accounting environment, the plugin file and the selection)
    and returns the scripted observation, or raises the scripted fault (`cancel`: the side's `ProcessCancelled`; `oserror`)."""

    def __init__(self, api, script, *, record_env=False):
        self.api, self.script, self.record_env, self.calls, self.roots = api, list(script), record_env, [], []

    def __call__(self, argv, *, stdout_path, stderr_path, cwd=None, timeout=120, env=None):
        if not self.script:
            raise AssertionError("unscripted run_logged_process call: " + str(argv))
        spec = self.script.pop(0)
        root = Path(stdout_path).parent
        self.roots.append(str(root))
        env = {} if env is None else env
        c = self.api.constants
        first = (env.get("PYTHONPATH") or "").split(":")[0]
        plugin = Path(first) / (c["PLUGIN_MODULE"] + ".py")
        select = env.get(c["SELECT_ENV"])
        call = {"label": Path(stdout_path).name, "argv": list(argv), "cwd": cwd, "timeout": timeout, "stderr_name": Path(stderr_path).name,
                "report_name": Path(env[c["REPORT_ENV"]]).name if c["REPORT_ENV"] in env else None,
                "select_name": Path(select).name if select else None,
                # the selection file holds the planned node ids unredacted (owner file); only its size and digest are recorded
                "select_count": len(json.loads(Path(select).read_text("utf-8"))) if select else None,
                "select_sha256": digest_of(json.loads(Path(select).read_text("utf-8"))) if select else None,
                "pythonpath_first": first, "plugin_exists": plugin.is_file(),
                "plugin_is_PLUGIN_SOURCE": plugin.is_file() and plugin.read_text("utf-8") == self.api.PLUGIN_SOURCE}
        if self.record_env:
            call["env_keys"] = sorted(env)
            call["pythonpath_rest"] = (env.get("PYTHONPATH") or "").split(":")[1:]
        self.calls.append(call)
        Path(stdout_path).write_text(spec.get("stdout", ""), encoding="utf-8")
        Path(stderr_path).write_text(spec.get("stderr", ""), encoding="utf-8")
        report = Path(env[c["REPORT_ENV"]])
        report.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in spec.get("events", [])) + spec.get("raw", ""), encoding="utf-8")
        if spec.get("no_report"):
            report.unlink()
        if "oserror" in spec:
            raise OSError(spec["oserror"])
        if "cancel" in spec:
            raise self.api.ProcessCancelled(copy.deepcopy(spec["cancel"]))
        return copy.deepcopy(spec["obs"])


class World:
    def __init__(self, api, script, *, fence=None, batch_nodes=None, record_env=False):
        self.api, self.artifacts, self.runner = api, FakeArtifacts(), FakeRunner(api, script, record_env=record_env)
        self.fence_calls = []
        self.fence_after = None if fence is None else fence

        def counting_fence():
            self.fence_calls.append(1)
            if self.fence_after is not None and len(self.fence_calls) > self.fence_after:
                raise api.ContractError("Stale release controller")

        self.suite = api.make_suite(self.artifacts, counting_fence, self.runner, batch_nodes)

    def check(self, *, argv=None, env=None, timeout=30, binding=None, scratch=None):
        before = None if env is None else copy.deepcopy(env)
        try:
            result = {"returned": plain(self.suite.check(list(argv or ARGV), cwd=ROOTPATH, timeout=timeout, env=env,
                                                          binding=BINDING if binding is None else binding))}
        except BaseException as exc:  # the interruption (ContractError, ProcessCancelled) is the characterized result
            result = {"raised": type(exc).__name__, "message": str(exc)[:300], "observation": plain(getattr(exc, "observation", None)),
                      "receipt": getattr(exc, "receipt", None)}
        roots = [(r, "<root>") for r in self.runner.roots] + ([(scratch, "<scratch>")] if scratch else [])
        record = {"result": result, "calls": self.runner.calls, "fence_calls": len(self.fence_calls), "artifacts": self.artifacts.records,
                  "unconsumed_script": len(self.runner.script), "caller_env_unmutated": env is None or env == before,
                  "temp_removed": not any(Path(r).exists() for r in self.runner.roots)}
        return normalize(record, roots)


def passing_batches(batch_nodes=2):
    """collection + the three batches of NODES at 2 per batch, every node passing (skipped/xfailed as marked)."""
    outcomes = {NODES[3]: "xfailed", NODES[4]: "skipped"}
    return [collection_call(NODES), batch_call(NODES[0:2], NODES), batch_call(NODES[2:4], NODES, outcomes), batch_call(NODES[4:5], NODES, outcomes)]


def cases(api, scratch: str) -> dict:
    env = {"PATH": "/usr/bin", "PYTHONPATH": "/x/lib:/y/lib", "LANG": "C"}
    c = api.constants
    stale = {**env, c["REPORT_ENV"]: "/stale/report.jsonl", c["SELECT_ENV"]: "/stale/select.json"}
    out = {}

    def run(name, script, *, fence=None, batch_nodes=2, record_env=True, scratch=scratch, **kwargs):
        out[name] = World(api, script, fence=fence, batch_nodes=batch_nodes, record_env=record_env).check(scratch=scratch, **kwargs)

    run("passes_in_batches", passing_batches(), env=env)
    run("passes_with_default_batch_size", [collection_call(NODES), batch_call(NODES, NODES, {NODES[4]: "skipped", NODES[3]: "xpassed"})], env=env,
        batch_nodes=None)
    run("stale_accounting_environment", passing_batches(), env=stale)
    # env=None: the suite copies the process environment; only the accounting facts are recorded (the rest differs by host).
    out["environment_none_uses_the_process_environment"] = World(api, passing_batches(), batch_nodes=2).check(scratch=scratch)
    run("failed_batch_stops_the_rest", [collection_call(NODES), batch_call(NODES[0:2], NODES, {NODES[1]: "failed"}, obs={"exit_code": 1, "timed_out": False},
                                                                           stdout="FAILED test_two\nassert False\n")], env=env)
    run("collection_failure", [{"obs": {"exit_code": 2, "timed_out": False}, "events": [
        {"event": "configure", "rootpath": ROOTPATH, "inipath": None},
        {"event": "collect_error", "nodeid": "tests/test_bad.py", "longrepr": "SyntaxError: invalid syntax"}], "stdout": "ERROR collecting\n"}], env=env)
    run("empty_collection", [{"obs": {"exit_code": 5, "timed_out": False}, "events": [
        {"event": "configure", "rootpath": ROOTPATH, "inipath": None}, {"event": "collected", "count": 0, "sha256": digest_of([]), "nodeids": []}]}], env=env)
    run("collection_without_report", [{"obs": dict(OK), "events": [], "no_report": True}], env=env)
    run("ambiguous_collection", [collection_call([NODES[0], NODES[0]])], env=env)
    skipped = {n: "skipped" for n in NODES}
    run("all_skipped", [collection_call(NODES), batch_call(NODES[0:2], NODES, skipped), batch_call(NODES[2:4], NODES, skipped),
                        batch_call(NODES[4:5], NODES, skipped)], env=env)
    run("collection_timeout", [{"obs": {"exit_code": None, "timed_out": True, "cleanup": {"method": "killpg", "descendants_gone": True}}, "events": [
        {"event": "configure", "rootpath": ROOTPATH, "inipath": None}], "stdout": "COLLECTING\n"}], env=env, timeout=8)
    run("batch_timeout", [collection_call(NODES), batch_call(NODES[0:2], NODES, {NODES[1]: "hang"}, finish=False,
                                                              obs={"exit_code": None, "timed_out": True, "cleanup": {"method": "killpg", "descendants_gone": True}},
                                                              stdout="FIRST-PROGRESS\nHANG-PROGRESS\n")], env=env, timeout=8)
    run("collection_spawn_oserror", [{"oserror": "FAULT: spawn refused " + "x" * 400}], env=env)
    run("batch_spawn_oserror", [collection_call(NODES), {"oserror": "FAULT: spawn refused"}], env=env)
    run("torn_event_file", [{**collection_call(NODES[:2]), "raw": "{torn\n[1, 2]\n\"text\"\n"}, {**batch_call(NODES[0:2], NODES[:2]), "raw": "not json at all\n"}],
        env=env, batch_nodes=2)
    run("drifted_collection", [collection_call(NODES), batch_call(NODES[0:2], NODES, collected_event=collected(NODES[:-1], with_ids=False))], env=env)
    run("omitted_node", [collection_call(NODES), {**batch_call(NODES[0:2], NODES),
                                                  "events": [e for e in batch_call(NODES[0:2], NODES)["events"] if e.get("nodeid") != NODES[1]]}], env=env)
    run("duplicate_node", [collection_call(NODES), {**batch_call(NODES[0:2], NODES), "events": batch_call(NODES[0:2], NODES)["events"][:-1]
                                                    + node_events(NODES[0], "passed") + [{"event": "sessionfinish", "exitstatus": 0}]}], env=env)
    run("unexpected_node", [collection_call(NODES), {**batch_call(NODES[0:2], NODES), "events": batch_call(NODES[0:2], NODES)["events"][:-1]
                                                     + node_events("tests/test_z.py::test_zz", "passed") + [{"event": "sessionfinish", "exitstatus": 0}]}], env=env)
    cancel = {"exit_code": None, "timed_out": False, "cancelled": True, "cleanup": {"method": "killpg", "descendants_gone": True, "reason": "proven"}}
    run("cancel_in_collection", [{"cancel": cancel, "events": [{"event": "configure", "rootpath": ROOTPATH, "inipath": None}], "stdout": "COLLECTING\n"}], env=env)
    run("cancel_in_batch", [collection_call(NODES), batch_call(NODES[0:2], NODES, {NODES[1]: "hang"}, finish=False, cancel={"cleanup": "proven"},
                                                               stdout="HANG-PROGRESS\n")], env=env)
    run("lost_fence_around_collection", [collection_call(NODES)], env=env, fence=1)
    run("lost_fence_between_batches", [collection_call(NODES[:2]), batch_call(NODES[0:1], NODES[:2])], env=env, fence=4, batch_nodes=1)
    run("lost_fence_before_collection", [], env=env, fence=0)
    with tempfile.TemporaryDirectory(prefix="zeus-s8-release-suite-ini-") as raw:
        ini = Path(raw) / "pytest.ini"
        ini.write_text("[pytest]\n", encoding="utf-8")
        run("config_file_digest", [collection_call(NODES[:1], inipath=str(ini)), batch_call(NODES[:1], NODES[:1])], env=env,
            argv=ARGV + ["-c", str(ini)], scratch=raw)
        run("config_file_missing", [collection_call(NODES[:1], inipath=str(Path(raw) / "gone.ini")), batch_call(NODES[:1], NODES[:1])], env=env, scratch=raw)
    secret_nodes = ["tests/test_s.py::test_p[" + GH + "]", "tests/test_s.py::test_p[" + GH_OMITTED + "]"]
    run("credential_shaped_node_ids", [collection_call(secret_nodes), batch_call(secret_nodes[:1], secret_nodes, selected=secret_nodes[:1],
                                                                                 stdout="out " + GH + " " + ASSIGNED + "\n", stderr="err " + BEARER + "\n",
                                                                                 raw="{torn " + GH + "\n")],
        env=env, batch_nodes=10, binding={"cwd": None, "expected_revision": "c" * 40, "env_keys": ["TOKEN"]})
    return out


# ---- bounded_log / read_events --------------------------------------------------------------------------------------------------------------

def log_view(result, *, keep=60):
    """A bounded view of a large result: sizes, counts and the digest of the text, with the first and last `keep` characters."""
    text = result["text"]
    return {**{k: v for k, v in result.items() if k != "text"}, "text_chars": len(text), "text_sha256": sha(text), "text_head": text[:keep],
            "text_tail": text[-keep:]}


def bounded_logs(api, scratch: str) -> dict:
    root = Path(scratch)
    out = {}

    def log(name, data, *args, view=False, **kwargs):
        path = root / name
        if data is not None:
            path.write_bytes(data)
        try:
            result = api.bounded_log(path, *args, **kwargs)
            out[name] = {"returned": plain(log_view(result) if view else result)}
        except Exception as exc:
            out[name] = {"refused": type(exc).__name__, "message": str(exc)[:300]}

    log("missing", None)
    log("empty", b"")
    log("small", b"line one\nline two\n")
    log("secret_lines", ("head " + GH + "\n" + ASSIGNED + "\n" + BEARER + "\ntail\n").encode())
    log("exactly_the_bound", b"a" * 10 + b"b" * 10, 10, 10)
    log("one_over_the_bound", b"a" * 10 + b"m" + b"b" * 10, 10, 10)
    log("omitted_marker", b"HEAD-" + b"x" * 100 + b"-TAIL", 5, 5)
    log("secret_in_the_kept_tail", b"x" * 50 + (" " + GH + " ").encode(), 5, 40)
    log("secret_split_by_the_cut", b"x" * 20 + GH.encode() + b"y" * 20, 30, 10)
    log("not_utf8", b"ok\xff\xfe bad \xc3(\n")
    log("not_utf8_cut", "한국어 로그 ".encode() * 20, 8, 8)
    log("default_bounds_large", b"".join(b"line %06d\n" % i for i in range(26000)), view=True)
    log("default_bounds_exact", b"y" * (api.constants["LOG_HEAD_BYTES"] + api.constants["LOG_TAIL_BYTES"]), view=True)
    log("default_bounds_one_over", b"y" * (api.constants["LOG_HEAD_BYTES"] + api.constants["LOG_TAIL_BYTES"] + 1), view=True)
    return normalize(out, [(scratch, "<scratch>")])


def read_events_cases(api, scratch: str) -> dict:
    root = Path(scratch)
    out = {}

    def read(name, data):
        path = root / name
        if data is not None:
            path.write_bytes(data)
        events, torn = api.read_events(path)
        out[name] = {"events": plain(events), "torn": torn}

    read("events_missing", None)
    read("events_empty", b"")
    read("events_clean", b'{"event": "a"}\n{"event": "b", "n": 1}\n')
    read("events_blank_lines_are_torn", b'{"event": "a"}\n\n   \n{"event": "b"}\n')
    read("events_torn_and_foreign", b'{"event": "a"}\n{torn\n[1, 2]\n"text"\n42\nnull\n{"event": "b"}\n{"event"')
    read("events_invalid_utf8_replaced", b'{"event": "a", "x": "\xff\xfe"}\n\xff\xfe\n')
    read("events_no_trailing_newline", b'{"event": "a"}')
    read("events_crlf", b'{"event": "a"}\r\n{"event": "b"}\r\n')
    return out


def release_suite(api) -> dict:
    with tempfile.TemporaryDirectory(prefix="zeus-s8-release-suite-") as raw:
        scratch = str(Path(raw).resolve())
        return {"m7_tests_mapped": M7_TESTS, "constants": {**api.constants, "plugin_source_sha256": sha(api.PLUGIN_SOURCE),
                                                           "plugin_source_lines": api.PLUGIN_SOURCE.count("\n")},
                "check": cases(api, scratch), "bounded_log": bounded_logs(api, scratch), "read_events": read_events_cases(api, scratch)}
