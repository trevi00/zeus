"""Record a bounded static review; never import or execute upstream source."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/harness"
REVISION = "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
PARTITION = "harness:scripts/cli:002"
REF = "docs/full-analysis/harness-cli-002/review.md"
NOTES = {
    "error_contract_cmd": ("C02", "AST 오류 계약 required/conditional·문서 채점. 이름/분기/접두/모집단 근사와 불능을 실제 인수와 분리.",
                           ["tests/unit/test_error_contract.py"], ["pipelines exact-name search: no hits; indirect consumers unreviewed"]),
    "evolve_cmd": ("C03", "계보 open/step/status. --executed 자기주장·grade 비검증·frozen 공백·수렴/세대/lease 제한.",
                   ["tests/integration/test_evolve_smoke.py"], ["scripts/engine/evolve.py:185-274"]),
    "extractor_canary_cmd": ("C04", "알려진 합성 답과 6종 본문 독립 재계수. 실제 HEAD/후보 게이트·DEFER 방어, OS 실행 격리/전체 의미 증명 아님.",
                             ["tests/contract/test_extractor_canary_contract.py"], ["scripts/cli/autoheart_cmd.py:768-817,850-921", "scripts/validators/harness_lint.py:1526-1567"]),
    "fleet_contracts_cmd": ("C05", "정적 atlas/ws/fanout 관찰; exit0≠배포 계약. 중복 키·서버 인자·top 제한과 --type --json 출력 경계.",
                            ["tests/contract/test_fleet_contracts_smoke.py"], ["scripts/engine/fleet_contracts.py:286-409"]),
    "fleet_status_cmd": ("C06", "PG projection·DDL·근사 done, feed 일부손상/전역시각 watermark/JSON후텍스트. 사람/큐 watermark는 별개.",
                         ["tests/contract/test_research_digest_contract.py", "tests/integration/test_cli_wrappers_smoke.py"], ["scripts/engine/projection_pg.py:1-67", "scripts/lib/research_digest.py:51-109", "brain/spikes/harness_board.py:324-343"]),
    "gate_dump_cmd": ("C07", "실제 로더 정규화 분모·enum·오류를 보고, 0방출 거부. lint는 파생 인자 결손을 유예; 전체실행가능 승인 아님.",
                      ["tests/contract/test_gate_dump_contract.py"], ["scripts/engine/pipeline_loader.py:199-256", "scripts/validators/harness_lint.py:1700-1800"]),
    "health_cmd": ("C08", "quick의 HUD spawn/쓰기, 부분 strict, 반복 read·형상/시각 오류, role_delivery JSON 부재와 고정 state 경로.",
                   ["tests/integration/test_health_smoke.py", "tests/contract/test_health_alerts_surface_contract.py", "tests/contract/test_latency_consumer_contract.py"], [".claude/commands/health.md:1-12", "scripts/validators/settings_wiring.py:132-211,232-280", "brain/spikes/harness_board.py:346-364", "scripts/cron/latency_gate.py:60-196"]),
    "hollow_cmd": ("C07", "문자열 단언 파일별 래칫·0분모 방어. basename 충돌·동일개수 교체·구문실패/해소범위·WEAK/ABSENT 비차단.",
                   ["tests/contract/test_hollow_audit.py"], ["scripts/lib/hollow_audit.py:56-105,134-166", "ontology/contracts.yaml:498-522"]),
    "hook_latency_probe": ("C09", "실 spawn 진단·temp state와 latency 직접쓰기. pinned bash 불일치·single event None 출력·repeat/timeout·시각불능 갱신누락.",
                           ["tests/integration/test_health_smoke.py", "tests/contract/test_latency_consumer_contract.py"], ["scripts/cron/l2_driver.py:307-341,1770-1803", "scripts/cron/latency_gate.py:60-196", ".claude/commands/health.md:1-12"]),
    "hud": ("C10", "ANSI/ASCII·tail·원자마커. 마커≠TUI/렌더/사람확인; P/F사건수·lease상태·git표시·추정토큰의 범위.",
            ["tests/integration/test_hud_smoke.py"], ["scripts/handlers/hud_launcher.sh:1-12", ".claude/settings.json:1-6", "scripts/validators/settings_wiring.py:162-211"]),
    "incident_cmd": ("C11", "장애 스키마·append lock·재개 이력. resolve note 공백/근거·fp 충돌·read/check/append 경합·손상 줄 건너뜀.",
                     ["tests/integration/test_backlog_smoke.py"], ["scripts/lib/ownership_events.py:1-44", "scripts/lib/backlog.py:26-45", "scripts/lib/ledger.py:214-302"]),
}
SUPPORT = {
    "scripts/engine/evolve.py": [[185, 274]],
    "scripts/engine/projection_pg.py": [[1, 67]],
    "scripts/lib/research_digest.py": [[51, 109]],
    "scripts/lib/ownership_events.py": [[1, 44]],
    "scripts/lib/backlog.py": [[26, 45]],
    "scripts/handlers/hud_launcher.sh": [[1, 12]],
    "scripts/validators/settings_wiring.py": [[132, 211], [232, 280]],
    ".claude/commands/health.md": [[1, 12]],
    "scripts/cron/latency_gate.py": [[60, 196]],
    "scripts/cron/l2_driver.py": [[307, 341], [1770, 1803]],
    "scripts/cli/autoheart_cmd.py": [[768, 817], [850, 921]],
    "scripts/validators/harness_lint.py": [[1526, 1567], [1700, 1800]],
    "ontology/contracts.yaml": [[498, 522]],
    "scripts/engine/pipeline_loader.py": [[105, 167], [199, 256]],
    "config/policy/write-boundary.json": [[235, 252]],
    "tests/unit/test_error_contract.py": [[232, 336]],
    "tests/integration/test_evolve_smoke.py": [[118, 152]],
    "tests/integration/test_backlog_smoke.py": [[177, 211]],
    "tests/integration/test_health_smoke.py": [[102, 156], [210, 246]],
    "tests/contract/test_gate_dump_contract.py": [[110, 219]],
    "scripts/lib/ledger.py": [[214, 302], [417, 429]],
    "tests/contract/test_research_digest_contract.py": [[178, 235]],
    "tests/contract/test_hollow_audit.py": [[74, 148]],
    "tests/integration/test_hud_smoke.py": [[31, 79], [157, 189]],
    "tests/contract/test_fleet_contracts_smoke.py": [[91, 111], [146, 165], [228, 288]],
    "tests/contract/test_health_alerts_surface_contract.py": [[60, 143]],
    "tests/contract/test_latency_consumer_contract.py": [[257, 280]],
    "scripts/engine/fleet_contracts.py": [[286, 409]],
    "scripts/lib/hollow_audit.py": [[56, 105], [134, 166]],
    "scripts/cron/research_queue.py": [[31, 45], [74, 95]],
    "brain/spikes/harness_board.py": [[324, 371]],
    ".claude/settings.json": [[1, 6]],
    "tests/contract/test_extractor_canary_contract.py": [[83, 137], [234, 262]],
    "tests/integration/test_cli_wrappers_smoke.py": [[62, 79]],
}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def verified(path, *, require_snapshot=True):
    entry = inventory[path]
    raw = (SOURCE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert (blob, len(raw)) == (entry["object"], entry["bytes"])
    snapshot_sha = entry.get("snapshot_sha256")
    if require_snapshot:
        assert snapshot_sha is not None
    if snapshot_sha is not None:
        assert sha == snapshot_sha
    return {"source": "harness", "revision": REVISION, "path": path,
            "pinned_sha256": sha, "git_blob": blob, "bytes": len(raw),
            "hash_verification": "manifest_sha256_git_blob_bytes" if snapshot_sha else
            "manifest_git_blob_bytes_verified_sha256_newly_recorded",
            "manifest_snapshot_sha256_present": snapshot_sha is not None}


manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
assert manifest["revision"] == REVISION
inventory = {r["path"]: r for r in manifest["inventory"]}
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
partition = next(p for p in partitions if p["partition"] == PARTITION)
assert partition["scope_sha256"] == "66ee737c398fc778990cd88697ff6699bc0fcc06a7df6caeaa8a36603af4a178"
rows = []
for item in partition["paths"]:
    assert item["source"] == "harness"
    path = item["path"]
    row = verified(path)
    section, note, tests, trace = NOTES[Path(path).stem]
    lines = len((SOURCE / "pinned" / path).read_text(encoding="utf-8").splitlines())
    row.update({"partition": PARTITION, "disposition": "semantically_reviewed",
                "read_extent": "full_body", "line_ranges": [[1, lines]],
                "semantic_summary": note, "review_ref": REF,
                "finding_sections": ["C01", section],
                "caller_or_dependency_trace": trace,
                "tests_read_in_part": tests, "tests_executed": [],
                "test_limits": "원본 실행·설치·probe·기기 조작 0건. 읽은 구간과 테스트 선언을 실행 실적 또는 인수로 계산하지 않음.",
                "remaining": ["실제 Claude 독립 검수", "공식 자료·라이선스 검토",
                              "전체 consumer와 효과·OS별 격리 실행",
                              "실제 서비스/금융/사람 oracle 인수", "Zeus PG SSOT와 티켓 적응"],
                "adoption_status": "not_approved_not_incorporated"})
    rows.append(row)
assert len(rows) == len({r["path"] for r in rows}) == 11
assert sum(r["bytes"] for r in rows) == partition["bytes"] == 178390
write("files.json", rows)
support = []
for path, ranges in SUPPORT.items():
    row = verified(path, require_snapshot=False)
    n = len((SOURCE / "pinned" / path).read_text(encoding="utf-8").splitlines())
    assert all(1 <= a <= z <= n for a, z in ranges), (path, n)
    row.update({"line_ranges": ranges, "read_extent": "listed_line_ranges_only",
                "counted_in_partition_coverage": False, "tests_executed": []})
    support.append(row)
write("supporting-evidence.json", support)
write("checkpoint.json", {
    "source": "harness", "revision": REVISION, "partitions": [PARTITION],
    "scope_sha256": partition["scope_sha256"], "expected": 11, "full_body_reviewed": 11,
    "bytes_verified": 178390, "unreviewed_paths_in_partition": [],
    "tests_executed": [], "upstream_execution_count": 0,
    "blocked_probe_retried_or_bypassed": False, "subsystem_complete": False,
    "adoption_approved": False, "claude_independent_review": "pending",
    "status": "static_review_complete_execution_and_independent_review_pending", "review_ref": REF,
    "searches": [{"scope": ["pipelines"], "source": "harness-pinned",
                  "pattern": "fleet_contracts_cmd|error_contract_cmd", "matches": 0,
                  "limit": "Exact text search only; indirect callers not ruled out"}],
    "search_limits": "탐색 rg 출력 1회 잘림. 전문 coverage에 계산하지 않았고 보고에 쓰는 supporting 본문은 별도 구간으로 읽음. 전체 consumer 감사는 아님.",
    "deferred": ["Samsung 실기기", "Device Farm SDK/MCP/Replay", "Astra→Sol→Terra 실행 자격 증명"],
})
print(json.dumps({"reviewed": len(rows), "bytes_verified": sum(r["bytes"] for r in rows),
                  "supporting_files": len(support), "upstream_executions": 0}))
