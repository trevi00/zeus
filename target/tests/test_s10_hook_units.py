"""S10 GAP #5: HookUnits opens one store unit per call (OWNER-DECISIONS-S10 #5)."""
import ast
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_coordination import Harness, organization  # noqa: E402

from codex_harness.composition.hook_units import HookUnits
from codex_harness.execution.adapters.providers.native_hooks import HookCandidates, HostHooks
from codex_harness.host_os.adapters import process_groups
from codex_harness.kernel.message import envelope
from codex_harness.research.domain.recurrence import hook_apply
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

# m7_intake is read as text: importing it needs the ported suite's conftest (ATTESTED), which is not loaded here.
_FIXTURE = Path(__file__).resolve().parent / "ported" / "m7_intake.py"
HOOK_UNITS = next(ast.literal_eval(node.value) for node in ast.parse(_FIXTURE.read_text("utf-8")).body
                  if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "HOOK_UNITS")

CALLS = {
    "review": (("h1", "lead:x", "rev", "hash", True, "ev"), {}),
    "get_hook": (("h1",), {}),
    "propose": (("h1", "worker:x", {"a": 1}, "rev"), {}),
    "record_canary": (("h1", "rev", "hash", {"reproduction": True}), {}),
    "activate": (("h1",), {}),
    "rollback": (("h1", "why"), {}),
    "prepare_command": ((["cmd"], "linux"), {}),
    "active_hooks": ((), {}),
}


class CountingStore:
    def __init__(self, store):
        self.store, self.entered = store, []

    @contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            self.entered.append(tx)
            yield tx


class RecordingLifecycle:
    def __init__(self, store):
        self.store, self.calls = store, []

    def __getattr__(self, name):
        def method(*args, transaction, **kwargs):
            self.calls.append((name, args, transaction, len(self.store.entered)))
            return name
        return method


@pytest.mark.parametrize("name", HOOK_UNITS)
def test_each_method_runs_in_one_unit_and_passes_that_transaction(name):
    store = CountingStore(MemoryStore())
    lifecycle = RecordingLifecycle(store)
    args, kwargs = CALLS[name]
    assert getattr(HookUnits(lifecycle, store), name)(*args, **kwargs) == name
    assert len(store.entered) == 1
    (called, got_args, transaction, entered_during), = lifecycle.calls
    assert called == name and got_args == args
    assert transaction is store.entered[0] and entered_during == 1


def test_public_methods_equal_the_fixture_units():
    public = {n for n in vars(HookUnits) if not n.startswith("_")}
    assert public == set(HOOK_UNITS) and set(CALLS) == public


ROOT = Path(__file__).resolve().parents[2]
HOOK_ID = "hook-ab97ba09554daa5aec289867"


def test_hook_candidates_over_hook_units_end_to_end(tmp_path):
    service = Harness(MemoryStore(), organization())
    for occurrence in ("review-one", "review-two"):
        service.record_incident(envelope(
            "incident.report", "lead:improvement", "conductor", "record_incident",
            {"occurrence_id": occurrence, "root_cause": "codex-bubblewrap-namespace-creation-denied",
             "scope": "docker/linux/codex-read-only-review", "evidence_refs": ["fixture:confirmed-diagnosis"]},
            "fixture"))

    def show(spec, strip=True):
        text = (ROOT / spec.split(":", 1)[1]).read_text()
        return text.strip() if strip else text

    units = HookUnits(service.hooks, service.store)
    host = HostHooks(units, show, FileArtifacts(str(tmp_path)), sys.executable)
    candidates = HookCandidates(units, service.store, show, host, validate=hook_apply,
                                runner=process_groups.run_process,
                                channel_environment=process_groups.python_channel_environment,
                                interpreter=sys.executable)
    spec = candidates.candidate(HOOK_ID, {"revision": "fixture-revision", "author": "worker:implementation"})
    assert spec["kind"] == "native_hook"
    checks = candidates.canary(HOOK_ID)
    assert all(check["passed"] for check in checks.values()), checks
    with service.store.transaction() as tx:
        assert tx.get("hooks", HOOK_ID)["status"] == "candidate"
        assert tx.get("hook_cases", HOOK_ID)["revision"] == "fixture-revision"
