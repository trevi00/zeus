## 읽은 범위 (정확히)

**전문 6개** (지정 범위): `handlers/stop/` 의 `__init__.py`(1줄), `autopilot_continue.py`(757줄), `calendar_gate_emitter.py`(319줄), `learner.py`(190줄), `response_guard.py`(180줄), `response_guard_core.py`(184줄). ※ 66844 bytes 는 내가 실측하지 않았음.

**추적으로 읽은 구간** (동일 pinned tree):
- `settings.json` — `"Stop"` 배열 전체(274–305) 및 인접 문맥
- 전문: `lib/autopilot_state.py`, `lib/completion_gate.py`, `lib/insight_index.py`, `lib/paths.py`, `lib/hook_io.py`
- 부분: `lib/work_unit_store.py`(심볼 맵 + 160–289), `lib/telemetry_log.py`(`log_telemetry`/`_rotate_if_needed` 주변), `lib/calendar_gate.py`(모듈 독스트링 + `read_ledger` 검증부)
- 테스트: `tests/test_autopilot_continue.py`(1–170, 210–629 = 사실상 전문), `tests/conftest.py`(격리 fixture 구간), `stop_hook_active` grep 결과
- **안 읽음**: `lib/reflexion_loop.py`, `lib/autopilot_compaction.py`, `lib/event_store.py`, `lib/ac_tree.py`, `lib/axis_scores_log.py`, `lib/atomic_json.py`, `lib/meta_rules.py`, `engine/orchestrator.py`, `commands/harness-autopilot.md`, `docs/subsystems/handlers-hooks.md`, atlas 노트 일체. 아래에서 이들에 의존하는 판단은 전부 **미검증**으로 표시.

---

## 1. `__init__.py`
1줄 독스트링뿐. 의미는 "hook 로직을 `scripts/` 에서 옮겨 담을 자리"라는 선언. 방어도 결함도 없음. 다만 이 패키지가 import 경로로 쓰이는 방식이 각 훅의 `sys.path.insert(0, _SCRIPTS)` 3중 중복(`autopilot_continue:73-75`, `calendar_gate_emitter:64-66`, `response_guard:44-46`, `learner:24-26`)으로 처리된다 — 패키지 `__init__` 이 경로 규약을 소유하지 않아 각 파일이 같은 관용구를 복제.

## 2. `response_guard_core.py`
**의미**: 순수 분석기. 5개 규칙 × 정규식으로 "조기 중단(block)" + 4개 warn 을 낸다. import-safe 를 명시적으로 지키고(모듈 레벨 env/IO 없음) `format_finding_lines` 로 두 호출자의 표현 계약을 공유 — 이건 진짜 방어다.

**실재 방어**: `strip_quoted_content` 로 코드펜스/인라인코드/큰따옴표/표를 제거해 "패턴을 논의하는 문장"의 오탐을 줄임. 규칙당 1매치로 끊어 폭주 방지.

**실패 반례**:
- `r"Phase\s*[2-9]"` 는 "작업 지연" warn 을 무조건 낸다. Zeus 의 **8단계 SDD** 를 그대로 보고하는 응답("Phase 3 완료, Phase 4 진행")은 매 턴 warn → block 이 된다. 이건 흡수 시 즉시 충돌하는 규칙이다.
- `(?:간단하게|일단|대충)\s*(?:처리|수정|해결|고쳤|했)` / `(?:아마|일단)\s*(?:될 거|괜찮|충분)` 은 한국어 상용구를 잡는다. 인용부호를 **한국어 홑따옴표/꺾쇠**로 감싸면 `strip_quoted_content` 는 `"..."` 만 지우므로 회피되지 않는다.
- `strip_quoted_content` 는 `"[^"\n]{3,}"` — **줄바꿈 포함 인용은 못 지운다**. 여러 줄 인용 안의 패턴은 그대로 탐지된다.

**근거**: 파일 33–123(규칙), 126–140(strip), 143–171.

