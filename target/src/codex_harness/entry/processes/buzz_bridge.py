"""Entry of the Buzz bridge process: `--config PATH` (Buzz DESIGN-D §2).

Layer: entry
Owns: argument parsing and the signal flag; delegates to the one composition function and defaults the world to
    `buzz_world.zeus_world`
Does not own: the loop, the use cases or the Zeus read side (composition)
Entry points: main
Contracts: INV-OBSERVATION-001

SIGTERM and SIGINT handlers ONLY set a flag (RESEARCH-D D1): the loop reads it between steps and in its wait slices,
so no handler runs store or relay work. A refused config exits 2 with the refusal text (never a secret value).
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from codex_harness.composition.buzz_bridge import BridgeConfig, build_runtime
from codex_harness.composition.buzz_world import zeus_world
from codex_harness.kernel.errors import ContractError

EXIT_REFUSED = 2


def main(argv=None, *, world_factory=None, **wiring) -> int:
    parser = argparse.ArgumentParser(prog="codex_harness.entry.processes.buzz_bridge")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        config = BridgeConfig.from_file(args.config)
        if world_factory is None:  # the default: the real Zeus world, read through the process's own clock
            def world_factory(store):
                return zeus_world(store, config, clock=time.time)
        runtime = build_runtime(config, world_factory=world_factory, **wiring)
    except ContractError as exc:
        print(f"buzz bridge refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    flag = []
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: flag.append(True))  # the handler only sets the flag
    return runtime.run(lambda: bool(flag))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
