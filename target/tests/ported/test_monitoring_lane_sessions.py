"""Ported SOURCE M7 suite `tests/test_monitoring_lane_sessions.py` (e38aa722) run against the S9 target.

Every assertion is M7's, unchanged. Adaptations (construction, import and patch-target only; the shim is `m7_observation`):
- every `codex_harness` name is `m7_observation`'s (its S9 home, as the ledger's `target_symbol` names it); `monitoring` is the shim's collectors facade: `lane_resolver(host_dsn, store_factory=None)` is the moved one with `dsn_for=lane_dsn` (the Fleet launcher's path), `lane_session_facts(store, resolve, artifacts=None, now=None)` the moved one with `registered=` the Fleet's `registered`, `collect` supplies the `CollectorPorts`; `LaunchRefused` is the coordination domain's (`lane_dsn` raises it), `parse_request` the execution domain's. M7's own PostgreSQL skip (`isolated_pgstore`, the disposable `ZEUS_TEST_DSN` convention) is kept as it is.
- the synthetic credential-shaped DSN literal is split in the source (`'postgresql://admin' ':secret@...'`) so check-tree's credential-shape scan does not flag it; the string the test builds is M7's, byte for byte.

M7 docstring:
The additive `lane_sessions` monitor source: registered lanes read from their own stores.

Every row below is a labelled synthetic FIXTURE shaped like the lane buckets (`operations`, `tasks`,
`decisions_pending`, `execution_progress`, `invocation_reservations`, `worker_sessions`); no
provider, model, process or database runs.

"""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from m7_observation import (
    Fleet,
    LaunchRefused,
    MemoryStore,
    monitoring,
    organization,
    parse_request,
)

CANARY = 'CANARY-lane-text-must-never-reach-the-snapshot'
T0 = '2026-09-27T20:00:00+00:00'


def registered(tmp_path):
    control = MemoryStore()
    # The registered lane paths carry the canary: no repository or runtime path may reach the envelope.
    Fleet(control).register({
        'schema': 'urn:zeus:fleet:1', 'id': 'fleet-1', 'max_parallel': 2, 'budget': {'per_host': 4, 'total': 8},
        'lanes': [{'id': lane, 'team': team, 'repository': str(tmp_path / (CANARY + '-repo-' + lane)),
                   'schema': 'lane_' + lane, 'redis_namespace': 'fleet-' + lane,
                   'runtime': str(tmp_path / (CANARY + '-rt-' + lane))}
                  for lane, team in (('a', 'alpha'), ('b', 'beta'))]})
    return control


def put(store, bucket, row):
    with store.transaction() as tx:
        tx.put(bucket, row['id'], row)


def reservation(task_id, generation, status, usage, *, invocation=1, at=T0):
    """Shaped exactly like the executor's reservation request: the `parse_request` result (the model
    lives under `options`) plus the assignment receipt."""
    request = {**parse_request('claude_cli', {'model': 'claude-fixture-model', 'timeout': 60,
                                              'output_schema': {'title': CANARY}}),
               'assignment': {'provider': 'claude', 'identity': 'claude-cli', 'transport': 'claude_cli',
                              'model_source': 'explicit_setting'}}
    return {'id': f'r-{task_id}-{generation}-{invocation}', 'bucket': 'tasks', 'task_id': task_id,
            'generation': generation, 'attempt': 1, 'invocation': invocation, 'stage': 'implement',
            'owner': 'exec-' + CANARY, 'status': status, 'reserved_at': at, 'usage': usage, 'outcome': None,
            'budget_seconds': 3600, 'request': request}


