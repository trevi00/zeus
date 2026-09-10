"""Register explicitly listed non-Git assets in an audit's observed-asset ledger.

    uv run python -m codex_harness.adapters.observed_assets AUDIT_ID manifest.json [--dry-run]

The manifest is a JSON list of {path, basis, state, sha256, size, evidence_refs}; `path` is the raw
relative path and is stored base64-encoded like Git inventory entries (INV-RESEARCH-001).
"""
import argparse
import base64
import json
import sys
from dataclasses import asdict
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.research import ResearchAudits
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import database_url, organization
from codex_harness.domain.model import ContractError, require
from codex_harness.domain.research import parse_record

MAX_MANIFEST_BYTES = 8 * 1024 * 1024


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
    parser = argparse.ArgumentParser(description=__doc__)
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
            store = store or PostgresStore(database_url())
            audits = ResearchAudits(store, None, artifacts or FileArtifacts(args.artifacts),
                                    Workflow(store, organization()))
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
