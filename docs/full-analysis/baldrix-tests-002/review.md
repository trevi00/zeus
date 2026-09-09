# Baldrix tests002 정적 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 16개 primary, 188,337 bytes를 모두 새로 전문 읽었다. 시작 Zeus HEAD는 `2458b8fd73616d4cd28d5e7a2f9a0457c72b9fc4`이며 시작 path-ledger의 16개 상태는 모두 unreviewed였다. 그 원장 행과 해시를 prior-path-ledger.json에 보존했다. 전문 독해 재사용은 0이며 지원 36개 파일은 실제 읽은 줄 구간만 별도로 기록한다. 원본 실행·import·probe·network·설치·live state 접근은 모두 0이다.

가장 중요한 발견은 다음과 같다.

- **검사 분모가 runner마다 다르다.** autopilot_state의 프로젝트별 목록/cwd 보존 두 test 함수는 수동 TESTS에 빠져 있다. brain_store의 10개 시나리오는 t_ 이름과 별도 카운터를 쓰므로 직접 main은 실행하지만 pytest 기본 수집에서는 빠진다. 명칭이나 총 PASS만으로 두 경로를 동등하게 볼 수 없다.
- **E2E라는 이름보다 실제 오라클이 좁다.** 병렬 autopilot smoke는 부모가 직접 Git과 합성 pane 이벤트를 다루며 실제 worker/model fanout과 merge SUT를 연결하지 않는다. backend 부재·시작 실패·출력 실패에서 return 또는 부모 log 대체가 PASS로 집계될 수 있다. calendar E2E도 실제 validator/unit 성공 대신 True를 넣고 helper 간 dict를 전달한다.
- **안전·내구성과 관측불가를 합치는 경로가 있다.** brain_git_status는 내용 일치가 아니라 ID 집합 포함을 검사하고 예외에서 at_risk=False를 낸다. calendar의 malformed/없는 ledger는 no-block 또는 defect0으로 바뀐다. JSONL 손상 행을 버리는 테스트는 실제 증거 완전성을 확인하지 않는다.
- **승인·자가개선의 근거가 부족하다.** 공개 문자열 token 비교와 apply-command 출력은 사용자 승인이나 권한 검증이 아니다. 잦은 breaker trip만으로 임계 완화를 제안하고 현재 override와 다른 기본 상수를 기준으로 삼을 수 있다. brain의 과거 clean streak를 복원한 결과도 새로운 환경의 검증·인수가 아니다.
- **형식·통계와 실제 효과가 다르다.** 합성 approved dict로 cross-target marker를 기록할 수 있고, caller timestamp/marker 및 경로 containment를 충분히 검증하지 않는다. merge 응답의 head_sha는 비어있지 않은 문자열이면 되며 실제 Git 객체 확인은 없다. routing regex와 boilerplate 휴리스틱은 tool 권한이나 요구사항 충족 검증이 아니다.
- **OS·환경 격리는 별도 검증이 필요하다.** Windows OS 이름 mock은 네이티브 파일시스템 시험이 아니다. OneDrive guard는 Linux인 WSL을 즉시 통과시킨다. hook 테스트는15초, 실제 설정은5초이며 사용자 절대경로와 bare python을 사용한다. breaker proposer의 CLI 테스트는 temp project만 전달하고 상태 디렉터리를 실제로 바꾸지 않는다.

보존할 후보는 corruption 오류를 명시적으로 분리하는 구조, 충돌 시 중단·worker branch 보존, 입력 형식 실패의 반환 경로, 프로젝트 귀속, deadline 경계, read가 빈 상태를 만들지 않는 방어다. 다만 Zeus에서는 Git 정의와 PG 운영 정본에 project/attempt/generation/정책 revision 및 실제 실행 영수증을 결속해야 한다. 사용자 8단계 SDD의 요구·구현·검증·사람 인수를 합성 bool, 과거 성공 횟수, mock 결과로 충족 처리하면 안 된다. 이 문서의 Zeus 모듈 매핑은 적응 방향이며 현 코드 동등성 검사가 아니다.

파일별 근거는 [file-reviews.md](file-reviews.md), 실제 SUT/caller/config 구간의 후속 판단은 [supporting-notes.md](supporting-notes.md), 바이트·Git blob·SHA와 정확한 범위는 [files.json](files.json) 및 [supporting-evidence.json](supporting-evidence.json)에 있다. 원본 긴 재현물이나 credentials는 포함하지 않았다.

완료한 것은 이16개 primary의 정적 전문 검토뿐이다. 미기재 전이 의존성, 실제 Claude 전체 교차검토, 외부 원문·라이선스 확인, 모델 자격, Windows/Linux/WSL 실제 실행, Zeus 적용·사람 인수·채택은 미완료다. 전체 분석 완료와 흡수 승인은 false로 유지한다. 자체 recorder/Ruff/해시·범위·링크 검사는 문서 정합성 검사이며 원본 테스트 실행이나 인수로 세지 않는다.
