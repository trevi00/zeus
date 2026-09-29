"""The review context a read-only reviewer is told: the trusted interpreter and the review checkout.

Layer: adapters
Context: context
Owns: the host (non-isolated) review-context value (review-contract-001)
Does not own: which interpreter is trusted (evidence, S8: passed in), the isolated variant (execution, S3)
Entry points: review_context

Moved from SOURCE M7 `adapters/executor.review_context`; the interpreter is injected (M7 called
`evidence_inspection.trusted_interpreter()`), the text is unchanged.
"""

from __future__ import annotations

from pathlib import Path


def review_context(cwd, interpreter) -> dict:
    """What a read-only reviewer runs tests with and against, composed by the host, never by the model
    (review-contract-001): the trusted interpreter that command replays also use, the review checkout
    and its `src` when present. Output is collected from stdout; nothing is written into the checkout."""
    root = Path(cwd).resolve()
    source = root / "src"
    return {"interpreter": str(interpreter), "cwd": str(root),
            "src": str(source) if source.is_dir() else None,
            "instruction": "Run tests with this interpreter against this checkout (for example "
            "<interpreter> -m pytest <focused tests>) so they exercise the candidate under review. "
            "Read results from stdout; do not redirect output into files, and do not create frame, log "
            "or note files in the checkout. Record one concise frame and verdict in your response; "
            "Zeus preserves the response and tool output outside the checkout."}
