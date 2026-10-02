"""Host-side collection. The HTTP server never imports this Docker/DB adapter.

The collector is a read-only consumer: it reads PostgreSQL facts and already persisted
metric observations, runs only read-only Docker/Redis commands and never puts rows or artifacts.

Layer: adapters
Context: observation
Owns: the monitor's collectors (S9 units U6 and U7): the read-only store, transaction, artifact and service wrappers (`ReadOnlyStore`, `ReadOnlyTransaction`, `ReadOnlyArtifacts`, `ReadOnlyService`, `read_only`), `safe_text`, `container_scope`, `parse_observed`, `persisted_measurements`, `DatabaseFacts`, `audit_progress`, the lane-session constants, the bounded activity projection (`ArtifactReader`, `project_receipt`, `execution_activity`, `lane_artifact_resolver` and the activity constants), `lane_view` and `scope_label`; the Docker and Redis sources (`docker_stats`, `docker_facts`, `redis_facts`), the eight `*_facts` projections (`fleet_facts`, `research_program_facts`, `portfolio_facts`, `fleet_backlog_facts`, `host_delivery_facts`, `worker_session_facts`, `continuation_facts`, `discovery_pressure_facts`), the lock-free lane snapshot store and resolver (`LANE_SNAPSHOT_BEGIN`, `LaneSnapshotStore`, `LaneSnapshotTransaction`, `lane_resolver`), `lane_session_facts` and `collect`
Does not own: the processes, Redis bus, Fleet registration, owner projections and lane DSN it is handed (D1.1: `run_process`, `bus_factory`, `project`, `registered`, `dsn_for` and `CollectorPorts` are injected keyword-only, refused at first use when unwired; S10 composes them), the monitor CLI (S10 `monitor`), the observation projection (`observation.adapters.monitoring_observations`), the worker-session bucket (`execution.application.worker_sessions.BUCKET`, read here as a literal)
Entry points: CONTAINER_NAME, MAX_CONTAINERS, safe_text, ReadOnlyTransaction, ReadOnlyStore, ReadOnlyArtifacts, ReadOnlyService, read_only, container_scope, parse_observed, persisted_measurements, DatabaseFacts, audit_progress, LANE_SESSIONS_SCHEMA, LANE_SESSION_LIMIT, ACTIVE_EXECUTION, UNINSTRUMENTED, ArtifactReader, project_receipt, execution_activity, lane_artifact_resolver, lane_view, scope_label, ACTIVITY_REFS, ACTIVITY_BODY_BYTES, RECENT_TERMINAL_SECONDS, TERMINAL_EXECUTION, ARTIFACT_REF, docker_stats, docker_facts, redis_facts, fleet_facts, research_program_facts, portfolio_facts, fleet_backlog_facts, host_delivery_facts, worker_session_facts, continuation_facts, LANE_SNAPSHOT_BEGIN, LaneSnapshotStore, LaneSnapshotTransaction, lane_resolver, lane_session_facts, discovery_pressure_facts, collect
Contracts: INV-OBSERVATION-001, INV-LANE-SESSIONS-001

Moved from M7 `adapters/monitoring.py` (SOURCE e38aa722) through named rules (S9 batches L2-B5 and L2-B6, A/evidence/rebuild/s9/l2-b6/transcribe.py): R-c0/R-u0 (the import block), R-c1 (the worker-session bucket literal and the execution-domain `status_view` home in `lane_view`), R-u1..R-u6 (OWNER-DECISIONS-S9 D1.1: the injected seams), R-ch (this header); every other statement is M7's, in M7's order. The first paragraph is M7's module docstring.
"""
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.execution.domain.progress_activity import (
    BUILTIN_TOOLS,
    CODEX_ITEM_TYPES,
    fixed_completed_status,
    fixed_completed_type,
    fixed_last_event,
    validate_receipt,
)
from codex_harness.kernel.errors import ContractError, require
from codex_harness.observation.adapters.monitoring_observations import observation_facts
from codex_harness.observation.application.monitoring import Monitoring
from codex_harness.research.domain.council import TASK_STATUSES

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


