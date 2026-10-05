# Ported from SOURCE M7 tests/test_threshold_collection.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
import base64
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

# S11 M B4: the constructors take context's `validate_source` (V18 R-t1: composition wires it; required on the `legacy_source` path),
# and `application.skill_import.MAX_EVENTS` is `context.application.skill_import.MAX_EVENTS`.
# S11 M B4: `events`, `policy_repo` (the fixture, built on the TARGET's POLICY_PATHS under GIT_PREFIX, DESIGN-s8 §18 V20) and
# `current_policy` are the m7_research labelled copies of this suite's helpers (the policy sources live under `GIT_PREFIX`
# in the fixture repository, so git paths below are `GIT_PREFIX + POLICY_PATHS[0]`; `policy['sources']` is keyed without it).
from m7_research import current_policy, events, policy_repo  # noqa: F401  `policy_repo` is a pytest fixture

from codex_harness.context.adapters.skill_import import import_file
from codex_harness.context.domain.skills.import_ import validate_source
from codex_harness.entry.cli.threshold_proposals import main
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.research.adapters.threshold_policy import GIT_PREFIX, POLICY_PATHS
from codex_harness.research.application.threshold_proposals import ThresholdProposals
from codex_harness.research.application.threshold_replay import ThresholdReplay
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore


def test_current_policy_is_bound_to_regular_committed_loaded_sources(policy_repo):  # noqa: F811
    root, git = policy_repo
    policy = current_policy(git)
    assert policy['values'] == {'skill_match.FULL_BODY_MIN_SCORE': 3}
    assert set(policy['sources']) == set(POLICY_PATHS)
    source = root / (GIT_PREFIX + POLICY_PATHS[0])
    source.write_text(source.read_text(encoding='utf-8') + '\n# dirty\n', encoding='utf-8')
    assert current_policy(git) == policy  # uncommitted file is not the selected Git definition
    git._git('add', '.')
    git._git('commit', '-qm', 'different definition')
    with pytest.raises(ContractError, match='differs'):
        current_policy(git)
    assert current_policy(git, policy['revision']) == policy
    blob = git._git('rev-parse', 'HEAD:' + GIT_PREFIX + POLICY_PATHS[0])
    git._git('update-index', '--cacheinfo', f'120000,{blob},{GIT_PREFIX + POLICY_PATHS[0]}')
    git._git('commit', '-qm', 'symlink source')
    with pytest.raises(ContractError, match='regular'):
        current_policy(git)


def test_collection_records_exact_evidence_once_and_keeps_history(policy_repo, tmp_path):  # noqa: F811
    _, git = policy_repo
    policy = current_policy(git)
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    with store.transaction() as tx:
        tx.put('skill_history', 'project', {'events': events()})
    original = copy.deepcopy(store.data['skill_history', 'project'])
    service = ThresholdProposals(store, artifacts, lambda: policy, validate_source=validate_source)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.collect('project'), range(8)))
    assert all(result == results[0] for result in results)
    run = results[0]
    assert len(run['proposals']) == 1 and not run['activation_ready']
    document = artifacts.document(run['evidence_ref'])
    assert document['events'] == events() and document['policy'] == policy
    assert len(document['proposals'][0]['alternatives']) == 2
    assert store.data['skill_history', 'project'] == original
    assert sum(bucket == 'threshold_proposals' for bucket, _ in store.data) == 1
    assert not any(bucket in {'deployment', 'decisions_pending'} for bucket, _ in store.data)
    assert service.collect('other')['id'] != run['id']


def test_vacuous_reference_acceptance_is_explicitly_blocked(policy_repo, tmp_path):  # noqa: F811
    _, git = policy_repo
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    with store.transaction() as tx:
        tx.put('skill_history', 'project', {'events': events(empty=True)})
    run = ThresholdProposals(store, artifacts, lambda: current_policy(git), validate_source=validate_source).collect('project')
    row, = run['proposals']
    # FA-021: the value that admits nothing (4) is refused by the gate itself, visibly; only the
    # value that still admits matches (2) can be suggested, and it is still not activation-ready.
    vacuous = next(c for c in row['proposal']['alternatives'] if c['value'] == 4)
    assert vacuous['report']['gate']['reason'] == 'empty_admission' and not vacuous['report']['gate']['accept']
    assert row['proposal']['suggested'] == 2 and 'empty_admission' not in row['activation_blockers']
    assert not row['activation_ready'] and 'native_task_success_and_release_review_required' in row['activation_blockers']
    for part in row['proposal']['report']['partitions'].values():
        assert part['current_admitted_entries'] > 0 and part['proposed_admitted_entries'] > 0


def test_import_to_replay_and_proposal_preserves_legacy_provenance(policy_repo, tmp_path):  # noqa: F811
    _, git = policy_repo
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    source = tmp_path / 'legacy.jsonl'
    source.write_text(''.join(json.dumps({'ts': event['at'], 'top': [
        {**entry, 'name': str(index)} for index, entry in enumerate(event['top'])]}) + '\n'
        for event in events()), encoding='utf-8')
    imported = import_file(source, 'project', 'segment', store, artifacts)
    before = copy.deepcopy(store.data)
    replay = ThresholdReplay(store, validate_source=validate_source).evaluate('project', legacy_source='segment', old_value=3,
        proposed_value=4, holdout_boundary='2026-01-01T00:00:28Z')
    assert replay['source_ref'] == imported['source_ref'] and replay['report']['gate']['accept']
    assert replay['report']['partitions']['holdout']['events'] == 12
    assert store.data == before
    run = ThresholdProposals(store, artifacts, lambda: current_policy(git), validate_source=validate_source).collect('project', legacy_source='segment')
    row, = run['proposals']
    assert 'historical_policy_and_skill_versions_unknown' in row['activation_blockers']
    evidence = artifacts.document(run['evidence_ref'])
    assert evidence['source_ref'] == imported['source_ref'] and evidence['events'] == replay['events']
    for key, value in before.items():
        assert store.data[key] == value


