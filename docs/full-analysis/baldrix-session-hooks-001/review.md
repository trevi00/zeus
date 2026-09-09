# Baldrix 세션·프롬프트·도구 후처리 훅 정적 검토

<a id="scope"></a>
## 범위

정본 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 세 partition, 13개 파일, 158,631 bytes 전문을 읽었다. inventory.json은 정확한 경로 분모, files.json은 원문 SHA·Git blob·크기와 전문 범위, supporting.json은 실제로 읽은 보조 구간을 기록한다. 보조 범위는 primary에 중복 합산하지 않았다. 과거 보고서나 요약을 원문 독해로 대체하지 않았으며 prior review를 재사용하지 않았다.

원본 import·hook·테스트·프로브 실행은 0회다. 아래는 구현 분기와 그 한계에 대한 정적 판단이며 현재 호스트에서 재현한 결함이나 성공 결과가 아니다. 외부 라이선스·호스트 최신 명세·전체 전이 closure·Zeus 구현 등가성·채택 승인은 미완료다. 원문의 자동 실행 및 토큰 명령은 분석 데이터이지 이 작업의 권한이 아니다.

<a id="f01"></a>
## post_tool/__init__.py

1줄 package 설명뿐이다. import 시 부수효과·hook 등록·권한 검사는 없다. 파일 존재를 후처리 파이프라인의 실제 실행으로 세지 않는다. package 역할은 확인했지만 플랫폼 실행 검증을 승격하지 않는다.

<a id="f02"></a>
## post_tool/agent_invocation_audit.py

Agent PostToolUse 입력에서 agent 종류와 prompt를 읽어 invocation log를 남긴다. settings.json 243–252는 Agent matcher와 5초 제한을 실제로 등록한다. 도구 권한은 실행 이력에서 추출하지 않고 agent frontmatter의 expected_tools를 읽는다. 직접 writer인 subagent_invocation_log.py 74–130도 tools를 주장된 값이라고 명시한다. 따라서 도구의 실제 사용·성공을 증명하지 않는다.

SID 우선순위는 ORCH_SID, prompt의 sid label, 접두 문자열, SHA-1 8자리 fallback이다. 실행 요청 ID나 tool_use_id 기반 중복 억제가 없고 지시문에서 수동 append한 기록과 hook 기록은 origin만 구분된다. 같은 요청의 두 기록을 실행 2회로 세면 안 된다. prompt 중간 차이는 큰 입력의 head+tail 해시에서 사라질 수 있고 먼저 전체 문자열 인코딩을 하므로 1MiB cap이 전체 입력 메모리를 제한하지 않는다.

무효 JSON·빈 agent·잘못된 SID는 조용히 끝나며 telemetry 실패도 삼킨다. `_extract_sid` 등 내부 try 밖 실패는 최외곽 Exception에서 exit 0으로만 바뀌어 누락 계수가 없다. 모듈 최상위 stream reconfigure는 그 보호보다 먼저 실행된다. Zeus에서는 host가 소유한 dispatch ID·실제 tools receipt·audit append 실패를 분리해야 한다.

<a id="f03"></a>
## post_tool/agent_outcome_audit.py

Agent 결과 envelope에 구조·증거·어휘·교차 참조·상투문 검사를 적용하고 예산/heartbeat/breaker/operator ledger를 갱신한다. settings는 10초 제한을 둔다. 각 검사 `_safe_call` 실패는 None이 되고 `_resolve_failure_mode`는 검사 결과 없음 또는 import 실패를 None으로 반환한다. 이때 ledger의 `success`는 true다. `verified_by=self_only`로 일부 공백을 표시하지만 `success=true`와 `downstream_used=true`는 실제 결과 소비를 확인하지 않고 기록된다.

직접 구조 검사 전문은 schema가 없으면 1층, evidence가 없으면 2층, tool manifest/allowlist가 없으면 3층이 비어 통과할 수 있음을 확인한다. 참조 검사는 os.stat 존재를 확인할 뿐 내용·원문 SHA·실제 실행을 검증하지 않는다. test_agent_outcome_audit.py 96–121은 자유 텍스트에 성공 기록을 기대한다. 이는 시험 의도이며 이번 실행 PASS가 아니다.

