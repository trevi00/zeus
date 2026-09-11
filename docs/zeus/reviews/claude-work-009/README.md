# PR #71 — U001 1차 검토: 수정 후 재검토

검토 head: `f2ce4d5a0f1a1b135f0e94ee91cd932fe1b5992b`. 수용 기준: `docs/zeus/autonomy/design-001/U001-logging-contract.md` L01–L10.

CI 10/10 SUCCESS와 제출 영수증의 결속은 확인했습니다. 그러나 아래 네 결함 때문에 U001 병합을 보류합니다. #17/#1/#11은 OPEN 유지, U002 착수는 아직 승인하지 않습니다. Claude는 같은 브랜치에서 이 범위의 구현·회귀 테스트·증거를 수정해 주십시오.

## 독립 검증

- Windows 기본 관측 테스트: **35 passed, 16 skipped**. integration 환경 미설정으로 PG/Redis 대상 skip.
- 별도 일회용 Docker PostgreSQL/Redis를 올린 Windows 관측 테스트: **51 passed, 0 skipped**. 생성한 `zeus-verify-*` 스택만 정리 완료. 모델 transport는 기존 테스트 대역이며 실제 모델 호출 증거가 아닙니다.
- 별도 반례: **6 passed**. 여기서 pass는 안전성 통과가 아니라 **결함 재현 성공**입니다. MemoryStore·실제 임시 스풀 파일·결정적 실패 주입을 사용했고 운영 환경 증거로 세지 않습니다.
- 첫 반례 실행은 검토 픽스처의 role 누락으로 1 failed/3 passed였습니다. role을 명시한 뒤 4개, 추가 redaction 2개까지 최종 6개 재현. 첫 실패 JUnit도 보존했습니다.
- 제출 Windows/WSL 영수증은 head `e36700332266a680984542bda8d9ede7fc828114`에 결속되어 있습니다. 최종 head와 `src/`, `scripts/`, lockfile, pyproject의 차이 없음, 각 3단계 stdout/stderr digest, JUnit byte hash, identity_stable을 대조했습니다. Windows 1495 passed/14 skipped, WSL 1501 passed/8 skipped, Docker 각 17 passed라는 제출 수치를 확인했습니다. 이번 검토에서 WSL 전체 스위트를 다시 실행한 것은 아닙니다.

## R1 · P1 — provider 실행 이후 보호 범위가 settlement에만 한정됨 (L04)

위치: `src/codex_harness/adapters/executor.py:430` 예외 처리, `:474` settlement 보호, `:502` persist_result.

`runtime.run`이 시작된 뒤 예외를 내면 reservation은 `unsettled_unknown`이 되지만 termination 기록 없이 task가 retry로 돌아갑니다. 결과를 받은 뒤 settlement까지 성공해도 `persist_result`가 실패하면 동일하게 재실행됩니다. 두 반례 모두 `execute_one` 두 번으로 provider 시작 횟수가 **2**가 되었고 pending termination은 **0**이었습니다. 외부 동작 이후 응답/저장 실패를 안전한 재시도로 취급할 수 없습니다.

수정: provider가 시작되지 않았음이 증명된 거절과, 실행 후 효과가 미확정인 실패를 구분하십시오. 실행 진입 이후 transport/progress/cleanup/정산/artifact/checkpoint/결과 수용 저장의 실패 경계를 추적하여, 증거와 reconciliation 차단 없이 새 실행을 허용하지 않도록 하십시오. `provider_started`도 현재 breaker admission 이전에 기록되므로 실제 시작과 실행 의도를 구분해야 합니다. 실제 호출 없이 회귀 테스트에서 외부 동작 카운터를 먼저 증가시킨 다음 연결/저장 실패를 발생시켜 다음 시도에서 증가하지 않음을 검증하십시오.

## R2 · P1 — reconciliation 저장 실패가 마지막 차단 기록을 제거함 (L04)

위치: `src/codex_harness/application/observations.py:425`, `src/codex_harness/adapters/observation_spool.py:226`.

`resolve_termination`은 먼저 로컬 pending 파일을 resolved로 옮겨 삭제하고, 그 뒤 PG decision/audit를 씁니다. PG 단절 중 생성되어 로컬에만 있는 termination에 대해 reconcile도 PG 실패시키면 명령은 실패하지만 pending은 사라집니다. PG 복구 후 `pending_terminations(task)`는 빈 목록이고 DB의 termination/audit도 없습니다.

