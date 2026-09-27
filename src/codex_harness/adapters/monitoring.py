"""Host-side collection. The HTTP server never imports this Docker/DB adapter.

The collector is a read-only consumer: it reads PostgreSQL facts and already persisted
metric observations, runs only read-only Docker/Redis commands and never puts rows or artifacts.
"""
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.commands import run_process
from codex_harness.adapters.monitoring_observations import observation_facts
from codex_harness.application.fleet import Fleet
from codex_harness.application.monitoring import Monitoring
from codex_harness.domain.fleet import FleetRefused
from codex_harness.domain.model import ContractError

CONTAINER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
MAX_CONTAINERS = 32


def safe_text(value, limit=1200):
    text = str(value or '')
    text = re.sub(r'([a-z]+://)[^\s/@]+:[^\s/@]+@', r'\1[redacted]@', text)
    text = re.sub(r'(?i)(Bearer\s+|(?:api[_-]?key|password|token)\s*[=:]\s*)\S+', r'\1[redacted]', text)
    return text[:limit]


class ReadOnlyTransaction:
    """Store transaction view for the monitor: reads delegate, every write is a contract error."""

    def __init__(self, transaction):
        self._transaction = transaction

    def get(self, bucket, key):
        return self._transaction.get(bucket, key)

    def scan(self, bucket):
        return self._transaction.scan(bucket)

    def entries(self, bucket, after='', limit=100):
        return self._transaction.entries(bucket, after, limit)

    def records(self):
        return self._transaction.records()

    def put(self, *args, **kwargs):
        raise ContractError('Monitor store is read-only')

    def graph(self):
        raise ContractError('Monitor store is read-only')


class ReadOnlyStore:
    def __init__(self, store):
        self._store = store

    @contextmanager
    def transaction(self):
        with self._store.transaction() as transaction:
            yield ReadOnlyTransaction(transaction)


class ReadOnlyArtifacts:
    """Artifact reader for the monitor: bounded integrity-checked reads only, never put."""

    def __init__(self, artifacts):
        self._artifacts = artifacts

    def put(self, *args, **kwargs):
        raise ContractError('Monitor artifact reader is read-only')

    def _body(self, reference, max_bytes=None):
        return self._artifacts._body(reference, max_bytes)

    def document(self, reference):
        return self._artifacts.document(reference)

    def text(self, reference, max_bytes):
        return self._artifacts.text(reference, max_bytes)

    def read(self, reference, start=0, length=8000):
        return self._artifacts.read(reference, start, length)

    def inspect(self, reference):
        return self._artifacts.inspect(reference)

    def search(self, reference, needle, limit=20):
        return self._artifacts.search(reference, needle, limit)


class ReadOnlyService:
    """The two attributes DatabaseFacts uses, with the store wrapped read-only."""

    def __init__(self, service):
        self.store, self.org = ReadOnlyStore(service.store), service.org


def read_only(service, artifacts):
    return ReadOnlyService(service), ReadOnlyArtifacts(artifacts)


def container_scope(value):
    """ZEUS_MONITOR_CONTAINERS: unset/blank keeps Compose scope (None); otherwise a JSON list of
    1..32 unique exact container names. Anything else is a configuration error, never a fallback."""
    if value is None or not str(value).strip():
        return None
    try:
        names = json.loads(value)
    except ValueError as exc:
        raise ValueError('Monitor container scope must be a JSON list') from exc
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_CONTAINERS:
        raise ValueError(f'Monitor container scope must list 1..{MAX_CONTAINERS} names')
    if not all(isinstance(name, str) and CONTAINER_NAME.fullmatch(name) for name in names):
        raise ValueError('Monitor container scope names must be exact Docker container names')
    if len(set(names)) != len(names):
        raise ValueError('Monitor container scope names must be unique')
    return list(names)


def parse_observed(value):
    """A stored observation counts only with a timezone-aware ISO timestamp."""
    try:
        observed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return observed if observed.tzinfo is not None else None


def persisted_measurements(store, now=None):
    """Latest persisted observation per metric_id from `metric_observations`, original time kept.
    No observations means an empty list: the monitor never evaluates or fabricates values."""
    now = now or datetime.now(timezone.utc)
    with store.transaction() as tx:
        rows = tx.scan('metric_observations')
    latest = {}
    for row in rows:
        metric_id, observed = row.get('metric_id'), parse_observed(row.get('observed_at'))
        if not isinstance(metric_id, str) or not metric_id or observed is None:
            continue
        current = latest.get(metric_id)
        if current is None or observed > current[0]:
            latest[metric_id] = (observed, row)
    output = []
    for metric_id in sorted(latest):
        observed, row = latest[metric_id]
        output.append({**row, 'source': 'persisted_observation',
                       'age_seconds': (now - observed).total_seconds()})
    return output


