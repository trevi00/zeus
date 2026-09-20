"""Compose Codex semantic analysis with runner-owned inspection receipts."""
import json
from dataclasses import asdict, replace
from importlib.resources import files

from codex_harness.application.audit_gate import AUDIT_EVIDENCE_BUCKETS
from codex_harness.application.research import ResearchAudits
from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.domain.observation import (
    ANALYSIS_CHECKPOINTED,
    ANALYSIS_CONTENT_REJECTED,
    ANALYSIS_REJECTED,
)
from codex_harness.domain.research import (
    PATH_DISPOSITIONS,
    IndependentReview,
    PartitionCheckpoint,
    parse_record,
)


def schema(**properties):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}


TEXT = {'type': 'string'}
STRINGS = {'type': 'array', 'items': TEXT}
NULL = {'type': 'null'}

# self-improvement-reference-001, 2026-09-21 host canary task
# `6975f930-7633-4f4b-b083-e002d04776b7` (`ContractError: Missing generator/original link`): the
# typed content boundary refused a generated draft while the execution, its receipts and its
# observations succeeded. A refused draft is retained work with its own explicit outcome, not a
# stopped execution: the raw content stays in the immutable output artifact, the partition keeps
# its generation and its whole remaining scope, and nothing is retried, merged or credited.
# `analysis_checkpointed` is partial progress, never semantic acceptance; `analysis_rejected` is
# never a successful review. A result carrying neither marker is unclassified history and is never
# newly inferred to be either. `domain.observation` owns the codes; this module only writes them.
ANALYSIS_VERSION = 1


def assigned_body(definition, identity):
    """The record definition without its identity field: the assigned key carries that identity."""
    return {**definition,
            'properties': {k: v for k, v in definition['properties'].items() if k != identity},
            'required': [k for k in definition['required'] if k != identity]}


