import base64
import json
import os
import subprocess
from dataclasses import asdict, replace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.source_verification import GitSourceVerifier
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.research import ResearchAudits
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, canonical, envelope
from codex_harness.domain.research import (
    InventoryEntry,
    PartitionCheckpoint,
    PathDisposition,
    SourceIdentity,
    require_dispatch,
)


@pytest.fixture
def audit(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args]).decode().strip()
    git('init', '-q')
    git('config', 'user.email', 'fixture@example.com')
    git('config', 'user.name', 'Fixture')
    git('remote', 'add', 'origin', 'https://github.com/fixture/repo.git')
    (repo / 'normal').write_text('source')
    git('add', '.')
    # INV-GRAPH-001: Git paths need not be representable on the host filesystem.
    raw_name = b'space and name' if os.name == 'nt' else b'space\tand\nnewline'
    for mode, name, body in [('100644', raw_name, b'\xff\x00\xfe'),
                             ('120000', b'link', b'normal')]:
        oid = subprocess.check_output(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'],
                                      input=body).strip()
        subprocess.run(['git', '-C', str(repo), 'update-index', '-z', '--index-info'],
                       input=mode.encode() + b' ' + oid + b'\t' + name + b'\0', check=True)
    git('commit', '-qm', 'fixture')
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    verifier = GitSourceVerifier(repo, artifacts)
    source = SourceIdentity('https://github.com/fixture/repo', git('rev-parse', 'HEAD'),
                            git('rev-parse', 'HEAD^{tree}'), 'sha256:' + '0' * 64)
    entries = verifier.inventory(source)
    manifest = {'version': 1, 'repository': source.repository, 'commit': source.commit,
                'tree': source.tree, 'entries': entries}
    source = replace(source, manifest_ref=artifacts.put(canonical(manifest), 'fixture')['ref'])
    entries = [InventoryEntry(**e) for e in entries]
    store = MemoryStore()
    workflow = Workflow(store, organization())
    service = ResearchAudits(store, verifier, artifacts, workflow)
    record = service.import_audit(source, entries, ['core'])
    return service, record, source, entries, git


def test_git_inventory_preserves_raw_paths_binary_and_symlink(audit):
    service, record, source, entries, _ = audit
    assert len(entries) == 3
    assert '120000' in {e.mode for e in entries}
    raw_name = b'space and name' if os.name == 'nt' else b'space\tand\nnewline'
    assert raw_name in {base64.b64decode(e.path) for e in entries}
    assert service.import_audit(source, entries, ['core']) == record
    assert service.coverage(record['id'])['reviewed_paths'] == 0
    assert service.coverage(record['id'])['remaining_subsystems'] == ['core']


def test_inert_reader_never_executes_repository_code(audit, tmp_path, monkeypatch):
    from codex_harness.adapters.audit_runner import AuditRunner
    service, _, source, entries, _ = audit
    def forbidden(*args, **kwargs):
        raise AssertionError('Inert inspection spawned a command')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    runner = AuditRunner(tmp_path / 'runner', service.artifacts)
    listing = runner.execute(source, ['source-list'])
    assert listing.exit_status == 0 and not listing.inspection_blocked
    entry = next(e for e in entries if base64.b64decode(e.path) == b'normal')
    read = runner.execute(source, ['source-read', entry.path, '0'])
    assert service.artifacts.document(read.output_ref)['lines'] == ['source']
    with pytest.raises(ContractError):
        runner.execute(source, ['source-read', 'arbitrary-path', '0'])


@pytest.mark.parametrize('content', ['x' * 24001, '가🙂' * 6001], ids=['ascii', 'unicode'])
def test_oversized_source_line_advances_without_losing_unicode(audit, tmp_path, content):
    from codex_harness.adapters.audit_runner import AuditRunner
    from codex_harness.domain.policy import POLICY
    service, _, source, _, git = audit
    from pathlib import Path
    (Path(service.verifier.repository) / 'normal').write_text(content, encoding='utf-8')
    git('add', 'normal')
    git('commit', '-qm', 'oversized source fixture')
    source = replace(source, commit=git('rev-parse', 'HEAD'), tree=git('rev-parse', 'HEAD^{tree}'))
    entries = service.verifier.inventory(source)
    manifest = {'version': 1, 'repository': source.repository, 'commit': source.commit,
                'tree': source.tree, 'entries': entries}
    source = replace(source, manifest_ref=service.artifacts.put(canonical(manifest), 'fixture')['ref'])
    runner = AuditRunner(tmp_path / 'reader', service.artifacts)
    path = next(e['path'] for e in entries if base64.b64decode(e['path']) == b'normal')
    cursor, chunks = (0, 0), []
    for _ in range(5):
        receipt = runner.execute(source, ['source-read', path, *map(str, cursor)])
        output = service.artifacts.document(receipt.output_ref)
        assert sum(len(s.encode('utf-8')) for s in output['lines']) <= POLICY.source_read_bytes
        chunks.extend(output['lines'])
        next_cursor = (output['next_line'], output['next_char'])
        assert next_cursor > cursor
        cursor = next_cursor
        if cursor[0] == output['total_lines']:
            break
    assert cursor == (1, 0) and ''.join(chunks) == content
    assert output['eof'] is True


@pytest.mark.parametrize('change', ['tree', 'commit', 'repository', 'omit', 'duplicate', 'blob', 'size', 'mode'])
def test_changed_source_fails_even_with_rehashed_manifest(audit, change):
    service, _, source, entries, git = audit
    if change == 'tree':
        source = replace(source, tree='a' * 40)
    if change == 'commit':
        source = replace(source, commit=source.tree)
    if change == 'repository':
        source = replace(source, repository='https://github.com/other/repo')
    if change == 'omit':
        entries = entries[:-1]
    if change == 'duplicate':
        entries = entries + entries[:1]
    if change == 'blob':
        entries[0] = replace(entries[0], object_id='a' * 40)
    if change == 'size':
        entries[0] = replace(entries[0], size=999)
    if change == 'mode':
        entries[0] = replace(entries[0], mode='100755')
    body = {'version': 1, 'repository': source.repository, 'commit': source.commit,
            'tree': source.tree, 'entries': [asdict(e) for e in entries]}
    source = replace(source, manifest_ref=service.artifacts.put(canonical(body), 'fixture')['ref'])
    with pytest.raises(ContractError):
        service.verifier.verify(source, entries)


def test_artifact_corruption_rejected(audit):
    service, _, source, entries, _ = audit
    path = service.artifacts.root / (entries[0].artifact_ref[7:] + '.txt')
    path.write_text('changed')
    with pytest.raises(ContractError, match='integrity'):
        service.verifier.verify(source, entries)


