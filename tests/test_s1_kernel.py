"""S1 kernel: injected clock/id ports, the canonical/digest identity, the six-W envelope and the
single policy definition (REBUILD-DESIGN-v2 §2.3 kernel, §5.2 R-D). The byte-level parity with
SOURCE M7 is the `kernel.values` differential scenario; these are the target-only properties."""

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_harness.kernel import errors, ids, message, policy, ports, usage

KERNEL = Path(ids.__file__).resolve().parent


class FixedClock:
    def __init__(self):
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self):
        return self.value


class CountingIds:
    def __init__(self):
        self.n = 0

    def uuid4(self):
        self.n += 1
        return uuid.UUID(int=self.n, version=4)


def test_system_ports_are_aware_utc_and_random():
    now = ids.SYSTEM_CLOCK.now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    assert ids.SYSTEM_IDS.uuid4() != ids.SYSTEM_IDS.uuid4()
    clock: ports.Clock = ids.SYSTEM_CLOCK  # structural: the Protocol names exactly this method
    source: ports.IdSource = ids.SYSTEM_IDS
    assert callable(clock.now) and callable(source.uuid4)


def test_utcnow_uses_the_injected_clock_and_keeps_the_record_format():
    clock = FixedClock()
    assert ids.utcnow(clock) == "2026-01-01T00:00:00+00:00"
    clock.value = datetime(2026, 1, 1, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    assert ids.utcnow(clock) == "2026-01-01T00:00:00+00:00", "any aware time is recorded in UTC"


def test_envelope_identity_comes_only_from_the_ports():
    clock, source = FixedClock(), CountingIds()
    first = message.envelope("task.assign", "lead:x", "worker:y", "act", {"evidence_refs": ["r"]}, "c",
                             clock=clock, ids=source)
    again = message.envelope("task.assign", "lead:x", "worker:y", "act", {"evidence_refs": ["r"]}, "c",
                             clock=clock, ids=CountingIds())
    assert first == again and first["message_id"] == str(uuid.UUID(int=1, version=4))
    assert first["when"]["created_at"] == "2026-01-01T00:00:00+00:00"
    assert first["why"]["evidence_refs"] == ["r"] and first["who"]["owner"] == "worker:y"
    assert set(first) == set(message.SixWMessage.__annotations__)


def test_canonical_and_digest_are_the_persisted_identity():
    assert ids.canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
    assert ids.digest({}) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"


def test_errors_and_require():
    assert issubclass(errors.ContractError, ValueError)
    try:
        errors.require(False, "reason")
    except errors.ContractError as exc:
        assert str(exc) == "reason"
    assert issubclass(usage.UsagePolicyError, errors.ContractError)


def test_policy_is_defined_once_and_frozen():
    assert policy.POLICY.task_seconds == 3600 and policy.POLICY.decision_seconds == 900
    try:
        policy.POLICY.task_seconds = 1
    except AttributeError:
        pass
    else:
        raise AssertionError("RuntimePolicy must stay frozen")


def test_kernel_imports_only_the_standard_library_and_itself():
    for path in KERNEL.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] in {"__future__", "codex_harness", *__import__("sys").stdlib_module_names}
                if node.module.startswith("codex_harness"):
                    assert node.module.startswith("codex_harness.kernel"), (path.name, node.module)
