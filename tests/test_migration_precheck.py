"""FA-031: a pinned migration tool, a closed filename contract, identified locations, four separate results, immutable
applied versions and receipts bound to the real process (INV-MIGRATION-001).

The upstream Flyway collision checker compared the first number only, overwrote earlier modules' vendor lists,
exited 0 after an arithmetic error on V08, reported an unreadable folder as success and never listed the files.
"""
import json
import os
import subprocess
import sys

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.migrations import HISTORY_TABLE, Migrator, discover
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.migration_receipts import BUCKET, MigrationReceipts
from codex_harness.domain.migrations import (
    TOOL,
    classify_location,
    evaluate,
    parse_config,
    parse_version,
)
from codex_harness.domain.model import ContractError, utcnow

CONFIG = {'version': 1, 'target_vendor': 'postgres', 'expected_tables': ['documents', 'ledger'],
          'locations': [{'module': 'core', 'vendor': 'postgres', 'path': 'core/postgres'},
                        {'module': 'core', 'vendor': 'mysql', 'path': 'core/mysql'},
                        {'module': 'billing', 'vendor': 'postgres', 'path': 'billing/postgres'},
                        {'module': 'billing', 'vendor': 'mysql', 'path': 'billing/mysql', 'required': False}]}


def layout(root, files):
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body if isinstance(body, bytes) else body.encode('utf-8'))


def test_version_normalization_is_pinned_and_unsupported_names_are_refused_not_skipped():
    assert TOOL['name'] == 'zeus-sql-migrator' and TOOL['version'] == 1
    assert parse_version('001.sql')['version'] == [1] == parse_version('V1__init.sql')['version'] == parse_version('V01__init.sql')['version']
    assert parse_version('V1_2__x.sql')['version'] == [1, 2] == parse_version('V1.2__x.sql')['version'], 'underscore and dot are the same separator'
    assert parse_version('V1.0__x.sql')['label'] == '1' and parse_version('V1.0.1__x.sql')['label'] == '1.0.1'
    assert parse_version('V08__eight.sql')['version'] == [8], 'zero padding is not octal'
    assert parse_version('V10__ten.sql')['version'] > parse_version('V9__nine.sql')['version'], 'numeric, not lexical'
    assert parse_version('V1.10__x.sql')['version'] > parse_version('V1.9__x.sql')['version'], 'composite versions compare component-wise'
    for bad, reason in (('init.sql', 'unsupported name'), ('V1__x.SQL', 'only lowercase .sql'), ('1a.sql', 'unsupported name'),
                        ('V1__.sql', 'unsupported name'), ('V1__x.txt', 'only lowercase .sql'), ('V1_.sql', 'unsupported name')):
        with pytest.raises(ContractError, match=reason):
            parse_version(bad)


