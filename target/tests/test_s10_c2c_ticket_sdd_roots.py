"""S10 unit C2c: the ticket and sdd roots composed from `composition.cli_tickets` (DESIGN-s10 §3 C2, R-c9, R-c10).

Parity with M7 on a disposable PostgreSQL is the `entry.cli_ticket_sdd.pg` compare family; these tests cover what it
excludes (the networked and executor-dependent subcommands) and the builders' injected ports.
"""

import argparse
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import cli_tickets
from codex_harness.entry import cli
from codex_harness.entry.cli import sdd, ticket
from codex_harness.host_os.adapters import process_groups
from codex_harness.kernel.ids import SYSTEM_CLOCK, digest
from codex_harness.storage.adapters.memory_store import MemoryStore

CLI_DIR = Path(cli.__file__).resolve().parent
CONTENT = {"title": "Isolated verification", "problem": "Production and tests share endpoints", "impact": "Potential contention",
           "rollback": "Restore verified image", "evidence_refs": ["fixture:source-inspection"], "scope": ["deployment"],
           "acceptance_criteria": ["Independent services"], "verification": ["Run isolated service integration test"]}


class Spawned(Exception):
    pass


@pytest.fixture
def repository(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path))
    return tmp_path


@pytest.fixture
def service(monkeypatch, repository):
    handle = composition.ServiceHandle(MemoryStore(), _org())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return handle


def _org():
    from codex_harness.routing.adapters.organization_source import packaged_organization
    return packaged_organization()


@pytest.fixture
def recorder(monkeypatch):
    calls = []

    def fake(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(process_groups, "run_process", fake)
    return calls


def args_of(parser_module, *argv):
    root = argparse.ArgumentParser(prog="zeus")
    parser_module.add_parser(root.add_subparsers(dest="command", required=True))
    return root.parse_args(list(argv))


def dispatch_keys() -> list[str]:
    tree = ast.parse((CLI_DIR / "__init__.py").read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    return [key.value for key in tables[0].value.keys]


def test_the_dispatch_table_holds_ticket_and_sdd():
    assert {"ticket", "sdd"} <= set(dispatch_keys())


def test_ticket_dispatch_refuses_until_unit_c5_r_c9(service, recorder, tmp_path):
    ticket_id = cli_tickets.tickets(service).create(CONTENT)["id"]
    with pytest.raises(RuntimeError, match=r"^zeus ticket dispatch is composed in S10 unit C5$"):
        ticket.run(args_of(ticket, "ticket", "dispatch", ticket_id, "--revision", "1"))
    assert recorder == []


def test_the_main_shell_reports_the_dispatch_refusal_as_an_error_document(service, recorder, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["zeus", "ticket", "dispatch", "ZEUS-x", "--revision", "1"])
    with pytest.raises(SystemExit) as exit_:
        cli.main()
    assert exit_.value.code == 1
    assert json.loads(capsys.readouterr().err) == {"error": "zeus ticket dispatch is composed in S10 unit C5"}


def test_ticket_sync_reaches_github_through_the_injected_run_process_r_c10(service, recorder):
    ticket_id = cli_tickets.tickets(service).create(CONTENT)["id"]
    with pytest.raises(RuntimeError, match="GitHub issue operation failed"):
        ticket.run(args_of(ticket, "ticket", "sync", ticket_id, "--repo", "owner/name"))
    argv, kwargs = recorder[0]
    assert argv[:3] == ["gh", "issue", "list"] and "owner/name" in argv and kwargs == {"timeout": 60}


def test_ticket_pull_reads_the_linked_issue_through_the_injected_run_process_r_c10(service, recorder):
    ticket_id = cli_tickets.tickets(service).create(CONTENT)["id"]
    key = digest({"ticket_id": ticket_id, "repository": "owner/name"})
    with service.store.transaction() as tx:
        tx.put("ticket_github", key, {"number": 7, "synced_revision": 1})
    with pytest.raises(RuntimeError, match="GitHub issue operation failed"):
        ticket.run(args_of(ticket, "ticket", "pull", ticket_id, "--repo", "owner/name"))
    argv, kwargs = recorder[0]
    assert argv == ["gh", "issue", "view", "7", "--repo", "owner/name", "--json", "number,url,title,body,state,comments"]
    assert kwargs == {"timeout": 60}


def test_sync_preview_prints_the_projection_and_never_spawns(service, recorder, capsys):
    ticket_id = cli_tickets.tickets(service).create(CONTENT)["id"]
    ticket.run(args_of(ticket, "ticket", "sync", ticket_id, "--repo", "owner/name", "--preview"))
    assert capsys.readouterr().out.startswith("<!-- zeus-ticket:" + ticket_id + " -->")
    assert recorder == []


def test_device_check_runs_adb_through_the_injected_run_process_r_c10(repository, recorder, tmp_path, monkeypatch):
    adb = tmp_path / "tools" / "adb"
    adb.parent.mkdir()
    adb.write_text("#!/bin/sh\n", encoding="utf-8")
    adb.chmod(0o755)
    monkeypatch.setenv("PATH", str(adb.parent))
    report = cli_tickets.device_probe()
    assert recorder == [([str(adb), "devices", "-l"], {"timeout": 20})]
    assert report["status"] == "unavailable" and report["acceptance_passed"] is False


def test_device_check_without_adb_blocks_without_spawning(repository, recorder, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli_tickets.device_probe()["status"] == "blocked" and recorder == []


def test_builders_inject_their_ports(service, repository):
    tickets = cli_tickets.tickets(service)
    assert tickets.outbox is not None and tickets.store is service.store
    life = cli_tickets.ticket_lifecycle(tickets)
    assert life.authority.run_process is process_groups.run_process
    assert life.authority.git.repository == repository.resolve()
    assert life.artifacts.root == (repository / ".runtime" / "artifacts").resolve()
    github = cli_tickets.github_tickets(tickets, life)
    assert github.run_process is process_groups.run_process and github.lifecycle is life and github.artifacts is life.artifacts
    iterations = cli_tickets.sdd(service)
    assert iterations.clock is SYSTEM_CLOCK and callable(iterations.ticket_binding) and iterations.store is service.store


def test_read_spec_binds_the_repository_root_and_run_process(repository, recorder):
    spec = {"schema": "zeus.sdd.v1"}
    path = repository / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(Exception):  # an incomplete spec is refused by the domain rule, after the root was bound
        cli_tickets.read_spec(path)
    with pytest.raises(Exception, match="Spec Git revision unavailable"):
        cli_tickets.read_spec(path, "HEAD")
    assert recorder[0][0] == ["git", "rev-parse", "--verify", "HEAD^{commit}"]
    assert recorder[0][1] == {"cwd": str(repository.resolve())}


def test_sdd_run_emits_the_result(repository, service, capsys):
    path = repository / "bad.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(Exception):
        sdd.run(args_of(sdd, "sdd", "inspect", str(path)))
    assert capsys.readouterr().out == ""
