"""Canonical append-only addition declarations (CUT-INT rule 7; harness only, never shipped).

No per-function public_api or atomic_unit additions: generate emits only cross-context M7 atomic units.
Research: RULE7-WRITER-FACTS.wf_69f12cd3.txt, generate.skeleton/dump, Relabel.item/evaluate,
and test_coverage_table's digest contract (2026-10-06, cb8090aa). Unknown evidence refuses relabel;
reuse its classifier before writing. Preserve the SOURCE skeleton and existing maintained values.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import generate
import layout
import relabel

# Backfilled verbatim seed/owned values; status and verification belong to relabel.
ADDITIONS = [{'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/operations.queue_item_waited',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `operations.queue_item_waited` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/development.role_dispatch_decided',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry added; X1b-2: produced by RunTask at the admission and '
                    'reservation boundary (owner decision R1, catalog v3 owner execution); X2 counter '
                    'zeus_role_dispatch_decisions_total',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py',
               'compare:observation.schema',
               'target:tests/test_s10_capacity_observer.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/operations.capacity_refused',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `operations.capacity_refused` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b; S10 #18b: CapacityObservingLedger produces it '
                    'on the invocation-capacity refusal (wiring C5/C6)',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/development.tool_call_completed',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `development.tool_call_completed` added with its typed '
                    'attributes; catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/development.skill_selected',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `development.skill_selected` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/operations.ci_observed',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `operations.ci_observed` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/operations.cleanup_recorded',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `operations.cleanup_recorded` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/operations.collector_started',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `operations.collector_started` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/operations.path_declined',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `operations.path_declined` added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/event/development.usage_split_recorded',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: REGISTRY entry `development.usage_split_recorded` (renamed from '
                    '`development.provider_usage_split`, catalog v2, X1b-1) added with its typed attributes; '
                    'catalog v1 enums closed; producers X1b',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.observation:REGISTRY'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py',
               'compare:observation.schema',
               'target:tests/test_s9_d6_research_log.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/resource/observability-catalog.json',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: the event catalog SSOT (catalog v1); moved into the observation package by the '
                    'owner CI fix 571877b4 (DESIGN-s9-X §1.2); catalog v4 registers the research EventLog as '
                    'a separate log (OWNER-DECISIONS-S9 D6)',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['src/codex_harness/observation/observability-catalog.json'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1a_catalog.py', 'compare:observation.schema'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/module/event_catalog',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X1a: load_catalog and check_catalog_attributes (the producer helper X1b uses)',
  'symbol_basis': 'DESIGN-s9-X §1.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.event_catalog'],
  'trace': 'addition (no SOURCE counterpart): producers are X1b, measured per site',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x1b1_execution.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §1)',
  'key': 'addition:observation/module/catalog_observer',
  'kind': 'addition',
  'layer': 'application',
  'slice': 'S9',
  'slice_progress': "S9 X1b-1 D3': the catalog-checking Observer decorator (S10 composition wires it, "
                    'OWNER-DECISIONS-S10 #18a)',
  'symbol_basis': 'DESIGN-s9-X §1.3',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.application.catalog_observer:CatalogCheckingObserver'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x2a_metrics.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §2, §2.2)',
  'key': 'addition:observation/bucket/observation_metrics',
  'kind': 'addition',
  'layer': 'ports',
  'slice': 'S9',
  'slice_progress': "S9 X2a: the metrics projection's own bucket (single writer metrics_projector; P0 before "
                    'its writer)',
  'symbol_basis': 'DESIGN-s9-X §2.2',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.ports:OWNED_BUCKETS'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x2a_metrics.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §2, §2.2)',
  'key': 'addition:observation/module/metric_families',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X2a: six metric families, closed label enums and the total samples() mapping; S9 '
                    'X2b: six more event-derived families (DESIGN-s9-X §2.3)',
  'symbol_basis': 'DESIGN-s9-X §2.2',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.metric_families:FAMILIES'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x2a_metrics.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §2, §2.2)',
  'key': 'addition:observation/module/metrics_projector',
  'kind': 'addition',
  'layer': 'application',
  'slice': 'S9',
  'slice_progress': "S9 X2a: MetricsProjector and the ProjectingStore decorator (inline in the Collector's "
                    'sink transaction)',
  'symbol_basis': 'DESIGN-s9-X §2.2',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.application.metrics_projector:ProjectingStore'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x2a_metrics.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §2, §2.2)',
  'key': 'addition:observation/module/metrics_exposition',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X2a: the Prometheus text format 0.0.4 renderer (golden-tested)',
  'symbol_basis': 'DESIGN-s9-X §2',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.adapters.metrics_exposition:render'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x3a_resource_facts.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §3)',
  'key': 'addition:observation/module/resource_facts',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X3a: cgroup v2, PSI, filesystem and interface facts through injectable roots; '
                    'unavailable is never zero',
  'symbol_basis': 'DESIGN-s9-X §3',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.adapters.resource_facts:ResourceFacts'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x4a_rules.py',
               'owner-run:promtool (A/evidence/rebuild/s9/integration/x4a-promtool.txt)'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §4)',
  'key': 'addition:observation/resource/zeus-s9-rules',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X4a: 5 recording rules and 9 alerts (owner, severity, for, keep_firing_for, runbook, '
                    'provisional thresholds); promtool firing/resolution tests in zeus-s9.test.yml, '
                    'owner-run outside pytest (the provider guard is kept)',
  'symbol_basis': 'DESIGN-s9-X §4',
  'target_owner': 'observation',
  'target_symbol': ['deploy/observability/prometheus/rules/zeus-s9.yml'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x4a_rules.py',
               'owner-run:promtool (A/evidence/rebuild/s9/integration/x4a-promtool.txt)'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §4)',
  'key': 'addition:observation/resource/zeus-s9-runbook',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X4a: one runbook section per alert (what fired, three read-only checks, what not to '
                    'conclude, owner)',
  'symbol_basis': 'DESIGN-s9-X §4',
  'target_owner': 'observation',
  'target_symbol': ['docs/runbooks/zeus-s9.md'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x2c_queue_facts.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §2.4)',
  'key': 'addition:observation/module/queue_facts',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X2c: queue depth and oldest-age facts as bounded state reads; truncated or '
                    'unreadable is unavailable, never zero',
  'symbol_basis': 'DESIGN-s9-X §2.4',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.adapters.queue_facts:QueueFacts'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x5a_features.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §5, §5.1)',
  'key': 'addition:observation/module/feature_registry',
  'kind': 'addition',
  'layer': 'domain',
  'slice': 'S9',
  'slice_progress': 'S9 X5a: 25 features over the 76 event types, the instrumented flag pinned to the '
                    'DESIGN-s9-X §5.1 measurement, zeus_feature_uses_total and the usage-state precedence '
                    '(zero use is never a removal authority)',
  'symbol_basis': 'DESIGN-s9-X §5.1',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.domain.feature_registry:FEATURES'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_redis_stream_facts.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §4) and '
            'REDIS-STREAMS-RELIABILITY-20261003',
  'key': 'addition:observation/module/redis_stream_facts',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'REDIS-STREAMS G3: Redis stream pending/lag/oldest pending idle/dead letters/memory '
                    'facts; unavailable is never zero',
  'symbol_basis': 'REDIS-STREAMS-MAP G3',
  'target_owner': 'observation',
  'target_symbol': ['codex_harness.observation.adapters.redis_stream_facts:RedisStreamFacts'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x4b_rules.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §4) and '
            'REDIS-STREAMS-RELIABILITY-20261003',
  'key': 'addition:observation/resource/zeus-s9b-rules',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X4b: rules over the queue (X2c), Redis stream (G3) and feature-use (X5a) facts; '
                    'promtool owner-run',
  'symbol_basis': 'DESIGN-s9-X §4',
  'target_owner': 'observation',
  'target_symbol': ['deploy/observability/prometheus/rules/zeus-s9b.yml'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False},
 {'evidence': ['target:tests/test_s9_x4b_rules.py'],
  'intent': 'addition:OBSERVABILITY-COVERAGE-20261002 (OWNER-DECISIONS-S9 D4; DESIGN-s9-X §4) and '
            'REDIS-STREAMS-RELIABILITY-20261003',
  'key': 'addition:observation/resource/zeus-s9b-runbook',
  'kind': 'addition',
  'layer': 'adapters',
  'slice': 'S9',
  'slice_progress': 'S9 X4b: one runbook section per alert',
  'symbol_basis': 'DESIGN-s9-X §4',
  'target_owner': 'observation',
  'target_symbol': ['docs/runbooks/zeus-s9b.md'],
  'trace': 'addition (no SOURCE counterpart)',
  'untraced': False}]

S2R = 'addition:REBASELINE-MAIN-S2R (A/evidence/rebuild/cutover/REBASELINE-MAIN-S2R.md)'
PR3 = 'addition:G1-06 PR-3 (A/evidence/rebuild/cutover/G1-06-ACCEPTANCE-RECORD.md)'
FA = 'addition:FA-SPEC + Amendment A (A/evidence/rebuild/cutover/FA-SPEC.md)'


def declaration(owner, name, layer, authority, symbols, tests, compares=()):
    return {'key': f'addition:{owner}/{name}', 'kind': generate.ADDITION, 'layer': layer,
            'intent': authority, 'trace': 'addition (no SOURCE counterpart)', 'untraced': False,
            'target_owner': owner, 'target_symbol': list(symbols),
            'evidence': ['target:tests/' + t + '.py' for t in tests] + ['compare:' + c for c in compares],
            'slice': relabel.OWNER_SLICE[owner], 'slice_progress': authority[len('addition:'):],
            'symbol_basis': authority[len('addition:'):]}


ADDITIONS += [
    declaration('delivery', 'contract/INV-HOST-DELIVERY-MAINTENANCE-001', 'domain', S2R,
                ['codex_harness.delivery.domain.maintenance'], ['test_s10_c8b4_host_delivery']),
    declaration('delivery', 'module/domain.maintenance', 'domain', S2R,
                ['codex_harness.delivery.domain.maintenance'], ['ported/test_host_delivery_maintenance_domain']),
    declaration('delivery', 'module/application.host_delivery.maintenance', 'application', S2R,
                ['codex_harness.delivery.application.host_delivery.maintenance:DeliveryMaintenance'],
                ['ported/test_host_delivery_maintenance', 'ported/test_host_delivery_maintenance_guards',
                 'ported/test_host_delivery_maintenance_e2e'], ['delivery.maintenance', 'delivery.maintenance.pg']),
    declaration('delivery', 'module/adapters.maintenance_evidence', 'adapters', S2R,
                ['codex_harness.delivery.adapters.maintenance_evidence'],
                ['ported/test_maintenance_evidence', 'ported/test_host_delivery_maintenance_adapter']),
    declaration('entry', 'cli/zeus host-delivery maintain', 'entry', S2R,
                ['codex_harness.entry.cli.host_delivery:add_parser'],
                ['ported/test_host_delivery_maintenance_cli'], ['cli.parser']),
    declaration('coordination', 'module/domain.fleet_maintenance', 'domain', PR3,
                ['codex_harness.coordination.domain.fleet_maintenance'], ['ported/test_fleet_maintenance']),
    declaration('coordination', 'module/application.fleet.maintenance', 'application', PR3,
                ['codex_harness.coordination.application.fleet.maintenance:FleetMaintenance',
                 'codex_harness.coordination.application.fleet.maintenance:claim_queued_job',
                 'codex_harness.coordination.application.fleet.maintenance:fail_unlaunched_job'],
                ['ported/test_fleet_maintenance', 'ported/test_fleet_forward_candidate',
                 'ported/test_fleet_maintenance_runner', 'ported/test_fleet_maintenance_postgres']),
    declaration('coordination', 'bucket/fleet_maintenance_admissions', 'application', PR3,
                ['codex_harness.coordination.ports:OWNED_BUCKETS'], ['ported/test_fleet_maintenance']),
    declaration('coordination', 'api/MaintenanceCanaryExecutor', 'application', PR3,
                ['codex_harness.coordination.application.fleet.runner:MaintenanceCanaryExecutor'],
                ['ported/test_fleet_maintenance_runner']),
    declaration('coordination', 'module/domain.fleet_admission_permit', 'domain', FA,
                ['codex_harness.coordination.domain.fleet_admission_permit'], ['test_fleet_admission_permit']),
    declaration('coordination', 'module/application.fleet.admission_permit', 'application', FA,
                ['codex_harness.coordination.application.fleet.admission_permit:FleetAdmissionPermits',
                 'codex_harness.coordination.application.fleet.admission_permit:store_consumption'],
                ['test_fleet_admission_permit', 'test_fleet_admission_permit_postgres']),
    declaration('coordination', 'bucket/fleet_admission_permits', 'application', FA,
                ['codex_harness.coordination.ports:OWNED_BUCKETS'],
                ['test_fleet_admission_permit', 'test_fleet_admission_permit_postgres']),
    declaration('coordination', 'api/AdmissionPermitExecutor', 'application', FA,
                ['codex_harness.coordination.application.fleet.runner:AdmissionPermitExecutor'],
                ['test_fleet_admission_permit']),
    declaration('entry', 'cli/zeus fleet grant-permit', 'entry', FA,
                ['codex_harness.entry.cli.fleet:add_parser'], ['test_fleet_admission_permit']),
    declaration('entry', 'cli/zeus fleet admit-permit', 'entry', FA,
                ['codex_harness.entry.cli.fleet:add_parser'], ['test_fleet_admission_permit']),
]

# CUT-INT rule 7 explicitly owns target owner/symbol despite the generator's maintained-field split.
OWNED_FIELDS = (set(ADDITIONS[0]) - generate.MAINTAINED_FIELDS) | {'target_owner', 'target_symbol'}


class Refused(Exception):
    pass


def digest(table):
    keys = sorted(r['key'] for r in table['rows'] if r['kind'] != 'atomic_unit')
    return hashlib.sha256('\n'.join(keys).encode()).hexdigest()


def inspect(table, root, declarations):
    declared = {r['key']: r for r in declarations}
    if len(declared) != len(declarations):
        raise Refused('duplicate_declaration')
    classifier = relabel.Relabel(root, {'nodes': [], 'not_passed': {}, 'owner_run': {}, 'compare': {}}, [])
    for r in declarations + [r for r in table['rows'] if r['kind'] == generate.ADDITION]:
        if not r.get('intent', '').startswith('addition:') or not r['intent'][len('addition:'):].strip():
            raise Refused('intent_without_authority: ' + r['key'])
        if not r.get('target_symbol'):
            raise Refused('empty_target_symbol: ' + r['key'])
        for e in r['evidence']:
            try:
                classifier.item(e)
            except relabel.Refused as exc:
                raise Refused('evidence_form: ' + str(exc)) from exc
    seen = set()
    for r in table['rows']:
        key = r['key']
        if key in seen:
            raise Refused('duplicate_key: ' + key)
        seen.add(key)
        if r['kind'] == generate.ADDITION and key not in declared:
            raise Refused('undeclared_addition: ' + key)
        if key in declared:
            for field in sorted(OWNED_FIELDS):
                if r.get(field) != declared[key].get(field):
                    raise Refused(f'owned_field_drift: {key}: {field}')
    return [r for r in declarations if r['key'] not in seen]


def run(root, write=False, declarations=None):
    declarations = ADDITIONS if declarations is None else declarations
    path = root / layout.TARGET_DIR / 'coverage/ledger-coverage.json'
    table = json.loads(path.read_text(encoding='utf-8'))
    missing = inspect(table, root, declarations)
    if not write:
        errors = []
        if missing:
            errors.append({'missing_keys': [r['key'] for r in missing]})
        count = sum(r['kind'] == generate.ADDITION for r in table['rows'])
        if table['counts'].get(generate.ADDITION) != count:
            errors.append('count_mismatch')
        if table['ledger_key_digest'] != digest(table):
            errors.append('digest_mismatch')
        return {'ok': not errors, 'addition_rows': count, 'errors': errors}, int(bool(errors))
    new = copy.deepcopy(table)
    index = max((i + 1 for i, r in enumerate(new['rows']) if r['kind'] == generate.ADDITION),
                default=len(new['rows']))
    new['rows'][index:index] = [dict(copy.deepcopy(r), status='designed') for r in missing]
    new['counts'][generate.ADDITION] = sum(r['kind'] == generate.ADDITION for r in new['rows'])
    new['ledger_key_digest'] = digest(new)
    if new != table:
        path.write_text(generate.dump(new), encoding='utf-8')
    return {'added': [r['key'] for r in missing], 'counts': new['counts'],
            'ledger_key_digest': new['ledger_key_digest']}, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--write', action='store_true')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result, code = run(args.root, args.write)
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        result, code = {'ok': False, 'error': str(exc)}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
