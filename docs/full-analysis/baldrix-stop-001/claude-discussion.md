## 대조 완료 — root 산출물 확인

읽은 것: `codex-initial.md`(42줄 전문), `component_observations.py`(89줄 전문), `components.stdout.txt`(215줄 전문), `components.receipt.json`, `calendar-lib-self-check.stdout/receipt`(24 PASS), `calendar-emitter-self-check.stdout/receipt`(12 PASS). 추가로 이번 토론을 위해 pinned tree 에서 `lib/event_store.py`(21–112 구간)를 신규 추적했다. **내 초기 raw 보고(claude-initial.md)는 수정하지 않고 보존**하며, 아래는 그에 대한 델타다.

실행 조건은 receipt 대로 이해했다: network none / read-only bind / nonroot 65534 / tmpfs / 고정 이미지 sha256:7415fb…, source 1648파일 전후 동일, `work_unit_store.mark("save")` 로 autosave 를 이번 관측 밖에 둠. 즉 **설치된 hook runtime·evaluator·model·worker·실기기·Windows/WSL 은 인수가 아니다**. 4개 자식은 실제 Stop CLI 다.

---

## 1. 내가 틀린 것 (정정)

### 1-1. learner `terminal_convergence_predicate` — 정정 수용
초기 보고에서 "매 턴 기록을 막는 필터"라고 독스트링 프레이밍을 그대로 옮겼다. 코드는 `learner.py:105` 에서 **`return bool(candidates)`** 뿐이고 `payload` 인자는 105줄까지 한 번도 참조되지 않는다. root 실측이 결정적이다: 이벤트 **1건**의 `"error error error"` → `candidates=[["error error error",3]]`, `convergence_with_incomplete_payload: **true**` (payload `goal_reached:false`). 
원인까지 짚으면, `find_recurring_errors`(84–89)는 **이벤트 수가 아니라 `_ERROR_RE.finditer` 매치 수**를 센다. 한 이벤트 안 3회 등장이면 snippet 창(start-40/end+60)이 겹쳐 동일 키가 되어 `MIN_REPEATS=3` 을 단일 이벤트로 충족한다. "최근 창에서 반복되는 오류"라는 문서 의미와 다르다. **반복 오류 ≠ 수렴**이고, 완료·검증·수정·재발여부 중 무엇도 조건에 없다. 초기 보고의 칭찬 문장을 철회한다.

### 1-2. "3개 등록 훅 모두 block 채널" — 틀림
`learner.py` 는 stdout 을 내지 않는다(독스트링 13줄이 명시, 본문에 `print`/`write_hook_output` 없음). 정확한 문장: **등록된 3개 중 2개(response_guard, autopilot_continue)가 `decision:block` 을 쓰고, learner 는 발화 채널이 없다.** 내 횡단 요약은 과일반화였다.

### 1-3. "다른 5개가 lazy import 규약을 지킨다" — 틀림
실제 top-level(무가드) lib import: `learner.py:28-32`, `autopilot_continue.py:77-88`, `calendar_gate_emitter.py:68-69`, `response_guard.py:47-53`. **네 실행 파일 전부** 무가드 top-level import 를 갖는다. 지켜지는 "규약"은 없다. 
다만 좁혀서 살아남는 사실이 있고, root 실측이 그것을 더 강하게 만든다: **learner 만 `main()` 에 바깥 try/except 가 없다**(response_guard:99-174, autopilot_continue:427-751 은 전체를 감싼다). 그리고 `_read_tail:63` 이 dict 검사 없이 아무 JSON 값이나 적재 → `_extract_text:70` 의 `event.get`. root 관측 `learner_wrong_shape: AttributeError "'list' object has no attribute 'get'"` 가 이 경로를 실증했다. **history.jsonl 에 `[]` 한 줄이 섞이면 해당 Stop 훅이 매 턴 예외로 죽는다.** 이건 내가 놓친, root 가 실측으로 잡은 결함이다.

