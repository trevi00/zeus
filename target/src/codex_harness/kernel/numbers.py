"""Finite-number predicate shared by every context that validates numeric policy values.

Layer: kernel
Context: kernel
Owns: the one definition of "a finite JSON number" (bool excluded)
Entry points: finite_number

Moved from SOURCE M7 `domain/threshold_replay.finite_number` (research) because context (skill
admission, native routing replay) and research both validate with it and neither may import the
other (§2.4); one definition in kernel, never a copy per context.
"""

from __future__ import annotations

import math


def finite_number(value) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False
