"""FA-030: a confirmed snapshot is verified strictly with its full denominator; missing is not empty; a change
names the checks it obliges (INV-SNAPSHOT-001).

The upstream status CLI dropped broken JSONL lines, treated a missing file as an empty state, never
required schema_version or id and returned success; its CI could skip the snapshot job by path filter.
"""
import json

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.snapshot_imports import BUCKET, SnapshotImports
from codex_harness.domain.model import ContractError
from codex_harness.domain.snapshot_integrity import (
    FILE_STATES,
    parse_manifest,
    required_checks,
    verify_file,
    verify_snapshot,
)

MANIFEST = {'version': 1, 'required': {
    'experience/lessons.jsonl': {'kind': 'jsonl', 'schema_version': 2},
    'experience/retractions.jsonl': {'kind': 'jsonl', 'schema_version': 2, 'required_fields': ['schema_version', 'id', 'retracts'],
                                     'references': {'retracts': 'experience/lessons.jsonl'}, 'allow_empty': True},
    'graduation.json': {'kind': 'json', 'schema_version': 1},
}}


def line(**fields):
    return (json.dumps(fields) + '\n').encode('utf-8')


def good():
    return {'experience/lessons.jsonl': line(schema_version=2, id='l1') + line(schema_version=2, id='l2'),
            'experience/retractions.jsonl': line(schema_version=2, id='r1', retracts='l1'),
            'graduation.json': json.dumps({'schema_version': 1, 'id': 'grad'}).encode('utf-8')}


def test_manifest_is_closed_and_references_must_resolve():
    parsed = parse_manifest(MANIFEST)
    assert parsed['required']['experience/lessons.jsonl']['required_fields'] == ['schema_version', 'id'] and parsed['manifest_hash']
    for bad in ({'version': 1, 'required': {}}, {'version': 2, 'required': MANIFEST['required']},
                {'version': 1, 'required': {'../x.jsonl': {'kind': 'jsonl', 'schema_version': 1}}},
                {'version': 1, 'required': {'a.jsonl': {'kind': 'yaml', 'schema_version': 1}}},
                {'version': 1, 'required': {'a.jsonl': {'kind': 'jsonl', 'schema_version': 0}}},
                {'version': 1, 'required': {'a.jsonl': {'kind': 'jsonl', 'schema_version': 1, 'references': {'x': 'missing.jsonl'}}}},
                {'version': 1, 'required': {'a.jsonl': {'kind': 'jsonl', 'schema_version': 1, 'allow_empty': 'yes'}}}):
        with pytest.raises(ContractError):
            parse_manifest(bad)


