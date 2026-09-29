"""Deterministic clock and id sources for reference drivers (REBUILD-DESIGN-v2 §5.2 R-D).

Layer: harness (never shipped)

The reference files stay untouched: the driver process replaces `datetime.datetime` and
`uuid.uuid4` in the stdlib modules (so later lazy imports bind the fakes) and rebinds the same
names inside every already-loaded module under the given prefixes. `time.monotonic` follows the same
fake clock, so M7's wall/monotonic continuity checks hold. The clock advances only when a scenario
step calls `advance`. Pids and OS temporary names are not injected; they are maskable.
"""

from __future__ import annotations

import datetime as _dt
import sys
import time as _time
import uuid as _uuid

ORIGINAL_DATETIME = _dt.datetime
ORIGINAL_UUID4 = _uuid.uuid4
ORIGINAL_MONOTONIC = _time.monotonic
EPOCH = ORIGINAL_DATETIME(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)


class FakeClock:
    def __init__(self, start: _dt.datetime = EPOCH):
        self.start = start
        self.current = start

    def reset(self) -> None:
        self.current = self.start

    def now(self, tz=None):
        value = self.current
        if tz is None:
            return ORIGINAL_DATETIME(*value.utctimetuple()[:6], value.microsecond)
        return value.astimezone(tz)

    def advance(self, seconds: float) -> None:
        self.current = self.current + _dt.timedelta(seconds=seconds)

    def monotonic(self) -> float:
        return 1000.0 + (self.current - self.start).total_seconds()


class FakeIds:
    def __init__(self, start: int = 1):
        self.start = start
        self.counter = start

    def reset(self) -> None:
        self.counter = self.start

    def uuid4(self):
        value = _uuid.UUID(int=(0x5EED << 112) | self.counter, version=4)
        self.counter += 1
        return value


def install(clock: FakeClock, ids: FakeIds, prefixes=("codex_harness",), constants=None):
    """`constants` maps a loaded module name to {attribute: value} for import-time identities
    (e.g. M7 `application.execution_time.DOMAIN`), set in the driver process only."""
    class FakeDateTime(ORIGINAL_DATETIME):
        @classmethod
        def now(cls, tz=None):
            v = clock.now(tz)
            return cls(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond,
                       tzinfo=v.tzinfo)

        @classmethod
        def utcnow(cls):
            return cls.now(None)

    _dt.datetime = FakeDateTime
    _time.monotonic = clock.monotonic
    _uuid.uuid4 = ids.uuid4
    for module_name, values in (constants or {}).items():
        for attr, value in values.items():
            setattr(sys.modules[module_name], attr, value)
    for name, module in list(sys.modules.items()):
        if module is None or not any(name == p or name.startswith(p + ".") for p in prefixes):
            continue
        for attr, value in list(vars(module).items()):
            if value is ORIGINAL_DATETIME:
                setattr(module, attr, FakeDateTime)
            elif value is ORIGINAL_UUID4:
                setattr(module, attr, ids.uuid4)
            elif value is ORIGINAL_MONOTONIC:
                setattr(module, attr, clock.monotonic)
    return FakeDateTime
