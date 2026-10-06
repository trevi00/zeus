"""Cutover RH-4a: the rehearsal R3 read-only parity runner (`compare/rehearsal/r3.py`, `r3-leaves.json`, `r3-masks.json`).

Layer: harness tooling tests (never shipped). Expected results come from the task spec's acceptance criteria and the
rehearsal design "5. R3" / critique #15: the SOURCE golden `compare/goldens/reference/cli.parser.json` (152 commands) is
the oracle for revision A's inventory; the fixtures' own constants are the oracle for the runner; the never-masked list is
the one in `compare/masks.json`'s note. The runner tests inject the leaf executor (`host_runner`: a host subprocess with a
closed env; the default `namespace_runner` is `namespace.run_in_namespace`, exercised by test_rehearsal_namespace). The
pure tests need no Docker; the copy tests need `ZEUS_TEST_DOCKER=1` and `ZEUS_TEST_DOCKER_PGEXEC=1`, and a skip under those
opt-ins is a failure.

Structural checks (named): `test_every_cited_function_exists_*` is a PROVENANCE check (a citation names a def that
exists in its tree); it is not behavioural acceptance of the leaf.
"""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import r3  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1" and os.environ.get(guard.DOCKER_PGEXEC_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
RUN8, DATABASE = "4a7c2e91", "zeus"
A_SRC, B_SRC = REPO / "reference" / "m7" / "src", REPO / "src"
GOLDEN = REPO / "compare" / "goldens" / "reference" / "cli.parser.json"
PYTHON = sys.executable


@pytest.fixture(scope="module")
def inventories():
    return {"A": r3.parser_inventory(A_SRC), "B": r3.parser_inventory(B_SRC)}


@pytest.fixture(scope="module")
def catalog():
    return r3.load_catalog()


# ---- the per-revision parser inventory (critique #15) ----

def test_revision_a_inventory_is_the_source_golden_node_list_and_help_digests(inventories):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["nodes"]
    assert r3.commands(inventories["A"]) == [n["command"] for n in golden] and len(golden) == 152
    assert [(n["root"], n["help_exit"]) for n in inventories["A"]] == [(n["root"], n["help_exit"]) for n in golden]
    # same walker rule, same bytes: the --help digests of the reference driver (recorded by SOURCE) are reproduced
    assert [n["help_sha256"] for n in inventories["A"]] == [n["help_sha256"] for n in golden]


def test_revision_b_has_nodes_a_lacks_and_each_inventory_is_covered_by_the_catalog(inventories, catalog):
    only_b = set(r3.commands(inventories["B"])) - set(r3.commands(inventories["A"]))
    assert {c for c in only_b if c.startswith("zeus dlq")} == {"zeus dlq", "zeus dlq list", "zeus dlq trim", "zeus dlq replay"}
    assert any(c.startswith("zeus research-package") for c in only_b) and len(only_b) == 11
    gaps = r3.coverage(catalog, {rev: r3.commands(nodes) for rev, nodes in inventories.items()})
    assert gaps == {"A": {"unclassified": [], "stale": []}, "B": {"unclassified": [], "stale": []}}


def test_a_node_in_one_revision_only_is_found_by_that_revisions_inventory_and_fails_coverage_there_only(
        inventories, catalog, tmp_path):
    fake = tmp_path / "src" / "codex_harness"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("")
    (fake / "cli.py").write_text(
        "import argparse\n"
        "def parser():\n"
        "    p = argparse.ArgumentParser(prog='zeus')\n"
        "    c = p.add_subparsers(dest='command', required=True)\n"
        "    c.add_parser('paths')\n"
        "    c.add_parser('extra-only')\n"
        "    return p\n")
    extra = r3.parser_inventory(tmp_path / "src")
    assert r3.commands(extra) == ["zeus paths", "zeus extra-only"]  # fixture-defined
    every = {"A": r3.commands(inventories["A"]), "B": r3.commands(inventories["B"]), "fakeX": r3.commands(extra)}
    known = copy.deepcopy(catalog)  # the catalog already classifies `zeus paths`; the fake revision is new to it
    known["nodes"]["zeus paths"]["revisions"].append("fakeX")
    gaps = r3.coverage(known, every)
    assert gaps["fakeX"] == {"unclassified": ["zeus extra-only"], "stale": []}
    assert gaps["A"] == gaps["B"] == {"unclassified": [], "stale": []}
    with pytest.raises(r3.Refused) as caught:
        r3.assert_covered(known, every)
    assert caught.value.code == "coverage_failed" and "unclassified=['zeus extra-only']" in caught.value.detail
    known["nodes"]["zeus extra-only"] = {"class": "excluded", "revisions": ["fakeX"], "reason": "fixture"}
    r3.assert_covered(known, every)  # classified in that revision's inventory: covered


