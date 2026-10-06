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
import re
import shlex
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
from codex_harness.domain.project_evidence import (
    CONTAINER_INTERPRETER,
    classify_check,
    enforceable,
    observed_checks,
    parse_profile,
    requires_container,
)

SETTING = 'HARNESS_EVIDENCE_PROFILE'
MAX_PROFILE_BYTES = 256 * 1024
MAX_DEPENDENCY_BYTES = 8 * 1024 * 1024
# `shlex.quote` makes any text one sh word; a control character would still break the one-line
# command and its permission rule, so such a value is refused rather than delivered.
UNPRINTABLE = re.compile(r'[\x00-\x1f\x7f]')


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
    if requires_container(profile):
        # A container interpreter is a path inside the pinned image: there is no host file to verify
        # and none is ever run here. Its binding is checked against the host isolation selection.
        return profile
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


def container_binding(profile, isolation):
    """The host's pinned isolation for THIS profile, or a refusal, before any provider reservation.

    Both directions are closed: a version-2 profile without isolation, a version-1 profile with it,
    and any image other than the exact host-selected one refuse here. Nothing falls back to the host.
    """
    from codex_harness.adapters.isolated_worker import IMAGE as ISOLATION_IMAGE
    from codex_harness.adapters.isolated_worker import MODE, TRUSTED_PYTHON

    require(TRUSTED_PYTHON == CONTAINER_INTERPRETER, 'The container profile interpreter must be the image interpreter')
    require(requires_container(profile), 'Project evidence profile version 1 has no container execution')
    require(isinstance(isolation, dict) and isolation.get('mode') == MODE
            and type(isolation.get('image')) is str and ISOLATION_IMAGE.fullmatch(isolation['image']),
            'A container project evidence profile requires the host isolation selection')
    require(profile['execution']['image'] == isolation['image'],
            'Project evidence execution image is not the host-selected isolation image')
    return {'kind': 'container', 'image': isolation['image'], 'mode': isolation['mode'],
            'limits': dict(isolation['limits']), 'isolation_digest': isolation['digest']}


def _container_path(relative):
    from codex_harness.adapters.isolated_worker import WORKSPACE

    return WORKSPACE if relative == '.' else WORKSPACE + '/' + relative


def resolve_container_profile(profile, cwd, isolation):
    """Every context verified against this candidate tree on the host, then mapped into the image.

    Existence, containment (symlinks included) and dependency digests are read from the real
    checkout, exactly as the host profile does; the values that EXECUTE are container paths under
    the mounted `/workspace`, the image's own interpreter and a fixed allowlisted environment. No
    host path, host interpreter or inherited host environment value reaches the container.
    """
    from codex_harness.adapters.isolated_evidence import container_environment

    binding = container_binding(profile, isolation)
    root = Path(cwd).resolve()
    require(root.is_dir(), 'Project evidence workspace directory does not exist')
    contexts = {}
    for name, context in profile['contexts'].items():
        directory = _contained(root, context['cwd'], 'Project evidence cwd')
        require(directory.is_dir(), 'Project evidence cwd is not a directory: ' + context['cwd'])
        sources = []
        for relative in context['source_paths']:
            source = _contained(root, relative, 'Project evidence source path')
            require(source.is_dir(), 'Project evidence source path is not a directory: ' + relative)
            sources.append(_container_path(relative))
        dependencies = {}
        for relative in context['dependency_files']:
            dependency = _contained(root, relative, 'Project evidence dependency file')
            require(dependency.is_file() and dependency.stat().st_size <= MAX_DEPENDENCY_BYTES,
                    'Project evidence dependency file is missing or exceeds its budget: ' + relative)
            dependencies[relative] = _file_digest(dependency)
        # The image's own fixed environment, never `replay_environment` (which is a HOST environment).
        environment = {k: v for k, v in container_environment().items() if k != 'PYTHONPATH'}
        environment['PYTHONPATH'] = ':'.join(sources)
        contexts[name] = {'cwd': _container_path(context['cwd']), 'relative_cwd': context['cwd'],
                          'interpreter': CONTAINER_INTERPRETER, 'source_paths': sources,
                          'relative_source_paths': list(context['source_paths']), 'dependency_files': dependencies,
                          'workspace': str(root), 'environment': environment,
                          'environment_digest': digest(sorted(environment.items()))}
    bound = {'profile_digest': profile['profile_digest'], 'execution': binding, 'workspace': str(root),
             'contexts': {name: {k: v for k, v in context.items() if k not in ('environment', 'workspace')}
                          for name, context in contexts.items()}}
    return {'digest': digest(bound), 'profile_digest': profile['profile_digest'], 'workspace': str(root),
            'execution': binding, 'contexts': contexts}


