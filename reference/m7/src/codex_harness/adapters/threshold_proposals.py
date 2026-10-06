"""Calculate and archive threshold proposals against the loaded Git-bound policy."""
import argparse
import json
import sys
import tempfile
from types import SimpleNamespace

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.native_routing_replay import NativeRoutingReplay
from codex_harness.adapters.skill_history import project_identity
from codex_harness.adapters.store import PostgresStore
from codex_harness.adapters.threshold_policy import current_policy
from codex_harness.application.threshold_proposals import ThresholdProposals
from codex_harness.bootstrap import database_url
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.project_skills import normalize_profile


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description=__doc__)
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
        project = project_identity(profile, SimpleNamespace(remote=args.github_repo))
        require(project is not None and args.min_sample > 0, 'Invalid proposal identity or sample floor')
        with tempfile.TemporaryDirectory(prefix='threshold-policy-') as workspaces:
            git = GitWorkspace(args.harness_repo, workspaces)
            policy = current_policy(git, args.revision)
        artifacts = FileArtifacts(args.artifacts)
        service = ThresholdProposals(store if store is not None else PostgresStore(database_url()),
            artifacts, lambda: policy, NativeRoutingReplay(artifacts))
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
