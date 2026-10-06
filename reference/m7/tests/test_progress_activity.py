"""S2b domain and collector (FLEET-S2B-SPEC §2/§4/§5, matrix S2B-3/4/5/14/15/16/18): the compact activity receipt
contract, the fixed S1a label vocabulary, the monitor's compact-path selection and retention by the existing sweep.
Every receipt, row and lane is a labelled synthetic FIXTURE on a temporary artifact root; nothing runs a provider."""
import hashlib
import json
import os
import time

import pytest

from codex_harness.adapters import monitoring
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.maintenance import ArtifactMaintenance
from codex_harness.adapters.monitoring import ArtifactReader, execution_activity
from codex_harness.adapters.store import MemoryStore
from codex_harness.domain.model import canonical
from codex_harness.domain.progress_activity import (
    ACTIVITY_SCHEMA,
    ActivityInvalid,
    build_receipt,
    claude_result_status,
    fixed_completed_status,
    fixed_completed_type,
    fixed_last_event,
    validate_receipt,
)

CANARY = 'CANARY-s2b-domain'
NOW_ISO = '2026-09-28T01:00:00+00:00'
RAW = 'sha256:' + 'a' * 64


def claude(kind, **fields):
    return {'provider': 'claude-code-cli', 'stream': 'stdout', 'type': kind, 'raw_type': 'assistant',
            'subtype': CANARY, 'id': 'toolu_' + CANARY, 'status': None, 'tool': None, 'text': CANARY,
            'raw': {'message': CANARY}, **fields}


def receipt(**overrides):
    base = dict(execution='task-1', transport='claude_cli', event=claude('tool_started', status='started', tool='Read'),
                activity_sequence=1, progress_sequence=None, generation=2, attempt=1, collected_at=NOW_ISO, raw_ref=None)
    return build_receipt(**{**base, **overrides})


# ----- S2B-3 / S2B-5 the exact contract --------------------------------------------------------------------------------
def test_a_start_record_is_a_new_fifteen_key_object_with_nothing_from_the_payload():
    document = receipt()
    assert set(document) == {'schema', 'execution', 'transport', 'event_label', 'tool_name', 'item_type', 'status',
                             'activity_sequence', 'progress_sequence', 'generation', 'attempt', 'collected_at',
                             'occurred_at', 'raw_ref'} and len(document) == 14
    assert document['schema'] == ACTIVITY_SCHEMA and document['tool_name'] == 'Read' and document['occurred_at'] is None
    assert CANARY not in canonical(document)


@pytest.mark.parametrize('overrides,code', [
    ({'activity_sequence': 0}, 'activity_sequence'), ({'activity_sequence': True}, 'activity_sequence'),
    ({'generation': -1}, 'generation'), ({'attempt': 1.0}, 'attempt'), ({'execution': ''}, 'execution'),
    ({'collected_at': '2026-09-28T01:00:00'}, 'collected_at'), ({'collected_at': 'soon'}, 'collected_at'),
    ({'progress_sequence': 1}, 'start_raw'), ({'raw_ref': RAW}, 'start_raw'), ({'transport': 'other'}, 'not_activity'),
    ({'execution': 'x' * 70000}, 'too_large'),
])
def test_invalid_internal_metadata_is_refused_with_a_fixed_code(overrides, code):
    with pytest.raises(ActivityInvalid) as refused:
        receipt(**overrides)
    assert refused.value.code == code and CANARY not in str(refused.value)


def test_a_raw_backed_record_needs_its_raw_ref_and_progress_sequence_and_a_claude_time_is_never_taken():
    event = claude('tool_completed', status='completed', occurred_at_ms=1790550000000)
    document = receipt(event=event, progress_sequence=3, raw_ref=RAW)
    assert (document['progress_sequence'], document['raw_ref'], document['occurred_at']) == (3, RAW, None)
    for bad in ({'raw_ref': None}, {'raw_ref': 'sha256:ABC'}, {'progress_sequence': None}):
        with pytest.raises(ActivityInvalid):
            receipt(event=event, **{'progress_sequence': 3, 'raw_ref': RAW, **bad})


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(extra=1), lambda d: d.pop('raw_ref'), lambda d: d.update(schema='urn:x'),
    lambda d: d.update(tool_name=['Read']), lambda d: d.update(tool_name='mcp__x'), lambda d: d.update(status={'a': 1}),
    lambda d: d.update(event_label='message'), lambda d: d.update(item_type='commandExecution'),
    lambda d: d.update(occurred_at=NOW_ISO), lambda d: d.update(collected_at='2026-09-28T10:00:00+09:00'),
])
def test_every_reader_rejects_a_record_off_the_exact_contract_without_raising_anything_else(mutation):
    document = dict(receipt())
    mutation(document)
    with pytest.raises(ActivityInvalid):
        validate_receipt(document)


