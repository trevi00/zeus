"""Passive Baldrix M7 score/dimension audit, with version-scoped identities."""
import math
import re
from collections import Counter
from datetime import datetime, timezone
from statistics import median

from codex_harness.domain.model import require
from codex_harness.domain.skill_history import (
    MAX_EVENTS,
    MIN_SAMPLES,
    THIN_SCORE_CEILING,
    is_candidate,
    valid_record,
)

DIMENSIONS = ('intent', 'path', 'kw', 'pat')
# FA-012: what an observation can prove, stated per target instead of one blended "precision".
DELIVERY_TIERS = ('full', 'pointer', 'external_pointer', 'unmatched', 'legacy')
MEASUREMENT_TARGETS = {
    'raw_match': 'top entries exist: the skill matched or was boosted at compile time',
    'rank': 'score order among matched candidates for one objective',
    'body_arrival': 'delivered tier per observation: full body, pointer, external pointer or unknown',
    'behavior': 'not measured by telemetry; requires actual model output and human acceptance'}


def duration_seconds(value):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([smhd])', value.lower())
    require(match is not None, 'Invalid duration; use a positive number followed by s/m/h/d')
    result = float(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]]
    require(math.isfinite(result) and result > 0, 'Duration must be finite and positive')
    return result


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def audit_history(events, *, min_samples=MIN_SAMPLES, cutoff=None):
    require(isinstance(min_samples, int) and not isinstance(min_samples, bool) and min_samples > 0,
            'Minimum samples must be a positive integer')
    require(cutoff is None or (isinstance(cutoff, (int, float)) and not isinstance(cutoff, bool)
                              and math.isfinite(cutoff)), 'Invalid time cutoff')
    scores, base_scores, boosted, dimensions, overall = {}, {}, Counter(), {}, Counter()
    delivery, rank_first = {}, Counter()
    invocations = unknown_dates = invalid_entries = 0
    for event in events[-MAX_EVENTS:]:
        if not isinstance(event, dict):
            invalid_entries += 1
            continue
        when = timestamp(event.get('at'))
        if cutoff is not None and when is not None and when < cutoff:
            continue
        invocations += 1
        unknown_dates += when is None
        entries = event.get('top') or []
        if not isinstance(entries, list):
            invalid_entries += 1
            continue
        valid = [entry for entry in entries if valid_record(entry)]
        invalid_entries += len(entries) - len(valid)
        if valid:
            best = max(entry['score'] for entry in valid)
            for entry in valid:
                if entry['score'] == best:
                    rank_first[(entry['path'], entry['content_ref'])] += 1
        for entry in valid:
            identity = (entry['path'], entry['content_ref'])
            scores.setdefault(identity, []).append(entry['score'])
            tier = entry.get('tier')
            delivery.setdefault(identity, Counter())[tier if tier in DELIVERY_TIERS else 'unknown'] += 1
            base = entry.get('base_score')
            if isinstance(base, int) and not isinstance(base, bool) and 0 <= base <= entry['score']:
                base_scores.setdefault(identity, []).append(base)
                boosted[identity] += base < entry['score']
            counts = dimensions.setdefault(identity, Counter())
            raw_dims = entry.get('dimensions') or []
            for dim in raw_dims if isinstance(raw_dims, list) else []:
                category = dim.split(':', 1)[0] if isinstance(dim, str) and ':' in dim else 'unknown'
                category = category if category in DIMENSIONS else 'unknown'
                counts[category] += 1
                overall[category] += 1
    skills, candidates = [], []
    for identity, values in scores.items():
        count, middle = len(values), median(values)
        rate = sum(score <= THIN_SCORE_CEILING for score in values) / count
        dims = dimensions[identity]
        dominant = dims.most_common(1)[0][0] if dims else None
        record = {'path': identity[0], 'content_ref': identity[1], 'count': count,
                  'score_min': min(values), 'score_median': middle, 'score_max': max(values),
                  'thin_rate': round(rate, 3), 'dominant_dim': dominant, 'dim_breakdown': dict(dims)}
        skills.append(record)
        base = base_scores.get(identity, [])
        record['base_score_profile'] = ({'count': len(base), 'min': min(base),
            'median': median(base), 'max': max(base), 'boosted_count': boosted[identity]} if base else None)
        record['missing_base_scores'] = count - len(base)
        # Counts per target, never a blended ratio: matched n times, ranked first m times,
        # full body delivered k times (unknown = observations recorded before tiers existed).
        record['rank_first_count'] = rank_first[identity]
        record['delivery'] = {tier: delivery[identity].get(tier, 0) for tier in (*DELIVERY_TIERS, 'unknown')}
        if is_candidate(count, rate, middle, min_samples):
            candidates.append({**record, 'reason': f'fires {count}x but {round(rate * 100)}% are thin '
                f'(score<={THIN_SCORE_CEILING}, never full-body); median {middle}. Narrow the '
                f'{dominant or "matching"} surface.'})
    def order(row):
        return -row['count'], row['path'], row['content_ref']
    return {'invocations': invocations, 'skills': sorted(skills, key=order),
            'false_positive_candidates': sorted(candidates, key=order), 'dim_weight': dict(overall),
            'unknown_timestamp_events': unknown_dates, 'invalid_entries': invalid_entries,
            'max_events': MAX_EVENTS, 'min_samples': min_samples, 'read_only': True,
            'measurement_targets': dict(MEASUREMENT_TARGETS)}
