"""Shared S8 scenario steps (`observation.monitoring_readiness`): M7 `adapters/monitoring_readiness.py` (`readiness`, `snapshot_state`,
`envelope_state`, `source_states`, `elapsed`, `parse`, `state` and the closed reason sets), characterized BEFORE the module moves
(DESIGN-s8 §12.1 V17 P-a: an S9 row moved AHEAD in S8). The cases mirror M7 `tests/test_monitor_readiness.py` without its HTTP server
(`monitoring_web` is not part of this move); each case group names its test in `M7_TESTS`.

- **s1_constants**: the schema, service, basis, window, tolerance, source tuples and the two closed reason sets.
- **s2_freshness**: `test_freshness_and_future_boundaries_are_exact` (7 ages), `test_collector_and_source_freshness_are_independent`,
  `test_fresh_snapshot_is_ready...`, `test_present_optional_envelopes...`, `test_payload_content_is_never_read_as_health`, and `elapsed` directly.
- **s3_envelopes**: `test_broken_required_envelopes_are_named_without_echoing_them` (10), `envelope_state`, `source_states`, the redaction case.
- **s4_snapshot_files**: the 17 undecodable payloads (deep nesting named in the M7 test as two safe reasons: both are recorded here as observed),
  `test_structurally_valid_snapshot_with_broken_collected_at...`, missing/unreadable path (directory), the oversized snapshot at and above
  `MAX_SNAPSHOT_BYTES`, no write, `parse` directly.
- **s5_now**: `test_naive_now_is_a_caller_error...`, an offset-aware `now`, the `now=None` default (shape only: it reads the real clock).

Temp-path rule (documented, driver-side): every snapshot file lives in one scenario temp directory; `norm` replaces that directory's string,
wherever it occurs in a result, by `<tmp>` and counts the replacements (`TEMP_PATH_REPLACEMENTS`). It never masks a state, a reason or an age;
M7 results contain no path at all, so the count is expected to be zero.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. Nothing here touches a database or a network;
the only file system use is the scenario's own temp directory."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
REQUIRED = ("database", "docker", "redis")
TEMP_PATH_REPLACEMENTS = {"count": 0}


class Scratch:
    """The scenario's single temp directory; removed by `close`."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s8mr-")).resolve()
        self.n = 0

    def path(self):
        self.n += 1
        return self.root / f"monitoring-{self.n}.json"

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def norm(value, root):
    """Replace the temp directory string by `<tmp>` anywhere in a result (documented rule; never masks a state or a reason)."""
    text = str(root)
    if isinstance(value, str):
        TEMP_PATH_REPLACEMENTS["count"] += value.count(text)
        return value.replace(text, "<tmp>")
    if isinstance(value, dict):
        return {norm(k, root): norm(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [norm(v, root) for v in value]
    return value


def envelope(age, now=NOW, status="ok", data=None):
    return {"status": status, "observed_at": (now - timedelta(seconds=age)).isoformat(), "data": [] if data is None else data}


def document(now=NOW, collected=1.0, ages=None, sources=None):
    ages = {"database": 1.0, "docker": 1.0, "redis": 1.0} if ages is None else ages
    envelopes = {name: envelope(age, now) for name, age in ages.items()}
    envelopes.update(sources or {})
    return {"schema": "harness-monitor.v1", "collected_at": (now - timedelta(seconds=collected)).isoformat(),
            "scope": {"label": "repository zeus", "docker": "compose", "containers": None}, "sources": envelopes}


def write(path, body):
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(json.dumps(body), "utf-8")


def answer(api, scratch, body, now=NOW):
    """Write `body` to a fresh snapshot file and return the whole readiness answer (normalized)."""
    path = scratch.path()
    write(path, body)
    return norm(api.readiness(path, now=now), scratch.root)


def s1_constants(api):
    return {"SCHEMA": api.SCHEMA, "SERVICE": api.SERVICE, "BASIS": api.BASIS, "SNAPSHOT_SCHEMA": api.SNAPSHOT_SCHEMA,
            "MAX_SNAPSHOT_BYTES": api.MAX_SNAPSHOT_BYTES, "FRESH_SECONDS": api.FRESH_SECONDS,
            "FUTURE_TOLERANCE_SECONDS": api.FUTURE_TOLERANCE_SECONDS, "REQUIRED_SOURCES": list(api.REQUIRED_SOURCES),
            "OPTIONAL_SOURCES": list(api.OPTIONAL_SOURCES), "SNAPSHOT_REASONS": list(api.SNAPSHOT_REASONS),
            "SOURCE_REASONS": list(api.SOURCE_REASONS),
            "state": api.state("fresh", "current", 1.5), "state_default_age": api.state("unavailable", "file_missing")}


def s2_freshness(api, scratch):
    out = {}
    boundaries = {}
    for label, age in (("19.999", 19.999), ("19.9996", 19.9996), ("19.999999", 19.999999), ("20", 20), ("20.001", 20.001),
                       ("minus_tolerance", -api.FUTURE_TOLERANCE_SECONDS), ("minus_5.001", -5.001)):
        body = document(NOW, collected=age, ages=dict.fromkeys(REQUIRED, age))
        boundaries[label] = answer(api, scratch, body)
    out["test_freshness_and_future_boundaries_are_exact"] = boundaries
    out["test_collector_and_source_freshness_are_independent"] = {
        "collector_stale": answer(api, scratch, document(NOW, collected=300, ages=dict.fromkeys(REQUIRED, 1.0))),
        "docker_stale": answer(api, scratch, document(NOW, collected=1.0, ages={"database": 1.0, "docker": 45.0, "redis": 1.0}))}
    out["test_fresh_snapshot_is_ready"] = answer(api, scratch, document(NOW))
    optional = {"fleet": envelope(1.0), "observations": envelope(1.0), "research_programs": envelope(1.0)}
    out["test_present_optional_envelopes_are_assessed_and_absent_ones_omitted"] = {
        "all_optional_fresh": answer(api, scratch, document(NOW, sources=optional)),
        "fleet_stale": answer(api, scratch, document(NOW, sources={"fleet": envelope(60.0)})),
        "unknown_name_ignored": answer(api, scratch, document(NOW, sources={"extra": envelope(1.0)})),
        "only_observations": answer(api, scratch, document(NOW, sources={"observations": envelope(1.0)})),
        "research_programs_failed": answer(api, scratch, document(NOW, sources={"research_programs": {"status": "unavailable"}}))}
    payload = {"docker": envelope(1.0, data=[{"name": "zeus_pg", "state": "exited"}]),
               "database": envelope(1.0, data={"operating_status": "unknown", "task_counts": {}, "measurements": []}),
               "fleet": envelope(1.0, data={"registered": False, "lanes": [], "jobs": []})}
    out["test_payload_content_is_never_read_as_health"] = answer(api, scratch, document(NOW, sources=payload))
    values = {"none": None, "empty": "", "int": 17, "float": 1.5, "bool": True, "list": [], "yesterday": "yesterday",
              "naive": "2026-09-19T12:00:00", "date_only": "2026-09-19", "z": "2026-09-19T11:59:59Z",
              "offset": "2026-09-19T20:59:59+09:00", "future_ok": "2026-09-19T12:00:04+00:00",
              "future_bad": "2026-09-19T12:00:06+00:00", "year_1": "0001-01-01T00:00:00+00:00",
              "year_9999": "9999-12-31T23:59:59+00:00", "stale": "2026-09-19T11:00:00+00:00",
              "microsecond": "2026-09-19T11:59:40.000001+00:00", "exact_20": "2026-09-19T11:59:40+00:00"}
    out["elapsed_directly"] = {label: list(api.elapsed(v, NOW)) for label, v in values.items()}
    return out


def s3_envelopes(api, scratch):
    out = {}
    cases = {"missing": None, "string": "ok", "list": [], "failed": {"status": "unavailable", "error": "RuntimeError", "observed_at": NOW.isoformat()},
             "no_observed_at": {"status": "ok"}, "empty_observed_at": {"status": "ok", "observed_at": ""},
             "int_observed_at": {"status": "ok", "observed_at": 17}, "yesterday": {"status": "ok", "observed_at": "yesterday"},
             "naive": {"status": "ok", "observed_at": "2026-09-19T12:00:00"}, "date_only": {"status": "ok", "observed_at": "2026-09-19"},
             "status_absent": {"observed_at": NOW.isoformat()}, "status_not_a_string": {"status": ["ok"], "observed_at": NOW.isoformat()},
             "ok_fresh": {"status": "ok", "observed_at": NOW.isoformat()}, "number": 3, "null_value": "null"}
    broken = {}
    for label, value in cases.items():
        body = document(NOW, ages={"docker": 1.0, "redis": 1.0})
        if value is not None:
            body["sources"]["database"] = value
        broken[label] = answer(api, scratch, body)
    out["test_broken_required_envelopes_are_named_without_echoing_them"] = broken
    out["envelope_state_directly"] = {
        "not_present": api.envelope_state(None, False, NOW), "present_none": api.envelope_state(None, True, NOW),
        "dict_ok": api.envelope_state({"status": "ok", "observed_at": NOW.isoformat()}, True, NOW),
        "dict_failed": api.envelope_state({"status": "unavailable"}, True, NOW), "list": api.envelope_state([], True, NOW),
        "present_but_not_a_dict_with_present_false": api.envelope_state("x", False, NOW)}
    out["source_states_directly"] = {
        "empty": api.source_states({}, NOW),
        "required_present": api.source_states({n: envelope(1.0) for n in REQUIRED}, NOW),
        "order_of_optional": list(api.source_states({n: envelope(1.0) for n in ("research_programs", "fleet", "observations", "redis")}, NOW)),
        "unknown_ignored": api.source_states({"zzz": envelope(1.0)}, NOW)}
    secret = "postgresql://admin:s3cr3t@localhost/db"
    body = document(NOW, ages={"docker": 1.0, "redis": 1.0})
    body["scope"]["label"] = secret
    body["sources"]["database"] = {"status": "unavailable", "error": secret, "data": None, "observed_at": "<script>alert(1)</script>"}
    body["sources"]["../../etc/passwd"] = envelope(1.0)
    body["sources"]["ready"] = {"status": "ok", "observed_at": NOW.isoformat()}
    reply = answer(api, scratch, body)
    text = json.dumps(reply)
    out["test_readiness_never_reflects_snapshot_values_keys_paths_or_errors"] = {
        "answer": reply, "leaks": [w for w in ("s3cr3t", "postgresql", "script", "passwd", "RuntimeError", "monitoring-", NOW.isoformat()) if w in text]}
    return out


PAYLOADS = {
    "empty": b"", "truncated": b'{"schema": "harness-monitor.v1", "sources": ',
    "bom": b'\xef\xbb\xbf{"schema": "harness-monitor.v1", "sources": {}}',
    "invalid_utf8": b'{"schema": "harness-monitor.v1", "sources": {}, "label": "\xff\xfe"}',
    "duplicate_key": b'{"schema": "harness-monitor.v1", "schema": "other", "sources": {}}',
    "nan": b'{"schema": "harness-monitor.v1", "collected_at": NaN, "sources": {}}',
    "infinity": b'{"schema": "harness-monitor.v1", "collected_at": Infinity, "sources": {}}',
    "minus_infinity": b'{"schema": "harness-monitor.v1", "collected_at": -Infinity, "sources": {}}',
    "deep_nesting": b'{"schema": "harness-monitor.v1", "sources": ' + b"[" * 20000 + b"]" * 20000 + b"}",
    "deep_nesting_root": b"[" * 20000 + b"]" * 20000,
    "root_array": b"[]", "root_string": b'"harness-monitor.v1"', "root_null": b"null", "root_number": b"7",
    "schema_absent": b'{"sources": {}}', "schema_other": b'{"schema": "harness-monitor.v2", "sources": {}}',
    "schema_list": b'{"schema": ["harness-monitor.v1"], "sources": {}}',
    "sources_absent": b'{"schema": "harness-monitor.v1"}', "sources_array": b'{"schema": "harness-monitor.v1", "sources": []}',
    "sources_string": b'{"schema": "harness-monitor.v1", "sources": "database"}',
    "sources_null": b'{"schema": "harness-monitor.v1", "sources": null}',
    "sources_empty_ok": b'{"schema": "harness-monitor.v1", "sources": {}}',
    "sources_empty_with_collected_at": b'{"schema": "harness-monitor.v1", "collected_at": "2026-09-19T11:59:59+00:00", "sources": {}}',
    "whitespace_only": b"   \n", "trailing_garbage": b'{"schema": "harness-monitor.v1", "sources": {}} x',
}


def s4_snapshot_files(api, scratch):
    out = {}
    payloads = {}
    for label, body in PAYLOADS.items():
        reply = answer(api, scratch, body)
        payloads[label] = {"snapshot": reply["snapshot"], "sources": reply["sources"], "ready": reply["ready"]}
    out["test_undecodable_snapshots_answer_503_with_no_sources_and_no_crash"] = payloads
    body = document(NOW)
    body["collected_at"] = "2026-09-19T12:00:00"
    out["test_structurally_valid_snapshot_with_broken_collected_at_still_assesses_envelopes"] = answer(api, scratch, body)
    for label, value in (("missing", None), ("not_a_string", 5), ("future", "2026-09-19T12:01:00+00:00"), ("unparsable", "not a date")):
        body = document(NOW)
        if value is None:
            del body["collected_at"]
        else:
            body["collected_at"] = value
        out["collected_at_" + label] = answer(api, scratch, body)
    missing = scratch.path()
    out["test_missing_and_unreadable_snapshot_paths_are_unavailable"] = {
        "file_missing": norm(api.readiness(missing, now=NOW), scratch.root),
        "snapshot_state_missing": norm(list(api.snapshot_state(missing, NOW)), scratch.root)}
    directory = scratch.path()
    directory.mkdir()
    out["test_missing_and_unreadable_snapshot_paths_are_unavailable"]["file_unreadable_directory"] = norm(api.readiness(directory, now=NOW), scratch.root)
    out["test_missing_and_unreadable_snapshot_paths_are_unavailable"]["path_as_str"] = norm(api.readiness(str(missing), now=NOW), scratch.root)
    limit = api.MAX_SNAPSHOT_BYTES
    out["test_oversized_snapshot_is_refused_before_parsing"] = {
        "limit_plus_one": answer(api, scratch, b"x" * (limit + 1))["snapshot"],
        "at_limit": answer(api, scratch, b"x" * limit)["snapshot"],
        "limit_plus_one_valid_json_prefix": answer(api, scratch, b'{"schema": "harness-monitor.v1", "sources": {}}' + b" " * limit)["snapshot"],
        "at_limit_valid_json": answer(api, scratch, b'{"schema": "harness-monitor.v1", "sources": {}}'.ljust(limit, b" "))["snapshot"]}
    path = scratch.path()
    write(path, document(NOW))
    before = sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in scratch.root.iterdir())
    for _ in range(3):
        api.readiness(path, now=NOW)
    after = sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in scratch.root.iterdir())
    out["test_readiness_writes_nothing_and_creates_no_file"] = {"unchanged": before == after, "names_unchanged": [n for n, _s, _m in before] == [n for n, _s, _m in after]}
    out["parse_directly"] = _parse_cases(api)
    out["snapshot_state_directly"] = {"fresh": norm(list(api.snapshot_state(path, NOW)), scratch.root)}
    return out


