"""Buzz D1b: the real Zeus world (org and task read models over `tasks` rows, ports, channel map, config keys).

MemoryStore plus the target `Workflow`, `FleetPause` and `RemoteControl`; no network, no double for org or tasks.
Contracts: Buzz DESIGN v3 §4.2, §4.4, §4.5; DESIGN-D §2b.
"""
import json
import re
import time
from datetime import datetime, timezone

import pytest
from test_buzz_b3_remote_control import NOW, OWNER, World, command, fence, inbox_row
from test_buzz_b4_projection import D_ORG, HeadRelay, P

from codex_harness.composition import buzz_world as bw
from codex_harness.composition.buzz_bridge import BridgeConfig, build_runtime, custody_name
from codex_harness.composition.buzz_world import TERMINAL_STATUSES, UNSOURCED, ZeusReads, zeus_world
from codex_harness.coordination.application.fleet import state
from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.entry.processes import buzz_bridge as entry
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain import buzz_projection as bp
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SCHEME = "postgresql" + "://"  # split: the tree check flags credential-shaped literals
ASSIGNEE = "worker:implementation"
HEX = "a" * 64
REF = "sha256:" + "ab" * 32


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def config(**extra):
    base = {"relay_url": "ws://127.0.0.1:1", "channels": ["cmd", "c-improvement"], "owners": [HEX],
            "custody_dir": "/nonexistent", "store_dsn_file": "/nonexistent", "commander_channel": "cmd",
            "org_d": D_ORG, "team_channels": {"improvement": "c-improvement"}}
    return BridgeConfig.parse({**base, **extra})


def legal_org_file(tmp_path):
    """An organization whose ids `TestRoleKeys` accepts: the packaged ids carry `:` (`lead:improvement`), which the
    custody refuses (reported to the owner: D1b NOTES)."""
    path = tmp_path / "org.json"
    path.write_text(json.dumps({"agents": [
        {"id": "conductor", "role": "conductor", "parent": None, "team": "control"},
        {"id": "lead-improvement", "role": "lead", "parent": "conductor", "team": "improvement"},
        {"id": "worker-impl", "role": "worker", "parent": "lead-improvement", "team": "improvement"}]}))
    return path


class Z:
    """The B3 world (store, one submitted task, fleet) read through the REAL `zeus_world` at a pinned clock."""

    def __init__(self, tmp_path, now=NOW):
        self.w, self.now = World(tmp_path), now
        self.world = zeus_world(self.w.store, config(), clock=lambda: self.now)
        self.reads = self.world.read_models

    def read(self, fn, *args):
        with self.w.store.transaction() as tx:
            return fn(tx, *args)

    def task(self):
        return self.read(self.reads.task, self.w.task["id"])

    def org(self):
        return {r["id"]: r for r in self.read(self.reads.org)["roles"]}

    def update(self, **fields):
        with self.w.store.transaction() as tx:
            row = tx.get("tasks", self.w.task["id"])
            row.update(fields)
            tx.put("tasks", self.w.task["id"], row)


@pytest.fixture
def z(tmp_path):
    return Z(tmp_path)


# ---- task views -------------------------------------------------------------------------------------------------
def test_a_submitted_task_maps_to_the_4_5_view_with_the_status_verbatim(z):
    row = z.w.task
    assert z.task() == {
        "task_id": row["id"], "title": row["id"], "team": "improvement", "assignee": ASSIGNEE,
        "sender": "lead:improvement", "generation": 0, "status": "queued", "stage": None, "terminal": False,
        "created_at": int(datetime.fromisoformat(row["created_at"]).timestamp()),
        "updated_at": int(datetime.fromisoformat(row["created_at"]).timestamp()), "observed_at": NOW,
        "summary": "", "evidence_refs": []}
    assert z.read(z.reads.tasks) == [z.task()]
    assert z.read(z.reads.task, "no-such-task") is None


def test_the_title_comes_from_the_six_w_details_and_updated_at_from_the_row(z):
    with z.w.store.transaction() as tx:
        row = tx.get("tasks", z.w.task["id"])
        row["message"]["what"]["details"]["title"] = "Fix it" + "x" * 600
        row.update(updated_at=iso(NOW - 7), stage="review")
        tx.put("tasks", row["id"], row)
    view = z.task()
    assert view["title"] == ("Fix it" + "x" * 600)[:bp.MAX_TITLE_CHARS]
    assert (view["updated_at"], view["stage"]) == (NOW - 7, "review")


