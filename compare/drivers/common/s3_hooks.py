"""Scenario body `hooks.native_container` (REBUILD-DESIGN-v2 §5.3 S3b and §5.4: native-hook digest binding,
refusal, timeout and container-only execution are characterized on the reference BEFORE S3b is enabled;
RESEARCH-S3 D7, G6, F-R2/F-R3).

Layer: harness (never shipped); standard library only. No Codex process is spawned: the App Server
client's process boundary (`__enter__`/`__exit__`/`request`) is replaced by a scripted peer, and the hook
store, Git and artifact store are in-memory fakes. What is recorded:
- the isolation refusal (`codex_container_native_hooks_unsupported`) and its order against the profile
  selection, for every transport/isolation/hook combination;
- the host hook configuration the reference composes (command = host interpreter + artifact path, the
  fixed per-hook timeout) and its script-digest refusal;
- the App Server trust binding: which discovered entries are bound, what trusted hash is recorded (the
  peer-reported `currentHash`, whatever the peer's trust status), the count refusal, and the resulting
  `-c hooks=...` server arguments.

`api` provides `role_profile(config, provider, transport, action, read_only, hooks)`,
`configuration(active_hooks, scripts, root)`, `AppServer(executable, hooks)`, `toml_literal(value)`,
`IsolationError`, `ContractError`, `python_executable` (the interpreter path the host command names).
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from s1_common import outcome, relative

HOOK = {"PreToolUse": [{"matcher": "shell", "hooks": [{"type": "command", "command": "python3 /h/a.py", "timeout": 30}]}]}
IMAGE = "sha256:" + "ab" * 32


class Stop(Exception):
    pass


def _bind(api, hooks: dict, discovered: list, hook_state: dict | None = None) -> dict:
    server = api.AppServer("/usr/local/bin/codex", hooks)
    if hook_state is not None:
        server.hook_state = dict(hook_state)
    calls = []

    def request(method, params, timeout=30):
        calls.append({"method": method, "params": params})
        if method == "hooks/list":
            return {"data": discovered}
        raise Stop(method)

    server.request = request
    entered = []
    server.__enter__ = lambda: entered.append("enter") or server
    server.__exit__ = lambda *a: entered.append("exit")
    result = outcome(lambda: server.run("p", "/workspace", {"type": "object"}, 30))
    return {"outcome": result, "calls": [c["method"] for c in calls],
            "hooks_list_params": calls[0]["params"] if calls and calls[0]["method"] == "hooks/list" else None,
            "restarts": entered, "hook_state": server.hook_state, "server_arguments": server.server_arguments()}


def run(api) -> dict:
    out: dict = {}
    base = Path(tempfile.mkdtemp(prefix="zeus-s3-hooks-")).resolve()
    # -- the isolation refusal and its order ---------------------------------------------------------
    configs = {"none": None, "claude_only": {"mode": "docker", "image": IMAGE},
               "with_store": {"mode": "docker", "image": IMAGE, "codex": {"credential_store": "/srv/x"}}}
    rows = {}
    for config_name, config in configs.items():
        for provider, transport in (("codex", "app_server"), ("claude", "claude_cli"), ("codex", "claude_cli")):
            for action, read_only in (("implement", False), ("review", True)):
                for hooks_name, hooks in (("no_hooks", {}), ("active_hook", HOOK)):
                    key = f"{config_name}:{provider}/{transport}:{action}:{'ro' if read_only else 'rw'}:{hooks_name}"
                    rows[key] = api.role_profile(config, provider, transport, action, read_only, hooks)
    out["role_profile"] = rows
    # -- the host configuration and its script digest ---------------------------------------------------
    script = "import sys, json\njson.load(sys.stdin)\nprint('{}')\n"
    digest = hashlib.sha256(script.encode()).hexdigest()
    spec = {"kind": "native_hook", "event": "PreToolUse", "matcher": "shell", "script_path": "harness_hooks/h.py",
            "script_sha256": digest}
    active = [
        {"id": "h1", "status": "active", "revision": "r" * 40, "spec": spec},
        {"id": "h2", "status": "active", "revision": "r" * 40, "spec": {**spec, "event": "Stop", "matcher": "*"}},
        {"id": "h3", "status": "proposed", "revision": "r" * 40, "spec": spec},
        {"id": "h4", "status": "active", "revision": "r" * 40, "spec": {**spec, "kind": "prompt_rule"}},
    ]
    roots = {"ROOT": str(base), "PYTHON": api.python_executable}
    out["configuration"] = relative(outcome(lambda: api.configuration(active, {"harness_hooks/h.py": script}, base)),
                                    roots)
    out["configuration_digest_mismatch"] = relative(
        outcome(lambda: api.configuration(active[:1], {"harness_hooks/h.py": script + "#changed\n"}, base)), roots)
    out["configuration_none_active"] = outcome(lambda: api.configuration(active[2:], {"harness_hooks/h.py": script}, base))
    # -- the App Server trust binding ------------------------------------------------------------------
    command = HOOK["PreToolUse"][0]["hooks"][0]["command"]
    two = {"PreToolUse": HOOK["PreToolUse"],
           "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /h/b.py", "timeout": 30}]}]}
    entry = {"key": "k1", "currentHash": "sha256:" + "1" * 64, "trustStatus": "untrusted",
             "handler": {"command": command}}
    bindings = {
        "untrusted_bound": (HOOK, [{"hooks": [entry]}]),
        "modified_bound_to_current": (HOOK, [{"hooks": [{**entry, "trustStatus": "modified"}]}]),
        "trusted": (HOOK, [{"hooks": [{**entry, "trustStatus": "trusted"}]}]),
        "top_level_command": (HOOK, [{"hooks": [{"key": "k2", "currentHash": "sha256:" + "2" * 64,
                                                 "command": command}]}]),
        "missing": (HOOK, [{"hooks": []}]),
        "foreign_only": (HOOK, [{"hooks": [{**entry, "handler": {"command": "python3 /other.py"}}]}]),
        "extra_foreign_ignored": (HOOK, [{"hooks": [entry, {**entry, "key": "k9", "handler": {"command": "x"}}]}]),
        "duplicate_discovery": (HOOK, [{"hooks": [entry]}, {"hooks": [{**entry, "key": "k1b"}]}]),
        "two_of_two": (two, [{"hooks": [entry, {"key": "k3", "currentHash": "sha256:" + "3" * 64,
                                                 "handler": {"command": "python3 /h/b.py"}}]}]),
        "one_of_two": (two, [{"hooks": [entry]}]),
    }
    out["binding"] = {name: _bind(api, hooks, discovered) for name, (hooks, discovered) in bindings.items()}
    out["binding_already_bound"] = _bind(api, HOOK, [], {"k1": {"enabled": True, "trusted_hash": "sha256:x"}})
    out["server_arguments"] = {
        "no_hooks": api.AppServer("/usr/local/bin/codex", None).server_arguments(),
        "hooks_unbound": api.AppServer("/usr/local/bin/codex", HOOK).server_arguments(),
    }
    out["toml_literal"] = api.toml_literal({"a": [1, "x\"y", {"b": None, "c": True}], "d": 1.5})
    return out
