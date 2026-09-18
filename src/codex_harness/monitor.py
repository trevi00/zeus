"""Separate host collector and read-only web processes.

The collector reads facts only: it builds the plain service and an artifact reader wrapped
read-only, never the executor (no provider, isolation or OAuth preflight, no knowledge writes).
"""
import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from filelock import FileLock, Timeout

from codex_harness.adapters.configuration import (
    repository_root,
    runtime_dir,
    select_repository,
    settings,
)

LOG_BYTES, LOG_BACKUPS = 1024 * 1024, 2
# Sanitized operational log: event/type names and small integers only; never DSNs, env values,
# payloads or raw exception text.
LOG_FIELDS = frozenset({'mode', 'once', 'scope', 'containers', 'source', 'status', 'error', 'reason'})
LOG_VALUE = re.compile(r'[A-Za-z0-9_.:-]{1,64}')


class Journal:
    def __init__(self, path):
        self.logger = logging.getLogger('zeus.monitor.collector')
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        for old in list(self.logger.handlers):
            self.logger.removeHandler(old)
            old.close()
        self.logger.addHandler(handler)

    def write(self, event, **fields):
        safe = {key: value for key, value in fields.items() if key in LOG_FIELDS and (
            value is None or isinstance(value, bool) or type(value) is int
            or (isinstance(value, str) and LOG_VALUE.fullmatch(value)))}
        self.logger.info(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'event': event, **safe},
                                    sort_keys=True))


def source_states(result):
    return {name: (envelope.get('status'), envelope.get('error')) for name, envelope in result['sources'].items()}


def run_collector(args, root, runtime, snapshot):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.monitoring import collect, container_scope, read_only
    from codex_harness.bootstrap import build, redis_url
    journal = Journal(runtime / 'monitor-collector.log')
    config = settings()
    try:
        containers = container_scope(config.get('ZEUS_MONITOR_CONTAINERS'))
    except ValueError as exc:
        journal.write('startup_refused', reason='config_invalid', error=type(exc).__name__)
        raise
    scope = config.get('ZEUS_MONITOR_SCOPE')
    os.chdir(root)
    try:
        with FileLock(str(runtime / 'monitor-collector.lock'), timeout=0):
            service, artifacts = read_only(build(), FileArtifacts(str(runtime / 'artifacts')))
            url = redis_url()
            journal.write('startup', mode='collect', once=bool(args.once),
                          scope='named' if containers is not None else 'compose',
                          containers=len(containers) if containers is not None else None)
            previous = {}
            while True:
                result = collect(service, artifacts, str(root), url, containers, scope)
                for name, state in source_states(result).items():
                    if previous.get(name) != state:
                        journal.write('source_state', source=name, status=state[0], error=state[1])
                previous = source_states(result)
                try:
                    temp = snapshot.with_suffix('.tmp')
                    temp.write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
                    os.replace(temp, snapshot)
                except OSError as exc:
                    journal.write('snapshot_write_failed', error=type(exc).__name__)
                    raise
                if args.once:
                    journal.write('shutdown', reason='once')
                    return
                time.sleep(5)
    except Timeout:
        journal.write('startup_refused', reason='collector_lock_busy')
        return
    except KeyboardInterrupt:
        journal.write('shutdown', reason='interrupt')
        return
    except Exception as exc:
        journal.write('shutdown', reason='failure', error=type(exc).__name__)
        raise


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
    run_collector(args, root, runtime, snapshot)


if __name__ == '__main__':
    main()
