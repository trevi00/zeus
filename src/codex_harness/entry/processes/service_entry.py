"""Entry of the journalled service process (M7 `adapters/service_entry.py` main).

Layer: entry
Owns: the choice of the CLI the service runs (`codex_harness.entry.cli.main`, injected as `cli_main`)
Does not own: the argv, the journal and the exit mapping (host_os.adapters.service_entry) and the wiring (composition.process_entries)
Entry points: main
Contracts: none

`python -m codex_harness.entry.processes.service_entry --journal PATH -- CLI_ARGS`.
"""
import sys

from codex_harness.composition import process_entries
from codex_harness.entry import cli


def main(argv=None) -> int:
    return process_entries.service_entry_main(argv, cli_main=cli.main)


if __name__ == "__main__":
    sys.exit(main())
