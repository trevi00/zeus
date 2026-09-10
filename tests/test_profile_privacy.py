"""FA-032: the profile data flow is a versioned contract whose notice is entailed by the policy; consent binds to the
policy hash; records are minimized and scanned before model input; every rendered field is checked or named
unchecked; temporary bundles belong to their run (INV-PROFILE-001).

The upstream feature sampled content and project paths into a model-input file before any redaction, redacted only
`evidence` while rendering `evidence_quotes`, and printed "None detected" when the counter was zero.
All inputs here are synthetic sentinels; no real conversation, credential or model call is involved.
"""
import json
import os
import subprocess
import sys

import pytest

from codex_harness.adapters.profile_scratch import ProfileScratch
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.profile_flow import RUNS, ProfileFlow
from codex_harness.domain.model import ContractError
from codex_harness.domain.profile_privacy import (
    BLOCKING,
    KINDS,
    check_render,
    minimize,
    normalize_evidence,
    parse_consent,
    parse_policy,
    project_ref,
    scan,
)

PROJECT_WIN = 'C:\\Users\\sentinel-user\\work\\shop'
PROJECT_LINUX = '/home/sentinel-user/work/shop'
POLICY = {'version': 1, 'purpose': 'derive working-style preferences for prompt guidance',
          'fields': {'content': 'the preference signal itself', 'project_path': 'grouping by project, hashed before model input',
                     'kind': 'restrict to user messages'},
          'read_scope': {'kinds': ['user_message'], 'max_records': 50, 'max_chars': 300, 'projects': [PROJECT_WIN, PROJECT_LINUX]},
          'model': {'name': 'local-preference-model', 'transport': 'local'},
          'retention': {'temporary': 'run', 'permanent': 'profile_only'},
          'notice': {'text': 'Messages from the projects you pick are read locally; secrets and paths are excluded automatically; raw text is not kept.',
                     'claims': ['no_external_transfer', 'automatic_exclusion', 'raw_not_retained']}}


def consent(policy, choice='grant', projects=(PROJECT_WIN, PROJECT_LINUX), at='2026-09-10T00:00:00+00:00'):
    return {'user': 'u1', 'choice': choice, 'policy_hash': parse_policy(policy)['policy_hash'], 'at': at, 'projects': list(projects)}


def test_notice_may_only_claim_what_the_policy_enforces():
    parsed = parse_policy(POLICY)
    assert parsed['policy_hash'] and parsed['notice']['claims'] == ['automatic_exclusion', 'no_external_transfer', 'raw_not_retained']
    external = {**POLICY, 'model': {'name': 'remote', 'transport': 'external'}}
    with pytest.raises(ContractError, match='notice claims no external transfer but the model transport is external'):
        parse_policy(external)
    honest_external = {**external, 'notice': {'text': 'Sent to a remote model.', 'claims': ['automatic_exclusion']}}
    assert parse_policy(honest_external)['model']['transport'] == 'external'
    with pytest.raises(ContractError, match='raw text is not retained'):
        parse_policy({**POLICY, 'retention': {'temporary': 'run', 'permanent': 'none'}})
    with pytest.raises(ContractError, match='must include content, project_path, kind; missing content, project_path'):
        parse_policy({**POLICY, 'fields': {'kind': 'only the kind'}})  # review counterexample (PR #63)
    for bad in ({**POLICY, 'version': 2}, {**POLICY, 'fields': {'secret_field': 'x'}}, {**POLICY, 'read_scope': {**POLICY['read_scope'], 'max_chars': 99999}},
                {**POLICY, 'notice': {'text': 'x', 'claims': ['never_leaks']}}, {k: v for k, v in POLICY.items() if k != 'purpose'}):
        with pytest.raises(ContractError):
            parse_policy(bad)


