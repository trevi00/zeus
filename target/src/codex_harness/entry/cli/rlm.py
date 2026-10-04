"""The `zeus rlm` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus rlm`), run (its body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.operation)
Entry points: add_parser, run
Contracts: INV-CONTEXT-001

Moved from M7 cli.py:258-261 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 cli.py:890-903 with `service = build()` first and the one owner rule R-c23: the App Server comes from the Executor's host-transport factory (`run_task.transports.host_app_server`, hooks `executor.host_hooks.configuration()`), so production refuses with `host_transport_refused_in_production` before any process starts (S10 unit C5f).
"""


def add_parser(commands) -> None:
    rlm = commands.add_parser("rlm")
    rlm.add_argument("reference")
    rlm.add_argument("question")
    rlm.add_argument("--max-calls", type=int, default=8)


def run(args) -> None:
    from functools import partial
    from types import SimpleNamespace

    from codex_harness.composition import build
    from codex_harness.composition.operation import build_executor
    from codex_harness.context.application.rlm import RecursiveContext
    from codex_harness.entry.cli.output import emit
    from codex_harness.routing.domain.model_selection import select_model
    service = build()
    executor = build_executor(service)
    with executor.run_task.transports.host_app_server(hooks=executor.host_hooks.configuration()) as runtime:
        selected = SimpleNamespace(run=partial(runtime.run, model=select_model('design').requested_model))
        rlm = RecursiveContext(executor.artifacts, selected, str(executor.git.repository),
                               max_calls=args.max_calls)
        emit(rlm.analyze(args.reference, args.question))
