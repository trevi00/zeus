"""S2b producer (FLEET-S2B-SPEC §3, matrix S2B-1/2/4/6..13/19): compact activity receipts beside byte-identical raw
progress receipts, retained Claude tool starts, contained display-only failures and the `_owned` fence.

Every provider line is a labelled synthetic FIXTURE normalized by the REAL Claude normalizer; the Claude runtime is a
fixture that only replays those events, and the Codex app server is stubbed to FAIL if reached, so no provider,
model or network ever runs."""
import json
import time
from types import SimpleNamespace

import pytest
from filelock import Timeout
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.claude_cli import _normalize
from codex_harness.adapters.executor import IMPLEMENTATION, Executor
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.project_skills import initialize
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.progress_activity import validate_receipt

CANARY = 'CANARY-s2b-producer-payload'


def lines(*bodies):
    """FIXTURE provider lines through the real normalizer, in order."""
    events = []
    for index, body in enumerate(bodies):
        events += _normalize({'stream': 'stdout', 'line': json.dumps(body).encode()}, index)
    return events


INIT = {'type': 'system', 'subtype': 'init', 'session_id': 'fixture-session', 'cwd': '/srv/' + CANARY}


def use(*names):
    return {'type': 'assistant', 'message': {'id': 'm-' + '-'.join(names), 'content': [
        {'type': 'tool_use', 'id': 'toolu_' + name + str(index), 'name': name, 'input': {'command': 'cat ' + CANARY}}
        for index, name in enumerate(names)]}}


def done(*ids, error=False):
    return {'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': identifier, 'content': CANARY, 'is_error': error} for identifier in ids]}}


def result(subtype='success', is_error=False):
    return {'type': 'result', 'subtype': subtype, 'is_error': is_error, 'session_id': 'fixture-session', 'result': CANARY}


class CountingStore(MemoryStore):
    """FIXTURE store counting transactions (and fail-fast ones) and tracking whether one is open."""

    def __init__(self):
        super().__init__()
        self.transactions, self.fail_fast, self.open, self.before, self.after = 0, 0, False, None, None

    def transaction(self, fail_fast=False):
        store = self

        class Scope:
            def __enter__(self):
                if store.before is not None:
                    store.before(fail_fast)
                store.transactions += 1
                store.fail_fast += int(fail_fast)
                store.open = True
                self.inner = MemoryStore.transaction(store, fail_fast)
                return self.inner.__enter__()

            def __exit__(self, *args):
                store.open = False
                if args[0] is None and store.after is not None and store.after(fail_fast):
                    self.inner.__exit__(RuntimeError, RuntimeError('commit failed'), None)
                    raise RuntimeError('injected commit failure')
                return self.inner.__exit__(*args)
        return Scope()


class CountingArtifacts(FileArtifacts):
    """FIXTURE artifacts counting puts per source kind. `fail[kind]` is how many more puts of that kind time out
    (a large number means always); `after[kind]` runs once after a put of that kind succeeds."""

    def __init__(self, root, store):
        super().__init__(root)
        self.store, self.puts, self.fail, self.after, self.inside = store, [], {}, {}, 0

    def put(self, body, source, lock_timeout=30):
        kind = source.split(':')[0]
        self.puts.append((kind, lock_timeout))
        self.inside += int(self.store.open)
        if self.fail.get(kind, 0) > 0:
            self.fail[kind] -= 1
            raise Timeout('artifacts.lock')
        receipt = super().put(body, source, lock_timeout=lock_timeout)
        hook = self.after.pop(kind, None)
        if hook is not None:
            hook()
        return receipt


def runtime(events):
    class Runtime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, prompt, *args, **kwargs):
            for event in events:
                if callable(event):  # a FIXTURE step between two provider lines
                    event()
                else:
                    kwargs['on_event'](event)
            return {'answer': {'summary': 'fixture', 'tests': []}, 'thread_id': 'fixture', 'usage': {},
                    'rotate': False, 'interrupted': False, 'events': []}
    return Runtime


class Unreachable:
    def __init__(self, **kwargs):
        raise AssertionError('this transport must never run in this module')


@pytest.fixture
def workspace(tmp_path):
    """A FIXTURE project repository, exactly as tests/test_execution_progress.py builds it."""
    root = tmp_path / 'project'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@example.invalid')
    initialize(root, 'stack: {language: python}')
    git._git('add', '.')
    git._git('commit', '-qm', 'project definition')
    return root, git, FileArtifacts(str(tmp_path / 'artifacts'))


