"""Cutover RH-6a: the rehearsal R6 rollback-read runner (`compare/rehearsal/r6.py`).

Layer: harness tooling tests (never shipped). Expected results come from the task spec and the rehearsal design "8. R6"
(PASS = failures(D_rev | B) is a subset of failures(D_rev | D at D0), and D1 == D0 on D; a rev whose column is missing from
the catalogs is a FAILURE, never a skip), AMD-1 B (the FA permit bucket is declared beyond OWNED_BUCKETS) and E6 (D_rev =
the releases of the R0 record); the fixtures' own constants are the oracle: each fixture revision's reader and leaf are tiny
programs whose behaviour is set by the rows the test inserts. The runner tests drive the public `run_r6` over two real
disposable copies (B and D) with fixture revisions run through their own interpreter; the pure `d_revs` tests need no
Docker; the copy tests need `ZEUS_TEST_DOCKER=1` and `ZEUS_TEST_DOCKER_PGEXEC=1`, and a skip under those opt-ins is a failure.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import copies as cp  # noqa: E402
from rehearsal import r3, r6  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
DOCKER = os.environ.get(guard.DOCKER_OPT_IN_ENV) == "1" and os.environ.get(guard.DOCKER_PGEXEC_ENV) == "1"
needs_docker = pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
RUN8, DATABASE = "6a3d9b52", "zeus"
REV_A, REV_M = "5aa220fd" + "0" * 32, "ced20281" + "1" * 32
COLUMN = "5aa220fd"

# ---- D_rev from the R0 record (pure) ----


def _r0(tmp_path, **payload):
    release = f"{tmp_path}/releases/{REV_A}"
    runtime = {"revision": REV_M, "tree": "t", "built_at": "b"}
    exe = {"realpath": "/base/py3", "release": release, "subcommand": "entry"}
    managed = {"shape": "runtime_dir", "runtime": runtime, "payload_executable": exe, **payload}
    return {"stable": {"releases": {release: {"interpreter_realpath": "/base/py3"}},
                       "managed_payload": {"releases": {f"{tmp_path}/payload/rt": managed}}}}, release


def test_d_revs_are_every_release_plus_the_payload_each_through_its_own_interpreter_and_src(tmp_path):
    record, release = _r0(tmp_path)
    revs, failures = r6.d_revs(record)
    assert failures == []
    assert revs == [
        r6.Rev("5aa220fd", release, f"{release}/.venv/bin/python", f"{release}/src", "release", "/base/py3"),
        r6.Rev("ced20281", f"{tmp_path}/payload/rt", f"{release}/.venv/bin/python", f"{tmp_path}/payload/rt/src",
               "runtime_dir", "/base/py3")]
    assert r6.rev_commands(revs[1])["python"] == [f"{release}/.venv/bin/python"]


def test_a_payload_with_no_resolved_executable_a_unknown_shape_or_a_repeated_column_is_a_failure_never_a_skip(tmp_path):
    record, release = _r0(tmp_path)
    where = f"{tmp_path}/payload/rt"
    record["stable"]["managed_payload"]["releases"][where].pop("payload_executable")
    assert r6.d_revs(record)[1] == [f"r6_rev_unresolved:{where}:payload_executable"]
    record["stable"]["managed_payload"]["releases"][where] = {"shape": "unknown", "dir": where}
    assert r6.d_revs(record)[1] == [f"r6_rev_unresolved:{where}:revision"]  # no column either: still named, never skipped
    record["stable"]["managed_payload"]["releases"][where] = {"shape": "unknown", "runtime": {"revision": REV_M}}
    assert r6.d_revs(record)[1] == [f"r6_rev_unresolved:{where}:shape:unknown"]
    twin = f"{tmp_path}/releases/{COLUMN}" + "f" * 32
    record["stable"]["releases"][twin] = {"interpreter_realpath": "/base/py3"}
    assert [c.column for c in r6.d_revs(record)[0]] == [COLUMN] and r6.d_revs(record)[1][0].startswith(
        "r6_rev_duplicate:5aa220fd")
    with pytest.raises(r6.Refused) as caught:
        r6.d_revs({"stable": {}})
    assert caught.value.code == "r0_malformed"


def test_a_payload_that_is_also_a_release_is_one_revision(tmp_path):
    record, release = _r0(tmp_path)
    record["stable"]["managed_payload"]["releases"] = {release: record["stable"]["releases"][release]}
    revs, failures = r6.d_revs(record)
    assert [r.column for r in revs] == [COLUMN] and failures == []


# ---- the runner over two real copies, with fixture revisions ----

READERS = '''
    class Refusal(Exception):
        def __init__(self, code):
            super().__init__("body-value-in-message")
            self.reason_code = code


    def read_job(body):
        if not isinstance(body.get("n"), int):
            raise Refusal("bad_n")
        if body.get("legacy") is True:
            raise Refusal("legacy_shape")
        return body


    def check_message(doc):
        if "who" not in doc:
            raise Refusal("no_who")
        return doc
'''
# The fixture leaf: argv[1] is the node's argv word. `status` exits 0; `legacy` exits 3 when the store holds the legacy row
# (a leaf that fails only where that row exists); `write` is a leaf that writes the store on the copies named in FX_WRITERS.
LEAF = '''
import os, sys, psycopg
mode = sys.argv[1]
with psycopg.connect(os.environ["RH_DSN"], autocommit=True) as conn:
    if mode == "legacy":
        sys.exit(3 if conn.execute("SELECT 1 FROM lane_a.documents WHERE id = 'j-legacy'").fetchone() else 0)
    if mode == "write" and os.environ["FX_COPY"] in os.environ["FX_WRITERS"]:
        conn.execute("INSERT INTO lane_a.documents VALUES ('notes', 'leaf-wrote', '{}') ON CONFLICT DO NOTHING")
print("status held")
'''


class World:
    pass


def _tree(root, column=COLUMN, revision=REV_A):
    release = root / "releases" / revision
    package = release / "src" / "codex_harness"
    (package / "fx").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "fx" / "__init__.py").write_text("")
    (package / "fx" / "readers.py").write_text(textwrap.dedent(READERS))
    binary = release / ".venv" / "bin"
    binary.mkdir(parents=True)
    (binary / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (binary / "python").chmod(0o755)
    return release


def _entry(spec):
    return {"reader": None, "reason": "fixture: no typed reader"} if spec is None else {"reader": spec[0], "call": spec[1]}


def _readers(column=COLUMN):
    job, stream = ("fx/readers.py:read_job", "body"), ("fx/readers.py:check_message", "body")
    return {"version": 1,
            "trees": {"A": {"rev": None, "root": "unused"}, "B": {"rev": None, "root": "unused"}, "D": {column: {}}},
            "buckets": {"jobs": {"owner": "fixture", "A": _entry(job), "B": _entry(job), "D": {column: _entry(job)}},
                        "notes": {"owner": "fixture", "A": _entry(None), "B": _entry(None), "D": {column: _entry(None)}},
                        r6.FA_BUCKET: {"owner": "fixture", "amd1": "B", "A": _entry(None), "B": _entry(None),
                                       "D": {column: _entry(None)}}},
            "redis": {"agent_stream": {"owner": "fixture", "prefix_re": r"rh:agent", "key_re": r"rh:agent:.+",
                                       "A": _entry(stream), "B": _entry(stream), "D": {column: _entry(stream)}}},
            "declared": []}


def _leaves(column=COLUMN, *, extra=()):
    nodes = {"zeus fixture status": {"class": "read_only", "revisions": [column], "argv": ["status"], "params": []}}
    for name in extra:
        nodes[f"zeus fixture {name}"] = {"class": "read_only", "revisions": [column], "argv": [name], "params": []}
    return {"version": 1, "revisions": {column: {"label": "fixture"}}, "nodes": nodes}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not DOCKER:
        pytest.skip("needs ZEUS_TEST_DOCKER=1 and ZEUS_TEST_DOCKER_PGEXEC=1")
    import psycopg
    import redis

    w = World()
    w.root, w.out = tmp_path_factory.mktemp("r6"), tmp_path_factory.mktemp("r6out")
    w.copies = cp.Copies(RUN8, w.root)
    try:
        w.handles = {name: w.copies.start(name) for name in ("D", "B")}
        for handle in w.handles.values():
            with psycopg.connect(cp.pg_dsn(handle.pg_socket, DATABASE), autocommit=True) as conn:
                conn.execute("CREATE SCHEMA lane_a")
                conn.execute("CREATE TABLE lane_a.documents (bucket text NOT NULL, id text NOT NULL, body jsonb NOT NULL, "
                             "PRIMARY KEY (bucket, id))")
                for ident, body in (("j1", {"n": 1}), ("j2", {"n": 2})):
                    conn.execute("INSERT INTO lane_a.documents VALUES ('jobs', %s, %s)", (ident, json.dumps(body)))
            client = redis.Redis(unix_socket_path=str(handle.redis_socket / "redis.sock"))
            client.xadd("rh:agent:one", {"body": json.dumps({"who": "x"})})
        # AMD-1 B: only the candidate side (B) holds the FA permit rows; the rollback revision must ignore them
        w.permits = r6.seed_fa_permits(w.handles["B"], DATABASE, "lane_a")
        w.release = _tree(w.root)
        w.rev = r6.Rev(COLUMN, str(w.release), str(w.release / ".venv" / "bin" / "python"), str(w.release / "src"),
                       "release", sys.executable)
        snap = r3.snapshot(w.handles["D"], DATABASE)
        w.d0 = {"facts": {k: snap[k] for k in r6.CHANGED}}
        w.runs = 0
        yield w
    finally:
        sweep(RUN8, w.root)


def _side_for(world, writers=""):
    def side_for(rev, copy_name):
        spec = {"PYTHONPATH": rev.src, "RH_DSN": cp.pg_dsn(world.handles[copy_name].pg_socket, DATABASE),
                "FX_COPY": copy_name, "FX_WRITERS": writers}
        return r3.Side(rev.column, spec, {"zeus": [rev.python, "-c", LEAF], "monitor": [rev.python, "-c", LEAF],
                                          "python": [rev.python]})
    return side_for


def _run(world, *, revs=None, leaves=None, readers=None, writers="", d0=None, **kwargs):
    world.runs += 1
    return r6.run_r6(revs if revs is not None else [world.rev], world.handles, DATABASE,
                     leaves or _leaves(), readers or _readers(), d0 or world.d0, world.out / f"r{world.runs}",
                     side_for=_side_for(world, writers), runner=r3.host_runner, timeout=120.0, **kwargs)


def _d0_now(world):
    """The D0 record of D as it is NOW (a test that adds a row to D first declares that state as its D0)."""
    snap = r3.snapshot(world.handles["D"], DATABASE)
    return {"facts": {k: snap[k] for k in r6.CHANGED}}


def _insert(world, copy, ident, body, bucket="jobs"):
    import psycopg

    with psycopg.connect(cp.pg_dsn(world.handles[copy].pg_socket, DATABASE), autocommit=True) as conn:
        conn.execute("INSERT INTO lane_a.documents VALUES (%s, %s, %s)", (bucket, ident, json.dumps(body)))


def _delete(world, copy, ident):
    import psycopg

    with psycopg.connect(cp.pg_dsn(world.handles[copy].pg_socket, DATABASE), autocommit=True) as conn:
        conn.execute("DELETE FROM lane_a.documents WHERE id = %s", (ident,))


@needs_docker
def test_a_clean_run_passes_ignores_the_fa_permit_bucket_and_writes_a_private_record_once(world):
    document = _run(world)
    facts = document["facts"]
    assert document["status"] == "ok" and facts["failures"] == [] and facts["d1_equals_d0"] is True
    row = facts["results"][COLUMN]
    assert row["verdict"] == "pass" and row["leaves"] == 1 and row["d_equals_d0"] and row["b_unchanged"]
    # AMD-1 B: B holds one issued + one consumed permit row, the revision predates the bucket: ignored once, not a failure
    assert row["ignored_unknown_buckets"] == {f"B|{r6.FA_BUCKET}": 1}
    assert world.permits == ["rh-fixture-permit-issued", "rh-fixture-permit-consumed"]
    path = world.out / f"r{world.runs}" / "r6.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == json.dumps(json.loads(path.read_text()), sort_keys=True, ensure_ascii=True) + "\n"
    with pytest.raises(r6.Refused) as again:  # O_EXCL: a record is never overwritten
        r6.write_record(path, document)
    assert again.value.code == "evidence_exists"


@needs_docker
def test_the_same_failure_on_both_copies_passes_and_a_failure_only_on_d_passes_too_the_subset_rule(world):
    _insert(world, "B", "j-bad", {"n": "x"})
    _insert(world, "D", "j-bad", {"n": "x"})  # the same unreadable row on both: the pre-existing failure
    _insert(world, "D", "j-d-only", {"n": "y"})  # a failure only D has: failures(B) is still a subset
    try:
        document = _run(world, d0=_d0_now(world))
    finally:
        _delete(world, "B", "j-bad")
        _delete(world, "D", "j-bad")
        _delete(world, "D", "j-d-only")
    row = document["facts"]["results"][COLUMN]
    assert document["status"] == "ok" and row["verdict"] == "pass"
    assert (row["failures_d0"], row["failures_b"], row["common"], row["b_only"]) == (2, 1, 1, [])


@needs_docker
def test_a_reader_failure_only_on_b_fails_naming_the_rev_bucket_and_code(world):
    _insert(world, "B", "j-legacy", {"n": 5, "legacy": True})
    try:
        with pytest.raises(r6.R6Failed) as caught:
            _run(world)
    finally:
        _delete(world, "B", "j-legacy")
    assert caught.value.failures == [f"{COLUMN}:B_only:(lane_a, jobs, j-legacy, Refusal, legacy_shape)"]
    written = json.loads((world.out / f"r{world.runs}" / "r6.json").read_text())  # the evidence exists
    assert written["status"] == "failed" and written["facts"]["results"][COLUMN]["verdict"] == "fail"
    assert "body-value-in-message" not in json.dumps(written)  # class and code only, never a message


@needs_docker
def test_a_leaf_failing_only_on_b_fails_and_failing_on_both_passes(world):
    leaves = _leaves(extra=("legacy",))
    _insert(world, "B", "j-legacy", {"n": 5})  # the leaf exits 3 where this id exists; the reader accepts the row
    try:
        with pytest.raises(r6.R6Failed) as caught:
            _run(world, leaves=leaves)
        assert caught.value.failures == [f"{COLUMN}:B_only:(leaf, zeus fixture legacy, *, LeafExit, exit_3)"]
        _insert(world, "D", "j-legacy", {"n": 5})
        try:
            document = _run(world, leaves=leaves, d0=_d0_now(world))
        finally:
            _delete(world, "D", "j-legacy")
    finally:
        _delete(world, "B", "j-legacy")
    assert document["status"] == "ok" and document["facts"]["results"][COLUMN]["common"] == 1


@needs_docker
def test_a_rev_whose_column_is_missing_from_a_catalog_fails_and_is_never_skipped(world):
    ghost = r6.Rev("deadbeef", str(world.release), world.rev.python, world.rev.src, "release")
    with pytest.raises(r6.R6Failed) as caught:
        _run(world, revs=[world.rev, ghost])
    assert caught.value.failures == ["r6_column_missing:deadbeef:r3+r4"]
    facts = caught.value.document["facts"]
    assert facts["revisions_run"] == [COLUMN, "deadbeef"] and facts["results"]["deadbeef"]["verdict"] == "fail"
    assert facts["results"][COLUMN]["verdict"] == "pass"  # the other revision still ran
    with pytest.raises(r6.R6Failed) as one:  # present in the leaf catalog but not in the reader catalog
        _run(world, revs=[ghost], leaves=_leaves("deadbeef"))
    assert one.value.failures == ["r6_column_missing:deadbeef:r4"]


@needs_docker
def test_a_leaf_that_writes_the_store_fails_as_not_read_only_and_d1_differs_from_d0(world):
    leaves = _leaves(extra=("write",))
    try:
        with pytest.raises(r6.R6Failed) as caught:
            _run(world, leaves=leaves, writers="D")  # only the D side's leaf writes
    finally:
        _delete(world, "D", "leaf-wrote")
    assert caught.value.failures == [f"{COLUMN}:not_read_only:{COLUMN}:D:zeus fixture write:catalog_sha256"]
    facts = caught.value.document["facts"]
    assert facts["d1_equals_d0"] is False and facts["results"][COLUMN]["d_equals_d0"] is False
    assert facts["catalog_sha256_d1"] != facts["catalog_sha256_d0"]


@needs_docker
def test_a_d_copy_that_is_not_at_d0_is_refused_before_it_is_read_as_d0(world):
    wrong = {"facts": {**world.d0["facts"], "catalog_sha256": "0" * 64}}
    with pytest.raises(r6.R6Failed) as caught:
        _run(world, d0=wrong)
    assert "d_not_at_d0:catalog_sha256" in caught.value.failures


@needs_docker
def test_a_revision_whose_src_is_not_where_codex_harness_resolves_is_refused_not_passed(world, tmp_path):
    stray = r6.Rev(COLUMN, str(world.release), world.rev.python, str(tmp_path / "elsewhere" / "src"), "release")
    (tmp_path / "elsewhere" / "src").mkdir(parents=True)
    with pytest.raises(r6.R6Failed) as caught:
        _run(world, revs=[stray])
    assert f"{COLUMN}:origin_refused:{COLUMN}:D" in caught.value.failures


@needs_docker
def test_the_m7_rollback_read_over_b_is_extra_parity_and_never_changes_the_verdict(world):
    _insert(world, "B", "j-legacy", {"n": 5, "legacy": True})
    try:
        document = _run(world, parity=(world.rev, _side_for(world)(world.rev, "B")), revs=[])
    finally:
        _delete(world, "B", "j-legacy")
    assert document["status"] == "ok"  # the parity read of B saw a failure but is not counted
    # B holds three jobs rows (one of them legacy) and one stream entry; the legacy row is the one failure
    assert document["facts"]["parity"] == {"column": COLUMN, "failures": 1, "rows_read": 4, "errors": 0,
                                           "counted_in_verdict": False}


@needs_docker
def test_the_runner_leaves_both_copies_unchanged(world):
    before = {name: r3.snapshot(world.handles[name], DATABASE) for name in ("B", "D")}
    _run(world)
    assert {name: r3.snapshot(world.handles[name], DATABASE) for name in ("B", "D")} == before
