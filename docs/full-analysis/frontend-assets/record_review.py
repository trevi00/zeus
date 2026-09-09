"""Record a completed static read; never imports or executes upstream modules."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/harness"
NAMES = {
    "harness:skills/frontend:001", "harness:skills/spec:001",
    "harness:skills/design:001", "harness:skills/verification:001",
    "harness:templates/_common:001", "harness:templates:001",
}
NOTES = {
    "frontend-e2e": "실패 화면 우선, storageState 재사용, 멱등 시드, 진단 스펙 제거, 반복 게이트. 실제 테스트 실행은 아님.",
    "react-19-actions": "Action 큐와 폼 자식 상태, optimistic 투영, peer 의존과 lint. React 버전별 외부 원문 재검증 필요.",
    "react-state-effects": "서버/전역/URL 상태 소유와 파생값, cleanup, stable key. 절대적 fetch 금지 문구는 설계 맥락과 분리 불가.",
    "react-typescript": "unknown 경계 parse, 스키마에서 타입 도출, strict 및 색인 검증. 파일 문자열 금지 검사는 타입 의미 검증을 대체하지 못함.",
    "react-vite-build": "모듈 설정 쌍, env 검증, 시크릿의 클라이언트 공개 금지, 정적 Tailwind 매핑. 실제 환경 피닝/빌드 증거는 없음.",
    "react-vitest": "단위/컴포넌트 범위의 MSW/fakeTimers 명시 권고가 사용자 no-mocking 요구와 충돌. E2E와 경계는 문서에 명시됨.",
    "api-spec": "EP별 요청/응답/헤더/오류 우선순위/인증/화면 소비를 요구하나 템플릿 및 전체 파일 존재 게이트와 불일치.",
    "arc42-structure": "12개 문서 영역을 결정 자체와 구별하고 구조/흐름/ADR/위험을 분리. 외부 원문과 로컬 규율의 경계를 표시함.",
    "contract-wiring": "스펙/등록/스키마/쿼리/UI 5축 양방향 대조와 데이터 소유 요구. 단순 ID 존재 검사의 한계를 자인함.",
    "domain-module": "EP 유일 배속, 소유 데이터, 조립 계층과 선언된 읽기 예외. 부분 문자열 파서 때문에 문서 참조를 금지하는 제한은 구조화해야 함.",
    "prd-boundaries": "PRD는 요구 생성이 아닌 접기, AC 정본 복제 금지, 배치 입력 누락 방지. 현재 배선은 일치하지만 인용 행 번호는 과거임.",
    "prd-coverage": "부분 문자열 앵커 충돌, PRD floor 배선 부재, 언급과 결정 차이를 자인. 정형 행 파서로 적응 필요.",
    "prd-scope": "문제/해법 분리, 성공 지표 5칸, 비범위 재개 조건, 검증할 가정, 책임 있는 OPEN 질문. 템플릿보다 규율이 더 풍부함.",
    "design-critique": "실렌더 7기둥, 여러 상태, a11y, 독립 판단. 뷰포트 세 폭과 스크린샷은 삼성 실제 기기 인수를 입증하지 못함.",
    "persona-gwt": "사람 페르소나와 정상/실패 GWT, REQ/UC/AC/EP 앵커, 역설계 의도 발명 금지. 린트는 의미를 검증하지 않음.",
    "tradeoff-record": "대안/기각/재검토 조건과 폐쇄 지표 요구. 자체 점검 CLI 경로는 실제 validator 이동을 반영하지 못함.",
    "verification": "기계 게이트와 정직 잔여, ERROR/FAIL 분리, 인접 무회귀. 산문 PASS보다 실제 현재 실행 증거 필요.",
    "verify-blackbox": "빌드 산출물 대상 브라우저 검사, 부하 중 실측, 여러 브라우저 축, 로그와 실제 tree 매칭. 역사 사례 재실행하지 않음.",
    "verify-e2e": "판정 장치 실재, 무수정 관측, 실응답 회귀 대조, 공유 리미터와 진단 스펙 간섭. 샘플 burst 숫자는 보편 한도 아님.",
    "verify-reliability": "저장 컬럼 정의역, 경계 오류, 과거 FAIL 실행 정체성, 실 DB 요구. 현재 해당 앱을 재실행하지 않음.",
    "verify-unit": "검사 층 선택, red 선확인, 테스트 완화 금지, coverage 해석, 동시성 대기 상한. 문서 선언과 실행 영수증 분리.",
    "verify-wiring": "수리 후 재판정 가능성이 범위를 정함, 다음 단계로 증거 전달, 실제 계층 호출. health 200 자체는 배선 정합 증거 아님.",
    "README": "24 템플릿의 앵커/게이트/발급 규약. SEQ/ST pending와 컴포넌트 화살표 계약은 현재 카탈로그와 재대조 필요.",
    "api-spec.template": "JSON 한 쌍과 산문 오류 예시. 최신 스킬의 EP별 오류/HTTP 표, 헤더/쿼리/소비 화면 계약을 담지 못함.",
    "component-diagram.template": "책임과 Mermaid 의존 분리. prose →/Mermaid -->는 의도적 분리이며 충돌 해석은 diagram-mobile-assets/review.md DM-01에서 정정. 설명문·그래프·코드 의미 정합은 별도 검증.",
    "conceptual-design.template": "CON/UC 개념 관계와 의도적 제외. 명사 전수라는 약속은 실제 UC 문자열 커버리지보다 강함.",
    "convention.template": "gate-patterns를 실행 가능한 규칙으로 선언. Markdown 정규식은 실제 응답 전체 계약을 검증하지 못함.",
    "decision.template": "사람 결정과 debate 승격, 근거/기각/파급. trust/created_by frontmatter 자체는 인증된 승인 아님.",
    "domain-spec.template": "배타 EP, 데이터, 규칙, 타 도메인 계약. 범위 표기 허용과 실제 substring 배속 파서가 모순; 출력 경로도 CLI와 다름.",
    "e2e-report.template": "실행/환경/인접 무회귀/flake 보고 골격. 현재 트리 해시·실행 ID·원시 영수증·초기화 계약 필드가 부족함.",
    "er-diagram.template": "CON→ENT 속성·키·관계와 미확정. 추출본 손편집 금지 의도는 유용하나 실제 DB 검사 아님.",
    "flowchart.template": "FLOW/UC와 정상/실패 Mermaid 흐름. 실패 GWT 대응 산문은 현재 UC 문자열 커버리지만으로 보장되지 않음.",
    "hardening-report.template": "기계 검사 증거와 사람 OPEN-H를 구분. 배포·rollback 자체를 실행하는 절차는 없음.",
    "lesson.template": "proposed 경험과 PASS 증거 및 family 매칭. 실제 curator가 지역 증거와 고유 실행을 보장하는지는 별도 경험 분석 대상.",
    "logical-design.template": "ENT→TBL와 제약/인덱스/관계 결정. 실제 migration과 저장 정의역 실행은 별도 필요.",
    "ontology-topology.template": "평면·관점축·관계 골격. markdown 발급과 pipeline ontology JSONL 산출/검증 사이 변환이 이 템플릿에 없음.",
    "physical-design.template": "DB 버전/마이그레이션/테이블 사상과 결정 근거. 실행 성공을 주장하려면 실제 대상 DB 영수증 필요.",
    "prd.template": "제품/페르소나/REQ별 릴리스/비범위/OPEN. 가정과 지표 5칸 등 최신 스킬 계약은 추가 저작 필요.",
    "repair-notes.template": "증상→재현→원인→수리→검증→교훈. Markdown PASS 문구의 존재를 실행 신뢰로 승격하면 안 됨.",
    "requirements.template": "목적/기능/비기능 REQ와 사용자 미확정 OPEN. 앵커가 있어도 사람 의도·실행 가능성은 별도 검토 필요.",
    "sequence-diagram.template": "UC/EP와 계층 왕복, 실패 분기. 카탈로그는 UC 언급을 재며 시퀀스 메시지 의미를 대조하지 않음.",
    "spike.template": "사전 판정 기준과 최소 실험·미해결·프로토타입 폐기 원칙. {name} placeholder는 CLI의 <프로젝트> 치환과 다름.",
    "state-diagram.template": "상태 전이/권한/불법 전이를 명시. _state 접미 앵커 커버리지와 실제 허용 전이 집합은 다름.",
    "test-plan.template": "AC→케이스, 실패 GWT, 은닉 오라클, 신뢰성 계획. 실제 케이스 실행/행동 단언과 사람 인수의 바인딩은 없음.",
    "usecase.template": "persona와 GWT/AC/EP 참조. 정상/실패 두 GWT 약속에 비해 예시와 린트는 단어 존재 수준임.",
    "wireframe.template": "SCR/FLOW, 진입/이탈과 로딩/빈/오류 표면. 실제 렌더·상태·컴포넌트 스토리 증거가 별도 필요.",
    "wiring-report.template": "기동과 경계 실호출·미관측 영역 기록. health/ping 예시만으로 계층 기능 완료를 판단하면 안 됨.",
}
SUPPORT = {
    "scripts/engine/graph_queries.py": [[55, 150], [290, 365]],
    "scripts/validators/usecase_lint.py": [[1, 84]],
    "scripts/validators/intent_doc_floor.py": [[20, 95]],
    "scripts/cli/scaffold_cmd.py": [[1, 97]],
    "ontology/graph-queries.yaml": [[1, 156]],
    "scripts/engine/skill_router.py": [[1, 44], [157, 335]],
    "pipelines/core.yaml": [[272, 305], [395, 490]],
    "scripts/engine/gate_runner.py": [[1, 179]],
    "tests/integration/test_scaffold_smoke.py": [[1, 216]],
    "tests/unit/test_router_smoke.py": [[30, 165]],
    "scripts/cli/step_cmd.py": [[90, 170], [440, 460]],
    "scripts/lib/seams.py": [[140, 225]],
    "scripts/validators/tradeoff_lint.py": [[1, 160]],
    "tests/contract/test_tradeoff_lint_contract.py": [[1, 80]],
}


def verified(path, index):
    record = index[path]
    raw = (SOURCE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert sha == record["snapshot_sha256"]
    assert blob == record["object"] and len(raw) == record["bytes"]
    return {"source": "harness", "revision": manifest["revision"], "path": path,
            "git_blob": blob, "bytes": len(raw), "pinned_sha256": sha}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
assert manifest["revision"] == "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
index = {r["path"]: r for r in manifest["inventory"]}
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
selected = [p for p in partitions if p["partition"] in NAMES]
assert len(selected) == 6
rows = []
for partition in selected:
    for item in partition["paths"]:
        path = item["path"]
        row = verified(path, index)
        row.update({
            "partition": partition["partition"],
            "disposition": "semantically_reviewed",
            "review_ref": "docs/full-analysis/frontend-assets/review.md",
            "read_extent": "full_body",
            "semantic_summary": NOTES[Path(path).stem],
            "tests_executed": [],
            "test_limits": "읽기 전용 정적 검토. 상류 테스트·브라우저·실기기 실행 0건. 연결 코드의 분기 추론은 실제 재현이 아니다.",
            "remaining": ["실제 Claude 독립 검토", "격리 실행과 재현 영수증", "외부 출처 및 라이선스 확인", "Zeus 적응 설계 및 승인"],
            "adoption_status": "not_approved_not_incorporated",
        })
        rows.append(row)
assert len(rows) == len({r["path"] for r in rows}) == 47
assert sum(r["bytes"] for r in rows) == 93217
write("files.json", rows)
support = []
for path, ranges in SUPPORT.items():
    row = verified(path, index)
    row.update({"read_extent": "listed_line_ranges_only", "line_ranges": ranges,
                "counted_in_partition_coverage": False, "tests_executed": []})
    support.append(row)
zeus = ROOT / "src/codex_harness/domain/sdd.py"
support.append({"source": "zeus-working-tree", "path": "src/codex_harness/domain/sdd.py",
                "sha256": hashlib.sha256(zeus.read_bytes()).hexdigest(),
                "line_ranges": [[1, 28], [35, 130], [169, 202]],
                "read_extent": "listed_line_ranges_only", "counted_in_partition_coverage": False})
write("supporting-evidence.json", support)
write("checkpoint.json", {
    "source": "harness", "revision": manifest["revision"],
    "partitions": sorted(NAMES), "expected": 47, "full_body_reviewed": 47,
    "bytes_verified": 93217, "unreviewed_paths_in_partition": [],
    "tests_executed": [], "subsystem_complete": False, "adoption_approved": False,
    "claude_independent_review": "pending",
    "status": "static_review_complete_execution_and_independent_review_pending",
    "not_found": ["scripts/engine/scaffold.py", "scripts/engine/dispatch.py",
                  "scripts/validators/api_examples_lint.py", "tests/unit/test_templates_smoke.py",
                  "scripts/cli/tradeoff_lint_cmd.py"],
    "search_limits": "초기 넓은 rg 출력은 절단됨. 근거는 이후에 읽은 명시 범위와 정확한 존재 대조만 사용. 전체 검색을 전문 검토로 세지 않음.",
    "review_ref": "docs/full-analysis/frontend-assets/review.md",
})
print(json.dumps({"reviewed": len(rows), "bytes_verified": sum(r["bytes"] for r in rows),
                  "supporting_files": len(support), "tests_executed": 0}))