def _parse_cases(api):
    out = {}
    for label, body in (("object", b'{"a": 1}'), ("list", b"[1, 2]"), ("scalar", b"3"), ("bom", b"\xef\xbb\xbf{}"), ("duplicate", b'{"a": 1, "a": 2}'),
                        ("nested_duplicate", b'{"a": {"b": 1, "b": 2}}'), ("nan", b"NaN"), ("infinity", b"Infinity"), ("empty", b""),
                        ("invalid_utf8", b"\xff"), ("trailing", b"{} x"), ("deep", b"[" * 20000 + b"]" * 20000)):
        try:
            out[label] = ["parsed", api.parse(body)]
        except BaseException as exc:  # noqa: BLE001 - what is raised is the observation
            out[label] = ["raised", type(exc).__name__, str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeDecodeError) else None,
                          isinstance(exc, UnicodeDecodeError), isinstance(exc, ValueError)]
    return out


def s5_now(api, scratch):
    out = {}
    path = scratch.path()
    write(path, document(NOW))
    try:
        api.readiness(path, now=datetime(2026, 9, 19, 12))
        out["naive_now"] = ["returned"]
    except ValueError as exc:
        out["naive_now"] = ["ValueError", str(exc)]
    for label, now in (("string", "2026-09-19T12:00:00+00:00"), ("int", 7)):
        try:
            api.readiness(path, now=now)
            out["not_a_datetime_" + label] = ["returned"]
        except ValueError as exc:
            out["not_a_datetime_" + label] = ["ValueError", str(exc)]
    reply = api.readiness(path, now=NOW.astimezone(timezone(timedelta(hours=9))))
    out["offset_now_ready"] = {"ready": reply["ready"], "checked_at": reply["checked_at"]}
    default = api.readiness(path)
    out["now_default_shape"] = {"keys": sorted(default), "checked_at_aware": datetime.fromisoformat(default["checked_at"]).tzinfo is not None,
                                "snapshot_state": default["snapshot"]["state"], "snapshot_reason": default["snapshot"]["reason"]}
    out["checked_at_is_utc_isoformat"] = api.readiness(path, now=NOW.astimezone(timezone(timedelta(hours=-5))))["checked_at"]
    return out


