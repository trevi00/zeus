"""Attempt-preserving recorder. Historical run_observations.py remains unchanged."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/baldrix/pinned"
IMAGE = "sha256:39d4f226fa8b1ae6087b283b16d0176e9181f8aaf31dcbf0c9145e513453725a"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(directory, argv, timeout, container_name=None, metadata=None):
    # Exclusive directory reserves the attempt before any process can run.
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "intent.json", {"argv": argv, "timeout_seconds": timeout,
         "container_name": container_name, "started_at": now(), "cwd": str(ROOT), "metadata": metadata})
    result = {"status": "not_started", "returncode": None, "timed_out": False,
              "process_tree_termination_verified": False}
    proc = None
    try:
        with (directory / "stdout.txt").open("xb") as stdout, (directory / "stderr.txt").open("xb") as stderr:
            try:
                proc = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr)
            except OSError as exc:
                result.update(status="launch_error", error_type=type(exc).__name__, error=str(exc))
            else:
                result.update(status="running", pid=proc.pid)
                try:
                    result["returncode"] = proc.wait(timeout=timeout)
                    result["status"] = "completed"
                except subprocess.TimeoutExpired:
                    result.update(status="timed_out", timed_out=True)
                    try:
                        proc.kill()
                        result["returncode"] = proc.wait(timeout=10)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        result.update(status="termination_error", error_type=type(exc).__name__)
                except BaseException as exc:
                    result.update(status="interrupted", error_type=type(exc).__name__)
                    try:
                        proc.kill()
                        result["returncode"] = proc.wait(timeout=10)
                    except (OSError, subprocess.TimeoutExpired) as termination:
                        result["termination_error"] = type(termination).__name__
                    raise
    finally:
        # A named Docker container is removed even if killing its CLI was insufficient.
        if container_name is not None:
            try:
                cleanup = subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=15)
                (directory / "cleanup.stdout.txt").write_bytes(cleanup.stdout)
                (directory / "cleanup.stderr.txt").write_bytes(cleanup.stderr)
                result["container_cleanup_returncode"] = cleanup.returncode
            except subprocess.TimeoutExpired as exc:
                for stream in ("stdout", "stderr"):
                    raw = getattr(exc, stream) or b""
                    (directory / f"cleanup.{stream}.txt").write_bytes(raw if isinstance(raw, bytes) else raw.encode())
                result["container_cleanup_error"] = "TimeoutExpired"
            except Exception as exc:
                result.update(container_cleanup_error=type(exc).__name__)
        result["completed_at"] = now()
        for stream in ("stdout", "stderr"):
            path = directory / f"{stream}.txt"
            result[f"{stream}_sha256"] = digest(path) if path.exists() else None
        save(directory / "receipt.json", result)
    return result


def recorder_check():
    base = OUT / "attempts" / ("recorder-check-" + uuid.uuid4().hex)
    base.mkdir(parents=True)
    (base / "recorder-source.py").write_bytes(Path(__file__).read_bytes())
    normal = capture(base / "normal", [sys.executable, "-c", "print('normal-output')"], 10)
    timed = capture(base / "timeout", [sys.executable, "-u", "-c", "import time; print('before-timeout', flush=True); time.sleep(10)"], 1)
    missing = capture(base / "missing", [str(base / "does-not-exist.exe")], 1)
    marker = base / "must-not-exist.txt"
    before = digest(base / "normal/stdout.txt")
    rejected = False
    try:
        capture(base / "normal", [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"], 10)
    except FileExistsError:
        rejected = True
    assert normal["returncode"] == 0 and normal["status"] == "completed"
    assert timed["timed_out"] and "before-timeout" in (base / "timeout/stdout.txt").read_text()
    assert missing["status"] == "launch_error"
    assert rejected and not marker.exists() and digest(base / "normal/stdout.txt") == before
    save(base / "validation.json", {"normal": True, "timeout_partial_output_retained": True,
         "launch_error_receipt": True, "existing_attempt_rejected_before_launch": True,
         "program_sha256": digest(Path(__file__)), "docker_backend_tested": False})
    print(json.dumps({"recorder_check": base.relative_to(ROOT).as_posix(), "passed": True}))


def original_observation():
    attempt_id = uuid.uuid4().hex
    base = OUT / "attempts" / ("components-" + attempt_id)
    name = "zeus-review-" + attempt_id
    argv = ["docker", "run", "--name", name, "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
            "--memory", "256m", "--cpus", "1", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m"]
    for value in ("HOME=/tmp", "CLAUDE_HOME=/tmp/state-home", "CLAUDE_ASSETS_HOME=/source",
                  "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "PYTHONUTF8=1", "PYTHONPATH=/source/scripts", "TZ=UTC0"):
        argv += ["--env", value]
    argv += ["--mount", f"type=bind,source={SOURCE},target=/source,readonly",
             "--mount", f"type=bind,source={OUT / 'component_observations.py'},target=/review.py,readonly",
             "--workdir", "/source/scripts", "--entrypoint", "/usr/bin/timeout", IMAGE,
             "60", "/app/.venv/bin/python", "-B", "/review.py"]
    before = {p.relative_to(SOURCE).as_posix(): digest(p) for p in sorted(SOURCE.rglob("*")) if p.is_file()}
    metadata = {"source_files": len(before), "revision": "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2",
                "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                "program_sha256": digest(OUT / "component_observations.py"), "recorder_sha256": digest(Path(__file__))}
    result = capture(base, argv, 80, container_name=name, metadata=metadata)
    after = {p.relative_to(SOURCE).as_posix(): digest(p) for p in sorted(SOURCE.rglob("*")) if p.is_file()}
    save(base / "source-check.json", {"source_files": len(before), "source_bytes_unchanged": before == after,
         "source_tree_hash_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
         "program_sha256": digest(OUT / "component_observations.py"), "recorder_sha256": digest(Path(__file__))})
    print(json.dumps({"attempt": base.relative_to(ROOT).as_posix(), **result}))
    return 0 if result["status"] == "completed" and result["returncode"] == 0 and result.get("container_cleanup_returncode") == 0 and before == after else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recorder-check", action="store_true")
    args = parser.parse_args()
    raise SystemExit(recorder_check() if args.recorder_check else original_observation())
