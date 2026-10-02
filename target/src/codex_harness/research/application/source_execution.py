"""Fenced infrastructure requests for source execution; source agents do not own Docker.

Layer: application
Context: research
Owns: the fenced queue of source execution requests (request, claim, result, complete); buckets source_execution_requests, source_execution_history (only this module writes them)
Does not own: the Docker runner (adapters.source_execution, a later layer), the injected coordination Workflow it reads (store, task ownership), the audit, release, image and deployment rows it only reads (research_audits, research_control, releases, deployment, images)
Entry points: SourceExecutions
Contracts: INV-RESEARCH-003

Moved from M7 `application/source_execution.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §6 V11, A/evidence/rebuild/s8/reverse-source-apps-move/transcribe.py): R-x0 (the kernel imports), R-x1 (the two function-level `ContractError` imports read `kernel.errors`); every other statement is M7's. The first paragraphs are M7's module docstring.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest, utcnow
from codex_harness.kernel.policy import POLICY


class SourceExecutions:
    def __init__(self, workflow):
        self.workflow, self.store = workflow, workflow.store

    def _validate(self, tx, task, source):
        current = self.workflow._owned(tx, task)
        details = current.get('input') or current['message']['what']['details']
        audit = tx.get('research_audits', details.get('audit_id', ''))
        require(audit is not None and audit['source'] == source, 'Source execution assignment mismatch')
        require((tx.get('research_control', 'activation') or {}).get('status') == 'active',
                'Source execution paused')

    def request(self, task, source, command):
        source.validate()
        require(command and all(isinstance(arg, str) and arg for arg in command), 'Invalid command')
        body = {'task': task, 'source': asdict(source), 'command': command}
        key = digest({'task': task['id'], 'generation': task['generation'],
                      'source': body['source'], 'command': command})
        with self.store.transaction() as tx:
            self._validate(tx, task, body['source'])
            old = tx.get('source_execution_requests', key)
            if old:
                return old
            row = {**body, 'id': key, 'status': 'queued', 'at': utcnow()}
            tx.put('source_execution_requests', key, row)
            return row

    def claim(self):
        from codex_harness.kernel.errors import ContractError
        with self.store.transaction() as tx:
            for row in tx.scan('source_execution_requests'):
                if row['status'] not in {'queued', 'running'}:
                    continue
                if row['status'] == 'running' and (
                    datetime.now(timezone.utc) - datetime.fromisoformat(row['started_at'])
                ).total_seconds() <= POLICY.source_execution_seconds + 40:
                    continue
                try:
                    self._validate(tx, row['task'], row['source'])
                except ContractError as exc:
                    tx.put('source_execution_requests', row['id'],
                           {**row, 'status': 'cancelled', 'reason': str(exc)})
                    continue
                active = tx.get('deployment', 'active') or {}
                image = tx.get('images', active.get('release_id', ''))
                release = tx.get('releases', active.get('release_id', ''))
                require(image and release and release['status'] == 'active'
                        and image['revision'] == active['revision']
                        and image['image'].startswith('sha256:'), 'Verified execution image unavailable')
                row.update(status='running', owner=str(uuid4()), started_at=utcnow(), image=image['image'],
                           release_id=active['release_id'])
                tx.put('source_execution_requests', row['id'], row)
                return row
        return None

    def result(self, task, request_id):
        with self.store.transaction() as tx:
            row = tx.get('source_execution_requests', request_id)
            require(row and row['task']['id'] == task['id']
                    and row['task']['generation'] == task['generation'], 'Source request owner mismatch')
            self._validate(tx, task, row['source'])
            if row['status'] == 'succeeded':
                require((tx.get('deployment', 'active') or {}).get('release_id') == row['release_id'],
                        'Execution image superseded before consumption')
            return row

    def complete(self, row, receipt):
        receipt.validate()
        require(asdict(receipt.source) == row['source'] and receipt.command == row['command'],
                'Source receipt binding mismatch')
        with self.store.transaction() as tx:
            current = tx.get('source_execution_requests', row['id'])
            tx.put('source_execution_history', digest({'request': row['id'], 'owner': row['owner']}),
                   {'request_id': row['id'], 'receipt': asdict(receipt), 'at': utcnow()})
            if not current or current['status'] != 'running' or current['owner'] != row['owner']:
                return  # A replaced runner may retain evidence but cannot publish a usable result.
            # INV-RESEARCH-003: keep evidence even if rollback or a stale lease prevents consumption.
            from codex_harness.kernel.errors import ContractError
            try:
                self._validate(tx, row['task'], row['source'])
                require((tx.get('deployment', 'active') or {}).get('release_id') == row['release_id'],
                        'Execution image superseded')
                status = 'succeeded'
            except ContractError:
                status = 'cancelled'
            tx.put('source_execution_requests', row['id'],
                   {**current, 'status': status, 'receipt': asdict(receipt), 'completed_at': utcnow()})
