# GSD bin 첫 파티션 독립 정적 검토

고정 원본 cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2의 7개, 198986바이트를 모두 새로 전문 읽었다. 이전 원장은 모두 unreviewed였고 정확한 행을 prior-path-ledger.json에 보존했다. 직접 지원 6개를 별도 범위로 읽었다. 소스 실행/import/collection/시험/네트워크/설치/Claude 호출은 0회다. node:test 13개는 읽은 설계이며 실행 결과가 아니다.

가장 먼저 고쳐야 할 후보는 조회 출력의 임시 파일 정리와 잠금이다. core는 큰 JSON 출력 과정에서 소유자 확인 없이 시스템 temp의 gsd-* 디렉터리도 삭제한다. 잠금은 시간 초과 뒤 재취득 없이 작업을 실행하고 callback의 EEXIST를 잠금 충돌로 오해해 재실행할 수 있다. 이 동작은 PG의 lease/트랜잭션 권위로 그대로 옮길 수 없다.

완료 신호도 인수와 다르다. commands는 SUMMARY 수와 status:passed 문자열로 Complete를 정하고, frontmatter validate는 필수 키 존재만 본다. 직접 소비 verify는 원문 artifact를 전부 skip하면 결과 분모 0/0으로 통과할 수 있다. 읽기는 마지막 YAML 블록, 쓰기는 첫 블록을 다루어 성공 응답 뒤에도 이전 값이 읽힐 수 있다. 설정 CRUD와 workstream 설정 소비의 기준 경로도 서로 다르다.

merge-back의 실제 Git 시험은 의미 있는 SHA·충돌·CRLF 사례를 가진다. 다만 구현은 expected-base를 무시하고 모든 linked worktree를 처리하며 reconcile 실패 뒤에도 정리와 merged=true로 갈 수 있다. 문서의 임무 소유권·원자 처리·회귀 커버 선언은 실행 증거로 승격하지 않았다. 모델 표와 agent 파일 존재는 실제 모델 위임 자격이 아니다.

Zeus에는 Git의 정의 revision과 PG의 실행 상태를 결속하고 사용자 8단계 SDD의 요구·검사 분모·실제 결과·검수·사람 핵심 시나리오를 분리하는 변형 후보로만 남긴다. 데이터 출력의 소유권, 원자 쓰기와 실패 보존, 엄격 schema 및 작업별 Git scope가 필요하다. 전체 직접/전이 closure, 실제 Claude 전체 대조, 라이선스·외부 주장, Windows/Linux/WSL, 모델 및 사람 인수, 구현·흡수 승인은 모두 미완료다. 이 파티션의 전문 정적 독해 완료만 보고하며 전체 분석 완료를 뜻하지 않는다.
