import copy
import json

import pytest
from test_threshold_collection import events
from test_threshold_collection import policy_repo as source_policy_repo

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.native_routing_replay import NativeRoutingReplay
from codex_harness.adapters.skill_routing import route_skills
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.threshold_proposals import main
from codex_harness.domain.model import ContextItem, canonical, digest


@pytest.fixture
def policy_repo(tmp_path):
    return source_policy_repo.__wrapped__(tmp_path)


def routed(tmp_path):
    class EmptyGit:
        def _git(self, *args, **kwargs):
            return ''
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    items, records = [], []
    for name, keywords, boost, body in [
        ('boosted', 'alpha', 3, 'BOOSTED'),
        ('relevant', 'alpha beta gamma', 0, 'R' * 5000),
        ('relevant2', 'alpha beta gamma', 0, 'x' * 1700),
        ('unmatched', 'unrelated', 0, 'HIDDEN')]:
        path = '.harness/skills/_common/' + name + '.md'
        text = f'---\nkeywords: {keywords}\n---\n{body}'
        ref = artifacts.put(text, 'fixture')['ref']
        records.append({'path': path, 'content_ref': ref, 'file': path, 'pipeline_boost': boost})
        items.append(ContextItem('project-skill:' + path, text, ref, 'a' * 40, 15))
    output, routing = route_skills(EmptyGit(), artifacts, str(tmp_path), 'a' * 40,
                                  'alpha beta gamma', items, records)
    manifest = {'skills': records, 'routing': routing, 'revision': 'a' * 40}
    ref = artifacts.put(canonical(manifest), 'fixture-manifest')['ref']
    return artifacts, manifest, ref, output


def test_replay_matches_actual_bodies_and_uses_base_instead_of_boosted_score(tmp_path):
    artifacts, _, ref, output = routed(tmp_path)
    report = NativeRoutingReplay(artifacts).evaluate([{'manifest_ref': ref}], [1, 3, 5])
    result = report['manifests'][ref]
    assert result['status'] == 'replayed'
    actual = {item.id.removeprefix('project-skill:'): digest(item.body)
              for item in output if item.priority == 18}
    assert result['baseline']['selected'] == actual
    lower, current, higher = result['alternatives']
    assert current['selected'] == actual
    assert not any('boosted' in path for path in current['selected'])
    assert any('boosted' in path for path in lower['selected'])
    assert higher['selected'] == {} and higher['body_characters'] == 0
    assert all(row['body_characters'] <= 4000 for row in result['alternatives'])
    assert not report['activation_ready']


@pytest.mark.parametrize('change', ['hash', 'model', 'body', 'eligibility', 'duplicate'])
def test_unreproducible_or_missing_evidence_is_not_success(tmp_path, change):
    artifacts, manifest, _, _ = routed(tmp_path)
    if change == 'model':
        manifest['routing'].pop('admission_model')
    elif change == 'duplicate':
        manifest['skills'].append(copy.deepcopy(manifest['skills'][0]))
    else:
        row = next(row for row in manifest['skills'] if row['tier'] == 'full')
        if change == 'hash':
            row['rendered_hash'] = 'wrong'
        elif change == 'body':
            (artifacts.root / (row['content_ref'][7:] + '.txt')).unlink()
        else:
            row['routing_eligible'] = False
    ref = artifacts.put(canonical(manifest), 'bad-fixture')['ref']
    report = NativeRoutingReplay(artifacts).evaluate([{'manifest_ref': ref}, {'top': []}], [3, 4])
    assert report['replayed_events'] == 0 and report['total_events'] == 2
    assert all(row['status'] == 'unavailable' for row in report['observations'])
    details = {'hash': 'Native baseline does not reproduce', 'model': 'Unsupported admission model',
               'eligibility': 'Incomplete routing eligibility', 'duplicate': 'Duplicate routing identity'}
    if change == 'body':
        assert report['manifests'][ref]['reason'] == 'FileNotFoundError'
        assert 'detail' not in report['manifests'][ref]
    else:
        assert report['manifests'][ref]['detail'] == details[change]