def assigned_partition(service, record):
    partitions = service.partition(record['id'], 1)
    assert service.partition(record['id'], 2) == sorted(partitions, key=lambda p: p['partition_id'])
    partition = next(p for p in partitions if p['paths'] == [base64.b64encode(b'normal').decode()])
    message = envelope('task.assign', 'lead:research', 'worker:github', 'research',
                       {'audit_id': record['id'], 'partition_id': partition['partition_id']}, 'fixture')
    service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture')
    return task, PartitionCheckpoint(**partition)


def test_checkpoint_resume_and_stale_writer(audit):
    service, record, _, _, _ = audit
    task, checkpoint = assigned_partition(service, record)
    evidence = service.artifacts.put('observed implementation and callers', 'fixture')['ref']
    disposition = PathDisposition(checkpoint.paths[0], 'semantic', [evidence], ['symbol'],
                                  'implementation traced', [], '', [])
    checkpoint = replace(checkpoint, evidence_refs=[evidence], remaining_paths=[], cursor='next')
    saved = service.checkpoint(task, checkpoint, [disposition], [])
    assert saved['generation'] == 1
    assert len(service.coverage(record['id'])['remaining_paths']) == 2
    with pytest.raises(ContractError, match='Stale partition'):
        service.checkpoint(task, checkpoint, [disposition], [])
    with service.store.transaction() as tx:
        current = tx.get('tasks', task['id'])
        current['generation'] += 1
        tx.put('tasks', task['id'], current)
    with pytest.raises(ContractError, match='Stale'):
        service.checkpoint(task, PartitionCheckpoint(**saved), [], [])


def test_cannot_drop_scope_or_duplicate_coverage(audit):
    service, record, _, _, _ = audit
    task, checkpoint = assigned_partition(service, record)
    with pytest.raises(ContractError, match='reconcile'):
        service.checkpoint(task, replace(checkpoint, remaining_paths=[]), [], [])
    with pytest.raises(ContractError, match='scope changed'):
        service.checkpoint(task, replace(checkpoint, paths=[], remaining_paths=[]), [], [])
    p = PathDisposition(checkpoint.paths[0], 'unreviewed', [], [], '', [], '', [])
    with pytest.raises(ContractError, match='Duplicate'):
        service.checkpoint(task, checkpoint, [p, p], [])
    with service.store.transaction() as tx:
        assert tx.scan('research_paths') == []


@pytest.mark.parametrize('source', ['github', 'geeknews'])
def test_readme_feed_discovery_never_queues_approval(source):
    workflow = Workflow(MemoryStore(), organization())
    message = envelope('task.assign', 'lead:research', 'worker:' + source, 'research',
                       {'source': source}, 'fixture')
    workflow.submit(message)
    task = workflow.claim('worker:' + source, 'fixture')
    workflow.complete(task, {'source_url': 'https://github.com/fixture/repo', 'evidence': 'README',
                             'accepted': True, 'adoption_eligible': True})
    with workflow.store.transaction() as tx:
        report = tx.scan('outbox')[0]['message']
    workflow.handle(report)
    workflow.handle(report)
    with workflow.store.transaction() as tx:
        assert len(tx.scan('decisions_pending')) == 1
        assert tx.scan('decisions_pending')[0]['status'] == 'deferred_pending_source_audit'
        assert len(tx.scan('research_discoveries')) == 1


@pytest.mark.parametrize('details', [
    {'source_url': 'https://github.com/fixture/repo'},
    {'proposal': {'accepted': True}},
    {'plan': {'origin': {'research_provenance': {'source_revision': 'a' * 40}}}},
    {'audit_id': 'inventoried', 'approval': {'accepted': True, 'actor': 'conductor'}},
])
def test_direct_dispatch_rejects_legacy_and_self_attested_approval(details):
    workflow = Workflow(MemoryStore(), organization())
    message = envelope('task.assign', 'conductor', 'lead:improvement', 'plan', details, 'fixture')
    with pytest.raises(ContractError, match='deferred'):
        workflow.submit(message)
    with pytest.raises(ContractError, match='deferred'):
        require_dispatch(details)


def test_incident_plan_preserved():
    workflow = Workflow(MemoryStore(), organization())
    message = envelope('task.assign', 'conductor', 'lead:improvement', 'plan',
                       {'objective': 'Repair incident', 'hook': {'id': 'hook'}}, 'fixture')
    assert workflow.submit(message)['status'] == 'queued'


def test_backlog_idempotent_and_preserves_legacy(audit, monkeypatch):
    service, _, _, _, _ = audit
    seeds = []
    for i in range(5):
        body = {'repository': f'https://github.com/fixture/repo{i}', 'revision': 'a' * 40,
                'files': [{'path': 'a'}, {'path': 'binary'}]}
        ref = service.artifacts.put(json.dumps(body), 'fixture')['ref']
        seeds.append({'repository': body['repository'], 'revision': body['revision'],
                      'files': 2, 'manifest_ref': ref})
    from types import SimpleNamespace
    monkeypatch.setattr('codex_harness.application.research.files', lambda _: SimpleNamespace(
        joinpath=lambda _: SimpleNamespace(read_text=lambda: json.dumps(seeds))))
    with service.store.transaction() as tx:
        tx.put('reference_audits', 'legacy', {'status': 'inventoried_not_reviewed'})
        for i, seed in enumerate(seeds):
            tx.put('reference_audits', str(i), seed)
    first = service.seed_backlog()
    assert service.seed_backlog() == first
    assert [r['priority'] for r in first] == list(range(1, 6))
    assert all(r['reviewed_paths'] == 0 and len(r['remaining_paths']) == 2 for r in first)
    with service.store.transaction() as tx:
        assert tx.get('reference_audits', 'legacy') == {'status': 'inventoried_not_reviewed'}
        assert not tx.scan('outbox')


def test_forged_receipt_cannot_advance_checkpoint(audit):
    service, record, _, _, _ = audit
    task, checkpoint = assigned_partition(service, record)
    ref = service.artifacts.put('model says command passed', 'fixture')['ref']
    record = PathDisposition(checkpoint.paths[0], 'binary', [ref], [], 'claimed inspection',
                             [], 'model', ['forged-runner-receipt'])
    with pytest.raises(ContractError, match='Runner receipt'):
        service.checkpoint(task, replace(checkpoint, remaining_paths=[]), [record], [])


def test_strict_wire_contract_rejects_unknown_fields_and_coercion(audit):
    from codex_harness.domain.research import parse_record
    source = audit[2]
    document = {'version': 1, 'kind': 'SourceIdentity', 'record': asdict(source)}
    assert parse_record(document) == source
    for field, value in [('version', True), ('commit', 123), ('extra', 'ignored')]:
        changed = {**document, 'record': {**document['record'], field: value}}
        with pytest.raises(ContractError):
            parse_record(changed)