@pytest.fixture
def claude(workspace, monkeypatch, tmp_path):
    root, git, _ = workspace
    for name, value in (('ZEUS_CLAUDE_ASSIGNMENTS', 'worker:implementation/implement'),
                        ('ZEUS_CLAUDE_MODEL', 'claude-fixture-model'), ('ZEUS_CLAUDE_MAX_BUDGET_USD', '1')):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Unreachable)
    store = CountingStore()
    artifacts = CountingArtifacts(str(tmp_path / 'counted-artifacts'), store)
    spool = MemorySpool(new_process_run_id())
    observer = Observer(store, spool, component='test-s2b', directory=MemoryDirectory())
    executor = Executor(Harness(store, organization()), git, artifacts, observer=observer)
    executor.workflow.submit(assignment())
    lease = executor.workflow.claim('worker:implementation', 'owner')

    def run(events, owner=None):
        monkeypatch.setattr('codex_harness.adapters.executor.ClaudeCodeRuntime', runtime(events))
        chosen = owner or lease
        return executor._run('worker:implementation', chosen['id'], 'fixture', {}, str(root), IMPLEMENTATION,
                             lease=chosen, action='implement', workload='implementation')

    def row():
        with MemoryStore.transaction(store) as tx:
            return tx.get('execution_progress', lease['id'])

    def progress_notes():
        return [record for record in spool.records() if 'progress_recorded' in json.dumps(record)]

    return SimpleNamespace(run=run, row=row, store=store, artifacts=artifacts, lease=lease, executor=executor,
                           monkeypatch=monkeypatch, root=root, progress_notes=progress_notes)


def compact(s, row=None):
    return [s.artifacts.document(ref) for ref in (row or s.row())['activity_recent']]


# ----- S2B-1 / S2B-2 / S2B-3 ------------------------------------------------------------------------------------------
def test_a_normal_claude_run_keeps_starts_as_compact_records_beside_unchanged_raw_receipts(claude):
    claude.run(lines(INIT, use('Read'), done('toolu_Read0'), result()))
    row = claude.row()
    assert row['provider'] == 'claude'
    assert (row['activity_sequence'], row['sequence'], row['activity_progress_sequence']) == (4, 3, 3)
    records = compact(claude, row)
    assert [(r['event_label'], r['tool_name'], r['status']) for r in records] == [
        ('session_started', None, 'started'), ('tool_started', 'Read', 'started'),
        ('tool_completed', None, 'completed'), ('result', None, 'success')]
    start = records[1]
    assert (start['progress_sequence'], start['raw_ref']) == (None, None), 'a start has no raw receipt'
    assert [r['raw_ref'] for r in records if r['raw_ref']] == row['recent'], 'raw-backed records point at their raw'
    assert [r['activity_sequence'] for r in records] == [1, 2, 3, 4]
    assert [r['progress_sequence'] for r in records] == [1, None, 2, 3]
    assert all(validate_receipt(r) == r for r in records)
    # S2B-2: the raw envelope is exactly the old one (the whole normalized event, with raw) and nothing else.
    for ref in row['recent']:
        document = claude.artifacts.document(ref)
        assert set(document) == {'event', 'malformed', 'defect', 'previous'} and document['event']['raw'] is not None
    # S2B-3: no payload, path, command, id or subtype reaches a compact record or the activity fields.
    blob = json.dumps(records) + json.dumps({k: row[k] for k in row if k.startswith('activity')})
    assert CANARY not in blob and 'toolu_' not in blob and 'fixture-session' not in blob and '/srv/' not in blob


@pytest.mark.parametrize('name,kept', [('Read', 'Read'), ('mcp__private__tool', None), ('CustomThing', None),
                                       ('read', None), ('Read ', None)])
def test_only_an_exact_builtin_tool_name_survives_on_a_start(claude, name, kept):
    claude.run(lines(use(name)))
    assert [r['tool_name'] for r in compact(claude)] == [kept]


# ----- S2B-4 D9 --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('subtype,is_error,expected', [('success', False, 'success'), ('success', True, 'error'),
                                                       ('success', [1], 'error'), ('success', 'yes', 'error'),
                                                       ('error_max_turns', False, 'error')])