def shell_command(context, argv):
    """(cd part, run part) of one host check as POSIX `sh` text, every value quoted by `shlex.quote`.

    Only host values enter it: the resolved context and the host's argv, whose first token is the
    context interpreter exactly as replay substitutes it. PYTHONPATH is always assigned (empty when the
    context names no source path) so a value the worker process carries can never stand in for it."""
    require(enforceable(argv), 'Only python -m pytest and python -m ruff check have a worker command')
    effective, _ = replay_argv(argv, context['interpreter'])
    values = [context['cwd'], context['environment'].get('PYTHONPATH', ''), *effective]
    require(not any(UNPRINTABLE.search(value) for value in values), 'Project evidence command value cannot be quoted safely')
    assignments = ['PYTHONPATH=' + shlex.quote(context['environment'].get('PYTHONPATH', '')), 'PYTHONDONTWRITEBYTECODE=1']
    return 'cd ' + shlex.quote(context['cwd']), ' '.join([*assignments, *(shlex.quote(token) for token in effective)])


def _commands(profile, resolved):
    listed = []
    for check in profile['checks']:
        change, run = shell_command(resolved['contexts'][check['context']], check['argv'])
        listed.append({'check_id': check['id'], 'context': check['context'], 'command': change + ' && ' + run, 'parts': [change, run]})
    return listed


def execution_instructions(profile, cwd, resolved=None):
    """What a worker or reviewer is told: the host's checks and the context resolved for THIS checkout."""
    resolved = resolve_profile(profile, cwd) if resolved is None else resolved
    contexts = {name: {'cwd': context['cwd'], 'interpreter': context['interpreter'], 'source_paths': context['source_paths'],
                       'environment': {'PYTHONPATH': context['environment'].get('PYTHONPATH'), 'PYTHONDONTWRITEBYTECODE': '1'}}
                for name, context in resolved['contexts'].items()}
    return {'schema': profile['schema'], 'profile_digest': profile['profile_digest'], 'contexts': contexts,
            'checks': [dict(check) for check in profile['checks']],
            'commands': {entry['check_id']: entry['command'] for entry in _commands(profile, resolved)},
            'instruction': 'These checks and contexts are host-authored and replace the legacy "python on PATH" rule for '
            'these checks only. `commands` holds each check as exact POSIX sh text (cd to the context cwd, the context '
            'environment, the context interpreter in place of the first token "python"); run it verbatim from the '
            'repository root, which stays your working and editing root. In another shell use the same cwd, environment, '
            'interpreter and argv. Do not choose another argv, cwd or interpreter and do not install dependencies. Every '
            'check is required. Report what you observed, a nonzero exit included. Read results from stdout; write no '
            'output files into the checkout.'}


def worker_delivery(profile, cwd, resolved=None):
    """What the Claude transport needs for THIS implementation checkout (INV-PROJECT-EVIDENCE-001 R3):
    the exact commands, the exact per-run Bash allow rules for them and the system-prompt section.

    Derived from the host profile and the resolved checkout only, never from model output. Every rule
    is an exact command string with no wildcard: the whole compound command and, because Claude Code
    checks compound commands part by part, its `cd` part and its run part. No deny rule is touched."""
    resolved = resolve_profile(profile, cwd) if resolved is None else resolved
    commands = _commands(profile, resolved)
    allow = []
    for entry in commands:
        for text in (entry['command'], *entry.pop('parts')):
            rule = 'Bash(' + text + ')'
            if rule not in allow:
                allow.append(rule)
    lines = ['## Host project checks (this run)', '',
             'The host selected project execution contexts for this run. For the checks below, and only for them, this '
             'section overrides the "Environment" interpreter rule and the legacy `tests` command-string format above: '
             'run each command verbatim with Bash from the repository root (it changes into its own context directory; '
             'your working and editing root stays the repository root). Do not alter argv, cwd, interpreter or '
             'environment, and do not install dependencies. `tests` holds exactly one {check_id, status, exit_code} per '
             'check: executed with the exit code you observed (a failure stays a failure), or not_run with null.', '']
    lines += [f'- {entry["check_id"]} (context {entry["context"]}): `{entry["command"]}`' for entry in commands]
    return {'profile_digest': profile['profile_digest'], 'project_digest': resolved['digest'], 'workspace': resolved['workspace'],
            'commands': commands, 'permissions_allow': allow, 'document': '\n'.join(lines) + '\n'}


