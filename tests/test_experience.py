"""INV-EXPERIENCE-001: upstream lesson labels are preserved data, never Zeus occurrence counts."""
import copy
import json
from uuid import uuid4

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.experience import import_lessons, main, parse_lesson, preview_lessons
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.experience import ExperienceClaims
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.experience import classify_evidence, experience_claim, split_frontmatter
from codex_harness.domain.model import ContractError, envelope

PINNED = {'kind': 'pinned', 'revision': 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'}
OBSERVED = {'kind': 'observed', 'revision': None}
PATH = 'knowledge/lessons/repair-cp949-629cb3e3.md'


def lesson(occurrences=308, evidence=None, trust='confirmed', extra='', body='# 수리 경험: cp949 — 자식 인코딩\n'):
    evidence = evidence if evidence is not None else [f'ledger:PASS x{n}' for n in (1, 2, *range(25, 46))] + [
        'repair-notes:harness']
    lines = ['---', 'created_by: agent:curator', 'created_ts: 1788396067.7754688', 'evidence:',
             *['- ' + token for token in evidence], 'id: lesson:' + PATH, 'kind: lesson', 'lifecycle: active',
             f'occurrences: {occurrences}', 'origin: promoted', 'pinned: false', 'source_families:',
             '- repair::스위트 러너가 인코딩 계약을 안 실어 준다', *([extra] if extra else []),
             f'trust: {trust}', '---', '', body]
    return '\n'.join(lines).encode('utf-8')


def test_upstream_counters_are_preserved_but_count_zero_independent_incidents():
    claim = parse_lesson('harness', PATH, lesson(), OBSERVED)
    upstream = claim['upstream']
    # Strings only: the loader applies no implicit typing, so '308' and 'false' stay as written.
    assert upstream['occurrences'] == '308' and upstream['trust'] == 'confirmed' and upstream['pinned'] == 'false'
    assert upstream['created_ts'] == '1788396067.7754688'
    assert upstream['source_families'] == ['repair::스위트 러너가 인코딩 계약을 안 실어 준다']
    assert claim['upstream_occurrences'] == 308
    independent = claim['independent_occurrences']
    assert independent['count'] == 0 and independent['identities'] == []
    assert len(independent['counters']) == 23 and independent['sources'] == ['repair-notes:harness']
    assert claim['status'] == 'upstream_occurrences_unverified'
    assert not {'trust', 'occurrences', 'lifecycle'} & set(claim), 'labels never surface at the top level'
    assert claim['source']['kind'] == 'observed' and claim['source']['revision'] is None


def test_nested_restatement_suspects_and_multiline_scalars_are_kept_as_data():
    extra = ('restatement_suspects:\n- jaccard: 1.0\n  name: repair-9-seam.md\n  shared:\n  - ledger:PASS x25\n'
             '  - repair-notes:harness\nnote: \'UUID column (`\'\'str\'\' object has\n  no attribute\'\'hex\'\'`)\'')
    claim = parse_lesson('harness', PATH, lesson(extra=extra), PINNED)
    assert claim['upstream']['restatement_suspects'] == [
        {'jaccard': '1.0', 'name': 'repair-9-seam.md', 'shared': ['ledger:PASS x25', 'repair-notes:harness']}]
    assert claim['upstream']['note'] == "UUID column (`'str' object has no attribute'hex'`)"
    assert claim['independent_occurrences']['count'] == 0


def test_identity_tokens_count_once_and_counters_never_count():
    evidence = ['incident:a', 'incident:a', 'ledger-event:orchestrator.427', 'ledger:PASS x45',
                'ledger:PASS x46', 'repair-notes:harness', 'something-else']
    groups = classify_evidence(evidence)
    assert groups['identities'] == ['incident:a', 'ledger-event:orchestrator.427']
    assert groups['counters'] == ['ledger:PASS x45', 'ledger:PASS x46'] and groups['unclassified'] == ['something-else']
    claim = parse_lesson('harness', 'lessons/x.md', lesson(occurrences=999, evidence=evidence), PINNED)
    assert claim['independent_occurrences']['count'] == 2 and claim['status'] == 'independently_recomputed'
    assert claim['upstream_occurrences'] == 999


@pytest.mark.parametrize('data, message', [
    (b'no frontmatter\n', 'frontmatter missing'),
    (b'---\nevidence: not-a-list\n---\n', 'Evidence tokens'),
    (b'---\nevidence:\n- \n---\n', 'Evidence tokens'),
    (b'---\nid: a\nid: b\n---\n', 'Duplicate'),
    (b'---\n- orphan\n---\n', 'must be a mapping'),
    (b'---\nx: !!python/object/apply:os.system ["echo"]\n---\n', 'Unsupported YAML tag'),
    (b'---\nid: [unclosed\n---\n', 'Invalid Lesson frontmatter YAML'),
    (b'---\nid: a\n---\n\xff\xfe', 'not UTF-8'),
    (b'---\nid: a\n---\n' + b'b' * (256 * 1024), 'byte limit'),
], ids=['no-frontmatter', 'scalar-evidence', 'empty-token', 'duplicate-key', 'list-root', 'python-tag',
        'invalid-yaml', 'not-utf8', 'oversize'])
def test_malformed_lessons_fail_explicitly(data, message):
    with pytest.raises(ContractError, match=message):
        parse_lesson('harness', 'lessons/x.md', data, PINNED)


def test_domain_rejects_typed_or_non_string_fields():
    with pytest.raises(ContractError, match='scalars must be strings'):
        experience_claim('harness', 'lessons/x.md', lesson(), PINNED, {'occurrences': 308})
    with pytest.raises(ContractError, match='keys must be strings'):
        experience_claim('harness', 'lessons/x.md', lesson(), PINNED, {1: 'a'})
    claim = experience_claim('harness', 'lessons/x.md', lesson(), PINNED, {'occurrences': '12x'})
    assert claim['upstream_occurrences'] is None and claim['upstream']['occurrences'] == '12x'


def test_basis_and_path_validation():
    with pytest.raises(ContractError, match='full commit revision'):
        parse_lesson('harness', 'lessons/x.md', lesson(), {'kind': 'pinned', 'revision': 'abc'})
    with pytest.raises(ContractError, match='omit the revision'):
        parse_lesson('harness', 'lessons/x.md', lesson(), {'kind': 'observed', 'revision': PINNED['revision']})
    for path in ('/abs/x.md', '../x.md', 'a/../x.md', ''):
        with pytest.raises(ContractError, match='lesson path'):
            parse_lesson('harness', path, lesson(), PINNED)
    with pytest.raises(ContractError, match='source name'):
        parse_lesson('bad name', 'lessons/x.md', lesson(), PINNED)


def test_crlf_frontmatter_split():
    frontmatter, body = split_frontmatter(b'---\r\nid: a\r\n---\r\nbody\r\n')
    assert frontmatter == 'id: a' and body == 'body\r\n'


def test_versions_are_separate_claims_and_reimport_is_idempotent(tmp_path):
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    directory = tmp_path / 'lessons'
    directory.mkdir()
    (directory / 'repair-cp949.md').write_bytes(lesson(occurrences=265))
    first = import_lessons([directory], 'harness', PINNED, store, artifacts, 'knowledge/lessons/')
    assert first['claims'][0]['changed'] and first['claims'][0]['path'] == 'knowledge/lessons/repair-cp949.md'
    assert first['totals'] == {'files': 1, 'upstream_occurrences_sum': 265, 'independent_occurrences_sum': 0,
                               'unverified': 1, 'recomputed': 0}
    before = copy.deepcopy(store.data)
    again = import_lessons([directory / 'repair-cp949.md'], 'harness', PINNED, store, artifacts, 'knowledge/lessons/')
    assert not again['claims'][0]['changed'] and store.data == before
    (directory / 'repair-cp949.md').write_bytes(lesson(occurrences=308))
    observed = import_lessons([directory], 'harness', OBSERVED, store, artifacts, 'knowledge/lessons/')
    assert observed['claims'][0]['changed'] and observed['claims'][0]['id'] != first['claims'][0]['id']
    versions = ExperienceClaims(store).versions('harness', 'knowledge/lessons/repair-cp949.md')
    assert [v['upstream_occurrences'] for v in versions] == [265, 308]
    assert [v['source']['kind'] for v in versions] == ['pinned', 'observed'] and [v['sequence'] for v in versions] == [1, 2]
    archived = artifacts.document(versions[1]['body_ref'])
    assert archived['sha256'] == versions[1]['source']['sha256']
    assert ExperienceClaims(store).summary() == {'claims': 2, 'upstream_occurrences_sum': 573,
                                                 'independent_occurrences_sum': 0, 'unverified': 2, 'recomputed': 0}


def test_same_bytes_acquired_on_different_bases_accumulate_without_new_versions():
    # Review counterexample (PR #36): observed -> pinned A -> pinned B of identical bytes must not be
    # refused as "different content", and must not add versions or occurrences either.
    store = MemoryStore()
    claims = ExperienceClaims(store)
    data = lesson()
    pinned_b = {'kind': 'pinned', 'revision': 'b' * 40}
    first = claims.record(parse_lesson('harness', PATH, data, OBSERVED), 'sha256:' + '0' * 64)
    second = claims.record(parse_lesson('harness', PATH, data, PINNED), 'sha256:' + '0' * 64)
    third = claims.record(parse_lesson('harness', PATH, data, pinned_b), 'sha256:' + '0' * 64)
    repeat = claims.record(parse_lesson('harness', PATH, data, PINNED), 'sha256:' + '0' * 64)
    assert first['changed'] and first['id'] == second['id'] == third['id']
    assert (second['changed'], second['acquisition_added']) == (False, True)
    assert (third['changed'], third['acquisition_added']) == (False, True)
    assert (repeat['changed'], repeat['acquisition_added']) == (False, False)
    versions = claims.versions('harness', PATH)
    assert len(versions) == 1 and versions[0]['acquisitions'] == [OBSERVED, PINNED, pinned_b]
    assert versions[0]['source']['kind'] == 'observed', 'the first acquisition stays the recorded source'
    assert claims.summary() == {'claims': 1, 'upstream_occurrences_sum': 308, 'independent_occurrences_sum': 0,
                                'unverified': 1, 'recomputed': 0}
    # Different bytes on any basis are still a separate version.
    assert claims.record(parse_lesson('harness', PATH, lesson(occurrences=309), pinned_b), 'sha256:' + '1' * 64)['changed']
    assert len(claims.versions('harness', PATH)) == 2


def test_same_id_with_different_content_is_rejected():
    store = MemoryStore()
    claim = parse_lesson('harness', 'lessons/x.md', lesson(), PINNED)
    ExperienceClaims(store).record(claim, 'sha256:' + '0' * 64)
    tampered = {**claim, 'upstream_occurrences': 1}
    with pytest.raises(ContractError, match='different content'):
        ExperienceClaims(store).record(tampered, 'sha256:' + '0' * 64)
    with pytest.raises(ContractError, match='archived first'):
        ExperienceClaims(store).record(claim, 'not-a-ref')


def test_imported_claims_never_feed_recurrence(tmp_path):
    store = MemoryStore()
    directory = tmp_path / 'lessons'
    directory.mkdir()
    for index in range(25):
        (directory / f'lesson-{index}.md').write_bytes(lesson(occurrences=308 + index))
    report = import_lessons([directory], 'harness', OBSERVED, store, FileArtifacts(str(tmp_path / 'a')))
    assert report['totals']['files'] == 25 and report['totals']['upstream_occurrences_sum'] > 7000
    service = Harness(store, organization())
    message = envelope('incident.report', 'worker:implementation', 'lead:improvement', 'record_incident',
                       {'occurrence_id': str(uuid4()), 'root_cause': 'cp949-child-encoding',
                        'scope': 'harness', 'evidence_refs': ['fixture:error']}, 'experience-test')
    result = service.record_incident(message)
    assert result['occurrences'] == 1 and result['hook_id'] is None
    with store.transaction() as tx:
        assert tx.scan('hooks') == [] and len(tx.scan('incidents')) == 1
        assert len(tx.scan('experience_claims')) == 25


def test_cli_dry_run_writes_nothing_and_import_uses_injected_store(tmp_path, capsys):
    directory = tmp_path / 'lessons'
    directory.mkdir()
    (directory / 'one.md').write_bytes(lesson())
    (directory / 'two.md').write_bytes(lesson(evidence=['incident:x']))
    (directory / 'ignored.txt').write_bytes(b'not a lesson')
    artifacts = tmp_path / 'artifacts'
    assert main([str(directory), '--basis', 'observed', '--dry-run', '--artifacts', str(artifacts)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['preview_only'] and report['totals'] == {'files': 2, 'upstream_occurrences_sum': 616,
                                                           'independent_occurrences_sum': 1, 'unverified': 1,
                                                           'recomputed': 1}
    assert not artifacts.exists()
    assert main([str(directory), '--basis', 'pinned', '--dry-run']) == 2
    assert 'full commit revision' in capsys.readouterr().err
    store = MemoryStore()
    assert main([str(directory), '--basis', 'pinned', '--revision', PINNED['revision'],
                 '--artifacts', str(artifacts), '--path-prefix', 'knowledge/lessons/'], store=store) == 0
    report = json.loads(capsys.readouterr().out)
    assert [entry['changed'] for entry in report['claims']] == [True, True] and artifacts.exists()
    assert ExperienceClaims(store).versions('harness', 'knowledge/lessons/one.md')[0]['upstream_occurrences'] == 308
    assert main([str(tmp_path / 'missing'), '--basis', 'observed', '--dry-run']) == 2
    assert preview_lessons([directory / 'two.md'], 'harness', OBSERVED)['claims'][0]['status'] == 'independently_recomputed'
