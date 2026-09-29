"""Shared S4 scenario steps (`hooks.candidate_canary`): the host NativeHooks candidate validation and canary
(M7 `adapters/hooks.NativeHooks.candidate/canary`), with the declarative validator `hook_apply`.

Layer: harness (never shipped)

`api.native_hooks(service, git, artifacts)` builds the side's NativeHooks (the target injects the validator,
the runner and the channel environment); `api.hook_apply` is the side's validator. The service, Git and the
artifact store are in-memory fakes; the canary runs a fixture stdlib script as a child (no provider).
Values/refusals, the proposals the service saw, the hook_cases rows and the canary verdicts are compared
(evidence by content digest; the interpreter and paths never appear).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

SCRIPT = ("import json, sys\n"
          "event = json.load(sys.stdin)\n"
          "if event.get('tool') == 'rm':\n"
          "    print(json.dumps({'decision': 'block'}))\n"
          "    sys.exit(2)\n"
          "print(json.dumps({'decision': 'allow'}))\n")
DIGEST = hashlib.sha256(SCRIPT.encode()).hexdigest()
SPEC = {"kind": "native_hook", "event": "PreToolUse", "matcher": "shell", "script_path": "harness_hooks/h.py",
        "script_sha256": DIGEST}
CASES = {"reproduction": [{"input": {"tool": "rm"}, "output": {"decision": "block"}, "exit_code": 2}],
         "normal_case": [{"input": {"tool": "ls"}, "output": {"decision": "allow"}, "exit_code": 0}]}


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


class Service:
    def __init__(self, store):
        self.store, self.proposed, self.hooks = store, [], {}

    def propose(self, hook_id, author, spec, revision):
        self.proposed.append([hook_id, author, spec, revision])
        self.hooks[hook_id] = {"id": hook_id, "spec": spec, "revision": revision, "status": "proposed"}

    def get_hook(self, hook_id):
        return self.hooks[hook_id]


class Git:
    def __init__(self, files):
        self.files = files

    def _git(self, *args, strip=True):
        revision, path = args[1].split(":", 1)
        text = self.files[path]
        return text.strip() if strip else text


class Artifacts:
    def __init__(self, root):
        self.root, self.bodies = Path(root), {}

    def put(self, text, source):
        ref = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        (self.root / (ref[7:] + ".txt")).write_text(text, encoding="utf-8")
        self.bodies[ref] = text
        return {"ref": ref}


def run(api) -> dict:
    out = {}
    manifest = json.dumps({"spec": SPEC, "cases": CASES})
    files = {"harness_hooks/h1.json": manifest, "harness_hooks/h.py": SCRIPT}
    candidate = {"revision": "r" * 40, "author": "worker:implementation"}
    with tempfile.TemporaryDirectory(prefix="zeus-s4-hooks-") as raw:
        store = api.MemoryStore()
        service, artifacts = Service(store), Artifacts(raw)
        hooks = api.native_hooks(service, Git(files), artifacts)
        out["candidate"] = call(hooks.candidate, "h1", candidate)
        out["proposed"] = service.proposed
        with store.transaction() as tx:
            out["hook_cases"] = tx.get("hook_cases", "h1")
        canary = hooks.canary("h1")
        out["canary"] = {kind: {"passed": check["passed"],
                                "evidence": [{k: e[k] for k in ("input", "output", "exit_code")}
                                             for e in json.loads(artifacts.bodies[check["evidence"]])]}
                         for kind, check in sorted(canary.items())}
        bad = dict(files)
        bad["harness_hooks/h.py"] = SCRIPT + "#changed\n"
        out["candidate_hash_mismatch"] = call(api.native_hooks(Service(store), Git(bad), artifacts).candidate, "h1",
                                              candidate)
        for name, change in (("cases_missing", {"cases": {"reproduction": CASES["reproduction"]}}),
                             ("case_empty", {"cases": {"reproduction": [], "normal_case": CASES["normal_case"]}}),
                             ("case_malformed", {"cases": {**CASES, "normal_case": [{"input": {}}]}}),
                             ("not_native", {"spec": {**SPEC, "kind": "executable_alias", "match": "a",
                                                      "replacement": "b", "platform": "linux"}}),
                             ("absolute_script", {"spec": {**SPEC, "script_path": "/etc/x"}})):
            changed = dict(files)
            changed["harness_hooks/h1.json"] = json.dumps({"spec": SPEC, "cases": CASES, **change})
            out["candidate_" + name] = call(api.native_hooks(Service(store), Git(changed), artifacts).candidate,
                                            "h1", candidate)
        wrong = dict(files)
        wrong["harness_hooks/h.py"] = SCRIPT.replace("'block'", "'deny'")
        failing = Service(store)
        failing.hooks["h1"] = {"id": "h1", "spec": {**SPEC, "script_sha256": hashlib.sha256(
            wrong["harness_hooks/h.py"].encode()).hexdigest()}, "revision": "r" * 40, "status": "proposed"}
        verdict = api.native_hooks(failing, Git(wrong), artifacts).canary("h1")
        out["canary_mismatch"] = {kind: check["passed"] for kind, check in sorted(verdict.items())}
        stale = Service(store)
        stale.hooks["h1"] = {"id": "h1", "spec": SPEC, "revision": "s" * 40, "status": "proposed"}
        out["canary_stale_fixtures"] = call(api.native_hooks(stale, Git(files), artifacts).canary, "h1")
    out["hook_apply"] = [call(api.hook_apply, spec, ["x"], "linux") for spec in (
        SPEC, {**SPEC, "event": "Other"}, {**SPEC, "script_path": "../x"}, {**SPEC, "script_sha256": "ab"},
        {"kind": "executable_alias", "match": "x", "replacement": "y", "platform": "linux"},
        {"kind": "executable_alias", "match": "x", "replacement": "y", "platform": "windows"}, {"kind": "other"})]
    return out
