"""Verify checkpoint identities and captured bytes, not semantic correctness."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".runtime/absorption/sources"
REPORT = ROOT / "docs/full-analysis"
FOLDERS = ("baldrix-engine-001", "baldrix-validators-001", "harness-cli-003", "harness-cron-002")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    manifests = {}
    primary = 0
    support = 0
    for folder in FOLDERS:
        for name in ("files.json", "supporting-evidence.json", "supporting.json"):
            path = REPORT / folder / name
            if not path.exists():
                continue
            records = json.loads(path.read_text(encoding="utf-8"))
            if name == "files.json":
                primary += len(records)
            else:
                support += len(records)
            for row in records:
                source = row["source"]
                if source == "zeus-working-tree":
                    raw = (ROOT / row["path"]).read_bytes()
                else:
                    if source not in manifests:
                        manifest = json.loads((BASE / source / "manifest.json").read_text(encoding="utf-8"))
                        manifests[source] = (manifest["revision"], {r["path"]: r for r in manifest["inventory"]})
                    revision, inventory = manifests[source]
                    assert row["revision"] == revision
                    entry = inventory[row["path"]]
                    raw = (BASE / source / "pinned" / row["path"]).read_bytes()
                    assert len(raw) == entry["bytes"]
                    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry["object"]
                assert digest(raw) == row["pinned_sha256"], (path, row["path"])
                lines = raw.splitlines(keepends=True)
                for span in row.get("read_ranges", row.get("line_ranges", [])):
                    if isinstance(span, dict):
                        start, end = span["start_line"], span["end_line"]
                        if "raw_range_sha256" in span:
                            assert digest(b"".join(lines[start - 1:end])) == span["raw_range_sha256"]
                    else:
                        start, end = span
                    assert 1 <= start <= end <= len(lines)
                if row.get("review_ref"):
                    assert (ROOT / row["review_ref"].split("#")[0]).is_file()
    assert primary == 67 and support == 97
    engine = REPORT / FOLDERS[0]
    for prefix in ("claude-initial", "claude-discussion"):
        receipt = json.loads((engine / f"{prefix}-receipt.json").read_text(encoding="utf-8"))
        raw = (engine / f"{prefix}.json").read_bytes()
        assert digest(raw) == receipt["stdout_sha256"]
        assert digest((engine / f"{prefix}.stderr.txt").read_bytes()) == receipt["stderr_sha256"]
        response = json.loads(raw)
        assert receipt["returncode"] == 0 and response["is_error"] is False
        assert (engine / f"{prefix}.md").read_bytes() == response["result"].encode("utf-8")
    for prefix, code, program in (
        ("test_dispatch_retry", 0, None),
        ("components-missing-pyyaml", 1, "components-missing-pyyaml.program.py"),
        ("components-UTC0", 0, "component_observations.py"),
    ):
        receipt = json.loads((engine / f"{prefix}.receipt.json").read_text(encoding="utf-8"))
        assert receipt["returncode"] == code and receipt["source_bytes_unchanged"] is True
        for stream in ("stdout", "stderr"):
            assert digest((engine / f"{prefix}.{stream}.txt").read_bytes()) == receipt[f"{stream}_sha256"]
        if program:
            assert digest((engine / program).read_bytes()) == receipt["program_sha256"]
        else:
            assert digest((BASE / "baldrix/pinned/scripts/tests/test_dispatch_retry.py").read_bytes()) == receipt["original_test_sha256"]
    artifacts = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for folder in FOLDERS for p in sorted((REPORT / folder).iterdir()) if p.is_file()}
    result = {
        "kind": "root_checkpoint_identity_verification", "primary_records": primary,
        "supporting_records": support, "receipt_hashes_verified": 5,
        "artifact_hashes": artifacts, "semantic_correctness_certified": False,
        "whole_analysis_complete": False, "adoption_approved": False,
    }
    (REPORT / "engine-validator-checkpoint-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": primary, "supporting": support, "receipts": 5, "artifacts": len(artifacts)}))


if __name__ == "__main__":
    main()
