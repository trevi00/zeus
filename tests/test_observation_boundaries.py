"""Output and evidence-inspection boundaries as observations (operating-portfolio-001, LOGGING.md).

An operator must be able to tell an output rejection, an inspection start, a completed refusal and a
failed inspection apart from correlated records, without reading a raw model stream. Every execution
below is a real `Executor.execute_one`: the transport is a labelled fixture seam (no provider, model,
network or Docker) and the results it returns are built by the production output classifier
(`completed_output`), while the executor, the Git workspace, the evidence inspector and its real
child processes, the Observer, the durable file spool, the Collector and the monitoring projection
are the production ones. Injected faults are labelled where they appear; none of this is operational
evidence of a live provider run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_git_workspace import repository

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.evidence_inspection import EvidenceInspector
from codex_harness.adapters.execution_output import completed_output
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.monitoring_observations import observation_facts
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.evidence_inspection import EvidenceInspections
from codex_harness.application.observations import Collector, MemoryDirectory, Observer
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.evidence import STATES
from codex_harness.domain.model import digest, envelope
from codex_harness.domain.observation import REGISTRY, safe_code
from codex_harness.domain.observation import new_process_run_id as run_id

PY = sys.executable
CANARY = 'CANARY-8b7a6c5d4e3f2019283746556677889a'  # injected fault marker; never a real secret
PASSING_CLAIM = f'{PY} -c "import sys; sys.exit(0)"'
OUTPUT_EVALUATED = 'development.output_evaluated'
STARTED = 'development.evidence_inspection_started'
FINISHED = 'development.evidence_inspection_finished'


def inspection_policy():
    """A replay policy that authorizes exactly this file's claim; the packaged one is untouched."""
    return {'version': 1,
            'replay': {'allowed_argv_prefixes': [[PY, '-c']], 'per_command_seconds': 20,
                       'total_seconds': 60, 'max_claims': 8, 'max_output_bytes': 4096,
                       'replays_per_claim': 1},
            'files': {'max_bytes': 1024 * 1024}}


def turn(text, schema, model):
    """What a transport returns for one completed turn: the production output classifier's own
    result, plus the transport fields the executor reads (the app_server shape)."""
    output = completed_output(text, schema)
    base = {'events': [], 'thread_id': 'thread', 'turn_id': 'turn', 'usage': None, 'rotate': False,
            'interrupted': False, 'requested_model': model}
    if output.get('failure'):
        return {**output, **base}
    return {'answer': output['answer'], 'model_answer_text': text, **base}


def answer_text(claims=(), summary='fixture implementation'):
    return json.dumps({'summary': summary, 'tests': list(claims)})


def build(tmp_path, monkeypatch, produce):
    """One real implement execution against a durable spool, a real collector and the projection."""
    root = repository(tmp_path)
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    service = Harness(MemoryStore(), organization())
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    runtime_root = tmp_path / 'runtime'
    spool_root = runtime_root / 'observations'
    directory = SpoolDirectory(spool_root)
    observer = Observer(service.store, FileSpool(spool_root, run_id(), max_bytes=1 << 20, fsync=False),
                        component='executor', directory=directory, alert_window_seconds=0)
    executor = Executor(service, git, artifacts, observer=observer)
    executor.evidence = EvidenceInspections(service.store, EvidenceInspector(artifacts, inspection_policy()))
    collector = Collector(service.store, directory, validate=validate_observation, observer=observer)

    class Runtime:
        """Fixture seam: no provider, no network. The result shape is the production classifier's."""

        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

        def run(self, prompt, cwd, schema, timeout, **kwargs):
            Path(cwd, 'change.txt').write_text('implemented', encoding='utf-8')
            return produce(schema, kwargs.get('model'))

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    message = envelope('task.assign', organization().actor('worker:implementation').parent,
                       'worker:implementation', 'implement',
                       {'plan': {'objective': 'fixture', 'acceptance_criteria': ['x'],
                                 'allowed_paths': ['change.txt']}}, 'corr-boundaries', None)
    message['where']['revision'] = git._git('rev-parse', 'HEAD')
    task = executor.workflow.submit(message)
    return SimpleNamespace(executor=executor, service=service, store=service.store, observer=observer,
                           collector=collector, artifacts=artifacts, task=task, runtime=runtime_root)


