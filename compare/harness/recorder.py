"""Transaction/fence/effect recorder for atomic-unit characterization (REBUILD-DESIGN-v2 §2.9).

Layer: harness (never shipped); standard library only, so it runs unchanged in the reference and
the target environment.

`RecordingStore` wraps any store exposing `transaction()` (M7 `MemoryStore`/`PostgresStore`, or a
target `storage.ports.Store`). The recorder logs BEGIN/COMMIT/ROLLBACK with a unit id, every write
inside a unit (bucket, key and a body digest; never the body), every fence check with its result,
and every external effect with the transaction depth at that moment.

Recorded violations (rule 5): a nested BEGIN inside an open unit, a write after a failed fence, a
write outside any unit, and an external effect at depth > 0. `classify` distinguishes an atomic
commit/rollback from a partial commit; `effect_protocol` distinguishes intent-before-effect from a
fabricated completion.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager


def body_digest(body) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Recorder:
    def __init__(self, normalize=None):
        """`normalize` applies the scenario's declared masks (harness/masks.py) before digesting."""
        self.normalize = normalize
        self.events: list[dict] = []
        self.violations: list[dict] = []
        self._stack: list[dict] = []
        self._next = 0

    @property
    def depth(self) -> int:
        return len(self._stack)

    def _event(self, kind: str, **fields) -> dict:
        event = {"seq": len(self.events), "kind": kind, **fields}
        self.events.append(event)
        return event

    def _violation(self, kind: str, event: dict) -> None:
        self.violations.append({"kind": kind, "seq": event["seq"]})

    def begin(self, label: str = "") -> dict:
        self._next += 1
        unit = {"unit": f"U{self._next}", "label": label, "fence_failed": False}
        event = self._event("BEGIN", unit=unit["unit"], depth=self.depth, label=label)
        if self._stack:
            self._violation("nested_begin", event)
        self._stack.append(unit)
        return unit

    def end(self, unit: dict, committed: bool, error: BaseException | None = None) -> None:
        if self._stack and self._stack[-1] is unit:
            self._stack.pop()
        if committed:
            event = self._event("COMMIT", unit=unit["unit"], depth=self.depth)
            if unit["fence_failed"]:
                self._violation("commit_after_failed_fence", event)
        else:
            self._event("ROLLBACK", unit=unit["unit"], depth=self.depth,
                        error=type(error).__name__ if error else None)

    def write(self, bucket: str, key: str, body) -> None:
        unit = self._stack[-1] if self._stack else None
        status = body.get("status") if isinstance(body, dict) else None
        event = self._event("write", unit=unit["unit"] if unit else None, bucket=bucket, key=str(key),
                            status=status,
                            digest=body_digest(self.normalize(body) if self.normalize else body))
        if unit is None:
            self._violation("write_outside_unit", event)
        elif unit["fence_failed"]:
            self._violation("write_after_failed_fence", event)

    def fence(self, name: str, ok: bool) -> None:
        unit = self._stack[-1] if self._stack else None
        self._event("fence", unit=unit["unit"] if unit else None, name=name, ok=bool(ok))
        if unit is not None and not ok:
            unit["fence_failed"] = True

    def effect(self, name: str) -> None:
        event = self._event("effect", name=name, depth=self.depth)
        if self.depth > 0:
            self._violation("effect_inside_unit", event)

    # -- derived views -------------------------------------------------------------------------

    def unit_outcomes(self) -> dict[str, str]:
        return {e["unit"]: e["kind"] for e in self.events if e["kind"] in {"COMMIT", "ROLLBACK"}}

    def durable_writes(self, since: int = 0) -> list[dict]:
        outcomes = self.unit_outcomes()
        return [e for e in self.events[since:]
                if e["kind"] == "write" and outcomes.get(e["unit"]) == "COMMIT"]

    def classify(self, authority_buckets: set[str], completion, since: int = 0) -> str:
        """`atomic_commit`, `atomic_rollback` or `partial_commit` for one logical authority unit.

        Authority writes are the unit's cross-owner writes (e.g. releases, release_queue, hooks);
        `completion(write_event)` names the terminal write (e.g. decisions_pending succeeded).
        """
        durable = self.durable_writes(since)
        authority = [e for e in durable if e["bucket"] in authority_buckets]
        completions = [e for e in durable if completion(e)]
        if not completions:
            return "atomic_rollback" if not authority else "partial_commit"
        units = {e["unit"] for e in completions}
        if len(units) == 1 and all(e["unit"] in units for e in authority):
            return "atomic_commit"
        return "partial_commit"

    def effect_protocol(self, intent, completion, since: int = 0) -> list[str]:
        """Intent must be durable before an effect; a completion needs a preceding effect."""
        outcomes = self.unit_outcomes()
        problems, intent_committed, effect_seen = [], False, False
        commit_seq = {e["unit"]: e["seq"] for e in self.events if e["kind"] == "COMMIT"}
        ordered = []
        for e in self.events[since:]:
            if e["kind"] == "write" and outcomes.get(e["unit"]) == "COMMIT":
                ordered.append((commit_seq[e["unit"]], e))
            elif e["kind"] == "effect":
                ordered.append((e["seq"], e))
        for _, e in sorted(ordered, key=lambda item: (item[0], item[1]["seq"])):
            if e["kind"] == "effect":
                if not intent_committed:
                    problems.append("effect_without_committed_intent")
                effect_seen = True
            elif intent(e):
                intent_committed = True
            elif completion(e) and not effect_seen:
                problems.append("completion_without_effect")
        return problems

    def trace(self) -> list[dict]:
        """The comparable trace: sequence numbers dropped, unit ids kept (they are ordinal)."""
        return [{k: v for k, v in e.items() if k != "seq"} for e in self.events]


class RecordingTransaction:
    def __init__(self, inner, recorder: Recorder):
        self._inner = inner
        self._recorder = recorder

    def put(self, bucket, key, body):
        self._recorder.write(bucket, key, body)
        return self._inner.put(bucket, key, body)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class RecordingStore:
    def __init__(self, inner, recorder: Recorder | None = None):
        self._inner = inner
        self.recorder = recorder or Recorder()

    @contextmanager
    def transaction(self, *args, **kwargs):
        unit = self.recorder.begin()
        try:
            with self._inner.transaction(*args, **kwargs) as tx:
                yield RecordingTransaction(tx, self.recorder)
        except BaseException as exc:
            self.recorder.end(unit, committed=False, error=exc)
            raise
        self.recorder.end(unit, committed=True)

    def __getattr__(self, name):
        return getattr(self._inner, name)
