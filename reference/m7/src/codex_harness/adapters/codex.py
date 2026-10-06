from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.output_schema import preflight
from codex_harness.domain.model import ContractError, canonical


def resolve_codex() -> str | None:
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    if executable and executable.lower().endswith(".cmd"):
        package = Path(executable).parent / "node_modules/@openai/codex/node_modules/@openai"
        candidates = sorted(package.glob("codex-win32-*/vendor/*/bin/codex.exe"))
        if len(candidates) == 1:
            return str(candidates[0])
    return executable


class CodexRuntime:
    """Noninteractive Codex transport. Prompts travel over stdin, never a shell string."""

    def __init__(self, executable: str | None = None):
        self.executable = executable or resolve_codex()
        if not self.executable:
            raise ContractError("Codex CLI not installed")

    def probe(self) -> dict:
        result = run_process([self.executable, "--version"], timeout=20)
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
                result = run_process(argv, input_text=prompt, timeout=timeout)
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