def test_the_result_status_uses_is_error_and_s1a_agrees_even_when_the_compact_put_fails(claude, subtype, is_error, expected):
    claude.run(lines(result(subtype, is_error)))
    row = claude.row()
    assert compact(claude, row)[-1]['status'] == expected and row['last_completed']['status'] == expected
    claude.artifacts.fail['runtime-activity'] = 1
    claude.run(lines(result(subtype, is_error)))
    assert claude.row()['last_completed']['status'] == expected, 'S1a gets D9 even when the activity is dropped'


def test_a_result_whose_raw_is_not_an_object_is_unknown(claude):
    event = lines(result())[0]
    claude.run([{**event, 'raw': ['not', 'an', 'object']}])
    assert compact(claude)[-1]['status'] == 'unknown' and claude.row()['last_completed']['status'] == 'unknown'


# ----- S2B-6 hot-path counts ------------------------------------------------------------------------------------------
@pytest.mark.parametrize('body,transactions,kinds', [
    (use('Read'), 1, [('runtime-activity', 0.5)]),
    (INIT, 2, [('runtime-event', 30), ('runtime-activity', 0.5)]),
    (done('x'), 2, [('runtime-event', 30), ('runtime-activity', 0.5)]),
    (result(), 2, [('runtime-event', 30), ('runtime-activity', 0.5)]),
    ({'type': 'assistant', 'message': {'id': 'm', 'content': [{'type': 'text', 'text': CANARY}]}}, 0, []),
])
def test_each_event_kind_costs_exactly_its_transactions_and_puts_and_never_puts_inside_one(claude, body, transactions, kinds):
    claude.run([])
    before_tx, before_puts = claude.store.transactions, len(claude.artifacts.puts)
    claude.run(lines(body))
    run_tx = claude.store.transactions - before_tx
    progress_puts = [put for put in claude.artifacts.puts[before_puts:] if put[0] in ('runtime-event', 'runtime-activity')]
    empty_tx = claude.store.transactions - before_tx
    claude.store.transactions = before_tx
    claude.run([])
    baseline = claude.store.transactions - before_tx
    assert run_tx - baseline == transactions and empty_tx == run_tx
    assert progress_puts == kinds and claude.artifacts.inside == 0


def test_six_parallel_starts_take_one_fail_fast_transaction_each(claude):
    claude.run(lines(INIT))
    fast = claude.store.fail_fast
    claude.run(lines(use('Read', 'Grep', 'Glob', 'Bash', 'Edit', 'Write')))
    assert claude.store.fail_fast - fast == 6
    assert [r['tool_name'] for r in compact(claude)] == ['Read', 'Grep', 'Glob', 'Bash', 'Edit', 'Write']


# ----- S2B-7 / S2B-19 containment -------------------------------------------------------------------------------------
def test_a_start_whose_activity_put_times_out_is_dropped_and_counted_at_the_next_progress_write(claude):
    claude.artifacts.fail['runtime-activity'] = 1
    claude.run(lines(use('Read'), INIT))
    row = claude.row()
    assert row['activity_dropped'] == 1, 'the run continued and the next owned write persisted the drop'
    assert [r['event_label'] for r in compact(claude, row)] == ['session_started']


def test_a_fail_fast_transaction_failure_on_a_start_is_contained_and_no_stale_guess_is_retried(claude):
    refused = []

    def refuse(fail_fast):
        if fail_fast and not refused:
            refused.append(True)
            raise TimeoutError('lock timeout')
    claude.store.before = refuse
    claude.run(lines(INIT, use('Read'), use('Grep'), done('toolu_Read0')))
    claude.store.before = None
    row = claude.row()
    # The failed start invalidated the prediction; the second start skipped instead of guessing; the completion
    # (an authoritative write) persisted both drops and CLEARED the ring, which misses the two dropped starts.
    assert row['activity_dropped'] == 2 and len(refused) == 1
    assert [r['event_label'] for r in compact(claude, row)] == ['tool_completed']


def test_a_compare_and_set_mismatch_drops_only_the_activity_and_the_raw_update_still_commits(claude):
    def move_counters():  # between the raw path's read and its write, another writer moved the counters
        with MemoryStore.transaction(claude.store) as tx:
            row = tx.get('execution_progress', claude.lease['id'])
            tx.put('execution_progress', claude.lease['id'], {**row, 'activity_sequence': row['activity_sequence'] + 5})
    claude.run(lines(INIT))
    claude.artifacts.after['runtime-activity'] = move_counters
    claude.run(lines(done('x')))
    row = claude.row()
    assert row['sequence'] == 2 and len(row['recent']) == 2, 'the ordinary raw update committed'
    assert row['activity_progress_sequence'] is None and row['activity_dropped'] == 1
    assert [r['event_label'] for r in compact(claude, row)] == ['session_started'], 'nothing linked'
    claude.run(lines(result()))
    row = claude.row()
    assert row['activity_progress_sequence'] == row['sequence'] == 3
    assert [r['event_label'] for r in compact(claude, row)] == ['result'], 'the stale ring was cleared, not continued'


