"""Entry of the isolated worker's operator steps (M7 `adapters/isolated_worker.py` `__main__`; INV-ISOLATED-WORKER-001).

Layer: entry
Owns: the argv shape of `python -m codex_harness.entry.processes.isolated_worker status <dir>...|reconcile <dir>`
Does not own: the run records and the reconcile rule (execution.adapters.containers.cleanup_ledger) and the Docker runner (composition.process_entries)
Entry points: main
Contracts: INV-ISOLATED-WORKER-001

The body is M7 :1233-1239 verbatim except the composition calls and that bad argv is `SystemExit(2)` from `main`.
"""
import json
import sys

from codex_harness.composition import process_entries


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "status":  # the worker's runs and the verifier's replays alike
        print(json.dumps(process_entries.isolated_worker_status(argv[1:]), sort_keys=True))
    elif len(argv) == 2 and argv[0] == "reconcile":
        print(json.dumps(process_entries.isolated_worker_reconcile(argv[1]), sort_keys=True))
    else:
        raise SystemExit(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
