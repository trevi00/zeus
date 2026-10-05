"""Live bounded recursive-context canary using synthetic, explicitly labeled facts."""
import json
import tempfile

from codex_harness.composition.operation import build_executor
from codex_harness.context.application.rlm import RecursiveContext
from codex_harness.execution.adapters.providers.codex_app_server import AppServer
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.kernel.ids import canonical


def main():
    executor = build_executor()
    source = "Fixture fact A: alpha equals 17.\n".ljust(200) + "Fixture fact B: beta equals 25.\n"
    reference = executor.artifacts.put(source, "verification:synthetic-rlm-input")["ref"]
    with tempfile.TemporaryDirectory(prefix="harness-rlm-canary-") as cwd:
        # S11 R-S3: a host App Server refuses without an injected process creator; this is the creator
        # composition.operation._host_app_server injects, the spawn chokepoint (S3/S4; DESIGN-s11 §7 R-S3).
        with AppServer(processes=ChokepointProcesses()) as runtime:
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
