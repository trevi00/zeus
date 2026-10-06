"""S10 GAP #6 (OWNER-DECISIONS-S10 #6): the RunTask closure seam, fixture proof only.

- **R-g6.** `IsolatedWorker.summary()` / `.review_context(cwd, profile)` are RunTask's isolation collaborator; they
  equal the module functions M7's Executor called with `isolation.config`. No docker runs: the host is the fixture
  `ContainerHost` of the ported suites, and RunTask's read-only path stubs BOTH transports (the unexpected one raises).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_containers import host, iw  # noqa: E402
from test_s4_run_task import ClaudeRefused, answer_for, build, submit, task_row  # noqa: E402

from codex_harness.execution.adapters.containers import launcher, owned_container  # noqa: E402
from codex_harness.execution.adapters.transports import Transports  # noqa: E402
from codex_harness.execution.domain import container_spec  # noqa: E402

IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "secrets" / "codex-product"
    root.mkdir(parents=True)
    root.chmod(0o700)
    auth = root / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": None, "auth_mode": "chatgpt",
                                "tokens": {"id_token": "idt-DUMMY", "access_token": "at-DUMMY-NOT-A-TOKEN",
                                           "refresh_token": "rt-DUMMY-NOT-A-TOKEN", "account_id": "acct-dummy-0001"},
                                "last_refresh": "2026-09-29T00:00:00Z"}), encoding="utf-8")
    auth.chmod(0o600)
    return iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                              "ZEUS_CODEX_CREDENTIAL_STORE": str(root)})


def worker(config, tmp_path):
    return launcher.IsolatedWorker(config, tmp_path, host=host())


def test_g6_isolated_worker_summary_and_review_context_equal_the_module_functions(config, tmp_path):
    isolated = worker(config, tmp_path)
    assert isolated.summary() == container_spec.summary(config)
    assert len(isolated.summary()) == 7
    assert isolated.review_context(tmp_path, None) == owned_container.isolated_review_context(tmp_path, config, None)
    assert isolated.review_context(tmp_path) == owned_container.isolated_review_context(tmp_path, config)
    assert (isolated.review_context(tmp_path, "codex-role-ro")
            == owned_container.isolated_review_context(tmp_path, config, "codex-role-ro"))
    assert isolated.review_context(tmp_path, "codex-role-ro")["cwd"] == container_spec.WORKSPACE


def test_g6_run_task_read_only_review_reaches_the_isolation_collaborator(config, tmp_path):
    run_task, workflow, store_, _, _ = build(tmp_path)
    isolated = worker(config, tmp_path)
    opened = []

    class Fixture:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def run(self, prompt, cwd, schema, *a, **kw):
            event = {"method": "item/completed", "params": {"item": {"id": "c1", "type": "command"}}}
            kw["on_event"](event)
            return {"events": [event], "thread_id": "th", "turn_id": "tu", "usage": {"totalTokens": 1},
                    "rotate": False, "interrupted": False, "answer": answer_for(schema)}

    def codex_runtime(*, profile, **kwargs):
        opened.append(profile)
        return Fixture()

    def unexpected(*args, **kwargs):
        raise AssertionError("the Claude role transport was reached")

    reviewed = []
    real_review = isolated.review_context
    isolated.review_context = lambda cwd, profile=None: reviewed.append(profile) or real_review(cwd, profile)
    isolated.codex_runtime, isolated.runtime = codex_runtime, unexpected
    run_task.isolation = isolated
    run_task.transports = Transports(isolation=isolated, host_app_server=unexpected, host_hooks=lambda: {},
                                     claude_runtime=ClaudeRefused)
    submit(workflow)
    out = run_task.execute_one("lead:improvement")
    assert out["status"] == "succeeded", out
    assert reviewed == ["codex-role-ro"] and opened == ["codex-role-ro"]
    assert task_row(store_)["result"]["execution_ref"]
