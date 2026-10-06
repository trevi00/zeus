"""Cutover rehearsal tooling (RH-1a): the evidence writer, disposable PostgreSQL/Redis copies and the label sweep.

Layer: harness (never shipped; AMD-1 C.8: this branch is never merged before C). Standard library plus the
repository's own dependencies (`psycopg`, `redis`) only; nothing here reads or writes a production path.
"""

from __future__ import annotations

import re

RUN8 = re.compile(r"[0-9a-f]{8}")


class Refused(ValueError):
    """A rule of the rehearsal tooling refused the request before any effect; `code` names the rule."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def check_run8(run8: object) -> str:
    if not isinstance(run8, str) or RUN8.fullmatch(run8) is None:
        raise Refused("bad_run8", "run8 must match ^[0-9a-f]{8}$")
    return run8
