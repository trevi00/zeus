# U002: 실제 Claude 팀원 실행 설계

Codex 분석·설계, 2026-09-12. 기준 `02efbd081cceee24aa487105618e2bf8947568be`. U001은 PR #71, merge `5a7a7bcb8f0da5c948bb5eda8d3758ff50c2f154`에서 수용됐다. 이 문서로 U002 구현 착수를 허용한다. 분석·선정·수용 기준·독립 검토·병합 판단은 Codex, 명세에 따른 구현·테스트·실행 증거·PR 제출은 Claude 책임이다.

## 범위와 분석 결과

이번 목적은 `worker:implementation`에 명시적으로 배정한 작업을 실제 Claude Code로 실행하고, 기존 원장과 증거 검사에 연결하는 것이다. 전체 무인 PR 반복·카나리아 운영 전환은 U004/U005에 남긴다. source-manifest.json은 아래 제한된 분석의 기준 파일을 고정하며 로컬 reference 전체 의미 분석의 완료 목록이 아니다. 미커밋 분석 자료와 커버리지 원장은 변경하지 않는다.

| 확인 경로 | 직접 확인한 현재 동작 | U002 결정 |
|---|---|---|
| organization.json / cli.serve / bus.py | conductor→lead→worker, 수신자 stream·workers group·재전달, 권한 확인→원장 수락→outbox→ACK | 재사용. 새로운 버스·조직 계층을 만들지 않는다 |
| executor._run / ports.Runtime | AppServer 직접 생성, callback·tick을 쓰지만 port에는 없음 | 명시적 Runtime factory와 provider별 어댑터 계약으로 연결 |
| model_routing.select_model | 구현 중요도와 무관하게 미자격 작업은 Astra 유지 | Codex 기존 정책 유지. Claude 모델은 별도 설정과 명시적 작업 배정으로 선택 |
| invocation.py / invocation_ledger.py | app_server 지원표, Codex 모양 이벤트로 모델·usage 판독, PG 예약·감사 | provider별 지원표와 관측 정규화 추가. 원장 복제 금지 |
| executor implement / execution_output.py | worktree 준비→실행→capture→독립 evidence 검사→완료 | 같은 흐름에 Claude 삽입. 자기보고를 검증으로 승격하지 않음 |
| checkpoint / execution_progress | agent 세션 조회, task·context binding, thread_id 저장 | provider/session/작업 결속 추가. U002 Claude는 새 프로세스·새 세션에서 증거 기반 복구 |
| commands.run_process / AppServer | Windows/POSIX 프로세스 종료와 UTF-8 처리 있으나 일괄 communicate는 heartbeat 스트리밍에 부족 | 유용한 부분 재사용, 수명 전체 제한과 실제 자손 종료 확인 추가 |
| U001 observation | provider 진입 전 예약·unconfirmed, 진입 후 실패 차단, 로그·spool·notice | Claude도 같은 경계 사용. 초기화 중 외부 효과도 보호 |

## 실행 계약: INV-CLAUDE-WORKER-001

