# U001 — 일반·개발·운영 로그와 실행 감사 계약

상태: Codex가 승인한 첫 구현 명세. 구현자 Claude, 검토·수용 Codex.
선행 근거: 같은 디렉터리 README.md 및 source-manifest.json. 기존 #17 실행 관측과 #1/#11 분석·흡수 범위에 연결한다. 새 중복 이슈는 만들지 않는다.

## 목적과 범위

기존 CLI 출력·실행 이벤트·원장·artifact를 재사용하면서 일반/개발/운영 로그를 동일 실행 단위로 추적하고, 기록 실패를 침묵시키지 않게 한다. 모든 코드에 print를 추가하거나 새 로그 플랫폼을 만드는 작업이 아니다.

첫 연결 경로는 cli.serve, Executor._run, AppServer 실행 경계, invocation reserve/settle, execution_progress/checkpoint, supervisor의 작업자 시작·교체 판단, outbox 수락/전달/ACK 결과다. 기존 메시지 처리·권한·상태 전이 의미는 유지한다. 중복 스키마·별도 작업 원장을 만들지 않는다.

Claude provider 연결, 지식 승격 구현, 자동 운영 배포는 이번 PR에 넣지 않는다. 다음 묶음에서 동일 계약을 사용한다.

## 로그 계약

1. 버전 관리 JSON schema와 domain 검증을 추가한다. 업무 메시지의 six-W v1은 그대로 둔다. 업무 메시지와 관측 이벤트는 다른 계약이며 로그가 task.assign으로 실행되지 않아야 한다.
2. category는 `general`, `development`, `operations`. 한 동작에 무조건 세 레코드를 복제하지 않고 공통 event ID와 관계로 연결한다.
3. 공통 필드: schema_version, event_id, category, event_type, severity, source, observed_at, occurred_at, correlation_id, causation_id, execution, sequence, outcome, reason_code, evidence_refs, attributes.
4. execution에는 role/agent, provider, process_run_id, session_id, task_id, generation, attempt, invocation_id, repository revision을 해당되는 경우 포함한다. system 이벤트에는 task/session이 없을 수 있으며 명시적으로 null로 표현한다. 실행 이벤트와 시스템 이벤트를 schema 분기로 검증한다. 모든 상관관계 필드에 임의 placeholder를 채우지 않는다.
5. occurred_at이 원본에 없으면 null. observed_at은 수집 시각으로 별도 기록한다. 둘을 바꿔 쓰지 않는다. 순서는 (process_run_id, sequence), 인과관계는 causation_id와 기존 task/message/generation으로 판단한다. 벽시계만으로 전체 순서를 보장한다고 주장하지 않는다.
6. outcome은 시작/성공/실패/중단/차단/미확정 상태를 구별한다. 재시도는 새 attempt와 원인 event를 연결한다. provider의 종료 코드 0 또는 ACK 성공만으로 task 성공을 생성하지 않는다.
7. event_id와 payload hash가 같으면 재수집/재전송으로 취급한다. 같은 ID에 다른 내용이면 격리하고 충돌을 알린다. sequence 갱신은 저장 성공과 결속하며 재시작하면 새 process_run_id를 사용한다.
8. attributes는 event_type별 허용 필드·크기 제한을 둔다. 원본 프롬프트·환경변수·인증정보·private key·추론 원문을 기본 로그에 싣지 않는다. 결정·근거 참조·실행·결과를 기록한다. 허용된 명령도 비밀 인자를 제거한 형태만 노출한다.

정확한 event_type/필드 타입/상한은 구현 전에 schema와 매핑 표로 먼저 작성해 PR 초안에 포함한다. 필드 이름 변경이나 기존 이벤트 의미 변경은 Codex에 보고한다.

## 저장·전달과 실패 정책

- 일반 로그: 세션/프로세스 lifecycle, 메시지 수신·원장 수락·ACK·재전달·거부를 구분.
- 개발 로그: 실행 의도/리비전/검토·명세 artifact, 도구·테스트 결과, 출력 검증, checkpoint 및 후보 결과. 모델의 '테스트 통과' 진술은 실제 테스트 영수증과 구분.
- 운영 로그: 프로세스 상태, heartbeat/lease, backlog/lag, 재시도·자원·usage, sink 상태, 정체·교체·정리 실패. 값이 없으면 unknown/null이며 비용 0으로 꾸미지 않음.
- 필수 감사 전이는 기존 PostgreSQL transaction에 append-only 감사 레코드와 필요한 전달 outbox를 함께 기록한다. 임의 로그로 업무 권한을 만들지 않는다. 호출 시작 전에 감사/예약 저장이 실패하면 provider를 시작하지 않는다.
- provider가 이미 수행된 후 기록 실패가 발생하면 완료됐다고 보고하거나 무조건 재실행하지 않는다. redacted 최소 종료 증거를 durable spool에 남기고 해당 실행을 reconciliation 필요 상태로 둔다. 중복 외부 부작용을 피하는 절차를 문서화한다.
- 비필수 진단 로그는 bounded durable spool → 수집 → ACK의 재전달 경로를 사용한다. 저장 공간·보존·권한을 명시하고 spool이 꽉 차면 카운터/health 상태/알림으로 드러낸다. 조용히 버리지 않는다. 백프레셔가 예약/lease 제한을 우회하지 않게 한다.
- spool은 임시 CLI 작업 디렉터리가 아닌 설정된 runtime 아래에 두고 프로세스별로 격리한다. 마지막 부분 레코드·손상·중복을 구분하고 복구한다. Windows와 Linux의 원자적 파일 쓰기·동시 append 차이를 다룬다.
- 같은 고장 난 sink로만 'sink 장애' 로그를 보내지 않는다. 보호된 로컬 최소 기록 및 health 관측 경로를 두고, 외부 notification 경로는 기존 execution.notice/outbox를 재사용할 수 있는지 확인한다. Redis/PG 모두 끊긴 상태에서 외부 알림 성공을 주장하지 않는다.
- 외부 알림은 대기/전달 시도/확인/실패를 구분하고 반복 알림 폭주를 제한한다. 긴 작업의 정상 heartbeat와 시작만 있고 종료가 없는 orphan 실행을 구별한다. 기존 lease/deadline 기준을 재사용한다.
- 외부 배포/승격 경계도 동일 필수 감사 계약을 적용할 수 있도록 API를 제공하되 이 PR에서 운영 배포를 실행하지 않는다.

