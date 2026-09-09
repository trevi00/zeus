# harness 실행기 002 체크포인트

`harness:scripts/engine:002`의 16개 파일, 184,493바이트 전문을 독립적으로 읽었다. 정본은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`이며 각 원본 SHA256과 Git blob을 manifest에 대조했다. 경로 전체 분모는 inventory.json, 파일별 판정·해시는 files.json, 의미 분석은 review.md, 실제 읽은 연결 구간은 supporting.json에 있다.

모든 primary 상태는 `body_reviewed_call_test_trace_pending`이다. 전문 의미 검토 완료와 전체 호출·시험 추적 완료를 구분한다. 원본, 원본 테스트, 생성 코드의 실행은 **0회**다. build-index.py 실행은 바이트·해시·보고서 메타 기록이며 테스트 통과가 아니다. 주석에 적힌 과거 PASS·수치·재현은 이번 실행 증거로 사용하지 않았다. 이전 보안 차단 probe도 재시도하지 않았다.

주요 정적 쟁점은 tick과 gate_runner의 PARTIAL 대기·재시도 경계 차이, sandbox 설명과 실패 교집합 조건의 차이, 관측 단계만으로 완료를 추론하는 PG projection, 격리되지 않은 RLM Python 실행, oracle 없는 xfail 골격이다. ontology 테스트의 전량 설명도 실제 고정 하한 단언과 다르다. 이는 해당 원본에서 읽은 조건이며 현재 배포 결함의 재현 판정은 아니다.

Zeus 대응의 기준은 `AGENTS.md`의 Git 정의/PG runtime 권한 분리와 `src/codex_harness/domain/sdd.py`의 8단계다. 스펙 논의 → 디자인 분석 → 코드 작성 → 자체 검증 → 알파 배포 → QA 및 증적 → 라이브 배포 → CS 대응이라는 사용자 흐름을 원본의 임의 DAG 단계 수·파일 존재·문자열 게이트로 대체할 수 없다. 읽은 native gate_report도 구조 검증 외에는 실제 실행과 인증된 사람 결정을 요구하며 release 권한을 주지 않는다.

흡수 후보는 전제 변경의 명시적 표면화, PASS 없는 하류 실행 차단, 제안과 검증 교훈의 분리, 실패한 방향을 직접 확인하는 테스트 설계다. PG projection·JSONL 상태·파일 승인 표식을 그대로 runtime SSOT로 채택할 수 없으며, 후보/환경/시험 분모 해시와 인증된 판단, 동시 갱신 및 실패 원자성을 갖춘 application 계약으로 다시 설계해야 한다. 검색·라우팅·반복 횟수는 사람 경험의 인수나 자가개선 승격 근거와 같지 않다.

모델 이름 문자열은 자격 증거가 아니다. 실제 읽은 native SDD 계약은 Astra/Sol/Terra 매핑을 `unqualified`, 자동 하향을 false로 둔다. Win/Linux/WSL 실행·프로세스 격리·Bash launcher 호환성과 실제 모델 시험은 이번 범위에서 미실행이다. 전체 구현 등가, 저장소 전체 분석 완료, 채택 승인은 주장하지 않는다. 남은 일은 remaining.json에 고정했다.