## 3. `response_guard.py`
**의미**: CLI 껍데기 — 재귀/서브에이전트 가드 → autopilot 활성 시 양보 → 분석 → 90초 쿨다운 → `decision:"block"` emit.

**실재 방어**: `stop_hook_active`/`agent_id`/이벤트명 3중 스킵. autopilot 활성 시 `sys.exit(0)`(119–129)로 "Stop 당 block 은 하나"라는 D3'' 불변식 유지, 실패 시 fail-open.

**실패 반례**:
1. **warn 도 block 이다**(157–169). 코드가 스스로 "systemMessage 는 stopHooks 가 안 읽으니 전부 block 으로 보낸다"고 적는다(2–27). 즉 이 훅에는 *경고* 채널이 없고, 경고조차 턴을 끝내지 않는다.
2. **"조기 중단" 규칙이 사람에게 묻는 행위를 차단한다.** `should I continue` / `계속 할까요` / `이쯤에서 마무리` → severity=block. 사람 승인 요청이 곧 위반으로 처리된다. Zeus 의 "인간 핵심 시나리오/사람 승인"과 정면 충돌하는 방향성이다.
3. **쿨다운 파일이 전역 1개**: `TEMP|TMPDIR|/tmp` + `.claude_stop_response_cooldown`(65–68). 세션/프로젝트/사용자 스코프가 없다 → 프로젝트 A 의 경고가 90초 동안 프로젝트 B 의 경고를 삼킨다. 예외 시 `return True`(fail-open)이라 파일 소유자가 다르면 쿨다운이 사실상 무효화된다.
4. `sys.stdin.reconfigure`(37–38)가 **무가드**다. 같은 저장소가 이 결함 계열을 `autopilot_continue:57-71` 과 `hook_io:31-38` 에서는 `getattr` 로 막아놨는데 여기만 남았다 — reconfigure 없는 스트림이면 import 시점 AttributeError.

## 4. `autopilot_continue.py` (핵심)
**의미**: Stop 을 "계속하라"로 뒤집는 루프 엔진. response_guard 결과 + autopilot 지시문을 한 payload 로 합쳐 `decision:block` 으로 재주입.

**실재 방어 (진짜인 것)**:
- 캡이 실제로 존재: `iter<=30`, wallclock 1800s, tag_miss 2, json_error 2 (`autopilot_state.can_continue`). empty_body 에 전용 상한이 없다는 사실을 **독스트링이 스스로 UNIMPLEMENTED 로 적는다**(38–41) — 정직한 문서화.
- shared-sid 경로의 fail-closed: `require_evaluator=True` + `iteration_started_ts` 신선도 바닥 + 예외 시 `_shared_sid_confirmed` 면 `'iterate'` 로 닫힘(624–681). `latest_fresh_evaluator_verdict(since_ts=None) → None` 도 fail-closed. 테스트 4건이 이 축을 실제로 구동한다(472–521, 545–598).
- `escalate` 를 `advance_iter` 로 접지 않고 terminal 로 올림(708–731).
- cwd 스코프 세션 선택(`list_active_sids(cwd_filter=cwd)`)으로 다른 프로젝트 세션을 몰지 못하게 함.

**실패 반례 (구체)**:

**(a) 재시도 1회로 세션이 조용히 증발한다 — 가장 심각.**
`tag_miss` 분기(532–541)와 `json_error` 분기(550–559)가 `AutopilotState(...)` 를 새로 만들면서 **`cwd=` 를 넘기지 않는다** → 기본값 `None`. 그런데 `list_active_sids` 는 `st.cwd is None` 인 파일을 cwd-스코프 스캔에서 **제외**한다(`autopilot_state:336`). 결과: 태그 한 번 빠뜨린 다음 턴부터 `_select_active_sid` 가 `None` → 훅이 침묵 → 루프가 종료 통보 없이 사라지고, 상태 파일은 `status="in_progress"` 로 남는다(`cleanup_terminal_sessions` 는 done/failed 만 지움). `tag_miss_count` 는 절대 2 에 도달하지 못하므로 `tag_miss_exhausted` terminal 은 이 경로에서 도달 불가다. 지시문이 약속한 `tag_miss_count=1/2 → 다음엔 반드시` 의 "다음"이 오지 않는다.
*근거*: 532–541, 550–559 ↔ `autopilot_state:86,231,336`. *테스트 공백*: `test_main_increments_tag_miss_count_on_missing_tag`(282–316)는 `tag_miss_count==1` 과 `iter==0` 만 단언하고 `cwd` 는 보지 않는다.