def docker_stats(names, *, run_process=None):
    if not names:
        return {}
    require(run_process is not None, 'run_process is not wired')
    process = run_process(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *names], timeout=15)
    if process.returncode:
        raise RuntimeError('Docker metrics unavailable')
    stats = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    return {row['Name']: row for row in stats}


def docker_facts(repository, containers=None, *, run_process=None):
    """Compose scope (containers None) is unchanged. Named scope lists exactly the requested
    containers with read-only `docker ps --all` and `docker stats`; the CLI name filter matches
    substrings, so returned names are checked exactly, unrelated containers are dropped and any
    missing requested name makes the whole source unavailable rather than success-empty."""
    if containers is None:
        require(run_process is not None, 'run_process is not wired')
        process = run_process(['docker', 'compose', 'ps', '--all', '--format', 'json'], cwd=repository, timeout=15)
        if process.returncode:
            raise RuntimeError('Docker status unavailable')
        rows = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
        rows = [{'service': row['Service'], 'name': row['Name'], 'state': row['State'], 'image': row['Image']}
                for row in rows]
    else:
        filters = [arg for name in containers for arg in ('--filter', f'name={name}')]
        require(run_process is not None, 'run_process is not wired')
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
    lookup = docker_stats([row['name'] for row in rows if row['state'] == 'running'], run_process=run_process)
    return [{**row, 'cpu': lookup.get(row['name'], {}).get('CPUPerc'),
             'memory': lookup.get(row['name'], {}).get('MemUsage')} for row in rows]


def redis_facts(url, agents, *, bus_factory=None):
    require(bus_factory is not None, 'bus_factory is not wired')
    bus = bus_factory(url)
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


def fleet_facts(store, *, project=None):
    """INV-FLEET-001 projection (`urn:zeus:fleet-status:1`) from PG reads only: identities,
    states, codes and counts; never manifests, paths, schemas, DSNs or raw errors. Registration
    is not service health, and `updated_at` is the last recorded fact, not liveness."""
    require(project is not None, 'fleet projection is not wired')
    return project(store)


def research_program_facts(store, *, project=None):
    """INV-RESEARCH-PROGRAM-001 projection (`urn:zeus:research-program-monitor:1`) from store reads
    only: program states, cycle/adoption counts, outcomes and stop reasons for at most 20 programs
    with `truncated` explicit; never configs, feed bodies, paths or raw errors."""
    require(project is not None, 'research_program projection is not wired')
    return project(store)


def portfolio_facts(store, *, project=None):
    """Operating portfolio projection (`urn:zeus:portfolio-status:1`) from store reads only: the
    owner's goals, their criterion acceptance records, the bound jobs' identities/states/codes and
    the failure investigation queue. Never manifests, objectives, paths, credentials or raw errors.
    A candidate is a coarse triage family, not a confirmed cause, and an acceptance record is an
    owner statement, not proof that the whole source was absorbed. A store failure propagates so
    the envelope becomes `unavailable` rather than an empty portfolio."""
    require(project is not None, 'portfolio projection is not wired')
    return project(store)


def fleet_backlog_facts(store, *, project=None):
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
    require(project is not None, 'fleet_backlog projection is not wired')
    return project(store)


def host_delivery_facts(store, *, project=None):
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
    require(project is not None, 'host_delivery projection is not wired')
    return project(store)


def worker_session_facts(store, *, project=None):
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
    require(project is not None, 'worker_session projection is not wired')
    return project(store)


def continuation_facts(store, *, project=None):
    """INV-CONTINUATION-001 projection (`urn:zeus:continuation-status:1`) from store reads only:
    registered policies (id, enabled, digest, pin), every intent's routing-table route, state,
    cause code, next owner and next action, evidence references and predecessor/successor links,
    per-state counts and the held families. Never a manifest, an objective, review text, a
    transcript, a path or a credential; nothing is ticked, dispatched or admitted, and a store
    failure propagates so the envelope becomes `unavailable` rather than an empty list."""
    require(project is not None, 'continuation projection is not wired')
    return project(store)


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