### 1-4. shared-sid 를 "실제 검사"로 단정한 것 — 정정 수용
과장이었다. 코드로 증명되는 것은 좁다: **"별도 파일에 `verdict` 값이 {approved,iterate,escalate} 중 하나로 존재하고 그 `ts` 가 iteration floor 이상이어야 한다"**(`completion_gate.py:201-249`). 증명되지 않은 것: 그 레코드의 **작성자·러너·artifact/actor 신원**. 나는 `lib/axis_scores_log.py` 를 읽지 않았으므로 "server-stamped ts" 는 내가 독스트링(220줄)을 옮긴 것이지 검증한 게 아니다. 오히려 반대 방향 증거가 내가 읽은 범위 안에 있다 — `tests/test_autopilot_continue.py:440-443` 이 `log_axis_event(sid, {..., "ts": floor + ts_offset})` 로 **ts 를 호출자가 직접 넣는다**. 신선도 바닥은 "호출자가 제출한 ts" 에 걸린 필터일 수 있다. 
또한 **내가 읽은 테스트는 이번 체크포인트에서 실행되지 않았다**(root 가 돌린 것은 calendar self-check 2건 + component program뿐). 초기 보고에서 테스트를 "이 축을 실제로 구동한다"고 쓴 것은 잘못이다 → "그 축을 **단언으로 기술**한다"로 정정. 
같은 이유로 `test_main_marks_done_on_goal_reached` 를 "수용 기준으로 고정"이라 부른 것도 철회한다. 그것은 **코드 경로를 문서화한 미실행 unit** 이고, 자기보고 종료 경로가 존재한다는 사실과 "프로젝트가 그것을 acceptance 로 삼는다"는 주장은 별개다. 후자는 미확인.

### 1-5. "Phase 2 는 매 턴 무조건 block" — 정정 수용
"무조건"은 틀렸다. 실제 조건 사슬: `len(message)>=30` → strip 후 `>=30` (`response_guard_core.py:149-154`) → 코드펜스/인라인코드/큰따옴표/표 밖에 있어야 매치 → findings 비어있지 않음 → (response_guard 경로) 90초 쿨다운 통과 → 그리고 skip 가드 3종(`stop_hook_active`/`agent_id`/이벤트명) 통과. autopilot 경로에는 추가 분기가 하나 더 있다: **done 분기(687–707)는 block 을 emit하지 않고 종료**하므로 완료 턴의 findings 는 전달되지 않고 버려진다. 
root 실측이 정확한 크기를 준다: 합법 문장 `"Phase 2 is approved by the user and the implementation has already begun."` → **`[["작업 지연", …, "warn"]], has_blocking=false`**. 즉 **오탐 1건, warn 등급**이다(그리고 response_guard 는 warn 도 `decision:block` 으로 보낸다는 별개 사실은 유효). 정정 문장: *"특정 패턴(`Phase\s*[2-9]` 등)이 합법 SDD 단계 보고에서 warn 오탐을 낸다. 다만 등급은 warn 이고 길이·인용·쿨다운·분기 조건이 붙는다."*

### 1-6. "사람 승인 요청이 곧 위반" — 과잉 일반화, 정정
block 등급 패턴은 4개뿐이고 **"계속/중단 허가"라는 특정 어형**만 잡는다(`response_guard_core.py:36-51`): `(should|shall|want me to) (I )?(continue|keep going|proceed)`, `계속 (할까요|진행할까요|해도 될까요)`, `(good|natural|logical) (stopping|breaking|pausing) point`, `(이쯤|여기서|이 정도)…(멈추|중단|그만|마무리)`. 
따라서 "A안과 B안 중 어느 쪽으로 갈까요?", "이 설계 승인해 주시겠습니까?", "권한이 필요합니다" 같은 **정당한 승인 경로는 매치되지 않는다.** 정정 문장: *"진행 허가를 묻는 흔한 어형이 block 등급으로 처벌되고, 그 외 승인 요청 경로는 열려 있다."*

### 1-7. iter 오프바이원 — **철회**
내 주장이 틀렸다. 재계산: 재시도 경로는 persisted `iter=N` 을 쓰고 `state`(=N)를 넘겨 `N+1` 을 표기(213). 전진 경로는 persisted `iter=N+1` 을 쓰고 `next_state`(=N+1)를 넘겨 `N+2` 를 표기. **두 경로 모두 emitted = persisted + 1** 로 일관된다. `iter` 를 "완료 횟수", 태그 라벨을 "다음에 수행할 회차"로 읽으면 정합적이다. root 실측도 이와 일치한다(persisted `iter:0` ↔ emitted `iter='1'`). 
남는 것은 결함이 아니라 관찰 하나뿐: 재시도 턴은 같은 회차 번호를 반복 표기한다(같은 iteration 재시도라는 의미로 오히려 타당). `autopilot_state.py:19` 의 주석 `# 0..max_iterations` 만으로는 정의가 명시되지 않으므로 **정의는 여전히 문서화 부재**로만 남긴다. 실측 데이터포인트는 재시도 경로 1건뿐, 전진 경로 실측은 없음.

