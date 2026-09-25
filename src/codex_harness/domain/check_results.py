"""Check results as structured verdicts bound to what was actually executed (INV-CHECK-001).

The upstream installer reported success into an unused hook directory, its pre-push checked the
working tree instead of the pushed ref, a missing coverage input was SKIP with rc 0, empty
counters were 100 % and a zero-check run was a pass. Here a check carries the revision it was
expected to run against and the one it observed, and a test run is a pass only when its parsed
denominator says something ran and nothing failed: an exit status alone never does.
"""
import hashlib
import re
from collections import Counter

from codex_harness.domain.model import require

OUTCOMES = ('executed', 'observation_error', 'revision_mismatch', 'empty_check', 'unstructured_output',
            'coverage_mismatch')
SUMMARY = re.compile(r'(?m)^(?:=+\s*)?(?P<body>(?:\d+ (?:passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)(?:, )?)+)'
                     r'(?: in [\d.]+s)?(?:\s*=+)?\s*$')
NO_TESTS = re.compile(r'(?m)^(?:=+\s*)?no tests ran(?: in [\d.]+s)?(?:\s*=+)?\s*$')
COUNTS = ('passed', 'failed', 'skipped', 'errors', 'xfailed', 'xpassed', 'deselected', 'warnings')


def pytest_summary(stdout):
    """Parse pytest's final summary line into counts; `parsed` says whether one was found at all."""
    require(isinstance(stdout, str), 'Test output must be text')
    counts = dict.fromkeys(COUNTS, 0)
    matches = list(SUMMARY.finditer(stdout))
    if not matches:
        return {**counts, 'parsed': bool(NO_TESTS.search(stdout)), 'no_tests_ran': bool(NO_TESTS.search(stdout))}
    body = matches[-1].group('body')
    for number, word in re.findall(r'(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)', body):
        key = {'error': 'errors', 'warning': 'warnings'}.get(word, word)
        counts[key] = int(number)
    return {**counts, 'parsed': True, 'no_tests_ran': False}


def classify_test_run(returncode, stdout):
    """A test check passes only when the parsed denominator shows executed tests and no failures."""
    require(type(returncode) is int, 'Exit status must be an integer')
    summary = pytest_summary(stdout)
    if not summary['parsed']:
        return {'passed': False, 'outcome': 'unstructured_output', 'denominator': summary,
                'reason': 'no pytest summary line; the exit status alone is not a verdict'}
    executed = summary['passed'] + summary['failed'] + summary['errors'] + summary['xfailed'] + summary['xpassed']
    if summary['no_tests_ran'] or executed == 0:
        return {'passed': False, 'outcome': 'empty_check', 'denominator': summary,
                'reason': f"nothing executed: {summary['skipped']} skipped, {summary['deselected']} deselected"}
    if returncode != 0 or summary['failed'] or summary['errors']:
        return {'passed': False, 'outcome': 'executed', 'denominator': summary,
                'reason': f"exit {returncode}: {summary['failed']} failed, {summary['errors']} errors"}
    return {'passed': True, 'outcome': 'executed', 'denominator': summary,
            'reason': f"{summary['passed']} passed, {summary['skipped']} skipped, {summary['xfailed']} xfailed"}


def is_test_run(argv):
    """A pytest invocation, whichever interpreter launches it."""
    return isinstance(argv, list) and ('pytest' in argv or any(str(a).endswith('pytest') for a in argv[:2]))


def bind_revision(expected, observed, dirty):
    """The check ran against `observed`; it counts only if that is the candidate and the tree was clean."""
    require(expected is None or (type(expected) is str and expected), 'Expected revision must be text')
    if expected is None:
        return {'bound': False, 'reason': 'no candidate revision declared for this check'}
    if observed != expected:
        return {'bound': False, 'reason': f'observed HEAD {observed} is not the candidate {expected}'}
    if dirty:
        return {'bound': False, 'reason': 'workspace is dirty: the checked tree is not the candidate tree'}
    return {'bound': True, 'reason': 'observed HEAD equals the candidate and the tree is clean'}


NODE_OUTCOMES = ('passed', 'failed', 'errors', 'skipped', 'xfailed', 'xpassed', 'unknown')


def nodes_digest(nodeids):
    """The manifest hash: sha256 over the exact ordered node IDs, one per line."""
    require(isinstance(nodeids, list) and all(type(n) is str for n in nodeids), 'Node IDs must be text')
    return hashlib.sha256('\n'.join(nodeids).encode('utf-8')).hexdigest()


