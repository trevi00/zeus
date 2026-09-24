from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.monitoring import DatabaseFacts
from codex_harness.adapters.store import MemoryStore, PostgresStore
from codex_harness.application.monitoring import Monitoring
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope
from codex_harness.ports import MessageDeliveryError, TransportChanged


@pytest.fixture(params=['memory', 'postgres'])
def service(request):
    store = MemoryStore() if request.param == 'memory' else request.getfixturevalue('isolated_pgstore')
    return Harness(store, organization())


class Bus:
    validate = staticmethod(validate_message)

    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.validate(message)
        self.messages.append(deepcopy(message))
        return f'{len(self.messages)}-0'


def put(service, n, message=None):
    message = message or envelope('task.assign', 'conductor', 'lead:improvement', 'plan',
                                   {'objective': 'Relay unit test'}, str(uuid4()))
    identity = f'00000000-0000-4000-8000-{n:012}'
    message['message_id'] = identity
    with service.store.transaction() as tx:
        tx.put('outbox', identity, {'message': message, 'sent': False})
    return identity


@pytest.mark.parametrize('bad', [[], None, False, 'bad', {'sent': 'false'}, {'sent': False, 'message': []}])
def test_poison_record_preserved_once_and_later_valid_message_delivered(service, bad):
    first, second = put(service, 1), put(service, 3)
    identity = '00000000-0000-4000-8000-000000000002'
    with service.store.transaction() as tx:
        tx.put('outbox', identity, bad)
    bus = Bus()
    result = service.flush_outbox(bus)
    assert result['published'] == 2 and result['quarantined'] == 1
    assert [m['message_id'] for m in bus.messages] == [first, second]
    assert service.flush_outbox(bus)['quarantined_existing'] == 1
    with service.store.transaction() as tx:
        assert tx.get('outbox', identity) == bad
        assert len(tx.scan('outbox_quarantine')) == 1
        assert len(tx.scan('events')) == 1
        assert tx.scan('outbox_quarantine')[0]['source'] == bad
        assert tx.get('outbox', first)['sent'] and tx.get('outbox', second)['sent']


def test_transport_ack_loss_retries_without_resending_prior_success(service):
    first, lost, last = [put(service, n) for n in (1, 2, 3)]
    class LoseAck(Bus):
        def publish(self, message):
            ref = super().publish(message)
            if message['message_id'] == lost and sum(m['message_id'] == lost for m in self.messages) == 1:
                raise MessageDeliveryError('Acknowledgement lost')
            return ref
    bus = LoseAck()
    assert service.flush_outbox(bus)['retry'] == 1
    assert service.flush_outbox(bus)['published'] == 1
    ids = [m['message_id'] for m in bus.messages]
    assert ids == [first, lost, last, lost]
    with service.store.transaction() as tx:
        attempts = [a for a in tx.scan('outbox_attempts') if a['outbox_id'] == lost]
        assert sorted(a['status'] for a in attempts) == ['delivered', 'retry']
        receipt = tx.get('outbox_delivery', lost)
        assert receipt['delivered_entry_id'] == '4-0' and receipt['attempts'] == 2


def test_unexpected_error_propagates_after_prior_success_and_error_receipt_commit(service):
    first, broken, last = [put(service, n) for n in (1, 2, 3)]
    class Broken(Bus):
        def publish(self, message):
            if message['message_id'] == broken:
                raise RuntimeError('Programmer error must surface')
            return super().publish(message)
    with pytest.raises(RuntimeError, match='Programmer error'):
        service.flush_outbox(Broken())
    with service.store.transaction() as tx:
        assert tx.get('outbox', first)['sent'] is True
        assert tx.get('outbox', last)['sent'] is False
        assert tx.get('outbox_delivery', broken)['status'] == 'error'
        assert any(a['status'] == 'error' for a in tx.scan('outbox_attempts'))


