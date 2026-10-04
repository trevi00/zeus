"""Reading approved backlog plans and their pinned manifests from Git (INV-FLEET-BACKLOG-001).

Layer: composition
Owns: load_plan, check_lanes, check_goals, load_manifest, manifest_loader, register_plan, coordinator, tick_plan, backlog_ticker, configured_plan, _parse and the plan, manifest and setting constants
Does not own: the pinned-bytes read (intake.adapters.backlog_blobs.read_blob), the coordinator (coordination.application.fleet_backlog) and the command bodies (entry.cli.fleet, composition.cli_fleet)
Entry points: load_plan, check_lanes, check_goals, load_manifest, manifest_loader, register_plan, coordinator, tick_plan, backlog_ticker, configured_plan, MAX_PLAN_BYTES, MAX_MANIFEST_BYTES, PLAN_SETTING
Contracts: INV-FLEET-001, INV-FLEET-BACKLOG-001

Moved from M7 `adapters/fleet_backlog.py` (SOURCE e38aa722) by named rule R-c28 (S10 unit C8b-2, DESIGN-s8 V33): what S7 left after `read_blob` and `REGULAR_BLOB` moved to `intake.adapters.backlog_blobs`.
Every body is M7's verbatim except the import homes and the one `Fleet` use: `coordinator` hands `FleetBacklog` the registry owner of the S5 split (`FleetRegistry`; `FleetBacklog` uses only `enqueue`, as the shim's `Fleet`
routes it), `bind_goal` is `composition.cli_operation`'s (R-c28) and `GitSource` is `host_os.adapters.git_source`'s. `_parse` (:38-50) is the one copy, used by `composition.continuation` too. M7 docstring follows.

The plan and every manifest it names are owner-authored configuration, so they are read through
the existing `GitSource` at an explicit 40-hex commit and never from the mutable working tree:
editing a checked-out file changes nothing until the change is committed and the new commit is
named in the plan. The bytes are bounded, parsed as strict JSON with duplicate keys refused,
digest-checked against the pin, validated by the existing operation manifest validator and bound
to their goal by the existing `bind_goal`. No code, command or text from a plan is ever executed.

Every I/O in this module happens OUTSIDE a store transaction. The loader it builds is handed to
`FleetBacklog.tick`, which calls it between its short transactions, so
no git or file read is ever holding the PostgreSQL control-plane advisory lock.
"""
from __future__ import annotations

import hashlib
import json

from codex_harness.composition.cli_operation import bind_goal
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.fleet_backlog import FleetBacklog
from codex_harness.coordination.domain.fleet import FleetRefused, lane_of, repository_identity
from codex_harness.coordination.domain.operation import validate_manifest
from codex_harness.host_os.adapters.git_source import GitSource
from codex_harness.intake.adapters.backlog_blobs import read_blob
from codex_harness.intake.adapters.portfolio import packaged_definitions
from codex_harness.intake.application.portfolio import Portfolio, validate_definitions
from codex_harness.intake.domain.backlog import BacklogRefused, validate_plan
from codex_harness.kernel.errors import ContractError, require
from codex_harness.routing.adapters.provider_policy import packaged_policy

MAX_PLAN_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
# The host setting that opts a running `zeus fleet run` into backlog ticks. Absent means disabled:
# the runtime default is unchanged and no configuration change enables it implicitly.
PLAN_SETTING = "ZEUS_FLEET_BACKLOG_PLAN"


