# 독립 검토와 Codex 수정 결과

실제 Claude CLI는 Read/Glob/Grep만 사용했다. Codex의 독립 설계 검토를 먼저 기록한 후 서로의 결과를 비교했고, 구현은 Codex가 수행했다. 검토 원문과 제공자·사용량 영수증은 `review/`에 보존한다.

| 발견자 | 문제 | 반영 |
|---|---|---|
| Codex·Claude | 기존 스펙 부재 PASS, xfail 생성물을 인수 자산으로 오인할 수 있음 | 엄격 스펙 계약, 관측/기대 분리, 미실행·미승인 상태 보존 |
| Claude | 다중 시나리오 순서와 초기화 미보장 | 초기화 통합 없는 다중 replay export 차단, 생성 메서드 순번 |
| Claude | replay 초안의 자동 테스트 수집 | 출력 어댑터에서 `.py.review` 강제; 검토 HTML도 `.html` 강제 |
| Claude | ADB daemon 진단을 기기 행으로 파싱 | transport 전용 파서, 진단 무시 |
| Claude | 에뮬레이터만 있어도 discovered | 물리 Samsung 후보 없으면 blocked |
| Claude | 요구사항 ID 삭제/의미 재사용 | 영구 ID, active/retired, 동일 ID 의미 불변, 은퇴 부활 금지 |
| Claude | 화면 재렌더 후 stale element로 잘못 실패 | selector로 재조회하며 정확한 문자열 동등성 유지 |
| Codex | 반복 간 동일 observation의 proposal dedup 충돌 | proposal identity에 iteration ID 포함 |
| Codex | DB→파일 잠금이 정리 작업의 파일→DB와 충돌 | 트랜잭션 밖 아티팩트 저장 후 현재 결속 재검증 |

Claude의 closure에서 6개 blocker 해소를 코드 검토로 확인했다. 이후 제안한 출력 확장자 검사를 공통 어댑터로 내리는 소규모 보완도 Codex가 반영하고 테스트했다. Claude는 테스트를 실행하거나 물리 기기·사람 승인을 인증하지 않았다.

남은 통합은 실제 앱/기기, 인증된 사람의 결정, 초기화 검증, Device Farm 세션 및 MCP/REPL, 전체 배포 엔진, 전체 로그 계측과 모델 자격 평가다. 현재 8단계는 준비 보고서이며 모두 증적·승인을 기다린다. 위 검토를 프로덕션 승인으로 해석하지 않는다.