class DatabaseFacts:
    def __init__(self, service, artifacts):
        self.service, self.artifacts = service, artifacts

    def read(self):
        with self.service.store.transaction() as tx:
            data = {name: tx.scan(name) for name in ('tasks', 'decisions_pending', 'sessions',
                    'execution_progress', 'hooks', 'releases', 'events', 'reference_audits',
                    'research_audits', 'research_partitions')}
            active, health = tx.get('deployment', 'active'), tx.get('health', 'latest')
            audit_control = tx.get('research_control', 'activation') or {}
            outbox_health = tx.get('health', 'outbox') or {}
            outbox_counts = dict(Counter(row['status'] for row in tx.scan('outbox_delivery')))
        progress_by_id = {p['id']: p for p in data['execution_progress']}
        def work(row, decision=False):
            message = row.get('message', {})
            details = message.get('what', {}).get('details', {})
            plan = details.get('plan') or details
            result = row.get('result') or {}
            return {'id': row['id'], 'agent': row.get('actor' if decision else 'agent'),
                    'status': row['status'], 'phase': row.get('phase', message.get('what', {}).get('action')),
                    'objective': safe_text(plan.get('objective') or result.get('summary')),
                    'correlation': message.get('correlation_id'), 'parent': message.get('causation_id'),
                    'attempt': row.get('attempt', 0), 'lease_until': row.get('lease_until'),
                    'created_at': row.get('created_at') or message.get('when', {}).get('created_at'),
                    'completed_at': row.get('completed_at'),
                    'progress_at': progress_by_id.get(row['id'], {}).get('at'),
                    'release_id': result.get('release_id'),
                    'error': safe_text(row.get('error')),
                    'reason': safe_text(result.get('reason')), 'accepted': result.get('accepted'),
                    'evidence': result.get('execution_ref'), 'revision': result.get('candidate', {}).get('revision')}
        tasks = [work(row) for row in data['tasks']]
        decisions = [work(row, True) for row in data['decisions_pending']]
        agents = [asdict(agent) for agent in self.service.org.agents.values()]
        sessions = {row['agent_id']: row for row in data['sessions']}
        for agent in agents:
            session = sessions.get(agent['id'], {})
            checkpoint = session.get('checkpoint', {})
            usage, usage_at, source = checkpoint.get('usage'), None, 'checkpoint'
            progress = sorted([p for p in data['execution_progress'] if p.get('agent') == agent['id']],
                              key=lambda p: p.get('at', ''), reverse=True)
            latest = progress[0] if progress else {}
            context_bytes = None
            if latest.get('context_ref'):
                try:
                    context_bytes = json.loads(self.artifacts._body(latest['context_ref'])).get('estimated_tokens')
                except (OSError, ValueError):
                    pass
            # Only extract telemetry; never expose raw tool output or model reasoning.
            for ref in reversed(latest.get('recent', [])):
                try:
                    item = json.loads(self.artifacts._body(ref))
                    event = item.get('event', item)
                    if event.get('method') == 'thread/tokenUsage/updated':
                        usage = event['params']['tokenUsage']
                        usage_at, source = latest.get('at'), 'recent_observation'
                        break
                except (OSError, ValueError, KeyError):
                    continue
            capacity = (usage or {}).get('modelContextWindow')
            used = (usage or {}).get('last', {}).get('totalTokens')
            agent['session'] = {'id': session.get('session_id'), 'generation': session.get('generation'),
                'thread_id': checkpoint.get('thread_id'), 'next_action': safe_text(checkpoint.get('next_action')),
                'handoff_reason': checkpoint.get('handoff_reason'), 'used_tokens': used, 'capacity': capacity,
                'fraction': used / capacity if used is not None and capacity else None,
                'usage_source': source, 'usage_at': usage_at, 'progress_at': latest.get('at'),
                'prompt_bytes': context_bytes, 'checkpoint_evidence': checkpoint.get('evidence_ref')}
        hooks = [{k: row.get(k) for k in ('id', 'status', 'root_cause', 'scope', 'revision', 'version')}
                 | {'fixture': row.get('root_cause') == 'fixture-cause', 'occurrences': len(row.get('occurrences', []))}
                 for row in data['hooks']]
        releases = []
        for row in data['releases']:
            candidate = row.get('candidate', {})
            releases.append({'id': row['id'], 'status': row['status'], 'revision': candidate.get('revision'),
                'created_at': row.get('created_at'), 'branch': candidate.get('branch'),
                'reviews': [{k: r.get(k) for k in ('actor', 'accepted', 'evidence')} for r in row.get('reviews', [])],
                'checks': {name: {'passed': check.get('passed'), 'evidence': check.get('evidence')}
                           for name, check in row.get('checks', {}).items()}})
        audits = audit_progress(data, audit_control)
        return {'agents': agents, 'tasks': tasks, 'decisions': decisions, 'hooks': hooks, 'releases': releases,
                'notifications': {'status_counts': outbox_counts, 'last_batch': outbox_health},
                'audits': audits,
                'active': {k: (active or {}).get(k) for k in ('release_id', 'revision', 'at')},
                'health': {k: (health or {}).get(k) for k in ('status', 'checked_at')},
                'events': [{k: row.get(k) for k in ('type', 'at', 'task_id', 'hook_id', 'release_id')}
                           for row in sorted(data['events'], key=lambda r: r.get('at', ''), reverse=True)[:60]]}


