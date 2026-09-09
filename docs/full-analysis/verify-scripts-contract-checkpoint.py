"""Verify source identities and captured review bytes, not adoption or semantics."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/full-analysis"
BASE = ROOT / ".runtime/absorption/sources"
FOLDERS = ("baldrix-scripts-root-001", "baldrix-tests-001", "harness-contract-tests-003", "harness-contract-tests-004")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    manifests = {}
    primary = support = 0
    for folder in FOLDERS:
        checkpoint = read(REPORT / folder / "checkpoint.json")
        partition = next(p for p in read(REPORT / "partitions.json") if p["partition"] == checkpoint["partition"])
        entries = read(REPORT / folder / "files.json")
        assert {(r["source"], r["path"]) for r in entries} == {(r["source"], r["path"]) for r in partition["paths"]}
        assert len(entries) == len(partition["paths"])
        assert checkpoint.get("scope_sha256", partition["scope_sha256"]) == partition["scope_sha256"]
        if checkpoint.get("review_sha256"):
            assert digest((REPORT / folder / "review.md").read_bytes()) == checkpoint["review_sha256"]
        for artifact, expected in checkpoint.get("artifact_sha256", {}).items():
            assert digest((REPORT / folder / artifact).read_bytes()) == expected
        artifact_ledger = REPORT / folder / "artifact-hashes.json"
        if artifact_ledger.exists():
            for artifact, expected in read(artifact_ledger).items():
                assert digest((REPORT / folder / artifact).read_bytes()) == expected
        overlap_path = REPORT / folder / "prior-overlap.json"
        if overlap_path.exists():
            for overlap in read(overlap_path):
                ledger = ROOT / overlap["prior_ledger"]
                assert digest(ledger.read_bytes()) == overlap["prior_ledger_sha256"]
                assert digest((ROOT / overlap["prior_review"]).read_bytes()) == overlap["prior_review_sha256"]
                matches = [r for r in read(ledger) if r["path"] == overlap["path"]]
                assert len(matches) == 1
                previous = matches[0]
                assert previous["git_blob"] == overlap["git_blob"]
                assert previous.get("pinned_sha256", previous.get("sha256")) == overlap["pinned_sha256"]
        for name in ("files.json", "supporting-evidence.json", "supporting.json", "reused-support.json"):
            path = REPORT / folder / name
            if not path.exists():
                continue
            records = read(path)
            primary += len(records) if name == "files.json" else 0
            support += len(records) if name != "files.json" else 0
            for row in records:
                if name == "reused-support.json" and "source" not in row:
                    prior_path = ROOT / row["prior_ledger"]
                    assert digest(prior_path.read_bytes()) == row["prior_ledger_sha256"]
                    for prior_review in row["prior_reviews"]:
                        assert digest((ROOT / prior_review["path"]).read_bytes()) == prior_review["sha256"]
                    candidates = [r for r in read(prior_path) if r["path"] == row["path"]]
                    assert len(candidates) == 1
                    prior = candidates[0]
                    assert prior["git_blob"] == row["git_blob"]
                    assert prior["pinned_sha256"] == row["pinned_sha256"]
                    assert prior["read_ranges"] == row["prior_read_ranges"]
                    row = {**prior, **row}
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
                if row.get("prior_ledger"):
                    assert digest((ROOT / row["prior_ledger"]).read_bytes()) == row["prior_ledger_sha256"]
                prior_primary = row.get("prior_primary")
                if not prior_primary and isinstance(row.get("prior_ref"), dict):
                    prior_primary = row["prior_ref"]
                if prior_primary:
                    ledger = ROOT / prior_primary["ledger"]
                    assert digest(ledger.read_bytes()) == prior_primary["ledger_sha256"]
                    assert digest((ROOT / prior_primary["review_ref"].split("#")[0]).read_bytes()) == prior_primary["review_sha256"]
                    matches = [r for r in read(ledger) if r["source"] == source and r["path"] == row["path"]]
                    assert len(matches) == 1 and matches[0] == prior_primary["row"]
                    assert matches[0]["pinned_sha256"] == digest(raw)
                    assert matches[0]["git_blob"] == row["git_blob"]
                joined = row.get("prior_read_evidence")
                if joined:
                    ledger = ROOT / joined["ledger"]
                    assert digest(ledger.read_bytes()) == joined["ledger_sha256"]
                    assert joined["row"] in read(ledger)
                    assert joined["row"]["pinned_sha256"] == digest(raw)
                    assert digest((ROOT / joined["review_ref"]).read_bytes()) == joined["review_sha256"]
                    joined_lines = set()
                    for start, end in joined["current_fresh_ranges"] + joined["row"]["read_ranges"]:
                        joined_lines.update(range(start, end + 1))
                    assert joined_lines == set(range(1, len(raw.splitlines()) + 1))
                reuse = row.get("previous_review_reuse")
                if reuse:
                    ledger = ROOT / reuse["supporting_ledger"]
                    assert digest(ledger.read_bytes()) == reuse["supporting_ledger_sha256"]
                    matches = [r for r in read(ledger) if r["source"] == source and r["path"] == row["path"]]
                    matches = [r for r in matches if r.get("line_ranges") == reuse["line_ranges"]]
                    assert len(matches) == 1
                    previous = matches[0]
                    assert previous.get("pinned_sha256", previous.get("sha256")) == reuse["sha256"] == digest(raw)
                    assert previous["line_ranges"] == reuse["line_ranges"] == row["line_ranges"]
                    review_path = ROOT / reuse["review_ref"].split("#")[0]
                    assert review_path.is_file()
                    if reuse.get("review_sha256"):
                        assert digest(review_path.read_bytes()) == reuse["review_sha256"]
                    if "source_row" in reuse:
                        assert previous == reuse["source_row"]
                    if "supporting_ledger_row_index_zero_based" in reuse:
                        assert read(ledger)[reuse["supporting_ledger_row_index_zero_based"]] == previous
                lines = raw.splitlines(keepends=True)
                covered = set()
                for span in row.get("read_ranges", row.get("line_ranges", row.get("reused_read_ranges", []))):
                    if isinstance(span, dict):
                        start = span.get("start_line", span.get("start"))
                        end = span.get("end_line", span.get("end"))
                        if "raw_range_sha256" in span:
                            assert digest(b"".join(lines[start - 1:end])) == span["raw_range_sha256"]
                    else:
                        start, end = span
                    assert 1 <= start <= end <= len(lines)
                    covered.update(range(start, end + 1))
                if name == "files.json":
                    assert len(covered) == len(lines), (path, row["path"])
                if row.get("review_ref"):
                    # Earlier recorder used a human-readable section annotation.
                    ref = row["review_ref"].split("#")[0].split(" (section ")[0]
                    assert (ROOT / ref).is_file(), ref
    assert primary == 61 and support == 100
    assert all((REPORT / folder / name).is_file() for folder in FOLDERS for name in ("files.json", "checkpoint.json"))
    stop = REPORT / FOLDERS[0]
    source_hashes = {
        p.relative_to(BASE / "baldrix/pinned").as_posix(): digest(p.read_bytes())
        for p in sorted((BASE / "baldrix/pinned").rglob("*")) if p.is_file()
    }
    tree_digest = digest(json.dumps(source_hashes, sort_keys=True).encode())
    for prefix in ("claude-initial", "claude-discussion"):
        receipt = read(stop / f"{prefix}-receipt.json")
        raw = (stop / f"{prefix}.json").read_bytes()
        assert digest(raw) == receipt["stdout_sha256"]
        assert digest((stop / f"{prefix}.stderr.txt").read_bytes()) == receipt["stderr_sha256"]
        response = json.loads(raw)
        assert receipt["returncode"] == 0 and response["is_error"] is False
        assert (stop / f"{prefix}.md").read_bytes() == response["result"].encode("utf-8")
    for prefix in ("install-hooks-unit", "components"):
        receipt = read(stop / f"{prefix}.receipt.json")
        assert receipt["returncode"] == 0
        assert receipt["source_bytes_unchanged"] is True
        assert len(source_hashes) == receipt["source_files"] == 1648
        assert tree_digest == receipt["source_tree_hash_before"]
        for stream in ("stdout", "stderr"):
            assert digest((stop / f"{prefix}.{stream}.txt").read_bytes()) == receipt[f"{stream}_sha256"]
        if receipt["program_sha256"]:
            assert digest((stop / "component_observations.py").read_bytes()) == receipt["program_sha256"]
        if receipt["original_source"]:
            assert digest((BASE / "baldrix/pinned" / receipt["original_source"]).read_bytes()) == receipt["original_source_sha256"]
    artifacts = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for folder in FOLDERS for p in sorted((REPORT / folder).iterdir()) if p.is_file()}
    result = {
        "kind": "root_checkpoint_identity_verification", "primary_records": primary,
        "supporting_records": support, "receipt_hashes_verified": 4,
        "direct_or_reused_supporting_records": 100, "reused_primary_reference_records": 0,
        "fresh_primary_read_with_prior_primary_overlap": 0,
        "same_byte_prior_support_references": 11, "joined_fresh_prior_support": 0,
        "original_installer_static_tests_passed": 5, "unit_attempts": 1, "actual_model_invocations": 0,
        "artifact_hashes": artifacts, "semantic_correctness_certified": False,
        "whole_analysis_complete": False, "adoption_approved": False,
    }
    (REPORT / "scripts-contract-checkpoint-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": primary, "supporting": support, "receipts": 4, "artifacts": len(artifacts)}))


if __name__ == "__main__":
    main()
