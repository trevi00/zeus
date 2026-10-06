import base64
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.skill_audit import main as audit_cli
from codex_harness.adapters.skill_import import import_file, main
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.skill_import import SkillImport
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.skill_audit import timestamp
from codex_harness.domain.skill_import import project_jsonl, source_document


def row(ts='2020-01-01T00:00:00Z', **changes):
    record = {'ts': ts, 'top': [{'name': 'broad.md', 'score': 1, 'dims': ['kw:x'], 'body_chars': 120}]}
    record.update(changes)
    return json.dumps(record).encode() + b'\n'


def test_replay_append_torn_tail_and_changed_prefix_preserve_source(tmp_path):
    source = tmp_path / 'skill-match.jsonl'
    artifacts, store = FileArtifacts(str(tmp_path / 'artifacts')), MemoryStore()
    source.write_bytes(row() + row() + b'{"ts":')
    first = import_file(source, 'project', 'segment-1', store, artifacts)
    assert first['added']['events'] == 2 and first['pending_bytes'] == 6
    archived = artifacts.document(first['source_ref'])
    assert base64.b64decode(archived['body']) == source.read_bytes()
    before = copy.deepcopy(store.data)
    assert not import_file(source, 'project', 'segment-1', store, artifacts)['changed']
    assert store.data == before
    source.write_bytes(row() + row() + row())
    third = import_file(source, 'project', 'segment-1', store, artifacts)
    assert third['added']['events'] == 1 and third['total']['events'] == 3
    report = SkillImport(store).audit('project', 'segment-1')
    assert report['skills'][0]['count'] == 3
    assert report['identity_status'] == 'historical_skill_version_unknown'
    assert SkillImport(store).audit('project', 'segment-1', cutoff=timestamp('2021-01-01T00:00:00Z'))[
        'invocations'] == 0
    before = copy.deepcopy(store.data)
    source.write_bytes(row('2021-01-01T00:00:00Z') + row() + row())
    with pytest.raises(ContractError, match='prefix changed'):
        import_file(source, 'project', 'segment-1', store, artifacts)
    assert store.data == before
    assert import_file(source, 'project', 'segment-2', store, artifacts)['changed']
    assert not any(bucket in {'skill_history', 'skill_observations'} for bucket, _ in store.data)


def test_invalid_bytes_entries_dates_and_line_boundaries_are_explicit():
    data = b'\xff\n\nnull\n{}\n' + row(None) + row(top=[None, {'name': 'bad', 'score': True}])
    data += b'{\rbroken}\n' + row()
    parsed = project_jsonl(data, 'segment')
    assert parsed['counts'] == {'lines': 8, 'events': 2, 'invalid_lines': 5,
                                'invalid_entries': 2, 'blank_lines': 1}
    assert parsed['consumed_bytes'] == len(data)
    assert parsed['events'][0]['at'] is None
    assert parsed['events'][1]['top'][0]['body_chars'] == 120
    assert parsed['events'][1]['top'][0]['content_ref'].startswith('legacy-version-unknown:')
    assert any(issue['reason'] == 'invalid_top_entry' for issue in parsed['issues'])
    assert any(issue['reason'] == 'no_valid_top_entries' for issue in parsed['issues'])
    duplicate = {'name': 'same.md', 'score': 1}
    assert len(project_jsonl(row(top=[duplicate, duplicate]), 'segment')['events'][0]['top']) == 2


@pytest.mark.parametrize('data', [
    b'{"ts":NaN,"top":[]}\n', b'{"ts":"\\ud800","top":[]}\n',
    b'{"ts":1e999,"top":[]}\n',
    b'{"ts":"\\u0000","top":[]}\n', b'{"top":' + b'[' * 2000 + b']' * 2000 + b'}\n',
])
def test_unrepresentable_json_never_poison_postgres_projection(data):
    result = project_jsonl(data + row(), 'segment')
    assert result['counts']['invalid_lines'] == 1 and result['counts']['events'] == 1


