"""The `zeus` CLI composition: the executor-root builders (S10 unit C5d, R-c21).

Layer: composition
Owns: executor, release_runner, artifact_maintenance
Does not own: any root's argument shape or body (entry.cli), the executor wiring (composition.operation.build_executor) and the
bus and message builders (composition.cli_bus, composition.cli)
Entry points: executor, release_runner, artifact_maintenance
Contracts: none

Replaces `build_executor(service[, observer=])`, `ReleaseRunner(service, executor.git, executor.artifacts, str(codex_auth()))` and
`ArtifactMaintenance(service.store, executor.artifacts)` of M7 `cli.py` (SOURCE e38aa722:742-746, 779-783, 839-873).
`release_runner` is `composition.release_verification.release_runner` with the carries wired as `tests/ported/m7_delivery.ReleaseRunner`
wires them for a unit suite, except that the production collaborators replace the labelled refusals: `runner` is `process_groups.run_process`,
`release_suite` the `ReleaseSuite` with the production injections (V19 R-rs1), `verification_services` the `VerificationServices` class,
`hooks` the `HookCandidates` of `tests/ported/m7_executor.NativeHooks` and `request_rebase` the `MessageHandler.request_rebase` that M7's
`Workflow.request_rebase` became (S5, `composition.cli.messages`). `artifact_maintenance` is `tests/ported/m7_research.ArtifactMaintenance`.
Imports sit inside the functions, so importing this module stays light.
"""


def executor(service, observer=None):
    from codex_harness.composition.operation import build_executor
    return build_executor(service, observer=observer)


def release_runner(service, executor):
    import sys

    from codex_harness.composition import cli
    from codex_harness.composition.configuration import codex_auth
    from codex_harness.composition.release_verification import release_runner as runner_for
    from codex_harness.execution.adapters.providers.native_hooks import HookCandidates, HostHooks
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.host_os.adapters.verification import VerificationServices
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.observation.domain.observation import redact_text, redact_value
    from codex_harness.research.domain.recurrence import hook_apply
    from codex_harness.review.adapters.release_suite import ReleaseSuite

    def release_suite(artifacts, fence):
        return ReleaseSuite(artifacts, fence, run_logged_process=process_groups.run_logged_process, redact=redact_text,
                            redact_value=redact_value)

    def hooks(service, git, artifacts):
        units = cli.hook_units(service)
        show = lambda spec, strip=True: git._git("show", spec, strip=strip)  # noqa: E731 - read at call time
        return HookCandidates(units, service.store, show, HostHooks(units, show, artifacts, sys.executable),
                              validate=hook_apply, runner=process_groups.run_process,
                              channel_environment=process_groups.python_channel_environment, interpreter=sys.executable)

    return runner_for(service, executor.git, executor.artifacts, str(codex_auth()), runner=process_groups.run_process,
                      release_suite=release_suite, verification_services=VerificationServices, hooks=hooks,
                      request_rebase=cli.messages(service).request_rebase, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def artifact_maintenance(service, artifacts):
    from codex_harness.coordination.application.events import EventJournal
    from codex_harness.kernel.ids import SYSTEM_CLOCK
    from codex_harness.storage.adapters.maintenance import ArtifactMaintenance
    return ArtifactMaintenance(service.store, artifacts, EventJournal(), clock=SYSTEM_CLOCK)