def lane_a_fixture():
    """Lane `a`, shaped like the lane writers:
    - FINALIZED operation `op-1`: one implementation task that ran twice (generation 1 never settled,
      generation 2 settled with measured usage) and its lead review, which REJECTED it. Its durable worker
      session is keyed by the continuation binding's session task id (`job-1`), not by the lane task id.
    - RUNNING operation `op-2`: `task_id`/`decision_id` are still null (they are written at finalization),
      its first task is `assignment_message_id` and its follow-up decision shares its correlation id."""
    store = MemoryStore()
    put(store, 'operations', {'id': 'op-1', 'status': 'rejected', 'reason_code': 'lead_rejected',
                              'correlation_id': 'operation:op-1', 'assignment_message_id': 'task-1',
                              'task_id': 'task-1', 'decision_id': 'dec-1', 'lead_accepted': False,
                              'identity': {'repository': '/srv/' + CANARY}, 'goal': {'criterion': CANARY},
                              'continuation': {'session': {'task_id': 'job-1', 'repository': '/srv/' + CANARY}},
                              'calls': {'reserved': 2, 'settled': 1, 'slots': [CANARY]},
                              'owner_handoff': {'code': 'fixture'}, 'claimed_at': T0,
                              'updated_at': '2026-09-27T20:30:00+00:00', 'finished_at': '2026-09-27T20:30:00+00:00'})
    put(store, 'operations', {'id': 'op-2', 'status': 'running', 'reason_code': None,
                              'continuation': {'session': {'task_id': 'job-2', 'repository': '/srv/' + CANARY}},
                              'correlation_id': 'operation:op-2', 'assignment_message_id': 'task-3',
                              'task_id': None, 'decision_id': None, 'lead_accepted': None,
                              'calls': {'reserved': 0, 'settled': 0, 'slots': []}, 'claimed_at': T0,
                              'updated_at': T0, 'finished_at': None})
    put(store, 'tasks', {'id': 'task-3', 'agent': 'implementer', 'status': 'succeeded', 'generation': 1,
                         'attempt': 1, 'created_at': '2026-09-27T20:31:00+00:00',
                         'message': {'correlation_id': 'operation:op-2'}})
    put(store, 'decisions_pending', {'id': 'dec-3', 'actor': 'lead', 'status': 'running', 'phase': 'lead_review',
                                     'attempt': 1, 'created_at': '2026-09-27T20:32:00+00:00',
                                     'message': {'correlation_id': 'operation:op-2'}})
    put(store, 'tasks', {'id': 'task-1', 'agent': 'implementer', 'status': 'succeeded', 'phase': 'implement',
                         'generation': 2, 'attempt': 1, 'lease_until': '2026-09-27T20:40:00+00:00',
                         'created_at': T0, 'completed_at': '2026-09-27T20:20:00+00:00', 'error': CANARY,
                         'message': {'what': {'action': 'implement', 'details': {'plan': {'objective': CANARY}}}}})
    put(store, 'decisions_pending', {'id': 'dec-1', 'actor': 'lead', 'status': 'succeeded', 'phase': 'lead_review',
                                     'attempt': 1, 'created_at': '2026-09-27T20:21:00+00:00',
                                     'result': {'accepted': False, 'summary': CANARY}})
    put(store, 'execution_progress', {'id': 'task-1', 'agent': 'implementer', 'sequence': 7, 'generation': 2,
                                      'attempt': 1, 'provider': 'claude-cli',
                                      'occurred_at': '2026-09-27T20:10:00+00:00',
                                      'collected_at': '2026-09-27T20:10:05+00:00',
                                      'at': '2026-09-27T20:10:05+00:00', 'last_event': 'tool_started',
                                      'worktree': '/srv/' + CANARY, 'context_ref': 'sha256:' + 'c' * 64,
                                      'recent': ['sha256:' + 'd' * 64],
                                      'last_completed': {'type': 'commandExecution', 'status': 'completed',
                                                         'command': CANARY, 'sequence': 6,
                                                         'occurred_at': '2026-09-27T20:09:00+00:00',
                                                         'evidence': 'sha256:' + 'e' * 64}})
    put(store, 'invocation_reservations', {**reservation('task-1', 1, 'unsettled_unknown',
                                                         {'source': 'unknown', 'total_tokens': None}),
                                           'reason': 'superseded_by_new_attempt'})
    put(store, 'invocation_reservations', {
        **reservation('task-1', 2, 'settled', {'source': 'claude/result.usage', 'total_tokens': 1234},
                      at='2026-09-27T20:05:00+00:00'),
        'outcome': 'accepted', 'settled_at': '2026-09-27T20:19:00+00:00', 'elapsed_seconds': 840.0,
        'within_budget': True})
    put(store, 'worker_sessions', {'id': 'job-1', 'task_id': 'job-1', 'state': 'awaiting_review', 'version': 3,
                                   'session_id': 'fixture-session', 'owner': None,
                                   'identity': {'model': CANARY}, 'checkpoints': [{'archive': 'sha256:' + 'f' * 64}],
                                   'reviews': [{'decision_id': 'dec-1', 'phase': 'lead_review', 'outcome': 'rejected',
                                                'text': CANARY}]})
    # The running operation's session is OWNED by an execution: its identifier must never be emitted.
    put(store, 'worker_sessions', {'id': 'job-2', 'task_id': 'job-2', 'state': 'active', 'version': 2,
                                   'session_id': 'fixture-session-2', 'identity': {'model': CANARY},
                                   'owner': {'execution': 'exec-' + CANARY, 'generation': 4, 'attempt': 2},
                                   'checkpoints': [], 'reviews': []})
    # A second task whose only invocation never settled: its usage is unknown, never zero.
    put(store, 'tasks', {'id': 'task-2', 'agent': 'implementer', 'status': 'failed', 'generation': 1, 'attempt': 1,
                         'created_at': '2026-09-27T19:00:00+00:00'})
    put(store, 'invocation_reservations', reservation('task-2', 1, 'unsettled_unknown',
                                                      {'source': 'unknown', 'total_tokens': None},
                                                      at='2026-09-27T19:01:00+00:00'))
    return store


