"""Buzz B1: the projection domain (§4.1-§4.5 builders, UUIDv5 vectors, QB1 thread tags, bounds, coalescing)."""

import hashlib
import json
import uuid

import pytest

from codex_harness.coordination.domain import remote_control as rc
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain import buzz_projection as bp
from codex_harness.observation.domain import nostr_event as ne

ROOT = "11" * 32
CMD_EVENT = "22" * 32
OWNER = "ab" * 32
PREV = "33" * 32
CMD_ID = "3f0c5f0e-8a3e-4b9a-9d0e-5b1f0c2d7a41"
CHANNEL = "chan-1"
NOW = 1_800_000_000


# --- UUIDv5 vectors (pinned once; the Desktop must reproduce them byte-for-byte) -------------------------------------

def test_namespace_is_the_pinned_literal():
    assert str(bp.NS_ZEUS_BUZZ) == "749812e0-6b7f-48d6-b33a-aadbee8eb990"
    assert bp.NS_ZEUS_BUZZ.version == 4


@pytest.mark.parametrize("task_id,expected", [
    ("t1", "9a139c21-5586-56a0-99a4-f910a6f7d7f8"),
    ("task-2026-10-01-alpha", "a8054e2c-109d-5cba-836c-ba2c7beaeb07"),
])
def test_task_artifact_d_vectors(task_id, expected):
    assert bp.task_artifact_d(task_id) == expected


def test_desk_session_id_vector():
    assert bp.desk_session_id(OWNER) == "c07b4a1c-e52a-5249-8485-d63bda7a1b69"