def collect(s):
    """Drain the durable spool through the real collector and return the stored observation rows."""
    summary = s.collector.collect()
    with s.store.transaction() as tx:
        rows = [row for row in tx.scan('observations')]
    rows.sort(key=lambda row: (row['sequence']['number'] is None, row['sequence']['number'] or 0))
    return summary, rows


def by_type(rows, event_type):
    return [row for row in rows if row['event_type'] == event_type]


def one(rows, event_type):
    [row] = by_type(rows, event_type)
    return row


# ---- the registry itself ------------------------------------------------------------------------

def test_the_three_boundary_events_are_declared_with_typed_scalar_allow_lists():
    for event_type in (OUTPUT_EVALUATED, STARTED, FINISHED):
        allowed = REGISTRY[event_type]
        assert allowed and all(kind in ('string', 'integer', 'boolean', 'number', 'nullable_string',
                                        'nullable_integer') for kind in allowed.values())
    assert 'prompt' not in REGISTRY[OUTPUT_EVALUATED] and 'answer' not in REGISTRY[OUTPUT_EVALUATED]
    # Every inspection state has a declared count: a new state would otherwise make the sink refuse
    # the whole finished event instead of reporting it.
    assert set(STATES) <= set(REGISTRY[FINISHED])


def test_an_unknown_code_never_becomes_a_zeus_code_and_an_absent_one_never_becomes_a_value():
    assert safe_code('schema_mismatch', ('schema_mismatch',)) == 'schema_mismatch'
    assert safe_code('vendor-brand-new-state', ('schema_mismatch',)) == 'unknown'
    assert safe_code(None, ('schema_mismatch',)) == 'none'
    assert safe_code(None, ('checked',), absent='unreported') == 'unreported'
    assert safe_code(7, ('checked',)) == 'unknown'


# ---- accepted output, checked evidence ----------------------------------------------------------

def test_an_accepted_answer_and_its_checked_inspection_are_one_correlated_story(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, lambda schema, model: turn(answer_text([PASSING_CLAIM]), schema, model))
    row = s.executor.execute_one('worker:implementation')
    assert row['status'] == 'succeeded', row.get('error')
    inspection = row['result']['evidence_inspection']
    assert inspection['verdict'] == 'all_checked' and inspection['denominator']['checked'] == 1
    summary, rows = collect(s)
    assert summary['inserted'] == summary['records'] and summary['corrupt'] == summary['refused'] == 0

    evaluated, started, finished = (one(rows, name) for name in (OUTPUT_EVALUATED, STARTED, FINISHED))
    for event in (evaluated, started, finished):
        validate_observation({k: v for k, v in event.items() if k not in
                              {'payload_hash', 'record_kind', 'audit_confirmed', 'collected_at', 'spool', 'authority'}})
        assert event['correlation_id'] == 'corr-boundaries' and event['causation_id'] == s.task['id']
        assert event['execution']['task_id'] == s.task['id'] and event['execution']['bucket'] == 'tasks'
        assert (event['execution']['generation'], event['execution']['attempt']) == (1, 1)
        assert event['execution']['role'] == 'worker:implementation' and event['category'] == 'development'
    assert evaluated['outcome'] == 'succeeded' and evaluated['severity'] == 'info'
    assert evaluated['reason_code'] == 'output_accepted'
    assert evaluated['attributes'] == {'reservation_id': evaluated['attributes']['reservation_id'],
                                       'invocation_outcome': 'accepted', 'output_reason': 'none',
                                       'provider_cause': 'none', 'terminal_subtype': 'none',
                                       'failure_owner': 'none', 'json_check': 'unreported',
                                       'schema_check': 'unreported', 'execution_failure': False}
    assert evaluated['evidence_refs'] == [row['result']['execution_ref']]
    assert started['outcome'] == 'started' and started['attributes'] == {'claims': 1}
    assert finished['outcome'] == 'succeeded' and finished['severity'] == 'info'
    assert finished['reason_code'] == 'evidence_all_checked'
    assert finished['attributes']['verdict'] == 'all_checked' and finished['attributes']['claims'] == 1
    assert finished['attributes']['inspection_id'] == inspection['inspection_id']
    assert finished['attributes']['checked'] == 1 and finished['attributes']['findings'] == 1
    assert finished['attributes']['not_checked'] == finished['attributes']['error'] == 0
    assert finished['attributes']['error_type'] is None and finished['attributes']['message_sha256'] is None
    assert finished['attributes']['elapsed_seconds'] >= 0.0
    # The evaluated output precedes the inspection of the claims it carried, and both precede nothing
    # that was invented for them: the ordering is the spool's own sequence.
    order = [r['event_type'] for r in rows]
    assert order.index(OUTPUT_EVALUATED) < order.index(STARTED) < order.index(FINISHED)
    assert order.index('development.provider_finished') < order.index(OUTPUT_EVALUATED)