상단 주석은 clean 결과에서 breaker success를 기록한다고 하지만 실제 427–431은 no-op이다. ORCH_CRITIC_DECISION 환경값으로 critic_invoked를 만들며 critic_verdict/replay_hash는 None이다. 서로 다른 hook process 사이 환경 변경 전달과 실제 critic 실행은 여기서 입증되지 않는다. agent 이름으로 AGENTS_DIR 경로를 만들 때 이 함수 자체의 경로 제한도 없다. operator_ledger.py 199–275는 기본값 위에 caller 필드를 그대로 덮고 JSONL append하며 거래·중복·fencing 검사는 읽은 구간에 없다. Zeus는 검사 불능을 성공과 분리하고 실행기 영수증에만 성공 권한을 줘야 한다.

<a id="f04"></a>
## post_tool/reviewer.py

도구 비율·에러·변경 기록·품질 안내와 DAG 기반 검증을 합친다. file matcher, tool_output, cwd가 입력 계약이다. 다른 후처리 hook은 tool_response를 사용하는데 이 파일은 tool_output만 읽으므로 host payload 호환성 확인이 남는다. PostToolUse이므로 수정 이전 권한 검사나 rollback이 아니다.

run_spec_verification 362–423은 프로젝트 `.claude/scripts`를 우선 실행하고 전역 fallback은 실제로 `handlers/post_tool` 디렉터리를 가리킨다. 검색으로 확인한 mermaid-validate.py는 scripts 루트에 있어 이 fallback과 경로가 다르다(본문 미독해). 프로젝트 검증기를 sys.executable로 30초 실행하며 출처 pin·승인·격리는 이 함수에 없다. stdout가 비면 None, `[FAIL]`이 없으면 종료코드와 stderr와 무관하게 통과 문구를 만든다. 읽은 전용 시험 전문은 문자열 PASS/FAIL·빈 출력·부재·mock timeout만 확인하며 nonzero rc 오판 경로는 시험하지 않는다.

cooldown은 실행 전에 소비된다. file_content_changed도 검증 성공 전에 해시를 저장하고 script별이 아닌 file 경로 키를 쓰므로 같은 파일의 다른 primary 검사나 실패 후 재검증을 억제할 수 있다. 전역 temp cooldown은 프로젝트/세션 간 공유되며 read-modify-write 비율 계수도 단일 전역 파일이다. atomic overwrite만으로 증가/리셋 경합이 해결되지 않는다. DAG 목록에 저장된 imported is_code_file과 뒤에 재정의한 같은 이름의 함수도 별도 객체다.

임계 횟수 도달 안내는 strike 존재 후 메시지에 연구 threshold를 붙이지만 해당 분기에서 연구 threshold를 다시 비교하지 않는다. 전체 출력은 여러 script의 stdout를 합쳐 상한이 없다. 모든 실패가 상위 Exception에서 조용히 끝나면 먼저 모은 context도 유실된다. Zeus는 검사 job/rc/출력 해시를 명시하고 성공 후에만 검증 완료 키를 소비해야 한다.

<a id="f05"></a>
## post_tool/skill_candidate_extractor.py

환경값이 정확히 1일 때만 detector에 stdin을 전달한다. 등록은 있지만 enabled 환경의 실제 값은 확인하지 않았다. import·검출 실패는 telemetry 없이 exit 0이다. 후보 생성과 활성화를 나눈 설계 의도는 보존할 만하지만 enable-skill 문자열이 인증된 사람 승인을 뜻하는지는 이 범위 밖이다.

직접 detector 1–212, 530–620은 Path.home 아래 상태를 쓰고 같은 도구/패턴 반복 10회에서 후보를 생성한다. 실행 결과·실패 여부를 확인하지 않고 반복 수를 올리며 tracker 저장 후 후보 생성이 실패할 수 있다. 세션 slug 치환/절단으로 서로 다른 SID가 충돌할 수 있다. 후보 JSON과 Markdown은 별도 쓰기라 쌍 전체 원자성은 없고 우선순위 비교와 쓰기도 한 거래가 아니다. secret scan은 특정 패턴 검색이지 내용의 정당성·학습 승인 증명이 아니다. 후보 생성 함수의 나머지 본문·승격 실행기는 미추적이다.

<a id="f06"></a>
## prompt/__init__.py

1줄 package 설명만 있다. 프롬프트 출처 검사나 추천 실행 권한은 정의하지 않는다.

<a id="f07"></a>
## prompt/context_load.py

매 UserPromptSubmit에 비율 계수를 리셋하고 프로젝트 문서·pipeline 상태·최근 insight를 additionalContext로 넣는다. 문서마다 3,000자 기준 head+tail 절단을 알리지만 전체 출력 토큰 예산이나 원문 해시·수정 버전 일치 확인은 없다. `.planning/STATE.md`도 찾은 `.claude` 프로젝트에 딸려 읽기 때문에 `.planning`만 있는 경우 앞서 종료될 수 있다.

