"""Offline scratch observations of original isolation helpers and golden.run only."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys

from engine import golden

BASE = Path('/tmp/environment-observations')


def main():
    BASE.mkdir()
    module = Path('/source/tests/_isolate.py')
    isolate = runpy.run_path(str(module))
    key = 'HARNESS_STATE_DIR'
    rows = []
    os.environ[key] = 'relative-uncreated-state'
    os.environ['HARNESS_HOME'] = str(BASE / 'outside')
    os.environ['HARNESS_L2_SPAWN'] = '1'
    got = isolate['isolate']()
    rows.append({'name': 'inherited-state', 'returned': str(got), 'exists': got.exists(),
                 'home_present': 'HARNESS_HOME' in os.environ,
                 'driver_stamp_present': 'HARNESS_L2_SPAWN' in os.environ})
    os.environ.pop(key)
    got = isolate['isolate']()
    rows.append({'name': 'new-state', 'returned': str(got), 'exists': got.is_dir(),
                 'env_equals_returned': os.environ[key] == str(got)})
    os.environ[key] = str(BASE / 'original-state')
    with isolate['real_state']():
        during = key in os.environ
        os.environ[key] = str(BASE / 'replacement-state')
    rows.append({'name': 'real-state-existing', 'present_during_entry': during,
                 'restored': os.environ.get(key)})
    os.environ.pop(key)
    with isolate['real_state']():
        os.environ[key] = str(BASE / 'new-inside-block')
    rows.append({'name': 'real-state-absent', 'value_after': os.environ.get(key)})
    before = os.environ.get(key)
    fresh = isolate['fresh_state']()
    rows.append({'name': 'fresh-state', 'exists': fresh.is_dir(),
                 'environment_unchanged': before == os.environ.get(key)})
    path = BASE / 'same-size.txt'
    path.write_bytes(b'AAAA')
    stat = path.stat()
    first = isolate['live_fingerprint'](str(path))
    path.write_bytes(b'BBBB')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = isolate['live_fingerprint'](str(path))
    rows.append({'name': 'same-size-restored-time', 'before': first, 'after': second,
                 'equal': first == second, 'before_content': 'AAAA', 'after_content': path.read_text()})

    def unavailable():
        raise OSError('scratch probe unavailable')

    with isolate['live_axis']('same-error', unavailable) as handle:
        try:
            bool(handle)
        except RuntimeError:
            early_rejected = True
    rows.append({'name': 'same-probe-error', 'before': handle.before, 'after': handle.after,
                 'stable_after': bool(handle), 'early_bool_rejected': early_rejected})
    propagated = False
    try:
        with isolate['live_axis']('body-error', str(path)):
            raise ValueError('original-body-error')
    except ValueError as exc:
        propagated = str(exc) == 'original-body-error'
    rows.append({'name': 'body-exception', 'propagated': propagated})
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        with isolate['live_axis']('changed-size', str(path)) as handle:
            path.write_bytes(b'LONGER')
    rows.append({'name': 'changed-size', 'stable': bool(handle), 'skip_output': stream.getvalue()})

    home = BASE / 'golden-home'
    (home / 'config').mkdir(parents=True)
    (home / 'knowledge/golden').mkdir(parents=True)
    (home / 'config/runtime.yaml').write_text(f'python_exe: {sys.executable}\n')
    os.environ['HARNESS_HOME'] = str(home)
    os.environ[key] = str(BASE / 'golden-state')
    probe = home / 'probe.py'
    probe.write_text('import pathlib,sys\nwith pathlib.Path("calls.txt").open("a") as f: f.write("called\\n")\nprint("TOKEN",file=sys.stderr)\nraise SystemExit(int(sys.argv[1]))\n')
    cases = home / 'knowledge/golden/cases.yaml'
    outputs = []

    def observe(name, document):
        if document is not None:
            cases.write_text(document)
        count_before = (home / 'calls.txt').read_text().count('called\n') if (home / 'calls.txt').exists() else 0
        try:
            result = {'result': golden.run(home)}
        except Exception as exc:
            result = {'error_type': type(exc).__name__, 'error': str(exc)}
        count_after = (home / 'calls.txt').read_text().count('called\n') if (home / 'calls.txt').exists() else 0
        outputs.append({'name': name, 'input_document': document, 'fixture_commands': count_after - count_before, **result})

    observe('missing-cases', None)
    observe('invalid-entries', '[42, "text", {"name":"missing-command"}]')
    observe('mapping-root', '{"cmd":"unused"}')
    command = f'{{python}} "{probe}"'
    observe('stderr-match', json.dumps([{'name': 'stderr', 'cmd': command + ' 0', 'expect_exit': 0, 'expect_contains': 'TOKEN'}]))
    observe('expected-failure-control', json.dumps([{'name': 'negative', 'cmd': command + ' 1', 'expect_exit': 1}]))
    observe('invalid-expect-exit', json.dumps([{'name': 'invalid', 'cmd': command + ' 0', 'expect_exit': 'not-an-integer'}]))
    observe('duplicate-name', json.dumps([{'name': 'same', 'cmd': command + ' 0'}, {'name': 'same', 'cmd': command + ' 0'}]))
    fixtures = [{'path': str(p.relative_to(BASE)), 'content': p.read_text(),
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(BASE.rglob('*')) if p.is_file()]
    print(json.dumps({'source': 'a3f8b3be9a0a389329de6e16a6c7db81782041a3',
                      'isolation_source_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
                      'golden_source_sha256': hashlib.sha256(Path(golden.__file__).read_bytes()).hexdigest(),
                      'python': sys.version, 'isolation_scenarios': rows,
                      'golden_run_observations': outputs, 'fixtures': fixtures,
                      'original_golden_cases_executed': 0, 'gatewriter_executed': False,
                      'source_suite_executed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