def test_a_sustained_activity_lock_outage_never_ends_the_run(claude):
    claude.artifacts.fail['runtime-activity'] = 10 ** 6
    claude.run(lines(INIT, *[use('Read') for _ in range(8)], done('x'), result()))
    row = claude.row()
    assert row['sequence'] == 3 and row['activity_dropped'] == 11 and row['activity_progress_sequence'] is None


def test_a_dropped_start_never_leaves_a_ring_that_looks_continuous(claude):
    """A start whose own write failed cannot null the watermark; the next successful write must clear the ring instead
    of appending to it as if nothing were missing (review finding, FLEET-S2B-SPEC §3.4)."""
    calls = []

    def refuse_second(fail_fast):
        if fail_fast:
            calls.append(True)
            if len(calls) == 2:
                raise TimeoutError('lock timeout')
    claude.store.before = refuse_second
    claude.run(lines(INIT, use('Read'), use('Grep'), done('toolu_Read0'), use('Glob')))
    claude.store.before = None
    row = claude.row()
    # Read linked; Grep's own write failed (a gap); the completion cleared the ring (it misses Grep) and persisted
    # the drop; Glob linked on the refreshed basis.
    assert [(r['event_label'], r['tool_name']) for r in compact(claude, row)] == [('tool_completed', None),
                                                                                ('tool_started', 'Glob')]
    assert row['activity_dropped'] == 1 and row['activity_progress_sequence'] == row['sequence']


def test_a_start_compare_and_set_mismatch_refreshes_the_prediction_and_writes_nothing(claude):
    claude.run(lines(INIT))
    before = claude.row()

    def move(fail_fast):
        if fail_fast:
            with MemoryStore.transaction(claude.store) as tx:
                row = tx.get('execution_progress', claude.lease['id'])
                tx.put('execution_progress', claude.lease['id'], {**row, 'activity_sequence': row['activity_sequence'] + 3})
            claude.store.before = None
    claude.store.before = move
    claude.run(lines(use('Read'), use('Grep'), done('x')))
    row = claude.row()
    assert row['activity_sequence'] == before['activity_sequence'] + 3 + 2, 'Read dropped; Grep and done linked on the refreshed basis'
    assert row['activity_dropped'] == 1
    assert [r['tool_name'] for r in compact(claude, row)] == ['Grep', None], 'the ring restarted after the gap'


def test_a_failed_flush_commit_keeps_the_pending_count(claude):
    claude.artifacts.fail['runtime-activity'] = 1
    failures = []

    def fail_first_fast_commit(fail_fast):
        if fail_fast and not failures:
            failures.append(True)
            return True
        return False
    claude.store.after = fail_first_fast_commit
    claude.run(lines(use('Read'), use('Grep'), INIT))
    claude.store.after = None
    row = claude.row()
    # Read: put dropped (1). Grep: its commit (carrying that flush) failed, so both stay pending (2). INIT persists 2.
    assert row['activity_dropped'] == 2 and len(failures) == 1


def test_a_start_only_write_leaves_every_legacy_field_and_emits_no_progress_observation(claude):
    claude.run(lines(INIT))
    before, notes = claude.row(), len(claude.progress_notes())
    claude.run(lines(use('Read', 'Grep')))
    after = claude.row()
    legacy = ('sequence', 'recent', 'last_record', 'at', 'collected_at', 'occurred_at', 'event_id', 'last_event',
              'last_completed', 'generation', 'attempt', 'agent', 'context_ref')
    assert {k: after.get(k) for k in legacy} == {k: before.get(k) for k in legacy}
    assert len(claude.progress_notes()) == notes, 'no progress_recorded observation for a start'
    assert after['activity_sequence'] == before['activity_sequence'] + 2


