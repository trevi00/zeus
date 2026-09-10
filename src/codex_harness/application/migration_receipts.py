"""Migration run receipts: a precheck or apply is evidence only when bound to its inputs and its process.

A caller runs the migrator as a real process and hands the receipt here: the argv, the config
hash, the root, the source revision, the tool identity, the environment label, the exact stdout
and stderr bytes and the exit code. The receipt is stored as it happened; a refused or errored run
is a recorded failure. `require_approved` admits only a precheck that allowed apply, and never a
receipt whose tool differs from the pinned one.
"""
import json

from codex_harness.domain.migrations import TOOL
from codex_harness.domain.model import canonical, digest, require, utcnow

BUCKET = 'migration_runs'
OPERATIONS = ('precheck', 'apply')


def _revision(value, name):
    require(type(value) is str and (len(value) == 40 and all(c in '0123456789abcdef' for c in value) or value == 'unversioned'),
            f'{name} must be a Git commit hash or "unversioned"')


class MigrationReceipts:
    def __init__(self, store, artifacts):
        self.store, self.artifacts = store, artifacts

    def record(self, run):
        require(isinstance(run, dict) and set(run) == {'operation', 'argv', 'config_hash', 'root', 'source_revision', 'environment',
                                                       'stdout', 'stderr', 'exit_code', 'started_at', 'finished_at'},
                'Run receipt requires operation, argv, config_hash, root, source_revision, environment, stdout, stderr, exit_code, started_at, finished_at')
        require(run['operation'] in OPERATIONS, 'Unknown migration operation')
        require(isinstance(run['argv'], list) and run['argv'] and all(type(a) is str for a in run['argv']), 'argv must be text')
        require(type(run['config_hash']) is str and len(run['config_hash']) == 64, 'config_hash must be the parsed config digest')
        _revision(run['source_revision'], 'source_revision')
        require(type(run['environment']) is str and run['environment'], 'environment must be a label')
        require(isinstance(run['stdout'], bytes) and isinstance(run['stderr'], bytes), 'stdout and stderr are bound as bytes')
        require(type(run['exit_code']) is int, 'exit_code must be an integer')
        try:
            document = json.loads(run['stdout'].decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            document = None
        tool = document.get('tool') if isinstance(document, dict) else None
        outcome = ('error' if isinstance(document, dict) and 'error' in document else 'refused' if isinstance(document, dict) and 'refused' in document
                   else 'completed' if isinstance(document, dict) and ('plan' in document or 'receipt' in document) else 'unparseable')
        # The process output must name the same operation, config and root the caller says it ran;
        # otherwise the receipt is kept as a binding mismatch and can never approve (review, PR #62).
        body = document.get('plan') if isinstance(document, dict) and 'plan' in document else document.get('receipt') if isinstance(document, dict) else None
        mismatches = []
        if isinstance(document, dict) and document.get('operation') != run['operation']:
            mismatches.append('operation')
        if isinstance(body, dict):
            if body.get('config_hash') != run['config_hash']:
                mismatches.append('config_hash')
            if body.get('root') != run['root']:
                mismatches.append('root')
        if mismatches and outcome == 'completed':
            outcome = 'binding_mismatch'
        stdout = self.artifacts.put(canonical({'kind': 'stdout', 'raw': run['stdout'].decode('latin-1')}), 'migration-run')
        stderr = self.artifacts.put(canonical({'kind': 'stderr', 'raw': run['stderr'].decode('latin-1')}), 'migration-run')
        key = digest(['migration-run-v1', run['operation'], run['argv'], run['config_hash'], run['source_revision'], run['environment'],
                      stdout['ref'], stderr['ref'], run['exit_code'], run['started_at']])
        row = {'id': key, 'operation': run['operation'], 'argv': run['argv'], 'config_hash': run['config_hash'], 'root': run['root'],
               'source_revision': run['source_revision'], 'environment': run['environment'], 'exit_code': run['exit_code'],
               'stdout_ref': stdout['ref'], 'stderr_ref': stderr['ref'], 'started_at': run['started_at'], 'finished_at': run['finished_at'],
               'tool': tool, 'tool_pinned': tool == TOOL, 'outcome': outcome, 'binding_mismatches': mismatches,
               'apply_allowed': bool(isinstance(document, dict) and document.get('plan', {}).get('apply_allowed')) if run['operation'] == 'precheck' else None,
               'results': document.get('plan', {}).get('results') if isinstance(document, dict) and run['operation'] == 'precheck' else None,
               'applied': document.get('receipt', {}).get('applied') if isinstance(document, dict) and run['operation'] == 'apply' else None,
               'recorded_at': utcnow(),
               'authority': 'bound process evidence; not deployment approval, not a human acceptance of money scenarios'}
        with self.store.transaction() as tx:
            existing = tx.get(BUCKET, key)
            if existing is not None:
                return existing
            tx.put(BUCKET, key, row)
        return row

    def require_approved(self, tx, run_id, *, source_revision, environment, config_hash, root):
        """The consumer says which config and root it is about to apply; the receipt must be for exactly those."""
        row = tx.get(BUCKET, run_id)
        require(row is not None, 'Migration run missing')
        require(row['operation'] == 'precheck', 'Only a precheck can approve an apply')
        require(row['tool_pinned'], 'Precheck ran a tool other than the pinned one')
        require(row['source_revision'] == source_revision and row['environment'] == environment,
                'Precheck is bound to another revision or environment')
        require(row['config_hash'] == config_hash and row['root'] == root, 'Precheck is bound to another migration config or root')
        require(not row['binding_mismatches'], 'Precheck output names another ' + ', '.join(row['binding_mismatches']) + ' than its receipt')
        require(row['outcome'] == 'completed' and row['exit_code'] == 0 and row['apply_allowed'] is True,
                'Precheck did not allow apply: ' + (', '.join(f'{k}={v}' for k, v in sorted((row.get('results') or {}).items())
                                                             if v not in {'ok', 'not_applicable'}) or row['outcome']))
        return row