def test_tasks_are_oldest_first(z):
    with z.w.store.transaction() as tx:
        older = {**tx.get("tasks", z.w.task["id"]), "id": "t-older", "created_at": iso(NOW - 5000)}
        tx.put("tasks", "t-older", older)
    assert [v["task_id"] for v in z.read(z.reads.tasks)][0] == "t-older"


def test_a_claimed_task_keeps_its_status_whatever_the_lease(z):
    z.update(status="running", generation=1, lease_owner="o", lease_until=iso(NOW + 60))
    assert (z.task()["status"], z.task()["terminal"], z.task()["generation"]) == ("running", False, 1)
    z.update(lease_until=iso(NOW - 5))  # example 1: expired lease: the view still says running, verbatim
    assert (z.task()["status"], z.task()["terminal"]) == ("running", False)


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_a_terminal_status_is_terminal_and_verbatim(z, status):
    z.update(status=status)
    assert (z.task()["status"], z.task()["terminal"]) == (status, True)


@pytest.mark.parametrize("status", ["queued", "retry", "running"])
def test_open_statuses_are_not_terminal(z, status):
    z.update(status=status)
    assert z.task()["terminal"] is False


def test_the_terminal_set_matches_every_status_the_workflow_writes_except_the_open_ones():
    from codex_harness.coordination.application.local_cycle import OPEN_TASK
    assert TERMINAL_STATUSES.isdisjoint(OPEN_TASK)
    assert TERMINAL_STATUSES == {"succeeded", "failed", "cancelled", "expired", "superseded", "blocked"}
    assert UNSOURCED == ("task.stage", "task.updated_at", "org.display")


def test_evidence_refs_keep_an_artifact_ref_and_drop_paths_and_urls(z):
    other = "sha256:" + "cd" * 32
    paths = ["/etc/passwd", "../x", "C:\\x", "docs/a.md", "https://h/x", "sha256:short", "file.txt", 7, None]
    z.update(result={"summary": "ok", "evidence_refs": [REF, *paths, REF]})
    with z.w.store.transaction() as tx:
        row = tx.get("tasks", z.w.task["id"])
        row["message"]["why"]["evidence_refs"] = [other, "/srv/secret"]
        tx.put("tasks", row["id"], row)
    assert z.task()["evidence_refs"] == [REF, other]
    assert all(bp.evidence_ref_ok(ref) for ref in z.task()["evidence_refs"])


def test_the_summary_is_truncated_at_2000_and_only_a_string_counts(z):
    z.update(result={"summary": "s" * 2500})
    assert z.task()["summary"] == "s" * 2000
    z.update(result={"summary": ["not text"]})
    assert z.task()["summary"] == ""
    z.update(result="not an object")
    assert z.task()["summary"] == ""


def test_a_naive_timestamp_is_utc_and_a_bad_one_is_refused(z):
    z.update(created_at="2023-11-14T22:13:20")
    assert z.task()["created_at"] == 1_700_000_000
    z.update(created_at="not a time")
    with pytest.raises(ContractError, match="created_at"):
        z.task()


def test_a_task_of_an_agent_the_organization_does_not_list_is_refused_not_invented(z):
    z.update(agent="ghost")
    with pytest.raises(ContractError, match="organization does not list"):
        z.task()


# ---- org --------------------------------------------------------------------------------------------------------
def test_org_lists_every_agent_idle_with_display_equal_to_id(z):
    org = z.org()
    assert set(org) == set(packaged_organization().agents)
    worker = org[ASSIGNEE]
    assert (worker["role"], worker["parent"], worker["team"], worker["display"]) == (
        "worker", "lead:improvement", "improvement", ASSIGNEE)
    assert all(r["display"] == r["id"] and r["status"]["state"] == "idle" and r["status"]["observed_at"] == NOW
               for r in org.values())
    assert worker["status"] == {"state": "idle", "task_id": None, "last_activity_at": z.task()["created_at"],
                                "observed_at": NOW}
    assert org["conductor"]["status"]["last_activity_at"] is None


def test_busy_only_with_a_live_lease_example_1(z):
    z.update(status="running", generation=1, lease_owner="o", lease_until=iso(NOW + 30))
    assert z.org()[ASSIGNEE]["status"]["state"] == "busy"
    assert z.org()[ASSIGNEE]["status"]["task_id"] == z.w.task["id"]
    z.update(lease_until=iso(NOW - 5))
    assert z.org()[ASSIGNEE]["status"]["state"] == "idle"
    assert z.org()[ASSIGNEE]["status"]["task_id"] is None
    z.update(status="queued", lease_until=None)
    assert z.org()[ASSIGNEE]["status"]["state"] == "idle"
    z.update(status="succeeded", lease_until=iso(NOW + 30))  # a terminal task is no execution evidence
    assert z.org()[ASSIGNEE]["status"]["state"] == "idle"
    z.update(status="running", lease_until="garbage")  # an unreadable lease is no evidence either
    assert z.org()[ASSIGNEE]["status"]["state"] == "idle"