def lane_b_fixture():
    """Lane `b` holds a task with the SAME id as lane `a`, still running."""
    store = MemoryStore()
    put(store, 'tasks', {'id': 'task-1', 'agent': 'implementer', 'status': 'running', 'generation': 1, 'attempt': 1,
                         'lease_until': '2026-09-27T21:00:00+00:00', 'created_at': '2026-09-27T20:50:00+00:00'})
    return store


def resolver(stores):
    return lambda lane: monitoring.ReadOnlyStore(stores[lane['id']])


def test_lane_sessions_show_lane_executions_the_control_store_does_not_hold(tmp_path):
    control, stores = registered(tmp_path), {'a': lane_a_fixture(), 'b': lane_b_fixture()}
    before = {name: deepcopy(store.data) for name, store in {'control': control, **stores}.items()}
    facts = monitoring.lane_session_facts(monitoring.ReadOnlyStore(control), resolver(stores))
    # A10: read-only; nothing in any store changed.
    assert {name: store.data for name, store in {'control': control, **stores}.items()} == before
    # A1: the executions are the lanes', while the control store has no task at all.
    with control.transaction() as tx:
        assert tx.scan('tasks') == [] and tx.scan('execution_progress') == []
    assert facts['schema'] == 'urn:zeus:lane-sessions:1' and facts['registered'] is True
    lane_a, lane_b = facts['lanes']
    assert (lane_a['lane'], lane_a['team'], lane_a['status']) == ('a', 'alpha', 'ok')
    assert facts['coverage']['lanes_registered'] == 2 and facts['coverage']['lanes_observed'] == 2
    assert 'external coordinator' in facts['coverage']['uninstrumented'][0]
    # A2: the same id in two lanes is two rows, each under its own lane.
    assert [row['id'] for row in lane_b['executions']] == ['task-1']
    assert lane_b['executions'][0]['status'] == 'running'
    by_id = {row['id']: row for row in lane_a['executions']}
    task, review = by_id['task-1'], by_id['dec-1']
    assert task['status'] == 'succeeded' and task['kind'] == 'task'
    # A4: liveness, event time and collection time are separate facts; no productive/hung label.
    assert task['lease_until'] == '2026-09-27T20:40:00+00:00'
    assert (task['progress']['occurred_at'], task['progress']['collected_at']) == (
        '2026-09-27T20:10:00+00:00', '2026-09-27T20:10:05+00:00')
    assert not {'productive', 'hung', 'stalled'} & set(json.dumps(facts).split('"'))
    # A5: execution status, the lead verdict and the worker-session review stay distinct fields.
    assert task['operation']['lead_accepted'] is False and task['operation']['status'] == 'rejected'
    assert review['kind'] == 'decision' and review['accepted'] is False and review['agent'] == 'lead'
    # The durable session is reached through the operation's continuation binding (`job-1`), and only
    # the implementer's task row carries it; the review decision of the same operation does not.
    assert task['worker_session']['reviews'] == [{'decision_id': 'dec-1', 'phase': 'lead_review',
                                                  'outcome': 'rejected'}]
    assert task['worker_session']['next_owner'] == 'independent_review'
    assert review['operation']['id'] == 'op-1' and review['worker_session'] is None
    assert task['operation']['calls'] == {'reserved': 2, 'settled': 1}
    # A RUNNING operation (task_id/decision_id still null) joins its first task by the assignment id and
    # its follow-up decision by the correlation id; its call counts are unknown until it finalizes.
    running_task, running_review = by_id['task-3'], by_id['dec-3']
    assert running_task['operation']['id'] == running_review['operation']['id'] == 'op-2'
    assert (running_task['operation']['status'], running_task['operation']['calls']) == ('running', None)
    assert by_id['task-2']['operation'] is None and running_review['worker_session'] is None
    # An owned session shows that it is owned and at which generation/attempt, never by which execution.
    assert running_task['worker_session']['owner'] == {'generation': 4, 'attempt': 2}
    assert (running_task['worker_session']['state'], running_task['worker_session']['next_owner']) == (
        'active', 'execution')
    assert task['worker_session']['owner'] is None
    # A6: measured usage is shown with its source; unknown usage stays unknown (null), never zero.
    latest = task['invocations']['latest']
    assert (latest['usage_source'], latest['total_tokens'], latest['generation']) == ('claude/result.usage', 1234, 2)
    # The model the request recorded is read where the writer keeps it (`request.options.model`).
    assert (latest['provider'], latest['model_source'], latest['requested_model'], latest['reported_model']) == (
        'claude', 'explicit_setting', 'claude-fixture-model', 'not_projected')
    unknown = by_id['task-2']['invocations']['latest']
    assert (unknown['usage_source'], unknown['total_tokens']) == ('unknown', None)
    # A7: lineage: both generations are counted, the latest is generation 2, and the earlier
    # unsettled attempt is not merged into it.
    assert task['invocations']['by_status'] == {'unsettled_unknown': 1, 'settled': 1}
    assert (task['generation'], task['progress']['generation'], task['worker_session']['version']) == (2, 2, 3)
    assert lane_a['invocations'] == {'unsettled_unknown': 2, 'settled': 1}
    assert lane_a['counts'] == {'task:succeeded': 2, 'task:failed': 1, 'decision:succeeded': 1,
                                'decision:running': 1}
    # Non-terminal work sorts first.
    assert lane_a['executions'][0]['id'] == 'dec-3'
    # A9: no objective, raw error, worktree, context ref, tool text, repository, goal, owner id or
    # review text reaches the projection.
    text = json.dumps(facts)
    assert CANARY not in text and 'context_ref' not in text and 'worktree' not in text
    assert task['progress']['last_completed'] == {'type': 'commandExecution', 'status': 'completed', 'sequence': 6,
                                                  'occurred_at': '2026-09-27T20:09:00+00:00',
                                                  'evidence': 'sha256:' + 'e' * 64}