def test_locations_are_identified_and_states_are_distinct(tmp_path):
    layout(tmp_path, {'core/postgres/V1__init.sql': 'CREATE TABLE t (id int);', 'core/postgres/V2__more.sql': 'ALTER TABLE t ADD c int;',
                      'core/postgres/notes.md': 'x', 'core/mysql/V1__init.sql': 'CREATE TABLE t (id int);',
                      'billing/postgres/V1__b.sql': 'select 1;'})
    (tmp_path / 'billing/mysql').write_text('not a directory')
    observations = discover(CONFIG, tmp_path)
    assert set(observations) == {'core/postgres/core/postgres', 'core/mysql/core/mysql', 'billing/postgres/billing/postgres', 'billing/mysql/billing/mysql'}
    assert observations['billing/mysql/billing/mysql']['state'] == 'unreadable' and 'NotADirectoryError' in observations['billing/mysql/billing/mysql']['error']
    plan = evaluate(CONFIG, observations, history=[], live_tables=['documents', 'ledger'])
    by_key = {(loc['module'], loc['vendor']): loc for loc in plan['locations']}
    assert by_key[('core', 'postgres')]['state'] == 'found' and by_key[('core', 'postgres')]['ignored'] == ['notes.md']
    assert by_key[('billing', 'mysql')]['state'] == 'unreadable' and by_key[('billing', 'mysql')]['status'] == 'not_applicable', 'optional scope'
    assert plan['results']['locations'] == 'ok'
    # Earlier modules keep their vendor lists (upstream overwrote them with the last module's).
    assert plan['filenames']['scopes']['core/postgres']['versions'] == ['1', '2'] and plan['filenames']['scopes']['billing/postgres']['versions'] == ['1']
    # Parity is a separate result: core/mysql lacks version 2; billing has one vendor -> not applicable, not ok.
    assert plan['results']['parity'] == 'refused' and plan['parity']['modules']['core']['missing'] == {'mysql': ['2']}
    assert plan['parity']['modules']['billing'] == {'status': 'not_applicable', 'vendors': ['postgres'], 'unobserved': ['mysql']}
    assert plan['results']['content'] == 'ok' and plan['results']['history'] == 'ok' and plan['results']['schema'] == 'ok'
    assert plan['apply_allowed'] is False and plan['pending'] == []
    # A required location that is missing refuses; an undiscovered required scope is unknown, never approval.
    os_missing = evaluate(CONFIG, {k: v for k, v in observations.items() if not k.startswith('core/mysql')}, history=[], live_tables=[])
    core_mysql = next(loc for loc in os_missing['locations'] if loc['vendor'] == 'mysql' and loc['module'] == 'core')
    assert core_mysql['state'] == 'unknown' and core_mysql['status'] == 'refused' and 'not approval' in core_mysql['error']
    gone = discover(CONFIG, tmp_path)
    gone['core/mysql/core/mysql'] = {'state': 'missing', 'files': [], 'error': 'path does not exist'}
    assert evaluate(CONFIG, gone, [], [])['results']['locations'] == 'refused'
    assert evaluate(CONFIG, gone, [], [])['parity']['modules']['core']['status'] == 'unknown', 'a required vendor that was not observed makes parity unknown'
    # Declared empty and required-but-empty differ.
    empty = classify_location({'module': 'm', 'vendor': 'postgres', 'path': 'p', 'required': True, 'allow_empty': True}, {'state': 'found', 'files': []})
    assert empty['state'] == 'empty' and empty['status'] == 'ok'
    empty_required = classify_location({'module': 'm', 'vendor': 'postgres', 'path': 'p', 'required': True, 'allow_empty': False}, {'state': 'found', 'files': []})
    assert empty_required['status'] == 'refused'
    # History and schema not read are unknown, and unknown is not approval.
    unknown = evaluate(CONFIG, observations)
    assert unknown['results']['history'] == 'unknown' and unknown['results']['schema'] == 'unknown' and not unknown['apply_allowed']
    for bad in ({'version': 1, 'target_vendor': 'oracle', 'locations': CONFIG['locations']},
                {'version': 1, 'target_vendor': 'postgres', 'locations': []},
                {'version': 1, 'target_vendor': 'postgres', 'locations': [{'module': 'core', 'vendor': 'postgres', 'path': '../x'}]},
                {'version': 1, 'target_vendor': 'postgres', 'locations': [{'module': 'core', 'vendor': 'mysql', 'path': 'x'}]},
                {'version': 1, 'target_vendor': 'postgres', 'locations': CONFIG['locations'][:1] * 2}):
        with pytest.raises(ContractError):
            parse_config(bad)