def test_an_unclassified_node_and_a_stale_entry_each_fail_coverage(inventories, catalog):
    commands = {rev: r3.commands(nodes) for rev, nodes in inventories.items()}
    missing = copy.deepcopy(catalog)
    del missing["nodes"]["zeus fleet status"]
    with pytest.raises(r3.Refused) as caught:
        r3.assert_covered(missing, commands)
    assert caught.value.code == "coverage_failed" and "unclassified=['zeus fleet status']" in caught.value.detail
    stale = copy.deepcopy(catalog)
    stale["nodes"]["zeus not-a-node"] = {"class": "excluded", "revisions": ["A"], "reason": "x"}
    with pytest.raises(r3.Refused) as caught:
        r3.assert_covered(stale, commands)
    assert "stale=['zeus not-a-node']" in caught.value.detail


def test_an_inventory_that_imported_another_tree_is_refused_not_passed_vacuously(tmp_path):
    (tmp_path / "src" / "codex_harness").mkdir(parents=True)  # a namespace dir: the venv's regular package wins
    (tmp_path / "src" / "codex_harness" / "cli.py").write_text("def parser():\n    raise SystemExit(9)\n")
    with pytest.raises(r3.Refused) as caught:
        r3.parser_inventory(tmp_path / "src")
    assert caught.value.code in {"inventory_origin", "inventory_failed"}


# ---- the catalog ----

def test_every_node_is_classified_with_a_reason_or_citations_and_the_disputed_set_is_the_owners(catalog):
    classes = {}
    for command, entry in catalog["nodes"].items():
        classes.setdefault(entry["class"], []).append(command)
        if entry["class"] == "read_only":
            assert all(entry["cites"][s] for s in ("A", "B")) and entry["argv"], command
        else:
            assert entry["reason"].strip(), command
    assert len(catalog["nodes"]) == 165 and len(classes.get("disputed", [])) / len(catalog["nodes"]) < 0.10
    assert r3.disputed(catalog) == []  # owner ruling 2026-10-06: `zeus sdd view` writes --output, so it is excluded
    # the spec's examples
    assert catalog["nodes"]["zeus fleet status"]["class"] == "read_only"
    maintain = catalog["nodes"]["zeus host-delivery maintain"]
    assert maintain["class"] == "excluded" and maintain["revisions"] == ["08bb9a44"]
    monitor = catalog["nodes"]["zeus-monitor collect --once"]
    assert monitor["class"] == "read_only" and any("monitoring.json" in w for w in monitor["declared_writes"])


def test_every_cited_function_exists_in_its_tree_provenance_check(catalog):
    """STRUCTURAL (provenance): a citation `path:Class.method` names a def that exists under its side's root."""
    roots = {"A": REPO / catalog["citation_roots"]["A"], "B": REPO / catalog["citation_roots"]["B"]}
    unresolved = [(c, side, cite) for c, e in catalog["nodes"].items() for side in ("A", "B")
                  for cite in e.get("cites", {}).get(side, []) if not r3.resolve_citation(cite, roots[side])]
    assert unresolved == []
    assert not r3.resolve_citation("cli.py:no_such_function", roots["A"])
    assert not r3.resolve_citation("no/such/file.py:main", roots["A"])


@pytest.mark.parametrize("mutate,code", [
    (lambda e: e.pop("cites"), "catalog_malformed"),
    (lambda e: e.update(argv=["x {unlisted}"]), "catalog_malformed"),
    (lambda e: e.update({"class": "excluded"}), "catalog_malformed"),  # excluded needs a reason
    (lambda e: e.update({"class": "maybe"}), "catalog_malformed"),
])
def test_a_malformed_catalog_entry_is_refused(catalog, mutate, code):
    broken = copy.deepcopy(catalog)
    mutate(broken["nodes"]["zeus fleet status"])
    with pytest.raises(r3.Refused) as caught:
        r3.validate_catalog(broken)
    assert caught.value.code == code


