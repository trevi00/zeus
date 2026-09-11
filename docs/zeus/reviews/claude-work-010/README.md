# PR #71 — U001 2차 검토

검토 head: `18df1c3526f4f1fae6617c81ae648121c1dedf27`. 판정: **수정 후 재검토, 병합 보류**. #17/#1/#11 OPEN 유지, U002 착수 미승인.

## 수용한 수정과 검증 범위

- R2의 PG decision/audit commit → 로컬 finalize 순서, 같은 결정 재전달, 다른 결정 거절, 늦은 finalize, 읽을 수 없는 종료 파일 차단을 확인했습니다. 기존 R2 반례는 해소됐습니다.
- R1의 transport/result_persistence/checkpoint 실패 차단, R3의 정상적인 세그먼트 회전·ACK 후 회수, R4의 `password=...` 형태 거절/정제, 기존 notice reason 연결은 개선됐습니다. 아래 남은 경계 때문에 각 항목 전체를 수용하지는 않습니다.
- provider 진입 후 미확정 실패를 retry → blocked로 바꾸는 테스트 기대값 변경은 의도에 맞습니다. 기존 lease·usage-limit·breaker 판정을 제거하지 않고 운영자 reconcile/repair를 명시한 변경을 확인했습니다. 단, 오류 원문을 테스트 기대값 때문에 일반 출력에 다시 넣는 것은 수용하지 않습니다(R4).
- `docs/zeus/reviews/**/*.py`에 한정한 E402/F401/I001 예외는 보관된 반례 원문을 보존하기 위한 선택으로 수용합니다. runtime/tests의 Ruff 검사나 F821 등 오류 검사는 제외하지 않았습니다. Codex가 넣은 보관 파일의 lint 문제 때문에 실패한 것은 구현 결함으로 세지 않습니다.
- 독립 Windows 실행: 일회용 Docker PostgreSQL/Redis에서 관측 테스트 **75 passed, 0 skipped**, 생성한 스택만 정리 완료. 변경 관련 기존 테스트 네 파일 **76 passed, 10 skipped**(integration 미설정), Ruff 통과.
- 독립 반례 **6 passed**는 아래 결함의 재현 성공을 뜻합니다. MemoryStore·실제 임시 파일·결정적 실패 주입·fake provider를 사용했으며 운영/실제 모델 증거가 아닙니다.
- CI 최종 head **10/10 SUCCESS**. 제출 `environment-runs-004`의 두 호스트 head는 `0dba6f8100fa8f2ae94d7dad2159ced7edc82dbe`입니다. Windows 1519 passed/14 skipped, WSL 1525 passed/8 skipped, Docker 각 17 passed, 단계별 stdout/stderr hash·JUnit byte hash·identity_stable을 대조했습니다. src/scripts/uv.lock은 최종 head와 동일하며 pyproject 차이는 위 Ruff 예외 두 줄입니다. 이번 독립 검토에서는 WSL 전체 스위트를 재실행하지 않았습니다.

## R1 잔여 · P1 — 최종 업무 저장 실패와 termination 파일 실패가 재실행을 허용함

위치: `src/codex_harness/adapters/executor.py:692`, `:438`, `src/codex_harness/application/observations.py:472`.

반례 A: 정상 provider 실행·settlement·checkpoint 이후 `Workflow.complete`의 succeeded task 쓰기만 실패시켰습니다. 첫 실행은 **retry**, pending termination은 **0**이며 다음 실행이 provider를 다시 시작해 시작 횟수가 **2**가 됩니다. `_run`의 보호 경계가 checkpoint에서 끝나므로 그 뒤 task/result/outbox 수용은 여전히 일반 실패로 처리됩니다. 구현 작업의 capture 및 decision commit 등 `_run` 호출 뒤 경계도 같은 기준으로 추적해야 합니다.

반례 B: provider 진입 후 transport 오류에 더해 termination 파일 쓰기가 OSError를 내면, `record_termination`은 PG 기록까지 도달하지 못합니다. PG가 정상이어도 task가 retry, pending 0, provider 두 번 실행입니다. 안전장치의 파일 쓰기 실패가 안전장치 자체를 우회합니다.

수정 요구: 실제 업무 결과/후속 outbox의 내구성 있는 수용까지 실행 효과의 미확정 상태를 유지하십시오. 기록된 결과로 수용만 멱등 재개할 수 있으면 그 경로를 사용하고, 증명할 수 없으면 차단해야 합니다. termination 파일 실패도 명시적으로 다뤄 PG 차단 또는 실행 전 기록한 내구성 있는 미확정 표식이 다음 claim을 막게 하십시오. 두 저장소가 모두 불가한 경우에도 이미 실행된 시도를 정상 retry로 처리해서는 안 됩니다.

또한 제출 설명의 “기존 실패 기록과 같은 트랜잭션에서 blocked”는 현재 코드와 다릅니다. `_fail_task`가 먼저 commit하고 `_block_after_failure`가 별도 transaction을 엽니다. 실제 원자성 범위로 문서를 정정하고, 그 사이 종료/다른 세션 claim 및 decision 경로를 검사하십시오. 처음 요청했던 L04 범위이며 새 기능 요구가 아닙니다.

