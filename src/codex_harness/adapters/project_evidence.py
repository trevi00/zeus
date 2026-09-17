"""Project-bound evidence replay (INV-PROJECT-EVIDENCE-001): host profile, immutable snapshot, replay.

The profile is operator configuration named by ZEUS_EVIDENCE_PROFILE (HARNESS_ alias): an absolute
JSON file outside the candidate, loaded once per run and never read from the candidate or accepted
from model output. A configured profile that is missing or invalid is refused; absence of the
setting leaves the legacy contract untouched. The snapshot resolves every context against the
actual candidate root (containment holds through symlinks) and binds the profile digest, resolved
paths, dependency-file byte digests, the interpreter's content digest and the environment value
digest into the inspection identity; every replay runs under those snapshot values, whatever the
host environment or profile file has become since. Limit: a selected interpreter path and its byte
digest do not attest the installed dependencies' immutability; the host prepares dependencies.
Replays reuse the existing bounded `_capture`, allowlist, budgets and raw-output archive.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from codex_harness.adapters.evidence_inspection import (
    EvidenceInspector,
    _capture,
    packaged_policy,
    replay_argv,
    replay_environment,
    trusted_interpreter,
)
from codex_harness.domain.evidence import authorized, classify_replays, finite_positive
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.project_evidence import classify_check, observed_checks, parse_profile

SETTING = 'HARNESS_EVIDENCE_PROFILE'
MAX_PROFILE_BYTES = 256 * 1024
MAX_DEPENDENCY_BYTES = 8 * 1024 * 1024


def load_profile(host_settings, policy=None):
    """None when the host configured no profile; otherwise the parsed immutable copy or a refusal."""
    configured = host_settings.get(SETTING) or host_settings.get('ZEUS_EVIDENCE_PROFILE')
    if not configured:
        return None
    path = Path(configured)
    require(path.is_absolute(), 'Evidence profile setting must name an absolute file')
    try:
        require(path.is_file() and path.stat().st_size <= MAX_PROFILE_BYTES, 'Evidence profile is missing or exceeds its budget')
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ContractError('Evidence profile unavailable or not valid JSON') from exc
    profile = parse_profile(document, policy if policy is not None else packaged_policy())
    for context in profile['contexts'].values():
        trusted_interpreter(context['interpreter'])
    return profile


def _file_digest(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as handle:
        while block := handle.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def _contained(root, relative, name):
    try:
        resolved = (root / relative).resolve()
    except (OSError, ValueError) as exc:
        raise ContractError(f'{name} cannot be resolved: {relative}') from exc
    require(resolved == root or root in resolved.parents, f'{name} resolves outside the candidate: {relative}')
    return resolved


def resolve_profile(profile, cwd, base=None):
    """Every context resolved against this candidate root, verified before any child exists."""
    root = Path(cwd).resolve()
    require(root.is_dir(), 'Project evidence workspace directory does not exist')
    contexts = {}
    for name, context in profile['contexts'].items():
        directory = _contained(root, context['cwd'], 'Project evidence cwd')
        require(directory.is_dir(), 'Project evidence cwd is not a directory: ' + context['cwd'])
        # Verified as an existing absolute file, but invoked by the host's own path: resolving a venv
        # interpreter symlink would leave the virtual environment the host selected.
        trusted_interpreter(context['interpreter'])
        interpreter = Path(context['interpreter'])
        sources = []
        for relative in context['source_paths']:
            source = _contained(root, relative, 'Project evidence source path')
            require(source.is_dir(), 'Project evidence source path is not a directory: ' + relative)
            sources.append(str(source))
        dependencies = {}
        for relative in context['dependency_files']:
            dependency = _contained(root, relative, 'Project evidence dependency file')
            require(dependency.is_file() and dependency.stat().st_size <= MAX_DEPENDENCY_BYTES,
                    'Project evidence dependency file is missing or exceeds its budget: ' + relative)
            dependencies[relative] = _file_digest(dependency)
        # The parent's PYTHONPATH is never read; editable-install source is not evidence.
        environment = replay_environment(base)
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        if sources:
            environment['PYTHONPATH'] = os.pathsep.join(sources)
        contexts[name] = {'cwd': str(directory), 'interpreter': str(interpreter), 'interpreter_sha256': _file_digest(interpreter),
                          'source_paths': sources, 'dependency_files': dependencies, 'environment': environment,
                          'environment_digest': digest(sorted(environment.items()))}
    bound = {'profile_digest': profile['profile_digest'], 'workspace': str(root),
             'contexts': {name: {k: v for k, v in context.items() if k != 'environment'} for name, context in contexts.items()}}
    return {'digest': digest(bound), 'profile_digest': profile['profile_digest'], 'workspace': str(root), 'contexts': contexts}


def execution_instructions(profile, cwd):
    """What a worker or reviewer is told: the host's checks and the context resolved for THIS checkout."""
    resolved = resolve_profile(profile, cwd)
    contexts = {name: {'cwd': context['cwd'], 'interpreter': context['interpreter'], 'source_paths': context['source_paths'],
                       'environment': {'PYTHONPATH': context['environment'].get('PYTHONPATH'), 'PYTHONDONTWRITEBYTECODE': '1'}}
                for name, context in resolved['contexts'].items()}
    return {'schema': profile['schema'], 'profile_digest': profile['profile_digest'], 'contexts': contexts,
            'checks': [dict(check) for check in profile['checks']],
            'instruction': 'These checks and contexts are host-authored. Run each check from its context cwd with that '
            'context interpreter in place of the first token "python" and with the listed environment values; do not '
            'choose another argv, cwd or interpreter and do not install dependencies. Every check is required. Report '
            'what you observed, a nonzero exit included. Read results from stdout; write no output files into the checkout.'}


