"""Initialize Git-owned project stack configuration; import legacy YAML explicitly."""
import argparse
import json
from pathlib import Path

import yaml

from codex_harness.adapters.project_detection import detect_project
from codex_harness.adapters.project_skills import initialize
from codex_harness.domain.model import ContractError, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', type=Path)
    source.add_argument('--from-claude', action='store_true')
    source.add_argument('--detect', action='store_true')
    parser.add_argument('--preview', action='store_true', help='Report detected profile without writing')
    args = parser.parse_args()
    path = args.root / '.claude/tech-stack.yaml' if args.from_claude else args.config
    try:
        if args.preview and not args.detect:
            parser.error('--preview requires --detect')
        if args.detect:
            profile = detect_project(args.root)
            require(args.preview or profile['metadata']['detection']['status'] != 'unknown',
                    'No project signals found; use --detect --preview to inspect or --config to specify a stack')
            require(args.preview or bool(profile['stacks']),
                    'Only metadata signals found; use --detect --preview or --config to specify a stack')
            result = {'profile': profile, 'written': False} if args.preview else initialize(
                args.root, yaml.safe_dump(profile, sort_keys=False))
        else:
            result = initialize(args.root, path.read_text('utf-8-sig'), legacy=args.from_claude)
    except (OSError, ContractError) as exc:
        parser.exit(2, json.dumps({'error': type(exc).__name__, 'message': str(exc)}) + '\n')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
