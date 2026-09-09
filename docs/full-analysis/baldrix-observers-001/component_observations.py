"""Original observer calls, controlled child processes and isolated real files.

No method/clock/subprocess patch. Synthetic claims are not human/model acceptance.
"""
import json
import os
from pathlib import Path
import sys

from lib.observers.evidence_fab import detect, REPLAY_BACKOFF_SEC


def main():
    assert os.getuid() == 65534
    root = Path("/tmp/observer-cases")
    root.mkdir()
    results = {"uid": os.getuid(), "actual_imported_backoff": REPLAY_BACKOFF_SEC}
    results["empty_envelope"] = detect({}).value
    results["outer_empty_hides_nested_missing"] = detect({"evidence": [], "envelope": {
        "evidence": [{"file_path": "/tmp/observer-missing-artifact"}]}}).value
    results["directory_as_evidence"] = detect({"evidence": [{"file_path": str(root)}]}).value
    results["passed_without_replay"] = detect({"evidence": [{"test_result": "passed"}]}).value
    target = root / "only-in-entry-cwd.txt"
    target.write_text("actual artifact", encoding="utf-8")
    results["relative_path_cwd_mismatch"] = detect({"evidence": [{
        "file_path": target.name, "cwd": str(root), "test_result": "passed",
        "replay_cmd": [sys.executable, "-c", "pass"]}]}).value
    results["missing_executable"] = detect({"evidence": [{
        "test_result": "passed", "replay_cmd": ["/tmp/observer-nonexistent-executable"]}]}).value
    written = root / "written-by-replay.txt"
    results["replay_write_verdict"] = detect({"evidence": [{"test_result": "passed", "replay_cmd": [
        sys.executable, "-c", "from pathlib import Path; Path('written-by-replay.txt').write_text('effect')"],
        "cwd": str(root)}]}).value
    results["replay_created_file"] = written.read_text() == "effect"
    try:
        detect({"evidence": [{"test_result": "passed", "replay_cmd": [
            sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([255]))"]}]})
    except Exception as exc:
        results["invalid_utf8_exception"] = type(exc).__name__
    try:
        detect({"evidence": [{"file_path": "invalid\0path"}]})
    except Exception as exc:
        results["nul_path_exception"] = type(exc).__name__
    restricted = root / "restricted"
    restricted.mkdir()
    hidden = restricted / "artifact"
    hidden.write_text("exists")
    restricted.chmod(0)
    try:
        results["permission_denied_path"] = detect({"evidence": [{"file_path": str(hidden)}]}).value
    finally:
        restricted.chmod(0o700)
    print(json.dumps(results, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