def test_missing_execution_and_unresolved_subsystems_stay_remaining(audit):
    from codex_harness.domain.research import SubsystemAnalysis
    service, record, _, _, _ = audit
    ref = service.artifacts.put('subsystem evidence', 'fixture')['ref']
    trace = SubsystemAnalysis('core', [record['inventory'][0]['path']], ['contract'], ['main'],
        ['impl'], ['caller'], ['config'], ['git'], ['failure'], ['test'], [], [ref], [], [], [])
    with pytest.raises(ContractError, match='Missing execution'):
        trace.validate()
    trace = replace(trace, tests_not_run=[{'test': 'test', 'reason': 'isolation unavailable',
                                         'follow_up': 'run in verified runner'}])
    trace.validate()
    with service.store.transaction() as tx:
        tx.put('research_subsystems', 'fixture', {'audit_id': record['id'], 'record': asdict(trace)})
    assert service.coverage(record['id'])['remaining_subsystems'] == ['core']


@pytest.mark.parametrize('with_receipt', [False, True])
def test_unexecuted_subsystem_persists_but_cannot_complete_or_adopt(audit, with_receipt):
    from codex_harness.domain.research import SubsystemAnalysis
    service, record, source, _, _ = audit
    activate_fixture(service)
    proposal = complete_fixture_audit(service, record, source)
    with service.store.transaction() as tx:
        part = next(p for p in tx.scan('research_partitions') if p['subsystems'])
    message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
        {'audit_id': record['id'], 'partition_id': part['partition_id']}, 'partial-tests')
    service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture')
    assert task is not None
    service.propose(record['id'], proposal)
    approve_fixture(service, 'lead:research')
    approve_fixture(service, 'conductor')
    assert service.coverage(record['id'])['adoption_eligible']
    ref = service.artifacts.put('tests could not run', 'fixture')['ref']
    receipts = []
    if with_receipt:
        receipts = [service.execute(task, record['id'], ['source-list'])['id']]
    analysis = SubsystemAnalysis('core', [record['inventory'][0]['path']], ['contract'], ['main'],
        ['impl'], ['caller'], ['config'], ['git'], ['failure'], [], receipts, [ref], [], [],
        [{'test': 'upstream test suite', 'reason': 'isolation unavailable',
          'follow_up': 'run in verified runner'}])
    checkpoint = replace(PartitionCheckpoint(**part), remaining_subsystems=['core'])
    saved = service.checkpoint(task, checkpoint, [], [analysis])
    with service.store.transaction() as tx:
        row = next(r for r in tx.scan('research_subsystems') if r['audit_id'] == record['id'])
        assert row['record'] == asdict(analysis)
        assert any(r['record'] == asdict(analysis) for r in tx.scan('research_evidence_history'))
    coverage = service.coverage(record['id'])
    assert coverage['remaining_paths'] == []
    assert coverage['remaining_subsystems'] == ['core']
    assert not coverage['adoption_eligible']
    with pytest.raises(ContractError, match='Remaining work does not reconcile'):
        service.checkpoint(task, replace(PartitionCheckpoint(**saved), remaining_subsystems=[]), [], [analysis])
    with pytest.raises(ContractError, match='Audit coverage incomplete'):
        service.propose(record['id'], proposal)
    with pytest.raises(ContractError, match='Missing subsystem trace: tests'):
        replace(analysis, tests_not_run=[]).validate()
    for field in ('test', 'reason', 'follow_up'):
        unexplained = {**analysis.tests_not_run[0], field: ''}
        with pytest.raises(ContractError, match='Unexplained test not run'):
            replace(analysis, tests_not_run=[unexplained]).validate()


def test_checkpoint_history_retains_transitive_evidence(audit):
    import os

    from codex_harness.adapters.maintenance import ArtifactMaintenance
    service, record, _, entries, _ = audit
    task, checkpoint = assigned_partition(service, record)
    leaf = service.artifacts.put('original evidence', 'fixture')['ref']
    parent = service.artifacts.put(canonical({'original_ref': leaf}), 'fixture')['ref']
    p = PathDisposition(checkpoint.paths[0], 'semantic', [parent], ['symbol'], 'trace', [], '', [])
    service.checkpoint(task, replace(checkpoint, remaining_paths=[], cursor='next'), [p], [])
    for path in service.artifacts.root.glob('*.txt'):
        os.utime(path, (1, 1))
    ArtifactMaintenance(service.store, service.artifacts).collect(apply=True, days=1)
    assert service.artifacts.read(leaf) == 'original evidence'
    for entry in entries:
        service.artifacts.inspect(entry.artifact_ref)


class FixtureRunner:
    """Injected fixture receipts; these are not actual isolated or Codex verification."""
    def __init__(self, artifacts, blocked=False):
        self.artifacts, self.blocked = artifacts, blocked

    def execute(self, source, command):
        from codex_harness.domain.research import ExecutionReceipt
        output = self.artifacts.put('fixture inspection output', 'test-fixture')['ref']
        return ExecutionReceipt(source, 'fixture-env', command, 'fixture-isolation',
                                125 if self.blocked else 0, output, 'fixture-runner', self.blocked)

    def execute_assigned(self, source, command, task, workflow):
        return self.execute(source, command)


def activate_fixture(service, revision='audit', expected=None, enabled=True):
    from codex_harness.application.releases import Releases
    releases = Releases(service.store, service.workflow.org)
    candidate = {'revision': revision, 'tree': 'fixture-tree', 'base': 'fixture-base',
                 'author': 'worker:implementation'}
    if enabled:
        candidate['audit_lifecycle_version'] = 1
    release = releases.propose(candidate, {'checks': ['tests', 'cli_start', 'cli_file_task']})
    for actor in ('lead:improvement', 'conductor'):
        releases.review(release['id'], actor, revision, True, 'fixture-review')
    releases.verify(release['id'], revision, release['policy_hash'], {
        k: {'passed': True, 'evidence': 'fixture-canary-not-production'}
        for k in release['policy']['checks']})
    releases.promote(release['id'], expected)
    return releases, release