def lane_resolver(host_dsn, store_factory=None, *, dsn_for=None):
    """`lane -> read-only store` over the lane's own schema through the SAME `lane_dsn` path the Fleet
    launcher and the owner actions use (no second registry). Cached per (lane id, schema), so a
    changed registration never reuses another schema's store; nothing is created here. The default
    store is the lock-free `LaneSnapshotStore`; `store_factory(dsn, schema)` is injectable."""
    require(dsn_for is not None, 'dsn_for is not wired')
    store_factory = store_factory or LaneSnapshotStore
    cache = {}

    def resolve(lane):
        key = (lane['id'], lane['schema'])
        if key not in cache:
            cache[key] = ReadOnlyStore(store_factory(dsn_for(host_dsn, lane['schema']), lane['schema']))
        return cache[key]
    return resolve


# ----- S2a activity pane (INV-LANE-SESSIONS-001 activity; FLEET-S2-SPEC) ---------------------------------------
# The executor keeps only progress receipts (Codex item/completed and token updates; Claude session_started,
# tool_completed, permission_denied, result), at most six per task. This projection shows exactly those retained
# receipts through a fixed allowlist: it is an emitted-event log, never a terminal or a screen, and a Claude tool
# completion carries no tool name.
ACTIVITY_REFS = 6
ACTIVITY_BODY_BYTES = 65_536
RECENT_TERMINAL_SECONDS = 600
# Only a KNOWN terminal execution status opens the completion window; an unknown, missing or new status is
# `not_selected` with no read (FLEET-S2-SPEC §5).
TERMINAL_EXECUTION = TASK_STATUSES - ACTIVE_EXECUTION
ARTIFACT_REF = re.compile(r'^sha256:([0-9a-f]{64})$')
CLAUDE_LABELS = frozenset({'tool_started', 'tool_completed', 'session_started', 'permission_denied', 'message',
                           'result'})
CODEX_LABELS = {'item/completed': 'item_completed', 'thread/tokenUsage/updated': 'token_usage_updated'}
# CODEX_ITEM_TYPES and BUILTIN_TOOLS (display labels only, never grants) are owned by domain/progress_activity.
PLAIN_STATUSES = frozenset({'started', 'completed', 'failed', 'denied', 'emitted'})
ENVELOPE_KEYS = frozenset({'event', 'malformed', 'defect', 'previous'})


def _optional_strings(mapping, keys) -> bool:
    """Every consulted field is a string or absent; anything else makes the receipt `invalid_shape` before any
    vocabulary lookup, so a list or object can never raise out of one entry."""
    return all(mapping.get(key) is None or isinstance(mapping.get(key), str) for key in keys)


class ArtifactReader:
    """Bounded, integrity-checked reads from ONE existing lane artifact root. Unlike FileArtifacts it never
    creates a directory, locks, touches or writes, and it refuses symlinks and non-regular files before any
    read, so a crafted entry can neither escape the root nor block on a FIFO. Each read answers a fixed code."""

    def __init__(self, root):
        self.root = Path(root)

    def available(self) -> bool:
        return self.root.is_dir() and not self.root.is_symlink()

    def read(self, reference):
        """(state, error_code, text): ok with the text, or unavailable/unreadable with a fixed code."""
        import hashlib
        import os
        import stat as stat_module
        match = ARTIFACT_REF.fullmatch(reference) if isinstance(reference, str) else None
        if match is None:
            return 'unreadable', 'invalid_ref', None
        if not self.available():
            return 'unavailable', 'runtime_unavailable', None
        path = self.root / (match[1] + '.txt')
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return 'unavailable', 'missing_artifact', None
        except OSError:
            return 'unreadable', 'io_error', None
        if not stat_module.S_ISREG(info.st_mode):
            return 'unreadable', 'io_error', None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                data = stream.read(ACTIVITY_BODY_BYTES + 1)
        except OSError:
            return 'unreadable', 'io_error', None
        if len(data) > ACTIVITY_BODY_BYTES:
            return 'unreadable', 'too_large', None
        if hashlib.sha256(data).hexdigest() != match[1]:
            return 'unreadable', 'integrity_failure', None
        try:
            return 'ok', None, data.decode('utf-8')
        except UnicodeDecodeError:
            return 'unreadable', 'invalid_json', None