# ---- the closed masks ----

def test_the_shipped_mask_proposal_is_closed_and_names_only_non_authority_fields():
    masks = r3.load_masks()
    assert masks["closed"] is True and masks["proposal"] is True
    assert [m["id"] for m in masks["masks"]] == ["rehearsal.r3.wall_clock", "rehearsal.r3.age", "rehearsal.r3.pid",
                                                  "rehearsal.r3.root_path"]
    merged = json.loads((REPO / "compare" / "masks.json").read_text(encoding="utf-8"))
    assert not any(m["id"].startswith("rehearsal.r3") for m in merged["masks"])  # Codex reviews it first


@pytest.mark.parametrize("field", ["status", "owner", "owner_id", "generation", "task_generation", "lease_expires_at",
                                   "attempts", "authorization", "body_sha256", "plan_digest", "event_hash", "evidence_ref",
                                   "job_status"])
def test_masking_an_authority_field_is_refused(field):
    document = {"version": 1, "closed": True, "masks": [
        {"id": "rehearsal.r3.bad", "fields": [field], "reason": "mutation"}]}
    with pytest.raises(r3.Refused) as caught:
        r3.validate_masks(document)
    assert caught.value.code == "mask_forbidden_field"


def test_a_mask_changes_only_its_declared_fields_and_leaves_status_and_digests_byte_equal():
    masks = r3.load_masks()
    text = json.dumps({"generated_at": "2026-10-06T00:00:00Z", "pid": 41, "status": "held", "plan_sha256": "ab" * 32,
                       "nested": [{"pid": 7, "owner": "lane-1", "elapsed_seconds": 3.5}], "path": "/r/ROOT/x/y"})
    out = json.loads(r3.apply_masks(text, masks, roots=("/r/ROOT/x",)))
    assert out["generated_at"] == "<masked:rehearsal.r3.wall_clock>" and out["pid"] == "<masked:rehearsal.r3.pid>"
    assert out["nested"][0] == {"pid": "<masked:rehearsal.r3.pid>", "owner": "lane-1",
                                "elapsed_seconds": "<masked:rehearsal.r3.age>"}
    assert out["status"] == "held" and out["plan_sha256"] == "ab" * 32  # never masked
    assert out["path"] == "<ROOT>/y"
    assert r3.apply_masks("plain /r/ROOT/x/text, pid 4", masks, roots=("/r/ROOT/x",)) == "plain <ROOT>/text, pid 4"


# ---- the runner with an injected snapshot (no Docker) ----

def _fixture_catalog(*nodes):
    entries = {}
    for name, argv in nodes:
        entries[name] = {"class": "read_only", "revisions": ["A", "B"], "argv": argv, "params": [],
                         "cites": {"A": ["x.py:f"], "B": ["y.py:g"]}}
    return {"version": 1, "nodes": entries}


class LeafEnv(dict):
    """The closed env a host-run leaf gets, carrying the `root`/`x` paths the runner rewrites in output."""

    def __init__(self, env=None, root="/r/ROOT", x="/r/ROOT/S"):
        super().__init__(env or {})
        self.root, self.x = root, x


def _sides(code, envs=None):
    envs = envs or {}
    return {name: r3.Side(name, LeafEnv(envs.get(name)), {"zeus": [PYTHON, "-c", code]}) for name in ("A", "B")}


# the pid differs per side (masked); status is the same; argv[1] is the leaf's mode
PROGRAM = ("import sys,json,os\n"
           "print(json.dumps({'leaf': sys.argv[1], 'status': 'held', 'pid': 1000 + int(os.environ.get('N', '0'))}))\n")
OK_CATALOG_ARGV = ["ok"]


class FakeCopy:
    pg_socket = redis_socket = "/nowhere"


def _fake_snapshots(state):
    return lambda copy, database: {"catalog_sha256": state["pg"], "redis_dbs": {}, "redis_prefixes": state["redis"],
                                   "redis_failures": []}


