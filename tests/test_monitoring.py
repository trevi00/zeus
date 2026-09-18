import json
import sys
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.monitoring import (
    container_scope,
    docker_facts,
    persisted_measurements,
    read_only,
    safe_text,
)
from codex_harness.adapters.monitoring_web import handler
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.monitoring import Monitoring, initiatives
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def observation(metric_id, observed_at, value=1):
    """Synthetic persisted row shaped like Measurements.collect output (fixture, not a real run)."""
    return {'id': f'{metric_id}-{observed_at}', 'metric_id': metric_id, 'value': value, 'status': 'pass',
            'reason': 'fixture', 'observed_at': observed_at, 'window_start': observed_at, 'window_end': observed_at,
            'evidence_refs': ['sha256:' + 'a' * 64], 'definition': {'metric_id': metric_id}}


def stubbed_sources(monkeypatch):
    from codex_harness.adapters import monitoring
    monkeypatch.setattr(monitoring, 'docker_facts', lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, 'redis_facts', lambda url, agents: [])


def test_read_only_store_and_reader_refuse_writes_while_collection_works(monkeypatch, tmp_path):
    from codex_harness.adapters import monitoring
    stubbed_sources(monkeypatch)
    store = MemoryStore()
    old = (NOW - timedelta(days=1)).isoformat()
    with store.transaction() as tx:
        tx.put('tasks', 'one', {'id': 'one', 'agent': 'worker:implementation', 'status': 'queued'})
        tx.put('metric_observations', 'm1', observation('first_attempt_success', old))
    artifacts_root = tmp_path / 'artifacts'
    service, artifacts = read_only(SimpleNamespace(store=store, org=organization()), FileArtifacts(str(artifacts_root)))
    with pytest.raises(ContractError):
        with service.store.transaction() as tx:
            tx.put('metric_observations', 'x', {'id': 'x'})
    with pytest.raises(ContractError):
        with service.store.transaction() as tx:
            tx.graph()
    with pytest.raises(ContractError):
        artifacts.put('body', 'monitor')
    before = store.data.copy()
    for _ in range(2):
        result = monitoring.collect(service, artifacts, str(tmp_path), 'redis://127.0.0.1/0')
    database = result['sources']['database']
    assert database['status'] == 'ok'
    assert database['data']['task_counts'] == {'queued': 1}
    measurements = database['data']['measurements']
    assert [m['metric_id'] for m in measurements] == ['first_attempt_success']
    assert measurements[0]['observed_at'] == old and measurements[0]['source'] == 'persisted_observation'
    assert measurements[0]['age_seconds'] > 20
    assert store.data == before
    assert list(artifacts_root.iterdir()) == []


def test_persisted_measurements_are_latest_per_metric_and_honest_when_empty():
    store = MemoryStore()
    assert persisted_measurements(store, NOW) == []
    with store.transaction() as tx:
        tx.put('metric_observations', 'a', observation('m', (NOW - timedelta(hours=2)).isoformat(), 1))
        tx.put('metric_observations', 'b', observation('m', (NOW - timedelta(hours=1)).isoformat(), 2))
        tx.put('metric_observations', 'c', observation('m', '2026-09-18T11:59:00', 3))  # naive: ignored
        tx.put('metric_observations', 'd', observation('m', 'not-a-time', 4))
        tx.put('metric_observations', 'e', observation('', NOW.isoformat(), 5))
        tx.put('metric_observations', 'f', observation('n', (NOW - timedelta(seconds=30)).isoformat(), 6))
    rows = persisted_measurements(store, NOW)
    assert [(r['metric_id'], r['value'], r['age_seconds']) for r in rows] == [('m', 2, 3600.0), ('n', 6, 30.0)]
    assert rows[0]['observed_at'] == (NOW - timedelta(hours=1)).isoformat()
    assert rows[0]['definition'] == {'metric_id': 'm'} and rows[0]['evidence_refs'] == ['sha256:' + 'a' * 64]


