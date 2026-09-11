# PR #71 — U001 3차 검토

Head `919d278065dd5006a293bff518f0c9bad476df00` (runtime/test `3d6e757aeb3ce375c9c3973921539df6c78563aa`). **병합 보류, 아래 네 경계 수정 후 재검토**. #17/#1/#11 OPEN, U002 미착수 유지.

## 확인한 개선과 독립 검증

실행 예약과 같은 PG transaction에 unconfirmed를 기록하고 완료 수용과 함께 닫는 변경, 실패 기록/blocked/notice의 transaction 통합, 종료 파일 실패 시 PG 기록을 계속하는 변경을 확인했습니다. 이전 최종 쓰기 실패·종료 파일 실패 반례는 차단됩니다. origin 소유 파일과 replayer별 event ID ACK, 9999→10000 숫자 순서, 알려진 token 형태 거절, settlement 예외의 원문 제거도 이전 반례를 해소했습니다. R2 reconcile의 기존 수용 판단은 유지합니다.

- 독립 Windows 일회용 Docker PG/Redis 관측 테스트 **99 passed, 0 skipped**. 생성한 스택만 정리 완료. 실제 모델 호출 없음.
- 변경 관련 executor/recovery/workflow 기본 테스트 **92 passed, 39 skipped**(integration 환경 미설정). Ruff 통과.
- 추가 경계 반례 **4 passed**는 결함 재현 성공이며 제품 수용 pass가 아닙니다. MemoryStore·실제 임시 파일·결정적 오류 주입·fake provider 사용.
- 별도 **실제 WSL/Linux 파일시스템 반례 1개**에서 살아 있는 작성자의 열린 파일 삭제와 이후 경로 없는 쓰기 성공을 확인했습니다. 파일 mtime을 조작한 경계 시험이며 8일간 운영했다고 주장하지 않습니다. 임시 디렉터리만 사용했습니다.
- 최종 head CI **10/10 SUCCESS**. 제출 environment-runs-005 Windows **1543 passed/14 skipped**, WSL **1549 passed/8 skipped**, Docker 각 **17 passed**의 로그/JUnit hash와 identity_stable을 대조했습니다. 두 영수증 head는 3d6e757이며 최종 head와 src/scripts/uv.lock/pyproject 차이가 없습니다. WSL 전체 스위트를 이번에 독립 재실행한 것은 아닙니다.

## R1 잔여 · P1 — 표식 조회 실패가 실행 허용으로 바뀜

`application/observations.py`의 `pending_terminations`는 PG 조회 예외를 잡고 로컬에 있는 목록만 반환합니다. `_run`은 이 목록이 비면 예약을 진행하며, 예약 transaction은 과거 미확정 표식을 다시 확인하지 않습니다.

반례: 실제 claim으로 얻은 이전 lease에 unconfirmed 표식을 PG에 남기고 lease를 만료시킵니다. 다음 claim에서 `observation_terminations` scan **한 번만** 실패시키고 이후 DB 동작은 정상으로 둡니다. local termination 파일이 없는 상태에서 provider가 시작되고 task는 succeeded가 됩니다. 이전 PG 표식은 여전히 unconfirmed입니다. 예약 당시 PG가 정상인 것만으로 앞선 조회가 완전했다고 보장할 수 없습니다.

수정 요구: 관측용 조회의 best effort 결과를 실행 허가로 사용하지 마십시오. 과거 미확정/종료 표식의 권위 있는 확인을 **예약과 같은 PG transaction**에 결속하고 확인 실패 시 provider 시작 0을 보장하십시오. 단절·query 실패·복구 사이의 경계를 회귀 테스트에 넣고 `_failure_disposition` 등 같은 조회 결과로 안전 판정을 내리는 호출부도 대조하십시오. 기존의 정상 다단계 호출은 유지하되 이전 attempt의 unknown을 건너뛰면 안 됩니다.

## 판단 3 잔여 · P1 — 스풀에 한 줄도 없는 보류 알림은 복구 후 재생되지 않음

`Collector.collect`는 일반 spool row를 처리하는 transaction 안에서만 `_flush_pending`을 부릅니다. 정작 spool full/쓰기 불가로 발생한 알림은 row 없이 pending 파일에만 존재할 수 있습니다.

반례: 1-byte 스풀 상한과 PG 단절로 원본 이벤트 및 알림의 spool 기록이 모두 실패하게 하고 pending 파일을 남깁니다. 프로세스 종료 후 PG를 복구하고 새 observer/collector로 세 번 수집해도 **records 0, PG observation_alerts 0**, inherited pending은 그대로입니다. 새로운 일반 이벤트가 없으면 보류 알림이 영구 대기합니다. 파일 복구·spool 실패는 바로 이 알림이 필요한 상황입니다.

