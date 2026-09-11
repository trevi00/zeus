# U001 — 일반·개발·운영 로그 계약과 실행 관측 기반 (GitHub #17 #1 #11)

역할: Codex가 명세([U001-logging-contract.md](../../autonomy/design-001/U001-logging-contract.md),
[design-001 README](../../autonomy/design-001/README.md))를 작성·승인했고, Claude가 이 문서의 구현·
테스트·증거·PR을 맡는다. 검토·병합·이슈 종료는 Codex가 판단한다. 이 문서는 구현자의 기록이며
인수 승인이 아니다. Claude provider 연결, 지식 승격, 운영 배포, 미커밋 분석 자료·원장 변경은 이
묶음에 없다.

## 1. 문제와 수용 기준

기존 Zeus에는 CLI JSON 출력, execution_progress, invocation ledger, artifacts, execution.notice/
outbox, health 버킷이 각각 있지만 (a) 세 종류 로그를 같은 실행 단위로 잇는 공통 envelope이 없고,
(b) 필수 감사 기록이 실패해도 provider가 시작될 수 있으며, (c) provider가 이미 실행된 뒤 원장
기록이 실패하면 다음 claim이 맹목적으로 재실행하고, (d) 기록 실패·스풀 포화·sink 단절이 관측되지
않는다. 수용 기준은 명세의 L01–L10이며 이 문서 5절이 각 항목의 증거를 가리킨다.

## 2. 원본 근거 (기준 리비전 `137bd24`, 변경 전 코드)

| 경로 | 확인한 사실 | 이번 연결 |
|---|---|---|
| `cli.serve` | `bus.receive → decode → authorize → handle → flush_outbox → ack` 순서, 거부는 dead-letter | 수신·수락·ACK·거부를 general 이벤트로 분리 |
| `Executor._run` | `parse_request → invocations.reserve(guard=_owned) → AppServer.run → classify → settle → persist_result → checkpoint` | 예약·정산 감사(필수), provider 시작/종료·진행·checkpoint 이벤트(진단), 종료 증거·재실행 거부 |
| `InvocationLedger.reserve/settle/abandon` | 예약은 소유권 재증명과 같은 tx; 정산 전 예외는 `abandon` | 같은 tx 안에서 `audit(tx, row)` 콜백 |
| `execution_progress` (observe) | 이벤트 자체의 `completedAtMs`를 occurred, 수집 시각을 collected로 분리; 기형 이벤트는 보존·카운트 | `development.progress_recorded`가 같은 구분을 유지 |
| `Harness.checkpoint` | 세션 generation CAS | `development.checkpoint_recorded` |
| `application/outbox._prepare/_publish` | 시도 의도 커밋 → 전송 → 영수증 커밋; quarantine·retry·error 구분 | 같은 tx에서 `general.message_published/delivery_retry/delivery_error/quarantined` 감사 |
| `supervisor.tick` | backlog·durable ready·busy로 기동/교체 판단 | `operations.backlog_observed / worker_wake_requested / worker_replace_requested / supervisor_tick / supervisor_error` |
| `execution_notices` | 정보용 six-W `execution.notice`; REASONS·schema enum 닫힘 | 재사용하지 않음(아래 6절 보고) |
| `monitoring.safe_text`, `profile_privacy.PATTERNS` | URL 자격증명·`password=` 정규식, 토큰 모양 | `domain/observation.redact_text`에 통합(신규 모듈, 기존 함수는 그대로) |

## 3. 설계

### 3.1 스키마 (`src/codex_harness/resources/observation.schema.json`, `urn:zeus:observation:1`)

공통 필드: `schema_version, event_id, category, event_type, severity, source, observed_at,
occurred_at, correlation_id, causation_id, execution, sequence, outcome, reason_code,
evidence_refs, attributes, redaction`. `execution.kind`로 `execution`/`system` 분기를 검증한다.
system 이벤트는 task/session/bucket/generation/attempt/invocation이 명시적 null이다. 빈 문자열
placeholder는 domain(`build_event`)과 schema(`minLength`) 양쪽에서 거절한다.