**(b) 같은 생성자 누락이 reflexion 텔레메트리를 종료 시점에 0으로 지운다.**
`_terminal`(330–350)과 done 분기(688–697)도 `pending_fp`/`reflection_seen_count`/`reflection_req_count`/`cwd` 를 넘기지 않는다 → 기본값으로 리셋. `autopilot_state:87-94` 는 이 카운터의 존재 이유를 "seen<req 이면 배선돼 있어도 사실상 죽은 경로임을 드러내는 지표"라고 적는데, **그 지표가 판독 시점(종료)에 파괴된다.** 자가개선 효과 측정이 구조적으로 불가능하다.

**(c) 콜드스타트에서 완료가 자기신고 3개 불리언으로 성립한다.**
`count_orchestrator_iterations` 가 `None`(orchestrator events.jsonl 부재)이면 `verdict is None` → `inline_pass = validators_passed and tests_passed and blocking_q==0`(683–687) → `status="done"`. 이 셋은 전부 **모델이 자기 메시지에 쓴 JSON**이다. 코드 자신이 B3 주석에서 "agent-controlled body 는 completion source 가 아니다"라고 선언하지만(646–651) 그 선언은 shared-sid 경로에만 적용된다. 그리고 `test_main_marks_done_on_goal_reached`(319–360)가 바로 이 자기신고 종료를 **수용 기준으로 고정**하고 있다. Zeus 의 no-mocked-acceptance 와 정면 충돌.

**(d) "사람 결정 필요"가 사람에게 가지 않는다.**
escalate/terminal 메시지는 `_emit_block`(326–327) 즉 `decision:"block"` 으로 나간다. 이 채널의 문서화된 효과는 `blockingError → 모델이 재시도`다(`response_guard:20-26`). 진짜 중단 채널인 `{"continue": false, "stopReason": ...}` 는 `hook_io.stop_decision` 에 구현돼 있지만 **읽은 6개 파일 어디서도 emit 되지 않는다**(독스트링 문장으로만 존재). 즉 이 Stop 핸들러 집합은 *턴을 끝내는 능력*을 한 번도 행사하지 않는다. 복구 안내도 "state file 수동 점검 후 status='in_progress'로 복구"라는 **수기 JSON 편집**이다.

**(e) 지시문의 iter 번호가 경로마다 어긋난다.**
`_build_combined_reason` 은 `next_iter = state.iter + 1`(213). 재시도 경로는 `state=`(전진 전)를 넘기고(543,561,568), 계속 경로는 `state=next_state`(전진 후)를 넘긴다(735,744). 같은 라벨이 경로에 따라 실제 상태의 +0/+1 을 가리킨다 → 원장·로그 상 iteration 신원이 불안정.

**(f) `_terminal` breadcrumb 이 재개 화면에 안 잡힌다.**
`record_work_unit(state.sid, "", ...)` — cwd 를 빈 문자열로 쓴다(347, 703). `_cwd_match` 는 `if not stored: return False`(`work_unit_store:274`) → cwd 필터가 걸린 `latest_work_unit` 은 이 종료 기록을 절대 못 고른다. 종료 사실이 재개 표면에서 사라진다.

**(g) 비-autopilot 턴에도 매번 비용을 낸다.**
`sid` 가드 **앞에**(444–494) `.planning/STATE.md` 최대 4단계 상향 탐색 + sha1 + work_unit read/write + telemetry 1건이 무조건 실행된다. 의도는 주석에 명시돼 있고(비-autopilot 이 흔한 경우라 앞에 뒀다) 합리적이지만, 모든 세션의 모든 Stop 에 10초 타임아웃 예산을 태우는 비용이다.