def _rfc9562_uuid5(namespace: uuid.UUID, name: str) -> str:
    # Independent of uuid.uuid5: SHA-1 over the namespace bytes and the UTF-8 name, version 5, variant 0b10.
    raw = bytearray(hashlib.sha1(namespace.bytes + name.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x50
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def test_vectors_match_an_independent_rfc9562_computation():
    assert bp.task_artifact_d("t1") == _rfc9562_uuid5(bp.NS_ZEUS_BUZZ, "zeus.task:t1")
    assert bp.desk_session_id(OWNER) == _rfc9562_uuid5(bp.NS_ZEUS_BUZZ, "zeus-desk:" + OWNER)
    assert uuid.UUID(bp.task_artifact_d("t1")).version == 5


def test_id_inputs_are_checked():
    for bad in ("", None, 5):
        with pytest.raises(ContractError):
            bp.task_artifact_d(bad)
    for bad in ("AB" * 32, "ab" * 31, None):
        with pytest.raises(ContractError):
            bp.desk_session_id(bad)


# --- schema URNs ---------------------------------------------------------------------------------------------------

def test_supported_schemas():
    for urn in (bp.ORG_SCHEMA, bp.TASK_ROOT_SCHEMA, bp.TASK_SCHEMA, bp.RECEIPT_SCHEMA, bp.COMMAND_SCHEMA):
        assert bp.supported(urn)
    assert (bp.ORG_SCHEMA, bp.TASK_SCHEMA) == ("urn:zeus:buzz-org:1", "urn:zeus:buzz-task:1")
    for urn in ("urn:zeus:buzz-task:2", "urn:zeus:buzz-task:0", "urn:zeus:buzz-task:01", "urn:zeus:buzz-other:1",
                "urn:zeus:buzz-task:", "urn:zeus:buzz-task:1.1", "", None, 1):
        assert not bp.supported(urn)


# --- builders ------------------------------------------------------------------------------------------------------

def _fence_body(content: str, name: str) -> dict:
    prefix = f"```{name}\n"
    assert content.startswith(prefix) and content.endswith("\n```")
    return json.loads(content[len(prefix):-4])


def _task(**over):
    base = {"task_id": "t1", "version": 4, "generation": 3, "status": "running", "assignee": "dev", "sender": "lead",
            "team": "core", "stage": None, "updated_at": NOW - 5, "observed_at": NOW - 1, "summary": "doing it",
            "evidence_refs": ["sha256:abc", "attempt_7"], "interventions": bp.interventions({"terminal": False}, None)}
    base.update(over)
    return base


def _card(**over):
    kw = {"task": _task(), "title": "Task one", "recipient_role": "dev", "channel": CHANNEL, "root_event_id": ROOT,
          "created_at": NOW}
    kw.update(over)
    return bp.task_card(**kw)


def test_task_root_example_3():
    event = bp.task_root(task_id="t1", title="Task one", team="core", assignee="dev", channel=CHANNEL, created_at=NOW)
    assert event["kind"] == 9 and event["created_at"] == NOW
    assert event["tags"] == [["h", CHANNEL], ["zr-op", "root:t1"]]
    assert _fence_body(event["content"], "zeus:task-root") == {
        "schema": "urn:zeus:buzz-task-root:1", "task_id": "t1", "title": "Task one", "team": "core",
        "assignee": "dev"}
    assert bp.resolve_thread(event["tags"]) is None  # the root is top-level
    assert not any(t[0] == "e" for t in event["tags"])


@pytest.mark.parametrize("over", [{"task_id": ""}, {"title": "x" * 501}, {"team": None}, {"assignee": 3},
                                  {"channel": ""}, {"created_at": -1}])
def test_task_root_refusals(over):
    kw = {"task_id": "t1", "title": "T", "team": "core", "assignee": "dev", "channel": CHANNEL, "created_at": NOW}
    kw.update(over)
    with pytest.raises(ContractError):
        bp.task_root(**kw)


def test_task_card_create_tags_and_content():
    event = _card()
    assert event["kind"] == 45010
    assert event["tags"] == [["ar", "1"], ["d", "9a139c21-5586-56a0-99a4-f910a6f7d7f8"], ["h", CHANNEL],
                             ["type", "zeus.task"], ["title", "Task one"], ["op", "create"], ["root", ROOT],
                             ["zt", "t1"], ["zs", "running"], ["zr", "dev"]]
    body = json.loads(event["content"])
    assert body["schema"] == "urn:zeus:buzz-task:1"
    assert set(body) == {"schema", "task_id", "version", "generation", "status", "assignee", "sender", "team", "stage",
                         "updated_at", "observed_at", "summary", "evidence_refs", "interventions"}
    assert event["content"] == json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_task_card_update_carries_prev_after_root():
    event = _card(op="update", prev=PREV)
    names = [t[0] for t in event["tags"]]
    assert names == ["ar", "d", "h", "type", "title", "op", "root", "prev", "zt", "zs", "zr"]
    assert ["prev", PREV] in event["tags"] and ["op", "update"] in event["tags"]


@pytest.mark.parametrize("kw", [{"op": "update"}, {"prev": PREV}, {"op": "delete"}, {"op": "update", "prev": "zz"},
                                {"root_event_id": "abc"}, {"recipient_role": ""}, {"title": "x" * 501}])
def test_task_card_tag_refusals(kw):
    with pytest.raises(ContractError):
        _card(**kw)


def test_card_content_bounds():
    assert _card(task=_task(summary="s" * 2000))["kind"] == 45010
    assert _card(task=_task(summary="é" * 2000))["kind"] == 45010  # characters
    with pytest.raises(ContractError):
        _card(task=_task(summary="s" * 2001))
    with pytest.raises(ContractError):
        _card(task=_task(version=-1))
    with pytest.raises(ContractError):
        _card(task=_task(generation=True))
    with pytest.raises(ContractError):
        _card(task=_task(stage=3))
    with pytest.raises(ContractError):
        _card(task=_task(extra=1))
    bad = _task()
    del bad["summary"]
    with pytest.raises(ContractError):
        _card(task=bad)


@pytest.mark.parametrize("ref", ["/etc/passwd", "../x", "a/b", "a\\b", "C:\\x", "c:x", "~/x", ".hidden", "file:///x",
                                 "https://x/y", "a..b", "", " x", "x y", "a" * 129, 5, None])
def test_evidence_refs_refuse_anything_path_like(ref):
    assert not bp.evidence_ref_ok(ref)
    with pytest.raises(ContractError):
        _card(task=_task(evidence_refs=[ref]))


def test_evidence_refs_accept_opaque_ids_and_are_bounded():
    for ref in ("sha256:abc123", "attempt_7", "ev-0.1", "a" * 128):
        assert bp.evidence_ref_ok(ref)
    with pytest.raises(ContractError):
        _card(task=_task(evidence_refs=["a"] * 101))
    with pytest.raises(ContractError):
        _card(task=_task(evidence_refs="sha256:abc"))


def test_intervention_entries_are_validated():
    for item in ({"op": "nope", "available": True, "reason_code": None},
                 {"op": "cancel_task", "available": False, "reason_code": None},
                 {"op": "cancel_task", "available": True, "reason_code": "bogus"},
                 {"op": "cancel_task", "available": 1, "reason_code": None},
                 {"op": "cancel_task", "available": True}):
        with pytest.raises(ContractError):
            _card(task=_task(interventions=[item]))


def test_content_must_stay_below_256_kib():
    assert bp.MAX_CONTENT_BYTES == 262144
    assert len(_card()["content"].encode()) < 4096  # far below
    big = {"id": "r", "role": "x", "parent": None, "team": "t", "display": "d" * 1000, "pubkey": OWNER,
           "status": {"state": "idle", "task_id": None, "last_activity_at": None, "observed_at": 1}}
    org = {"version": 1, "generated_at": 1, "roles": [big] * 300,
           "fleet": {"paused": None, "version": None, "activation_hold": None}}
    with pytest.raises(ContractError):
        bp.org_snapshot(org=org, d="org-d", channel=CHANNEL, created_at=NOW)


def _org(**over):
    role = {"id": "dev", "role": "developer", "parent": "lead", "team": "core", "display": "Dev", "pubkey": OWNER,
            "status": {"state": "busy", "task_id": "t1", "last_activity_at": NOW - 3, "observed_at": NOW - 1}}
    base = {"version": 7, "generated_at": NOW, "roles": [role],
            "fleet": {"paused": False, "version": 2, "activation_hold": False}}
    base.update(over)
    return base


def test_org_snapshot_shape():
    event = bp.org_snapshot(org=_org(), d="pinned-org-d", channel=CHANNEL, created_at=NOW)
    assert event["kind"] == 45010
    assert event["tags"] == [["ar", "1"], ["d", "pinned-org-d"], ["h", CHANNEL], ["type", "zeus.org"],
                             ["title", bp.ORG_TITLE], ["op", "create"]]
    body = json.loads(event["content"])
    assert body["schema"] == "urn:zeus:buzz-org:1" and body["version"] == 7
    assert body["fleet"] == {"paused": False, "version": 2, "activation_hold": False}
    assert "fresh" not in event["content"]
    update = bp.org_snapshot(org=_org(), d="pinned-org-d", channel=CHANNEL, created_at=NOW, op="update", prev=PREV)
    assert update["tags"][-2:] == [["op", "update"], ["prev", PREV]]


def test_org_snapshot_accepts_unknown_fleet_values():
    org = _org(fleet={"paused": None, "version": None, "activation_hold": None})
    assert json.loads(bp.org_snapshot(org=org, d="d", channel=CHANNEL, created_at=NOW)["content"])["fleet"] == {
        "paused": None, "version": None, "activation_hold": None}


@pytest.mark.parametrize("mutate", [
    lambda o: o["roles"][0]["status"].update(state="sleeping"),
    lambda o: o["roles"][0].update(pubkey="XY" * 32),
    lambda o: o["roles"][0].pop("display"),
    lambda o: o["roles"][0]["status"].pop("observed_at"),
    lambda o: o["fleet"].update(paused="no"),
    lambda o: o["fleet"].update(version=-1),
    lambda o: o.update(version=-1),
    lambda o: o.update(roles="x"),
    lambda o: o.update(extra=1),
])
def test_org_snapshot_refusals(mutate):
    org = _org()
    mutate(org)
    with pytest.raises(ContractError):
        bp.org_snapshot(org=org, d="d", channel=CHANNEL, created_at=NOW)


def _receipt(**over):
    kw = {"command_id": CMD_ID, "command_event_id": CMD_EVENT, "command_author": OWNER, "root_event_id": ROOT,
          "channel": CHANNEL, "transition_revision": 2, "disposition": "effect_done", "task_id": "t1",
          "generation_after": 4, "at": NOW, "created_at": NOW}
    kw.update(over)
    return bp.receipt(**kw)


def test_receipt_tags_are_the_qb1_set_example_3():
    event = _receipt()
    assert event["kind"] == 9
    assert event["tags"] == [["e", ROOT, "", "root"], ["e", CMD_EVENT, "", "reply"], ["p", OWNER], ["h", CHANNEL],
                             ["zr-op", f"receipt:{CMD_ID}:2"]]
    assert bp.resolve_thread(event["tags"]) == (ROOT, CMD_EVENT)  # a nested reply under the root
    body = _fence_body(event["content"], "zeus:receipt")
    assert body == {"schema": "urn:zeus:buzz-receipt:1", "command_id": CMD_ID, "command_event_id": CMD_EVENT,
                    "transition_revision": 2, "disposition": "effect_done", "reason_code": None, "task_id": "t1",
                    "generation_after": 4, "work": None, "at": NOW}


def test_receipt_with_work_and_refusal():
    work = {"state": "completed", "result": "needs_spec", "evidence_at": NOW}
    body = _fence_body(_receipt(work=work)["content"], "zeus:receipt")
    assert body["work"] == work
    refused = _fence_body(_receipt(disposition="refused", reason_code="stale_generation")["content"],
                          "zeus:receipt")
    assert refused["reason_code"] == "stale_generation"
    assert _receipt(disposition="effect_unknown", reason_code="not_applied")["kind"] == 9
    assert _receipt(disposition="received", task_id=None, generation_after=None)["kind"] == 9


@pytest.mark.parametrize("over", [
    {"command_id": "nope"}, {"command_id": CMD_ID.upper()}, {"command_id": str(uuid.uuid1())},
    {"disposition": "done"}, {"disposition": "refused"}, {"disposition": "effect_done", "reason_code": "not_applied"},
    {"reason_code": "bogus"}, {"transition_revision": 0}, {"transition_revision": -1},
    {"transition_revision": True}, {"command_event_id": "x"}, {"root_event_id": "x"},
    {"command_author": "AB" * 32}, {"channel": ""}, {"at": -1}, {"generation_after": -1},
    {"work": {"state": "weird", "result": None, "evidence_at": None}},
    {"work": {"state": "running", "result": None, "evidence_at": None}},
    {"work": {"state": "queued", "result": "answered", "evidence_at": None}},
    {"work": {"state": "completed", "result": None, "evidence_at": None}},
    {"work": {"state": "completed", "result": "done", "evidence_at": None}},
    {"work": {"state": "queued"}},
])
def test_receipt_refusals(over):
    with pytest.raises(ContractError):
        _receipt(**over)


def test_two_receipts_with_the_same_disposition_have_distinct_identities():
    a = _receipt(transition_revision=2, work={"state": "queued", "result": None, "evidence_at": None})
    b = _receipt(transition_revision=3, work={"state": "claimed", "result": None, "evidence_at": None})
    assert dict(t for t in a["tags"] if t[0] == "zr-op") != dict(t for t in b["tags"] if t[0] == "zr-op")
    assert bp.receipt_op(CMD_ID, 2) != bp.receipt_op(CMD_ID, 3)


# --- thread tags (QB1/QB2) -------------------------------------------------------------------------------------------

def test_in_thread_post_tags_carry_reply_never_a_lone_root():
    tags = bp.thread_post_tags(CHANNEL, ROOT, OWNER)
    assert tags == [["e", ROOT, "", "reply"], ["p", OWNER], ["h", CHANNEL]]
    assert bp.resolve_thread(tags) == (ROOT, ROOT)
    assert not any(t[0] == "e" and t[3] == "root" for t in tags)


def test_a_lone_root_marker_never_threads():
    assert bp.resolve_thread([["e", ROOT, "", "root"], ["h", CHANNEL]]) is None  # the negative the design pins
    assert bp.resolve_thread([["h", CHANNEL]]) is None
    assert bp.resolve_thread([["e", "short", "", "reply"]]) is None
    assert bp.resolve_thread([["e", ROOT, "", "reply"], ["e", CMD_EVENT, "", "reply"]]) == (CMD_EVENT, CMD_EVENT)
    assert bp.resolve_thread([["e", ROOT, "", "root"], ["e", CMD_EVENT, "", "reply"]]) == (ROOT, CMD_EVENT)


def test_every_kind_9_and_45010_event_carries_h():
    events = [bp.task_root(task_id="t1", title="T", team="c", assignee="dev", channel=CHANNEL, created_at=NOW),
              _receipt(), _card(), bp.org_snapshot(org=_org(), d="d", channel=CHANNEL, created_at=NOW)]
    for event in events:
        assert [t for t in event["tags"] if t[0] == "h"] == [["h", CHANNEL]]
    assert [e["kind"] for e in events] == [9, 9, 45010, 45010]


@pytest.mark.parametrize("args", [(CHANNEL, "x", OWNER), (CHANNEL, ROOT, "x"), ("", ROOT, OWNER)])
def test_thread_tag_inputs_are_checked(args):
    with pytest.raises(ContractError):
        bp.thread_post_tags(*args)


def test_builders_feed_the_codec_unchanged():
    # The unsigned dicts are exactly what Batch A's codec serializes (no field mapping, no duplication).
    for event in (_receipt(), _card()):
        ne.serialize_for_id(OWNER, event["created_at"], event["kind"], event["tags"], event["content"])


# --- coalescing ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,period", [("org", 10), ("task", 2)])
def test_may_publish_period_boundaries(kind, period):
    last = NOW
    assert bp.may_publish(kind, last, last + period - 1) is False
    assert bp.may_publish(kind, last, last + period) is True
    assert bp.may_publish(kind, last, last + period + 1) is True
    assert bp.may_publish(kind, last, last) is False
    assert bp.may_publish(kind, last, last - 5) is False  # the clock stepped back: wait
    assert bp.may_publish(kind, None, NOW) is True  # first publish
    assert bp.may_publish(kind, last, last, terminal=True) is True  # terminal is immediate
    assert bp.may_publish(kind, last, last - 5, terminal=True) is True


def test_may_publish_inputs():
    with pytest.raises(ContractError):
        bp.may_publish("receipt", 1, 2)
    for args in ((1, -1), (-1, 1), (True, 5), ("1", 5)):
        with pytest.raises(ContractError):
            bp.may_publish("task", *args)


# --- interventions ---------------------------------------------------------------------------------------------------

def _by_op(items):
    assert [i["op"] for i in items] == list(rc.OPS)
    for i in items:
        assert set(i) == {"op", "available", "reason_code"}
        assert (i["reason_code"] is None) == i["available"]
    return {i["op"]: i for i in items}


def test_interventions_for_a_live_task_and_a_running_fleet():
    items = _by_op(bp.interventions({"terminal": False}, {"paused": False, "activation_hold": False}))
    assert items["cancel_task"]["available"] is True
    assert items["pause_fleet"]["available"] is True
    assert items["resume_fleet"] == {"op": "resume_fleet", "available": False, "reason_code": "not_applied"}


def test_interventions_for_a_paused_fleet_and_a_hold():
    paused = _by_op(bp.interventions({"terminal": False}, {"paused": True, "activation_hold": False}))
    assert paused["resume_fleet"]["available"] is True
    assert paused["pause_fleet"] == {"op": "pause_fleet", "available": False, "reason_code": "not_applied"}
    held = _by_op(bp.interventions({"terminal": False}, {"paused": True, "activation_hold": True}))
    assert held["resume_fleet"] == {"op": "resume_fleet", "available": False,
                                    "reason_code": "activation_hold_present"}


def test_interventions_unknown_inputs_are_unavailable():
    unknown = _by_op(bp.interventions(None, None))
    assert unknown["cancel_task"]["reason_code"] == "task_unknown"
    assert not unknown["pause_fleet"]["available"] and not unknown["resume_fleet"]["available"]
    assert _by_op(bp.interventions({}, {"paused": True, "activation_hold": None}))["resume_fleet"][
        "available"] is False
    assert _by_op(bp.interventions({"terminal": True}, None))["cancel_task"]["reason_code"] == "not_applied"


@pytest.mark.parametrize("task_view,fleet_view", [(None, None), ({"terminal": False}, {"paused": True,
                                                                                       "activation_hold": False})])
def test_desk_ops_are_not_migrated_in_this_batch(task_view, fleet_view):
    items = _by_op(bp.interventions(task_view, fleet_view))
    for op in ("desk_open", "desk_turn"):
        assert items[op] == {"op": op, "available": False, "reason_code": "desk_not_migrated"}
    assert bp.DESK_MIGRATED is False


def test_interventions_are_accepted_by_the_card_builder():
    for views in ((None, None), ({"terminal": False}, {"paused": True, "activation_hold": False})):
        assert _card(task=_task(interventions=bp.interventions(*views)))["kind"] == 45010


# --- NIP-AR envelope contract (Buzz docs/nips/NIP-AR.md lines 36-47; artifact.rs:100-125) ---------------------------
# The relay refuses a non-delete revision without exactly one each of ar=1, d (UUID), h, type, a nonblank title
# (<= 512 UTF-8 bytes) and op, and `prev` exactly on an update; the org snapshot once lacked `title` (E2E run 3).

def _artifact_events():
    org_d = str(uuid.uuid5(bp.NS_ZEUS_BUZZ, "zeus.org:contract"))
    events = [bp.org_snapshot(org=_org(), d=org_d, channel=CHANNEL, created_at=NOW),
              bp.org_snapshot(org=_org(), d=org_d, channel=CHANNEL, created_at=NOW, op="update", prev=PREV),
              _card(), _card(op="update", prev=PREV)]
    return [e for e in events if e["kind"] == 45010]


def test_every_45010_event_meets_the_nip_ar_envelope_contract():
    events = _artifact_events()
    assert len(events) == 4
    for event in events:
        names = [tag[0] for tag in event["tags"]]
        for required in ("ar", "d", "h", "type", "title", "op"):
            assert names.count(required) == 1, (required, event["tags"])
        assert names.count("prev") == (1 if ["op", "update"] in event["tags"] else 0), event["tags"]
        tags = {tag[0]: tag[1] for tag in event["tags"]}
        assert tags["ar"] == "1" and tags["op"] in ("create", "update")
        assert str(uuid.UUID(tags["d"])) == tags["d"], "d is a canonical lowercase UUID"
        assert tags["h"] and tags["type"]
        assert tags["title"].strip() and len(tags["title"].encode("utf-8")) <= 512
    assert {tag[1] for e in events for tag in e["tags"] if tag[0] == "type"} == {"zeus.org", "zeus.task"}
