"""Measure the window after a paused or stopped database is brought back.

`readiness-004` measured the window at **start**: every disposable stack has a stretch where the
published port accepts TCP and PostgreSQL still refuses the session, and readiness now waits for a
real answer instead of an open socket. That gate is in `VerificationServices.__enter__`.

The interruption tests bring the same database back **mid-test** - `unpause`, or
`up -d --no-recreate --wait` after a `stop` - and then assert immediately. Those paths have either no
gate at all or only the container healthcheck, and a healthcheck is not the claim "this service can
answer me". The two CI failures in the ledger are exactly the two refusals such a window produces:

    B  test_postgres_pause_is_not_a_clock_step        server closed the connection unexpectedly
    C  test_host_probe_never_falls_back_to_public_tasks  FATAL: the database system is starting up

This measures whether that window exists on the resume paths, and how wide it is. It does not assume
it: a run where health and the first answer coincide would say so.

The repetition plan is fixed here, before anything runs, and every cycle is recorded - the ones that
found nothing too.

    uv run python scripts/resume_probe.py --label wsl-ubuntu-26.04 --out docs/zeus/evidence/...json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.verification import VerificationServices  # noqa: E402

CYCLES_PER_WAY = 4
WAYS = ("pause", "stop", "restart")
WATCH_SECONDS = 30.0
GAP = 0.02


def health(container):
    """What the container healthcheck says right now, or None when it cannot be read.

    One `docker inspect` against an id resolved before the interruption. Resolving the id inside the
    loop cost about a third of a second per pass, which is wider than the window being looked for.
    """
    if not container:
        return None
    from codex_harness.adapters.commands import run_process

    try:
        done = run_process(["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
                           timeout=10)
        return (done.stdout or "").strip() or None
    except Exception:
        return None


def bring_down_and_back(services, way):
    """Interrupt postgres the way the interruption tests do, and put it back the same way."""
    if way == "pause":
        services._command("pause", "postgres")
        time.sleep(2.0)
        started = time.monotonic()
        services._command("unpause", "postgres")
    elif way == "stop":
        services._command("stop", "--timeout", "5", "postgres")
        started = time.monotonic()
        services._command("up", "-d", "--no-recreate", "--wait", "postgres")
    else:
        started = time.monotonic()
        services._command("restart", "postgres")
    return started


def watch(services, container, port, started):
    """From the moment the bring-back returned: when health goes green, when an answer arrives."""
    refusals, first_healthy, first_answer = {}, None, None
    healthy_before_answer = None
    deadline = started + WATCH_SECONDS
    while time.monotonic() < deadline and first_answer is None:
        state = health(container)
        if first_healthy is None and state == "healthy":
            first_healthy = round(time.monotonic() - started, 3)
        try:
            services._answer("postgres", port, 2.0)
            first_answer = round(time.monotonic() - started, 3)
            if first_healthy is not None and healthy_before_answer is None:
                healthy_before_answer = True
        except BaseException as exc:
            kind = services._refusal_kind(exc)
            refusals[kind] = refusals.get(kind, 0) + 1
            if first_healthy is not None and healthy_before_answer is None:
                # Health said green and this request was still refused. That is the window.
                healthy_before_answer = False
            time.sleep(GAP)
    return {"first_healthy_after": first_healthy, "first_answer_after": first_answer,
            "refusals": refusals,
            "refused_after_health_was_green": healthy_before_answer is False,
            "gate_would_have_been_wrong": bool(first_healthy is not None and first_answer is not None
                                               and first_healthy < first_answer)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cycles = []
    for way in WAYS:
        for index in range(CYCLES_PER_WAY):
            # A scratch room of its own, outside the repository. Writing these next to the evidence
            # left a dozen working directories behind in the tree on the first run.
            with tempfile.TemporaryDirectory(prefix="zeus-resume-") as scratch:
                room = pathlib.Path(scratch)
                services = VerificationServices(room / "verification",
                                                FileArtifacts(room / "artifacts"))
                with services as endpoints:
                    port = int(endpoints["database_url"].rsplit(":", 1)[1].split("/")[0])
                    container = services._command("ps", "-q", "postgres", timeout=20).strip()
                    started = bring_down_and_back(services, way)
                    row = watch(services, container, port, started)
            row.update({"way": way, "cycle": index})
            cycles.append(row)
            print(json.dumps(row))

    windows = [row for row in cycles if row["gate_would_have_been_wrong"]]
    summary = {
        "label": args.label, "plan": {"ways": list(WAYS), "cycles_per_way": CYCLES_PER_WAY},
        "cycles": cycles,
        "cycles_where_health_was_green_before_the_first_answer": len(windows),
        "cycles_where_a_request_was_refused_after_health_went_green":
            sum(1 for row in cycles if row["refused_after_health_was_green"]),
        "widest_gap_seconds": max([round(row["first_answer_after"] - row["first_healthy_after"], 3)
                                   for row in windows] or [0.0]),
        "note": "measured on the resume paths the interruption tests use; the start path is gated "
                "by _await_service and is not what this measures",
    }
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(summary, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "cycles"}, indent=1))


if __name__ == "__main__":
    main()
