"""Execute reviewed original self-checks and bounded scenarios in an immutable image."""
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
    return {p.relative_to(SOURCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SOURCE.rglob("*")) if p.is_file()}


def main():
    before = hashes()
    for name, args, source in (
        ("composite-unit", ["/source/scripts/tests/test_composite_breaker.py"], "scripts/tests/test_composite_breaker.py"),
        ("config-unit", ["/source/scripts/tests/test_breaker_config.py"], "scripts/tests/test_breaker_config.py"),
        ("components", ["/review.py"], None),
    ):
        assert not (OUT / f"{name}.receipt.json").exists(), "Preserve previous attempt before repeating"
        program = OUT / "component_observations.py"
        argv = [
            "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
            "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m", "--env", "HOME=/tmp",
            "--env", "CLAUDE_HOME=/tmp/state-home", "--env", "CLAUDE_ASSETS_HOME=/source",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONNOUSERSITE=1",
            "--env", "PYTHONUTF8=1", "--env", "PYTHONPATH=/source/scripts", "--env", "TZ=UTC0",
            "--mount", f"type=bind,source={SOURCE},target=/source,readonly",
            "--mount", f"type=bind,source={program},target=/review.py,readonly",
            "--workdir", "/source/scripts", IMAGE, "timeout", "60", "python", "-B", *args,
        ]
        started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=80)
        for stream in ("stdout", "stderr"):
            (OUT / f"{name}.{stream}.txt").write_bytes(getattr(proc, stream))
        receipt = {
            "kind": "original_breaker_unit_wrapper" if source else "original_breaker_file_observations",
            "revision": "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2",
            "argv": argv, "image": IMAGE, "started_at": started,
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "returncode": proc.returncode, "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
            "source_files": len(before), "source_bytes_unchanged": before == hashes(),
            "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "original_source": source, "original_source_sha256": before[source] if source else None,
            "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest() if not source else None,
            "limits": "Original unit wrappers use temporary files plus injected clock/emitter/config-path fixtures; not acceptance. Component program uses original methods and real isolated JSON/YAML/permission failures without patched clocks, methods, providers or SDKs. Seeded stale record and late object result are not a killed/live process experiment. No actual concurrent-process race, vendor/model/worker/host-hook/human/device/Windows/WSL acceptance or source mutation.",
        }
        (OUT / f"{name}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
        print(json.dumps({"name": name, "returncode": proc.returncode, "last_line": lines[-1] if lines else "", "source_unchanged": receipt["source_bytes_unchanged"]}))


if __name__ == "__main__":
    main()