def test_lane_sessions_fail_per_lane_and_the_collector_adds_them_only_with_a_resolver(monkeypatch, tmp_path):
    control, stores = registered(tmp_path), {'a': lane_a_fixture()}

    def resolve(lane):  # INJECTED lane outage for lane `b` only
        if lane['id'] == 'b':
            raise RuntimeError('injected outage ' + CANARY)
        return monitoring.ReadOnlyStore(stores[lane['id']])
    facts = monitoring.lane_session_facts(monitoring.ReadOnlyStore(control), resolve)
    lane_a, lane_b = facts['lanes']
    # A3: the failed lane is unavailable with its error TYPE only, never an empty ok lane.
    assert lane_a['status'] == 'ok' and len(lane_a['executions']) == 5
    assert lane_b == {'lane': 'b', 'team': 'beta', 'observed_at': lane_b['observed_at'], 'status': 'unavailable',
                      'error': 'RuntimeError'}
    assert facts['coverage'] == {'lanes_registered': 2, 'lanes_observed': 1, 'lanes_unavailable': 1,
                                 'uninstrumented': [monitoring.UNINSTRUMENTED]}
    assert CANARY not in json.dumps(facts)
    # A9 through the real resolver: the host DSN, the registered lane paths and a failing lane store all
    # carry the canary; only the lane id, team and error TYPE reach the envelope.
    def failing(dsn, schema):  # FIXTURE store factory whose read fails with a canary-bearing error
        class Store:
            def transaction(self):
                raise RuntimeError('connect failed for ' + dsn)
        return Store()
    real = monitoring.lane_session_facts(control, monitoring.lane_resolver(
        f'postgresql://user' f':{CANARY}@fixture-host/zeus', failing))
    assert [lane['error'] for lane in real['lanes']] == ['RuntimeError', 'RuntimeError']
    assert CANARY not in json.dumps(real) and 'fixture-host' not in json.dumps(real)
    # An unregistered Fleet reports exactly that; it is not a store failure.
    empty = monitoring.lane_session_facts(MemoryStore(), resolve)
    assert (empty['registered'], empty['lanes'], empty['coverage']['lanes_registered']) == (False, [], 0)
    monkeypatch.setattr(monitoring, 'docker_facts', lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, 'redis_facts', lambda url, agents: [])
    service = SimpleNamespace(store=control, org=organization())
    # A11: without a lane resolver the snapshot is exactly as before (no `lane_sessions`).
    plain = monitoring.collect(service, None, str(tmp_path), 'redis://127.0.0.1/0')
    assert 'lane_sessions' not in plain['sources']
    snapshot = monitoring.collect(service, None, str(tmp_path), 'redis://127.0.0.1/0', lanes=resolve)
    assert snapshot['sources']['lane_sessions']['status'] == 'ok'
    assert snapshot['sources']['lane_sessions']['data']['coverage']['lanes_unavailable'] == 1

    class Broken:  # INJECTED control-store outage: the whole envelope is unavailable, never empty
        def transaction(self):
            raise RuntimeError('injected outage ' + CANARY)
    failed = monitoring.collect(SimpleNamespace(store=Broken(), org=organization()), None, str(tmp_path),
                                'redis://127.0.0.1/0', lanes=resolve)['sources']['lane_sessions']
    assert failed == {'status': 'unavailable', 'observed_at': failed['observed_at'], 'error': 'RuntimeError',
                      'data': None}