수정: PG decision과 필수 감사가 확정되기 전에는 차단을 해제하지 마십시오. PG commit 후 로컬 finalize 실패/프로세스 종료, commit 응답 유실, 같은 명령 재전달에도 재시도 가능한 프로토콜이 필요합니다. 파일/DB 사이에 단일 트랜잭션이 있다고 가정하지 마십시오. `rerun`과 `discard`의 권한 효과 및 기존 execution-recovery 경로도 문서·테스트로 결속하십시오. 현재 termination 생성은 `open('x')`로 직접 쓰므로 README의 “임시 파일 + os.replace 원자 기록” 설명과 다릅니다. 부분 생성 파일은 안전하게 차단·복구하도록 시험하고 구현에 맞게 문서를 정정하십시오.

## R3 · P1 — 정상 수집 후에도 스풀이 영구 포화됨 (L06)

위치: `src/codex_harness/adapters/observation_spool.py:118`, `src/codex_harness/application/observations.py:444`.

용량 검사는 파일의 누적 크기에 적용하지만 Collector는 ACK 오프셋만 전진시킵니다. ACK된 공간의 회수/세그먼트 회전 경로가 없습니다. 작은 상한으로 매 이벤트 직후 정상 수집해도 결국 `ack == file size`인 상태에서 모든 후속 이벤트가 `dropped_spool_full`로 거절됩니다. 기본 32 MiB에서는 같은 결함이 늦게 나타날 뿐입니다. 프로세스 재시작마다 파일도 계속 쌓입니다.

수정: 미확인 데이터 보존과 확인된 세그먼트 회수/보존 정책, 전체 디렉터리 상한을 정하고 구현하십시오. 활성 파일을 단순 truncate하여 작성자/수집기 offset을 깨뜨리면 안 됩니다. Windows/WSL에서 계속 생산·수집하며 상한을 여러 번 넘겨도 기록이 이어지고, sink 단절·재시작·ACK 유실 후 중복/유실 없이 복구되는 증거가 필요합니다.

## R4 · P1 — redaction이 관측 경계 전체를 덮지 않음 (L09)

위치: `src/codex_harness/application/observations.py:429` decision, `:514` schema_refused, `src/codex_harness/domain/observation.py` build_event 공통 필드.

`--reason 'password=<합성 canary>'`가 resolved termination 파일, PG 행, CLI 반환 객체에 그대로 남습니다. `correlation_id`의 같은 문자열도 producer/collector를 통과해 일반 observations에 남습니다. 스키마가 거절한 outcome 값은 jsonschema 오류 문장을 통해 quarantine의 defect에 원문으로 저장됩니다. 모두 합성 문자열로 재현했으며 실제 인증정보를 사용하지 않았습니다.

수정: decision/operator/reason, 공통 identity/correlation 필드, schema 오류/격리 경로까지 직렬화 전 정책을 적용하십시오. 상관관계 식별자의 임의 치환으로 서로 다른 실행이 합쳐지지 않도록 거절 또는 안정적인 digest 참조 규칙을 설계하십시오. 이물 오류는 승인된 타입+digest 정책을 일관되게 사용하고, 보호된 artifact가 필요하면 참조만 일반 로그에 넣으십시오. producer뿐 아니라 CLI 반환, PG, 파일, 수집 거절, 알림, JUnit을 함께 검사하는 회귀 테스트가 필요합니다.

## 보고된 다섯 설계 판단에 대한 결정

1. `outcome=observed`: 수용합니다. heartbeat/backlog와 실행 미확정을 구별하는 의미가 적절합니다.
2. `reconciliation_required` notice: 기존 execution.notice/outbox를 재사용하는 방향으로 진행하십시오. reason 계약의 producer/consumer/schema를 함께 갱신하고 이전 소비자 호환성·재전달·정확한 수신자 검사를 추가하십시오. DB blocked만으로 팀장에게 알림이 전달됐다고 볼 수 없습니다. 관측 이벤트에 업무 권한을 주지는 않습니다.
3. 새 외부 알림 채널을 만들지 않은 선택은 수용합니다. `observation_alerts`의 recorded는 PG 저장이며 외부 전달/확인이 아닙니다. 보류 알림은 프로세스 재시작과 PG commit 실패 이후에도 재생 가능함을 증명하십시오. 현재 `_flush_pending`의 commit 전 pop과 메모리 pending 큐도 이 검증에 포함하십시오.
4. 이물 오류를 타입+digest로 남기는 정책은 수용합니다. R4의 누락 경로까지 일관되게 적용해야 합니다.
5. heartbeat의 갱신 행 반환은 수용합니다. 반환이 관측용임을 유지하고 기존 lease/fencing 계약을 바꾸지 마십시오.

수정 제출에는 위 반례를 안전한 결과를 요구하는 회귀 테스트로 바꿔 포함하고, 정확한 수정 SHA·실패 이력·Windows/WSL 관련 실측·CI를 남겨 주십시오. 코드 수용과 실제 무인 운영 승인, #1/#11 전체 분석 완료는 별도 판정입니다.