# ---- refused output -------------------------------------------------------------------------

def test_a_schema_rejection_is_a_named_failure_with_a_durable_link_and_no_property_names(tmp_path, monkeypatch):
    """The answer is valid JSON and the wrong shape: a real `schema_mismatch` from the real validator."""
    s = build(tmp_path, monkeypatch,
              lambda schema, model: turn(json.dumps({'summary': 17, 'tests': []}), schema, model))
    row = s.executor.execute_one('worker:implementation')
    assert row['status'] != 'succeeded' and row.get('result') is None, 'the refusal stays a refusal'
    _, rows = collect(s)
    evaluated = one(rows, OUTPUT_EVALUATED)
    assert evaluated['outcome'] == 'failed' and evaluated['severity'] == 'error'
    assert evaluated['reason_code'] == 'output_schema_mismatch'
    assert evaluated['attributes']['invocation_outcome'] == 'invalid_output'
    assert evaluated['attributes']['output_reason'] == 'schema_mismatch'
    assert evaluated['attributes']['failure_owner'] == 'agent_output'
    assert evaluated['attributes']['json_check'] == 'checked' and evaluated['attributes']['schema_check'] == 'failed'
    assert evaluated['attributes']['provider_cause'] == 'none', 'an output defect is not a provider failure'
    assert evaluated['attributes']['execution_failure'] is True
    # The durable receipt exists before the event names it, and the event carries the link, not the answer.
    [ref] = evaluated['evidence_refs']
    stored = json.loads(s.artifacts.read(ref))
    assert stored['failure']['output_reason'] == 'schema_mismatch'
    text = json.dumps(evaluated)
    for leaked in ('summary', 'tests', 'instance_path', 'schema_path', 'properties', 'is not of type'):
        assert leaked not in text, leaked
    assert not by_type(rows, STARTED) and not by_type(rows, FINISHED), 'a refused output reaches no inspection'


@pytest.mark.parametrize('cause, subtype, owner, expected_cause, expected_subtype, expected_owner', [
    ('claude-provider-timeout', None, 'provider', 'claude-provider-timeout', 'none', 'provider'),
    ('claude-provider-error-result', 'error_max_turns', 'provider', 'claude-provider-error-result',
     'error_max_turns', 'provider'),
    ('vendor-retry-budget-spent', 'error_vendor_specific', 'vendor', 'unknown', 'unknown', 'unknown'),
])
def test_a_provider_failure_keeps_its_own_code_and_a_foreign_one_stays_unknown(
        tmp_path, monkeypatch, cause, subtype, owner, expected_cause, expected_subtype, expected_owner):
    """A provider failure reported by the transport; the third row is a LABELLED synthetic future code."""
    failure = {'cause': cause, 'owner': owner, 'kind': 'provider', 'stop_reason': 'deadline'}
    if subtype is not None:
        failure['result_subtype'] = subtype
    s = build(tmp_path, monkeypatch, lambda schema, model: {
        'answer': None, 'model_answer_text': '', 'failure': failure, 'events': [], 'thread_id': 'thread',
        'turn_id': 'turn', 'usage': None, 'rotate': False, 'interrupted': False, 'requested_model': model})
    row = s.executor.execute_one('worker:implementation')
    assert row['status'] != 'succeeded'
    _, rows = collect(s)
    evaluated = one(rows, OUTPUT_EVALUATED)
    assert evaluated['attributes']['invocation_outcome'] == 'provider_failure'
    assert evaluated['attributes']['provider_cause'] == expected_cause
    assert evaluated['attributes']['terminal_subtype'] == expected_subtype
    assert evaluated['attributes']['failure_owner'] == expected_owner
    assert evaluated['outcome'] == 'failed' and evaluated['severity'] == 'error'
    assert evaluated['reason_code'] == 'output_provider_failure'
    # Nothing about the output itself is invented from a provider subtype.
    assert evaluated['attributes']['output_reason'] == 'none'
    assert evaluated['attributes']['json_check'] == evaluated['attributes']['schema_check'] == 'unreported'
    if expected_cause == 'unknown':
        text = json.dumps(evaluated)
        assert cause not in text and subtype not in text and owner not in text


