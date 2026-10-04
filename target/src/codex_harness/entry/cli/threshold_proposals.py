"""Calculate and archive threshold proposals against the loaded Git-bound policy.

Layer: entry
Owns: main, the argparse main of the threshold-proposal calculation (V27)
Does not own: the adapter constructions (composition.thresholds), the proposal rules (research.application.threshold_proposals) and the Git-bound policy (research.adapters.threshold_policy)
Entry points: main
Contracts: INV-THRESHOLD-PROPOSAL-001

Moved from M7 `adapters/threshold_proposals.py` (SOURCE e38aa722) by rule R-c19 R-t1 (S10 unit T1): every adapter construction is a `composition.thresholds` builder, `ContractError`, `digest` and `require` come from kernel and `normalize_profile` from context's domain; every other statement is M7's, including the exit codes 0/1/2 and the two error JSON shapes. The first paragraph is M7's module docstring.
"""
import argparse
import json
import sys
import tempfile
from types import SimpleNamespace

from codex_harness.composition import thresholds
from codex_harness.context.domain.project_skills import normalize_profile
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description="Calculate and archive threshold proposals against the loaded Git-bound policy.")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--project-id')
    identity.add_argument('--github-repo')
    parser.add_argument('--harness-repo', required=True)
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--legacy-source')
    parser.add_argument('--min-sample', type=int, default=10)
    parser.add_argument('--evaluation-round', type=int, default=0,
                        help='Explicit new comparison round; identical rounds reuse retained results')
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    args = parser.parse_args(argv)
    try:
        profile = normalize_profile({'project_id': args.project_id}) if args.project_id else {}
        project = thresholds.project_identity(profile, SimpleNamespace(remote=args.github_repo))
        require(project is not None and args.min_sample > 0, 'Invalid proposal identity or sample floor')
        with tempfile.TemporaryDirectory(prefix='threshold-policy-') as workspaces:
            git = thresholds.policy_git(args.harness_repo, workspaces)
            policy = thresholds.current_policy(git, args.revision)
        artifacts = thresholds.artifacts(args.artifacts)
        service = thresholds.proposals(store if store is not None else thresholds.proposal_store(),
            artifacts, policy)
        run = service.collect(digest(project), legacy_source=args.legacy_source, min_sample=args.min_sample,
                              evaluation_round=args.evaluation_round)
        print(json.dumps(run, ensure_ascii=True, allow_nan=False))
        return 0
    except ContractError:
        print(json.dumps({'error': 'Invalid or stale proposal input'}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'error': 'Proposal calculation unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
