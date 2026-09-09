"""Separate host collector and read-only web processes."""
import argparse
import json
import os
import time
from pathlib import Path

from filelock import FileLock, Timeout

from codex_harness.adapters.configuration import repository_root, runtime_dir, select_repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['collect', 'web'])
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    if args.repository:
        select_repository(args.repository)
    root = repository_root()
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    snapshot = runtime / 'monitoring.json'
    if args.mode == 'web':
        from codex_harness.adapters.monitoring_web import serve
        serve(snapshot, args.port)
        return
    from codex_harness.adapters.monitoring import collect
    from codex_harness.bootstrap import build_executor, redis_url
    os.chdir(root)
    try:
        with FileLock(str(runtime / 'monitor-collector.lock'), timeout=0):
            executor = build_executor()
            while True:
                result = collect(executor.service, executor.artifacts, str(root), redis_url())
                temp = snapshot.with_suffix('.tmp')
                temp.write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
                os.replace(temp, snapshot)
                if args.once:
                    return
                time.sleep(5)
    except Timeout:
        return


if __name__ == '__main__':
    main()