@pytest.mark.parametrize('value', ['[', '{}', '[]', '["a", "a"]', '["-x"]', '[1]', '["a b"]',
                                   json.dumps(['c%d' % i for i in range(33)]), '["' + 'a' * 129 + '"]'])
def test_container_scope_rejects_invalid_configuration(value):
    with pytest.raises(ValueError):
        container_scope(value)


def test_container_scope_unset_keeps_compose_and_named_mode_is_exact(monkeypatch):
    from codex_harness.adapters import monitoring
    assert container_scope(None) is None and container_scope('  ') is None
    assert container_scope('["zeus-local-ops-redis", "zeus_pg.1"]') == ['zeus-local-ops-redis', 'zeus_pg.1']
    commands = []
    listing = {'zeus-local-ops-redis': 'running', 'zeus-local-ops-redis-2': 'running', 'flexday': 'running',
               'zeus_pg.1': 'exited'}

    def fake_run(argv, cwd=None, timeout=None, **kwargs):
        commands.append(argv)
        if argv[:2] == ['docker', 'compose']:
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                {'Service': 'redis', 'Name': 'zeus-redis-1', 'State': 'running', 'Image': 'redis'}))
        if argv[:2] == ['docker', 'ps']:
            # Simulated substring matching of the CLI name filter (fixture, not a Docker run).
            wanted = [arg[5:] for arg in argv if arg.startswith('name=')]
            rows = [{'Names': n, 'State': s, 'Image': 'img'} for n, s in listing.items() if any(w in n for w in wanted)]
            return SimpleNamespace(returncode=0, stdout='\n'.join(json.dumps(r) for r in rows))
        assert argv[:2] == ['docker', 'stats']
        return SimpleNamespace(returncode=0, stdout='\n'.join(
            json.dumps({'Name': n, 'CPUPerc': '1%', 'MemUsage': '1MiB / 2MiB'}) for n in argv[5:]))
    monkeypatch.setattr(monitoring, 'run_process', fake_run)
    rows = docker_facts('.', ['zeus-local-ops-redis', 'zeus_pg.1'])
    assert [(r['name'], r['state'], r['cpu']) for r in rows] == [('zeus-local-ops-redis', 'running', '1%'),
                                                                 ('zeus_pg.1', 'exited', None)]
    assert commands[-1] == ['docker', 'stats', '--no-stream', '--format', '{{json .}}', 'zeus-local-ops-redis']
    with pytest.raises(RuntimeError, match='missing'):
        docker_facts('.', ['zeus-local-ops-redis', 'absent'])
    assert docker_facts('.')[0] == {'service': 'redis', 'name': 'zeus-redis-1', 'state': 'running',
                                    'image': 'redis', 'cpu': '1%', 'memory': '1MiB / 2MiB'}
    assert commands[-2][:3] == ['docker', 'compose', 'ps']
    assert {argv[1] for argv in commands} <= {'compose', 'ps', 'stats'}
    assert all(argv[:2] != ['docker', 'inspect'] for argv in commands)


