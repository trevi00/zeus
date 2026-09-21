"""Host-authored project verification contract as data (INV-PROJECT-EVIDENCE-001).

A project profile is operator configuration: named execution contexts (cwd, interpreter, source
paths, dependency files) and named required checks (context, argv, expected exit). The worker
never chooses argv, cwd, interpreter or whether a check is required; it reports one observation
per declared check (`executed` with its exit status, or `not_run`). A reported failure stays a
failure, a `not_run` stays incomplete, and an observation for an undeclared, repeated or missing
check is an explicit non-checked finding. Replay authority is still the packaged evidence policy
(INV-EVIDENCE-001): a profile cannot authorize a command the allowlist refuses.

Version 2 is the same contract with one explicit closed addition: `execution`, which names the
container image the host pinned for isolation. It changes WHERE the checks run, never who owns
them. A version-2 context interpreter must be the trusted in-image interpreter, so a host
interpreter can never be silently reinterpreted as a container path (and the reverse); version 1
stays a host profile and keeps refusing isolation. Everything else - the checks grammar, the worker
schema, the observation rules and the classifier - is shared by both versions.
"""
import re

from codex_harness.domain.evidence import MAX_ARGV, authorized
from codex_harness.domain.model import digest, require

SCHEMA = 'urn:zeus:project-evidence:1'
SCHEMA_V2 = 'urn:zeus:project-evidence:2'
SCHEMAS = (SCHEMA, SCHEMA_V2)
PROFILE_KEYS = frozenset({'schema', 'contexts', 'checks'})
PROFILE_KEYS_V2 = frozenset({'schema', 'contexts', 'checks', 'execution'})
EXECUTION_KEYS = frozenset({'kind', 'image'})
CONTAINER = 'container'
# The trusted in-image interpreter (adapters.isolated_worker.TRUSTED_PYTHON). Stated here as data so
# the domain stays adapter-free; the adapter asserts the two are the same string.
CONTAINER_INTERPRETER = '/opt/zeus/bin/python'
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
CONTEXT_KEYS = frozenset({'cwd', 'interpreter', 'source_paths', 'dependency_files'})
CHECK_KEYS = frozenset({'id', 'context', 'argv', 'expected_exit'})
OBSERVATION_KEYS = frozenset({'check_id', 'status', 'exit_code'})
STATUSES = ('executed', 'not_run')
KIND = 'project_check'
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
MAX_CONTEXTS = 16
MAX_PATHS = 32
# Version 1 is Python-only by decision: replay enforces a context interpreter solely by replacing the
# first token of `python -m ...`, so any other authorized form (`uv run ...`, bare `ruff`) would reach
# the child unchanged while the finding named an interpreter it never ran. Those forms are refused
# here; the legacy unprofiled contract keeps them.
PROFILE_ARGV_PREFIXES = (('python', '-m', 'pytest'), ('python', '-m', 'ruff', 'check'))


def enforceable(argv):
    """Whether replay binds this argv to the context interpreter (intersected with the allowlist)."""
    return any(tuple(argv[:len(prefix)]) == prefix for prefix in PROFILE_ARGV_PREFIXES)


def safe_relative(path, name, *, allow_root=False):
    """A workspace-relative path: no absolute form, drive, traversal or NUL. Containment of the
    resolved path (symlinks included) is the adapter's check against the actual candidate root."""
    require(type(path) is str and path and '\x00' not in path and len(path) <= 512, f'{name} must be a relative path')
    if path == '.':
        require(allow_root, f'{name} cannot be the workspace root')
        return '.'
    normalized = path.replace('\\', '/')
    parts = normalized.split('/')
    require(not normalized.startswith('/') and not re.match(r'[A-Za-z]:', normalized)
            and all(part and part not in ('.', '..') for part in parts),
            f'{name} must be relative and inside the workspace')
    return normalized


def _paths(value, name):
    require(isinstance(value, list) and len(value) <= MAX_PATHS, f'{name} must be a bounded list')
    paths = [safe_relative(item, name, allow_root=False) for item in value]
    require(len(set(paths)) == len(paths), f'{name} must be distinct')
    return paths