- `event_id` = sha256(`["observation", "1.0", event_type, identity…]`). identity는 감사 이벤트의
  경우 호출자가 준 전이 식별자(예: `["reservation", <id>, "settled"]`), 진단 이벤트는
  `["sequence", process_run_id, number]`.
- `content_hash` = 내용 필드(observed_at·sequence·source·redaction 제외)의 sha256. 같은 id·같은
  hash = 재전달, 같은 id·다른 hash = 충돌(격리·알림).
- `outcome`: started / succeeded / failed / aborted / blocked / unknown / **observed**. 명세의 여섯
  상태에 순수 관측(heartbeat, backlog)용 `observed`를 추가했다(Codex 확인 항목).
- `sequence.basis`: `spool_append`(스풀 append 성공에 결속) 또는 `unassigned`(스풀 불가 시
  감사 레코드만 PG에 기록, 번호 없음).
- runner 분류 → outcome: accepted→succeeded, empty_answer/invalid_output/tool_only/
  provider_failure→failed, interrupted→aborted, inspection_blocked→blocked. exit code·ACK는
  입력이 아니다.

### 3.2 이벤트 매핑 표 (레지스트리 `domain/observation.REGISTRY`가 원본)

| 기존 경로 | event_type | 분류 | 경로 | identity |
|---|---|---|---|---|
| serve 시작/유휴 종료 | `general.process_started`, `general.process_idle_exit` | general | 스풀 | sequence |
| bus.receive/decode | `general.message_received` | general | 스풀 | sequence |
| handle/record_incident 반환 | `general.message_accepted` | general | 스풀 | sequence |
| bus.ack | `general.message_acknowledged` | general | 스풀 | sequence |
| dead_letter | `general.message_rejected` | general | 스풀 | sequence |
| outbox `_publish` 성공 | `general.message_published` (stream_entry_id 포함) | general | **감사(tx)** | outbox_attempt id |
| outbox retry / error | `general.message_delivery_retry` / `_error` | general | 감사(tx) | outbox_attempt id |
| outbox quarantine | `general.message_quarantined` | general | 감사(tx) | quarantine id |
| ledger.reserve | `development.invocation_reserved` | development | **감사(tx)** | reservation id |
| AppServer 진입 전 | `development.provider_started` | development | 스풀 | sequence |
| AppServer 종료 후 | `development.provider_finished` / `provider_failed` | development | 스풀 | sequence |
| ledger.settle | `development.invocation_settled` | development | **감사(tx)** | reservation id |
| ledger.abandon | `development.invocation_abandoned` | development | 감사(tx) | reservation id |
| execution_progress | `development.progress_recorded` | development | 스풀 | sequence |
| Harness.checkpoint | `development.checkpoint_recorded` | development | 스풀 | sequence |
| workflow.complete / _fail_task | `development.task_completed` / `task_failed` | development | 스풀 | sequence |
| 정산 기록 실패 | `development.termination_recorded` + 로컬 termination 파일 | development | 스풀+로컬+PG(가능 시) | task/generation/attempt |
| 재실행 거부 | `development.reconciliation_required` | development | 감사(tx) | bucket/task/generation/attempt |
| 운영자 정리 | `development.reconciliation_resolved` | development | 감사(tx) | record id |
| heartbeat | `operations.lease_renewed` | operations | 스풀 | sequence |
| supervisor | `operations.supervisor_tick`, `backlog_observed`, `worker_wake_requested`, `worker_replace_requested`, `supervisor_error` | operations | 스풀 | sequence |
| 스풀/sink 상태 | `operations.spool_saturated`, `spool_append_failed`, `sink_unavailable`, `sink_recovered` | operations | 알림(PG 또는 로컬 보류) | alert kind/key/time |
| 충돌·거절·수집 | `operations.observation_conflict`, `observation_refused`, `collection_completed`, `alert_suppressed`, `alert_pending` | operations | 알림/스풀 | — |

attributes 허용 키와 타입은 레지스트리에 있다. 프롬프트·환경변수·인증정보·추론 원문 키는
존재하지 않으며, 허용되지 않은 키는 이름을 들어 거절된다. 문자열은 1,024자, attributes 전체는
4,096바이트로 제한한다.

