"""Pinned Baldrix M22 numeric replay; diagnostic, not native policy approval."""
import math
from dataclasses import asdict, dataclass

from codex_harness.domain.model import require
from codex_harness.domain.skill_audit import timestamp

REFERENCE_BODY_BUDGET = 4000
REFERENCE_TOP_K = 3
REFERENCE_MODEL = 'baldrix-b9586c59-total-score-raw-body'


def top_entries(event):
    top = event.get('top') if isinstance(event, dict) else None
    return [entry for entry in top if isinstance(entry, dict)] if isinstance(top, list) else []


def finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def split_by_holdout(events, boundary):
    cutoff = timestamp(boundary)
    require(cutoff is not None, 'Invalid holdout boundary')
    trailing, holdout = [], []
    for event in events:
        when = timestamp(event.get('at')) if isinstance(event, dict) else None
        (holdout if when is not None and when >= cutoff else trailing).append(event)
    return trailing, holdout


def full_body_admit_precision(events, threshold):
    require(finite_number(threshold), 'Invalid replay threshold')
    scores = [entry['score'] for event in events for entry in top_entries(event)
              if finite_number(entry.get('score')) and entry['score'] >= threshold]
    return sum(score > threshold for score in scores) / len(scores) if scores else 1.0


def admitted_entries(events, threshold):
    """Entries the threshold would admit: the denominator a precision of 1.0 must not hide."""
    return sum(1 for event in events for entry in top_entries(event)
               if finite_number(entry.get('score')) and entry['score'] >= threshold)


def non_truncation_rate(events, threshold):
    require(finite_number(threshold), 'Invalid replay threshold')
    usable = truncated = 0
    for event in events:
        sized = [(entry['score'], entry['body_chars']) for entry in top_entries(event)
                 if finite_number(entry.get('score')) and isinstance(entry.get('body_chars'), int)
                 and not isinstance(entry['body_chars'], bool) and entry['body_chars'] >= 0]
        if not sized:
            continue
        usable += 1
        chosen = sorted((entry for entry in sized if entry[0] >= threshold),
                        key=lambda entry: -entry[0])[:REFERENCE_TOP_K]
        truncated += sum(size for _, size in chosen) > REFERENCE_BODY_BUDGET
    return 1 - truncated / usable if usable else math.nan


@dataclass(frozen=True)
class ThresholdGateResult:
    accept: bool
    target_delta_holdout: float | None
    guard_delta: float | None
    reason: str


def evaluate_threshold_change(*, events, old_value, proposed_value, holdout_boundary,
                              metric_fn=full_body_admit_precision, guard_fn=non_truncation_rate,
                              min_corpus=10):
    def reject(reason):
        return ThresholdGateResult(False, None, None, reason)

    if not isinstance(min_corpus, int) or isinstance(min_corpus, bool) or min_corpus <= 0:
        return reject('invalid_min_corpus')
    if not finite_number(old_value) or not finite_number(proposed_value):
        return reject('invalid_threshold')
    if metric_fn is None or guard_fn is None:
        return reject('unresolved_metric_fn')
    if not isinstance(events, list) or len(events) < min_corpus:
        return reject('corpus_too_small')
    try:
        trailing, holdout = split_by_holdout(events, holdout_boundary)
    except Exception as exc:
        return reject('split_error:' + type(exc).__name__)
    if len(trailing) < min_corpus or len(holdout) < min_corpus:
        return reject('insufficient_holdout')
    try:
        t_new, t_old = float(metric_fn(holdout, proposed_value)), float(metric_fn(holdout, old_value))
        g_new, g_old = float(guard_fn(events, proposed_value)), float(guard_fn(events, old_value))
    except Exception as exc:
        return reject('replay_error:' + type(exc).__name__)
    if not all(math.isfinite(value) for value in (t_new, t_old, g_new, g_old)):
        return reject('non_finite_metric')
    if admitted_entries(holdout, proposed_value) == 0 or admitted_entries(trailing, proposed_value) == 0:
        # INV-THRESHOLD-APPROVAL-001: excluding every match scores a vacuous precision, never an improvement.
        return reject('empty_admission')
    target, guard = t_new - t_old, g_new - g_old
    accepted = target > 0 and guard >= 0
    reason = ('accept: target improves on held-out, guard not regressed' if accepted else
              'no-stage: target did not improve on held-out window' if target <= 0 else
              'no-stage: guard regressed (budget pressure increased)')
    return ThresholdGateResult(accepted, target, guard, reason)


def replay_report(events, **options):
    result = evaluate_threshold_change(events=events, **options)
    entries = [entry for event in events for entry in top_entries(event)]
    sized = sum(isinstance(entry.get('body_chars'), int) and not isinstance(entry['body_chars'], bool)
                and entry['body_chars'] >= 0 for entry in entries)
    usable_events = partially_sized_events = 0
    for event in events:
        scored = [entry for entry in top_entries(event) if finite_number(entry.get('score'))]
        usable = sum(isinstance(entry.get('body_chars'), int)
                     and not isinstance(entry['body_chars'], bool) and entry['body_chars'] >= 0
                     for entry in scored)
        usable_events += usable > 0
        partially_sized_events += 0 < usable < len(scored)
    partitions = None
    if timestamp(options.get('holdout_boundary')) is not None:
        trailing, holdout = split_by_holdout(events, options['holdout_boundary'])
        partitions = {}
        for name, rows in [('trailing', trailing), ('holdout', holdout)]:
            counts = {'events': len(rows)}
            for label, value in [('current', options['old_value']), ('proposed', options['proposed_value'])]:
                eligible = [[entry for entry in top_entries(event)
                             if finite_number(entry.get('score')) and finite_number(value)
                             and entry['score'] >= value] for event in rows]
                counts[label + '_admitted_entries'] = sum(map(len, eligible))
                counts[label + '_admitted_events'] = sum(bool(entries) for entries in eligible)
            partitions[name] = counts
    return {'reference_model': REFERENCE_MODEL, 'gate': asdict(result),
            'observations': len(events), 'entries': len(entries), 'sized_entries': sized,
            'missing_or_invalid_sizes': len(entries) - sized,
            'guard_usable_events': usable_events,
            'guard_skipped_events': len(events) - usable_events,
            'guard_partially_sized_events': partially_sized_events,
            'partitions': partitions,
            'unknown_timestamps': sum(timestamp(event.get('at') if isinstance(event, dict) else None)
                                      is None for event in events),
            'advisory_only': True, 'policy_changed': False,
            'limitations': ['Total scores, not native base-score admission.',
                'The target is a score-margin statistic, not admission quality or task success.',
                'Target deltas use holdout; guard deltas use the complete corpus, including training.',
                'Raw character sum, not per-body reduction or the final UTF-8 context compiler.',
                'Only recorded top matches are available; lowering thresholds can undercount admissions and pressure.',
                'The pinned precision scores an empty admission as 1.0; the gate rejects such a value as empty_admission.',
                'Reference guard skips unsized entries; acceptance is not a coverage guarantee.']}
