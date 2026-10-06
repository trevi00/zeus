"""Import explicitly selected Baldrix JSONL; never scan user homes automatically."""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.skill_history import project_identity
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.skill_import import SkillImport
from codex_harness.bootstrap import database_url
from codex_harness.domain.model import ContractError, canonical, digest, require
from codex_harness.domain.project_skills import normalize_profile
from codex_harness.domain.skill_import import (
    MAX_INPUT_BYTES,
    project_jsonl,
    source_document,
    validate_source,
)


def import_file(path, project, source, store, artifacts):
    validate_source(source)
    require(Path(path).is_file(), 'Import source must be a regular file')
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    require(len(data) <= MAX_INPUT_BYTES, 'Import exceeds byte limit')
    receipt = artifacts.put(canonical(source_document(data, source)), 'legacy-skill-jsonl')
    return SkillImport(store).ingest(project, source, data, receipt['ref'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--source-id', required=True, help='Stable ID of one append-only segment; new ID after rotation')
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--project-id')
    identity.add_argument('--github-repo')
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    parser.add_argument('--dry-run', action='store_true', help='Parse only; does not check an existing import cursor')
    args = parser.parse_args(argv)
    try:
        profile = normalize_profile({'project_id': args.project_id}) if args.project_id else {}
        project = project_identity(profile, SimpleNamespace(remote=args.github_repo))
        require(project is not None, 'Invalid project identity')
        validate_source(args.source_id)
        require(args.file.is_file(), 'Import source must be a regular file')
        if args.dry_run:
            with args.file.open('rb') as stream:
                parsed = project_jsonl(stream.read(MAX_INPUT_BYTES + 1), args.source_id)
            report = {k: v for k, v in parsed.items() if k != 'events'}
            report['preview_only'] = True
        else:
            report = import_file(args.file, digest(project), args.source_id,
                                 PostgresStore(database_url()), FileArtifacts(args.artifacts))
    except ContractError as exc:
        print(json.dumps({'error': 'ContractError', 'message': str(exc)}), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(json.dumps({'error': type(exc).__name__}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'error': 'Import unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0
