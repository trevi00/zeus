"""Transactional cursor and immutable-source binding for legacy log segments."""
import hashlib

from codex_harness.domain.model import digest, require, utcnow
from codex_harness.domain.skill_audit import audit_history
from codex_harness.domain.skill_history import MAX_EVENTS
from codex_harness.domain.skill_import import (
    IMPORT_VERSION,
    MAX_INPUT_BYTES,
    project_jsonl,
    source_document,
    validate_source,
)


class SkillImport:
    def __init__(self, store):
        self.store = store

    def ingest(self, project, source, data, source_ref):
        validate_source(source)
        require(isinstance(data, bytes) and len(data) <= MAX_INPUT_BYTES, 'Import exceeds byte limit')
        require(source_ref == 'sha256:' + digest(source_document(data, source)), 'Source artifact does not bind input')
        key = digest([project, source])
        with self.store.transaction() as tx:
            old = tx.get('legacy_skill_imports', key)
            start = old['consumed_bytes'] if old else 0
            if old:
                require(old['version'] == IMPORT_VERSION,
                        'Import parser version changed; preserve this archive and use a new source ID for re-import')
                require(len(data) >= start and hashlib.sha256(data[:start]).hexdigest() == old['prefix_sha256'],
                        'Previously imported prefix changed; use a different ID for a new segment')
            batch = project_jsonl(data, source, start=start, line_offset=old['counts']['lines'] if old else 0)
            require(old is not None or batch['counts']['events'] > 0 or batch['counts']['invalid_lines'] == 0,
                    'No valid skill records found; verify the input log category before importing')
            counts = {k: v + (old['counts'][k] if old else 0) for k, v in batch['counts'].items()}
            state = {'version': IMPORT_VERSION, 'project_key': project, 'source_id': source,
                     'created_at': old.get('created_at', old['at']) if old else utcnow(),
                     'consumed_bytes': batch['consumed_bytes'], 'prefix_sha256': batch['prefix_sha256'],
                     'counts': counts, 'events': ((old['events'] if old else []) + batch['events'])[-MAX_EVENTS:],
                     'source_ref': source_ref, 'at': utcnow()}
            changed = old is None or batch['consumed_bytes'] > start
            if changed:
                tx.put('legacy_skill_imports', key, state)
            return {'project_key': project, 'source_id': source, 'changed': changed,
                    'added': batch['counts'], 'total': counts, 'retained_events': len(state['events']),
                    'pending_bytes': batch['pending_bytes'], 'issues': batch['issues'],
                    'source_ref': state['source_ref'] if changed else old['source_ref'],
                    'input_ref': source_ref, 'consumed_bytes': batch['consumed_bytes']}

    def audit(self, project, source, **options):
        validate_source(source)
        with self.store.transaction() as tx:
            state = tx.get('legacy_skill_imports', digest([project, source]))
        return {'project_key': project, 'legacy_source': source,
                'source_ref': state['source_ref'] if state else None,
                'identity_status': 'historical_skill_version_unknown',
                **audit_history(state['events'] if state else [], **options)}
