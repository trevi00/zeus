"""Target driver: the safe per-entry characterization matrix on the target tree (REBUILD-DESIGN-v2 §5.2a, F3; S10 E5b).

Scenario family `entries.safe_matrix`. The reference driver's 31 rows, run as children of the target venv
under the same R-P child environment, timeout and masks. The kept shims (`import_rules.SHIMS`) and the
console scripts run M7's argv unchanged; a module that is not kept at its M7 path runs under its target
dotted path (`ARGV_MAP`, DESIGN-s10 section 16 (b)), a declared argv difference in the scenario. The
deploy script and `aibox_data` run from the target tree and the `metadata` rows run from the target
checkout root, which holds the profile resources.

Never done here (the "never" column, unchanged from the reference): running a CLI handler, `--once`, a
live monitor `collect`/`web`, a valid isolated-worker request through `-m`, any
subcommand of the delivery/migration modules, `service_entry`/`monitor_frontend_checks` `main()`,
`zeus_aibox_service` `render`/`launch`/`journal`, and any `aibox_data` transfer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("target")

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import codex_harness  # noqa: E402,F401  (R-O: the origin check counts at least one product module)
import masks  # noqa: E402
import provider_guard  # noqa: E402

TARGET = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]).resolve().parent
# Row key -> (M7 module, target module). S10 E5b (DESIGN-s10 section 16 (b), owner 2026-10-04): the M7 module is
# not kept at its M7 path (REBUILD-DESIGN-v2 section 3.5, S0's pinned-argv scan); its target entry is the second.
# Owner int44 (DESIGN-s10 section 16b): artifact_reader, host_migration and migrations are KEPT by the corrected S0
# scan (static.source.json keep_shim true), so their rows run M7's argv against the shims and are not mapped.
ARGV_MAP = {
    "module.adapters.experience --help": ("codex_harness.adapters.experience",
                                          "codex_harness.entry.processes.experience"),  # E5a
    "module.adapters.observed_assets --help": ("codex_harness.adapters.observed_assets",
                                               "codex_harness.entry.cli.observed_assets"),
    # import-only row: DESIGN-s10 section 16 int38 note (isolated_worker); service_entry is a kept shim (S11 SH-1)
    "import_only.codex_harness.adapters.isolated_worker": ("codex_harness.adapters.isolated_worker",
                                                           "codex_harness.entry.processes.isolated_worker_runs"),
}


def target_module(key: str, m7: str) -> str:
    mapped = ARGV_MAP.get(key)
    assert mapped is None or mapped[0] == m7, key
    return m7 if mapped is None else mapped[1]

BIN = Path(sys.executable).parent
PY = str(Path(sys.executable))
TIMEOUT = 60
IMPORT_ONLY = "import importlib, sys; importlib.import_module(sys.argv[1]); print('imported')"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


TRACEBACK = "Traceback (most recent call last):"


def collapse_traceback(text: str) -> str:
    """A Python traceback's frames name the interpreter's own files and line numbers, which differ by version and install
    path (int61 CI 37401999157: CPython 3.12.14 on the runner vs 3.13.15 on aibox), so only its exception line is an
    observable of the entry. No row that compares equal carries a traceback (it would already differ across versions);
    the one target row that does is the declared U6(b) retirement (owner, S11 unit P)."""
    if TRACEBACK not in text:
        return text
    return "<traceback>\n" + text.rstrip("\n").splitlines()[-1] + "\n"


class Runner:
    def __init__(self, work: Path):
        self.work = work
        self.env = provider_guard.child_environment(work / "child")
        self.masker = masks.Masker("entries.safe_matrix", roots={
            "SOURCE": str(TARGET), "VENV": str(Path(sys.prefix).resolve()), "WORK": str(work),
            "PREFIX": sys.prefix})

    def text(self, raw: bytes) -> str:
        return self.masker.apply(raw.decode("utf-8", "replace"))

    def run(self, argv, *, stdin=b"", cwd=None, keep_stdout=True, parse_json=False):
        proc = subprocess.run(argv, input=stdin, capture_output=True, timeout=TIMEOUT,
                              cwd=str(cwd or self.work), env=self.env)
        row = {"argv": [self.masker.apply(a) for a in
                        ([Path(argv[0]).name] if argv[0].startswith(str(BIN)) or argv[0] == PY
                         else argv[:1]) + list(argv[1:])],
               "exit": proc.returncode,
               "stdout_sha256": sha(self.text(proc.stdout).encode()),
               "stdout_bytes": len(proc.stdout),
               "stderr_sha256": sha(collapse_traceback(self.text(proc.stderr)).encode()),
               "stderr_last_line": self.text(proc.stderr).strip().splitlines()[-1:]}
        if keep_stdout:
            row["stdout"] = self.text(proc.stdout)
        if parse_json:
            lines = [json.loads(line) for line in proc.stdout.decode().splitlines() if line.strip()]
            row["json"] = self.masker.apply(lines)
        return row


def hook_rows(r: Runner) -> dict:
    module = [PY, "-m", "codex_harness.resources.worker_profile_hook"]
    out = {"no_arguments": r.run(module)}
    events = {
        "allowed_bash": {"hook_event_name": "PostToolUse", "session_id": "s0-session",
                         "tool_name": "Bash", "tool_use_id": "tu-1",
                         "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}},
        "denied_write_1": {"hook_event_name": "PostToolUseFailure", "session_id": "s0-session",
                           "tool_name": "Write", "tool_use_id": "tu-2",
                           "tool_input": {"file_path": "/denied/a.txt"},
                           "error": "Permission denied: /denied/a.txt"},
        "denied_write_2": {"hook_event_name": "PostToolUseFailure", "session_id": "s0-session",
                           "tool_name": "Write", "tool_use_id": "tu-3",
                           "tool_input": {"file_path": "/denied/b.txt"},
                           "error": "Permission denied: /denied/b.txt"},
        "malformed_json": None,
    }
    directory = r.work / "hook-receipts"
    for name, event in events.items():
        before = set(directory.glob("*.json")) if directory.exists() else set()
        stdin = b"{not json" if event is None else json.dumps(event).encode()
        row = r.run([*module, "--directory", str(directory), "--profile-digest", "d" * 64],
                    stdin=stdin)
        new = sorted(set(directory.glob("*.json")) - before)
        receipts = []
        for path in new:
            body = json.loads(path.read_text(encoding="utf-8"))
            receipts.append({"receipt_name": path.name, **body})
        row["receipts"] = r.masker.apply(receipts)
        out[name] = row
    out["session_state_files"] = sorted(p.name for p in directory.iterdir()
                                        if not p.name.endswith(".json"))
    return out


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zeus-s0-entries-") as raw:
        work = Path(raw)
        r = Runner(work)
        rows = {}
        rows["console.zeus --help"] = r.run([str(BIN / "zeus"), "--help"])
        rows["console.zeus --version"] = r.run([str(BIN / "zeus"), "--version"])
        rows["console.harness --help"] = r.run([str(BIN / "harness"), "--help"])
        rows["module.zeus ticket --help"] = r.run([PY, "-m", "zeus", "ticket", "--help"])
        rows["console.zeus-supervisor --help"] = r.run([str(BIN / "zeus-supervisor"), "--help"])
        rows["console.harness-supervisor --help"] = r.run([str(BIN / "harness-supervisor"), "--help"])
        rows["console.zeus-monitor --help"] = r.run([str(BIN / "zeus-monitor"), "--help"])
        rows["module.codex_harness.monitor --help"] = r.run([PY, "-m", "codex_harness.monitor", "--help"])
        meta = [PY, "-m", "codex_harness.adapters.worker_profile_metadata"]
        rows["metadata.no_arguments_from_checkout_root"] = r.run(meta, cwd=TARGET, parse_json=True)
        rows["metadata.--help"] = r.run([*meta, "--help"], cwd=TARGET)
        rows["metadata.extra_argument"] = r.run([*meta, "extra"], cwd=TARGET)
        entry = [PY, "-m", "codex_harness.adapters.isolated_worker_entry"]
        rows["isolated_worker_entry.empty_stdin"] = r.run(entry, parse_json=True)
        rows["isolated_worker_entry.malformed_stdin"] = r.run(entry, stdin=b"{", parse_json=True)
        rows["isolated_worker_entry.wrong_protocol"] = r.run(
            entry, stdin=b'{"protocol": "not-a-protocol"}', parse_json=True)
        rows["worker_profile_hook"] = hook_rows(r)
        for module in ("codex_harness.container_main", "codex_harness.adapters.isolated_worker",
                       "codex_harness.adapters.isolated_worker_entry",
                       "codex_harness.adapters.service_entry",
                       "codex_harness.adapters.monitor_frontend_checks"):
            key = "import_only." + module
            rows[key] = r.run([PY, "-c", IMPORT_ONLY, target_module(key, module)])
        artifacts = work / "fixture-artifacts"
        artifacts.mkdir()
        body = json.dumps({"fixture": True, "items": [1, 2, 3]}, sort_keys=True).encode()
        (artifacts / (sha(body) + ".txt")).write_bytes(body)
        reader = [PY, "-m", target_module("artifact_reader --help", "codex_harness.adapters.artifact_reader")]
        rows["artifact_reader --help"] = r.run([*reader, "--help"])
        rows["artifact_reader.index_fixture"] = r.run(
            [*reader, "--root", str(artifacts), "--ref", "sha256:" + sha(body), "index"],
            parse_json=True)
        for module in ("continuation_process", "managed_runtime", "host_delivery", "host_migration",
                       "migrations", "observed_assets", "experience"):
            key = f"module.adapters.{module} --help"
            rows[key] = r.run([PY, "-m", target_module(key, "codex_harness.adapters." + module), "--help"])
        rows["deploy.zeus_aibox_service --help"] = r.run(
            [PY, str(TARGET / "deploy/aibox/zeus_aibox_service.py"), "--help"], cwd=TARGET)
        rows["scripts.aibox_data --help"] = r.run([PY, str(TARGET / "scripts/aibox_data"), "--help"],
                                                  cwd=TARGET)
        result = {"rows": rows, "timeout_seconds": TIMEOUT,
                  "render_policy": "zeus_aibox_service render not run: purity not established in S0"}
    driver.finish("target", "entries.safe_matrix", result)


if __name__ == "__main__":
    main()