def audit_progress(data, control):
    """INV-RESEARCH-001: checkpoint counts do not certify semantic review or adoption."""
    output = {(r['repository'], r['revision']): {k: r.get(k) for k in (
        'id', 'repository', 'revision', 'status', 'files', 'manifest_ref',
        'semantically_reviewed_files', 'independent_review', 'review_ref', 'test_receipt_ref')}
        for r in data.get('reference_audits', [])}
    for audit in data.get('research_audits', []):
        source = audit['source']
        key = (source['repository'], source['commit'])
        partitions = [p for p in data.get('research_partitions', []) if p['audit_id'] == audit['id']]
        row = output.setdefault(key, {'repository': key[0], 'revision': key[1]})
        row.update(audit_id=audit['id'], files=len(audit['inventory']),
                   status=audit['status'], manifest_ref=source['manifest_ref'],
                   dispatch_status=control.get('status', 'inactive'),
                   checkpoint_partitions=len(partitions),
                   remaining_paths=len({p for part in partitions for p in part['remaining_paths']})
                   if partitions else None,
                   remaining_subsystems=len({s for part in partitions for s in part['remaining_subsystems']})
                   if partitions else None,
                   open_questions=sum(len(p['open_questions']) for p in partitions),
                   independent_review='not_certified_by_monitor')
    return list(output.values())


def docker_stats(names):
    if not names:
        return {}
    process = run_process(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *names], timeout=15)
    if process.returncode:
        raise RuntimeError('Docker metrics unavailable')
    stats = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    return {row['Name']: row for row in stats}


def docker_facts(repository, containers=None):
    """Compose scope (containers None) is unchanged. Named scope lists exactly the requested
    containers with read-only `docker ps --all` and `docker stats`; the CLI name filter matches
    substrings, so returned names are checked exactly, unrelated containers are dropped and any
    missing requested name makes the whole source unavailable rather than success-empty."""
    if containers is None:
        process = run_process(['docker', 'compose', 'ps', '--all', '--format', 'json'], cwd=repository, timeout=15)
        if process.returncode:
            raise RuntimeError('Docker status unavailable')
        rows = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
        rows = [{'service': row['Service'], 'name': row['Name'], 'state': row['State'], 'image': row['Image']}
                for row in rows]
    else:
        filters = [arg for name in containers for arg in ('--filter', f'name={name}')]
        process = run_process(['docker', 'ps', '--all', '--format', '{{json .}}', *filters], timeout=15)
        if process.returncode:
            raise RuntimeError('Docker status unavailable')
        listed = {}
        for line in process.stdout.splitlines():
            if line.startswith('{'):
                row = json.loads(line)
                listed[row.get('Names')] = row
        missing = [name for name in containers if name not in listed]
        if missing:
            raise RuntimeError('Docker container missing')
        rows = [{'service': name, 'name': name, 'state': listed[name].get('State'),
                 'image': listed[name].get('Image')} for name in containers]
    lookup = docker_stats([row['name'] for row in rows if row['state'] == 'running'])
    return [{**row, 'cpu': lookup.get(row['name'], {}).get('CPUPerc'),
             'memory': lookup.get(row['name'], {}).get('MemUsage')} for row in rows]


