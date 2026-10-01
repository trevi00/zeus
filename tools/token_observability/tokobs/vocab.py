"""Bounded vocabularies and model normalization.

Purpose: the one place for label allowlists, reason/outcome enums and model-name normalization.
Layer: tooling. Owns: DESIGN §3.6 reason precedence, §3.7 version gate, §3.11 model normalization,
§5 label allowlists. Does-not-own: any ledger or file access.
Implements: ACCEPTANCE A22, A24, A31 (version parsing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LABEL_RE = re.compile(r"^[a-z0-9_.-]{1,48}$")
OTHER = "other"

PROVIDERS = ("anthropic", "openai")
SOURCES = ("routine", "coordinator", "lane", "codex_exec")
TOKEN_TYPES = ("input", "output", "cache_read", "cache_write")
ROLES = ("implementer", "advisor", "advisor_or_nested", "nested_unattributed", "coordinator",
         "lane_worker", "reviewer")
OUTCOMES = ("finished", "failed", "escalate", "blocked", "timed_out", "interrupted", "codex_completed",
            "codex_failed", "terminal_unproven")
# DESIGN §3.6: primary reason precedence, strongest first.
REASON_PRECEDENCE = ("no_result", "error_zeroed", "terminal_unproven", "incomplete_tail", "no_baseline",
                     "unknown_version_semantics", "non_monotonic", "inconsistent", "malformed")
EXECUTOR_ROLE = {"routine": "implementer", "coordinator": "coordinator", "lane": "lane_worker",
                 "codex_exec": "reviewer"}
LANE_HORIZON_SECONDS = 14_400  # DESIGN §3.2 / C-W1-2: idle horizon of a stream without launcher metadata
# DESIGN §3.2: S3 idle horizon = 2 x the policy `decision_seconds` (src/codex_harness/domain/policy.py). The
# collector is stdlib-only and runs where that package is absent, so the value is mirrored here and a test
# (test_tokobs_codex) asserts it still equals the policy field.
CODEX_DECISION_SECONDS = 900
CODEX_IDLE_SECONDS = 2 * CODEX_DECISION_SECONDS
IDENTITY_UNAVAILABLE = "identity_unavailable"
ADVISOR_STATES = ("enabled", "skipped", "unknown", "not_configured")
CORRECTION_KINDS = ("late_point", "late_predecessor", "late_terminal", "late_tail", "duplicate_after_publish")
OPEN_STATES = ("open", "terminal_observed_pending_eof", "awaiting_predecessor")
FILE_STATES = ("open", "finalized", "alias_pending", "bound")
TASK_OUTCOMES = ("accepted", "abandoned")
WINDOW_STATES = ("current", "stale", "expired", "unavailable")

MODEL_ALLOWLIST = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "gpt-6-astra")
FAMILY_MODEL = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-4-5"}
FIXED_TASK_CLASSES = ("unclassified", "unattributed_interval", "identity_unavailable", "coordination", OTHER)
MAX_TASK_CLASSES = 16  # DESIGN §5: task_class <= 16 values including the fixed ones
MAX_REGISTRY_CLASSES = MAX_TASK_CLASSES - len(FIXED_TASK_CLASSES)

# Per-label allowlists (DESIGN §5). A value outside its list is exported as `other`.
LABEL_ALLOWLISTS = {
    "provider": frozenset(PROVIDERS),
    "role": frozenset(ROLES),
    "token_type": frozenset(TOKEN_TYPES),
    "source": frozenset(SOURCES),
    "outcome": frozenset(OUTCOMES) | frozenset(TASK_OUTCOMES),
    "reason": frozenset(REASON_PRECEDENCE),
    "state": frozenset(OPEN_STATES) | frozenset(ADVISOR_STATES) | frozenset(FILE_STATES) | frozenset(WINDOW_STATES),
    "slot": frozenset(("primary", "secondary", "unknown")),
    "window": frozenset(("five_hour", "seven_day")),
    "freshness": frozenset(("current", "stale")),
    "provenance": frozenset(("stream_preceding_timestamp",)),
    "kind": frozenset(CORRECTION_KINDS),
    "first_pass": frozenset(("true", "false")),
}

_VARIANT = re.compile(r"\[[^\]]*\]$")
_VERSION = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
# D2: before 2.1.277 a resumed process started its totals at zero.
RESUME_CUMULATIVE_SINCE = (2, 1, 277)


def strip_variant(model: str) -> str:
    return _VARIANT.sub("", model.strip())


@dataclass(frozen=True)
class ModelLabel:
    label: str
    recognized: bool | None  # None: no model information at all (never flagged)


def normalize_model(raw: object) -> ModelLabel:
    """DESIGN §3.11: allowlist + `opus`/`sonnet`/`haiku` aliases; `[…]` variants stripped; else `other`."""
    if not isinstance(raw, str) or not raw.strip():
        return ModelLabel(OTHER, None)
    base = strip_variant(raw).lower()
    if base in FAMILY_MODEL:
        return ModelLabel(FAMILY_MODEL[base], True)
    if base in MODEL_ALLOWLIST:
        return ModelLabel(base, True)
    return ModelLabel(OTHER, False)


def is_model_mismatch(requested: object, observed: object) -> bool:
    """Requested and observed both known but different after normalization (A22)."""
    req, obs = normalize_model(requested), normalize_model(observed)
    if req.recognized is None or obs.recognized is None:
        return False
    if not req.recognized or not obs.recognized:
        return strip_variant(str(requested)) != strip_variant(str(observed))
    return req.label != obs.label


def provider_of(model_label: str) -> str:
    return "openai" if model_label.startswith("gpt-") else "anthropic"


def parse_version(raw: object) -> tuple[int, int, int] | None:
    if not isinstance(raw, str):
        return None
    match = _VERSION.match(raw.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def primary_reason(reasons: set[str] | frozenset[str]) -> str | None:
    for reason in REASON_PRECEDENCE:
        if reason in reasons:
            return reason
    return None
