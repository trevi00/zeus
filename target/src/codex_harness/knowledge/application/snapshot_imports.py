"""Snapshot imports: verify before import, bind bytes and revisions, keep failures as failures.

Layer: application
Context: knowledge
Owns: bucket snapshot_imports (single writer)
Does not own: snapshot verification rules (knowledge.domain.snapshot_integrity)
Entry points: SnapshotImports
Contracts: INV-SNAPSHOT-001
Moved from SOURCE M7 `src/codex_harness/application/snapshot_imports.py` (behaviour unchanged unless noted).

A snapshot is imported only after `verify_snapshot` says valid; the receipt binds the immutable
bytes (archived as artifacts), the source, tool and environment revisions, the manifest hash, the
mode and the full report. An invalid snapshot is recorded with its raw bytes and errors and never
touches existing runtime state; a consumer that needs a snapshot calls `require_valid`.
"""
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical, digest, utcnow
from codex_harness.knowledge.domain.snapshot_integrity import verify_snapshot

BUCKET = 'snapshot_imports'
REVISION = 40


def _revision(value, name):
    require(type(value) is str and (len(value) == REVISION and all(c in '0123456789abcdef' for c in value) or value == 'unversioned'),
            f'{name} must be a Git commit hash or "unversioned"')
    return value


class SnapshotImports:
    def __init__(self, store, artifacts, clock=None):
        # Injected clock (kernel.ports.Clock); None is the system clock (R-D).
        self.clock = clock
        self.store, self.artifacts = store, artifacts

    def import_snapshot(self, files, manifest, *, binding, mode='confirmed'):
        require(isinstance(binding, dict) and set(binding) == {'source_revision', 'tool_revision', 'environment'},
                'Import binding requires source_revision, tool_revision, environment')
        _revision(binding['source_revision'], 'source_revision')
        _revision(binding['tool_revision'], 'tool_revision')
        require(type(binding['environment']) is str and binding['environment'], 'environment must be a label')
        report = verify_snapshot(files, manifest, mode)
        archived = {}
        for name in sorted(files):
            data = files[name]
            if isinstance(data, bytes):
                receipt = self.artifacts.put(canonical({'name': name, 'encoding': 'latin-1 byte-preserving',
                                                        'sha256': digest(data.decode('latin-1')), 'bytes': len(data),
                                                        'raw': data.decode('latin-1')}), 'snapshot-file')
                archived[name] = receipt['ref']
            else:
                archived[name] = None
        key = digest(['snapshot-import-v1', report['snapshot_hash'], report['manifest_hash'], binding, mode])
        with self.store.transaction() as tx:
            existing = tx.get(BUCKET, key)
            if existing is not None:
                return existing
            row = {'id': key, 'status': report['status'], 'mode': mode, 'binding': binding, 'manifest_hash': report['manifest_hash'],
                   'snapshot_hash': report['snapshot_hash'], 'files': archived, 'report': report, 'imported_at': utcnow(self.clock),
                   'importable': report['status'] == 'valid',
                   'authority': 'verified bytes bound to revisions; not adoption, promotion or model qualification'}
            tx.put(BUCKET, key, row)
            return row

    def require_valid(self, tx, import_id):
        row = tx.get(BUCKET, import_id)
        require(row is not None, 'Snapshot import missing')
        problems = ('files_missing', 'files_unreadable', 'files_corrupt', 'lines_corrupt', 'dangling_references')
        counts = row['report']['denominator']
        require(row['importable'], 'Snapshot import is ' + row['status'] + ': '
                + ', '.join(f'{k}={counts[k]}' for k in problems if counts.get(k)))
        return row