def _strict_json(text):
    def pairs(items):
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate key')
        return dict(items)

    def constant(name):
        raise ValueError('non-finite number')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _epoch_ms(value):
    if type(value) is int and 0 < value < 10 ** 14:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return None


def project_receipt(text) -> dict:
    """The allowlisted view of ONE runtime-event receipt: a NEW small object, never a redacted copy. Only fixed
    vocabularies, a built-in tool name, validated epoch times and the malformed flag survive; payloads, text,
    commands, paths, ids, subtypes and unknown keys are dropped."""
    empty = {'event_label': 'malformed', 'tool_name': None, 'item_type': None, 'status': None, 'occurred_at': None,
             'malformed': True}
    try:
        body = _strict_json(text)
    except (ValueError, RecursionError):
        return {**empty, 'state': 'unreadable', 'error_type': 'invalid_json'}
    if not isinstance(body, dict) or not set(body) <= ENVELOPE_KEYS or type(body.get('malformed')) is not bool:
        return {**empty, 'state': 'malformed', 'error_type': 'invalid_shape'}
    event = body.get('event')
    if body['malformed'] or not isinstance(event, dict):
        return {**empty, 'state': 'malformed', 'error_type': None}
    view = {'state': 'ok', 'error_type': None, 'event_label': 'unknown', 'tool_name': None, 'item_type': None,
            'status': None, 'occurred_at': None, 'malformed': False}
    if event.get('provider') == 'claude-code-cli':
        if not _optional_strings(event, ('type', 'status', 'tool')):
            return {**empty, 'state': 'malformed', 'error_type': 'invalid_shape'}
        kind, status = event.get('type'), event.get('status')
        if kind in CLAUDE_LABELS:
            view['event_label'] = kind
        if kind == 'tool_started' and event.get('tool') in BUILTIN_TOOLS:
            view['tool_name'] = event['tool']
        if kind == 'result':
            view['status'] = ('success' if status == 'success'
                              else 'error' if isinstance(status, str) and status.startswith('error') else 'unknown')
        elif status in PLAIN_STATUSES:
            view['status'] = status
        elif status is not None:
            view['status'] = 'unknown'
        view['occurred_at'] = _epoch_ms(event.get('occurred_at_ms'))
    elif isinstance(event.get('method'), str):
        view['event_label'] = CODEX_LABELS.get(event['method'], 'unknown')
        params = event.get('params') if isinstance(event.get('params'), dict) else {}
        item = params.get('item') if isinstance(params.get('item'), dict) else None
        if item is not None and not _optional_strings(item, ('type', 'status')):
            return {**empty, 'state': 'malformed', 'error_type': 'invalid_shape'}
        if item is not None:
            view['item_type'] = item.get('type') if item.get('type') in CODEX_ITEM_TYPES else 'unknown'
            status = item.get('status')
            view['status'] = status if status in ('completed', 'failed') else (None if status is None else 'unknown')
        for candidate in (params.get('completedAtMs'), (item or {}).get('completedAtMs'), event.get('emittedAtMs')):
            moment = _epoch_ms(candidate)
            if moment is not None:
                view['occurred_at'] = moment
                break
    return view


def _aware(value):
    moment = parse_observed(value)
    return moment.astimezone(timezone.utc) if moment is not None else None


