"""Import explicitly selected upstream lesson files; never scan user homes automatically.

Layer: adapters
Context: knowledge
Owns: reading explicitly selected upstream lesson files
Does not own: the CLI argv and store construction (entry/composition, S10)
Entry points: parse_lesson, lesson_files, read_lesson, import_lessons, preview_lessons, row, totals, main
Contracts: INV-EXPERIENCE-001
Moved from SOURCE M7 `src/codex_harness/adapters/experience.py` (behaviour unchanged unless noted).

    uv run python -m codex_harness.adapters.experience DIR_OR_FILES... --basis observed --dry-run

The M7 `main()` (argparse, `PostgresStore(database_url())`, `FileArtifacts`) is entry/composition
work and moves to `entry.cli` / `composition` in S10 (§3.5 keeps the `-m` form if pinned); this
module keeps the injected-store functions only.
Change (declared): the bounded YAML loader is injected (`load_yaml=`); at M7 this module imported
`adapters.project_skills.load_yaml`, but knowledge may not import context (§2.4). Composition passes
`context.adapters.yaml_source.load_yaml`, the same loader, so parsing is unchanged.
"""
import base64
from pathlib import Path

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical
from codex_harness.knowledge.application.experience import ExperienceClaims
from codex_harness.knowledge.domain.experience import (
    MAX_LESSON_BYTES,
    experience_claim,
    split_frontmatter,
    validate_basis,
)


def parse_lesson(source, path, data, basis, *, load_yaml):
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


def import_lessons(paths, source, basis, store, artifacts, path_prefix='', *, load_yaml):
    basis = validate_basis(basis)
    claims = ExperienceClaims(store)
    report = []
    for file in lesson_files(paths):
        data = read_lesson(file)
        claim = parse_lesson(source, path_prefix + file.name, data, basis, load_yaml=load_yaml)
        receipt = artifacts.put(canonical({'encoding': 'base64', **claim['source'],
                                           'body': base64.b64encode(data).decode('ascii')}), 'upstream-lesson')
        result = claims.record(claim, receipt['ref'])
        report.append(row(claim, result))
    return {'source': source, 'basis': basis, 'claims': report, 'totals': totals(report)}


def preview_lessons(paths, source, basis, path_prefix='', *, load_yaml):
    basis = validate_basis(basis)
    report = [row(parse_lesson(source, path_prefix + file.name, read_lesson(file), basis, load_yaml=load_yaml))
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
