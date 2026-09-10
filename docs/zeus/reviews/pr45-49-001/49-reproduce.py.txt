import json, sys, tempfile
from pathlib import Path
sys.path[:0] = ['C:/Users/rudtn/zeus-pr-review-49/src', 'C:/Users/rudtn/zeus-pr-review-49/tests']
import pytest
from test_execution_progress import project, runtime_factory, completed, assignment
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.adapters.executor import Executor, IMPLEMENTATION
for bad in [{'method': [], 'params': {}}, {'method':'item/completed','params':{'item':'garbage'}}]:
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as patch:
        root, git, artifacts = project.__wrapped__(Path(d))
        store=MemoryStore(); service=Harness(store,organization()); executor=Executor(service,git,artifacts)
        executor.workflow.submit(assignment()); lease=executor.workflow.claim('worker:implementation','owner')
        patch.setattr('codex_harness.adapters.executor.AppServer',runtime_factory([completed('good'),bad],[]))
        error=None
        try: executor._run('worker:implementation',lease['id'],'Counterexample',{},str(root),IMPLEMENTATION,lease=lease)
        except Exception as exc: error=type(exc).__name__+': '+str(exc)
        with store.transaction() as tx: state=tx.get('execution_progress',lease['id'])
        print(json.dumps({'scope':'fixture event source through actual Executor and ledger; no actual model','input':bad,'error':error,'sequence':state.get('sequence'),'malformed_events':state.get('malformed_events',0),'last_event':state.get('last_event')}))
