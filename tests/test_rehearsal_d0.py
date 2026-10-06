"""Cutover RH-3: the rehearsal R2 "D0" recorder (`compare/rehearsal/d0.py`).

Layer: harness tooling tests (never shipped). Expected results come from the task spec's acceptance criteria and the
rehearsal design "4. R2: D0": the seeded fixture's known counts (computed here from the seed, never from the recorder),
an independent sha256-of-sorted-body-digests oracle, DBSIZE as the Redis coverage oracle, and the pure rules (prefix
rule, module resolution) as examples. The pure tests need no Docker; the copy tests need `ZEUS_TEST_DOCKER=1` and
`ZEUS_TEST_DOCKER_PGEXEC=1`, and a skip under those opt-ins is a failure.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import d0  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1" and os.environ.get(guard.DOCKER_PGEXEC_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
RUN8, DATABASE = "d03a5c7e", "zeus"
B_RELEASE = REPO  # a release dir is `<dir>/src/codex_harness/...`; the repository root has the same shape

FLEET_ARGV = "python -m codex_harness.entry.cli.fleet status"
SHIM_ARGV = "python -m codex_harness.cli --root /x"
# schema -> bucket -> bodies. `lane_a.jobs` carries both a target and a shim argv.
DOCS = {"lane_a": {"jobs": [{"n": 1, "argv": FLEET_ARGV}, {"n": 2, "argv": SHIM_ARGV}, {"n": 3, "note": "body-marker-q7"}],
                   "releases": [{"rev": "r1"}],
                   "hooks": [{"id": "h1", "status": "active"}, {"id": "h2", "status": "rejected"}]},
        "lane_b": {"hooks": [{"id": "h3", "status": "active"}], "jobs": [{"n": 9}]}}


def oracle(bodies) -> str:
    """sha256 of the sorted canonical body digests, newline-joined (the design's R2 per-bucket field)."""
    each = [hashlib.sha256(json.dumps(b, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            for b in bodies]
    return hashlib.sha256("\n".join(sorted(each)).encode()).hexdigest()


# ---- the pure rules (no Docker) ----

@pytest.mark.parametrize("key,prefix", [("a", "a"), ("a:b", "a:b"), ("a:b:c", "a:b"), ("a:b:c:d:e", "a:b"), ("a:", "a:"),
                                        ("", "")])
def test_the_redis_prefix_is_the_key_up_to_two_segments(key, prefix):
    assert d0.redis_prefix(key) == prefix


def test_an_ancestor_prefix_swallows_its_descendants_so_the_inventoried_sets_are_disjoint():
    assert d0.minimal_prefixes(["a", "a:b", "a:b", "ab:c", "x:y", "x:y"]) == ["a", "ab:c", "x:y"]


def test_a_module_resolves_only_inside_the_release_src(tmp_path):
    src = REPO / "src"
    assert d0.resolve_module("codex_harness.entry.cli.fleet", src)
    assert d0.resolve_module("codex_harness.entry", src)  # a package
    assert not d0.resolve_module("codex_harness.nonexistent", src)
    assert not d0.resolve_module("codex_harness.entry.cli.fleet.nope", src)  # below a plain module
    fake = tmp_path / "src"
    (fake / "codex_harness").mkdir(parents=True)
    (fake / "codex_harness" / "__init__.py").write_text("")
    (fake / "codex_harness" / "only_here.py").write_text("")
    assert d0.resolve_module("codex_harness.only_here", fake)
    assert not d0.resolve_module("codex_harness.entry.cli.fleet", fake)  # exists in the repo, not in THIS release
    outside = tmp_path / "outside"
    (outside / "pkg").mkdir(parents=True)
    (outside / "pkg" / "__init__.py").write_text("")
    (fake / "linked").symlink_to(outside / "pkg")
    assert not d0.resolve_module("linked", fake)  # a symlink out of src is not inside the namespace


def test_the_module_pattern_names_dotted_modules_and_stops_before_punctuation():
    assert d0.MODULE.findall("x -m codex_harness.entry.cli.fleet, then codex_harness.cli. and codex_harness") == [
        "codex_harness.entry.cli.fleet", "codex_harness.cli"]


# ---- real Docker: one fixture copy ----

class World:
    pass


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    import psycopg
    import redis

    w = World()
    w.root, w.out = tmp_path_factory.mktemp("d0"), tmp_path_factory.mktemp("d0out")
    w.copies = cp.Copies(RUN8, w.root)
    try:
        w.handle = w.copies.start("S")
        with psycopg.connect(cp.pg_dsn(w.handle.pg_socket, DATABASE), autocommit=True) as conn:
            for schema, buckets in DOCS.items():
                conn.execute(f"CREATE SCHEMA {schema}")
                conn.execute(f"CREATE TABLE {schema}.documents (bucket text NOT NULL, id text NOT NULL, "
                             "body jsonb NOT NULL, PRIMARY KEY (bucket, id))")
                for bucket, bodies in buckets.items():
                    for i, body in enumerate(bodies):
                        conn.execute(f"INSERT INTO {schema}.documents VALUES (%s, %s, %s)",
                                     (bucket, f"id{i}", json.dumps(body)))
            conn.execute("CREATE TABLE lane_a.knowledge_nodes (id text PRIMARY KEY, repository text NOT NULL, "
                         "kind text NOT NULL, body text NOT NULL)")
            conn.execute("INSERT INTO lane_a.knowledge_nodes VALUES ('n1','r','k','one'), ('n2','r','k','two')")
            conn.execute("CREATE TABLE lane_a.knowledge_edges (source text, target text, kind text)")
            conn.execute("INSERT INTO lane_a.knowledge_edges VALUES ('n1','n2','calls')")
            conn.execute("CREATE TABLE lane_a.schema_migrations (module text, version text, checksum text, "
                         "PRIMARY KEY (module, version))")
            conn.execute("INSERT INTO lane_a.schema_migrations VALUES ('core','002','x'), ('core','001','y')")
            w.knowledge_digest = conn.execute(
                "SELECT encode(sha256(convert_to(string_agg(t::text, E'\\n' ORDER BY t::text), 'UTF8')), 'hex') "
                "FROM lane_a.knowledge_nodes t").fetchone()[0]
        w.redis = redis.Redis(unix_socket_path=str(w.handle.redis_socket / "redis.sock"))
        for _ in range(3):
            w.redis.xadd("rh:stream:1", {"k": "v"})
        w.redis.set("rh:plain", "v")
        w.redis.set("deep:x:y:z", "v")
        w.runs = 0
        yield w
    finally:
        sweep(RUN8, w.root)


def _record(world, **kwargs):
    world.runs += 1
    return d0.record_d0(world.handle, B_RELEASE, world.out / f"r{world.runs}", database=DATABASE, **kwargs)


@contextlib.contextmanager
def _planted(world, schema_body=None, key=None):
    import psycopg

    try:
        if schema_body is not None:
            with psycopg.connect(cp.pg_dsn(world.handle.pg_socket, DATABASE), autocommit=True) as conn:
                conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', 'planted', %s)", (json.dumps(schema_body),))
        if key is not None:
            world.redis.set(key, "v")
        yield
    finally:
        if schema_body is not None:
            with psycopg.connect(cp.pg_dsn(world.handle.pg_socket, DATABASE), autocommit=True) as conn:
                conn.execute("DELETE FROM lane_a.documents WHERE id = 'planted'")
        if key is not None:
            world.redis.delete(key)


@needs_docker
def test_d0_records_the_fixtures_known_buckets_knowledge_migrations_hooks_and_redis(world):
    facts = _record(world)["facts"]
    assert facts["failures"] == [] and facts["read_only"] is True
    for schema, buckets in DOCS.items():
        assert facts["buckets"][schema] == {b: {"count": len(v), "digest": oracle(v)} for b, v in sorted(buckets.items())}
        everything = [x for v in buckets.values() for x in v]
        assert facts["schema_totals"][schema] == {"count": len(everything), "digest": oracle(everything)}
    assert facts["buckets"]["lane_a"]["jobs"]["count"] == 3 and facts["buckets"]["lane_a"]["releases"]["count"] == 1
    assert facts["knowledge"] == {"lane_a": {"knowledge_nodes": {"count": 2, "digest": world.knowledge_digest},
                                             "knowledge_edges": {"count": 1, "digest": facts["knowledge"]["lane_a"][
                                                 "knowledge_edges"]["digest"]}}}
    assert len(facts["knowledge"]["lane_a"]["knowledge_edges"]["digest"]) == 64
    assert facts["migrations"] == {"lane_a": ["core/001", "core/002"]}
    assert facts["hooks"] == {"documents_present": True, "active": 2, "by_status": {"active": 2, "rejected": 1}}
    assert facts["redis_dbs"] == {"db0": {"dbsize": 3, "inventoried": 3, "uncovered": 0, "prefixes": 3}}
    prefixes = facts["redis_prefixes"]
    assert set(prefixes) == {"db0|rh:stream", "db0|rh:plain", "db0|deep:x"}
    assert (prefixes["db0|rh:stream"]["streams"], prefixes["db0|rh:stream"]["stream_entries"]) == (1, 3)
    assert prefixes["db0|rh:plain"]["keys"] == 1 and prefixes["db0|deep:x"]["keys"] == 1
    assert facts["argv_modules"] == {
        "codex_harness.cli": {"count": 1, "resolved": True, "class": "shim", "flag": "E5b"},
        "codex_harness.entry.cli.fleet": {"count": 1, "resolved": True, "class": "target"}}
    assert facts["argv_unresolved"] == [] and len(facts["catalog_sha256"]) == 64


@needs_docker
def test_d0_holds_no_record_body_only_names_counts_and_digests(world):
    _record(world)
    text = (world.out / f"r{world.runs}" / "d0.json").read_text()
    for body_text in ("body-marker-q7", "python -m", "--root", "calls", '"note"', '"argv"'):
        assert body_text not in text, body_text


@needs_docker
def test_two_runs_over_the_same_copy_differ_only_in_the_at_field(world):
    ticks = iter(("2026-01-01T00:00:00.000+00:00", "2027-02-02T00:00:00.000+00:00"))
    d0_a = d0.record_d0(world.handle, B_RELEASE, world.out / "det-a", database=DATABASE, clock=lambda: next(ticks))
    d0_b = d0.record_d0(world.handle, B_RELEASE, world.out / "det-b", database=DATABASE, clock=lambda: next(ticks))
    raw_a, raw_b = ((world.out / n / "d0.json").read_bytes() for n in ("det-a", "det-b"))
    assert raw_a != raw_b and d0_a["at"] != d0_b["at"]
    assert raw_a.replace(d0_a["at"].encode(), b"T") == raw_b.replace(d0_b["at"].encode(), b"T")


@needs_docker
def test_a_planted_unresolvable_argv_is_reported_and_fails_the_record(world):
    with _planted(world, schema_body={"argv": ["python", "-m", "codex_harness.nonexistent"]}):
        with pytest.raises(d0.D0Failed) as caught:
            _record(world)
    assert "argv_module_unresolved:codex_harness.nonexistent" in caught.value.failures
    written = json.loads((world.out / f"r{world.runs}" / "d0.json").read_text())
    assert written["status"] == "failed"
    assert written["facts"]["argv_unresolved"] == ["codex_harness.nonexistent"]
    assert written["facts"]["argv_modules"]["codex_harness.nonexistent"] == {"count": 1, "resolved": False,
                                                                           "class": "unclassified"}
    assert _record(world)["status"] == "ok"  # the plant is gone: the same copy records clean again


@needs_docker
def test_a_key_outside_the_derived_prefixes_fails_dbsize_coverage_with_the_uncovered_count(world):
    with _planted(world, key="zz:orphan:1"):
        assert _record(world)["facts"]["redis_dbs"]["db0"]["uncovered"] == 0  # derived prefixes see the new key
        with pytest.raises(d0.D0Failed) as caught:  # a restricted list cannot
            _record(world, prefixes=["rh:stream", "rh:plain", "deep:x"])
    assert caught.value.failures == ["redis_uncovered:db0:1"]
    db = caught.value.document["facts"]["redis_dbs"]["db0"]
    assert (db["dbsize"], db["inventoried"], db["uncovered"]) == (4, 3, 1)


@needs_docker
def test_d0_never_writes_to_the_copy_its_catalog_digest_is_unchanged(world):
    before = cp.catalog_sha256(world.handle.pg_socket, DATABASE)
    document = _record(world)
    assert cp.catalog_sha256(world.handle.pg_socket, DATABASE) == before
    assert document["facts"]["catalog_sha256"] == before == document["facts"]["catalog_sha256_after"]
    assert world.redis.dbsize() == 3


@needs_docker
def test_an_existing_d0_json_is_never_overwritten(world):
    out = world.out / "once"
    d0.record_d0(world.handle, B_RELEASE, out, database=DATABASE)
    before = (out / "d0.json").read_bytes()
    with pytest.raises(d0.Refused) as caught:
        d0.record_d0(world.handle, B_RELEASE, out, database=DATABASE)
    assert caught.value.code == "evidence_exists" and (out / "d0.json").read_bytes() == before


# ---- RH-1b: the d0a/d0b restored-catalog bracket (`compare/rehearsal/bracket.py`) ----
# Expected results: the rehearsal design "2. PHASE P" verdicts ("If equal: production was quiescent ... If unequal:
# D0 := d0a. List the differing relations and declare the cross-store skew; PEL-owner checks are then informational").
# The oracle is the fixture's own history (a row is added between the dumps), never the bracket's output.

from rehearsal import bracket as brk  # noqa: E402

BRACKET_RUN8, BRACKET_DB = "b4c7e19a", "rhb"


def _catalog(rows, sha, extra=None):
    relations = {"items": {"kind": "r", "columns": [["id", "integer"]], "rows": rows, "rows_sha256": sha}}
    relations.update(extra or {})
    return {"schema": "x", "database": "rhb", "server_version_num": 170000, "extensions": [], "extension_members": [],
            "schemas": {"app": {"owner": "zeus", "acl": None, "comment": None, "relations": relations, "indexes": [],
                                "constraints": [], "sequences": [], "views": [], "functions": [], "triggers": []}}}


def test_equal_catalogs_are_quiescent_and_keep_the_pel_owner_checks_enforced():
    facts = brk.compare_catalogs(_catalog(3, "a" * 64), _catalog(3, "a" * 64))
    assert facts["quiescent"] is True and facts["cross_store_skew"] is False and facts["differing"] == []
    assert facts["d0"] == "d0a" and facts["pel_owner_checks"] == "enforced" and "catalog_only_difference" not in facts
    assert facts["catalog_sha256"]["d0a"] == facts["catalog_sha256"]["d0b"]


def test_a_relation_with_one_more_row_declares_the_skew_names_it_and_keeps_d0_a():
    facts = brk.compare_catalogs(_catalog(3, "a" * 64), _catalog(4, "b" * 64))
    assert facts["quiescent"] is False and facts["cross_store_skew"] is True and facts["d0"] == "d0a"
    assert facts["differing"] == ["app.items"] and facts["differing_counts"] == {"app.items": {"d0a": 3, "d0b": 4}}
    assert facts["pel_owner_checks"] == "informational" and facts["catalog_only_difference"] is False


def test_a_relation_present_on_one_side_only_and_a_same_count_digest_change_are_differences():
    extra = {"added": {"kind": "r", "columns": [], "rows": 2, "rows_sha256": "c" * 64}}
    facts = brk.compare_catalogs(_catalog(3, "a" * 64), _catalog(3, "b" * 64, extra))
    assert facts["differing"] == ["app.added", "app.items"]
    assert facts["differing_counts"] == {"app.added": {"d0a": None, "d0b": 2}, "app.items": {"d0a": 3, "d0b": 3}}


def test_a_catalog_difference_outside_the_row_digests_is_skew_with_no_named_relation():
    other = _catalog(3, "a" * 64)
    other["schemas"]["app"]["owner"] = "someone_else"
    facts = brk.compare_catalogs(_catalog(3, "a" * 64), other)
    assert facts["quiescent"] is False and facts["differing"] == [] and facts["catalog_only_difference"] is True


@pytest.fixture(scope="module")
def bracket_world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    import psycopg

    w = World()
    w.root, w.out = tmp_path_factory.mktemp("brk"), tmp_path_factory.mktemp("brkout")
    w.copies = cp.Copies(BRACKET_RUN8, w.root)
    try:
        src = w.copies.start("A")
        with psycopg.connect(cp.pg_dsn(src.pg_socket), autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {BRACKET_DB}")
        with psycopg.connect(cp.pg_dsn(src.pg_socket, BRACKET_DB), autocommit=True) as conn:
            conn.execute("CREATE SCHEMA app")
            conn.execute("CREATE TABLE app.fleet_jobs (id integer PRIMARY KEY, name text)")
            conn.execute("CREATE TABLE app.steady (id integer PRIMARY KEY)")
            conn.execute("INSERT INTO app.fleet_jobs SELECT g, 'job-' || g FROM generate_series(1, 5) g")
            conn.execute("INSERT INTO app.steady SELECT g FROM generate_series(1, 3) g")
            _dump(w, "d0a.dump")
            _dump(w, "d0b-equal.dump")
            conn.execute("INSERT INTO app.fleet_jobs VALUES (6, 'job-6')")  # production moved between the dumps
            _dump(w, "d0b-skew.dump")
        for name, dump in (("S", "d0a.dump"), ("seal-b", "d0b-equal.dump"), ("B", "d0b-skew.dump")):
            w.copies.start(name)
            w.copies.restore(name, dump, BRACKET_DB)
        yield w
    finally:
        sweep(BRACKET_RUN8, w.root)


def _dump(world, name):
    import subprocess

    env = {**os.environ, guard.DOCKER_OPT_IN_ENV: "1", guard.DOCKER_PGEXEC_ENV: "1",
           guard.DOCKER_BIND_ROOT_ENV: str(world.root)}
    argv = ["docker", "exec", world.copies.copies["A"].pg_name, "pg_dump", "-U", "zeus", "-h", cp.PG_SOCKET_DIR, "-Fc",
            BRACKET_DB]
    guard.docker_policy(argv, env)
    done = subprocess.run(argv, env=env, capture_output=True, timeout=300)
    assert done.returncode == 0, done.stderr[-300:]
    (world.copies.source / name).write_bytes(done.stdout)


@needs_docker
def test_equal_restored_dumps_are_quiescent(bracket_world):
    c = bracket_world.copies.copies
    facts = brk.bracket(c["S"], c["seal-b"], BRACKET_DB)
    assert facts["quiescent"] is True and facts["differing"] == [] and facts["relations_compared"] == 2
    assert facts["catalog_sha256"]["d0a"] == bracket_world.copies.catalog_sha256("S", BRACKET_DB)


@needs_docker
def test_a_row_added_between_the_dumps_declares_the_skew_with_that_relation_and_d0_is_d0a(bracket_world):
    c = bracket_world.copies.copies
    facts = brk.bracket(c["S"], c["B"], BRACKET_DB)
    assert facts["quiescent"] is False and facts["cross_store_skew"] is True and facts["d0"] == "d0a"
    assert facts["differing"] == ["app.fleet_jobs"]  # app.steady did not move
    assert facts["differing_counts"] == {"app.fleet_jobs": {"d0a": 5, "d0b": 6}}
    assert facts["pel_owner_checks"] == "informational"


@needs_docker
def test_d0_json_carries_the_bracket_and_a_bracket_that_is_not_d0a_fails_the_record(bracket_world):
    c = bracket_world.copies.copies
    facts = brk.bracket(c["S"], c["B"], BRACKET_DB)
    document = d0.record_d0(c["S"], B_RELEASE, bracket_world.out / "ok", database=BRACKET_DB, bracket=facts)
    assert document["status"] == "ok" and document["facts"]["bracket"] == facts
    on_disk = json.loads((bracket_world.out / "ok" / "d0.json").read_text())
    assert on_disk["facts"]["bracket"]["differing"] == ["app.fleet_jobs"] and on_disk["facts"]["failures"] == []
    swapped = brk.bracket(c["B"], c["S"], BRACKET_DB)  # d0a would be the copy B, not S
    with pytest.raises(d0.D0Failed) as info:
        d0.record_d0(c["S"], B_RELEASE, bracket_world.out / "swapped", database=BRACKET_DB, bracket=swapped)
    assert "bracket_d0a_is_not_this_copy" in info.value.failures