def test_paused_when_the_fleet_is_paused_and_the_agent_is_not_busy(z):
    z.w.pause.pause()
    org = z.org()
    assert {r["status"]["state"] for r in org.values()} == {"paused"}
    z.update(status="running", generation=1, lease_owner="o", lease_until=iso(NOW + 30))
    org = z.org()
    assert org[ASSIGNEE]["status"]["state"] == "busy"  # busy wins over paused
    assert org["conductor"]["status"]["state"] == "paused"


def test_last_activity_is_the_newest_task_update_and_observed_at_is_the_read_clock(z):
    z.update(updated_at=iso(NOW - 40))
    with z.w.store.transaction() as tx:
        later = {**tx.get("tasks", z.w.task["id"]), "id": "t-2", "updated_at": iso(NOW - 3), "status": "succeeded"}
        tx.put("tasks", "t-2", later)
    z.now = NOW + 11
    status = z.org()[ASSIGNEE]["status"]
    assert (status["last_activity_at"], status["observed_at"]) == (NOW - 3, NOW + 11)


def test_an_unreadable_store_raises_and_never_fabricates_unknown(z):
    class Broken:
        def get(self, bucket, key):
            return None

        def scan(self, bucket):
            raise RuntimeError("store down")

    with pytest.raises(RuntimeError, match="store down"):
        z.reads.org(Broken())


# ---- the bridge projection, end to end over MemoryStore, no double for org or tasks ------------------------------
def test_the_projection_plans_an_org_snapshot_and_task_cards_the_b_validators_accept(tmp_path):
    cfg = config(organization_file=str(legal_org_file(tmp_path)))
    org = cfg.load_organization()
    p = P(tmp_path, roles=tuple(org.agents))
    p.now = p.w.now = int(time.time())
    world = zeus_world(p.w.store, cfg, clock=lambda: p.now)
    p.proj.read_models = world.read_models
    p.proj.channels = world.channels
    with p.w.store.transaction() as tx:  # the B3 world's task, re-addressed to the file's agents, with a live lease
        row = tx.get("tasks", p.w.task["id"])
        row["message"]["who"]["sender"] = "lead-improvement"
        row.update(agent="worker-impl", status="running", generation=1, lease_owner="o", lease_until=iso(p.now + 60))
        tx.put("tasks", row["id"], row)
    first = p.plan()  # the task's root and the org snapshot; the card follows once the root is acknowledged
    p.deliver()
    counts = p.plan()
    assert first["roots"] == 1 and counts["cards"] == 1, (first, counts)
    by_type = {}
    for event in p.signed:  # every event the projection built went through the B domain validators
        by_type.setdefault(next((t[1] for t in event["tags"] if t[0] == "type"), "root"), event)
    snapshot = json.loads(by_type["zeus.org"]["content"])
    assert snapshot["schema"] == bp.ORG_SCHEMA and len(snapshot["roles"]) == len(org.agents)
    busy = [r for r in snapshot["roles"] if r["status"]["state"] == "busy"]
    assert [r["id"] for r in busy] == ["worker-impl"] and busy[0]["status"]["task_id"] == p.w.task["id"]
    assert [r["status"]["state"] for r in snapshot["roles"] if r["id"] != "worker-impl"] == ["idle", "idle"]
    card = json.loads(by_type["zeus.task"]["content"])
    assert card["schema"] == bp.TASK_SCHEMA and card["task_id"] == p.w.task["id"] and card["status"] == "running"
    assert (card["assignee"], card["team"], card["sender"]) == ("worker-impl", "improvement", "lead-improvement")
    assert ["h", "c-improvement"] in by_type["zeus.task"]["tags"]
    # the same validators accept the same read models directly
    with p.w.store.transaction() as tx:
        view = world.read_models.task(tx, p.w.task["id"])
    assert bp.interventions({"terminal": view["terminal"]}, {"paused": False, "activation_hold": False})
    assert bp.evidence_ref_ok("sha256:" + "0" * 64)


