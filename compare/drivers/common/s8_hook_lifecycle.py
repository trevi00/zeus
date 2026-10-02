"""Shared S8 scenario steps (`research.hook_lifecycle`): M7 `Harness.get_hook/propose/record_canary/activate/rollback/
active_hooks/prepare_command`, the rest of the hook lifecycle after S4's `record_incident`/`review`, over MemoryStore.

Layer: harness (never shipped)

`api.hooks(store)` is the side's object with the M7 SELF-TRANSACTING call shapes (`activate` also takes a given
`transaction=`); `api.advance(seconds)` moves the scripted clock; `api.reset()` resets clock and ids. Values/refusals,
the final hook records, the events written (ids and times) and the full record set (by body digest) are compared.
"""

from __future__ import annotations

import hashlib
import json

ALIAS = {"kind": "executable_alias", "match": "python", "replacement": "py", "platform": "windows"}
OTHER_ALIAS = {"kind": "executable_alias", "match": "python", "replacement": "python3", "platform": "windows"}
NODE_ALIAS = {"kind": "executable_alias", "match": "node", "replacement": "nodejs", "platform": "windows"}
GIT_ALIAS = {"kind": "executable_alias", "match": "git", "replacement": "git.exe", "platform": "windows"}
NPM_ALIAS = {"kind": "executable_alias", "match": "npm", "replacement": "npm.cmd", "platform": "windows"}
CHECKS = {"reproduction": True, "normal_case": True, "cli_start": True}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def run(api) -> dict:
    api.reset()
    store = api.MemoryStore()
    h = api.hooks(store)
    out = {}
    author = "worker:implementation"

    def step(name, fn, *args, **kwargs):
        out[name] = call(fn, *args, **kwargs)
        api.advance(1)

    def seed(hid, **fields):
        with store.transaction() as tx:
            tx.put("hooks", hid, {"id": hid, "status": "required", "revision": None, "spec": None, "author": None,
                                  "reviews": [], "version": 1, "canary": None, **fields})

    def reviewed(hid, revision, spec):
        sh = api.digest(spec)
        h.review(hid, "lead:improvement", revision, sh, True, "ev-lead")
        h.review(hid, "conductor", revision, sh, True, "ev-conductor")

    for hid in ("hook-a", "hook-b", "hook-c", "hook-d", "hook-g", "hook-h", "hook-n"):
        seed(hid)
    seed("hook-rej", status="rejected", spec=OTHER_ALIAS, revision="rev-0", author=author, version=3)
    seed("hook-act", status="active", spec=NODE_ALIAS, revision="rev-1", author=author, version=2)
    seed("hook-prev", status="active", spec=GIT_ALIAS, revision="rev-2", author=author, version=4,
         previous_active={"id": "hook-prev", "status": "active", "spec": NPM_ALIAS, "revision": "rev-1", "author": author,
                          "reviews": [], "version": 3, "canary": None})

    # propose: refusals, then the happy path and replacements
    step("get_hook_unknown", h.get_hook, "hook-none")
    step("get_hook_required", h.get_hook, "hook-a")
    step("propose_non_worker", h.propose, "hook-a", "lead:improvement", ALIAS, "rev-1")
    step("propose_unknown_actor", h.propose, "hook-a", "worker:nobody", ALIAS, "rev-1")
    step("propose_empty_revision", h.propose, "hook-a", author, ALIAS, "")
    step("propose_bad_spec", h.propose, "hook-a", author, {"kind": "mystery"}, "rev-1")
    step("propose_unknown_hook", h.propose, "hook-none", author, ALIAS, "rev-1")
    step("propose_active_not_replaceable", h.propose, "hook-act", author, ALIAS, "rev-9")
    step("propose_a", h.propose, "hook-a", author, ALIAS, "rev-1")
    step("propose_a_replaces_candidate", h.propose, "hook-a", author, ALIAS, "rev-1b")
    step("propose_a_back", h.propose, "hook-a", author, ALIAS, "rev-1")
    step("propose_b", h.propose, "hook-b", author, ALIAS, "rev-1")
    step("propose_rejected_replaced", h.propose, "hook-rej", author, ALIAS, "rev-1")
    step("propose_native_hook", h.propose, "hook-n", author,
         {"kind": "native_hook", "event": "Stop", "matcher": "*", "script_path": "hooks/x.py", "script_sha256": "0" * 64},
         "rev-1")
    for hid in ("hook-c", "hook-g", "hook-h"):
        h.propose(hid, author, ALIAS if hid != "hook-h" else OTHER_ALIAS, "rev-1")

    # record_canary: refusals (hook-b is only a candidate), then success/failure
    sha = api.digest(ALIAS)
    step("canary_missing_check", h.record_canary, "hook-a", "rev-1", sha, {"reproduction": True, "normal_case": True})
    step("canary_extra_check", h.record_canary, "hook-a", "rev-1", sha, {**CHECKS, "bonus": True})
    step("canary_non_bool", h.record_canary, "hook-a", "rev-1", sha, {**CHECKS, "cli_start": 1})
    step("canary_before_review", h.record_canary, "hook-b", "rev-1", sha, CHECKS)
    step("canary_unknown_hook", h.record_canary, "hook-none", "rev-1", sha, CHECKS)
    reviewed("hook-a", "rev-1", ALIAS)
    reviewed("hook-c", "rev-1", ALIAS)
    reviewed("hook-g", "rev-1", ALIAS)
    reviewed("hook-h", "rev-1", OTHER_ALIAS)
    step("canary_stale_revision", h.record_canary, "hook-a", "rev-0", sha, CHECKS)
    step("canary_stale_hash", h.record_canary, "hook-a", "rev-1", "0" * 64, CHECKS)
    step("canary_ok_a", h.record_canary, "hook-a", "rev-1", sha, CHECKS)
    step("canary_fails_c", h.record_canary, "hook-c", "rev-1", sha, {**CHECKS, "normal_case": False})
    step("canary_ok_g", h.record_canary, "hook-g", "rev-1", sha, CHECKS)
    step("canary_ok_h", h.record_canary, "hook-h", "rev-1", api.digest(OTHER_ALIAS), CHECKS)
    step("canary_again_after_verified", h.record_canary, "hook-a", "rev-1", sha, CHECKS)

    # activate: refusals, the spec changed after the canary, then activation (own unit, and a given transaction)
    step("activate_not_verified_candidate", h.activate, "hook-b")
    step("activate_rejected_by_canary", h.activate, "hook-c")
    step("activate_unknown", h.activate, "hook-none")
    with store.transaction() as tx:
        changed = tx.get("hooks", "hook-g")
        changed["spec"] = {**ALIAS, "replacement": "py3"}
        tx.put("hooks", "hook-g", changed)
    step("activate_spec_changed_after_canary", h.activate, "hook-g")

    def activate_in_unit(hid):
        with store.transaction() as tx:
            return h.activate(hid, transaction=tx)

    step("activate_a_given_transaction", activate_in_unit, "hook-a")
    step("activate_a_again", h.activate, "hook-a")

    # active_hooks / prepare_command: one active alias, no match, a conflict, then the conflict resolved by rollback
    step("active_hooks_one_alias", h.active_hooks)
    step("prepare_windows", h.prepare_command, ["python", "-V"], "windows")
    step("prepare_other_platform", h.prepare_command, ["python", "-V"], "linux")
    step("prepare_other_executable", h.prepare_command, ["cargo", "build"], "windows")
    step("prepare_active_git_alias", h.prepare_command, ["git", "status"], "windows")
    step("prepare_previous_active_npm_alias", h.prepare_command, ["npm", "ci"], "windows")
    step("prepare_empty_argv", h.prepare_command, [], "windows")
    step("activate_h_own_unit", h.activate, "hook-h")
    step("prepare_conflicting_active_hooks", h.prepare_command, ["python", "-V"], "windows")
    step("prepare_conflict_not_triggered", h.prepare_command, ["git", "status"], "windows")

    # rollback: refusals, to previous_active, to rolled_back
    step("rollback_empty_reason", h.rollback, "hook-h", "")
    step("rollback_inactive", h.rollback, "hook-b", "why")
    step("rollback_unknown", h.rollback, "hook-none", "why")
    step("rollback_without_previous", h.rollback, "hook-h", "conflict")
    step("rollback_to_previous_active", h.rollback, "hook-prev", "regression")
    step("prepare_npm_after_rollback_to_previous", h.prepare_command, ["npm", "ci"], "windows")
    step("prepare_git_after_rollback_to_previous", h.prepare_command, ["git", "status"], "windows")
    step("rollback_previous_again", h.rollback, "hook-prev", "regression-2")
    step("active_hooks_after_rollback", h.active_hooks)
    step("prepare_after_rollback", h.prepare_command, ["python", "-V"], "windows")
    step("get_hook_rolled_back", h.get_hook, "hook-h")
    step("get_hook_previous", h.get_hook, "hook-prev")

    with store.transaction() as tx:
        rows = tx.records()
    out["hooks"] = sorted([r["id"], r["body"]] for r in rows if r["bucket"] == "hooks")
    out["events"] = sorted([r["id"], r["body"]] for r in rows if r["bucket"] == "events")
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
