from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from codex_harness.adapters.commands import python_channel_environment, run_process
from codex_harness.domain.model import canonical, hook_apply, require


class NativeHooks:
    def __init__(self, service, git, artifacts):
        self.service, self.git, self.artifacts = service, git, artifacts

    def candidate(self, hook_id: str, candidate: dict) -> dict:
        manifest_text = self.git._git("show", candidate["revision"] + ":harness_hooks/" + hook_id + ".json")
        manifest = json.loads(manifest_text)
        spec = manifest["spec"]
        hook_apply(spec, [], "linux")
        require(spec["kind"] == "native_hook", "Self-improvement hook must include an executable native hook")
        script = self.git._git("show", candidate["revision"] + ":" + spec["script_path"], strip=False)
        require(hashlib.sha256(script.encode()).hexdigest() == spec["script_sha256"], "Hook script hash mismatch")
        require(set(manifest["cases"]) == {"reproduction", "normal_case"}, "Hook requires recurrence and negative cases")
        for cases in manifest["cases"].values():
            require(isinstance(cases, list) and bool(cases), "Empty hook case suite")
            for case in cases:
                require(set(case) == {"input", "output", "exit_code"}, "Invalid hook test case")
        self.service.propose(hook_id, candidate["author"], spec, candidate["revision"])
        with self.service.store.transaction() as tx:
            tx.put("hook_cases", hook_id, {"id": hook_id, "revision": candidate["revision"], "cases": manifest["cases"]})
        return spec

    def materialize(self, hook: dict) -> Path:
        spec = hook["spec"]
        script = self.git._git("show", hook["revision"] + ":" + spec["script_path"], strip=False)
        require(hashlib.sha256(script.encode()).hexdigest() == spec["script_sha256"], "Reviewed script changed")
        receipt = self.artifacts.put(script, "git:" + hook["revision"] + ":" + spec["script_path"])
        return self.artifacts.root / (receipt["ref"][7:] + ".txt")

    def canary(self, hook_id: str) -> dict:
        hook = self.service.get_hook(hook_id)
        script = self.materialize(hook)
        with self.service.store.transaction() as tx:
            manifest = tx.get("hook_cases", hook_id)
        require(manifest["revision"] == hook["revision"], "Stale hook fixtures")
        checks = {}
        for kind, cases in manifest["cases"].items():
            passed, evidence = True, []
            for case in cases:
                # INV-ENCODING-001: case input/output cross the channel as UTF-8 in both directions.
                result = run_process([sys.executable, str(script)], input_text=canonical(case["input"]),
                                     timeout=30, env=python_channel_environment())
                try:
                    output = json.loads(result.stdout) if result.stdout.strip() else None
                except json.JSONDecodeError:
                    output = {"invalid_json": result.stdout}
                passed = passed and result.returncode == case["exit_code"] and output == case["output"]
                evidence.append({"input": case["input"], "output": output, "exit_code": result.returncode,
                                 "stderr": result.stderr})
            checks[kind] = {"passed": passed, "evidence": self.artifacts.put(canonical(evidence), "hook-canary:" + hook_id)["ref"]}
        return checks

    def configuration(self) -> dict:
        hooks = self.service.active_hooks()
        output = {}
        for hook in hooks:
            if hook["status"] != "active" or hook["spec"].get("kind") != "native_hook":
                continue
            script = self.materialize(hook)
            argv = [sys.executable, str(script)]
            command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
            spec = hook["spec"]
            output.setdefault(spec["event"], []).append({"matcher": spec["matcher"],
                                                       "hooks": [{"type": "command", "command": command, "timeout": 30}]})
        return output
