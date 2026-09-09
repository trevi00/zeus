"""Record static review metadata without importing reference source."""

import hashlib
import json
from pathlib import Path

OWN = Path(__file__).resolve().parent
ROOT = OWN.parents[2]
PREFIX = OWN.relative_to(ROOT).as_posix()
REV = "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
LIMIT = "Original execution/import/collection/probe/network/install/Claude/live access: zero."
SUPPORT = [
    ("harness", "scripts/engine/cohesion.py", [(29, 125)], [2]),
    ("harness", "scripts/cli/cycle_cmd.py", [(1, 84)], [3]),
    ("harness", "scripts/cli/completion_cmd.py", [(1, 112)], [3]),
    ("harness", "scripts/lib/backlog.py", [(46, 80), (106, 159)], [3, 7]),
    ("harness", "scripts/engine/curator.py", [(90, 165), (285, 319)], [4]),
    ("harness", "scripts/lib/completion_line.py", [(1, 87)], [3]),
    ("guardian", "console.py", [(160, 228)], [5]),
    ("harness", "tests/contract/test_fleet_mount_boundary_contract.py", [(1, 121)], [6, 8]),
    ("harness", "scripts/lib/test_outcome.py", [(189, 253)], [8]),
    ("harness", "scripts/engine/sandbox.py", [(172, 397)], [13]),
    ("harness", "scripts/validators/harness_lint.py", [(375, 436), (1661, 1794)], [7, 9]),
    ("harness", "brain/spikes/board_publisher.py", [(84, 141)], [10]),
    ("harness", "agents/evaluator.md", [(1, 21)], [14]),
    ("harness", "infra/fleet/docker-compose.yml", [(105, 119), (202, 217)], [6]),
    ("baldrix", "scripts/lib/debate_convergence.py", [(34, 222)], [11]),
    ("harness", "scripts/cron/reachability.py", [(105, 187), (216, 258), (274, 313)], [1, 12]),
    ("harness", "scripts/cron/research_collector.py", [(78, 130)], [15]),
    ("harness", "scripts/cron/research_queue.py", [(98, 148)], [15]),
    ("harness", "scripts/lib/research_digest.py", [(1, 150)], [15]),
    ("harness", "scripts/engine/mutation.py", [(106, 149)], [13]),
    ("harness", "scripts/cli/suite_cmd.py", [(277, 341)], [13]),
    ("baldrix", "scripts/cli/debate_converge_check.py", [(62, 113)], [11]),
    ("baldrix", "scripts/tests/test_debate_convergence.py", [(164, 270)], [11]),
    ("harness", "tests/contract/test_research_collector_contract.py", [(42, 99)], [8, 15]),
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, value):
    (OWN / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def identity(source, path, ranges=None):
    base = ROOT / ".runtime/absorption/sources" / source
    manifest_raw = (base / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    record = next(r for r in manifest["inventory"] if r["path"] == path)
    raw = (base / "pinned" / path).read_bytes()
    lines = raw.decode("utf-8").splitlines()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert blob == record["object"] and len(raw) == record["bytes"]
    assert not record.get("snapshot_sha256") or record["snapshot_sha256"] == sha(raw)
    ranges = ranges or [(1, len(lines))]
    assert all(1 <= a <= b <= len(lines) for a, b in ranges)
    return {
        "source": source, "path": path, "revision": manifest["revision"],
        "git_blob": blob, "bytes": len(raw), "pinned_sha256": sha(raw),
        "observed_sha256": None, "manifest_file_sha256": sha(manifest_raw),
        "manifest_snapshot_sha256": record.get("snapshot_sha256"),
        "manifest_sha256_status": "matched" if record.get("snapshot_sha256") else "absent",
        "line_count": len(lines), "read_ranges": ranges,
        "read_kind": "fresh_full" if ranges == [(1, len(lines))] else "fresh_partial",
        "tests_executed": [], "test_limits": LIMIT,
    }


def main():
    inventory = json.loads((OWN / "inventory.json").read_bytes())
    prior = json.loads((OWN / "prior-ledger.json").read_bytes())
    review = (OWN / "review.md").read_text(encoding="utf-8")
    support = []
    for i, (source, path, ranges, refs) in enumerate(SUPPORT, 1):
        row = identity(source, path, ranges)
        row.update({"support_id": f"s{i:02}", "role": "supporting_not_primary",
                    "prior_reuse": False, "global_coverage_increment_claimed": False,
                    "review_refs": [f"{PREFIX}/review.md#f{n:02}" for n in refs]})
        support.append(row)
    files = []
    for i, item in enumerate(inventory["paths"], 1):
        row = identity(item["source"], item["path"])
        assert row["revision"] == REV
        old = next(r for r in prior["rows"] if r["row"]["path"] == row["path"])
        assert old["row"]["disposition"] == "unreviewed"
        assert old["row"]["git_blob"] == row["git_blob"]
        anchor = f"f{i:02}"
        body = review.split(f"## {anchor}\n\n", 1)[1].split("\n## ", 1)[0].strip()
        row.update({
            "partition": inventory["partition"], "scope_sha256": inventory["scope_sha256"],
            "status": "body_reviewed_call_test_trace_pending",
            "disposition": "body_reviewed_call_test_trace_pending",
            "review_ref": f"{PREFIX}/review.md#{anchor}", "semantic_rationale": body,
            "supporting_ids": [f"s{n:02}" for n, s in enumerate(SUPPORT, 1) if i in s[3]],
            "prior_ledger_path": prior["ledger_path"],
            "prior_ledger_sha256": prior["ledger_sha256"],
            "prior_row_index": old["row_index"], "prior_row": old["row"],
            "prior_row_sha256": sha(json.dumps(old["row"], sort_keys=True,
                                                ensure_ascii=False).encode()),
            "remaining": "Transitive call/test closure and original execution pending; see review.",
            "adoption_approved": False,
        })
        files.append(row)
    assert len(files) == 15 and sum(r["bytes"] for r in files) == 190115
    write("files.json", files)
    write("supporting.json", support)
    write("remaining.json", {
        "unread_primary": [], "full_transitive_closure": False,
        "original_executions": 0, "actual_claude": False, "license": False,
        "os_validated": False, "model_qualified": False, "human_acceptance": False,
        "adoption_approved": False,
        "unknowns": ["All resolution/authentication writers", "Guardian deployment and event writers",
                     "Full verifier ownership and test closure", "Evidence freshness failure cause",
                     "Card-to-spawn capabilities", "All feed consumers and external source bodies"],
    })
    for p in OWN.iterdir():
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            p.write_text("\n".join(s.rstrip() for s in text.splitlines()).rstrip() + "\n",
                         encoding="utf-8", newline="\n")
    write("checkpoint.json", {
        "partition": inventory["partition"], "scope_sha256": inventory["scope_sha256"],
        "primary_full_fresh": 15, "primary_bytes": 190115,
        "prior_unreviewed": 15, "supporting_unique_files": len(support),
        "supporting_full": sum(r["read_kind"] == "fresh_full" for r in support),
        "supporting_test_files": 3, "source_executions": 0,
        "full_closure": False, "actual_claude": False, "adoption_approved": False,
        "hashes": {n: sha((OWN / n).read_bytes()) for n in
                   ["files.json", "supporting.json", "review.md", "prior-ledger.json",
                    "inventory.json", "remaining.json", "build_index.py"]},
    })
    print("Recorded 15 primary files and 24 supporting files; original execution zero.")


if __name__ == "__main__":
    main()