def plan_batches(nodeids, max_nodes):
    """Deterministic serial batches: whole files in collection order, packed up to `max_nodes`.

    A file larger than `max_nodes` is split in order. The concatenated batches are exactly the
    manifest, so no node is dropped or repeated by the plan itself.
    """
    require(type(max_nodes) is int and max_nodes > 0, 'Batch size must be a positive integer')
    require(isinstance(nodeids, list) and nodeids, 'A batch plan needs a non-empty manifest')
    require(len(set(nodeids)) == len(nodeids), 'Manifest node IDs must be unique')
    files = []
    for nodeid in nodeids:
        path = nodeid.split('::', 1)[0]
        if files and files[-1][0] == path:
            files[-1][1].append(nodeid)
        else:
            files.append((path, [nodeid]))
    batches, current = [], []
    for _, nodes in files:
        if current and len(current) + len(nodes) > max_nodes:
            batches.append(current)
            current = []
        for start in range(0, len(nodes), max_nodes):
            chunk = nodes[start:start + max_nodes]
            if len(current) + len(chunk) > max_nodes:
                batches.append(current)
                current = []
            current = current + chunk
    if current:
        batches.append(current)
    require([n for batch in batches for n in batch] == nodeids, 'Batch plan does not cover the manifest')
    return batches


def reconcile_nodes(planned, observed):
    """Compare what ran with what was planned as multisets; anything else refuses."""
    want, got = Counter(planned), Counter(observed)
    missing = sorted(n for n in want if got[n] < want[n])
    duplicate = sorted(n for n in got if got[n] > 1)
    unexpected = sorted(n for n in got if n not in want)
    return {'complete': not (missing or duplicate or unexpected), 'planned': len(planned),
            'observed': len(observed), 'missing': missing, 'duplicate': duplicate, 'unexpected': unexpected}


def node_outcome(phases):
    """One test's outcome from its setup/call/teardown reports; never a pass without a passed call."""
    failed = [p for p in phases if p.get('outcome') == 'failed']
    if any(p.get('when') == 'call' for p in failed):
        return 'failed'
    if failed:
        return 'errors'
    if any(p.get('outcome') == 'skipped' for p in phases):
        return 'xfailed' if any(p.get('xfail') for p in phases) else 'skipped'
    call = [p for p in phases if p.get('when') == 'call']
    if len(call) == 1 and call[0].get('outcome') == 'passed':
        return 'xpassed' if call[0].get('xfail') else 'passed'
    return 'unknown'


def node_results(events):
    """(nodeid, outcome) per finished test, in finish order; unfinished tests are not results."""
    phases, results = {}, []
    for event in events:
        if event.get('event') == 'phase':
            phases.setdefault(event.get('nodeid'), []).append(event)
        elif event.get('event') == 'finish':
            results.append((event.get('nodeid'), node_outcome(phases.pop(event.get('nodeid'), []))))
    return results


def last_event(events, kind):
    """The last accounting event of one kind, or None when the process never reported it."""
    return next((e for e in reversed(events) if e.get('event') == kind), None)


def classify_collection(returncode, events):
    """What a `--collect-only` run with the accounting plugin established; never an empty pass."""
    errors = [e for e in events if e.get('event') == 'collect_error']
    if returncode is None:
        return {'passed': False, 'outcome': 'observation_error', 'reason': 'collection did not finish'}
    if errors or returncode not in (0, 5):
        return {'passed': False, 'outcome': 'executed',
                'reason': f'collection failed: exit {returncode}, {len(errors)} collection errors'}
    record = last_event(events, 'collected')
    if record is None or not isinstance(record.get('nodeids'), list):
        return {'passed': False, 'outcome': 'observation_error',
                'reason': 'no accounting report: collection is unobserved, not empty'}
    nodeids = record['nodeids']
    if returncode == 5 or not nodeids:
        return {'passed': False, 'outcome': 'empty_check', 'reason': 'collection found no tests', 'nodeids': []}
    duplicate = sorted(n for n, c in Counter(nodeids).items() if c > 1)
    if duplicate or record.get('count') != len(nodeids):
        return {'passed': False, 'outcome': 'coverage_mismatch', 'duplicate': duplicate[:50],
                'reason': f'collection is ambiguous: {len(duplicate)} duplicate node IDs'}
    return {'passed': True, 'outcome': 'executed', 'reason': f'{len(nodeids)} node IDs collected', 'nodeids': nodeids}


