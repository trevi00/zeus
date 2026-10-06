import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.hooks import NativeHooks
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest, envelope

ROOT = Path(__file__).resolve().parents[1]
HOOK_ID = 'hook-ab97ba09554daa5aec289867'


@pytest.fixture(params=[
    ("hook-ec928b6c78b06bb571eb45cb", "codex-provider-usage-limit-exceeded", "worker:github/codex-turn"),
    (HOOK_ID, "codex-bubblewrap-namespace-creation-denied", "docker/linux/codex-read-only-review"),
    ("hook-572b2b90cf311ed31d66b108", "codex-output-schema-version-missing-type",
     "codex-harness/research-audit/output-schema"),
])
def native_candidate(tmp_path, request):
    hook_id, cause, scope = request.param
    service = Harness(MemoryStore(), organization())
    # Fixture diagnosis only. No automatic cause confirmation from error text.
    for occurrence in ['review-one', 'review-two']:
        message = envelope('incident.report', 'lead:improvement', 'conductor', 'record_incident',
                           {'occurrence_id': occurrence,
                            'root_cause': cause,
                            'scope': scope,
                            'evidence_refs': ['fixture:confirmed-diagnosis']}, 'fixture')
        service.record_incident(message)
        service.record_incident(message)
    def git_show(command, revision_path, **kwargs):
        assert command == 'show' and revision_path.startswith('fixture-revision:')
        return (ROOT / revision_path.split(':', 1)[1]).read_text()
    adapter = NativeHooks(service, SimpleNamespace(_git=git_show), FileArtifacts(str(tmp_path)))
    spec = adapter.candidate(hook_id, {'revision': 'fixture-revision', 'author': 'worker:implementation'})
    return service, adapter, spec, hook_id


def test_canary_channel_carries_non_locale_text_both_ways(native_candidate, tmp_path):
    # INV-ENCODING-001: an actual hook child echoes text outside the Windows console code page.
    service, adapter, spec, hook_id = native_candidate
    script = tmp_path / 'echo_hook.py'
    script.write_text('import json, sys\n'
                      'data = json.loads(sys.stdin.read())\n'
                      'print(json.dumps({"encoding": sys.stdout.encoding, "echo": data["text"]}, '
                      'ensure_ascii=False))\n', encoding='utf-8')
    adapter.materialize = lambda hook: script
    cases = {kind: [{'input': {'text': '검증 — 완료'}, 'output': {'encoding': 'utf-8', 'echo': '검증 — 완료'},
                     'exit_code': 0}] for kind in ('reproduction', 'normal_case')}
    with service.store.transaction() as tx:
        tx.put('hook_cases', hook_id, {'id': hook_id, 'revision': 'fixture-revision', 'cases': cases})
    checks = adapter.canary(hook_id)
    assert all(check['passed'] for check in checks.values()), checks
    evidence = json.loads(adapter.artifacts.text(checks['reproduction']['evidence'], 100_000))
    assert evidence[0]['output'] == cases['reproduction'][0]['output'] and evidence[0]['stderr'] == ''


def test_native_activation_gates_canary_and_rollback_exclusion(native_candidate):
    service, adapter, spec, hook_id = native_candidate
    assert adapter.configuration() == {}
    with pytest.raises(ContractError):
        service.activate(hook_id)
    for revision, spec_hash in [('stale', digest(spec)), ('fixture-revision', 'stale')]:
        with pytest.raises(ContractError, match='Stale review'):
            service.review(hook_id, 'lead:improvement', revision, spec_hash, True, 'fixture')
    for actor in ['conductor', 'lead:research', 'worker:implementation']:
        with pytest.raises(ContractError):
            service.review(hook_id, actor, 'fixture-revision', digest(spec), True, 'fixture')
    for actor in ['lead:improvement', 'conductor']:
        service.review(hook_id, actor, 'fixture-revision', digest(spec), True, 'fixture')
    checks = adapter.canary(hook_id)
    assert all(check['passed'] for check in checks.values())
    assert adapter.configuration() == {}
    service.record_canary(hook_id, 'fixture-revision', digest(spec),
                          {'reproduction': True, 'normal_case': True, 'cli_start': True})
    service.activate(hook_id)
    configuration = adapter.configuration()
    assert configuration['SessionStart'][0]['matcher'] == spec['matcher']
    service.rollback(hook_id, 'fixture rollback through existing use case')
    assert NativeHooks(service, adapter.git, adapter.artifacts).configuration() == {}
    assert service.get_hook(hook_id)['status'] == 'rolled_back'
    with service.store.transaction() as tx:
        assert len(tx.scan('incidents')) == 2


