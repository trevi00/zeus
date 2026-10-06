"""Entry of the `zeus-monitor` process: `collect | web | desk` (M7 `monitor.main`, R-e2).

Layer: entry
Owns: the argument shape and the mode dispatch
Does not own: the collect loop, the desk service, the refusal rule and the production CollectorPorts (composition.monitor), the desk routes (entry.http.desk)
Entry points: main
Contracts: INV-MONITOR-VIEWER-001

M7 `monitor.main` (:160-186, SOURCE e38aa722) statement for statement: the refusal is checked before any listener binds, the web branch is the read-only viewer, the desk branch
injects this package's `entry.http.desk` module as the `DeskHttp` (entry -> entry), and the collect branch runs the collector.
"""
import argparse
from pathlib import Path

from codex_harness.composition.configuration import repository_root, runtime_dir, select_repository, settings
from codex_harness.composition.monitor import listener_refusal, run_collector, serve_desk, serve_web
from codex_harness.entry.http import desk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['collect', 'web', 'desk'])
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--port', type=int, default=None)
    args = parser.parse_args()
    refusal = listener_refusal(args.mode, args.port, settings().get('ZEUS_DESK_REVISION'))
    if refusal is not None:
        raise SystemExit(refusal)
    if args.repository:
        select_repository(args.repository)
    root = repository_root()
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    snapshot = runtime / 'monitoring.json'
    if args.mode in ('web', 'desk'):
        if args.mode == 'web':
            # The viewer listener: read-only, no desk, whatever the environment says (checked above).
            serve_web(snapshot, args.port)
        else:
            serve_desk(snapshot, args.port, desk_http=desk)
        return
    run_collector(args, root, runtime, snapshot)
