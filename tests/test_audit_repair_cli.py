"""`zeus audit-repair enable|disable|inspect|status` (INV-AUDIT-REPAIR-001).

The parser and the dispatch are the real ones, and the owner runs over the real store and artifact
store. No subcommand here may create a task, publish a message, enter an executor, a transport or a
provider: an operator opt-in is an opt-in, and admission belongs to the existing audit service tick.
"""
from types import SimpleNamespace

import pytest
from test_audit_repair import (  # noqa: F401  imported fixtures register with pytest
    OPERATOR,
    SECRET,
    corrections_of,
    enabled_owner,
    owner,
    rejected_execution,
    repairable,
)
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    activate_fixture,
    audit,
)

from codex_harness import cli
from codex_harness.adapters import audit_repair_cli
from codex_harness.domain import audit_repair as domain_repair
from codex_harness.domain.model import canonical


def command(*argv):
    return cli.parser().parse_args(["audit-repair", *argv])


def run(ctx, repair, *argv):
    return audit_repair_cli.execute(ctx.service, command(*argv), repair=repair)


def test_the_parser_declares_the_four_owner_subcommands(repairable):  # noqa: F811
    enable = command("enable", "--audit-id", "a", "--task-id", "t", "--operator", "o")
    assert {key: value for key, value in vars(enable).items() if key != "repository"} == \
        vars(SimpleNamespace(command="audit-repair", audit_repair_command="enable", audit_id="a",
                             task_id="t", operator="o"))
    assert command("status", "--audit-id", "a").audit_repair_command == "status"
    assert command("inspect", "--audit-id", "a").task_id is None
    assert command("disable", "--audit-id", "a", "--operator", "o").operator == "o"
    with pytest.raises(SystemExit):     # every subcommand names its audit explicitly
        command("status")
    with pytest.raises(SystemExit):
        command("enable", "--audit-id", "a", "--task-id", "t")


def test_inspect_and_status_report_the_bounded_lineage_and_write_nothing(repairable):  # noqa: F811
    ctx = repairable
    task, ref = rejected_execution(ctx)
    repair = owner(ctx)
    report = run(ctx, repair, "inspect", "--audit-id", ctx.audit_id)

    assert report["exit_code"] == 0 and report["audit_repair"] == "inspect"
    assert report["enabled"] is False and report["candidates"][0]["eligible"] is True
    assert report["candidates"][0]["diagnosis"] == "missing_test_disposition"
    assert report["candidates"][0]["source_execution_ref"] == ref
    status = run(ctx, repair, "status", "--audit-id", ctx.audit_id)
    assert status["counts"] == {"attempted": 0, "admitted": 0, "repaired": 0, "deferred": 0,
                                "research_required": 0, "reconciliation_required": 0}
    assert status["corrections"] == [] and corrections_of(ctx) == []
    # Neither read created a lineage, an opt-in, a schedule key or a queued assignment.
    with ctx.store.transaction() as tx:
        assert [row for row in tx.scan("schedule") if row["id"].startswith("repair:")] == []
    assert SECRET not in canonical([report, status])


def test_enable_scopes_one_task_and_disable_closes_admission(repairable):  # noqa: F811
    ctx = repairable
    task, _ = rejected_execution(ctx)
    repair = owner(ctx)
    enabled = run(ctx, repair, "enable", "--audit-id", ctx.audit_id, "--task-id", task["id"],
                  "--operator", OPERATOR)
    assert enabled == {"audit_repair": "enable", "audit_id": ctx.audit_id, "enabled": True,
                       "scope": [task["id"]], "exit_code": 0}
    # The opt-in alone admits nothing: no lineage, no assignment, no schedule key.
    assert corrections_of(ctx) == []
    with ctx.store.transaction() as tx:
        assert [row for row in tx.scan("schedule") if row["id"].startswith("repair:")] == []
    admitted = repair.admit(ctx.audit_id)
    disabled = run(ctx, repair, "disable", "--audit-id", ctx.audit_id, "--operator", OPERATOR)
    assert disabled["enabled"] is False and disabled["scope"] == [task["id"]]
    status = run(ctx, repair, "status", "--audit-id", ctx.audit_id)
    assert status["counts"]["attempted"] == 1 and status["enabled"] is False
    correction = status["corrections"][0]
    assert correction["id"] == admitted["correction_id"] and correction["state"] == "admitted"
    assert correction["diagnosis"] == "missing_test_disposition"
    assert correction["successor_schedule_key"] == domain_repair.schedule_key(correction["id"])


@pytest.mark.parametrize("argv,code", [
    (("enable", "--audit-id", "absent", "--task-id", "t", "--operator", OPERATOR), "unknown_audit"),
    (("enable", "--audit-id", "AUDIT", "--task-id", "absent", "--operator", OPERATOR), "unknown_task"),
    (("disable", "--audit-id", "absent", "--operator", OPERATOR), "unknown_audit"),
])
def test_a_refusal_prints_a_code_and_a_type_only(repairable, argv, code):  # noqa: F811
    ctx = repairable
    rejected_execution(ctx)
    argv = tuple(ctx.audit_id if value == "AUDIT" else value for value in argv)
    result = run(ctx, owner(ctx), *argv)
    assert result == {"status": "refused", "reason_code": code, "error_type": "RepairRefused",
                      "exit_code": 1}


def test_the_cli_command_exits_nonzero_on_a_refusal_and_zero_on_a_read(repairable, capsys):  # noqa: F811
    ctx = repairable
    task, _ = rejected_execution(ctx)
    enabled_owner(ctx, task)
    cli.audit_repair_command(ctx.service, command("status", "--audit-id", ctx.audit_id))
    assert '"audit_repair": "status"' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.audit_repair_command(ctx.service, command(
            "enable", "--audit-id", "absent", "--task-id", task["id"], "--operator", OPERATOR))
    printed = capsys.readouterr().out
    assert '"reason_code": "unknown_audit"' in printed and SECRET not in printed
