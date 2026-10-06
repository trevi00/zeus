"""The coordination read behind the proactive discovery pressure census (INV-DISCOVERY-PRESSURE-001).

Layer: application
Context: coordination
Owns: `DiscoveryCensusReader.observe`: the read-only census block of M7 `DiscoveryPressure._evaluate`, in M7's order
Does not own: the pressure policy, the decision or the row write (research.application.discovery_pressure)
Entry points: DiscoveryCensusReader
Contracts: INV-DISCOVERY-PRESSURE-001

New in S8 pilot 76 (DESIGN-s8 V2e/V15): research -> coordination is not an edge, so research's evaluator calls this through its
`DiscoveryCensus` port and the composition wires it. The reads are exactly M7's, inside the caller's transaction: the Fleet registry
and control, the effective config when a fleet is registered, the scans of the Fleet jobs (by id), the Fleet units, the backlog plans
and intents and the continuation intents, the repository aliases when registered, then `census`. Nothing is written.
"""
from __future__ import annotations

from codex_harness.coordination.application.continuation.state import BUCKET_INTENTS as CONTINUATION_INTENTS
from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS, BUCKET_UNITS
from codex_harness.coordination.domain.discovery_census import census
from codex_harness.coordination.domain.fleet import effective_config
from codex_harness.intake.domain.backlog import BUCKET_INTENTS as BACKLOG_INTENTS
from codex_harness.intake.domain.backlog import BUCKET_PLANS
from codex_harness.kernel.ids import digest


class DiscoveryCensusReader:
    def observe(self, tx, ledger) -> dict:
        """`{"observed": <census>, "fleet_config_sha256": <digest of the registered config, or None>}` from ONE read of the rows."""
        registry = state.registry(tx)
        control = state.control(tx)
        config = effective_config(registry["config"], control) if registry is not None else None
        jobs = {job["id"]: job for job in tx.scan(BUCKET_JOBS)}
        observed = census(config=config, control=control, jobs=jobs, units=tx.scan(BUCKET_UNITS),
                          plans=tx.scan(BUCKET_PLANS), intents=tx.scan(BACKLOG_INTENTS),
                          continuation_intents=tx.scan(CONTINUATION_INTENTS),
                          aliases=state.repository_aliases(tx) if registry is not None else None, ledger=ledger)
        return {"observed": observed,
                "fleet_config_sha256": digest(registry["config"]) if registry is not None else None}


__all__ = ["DiscoveryCensusReader"]