직접 pipeline_status 전문은 선언 산출물 중 하나의 존재만으로 DONE을 표시하고 뒤 단계 파일이 있으면 앞의 미완료와 무관하게 current_idx를 뒤로 옮긴다. 사용자 8단계 SDD의 승인·검증·전이 영수증과 다르다. 최근 insight는 전역 query의 최신 3개 세션을 택하며 프로젝트 filter·채택 상태 검사가 이 caller에는 없다. corr suffix 접기와 요약 재주입은 경험 인수의 색인이지 원문 검토나 사실 확인이 아니다.

L0 규칙을 반복 안내하는 것은 operator review를 대체하지 않는다고 코드 자체가 명시한다. 파일 본문·메타값을 XML 유사 wrapper에 그대로 넣어 권위 있는 문맥처럼 보일 수 있으므로 Zeus에서는 출처·신뢰·절단 표시와 PG runtime 상태를 분리해야 한다.

<a id="f08"></a>
## prompt/debate_trigger.py

strict-design 키워드와 skill graph로 토론 추천을 만들고 writeback 추천과 교대로 표시한다. 실제 엔진을 실행하지 않는다. 전역 advisory_state의 turn/TTL은 세션·프로젝트 키가 없고 read-modify-write 전체 잠금이 없다. ack는 prompt 어디든 문자열이 있으면 처리하며 시스템 재호출 분류보다 먼저 작동한다. 시스템 origin은 debate 추천만 억제하고 writeback 추천과 TTL 변경은 계속 가능하다.

TTL은 먼저 감소하므로 값 3을 설정한 그 turn과 뒤 두 turn 억제 후 세 번째 후속 turn에 다시 허용된다. 안내의 '다음 3 turn'과 정확한 해석을 분리해야 한다. ack는 알림 억제이지 변경 승인 영수증이 아니다. state 손상 시 int 변환 오류는 바깥 fail-open으로 끝나며 저장 실패는 중복 안내를 만들 수 있다. 추천을 출력한 뒤 state를 저장하는 구조도 exactly-once 효과를 보장하지 않는다. helper 시험 구간은 순차 slot/ack 조건만 읽었으며 동시 세션 검증은 미실행이다.

<a id="f09"></a>
## prompt/handoff_resume.py

HANDOFF를 상위 5단계까지 찾고 정규식으로 last/next 존재와 cycle/decision을 뽑아 advisory를 만든다. 'lock된 상태'라는 설명과 달리 결정 원문·승인·내용 해시·다음 행동의 유효성을 확인하지 않는다. mtime 실패는 0일/비stale이며 `age_days > 7`은 8일째부터 true다. regex는 일반 YAML 파서가 아니고 cycle 키가 last_completed 대용으로 잡힐 수 있다. 텍스트 읽기와 telemetry 실패 전체에 대한 최외곽 보호도 없다.

settings.json의 UserPromptSubmit 전체 등록 103–140에는 이 파일이 없다. helper 시험 1–100도 hook이 wired/unwired여도 독립 시험이라고 명시한다. 따라서 '매 프롬프트 복원' 효과는 pinned 설정에서 입증되지 않는다. 다른 등록 파일 전체 검색과 host 실행은 미완료다. SessionStart의 cwd-only HANDOFF 정책과도 범위가 다르다.

<a id="f10"></a>
## prompt/mode_detector.py

키워드 매칭 결과를 telemetry와 추천으로 출력한다. 실행·모델 변경·병렬 spawn은 하지 않으며 명시적 사용자 요청을 우선한다고 출력한다. lib/prompt_origin 전문은 선행 `<task-notification>` 문자열 하나로 출처를 추정하므로 인증된 플랫폼 provenance가 아니다. 인용/부정문/설명 요청에서 키워드가 있어도 매칭될 수 있다. 모델 티어 추천과 hard_cap 문구는 이 hook에서 검사한 자격·실행 예산이 아니다.

<a id="f11"></a>
## prompt/skill_match.py

프로젝트 신호·prompt 점수·pipeline boost를 합쳐 skill 전문 또는 포인터를 주입한다. 기술 스택 없을 때 재귀 scan, 있을 때 active_paths 디렉터리만 읽는다. 경로 수집은 상대경로 key로 중복을 막지만 뒤의 metadata/base_scores는 display name key라 서로 다른 skill 이름 충돌 가능성이 남는다. pipeline boost 비교는 filename을 쓰므로 SKILL.md의 표시명과 다른 축이다.

