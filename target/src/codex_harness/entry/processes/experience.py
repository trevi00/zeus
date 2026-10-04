"""Entry of the upstream-lesson import process (M7 `adapters/experience.py` main; INV-EXPERIENCE-001).

Layer: entry
Owns: the argv shape and exit codes (0 imported, 1 unavailable, 2 contract refusal) of `python -m codex_harness.entry.processes.experience`
Does not own: the lesson parsing and import (knowledge.adapters.experience_import) and the store and artifacts wiring (composition.process_entries)
Entry points: main
Contracts: INV-EXPERIENCE-001

    uv run python -m codex_harness.entry.processes.experience DIR_OR_FILES... --basis observed --dry-run

The body is M7 `main` (:91-115) verbatim except the composition calls and the home of `ContractError` (kernel.errors).
"""
import argparse
import json
import sys
from pathlib import Path

from codex_harness.composition import process_entries
from codex_harness.kernel.errors import ContractError


def main(argv=None, store=None):
    parser = argparse.ArgumentParser(description="Import explicitly selected upstream lesson files; never scan user homes automatically.")
    parser.add_argument('paths', nargs='+', type=Path, help='Lesson .md files or directories (non-recursive)')
    parser.add_argument('--source', default='harness', help='Upstream source name')
    parser.add_argument('--basis', choices=('pinned', 'observed'), required=True)
    parser.add_argument('--revision', help='Full commit SHA; required for pinned, forbidden for observed')
    parser.add_argument('--path-prefix', default='', help='Upstream-relative directory recorded before file names')
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    parser.add_argument('--dry-run', action='store_true', help='Parse and classify only; no database or artifact writes')
    args = parser.parse_args(argv)
    basis = {'kind': args.basis, 'revision': args.revision}
    try:
        if args.dry_run:
            report = process_entries.experience_preview(args.paths, args.source, basis, args.path_prefix)
        else:
            report = process_entries.experience_import(args.paths, args.source, basis,
                                                       store or process_entries.experience_store(),
                                                       process_entries.experience_artifacts(args.artifacts), args.path_prefix)
    except ContractError as exc:
        print(json.dumps({'error': 'ContractError', 'message': str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'error': 'Import unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