def test_first_attempt_binding_survives_post_publish_database_failure(service):
    identity = put(service, 1)
    original = service.store.transaction
    @contextmanager
    def fail_receipt_commit():
        with original() as tx:
            yield tx
            if any(a['status'] == 'delivered' for a in tx.scan('outbox_attempts')):
                raise OSError('Commit interrupted after transport success')
    service.store.transaction = fail_receipt_commit
    bus = Bus()
    with pytest.raises(OSError, match='Commit interrupted'):
        service.flush_outbox(bus)
    service.store.transaction = original
    with original() as tx:
        assert tx.get('outbox_delivery', identity)['status'] == 'publishing'
        item = tx.get('outbox', identity)
        item['message']['what']['details']['objective'] = 'Different content under attempted ID'
        tx.put('outbox', identity, item)
    assert service.flush_outbox(bus)['quarantined'] == 1
    assert len(bus.messages) == 1
    with original() as tx:
        assert tx.scan('outbox_quarantine')[0]['reason'] == 'AttemptedMessageIdentityReused'


def test_invalid_identity_and_routing_never_publish_and_can_be_corrected_before_attempt(service):
    identity = put(service, 1)
    with service.store.transaction() as tx:
        original = tx.get('outbox', identity)
        wrong = deepcopy(original)
        wrong['message']['message_id'] = str(uuid4())
        tx.put('outbox', identity, wrong)
    bus = Bus()
    assert service.flush_outbox(bus)['quarantined'] == 1
    with service.store.transaction() as tx:
        wrong = deepcopy(original)
        wrong['message']['who']['sender'] = 'worker:implementation'
        tx.put('outbox', identity, wrong)
    assert service.flush_outbox(bus)['quarantined'] == 1
    with service.store.transaction() as tx:
        tx.put('outbox', identity, original)
    assert service.flush_outbox(bus)['published'] == 1
    assert len(bus.messages) == 1


def test_concurrent_flush_uses_committed_receipts(service):
    identity = put(service, 1)
    bus = Bus()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.flush_outbox(bus), range(2)))
    assert sum(r['published'] for r in results) == 1
    assert [m['message_id'] for m in bus.messages] == [identity]


def test_bounded_cursor_reaches_later_records_and_retains_legacy_semantics(service):
    for n in range(1, 7):
        identity = put(service, n)
        if n != 6:
            with service.store.transaction() as tx:
                item = tx.get('outbox', identity)
                tx.put('outbox', identity, {**item, 'sent': True})
    bus = Bus()
    results = [service.flush_outbox(bus, limit=2) for _ in range(3)]
    assert all(r['examined'] == 2 for r in results)
    assert sum(r['legacy_sent'] for r in results) == 5
    assert results[-1]['published'] == 1
    assert len(bus.messages) == 1


def committed_started_attempts(store):
    """Independent observer of the COMMITTED intent at publish time. `_publish` calls the bus while
    its own transaction holds the writer lock, so PostgreSQL is read on a separate read-only
    connection that never takes `pg_advisory_xact_lock` and sees only committed rows, confined to
    the fixture's isolated schema; the memory store's lock is re-entrant and holds only commits."""
    if not isinstance(store, PostgresStore):
        with store.transaction() as tx:
            return [deepcopy(a) for a in tx.scan('outbox_attempts') if a['status'] == 'started']
    with psycopg.connect(store.dsn, connect_timeout=5) as conn:
        conn.read_only = True
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout = '5s'")
            [schema] = conn.execute('SELECT current_schema()').fetchone()
            assert schema.startswith('test_'), 'observer is confined to the isolated fixture schema'
            rows = conn.execute(sql.SQL("""SELECT body FROM {} WHERE bucket = 'outbox_attempts'
                AND body->>'status' = 'started' ORDER BY id LIMIT 100""").format(
                sql.Identifier(schema, 'documents'))).fetchall()
    return [row[0] for row in rows]


class BoundBus(Bus):
    """LABELLED binding-capable bus: a fixed credential-free identity; `seen` records what was
    committed for the attempt AT the publish call, and `refuse` raises the pre-write refusal."""

    def __init__(self, service, name='a', refuse=False, fail=None):
        super().__init__()
        self.service, self.identity = service, {'schema': 'urn:test:transport:1', 'storage': 'token-' + name}
        self.refuse, self.fail, self.seen, self.bound = refuse, fail, [], []

    def transport(self):
        if self.fail:
            raise MessageDeliveryError('TimeoutError')
        return dict(self.identity)

    def publish(self, message, transport=None):
        self.bound.append(transport)
        self.seen.append(committed_started_attempts(self.service.store))
        if self.refuse:
            raise TransportChanged('transport_changed')
        return super().publish(message)


