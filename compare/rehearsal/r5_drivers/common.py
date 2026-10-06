"""Shared plumbing of the R5 side drivers (`a.py`, `b.py`): arguments, the provider guard, the spawn audit, the fixture
provider transport and the result document. Layer: harness (never shipped). Imports no product code at module level
(each side imports its own tree after `bootstrap`).

Provenance: `schema_answer`/`FixtureTransport` follow the fixture of `compare/drivers/{reference,target}/s4_run_task.py`
(the S4 run-task goldens' success case: a schema-valid canned plan from a fake transport, the unexpected transport loud).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
COMPARE = HERE.parents[1]
DOMAIN = "00000000-0000-4000-8000-0000000005f5"  # the clock-domain identity both sides use (execution_time.DOMAIN)
FAULTS = ("codex_unstubbed", "claude_reached")


def parse(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="r5-side-driver")
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--run8", required=True)
    parser.add_argument("--src", required=True, help="the revision's package root (<rev>/src)")
    parser.add_argument("--scratch", required=True, help="the fixture workspace root (not diffed)")
    parser.add_argument("--artifacts", required=True, help="the artifacts overlay upper dir (diffed)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("seed", "run"), default="run")
    parser.add_argument("--fault", choices=FAULTS, default=None)
    parser.add_argument("--inject-extra", default=None, help="TEST ONLY: one extra store put on this side, bucket/key")
    parser.add_argument("--inject-readonly", action="store_true", help="TEST ONLY: one extra read-only unit in step fleet_resume")
    return parser.parse_args(argv)


def bootstrap(src: str) -> None:
    """Put the side's own tree first; the harness, the compare common modules and the guard follow."""
    sys.path[:0] = [str(Path(src).resolve()), str(COMPARE / "guard"), str(COMPARE / "harness"),
                    str(COMPARE / "drivers" / "common"), str(COMPARE / "rehearsal" / "r5_drivers")]
    import provider_guard

    provider_guard.install()
    if not provider_guard.installed():
        raise SystemExit("R-P: provider guard is not installed in this driver process")


class SpawnAudit:
    """Counts every process-creation audit event (`subprocess.Popen`, `os.exec*`, `os.posix_spawn`, `os.system`,
    `os.fork*`); the provider guard refuses provider spawns, this counts ANY attempt, refused or not."""

    EVENTS = frozenset({"subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn", "os.system", "os.fork", "os.forkpty"})

    def __init__(self):
        self.events: list[str] = []
        sys.addaudithook(self._hook)

    def _hook(self, event, args):
        if event in self.EVENTS:
            self.events.append(event)


def schema_answer(schema: dict, plan: dict) -> dict:
    answer = {}
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type")
        if name in plan:
            answer[name] = plan[name]
        elif kind == "array":
            answer[name] = []
        elif kind == "integer":
            answer[name] = 0
        elif kind == "boolean":
            answer[name] = False
        elif kind == "object":
            answer[name] = schema_answer(spec, plan)
        else:
            answer[name] = "fixture"
    return answer


def fixture_transport(plan: dict, calls: list, advance, contract_error, claude_hook=None):
    """The fixture provider transport: records one call, emits one command event, answers the canned plan."""

    class FixtureTransport:
        enters_on_open = True

        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, prompt, cwd, schema, *args, **kw):
            calls.append("task")
            if claude_hook is not None:
                claude_hook()  # the unexpected transport: constructing it raises (never a provider call)
            event = {"method": "item/completed", "params": {"item": {"id": "c" + str(len(calls)), "type": "command"}}}
            kw["on_event"](event)
            advance(1)
            return {"events": [event], "thread_id": "thread-rh", "turn_id": "turn-" + str(len(calls)),
                    "usage": {"totalTokens": 123}, "rotate": False, "interrupted": False,
                    "answer": schema_answer(schema, plan)}

    return FixtureTransport


class ClaudeRefused:
    """The unexpected transport: constructing it is a driver failure, never a provider call."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("ClaudeCodeRuntime reached in the R5 fixture")


class _ReadProxy:
    def __init__(self, tx, recorder):
        self._tx, self._recorder = tx, recorder

    def _read(self, bucket, key):
        unit = self._recorder._stack[-1]["unit"] if self._recorder._stack else None
        self._recorder._event("read", unit=unit, bucket=bucket, key=str(key))

    def get(self, bucket, key):
        self._read(bucket, key)
        return self._tx.get(bucket, key)

    def scan(self, bucket):
        self._read(bucket, "*")
        return self._tx.scan(bucket)

    def records(self):
        self._read("*", "*")
        return self._tx.records()

    def entries(self, bucket, *args, **kwargs):
        self._read(bucket, "*")
        return self._tx.entries(bucket, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._tx, name)


class ReadLoggingStore:
    """R5-wrapper-only read logging (`compare/harness/recorder.py` is untouched): each `get`/`scan`/`records`/`entries` of a
    unit is logged as a `read` event of the recorder, so a read-only unit's reads can be named."""

    def __init__(self, store):
        self._store = store

    def transaction(self, *args, **kwargs):
        from contextlib import contextmanager

        @contextmanager
        def unit():
            with self._store.transaction(*args, **kwargs) as tx:
                yield _ReadProxy(tx, self._store.recorder)

        return unit()

    def __getattr__(self, name):
        return getattr(self._store, name)


def tap_observer(observer) -> list:
    """Record `(event, outcome)` of every `emit` (the spool sequence counts these appends); returns the live list."""
    seen: list = []
    inner = observer.emit

    def emit(event, outcome, *args, **kwargs):
        seen.append([event, outcome])
        return inner(event, outcome, *args, **kwargs)

    observer.emit = emit
    return seen


def write_result(path: str, side: str, origin: dict, scenario: dict, recorder, audit: SpawnAudit, extra: dict) -> None:
    document = {"side": side, "origin": origin, "profile": "harness-fixture (ZEUS_COMPOSITION_PROFILE not set)",
                "production_profile_set": os.environ.get("ZEUS_COMPOSITION_PROFILE") == "production",
                "spawn_events": audit.events, "recorder_violations": recorder.violations(), **scenario, **extra}
    Path(path).write_text(json.dumps(document, sort_keys=True, ensure_ascii=False, indent=1), encoding="utf-8")


def api_namespace(**fields) -> SimpleNamespace:
    return SimpleNamespace(**fields)
