"""Shared S4 scenario steps (`execution.lease_progress`): the per-call ownership check after the provider.

Layer: harness (never shipped)

`api.LeaseProgress` is the side's class; a scripted workflow records every `remaining_seconds` and
`heartbeat` call and can refuse, and a scripted monotonic clock drives the cadence. Reported: the
calls per step, the counters, and the refusal type kept on `refusal`.
"""

from __future__ import annotations


class Refused(RuntimeError):
    """The scripted workflow's refusal (an ended lease)."""


class ScriptedWorkflow:
    def __init__(self, refuse_at=None):
        self.calls, self.refuse_at = [], refuse_at

    def remaining_seconds(self, task, maximum):
        self.calls.append(["remaining_seconds", task["id"], maximum])
        if self.refuse_at is not None and len(self.calls) >= self.refuse_at:
            raise Refused("Stale or expired task execution")
        return 100.0

    def heartbeat(self, task, *args):
        self.calls.append(["heartbeat", task["id"], list(args)])


def drive(api, steps, *, refuse_at=None, own_heartbeat=False, **kwargs) -> dict:
    now = [0.0]
    workflow, beats = ScriptedWorkflow(refuse_at), []
    heartbeat = (lambda: beats.append(now[0])) if own_heartbeat else None
    progress = api.LeaseProgress(workflow, {"id": "task-1"}, heartbeat=heartbeat, clock=lambda: now[0], **kwargs)
    trace = []
    for at, stage in steps:
        now[0] = at
        before = len(workflow.calls)
        try:
            progress(stage)
            outcome = "ok"
        except Refused as exc:
            outcome = "refused:" + type(exc).__name__
        trace.append({"at": at, "stage": stage, "calls": workflow.calls[before:], "outcome": outcome})
    return {"trace": trace, "checks": progress.checks, "renewals": progress.renewals, "own_heartbeats": beats,
            "refusal": None if progress.refusal is None else type(progress.refusal).__name__,
            "check_seconds": progress.check_seconds, "renew_seconds": progress.renew_seconds}


def run(api) -> dict:
    waits = [(0.0, "replay_wait"), (1.0, "replay_wait"), (4.9, "replay_wait"), (5.0, "replay_wait"),
             (6.0, "inspection"), (19.9, "replay_wait"), (20.0, "replay_wait"), (21.0, None), (45.0, "publish")]
    return {"class": {"check": api.LeaseProgress.CHECK_SECONDS, "renew": api.LeaseProgress.RENEW_SECONDS,
                      "poll_stages": sorted(api.LeaseProgress.POLL_STAGES)},
            "default_cadence": drive(api, waits),
            "own_heartbeat": drive(api, waits, own_heartbeat=True),
            "custom_cadence": drive(api, waits, check_seconds=0.0, renew_seconds=1.0),
            "refused_mid_wait": drive(api, waits, refuse_at=3)}
