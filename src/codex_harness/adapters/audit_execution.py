"""Compose Codex semantic analysis with runner-owned inspection receipts."""
import json
from dataclasses import asdict, replace
from importlib.resources import files

from codex_harness.application.audit_gate import AUDIT_EVIDENCE_BUCKETS
from codex_harness.application.research import ResearchAudits
from codex_harness.domain.model import digest, require, utcnow
from codex_harness.domain.research import IndependentReview, PartitionCheckpoint, parse_record


def schema(**properties):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}


TEXT = {'type': 'string'}
STRINGS = {'type': 'array', 'items': TEXT}


def output_definitions():
    definitions = json.loads(files('codex_harness.resources').joinpath('research.schema.json').read_text())['$defs']
    # INV-RESEARCH-003: retain historical evidence; constrain only newly generated output.
    # The provider rejects open objects even in unused definitions (2026-09-07 canary).
    definitions['SubsystemAnalysis']['properties']['tests_not_run']['items'] = schema(
        test=TEXT, reason=TEXT, follow_up=TEXT)
    return definitions


class AuditExecution:
    def __init__(self, executor, runner):
        self.executor, self.runner = executor, runner
        self.audits = ResearchAudits(executor.service.store, None, executor.artifacts,
                                    executor.workflow, runner)

    def run_model(self, task, objective, evidence, result_schema):
        workload = "final_validation" if task.get('phase') == 'audit_review' else "design"
        return self.executor._run(task.get('agent', task.get('actor')), task['id'], objective,
            evidence, str(self.executor.git.repository), result_schema, True,
            heartbeat=lambda: self.executor.workflow.heartbeat(task), lease=task,
            stage="audit:" + digest({"objective": objective, "schema": result_schema}),
            workload=workload)

    @staticmethod
    def typed_schema(kind):
        definitions = output_definitions()
        return {**definitions[kind], '$defs': definitions}

    @staticmethod
    def partition_schema(partition=None):
        defs = output_definitions()
        result_schema = schema(paths={'type': 'array', 'items': {'$ref': '#/$defs/PathDisposition'}},
            subsystems={'type': 'array', 'items': {'$ref': '#/$defs/SubsystemAnalysis'}},
            open_questions=STRINGS, cursor=TEXT)
        result_schema['$defs'] = defs
        if partition is not None:
            # INV-RESEARCH-002: output identities must match immutable assigned scope.
            for field, kind, identity in [('paths', 'PathDisposition', 'path'),
                                          ('subsystems', 'SubsystemAnalysis', 'name')]:
                if partition[field]:
                    defs[kind]['properties'][identity] = {'type': 'string', 'enum': list(partition[field])}
                else:
                    result_schema['properties'][field]['maxItems'] = 0
        return result_schema

    def execute(self, task):
        details = task['message']['what']['details']
        action = task['message']['what']['action']
        if action == 'audit_discovery':
            with self.audits.store.transaction() as tx:
                discovery = tx.get('research_discoveries', details['discovery_id'])
            require(discovery is not None, 'Unknown discovery')
            mapping = self.run_model(task, 'Identify a canonical primary GitHub repository for this '
                'discovery from cited evidence. Return an empty repository and explain why if unavailable. '
                'This mapping is provisional and must be independently reviewed before adoption.',
                discovery, schema(repository=TEXT, reason=TEXT))
            if not mapping['repository']:
                return {'status': 'unmapped', 'reason': mapping['reason']}
            detail = self.executor.research.github_detail(mapping['repository'])
            row = {'id': digest({'repository': detail['url'], 'revision': detail['revision']}),
                   'repository': detail['url'], 'revision': detail['revision'], 'priority': 100,
                   'status': 'discovered_not_reviewed', 'discovery_id': discovery['id'],
                   'mapping_ref': mapping['execution_ref'], 'manifest_ref': None}
            with self.audits.store.transaction() as tx:
                self.executor.workflow._owned(tx, task)
                if not tx.get('research_backlog', row['id']):
                    tx.put('research_backlog', row['id'], row)
            return row
        if action == 'audit_acquire':
            source, entries, verifier = self.runner.acquire(details['repository'], details['commit'])
            taxonomy = self.run_model(task, 'Inventory every subsystem, including configuration, tests, '
                'scripts and dependencies. This is scope discovery, not semantic completion.',
                {'source': asdict(source), 'inventory': [asdict(e) for e in entries]},
                schema(subsystems=STRINGS))
            self.audits.verifier = verifier
            audit = self.audits.import_audit(source, entries, taxonomy['subsystems'])
            self.audits.partition(audit['id'])
            with self.audits.store.transaction() as tx:
                self.executor.workflow._owned(tx, task)
                row = tx.get('research_backlog', details['backlog_id'])
                require(row is not None and row['repository'] == source.repository
                        and row['revision'] == source.commit, 'Backlog source changed')
                row.update(audit_id=audit['id'], status='source_verified_not_reviewed')
                tx.put('research_backlog', row['id'], row)
            return {'audit_id': audit['id'], 'source': asdict(source)}
        with self.audits.store.transaction() as tx:
            audit = tx.get('research_audits', details['audit_id'])
            require(audit is not None, 'Unknown audit')
            evidence = {'audit': audit, 'coverage': {
                bucket: [r for r in tx.scan(bucket) if r['audit_id'] == audit['id']]
                for bucket in ('research_paths', 'research_subsystems')}}
            partition = tx.get('research_partitions', details.get('partition_id', ''))
        if action == 'audit_propose':
            answer = self.run_model(task, 'Propose an adaptation using the complete retained source audit. '
                'Map behavior, failures, license, dependencies, graph impact and harness contracts. '
                'Use your own actor identity as author; defer or reject if unjustified.', evidence,
                self.typed_schema('AdaptationProposal'))
            document = {k: answer[k] for k in self.typed_schema('AdaptationProposal')['properties']}
            proposal = parse_record({'version': 1, 'kind': 'AdaptationProposal', 'record': document})
            require(proposal.author == task['agent'], 'Proposal author mismatch')
            result = self.audits.propose(audit['id'], proposal)
            with self.audits.store.transaction() as tx:
                self.executor.workflow._owned(tx, task)
                tx.put('research_proposal_runs', audit['id'], {'audit_id': audit['id'], 'result': result})
            return result
        require(partition is not None and partition['generation'] == details['generation'],
                'Stale partition assignment')
        evidence['partition'] = partition
        plan = self.run_model(task, 'Select bounded source inspection or test commands for this partition. '
            'For source inspection prefer ["source-list", "0"] (100 entries per page) or '
            '["source-read", "BASE64_PATH_FROM_MANIFEST", "0", "0"] (line and character offsets). '
            'These read immutable objects without running repository code. Continue with BOTH next_line '
            'and next_char; partial_last_line means that line is not fully read. '
            'Commands run in a networkless, read-only source tree with inert symlinks and no installs. '
            'Do not claim commands ran. Return at most four commands.', evidence,
            schema(commands={'type': 'array', 'maxItems': 4, 'items': STRINGS}))
        require(len(plan['commands']) <= 4, 'Inspection command budget exceeded')
        receipts = [self.audits.execute(task, audit['id'], command) for command in plan['commands']]
        evidence['receipts'] = receipts
        result_schema = self.partition_schema(partition)
        answer = self.run_model(task, 'Semantically trace this bounded partition against contracts, callers, '
            'configuration, failure handling and tests. Use only supplied successful runner receipt IDs. '
            'Return paths records only for identities in partition.paths and subsystem records only '
            'for names in partition.subsystems. An empty assignment requires an empty output array; '
            'do not add supporting subsystem records to a path-only partition. Subsystem trace paths '
            'may reference repository inventory paths. Partial results may omit assigned identities; '
            'all omitted or unresolved work remains in its existing partition. '
            'Explicitly preserve unreviewed scope, tests not run and open questions. Inventory is not review. '
            'Never infer execution from test file presence. For each executed test in tests, use a JSON '
            'string encoding the exact argv array of its successful execution receipt. source-list and '
            'source-read are never test execution. Put unexecuted tests in tests_not_run, not tests, '
            'including each test verbatim '
            'with reason and follow_up. On context limits return partial progress.',
            evidence, result_schema)
        def decode(kind, records):
            return [parse_record({'version': 1, 'kind': kind, 'record': r}) for r in records]
        paths = decode('PathDisposition', answer['paths'])
        systems = decode('SubsystemAnalysis', answer['subsystems'])
        covered_paths = {p.path for p in paths if p.disposition not in {'unreviewed', 'unavailable'}}
        covered_systems = {s.name for s in systems if not (
            s.contradictions or s.unresolved_dependencies or s.tests_not_run)}
        # checkpoint() independently reconciles these claims against persisted coverage.
        checkpoint = replace(PartitionCheckpoint(**partition),
            remaining_paths=sorted(set(partition['remaining_paths']) - covered_paths),
            remaining_subsystems=sorted(set(partition['remaining_subsystems']) - covered_systems),
            open_questions=answer['open_questions'], cursor=answer['cursor'])
        return self.audits.checkpoint(task, checkpoint, paths, systems)

    def review(self, task):
        from codex_harness.application.execution_notices import record as execution_notice
        from codex_harness.application.execution_recovery import ExecutionRecovery
        recovery = ExecutionRecovery(self.audits.store, self.audits.workflow.org, self.audits.artifacts)
        data = task['input']
        # Successful command inspection is mandatory even if the model's verdict is positive.
        receipt = self.audits.execute(task, data['audit_id'], ['source-list'])
        blocked = receipt['receipt']['inspection_blocked'] or receipt['receipt']['exit_status'] != 0
        if blocked:
            result = {'accepted': False, 'inspection_blocked': True, 'execution_ref': receipt['receipt']['output_ref']}
        else:
            with self.audits.store.transaction() as tx:
                audit = tx.get('research_audits', data['audit_id'])
                evidence = {bucket: [r for r in tx.scan(bucket) if r['audit_id'] == data['audit_id']]
                            for bucket in (*AUDIT_EVIDENCE_BUCKETS, 'research_receipts')}
            result = self.run_model(task, 'Independently inspect source evidence and evaluate this adaptation. '
                'Reject incomplete scope, unresolved contradictions, license/dependency concerns or unsafe '
                'architecture, SRE and graph impact. Source inventory alone is not semantic evidence.',
                {**data, 'audit': audit, 'evidence': evidence, 'inspection': receipt},
                self.typed_schema('IndependentReview'))
            if result.get('inspection_blocked'):
                with self.audits.store.transaction() as tx:
                    current = self.executor.workflow._owned(tx, task)
                    recovery.validate_decision(tx, current)
                    current.update(status='inspection_blocked', result=result, completed_at=utcnow())
                    tx.put('decisions_pending', task['id'], current)
                    execution_notice(tx, self.audits.workflow.org, current, 'decisions_pending', 'inspection_blocked', utcnow())
                return current
            review = IndependentReview(data['binding'], task['actor'], receipt['id'], result['accepted'],
                result['license_assessment'], result['dependency_assessment'], result['sre_assessment'],
                result['architecture_assessment'], result['graph_assessment'])
            self.audits.review(task, review)
        with self.audits.store.transaction() as tx:
            current = self.executor.workflow._owned(tx, task)
            if blocked:
                recovery.validate_decision(tx, current)
            current.update(status='inspection_blocked' if blocked else 'succeeded',
                           result=result, completed_at=utcnow())
            tx.put('decisions_pending', task['id'], current)
            if blocked:
                execution_notice(tx, self.audits.workflow.org, current, 'decisions_pending', 'inspection_blocked', utcnow())
        return current