### 3.3 저장·전달·실패 정책

| 경로 | 저장 | 실패 시 |
|---|---|---|
| 필수 감사 (`Observer.audit`) | 호출자 PG tx 안 `observation_audit` append-only; 스풀에도 `audit` 종류로 append(가능 시) | 거절 → ContractError로 tx 중단 → 예약 없음·provider 시작 없음 (L03). 같은 id 다른 내용 → `observation_quarantine` + `operations.observation_conflict` 알림, 기존 레코드 유지 (L02) |
| 진단 (`Observer.emit`) | `<runtime>/observations/spool/<process_run_id>.jsonl`, 한 프로세스 한 파일, 레코드당 한 번의 write, 32 MiB 상한 | 절대 raise하지 않음. SpoolFull/OSError → 카운터, `health/<run>.json` 갱신, 알림(창 300초 억제). 거절된 이벤트는 payload 없이 `observation_refused` |
| 수집 (`Collector.collect`, `zeus observe collect`) | 파일별 ack 오프셋부터 읽어 PG `observations`에 넣고, 커밋 후 `.ack` 원자 교체 | sink 실패 → ack 전진 없음, `sink_unavailable` 알림 보류, 다음 수집에서 재시도·중복 제거 (L06). 손상 줄 → `observation_quarantine`, 잘린 꼬리 → 소비 안 함 (L05) |
| 알림 | PG `observation_alerts` (tx 안 또는 별도 tx) | PG 불가 → `notification.status=pending, channel=null`로 로컬 보류(100건 상한), 복구 후 `recorded_after_recovery`로 재생. Redis/PG 모두 없을 때 외부 알림 성공을 주장하지 않음 |
| provider **진입 이후** 실패 (검토 R1) | `terminations/<digest>.json`(임시 파일 + `os.replace`, 존재 시 재전달로 계수), 가능하면 PG `observation_terminations`; 레코드에 실패 경계 `boundary` ∈ transport / classification / settlement / breaker_report / result_persistence / checkpoint | `provider_entered`가 외부 효과 경계다. 진입 전 거절(예약 감사 실패, breaker, AppServer 생성 실패)은 종료 기록 없이 통상 retry. 진입 후에는 checkpoint까지의 모든 예외가 `PostExecutionRecordFailure`가 되어 (1) 기존 실패 기록(영수증·진단 요청·`execution_failed` notice)을 남기고 (2) 같은 tx에서 작업을 `blocked/reconciliation_required`로 바꾸고 `execution.notice(reconciliation_required)`를 outbox에 넣고 감사한다. 예외: runner가 관측한 출력 실패(`ExecutionFailure`)는 증거 artifact를 먼저 저장하므로 관측된 결과이며 기존 retry 의미를 유지한다. `_run` 진입 시 `pending_terminations` 검사는 다른 프로세스가 남긴 기록에 대한 2차 방어다 (L04) |
| reconcile (검토 R2) | `zeus observe reconcile <id> --resolution rerun\|discard --operator <식별자> --reason <문장>`: **PG 결정 + 감사 커밋이 먼저**, 로컬 pending 파일의 resolved 이동은 그 뒤 | PG 실패 → 명령 실패, pending 유지. 커밋 후 로컬 finalize 실패·응답 유실 → 같은 명령 재전달이 PG의 resolved 행과 같은 결정임을 확인하고 finalize만 다시 한다(다른 결정이면 거절). `pending_terminations`는 PG가 resolved인 로컬 파일을 늦게 finalize한다. 읽을 수 없는 pending 파일은 모든 작업을 차단하고 status에 `unreadable`로 나온다. 권한 효과: `rerun`/`discard` 모두 관측 차단만 해제한다. 재큐잉은 기존 `execution-recovery prepare --operation repair` + `apply`로만 하며, PG에 pending termination이 남아 있으면 repair가 거절된다. `discard`는 작업을 blocked로 둔다(cancel 또는 별도 결정) |
| 스풀 공간 (검토 R3) | 세그먼트 회전(`<run>.<n>.jsonl`, 기본 4 MiB)과 **미확인 바이트** 기준 상한(32 MiB). 수집기가 세그먼트를 ack하고, 완전히 ack된 세그먼트가 작성자의 현재 세그먼트가 아니면(다음 세그먼트 존재 또는 `.closed` 마커) 삭제한다 | 활성 세그먼트는 절대 truncate하지 않는다. 수집이 따라오면 상한을 몇 번 넘겨도 기록이 이어지고, sink 단절 중에는 상한에서 멈추며 카운터·알림으로 드러난다. ack 유실은 재수집 후 id/hash 중복 제거로 흡수된다 |
| 보류 알림 (설계 판단 3) | `pending-alerts/<run>.json`에 원자 기록. 새 프로세스는 이전 run의 보류 파일을 상속한다 | `_flush_pending`은 tx 안에 put만 하고, 커밋 후 `_flushed`가 목록·파일을 비운다. 커밋 실패 시 보류 유지. 재시작 후 다음 성공 tx에서 `recorded_after_recovery`(replayed_by 포함)로 재생 |

