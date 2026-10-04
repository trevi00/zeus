"""The `zeus continuation conduct` composition: the lane-side executor, its call budget and its worker-session owner.

Layer: composition
Owns: lane_executor
Does not own: the argument shape and the command bodies (entry.cli.continuation), the policy, lane and process wiring (composition.continuation) and the executor builder (composition.operation)
Entry points: lane_executor
Contracts: INV-CONTINUATION-001, INV-PROJECT-EVIDENCE-001, INV-ISOLATED-WORKER-001, INV-WORKER-SESSION-001

Moved from M7 `adapters/continuation_cli.py` `_lane_executor` (:117-132, SOURCE e38aa722) by named rule R-c27 (S10 unit C8b-1): the body is M7's with the target homes: `settings` is `composition.configuration.settings`,
`load_profile(host)` is `composition.operation.host_evidence_profile()` (it reads the same settings), `host_isolation` and `build_executor` are `composition.operation`, `build_observer` is `composition.observation`,
`execution_policy` and `session_owner` are C6a's `composition.cli_operation` and `CallBudget()` is its `call_budget` builder. An absent `ZEUS_COMPOSITION_PROFILE` refuses in `build_executor`
(`composition_profile_unknown`, OWNER-DECISIONS-S10 #10). Imports sit inside the function, so importing this module stays light.
"""


def lane_executor(service, manifest, binding):
    from codex_harness.composition.cli_operation import call_budget, execution_policy, session_owner
    from codex_harness.composition.configuration import settings
    from codex_harness.composition.observation import build_observer
    from codex_harness.composition.operation import build_executor, host_evidence_profile, host_isolation

    host = settings()
    profile = host_evidence_profile()
    isolated = host_isolation(profile)
    observer = build_observer(service.store, "cli.continuation")
    owner = session_owner(service, manifest["id"], observer)
    executor = build_executor(service, observer=observer, execution_policy=execution_policy(manifest, host),
                              knowledge=False, evidence_profile=profile,
                              **({} if isolated is None else {"isolation": isolated}), **owner)
    return executor, call_budget(), owner.get("worker_sessions")
