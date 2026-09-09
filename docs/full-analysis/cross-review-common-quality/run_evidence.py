"""Run bounded original modules in a cached, isolated Linux container."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/baldrix/pinned"
IMAGE = "sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a"


def hashes():
    return {
        str(p.relative_to(SOURCE)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(SOURCE.rglob("*")) if p.is_file()
    }


def main():
    before = hashes()
    base = [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
        "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
    ]
    for value in (
        "HOME=/home/reviewer", "CLAUDE_ASSETS_HOME=/home/reviewer/.claude",
        "CLAUDE_HOME=/tmp/state-home", "CLAUDE_STATE_DIR=/tmp/state",
        "CLAUDE_TELEMETRY_DIR=/tmp/telemetry", "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONNOUSERSITE=1", "PYTHONUTF8=1", "PYTHONPATH=/home/reviewer/.claude/scripts",
    ):
        base += ["--env", value]
    base += [
        "--mount", f"type=bind,source={SOURCE},target=/home/reviewer/.claude,readonly",
        "--mount", f"type=bind,source={OUT / 'observe_quality.py'},target=/review/observe_quality.py,readonly",
        "--workdir", "/home/reviewer/.claude/scripts", IMAGE, "timeout", "70", "python", "-B",
    ]
    cases = {
        "upstream-trigger": ["-m", "tests.test_skill_trigger_eval"],
        "upstream-quality": ["-m", "tests.test_skill_quality_axes"],
        "reviewer-observations": ["/review/observe_quality.py"],
    }
    for name, command in cases.items():
        argv = base + command
        started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=90)
        for stream in ("stdout", "stderr"):
            (OUT / f"{name}.{stream}.txt").write_bytes(getattr(result, stream))
        receipt = {
            "kind": "actual_isolated_upstream_test" if name.startswith("upstream") else "actual_reviewer_input_observations",
            "source": "baldrix", "revision": "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2",
            "argv": argv, "image": IMAGE, "started_at": started,
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "source_files_before": len(before),
            "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "source_bytes_unchanged": before == hashes(),
            "home_skill_present": "skills/_common/qa-boundary.md" in before,
            "home_skill_sha256": before.get("skills/_common/qa-boundary.md"),
            "limitations": "Linux container only. Original unit tests use temporary input fixtures and SKILLS_DIR reassignment; no real-agent, acceptance, Windows or WSL execution. No host credentials or live state mounted. qa-boundary home path points to pinned assets to avoid silent missing-file return.",
        }
        if name == "reviewer-observations":
            receipt["reviewer_program_sha256"] = hashlib.sha256((OUT / "observe_quality.py").read_bytes()).hexdigest()
        (OUT / f"{name}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(name, result.returncode, result.stdout.decode("utf-8", errors="replace")[-900:])


if __name__ == "__main__":
    main()
