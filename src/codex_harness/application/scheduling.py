from __future__ import annotations

import time

from codex_harness.domain.model import envelope, utcnow
from codex_harness.domain.policy import POLICY


def schedule_research(service, now: float | None = None) -> int:
    slot = int((time.time() if now is None else now) // (POLICY.research_interval_hours * 3600))
    created = 0
    with service.store.transaction() as tx:
        for source in ("github", "geeknews"):
            key = f"research:{source}:{slot}"
            if tx.get("schedule", key):
                continue
            message = envelope("task.assign", "lead:research", "worker:" + source, "research",
                               {"source": source}, key)
            service.org.authorize(message)
            tx.put("outbox", message["message_id"], {"message": message, "sent": False})
            tx.put("schedule", key, {"id": key, "at": utcnow()})
            created += 1
    return created + schedule_audits(service)


def schedule_audits(service, audit_id: str | None = None) -> int:
    """One durable assignment per partition generation; unfinished scope survives budgets.

    `audit_id` narrows ONE pass to the assignments of that audit (its partitions, proposal and
    adoption). Discovery and acquisition are not bound to an audit, so a narrowed pass leaves them
    to the existing global pass; nothing else changes. The default None is the existing behaviour,
    including the generation deduplication every caller relies on.
    """
    from codex_harness.application.releases import Releases
    from codex_harness.domain.model import digest
    Releases(service.store, service.org).reconcile_audits()
    created = 0
    with service.store.transaction() as tx:
        control = tx.get('research_control', 'activation') or {}
        if control.get('status') != 'active':
            return 0
        if audit_id is None:
            for discovery in tx.scan('research_discoveries'):
                key = 'map:' + discovery['id']
                if tx.get('schedule', key):
                    continue
                message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_discovery',
                                   {'discovery_id': discovery['id']}, key)
                service.org.authorize(message)
                tx.put('outbox', message['message_id'], {'message': message, 'sent': False})
                tx.put('schedule', key, {'id': key, 'task_id': message['message_id'], 'at': utcnow()})
                created += 1
            for row in sorted(tx.scan('research_backlog'), key=lambda r: r['priority']):
                if row.get('audit_id'):
                    continue
                key = 'acquire:' + row['id']
                if tx.get('schedule', key):
                    continue
                message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_acquire',
                                   {'backlog_id': row['id'], 'repository': row['repository'],
                                    'commit': row['revision']}, key)
                service.org.authorize(message)
                tx.put('outbox', message['message_id'], {'message': message, 'sent': False})
                tx.put('schedule', key, {'id': key, 'task_id': message['message_id'], 'at': utcnow()})
                created += 1
        for partition in tx.scan('research_partitions'):
            if audit_id is not None and partition['audit_id'] != audit_id:
                continue
            if not (partition['remaining_paths'] or partition['remaining_subsystems']
                    or partition['open_questions']):
                continue
            # Do not overlap a predecessor whose checkpoint committed before task completion.
            prior = [r for r in tx.scan('schedule') if r.get('partition_id') == partition['partition_id']]
            if any((tx.get('tasks', r['task_id']) or {}).get('status', 'queued')
                   in {'queued', 'running', 'retry'} for r in prior):
                continue
            key = 'audit:' + digest({'partition': partition['partition_id'],
                                     'generation': partition['generation']})
            if tx.get('schedule', key):
                continue
            message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
                {'audit_id': partition['audit_id'], 'partition_id': partition['partition_id'],
                 'generation': partition['generation']}, key)
            service.org.authorize(message)
            tx.put('outbox', message['message_id'], {'message': message, 'sent': False})
            tx.put('schedule', key, {'id': key, 'task_id': message['message_id'],
                'partition_id': partition['partition_id'], 'at': utcnow()})
            created += 1
        for audit in tx.scan('research_audits'):
            if audit_id is not None and audit['id'] != audit_id:
                continue
            partitions = [p for p in tx.scan('research_partitions') if p['audit_id'] == audit['id']]
            if not partitions or any(p['remaining_paths'] or p['remaining_subsystems']
                                     or p['open_questions'] for p in partitions):
                continue
            key = 'propose:' + digest(partitions)
            if tx.get('schedule', key):
                continue
            message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_propose',
                               {'audit_id': audit['id']}, key)
            service.org.authorize(message)
            tx.put('outbox', message['message_id'], {'message': message, 'sent': False})
            tx.put('schedule', key, {'id': key, 'task_id': message['message_id'], 'at': utcnow()})
            created += 1
        from codex_harness.application.audit_gate import require_adoption
        from codex_harness.domain.model import ContractError
        for approval in tx.scan('research_approvals'):
            if audit_id is not None and approval['audit_id'] != audit_id:
                continue
            key = 'adopt:' + approval['binding']
            if tx.get('schedule', key):
                continue
            details = {'audit_id': approval['audit_id'], 'audit_approval': approval['binding'],
                       'proposal': approval['proposal'], 'importance': 'important'}
            try:
                require_adoption(tx, details)
            except ContractError:
                continue
            message = envelope('task.assign', 'conductor', 'lead:improvement', 'plan', details, key)
            service.org.authorize(message)
            tx.put('outbox', message['message_id'], {'message': message, 'sent': False})
            tx.put('schedule', key, {'id': key, 'task_id': message['message_id'], 'at': utcnow()})
            created += 1
    return created
