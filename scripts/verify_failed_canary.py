"""Real broken-CLI image plus an isolated promotion-gate fixture. Never deploys it."""
import copy
import json
import re
import tempfile
from pathlib import Path

from codex_harness.composition import ServiceHandle
from codex_harness.composition.cli_executor import release_runner
from codex_harness.composition.operation import build_executor
from codex_harness.coordination.application.events import EventJournal
from codex_harness.host_os.adapters.process_groups import run_process
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, canonical
from codex_harness.research.application.hook_rollback import HookRollback
from codex_harness.review.application.releases import Releases
from codex_harness.storage.adapters.memory_store import MemoryStore


def main():
    executor = build_executor()
    with executor.service.store.transaction() as tx:
        active = tx.get("deployment", "active")
        image = tx.get("images", active["release_id"])["image"]
    assert re.fullmatch(r"[a-zA-Z0-9:._/-]+", image)
    bad = "codex-harness:canary-broken-cli"
    with tempfile.TemporaryDirectory(prefix="harness-negative-canary-") as directory:
        # A local tag avoids registry resolution of a bare content digest in FROM.
        tagged = run_process(["docker", "tag", image, "codex-harness:canary-parent"])
        assert tagged.returncode == 0
        Path(directory, "Dockerfile").write_text("FROM codex-harness:canary-parent\n"
                                                 "RUN mv /usr/local/bin/codex /usr/local/bin/codex.disabled\n")
        built = run_process(["docker", "build", "-t", bad, directory], timeout=120)
        assert built.returncode == 0, built.stderr
    try:
        # S11 R-S3: ReleaseRunner(service, git, artifacts, auth) is composition.cli_executor.release_runner(service, executor)
        # (OWNER-DECISIONS-S10 #12): its releases, ticket binding, runner, release suite, verification services, hooks and
        # rebase request are wired there. The auth file is the composition's `codex_auth()`, which is `~/.codex/auth.json`
        # unless HARNESS_CODEX_AUTH or CODEX_HOME names another.
        runner = release_runner(executor.service, executor)
        check = runner.file_canary(bad)
        assert check["passed"] is False
        # S11 R-S3: Releases needs its ports (the keyword ticket_binding among them), wired as composition wires them
        # (composition.release_verification.release_runner: ticket binding, TicketSuperseded, event journal, hook rollback,
        # system clock and ids); the store and the organization are M7's.
        gate = Releases(MemoryStore(), executor.service.org, ticket_binding=tickets.ticket_binding,
                        ticket_superseded=tickets.TicketSuperseded, events=EventJournal(), hooks=HookRollback(),
                        clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        fixture = gate.propose({"revision": "fixture", "base": "fixture-base", "tree": "fixture-tree",
                                "author": "worker:implementation"}, {"checks": ["cli_file_task"]})
        for actor in ("lead:improvement", "conductor"):
            gate.review(fixture["id"], actor, "fixture", True, "fixture:scripted-approval-not-live-review")
        gate.verify(fixture["id"], "fixture", fixture["policy_hash"], {"cli_file_task": check})
        rejected = False
        try:
            gate.promote(fixture["id"], None)
        except ContractError:
            rejected = True
        assert rejected
        # Fault injection is isolated from the production database. The external
        # controller must recover even though the injected image cannot run Codex.
        # S11 R-S3: Harness(store, org) has no target class; the holder of a store and an organization is ServiceHandle
        # (OWNER-DECISIONS-S10 #12).
        isolated = ServiceHandle(MemoryStore(), executor.service.org)
        with isolated.store.transaction() as tx:
            tx.put("deployment", "active", {"release_id": "broken-fixture",
                                             "previous": {"release_id": "good-fixture"}})
            tx.put("images", "broken-fixture", {"image": bad})
            tx.put("releases", "broken-fixture", {"id": "broken-fixture", "status": "active"})
        # S11 R-S3: the same composition factory, over the isolated service (see the first runner above).
        recovered = release_runner(isolated, executor).monitor()
        assert recovered["status"] == "rolled_back"
        assert recovered["active"]["release_id"] == "good-fixture"
        with executor.service.store.transaction() as tx:
            assert tx.get("deployment", "active") == active
        result = {"mode": "real broken image; isolated scripted approval fixture",
                  "live_canary_detected_failure": True, "promotion_gate_rejected": rejected,
                  "external_controller_rollback": True,
                  "active_deployment_unchanged": True, "canary": copy.deepcopy(check)}
        receipt = executor.artifacts.put(canonical(result), "verification:failed-canary")
        with executor.service.store.transaction() as tx:
            tx.put("verification", "failed-canary", {"id": "failed-canary", "evidence": receipt["ref"], **result})
        print(json.dumps(result))
    finally:
        run_process(["docker", "image", "rm", bad, "codex-harness:canary-parent"], timeout=30)


if __name__ == "__main__":
    main()