def test_real_git_cli_collection_and_stale_code_rejection(policy_repo, tmp_path, capsys):  # noqa: F811
    root, git = policy_repo
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('skill_history', digest('github:owner/repo'), {'events': events()})
    args = ['--github-repo', 'owner/repo', '--harness-repo', str(root), '--artifacts', str(tmp_path / 'artifacts')]
    assert main(args, store=store) == 0
    run = json.loads(capsys.readouterr().out)
    assert len(run['proposals']) == 1
    source = root / (GIT_PREFIX + POLICY_PATHS[0])
    source.write_text('FULL_BODY_MIN_SCORE = 99\n', encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'mismatch')
    before = copy.deepcopy(store.data)
    assert main(args, store=store) == 2
    assert 'Traceback' not in capsys.readouterr().err and store.data == before


def test_nonfinite_source_metadata_cannot_enter_evidence(policy_repo, tmp_path):  # noqa: F811
    _, git = policy_repo
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    corpus = events()
    corpus[0]['extra'] = float('nan')
    with store.transaction() as tx:
        tx.put('skill_history', 'project', {'events': corpus})
    with pytest.raises(ContractError, match='finite JSON'):
        ThresholdProposals(store, artifacts, lambda: current_policy(git), validate_source=validate_source).collect('project')
    assert not list(artifacts.root.glob('*.txt'))
    assert not any(bucket.startswith('threshold_') for bucket, _ in store.data)


@pytest.mark.parametrize('sized', [True, False])
def test_reference_verdict_never_removes_required_release_blocker(policy_repo, tmp_path, sized):  # noqa: F811
    _, git = policy_repo
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    corpus = events()
    if not sized:
        for event in corpus:
            for entry in event['top']:
                del entry['body_chars']
    with store.transaction() as tx:
        tx.put('skill_history', 'project', {'events': corpus})
    run = ThresholdProposals(store, artifacts, lambda: current_policy(git), validate_source=validate_source).collect('project')
    row, = run['proposals']
    assert 'native_task_success_and_release_review_required' in row['activation_blockers']
    assert not row['activation_ready'] and not run['activation_ready']
    assert row['proposal']['reference_accepted'] is sized
    assert ('reference_gate_rejected' in row['activation_blockers']) is not sized
    if not sized:
        assert row['proposal']['suggested'] is None
        assert row['proposal']['report']['gate']['reason'] == 'non_finite_metric'


def test_literal_crlf_git_blob_matches_normalized_loaded_source(policy_repo):  # noqa: F811
    root, git = policy_repo
    path = GIT_PREFIX + POLICY_PATHS[0]
    source = root / path
    source.write_bytes(source.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8'))
    blob = git._git('hash-object', '-w', '--no-filters', path)
    git._git('update-index', '--cacheinfo', f'100644,{blob},{path}')
    git._git('commit', '-qm', 'literal CRLF policy blob')
    assert git._git('cat-file', '-s', blob) == str(len(source.read_bytes()))
    policy = current_policy(git)
    assert '\r' not in policy['sources'][POLICY_PATHS[0]]['text']
    assert policy['values']['skill_match.FULL_BODY_MIN_SCORE'] == 3


def test_import_append_tail_and_separate_segment_keep_replayable_lineage(policy_repo, tmp_path, monkeypatch):  # noqa: F811
    _, git = policy_repo
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    monkeypatch.setattr('codex_harness.context.application.skill_import.MAX_EVENTS', 30)
    source = tmp_path / 'legacy.jsonl'
    lines = [(json.dumps({'ts': event['at'], 'top': [{**entry, 'name': str(index)}
              for index, entry in enumerate(event['top'])]}) + '\n').encode('utf-8') for event in events()]
    source.write_bytes(b''.join(lines[:20]))
    first = import_file(source, 'project', 'segment-1', store, artifacts)
    source.write_bytes(b''.join(lines))
    latest = import_file(source, 'project', 'segment-1', store, artifacts)
    other = import_file(source, 'project', 'segment-2', store, artifacts)
    assert latest['source_ref'] != first['source_ref']
    assert latest['source_ref'] != other['source_ref']
    service = ThresholdProposals(store, artifacts, lambda: current_policy(git), validate_source=validate_source)
    for segment, imported in [('segment-1', latest), ('segment-2', other)]:
        run = service.collect('project', legacy_source=segment)
        evidence = artifacts.document(run['evidence_ref'])
        raw = base64.b64decode(artifacts.document(evidence['source_ref'])['body'])
        assert evidence['source_ref'] == imported['source_ref'] and raw == b''.join(lines)
        assert len(evidence['events']) == 30
        for event in evidence['events']:
            line = raw.splitlines(keepends=True)[event['source_line'] - 1]
            assert hashlib.sha256(line).hexdigest() == event['raw_line_sha256']
            assert json.loads(line)['ts'] == event['at']
        assert evidence['legacy_source'] == segment
