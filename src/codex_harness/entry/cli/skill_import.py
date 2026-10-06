"""Import explicitly selected Baldrix JSONL; never scan user homes automatically.

Layer: entry
Owns: main, the argparse main of the legacy skill telemetry import (INV-SKILL-IMPORT-001)
Does not own: the adapter constructions (composition.skill_telemetry), the import of one file (context.adapters.skill_import) and the import rules (context.application.skill_import, context.domain.skills.import_)
Entry points: main
Contracts: INV-SKILL-IMPORT-001

Moved from M7 `adapters/skill_import.py:main` (SOURCE e38aa722:33-68) by rule R-c19 R-t1 (S11 R-S7, the threshold_proposals precedent): every adapter construction is a `composition.skill_telemetry` builder, `ContractError`, `digest` and `require` come from kernel and `normalize_profile`, `project_jsonl`, `validate_source` and `MAX_INPUT_BYTES` from context's domain; every other statement is M7's, including the exit codes 0/1/2 and the error JSON shapes. `import_file` stays in context's adapters. The first paragraph is M7's module docstring.
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from codex_harness.composition import skill_telemetry
from codex_harness.context.domain.project_skills import normalize_profile
from codex_harness.context.domain.skills.import_ import MAX_INPUT_BYTES, project_jsonl, validate_source
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest


def main(argv=None, *, store=None, artifacts=None):
    parser = argparse.ArgumentParser(description="Import explicitly selected Baldrix JSONL; never scan user homes automatically.")
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
        project = skill_telemetry.project_identity(profile, SimpleNamespace(remote=args.github_repo))
        require(project is not None, 'Invalid project identity')
        validate_source(args.source_id)
        require(args.file.is_file(), 'Import source must be a regular file')
        if args.dry_run:
            with args.file.open('rb') as stream:
                parsed = project_jsonl(stream.read(MAX_INPUT_BYTES + 1), args.source_id)
            report = {k: v for k, v in parsed.items() if k != 'events'}
            report['preview_only'] = True
        else:
            report = skill_telemetry.import_file(args.file, digest(project), args.source_id,
                                                 store if store is not None else skill_telemetry.store(),
                                                 artifacts if artifacts is not None else skill_telemetry.artifacts(args.artifacts))
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
