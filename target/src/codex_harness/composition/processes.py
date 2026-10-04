"""The container host facilities: docker/git runner, child processes, attached-client trees and worker profiles.

Layer: composition
Owns: container_host
Does not own: the host facilities' shape (execution.adapters.containers.launcher.ContainerHost), the process chokepoint (host_os.adapters.process_groups), the attached-client tree (host_os.adapters.process_tree) and the worker-profile documents (context.adapters.worker_profile)
Entry points: container_host
Contracts: INV-ROLE-CONTAINER-001, INV-WORKER-PROFILE-001

Binds `ContainerHost` by rule R-c15 (S10 unit C5c-1) to what M7's `adapters/isolated_worker` and `adapters/role_containers` reached through module globals: the host_os chokepoint runner, its child processes, `ProcessTree`, and the worker-profile module. `worker_profiles` is the module, as M7 imported `hook_receipts`, `load_profile` and `profile_digest` unconditionally (isolated_worker.py:34); the launcher reads it only when a runtime configures a worker profile (launcher.py:179, as M7 isolated_worker.py:779).
"""


def container_host():
    """A `ContainerHost` over the host_os chokepoint and the worker-profile module."""
    from codex_harness.context.adapters import worker_profile
    from codex_harness.execution.adapters.containers.launcher import ContainerHost
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.host_os.adapters.process_tree import ProcessTree
    return ContainerHost(runner=process_groups.run_process, processes=process_groups.ChokepointProcesses(),
                         trees=ProcessTree, worker_profiles=worker_profile)