def execution_activity(row, progress, reader, now, recent_terminal_seconds=RECENT_TERMINAL_SECONDS):
    """(activity_status, activity) for one lane row. Membership is ONLY this row's bound ring: the compact
    `activity_recent` when it is synchronized with the row's progress sequence (S2b, FLEET-S2B-SPEC §4), otherwise
    the legacy `progress.recent`; the last six either way, never merged and never backfilled. `last_record`
    annotates a legacy member but never widens it, and `previous`/`raw_ref` links are never followed, so no
    other artifact can be read through this row. A legacy entry has sequence and collection time only as the
    `last_record`; a compact entry carries its own."""
    status = row.get('status')
    if not isinstance(status, str):
        selected = False
    elif status in ACTIVE_EXECUTION:
        selected = True
    elif status in TERMINAL_EXECUTION:
        completed = _aware(row.get('completed_at'))
        selected = completed is not None and 0 <= (now - completed).total_seconds() <= recent_terminal_seconds
    else:
        selected = False
    if not selected:
        return 'not_selected', []
    if progress is None:
        return 'empty', []
    lineage = (progress.get('generation'), progress.get('attempt'))
    if not all(type(value) is int for value in lineage) or lineage != (row.get('generation'), row.get('attempt')):
        return 'lineage_unconfirmed', []
    compact = _compact_selected(progress)
    source = 'activity_receipt' if compact else 'progress_receipt'
    recent = progress.get('activity_recent' if compact else 'recent')
    refs = recent[-ACTIVITY_REFS:] if isinstance(recent, list) else []
    if not refs:
        malformed = progress.get('malformed_events')
        return ('malformed_not_in_recent' if type(malformed) is int and malformed > 0 else 'empty'), []
    if reader is None:
        return 'unavailable', [_failed_entry(None, source, 'unavailable', 'runtime_unavailable')]
    if compact:
        return _compact_activity(row, refs, reader)
    last = progress.get('last_record')
    sequence = progress.get('sequence')
    collected = _aware(progress.get('collected_at'))
    activity, seen = [], set()
    for reference in refs:
        valid = isinstance(reference, str) and ARTIFACT_REF.fullmatch(reference) is not None
        if not valid:
            activity.append(_failed_entry(None, 'progress_receipt', 'unreadable', 'invalid_ref'))
            continue
        if reference in seen:
            continue
        seen.add(reference)
        # Each selected ref fails on its own with a fixed code; no exception text leaves this entry.
        try:
            state, code, text = reader.read(reference)
        except Exception:
            state, code, text = 'unreadable', 'io_error', None
        if state != 'ok':
            entry = {'state': state, 'error_type': code, 'event_label': None, 'tool_name': None, 'item_type': None,
                     'status': None, 'occurred_at': None, 'malformed': None}
        else:
            try:
                entry = project_receipt(text)
            except Exception:
                entry = {'state': 'malformed', 'error_type': 'invalid_shape', 'event_label': 'malformed',
                         'tool_name': None, 'item_type': None, 'status': None, 'occurred_at': None,
                         'malformed': True}
        is_last = reference == last and entry['state'] == 'ok'
        activity.append({'receipt_ref': reference, 'source': 'progress_receipt', **entry, **COMPACT_ONLY,
                         'sequence': sequence if is_last and type(sequence) is int and sequence > 0 else None,
                         'collected_at': collected.isoformat() if is_last and collected is not None else None})
    return ('ok' if any(entry['state'] == 'ok' for entry in activity) else 'unavailable'), activity


# Keys only a compact entry fills; a legacy entry carries them as null (additive, FLEET-S2B-SPEC §4).
COMPACT_ONLY = {'activity_sequence': None, 'generation': None, 'attempt': None, 'raw_ref': None}


def _failed_entry(reference, source, state, code):
    return {'receipt_ref': reference, 'source': source, 'state': state, 'error_type': code, 'event_label': None,
            'tool_name': None, 'item_type': None, 'status': None, 'sequence': None, 'occurred_at': None,
            'collected_at': None, 'malformed': None, **COMPACT_ONLY}


