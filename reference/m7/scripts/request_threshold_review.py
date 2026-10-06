"""Queue an assessment using the deployed threshold-review-capable controller."""
import argparse
import json
import sys

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.application.threshold_reviews import ThresholdReviews
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import build
from codex_harness.domain.model import ContractError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposal_id')
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    args = parser.parse_args()
    try:
        service = build()
        result = ThresholdReviews(Workflow(service.store, service.org), FileArtifacts(args.artifacts)).request(args.proposal_id)
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
