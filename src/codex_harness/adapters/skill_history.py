"""Bind routed skill observations and atomic body advisories to Executor context."""
import re
from dataclasses import replace

from codex_harness.application.skill_history import SkillHistory
from codex_harness.domain.model import canonical, digest
from codex_harness.domain.skill_history import TOP_MATCHES


def project_identity(selection, git):
    """Prefer Git-owned UUID; configured GitHub slug supports existing profiles."""
    if selection.get('project_id'):
        return 'uuid:' + selection['project_id']
    remote = getattr(git, 'remote', None)
    if isinstance(remote, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]*', remote):
        return 'github:' + remote.lower().removesuffix('.git')
    return None


def prepare_history(store, artifacts, project, agent, task, objective, selection, items):
    draft = dict(selection)
    try:
        prepared = _prepare_history(store, artifacts, project, agent, task, objective, draft, items)
    except Exception as exc:
        # INV-SKILL-HISTORY-001: optional history cannot abort authoritative work.
        # Only the class is exposed; backend exceptions can contain credentials.
        selection['history'] = {'status': 'unavailable', 'reason': type(exc).__name__}
        return items, None
    selection.update(draft)
    return prepared


def record_history(observation, context_ref, guard=None):
    history, project, event = observation
    ownership_failed = False
    ownership_checked = False

    def owned(tx):
        nonlocal ownership_failed, ownership_checked
        try:
            if guard:
                guard(tx)
            ownership_checked = True
        except Exception:
            ownership_failed = True
            raise

    try:
        recorded = history.record(project, {**event, 'context_ref': context_ref}, owned)
        return {'status': 'recorded' if recorded else 'duplicate'}
    except Exception as exc:
        # Lease authority is never advisory: stale ownership must stop execution.
        if ownership_failed or (guard is not None and not ownership_checked):
            raise
        return {'status': 'unavailable', 'reason': type(exc).__name__}


def _prepare_history(store, artifacts, project, agent, task, objective, selection, items):
    if not selection.get('manifest_ref'):
        return items, None
    if not project:
        selection['history'] = {'status': 'unavailable', 'reason': 'project_identity_required'}
        return items, None
    manifest = artifacts.document(selection['manifest_ref'])
    records = [r for r in manifest['skills'] if 'score' in r and r['tier'] != 'unmatched']
    if not records:
        return items, None
    project_key = digest(project)
    event_id = digest([agent, task, objective, selection['manifest_ref']])
    history = SkillHistory(store)
    assessment = history.snapshot(project_key, records, event_id)
    receipt = artifacts.put(canonical({'project': project_key, 'assessment': assessment,
                                      'current_event_excluded': event_id}), 'skill-history-assessment')
    selection['history'] = {'ref': receipt['ref'],
                           'file': str(artifacts.root / (receipt['ref'][7:] + '.txt'))}
    flagged = {(r['path'], r['content_ref']) for r in assessment if r['candidate']}
    full = {r['path'] for r in records if r['tier'] == 'full'}
    annotated = []
    for item in items:
        path = item.id.removeprefix('project-skill:')
        if path in full and (path, item.source_ref) in flagged:
            # INV-SKILL-HISTORY-001: body and advice are admitted/omitted atomically.
            item = replace(item, body=canonical({'skill_body': item.body,
                'historical_advisory': 'This skill often matched on weak signals. Review its guidance '
                    'critically; repeated false positives warrant narrowing its trigger metadata.',
                'history_ref': receipt['ref']}))
        annotated.append(item)
    top = sorted(records, key=lambda r: (-r['score'], r['path']))[:TOP_MATCHES]
    # FA-012: the observation carries the delivered tier and rendered body hash next to the score,
    # so audits can separate raw match, rank and body arrival instead of inferring delivery from top5.
    event = {'id': event_id, 'manifest_ref': selection['manifest_ref'],
             'top': [{**{key: r[key] for key in ('path', 'content_ref', 'score', 'base_score', 'body_chars',
                                                 'tier', 'rendered_hash') if key in r},
                      'dimensions': r.get('dimensions', [])}
                     for r in top], 'kind': 'compiled_skill_selection'}
    return annotated, (history, project_key, event)