Windows/Linux 차이: 단일 작성자 세그먼트 + O_APPEND 한 번 쓰기로 동시 append 인터리빙을 피하고,
ack/health/termination/pending-alerts는 임시 파일 + `os.replace`(양쪽 모두 원자)로 쓴다. fsync는 기본 on.

### 3.3.1 redaction 경계 (검토 R4)

- `correlation_id`·`causation_id`·`evidence_refs`는 불투명 식별자 규칙(`^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,199}$`)을
  통과해야 하고, 아니면 이벤트를 **거절**한다(치환하면 서로 다른 실행이 합쳐지므로). 거절은
  `operations.observation_refused`로 남고 payload는 싣지 않는다.
- `reconcile`의 `operator`는 같은 식별자 규칙, `reason`은 redaction 후 300자로 잘라 `{text, sha256,
  redaction_findings, truncated}`로 저장한다. CLI 반환값·resolved 파일·PG 행 모두 이 형태다.
- `validate_observation` 오류 문장은 경로와 실패 키워드만 담는다(`['outcome']: enum`). 격리 행의
  `defect`도 그 문장이다.
- 이물 예외는 타입 + `message_sha256` 16자만 기록한다. `ContractError`(Zeus 자체 문구)는 redaction 후
  300자.
- 회귀 테스트가 producer·CLI 반환·PG 행·파일·격리·알림·health·status를 함께 검사한다. JUnit은 호스트
  러너가 비밀번호를 scrub한 뒤 `CANARY-`/`password=`를 grep한다.

### 3.4 기존 기능 재사용 표

| 기존 | 재사용 방식 | 새로 만들지 않은 것 |
|---|---|---|
| `documents` 테이블(bucket 문서 저장소) | `observation_*` 버킷 6개 | 새 테이블·마이그레이션 없음 |
| six-W v1 `message.schema.json` | 관측 레코드는 별도 스키마. Codex 결정(설계 판단 2)으로 `execution.notice`의 `reason_code` enum과 `REASONS`에 `reconciliation_required` 1개를 추가해 차단을 팀장에게 기존 경로로 알린다 | 새 message type 없음. 소비자(`Workflow.handle → receive`)는 변경 없이 증명·중복 전달·수신자 검사를 그대로 적용 |
| invocation ledger 예약/정산/포기 | `audit=` 콜백 한 줄 | 별도 작업 원장 없음 |
| outbox 시도/영수증 | `audit=` 콜백 | 별도 전달 경로 없음 |
| execution_progress / checkpoint / artifacts | 그대로 두고 참조(evidence_refs)만 기록 | 이벤트 원문 복제 없음 |
| `execution_notices` (six-W notice) | 그대로 둠 | 6절 보고 |
| `health` 버킷 | supervisor·outbox health 유지 | 관측 health는 로컬 파일 + `zeus observe status` |
| `execution-recovery prepare/apply` | `repair`의 적격 오류에 `reconciliation_required`를 추가. PG에 pending termination이 남아 있으면 prepare/apply 모두 거절 | 새 recovery 명령 없음 |
| `profile_privacy` / `monitoring.safe_text` 정규식 | 같은 패턴을 `redact_text`에 통합 | 기존 함수 변경 없음 |

