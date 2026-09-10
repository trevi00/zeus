"""Check results as structured verdicts bound to what was actually executed (INV-CHECK-001).

The upstream installer reported success into an unused hook directory, its pre-push checked the
working tree instead of the pushed ref, a missing coverage input was SKIP with rc 0, empty
counters were 100 % and a zero-check run was a pass. Here a check carries the revision it was
expected to run against and the one it observed, and a test run is a pass only when its parsed
denominator says something ran and nothing failed: an exit status alone never does.
"""
import re

from codex_harness.domain.model import require

OUTCOMES = ('executed', 'observation_error', 'revision_mismatch', 'empty_check', 'unstructured_output')
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