def test_duplicates_list_every_file_and_unsupported_or_undecodable_files_refuse(tmp_path):
    layout(tmp_path, {'core/postgres/V1__a.sql': 'select 1;', 'core/postgres/V01__b.sql': 'select 2;', 'core/postgres/V1.0__c.sql': 'select 3;',
                      'core/postgres/V2__ok.sql': 'select 4;', 'core/postgres/legacy.sql': 'select 5;', 'core/postgres/V3__bad.sql': b'select \xff;',
                      'core/postgres/V4__empty.sql': b'', 'core/mysql/V1__a.sql': 'x', 'core/mysql/V2__ok.sql': 'x', 'core/mysql/V3__bad.sql': 'x',
                      'core/mysql/V4__empty.sql': 'x', 'billing/postgres/V1__b.sql': 'x'})
    plan = evaluate(CONFIG, discover(CONFIG, tmp_path), history=[], live_tables=['documents', 'ledger'])
    assert plan['filenames']['scopes']['core/postgres']['duplicates'] == {'1': ['V01__b.sql', 'V1.0__c.sql', 'V1__a.sql']}, 'every colliding file is listed'
    core = next(loc for loc in plan['locations'] if loc['module'] == 'core' and loc['vendor'] == 'postgres')
    assert core['refused_names'] == ['legacy.sql: unsupported name; contract is ' + TOOL['filename_contract']]
    assert plan['results']['filenames'] == 'refused' and plan['results']['locations'] == 'refused'
    problems = {f['name']: f['problem'] for f in plan['content']['files'] if f['problem']}
    assert problems == {'V3__bad.sql': 'parse_error: UnicodeDecodeError at byte 7', 'V4__empty.sql': 'empty file'}
    assert plan['results']['content'] == 'refused' and plan['denominator']['files_refused'] == 1 and plan['denominator']['files_supported'] == 11


def test_applied_versions_are_immutable_and_new_versions_reconcile_with_the_real_history(tmp_path, isolated_pgstore):
    root = tmp_path / 'migrations'
    config = {'version': 1, 'target_vendor': 'postgres', 'expected_tables': ['documents', 'ledger', HISTORY_TABLE],
              'locations': [{'module': 'ledger', 'vendor': 'postgres', 'path': 'core'}]}
    layout(root, {'core/V1__ledger.sql': 'CREATE TABLE ledger (id text PRIMARY KEY, amount_cents bigint NOT NULL);'})
    migrator = Migrator(isolated_pgstore.dsn, config, root)
    before = migrator.precheck()
    assert before['results'] == {'locations': 'ok', 'filenames': 'ok', 'parity': 'not_applicable', 'content': 'ok', 'history': 'ok', 'schema': 'refused'}
    assert before['schema']['missing'] == ['ledger'] and before['history']['pending'] == [{'module': 'ledger', 'version': '1', 'name': 'V1__ledger.sql'}]
    assert not before['apply_allowed']
    assert before['history']['foreign_modules'] == ['core'], 'the fixture bootstrap (001.sql) is history of another module, listed and not judged'
    receipt = migrator.apply('tester')
    assert receipt['applied'] == [{'module': 'ledger', 'version': '1'}]
    row = next(r for r in receipt['history'] if r['module'] == 'ledger')
    assert row['tool'] == 'zeus-sql-migrator@1' and row['checksum'].startswith('sha256:') and row['name'] == 'V1__ledger.sql'
    assert receipt['already_applied'] == [{'module': 'core', 'version': '1'}]
    after = migrator.precheck()
    assert after['results']['history'] == 'ok' and after['results']['schema'] == 'ok' and after['apply_allowed'] and after['pending'] == []
    assert migrator.apply('tester')['applied'] == [], 'idempotent'
    # Editing an applied file is refused; nothing else is applied.
    layout(root, {'core/V1__ledger.sql': 'CREATE TABLE ledger (id text PRIMARY KEY, amount_cents bigint NOT NULL); -- edited',
                  'core/V2__index.sql': 'CREATE INDEX ledger_amount ON ledger (amount_cents);'})
    modified = migrator.precheck()
    assert modified['results']['history'] == 'refused' and modified['history']['problems'][0]['problem'] == 'applied version modified'
    with pytest.raises(ContractError, match='Migration refused: history=refused'):
        migrator.apply('tester')
    assert migrator.precheck()['history']['applied'] == {'ledger': ['1']}, 'nothing applied after a refusal'
    layout(root, {'core/V1__ledger.sql': 'CREATE TABLE ledger (id text PRIMARY KEY, amount_cents bigint NOT NULL);'})
    assert migrator.apply('tester')['applied'] == [{'module': 'ledger', 'version': '2'}]
    # A new version lower than an applied one is out of order, not "MAX+1 will do".
    layout(root, {'core/V1.5__late.sql': 'select 1;'})
    late = migrator.precheck()
    assert late['results']['history'] == 'refused' and late['history']['problems'] == [
        {'module': 'ledger', 'version': '1.5', 'problem': 'out of order: lower than an applied version', 'file': 'V1.5__late.sql'}]
    (root / 'core/V1.5__late.sql').unlink()
    # An applied version whose file disappeared cannot be verified.
    (root / 'core/V2__index.sql').rename(root / 'core/V2__renamed.sql')
    assert migrator.precheck()['results']['history'] == 'ok', 'a rename with the same bytes keeps the version and checksum'
    (root / 'core/V2__renamed.sql').unlink()
    assert migrator.precheck()['history']['problems'][0]['problem'].startswith('applied version has no file')
    # A file that fails when applied leaves no history row and no partial schema.
    layout(root, {'core/V2__index.sql': 'CREATE INDEX ledger_amount ON ledger (amount_cents);', 'core/V3__broken.sql': 'CREATE TABLE broken (;'})
    with pytest.raises(Exception):
        migrator.apply('tester')
    assert migrator.precheck()['history']['applied'] == {'ledger': ['1', '2']} and 'broken' not in migrator.precheck()['schema']['observed']


