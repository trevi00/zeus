"""Contract tests for the dependency-free immutable artifact reader."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.application import artifact_query


def _pages(call):
    """Collect every page, proving cursors neither overlap nor skip content."""
    cursor = 0
    pieces: list[str] = []
    while True:
        rendered = call(cursor)
        assert len(rendered) <= 512
        page = json.loads(rendered)
        assert page["cursor"] == cursor
        pieces.append(page["content"])
        if page["next_cursor"] is None:
            assert not page["truncated"]
            return "".join(pieces)
        assert page["truncated"]
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]


def test_page_reconstructs_unicode_quotes_and_backslashes_at_minimum_budget():
    text = ('한글 "quoted" \\ path / value\n' * 200) + "끝"
    result = _pages(lambda cursor: artifact_query.page("sha256:" + "a" * 64, text, cursor, 512))
    assert result == text


def test_pointer_reconstructs_canonical_json_across_pages_without_gaps():
    document = {"a/b~c": {"items": ["한글\\\"" * 160, {"z": 3}]}}
    text = json.dumps(document, ensure_ascii=False)
    expected = json.dumps(document["a/b~c"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result = _pages(
        lambda cursor: artifact_query.pointer(
            "sha256:" + "b" * 64, text, "/a~1b~0c", cursor, 512
        )
    )
    assert result == expected


def test_rfc6901_escapes_and_invalid_array_indexes():
    text = '{"a/b~c":["zero","one"]}'
    answer = json.loads(artifact_query.pointer("sha256:" + "c" * 64, text, "/a~1b~0c/1"))
    assert answer["content"] == '"one"'
    for target in ("/a~1b~0c/-1", "/a~1b~0c/01", "/a~1b~0c/+1"):
        with pytest.raises(artifact_query.ArtifactQueryError, match="array index"):
            artifact_query.pointer("sha256:" + "c" * 64, text, target)
    with pytest.raises(artifact_query.ArtifactQueryError, match="escape"):
        artifact_query.pointer("sha256:" + "c" * 64, text, "/a~2b")


def test_megabyte_single_line_json_has_pointer_and_useful_search_near_end():
    nonce = "UNIQUE-NONCE-9f1d"
    text = json.dumps({"payload": "x" * (1024 * 1024), "nonce": nonce}, separators=(",", ":"))
    pointer = json.loads(artifact_query.pointer("sha256:" + "d" * 64, text, "/nonce", limit=512))
    assert pointer["content"] == json.dumps(nonce)
    search = json.loads(artifact_query.search("sha256:" + "d" * 64, text, nonce, limit=8000))
    hit = search["content"][0]
    assert hit["start"] > 1024 * 1024
    assert nonce in hit["snippet"]
    assert len(search["content"][0]["snippet"]) <= 320


def test_search_cursor_budget_rescans_a_large_gap_without_growing_the_envelope():
    reference = "sha256:" + "4" * 64
    query = "needle"
    text = query + "x" * 1_000_000 + query
    generous = json.loads(artifact_query.search(reference, text, query, limit=8000))
    first = generous["content"][0]
    base = {
        "content_encoding": "search-hits",
        "contract": artifact_query.CONTRACT,
        "cursor": 0,
        "mode": "search",
        "query": query,
        "ref": reference,
    }
    continuing = {**base, "content": [first], "next_cursor": len(query), "truncated": True}
    complete = {**base, "content": [first], "next_cursor": None, "truncated": False}
    limit = max(
        len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        for value in (continuing, complete)
    )
    assert limit == 625

    rendered = artifact_query.search(reference, text, query, limit=limit)
    page = json.loads(rendered)
    assert len(rendered) <= limit
    assert page["truncated"] and page["next_cursor"] == len(query)
    resumed = json.loads(
        artifact_query.search(reference, text, query, cursor=page["next_cursor"], limit=8000)
    )
    assert resumed["content"][0]["start"] == len(query) + 1_000_000


def test_index_pages_every_path_without_including_huge_values():
    huge = "v" * 100_000
    text = json.dumps({"root": {"slash/key": huge, "array": [True, None]}})
    cursor = 0
    pointers: list[str] = []
    while True:
        rendered = artifact_query.index("sha256:" + "e" * 64, text, cursor, 512)
        assert len(rendered) <= 512
        page = json.loads(rendered)
        serialized_content = json.dumps(page["content"])
        assert huge not in serialized_content
        pointers.extend(item["pointer"] for item in page["content"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert pointers == ["", "/root", "/root/array", "/root/array/0", "/root/array/1", "/root/slash~1key"]


@pytest.mark.parametrize("limit", [511, 32001, True, 512.0])
def test_invalid_output_budgets_are_rejected(limit):
    with pytest.raises(artifact_query.ArtifactQueryError, match="Output limit"):
        artifact_query.page("sha256:" + "f" * 64, "x", limit=limit)


def _write_artifact(root: Path, text: str) -> str:
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    (root / f"{digest}.txt").write_bytes(data)
    return "sha256:" + digest


def test_standalone_reader_uses_only_stdlib_and_rejects_missing_or_tampered_artifacts(tmp_path):
    reference = _write_artifact(tmp_path, '{"message":"한글 \\\"quoted\\\" \\\\ path"}')
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    command = [
        sys.executable,
        "-S",
        "-m",
        "codex_harness.adapters.artifact_reader",
        "--root",
        str(tmp_path),
        "--ref",
        reference,
        "page",
        "--limit",
        "8000",
    ]
    success = subprocess.run(command, env=environment, capture_output=True,
                             text=True, encoding="utf-8", check=False)
    assert success.returncode == 0 and len(success.stdout) <= 8000
    assert json.loads(success.stdout)["content"]

    (tmp_path / f"{reference[7:]}.txt").write_text("tampered", encoding="utf-8")
    tampered = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
    assert tampered.returncode == 1 and tampered.stdout == ""
    assert json.loads(tampered.stderr)["error"] == "Artifact modified"

    missing_command = [*command]
    missing_command[missing_command.index(reference)] = "sha256:" + "0" * 64
    missing = subprocess.run(missing_command, env=environment, capture_output=True, text=True, check=False)
    assert missing.returncode == 1 and missing.stdout == ""
    assert len(missing.stderr) <= 512
    assert json.loads(missing.stderr)["error"] == "Artifact is unavailable"
