"""Reference driver: `entry.cli_store_b.pg` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2b).

M7 `codex_harness.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable
PostgreSQL (see compare/drivers/common/s10_cli_store_b.py); tasks are seeded through M7's own `Workflow`.
"""

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_cli_store_b  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.configuration import runtime_dir  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import build  # noqa: E402
from codex_harness.cli import main  # noqa: E402


def seed_exhausted(message):
    service = build()
    workflow = Workflow(service.store, service.org)
    task = workflow.submit(message)
    lease = workflow.claim("lead:improvement", "owner", max_attempts=1)
    workflow.fail(lease, "Actual failure API input")
    assert workflow.claim("lead:improvement", "after-failure") is None  # the claim finds the budget exhausted (M7 test_execution_recovery.exhausted)
    with service.store.transaction() as tx:
        return tx.get("tasks", task["id"])


def put_evidence(text):
    return FileArtifacts(runtime_dir() / "artifacts").put(text, "unit-test")["ref"]


def put_artifact(directory, text):
    return FileArtifacts(directory).put(text, "fixture")["ref"]


def plant_history(seeds):
    service = build()
    with service.store.transaction() as tx:
        tx.put("reference_audits", "legacy", {"status": "inventoried_not_reviewed"})
        for i, seed in enumerate(seeds):
            tx.put("reference_audits", str(i), seed)


@contextlib.contextmanager
def packaged_backlog(seeds):
    resource = SimpleNamespace(joinpath=lambda _: SimpleNamespace(read_text=lambda: json.dumps(seeds)))
    with mock.patch("codex_harness.application.research.files", lambda _: resource):
        yield


API = SimpleNamespace(main=main, seed_exhausted=seed_exhausted, put_evidence=put_evidence, put_artifact=put_artifact,
                      plant_history=plant_history, packaged_backlog=packaged_backlog)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s10-c2b-") as raw:
        result = s10_cli_store_b.run_all(API, Path(raw).resolve(), os.environ["ZEUS_REBUILD_PG_DSN"])
    driver.finish("reference", "entry.cli_store_b.pg", result)