# ---- empty and failed evidence -------------------------------------------------------------------

def test_an_answer_without_claims_is_recorded_as_no_claims_and_never_as_success(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, lambda schema, model: turn(answer_text([]), schema, model))
    row = s.executor.execute_one('worker:implementation')
    assert row['result']['evidence_inspection']['verdict'] == 'no_claims'
    _, rows = collect(s)
    started, finished = one(rows, STARTED), one(rows, FINISHED)
    assert started['attributes'] == {'claims': 0}
    assert finished['outcome'] == 'blocked' and finished['severity'] == 'warning'
    assert finished['reason_code'] == 'evidence_no_claims'
    assert finished['attributes']['verdict'] == 'no_claims' and finished['attributes']['findings'] == 0
    assert finished['attributes']['checked'] == 0
    assert 'succeeded' not in {event['outcome'] for event in (started, finished)}
    # The task completing is a different fact from the evidence being checked, and it says so.
    assert one(rows, 'development.task_completed')['attributes']['status'] == 'succeeded'


def test_an_unchecked_claim_is_incomplete_and_the_denominator_says_why(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch,
              lambda schema, model: turn(answer_text([PASSING_CLAIM, 'rm -rf build']), schema, model))
    row = s.executor.execute_one('worker:implementation')
    assert row['result']['evidence_inspection']['verdict'] == 'incomplete'
    finished = one(collect(s)[1], FINISHED)
    assert finished['outcome'] == 'blocked' and finished['reason_code'] == 'evidence_incomplete'
    assert finished['attributes']['claims'] == 2 and finished['attributes']['checked'] == 1
    assert finished['attributes']['not_checked'] == 1


def test_a_failed_inspection_is_unknown_and_its_exception_text_reaches_no_surface(tmp_path, monkeypatch):
    """INJECTED fault: the recorded inspection raises. The canary stands for any foreign message."""
    s = build(tmp_path, monkeypatch, lambda schema, model: turn(answer_text([PASSING_CLAIM]), schema, model))

    def explode(*args, **kwargs):
        raise RuntimeError('inspection ledger unavailable ' + CANARY)

    monkeypatch.setattr(s.executor.evidence, 'inspect', explode)
    row = s.executor.execute_one('worker:implementation')
    inspection = row['result']['evidence_inspection']
    assert inspection['verdict'] == 'inspection_error' and inspection['claims'] == 1
    assert inspection['cause'] == 'RuntimeError: message_sha256=' + digest(
        'inspection ledger unavailable ' + CANARY)[:16]
    summary, rows = collect(s)
    finished = one(rows, FINISHED)
    assert finished['outcome'] == 'unknown' and finished['severity'] == 'error'
    assert finished['reason_code'] == 'evidence_inspection_error'
    assert finished['attributes']['verdict'] == 'inspection_error'
    assert finished['attributes']['error_type'] == 'RuntimeError'
    assert finished['attributes']['message_sha256'] == digest('inspection ledger unavailable ' + CANARY)[:16]
    assert finished['attributes']['inspection_id'] is None and finished['attributes']['findings'] is None
    assert finished['attributes']['checked'] is None, 'no count is invented for an inspection that did not run'
    assert by_type(rows, STARTED), 'the start is still recorded; only the verdict is unknown'
    facts = observation_facts(s.store, s.runtime, datetime.now(timezone.utc))
    with s.store.transaction() as tx:
        stored = json.dumps([tx.scan(bucket) for bucket in ('observations', 'observation_audit', 'tasks')])
    assert CANARY not in json.dumps(row) and CANARY not in json.dumps(rows)
    assert CANARY not in stored and CANARY not in json.dumps(facts, default=str)
    assert CANARY not in json.dumps(s.observer.health())
    assert summary['inserted'] == summary['records']