def complete_fixture_audit(service, record, source):
    from codex_harness.domain.research import AdaptationProposal, SubsystemAnalysis
    service.runner = FixtureRunner(service.artifacts)
    for part in service.partition(record['id'], 1):
        message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
            {'audit_id': record['id'], 'partition_id': part['partition_id']}, 'fixture')
        service.workflow.submit(message)
        task = service.workflow.claim('worker:github', 'fixture')
        receipt = service.execute(task, record['id'], ['fixture-inspection'])
        ref = receipt['receipt']['output_ref']
        paths = [PathDisposition(p, 'binary' if base64.b64decode(p).startswith(b'space') else 'semantic',
                    [ref], ['symbol'], 'fixture trace', [], 'fixture-inspection', [receipt['id']])
                 for p in part['paths']]
        systems = [SubsystemAnalysis(name, [e['path'] for e in record['inventory']], ['contract'],
            ['main'], ['impl'], ['caller'], ['config'], ['git'], ['failure'], [json.dumps(['fixture-inspection'])],
            [receipt['id']], [ref], [], [], []) for name in part['subsystems']]
        saved = service.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_paths=[],
                                   remaining_subsystems=[], cursor='done'), paths, systems)
        service.workflow.complete(task, saved)
    return AdaptationProposal(source, [e['path'] for e in record['inventory']], ['source:symbol'],
        'behavior', 'failures', ['harness:symbol'], 'overlap', 'boundaries', 'git/postgres',
        'six-w.v1', 'graph', 'attribution', 'license', 'dependencies', 'adapt', 'reason', 'worker:github')