def _execution(document):
    """Version 2's closed `execution`: the immutable container image the host pinned, or None (v1)."""
    if document['schema'] == SCHEMA:
        require(set(document) == PROFILE_KEYS, 'Project evidence profile must carry schema, contexts, checks')
        return None
    require(set(document) == PROFILE_KEYS_V2,
            'Project evidence profile version 2 must carry schema, contexts, checks, execution')
    execution = document['execution']
    require(isinstance(execution, dict) and set(execution) == EXECUTION_KEYS, 'Project evidence execution fields')
    require(execution['kind'] == CONTAINER, 'Project evidence execution kind must be container')
    require(type(execution['image']) is str and IMAGE.fullmatch(execution['image']),
            'Project evidence execution image must be an immutable sha256:<64hex> image id')
    return {'kind': CONTAINER, 'image': execution['image']}


def requires_container(profile):
    """Whether this parsed profile may run only in the host's pinned isolation image."""
    return isinstance(profile, dict) and profile.get('schema') == SCHEMA_V2


def parse_profile(document, policy):
    """The closed, normalized profile with its digest. Every check is a required acceptance check."""
    require(isinstance(document, dict) and type(document.get('schema')) is str, 'Project evidence profile must carry a schema')
    require(document['schema'] in SCHEMAS, 'Unknown project evidence profile schema')
    execution = _execution(document)
    contexts = document['contexts']
    require(isinstance(contexts, dict) and 0 < len(contexts) <= MAX_CONTEXTS, 'Project evidence contexts must be a nonempty mapping')
    parsed = {}
    for name in sorted(contexts):
        context = contexts[name]
        require(type(name) is str and SAFE_ID.fullmatch(name), 'Project evidence context id must be a safe short id')
        require(isinstance(context, dict) and set(context) == CONTEXT_KEYS, 'Project evidence context fields')
        interpreter = context['interpreter']
        require(type(interpreter) is str and interpreter and '\x00' not in interpreter and len(interpreter) <= 1024,
                'Project evidence interpreter must be an absolute host path')
        # No silent reinterpretation: a container profile names the trusted in-image interpreter and
        # nothing else. A version-1 interpreter is a HOST path whatever it spells, and it is still
        # verified as an existing host file before any replay, so the two can never be confused.
        require(execution is None or interpreter == CONTAINER_INTERPRETER,
                'Project evidence version 2 requires the container interpreter ' + CONTAINER_INTERPRETER)
        parsed[name] = {'cwd': safe_relative(context['cwd'], 'Project evidence cwd', allow_root=True),
                        'interpreter': interpreter,
                        'source_paths': _paths(context['source_paths'], 'Project evidence source_paths'),
                        'dependency_files': _paths(context['dependency_files'], 'Project evidence dependency_files')}
    checks = document['checks']
    require(isinstance(checks, list) and 0 < len(checks) <= policy['replay']['max_claims'],
            'Project evidence checks must be a nonempty list within the claim budget')
    listed = []
    for check in checks:
        require(isinstance(check, dict) and set(check) == CHECK_KEYS, 'Project evidence check fields')
        require(type(check['id']) is str and SAFE_ID.fullmatch(check['id']), 'Project evidence check id must be a safe short id')
        require(check['id'] not in {c['id'] for c in listed}, 'Project evidence check ids must be distinct')
        require(check['context'] in parsed, 'Project evidence check names an unknown context')
        argv = check['argv']
        require(isinstance(argv, list) and 0 < len(argv) <= MAX_ARGV
                and all(type(a) is str and a and '\x00' not in a for a in argv), 'Project evidence check argv must be non-empty text tokens')
        # The SAME packaged allowlist: a host profile cannot widen replay authority.
        require(authorized(argv, policy), 'Project evidence check argv is not an authorized replay prefix')
        require(enforceable(argv), 'Project evidence check argv must be python -m pytest or python -m ruff check: '
                'profile version 1 enforces the context interpreter only for those forms')
        require(type(check['expected_exit']) is int and 0 <= check['expected_exit'] <= 255,
                'Project evidence expected_exit must be an exit status')
        listed.append({'id': check['id'], 'context': check['context'], 'argv': list(argv), 'expected_exit': check['expected_exit']})
    profile = {'schema': document['schema'], 'contexts': parsed, 'checks': listed}
    if execution is not None:
        profile['execution'] = execution
    profile['profile_digest'] = digest(profile)
    return profile


