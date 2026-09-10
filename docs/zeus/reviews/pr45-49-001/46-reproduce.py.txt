import json, sys, tempfile
from pathlib import Path
sys.path[:0] = ['C:/Users/rudtn/zeus-pr-review-46/src', 'C:/Users/rudtn/zeus-pr-review-46/tests']
from test_gate_verdicts import registered_iteration, runner, retraction, DEFINITION
from dataclasses import replace
from codex_harness.domain.gate_verdicts import fold_verdicts
with tempfile.TemporaryDirectory() as d:
    service, row = registered_iteration(Path(d))
    receipt = service.artifacts.put('arbitrary text, no process or human authentication', 'counterexample')['ref']
    doc = dict(statement_id='human_scope', stage='spec_discussion', verdict='PASS', origin='runner_receipt',receipt_ref=receipt,exit_status=0)
    result = service.record_gate_verdict(row['id'],doc)
    print(json.dumps({'scope':'controlled application counterexample, no human/provider or deployment', 'human_scope_runner_claim':result['gate']['statements']['human_scope'], 'release_authorized':result['release_authorized']}))
    service.human_provider = object()
    doc.update(origin='reviewer_decision',receipt_ref=None,exit_status=None,actor='claimed-human',authority='authenticated_provider')
    print(json.dumps({'unused_provider_object_accepted':service.record_gate_verdict(row['id'],doc)['gate']['statements']['human_scope']}))
events = [runner('a','PASS',1), replace(retraction('a',1,2),run_id='foreign-run')]
print(json.dumps({'foreign_retraction_changes_current_run':fold_verdicts(events,DEFINITION,'run-1',1)}))