### 1-8. terminal / 중단 채널 — 범위 축소
`decision:block → blockingError → 모델 재시도` 는 **이 저장소 자신의 주석 규약**이다(`response_guard.py:20-26,149-155`, `hook_io.py:12,86-107`). 현재 클라이언트에서의 실제 host 효과는 이번 체크포인트에서 **미검증**이다. root 표현대로, block emit 은 "워커가 죽었다/사람이 결정했다/추가 툴이 안 돌았다"의 증거가 아니다. 
그리고 "stop/kill 채널 부재" 주장은 **이 6개 파일 안으로 한정**한다(6개 어디서도 `continue:false` 를 emit하지 않는 것은 전문 통독으로 확인). 하네스 전체로 확대하지 않는다.

### 1-9. 범위 축소 3건 (point 5 수용)
- **"재시도 이후 영구 불가"** → **"cwd 스코프 선택 경로로는 재개 불가"**. `autopilot_state.py:325,336` 은 `cwd_filter is not None` 일 때만 필터를 적용하므로 **무스코프 `list_active_sids()` 는 여전히 이 세션을 반환한다.** SessionStart 등 다른 호출자가 어떻게 부르는지 나는 읽지 않았다 → 미확인. 외부 writer/수기 state 복구도 배제 못 한다.
- **"자가개선 측정 구조적 불가"** → **"종료·재시도 스냅샷에서 `pending_fp`/`reflection_seen_count`/`reflection_req_count`/`cwd` 4필드 유실"**. `lib/reflexion_loop.py` 미독이므로 그쪽 자체 저장소·다른 로그가 같은 지표를 보유할 가능성을 배제하지 못한다.
- **"원문 추적 불가"** → **"원장 항목에 정확한 원문 ID 포인터가 없다"**(`body_ref=None`, `learner.py:139,179`; 정규화 `_NORMALIZE_RE:45`). history.jsonl 이 남아 있으면 사람이 대조하는 경로까지 부정하는 증명은 아니다.
- **insight TTL**: "이 모듈에 미구현"으로 한정. `cron/check_l2_promotion.py` 를 포함한 cron 전체는 미검토.

### 1-10. terminal 복구 지시가 실제로 안 되는 건 맞다 (보강)
사용자가 지적한 대로, 종료 메시지의 `status='in_progress'로 복구`(518-520, 727-729)는 `can_continue()`(`autopilot_state.py:142-150`)의 나머지 4조건 — `iter_cap` / `wallclock`(`started_ts` 불변) / `tag_miss_exhausted` / `json_error_exhausted` — 을 **하나도 되돌리지 못한다.** 즉 메시지에 인쇄되는 바로 그 종료 사유들에 대해 안내된 복구 절차가 무효다. 초기 보고에서 "수기 편집"이라고만 쓴 것을 이 형태로 강화한다.

---

## 2. 실측으로 확인된 합의 (내 초기 보고가 버틴 것)

**재시도 1회에 세션이 조용히 증발** — 정적 추론이 4개 실제 CLI 자식으로 재현됐다.
- `selected_before: ["orch-review-tag_miss"]` → 1차 호출 rc0, block emit(`tag_miss_count=1/2` 문구) → `state_after_first.cwd: **null**`, `pending_fp: null`, `reflection_seen_count: 3→**0**`, `reflection_req_count: 5→**0**`
- `selected_after_first: **[]**` → 2차 호출 rc0, **stdout·stderr 모두 빈 문자열**(sha256 e3b0c442… = 빈 바이트), `tag_miss_count` 1 유지, `status` `in_progress` 유지
- json_error 경로 동일(`json_error_count 1`, cwd null, selected []).
원인 줄: `autopilot_continue.py:532-541`(tag_miss), `550-559`(json_error) 가 `cwd=`/reflexion 4필드를 생성자에 넘기지 않음 ↔ `autopilot_state.py:86,92-94`(기본 None/0), `:336`(cwd None 행 제외). `advance_iter`(256-276)는 정상 보존하므로 **분기 국소 결함**이라는 root 의 규정에 동의한다.
따라서 `MAX_TAG_MISS=2` / `MAX_JSON_ERROR=2` terminal 은 이 경로에서 **도달 보장이 없다** — 실측 2회 호출로 도달하지 않았다. (초기 보고의 "도달 불가" 단정은 위 1-9에 따라 "cwd 스코프 경로에서 도달하지 않음"으로 조정.)

부수 합의: 이 순간 `response_guard.py:124-129` 의 양보 조건도 함께 뒤집힌다. `list_active_sids` 가 `[]` 를 반환하므로 **피드백 소유권이 런 도중 조용히 response_guard 로 되돌아간다.** root 의 "성공 처리 여부가 아니라 존재 여부로 양보한다"는 지적과 내 발견이 여기서 합쳐진다.