def test_parity_passes_when_exits_and_masked_digests_agree_and_the_copy_is_unchanged(tmp_path):
    state = {"pg": "d0", "redis": {}}
    catalog = _fixture_catalog(("zeus fixture status", OK_CATALOG_ARGV))
    inventories = {"A": ["zeus fixture status"], "B": ["zeus fixture status"]}
    sides = _sides(PROGRAM, {"A": {"N": "1"}, "B": {"N": "2"}})  # pid 1001 vs 1002: masked; status is equal
    document = r3.run_r3(sides, FakeCopy(), DATABASE, catalog, r3.load_masks(), tmp_path / "ok", inventories=inventories,
                         runner=r3.host_runner, snap=_fake_snapshots(state))
    row = document["facts"]["results"][0]
    unmasked = r3.apply_masks(json.dumps({"leaf": "ok", "status": "held", "pid": 1001}), {"masks": []})
    assert r3._sha(unmasked) != row["A"]["stdout_sha256"]  # the pid really was masked in the digest
    assert document["status"] == "ok" and document["facts"]["d1_equals_d0"] is True
    assert row["verdict"] == "pass" and row["A"]["exit"] == row["B"]["exit"] == 0
    assert row["A"]["stdout_sha256"] == row["B"]["stdout_sha256"]
    assert json.loads((tmp_path / "ok" / "r3.json").read_text())["facts"]["leaves"] == 1


def test_an_unmasked_difference_in_a_status_field_fails_parity(tmp_path):
    state = {"pg": "d0", "redis": {}}
    code = "import json,os\nprint(json.dumps({'status': os.environ['SIDE']}))\n"
    sides = _sides(code, {"A": {"SIDE": "A"}, "B": {"SIDE": "B"}})
    catalog = _fixture_catalog(("zeus fixture status", []))
    with pytest.raises(r3.R3Failed) as caught:
        r3.run_r3(sides, FakeCopy(), DATABASE, catalog, r3.load_masks(), tmp_path / "bad",
                  inventories={"A": ["zeus fixture status"], "B": ["zeus fixture status"]}, runner=r3.host_runner,
                  snap=_fake_snapshots(state))
    assert caught.value.failures == ["zeus fixture status:stdout_differs"]


def test_a_leaf_that_changes_the_copy_fails_as_not_read_only_and_a_blind_snapshot_would_miss_it(tmp_path):
    """The mutation proof: with the real before/after snapshots the writer fails; with a snapshot that cannot see the
    change (the disabled D1 comparison) the same run passes, so the detection is exactly the D1 comparison."""
    state = {"pg": "d0", "redis": {}}

    def writing_runner(side, command, timeout):
        state["pg"] = "d1-after-write"  # the leaf "secretly writes a row" (the fake copy's catalog digest moves)
        return r3.host_runner(side, command, timeout)

    catalog = _fixture_catalog(("zeus fixture status", OK_CATALOG_ARGV))
    inventories = {"A": ["zeus fixture status"], "B": ["zeus fixture status"]}
    with pytest.raises(r3.R3Failed) as caught:
        r3.run_r3(_sides(PROGRAM), FakeCopy(), DATABASE, catalog, r3.load_masks(), tmp_path / "w", inventories=inventories,
                  runner=writing_runner, snap=_fake_snapshots(state))
    assert caught.value.failures == ["zeus fixture status:not_read_only:A:catalog_sha256"]  # B sees the moved baseline
    assert caught.value.document["facts"]["d1_equals_d0"] is False
    state["pg"] = "d0"
    blind = r3.run_r3(_sides(PROGRAM), FakeCopy(), DATABASE, catalog, r3.load_masks(), tmp_path / "blind",
                      inventories=inventories, runner=writing_runner, snap=lambda c, d: {
                          "catalog_sha256": "d0", "redis_dbs": {}, "redis_prefixes": {}, "redis_failures": []})
    assert blind["status"] == "ok"  # the mutated (blind) run passes: it is the comparison that catches the writer


