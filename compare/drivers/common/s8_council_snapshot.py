"""Shared S8 scenario steps (`research.council_snapshot`): M7 `adapters/council_snapshot.py` (`SnapshotUnavailable`, `ReadOnlySnapshot`:
the constructor's timeout validation, `observe`, `_session`, the BEGIN/IDENTITY/SELECT statements, the reductions through
`domain.council`, and the failure mapping to `snapshot_unavailable` with no `__cause__`/`__context__`), characterized BEFORE the module
moves (DESIGN-s8 §6 V11; the branch table `branch-table-research.txt` section `adapters/council_snapshot.py`: every raise and every
except of the module is covered, see `branch_coverage`).

- **s1_constructor**: the defaults, the injected values, every timeout the constructor accepts or refuses (and that a refusal makes
  no connection), the keyword-only arguments, the exception class.
- **s2_observe**: the statements in order with their parameters, the connect call, the one clock read inside the transaction, the
  reductions (found, missing, unknown), the endpoint identity digest, the selection validation that runs before any connection, the
  refusals of the domain envelope that propagate unchanged.
- **s3_failures**: every connection or read failure and its single outcome (`snapshot_unavailable`, code, message, `__cause__` and
  `__context__` None, no secret on the traceback), the statements issued up to the failure (the ROLLBACK that always follows a BEGIN
  that was followed by a failing statement), a `BaseException` that is not mapped, the malformed identities, the failures that are NOT
  mapped (a malformed row, an envelope refusal).
- **s4_m7_tests**: the M7 `tests/test_council.py` and `tests/test_council_postgres.py` parts that touch this module, mapped to the cases.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target)
driver builds. The connection is a LABELLED fake (M7 `FakeConnection` of `tests/test_council.py`, extended with a scripted fault per
statement and an event log); the `connect` and the clock are LABELLED doubles. The PostgreSQL integration test
(`tests/test_council_postgres.py`) is `unreachable: integration lane (owner)`. Nothing here touches a database, a network or a provider."""

from __future__ import annotations

import copy
import traceback

SECRET = "SECRET-row-text-never-emitted"
DSN = "postgresql://user:" + SECRET + "@host/db"
BASE = "a" * 40
NOW = "2029-01-01T00:00:00+00:00"
SELECTION = [{"bucket": "tasks", "id": "task-known"}, {"bucket": "operations", "id": "op-missing"},
             {"bucket": "autonomous_runs", "id": "run-odd"}]
# M7 `DB_ROWS` (tests/test_council.py): a task that is found (its `error` text is never exported) and a run whose stage is outside
# the finite vocabulary (unknown); the operation has no row (missing).
ROWS = {("tasks", "task-known"): {"id": "task-known", "status": "succeeded", "agent": "worker:implementation", "error": SECRET},
        ("autonomous_runs", "run-odd"): {"id": "run-odd", "status": "running", "stage": "not a token!"}}
IDENTITY_ROW = ("zeus", "test_schema", "18.0")
BINDING = dict(topic="t", run_id="council-001", base_revision=BASE, max_age_seconds=600)
UNSET = object()
BEGIN_STATEMENT = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"


class Stop(BaseException):
    """LABELLED. A fault that is not an `Exception` (a cancellation): `except Exception` does not map it."""


class Cursor:
    """LABELLED. M7 `_Cursor`; `fail_one`/`fail_all` script a fault on the fetch."""

    def __init__(self, rows, fail_one=None, fail_all=None):
        self.rows, self.fail_one, self.fail_all = rows, fail_one, fail_all

    def fetchone(self):
        if self.fail_one is not None:
            raise self.fail_one
        return self.rows[0] if self.rows else None

    def fetchall(self):
        if self.fail_all is not None:
            raise self.fail_all
        return list(self.rows)


