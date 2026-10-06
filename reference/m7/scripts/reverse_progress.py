"""Observe or checkpoint reverse stages through the PostgreSQL application use case."""
import argparse
import json

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.reverse_source import observe_source
from codex_harness.application.reverse_progress import STAGES, STATUSES, ReverseProgress
from codex_harness.bootstrap import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    parser.add_argument('source')
    parser.add_argument('--stage', choices=STAGES)
    parser.add_argument('--status', choices=STATUSES, default='partial')
    parser.add_argument('--artifact', action='append', default=[])
    parser.add_argument('--generation', type=int)
    parser.add_argument('--request-id')
    parser.add_argument('--rebaseline', action='store_true')
    args = parser.parse_args()
    usecase = ReverseProgress(build().store, FileArtifacts('.runtime/artifacts'))
    source = observe_source(args.source)
    if args.stage:
        if args.generation is None or not args.request_id:
            parser.error('--stage requires --generation and --request-id')
        result = usecase.record(args.project, args.stage, args.status, source, args.artifact,
                                args.generation, args.request_id, rebaseline=args.rebaseline)
    else:
        result = usecase.status(args.project, source)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
