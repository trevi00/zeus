"""The `zeus` CLI composition: the bus builders (S10 unit C4, R-c8).

Layer: composition
Owns: flusher, bus, spool
Does not own: any root's argument shape or body (entry.cli) and the observer builders (composition.observation)
Entry points: flusher, bus, spool
Contracts: none

Replaces `Harness.flush_outbox` and `RedisBus(redis_url())` of M7 `cli.py` (SOURCE e38aa722:760-765, 820-827): `flusher` wires
`OutboxFlusher` as `tests/ported/m7_coordination.Harness.__init__` does, and `bus` supplies the namespace M7's `RedisBus` read from
`HARNESS_REDIS_NAMESPACE` itself (the target `RedisBus` takes it from composition).
Imports sit inside the functions, so importing this module stays light (no redis).
"""


def flusher(service):
    from codex_harness.coordination.application.outbox_relay import OutboxFlusher
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.observation.application.health import HealthRecords
    return OutboxFlusher(service.store, service.org, health=HealthRecords().record, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def bus():
    from codex_harness.composition import redis_url
    from codex_harness.composition.configuration import settings
    from codex_harness.storage.adapters.redis_bus import RedisBus
    return RedisBus(redis_url(), settings().get("HARNESS_REDIS_NAMESPACE", "codex-harness"))


def spool():
    """`SpoolDirectory(observation_root())` of M7 `observe_command` (an entry module may not import the adapter)."""
    from codex_harness.composition.observation import observation_root
    from codex_harness.observation.adapters.observation_spool import SpoolDirectory
    return SpoolDirectory(observation_root())
