"""Shared S2R scenario steps (`delivery.maintenance`, `delivery.maintenance.pg`): the restart phase of the active-generation
maintenance (INV-HOST-DELIVERY-MAINTENANCE-001) driven through the use case `HostDelivery.maintain` on the LABELLED S2R
fixtures (`host_delivery_maintenance_fixtures`: a real HostDelivery driven to ACTIVE over a simulated managed host, a real
Fleet and ReleaseQueue, a labelled authority store and artifact store; no systemd, provider, model or network).

Layer: harness (never shipped). Never imports `codex_harness`.

M7 has no maintenance (G1-13C-COMPARE-DECISION rule 5): the reference is the approved rebaseline wheel (main-s2r-b9d8f15)
and the golden lives under `goldens/rebaseline/main-s2r-b9d8f15/`. `api.F` is the fixtures module of the side (the
rebaseline's `tests/` for the reference, the ported `tests/ported/` for the target), `api.backend(root)` builds the pair of
stores (memory, or a fresh schema each on the disposable PostgreSQL) the fixtures use. Cases:
- `check_restart_replay`: `restart --check` writes nothing, `restart` replaces the incumbent (`started`), a replay is cached;
- `refusals`: an unsupported phase, a wrong evidence reference and a tampered document are refused by name;
- `held_target`: after `started` the open generation holds its target: a controller tick acts on nothing (`idle`), and the
  release, pointer and queue rows stay as they were."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

A = None  # the api of this run
HEX64 = re.compile(r"[0-9a-f]{64}|(?<=canary-)[0-9a-f]{24}")


def canonical(value, root: Path):
    """The result as plain JSON with the run's temporary root as `<tmp>` and every 64-hex digest (and the 24-hex job id prefix `canary-<hex>` derived from one) renamed `<d:n>` by first
    appearance in sorted-key order: a digest here covers the case's own temporary paths (a descriptor's `root`), so its
    VALUE is run-specific while equal digests stay equal and distinct ones distinct (documented normalization; no state,
    reason code or count is touched)."""
    text = json.dumps(value, default=str, sort_keys=True).replace(str(root), "<tmp>")
    names: dict[str, str] = {}
    return json.loads(HEX64.sub(lambda m: names.setdefault(m.group(0), f"<d:{len(names) + 1}>"), text))


def settle(call):
    """The result of a call, or the named refusal (type, reason code, field; never a message value)."""
    try:
        return {"returned": call()}
    except Exception as exc:
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None),
                "field": getattr(exc, "field", None)}


def maintain(system, document, evidence, phase="restart", **kwargs):
    return system["delivery"].maintain(document, evidence, phase, startup_seconds=0, poll_seconds=0, **kwargs)


def wall(row: dict, field: str) -> dict:
    """The row with one UNINJECTED wall-clock reading replaced by a label (documented normalization): `Releases` stamps
    `created_at`, `ReleaseQueue` and the active pointer stamp `at` from the module's own `utcnow()`, which no fixture
    injects, so the value is the run's real time on both sides. Every other field, including the injected clock's
    `at` values inside the attempts, is kept."""
    return None if row is None else {**row, field: "<wall-clock>"}


def rows(system) -> dict:
    F = A.F
    return {"intent": F.intent_of(system), "plan_row": F.plan_row_of(system), "descriptor_row": F.row_of(system),
            "queue": wall(F.read(system["store"], "release_queue", system["release"]["id"]), "at"),
            "release": wall(F.read(system["store"], "releases", system["release"]["id"]), "created_at"),
            "pointer": wall(F.read(system["store"], "deployment", "active"), "at")}


def check_restart_replay(root: Path) -> dict:
    F = A.F
    system = F.active_system(root)
    document, evidence = F.document_for(system)
    before = rows(system)
    checked = maintain(system, document, evidence, check=True)
    unchanged = rows(system) == before
    started = maintain(system, document, evidence)
    after = rows(system)
    replay = maintain(system, document, evidence)
    return {"check": checked, "check_wrote_nothing": unchanged, "started": started, "replay": replay,
            "generation": F.generation_of(system), "intent_after": after["intent"],
            "descriptor_row_after": after["descriptor_row"], "queue_after": after["queue"],
            "release_after": after["release"], "pointer_after": after["pointer"],
            "pointer_unchanged": after["pointer"] == before["pointer"],
            "rows_after_replay_equal": rows(system) == after}


def refusals(root: Path) -> dict:
    F = A.F
    system = F.active_system(root)
    document, evidence = F.document_for(system)
    before = rows(system)
    out = {"phase_arm": settle(lambda: maintain(system, document, evidence, phase="arm")),
           "phase_bind": settle(lambda: maintain(system, document, evidence, phase="bind")),
           "evidence_mismatch": settle(lambda: maintain(system, document, "sha256:" + "0" * 64)),
           "tampered_plan_sha256": settle(lambda: maintain(system, {**document, "plan_sha256": "f" * 64}, evidence)),
           "wrong_reason": settle(lambda: maintain(system, {**document, "reason": "other"}, evidence))}
    out["rows_unchanged"] = rows(system) == before
    return out


def held_target(root: Path) -> dict:
    F = A.F
    system = F.active_system(root)
    document, evidence = F.document_for(system)
    started = maintain(system, document, evidence)
    tick = settle(system["delivery"].tick)
    after = rows(system)
    return {"state": started["state"], "tick": tick, "queue": after["queue"], "intent_stage": after["intent"]["stage"],
            "pointer_unchanged": after["pointer"] == rows(system)["pointer"]}


CASES = [("check_restart_replay", check_restart_replay), ("refusals", refusals), ("held_target", held_target)]


def run(api) -> dict:
    global A
    A = api
    out = {}
    for name, fn in CASES:
        with tempfile.TemporaryDirectory(prefix="zeus-s2r-maintenance-") as raw:
            root = Path(raw)
            api.backend(root)
            try:
                result = fn(root)
            except Exception as exc:  # an unexpected failure of the characterized operation is itself compared
                result = {"case_error": type(exc).__name__, "message": str(exc)[:300]}
            out[name] = canonical(result, root)
    return out
