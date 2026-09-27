"""Host ports of the named worker credentials (INV-WORKER-CREDENTIALS-001).

* `read_secret(reference)`: the private secret a configuration REFERENCES, read only when a worker environment
  is being built. The file must be a regular non-symlink file owned by this uid with no group/other access,
  under the private secret root; the value is returned to the caller and never logged or recorded.
* `ClaudeUsageTelemetry`: ONE fresh provider usage observation through the supported, installed Claude Code
  command `claude -p /usage` (no model request: tools disabled, no session persistence, no setting sources),
  run in a NEW private config directory holding ONLY a copy of the alias's bound LOGIN credential (no caches,
  no settings, no token variable in its environment), with the CLI version pinned. It parses the versioned
  all-model weekly line and the session line of the pinned renderer; anything else (another version, no
  windows - a static token reports none -, a model call, an error, a timeout, a malformed line) is a named
  `unknown` observation, never an assumed zero. The temporary directory and its credential copy are removed.
* `write_selected_env(path, token)`: the one-variable EnvironmentFile a reviewed managed-unit drop-in reads for
  the NEXT managed generation (0600, atomic, never printed).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from codex_harness.domain.model import utcnow
from codex_harness.domain.worker_credentials import (
    OBSERVATION_SCHEMA,
    SECRET_ROOT,
    TOKEN_NAME,
    CredentialRefused,
    secret_path,
)

MAX_SECRET_BYTES = 16384
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9._~+/=-]{20,4096}$")
USAGE_ARGV = ("-p", "/usage", "--tools", "", "--no-session-persistence", "--output-format", "json",
              "--setting-sources", "")
# The pinned non-interactive renderer (installed 2.1.280): `<title>: <floor(utilization)>% used[ · resets <display>]`.
LINE = re.compile(r"^(?P<title>Current session|Current week \(all models\)): (?P<used>\d{1,3})% used"
                  r"(?: · resets (?P<resets>[^\n]{1,64}))?$")
ENV_ALLOWED = ("PATH", "LANG", "LC_ALL", "TZ")


def _private_file(path: str) -> Path:
    if not secret_path(path):
        raise CredentialRefused("secret_path_invalid", "path")
    target = Path(path)
    try:
        info = os.lstat(target)
    except OSError as exc:
        raise CredentialRefused("secret_unavailable", "path") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CredentialRefused("secret_not_regular", "path")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CredentialRefused("secret_not_private", "path")
    if info.st_size == 0:
        raise CredentialRefused("secret_empty", "path")
    if info.st_size > MAX_SECRET_BYTES:
        raise CredentialRefused("secret_oversized", "path")
    parent = os.lstat(target.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077 or not str(target.parent).startswith(SECRET_ROOT):
        raise CredentialRefused("secret_directory_not_private", "path")
    return target


def read_secret(reference: dict) -> str:
    """The referenced token value; refuses anything but a private, well-shaped single token."""
    target = _private_file(reference.get("path"))
    text = target.read_text("utf-8")
    if reference.get("kind") == "env_file_key":
        values = [line.split("=", 1)[1].strip() for line in text.splitlines()
                  if line.strip() and not line.lstrip().startswith("#") and line.split("=", 1)[0].strip() == reference["key"]]
        if len(values) != 1:
            raise CredentialRefused("secret_key_not_exactly_one", "key")
        value = values[0].strip("'\"")
    elif reference.get("kind") == "token_file":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 1:
            raise CredentialRefused("secret_not_single_token", "path")
        value = lines[0]
    else:
        raise CredentialRefused("secret_kind_unknown", "kind")
    if not TOKEN_SHAPE.fullmatch(value):
        raise CredentialRefused("secret_shape_invalid", "path")
    return value


def parse_usage(text) -> dict | None:
    """The session and all-model weekly windows of the pinned renderer, or None when either is absent."""
    if not isinstance(text, str):
        return None
    windows = {}
    for line in text.splitlines():
        match = LINE.fullmatch(line.strip())
        if match is None:
            continue
        key = "five_hour" if match.group("title") == "Current session" else "weekly"
        used = int(match.group("used"))
        if key in windows or used > 100:
            return None   # a duplicated or impossible window is ambiguity, never a reading
        windows[key] = {"used_percent": used, "resets_at": match.group("resets")}
    return windows if set(windows) == {"weekly", "five_hour"} else None


class ClaudeUsageTelemetry:
    """One fresh, cache-free `/usage` observation of the alias's bound login (see the module docstring)."""

    def __init__(self, claude: str = "claude", *, runner=subprocess.run, timeout: int = 60, clock=utcnow,
                 scratch: str | None = None):
        self.claude, self.runner, self.timeout, self.clock, self.scratch = claude, runner, timeout, clock, scratch

    def __call__(self, row: dict) -> dict:
        telemetry = row["telemetry"]
        base = {"schema": OBSERVATION_SCHEMA, "alias": row["alias"], "generation": row["generation"],
                "source": {"kind": telemetry["kind"], "cli_version": None, "isolated_config": True,
                           "cache_free": True}, "observed_at": self.clock()}

        def unknown(code: str) -> dict:
            return {**base, "status": "unknown", "reason_code": code, "weekly": None, "five_hour": None}
        env = {k: v for k, v in os.environ.items() if k in ENV_ALLOWED}
        try:
            version = self.runner([self.claude, "--version"], capture_output=True, text=True, timeout=self.timeout,
                                  env=env)
        except (OSError, subprocess.SubprocessError):
            return unknown("cli_unavailable")
        found = re.match(r"^(\d+\.\d+\.\d+)", (version.stdout or "").strip())
        base["source"]["cli_version"] = found.group(1) if found else "unknown"
        if version.returncode != 0 or found is None or found.group(1) != telemetry["cli_version"]:
            return unknown("cli_version_mismatch")
        try:
            login = _private_file(telemetry["login_credentials_path"])
        except CredentialRefused as exc:
            return unknown("login_" + exc.reason_code)
        directory = Path(tempfile.mkdtemp(prefix="zeus-usage-", dir=self.scratch))
        try:
            os.chmod(directory, 0o700)
            copy = directory / ".credentials.json"
            shutil.copyfile(login, copy)
            os.chmod(copy, 0o600)
            child = {**env, "HOME": str(directory), "CLAUDE_CONFIG_DIR": str(directory)}
            try:
                done = self.runner([self.claude, *USAGE_ARGV], capture_output=True, text=True, timeout=self.timeout,
                                   env=child, cwd=str(directory))
            except subprocess.TimeoutExpired:
                return unknown("usage_timeout")
            except (OSError, subprocess.SubprocessError):
                return unknown("usage_unavailable")
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        if done.returncode != 0:
            return unknown("usage_exit_nonzero")
        try:
            result = json.loads(done.stdout or "")
        except ValueError:
            return unknown("usage_output_malformed")
        if not isinstance(result, dict) or result.get("is_error") or result.get("subtype") != "success":
            return unknown("usage_error_result")
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        if any(int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens")):
            return unknown("model_call_detected")
        windows = parse_usage(result.get("result"))
        if windows is None:
            return unknown("usage_windows_missing")
        return {**base, "status": "known", "reason_code": None, **windows}


def write_selected_env(path: str, token: str) -> None:
    """Atomically write the one-variable EnvironmentFile of the selected credential (0600, private dir)."""
    if not secret_path(path):
        raise CredentialRefused("selected_env_path_invalid", "path")
    if not TOKEN_SHAPE.fullmatch(token or ""):
        raise CredentialRefused("secret_shape_invalid", "token")
    target = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".selected-", dir=str(target.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(TOKEN_NAME + "=" + token + "\n")
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


CONFIG_SETTING = "ZEUS_WORKER_CREDENTIALS"


def configured_credentials(store, host: dict, *, clock=utcnow):
    """The admission use case for the host's named credentials, or None when the setting is absent (the exact
    previous one-token behaviour). A PRESENT but unreadable or invalid configuration refuses: it never falls
    back silently to the inherited token."""
    value = (host or {}).get(CONFIG_SETTING)
    if not (isinstance(value, str) and value.strip()):
        return None
    from codex_harness.adapters.claude_cli import resolve_claude
    from codex_harness.application.worker_credentials import WorkerCredentials
    telemetry = ClaudeUsageTelemetry(resolve_claude() or "claude", clock=clock)
    return WorkerCredentials(store, load_config(value.strip()), clock=clock, telemetry=telemetry, secrets=read_secret)


def load_config(path: str) -> dict:
    """The versioned configuration document (references only; no secret value)."""
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise CredentialRefused("credentials_config_unreadable", "path") from exc


__all__ = ["CONFIG_SETTING", "ClaudeUsageTelemetry", "configured_credentials", "load_config", "parse_usage", "read_secret", "write_selected_env"]