## redaction과 증거

redaction은 JSON 직렬화·stdout/stderr·spool·알림·영수증·JUnit 등 공개/일반 관측으로 나가는 모든 경로에 적용한다. 중첩 데이터와 오류 문장도 포함한다. publish된 byte hash는 redaction 이후 바이트에 대해 기록한다. 원문이 필요한 증거는 접근 제한 artifact로 분리하며 일반 로그에는 ref와 권한 범위만 둔다. digest만 있다고 원문 공개가 허용되는 것은 아니다.

이미 존재하는 execution_output 및 PR #69의 JUnit 비밀번호 보호를 회귀시키지 않는다. 테스트 실패에 비밀 canary 문자열을 넣어 공개 산출물 전체에 없는지 검사한다. 사용자 인증정보로 테스트하지 않는다.

## 수용 테스트

| ID | 조건 | 요구 결과 |
|---|---|---|
| L01 | 작업 수신→예약→프로세스 시작→진행→종료→원장 수락→결과 발송 | 같은 task/generation/attempt/correlation으로 추적. transport ACK와 작업 완료가 구분됨 |
| L02 | 같은 event 재전달 및 같은 ID/다른 내용 | 정확히 한 논리 레코드, 내용 충돌은 격리·알림 |
| L03 | PG 감사 기록/예약 저장 실패 | provider 시작 횟수 0. 감사 없이 성공 상태 없음 |
| L04 | 실행 후 PG 저장 실패·ACK 유실 | 최소 종료 증거 유지, unknown/reconciliation 표시, 맹목적 재실행 없음 |
| L05 | spool append 중 프로세스 종료·부분 레코드·동시 생산자 | 완료 레코드 유실 없음, 손상은 식별, 재개 후 중복 처리 없음 |
| L06 | sink 단절·spool full·복구 | bounded 동작과 독립적인 장애 관측, 복구 후 재전송·확인, 조용한 유실 없음 |
| L07 | lease 만료 후 늦은 이벤트·이전 session의 완료 | stale 관측은 보존 가능하나 현재 작업 상태/권한/지식 승격에 영향 없음 |
| L08 | 원본 발생 시각 없음·프로세스 재시작 | 발생 시각 조작 없음, sequence namespace 충돌 없음 |
| L09 | 중첩 오류/CLI/알림/JUnit에 비밀 canary 삽입 | 공개/일반 로그·스풀·알림 산출물에서 검출 0 |
| L10 | 관측 기록을 업무 메시지로 위장·권한 주입 | schema/역할 검사에서 거절, 독립 감사 실패 자체도 기록 |

MemoryStore/deterministic fault injection은 경계 회귀 테스트로 사용할 수 있으나 실제 운영 증거로 표시하지 않는다. 실제 PG+Redis 격리 인스턴스와 자식 프로세스로 L01/L04/L05/L06을 Windows와 WSL에서 확인한다. 호스트 재부팅·Docker Desktop 재시작은 수행하지 않는다. 실제 PG/Redis 대상 테스트에서는 운영 namespace와 테스트 schema/stream을 분리하고 정리는 소유한 자산에 한정한다.

U001은 provider-neutral 기반이므로 실제 Claude 호출·장시간 무인 운영은 아직 수용 분모가 아니다. 이를 통과했다고 U002/U004 완료를 주장하지 않는다.

## 제출 및 완료 경계

- 한 기능 묶음 PR. 연결 이슈 Refs #17 #1 #11, 자동 종료 참조 없음.
- 기존 기능 재사용 표, schema·event mapping, 실패 정책, 바뀐 파일, 정확한 head SHA, 실행 명령/exit code, 실패 및 재검증 이력, L01–L10 대응 증거를 제출.
- Ruff와 전체 pytest, 관련 실제 PG/Redis/프로세스 검증을 수행. skip 사유를 공개하고 실행하지 않은 환경은 명시.
- 기존 미커밋 분석 자료 및 coverage/path-ledger/goal-progress를 수정하거나 일괄 커밋하지 않는다.
- Claude는 구현·테스트·PR까지만. Codex가 검토·병합·이슈 종료를 판단한다. U002 이후 자동 착수하지 않는다.
