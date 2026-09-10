"""Migration discovery, history, live schema and apply on real files and a real PostgreSQL (INV-MIGRATION-001).

`discover` reads the configured locations from the filesystem and reports each as found, empty,
missing or unreadable with the exact error. `Migrator.precheck` evaluates the discovery against
the applied history and the live schema without changing anything; `Migrator.apply` re-reads the
history under the control-plane advisory lock, refuses if anything changed and applies pending
versions in normalized order, recording version, checksum, tool and name in the same transaction.
`main` runs either as a child process and prints one JSON document so a caller can bind argv,
stdout, stderr and the exit code.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg

from codex_harness.domain.migrations import TOOL, evaluate, parse_config
from codex_harness.domain.model import ContractError, require, utcnow

HISTORY_TABLE = 'schema_migrations'
HISTORY_DDL = f"""CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (
    module text NOT NULL,
    version text NOT NULL,
    checksum text NOT NULL,
    name text NOT NULL,
    tool text NOT NULL,
    applied_at text NOT NULL,
    applied_by text NOT NULL,
    PRIMARY KEY (module, version)
)"""
LOCK = 734219  # the same control-plane lock as PostgresStore.transaction / migrate


def _observe(path):
    if not path.exists():
        return {'state': 'missing', 'files': [], 'error': 'path does not exist'}
    try:
        entries = sorted(p for p in path.iterdir())
    except OSError as exc:
        return {'state': 'unreadable', 'files': [], 'error': type(exc).__name__ + ': ' + str(exc)[:200]}
    files = []
    for entry in entries:
        if not entry.is_file():
            continue
        record = {'name': entry.name, 'bytes': 0, 'checksum': None, 'error': None}
        try:
            data = entry.read_bytes()
            record['bytes'] = len(data)
            record['checksum'] = 'sha256:' + hashlib.sha256(data).hexdigest()
            if entry.name.lower().endswith('.sql'):
                data.decode('utf-8')
        except OSError as exc:
            record['error'] = 'unreadable: ' + type(exc).__name__
        except UnicodeDecodeError as exc:
            record['error'] = 'parse_error: ' + type(exc).__name__ + ' at byte ' + str(exc.start)
        files.append(record)
    return {'state': 'found', 'files': files, 'error': None}


def discover(config, root):
    """Every configured location on the real filesystem, keyed by module/vendor/path."""
    config = parse_config(config)
    root = Path(root)
    require(root.is_dir(), 'Migration root must be a directory')
    return {f"{loc['module']}/{loc['vendor']}/{loc['path']}": _observe(root / loc['path']) for loc in config['locations']}


def _sources(config, root):
    """Bytes of every target-vendor file by (module, name) (only called after discovery succeeded)."""
    sources = {}
    for loc in parse_config(config)['locations']:
        if loc['vendor'] != config['target_vendor']:
            continue
        folder = Path(root) / loc['path']
        if folder.is_dir():
            for entry in folder.iterdir():
                if entry.is_file() and entry.name.endswith('.sql'):
                    sources[(loc['module'], entry.name)] = entry.read_bytes()
    return sources


class Migrator:
    def __init__(self, dsn, config, root):
        self.dsn, self.config, self.root = dsn, parse_config(config), Path(root)

    @staticmethod
    def history(conn):
        conn.execute(HISTORY_DDL)
        return [{'module': row[0], 'version': row[1], 'checksum': row[2], 'name': row[3], 'tool': row[4], 'applied_at': row[5]} for row in
                conn.execute(f"SELECT module, version, checksum, name, tool, applied_at FROM {HISTORY_TABLE} ORDER BY module, version").fetchall()]

    @staticmethod
    def live_tables(conn):
        return [row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ANY(current_schemas(false)) ORDER BY table_name").fetchall()]

    def _evaluate(self, conn):
        return evaluate(self.config, discover(self.config, self.root), self.history(conn), self.live_tables(conn))

    def precheck(self):
        """Read-only: files, history and schema as they are now."""
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute(f"SELECT pg_advisory_xact_lock({LOCK})")
            plan = self._evaluate(conn)
            conn.rollback()
        return plan

    def apply(self, applied_by='zeus'):
        """Re-evaluate under the lock, then apply pending versions and record each in the same transaction."""
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute(f"SELECT pg_advisory_xact_lock({LOCK})")
            plan = self._evaluate(conn)
            plan['results']['schema'] = 'deferred'  # the schema is verified after apply, not before
            blocking = {k: v for k, v in plan['results'].items() if v not in {'ok', 'not_applicable', 'deferred'}}
            if blocking:
                conn.rollback()
                raise ContractError('Migration refused: ' + ', '.join(f'{k}={v}' for k, v in sorted(blocking.items())))
            sources = _sources(self.config, self.root)
            by_key = {(f['module'], f['version']): f for f in plan['content']['files']}
            applied = []
            for item in plan['history']['pending']:
                entry = by_key[(item['module'], item['version'])]
                data = sources[(item['module'], entry['name'])]
                require('sha256:' + hashlib.sha256(data).hexdigest() == entry['checksum'], f'{entry["name"]} changed between precheck and apply')
                conn.execute(data.decode('utf-8'))
                conn.execute(f"INSERT INTO {HISTORY_TABLE}(module, version, checksum, name, tool, applied_at, applied_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                             (item['module'], item['version'], entry['checksum'], entry['name'], f"{TOOL['name']}@{TOOL['version']}", utcnow(), applied_by))
                applied.append({'module': item['module'], 'version': item['version']})
            missing = sorted(set(self.config['expected_tables']) - set(self.live_tables(conn)))
            if missing:
                conn.rollback()
                raise ContractError('Schema verification failed after apply: missing ' + ', '.join(missing))
            conn.commit()
            history = self.history(conn)
        return {'applied': applied, 'already_applied': [{'module': r['module'], 'version': r['version']} for r in history
                                                        if {'module': r['module'], 'version': r['version']} not in applied],
                'history': history, 'tool': TOOL, 'config_hash': self.config['config_hash'], 'schema_verified': self.config['expected_tables']}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='codex_harness.adapters.migrations')
    parser.add_argument('operation', choices=['precheck', 'apply'])
    parser.add_argument('--config', required=True, help='JSON file with version, target_vendor, locations, expected_tables')
    parser.add_argument('--root', required=True)
    parser.add_argument('--dsn-env', default='ZEUS_DATABASE_URL')
    parser.add_argument('--applied-by', default='zeus')
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.dsn_env)
    try:
        require(bool(dsn), f'{args.dsn_env} is not set')
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        migrator = Migrator(dsn, config, args.root)
        if args.operation == 'precheck':
            plan = migrator.precheck()
            print(json.dumps({'operation': 'precheck', 'tool': TOOL, 'plan': plan}, sort_keys=True))
            if not plan['apply_allowed']:
                print('precheck refused: ' + ', '.join(f'{k}={v}' for k, v in sorted(plan['results'].items()) if v not in {'ok', 'not_applicable'}), file=sys.stderr)
                return 1
            return 0
        receipt = migrator.apply(args.applied_by)
        print(json.dumps({'operation': 'apply', 'tool': TOOL, 'receipt': receipt}, sort_keys=True))
        return 0
    except ContractError as exc:
        print(json.dumps({'operation': args.operation, 'tool': TOOL, 'refused': str(exc)}, sort_keys=True))
        print('refused: ' + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # an error is neither success nor refusal; it is named and exits non-zero
        print(json.dumps({'operation': args.operation, 'tool': TOOL, 'error': type(exc).__name__ + ': ' + str(exc)[:500]}, sort_keys=True))
        print('error: ' + type(exc).__name__ + ': ' + str(exc)[:500], file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
