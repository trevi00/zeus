"""Zeus state to Buzz operations: plan, replan after a lost CAS, regenerate deferred work (design §4, §6.1, §6.3).

Layer: application
Context: observation
Owns: the `buzz_bindings` (the canonical task root P1 and its aliases) and `buzz_heads` (per-subject projection
    version, publication time, own head, condition and rendering digests) buckets; the mapping from the Zeus read
    models to outbox operations
Does not own: signing, sending and the capacity rule (`BuzzOutbox`), the schemas and builders (domain
    `buzz_projection`), the read models (the injected `ZeusReadModels`: coordination and execution reads wired by the
    composition, Batch D), the relay protocol (the injected RelayClient)
Entry points: BuzzProjection.plan, BuzzProjection.replan, BuzzProjection.regenerate, BuzzProjection.use_generation
Contracts: INV-OBSERVATION-001, INV-IDEMPOTENCY-001 (Buzz DESIGN §4.1-§4.5, §6.1, §6.3; DESIGN-B §7 readings Q1-Q7)

`plan(generation)` runs in ONE transaction under the bridge fence (§6.5) and is idempotent: it walks the whole audit
every pass, and the outbox's op id (`digest(subject, version)`) absorbs what is already queued, so nothing depends on a
cursor that could skip a row (Q5). Append subjects (task roots, receipts) are enqueued in ONE global order
`(at, kind, id)`, oldest first, and planning stops at the first `deferred` (the outbox's own watermark then marks where
`regenerate` resumes, Q6). A receipt is rendered ONLY from a `remote_command_transitions` row (P6); it waits, without
blocking the others, until its task's canonical root is bound. State subjects (the org snapshot, task cards) get a
strictly increasing version `1 + max(buzz_heads.version, highest outbox version)`; `prev` is the last ACKNOWLEDGED own
row of the subject, never a pending one (a pending version is superseded before it is sent), and `create` when there is
none. Coalescing (§6.3): a rendering equal to the latest queued one (version and `observed_at` excluded) produces
nothing; otherwise `may_publish` decides (org 10 s, task 2 s, terminal at once).

The canonical root (Q3, P1) is the FIRST `root:<task_id>` attempt the outbox marks `acknowledged`, bound once and never
rebound; every other attempt is an alias. No card is planned for a task before its root is bound.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest
from codex_harness.observation.application.buzz_outbox import OUTBOX
from codex_harness.observation.domain import buzz_projection as bp

BINDINGS = "buzz_bindings"
HEADS = "buzz_heads"
FOREIGN_CORRECTED = "foreign_revision_corrected"
UNVERIFIED = "unverified_foreign_revision"
PAGE = 500  # the page asked of `transitions_after`
RENDERS_KEPT = 8  # rendering digests remembered per subject
_UNSTABLE = frozenset({"version", "generated_at", "observed_at"})  # not part of "the rendering": see `_stable`
_COUNTS = ("org", "cards", "roots", "receipts", "unchanged", "coalesced", "deferred", "waiting", "unverified", "invalid",
           "no_channel", "no_root", "duplicate")


def _stable(value, *, top: bool = True):
    """The rendering minus what changes without meaning: the projection version, `generated_at` and `observed_at`
    (the client computes freshness from its own state, §4.2). `fleet.version` is the P2 control version and stays."""
    if isinstance(value, dict):
        return {key: _stable(item, top=False) for key, item in value.items()
                if not (key == "observed_at" or (top and key in _UNSTABLE))}
    if isinstance(value, list):
        return [_stable(item, top=False) for item in value]
    return value


@dataclass(frozen=True)
class _State:
    """One state subject's current rendering: `stable` is its digest, `build(version, op, prev, now)` the unsigned event."""

    subject: str
    kind: str  # "org" | "task"
    d: str
    terminal: bool
    stable: str
    build: Callable[[int, str, str | None, int], dict]


@dataclass
class _Context:
    now: int
    fleet: dict
    views: list
    by_id: dict
    org: dict | None
    bindings: dict


