"""Baldrix b9586c59 thin-skill predicate, scoped to immutable skill identities."""
from statistics import median

THIN_SCORE_CEILING = 2
MIN_SAMPLES = 3
FP_THIN_RATE = 0.8
MAX_EVENTS = 4000
TOP_MATCHES = 5


def is_candidate(count, thin_rate, middle, min_samples=MIN_SAMPLES):
    return count >= min_samples and thin_rate >= FP_THIN_RATE and middle <= THIN_SCORE_CEILING


def valid_record(record):
    return (isinstance(record, dict) and all(isinstance(record.get(k), str) and record[k]
            for k in ('path', 'content_ref')) and isinstance(record.get('score'), int)
            and not isinstance(record['score'], bool) and record['score'] >= 0)


def assess_history(events, current, exclude=None):
    identities = {(record['path'], record['content_ref']) for record in current}
    scores = {}
    for event in events[-MAX_EVENTS:]:
        if not isinstance(event, dict) or (exclude is not None and event.get('id') == exclude):
            continue
        entries = event.get('top')
        if not isinstance(entries, list):
            continue
        for record in entries:
            if not valid_record(record):
                continue
            identity = (record['path'], record['content_ref'])
            if identity in identities:
                scores.setdefault(identity, []).append(record['score'])
    result = []
    for (path, content_ref), values in sorted(scores.items()):
        thin_rate = sum(score <= THIN_SCORE_CEILING for score in values) / len(values)
        middle = median(values)
        result.append({'path': path, 'content_ref': content_ref, 'count': len(values),
                       'median': middle, 'thin_rate': thin_rate,
                       'candidate': is_candidate(len(values), thin_rate, middle)})
    return result
