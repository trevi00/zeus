# 독립 정적 판단

## 범위와 증거 수준

20개 primary의 전문을 읽었다. 파일별 정확한 전체 줄 범위와 SHA-256은 files.json에 기록했다. supporting.json의 명시 구간만 보조 근거로 읽었으며, 이름 검색으로 발견한 나머지 호출자를 읽었다고 주장하지 않는다. 원본 명령과 복구 지시는 분석 데이터로만 취급했다. 외부 문서의 현행 계약과 실제 Windows/Linux/WSL hook host 반응은 검증하지 않았다.

실행 결과가 아니라 코드가 구성하는 분기와 정적 실패 가능성을 판단한다. 예외·동시성·오탐 가능성은 이번에 재현한 결함이 아니다. 테스트 파일의 assertion은 시험 의도이며 현재 PASS가 아니다.

## 01 dispatch.py

8개 이벤트를 registry 순서대로 실행하고 가장 강한 판정을 합성한다. 앞 handler가 deny/block을 내도 뒤 handler를 계속 호출하므로 부수효과는 취소되지 않는다. `budget_ms`는 완료 후 초과 로그만 남기며 강제 중단하지 않는다. handler의 Exception은 정책에 따라 처리하지만 BaseException과 잘못된 반환 객체의 `.get` 실패는 개별 보호 범위를 벗어날 수 있다. stdout 격리도 없다. 최소 fallback은 전체 정책과 동등하지 않다.

저널 실패는 기록 실패 표시와 실제 영수증을 구분해야 한다. 입력 `_synthetic`의 출처 인증은 여기 없다. 크래시 ring과 통지 dedup은 잠금 없는 읽기·수정·고정 임시 파일 교체이므로 경합 시 누락 가능성이 남는다. Zeus에서는 판정, 실행, 효과 확인을 별도 PG 사건으로 기록하고 handler별 실행 기한과 오류 유형을 유지해야 한다.

## 02 dispatch.sh

runtime.yaml의 행 시작 `python_exe:`를 sed/head/tr로 추출하고 guard_boot를 exec한다. YAML 파서가 아니므로 인용·들여쓰기·주석 형식 지원을 가정할 수 없다. 핀 부재는 stderr 후 exit 0이어서 훅 보호가 실행되지 않은 상태와 정상 허용이 종료코드로 구분되지 않는다. 잘못된 실행 경로는 exec 자체 실패가 가능하다. POSIX sh 도구와 핀 형식은 Windows Git Bash, Linux, WSL 각각 검증이 필요하다.

## 03 guard_boot.py

dispatch import/실행의 BaseException을 잡아 최소 보호 경로와 쓰기 토큰을 검사하고 크래시 통지를 남긴다. 전체 정책 평가기를 대체하지 않으며 알 수 없는 도구·간접 쓰기를 닫는 보장도 없다. JSON 파싱 결과가 dict가 아닌 경우 `boundary_verdict`의 `.get`이 fallback 안에서 다시 실패할 수 있는 구조다. 통지 저장 실패를 BaseException으로 삼키는 경로도 있다. PostToolUse의 block은 이미 발생한 변경의 rollback이 아니다. Zeus 부트 실패는 독립 감시 영수증과 축소 모드를 명시해야 한다.

## 04 hud_launcher.sh

동일한 sed 핀 추출 후 cli/hud.py를 실행한다. 홈 진입 또는 핀 부재 시 빈 출력으로 종료하므로 HUD 공백은 정상 건강의 증거가 아니다. `.claude/settings.json` 1–5의 실제 등록을 읽었다. HUD 본체와 호스트 렌더링은 이번 보조 추적 범위 밖이다.

## 05 registry.py

8개 이벤트의 순서·fail 정책·시간 예산을 선언한다. PreToolUse의 3개 handler는 closed지만 내부에서 예외를 삼키면 이 정책에 도달하지 않는다. Stop은 heartbeat, reflector, reenforce, rollup 순서다. 예산 합계 30,100ms는 settings의 Stop 제한 30초보다 크며 순차 총시간을 보장하는 별도 deadline이 없다. handler 목록의 존재는 현재 등록 호스트가 실행했다는 증거가 아니다.

## 06 rlm_launcher.sh

