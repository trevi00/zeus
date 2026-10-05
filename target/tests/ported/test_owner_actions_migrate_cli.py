# Ported from SOURCE M7 tests/test_owner_actions_migrate_cli.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""`zeus owner-actions migrate --document FILE` executed through the real CLI dispatch
(INV-OWNER-ACTIONS-MIGRATION-001): the real `cli.owner_actions_command` -> `execute` ->
`OwnerActions.request_migration`, its emitted JSON and exit code. Only the Fleet registration read and
the coordinator's external ports are replaced (labelled below); no Git, host, lane or model is touched.
"""
from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from unittest import mock

import pytest
from m7_coordination import OwnerActions, organization

from codex_harness.entry.cli import owner_actions as adapter  # S11 M B5: M7 adapters.owner_actions (the parser and the command body)
from codex_harness.storage.adapters.memory_store import MemoryStore

# S11 M B5: the M7 coordinator carried `.request_migration`; the target's owner exposes the split `.migration` owner, and the
# ported OwnerActions facade keeps its split objects in `.objects`.
REGISTERED = "codex_harness.coordination.application.fleet.registry.FleetRegistry.registered"
SETTINGS = "codex_harness.composition.configuration.settings"  # S11 M B5: M7 adapters.configuration.settings


def routed(owner):
    return SimpleNamespace(migration=owner.objects["migration"], canary=owner.objects["canary"])

DOCUMENT_KEYS = ("policy_id", "intent_id", "lane", "target_id", "source_release_id", "source_policy_hash",
                 "candidate_revision", "old_plan_id", "old_plan_sha256", "approval", "evidence", "actor")


@pytest.fixture
def service(monkeypatch):
    store = MemoryStore()
    # LABELLED: the Fleet registration read and the coordinator's external ports (lanes, Git
    # publisher, target files) are replaced; the OwnerActions the CLI drives is the real one.
    monkeypatch.setattr(REGISTERED, lambda self: {"config": {"lanes": []}})
    monkeypatch.setattr(SETTINGS, lambda: {})
    monkeypatch.setattr("codex_harness.composition.owner_actions.coordinator",
                        lambda svc, config, host, **ports: routed(OwnerActions(svc.store)))
    return SimpleNamespace(store=store, org=organization())


def run(service, path, capsys):
    args = argparse.Namespace(owner_actions_command="migrate", document=str(path))
    code = 0
    try:
        # S11 M B5: M7 cli.owner_actions_command(service, args); the target command builds its service (composition.build), which is the double
        with mock.patch("codex_harness.composition.build", lambda: service):
            adapter.run(args)
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
    monkeypatch.setattr(REGISTERED, lambda self: {"config": {"lanes": []}})
    monkeypatch.setattr(SETTINGS, lambda: {})
    monkeypatch.setattr("codex_harness.composition.owner_actions.coordinator",
                        lambda svc, config, host, **ports: routed(w["owner"]))
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