def lease_review(service, actor):
    from datetime import datetime, timedelta, timezone
    with service.store.transaction() as tx:
        row = next(r for r in tx.scan('decisions_pending') if r['actor'] == actor and r['status'] == 'pending')
        row.update(status='running', generation=1, lease_owner='fixture', owner='fixture',
                   lease_until=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        tx.put('decisions_pending', row['id'], row)
        return {**row, '_bucket': 'decisions_pending'}


def approve_fixture(service, actor):
    from codex_harness.domain.research import IndependentReview
    task = lease_review(service, actor)
    receipt = service.execute(task, task['input']['audit_id'], ['fixture-independent-inspection'])
    review = IndependentReview(task['input']['binding'], actor, receipt['id'], True,
                               'license', 'deps', 'sre', 'architecture', 'graph')
    service.review(task, review)
    return task, review


@pytest.mark.parametrize('predecessor_enabled', [False, True])
def test_positive_lifecycle_dispatch_revalidation_and_rollback(audit, predecessor_enabled):
    from codex_harness.application.audit_gate import inspect_approval
    from codex_harness.application.scheduling import schedule_audits
    service, record, source, _, _ = audit
    _, previous = activate_fixture(service, 'old', enabled=predecessor_enabled)
    releases, active = activate_fixture(service, expected=previous['id'])
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    assert not service.coverage(record['id'])['adoption_eligible']
    approve_fixture(service, 'lead:research')
    assert not service.coverage(record['id'])['adoption_eligible']
    _, review = approve_fixture(service, 'conductor')
    assert service.coverage(record['id'])['adoption_eligible']
    details = {'audit_id': record['id'], 'audit_approval': review.binding, 'proposal': asdict(proposal)}
    with service.store.transaction() as tx:
        inspect_approval(tx, details, service.artifacts)
    # Includes an idempotent proposal scheduling event as well as adoption dispatch.
    schedule_audits(service.workflow)
    assert schedule_audits(service.workflow) == 0
    message = envelope('task.assign', 'conductor', 'lead:improvement', 'plan', details, 'fixture')
    service.workflow.submit(message)
    releases.rollback(active['id'], 'fixture rollback')
    assert service.workflow.claim('lead:improvement', 'fixture') is None
    assert not service.coverage(record['id'])['adoption_eligible']
    assert schedule_audits(service.workflow) == 0
    with service.store.transaction() as tx:
        assert tx.scan('research_evidence_history') and tx.scan('research_approvals')


@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_host_output_digests_are_not_artifact_edges_but_declared_children_are(audit, monkeypatch, damage):
    from codex_harness.adapters.source_execution import DockerSourceRunner
    service, record, source, _, _ = audit
    activate_fixture(service)
    child = service.artifacts.put('retained child evidence', 'fixture')['ref']
    def fixture_process(argv, timeout):
        return subprocess.CompletedProcess(argv, 0, 'fixture process; not an actual Docker execution', '')
    monkeypatch.setattr('codex_harness.adapters.source_execution.bounded_command', fixture_process)
    monkeypatch.setattr('codex_harness.adapters.source_execution.run_process', fixture_process)
    def structured_output(self, source, command):
        image = 'sha256:' + 'a' * 64
        receipt = DockerSourceRunner(self.artifacts.root.parent / 'host', self.artifacts).execute(
            source, command, image)
        output = {**self.artifacts.document(receipt.output_ref), 'artifact_refs': [child]}
        return replace(receipt, output_ref=self.artifacts.put(canonical(output), 'host-format-fixture')['ref'])
    monkeypatch.setattr(FixtureRunner, 'execute', structured_output)
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    approve_fixture(service, 'lead:research')
    approve_fixture(service, 'conductor')
    assert service.coverage(record['id'])['adoption_eligible']
    path = service.artifacts.root / (child[7:] + '.txt')
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text('changed evidence')
    assert not service.coverage(record['id'])['adoption_eligible']


@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
@pytest.mark.parametrize('include_audit_id', [False, True])
def test_checkpoint_only_evidence_survives_continuation_and_is_required_for_adoption(
        audit, damage, include_audit_id):
    from codex_harness.application.audit_gate import inspect_approval
    service, record, source, _, _ = audit
    activate_fixture(service)
    evidence = service.artifacts.put('checkpoint-only evidence', 'fixture')['ref']
    task, checkpoint = assigned_partition(service, record)
    saved = service.checkpoint(task, replace(checkpoint, evidence_refs=[evidence]), [], [])
    continued = service.checkpoint(task, replace(PartitionCheckpoint(**saved), evidence_refs=[]), [], [])
    assert evidence in continued['evidence_refs']
    service.workflow.complete(task, continued)
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    approve_fixture(service, 'lead:research')
    approve_fixture(service, 'conductor')
    assert service.coverage(record['id'])['adoption_eligible']
    with service.store.transaction() as tx:
        approval = next(r for r in tx.scan('research_approvals') if r['audit_id'] == record['id'])
        details = {'proposal': approval['proposal'], 'audit_approval': approval['binding']}
        if include_audit_id:
            details['audit_id'] = record['id']
        inspect_approval(tx, details, service.artifacts)
    path = service.artifacts.root / (evidence[7:] + '.txt')
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text('tampered checkpoint evidence')
    assert not service.coverage(record['id'])['adoption_eligible']
    with service.store.transaction() as tx:
        with pytest.raises((FileNotFoundError, ContractError)):
            inspect_approval(tx, details, service.artifacts)


@pytest.mark.parametrize('change', ['graph', 'evidence', 'receipt', 'review_receipt', 'policy', 'revision'])
def test_approval_invalidated_by_changed_binding(audit, change):
    service, record, source, _, _ = audit
    _, release = activate_fixture(service)
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    approve_fixture(service, 'lead:research')
    approve_fixture(service, 'conductor')
    assert service.coverage(record['id'])['adoption_eligible']
    with service.store.transaction() as tx:
        if change == 'graph':
            tx.put('research_control', 'graph', {'changed': True})
        elif change == 'evidence':
            row = tx.scan('research_paths')[0]
            row['record']['justification'] = 'changed'
            from codex_harness.domain.model import digest
            tx.put('research_paths', digest({'audit': record['id'], 'item': row['record']['path']}), row)
        elif change in {'receipt', 'review_receipt'}:
            key = (tx.scan('research_paths')[0]['record']['receipt_ids'][0] if change == 'receipt'
                   else tx.scan('research_reviews')[0]['review']['execution_id'])
            row = tx.get('research_receipts', key)
            row['receipt']['exit_status'] = 1
            tx.put('research_receipts', key, row)
        elif change == 'policy':
            row = tx.get('releases', release['id'])
            row['policy_hash'] = 'changed'
            tx.put('releases', release['id'], row)
        else:
            row = tx.get('deployment', 'active')
            row['revision'] = 'changed'
            tx.put('deployment', 'active', row)
    assert not service.coverage(record['id'])['adoption_eligible']


def observed(path, state='unreviewed_observed_asset', basis='observed', sha='a' * 64, refs=()):
    from codex_harness.domain.research import ObservedAsset
    return ObservedAsset(base64.b64encode(path.encode()).decode(), basis, state, sha, 10, list(refs))


def test_observed_assets_are_a_separate_completeness_ledger(audit):
    # FA-010: assets outside Git never enter the tracked denominator, yet block completion and adoption.
    from codex_harness.domain.research import ObservedAsset
    service, record, source, _, _ = audit
    activate_fixture(service)
    evidence = service.artifacts.put('observed asset review', 'fixture')['ref']
    before = service.coverage(record['id'])
    assert before['observed_assets'] == {'total': 0, 'pending': 0, 'pending_paths': [], 'states': {}}
    assert not before['whole_analysis_complete']
    result = service.observe_assets(record['id'], [
        observed('notes/uncommitted.md'), observed('.cache/index.json', 'generated_cache_metadata_only', 'cache', None),
        observed('sessions/private.jsonl', 'excluded_private_session_or_credential_surface', 'private_session', None),
        observed('vendor/nested/.git/HEAD', 'acquisition_pending', 'nested_repository', None)])
    assert result['changed'] == 4 and result['pending'] == 2
    coverage = service.coverage(record['id'])
    assert coverage['remaining_paths'] == before['remaining_paths'], 'the Git denominator is untouched'
    assert coverage['observed_assets']['states'] == {
        'acquisition_pending': 1, 'excluded_private_session_or_credential_surface': 1,
        'generated_cache_metadata_only': 1, 'unreviewed_observed_asset': 1}
    proposal = complete_fixture_audit(service, record, source)
    assert service.coverage(record['id'])['remaining_paths'] == []
    assert not service.coverage(record['id'])['whole_analysis_complete']
    with pytest.raises(ContractError, match='Observed assets await disposition'):
        service.propose(record['id'], proposal)
    # Idempotent re-observation leaves no history; a disposition advances with evidence.
    assert service.observe_assets(record['id'], [observed('notes/uncommitted.md')])['changed'] == 0
    with pytest.raises(ContractError, match='requires content hash and evidence'):
        service.observe_assets(record['id'], [observed('notes/uncommitted.md', 'semantically_reviewed')])
    service.observe_assets(record['id'], [observed('notes/uncommitted.md', 'semantically_reviewed', refs=[evidence]),
                                          observed('vendor/nested/.git/HEAD', 'excluded_private_session_or_credential_surface',
                                                   'nested_repository', None)])
    assert service.coverage(record['id'])['whole_analysis_complete']
    with pytest.raises(ContractError, match='cannot regress'):
        service.observe_assets(record['id'], [observed('notes/uncommitted.md')])
    with service.store.transaction() as tx:
        row = next(r for r in tx.scan('research_observed_assets')
                   if r['record']['path'] == observed('notes/uncommitted.md').path)
        assert [h['state'] for h in row['history']] == ['unreviewed_observed_asset']
    tracked = base64.b64encode(b'normal').decode()
    with pytest.raises(ContractError, match='belong to the inventory'):
        service.observe_assets(record['id'], [ObservedAsset(tracked, 'observed', 'unreviewed_observed_asset', None, None, [])])
    for bad in [observed('x', basis='mystery'), observed('x', state='done'), observed('/abs'), observed('a/../b'),
                observed('x', sha='zz')]:
        with pytest.raises(ContractError):
            service.observe_assets(record['id'], [bad])
    service.propose(record['id'], proposal)
    approve_fixture(service, 'lead:research')
    approve_fixture(service, 'conductor')
    assert service.coverage(record['id'])['adoption_eligible']
    # A new observed asset after approval changes the evidence binding and defers adoption.
    service.observe_assets(record['id'], [observed('notes/late.md')])
    assert not service.coverage(record['id'])['adoption_eligible']


def test_blocked_inspection_and_actor_spoof_cannot_approve(audit):
    from codex_harness.domain.research import IndependentReview
    service, record, source, _, _ = audit
    activate_fixture(service)
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    task = lease_review(service, 'lead:research')
    service.runner = FixtureRunner(service.artifacts, blocked=True)
    receipt = service.execute(task, record['id'], ['fixture-blocked-inspection'])
    review = IndependentReview(task['input']['binding'], 'lead:research', receipt['id'], True,
                               'license', 'deps', 'sre', 'architecture', 'graph')
    with pytest.raises(ContractError, match='Unauthorized'):
        service.review(task, replace(review, actor='conductor'))
    with pytest.raises(ContractError, match='Inspection-blocked'):
        service.review(task, review)
    assert service.review(task, replace(review, accepted=False))['status'] == 'inspection-blocked'
    with service.store.transaction() as tx:
        assert not tx.scan('research_approvals')
        assert tx.get('research_receipts', receipt['id'])


def test_scheduler_deduplicates_and_resumes_checkpoint_generation(audit):
    from codex_harness.application.scheduling import schedule_audits
    service, record, _, _, _ = audit
    partitions = service.partition(record['id'], 1)
    assert schedule_audits(service.workflow) == 0  # No unverified bootstrap activation.
    activate_fixture(service)
    assert schedule_audits(service.workflow) == len(partitions)
    assert schedule_audits(service.workflow) == 0
    with service.store.transaction() as tx:
        messages = [r['message'] for r in tx.scan('outbox')]
    for message in messages:
        service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture')
    with service.store.transaction() as tx:
        part = tx.get('research_partitions', task['message']['what']['details']['partition_id'])
    # Context exhaustion retains every remaining path and immutable checkpoint evidence.
    saved = service.checkpoint(task, replace(PartitionCheckpoint(**part), cursor='context-budget'), [], [])
    assert schedule_audits(service.workflow) == 0
    service.workflow.complete(task, saved)
    assert schedule_audits(service.workflow) == 1
    assert schedule_audits(service.workflow) == 0


def test_real_runner_failure_retains_command_evidence(audit, tmp_path, monkeypatch):
    from codex_harness.adapters.audit_runner import AuditRunner
    service, _, source, _, _ = audit
    # Exercise actual process startup with no bubblewrap on PATH; never weaken isolation.
    monkeypatch.setenv('PATH', str(tmp_path / 'absent-bin'))
    receipt = AuditRunner(tmp_path / 'runner', service.artifacts).execute(source, ['find', '.'])
    assert receipt.inspection_blocked and receipt.exit_status == 125
    output = service.artifacts.document(receipt.output_ref)
    assert output['argv'][0] == 'bwrap' and output['argv'][-2:] == ['find', '.']
    assert output['error']


def test_audit_activation_requires_candidate_checks_and_is_atomic(audit):
    from codex_harness.application.releases import Releases
    service = audit[0]
    releases = Releases(service.store, service.workflow.org)
    release = releases.propose({'revision': 'fixture', 'base': 'base', 'tree': 'tree',
        'author': 'worker:implementation', 'audit_lifecycle_version': 1}, {'checks': ['tests']})
    for actor in ('lead:improvement', 'conductor'):
        releases.review(release['id'], actor, 'fixture', True, 'fixture')
    releases.verify(release['id'], 'fixture', release['policy_hash'],
                    {'tests': {'passed': True, 'evidence': 'fixture'}})
    with pytest.raises(ContractError, match='CLI canary'):
        releases.promote(release['id'], None)
    with service.store.transaction() as tx:
        assert tx.get('deployment', 'active') is None
        assert tx.get('research_control', 'activation') is None


def test_corrupt_artifact_and_changed_provenance_block_dispatch(audit):
    from codex_harness.application.audit_gate import inspect_approval, require_adoption
    service, record, source, entries, _ = audit
    activate_fixture(service)
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    approve_fixture(service, 'lead:research')
    _, review = approve_fixture(service, 'conductor')
    details = {'audit_id': record['id'], 'audit_approval': review.binding}
    with service.store.transaction() as tx:
        with pytest.raises(ContractError, match='provenance'):
            require_adoption(tx, {**details, 'source_url': 'https://github.com/other/repo'})
    artifact = service.artifacts.root / (entries[0].artifact_ref[7:] + '.txt')
    artifact.write_text('corrupted')
    assert not service.coverage(record['id'])['adoption_eligible']
    with service.store.transaction() as tx:
        with pytest.raises(ContractError, match='modified'):
            inspect_approval(tx, details, service.artifacts)


def test_namespace_denial_preserves_evidence_and_never_changes_isolation(audit, tmp_path, monkeypatch):
    from codex_harness.adapters.audit_runner import AuditRunner
    service, _, source, _, _ = audit
    observed = []
    def denied(argv, timeout):
        observed.append(argv)
        return subprocess.CompletedProcess(argv, 1, '', 'bwrap: Creating new namespace failed: Operation not permitted')
    monkeypatch.setattr('codex_harness.adapters.audit_runner.run_process', denied)
    receipt = AuditRunner(tmp_path / 'runner', service.artifacts).execute(source, ['find', '.'])
    assert receipt.inspection_blocked
    assert len(observed) == 1 and '--unshare-all' in observed[0]
    assert 'namespace' in service.artifacts.document(receipt.output_ref)['stderr']


def test_acquire_pins_objects_without_checkout(audit, tmp_path, monkeypatch):
    from codex_harness.adapters.audit_runner import AuditRunner
    from codex_harness.domain.model import digest
    service, _, source, entries, git = audit
    runner = AuditRunner(tmp_path / 'acquired', service.artifacts)
    target = runner.root / digest({'repository': source.repository, 'commit': source.commit})
    subprocess.run(['git', 'clone', '--bare', service.verifier.repository, str(target)],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(target), 'remote', 'set-url', 'origin', source.repository],
                   check=True, capture_output=True)
    original = GitSourceVerifier.git
    commands = []
    def fixture_fetch(self, *args):
        if 'fetch' in args:
            commands.append(args)
            return b''  # Local fixture already has the exact objects; no network verification claimed.
        return original(self, *args)
    monkeypatch.setattr(GitSourceVerifier, 'git', fixture_fetch)
    acquired, actual, verifier = runner.acquire(source.repository, source.commit)
    assert acquired == source and actual == entries
    assert commands == []  # Exact cached objects can be verified without network access.
    assert not (target / 'normal').exists()
    assert verifier.verify(acquired, actual)['tree'] == source.tree