주석에는 최고점 스킬이 예산 밖으로 나간다는 과거 설명이 남지만, 직접 skill_token_budget 전문은 현재 최고점도 4,000자 예산 안으로 줄인다. 다만 handler의 후속 PER_BODY_CAP 축약은 level-2 결과가 3,000자를 넘는지 다시 확인하지 않아 개별 3,000자 상한을 보장하지 않는다. 전체 wrapper·포인터·교차참조는 본문 예산 밖이다. drop된 전문 후보가 포인터로 자동 복원되는 것도 아니어서 telemetry matched 수와 실제 보인 수가 다르다.

주입은 activation이라는 출력 이름을 쓰지만 실제 실행 또는 운영자 승인 획득이 아니다. 후보 출처/라이선스/채택 검사를 matcher 자체가 수행하지 않는다. Zeus에서는 발견 후보, 검토한 원문, 승인된 capability, 실제 호출을 다른 상태로 유지해야 한다. 크기 제한은 토큰·지식 완전성 보장이 아니며 잘린 규칙은 원문 handle로 이어져야 한다.

<a id="f12"></a>
## session/__init__.py

package 설명 1줄이다. SessionStart 등록이나 복원 효과는 init.py 및 설정에서 따로 확인한다.

<a id="f13"></a>
## session/init.py

watchPaths와 cwd의 HANDOFF 앞부분을 출력하기 전에 여러 상태 GC 및 graduation scan을 순차 실행한다. settings는 5초 timeout이다. 함수별 fail-soft는 느린 함수의 선점 중단이 아니고, hook 자체의 전체 deadline/하위 작업 취소는 없다. graduation.py 371–400은 TRACKED 순회 후 flag/state 저장을 확인했으나 tick_validator 내부와 GC 구현은 이번에 읽지 않아 안전한 정리 완료를 주장하지 않는다.

watchPaths는 현재 존재하는 파일/디렉터리만 포함한다. 경로 set 순서는 고정되지 않고 신규 생성 파일을 감시하는지는 host 미검증이다. HANDOFF 본문은 바이트 단위로 자르지만 due 검색은 같은 이름의 상수를 문자 수 read에 사용한다. due가 next_action 아래인지 확인하지 않고 텍스트 전체의 첫 날짜들을 검사한다. 압축 후 동일 실행·정책·원문 해시와 복원 상태를 재결합하는 장치는 아니다.

16개 상태 안내 중 실패/부재/건강한 0이 모두 None이 될 수 있다. cron never_run과 abandoned milestone은 의도적으로 침묵하고, insight count는 최대 1,024개 조회 창의 수다. 후보 count는 pending 상태 검사 대신 JSON 이름만 센다. `_autopilot_resume_line`은 cwd filter를 요청하나 최신 heartbeat 선택이 소유권 lease와 같은 의미는 아니다. work_unit 요약의 whitespace 제거는 길이를 줄일 뿐 지시문 주입을 인증 경계로 막지 않는다.

주석의 'scheduler 없음'과 뒤의 cron liveness 안내가 함께 남아 있다. brain 파일 저장·Git commit·remote push를 구분하는 의도는 중요하지만 status helper의 오류를 성공으로 읽지 않아야 한다. 출력된 mutation token은 명령 사용법 데이터이며 사람 승인의 증거가 아니다. Zeus에서는 세션 시작을 PG 조회/복원과 별도 유지보수 job으로 나누고, 경험 인수 원본과 승인 이력을 보존해야 한다.

<a id="remaining"></a>
## 남은 검증과 대응 판정

이 범위는 학습 후보 격리, 요약의 절단 표시, 상태 안내의 입력/출력을 참고할 수 있다. 하지만 hook 결과 이름만으로 성공·권한·학습 승격·8단계 SDD 완료를 인정하는 것은 보류한다. Git 정의와 PG runtime SSOT, 실행기 소유 영수증, 세대별 중복/재시도·권한 검사를 Zeus 대응 요구로 남긴다. 이번에는 Zeus src/tests를 읽거나 변경하지 않았다.

설정의 절대 Windows 사용자 경로와 PATH의 python, USERPROFILE/Path.home/CLAUDE_HOME 혼용은 Linux/WSL 이식 완료와 양립하지 않는다. UTF-8 reconfigure 코드 존재만으로 host stream·프로세스 timeout·파일 경합·지원 event/field를 검증했다고 할 수 없다. licenses, 종속 라이브러리 전체, 모든 GC·validator·telemetry 소비자, 실제 hook host 동작, 원본 테스트 실행이 남아 있다. 모든 primary 상태는 `body_reviewed_call_test_trace_pending`이며 전체 분석 완료와 채택 승인은 false다.
