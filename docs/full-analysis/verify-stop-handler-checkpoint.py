"""Verify source identities and captured review bytes, not adoption or semantics."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/full-analysis"
BASE = ROOT / ".runtime/absorption/sources"
FOLDERS = ("baldrix-stop-001", "baldrix-validators-002", "harness-cli-004", "harness-handlers-001")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    manifests = {}
    primary = support = 0
    for folder in FOLDERS:
        for name in ("files.json", "supporting-evidence.json", "supporting.json"):
            path = REPORT / folder / name
            if not path.exists():
                continue
            records = read(path)
            primary += len(records) if name == "files.json" else 0
            support += len(records) if name != "files.json" else 0
            for row in records:
                source = row["source"]
                if source in ("zeus-working-tree", "zeus"):
                    raw = (ROOT / row["path"]).read_bytes()
                    assert len(raw) == row["bytes"]
                else:
                    if source not in manifests:
                        manifest = read(BASE / source / "manifest.json")
                        manifests[source] = (manifest["revision"], {r["path"]: r for r in manifest["inventory"]})
                    revision, inventory = manifests[source]
                    entry = inventory[row["path"]]
                    assert row["revision"] == revision
                    raw = (BASE / source / "pinned" / row["path"]).read_bytes()
                    assert len(raw) == entry["bytes"]
                    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                    assert blob == entry["object"] == row["git_blob"]
                assert digest(raw) == row.get("pinned_sha256", row.get("sha256")), (path, row["path"])
                lines = raw.splitlines(keepends=True)
                for span in row.get("read_ranges", row.get("line_ranges", [])):
                    if isinstance(span, dict):
                        start = span.get("start_line", span.get("start"))
                        end = span.get("end_line", span.get("end"))
                        if "raw_range_sha256" in span:
                            assert digest(b"".join(lines[start - 1:end])) == span["raw_range_sha256"]
                    else:
                        start, end = span
                    assert 1 <= start <= end <= len(lines)
                if row.get("review_ref"):
                    # Earlier recorder used a human-readable section annotation.
                    ref = row["review_ref"].split("#")[0].split(" (section ")[0]
                    assert (ROOT / ref).is_file(), ref
    assert primary == 56 and support == 82
    stop = REPORT / FOLDERS[0]
    for prefix in ("claude-initial", "claude-discussion"):
        receipt = read(stop / f"{prefix}-receipt.json")
        raw = (stop / f"{prefix}.json").read_bytes()
        assert digest(raw) == receipt["stdout_sha256"]
        assert digest((stop / f"{prefix}.stderr.txt").read_bytes()) == receipt["stderr_sha256"]
        response = json.loads(raw)
        assert receipt["returncode"] == 0 and response["is_error"] is False
        assert (stop / f"{prefix}.md").read_bytes() == response["result"].encode("utf-8")
    for prefix in ("calendar-lib-self-check", "calendar-emitter-self-check", "components"):
        receipt = read(stop / f"{prefix}.receipt.json")
        assert receipt["returncode"] == 0 and receipt["source_bytes_unchanged"] is True
        for stream in ("stdout", "stderr"):
            assert digest((stop / f"{prefix}.{stream}.txt").read_bytes()) == receipt[f"{stream}_sha256"]
        if receipt["program_sha256"]:
            assert digest((stop / "component_observations.py").read_bytes()) == receipt["program_sha256"]
        if receipt["original_source"]:
            assert digest((BASE / "baldrix/pinned" / receipt["original_source"]).read_bytes()) == receipt["original_source_sha256"]
    observation = read(stop / "components.stdout.txt")
    for case in observation["retry_cases"].values():
        for name in ("first", "second"):
            child = case[name]
            assert child["returncode"] == 0
            assert digest(json.dumps(child["input"]).encode("utf-8")) == child["input_sha256"]
            for stream in ("stdout", "stderr"):
                assert digest(child[stream].encode("utf-8")) == child[f"{stream}_sha256"]
    failure = read(REPORT / "baldrix-validators-002/recorder-failure.json")
    assert digest((REPORT / "baldrix-validators-002" / failure["program"]).read_bytes()) == failure["sha256"]
    artifacts = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for folder in FOLDERS for p in sorted((REPORT / folder).iterdir()) if p.is_file()}
    result = {
        "kind": "root_checkpoint_identity_verification", "primary_records": primary,
        "supporting_records": support, "receipt_hashes_verified": 5,
        "nested_actual_Stop_CLI_stream_records": 4, "historical_failed_recorder_preserved": True,
        "artifact_hashes": artifacts, "semantic_correctness_certified": False,
        "whole_analysis_complete": False, "adoption_approved": False,
    }
    (REPORT / "stop-handler-checkpoint-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": primary, "supporting": support, "receipts": 5, "artifacts": len(artifacts)}))


if __name__ == "__main__":
    main()