def test_reconcile_after_incumbent_promotion_preserves_pause(audit):
    service, _, _, _, _ = audit
    releases, release = activate_fixture(service)
    with service.store.transaction() as tx:
        tx.put('research_control', 'activation', {})
    assert releases.reconcile_audits()['release_id'] == release['id']
    with service.store.transaction() as tx:
        tx.put('research_control', 'activation', {'status': 'paused', 'release_id': release['id']})
    assert releases.reconcile_audits()['status'] == 'paused'


def test_reconcile_refuses_missing_canary(audit):
    service, _, _, _, _ = audit
    releases, release = activate_fixture(service)
    with service.store.transaction() as tx:
        tx.put('research_control', 'activation', {})
        row = tx.get('releases', release['id'])
        row['checks'].pop('cli_file_task')
        tx.put('releases', row['id'], row)
    with pytest.raises(ContractError, match='checks incomplete'):
        releases.reconcile_audits()


def queued_source_fixture(audit):
    from codex_harness.application.source_execution import SourceExecutions
    service, record, source, _, _ = audit
    _, release = activate_fixture(service)
    with service.store.transaction() as tx:
        tx.put('images', release['id'], {'id': release['id'], 'revision': 'audit',
                                       'image': 'sha256:' + 'a' * 64})
    message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
                       {'audit_id': record['id']}, 'host-runner-fixture')
    service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture-host')
    return SourceExecutions(service.workflow), service, source, task


def test_host_request_deduplicates_and_rejects_cross_source(audit):
    queue, _, source, task = queued_source_fixture(audit)
    request = queue.request(task, source, ['python', '--version'])
    assert queue.request(task, source, ['python', '--version']) == request
    with pytest.raises(ContractError, match='assignment mismatch'):
        queue.request(task, replace(source, repository='https://github.com/other/repo'), ['true'])
    row = queue.claim()
    assert row['id'] == request['id'] and row['image'] == 'sha256:' + 'a' * 64
    assert queue.claim() is None