class BuzzProjection:
    def __init__(self, store, outbox, read_models, relay, signer_pubkeys, channels, clock):
        """`signer_pubkeys`: role id -> pubkey hex (the outbox's signing role and every org role). `channels`:
        `{"commander": id, "org_d": the pinned org artifact id, "teams": {team: channel id}}`."""
        self.store, self.outbox, self.read_models, self.relay = store, outbox, read_models, relay
        self.signer_pubkeys, self.channels, self.clock = dict(signer_pubkeys), channels, clock
        require(outbox.role in self.signer_pubkeys, "The outbox signing role needs a pubkey")
        require(isinstance(channels.get("commander"), str) and isinstance(channels.get("org_d"), str)
                and isinstance(channels.get("teams"), dict), "channels needs commander, org_d and teams")
        self.own_pubkey = self.signer_pubkeys[outbox.role]
        self.generation: int | None = None

    def use_generation(self, generation: int) -> None:
        """Remember the bridge lease generation for `replan` and `regenerate`, which the outbox calls without one."""
        self.generation = generation

    # -- plan ---------------------------------------------------------------------------------------------

    def plan(self, generation: int) -> dict:
        """Enqueue everything the Zeus state now calls for; the counts of what happened."""
        self.generation = generation
        counts = dict.fromkeys(_COUNTS, 0)
        probes = self._unverified_heads()  # relay calls stay outside the transaction
        with self.store.transaction() as tx:
            self.outbox.lease.require_current(tx, generation)
            ctx = self._context(tx)
            self._sync_roots(tx, ctx)
            self._plan_append(tx, ctx, counts)
            index = self._state_index(tx)
            for state in self._states(ctx, counts):
                if not self._plan_state(tx, ctx, state, index.get(state.subject, []), probes, counts):
                    break  # deferred: oldest first, later states wait for recovery
        return counts

    def _plan_append(self, tx, ctx: _Context, counts: dict) -> None:
        for at, kind, ident, subject, version, source in self._append_items(tx, ctx):
            if tx.get(OUTBOX, digest([subject, version])) is not None:
                counts["duplicate"] += 1
                continue
            unsigned = self._render_append(ctx, kind, source, counts)
            if unsigned is None:
                continue
            outcome = self.outbox.enqueue(tx, self.generation, subject, version, unsigned, "append")
            if outcome["status"] == "deferred":
                counts["deferred"] += 1
                break  # oldest first: nothing later may pass a deferred item
            counts["roots" if kind == 0 else "receipts"] += outcome["status"] == "enqueued"

    def _plan_state(self, tx, ctx: _Context, state: _State, rows: list, probes: dict, counts: dict) -> bool:
        """False when the outbox deferred (stop planning states this pass)."""
        head = self._head(tx, state.subject, rows)
        retry = False
        if head["condition"] == UNVERIFIED:
            current = probes.get(state.subject)
            if current is None or current["id"] == head["foreign_head_id"]:
                counts["unverified"] += 1  # Q1: not retried until the relay head changes
                return True
            head.update(condition=None, foreign_head_id=None)  # the head changed: say it again, even if unchanged
            retry = True
        latest = head["latest"]
        if not retry and latest is not None and head["renders"].get(str(latest["version"])) == state.stable:
            counts["unchanged"] += 1  # Q4: an unchanged rendering produces nothing
            return True
        if not bp.may_publish(state.kind, latest["enqueued_at"] if latest else None, ctx.now, state.terminal):
            counts["coalesced"] += 1  # §6.3: org >= 10 s, task >= 2 s, terminal immediate
            return True
        version, op, prev = self._next(head)
        try:
            unsigned = state.build(version, op, prev, ctx.now)
        except ContractError:
            counts["invalid"] += 1
            return True
        outcome = self.outbox.enqueue(tx, self.generation, state.subject, version, unsigned, "state")
        if outcome["status"] == "deferred":
            counts["deferred"] += 1
            return False
        if outcome["status"] != "enqueued":
            counts["duplicate"] += 1
            return True
        self._put_head(tx, head, version=version, last_published_at=ctx.now, render=(version, state.stable))
        counts["org" if state.kind == "org" else "cards"] += 1
        return True

    # -- replan (Q1: the CAS path) ------------------------------------------------------------------------

    def replan(self, subject: str) -> dict | None:
        """A state op lost its CAS or its window: read the CURRENT relay head (never a remembered one) and decide.

        `{"superseded": True}` when our own newer-or-equal revision is the head, or when a foreign head cannot be
        corrected (recorded `unverified_foreign_revision`); a corrective `{"version", "unsigned"}` over a foreign (or
        our own older) head with `prev` = that head (a foreign one is recorded `foreign_revision_corrected`); None
        when nothing can be decided (no generation, no positive head answer, an unknown subject): the op stays unknown.
        """
        d = self._d_of(subject)
        if self.generation is None or d is None:
            return None
        head_event = self._query_head(d)  # outside any transaction
        if head_event is None:
            return None
        with self.store.transaction() as tx:
            self.outbox.lease.require_current(tx, self.generation)
            ctx = self._context(tx)
            self._sync_roots(tx, ctx)
            head = self._head(tx, subject, self._state_index(tx).get(subject, []))
            head_version = self._content_version(head_event)
            if head_event["pubkey"] in self.signer_pubkeys.values():
                if head_version is not None and head_version >= head["version"]:
                    return {"superseded": True}
                condition = head["condition"]  # our own older revision: the next version goes over it
            elif head_event["id"] != head["foreign_head_id"] and self._tag(head_event, "op") in bp.CARD_OPS:
                condition = FOREIGN_CORRECTED
            else:  # a foreign delete/move, or the head we already corrected over: nothing is published over it
                self._put_head(tx, head, condition=UNVERIFIED, foreign_head_id=head_event["id"])
                return {"superseded": True}
            state = next((s for s in self._states(ctx, dict.fromkeys(_COUNTS, 0)) if s.subject == subject), None)
            if state is None:  # the source is gone (or its root is not bound): nothing to say over the head
                return {"superseded": True}
            version = head["version"] + 1
            try:
                unsigned = state.build(version, "update", head_event["id"], ctx.now)
            except ContractError:
                return None
            self._put_head(tx, head, condition=condition, version=version, render=(version, state.stable),
                           foreign_head_id=head_event["id"] if condition == FOREIGN_CORRECTED else head["foreign_head_id"])
        return {"version": version, "unsigned": unsigned}

    # -- regenerate (Q5, Q6) ------------------------------------------------------------------------------

    def regenerate(self, cls: str, after: list | None) -> list[dict]:
        """The deferred work of `cls` after the outbox watermark `[subject, version]`, oldest first.

        Append: roots and receipts in the plan's global order, from the audit and the task rows. State: the org and
        the cards of the current Zeus state, with no coalescing wait (this is catch-up) but with the unchanged rule.
        """
        if self.generation is None or cls not in ("append", "state"):
            return []
        mark = after[0] if after else None
        out = []
        with self.store.transaction() as tx:
            self.outbox.lease.require_current(tx, self.generation)
            ctx = self._context(tx)
            self._sync_roots(tx, ctx)
            if cls == "append":
                items = self._append_items(tx, ctx)
                subjects = [item[3] for item in items]
                start = subjects.index(mark) + 1 if mark in subjects else 0
                for at, kind, ident, subject, version, source in items[start:]:
                    unsigned = self._render_append(ctx, kind, source, dict.fromkeys(_COUNTS, 0))
                    if unsigned is not None:
                        out.append({"subject": subject, "version": version, "unsigned": unsigned})
                return out
            index = self._state_index(tx)
            states = self._states(ctx, dict.fromkeys(_COUNTS, 0))
            subjects = [state.subject for state in states]
            start = subjects.index(mark) + 1 if mark in subjects else 0
            for state in states[start:]:
                head = self._head(tx, state.subject, index.get(state.subject, []))
                latest = head["latest"]
                if latest is not None and head["renders"].get(str(latest["version"])) == state.stable:
                    continue
                version, op, prev = self._next(head)
                try:
                    unsigned = state.build(version, op, prev, ctx.now)
                except ContractError:
                    continue
                self._put_head(tx, head, render=(version, state.stable))  # the digest the next plan compares against
                out.append({"subject": state.subject, "version": version, "unsigned": unsigned})
        return out

    # -- the canonical roots (Q3) -------------------------------------------------------------------------

    def _sync_roots(self, tx, ctx: _Context) -> None:
        """Bind each task to the first acknowledged root attempt (once, never rebound); every other attempt is an alias."""
        rows = sorted((row for row in tx.scan(OUTBOX) if row["cls"] == "append" and row["subject"].startswith("root:")
                       and row["status"] == "acknowledged"),
                      key=lambda row: (row["last_attempt_at"] or 0, row["version"], row["id"]))
        for row in rows:
            task_id = row["subject"][len("root:"):]
            canonical = row.get("canonical_event_id") or row["event_id"]
            binding = ctx.bindings.get(task_id)
            if binding is None:
                binding = {"id": task_id, "task_id": task_id, "canonical_root_event_id": canonical, "aliases": [],
                           "bound_at": ctx.now, "bound_op": row["id"]}
            changed = task_id not in ctx.bindings
            for attempt in (canonical, row["event_id"]):
                if attempt != binding["canonical_root_event_id"] and attempt not in binding["aliases"]:
                    binding["aliases"].append(attempt)
                    changed = True
            if changed:
                tx.put(BINDINGS, task_id, binding)
                ctx.bindings[task_id] = binding

    # -- append items (roots and receipts) ----------------------------------------------------------------

    def _append_items(self, tx, ctx: _Context) -> list:
        """`(at, kind, id, subject, version, source)` sorted oldest first: roots (kind 0) then receipts (kind 1)."""
        items = []
        for view in ctx.views:
            items.append((view["created_at"], 0, view["task_id"], "root:" + view["task_id"], 1, view))
        for row in self._transitions(tx):
            items.append((row["at"], 1, row["id"], bp.receipt_op(row["command_id"], row["transition_revision"]),
                          row["transition_revision"], row))
        return sorted(items, key=lambda item: (item[0], item[1], item[2]))

    def _transitions(self, tx) -> list:
        rows, after, limit = {}, None, PAGE
        while True:
            page = self.read_models.transitions_after(tx, after, limit)
            rows.update((row["id"], row) for row in page)
            if len(page) < limit:
                return list(rows.values())
            if page[-1]["at"] == after:  # a full page of one second: widen it rather than loop
                limit *= 2
            after = page[-1]["at"]

    def _render_append(self, ctx: _Context, kind: int, source: dict, counts: dict) -> dict | None:
        try:
            if kind == 0:
                channel = self._team_channel(source["team"])
                if channel is None:
                    counts["no_channel"] += 1
                    return None
                return bp.task_root(task_id=source["task_id"], title=source["title"], team=source["team"],
                                    assignee=source["assignee"], channel=channel, created_at=ctx.now)
            return self._render_receipt(ctx, source, counts)
        except (ContractError, KeyError, TypeError):
            counts["invalid"] += 1
            return None

    def _render_receipt(self, ctx: _Context, row: dict, counts: dict) -> dict | None:
        """Q5: a receipt is the transition row, threaded under its canonical root (the task root for a cancel of a known
        task, else the command event itself in the command's channel). Waits while that root is unbound."""
        if row["command_author"] is None:
            counts["invalid"] += 1  # no retained inbox row: the receipt's `p` cannot be named (REFUSE-READING)
            return None
        view = ctx.by_id.get(row["task_id"]) if row["op"] == "cancel_task" and row["task_id"] else None
        if view is not None:
            binding = ctx.bindings.get(view["task_id"])
            if binding is None:
                counts["waiting"] += 1
                return None
            root = binding["canonical_root_event_id"]
            channel = row["channel"] or self._team_channel(view["team"])
        else:
            root, channel = row["command_event_id"], row["channel"] or self.channels["commander"]
        if channel is None:
            counts["no_channel"] += 1
            return None
        return bp.receipt(command_id=row["command_id"], command_event_id=row["command_event_id"],
                          command_author=row["command_author"], root_event_id=root, channel=channel,
                          transition_revision=row["transition_revision"], disposition=row["disposition"],
                          reason_code=row["reason_code"], task_id=row["task_id"],
                          generation_after=row["generation_after"], work=row["work"], at=row["at"], created_at=ctx.now)

    # -- state subjects ------------------------------------------------------------------------------------

    def _states(self, ctx: _Context, counts: dict) -> list[_State]:
        """The org snapshot, then one card per task whose root is bound, oldest task first."""
        out = []
        state = self._org_state(ctx, counts)
        if state is not None:
            out.append(state)
        for view in ctx.views:
            binding = ctx.bindings.get(view["task_id"])
            if binding is None:
                counts["no_root"] += 1  # Q3: no card before the binding
                continue
            channel = self._team_channel(view["team"])
            if channel is None:
                counts["no_channel"] += 1
                continue
            try:
                out.append(self._card_state(ctx, view, binding["canonical_root_event_id"], channel))
            except (ContractError, KeyError, TypeError):
                counts["invalid"] += 1
        return out

    def _card_state(self, ctx: _Context, view: dict, root: str, channel: str) -> _State:
        fleet = {"paused": ctx.fleet["paused"], "activation_hold": ctx.fleet["activation_hold"]}
        core = {"task_id": view["task_id"], "generation": view["generation"], "status": view["status"],
                "assignee": view["assignee"], "sender": view["sender"], "team": view["team"], "stage": view["stage"],
                "updated_at": view["updated_at"], "observed_at": view["observed_at"], "summary": view["summary"],
                "evidence_refs": list(view["evidence_refs"]),
                "interventions": bp.interventions({"terminal": view["terminal"]}, fleet)}
        title, recipient = view["title"], view["assignee"]

        def build(version: int, op: str, prev: str | None, now: int) -> dict:
            return bp.task_card(task={**core, "version": version}, title=title, recipient_role=recipient,
                                channel=channel, root_event_id=root, created_at=now, op=op, prev=prev)

        build(0, "create", None, 0)  # validates the rendering now: a malformed view is `invalid`, not a later crash
        stable = digest([_stable(core), title, root, channel])
        return _State("task:" + view["task_id"], "task", bp.task_artifact_d(view["task_id"]),
                      view["terminal"] is True, stable, build)

    def _org_state(self, ctx: _Context, counts: dict) -> _State | None:
        if ctx.org is None:
            return None
        try:
            roles = [{**{k: role[k] for k in ("id", "role", "parent", "team", "display", "status")},
                      "pubkey": self.signer_pubkeys.get(role["id"])} for role in ctx.org["roles"]]
            if any(role["pubkey"] is None for role in roles):
                counts["invalid"] += 1  # REFUSE-READING: a snapshot naming a role without a key is not published
                return None
            core = {"roles": roles, "fleet": {"paused": ctx.fleet["paused"], "version": ctx.fleet["control_version"],
                                              "activation_hold": ctx.fleet["activation_hold"]}}
            channel, d = self.channels["commander"], self.channels["org_d"]

            def build(version: int, op: str, prev: str | None, now: int) -> dict:
                return bp.org_snapshot(org={**core, "version": version, "generated_at": now}, d=d, channel=channel,
                                       created_at=now, op=op, prev=prev)

            build(0, "create", None, 0)
        except (ContractError, KeyError, TypeError):
            counts["invalid"] += 1
            return None
        return _State("org", "org", d, False, digest(_stable(core)), build)

    # -- heads ---------------------------------------------------------------------------------------------

    @staticmethod
    def _state_index(tx) -> dict:
        index: dict = {}
        for row in tx.scan(OUTBOX):
            if row["cls"] == "state":
                index.setdefault(row["subject"], []).append(row)
        return index

    @staticmethod
    def _head(tx, subject: str, rows: list) -> dict:
        """The subject's head, derived from the outbox (the truth) and the stored record (version, digests, condition)."""
        stored = tx.get(HEADS, subject) or {"id": subject, "subject": subject, "version": 0, "last_published_at": None,
                                            "own_head_event_id": None, "condition": None, "foreign_head_id": None,
                                            "renders": {}}
        latest = max(rows, key=lambda row: row["version"], default=None)
        acked = max((row for row in rows if row["status"] == "acknowledged"), key=lambda row: row["version"],
                    default=None)
        stored["version"] = max(stored["version"], latest["version"] if latest else 0)
        return {**stored, "latest": latest, "acked": acked}

    @staticmethod
    def _next(head: dict) -> tuple[int, str, str | None]:
        acked = head["acked"]
        return head["version"] + 1, ("update" if acked else "create"), (acked["event_id"] if acked else None)

    @staticmethod
    def _put_head(tx, head: dict, *, render: tuple | None = None, **changes) -> None:
        body = {key: value for key, value in head.items() if key not in ("latest", "acked")}
        body.update(changes)
        body["own_head_event_id"] = head["acked"]["event_id"] if head["acked"] else body["own_head_event_id"]
        if render is not None:
            renders = {**body["renders"], str(render[0]): render[1]}
            body["renders"] = dict(sorted(renders.items(), key=lambda item: int(item[0]))[-RENDERS_KEPT:])
        tx.put(HEADS, body["subject"], body)

    # -- relay head -----------------------------------------------------------------------------------------

    def _unverified_heads(self) -> dict:
        """The relay's current head of each subject recorded `unverified_foreign_revision` (only those are re-queried)."""
        with self.store.transaction() as tx:
            subjects = [row["subject"] for row in tx.scan(HEADS) if row["condition"] == UNVERIFIED]
        return {subject: self._query_head(self._d_of(subject)) for subject in subjects if self._d_of(subject)}

    def _query_head(self, d: str) -> dict | None:
        """The current 45010 head of `d` (`{"kinds":[45010], "#d":[d]}`), or None: an empty, erroring or non-EOSE
        answer proves nothing (P1)."""
        try:
            result = self.relay.query([{"kinds": [bp.KIND_ARTIFACT], "#d": [d]}])
        except Exception:  # noqa: BLE001
            return None
        if result.get("ended") != "eose":
            return None
        events = [event for event in result.get("events", []) if event.get("kind") == bp.KIND_ARTIFACT
                  and self._tag(event, "d") == d]
        return min(events, key=lambda event: (-event["created_at"], event["id"]), default=None)

    @staticmethod
    def _tag(event: dict, name: str) -> str | None:
        return next((tag[1] for tag in event.get("tags", []) if len(tag) > 1 and tag[0] == name), None)

    @staticmethod
    def _content_version(event: dict) -> int | None:
        try:
            version = json.loads(event["content"]).get("version")
        except (ValueError, KeyError, AttributeError, TypeError):
            return None
        return version if type(version) is int else None

    def _d_of(self, subject: str) -> str | None:
        if subject == "org":
            return self.channels["org_d"]
        return bp.task_artifact_d(subject[len("task:"):]) if subject.startswith("task:") and len(subject) > 5 else None

    # -- the Zeus read side -------------------------------------------------------------------------------

    def _context(self, tx) -> _Context:
        try:
            fleet = dict(self.read_models.fleet(tx))
        except Exception:  # noqa: BLE001 - an unreadable fleet row is unknown, never optimistic (§6.3)
            fleet = {"paused": None, "activation_hold": None, "control_version": None}
        try:
            org = self.read_models.org(tx)
        except Exception:  # noqa: BLE001
            org = None
        views = sorted(self.read_models.tasks(tx), key=lambda view: (view["created_at"], view["task_id"]))
        return _Context(int(self.clock()), fleet, views, {view["task_id"]: view for view in views}, org,
                        {row["task_id"]: row for row in tx.scan(BINDINGS)})

    def _team_channel(self, team: str) -> str | None:
        channel = self.channels["teams"].get(team)
        return channel if isinstance(channel, str) else None
