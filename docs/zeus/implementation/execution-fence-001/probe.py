"""FA-003 reproduction against Zeus: the upstream lease ABA shapes, run on the real Workflow.

Each variant runs the same two scenarios on a MemoryStore (and on PostgreSQL when
ZEUS_PROBE_DSN is set): (1) an expired holder acting after another owner reclaimed the
task, (2) a purged task row recreated from generation 0. Variants weaken one binding at
a time so the receipt shows which binding rejects which action; only "current" is shipped.
Usage: uv run python docs/zeus/implementation/execution-fence-001/probe.py [output.json]
"""
import contextlib
import json
import os
import platform
import sys
import time
from pathlib import Path

import psycopg

from codex_harness.adapters.store import MemoryStore, PostgresStore
from codex_harness.application import workflow as workflow_module
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope

ROOT = Path(__file__).resolve().parents[4]


def assignment():
    return envelope('task.assign', 'lead:improvement', 'worker:implementation', 'implement',
                    {'objective': 'probe'}, 'probe-correlation')


def attempt(action):
    try:
        action()
        return 'accepted'
    except ContractError as exc:
        return 'rejected: ' + str(exc)


def purge(store, row_id):
    if isinstance(store, MemoryStore):
        del store.data['tasks', row_id]
    else:
        with psycopg.connect(store.dsn) as conn:
            conn.execute("DELETE FROM documents WHERE bucket='tasks' AND id=%s", (row_id,))


@contextlib.contextmanager
def weakened(variant):
    original = Workflow._same_execution
    fence = (workflow_module.advance_fence, workflow_module.require_unused_fence)
    try:
        if variant in {'owner_blind', 'generation_blind'}:
            skipped = 'lease_owner' if variant == 'owner_blind' else 'generation'

            def blind(current, task):
                return original({**current, skipped: None}, {**task, skipped: None})
            Workflow._same_execution = staticmethod(blind)
        if variant == 'no_fence':
            workflow_module.advance_fence = lambda *a, **k: None
            workflow_module.require_unused_fence = lambda *a, **k: None
        yield
    finally:
        Workflow._same_execution = staticmethod(original)
        workflow_module.advance_fence, workflow_module.require_unused_fence = fence


def scenarios(store):
    w = Workflow(store, organization())
    task = w.submit(assignment())
    first = w.claim('worker:implementation', 'first-owner', lease_seconds=1)
    time.sleep(1.2)
    second = w.claim('worker:implementation', 'second-owner', lease_seconds=60)
    aba = {'reclaimed_generation': second['generation'],
           'stale_heartbeat': attempt(lambda: w.heartbeat(first)),
           'stale_complete': attempt(lambda: w.complete(first, {'summary': 'stale'})),
           'stale_with_spoofed_generation': attempt(lambda: w.heartbeat({**first, 'generation': second['generation']}))}
    with store.transaction() as tx:
        row = tx.get('tasks', task['id'])
    purge(store, task['id'])
    message = task['message']
    recreated = {'resubmit_after_purge': attempt(lambda: w.submit(message))}
    with store.transaction() as tx:
        tx.put('tasks', task['id'], {**row, 'status': 'queued', 'generation': 0, 'attempt': 0,
                                     'lease_owner': None, 'lease_until': None})
    # The upstream file lease re-issued epoch 1 to the same owner string; Zeus executors use a
    # fresh uuid4 per claim, so owner reuse here is the adversarial worst case, not normal traffic.
    claimed = w.claim('worker:implementation', 'first-owner', lease_seconds=60)
    with store.transaction() as tx:
        after = tx.get('tasks', task['id'])
    recreated['claim_of_recreated_row_with_reused_owner'] = (
        'accepted with generation %d attempt %d' % (claimed['generation'], claimed['attempt'])
        if claimed else 'rejected: ' + str(after['error']))
    recreated['old_first_holder_after_recreation'] = attempt(lambda: w.heartbeat(first))
    recreated['old_second_holder_after_recreation'] = attempt(lambda: w.heartbeat(second))
    return {'expired_holder': aba, 'recreated_row': recreated}


@contextlib.contextmanager
def isolated_schema(dsn):
    """Same shape as the test fixture: a throwaway schema, never the operator's public tables."""
    from uuid import uuid4

    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    schema = 'probe_' + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        store = PostgresStore(make_conninfo(dsn, options=f'-c search_path={schema},public'))
        store.migrate()
        yield store, schema
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def main():
    dsn = os.environ.get('ZEUS_PROBE_DSN')
    receipt = {'python': sys.version, 'os': platform.platform(),
               'scope': 'Real Workflow on MemoryStore' + (' and a throwaway PostgreSQL schema' if dsn else '')
                        + '; weakened variants are probe-only patches, not shipped code.',
               'variants': {}}
    for variant in ('current', 'owner_blind', 'generation_blind', 'no_fence'):
        receipt['variants'][variant] = {}
        with weakened(variant):
            receipt['variants'][variant]['memory'] = scenarios(MemoryStore())
            if dsn:
                with isolated_schema(dsn) as (store, schema):
                    receipt['variants'][variant]['postgres'] = scenarios(store)
                    receipt['variants'][variant]['postgres']['schema'] = schema
    text = json.dumps(receipt, ensure_ascii=False, indent=2) + '\n'
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding='utf-8')
    sys.stdout.buffer.write(text.encode('utf-8'))


if __name__ == '__main__':
    main()