@pytest.mark.parametrize('invalidate', ['pause', 'lease', 'deployment'])
def test_host_result_preserves_evidence_but_cannot_cross_invalidated_authority(audit, invalidate):
    queue, service, source, task = queued_source_fixture(audit)
    queue.request(task, source, ['true'])
    row = queue.claim()
    receipt = FixtureRunner(service.artifacts).execute(source, ['true'])
    with service.store.transaction() as tx:
        if invalidate == 'pause':
            tx.put('research_control', 'activation', {'status': 'paused'})
        elif invalidate == 'lease':
            current = tx.get('tasks', task['id'])
            tx.put('tasks', task['id'], {**current, 'generation': current['generation'] + 1})
        else:
            tx.put('deployment', 'active', {'release_id': 'changed'})
    queue.complete(row, receipt)
    with service.store.transaction() as tx:
        saved = tx.get('source_execution_requests', row['id'])
    assert saved['status'] == 'cancelled'
    assert saved['receipt']['output_ref'] == receipt.output_ref


def test_host_queue_pause_cancels_pending_without_execution(audit):
    queue, service, source, task = queued_source_fixture(audit)
    request = queue.request(task, source, ['true'])
    with service.store.transaction() as tx:
        tx.put('research_control', 'activation', {'status': 'paused'})
    assert queue.claim() is None
    with service.store.transaction() as tx:
        assert tx.get('source_execution_requests', request['id'])['status'] == 'cancelled'


def test_completed_host_receipt_rechecks_deployment_on_consumption(audit):
    queue, service, source, task = queued_source_fixture(audit)
    queue.request(task, source, ['true'])
    row = queue.claim()
    queue.complete(row, FixtureRunner(service.artifacts).execute(source, ['true']))
    assert queue.result(task, row['id'])['status'] == 'succeeded'
    with service.store.transaction() as tx:
        tx.put('deployment', 'active', {'release_id': 'changed-after-completion'})
    with pytest.raises(ContractError, match='superseded before consumption'):
        queue.result(task, row['id'])


@pytest.mark.parametrize('claimed_test', [['source-list'], ['python', 'unexecuted_test.py']])
def test_inventory_receipt_cannot_clear_claimed_test_coverage(audit, tmp_path, claimed_test):
    from codex_harness.adapters.audit_runner import AuditRunner
    from codex_harness.domain.research import SubsystemAnalysis
    service, record, _, _, _ = audit
    service.runner = AuditRunner(tmp_path / 'inert-runner', service.artifacts)
    part = next(p for p in service.partition(record['id']) if p['subsystems'])
    message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
        {'audit_id': record['id'], 'partition_id': part['partition_id']}, 'test-claim')
    service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture')
    receipt = service.execute(task, record['id'], ['source-list'])
    analysis = SubsystemAnalysis('core', [record['inventory'][0]['path']], ['contract'], ['main'],
        ['impl'], ['caller'], ['config'], ['git'], ['failure'], [json.dumps(claimed_test)],
        [receipt['id']], [receipt['receipt']['output_ref']], [], [], [])
    with pytest.raises(ContractError, match='Claimed test lacks'):
        service.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_subsystems=[]), [], [analysis])
    assert service.coverage(record['id'])['remaining_subsystems'] == ['core']


def test_host_restart_reclaims_expired_runner_and_fences_late_result(audit):
    from datetime import datetime, timedelta, timezone
    queue, service, source, task = queued_source_fixture(audit)
    queue.request(task, source, ['true'])
    first = queue.claim()
    with service.store.transaction() as tx:
        row = tx.get('source_execution_requests', first['id'])
        row['started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        tx.put('source_execution_requests', first['id'], row)
    second = queue.claim()
    assert second['owner'] != first['owner']
    queue.complete(first, FixtureRunner(service.artifacts).execute(source, ['true']))
    with service.store.transaction() as tx:
        assert tx.get('source_execution_requests', first['id'])['owner'] == second['owner']
        assert tx.get('source_execution_requests', first['id'])['status'] == 'running'
        assert len(tx.scan('source_execution_history')) == 1


def test_docker_source_runner_uses_only_inert_source_and_immutable_image(audit, tmp_path, monkeypatch):
    from codex_harness.adapters.source_execution import DockerSourceRunner
    service, _, source, _, _ = audit
    observed = []
    def run(argv, timeout):
        observed.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'fixture-only', '')
    monkeypatch.setattr('codex_harness.adapters.source_execution.bounded_command', run)
    monkeypatch.setattr('codex_harness.adapters.source_execution.run_process', run)
    receipt = DockerSourceRunner(tmp_path / 'host', service.artifacts).execute(
        source, ['python', '--version'], 'sha256:' + 'a' * 64)
    assert receipt.exit_status == 0 and not receipt.inspection_blocked
    argv = observed[0]
    assert argv[argv.index('--network') + 1] == 'none'
    assert '--read-only' in argv and '--pids-limit' in argv and '--cap-drop' in argv
    assert argv.count('-v') == 1 and argv[argv.index('-v') + 1].endswith(':/source:ro')
    assert argv[-5:] == ['--signal=KILL', '--', '120', 'python', '--version']
    assert observed[-1][:3] == ['docker', 'rm', '-f']


@pytest.mark.parametrize('legacy_control', [False, True])
def test_rollback_between_audit_releases_keeps_dispatch_paused(audit, legacy_control):
    from codex_harness.application.scheduling import schedule_audits

    service, record, _, _, _ = audit
    service.partition(record['id'], 1)
    releases, first = activate_fixture(service, revision='first')
    _, second = activate_fixture(service, revision='second', expected=first['id'])
    releases.rollback(second['id'], 'audit regression')
    with service.store.transaction() as tx:
        assert tx.get('deployment', 'active')['release_id'] == first['id']
        control = tx.get('research_control', 'activation')
        assert control['status'] == 'paused'
        assert control['rolled_back_release'] == second['id']
        if legacy_control:
            control.pop('release_id', None)
            control.pop('revision', None)
            tx.put('research_control', 'activation', control)
        retained = {table: tx.scan(table) for table in (
            'research_audits', 'research_partitions', 'research_evidence_history',
            'research_approvals', 'outbox', 'schedule')}
    for _ in range(2):
        assert schedule_audits(service.workflow) == 0
        assert releases.reconcile_audits() == control
    with service.store.transaction() as tx:
        assert tx.get('research_control', 'activation') == control
        assert {table: tx.scan(table) for table in retained} == retained
    # INV-RESEARCH-004: only another verified promotion lifts rollback containment.
    activate_fixture(service, revision='fixed', expected=first['id'])
    assert schedule_audits(service.workflow) > 0