def test_collector_entrypoint_is_read_only_and_needs_no_executor(monkeypatch, tmp_path):
    from codex_harness import bootstrap, monitor
    stubbed_sources(monkeypatch)
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('metric_observations', 'm1', observation('m', (NOW - timedelta(days=1)).isoformat()))
    monkeypatch.setattr(bootstrap, 'build', lambda: SimpleNamespace(store=store, org=organization()))
    monkeypatch.setattr(bootstrap, 'build_executor',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('monitor must not build the executor')))
    monkeypatch.setattr(bootstrap, 'redis_url', lambda: 'redis://127.0.0.1:1/0')
    monkeypatch.setenv('HARNESS_RUNTIME_DIR', 'runtime')
    monkeypatch.setenv('ZEUS_MONITOR_CONTAINERS', '')
    monkeypatch.setenv('ZEUS_MONITOR_SCOPE', 'Zeus 고정 운영 원장 · 과거 격리 실행 제외 password=secret')
    for name in ('CODEX_HOME', 'HARNESS_CODEX_AUTH', 'ZEUS_CODEX_AUTH'):
        monkeypatch.delenv(name, raising=False)
    # The real CLI calls select_repository, which writes both repository aliases into os.environ.
    # Register both with monkeypatch first so teardown restores the original process environment
    # instead of leaking tmp_path into later tests (e.g. tests/test_supervisor.py).
    for name in ('ZEUS_REPOSITORY', 'HARNESS_REPOSITORY'):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    before = store.data.copy()
    for _ in range(2):
        monkeypatch.setattr(sys, 'argv', ['zeus-monitor', 'collect', '--once', '--repository', str(tmp_path)])
        monitor.main()
    runtime = tmp_path / 'runtime'
    snapshot = json.loads((runtime / 'monitoring.json').read_text('utf-8'))
    assert snapshot['scope']['docker'] == 'compose'
    assert snapshot['scope']['label'] == 'Zeus 고정 운영 원장 · 과거 격리 실행 제외 password=[redacted]'
    assert snapshot['sources']['database']['data']['measurements'][0]['age_seconds'] > 20
    assert store.data == before
    assert list((runtime / 'artifacts').iterdir()) == []
    lines = [json.loads(line) for line in (runtime / 'monitor-collector.log').read_text('utf-8').splitlines()]
    # Five sources: observatory-001 added observations (the CLI passes the runtime) and fleet-001
    # added the additive fleet envelope (INV-FLEET-001).
    assert [line['event'] for line in lines] == (['startup'] + ['source_state'] * 5 + ['shutdown']) * 2
    assert snapshot['sources']['observations']['status'] == 'ok'
    # Unregistered fleet: an ok envelope with the fixed empty shape; the read-only store is unchanged
    # (asserted above) and no executor was built.
    assert snapshot['sources']['fleet']['status'] == 'ok'
    assert snapshot['sources']['fleet']['data'] == {'schema': 'urn:zeus:fleet-status:1', 'registered': False,
                                                    'lanes': [], 'jobs': []}
    assert snapshot['sources']['observations']['data']['local'] == {'status': 'unavailable',
                                                                    'reason': 'directory_missing'}
    assert lines[0] == {'at': lines[0]['at'], 'event': 'startup', 'mode': 'collect', 'once': True,
                        'scope': 'compose', 'containers': None}
    text = (runtime / 'monitor-collector.log').read_text('utf-8')
    assert 'secret' not in text and 'redis://' not in text and '고정' not in text
    monkeypatch.setenv('ZEUS_MONITOR_CONTAINERS', '["a", "a"]')
    with pytest.raises(ValueError):
        monitor.main()
    last = json.loads((runtime / 'monitor-collector.log').read_text('utf-8').splitlines()[-1])
    assert last == {'at': last['at'], 'event': 'startup_refused', 'reason': 'config_invalid', 'error': 'ValueError'}


def test_audit_progress_keeps_missing_checkpoints_unknown_and_pause_visible():
    from codex_harness.adapters.monitoring import audit_progress
    data = {'reference_audits': [{'id': 'legacy', 'repository': 'repo', 'revision': 'rev',
                                'files': 2, 'status': 'inventoried_not_reviewed'}],
            'research_audits': [{'id': 'audit', 'source': {'repository': 'repo', 'commit': 'rev',
                'manifest_ref': 'manifest'}, 'inventory': ['a', 'b'], 'status': 'source_verified_not_reviewed'}]}
    row = audit_progress(data, {})[0]
    assert row['remaining_paths'] is None
    assert row['dispatch_status'] == 'inactive'
    data['research_partitions'] = [{'audit_id': 'audit', 'remaining_paths': ['a'],
        'remaining_subsystems': ['storage'], 'open_questions': ['test not run']}]
    row = audit_progress(data, {'status': 'paused'})[0]
    assert row['remaining_paths'] == row['remaining_subsystems'] == row['open_questions'] == 1
    assert row['dispatch_status'] == 'paused'
    assert row['independent_review'] == 'not_certified_by_monitor'
    assert len(audit_progress(data, {})) == 1