def worker_schema(profile):
    """The profile-aware worker answer: still {summary, tests}; each tests entry is an observation of
    a host-declared check. A fresh object per call; nothing global is mutated."""
    observation = {'type': 'object', 'additionalProperties': False,
                   'properties': {'check_id': {'type': 'string', 'enum': [c['id'] for c in profile['checks']]},
                                  'status': {'type': 'string', 'enum': list(STATUSES)},
                                  'exit_code': {'type': ['integer', 'null']}},
                   'required': ['check_id', 'status', 'exit_code']}
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'summary': {'type': 'string', 'description': 'What changed and what was observed: actual results, '
                                       'failures, skipped tests with reasons, diagnostic attempts and what was not run.'},
                           'tests': {'type': 'array', 'items': observation,
                                     'description': 'Exactly one observation per host-declared check id: status executed '
                                     'with the integer exit_code you observed (failures included, never rewritten), or '
                                     'not_run with exit_code null. No other commands; those belong in summary.'}},
            'required': ['summary', 'tests']}


def _claim(check, status, reported_exit):
    body = {'kind': KIND, 'check_id': check['id'], 'context': check['context'], 'argv': list(check['argv']),
            'expected_exit': check['expected_exit'], 'status': status, 'reported_exit': reported_exit}
    return {**body, 'origin': 'host_profile', 'id': digest([KIND, body])}


def observed_checks(profile, observations):
    """One claim per declared check in host order, then one refusal per unusable observation.

    A claim's status is `executed`, `not_run` or `missing`; argv, context and expected exit are always
    the host's. Refusals (`refused` set) are malformed, unknown or duplicate observations: they are
    findings, so they can never be dropped into an all_checked verdict.
    """
    declared = {check['id']: check for check in profile['checks']}
    seen, refusals = {}, []
    for raw in observations if isinstance(observations, list) else [observations]:
        shown = {'kind': KIND, 'raw': repr(raw)[:500]}
        if not (isinstance(raw, dict) and set(raw) == OBSERVATION_KEYS and type(raw['check_id']) is str):
            refusals.append({**shown, 'refused': 'observation must carry exactly check_id, status, exit_code'})
        elif raw['check_id'] not in declared:
            refusals.append({**shown, 'refused': 'observation names a check the host did not declare'})
        elif raw['check_id'] in seen:
            refusals.append({**shown, 'refused': 'duplicate observation for check ' + raw['check_id']})
        elif raw['status'] == 'executed' and type(raw['exit_code']) is int:
            seen[raw['check_id']] = ('executed', raw['exit_code'])
        elif raw['status'] == 'not_run' and raw['exit_code'] is None:
            seen[raw['check_id']] = ('not_run', None)
        else:
            seen[raw['check_id']] = None
            refusals.append({**shown, 'refused': 'executed needs an integer exit_code and not_run needs null'})
    claims = []
    for check in profile['checks']:
        status, reported = seen.get(check['id']) or ('missing', None)
        claims.append(_claim(check, status, reported))
    return claims, refusals


def classify_check(claim, state, cause, observed_exits):
    """Replay agreement alone is not a pass: the worker's reported exit must equal the host's expected
    exit too. A reported failure is retained, never coerced to the expectation."""
    if state == 'checked' and claim['reported_exit'] != claim['expected_exit']:
        return 'verified_mismatch', (f'worker reported exit {claim["reported_exit"]}, host expected {claim["expected_exit"]}; '
                                     f'replay exits {observed_exits}')
    return state, cause
