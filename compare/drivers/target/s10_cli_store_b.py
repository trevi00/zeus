"""Target driver: `entry.cli_store_b.pg` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2b).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable
PostgreSQL (see compare/drivers/common/s10_cli_store_b.py); tasks are seeded through the target's own composed Workflow.
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

driver.start("target")

import s10_cli_store_b  # noqa: E402
from codex_harness.composition import build  # noqa: E402
from codex_harness.composition.cli import artifacts, workflow  # noqa: E402
from codex_harness.composition.configuration import runtime_dir  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402


def seed_exhausted(message):
    service = build()
    flow = workflow(service)
    task = flow.submit(message)
    lease = flow.claim("lead:improvement", "owner", max_attempts=1)
    flow.fail(lease, "Actual failure API input")
    assert flow.claim("lead:improvement", "after-failure") is None  # the claim finds the budget exhausted (M7 test_execution_recovery.exhausted)
    with service.store.transaction() as tx:
        return tx.get("tasks", task["id"])


def put_evidence(text):
    return artifacts(runtime_dir() / "artifacts").put(text, "unit-test")["ref"]


def put_artifact(directory, text):
    return artifacts(directory).put(text, "fixture")["ref"]


def plant_history(seeds):
    service = build()
    with service.store.transaction() as tx:
        tx.put("reference_audits", "legacy", {"status": "inventoried_not_reviewed"})
        for i, seed in enumerate(seeds):
            tx.put("reference_audits", str(i), seed)


@contextlib.contextmanager
def packaged_backlog(seeds):
    resource = SimpleNamespace(joinpath=lambda _: SimpleNamespace(read_text=lambda: json.dumps(seeds)))
    with mock.patch("codex_harness.research.application.research.files", lambda _: resource):
        yield


API = SimpleNamespace(main=main, seed_exhausted=seed_exhausted, put_evidence=put_evidence, put_artifact=put_artifact,
                      plant_history=plant_history, packaged_backlog=packaged_backlog)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s10-c2b-") as raw:
        result = s10_cli_store_b.run_all(API, Path(raw).resolve(), os.environ["ZEUS_REBUILD_PG_DSN"])
    driver.finish("target", "entry.cli_store_b.pg", result)