def test_materialization_checks_exact_git_content(native_candidate):
    service, adapter, _, hook_id = native_candidate
    adapter.git._git = lambda *a, **k: 'tampered'
    with pytest.raises(ContractError, match='Reviewed script changed'):
        adapter.materialize(service.get_hook(hook_id))


def test_manifest_replay_is_explicitly_not_native_failure_coverage():
    manifest = json.loads((ROOT / f'harness_hooks/{HOOK_ID}.json').read_text())
    assert manifest['spec']['event'] == 'SessionStart'
    assert all(c['input']['method'] == 'item/completed' for c in manifest['cases']['reproduction'])


def test_recurrence_replacement_retains_incumbent_until_verified(native_candidate):
    service, adapter, spec, hook_id = native_candidate
    checks = {'reproduction': True, 'normal_case': True, 'cli_start': True}

    def review(revision, candidate_spec):
        for actor in ['lead:improvement', 'conductor']:
            service.review(hook_id, actor, revision, digest(candidate_spec), True, 'fixture')

    review('fixture-revision', spec)
    service.record_canary(hook_id, 'fixture-revision', digest(spec), checks)
    incumbent = service.activate(hook_id)
    configuration = adapter.configuration()
    message = envelope('incident.report', 'lead:improvement', 'conductor', 'record_incident',
                       {'occurrence_id': 'after-activation', 'root_cause': incumbent['root_cause'],
                        'scope': incumbent['scope'], 'evidence_refs': ['fixture:new-diagnosis']}, 'fixture')
    service.record_incident(message)
    required = service.get_hook(hook_id)
    assert required['status'] == 'required'
    assert required['previous_active'] == incumbent
    service.record_incident(message)
    redelivery = {**message, 'message_id': 'new-delivery-same-occurrence'}
    service.record_incident(redelivery)
    assert service.get_hook(hook_id) == required
    assert adapter.configuration() == configuration

    replacement = {**spec, 'matcher': '^startup$'}
    pending = service.propose(hook_id, 'worker:implementation', replacement, 'fixture-pending')
    service.review(hook_id, 'lead:improvement', 'fixture-pending', digest(replacement), True, 'fixture')
    assert pending['version'] == incumbent['version'] + 1
    assert adapter.configuration() == configuration
    for revision, reject in [('fixture-revision-two', 'review'), ('fixture-revision-three', 'canary'),
                             ('fixture-revision-four', None)]:
        previous = service.get_hook(hook_id)
        candidate = service.propose(hook_id, 'worker:implementation', replacement, revision)
        assert candidate['version'] == previous['version'] + 1
        assert candidate['reviews'] == [] and candidate['canary'] is None
        assert adapter.configuration() == configuration
        for stale_revision, stale_spec in [('fixture-revision', digest(replacement)), (revision, digest(spec))]:
            with pytest.raises(ContractError, match='Stale review'):
                service.review(hook_id, 'lead:improvement', stale_revision, stale_spec, True, 'fixture')
        if reject == 'review':
            service.review(hook_id, 'lead:improvement', revision, digest(replacement), False, 'fixture')
        else:
            review(revision, replacement)
            for stale_revision, stale_spec in [('fixture-revision', digest(replacement)), (revision, digest(spec))]:
                with pytest.raises(ContractError, match='Stale canary'):
                    service.record_canary(hook_id, stale_revision, stale_spec, checks)
            service.record_canary(hook_id, revision, digest(replacement),
                                  {**checks, 'cli_start': reject is None})
        if reject:
            with pytest.raises(ContractError, match='not verified'):
                service.activate(hook_id)
            assert service.get_hook(hook_id)['status'] == 'rejected'
        assert adapter.configuration() == configuration
    # INV-RECURRENCE-001: even verified candidates retain the incumbent until activation.
    service.activate(hook_id)
    adapter.git._git = lambda command, path, **kw: (ROOT / path.split(':', 1)[1]).read_text()
    assert adapter.configuration()['SessionStart'][0]['matcher'] == '^startup$'
    service.rollback(hook_id, 'fixture replacement rollback')
    assert service.get_hook(hook_id) == incumbent
    assert adapter.configuration() == configuration


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'null', b'[]', b'"text"'])
def test_schema_reminder_malformed_input_is_silent(raw):
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(ROOT / 'harness_hooks/codex_output_schema_guard.py')],
                            input=raw, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout == b'' and result.stderr == b''