def classify_batch(planned, manifest, returncode, events):
    """A batch passes only when it ran exactly its planned nodes of an unchanged collection and none failed.

    `manifest` is {'count', 'sha256'} of the whole collection; a batch process re-collects before
    selecting, and a different collection is drift. A process that never reached session finish
    is an observation error: what it would have reported is unknown.
    """
    counts = dict.fromkeys(NODE_OUTCOMES, 0)
    results = node_results(events)
    for _, outcome in results:
        counts[outcome] += 1
    base = {'counts': counts, 'finished': len(results)}
    if returncode is None or not any(e.get('event') == 'sessionfinish' for e in events):
        return {**base, 'passed': False, 'outcome': 'observation_error',
                'reason': 'test process ended without a session finish report'}
    collected = last_event(events, 'collected')
    if collected is None or collected.get('count') != manifest['count'] or collected.get('sha256') != manifest['sha256']:
        return {**base, 'passed': False, 'outcome': 'coverage_mismatch',
                'reason': 'batch collection differs from the manifest (drift)'}
    selected = reconcile_nodes(planned, (last_event(events, 'selected') or {}).get('nodeids') or [])
    executed = reconcile_nodes(planned, [nodeid for nodeid, _ in results])
    if not selected['complete'] or not executed['complete']:
        return {**base, 'passed': False, 'outcome': 'coverage_mismatch', 'reconciliation': executed,
                'selection': selected,
                'reason': (f"executed nodes differ from the plan: {len(executed['missing'])} missing, "
                           f"{len(executed['duplicate'])} duplicate, {len(executed['unexpected'])} unexpected")}
    errors = sum(e.get('event') == 'collect_error' for e in events)
    if returncode != 0 or counts['failed'] or counts['errors'] or counts['unknown'] or errors:
        return {**base, 'passed': False, 'outcome': 'executed', 'reconciliation': executed,
                'reason': (f"exit {returncode}: {counts['failed']} failed, {counts['errors']} errors, "
                           f"{counts['unknown']} unknown, {errors} collection errors")}
    return {**base, 'passed': True, 'outcome': 'executed', 'reconciliation': executed,
            'reason': f"{counts['passed']} passed, {counts['skipped']} skipped, {counts['xfailed']} xfailed"}


RUN_CATEGORIES = ('executed', 'isolation_unavailable', 'client_timeout', 'timeout', 'runner_error')
RUNNER_EXIT = {124: 'timeout', 137: 'timeout', 125: 'runner_error', 126: 'runner_error', 127: 'runner_error'}


def classify_isolated_run(*, stage, exit_status, stdout, stderr, command, client_timeout=False, error=None):
    """Name what an isolated run was: never a pass by exit status, empty output or a diagnostic alone.

    `stage` is where the attempt ended: `materialize` (source could not be laid out), `spawn` (the
    runner could not be started), or `run` (a child ran to some exit). Isolation failures are
    unavailable, never a substitute execution; an in-container deadline (124/137) is a timeout; the
    runner's own exits (125-127) are runner errors, not the command's verdict.
    """
    require(stage in ('materialize', 'spawn', 'run'), 'Unknown run stage')
    require(isinstance(command, list) and command, 'Command required')
    if stage != 'run':
        return {'category': 'isolation_unavailable', 'stage': stage, 'passed': False, 'reason': error or stage + ' failed',
                'output_class': 'none', 'substitute_execution': False}
    if client_timeout:
        return {'category': 'client_timeout', 'stage': stage, 'passed': False, 'output_class': 'none',
                'reason': error or 'runner client timed out; the container may have outlived the client', 'substitute_execution': False}
    require(type(exit_status) is int, 'Exit status must be an integer')
    stdout, stderr = stdout or '', stderr or ''
    output_class = 'empty' if not stdout.strip() and not stderr.strip() else 'stderr_only' if not stdout.strip() else 'stdout'
    if exit_status in RUNNER_EXIT:
        return {'category': RUNNER_EXIT[exit_status], 'stage': stage, 'passed': False, 'exit_status': exit_status,
                'output_class': output_class, 'reason': f'exit {exit_status} belongs to the runner or its deadline, not the command'}
    result = {'category': 'executed', 'stage': stage, 'exit_status': exit_status, 'output_class': output_class}
    if is_test_run(command):
        verdict = classify_test_run(exit_status, stdout)
        return {**result, **verdict, 'mode': 'pytest'}
    if exit_status != 0:
        return {**result, 'passed': False, 'mode': 'command', 'reason': f'exit {exit_status}'}
    if output_class == 'empty':
        return {**result, 'passed': False, 'mode': 'command', 'reason': 'exit 0 with no output: nothing observable ran'}
    if output_class == 'stderr_only':
        return {**result, 'passed': False, 'mode': 'command', 'reason': 'exit 0 with diagnostics only on stderr; not a verdict'}
    return {**result, 'passed': True, 'mode': 'command', 'reason': 'exit 0 with output'}
