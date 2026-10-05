"""Reference-side block exercise recorder (S11 R-L3d, DESIGN-s11 §17): which M7 transaction blocks a golden case executed.

Layer: harness (never shipped); standard library only.

Python 3.12 `sys.monitoring` (PEP 669), tool id 3 (the predefined ids are 0-5; R-AU3's recorder uses COVERAGE_ID). LINE events
are set globally; a callback records a hit only while a window is open and only for the `(path, line)` of a
`transaction_blocks.units` entry of `compare/goldens/reference/static.source.json`, and every callback returns DISABLE.
`open()` calls `restart_events()`, so each window sees every location once.

Armed ONLY when `ZEUS_BLOCK_EXERCISE_OUT` names an output file. `compare/run.py run --record` sets it for the REFERENCE
driver alone; the target side and CI compare runs never set it. Unarmed, `open`/`close`/`assign` are no-ops and no tool id
is taken. The driver's window (`open` .. `close`) is the unit-under-test call; the file it writes is `{case: [block key]}`
and `compare/run.py` turns it into `goldens/reference/<family>.blocks.json` with `artifact()`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV = "ZEUS_BLOCK_EXERCISE_OUT"
TOOL = 3
SCHEMA = "zeus:s11-block-exercise:1"
CATALOGUE = Path(__file__).resolve().parents[1] / "goldens/reference/static.source.json"


def block_lines(units: list[dict]) -> dict[tuple[str, int], str]:
    """`(path under the package root, line)` -> block key, for the catalogue's transaction blocks."""
    return {(u["path"].removeprefix("src/"), u["line"]): u["key"] for u in units}


def artifact(family: str, cases: dict[str, list[str]]) -> str:
    """The committed blocks artifact: sorted keys and lists, one trailing newline (deterministic bytes)."""
    document = {"schema": SCHEMA, "family": family, "cases": {k: sorted(set(v)) for k, v in sorted(cases.items())}}
    return json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


class Recorder:
    def __init__(self, blocks: dict[tuple[str, int], str], out: Path, tool: int = TOOL):
        self.blocks, self.out, self.tool = blocks, Path(out), tool
        self.suffixes = sorted({p for p, _ in blocks})
        self.lines = {line for _, line in blocks}
        self.windows: list[tuple[str, set[str]]] = []  # in opening order: (case key, block keys)
        self.hits: set[str] | None = None
        self.files: dict[str, str | None] = {}
        events = sys.monitoring.events
        sys.monitoring.use_tool_id(tool, "zeus-block-exercise")
        sys.monitoring.register_callback(tool, events.LINE, self._line)
        sys.monitoring.set_events(tool, events.LINE)

    def _path(self, filename: str) -> str | None:
        if filename not in self.files:
            self.files[filename] = next((p for p in self.suffixes if filename.endswith("/" + p)), None)
        return self.files[filename]

    def _line(self, code, line):
        if self.hits is not None and line in self.lines:
            path = self._path(code.co_filename)
            key = self.blocks.get((path, line)) if path else None
            if key:
                self.hits.add(key)
        return sys.monitoring.DISABLE

    def open(self, case: str) -> None:
        if self.hits is not None:
            raise SystemExit(f"block exercise: window {case!r} opened inside the open window {self.windows[-1][0]!r}")
        sys.monitoring.restart_events()
        self.hits = set()
        self.windows.append((case, self.hits))

    def close(self) -> None:
        self.hits = None
        self.write()

    def cases(self) -> dict[str, list[str]]:
        merged: dict[str, set[str]] = {}
        for case, hits in self.windows:
            merged.setdefault(case, set()).update(hits)
        return {k: sorted(v) for k, v in sorted(merged.items())}

    def write(self) -> None:
        self.out.write_text(json.dumps(self.cases(), sort_keys=True, indent=1) + "\n", encoding="utf-8")

    def assign(self, keys: list[str]) -> None:
        """Name the windows, in opening order, with the golden case keys (the driver evaluates its cases in key order).

        One window per case (S11 R-L3d-2): each `Case` opens its window under its own case name, so a name that opens two
        windows is a case with a double open, and a missing window shows as a count short of the golden's cases."""
        names = [name for name, _ in self.windows]
        doubled = sorted({n for n in names if names.count(n) > 1})
        if doubled:
            raise SystemExit(f"block exercise: case(s) {doubled} opened more than one window")
        if len(keys) != len(self.windows):
            raise SystemExit(f"block exercise: {len(self.windows)} windows for {len(keys)} golden cases (a case opened none)")
        self.windows = [(key, hits) for key, (_, hits) in zip(keys, self.windows)]
        self.write()

    def release(self) -> None:
        events = sys.monitoring.events
        sys.monitoring.set_events(self.tool, 0)
        sys.monitoring.register_callback(self.tool, events.LINE, None)
        sys.monitoring.free_tool_id(self.tool)


_recorder: Recorder | None = None


def _armed() -> Recorder | None:
    global _recorder
    out = os.environ.get(ENV)
    if not out:
        return None
    if _recorder is None:
        units = json.loads(CATALOGUE.read_text(encoding="utf-8"))["transaction_blocks"]["units"]
        _recorder = Recorder(block_lines(units), Path(out))
    return _recorder


def open(case: str) -> None:  # noqa: A001 - the window verb of the design (§17 item 2)
    recorder = _armed()
    if recorder is not None:
        recorder.open(case)


def close() -> None:
    recorder = _armed()
    if recorder is not None:
        recorder.close()


def assign(keys: list[str]) -> None:
    recorder = _armed()
    if recorder is not None:
        recorder.assign(keys)
