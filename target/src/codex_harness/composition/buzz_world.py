"""The real Zeus world of the Buzz bridge: ports and read models over the store (Buzz DESIGN-D §2b).

Layer: composition
Owns: `ZeusReads` (the `ZeusReadModels` implementation: org and task views from the `tasks` rows and the
    Organization, fleet and transitions from coordination), `zeus_world` (ports, read models, channel map, role ids),
    `TERMINAL_STATUSES` and `UNSOURCED`
Does not own: the workflow, the fleet pause, remote control or the projection (their use cases), the config
    (`composition.buzz_bridge`)
Entry points: ZeusReads, zeus_world, TERMINAL_STATUSES, UNSOURCED
Contracts: INV-OBSERVATION-001, INV-EXECUTION-IDENTITY-001 (Buzz DESIGN v3 §4.2, §4.4, §4.5; DESIGN-D §2b)

It reads only Zeus rows, inside the caller's transaction, and invents nothing: a field with no target source is null
(or empty where the contract needs a value) and named in `UNSOURCED`. A read error propagates (the projection already
handles an unreadable org); `unknown` is never fabricated from one.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone

from codex_harness.composition.buzz_bridge import BridgeConfig, ZeusWorld, custody_name
from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.operation_finalization import park
from codex_harness.coordination.application.remote_control import transitions_after
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.observation.domain import buzz_projection as bp
from codex_harness.research.application.audit_gate import require_adoption

# Statuses after which the workflow writes no further execution of the task (derived from the writers: `claim` ->
# running/expired/cancelled/failed/blocked, `complete` -> succeeded/superseded, `fail_execution` -> retry/failed,
# `block_execution` -> blocked, `cancel_in` -> cancelled). `queued`, `retry` and `running` are the open statuses
# (local_cycle OPEN_TASK); `blocked` is held for an owner reconciliation and is never claimed again.
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "expired", "superseded", "blocked"})
# View fields with no target source (DESIGN-D §2b): no `tasks` row writer sets `updated_at` (it falls back to
# `created_at`) or a stage; the target `Agent` carries no display name (the id is the display).
UNSOURCED = ("task.stage", "task.updated_at", "org.display")
_ARTIFACT_REF = re.compile(r"sha256:[0-9a-f]{64}")


def _epoch(value, name: str) -> int:
    """An ISO-8601 timestamp (a naive one is UTC, as the workflow writes) as whole epoch seconds."""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ContractError(f"buzz world: {name} is not an ISO timestamp") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _live(row: dict, now: int) -> bool:
    """True iff the row holds a lease that has not expired (an absent or unreadable one is not evidence)."""
    until = row.get("lease_until")
    if until is None:
        return False
    try:
        return _epoch(until, "lease_until") > now
    except ContractError:
        return False


def _refs(*sources) -> list:
    """Opaque artifact references only (`sha256:<hex>`), in order, without duplicates; never a path or URL."""
    out: list = []
    for source in sources:
        for ref in source if isinstance(source, list) else ():
            if (isinstance(ref, str) and _ARTIFACT_REF.fullmatch(ref) and bp.evidence_ref_ok(ref) and ref not in out):
                out.append(ref)
    return out[:bp.MAX_EVIDENCE_REFS]


class ZeusReads:
    """`ZeusReadModels` over the Zeus store: the org and task views are read from rows, never from a double."""

    def __init__(self, organization, clock: Callable[[], float]):
        self.organization, self.clock = organization, clock

    def fleet(self, tx) -> dict:
        return state.fleet_view(tx)

    def transitions_after(self, tx, after: int | None, limit: int) -> list[dict]:
        return transitions_after(tx, after, limit)

    def tasks(self, tx) -> list[dict]:
        now = int(self.clock())
        views = [self._view(row, now) for row in tx.scan("tasks")]
        return sorted(views, key=lambda view: (view["created_at"], view["task_id"]))

    def task(self, tx, task_id: str) -> dict | None:
        row = tx.get("tasks", task_id)
        return None if row is None else self._view(row, int(self.clock()))

    def org(self, tx) -> dict:
        now = int(self.clock())
        paused = bool(self.fleet(tx)["paused"])
        rows = tx.scan("tasks")
        roles = []
        for agent in self.organization.agents.values():
            mine = [row for row in rows if row.get("agent") == agent.id]
            live = sorted((row for row in mine if row.get("status") not in TERMINAL_STATUSES and _live(row, now)),
                          key=lambda row: (_epoch(row["lease_until"], "lease_until"), row["id"]))
            seen = [_epoch(row.get("updated_at") or row["created_at"], "updated_at") for row in mine]
            if live:  # §4.4 "running ONLY with execution evidence": a live lease of a non-terminal task
                state_, task_id = "busy", live[-1]["id"]
            else:
                state_, task_id = ("paused" if paused else "idle"), None
            roles.append({"id": agent.id, "role": agent.role, "parent": agent.parent, "team": agent.team,
                          "display": agent.id,
                          "status": {"state": state_, "task_id": task_id,
                                     "last_activity_at": max(seen) if seen else None, "observed_at": now}})
        return {"roles": roles}

    def _view(self, row: dict, now: int) -> dict:
        message, result = row["message"], row.get("result")
        agent = self.organization.agents.get(row["agent"])
        require(agent is not None, "buzz world: a task is assigned to an agent the organization does not list")
        details = message["what"].get("details")
        title = details.get("title") if isinstance(details, dict) else None
        summary = result.get("summary") if isinstance(result, dict) else None
        created = _epoch(row["created_at"], "created_at")
        stage = row.get("stage")
        return {
            "task_id": row["id"], "title": (title if isinstance(title, str) and title else row["id"])[:bp.MAX_TITLE_CHARS],
            "team": agent.team, "assignee": row["agent"], "sender": message["who"]["sender"],
            "generation": row["generation"], "status": row["status"],
            "stage": stage if isinstance(stage, str) and stage else None,
            "terminal": row["status"] in TERMINAL_STATUSES, "created_at": created,
            "updated_at": _epoch(row["updated_at"], "updated_at") if row.get("updated_at") else created,
            "observed_at": now, "summary": summary[:bp.MAX_SUMMARY_CHARS] if isinstance(summary, str) else "",
            "evidence_refs": _refs(result.get("evidence_refs") if isinstance(result, dict) else None,
                                   (message.get("why") or {}).get("evidence_refs"))}


def zeus_world(store, config: BridgeConfig, *, clock: Callable[[], float]) -> ZeusWorld:
    """The bridge's ports, read models and channel map over `store`, from the config's organization and channels."""
    organization = config.load_organization()
    for role_id in organization.agents:
        custody_name(role_id)  # a role id that cannot map injectively is refused when the world is built
    workflow = Workflow(store, organization, ticket_binding=tickets.ticket_binding,
                        TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption, park_terminal=park,
                        clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    return ZeusWorld(messages=MessageHandler(workflow), fleet_pause=FleetPause(store),
                     read_models=ZeusReads(organization, clock),
                     channels={"commander": config.commander_channel, "org_d": config.org_d,
                               "teams": dict(config.team_channels)},
                     roles=tuple(organization.agents))