## 4. 구현 (바뀐 파일)

- 신규: `domain/observation.py`, `adapters/observation_spool.py`, `application/observations.py`,
  `resources/observation.schema.json`; 테스트 `tests/test_observation_contract.py`,
  `tests/test_observation_spool.py`, `tests/test_observations.py`, `tests/test_observation_wiring.py`.
- 변경: `ports.py`(SpoolFull, 스풀/디렉터리 Protocol), `adapters/contracts.py`
  (`validate_observation`), `application/invocation_ledger.py`(`audit=`), `application/outbox.py`
  (`audit=`), `application/service.py`(`flush_outbox(audit=)`), `application/workflow.py`
  (`heartbeat`가 현재 행을 반환), `adapters/executor.py`(관측자·감사·종료 증거·재실행 거부),
  `cli.py`(`serve` 관측, `observe collect|status|reconcile`, `inspect` 버킷), `supervisor.py`,
  `bootstrap.py`(`build_observer`, `build_collector`), `domain/policy.py`(스풀 32 MiB, 알림 창
  300초, 수집 배치 1000), `docs/contracts.md`(INV-OBSERVATION-001).
- `Executor`는 `observer` 없이도 동작한다(메모리 스풀 + 저장소 감사). 배포 경로(`bootstrap`)는
  항상 파일 스풀 관측자를 준다.

## 5. 검증

이 절은 실행한 명령과 결과만 적는다. 실행하지 않은 것은 실행하지 않았다고 적는다.

### 5.1 수용 기준별 증거

| ID | 증거 (테스트) | 단위 경계 / 실제 |
|---|---|---|
| L01 | `test_observation_wiring::test_l01_one_execution_is_traceable_end_to_end_and_ack_is_not_completion[memory,postgres]`, `test_l01_real_redis_publish_records_the_actual_stream_entry` | fake transport(모델 없음) + MemoryStore / 실제 격리 PG / 실제 Redis stream entry |
| L02 | `test_observations::test_audit_same_id…`, `test_collector_deduplicates…` [memory,postgres] | 실제 격리 PG 포함 |
| L03 | `test_observation_wiring::test_l03_audit_write_failure…` [memory,postgres] | 쓰기 실패는 주입(Interceptor), provider 시작 0 |
| L04 | `test_observation_wiring::test_l04_settlement_write_failure…` [memory,postgres] | 정산 쓰기 실패 주입, 종료 파일·재실행 거부·운영자 정리 실제 경로 |
| L05 | `test_observation_spool::test_real_child_processes_concurrent_kill_and_partial_tail…` [memory,postgres] | 실제 자식 프로세스 4개(동시 2, kill 1, 부분 꼬리 1) |
| L06 | `test_observations::test_sink_outage…`, `test_spool_saturation…`, `test_real_postgres_connection_refusal_is_a_sink_outage` | 주입 단절 + 실제 연결 거부(psycopg OperationalError) + 실제 스풀 상한 |
| L07 | `test_observations::test_stale_observation_after_lease_expiry…`, `test_orphan_report…` | 실제 lease 만료(1초) |
| L08 | `test_observation_contract::test_occurred_at_stays_null…`, `test_observations::test_restart_uses_a_new_namespace…` | 단위 |
| L09 | `test_observation_contract::test_redaction_covers…`, `test_observations::test_canary_secret_never_reaches…`, wiring L03/L04/abandon의 canary 검사 | 스풀 바이트·PG 행·health·status·CLI 구조; JUnit은 5.2 호스트 실행 산출물에서 검사 |
| L10 | `test_observation_contract::test_observation_is_not_a_business_message…`, `test_attributes_are_allow_listed…`, `test_observation_wiring::test_l10_observation_record_cannot_be_submitted_or_relayed_as_work` | 단위 |

### 5.2 실행 기록