def test_confirmed_snapshot_is_strict_and_the_denominator_is_complete():
    report = verify_snapshot(good(), MANIFEST)
    assert report['status'] == 'valid' and report['denominator']['records_valid'] == 4 and report['denominator']['lines_corrupt'] == 0
    assert report['denominator']['files_required'] == 3 == report['denominator']['files_present'] and report['snapshot_hash']
    # A broken line is corrupt, not dropped (upstream: silently discarded, success).
    broken = {**good(), 'experience/lessons.jsonl': good()['experience/lessons.jsonl'] + b'{"schema_version": 2, "id": "l3"\n'}
    report = verify_snapshot(broken, MANIFEST)
    assert report['status'] == 'invalid' and report['files']['experience/lessons.jsonl']['state'] == 'corrupt'
    assert report['denominator']['lines_corrupt'] == 1 and report['denominator']['records_valid'] == 4
    # A non-object line, a line without id, a wrong schema version: each is named, none is success.
    for tail, state, match in ((b'[1, 2]\n', 'corrupt', 'not an object'), (line(schema_version=2), 'corrupt', 'missing id'),
                               (line(schema_version=3, id='x'), 'version_mismatch', 'is not 2'),
                               (line(schema_version=2, id=''), 'corrupt', 'non-empty text'),
                               (b'{"schema_version": 2, "id": "n", "v": NaN}\n', 'corrupt', 'non-finite')):
        report = verify_snapshot({**good(), 'experience/lessons.jsonl': good()['experience/lessons.jsonl'] + tail}, MANIFEST)
        assert report['status'] == 'invalid' and report['files']['experience/lessons.jsonl']['state'] == state
        assert any(match in error for error in report['files']['experience/lessons.jsonl']['errors'])
    # Missing, unreadable, empty-where-required and legitimately empty are four different states.
    missing = verify_snapshot({k: v for k, v in good().items() if k != 'graduation.json'}, MANIFEST)
    assert missing['status'] == 'invalid' and missing['files']['graduation.json']['state'] == 'missing' and missing['denominator']['files_missing'] == 1
    unreadable = verify_snapshot({**good(), 'graduation.json': PermissionError('denied')}, MANIFEST)
    assert unreadable['files']['graduation.json']['state'] == 'unreadable' and unreadable['denominator']['files_unreadable'] == 1
    empty_required = verify_snapshot({**good(), 'experience/lessons.jsonl': b''}, MANIFEST)
    assert empty_required['status'] == 'invalid' and empty_required['files']['experience/lessons.jsonl']['state'] == 'corrupt'
    empty_allowed = verify_snapshot({**good(), 'experience/retractions.jsonl': b''}, MANIFEST)
    assert empty_allowed['status'] == 'valid' and empty_allowed['files']['experience/retractions.jsonl']['state'] == 'empty'
    assert empty_allowed['denominator']['files_empty'] == 1 and 'not empty' in empty_allowed['note']
    # A malformed graduation document is corrupt, not an empty state (upstream: empty, success).
    bad_doc = verify_snapshot({**good(), 'graduation.json': b'{"schema_version": 1'}, MANIFEST)
    assert bad_doc['status'] == 'invalid' and bad_doc['files']['graduation.json']['state'] == 'corrupt'
    assert verify_snapshot({**good(), 'graduation.json': json.dumps({'schema_version': 9, 'id': 'g'}).encode()}, MANIFEST)['files']['graduation.json']['state'] == 'version_mismatch'
    # A retraction of an id that no lesson declares dangles; the snapshot is invalid.
    dangling = verify_snapshot({**good(), 'experience/retractions.jsonl': line(schema_version=2, id='r1', retracts='ghost')}, MANIFEST)
    assert dangling['status'] == 'invalid' and dangling['dangling_references'][0]['value'] == 'ghost'
    # A reference that is not text is invalid, not skipped (review, PR #61).
    typed = verify_snapshot({**good(), 'experience/retractions.jsonl': line(schema_version=2, id='r1', retracts=['l1'])}, MANIFEST)
    assert typed['status'] == 'invalid' and typed['dangling_references'][0]['problem'] == 'reference must be text'
    assert 'parsed' not in typed['files']['experience/retractions.jsonl'], 'validated records are consumed, not reported'
    extra = verify_snapshot({**good(), 'stray.txt': b'x'}, MANIFEST)
    assert extra['status'] == 'valid' and extra['denominator']['extra_files'] == ['stray.txt']
    assert set(FILE_STATES) >= {'valid', 'empty', 'missing', 'unreadable', 'corrupt', 'version_mismatch'}


def test_json_documents_resolve_references_whatever_their_layout():
    # Review counterexample (PR #61): the reference pass re-parsed line by line, so a pretty-printed
    # document with a dangling parent passed while the compact form failed.
    manifest = {'version': 1, 'required': {
        'lessons.jsonl': {'kind': 'jsonl', 'schema_version': 1},
        'graduation.json': {'kind': 'json', 'schema_version': 1, 'required_fields': ['schema_version', 'id', 'parent'],
                            'references': {'parent': 'lessons.jsonl'}}}}
    lessons = line(schema_version=1, id='l1')
    for layout in (json.dumps({'schema_version': 1, 'id': 'g', 'parent': 'ghost'}),
                   json.dumps({'schema_version': 1, 'id': 'g', 'parent': 'ghost'}, indent=2),
                   json.dumps({'schema_version': 1, 'id': 'g', 'parent': 'ghost'}, indent=2).replace('\n', '\r\n')):
        report = verify_snapshot({'lessons.jsonl': lessons, 'graduation.json': layout.encode('utf-8')}, manifest)
        assert report['status'] == 'invalid' and report['denominator']['dangling_references'] == 1, layout
        assert report['dangling_references'] == [{'file': 'graduation.json', 'line': 1, 'field': 'parent', 'target': 'lessons.jsonl',
                                                  'value': 'ghost', 'problem': 'no such id'}]
    resolved = verify_snapshot({'lessons.jsonl': lessons, 'graduation.json': json.dumps({'schema_version': 1, 'id': 'g', 'parent': 'l1'}, indent=2).encode()}, manifest)
    assert resolved['status'] == 'valid' and resolved['denominator']['dangling_references'] == 0
    nested = verify_snapshot({'lessons.jsonl': lessons, 'graduation.json': json.dumps({'schema_version': 1, 'id': 'g', 'parent': {'id': 'l1'}}).encode()}, manifest)
    assert nested['status'] == 'invalid' and nested['dangling_references'][0]['problem'] == 'reference must be text'


