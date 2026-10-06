"""Cutover RH-4b: the rehearsal R4 read-compat sweep (`compare/rehearsal/r4.py`, `r4-readers.json`).

Layer: harness tooling tests (never shipped). Expected results come from the task spec's acceptance criteria and the
rehearsal design "6. R4" / AMD-1 A/B: coverage must equal the D0 bucket set, a bucket with no B reader is a failure (never
a skip), PASS = failures(B) == failures(A) except declared intended differences, a failure is (bucket, id, class, code)
and carries no body. The runner tests drive the public `run_r4` over a real disposable PostgreSQL/Redis copy with tiny
fixture revisions (a fake `src/codex_harness` per side, whose reader functions are the fixtures' own constants); the
pure tests need no Docker; the copy tests need `ZEUS_TEST_DOCKER=1` and `ZEUS_TEST_DOCKER_PGEXEC=1`, and a skip under
those opt-ins is a failure.

Structural checks (named): `test_every_typed_reader_resolves_*` is a PROVENANCE check (a catalog citation names a def
that exists in its tree and is callable by the sweep); `test_the_catalog_owners_*` is an OWNED_BUCKETS-PRESERVATION check
(the catalog owner of a bucket is the target context that declares it). Neither is behavioural acceptance of a reader.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import textwrap

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import r3, r4  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1" and os.environ.get(guard.DOCKER_PGEXEC_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
RUN8, DATABASE = "b4e7c9a1", "zeus"
PYTHON = sys.executable


@pytest.fixture(scope="module")
def catalog():
    return r4.load_catalog()


# ---- the shipped catalog ----

def test_the_catalog_owners_are_the_target_owned_buckets_and_every_owned_bucket_is_cataloged(catalog):
    """STRUCTURAL (OWNED_BUCKETS preservation): the catalog owner of a bucket is the target context declaring it."""
    owned = {}
    for path in sorted((REPO / "src" / "codex_harness").glob("*/ports.py")):
        module = importlib.import_module(f"codex_harness.{path.parent.name}.ports")
        for bucket in getattr(module, "OWNED_BUCKETS", ()):
            owned[bucket] = path.parent.name
    assert len(owned) == 185
    assert {b: row["owner"] for b, row in catalog["buckets"].items() if "amd1" not in row} == owned
    declared = {b for b, row in catalog["buckets"].items() if "amd1" in row}
    assert declared == {"fleet_admission_permits"}  # the FA permit bucket (AMD-1 B) is the one bucket beyond OWNED_BUCKETS
    assert catalog["buckets"]["fleet_admission_permits"]["amd1"] == "B"


def test_the_s2r_shapes_and_the_fa_permit_bucket_are_listed_explicitly(catalog):
    shapes = {item["shape"].split(" (")[0] for item in catalog["s2r"]}
    assert shapes == {"intent `generations`", "maintenance rows", "release-queue maintenance scope `host_delivery_maintenance`"}
    assert {item["bucket"] for item in catalog["s2r"]} == {"host_delivery_intents", "release_queue"}
    assert catalog["buckets"]["host_delivery_intents"]["A"]["reader"].endswith(":maintenance_of")
    # this tree has no S2R reader: B is `none` with the reason naming its unit, so the sweep fails here by design
    assert catalog["buckets"]["host_delivery_intents"]["B"]["reader"] is None
    assert "G1" in catalog["buckets"]["host_delivery_intents"]["B"]["reason"]
    assert catalog["buckets"]["fleet_admission_permits"]["B"]["reader"] is None


def test_every_typed_reader_resolves_in_its_tree_and_is_callable_by_the_sweep_provenance_check(catalog):
    """STRUCTURAL (provenance): each cited def exists in its column's tree, is a module function or staticmethod, and
    needs no more inputs than its declared call form supplies."""
    trees = {"A": catalog["trees"]["A"], "B": catalog["trees"]["B"], **catalog["trees"]["D"]}
    rows = [(name, row) for name, row in [*catalog["buckets"].items(), *catalog["redis"].items()]]
    problems = []
    typed = 0
    for name, row in rows:
        columns = {"A": row["A"], "B": row["B"], **row["D"]}
        for column, entry in columns.items():
            typed += entry["reader"] is not None
            problem = r4.reader_problem(entry, trees[column])
            if problem:
                problems.append((name, column, problem))
    assert problems == [] and typed > 40


def test_a_none_entry_always_carries_a_reason_and_a_typed_entry_a_call_form(catalog):
    for name, row in [*catalog["buckets"].items(), *catalog["redis"].items()]:
        for entry in [row["A"], row["B"], *row["D"].values()]:
            assert (entry["reader"] is None and entry["reason"].strip()) or entry["call"] in r4.CALLS, name


@pytest.mark.parametrize("mutate", [
    lambda c: c["buckets"]["tasks"].pop("B"),
    lambda c: c["buckets"]["tasks"]["B"].update(reason=" "),
    lambda c: c["buckets"]["tasks"]["D"].pop("08bb9a44"),
    lambda c: c["buckets"]["tasks"].update(owner=""),
    lambda c: c.update(declared=[{"side": "B", "bucket": "tasks", "class": "X", "code": "y", "reason": "r"}]),  # no amd1
    lambda c: c["redis"]["agent_stream"].update(key_re="("),
])
def test_a_malformed_catalog_is_refused(catalog, mutate):
    broken = copy.deepcopy(catalog)
    mutate(broken)
    with pytest.raises(r4.Refused) as caught:
        r4.validate_catalog(broken)
    assert caught.value.code == "catalog_malformed"


# ---- coverage ----

def _mini(a_reader=("fx/readers.py:read_job", "body"), b_reader=("fx/readers.py:read_job", "body"), declared=()):
    def entry(spec):
        return {"reader": None, "reason": "fixture: no typed reader"} if spec is None else {"reader": spec[0], "call": spec[1]}
    stream = ("fx/readers.py:check_message", "body")
    return {"version": 1,
            "trees": {"A": {"rev": None, "root": "unused"}, "B": {"rev": None, "root": "unused"}, "D": {}},
            "buckets": {"jobs": {"owner": "fixture", "A": entry(a_reader), "B": entry(b_reader), "D": {}},
                        "notes": {"owner": "fixture", "A": entry(None), "B": entry(None), "D": {}}},
            "redis": {"agent_stream": {"owner": "fixture", "prefix_re": r"rh:agent", "key_re": r"rh:agent:.+",
                                       "A": entry(stream), "B": entry(stream), "D": {}}},
            "declared": list(declared)}


def _d0(buckets=None, prefixes=("db0|rh:agent",)):
    buckets = buckets if buckets is not None else {"lane_a": {"jobs": {}, "notes": {}}}
    return {"facts": {"buckets": buckets, "redis_prefixes": {p: {} for p in prefixes}}}


def test_a_bucket_unknown_to_the_catalog_is_a_coverage_failure_listing_it():
    report = r4.coverage(_mini(), _d0({"lane_a": {"jobs": {}, "mystery": {}}, "lane_b": {"other": {}}})["facts"])
    assert report["missing"] == ["coverage_missing:mystery", "coverage_missing:other"]
    assert report["catalog_only"] == ["notes"]  # in the catalog, not in this D0: reported, never a failure
    assert r4.coverage(_mini(), _d0()["facts"])["missing"] == []


def test_a_redis_prefix_no_namespace_covers_is_a_coverage_failure():
    report = r4.coverage(_mini(), _d0(prefixes=("db0|rh:agent", "db0|stray:key"))["facts"])
    assert report["missing"] == ["coverage_missing:redis:stray:key"]


def test_the_runner_refuses_an_uncovered_d0_before_any_child_starts(tmp_path):
    calls = []
    with pytest.raises(r4.R4Failed) as caught:
        r4.run_r4({}, None, DATABASE, _mini(), _d0({"lane_a": {"jobs": {}, "mystery": {}}}), tmp_path / "c",
                  runner=lambda *a: calls.append(a))
    assert caught.value.failures == ["coverage_missing:mystery"] and calls == []
    assert json.loads((tmp_path / "c" / "r4.json").read_text())["status"] == "failed"  # the evidence exists


# ---- declared intended differences (pure) ----

def test_a_declared_difference_is_absorbed_only_on_its_side_bucket_class_and_code():
    declared = [{"side": "B", "bucket": "jobs", "class": "Refusal", "code": "legacy", "amd1": "A", "reason": "r"}]
    catalog = {"declared": declared}
    hit = ["lane_a", "jobs", "j9", "Refusal", "legacy"]
    rest, report = r4.declared_split(catalog, {"A": [], "B": [hit]})
    assert rest == {"A": [], "B": []} and report == [{"bucket": "jobs", "side": "B", "amd1": "A", "absorbed": 1}]
    for other in (["lane_a", "jobs", "j9", "Refusal", "other"], ["lane_a", "jobs", "j9", "ContractError", "legacy"],
                  ["lane_a", "notes", "j9", "Refusal", "legacy"]):
        assert r4.declared_split(catalog, {"A": [], "B": [other]})[0]["B"] == [other]
    assert r4.declared_split(catalog, {"A": [hit], "B": []})[0]["A"] == [hit]  # declared for B only


# ---- the sweep over a real copy, with fixture revisions ----

READERS = {
    "A": '''
        class ContractError(ValueError):
            pass


        class Refusal(Exception):
            def __init__(self, code):
                super().__init__("body-value-in-message-A")
                self.reason_code = code


        def read_job(body):
            if not isinstance(body.get("n"), int):
                raise Refusal("bad_n")
            return body


        def check_message(doc):
            if "who" not in doc:
                raise ContractError("secret-body-value-A")
            return doc
    ''',
    "B": '''
        class ContractError(ValueError):
            pass


        class Refusal(Exception):
            def __init__(self, code):
                super().__init__("reworded-B")
                self.reason_code = code


        def read_job(body):
            if not isinstance(body.get("n"), int):
                raise Refusal("bad_n")
            if body.get("legacy") is True:
                raise Refusal("legacy_shape")
            return body


        def check_message(doc):
            if "who" not in doc:
                raise ContractError("secret-body-value-B")
            return doc
    ''',
}


class World:
    pass


def _tree(root, side):
    package = root / side / "src" / "codex_harness"
    (package / "fx").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "fx" / "__init__.py").write_text("")
    (package / "fx" / "readers.py").write_text(textwrap.dedent(READERS[side]))
    return str(root / side / "src")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    import psycopg
    import redis

    w = World()
    w.root, w.out = tmp_path_factory.mktemp("r4"), tmp_path_factory.mktemp("r4out")
    w.copies = cp.Copies(RUN8, w.root)
    try:
        w.handle = w.copies.start("S")
        with psycopg.connect(cp.pg_dsn(w.handle.pg_socket, DATABASE), autocommit=True) as conn:
            conn.execute("CREATE SCHEMA lane_a")
            conn.execute("CREATE TABLE lane_a.documents (bucket text NOT NULL, id text NOT NULL, body jsonb NOT NULL, "
                         "PRIMARY KEY (bucket, id))")
            for ident, body in (("j1", {"n": 1}), ("j2", {"n": 2}), ("bad", {"n": "x", "marker": "body-marker-q7"})):
                conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', %s, %s)", (ident, json.dumps(body)))
            conn.execute("INSERT INTO lane_a.documents VALUES ('notes', 'n1', '{\"free\": true}')")
        w.redis = redis.Redis(unix_socket_path=str(w.handle.redis_socket / "redis.sock"))
        w.redis.xadd("rh:agent:one", {"body": json.dumps({"who": "x"})})
        w.redis.xadd("rh:agent:one", {"body": json.dumps({"nobody": "secret-body-value-in-data"})})
        w.src = {side: _tree(w.root, side) for side in ("A", "B")}
        w.runs = 0
        yield w
    finally:
        sweep(RUN8, w.root)


def _sides(world, src=None):
    src = src or world.src
    return {name: r4.R4Side(name, r3.Side(name, {}, {"python": [PYTHON]}), src[name]) for name in ("A", "B")}


def _run(world, catalog, **kwargs):
    world.runs += 1
    return r4.run_r4(_sides(world, kwargs.pop("src", None)), world.handle, DATABASE, catalog, _d0(),
                     world.out / f"r{world.runs}", runner=r3.host_runner, timeout=120.0, **kwargs)


@needs_docker
def test_an_identical_failure_on_both_sides_passes_and_carries_no_body_or_message(world):
    document = _run(world, _mini())
    facts = document["facts"]
    assert document["status"] == "ok" and facts["failures"] == []
    # the same unreadable row (jobs/bad: Refusal bad_n), the same invalid stream entry and the same `none` bucket
    # (notes: NoReader on both columns) fail on BOTH sides: three common failures, none side-only
    assert facts["failures_by_side"] == {"A": 3, "B": 3} and facts["common_failures"] == 3
    text = (world.out / f"r{world.runs}" / "r4.json").read_text()
    for forbidden in ("body-marker-q7", "secret-body-value", "body-value-in-message", "reworded-B"):
        assert forbidden not in text
    assert facts["rows_read"] == {"A": 3 + 2, "B": 3 + 2}  # jobs rows + stream entries (notes has no reader)


@needs_docker
def test_an_unreadable_row_on_b_only_fails_with_its_bucket_id_class_and_code(world):
    import psycopg

    with psycopg.connect(cp.pg_dsn(world.handle.pg_socket, DATABASE), autocommit=True) as conn:
        conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', 'j-legacy', '{\"n\": 5, \"legacy\": true}') "
                     "ON CONFLICT DO NOTHING")
    try:
        with pytest.raises(r4.R4Failed) as caught:
            _run(world, _mini())
    finally:
        with psycopg.connect(cp.pg_dsn(world.handle.pg_socket, DATABASE), autocommit=True) as conn:
            conn.execute("DELETE FROM lane_a.documents WHERE id = 'j-legacy'")
    assert caught.value.failures == ["B_only:(lane_a, jobs, j-legacy, Refusal, legacy_shape)"]
    assert caught.value.document["facts"]["only_listed"]["B"] == [["lane_a", "jobs", "j-legacy", "Refusal", "legacy_shape"]]


@needs_docker
def test_a_declared_intended_difference_passes_and_an_undeclared_one_fails(world):
    import psycopg

    declared = {"side": "B", "bucket": "jobs", "class": "Refusal", "code": "legacy_shape", "amd1": "A",
                "reason": "fixture: the legacy shape is retired on B"}
    with psycopg.connect(cp.pg_dsn(world.handle.pg_socket, DATABASE), autocommit=True) as conn:
        conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', 'j-legacy', '{\"n\": 5, \"legacy\": true}') "
                     "ON CONFLICT DO NOTHING")
    try:
        document = _run(world, _mini(declared=[declared]))
        assert document["status"] == "ok" and document["facts"]["declared"] == [
            {"bucket": "jobs", "side": "B", "amd1": "A", "absorbed": 1}]
        for wrong in ({"code": "other_code"}, {"bucket": "notes"}, {"side": "A"}, {"class": "ContractError"}):
            with pytest.raises(r4.R4Failed) as caught:
                _run(world, _mini(declared=[{**declared, **wrong}]))
            assert caught.value.failures == ["B_only:(lane_a, jobs, j-legacy, Refusal, legacy_shape)"], wrong
    finally:
        with psycopg.connect(cp.pg_dsn(world.handle.pg_socket, DATABASE), autocommit=True) as conn:
            conn.execute("DELETE FROM lane_a.documents WHERE id = 'j-legacy'")


@needs_docker
def test_a_bucket_with_a_reader_on_a_but_none_on_b_fails_and_treating_none_as_a_skip_would_hide_it(world, monkeypatch):
    """The mutation proof: a `none` B reader fails as NoReader; with the sweep mutated to skip NoReader failures (the
    disabled accounting) the same run passes, so the detection is exactly the NoReader failure."""
    broken = _mini(b_reader=None)
    with pytest.raises(r4.R4Failed) as caught:
        _run(world, broken)
    assert caught.value.failures == ["A_only:(lane_a, jobs, bad, Refusal, bad_n)",
                                     "B_only:(lane_a, jobs, *, NoReader, none)"]
    original = r4.sweep_side

    def skipping(*args, **kwargs):
        result = original(*args, **kwargs)
        result["failures"] = [f for f in result["failures"] if f[3] != "NoReader"]
        return result

    monkeypatch.setattr(r4, "sweep_side", skipping)
    with pytest.raises(r4.R4Failed) as still:  # A's unreadable row is still A-only (B reads nothing of jobs)
        _run(world, broken)
    assert still.value.failures == ["A_only:(lane_a, jobs, bad, Refusal, bad_n)"]  # the NoReader failure is gone


@needs_docker
def test_a_side_whose_src_is_not_the_revision_it_claims_is_refused_not_passed(world, tmp_path):
    (tmp_path / "empty-src").mkdir()
    with pytest.raises(r4.R4Failed) as caught:
        _run(world, _mini(), src={"A": str(tmp_path / "empty-src"), "B": world.src["B"]})
    assert "origin_refused:A:3" in caught.value.failures


@needs_docker
def test_a_sweep_that_changes_the_copy_fails_as_not_read_only(world):
    states = iter(["d0", "d0", "moved", "moved"])

    def snap(copy, database):
        return {"catalog_sha256": next(states), "redis_dbs": {}, "redis_prefixes": {}, "redis_failures": []}

    with pytest.raises(r4.R4Failed) as caught:
        _run(world, _mini(), snap=snap)
    assert "not_read_only:B:catalog_sha256" in caught.value.failures  # A's run saw d0 -> d0, B's d0 -> moved


@needs_docker
def test_the_copy_is_unchanged_by_the_sweep(world):
    before = r3.snapshot(world.handle, DATABASE)
    _run(world, _mini())
    assert r3.snapshot(world.handle, DATABASE) == before