def test_explicit_new_round_recovers_missing_evidence_without_rewriting_old_run(policy_repo, tmp_path, capsys):
    root, _ = policy_repo
    artifacts, manifest, ref, _ = routed(tmp_path)
    row = next(row for row in manifest['skills'] if row['tier'] == 'full')
    body_path = artifacts.root / (row['content_ref'][7:] + '.txt')
    original = body_path.read_bytes()
    body_path.unlink()
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('skill_history', digest('github:owner/repo'),
               {'events': [{**event, 'manifest_ref': ref} for event in events()]})
    args = ['--github-repo', 'owner/repo', '--harness-repo', str(root), '--artifacts', str(artifacts.root)]
    assert main(args, store=store) == 0
    old = json.loads(capsys.readouterr().out)
    assert 'native_replay_incomplete' in old['proposals'][0]['activation_blockers']
    body_path.write_bytes(original)
    assert main(args, store=store) == 0
    assert json.loads(capsys.readouterr().out) == old
    assert main([*args, '--evaluation-round', '1'], store=store) == 0
    new = json.loads(capsys.readouterr().out)
    assert new['id'] != old['id'] and new['evaluation_round'] == 1
    assert 'native_replay_incomplete' not in new['proposals'][0]['activation_blockers']
    assert 'native_task_success_and_release_review_required' in new['proposals'][0]['activation_blockers']
    assert not new['activation_ready']
    assert main([*args, '--evaluation-round', '1'], store=store) == 0
    assert json.loads(capsys.readouterr().out) == new
    with store.transaction() as tx:
        assert tx.get('threshold_proposal_runs', old['id']) == old
        assert len(tx.scan('threshold_proposal_runs')) == 2
    assert main([*args, '--evaluation-round', '-1'], store=store) == 2


def test_real_collection_cli_archives_native_comparison_with_reference_proposals(policy_repo, tmp_path, capsys):
    root, _ = policy_repo
    artifacts, _, ref, _ = routed(tmp_path)
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('skill_history', digest('github:owner/repo'),
               {'events': [{**event, 'manifest_ref': ref} for event in events()]})
    assert main(['--github-repo', 'owner/repo', '--harness-repo', str(root),
                 '--artifacts', str(artifacts.root)], store=store) == 0
    run = json.loads(capsys.readouterr().out)
    document = artifacts.document(run['evidence_ref'])
    assert len(document['proposals']) == 1
    native = document['native_routing']
    assert native['replayed_events'] == 40 and native['values'] == [2, 3, 4]
    assert not run['activation_ready'] and not native['activation_ready']
    assert native['distinct_manifests'] == 1 and len(native['manifests']) == 1
    # Losing transitive files cannot create another run for the same input basis.
    native_ref = native['manifests'][ref]['body_refs'][0]
    (artifacts.root / (native_ref[7:] + '.txt')).unlink()
    assert main(['--github-repo', 'owner/repo', '--harness-repo', str(root),
                 '--artifacts', str(artifacts.root)], store=store) == 0
    assert json.loads(capsys.readouterr().out) == run


def test_actual_project_context_manifest_reproduces(policy_repo, tmp_path):
    from codex_harness.adapters.project_skills import project_context

    root, git = policy_repo
    path = root / '.harness/skills/_common/fixture.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nkeywords: alpha beta gamma\n---\nREAL BODY', encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'project skill fixture')
    revision = git._git('rev-parse', 'HEAD')
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    output, selection = project_context(git, artifacts, str(root), revision, 'alpha beta gamma')
    report = NativeRoutingReplay(artifacts).evaluate([{'manifest_ref': selection['manifest_ref']}], [3, 4])
    assert report['status'] == 'complete'
    replayed = report['manifests'][selection['manifest_ref']]
    assert replayed['baseline']['selected'] == {
        item.id.removeprefix('project-skill:'): digest(item.body) for item in output if item.priority == 18}
