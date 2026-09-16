# 제한 실행 루프 검증 결과

2026-09-16. Codex 설계·검토, Zeus를 통한 Claude 구현. 이번 구현의 수용과 무인운영 전체의 완료를 구분한다.

## 구현과 독립 검증

`zeus cycle start/status/step`은 PG에 실행 한도와 진행 중 표식을 유지한다. Redis·Workflow·Executor를 재사용하며 실패/알림/다른 correlation에서 중단한다. 실행기 claim의 기존 트랜잭션에서 예상 작업을 검사하므로 사전 조회 이후 다른 작업이 들어와도 대신 실행하지 않는다. 검토 수용 뒤에는 운영자를 기다리고 conductor·배포를 실행하지 않는다.

- 실제 PostgreSQL+Redis를 붙인 전체 시험: 1,830 passed, 2 failed, 20 skipped. Ruff 통과.
- 두 실패는 새 테스트의 가짜 Git 후보에 author가 빠진 문제였다. Codex가 검증 픽스처만 정정했고 관련 20건은 격리 PG 검사를 포함해 20 passed, skip 0. 전체 스위트를 다시 통과했다고 표현하지 않는다. 런타임 변경은 없다.
- 별도 실제 PG schema와 Redis namespace에서 작업→검토 거절→수정→검토 수용 네 step을 확인했다. 모델과 Git은 대역이다. 별도 Python 프로세스가 실행 횟수 3을 재조회했고, 네 번째 step 뒤 awaiting_operator, release_queue 0건이었다.
- 위 추가 시험의 첫 시도는 같은 가짜 Git revision을 거절·수용에 재사용해 실패했다. 후보 revision을 실제 재작업처럼 구분한 뒤 통과했다. 실패 영수증도 보존했다.
- 첫 초안의 실제 Workflow.claim 반례는 다른 correlation을 선택했다. 수정된 guard 회귀는 provider 진입 전에 거절함을 확인했다.

## 실제 모델 실행

1. Claude 첫 호출: provider 예산 종료, task retry, 실패 알림과 diagnose 보존. 남은 초안을 성공으로 승격하지 않았다.
2. Claude 보완 호출: 코드 제출 성공, task.result에서 review_lead 등록. Claude는 테스트를 실행하지 못했다고 보고했다. 원시 tool_result에서도 권한 거절을 확인했다.
3. 새 LocalCycle을 통한 실제 Codex 팀장 호출: 300초 turn 예산 초과. 결정은 blocked/reconciliation_required, invocation은 unsettled_unknown, cycle은 execution_blocked로 중단됐다. 관측 56건, 수집 실패 0건. 검토 수용으로 기록하거나 재호출하지 않았다.

기계 호출 원장은 기존 5개에서 8개로 증가했다. Claude 2회 한도를 모두 사용했고 추가 호출은 하지 않았다. provider 비용 추정치는 청구액 또는 엄격한 지출 보증이 아니다. 이번 단계는 성공한 실제 Claude→Codex 수용 한 바퀴를 증명하지 않는다.

## 운영 잔여와 다음 범위

1. Claude 테스트 권한: 정책의 `python -m pytest ...` 허용과 실제 전달한 가상환경 Python 절대 경로가 맞지 않았다. 무인 세션에는 승인 창이 없어 자동 거절됐다. 다음 배정 전 고정된 테스트·Ruff 실행 명령과 허용 규칙을 일치시켜야 한다. 일반적인 Windows sandbox 고장으로 단정하지 않는다.
2. 팀장 검토: 입력과 검토 산출물 범위를 줄여 기존 시간 예산 안에서 완료하도록 해야 한다. 현재 미확정 호출은 종료 증거를 검토하고 기존 reconcile 절차로 처리한 뒤에만 새 실행을 고려한다. 여기서는 차단을 해제하지 않았다.

원장·대화·대형 로그는 D 드라이브에 보존한다. manifest.json은 검증 당시 원본 해시를 고정한다. persistent-cycle-001 실패 schema와 persistent-cycle-002 제출/차단 schema, 전용 Redis는 재시작 후 확인을 위해 유지한다. 기존 운영 PG 컨테이너를 재시작하지 않았다. 이슈 #20은 전체 무인운영 조건이 남아 있어 열어 둔다.
