"""Host-side collection. The HTTP server never imports this Docker/DB adapter."""
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.commands import run_process
from codex_harness.application.measurements import Measurements
from codex_harness.application.monitoring import Monitoring


def safe_text(value, limit=1200):
    text = str(value or '')
    text = re.sub(r'([a-z]+://)[^\s/@]+:[^\s/@]+@', r'\1[redacted]@', text)
    text = re.sub(r'(?i)(Bearer\s+|(?:api[_-]?key|password|token)\s*[=:]\s*)\S+', r'\1[redacted]', text)
    return text[:limit]


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


def docker_facts(repository):
    process = run_process(['docker', 'compose', 'ps', '--all', '--format', 'json'], cwd=repository, timeout=15)
    if process.returncode:
        raise RuntimeError('Docker status unavailable')
    rows = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    stats = []
    names = [row['Name'] for row in rows if row.get('State') == 'running']
    if names:
        process = run_process(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *names], timeout=15)
        if process.returncode:
            raise RuntimeError('Docker metrics unavailable')
        stats = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    lookup = {row['Name']: row for row in stats}
    return [{'service': row['Service'], 'name': row['Name'], 'state': row['State'], 'image': row['Image'],
             'cpu': lookup.get(row['Name'], {}).get('CPUPerc'),
             'memory': lookup.get(row['Name'], {}).get('MemUsage')} for row in rows]


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


def collect(service, artifacts, repository, redis_url):
    def sample(callback):
        try:
            return {'status': 'ok', 'observed_at': datetime.now(timezone.utc).isoformat(), 'data': callback()}
        except Exception as exc:
            return {'status': 'unavailable', 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'error': type(exc).__name__, 'data': None}
    def database():
        revision = run_process(['git', 'rev-parse', 'HEAD'], cwd=repository, timeout=15)
        if revision.returncode:
            raise RuntimeError('Measurement revision unavailable')
        measurements = Measurements(service.store, artifacts).collect(revision.stdout.strip())
        return {**Monitoring(DatabaseFacts(service, artifacts)).snapshot(), 'measurements': measurements}
    jobs = {'database': database,
            'docker': lambda: docker_facts(repository),
            'redis': lambda: redis_facts(redis_url, service.org.agents)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(sample, callback) for name, callback in jobs.items()}
        sources = {name: future.result() for name, future in futures.items()}
    return {'schema': 'harness-monitor.v1', 'collected_at': datetime.now(timezone.utc).isoformat(), 'sources': sources}
