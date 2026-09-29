"""Noninteractive Codex transport (`codex exec`): prompts over stdin, never a shell string.

Layer: adapters
Context: execution
Owns: CodexRuntime (M7 `adapters/codex.py`, moved; `resolve_codex` already lives with the App Server
    client since S3)
Does not own: process creation (the injected host_os `ProcessRunner`, the one spawn chokepoint), schema
    preflight (execution.adapters.output_schema), who uses it (the canary probe S8, the CLI S10)
Entry points: CodexRuntime, CodexRuntime.probe, CodexRuntime.run
Contracts: INV-INVOCATION-001

Target change of shape only: the child is run through `runner` (host_os ProcessRunner, composition passes
`host_os.adapters.process_groups.run_process`) instead of a module-level import, with the same argv, stdin,
timeout and results. The schema is preflighted before any process and the answer is validated against it
after (RESEARCH-S4 R5/R6: the provider's own schema handling is not trusted alone; CE-9).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from codex_harness.execution.adapters.output_schema import preflight
from codex_harness.execution.adapters.providers.codex_app_server import resolve_codex
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical


class CodexRuntime:
    """Noninteractive Codex transport. Prompts travel over stdin, never a shell string."""

    def __init__(self, executable: str | None = None, *, runner):
        self.executable = executable or resolve_codex()
        self.runner = runner
        if not self.executable:
            raise ContractError("Codex CLI not installed")

    def probe(self) -> dict:
        result = self.runner([self.executable, "--version"], timeout=20)
        return {"passed": result.returncode == 0, "version": result.stdout.strip(),
                "exit_code": result.returncode}

    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 120) -> dict:
        preflight(schema)
        with tempfile.TemporaryDirectory(prefix="codex-harness-") as tmp:
            schema_path = Path(tmp) / "response.schema.json"
            output = Path(tmp) / "response.json"
            schema_path.write_text(canonical(schema), encoding="utf-8")
            argv = [self.executable, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
                    "--color", "never", "--output-schema", str(schema_path),
                    "--output-last-message", str(output), "-C", str(Path(cwd).resolve()), "-"]
            try:
                result = self.runner(argv, input_text=prompt, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise ContractError("Codex invocation timed out") from exc
            if result.returncode != 0 or not output.exists():
                raise ContractError(f"Codex execution failed (exit={result.returncode}): "
                                    + result.stderr[-1000:])
            from jsonschema import validate

            answer = json.loads(output.read_text(encoding="utf-8"))
            validate(answer, schema)
            return {"answer": answer, "events": [json.loads(line) for line in result.stdout.splitlines()
                                                   if line.startswith("{")]}