def output_definitions():
    definitions = json.loads(files('codex_harness.resources').joinpath('research.schema.json').read_text())['$defs']
    # INV-RESEARCH-003: retain historical evidence; constrain only newly generated output.
    # The provider rejects open objects even in unused definitions (2026-09-07 canary).
    definitions['SubsystemAnalysis']['properties']['tests_not_run']['items'] = schema(
        test=TEXT, reason=TEXT, follow_up=TEXT)
    # The domain vocabulary is the authority for generated output; the packaged declaration
    # states the same values and test_audit_output_vocabulary asserts they cannot drift
    # (2026-09-20 canary: an unconstrained string let `partial` reach parse_record).
    definitions['PathDisposition']['properties']['disposition'] = {
        'type': 'string', 'enum': list(PATH_DISPOSITIONS)}
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
            # INV-RESEARCH-002: output identities must match immutable assigned scope, and each
            # assigned identity owns exactly one result. 2026-09-21 host canary
            # `d1133291-1151-4ffd-987a-6671cd0f34bd`: an enum-constrained array bound membership
            # but still returned two PathDisposition rows for one path, so the checkpoint duplicate
            # guard refused the whole partition. One required, nullable property per identity
            # cannot express a second record; an unscoped schema stays generic for inspection.
            for field, kind, identity in [('paths', 'PathDisposition', 'path'),
                                          ('subsystems', 'SubsystemAnalysis', 'name')]:
                require(len(set(partition[field])) == len(partition[field]),
                        'Duplicate assigned identity')
                defs['Assigned' + kind] = assigned_body(defs[kind], identity)
                properties = {key: {'anyOf': [NULL, {'$ref': '#/$defs/Assigned' + kind}]}
                              for key in partition[field]}
                result_schema['properties'][field] = {
                    'type': 'object', 'additionalProperties': False,
                    'properties': properties, 'required': list(properties)}
        return result_schema

    @staticmethod
    def decode_assigned(kind, identity, assigned, results):
        """Decode one nullable body per assigned identity; the shape is checked before the domain.

        Missing, foreign or repeated identities, arrays, an identity field inside a body and any
        malformed body are refused here. Nothing is deduplicated, reordered or normalized: a null
        is simply not analyzed and its identity stays in the partition's remaining work.
        """
        require(len(set(assigned)) == len(assigned), 'Duplicate assigned identity')
        require(type(results) is dict and set(results) == set(assigned),
                'Assigned output identities changed')
        records = []
        for key in assigned:
            body = results[key]
            if body is None:
                continue
            require(type(body) is dict and identity not in body, 'Invalid assigned output record')
            records.append(parse_record({'version': 1, 'kind': kind,
                                         'record': {**body, identity: key}}))
        return records

    @staticmethod
    def proposed_checkpoint(trusted, answer):
        """Decode one model answer into the checkpoint it proposes. Pure content validation only.

        This is the ONE recoverable rejection boundary: it reads the already validated trusted
        partition and the answer, and it touches no store, lease, runner, artifact or provider. A
        `ContractError` raised inside it therefore says that generated content was refused and
        nothing else. Identities come from the trusted scope, never from the answer, and no value
        is deduplicated, merged or normalized.
        """
        paths = AuditExecution.decode_assigned('PathDisposition', 'path', trusted.paths,
                                               answer.get('paths'))
        systems = AuditExecution.decode_assigned('SubsystemAnalysis', 'name', trusted.subsystems,
                                                 answer.get('subsystems'))
        covered_paths = {p.path for p in paths if p.disposition not in {'unreviewed', 'unavailable'}}
        covered_systems = {s.name for s in systems if not (
            s.contradictions or s.unresolved_dependencies or s.tests_not_run)}
        questions, cursor = answer.get('open_questions'), answer.get('cursor')
        require(type(questions) is list and all(type(q) is str and q for q in questions),
                'Invalid analysis open questions')
        require(type(cursor) is str, 'Invalid analysis cursor')
        # checkpoint() independently reconciles these claims against persisted coverage.
        checkpoint = replace(trusted,
            remaining_paths=sorted(set(trusted.remaining_paths) - covered_paths),
            remaining_subsystems=sorted(set(trusted.remaining_subsystems) - covered_systems),
            open_questions=questions, cursor=cursor)
        checkpoint.validate()
        return checkpoint, paths, systems

    @staticmethod
    def evidence_ref(answer):
        """This answer's executor-owned artifact reference, or None when the answer carries none."""
        ref = answer.get('execution_ref')
        return ref if type(ref) is str and ref else None

    @staticmethod
    def analysis_binding(task, trusted, outcome, execution_ref, **facts):
        """What this execution did, on which assigned scope, and where its evidence is.

        Identifiers, integers and fixed codes only: model answers, source text, prompts and
        exception messages never enter this projection, which travels into the durable task result,
        the six-W report and the service's logs.
        """
        return {'version': ANALYSIS_VERSION, 'outcome': outcome, 'task_id': task['id'],
                'task_generation': task['generation'], 'attempt': task['attempt'],
                'audit_id': trusted.audit_id, 'partition_id': trusted.partition_id,
                'partition_generation': trusted.generation, 'execution_ref': execution_ref, **facts}

    def rejected_analysis(self, task, trusted, answer, error):
        """Retain a refused draft as its own explicit outcome, bound to its immutable evidence.

        The executor-owned reference is inspected HERE, outside the pure catch: absent, unreadable
        or modified evidence stays an execution failure, because then there is no retained content
        to review later. Only the error's type and a digest of its message leave this method.
        """
        ref = self.evidence_ref(answer)
        require(ref is not None, 'Analysis rejection evidence missing')
        inspected = self.audits.artifacts.inspect(ref)
        require(inspected.get('ref') == ref, 'Analysis rejection evidence mismatch')
        return {'analysis': self.analysis_binding(
            task, trusted, ANALYSIS_REJECTED, ref, reason_code=ANALYSIS_CONTENT_REJECTED,
            error_type=type(error).__name__, error_digest=digest(str(error)),
            checkpointed=False, rejected_at=utcnow())}

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
        # The trusted stored partition is validated BEFORE any generated content is decoded: a
        # stale, corrupt or unreadable assignment is an ownership failure and can never be reported
        # as a rejected draft, and the decode below binds identities from THIS record only.
        trusted = PartitionCheckpoint(**partition)
        trusted.validate()
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
            'paths and subsystems are objects keyed by exactly the identities in partition.paths '
            'and partition.subsystems: every assigned key is present once and carries either null '
            'or one record body. Omit the path/name field inside a body; the key is that identity. '
            'Use null for an identity you did not analyze, and never repeat, rename, add or drop a '
            'key. Use only these dispositions: '
            + ', '.join(PATH_DISPOSITIONS) + '. A partially read path stays unreviewed with its '
            'explanation in justification and its remaining work in open_questions, or is null; '
            'partial is not a disposition and unverified work is never semantic. '
            'An empty assignment requires an empty object; '
            'do not add supporting subsystem records to a path-only partition. Subsystem trace paths '
            'may reference repository inventory paths. Partial results may leave assigned identities '
            'null; all null or unresolved work remains in its existing partition. '
            'Explicitly preserve unreviewed scope, tests not run and open questions. Inventory is not review. '
            'Never infer execution from test file presence. For each executed test in tests, use a JSON '
            'string encoding the exact argv array of its successful execution receipt. source-list and '
            'source-read are never test execution. Put unexecuted tests in tests_not_run, not tests, '
            'including each test verbatim '
            'with reason and follow_up. On context limits return partial progress.',
            evidence, result_schema)
        try:
            # `.get` inside: a field the provider dropped is refused by the same shape check.
            checkpoint, paths, systems = self.proposed_checkpoint(trusted, answer)
        except ContractError as rejection:
            # ONLY the pure content boundary above is recoverable. run_model, the runner, artifact
            # inspection, the lease, the store and ResearchAudits.checkpoint are all outside this
            # catch, and a programmer error is not a ContractError, so none of them can be reported
            # as a rejected draft. Nothing of this batch is checkpointed: the partition keeps its
            # generation and its whole remaining scope for an explicitly reviewed later decision.
            return self.rejected_analysis(task, trusted, answer, rejection)
        saved = self.audits.checkpoint(task, checkpoint, paths, systems)
        ref = self.evidence_ref(answer)
        if ref is None:
            # No executor-owned evidence to bind this outcome to (an injected or legacy answer):
            # the durable checkpoint is the retained work and the result stays unclassified rather
            # than carrying an unbindable marker. `Executor._run` always supplies this reference.
            return saved
        # The persisted canonical checkpoint is untouched; the marker travels with the task result.
        return {**saved, 'analysis': self.analysis_binding(
            task, trusted, ANALYSIS_CHECKPOINTED, ref, checkpoint_generation=saved['generation'],
            checkpointed=True)}

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
