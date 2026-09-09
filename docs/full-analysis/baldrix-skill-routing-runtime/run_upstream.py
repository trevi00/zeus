"""Original bounded unit modules in an immutable isolated Linux image."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/baldrix/pinned"
IMAGE = "sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a"


def tree_hashes():
    return {p.relative_to(SOURCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(SOURCE.rglob("*")) if p.is_file()}


def main():
    before = tree_hashes()
    for module in ("test_skill_token_budget", "test_tech_stack", "test_skill_match_render"):
        argv = [
            "docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
            "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--env", "HOME=/tmp", "--env", "CLAUDE_HOME=/tmp/state-home",
            "--env", "CLAUDE_ASSETS_HOME=/source", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONNOUSERSITE=1", "--env", "PYTHONUTF8=1",
            "--mount", f"type=bind,source={SOURCE},target=/source,readonly",
            "--workdir", "/source/scripts", IMAGE,
            "timeout", "60", "python", "-B", "-m", "tests." + module,
        ]
        start = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=80)
        for stream in ("stdout", "stderr"):
            (OUT / f"{module}.{stream}.txt").write_bytes(getattr(result, stream))
        receipt = {
            "kind": "actual_isolated_original_unit_test", "source": "baldrix",
            "revision": "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2",
            "argv": argv, "image": IMAGE, "started_at": start,
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            "source_files": len(before), "source_bytes_unchanged": before == tree_hashes(),
            "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "original_test_sha256": before[f"scripts/tests/{module}.py"],
            "limits": "Original unit tests and temporary input fixtures. Not actual model, full hook, acceptance, Windows, WSL or live-state verification. No host credentials mounted.",
        }
        (OUT / f"{module}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(module, result.returncode, result.stdout.decode("utf-8").splitlines()[-1])


if __name__ == "__main__":
    main()