calendar self-check 24+12 PASS 는 그대로 인정한다. 단 그것이 검증하는 것은 스캐너/어댑터의 선언된 계약이며, 아래 2-(i)의 누락은 그 24+12 안에 **없다**.

---

## 3. root point-6 검증 (코드로 반증 시도 → 결과)

| root 주장 | 판정 | 근거 |
|---|---|---|
| 모든 writer bool 무시 | **확인** | `write_state` 는 bool 반환(`autopilot_state.py:235-240`)인데 `autopilot_continue.py:342,542,560,698,734` 전부 반환값 미검사. block emit 은 상태 전이 실패와 무관하게 나간다 |
| goal_reached False면 blocking_q 도 reflexion/advance | **확인** | `:575` 가 `is True` 엄격 비교. 아니면 `:741-747` 로 직행 → `blocking_question_count>0` 이어도 escalate 게이트에 도달하지 않음 |
| parser mode 미소비 | **확인** | main 전체(426-753)에서 `parsed["mode"]` 참조 0. `kind`/`body` 만 사용 |
| quoted tag | **확인** | `parse_autopilot_tag` 는 원문에 직접 정규식(`:131,139-142`). `strip_quoted_content` 미적용 → 코드펜스 안의 예시 태그가 실지시로 파싱될 수 있음 |
| mixed identity | **확인, 실측 포함** | `mixed_mode` → `{"kind":"ok","mode":"advisory","body":{"goal_reached":true}}`. 첫 태그(advisory)의 mode 와 두 번째(execute) 블록의 body 가 결합. mode 미소비와 합쳐지면 **advisory 선언이 execute 권위 body 를 실어 완료 게이트에 진입**한다 |
| emitted sid/iter 를 parser 가 거부 | **확인, 실측** | `emitted_attributes: null`. `_AUTOPILOT_TAG_RE`(93-96)가 mode 값 뒤 `>` 만 허용 → 훅 자신의 출력 형식이 자기 파서를 통과하지 못함. 다만 DIRECTIVE 가 요구하는 형식(속성 없는 태그/`<iteration-result>`)은 통과하므로 "지시대로면 정상, 지시문 태그를 흉내내면 tag_miss" |
| AC reduction 에 iteration/spec/expected leaf set 없음 | **확인** | `_reduce_ac_leaf_events`(353-423)가 `iter_by_type` → `replay()` 로 **세션 전체 로그**를 훑고 leaf_id 별 tail 만 취함. 기대 leaf 집합 없음 → 누락 leaf 는 조용히 부재. `gate_pass` 비고 advisory 만 있으면 `approved` 아님/`None`, gate 만 있고 advisory 없으면 `approved`(419). `isinstance(score,int)` 는 **bool 통과**(True→1) |
| body ac_verdict 가 None 일 때만 reduce | **확인** | `:610-622`. `ac_verdict_raw` 가 `"approved"` 또는 임의 문자열이면 두 분기 모두 미실행 → **모델이 넣은 스칼라 하나로 이벤트 축약 검증이 통째로 건너뛰어진다** |
| EventStore 가 읽기 경로에서 상태 생성 | **확인(신규 추적)** | `event_store.py:37` `self.dir = ensure_dir((base_dir or DEBATES_DIR)/session_id)` — 생성자가 mkdir. `:380` 의 `store.path.exists()` 가드는 **디렉터리가 이미 만들어진 뒤**에 돈다 |
| warm cooldown 이 다른 프로젝트 block 도 억제 | **확인** | `response_guard.py:136` 의 쿨다운 체크가 `146` 의 `has_blocking` 분기 **앞**. 쿨다운 파일은 전역 1개(`:65-68`). 즉 프로젝트 A 의 **warn** 이 90초 동안 프로젝트 B 의 **block** 을 삼킨다(우선순위 역전) |
| calendar errors 리스트 누락 | **확인, 실측** | `calendar_gate_emitter.py:131-132` 가 `errors=[]` 를 만들어 넘기고 **135-138에서 무시**. 실측: 전손상 원장 → `scanner_errors:1, overdue:0, adapter_payload:**null**`. 손상이 "부채 없음"과 구분 불가 |
| main 이 cwd 선택에 session_id 미사용 | **확인** | `:498 _select_active_sid(cwd)`. `session_id` 는 `:458` 의 work_unit breadcrumb 용 `_wu_sid` 로만 쓰임 → 한 트리의 동시 세션 2개가 같은 autopilot state 를 몬다 |