def test_consent_binds_to_the_policy_hash_and_keeps_cancel_and_questionnaire():
    granted = parse_consent(consent(POLICY), POLICY)
    assert granted['collect'] is True and 'never authorization' in granted['note']
    assert parse_consent(consent(POLICY, 'cancel'), POLICY)['collect'] is False
    assert parse_consent(consent(POLICY, 'questionnaire'), POLICY)['collect'] is False
    assert parse_consent(consent(POLICY, 'grant', projects=()), POLICY)['collect'] is False, 'a grant for no project collects nothing'
    with pytest.raises(ContractError, match='bound to another policy version'):
        parse_consent({**consent(POLICY), 'policy_hash': 'f' * 64}, POLICY)
    with pytest.raises(ContractError, match='cannot widen'):
        parse_consent(consent(POLICY, projects=(PROJECT_WIN, '/home/other/project')), POLICY)
    with pytest.raises(ContractError):
        parse_consent({**consent(POLICY), 'choice': 'maybe'}, POLICY)


def test_scan_covers_the_needed_kinds_across_windows_linux_wsl_and_korean_text():
    text = ('password: hunter2-sentinel 그리고 비밀번호=상자열쇠 ' + 'sk-' + 'a' * 24 + ' AKIA' + 'B' * 16 + ' me@example.com '
            'C:\\Users\\sentinel-user\\x /home/sentinel-user/y /mnt/c/Users/sentinel-user/z \\\\wsl$\\Ubuntu\\home\\sentinel-user\\w '
            '4111 1111 1111 1111 1234 5678 9012 3450 '
            '-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----')
    kinds = [f['kind'] for f in scan(text)]
    assert kinds.count('credential') == 2 and kinds.count('token') == 2 and kinds.count('email') == 1
    assert kinds.count('user_path') == 4 and kinds.count('card_number') == 1, 'Luhn keeps the real card pattern and drops the other digits'
    assert kinds.count('private_key') == 1 and set(kinds) <= set(KINDS) and set(BLOCKING) == {'private_key', 'credential', 'token'}
    assert scan('평범한 한국어 메시지입니다. 경로 없음, 비밀 없음.') == []
    assert scan('surrogate \udcff text password=x') and project_ref('C:\\Users\\A\\P') == project_ref('c:/users/a/p/'), 'the same project on both slashes'
    with pytest.raises(ContractError):
        scan(b'bytes')