def test_transport_binding_is_committed_before_publish_and_passed_to_the_publisher(service):
    identity = put(service, 1)
    bus = BoundBus(service)
    assert service.flush_outbox(bus)['published'] == 1
    [[started]] = bus.seen
    assert started['transport'] == bus.identity and bus.bound == [bus.identity], 'intent held the binding first'
    with service.store.transaction() as tx:
        assert tx.get('outbox_delivery', identity)['transport'] == bus.identity


def test_retry_keeps_the_first_binding_and_each_attempt_records_its_own_transport(service):
    identity = put(service, 1)
    class Lost(BoundBus):
        def publish(self, message, transport=None):
            super().publish(message, transport)
            raise MessageDeliveryError('Acknowledgement lost')   # LABELLED lost reply after the write
    first, second = Lost(service, 'a'), BoundBus(service, 'b')
    assert service.flush_outbox(first)['retry'] == 1
    assert service.flush_outbox(second)['published'] == 1
    with service.store.transaction() as tx:
        attempts = sorted(tx.scan('outbox_attempts'), key=lambda a: a['number'])
        assert [(a['status'], a['transport']['storage']) for a in attempts] == [('retry', 'token-a'), ('delivered', 'token-b')]
        assert tx.get('outbox_delivery', identity)['transport'] == first.identity, 'history is never rewritten'


def test_pre_write_refusal_and_unreadable_identity_hand_nothing_to_the_transport(service):
    identity = put(service, 1)
    refusing = BoundBus(service, refuse=True)
    assert service.flush_outbox(refusing)['retry'] == 1 and refusing.messages == []
    unreadable = BoundBus(service, fail=True)
    assert service.flush_outbox(unreadable)['retry'] == 1 and unreadable.bound == []
    with service.store.transaction() as tx:
        statuses = sorted(a['status'] for a in tx.scan('outbox_attempts'))
        assert statuses == ['transport_changed_before_publish', 'transport_unavailable']
        assert tx.get('outbox_delivery', identity)['status'] == 'retry'
        assert {e['error_type'] for e in tx.scan('events')} == {'TransportChanged', 'MessageDeliveryError'}
    assert service.flush_outbox(BoundBus(service))['published'] == 1


def test_a_bus_without_identity_keeps_the_legacy_unbound_records(service):
    identity = put(service, 1)
    assert service.flush_outbox(Bus())['published'] == 1
    with service.store.transaction() as tx:
        [attempt] = tx.scan('outbox_attempts')
        assert 'transport' not in attempt and 'transport' not in tx.get('outbox_delivery', identity)


def test_a_publish_override_that_cannot_recheck_stays_unbound_and_delivers(service):
    """A subclass that overrides `publish(message)` with the old signature cannot take the binding
    back, so no binding is claimed for it; its delivery is unchanged."""
    identity = put(service, 1)
    class OldSignature(BoundBus):
        def publish(self, message):
            return Bus.publish(self, message)
    bus = OldSignature(service)
    assert service.flush_outbox(bus)['published'] == 1 and len(bus.messages) == 1
    with service.store.transaction() as tx:
        assert 'transport' not in tx.scan('outbox_attempts')[0]
        assert 'transport' not in tx.get('outbox_delivery', identity)


def test_monitor_keeps_quarantine_attention_after_later_empty_successful_batches(service):
    with service.store.transaction() as tx:
        tx.put('outbox', 'invalid', [])
    service.flush_outbox(Bus())
    service.flush_outbox(Bus())
    facts = DatabaseFacts(service, SimpleNamespace()).read()
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    snapshot = Monitoring(SimpleNamespace(read=lambda: facts)).snapshot(later)
    assert snapshot['notifications']['status'] == 'attention'
    assert snapshot['notifications']['status_counts']['quarantined'] == 1
    assert 'source' not in str(snapshot['notifications'])