def test_a_provider_change_resets_the_activity_binding(claude):
    claude.run(lines(INIT, use('Read')))
    assert claude.row()['activity_sequence'] == 2
    claude.monkeypatch.delenv('ZEUS_CLAUDE_ASSIGNMENTS')
    claude.executor._execution_policy = None  # the policy is read once per executor
    item = {'method': 'item/completed', 'params': {'item': {'id': 'a', 'type': 'fileChange', 'status': 'completed'}}}
    claude.monkeypatch.setattr('codex_harness.adapters.executor.AppServer', runtime([item]))
    claude.run([])
    row = claude.row()
    assert row['provider'] != 'claude' and row['activity_sequence'] == 1 and row['activity_dropped'] == 0
    assert [r['event_label'] for r in compact(claude, row)] == ['item_completed']


def test_the_raw_envelope_keeps_the_exact_normalized_event_and_its_lineage_is_the_lease(claude):
    events = lines(INIT, done('x'), result('success', True))
    snapshot = json.loads(json.dumps(events))
    claude.run(events)
    row = claude.row()
    assert [claude.artifacts.document(ref)['event'] for ref in row['recent']] == snapshot, 'D9 never rewrites the event'
    records = compact(claude, row)
    assert all((r['generation'], r['attempt']) == (claude.lease['generation'], claude.lease['attempt']) for r in records)


def test_a_raw_receipt_failure_still_ends_the_run_as_before(claude):
    claude.artifacts.fail['runtime-event'] = 1
    with pytest.raises(Exception) as failed:
        claude.run(lines(INIT))
    assert 'artifacts.lock' in str(failed.value) or 'artifacts.lock' in str(failed.value.__cause__ or failed.value.__context__)


def test_the_real_adapters_use_their_short_activity_budgets(tmp_path, monkeypatch):
    from filelock import FileLock

    from codex_harness.adapters import store as store_module
    artifacts = FileArtifacts(str(tmp_path / 'held'))
    with FileLock(str(artifacts.root.parent / 'artifacts.lock')):
        started = time.monotonic()
        with pytest.raises(Timeout):
            artifacts.put('x', 'runtime-activity:t', lock_timeout=0.5)
        assert time.monotonic() - started < 2
    executed = []

    class Connection:
        def __init__(self, dsn, connect_timeout):
            executed.append(('connect_timeout', connect_timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, *args):
            executed.append(sql)
    monkeypatch.setattr(store_module.psycopg, 'connect', Connection)
    with store_module.PostgresStore('postgresql://fixture').transaction(fail_fast=True):
        pass
    with store_module.PostgresStore('postgresql://fixture').transaction():
        pass
    assert executed[:2] == [('connect_timeout', 2), "SET LOCAL lock_timeout = '500ms'"]
    assert executed[3:5] == [('connect_timeout', 5), "SET LOCAL lock_timeout = '10s'"]


# ----- S2B-8 the fence is never swallowed ----------------------------------------------------------------------------
def test_a_stale_owner_start_ends_the_run_and_writes_nothing(claude):
    claude.run(lines(INIT))
    before = claude.row()
    stale = dict(claude.lease, generation=claude.lease['generation'] - 1 if claude.lease['generation'] > 0 else 99)
    with pytest.raises(ContractError):
        claude.run(lines(use('Read')), owner=stale)
    assert claude.row() == before


def test_an_expired_lease_is_refused_on_the_start_path_exactly_like_progress(workspace, monkeypatch):
    root, git, artifacts = workspace
    for name, value in (('ZEUS_CLAUDE_ASSIGNMENTS', 'worker:implementation/implement'),
                        ('ZEUS_CLAUDE_MODEL', 'claude-fixture-model'), ('ZEUS_CLAUDE_MAX_BUDGET_USD', '1')):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Unreachable)
    monkeypatch.setattr('codex_harness.adapters.executor.ClaudeCodeRuntime', runtime(lines(use('Read'))))
    store = MemoryStore()
    executor = Executor(Harness(store, organization()), git, artifacts)
    executor.workflow.submit(assignment())
    stale = executor.workflow.claim('worker:implementation', 'first-owner', lease_seconds=1)
    time.sleep(1.2)
    current = executor.workflow.claim('worker:implementation', 'second-owner', lease_seconds=60)
    assert current['generation'] == 2
    with pytest.raises(ContractError, match='Stale or expired'):
        executor._run('worker:implementation', stale['id'], 'fixture', {}, str(root), IMPLEMENTATION, lease=stale,
                      action='implement', workload='implementation')
    with store.transaction() as tx:
        assert tx.get('execution_progress', stale['id']) is None, 'a refused start writes nothing'



