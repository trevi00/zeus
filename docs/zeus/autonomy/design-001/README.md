# 무인 자율 고도화: 기존 경로 분석과 구현 순서

기준: `32928ab1d340db9acc49658b3670999e91bcb40f`, 2026-09-11. 작성·분석·설계: Codex.
이 문서는 지정된 Zeus 실행 경로의 제한된 분석이다. 로컬 원본 전체 분석 완료가 아니며 기존 125개 미커밋 분석 파일과 원장 전이 40건은 변경하지 않았다. 새로운 원본 의미 분석 커버리지 가산은 0이다.

## 확정 요구사항과 책임

- 오케스트레이터 → 팀장 → 팀원. Codex가 목표·분석·설계·검토를, Claude가 명세에 따른 구현을 담당한다. 역할과 provider/model은 별도 축이다.
- 세션 간 통신은 기존 Redis Streams와 six-W v1 JSON을 유지한다. 임의의 CLI 결과를 권한 있는 팀장 메시지로 받아들이지 않는다.
- PostgreSQL은 작업·권한·실행·검증 원장이다. Redis 메시지 ACK는 업무 완료나 지식 승격의 승인이 아니다.
- 검증 전 컨텍스트는 임시 후보다. 검증과 실제 반영을 모두 확인한 뒤에만 온톨로지/토폴로지의 신뢰된 지식으로 승격한다. 검증 전에도 복구용 원장과 실행 증거는 저장한다.
- 일반·개발·운영 로그를 공통 식별자로 연결한다. 로그 수집 실패 자체도 관측하며 필수 감사 기록이 불가능하면 신규 중요 동작을 막는다.
- code-tutor-ai의 새 구축·배포는 전체 분석/흡수 및 무인 자율 고도화 검증 이후다. 현재 운영 서비스 교체나 무제한 모델 호출은 이번 명세에 포함하지 않는다.

## 기존 기능과 정확한 차이

| 경로 | 확인한 구현 | 필요한 고도화 |
|---|---|---|
| 조직 | resources/organization.json: conductor, lead, worker 및 parent | 새 계층을 만드는 대신 역할별 provider 정책과 실제 세션 실행을 연결 |
| 메시지 | message.schema.json; RedisBus.publish/receive/ack: 수신자별 stream, workers group, XAUTOCLAIM, XREADGROUP, XACK | 실제 provider 프로세스와 전달·수락·실행·완료의 상관관계 연결 |
| 소비/원장 | cli.serve → Workflow.handle → flush_outbox → ack; application/outbox.py의 전달 시도·격리 | 기존 재전달/원장 의미 보존. model exit=0이나 stream ACK를 완료로 오인하지 않기 |
| 실행 | Executor._run이 AppServer를 직접 생성. parse_request('app_server'), codex-app-server breaker, Codex 이벤트·usage 형식 | 런타임 선택/어댑터 경계, Claude 이벤트 정규화, 실행 capability 선언 필요 |
| 세션 복구 | sessions를 agent로 조회하고 task/근거 binding, execution_progress, checkpoint generation 확인 | provider session ID는 실행 lease와 별개로 결속. provider별 재개 또는 새 세션 복구 정책 필요 |
| supervisor | TARGETS 서비스와 active image를 비교하고 busy가 아닐 때 교체 | 컨테이너 교체와 모델 세션 권한 인계를 구분. 오래된 프로세스의 완료·승격 차단 실측 필요 |
| 지식 | PostgresKnowledge.index_python과 project_runtime이 관측을 knowledge_nodes/edges에 투영. experience_claims도 별도 존재 | 관측 그래프와 승인된 지식 그래프의 신뢰 경계·조회 필터·승격/철회 이력 필요 |
| 로그 | CLI emit, supervisor JSON print, AppServer의 bounded stderr, execution_progress, invocation ledger, artifacts, execution.notice/outbox | 로그가 없는 상태는 아님. 세 종류의 공통 envelope, 필수 기록 계약, 누락·정체 탐지, 수집/스풀 복구 경로를 연결해야 함 |

위 표는 해당 경로의 직접 코드 독해 결과다. 저장소 전체에서 다른 부분 구현이 전혀 없다는 증명은 아니다. Claude 구현 전에 같은 목적의 코드가 발견되면 새로 만들지 말고 근거와 재사용 대안을 보고한다.

## provider와 세션 통신 경계

`Redis six-W → 권한 검사/원장 수락 → 실행 lease·호출 예약 → provider adapter → 구조화된 결과·증거 → 원장 전이/outbox → Redis six-W`

provider의 stdout/stream-json은 내부 실행 프로토콜이다. 모든 세션 간 업무 메시지는 기존 six-W로 포장하며 실제 sender/recipient는 검증된 역할과 lease에서 도출한다. Claude에게 DB 자격증명이나 Redis 직접 발신 권한을 주어 결과를 스스로 승인하게 하지 않는다. 긴 작업은 로그·진행 이벤트를 내보내되 lease를 갱신할 수 없으면 더 이상 중요 동작을 시작하지 않는다.