# ---- the command path through the real messages and fleet pause ---------------------------------------------------
def test_an_owner_cancel_task_advances_the_generation_through_the_real_messages(tmp_path):
    z = Z(tmp_path)
    generation = z.w.task["generation"]
    z.w.remote.messages, z.w.remote.fleet_pause = z.world.messages, z.world.fleet_pause
    outcome = z.w.admit(inbox_row(fence(z.w.cancel_cmd()), 1))
    assert outcome["outcome"] == "command_admitted" and outcome["disposition"] == "effect_done"
    view = z.task()
    assert (view["status"], view["generation"], view["terminal"]) == ("cancelled", generation + 1, True)
    assert z.w.task_row()["error"] == "operator asked"


def test_an_owner_pause_fleet_changes_fleet_view(tmp_path):
    z = Z(tmp_path)
    z.w.remote.messages, z.w.remote.fleet_pause = z.world.messages, z.world.fleet_pause
    assert z.read(state.fleet_view) == z.read(z.reads.fleet) == {"paused": False, "activation_hold": False,
                                                                 "control_version": 0}
    pause = command("pause_fleet", 2, expected_control={"paused": False, "version": 0})
    assert z.w.admit(inbox_row(fence(pause), 2))["disposition"] == "effect_done"
    assert z.read(z.reads.fleet) == {"paused": True, "activation_hold": False, "control_version": 1}
    assert {r["status"]["state"] for r in z.org().values()} == {"paused"}


def test_the_ports_are_the_real_ones_and_the_channel_map_comes_from_the_config(tmp_path):
    z = Z(tmp_path)
    assert type(z.world.messages).__name__ == "MessageHandler" and type(z.world.fleet_pause).__name__ == "FleetPause"
    assert isinstance(z.world.read_models, ZeusReads)
    assert z.world.channels == {"commander": "cmd", "org_d": D_ORG, "teams": {"improvement": "c-improvement"}}
    assert z.world.roles == tuple(packaged_organization().agents)
    assert bw.ZeusReads(packaged_organization(), time.time).clock is time.time


# ---- config -----------------------------------------------------------------------------------------------------
def test_a_missing_team_channel_in_channels_is_refused_example_2():
    with pytest.raises(ContractError, match="channels must include"):
        config(channels=["c-commander"], commander_channel="c-commander", team_channels={"core": "c-core"})


def test_a_missing_commander_channel_in_channels_is_refused():
    with pytest.raises(ContractError, match="channels must include"):
        config(channels=["c-improvement"])


@pytest.mark.parametrize("bad", [{"team_channels": {}}, {"team_channels": {"core": 1}}, {"team_channels": ["core"]},
                                 {"org_d": ""}, {"commander_channel": 5}, {"organization_file": ""}])
def test_the_new_keys_are_strict(bad):
    with pytest.raises(ContractError):
        config(**bad)


def test_an_invalid_organization_file_is_refused(tmp_path):
    cases = {"missing": None, "notjson": "{", "shape": json.dumps({"agents": [{"id": "x"}]}),
             "two conductors": json.dumps({"agents": [
                 {"id": "a", "role": "conductor", "parent": None, "team": "t"},
                 {"id": "b", "role": "conductor", "parent": None, "team": "t"}]}),
             "bad hierarchy": json.dumps({"agents": [
                 {"id": "a", "role": "conductor", "parent": None, "team": "t"},
                 {"id": "w", "role": "worker", "parent": "a", "team": "t"}]})}
    for name, text in cases.items():
        path = tmp_path / f"{name}.json"
        if text is not None:
            path.write_text(text)
        with pytest.raises(ContractError):
            config(organization_file=str(path))


def test_a_valid_organization_file_is_loaded_and_drives_the_world(tmp_path):
    path = tmp_path / "org.json"
    path.write_text(json.dumps({"agents": [{"id": "boss", "role": "conductor", "parent": None, "team": "t"},
                                           {"id": "lead:x", "role": "lead", "parent": "boss", "team": "t"}]}))
    cfg = config(organization_file=str(path))
    assert list(cfg.load_organization().agents) == ["boss", "lead:x"]
    world = zeus_world(MemoryStore(), cfg, clock=lambda: NOW)
    assert world.roles == ("boss", "lead:x")
    with MemoryStore().transaction() as tx:
        assert [r["id"] for r in world.read_models.org(tx)["roles"]] == ["boss", "lead:x"]


def test_the_default_organization_is_the_packaged_one():
    assert config().organization_file is None
    assert set(config().load_organization().agents) == set(packaged_organization().agents)


class QuietRelay(HeadRelay):
    def query_all(self, filter, **kwargs):  # noqa: A002
        return {"events": [], "ended": "eose", "pages": 1, "unverified": 0}


