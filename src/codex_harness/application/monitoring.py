"""Read-only monitoring projection; durable records retain their original meaning."""
from collections import Counter
from datetime import datetime, timezone
from typing import Protocol

from codex_harness.domain.policy import POLICY


class MonitoringFacts(Protocol):
    def read(self) -> dict: ...


def age_seconds(timestamp, now):
    try:
        return max(0, (now - datetime.fromisoformat(timestamp)).total_seconds())
    except (TypeError, ValueError):
        return None


class Monitoring:
    def __init__(self, facts: MonitoringFacts):
        self.facts = facts

    def snapshot(self, now=None):
        now = now or datetime.now(timezone.utc)
        facts = self.facts.read()
        health = facts.get('health') or {}
        age = age_seconds(health.get('checked_at'), now)
        facts['operating_status'] = (health.get('status', 'unknown')
                                     if age is not None and age <= 120 else 'unknown')
        facts['health_age_seconds'] = age
        notifications = facts.setdefault('notifications', {'status_counts': {}, 'last_batch': {}})
        notification_age = age_seconds(notifications['last_batch'].get('at'), now)
        attention = any(notifications['status_counts'].get(k, 0) for k in ('quarantined', 'retry', 'error', 'publishing'))
        notifications['status'] = ('attention' if attention else 'observed'
                                   if notification_age is not None and notification_age <= 120 else 'unknown')
        notifications['age_seconds'] = notification_age
        facts['task_counts'] = dict(Counter(row['status'] for row in facts['tasks']))
        for agent in facts['agents']:
            owned = [row for row in facts['tasks'] + facts['decisions'] if row['agent'] == agent['id']]
            running = [row for row in owned if row['status'] == 'running'
                       and age_seconds(row.get('lease_until'), now) == 0
                       and row.get('lease_until') is not None]
            agent['execution_state'] = 'running' if running else 'waiting'
            agent['work'] = [row['id'] for row in running]
            agent['queued'] = sum(row['status'] in {'queued', 'pending', 'retry'} for row in owned)
            agent['expired_leases'] = sum(row['status'] == 'running' and row not in running for row in owned)
        facts['policy'] = POLICY.snapshot()
        facts['observed_at'] = now.isoformat()
        facts['initiatives'] = initiatives(facts, now)
        return facts


def initiatives(facts, now):
    """Project durable workflow stages without equating task completion to deployment."""
    grouped = {}
    for row in facts['tasks'] + facts['decisions']:
        if row.get('correlation'):
            grouped.setdefault(row['correlation'], []).append(row)
    output = []
    phases = [('plan', '계획'), ('implement', '구현'), ('review_lead', '팀장 검수'),
              ('review_conductor', '지휘자 검수')]
    for correlation, rows in grouped.items():
        if not any(r.get('phase') in {'plan', 'implement'} for r in rows):
            continue
        rows.sort(key=lambda r: r.get('created_at') or '')
        stages = []
        for phase, title in phases:
            matching = [r for r in rows if r.get('phase') == phase]
            row = matching[-1] if matching else None
            state = row['status'] if row else 'waiting'
            if row and row.get('accepted') is False and state == 'succeeded':
                state = 'rejected'
            if row and state == 'running' and age_seconds(row.get('lease_until'), now) != 0:
                state = 'lease_expired'
            stages.append({'phase': phase, 'title': title, 'status': state, 'record': row})
        release_ids = {r.get('release_id') for r in rows} - {None}
        revisions = {r.get('revision') for r in rows} - {None}
        releases = [r for r in facts.get('releases', [])
                    if r['id'] in release_ids or r.get('revision') in revisions]
        release = max(releases, key=lambda r: r.get('created_at') or '') if releases else None
        checks = (release or {}).get('checks', {})
        canary = ('failed' if any(c.get('passed') is False for c in checks.values()) else
                  'succeeded' if checks and release['status'] in {'verified', 'active', 'superseded'}
                  and all(c.get('passed') is True for c in checks.values()) else 'waiting')
        stages.extend([{'phase': 'canary', 'title': '테스트 · 카나리아', 'status': canary, 'record': release},
                       {'phase': 'deployment', 'title': '운영 반영',
                        'status': (release or {}).get('status', 'waiting'), 'record': release}])
        attention = [s for s in stages if s['status'] in
                     {'blocked', 'inspection_blocked', 'failed', 'rejected', 'lease_expired', 'rolled_back'}]
        active = [s for s in stages[:4] if s['status'] in {'running', 'pending', 'queued', 'retry'}]
        focus = attention[0] if attention else active[0] if active else None
        last_activity = max((r.get('progress_at') or r.get('completed_at') or r.get('created_at') or ''
                             for r in rows), default='')
        activity_age = age_seconds(last_activity, now)
        output.append({'id': correlation,
            'title': next((r['objective'] for r in rows if r.get('objective')), correlation),
            'status': 'attention' if attention else 'running' if active else
                      'deployed' if (release or {}).get('status') == 'active' else
                      'previously_deployed' if (release or {}).get('status') == 'superseded' else
                      'awaiting_next_stage',
            'focus': focus['title'] if focus else '다음 단계 확인',
            'reason': ((focus or {}).get('record') or {}).get('reason') or
                      ((focus or {}).get('record') or {}).get('error') or '',
            'last_activity': last_activity, 'activity_age_seconds': activity_age,
            'activity_note': '최근 활동 관측' if activity_age is not None and activity_age <= 120 else
                             '최근 활동 없음 · 정체 여부 확인 필요',
            'stages': stages})
    return sorted(output, key=lambda r: (r['status'] == 'attention', r['last_activity']), reverse=True)