| 실행 | 명령 | 결과 |
|---|---|---|
| Windows 11, 통상 스위트 (head `88a9817`) | `uv run ruff check .` / `uv run pytest -q` | All checks passed / 4 failed, 1147 passed, 358 skipped → 스텁 서명 2개 수정 후 `uv run pytest -q tests/test_dispatch_fairness.py tests/test_supervisor.py` 8 passed |
| Windows 11, 호스트 증거 1차 (head `88a9817`) | `uv run python scripts/environment_evidence.py --label windows-11 --out docs/zeus/evidence/environment-runs-003` | **실패**: full-suite-integration 1 failed, 1494 passed, 14 skipped (`test_real_postgres_connection_refusal_is_a_sink_outage`: 알림 행이 `pending`으로 저장됨). 러너·로그·JUnit은 `attempt-1-alert-row-kept-pending-status/`에 보존 |
| 결함 수정 (head `e367003`) | `_record_alert`가 저장 행에 `recorded` 상태를 쓰도록 변경; 메모리 테스트가 반환값이 아니라 저장 행을 읽도록 변경 | `uv run pytest -q tests/test_observation_*.py tests/test_observations.py` 35 passed, 16 skipped |
| Windows 11, 호스트 증거 2차 (head `e367003`) | 같은 러너 | **통과**: ruff 0.1s; full-suite-integration 1495 passed, 14 skipped (420.2s); disposable-docker-checks 17 passed (61.8s). 관측 테스트 파일별: contract 16, spool 5, observations 19, wiring 11 passed, skip 0. 격리 스택 `harness-evidence-windows-11-793e601e`, 임시 포트, 종료 후 정리. 영수증 `windows-11-receipt.json`(tracked_changes [], untracked []) |
| WSL Ubuntu 26.04 (WSL2 kernel 6.18), 호스트 증거 (head `e367003`) | `~/.local/bin/uv run python scripts/environment_evidence.py --label wsl-ubuntu-26.04 --out docs/zeus/evidence/environment-runs-003` (WSL fs 클론 `~/zeus-evidence`, 같은 커밋) | **통과**: ruff; full-suite-integration 1501 passed, 8 skipped (140.8s); disposable-docker-checks 17 passed (53.6s). 관측 테스트 파일별: contract 16, spool 5, observations 19, wiring 11 passed, skip 0. 격리 스택 `harness-evidence-wsl-ubuntu-26-04-bf2f7d72`. 영수증 `wsl-ubuntu-26.04-receipt.json`(tracked_changes [], untracked []) |

GitHub Actions (head `9b7156d`): ubuntu 3.12/3.14와 integration 잡은 통과, windows 잡 4개 중 3개가
`test_real_child_processes_…[memory]`에서 실패했다. 공유 러너에서 자식 프로세스의 import가 0.4초보다
오래 걸려 kill 시점에 스풀 파일이 아직 없었다(타이밍 결함은 테스트에 있고 런타임 코드는 같다).
다음 커밋에서 kill을 "첫 완료 레코드가 관측된 뒤"로 바꿔 결정적으로 만들었다. 이 수정은 테스트
파일만 바꾸므로 위 호스트 영수증(head `e367003`)은 런타임 코드에 대해 그대로 유효하다.

공개 산출물 검사: 두 호스트의 JUnit XML과 통합 로그에서 canary 문자열 `CANARY-` 0건, `password=` 0건
(러너가 실행별 비밀번호를 scrub한 뒤 기록). 이 검사는 grep으로 했고 결과를 PR 본문에 적었다.

실행하지 않은 것: 실제 Claude/Codex 모델 호출(범위 밖, fake transport만 사용), 네이티브 Linux(WSL2만),
호스트 재부팅·Docker Desktop 재시작, 사람 인수. 단위 테스트의 PG 쓰기 실패·연결 단절은 Interceptor
주입이며, `test_real_postgres_connection_refusal_is_a_sink_outage`만 실제 연결 거부를 쓴다.
GitHub Actions 결과는 PR 체크에서 확인한다.

## 5.3 1차 검토(PR #71 review 5175360030) 반영

