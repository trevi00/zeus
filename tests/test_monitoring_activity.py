"""S2a activity pane (FLEET-S2-SPEC matrix S2-1..S2-9): the allowlisted projection of a lane execution's RETAINED
runtime-event receipts. Every receipt, progress row and lane below is a labelled synthetic FIXTURE written to a
temporary artifact root; no provider, model, process or database runs."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from codex_harness.adapters import monitoring
from codex_harness.adapters.monitoring import (
    ACTIVITY_BODY_BYTES,
    ArtifactReader,
    execution_activity,
    project_receipt,
)
from codex_harness.adapters.store import MemoryStore

CANARY = 'CANARY-activity-payload-must-never-reach-the-snapshot'
NOW = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)


def store_receipt(root, body) -> str:
    """Write one receipt exactly as FileArtifacts would name it (sha256 of the bytes) and return its ref."""
    data = (body if isinstance(body, str) else json.dumps(body)).encode('utf-8')
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(data).hexdigest()
    (root / (key + '.txt')).write_bytes(data)
    return 'sha256:' + key


def envelope(event, malformed=False, defect=None, previous=None):
    return {'event': event, 'malformed': malformed, 'defect': defect, 'previous': previous}


def claude(kind, status=None, tool=None, **extra):
    """A FIXTURE normalized Claude event; `raw` always carries the canary in payload positions."""
    return {'provider': 'claude-code-cli', 'stream': 'stdout', 'type': kind, 'raw_type': 'assistant',
            'subtype': CANARY, 'id': 'toolu_' + CANARY, 'status': status, 'sequence': 41, 'tool': tool,
            'text': CANARY, 'defect': CANARY,
            'raw': {'message': {'content': [{'type': 'tool_use', 'input': {'command': 'cat ' + CANARY},
                                             'thinking': CANARY}]}}, **extra}


def codex(method, item=None, **extra):
    return {'jsonrpc': '2.0', 'method': method, 'id': CANARY,
            'params': {'threadId': CANARY, 'turnId': CANARY, 'item': item, 'completedAtMs': 1790550000000,
                       'tokenUsage': {'secret': CANARY}}, **extra}


class Spy:
    """FIXTURE reader recording every requested ref; reads go to a real ArtifactReader."""

    def __init__(self, root):
        self.inner, self.calls = ArtifactReader(root), []

    def read(self, reference):
        self.calls.append(reference)
        return self.inner.read(reference)


def row(status='running', generation=2, attempt=1, completed_at=None):
    return {'id': 'task-1', 'status': status, 'generation': generation, 'attempt': attempt, 'completed_at': completed_at}


def progress(recent, last=None, generation=2, attempt=1, sequence=7, collected='2026-09-28T00:59:30+00:00', **extra):
    return {'id': 'task-1', 'recent': recent, 'last_record': last if last is not None else (recent[-1] if recent else None),
            'generation': generation, 'attempt': attempt, 'sequence': sequence, 'collected_at': collected, **extra}


# ----- S2-1 exclusion canaries and S2-2 transport derivation ------------------------------------------------------
@pytest.mark.parametrize('event,label,tool,item_type,status', [
    (claude('tool_started', 'started', tool='Read'), 'tool_started', 'Read', None, 'started'),
    (claude('tool_started', 'started', tool='mcp__private_server__tool'), 'tool_started', None, None, 'started'),
    (claude('tool_started', 'started', tool=CANARY), 'tool_started', None, None, 'started'),
    (claude('tool_completed', 'completed'), 'tool_completed', None, None, 'completed'),
    (claude('result', 'error_max_turns'), 'result', None, None, 'error'),
    (claude('result', CANARY), 'result', None, None, 'unknown'),
    (claude(CANARY, CANARY), 'unknown', None, None, 'unknown'),
    (codex('item/completed', {'id': CANARY, 'type': 'commandExecution', 'status': 'completed',
                              'command': 'rm -rf ' + CANARY, 'cwd': '/srv/' + CANARY,
                              'aggregatedOutput': CANARY}), 'item_completed', None, 'commandExecution', 'completed'),
    (codex('item/completed', {'id': 'x', 'type': 'mcpToolCall', 'server': CANARY, 'tool': CANARY,
                              'arguments': CANARY, 'status': CANARY}), 'item_completed', None, 'mcpToolCall', 'unknown'),
    (codex('item/completed', {'id': 'x', 'type': CANARY, 'text': CANARY}), 'item_completed', None, 'unknown', None),
    (codex(CANARY), 'unknown', None, None, None),
    (codex('thread/tokenUsage/updated'), 'token_usage_updated', None, None, None),
])
def test_only_fixed_vocabularies_and_builtin_tool_names_survive(event, label, tool, item_type, status):
    body = envelope(event, defect=CANARY)
    view = project_receipt(json.dumps(body))
    assert (view['event_label'], view['tool_name'], view['item_type'], view['status']) == (label, tool, item_type, status)
    assert view['state'] == 'ok' and view['malformed'] is False
    assert CANARY not in json.dumps(view), 'no payload, text, id, subtype, command, path or unknown name escapes'


def test_codex_occurrence_is_validated_epoch_millis_and_claude_has_none():
    assert project_receipt(json.dumps(envelope(codex('item/completed', {'id': 'x', 'type': 'fileChange'}))))[
        'occurred_at'] == datetime.fromtimestamp(1790550000, tz=timezone.utc).isoformat()
    bad = codex('item/completed', {'id': 'x', 'type': 'fileChange'})
    bad['params']['completedAtMs'] = True
    assert project_receipt(json.dumps(envelope(bad)))['occurred_at'] is None
    assert project_receipt(json.dumps(envelope(claude('tool_completed', 'completed'))))['occurred_at'] is None


# ----- S2-3 foreign references are never read ------------------------------------------------------------------------
def test_membership_is_only_the_bound_recent_list(tmp_path):
    root = tmp_path / 'artifacts'
    member = store_receipt(root, envelope(claude('tool_completed', 'completed'),
                                          previous=store_receipt(root, envelope(claude('result', 'success')))))
    foreign = store_receipt(root, envelope(claude('session_started', 'started')))
    reader = Spy(root)
    status, items = execution_activity(row(), progress([member], last=foreign), reader, NOW)
    assert reader.calls == [member], 'previous links, last_record outside recent and other files are never read'
    assert status == 'ok' and [item['receipt_ref'] for item in items] == [member]
    assert items[0]['sequence'] is None, 'last_record outside recent annotates nothing'


def test_two_lanes_never_share_an_artifact_root(tmp_path):
    lanes = [{'id': lane, 'schema': 'lane_' + lane, 'runtime': str(tmp_path / ('rt-' + lane))} for lane in ('a', 'b')]
    resolve = monitoring.lane_artifact_resolver()
    ref = store_receipt(tmp_path / 'rt-a' / 'artifacts', envelope(claude('tool_completed', 'completed')))
    assert resolve(lanes[0]).read(ref)[0] == 'ok'
    assert resolve(lanes[1]).read(ref)[:2] == ('unavailable', 'runtime_unavailable')
    assert not (tmp_path / 'rt-b' / 'artifacts').exists(), 'a missing lane root is never created'
    moved = {**lanes[0], 'runtime': str(tmp_path / 'rt-a2')}
    assert resolve(moved) is not resolve(lanes[0]), 'a changed registration never reuses the previous root'


# ----- S2-4 malformed and missing stay visible ----------------------------------------------------------------------
def test_malformed_and_missing_receipts_stay_explicit_beside_a_valid_one(tmp_path):
    root = tmp_path / 'artifacts'
    valid = store_receipt(root, envelope(claude('tool_completed', 'completed')))
    corrupt = store_receipt(root, '{"event": ')
    duplicate = store_receipt(root, '{"event": {}, "event": {}, "malformed": false}')
    flagged = store_receipt(root, envelope('<repr ' + CANARY + '>', malformed=True, defect=CANARY))
    shaped = store_receipt(root, {'event': {}, 'malformed': 'no', 'extra': CANARY})
    missing = 'sha256:' + 'f' * 64
    status, items = execution_activity(row(), progress([valid, corrupt, duplicate, flagged, shaped, missing]),
                                       ArtifactReader(root), NOW)
    states = [(item['state'], item['error_type'], item['event_label']) for item in items]
    assert states == [('ok', None, 'tool_completed'), ('unreadable', 'invalid_json', 'malformed'),
                      ('unreadable', 'invalid_json', 'malformed'), ('malformed', None, 'malformed'),
                      ('malformed', 'invalid_shape', 'malformed'), ('unavailable', 'missing_artifact', None)]
    assert status == 'ok' and CANARY not in json.dumps(items)
    assert [item['malformed'] for item in items] == [False, True, True, True, True, None]


def test_malformed_only_progress_says_so_and_never_reads_the_malformed_ring(tmp_path):
    reader = Spy(tmp_path / 'artifacts')
    status, items = execution_activity(row(), progress([], malformed_events=2,
                                                       malformed_recent=['sha256:' + 'a' * 64]), reader, NOW)
    assert (status, items, reader.calls) == ('malformed_not_in_recent', [], [])


# ----- S2-5 bounds and no writes -------------------------------------------------------------------------------------
def test_only_the_last_six_refs_are_read_and_the_body_budget_is_exact(tmp_path):
    root = tmp_path / 'artifacts'
    refs = [store_receipt(root, envelope(claude('tool_completed', 'completed', padding=str(index))))
            for index in range(7)]
    reader = Spy(root)
    execution_activity(row(), progress(refs), reader, NOW)
    assert reader.calls == refs[1:], 'executor retention: the last six, oldest to newest'
    base = json.dumps(envelope(claude('tool_completed', 'completed')))
    fits = base[:-1] + ', "pad": "' + 'x' * (ACTIVITY_BODY_BYTES - len(base) - 11) + '"}'
    assert len(fits.encode()) == ACTIVITY_BODY_BYTES
    assert ArtifactReader(root).read(store_receipt(root, fits))[0] == 'ok'
    over = fits[:-2] + 'x"}'
    assert ArtifactReader(root).read(store_receipt(root, over))[:2] == ('unreadable', 'too_large')


def test_integrity_encoding_numbers_depth_links_and_fifos_are_refused_without_writes(tmp_path, monkeypatch):
    root = tmp_path / 'artifacts'
    ref = store_receipt(root, envelope(claude('tool_completed', 'completed')))
    (root / (ref[7:] + '.txt')).write_bytes(b'{"tampered": true}')
    assert ArtifactReader(root).read(ref)[:2] == ('unreadable', 'integrity_failure')
    bad_utf8 = b'\xff\xfe'
    key = hashlib.sha256(bad_utf8).hexdigest()
    (root / (key + '.txt')).write_bytes(bad_utf8)
    assert ArtifactReader(root).read('sha256:' + key)[:2] == ('unreadable', 'invalid_json')
    assert project_receipt('{"event": {}, "malformed": false, "defect": NaN}')['error_type'] == 'invalid_json'
    assert project_receipt('[' * 100000 + ']' * 100000)['error_type'] in ('invalid_json', 'invalid_shape')
    target = store_receipt(tmp_path / 'outside', envelope(claude('tool_completed', 'completed', marker='outside')))
    (root / (target[7:] + '.txt')).symlink_to(tmp_path / 'outside' / (target[7:] + '.txt'))
    assert ArtifactReader(root).read(target)[:2] == ('unreadable', 'io_error')
    fifo_key = 'e' * 64
    os.mkfifo(root / (fifo_key + '.txt'))
    assert ArtifactReader(root).read('sha256:' + fifo_key)[:2] == ('unreadable', 'io_error'), 'never blocks on a FIFO'
    for name in ('mkdir', 'touch', 'write_text', 'write_bytes'):
        monkeypatch.setattr('pathlib.Path.' + name, lambda *a, **k: pytest.fail('the reader wrote: ' + name))
    reader = ArtifactReader(tmp_path / 'never-created')
    assert reader.read(ref)[:2] == ('unavailable', 'runtime_unavailable')


# ----- S2-6 ordering ----------------------------------------------------------------------------------------------------
def test_retention_order_is_kept_duplicates_read_once_and_only_last_record_has_sequence(tmp_path):
    root = tmp_path / 'artifacts'
    first = store_receipt(root, envelope(codex('item/completed', {'id': 'a', 'type': 'fileChange', 'completedAtMs': 1790550999000})))
    second = store_receipt(root, envelope(codex('item/completed', {'id': 'b', 'type': 'commandExecution'})))
    reader = Spy(root)
    status, items = execution_activity(row(), progress([first, second, first, second]), reader, NOW)
    assert reader.calls == [first, second] and [item['receipt_ref'] for item in items] == [first, second]
    assert [item['sequence'] for item in items] == [None, 7]
    assert [item['collected_at'] for item in items] == [None, '2026-09-28T00:59:30+00:00']
    assert items[0]['occurred_at'] is not None, 'an event time later than collection is kept as its own fact'


# ----- S2-7 selection ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('status,completed,selected', [
    ('running', None, True), ('queued', None, True),
    ('succeeded', (NOW - timedelta(seconds=600)).isoformat(), True),
    ('succeeded', (NOW - timedelta(seconds=601)).isoformat(), False),
    ('failed', (NOW + timedelta(seconds=5)).isoformat(), False),
    ('failed', None, False), ('succeeded', 'not a time', False),
])
def test_active_rows_and_recently_completed_rows_only(tmp_path, status, completed, selected):
    root = tmp_path / 'artifacts'
    ref = store_receipt(root, envelope(claude('result', 'success')))
    reader = Spy(root)
    result, _ = execution_activity(row(status, completed_at=completed), progress([ref]), reader, NOW)
    assert (result != 'not_selected') is selected and bool(reader.calls) is selected


# ----- S2-8 lineage -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('generation,attempt', [(1, 1), (2, 2), (None, 1), ('2', 1)])
def test_progress_of_another_generation_or_attempt_is_never_shown(tmp_path, generation, attempt):
    root = tmp_path / 'artifacts'
    reader = Spy(root)
    status, items = execution_activity(row(), progress([store_receipt(root, envelope(claude('result', 'success')))],
                                                       generation=generation, attempt=attempt), reader, NOW)
    assert (status, items, reader.calls) == ('lineage_unconfirmed', [], [])


# ----- S2-9 partial failure and compatibility ----------------------------------------------------------------------------
def test_one_unreadable_lane_root_leaves_the_other_lane_and_every_session_fact_intact(tmp_path):
    from codex_harness.application.fleet import Fleet
    control = MemoryStore()
    Fleet(control).register({'schema': 'urn:zeus:fleet:1', 'id': 'f', 'max_parallel': 2, 'budget': {'per_host': 4, 'total': 8},
                             'lanes': [{'id': lane, 'team': lane, 'repository': str(tmp_path / ('repo-' + lane)),
                                        'schema': 'lane_' + lane, 'redis_namespace': 'n-' + lane,
                                        'runtime': str(tmp_path / ('rt-' + lane))} for lane in ('a', 'b')]})
    stores = {}
    for lane in ('a', 'b'):
        store = MemoryStore()
        ref = store_receipt(tmp_path / ('rt-' + lane) / 'artifacts', envelope(claude('tool_completed', 'completed')))
        with store.transaction() as tx:
            tx.put('tasks', 'task-1', {'id': 'task-1', 'agent': 'implementer', 'status': 'running', 'generation': 2,
                                       'attempt': 1, 'created_at': '2026-09-28T00:00:00+00:00'})
            tx.put('execution_progress', 'task-1', progress([ref]))
        stores[lane] = store
    (tmp_path / 'rt-b' / 'artifacts').rename(tmp_path / 'rt-b' / 'gone')
    facts = monitoring.lane_session_facts(control, lambda lane: monitoring.ReadOnlyStore(stores[lane['id']]),
                                          monitoring.lane_artifact_resolver(), now=NOW)
    lane_a, lane_b = (lane['executions'][0] for lane in facts['lanes'])
    assert lane_a['activity_status'] == 'ok' and lane_a['activity'][0]['event_label'] == 'tool_completed'
    assert lane_b['activity_status'] == 'unavailable' and lane_b['activity'][0]['error_type'] == 'runtime_unavailable'
    assert lane_b['status'] == 'running' and lane_b['progress']['sequence'] == 7, 'session facts stay listed'
    assert not (tmp_path / 'rt-b' / 'artifacts').exists()
