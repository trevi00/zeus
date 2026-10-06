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
    # the FA permit bucket (AMD-1 B) and its PR-3 successor are the buckets beyond this checkout's OWNED_BUCKETS
    assert declared == {"fleet_admission_permits", "fleet_maintenance_admissions"}
    assert catalog["buckets"]["fleet_admission_permits"]["amd1"] == "B"
    assert catalog["buckets"]["fleet_maintenance_admissions"]["owner"] == "coordination"


def test_the_s2r_shapes_and_the_fa_permit_bucket_are_listed_explicitly(catalog):
    shapes = {item["shape"].split(" (")[0] for item in catalog["s2r"]}
    assert shapes == {"intent `generations`", "maintenance rows", "release-queue maintenance scope `host_delivery_maintenance`"}
    assert {item["bucket"] for item in catalog["s2r"]} == {"host_delivery_intents", "release_queue"}
    assert catalog["buckets"]["host_delivery_intents"]["A"]["reader"].endswith(":maintenance_of")
    # the B tree (G1-13a) carries the S2R reader: the intent bucket's B entry is that reader, in the delivery context
    assert catalog["buckets"]["host_delivery_intents"]["B"]["reader"] == "delivery/domain/host_delivery.py:maintenance_of"
    assert all(item["B"].startswith(("delivery/domain/host_delivery.py:maintenance_of", "review/application/release_queue.py"))
               for item in catalog["s2r"])
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


# ---- the cutover columns and the PR-3 bucket (RH-4c; AMD-1 errata E2/E6, reconciliation DD-19/DD-20) ----

PINS = {"A": "bb579d558cd5902fa9d6493fad9b92ebd5be4b68", "B": "8be54d0a336bf0e8c7b609274ec1334e16468a37",
        "1b9d746c": "1b9d746c52ab1a116beda5c72a23f86903aeb4f3", "ec8aa0a2": "ec8aa0a2947f964eeb94faed20cb6cf05e0681f6"}
OLD_D = ["08bb9a44", "5aa220fd", "ced20281", "5c67f099"]


def test_the_columns_are_the_cutover_pins_and_the_existing_d_columns_stay(catalog):
    """The pinned revisions are the owner decisions (spec RH-4c item 1), not read back from the catalog's own output."""
    trees = catalog["trees"]
    assert trees["A"]["rev"] == PINS["A"] and "rebaseline entry 2" in trees["A"]["label"]
    assert trees["B"]["rev"] == PINS["B"] and "final regeneration at CUT-INT on H" in trees["B"]["label"]
    assert list(trees["D"]) == [*OLD_D, "1b9d746c", "ec8aa0a2"]
    assert {n: trees["D"][n]["rev"] for n in ("1b9d746c", "ec8aa0a2")} == {n: PINS[n] for n in ("1b9d746c", "ec8aa0a2")}
    assert all(t["root"] == "src/codex_harness" for t in [trees["A"], trees["B"], *trees["D"].values()])
    for row in [*catalog["buckets"].values(), *catalog["redis"].values()]:
        assert list(row["D"]) == [*OLD_D, "1b9d746c", "ec8aa0a2"]


def test_the_pr3_bucket_has_a_reader_per_column_or_the_pr3_reason(catalog):
    row = catalog["buckets"]["fleet_maintenance_admissions"]
    assert row["owner"] == "coordination"
    for column in OLD_D + ["ec8aa0a2"]:  # trees that predate PR-3 (or the stripped payload): no such bucket
        assert row["D"][column] == {"reader": None, "reason": "bucket introduced by PR-3"}, column
    assert row["A"] == {"reader": "domain/fleet_maintenance.py:permit_view", "call": "body"}  # bb579d55 carries it
    assert row["D"]["1b9d746c"] == row["A"]
    assert row["B"] == {"reader": "coordination/domain/fleet_maintenance.py:permit_view", "call": "body"}


def test_the_scan_is_idempotent_and_refuses_a_citation_it_cannot_trace(catalog):
    assert r4.regenerate(catalog) == catalog
    older = copy.deepcopy(catalog)
    older["trees"]["B"] = {"rev": None, "root": "src/codex_harness", "label": "this checkout"}  # force a re-scan of B
    again = r4.regenerate(older)
    assert again["buckets"]["host_delivery_intents"]["B"] == catalog["buckets"]["host_delivery_intents"]["B"]
    assert r4.trace_entry({"reader": "domain/nope.py:missing", "call": "body"}, catalog["trees"]["A"])["reader"] is None


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


