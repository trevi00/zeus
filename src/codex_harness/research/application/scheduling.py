"""Research scheduler: one durable `task.assign` per research slot, discovery, acquisition, partition generation, proposal and adoption.

Layer: application
Context: research
Owns: the scheduling use cases schedule_research and schedule_audits (the `schedule` deduplication keys; the assignments they publish)
Does not own: the outbox bucket body (coordination: Outbox.append, injected as `outbox`), the release reconciliation (review: Releases.reconcile_audits, injected as `reconcile_audits`), the adoption gate (research audit_gate), the partition, discovery, backlog, audit, approval and task rows it reads
Entry points: schedule_research, schedule_audits
Contracts: INV-RESEARCH-004, INV-AUDIT-REPAIR-001, INV-DISCOVERY-PRESSURE-001

Moved from M7 `application/scheduling.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §19 V23, A/evidence/rebuild/s8/scheduling-move/transcribe.py): R-sc0 (each name from the target home of the module that defines it; the lazy `Releases` import is removed), R-sc1 (both functions take the keyword-only `outbox` and `reconcile_audits` ports, and `schedule_research` passes both to `schedule_audits`), R-sc2 (the lazy `Releases(...).reconcile_audits()` becomes the injected `reconcile_audits()` after one added `require`, in the same place, before the transaction), R-sc3 (the six outbox puts (DESIGN-s8 §19 counts five: one is in `schedule_research`) become `_append(outbox, tx, message)` in place; `_append` requires the port at first use); every other body is M7's.
"""
from __future__ import annotations

import time

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.message import envelope
from codex_harness.kernel.policy import POLICY


def _append(outbox, tx, message):
    # V23 R-sc3: the port is required at first use (inside the transaction, which rolls back), so a pass that schedules
    # nothing never needs it, as M7 never touched the outbox then
    require(outbox is not None, 'Outbox is not wired')
    outbox.append(tx, message)


def schedule_research(service, now: float | None = None, *, outbox=None, reconcile_audits=None) -> int:
    slot = int((time.time() if now is None else now) // (POLICY.research_interval_hours * 3600))
    created = 0
    with service.store.transaction() as tx:
        for source in ("github", "geeknews"):
            key = f"research:{source}:{slot}"
            if tx.get("schedule", key):
                continue
            # INV-DISCOVERY-PRESSURE-001: a periodic feed fetch is proactive discovery by definition; it states
            # so and is gated by pressure at fetch time, never refused for a missing intent.
            message = envelope("task.assign", "lead:research", "worker:" + source, "research",
                               {"source": source, "intent": "proactive"}, key)
            service.org.authorize(message)
            _append(outbox, tx, message)
            tx.put("schedule", key, {"id": key, "at": utcnow()})
            created += 1
    return created + schedule_audits(service, outbox=outbox, reconcile_audits=reconcile_audits)


def schedule_audits(service, audit_id: str | None = None, *, outbox=None, reconcile_audits=None) -> int:
    """One durable assignment per partition generation; unfinished scope survives budgets.

    `audit_id` narrows ONE pass to the assignments of that audit (its partitions, proposal and
    adoption). Discovery and acquisition are not bound to an audit, so a narrowed pass leaves them
    to the existing global pass; nothing else changes. The default None is the existing behaviour,
    including the generation deduplication every caller relies on.

    A bounded correction admitted by `application.audit_repair` (INV-AUDIT-REPAIR-001) writes its
    own `schedule` row carrying the same `partition_id`, so the overlap guard below sees it exactly
    like any other unfinished assignment of that partition and this pass adds no second one. This
    function itself is unchanged: it never creates, prefers, reorders or retries a correction.
    """
    from codex_harness.kernel.ids import digest
    require(reconcile_audits is not None, 'Release reconciliation is not wired')
    reconcile_audits()
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
                _append(outbox, tx, message)
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
                _append(outbox, tx, message)
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
            _append(outbox, tx, message)
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
            _append(outbox, tx, message)
            tx.put('schedule', key, {'id': key, 'task_id': message['message_id'], 'at': utcnow()})
            created += 1
        from codex_harness.kernel.errors import ContractError
        from codex_harness.research.application.audit_gate import require_adoption
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
            _append(outbox, tx, message)
            tx.put('schedule', key, {'id': key, 'task_id': message['message_id'], 'at': utcnow()})
            created += 1
    return created
