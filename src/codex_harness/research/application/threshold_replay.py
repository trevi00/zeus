"""Read a stable runtime corpus for diagnostic threshold replay.

Layer: application
Context: research
Owns: ThresholdReplay.evaluate, the read of one stable runtime corpus (native history or one imported legacy segment) for the diagnostic threshold replay; it writes nothing
Does not own: the replay rules (research.domain.threshold_replay), the source-ID rule (context's `validate_source`, injected as `validate_source` by composition), the skill history and legacy import records it reads (context), the CLI (S10)
Entry points: ThresholdReplay, MAX_EVENTS
Contracts: INV-NATIVE-REPLAY-001

Moved from M7 `application/threshold_replay.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §13 V18, A/evidence/rebuild/s8/thresholds-a-move/transcribe.py): R-t0 (`MAX_EVENTS` is a V9 local constant, equal to context's), R-t1 (`validate_source` is an injected keyword-only constructor parameter, required only on the `legacy_source` path), R-t3 (each name from the target home of the module that defines it); every other statement is M7's. The first paragraph is M7's module docstring.
"""
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest
from codex_harness.research.domain.threshold_replay import replay_report

# V18 R-t0: a V9 local published-language constant (context.domain.skills.history); a move test pins equality with the owner.
MAX_EVENTS = 4000


class ThresholdReplay:
    def __init__(self, store, *, validate_source=None):
        self.store = store
        # V18 R-t1: context's `validate_source`, wired by composition
        self.validate_source = validate_source

    def evaluate(self, project, *, legacy_source=None, **options):
        if legacy_source is not None:
            require(self.validate_source is not None, 'validate_source is not wired')
            self.validate_source(legacy_source)
        bucket = 'legacy_skill_imports' if legacy_source is not None else 'skill_history'
        key = digest([project, legacy_source]) if legacy_source is not None else project
        with self.store.transaction() as tx:
            state = tx.get(bucket, key) or {'events': []}
        events = state['events'][-MAX_EVENTS:]
        return {'project_key': project, 'legacy_source': legacy_source, 'options': options,
                'source_ref': state.get('source_ref'), 'corpus_hash': digest(events),
                'events': events, 'report': replay_report(events, **options)}