def test_exit_difference_missing_parameter_timeout_and_disputed_nodes_each_fail(tmp_path, catalog):
    state = {"pg": "d0", "redis": {}}
    snap = _fake_snapshots(state)
    code = "import os,sys\nsys.exit(int(os.environ['RC']))\n"
    sides = _sides(code, {"A": {"RC": "0"}, "B": {"RC": "3"}})
    ok = _fixture_catalog(("zeus fixture status", []))
    inv = {"A": ["zeus fixture status"], "B": ["zeus fixture status"]}
    with pytest.raises(r3.R3Failed) as caught:
        r3.run_r3(sides, FakeCopy(), DATABASE, ok, r3.load_masks(), tmp_path / "e", inventories=inv, runner=r3.host_runner,
                  snap=snap)
    assert caught.value.failures == ["zeus fixture status:exit_differs:0!=3"]
    needs = _fixture_catalog(("zeus fixture status", ["{ticket_id}"]))
    needs["nodes"]["zeus fixture status"]["params"] = ["ticket_id"]
    with pytest.raises(r3.R3Failed) as caught:
        r3.run_r3(sides, FakeCopy(), DATABASE, needs, r3.load_masks(), tmp_path / "p", inventories=inv,
                  runner=r3.host_runner, snap=snap)
    assert caught.value.failures == ["zeus fixture status:param_missing:ticket_id"]
    slow = {"A": r3.Side("A", LeafEnv(), {"zeus": [PYTHON, "-c", "import time; time.sleep(30)"]}),
            "B": r3.Side("B", LeafEnv(), {"zeus": [PYTHON, "-c", "pass"]})}
    with pytest.raises(r3.R3Failed) as caught:
        r3.run_r3(slow, FakeCopy(), DATABASE, ok, r3.load_masks(), tmp_path / "t", inventories=inv, runner=r3.host_runner,
                  snap=snap, timeout=0.5)
    assert "zeus fixture status:timeout:A" in caught.value.failures
    disputed = copy.deepcopy(ok)
    disputed["nodes"]["zeus fixture view"] = {"class": "disputed", "revisions": ["A", "B"], "reason": "owner decides"}
    with pytest.raises(r3.R3Failed) as caught:
        r3.run_r3(_sides(PROGRAM), FakeCopy(), DATABASE, disputed, r3.load_masks(), tmp_path / "d",
                  inventories={"A": ["zeus fixture status", "zeus fixture view"], "B": ["zeus fixture status", "zeus fixture view"]},
                  runner=r3.host_runner, snap=snap)
    assert "disputed_unresolved:zeus fixture view" in caught.value.failures and not any(
        f.startswith("zeus fixture view:") for f in caught.value.failures)
    with pytest.raises(r3.Refused) as caught:  # coverage is checked before any leaf runs
        r3.run_r3(_sides(PROGRAM), FakeCopy(), DATABASE, ok, r3.load_masks(), tmp_path / "c",
                  inventories={"A": ["zeus fixture status", "zeus unclassified"], "B": ["zeus fixture status"]},
                  runner=r3.host_runner, snap=snap)
    assert caught.value.code == "coverage_failed"


def test_read_only_leaves_present_on_one_side_only_are_logged_not_dropped(tmp_path, catalog):
    both, one = r3.read_only_leaves(catalog)
    assert "zeus fleet status" in both and one == []
    mixed = _fixture_catalog(("zeus fixture status", OK_CATALOG_ARGV))
    mixed["nodes"]["zeus fixture b-only"] = {"class": "read_only", "revisions": ["B"], "argv": [], "params": [],
                                             "cites": {"B": ["y.py:g"]}}
    state = {"pg": "d0", "redis": {}}
    document = r3.run_r3(_sides(PROGRAM), FakeCopy(), DATABASE, mixed, r3.load_masks(), tmp_path / "one",
                         inventories={"A": ["zeus fixture status"], "B": ["zeus fixture status", "zeus fixture b-only"]},
                         runner=r3.host_runner, snap=_fake_snapshots(state))
    assert document["facts"]["skipped_one_side"] == ["zeus fixture b-only"] and document["facts"]["leaves"] == 1


# ---- real Docker: one fixture copy with real catalog and Redis digests ----

