"""Validate actual lead -> conductor processing in running Compose consumers."""
import json
import time
from uuid import uuid4

from codex_harness.composition import build
from codex_harness.composition.cli_bus import bus as namespaced_bus
from codex_harness.kernel.message import envelope

service = build()
# S11 R-S3: RedisBus requires its namespace (S1); composition.cli_bus.bus() is RedisBus(redis_url(), HARNESS_REDIS_NAMESPACE or
# "codex-harness"), the namespace M7's RedisBus read itself (DESIGN-s11 §7 R-S3).
bus = namespaced_bus()
scope = "compose-smoke-" + uuid4().hex
for _ in range(2):
    bus.publish(envelope("incident.report", "worker:implementation", "lead:improvement", "record_incident",
                         {"occurrence_id": str(uuid4()), "root_cause": "fixture-cause", "scope": scope,
                          "evidence_refs": ["fixture:compose-smoke"]}, scope))
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    with service.store.transaction() as tx:
        hooks = [h for h in tx.scan("hooks") if h["scope"] == scope]
        delivered = [d for d in tx.scan("deliveries") if d["message"]["correlation_id"] == scope]
    if len(hooks) == 1 and delivered:
        assert delivered[0]["agent"] == "conductor"
        print(json.dumps({"compose_bus_passed": True, "hook_id": hooks[0]["id"],
                          "conductor_status": delivered[0]["status"]}))
        break
    time.sleep(0.5)
else:
    raise SystemExit("Timed out waiting for the lead -> conductor message path")