# ----- authoritative publication route (SPEC "Council isolation resubmission", 2026-09-24) -------------
class RunBus(Bus):
    """The route shape `RedisBus.for_run` configures (fixture bus; the adapter itself is covered in
    tests/test_bus.py and the production run wiring in tests/test_autonomous.py)."""

    def __init__(self, run_id):
        super().__init__()
        self.namespace = 'ns:run:' + run_id
        self.route = {'scope': 'run', 'run_id': run_id, 'namespace': self.namespace}


def pinned(service, n, run_id, correlation=None):
    from codex_harness.application.outbox import pin_route
    correlation = correlation or 'autonomous:' + run_id
    with service.store.transaction() as tx:
        pin_route(tx, correlation, RunBus(run_id).route, 'at')
    return put(service, n, envelope('task.assign', 'conductor', 'lead:improvement', 'plan',
                                    {'objective': 'Pinned relay test'}, correlation))


def untouched(service, identity):
    with service.store.transaction() as tx:
        assert tx.get('outbox', identity)['sent'] is False
        assert tx.get('outbox_delivery', identity) is None
        assert [a for a in tx.scan('outbox_attempts') if a['outbox_id'] == identity] == []
        assert tx.scan('outbox_quarantine') == []


def test_a_global_relay_holds_a_pinned_record_and_only_its_run_route_publishes_it_once(service):
    legacy, own, foreign = put(service, 1), pinned(service, 2, 'run-A'), pinned(service, 3, 'run-B')
    global_bus = Bus()
    first = service.flush_outbox(global_bus)
    assert first['published'] == 1 and first['route_held'] == 2
    assert [m['message_id'] for m in global_bus.messages] == [legacy], 'legacy global work still progresses'
    untouched(service, own)
    untouched(service, foreign)
    wrong = RunBus('run-B')
    refused = service.flush_outbox(wrong, correlation_id='autonomous:run-A')
    assert refused['route_refused'] == 1 and refused['complete'] is False and wrong.messages == []
    untouched(service, own)
    bus = RunBus('run-A')
    done = service.flush_outbox(bus, correlation_id='autonomous:run-A')
    assert done['published'] == 1 and done['complete'] is True
    assert [m['message_id'] for m in bus.messages] == [own]
    assert service.flush_outbox(bus, correlation_id='autonomous:run-A')['examined'] == 0
    assert service.flush_outbox(global_bus)['published'] == 0 and len(global_bus.messages) == 1
    untouched(service, foreign)


def test_a_malformed_pinned_record_is_never_quarantined_by_a_relay_that_does_not_own_it(service):
    identity = pinned(service, 1, 'run-A')
    with service.store.transaction() as tx:
        item = tx.get('outbox', identity)
        item['message']['who']['recipient'] = 'nobody'
        tx.put('outbox', identity, item)
    assert service.flush_outbox(Bus())['route_held'] == 1
    untouched(service, identity)
    assert service.flush_outbox(RunBus('run-A'), correlation_id='autonomous:run-A')['quarantined'] == 1, \
        'its owner keeps the strict existing validation'


@pytest.mark.parametrize('damage', ['malformed_pin', 'missing_pin_of_known_scoped_run'])
def test_unavailable_route_authority_never_falls_back_to_the_global_route(service, damage):
    if damage == 'malformed_pin':
        identity = pinned(service, 1, 'run-A')
    else:   # the run row records its scoped bus, but no pin is readable for its correlation
        identity = put(service, 1, envelope('task.assign', 'conductor', 'lead:improvement', 'plan',
                                            {'objective': 'unpinned'}, 'autonomous:run-A'))
    with service.store.transaction() as tx:
        if damage == 'malformed_pin':
            tx.put('outbox_routes', 'autonomous:run-A', {'id': 'autonomous:run-A', 'scope': 'run'})
        else:
            tx.put('autonomous_runs', 'run-A', {'id': 'run-A', 'correlation_id': 'autonomous:run-A',
                                                'bus': {'namespace': 'ns:run:run-A', 'scope': 'run'}})
    global_bus, bus = Bus(), RunBus('run-A')
    assert service.flush_outbox(global_bus)['route_unavailable'] == 1
    assert service.flush_outbox(bus, correlation_id='autonomous:run-A')['route_unavailable'] == 1
    assert global_bus.messages == bus.messages == []
    untouched(service, identity)


