"""Run a Baldrix reference replay and preserve the exact corpus as evidence."""
import argparse
import json
import sys
from types import SimpleNamespace

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.skill_history import project_identity
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.threshold_replay import ThresholdReplay
from codex_harness.bootstrap import database_url
from codex_harness.domain.model import ContractError, canonical, digest, require
from codex_harness.domain.project_skills import normalize_profile
from codex_harness.domain.skill_audit import timestamp
from codex_harness.domain.skill_import import validate_source
from codex_harness.domain.threshold_replay import finite_number


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--project-id')
    identity.add_argument('--github-repo')
    parser.add_argument('--legacy-source')
    parser.add_argument('--holdout-boundary', required=True, help='UTC/offset ISO timestamp; this instant belongs to holdout')
    parser.add_argument('--old-value', required=True, type=float)
    parser.add_argument('--proposed-value', required=True, type=float)
    parser.add_argument('--min-samples', type=int, default=10)
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    args = parser.parse_args(argv)
    try:
        profile = normalize_profile({'project_id': args.project_id}) if args.project_id else {}
        project = project_identity(profile, SimpleNamespace(remote=args.github_repo))
        require(project is not None, 'Invalid project identity')
        require(timestamp(args.holdout_boundary) is not None, 'Invalid holdout boundary')
        require(args.min_samples > 0, 'Minimum samples must be positive')
        require(all(finite_number(value) for value in (args.old_value, args.proposed_value)), 'Invalid threshold')
        if args.legacy_source is not None:
            validate_source(args.legacy_source)
    except ContractError as exc:
        print(json.dumps({'error': 'Invalid replay arguments', 'message': str(exc)}), file=sys.stderr)
        return 2
    try:
        backend = store if store is not None else PostgresStore(database_url())
        document = ThresholdReplay(backend).evaluate(digest(project), legacy_source=args.legacy_source,
            old_value=args.old_value, proposed_value=args.proposed_value,
            holdout_boundary=args.holdout_boundary, min_corpus=args.min_samples)
        receipt = FileArtifacts(args.artifacts).put(canonical(document), 'threshold-reference-replay')
        output = {k: value for k, value in document.items() if k != 'events'}
        output['evidence_ref'] = receipt['ref']
    except Exception as exc:
        print(json.dumps({'error': 'Replay unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=True, allow_nan=False))
    return 0