# ---- the read-coverage map (RH-4c; reconciliation DD-19, critic #14 / AC7) ----
# Expected results: PostgreSQL's `log_statement=all` format (`LOG:  execute <name>: <sql>` then `DETAIL:  Parameters:
# $1 = '...'`; observed on the pinned PostgreSQL 17 image, earlier releases print `parameters:`) and the spec's rules:
# typed / leaf-covered / uncovered, the parse fails closed on an unparseable records-table statement, and
# `uncovered > 0` is never a pass.

HEAD = "2026-10-06 12:00:00.123 UTC [77] "


def _log(*entries):
    """Entries are `(level, message)`; a message with newlines continues on tab-led lines like PostgreSQL's own."""
    return "".join(HEAD + f"{level}:  " + message.replace("\n", "\n\t") + "\n" for level, message in entries)


def test_the_log_parser_reads_the_bucket_of_a_parameterized_a_literal_and_a_multiline_statement():
    text = _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE bucket=$1 ORDER BY id"),
                ("DETAIL", "Parameters: $1 = 'tasks'"),
                ("LOG", "execute _pg3_0: SELECT body FROM lane_a.documents WHERE bucket=$1\nAND id=$2"),
                ("DETAIL", "Parameters: $1 = 'events', $2 = 'it''s'"),
                ("LOG", "statement: SELECT id FROM documents WHERE bucket = 'outbox'"),
                ("LOG", "execute <unnamed>: SELECT 1"))
    found = r4.parse_statement_log(text)
    assert found["buckets"] == ["events", "outbox", "tasks"] and found["writes"] == 0 and found["all_buckets_reads"] == 0


def test_the_lowercase_parameters_label_of_earlier_releases_is_read_too():
    text = _log(("LOG", "execute <unnamed>: SELECT 1 FROM documents WHERE bucket=$1"), ("DETAIL", "parameters: $1 = 'tasks'"))
    assert r4.parse_statement_log(text)["buckets"] == ["tasks"]


def test_a_whole_table_read_covers_no_bucket_a_write_and_ddl_are_counted_apart_and_other_tables_are_ignored():
    text = _log(("LOG", "execute <unnamed>: SELECT bucket,id,body FROM documents ORDER BY bucket,id"),
                ("LOG", "execute <unnamed>: INSERT INTO documents(bucket,id,body) VALUES ($1,$2,$3)"),
                ("DETAIL", "Parameters: $1 = 'tasks', $2 = 'x', $3 = '{}'"),
                ("LOG", "statement: CREATE TABLE IF NOT EXISTS documents (bucket text)"),
                ("LOG", "execute <unnamed>: SELECT 1 FROM information_schema.tables WHERE table_name = 'documents'"),
                ("ERROR", "relation \"x\" does not exist"),
                ("STATEMENT", "SELECT * FROM documents WHERE nothing"))
    assert r4.parse_statement_log(text) == {"buckets": [], "all_buckets_reads": 1, "writes": 1, "ddl": 1, "statements": 4}


@pytest.mark.parametrize("text", [
    "this is not a log line\n",  # a corrupted line
    _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE bucket=$1")),  # parameters missing
    _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE bucket=$1"), ("DETAIL", "Parameters: $1 = tasks")),
    _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE bucket=$1"), ("DETAIL", "Parameters: $2 = 'x'")),
    _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE bucket=$1"), ("DETAIL", "Parameters: $1 = NULL")),
    _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE id=$1"), ("DETAIL", "Parameters: $1 = 'x'")),
    _log(("LOG", "execute <unnamed>: SELECT body FROM documents WHERE bucket IN ($1,$2)"),
         ("DETAIL", "Parameters: $1 = 'a', $2 = 'b'")),
    _log(("LOG", "statement: COPY documents TO STDOUT")),
])
def test_an_unparseable_statement_on_the_records_table_fails_closed(text):
    with pytest.raises(r4.LogUnparseable) as caught:
        r4.parse_statement_log(text)
    assert caught.value.code == "coverage_log_unparseable"
    assert "tasks" not in caught.value.detail  # the failure names a class and a line, never log text