def test_completed_implementation_does_not_hide_blocked_review():
    now = datetime.now(timezone.utc)
    facts = {'tasks': [{'id': 'impl', 'correlation': 'goal', 'phase': 'implement',
                       'status': 'succeeded', 'created_at': now.isoformat(), 'objective': 'Improve'}],
             'decisions': [{'id': 'review', 'correlation': 'goal', 'phase': 'review_lead',
                           'status': 'blocked', 'reason': 'Cannot inspect candidate',
                           'created_at': now.isoformat()}], 'releases': []}
    result = initiatives(facts, now)[0]
    assert result['status'] == 'attention'
    assert result['reason'] == 'Cannot inspect candidate'
    assert result['stages'][-1]['status'] == 'waiting'
    facts['decisions'] = []
    assert initiatives(facts, now)[0]['status'] == 'awaiting_next_stage'


def test_failed_canary_and_expired_lease_are_attention_states():
    now = datetime.now(timezone.utc)
    facts = {'tasks': [{'id': 'impl', 'correlation': 'goal', 'phase': 'implement',
                       'status': 'running', 'revision': 'abc',
                       'lease_until': (now - timedelta(seconds=1)).isoformat()}],
             'decisions': [], 'releases': [{'id': 'release', 'revision': 'abc', 'status': 'rejected',
                                          'checks': {'cli': {'passed': False}}}]}
    result = initiatives(facts, now)[0]
    assert result['status'] == 'attention'
    assert result['stages'][1]['status'] == 'lease_expired'
    assert result['stages'][-2]['status'] == 'failed'


def test_expired_execution_and_stale_health_are_not_live():
    now = datetime.now(timezone.utc)
    facts = {'health': {'status': 'healthy', 'checked_at': (now - timedelta(minutes=3)).isoformat()},
             'agents': [{'id': 'worker'}], 'decisions': [],
             'tasks': [{'id': 'old', 'agent': 'worker', 'status': 'running',
                        'lease_until': (now - timedelta(seconds=1)).isoformat()},
                       {'id': 'new', 'agent': 'worker', 'status': 'queued'}]}
    result = Monitoring(SimpleNamespace(read=lambda: facts)).snapshot(now)
    assert result['operating_status'] == 'unknown'
    assert result['agents'][0]['work'] == []
    assert result['agents'][0]['expired_leases'] == 1
    assert result['agents'][0]['queued'] == 1
    assert result['task_counts']['running'] == 1


class BrokenStore:
    """Injected fault (test fixture): every transaction fails like an unreachable database."""

    def transaction(self):
        raise RuntimeError('injected database outage')


def test_collect_keeps_source_failures_independent(monkeypatch):
    """Envelope contract read by monitor.html: one failed source never hides the others."""
    from codex_harness.adapters import monitoring
    monkeypatch.setattr(monitoring, 'run_process',
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('no process in this test')))
    monkeypatch.setattr(monitoring, 'docker_facts',
                        lambda repository, containers=None: [{'service': 'redis', 'state': 'running'}])
    monkeypatch.setattr(monitoring, 'redis_facts', lambda url, agents: [{'agent': 'conductor', 'entries': 1}])
    service = SimpleNamespace(store=BrokenStore(), org=SimpleNamespace(agents={'conductor': object()}))
    before = datetime.now(timezone.utc)
    result = monitoring.collect(service, None, '.', 'redis://127.0.0.1/0')
    sources = result['sources']
    assert result['schema'] == 'harness-monitor.v1'
    assert result['scope'] == {'label': 'repository ' + Path('.').resolve().name, 'docker': 'compose', 'containers': None}
    assert set(sources) == {'database', 'docker', 'redis', 'fleet'}
    assert sources['database']['status'] == 'unavailable'
    assert sources['database']['data'] is None
    assert sources['database']['error'] == 'RuntimeError'
    # The additive fleet source (INV-FLEET-001) reads the same store: unavailable, never a guess.
    assert sources['fleet']['status'] == 'unavailable'
    assert sources['fleet']['data'] is None and sources['fleet']['error'] == 'RuntimeError'
    assert sources['docker'] == {'status': 'ok', 'observed_at': sources['docker']['observed_at'],
                                 'data': [{'service': 'redis', 'state': 'running'}]}
    assert sources['redis']['status'] == 'ok' and sources['redis']['data'][0]['agent'] == 'conductor'
    for name in ('database', 'docker', 'redis', 'fleet'):
        observed = datetime.fromisoformat(sources[name]['observed_at'])
        assert observed.tzinfo is not None
        assert before <= observed <= datetime.fromisoformat(result['collected_at'])


