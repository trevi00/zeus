"""The `zeus serve` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus serve`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_cycle, composition.cli_bus, composition.observation, composition.operation)
Entry points: add_parser, run
Contracts: INV-MESSAGE-001, INV-OBSERVATION-001

Moved from M7 cli.py:224-227 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `_serve` is M7 `serve` (SOURCE cli.py:83-) with `Workflow(store, org)` on `composition.cli_cycle.serve_handler`, `RedisBus(redis_url())` on `composition.cli_bus.bus()`, `service.flush_outbox(bus, audit=)` on `composition.cli_bus.flusher(service).flush(bus, audit=)`, `service.record_incident` on `composition.cli_cycle.incident_recorder` and the imports remapped; `run` is the M7 `main()` branch with `service = build()` first (S10 unit C5e, R-c22). Declared target addition (S10 unit A5-1a, R-a51a, DESIGN-s10 §17a): SIGINT/SIGTERM/SIGBREAK end the loop after the iteration in hand, close the observer and print `{"status": "stopped", ...}` (M7's serve was killed and printed nothing); the `--once` and idle paths are M7's.
"""


def add_parser(commands) -> None:
    s = commands.add_parser("serve")
    s.add_argument("--agent", required=True)
    s.add_argument("--once", action="store_true")
    s.add_argument("--execute", action="store_true")


def _serve(service, agent: str, once: bool, execute: bool = False, observer=None) -> None:
    import json
    import signal
    import sys
    import threading
    import time
    from contextlib import suppress
    from uuid import uuid4

    from codex_harness.composition import cli_bus, cli_cycle
    from codex_harness.composition.observation import build_observer
    from codex_harness.entry.cli.output import emit
    from codex_harness.kernel.errors import ContractError, require
    from codex_harness.kernel.ids import utcnow
    from codex_harness.kernel.policy import POLICY
    service.org.actor(agent)
    bus = cli_bus.bus()
    consumer = f"{agent}:{uuid4()}"
    last_activity = time.monotonic()
    record_incident = cli_cycle.incident_recorder(service)
    flusher = cli_bus.flusher(service)
    # INV-OBSERVATION-001: one process run, one spool; message receipt, ledger acceptance and the
    # transport acknowledgement are three separate general-log facts, none of them a task result.
    observer = observer or build_observer(service.store, "cli.serve", agent)
    workflow = cli_cycle.serve_handler(service, observer)  # S11 XC-3: task_spec_bound goes through this observer
    if execute:
        from codex_harness.composition.operation import build_executor
        executor = build_executor(service, observer=observer)
    else:
        executor = None
    prefer_decisions = True
    observer.emit("general.process_started", "started",
                  attributes={"agent": agent, "autonomous": execute, "platform": sys.platform,
                              "python": sys.version.split()[0], "mode": "serve"})
    emit({"status": "listening", "agent_id": agent, "autonomous": execute,
          "process_run_id": observer.process_run_id})
    # R-a51a, DESIGN-s10 §17a: SIGINT/SIGTERM/SIGBREAK only set a flag; the iteration in hand (the row, its
    # flush and ack, the executor turn) settles before the loop ends. Handlers can be installed from the main
    # thread only; the previous ones are restored on every exit (the composition.cli_desk precedent).
    stopping = {"stop": False}
    installed = []  # (signal number, previous handler) for each handler THIS run replaced
    try:
        if threading.current_thread() is threading.main_thread():
            def stop_handler(*_):
                stopping["stop"] = True
            for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
                if hasattr(signal, name):
                    number = getattr(signal, name)
                    installed.append((number, signal.signal(number, stop_handler)))
        while not stopping["stop"]:
            row = bus.receive(agent, consumer)
            if row:
                entry_id, fields = row
                message = None
                try:
                    message = bus.decode(fields)
                    observer.emit("general.message_received", "observed", correlation_id=message["correlation_id"],
                                  causation_id=message["message_id"],
                                  attributes={"stream_entry_id": entry_id, "message_id": message["message_id"],
                                              "message_type": message["type"], "sender": message["who"]["sender"],
                                              "recipient": message["who"]["recipient"]})
                    require(message["who"]["recipient"] == agent, "Message routed to wrong agent")
                    service.org.authorize(message)
                    if message["type"] == "incident.report":
                        result = record_incident(message)
                    else:
                        result = workflow.handle(message)
                    observer.emit("general.message_accepted", "succeeded", correlation_id=message["correlation_id"],
                                  causation_id=message["message_id"],
                                  attributes={"message_id": message["message_id"], "message_type": message["type"],
                                              "result_kind": type(result).__name__})
                    flusher.flush(bus, audit=observer.audit_system)
                    bus.ack(agent, entry_id)
                    observer.emit("general.message_acknowledged", "observed", correlation_id=message["correlation_id"],
                                  causation_id=message["message_id"],
                                  attributes={"stream_entry_id": entry_id, "message_id": message["message_id"]})
                    emit({"message_id": message["message_id"], "result": result})
                    last_activity = time.monotonic()
                except (ContractError, json.JSONDecodeError, KeyError) as exc:
                    bus.dead_letter(agent, entry_id, fields, str(exc))
                    observer.emit("general.message_rejected", "blocked", severity="warning",
                                  correlation_id=message.get("correlation_id") if isinstance(message, dict) else None,
                                  reason_code=type(exc).__name__,
                                  attributes={"stream_entry_id": entry_id, "error_type": type(exc).__name__,
                                              "dead_letter": True})
                    emit({"rejected": entry_id, "reason": str(exc)})
            if executor:
                # Give both durable queues turns, even under a continuous task backlog.
                first, second = ((executor.decide_one, executor.execute_one) if prefer_decisions
                                 else (executor.execute_one, executor.decide_one))
                result = first(agent) or second(agent)
                prefer_decisions = not prefer_decisions
                if result:
                    emit({"execution": result})
                    flusher.flush(bus, audit=observer.audit_system)
                    last_activity = time.monotonic()
            if once:
                break
            if time.monotonic() - last_activity >= POLICY.idle_seconds:
                observer.emit("general.process_idle_exit", "observed",
                              attributes={"agent": agent, "idle_seconds": POLICY.idle_seconds})
                observer.close()
                emit({"status": "idle_exit", "agent": agent, "at": utcnow()})
                return
    finally:
        for number, previous in reversed(installed):
            with suppress(Exception):  # a restore failure never replaces the original outcome
                signal.signal(number, previous)
    observer.close()
    if stopping["stop"] and not once:
        emit({"status": "stopped", "agent": agent, "at": utcnow()})


def run(args) -> None:
    from codex_harness.composition import build
    service = build()
    _serve(service, args.agent, args.once, args.execute)