| 지적 | 반영 | 회귀 테스트 |
|---|---|---|
| R1 provider 실행 이후 보호 범위 | `provider_entered` 경계, 6개 실패 경계 추적, 실패 즉시 blocked + notice, 진입 전 거절은 retry 유지, 출력 실패(`ExecutionFailure`)는 관측 결과로 예외 처리, schema preflight를 진입 전으로 이동 | `test_observation_wiring::test_post_entry_failures_all_leave_evidence_and_block[transport,result_persistence,checkpoint]`, `test_refusal_before_entry_is_an_ordinary_retry`, `test_repair_is_refused_until_reconciled_and_then_reruns_once`, `test_executor_research`의 갱신 3건 |
| R2 reconcile 저장 실패 | PG 커밋 → 로컬 finalize 순서, 같은 결정 재전달 멱등, 다른 결정 거절, 늦은 finalize, 읽을 수 없는 파일 차단, termination 원자 생성 | `test_observation_review::test_failed_reconcile_keeps_the_pending_marker`, `test_reconcile_survives_lost_commit_response_and_local_finalize_failure`, `test_sink_resolved_record_is_finalized_late_by_pending_check`, `test_unreadable_termination_file_blocks_and_is_reported` |
| R3 스풀 영구 포화 | 세그먼트 회전, 미확인 바이트 상한, ack 후 회수, `.closed` 마커 | `test_continuous_production_and_collection_never_saturates`, `test_sink_outage_bounds_the_spool_and_recovery_resumes_without_loss_or_duplicates`, 기존 L05 자식 프로세스 테스트(세그먼트 대응) |
| R4 redaction 경계 | 식별자 규칙으로 거절, reason/operator 정책, validator 문장, 격리 defect | `test_reconcile_decision_correlation_and_schema_errors_never_carry_the_canary` |
| 판단 2 notice 재사용 | `REASONS`·schema enum·producer(`_record_reconciliation_block`) | L04 테스트의 notice 검증(schema, 중복 전달 멱등, 잘못된 수신자 거절) |
| 판단 3 보류 알림 | 커밋 후 비움, 로컬 파일 지속, 재시작 상속 | `test_pending_alerts_survive_restart_and_replay_after_the_next_commit` |

반영 중 발견한 추가 결함: 수집기가 ack·회수 전에 `sink_recovered`를 emit해 복구 이벤트 자체가
포화 스풀에서 떨어졌다. ack·회수 뒤로 옮겼다.

기존 동작 변경(Codex 확인 항목): provider 진입 후 transport 예외·checkpoint 실패·persist 실패는 더
이상 `retry`가 아니라 `blocked`다. `test_executor_research`의 세 테스트가 그 의미로 갱신됐고,
운영자 재개 경로는 `observe reconcile` → `execution-recovery repair`다.

## 6. Codex에 보고하는 설계 판단

1. `outcome`에 `observed`를 추가했다. heartbeat·backlog처럼 성공/실패가 없는 순수 관측을
   `unknown`으로 적으면 "미확정"의 뜻이 흐려진다.
2. 재실행 거부 상태를 `execution.notice`로 내보내지 않았다. `REASONS`와 six-W schema의
   `reason_code` enum이 닫혀 있어 `reconciliation_required`를 추가하면 six-W v1 변경이 된다.
   대신 `tasks.status=blocked`, `events.execution.reconciliation_required`, 관측 감사로 남겼다.
   notice로도 알리려면 enum 확장이 필요하다(Codex 판단).
3. 외부 알림 채널은 새로 만들지 않았다. PG `observation_alerts`가 채널이고, PG 불가 시
   로컬 보류 후 재생한다. Redis/PG가 모두 끊긴 동안 외부 알림 성공을 주장하는 경로는 없다.
4. 이물 오류 메시지는 타입과 digest만 기록한다. 정규식 redaction만으로는 임의 비밀을 못 잡기
   때문이다. 원문이 필요하면 접근 제한 artifact에 따로 둔다(이번에는 termination 파일에도 원문을
   두지 않았다).
5. `Workflow.heartbeat`가 갱신된 행을 반환하도록 바꿨다(반환값 없던 함수). 호출자 동작은 같다.