def test_torn_tail_is_tolerated_live_and_refused_confirmed():
    torn = {**good(), 'experience/lessons.jsonl': good()['experience/lessons.jsonl'] + b'{"schema_version": 2, "id": "l3"'}
    live = verify_snapshot(torn, MANIFEST, mode='live')
    assert live['status'] == 'valid' and live['files']['experience/lessons.jsonl'].get('torn_tail') is True
    assert live['denominator']['torn_tails'] == 1 and live['denominator']['records_valid'] == 4, 'the torn line is not a record'
    confirmed = verify_snapshot(torn, MANIFEST, mode='confirmed')
    assert confirmed['status'] == 'invalid' and confirmed['files']['experience/lessons.jsonl']['state'] == 'corrupt'
    assert any('torn tail' in e for e in confirmed['files']['experience/lessons.jsonl']['errors'])
    with pytest.raises(ContractError, match='Unknown verification mode'):
        verify_file('x', b'', {'kind': 'jsonl', 'schema_version': 1, 'required_fields': ['id'], 'references': {}, 'allow_empty': True}, 'draft')


def test_changes_oblige_checks_and_skipped_is_never_passed():
    policy = {'brain/': ['snapshot_integrity'], 'skills/': ['skill_validation'], 'src/': ['unit_suite', 'ruff'], 'docs/': []}
    with pytest.raises(ContractError, match='Check policy'):
        required_checks(['brain/x.jsonl'], policy)
    policy.pop('docs/')
    brain = required_checks(['brain/snapshot/lessons.jsonl'], policy)
    assert brain['status'] == 'checks_required' and brain['checks_required'] == ['snapshot_integrity']
    mixed = required_checks(['brain/a.jsonl', 'src/x.py', 'src/y.py', 'README.md'], policy)
    assert mixed['status'] == 'unmapped_changes' and mixed['unmapped'] == ['README.md'] and mixed['changes'] == 4
    assert mixed['obligations']['unit_suite'] == ['src/x.py', 'src/y.py']
    none = required_checks([], policy)
    assert none['status'] == 'no_checks_required' and 'never a passed check' in none['note']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_import_binds_bytes_and_revisions_and_keeps_invalid_snapshots_as_failures(backend, request, tmp_path):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    imports = SnapshotImports(store, FileArtifacts(str(tmp_path / 'artifacts')))
    binding = {'source_revision': 'a' * 40, 'tool_revision': 'b' * 40, 'environment': 'windows-11'}
    row = imports.import_snapshot(good(), MANIFEST, binding=binding)
    assert row['status'] == 'valid' and row['importable'] and set(row['files']) == set(good())
    assert imports.import_snapshot(good(), MANIFEST, binding=binding) == row
    archived = imports.artifacts.document(row['files']['experience/lessons.jsonl'])
    assert archived['raw'].encode('latin-1') == good()['experience/lessons.jsonl'] and archived['sha256']
    broken = {**good(), 'experience/lessons.jsonl': good()['experience/lessons.jsonl'] + b'{"schema_version": 2\n'}
    failed = imports.import_snapshot(broken, MANIFEST, binding=binding)
    assert failed['status'] == 'invalid' and not failed['importable'] and failed['report']['denominator']['lines_corrupt'] == 1
    assert imports.artifacts.document(failed['files']['experience/lessons.jsonl'])['raw'].encode('latin-1') == broken['experience/lessons.jsonl'], 'the failing bytes are kept'
    with store.transaction() as tx:
        assert imports.require_valid(tx, row['id'])['id'] == row['id']
        with pytest.raises(ContractError, match='Snapshot import is invalid: files_corrupt=1, lines_corrupt=1'):
            imports.require_valid(tx, failed['id'])
        with pytest.raises(ContractError, match='missing'):
            imports.require_valid(tx, 'nope')
        assert len(tx.scan(BUCKET)) == 2 and all(r['binding'] == binding for r in tx.scan(BUCKET))
    for bad in ({**binding, 'source_revision': 'HEAD'}, {**binding, 'environment': ''}, {'source_revision': 'a' * 40}):
        with pytest.raises(ContractError):
            imports.import_snapshot(good(), MANIFEST, binding=bad)
    missing_file = imports.import_snapshot({k: v for k, v in good().items() if k != 'graduation.json'}, MANIFEST, binding=binding)
    assert missing_file['status'] == 'invalid' and missing_file['files'].get('graduation.json') is None
    assert missing_file['report']['files']['graduation.json']['state'] == 'missing'
