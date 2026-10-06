"""The bounded Fleet dispatcher over the LaneLauncher port: admit, launch, wait outside every transaction,
finalize owned children; never relaunches, retries or merges.

Layer: application
Context: coordination
Owns: the children this process launched (process lifetime)
Does not own: the Fleet buckets (the three Fleet objects it drives), lane processes (the launcher)
Entry points: FleetRunner.run, FleetRunner.stop
Contracts: INV-FLEET-001, INV-FLEET-BACKLOG-001

Moved from M7 `application/fleet.py` (SOURCE e38aa722) by the named split (DESIGN-s5 §F); the method
bodies are M7's.
"""

from __future__ import annotations

import logging
import time

from codex_harness.coordination.domain.fleet import FAILED, UNKNOWN, LaunchRefused, safe_code
from codex_harness.intake.domain.backlog import runner_state
from codex_harness.intake.domain.backlog import safe_error_type as safe_backlog_error_type

LOGGER = logging.getLogger("zeus.fleet.runner")


class FleetRunner:
    """Bounded dispatcher over a launcher port: `launch(job) -> handle`, `wait(handles, seconds)
    -> finished handles`, `outcome(handle, job) -> outcome`, `budget_exhausted(budget) -> bool`.
    Children are bounded by `max_parallel`, waited for outside transactions, and every claimed
    job this process launched is finalized by it even if another runner races."""

    def __init__(self, registry, admission, pause, launcher, sleep=time.sleep, interval: float = 5.0, reconcile=None,
                 backlog=None, control=None, continuation=None, observer=None):
        # DESIGN-s5 F: the runner holds the three Fleet objects it drives (M7 held one `Fleet`).
        self.fleet_registry, self.fleet_admission, self.fleet_pause = registry, admission, pause
        self.launcher, self.sleep, self.interval = launcher, sleep, interval
        # Optional descriptor-bound runtime control of a managed host target (HOST-RUNTIME.md):
        # `admission_open() -> bool`, `stop_requested() -> bool` and `heartbeat(state)`. A closed
        # admission stops the backlog tick and new admissions while owned children are still waited
        # for and finalized; a stop request is the same graceful `stop()`. None - the default -
        # keeps this runner's exact previous behaviour and writes no heartbeat.
        self.control = control
        self.admission = "open"
        # Optional bounded read/group pass run once per tick BEFORE admission, in its own
        # transaction (the adapter supplies it, so this layer keeps no portfolio dependency).
        self.reconcile = reconcile
        # Optional bounded approved-backlog tick (INV-FLEET-BACKLOG-001), also supplied by the
        # adapter and also in its own transactions. None - the default - keeps this runner's exact
        # previous behaviour: it invents no successor, no retry and no merge.
        self.backlog = backlog
        # Optional opt-in conductor continuation pass (INV-CONTINUATION-001), supplied by the adapter
        # and run in its own transactions after the backlog tick and before admission, so a
        # successor or an initial session binding it records is visible to this same admission.
        # It never waits for a conductor decision: it starts an owned child and polls it on later
        # passes. When it also offers `owned()`, `unresolved()` and `drain()`, pending conductors
        # take admission slots, count as active/unresolved work in the heartbeat, keep a graceful
        # stop draining, and are settled by `drain()` while admission is closed. None - the
        # default - keeps this runner's exact previous behaviour.
        self.continuation = continuation
        # Optional catalog observer (S10 A5-2): `path_declined` for each pass this runner was built without.
        self.observer = observer
        self.continuation_state = None
        # Last logged reconciliation state, so repeated identical failures stay silent and only a
        # real transition is written.
        self.reconciliation_state = None
        self.backlog_state = None
        self.children: dict[str, tuple[dict, object]] = {}
        self.stopping = False
        # What the conductor stop request reached (`_forward_stop`); None until a stop is forwarded.
        self.stop_request = None
        # Whether this runtime's own activation hold was released (`_release_hold`); None until tried.
        self.hold_state = None

    def stop(self) -> None:
        """Graceful stop: close admission and drain owned children; nothing is killed.

        A continuation that offers `request_stop()` is asked HERE, before any store access, to have
        the guardians of its conductor launches end their trees. That request is local and DB-free
        (SPEC stop correction), so a blocked or unavailable store cannot hold it back; it proves no
        cleanup - each guardian still writes its own proof, and each unit stays held until the Fleet
        settles it. Worker jobs are never signalled. It never raises: a stop may come from a signal."""
        self.stopping = True
        self._forward_stop()

    def _forward_stop(self) -> None:
        """Ask the continuation's guardians to stop; repeated calls ask only launches not yet asked.

        The outcome is kept in `stop_request` and reported in the run summary: a request that could
        not be written is `failed` with its error type, never counted as asked, and the guardian's
        own deadline still bounds that launch."""
        request = getattr(self.continuation, "request_stop", None)
        if request is None:
            return
        prior = self.stop_request or {"asked": [], "failed": []}
        try:
            result = request()
            asked = sorted(set(prior["asked"]) | set(result.get("asked") or []))
            failed = [row for row in result.get("failed") or [] if row.get("launch") not in asked]
            error_type = None
        except Exception as exc:
            asked, failed, error_type = prior["asked"], prior["failed"], type(exc).__name__
        state = "failed" if failed or error_type else "requested" if asked else "none"
        self.stop_request = {"state": state, "asked": asked, "failed": failed, "error_type": error_type}

    def run(self, once: bool) -> dict:
        self.fleet_registry.registered()  # refuse early when unregistered; ceilings are re-read per scan
        if self.observer is not None:
            for feature, pass_ in (("fleet_reconcile", self.reconcile), ("fleet_backlog", self.backlog),
                                   ("continuation", self.continuation)):
                if pass_ is None:
                    self.observer.emit("operations.path_declined", "observed",
                                       attributes={"feature": feature, "decline_reason": "disabled"})
        summary = {"admitted": [], "finalized": [], "finalize_failures": [], "blocked": {}, "stopped": False,
                   "reconciliation": {"state": "disabled", "error_type": None},
                   "backlog": {"state": "disabled", "outcome": None, "reason_code": None,
                               "error_type": None}}
        if self.continuation is not None:
            summary["continuation"] = {"state": "disabled", "outcome": None, "reason_code": None, "error_type": None}
        while True:
            self._release_hold(summary)
            admitting = self._admission_open(summary)
            if self.stopping:
                # Every stopping pass forwards the stop BEFORE any store access of that pass, so a
                # launch started just before the stop, or a request that failed, is asked again.
                self._forward_stop()
            self._reconcile(summary)
            progressed = False
            if admitting and not self.stopping:
                self._backlog(summary)
                progressed = self._continue(summary)
                progressed = self._admit(summary) or progressed
            else:
                self._drain_continuation(summary)
            progressed = self._reap(summary) or progressed
            self._heartbeat(summary)
            if self.children or progressed:
                continue
            if self._conductors():
                # A pending conductor child is polled on the next pass, never waited on here; a
                # graceful stop or `--once` keeps draining it rather than leaving it behind.
                self.sleep(self.interval)
                continue
            if once or self.stopping:
                break
            self.sleep(self.interval)
        summary["stopped"] = self.stopping
        if self.stop_request is not None:
            summary["stop_request"] = dict(self.stop_request)
        summary["reconciliation_required"] = self.fleet_registry.reconciliation_required()
        if self.continuation is not None:
            # A stop never reports idle past owned debt: execution units still held (a conductor
            # awaiting cleanup proof or settlement) are listed; an unreadable list is unknown.
            try:
                summary["units_held"] = self.fleet_admission.held_units()
            except Exception as exc:
                summary["units_held"] = {"state": "unknown", "error_type": type(exc).__name__}
        return summary

    def _release_hold(self, summary: dict) -> None:
        """Release the host activation hold THIS runtime was started under, once.

        A control offering `activation()` names the descriptor digest this runtime is running;
        `Fleet.release_activation_hold` resumes admission only when the pause is exactly that
        activation's hold. A failed read leaves admission paused (safe) and is tried again on the
        next pass; any other pause is not this runner's to lift."""
        if self.hold_state is not None or self.stopping:
            return
        activation = getattr(self.control, "activation", None)
        if activation is None:
            self.hold_state = "none"
            return
        try:
            released = self.fleet_pause.release_activation_hold(activation())["released"]
        except Exception as exc:
            summary["activation_hold"] = {"state": "unavailable", "error_type": type(exc).__name__}
            return
        self.hold_state = "released" if released else "none"
        summary["activation_hold"] = {"state": self.hold_state, "error_type": None}

    def _admission_open(self, summary: dict) -> bool:
        """Whether new work may be selected or admitted on this pass. Always true without control.

        A control that cannot be read closes admission rather than opening it: an unknown pause is
        treated as a pause, never as permission to take new work.
        """
        if self.control is None:
            return True
        try:
            if self.control.stop_requested():
                self.stop()
            open_ = not self.stopping and bool(self.control.admission_open())
        except Exception as exc:
            summary["control"] = {"state": "unavailable", "error_type": type(exc).__name__}
            open_ = False
        self.admission = "stopping" if self.stopping else "open" if open_ else "paused"
        return open_

    def _heartbeat(self, summary: dict) -> None:
        """Report the work this runner ACTUALLY owns, plus Fleet reservations nobody here owns.

        `active` is the number of children this process launched and has not finalized; `unresolved`
        is every dispatching or unknown job that is not one of them, which a successor could not
        account for either. A heartbeat that cannot be computed or written is simply not written:
        its reader then sees a stale or missing heartbeat, which is unknown and never idle.
        """
        if self.control is None:
            return
        try:
            owned = set(self.children)
            unresolved = [job for job in self.fleet_registry.reconciliation_required() if job not in owned]
            # Conductor children this process owns are active work; dispatched launches it does not
            # own (a previous owner's, an unconfirmed start) are unresolved. A failure to read them
            # skips the heartbeat rather than under-reporting work.
            pending = getattr(self.continuation, "unresolved", None)
            conductors = self._conductors()
            unresolved_conductors = list(pending()) if pending is not None else []
            self.control.heartbeat({"admission": self.admission, "active": len(owned) + len(conductors),
                                    "unresolved": len(unresolved) + len(unresolved_conductors)})
        except Exception as exc:
            summary["heartbeat"] = {"state": "unavailable", "error_type": type(exc).__name__}
        else:
            summary["heartbeat"] = {"state": "ok", "error_type": None}

    def _reconcile(self, summary: dict) -> None:
        """One bounded reconciliation per tick, before admission and outside every other
        transaction. It never admits, launches, finalizes or retries anything, and its failure is
        recorded as a fixed `unavailable` state with the exception TYPE only: unrelated Fleet
        admission and finalization keep running.

        A long-running service only returns its summary when it stops, so each state TRANSITION is
        also logged once: a fixed message on entering `unavailable` and one on recovery. Repeated
        identical failures stay silent, and no traceback, exception text or message is logged."""
        if self.reconcile is None:
            return
        try:
            self.reconcile()
        except Exception as exc:
            summary["reconciliation"] = {"state": "unavailable", "error_type": type(exc).__name__}
            if self.reconciliation_state != "unavailable":
                LOGGER.warning("portfolio reconciliation unavailable; fleet admission continues")
            self.reconciliation_state = "unavailable"
        else:
            summary["reconciliation"] = {"state": "ok", "error_type": None}
            if self.reconciliation_state == "unavailable":
                LOGGER.info("portfolio reconciliation recovered")
            self.reconciliation_state = "ok"

    def _backlog(self, summary: dict) -> None:
        """One bounded approved-backlog tick per cycle, before admission and outside every other
        transaction. Disabled unless the adapter wired one, and skipped once a graceful stop has
        begun, so a stopping runner admits no new work.

        It selects at most one already approved item and hands it to the ordinary `Fleet.enqueue`;
        it never admits, launches, finalizes, retries or merges anything.

        A tick that RETURNS a failure is a failure of that tick, exactly like one that raises: an
        `unavailable`, `refused`, `conflict` or `plan_unregistered` answer is reported with its own
        fixed reason code and exception TYPE, never as `ok` merely because the call returned. Idle,
        blocked and both pauses are healthy. Unrelated admission and finalization keep running, and
        only a state TRANSITION is logged - repeated identical failures, repeated idle polls, raw
        exception text and raw messages never reach a log line.
        """
        if self.backlog is None or self.stopping:
            return
        try:
            result = self.backlog()
        except Exception as exc:
            self._backlog_state(summary, "unavailable", None, None, type(exc).__name__)
        else:
            row = result if isinstance(result, dict) else {}
            outcome = row.get("outcome")
            self._backlog_state(summary, runner_state(outcome), outcome, row.get("reason_code"),
                                row.get("error_type"))

    def _backlog_state(self, summary: dict, state: str, outcome, reason_code, error_type) -> None:
        summary["backlog"] = {"state": state, "outcome": outcome,
                              "reason_code": safe_code(reason_code) if reason_code is not None else None,
                              "error_type": safe_backlog_error_type(error_type)}
        if state == self.backlog_state:
            return
        if state == "unavailable":
            LOGGER.warning("approved backlog unavailable; fleet admission continues")
        elif state != "ok":
            LOGGER.warning("approved backlog %s; fleet admission continues reason=%s", state,
                           summary["backlog"]["reason_code"])
        elif self.backlog_state is not None:
            LOGGER.info("approved backlog recovered")
        self.backlog_state = state

    def _continue(self, summary: dict) -> bool:
        """One bounded continuation pass per cycle. Its failure is its own `unavailable` state with
        the exception TYPE only; unrelated admission and finalization keep running. Returns whether
        it recorded progress (so `--once` drains a successor it just admitted)."""
        if self.continuation is None or self.stopping:
            return False
        try:
            result = self.continuation()
        except Exception as exc:
            state, row = "unavailable", {"error_type": type(exc).__name__}
        else:
            row = result if isinstance(result, dict) else {}
            state = {"refused": "refused", "disabled": "disabled"}.get(row.get("outcome"), "ok")
        summary["continuation"] = {"state": state, "outcome": row.get("outcome"),
                                   "reason_code": safe_code(row["reason_code"]) if row.get("reason_code") else None,
                                   "error_type": row.get("error_type") if isinstance(row.get("error_type"), str) else None}
        if state != self.continuation_state and state in {"unavailable", "refused"}:
            LOGGER.warning("conductor continuation %s; fleet admission continues", state)
        self.continuation_state = state
        return state == "ok" and any(action.get("effect") in {"admitted", "session_bound"}
                                     for action in row.get("actions") or [] if isinstance(action, dict))

    def _conductors(self) -> list:
        """Conductor launches this runner's continuation owns and has not settled (none without)."""
        owned = getattr(self.continuation, "owned", None)
        return list(owned()) if owned is not None else []

    def _drain_continuation(self, summary: dict) -> None:
        """Admission is closed (graceful stop or host pause): only already started conductor
        launches are polled and settled, under the binding they were started with. No new effect."""
        drain = getattr(self.continuation, "drain", None)
        if drain is None:
            return
        try:
            result = drain()
        except Exception as exc:
            state, row = "unavailable", {"error_type": type(exc).__name__}
        else:
            state, row = "draining", result if isinstance(result, dict) else {}
        summary["continuation"] = {"state": state, "outcome": row.get("outcome"), "reason_code": None,
                                   "error_type": row.get("error_type") if isinstance(row.get("error_type"), str) else None}
        if state != self.continuation_state and state == "unavailable":
            LOGGER.warning("conductor continuation %s; fleet admission continues", state)
        self.continuation_state = state

    def _admit(self, summary: dict) -> bool:
        progressed = False
        # Effective ceilings are refreshed before every admission scan: a grant made while this
        # service sleeps applies to the next scan without a restart and without any hidden reset.
        config = self.fleet_registry.registered()["config"]
        # `admit_one` is the only capacity authority: its transaction counts reserving jobs AND held
        # execution units (a conductor of any controller or standalone tick), so no local count here
        # authorizes a start or counts a durable reservation twice. `children` only bounds the loop.
        while not self.stopping and len(self.children) < config["max_parallel"]:
            exhausted = bool(self.launcher.budget_exhausted(config["budget"]))
            decision = self.fleet_admission.admit_one(budget_exhausted=exhausted)
            summary["blocked"] = decision["blocked"]
            job = decision["job"]
            if job is None:
                break
            progressed = True
            summary["admitted"].append(job["id"])
            try:
                handle = self.launcher.launch(job)
            except LaunchRefused as exc:
                self._finalize(job, {"status": FAILED, "reason_code": exc.reason_code}, summary)
            except Exception as exc:
                # The process may or may not exist: the claim, lane and paths stay reserved.
                self._finalize(job, {"status": UNKNOWN, "reason_code": "spawn_uncertain",
                                     "error_type": type(exc).__name__}, summary)
            else:
                self.children[job["id"]] = (job, handle)
        return progressed

    def _reap(self, summary: dict) -> bool:
        if not self.children:
            return False
        finished = self.launcher.wait([handle for _, handle in self.children.values()], self.interval)
        progressed = False
        for handle in finished:
            job, _ = self.children.pop(handle["job_id"])
            try:
                outcome = self.launcher.outcome(handle, job)
            except Exception as exc:
                outcome = {"status": UNKNOWN, "reason_code": "outcome_uncertain", "error_type": type(exc).__name__}
            self._finalize(job, outcome, summary)
            progressed = True
        return progressed

    def _finalize(self, job: dict, outcome: dict, summary: dict) -> None:
        try:
            row = self.fleet_admission.finalize(job["id"], job["owner_token"], outcome)
        except Exception as exc:
            # The row stays dispatching and is reported as reconciliation_required; no retry here.
            summary["finalize_failures"].append({"id": job["id"], "error_type": type(exc).__name__})
            return
        summary["finalized"].append({"id": row["id"], "status": row["status"], "reason_code": row["reason_code"]})