M7_TESTS = {
    "test_fresh_snapshot_is_ready_over_http_with_the_fixed_contract": "s2_freshness.test_fresh_snapshot_is_ready",
    "test_present_optional_envelopes_are_assessed_and_absent_ones_omitted": "s2_freshness (same name)",
    "test_freshness_and_future_boundaries_are_exact": "s2_freshness (same name, 7 ages)",
    "test_collector_and_source_freshness_are_independent": "s2_freshness (same name)",
    "test_broken_required_envelopes_are_named_without_echoing_them": "s3_envelopes (same name, 10 cases and 5 more)",
    "test_undecodable_snapshots_answer_503_with_no_sources_and_no_crash": "s4_snapshot_files (same name; HTTP status is monitoring_web's)",
    "test_structurally_valid_snapshot_with_broken_collected_at_still_assesses_envelopes": "s4_snapshot_files (same name)",
    "test_missing_and_unreadable_snapshot_paths_are_unavailable": "s4_snapshot_files (same name)",
    "test_oversized_snapshot_is_refused_before_parsing": "s4_snapshot_files (same name)",
    "test_liveness_and_snapshot_api_keep_their_own_contracts": {"unreachable": "HTTP routes of monitoring_web (S9/S10)"},
    "test_payload_content_is_never_read_as_health": "s2_freshness (same name)",
    "test_stale_snapshot_recovers_on_the_same_server_without_restart": {"unreachable": "a running server; readiness itself retains nothing (each call a fresh file in s2_freshness)"},
    "test_readiness_never_reflects_snapshot_values_keys_paths_or_errors": "s3_envelopes (same name)",
    "test_readiness_writes_nothing_and_creates_no_file": "s4_snapshot_files (same name)",
    "test_host_guard_and_read_only_refusal_cover_the_new_route": {"unreachable": "HTTP guard of monitoring_web (S9/S10)"},
    "test_each_request_is_one_complete_view_or_a_refused_open_while_the_file_is_replaced": {"unreachable": "concurrent HTTP replacement; atomic publication is the writer's, not this module's"},
    "test_naive_now_is_a_caller_error_not_a_snapshot_state": "s5_now (same name)",
}


def run(api) -> dict:
    scratch = Scratch()
    try:
        result = {"s1_constants": s1_constants(api), "s2_freshness": s2_freshness(api, scratch), "s3_envelopes": s3_envelopes(api, scratch),
                  "s4_snapshot_files": s4_snapshot_files(api, scratch), "s5_now": s5_now(api, scratch)}
    finally:
        scratch.close()
    result["s6_m7_tests"] = M7_TESTS
    result["temp_path_replacements"] = TEMP_PATH_REPLACEMENTS["count"]
    result["cases_per_group"] = {name: len(result[name]) for name in ("s1_constants", "s2_freshness", "s3_envelopes", "s4_snapshot_files", "s5_now")}
    return result