class ProjectEvidenceInspector(EvidenceInspector):
    """The legacy inspector's policy, budgets, capture and archive, replaying host-declared checks."""

    def __init__(self, artifacts, profile, policy=None, interpreter=None):
        super().__init__(artifacts, policy, interpreter)
        require(isinstance(profile, dict) and type(profile.get('profile_digest')) is str, 'Parsed project evidence profile required')
        self.profile = profile

    def snapshot(self, cwd=None):
        require(cwd is not None, 'Project evidence snapshot requires the candidate workspace')
        snapshot = super().snapshot(cwd)
        project = resolve_profile(self.profile, cwd)
        identity = {**snapshot['identity'], 'project': {
            'digest': project['digest'], 'profile_digest': project['profile_digest'], 'workspace': project['workspace'],
            'contexts': {name: {k: v for k, v in context.items() if k != 'environment'}
                         for name, context in project['contexts'].items()}}}
        return {**snapshot, 'identity': identity, 'project': project}

    def _check(self, claim, project, remaining_seconds):
        if claim['status'] == 'missing':
            return {'state': 'not_checked', 'cause': 'required check has no observation; not replayed'}
        if claim['status'] == 'not_run':
            return {'state': 'not_checked', 'cause': 'worker reported not_run; a required check stays incomplete and is not replayed'}
        if not authorized(claim['argv'], self.policy):
            return {'state': 'not_checked', 'cause': 'command is not an authorized replay prefix; a profile is not authority'}
        per_command = min(self.policy['replay']['per_command_seconds'], remaining_seconds)
        if per_command <= 0:
            return {'state': 'not_checked', 'cause': 'aggregate replay budget exhausted'}
        finite_positive(per_command, 'replay deadline', self.policy['replay']['total_seconds'])
        context = project['contexts'][claim['context']]
        effective, transformation = replay_argv(claim['argv'], context['interpreter'])
        runs = []
        for _ in range(self.policy['replay']['replays_per_claim']):
            run = _capture(effective, context['cwd'], per_command, self.policy['replay']['max_output_bytes'],
                           dict(context['environment']))
            runs.append(self._archive(run))
            if run.get('failure'):
                break
        observed = [run['returncode'] for run in runs]
        state, cause = classify_check(claim, *classify_replays(runs, claim['expected_exit']), observed)
        return {'state': state, 'cause': cause, 'runs': runs, 'check_id': claim['check_id'], 'context': claim['context'],
                'original_argv': list(claim['argv']), 'replay_argv': effective, 'argv_transformation': transformation,
                'reported_exit': claim['reported_exit'], 'expected_exit': claim['expected_exit'], 'observed_exits': observed,
                'cwd': context['cwd'], 'interpreter': context['interpreter'], 'timeout_seconds': per_command}

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None, project=None):
        root = Path(cwd)
        if not root.is_dir():
            return {'context': {**binding, 'cwd': str(root)}, 'policy_hash': self.policy['policy_hash'], 'findings': [
                {'claim': None, 'state': 'error', 'cause': 'workspace directory does not exist'}]}
        snapshot = None
        if project is None or environment is None:
            snapshot = self.snapshot(root)
        project = project if project is not None else snapshot['project']
        environment = dict(environment) if environment is not None else snapshot['environment']
        interpreter = trusted_interpreter(interpreter if interpreter is not None else self._interpreter)
        context = {**binding, 'cwd': str(root.resolve()), 'environment': sorted(environment),
                   'environment_digest': digest(sorted(environment.items())), 'python': sys.version.split()[0],
                   'interpreter': str(interpreter), 'pythonpath': environment.get('PYTHONPATH'),
                   'project_digest': project['digest'], 'profile_digest': project['profile_digest'],
                   'project_contexts': {name: {k: v for k, v in value.items() if k != 'environment'}
                                        for name, value in project['contexts'].items()},
                   'limits': 'interpreter path and byte digest do not attest installed dependency immutability'}
        checks, refusals = observed_checks(self.profile, claims)
        findings = []
        deadline = time.monotonic() + self.policy['replay']['total_seconds']
        for index, claim in enumerate(checks):
            if index >= self.policy['replay']['max_claims']:
                findings.append({'claim': claim, 'state': 'not_checked', 'cause': 'claim budget exhausted'})
                continue
            findings.append({'claim': claim, **self._check(claim, project, deadline - time.monotonic())})
        findings.extend({'claim': {k: v for k, v in refusal.items() if k != 'refused'}, 'state': 'error',
                         'cause': refusal['refused']} for refusal in refusals)
        return {'context': context, 'policy_hash': self.policy['policy_hash'], 'findings': findings,
                'inspection_id': digest([context, self.policy['policy_hash'], [f['claim'] for f in findings]])}
