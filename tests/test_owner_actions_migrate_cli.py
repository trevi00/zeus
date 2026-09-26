"""`zeus owner-actions migrate --document FILE` executed through the real CLI dispatch
(INV-OWNER-ACTIONS-MIGRATION-001): the real `cli.owner_actions_command` -> `execute` ->
`OwnerActions.request_migration`, its emitted JSON and exit code. Only the Fleet registration read and
the coordinator's external ports are replaced (labelled below); no Git, host, lane or model is touched.
"""
from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from codex_harness import cli
from codex_harness.adapters import owner_actions as adapter
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.owner_actions import OwnerActions
from codex_harness.bootstrap import organization

DOCUMENT_KEYS = ("policy_id", "intent_id", "lane", "target_id", "source_release_id", "source_policy_hash",
                 "candidate_revision", "old_plan_id", "old_plan_sha256", "approval", "evidence", "actor")


@pytest.fixture
def service(monkeypatch):
    store = MemoryStore()
    # LABELLED: the Fleet registration read and the coordinator's external ports (lanes, Git
    # publisher, target files) are replaced; the OwnerActions the CLI drives is the real one.
    monkeypatch.setattr("codex_harness.application.fleet.Fleet.registered",
                        lambda self: {"config": {"lanes": []}})
    monkeypatch.setattr("codex_harness.adapters.configuration.settings", lambda: {})
    monkeypatch.setattr(adapter, "coordinator", lambda svc, config, host: OwnerActions(svc.store))
    return SimpleNamespace(store=store, org=organization())


def run(service, path, capsys):
    args = argparse.Namespace(owner_actions_command="migrate", document=str(path))
    code = 0
    try:
        cli.owner_actions_command(service, args)
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(capsys.readouterr().out)


def document(**changes):
    body = {key: "x" for key in DOCUMENT_KEYS}
    body.update(approval={"source_release_id": "x", "base": "b" * 40, "evaluator_revision": "e" * 40,
                          "evaluator_tree": "f" * 40, "patch_sha256": "a" * 64,
                          "paths": ["tests/test_host_migration.py"], "evidence": "sha256:" + "c" * 64,
                          "approved_by": "conductor"},
                evidence="sha256:" + "c" * 64)
    body.update(changes)
    return body


def test_an_unreadable_document_is_a_named_refusal_with_exit_1(service, tmp_path, capsys):
    missing = tmp_path / "absent.json"
    code, out = run(service, missing, capsys)
    assert code == 1 and out["reason_code"] == "migration_document_unreadable"
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code, out = run(service, broken, capsys)
    assert code == 1 and out["reason_code"] == "migration_document_unreadable"


def test_a_malformed_document_is_refused_by_the_real_validation_and_writes_nothing(service, tmp_path, capsys):
    path = tmp_path / "doc.json"
    body = document()
    del body["actor"]
    path.write_text(json.dumps(body), encoding="utf-8")
    code, out = run(service, path, capsys)
    assert code == 1 and out["status"] == "refused" and out["reason_code"]
    assert out["error_type"] == "OwnerActionRefused"
    with service.store.transaction() as tx:
        assert tx.scan("owner_action_migrations") == []


def test_a_well_formed_document_without_its_control_records_is_refused_without_a_write(service, tmp_path,
                                                                                     capsys):
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(document()), encoding="utf-8")
    code, out = run(service, path, capsys)
    assert code == 1 and out["status"] == "refused" and out["reason_code"] not in {None, "error"}
    with service.store.transaction() as tx:
        assert tx.scan("owner_action_migrations") == []


def test_the_parser_names_the_migrate_command():
    parser = argparse.ArgumentParser()
    adapter.add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["owner-actions", "migrate", "--document", "d.json"])
    assert args.owner_actions_command == "migrate" and args.document == "d.json"


def test_a_valid_document_is_recorded_once_through_the_cli_replays_and_refuses_another(monkeypatch, tmp_path,
                                                                                      capsys):
    from test_owner_actions_migration import document as migration_document
    from test_owner_actions_migration import world

    w = world()  # the real OwnerActions over its own control records; lane/Git/target ports are labelled fakes
    monkeypatch.setattr("codex_harness.application.fleet.Fleet.registered", lambda self: {"config": {"lanes": []}})
    monkeypatch.setattr("codex_harness.adapters.configuration.settings", lambda: {})
    monkeypatch.setattr(adapter, "coordinator", lambda svc, config, host: w["owner"])
    service = SimpleNamespace(store=w["control"], org=organization())
    path = tmp_path / "migration.json"
    path.write_text(json.dumps(migration_document(w)), encoding="utf-8")
    code, first = run(service, path, capsys)
    assert code == 0 and first["cached"] is False and first["exit_code"] == 0
    code, again = run(service, path, capsys)
    assert code == 0 and again["cached"] is True
    path.write_text(json.dumps(migration_document(w, actor="lead:other")), encoding="utf-8")
    code, refused = run(service, path, capsys)
    assert code == 1 and refused["reason_code"] == "migration_conflict"
    with w["control"].transaction() as tx:
        assert len(tx.scan("owner_action_migrations")) == 1
