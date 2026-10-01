"""Shared S7 scenario steps (`delivery.migration_evidence_cli`): the in-process operator CLI cases of the M7 migration
evidence producer (`main(argv)`, `cli_ports`, `parser`; INV-HOST-MIGRATION-001), split out of
`delivery.migration_evidence` (S7 pilot 46, owner-authorized: the CLI is the S10 carry, so this family is REFERENCE-ONLY
until S10).

Layer: harness (never shipped). Never imports `codex_harness`.

Twelve M7 tests, moved WHOLE from the evidence family under the same group and case names, with the same worlds, the same
doubles and the same CLI calls (every case whose code path calls `api.main`, `api.cli_ports` or `api.parser`):
- `capture`: `cli_prints_and_exits_by_ok`;
- `refuse`: `cli_argument.*` (the arguments the parser refuses, 4);
- `read_only`: `lane_path_through_read_only_snapshots`, `cli_ports_are_read_only_snapshots`;
- `archive`: `unreadable_archive_file.*` (4);
- `host_reader`: `reused_pid_keeps_only_an_argv_digest.*` (2);
- `ph4_13`: `post_transition_without_an_archive`, `cli_comparison_read_only.*` (2);
- `f1`: `leak.*` (37, each also records its result-side checks), `credential_as_env_name.*` (3), `malformed_dsn.*` (6),
  `cli_store_failure_leaks_no_credential`.

The fixtures, the world, the tables and the normalization are `s7_migration_evidence`'s, IMPORTED. `api` is the evidence
reference driver's api (`main`, `parser`, `cli_ports`, `patched`, `environ`, `patch_connect`, `forbid_writer_store`,
`LaneSnapshotStore`, `conninfo_to_dict`, `OperationalError` and the rest). `cli_argv` and `cli` are `World.cli_argv` and
`World.cli` of the evidence module, moved here as functions of the world. The split is proven lossless by
`split_check.py`.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
from pathlib import Path

from s7_migration_evidence import (
    ENTRY_PID,
    ENTRY_TICKS,
    MARKER,
    MID,
    PLAN,
    PW,
    RECEIPT_NAME,
    SUP_PID,
    SUP_TICKS,
    TARGET,
    Lab,
    archived,
    dsn,
    put,
    refusal,
    tables,
    tree,
)

M7_TESTS = 12


def printed(run: dict):
    try:
        return json.loads(run["stdout"])
    except ValueError:
        return None


def cli_argv(w, *extra) -> list:
    return ["observe-limited-active", "--migration-id", MID, "--expected-id", w.effective_id,
            "--target-id", TARGET, "--plan-id", PLAN, "--actor", "claude-ph4", "--root", str(w.root),
            "--schema", "zeus_aibox_migration", "--control-schema", "zeus_aibox_control", *extra]


def cli(w, *extra, ports=None, patches=None, env=None) -> dict:
    """`main(argv)` in this process, its stdout and stderr captured, under the write guard."""
    api, out, err = w.api, io.StringIO(), io.StringIO()
    attributes = dict(patches or {})
    if ports is not None:
        attributes["cli_ports"] = lambda args: ports
    with contextlib.ExitStack() as stack:
        if attributes:
            stack.enter_context(api.patched(**attributes))
        if env is not None:
            stack.enter_context(api.environ(env))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        stack.enter_context(w.guard.active())
        try:
            code = api.main(cli_argv(w, *extra))
        except SystemExit as exc:
            code = ["exit", exc.code]
    run = {"code": code, "stdout": out.getvalue(), "stderr": err.getvalue()}
    body = printed(run)
    if isinstance(body, dict) and "projections" in body:
        w.learn(body)
    return run


def group_capture(lab: Lab) -> dict:
    out = {}

    w = lab.world()
    ports = w.ports()
    run = cli(w, ports=ports)
    body = printed(run)
    first = {"code": run["code"], "keys_include": sorted({"observation", "evidence", "transition_draft"} & set(body)),
             "ok": body["observation"]["ok"]}
    w.edit(RECEIPT_NAME, instance_id=None)
    ports = w.ports()
    run = cli(w, ports=ports)
    second = {"code": run["code"], "reason_code": printed(run)["observation"]["reason_code"]}
    put(lab, out, "capture", "test_cli_prints_observation_evidence_and_draft_and_exits_by_ok",
        "cli_prints_and_exits_by_ok", w.wrap({"success": first, "canary_failure": second}))
    return out


def group_refuse(lab: Lab) -> dict:
    api, out = lab.api, {}

    for argv in (["--consumed", "true"], ["--passed", "true"], ["--receipt", "r.json"], ["--apply"]):
        w = lab.world()
        out_io, err_io = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out_io), contextlib.redirect_stderr(err_io):
                api.parser().parse_args(cli_argv(w, *argv))
            outcome = "accepted"
        except SystemExit as exc:
            outcome = {"exit": exc.code}
        put(lab, out, "refuse", "test_cli_accepts_no_claim_substitute_receipt_or_apply_argument",
            "cli_argument." + argv[0].lstrip("-"), w.wrap({"outcome": outcome,
                                                          "printed_to_stdout": out_io.getvalue() != ""}))
    return out


def group_read_only(lab: Lab) -> dict:
    api, out = lab.api, {}

    # The lane path: every store read through a read-only snapshot, exactly this SQL shape.
    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return list(self.rows)

    class Connection:
        """A psycopg connection double serving the fixture store of the connection's search path."""

        def __init__(self, stores, connection, kwargs, log):
            options = api.conninfo_to_dict(connection)["options"]
            assert options.startswith("-c search_path=")
            self.schema = options.split("=", 1)[1]
            self.store, self.statements = stores[self.schema], []
            log.append({"schema": self.schema, "kwargs": kwargs, "statements": self.statements})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=()):
            self.statements.append(sql)
            if sql == "SELECT current_schema()":
                return Rows([(self.schema,)])
            if sql == "SELECT body FROM documents WHERE bucket=%s AND id=%s":
                body = self.store.data.get(tuple(params))
                return Rows([] if body is None else [(copy.deepcopy(body),)])
            if sql == "SELECT body FROM documents WHERE bucket=%s ORDER BY id":
                return Rows([(copy.deepcopy(body),) for (bucket, _), body in sorted(self.store.data.items())
                             if bucket == params[0]])
            return Rows([])

    w = lab.world()
    with w.control_store.transaction() as tx:
        tx.put("fleet_registry", "fleet", {"id": "fleet", "config": {"lanes": [
            {"id": "harness", "schema": "zeus_lane_harness"}, {"id": "other", "schema": "zeus_lane_other"}]}})
    stores = {"zeus_aibox_migration": w.coordinator, "zeus_aibox_control": w.control_store,
              "zeus_lane_harness": w.delivery}
    before = {name: copy.deepcopy(store.data) for name, store in stores.items()}
    log: list = []
    host = w.host()
    env = {"ZEUS_TEST_MIGRATION_DSN": "postgresql://zeus@127.0.0.1:1/zeus",
           "ZEUS_TEST_CONTROL_DSN": "postgresql://zeus@127.0.0.1:1/zeus"}
    with api.patch_connect(lambda connection, **kwargs: Connection(stores, connection, kwargs, log)):
        run = cli(w, "--dsn-env", "ZEUS_TEST_MIGRATION_DSN", "--control-dsn-env", "ZEUS_TEST_CONTROL_DSN",
                    "--lane", "harness", patches={"HostReader": lambda **kwargs: host}, env=env)
    body = printed(run)
    connections = []
    for entry in log:
        statements = entry["statements"]
        connections.append({
            "schema": entry["schema"], "kwargs": entry["kwargs"], "head": statements[:3], "tail": statements[-1],
            "statements": len(statements), "middle_only_selects": all(sql in (
                "SELECT body FROM documents WHERE bucket=%s AND id=%s",
                "SELECT body FROM documents WHERE bucket=%s ORDER BY id") for sql in statements[3:-1]),
            "advisory_lock": any("pg_advisory" in sql.lower() for sql in statements)})
    put(lab, out, "read_only", "test_lane_path_reads_every_store_through_read_only_snapshots_with_the_exact_sql_shape",
        "lane_path_through_read_only_snapshots", w.wrap({
            "code": run["code"], "ok": body["observation"]["ok"], "stderr_empty": run["stderr"] == "",
            "schemas": sorted({entry["schema"] for entry in log}), "connections": connections,
            "lane_reads": len([entry for entry in log if entry["schema"] == "zeus_lane_harness"]),
            "stores_unchanged": {name: store.data for name, store in stores.items()} == before}))

    w = lab.world()
    connected = []
    stored = []
    with contextlib.ExitStack() as stack:
        stack.enter_context(api.environ({"ZEUS_TEST_DSN": "postgresql://zeus@127.0.0.1:1/zeus"}))
        stack.enter_context(api.patch_connect(lambda *a, **k: connected.append(1) or (_ for _ in ()).throw(
            AssertionError("connected"))))
        stack.enter_context(api.forbid_writer_store(stored))
        args = api.parser().parse_args(["observe-limited-active", "--migration-id", MID, "--expected-id", "a" * 64,
                                        "--target-id", TARGET, "--plan-id", PLAN, "--actor", "a", "--root", "/r",
                                        "--dsn-env", "ZEUS_TEST_DSN", "--schema", "zeus_aibox_migration",
                                        "--control-dsn-env", "ZEUS_TEST_DSN", "--control-schema",
                                        "zeus_aibox_control"])
        ports = api.cli_ports(args)
        snapshot = {"coordinator_is_snapshot": isinstance(ports.coordinator, api.LaneSnapshotStore),
                    "control_is_snapshot": isinstance(ports.control, api.LaneSnapshotStore),
                    "schemas": [ports.coordinator.schema, ports.control.schema],
                    "delivery_is_control": ports.delivery(ports.control) is ports.control}
        args.schema = "public"
        public = w.attempt(lambda: api.cli_ports(args))
    put(lab, out, "read_only", "test_cli_ports_are_read_only_snapshots_and_connect_nothing",
        "cli_ports_are_read_only_snapshots", w.wrap({
            **snapshot, "public_schema": public, "connections_opened": len(connected),
            "writer_store_constructed": len(stored)}))
    return out


