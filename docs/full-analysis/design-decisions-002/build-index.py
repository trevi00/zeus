"""Reviewer metadata only. Never imports or runs captured source code."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/full-analysis/design-decisions-002"
SOURCES = ROOT / ".runtime/absorption/sources"
STATUS = "body_reviewed_call_test_trace_pending"


def read_json(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(b):
    return hashlib.sha256(b).hexdigest()


MANIFESTS = {s: read_json(SOURCES / s / "manifest.json") for s in ("harness", "harness-design")}
INDEX = {s: {x["path"]: x for x in m["inventory"]} for s, m in MANIFESTS.items()}
inventory = read_json(OUT / "inventory.json")[0]
review = (OUT / "review.md").read_text(encoding="utf-8")

# These are the exact line intervals displayed and read during this partition.
# Whole-file hashes identify the bytes, but do not imply all lines were read.
ranges = [
    ("scripts/lib/derive_state.py", [[54, 275]]),
    ("scripts/engine/tick.py", [[60, 200]]),
    ("scripts/engine/select_ready.py", [[1, 99]]),
    ("scripts/lib/preconditions.py", [[1, 100]]),
    ("scripts/engine/staleness.py", [[1, 46]]),
    ("scripts/lib/repair_tier.py", [[1, 82]]),
    ("scripts/handlers/stop/subagent_harvest.py", [[1, 154]]),
    ("scripts/cron/l2_driver.py", [[598, 780], [1310, 1347], [1420, 1450]]),
    ("scripts/engine/sandbox.py", [[155, 265]]),
    ("scripts/cli/sandbox_cmd.py", [[33, 69]]),
    ("scripts/engine/workup.py", [[178, 225]]),
    ("tests/contract/test_arm_reopens_cycle_contract.py", [[1, 282]]),
    ("scripts/cli/cycle_cmd.py", [[1, 118]]),
    ("scripts/engine/circuit.py", [[85, 216]]),
    ("scripts/lib/completion_line.py", [[1, 87]]),
    ("scripts/lib/decomposition.py", [[1, 188]]),
    ("scripts/lib/ownership_events.py", [[1, 74]]),
    ("scripts/engine/counterfactual.py", [[1, 109]]),
    ("scripts/validators/harness_lint.py", [[280, 335], [395, 537]]),
    ("scripts/lib/seams.py", [[112, 225]]),
    ("scripts/lib/code_context.py", [[1, 128]]),
    ("config/profile.yaml", [[1, 7]]),
    ("agents/design-critic.md", [[1, 20]]),
    ("scripts/engine/gate_runner.py", [[1, 179]]),
]
supporting = []
for path, intervals in ranges:
    raw = (SOURCES / "harness/pinned" / path).read_bytes()
    lines = raw.decode("utf-8").splitlines()
    assert all(1 <= a <= b <= len(lines) for a, b in intervals), path
    item = INDEX["harness"][path]
    h = sha(raw)
    assert h == item["snapshot_sha256"], path
    supporting.append({"source": "harness", "revision": MANIFESTS["harness"]["revision"],
        "path": path, "pinned_sha256": h, "git_blob": item["object"],
        "read_ranges_inclusive": intervals, "total_lines": len(lines),
        "read_extent": "full_body" if intervals == [[1, len(lines)]] else "selected_ranges_only",
        "tests_executed": [], "authority": "static_source_read_not_execution"})
for path in ("src/codex_harness/domain/sdd.py", "docs/zeus/full-delivery-scope.md"):
    raw = (ROOT / path).read_bytes()
    supporting.append({"source": "zeus", "path": path, "observed_sha256": sha(raw),
        "read_ranges_inclusive": [[1, len(raw.decode("utf-8").splitlines())]],
        "read_extent": "full_body", "tests_executed": [],
        "authority": "local_comparison_read_not_execution_or_whole_repo_claim"})
save("supporting.json", supporting)

maps = {
    "D-032": (["scripts/engine/counterfactual.py", "scripts/engine/gate_runner.py"],
        "probe CLI/PARTIAL 입력 계약·BLINDSPOTS 갱신·checks 부작용·격리 실행"),
    "D-033": (["scripts/lib/repair_tier.py", "scripts/engine/gate_runner.py", "scripts/lib/derive_state.py"],
        "tick 전체 tier 소비·reflector/curator·접힘/철회 등가성과 실제 수리 실행"),
    "D-035": (["scripts/lib/preconditions.py", "scripts/engine/staleness.py", "scripts/engine/tick.py", "scripts/engine/gate_runner.py"],
        "전제 기록의 시점 결속·선언 삭제·compaction/retraction·환경 전체 및 실제 재검증"),
    "D-036": (["scripts/lib/seams.py", "scripts/engine/tick.py"],
        "promotion_readiness·effective blocking caller/config·전체 debate 종료 및 실전 승격"),
    "D-037": (["scripts/lib/completion_line.py", "scripts/lib/decomposition.py", "scripts/lib/preconditions.py"],
        "reject 계수·패널 독립성·Jaccard·recall 인덱스/성능 및 의미 검수"),
    "D-038": (["scripts/validators/harness_lint.py"],
        "cohesion 계산/발의 writer·실제 상시 로드 소비자·통지 및 threshold 검증"),
    "D-039": (["config/profile.yaml", "scripts/cron/l2_driver.py"],
        "state_dir 소비자 전수·guardian 다중 감시·전역 예산/lease·환경 전파·운영 실행"),
    "D-040": (["scripts/handlers/stop/subagent_harvest.py", "scripts/lib/decomposition.py", "config/profile.yaml"],
        "훅 registry/실제 플랫폼 전파·독립 세션 receipt·Redis 현재 배포·수거 재실행"),
    "D-041": (["scripts/validators/harness_lint.py"],
        "contracts.yaml 전체 재대조·guardian 계약 7파일 producer/consumer·freshness·실제 probe"),
    "D-042": (["scripts/lib/ownership_events.py", "scripts/validators/harness_lint.py"],
        "incident writer·vitals·깨우기 dispatcher·계보/귀속 인증·실제 무응답 검증"),
    "D-043": (["scripts/handlers/stop/subagent_harvest.py", "scripts/cron/l2_driver.py"],
        "전용 Java/fleet 추출기·write_boundary/seeding·원본 outpos 레포·축별 smoke 전체"),
    "D-044": (["scripts/engine/workup.py"],
        "machine_sections 전체 추출기·workup CLI/test·사람 착수 검수·분석 버전 관리"),
    "D-045": (["scripts/engine/tick.py", "scripts/engine/select_ready.py", "scripts/engine/circuit.py", "scripts/lib/derive_state.py"],
        "backlog/승인 writer·전체 spawn/watchdog/stuck·세션 심박·P3 격리·실제 사람 인수"),
    "D-046": (["scripts/engine/sandbox.py", "scripts/cli/sandbox_cmd.py", "scripts/cron/l2_driver.py"],
        "autoheart judge/promote 및 기준 앵커 전체·compaction·모든 env 경로·격리 승격 실행"),
    "D-047": (["scripts/lib/code_context.py", "scripts/validators/harness_lint.py"],
        "context 선언 전부·정적 추출 밖 import·전체 lint caller 및 실행"),
    "D-048": ([], "mitgrim schema/renderer/pipeline/completion/실행·사람 렌더 검수 전부"),
    "D-049": (["agents/design-critic.md", "scripts/engine/gate_runner.py"],
        "7기둥 skill·시딩/실제 독립 judge spawn·인증된 판정·실렌더/실기기"),
    "D-050": (["scripts/lib/derive_state.py", "scripts/engine/tick.py", "scripts/engine/select_ready.py",
        "scripts/cli/cycle_cmd.py", "scripts/engine/circuit.py", "scripts/cron/l2_driver.py",
        "tests/contract/test_arm_reopens_cycle_contract.py"],
        "전체 retries/ERROR 이력·candidate별 circuit·멱등키 writer/reader·compaction·표면 및 실제 실행"),
    "D-5b": (["scripts/lib/decomposition.py", "scripts/handlers/stop/subagent_harvest.py"],
        "depth hook/실제 메인 spawn·모델 자격/성능·독립 팀 실행 및 검증"),
}
rows = []
for entry in inventory["paths"]:
    path = entry["path"]
    key = next(k for k in maps if Path(path).name.startswith(k + "-"))
    raw = (SOURCES / "harness-design/pinned" / path).read_bytes()
    item = INDEX["harness-design"][path]
    h = sha(raw)
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert h == item["snapshot_sha256"] and blob == item["object"] and len(raw) == item["bytes"]
    heading = "## " + key + "\n"
    assert heading in review
    section = review.split(heading, 1)[1].split("\n## ", 1)[0].strip()
    row = {"source": "harness-design", "revision": MANIFESTS["harness-design"]["revision"],
        "path": path, "git_blob": blob, "bytes": len(raw), "pinned_sha256": h,
        "observed_sha256": None, "disposition": STATUS,
        "review_ref": "docs/full-analysis/design-decisions-002/review.md#" + key.lower(),
        "body_read": {"extent": "full", "lines": len(raw.decode("utf-8").splitlines())},
        "tests_executed": [],
        "test_limits": "원문·주석의 PASS/수치/실험은 역사적 주장이다. 이번 원본 테스트·프로브 실행 0회. supporting의 표시 구간만 정적 독해했다.",
        "remaining": [maps[key][1], "실행·독립 공동 검토 및 Zeus 채택/구현/검증"],
        "supporting_paths_actually_read": maps[key][0],
        "supporting_ranges_ref": "docs/full-analysis/design-decisions-002/supporting.json",
        "source_instructions": "data_only_no_inherited_authority",
        "adoption_status": "not_approved_not_incorporated",
        "findings": section}
    if key == "D-050":
        old_rows = read_json(ROOT / "docs/full-analysis/design-canon/files.json")
        old = next(x for x in old_rows if x["path"] == path)
        assert old["pinned_sha256"] == h and old["disposition"] == STATUS
        row["duplicate_review"] = {"metadata_only_read": "docs/full-analysis/design-canon/files.json",
            "same_sha256": True, "prior_sha256": old["pinned_sha256"],
            "prior_disposition": old["disposition"], "primary_status_unchanged": True,
            "prior_semantic_report_read": False, "no_duplicate_adoption_credit": True}
    rows.append(row)
assert len(rows) == 19 and sum(x["bytes"] for x in rows) == 103013
assert len({x["path"] for x in rows}) == 19
assert all(x["path"] in {s["path"] for s in supporting} for values in maps.values() for x in [{"path": p} for p in values[0]])
save("files.json", rows)
save("remaining.json", {"partition": inventory["partition"], "body_reviewed": 19,
    "primary_status": STATUS, "current_source_tests_executed": 0,
    "adoption": "not_approved_not_incorporated", "unreviewed_primary_bodies": [],
    "per_file": [{"path": x["path"], "remaining": x["remaining"]} for x in rows],
    "global_limits": ["외부 논문·링크 본문이나 현행 사실은 이번에 검증하지 않았다. 인용은 원문 주장으로 보존한다.",
        "다른 보고서의 PASS나 이전 Windows/Linux CI는 이 원본 실행 증거가 아니다.",
        "supporting 전체 수집/해시는 전문 독해를 뜻하지 않는다. 구간 밖 caller/config/test는 미추적이다.",
        "원본 쓰기·실행·자동 보안 검사 중단 probe의 우회 재시도 없이 정적 검토만 수행했다."]})
save("validation.json", {"kind": "reviewer_metadata_validation_not_source_test",
    "partition": inventory["partition"], "scope_sha256": inventory["scope_sha256"],
    "path_count": 19, "body_review_count": 19, "bytes": 103013,
    "manifest_sha256_matches": 19, "git_blob_matches": 19,
    "review_heading_matches": 19, "supporting_files": len(supporting),
    "source_tests_executed": 0, "executed_foreign_commands": 0,
    "source_revisions": {s: m["revision"] for s, m in MANIFESTS.items()},
    "primary_status_counts": {STATUS: 19},
    "conclusion": "본문 검토와 해시/목록 대조만 완료. 전체 추적·실행·흡수 완료 아님."})
print(json.dumps({"primary_files": len(rows), "supporting_files": len(supporting),
                  "source_tests_executed": 0, "sha256_and_git_blob_matches": len(rows)}))
