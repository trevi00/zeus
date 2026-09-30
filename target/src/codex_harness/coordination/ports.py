"""Coordination ports: the buckets coordination owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: coordination
Owns: OWNED_BUCKETS of the coordination context
Does not own: the Protocols coordination declares for other contexts (TaskRunner, LaneLauncher, ...: S5/S6)
Entry points: OWNED_BUCKETS
Contracts: INV-EXECUTION-IDENTITY-001

S4 (lead decision Option A) declares the buckets its moved-ahead owner operations write; S5 adds the rest.
"""

from __future__ import annotations

OWNED_BUCKETS = ("tasks", "decisions_pending", "outbox", "events", "execution_fences", "execution_notices",
                 "execution_notice_errors", "execution_time_events", "workflow_inbox", "execution_rejections",
                 "execution_failures",
                 "breakers", "breaker_events", "breaker_notices", "breaker_policies", "sessions",
                 # S5 Fleet split (DESIGN-s5 §F): the four Fleet objects are this context's writers.
                 "fleet_registry", "fleet_control", "fleet_jobs", "fleet_budget_grants", "fleet_delivery",
                 "fleet_units", "fleet_recovery_receipts", "fleet_relocations", "fleet_host_migrations")