SNEAKY = r'''
import json, os, sys
mode = sys.argv[1]
if mode == "write-pg":
    import psycopg
    with psycopg.connect(os.environ["PGDSN"], autocommit=True) as conn:
        conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', 'secret', '{\"n\": 99}') ON CONFLICT DO NOTHING")
elif mode == "write-redis":
    import redis
    redis.Redis(unix_socket_path=os.environ["RSOCK"]).set("rh:plain", "changed")
elif mode == "read":
    import psycopg, redis
    with psycopg.connect(os.environ["PGDSN"]) as conn:
        n = conn.execute("SELECT count(*) FROM lane_a.documents").fetchone()[0]
    redis.Redis(unix_socket_path=os.environ["RSOCK"]).get("rh:plain")
    print(json.dumps({"rows": n}))
'''


class World:
    pass


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    import psycopg
    import redis

    w = World()
    w.root, w.out = tmp_path_factory.mktemp("r3"), tmp_path_factory.mktemp("r3out")
    w.copies = cp.Copies(RUN8, w.root)
    try:
        w.handle = w.copies.start("S")
        with psycopg.connect(cp.pg_dsn(w.handle.pg_socket, DATABASE), autocommit=True) as conn:
            conn.execute("CREATE SCHEMA lane_a")
            conn.execute("CREATE TABLE lane_a.documents (bucket text NOT NULL, id text NOT NULL, body jsonb NOT NULL, "
                         "PRIMARY KEY (bucket, id))")
            conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', 'j1', '{\"n\": 1}')")
        w.redis = redis.Redis(unix_socket_path=str(w.handle.redis_socket / "redis.sock"))
        w.redis.set("rh:plain", "v")
        w.redis.xadd("rh:stream:1", {"k": "v"})
        env = {"PGDSN": cp.pg_dsn(w.handle.pg_socket, DATABASE), "RSOCK": str(w.handle.redis_socket / "redis.sock")}
        w.sides = {}
        for name in ("A", "B"):
            w.sides[name] = r3.Side(name, LeafEnv(env, str(w.root), str(w.root / "S")), {"zeus": [PYTHON, "-c", SNEAKY]})
        w.runs = 0
        yield w
    finally:
        sweep(RUN8, w.root)


def _run(world, nodes, **kwargs):
    world.runs += 1
    catalog = _fixture_catalog(*nodes)
    inventories = {"A": [n for n, _ in nodes], "B": [n for n, _ in nodes]}
    return r3.run_r3(world.sides, world.handle, DATABASE, catalog, r3.load_masks(), world.out / f"r{world.runs}",
                     inventories=inventories, runner=r3.host_runner, **kwargs)


@needs_docker
def test_real_copy_a_pure_reader_leaves_d1_equal_to_d0(world):
    before = r3.snapshot(world.handle, DATABASE)
    document = _run(world, [("zeus fixture status", ["read"])])
    assert document["status"] == "ok" and document["facts"]["d1_equals_d0"] is True
    assert document["facts"]["catalog_sha256_d0"] == before["catalog_sha256"] == cp.catalog_sha256(
        world.handle.pg_socket, DATABASE)
    assert r3.snapshot(world.handle, DATABASE) == before


@needs_docker
def test_real_copy_a_status_leaf_that_secretly_writes_a_row_fails_with_d1_not_equal_d0(world):
    before = cp.catalog_sha256(world.handle.pg_socket, DATABASE)
    with pytest.raises(r3.R3Failed) as caught:
        _run(world, [("zeus fixture status", ["write-pg"])])
    assert caught.value.failures == ["zeus fixture status:not_read_only:A:catalog_sha256"]
    facts = caught.value.document["facts"]
    assert facts["d1_equals_d0"] is False and facts["catalog_sha256_d0"] == before != facts["catalog_sha256_d1"]
    assert json.loads((world.out / f"r{world.runs}" / "r3.json").read_text())["status"] == "failed"  # evidence exists


@needs_docker
def test_real_copy_a_leaf_that_changes_a_redis_value_fails_too_value_sensitive_digest(world):
    world.redis.set("rh:plain", "v")
    with pytest.raises(r3.R3Failed) as caught:
        _run(world, [("zeus fixture status", ["write-redis"])])
    assert caught.value.failures[0].startswith("zeus fixture status:not_read_only:A:redis_prefixes")
    assert world.redis.get("rh:plain") == b"changed"
