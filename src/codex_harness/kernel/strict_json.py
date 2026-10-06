"""Strict JSON reading: duplicate object keys are refused.

Layer: kernel
Context: kernel
Owns: `parse_json`, the pure strict JSON reader (M7 `adapters/sdd.py`, moved ahead in S8)
Does not own: reading spec files, Git and the SDD adapter (the review SDD adapter, S8 step 6)
Entry points: parse_json
Contracts: INV-SDD-001

Moved ahead from M7 `adapters/sdd.py` (SOURCE e38aa722) for review (sdd) and intake (ticket_authority) per DESIGN-s8 V2b (A/evidence/rebuild/s8/domain-moves-a/transcribe.py); the function is M7's verbatim, M7 `adapters/sdd.py` itself is not moved here.
"""
import json

from codex_harness.kernel.errors import require


def parse_json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(body, object_pairs_hook=unique)
