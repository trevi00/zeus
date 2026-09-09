"""Run original Bash collision checker on real temporary files, without a database."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

SOURCE = Path('/source/tools/check-flyway-collision.sh')
BASE = Path('/tmp/collision-observations')


def run_case(name, files, *, discover=False, inaccessible=False, missing=False):
    directory = BASE / name
    directory.mkdir(parents=True)
    fixtures = []
    for relative in files:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b'-- inert observation input; SQL is never executed\n'
        path.write_bytes(raw)
        fixtures.append({'path': relative, 'content': raw.decode(),
                         'sha256': hashlib.sha256(raw).hexdigest()})
    if inaccessible:
        directory.chmod(0)
    argv = ['bash', str(SOURCE)]
    if not discover:
        argv.append(str(directory / 'missing' if missing else directory))
    try:
        result = subprocess.run(argv, cwd=BASE if inaccessible else directory,
                                capture_output=True, timeout=5)
    finally:
        if inaccessible:
            directory.chmod(0o700)
    return {'name': name, 'argv': argv, 'cwd': str(BASE if inaccessible else directory),
            'fixtures': fixtures, 'directory_mode': '000' if inaccessible else 'default',
            'returncode': result.returncode, 'stdout': result.stdout.decode('utf-8'),
            'stderr': result.stderr.decode('utf-8'),
            'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
            'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()}


def main():
    BASE.mkdir()
    cases = [
        run_case('ordinary-distinct', ['V1__a.sql', 'V2__b.sql']),
        run_case('ordinary-duplicate', ['V1__a.sql', 'V1__b.sql']),
        run_case('dotted-distinct', ['V1.1__a.sql', 'V1.2__b.sql']),
        run_case('underscore-distinct', ['V1_1__a.sql', 'V1_2__b.sql']),
        run_case('zero-padding', ['V01__a.sql', 'V1__b.sql']),
        run_case('octal-eight', ['V08__a.sql']),
        run_case('nondigit-version', ['Vbad__a.sql']),
        run_case('empty', []),
        run_case('missing', [], missing=True),
        run_case('unreadable', ['V1__a.sql', 'V1__b.sql'], inaccessible=True),
        run_case('multi-module-vendor', [
            'a/db/migration/mysql/V1__a.sql',
            'a/db/migration/postgresql/V1__a.sql',
            'a/db/migration/mysql/V2__missing_in_postgres.sql',
            'z/db/migration/mysql/V1__a.sql',
            'z/db/migration/postgresql/V1__a.sql'], discover=True),
        run_case('parity-gap-control', [
            'a/db/migration/mysql/V1__a.sql',
            'a/db/migration/postgresql/V2__b.sql'], discover=True),
    ]
    print(json.dumps({'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                      'bash_version': subprocess.run(['bash', '--version'], capture_output=True,
                                                     text=True, check=True).stdout,
                      'flyway_available': shutil.which('flyway'),
                      'scope': 'original Bash on scratch files; no Flyway/DB/Windows/WSL acceptance',
                      'cases': cases}, ensure_ascii=False))


if __name__ == '__main__':
    main()
