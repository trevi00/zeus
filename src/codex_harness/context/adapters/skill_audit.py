"""Read-only CLI presentation and PostgreSQL composition for skill telemetry.

Layer: adapters
Context: context
Owns: the read-only skill telemetry report text
Does not own: the CLI argv and store construction (entry/composition, S10)
Entry points: render_text, main
Contracts: INV-SKILL-HISTORY-001
Moved from SOURCE M7 `src/codex_harness/adapters/skill_audit.py` (behaviour unchanged unless noted).

The M7 `main()` (argparse, `PostgresStore(database_url())`, `FileArtifacts`) is entry/composition
work and moves to `entry.cli` / `composition` in S10 (§3.5 keeps the `-m` form if pinned); this
module keeps the injected-store functions only.
"""

from codex_harness.context.domain.skills.audit import DIMENSIONS


def render_text(report):
    lines = [f"=== skill telemetry audit ({report['invocations']} invocations) ==="]
    if report.get('legacy_source'):
        lines.extend([f"LEGACY SOURCE: {report['legacy_source']}",
                      'Historical skill version unknown; findings do not identify current skill bytes.',
                      f"Source artifact: {report.get('source_ref') or 'not imported'}"])
    if not report['skills']:
        lines.append('(no skill-match telemetry)')
    else:
        lines.append('skill [content version] | n | min | median | max | thin% | dominant dimension')
        for row in report['skills']:
            lines.append(f"{row['path']} [{row['content_ref']}] | {row['count']} | {row['score_min']} | "
                         f"{row['score_median']} | {row['score_max']} | {round(row['thin_rate'] * 100)}% | "
                         f"{row['dominant_dim'] or '-'}")
            base = row['base_score_profile']
            if base:
                lines.append(f"  base score median: {base['median']}; boosted observations: "
                             f"{base['boosted_count']}/{base['count']}; "
                             f"missing base scores: {row['missing_base_scores']}")
            delivered = row['delivery']
            lines.append(f"  ranked first: {row['rank_first_count']}/{row['count']}; delivered full body: "
                         f"{delivered['full']}, pointer: {delivered['pointer'] + delivered['external_pointer']}, "
                         f"omitted by budget: {delivered['omitted']}, tier unknown: {delivered['unknown']} "
                         f"(match != delivery != behavior; delivery = final compiled context, not model reach)")
        lines.append('dimension weight (counts of matching signals, not score contributions):')
        weights = report['dim_weight']
        total = sum(weights.values()) or 1
        for category in (*DIMENSIONS, 'unknown'):
            if category in weights:
                lines.append(f'{category}: {weights[category]} ({round(100 * weights[category] / total)}%)')
        if not weights:
            lines.append('(no dimension data in these observations)')
        lines.append(f"false-positive candidates: {len(report['false_positive_candidates'])}")
        for row in report['false_positive_candidates']:
            lines.append(f"{row['path']} [{row['content_ref']}]: {row['reason']}")
    lines.append(f"Bounded to {report['max_events']} recent observations; "
                 f"unknown timestamps included: {report['unknown_timestamp_events']}; "
                 f"invalid entries skipped: {report['invalid_entries']}. Read-only; no skill edits.")
    return '\n'.join(lines)
