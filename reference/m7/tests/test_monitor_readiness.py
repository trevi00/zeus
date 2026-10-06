"""Readiness of the monitor's observation delivery (monitor-readiness-001).

Real temporary snapshot files and a real loopback HTTP server: no mocked file system, no mocked
transport. Injected malformed snapshots are labelled fixtures, not observations of a real
collector failure. Every server thread and connection is closed in `finally`.
"""
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from codex_harness.adapters.monitoring_readiness import (
    FRESH_SECONDS,
    FUTURE_TOLERANCE_SECONDS,
    MAX_SNAPSHOT_BYTES,
    SCHEMA,
    SNAPSHOT_REASONS,
    SOURCE_REASONS,
    readiness,
)
from codex_harness.adapters.monitoring_web import handler

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
ANSWER_KEYS = {'schema', 'service', 'ready', 'basis', 'checked_at', 'freshness_seconds',
               'future_tolerance_seconds', 'snapshot', 'sources'}
REQUIRED = {'database', 'docker', 'redis'}


def envelope(age, now=NOW, status='ok', data=None):
    """One collector envelope shaped like adapters/monitoring.py `sample` output (fixture)."""
    return {'status': status, 'observed_at': (now - timedelta(seconds=age)).isoformat(),
            'data': [] if data is None else data}


def document(now=NOW, collected=1.0, ages=None, sources=None):
    ages = {'database': 1.0, 'docker': 1.0, 'redis': 1.0} if ages is None else ages
    envelopes = {name: envelope(age, now) for name, age in ages.items()}
    envelopes.update(sources or {})
    return {'schema': 'harness-monitor.v1',
            'collected_at': (now - timedelta(seconds=collected)).isoformat(),
            'scope': {'label': 'repository zeus', 'docker': 'compose', 'containers': None},
            'sources': envelopes}


def replace(path, body, attempts=100):
    """Atomic publication, exactly how the collector replaces the snapshot. The bounded retry is a
    Windows accommodation: there a concurrent reader's open handle can briefly refuse the
    replacement with a sharing violation, which is a property of the test's own writer."""
    temporary = path.with_name(path.name + '.tmp')
    if isinstance(body, bytes):
        temporary.write_bytes(body)
    else:
        temporary.write_text(json.dumps(body), 'utf-8')
    for attempt in range(attempts):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.01)


