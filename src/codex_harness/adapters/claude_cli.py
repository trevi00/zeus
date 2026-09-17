"""Non-interactive Claude Code CLI transport: `claude --print`, text stdin, stream-json stdout.

What this adapter is responsible for, and what it refuses to claim:

The prompt never appears in an argument vector or a shell string. It is written to the child's
stdin by a thread of its own, so a child that never reads stdin blocks that thread and nothing
else. Both output pipes are drained by their own threads into a bounded queue, with a per-line
byte limit, a total byte limit and a queue depth, so a flooding or silent child cannot exhaust
this process or stall the tick that renews the lease. One monotonic deadline covers the whole
run, and the tick and the cancel check run even while no event has arrived for minutes.

Entry is the moment the process starts, not the moment this object is constructed: initialization
inside Claude Code can already touch the working tree, so everything after `Popen` is treated as
an execution that happened (INV-OBSERVATION-001). Termination kills only the tree this adapter
created and then *confirms* the exit; an unconfirmed termination is an unknown outcome that blocks,
never a failure the caller may retry.

The result is classified from what was observed. A clean exit is not an answer, an assistant
sentence is not an answer, and a provider's own claim that it honoured the schema is not a
validation: the structured output is validated here against the same schema subset the rest of the
harness uses. Usage is read only from the terminal result message, so a redelivered or partial
message cannot be added twice, and a reported cost is recorded as the provider's estimate.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.execution_output import completed_output
from codex_harness.adapters.process_tree import ProcessTree, TreeOwnershipLeak
from codex_harness.adapters.worker_profile import (
    delivery_receipt,
    evidence_root,
    hook_command,
    hook_receipts,
    hook_settings,
    load_profile,
    merge_settings,
    profile_digest,
    profile_environment,
    session_directory,
    verified_interpreter,
)
from codex_harness.domain.model import ContractError, canonical, digest, require
from codex_harness.domain.observation import redact_text
from codex_harness.domain.policy import POLICY
from codex_harness.domain.provider_stream import ClaudeStream

IDENTITY = ClaudeStream.identity
TRANSPORT = ClaudeStream.transport
SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Names that stand for "whatever the latest model of this family is". A provider that answers with
# a concrete model has not disagreed with an alias, and this harness cannot decide the pairing.
MODEL_ALIASES = ("fable", "opus", "sonnet", "haiku", "default")
FLAG = re.compile(r"--[a-zA-Z][a-zA-Z0-9-]*")

# The child inherits only what it needs to start and to authenticate as this host already does.
# Zeus's own database, cache and operator settings are never among them.
BASE_ENVIRONMENT = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR",
    "HOME", "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "NUMBER_OF_PROCESSORS", "OS",
    "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SHELL", "USER", "LOGNAME",
    "TERM", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
)
# Authentication stays exactly as the host already has it: these names are passed through when the
# host sets them and left absent when it does not. No value is ever read, logged or synthesized,
# and nothing here switches a subscription login to an API key.
AUTHENTICATION_ENVIRONMENT = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                              "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")
DENIED_ENVIRONMENT_PREFIXES = ("ZEUS_", "HARNESS_", "POSTGRES_", "PG")
DENIED_ENVIRONMENT_NAMES = ("DATABASE_URL", "REDIS_URL", "COMPOSE_PROJECT_NAME")


def resolve_claude(executable: str | None = None) -> str | None:
    if executable:
        return executable
    return shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")


def child_environment(base: dict | None = None) -> tuple[dict, dict]:
    """Build the child's environment from an allow-list and report which names it carries.

    The report names only variables, never values, so it can be stored beside the execution."""
    source = dict(os.environ if base is None else base)
    env, authentication = {}, []
    for name in BASE_ENVIRONMENT:
        if name in source:
            env[name] = source[name]
    for name in AUTHENTICATION_ENVIRONMENT:
        if name in source:
            env[name] = source[name]
            authentication.append(name)
    env["PYTHONIOENCODING"] = "utf-8"
    withheld = sorted(name for name in source if name not in env
                      and (name.upper().startswith(DENIED_ENVIRONMENT_PREFIXES)
                           or name.upper() in DENIED_ENVIRONMENT_NAMES))
    return env, {"inherited": sorted(env), "authentication_present": authentication,
                 "withheld_zeus_names": withheld,
                 "note": "names only; no value from the host environment is recorded or logged"}


def claude_settings(runtime: dict | None) -> dict | None:
    """Per-run permission settings, passed as a value on the command line.

    The host's own settings files are never edited: this is the only place the run's tool
    permissions come from, it lives for exactly this process, and a rule may contain spaces
    because it travels as JSON rather than as a space-separated option value.
    """
    runtime = runtime or {}
    allow = [str(rule) for rule in runtime.get("allowed_tools") or []]
    deny = [str(rule) for rule in runtime.get("disallowed_tools") or []]
    if not allow and not deny:
        return None
    return {"permissions": {"allow": allow, "deny": deny,
                            "defaultMode": str(runtime.get("permission_mode", "acceptEdits"))}}


class ClaudeUnavailable(ContractError):
    """The CLI cannot be used for this request; nothing was started (a refusal before entry)."""


class ClaudeCodeRuntime:
    """One assigned task's Claude Code execution. Constructed per attempt, never reused."""

    enters_on_open = False  # entry is the process start inside run(), not this object's creation

    def __init__(self, *, model: str, runtime: dict | None = None, executable: str | None = None,
                 max_budget_usd: float | None = None, settings_document: dict | None = None,
                 environment: dict | None = None, probe_timeout: int = 30,
                 launcher: list | None = None, limits: dict | None = None,
                 project_delivery: dict | None = None):
        require(type(model) is str and bool(model.strip()), "Claude requires an explicit model name")
        self.model = model.strip()
        self.runtime = dict(runtime or {})
        self.executable = resolve_claude(executable)
        self.max_budget_usd = max_budget_usd
        self.settings_document = settings_document
        self.environment_source = environment
        self.probe_timeout = probe_timeout
        # A launcher is the interpreter a protocol-test child needs in front of its script. It is
        # recorded with every run, so evidence from a fixture can never be read as a real provider
        # measurement. Production resolves an executable and leaves this empty.
        self.launcher = [str(part) for part in (launcher or [])]
        self.limit_overrides = dict(limits or {})
        # INV-WORKER-PROFILE-001: the profile is chosen by configuration alone and verified now,
        # before any probe or process. Unconfigured runs keep every existing default untouched.
        self.profile = None
        self.profile_interpreter = None
        if self.runtime.get("worker_profile") is not None:
            self.profile = load_profile(self.runtime["worker_profile"])
            self.profile_interpreter = verified_interpreter(self.runtime.get("profile_interpreter"))
        # INV-PROJECT-EVIDENCE-001 (R3): the executor resolved the HOST profile against this run's
        # checkout; nothing here is read from an assignment message or a model output. Its allow
        # rules are exact command strings, so a wildcard or a non-Bash rule is refused before entry.
        self.project_delivery = None
        if project_delivery is not None:
            rules = project_delivery.get("permissions_allow") if isinstance(project_delivery, dict) else None
            require(isinstance(rules, list) and bool(rules)
                    and all(type(rule) is str and rule.startswith("Bash(") and rule.endswith(")")
                            and len(rule) > len("Bash()") and "*" not in rule for rule in rules)
                    and type(project_delivery.get("document")) is str and bool(project_delivery["document"])
                    and type(project_delivery.get("workspace")) is str,
                    "Project delivery must carry exact Bash rules, a document and its workspace")
            self.project_delivery = project_delivery
        self.version = None
        self.help_digest = None
        self.capabilities = ()
        self.process = None
        self.tree = None
        self.session_id = None
        self._termination = None

    # ---- availability, checked before anything is entered ---------------------------------------
    def probe(self) -> dict:
        if not self.executable:
            return {"executable": None, "passed": False, "version": "", "exit_code": None}
        result = run_process([*self.launcher, self.executable, "--version"], timeout=self.probe_timeout)
        return {"executable": self.executable, "passed": result.returncode == 0,
                "version": result.stdout.strip(), "exit_code": result.returncode}

    def _read_capabilities(self) -> tuple:
        result = run_process([*self.launcher, self.executable, "--help"], timeout=self.probe_timeout)
        require(result.returncode == 0, "Claude CLI did not report its options")
        self.help_digest = digest(result.stdout)
        return tuple(sorted(set(FLAG.findall(result.stdout))))

    def __enter__(self):
        """Resolve and check the installed CLI. Every failure here is a refusal before entry."""
        if not self.executable:
            raise ClaudeUnavailable("Claude Code CLI not installed")
        probe = self.probe()
        if not probe["passed"]:
            raise ClaudeUnavailable("Claude Code CLI did not report a version")
        self.version = probe["version"]
        self.capabilities = self._read_capabilities()
        missing = sorted(flag for flag in self._planned_flags() if flag not in self.capabilities)
        if missing:
            # An option this version does not have is never passed and never silently dropped.
            raise ClaudeUnavailable("Installed Claude Code lacks required options: " + ", ".join(missing))
        return self

    def __exit__(self, *_):
        if self.tree is not None:
            if self.process is not None and self.process.poll() is None:
                self._terminate("context_exit")
            self.tree.close()  # on Windows the job's kill-on-close is the last guarantee
            self.tree = None

    # ---- command construction -------------------------------------------------------------------
    def _planned_flags(self) -> list:
        flags = ["--print", "--output-format", "--input-format", "--model", "--session-id",
                 "--permission-mode", "--max-budget-usd", "--json-schema"]
        if self.runtime.get("verbose", True):
            flags.append("--verbose")
        if self.runtime.get("permission_prompts"):
            flags.append("--permission-prompts")
        if self.runtime.get("strict_mcp_config"):
            flags.append("--strict-mcp-config")
        if self.runtime.get("restricted"):
            flags.append("--restricted")
        if self.runtime.get("setting_sources") is not None:
            flags.append("--setting-sources")
        if self.runtime.get("tools"):
            flags.append("--tools")
        if self.settings_document is not None or self.profile is not None or self.project_delivery is not None:
            flags.append("--settings")
        if self.profile is not None or self.project_delivery is not None:
            flags.append("--append-system-prompt")
        return flags

    def _system_prompt(self) -> str | None:
        """The worker profile document, then the host's per-run project section when there is one."""
        parts = [part["document"] for part in (self.profile, self.project_delivery) if part is not None]
        return "\n".join(parts) if parts else None

    def _run_settings(self, evidence_directory) -> dict | None:
        """The settings value for this run: the configured document, plus the profile's hooks and
        Bash rules when a profile is selected, plus the host project checks' exact Bash rules.
        Without either it is the document unchanged; mode and deny rules are never touched."""
        settings = self.settings_document
        if self.profile is not None:
            command = hook_command(self.profile_interpreter, self.profile["hook_path"],
                                   evidence_directory, profile_digest(self.profile))
            settings = merge_settings(settings, self.profile, hook_settings(command))
        if self.project_delivery is not None:
            settings = json.loads(json.dumps(settings or {}))
            permissions = settings.setdefault("permissions", {})
            permissions["allow"] = [*(permissions.get("allow") or []),
                                    *(rule for rule in self.project_delivery["permissions_allow"]
                                      if rule not in (permissions.get("allow") or []))]
            permissions.setdefault("deny", [])
        return settings

    def _command(self, *, schema: dict, session_id: str,
                 settings_document: dict | None = None) -> tuple[list, list]:
        """Return (argv, manifest). The manifest is what may be written to a log: every element
        that can carry schema, context or configuration text is replaced by its digest."""
        require(self.max_budget_usd is not None, "Claude execution requires a configured spend ceiling")
        if settings_document is None:
            settings_document = self.settings_document
        argv = [*self.launcher, self.executable]
        manifest = [*self.launcher, "<claude-executable>"]

        def add(*values, sensitive_from: int | None = None):
            for index, value in enumerate(values):
                argv.append(value)
                hidden = sensitive_from is not None and index >= sensitive_from
                manifest.append(f"<{digest(value)}>" if hidden else value)

        add("--print", "--output-format", str(self.runtime.get("output_format", "stream-json")),
            "--input-format", str(self.runtime.get("input_format", "text")))
        if self.runtime.get("verbose", True):
            add("--verbose")
        add("--model", self.model, "--session-id", session_id)
        add("--permission-mode", str(self.runtime.get("permission_mode", "acceptEdits")))
        if self.runtime.get("permission_prompts"):
            add("--permission-prompts", str(self.runtime["permission_prompts"]))
        if self.runtime.get("strict_mcp_config"):
            add("--strict-mcp-config")
        if self.runtime.get("restricted"):
            # Confines the file tools to the working directories and ignores the host's user,
            # project and local settings, without touching how the host authenticates. Off until a
            # real call has verified it end to end (see the implementation record).
            add("--restricted")
        if self.runtime.get("setting_sources") is not None:
            add("--setting-sources", str(self.runtime["setting_sources"]))
        if self.runtime.get("tools"):
            add("--tools", ",".join(str(tool) for tool in self.runtime["tools"]))
        if settings_document is not None:
            add("--settings", canonical(settings_document), sensitive_from=1)
        if self._system_prompt() is not None:
            # The document travels as a value; the log keeps its digest (INV-WORKER-PROFILE-001).
            add("--append-system-prompt", self._system_prompt(), sensitive_from=1)
        add("--max-budget-usd", format(float(self.max_budget_usd), ".2f"))
        add("--json-schema", canonical(schema), sensitive_from=1)
        return argv, manifest

    # ---- execution ------------------------------------------------------------------------------
    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 240, *, on_event=None,
            on_tick=None, read_only: bool = False, model: str | None = None, on_enter=None,
            cancel=None, session_id: str | None = None) -> dict:
        require(type(timeout) in (int, float) and timeout == timeout and 0 < timeout < float("inf"),
                "Execution timeout must be finite and positive")
        require(type(prompt) is str and bool(prompt), "Claude execution requires a prompt")
        require(isinstance(schema, dict) and bool(schema), "Claude execution requires an output schema")
        # `read_only` has a mechanism here (tool and permission restrictions) whose effect this
        # adapter has not independently verified, so it is refused rather than claimed.
        require(not read_only, "claude_cli cannot prove a read-only execution; it is not assigned reviews")
        require(self.process is None, "This transport object already ran; every attempt builds its own")
        require(model is None or model == self.model,
                "The requested model differs from the configured Claude model")
        session_id = session_id or str(uuid4())
        require(SESSION_ID.fullmatch(session_id) is not None, "Claude session id must be a UUID")
        self.session_id = session_id
        workspace = str(Path(cwd).resolve())
        environment, environment_report = child_environment(self.environment_source)
        profile_delivery, evidence_directory = None, None
        if self.profile is not None:
            # Receipts live outside the checkout, one directory per session, created before the
            # process so a hook that runs during initialization already has somewhere to write.
            evidence_directory = session_directory(evidence_root(self.runtime), session_id)
            environment, profile_env = profile_environment(environment, workspace, self.profile_interpreter)
            environment_report = {**environment_report, "profile": profile_env}
            profile_delivery = delivery_receipt(self.profile, evidence_directory)
        project_receipt = None
        if self.project_delivery is not None:
            require(self.project_delivery["workspace"] == workspace,
                    "Project delivery was resolved for another checkout than this run's workspace")
            # Each delivered command assigns its own context PYTHONPATH; the root `src` the legacy
            # profile prepares must not stand in for a host-selected context.
            environment.pop("PYTHONPATH", None)
            project_receipt = {"profile_digest": self.project_delivery.get("profile_digest"),
                               "project_digest": self.project_delivery.get("project_digest"),
                               "checks": [entry["check_id"] for entry in self.project_delivery.get("commands", [])],
                               "permissions_added": len(self.project_delivery["permissions_allow"]),
                               "permissions_sha256": digest(self.project_delivery["permissions_allow"]),
                               "document_sha256": digest(self.project_delivery["document"]),
                               "pythonpath": "unset for the process; every host command assigns its context value",
                               "compliance": "not judged here: delivery is recorded, the worker's execution is not"}
            environment_report = {**environment_report, "project_evidence": {"pythonpath": None}}
        settings_document = self._run_settings(evidence_directory)
        argv, manifest = self._command(schema=schema, session_id=session_id,
                                       settings_document=settings_document)
        limits = {"line_bytes": POLICY.claude_line_bytes, "stream_bytes": POLICY.claude_stream_bytes,
                  "queue_events": POLICY.claude_event_queue, "retained_events": POLICY.claude_events_retained,
                  **self.limit_overrides, "deadline_seconds": float(timeout)}
        command = {"argv": manifest, "argv_length": len(argv), "executable": self.executable,
                   "cli_version": self.version, "help_digest": self.help_digest,
                   "prompt_transport": "stdin", "prompt_sha256": digest(prompt),
                   "prompt_bytes": len(prompt.encode("utf-8")), "schema_sha256": digest(schema),
                   "settings_sha256": digest(settings_document) if settings_document is not None else None,
                   "worker_profile": profile_delivery,
                   **({"project_evidence": project_receipt} if project_receipt is not None else {}),
                   "cwd": workspace, "session_id": session_id, "requested_model": self.model,
                   "launcher": list(self.launcher),
                   "measurement": ("fixture interpreter in front of the executable; a protocol test, "
                                   "not a provider measurement") if self.launcher else "host executable",
                   "max_budget_usd": float(self.max_budget_usd), "limits": limits,
                   "environment": environment_report,
                   "uncontrolled_inheritance": list(self.runtime.get("uncontrolled_inheritance", []))}

        deadline = time.monotonic() + float(timeout)
        events, state = [], _StreamState(limits)
        started = time.monotonic()
        try:
            # The boundary exists before the process runs, so a grandchild cannot be created
            # outside it and then be missed when the parent's exit is mistaken for the tree's.
            self.tree = ProcessTree.spawn(argv, cwd=workspace, env=environment,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
        except TreeOwnershipLeak as exc:
            # A process was created and could not be proven gone. It had not run an instruction —
            # it was still suspended — but a pid this run made is unaccounted for, and a retry
            # would put a second one beside it. So this enters rather than refuses: the executor
            # records termination evidence and blocks the task until an operator has looked.
            if on_enter is not None:
                on_enter()
            raise ContractError(
                "Claude Code CLI could not be started and a process it created could not be proven "
                "gone: " + json.dumps(exc.detail, ensure_ascii=False, sort_keys=True)) from exc
        except Exception as exc:
            # The boundary failed with nothing created or nothing left, so this is a refusal that
            # may be retried. That claim is the cleanup's exit status, not an assumption.
            raise ContractError("Claude Code CLI could not be started: " + type(exc).__name__) from exc
        self.process = self.tree.process
        if on_enter is not None:
            # The process exists: from here on its initialization can already change the workspace.
            on_enter()
        process = self.process
        inbox: queue.Queue = queue.Queue(maxsize=limits["queue_events"])
        writer = threading.Thread(target=_write_prompt, args=(process, prompt, state), daemon=True,
                                  name="claude-stdin")
        readers = [threading.Thread(target=_drain, args=(process.stdout, "stdout", inbox, state, limits),
                                    daemon=True, name="claude-stdout"),
                   threading.Thread(target=_drain, args=(process.stderr, "stderr", inbox, state, limits),
                                    daemon=True, name="claude-stderr")]
        writer.start()
        for reader in readers:
            reader.start()

        terminal, conflict, sequence = None, None, 0
        reason, open_readers = None, 2
        try:
            while True:
                if cancel is not None and cancel():
                    reason = "cancelled"
                    break
                if on_tick is not None:
                    on_tick()  # a lease check may raise; the finally block still stops the tree
                if time.monotonic() >= deadline:
                    reason = "deadline"
                    break
                try:
                    item = inbox.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    if open_readers == 0 and process.poll() is not None:
                        reason = reason or "stream_closed"
                        break
                    continue
                if item is None:
                    open_readers -= 1
                    if open_readers == 0 and inbox.empty():
                        reason = reason or "stream_closed"
                        break
                    continue
                for normalized in _normalize(item, sequence):
                    sequence += 1
                    normalized["sequence"] = sequence
                    state.observe(normalized)
                    if len(events) < limits["retained_events"]:
                        events.append(normalized)
                    else:
                        state.dropped_retained += 1
                    if normalized["type"] == "result":
                        if terminal is None:
                            terminal = normalized
                        elif canonical(normalized.get("raw")) != canonical(terminal.get("raw")):
                            conflict = conflict or normalized
                        else:
                            state.redelivered_terminals += 1
                    if on_event is not None:
                        on_event(normalized)
        finally:
            if reason == "stream_closed" and process.poll() is None:
                # Its output ended; give it a moment to end by itself so the receipt can say
                # whether it exited on its own or had to be stopped.
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            termination = self._terminate(reason or "completed")
            # A pipe is closed only once the thread that was reading or writing it has finished.
            # Closing one while a thread is blocked inside it waits for that thread's buffer lock,
            # which is exactly the case an unconfirmed termination leaves behind: the run would
            # hang for as long as the child lives instead of reporting the unknown outcome.
            for thread, pipe in ((writer, process.stdin), (readers[0], process.stdout),
                                 (readers[1], process.stderr)):
                thread.join(timeout=5)
                if thread.is_alive():
                    state.count("pipe_left_open")
                    continue
                try:
                    pipe.close()
                except OSError:
                    pass
        require(termination["confirmed"],
                "Claude process tree termination could not be confirmed; the outcome is unknown")
        result = self._result(events=events, terminal=terminal, conflict=conflict, state=state,
                              termination=termination, command=command, schema=schema,
                              elapsed=time.monotonic() - started, reason=reason, session_id=session_id)
        if self.profile is not None:
            # Read after the tree is confirmed gone, so the count is final. "selected" is what this
            # run passed; "hook_receipts" is what the hook wrote; neither is the other.
            result["worker_profile"] = {
                "selected": profile_delivery,
                "hook_receipts": hook_receipts(evidence_directory, profile_digest(self.profile)),
                "note": "delivery and observation recorded separately; neither certifies compliance"}
        return result

    # ---- termination ----------------------------------------------------------------------------
    def _terminate(self, reason: str) -> dict:
        """End the tree this adapter owns and report the parent and the tree separately.

        A parent that exited proves nothing about what it left behind, so the tree keeps its own
        receipt and acceptance needs both. Nothing here can turn a surviving descendant into a
        finished run, and nothing a kill command reports can withdraw an exit code already in hand.
        """
        if self.tree is None:
            record = {"reason": reason, "parent": {"confirmed": True, "never_started": True},
                      "tree": {"confirmed": True, "method": "never_started"}, "confirmed": True,
                      "boundary": None, "note": "no process was created"}
            self._termination = record
            return record
        record = self.tree.terminate(reason)
        parent = record["parent"]
        flattened = {**record, "exit_code": parent.get("exit_code"),
                     "escalated": bool(parent.get("escalated")),
                     "ended_on_its_own": bool(parent.get("ended_on_its_own"))}
        self._termination = flattened
        return flattened

    # ---- result ---------------------------------------------------------------------------------
    def _result(self, *, events, terminal, conflict, state, termination, command, schema, elapsed,
                reason, session_id) -> dict:
        raw_terminal = terminal.get("raw") if terminal else None
        reported_model = _text(raw_terminal, "model") or state.init_model
        reported_session = _text(raw_terminal, "session_id") or state.init_session
        usage = raw_terminal.get("usage") if isinstance(raw_terminal, dict) else None
        cost = raw_terminal.get("total_cost_usd") if isinstance(raw_terminal, dict) else None
        binding = _session_binding(session_id, state.init_session, reported_session)
        agreement = _model_agreement(self.model, reported_model)
        result = {
            "provider": IDENTITY, "transport": TRANSPORT, "answer": None, "model_answer_text": "",
            "events": events, "thread_id": session_id, "turn_id": None, "usage": usage if isinstance(usage, dict) else None,
            "rotate": False, "interrupted": False, "requested_model": self.model,
            "reported_model": reported_model, "model_agreement": agreement,
            "session": {**binding, "resume": "unsupported",
                        "basis": "a fresh session id for every attempt"},
            "cost": {"reported_usd": cost if type(cost) in (int, float) else None,
                     "source": "provider_estimate" if type(cost) in (int, float) else "unknown",
                     "note": "the provider's own estimate for this run, not a billed amount"},
            "command": command, "process": {**termination, "elapsed_seconds": elapsed, "stop_reason": reason},
            "effective_configuration": {
                # A provider that never sent its startup report tells us nothing about what it
                # loaded. That is recorded as `reported: false` rather than as empty lists, because
                # an absent report and a report of nothing are different facts.
                "reported": False, **state.effective,
                "hook_events_observed": sum(1 for event in events
                                            if str(event.get("subtype") or "").startswith("hook")),
                "requested_controls": {key: command["limits"].get(key) for key in ("deadline_seconds",)},
                "note": ("what the provider reported it loaded at startup, beside the controls this "
                         "run passed; an empty list is the provider's report, not this runner's claim, "
                         "and nothing here is reported when `reported` is false")},
            "stream": state.report(),
            "tool_items": ClaudeStream.tool_items(events),
            "tool_usage_observed": state.tools(),
            "terminal": _terminal_report(terminal, conflict, state),
        }
        failure = _provider_failure(terminal=terminal, conflict=conflict, state=state,
                                    termination=termination, reason=reason, binding=binding,
                                    agreement=agreement)
        if failure:
            result["failure"] = failure
            return result
        text, source = _answer_text(raw_terminal)
        result["answer_source"] = source
        result["model_answer_text"] = text
        # The provider's compliance claim is not the check: the schema runs here, locally.
        validated = completed_output(text, schema, label="claude")
        result["structural"] = validated["structural"]
        if validated.get("failure"):
            if validated["failure"].get("output_reason") == "empty":
                # The terminal result carried no output at all, which is a different observation
                # from an answer that was produced and malformed: the invocation contract names it
                # `tool_only` when tools ran and `empty_answer` when nothing did. Neither is success.
                return result
            result["failure"] = validated["failure"]
            result["output_schema"] = schema
            return result
        result["answer"] = validated["answer"]
        return result


def _write_prompt(process, prompt: str, state: "_StreamState") -> None:
    """Deliver the prompt over stdin. A child that never reads it blocks this thread only."""
    data = prompt.encode("utf-8")
    try:
        process.stdin.write(data)
        process.stdin.flush()
        state.stdin = {"bytes": len(data), "state": "written"}
    except (BrokenPipeError, ValueError, OSError) as exc:
        state.stdin = {"bytes": 0, "state": "failed", "error": type(exc).__name__}
        return
    try:
        process.stdin.close()
    except (BrokenPipeError, OSError):
        state.stdin["state"] = "written_close_failed"


def _drain(pipe, name: str, inbox: queue.Queue, state: "_StreamState", limits: dict) -> None:
    """Read one pipe to the end, bounded. Reading never stops before EOF, so the child never
    blocks on a full pipe even after this adapter has stopped keeping what it reads."""
    limit = limits["line_bytes"]
    try:
        while True:
            chunk = pipe.readline(limit + 1)
            if not chunk:
                break
            oversized = len(chunk) > limit and not chunk.endswith(b"\n")
            if oversized:
                skipped = len(chunk)
                while True:
                    more = pipe.readline(limit + 1)
                    skipped += len(more)
                    if not more or more.endswith(b"\n"):
                        break
                state.count("oversized_line")
                state.add_bytes(name, skipped)
                _offer(inbox, {"stream": name, "defect": f"line exceeded {limit} bytes", "bytes": skipped}, state)
                continue
            state.add_bytes(name, len(chunk))
            if state.bytes_total > limits["stream_bytes"]:
                state.truncated = True
                continue
            _offer(inbox, {"stream": name, "line": chunk}, state)
    except (OSError, ValueError) as exc:
        state.reader_errors.append({"stream": name, "error": type(exc).__name__})
    finally:
        try:
            inbox.put_nowait(None)
        except queue.Full:
            state.count("queue_full")


def _offer(inbox: queue.Queue, item: dict, state: "_StreamState") -> None:
    try:
        inbox.put_nowait(item)
    except queue.Full:
        state.count("queue_full")


class _StreamState:
    def __init__(self, limits: dict):
        self.limits = limits
        self.bytes_by_stream = {"stdout": 0, "stderr": 0}
        self.bytes_total = 0
        self.counts: dict = {}
        self.truncated = False
        self.reader_errors: list = []
        self.stdin: dict = {"bytes": 0, "state": "pending"}
        self.dropped_retained = 0
        self.redelivered_terminals = 0
        self.init_model = None
        self.init_session = None
        self.effective: dict = {}
        self.permission_denials: list = []
        self.started_tools: list = []
        self.completed_tools: list = []
        self.failed_tools: list = []
        self.stderr_tail: list = []
        self.stderr_bytes = 0
        self.malformed = 0
        self.saw_any_line = False

    def add_bytes(self, name: str, count: int) -> None:
        self.bytes_by_stream[name] = self.bytes_by_stream.get(name, 0) + count
        self.bytes_total += count

    def count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1

    def observe(self, event: dict) -> None:
        self.saw_any_line = True
        kind = event.get("type")
        if kind == "malformed":
            self.malformed += 1
        elif kind == "session_started":
            self.init_session = event.get("id")
            raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
            self.init_model = _text(raw, "model")
            # What the provider says it actually loaded. Inherited hooks, MCP servers and plugins
            # change what a run does, so the controls that are supposed to exclude them are checked
            # against the provider's own report rather than assumed to have worked.
            self.effective = {
                "reported": True,
                "model": _text(raw, "model"), "permission_mode": _text(raw, "permissionMode"),
                "api_key_source": _text(raw, "apiKeySource"),
                "output_style": _text(raw, "output_style"),
                "tools": [str(name)[:60] for name in (raw.get("tools") or [])][:60],
                "mcp_servers": [str(entry)[:120] for entry in (raw.get("mcp_servers") or [])][:20],
                "mcp_server_errors": len(raw.get("mcp_server_errors") or []),
                "plugins": [str(entry)[:120] for entry in (raw.get("plugins") or [])][:20],
                "plugin_errors": len(raw.get("plugin_errors") or []),
                "slash_commands": len(raw.get("slash_commands") or []),
                "agents": len(raw.get("agents") or []),
                "capabilities": [str(name)[:60] for name in (raw.get("capabilities") or [])][:20],
                "keys_reported": sorted(str(key)[:40] for key in raw)[:40]}
        elif kind == "tool_started" and event.get("id"):
            self.started_tools.append(event["id"])
        elif kind == "tool_completed" and event.get("id"):
            self.completed_tools.append(event["id"])
            if event.get("status") == "failed":
                self.failed_tools.append(event["id"])
        elif kind == "permission_denied":
            self.permission_denials.append({"id": event.get("id"), "status": event.get("status")})
        if event.get("stream") == "stderr":
            self.stderr_bytes += len(str(event.get("text", "")).encode("utf-8"))
            if len(self.stderr_tail) < 20:
                # Diagnostic text from a foreign process: credential shapes are removed and the
                # tail stays inside the access-controlled evidence artifact. What travels outward
                # with a failure is the digest, never the text (INV-OBSERVATION-001).
                self.stderr_tail.append(redact_text(str(event.get("text", ""))[:200])[0])

    def tools(self) -> dict:
        return {"started": list(self.started_tools), "completed": list(self.completed_tools),
                "failed": list(self.failed_tools),
                "source": "provider stream lines observed by this runner; a summary in the answer certifies nothing"}

    def report(self) -> dict:
        return {"bytes": dict(self.bytes_by_stream), "bytes_total": self.bytes_total,
                "truncated": self.truncated, "counts": dict(self.counts),
                "reader_errors": list(self.reader_errors), "stdin": dict(self.stdin),
                "malformed_lines": self.malformed, "dropped_retained_events": self.dropped_retained,
                "redelivered_terminals": self.redelivered_terminals,
                "permission_denials": list(self.permission_denials),
                "effective_configuration": dict(self.effective),
                "stderr_tail": list(self.stderr_tail), "stderr_bytes": self.stderr_bytes,
                "stderr_digest": digest(self.stderr_tail), "limits": dict(self.limits)}


def _constant(_value):
    raise ValueError("Non-JSON constant")


def _object(pairs):
    body = {}
    for key, value in pairs:
        if key in body:
            raise ValueError("Duplicate property")
        body[key] = value
    return body


def _text(body, key):
    value = body.get(key) if isinstance(body, dict) else None
    return value if type(value) is str and value else None


def _normalize(item: dict, sequence: int) -> list:
    """One raw stream item becomes one or more normalized events; the raw line is always kept."""
    stream = item.get("stream", "stdout")
    if "defect" in item:
        return [{"provider": IDENTITY, "stream": stream, "raw_type": "oversized", "subtype": None,
                 "type": "malformed", "id": None, "status": None, "defect": item["defect"],
                 "raw": None, "bytes": item.get("bytes")}]
    line = item.get("line", b"")
    text = line.decode("utf-8", "replace").rstrip("\r\n")
    if stream == "stderr":
        return [{"provider": IDENTITY, "stream": "stderr", "raw_type": "stderr", "subtype": None,
                 "type": "diagnostic", "id": None, "status": None, "text": text[:2000], "raw": None}]
    if not text.strip():
        return []
    try:
        body = json.loads(text, parse_constant=_constant, object_pairs_hook=_object)
    except (ValueError, RecursionError) as exc:
        return [{"provider": IDENTITY, "stream": stream, "raw_type": "non_json", "subtype": None,
                 "type": "malformed", "id": None, "status": None,
                 "defect": type(exc).__name__, "raw": None, "text": text[:500]}]
    if not isinstance(body, dict):
        return [{"provider": IDENTITY, "stream": stream, "raw_type": "non_object", "subtype": None,
                 "type": "malformed", "id": None, "status": None, "defect": "line is not an object",
                 "raw": None}]
    raw_type = _text(body, "type") or "untyped"
    subtype = _text(body, "subtype")
    base = {"provider": IDENTITY, "stream": stream, "raw_type": raw_type, "subtype": subtype,
            "raw": body}
    if raw_type == "system" and subtype == "init":
        return [{**base, "type": "session_started", "id": _text(body, "session_id"), "status": "started"}]
    if raw_type == "system" and subtype == "permission_denied":
        return [{**base, "type": "permission_denied",
                 "id": _text(body, "uuid") or _text(body, "tool_name"), "status": "denied"}]
    if raw_type == "system":
        return [{**base, "type": "system", "id": _text(body, "uuid"), "status": subtype}]
    if raw_type == "result":
        return [{**base, "type": "result", "id": _text(body, "session_id"), "status": subtype or "unknown"}]
    if raw_type in ("assistant", "user"):
        return _normalize_message(base, body, raw_type)
    return [{**base, "type": "unknown", "id": _text(body, "uuid"), "status": None}]


def _normalize_message(base: dict, body: dict, raw_type: str) -> list:
    message = body.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    produced = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = _text(block, "type")
            if kind == "tool_use" and raw_type == "assistant":
                produced.append({**base, "type": "tool_started", "id": _text(block, "id"),
                                 "status": "started", "tool": _text(block, "name"), "raw": None})
            elif kind == "tool_result" and raw_type == "user":
                produced.append({**base, "type": "tool_completed", "id": _text(block, "tool_use_id"),
                                 "status": "failed" if block.get("is_error") else "completed", "raw": None})
    if raw_type == "assistant" and not produced:
        produced.append({**base, "type": "message", "id": _text(message, "id") if isinstance(message, dict) else None,
                         "status": "emitted"})
    if not produced:
        produced.append({**base, "type": "unknown", "id": None, "status": None})
    produced[0]["raw"] = body
    return produced


def _terminal_report(terminal, conflict, state: _StreamState) -> dict:
    raw = terminal.get("raw") if terminal else None
    return {"present": terminal is not None, "subtype": _text(raw, "subtype"),
            "is_error": bool(raw.get("is_error")) if isinstance(raw, dict) else None,
            "num_turns": raw.get("num_turns") if isinstance(raw, dict) else None,
            "duration_ms": raw.get("duration_ms") if isinstance(raw, dict) else None,
            "conflicting": conflict is not None,
            "conflicting_subtype": _text(conflict.get("raw"), "subtype") if conflict else None,
            "redelivered": state.redelivered_terminals,
            "permission_denials": raw.get("permission_denials") if isinstance(raw, dict) else None,
            "basis": "the first result message is terminal; an identical repeat is a redelivery"}


def _answer_text(raw_terminal) -> tuple[str, str]:
    """Prefer the provider's structured output, fall back to its final text; say which was used."""
    structured = raw_terminal.get("structured_output") if isinstance(raw_terminal, dict) else None
    if isinstance(structured, (dict, list)):
        return canonical(structured), "structured_output"
    text = raw_terminal.get("result") if isinstance(raw_terminal, dict) else None
    return (text if type(text) is str else ""), "result_text"


def _session_binding(requested: str, init_session, terminal_session) -> dict:
    """Which session the answer belongs to.

    An identifier nobody reported is unknown, and unknown is not a match: an answer that cannot be
    tied to the session this attempt opened may belong to another execution entirely.
    """
    reported = {name: value for name, value in
                (("init", init_session), ("terminal", terminal_session)) if value is not None}
    distinct = set(reported.values())
    if not reported:
        state = "unreported"
    elif len(distinct) > 1:
        state = "conflicting"
    elif distinct == {requested}:
        state = "match"
    else:
        state = "mismatch"
    return {"requested": requested, "reported": reported or None, "state": state,
            "match": state == "match",
            "basis": "the provider's own session identifiers, compared with the one this attempt opened"}


def _model_agreement(requested: str, reported) -> dict:
    """Whether the model that answered is the one asked for, or whether that cannot be decided.

    An alias names a family, so a concrete answer to an alias has not disagreed with anything and
    this harness does not pretend to have checked it. An exact name that comes back different has.
    """
    if reported is None:
        state = "unreported"
    elif reported == requested:
        state = "match"
    elif requested in MODEL_ALIASES:
        state = "alias_not_decidable"
    else:
        state = "mismatch"
    return {"requested": requested, "reported": reported, "state": state,
            "decided_here": state in {"match", "mismatch"},
            "basis": "the model this attempt asked for, beside the one the provider reported"}


def _process_conflict(termination, reason) -> str | None:
    """Why this run's ending contradicts a successful result, or None when it does not.

    A terminal message says what the provider meant to report. How the process ended says what
    actually happened. A success that arrived before a non-zero exit, or before this runner had to
    stop the process, is not a clean run, and the earlier message does not settle the later fact.
    """
    parent = termination.get("parent") or {}
    if reason in {"deadline", "cancelled"}:
        return f"the run was stopped ({reason}); a result that arrived first does not make it clean"
    if not parent.get("ended_on_its_own"):
        return "the provider had to be terminated rather than ending on its own"
    code = parent.get("exit_code")
    if code not in (0, None):
        return f"the provider reported success and then exited with code {code}"
    return None


def _provider_failure(*, terminal, conflict, state: _StreamState, termination, reason,
                      binding=None, agreement=None) -> dict | None:
    """Name what the provider did wrong, before any answer is read out of it."""
    # A failure travels outward (task row, notice, diagnosis request). Foreign diagnostic text
    # never goes with it: the digest and the byte count identify the same stderr in the artifact.
    lost = _lost_output(state)
    shared = {"kind": "provider", "owner": "provider", "stop_reason": reason,
              "exit_code": termination.get("exit_code"), "stderr_digest": digest(state.stderr_tail),
              "stderr_bytes": state.stderr_bytes,
              # Carried on every failure, not only the one it causes: a run that ended at its
              # deadline *and* lost output should not read as a clean timeout.
              "lost_output": lost}
    if conflict is not None:
        return {**shared, "cause": "claude-provider-conflicting-terminal",
                "detail": "two different result messages arrived for one run"}
    if terminal is None:
        if reason == "deadline":
            return {**shared, "cause": "claude-provider-timeout",
                    "detail": "the execution budget elapsed before a terminal result"}
        if reason == "cancelled":
            return {**shared, "cause": "claude-provider-cancelled", "detail": "the run was cancelled"}
        if lost:
            return {**shared, "cause": "claude-provider-stream-truncated", "detail": lost}
        if not state.saw_any_line:
            return {**shared, "cause": "claude-provider-startup-failed",
                    "detail": "the process produced no stream line"}
        return {**shared, "cause": "claude-provider-missing-terminal",
                "detail": "the stream ended without a result message"}
    raw = terminal.get("raw") or {}
    subtype = _text(raw, "subtype") or "unknown"
    text = raw.get("result") if type(raw.get("result")) is str else ""
    if raw.get("is_error") or subtype != "success":
        if "budget" in subtype.lower() or "Budget limit reached" in text:
            cause = "claude-provider-budget-exhausted"
        elif subtype == "error_max_turns":
            cause = "claude-provider-max-turns"
        else:
            cause = "claude-provider-error-result"
        return {**shared, "cause": cause, "result_subtype": subtype,
                "detail": "the provider reported an unsuccessful result"}
    if binding is not None and not binding["match"]:
        # The answer cannot be tied to the session this attempt opened, so it is not this
        # attempt's answer whatever it says.
        return {**shared, "cause": "claude-provider-session-" + binding["state"],
                "session": binding,
                "detail": "the result does not belong to the session this attempt opened"}
    if agreement is not None and agreement["state"] == "mismatch":
        return {**shared, "cause": "claude-provider-model-mismatch", "model": agreement,
                "detail": "the provider reported a different model than the one this attempt asked for"}
    ending = _process_conflict(termination, reason)
    if ending:
        return {**shared, "cause": "claude-provider-exit-conflict", "detail": ending}
    if lost:
        return {**shared, "cause": "claude-provider-stream-truncated", "detail": lost}
    return None


def _lost_output(state: _StreamState) -> str | None:
    """Whether provider output went unread, and why. Three different accidents, one consequence:
    the record of what the provider did is incomplete, so this run is not something to accept."""
    if state.truncated:
        return "the output limit was reached; the retained stream is incomplete"
    if state.counts.get("queue_full"):
        return "the event queue overflowed; lines were read but never examined"
    failed = [error["stream"] for error in state.reader_errors if error.get("stream") == "stdout"]
    if failed:
        return "the stdout reader failed before the stream ended"
    return None
