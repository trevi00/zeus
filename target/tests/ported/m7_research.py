"""M7 research-subject names over the S8 target, for the ported M7 research suites (DESIGN-s8 §29).

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_research_*.py` run, with their assertions unchanged,
against the S8 research target. Ids and clocks are NOT scripted here: as in M7 the real clock and uuid4 are used.

Named adaptations (each is a construction/import adaptation, never a behaviour change):
- `packaged_policy` is `routing.adapters.provider_policy.packaged_policy` (M7 `adapters.providers.packaged_policy`).
- `OwnerActions(store, **ports)` is `m7_coordination.OwnerActions` (the facade over the split objects of
  `coordination.application.owner_actions`, built as the S6 composition builds it, with the SYSTEM clock and ids) with
  four more routes, for the private methods of M7's one class that the scoped-research suite calls, to the split
  homes: `_research_decide`, `_observe_dispatch` and `_discover_research` (the target's `discover`) to the
  scheduler's `research_dispatch` family, `_research_binding` (the target's `research_binding`) to its
  `research_acceptance` family. An unrouted name still raises AttributeError (never a fallback).
- `unavailable(slice_, name)` is `m7_coordination`'s.
- The research domain modules (`research_attempt_scope`, `research_program`, `research_investigations`,
  `audit_progress`, `autonomous`, `council`, `discovery_pressure`) are imported by the ported suites from
  `codex_harness.research.domain`; `continuation` and `owner_actions` from `codex_harness.coordination.domain`;
  `family_id` and the portfolio bucket names from `intake.domain.portfolio`; the owner-action, continuation and research
  bucket names from the `state` modules of their application packages; `digest`/`canonical` from `kernel.ids`;
  `MemoryStore` from `storage.adapters.memory_store`. No M7 name of this batch is without an S8-or-earlier home.
"""

from __future__ import annotations

from m7_coordination import OwnerActions as _OwnerActions
from m7_coordination import packaged_policy, unavailable

__all__ = ["OwnerActions", "packaged_policy", "unavailable"]

RESEARCH_PRIVATE = {"_research_decide": ("research_dispatch", "_research_decide"),
                    "_observe_dispatch": ("research_dispatch", "_observe_dispatch"),
                    "_discover_research": ("research_dispatch", "discover"),
                    "_research_binding": ("research_acceptance", "research_binding")}


class OwnerActions(_OwnerActions):
    def __getattr__(self, name):
        route = RESEARCH_PRIVATE.get(name)
        if route is None:
            return super().__getattr__(name)
        return getattr(getattr(self.objects["scheduler"], route[0]), route[1])