핀 추출 후 engine/rlm_kernel.py를 실행한다. 핀 부재는 exit 1로 다른 두 launcher와 다르다. `.mcp.json`의 bash 명령 및 상대 launcher 인자를 확인했다. MCP 시작 cwd, Python 실행 가능성, RLM 커널의 현재 동작은 미검증이다. Zeus는 호스트별 경로·실행 파일 식별·프로토콜 handshake를 검증해야 한다.

## 07 notification/relay.py

Notification payload를 길이 제한한 메시지와 세션으로 로컬 notifications.jsonl에 append한다. 전달 성공·수신 확인·고유 event ID·재시도 lease 영수증은 아니다. append_line은 호출자 잠금을 요구하는 보조 함수이며 단일 append 자체가 배달 보장이 되지 않는다. 실제 guardian 소비자와 외부 전달은 읽거나 실행하지 않았다. Zeus outbox에서 발생, 전달 시도, 수신 확인을 구분해야 한다.

## 08 post_tool/heart_selfcheck.py

감시 대상 편집 뒤 synthetic PreToolUse 두 건을 sys.executable로 dispatch.py에 직접 보낸다. 따라서 실제 dispatch.sh→guard_boot→핀 해석 체인 전체를 실행하는 검사는 아니다. 런처 검사는 파일과 핀 존재 확인에 한정되며, strip 기반 핀 검사와 sed 행 시작 파싱도 다르다. deny 검사는 stdout 문자열 포함 여부이고 허용 Read는 빈 출력도 통과할 수 있다. 환경을 상속하므로 합성 프로브라도 실제 저널·통지 등 부수 쓰기를 만들 수 있다. 이번에는 실행하지 않았다.

PostToolUse 이후 검사이므로 변경 이전 권한 증명이나 되돌림을 대신하지 않는다. 감시 경로의 resolve는 payload cwd와 같은 의미라고 가정할 수 없다. tests/integration/test_heart_guard_smoke.py 37–125는 오류·dedup·프로브 시험 의도를 보여 주지만 실행 증거가 아니다.

## 09 pre_tool/agent_depth_guard.py

Task/Agent 도구에서 관측 깊이에 1을 더해 상한을 판단한다. lib/agent_depth.py 전문은 ORCH_DEPTH 부재·손상을 0으로 취급하고 자식 전파가 보장되지 않는다고 명시한다. 따라서 전역 재귀 상한·모델 자격·토큰 예산 강제가 아니다. Zeus는 실행기 소유의 parent/run 관계와 예산 예약을 사용해야 한다.

## 10 pre_tool/extracted_guard.py

기존 Markdown의 처음 400자에서 `origin: extracted` 문자열을 찾아 Write/Edit/NotebookEdit를 제한한다. MultiEdit, 셸, 삭제·이동 및 다른 생성 경로를 포괄하지 않는다. YAML provenance 인증이 아니고 파일 읽기 OSError는 내부에서 None으로 처리한다. registry closed 선언만으로 이 경로가 fail-closed가 되지 않는다. Zeus에서는 생성 출처와 승격 상태를 파일 문자열 대신 검증된 기록으로 연결해야 한다.

## 11 pre_tool/write_boundary.py

1–1102 전체를 읽었다. 정책 로딩·경로 대조, 셸 표면/쓰기 의도 분리, 대상 추출, push 검사, 무인 바인딩·프로젝트 fence, 사람 전용 채널 휴리스틱을 구현한다. 파일 도구는 deny 항목을 먼저 검사하며 collab_ask는 비무인 세션에서 ask로 완화한다. 셸에서는 동일 collab_ask 항목을 비무인 세션이면 건너뛰므로 파일 도구와 같은 사람 승인 보장이 아니다. 환경 스탬프와 바인딩/cwd의 조합은 실행 귀속 힌트이며 인증된 사람 권한 증명이 아니다.

파일 도구 fence는 프로젝트/임시 scratchpad를 기준으로 하지만 셸 fence는 하네스 홈에 대한 일부 쓰기 목적지로 좁다. 소스가 직접 인정하는 변수·공백 경로·붙인 플래그 등의 한계 외에도 알 수 없는 도구는 None으로 끝난다. 바인딩을 다시 읽지 못하거나 경로를 resolve하지 못하면 일부 fence가 열리는 분기다. 정책 JSON 전문의 역사적 카나리아 수치는 현재 테스트 결과가 아니다.