class Conn:
    """LABELLED. M7 `FakeConnection` (tests/test_council.py): records every statement and serves the fixed rows. Extensions: the
    shared event `log` (enter, execute with its parameters, exit), `fail` (a substring of a statement -> the exception that
    `execute` raises for it, after logging it), `identity` (what the identity statement's `fetchone` returns), `select_rows` (what the
    SELECT's `fetchall` returns instead of the rows for the asked keys), `fetch_fail` ((statement prefix, 'one'|'all') -> exception)
    and `exit_error` (raised by `__exit__`)."""

    def __init__(self, log, rows=ROWS, fail=None, identity=UNSET, select_rows=UNSET, fetch_fail=None, exit_error=None):
        self.log, self.rows, self.fail = log, rows, fail or {}
        self.identity = [IDENTITY_ROW] if identity is UNSET else identity
        self.select_rows, self.fetch_fail, self.exit_error = select_rows, fetch_fail or {}, exit_error

    def __enter__(self):
        self.log.append(["enter"])
        return self

    def __exit__(self, exc_type, exc, tb):
        self.log.append(["exit", None if exc_type is None else exc_type.__name__])
        if self.exit_error is not None:
            raise self.exit_error
        return False

    def execute(self, statement, params=None):
        self.log.append(["execute", statement, None if params is None else [list(p) for p in params]])
        for part, error in self.fail.items():
            if part in statement:
                raise error
        if statement.startswith("SELECT current_database"):
            return Cursor(self.identity, fail_one=self.fetch_fail.get("identity"))
        if statement.startswith("SELECT s.bucket"):
            buckets, ids = params
            rows = ([(b, i, self.rows[(b, i)]) for b, i in zip(buckets, ids) if (b, i) in self.rows]
                    if self.select_rows is UNSET else self.select_rows)
            return Cursor(rows, fail_all=self.fetch_fail.get("select"))
        return Cursor([])


def clock_into(log, value=NOW):
    def read():
        log.append(["clock"])
        if isinstance(value, BaseException):
            raise value
        return value
    return read


def outcome(exc) -> dict:
    """What a caught exception shows: its type, text, public fields and the chain facts."""
    result = {"raised": type(exc).__name__, "message": str(exc)[:400], "mro": [c.__name__ for c in type(exc).__mro__[:4]]}
    for name in ("reason_code", "field"):
        if hasattr(exc, name):
            result[name] = getattr(exc, name)
    result.update(cause_is_none=exc.__cause__ is None, context_is_none=exc.__context__ is None, suppress_context=exc.__suppress_context__,
                  traceback_leaks_secret=SECRET in "".join(traceback.format_exception(exc)), message_leaks_secret=SECRET in str(exc))
    return result


def drive(api, selection=None, rows=ROWS, constructor=None, connect=UNSET, clock=UNSET, binding=None, **conn):
    """One `observe` over a fake connection: the events (connect, enter, execute, clock, exit) and the value or the refusal."""
    log = []
    selection = copy.deepcopy(SELECTION if selection is None else selection)
    before = copy.deepcopy(selection)

    def connected(dsn, **kwargs):
        log.append(["connect", dsn == DSN, kwargs])
        return Conn(log, rows=rows, **conn)

    port_kwargs = dict(constructor or {})
    port_kwargs["connect"] = connected if connect is UNSET else (lambda dsn, **kw: (log.append(["connect", dsn == DSN, kw]), connect(dsn, **kw))[1])
    if clock is UNSET:
        port_kwargs["clock"] = clock_into(log)
    elif clock is not None:
        port_kwargs["clock"] = clock_into(log, clock)
    port = api.ReadOnlySnapshot(DSN, **port_kwargs)
    try:
        value = port.observe(selection, **(BINDING if binding is None else binding))
        result = {"value": value}
    except (Exception, Stop) as exc:
        result = outcome(exc)
    statements = [e[1] for e in log if e[0] == "execute"]
    result.update(events=log, statements=statements, selection_unchanged=selection == before,
                  only_read_statements=all(s.startswith(("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY", "SET LOCAL statement_timeout",
                                                         "SELECT ", "ROLLBACK")) for s in statements),
                  never_committed=not any("COMMIT" in s.upper() for s in statements))
    return result