def _compact_selected(progress) -> bool:
    """D11: the compact ring is shown only when it is non-empty and its watermark equals the row's progress
    sequence (0 only when absent); exact integers, so a bool never passes for 0/1. Anything else is the
    legacy path: an older producer ran after it, or a compact write was dropped."""
    ring, watermark = progress.get('activity_recent'), progress.get('activity_progress_sequence')
    sequence = progress.get('sequence', 0)
    return (isinstance(ring, list) and len(ring) > 0 and type(watermark) is int and watermark >= 0
            and type(sequence) is int and watermark == sequence)


def _compact_activity(row, refs, reader):
    """Compact entries: each member read once, bounded and integrity-checked, validated against the exact
    receipt contract and bound to THIS execution; `raw_ref` is never followed. Every failure stays listed with a
    fixed code and never falls back to the raw ring (that would conceal corruption)."""
    activity, seen = [], set()
    for reference in refs:
        if not (isinstance(reference, str) and ARTIFACT_REF.fullmatch(reference)):
            activity.append(_failed_entry(None, 'activity_receipt', 'unreadable', 'invalid_ref'))
            continue
        if reference in seen:
            continue
        seen.add(reference)
        try:
            state, code, text = reader.read(reference)
        except Exception:
            state, code, text = 'unreadable', 'io_error', None
        if state != 'ok':
            activity.append(_failed_entry(reference, 'activity_receipt', state, code))
            continue
        try:
            parsed = _strict_json(text)
        except (ValueError, RecursionError):
            activity.append({**_failed_entry(reference, 'activity_receipt', 'unreadable', 'invalid_json'),
                             'event_label': 'malformed', 'malformed': True})
            continue
        try:  # ActivityInvalid is a ContractError (a ValueError), so it is caught apart from the JSON parse
            document = validate_receipt(parsed)
        except Exception:
            activity.append({**_failed_entry(reference, 'activity_receipt', 'malformed', 'invalid_shape'),
                             'event_label': 'malformed', 'malformed': True})
            continue
        if document['execution'] != row.get('id'):
            activity.append(_failed_entry(reference, 'activity_receipt', 'unreadable', 'binding_mismatch'))
            continue
        activity.append({'receipt_ref': reference, 'source': 'activity_receipt', 'state': 'ok', 'error_type': None,
                         'event_label': document['event_label'], 'tool_name': document['tool_name'],
                         'item_type': document['item_type'], 'status': document['status'],
                         'sequence': document['progress_sequence'], 'occurred_at': document['occurred_at'],
                         'collected_at': document['collected_at'], 'malformed': False,
                         'activity_sequence': document['activity_sequence'], 'generation': document['generation'],
                         'attempt': document['attempt'], 'raw_ref': document['raw_ref']})
    return ('ok' if any(entry['state'] == 'ok' for entry in activity) else 'unavailable'), activity


def lane_artifact_resolver():
    """`lane -> ArtifactReader` over the lane's REGISTERED runtime `artifacts` directory (never a path found in an
    event, progress row or request), cached per (lane id, schema, runtime) so a changed registration never
    reuses another root. Nothing is created."""
    cache = {}

    def resolve(lane):
        key = (lane['id'], lane['schema'], lane['runtime'])
        if key not in cache:
            cache[key] = ArtifactReader(Path(lane['runtime']) / 'artifacts')
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
            # Fixed vocabularies only (S2b D10): no provider subtype or unknown method text reaches the view.
            'last_event': fixed_last_event(progress.get('last_event')),
            'last_completed': {**{k: completed.get(k) for k in ('sequence', 'occurred_at', 'evidence')},
                               'type': fixed_completed_type(completed.get('type')),
                               'status': fixed_completed_status(completed.get('status'))} if completed else None,
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


