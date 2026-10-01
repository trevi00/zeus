"""Remote control (Buzz): admit one owner `zeus:command` event, bind it once and move it forward.

Layer: application
Context: coordination
Owns: the `remote_commands` bucket (the immutable binding; forward-only disposition; append-only aliases and
    conflicts) and the `remote_command_transitions` bucket (one immutable row per committed transition)
Does not own: the command schema and the disposition machine (domain `remote_control`), the cancel and pause effects
    (`MessageHandler.cancel_in`, `FleetPause.set_paused_in`), the bridge lease, the inbox rows, the receipt event
    (observation `buzz_projection`), the desk conversation (S8: refused `desk_not_migrated` until it moves)
Entry points: RemoteControl.admit, transitions_after
Contracts: INV-IDEMPOTENCY-001, INV-EXECUTION-IDENTITY-001 (Buzz DESIGN §4.3/§4.4/§6.2.3/§6.4/§6.5; DESIGN-B §6 R1-R10)

`admit(inbox_row, generation)` runs the §6.2.3 order: (i) the schema, (ii) the existing binding (replay, alias,
conflict; a terminal replay ignores age), (iii) freshness for NEW admission only, (iv) the bridge fence, the
precondition, the effect through the seam, the binding and the transition row in ONE transaction (P6). It returns the
inbox outcome the sink hands to `InboundPass` (R1). An unexpected exception from that transaction leads to ONE settle
transaction that re-reads the binding (R6, §6.4): present is its disposition, absent binds `refused: not_applied`.
A lost bridge lease propagates unchanged (nothing commits, the inbox row stays pending, §6.5).

`transitions_after` is the read side of the audit (DESIGN-B Q2, Q5): the immutable transition rows, enriched read-only
with what a receipt needs and a transition row does not carry. It writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from codex_harness.coordination.application.bridge_lease import LOST
from codex_harness.coordination.application.messages import TaskRefused
from codex_harness.coordination.domain import remote_control as rc
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.kernel.errors import ContractError

COMMANDS = "remote_commands"
INBOX = "remote_inbox"
TRANSITIONS = "remote_command_transitions"
ACTOR = "conductor"  # R8: the effects run as the conductor (the CLI cancels as the conductor)
ADMITTED, REFUSED = "command_admitted", "command_refused"
_MAX_OP_CHARS = 64


@dataclass(frozen=True)
class _Intake:
    """One event under admission: `command` is the parsed object (None: no extractable id), `refusal` the schema
    refusal (R3) when the object is not a valid command."""

    command: dict
    refusal: rc.Refusal | None
    event_id: str
    created_at: int
    received_at: int
    digest: str

    @property
    def command_id(self) -> str:
        return self.command["command_id"]


def _result(outcome: str, command_id, disposition, reason_code) -> dict:
    return {"outcome": outcome, "command_id": command_id, "disposition": disposition, "reason_code": reason_code}


def _bound_result(row: dict) -> dict:
    """The bound disposition as an inbox outcome. Only a terminal binding is ever replayed or settled (REFUSE-READING:
    `accepted`/`effect_unknown` are desk states, written only after S8; seeing one here is an error, not a guess)."""
    if row["disposition"] not in rc.TERMINAL:
        raise ContractError("remote control: nonterminal command binding is not settled here")
    outcome = ADMITTED if row["disposition"] == "effect_done" else REFUSED
    return _result(outcome, row["command_id"], row["disposition"], row["reason_code"])


class RemoteControl:
    def __init__(self, store, messages, fleet_pause, lease, owners, clock):
        self.store, self.messages, self.fleet_pause, self.lease = store, messages, fleet_pause, lease
        self.owners, self.clock = frozenset(owners), clock

    def admit(self, inbox_row: dict, generation: int) -> dict:
        """`{"outcome", "command_id", "disposition", "reason_code"}` for one pending owner inbox row."""
        if not rc.owner_allowed(inbox_row["author"], self.owners):  # R10: defence in depth, no binding, no receipt
            return _result(rc.IGNORED_NOT_OWNER, None, None, None)
        content, created_at = inbox_row["event"]["content"], inbox_row["created_at"]
        parsed = rc.parse_command(content, created_at=created_at)  # (i) the schema
        refusal = parsed if isinstance(parsed, rc.Refusal) else None
        command = rc.extract_command(content) if refusal is not None else parsed
        if command is None:  # R3: no extractable id, so nothing to bind
            return _result(REFUSED, None, None, refusal.code)
        intake = _Intake(command, refusal, inbox_row["event_id"], created_at, inbox_row["received_at"],
                         rc.command_digest(command))
        try:
            return self._admit(intake, generation)
        except Exception as exc:  # noqa: BLE001 - R6: the outcome of the transaction is unknown
            if isinstance(exc, ContractError) and str(exc) == LOST:
                raise
            return self._settle(intake, generation)

    # -- the admission transaction -----------------------------------------------------------------------

    def _admit(self, intake: _Intake, generation: int) -> dict:
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)  # §6.5: inside the transaction
            existing = tx.get(COMMANDS, intake.command_id)
            if existing is not None:  # (ii) replay, alias, conflict
                if intake.refusal is not None:  # R3: an already-bound id is never touched by a malformed event
                    if existing["event_id"] == intake.event_id:
                        return _bound_result(existing)
                    return _result(REFUSED, intake.command_id, None, intake.refusal.code)
                return self._replay(tx, existing, intake)
            if intake.refusal is not None:  # R3
                return self._bind(tx, intake, "refused", intake.refusal.code)
            if not rc.fresh_for_admission(intake.received_at, intake.created_at):  # (iii) NEW admission only
                return self._bind(tx, intake, "refused", rc.COMMAND_EXPIRED)
            return self._effect(tx, intake)  # (iv)

    def _effect(self, tx, intake: _Intake) -> dict:
        command = intake.command
        op = command["op"]
        if op in ("desk_open", "desk_turn"):  # R9: DeskTurns is never called before S8
            return self._bind(tx, intake, "refused", rc.DESK_NOT_MIGRATED)
        if op == "cancel_task":
            return self._cancel(tx, intake)
        paused = op == "pause_fleet"
        try:
            self.fleet_pause.set_paused_in(tx, paused, expected_control=command["expected_control"],
                                           allow_hold_release=False)
        except FleetRefused as refused:
            # REFUSE-READING: stale_control and activation_hold_present are the contract's codes; any other fleet
            # refusal (`unregistered`) is `not_applied` (DESIGN-B §1).
            code = refused.reason_code if refused.reason_code in (rc.STALE_CONTROL, rc.ACTIVATION_HOLD_PRESENT) \
                else rc.NOT_APPLIED
            return self._bind(tx, intake, "refused", code)
        return self._bind(tx, intake, "effect_done", None)

    def _cancel(self, tx, intake: _Intake) -> dict:
        command = intake.command
        task_id = command["task_id"]
        if not command["reason"]:  # R8: refused before the seam
            return self._bind(tx, intake, "refused", rc.INVALID_COMMAND)
        if tx.get("tasks", task_id) is None:  # the seam raises a plain ContractError for an absent task
            return self._bind(tx, intake, "refused", rc.TASK_UNKNOWN)
        try:
            self.messages.cancel_in(tx, task_id, ACTOR, command["reason"],
                                    expected_generation=command["expected_generation"])
        except TaskRefused as refused:
            return self._bind(tx, intake, "refused", refused.code)
        return self._bind(tx, intake, "effect_done", None, generation_after=tx.get("tasks", task_id)["generation"])

    # -- the binding and its transition ------------------------------------------------------------------

    def _bind(self, tx, intake: _Intake, disposition: str, reason_code: str | None, *,
              generation_after: int | None = None) -> dict:
        """The first COMMITTED disposition (R2): revision 1, the binding and its immutable transition row together."""
        if not rc.next_transition("received", disposition):
            raise ContractError("remote control: disposition is not reachable from received")
        command, valid = intake.command, intake.refusal is None
        op = command.get("op")
        args = {name: command.get(name) for name in ("task_id", "expected_generation", "expected_control", "reason",
                                                      "desk")} if valid else {}
        tx.put(COMMANDS, intake.command_id, {
            "id": intake.command_id, "command_id": intake.command_id, "event_id": intake.event_id,
            "digest": intake.digest, "op": op if isinstance(op, str) and len(op) <= _MAX_OP_CHARS else None,
            "args": args, "created_at": intake.created_at, "received_at": intake.received_at,
            "disposition": disposition, "reason_code": reason_code, "work": None, "transition_revision": 1,
            "aliases": [], "conflicts": []})
        task_id = command.get("task_id") if valid and isinstance(command.get("task_id"), str) else None
        tx.put(TRANSITIONS, f"{intake.command_id}:1", {
            "id": f"{intake.command_id}:1", "command_id": intake.command_id, "command_event_id": intake.event_id,
            "transition_revision": 1, "disposition": disposition, "reason_code": reason_code, "task_id": task_id,
            "generation_after": generation_after, "work": None, "at": int(self.clock())})
        return _bound_result(tx.get(COMMANDS, intake.command_id))

    def _replay(self, tx, existing: dict, intake: _Intake) -> dict:
        """(ii): the same content replays (another event id is an alias); other content is a conflict (R4, R5)."""
        if existing["digest"] != intake.digest:
            if intake.event_id not in {entry["event_id"] for entry in existing["conflicts"]}:
                existing["conflicts"].append({"event_id": intake.event_id, "digest": intake.digest})
                tx.put(COMMANDS, intake.command_id, existing)
            return _result(REFUSED, intake.command_id, None, rc.COMMAND_CONFLICT)
        if intake.event_id != existing["event_id"] and intake.event_id not in {
                entry["event_id"] for entry in existing["aliases"]}:
            existing["aliases"].append({"event_id": intake.event_id, "received_at": intake.received_at})
            tx.put(COMMANDS, intake.command_id, existing)
        return _bound_result(existing)

    # -- R6: the settle path -----------------------------------------------------------------------------

    def _settle(self, intake: _Intake, generation: int) -> dict:
        """ONE transaction: re-check the fence, READ the binding (§6.4). A failure here propagates (row stays pending)."""
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            existing = tx.get(COMMANDS, intake.command_id)
            if existing is None:
                return self._bind(tx, intake, "refused", rc.NOT_APPLIED)
            if intake.refusal is not None:
                return _bound_result(existing) if existing["event_id"] == intake.event_id else _result(
                    REFUSED, intake.command_id, None, intake.refusal.code)
            return self._replay(tx, existing, intake)


def transitions_after(tx, after: int | None, limit: int) -> list[dict]:
    """Transition rows with `at >= after` (all when None), oldest first by `(at, id)`, at most `limit`.

    The bound is INCLUSIVE (DESIGN-B Q5): `at` has one-second resolution, so a transition committed later in the same
    second as an already-read one must not be skipped; the reader absorbs the overlap by the receipt's op id. Each row
    is the stored transition plus `op` (the command's op), `command_author` and `channel` (from the retained inbox
    row of the command event); each is None when its source is absent. Read-only (P6).
    """
    if after is not None and (isinstance(after, bool) or not isinstance(after, int) or after < 0):
        raise ContractError("remote control: after must be a non-negative integer or None")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ContractError("remote control: limit must be a positive integer")
    rows = [row for row in tx.scan(TRANSITIONS) if after is None or row["at"] >= after]
    out = []
    for row in sorted(rows, key=lambda r: (r["at"], r["id"]))[:limit]:
        binding = tx.get(COMMANDS, row["command_id"]) or {}
        inbox = tx.get(INBOX, row["command_event_id"]) or {}
        out.append({**row, "op": binding.get("op"), "command_author": inbox.get("author"),
                    "channel": inbox.get("channel")})
    return out
