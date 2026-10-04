"""The `zeus dlq` composition: the dead-letter operator over the store and the Redis bus (S10 A5-1b, DESIGN-s10 §17a).

Layer: composition
Owns: dead_letters
Does not own: the argument shape and the command bodies (entry.cli.dlq) and the list/replay policy
    (coordination.application.dead_letters)
Entry points: dead_letters
Contracts: INV-MESSAGE-001

A declared target addition (no M7 counterpart). Imports sit inside the function, so importing this module stays light.
"""


def dead_letters():
    from codex_harness.composition import build, cli_bus
    from codex_harness.coordination.application.dead_letters import DeadLetters
    from codex_harness.kernel.ids import SYSTEM_CLOCK
    return DeadLetters(build().store, cli_bus.bus(), clock=SYSTEM_CLOCK)