def lane_view(store, reader=None, now=None, recent_terminal_seconds=RECENT_TERMINAL_SECONDS):
    """One lane's executions from ONE read transaction of its own store: task and decision rows, the
    operation that names them, their progress, invocation reservations and durable worker session.
    Rows are keyed by the lane-local id; the caller adds the lane, so equal ids in two lanes stay
    distinct. Never objectives, prompts, transcripts, tool text, worktrees, context refs or raw errors."""
    SESSIONS = 'worker_sessions'  # R-c1: the V9 literal of execution.application.worker_sessions.BUCKET (an observation adapter may not import it)
    from codex_harness.execution.domain.worker_sessions import status_view
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
    shown = executions[:LANE_SESSION_LIMIT]
    # Artifact reads happen AFTER the store snapshot, only for the rows shown (FLEET-S2-SPEC §5).
    rows_by_key = {(kind, row['id']): row for kind, bucket in (('task', 'tasks'), ('decision', 'decisions_pending'))
                   for row in rows[bucket]}
    moment = now or datetime.now(timezone.utc)
    for view in shown:
        # Activity is additive: a row it cannot project is `unavailable`, never a lost lane or session fact.
        try:
            status, items = execution_activity(rows_by_key[(view['kind'], view['id'])], progress.get(view['id']),
                                               reader, moment, recent_terminal_seconds)
        except Exception:
            status, items = 'unavailable', []
        view['activity_status'], view['activity'] = status, items
        # Recorded activity drops (S2b): a partial persisted count, null when this producer never wrote one.
        dropped = (progress.get(view['id']) or {}).get('activity_dropped')
        view['activity_dropped'] = dropped if type(dropped) is int and dropped >= 0 else None
    return {'executions': shown, 'total': len(executions),
            'truncated': len(executions) > LANE_SESSION_LIMIT,
            'counts': dict(Counter(f"{view['kind']}:{view['status']}" for view in executions)),
            'invocations': dict(Counter(row.get('status') for row in rows['invocation_reservations'])),
            'worker_sessions': dict(Counter(view['state'] for view in sessions.values()))}


def lane_session_facts(store, resolve, artifacts=None, now=None, *, registered=None):
    """INV-LANE-SESSIONS-001 (`urn:zeus:lane-sessions:1`): every REGISTERED lane's executions, read
    from the lane's own store (the control store holds none of them). Each lane fails independently as `unavailable` with its
    error type only, never as an empty ok lane. An unregistered Fleet is `registered: false` with no
    lane (as the `fleet` source reports it); any other store failure propagates so the envelope is
    `unavailable`. `coverage.uninstrumented` names what this source cannot see. A collected row is
    a durable-record projection only: never evidence of useful progress, acceptance or delivery."""
    require(registered is not None, 'registered is not wired')
    try:
        lanes = registered(store)['config']['lanes']
    except FleetRefused as exc:
        if exc.reason_code != 'unregistered':
            raise
        lanes = None
    views = []
    for lane in lanes or ():
        observed = datetime.now(timezone.utc).isoformat()
        try:
            view = {'status': 'ok', **lane_view(resolve(lane), artifacts(lane) if artifacts else None, now)}
        except Exception as exc:
            view = {'status': 'unavailable', 'error': type(exc).__name__}
        views.append({'lane': lane['id'], 'team': lane.get('team'), 'observed_at': observed, **view})
    observed = sum(view['status'] == 'ok' for view in views)
    return {'schema': LANE_SESSIONS_SCHEMA, 'registered': lanes is not None,
            'authority': 'durable-record projection; not progress, acceptance or delivery evidence',
            'lanes': views,
            'coverage': {'lanes_registered': len(lanes or ()), 'lanes_observed': observed,
                         'lanes_unavailable': len(views) - observed, 'uninstrumented': [UNINSTRUMENTED]}}