수정 요구: pending alert의 내구성 있는 replay/commit/ACK를 일반 spool row 유무와 독립적으로 진행하십시오. pending-only 복구, spool 디렉터리 쓰기 불가, 중간 commit/ACK 실패, 재시작·동시 상속자를 시험하고 기존 event ID ACK 안전성은 유지하십시오.

## R3 잔여 · P1 — 파일 나이로 live writer를 종료 판정해 로그를 삭제함

`SpoolDirectory.run_finished`는 closed marker 없이도 최근 spool mtime이 7일보다 오래되면 종료로 판정합니다. `prune`은 이 판정으로 마지막 활성 세그먼트까지 unlink합니다. 시간 경과는 프로세스 종료나 작성 권한 해제 증거가 아닙니다.

실제 WSL 반례: FileSpool의 descriptor를 열어 둔 채 한 레코드를 쓰고 ACK한 뒤 mtime만 8일 전으로 바꿨습니다. prune은 그 파일을 삭제했습니다. **같은 살아 있는 writer의 다음 append는 성공을 반환하지만 visible segments는 0**이며 수집 경로가 없습니다. Linux의 열린 inode에만 쓰이므로 이후 레코드는 수집할 수 없습니다. 장기 정지/복구·시계 이동에도 적용되는 L05/L06 안전성 결함입니다.

수정 요구: retention age는 GC 후보 선정에만 쓰고 작성자 종료/쓰기 권한 해제를 별도로 증명하십시오. 명시적으로 닫힌 또는 회전으로 봉인된 세그먼트를 회수하고, 불명확한 활성 마지막 파일은 보존·보고하십시오. Windows/WSL의 열린 파일 의미 차이를 시험하고, 프로세스가 살아 있는 경우와 실제로 종료된 경우를 구분해야 합니다. 숫자 index 수정과 디렉터리 총량/하드 캡 구분은 수용합니다.

## R4 잔여 · P1 — 최종 업무 저장 오류는 여전히 원문을 CLI에 노출함

`PostExecutionRecordFailure`의 안전한 메시지는 `_run` 내부 예외만 덮습니다. `Workflow.complete`의 최종 succeeded 쓰기가 실패하면 일반 except → `_failure_disposition` → `_fail_task`로 가면서 원래 exception이 그대로 failure/diagnosis/attempt_outcomes에 직렬화됩니다.

반례: 최종 task 쓰기에 합성 CANARY를 포함한 OSError를 주입했습니다. task는 올바르게 blocked지만 **반환 JSON과 cli.emit stdout에 CANARY가 검출**됩니다. settlement 반례만 깨끗해진 상태이며 “전체 실패 경로에서 0”은 아직 성립하지 않습니다.

수정 요구: 최종 완료/decision commit/capture 등 `_run` 밖의 실패도 boundary·타입·digest·record ID를 사용하는 공통 공개 표현으로 바꾸십시오. 내부 cause 객체 보관과 공개 직렬화는 분리하고, CLI/일반 failure 요약/notice/diagnosis 및 로그를 함께 검사하십시오. 오류 문장 검사 때문에 인증정보 원문이 필요하지는 않습니다.

## 별도 보고된 환경 실패의 판정

- WSL 첫 disposable run은 `test_postgres_pause_is_not_a_clock_step[2]`에서 호스트 포트가 30초 동안 ConnectionRefusedError를 반환해 **16 passed/1 error**였음을 원본 로그에서 확인했습니다.
- runtime head의 pull_request run **34577826760 attempt 1**은 disposable DB 검증에서 **database system is starting up**, host interruption setup에서 **server closed the connection unexpectedly**로 실패했습니다. attempt 2는 통과했습니다. TCP connect 확인과 실제 SQL 준비 완료 사이의 차이가 조사 후보입니다. 컨테이너 내부 상태까지 확인한 확정 원인은 아닙니다.
- 최종 head pull_request run **34579463569 attempt 1**, Windows 3.12 job **103199406524**는 `test_launchers_handle_corrupt_pid_custom_paths_and_duplicate_start`의 PowerShell이 **120초 TimeoutExpired**로 실패했습니다. attempt 2 통과는 확인했지만 원인은 미확정입니다.

이 PR에서 해당 파일을 변경하지 않았다는 사실과 결함 여부는 별개입니다. 재실행 통과를 원인 해결로 세지 않으며 기존 환경/복구 이슈에 실패 근거를 남깁니다. U001의 위 네 코드 결함과 분리해 추적하고, 근거 없이 테스트 삭제·timeout 증가·자동 retry로 가리지 마십시오.

## 다음 제출

같은 PR에서 위 네 경계의 구현과 안전 결과 회귀를 제출하십시오. 이미 수용한 reconcile/index/ACK 소유권 변경을 다시 설계할 필요는 없습니다. 정확한 SHA, 실패 보존, 관련 Windows/WSL 증거 및 CI를 갱신하면 재검토합니다. 병합·이슈 종료·U002 착수 판단은 Codex가 유지합니다.