def test_minimize_refuses_blocked_records_and_never_marks_unchecked_input_safe():
    policy = parse_policy(POLICY)
    granted = parse_consent(consent(POLICY), POLICY)
    ready = minimize({'content': 'I prefer short diffs. mail me@example.com at C:\\Users\\sentinel-user\\notes', 'project_path': PROJECT_WIN,
                      'kind': 'user_message', 'session_id': 's1', 'observed_at': 't'}, policy, granted)
    assert ready['status'] == 'ready' and ready['findings'] == {'email': 1, 'user_path': 1} and ready['dropped_fields'] == ['observed_at', 'session_id']
    assert ready['input'] == {'content': 'I prefer short diffs. mail [REDACTED email] at [REDACTED user_path]\\notes',
                              'project_ref': project_ref(PROJECT_WIN), 'kind': 'user_message'}, 'dropped fields never reach the input'
    wider = parse_policy({**POLICY, 'fields': {**POLICY['fields'], 'observed_at': 'ordering', 'session_id': 'grouping'}})
    wide = minimize({'content': 'x', 'project_path': PROJECT_WIN, 'kind': 'user_message', 'session_id': 's1', 'observed_at': 't1'}, wider, granted)
    assert set(wide['input']) == {'content', 'project_ref', 'kind', 'session_ref', 'observed_at'} and wide['input']['session_ref'] != 's1'
    assert wide['dropped_fields'] == [] and 's1' not in json.dumps(wide)
    assert 'sentinel-user' not in json.dumps(ready) and 'example.com' not in json.dumps(ready), 'neither the ledger nor the input keeps the value'
    blocked = minimize({'content': 'use password: hunter2-sentinel please', 'project_path': PROJECT_LINUX, 'kind': 'user_message'}, policy, granted)
    assert blocked['status'] == 'blocked' and 'input' not in blocked and blocked['findings'] == {'credential': 1} and 'hunter2' not in json.dumps(blocked)
    assert minimize({'content': 'x', 'project_path': '/home/other/p', 'kind': 'user_message'}, policy, granted)['status'] == 'not_consented'
    assert minimize({'content': 'x', 'project_path': PROJECT_WIN, 'kind': 'assistant_message'}, policy, granted)['status'] == 'out_of_scope'
    cancelled = parse_consent(consent(POLICY, 'cancel'), POLICY)
    assert minimize({'content': 'x', 'project_path': PROJECT_WIN, 'kind': 'user_message'}, policy, cancelled)['status'] == 'not_consented'
    for record, status, unchecked in ((OSError('locked'), 'read_error', 5), ('not json', 'parse_error', 5),
                                      ({'content': 'x', 'project_path': PROJECT_WIN, 'kind': 'user_message', 'extra': 1}, 'parse_error', 1),
                                      ({'content': 'x'}, 'parse_error', 2), ({'content': 1, 'project_path': PROJECT_WIN, 'kind': 'user_message'}, 'parse_error', 3)):
        result = minimize(record, policy, granted)
        assert result['status'] == status and len(result['unchecked_fields']) == unchecked and 'input' not in result
    long = minimize({'content': 'a' * 400 + ' password=late', 'project_path': PROJECT_WIN, 'kind': 'user_message'}, policy, granted)
    assert long['status'] == 'ready' and long['truncated'] is True and len(long['input']['content']) == 300, 'the cap applies before the model sees anything'


def test_evidence_forms_normalize_and_every_rendered_field_is_checked_or_named():
    same = [{'quote': 'likes tests', 'source': 's1', 'signal': 'testing'}]
    with pytest.raises(ContractError, match='disagree'):
        normalize_evidence({'evidence': same, 'evidence_quotes': ['likes tests']})  # same quote, different source: still a conflict
    assert normalize_evidence({'evidence_quotes': ['likes tests']}) == [{'quote': 'likes tests', 'source': '', 'signal': ''}]
    assert normalize_evidence({'evidence': same, 'evidence_quotes': same}) == same
    with pytest.raises(ContractError, match='disagree'):
        normalize_evidence({'evidence': same, 'evidence_quotes': [{'quote': 'other'}]})
    with pytest.raises(ContractError, match='Unsupported dimension fields: raw_messages'):
        normalize_evidence({'evidence': same, 'raw_messages': ['x']})
    with pytest.raises(ContractError):
        normalize_evidence({'evidence': [{'quote': 'q', 'weight': 3}]})
    profile = {'profile_version': 1, 'dimensions': {
        'testing': {'evidence': [{'quote': 'clean quote'}], 'evidence_quotes': [{'quote': 'clean quote'}], 'summary': 'ok',
                    'instruction': 'keep tests', 'project': 'shop', 'signal': 'HIGH', 'metadata': {'count': 2}},
        'paths': {'evidence_quotes': ['saved at C:\\Users\\sentinel-user\\notes'], 'summary': 'mentions password: sentinel-pw',
                  'instruction': 'fine', 'project': PROJECT_LINUX, 'metadata': {'nested': {'deep': 'x'}}}}}
    report = check_render(profile)
    assert report['verdict'] == 'unchecked_fields' and report['unchecked'] == ['paths.metadata']
    paths = report['dimensions']['paths']['fields']
    assert paths['evidence']['findings'] == {'user_path': 1} and paths['summary']['findings'] == {'credential': 1} and paths['project']['findings'] == {'user_path': 1}
    assert report['findings'] == {'credential': 1, 'user_path': 2} and 'sentinel' not in json.dumps(report)
    clean = check_render({'dimensions': {'testing': profile['dimensions']['testing']}})
    assert clean['verdict'] == 'none_detected_in_checked_fields' and clean['unchecked'] == [] and 'never safe' in clean['note']
    conflicting = check_render({'dimensions': {'x': {'evidence': [{'quote': 'a'}], 'evidence_quotes': [{'quote': 'b'}]}}})
    assert conflicting['verdict'] == 'unchecked_fields' and conflicting['dimensions']['x']['status'] == 'parse_error'
    with pytest.raises(ContractError, match='Unsupported profile fields'):
        check_render({'dimensions': {'x': {'evidence': []}}, 'raw_dump': 1})


