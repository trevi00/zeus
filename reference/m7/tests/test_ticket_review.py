from copy import deepcopy
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pytest
import test_ticket_lifecycle
from test_tickets import content

from codex_harness import cli
from codex_harness.adapters import ticket_cli
from codex_harness.adapters.ticket_review import render_ticket_review
from codex_harness.domain.model import ContractError, canonical

github_setup = test_ticket_lifecycle.github_setup
lifecycle = test_ticket_lifecycle.lifecycle


def test_review_cli_is_read_only_and_preserves_canonical_signing_file(lifecycle, tmp_path, monkeypatch):
    life, ticket, _, _, prepare, _, _, _ = lifecycle
    prepared = prepare()
    packet = tmp_path / 'packet.json'
    packet.write_text(prepared['signing_payload'], encoding='utf-8', newline='\n')
    with life.store.transaction() as tx:
        before = tx.records()
    files = {p.name: p.read_bytes() for p in life.artifacts.root.iterdir()}
    monkeypatch.setattr(ticket_cli, 'build_lifecycle', lambda _: life)
    monkeypatch.setattr(life.authority, 'verify', lambda *a, **k: pytest.fail('Review attempted approval verification'))
    args = cli.parser().parse_args(['ticket', 'review-close', ticket['id'], '--packet', str(packet),
                                   '--output', str(tmp_path / 'review.html')])
    result = ticket_cli.execute(life.tickets, args)
    assert result['approval_granted'] is False and result['packet_ref'] == prepared['packet_ref']
    assert ticket_cli.execute(life.tickets, args) == result
    with life.store.transaction() as tx:
        assert tx.records() == before
    assert {p.name: p.read_bytes() for p in life.artifacts.root.iterdir()} == files
    assert packet.read_bytes() == prepared['signing_payload'].encode('utf-8')
    page = args.output.read_text('utf-8')
    assert 'Independent services' in page and prepared['packet_ref'] in page
    assert '사람 승인 요구 없음' in page and '서명 기한' in page
    args.output = life.artifacts.root / 'review.html'
    with pytest.raises(ContractError, match='outside artifact'):
        ticket_cli.execute(life.tickets, args)


def test_review_escapes_active_content_in_every_displayed_input(lifecycle):
    life, ticket, _, _, prepare, _, _, _ = lifecycle
    payload = '<script src="https://invalid.example/x"></script><img src=x onerror="alert(1)">'
    data = content(payload)
    data['acceptance_criteria'] = [payload]
    data['problem'] = payload
    life.tickets.update(ticket['id'], 1, data, 'Test hostile text')
    packet = prepare()['packet']
    page = render_ticket_review(life.review(packet), payload)
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags, self.attributes = [], []
        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)
            self.attributes.extend(attrs)
    parser = Tags()
    parser.feed(page)
    assert not set(parser.tags) & {'script', 'img', 'iframe', 'form', 'a', 'object', 'base'}
    assert not any(name.startswith('on') for name, _ in parser.attributes)
    assert '&lt;script' in page and "script-src 'none'" in page


def test_expired_packet_can_be_inspected_but_cannot_be_closed(lifecycle, monkeypatch):
    from codex_harness.application import ticket_lifecycle as application
    from codex_harness.domain import ticket_lifecycle as domain
    life, _, _, _, prepare, _, _, _ = lifecycle
    packet = prepare()
    future = datetime.fromisoformat(packet['packet']['expires_at']) + timedelta(hours=1)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return future
    monkeypatch.setattr(application, 'datetime', Clock)
    monkeypatch.setattr(domain, 'datetime', Clock)
    review = life.review(packet['packet'])
    assert review['time_status'] == 'expired'
    assert '서명 기한이 지났습니다' in render_ticket_review(review, 'packet.json')
    with pytest.raises(ContractError, match='expired'):
        life.close(packet['packet_ref'], [])


def test_review_rejects_stale_ticket_and_corrupted_evidence(lifecycle):
    life, ticket, _, _, prepare, _, _, _ = lifecycle
    packet = prepare()['packet']
    life.tickets.update(ticket['id'], 1, content('Changed requirement'), 'Changed before rendering')
    with pytest.raises(ContractError, match='Stale closure'):
        life.review(packet)
    fresh = prepare()['packet']
    path = life.artifacts.root / (fresh['environment_ref'][7:] + '.txt')
    path.write_text('tampered', encoding='utf-8')
    with pytest.raises(ContractError, match='Artifact modified'):
        life.review(fresh)


def test_large_evidence_preview_is_bounded_and_truncation_visible(lifecycle):
    life, _, _, _, prepare, _, _, _ = lifecycle
    packet = deepcopy(prepare()['packet'])
    env = life.artifacts.document(packet['environment_ref'])
    env['details'] = {'large': '<' * 300000}
    packet['environment_ref'] = life.artifacts.put(canonical(env), 'large-test-observation')['ref']
    page = render_ticket_review(life.review(packet), 'packet.json')
    assert '미리보기 일부만 표시됨' in page and packet['environment_ref'] in page
    assert len(page.encode('utf-8')) < 400000


def test_review_rejects_an_existing_unmerged_solution_commit(lifecycle):
    life, _, _, _, prepare, _, _, _ = lifecycle
    packet = deepcopy(prepare()['packet'])
    git = life.authority.git
    tree = git._git('rev-parse', 'HEAD^{tree}')
    orphan = git._git('-c', 'user.name=Zeus test', '-c', 'user.email=test@zeus.invalid',
                      'commit-tree', tree, '-m', 'Unmerged test object')
    packet['solution_commit'] = orphan
    for slot in [packet['criteria'][0]['evidence_refs'], [packet['environment_ref']]]:
        original = slot[0]
        document = life.artifacts.document(original)
        document['solution_commit'] = orphan
        ref = life.artifacts.put(canonical(document), 'unmerged-observation')['ref']
        if original == packet['environment_ref']:
            packet['environment_ref'] = ref
        else:
            slot[0] = ref
    with pytest.raises((ContractError, RuntimeError)):
        life.review(packet)


def test_environment_preview_survives_exhausted_criterion_budget(lifecycle):
    life, _, _, _, prepare, _, _, _ = lifecycle
    review = life.review(prepare()['packet'])
    criterion = review['packet']['criteria'][0]
    ref = criterion['evidence_refs'][0]
    review['documents'][ref]['details'] = {'large': 'x' * 100000}
    criterion['evidence_refs'] = [ref] * 5
    environment = review['packet']['environment_ref']
    review['documents'][environment]['details'] = {'environment_marker': 'ENVIRONMENT_STILL_VISIBLE'}
    page = render_ticket_review(review, 'packet.json')
    assert 'ENVIRONMENT_STILL_VISIBLE' in page and '미리보기 일부만 표시됨' in page
