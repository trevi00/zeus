import json

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.skill_guidance import guidance_context
from codex_harness.domain.skill_guidance import (
    cross_references,
    detect_phase,
    guidance,
    is_strict_design_intent,
)


def record(path, tier='unmatched', **metadata):
    return {'path': '.harness/skills/' + path, 'tier': tier, 'metadata': metadata,
            'score': 3, 'content_ref': 'sha256:' + 'a' * 64, 'file': '/artifacts/a.txt'}


def test_phase_detection_and_strict_design_are_distinct():
    assert detect_phase('how do I inspect an error') == {'plan', 'review', 'debug'}
    assert not is_strict_design_intent('how do I rename a file')
    assert is_strict_design_intent('refactor the parser')
    assert not detect_phase('showcase feedback')
    assert detect_phase('설계하고 구현 후 검토하자') == {'plan', 'implement', 'review'}


def test_guidance_uses_pipeline_phase_and_available_tool_actions():
    result = guidance('파일 검색하고 파일을 읽어줘', [], ['review', 'unknown'])
    assert 'review' in result['phases']
    assert len(result['sensor_reminders']) == 1
    assert any('rg --files' in hint for hint in result['tool_hints'])
    assert any('bounded line ranges' in hint for hint in result['tool_hints'])
    assert all('Glob' not in hint for hint in result['tool_hints'])
    assert result['advisory_only'] is True


def test_requires_are_one_hop_deduped_and_cannot_bypass_eligibility():
    records = [record('python/a.md', 'full', requires='helper missing ../escape'),
               record('python/b.md', 'pointer', requires='helper'),
               record('python/helper.md', requires='transitive', keywords='one two three four'),
               record('python/transitive.md')]
    result = cross_references(records)
    assert [r['path'] for r in result['resolved']] == ['.harness/skills/python/helper.md']
    assert result['resolved'][0]['keywords'] == ['one', 'two', 'three']
    assert [r['reason'] for r in result['unresolved']] == ['unavailable', 'invalid']
    records[2]['tier'] = 'full'
    assert all(r['path'] != records[2]['path'] for r in cross_references(records)['resolved'])


def test_duplicate_skill_names_are_resolved_in_origin_scope_or_reported():
    records = [record('python/a.md', 'full', requires='helper'),
               record('python/first/helper.md'), record('python/second/helper.md'),
               record('java/helper.md')]
    result = cross_references(records)
    assert not result['resolved']
    assert result['unresolved'][0]['reason'] == 'ambiguous'
    assert len(result['unresolved'][0]['candidates']) == 2
    records.append(record('python/helper.md'))
    assert cross_references(records)['resolved'][0]['path'] == records[-1]['path']


def test_packaged_skill_alias_and_exact_path_reference():
    records = [record('_common/a.md', 'full', requires='typed python/pkg/SKILL.md'),
               record('python/pkg/SKILL.md', name='typed')]
    assert len(cross_references(records)['resolved']) == 1


def test_guidance_reference_tail_is_external_and_provenance_survives(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    names = [f'helper{i}' for i in range(20)]
    records = [record('python/a.md', 'full', requires=' '.join(names))]
    records.extend(record('python/' + name + '.md') for name in names)
    item, summary = guidance_context(artifacts, 'a' * 40, 'implement and review', records,
                                     {'recommendations': []})
    inline = json.loads(item.body)
    assert len(item.body.encode('utf-8')) <= 6000
    assert len(inline['cross_references']) <= 8
    assert inline['external_references'] == 20 - len(inline['cross_references'])
    assert summary['resolved'] == 20
    assert len(artifacts.document(summary['ref'])['cross_references']['resolved']) == 20
