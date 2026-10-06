"""Live bounded recursive-context canary using synthetic, explicitly labeled facts."""
import json
import tempfile

from codex_harness.adapters.app_server import AppServer
from codex_harness.application.rlm import RecursiveContext
from codex_harness.bootstrap import build_executor
from codex_harness.domain.model import canonical


def main():
    executor = build_executor()
    source = "Fixture fact A: alpha equals 17.\n".ljust(200) + "Fixture fact B: beta equals 25.\n"
    reference = executor.artifacts.put(source, "verification:synthetic-rlm-input")["ref"]
    with tempfile.TemporaryDirectory(prefix="harness-rlm-canary-") as cwd:
        with AppServer() as runtime:
            rlm = RecursiveContext(executor.artifacts, runtime, cwd, max_calls=3, chunk_size=200)
            result = rlm.analyze(reference, "Extract alpha and beta. When both are available, calculate "
                                 "their sum in decimal digits. Preserve individual known values in partial "
                                 "findings. Do not invent missing values or use tools.")
    assert rlm.calls == 3
    assert "42" in result["answer"]["finding"] and result["answer"]["sufficient"]
    receipt = executor.artifacts.put(canonical(result), "verification:live-rlm")
    record = {"id": "live-rlm", "mode": "real Codex calls; synthetic facts", "calls": rlm.calls,
              "passed": True, "evidence": receipt["ref"]}
    with executor.service.store.transaction() as tx:
        tx.put("verification", record["id"], record)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
