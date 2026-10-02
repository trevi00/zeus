"""S8 pilot 89 (DESIGN-s8 §12.1 V17 P-a): the M7 monitor readiness assessment moved AHEAD into observation, VERBATIM; only the §3.2
header is new (A/evidence/rebuild/s8/monitoring-readiness-move/transcribe.py).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`observation.monitoring_readiness` golden.
"""
import ast
import importlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
MODULE = "codex_harness.observation.adapters.monitoring_readiness"
M7_PATH = "src/codex_harness/adapters/monitoring_readiness.py"
NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
FUNCTIONS = ["state", "parse", "elapsed", "envelope_state", "source_states", "snapshot_state", "readiness"]


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def module():
    return importlib.import_module(MODULE)


def target_text():
    return Path(module().__file__).read_text()


def defined(node):
    if isinstance(node, ast.FunctionDef):
        return (node.name,)
    return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        out[defined(node)] = node
    return out


def imports(src):
    return [ast.dump(n) for n in ast.parse(src).body if isinstance(n, (ast.Import, ast.ImportFrom))]


def test_every_statement_is_m7_s_by_ast_in_m7_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) and len(ref) == 18
    assert [k[0] for k in ref if k[0] in FUNCTIONS] == FUNCTIONS
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_the_only_change_is_the_header_and_the_body_is_byte_identical():
    assert imports(m7_text()) == imports(target_text())
    marker = "\nimport json\n"
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: adapters", "Context: observation", "Entry points: " + ", ".join(FUNCTIONS), "Contracts: INV-MONITOR-VIEWER-001"):
        assert line in doc.splitlines()


def test_imports_are_stdlib_only_and_the_only_io_is_the_one_bounded_snapshot_read():
    tree = ast.parse(target_text())
    assert sorted(n.module if isinstance(n, ast.ImportFrom) else n.names[0].name for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))) == ["datetime", "json"]
    assert "codex_harness" not in target_text().split('"""', 2)[2]
    body = target_text().split('"""', 2)[2]
    assert body.count("open(") == 1 and "'rb'" in body
    for word in (".write", "subprocess", "socket", "psycopg", "os.", "Path"):
        assert word not in body, word


def write(path, body):
    path.write_bytes(body) if isinstance(body, bytes) else path.write_text(json.dumps(body), "utf-8")


def envelope(age, status="ok"):
    return {"status": status, "observed_at": (NOW - timedelta(seconds=age)).isoformat(), "data": []}


def snapshot(collected=1.0, ages=None, **extra):
    ages = {"database": 1.0, "docker": 1.0, "redis": 1.0} if ages is None else ages
    sources = {name: envelope(age) for name, age in ages.items()}
    sources.update(extra)
    return {"schema": "harness-monitor.v1", "collected_at": (NOW - timedelta(seconds=collected)).isoformat(), "sources": sources}


def test_the_constants_and_the_closed_reason_sets():
    m = module()
    assert (m.SCHEMA, m.SERVICE, m.BASIS, m.SNAPSHOT_SCHEMA) == ("urn:zeus:monitor-readiness:1", "harness-monitor", "observation_freshness", "harness-monitor.v1")
    assert (m.MAX_SNAPSHOT_BYTES, m.FRESH_SECONDS, m.FUTURE_TOLERANCE_SECONDS) == (5_000_000, 20, 5)
    assert m.REQUIRED_SOURCES == ("database", "docker", "redis") and m.OPTIONAL_SOURCES == ("observations", "fleet", "research_programs")
    assert len(m.SNAPSHOT_REASONS) == 13 and len(m.SOURCE_REASONS) == 9


@pytest.mark.parametrize("age, expected, clamped", [
    (19.999, ("fresh", "current"), 19.999), (19.9996, ("fresh", "current"), 19.9996), (20, ("stale", "older_than_window"), 20.0),
    (-5, ("fresh", "current"), 0.0), (-5.001, ("invalid", "timestamp_in_future"), None)])
def test_freshness_and_future_boundaries_are_exact(tmp_path, age, expected, clamped):
    path = tmp_path / "s.json"
    write(path, snapshot(collected=age, ages=dict.fromkeys(("database", "docker", "redis"), age)))
    answer = module().readiness(path, now=NOW)
    assert (answer["snapshot"]["state"], answer["snapshot"]["reason"], answer["snapshot"]["age_seconds"]) == (*expected, clamped)
    assert answer["ready"] is (expected[0] == "fresh") and answer["checked_at"] == "2026-09-19T12:00:00+00:00"
    assert set(answer["sources"]) == {"database", "docker", "redis"}