def test_flow_needs_consent_keeps_only_counts_and_binds_the_run(tmp_path):
    flow = ProfileFlow(MemoryStore(), ProfileScratch(tmp_path / 'scratch'))
    binding = {'source_revision': 'a' * 40, 'environment': 'windows-11'}
    records = [{'content': 'I prefer short diffs', 'project_path': PROJECT_WIN, 'kind': 'user_message'},
               {'content': 'token sk-' + 'z' * 24 + ' here', 'project_path': PROJECT_WIN, 'kind': 'user_message'},
               {'content': 'x', 'project_path': '/home/other/p', 'kind': 'user_message'}, OSError('unreadable'), 'garbage']
    with pytest.raises(ContractError, match='No consent recorded'):
        flow.prepare_model_input('run-1', owner='w1', user='u1', policy=POLICY, records=records, binding=binding, lease_until='2999-01-01T00:00:00+00:00')
    flow.record_consent(POLICY, consent(POLICY, 'cancel', at='2026-09-10T00:00:00+00:00'))
    cancelled = flow.prepare_model_input('run-0', owner='w1', user='u1', policy=POLICY, records=records, binding=binding, lease_until='2999-01-01T00:00:00+00:00')
    assert cancelled['status'] == 'not_consented' and cancelled['bundle'] is None and not (tmp_path / 'scratch' / 'run-0').exists()
    flow.record_consent(POLICY, consent(POLICY, 'grant', at='2026-09-10T00:00:01+00:00'))
    run = flow.prepare_model_input('run-1', owner='w1', user='u1', policy=POLICY, records=records, binding=binding, lease_until='2999-01-01T00:00:00+00:00')
    assert run['status'] == 'ready' and run['counts'] == {'ready': 1, 'blocked': 1, 'not_consented': 1, 'read_error': 1, 'parse_error': 1}
    assert run['findings'] == {'token': 1} and run['binding'] == binding and run['model']['transport'] == 'local'
    assert 'sk-zzz' not in json.dumps(run) and 'short diffs' not in json.dumps(run), 'the ledger row carries no record text'
    bundle = flow.scratch.read('run-1', 'w1')
    assert [r['content'] for r in bundle['records']] == ['I prefer short diffs'] and bundle['records'][0]['sequence'] == 0
    with pytest.raises(ContractError, match='produced no model input'):
        flow.render('run-0', {'dimensions': {'x': {'evidence': [{'quote': 'q'}]}}})
    rendered = flow.render('run-1', {'dimensions': {'x': {'evidence': [{'quote': 'q'}], 'summary': 'see /home/sentinel-user/z'}}})
    assert rendered['renderable'] is False and rendered['findings'] == {'user_path': 1}
    with pytest.raises(ContractError, match='owned by another worker'):
        flow.finish('run-1', 'w2')
    assert flow.finish('run-1', 'w1')['deleted'] is True and not (tmp_path / 'scratch' / 'run-1').exists()
    with flow.store.transaction() as tx:
        row = tx.get(RUNS, 'run-1')
        assert row['cleanup']['deleted'] and row['render']['verdict'] == 'findings'
    with pytest.raises(ContractError, match='Binding requires'):
        flow.prepare_model_input('run-2', owner='w1', user='u1', policy=POLICY, records=[], binding={}, lease_until='x')
    # temporary=none: nothing is written to scratch; the input lives only in the return value (review, PR #63).
    volatile = {**POLICY, 'retention': {'temporary': 'none', 'permanent': 'profile_only'}}
    flow.record_consent(volatile, consent(volatile, 'grant', at='2026-09-10T00:00:02+00:00'))
    run2 = flow.prepare_model_input('run-3', owner='w1', user='u1', policy=volatile, records=records[:1], binding=binding, lease_until='2999-01-01T00:00:00+00:00')
    assert run2['status'] == 'ready' and run2['bundle'] is None and run2['temporary_storage'] == 'none'
    assert [r['content'] for r in run2['input_records']] == ['I prefer short diffs'] and not (tmp_path / 'scratch' / 'run-3').exists()
    with flow.store.transaction() as tx:
        stored = tx.get(RUNS, 'run-3')
        assert 'input_records' not in stored and 'short diffs' not in json.dumps(stored)