def discovery_pressure_facts(store, *, project=None):
    """INV-DISCOVERY-PRESSURE-001 projection (`urn:zeus:discovery-pressure:1`) from store reads only: the
    recorded proactive-discovery decision, its hysteresis state, W/C (null when unknown, never 0), occupancy,
    basis and policy, or `evaluated: false` when no evaluator ever ran. Reading never evaluates or writes; a
    store failure propagates so the envelope becomes `unavailable`."""
    require(project is not None, 'discovery_pressure projection is not wired')
    return project(store)


def scope_label(repository, label=None):
    """ZEUS_MONITOR_SCOPE names what is observed; the default is the repository name. It is a
    label for the page toolbar, not a status or success claim."""
    text = safe_text(label, 200).strip()
    return text or f'repository {Path(repository).resolve().name}'


def collect(service, artifacts, repository, redis_url, containers=None, scope=None, runtime=None, lanes=None,
            lane_artifacts=None, *, ports=None):
    """The three legacy sources (`database`, `docker`, `redis`) plus the additive store-backed
    projections; with a runtime directory also `observations` (observatory-001) and with a lane
    resolver also `lane_sessions`. Every envelope fails independently."""
    require(ports is not None, 'collector ports are not wired')
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
            'docker': lambda: docker_facts(repository, containers, run_process=ports.run_process),
            'redis': lambda: redis_facts(redis_url, service.org.agents, bus_factory=ports.bus_factory),
            # Additive fleet envelope (INV-FLEET-001): same read-only store, fails independently.
            'fleet': lambda: fleet_facts(service.store, project=ports.fleet),
            # Additive research-program envelope (INV-RESEARCH-PROGRAM-001): same read-only store, fails independently.
            'research_programs': lambda: research_program_facts(service.store, project=ports.research_program),
            # Additive portfolio envelope (operating-portfolio-001): same read-only store, fails independently.
            'portfolio': lambda: portfolio_facts(service.store, project=ports.portfolio),
            # Additive approved-backlog envelope (INV-FLEET-BACKLOG-001): same read-only store,
            # fails independently, and never ticks the backlog it observes.
            'fleet_backlog': lambda: fleet_backlog_facts(service.store, project=ports.fleet_backlog),
            # Additive host-delivery envelope (INV-HOST-DELIVERY-001): same read-only store, fails
            # independently, and never ticks, publishes, merges or switches what it observes.
            'host_delivery': lambda: host_delivery_facts(service.store, project=ports.host_delivery),
            # Additive worker-session envelope (INV-WORKER-SESSION-001): same read-only store, fails
            # independently, and never reads an archive, resumes, promotes or closes what it observes.
            'worker_sessions': lambda: worker_session_facts(service.store, project=ports.worker_session),
            # Additive continuation envelope (INV-CONTINUATION-001): same read-only store, fails
            # independently, and never ticks, dispatches or admits what it observes.
            'continuation': lambda: continuation_facts(service.store, project=ports.continuation),
            # Additive discovery-pressure envelope (INV-DISCOVERY-PRESSURE-001): same read-only store, fails
            # independently, and never evaluates, initializes or writes the pressure row.
            'discovery_pressure': lambda: discovery_pressure_facts(service.store, project=ports.discovery_pressure)}
    if runtime is not None:
        jobs['observations'] = lambda: observation_facts(service.store, runtime)
    if lanes is not None:
        # Additive lane-session envelope: every registered lane's own read-only store, each lane
        # failing independently inside it; nothing is written, ticked or resumed.
        jobs['lane_sessions'] = lambda: lane_session_facts(service.store, lanes, lane_artifacts, registered=ports.registered)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(sample, callback) for name, callback in jobs.items()}
        sources = {name: future.result() for name, future in futures.items()}
    return {'schema': 'harness-monitor.v1', 'collected_at': datetime.now(timezone.utc).isoformat(),
            'scope': {'label': scope_label(repository, scope),
                      'docker': 'named' if containers is not None else 'compose',
                      'containers': list(containers) if containers is not None else None},
            'sources': sources}