def test_size_limits_crlf_and_incomplete_record(monkeypatch):
    monkeypatch.setattr('codex_harness.domain.skill_import.MAX_INPUT_BYTES', 100)
    with pytest.raises(ContractError, match='byte limit'):
        project_jsonl(b'x' * 101, 'segment')
    monkeypatch.setattr('codex_harness.domain.skill_import.MAX_INPUT_BYTES', 4096)
    parsed = project_jsonl(row().replace(b'\n', b'\r\n') + row()[:-1], 'segment')
    assert parsed['counts']['events'] == 1 and parsed['pending_bytes'] == len(row()) - 1
    monkeypatch.setattr('codex_harness.domain.skill_import.MAX_LINE_BYTES', 10)
    assert project_jsonl(row(), 'segment')['counts']['invalid_lines'] == 1


def test_unbounded_integer_score_is_retained_only_in_raw_source():
    parsed = project_jsonl(row(top=[{'name': 'large', 'score': 10**500}]) + row(), 'segment')
    assert parsed['counts']['invalid_entries'] == 1
    assert parsed['counts']['invalid_lines'] == 1 and parsed['counts']['events'] == 1


@pytest.mark.parametrize('entry', [
    {'name': 'x' * 513, 'score': 1},
    {'name': 'x', 'score': 1, 'dims': ['kw:x'] * 129},
    {'name': 'x', 'score': 1, 'dims': ['x' * 513]},
])
def test_oversized_projected_fields_are_counted(entry):
    result = project_jsonl(row(top=[entry]), 'segment')
    assert result['counts']['invalid_entries'] == 1 and result['events'] == []
    assert result['issues'][0]['reason'] == 'oversized_top_entry'


def test_wrong_category_does_not_claim_source_and_pending_snapshot_refs_are_distinct(tmp_path):
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    path = tmp_path / 'source.jsonl'
    path.write_bytes(b'{"name":"hook-latency","duration":5}\n')
    with pytest.raises(ContractError, match='input log category'):
        import_file(path, 'project', 'source', store, artifacts)
    assert store.data == {}
    path.write_bytes(row())
    committed = import_file(path, 'project', 'source', store, artifacts)
    path.write_bytes(row() + b'{"partial":')
    pending = import_file(path, 'project', 'source', store, artifacts)
    assert not pending['changed']
    assert pending['source_ref'] == committed['source_ref'] != pending['input_ref']


def test_concurrent_reimport_and_retention_keep_one_cursor(monkeypatch):
    monkeypatch.setattr('codex_harness.application.skill_import.MAX_EVENTS', 2)
    store = MemoryStore()
    importer = SkillImport(store)
    data = row() * 3
    ref = 'sha256:' + digest(source_document(data, 'segment'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: importer.ingest('project', 'segment', data, ref), range(8)))
    assert sum(r['changed'] for r in results) == 1
    with store.transaction() as tx:
        state = tx.get('legacy_skill_imports', digest(['project', 'segment']))
    assert state['counts']['events'] == 3 and len(state['events']) == 2
    assert not importer.ingest('project', 'segment', data, ref)['changed']
    assert importer.audit('other-project', 'segment')['invocations'] == 0
    with pytest.raises(ContractError, match='Source artifact'):
        importer.ingest('project', 'segment', data, 'sha256:wrong')


def test_cli_preview_has_no_database_or_artifact_writes_and_audit_selects_legacy(tmp_path, capsys):
    path = tmp_path / 'legacy.jsonl'
    path.write_bytes(row() * 3)
    target = tmp_path / 'artifacts'
    assert main([str(path), '--source-id', 'segment', '--github-repo', 'owner/repo',
                 '--artifacts', str(target), '--dry-run']) == 0
    assert json.loads(capsys.readouterr().out)['counts']['events'] == 3
    assert not target.exists()
    store = MemoryStore()
    import_file(path, digest('github:owner/repo'), 'segment', store, FileArtifacts(str(target)))
    before = copy.deepcopy(store.data)
    assert audit_cli(['--github-repo', 'owner/repo', '--legacy-source', 'segment', '--json'], store=store) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['invocations'] == 3 and report['source_ref'].startswith('sha256:')
    assert store.data == before
    assert audit_cli(['--github-repo', 'owner/repo', '--legacy-source', 'segment'], store=store) == 0
    text = capsys.readouterr().out
    assert 'LEGACY SOURCE: segment' in text and 'Historical skill version unknown' in text
    assert report['source_ref'] in text
    assert audit_cli(['--github-repo', 'owner/repo', '--json'], store=store) == 0
    assert json.loads(capsys.readouterr().out)['invocations'] == 0