def redis_facts(url, agents):
    bus = RedisBus(url)
    bus.client.connection_pool.connection_kwargs.update(socket_timeout=3, socket_connect_timeout=3)
    output = []
    for agent in agents:
        key = bus.stream(agent)
        exists = bus.client.exists(key)
        groups = bus.client.xinfo_groups(key) if exists else []
        output.append({'agent': agent, 'entries': bus.client.xlen(key) if exists else 0,
                       'pending': sum(g.get('pending', 0) for g in groups),
                       'lag': (None if any(g.get('lag') is None for g in groups)
                               else sum(g.get('lag', 0) for g in groups)) if groups else None})
    return output


def fleet_facts(store):
    """INV-FLEET-001 projection (`urn:zeus:fleet-status:1`) from PG reads only: identities,
    states, codes and counts; never manifests, paths, schemas, DSNs or raw errors. Registration
    is not service health, and `updated_at` is the last recorded fact, not liveness."""
    return Fleet(store).status()


def research_program_facts(store):
    """INV-RESEARCH-PROGRAM-001 projection (`urn:zeus:research-program-monitor:1`) from store reads
    only: program states, cycle/adoption counts, outcomes and stop reasons for at most 20 programs
    with `truncated` explicit; never configs, feed bodies, paths or raw errors."""
    from codex_harness.application.research_program import ResearchProgram
    return ResearchProgram(store).monitor()


def portfolio_facts(store):
    """Operating portfolio projection (`urn:zeus:portfolio-status:1`) from store reads only: the
    owner's goals, their criterion acceptance records, the bound jobs' identities/states/codes and
    the failure investigation queue. Never manifests, objectives, paths, credentials or raw errors.
    A candidate is a coarse triage family, not a confirmed cause, and an acceptance record is an
    owner statement, not proof that the whole source was absorbed. A store failure propagates so
    the envelope becomes `unavailable` rather than an empty portfolio."""
    from codex_harness.adapters.portfolio import portfolio
    return portfolio(store).status()


def fleet_backlog_facts(store):
    """INV-FLEET-BACKLOG-001 projection (`urn:zeus:fleet-backlog-status:1`) for every registered
    plan, from store reads only: plan and item identities, the pin, item state, the authoritative
    Fleet job status, the linkage state, fixed reason codes, attempts, deferrals, counts and a
    bounded next action. Never manifests, objectives, goal text, absolute paths, schemas, DSNs or
    raw errors.

    This is the same read-only status the `fleet backlog status` command projects; no tick happens
    here, so nothing is selected, read from Git, enqueued, bound or written. `plan_paused`,
    `fleet_paused`, `backlog_exhausted`, `blocked` and `conflict` stay distinct outcomes, an
    unregistered plan is `registered: false` with an empty `plans` list rather than an absent
    source, and a store failure propagates so the envelope becomes `unavailable` rather than an
    empty backlog. A collected status is a selection projection only: never evidence of active
    work, acceptance, release or deployment.
    """
    from codex_harness.application.fleet_backlog import FleetBacklog
    return FleetBacklog(store).status()


def host_delivery_facts(store):
    """INV-HOST-DELIVERY-001 projection (`urn:zeus:host-delivery-status:1`) for every registered
    delivery plan and every host target, from store reads only: plan, release, target and instance
    identities, the Git pin, descriptor DIGESTS, the durable stage, fixed reason codes, counts and
    a bounded next action. Never a descriptor body, a host root, a service name, a scheduled task,
    a PR title, a check log, a credential or a raw error.

    This is the same read-only status the `host-delivery status` command projects; no tick happens
    here, so nothing is published, merged, switched, started or written. `awaiting_review`,
    `awaiting_ci`, `switching`, `awaiting_consumption`, `active`, `blocked`, `rolling_back` and
    `rolled_back` stay distinct, a target whose descriptor was switched but NOT consumed reports
    `consumed: false` rather than an activation, an unregistered controller is `registered: false`
    with an empty list rather than an absent source, and a store failure propagates so the envelope
    becomes `unavailable` rather than an empty delivery. A collected status is a durable-record
    projection only: never evidence of a qualified live host or a passed owner canary.
    """
    from codex_harness.application.host_delivery import HostDelivery
    return HostDelivery(store).status()