**(h) autopilot 중 품질 경고에는 쿨다운이 없다.**
`analyze_response` 결과가 매 턴 지시문 앞에 붙는다(186–189). response_guard 의 90초 쿨다운은 이 경로를 타지 않는다 → 위 3-(a)류 오탐(예: "Phase 4") 이 30 iteration 내내 반복 주입된다. 토큰 효율 관점의 실제 손실 지점.

## 5. `learner.py`
**의미**: SENSOR 전용. history 꼬리 300건에서 오류 문구를 정규화·빈도 집계 → 텔레메트리 + L1 insight-index 에 요약 기록. skill 자동생성은 명시적으로 거부(사용자 개시 `/harness-skill learn` 로 미룸) — **의도적으로 옳은 방향의 자제**다.

**실재 방어**: stdout 미발화(Stop 스키마에 additionalContext 없음을 인지). `terminal_convergence_predicate` 로 매 턴 기록을 막고, 다이제스트는 900초 워터마크로 스로틀. insight_index 쓰기 2곳 모두 `except: pass` fail-soft.

**실패 반례**:
1. **원문 신원이 소실된다.** `_NORMALIZE_RE = r"\d+|[/\\][\w./\\\-]+"` → 숫자와 경로를 전부 `<X>` 로 치환(45, 88). 어떤 파일·어떤 라인·어떤 값이 실패했는지가 지워진 뒤 그 문자열이 원장에 남는다. 게다가 두 append 모두 `body_ref=None`(139, 179) — insight_index 스키마가 "richer body 로의 포인터"로 정의한 필드(`insight_index:24`)를 쓰지 않는다. `correlation_id` 는 `session_id` / `session_id+"-wu"` 뿐. **원장에서 원문으로 되돌아갈 경로가 없다.**
2. **절단 3중**: `top_pattern[:120]`, 다이제스트 `p[:50]`, `work[:170]`, 최종 `[:280]`.
3. **수명 비대칭**: `learner-candidates` 텔레메트리는 1MiB 에서 `.jsonl.1` 1세대만 남기고 이전 것을 `unlink`(`telemetry_log:71-75`) → 사라진다. 반면 `memory/insight-index.jsonl` 은 **무한 append, TTL 없음, retract 도 append-only**. 즉 상세는 휘발하고 요약은 영구히 쌓인다. L2 승격은 DEFERRED 로 명시(`insight_index:37`).
4. **매 Stop 마다 history 전체를 읽는다.** `_read_tail` 이 `f.readlines()` 로 파일을 통째 로드한 뒤 `lines[-n:]`(52–57). 꼬리 300줄만 필요한데 O(파일크기)다. 스로틀은 *다이제스트 발화*에만 걸리고 이 스캔에는 안 걸린다 → 10초 타임아웃 위험이 파일 성장에 비례.
5. **훅 규율 위반 1곳**: `from lib import insight_index` 가 모듈 최상단(32)이다. 다른 5개 파일이 지키는 "lazy import + try" 규약(예: `autopilot_continue:241,635,701`)에서 벗어나 있어, 이 import 가 깨지면 훅 프로세스가 import 시점에 죽는다.
6. **작성자 신원이 문자열이다.** `source_module: "handlers.stop.learner"` 를 **호출자가 넣어 보낸다**. `insight_index.append` 의 화이트리스트는 그 문자열을 비교할 뿐이고, 파일 자신이 "spoof-resistant 경계가 아니며 실제 경계는 정적 AST 화이트리스트"라고 적는다(`insight_index:72-84`). 원장 항목에 **어느 에이전트가 배웠는지**는 아예 필드가 없다.

## 6. `calendar_gate_emitter.py`
**의미**: residual-norm 원장(마감일 + known_defects)이 지나면 Stop 을 막는 잔여-부채 게이트. 순수 어댑터(`build_block_payload`)와 `today` 주입 분리는 잘 된 설계.