현재 Runtime Protocol.run은 Executor가 쓰는 이벤트·heartbeat·취소 capability를 충분히 표현하지 않는다. 새 어댑터는 단순히 클래스 하나를 추가하는 수준이 아니라 이 계약과 호출 지원표, 결과 정규화, checkpoint binding까지 함께 연결해야 한다. 기존 Codex 경로는 기본값으로 유지하고 명시적으로 배정한 구현 작업만 Claude 경로로 보낸다. provider 변경을 모델 자격 승격으로 간주하지 않는다.

## 지식 신뢰 상태 설계

후속 U003의 상태: `candidate → verified → applied → promoted`, 실패/반례는 `rejected` 또는 `revoked` 이력으로 남긴다. 의미적으로 다른 상태를 하나의 success 플래그로 합치지 않는다.

- candidate context: TTL/크기 제한이 있는 임시 조회 계층. 원문·출처 해시는 복구 원장/제한된 artifact 저장소에 보존 가능하다. cache가 유실돼도 기록에서 재구성한다.
- observed graph: 코드에서 추출한 may_call/imports와 현재 작업 배치 등 관측 관계. 사실 관측의 출처이지 개선 지식의 승인 증거가 아니다.
- trusted graph: 독립 검증 대상과 결과, 실제 적용 리비전/배포, 승인 정책을 확인한 지식. 모델 self-report나 임의 DB row만으로 승격하지 않는다.
- 승격: claim/version/evidence/적용 대상 및 graph version을 트랜잭션/CAS에 결속하고 outbox projection을 재전달해도 한 번만 적용한다.
- 철회: 이력 삭제 대신 supersedes/revokes 관계와 조회 제한을 갱신한다. 과거 판단 근거는 보존한다.

관측 그래프 자체를 금지하거나 작업/로그 원장을 지우는 변경은 하지 않는다. 신뢰된 지식을 요구하는 소비자는 trusted view를 명시적으로 조회해야 한다.

## 구현 순서와 통과 조건

1. **U001: 세 종류 로그 계약과 실행 관측 기반.** [구현 명세](U001-logging-contract.md). 이 묶음만 Claude 착수 가능.
2. **U002: Claude 팀원 실행.** U001 수용 후 Codex가 상세 명세 제공. capability/provider routing, stdin 기반 요청, JSON/stream 정규화, timeout·프로세스 트리 종료, lease·session·usage 결속, 실제 Claude 제한 작업 실측. 로컬 help만으로 지원/모델 준비 완료를 선언하지 않음.
3. **U003: 후보 컨텍스트와 지식 승격.** U001 이후 독립 묶음. 관측/후보/신뢰 조회 경계를 검증하고 실제 적용 전 승격을 거절.
4. **U004: 3계층 반복과 중단 복구.** U002/003 수용 뒤 Zeus의 작은 작업으로 명세→Claude→PR→Codex→수정→수용을 실행. ACK 유실, 작업자/팀장 종료, PG/Redis 중단, stale session과 비용·재시도 상한 실측.
5. **U005: 개선 후보 카나리아와 운영 승격.** 기존 release pipeline을 재사용. 후보 세션은 등장만으로 운영 권한을 받지 않는다. 증거에 결속한 승격, 기존 작업 drain/lease 종료, 이전 세션 차단, rollback을 격리된 운영 시험에서 실측.

로컬 전체 자산 분석은 Codex가 계속 담당한다. 이 순서는 이미 확인된 Zeus의 차이를 보완하는 순서이지 원본 전체 분석을 생략하거나 흡수 완료로 표시하는 절차가 아니다. 새 팀/제품/실기기 UI 구현은 이 첫 묶음 범위 밖이다.

## 이번 검증과 한계

- 기존 tests/test_bus.py, test_invocation_ledger.py, test_execution_progress.py, test_execution_output.py: **47 passed, 14 skipped**. 기존 경계의 회귀 확인이며 실제 Redis·Claude 운영 통과로 취급하지 않는다.
- 로컬 Claude Code **2.1.268**의 `--version`, `--help` 확인. stdin/출력/schema/session/resume/budget 관련 옵션 존재를 확인했지만 모델은 호출하지 않았다. 실제 동작과 플랫폼 차이는 U002에서 검증한다.
- 이번에는 runtime/배포 설정, 제품 코드, 원장 상태, 운영 세션을 변경하지 않았다. 실행 코드 수정이 없는 분석·명세 산출물이다.
- source-manifest.json은 분석 근거 파일을 기준 commit의 blob과 연결한다. 파일 전체 의미 검토 완료 목록이 아니다.
