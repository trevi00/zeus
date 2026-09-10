from __future__ import annotations

import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from jsonschema import validate

from codex_harness.adapters.codex import resolve_codex
from codex_harness.adapters.output_schema import preflight
from codex_harness.domain.model import ContractError, canonical, require
from codex_harness.domain.policy import POLICY

NAMESPACE_DENIAL = "bwrap: No permissions to create a new namespace"


def namespace_failure(event: object) -> bool:
    """Inspect completed execution output only, never prompts or command arguments."""
    if not isinstance(event, dict) or event.get("method") != "item/completed":
        return False
    params = event.get("params")
    if (not isinstance(params, dict)
            or not all(isinstance(params.get(k), str) and params[k]
                       for k in ("threadId", "turnId"))):
        return False
    item = params.get("item")
    return (isinstance(item, dict) and item.get("type") == "commandExecution"
            and isinstance(item.get("id"), str) and bool(item["id"])
            and item.get("status") == "failed"
            and type(item.get("exitCode")) is int and item["exitCode"] != 0
            and isinstance(item.get("aggregatedOutput"), str)
            and NAMESPACE_DENIAL in item["aggregatedOutput"])


def toml_literal(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml_literal(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(toml_literal(v) for v in value) + "]"
    return json.dumps(value)


class AppServer:
    """Versioned Codex JSON-RPC stdio client; no shell interpolation or shared thread."""

    def __init__(self, executable: str | None = None, hooks: dict | None = None,
                 context_window: int | None = None):
        self.executable = executable or resolve_codex()
        require(bool(self.executable), "Codex CLI unavailable")
        self.process = None
        self.sequence = 0
        self.incoming = queue.Queue()
        self.notifications = deque()
        self.stderr = deque(maxlen=20)
        self.hooks = hooks or {}
        self.hook_state = {}
        self.readers = []
        self.context_window = context_window

    def __enter__(self):
        flags = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})
        argv = [self.executable, "app-server"]
        if self.context_window:
            argv += ["-c", "model_context_window=" + str(self.context_window)]
        if self.hooks:
            argv += ["-c", "hooks=" + toml_literal({**self.hooks, "state": self.hook_state}), "--enable", "hooks"]
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace", **flags)
        self.readers = [threading.Thread(target=self._read, daemon=True), threading.Thread(target=self._errors, daemon=True)]
        for reader in self.readers:
            reader.start()
        self.request("initialize", {"clientInfo": {"name": "codex_harness", "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}}, 20)
        self.send({"method": "initialized"})
        return self

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.incoming.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.incoming.put(None)

    def _errors(self):
        for line in self.process.stderr:
            self.stderr.append(line)

    def send(self, value: dict):
        self.process.stdin.write(canonical(value) + "\n")
        self.process.stdin.flush()

    def _receive(self, timeout: float, poll: bool = False):
        try:
            value = self.incoming.get(timeout=max(timeout, 0.01))
        except queue.Empty as exc:
            if poll:
                return {}
            raise ContractError("Codex App Server timed out") from exc
        require(value is not None, "Codex App Server exited unexpectedly: " + "".join(self.stderr)[-2000:])
        if "id" in value and "method" in value:
            # This unattended protocol cannot answer interactive questions as user consent.
            self.send({"id": value["id"], "error": {"code": -32601,
                       "message": "Interactive requests are unsupported; use assignment constraints"}})
        return value

    def request(self, method: str, params: dict, timeout: float = 30):
        require(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
                'Request timeout must be finite and positive')
        deadline = time.monotonic() + timeout
        if method == "turn/start" and "outputSchema" in params:
            preflight(params["outputSchema"])
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        while time.monotonic() < deadline:
            value = self._receive(deadline - time.monotonic())
            if value.get("id") == request_id and "method" not in value:
                require(time.monotonic() < deadline, f"Codex {method} timed out")
                require("error" not in value, f"Codex {method} error: {value.get('error')}")
                return value.get("result", {})
            self.notifications.append(value)
        raise ContractError(f"Codex {method} timed out")

    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 240,
            thread_id: str | None = None, on_event=None, read_only: bool = False, on_tick=None,
            model: str | None = None) -> dict:
        require(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
                'Execution timeout must be finite and positive')
        deadline = time.monotonic() + timeout
        def request_budget():
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'Codex execution budget exceeded before turn start')
            return min(30, remaining)

        require(model is None or (isinstance(model, str) and model.strip()),
                "model must be a nonempty string")
        options = {"cwd": str(Path(cwd).resolve()), "approvalPolicy": "never",
                   "sandbox": "danger-full-access"}
        if model is not None:
            options["model"] = model
        if read_only:
            options["developerInstructions"] = "This is an independent review. Inspect and test, but do not edit tracked source, commit, push, merge, or deploy."
        if self.hooks and not self.hook_state:
            discovered = self.request("hooks/list", {"cwds": [options["cwd"]]}, request_budget())
            commands = {hook["command"] for groups in self.hooks.values()
                        for group in groups for hook in group["hooks"]}
            entries = [hook for row in discovered["data"] for hook in row["hooks"]
                       if hook.get("handler", {}).get("command") in commands
                       or hook.get("command") in commands]
            require(len(entries) == sum(len(g["hooks"]) for groups in self.hooks.values() for g in groups),
                    "Codex did not discover all verified hooks")
            self.hook_state = {hook["key"]: {"enabled": True, "trusted_hash": hook["currentHash"]} for hook in entries}
            self.__exit__()
            self.incoming = queue.Queue()
            self.notifications.clear()
            self.__enter__()
        if thread_id:
            response = self.request("thread/resume", {"threadId": thread_id, **options}, request_budget())
        else:
            response = self.request("thread/start", options, request_budget())
        thread_id = response["thread"]["id"]
        turn_options = {"threadId": thread_id,
                        "input": [{"type": "text", "text": prompt}], "outputSchema": schema}
        if model is not None:
            turn_options["model"] = model
        turn = self.request("turn/start", turn_options, request_budget())
        turn_id = turn["turn"]["id"]
        events, answer_text, usage = [], "", None
        inspection_failures = {}
        rotate, interrupted = False, False
        active_tools = set()

        def blocked_result(error=None):
            # INV-RELEASE-001: transport loss cannot erase observed inspection failure.
            return {"answer": None, "model_answer_text": answer_text, "events": events,
                    "thread_id": thread_id, "usage": usage, "rotate": False,
                    "interrupted": False, "inspection_blocked": True,
                    "inspection_failures": list(inspection_failures.values()),
                    "termination_error": error, "requested_model": model}

        while time.monotonic() < deadline:
            if on_tick:
                on_tick()
            try:
                event = (self.notifications.popleft() if self.notifications
                         else self._receive(min(5, deadline - time.monotonic()), poll=True))
            except (ContractError, OSError) as exc:
                if inspection_failures:
                    return blocked_result(str(exc))
                raise
            if not event:
                continue
            method, params = event.get("method", ""), event.get("params", {})
            if params.get("threadId", thread_id) != thread_id:
                continue
            if params.get("turnId", turn_id) != turn_id:
                continue
            events.append(event)
            if on_event:
                on_event(event)
            if method == "thread/tokenUsage/updated":
                usage = params["tokenUsage"]
                capacity = usage.get("modelContextWindow")
                # Latest request occupancy is not the lifetime total across requests.
                rotate = rotate or bool(capacity and usage["last"]["totalTokens"] >= capacity * POLICY.context_checkpoint_fraction)
            item = params.get("item", {})
            if method == "item/started" and item.get("type") in {"commandExecution", "fileChange", "mcpToolCall"}:
                active_tools.add(item["id"])
            if method == "item/completed":
                active_tools.discard(item.get("id"))
                if read_only and namespace_failure(event):
                    # INV-RECURRENCE-001: redelivery of one command is not a new incident.
                    inspection_failures.setdefault(item["id"], event)
                if item.get("type") == "agentMessage":
                    answer_text = item.get("text", "")
            if method == "turn/completed":
                if params["turn"].get("id") != turn_id:
                    continue
                status = params["turn"]["status"]
                if inspection_failures:
                    return blocked_result()
                error = params["turn"].get("error")
                # INV-RECURRENCE-001: only the provider's failed-turn field is authoritative.
                if (status == "failed" and params.get("threadId") == thread_id
                        and isinstance(error, dict)
                        and error.get("codexErrorInfo") == "usageLimitExceeded"):
                    return {"answer": None, "events": events, "thread_id": thread_id,
                            "turn_id": turn_id, "usage": usage, "rotate": False,
                            "interrupted": False,
                            "failure": {"cause": "codex-provider-usage-limit-exceeded",
                                        "provider_error": error}}
                require(status in {"completed", "interrupted"},
                        f"Codex turn failed: {params['turn'].get('error')}")
                if status == "completed":
                    answer = json.loads(answer_text)
                    validate(answer, schema)
                else:
                    answer = None
                return {"answer": answer, "events": events, "thread_id": thread_id,
                        "usage": usage, "rotate": rotate, "interrupted": status == "interrupted",
                        "requested_model": model}
            if rotate and not active_tools and not interrupted and not inspection_failures:
                self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                interrupted = True
        if inspection_failures:
            return blocked_result("Codex turn execution budget exceeded")
        raise ContractError("Codex turn execution budget exceeded")

    def __exit__(self, *_):
        if not self.process:
            return
        if self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               capture_output=True, timeout=20)
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                # INV-RESOURCE-001: reap a server that ignores graceful termination.
                if os.name == "nt":
                    self.process.kill()
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=20)
        for reader in self.readers:
            reader.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