def _map_catalog():
    entry = {"reader": None, "reason": "fixture: no typed reader"}
    return {"version": 1, "trees": {"A": {"rev": None, "root": "x"}, "B": {"rev": None, "root": "x"}, "D": {"d1": {}}},
            "buckets": {"typed_z": {"owner": "f", "A": {"reader": "fx/r.py:read", "call": "body"}, "B": entry,
                                    "D": {"d1": entry}},
                        "read_x": {"owner": "f", "A": entry, "B": entry, "D": {"d1": entry}},
                        "unread_y": {"owner": "f", "A": entry, "B": entry, "D": {"d1": entry}}},
            "redis": {}}


def test_the_map_classifies_typed_leaf_covered_and_uncovered_and_an_uncovered_bucket_is_never_a_pass():
    result = r4.coverage_map(_map_catalog(), {"A": {"leaves": 1, "buckets": ["read_x", "typed_z"]}})
    column = result["columns"]["A"]
    assert (column["typed"], column["leaf_covered"], column["uncovered"]) == (1, 1, 1)
    assert column["leaf_covered_buckets"] == ["read_x"]  # a typed bucket is `typed`, not also leaf-covered
    assert column["uncovered_buckets"] == ["unread_y"] and column["observation"] == "observed"
    assert result["columns"]["B"]["observation"] == "not_run" and result["columns"]["B"]["uncovered"] == 3
    assert result["verdict"] == "uncovered" and "pass" not in json.dumps(result).lower()
    full = r4.coverage_map({**_map_catalog(), "buckets": {"typed_z": _map_catalog()["buckets"]["typed_z"]}},
                           {c: {"leaves": 1, "buckets": []} for c in ("A", "B", "d1")})
    assert full["columns"]["A"]["uncovered"] == 0 and full["columns"]["B"]["uncovered"] == 1  # B has no typed reader
    assert full["verdict"] == "uncovered"


def test_the_committed_baseline_is_the_catalog_typed_counts_with_every_untyped_bucket_uncovered_provenance_check(catalog):
    """STRUCTURAL (generated-file freshness): `r4-coverage.json` is exactly what `static_map` derives from the catalog."""
    committed = json.loads(r4.COVERAGE.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(r4.static_map(catalog)))
    facts = committed["facts"]
    assert facts["verdict"] == "not_observed" and facts["universe"] == len(catalog["buckets"]) == 187
    assert facts["columns"]["B"]["typed"] == 14 and facts["columns"]["B"]["uncovered"] == 173  # 13 + the PR-3 bucket
    assert all(c["observation"] == "not_run" and c["leaf_covered"] == 0 for c in facts["columns"].values())
    assert set(facts["columns"]) == {"A", "B", *catalog["trees"]["D"]}


# ---- the map over a real trace copy ----

RUN8T = "e3a9c5d7"
LEAF = r'''
import json, os, sys
import psycopg
mode, arg = sys.argv[1], sys.argv[2]
with psycopg.connect(os.environ["DSN"], connect_timeout=10) as conn:
    if mode == "read":
        conn.execute("SELECT id, body FROM lane_a.documents WHERE bucket = %s ORDER BY id", (arg,)).fetchall()
    elif mode == "byid":
        conn.execute("SELECT body FROM lane_a.documents WHERE id = %s", (arg,)).fetchall()
    elif mode == "write":
        conn.execute("INSERT INTO lane_a.documents VALUES (%s, 'w1', '{}') ON CONFLICT DO NOTHING", (arg,))
print(json.dumps({"mode": mode}))
'''