def group_archive(lab: Lab) -> dict:
    out = {}

    for content in (None, "{not json", "[]", "NaN"):
        w = lab.world()
        (w.tmp / "archive").mkdir()
        path = w.tmp / "archive" / "archived-observation.json"
        if content is not None:
            path.write_text(content)
        built = []
        patches = {"cli_ports": lambda args: built.append(1) or (_ for _ in ()).throw(AssertionError("ports built"))}
        first = cli(w, "--expect", str(path), patches=patches)
        second = cli(w, "--expect", "relative/archive.json", patches=patches)
        put(lab, out, "archive", "test_ph4_13_an_unreadable_archive_file_is_refused_naming_the_argument_only",
            "unreadable_archive_file." + ("missing" if content is None else {"{not json": "not_json", "[]": "array",
                                                                             "NaN": "nan"}[content]),
            w.wrap({"absolute_path": {"code": first["code"], "printed": printed(first)},
                    "relative_path": {"code": second["code"], "printed": printed(second)},
                    "ports_built": len(built)}))
    return out


def group_host_reader(lab: Lab) -> dict:
    out = {}

    for role in ("supervisor", "entry"):
        w = lab.world()
        secret = "--password=" + PW + "-argv-secret"
        pid, ppid, ticks = (SUP_PID, 1, SUP_TICKS) if role == "supervisor" else (ENTRY_PID, SUP_PID, ENTRY_TICKS)
        w.process(pid, ppid, ticks, ["/usr/bin/other-tool", secret])
        ports = w.ports()
        run = cli(w, ports=ports)
        body = printed(run)
        projection = body["projections"][role]
        put(lab, out, "host_reader",
            "test_a_reused_pid_keeps_only_an_argv_digest_and_its_arguments_never_reach_the_output",
            "reused_pid_keeps_only_an_argv_digest." + role, w.wrap({
                "code": run["code"], "argument_absent_from_output": PW not in run["stdout"] + run["stderr"],
                "diagnostic": body["diagnostic"], "projection": projection,
                "no_raw_argv": "argv" not in projection, "argv_match": projection["argv_match"],
                "validated": projection["validated"],
                "digest_is_the_cmdline_digest": projection["argv_sha256"] == hashlib.sha256(
                    b"/usr/bin/other-tool\0" + secret.encode() + b"\0").hexdigest()}))
    return out