def _child(operation, config_path, root, dsn, applied_by):
    env = {**os.environ, 'ZEUS_DATABASE_URL': dsn, 'PYTHONIOENCODING': 'utf-8'}
    argv = [sys.executable, '-m', 'codex_harness.adapters.migrations', operation, '--config', str(config_path), '--root', str(root), '--applied-by', applied_by]
    started = utcnow()
    run = subprocess.run(argv, capture_output=True, env=env, timeout=120)
    return {'argv': argv, 'stdout': run.stdout, 'stderr': run.stderr, 'exit_code': run.returncode, 'started_at': started, 'finished_at': utcnow()}


def test_concurrent_apply_records_each_version_once_and_receipts_bind_the_process(tmp_path, isolated_pgstore):
    root = tmp_path / 'migrations'
    config = {'version': 1, 'target_vendor': 'postgres', 'expected_tables': ['documents', 'ledger', HISTORY_TABLE],
              'locations': [{'module': 'ledger', 'vendor': 'postgres', 'path': 'core'}]}
    layout(root, {'core/V1__ledger.sql': 'CREATE TABLE ledger (id text PRIMARY KEY);', 'core/V2__col.sql': 'ALTER TABLE ledger ADD amount_cents bigint;'})
    config_path = tmp_path / 'migrations.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    config_hash = parse_config(config)['config_hash']
    binding = {'config_hash': config_hash, 'root': str(root), 'source_revision': 'c' * 40, 'environment': 'windows-11'}
    receipts = MigrationReceipts(isolated_pgstore, FileArtifacts(str(tmp_path / 'artifacts')))
    precheck = _child('precheck', config_path, root, isolated_pgstore.dsn, 'a')
    row = receipts.record({'operation': 'precheck', **binding, **precheck})
    assert row['exit_code'] == 1 and row['outcome'] == 'completed' and row['apply_allowed'] is False and row['results']['schema'] == 'refused'
    assert row['tool_pinned'] and b'precheck refused: schema=refused' in precheck['stderr']
    with isolated_pgstore.transaction() as tx:
        with pytest.raises(ContractError, match='did not allow apply: schema=refused'):
            receipts.require_approved(tx, row['id'], source_revision='c' * 40, environment='windows-11')
    env = {**os.environ, 'ZEUS_DATABASE_URL': isolated_pgstore.dsn, 'PYTHONIOENCODING': 'utf-8'}
    children = [subprocess.Popen([sys.executable, '-m', 'codex_harness.adapters.migrations', 'apply', '--config', str(config_path), '--root', str(root),
                                  '--applied-by', name], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for name in ('left', 'right')]
    outputs = [child.communicate(timeout=120) for child in children]
    documents = [json.loads(out.decode('utf-8')) for out, _ in outputs]
    assert [child.returncode for child in children] == [0, 0], outputs
    applied = [doc['receipt']['applied'] for doc in documents]
    assert sorted(applied, key=len) == [[], [{'module': 'ledger', 'version': '1'}, {'module': 'ledger', 'version': '2'}]], 'exactly one process applied each version'
    with isolated_pgstore.transaction() as tx:
        rows = tx.conn.execute(f"SELECT version, applied_by FROM {HISTORY_TABLE} WHERE module = 'ledger' ORDER BY version").fetchall()
    assert [r[0] for r in rows] == ['1', '2'] and len({r[1] for r in rows}) == 1
    approved = receipts.record({'operation': 'precheck', **binding, **_child('precheck', config_path, root, isolated_pgstore.dsn, 'a')})
    assert approved['exit_code'] == 0 and approved['apply_allowed'] is True and approved['results']['history'] == 'ok'
    with isolated_pgstore.transaction() as tx:
        assert receipts.require_approved(tx, approved['id'], source_revision='c' * 40, environment='windows-11')['id'] == approved['id']
        with pytest.raises(ContractError, match='another revision or environment'):
            receipts.require_approved(tx, approved['id'], source_revision='d' * 40, environment='windows-11')
        assert receipts.artifacts.document(approved['stdout_ref'])['raw'].encode('latin-1').startswith(b'{"operation": "precheck"')
        assert len(tx.scan(BUCKET)) == 2
    # An errored run (unset DSN) is recorded as an error with exit 2, not as success.
    broken = _child('precheck', config_path, root, '', 'a')
    errored = receipts.record({'operation': 'precheck', **binding, **broken})
    assert errored['exit_code'] == 1 and errored['outcome'] == 'refused' and b'ZEUS_DATABASE_URL is not set' in broken['stderr']
    unreachable = _child('precheck', config_path, root, 'postgresql://nobody@127.0.0.1:1/none?connect_timeout=1', 'a')
    assert unreachable['exit_code'] == 2 and unreachable['stderr'].startswith(b'error: ') and b'timeout' in unreachable['stderr'].lower()
    assert receipts.record({'operation': 'precheck', **binding, **unreachable})['outcome'] == 'error'
    for bad in ({**binding, 'source_revision': 'HEAD'}, {**binding, 'environment': ''}, {**binding, 'config_hash': 'short'}):
        with pytest.raises(ContractError):
            receipts.record({'operation': 'precheck', **bad, **precheck})
    apply_row = receipts.record({'operation': 'apply', **binding, **precheck})
    with isolated_pgstore.transaction() as tx:
        with pytest.raises(ContractError, match='Only a precheck'):
            receipts.require_approved(tx, apply_row['id'], source_revision='c' * 40, environment='windows-11')


def test_memory_store_receipts_do_not_need_postgres(tmp_path):
    receipts = MigrationReceipts(MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts')))
    row = receipts.record({'operation': 'precheck', 'argv': ['x'], 'config_hash': 'a' * 64, 'root': 'r', 'source_revision': 'unversioned',
                           'environment': 'ci', 'stdout': b'not json', 'stderr': b'', 'exit_code': 0, 'started_at': utcnow(), 'finished_at': utcnow()})
    assert row['outcome'] == 'unparseable' and row['tool_pinned'] is False and row['apply_allowed'] is False
    with MemoryStore().transaction() as tx:
        with pytest.raises(ContractError, match='missing'):
            receipts.require_approved(tx, row['id'], source_revision='unversioned', environment='ci')
