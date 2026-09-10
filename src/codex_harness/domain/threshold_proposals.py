"""Baldrix b9586c59 M22 registry and deterministic threshold proposal calculation.

Source: scripts/lib/calibration/{threshold_registry,threshold_proposer}.py.
Pure proposals carry their current-policy basis; staging/activation are separate.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from codex_harness.domain import threshold_replay as replay
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.skill_audit import timestamp
from codex_harness.domain.threshold_replay import (
    finite_number,
    full_body_admit_precision,
    replay_report,
    split_by_holdout,
)

HOLDOUT_FRACTION = 0.30
HYSTERESIS_MARGIN = 0.02
CALCULATION_VERSION = 2


@dataclass(frozen=True)
class TunableThreshold:
    name: str
    qualified: str
    default: float
    telemetry_source: str
    target_metric: str
    guard_metric: str
    direction_safety: str
    step: float
    process_lifetime: str
    wired: bool = False


REGISTRY = {
    entry.name: entry for entry in (
        TunableThreshold('skill_match.FULL_BODY_MIN_SCORE', 'handlers.prompt.skill_match.FULL_BODY_MIN_SCORE',
            3, 'skill-match', 'full_body_admit_precision', 'non_truncation_rate', 'either', 1, 'short_hook', True),
        TunableThreshold('skill_candidate_detector._THRESHOLD', 'lib.skill_candidate_detector._THRESHOLD',
            10, 'skill-candidate', 'candidate_signal_rate', 'noise_suppression_rate', 'raise_safe', 1, 'short_hook'),
        TunableThreshold('handoff_resume.STALE_DAYS_THRESHOLD', 'handlers.prompt.handoff_resume.STALE_DAYS_THRESHOLD',
            7, 'handoff-resume', 'resume_relevance_rate', 'stale_suppression_rate', 'either', 1, 'short_hook'),
        TunableThreshold('skill_telemetry_audit.FP_THIN_RATE', 'cli.skill_telemetry_audit.FP_THIN_RATE',
            .8, 'skill-match', 'fp_flag_precision', 'fp_flag_recall', 'either', .05, 'long_lived'),
        TunableThreshold('ratio_tracker.WARN_THRESHOLD', 'lib.ratio_tracker.WARN_THRESHOLD',
            3., 'read-edit-ratio', 'warn_precision', 'warn_recall', 'raise_safe', .5, 'short_hook'),
    )
}
LOCKED_DENY = frozenset({
    'lib.repeat_error_tracker.STRIKE_THRESHOLD', 'lib.repeat_error_tracker.ESCALATED_THRESHOLD',
    'lib.strike_dispatcher.RESEARCH_DISPATCH_THRESHOLD', 'lib.strike_dispatcher.PER_FINGERPRINT_DISPATCH_LIMIT',
    'lib.wonder.WONDER_STRIKE_THRESHOLD', 'lib.wonder.WONDER_DEPTH_CAP',
    'lib.graduation.GRADUATION_THRESHOLD', 'lib.evaluator_dispatcher.PER_PHASE_EVAL_LIMIT',
    'lib.l2_promoter._GROUP_THRESHOLD', 'lib.phase_tree.PROMOTION_STEP_THRESHOLD',
    'lib.phase_tree.PROMOTION_SUB_STEP_THRESHOLD', 'engine.debate.GENERATION_HARD_CAP',
})


def validate_registry():
    # INV-THRESHOLD-PROPOSAL-001: enforce at runtime, including python -O.
    for name, entry in REGISTRY.items():
        require(name == entry.name, 'Threshold registry name mismatch')
        require(entry.qualified not in LOCKED_DENY and name not in LOCKED_DENY,
                'Threshold registry overlaps locked invariants')
        require(entry.direction_safety in {'raise_safe', 'lower_safe', 'either'}, 'Invalid safe direction')
        require(finite_number(entry.step) and entry.step > 0 and finite_number(entry.default),
                'Invalid threshold registry number')
        if entry.wired:
            require(entry.target_metric == 'full_body_admit_precision'
                    and entry.guard_metric == 'non_truncation_rate', 'Unresolved threshold metrics')


def holdout_boundary(events):
    dates = sorted(when for event in events if isinstance(event, dict)
                   and (when := timestamp(event.get('at'))) is not None)
    if len(dates) < 2:
        return None
    index = min(max(int(len(dates) * (1 - HOLDOUT_FRACTION)), 1), len(dates) - 1)
    return datetime.fromtimestamp(dates[index], timezone.utc).isoformat()


def unique_events(events):
    """Deduplicate a corpus by observation id (or exact content when unidentified) and describe
    the denominator: audit rows, re-collected duplicates and unscored events never count as
    additional successful executions."""
    seen, unique = set(), []
    counts = {'events': 0, 'invalid': 0, 'unidentified': 0, 'duplicates': 0, 'unscored': 0}
    for event in events:
        counts['events'] += 1
        if not isinstance(event, dict):
            counts['invalid'] += 1
            continue
        identity = event.get('id')
        if not isinstance(identity, str) or not identity:
            counts['unidentified'] += 1
            try:
                identity = 'content:' + digest(event)
            except (TypeError, ValueError, OverflowError, RecursionError) as exc:
                raise ContractError('Invalid threshold corpus encoding') from exc
        if identity in seen:
            counts['duplicates'] += 1
            continue
        seen.add(identity)
        if not any(finite_number(entry.get('score')) for entry in replay.top_entries(event)):
            counts['unscored'] += 1
        unique.append(event)
    counts['unique'] = len(unique)
    return unique, counts


def evaluation_scope(events, entry, policy_revision):
    dates = sorted(when for event in events if (when := timestamp(event.get('at'))) is not None)
    return {'telemetry_source': entry.telemetry_source, 'policy_revision': policy_revision,
            'first_at': datetime.fromtimestamp(dates[0], timezone.utc).isoformat() if dates else None,
            'last_at': datetime.fromtimestamp(dates[-1], timezone.utc).isoformat() if dates else None,
            'unknown_timestamps': len(events) - len(dates)}


def direction_allowed(entry, current, proposed):
    # Compare against effective current policy, not a possibly obsolete default.
    return (entry.direction_safety == 'either'
            or entry.direction_safety == 'raise_safe' and proposed >= current
            or entry.direction_safety == 'lower_safe' and proposed <= current)


def propose_threshold_changes(*, events_by_source, current_values, policy_revision, min_sample=10):
    validate_registry()
    require(isinstance(policy_revision, str) and len(policy_revision) in {40, 64}
            and all(c in '0123456789abcdef' for c in policy_revision), 'Invalid policy revision')
    require(isinstance(min_sample, int) and not isinstance(min_sample, bool) and min_sample > 0,
            'Invalid minimum samples')
    require(isinstance(current_values, dict) and isinstance(events_by_source, dict), 'Invalid proposal input')
    require(set(current_values) <= set(REGISTRY), 'Unregistered threshold policy')
    require(all(finite_number(value) for value in current_values.values()), 'Invalid current threshold')
    proposals = []
    for name, entry in sorted(REGISTRY.items()):
        if not entry.wired:
            continue
        require(name in current_values, 'Missing effective threshold value')
        collected = events_by_source.get(entry.telemetry_source, [])
        require(isinstance(collected, list), 'Invalid threshold corpus')
        try:
            corpus_hash = digest(collected)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ContractError('Invalid threshold corpus encoding') from exc
        # The denominator is unique executions, not collected rows.
        events, denominator = unique_events(collected)
        if len(events) < min_sample:
            continue
        boundary = holdout_boundary(events)
        if boundary is None:
            continue
        trailing, held = split_by_holdout(events, boundary)
        if len(trailing) < min_sample:
            continue
        current = current_values[name]
        target = full_body_admit_precision(trailing, current)
        accepted, rejected, alternatives = [], [], []
        for value in (current + entry.step, current - entry.step):
            if not finite_number(value) or not direction_allowed(entry, current, value):
                continue
            proposed_target = full_body_admit_precision(trailing, value)
            candidate = {'value': value, 'trailing_target': proposed_target,
                         'trailing_gain': proposed_target - target, 'report': None,
                         'passed_hysteresis': proposed_target - target > HYSTERESIS_MARGIN}
            alternatives.append(candidate)
            if not candidate['passed_hysteresis']:
                continue
            report = replay_report(events, old_value=current, proposed_value=value,
                holdout_boundary=boundary, min_corpus=min_sample)
            candidate['report'] = report
            (accepted if report['gate']['accept'] else rejected).append(candidate)
        if not accepted and not rejected:
            continue
        chosen = (sorted(accepted, key=lambda c: -c['report']['gate']['target_delta_holdout'])[0]
                  if accepted else rejected[-1])
        basis = {'name': name, 'policy_revision': policy_revision, 'current': current,
                 'suggested': chosen['value'] if accepted else None,
                 'evaluated_value': chosen['value'], 'corpus_hash': corpus_hash,
                 'unique_corpus_hash': digest(events),
                 'registry_hash': digest(asdict(entry)), 'min_sample': min_sample,
                 'calculation': {'version': CALCULATION_VERSION,
                     'reference_model': replay.REFERENCE_MODEL,
                     'body_budget': replay.REFERENCE_BODY_BUDGET, 'top_k': replay.REFERENCE_TOP_K,
                     'holdout_fraction': HOLDOUT_FRACTION, 'hysteresis_margin': HYSTERESIS_MARGIN},
                 'holdout_boundary': boundary}
        proposals.append({**basis, 'id': digest(basis), 'reference_accepted': bool(accepted),
            'advisory_only': True, 'activation_ready': False,
            'sample_size': len(events), 'trailing_size': len(trailing), 'holdout_size': len(held),
            'denominator': denominator, 'evaluation_scope': evaluation_scope(events, entry, policy_revision),
            'trailing_target_current': target, 'trailing_target_proposed': chosen['trailing_target'],
            'report': chosen['report'], 'alternatives': alternatives,
            'selection_rule': 'highest_holdout_gain_raise_first_ties' if accepted else 'last_rejected_candidate'})
    return proposals
