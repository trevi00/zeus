"""Own metadata recorder; reads bytes only and never imports upstream code."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REL = OUT.relative_to(ROOT).as_posix()
SOURCE = ROOT / ".runtime/absorption/sources/baldrix"
REV = "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2"
STATUS = "body_reviewed_call_test_trace_pending"
SUPPORT = [
    ("scripts/cli/reverse_engineer.py", [[1, 266]]),
    ("scripts/cli/ingest_docs.py", [[1, 80]]),
    ("scripts/cli/project_analyze.py", [[350, 396]]),
    ("scripts/lib/spec_facets.py", [[123, 179]]),
    ("scripts/lib/intent_doc_floor.py", [[1, 69]]),
    ("scripts/tests/probe_intent_docs.py", [[1, 124]]),
    ("scripts/validators/prd.py", [[1, 98]]),
    ("scripts/validators/convention.py", [[1, 97]]),
    ("scripts/validators/logical.py", [[1, 143]]),
    ("scripts/tests/test_extractors.py", [[1, 895]]),
    ("scripts/tests/test_doc_classifier.py", [[1, 130]]),
    ("scripts/tests/test_doc_classifier_explained.py", [[1, 69]]),
    ("scripts/tests/test_reverse_engineer.py", [[1, 69]]),
]
LINKS = {
    1: [1, 10, 13], 2: [1, 5, 6, 10], 3: [1, 4, 10],
    4: [1, 5, 6, 10], 5: [1, 8, 10], 6: [1, 9, 10],
    7: [1, 2, 3, 11, 12, 13], 8: [1, 4, 10],
    9: [1, 5, 6, 10], 10: [1, 4, 9, 10],
    11: [1, 5, 6, 7, 10], 12: [1, 5, 6, 10],
}
REMAINING = [
    "Transitive caller/config/test closure pending; only recorded ranges reviewed.",
    "Upstream tests/import/probe execution prohibited in this static partition: not run.",
    "Actual Claude review, license/dependency closure, model qualification pending.",
    "Windows/Linux/WSL execution, human experience acceptance, adoption approval pending.",
    "Zeus implementation equivalence and exact eight-stage SDD wiring not established.",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def main():
    manifest = load(SOURCE / "manifest.json")
    assert manifest["revision"] == REV
    entries = {r["path"]: r for r in manifest["inventory"]}
    inventory = load(OUT / "inventory.json")
    assert inventory == next(p for p in load(ROOT / "docs/full-analysis/partitions.json")
                             if p["partition"] == inventory["partition"])
    review = (OUT / "review.md").read_text(encoding="utf-8")

    def meta(path, ranges=None):
        raw = (SOURCE / "pinned" / path).read_bytes()
        lines = len(raw.decode("utf-8").splitlines())
        entry = entries[path]
        digest = sha(raw)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        expected = entry.get("snapshot_sha256")
        assert blob == entry["object"] and len(raw) == entry["bytes"], path
        assert expected is None or expected == digest, path
        ranges = ranges or [[1, lines]]
        assert all(1 <= a <= b <= lines for a, b in ranges), path
        return {
            "source": "baldrix", "path": path, "revision": REV,
            "bytes": len(raw), "git_blob": blob, "raw_git_blob_status": "matched",
            "pinned_sha256": digest, "observed_sha256": None,
            "manifest_sha256": expected,
            "manifest_sha256_status": "matched" if expected else "absent_computed_only",
            "read_ranges": ranges, "total_lines": lines,
            "body_read_complete": ranges == [[1, lines]],
            "read_basis": "fresh_pinned_body_read", "prior_ref": None,
            "tests_executed": [], "test_limits": REMAINING[1],
        }

    rows = []
    for i, item in enumerate(inventory["paths"], 1):
        row = meta(item["path"])
        anchor = f"f{i:02}"
        assert f"## {anchor}\n" in review
        row.update({
            "partition": inventory["partition"],
            "scope_sha256": inventory["scope_sha256"],
            "disposition": STATUS, "primary_status": STATUS,
            "review_ref": f"{REL}/review.md#{anchor}",
            "supporting_ids": [f"s{n:02}" for n in LINKS[i]],
            "remaining": REMAINING, "adoption_approved": False,
            "prior_full_body_reused": False,
        })
        rows.append(row)
    assert len(rows) == 12 and sum(r["bytes"] for r in rows) == 86101
    supports = []
    for i, (path, ranges) in enumerate(SUPPORT, 1):
        row = meta(path, ranges)
        row.update({"id": f"s{i:02}", "counted_as_primary": False,
                    "review_ref": f"{REL}/review.md",
                    "disposition": "supporting_ranges_reviewed_execution_pending"})
        supports.append(row)
    assert not {r["path"] for r in rows} & {s["path"] for s in supports}
    save("files.json", rows)
    save("supporting.json", supports)
    save("remaining.json", {"primary_body_unread": [], "remaining": REMAINING,
                            "subsystem_complete": False, "adoption_approved": False})
    save("checkpoint.json", {
        "partition": inventory["partition"], "revision": REV,
        "scope_sha256": inventory["scope_sha256"],
        "primary_paths": 12, "primary_bytes": 86101, "primary_full_body_read": 12,
        "primary_full_body_reused": 0,
        "global_coverage_mutated": False,
        "prior_primary_inventory_basis": "Parent allocation: all 12 previously unreviewed; no global ledger modified.",
        "supporting_paths": len(supports),
        "supporting_full_body_read": sum(s["body_read_complete"] for s in supports),
        "supporting_partial_body_read": sum(not s["body_read_complete"] for s in supports),
        "supporting_reused": 0, "source_execution_count": 0,
        "source_import_probe_network_install_count": 0,
        "source_runtime_shared_coverage_changes": 0,
        "subsystem_complete": False, "adoption_approved": False,
        "review_sha256": sha((OUT / "review.md").read_bytes()),
        "files_sha256": sha((OUT / "files.json").read_bytes()),
        "supporting_sha256": sha((OUT / "supporting.json").read_bytes()),
        "manifest_sha256": sha((SOURCE / "manifest.json").read_bytes()),
        "remaining": REMAINING,
    })
    for p in OUT.iterdir():
        if p.is_file():
            raw = p.read_bytes()
            raw.decode("utf-8")
            assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf"), p
            if p.suffix == ".json":
                load(p)
    print(json.dumps({"metadata": "PASS", "primary": len(rows),
                      "supporting": len(supports), "upstream_execution": 0}))


if __name__ == "__main__":
    main()
