"""The per-call ownership check for one bounded piece of post-provider work (research-dispatch-001).

Layer: application
Context: execution
Owns: LeaseProgress (M7 `adapters/executor.py` class, moved unchanged)
Does not own: the lease itself: renewal and the remaining-deadline read go through the injected
    `workflow` (execution.ports.TaskLedger, coordination's TaskOwnership in S5)
Entry points: LeaseProgress
Contracts: INV-EXECUTION-IDENTITY-001

A stale owner must stop before it spawns another child or publishes (RESEARCH-S4 R1/R2: the lease is
re-checked by the store, never trusted from a cached verdict at a boundary).
"""

from __future__ import annotations

import time

from codex_harness.execution.domain.output_contracts import LEASE_CHECK_SECONDS, LEASE_RENEW_SECONDS
from codex_harness.kernel.policy import POLICY


class LeaseProgress:
    """One owner's per-call ownership check for one bounded piece of post-provider work.

    research-dispatch-001: the provider heartbeat covers the provider call only. The executor renewed
    the lease immediately after it and then replayed the worker's evidence synchronously, with no
    check at all - so an inspection whose replays ran for minutes could finish, and try to publish,
    after the lease it was working under had already expired (host inspection at 05:21:35 UTC under a
    lease until 05:20:28 UTC).

    This is not a renewal thread and not a shared callback: the caller builds ONE of these for ONE
    call and hands it down, so every check runs on the working thread between bounded waits and stops
    existing when the call returns. It renews through the existing workflow heartbeat, at its
    existing duration - nothing here makes a lease longer - and re-reads the remaining deadline
    through `remaining_seconds`, which refuses a lost, superseded or expired execution. The refusal
    is raised unchanged so the caller's own failure path keeps its type, and is kept on `refusal` so
    that caller can tell an ended lease from a failure of the work itself.

    The cadence throttles the polls of one wait only: at every boundary the ownership and deadline
    read is fresh. Renewal keeps its own longer cadence - a boundary must not turn into a heartbeat
    per replay, and nothing here lengthens a lease.
    """

    # The cadence lives on the class so one call's rhythm is visible and a test can shorten it
    # without a second scheduler; an instance may still be built with its own.
    CHECK_SECONDS = LEASE_CHECK_SECONDS
    RENEW_SECONDS = LEASE_RENEW_SECONDS
    # Only the intermediate polls of one wait are throttled to that cadence. Every other stage is a
    # BOUNDARY - an inspection or a replay is about to start, or its result is about to travel on -
    # and there the ownership and deadline read is taken fresh, because a verdict cached up to five
    # seconds ago is exactly what let a lost owner spawn one more child and publish after its lease.
    POLL_STAGES = frozenset({'replay_wait'})

    def __init__(self, workflow, task, *, heartbeat=None, clock=time.monotonic,
                 check_seconds=None, renew_seconds=None):
        self.workflow, self.task, self._heartbeat = workflow, task, heartbeat
        self.clock = clock
        self.check_seconds = self.CHECK_SECONDS if check_seconds is None else check_seconds
        self.renew_seconds = self.RENEW_SECONDS if renew_seconds is None else renew_seconds
        self.checked = self.renewed = None
        self.checks = self.renewals = 0
        self.refusal = None

    def __call__(self, stage=None):
        now = self.clock()
        boundary = stage not in self.POLL_STAGES
        try:
            if boundary or self.checked is None or now - self.checked >= self.check_seconds:
                self.workflow.remaining_seconds(self.task, POLICY.task_lease_seconds)
                self.checked, self.checks = now, self.checks + 1
            if self.renewed is None or now - self.renewed >= self.renew_seconds:
                if self._heartbeat is not None:
                    self._heartbeat()
                else:
                    self.workflow.heartbeat(self.task)
                self.renewed, self.renewals = now, self.renewals + 1
        except BaseException as exc:
            self.refusal = exc
            raise
