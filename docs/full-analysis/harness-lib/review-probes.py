"""Synthetic edge probes against unmodified pinned source. PASS means reproduced observation, not safety."""
from pathlib import Path
import concurrent.futures
import datetime
import json
import math
import os
import sys
import tempfile
import threading

sys.path.insert(0, '/source/scripts')
from lib import (agent_depth, arming, atomic_jsonl, code_context, completion_line,
                 debate_rules, decomposition, derive_state, evaluator, evidence_freshness,
                 idempotency, lease, ledger, ownership_events, ownership_vitals, params,
                 preconditions, repro_probe, research_digest, seams, suite_floor)

findings = []
def observe(name, fn):
    try:
        data = fn()
        findings.append({'probe': name, 'observation': data, 'probe_error': None})
    except Exception as exc:
        findings.append({'probe': name, 'observation': None,
                         'probe_error': f'{type(exc).__name__}: {exc}'})

def event(kind, **payload):
    return {'event': kind, 'payload': payload}

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    os.environ['HARNESS_STATE_DIR'] = str(root / 'state')
    os.environ['HARNESS_HOME'] = str(root)
    (root / 'scripts').mkdir()
    (root / 'scripts/example.py').write_text('value=1\n')

    def aba():
        f = root / 'lease.json'
        old = lease.acquire(f, 'old')
        f.unlink()
        new = lease.acquire(f, 'new')
        lease.guard(f, old)
        lease.release(f, old)
        return {'old_epoch': old['epoch'], 'new_epoch': new['epoch'],
                'different_owner': old['owner'] != new['owner'], 'old_guard_accepted': True,
                'old_release_changed_new_state': lease.inspect(f)['state']}
    observe('lease_deleted_reissued_ABA', aba)

    def same_key_race():
        f = root / 'idempotency.jsonl'
        barrier = threading.Barrier(2)
        original = idempotency.already_done
        def read_before_both_appends(*args, **kwargs):
            answer = original(*args, **kwargs)
            barrier.wait(timeout=5)
            return answer
        idempotency.already_done = read_before_both_appends
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                answers = list(pool.map(lambda sid: idempotency.once(
                    'same-key', 'inert-no-external-action', session_id=sid, ledger_file=f), ['one', 'two']))
        finally:
            idempotency.already_done = original
        return {'both_allowed': answers, 'durable_events': len(ledger.read_events(f)),
                'scheduling': 'barrier only after actual reads, real append locking unchanged'}
    observe('idempotency_concurrent_check_append', same_key_race)

    def error_after_pass():
        rows = [event('gate_verdict', stage='s', verdict=v) for v in ['PASS', 'ERROR']]
        return {'stage_state': derive_state.derive_stage_states(rows)['s']['state'],
                'completed': sorted(derive_state.derive_completed(rows))}
    observe('derive_PASS_then_ERROR', error_after_pass)

    def spaced_id():
        f = root / 'spaced.jsonl'
        f.write_text(json.dumps({'id': 'same.0', 'event': 'dispatch', 'payload': {}}) + '\n')
        appended = ledger.append_event('dispatch', {}, session_id='same', ledger_file=f)
        return {'existing_id': 'same.0', 'new_id': appended['id']}
    observe('ledger_existing_standard_json_spacing', spaced_id)

    observe('arming_unknown_grade', lambda: arming._grade_gate(
        {'target_project': 'scripts/example.py'}, lambda ps, h: {p: 'unknown-grade' for p in ps}, root))
    observe('malformed_agent_depth', lambda: {'bad': agent_depth.current_depth({'ORCH_DEPTH': 'broken'}),
                                            'negative': agent_depth.current_depth({'ORCH_DEPTH': '-9'})})
    observe('future_evidence', lambda: evidence_freshness.assess(
        'measured 2099-01-01', today=datetime.date(2026, 9, 9)))
    observe('unknown_repro_crystallizable', lambda: {'assessment': repro_probe.classify_family([], 's', 'x'),
        'allowed': repro_probe.crystallizable(repro_probe.classify_family([], 's', 'x'))})
    observe('synthetic_ownership_denominator', lambda: ownership_vitals.vitals(
        {'c': 'a'}, [event('dispatch', role='a', synthetic=True)]))
    observe('nonfinite_timeout_schema', lambda: ownership_events.judge_wakeup_timeout(
        {'wakeup_id': 'w', 'deadline_s': float('nan')}))
    observe('unrecorded_preconditions', lambda: preconditions.changed(None, {'important': 'changed'}))

    def numeric_policy():
        f = root / 'params.json'
        f.write_text('{"minimum":{"value":5,"tighten":"increase"}}')
        old_registry, old_fallback = params._registry_file, params.fallback_status
        params._registry_file, params.fallback_status = lambda: f, lambda: None
        try:
            answer = params.set_param('minimum', float('nan'))
            return {'accepted_nan': math.isnan(answer['value']), 'file_contains_NaN': 'NaN' in f.read_text()}
        finally:
            params._registry_file, params.fallback_status = old_registry, old_fallback
    observe('params_nonfinite_tightening', numeric_policy)

    def missing_state_promotion():
        evs = [event('gate_check', evidence={'query': 'q', 'status': seams.OK})]
        evs += [event('gate_check', evidence={'query': 'q', 'status': seams.OK, 'docs': {'a': 'hash'}})] * 2
        return seams.auto_promotion({}, evs, 'q')
    observe('seams_unknown_plus_known_doc_state', missing_state_promotion)
    observe('debate_first_gen_without_fields_or_critic', lambda: vars(debate_rules.evaluate_convergence(
        [event('debate_verdict', actor='architect', gen=1, verdict='approved')], 1)))

    def reduced_quorum():
        declared = [evaluator.JuryMember(n, 'family-' + n) for n in ['a', 'b', 'c']]
        vote = evaluator.JuryVote(member='a', family='family-a', verdict='approved', raw_verdict='approved', citations=3)
        solo = evaluator.decide_quorum([vote], declared=declared)
        duplicate = evaluator.decide_quorum([vote, vote], declared=declared)
        return {'solo': vars(solo), 'duplicate': vars(duplicate)}
    observe('evaluator_reduced_and_duplicate_electorate', reduced_quorum)

    def outside_evidence():
        project = root / 'project'; project.mkdir()
        (root / 'outside.txt').write_text('unrelated file')
        return completion_line.assess({'goal': 'g', 'included': [{'claim': 'outside proof', 'evidence': '../outside.txt'}],
                                       'excluded': ['x'], 'interpretation': 'i'}, project)
    observe('completion_outside_project_evidence', outside_evidence)

    def relative_cross():
        base = root / 'eng'; (base / 'a').mkdir(parents=True)
        (base / 'a/inner.py').write_text('from .. import b\n')
        (base / 'b.py').write_text('VALUE=1\n')
        return {k: sorted(v) for k, v in code_context.intra_edges(base, 'eng').items()}
    observe('code_context_parent_relative_import', relative_cross)

    def candidate_floor():
        base = root / 'floor'; (base / 'tests').mkdir(parents=True)
        (base / 'tests/test_one.py').write_text('assert True\n')
        (base / 'tests/test_two.py').write_text('assert False\n')
        before = suite_floor.floor_violation(base, 'tests/test_one.py')
        (base / 'tests/test_two.py').unlink()
        after = suite_floor.floor_violation(base, 'tests/test_one.py')
        return {'before_deletion': before, 'after_deletion': after}
    observe('suite_floor_candidate_deletion', candidate_floor)

print(json.dumps({'kind': 'synthetic_observations_not_safety_pass', 'findings': findings}, ensure_ascii=False, indent=2, default=str))
raise SystemExit(1 if any(f['probe_error'] for f in findings) else 0)
