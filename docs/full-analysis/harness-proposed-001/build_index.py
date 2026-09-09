"""Record only review metadata; never import or execute reference code."""

import hashlib
import json
from pathlib import Path

OWN = Path(__file__).resolve().parent
ROOT = OWN.parents[2]
SOURCE = ROOT / ".runtime/absorption/sources/harness"
REV = "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
PREFIX = "docs/full-analysis/harness-proposed-001"
STATUS = "body_reviewed_call_test_trace_pending"
LIMIT = "No original execution/import/collection/probe/network/install/Claude or live access."
REMAINING = [
    "Full transitive caller/config/test closure is pending.",
    "Historical measurements and PASS labels are not current execution receipts.",
    "Actual Claude, license, model qualification, Windows/Linux/WSL and human acceptance pending.",
    "Current Zeus equivalence and adoption approval are not established.",
]
SUPPORT = {
    "s01": ("scripts/lib/derive_state.py", [(277, 426)]),
    "s02": ("scripts/cli/agentsmd_cmd.py", [(28, 83), (132, 180)]),
    "s03": ("scripts/lib/arming.py", [(314, 410), (419, 442), (574, 737), (884, 928)]),
    "s04": ("scripts/lib/paths.py", [(94, 121)]),
    "s05": ("scripts/cli/arming_cmd.py", [(64, 177)]),
    "s06": ("scripts/cron/note_archive.py", [(66, 180)]),
    "s07": ("scripts/lib/approval_proof.py", [(55, 136)]),
    "s08": ("scripts/cron/bus_tailer.py", [(1, 136)]),
    "s09": ("scripts/lib/debate_rules.py", [(89, 149), (255, 274)]),
    "s10": ("scripts/engine/debate.py", [(72, 103)]),
    "s11": ("scripts/handlers/pre_tool/write_boundary.py", [(706, 770), (924, 1102)]),
    "s12": ("scripts/engine/sandbox.py", [(89, 161)]),
    "s15": ("scripts/cron/reachability.py", [(111, 165), (216, 258), (274, 313)]),
    "s16": ("scripts/cron/l2_driver.py", [(512, 559), (716, 832), (1204, 1244), (1277, 1345)]),
    "s17": ("scripts/cron/commit_scope.py", [(1, 140)]),
    "s18": ("scripts/cli/spiral_cmd.py", [(54, 79), (133, 177), (266, 290), (309, 384)]),
    "s19": ("pipelines/core.yaml", [(477, 489)]),
    "s20": ("pipelines/youtube-note.yaml", [(47, 108)]),
    "s21": ("scripts/cron/youtube_collector.py", [(130, 139)]),
    "s22": ("agents/design-critic.md", [(1, 20)]),
    "s23": ("agents/critic.md", [(1, 19)]),
    "s24": ("scripts/handlers/registry.py", [(38, 61)]),
    "s25": ("scripts/handlers/dispatch.sh", [(1, 25)]),
    "s28": ("tests/contract/test_acceptance_coverage_contract.py", [(182, 294)]),
    "s29": ("tests/contract/test_arming_freshness_contract.py", [(143, 196)]),
    "s30": ("tests/contract/test_bus_watermark_contract.py", [(196, 261)]),
    "s31": ("tests/integration/test_debate_smoke.py", [(72, 102)]),
    "s32": ("scripts/validators/harness_lint.py", [(1419, 1447), (2031, 2071)]),
    "s33": ("scripts/cli/health_cmd.py", [(603, 629)]),
    "s34": ("scripts/handlers/dispatch.py", [(1, 70), (197, 280)]),
    "s35": (".mcp.json", [(1, 8)]),
    "s36": ("scripts/cli/debate_cmd.py", [(64, 94)]),
    "s37": (".claude/settings.json", [(29, 40)]),
    "s38": ("config/policy/write-boundary.json", [(32, 53), (96, 109), (145, 158)]),
    "s39": ("tests/contract/test_bus_tailer_contract.py", [(56, 87)]),
}
MAP = [
    ["s01", "s28"], ["s33", "s34"], ["s02", "s32"], ["s03", "s07"],
    ["s32"], ["s06", "s17", "s20"], ["s03", "s16"], ["s05", "s18"],
    ["s03", "s05", "s16", "s18", "s29"],
    ["s11", "s24", "s34", "s37", "s38"], ["s11", "s38"],
    ["s19", "s22", "s35"], ["s09", "s10", "s23", "s31", "s36", "s38"],
    ["s08", "s16", "s30", "s39"], ["s15", "s20", "s21"],
    ["s04", "s11", "s12", "s25"], [],
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, value):
    (OWN / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def main():
    manifest_raw = (SOURCE / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["revision"] == REV
    index = {r["path"]: r for r in manifest["inventory"]}
    inventory = json.loads((OWN / "inventory.json").read_bytes())
    prior = json.loads((OWN / "prior-ledger.json").read_bytes())
    review = (OWN / "review.md").read_text(encoding="utf-8")

    def identity(path, ranges):
        raw = (SOURCE / "pinned" / path).read_bytes()
        lines = raw.decode("utf-8").splitlines()
        record = index[path]
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert blob == record["object"] and len(raw) == record["bytes"]
        actual_sha = sha(raw)
        expected_sha = record.get("snapshot_sha256")
        assert expected_sha is None or expected_sha == actual_sha
        assert all(1 <= a <= b <= len(lines) for a, b in ranges)
        return {
            "source": "harness", "path": path, "revision": REV,
            "bytes": len(raw), "git_blob": blob, "raw_git_blob_status": "matched",
            "pinned_sha256": actual_sha, "observed_sha256": None,
            "manifest_sha256": expected_sha,
            "manifest_sha256_status": "matched" if expected_sha else "absent",
            "line_count": len(lines), "read_ranges": ranges,
            "read_kind": "fresh_full" if ranges == [(1, len(lines))] else "fresh_partial",
            "tests_executed": [], "test_limits": LIMIT,
        }

    support = []
    for sid, (path, ranges) in SUPPORT.items():
        record = identity(path, ranges)
        anchors = [f"f{i:02}" for i, refs in enumerate(MAP, 1) if sid in refs]
        record.update({"id": sid, "role": "supporting_not_primary",
                       "review_refs": [f"{PREFIX}/review.md#{a}" for a in anchors],
                       "prior_full_body_reused": False,
                       "remaining": "Unlisted body and transitive dependencies are not claimed read."})
        support.append(record)
    files = []
    for i, item in enumerate(inventory["paths"], 1):
        path = item["path"]
        raw = (SOURCE / "pinned" / path).read_bytes()
        json.loads(raw)
        record = identity(path, [(1, len(raw.decode("utf-8").splitlines()))])
        row = next(r for r in prior["rows"] if r["row"]["path"] == path)
        assert row["row"]["disposition"] == "unreviewed"
        assert row["row"]["pinned_sha256"] == record["pinned_sha256"]
        anchor = f"f{i:02}"
        rationale = review.split(f"## {anchor}\n", 1)[1].split("\n## ", 1)[0].strip()
        record.update({
            "partition": inventory["partition"], "scope_sha256": inventory["scope_sha256"],
            "primary_status": STATUS, "disposition": STATUS,
            "review_ref": f"{PREFIX}/review.md#{anchor}",
            "semantic_rationale": rationale, "supporting_ids": MAP[i - 1],
            "test_role": "proposal_and_historical_claims_not_current_test_execution",
            "denominator_basis": "All primary JSON lines freshly read; supporting ranges separate.",
            "source_executed": False, "prior_full_body_reused": False,
            "prior_ledger_row_index": row["row_index"],
            "prior_ledger_sha256": prior["ledger_sha256"],
            "prior_primary_disposition": row["row"]["disposition"],
            "prior_ledger_record_ref": f"{PREFIX}/prior-ledger.json",
            "remaining": REMAINING, "adoption_approved": False,
        })
        files.append(record)
    assert len(files) == 17 and sum(r["bytes"] for r in files) == 182520
    write("files.json", files)
    write("supporting.json", support)
    write("remaining.json", {
        "primary_unread": [], "limits": REMAINING,
        "unavailable": ["Harness pinned config/runtime.yaml is not captured.",
                        "No pinned nfx-kr SUT read; catalog proposal remains unverified.",
                        "No fresh architecture-view bodies read for f05."],
        "source_operations_executed": 0,
    })
    write("checkpoint.json", {
        "partition": inventory["partition"], "scope_sha256": inventory["scope_sha256"],
        "revision": REV, "primary_full_fresh": len(files), "primary_bytes": 182520,
        "primary_prior_unreviewed": 17, "primary_prior_reused": 0,
        "supporting_unique_paths": len(support),
        "supporting_full": sum(r["read_kind"] == "fresh_full" for r in support),
        "supporting_partial": sum(r["read_kind"] == "fresh_partial" for r in support),
        "source_test_bodies_partial": sum(r["path"].startswith("tests/") for r in support),
        "source_test_bodies_full": 0, "source_operations_executed": 0,
        "status": "bounded_primary_body_review_complete_supporting_closure_pending",
        "full_closure": False, "actual_claude_complete": False,
        "platform_validated": False, "model_qualified": False,
        "human_acceptance": False, "license_closed": False, "adoption_approved": False,
        "manifest_sha256": sha(manifest_raw), "prior_ledger_sha256": prior["ledger_sha256"],
        "files_sha256": sha((OWN / "files.json").read_bytes()),
        "supporting_sha256": sha((OWN / "supporting.json").read_bytes()),
        "review_sha256": sha((OWN / "review.md").read_bytes()),
    })
    # Normalize only our captured metadata, never original source or shared ledger.
    write("inventory.json", inventory)
    write("prior-ledger.json", prior)
    print("Recorded 17 primary bodies; supporting paths:", len(support))


if __name__ == "__main__":
    main()
