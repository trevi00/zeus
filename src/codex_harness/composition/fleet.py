"""The lane launcher and lane environment bindings: the isolation loader, the call budget and the spawn.

Layer: composition
Owns: lane_environment, lane_launcher, lane_popen
Does not own: the lane launcher, the lane environment and the receipt read (coordination.adapters.fleet_runtime), the isolation loader (execution.adapters.containers.owned_container), the call budget (execution.adapters.call_budget) and the spawn keyword policy (host_os.adapters.process_groups)
Entry points: lane_environment, lane_launcher, lane_popen
Contracts: INV-FLEET-001

Binds the three ports `coordination.adapters.fleet_runtime` takes by rule R-c16 (S10 unit C8a, GAP #3) to M7's own objects: `load_isolation` is `load_host_isolation` (M7 `isolated_worker.load_isolation`), `budget` defaults to `CallBudget()` as M7's `LaneLauncher.__init__` did (no argument: the machine ledger at its default home path), and `popen` is M7's `subprocess.Popen(..., **no_console_kwargs(process_group=True))`.
"""

def lane_popen(argv, **kwargs):
    """M7's lane spawn in its own process group, no console window: the target's single `subprocess.Popen` call site
    (`process_groups.popen`, which looks `subprocess.Popen` up at call time) with M7's `no_console_kwargs(process_group=True)`."""
    from codex_harness.host_os.adapters.process_groups import no_console_kwargs, popen
    return popen(argv, **kwargs, **no_console_kwargs(process_group=True))


def lane_environment(lane, host_settings, base=None):
    """M7 `lane_environment(lane, host_settings, base)`: the moved function with the host isolation loader bound."""
    from codex_harness.coordination.adapters import fleet_runtime
    from codex_harness.execution.adapters.containers.owned_container import load_host_isolation
    return fleet_runtime.lane_environment(lane, host_settings, base, load_isolation=load_host_isolation)


def lane_launcher(config, host_settings, **kwargs):
    """M7 `LaneLauncher(config, host_settings, **kwargs)`: isolation and spawn bound, `CallBudget()` unless a budget is passed."""
    from codex_harness.coordination.adapters.fleet_runtime import LaneLauncher
    from codex_harness.execution.adapters.call_budget import CallBudget
    from codex_harness.execution.adapters.containers.owned_container import load_host_isolation
    budget = kwargs.pop("budget", None)
    return LaneLauncher(config, host_settings, load_isolation=load_host_isolation,
                        budget=budget if budget is not None else CallBudget(), popen=lane_popen, **kwargs)