**반증된 것: 없음.** 12건 모두 코드/실측과 일치했다.

root 보고 중 내가 추가로 확인한 것: `wallclock_elapsed`(`autopilot_state.py:127-128`)의 `max(0.0, ...)` 는 미래 `started_ts` 를 0 으로 클램프하고, `from_dict` 의 `float()` 는 NaN 을 통과시키며 `nan >= 1800` 은 False → **두 경우 모두 wallclock 캡이 영구히 열린다**. `state_path`(:210-211)에는 `completion_gate.py:119,164,224` 가 갖는 `"/" in sid` 류 가드가 없다(다만 Stop 경로의 sid 는 파일명 stem 유래라 악용에는 파일 쓰기가 선행 필요).

---

## 4. 이견 (약한 것 1건)

root 의 "calendar `main` 이 hook event/agent/reentry 를 전혀 무시하고 전역 state 를 스캔한다"는 사실로 맞다. 다만 그 모듈은 **입력 비의존을 명시적 설계로 선언**하고 파이프 계약만 지키려 stdin 을 배수한다(`calendar_gate_emitter.py:45-53,165-172`). 결함으로 계상할 때 "미선언 누락"이 아니라 "선언된 설계의 대가(서브에이전트/재진입 턴에도 동일 발화)"로 라벨해야 한다. 결론 방향에는 동의한다.

그 외 root 보고에서 내가 반대하는 지점은 없다.

---

## 5. 미확인 (양측 공통, 확대 금지)

`lib/reflexion_loop.py`, `lib/autopilot_compaction.py`, `lib/axis_scores_log.py`, `lib/ac_tree.py`, `lib/atomic_json.py`, `lib/meta_rules.py`(residual_norm 원장 작성자), `engine/orchestrator.py`, `cron/*`, `commands/harness-autopilot.md`, `docs/subsystems/handlers-hooks.md`, atlas 노트 — 전부 미독. 
그리고: 실효 hook 등록(user/project settings 병합), 설치 클라이언트의 `decision:block`/`stop_hook_active` 실제 해석, `test_*.py` 실행 결과, autosave/brain 스냅샷 실동작(이번에 `mark("save")` 로 의도적 제외), Windows/Linux/WSL 상등물, 원본 provenance/license. **`stop_hook_active` 가 턴마다 리셋되는지**는 여전히 미검증이며, 리셋되지 않으면 30회/1800초 캡은 도달 불가가 된다.

---

## 6. Zeus 대응 (합의된 수정본, 구현 아님)

- **PG SSOT/Git 정의**: 상태 4종(`state/autopilot`, `state/work_unit`, `memory/insight-index.jsonl`, `telemetry/`)이 홈 디렉터리 파일이고 원장에 repo/commit/actor 좌표가 없다. 이관 시 (1) 시도/세대 권위와 타입드 결과를 PG 에, (2) 재시도 카운터를 **분기별 재구성이 아니라 단일 갱신 경로**로, (3) 학습 후보에 불변 원문 링크(`body_ref` 상당)와 **에이전트 신원** 컬럼을.
- **8단계 SDD**: `Phase\s*[2-9]` warn 오탐(실측 1건)은 규칙 조정 대상이지 차단기 아님.
- **인간 시나리오/no mocked acceptance**: 콜드스타트 자기신고 종료 경로(683-707)와 `bool("false")→True`(581-582), `int("abc")` 예외 탈출(583→749)을 분리 처리. shared-sid 경로의 fail-closed 골격은 보존 가치가 있으나 **verdict 작성자 신원 검증이 추가되어야** Zeus 의 "엄격 재현"을 만족한다.
- **사람 승인**: escalate 를 사람 채널로 라우팅하는 배선은 **신규 작업**(현 6개 파일에 없음). 종료 안내문은 `can_continue()` 4조건 전체를 되돌리는 절차로 교체 필요.
- **Astra→Sol→Terra 자격 이관**: 원장 작성자 검증이 호출자 제출 문자열이고(`insight_index.py:72-84` 가 스스로 advisory 라 명시) 에이전트 신원 필드가 없다. 현 스키마로는 "누가 배웠고 누가 자격을 얻는가"를 표현할 수 없다.

---

**상태**: 6 primary 전문 완료 = 부분 검토 완료일 뿐, **전체 분석 미완료 · 흡수 승인 미완료**. 원본 수정 없음, Zeus 구현 없음, 이번 턴에서 원본 실행·쓰기·네트워크·credentials·live 접근 없음(읽기 전용 도구만 사용).