@pytest.mark.parametrize('body', [use('Read'), done('x')], ids=['start', 'raw-backed'])
def test_a_superseded_execution_mid_stream_ends_the_run_the_same_way_on_both_paths(claude, body):
    """The fence is checked inside the start's own write, not only before the run: a start after the task stopped
    running is refused with the same failure as a raw-backed progress write, and writes nothing."""
    snapshot = {}

    def supersede():
        with MemoryStore.transaction(claude.store) as tx:
            task = tx.get('tasks', claude.lease['id'])
            tx.put('tasks', task['id'], {**task, 'status': 'failed'})
            snapshot['row'] = tx.get('execution_progress', claude.lease['id'])
    reached = []
    with pytest.raises(Exception) as refused:
        claude.run([*lines(INIT), supersede, *lines(body), lambda: reached.append(True)])
    assert reached == [], 'the refusal ended the stream at that event; a swallowed refusal would continue it'
    assert 'Stale or expired task execution' in str(refused.value) or any(
        'Stale or expired task execution' in str(link) for link in (refused.value.__cause__, refused.value.__context__))
    assert claude.row() == snapshot['row'], 'the refused write changed nothing'


# ----- S2B-10 / S2B-12 / S2B-13 ----------------------------------------------------------------------------------------
def test_an_older_producer_in_between_clears_the_ring_and_keeps_the_counter_monotonic(claude):
    claude.run(lines(INIT, use('Read')))
    with MemoryStore.transaction(claude.store) as tx:  # an older producer advanced raw progress only
        row = tx.get('execution_progress', claude.lease['id'])
        tx.put('execution_progress', claude.lease['id'], {**row, 'sequence': row['sequence'] + 1})
    claude.run(lines(done('x')))
    row = claude.row()
    assert [r['event_label'] for r in compact(claude, row)] == ['tool_completed']
    assert row['activity_sequence'] == 3 and row['activity_progress_sequence'] == row['sequence'] == 3


def test_eight_identical_starts_under_a_frozen_clock_are_distinct_and_only_six_are_kept(claude):
    claude.monkeypatch.setattr('codex_harness.adapters.executor.utcnow', lambda: '2026-09-28T01:00:00+00:00')
    claude.run(lines(INIT, done('x', error=True)))
    claude.run(lines(*[use('Read') for _ in range(8)]))
    row = claude.row()
    records = compact(claude, row)
    assert len(row['activity_recent']) == len(set(row['activity_recent'])) == 6
    assert [r['activity_sequence'] for r in records] == [5, 6, 7, 8, 9, 10]
    assert all(r['event_label'] == 'tool_started' for r in records), 'the failed completion was displaced'
    assert len(row['recent']) == 2, 'the raw ring is unchanged'


def test_codex_token_updates_and_malformed_events_never_take_a_compact_slot(workspace, monkeypatch, tmp_path):
    root, git, _ = workspace
    monkeypatch.setattr('codex_harness.adapters.executor.ClaudeCodeRuntime', Unreachable)
    store = MemoryStore()
    artifacts = FileArtifacts(str(tmp_path / 'codex-artifacts'))
    executor = Executor(Harness(store, organization()), git, artifacts)
    executor.workflow.submit(assignment())
    lease = executor.workflow.claim('worker:implementation', 'owner')
    events = [{'method': 'item/completed', 'params': {'item': {'id': 'a', 'type': 'commandExecution', 'status': 'completed',
                                                               'command': 'cat ' + CANARY}, 'completedAtMs': 1790550000000}},
              {'method': 'thread/tokenUsage/updated', 'params': {'tokenUsage': {'last': {'totalTokens': 3}}}},
              'not-an-object',
              {'method': 'item/completed', 'params': {'item': {'id': 'b', 'type': CANARY}}}]
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', runtime(events))
    executor._run('worker:implementation', lease['id'], 'fixture', {}, str(root), IMPLEMENTATION, lease=lease)
    with store.transaction() as tx:
        row = tx.get('execution_progress', lease['id'])
    assert row['provider'] != 'claude-code-cli' and row['sequence'] == 3 and row['malformed_events'] == 1
    records = [artifacts.document(ref) for ref in row['activity_recent']]
    assert [(r['event_label'], r['item_type'], r['status']) for r in records] == [
        ('item_completed', 'commandExecution', 'completed'), ('item_completed', 'unknown', None)]
    assert records[0]['occurred_at'] == '2026-09-27T23:00:00+00:00' and CANARY not in json.dumps(records)
    assert row['activity_progress_sequence'] == row['sequence'] == 3
