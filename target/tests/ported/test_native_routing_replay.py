"""Ported SOURCE M7 suite `tests/test_native_routing_replay.py` run against the target (REBUILD-DESIGN-v2 §5.3 S2).

Import paths rewritten to the target modules; any other adaptation is named in place.

Not ported here (owning slice; carried forward, listed in the S2 coverage evidence):
- test_actual_project_context_manifest_reproduces: S8 research: the Git-pinned native threshold policy repository (runtime_thresholds/threshold_proposals)
- test_explicit_new_round_recovers_missing_evidence_without_rewriting_old_run: S8 research: the threshold-proposal collection CLI (M7 adapters.threshold_proposals.main)
- test_real_collection_cli_archives_native_comparison_with_reference_proposals: S8 research: the threshold-proposal collection CLI (M7 adapters.threshold_proposals.main)
"""
import copy
from functools import partial as _partial

import pytest
from conftest import NATIVE_THRESHOLDS as _THRESHOLDS

from codex_harness.context.adapters import project_skills as _project_skills
from codex_harness.context.adapters import skill_routing as _skill_routing
from codex_harness.context.adapters.native_routing_replay import NativeRoutingReplay
from codex_harness.context.adapters.skill_routing import route_skills
from codex_harness.context.domain.packet import ContextItem
from codex_harness.kernel.ids import canonical, digest
from codex_harness.storage.adapters.file_artifacts import FileArtifacts

# Adapted: the native threshold definition reaches context through context.ports.ThresholdPolicySource
# (research implements it in S8); these suites supply the packaged definition.
project_context = _partial(_project_skills.project_context, thresholds=_THRESHOLDS)  # noqa: F811
route_skills = _partial(_skill_routing.route_skills, threshold_policy=_THRESHOLDS.effective_policy())  # noqa: F811




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