@pytest.mark.parametrize('operation', ['proposal', 'review'])
def test_schema_preflight_failure_cannot_create_audit_success(audit, monkeypatch, operation):
    from types import SimpleNamespace

    from codex_harness.adapters.app_server import AppServer
    from codex_harness.adapters.audit_execution import AuditExecution
    from codex_harness.adapters.output_schema import CAUSE

    service, record, source, _, _ = audit
    executor = SimpleNamespace(service=SimpleNamespace(store=service.store),
                               artifacts=service.artifacts, workflow=service.workflow)
    execution = AuditExecution(executor, FixtureRunner(service.artifacts))
    server = AppServer(executable='fixture')
    sent = []
    monkeypatch.setattr(server, 'send', sent.append)

    cause = CAUSE

    def defective_turn(task, objective, evidence, schema):
        del schema['properties']['version']['type']
        return server.request('turn/start', {'outputSchema': schema})

    monkeypatch.setattr(execution, 'run_model', defective_turn)
    if operation == 'review':
        activate_fixture(service)
        proposal = complete_fixture_audit(service, record, source)
        service.propose(record['id'], proposal)
        task = lease_review(service, 'lead:research')
        with pytest.raises(ContractError, match=cause):
            execution.review(task)
    else:
        task = {'agent': 'worker:github', 'message': {'what': {'action': 'audit_propose',
                'details': {'audit_id': record['id']}}}}
        with pytest.raises(ContractError, match=cause):
            execution.execute(task)
    assert sent == []
    with service.store.transaction() as tx:
        assert not tx.scan('research_reviews')
        assert not tx.scan('research_proposal_runs')
        assert all(row['status'] != 'succeeded' for row in tx.scan('decisions_pending'))


def test_affected_records_still_validate_and_parse(audit):
    from jsonschema import ValidationError, validate

    from codex_harness.adapters.audit_execution import AuditExecution
    from codex_harness.domain.research import parse_record

    service, record, source, _, _ = audit
    activate_fixture(service)
    proposal = complete_fixture_audit(service, record, source)
    service.propose(record['id'], proposal)
    _, review = approve_fixture(service, 'lead:research')
    for kind, value in [('AdaptationProposal', proposal), ('IndependentReview', review)]:
        schema = AuditExecution.typed_schema(kind)
        body = asdict(value)
        validate(body, schema)
        assert parse_record({'version': 1, 'kind': kind, 'record': body}) == value
        for version in [0, 2, True, '1']:
            with pytest.raises(ValidationError):
                validate({**body, 'version': version}, schema)


@pytest.mark.parametrize('scope', ['paths', 'subsystems'])
def test_execution_scopes_output_and_checkpoints_partial_progress(audit, monkeypatch, scope):
    from types import SimpleNamespace

    from jsonschema import ValidationError, validate

    from codex_harness.adapters.audit_execution import AuditExecution
    from codex_harness.adapters.output_schema import preflight
    from codex_harness.domain.research import SubsystemAnalysis

    service, record, _, _, _ = audit
    activate_fixture(service)
    partitions = service.partition(record['id'])
    part = next(p for p in partitions if p[scope])
    message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
        {'audit_id': record['id'], 'partition_id': part['partition_id'],
         'generation': part['generation']}, 'scoped-output')
    service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture')
    executor = SimpleNamespace(service=SimpleNamespace(store=service.store),
                               artifacts=service.artifacts, workflow=service.workflow)
    execution = AuditExecution(executor, FixtureRunner(service.artifacts))
    ref = service.artifacts.put('partial semantic trace', 'fixture')['ref']
    path = asdict(PathDisposition(base64.b64encode(b'normal').decode(), 'semantic',
        [ref], ['symbol'], 'implementation and callers traced', [], '', []))
    subsystem = asdict(SubsystemAnalysis('core', [path['path']], ['contract'], ['main'],
        ['impl'], ['caller'], ['config'], ['git'], ['failure'], [], [], [ref], [], [],
        [{'test': 'upstream suite', 'reason': 'dependencies unavailable',
          'follow_up': 'run in verified runner'}]))
    answer = {'paths': [path] if scope == 'paths' else [],
              'subsystems': [subsystem] if scope == 'subsystems' else [],
              'open_questions': ['remaining work'], 'cursor': 'partial'}
    seen = []

    def run_model(task, objective, evidence, result_schema):
        seen.append(result_schema)
        if 'commands' in result_schema['properties']:
            return {'commands': []}
        assert evidence['partition'] == part
        assert 'partition.paths' in objective and 'partition.subsystems' in objective
        assert 'tests_not_run, not tests' in objective
        preflight(result_schema)
        for definition in result_schema['$defs'].values():
            if 'version' in definition['properties']:
                assert definition['properties']['version'] == {'type': 'integer', 'const': 1}
        validate(answer, result_schema)
        validate({**answer, 'paths': [], 'subsystems': []}, result_schema)
        # A supporting subsystem on a path-only partition is still forbidden.
        for invalid in ({**answer, 'paths': [path], 'subsystems': [subsystem]},
                        {**answer, scope: [{**(path if scope == 'paths' else subsystem),
                            ('path' if scope == 'paths' else 'name'): 'unassigned'}]}):
            with pytest.raises(ValidationError):
                validate(invalid, result_schema)
        return answer

    monkeypatch.setattr(execution, 'run_model', run_model)
    saved = execution.execute(task)
    assert len(seen) == 2 and saved['generation'] == part['generation'] + 1
    assert saved['paths'] == part['paths'] and saved['subsystems'] == part['subsystems']
    assert saved['remaining_paths'] == sorted(set(part['paths']) - {path['path']})
    assert saved['remaining_subsystems'] == part['subsystems']
    coverage = service.coverage(record['id'])
    assert len(coverage['remaining_paths']) == (2 if scope == 'paths' else 3)
    assert coverage['remaining_subsystems'] == ['core']
    assert not coverage['adoption_eligible']
    with service.store.transaction() as tx:
        assert all(tx.get('research_partitions', p['partition_id']) == p
                   for p in partitions if p['partition_id'] != part['partition_id'])
        bucket = 'research_paths' if scope == 'paths' else 'research_subsystems'
        assert [r['record'] for r in tx.scan(bucket)] == answer[scope]
        assert any(r['record'] == answer[scope][0] for r in tx.scan('research_evidence_history'))
    # INV-RESEARCH-002: bypassing output validation cannot bypass application scope gates.
    with pytest.raises(ContractError, match='Cross-partition evidence'):
        service.checkpoint(task, PartitionCheckpoint(**saved),
            [PathDisposition(**path)], [SubsystemAnalysis(**subsystem)])
    generic = AuditExecution.partition_schema()
    validate({**answer, 'paths': [path], 'subsystems': [subsystem]}, generic)