def group_ph4_13(lab: Lab) -> dict:
    api, out = lab.api, {}

    w = lab.world()
    ports = w.ports()
    outcome = w.attempt(lambda: api.observe(w.request(), ports, post_transition=True))
    built = []
    run = cli(w, "--post-transition", patches={
        "cli_ports": lambda args: built.append(1) or (_ for _ in ()).throw(AssertionError("ports built"))})
    put(lab, out, "ph4_13", "test_ph4_13_post_transition_without_an_archive_is_refused_before_any_read",
        "post_transition_without_an_archive", w.wrap({
            "outcome": outcome, "no_command_ran": w.runner.calls == [],
            "no_store_transaction": all(store.transactions == 0 for store in w.stores.values()),
            "cli": {"code": run["code"], "printed": printed(run), "ports_built": len(built)}}))

    for post in (False, True):
        w = lab.world()
        archive = archived(w.observe())
        (w.tmp / "archive").mkdir()
        path = w.tmp / "archive" / "archived-observation.json"
        path.write_text(json.dumps(archive, sort_keys=True, indent=2))
        if post:
            w.submit(archive)
        ports = w.ports()
        before = (tree(w.root, w.proc), copy.deepcopy(w.coordinator.data), copy.deepcopy(w.control_store.data),
                  copy.deepcopy(w.delivery.data))
        extra = ["--expect", str(path)] + (["--post-transition"] if post else [])
        w.runner.calls.clear()
        w.runner.envs.clear()
        w.guard.os_opens.clear()
        w.guard.opens.clear()
        run = cli(w, *extra, ports=ports)
        after = (tree(w.root, w.proc), w.coordinator.data, w.control_store.data, w.delivery.data)
        body = printed(run)
        record = {"code": run["code"], "no_draft_or_evidence": "transition_draft" not in body and "evidence" not in body,
                  "post_check": body["comparison"]["post_check"], "comparison": body["comparison"],
                  "no_write_attempt": w.guard.attempts == [], "no_store_put": all(s.puts == [] for s in w.stores.values()),
                  "filesystem_and_stores_unchanged": after == before, "stderr_empty": run["stderr"] == ""}
        w.learn(body)
        ports = w.ports()
        opposite = cli(w, "--expect", str(path), *([] if post else ["--post-transition"]), ports=ports)
        record["opposite_mode"] = {"code": opposite["code"],
                                   "reason_code": printed(opposite)["comparison"]["reason_code"]}
        put(lab, out, "ph4_13", "test_ph4_13_the_comparison_is_read_only_and_exits_by_its_verdict",
            "cli_comparison_read_only." + ("post_transition" if post else "pre_submit"), w.wrap(record))
    return out


