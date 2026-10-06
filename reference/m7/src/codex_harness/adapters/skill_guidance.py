"""Bounded guidance rendering with complete immutable cross-reference evidence."""
from codex_harness.domain.model import ContextItem, canonical
from codex_harness.domain.skill_guidance import guidance


def guidance_context(artifacts, revision, objective, records, pipeline):
    phases = [r.get('phase', '') for r in pipeline['recommendations']]
    result = guidance(objective, records, phases)
    stored = artifacts.put(canonical(result), 'project-skill-guidance')
    handle = {'ref': stored['ref'], 'file': str(artifacts.root / (stored['ref'][7:] + '.txt'))}
    references = result['cross_references']['resolved']
    compact = {key: value for key, value in result.items() if key != 'cross_references'}
    compact.update(details=handle, cross_references=references[:8],
                   unresolved_count=len(result['cross_references']['unresolved']),
                   external_references=len(references) - min(8, len(references)))
    # INV-CONTEXT-001: large reference names must not turn advisory context unbounded.
    while len(canonical(compact).encode('utf-8')) > 6000 and compact['cross_references']:
        compact['cross_references'].pop()
        compact['external_references'] += 1
    item = ContextItem('project-guidance:' + stored['ref'], canonical(compact),
                       stored['ref'], revision, 13)
    return item, {**handle, 'resolved': len(references),
                  'unresolved': compact['unresolved_count'], 'advisory_only': True}
