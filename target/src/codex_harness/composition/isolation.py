"""The IsolatedWorker composition: preflight, the container host, the credential boundary and the Codex broker factory.

Layer: composition
Owns: credential_boundary, isolated_worker
Does not own: the preflight refusals (execution.adapters.containers.owned_container), the worker and its host facilities (execution.adapters.containers.launcher), the container host binding (composition.processes), the scrubber (credentials.adapters.scrubber) and the Codex broker (credentials.adapters.codex_custody)
Entry points: credential_boundary, isolated_worker
Contracts: INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001

M7 `bootstrap.host_isolation` (lines 95-96) over the target, by rule R-c15 (S10 unit C5c-1): `preflight(config)` then `IsolatedWorker(config, runtime_dir() / "isolated-worker")`, with the host, the broker factory and the credential boundary the target takes explicitly. Nothing else is constructed: the broker class is the factory, and no provider, container or broker instance exists until a run asks for one.
"""


def credential_boundary():
    """A `CredentialBoundary` over the credential scrubber and its unsanitizable-output refusal."""
    from codex_harness.credentials.adapters import scrubber
    from codex_harness.execution.adapters.containers.launcher import CredentialBoundary
    return CredentialBoundary(scrubber=scrubber.CredentialScrubber, OutputUnsanitizable=scrubber.OutputUnsanitizable)


def isolated_worker(config, *, environment=None):
    """Refuse before any provider entry (daemon, image, token), then build the worker under `runtime_dir()/isolated-worker`."""
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.composition.processes import container_host
    from codex_harness.credentials.adapters.codex_custody import CodexCredentialBroker
    from codex_harness.execution.adapters.containers.launcher import IsolatedWorker
    from codex_harness.execution.adapters.containers.owned_container import preflight
    from codex_harness.host_os.adapters import process_groups
    preflight(config, environment=environment, runner=process_groups.run_process)
    return IsolatedWorker(config, runtime_dir() / "isolated-worker", host=container_host(),
                          broker_factory=CodexCredentialBroker, credentials=credential_boundary())