def test_index_falls_back_to_legacy_without_build_and_assets_are_strict(monkeypatch, tmp_path):
    from codex_harness.adapters import monitoring_web
    legacy = monitoring_web.resource('monitor.html').read_bytes()
    assets = tmp_path / 'observatory' / 'assets'
    assets.mkdir(parents=True)
    (assets / 'index-abc.js').write_bytes(b'console.log(1)')
    (assets / 'index-abc.css').write_bytes(b'body{}')
    (assets / 'big.js').write_bytes(b'x' * (monitoring_web.MAX_ASSET_BYTES + 1))
    (assets / 'secret.json').write_bytes(b'{}')
    monkeypatch.setattr(monitoring_web, 'resource', lambda *parts: tmp_path.joinpath(*parts))
    (tmp_path / 'monitor.html').write_bytes(legacy)
    assert monitoring_web.index_page() == legacy  # no build output: the legacy page, not a placeholder
    (tmp_path / 'observatory' / 'index.html').write_bytes(b'<!doctype html><div id="root"></div>')
    assert monitoring_web.index_page().startswith(b'<!doctype html>')
    assert monitoring_web.asset('index-abc.js') == (b'console.log(1)', 'text/javascript; charset=utf-8')
    assert monitoring_web.asset('index-abc.css') == (b'body{}', 'text/css; charset=utf-8')
    for name in ('big.js', 'secret.json', '../legacy/monitor.html', '..', 'index-abc.js/', '.hidden.js', 'x' * 130 + '.js'):
        assert monitoring_web.asset(name) is None, name


def test_credential_redaction():
    text = safe_text('postgresql://admin:secret@localhost/db Bearer abc token=def password=xyz')
    assert all(secret not in text for secret in ['secret', 'abc', 'def', 'xyz'])


def test_http_rejects_mutations_hosts_and_unavailable_snapshot(tmp_path):
    path = tmp_path / 'status.json'
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(path))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(method, endpoint, headers=None):
        connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            connection.request(method, endpoint, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()
    try:
        assert request('GET', '/api/status')[0] == 503
        path.write_text(json.dumps({'sources': {}}))
        assert request('GET', '/api/status') == (200, b'{"sources": {}}')
        path.write_text('{"sources": ')
        assert request('GET', '/api/status') == (503, b'{"error":"snapshot_unavailable"}')
        path.write_text(json.dumps({'sources': {}}))
        assert request('GET', '/api/status')[0] == 200
        assert request('GET', '/api/status', {'Host': 'untrusted.example'})[0] == 403
        assert request('POST', '/api/status')[0] == 405
        assert request('GET', '/.env')[0] == 404
        assert request('GET', '/')[0] == 200
        legacy = request('GET', '/legacy')
        assert legacy[0] == 200 and b'<script>' in legacy[1]
        assert request('GET', '/legacy', {'Host': 'untrusted.example'})[0] == 403
        for endpoint in ('/assets/', '/assets/../monitor.html', '/assets/..%2fmonitor.html', '/assets/x/y.js',
                         '/assets/monitor.html', '/assets/index.json', '/assets/.hidden.js', '/assets/missing.js',
                         '/assets/index.js?x=1', '/legacy/'):
            assert request('GET', endpoint)[0] == 404, endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