CONTAINER_NOTE = ('These commands run INSIDE the pinned verification image over the mounted candidate at /workspace. '
                  'The paths, the interpreter and the environment are container values: they do not exist on the host '
                  'and must never be run there.')


def container_execution_instructions(profile, cwd, isolation):
    """The reviewer's/worker's copy of the same checklist, stated in container terms.

    The check ids, contexts, argv and expected exits are the host's, identically to version 1; only
    the resolved paths, the interpreter and the environment are the image's, and the instruction says
    so explicitly so a host lead never runs these commands on its own machine."""
    from codex_harness.adapters.isolated_worker import WORKSPACE

    resolved = resolve_container_profile(profile, cwd, isolation)
    instructions = execution_instructions(profile, cwd, resolved=resolved)
    return {**instructions, 'execution': resolved['execution'], 'project_digest': resolved['digest'],
            'workspace': WORKSPACE, 'host_workspace': resolved['workspace'],
            'instruction': CONTAINER_NOTE + ' ' + instructions['instruction']}


def container_worker_delivery(profile, cwd, isolation):
    """`worker_delivery` for the isolated transport: container contexts, never host absolute paths.

    The delivered `workspace` is the container's mounted root, because that is the working directory
    the in-image runtime verifies this delivery against; the host checkout it was resolved from is
    recorded beside it as evidence only."""
    from codex_harness.adapters.isolated_worker import WORKSPACE

    resolved = resolve_container_profile(profile, cwd, isolation)
    delivery = worker_delivery(profile, cwd, resolved=resolved)
    document = delivery['document'].replace('## Host project checks (this run)',
                                            '## Host project checks (this run, inside this container)', 1)
    return {**delivery, 'execution': resolved['execution'], 'workspace': WORKSPACE,
            'host_workspace': resolved['workspace'], 'document': document}