# ---- collection and projection ---------------------------------------------------------------------

def test_the_boundary_events_reach_the_monitoring_projection_and_replay_adds_no_second_count(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, lambda schema, model: turn(answer_text([PASSING_CLAIM]), schema, model))
    s.executor.execute_one('worker:implementation')
    first, rows = collect(s)
    assert first['inserted'] >= 3 and first['duplicates'] == 0
    projected = observation_facts(s.store, s.runtime, datetime.now(timezone.utc))
    seen = {event['event_type']: event for event in projected['events']['rows']}
    assert {OUTPUT_EVALUATED, STARTED, FINISHED} <= set(seen)
    assert seen[OUTPUT_EVALUATED]['reason_code'] == 'output_accepted'
    assert seen[FINISHED]['reason_code'] == 'evidence_all_checked'
    for name in (OUTPUT_EVALUATED, STARTED, FINISHED):
        assert seen[name]['execution']['task_id'] == s.task['id'] and seen[name]['correlation_id'] == 'corr-boundaries'
        assert seen[name]['record_kind'] == 'collected' and 'attributes' not in seen[name]
    assert seen[OUTPUT_EVALUATED]['evidence_refs'] == one(rows, OUTPUT_EVALUATED)['evidence_refs']
    assert projected['local']['status'] == 'ok' and projected['authority'] == 'informational_only'
    # A second pass over the same spool counts these events no second time; what it does add is the
    # collector's own receipt event for the first pass, which is a different fact.
    known = {row['event_id'] for row in rows}
    second = s.collector.collect()
    assert second['conflicts'] == 0
    with s.store.transaction() as tx:
        after = [row for row in tx.scan('observations')]
    boundary = [row for row in after if row['event_type'] in {OUTPUT_EVALUATED, STARTED, FINISHED}]
    assert len(boundary) == 3 and len({row['event_id'] for row in boundary}) == 3
    assert {row['event_type'] for row in after if row['event_id'] not in known} <= {'operations.collection_completed'}


def test_a_refused_spool_write_is_counted_and_the_execution_still_completes(tmp_path, monkeypatch):
    """INJECTED fault: the diagnostic path is best effort, so a full spool costs events, not the task."""
    s = build(tmp_path, monkeypatch, lambda schema, model: turn(answer_text([PASSING_CLAIM]), schema, model))
    s.observer.spool = _FullSpool(s.observer.spool.process_run_id)
    s.observer.directory = MemoryDirectory()
    row = s.executor.execute_one('worker:implementation')
    assert row['status'] == 'succeeded', row.get('error')
    assert row['result']['evidence_inspection']['verdict'] == 'all_checked'
    assert s.observer.counters['dropped_spool_full'] > 0
    assert s.observer.counters['emitted'] == 0, 'nothing was spooled, and the health counters say so'
    with s.store.transaction() as tx:
        audited = {audit['event_type'] for audit in tx.scan('observation_audit')}
    assert 'development.invocation_reserved' in audited, 'the mandatory audit path is untouched'


class _FullSpool:
    """INJECTED fault seam: a spool that is always full (the Observer's no-raise contract)."""

    process_run_id: str
    max_bytes = 1

    def __init__(self, process_run_id):
        self.process_run_id = process_run_id

    def append(self, kind, event):
        from codex_harness.ports import SpoolFull
        raise SpoolFull('injected full spool')

    def size(self):
        return 1

    def close(self):
        return None