CHILD = r'''
import sys, json
from codex_harness.adapters.profile_scratch import ProfileScratch
scratch = ProfileScratch(sys.argv[1])
scratch.write('run-crash', 'child', '2999-01-01T00:00:00+00:00', {'records': [{'content': 'partial', 'sequence': 0}]})
print(json.dumps({'written': True}))
sys.stdout.flush()
raise SystemExit(3)  # crashes after writing: the bundle must be preserved for the owner to resume
'''


def test_scratch_bundles_are_owned_preserved_after_a_crash_and_swept_only_by_lease(tmp_path):
    scratch = ProfileScratch(tmp_path / 'scratch')
    run = subprocess.run([sys.executable, '-c', CHILD, str(tmp_path / 'scratch')], capture_output=True, text=True,
                         env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, timeout=60)
    assert run.returncode == 3 and json.loads(run.stdout)['written'] is True
    assert scratch.read('run-crash', 'child')['records'][0]['content'] == 'partial', 'preserved after the process died'
    with pytest.raises(ContractError, match='owned by another worker'):
        scratch.read('run-crash', 'parent')
    with pytest.raises(ContractError, match='not deleted'):
        scratch.cleanup('run-crash', 'parent')
    resumed = scratch.write('run-crash', 'child', '2999-01-01T00:00:00+00:00', {'records': [{'content': 'partial', 'sequence': 0}, {'content': 'rest', 'sequence': 1}]})
    assert resumed['bytes'] > 0 and len(scratch.read('run-crash', 'child')['records']) == 2
    with pytest.raises(ContractError, match='owned by another worker'):
        scratch.write('run-crash', 'thief', '2999-01-01T00:00:00+00:00', {})
    scratch.write('run-old', 'w1', '2000-01-01T00:00:00+00:00', {'records': []})
    (tmp_path / 'scratch' / 'run-orphan').mkdir()
    (tmp_path / 'scratch' / 'run-orphan' / 'bundle.json').write_text('{}')
    swept = scratch.sweep('2026-09-10T00:00:00+00:00')
    assert [d['run_id'] for d in swept['deleted']] == ['run-old'] and {k['run_id']: k['reason'] for k in swept['kept']} == {
        'run-crash': 'lease active', 'run-orphan': 'no owner sidecar'}
    assert (tmp_path / 'scratch' / 'run-crash' / 'bundle.json').exists() and 'prefix never decide' in swept['note']
    (tmp_path / 'scratch' / 'run-crash' / 'bundle.json').write_bytes(b'{"records": []}')
    with pytest.raises(ContractError, match='digest mismatch; preserved'):
        scratch.read('run-crash', 'child')
    with pytest.raises(ContractError, match='not deleting an unowned directory'):
        scratch.cleanup('run-orphan', 'w1')
    assert scratch.cleanup('never-written', 'w1') == {'run_id': 'never-written', 'deleted': False, 'reason': 'absent'}
