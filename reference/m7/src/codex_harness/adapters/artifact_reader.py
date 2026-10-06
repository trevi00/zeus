"""Standalone bounded reader for immutable artifact files.

This module intentionally uses no harness bootstrap or external service adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from codex_harness.application import artifact_query


def load_artifact(root: str, reference: str) -> str:
    """Load exactly one content-addressed artifact and validate its bytes."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", reference):
        raise artifact_query.ArtifactQueryError("Invalid artifact reference")
    try:
        artifact_root = Path(root).resolve(strict=True)
    except OSError as exc:
        raise artifact_query.ArtifactQueryError("Artifact root is unavailable") from exc
    if not artifact_root.is_dir():
        raise artifact_query.ArtifactQueryError("Artifact root is not a directory")
    digest = reference[7:]
    try:
        data = (artifact_root / f"{digest}.txt").read_bytes()
    except OSError as exc:
        raise artifact_query.ArtifactQueryError("Artifact is unavailable") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise artifact_query.ArtifactQueryError("Artifact modified")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise artifact_query.ArtifactQueryError("Artifact is not valid UTF-8") from exc


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Bounded immutable artifact reader")
    command.add_argument("--root", required=True, help="exact artifact store root")
    command.add_argument("--ref", required=True, help="exact sha256:<digest> reference")
    modes = command.add_subparsers(dest="mode", required=True)
    for name in ("index", "page"):
        mode = modes.add_parser(name)
        mode.add_argument("--cursor", type=int, default=0)
        mode.add_argument("--limit", type=int, default=artifact_query.DEFAULT_LIMIT)
    pointer = modes.add_parser("pointer")
    pointer.add_argument("--pointer", required=True, help="RFC 6901 JSON pointer")
    pointer.add_argument("--cursor", type=int, default=0)
    pointer.add_argument("--limit", type=int, default=artifact_query.DEFAULT_LIMIT)
    search = modes.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--cursor", type=int, default=0)
    search.add_argument("--limit", type=int, default=artifact_query.DEFAULT_LIMIT)
    return command


def run(args: argparse.Namespace) -> str:
    artifact_query.validate_bounds(args.cursor, args.limit)
    text = load_artifact(args.root, args.ref)
    if args.mode == "index":
        return artifact_query.index(args.ref, text, args.cursor, args.limit)
    if args.mode == "page":
        return artifact_query.page(args.ref, text, args.cursor, args.limit)
    if args.mode == "pointer":
        return artifact_query.pointer(args.ref, text, args.pointer, args.cursor, args.limit)
    return artifact_query.search(args.ref, text, args.query, args.cursor, args.limit)


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        # INV-ARTIFACT-001: stdout has no trailing newline, so --limit covers every
        # serialized character emitted on the successful output channel.
        sys.stdout.write(run(args))
    except artifact_query.ArtifactQueryError as exc:
        message = str(exc)
    except OSError:
        message = "Artifact I/O failure"
    else:
        return
    error = json.dumps(
        {"contract": artifact_query.CONTRACT, "error": message},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stderr.write(error)
    raise SystemExit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