def test_codex_items_keep_only_the_fixed_category_status_and_occurrence():
    event = {'method': 'item/completed', 'params': {'item': {'id': CANARY, 'type': 'mcpToolCall', 'status': CANARY,
                                                            'server': CANARY}, 'completedAtMs': 1790550000000}}
    document = receipt(transport='app_server', event=event, progress_sequence=1, raw_ref=RAW)
    assert (document['event_label'], document['item_type'], document['status'], document['tool_name']) == (
        'item_completed', 'mcpToolCall', 'unknown', None)
    assert document['occurred_at'] == '2026-09-27T23:00:00+00:00' and CANARY not in canonical(document)


# ----- S2B-4 D9 --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('status,raw,expected', [
    ('success', {'is_error': False}, 'success'), ('success', {}, 'success'), ('success', {'is_error': True}, 'error'),
    ('success', {'is_error': [0]}, 'error'), ('success', {'is_error': 'no'}, 'error'), ('success', {'is_error': 0}, 'success'),
    ('error_during_execution', {'is_error': False}, 'error'), ('success', None, 'unknown'), ('success', [1], 'unknown'),
])
def test_the_claude_result_rule_reads_only_the_truthiness_of_is_error(status, raw, expected):
    assert claude_result_status({'status': status, 'raw': raw}) == expected


# ----- S2B-16 fixed S1a labels -----------------------------------------------------------------------------------------
@pytest.mark.parametrize('value,expected', [
    ('item/completed', 'item/completed'), ('thread/tokenUsage/updated', 'thread/tokenUsage/updated'),
    ('claude/system/init', 'claude/system/init'), ('claude/system/' + CANARY, 'claude/system'),
    ('claude/result/success', 'claude/result'), ('claude/assistant', 'claude/assistant'),
    ('claude/' + CANARY, 'unknown'), ('turn/' + CANARY, 'unknown'), (None, None), (['x'], 'unknown'),
])
def test_last_event_keeps_only_the_fixed_vocabulary(value, expected):
    assert fixed_last_event(value) == expected


def test_completed_type_and_status_collapse_to_fixed_values():
    assert [fixed_completed_type(v) for v in ('result', 'commandExecution', CANARY, None, 3)] == [
        'result', 'commandExecution', 'unknown', None, 'unknown']
    assert [fixed_completed_status(v) for v in ('success', 'error_max_turns', CANARY, None, {'a': 1})] == [
        'success', 'error', 'unknown', None, 'unknown']


# ----- S2B-14 / S2B-15 the collector ------------------------------------------------------------------------------------
def store_text(root, text) -> str:
    data = text.encode('utf-8')
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(data).hexdigest()
    (root / (key + '.txt')).write_bytes(data)
    return 'sha256:' + key


class Spy:
    def __init__(self, root):
        self.inner, self.calls = ArtifactReader(root), []

    def read(self, reference):
        self.calls.append(reference)
        return self.inner.read(reference)


def row(status='running'):
    return {'id': 'task-1', 'status': status, 'generation': 2, 'attempt': 1, 'completed_at': None}


def compact_progress(ring, sequence=3, watermark=3, **extra):
    return {'id': 'task-1', 'recent': ['sha256:' + 'e' * 64], 'last_record': 'sha256:' + 'e' * 64, 'generation': 2,
            'attempt': 1, 'sequence': sequence, 'collected_at': NOW_ISO, 'activity_recent': ring,
            'activity_sequence': len(ring), 'activity_progress_sequence': watermark, **extra}


def test_a_synchronized_compact_ring_is_read_instead_of_the_raw_ring_and_raw_ref_is_never_followed(tmp_path):
    root = tmp_path / 'artifacts'
    start = store_text(root, canonical(receipt()))
    other = store_text(root, canonical(receipt(execution='task-OTHER', activity_sequence=2)))
    corrupt = store_text(root, '{"schema": ')
    shaped = store_text(root, canonical({**receipt(activity_sequence=3), 'extra': CANARY}))
    reader = Spy(root)
    status, items = execution_activity(row(), compact_progress([start, other, corrupt, shaped]), reader,
                                       monitoring.datetime.fromisoformat(NOW_ISO))
    assert reader.calls == [start, other, corrupt, shaped], 'members only: no raw ring, no raw_ref'
    assert status == 'ok' and all(item['source'] == 'activity_receipt' for item in items)
    assert [(i['state'], i['error_type']) for i in items] == [('ok', None), ('unreadable', 'binding_mismatch'),
                                                               ('unreadable', 'invalid_json'), ('malformed', 'invalid_shape')]
    first = items[0]
    assert (first['event_label'], first['tool_name'], first['activity_sequence'], first['sequence'],
            first['collected_at'], first['generation'], first['attempt']) == ('tool_started', 'Read', 1, None, NOW_ISO, 2, 1)
    assert CANARY not in json.dumps(items)