@pytest.mark.parametrize('recorded', [None, {'namespace': 'ns'}, {'namespace': 'ns:run:' + '0' * 32}])
def test_a_run_row_that_never_pinned_a_route_stays_on_the_legacy_route(service, recorded):
    """Historical rows (no bus, or a bare namespace recorded before routes were pinned) are never
    reinterpreted as scoped from their correlation or namespace text."""
    identity = put(service, 1, envelope('task.assign', 'conductor', 'lead:improvement', 'plan',
                                        {'objective': 'historical'}, 'autonomous:old-run'))
    with service.store.transaction() as tx:
        tx.put('autonomous_runs', 'old-run', {'id': 'old-run', 'correlation_id': 'autonomous:old-run', 'bus': recorded})
    bus = Bus()
    assert service.flush_outbox(bus)['published'] == 1 and [m['message_id'] for m in bus.messages] == [identity]


def test_the_route_is_rechecked_at_the_publication_transaction_boundary(service):
    from codex_harness.application.outbox import _prepare, _publish
    identity = pinned(service, 1, 'run-A')
    bus = RunBus('run-A')
    with service.store.transaction() as tx:
        result, prepared = _prepare(tx, identity, service.org, bus)
    assert result == 'prepared'
    with service.store.transaction() as tx:   # the pin changes between the intent and the publication
        pin = tx.get('outbox_routes', 'autonomous:run-A')
        tx.put('outbox_routes', 'autonomous:run-A', {**pin, 'namespace': 'ns:run:elsewhere'})
    with service.store.transaction() as tx:
        assert _publish(tx, prepared, bus) == ('route_refused', None)
    assert bus.messages == []
    with service.store.transaction() as tx:
        assert tx.get('outbox', identity)['sent'] is False
        assert tx.get('outbox_attempts', prepared['attempt_id'])['status'] == 'route_changed_before_publish'
        assert tx.get('outbox_delivery', identity)['status'] == 'retry'
        tx.put('outbox_routes', 'autonomous:run-A', pin)
    assert service.flush_outbox(bus, correlation_id='autonomous:run-A')['published'] == 1 and len(bus.messages) == 1


def test_a_pin_is_written_once_and_a_changed_route_never_replaces_it(service):
    from codex_harness.application.outbox import pin_route
    from codex_harness.domain.model import ContractError
    route = RunBus('run-A').route
    with service.store.transaction() as tx:
        pin_route(tx, 'autonomous:run-A', route, 'first')
    with service.store.transaction() as tx:
        pin_route(tx, 'autonomous:run-A', route, 'second')   # the same route is idempotent
    for bad in ({**route, 'namespace': 'ns:run:other'}, {**route, 'run_id': 'run-B'}):
        with pytest.raises(ContractError, match='route_conflict'):
            with service.store.transaction() as tx:
                pin_route(tx, 'autonomous:run-A', bad, 'third')
    for bad in (None, {}, {**route, 'scope': 'global'}, {**route, 'namespace': ''}):
        with pytest.raises(ContractError, match='route_invalid'):
            with service.store.transaction() as tx:
                pin_route(tx, 'autonomous:run-A', bad, 'third')
    with service.store.transaction() as tx:
        assert tx.get('outbox_routes', 'autonomous:run-A')['pinned_at'] == 'first'
        assert tx.get('outbox_routes', 'autonomous:run-A')['namespace'] == route['namespace']


def test_concurrent_global_and_scoped_relays_publish_each_pinned_record_once_on_its_route(service):
    own = [pinned(service, n, 'run-A') for n in (1, 2, 3)]
    legacy = put(service, 4)
    global_bus, bus = Bus(), RunBus('run-A')
    jobs = [lambda: service.flush_outbox(global_bus), lambda: service.flush_outbox(bus, correlation_id='autonomous:run-A')] * 2
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda job: job(), jobs))
    assert [m['message_id'] for m in global_bus.messages] == [legacy]
    assert sorted(m['message_id'] for m in bus.messages) == own
