"""Read a stable runtime corpus for diagnostic threshold replay."""
from codex_harness.domain.model import digest
from codex_harness.domain.skill_history import MAX_EVENTS
from codex_harness.domain.skill_import import validate_source
from codex_harness.domain.threshold_replay import replay_report


class ThresholdReplay:
    def __init__(self, store):
        self.store = store

    def evaluate(self, project, *, legacy_source=None, **options):
        if legacy_source is not None:
            validate_source(legacy_source)
        bucket = 'legacy_skill_imports' if legacy_source is not None else 'skill_history'
        key = digest([project, legacy_source]) if legacy_source is not None else project
        with self.store.transaction() as tx:
            state = tx.get(bucket, key) or {'events': []}
        events = state['events'][-MAX_EVENTS:]
        return {'project_key': project, 'legacy_source': legacy_source, 'options': options,
                'source_ref': state.get('source_ref'), 'corpus_hash': digest(events),
                'events': events, 'report': replay_report(events, **options)}