def worker_session_facts(store):
    """INV-WORKER-SESSION-001 projection (`zeus.worker-session.v1`) of every durable task session,
    from store reads only: task and session identifiers, state, version, the running owner's
    execution/generation/attempt, the binding as ONE digest, archive references and hashes, review
    decision ids and outcomes, promotion/cleanup records, per-state counts and the fixed next owner
    and next action (blocked, unresolved and cleanup-failed sessions name the operator). Never
    transcript bytes, archive paths, prompts or the raw binding values.

    This is the same read-only status `worker-session status` prints; no archive is read, nothing
    is begun, resumed, promoted or closed, and a store failure propagates so the envelope becomes
    `unavailable` rather than an empty list. A collected status is not a transcript continuity
    proof, an acceptance, a promotion or evidence that any model call ran.
    """
    from codex_harness.application.worker_sessions import WorkerSessions
    return WorkerSessions(store, None).status()


def continuation_facts(store):
    """INV-CONTINUATION-001 projection (`urn:zeus:continuation-status:1`) from store reads only:
    registered policies (id, enabled, digest, pin), every intent's routing-table route, state,
    cause code, next owner and next action, evidence references and predecessor/successor links,
    per-state counts and the held families. Never a manifest, an objective, review text, a
    transcript, a path or a credential; nothing is ticked, dispatched or admitted, and a store
    failure propagates so the envelope becomes `unavailable` rather than an empty list."""
    from codex_harness.application.continuation import Continuation
    return Continuation(store).status()


LANE_SESSIONS_SCHEMA = 'urn:zeus:lane-sessions:1'
LANE_SESSION_LIMIT = 50
ACTIVE_EXECUTION = frozenset({'queued', 'pending', 'retry', 'running'})
UNINSTRUMENTED = ('sessions started outside Zeus task ownership (an external coordinator or helper process) '
                  'are not observed here and are never inferred from unit names or process ids')


LANE_SNAPSHOT_BEGIN = 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY'


class LaneSnapshotStore:
    """A lane store for the monitor that never takes the writers' advisory lock
    (`PostgresStore.transaction` serializes every writer of the database through it). Each
    transaction is ONE `REPEATABLE READ READ ONLY` snapshot (the council_snapshot pattern) with
    bounded connect and statement timeouts, over a connection whose selected schema is verified to be
    the lane's; it is always rolled back, and a write is refused here and by the server."""

    def __init__(self, dsn, schema, *, connect=None, statement_timeout_ms=5000):
        if connect is None:  # imported lazily so a store-free unit test needs no driver
            import psycopg
            connect = psycopg.connect
        self.dsn, self.schema, self.connect, self.statement_timeout_ms = dsn, schema, connect, statement_timeout_ms

    @contextmanager
    def transaction(self):
        with self.connect(self.dsn, connect_timeout=5, autocommit=True) as conn:
            conn.execute(LANE_SNAPSHOT_BEGIN)
            try:
                conn.execute("SET LOCAL statement_timeout = '%dms'" % self.statement_timeout_ms)
                if conn.execute('SELECT current_schema()').fetchone()[0] != self.schema:
                    raise ContractError('Lane snapshot selected another schema')
                yield LaneSnapshotTransaction(conn)
            finally:
                conn.execute('ROLLBACK')


class LaneSnapshotTransaction:
    def __init__(self, conn):
        self._conn = conn

    def get(self, bucket, key):
        row = self._conn.execute('SELECT body FROM documents WHERE bucket=%s AND id=%s', (bucket, key)).fetchone()
        return row[0] if row else None

    def scan(self, bucket):
        return [row[0] for row in self._conn.execute(
            'SELECT body FROM documents WHERE bucket=%s ORDER BY id', (bucket,)).fetchall()]

    def put(self, *args, **kwargs):
        raise ContractError('Monitor store is read-only')


def lane_resolver(host_dsn, store_factory=None):
    """`lane -> read-only store` over the lane's own schema through the SAME `lane_dsn` path the Fleet
    launcher and the owner actions use (no second registry). Cached per (lane id, schema), so a
    changed registration never reuses another schema's store; nothing is created here. The default
    store is the lock-free `LaneSnapshotStore`; `store_factory(dsn, schema)` is injectable."""
    from codex_harness.adapters.fleet_runtime import lane_dsn
    store_factory = store_factory or LaneSnapshotStore
    cache = {}

    def resolve(lane):
        key = (lane['id'], lane['schema'])
        if key not in cache:
            cache[key] = ReadOnlyStore(store_factory(lane_dsn(host_dsn, lane['schema']), lane['schema']))
        return cache[key]
    return resolve


