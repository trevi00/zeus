"""The one ISO-8601 to epoch-seconds reader for audit and threshold telemetry.

Layer: kernel
Context: kernel
Owns: `timestamp`, M7 `domain/skill_audit.timestamp` (DESIGN-s8 V2g: context skills audit and research threshold replay share it, neither may import the other, §2.4)
Does not own: the skill audit aggregation (context.domain.skills.audit)
Entry points: timestamp
Contracts: INV-SKILL-HISTORY-001

Moved from M7 `domain/skill_audit.py` (SOURCE e38aa722); the function is M7's verbatim (A/evidence/rebuild/s8/domain-moves-b/transcribe.py).
"""
from datetime import datetime, timezone


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None
