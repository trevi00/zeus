"""Scenario bodies `credentials.custody` and `credentials.scrubber` (REBUILD-DESIGN-v2 §5.3 S3: credential
custody and scrubber, I1 (f)4 with RC2-F3 1-5, the scrub/refusal controls; RESEARCH-S3 D1/D2, G3/G4/G5, R4).

Layer: harness (never shipped); standard library only. Every credential here is a dummy written by this
file into the scenario's own temporary directory; no real store, home or environment value is read.
Results carry reason codes, states, key sets, modes and digests; timestamps are never reported.

`api` provides:
- `Broker(store)`: the Codex credential broker (`read_store`, `admit(wait_seconds=)`, `reconcile`,
  `entries`, `quarantined`, and the `Admission` it returns: `issue(run_id, record, home)`, `settle`,
  `release`);
- `read_credential_file(path)`, `credential_shape(data)`, `credential_values(data)`;
- `Scrubber(issued, path)`: the output boundary (`text`, `scrub`, `event`, `failure`, `result`,
  `refresh`), `OutputUnsanitizable`, `REDACTED`, `REDACTED_JWT`, `MIN_SECRET_CHARS`, `MAX_AUTH_BYTES`;
- `IsolationError`, `ContractError`.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

from s1_common import outcome, relative, sha

RUN_A, RUN_B = "a" * 32, "b" * 32


def auth(account="acct-fixture-0001", access="access-fixture-token-000000000001", **extra) -> bytes:
    body = {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "last_refresh": "2026-01-01T00:00:00Z",
            "tokens": {"id_token": 'id-fixture"quoted\\token-0001', "access_token": access,
                       "refresh_token": "refresh-fixture-token-00000000000001", "account_id": account}}
    body.update(extra)
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.write_bytes(data)
    os.chmod(path, mode)


def _store(base: Path, name: str, data: bytes | None = None) -> Path:
    store = base / name / "codex-store"
    store.mkdir(mode=0o700, parents=True)
    os.chmod(store, 0o700)
    _write(store / "auth.json", auth() if data is None else data)
    return store


def _record(path: Path, state: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "lifecycle": []}), encoding="utf-8")


def _entries(api, broker, roots) -> list:
    return [relative({"run_id": e.get("run_id"), "state": e.get("state"), "reason": e.get("reason"),
                      "keys": sorted(e), "home": e.get("home")}, roots) for e in broker.entries()]


def _state(api, broker, store: Path, roots) -> dict:
    marker = broker.quarantined()
    return {"store_sha256": sha((store / "auth.json").read_bytes()) if (store / "auth.json").exists() else None,
            "store_files": sorted(os.listdir(store)) if store.is_dir() else None,
            "quarantine": None if marker is None else {"keys": sorted(marker), "reason": marker.get("reason"),
                                                        "run_id": marker.get("run_id")},
            "entries": outcome(lambda: _entries(api, broker, roots))}


def run_custody(api) -> dict:
    base = Path(tempfile.mkdtemp(prefix="zeus-s3-custody-")).resolve()
    roots = {"BASE": str(base)}
    out: dict = {"read_store": {}, "settle": {}, "admission": {}}

    # -- read_store: every refusal names the check, never the content --------------------------------
    def store_case(name, build):
        store = base / "read" / name / "codex-store"
        store.parent.mkdir(parents=True)
        build(store)
        broker = api.Broker(store)
        row = outcome(broker.read_store)
        if "ok" in row:
            row["ok"] = {"data_sha256": sha(row["ok"][0]), "shape": row["ok"][1]}
        out["read_store"][name] = relative(row, roots)

    def ok(store):
        store.mkdir(mode=0o700)
        _write(store / "auth.json", auth())

    store_case("ok", ok)
    store_case("missing", lambda store: None)
    store_case("mode_0755", lambda store: (ok(store), os.chmod(store, 0o755)))
    store_case("extra_file", lambda store: (ok(store), _write(store / "notes.txt", b"x")))
    store_case("empty_dir", lambda store: store.mkdir(mode=0o700))

    def linked_dir(store):
        real = store.parent / "real"
        ok(real)
        store.symlink_to(real)

    store_case("store_symlink", linked_dir)
    store_case("auth_mode_0644", lambda store: (ok(store), os.chmod(store / "auth.json", 0o644)))

    def auth_symlink(store):
        store.mkdir(mode=0o700)
        _write(store.parent / "elsewhere.json", auth())
        (store / "auth.json").symlink_to(store.parent / "elsewhere.json")

    store_case("auth_symlink", auth_symlink)
    store_case("auth_hardlinked", lambda store: (ok(store), os.link(store / "auth.json", store.parent / "twin.json")))
    store_case("auth_directory", lambda store: (store.mkdir(mode=0o700), (store / "auth.json").mkdir()))
    for name, data in {
        "too_large": b"{" + b" " * (api.MAX_AUTH_BYTES + 1) + b"}",
        "at_limit_unparseable": b"x" * api.MAX_AUTH_BYTES,
        "not_utf8": b"\xff\xfe{}",
        "not_json": b"{not json",
        "array": b"[]",
        "tokens_not_object": json.dumps({"tokens": ["x"]}).encode(),
        "token_empty": auth(access=""),
        "refresh_missing": json.dumps({"tokens": {"id_token": "i" * 9, "access_token": "a" * 9,
                                                  "account_id": "acct"}}).encode(),
        "identity_missing": auth(account=""),
        "api_key": auth(OPENAI_API_KEY="sk-fixture-not-a-real-key"),
        "api_key_empty_string": auth(OPENAI_API_KEY=""),
        "extra_top_level_key": auth(extra_field="kept"),
    }.items():
        store_case(name, lambda store, data=data: (store.mkdir(mode=0o700), _write(store / "auth.json", data)))

    # -- settle: the credential-only write-back table (RC2-F3 3/4) ------------------------------------
    def settle_case(name, mutate, *, then_admit=True):
        store = _store(base, "settle-" + name)
        broker = api.Broker(store)
        admission = broker.admit(wait_seconds=0.0)
        home = store.parent / "runs" / RUN_A / "codex-home"
        record = store.parent / "runs" / RUN_A / "run.json"
        issued = admission.issue(RUN_A, record, home)
        mutate(store, home)
        settled = outcome(admission.settle)
        admission.release()
        row = {"issued": issued, "settle": settled, "after": _state(api, broker, store, roots),
               "home_files": sorted(os.listdir(home)) if home.is_dir() else None,
               "home_mode": oct(home.stat().st_mode & 0o777) if home.is_dir() else None}
        if then_admit:
            nxt = outcome(lambda: broker.admit(wait_seconds=0.0))
            if "ok" in nxt:
                admitted = nxt["ok"]
                nxt = {"ok": {"data_sha256": sha(admitted.data), "shape": admitted.shape}}
                admitted.release()
            row["next_admission"] = nxt
        out["settle"][name] = relative(row, roots)

    settle_case("unchanged", lambda store, home: None)
    settle_case("refreshed_same_identity",
                lambda store, home: _write(home / "auth.json", auth(access="access-fixture-token-REFRESHED-0002")))
    settle_case("identity_changed",
                lambda store, home: _write(home / "auth.json", auth(account="acct-fixture-OTHER")))
    settle_case("structure_changed",
                lambda store, home: _write(home / "auth.json", auth(access="access-new-0000000003", extra="x")))
    settle_case("per_run_missing", lambda store, home: (home / "auth.json").unlink())
    settle_case("per_run_mode", lambda store, home: os.chmod(home / "auth.json", 0o644))
    settle_case("per_run_unparseable", lambda store, home: _write(home / "auth.json", b"{partial"))
    settle_case("per_run_api_key",
                lambda store, home: _write(home / "auth.json", auth(OPENAI_API_KEY="sk-fixture-new")))
    settle_case("store_changed_during_run",
                lambda store, home: (_write(home / "auth.json", auth(access="access-fixture-token-R-0004")),
                                     _write(store / "auth.json", auth(access="access-operator-edit-0005"))))
    settle_case("store_invalid_during_run",
                lambda store, home: (_write(home / "auth.json", auth(access="access-fixture-token-R-0006")),
                                     _write(store / "extra", b"x")))
    settle_case("per_run_symlink",
                lambda store, home: ((home / "auth.json").unlink(),
                                     _write(home / "target.json", auth(access="access-link-000000007")),
                                     (home / "auth.json").symlink_to(home / "target.json")))

    # -- admission: lock, quarantine, prior runs (RC2-F3 5) ------------------------------------------
    def admit_case(name, prepare):
        store = _store(base, "admit-" + name)
        broker = api.Broker(store)
        holder = prepare(store, broker)
        row = outcome(lambda: broker.admit(wait_seconds=0.0))
        if "ok" in row:
            admitted = row["ok"]
            row = {"ok": {"data_sha256": sha(admitted.data), "shape": admitted.shape}}
            admitted.release()
        if isinstance(holder, int):
            os.close(holder)
        row["after"] = _state(api, broker, store, roots)
        out["admission"][name] = relative(row, roots)

    def busy(store, broker):
        descriptor = os.open(broker.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor

    def issued_with_record(state, change=None):
        def prepare(store, broker):
            admission = broker.admit(wait_seconds=0.0)
            record = store.parent / "runs" / RUN_A / "run.json"
            home = store.parent / "runs" / RUN_A / "codex-home"
            admission.issue(RUN_A, record, home)
            admission.release()
            if change is not None:
                _write(home / "auth.json", change)
            if state is not None:
                _record(record, state)
        return prepare

    admit_case("ok", lambda store, broker: None)
    admit_case("busy", busy)
    admit_case("quarantined", lambda store, broker: _write(broker.quarantine_path, b'{"reason": "fixture"}'))
    admit_case("quarantine_unreadable", lambda store, broker: _write(broker.quarantine_path, b"{"))
    admit_case("prior_unsettled_running", issued_with_record("running"))
    admit_case("prior_unsettled_stop_unconfirmed", issued_with_record("stop_unconfirmed"))
    admit_case("prior_unknown_no_record", issued_with_record(None))
    admit_case("prior_removed_unchanged", issued_with_record("removed"))
    admit_case("prior_refused_refreshed", issued_with_record("refused", auth(access="access-fixture-token-RC-0008")))
    admit_case("prior_removed_identity_changed", issued_with_record("removed", auth(account="acct-fixture-SWAP")))

    def unreadable_ledger(store, broker):
        broker.ledger.mkdir(mode=0o700)
        (broker.ledger / (RUN_B + ".json")).write_text("{", encoding="utf-8")

    admit_case("ledger_unreadable", unreadable_ledger)
    admit_case("store_missing_after_lock", lambda store, broker: (os.unlink(store / "auth.json"), os.rmdir(store)))
    out["relative_store_refused"] = outcome(lambda: api.Broker("relative/codex-store"))
    out["invalid_run_id"] = outcome(lambda: api.Broker(base / "x" / "codex-store")._entry_path("../escape"))
    return out


class Custom(Exception):
    pass


def run_scrubber(api) -> dict:
    base = Path(tempfile.mkdtemp(prefix="zeus-s3-scrub-")).resolve()
    out: dict = {}
    issued = auth()
    body = json.loads(issued)
    tokens = body["tokens"]
    out["credential_values"] = sorted(sha(v) for v in api.credential_values(issued))
    out["credential_values_count"] = len(api.credential_values(issued))
    out["credential_values_refusals"] = {name: outcome(lambda data=data: sorted(api.credential_values(data)))
                                         for name, data in {"not_json": b"{", "list": b"[1]", "not_utf8": b"\xff"}.items()}
    out["short_leaf_kept"] = len(api.credential_values(auth(account="short"))) == len(api.credential_values(issued)) - 1
    path = base / "auth.json"
    _write(path, issued)
    scrubber = api.Scrubber(issued, path)
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaXh0dXJlIn0.c2lnbmF0dXJlZml4dHVyZQ"
    texts = {
        "access": "token=" + tokens["access_token"] + " end",
        "refresh_in_json": json.dumps({"refresh": tokens["refresh_token"]}),
        "id_raw_with_quote": "id " + tokens["id_token"],
        "id_json_escaped": json.dumps({"id": tokens["id_token"]}),
        "account": "account " + tokens["account_id"],
        "auth_mode_not_secret": "mode chatgpt and 2026-01-01T00:00:00Z",
        "jwt_shaped": "bearer " + jwt,
        "jwt_prefix_only": "eyJ short",
        "plain": "nothing secret here",
        "two": tokens["access_token"] + tokens["refresh_token"],
    }
    out["text"] = {name: scrubber.text(text) for name, text in texts.items()}
    out["scrub_structure"] = scrubber.scrub({tokens["access_token"]: [texts["access"], 3, None, ("t", jwt)],
                                             "n": 1.5, "b": True})
    # Streamed fragments: a token split across deltas of one item is never forwarded piecewise.
    access = tokens["access_token"]
    stream = []
    for index, delta in enumerate(["prefix ", access[:10], access[10:20], access[20:] + " tail", "e", "yJ"]):
        stream.append(scrubber.event({"method": "item/agentMessage/delta", "params": {"itemId": "i1", "delta": delta}}))
    out["stream_split"] = stream
    out["stream_other_item_independent"] = [
        scrubber.event({"method": "item/agentMessage/delta", "params": {"itemId": "i2", "delta": access[:12]}}),
        scrubber.event({"method": "item/agentMessage/delta", "params": {"itemId": "i3", "delta": "fine"}}),
        scrubber.event({"method": "item/agentMessage/delta", "params": {"itemId": "i2", "delta": "zzz"}}),
    ]
    out["event_non_delta"] = scrubber.event({"method": "item/completed", "params": {"item": {"text": texts["access"]}}})
    # Refresh during the run: the new value joins the set; the old one stays in it.
    refreshed = "access-fixture-token-REFRESHED-9999"
    _write(path, auth(access=refreshed))
    out["after_refresh"] = scrubber.event({"method": "x", "params": {"text": refreshed + " / " + access}})
    # Failures.
    for name, exc in {"contract": api.ContractError("failed with " + refreshed),
                      "runtime": RuntimeError("boom " + access), "oserror": OSError("io " + jwt),
                      "custom": Custom("custom " + access), "clean": ValueError("nothing here")}.items():
        replaced = scrubber.failure(exc)
        out.setdefault("failure", {})[name] = {"type": type(replaced).__name__, "text": str(replaced),
                                               "same_object": replaced is exc}
    events = [{"method": "a", "params": {"t": access}}, {"method": "b", "params": {"t": "ok"}}]
    forwarded = {id(events[0]): {"method": "a", "params": {"t": "FORWARDED"}}}
    out["result"] = scrubber.result({"final": "answer " + refreshed, "events": events, "usage": {"k": access}},
                                    forwarded)
    # Refusals: an unestablishable secret set replaces the output.
    os.chmod(path, 0o644)
    out["event_unreadable"] = outcome(lambda: scrubber.event({"method": "x", "params": {}}))
    out["failure_unreadable"] = (lambda r: {"type": type(r).__name__, "text": str(r),
                                            "reason_code": getattr(r, "reason_code", None)})(
        scrubber.failure(RuntimeError("x " + access)))
    path.unlink()
    out["result_missing"] = outcome(lambda: scrubber.result({"final": "x"}, {}))
    _write(path, b"{truncated")
    out["event_malformed"] = outcome(lambda: scrubber.event({"method": "x", "params": {}}))
    out["construct_malformed"] = outcome(lambda: api.Scrubber(b"not json", path))
    out["construct_list"] = outcome(lambda: api.Scrubber(b"[]", path))
    out["markers"] = {"credential": api.REDACTED, "jwt": api.REDACTED_JWT, "min_secret_chars": api.MIN_SECRET_CHARS}
    out["is_isolation_error"] = issubclass(api.OutputUnsanitizable, api.IsolationError)
    return out