**실재 방어**: `today` 를 주입받아 시계 의존 제거, `MAX_SURFACED=5` + overflow 요약으로 payload 폭주 방지, `_resolve_state_root` 가 `state_dir()` 위임(직접 계산하면 `CLAUDE_STATE_DIR` 격리를 무시했다는 실측 사고를 독스트링이 기록 — 144–149), 임베디드 self-check 10건.

**실패 반례**:
1. **이 pinned `settings.json` 의 Stop 배열은 정확히 3개**(response_guard / learner / autopilot_continue)이고 이 emitter 는 없다(274–305). 파일 자신도 "auto-register 하지 않음, operator-gated"라고 선언(9–13). 즉 **이 설정 스냅샷에서 이 게이트는 발화 지점이 없다.** (과거 실행 이력에 대해서는 아무 주장도 하지 않음.)
2. `main()` 은 실패를 stderr 로 삼키고 항상 0 반환(182–191) — 게이트 자체 버그가 조용한 무게이트로 붕괴한다. 방향은 fail-open 으로 명시적 선택이지만, 부채 게이트로서는 "막아야 할 때 안 막는" 쪽으로 실패한다.
3. `known_defects` 는 원장 JSON 의 자기신고 정수이고, 해소책으로 **"deadline 연장(explicit deferral)"** 을 안내문에 명시(107–110) → 게이트를 통과하는 정당한 방법이 "미루기"다. 원장 작성자는 `lib/meta_rules.py`·`lib/evaluator_dispatcher.py` 쪽으로 보이나 **읽지 않았음 → 미검증**.
4. self-check Case 8 이 결과 경로를 3가지 문자열 중 하나로 받아들인다(292–295) — 경로 규약이 플랫폼별로 갈린다는 걸 테스트가 스스로 인정.

---

## 횡단 토픽

**Stop 요청 / 실제 중단**: 3개 등록 훅이 쓰는 채널은 전부 `decision:"block"` 하나다. warn 도, terminal 도, escalate 도, "사람이 결정해야 함"도 같은 채널로 나가 **모델을 다시 돌린다**. 사용자가 턴을 끝내려는 순간을 훅이 되돌리는데, 되돌림을 취소할 사용자 채널은 이 6개 파일 안에 없다. `continue:false` 는 미사용.

**완료 자기신고 vs 검사 vs 사람 승인**: 3층이다. ①shared-sid + 신선한 evaluator verdict = 실제 검사(fail-closed, 잘 됨) ②콜드스타트 = 자기신고 불리언 3개로 done ③사람 승인 = 없음(텍스트만). ②가 ①의 존재로 정당화되지 않는다 — 어떤 세션이 ②로 떨어지는지는 `state/orchestrator/<sid>/events.jsonl` 존재 여부라는 암묵 조건이다.

**반복·중복·재개·실패 방향**: 캡은 4중으로 실재하지만 empty_body 는 wallclock 만이 상한(자백됨), tag_miss/json_error 는 위 4-(a) 때문에 상한 도달 전에 세션이 사라진다. 재개는 수기 JSON 편집. 실패 방향은 대체로 fail-open(계산 실패 → 무게이트)이고, 유일하게 fail-closed 인 곳이 shared-sid 판정이다.

**학습 원장 수명·원문 신원**: 상세=1MiB 2세대 회전 후 소멸 / 요약=무한 영속, TTL·승격 미구현. 원문 포인터(`body_ref`) 미사용, 숫자·경로 정규화로 식별자 제거, 에이전트 신원 필드 부재, 작성자 검증은 문자열 자기신고.

**알림·토큰 효율**: 쿨다운은 전역 파일 1개 90초이고 autopilot 경로는 우회한다. 지시문은 매 턴 재발화(~800자 한국어) + 경고 최대 5줄. 비-autopilot Stop 에도 STATE.md 탐색·sha1·work_unit IO·telemetry 가 무조건 붙는다. learner 는 매 Stop 마다 history 전체를 읽는다.

