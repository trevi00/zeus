"""Register explicitly listed non-Git assets in an audit's observed-asset ledger.

Layer: entry
Owns: load_manifest, main, the manifest loader and the argparse main of the observed-asset registration (V27)
Does not own: the adapter constructions (composition.research_entries), the audit rules (research.application.research.ResearchAudits) and the record rules (research.domain.research.parse_record)
Entry points: main, load_manifest
Contracts: INV-RESEARCH-001

Moved from M7 `adapters/observed_assets.py` (SOURCE e38aa722) by rule R-c20 R-t5 (S10 unit T2): every adapter construction is a `composition.research_entries` builder, `ContractError` and `require` come from kernel and `parse_record` from research's domain; every other statement is M7's, including the exit codes 0/1/2, the two error JSON shapes and the `__main__` guard. The usage text of M7's module docstring (the argparse description, `DESCRIPTION`):

    uv run python -m codex_harness.entry.cli.observed_assets AUDIT_ID manifest.json [--dry-run]

The manifest is a JSON list of {path, basis, state, sha256, size, evidence_refs}; `path` is the raw
relative path and is stored base64-encoded like Git inventory entries (INV-RESEARCH-001).
"""
import argparse
import base64
import json
import sys
from dataclasses import asdict
from pathlib import Path

from codex_harness.composition import research_entries
from codex_harness.kernel.errors import ContractError, require
from codex_harness.research.domain.research import parse_record

MAX_MANIFEST_BYTES = 8 * 1024 * 1024

DESCRIPTION = """Register explicitly listed non-Git assets in an audit's observed-asset ledger.

    uv run python -m codex_harness.entry.cli.observed_assets AUDIT_ID manifest.json [--dry-run]

The manifest is a JSON list of {path, basis, state, sha256, size, evidence_refs}; `path` is the raw
relative path and is stored base64-encoded like Git inventory entries (INV-RESEARCH-001).
"""


def load_manifest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Manifest must be a regular file')
    data = path.read_bytes()
    require(len(data) <= MAX_MANIFEST_BYTES, 'Manifest exceeds byte limit')
    try:
        entries = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError('Manifest is not UTF-8 JSON') from exc
    require(isinstance(entries, list) and entries, 'Manifest must be a non-empty list')
    assets = []
    for entry in entries:
        require(isinstance(entry, dict) and isinstance(entry.get('path'), str) and entry['path'],
                'Manifest entry requires a raw relative path')
        record = {**entry, 'path': base64.b64encode(entry['path'].encode('utf-8')).decode('ascii')}
        assets.append(parse_record({'version': 1, 'kind': 'ObservedAsset', 'record': record}))
    return assets


def main(argv=None, store=None, artifacts=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('audit_id')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--artifacts', default='.runtime/artifacts')
    parser.add_argument('--dry-run', action='store_true', help='Validate the manifest only; no database write')
    args = parser.parse_args(argv)
    try:
        assets = load_manifest(args.manifest)
        if args.dry_run:
            report = {'audit_id': args.audit_id, 'assets': len(assets), 'preview_only': True,
                      'pending': sum(a.pending for a in assets),
                      'records': [asdict(a) for a in assets]}
        else:
            store = store or research_entries.observed_assets_store()
            audits = research_entries.observed_assets_audits(
                store, artifacts or research_entries.observed_assets_artifacts(args.artifacts))
            report = audits.observe_assets(args.audit_id, assets)
    except ContractError as exc:
        print(json.dumps({'error': 'ContractError', 'message': str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'error': 'Registration unavailable', 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
