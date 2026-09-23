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


def scope_label(repository, label=None):
    """ZEUS_MONITOR_SCOPE names what is observed; the default is the repository name. It is a
    label for the page toolbar, not a status or success claim."""
    text = safe_text(label, 200).strip()
    return text or f'repository {Path(repository).resolve().name}'


def collect(service, artifacts, repository, redis_url, containers=None, scope=None, runtime=None):
    """The three legacy sources (`database`, `docker`, `redis`) plus the additive store-backed
    projections; with a runtime directory also `observations` (observatory-001). Every envelope
    fails independently."""
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
            'host_delivery': lambda: host_delivery_facts(service.store)}
    if runtime is not None:
        jobs['observations'] = lambda: observation_facts(service.store, runtime)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(sample, callback) for name, callback in jobs.items()}
        sources = {name: future.result() for name, future in futures.items()}
    return {'schema': 'harness-monitor.v1', 'collected_at': datetime.now(timezone.utc).isoformat(),
            'scope': {'label': scope_label(repository, scope),
                      'docker': 'named' if containers is not None else 'compose',
                      'containers': list(containers) if containers is not None else None},
            'sources': sources}
