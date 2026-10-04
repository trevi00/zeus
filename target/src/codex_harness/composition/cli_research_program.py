"""The `zeus research-program` composition: the state machine with its ports and the builders of the program runner's adapters.

Layer: composition
Owns: research_program, packaged_policy, artifacts, call_budget, research_sources, git_capture, program_runner, pressure_evaluator, recovery_evidence, transport_probe
Does not own: the argument shape and the command bodies (entry.cli.research_program), the state machine and the runner (research.application, research.adapters) and the git source (composition.cli_research)
Entry points: research_program, packaged_policy, artifacts, call_budget, research_sources, git_capture, program_runner, pressure_evaluator, recovery_evidence, transport_probe
Contracts: INV-RESEARCH-PROGRAM-001, INV-DISCOVERY-PRESSURE-001

Built from the construction statements of M7 `adapters/research_program_cli.py` (SOURCE e38aa722) by named rule R-c26 (S10 unit C6c): `ResearchProgram(service.store[, token=...])` (:77, :150), `packaged_policy()` (:61),
`FileArtifacts(str(runtime / "artifacts"))` (:83), `CallBudget()` (:93), `ResearchSources(artifacts, pressure=evaluator)` (:92), `GitCapture(repository)` and `ProgramRunner(...)` (:92-94), `pressure(store, observer)` (:90),
`ExecutionEvidence(FileArtifacts(...))` (:119-121) and `TransportProbe(RedisBus(redis_url()), scoped=RedisBus.for_run(...))` (:128-133), with the target homes (`research.application.research_program`, `routing.adapters.provider_policy`,
`storage.adapters.file_artifacts`, `execution.adapters.call_budget`, `research.adapters.research`, `research.adapters.research_program`, `research.adapters.autonomous_evidence`, `storage.adapters.redis_bus`).
`research_program` wires the three ports of `tests/ported/m7_research.ResearchProgram` (coordination's `ResearchLaunchFacts`, the `execution_fence` module and the `outbox_relay` module); `git_capture`, `program_runner` and `pressure_evaluator`
are `composition.research_program_adapters` (the host_os process runner and Git source, the dge source verifier, the host ledger and the census reader). Imports sit inside the functions, so importing this module stays light.
"""


def research_program(store, token=None, observer=None):
    """`ResearchProgram(store[, token=...])` with its three composition ports wired; `token` is the cycle owner of a `--cycle-owner` run.

    `observer` (S10 F2-B) is an observer the caller already holds: the program is then the composition wrapper that reports its
    investigation claims as `queue_item_waited` (`composition.queue_waits`); without one it is the plain `ResearchProgram`."""
    from codex_harness.coordination.application import execution_fence, outbox_relay
    from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
    from codex_harness.research.application.research_program import ResearchProgram
    ports = dict(launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay)
    if token is not None:
        ports["token"] = token
    if observer is not None:
        from codex_harness.composition.queue_waits import observed_research_program
        return observed_research_program(store, observer, **ports)
    return ResearchProgram(store, **ports)


def packaged_policy():
    """The packaged provider policy (an entry module may not import the routing adapter)."""
    from codex_harness.routing.adapters import provider_policy
    return provider_policy.packaged_policy()


def artifacts(runtime):
    """The artifact store of the runtime directory: `FileArtifacts(str(runtime / "artifacts"))`."""
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return FileArtifacts(str(runtime / "artifacts"))


def call_budget():
    from codex_harness.execution.adapters.call_budget import CallBudget
    return CallBudget()


def research_sources(artifacts, pressure=None):
    """`ResearchSources(artifacts, pressure=evaluator)`; None holds every proactive fetch (fail-closed)."""
    from codex_harness.research.adapters.research import ResearchSources
    return ResearchSources(artifacts, pressure=pressure)


def git_capture(repository):
    from codex_harness.composition import research_program_adapters
    return research_program_adapters.git_capture(repository)


def program_runner(*args, **kwargs):
    """`ProgramRunner(service, programs, sources, git_source, capture, budget, artifacts, runtime, council=, github_detail=, repository=)` with the dge `verify_sources` wired (R-q3b)."""
    from codex_harness.composition import research_program_adapters
    return research_program_adapters.program_runner(*args, **kwargs)


def pressure_evaluator(store, observer):
    """INV-DISCOVERY-PRESSURE-001: the evaluator over THIS process's store, with the host ledger and the census reader (R-dp2)."""
    from codex_harness.composition import research_program_adapters
    return research_program_adapters.discovery_pressure(store, observer)


def recovery_evidence():
    """The execution evidence reader over the executor's own artifact store (M7 `ExecutionEvidence(FileArtifacts(runtime_dir() / "artifacts"))`)."""
    from codex_harness.composition import cli_research
    return cli_research.execution_evidence()


def transport_probe(run_id):
    """The read-only probe of the CONFIGURED bus; a run-scoped council published under its own namespace is probed through
    `RedisBus.for_run` when the failed attempt names its run (a malformed request refuses in the owner)."""
    from codex_harness.composition import cli_bus, redis_url
    from codex_harness.composition.configuration import settings
    from codex_harness.research.adapters.research_program import TransportProbe
    from codex_harness.storage.adapters.redis_bus import RedisBus
    scoped = (RedisBus.for_run(redis_url(), run_id, settings().get("HARNESS_REDIS_NAMESPACE", "codex-harness"))
              if isinstance(run_id, str) and run_id else None)
    return TransportProbe(cli_bus.bus(), scoped=scoped)