class ProjectEvidenceInspector(EvidenceInspector):
    """The legacy inspector's policy, budgets, capture and archive, replaying host-declared checks."""

    def __init__(self, artifacts, profile, policy=None, interpreter=None):
        super().__init__(artifacts, policy, interpreter)
        require(isinstance(profile, dict) and type(profile.get('profile_digest')) is str, 'Parsed project evidence profile required')
        self.profile = profile
        self.clock = time.monotonic  # the one clock of the absolute aggregate deadline

    def snapshot(self, cwd=None):
        require(cwd is not None, 'Project evidence snapshot requires the candidate workspace')
        snapshot = super().snapshot(cwd)
        project = resolve_profile(self.profile, cwd)
        identity = {**snapshot['identity'], 'project': {
            'digest': project['digest'], 'profile_digest': project['profile_digest'], 'workspace': project['workspace'],
            'contexts': {name: {k: v for k, v in context.items() if k != 'environment'}
                         for name, context in project['contexts'].items()}}}
        return {**snapshot, 'identity': identity, 'project': project}

    def _execute_check(self, argv, context, timeout, max_bytes, progress=None):
        """WHERE one already authorized, interpreter-bound check runs. The host route is the existing
        bounded capture in the resolved context; the isolated route overrides only this method."""
        return _capture(argv, context['cwd'], timeout, max_bytes, dict(context['environment']), progress=progress)

    def _check(self, claim, project, deadline, progress=None):
        """`deadline` is the inspection's one absolute monotonic instant. The remaining allowance is
        recomputed before EVERY repeat, no repeat starts at or beyond it, and a result observed after
        it is never counted as checked: a repeat can only spend what the aggregate budget still holds.

        `progress` is the caller's per-call ownership/cancellation check (research-dispatch-001): it
        runs before and after every host check and, through `_capture`, between the bounded polls of
        its wait. Its refusal travels out of this check - a cancelled replay is never classified."""
        if claim['status'] == 'missing':
            return {'state': 'not_checked', 'cause': 'required check has no observation; not replayed'}
        if claim['status'] == 'not_run':
            return {'state': 'not_checked', 'cause': 'worker reported not_run; a required check stays incomplete and is not replayed'}
        if not (authorized(claim['argv'], self.policy) and enforceable(claim['argv'])):
            return {'state': 'not_checked', 'cause': 'command is not an authorized replay prefix; a profile is not authority'}
        context = project['contexts'][claim['context']]
        effective, transformation = replay_argv(claim['argv'], context['interpreter'])
        runs, timeouts, exhausted = [], [], None
        for attempt in range(self.policy['replay']['replays_per_claim']):
            per_command = min(self.policy['replay']['per_command_seconds'], deadline - self.clock())
            if per_command <= 0:
                exhausted = f'aggregate replay budget exhausted before replay {attempt + 1}'
                break
            finite_positive(per_command, 'replay deadline', self.policy['replay']['total_seconds'])
            timeouts.append(per_command)
            if progress is not None:
                progress('replay_start')
            run = self._execute_check(effective, context, per_command, self.policy['replay']['max_output_bytes'],
                                      progress=progress)
            runs.append(self._archive(run))
            if progress is not None:
                progress('replay_end')
            if run.get('failure'):
                break
            if self.clock() > deadline:
                exhausted = f'replay {attempt + 1} ended after the aggregate replay deadline; a late result is not counted'
                break
        observed = [run['returncode'] for run in runs]
        if exhausted is not None:
            state, cause = 'not_checked', exhausted + (f'; replay exits so far {observed}' if runs else '')
        else:
            state, cause = classify_check(claim, *classify_replays(runs, claim['expected_exit']), observed)
        return {'state': state, 'cause': cause, 'runs': runs, 'check_id': claim['check_id'], 'context': claim['context'],
                'original_argv': list(claim['argv']), 'replay_argv': effective, 'argv_transformation': transformation,
                'reported_exit': claim['reported_exit'], 'expected_exit': claim['expected_exit'], 'observed_exits': observed,
                'cwd': context['cwd'], 'interpreter': context['interpreter'],
                'timeout_seconds': timeouts[0] if timeouts else 0, 'timeouts_seconds': timeouts}

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None, project=None, progress=None):
        """The host's required checks, replayed in their own contexts, under the caller's own lease.

        `progress` is the per-call ownership/cancellation check the ledger hands to any inspector that
        declares one: the profile route takes it exactly like the legacy route, forwards it into the
        existing `_capture` polling, and never turns a refusal into a check that is reported as done.
        The snapshot, the profile digest, the allowlist and the environment are untouched by it."""
        root = Path(cwd)
        if not root.is_dir():
            return {'context': {**binding, 'cwd': str(root)}, 'policy_hash': self.policy['policy_hash'], 'findings': [
                {'claim': None, 'state': 'error', 'cause': 'workspace directory does not exist'}]}
        snapshot = None
        if project is None or environment is None:
            snapshot = self.snapshot(root)
        project = project if project is not None else snapshot['project']
        environment = dict(environment) if environment is not None else snapshot['environment']
        # `self._trusted` / `self._python`: the host route verifies a real host interpreter file
        # exactly as before; the isolated route names the image's own interpreter, which has no host file.
        interpreter = self._trusted(interpreter if interpreter is not None else self._interpreter)
        context = {**binding, 'cwd': str(root.resolve()), 'environment': sorted(environment),
                   'environment_digest': digest(sorted(environment.items())), 'python': self._python(),
                   'interpreter': str(interpreter), 'pythonpath': environment.get('PYTHONPATH'),
                   'project_digest': project['digest'], 'profile_digest': project['profile_digest'],
                   'project_contexts': {name: {k: v for k, v in value.items() if k != 'environment'}
                                        for name, value in project['contexts'].items()},
                   'limits': 'interpreter path and byte digest do not attest installed dependency immutability'}
        checks, refusals = observed_checks(self.profile, claims)
        findings = []
        deadline = self.clock() + self.policy['replay']['total_seconds']
        for index, claim in enumerate(checks):
            if index >= self.policy['replay']['max_claims']:
                findings.append({'claim': claim, 'state': 'not_checked', 'cause': 'claim budget exhausted'})
                continue
            findings.append({'claim': claim, **self._check(claim, project, deadline, progress=progress)})
        findings.extend({'claim': {k: v for k, v in refusal.items() if k != 'refused'}, 'state': 'error',
                         'cause': refusal['refused']} for refusal in refusals)
        return {'context': context, 'policy_hash': self.policy['policy_hash'], 'findings': findings,
                'inspection_id': digest([context, self.policy['policy_hash'], [f['claim'] for f in findings]])}
