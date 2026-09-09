"""Reviewer execution harness; explicit already-read tests only, never upstream host execution."""
from pathlib import Path
import datetime
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / '.runtime/absorption/sources/harness/pinned'
OUT = Path(__file__).resolve().parent
IMAGE = 'sha256:39d4f226fa8b1ae6087b283b16d0176e9181f8aaf31dcbf0c9145e513453725a'
for test in sys.argv[1:]:
    assert test.startswith('tests/') and '..' not in Path(test).parts
    argv = ['docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--memory', '512m', '--cpus', '1', '--pids-limit', '100',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m', '--mount',
            f'type=bind,source={SOURCE},target=/source,readonly',
            '--workdir', '/source', '--env', 'HOME=/tmp/review-empty-home',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONIOENCODING=utf-8',
            '--env', 'CODEX_LIVE=0', '--entrypoint', 'timeout', IMAGE, '180', 'python', test]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', timeout=210)
        rc, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        rc, stdout, stderr = None, str(exc.stdout or ''), str(exc.stderr or '')
    receipt = dict(test=test, source_revision='a3f8b3be9a0a389329de6e16a6c7db81782041a3',
                   test_sha256=hashlib.sha256((SOURCE / test).read_bytes()).hexdigest(),
                   image=IMAGE, argv=argv, started_utc=started, elapsed_s=time.monotonic()-t,
                   returncode=rc, stdout=stdout, stderr=stderr,
                   limits=['source-only readonly network-none no host credentials',
                           'CODEX_LIVE=0; provider actual roundtrip not run',
                           'test executable code read; full test repository not reviewed'])
    (OUT / (Path(test).stem + '.receipt.json')).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(test, rc, stdout[-300:], stderr[-300:])
