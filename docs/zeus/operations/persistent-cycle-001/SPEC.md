# 지속 원장의 제한 실행 루프

2026-09-16 Codex 분석·설계. 기존 Workflow.handle, Executor.execute_one/decide_one, outbox, Redis consumer group, observation을 재사용한다. 구현은 Claude, 독립 검토·수용·병합은 Codex다.

## 확인한 공백과 범위

기존 cli.serve는 성공 결과를 review_lead로 연결하고 Executor는 거절을 rework로 연결한다. 새 메시지 버스·검토 체계를 만들지 않는다. 기존 serve를 무제한 켜면 retry 상태가 자동 재호출될 수 있고, 전체 운영 단계의 호출 상한과 재시작 후 중단 지점은 별도로 결속돼 있지 않다.

이번 변경은 전용 PG schema·Redis namespace·D runtime을 쓰는 운영 프로필에서 한 correlation만 처리하는 제한 실행 제어다. 영구 저장소는 종료 시 삭제하지 않는다. 프로필 namespace는 보안 경계가 아니며 인증·권한 계약은 그대로다. conductor 실행, release_queue 소비, 병합, 배포는 제외한다.

## 인터페이스와 동작

1. `LocalCycle`을 application 계층에 추가한다. 기존 service/store, Workflow/Executor와 bus를 의존성으로 받는다. 기존 port를 재사용하고 adapter import를 application에 넣지 않는다.
2. `start(cycle_id, correlation_id, max_executions)`는 PG `local_cycles`에 정책을 한 번 저장한다. 같은 요청은 멱등, 다른 correlation/한도로 덮어쓰기는 거절한다. `status(cycle_id)`는 읽기만 한다.
3. `step(cycle_id)`는 메시지 전달·원장 수락·outbox·ACK를 기존 계약대로 처리하고, 최대 한 번의 실제 executor 호출만 한다. 역할은 worker:implementation, lead:improvement, 팀장 phase는 review_lead만 허용한다. 기존 결과 메시지 처리를 우회하지 않는다.
4. 실행 전에 트랜잭션으로 슬롯을 증가시키고 in_flight 상태를 기록한다. max_executions는 이 cycle을 통한 executor 시작 허용 횟수이며, 모델의 실제 청구·호출 횟수라고 부르지 않는다. 재시작·다중 호출로 초기화하지 않는다. in_flight를 만난 다른 step은 실행하지 않으며 자동 해제하지 않는다.
5. 실행 실패·retry·blocked·미확정·예외 또는 execution.notice/diagnose 대기가 있으면 cycle을 멈추고 사유를 남긴다. 자동 재시도·자동 예산 증액은 없다. 정상적인 review_lead 거절의 후속 implement만 기존 rework 경로로 허용한다.
6. 작업·결정과 수신 메시지의 correlation이 지정한 것과 다르면 거절/중단하며 ACK하거나 실행하지 않는다. 다른 작업을 잘못 선택할 수 있는 큐가 있으면 fail closed한다. 이 루프가 claim 선택 정책을 새로 만들지 않는다.
7. accepted review_lead 결과가 conductor에게 넘어간 상태는 `awaiting_operator`다. conductor 소비·실행·PR 병합·배포를 하지 않는다. 할 일이 없으면 idle로 보고하며 성공을 꾸미지 않는다.
8. 작은 CLI `zeus cycle start/status/step`을 추가한다. 기존 settings/프로필 환경을 사용하고 자격증명을 출력하지 않는다. `step`은 반복 프로세스의 한 턴이며, 영구 상태가 다음 프로세스로 이어진다. 추가 daemon, Docker 관리, 전역 정책 변경은 범위 밖이다.

## 수용 기준

- 기존 PG+Redis 경로를 재사용한 정상 성공→검토, 거절→수정 전달이 유지된다.
- 같은 cycle 재시작의 한도 유지, 중복 step의 한 번 실행, in_flight 이후 자동 재진입 거절.
- notice/실패/retry 중단, 다른 correlation 거절, accepted review에서 conductor 앞 정지.
- 실제 외부 모델 호출은 검증 단계에서만 수행하고 단위/통합 시험의 대역과 구별한다. fixture 모델을 실제 Claude/Codex라고 부르지 않는다.
- 일반·개발·운영 로그는 기존 executor/outbox 경로를 유지한다. cycle 상태·시작 횟수·중단 사유는 PG와 CLI로 확인한다.
- 테스트 후 Ruff와 전체 pytest를 실행한다. PostgreSQL 검사는 Codex가 격리 환경에서 독립 실행한다. 모델에게 운영 DB 자격증명을 전달하지 않는다.

## 이번 단계의 실제 호출 범위

사용자 진행 지시에 따라 새 단계로 시작한다. 기존 기계 원장 5개 항목을 유지한다. Claude 구현·필요한 수정 최대 2회, 호출당 900초·provider 예산 옵션 USD 3. Codex 팀장 검토 최대 2회, 기존 decision deadline 적용. 단계 총 4회이며 누적 호출 슬롯 상한 9로 고정한다. 수치가 실제 청구액을 보증하지 않으며 자동 증액하지 않는다. 현재 Codex 세션은 분석과 최종 수용을 담당한다.

구현 범위: `src/codex_harness/application/local_cycle.py`, CLI 배선, 관련 테스트와 계약·짧은 운영 문서. 필요한 변경은 이 범위 안에서 한 번에 제출한다. reference 분석·디자인 자산·WSL 추가 조사로 범위를 늘리지 않는다.

## 첫 구현 검토와 한 번의 보완

첫 Claude 실행은 provider의 예산 종료로 실패했고 초안만 남았다. 단위 테스트 14개와 Ruff는 독립 실행에서 통과했다. 실패 원장과 diagnose는 그대로 보존하며 성공으로 바꾸지 않는다.

실제 Workflow.claim을 사용한 반례에서 cycle의 사전 조회와 executor claim 사이에 들어온 다른 correlation이 선택됐다. 모델 호출 없이 재현했다. 따라서 기존 선택 순서를 재구현하지 않고, executor와 Workflow.claim의 기존 트랜잭션에 선택한 id·correlation·허용 상태/phase를 검사하는 선택적 guard를 전달하도록 범위를 좁게 확장한다. 기본 호출은 이전 동작을 유지한다. guard 불일치는 provider 시작 전에 거절하고 cycle이 중단한다. DB 트랜잭션을 모델 실행 동안 유지하지 않는다.

보완은 위 결함, 실제 Workflow를 이용한 성공→검토·거절→수정 계약 시험, 별도 프로세스에서 PG 상태 재조회 시험을 한 묶음으로 진행한다. 외부 모델 대역과 실제 Redis/PG 사용을 구별한다. 기존 초안을 보존한 revision 위에서 남은 Claude 1회를 사용하며 예산은 증액하지 않는다. 첫 실패 schema와 다른 보완 schema를 사용해 실패 작업을 자동 재호출하지 않는다.