1. **배정과 권한.** Git 관리 실행 정책에서 기본 provider는 기존 Codex로 유지한다. 승인된 `worker:implementation`의 implement 작업만 Claude 경로로 선택 가능하다. 메시지 본문·모델 출력이 provider, role, parent, tool 권한을 바꿀 수 없다. 설정 provider/model/workload/capability 불일치는 spawn 전에 거절한다. Claude 불가 시 Codex로 묵시적 fallback하지 않는다. 선택 정책 버전·설정 digest를 예약 및 증거에 남긴다.
2. **모델 축 분리.** Claude 모델 이름을 Astra/Sol/Terra에서 추측·치환하지 않는다. 명시적 Claude 모델 설정이 필요하다. 요청 모델, provider가 보고한 모델, 확인 불가를 구별한다. 실제 호출 성공은 전 작업 자격 이전이 아니다. 기존 Codex 모델 라우팅과 자격 정책은 변경하지 않는다.
3. **어댑터 계약.** 표준 라이브러리 기반 내부 port에 실행 요청, 제한, event callback, tick/cancel, 정규화된 결과를 표현한다. provider SDK/프로세스 타입은 adapter 안에 둔다. 각 provider의 옵션 지원·미지원·미확인을 선언하고 미지원 값을 무시하지 않는다. `read_only`를 prompt만으로 강제 지원한다고 주장하지 않는다. Claude 검토 역할은 이번 배정 대상이 아니다.
4. **프로세스 입출력.** 우선 Claude Code CLI `-p`, text stdin, stream-json stdout을 사용한다. prompt는 argv/shell 문자열에 넣지 않는다. shell=False의 인수 배열, UTF-8, 공백·한글 경로를 지원한다. stdout/stderr 동시 배출, 줄·전체 바이트·queue 상한, monotonic 전체 deadline을 둔다. 읽기·stdin 쓰기가 막히거나 이벤트가 없어도 tick/cancel이 작동해야 한다. 비밀이 들어갈 수 있는 schema/context/config 원문을 명령 로그에 노출하지 않는다.
5. **초기화도 외부 효과.** 예약·필수 감사·unconfirmed 표식을 commit하고 현재 lease를 확인한 뒤에만 provider를 시작한다. Claude spawn 이후 hook/초기화도 외부 효과가 가능하므로 그 이후의 예외를 'provider 미진입'으로 오인해 재시도하지 않는다. U001 종료 증거·blocked·reconcile을 그대로 사용한다. 영수증 저장 실패나 PG 단절로 호출을 중복 시작하지 않는다.
6. **프로세스 종료.** timeout, lease 상실, 취소, reader 실패 시 자신이 생성한 프로세스 트리만 종료하고 종료 확인 후 수습한다. Windows 자손과 POSIX 그룹을 실제 시험한다. 확인 실패는 unknown/blocked이며 다음 실행을 허용하지 않는다. global kill, 운영 서비스 재시작은 금지한다. 호스트 직접 CLI 실행은 강한 보안 격리가 아니며 이미 시작한 외부 효과를 취소할 수 있다는 주장은 하지 않는다.
7. **이벤트/결과.** provider 원본 타입과 normalized 타입을 구별한다. Claude 이벤트를 Codex 서버가 실제 보낸 이벤트로 위장하지 않는다. 정상 terminal result, process exit, 구조화 출력 유효성, 실행 결과 검증을 별도 기록한다. exit=0·assistant 텍스트·tool-only·빈 결과는 성공 증거가 아니다. terminal 누락·상충 terminal·잘린 JSON·잘못된 중첩 타입·권한 거절·budget 종료를 명시적으로 분류한다. schema는 기존 preflight와 completed_output을 통해 로컬에서 독립 검증한다. provider의 schema 준수 주장에 의존하지 않는다.
8. **usage.** input/output/cache 항목의 의미와 누적/증분 기준을 명시한다. stream 재전달·partial delta로 이중 합산하지 않는다. 모르는 사용량·모델·비용은 null/unknown이다. provider 보고 비용은 출처 있는 추정치이며 실제 청구액으로 부르지 않는다. 동일 작업의 provider 변경으로 예약·차단·예산이 초기화되지 않도록 한다.
9. **세션.** U002 Claude는 task/attempt마다 새 세션을 사용한다. `--continue`나 마지막 세션 자동 선택은 사용하지 않는다. checkpoint에는 provider, provider_session_id, agent, task, generation, attempt, invocation, basis revision, workspace identity, 정책 digest를 결속한다. 새 attempt는 기존 권위 있는 checkpoint/artifact를 context compiler로 받아 복구한다. 다른 provider/task/workspace 세션은 재개하지 않는다. native resume는 미지원으로 선언하며 U002 수용 요건이 아니다.
10. **통신.** provider stream은 실행 내부 데이터다. six-W 메시지는 기존 Workflow/outbox가 검증된 sender/recipient와 작업에서 생성한다. Claude가 출력한 six-W JSON은 명령 권한이 없다. Redis ACK 유실·XAUTOCLAIM에서도 PG 작업 수락과 실행 fencing이 중복 실행을 막아야 한다. ACK만으로 작업 완료·PR 승인·지식 승격을 하지 않는다.
11. **환경과 로그.** 자식에 Zeus PG/Redis 자격증명·운영자 서명키를 전달하지 않는다. 인증에 필요한 provider 설정만 참조하고 값은 기록하지 않는다. 상속 hook/MCP/plugin/환경 변수가 재현성에 영향을 주므로 유효 설정·CLI 버전·실행파일 identity·작업 revision·권한 정책의 비밀 제거 manifest를 기록한다. 기존 사용자 전역 권한 설정은 변경하지 않는다. 작업별 정책은 기존 승인 범위에서 명시하며 prompt만을 격리 수단으로 쓰지 않는다. U001 일반/개발/운영 로그에 같은 실행 identity를 연결하고 canary 유출을 검사한다.

## 수용 시험

