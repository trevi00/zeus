"""Generate receipts for completed static reads without loading upstream modules."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/harness"
REVISION = "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
PARTITION = "harness:scripts/engine:001"
REF = "docs/full-analysis/harness-engine-001/review.md"
NOTES = {
    "asset_gate": ("E04", "필수 키 존재·본문 4000자·휴리스틱 필터. 값 타입/진위/토큰 예산의 최종 경계는 아님.",
                   ["scripts/engine/curator.py", "scripts/engine/debate.py"], ["tests/integration/test_curator_smoke.py"]),
    "checks": ("E01", "8종 결과 정형화와 ERROR 구분. metric/trigger 종료 코드 미반영, shell/반복 전체 예산·실제 관측 귀속 공백.",
               ["scripts/engine/gate_runner.py", "scripts/engine/counterfactual.py"], ["tests/unit/test_checks_smoke.py"]),
    "circuit": ("E07", "stuck/fruitless·냉각·trial·storm. trial 시각 뒤 임의 PASS, 메타 초기화와 호출부 fail-open, 비용 직접 측정 유예.",
                ["scripts/cron/l2_driver.py"], ["tests/unit/test_circuit_smoke.py"]),
    "code_graph": ("E09", "Java tree-sitter 구조·메서드 추출. parse_errors는 오류 파일 수이며 심볼 참조·빌드 결과 아님.",
                   ["scripts/engine/graph_queries.py"], ["tests/unit/test_graph_smoke.py"]),
    "cohesion": ("E10", "git co-change/Jaccard 근사로 상시 로드 표면 분해 발의. 자동 분해 아님; 드라이버가 proposed와 notification에 연결.",
                 ["scripts/cron/l2_driver.py"], ["tests/integration/test_context_programming_smoke.py"]),
    "counterfactual": ("E08", "기준선·주입·복원 대조. 실제 target 직접 수정/고정 백업, ERROR도 LIVE 후보; 임시 복사 격리 주장과 다름. 미실행.",
                       ["scripts/cli/probe_cmd.py"], ["tests/integration/test_probe_smoke.py"]),
    "curator": ("E03", "해결 계보와 노트 수확·bake/pinned/lifecycle. 재수확 빈도가 재성공으로 누적되고 인과·프로젝트 키·혼합 digest 대기 공백.",
                ["scripts/cron/l2_driver.py"], ["tests/integration/test_curator_smoke.py", "tests/unit/test_golden_smoke.py"]),
    "debate": ("E06", "원장 수렴·비평/의심 보존·순차 재생. gen1 architect 단독 수렴, 패널 인증/동시 종결/카드 원자성은 미보장.",
               ["scripts/cli/debate_cmd.py", "scripts/lib/debate_rules.py", "scripts/lib/ledger.py"], ["tests/integration/test_debate_smoke.py"]),
    "endpoint_graph": ("E09", "동일 catalog/scope/parity로 문서·seam·필드 1-hop atlas. 같은 이름 JOIN은 의미나 실제 배포 영향의 완전 분석 아님.",
                       ["scripts/cli/endpoint_cmd.py"], ["tests/integration/test_endpoint_graph_smoke.py"]),
    "evolve": ("E05", "모호 표지/시그니처·동결·정체·세대. executed 입력이 성공 권위, lease 전 재독·종결/상한 후 호출·frozen 축소 공백.",
               ["scripts/cli/evolve_cmd.py", "scripts/lib/lease.py"], ["tests/integration/test_evolve_smoke.py"]),
    "fleet_contracts": ("E10", "Dart/C#/Spring/proto/WS/Kotlin/Intent 및 fanout 휴리스틱. 기본 atlas 범위와 함수 존재 구분; type 조회가 top 제한 후 검색.",
                        ["scripts/cli/fleet_contracts_cmd.py"], ["tests/contract/test_fleet_contracts_smoke.py"]),
    "gate_ratchet": ("E09", "과거 stage+statement 삭제와 명명 waiver. 같은 문장의 check/regex/threshold 변경은 검사하지 않으며 tick 예외는 fail-open.",
                     ["scripts/engine/tick.py"], ["tests/integration/test_gate_ratchet_smoke.py"]),
    "gate_runner": ("E02", "machine·외부 판정 합산, ERROR/PARTIAL 파킹과 cycle 철회. 소비자는 statement/hash/by 미대조, marker는 잠금 아님.",
                    ["scripts/cli/step_cmd.py", "scripts/engine/tick.py"], ["tests/integration/test_probe_smoke.py"]),
    "golden": ("E04", "명령·기대 결과 회귀. 0사례 gate=true, held-out 라우팅 분리와 접근 격리 구분, curator 갱신 후 검증 부재.",
               ["scripts/engine/curator.py", "scripts/cli/quality_cmd.py"], ["tests/unit/test_golden_smoke.py"]),
    "graph_queries": ("E09", "0건 방어·overlay ERROR·구조/문자열/소유/parity 판정. 파싱 오류 advisory, 모집단 제외·문턱·자동 승급 소실 경계.",
                      ["scripts/engine/checks.py", "scripts/engine/endpoint_graph.py"], ["tests/unit/test_graph_smoke.py"]),
    "ladder_probe": ("E08", "guardian 합성 조건 반전과 실물 형태 감사 분리. sibling/sys.executable, 실행 코드 미확인 progress 문자열 관측. 미실행.",
                     ["tests/integration/test_ladder_probe_smoke.py"], ["tests/integration/test_ladder_probe_smoke.py"]),
    "mirror": ("E09", "제한된 코드/앵커와 ref 존재로 KEEP/ABSENT/DROP. 주장 의미·행 실존은 미검증, 제목뿐 wiki/앵커0 ready 경계.",
               ["scripts/cli/mirror_cmd.py"], ["tests/integration/test_mirror_smoke.py"]),
    "mutation": ("E08", "HEAD worktree baseline/0suite 방어와 변이 측정. 후보 위치와 원문 첫 치환 불일치, 격리 경계·등가 변이; CLI는 하한 차단.",
                 ["scripts/cli/quality_cmd.py", "scripts/engine/sandbox.py"], ["tests/integration/test_mutation_baseline_smoke.py"]),
}
SUPPORT = {
    "scripts/cli/evolve_cmd.py": [[20, 78]],
    "scripts/cron/l2_driver.py": [[188, 254], [1724, 1765], [1966, 1984]],
    "scripts/cli/probe_cmd.py": [[25, 70]],
    "scripts/cli/quality_cmd.py": [[109, 174]],
    "scripts/cli/fleet_contracts_cmd.py": [[30, 130]],
    "scripts/cli/debate_cmd.py": [[45, 105]],
    "config/paths.yaml": [[1, 32]],
    "config/params.json": [[1, 19]],
    "scripts/lib/ledger.py": [[243, 303]],
    "scripts/lib/lease.py": [[57, 129]],
    "scripts/lib/debate_rules.py": [[63, 154]],
    "scripts/cli/step_cmd.py": [[451, 503]],
    "scripts/engine/tick.py": [[60, 163]],
    "scripts/engine/sandbox.py": [[172, 252]],
    "scripts/cli/endpoint_cmd.py": [[23, 62]],
    "tests/unit/test_checks_smoke.py": [[30, 145]],
    "tests/integration/test_curator_smoke.py": [[45, 158], [302, 335]],
    "tests/integration/test_evolve_smoke.py": [[45, 161]],
    "tests/unit/test_circuit_smoke.py": [[55, 135]],
    "tests/integration/test_debate_smoke.py": [[40, 135]],
    "tests/integration/test_probe_smoke.py": [[45, 82]],
    "tests/unit/test_golden_smoke.py": [[30, 77]],
    "tests/integration/test_mutation_baseline_smoke.py": [[185, 217]],
    "tests/integration/test_ladder_probe_smoke.py": [[28, 76]],
    "tests/integration/test_mirror_smoke.py": [[30, 100]],
    "tests/integration/test_context_programming_smoke.py": [[86, 116]],
    "tests/integration/test_gate_ratchet_smoke.py": [[30, 100]],
    "scripts/cli/mirror_cmd.py": [[24, 58]],
    "knowledge/golden/cases.yaml": [[1, 51]],
    "tests/unit/test_graph_smoke.py": [[26, 68], [127, 186]],
    "tests/integration/test_endpoint_graph_smoke.py": [[30, 120]],
    "tests/contract/test_fleet_contracts_smoke.py": [[31, 139]],
    "pipelines/core.yaml": [[58, 114], [432, 455]],
}
ZEUS = {
    "src/codex_harness/domain/model_routing.py": [[1, 39]],
    "src/codex_harness/domain/sdd.py": [[1, 42], [165, 202]],
    "src/codex_harness/adapters/store.py": [[1, 85]],
    "AGENTS.md": [[1, 17]],
}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def verified(path):
    src = manifest_by_path[path]
    raw = (SOURCE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert (sha, blob, len(raw)) == (src["snapshot_sha256"], src["object"], src["bytes"])
    return {"source": "harness", "revision": REVISION, "path": path,
            "pinned_sha256": sha, "git_blob": blob, "bytes": len(raw)}


manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
assert manifest["revision"] == REVISION
manifest_by_path = {r["path"]: r for r in manifest["inventory"]}
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
partition = next(p for p in partitions if p["partition"] == PARTITION)
rows = []
for item in partition["paths"]:
    path = item["path"]
    row = verified(path)
    section, note, callers, tests = NOTES[Path(path).stem]
    row.update({"partition": PARTITION, "disposition": "semantically_reviewed",
                "read_extent": "full_body", "semantic_summary": note,
                "review_ref": REF, "finding_sections": [section],
                "caller_or_dependency_trace": callers, "tests_read_in_part": tests,
                "tests_executed": [],
                "test_limits": "원본 실행·설치·probe·기기 조작 0건. 기존 테스트의 읽은 구간만 기록하며 실행 성공이나 결함 재현을 주장하지 않음.",
                "remaining": ["실제 Claude 독립 교차 검수", "안전한 격리/권한 경계 설계",
                              "기존 테스트와 플랫폼별 경계 재현", "라이선스·현재 공식 자료 확인",
                              "Zeus PG runtime 적응과 인수 승인"],
                "adoption_status": "not_approved_not_incorporated"})
    rows.append(row)
assert len(rows) == len({r["path"] for r in rows}) == 18
assert sum(r["bytes"] for r in rows) == partition["bytes"] == 190174
write("files.json", rows)
support = []
for path, ranges in SUPPORT.items():
    row = verified(path)
    lines = (SOURCE / "pinned" / path).read_text(encoding="utf-8").splitlines()
    assert all(1 <= a <= b <= len(lines) for a, b in ranges), path
    row.update({"line_ranges": ranges, "read_extent": "listed_line_ranges_only",
                "counted_in_partition_coverage": False, "tests_executed": []})
    support.append(row)
for path, ranges in ZEUS.items():
    raw = (ROOT / path).read_bytes()
    assert all(1 <= a <= b <= len(raw.decode("utf-8").splitlines()) for a, b in ranges), path
    support.append({"source": "zeus-working-tree", "path": path,
                    "sha256": hashlib.sha256(raw).hexdigest(), "line_ranges": ranges,
                    "read_extent": "listed_line_ranges_only",
                    "counted_in_partition_coverage": False, "tests_executed": []})
write("supporting-evidence.json", support)
write("checkpoint.json", {
    "source": "harness", "revision": REVISION, "partitions": [PARTITION],
    "expected": 18, "full_body_reviewed": 18, "bytes_verified": 190174,
    "scope_sha256": partition["scope_sha256"], "unreviewed_paths_in_partition": [],
    "tests_executed": [], "upstream_execution_count": 0,
    "blocked_gate_writer_probe_retried_or_bypassed": False,
    "subsystem_complete": False, "adoption_approved": False,
    "claude_independent_review": "pending",
    "status": "static_review_complete_execution_and_independent_review_pending",
    "review_ref": REF, "other_reviews_consulted_for_this_partition": [],
    "output_truncation_recovery": ["fleet_contracts.py:330-409 재독", "ladder_probe.py:1-35 재독"],
    "search_limits": "초기 넓은 rg 출력은 절단됨. 이후 실제 경로를 확정해 supporting 구간을 직접 읽음. 검색 히트나 타 파티션 구간을 전문 커버리지로 계산하지 않음.",
    "deferred": ["Samsung 실제 기기", "Device Farm SDK/MCP/replay 구축·인수"],
})
print(json.dumps({"reviewed": len(rows), "bytes_verified": sum(r["bytes"] for r in rows),
                  "supporting_files": len(support), "upstream_executions": 0}))
