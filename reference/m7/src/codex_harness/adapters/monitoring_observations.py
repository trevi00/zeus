"""Read-only observation projection for the monitor (INV-OBSERVATION-001, observatory-001).

Reads the stored observation buckets through the monitor's read-only transaction and the local
spool directory through its read methods only. Nothing here collects, prunes, acknowledges,
reclaims or probes a writer lock: the projection is a bounded sample of what is stored, labelled
with how much was scanned and whether the sample was cut, never a lifetime total.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.application.observations import (
    ALERT_BUCKET,
    AUDIT_BUCKET,
    COLLECTION_BUCKET,
    EVENT_BUCKET,
    QUARANTINE_BUCKET,
    TERMINATION_BUCKET,
)
from codex_harness.domain.observation import CATEGORIES, REFERENCE, SEVERITIES, redact_text

SCHEMA = 'harness-monitor-observations.v1'
BUCKET_LIMIT = 2000       # stored rows read per bucket, in store id order
PAGE = 500
ROW_LIMIT = 200           # projected event rows carried in the snapshot
HIGH_LIMIT = 50           # error/critical rows carried separately
OPERATION_LIMIT = 100
TEXT_LIMIT = 200
REFS_LIMIT = 8
SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}
CATEGORY_RANK = {'operations': 0, 'development': 1, 'general': 2}
CATEGORY_LABELS = {'general': '일반·디버깅', 'development': '개발', 'operations': '운영'}
PENDING_TERMINATION = ('pending_reconciliation', 'unconfirmed')
OPERATION_BUCKET = 'operations'


def text(value, limit=TEXT_LIMIT):
    """Redacted, bounded string at the public boundary; non-strings become None."""
    if not isinstance(value, str):
        return None
    redacted, _ = redact_text(value)
    return redacted[:limit]


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def scan_bounded(tx, bucket, limit=BUCKET_LIMIT, page=PAGE):
    """First `limit` rows of a bucket in id order; says whether more rows remain."""
    rows, after = [], ''
    while len(rows) < limit:
        size = min(page, limit - len(rows))
        batch = tx.entries(bucket, after, size)
        rows.extend(item['body'] for item in batch)
        if len(batch) < size:
            return rows, {'scanned': len(rows), 'limit': limit, 'truncated': False}
        after = batch[-1]['id']
    truncated = bool(tx.entries(bucket, after, 1))
    return rows, {'scanned': len(rows), 'limit': limit, 'truncated': truncated}


def project_event(row, record_kind):
    execution = row.get('execution') if isinstance(row.get('execution'), dict) else {}
    source = row.get('source') if isinstance(row.get('source'), dict) else {}
    severity, category = row.get('severity'), row.get('category')
    observed = parse_time(row.get('observed_at'))
    refs = [ref for ref in (row.get('evidence_refs') or []) if isinstance(ref, str) and REFERENCE.fullmatch(ref)]
    return {'event_id': text(row.get('event_id')), 'event_type': text(row.get('event_type')),
            'category': category if category in CATEGORIES else 'unknown',
            'severity': severity if severity in SEVERITIES else 'unknown',
            'outcome': text(row.get('outcome'), 40), 'reason_code': text(row.get('reason_code'), 80),
            'observed_at': row.get('observed_at') if observed else None,
            'observed_at_valid': observed is not None,
            'occurred_at': row.get('occurred_at') if parse_time(row.get('occurred_at')) else None,
            'collected_at': row.get('collected_at') if parse_time(row.get('collected_at')) else None,
            'record_kind': record_kind, 'audit_confirmed': row.get('audit_confirmed'),
            'correlation_id': text(row.get('correlation_id')),
            'execution': {'kind': text(execution.get('kind'), 20), 'role': text(execution.get('role')),
                          'task_id': text(execution.get('task_id')), 'bucket': text(execution.get('bucket'), 40),
                          'attempt': execution.get('attempt') if type(execution.get('attempt')) is int else None,
                          'generation': execution.get('generation') if type(execution.get('generation')) is int else None,
                          'process_run_id': text(execution.get('process_run_id'), 40),
                          'invocation_id': text(execution.get('invocation_id'))},
            'component': text(source.get('component'), 80),
            'evidence_refs': refs[:REFS_LIMIT], 'evidence_refs_total': len(refs)}


def sort_key(event):
    return (-SEVERITY_RANK.get(event['severity'], -1), CATEGORY_RANK.get(event['category'], 3),
            not event['observed_at_valid'], event['observed_at'] or '', event['event_id'] or '')


def merge_events(audits, collected):
    """One logical event per event_id; the collected record wins, the audit-only rest is kept."""
    merged, kinds = {}, Counter()
    for row in audits:
        event_id = row.get('event_id')
        if isinstance(event_id, str):
            merged[event_id] = project_event(row, 'audit')
    for row in collected:
        event_id = row.get('event_id')
        if not isinstance(event_id, str):
            continue
        kind = 'both' if event_id in merged else 'collected'
        merged[event_id] = project_event(row, kind)
    for event in merged.values():
        kinds[event['record_kind']] += 1
    return sorted(merged.values(), key=sort_key), dict(kinds)


def collection_facts(receipts, now):
    latest, valid = None, 0
    for row in receipts:
        at = parse_time(row.get('at'))
        if at is None:
            continue
        valid += 1
        if latest is None or at > latest[0]:
            latest = (at, row)
    if latest is None:
        return {'last_at': None, 'lag_seconds': None, 'last': None, 'receipts_with_time': valid}
    at, row = latest
    keys = ('file', 'records', 'inserted', 'duplicates', 'conflicts', 'corrupt', 'refused', 'truncated_tail',
            'unconfirmed_audits', 'confirmed_audits')
    return {'last_at': row.get('at'), 'lag_seconds': max(0.0, (now - at).total_seconds()),
            'last': {k: (text(row.get(k), 120) if k == 'file' else row.get(k)) for k in keys},
            'receipts_with_time': valid}


def project_operation(row):
    goal = row.get('goal') if isinstance(row.get('goal'), dict) else {}
    return {'id': text(row.get('id')), 'status': text(row.get('status'), 40),
            'reason_code': text(row.get('reason_code'), 80), 'task_id': text(row.get('task_id')),
            'decision_id': text(row.get('decision_id')), 'lead_accepted': row.get('lead_accepted'),
            'criterion': text(goal.get('criterion')), 'correlation_id': text(row.get('correlation_id'))}


def local_facts(runtime):
    """Local spool health through SpoolDirectory read methods only; missing data is unavailable."""
    if runtime is None:
        return {'status': 'unavailable', 'reason': 'runtime_not_configured'}
    root = Path(runtime) / 'observations'
    if not root.is_dir():
        return {'status': 'unavailable', 'reason': 'directory_missing'}
    from codex_harness.adapters.observation_spool import SpoolDirectory
    directory = SpoolDirectory(root)
    try:
        segments = directory.spool_files()
        health = []
        for record in directory.read_health():
            counters = record.get('counters') if isinstance(record.get('counters'), dict) else {}
            spool = record.get('spool') if isinstance(record.get('spool'), dict) else {}
            health.append({'process_run_id': text(record.get('process_run_id'), 40),
                           'component': text(record.get('component'), 80), 'role': text(record.get('role')),
                           'updated_at': record.get('updated_at') if parse_time(record.get('updated_at')) else None,
                           'sink': text(record.get('sink'), 20), 'unreadable': bool(record.get('unreadable')),
                           'dropped': {k: counters.get(k) for k in ('dropped_spool_full', 'spool_failures', 'refused',
                                                                     'dropped_run_refused', 'alerts_pending_dropped')},
                           'pending_alerts': len(record.get('pending_alerts') or []),
                           'unacknowledged_bytes': spool.get('unacknowledged_bytes'),
                           'limit_bytes': spool.get('limit_bytes'),
                           'last_defect': text(record.get('last_defect'), 120)})
        pending = directory.pending_terminations()
        alerts = directory.read_pending_alerts()
        return {'status': 'ok', 'segments': len(segments), 'unacknowledged_bytes': directory.unacknowledged_bytes(),
                'health': health[:50], 'health_total': len(health),
                'pending_alert_files': {text(k, 40): len(v) for k, v in list(alerts.items())[:50]},
                'pending_alerts': sum(len(v) for v in alerts.values()),
                'pending_terminations': len(pending), 'unreadable_terminations': sum(bool(r.get('unreadable')) for r in pending)}
    except (OSError, ValueError) as exc:
        return {'status': 'unavailable', 'reason': type(exc).__name__}


def observation_facts(store, runtime=None, now=None):
    now = now or datetime.now(timezone.utc)
    sample = {}
    with store.transaction() as tx:
        data = {}
        for bucket in (AUDIT_BUCKET, EVENT_BUCKET, ALERT_BUCKET, QUARANTINE_BUCKET, COLLECTION_BUCKET,
                       TERMINATION_BUCKET, OPERATION_BUCKET):
            data[bucket], sample[bucket] = scan_bounded(tx, bucket)
    events, kinds = merge_events(data[AUDIT_BUCKET], data[EVENT_BUCKET])
    unknown = {'severity': sum(e['severity'] == 'unknown' for e in events),
               'category': sum(e['category'] == 'unknown' for e in events),
               'observed_at': sum(not e['observed_at_valid'] for e in events)}
    high = [e for e in events if e['severity'] in ('error', 'critical')]
    terminations = Counter(text(r.get('status'), 40) or 'unknown' for r in data[TERMINATION_BUCKET])
    operations = [project_operation(r) for r in data[OPERATION_BUCKET]]
    return {'schema': SCHEMA, 'observed_at': now.isoformat(), 'authority': 'informational_only',
            'labels': dict(CATEGORY_LABELS),
            'sample': {'limit_per_bucket': BUCKET_LIMIT, 'selection': 'first rows in store id order',
                       'truncated': any(s['truncated'] for s in sample.values()), 'buckets': sample,
                       'note': 'counts describe the sampled stored rows, not lifetime totals; '
                               'stored rows do not prove every expected event was emitted'},
            'events': {'total': len(events), 'record_kinds': kinds,
                       'by_category': dict(Counter(e['category'] for e in events)),
                       'by_severity': dict(Counter(e['severity'] for e in events)),
                       'by_outcome': dict(Counter(e['outcome'] or 'unknown' for e in events)),
                       'unknown': unknown, 'rows': events[:ROW_LIMIT], 'rows_limit': ROW_LIMIT,
                       'rows_truncated': len(events) > ROW_LIMIT,
                       'high_severity': high[:HIGH_LIMIT], 'high_severity_total': len(high)},
            'collection': {**collection_facts(data[COLLECTION_BUCKET], now), 'receipts': len(data[COLLECTION_BUCKET])},
            'alerts': {'recorded': len(data[ALERT_BUCKET]),
                       'by_status': dict(Counter(text((r.get('notification') or {}).get('status'), 40) or 'unknown'
                                                 for r in data[ALERT_BUCKET]))},
            'quarantine': {'total': len(data[QUARANTINE_BUCKET]),
                           'by_reason': dict(Counter(text(r.get('reason'), 40) or 'unknown' for r in data[QUARANTINE_BUCKET]))},
            'terminations': {'by_status': dict(terminations),
                             'pending': sum(terminations[s] for s in PENDING_TERMINATION)},
            'operations': {'total': len(operations), 'by_status': dict(Counter(o['status'] or 'unknown' for o in operations)),
                           'rows': operations[:OPERATION_LIMIT], 'rows_truncated': len(operations) > OPERATION_LIMIT},
            'local': local_facts(runtime)}
