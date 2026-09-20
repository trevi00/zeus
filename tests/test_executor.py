"""The implementation worker's delivered instruction (operating-portfolio-001, completion batch).

Run 5b6a3b1cc9f249dfbbc0b2c8f5407e50 lost 647s to five refused StructuredOutput attempts, each one
missing the required `tests` field, so the envelope is now stated in the objective as well. These
tests read the objective of a REAL `execute_one` implementation run on both paths: the runtime is a
labelled fixture seam (no provider, model, network or Docker), while the executor, the Git
workspace, the workflow and the prompt composition are the production ones.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from test_git_workspace import git, repository
from test_project_evidence import POLICY, document, workspace

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import IMPLEMENTATION, Executor, implementation_instruction
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope
from codex_harness.domain.project_evidence import parse_profile

PY = sys.executable


def run_implementation(tmp_path, monkeypatch, profile=None):
    """One real implement execution; returns the prompts the fixture runtime received."""
    root = repository(tmp_path)
    if profile is not None:  # the profile's context must exist in the candidate the worker receives
        workspace(tmp_path, 'repository')
        git(root, 'add', '.')
        git(root, 'commit', '-m', 'backend context')
    git_workspace = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    service = Harness(MemoryStore(), organization())
    executor = Executor(service, git_workspace, FileArtifacts(str(tmp_path / 'artifacts')),
                        evidence_profile=profile)
    prompts = []

    class Runtime:
        """Fixture seam: records the composed prompt and answers the declared schema."""

        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

        def run(self, prompt, cwd, schema, timeout, **kwargs):
            prompts.append(json.loads(prompt))
            Path(cwd, 'change.txt').write_text('implemented', encoding='utf-8')
            return {'answer': {'summary': 'fixture', 'tests': []}, 'events': [], 'thread_id': 'thread',
                    'turn_id': 'turn', 'usage': None, 'rotate': False, 'interrupted': False,
                    'requested_model': kwargs.get('model')}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    message = envelope('task.assign', organization().actor('worker:implementation').parent,
                       'worker:implementation', 'implement',
                       {'plan': {'objective': 'fixture', 'acceptance_criteria': ['x'],
                                 'allowed_paths': ['change.txt']}}, 'fixture', None)
    message['where']['revision'] = git_workspace._git('rev-parse', 'HEAD')
    executor.workflow.submit(message)
    row = executor.execute_one('worker:implementation')
    return SimpleNamespace(prompts=prompts, row=row)


def test_the_legacy_implementation_objective_requires_both_fields_and_shows_only_a_shape(tmp_path, monkeypatch):
    delivered = run_implementation(tmp_path, monkeypatch)
    objective = delivered.prompts[0]['required']['objective']
    assert objective == implementation_instruction(False)
    assert 'BOTH top-level fields, `summary` and `tests`' in objective
    assert 'neither is optional' in objective and 'omits one is refused' in objective
    assert 'lists only the exact commands you executed, one per string' in objective
    assert 'Shape only, not an example of work that was done' in objective
    assert '{"summary": "<concise observed results>", "tests": ["python -m pytest tests/test_x.py -q"]}' in objective
    # An empty answer stays honest, and honest is still not acceptance.
    assert 'empty' in objective and 'never by itself sufficient' in objective
    assert 'check_id' not in objective, 'the profiled observation shape belongs to the profiled path only'
    assert 'concise observed fact' in objective
    assert delivered.row['status'] == 'succeeded', delivered.row


def test_the_profiled_implementation_objective_states_the_observation_shape_and_the_same_two_fields(tmp_path, monkeypatch):
    profile = parse_profile(document(), POLICY)
    delivered = run_implementation(tmp_path, monkeypatch, profile=profile)
    objective = delivered.prompts[0]['required']['objective']
    assert objective == implementation_instruction(True)
    assert 'BOTH top-level fields, `summary` and `tests`' in objective
    assert '{check_id, status, exit_code}' in objective and 'a failure stays a failure' in objective
    assert '[{"check_id": "<a declared check_id>", "status": "executed", "exit_code": 0}]}' in objective
    assert 'Shape only, not an example of work that was done' in objective
    assert 'python -m pytest tests/test_x.py -q' not in objective, 'no legacy command shape on this path'
    assert 'never by itself sufficient' in objective
    # The host's own project context still travels with it; the instruction replaced nothing else.
    assert delivered.prompts[0]['required']['project_evidence']['checks'] == profile['checks']


def test_the_implementation_schema_still_refuses_an_answer_that_omits_either_field():
    """Schema validation is unchanged: the instruction is a mitigation, never the enforcement."""
    validator = Draft202012Validator(IMPLEMENTATION)
    assert IMPLEMENTATION['required'] == ['summary', 'tests']
    assert validator.is_valid({'summary': 'ran nothing', 'tests': []})
    assert not validator.is_valid({'summary': 'prose instead of the envelope'})
    assert not validator.is_valid({'tests': ['python -m pytest -q']})
    assert not validator.is_valid({'summary': 's', 'tests': []} | {'notes': 'x'})


@pytest.mark.parametrize('profiled', [False, True])
def test_the_instruction_never_claims_a_check_was_run(profiled):
    objective = implementation_instruction(profiled)
    assert 'Shape only' in objective
    for claim in ('passed', 'ran successfully', 'all tests pass'):
        assert claim not in objective
