"""Real broken-CLI image plus an isolated promotion-gate fixture. Never deploys it."""
import copy
import json
import re
import tempfile
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.releases import Releases
from codex_harness.application.service import Harness
from codex_harness.bootstrap import build_executor
from codex_harness.domain.model import ContractError, canonical


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
        runner = ReleaseRunner(executor.service, executor.git, executor.artifacts,
                               str(Path.home() / ".codex/auth.json"))
        check = runner.file_canary(bad)
        assert check["passed"] is False
        gate = Releases(MemoryStore(), executor.service.org)
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
        isolated = Harness(MemoryStore(), executor.service.org)
        with isolated.store.transaction() as tx:
            tx.put("deployment", "active", {"release_id": "broken-fixture",
                                             "previous": {"release_id": "good-fixture"}})
            tx.put("images", "broken-fixture", {"image": bad})
            tx.put("releases", "broken-fixture", {"id": "broken-fixture", "status": "active"})
        recovered = ReleaseRunner(isolated, executor.git, executor.artifacts,
                                  str(Path.home() / ".codex/auth.json")).monitor()
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