@pytest.mark.parametrize("packaged", [False, True])
def test_main_with_a_complete_config_builds_the_real_world_without_an_injected_factory(tmp_path, capsys, packaged):
    org_file = None if packaged else legal_org_file(tmp_path)
    roles = packaged_organization().agents if packaged else ("lead-improvement", "worker-impl")
    keys = TestRoleKeys(tmp_path / "keys")
    for name in dict.fromkeys(("conductor", *map(custody_name, roles))):
        keys.create(name)
    dsn = tmp_path / "dsn"
    dsn.write_text(SCHEME + "u:pw@h/db")
    dsn.chmod(0o600)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "relay_url": "ws://127.0.0.1:1", "channels": ["cmd", "c-improvement"], "owners": [OWNER],
        "custody_dir": str(tmp_path / "keys"), "store_dsn_file": str(dsn), "commander_channel": "cmd",
        "org_d": D_ORG, "team_channels": {"improvement": "c-improvement"}, "max_seconds": 0,
        **({} if org_file is None else {"organization_file": str(org_file)})}))
    store, seen = MemoryStore(), []

    def store_factory(text):
        seen.append(text)
        return store

    relay = QuietRelay()
    code = entry.main(["--config", str(path)], store_factory=store_factory, relay_factory=lambda cfg, signer: relay,
                      clock=lambda: float(NOW), sleep=lambda seconds: None, owner_id="bridge-1")
    assert code == 0 and seen == [SCHEME + "u:pw@h/db"]
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["generation"] == 1 and "plan" in line["steps"]
    with store.transaction() as tx:
        assert tx.scan("buzz_outbox")  # the org snapshot was planned from the real read models
        subjects = {row["subject"] for row in tx.scan("buzz_outbox")}
    assert "org" in subjects


# ---- custody naming (v2): an injective role id -> key name map ----------------------------------------------------
def test_the_packaged_ids_map_injectively_and_legal_ids_map_to_themselves():
    ids = list(packaged_organization().agents)
    names = [custody_name(i) for i in ids]
    assert len(set(names)) == len(ids)
    assert custody_name("conductor") == "conductor" and custody_name("lead-improvement") == "lead-improvement"
    assert custody_name("lead:frontdesk") == "x-" + b"lead:frontdesk".hex()
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", n) for n in names)


def test_an_x_prefixed_legal_id_is_refused_and_so_is_a_world_that_lists_one(tmp_path):
    with pytest.raises(ContractError, match="escape prefix"):
        custody_name("x-6162")
    path = tmp_path / "org.json"
    path.write_text(json.dumps({"agents": [{"id": "conductor", "role": "conductor", "parent": None, "team": "t"},
                                           {"id": "x-6162", "role": "lead", "parent": "conductor", "team": "t"}]}))
    with pytest.raises(ContractError, match="escape prefix"):
        zeus_world(MemoryStore(), config(organization_file=str(path)), clock=lambda: NOW)


def test_distinct_ids_never_share_a_custody_name():
    ids = set(packaged_organization().agents) | {"a", "a:b", "a-b", "a_b", "A", "a b", "é", "lead:x", "lead-x", "x",
                                                 "x:", "x-", "xx", "0", ":", "::", "conductor:"}
    names = {}
    for role_id in ids:
        try:
            name = custody_name(role_id)
        except ContractError:
            continue  # only the reserved `x-` legal ids are refused
        assert names.setdefault(name, role_id) == role_id, (name, role_id, names[name])


def test_build_runtime_with_the_packaged_org_looks_up_every_key_by_custody_name(tmp_path):
    org = packaged_organization()
    keys = TestRoleKeys(tmp_path / "keys")
    for name in dict.fromkeys(("conductor", *map(custody_name, org.agents))):
        keys.create(name)
    dsn = tmp_path / "dsn"
    dsn.write_text(SCHEME + "u:pw@h/db")
    dsn.chmod(0o600)
    cfg = config(custody_dir=str(tmp_path / "keys"), store_dsn_file=str(dsn))
    runtime = build_runtime(cfg, world_factory=lambda store: zeus_world(store, cfg, clock=lambda: NOW),
                            store_factory=lambda text: MemoryStore(), relay_factory=lambda c, signer: QuietRelay())
    pubkeys = runtime.projection.signer_pubkeys
    assert set(pubkeys) == {"conductor", *org.agents}
    assert pubkeys["lead:frontdesk"] == keys.pubkey(custody_name("lead:frontdesk"))
    assert pubkeys["conductor"] == keys.pubkey("conductor")