`git push` 문자열로 진입하는 검사와 lib/git_flow의 명시적 opt-in을 확인했다. pinned `.claude/git-flow-overrides.md`는 lint만 켜고 direct_push_main deny는 선언하지 않는다. push gate는 최대 90초인 반면 실제 PreToolUse hook timeout은 10초다. 원문 자체의 lint 10.4–10.7초 주장은 과거 주장이나, 두 timeout 계약의 불일치는 정적으로 존재한다. 호스트 timeout 시 최종 권한 처리와 lint 하위 프로세스 종료는 미검증이다. 이 파일은 최종 OS 보안 경계가 아니며 Zeus에서는 실행 요청의 구조화된 권한, PG 정책 버전, 독립 검증 증거로 옮길 후보일 뿐이다.

## 12 prompt/promptlog.py

사용자 프롬프트를 SQLite에 적재하고 20,000자 초과를 잘라 원래 길이와 truncated를 기록한다. 이 제한은 DB 전체 크기나 보존 기한이 아니다. hook ID 중복 억제는 없고 handle의 Exception은 조용히 삼켜져 dispatch 누락 로그에도 보이지 않는다. 2초 DB 연결 제한은 300ms의 soft 예산보다 길다. select 결과가 truncated/cwd를 제외하므로 후속 요약에서 원문 완전성을 별도로 표시해야 한다. Zeus 경험 인수는 원문 해시·절단·보존 상태와 사용자 의도를 함께 유지해야 한다.

## 13 prompt/seeding.py

세션 마커로 1회 안내와 활성 바인딩의 진행 힌트를 넣는다. 마커가 후속 읽기·도출 성공 전에 저장되므로 실패 또는 동일 세션 재바인딩 때 안내가 다시 나오지 않을 수 있다. cwd normcase 비교는 경로 정규화 전체와 동등하지 않다. chat pipeline의 일부 문서를 잘라 넣는 행위는 신뢰 승격이나 사용자의 8단계 SDD 충족 증명이 아니다. 프로젝트/실행 세대별 idempotency와 출처 표시가 필요하다.

## 14 session/precompact_guidance.py

고정 문구로 목표·다음 행동·사용자 정정을 보존하도록 요청한다. hook_protocol은 이 이벤트를 평문으로 출력하지만 실제 압축기에 반영됐는지는 미확인이다. 영속 체크포인트를 쓰거나 압축 전후 사실을 대조하지 않는다. 사람 경험 인수에는 안내문 외에 출처를 가진 지속 상태가 필요하다.

## 15 session/projection_report.py

원장을 읽어 projection을 쓰고 진행 상태 및 lease/이력 요약을 안내한다. 이벤트가 비면 새 상태를 돌려주지만 이전 projection 파일을 지우지 않아 stale 파일이 남을 수 있다. lease 안내는 현재 PID·실행 진척의 증명이 아니며 읽기 오류를 숨기는 부분은 미상으로 표시되지 않는다. 현재 run의 기대 단계 분모와 독립 판정 권한까지 증명하지 않는다. Zeus에서는 PG runtime SSOT에서 읽는 projection으로만 사용해야 한다.

## 16 stop/heartbeat.py

PostToolUse·Stop·SubagentStop 모두 하나의 운영 파일에 현재 시각과 hook 프로세스 PID를 쓴다. 이는 worker PID나 실제 작업 진척·성공 영수증이 아니다. 병렬 세션의 마지막 쓰기가 다른 세션의 정체를 가릴 수 있다. 원자 helper는 고정 tmp 이름이고 호출자 간 잠금이 없으면 경합이 남는다. Zeus heartbeat는 lease 세대와 worker identity에 묶여야 한다.

## 17 stop/prompt_rollup.py

주차별 digest 존재를 실행 마커로 삼아 만료 프롬프트 요약을 먼저 쓰고 삭제한다. 하지만 삭제는 선택한 row ID가 아니라 ts 술어를 다시 쓰므로 동시 삽입 시 요약 집합과 삭제 집합의 일치를 보장하지 않는다. digest를 일반 write_text로 두 번 쓰며, 첫 기록 뒤 실패하면 불완전 파일도 그 주 실행을 억제할 수 있다. 삭제 뒤 두 번째 기록이 손상되면 영수증도 잃을 수 있다.

