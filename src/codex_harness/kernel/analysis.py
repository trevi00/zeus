"""The analysis marker of one durable task result, projected to fixed codes (M7 `domain/observation`).

Layer: kernel
Context: kernel
Owns: ANALYSIS_* codes, ARTIFACT_REFERENCE, safe_code and analysis_facts (moved unchanged from M7
    `domain/observation.py`, where they sat beside the observation schema)
Does not own: the observation events themselves (observation, S9, which imports these from here)
Entry points: analysis_facts, safe_code, ANALYSIS_CHECKPOINTED, ANALYSIS_REJECTED, ANALYSIS_UNCLASSIFIED,
    ANALYSIS_CONTENT_REJECTED, ANALYSIS_OUTCOMES, ANALYSIS_REASONS, ANALYSIS_FACTS, NO_ANALYSIS,
    ARTIFACT_REFERENCE

Defined once in the kernel (S4, lead decision Option A) because coordination's execution notices read
the marker and no context may import observation (REBUILD-DESIGN-v2 §2.4); observation reuses it.
"""

from __future__ import annotations

import re

# self-improvement-reference-001: what one settled `audit_partition` execution's content was judged
# to be, written by the execution into its own durable result and read back from there. These are
# the one authority for the codes; `analysis_unclassified` is a result that carries no marker -
# historical rows included - and it is never promoted to a checkpoint or an acceptance. `safe_code`
# maps anything foreign to "unknown" rather than letting a stored string become a Zeus code. A
# checkpoint is partial progress, and a rejection is retained work, not a successful review.
ANALYSIS_CHECKPOINTED = "analysis_checkpointed"
ANALYSIS_REJECTED = "analysis_rejected"
ANALYSIS_UNCLASSIFIED = "analysis_unclassified"
ANALYSIS_CONTENT_REJECTED = "analysis_content_rejected"
ANALYSIS_OUTCOMES = (ANALYSIS_CHECKPOINTED, ANALYSIS_REJECTED, ANALYSIS_UNCLASSIFIED)
ANALYSIS_REASONS = (ANALYSIS_CONTENT_REJECTED,)
ANALYSIS_FACTS = ("analysis_outcome", "analysis_reason", "analysis_ref", "analysis_generation")
NO_ANALYSIS = dict.fromkeys(ANALYSIS_FACTS)
ARTIFACT_REFERENCE = re.compile(r"sha256:[0-9a-f]{64}")


def analysis_facts(result) -> dict:
    """The analysis outcome of ONE durable task result, in fixed codes and identifiers only.

    The result is data a reader reads, never an instruction: an outcome or reason outside the
    declared vocabularies is `unknown`, a reference that is not an immutable artifact handle is
    dropped, and a missing marker is `analysis_unclassified`. No stored string can become free text
    in a log, a step, a status read or a repair diagnosis this way. This is the one projection of
    that marker: `adapters.audit_service` and the repair owner both read it here.
    """
    analysis = result.get("analysis") if isinstance(result, dict) else None
    if not isinstance(analysis, dict):
        return {**NO_ANALYSIS, "analysis_outcome": ANALYSIS_UNCLASSIFIED}
    ref, generation = analysis.get("execution_ref"), analysis.get("partition_generation")
    return {"analysis_outcome": safe_code(analysis.get("outcome"), ANALYSIS_OUTCOMES,
                                          absent=ANALYSIS_UNCLASSIFIED),
            "analysis_reason": safe_code(analysis.get("reason_code"), ANALYSIS_REASONS, absent=None),
            "analysis_ref": ref if type(ref) is str and ARTIFACT_REFERENCE.fullmatch(ref) else None,
            "analysis_generation": generation if type(generation) is int else None}


def safe_code(value, allowed, *, absent: str = "none") -> str:
    """One declared code, or a word that says why there is none. Never the foreign value itself."""
    if value is None:
        return absent
    return value if type(value) is str and value in allowed else "unknown"
