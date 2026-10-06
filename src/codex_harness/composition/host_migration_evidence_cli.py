"""The host migration operator CLI's evidence command: `observe-limited-active` (INV-HOST-MIGRATION-001).

Layer: composition
Owns: cli_ports, observe_command and the private _named_env, _schema, _lane_dsn, _archive
Does not own: the observation (`delivery.adapters.host_migration_evidence.observe`), the policy (`delivery.domain.host_migration_evidence`), the argument shape (`entry.processes.host_migration`) and `execute` (`composition.host_migration_cli`)
Entry points: observe_command, cli_ports
Contracts: INV-HOST-MIGRATION-001, INV-HOST-DELIVERY-VERIFY-001

Moved from M7 `adapters/host_migration_evidence.py` :735-826 (SOURCE e38aa722) by rule R-e5cd (S10 unit E5c, owner decision of resume 1): the CLI half S7 left out (`delivery/adapters/host_migration_evidence.py:6`). Bodies are M7's verbatim except these declared differences:
* `HostReader` requires `facts` and `processes` (S7 V6): `cli_ports` passes `facts=HostFacts()` (`host_os.adapters.host_facts`) and `processes=ChokepointProcesses()` (`host_os.adapters.process_groups`, as `composition.delivery_hosts`).
* M7's `Fleet(control).registered()` is the S5 split's `FleetRegistry(control).registered()` (`coordination.application.fleet.registry`).
* `ENV_NAME` and `MAX_ARCHIVE_BYTES` are M7's constants (:107, :94); the target evidence adapter does not export them. `IDENT` is `delivery.domain.host_migration`'s. `lane_dsn` is `coordination.adapters.fleet_runtime`'s; `LaneSnapshotStore` is `observation.adapters.collectors`'.
This module is a separate file so that both M7 `_schema` functions (this one and `composition.host_migration_cli._schema`) keep their names.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from codex_harness.delivery.adapters.host_migration_evidence import (
    HostReader,
    Ports,
    observe,
    validate_request,
)
from codex_harness.delivery.domain import host_migration_evidence as policy
from codex_harness.delivery.domain.host_migration import IDENT, MigrationRefused

MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


def _named_env(name, argument: str) -> str:
    """The value of a NAMED environment variable. A refusal names the argument, never what was given:
    a credential typed where a name belongs is never echoed."""
    if not (type(name) is str and ENV_NAME.fullmatch(name)):
        raise MigrationRefused("environment_name_invalid", argument)
    value = os.environ.get(name)
    if not value:
        raise MigrationRefused("environment_missing", argument)
    return value


def _schema(value, field_name: str) -> str:
    if not (type(value) is str and IDENT.fullmatch(value)) or value == "public":
        raise MigrationRefused("schema_invalid", field_name)
    return value


def _lane_dsn(value: str, schema: str, argument: str) -> str:
    """The snapshot connection string over one schema. libpq's parse errors quote the value they
    could not parse (a malformed DSN, or a credential in a variable named where a DSN belongs), so any
    failure names only the argument and carries no exception, message or traceback."""
    from codex_harness.coordination.adapters.fleet_runtime import lane_dsn

    try:
        return lane_dsn(value, schema)
    except Exception:  # noqa: BLE001 - every failure is the same refusal, with no text kept
        pass
    raise MigrationRefused("environment_invalid", argument) from None


def cli_ports(args) -> Ports:
    """Read-only snapshot stores over the stated schemas and the real host. Nothing connects here."""
    from codex_harness.host_os.adapters.host_facts import HostFacts
    from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
    from codex_harness.observation.adapters.collectors import LaneSnapshotStore

    schema, control_schema = _schema(args.schema, "schema"), _schema(args.control_schema, "control_schema")
    migration_dsn = _lane_dsn(_named_env(args.dsn_env, "dsn_env"), schema, "dsn_env")
    control_env = _named_env(args.control_dsn_env, "control_dsn_env")
    control_dsn = _lane_dsn(control_env, control_schema, "control_dsn_env")
    lane_id = args.lane

    def delivery(control):
        if lane_id is None:
            return control
        from codex_harness.coordination.application.fleet.registry import FleetRegistry

        lanes = [lane for lane in FleetRegistry(control).registered()["config"].get("lanes") or []
                 if lane.get("id") == lane_id]
        if len(lanes) != 1 or not (type(lanes[0].get("schema")) is str and IDENT.fullmatch(lanes[0]["schema"])):
            raise MigrationRefused(policy.UNAVAILABLE, "lane")
        schema = _schema(lanes[0]["schema"], "lane")
        return LaneSnapshotStore(_lane_dsn(control_env, schema, "control_dsn_env"), schema)

    return Ports(coordinator=LaneSnapshotStore(migration_dsn, schema),
                 control=LaneSnapshotStore(control_dsn, control_schema), delivery=delivery,
                 host=HostReader(facts=HostFacts(), processes=ChokepointProcesses()))


def _archive(path) -> dict:
    """The archived observation output named by `--expect`, read like every other file (bounded, no
    link, regular only). A refusal names the argument, never the path or the content."""
    if not (type(path) is str and Path(path).is_absolute()):
        raise MigrationRefused("request_invalid", "expect")

    def constant(name):
        raise ValueError(name)

    try:
        raw = HostReader.file(path, MAX_ARCHIVE_BYTES)
        document = None if raw is None else json.loads(raw, parse_constant=constant)
    except Exception:  # noqa: BLE001 - unreadable or not JSON is the same refusal
        document = None
    if not isinstance(document, dict):
        raise MigrationRefused(policy.EXPECT, "expect")
    return document


def observe_command(args, *, ports: Ports | None = None) -> tuple[dict, bool]:
    """`observe-limited-active`: the inputs, including an archive to compare against, are refused
    before anything else is read. The exit follows `ok`, or the comparison's `ok`."""
    request = {"migration_id": args.migration_id, "expected_id": args.expected_id, "target_id": args.target_id,
               "plan_id": args.plan_id, "actor": args.actor, "root": args.root, "config_file": args.config_file}
    validate_request(request)
    post_transition, expect_path = bool(getattr(args, "post_transition", False)), getattr(args, "expect", None)
    if post_transition and expect_path is None:
        raise MigrationRefused("request_invalid", "expect")
    expect = None if expect_path is None else _archive(expect_path)
    result = observe(request, ports or cli_ports(args), expect=expect, post_transition=post_transition)
    if "comparison" in result:
        return result, result["comparison"]["ok"]
    return result, result["observation"]["ok"]


__all__ = ["cli_ports", "observe_command"]