def test_a_30_second_old_snapshot_is_stale_older_than_window(tmp_path):
    path = tmp_path / "s.json"
    write(path, snapshot(collected=30))
    assert module().readiness(path, now=NOW)["snapshot"] == {"state": "stale", "reason": "older_than_window", "age_seconds": 30.0}


@pytest.mark.parametrize("payload, reason", [
    (b"", "undecodable"), (b"\xef\xbb\xbf{}", "undecodable"), (b'{"a": 1, "a": 2}', "undecodable"), (b'{"collected_at": NaN}', "undecodable"),
    (b"[]", "not_an_object"), (b"{}", "schema_unexpected"), (b'{"schema": "harness-monitor.v1"}', "sources_unexpected")])
def test_malformed_snapshots_are_fixed_states_with_no_sources(tmp_path, payload, reason):
    path = tmp_path / "s.json"
    write(path, payload)
    answer = module().readiness(path, now=NOW)
    assert answer["snapshot"] == {"state": "invalid", "reason": reason, "age_seconds": None}
    assert answer["sources"] == {} and answer["ready"] is False


def test_missing_and_unreadable_paths_are_unavailable_and_an_oversized_file_is_refused_never_raised(tmp_path):
    m = module()
    assert m.readiness(tmp_path / "none.json", now=NOW)["snapshot"] == {"state": "unavailable", "reason": "file_missing", "age_seconds": None}
    assert m.readiness(tmp_path, now=NOW)["snapshot"] == {"state": "unavailable", "reason": "file_unreadable", "age_seconds": None}
    big = tmp_path / "big.json"
    write(big, b"x" * (m.MAX_SNAPSHOT_BYTES + 1))
    assert m.readiness(big, now=NOW)["snapshot"] == {"state": "invalid", "reason": "too_large", "age_seconds": None}
    write(big, b"x" * m.MAX_SNAPSHOT_BYTES)
    assert m.readiness(big, now=NOW)["snapshot"]["reason"] == "undecodable"


@pytest.mark.parametrize("value, expected", [
    (None, ("unavailable", "envelope_missing")), ("ok", ("unavailable", "envelope_invalid")), ([], ("unavailable", "envelope_invalid")),
    ({"status": "unavailable", "observed_at": "2026-09-19T12:00:00+00:00"}, ("unavailable", "collection_failed")),
    ({"status": "ok"}, ("invalid", "timestamp_missing")), ({"status": "ok", "observed_at": "yesterday"}, ("invalid", "timestamp_unparsable")),
    ({"status": "ok", "observed_at": "2026-09-19T12:00:00"}, ("invalid", "timestamp_naive"))])
def test_a_broken_required_envelope_is_named_without_echoing_it(tmp_path, value, expected):
    path = tmp_path / "s.json"
    body = snapshot(ages={"docker": 1.0, "redis": 1.0})
    if value is not None:
        body["sources"]["database"] = value
    write(path, body)
    answer = module().readiness(path, now=NOW)
    assert answer["sources"]["database"] == {"state": expected[0], "reason": expected[1], "age_seconds": None} and answer["ready"] is False


def test_optional_envelopes_only_when_present_and_unknown_names_never_reach_the_answer(tmp_path):
    path = tmp_path / "s.json"
    write(path, snapshot(fleet=envelope(60.0), observations=envelope(1.0), extra=envelope(1.0), **{"../../etc/passwd": envelope(1.0)}))
    answer = module().readiness(path, now=NOW)
    assert list(answer["sources"]) == ["database", "docker", "redis", "observations", "fleet"]
    assert answer["sources"]["fleet"]["reason"] == "older_than_window" and answer["ready"] is False
    assert "passwd" not in json.dumps(answer) and str(path) not in json.dumps(answer)


def test_a_naive_now_is_a_caller_error_and_an_offset_now_is_reported_in_utc(tmp_path):
    path = tmp_path / "s.json"
    write(path, snapshot())
    m = module()
    with pytest.raises(ValueError, match="requires a timezone-aware datetime"):
        m.readiness(path, now=datetime(2026, 9, 19, 12))
    answer = m.readiness(path, now=NOW.astimezone(timezone(timedelta(hours=9))))
    assert answer["ready"] is True and answer["checked_at"] == "2026-09-19T12:00:00+00:00"


def test_readiness_writes_nothing(tmp_path):
    path = tmp_path / "s.json"
    write(path, snapshot())
    before = sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in tmp_path.iterdir())
    module().readiness(path, now=NOW)
    module().readiness(tmp_path / "none.json", now=NOW)
    assert sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in tmp_path.iterdir()) == before


def test_the_target_driver_uses_this_module():
    driver = (REPO / "compare" / "drivers" / "target" / "s8_monitoring_readiness.py").read_text()
    assert "from codex_harness.observation.adapters import monitoring_readiness as API" in driver
