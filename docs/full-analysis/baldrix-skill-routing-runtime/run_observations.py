"""Capture actual component observations separately from upstream test results."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

from run_upstream import ROOT, SOURCE, tree_hashes

OUT = Path(__file__).resolve().parent
IMAGE = "sha256:39d4f226fa8b1ae6087b283b16d0176e9181f8aaf31dcbf0c9145e513453725a"


def main():
    before = tree_hashes()
    argv = [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--env", "HOME=/tmp", "--env", "CLAUDE_HOME=/tmp/state-home",
        "--env", "CLAUDE_ASSETS_HOME=/source", "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "PYTHONNOUSERSITE=1", "--env", "PYTHONUTF8=1", "--env", "PYTHONPATH=/source/scripts",
        "--mount", f"type=bind,source={SOURCE},target=/source,readonly",
        "--mount", f"type=bind,source={OUT / 'observe_components.py'},target=/review/observe_components.py,readonly",
        "--workdir", "/source/scripts", "--entrypoint", "/usr/bin/timeout", IMAGE,
        "60", "/app/.venv/bin/python", "-B", "/review/observe_components.py",
    ]
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=80)
    for stream in ("stdout", "stderr"):
        (OUT / f"observations.{stream}.txt").write_bytes(getattr(result, stream))
    receipt = {
        "kind": "actual_original_component_input_observations",
        "revision": "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2", "source": "baldrix",
        "argv": argv, "image": IMAGE, "pyyaml_version": "6.0.3 (image interpreter verified separately)",
        "started_at": start, "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "returncode": result.returncode, "source_files": len(before), "source_bytes_unchanged": before == tree_hashes(),
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(), "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "program_sha256": hashlib.sha256((OUT / "observe_components.py").read_bytes()).hexdigest(),
        "limits": "Temporary inputs, Linux only, original component APIs. No runtime hook main, threshold writer, actual model, production permission, acceptance or live-state verification. Original entrypoint overridden; no service launched.",
    }
    (OUT / "observations.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"returncode": result.returncode, "bytes": len(result.stdout), "unchanged": receipt["source_bytes_unchanged"]}))


if __name__ == "__main__":
    main()
