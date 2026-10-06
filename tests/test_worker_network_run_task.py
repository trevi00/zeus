"""CUT-INT WN-1 round-1 F1: where the launch-time network/guard refusals sit relative to the invocation reservation.

SYNTHETIC integrated proof (no provider, credential or real docker): a leased run goes through the real
`RunTask.execute_one` with the real `Transports` and `IsolatedWorker` under the production isolation selection, over
an injected docker/systemctl runner shaped from observed-shapes.json. The launch refusals run at runtime entry, which
`run_task` reaches AFTER reserving the invocation, so each closes the reservation `unsettled_unknown` (usage unknown)
and its unconfirmed marker `not_entered`. The pre-existing `worker_image_unavailable` refusal is the control: the new
refusals must book exactly the same. Healthy control: the reservation exists before the first `docker create`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_s4_run_task import PLAN, answer_for, build, hooks, inspected, reservations, submit
from test_worker_network_binding import OBSERVED, PRODUCTION, Fake, _network, config

from codex_harness.execution.adapters.containers import launcher
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import UNKNOWN_USAGE
from codex_harness.execution.domain import container_spec as spec
from codex_harness.observation.application.observations import TERMINATION_BUCKET
from codex_harness.routing.adapters.provider_policy import host_policy

CASES = [("worker_image_unavailable", {}), ("worker_network_unavailable", {"network": ("\n", 1)}),
         ("worker_network_identity_mismatch", {"network": (json.dumps(_network(Options={})) + "\n", 0)}),
         ("worker_network_guard_unready", {"guard": (OBSERVED["systemctl_show_stdout"], 0)})]
# (recipient, action, details): a Codex role container run and a Claude role/worker container run.
PATHS = {"codex": ("lead:improvement", "plan"), "claude": ("worker:implementation", "implement")}


class Recording(Fake):
    def __init__(self, *args, image_ok=True, on_create=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_ok, self.on_create = image_ok, on_create

    def __call__(self, argv, *, timeout, env=None):
        if argv[1:3] == ["image", "inspect"] and not self.image_ok:
            self.calls.append(list(argv))
            return SimpleNamespace(returncode=1, stdout="", stderr="no such image")
        if len(argv) > 1 and argv[1] == "create":
            self.calls.append(list(argv))
            if self.on_create is not None:
                self.on_create()
            return SimpleNamespace(returncode=0, stdout="e" * 64 + "\n", stderr="")
        return super().__call__(argv, timeout=timeout, env=env)


def wired(tmp_path, runner, path):
    tmp_path.mkdir(parents=True)
    run_task, workflow, store, _, calls = build(tmp_path, evidence_gate=inspected([]), hook_candidates=hooks([]))
    body = {**config(PRODUCTION), "codex": {"credential_store": str(tmp_path / "store")}}
    host = SimpleNamespace(runner=runner, processes=None, trees=None, worker_profiles=None)
    worker = launcher.IsolatedWorker(body, tmp_path / "iso", host=host, broker_factory=lambda p: object(),
                                     credentials=object())
    run_task.isolation = worker
    run_task.transports = Transports(isolation=worker, hooks=None, claude_settings=lambda runtime: {},
                                     host_app_server=lambda **kw: pytest.fail("host App Server"),
                                     claude_runtime=lambda **kw: pytest.fail("host Claude"))
    recipient, action = PATHS[path]
    if path == "claude":  # the host enables Claude for worker:implementation/implement (a synthetic, fixed setting set)
        run_task.execution_policy = host_policy({"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                                                 "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"})
    submit(workflow, action, {"plan": dict(PLAN)},
           "lead:improvement" if recipient != "lead:improvement" else "conductor", recipient)
    return run_task, store, calls


def bookkeeping(store):
    with store.transaction() as tx:
        markers = [(row["status"], row.get("closure")) for row in tx.scan(TERMINATION_BUCKET)]
    return [(r["status"], r.get("reason", "").split(":")[0]) for r in reservations(store)], markers


@pytest.mark.parametrize("path", sorted(PATHS))
def test_every_launch_refusal_books_the_same_as_the_existing_image_refusal(tmp_path, path, monkeypatch):
    entries, provider_calls = [], []

    def wrap_enter(original):
        def enter(runtime):
            entries.append(type(runtime).__name__)
            return original(runtime)
        return enter

    def provider_entered(runtime, *args, **kwargs):
        provider_calls.append(type(runtime).__name__)
        raise AssertionError("provider entered")

    for runtime_class in (launcher.IsolatedClaudeRuntime, launcher.IsolatedCodexRuntime):
        monkeypatch.setattr(runtime_class, "__enter__", wrap_enter(runtime_class.__enter__))
        monkeypatch.setattr(runtime_class, "run", provider_entered)

    seen = {}
    for code, answers in CASES:
        entries.clear()
        provider_calls.clear()
        fake = Recording(image_ok=code != "worker_image_unavailable", **answers)
        run_task, store, _ = wired(tmp_path / code, fake, path)
        out = run_task.execute_one(PATHS[path][0])
        assert entries == [{"codex": "IsolatedCodexRuntime", "claude": "IsolatedClaudeRuntime"}[path]]
        assert provider_calls == []
        assert out["status"] in {"retry", "failed"} and code in (out.get("error") or ""), (code, out)
        rows = reservations(store)
        assert len(rows) == 1 and rows[0]["status"] == "unsettled_unknown"
        assert rows[0]["usage"] == UNKNOWN_USAGE  # the producer's own unknown-usage record (invocation_ledger.py:36)
        _, markers = bookkeeping(store)
        assert markers == [("closed", "not_entered")]
        assert "create" not in fake.verbs()
        seen[code] = (*bookkeeping(store)[0], tuple(sorted(rows[0]["usage"].items())), len(entries))
        verbs = {"worker_image_unavailable": ["version", "image"],
                 "worker_network_unavailable": ["version", "image", "network"],
                 "worker_network_identity_mismatch": ["version", "image", "network"],
                 "worker_network_guard_unready": ["version", "image", "network", "systemctl"]}[code]
        assert fake.verbs() == verbs
    assert len({tuple(v) for v in seen.values()}) == 1


@pytest.mark.parametrize("path", sorted(PATHS))
def test_healthy_launch_reserves_before_the_first_create_and_reaches_the_provider(tmp_path, path, monkeypatch):
    events, entered = [], []
    holder = {}
    fake = Recording(on_create=lambda: events.append([r["status"] for r in reservations(holder["store"])]))
    run_task, store, calls = wired(tmp_path / 'run', fake, path)
    holder["store"] = store

    def run(self, prompt, cwd, schema, *a, **kw):  # SYNTHETIC provider stub: no container, no credential
        created = self.host.runner(["docker", "create", "--network", self.config["network"]["worker"]], timeout=1, env={})
        assert created.returncode == 0
        entered.append(type(self).__name__)
        return {"events": [], "thread_id": "th", "turn_id": "tu", "usage": {"totalTokens": 1}, "rotate": False,
                "interrupted": False, "answer": answer_for(schema)}

    monkeypatch.setenv(spec.TOKEN_NAME, "synthetic-not-a-credential")
    monkeypatch.setattr(launcher.IsolatedCodexRuntime, "run", run)
    monkeypatch.setattr(launcher.IsolatedClaudeRuntime, "run", run)
    out = run_task.execute_one(PATHS[path][0])
    assert out["status"] == "succeeded", out.get("error")
    assert events == [["reserved"]]
    assert entered == [{"codex": "IsolatedCodexRuntime", "claude": "IsolatedClaudeRuntime"}[path]]
    assert fake.verbs()[:4] == ["version", "image", "network", "systemctl"]