## 판단 3 잔여 · P1 — 살아 있는 origin의 새 보류 알림을 상속 세션이 삭제함

위치: `src/codex_harness/application/observations.py:390` `_flushed`, `:419` `_inherit_pending_alerts`.

A가 PG 단절 중 알림을 기록 → B가 A의 보류 파일을 상속 → 살아 있는 A가 새 알림을 추가 → PG 복구 후 B가 자신의 snapshot만 commit하는 순서를 재현했습니다. B는 자신이 commit한 event ID만 지우지 않고 **A의 파일 전체**를 삭제합니다. A 종료 후 C에는 상속할 pending이 없고 새 알림은 PG `observation_alerts`에 없습니다. 일반 spool을 수집해도 alert 채널로 재생되지 않습니다.

수정 요구: commit한 `(origin, event_id)`에 대해서만 내구성 있는 확인 처리를 하십시오. origin의 새 기록과 상속 수집기가 충돌하지 않는 소유권/원자적 갱신 규칙이 필요합니다. `_flushed`가 현재 프로세스의 전체 큐도 무조건 비우는 경계, 복수 상속 세션, commit 응답 유실, 원본 프로세스 종료를 함께 회귀 검증하십시오. 각 origin이 이미 죽었다고 가정해서는 안 됩니다. 오케스트레이터/팀장/팀원은 동시 실행됩니다.

## R3 잔여 · P2 — 세그먼트 10000부터 수집 대상에서 사라짐

위치: `src/codex_harness/adapters/observation_spool.py:38` SEGMENT, `segment_path`, `SpoolDirectory.spool_files`.

작성자는 `:04d`(최소 네 자리)로 파일을 생성하지만 독자는 `\d{4}`(정확히 네 자리)만 받습니다. index 10000의 정상 레코드는 작성 성공으로 보고되나 수집기는 **0 files/0 records**로 봅니다. 영구 무인 운영에서 조용한 수집 누락과 용량 회수 실패가 재발합니다. 반례는 10000번 회전을 실제 수행했다고 주장하지 않으며, 도달 가능한 경계 index를 직접 설정해 생산/수집 계약 불일치를 검증했습니다.

수정 요구: 생산/파싱/정렬/회수의 index 계약을 일치시키고 9999→10000 경계를 시험하십시오. per-run 미확인 바이트 상한과 **전체 runtime 디렉터리**의 보존/상한은 구별해야 합니다. 오래된 process health/closed/ACK/부분 segment의 보존·회수 및 여러 producer 전체 공간 정책도 명시하십시오. 현재 per-run 상한을 전체 디스크 상한으로 표현하지 마십시오.

## R4 잔여 · P1 — 식별자 정규식은 비밀정보 검사가 아니며 원문 오류가 CLI로 회귀함

위치: `src/codex_harness/domain/observation.py:33`, build_event, `src/codex_harness/application/observations.py:80`.

반례 A: 기존 redactor가 인식하는 합성 GitHub token 형태(`ghp_` + 반복 문자)를 correlation_id/evidence_refs에 넣으면 REFERENCE 정규식을 통과하여 일반 spool 및 PG observations에 그대로 남습니다. 문자 집합 검사는 credential shape를 배제하지 않습니다. operator 및 다른 공통 identity 필드도 같은 원칙으로 검토하십시오.

반례 B: settlement 감사 쓰기 오류에 합성 CANARY가 있으면 새 `PostExecutionRecordFailure`가 `{cause}` 원문을 포함합니다. 그 원문이 `attempt_outcomes`를 통해 `execute_one` 반환 객체와 `cli.emit` stdout에 그대로 노출됩니다. 이 경로는 이전 settlement 예외가 타입·record ID만 표시하던 동작에서 회귀했습니다. 일반 출력이므로 “기존 task 실패 기록은 raw”라는 주석으로 L09에서 제외할 수 없습니다.

수정 요구: 식별자 형식 검사와 별도로 알려진 credential 형태를 거절하거나 안전한 참조 규칙을 적용하십시오. 타입+digest+boundary+record ID로 진단할 수 있게 하고 원문은 승인된 접근 제한 artifact 경계에서만 취급하십시오. cause 객체를 내부에 유지하는 것과 `str(exception)`/CLI/notice/실패 요약에 직렬화하는 것은 별개입니다. 새 반례의 CLI stdout·PG·spool까지 비밀 검출 0을 요구하는 회귀로 바꾸십시오.

## 다음 제출

같은 PR 브랜치에서 위 잔여만 수정하고, 반례 6개를 안전 결과를 요구하는 테스트로 편입하십시오. R2 등 이미 해소된 항목은 재설계하지 않아도 됩니다. README 6절의 “notice 미발행” 설명도 현재 구현과 맞춰 갱신하십시오. 정확한 head와 실패 이력·관련 Windows/WSL 증거·CI를 제출하면 재검토합니다. 원본 전체 분석, 이슈 종료, U002 착수는 별도 승인 범위로 유지합니다.
