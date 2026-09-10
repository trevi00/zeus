"""Read-only CLI presentation and PostgreSQL composition for skill telemetry."""
import argparse
import json
import sys
import time
from types import SimpleNamespace

from codex_harness.adapters.skill_history import project_identity
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.skill_history import SkillHistory
from codex_harness.application.skill_import import SkillImport
from codex_harness.bootstrap import database_url
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.project_skills import normalize_profile
from codex_harness.domain.skill_audit import DIMENSIONS, duration_seconds
from codex_harness.domain.skill_history import MIN_SAMPLES
from codex_harness.domain.skill_import import validate_source


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


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--project-id', help='Git-owned project UUID from .harness/tech-stack.yaml')
    identity.add_argument('--github-repo', help='Configured owner/repo fallback for profiles without UUID')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--since', default='')
    parser.add_argument('--min-samples', type=int, default=MIN_SAMPLES)
    parser.add_argument('--legacy-source', help='Audit one explicitly imported log segment, separately from live history')
    args = parser.parse_args(argv)
    try:
        cutoff = time.time() - duration_seconds(args.since) if args.since else None
        require(args.min_samples > 0, 'Minimum samples must be positive')
        if args.legacy_source is not None:
            validate_source(args.legacy_source)
        selection = normalize_profile({'project_id': args.project_id}) if args.project_id else {}
        project = project_identity(selection, SimpleNamespace(remote=args.github_repo))
        require(project is not None, 'Invalid project identity')
    except (ContractError, ValueError):
        print(json.dumps({'error': 'Invalid audit arguments'}), file=sys.stderr)
        return 2
    try:
        backend = store if store is not None else PostgresStore(database_url())
        options = {'min_samples': args.min_samples, 'cutoff': cutoff}
        report = (SkillImport(backend).audit(digest(project), args.legacy_source, **options)
                  if args.legacy_source else SkillHistory(backend).audit(digest(project), **options))
    except Exception as exc:
        print(json.dumps({'error': 'Audit unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True) if args.json else render_text(report))
    return 0
