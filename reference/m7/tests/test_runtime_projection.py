import json

from codex_harness.adapters.knowledge import PostgresKnowledge
from codex_harness.adapters.store import MemoryStore
from codex_harness.bootstrap import organization


def test_blocked_decision_is_projected_with_owner_and_evidence(monkeypatch):
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            statements.append((sql, params))

    monkeypatch.setattr('codex_harness.adapters.knowledge.psycopg.connect', lambda _: Connection())
    store = MemoryStore()
    decision = {'id': 'review', 'actor': 'lead:improvement', 'status': 'inspection_blocked',
                'result': {'accepted': False, 'execution_ref': 'sha256:fixture'}}
    knowledge = PostgresKnowledge('fixture')
    before = knowledge.project_runtime(store, organization())
    with store.transaction() as tx:
        tx.put('decisions_pending', 'review', decision)
    after = knowledge.project_runtime(store, organization())
    assert before['snapshot'] != after['snapshot']
    node = next(params for sql, params in statements if sql.startswith('INSERT INTO knowledge_nodes')
                and params[0] == 'runtime:decisions_pending:review')
    assert json.loads(node[2]) == decision
    assert node[3] == 'postgres:decisions_pending/review'
    assert node[5].obj['authority'] == 'PostgreSQL'
    assert any(params == ('runtime:agent:lead:improvement', 'runtime:decisions_pending:review', 'owns')
               for sql, params in statements if sql.startswith('INSERT INTO knowledge_edges'))
