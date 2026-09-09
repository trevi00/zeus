from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.monitoring import DatabaseFacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.monitoring import Monitoring
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope
from codex_harness.ports import MessageDeliveryError


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
