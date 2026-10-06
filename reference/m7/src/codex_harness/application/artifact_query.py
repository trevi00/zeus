"""Bounded projections over an already integrity-checked immutable artifact."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from typing import Any

CONTRACT = "artifact-query.v1"
DEFAULT_LIMIT = 8000
MAX_LIMIT = 32000
MIN_LIMIT = 512


class ArtifactQueryError(ValueError):
    """The requested projection cannot satisfy the artifact query contract."""


def _json(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    # JSON accepts escaped surrogate code points that UTF-8 output does not. Keep
    # ordinary Unicode readable while re-escaping only those unsafe code points.
    return rendered.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _require_limit(limit: int) -> None:
    if type(limit) is not int or not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise ArtifactQueryError(f"Output limit must be {MIN_LIMIT}..{MAX_LIMIT} characters")


def _require_cursor(cursor: int) -> None:
    if type(cursor) is not int or cursor < 0:
        raise ArtifactQueryError("Cursor must be a non-negative integer")


def validate_bounds(cursor: int, limit: int) -> None:
    """Validate cheap request bounds before an adapter performs artifact I/O."""
    _require_limit(limit)
    _require_cursor(cursor)


def _render(envelope: dict[str, Any], limit: int) -> str:
    rendered = _json(envelope)
    if len(rendered) > limit:
        raise ArtifactQueryError("Query metadata exceeds output budget")
    return rendered


def _list_fits(
    base: dict[str, Any], content: list[dict[str, Any]], next_cursor: int, limit: int
) -> bool:
    continuing = {
        **base,
        "content": content,
        "next_cursor": next_cursor,
        "truncated": True,
    }
    complete = {**base, "content": content, "next_cursor": None, "truncated": False}
    return max(len(_json(continuing)), len(_json(complete))) <= limit


def _base(reference: str, mode: str, cursor: int, encoding: str) -> dict[str, Any]:
    return {
        "content_encoding": encoding,
        "contract": CONTRACT,
        "cursor": cursor,
        "mode": mode,
        "ref": reference,
    }


def _text_page(
    base: dict[str, Any], source: str, cursor: int, limit: int, **metadata: Any
) -> str:
    if cursor > len(source):
        raise ArtifactQueryError("Cursor exceeds projected content")

    def candidate(end: int) -> dict[str, Any]:
        truncated = end < len(source)
        return {
            **base,
            **metadata,
            "content": source[cursor:end],
            "next_cursor": end if truncated else None,
            "truncated": truncated,
        }

    # Completion removes the numeric cursor and can be shorter than a preceding page.
    if len(_json(candidate(len(source)))) <= limit:
        return _json(candidate(len(source)))
    low, high, best = cursor, len(source) - 1, None
    while low <= high:
        middle = (low + high) // 2
        if len(_json(candidate(middle))) <= limit:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best is None or best == cursor:
        raise ArtifactQueryError("Output budget is too small for one content character")
    return _json(candidate(best))


def page(reference: str, text: str, cursor: int = 0, limit: int = DEFAULT_LIMIT) -> str:
    """Return a character-offset page of the original artifact text."""
    _require_limit(limit)
    _require_cursor(cursor)
    return _text_page(
        _base(reference, "page", cursor, "text"),
        text,
        cursor,
        limit,
        total_characters=len(text),
    )


def _parse_json(text: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ArtifactQueryError("Artifact is not valid JSON") from exc


def _pointer_tokens(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ArtifactQueryError("Invalid JSON pointer: expected empty string or leading slash")
    if len(pointer) > 4096:
        raise ArtifactQueryError("JSON pointer exceeds 4096 characters")
    tokens = []
    for raw in pointer.split("/")[1:] if pointer else []:
        token, index = "", 0
        while index < len(raw):
            if raw[index] != "~":
                token += raw[index]
                index += 1
                continue
            if index + 1 >= len(raw) or raw[index + 1] not in "01":
                raise ArtifactQueryError("Invalid JSON pointer escape")
            token += "~" if raw[index + 1] == "0" else "/"
            index += 2
        tokens.append(token)
    return tokens


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in _pointer_tokens(pointer):
        if isinstance(value, dict):
            if token not in value:
                raise ArtifactQueryError("JSON pointer does not exist")
            value = value[token]
        elif isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ArtifactQueryError("JSON pointer has an invalid array index")
            index = int(token)
            if index >= len(value):
                raise ArtifactQueryError("JSON pointer does not exist")
            value = value[index]
        else:
            raise ArtifactQueryError("JSON pointer traverses a scalar value")
    return value


def pointer(
    reference: str,
    text: str,
    target: str,
    cursor: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """Page the canonical JSON serialization selected by an RFC 6901 pointer."""
    _require_limit(limit)
    _require_cursor(cursor)
    value = _resolve_pointer(_parse_json(text), target)
    try:
        projection = _json(value)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ArtifactQueryError("Selected JSON value cannot be serialized") from exc
    return _text_page(
        _base(reference, "pointer", cursor, "json"),
        projection,
        cursor,
        limit,
        pointer=target,
        total_characters=len(projection),
    )


def _pointer_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "object"


def _index_entries(document: Any) -> Iterator[dict[str, Any]]:
    stack: list[tuple[str, Any]] = [("", document)]
    while stack:
        target, value = stack.pop()
        entry: dict[str, Any] = {"pointer": target, "type": _kind(value)}
        if isinstance(value, (dict, list, str)):
            entry["length"] = len(value)
        yield entry
        if isinstance(value, dict):
            for key in sorted(value, reverse=True):
                stack.append((target + "/" + _pointer_escape(key), value[key]))
        elif isinstance(value, list):
            for item_index in range(len(value) - 1, -1, -1):
                stack.append((target + "/" + str(item_index), value[item_index]))


def _compact_index_entry(entry: dict[str, Any], base: dict[str, Any], limit: int) -> dict[str, Any]:
    if _list_fits(base, [entry], 1, limit):
        return entry
    target = entry["pointer"]
    compact = {
        **entry,
        "pointer": target[:80],
        "pointer_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        "pointer_truncated": True,
    }
    return compact


def index(
    reference: str, text: str, cursor: int = 0, limit: int = DEFAULT_LIMIT
) -> str:
    """Return a deterministic, paged structural index of JSON pointers."""
    _require_limit(limit)
    _require_cursor(cursor)
    base = _base(reference, "index", cursor, "json-index")
    entries = _index_entries(_parse_json(text))
    for _ in range(cursor):
        if next(entries, None) is None:
            raise ArtifactQueryError("Cursor exceeds JSON index")
    content: list[dict[str, Any]] = []
    position = cursor
    while True:
        entry = next(entries, None)
        if entry is None:
            return _render(
                {**base, "content": content, "next_cursor": None, "truncated": False}, limit
            )
        entry = _compact_index_entry(entry, base, limit)
        candidate_content = [*content, entry]
        if not _list_fits(base, candidate_content, position + 1, limit):
            if not content:
                raise ArtifactQueryError("JSON index entry exceeds output budget")
            return _render(
                {
                    **base,
                    "content": content,
                    "next_cursor": position,
                    "truncated": True,
                },
                limit,
            )
        content = candidate_content
        position += 1


def _snippet(text: str, start: int, end: int, width: int = 320) -> tuple[int, int, str]:
    match_middle = (start + end) // 2
    window_start = max(0, match_middle - width // 2)
    window_end = min(len(text), window_start + width)
    window_start = max(0, window_end - width)
    return window_start, window_end, text[window_start:window_end]


def search(
    reference: str,
    text: str,
    query: str,
    cursor: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """Return bounded windows around case-insensitive matches, starting at a text cursor."""
    _require_limit(limit)
    _require_cursor(cursor)
    if not isinstance(query, str) or not query:
        raise ArtifactQueryError("Search query must be non-empty")
    if len(query) > 4096:
        raise ArtifactQueryError("Search query exceeds 4096 characters")
    if cursor > len(text):
        raise ArtifactQueryError("Cursor exceeds artifact text")
    base = {
        **_base(reference, "search", cursor, "search-hits"),
        "query": query,
    }
    expression = re.compile(re.escape(query), re.IGNORECASE)
    content: list[dict[str, Any]] = []
    position = cursor
    while True:
        match = expression.search(text, position)
        if match is None:
            return _render(
                {**base, "content": content, "next_cursor": None, "truncated": False}, limit
            )
        window_start, window_end, snippet = _snippet(text, match.start(), match.end())
        hit = {
            "end": match.end(),
            "snippet": snippet,
            "start": match.start(),
            "window_end": window_end,
            "window_start": window_start,
        }
        next_position = max(match.end(), match.start() + 1)
        candidate_content = [*content, hit]
        if not _list_fits(base, candidate_content, next_position, limit):
            if not content:
                hit["snippet"] = ""
                hit["window_end"] = hit["window_start"] = match.start()
                if not _list_fits(base, [hit], next_position, limit):
                    raise ArtifactQueryError("Search metadata exceeds output budget")
                content.append(hit)
                position = next_position
                continue
            return _render(
                {
                    **base,
                    "content": content,
                    "next_cursor": position,
                    "truncated": True,
                },
                limit,
            )
        content = candidate_content
        position = next_position