def group_f1(lab: Lab) -> dict:
    api, out, T = lab.api, {}, tables(lab.api)

    for case in sorted(T.leak):
        mutate, code, detail = T.leak[case]
        w = lab.world()
        mutate(w)
        result = w.observe()
        record = refusal(lab, w, result, code, detail) if code is not None else w.wrap(w.summary(result))
        record["marker_absent_from_the_result"] = MARKER not in json.dumps(result, sort_keys=True)
        record["success_keeps_its_draft"] = (result["observation"]["ok"] is True
                                             and result["transition_draft"] is not None) if code is None else None
        ports = w.ports()
        run = cli(w, ports=ports)
        body = printed(run)
        record["cli"] = {"code": run["code"], "exit_expected": run["code"] == (0 if code is None else 1),
                         "marker_absent": MARKER not in run["stdout"] + run["stderr"], "stderr_empty": run["stderr"] == "",
                         "same_digest": body["result_sha256"] == result["result_sha256"],
                         "recomputes": w.recompute(body)}
        put(lab, out, "f1", "test_f1_no_excluded_key_or_untyped_value_reaches_the_result_or_the_cli", "leak." + case,
            w.n(record))


    # A credential typed where an environment name belongs, and a malformed DSN, are refused without its value.
    for option in ("--dsn", "--dsn-env", "--control-dsn-env"):
        w = lab.world()
        secret = dsn(PW)
        built = []
        run = cli(w, option, secret, patches={"HostReader": lambda **kwargs: built.append(1) or (_ for _ in ()).throw(
            AssertionError("host reader built"))}, env={"HARNESS_DATABASE_URL": "postgresql://zeus@127.0.0.1:1/zeus"})
        put(lab, out, "f1", "test_a_credential_given_as_an_env_name_is_refused_and_never_echoed",
            "credential_as_env_name." + option.lstrip("-"), w.wrap({
                "code": run["code"], "secret_absent": PW not in run["stdout"] + run["stderr"],
                "printed": printed(run), "host_reader_built": len(built)}))

    values = {"malformed_percent_escape": "postgresql://zeus:" + "hun%zz" + "ter2@127.0.0.1/zeus",
              "secret_token": "sk-live-" + PW + "-secret",
              "unterminated_host": "postgresql://zeus:" + PW + "@[unterminated/zeus"}
    for name, value in values.items():
        for option in ("--dsn-env", "--control-dsn-env"):
            w = lab.world()
            built = []
            other = "--control-dsn-env" if option == "--dsn-env" else "--dsn-env"
            run = cli(w, option, "ZEUS_TEST_SECRET", other, "ZEUS_TEST_DSN", patches={
                "HostReader": lambda **kwargs: built.append(1) or (_ for _ in ()).throw(AssertionError("built"))},
                env={"ZEUS_TEST_DSN": "postgresql://zeus@127.0.0.1:1/zeus", "ZEUS_TEST_SECRET": value})
            put(lab, out, "f1", "test_a_malformed_dsn_or_a_secret_variable_is_refused_without_its_value",
                "malformed_dsn." + name + "." + option.lstrip("-"), w.wrap({
                    "code": run["code"], "secret_absent": PW not in run["stdout"] + run["stderr"],
                    "no_traceback": "Traceback" not in run["stderr"], "printed": printed(run),
                    "host_reader_built": len(built)}))

    # A store failure through the real snapshot store with a failing connection: no credential, no host command.
    w = lab.world()
    host_calls = []

    def connect(connection, **kwargs):
        raise api.OperationalError("connection to " + connection + " failed: password " + PW + "-credential")

    with api.patch_connect(connect):
        run = cli(w, "--dsn-env", "ZEUS_TEST_MIGRATION_DSN", "--control-dsn-env", "ZEUS_TEST_CONTROL_DSN", "--lane",
                    "harness", patches={"bounded_run": lambda *a, **k: host_calls.append(1) or (_ for _ in ()).throw(
                        AssertionError("host command"))},
                    env={"ZEUS_TEST_MIGRATION_DSN": dsn(PW + "-credential", "127.0.0.1:1/zeus"),
                         "ZEUS_TEST_CONTROL_DSN": dsn(PW + "-credential", "127.0.0.1:1/zeus")})
    body = printed(run)
    put(lab, out, "f1", "test_cli_store_failure_leaks_no_credential_and_reads_no_host",
        "cli_store_failure_leaks_no_credential", w.wrap({
            "code": run["code"], "credential_absent": PW not in run["stdout"] + run["stderr"],
            "diagnostic": body["diagnostic"], "draft_none": body["transition_draft"] is None,
            "host_commands": len(host_calls)}))
    return out


GROUPS = (("capture", group_capture), ("refuse", group_refuse), ("read_only", group_read_only),
          ("archive", group_archive), ("host_reader", group_host_reader), ("ph4_13", group_ph4_13),
          ("f1", group_f1))


def run(api) -> dict:
    result, counts = {}, {}
    with tempfile.TemporaryDirectory(prefix="s7-migration-evidence-cli-") as raw:
        lab = Lab(api, Path(raw).resolve())
        for name, group in GROUPS:
            result[name] = group(lab)
            counts[name] = len(result[name])
        result["mirrored_tests"] = {test: sorted(keys) for test, keys in sorted(lab.mirrors.items())}
        assert len(result["mirrored_tests"]) == M7_TESTS, sorted(result["mirrored_tests"])
    result["cases_per_group"] = counts
    text = json.dumps(result, sort_keys=True)
    for secret in (PW, "sk-live", MARKER, "postgresql://zeus:"):
        assert secret not in text, "a secret-shaped test value reached the result"
    return result
