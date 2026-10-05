# Ported from SOURCE M7 tests/test_runtime_projection.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
import json

from codex_harness.knowledge.adapters.postgres_knowledge import PostgresKnowledge
from codex_harness.routing.adapters.organization_source import packaged_organization as organization
from codex_harness.storage.adapters.memory_store import MemoryStore


def test_blocked_decision_is_projected_with_owner_and_evidence(monkeypatch):
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            statements.append((sql, params))

    # S11 M B3: the target module that looks psycopg up
    monkeypatch.setattr('codex_harness.knowledge.adapters.postgres_knowledge.psycopg.connect', lambda _: Connection())
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