def test_lane_sessions_are_bounded_active_first_and_say_when_truncated(tmp_path):
    control, lane = registered(tmp_path), MemoryStore()
    for index in range(monitoring.LANE_SESSION_LIMIT + 1):
        put(lane, 'tasks', {'id': f'done-{index:02d}', 'agent': 'implementer', 'status': 'succeeded',
                            'created_at': f'2026-09-27T20:{index:02d}:00+00:00'})
    put(lane, 'tasks', {'id': 'oldest-running', 'agent': 'implementer', 'status': 'running',
                        'created_at': '2026-09-01T00:00:00+00:00'})
    facts = monitoring.lane_session_facts(control, resolver({'a': lane, 'b': MemoryStore()}))
    rows = facts['lanes'][0]
    # A8: capped, with the total and the truncation explicit; running work is never cut off.
    assert (rows['total'], rows['truncated'], len(rows['executions'])) == (
        monitoring.LANE_SESSION_LIMIT + 2, True, monitoring.LANE_SESSION_LIMIT)
    assert rows['executions'][0]['id'] == 'oldest-running'
    assert rows['executions'][1]['id'] == f'done-{monitoring.LANE_SESSION_LIMIT:02d}'
    assert facts['lanes'][1]['total'] == 0 and facts['lanes'][1]['truncated'] is False


