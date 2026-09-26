"""`zeus dge register|submit|status`: thin wiring around DebateSessions (INV-DGE-001).

Register verifies every pinned source through git argv at the packet's base revision before the
PostgreSQL row exists; submit and status touch the store only. No provider, bus, budget, observer
or knowledge adapter is built by any of these commands.
"""
from __future__ import annotations

from pathlib import Path

from codex_harness.adapters.operation_cli import (
    MAX_MANIFEST_BYTES,
    GitSource,
    read_document,
    refusal,
)
from codex_harness.application.dge import DebateSessions, DgeRefused
from codex_harness.domain.dge import source_binding, validate_packet
from codex_harness.domain.model import ContractError, digest

MAX_DOCUMENT_BYTES = MAX_MANIFEST_BYTES  # read_document is operation_cli's one shared operator JSON reader


def repository_identity(repository) -> str:
    """The same resolved-repository digest `operate` records in its identity, so the claim-time
    gate compares like with like; the path itself is never stored."""
    return digest(str(Path(repository).resolve()))


def verify_sources(packet: dict, source: GitSource) -> list:
    """Every source must be a regular blob at base whose bytes hash to the pinned digest.
    Directories, symlinks and submodules are not regular blobs and are refused."""
    if not source.commit_exists(packet["base_revision"]):
        raise DgeRefused("base_revision_missing")
    bound = []
    for entry in packet["sources"]:
        mode, data = source.blob(packet["base_revision"], entry["path"])
        if mode is None:
            raise DgeRefused("source_missing_at_base")
        try:
            bound.append(source_binding(entry, mode, data))
        except ContractError as exc:
            raise DgeRefused("source_not_regular" if mode != "100644" else "source_digest_mismatch") from exc
    return bound


def register(service, args) -> dict:
    from codex_harness.adapters.configuration import repository_root
    packet = validate_packet(read_document(args.file, "Research packet"))
    repository = repository_root()
    bound = verify_sources(packet, GitSource(repository))
    result = DebateSessions(service.store).register(packet, repository_identity(repository), bound)
    return {"status": "registered", "cached": result["cached"], "exit_code": 0,
            "session": DebateSessions._safe(result["session"])}


def submit(service, args) -> dict:
    event = read_document(args.file, "Debate event")
    result = DebateSessions(service.store).submit(args.session_id, event)
    return {**result, "exit_code": 0}


def status(service, args) -> dict:
    # Store read only: no executor, observer, bus, budget or provider is built.
    return {**DebateSessions(service.store).status(args.session_id), "exit_code": 0}


def add_parser(commands) -> None:
    dge = commands.add_parser("dge", help="Research-bound design control: register packet, submit debate event, status")
    sub = dge.add_subparsers(dest="dge_command", required=True)
    reg = sub.add_parser("register", help="Verify pinned sources through git and register the packet (urn:zeus:research-packet:1)")
    reg.add_argument("--file", type=Path, required=True)
    put = sub.add_parser("submit", help="Record one operator-submitted debate event (urn:zeus:debate-event:1)")
    put.add_argument("session_id")
    put.add_argument("--file", type=Path, required=True)
    show = sub.add_parser("status", help="Safe session summary; store read only")
    show.add_argument("session_id")


def execute(service, args) -> dict:
    """Fixed-code failure rendering; exit 0 only for a recorded, replayed or read result."""
    try:
        if args.dge_command == "register":
            return register(service, args)
        if args.dge_command == "submit":
            return submit(service, args)
        return status(service, args)
    except Exception as exc:
        return refusal(exc)
