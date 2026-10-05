"""Read-only CLI presentation and PostgreSQL composition for skill telemetry.

Layer: entry
Owns: main, the argparse main of the read-only skill telemetry audit (INV-SKILL-HISTORY-001)
Does not own: the adapter constructions (composition.skill_telemetry), the report text (context.adapters.skill_audit) and the audit rules (context.application.skill_history, context.application.skill_import, context.domain.skills.audit)
Entry points: main
Contracts: INV-SKILL-HISTORY-001

Moved from M7 `adapters/skill_audit.py:main` (SOURCE e38aa722:61-90) by rule R-c19 R-t1 (S11 R-S7, the threshold_proposals precedent): every adapter construction is a `composition.skill_telemetry` builder, `ContractError`, `digest` and `require` come from kernel and `normalize_profile`, the audit and import domain constants from context's domain; every other statement is M7's, including the exit codes 0/1/2 and the error JSON shapes. `render_text` stays in context's adapters (re-exported by the composition). The first paragraph is M7's module docstring.
"""
import argparse
import json
import sys
import time
from types import SimpleNamespace

from codex_harness.composition import skill_telemetry
from codex_harness.context.domain.project_skills import normalize_profile
from codex_harness.context.domain.skills.audit import duration_seconds
from codex_harness.context.domain.skills.history import MIN_SAMPLES
from codex_harness.context.domain.skills.import_ import validate_source
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description="Report historical skill score/dimension signals without modifying definitions.")
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
        project = skill_telemetry.project_identity(selection, SimpleNamespace(remote=args.github_repo))
        require(project is not None, 'Invalid project identity')
    except (ContractError, ValueError):
        print(json.dumps({'error': 'Invalid audit arguments'}), file=sys.stderr)
        return 2
    try:
        backend = store if store is not None else skill_telemetry.store()
        options = {'min_samples': args.min_samples, 'cutoff': cutoff}
        report = (skill_telemetry.SkillImport(backend).audit(digest(project), args.legacy_source, **options)
                  if args.legacy_source else skill_telemetry.SkillHistory(backend).audit(digest(project), **options))
    except Exception as exc:
        print(json.dumps({'error': 'Audit unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True) if args.json else skill_telemetry.render_text(report))
    return 0