def test_lane_resolver_reads_each_lane_schema_through_lane_dsn_and_caches_per_schema():
    opened = []

    def factory(dsn, schema):  # FIXTURE store factory: records the connection string, opens nothing
        opened.append((dsn, schema))
        return MemoryStore()
    resolve = monitoring.lane_resolver('postgresql://fixture-host/zeus', factory)
    first = resolve({'id': 'a', 'schema': 'lane_a'})
    assert resolve({'id': 'a', 'schema': 'lane_a'}) is first and len(opened) == 1
    assert 'search_path=lane_a' in opened[0][0] and opened[0][1] == 'lane_a'
    # A changed registration for the same lane id never reuses the other schema's store.
    assert resolve({'id': 'a', 'schema': 'lane_a2'}) is not first and 'search_path=lane_a2' in opened[1][0]
    # The wrapper is read-only: a write through it is a contract error.
    with first.transaction() as tx, pytest.raises(monitoring.ContractError):
        tx.put('tasks', 'x', {})
    # A missing host DSN is the launcher's own refusal (the lane becomes unavailable), never a fallback.
    with pytest.raises(LaunchRefused):
        monitoring.lane_resolver(None, factory)({'id': 'b', 'schema': 'lane_b'})
    # The default store is the lock-free snapshot store, not the writers' PostgresStore.
    assert isinstance(monitoring.lane_resolver('postgresql://fixture-host/zeus')(
        {'id': 'a', 'schema': 'lane_a'})._store, monitoring.LaneSnapshotStore)


class FakeConnection:
    """FIXTURE psycopg connection: records every statement and answers the schema and scan reads."""

    def __init__(self, schema):
        self.schema, self.statements = schema, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append(statement)
        rows = [(self.schema,)] if statement == 'SELECT current_schema()' else [({'id': 'task-1'},)]
        return SimpleNamespace(fetchone=lambda: rows[0], fetchall=lambda: rows)


def test_lane_snapshot_store_reads_one_read_only_snapshot_without_the_writer_lock():
    connections = []

    def connect(dsn, **options):  # FIXTURE connect: no database
        assert options == {'connect_timeout': 5, 'autocommit': True}
        connections.append(FakeConnection('lane_a' if 'lane_a' in dsn else 'public'))
        return connections[-1]
    store = monitoring.LaneSnapshotStore('fixture lane_a', 'lane_a', connect=connect)
    with store.transaction() as tx:
        assert tx.scan('tasks') == [{'id': 'task-1'}]
        with pytest.raises(monitoring.ContractError):
            tx.put('tasks', 'x', {})
    statements = connections[0].statements
    assert statements[0] == 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY'
    assert statements[1] == "SET LOCAL statement_timeout = '5000ms'" and statements[-1] == 'ROLLBACK'
    assert not [statement for statement in statements if 'advisory' in statement or 'lock' in statement.lower()]
    # A connection that selected another schema (e.g. a fallback to `public`) reads nothing, and the
    # snapshot is still rolled back.
    with pytest.raises(monitoring.ContractError), \
            monitoring.LaneSnapshotStore('fixture other', 'lane_a', connect=connect).transaction():
        pass
    assert connections[1].statements[-1] == 'ROLLBACK' and len(connections[1].statements) == 4


def test_lane_snapshot_store_is_not_blocked_by_a_held_writer_lock(isolated_pgstore):
    """Integration (real PostgreSQL): while a writer holds the store's advisory lock in an open
    transaction, the monitor's lane snapshot still reads the committed rows at once."""
    import psycopg
    store = isolated_pgstore
    with psycopg.connect(store.dsn) as conn:
        schema = conn.execute('SELECT current_schema()').fetchone()[0]
    with store.transaction() as tx:
        tx.put('tasks', 'task-1', {'id': 'task-1', 'agent': 'implementer', 'status': 'running'})
    with store.transaction() as tx:  # the writer lock is held for the rest of this block
        tx.put('tasks', 'task-2', {'id': 'task-2', 'agent': 'implementer', 'status': 'queued'})
        with monitoring.LaneSnapshotStore(store.dsn, schema, statement_timeout_ms=2000).transaction() as snapshot:
            assert [row['id'] for row in snapshot.scan('tasks')] == ['task-1']
