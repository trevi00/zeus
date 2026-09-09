"""Bounded original check/launcher observations; no gate writer, suite or live state."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from engine import checks

BASE = Path('/tmp/entry-observations')


def main():
    BASE.mkdir()
    home = BASE / 'driver-home'
    project = BASE / 'project'
    (home / 'config').mkdir(parents=True)
    project.mkdir()
    runtime = f'python_exe: {sys.executable}\n'
    (home / 'config/runtime.yaml').write_text(runtime)
    os.environ['HARNESS_HOME'] = str(home)
    os.environ['HARNESS_STATE_DIR'] = str(BASE / 'state')
    probe = project / 'process_probe.py'
    body = 'import os,sys\nprint("HARNESS_HOME="+os.environ.get("HARNESS_HOME",""))\nprint("OBSERVED metric=42")\nraise SystemExit(int(sys.argv[1]))\n'
    probe.write_text(body)
    (project / 'config.txt').write_text('enabled\n')
    (project / 'a.txt').write_text('REQUIRED\n')
    (project / 'b.txt').write_text('unrelated\n')
    cmd = f'{{python}} "{probe}" 1'
    good = f'{{python}} "{probe}" 0'
    specs = [
        ('exit-code-failure', {'type': 'exit_code', 'cmd': cmd}),
        ('metric-failed-process', {'type': 'metric_threshold', 'cmd': cmd,
                                   'extract': r'metric=(\d+)', 'op': '>=', 'value': 40}),
        ('trigger-failed-process', {'type': 'trigger_effect', 'config_target': 'config.txt',
                                    'config_expect': 'enabled', 'observe_cmd': cmd,
                                    'observe_expect': 'OBSERVED'}),
        ('db-failed-process', {'type': 'db_query', 'cmd': cmd, 'expect': 'OBSERVED'}),
        ('exit-code-success', {'type': 'exit_code', 'cmd': good}),
        ('windows-set-prefix-on-linux', {'type': 'exit_code',
                                         'cmd': 'set "HARNESS_HOME=%CD%" && ' + good}),
        ('repeat-fraction', {'type': 'exit_code', 'cmd': good, 'repeat': 1.9}),
        ('repeat-boolean', {'type': 'exit_code', 'cmd': good, 'repeat': True}),
        ('required-across-files', {'type': 'file_content', 'target': '[ab].txt', 'expect': 'REQUIRED'}),
    ]
    results = []
    for name, spec in specs:
        verdict, evidence = checks.run(spec, project)
        results.append({'name': name, 'input': spec, 'verdict': verdict, 'evidence': evidence})
    launchers = []
    for name in ('dispatch.sh', 'hud_launcher.sh', 'rlm_launcher.sh'):
        path = Path('/source/scripts/handlers') / name
        argv = ['sh', str(path)]
        if name == 'dispatch.sh':
            argv.append('SessionStart')
        result = subprocess.run(argv, cwd=project, input=b'{}', capture_output=True, timeout=5)
        launchers.append({'name': name, 'argv': argv, 'returncode': result.returncode,
                          'stdout': result.stdout.decode('utf-8'),
                          'stderr': result.stderr.decode('utf-8'),
                          'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    fixtures = [{'path': str(path.relative_to(BASE)), 'content': path.read_text(),
                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(BASE.rglob('*')) if path.is_file()]
    print(json.dumps({'scope': 'nine direct original checks and three original shell launchers; no gate writer or source suite',
                      'source': 'a3f8b3be9a0a389329de6e16a6c7db81782041a3',
                      'checks_sha256': hashlib.sha256(Path(checks.__file__).read_bytes()).hexdigest(),
                      'python': sys.version, 'driver_home': str(home), 'project': str(project),
                      'source_runtime_pin_exists': Path('/source/config/runtime.yaml').exists(),
                      'fixtures': fixtures, 'checks': results, 'launchers': launchers}, ensure_ascii=False))


if __name__ == '__main__':
    main()
