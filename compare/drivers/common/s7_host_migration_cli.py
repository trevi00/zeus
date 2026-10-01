"""Shared S7 scenario steps (`delivery.host_migration_cli`): the in-process operator CLI of M7 `adapters/host_migration.py`
(`main(argv)` -> `execute` -> `_coordinator`, INV-HOST-MIGRATION-001), split out of `delivery.host_migration_transfer`
(S7 pilot 44, owner-authorized: the CLI is the S10 carry, so this family is REFERENCE-ONLY until S10).

Layer: harness (never shipped). Never imports `codex_harness`.

Two cases, moved whole from the transfer family with the same worlds and the same CLI calls:
- `switch.cli_successor_and_switch`: `switch_cli` (test_cli_records_a_successor_and_switches_only_with_an_expected_head);
- `switch.non_posix_refusal_cli`: the CLI part of the transfer family's `non_posix_refusal` (the CLI refuses before the store).

The fixtures, the helpers (`Ws`, `host`, `release`, `view`, `att`) and the normalization are the transfer module's, IMPORTED.
`api` is the transfer family's api (`main`, `patched`, `trace`, ...). Splitting is proven lossless by `split_check.py`.
"""

from __future__ import annotations

import contextlib
import io
import json
from types import SimpleNamespace

import s7_host_migration_transfer as T
import s7_host_migrations as HM

A = None  # the api of this run
MID, NEXT = HM.MID, T.NEXT
Ws, att, host, release, view = T.Ws, T.att, T.host, T.release, T.view


def cli(ws, argv) -> dict:
    """One in-process `main(argv)`: its exit code and the JSON it printed (normalized)."""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = A.main(list(argv))
    text = captured.getvalue()
    try:
        return {"exit": code, "json": ws.n(json.loads(text))}
    except ValueError:
        return {"exit": code, "text": ws.n(text)}


def switch_cli(ws):
    """test_cli_records_a_successor_and_switches_only_with_an_expected_head (in process, labelled doubles)."""
    coordinator, _, intent_id = HM.paused()
    h = host(ws, coordinator)
    document = ws.root / "successor.json"
    document.write_text(json.dumps(HM.successor(intent_id)))
    store = ["--dsn-env", "ZEUS_AIBOX_MIGRATION_DSN", "--schema", "zeus_aibox_migration"]
    out = {}
    with A.patched(_coordinator=lambda args: coordinator, recovery_preconditions=lambda control, managed: []):
        out["record"] = cli(ws, ["activation-successor", "--file", str(document), *store])
        head = out["record"]["json"]["successor_id"]
        out["replay"] = cli(ws, ["activation-successor", "--file", str(document), *store])
        paths = ["--migration-id", MID, "--control-dir", str(h.control), "--releases-dir", str(h.releases),
                 "--managed-state-dir", str(h.managed), *store]
        out["switch_without_expected_id"] = cli(ws, ["activation-switch", *paths])
        out["check"] = cli(ws, ["activation-switch", "--check", *paths])
        out["switch"] = cli(ws, ["activation-switch", "--expected-id", head, *paths])
        (h.control / "host-activation.json").write_text("{}\n")
        out["check_inconsistent"] = cli(ws, ["activation-switch", "--check", *paths])
    out["view"] = view(ws, h)
    return out


def switch_non_posix_cli(ws):
    """The CLI part of `non_posix_refusal`: `activation-switch` is refused by the platform check before the store."""
    coordinator, _, intent_id = HM.paused()
    h = SimpleNamespace(control=ws.root / "control", releases=ws.root / "releases", managed=ws.root / "managed",
                        calls=[], root=ws.root)
    for directory in (h.control, h.releases, h.managed):
        directory.mkdir()
    A.write_activation(h.control, coordinator.activation_document(MID))  # the intent's receipt
    release(ws.root, NEXT, seal=False)
    head = coordinator.record_successor(HM.successor(intent_id))["successor_id"]
    out = {}
    with A.patched(_posix=lambda: False), A.trace():
        paths = ["--migration-id", MID, "--control-dir", str(h.control), "--releases-dir", str(h.releases),
                 "--managed-state-dir", str(h.managed), "--dsn-env", "ZEUS_AIBOX_MIGRATION_DSN",
                 "--schema", "zeus_aibox_migration"]
        opened = []
        out["cli"] = {}
        with A.patched(_coordinator=lambda args: opened.append(1) or coordinator):
            for label, extra in (("expected_id", ["--expected-id", head]), ("check", ["--check"])):
                out["cli"][label] = cli(ws, ["activation-switch", *extra, *paths])
    out["coordinator_opened"] = opened
    return out


GROUPS = {"switch": [("cli_successor_and_switch", switch_cli), ("non_posix_refusal_cli", switch_non_posix_cli)]}


def run(api) -> dict:
    global A
    A = api
    T.A = api
    HM.A = api
    out = {}
    for group, cases in GROUPS.items():
        out[group] = {}
        for name, fn in cases:
            HM.STORES.clear()
            ws = Ws()
            try:
                try:
                    result = fn(ws)
                except Exception as exc:  # an unexpected failure of the characterized operation is itself compared
                    result = {"case_error": type(exc).__name__, "message": ws.n(str(exc))[:300]}
            finally:
                ws.close()
            out[group][name] = result
    return out