def _execution_view(row, kind, operation, progress, reservations, session):
    message = row.get('message') or {}
    completed = (progress or {}).get('last_completed') or {}
    latest = max(reservations, key=lambda r: (r.get('generation', 0), r.get('attempt', 0), r.get('invocation', 0)),
                 default=None)
    usage = (latest or {}).get('usage') or {}
    assignment = ((latest or {}).get('request') or {}).get('assignment') or {}
    measured = usage.get('source') not in (None, 'unknown')
    return {
        'kind': kind, 'id': row['id'], 'agent': row.get('actor' if kind == 'decision' else 'agent'),
        'status': row.get('status'), 'phase': row.get('phase', (message.get('what') or {}).get('action')),
        'generation': row.get('generation'), 'attempt': row.get('attempt'),
        # Ownership liveness only: a renewed lease is not evidence of useful work.
        'lease_until': row.get('lease_until'),
        'created_at': row.get('created_at') or (message.get('when') or {}).get('created_at'),
        'completed_at': row.get('completed_at'),
        # A review verdict is its own field, never folded into the execution status.
        'accepted': (row.get('result') or {}).get('accepted') if kind == 'decision' else None,
        'operation': None if operation is None else {
            'id': operation['id'], 'status': operation.get('status'), 'reason_code': operation.get('reason_code'),
            'decision_id': operation.get('decision_id'), 'lead_accepted': operation.get('lead_accepted'),
            # Call counts are written only when the operation finalizes; while it runs they are unknown.
            'calls': None if operation.get('status') == 'running' else {
                k: (operation.get('calls') or {}).get(k) for k in ('reserved', 'settled')},
            'owner_handoff': bool(operation.get('owner_handoff')), 'claimed_at': operation.get('claimed_at'),
            'updated_at': operation.get('updated_at'), 'finished_at': operation.get('finished_at')},
        'progress': None if progress is None else {
            'sequence': progress.get('sequence'), 'generation': progress.get('generation'),
            'attempt': progress.get('attempt'), 'provider': progress.get('provider'),
            # Event time and collection time stay apart (a replay never reorders by the merge moment).
            'occurred_at': progress.get('occurred_at'), 'collected_at': progress.get('collected_at'),
            'last_event': progress.get('last_event'),
            'last_completed': {k: completed.get(k) for k in ('type', 'status', 'sequence', 'occurred_at',
                                                               'evidence')} if completed else None,
            'malformed_events': progress.get('malformed_events', 0)},
        'invocations': {
            'count': len(reservations),
            'by_status': dict(Counter(r.get('status') for r in reservations)),
            'latest': None if latest is None else {
                'stage': latest.get('stage'), 'status': latest.get('status'), 'outcome': latest.get('outcome'),
                'reason': latest.get('reason'), 'generation': latest.get('generation'),
                'attempt': latest.get('attempt'), 'invocation': latest.get('invocation'),
                'provider': assignment.get('provider'), 'identity': assignment.get('identity'),
                'transport': assignment.get('transport'), 'model_source': assignment.get('model_source'),
                # The model the reservation request recorded (`parse_request` keeps it under `options`);
                # the model the provider reported lives in the execution receipt and is not read here.
                'requested_model': ((latest.get('request') or {}).get('options') or {}).get('model'),
                'reported_model': 'not_projected',
                # INV-INVOCATION-001: unknown usage carries no count; it is never read as zero.
                'usage_source': usage.get('source', 'unknown'),
                'total_tokens': usage.get('total_tokens') if measured else None,
                'reserved_at': latest.get('reserved_at'), 'settled_at': latest.get('settled_at'),
                'elapsed_seconds': latest.get('elapsed_seconds'), 'within_budget': latest.get('within_budget')}},
        'worker_session': None if session is None else {
            **{k: session.get(k) for k in ('state', 'version', 'reviews', 'next_owner', 'next_action', 'blocked',
                                           'reason')},
            # Ownership and its lineage only: the owning execution's identifier is never emitted.
            'owner': {k: session['owner'].get(k) for k in ('generation', 'attempt')}
            if isinstance(session.get('owner'), dict) else None}}