@pytest.mark.parametrize('progress_overrides,compact', [
    ({}, True), ({'activity_progress_sequence': None}, False), ({'activity_progress_sequence': 2}, False),
    ({'activity_progress_sequence': True, 'sequence': 1}, False), ({'activity_recent': []}, False),
    ({'activity_recent': 'sha256:x'}, False),
])
def test_the_compact_ring_is_selected_only_when_it_is_synchronized_with_the_raw_sequence(tmp_path, progress_overrides, compact):
    root = tmp_path / 'artifacts'
    start = store_text(root, canonical(receipt()))
    legacy = store_text(root, json.dumps({'event': claude('tool_completed', status='completed'), 'malformed': False,
                                          'defect': None, 'previous': None}))
    progress = {**compact_progress([start]), 'recent': [legacy], 'last_record': legacy, **progress_overrides}
    status, items = execution_activity(row(), progress, ArtifactReader(root), monitoring.datetime.fromisoformat(NOW_ISO))
    assert items[0]['source'] == ('activity_receipt' if compact else 'progress_receipt')
    if not compact:
        assert items[0]['receipt_ref'] == legacy and items[0]['activity_sequence'] is None, 'legacy entries unchanged'


def test_the_lane_view_projects_fixed_s1a_labels_and_the_recorded_drop_count(tmp_path):
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('tasks', 'task-1', {'id': 'task-1', 'agent': 'implementer', 'status': 'running', 'generation': 2,
                                   'attempt': 1, 'created_at': NOW_ISO})
        tx.put('execution_progress', 'task-1', {**compact_progress([]), 'last_event': 'claude/result/' + CANARY,
                                                'last_completed': {'type': CANARY, 'status': 'error_' + CANARY,
                                                                   'sequence': 3, 'occurred_at': None, 'evidence': None},
                                                'activity_dropped': 4})
        tx.put('tasks', 'task-2', {'id': 'task-2', 'agent': 'implementer', 'status': 'running', 'created_at': NOW_ISO})
    view = monitoring.lane_view(monitoring.ReadOnlyStore(store), ArtifactReader(tmp_path / 'artifacts'),
                                monitoring.datetime.fromisoformat(NOW_ISO))
    by_id = {execution['id']: execution for execution in view['executions']}
    progress = by_id['task-1']['progress']
    assert progress['last_event'] == 'claude/result'
    assert (progress['last_completed']['type'], progress['last_completed']['status']) == ('unknown', 'error')
    assert by_id['task-1']['activity_dropped'] == 4 and by_id['task-2']['activity_dropped'] is None
    assert CANARY not in json.dumps(view)


# ----- S2B-18 retention by the existing sweep --------------------------------------------------------------------------
def test_the_sweep_keeps_linked_compact_records_and_their_raw_and_collects_displaced_ones(tmp_path):
    store = MemoryStore()
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    raw = artifacts.put('{"event": "raw"}', 'runtime-event:task-1')['ref']
    linked = artifacts.put(canonical(receipt(event=claude('tool_completed', status='completed'), progress_sequence=1,
                                             raw_ref=raw)), 'runtime-activity:task-1')['ref']
    displaced = artifacts.put(canonical(receipt(activity_sequence=9)), 'runtime-activity:task-1')['ref']
    with store.transaction() as tx:
        tx.put('execution_progress', 'task-1', {'id': 'task-1', 'recent': [], 'activity_recent': [linked]})
    old = time.time() - 30 * 86400
    for ref in (raw, linked, displaced):
        os.utime(artifacts.root / (ref[7:] + '.txt'), (old, old))
    result = ArtifactMaintenance(store, artifacts).collect(apply=True)
    assert result['files'] == 1 and not (artifacts.root / (displaced[7:] + '.txt')).exists()
    assert (artifacts.root / (linked[7:] + '.txt')).exists() and (artifacts.root / (raw[7:] + '.txt')).exists()


def test_a_compact_ring_that_fails_entirely_never_falls_back_to_raw_and_raw_ref_is_never_read(tmp_path):
    root = tmp_path / 'artifacts'
    raw = store_text(root, json.dumps({'event': claude('tool_completed', status='completed'), 'malformed': False,
                                       'defect': None, 'previous': None}))
    linked = store_text(root, canonical(receipt(event=claude('tool_completed', status='completed'), progress_sequence=3,
                                                raw_ref=raw, activity_sequence=2)))
    reader = Spy(root)
    status, items = execution_activity(row(), {**compact_progress([linked]), 'recent': [raw], 'last_record': raw}, reader,
                                       monitoring.datetime.fromisoformat(NOW_ISO))
    assert reader.calls == [linked] and items[0]['raw_ref'] == raw, 'raw_ref is data, never followed'
    missing = 'sha256:' + 'c' * 64
    reader = Spy(root)
    status, items = execution_activity(row(), {**compact_progress([missing]), 'recent': [raw], 'last_record': raw}, reader,
                                       monitoring.datetime.fromisoformat(NOW_ISO))
    assert status == 'unavailable' and reader.calls == [missing], 'no fallback to the raw ring that would hide the failure'
    assert [(i['source'], i['state'], i['error_type']) for i in items] == [('activity_receipt', 'unavailable', 'missing_artifact')]
