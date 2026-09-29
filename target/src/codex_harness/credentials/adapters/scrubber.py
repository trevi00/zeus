"""The Codex output boundary of one run: credential material never leaves the role-container layer.

Layer: adapters
Context: credentials
Owns: `CredentialScrubber` (every event before the executor sees it, every failure text, the retained
    result and the returned value) and `OutputUnsanitizable` (the refusal when the secret set of a run
    cannot be established: nothing more is forwarded, returned or kept)
Does not own: the credential shape rules (credentials.domain), the per-run copy (codex_custody), the
    transport that produces the events (execution)
Entry points: CredentialScrubber, OutputUnsanitizable
Contracts: INV-CODEX-CREDENTIAL-001

Moved from SOURCE M7 `adapters/role_containers` (the I1 F1 output boundary, Codex ACCEPT 45512161),
characterized first by the `credentials.scrubber` golden. RESEARCH-S3 G5: scrubbing by known values is
complete only while the secret set is known (issued plus every refresh, never dropping one) and a value
split across streamed fragments is withheld until decided; an unreadable or malformed per-run file
therefore refuses the output instead of forwarding it.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from codex_harness.credentials.adapters.codex_custody import read_credential_file
from codex_harness.credentials.domain.codex_credential import (
    JWT_SHAPE,
    JWT_TAIL,
    MAX_AUTH_BYTES,
    REDACTED,
    REDACTED_JWT,
    credential_values,
)
from codex_harness.kernel.errors import ContractError, IsolationError

SECRET_READ_ATTEMPTS, SECRET_READ_PAUSE = 5, 0.02  # rides over one in-place rewrite by the CLI


class OutputUnsanitizable(IsolationError):
    """The secret set of a run could not be established: nothing more is forwarded, returned or kept."""

    def __init__(self, detail: str):
        super().__init__("codex_output_secret_set_unavailable", detail)


class CredentialScrubber:
    """INV-CODEX-CREDENTIAL-001 output boundary of one Codex run: every event before the executor sees
    it, every failure text, the retained result and the returned value.

    The secret set is every credential leaf of the per-run auth.json as issued, kept current by
    re-reading that file before each forward (a refresh adds its new values; nothing is ever dropped).
    Values stay in memory and are replaced by fixed markers. A streamed `delta` fragment that may still
    grow into a credential or a JWT-shaped string is withheld until the next fragment of the same
    stream decides it, so no split value is forwarded piecewise; a stream that ends on such a tail
    keeps it withheld (the completed item carries the full scrubbed text)."""

    def __init__(self, issued: bytes, path):
        self.path, self.secrets, self._variants, self._pattern = Path(path), set(), [], None
        self._digest, self._pending = None, {}
        try:
            self._learn(issued)
        except IsolationError as exc:
            raise OutputUnsanitizable(exc.reason_code) from None

    def _learn(self, data: bytes) -> None:
        values = credential_values(data)
        self._digest = hashlib.sha256(data).hexdigest()
        if values <= self.secrets:
            return
        self.secrets |= values
        # The raw value and its JSON-escaped form, longest first so no shorter value splits a longer one.
        self._variants = sorted({form for value in self.secrets
                                 for form in (value, json.dumps(value, ensure_ascii=False)[1:-1])},
                                key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(form) for form in self._variants))

    def refresh(self) -> None:
        """The current per-run auth.json joins the secret set; unreadable or malformed refuses."""
        reason = None
        for attempt in range(SECRET_READ_ATTEMPTS):
            if attempt:
                time.sleep(SECRET_READ_PAUSE)
            try:
                data = read_credential_file(self.path)
                if hashlib.sha256(data).hexdigest() != self._digest:
                    self._learn(data)
                return
            except (IsolationError, OSError) as exc:
                reason = getattr(exc, "reason_code", type(exc).__name__)
        raise OutputUnsanitizable(reason)

    def text(self, value: str) -> str:
        if self._pattern is not None:
            value = self._pattern.sub(REDACTED, value)
        return JWT_SHAPE.sub(REDACTED_JWT, value)

    def scrub(self, value):
        """Stateless: every string, dictionary key included, of a JSON-shaped value."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.scrub(key): self.scrub(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(self.scrub(item) for item in value)
        return value

    def event(self, event):
        """One event as the executor may see it, after the secret set is brought current."""
        self.refresh()
        params = event.get("params") if isinstance(event, dict) else None
        stream = (str(event.get("method")) if isinstance(event, dict) else "",
                  *(str(params.get(name)) for name in ("itemId", "summaryIndex", "contentIndex")
                    if isinstance(params, dict)))
        return self._walk(event, stream)

    def _walk(self, value, stream):
        if isinstance(value, dict):
            return {self.scrub(key): self._fragment(stream + (key,), item) if key == "delta" and isinstance(item, str)
                    else self._walk(item, stream + (str(key),)) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(self._walk(item, stream) for item in value)
        return self.scrub(value)

    def _fragment(self, stream, text: str) -> str:
        buffer = self._pending.pop(stream, "") + text
        held = self._undecided_tail(buffer)
        if held:
            self._pending[stream] = buffer[len(buffer) - held:]
            buffer = buffer[:len(buffer) - held]
        return self.text(buffer)

    def _undecided_tail(self, buffer: str) -> int:
        longest = 0
        for form in self._variants:
            index = buffer.find(form[0], max(0, len(buffer) - len(form)))
            while index != -1 and len(buffer) - index > longest:
                if form.startswith(buffer[index:]):
                    longest = len(buffer) - index
                    break
                index = buffer.find(form[0], index + 1)
        tail = JWT_TAIL.search(buffer, max(0, len(buffer) - MAX_AUTH_BYTES))
        return max(longest, len(buffer) - tail.start() if tail else 0)

    def failure(self, exc: Exception) -> Exception:
        """The same failure with credential material replaced (the original when nothing matched); an
        unestablished secret set replaces the whole failure with the fixed refusal."""
        try:
            self.refresh()
        except OutputUnsanitizable as refused:
            return refused
        text = str(exc)
        clean = self.text(text)
        if clean == text:
            return exc
        kind = type(exc) if type(exc) in (ContractError, RuntimeError, ValueError, OSError) else ContractError
        replaced = kind(clean)
        if hasattr(exc, "capture_cleanup"):
            replaced.capture_cleanup = exc.capture_cleanup
        return replaced

    def result(self, value: dict, forwarded: dict) -> dict:
        """The transport value: the returned events are exactly the forwarded (scrubbed) ones."""
        self.refresh()
        clean = self.scrub({key: item for key, item in value.items() if key != "events"})
        if isinstance(value.get("events"), list):
            clean["events"] = [forwarded[id(event)] if id(event) in forwarded else self.scrub(event)
                               for event in value["events"]]
        return clean