def lane_view(store):
    """One lane's executions from ONE read transaction of its own store: task and decision rows, the
    operation that names them, their progress, invocation reservations and durable worker session.
    Rows are keyed by the lane-local id; the caller adds the lane, so equal ids in two lanes stay
    distinct. Never objectives, prompts, transcripts, tool text, worktrees, context refs or raw errors."""
    from codex_harness.application.worker_sessions import BUCKET as SESSIONS
    from codex_harness.domain.worker_sessions import status_view
    with store.transaction() as tx:
        rows = {name: tx.scan(name) for name in ('operations', 'tasks', 'decisions_pending', 'execution_progress',
                                                 'invocation_reservations', SESSIONS)}
    # An operation names its first task (`assignment_message_id`) from the claim, but `task_id` and
    # `decision_id` only when it finalizes; every execution of it carries the operation's correlation id.
    by_execution, by_correlation = {}, {}
    for row in rows['operations']:
        for key in ('assignment_message_id', 'task_id', 'decision_id'):
            if isinstance(row.get(key), str):
                by_execution.setdefault(row[key], row)
        if isinstance(row.get('correlation_id'), str):
            by_correlation.setdefault(row['correlation_id'], row)

    def operation_of(row):
        correlation = (row.get('message') or {}).get('correlation_id')
        return by_execution.get(row['id']) or (by_correlation.get(correlation) if isinstance(correlation, str) else None)

    progress = {row['id']: row for row in rows['execution_progress']}
    reservations = {}
    for row in rows['invocation_reservations']:
        reservations.setdefault((row.get('bucket', 'tasks'), row.get('task_id')), []).append(row)
    # A durable worker session is keyed by the continuation binding's session task id (the Fleet job or
    # its family root), recorded on the lane operation at claim; it is reached through that operation.
    sessions = {row.get('task_id'): status_view(row) for row in rows[SESSIONS]}

    def session_of(operation):
        session = ((operation or {}).get('continuation') or {}).get('session')
        return sessions.get(session.get('task_id')) if isinstance(session, dict) else None

    executions = []
    for kind, bucket in (('task', 'tasks'), ('decision', 'decisions_pending')):
        for row in rows[bucket]:
            operation = operation_of(row)
            # The durable session is the implementer's; a review decision of the same operation is not it.
            executions.append(_execution_view(row, kind, operation, progress.get(row['id']),
                                              reservations.get((bucket, row['id']), []),
                                              session_of(operation) if kind == 'task' else None))

    def activity(view):
        latest = view['invocations']['latest'] or {}
        return max((str(value) for value in (view['created_at'], view['completed_at'],
                                             (view['progress'] or {}).get('collected_at'),
                                             latest.get('reserved_at'), latest.get('settled_at')) if value),
                   default='')
    executions.sort(key=lambda view: (view['status'] in ACTIVE_EXECUTION, activity(view)), reverse=True)
    return {'executions': executions[:LANE_SESSION_LIMIT], 'total': len(executions),
            'truncated': len(executions) > LANE_SESSION_LIMIT,
            'counts': dict(Counter(f"{view['kind']}:{view['status']}" for view in executions)),
            'invocations': dict(Counter(row.get('status') for row in rows['invocation_reservations'])),
            'worker_sessions': dict(Counter(view['state'] for view in sessions.values()))}


def lane_session_facts(store, resolve):
    """INV-LANE-SESSIONS-001 (`urn:zeus:lane-sessions:1`): every REGISTERED lane's executions, read
    from the lane's own store (the control store holds none of them). Each lane fails independently as `unavailable` with its
    error type only, never as an empty ok lane. An unregistered Fleet is `registered: false` with no
    lane (as the `fleet` source reports it); any other store failure propagates so the envelope is
    `unavailable`. `coverage.uninstrumented` names what this source cannot see. A collected row is
    a durable-record projection only: never evidence of useful progress, acceptance or delivery."""
    try:
        lanes = Fleet(store).registered()['config']['lanes']
    except FleetRefused as exc:
        if exc.reason_code != 'unregistered':
            raise
        lanes = None
    views = []
    for lane in lanes or ():
        observed = datetime.now(timezone.utc).isoformat()
        try:
            view = {'status': 'ok', **lane_view(resolve(lane))}
        except Exception as exc:
            view = {'status': 'unavailable', 'error': type(exc).__name__}
        views.append({'lane': lane['id'], 'team': lane.get('team'), 'observed_at': observed, **view})
    observed = sum(view['status'] == 'ok' for view in views)
    return {'schema': LANE_SESSIONS_SCHEMA, 'registered': lanes is not None,
            'authority': 'durable-record projection; not progress, acceptance or delivery evidence',
            'lanes': views,
            'coverage': {'lanes_registered': len(lanes or ()), 'lanes_observed': observed,
                         'lanes_unavailable': len(views) - observed, 'uninstrumented': [UNINSTRUMENTED]}}


