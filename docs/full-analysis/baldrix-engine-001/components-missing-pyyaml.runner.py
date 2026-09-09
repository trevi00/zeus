"""Run bounded component observations in a read-only, networkless container."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

from run_upstream import IMAGE, OUT, ROOT, SOURCE, tree_hashes


def main():
    before = tree_hashes()
    program = OUT / "component_observations.py"
    for zone in ("UTC0",):
        argv = [
            "docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
            "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--env", "HOME=/tmp", "--env", "CLAUDE_HOME=/tmp/state-home",
            "--env", "CLAUDE_ASSETS_HOME=/source", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONNOUSERSITE=1", "--env", "PYTHONUTF8=1",
            "--env", "PYTHONPATH=/source/scripts", "--env", "TZ=" + zone,
            "--mount", f"type=bind,source={SOURCE},target=/source,readonly",
            "--mount", f"type=bind,source={program},target=/review.py,readonly",
            "--workdir", "/source/scripts", IMAGE,
            "timeout", "60", "python", "-B", "/review.py",
        ]
        start = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=80)
        name = "components-" + zone
        for stream in ("stdout", "stderr"):
            (OUT / f"{name}.{stream}.txt").write_bytes(getattr(result, stream))
        receipt = {
            "kind": "actual_isolated_original_component_observations", "source": "baldrix",
            "revision": "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2",
            "argv": argv, "image": IMAGE, "started_at": start,
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
            "source_files": len(before), "source_bytes_unchanged": before == tree_hashes(),
            "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "limits": "Explicit temporary input files and actual original functions; no mocks. No provider, worker, validator, real user/device, acceptance, Windows/WSL, live state or operating harness invocation. PyYAML version is captured in stdout.",
        }
        (OUT / f"{name}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(name, result.returncode, result.stdout.decode("utf-8"))


if __name__ == "__main__":
    main()
