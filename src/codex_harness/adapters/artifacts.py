from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from filelock import FileLock

from codex_harness.domain.model import ContractError, canonical, require, utcnow


class FileArtifacts:
    """Content-addressed external context. Reads are bounded and integrity checked."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, body: str, source: str) -> dict:
        with FileLock(str(self.root.parent / "artifacts.lock"), timeout=30):
            return self._put(body, source)

    def _put(self, body: str, source: str) -> dict:
        data = body.encode("utf-8")
        key = hashlib.sha256(data).hexdigest()
        path = self.root / (key + ".txt")
        if path.exists():
            require(path.read_bytes() == data, "Artifact integrity failure")
            path.touch()
        else:
            try:
                with path.open("xb") as stream:
                    stream.write(data)
            except FileExistsError:
                require(path.read_bytes() == data, "Concurrent artifact integrity failure")
        receipt = {"ref": "sha256:" + key, "source": source, "bytes": len(data), "at": utcnow()}
        metadata = self.root / (key + ".json")
        if not metadata.exists():
            metadata.write_text(canonical(receipt), encoding="utf-8")
        return receipt

    def _body(self, reference: str, max_bytes: int | None = None) -> str:
        require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", reference)), "Invalid artifact reference")
        key = reference.partition(":")[2]
        with (self.root / (key + ".txt")).open("rb") as stream:
            data = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        require(max_bytes is None or len(data) <= max_bytes, "Artifact exceeds text budget")
        require(hashlib.sha256(data).hexdigest() == key, "Artifact modified")
        return data.decode("utf-8")

    def document(self, reference: str) -> dict:
        """Load an integrity-checked document for mechanical validation, not model context."""
        value = json.loads(self._body(reference))
        require(isinstance(value, dict), "Evidence document must be an object")
        return value

    def text(self, reference: str, max_bytes: int) -> str:
        """One integrity-checked bounded document read for mechanical consumers."""
        require(type(max_bytes) is int and 0 < max_bytes <= 1024 * 1024, 'Invalid text budget')
        return self._body(reference, max_bytes)

    def read(self, reference: str, start: int = 0, length: int = 8000) -> str:
        require(start >= 0 and 0 < length <= 32000, "Artifact read exceeds budget")
        return self._body(reference)[start:start + length]

    def inspect(self, reference: str) -> dict:
        text = self._body(reference)
        try:
            metadata = json.loads((self.root / (reference[7:] + '.json')).read_text('utf-8'))
        except (OSError, ValueError) as exc:
            raise ContractError('Artifact metadata unavailable or invalid') from exc
        require(isinstance(metadata, dict), 'Artifact metadata must be an object')
        require(metadata.get('ref') == reference, 'Artifact metadata reference mismatch')
        require(type(metadata.get('bytes')) is int
                and metadata['bytes'] == len(text.encode('utf-8')),
                'Artifact metadata byte count mismatch')
        # Source/at remain descriptive metadata, not authenticated provenance.
        return {"ref": reference, "characters": len(text), "lines": len(text.splitlines()),
                "metadata": metadata}

    def search(self, reference: str, needle: str, limit: int = 20) -> list[dict]:
        require(bool(needle) and 0 < limit <= 100, "Invalid search budget")
        hits = []
        for number, line in enumerate(self._body(reference).splitlines(), 1):
            if needle.casefold() in line.casefold():
                hits.append({"line": number, "text": line[:1000]})
                if len(hits) == limit:
                    break
        return hits