@pytest.fixture(scope="module")
def tworld(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    import psycopg

    w = World()
    w.root, w.out = tmp_path_factory.mktemp("r4t"), tmp_path_factory.mktemp("r4tout")
    w.copies = cp.Copies(RUN8T, w.root)
    try:
        w.handle = w.copies.start("S", trace=True)
        with psycopg.connect(cp.pg_dsn(w.handle.pg_socket, DATABASE), autocommit=True) as conn:
            conn.execute("CREATE SCHEMA lane_a")
            conn.execute("CREATE TABLE lane_a.documents (bucket text NOT NULL, id text NOT NULL, body jsonb NOT NULL, "
                         "PRIMARY KEY (bucket, id))")
            for bucket in ("typed_z", "read_x", "unread_y"):
                conn.execute("INSERT INTO lane_a.documents VALUES (%s, 'r1', '{\"n\": 1}')", (bucket,))
        w.script = w.root / "leaf.py"
        w.script.write_text(LEAF)
        w.dsn = cp.pg_dsn(w.handle.pg_socket, DATABASE)
        w.runs = 0
        yield w
    finally:
        sweep(RUN8T, w.root)


def _leaf(argv, revisions=("A",)):
    return {"class": "read_only", "revisions": list(revisions), "argv": argv, "params": [], "cites": {}}


def _trace_run(tworld, leaves, runner=r3.host_runner, catalog=None):
    tworld.runs += 1
    side = r3.Side("A", {"DSN": tworld.dsn}, {"zeus": [PYTHON, str(tworld.script)]})
    return r4.run_coverage_map({"A": side}, tworld.handle, DATABASE, catalog or _map_catalog(),
                               {"version": 1, "nodes": leaves}, _d0({"lane_a": {"typed_z": {}, "read_x": {}, "unread_y": {}}}),
                               tworld.out / f"m{tworld.runs}", runner=runner, timeout=120.0, wait=20.0)


@needs_docker
def test_a_leaf_that_reads_bucket_x_makes_x_leaf_covered_y_uncovered_and_z_typed_on_a_real_trace_copy(tworld):
    document = _trace_run(tworld, {"zeus fixture read-x": _leaf(["read", "read_x"])})
    column = document["facts"]["columns"]["A"]
    assert (column["typed"], column["leaf_covered"], column["uncovered"]) == (1, 1, 1)
    assert column["leaf_covered_buckets"] == ["read_x"] and column["uncovered_buckets"] == ["unread_y"]
    assert document["status"] == "ok" and document["facts"]["verdict"] == "uncovered"
    assert document["facts"]["observed_leaves"]["A"] == [{"node": "zeus fixture read-x", "exit": 0, "all_buckets_reads": 0}]
    written = (tworld.out / f"m{tworld.runs}" / "r4-coverage.json").read_text()
    assert "n\": 1" not in written and "'r1'" not in written  # no body or id value reaches the evidence


@needs_docker
def test_a_corrupted_log_line_inside_a_leaf_window_fails_the_run_closed_and_counts_no_bucket(tworld):
    def corrupting(side, command, timeout):
        done = r3.host_runner(side, command, timeout)
        log = sorted(tworld.handle.trace_dir.glob("*.log"))[-1]
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("garbage that is no log entry\n")
        return done

    with pytest.raises(r4.R4Failed) as caught:
        _trace_run(tworld, {"zeus fixture read-x": _leaf(["read", "read_x"])}, runner=corrupting)
    assert any("coverage_log_unparseable" in f for f in caught.value.failures)
    assert caught.value.document["facts"]["columns"]["A"]["leaf_covered"] == 0  # the unparsed window counted nothing


@needs_docker
def test_a_real_records_read_without_a_bucket_predicate_and_a_leaf_that_writes_are_run_failures(tworld):
    with pytest.raises(r4.R4Failed) as caught:
        _trace_run(tworld, {"zeus fixture by-id": _leaf(["byid", "r1"])})
    assert any("coverage_log_unparseable" in f for f in caught.value.failures)
    with pytest.raises(r4.R4Failed) as wrote:
        _trace_run(tworld, {"zeus fixture write": _leaf(["write", "read_x"])})
    assert wrote.value.failures == ["A:zeus fixture write:leaf_wrote_records:1"]


@needs_docker
def test_trace_mode_is_off_on_a_default_copy_and_on_for_the_trace_copy(world, tworld):
    import psycopg

    def setting(handle, name):
        with psycopg.connect(cp.pg_dsn(handle.pg_socket, DATABASE)) as conn:
            return conn.execute(f"SHOW {name}").fetchone()[0]  # noqa: S608 - fixed names

    assert (setting(world.handle, "log_statement"), setting(world.handle, "logging_collector")) == ("none", "off")
    assert world.handle.trace_dir is None
    assert (setting(tworld.handle, "log_statement"), setting(tworld.handle, "logging_collector")) == ("all", "on")
    assert tworld.handle.trace_dir == tworld.root / "S" / "pgdata" / cp.TRACE_LOG_DIR and tworld.handle.trace_dir.is_dir()
    assert r4.read_trace_log(tworld.handle.trace_dir)  # the host reads the log from ROOT
    with pytest.raises(r4.Refused) as off:
        r4.observe_column("A", None, world.handle, DATABASE, {"nodes": {}}, params={}, runner=None, timeout=1)
    assert off.value.code == "trace_off"
