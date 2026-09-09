"""Record metadata only; never import or execute pinned modules."""

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
    ("scripts/handlers/prompt/skill_match.py", [[267, 308], [410, 445], [500, 522]]),
    ("scripts/cli/surgery.py", [[191, 249]]),
    ("scripts/cli/team_policy_check.py", [[147, 249]]),
    ("scripts/cli/milestone_step.py", [[337, 381]]),
    ("scripts/cli/greenfield_spec_emit.py", [[83, 119]]),
    ("scripts/handlers/session/init.py", [[217, 237]]),
    ("scripts/cli/observe.py", [[74, 84], [155, 181]]),
    ("scripts/lib/calibration/threshold_proposer.py", [[49, 76], [154, 183]]),
    ("scripts/lib/calibration/threshold_registry.py", [[29, 44], [70, 109], [117, 149]]),
    ("scripts/tests/test_stub_faker_mutation.py", [[1, 160]]),
    ("scripts/tests/test_team_policy.py", [[292, 331]]),
    ("scripts/tests/test_team_runtime.py", [[89, 146]]),
    ("scripts/handlers/post_tool/agent_invocation_audit.py", [[175, 218]]),
    ("scripts/handlers/prompt/context_load.py", [[151, 169]]),
    ("scripts/handlers/post_tool/reviewer.py", [[568, 587]]),
    ("scripts/tests/test_staging_guard.py", [[1, 128]]),
    ("scripts/tests/test_testgen.py", [[1, 123]]),
    ("scripts/tests/test_skill_surgery.py", [[1, 118]]),
    ("skills/_pipeline/overlays/java.overlay.yaml", [[1, 120]]),
    ("scripts/cli/spec_bundle_emit.py", [[83, 142]]),
    ("scripts/lib/ensemble_evaluator.py", [[284, 296]]),
    ("scripts/lib/quota_tracker.py", [[1, 158]]),
    ("scripts/lib/psmux.py", [[1, 340]]),
]
LINKS = {
    1: [1, 2, 18], 2: [1], 3: [5, 17], 4: [20], 5: [16], 6: [15],
    7: [22], 8: [19, 17], 9: [10, 19], 10: [13], 11: [12],
    12: [3, 11, 21], 13: [3, 12, 23], 14: [12], 15: [1], 16: [14],
    17: [13], 18: [1, 6], 19: [5, 17, 19], 20: [1, 9],
    21: [8, 9], 22: [4], 23: [7],
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def main():
    manifest_path = SOURCE / "manifest.json"
    manifest = load(manifest_path)
    assert manifest["revision"] == REV
    entries = {x["path"]: x for x in manifest["inventory"]}
    inventory = load(OUT / "inventory.json")
    part = next(x for x in load(ROOT / "docs/full-analysis/partitions.json")
                if x.get("partition") == inventory["partition"])
    assert part == inventory
    review = (OUT / "review.md").read_text(encoding="utf-8")

    def meta(path, ranges=None):
        raw = (SOURCE / "pinned" / path).read_bytes()
        lines = len(raw.decode("utf-8").splitlines())
        ranges = ranges or [[1, lines]]
        entry = entries[path]
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        digest = sha(raw)
        expected = entry.get("snapshot_sha256")
        assert blob == entry["object"] and len(raw) == entry["bytes"], path
        assert expected is None or expected == digest, path
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
        }

    def bind(row, ledger_rel):
        ledger = ROOT / ledger_rel
        old = next(x for x in load(ledger) if x.get("source") == "baldrix"
                   and x["path"] == row["path"])
        for key in ("revision", "pinned_sha256", "git_blob"):
            assert old[key] == row[key], (row["path"], key)
        assert old.get("body_read_complete") or old.get("read_extent") == "full_body"
        prior_review = ROOT / old["review_ref"].split("#")[0]
        return {
            "ledger": ledger_rel, "ledger_sha256": sha(ledger.read_bytes()),
            "row": old, "review_ref": old["review_ref"],
            "review_sha256": sha(prior_review.read_bytes()),
            "same_revision_raw_sha_git_blob": True,
            "bound_full_range": [[1, row["total_lines"]]],
            "new_primary_coverage": False,
        }

    supports = []
    for i, (path, ranges) in enumerate(SUPPORT, 1):
        row = meta(path, ranges)
        row.update(id=f"s{i:02}", counted_as_primary=False, tests_executed=[])
        if i >= 22:
            row["read_basis"] = "prior_full_body_same_bytes_reused_not_fresh"
            row["prior_ref"] = bind(row, "docs/full-analysis/baldrix-lib-006/files.json")
        supports.append(row)
    rows = []
    for i, item in enumerate(inventory["paths"], 1):
        row = meta(item["path"])
        anchor = f"f{i:02}"
        assert f'id="{anchor}"' in review
        row.update(
            partition=inventory["partition"], partition_scope_sha256=inventory["scope_sha256"],
            disposition=STATUS, primary_status=STATUS,
            review_ref=f"{REL}/review.md#{anchor}",
            supporting_ids=[f"s{n:02}" for n in LINKS[i]],
            tests_executed=[],
            test_limits="Static bodies/oracles only; upstream import/execution/test/probe/network/install zero.",
            tests_not_run=["all upstream tests", "actual host and model behavior"],
            remaining=["full caller/config/test closure", "actual Claude", "license", "OS validation",
                       "model qualification", "human acceptance", "Zeus adoption"],
            adoption_approved=False, prior_primary=None,
        )
        if i in (2, 15, 21):
            row["prior_primary"] = bind(row, "docs/full-analysis/baldrix-skill-routing-runtime/files.json")
            row["prior_primary"]["fresh_read_this_task"] = True
        rows.append(row)
    assert len(rows) == 23 and sum(x["bytes"] for x in rows) == 196126
    assert not ({x["path"] for x in rows} & {x["path"] for x in supports})
    save("files.json", rows)
    save("supporting.json", supports)
    save("checkpoint.json", {
        "partition": inventory["partition"], "revision": REV,
        "scope_sha256": inventory["scope_sha256"], "primary_count": 23, "primary_bytes": 196126,
        "primary_full_body_read": 23, "primary_body_pending": 0,
        "primary_fresh_body_read": 23, "prior_primary_overlap": 3,
        "new_primary_paths_relative_to_prior_ledger": 20,
        "supporting_count": 23, "supporting_fresh_full": 1, "supporting_fresh_partial": 20,
        "supporting_prior_full_reused": 2, "upstream_execution": 0, "upstream_import": 0,
        "upstream_tests": 0, "probes": 0, "network": 0, "install": 0,
        "full_semantic_call_test_closure": False, "actual_claude_complete": False,
        "license_complete": False, "platform_validation_complete": False,
        "model_qualification_complete": False, "human_acceptance_complete": False,
        "adoption_approved": False, "checkpoint_complete": True,
        "metadata_sha_blob_size_ranges_refs": "passed",
        "manifest_sha256": sha(manifest_path.read_bytes()),
        "review_sha256": sha((OUT / "review.md").read_bytes()), "own_ruff": "see validation.json",
    })
    for path in OUT.iterdir():
        if path.is_file() and path.suffix in (".json", ".py", ".md"):
            raw = path.read_bytes()
            raw.decode("utf-8")
            assert b"\r\n" not in raw, path
            if path.suffix == ".json":
                json.loads(raw)
    print("metadata PASS: 23 primary, 23 supporting; SHA/blob/bytes/ranges/refs/prior bindings/UTF-8 LF")


if __name__ == "__main__":
    main()
