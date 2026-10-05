"""The artifact store RunTask writes provider-stream evidence through: credential spans are redacted before the write.

Layer: adapters
Context: execution
Owns: `RedactingArtifacts`, an artifact-store decorator that redacts the persisted provider-stream artifacts
    (`runtime-event:` and `execution:` sources) and records the count in the artifact's receipt
Does not own: the artifact store and its digest (storage), the credential-pattern redaction itself (observation's
    `redact_credential_shapes`, injected by composition: execution may not import observation), the other artifact sources
Entry points: RedactingArtifacts, STREAM_SOURCES, redact_document
Contracts: INV-ARTIFACT-001, INV-OBSERVATION-001

S11 XC-2b B3 (TQ-XCUT-PLAN B3): the provider's text (assistant text, tool results, result text, stderr tail) is persisted by
RunTask as `runtime-event:<key>` and `execution:<key>` artifacts and served verbatim by `zeus artifact`. The document is parsed,
every string in it (keys included) goes through the injected `redact(text) -> (text, count)` (credential SHAPES only: other bytes, prose included, are unchanged), and the artifact is the
redacted document: the store's digest is of the redacted bytes. With no credential-shaped span the body is passed through
unchanged (byte-identical to before) and the receipt records `redactions: 0`. Other artifacts are never touched.
"""
from __future__ import annotations

import json

from codex_harness.execution.adapters.execution_output import evidence_json

STREAM_SOURCES = ("runtime-event:", "execution:")


def redact_document(value, redact):
    """`(document, count)`: every string and mapping key redacted, structure and non-string values unchanged."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        out, total = {}, 0
        for key, item in value.items():
            key_text, found = (redact(key) if isinstance(key, str) else (key, 0))
            item, more = redact_document(item, redact)
            out[key_text] = item
            total += found + more
        return out, total
    if isinstance(value, (list, tuple)):
        out, total = [], 0
        for item in value:
            item, found = redact_document(item, redact)
            out.append(item)
            total += found
        return out, total
    return value, 0


class RedactingArtifacts:
    def __init__(self, artifacts, redact):
        self._artifacts, self._redact = artifacts, redact

    def __getattr__(self, name):
        return getattr(self._artifacts, name)

    def put(self, body, source, lock_timeout=30):
        if not source.startswith(STREAM_SOURCES):
            return self._artifacts.put(body, source, lock_timeout)
        document, count = redact_document(json.loads(body), self._redact)
        return self._artifacts.put(evidence_json(document) if count else body, source, lock_timeout, redactions=count)