def attempt(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except (Exception, Stop) as exc:
        return outcome(exc)


# ---- S1 -----------------------------------------------------------------------------------------------------------------------
def s1_constructor(api):
    out = {}
    port = api.ReadOnlySnapshot(DSN)
    out["defaults"] = {"dsn_is_stored": port.dsn == DSN, "connect_is_psycopg_connect": port.connect is api.default_connect,
                       "clock_name": getattr(port.clock, "__name__", None), "connect_timeout": port.connect_timeout,
                       "statement_timeout_ms": port.statement_timeout_ms, "attributes": sorted(vars(port))}
    marker = object()
    clock = lambda: NOW  # noqa: E731
    port = api.ReadOnlySnapshot("dsn", connect=marker, clock=clock, connect_timeout=2, statement_timeout_ms=250)
    out["injected"] = {"connect_is_the_argument": port.connect is marker, "clock_is_the_argument": port.clock is clock,
                       "connect_timeout": port.connect_timeout, "statement_timeout_ms": port.statement_timeout_ms}
    out["a_falsy_connect_falls_back_to_psycopg"] = {name: api.ReadOnlySnapshot("dsn", connect=value).connect is api.default_connect
                                                    for name, value in (("none", None), ("zero", 0), ("empty_tuple", ()))}
    calls = []
    port = api.ReadOnlySnapshot("dsn", connect=lambda *a, **k: calls.append(a) or None)
    out["construction_connects_nothing"] = {"calls": len(calls)}
    refused = {}
    for name, ct, st in (("zero_connect", 0, 5000), ("negative_connect", -1, 5000), ("bool_connect", True, 5000), ("false_connect", False, 5000),
                         ("float_connect", 5.0, 5000), ("text_connect", "5", 5000), ("none_connect", None, 5000),
                         ("zero_statement", 5, 0), ("negative_statement", 5, -1), ("bool_statement", 5, True), ("float_statement", 5, 5000.0),
                         ("text_statement", 5, "5000"), ("none_statement", 5, None), ("both_bad", 0, 0), ("float_both", 1.0, 1.0)):
        sink = []
        refused[name] = {**attempt(api.ReadOnlySnapshot, "dsn", connect=lambda *a, **k: sink.append(a), connect_timeout=ct, statement_timeout_ms=st),
                         "connect_calls": len(sink)}
    out["timeouts_refused"] = refused
    accepted = {}
    for name, ct, st in (("one_and_one", 1, 1), ("large", 10 ** 9, 10 ** 9), ("default_connect_custom_statement", 5, 7)):
        built = api.ReadOnlySnapshot("dsn", connect_timeout=ct, statement_timeout_ms=st)
        accepted[name] = {"connect_timeout": built.connect_timeout, "statement_timeout_ms": built.statement_timeout_ms}
    out["timeouts_accepted"] = accepted
    out["connect_is_keyword_only"] = attempt(api.ReadOnlySnapshot, "dsn", lambda *a, **k: None)
    out["dsn_is_required"] = attempt(api.ReadOnlySnapshot)
    out["unknown_keyword"] = attempt(api.ReadOnlySnapshot, "dsn", timeout=3)
    out["observe_arguments_are_keyword_only"] = attempt(api.ReadOnlySnapshot("dsn").observe, SELECTION, "t", "r", BASE, 600)
    unavailable = api.SnapshotUnavailable("some_code")
    out["exception_class"] = {"message": str(unavailable), "reason_code": unavailable.reason_code, "args": list(unavailable.args),
                              "is_contract_error": isinstance(unavailable, api.ContractError), "is_exception": isinstance(unavailable, Exception),
                              "mro": [c.__name__ for c in type(unavailable).__mro__[:3]], "cause_is_none": unavailable.__cause__ is None,
                              "reason_is_required": attempt(api.SnapshotUnavailable)}
    out["module_names"] = {"BEGIN": api.module.BEGIN, "IDENTITY": api.module.IDENTITY, "SELECT": api.module.SELECT,
                           "__all__": sorted(api.module.__all__), "BEGIN_is_read_only_repeatable_read": api.module.BEGIN == BEGIN_STATEMENT}
    return out


# ---- S2 -----------------------------------------------------------------------------------------------------------------------
def s2_observe(api):
    out = {}
    out["ok"] = drive(api)
    out["the_connect_call"] = [e for e in out["ok"]["events"] if e[0] == "connect"]
    out["custom_timeouts_reach_the_connect_call_and_the_set_local"] = drive(api, constructor={"connect_timeout": 2, "statement_timeout_ms": 250})
    keys = drive(api)
    out["select_parameters_are_the_two_columns_in_selection_order"] = [e for e in keys["events"] if e[0] == "execute" and e[1].startswith("SELECT s.bucket")]
    out["one_clock_read_inside_the_transaction"] = {"order": [e[0] if e[0] != "execute" else e[1].split(" ")[0] for e in keys["events"]],
                                                    "clock_reads": sum(e == ["clock"] for e in keys["events"])}
    out["records_all_found"] = drive(api, selection=[{"bucket": "tasks", "id": "task-known"}], rows=ROWS)
    out["records_all_missing"] = drive(api, selection=SELECTION, rows={})
    out["records_unknown_body"] = drive(api, selection=[{"bucket": "tasks", "id": "task-known"}],
                                        rows={("tasks", "task-known"): ["not", "a", "mapping"]})
    out["records_unknown_field"] = drive(api, selection=[{"bucket": "tasks", "id": "task-known"}],
                                         rows={("tasks", "task-known"): {"id": "task-known", "status": "succeeded"}})
    out["row_not_selected_is_ignored"] = drive(api, selection=[{"bucket": "tasks", "id": "task-known"}],
                                               select_rows=[("tasks", "other", {"status": "failed"}), ("tasks", "task-known", ROWS[("tasks", "task-known")])])
    out["the_last_row_of_a_key_wins"] = drive(api, selection=[{"bucket": "tasks", "id": "task-known"}],
                                              select_rows=[("tasks", "task-known", {"id": "x", "status": "failed", "agent": "conductor"}),
                                                           ("tasks", "task-known", ROWS[("tasks", "task-known")])])
    out["rows_as_lists"] = drive(api, selection=[{"bucket": "tasks", "id": "task-known"}],
                                 select_rows=[["tasks", "task-known", ROWS[("tasks", "task-known")]]])
    out["identity_as_a_list"] = drive(api, identity=[list(IDENTITY_ROW)])
    identities = {}
    for name, row in (("other_database", ("other", "test_schema", "18.0")), ("other_schema", ("zeus", "public", "18.0")),
                      ("other_version", ("zeus", "test_schema", "17.11")), ("same", IDENTITY_ROW)):
        identities[name] = drive(api, identity=[row])["value"]["database_identity"]
    out["endpoint_digest_is_the_digest_of_database_schema_and_version"] = {
        **{k: v == api.digest({"database": r[0], "schema": r[1], "server_version": r[2]})
           for k, v, r in (("other_database", identities["other_database"], ("other", "test_schema", "18.0")),
                           ("other_schema", identities["other_schema"], ("zeus", "public", "18.0")),
                           ("other_version", identities["other_version"], ("zeus", "test_schema", "17.11")),
                           ("same", identities["same"], IDENTITY_ROW))},
        "all_distinct": len(set(identities.values())) == 4}
    out["the_dsn_never_reaches_the_value"] = {"in_value": SECRET in repr(drive(api).get("value"))}
    out["clock_value_sets_observed_at_and_expiry"] = {name: drive(api, clock=value)["value"]["observed_at"] for name, value in
                                                      (("utc", "2029-06-01T10:00:00+00:00"), ("offset", "2029-06-01T10:00:00+02:00"))}
    out["max_age_sets_the_expiry"] = {str(age): drive(api, binding={**BINDING, "max_age_seconds": age})["value"]["expires_at"] for age in (60, 3600)}
    out["binding_is_echoed"] = {k: drive(api, binding={**BINDING, k: v})["value"][k] for k, v in
                                (("topic", "other-topic"), ("run_id", "council-002"), ("base_revision", "b" * 40))}
    out["max_age_outside_60_to_3600_is_refused_before_connect"] = {
        str(age): drive(api, binding={**BINDING, "max_age_seconds": age}) for age in (59, 3601, True, 600.0)}
    out["the_default_clock_is_read_when_none_is_injected"] = default_clock(api)
    refused = {}
    for name, selection in (("empty", []), ("twenty_one", [{"bucket": "tasks", "id": "t%d" % i} for i in range(21)]),
                            ("duplicate", [SELECTION[0], SELECTION[0]]), ("unknown_bucket", [{"bucket": "outbox", "id": "x"}]),
                            ("extra_key", [{"bucket": "tasks", "id": "x", "extra": 1}]), ("not_a_mapping", ["tasks"]),
                            ("unsafe_id", [{"bucket": "tasks", "id": "not a token!"}])):
        refused[name] = drive(api, selection=selection)
    out["selection_refused_before_any_connection"] = refused
    out["twenty_records_are_accepted"] = drive(api, selection=[{"bucket": "tasks", "id": "t%d" % i} for i in range(20)], rows={})["value"]["selection"][-1]
    envelope = {}
    for name, value in (("not_a_date", "not a date"), ("naive", "2029-01-01T00:00:00"), ("none", None), ("number", 5), ("empty", "")):
        envelope[name] = drive(api, clock=value) if value is not None else drive(api, clock=None, constructor={"clock": lambda: None})
    out["envelope_refusals_propagate_unchanged_after_the_rollback"] = envelope
    return out


def default_clock(api):
    """The module's default `clock=utcnow`: with none injected `observe` reads the harness's clock (one instant per call)."""
    log = []

    def connected(dsn, **kwargs):
        return Conn(log)

    first = api.ReadOnlySnapshot(DSN, connect=connected).observe(SELECTION, **BINDING)
    return {"observed_at": first["observed_at"], "expires_at": first["expires_at"]}


# ---- S3 -----------------------------------------------------------------------------------------------------------------------
def s3_failures(api):
    out = {}
    boom = OSError("connection reset " + SECRET)
    out["connect_raises"] = drive(api, connect=lambda dsn, **kw: (_ for _ in ()).throw(OSError("could not connect to " + dsn)))
    out["connect_raises_a_runtime_error"] = drive(api, connect=lambda dsn, **kw: (_ for _ in ()).throw(RuntimeError(SECRET)))
    out["connect_returns_none"] = drive(api, connect=lambda dsn, **kw: None)
    out["connect_returns_a_non_connection"] = drive(api, connect=lambda dsn, **kw: object())
    out["connect_rejects_the_keywords"] = drive(api, connect=lambda dsn: Conn([]))
    out["connect_raises_a_base_exception_unmapped"] = drive(api, connect=lambda dsn, **kw: (_ for _ in ()).throw(Stop("cancel")))
    out["begin_raises_no_rollback"] = drive(api, fail={"BEGIN": boom})
    out["set_local_raises_rolls_back"] = drive(api, fail={"SET LOCAL": boom})
    out["identity_execute_raises_rolls_back"] = drive(api, fail={"current_database": boom})
    out["select_execute_raises_rolls_back"] = drive(api, fail={"unnest": boom})
    out["identity_fetchone_raises"] = drive(api, fetch_fail={"identity": boom})
    out["select_fetchall_raises"] = drive(api, fetch_fail={"select": boom})
    out["clock_raises"] = drive(api, clock=boom)
    out["clock_raises_a_base_exception_unmapped"] = drive(api, clock=Stop("cancel"))
    out["rollback_raises_after_a_clean_read"] = drive(api, fail={"ROLLBACK": boom})
    out["rollback_raises_after_a_failed_read"] = drive(api, fail={"unnest": OSError("read " + SECRET), "ROLLBACK": boom})
    out["exit_raises_after_a_clean_read"] = drive(api, exit_error=boom)
    out["a_base_exception_in_the_read_is_unmapped_and_rolled_back"] = drive(api, fail={"unnest": Stop("cancel")})
    out["a_value_error_in_the_read_is_mapped"] = drive(api, fail={"unnest": ValueError(SECRET)})
    out["key_error_in_the_read"] = drive(api, fail={"current_database": KeyError(SECRET)})
    identities = {}
    for name, row in (("none", None), ("empty_rows", "empty"), ("two_columns", ("zeus", "public")), ("four_columns", ("a", "b", "c", "d")),
                      ("non_text_member", ("zeus", "public", 18)), ("none_member", ("zeus", None, "18.0")), ("text_not_a_sequence", "abc"),
                      ("mapping", {"database": "a", "schema": "b", "server_version": "c"}), ("set_of_three", {"a", "b", "c"}),
                      ("bytes_members", (b"a", b"b", b"c"))):
        identities[name] = drive(api, identity=[] if row == "empty" else [row])
    out["malformed_identity_is_unavailable"] = identities
    out["a_malformed_identity_still_rolled_back"] = [e[1] for e in identities["two_columns"]["events"] if e[0] == "execute"][-1]
    out["row_of_the_wrong_width_is_a_value_error_not_unavailable"] = drive(api, select_rows=[("tasks", "task-known")])
    out["row_of_too_many_columns_is_a_value_error"] = drive(api, select_rows=[("tasks", "task-known", {}, 1)])
    out["row_that_is_not_iterable_is_a_type_error"] = drive(api, select_rows=[5])
    out["unhashable_row_key_is_a_type_error"] = drive(api, select_rows=[(["tasks"], "task-known", {})])
    out["each_refusal_is_the_same_public_outcome"] = sorted({(r["raised"], r["message"], r["reason_code"]) for r in (
        out["connect_raises"], out["connect_returns_none"], out["begin_raises_no_rollback"], out["select_execute_raises_rolls_back"],
        out["clock_raises"], out["rollback_raises_after_a_clean_read"], identities["none"], identities["bytes_members"])})
    out["unavailable_has_no_chain"] = all(r["cause_is_none"] and r["context_is_none"] and not r["traceback_leaks_secret"] for r in (
        out["connect_raises"], out["connect_raises_a_runtime_error"], out["connect_returns_none"], out["connect_returns_a_non_connection"],
        out["begin_raises_no_rollback"], out["set_local_raises_rolls_back"], out["select_execute_raises_rolls_back"],
        out["identity_fetchone_raises"], out["clock_raises"], out["rollback_raises_after_a_clean_read"], identities["none"]))
    return out


# ---- coverage ------------------------------------------------------------------------------------------------------------------
BRANCH_COVERAGE = {
    "ReadOnlySnapshot.__init__ raise ContractError('Snapshot timeouts must be positive integers')": "s1_constructor.timeouts_refused (a refusal per operand and per type)",
    "ReadOnlySnapshot._session except Exception (connect)": "s3_failures.connect_raises, connect_raises_a_runtime_error, connect_rejects_the_keywords",
    "ReadOnlySnapshot._session raise SnapshotUnavailable (conn is None)": "s3_failures.connect_raises, connect_returns_none",
    "ReadOnlySnapshot.observe except Exception": "s3_failures (begin, set_local, identity, select, fetch, clock, rollback, exit, non-connection)",
    "ReadOnlySnapshot.observe raise SnapshotUnavailable (failed)": "s3_failures.begin_raises_no_rollback and every mapped fault",
    "ReadOnlySnapshot.observe raise SnapshotUnavailable (identity)": "s3_failures.malformed_identity_is_unavailable",
    "SnapshotUnavailable.__init__": "s1_constructor.exception_class",
}


M7_TESTS = {
    "tests/test_council.py::test_unavailable_or_malformed_snapshot_... (the port half)": "s3_failures (connect_error, read_error), s2_observe.ok",
    "tests/test_council.py::test_application_snapshot_refusal_keeps_no_raw_exception_chain (the port's SnapshotUnavailable)": "s3_failures.unavailable_has_no_chain",
    "tests/test_council.py (the constructor refusal ReadOnlySnapshot('dsn', connect=..., connect_timeout=0))": "s1_constructor.timeouts_refused.zero_connect",
    "tests/test_council.py (port.observe over 21 records: AutonomousManifestError)": "s2_observe.selection_refused_before_any_connection.twenty_one",
    "tests/test_council_postgres.py::test_read_only_repeatable_read_snapshot_against_postgres": {
        "unreachable": "integration lane (owner): a real PostgreSQL (isolated_pgstore) and psycopg.connect"},
    "tests/test_council_postgres.py (the unreachable endpoint with connect_timeout=1)": {
        "unreachable": "integration lane (owner): a real socket to 127.0.0.1:1; the mapping is s3_failures.connect_raises"},
}


def run(api) -> dict:
    result = {"s1_constructor": s1_constructor(api), "s2_observe": s2_observe(api), "s3_failures": s3_failures(api)}
    result["s4_m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = {name: len(result[name]) for name in ("s1_constructor", "s2_observe", "s3_failures")}
    return result