def _parse(data: bytes, reason_code: str) -> dict:
    """Bounded UTF-8 JSON with duplicate keys refused; the code names the role, never the bytes."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Fleet backlog document has a duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeDecodeError, ContractError) as exc:
        raise BacklogRefused(reason_code) from exc


def load_plan(source, revision: str, path: str) -> dict:
    """The pinned plan with the identity of the exact bytes it was read from."""
    data = read_blob(source, revision, path, MAX_PLAN_BYTES, "plan")
    plan = validate_plan(_parse(data, "plan_not_json"))
    return {"plan": plan, "pin": {"revision": revision, "path": path,
                                  "sha256": hashlib.sha256(data).hexdigest()}, "bytes": len(data)}


def check_lanes(plan: dict, config: dict) -> dict:
    """Every item's lane exists in THIS fleet and resolves to the plan's repository identity.

    A plan that names an unknown lane, or a lane whose repository is not the repository the plan
    was approved for, is refused: a foreign repository can never be admitted because a document
    claims it.
    """
    for item in plan["items"]:
        try:
            lane = lane_of(config, item["lane"])
        except FleetRefused as exc:
            raise BacklogRefused("lane_unknown", "items[].lane") from exc
        if repository_identity(lane["repository"]) != plan["repository"]:
            raise BacklogRefused("repository_foreign", "items[].lane")
    return plan


def check_goals(plan: dict, definitions=None) -> dict:
    """Every item names a project and criterion the owner's portfolio actually defines.

    The portfolio stays the authority over goals: this is a read-only check, it records no binding
    and no acceptance, and a definition that no longer exists refuses the item's plan instead of
    admitting work under an unknown goal.
    """
    validated = validate_definitions(packaged_definitions() if definitions is None else definitions)
    defined = {(project["id"], criterion["id"]) for project in validated["projects"]
               for criterion in project["criteria"]}
    for item in plan["items"]:
        if (item["project_id"], item["criterion_id"]) not in defined:
            raise BacklogRefused("goal_unknown", "items[].criterion_id")
    return plan


def load_manifest(source, item: dict) -> dict:
    """One item's pinned operation manifest, validated and bound to its goal at base.

    The digest of the committed bytes must equal the item's pin, so a manifest that moved under an
    approved item is refused rather than admitted. Validation is the existing operation validator
    and the binding is the existing `bind_goal`; no second manifest schema exists here.
    """
    data = read_blob(source, item["manifest_revision"], item["manifest_path"], MAX_MANIFEST_BYTES, "manifest")
    if hashlib.sha256(data).hexdigest() != item["manifest_sha256"]:
        raise BacklogRefused("manifest_pin_mismatch", "items[].manifest_sha256")
    document = _parse(data, "manifest_not_json")
    try:
        manifest = validate_manifest(document, packaged_policy())
    except ContractError as exc:
        raise BacklogRefused("manifest_refused") from exc
    try:
        goal = bind_goal(manifest, source)
    except ContractError as exc:
        raise BacklogRefused("goal_mismatch") from exc
    return {"manifest": manifest, "goal": goal, "bytes": len(data)}


def manifest_loader(config: dict, plan: dict, source_factory=GitSource, definitions=None):
    """The per-item callable `FleetBacklog.tick` calls outside every store transaction.

    It re-checks the lane, the repository identity and the portfolio goal on every tick, so a
    definition or configuration that changed after registration refuses the item with a reason
    instead of admitting stale work. It also names the lane repository IDENTITY (the digest, never
    the path) the job will carry, so the coordinator can record the complete Fleet binding before
    the enqueue instead of comparing a partial one afterwards.
    """
    def load(item: dict) -> dict:
        check_lanes({**plan, "items": [item]}, config)
        check_goals({**plan, "items": [item]}, definitions)
        lane = lane_of(config, item["lane"])
        return {**load_manifest(source_factory(lane["repository"]), item),
                "repository": repository_identity(lane["repository"])}

    return load


def register_plan(store, config: dict, lane_id: str, revision: str, path: str,
                  source_factory=GitSource, definitions=None) -> dict:
    """Read one plan at its pin from the named lane's repository and register it."""
    lane = lane_of(config, lane_id)
    loaded = load_plan(source_factory(lane["repository"]), revision, path)
    plan = check_goals(check_lanes(loaded["plan"], config), definitions)
    if plan["repository"] != repository_identity(lane["repository"]):
        raise BacklogRefused("repository_foreign", "repository")
    receipt = FleetBacklog(store).register(plan, loaded["pin"])
    return {**receipt, "bytes": loaded["bytes"]}


def coordinator(store, definitions=None, observer=None) -> FleetBacklog:
    """The coordinator with its existing owners wired: the unchanged `Fleet` for admission, the
    unchanged `Portfolio` for the job-to-criterion binding of an admitted job, and the existing
    observation port for the fixed structured transitions. Both owners open their own
    transactions, so nothing here is ever called under a held one."""
    validated = packaged_definitions() if definitions is None else definitions
    return FleetBacklog(store, FleetRegistry(store), portfolio=Portfolio(store, validated), observer=observer)


def tick_plan(store, config: dict, plan_id: str, source_factory=GitSource, definitions=None,
              observer=None) -> dict:
    """One bounded tick over an already registered plan."""
    backlog = coordinator(store, definitions, observer)
    row = backlog.plan(plan_id)
    if row is None:
        return backlog.tick(plan_id, lambda item: None)  # records `plan_unregistered`, writes nothing
    loader = manifest_loader(config, row["plan"], source_factory, definitions)
    return backlog.tick(plan_id, loader)


def backlog_ticker(store, config: dict, plan_id: str, source_factory=GitSource, definitions=None,
                   observer=None):
    """The optional per-tick callable for `FleetRunner(..., backlog=...)`; disabled by default.

    It opens its own transactions, exactly like the portfolio reconciler beside it, so a backlog
    outage never blocks admission and admission never holds a lock across this work.
    """
    return lambda: tick_plan(store, config, plan_id, source_factory, definitions, observer)


def configured_plan(settings: dict) -> str | None:
    """The opt-in plan id from host settings, or None. Absent means the runner never ticks."""
    value = (settings or {}).get(PLAN_SETTING)
    return value.strip() if type(value) is str and value.strip() else None


__all__ = ["MAX_MANIFEST_BYTES", "MAX_PLAN_BYTES", "PLAN_SETTING", "backlog_ticker", "check_goals",
           "check_lanes", "configured_plan", "coordinator", "load_manifest", "load_plan",
           "manifest_loader", "register_plan", "tick_plan"]
