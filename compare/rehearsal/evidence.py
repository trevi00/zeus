"""The rehearsal evidence writer (RH-1a rule 2): `run-start.json`, appended `steps.jsonl` rows
`{at, step, status, facts}`, `run-exit.json`, then `SHA256SUMS` last.

Every file is created O_EXCL and refused when it already exists. Facts are bounded: a record body, an
environment value, or a digest/path under a `secrets` path is refused with a named `Refused` code.
The evidence root is injected; the live root is `A/evidence/rebuild/rehearsal/<run8>/` (no live run here).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from . import Refused, check_run8

MAX_STRING, MAX_ITEMS, MAX_DEPTH = 512, 64, 4
# Keys that name a record body or an environment value; a fact carries counts and digests of non-secret data.
BODY_KEYS = frozenset({"body", "bodies", "record", "records", "row", "rows", "payload", "document", "documents",
                       "content", "contents", "value", "values", "data"})
ENV_KEYS = frozenset({"env", "environ", "environment", "env_values"})
SECRET_PART = "secrets"
FILES = ("run-start.json", "steps.jsonl", "run-exit.json")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


def _secret_path(text: str) -> bool:
    return SECRET_PART in [part.lower() for part in text.replace("\\", "/").split("/")]


def check_facts(facts: object, *, _depth: int = 0, max_items: int = MAX_ITEMS) -> None:
    """Refuse a fact that is not bounded; the refusal names the rule, never the offending value.

    `max_items` widens only the per-container item bound (the D0 record lists every schema/bucket/module)."""
    if _depth > MAX_DEPTH:
        raise Refused("fact_too_deep")
    if isinstance(facts, dict):
        if len(facts) > max_items:
            raise Refused("fact_too_large")
        for key, value in facts.items():
            if not isinstance(key, str):
                raise Refused("fact_key_not_text")
            if key.lower() in ENV_KEYS:
                raise Refused("env_value_fact", key)
            if key.lower() in BODY_KEYS:
                raise Refused("record_body_fact", key)
            if _secret_path(key):
                raise Refused("secret_path_fact", "key")
            check_facts(value, _depth=_depth + 1, max_items=max_items)
    elif isinstance(facts, (list, tuple)):
        if len(facts) > max_items:
            raise Refused("fact_too_large")
        for value in facts:
            check_facts(value, _depth=_depth + 1, max_items=max_items)
    elif isinstance(facts, str):
        if len(facts) > MAX_STRING:
            raise Refused("record_body_fact", "string over the bound")
        if _secret_path(facts):
            raise Refused("secret_path_fact", "value")
        if len(facts) >= 8 and facts in set(os.environ.values()):
            raise Refused("env_value_fact", "value equals an environment value")
    elif facts is not None and not isinstance(facts, (bool, int, float)):
        raise Refused("fact_type", type(facts).__name__)


def _create(path: Path, data: bytes = b"", *, append: bool = False) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | (os.O_APPEND if append else 0)
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        raise Refused("evidence_exists", path.name) from None
    if data:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(fd)
        os.close(fd)
        return -1
    return fd


def write_record(path: Path, document: dict, *, max_items: int = MAX_ITEMS) -> None:
    """Write one standalone evidence record (never overwritten): `document["facts"]` passes `check_facts` first."""
    check_facts(document.get("facts", {}), max_items=max_items)
    _create(Path(path), _line(document))


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


class Evidence:
    """One run's evidence directory. `root` IS that directory (the live one ends in `<run8>`)."""

    def __init__(self, run8: str, root: Path, *, clock: Callable[[], str] = _utc_now):
        self.run8, self.root, self.clock = check_run8(run8), Path(root), clock
        self.state, self.steps_fd = "new", -1

    def _need(self, *states: str) -> None:
        if self.state not in states:
            raise Refused("evidence_order", f"{self.state} -> expected {'/'.join(states)}")

    def start(self, facts: dict | None = None) -> None:
        self._need("new")
        facts = facts or {}
        check_facts(facts)
        self.root.mkdir(parents=True, exist_ok=True)
        _create(self.root / FILES[0], _line({"run8": self.run8, "at": self.clock(), "facts": facts}))
        self.state = "started"

    def step(self, step: str, status: str, facts: dict | None = None) -> None:
        self._need("started")
        facts = facts or {}
        check_facts({"step": step, "status": status})
        check_facts(facts)
        if self.steps_fd < 0:
            self.steps_fd = _create(self.root / FILES[1], append=True)
        os.write(self.steps_fd, _line({"at": self.clock(), "step": step, "status": status, "facts": facts}))
        os.fsync(self.steps_fd)

    def finish(self, status: str, facts: dict | None = None) -> None:
        """Write `run-exit.json`, then `SHA256SUMS` last; the run accepts nothing afterwards."""
        self._need("started")
        facts = facts or {}
        check_facts({"status": status})
        check_facts(facts)
        if self.steps_fd >= 0:
            os.close(self.steps_fd)
            self.steps_fd = -1
        _create(self.root / FILES[2], _line({"run8": self.run8, "at": self.clock(), "status": status, "facts": facts}))
        sums = "".join(f"{hashlib.sha256((self.root / name).read_bytes()).hexdigest()}  {name}\n"
                       for name in FILES if (self.root / name).exists())
        _create(self.root / "SHA256SUMS", sums.encode("ascii"))
        self.state = "finished"
