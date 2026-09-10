"""Import explicitly selected upstream lesson files; never scan user homes automatically.

    uv run python -m codex_harness.adapters.experience DIR_OR_FILES... --basis observed --dry-run
"""
import argparse
import base64
import json
import sys
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.project_skills import load_yaml
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.experience import ExperienceClaims
from codex_harness.bootstrap import database_url
from codex_harness.domain.experience import (
    MAX_LESSON_BYTES,
    experience_claim,
    split_frontmatter,
    validate_basis,
)
from codex_harness.domain.model import ContractError, canonical, require


def parse_lesson(source, path, data, basis):
    """Frontmatter goes through the bounded string-only loader; implicit typing never applies."""
    frontmatter, _ = split_frontmatter(data)
    return experience_claim(source, path, data, basis, load_yaml(frontmatter, 'Lesson frontmatter'))


def lesson_files(paths):
    files = []
    for path in paths:
        path = Path(path)
        require(not path.is_symlink(), 'Symlinked lesson input is not accepted')
        if path.is_dir():
            files.extend(p for p in sorted(path.glob('*.md')) if p.is_file() and not p.is_symlink())
        else:
            require(path.is_file(), 'Lesson input must be a regular file or directory: ' + str(path))
            files.append(path)
    require(bool(files), 'No lesson files selected')
    return files


def read_lesson(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_LESSON_BYTES + 1)
    require(len(data) <= MAX_LESSON_BYTES, 'Lesson exceeds byte limit: ' + Path(path).name)
    return data


def import_lessons(paths, source, basis, store, artifacts, path_prefix=''):
    basis = validate_basis(basis)
    claims = ExperienceClaims(store)
    report = []
    for file in lesson_files(paths):
        data = read_lesson(file)
        claim = parse_lesson(source, path_prefix + file.name, data, basis)
        receipt = artifacts.put(canonical({'encoding': 'base64', **claim['source'],
                                           'body': base64.b64encode(data).decode('ascii')}), 'upstream-lesson')
        result = claims.record(claim, receipt['ref'])
        report.append(row(claim, result))
    return {'source': source, 'basis': basis, 'claims': report, 'totals': totals(report)}


def preview_lessons(paths, source, basis, path_prefix=''):
    basis = validate_basis(basis)
    report = [row(parse_lesson(source, path_prefix + file.name, read_lesson(file), basis))
              for file in lesson_files(paths)]
    return {'source': source, 'basis': basis, 'claims': report, 'totals': totals(report), 'preview_only': True}


def row(claim, result=None):
    return {'path': claim['source']['path'], 'sha256': claim['source']['sha256'], 'id': claim['id'],
            'status': claim['status'], 'upstream_occurrences': claim['upstream_occurrences'],
            'upstream_trust': claim['upstream'].get('trust'),
            'independent_occurrences': claim['independent_occurrences']['count'],
            'counters': len(claim['independent_occurrences']['counters']),
            'unclassified': len(claim['independent_occurrences']['unclassified']),
            **({'changed': result['changed'], 'body_ref': result['body_ref']} if result else {})}


def totals(report):
    return {'files': len(report),
            'upstream_occurrences_sum': sum(entry['upstream_occurrences'] or 0 for entry in report),
            'independent_occurrences_sum': sum(entry['independent_occurrences'] for entry in report),
            'unverified': sum(entry['status'] == 'upstream_occurrences_unverified' for entry in report),
            'recomputed': sum(entry['status'] == 'independently_recomputed' for entry in report)}


def main(argv=None, store=None):
    parser = argparse.ArgumentParser(description=__doc__)
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
            report = preview_lessons(args.paths, args.source, basis, args.path_prefix)
        else:
            report = import_lessons(args.paths, args.source, basis, store or PostgresStore(database_url()),
                                    FileArtifacts(args.artifacts), args.path_prefix)
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
