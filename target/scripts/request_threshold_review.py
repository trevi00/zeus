"""Queue an assessment using the deployed threshold-review-capable controller."""
import argparse
import json
import sys

from codex_harness.composition import build
from codex_harness.composition.cli import workflow
from codex_harness.kernel.errors import ContractError
from codex_harness.research.application.threshold_reviews import ThresholdReviews
from codex_harness.storage.adapters.file_artifacts import FileArtifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposal_id')
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    args = parser.parse_args()
    try:
        service = build()
        # S11 R-S3: Workflow is no longer constructible as Workflow(store, org); composition.cli.workflow(service) wires the
        # ticket binding, TicketSuperseded and adoption ports it needs (DESIGN-s11 §7 R-S3; build() returns a ServiceHandle,
        # OWNER-DECISIONS-S10 #12).
        result = ThresholdReviews(workflow(service), FileArtifacts(args.artifacts)).request(args.proposal_id)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except ContractError:
        print(json.dumps({'error': 'Invalid threshold review request'}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'error': 'Threshold review unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
