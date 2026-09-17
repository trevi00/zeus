"""INV-PROJECT-EVIDENCE-001 R3: the host project contexts reach the actual Claude transport.

The transport runs against `tests/claude_protocol_child.py` (a labelled protocol fixture, never a
model or a provider measurement): what it received as `--settings`, `--append-system-prompt` and
environment is read back. The delivered command text is then executed by a real POSIX `sh`, which
is what proves the quoting, the context cwd, the host interpreter and the source environment. That
the installed Claude CLI honours the rules is decided by the operation's canary, not here.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_project_evidence import POLICY, PROBE, argv_for, document, workspace
from test_project_evidence import SCHEMA as PROFILE_SCHEMA
from test_worker_profile import CHILD, RUNTIME, SCHEMA, observation, profiled

from codex_harness.adapters.claude_cli import ClaudeCodeRuntime, claude_settings
from codex_harness.adapters.project_evidence import execution_instructions, worker_delivery
from codex_harness.adapters.worker_profile import load_profile
from codex_harness.domain.model import ContractError
from codex_harness.domain.project_evidence import parse_profile

SH = shutil.which('sh')
AWKWARD = "candidate it's $HOME 작업"  # a space, a quote, a dollar sign and non-ASCII text in the path


def two_contexts(root):
    """A second context at the repository root with no source path, beside the backend one."""
    (root / 'rootprobes').mkdir(exist_ok=True)
    (root / 'rootprobes' / 'test_root.py').write_text(
        'import os\nfrom pathlib import Path\n\n\ndef test_root():\n'
        '    assert (Path.cwd() / "backend").is_dir()\n'
        '    assert not os.environ.get("PYTHONPATH")\n', encoding='utf-8')
    doc = document([{'id': 'unit', 'context': 'backend', 'argv': argv_for(PROBE), 'expected_exit': 0},
                    {'id': 'rooted', 'context': 'top', 'expected_exit': 0,
                     'argv': ['python', '-m', 'pytest', 'rootprobes/test_root.py', '-q', '-p', 'no:cacheprovider']}])
    doc['contexts']['top'] = {'cwd': '.', 'interpreter': sys.executable, 'source_paths': [], 'dependency_files': []}
    return parse_profile(doc, POLICY)


def test_rules_are_exact_host_commands_per_context_and_never_broad(tmp_path):
    root = workspace(tmp_path, AWKWARD)
    delivery = worker_delivery(two_contexts(root), root)
    by_id = {entry['check_id']: entry for entry in delivery['commands']}
    assert set(by_id) == {'unit', 'rooted'} and by_id['unit']['context'] == 'backend' and by_id['rooted']['context'] == 'top'
    assert str((root / 'backend').resolve()) in by_id['unit']['command'].replace("'\"'\"'", "'")
    assert "PYTHONPATH=''" in by_id['rooted']['command'], 'no source path: the process value can never stand in'
    rules = delivery['permissions_allow']
    assert len(rules) == 6 and all(rule.startswith('Bash(') and '*' not in rule for rule in rules)
    for entry in delivery['commands']:
        change, run = entry['command'].split(' && ', 1)
        assert {f'Bash({entry["command"]})', f'Bash({change})', f'Bash({run})'} <= set(rules)
    assert all(entry['command'] in delivery['document'] for entry in delivery['commands'])
    assert execution_instructions(two_contexts(root), root)['commands'] == {k: v['command'] for k, v in by_id.items()}
    other = workspace(tmp_path, 'review')
    assert str(root.resolve()) not in json.dumps(worker_delivery(two_contexts(other), other), ensure_ascii=False)


@pytest.mark.skipif(SH is None, reason='no POSIX sh on this host to execute the delivered command text')
def test_the_delivered_text_really_runs_each_check_in_its_context(tmp_path):
    """Real subprocesses: sh parses the text from the repository root under a poisoned parent
    PYTHONPATH; the probes themselves assert cwd, PYTHONPATH and PYTHONDONTWRITEBYTECODE."""
    root = workspace(tmp_path, AWKWARD)
    delivery = worker_delivery(two_contexts(root), root)
    parent = {**os.environ, 'PYTHONPATH': str(tmp_path / 'parent-leak'), 'HOME': str(tmp_path / 'not-expanded')}
    for entry in delivery['commands']:
        done = subprocess.run([SH, '-c', entry['command']], cwd=str(root), env=parent, capture_output=True, timeout=120)
        assert done.returncode == 0, (entry['command'], done.stdout[-600:], done.stderr[-600:])
    (root / 'backend' / 'probes' / f'test_{PROBE}.py').write_text('def test_fails():\n    assert False\n', encoding='utf-8')
    failed = subprocess.run([SH, '-c', delivery['commands'][0]['command']], cwd=str(root), env=parent,
                            capture_output=True, timeout=120)
    assert failed.returncode == 1, 'the observed exit is the check\'s own, not the wrapper\'s'


def test_the_transport_delivers_settings_instructions_and_environment(tmp_path):
    runtime, _ = profiled(tmp_path)
    root = workspace(tmp_path, 'candidate 작업')
    (root / 'src').mkdir()  # the legacy profile would put this on PYTHONPATH
    delivery = worker_delivery(two_contexts(root), root)
    with ClaudeCodeRuntime(model='claude-stub-normal', runtime=runtime, executable=str(CHILD), launcher=[sys.executable],
                           max_budget_usd=1.0, settings_document=claude_settings(runtime),
                           project_delivery=delivery) as opened:
        result = opened.run('fixture prompt', str(root), SCHEMA, timeout=90)
    seen = observation(root)
    settings = json.loads(seen['settings'])
    allow = settings['permissions']['allow']
    assert allow[:3] == RUNTIME['allowed_tools'] and set(delivery['permissions_allow']) <= set(allow)
    assert set(load_profile('worker-v1')['permissions_allow']) <= set(allow), 'legacy rules stay'
    assert settings['permissions']['deny'] == RUNTIME['disallowed_tools'], 'every deny rule preserved'
    assert settings['permissions']['defaultMode'] == 'acceptEdits' and 'bypassPermissions' not in seen['settings']
    assert not {'Bash', 'Bash(*)', 'Bash(:*)'} & set(allow)
    prompt = seen['append_system_prompt']
    assert prompt.startswith(load_profile('worker-v1')['document']) and '## Host project checks (this run)' in prompt
    assert all(entry['command'] in prompt for entry in delivery['commands'])
    assert seen['pythonpath'] is None, 'the root src is not prepared when the host selected contexts'
    assert Path(seen['cwd']) == root.resolve(), 'the repository root stays the working root'
    receipt = result['command']['project_evidence']
    assert receipt['checks'] == ['unit', 'rooted'] and receipt['profile_digest'] == delivery['profile_digest']
    assert all(entry['command'] not in json.dumps(result['command'], ensure_ascii=False) for entry in delivery['commands'])


def test_the_packaged_document_no_longer_contradicts_a_host_profile():
    text = load_profile('worker-v1')['document']
    assert 'Do not substitute an absolute interpreter' not in text
    assert 'except host `project_evidence` commands' in text and 'Run tests as `python -m pytest`' in text


def test_a_broad_rule_a_foreign_checkout_and_model_text_are_refused(tmp_path):
    root = workspace(tmp_path)
    delivery = worker_delivery(two_contexts(root), root)
    for rules in (['Bash(*)'], ['Bash'], ['Bash(python -m pytest:*)'], ['Read'], []):
        with pytest.raises(ContractError, match='exact Bash rules'):
            ClaudeCodeRuntime(model='claude-stub-normal', runtime=RUNTIME, executable=str(CHILD), launcher=[sys.executable],
                              max_budget_usd=1.0, project_delivery={**delivery, 'permissions_allow': rules})
    elsewhere = workspace(tmp_path, 'elsewhere')
    with ClaudeCodeRuntime(model='claude-stub-normal', runtime=RUNTIME, executable=str(CHILD), launcher=[sys.executable],
                           max_budget_usd=1.0, project_delivery=delivery) as opened:
        with pytest.raises(ContractError, match='another checkout'):
            opened.run('fixture prompt', str(elsewhere), SCHEMA, timeout=30)
    assert not (elsewhere / 'stub-runs.log').exists(), 'refused before any process'
    # A control character cannot be carried by a one-line command or its rule: refused, not escaped.
    doc = document([{'id': 'unit', 'context': 'backend', 'expected_exit': 0,
                     'argv': ['python', '-m', 'pytest', 'x\n; rm -rf /']}])
    with pytest.raises(ContractError, match='quoted safely'):
        worker_delivery(parse_profile(doc, POLICY), root)
    assert PROFILE_SCHEMA == 'urn:zeus:project-evidence:1'


def test_the_executor_hands_the_transport_this_checkout_only_for_a_profiled_implementation(tmp_path, monkeypatch):
    """Seam (labelled fake transport class): what `_open_runtime` constructs; legacy stays exact."""
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import Executor
    from codex_harness.adapters.store import MemoryStore
    from codex_harness.application.service import Harness
    from codex_harness.bootstrap import organization

    built = []
    monkeypatch.setattr('codex_harness.adapters.executor.ClaudeCodeRuntime', lambda **kwargs: built.append(kwargs))
    root = workspace(tmp_path)
    assignment = SimpleNamespace(transport='claude_cli', runtime=dict(RUNTIME), controls={'max_budget_usd': 1.0})
    git = SimpleNamespace(_git=lambda *a, **k: 'revision')
    profile = parse_profile(document(), POLICY)
    executor = Executor(Harness(MemoryStore(), organization()), git, FileArtifacts(str(tmp_path / 'a')), evidence_profile=profile)
    executor._open_runtime(assignment, 'sonnet', str(root), 'implement')
    executor._open_runtime(assignment, 'sonnet', str(root), 'review')
    legacy = Executor(Harness(MemoryStore(), organization()), git, FileArtifacts(str(tmp_path / 'b')))
    legacy._open_runtime(assignment, 'sonnet', str(root), 'implement')
    assert built[0]['project_delivery'] == worker_delivery(profile, root)
    assert built[0]['project_delivery']['workspace'] == str(root.resolve())
    assert 'project_delivery' not in built[1] and 'project_delivery' not in built[2]
    assert set(built[2]) == {'model', 'runtime', 'executable', 'max_budget_usd', 'settings_document'}
