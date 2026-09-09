"""Generate records for completed static reads without executing upstream code."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/harness"
NAMES = {"harness:skills/backend:001", "harness:skills/data:001",
         "harness:skills/devops:001", "harness:skills/convention:001"}
NOTES = {
    "auth-authz": "신원과 소유자/프로필 대조, 필터와 실패 순서. FastAPI 기본 403 등은 버전 의존 원문 주장으로 보존.",
    "auth-credential": "비밀번호 길이/해시·계정 부재 타이밍·응답 동일성. 사전압축/NUL 처리와 실패 False 전략을 현재 보안 권고로 승인하지 않음.",
    "auth-failure-tests": "형태 7·클레임 5·다른 키·다른 신원 축과 응답 본문 동일성. 인용 프로젝트의 실제 실패 테스트는 이번에 미실행.",
    "auth-storage-oauth": "저장 매체 위험·서명 키 회전·임시 키 기동·OAuth code/PKCE/state/nonce. OAuth 구현 실적 부재를 원문이 명시함.",
    "auth-token": "알고리즘/클레임/용도·만료·회수·refresh 계보. 전제 없는 stateless 설명과 24시간 사례를 전역 정책으로 사용하지 않음.",
    "backend-repair": "근본 원인, 계약을 잘못 가정한 테스트의 수정 사유, 전체 무회귀, 라우트 직접 호출 회귀. lesson one-shot은 신뢰 검증 필요.",
    "csharp-pos-device-gateway": "벤더 파사드·프로토콜 정규화·오류표·제한적 재시도·단일 장치 소유. 프로세스 Kill/금액0 기본값/로그 삼킴을 Zeus 규칙으로 채택하지 않음.",
    "java-build": "JDK/toolchain·호환표·마이그레이션 중복·방언·분할 빌드. Bash 명령은 현재 shell=True 실행기와 Windows 계약 대조 필요.",
    "java-database": "실행계획·복합 인덱스·락·파티션·용량·풀·Redis 목적·Tasklet/Chunk. 원문 데이터베이스별 일반화와 수치 효과를 재검증해야 함.",
    "java-jpa": "enum·validate·OSIV·쿼리 형상·락·마이그레이션. path/contains 예시는 실행기의 target/expect와 불일치.",
    "java-mybatis": "바인딩/동적 식별자·실 DDL·XML 조건·PK resultMap·빈 IN·N+1·접속 설정. 컴파일/런타임 단정은 대상 버전별 검증 필요.",
    "java-scheduled-batch": "dispatcher/enable/SQL 상한/건별 오류·rowcount·CAS·배포 트리·경보 목적지. lease를 외부 부작용 at-most-once로 승격할 근거 부족.",
    "java-spring-core": "계층·프록시·트랜잭션·스레드 컨텍스트·설정 주입·DTO·예외·모놀리식. Zeus 도메인에 프레임워크 예외 의존을 들이지 않음.",
    "java-spring-test": "슬라이스와 실 DB 통합 분리, 컨테이너 수명, mock 누수·커버리지 의미. mock 권고와 사용자 no-mocking 요구를 구분.",
    "python-batch": "독립 프로세스·시각 주입·반개방 창·동점 정렬·원자 교체·0건 결과·청크 불변. 실제 데이터와 반복 실행 증거가 후속 필요.",
    "python-fastapi-layout": "미들웨어/CORS·지연 DB·생존 경로·앱 팩토리·미설정 기동·RLock. 개발 선택을 운영 준비로 승격하지 않음.",
    "python-fastapi-routing": "서비스 HTTP 비의존·오류 봉투·폐쇄 코드·cursor·라우터 등록·OpenAPI. cursor 서명 금지와 상한20/100은 프로젝트 선택.",
    "python-sqlalchemy": "프로젝트 CI 실행 경로·정확 핀·migration/DDL 정본·UUID/시간/DSN 바인딩. 실제 psycopg Zeus adapter에 SQLAlchemy 규칙을 무조건 적용하지 않음.",
    "python-testing": "스위트 비용 분리·패키지 지원 코드·인증 API·시드 경계·프로퍼티 예산·실 DB 공급·커버리지. deadline 해제에는 별도 전체 상한 필요.",
    "canonical-schema": "코드/스키마/타입 우선순위·폐쇄 어휘·여집합·휘발상태·호환면·버전. additive 무버전 일반화는 이전 reader 호환 검증 필요.",
    "conceptual-design": "개념/제외 양쪽 공백 방지·UC 출처·상태와 이벤트 로그 정본·화면필터 분리·공백 백로그 연결. 언급 앵커는 의미 증명 아님.",
    "er-diagram": "비엔티티 판단·표시/저장값·순위·자연키 정규화·PK·집계 멱등. 특정 앱의 모든 상태/로그 키 선택을 일반 법칙으로 삼지 않음.",
    "logical-design": "비정규화 대가·인덱스 소비자·동시성 한계·FK/기본값·봉투 분리·중복 문서. 알려진 한계 기록이 금전 위험 수용 승인 아님.",
    "physical-schema": "물리 정의역의 경계 전사·EP별 오류 의미·부분쓰기·바인딩·DDL 정본·drift. dry-run 성공은 migration/복구/앱 인수와 다름.",
    "schema-domain": "직렬화 해상도·폭주 상한·하류 CSS 정의역·편집 UI 탈출·미방출/골든·명시 순위. 실제 rendering/roundtrip은 이번 미실행.",
    "project-convention": "gate-patterns·정규식·관찰 범위·소비 게이트·제외 사유·원장 상태·래칫. 현재 래칫은 문장 삭제뿐이며 의미 완화는 검증하지 않음.",
    "scaffold-boundaries": "계층×도메인 경계·공유물 소유·순환 제거·실제 첫 도메인. proposed 경험을 검증된 모듈 이식으로 표기하지 않음.",
    "scaffold-gates": "게이트 파생/컨벤션 실행부 선확인·ERROR 구별·존재와 계약 구별·즉시 빌드. 스킬의 단계 번호와 현재 core를 구분.",
    "scaffold-runtime": "설정 주입·생존 endpoint·3개 진입점·CORS·docstring·gitignore. 임시 키/무DB 기동을 운영 적합성으로 읽지 않음.",
    "devops-ci": "리뷰 단위·CI 트리거·정적 분석·빌드/배포 분리. Java/ArgoCD/Kubernetes/systemctl 배제는 현재 Zeus 채택 결정 아님.",
    "devops-compose": "기동 작업과 관측 게이트 분리·내부/호스트 포트·status본문·미기동 범위·태그 피닝. 실제 http_probe는 본문을 읽지 않음.",
    "devops-observability": "지연 분포/오류 분모/포화·측정기/문턱/소비자·증상 경보. 도구/1~3초/1~2주 견적의 현재 타당성과 실제 전달은 미검증.",
}
SUPPORT = {
    "scripts/engine/checks.py": [[1, 162]],
    "scripts/engine/pipeline_loader.py": [[222, 260], [420, 455]],
    "scripts/validators/ddl_dry_run.py": [[1, 57]],
    "scripts/engine/gate_ratchet.py": [[1, 62]],
    "config/retriever.yaml": [[1, 15]],
    "scripts/engine/skill_router.py": [[45, 90]],
    "tests/unit/test_checks_smoke.py": [[1, 145]],
    "tests/integration/test_gate_ratchet_smoke.py": [[1, 130]],
    "pipelines/core.yaml": [[325, 395], [490, 575]],
}
ZEUS = {
    "src/codex_harness/adapters/store.py": [[1, 85]],
    "src/codex_harness/adapters/configuration.py": [[1, 100]],
    "src/codex_harness/application/release_queue.py": [[1, 91]],
    "src/codex_harness/application/monitoring.py": [[1, 103]],
}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def verified(path):
    row = index[path]
    raw = (SOURCE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert sha == row["snapshot_sha256"] and blob == row["object"]
    assert len(raw) == row["bytes"]
    return {"source": "harness", "revision": manifest["revision"], "path": path,
            "git_blob": blob, "pinned_sha256": sha, "bytes": len(raw)}


manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
assert manifest["revision"] == "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
index = {r["path"]: r for r in manifest["inventory"]}
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
selected = [p for p in partitions if p["partition"] in NAMES]
assert len(selected) == 4
rows = []
for partition in selected:
    for item in partition["paths"]:
        path = item["path"]
        row = verified(path)
        row.update({"partition": partition["partition"], "disposition": "semantically_reviewed",
                    "read_extent": "full_body", "semantic_summary": NOTES[Path(path).stem],
                    "review_ref": "docs/full-analysis/backend-assets/review.md",
                    "tests_executed": [],
                    "test_limits": "정적 읽기 전용. 상류 실행·설치·DB 변경·배포 0건. 기술 권고와 역사 실측은 원문 주장, 현재 공식 자료 및 실제 환경 검증 필요.",
                    "remaining": ["실제 Claude 독립 검토", "격리 재현 및 기존 테스트 실행", "공식 기술 문서와 라이선스 확인", "Zeus 적응 설계 및 승인"],
                    "adoption_status": "not_approved_not_incorporated"})
        rows.append(row)
assert len(rows) == len({r["path"] for r in rows}) == 32
assert sum(r["bytes"] for r in rows) == 134967
write("files.json", rows)
support = []
for path, ranges in SUPPORT.items():
    row = verified(path)
    row.update({"read_extent": "listed_line_ranges_only", "line_ranges": ranges,
                "counted_in_partition_coverage": False, "tests_executed": []})
    support.append(row)
for path, ranges in ZEUS.items():
    support.append({"source": "zeus-working-tree", "path": path,
                    "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                    "line_ranges": ranges, "read_extent": "listed_line_ranges_only",
                    "counted_in_partition_coverage": False, "tests_executed": []})
for path, lines in {"scripts/engine/tick.py": [89, 90, 95],
                    "scripts/lib/seams.py": [284, 312, 313]}.items():
    row = verified(path)
    row.update({"read_extent": "rg_matching_lines_only", "matching_lines": lines,
                "counted_in_partition_coverage": False})
    support.append(row)
write("supporting-evidence.json", support)
write("checkpoint.json", {
    "source": "harness", "revision": manifest["revision"], "partitions": sorted(NAMES),
    "expected": 32, "full_body_reviewed": 32, "bytes_verified": 134967,
    "unreviewed_paths_in_partition": [], "tests_executed": [],
    "subsystem_complete": False, "adoption_approved": False,
    "claude_independent_review": "pending",
    "status": "static_review_complete_execution_and_independent_review_pending",
    "review_ref": "docs/full-analysis/backend-assets/review.md",
    "prior_router_trace": "docs/full-analysis/frontend-assets/supporting-evidence.json",
    "search_limits": "잘못 추정한 파일 경로는 이후 rg --files로 정정. 절단된 지원 파일은 해당 부분을 재독. 검색 히트는 전문 coverage로 계산하지 않음.",
})
print(json.dumps({"reviewed": len(rows), "bytes_verified": sum(r["bytes"] for r in rows),
                  "supporting_files": len(support), "tests_executed": 0}))
