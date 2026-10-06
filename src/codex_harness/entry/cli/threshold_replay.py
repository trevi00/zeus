"""Run a Baldrix reference replay and preserve the exact corpus as evidence.

Layer: entry
Owns: main, the argparse main of the Baldrix reference replay (V27)
Does not own: the adapter constructions (composition.thresholds), the replay rules (research.application.threshold_replay.ThresholdReplay) and the project identity (context.adapters.skill_history.project_identity)
Entry points: main
Contracts: INV-NATIVE-REPLAY-001

Moved from M7 `adapters/threshold_replay.py` (SOURCE e38aa722) by rule R-c20 R-t5 (S10 unit T2): every adapter construction is a `composition.thresholds` builder (`replay_store`, `replay`, `replay_artifacts`, `project_identity`), `ContractError`, `require`, `digest`, `canonical`, `timestamp` and `finite_number` come from kernel, and `normalize_profile` and `validate_source` from context's domain; every other statement is M7's, including the exit codes 0/1/2 and the two error JSON shapes. The first line is M7's module docstring.
"""
import argparse
import json
import sys
from types import SimpleNamespace

from codex_harness.composition import thresholds
from codex_harness.context.domain.project_skills import normalize_profile
from codex_harness.context.domain.skills.import_ import validate_source
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import canonical, digest
from codex_harness.kernel.numbers import finite_number
from codex_harness.kernel.timestamps import timestamp


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description="Run a Baldrix reference replay and preserve the exact corpus as evidence.")
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
        project = thresholds.project_identity(profile, SimpleNamespace(remote=args.github_repo))
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
        backend = store if store is not None else thresholds.replay_store()
        document = thresholds.replay(backend).evaluate(digest(project), legacy_source=args.legacy_source,
            old_value=args.old_value, proposed_value=args.proposed_value,
            holdout_boundary=args.holdout_boundary, min_corpus=args.min_samples)
        receipt = thresholds.replay_artifacts(args.artifacts).put(canonical(document), 'threshold-reference-replay')
        output = {k: value for k, value in document.items() if k != 'events'}
        output['evidence_ref'] = receipt['ref']
    except Exception as exc:
        print(json.dumps({'error': 'Replay unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=True, allow_nan=False))
    return 0
