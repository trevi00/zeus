"""Bind routed skill observations and atomic body advisories to Executor context."""
import hashlib
import re
from dataclasses import replace

from codex_harness.application.skill_history import SkillHistory
from codex_harness.domain.model import canonical, digest
from codex_harness.domain.skill_audit import EVIDENCE_STAGE
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


def finalize_delivery(observation, packet):
    """Rewrite the observation from the sealed packet: a skill the budget dropped is `omitted`, not
    `full`, and an admitted body is hashed as it actually appears in the context (review, PR #45).

    Selection tier (manifest) and final inclusion are different evidence stages; this records the
    latter and names the stage, which is still before provider submission and any model behavior.
    """
    if observation is None:
        return None
    history, project, event = observation
    admitted = {item['id']: item for item in packet.evidence if item['id'].startswith('project-skill:')}
    omitted = {entry['id'] for entry in packet.omitted if entry['id'].startswith('project-skill:')}
    top = []
    for record in event['top']:
        key = 'project-skill:' + record['path']
        if key in admitted:
            top.append({**record, 'context_body_hash': hashlib.sha256(
                admitted[key]['body'].encode('utf-8')).hexdigest()})
        elif key in omitted or record.get('tier') == 'full':
            top.append({**{k: v for k, v in record.items() if k != 'rendered_hash'}, 'tier': 'omitted'})
        else:
            top.append(record)  # pointer tiers never carried a body into the packet
    delivery = {'stage': EVIDENCE_STAGE, 'admitted': sorted(k.removeprefix('project-skill:') for k in admitted),
                'omitted': sorted(k.removeprefix('project-skill:') for k in omitted)}
    return history, project, {**event, 'top': top, 'delivery': delivery}


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
                     for r in top], 'kind': 'compiled_skill_selection', 'evidence_stage': 'selected_not_compiled'}
    return annotated, (history, project_key, event)