def discovery_pressure_facts(store):
    """INV-DISCOVERY-PRESSURE-001 projection (`urn:zeus:discovery-pressure:1`) from store reads only: the
    recorded proactive-discovery decision, its hysteresis state, W/C (null when unknown, never 0), occupancy,
    basis and policy, or `evaluated: false` when no evaluator ever ran. Reading never evaluates or writes; a
    store failure propagates so the envelope becomes `unavailable`."""
    from codex_harness.application.discovery_pressure import status
    return status(store)


def scope_label(repository, label=None):
    """ZEUS_MONITOR_SCOPE names what is observed; the default is the repository name. It is a
    label for the page toolbar, not a status or success claim."""
    text = safe_text(label, 200).strip()
    return text or f'repository {Path(repository).resolve().name}'


def collect(service, artifacts, repository, redis_url, containers=None, scope=None, runtime=None, lanes=None):
    """The three legacy sources (`database`, `docker`, `redis`) plus the additive store-backed
    projections; with a runtime directory also `observations` (observatory-001) and with a lane
    resolver also `lane_sessions`. Every envelope fails independently."""
    def sample(callback):
        try:
            return {'status': 'ok', 'observed_at': datetime.now(timezone.utc).isoformat(), 'data': callback()}
        except Exception as exc:
            return {'status': 'unavailable', 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'error': type(exc).__name__, 'data': None}
    def database():
        # Read-only: stored facts plus already persisted observations; nothing is evaluated or written.
        return {**Monitoring(DatabaseFacts(service, artifacts)).snapshot(),
                'measurements': persisted_measurements(service.store)}
    jobs = {'database': database,
            'docker': lambda: docker_facts(repository, containers),
            'redis': lambda: redis_facts(redis_url, service.org.agents),
            # Additive fleet envelope (INV-FLEET-001): same read-only store, fails independently.
            'fleet': lambda: fleet_facts(service.store),
            # Additive research-program envelope (INV-RESEARCH-PROGRAM-001): same read-only store, fails independently.
            'research_programs': lambda: research_program_facts(service.store),
            # Additive portfolio envelope (operating-portfolio-001): same read-only store, fails independently.
            'portfolio': lambda: portfolio_facts(service.store),
            # Additive approved-backlog envelope (INV-FLEET-BACKLOG-001): same read-only store,
            # fails independently, and never ticks the backlog it observes.
            'fleet_backlog': lambda: fleet_backlog_facts(service.store),
            # Additive host-delivery envelope (INV-HOST-DELIVERY-001): same read-only store, fails
            # independently, and never ticks, publishes, merges or switches what it observes.
            'host_delivery': lambda: host_delivery_facts(service.store),
            # Additive worker-session envelope (INV-WORKER-SESSION-001): same read-only store, fails
            # independently, and never reads an archive, resumes, promotes or closes what it observes.
            'worker_sessions': lambda: worker_session_facts(service.store),
            # Additive continuation envelope (INV-CONTINUATION-001): same read-only store, fails
            # independently, and never ticks, dispatches or admits what it observes.
            'continuation': lambda: continuation_facts(service.store),
            # Additive discovery-pressure envelope (INV-DISCOVERY-PRESSURE-001): same read-only store, fails
            # independently, and never evaluates, initializes or writes the pressure row.
            'discovery_pressure': lambda: discovery_pressure_facts(service.store)}
    if runtime is not None:
        jobs['observations'] = lambda: observation_facts(service.store, runtime)
    if lanes is not None:
        # Additive lane-session envelope: every registered lane's own read-only store, each lane
        # failing independently inside it; nothing is written, ticked or resumed.
        jobs['lane_sessions'] = lambda: lane_session_facts(service.store, lanes)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(sample, callback) for name, callback in jobs.items()}
        sources = {name: future.result() for name, future in futures.items()}
    return {'schema': 'harness-monitor.v1', 'collected_at': datetime.now(timezone.utc).isoformat(),
            'scope': {'label': scope_label(repository, scope),
                      'docker': 'named' if containers is not None else 'compose',
                      'containers': list(containers) if containers is not None else None},
            'sources': sources}
