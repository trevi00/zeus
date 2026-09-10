"""Durable audit progress. Inventory import never implies semantic coverage."""
from __future__ import annotations

import base64
import json
from dataclasses import asdict
from importlib.resources import files

from codex_harness.domain.model import canonical, digest, require, utcnow
from codex_harness.domain.research import (
    AdaptationProposal,
    InventoryEntry,
    ObservedAsset,
    PartitionCheckpoint,
    PathDisposition,
    SourceIdentity,
    SubsystemAnalysis,
    parse_record,
)
from codex_harness.ports import AuditArtifacts, SourceVerifier, Store


class ResearchAudits:
    def __init__(self, store: Store, verifier: SourceVerifier | None,
                 artifacts: AuditArtifacts, workflow, runner=None):
        self.store, self.verifier = store, verifier
        self.artifacts, self.workflow = artifacts, workflow
        self.runner = runner

    def seed_backlog(self):
        seeds = json.loads(files('codex_harness.resources').joinpath('research-backlog.json').read_text())
        records = []
        for priority, seed in enumerate(seeds, 1):
            manifest = self.artifacts.document(seed['manifest_ref'])
            paths = [item['path'] for item in manifest['files']]
            require(manifest['repository'] == seed['repository']
                    and manifest['revision'] == seed['revision']
                    and len(paths) == seed['files'] and len(set(paths)) == len(paths),
                    'Backlog manifest mismatch')
            records.append({'id': digest(seed), 'version': 1, **seed, 'priority': priority,
                'status': 'inventoried_not_reviewed', 'activation': 'pending_verified_rollout',
                'source_verified': False, 'reviewed_paths': 0, 'remaining_paths': paths,
                'remaining_subsystems': ['subsystem discovery required'],
                'open_questions': ['Verify original Git objects and linked artifact bytes'],
                'manifest_ref': seed['manifest_ref']})
        with self.store.transaction() as tx:
            historical = tx.records()
            for record in records:
                matches = [r['id'] for r in historical if r['bucket'] == 'reference_audits'
                           and all(value in canonical(r['body']) for value in
                                   (record['repository'], record['revision'], record['manifest_ref']))]
                require(bool(matches), 'Missing historical reference audit for backlog')
                record['historical_reference_ids'] = matches
                old = tx.get('research_backlog', record['id'])
                if old is None:
                    tx.put('research_backlog', record['id'], record)
            # INV-RESEARCH-001: preserve reference_audits and all legacy proposals verbatim.
            return [tx.get('research_backlog', r['id']) for r in records]

    def import_audit(self, source: SourceIdentity, entries: list[InventoryEntry],
                     subsystems: list[str]):
        source = parse_record({'version': 1, 'kind': 'SourceIdentity', 'record': asdict(source)})
        entries = [parse_record({'version': 1, 'kind': 'InventoryEntry', 'record': asdict(e)})
                   for e in entries]
        require(self.verifier is not None, 'Source verifier unavailable')
        require(subsystems and len(subsystems) == len(set(subsystems))
                and all(subsystems), 'Explicit unique subsystem inventory required')
        verified = self.verifier.verify(source, entries)
        key = digest(asdict(source))
        record = {'id': key, 'version': 1, 'source': asdict(source), 'inventory': verified['entries'],
                  'subsystems': sorted(subsystems), 'status': 'source_verified_not_reviewed',
                  'activation': 'pending_verified_rollout'}
        with self.store.transaction() as tx:
            old = tx.get('research_audits', key)
            require(old is None or old == record, 'Conflicting audit import')
            if old is None:
                tx.put('research_audits', key, record)
        return record

    def partition(self, audit_id: str, limit: int = 32):
        require(type(limit) is int and 0 < limit <= 128, 'Invalid partition budget')
        with self.store.transaction() as tx:
            audit = tx.get('research_audits', audit_id)
            require(audit is not None, 'Unknown audit')
            existing = [p for p in tx.scan('research_partitions') if p['audit_id'] == audit_id]
            if existing:
                return sorted(existing, key=lambda p: p['partition_id'])
            paths = sorted(e['path'] for e in audit['inventory'])
            records = []
            # Subsystem work is separate; every scope item survives task budgets.
            for kind, scope in [('paths', paths), ('subsystems', audit['subsystems'])]:
                for offset in range(0, len(scope), limit):
                    selected = scope[offset:offset + limit]
                    key = digest({'audit': audit_id, 'kind': kind, 'scope': selected})
                    p = PartitionCheckpoint(audit_id, key, 0,
                        selected if kind == 'paths' else [], selected if kind == 'subsystems' else [],
                        [], selected if kind == 'paths' else [], selected if kind == 'subsystems' else [],
                        [], 'pending')
                    p.validate()
                    body = asdict(p)
                    tx.put('research_partitions', key, body)
                    records.append(body)
            return records

    def checkpoint(self, task, checkpoint: PartitionCheckpoint,
                   dispositions: list[PathDisposition], analyses: list[SubsystemAnalysis],
                   continuation: dict | None = None):
        checkpoint = parse_record({'version': 1, 'kind': 'PartitionCheckpoint',
                                   'record': asdict(checkpoint)})
        for record in [*dispositions, *analyses]:
            parse_record({'version': 1, 'kind': type(record).__name__, 'record': asdict(record)})
            for ref in record.evidence_refs:
                self.artifacts.inspect(ref)
        for ref in checkpoint.evidence_refs:
            self.artifacts.inspect(ref)
        require(len({p.path for p in dispositions}) == len(dispositions)
                and len({s.name for s in analyses}) == len(analyses), 'Duplicate coverage')
        with self.store.transaction() as tx:
            current_task = self.workflow._owned(tx, task)
            details = current_task['message']['what']['details']
            require(details.get('audit_id') == checkpoint.audit_id
                    and details.get('partition_id') == checkpoint.partition_id,
                    'Execution is not assigned this partition')
            old = tx.get('research_partitions', checkpoint.partition_id)
            require(old is not None and old['audit_id'] == checkpoint.audit_id
                    and old['generation'] == checkpoint.generation, 'Stale partition writer')
            require(old['paths'] == checkpoint.paths and old['subsystems'] == checkpoint.subsystems,
                    'Partition scope changed')
            require(all(p.path in old['paths'] for p in dispositions)
                    and all(s.name in old['subsystems'] for s in analyses), 'Cross-partition evidence')
            audit = tx.get('research_audits', checkpoint.audit_id)
            inventory = {p['path']: p for p in audit['inventory']}
            # INV-RESEARCH-003: model-authored receipt IDs are not runner attestations.
            for item in [*dispositions, *analyses]:
                for receipt_id in item.receipt_ids:
                    receipt = tx.get('research_receipts', receipt_id)
                    require(receipt is not None and receipt['audit_id'] == checkpoint.audit_id
                            and receipt['task_id'] == task['id']
                            and receipt['generation'] == task['generation']
                            and receipt['receipt']['exit_status'] == 0
                            and not receipt['receipt']['inspection_blocked'],
                            'Runner receipt missing, stale, blocked or unsuccessful')
                    self.artifacts.inspect(receipt['receipt']['output_ref'])
            for disposition in dispositions:
                entry = inventory[disposition.path]
                if disposition.disposition in {'unreviewed', 'unavailable'}:
                    continue
                require(entry['mode'] != '160000', 'Submodule requires its own verified audit')
                envelope = self.artifacts.document(entry['artifact_ref'])
                raw = base64.b64decode(envelope['data'], validate=True)
                try:
                    raw.decode('utf-8')
                    binary = b'\0' in raw
                except UnicodeDecodeError:
                    binary = True
                require(not binary or (disposition.disposition == 'binary'
                        and disposition.receipt_ids),
                        'Binary coverage requires verified runner inspection')
                require(set(disposition.links) <= set(inventory), 'Unknown generator/original path')
            for analysis in analyses:
                require(set(analysis.paths) <= set(inventory), 'Unknown subsystem path')
                # INV-RESEARCH-003: listing files cannot attest that a claimed test command ran.
                not_run = {test['test'] for test in analysis.tests_not_run}
                executed = [tx.get('research_receipts', ref)['receipt'] for ref in analysis.receipt_ids]
                for test in analysis.tests:
                    if test in not_run:
                        continue
                    try:
                        command = json.loads(test)
                    except (TypeError, ValueError):
                        command = None
                    require(isinstance(command, list) and command and all(isinstance(s, str) for s in command)
                            and command[0] not in {'source-list', 'source-read'}
                            and any(r['command'] == command
                                    and r['isolation'] != 'inert-objects-no-code-execution'
                                    for r in executed),
                            'Claimed test lacks matching successful execution command')
            for kind, records, field in [('research_paths', dispositions, 'path'),
                                         ('research_subsystems', analyses, 'name')]:
                for record in records:
                    key = digest({'audit': checkpoint.audit_id, 'item': getattr(record, field)})
                    body = {'audit_id': checkpoint.audit_id, 'record': asdict(record),
                            'task_id': task['id'], 'generation': task['generation']}
                    tx.put(kind, key, body)
                    tx.put('research_evidence_history', digest(body), body)
            paths, subsystems = self._coverage(tx, audit)
            require(set(checkpoint.remaining_paths) == set(old['paths']) - paths
                    and set(checkpoint.remaining_subsystems) == set(old['subsystems']) - subsystems,
                    'Remaining work does not reconcile')
            body = asdict(checkpoint)
            body['evidence_refs'] = sorted(set(old['evidence_refs']) | set(body['evidence_refs']) |
                {ref for r in [*dispositions, *analyses] for ref in r.evidence_refs})
            body['generation'] += 1
            # Immutable checkpoint history retains prior evidence transitively.
            history = digest(body)
            tx.put('research_checkpoints', history, body)
            tx.put('research_partitions', checkpoint.partition_id, body)
            if continuation:
                self.workflow.org.authorize(continuation)
                require(continuation['who']['sender'] == task['agent']
                        and continuation['what']['details'].get('audit_id') == checkpoint.audit_id
                        and continuation['what']['details'].get('partition_id') == checkpoint.partition_id,
                        'Invalid audit continuation')
                tx.put('outbox', continuation['message_id'], {'message': continuation, 'sent': False})
            return body

    @staticmethod
    def _coverage(tx, audit):
        paths, subsystems = set(), set()
        for row in tx.scan('research_paths'):
            if row['audit_id'] == audit['id']:
                p = PathDisposition(**row['record'])
                p.validate()
                if p.disposition not in {'unreviewed', 'unavailable'}:
                    paths.add(p.path)
        for row in tx.scan('research_subsystems'):
            if row['audit_id'] == audit['id']:
                s = SubsystemAnalysis(**row['record'])
                s.validate()
                if not (s.contradictions or s.unresolved_dependencies or s.tests_not_run):
                    subsystems.add(s.name)
        return paths, subsystems

    @staticmethod
    def _observed(tx, audit):
        """INV-RESEARCH-001: observed assets are a separate ledger with their own completeness."""
        from collections import Counter
        rows = [r for r in tx.scan('research_observed_assets') if r['audit_id'] == audit['id']]
        assets = [ObservedAsset(**r['record']) for r in rows]
        for asset in assets:
            asset.validate()
        pending = sorted(a.path for a in assets if a.pending)
        return {'total': len(assets), 'pending': len(pending), 'pending_paths': pending,
                'states': dict(sorted(Counter(a.state for a in assets).items()))}

    def observe_assets(self, audit_id, assets: list[ObservedAsset]):
        assets = [parse_record({'version': 1, 'kind': 'ObservedAsset', 'record': asdict(a)}) for a in assets]
        require(assets and len({a.path for a in assets}) == len(assets), 'Unique observed asset paths required')
        for asset in assets:
            for ref in asset.evidence_refs:
                self.artifacts.inspect(ref)
        with self.store.transaction() as tx:
            audit = tx.get('research_audits', audit_id)
            require(audit is not None, 'Unknown audit')
            tracked = {e['path'] for e in audit['inventory']}
            changed = 0
            for asset in assets:
                require(asset.path not in tracked, 'Tracked Git paths belong to the inventory, not the observed ledger')
                key = digest({'audit': audit_id, 'path': asset.path})
                record = asdict(asset)
                old = tx.get('research_observed_assets', key)
                if old is not None:
                    if old['record'] == record:
                        continue
                    previous = ObservedAsset(**old['record'])
                    require(previous.pending or not asset.pending,
                            'Observed asset disposition cannot regress to pending')
                    history = old.get('history', []) + [old['record']]
                else:
                    history = []
                tx.put('research_observed_assets', key, {'id': key, 'audit_id': audit_id, 'record': record,
                                                         'history': history, 'at': utcnow()})
                changed += 1
            return {'audit_id': audit_id, 'changed': changed, **self._observed(tx, audit)}

    def coverage(self, audit_id):
        with self.store.transaction() as tx:
            audit = tx.get('research_audits', audit_id)
            require(audit is not None, 'Unknown audit')
            paths, subsystems = self._coverage(tx, audit)
            observed = self._observed(tx, audit)
            remaining_paths = sorted(set(p['path'] for p in audit['inventory']) - paths)
            remaining_subsystems = sorted(set(audit['subsystems']) - subsystems)
            return {'reviewed_paths': len(paths),
                    'remaining_paths': remaining_paths,
                    'remaining_subsystems': remaining_subsystems,
                    'observed_assets': observed,
                    'whole_analysis_complete': not remaining_paths and not remaining_subsystems
                    and observed['pending'] == 0,
                    'adoption_eligible': self._eligible(tx, audit),
                    'reason': 'Eligibility requires complete coverage, dispositioned observed assets '
                              'and current independent approvals'}

    def propose(self, audit_id, proposal: AdaptationProposal):
        proposal = parse_record({'version': 1, 'kind': 'AdaptationProposal', 'record': asdict(proposal)})
        require(self.workflow.org.actor(proposal.author, 'worker').team == 'research',
                'Research proposal author required')
        with self.store.transaction() as tx:
            audit = tx.get('research_audits', audit_id)
            require(audit is not None and audit['source'] == asdict(proposal.source),
                    'Cross-repository proposal')
            require(set(proposal.scope) <= {p['path'] for p in audit['inventory']}, 'Unknown proposal scope')
            body = {'audit_id': audit_id, 'proposal': asdict(proposal), 'status': 'deferred'}
            key = digest(body)
            body['id'] = key
            tx.put('research_adaptations', key, body)
            if proposal.decision in {'adopt', 'adapt'}:
                paths, systems = self._coverage(tx, audit)
                require(paths == {e['path'] for e in audit['inventory']}
                        and systems == set(audit['subsystems']), 'Audit coverage incomplete')
                require(self._observed(tx, audit)['pending'] == 0, 'Observed assets await disposition')
                from codex_harness.application.audit_gate import binding
                require(not any(p['open_questions'] for p in tx.scan('research_partitions')
                                if p['audit_id'] == audit_id), 'Open audit questions remain')
                bound = binding(tx, audit_id, body['proposal'])
                self._queue_review(tx, audit_id, body['proposal'], bound, 'lead:research')
            return body


    def execute(self, task, audit_id, command):
        """Only the configured infrastructure runner can create receipt authority."""
        require(self.runner is not None, 'Isolated runner unavailable')
        with self.store.transaction() as tx:
            current = self.workflow._owned(tx, task)
            details = (current.get('input') or current.get('message', {}).get('what', {}).get('details', {}))
            require(details.get('audit_id') == audit_id, 'Execution is not assigned this audit')
            audit = tx.get('research_audits', audit_id)
            require(audit is not None, 'Unknown audit')
        receipt = self.runner.execute_assigned(SourceIdentity(**audit['source']), command, task, self.workflow)
        receipt.validate()
        require(asdict(receipt.source) == audit['source'], 'Runner source mismatch')
        self.artifacts.inspect(receipt.output_ref)
        body = {'audit_id': audit_id, 'task_id': task['id'], 'generation': task['generation'],
                'receipt': asdict(receipt)}
        key = digest(body)
        with self.store.transaction() as tx:
            self.workflow._owned(tx, task)
            tx.put('research_receipts', key, body)
        return {'id': key, **body}

    @staticmethod
    def _queue_review(tx, audit_id, proposal, bound, actor):
        from codex_harness.domain.model import envelope
        key = digest({'binding': bound, 'actor': actor})
        if tx.get('decisions_pending', key):
            return
        message = envelope('review.result', 'lead:research', actor, 'audit_review',
                           {'audit_id': audit_id}, 'audit:' + audit_id)
        tx.put('decisions_pending', key, {'id': key, 'actor': actor, 'phase': 'audit_review',
            'input': {'audit_id': audit_id, 'proposal': proposal, 'binding': bound},
            'message': message, 'status': 'pending', 'attempt': 0})

    def review(self, task, review):
        from codex_harness.application.audit_gate import binding
        review = parse_record({'version': 1, 'kind': 'IndependentReview', 'record': asdict(review)})
        with self.store.transaction() as tx:
            current = self.workflow._owned(tx, task)
            from codex_harness.application.execution_recovery import ExecutionRecovery
            ExecutionRecovery(self.store, self.workflow.org, self.artifacts).validate_decision(tx, current)
            require(current.get('phase') == 'audit_review' and current['actor'] == review.actor,
                    'Unauthorized audit reviewer')
            data = current['input']
            require(review.actor != data['proposal']['author'], 'Self review forbidden')
            require(review.binding == data['binding'] == binding(tx, data['audit_id'], data['proposal']),
                    'Stale audit review')
            receipt = tx.get('research_receipts', review.execution_id)
            require(receipt is not None and receipt['audit_id'] == data['audit_id']
                    and receipt['task_id'] == task['id'] and receipt['generation'] == task['generation'],
                    'Independent command inspection required')
            self.artifacts.inspect(receipt['receipt']['output_ref'])
            successful = receipt['receipt']['exit_status'] == 0 and not receipt['receipt']['inspection_blocked']
            require(successful or not review.accepted, 'Inspection-blocked review cannot approve')
            record = {'audit_id': data['audit_id'], 'review': asdict(review),
                      'status': 'reviewed' if successful else 'inspection-blocked'}
            tx.put('research_reviews', digest(asdict(review)), record)
            if not review.accepted:
                return record
            if review.actor == 'lead:research':
                self._queue_review(tx, data['audit_id'], data['proposal'], review.binding, 'conductor')
            else:
                require(any(r['review']['binding'] == review.binding
                            and r['review']['actor'] == 'lead:research' and r['review']['accepted']
                            for r in tx.scan('research_reviews')), 'Research lead approval required')
                reviews = [r for r in tx.scan('research_reviews')
                           if r['review']['binding'] == review.binding and r['review']['accepted']]
                approval = {'audit_id': data['audit_id'], 'binding': review.binding,
                            'proposal': data['proposal'],
                            'reviews': [digest(r['review']) for r in reviews]}

                tx.put('research_approvals', review.binding, approval)
            return record

    def _eligible(self, tx, audit):
        from codex_harness.application.audit_gate import inspect_approval
        from codex_harness.domain.model import ContractError
        for key, row in [(r['binding'], r) for r in tx.scan('research_approvals')]:
            if row['audit_id'] == audit['id']:
                try:
                    inspect_approval(tx, {'audit_id': audit['id'], 'audit_approval': key},
                                     self.artifacts)
                    return True
                except (ContractError, OSError, ValueError):
                    pass
        return False