**Windows/Linux/WSL**:
- `settings.json` 이 `python C:/Users/rudtn/.claude/scripts/...` 로 **절대 Windows 경로 + `python`** 을 박아둠(280/290/300). 다른 사용자·WSL·Linux 에서는 이 3개 훅의 커맨드가 성립하지 않는다.
- `response_guard.py:37-38` 무가드 reconfigure (다른 3파일은 가드됨).
- 쿨다운 파일: WSL/Linux 에서는 `TEMP`/`TMPDIR` 부재 시 공용 `/tmp` 로 떨어짐 → 사용자 간 충돌, 소유권 오류 시 fail-open.
- `work_unit_store._norm_cwd` 가 `os.name=="nt"` 일 때만 casefold(263). `C:\proj` 로 기록된 세션을 WSL(`/mnt/c/proj`)에서 읽으면 `_cwd_match` 실패 → **같은 디렉터리가 두 프로젝트로 갈린다**. autopilot cwd 바인딩이 WSL 경계를 넘지 못한다.
- `paths.claude_home()` 이 `USERPROFILE` 분기를 갖는데 POSIX 인터프리터에서 갈린다는 잔여 위험을 파일 자신이 기록(88–93).
- 텔레메트리 회전이 Windows PermissionError 를 명시적으로 처리.

## Zeus 요구 대응 (흡수 관점, 결론 아님)
- **PG runtime SSOT / Git 정의**: 여기 상태는 전부 홈 디렉터리 파일이다 — `state/autopilot/*.json`, `state/work_unit/*.json`, `memory/insight-index.jsonl`, `telemetry/*.jsonl`. 원장 항목에 repo·commit·파일 좌표가 없고 프로젝트 바인딩은 `cwd` 문자열 하나이며 그마저 위 4-(a)에서 유실된다. PG 이관 시 (1) entry 스키마에 repo/commit/agent identity 추가 (2) `body_ref` 를 실제 원문 포인터로 채우기 (3) work_unit 의 "세션당 1행 덮어쓰기"를 이력 테이블로 바꾸기가 선행 조건.
- **8단계 SDD**: `response_guard_core` 의 `Phase\s*[2-9]` 규칙이 SDD 단계 보고를 페널티로 처리한다 — 흡수 전 규칙 수정 필요.
- **인간 핵심 시나리오 / 엄격 재현 / no mocked acceptance**: 콜드스타트 자기신고 완료 경로(4-(c))와 그것을 고정한 테스트가 정면 위반. shared-sid 경로의 fail-closed 설계는 그대로 가져갈 가치가 있다.
- **사람 승인**: `continue:false` 채널이 미사용이고 "조기 중단" 규칙이 승인 요청 자체를 차단한다. 흡수하려면 escalate 를 사람 채널로 라우팅하는 배선이 신규 작업으로 필요.
- **Astra→Sol→Terra 자격 이관**: 원장에 에이전트 신원 필드가 없고 작성자 검증이 문자열 자기신고 + 정적 AST 경계다. 자격 이관의 근거가 될 "누가 무엇을 배웠나"를 현 스키마로는 표현할 수 없다.

## 미검증 (읽지 않은 것에 의존)
`reflexion_loop`(lessons/strike/wonder store 실제 동작 및 "seen<req" 지표 소비처), `autopilot_compaction`, `event_store`/`ac_tree` 축약 정합성, `axis_scores_log` 의 ts 서버 스탬프 주장, `engine.orchestrator` 의 `iteration_started` 발화 지점, residual_norm 원장 작성자, `/harness-autopilot --resume` 의 실제 구현, `atomic_json` 의 원자성. 또한 **런타임이 turn 마다 `stop_hook_active` 를 리셋하는지** — 테스트 9곳 모두 `False` 하드코딩이고 다중 턴 e2e 가 없다. 리셋되지 않는다면 autopilot 루프는 1회로 끝나고 30/1800 캡은 도달 불가가 된다(정적으로 판정 불가).

전체 분석·흡수 승인은 미완료로 유지. root 독립 분석 후 토론 대기.