| ID | 자극 | 요구 결과 |
|---|---|---|
| C01 | 기본 설정, Claude implement 배정, 잘못된 역할/provider/model/옵션 | 기존 Codex 회귀 유지, 허용 배정만 Claude 실행, 거절 시 spawn 0 |
| C02 | 실제 임시 자식이 stdin 한글·공백 경로를 읽고 stdout/stderr를 동시에 출력 | 내용 hash 일치, prompt argv 노출 없음, 상한·tick 유지 |
| C03 | 정상 구조화 결과, exit0 빈 결과, tool-only, malformed/partial/중복/상충 terminal | 원본과 정규화 근거 보존, 잘못된 성공·예외 원문 유출 없음 |
| C04 | usage 누락, 누적 usage 반복, 요청/보고 모델 불일치 | unknown 보존, 이중 합산 없음, provenance 정확 |
| C05 | PG 예약/감사 실패 및 spawn 직후/최종 저장 실패 | 사전 실패 spawn 0, 진입 후 미확정 차단·notice·reconcile, 자동 재실행 0 |
| C06 | 무출력·stdout 포화·stdin 미소비·timeout·취소·lease 상실 | 유계 종료, 실제 부모/자손 종료 확인, stale 결과·후속 권한 전이 거절 |
| C07 | 다른 provider/task/workspace checkpoint와 새 attempt | 세션 오연결 0, 새 세션+결속된 context 복구, 미확정 작업 차단 유지 |
| C08 | 실제 PG+Redis에서 메시지 재전달·ACK 유실, 결과에 위조 six-W 포함 | 한 작업 수락·한 실행 예약, 권한 위조 거절, 팀장에게 기존 outbox 결과 전달 |
| C09 | 설정/오류/stdout/stderr에 합성 비밀 canary | 일반·개발·운영 로그, CLI, PG 공개 필드, spool, JUnit에서 원문 0 |
| C10 | 실제 Claude로 작은 임시 저장소 변경과 테스트 | worktree diff·직접 실행 테스트·provider receipt·PG task·six-W 결과 결속, 자기보고와 독립 실측 구분 |

C02/C03/C06의 명시적 프로토콜 시험 자식은 장애 주입 도구이며 실제 Claude 성공 증거가 아니다. C05/C08은 격리 PG/Redis로 실행한다. C10을 fake transport로 대체하지 않는다. Windows와 WSL에서 해당 경계를 실측하며 native Linux는 CI 결과와 WSL 증거를 구별한다. U001 관측 129건과 기존 invocation/breaker/output/progress/fence/recovery/routing/bus 검사를 회귀 분모에 포함하고 전체 Ruff/pytest를 실행한다.

## 실제 호출의 제한

실제 Claude 실측은 구현과 로컬 계약 검사가 통과한 뒤만 한다. Windows/WSL 각각 성공 1건을 목표로, 호스트당 최대 2회(총 4회), 호출당 300초, provider 예산 설정 USD 1을 상한으로 둔다. 중단 후 자동 증액·모델 fallback·반복 호출은 하지 않는다. 명시적 모델 및 적용 가능한 예산 제어를 검증할 수 없거나 인증이 없으면 실제 호출을 시작하지 않고 미실행 이유를 보고한다. 이 숫자는 청구액 보증이 아니라 러너 실행 한도다. 이미 있는 인증을 사용하며 API 결제 전환·새 자격증명 발급은 하지 않는다.

작업은 임시 Git 저장소에서 작은 stdlib 함수와 테스트를 작성·수정하고 러너가 실제 테스트를 재실행하는 범위다. 네트워크 게시·제품 배포·실금전 작업·현재 운영 교체는 제외한다. Claude 결과에서 commit/PR 제출을 직접 허용하지 않고 기존 하네스 source-control 경계를 재사용한다. U002 개발 PR 제출은 구현 담당 Claude가 정상 개발 절차로 수행한다.

## 공식 자료와 로컬 확인

2026-09-12 로컬 `claude --version`은 **2.1.269**. help/version은 실행파일 존재만 증명하며 모델 준비 완료가 아니다. 이 설계 작성 중 실제 모델 호출은 하지 않았다.

- [공식 programmatic 실행 문서](https://code.claude.com/docs/en/headless): stdin, stream-json, structured_output 및 종료 동작을 확인했다. 로컬 adapter의 성공·복구 판정은 위 Zeus 계약으로 독립 검증한다.
- [공식 CLI reference](https://code.claude.com/docs/en/cli-reference): 모델·세션·도구·설정·예산 관련 옵션을 확인했다. 설치 버전 help와 실제 실행에서 조합 지원을 다시 확인한다.

공식 문서의 bare 실행은 인증 방식에 영향을 줄 수 있다. 재현성을 이유로 기존 구독 인증을 API 방식으로 몰래 바꾸지 않는다. 구현자는 실제 인증을 유지하면서 적용 가능한 설정 통제를 선택하고, 통제하지 못한 상속 경로를 명시한다.