@pytest.fixture
def monitor(tmp_path):
    """One real server over one real snapshot path; sockets and the thread closed in finally."""
    path = tmp_path / 'monitoring.json'
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(path))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, endpoint, headers=None):
        connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request(method, endpoint, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()
    try:
        yield SimpleNamespace(path=path, request=request, directory=tmp_path)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def ready_answer(monitor, expected_status):
    status, body, headers = monitor.request('GET', '/ready')
    answer = json.loads(body)
    assert status == expected_status
    assert set(answer) == ANSWER_KEYS
    assert answer['schema'] == SCHEMA and answer['service'] == 'harness-monitor'
    assert answer['basis'] == 'observation_freshness'
    assert answer['freshness_seconds'] == FRESH_SECONDS == 20
    assert answer['future_tolerance_seconds'] == FUTURE_TOLERANCE_SECONDS == 5
    assert answer['ready'] is (status == 200)
    assert answer['snapshot']['reason'] in SNAPSHOT_REASONS
    assert all(source['reason'] in SOURCE_REASONS for source in answer['sources'].values())
    assert headers['Content-Type'] == 'application/json; charset=utf-8'
    assert headers['Cache-Control'] == 'no-store'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    return answer


def test_fresh_snapshot_is_ready_over_http_with_the_fixed_contract(monitor):
    before = datetime.now(timezone.utc)
    replace(monitor.path, document(before))
    answer = ready_answer(monitor, 200)
    checked = datetime.fromisoformat(answer['checked_at'])
    assert checked.tzinfo is not None and before <= checked <= datetime.now(timezone.utc)
    assert answer['snapshot']['state'] == 'fresh' and answer['snapshot']['reason'] == 'current'
    assert 1.0 <= answer['snapshot']['age_seconds'] < 20
    assert set(answer['sources']) == REQUIRED
    assert all(source['state'] == 'fresh' for source in answer['sources'].values())
    assert all(0 <= source['age_seconds'] < 20 for source in answer['sources'].values())


def test_present_optional_envelopes_are_assessed_and_absent_ones_omitted(monitor):
    now = datetime.now(timezone.utc)
    optional = {'fleet': envelope(1.0, now), 'observations': envelope(1.0, now),
                'research_programs': envelope(1.0, now)}
    replace(monitor.path, document(now, sources=optional))
    answer = ready_answer(monitor, 200)
    assert set(answer['sources']) == REQUIRED | {'fleet', 'observations', 'research_programs'}
    replace(monitor.path, document(now, sources={'fleet': envelope(60.0, now)}))
    answer = ready_answer(monitor, 503)
    assert set(answer['sources']) == REQUIRED | {'fleet'}
    assert answer['sources']['fleet']['state'] == 'stale'
    assert answer['snapshot']['state'] == 'fresh'
    assert all(answer['sources'][name]['state'] == 'fresh' for name in REQUIRED)


@pytest.mark.parametrize('age, expected, clamped', [
    (19.999, ('fresh', 'current'), 19.999),
    # Sub-millisecond ages below the window stay fresh: rounding to milliseconds before the
    # comparison used to report these as stale (regression, monitor-readiness-001 correction).
    (19.9996, ('fresh', 'current'), 19.9996),
    (19.999999, ('fresh', 'current'), 19.999999),
    (20, ('stale', 'older_than_window'), 20.0),
    (20.001, ('stale', 'older_than_window'), 20.001),
    (-FUTURE_TOLERANCE_SECONDS, ('fresh', 'current'), 0.0),
    (-5.001, ('invalid', 'timestamp_in_future'), None),
])
def test_freshness_and_future_boundaries_are_exact(tmp_path, age, expected, clamped):
    path = tmp_path / 'monitoring.json'
    replace(path, document(NOW, collected=age, ages=dict.fromkeys(REQUIRED, age)))
    answer = readiness(path, now=NOW)
    assert (answer['snapshot']['state'], answer['snapshot']['reason']) == expected
    assert answer['snapshot']['age_seconds'] == clamped
    for name in REQUIRED:
        source = answer['sources'][name]
        assert (source['state'], source['reason'], source['age_seconds']) == (*expected, clamped)
    assert answer['ready'] is (expected[0] == 'fresh')


def test_collector_and_source_freshness_are_independent(tmp_path):
    path = tmp_path / 'monitoring.json'
    replace(path, document(NOW, collected=300, ages=dict.fromkeys(REQUIRED, 1.0)))
    answer = readiness(path, now=NOW)
    assert answer['ready'] is False
    assert answer['snapshot'] == {'state': 'stale', 'reason': 'older_than_window',
                                  'age_seconds': 300.0}
    assert all(answer['sources'][name]['state'] == 'fresh' for name in REQUIRED)
    replace(path, document(NOW, collected=1.0, ages={'database': 1.0, 'docker': 45.0,
                                                     'redis': 1.0}))
    answer = readiness(path, now=NOW)
    assert answer['ready'] is False
    assert answer['snapshot']['state'] == 'fresh'
    assert answer['sources']['docker'] == {'state': 'stale', 'reason': 'older_than_window',
                                           'age_seconds': 45.0}
    assert answer['sources']['database']['state'] == answer['sources']['redis']['state'] == 'fresh'


@pytest.mark.parametrize('envelope_value, expected', [
    (None, ('unavailable', 'envelope_missing')),
    ('ok', ('unavailable', 'envelope_invalid')),
    ([], ('unavailable', 'envelope_invalid')),
    ({'status': 'unavailable', 'error': 'RuntimeError', 'observed_at': NOW.isoformat()},
     ('unavailable', 'collection_failed')),
    ({'status': 'ok'}, ('invalid', 'timestamp_missing')),
    ({'status': 'ok', 'observed_at': ''}, ('invalid', 'timestamp_missing')),
    ({'status': 'ok', 'observed_at': 17}, ('invalid', 'timestamp_missing')),
    ({'status': 'ok', 'observed_at': 'yesterday'}, ('invalid', 'timestamp_unparsable')),
    ({'status': 'ok', 'observed_at': '2026-09-19T12:00:00'}, ('invalid', 'timestamp_naive')),
    ({'status': 'ok', 'observed_at': '2026-09-19'}, ('invalid', 'timestamp_naive')),
])
def test_broken_required_envelopes_are_named_without_echoing_them(tmp_path, envelope_value,
                                                                  expected):
    path = tmp_path / 'monitoring.json'
    body = document(NOW, ages={'docker': 1.0, 'redis': 1.0})
    if envelope_value is not None:
        body['sources']['database'] = envelope_value
    replace(path, body)
    answer = readiness(path, now=NOW)
    assert answer['ready'] is False
    assert answer['snapshot']['state'] == 'fresh'
    assert set(answer['sources']) == REQUIRED
    assert answer['sources']['database'] == {'state': expected[0], 'reason': expected[1],
                                             'age_seconds': None}


# Deep nesting may be refused by the parser (undecodable) or, where the parser decodes it, by
# structural validation of the non-object `sources` (sources_unexpected). Both are the same safe
# refusal; the required answer -- 503, ready false, invalid, no sources, no payload disclosure,
# responsive server -- is asserted identically for either. No nesting-depth threshold is asserted.
DEEP_NESTING_REASONS = ('undecodable', 'sources_unexpected')


@pytest.mark.parametrize('payload, expected', [
    (b'', 'undecodable'),
    (b'{"schema": "harness-monitor.v1", "sources": ', 'undecodable'),
    (b'\xef\xbb\xbf{"schema": "harness-monitor.v1", "sources": {}}', 'undecodable'),
    (b'{"schema": "harness-monitor.v1", "sources": {}, "label": "\xff\xfe"}', 'undecodable'),
    (b'{"schema": "harness-monitor.v1", "schema": "other", "sources": {}}', 'undecodable'),
    (b'{"schema": "harness-monitor.v1", "collected_at": NaN, "sources": {}}', 'undecodable'),
    (b'{"schema": "harness-monitor.v1", "collected_at": Infinity, "sources": {}}', 'undecodable'),
    (b'{"schema": "harness-monitor.v1", "sources": ' + b'[' * 20000 + b']' * 20000 + b'}',
     DEEP_NESTING_REASONS),
    (b'[]', 'not_an_object'),
    (b'"harness-monitor.v1"', 'not_an_object'),
    (b'null', 'not_an_object'),
    (b'{"sources": {}}', 'schema_unexpected'),
    (b'{"schema": "harness-monitor.v2", "sources": {}}', 'schema_unexpected'),
    (b'{"schema": ["harness-monitor.v1"], "sources": {}}', 'schema_unexpected'),
    (b'{"schema": "harness-monitor.v1"}', 'sources_unexpected'),
    (b'{"schema": "harness-monitor.v1", "sources": []}', 'sources_unexpected'),
    (b'{"schema": "harness-monitor.v1", "sources": "database"}', 'sources_unexpected'),
], ids=['empty', 'truncated', 'bom', 'invalid-utf8', 'duplicate-key', 'nan', 'infinity',
        'deep-nesting', 'root-array', 'root-string', 'root-null', 'schema-absent', 'schema-other',
        'schema-not-a-string', 'sources-absent', 'sources-array', 'sources-string'])
def test_undecodable_snapshots_answer_503_with_no_sources_and_no_crash(monitor, payload, expected):
    """Injected malformed bytes (fixtures): every one is bounded input, never a handler failure.

    The explicit ids keep the full payloads out of the test id: a generated id for the 20 000-deep
    input pushes PYTEST_CURRENT_TEST past the Windows 32 767-character environment value limit and
    the case errors in setup before this body runs. The inputs themselves are unchanged.

    `expected` is one fixed reason for every case except deep nesting, which accepts either of the
    two documented safe refusals (DEEP_NESTING_REASONS) because the parser's nesting guard is not
    reached identically on every platform; state, age and the empty sources stay exact.
    """
    accepted = (expected,) if isinstance(expected, str) else expected
    replace(monitor.path, payload)
    answer = ready_answer(monitor, 503)
    snapshot = answer['snapshot']
    assert set(snapshot) == {'state', 'reason', 'age_seconds'}
    assert snapshot['state'] == 'invalid' and snapshot['age_seconds'] is None
    assert snapshot['reason'] in accepted
    assert answer['sources'] == {}


def test_structurally_valid_snapshot_with_broken_collected_at_still_assesses_envelopes(tmp_path):
    path = tmp_path / 'monitoring.json'
    body = document(NOW)
    body['collected_at'] = '2026-09-19T12:00:00'  # naive: no timezone context
    replace(path, body)
    answer = readiness(path, now=NOW)
    assert answer['ready'] is False
    assert answer['snapshot'] == {'state': 'invalid', 'reason': 'timestamp_naive',
                                  'age_seconds': None}
    assert all(answer['sources'][name]['state'] == 'fresh' for name in REQUIRED)


def test_missing_and_unreadable_snapshot_paths_are_unavailable(monitor):
    answer = ready_answer(monitor, 503)
    assert answer['snapshot'] == {'state': 'unavailable', 'reason': 'file_missing',
                                  'age_seconds': None}
    assert answer['sources'] == {}
    monitor.path.mkdir()  # a directory is not a readable snapshot stream on any platform
    answer = ready_answer(monitor, 503)
    assert answer['snapshot'] == {'state': 'unavailable', 'reason': 'file_unreadable',
                                  'age_seconds': None}


def test_oversized_snapshot_is_refused_before_parsing(monitor):
    replace(monitor.path, b'x' * (MAX_SNAPSHOT_BYTES + 1))
    answer = ready_answer(monitor, 503)
    assert answer['snapshot']['reason'] == 'too_large'
    replace(monitor.path, b'x' * MAX_SNAPSHOT_BYTES)  # at the limit: read, then refused as input
    assert ready_answer(monitor, 503)['snapshot']['reason'] == 'undecodable'


def test_liveness_and_snapshot_api_keep_their_own_contracts(monitor):
    assert monitor.request('GET', '/health')[:2] == (200, b'{"service":"harness-monitor"}')
    assert monitor.request('GET', '/api/status')[0] == 503
    assert ready_answer(monitor, 503)['snapshot']['reason'] == 'file_missing'
    stale = json.dumps(document(NOW)).encode('utf-8')  # collected in the past, still valid JSON
    replace(monitor.path, stale)
    assert monitor.request('GET', '/health')[:2] == (200, b'{"service":"harness-monitor"}')
    assert monitor.request('GET', '/api/status')[:2] == (200, stale)
    assert ready_answer(monitor, 503)['snapshot']['state'] == 'stale'


def test_payload_content_is_never_read_as_health(monitor):
    """A paused fleet, an exited container or an empty task list is not a freshness fact."""
    now = datetime.now(timezone.utc)
    sources = {'docker': envelope(1.0, now, data=[{'name': 'zeus_pg', 'state': 'exited'}]),
               'database': envelope(1.0, now, data={'operating_status': 'unknown',
                                                    'task_counts': {}, 'measurements': []}),
               'fleet': envelope(1.0, now, data={'registered': False, 'lanes': [], 'jobs': []})}
    replace(monitor.path, document(now, sources=sources))
    answer = ready_answer(monitor, 200)
    assert answer['ready'] is True
    assert set(answer['sources']) == REQUIRED | {'fleet'}


def test_stale_snapshot_recovers_on_the_same_server_without_restart(monitor):
    replace(monitor.path, document(datetime.now(timezone.utc), collected=300,
                                   ages=dict.fromkeys(REQUIRED, 300.0)))
    assert ready_answer(monitor, 503)['snapshot']['state'] == 'stale'
    replace(monitor.path, document(datetime.now(timezone.utc)))
    assert ready_answer(monitor, 200)['ready'] is True
    replace(monitor.path, document(datetime.now(timezone.utc), collected=300,
                                   ages=dict.fromkeys(REQUIRED, 300.0)))
    assert ready_answer(monitor, 503)['ready'] is False  # nothing cached in either direction


def test_readiness_never_reflects_snapshot_values_keys_paths_or_errors(monitor):
    secret = 'postgresql://admin:s3cr3t@localhost/db'
    body = document(NOW, ages={'docker': 1.0, 'redis': 1.0})
    body['scope']['label'] = secret
    body['sources']['database'] = {'status': 'unavailable', 'error': secret, 'data': None,
                                   'observed_at': '<script>alert(1)</script>'}
    body['sources']['../../etc/passwd'] = envelope(1.0)
    body['sources']['ready'] = {'status': 'ok', 'observed_at': NOW.isoformat()}
    replace(monitor.path, body)
    status, raw, _ = monitor.request('GET', '/ready')
    answer = json.loads(raw)
    assert status == 503 and answer['ready'] is False
    assert set(answer['sources']) == REQUIRED
    assert answer['sources']['database'] == {'state': 'unavailable', 'reason': 'collection_failed',
                                             'age_seconds': None}
    text = raw.decode('utf-8')
    for leak in ('s3cr3t', 'postgresql', 'script', 'passwd', 'RuntimeError',
                 str(monitor.path), monitor.path.name, NOW.isoformat()):
        assert leak not in text, leak


def test_readiness_writes_nothing_and_creates_no_file(monitor):
    replace(monitor.path, document(datetime.now(timezone.utc)))
    before = sorted((entry.name, entry.stat().st_size, entry.stat().st_mtime_ns)
                    for entry in monitor.directory.iterdir())
    for _ in range(3):
        ready_answer(monitor, 200)
    monitor.path.unlink()
    ready_answer(monitor, 503)
    after = sorted((entry.name, entry.stat().st_size, entry.stat().st_mtime_ns)
                   for entry in monitor.directory.iterdir())
    assert before[1:] == after  # only the snapshot removed by this test itself
    assert [name for name, _size, _mtime in before] == ['monitoring.json']


def test_host_guard_and_read_only_refusal_cover_the_new_route(monitor):
    replace(monitor.path, document(datetime.now(timezone.utc)))
    assert monitor.request('GET', '/ready', {'Host': 'untrusted.example'})[:2] == (403,
                                                                                  b'Forbidden host')
    assert monitor.request('POST', '/ready')[:2] == (405, b'Read only')
    assert monitor.request('GET', '/ready/')[0] == 404
    assert monitor.request('GET', '/ready?x=1')[0] == 200  # query strings are ignored for routing


def concurrent_view(status, answer):
    """The complete answers a reader may lawfully get while the snapshot is being republished.

    Publication integrity and the availability of an open handle are two different facts. A read
    that succeeds must expose one whole published document: each fixture here writes `collected_at`
    and all three required envelopes at the same instant, so a consistent view carries one state,
    one reason and one identical age across the snapshot and every source, so a mixed, partial or
    `invalid` answer cannot pass. A read whose open is refused (Windows can deny an open that
    overlaps `os.replace`) is the only other lawful answer: 503, `unavailable` with
    `file_missing`/`file_unreadable`, null age and no sources, never a 200. Returns the view name;
    every assertion carries the whole answer as its diagnostic.
    """
    snapshot, sources = answer['snapshot'], answer['sources']
    assert answer['ready'] is (status == 200), answer
    if snapshot['state'] == 'unavailable':
        assert status == 503 and answer['ready'] is False, answer
        assert snapshot['reason'] in ('file_missing', 'file_unreadable'), answer
        assert snapshot['age_seconds'] is None, answer
        assert sources == {}, answer
        return 'unavailable'
    assert snapshot['state'] in ('fresh', 'stale'), answer
    reason = 'current' if snapshot['state'] == 'fresh' else 'older_than_window'
    assert snapshot['reason'] == reason, answer
    assert status == (200 if snapshot['state'] == 'fresh' else 503), answer
    assert isinstance(snapshot['age_seconds'], (int, float)), answer
    assert (snapshot['age_seconds'] < FRESH_SECONDS) is (snapshot['state'] == 'fresh'), answer
    assert set(sources) == REQUIRED, answer                 # the whole published source set
    for source in sources.values():
        assert (source['state'], source['reason']) == (snapshot['state'], reason), answer
        assert source['age_seconds'] == snapshot['age_seconds'], answer
    return snapshot['state']


def test_each_request_is_one_complete_view_or_a_refused_open_while_the_file_is_replaced(monitor):
    """Atomic replacement never exposes a partial file, but an overlapping open can be refused.

    Every response is kept whole and checked by `concurrent_view`; there is no HTTP retry and no
    skip, so a refused open is recorded as a legitimate unavailable answer rather than retried
    away. Only the writer retries, for its own sharing violation. After the writers and readers
    finish, one fresh publication must restore a ready 200 on the same running server.
    """
    replace(monitor.path, document(datetime.now(timezone.utc)))
    results, failures = [], []

    def poll():
        for _ in range(10):
            try:
                status, raw, _ = monitor.request('GET', '/ready')
                results.append((status, json.loads(raw)))
            except Exception as exc:                        # pragma: no cover - reported below
                failures.append(repr(exc))

    threads = [Thread(target=poll) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        for _ in range(10):
            replace(monitor.path, document(datetime.now(timezone.utc)))
            replace(monitor.path, document(datetime.now(timezone.utc), collected=300,
                                           ages=dict.fromkeys(REQUIRED, 300.0)))
    finally:
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert not failures, failures                           # no request or JSON failure is allowed
    assert len(results) == 40
    views = Counter(concurrent_view(status, answer) for status, answer in results)
    assert views.total() == 40, views                       # counts reported when anything fails

    replace(monitor.path, document(datetime.now(timezone.utc)))
    recovered = ready_answer(monitor, 200)
    assert recovered['snapshot']['state'] == 'fresh', recovered
    assert {source['state'] for source in recovered['sources'].values()} == {'fresh'}, recovered


def test_naive_now_is_a_caller_error_not_a_snapshot_state(tmp_path):
    path = tmp_path / 'monitoring.json'
    replace(path, document(NOW))
    with pytest.raises(ValueError):
        readiness(path, now=datetime(2026, 9, 19, 12))
    assert readiness(path, now=NOW.astimezone(timezone(timedelta(hours=9))))['ready'] is True