hook_journal의 read→replace 만료도 append와 공통 잠금이 없어 동시 새 로그 손실 가능성이 있다. prompt_clusters 52–101의 탐욕적 쌍 비교는 입력 규모에 따라 Stop 시간을 늘린다. rollup smoke 79–190는 첫 쓰기 실패 시 삭제 금지와 단일 흐름의 건수 일치를 확인하려는 코드이며 동시성·두 번째 기록 장애 검증을 읽은 것은 아니다. Zeus에서는 선택 집합과 요약/만료 영수증을 트랜잭션으로 연결하고 후속 작업으로 실행해야 한다.

## 18 stop/reenforce.py

safe-mode, 무인 바인딩/cwd, 드라이버 스탬프를 검사한 뒤 tick subprocess를 최대 25초 기다린다. rc 오류·빈 출력·불명 outcome은 계속 강제를 내지 않는 경로다. done/halt/idle의 사용자 효과가 같아도 의미는 다르다. continue에서만 transcript byte cap을 확인하며 파일 상태를 읽지 못하면 그 제한을 적용하지 못한다. tick 전후 lease 세대 fence나 stop_hook_active 반복 억제는 여기 없다. tick 본체는 이번에 읽지 않았으므로 내부 반복·예산을 전체 검증했다고 하지 않는다.

## 19 stop/reflector_fork.py

원장 사건 수와 실패 family를 전역 watermark와 비교해 백그라운드 reflect를 시작한 뒤 watermark를 소비한다. child의 성공·산출 확인 전에 소비하므로 실패 후 재시도 누락, spawn와 watermark 사이 장애 시 중복 가능성이 있다. 전역 event_count/family는 새 원장·run 경계를 식별하지 않는다. safe-mode·드라이버 스탬프·lease 검사는 이 handler에 없으며 Windows만 detached creation flags를 사용한다.

직접 backend reflect.py 1–73은 LLM을 호출하지 않는 결정론 digest를 proposed에 쓴다. 따라서 현재 구현을 모델 토론이나 검증된 학습 승격으로 부르지 않는다. 출처 표시는 있으나 제안의 참·채택·해결을 증명하지 않는다. Zeus에서는 제안 job과 결과 영수증을 분리하고 PG 실행 세대로 소유권을 고정해야 한다.

## 20 stop/subagent_harvest.py

SubagentStop에서 드라이버 스탬프와 현재 바인딩을 읽고 transcript의 shard 문자열과 마지막 assistant 일부를 subagent_result로 적재한다. child/job ID·부모 run/lease 세대·cwd 연결 확인이 없어 오래된 자식의 종료가 새 원장에 귀속될 가능성이 남는다. 첫 읽을 수 있는 transcript를 고르며 모든 문자열을 검색하므로 marker 출처를 Task 프롬프트로 인증하지 않는다. 빈 요약도 결과를 기록할 수 있고 내부 append 예외는 조용히 반환한다.

직접 소비자 decomposition.py 161–188은 stage 없이 shard 이름만 계획에 맞으면 harvested로 센다. 같은 shard 이름의 다른 단계 결과와 구분되지 않으며 이 소비자도 검증이 아닌 복귀 신호라고 명시한다. stuck.py 31–34는 subagent_result를 진행 사건 목록에 넣는다. 따라서 이름 수거를 산출 검증·8단계 완료·모델 자격으로 올리면 안 된다. Zeus는 실행 요청 ID, 실제 결과 해시, 검증 담당자 및 단계 판정 영수증을 연결해야 한다.

## 공통 Zeus 대응과 남은 경계

이 범위의 파일 원장·전역 상태·환경 표시는 PostgreSQL runtime SSOT, 인증된 실행 귀속, 사람 경험 인수, 사용자의 8단계 SDD 판정과 동등하지 않다. 비교는 요구 계약 수준이며 Zeus src의 현재 구현을 이번 범위에서 다시 읽거나 등가 검증한 것은 아니다. 안전한 채택 후보는 이벤트별 출력 어댑터, 오류 분리, 제안 격리의 의도다. 경로 휴리스틱이나 과거 PASS 문구를 그대로 권한·완료 판정으로 가져오는 것은 보류한다.

Windows 경로·인코딩 보완 코드는 존재하지만 Linux/WSL 지원 완료를 뜻하지 않는다. POSIX launcher 의존성, 핀 형식, cwd, process group, host timeout, 파일 잠금/교체는 플랫폼별 검증이 남는다. 이번 실행은 메타데이터 기록과 해시 확인뿐이며 원본 프로브 실행은 0회다.
