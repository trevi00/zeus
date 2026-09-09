## 읽은 범위 (pinned a3f8b3be…)

**전문 5개(대상)**: `scripts/engine/`의 `checks.py`(285줄), `gate_runner.py`(179), `select_ready.py`(99), `testgen.py`(70), `tick.py`(379).
**의미 확정용 추가 읽기(같은 pinned 트리)**: `lib/derive_state.py`(전문), `lib/ledger.py`(전문), `lib/preconditions.py`(전문), `lib/repair_tier.py`(전문), `engine/staleness.py`(전문), `engine/gate_ratchet.py`(전문), `cli/testgen_cmd.py`(전문), `cli/residual_cmd.py`(20–123), `cli/step_cmd.py`(440–502), `engine/pipeline_loader.py`(150–309), `lib/paths.py`(24–84 grep 컨텍스트), `tests/integration/test_engine_smoke.py`(전문), 파일 목록 glob 2회 + `verdict_mode|actor` grep 1회.
**안 읽음**: 다른 리뷰 보고서, 개인 설정·세션·비밀, 외부 웹. **실행/쓰기 0** — 차단 이력이 있는 gate-writer ERROR probe는 재현·우회 시도하지 않았고 아래는 전부 정적 반례다.

---

## 1. `checks.py` — 판정기 레지스트리

**의미**: `check.type` 8종을 `(verdict, evidence)`로 환원하는 유일한 실행부. ERROR를 FAIL과 분리하는 정책이 이 파일에서 시작된다.

**정적으로 확인된 방어**
- `run()`의 포괄 except(:283)와 미등록 type(:280)이 모두 ERROR — 판정기 고장이 PASS/FAIL로 새지 않는다.
- `_trigger_effect`가 `observe_cmd` 없으면 ERROR(:227) — 설정만 맞고 실증 없는 상태를 통과로 안 흡수한다.
- `against` 파일에 `gate-patterns` 블록이 없으면 ERROR(:125) — 대조 규칙 부재를 통과로 접지 않는다.
- `repeat` 비정수/0 이하 ERROR(:38,:40), 첫 실패 즉시 중단 후 `exits` 전량 보고.
- `python_exe()`(paths.py:78)가 미피닝 시 예외 → `run()`이 ERROR로 흡수. bare `python` 폴백 없음.

**중요 결함**
- **`_metric_threshold`가 종료 코드를 버린다.** `_source_text`(:180)는 `{"cmd","exit"}`를 돌려주는데 `_metric_threshold`(:199–208)는 `meta`를 evidence로만 쓰고 `exit`을 판정에 안 쓴다. `_db_query`(:251)는 `returncode != 0`을 FAIL로 잡는다 — 같은 파일 안의 비대칭. 반례: 커버리지 도구가 스택트레이스와 함께 exit 1로 죽으면서 stderr에 `lines: 100.0%`를 찍으면 `extract`가 물어 **PASS**. 크래시한 측정기가 수치 게이트를 연다.
- **`_file_content`의 `forbid`가 나머지 판정을 삼킨다.** `forbid` 분기(:98–113)가 `against`/`expect`보다 먼저 return한다. 한 check에 `forbid`와 `expect`를 같이 선언하면 존재 의무는 조용히 사라지고, 로더(pipeline_loader:231–258)도 이 배타성을 검사하지 않는다. 여기에 `forbid`+대상 0건=PASS(:99–101, 의도된 설계)가 겹치면 **target 오타 한 글자가 영구 초록**이 된다 — 금지 패턴 게이트에는 "대상 ≥1" 하한이 없다.
- **`_http_probe`는 접속 불능을 FAIL로 기록한다**(:155–156). 모듈 독스트링이 선언한 "판정기 자체 실패=ERROR" 규율의 예외이며, 주석은 이를 "관측 결과"로 정당화한다. 결과적으로 프록시·DNS·포트 미기동 같은 **환경 사유가 제품 실패로 원장에 앉고**, `repair_tier.FAMILY_THRESHOLD=2`(repair_tier.py:27)에 따라 두 번이면 조사 등급 지시까지 발동한다.
- **Windows/Linux(WSL) 경계가 FAIL로 나타난다.** `_exit_code`는 `shell=True`(:45)로 플랫폼 셸에 그대로 넘기고, `_pinned_cmd`는 `runtime.yaml`의 **머신 로컬 절대경로**(paths.py:62–80)를 박아 넣는다. 같은 revision·같은 pipeline이 WSL 쪽에서 돌면 `"C:\...\python.exe"`는 없는 경로 → 127 → **FAIL**(ERROR 아님). 원장에는 실제 결함과 구분 불가능한 FAIL이 남는다. 추가로 `_file_exists`/`_file_content`의 `root.glob`은 Windows에서 대소문자 무시, POSIX에서 구분 — **같은 트리에서 플랫폼별로 verdict가 갈리는 경로**가 있다.
- **예산 단위가 상위 캡과 무관하다.** `CMD_TIMEOUT_S=600` 고정, `repeat: N`이면 최악 N×600s. `tick.WALLCLOCK_TTL_S=1800`(tick.py:39)은 tick 시점에만 평가되므로 게이트 하나가 세션 TTL을 넘겨 돌 수 있고, per-check 예산 override 지점이 없다.
- `_trigger_effect`의 관측 단계(:229–238)는 exit 코드도, **관측된 실행의 시점·revision도 안 본다.** `gh run list` 류 출력이 과거 커밋의 성공을 보여도 정규식만 물면 PASS다 — "트리거 실증"이 현재 산출물에 귀속되지 않는다.

---

## 2. `gate_runner.py` — 합산과 물화

**의미**: machine 문장은 직접 판정, render/human 문장은 선행 `gate_check`를 소비만 하고, `gate_verdict`의 단일 writer로 남는다.

**정적으로 확인된 방어**
- ERROR 존재 시 `gate_verdict` 미발급 + `stage_finished(status:error)`(:126–129) — PASS/FAIL 폴백 없음.
- PENDING_HUMAN에서 verdict를 안 낸다(:169–170) — 파킹이 완료로 승격하지 않는다.
- `evidence_refs`(:98,:109,:116)로 verdict→gate_check id 역추적.
- `gate_active.json`은 fail-open 표지임을 코드가 명시(:75–76), 잠금이라 주장하지 않는다.
- `_external_verdict`의 `cycle_started.redo` 철회(:42–44) — 재개방된 단계의 지난 사이클 사람 승인이 살아남지 않는다. 이건 실제로 배선된 방어다.

**중요 결함**
- **`_external_verdict`는 문장에 눈이 멀었다.** 필터가 `p.get("stage")==stage_id and p.get("verdict_mode")==mode`뿐(:47) — `statement`를 안 본다. 반례: 한 단계에 human 문장이 둘("설계 승인", "배포 승인")일 때 `residual_cmd pass --statement <설계>` 한 번이면(residual_cmd.py:99–102가 statement를 성실히 기록해도) 두 문장 모두 PASS로 합산되어 `gate_verdict PASS`가 난다. step_cmd judge는 쓰기 시점에 문장을 강제하는데(step_cmd.py:479–490) **소비 측이 그 정보를 버린다.** 역방향도 성립: A에 PASS 뒤 B에 PARTIAL을 적으면 최신값이 PARTIAL이라 **이미 승인된 A까지 파킹으로 되돌아간다**(최신-우선 fold의 부작용).
- **철회·컴팩션이 외부 판정에 안 걸린다.** `_external_verdict`는 원시 이벤트를 그대로 훑고 `derive_state.apply_retractions`(derive_state.py:33)를 통과시키지 않는다 → **tombstone된 사람/심판 PASS가 여전히 게이트를 연다**. 반대 방향으로, `gate_check`는 `PRESERVED_EVENTS`(ledger.py:132–145) 밖이고 `_is_audit`(ledger.py:152–156)은 `actor=="operator"`만 보존한다 — **`actor:"judge"`인 render 판정(step_cmd.py:494)은 컴팩션에서 접힌다.** 그러면 통과했던 render 게이트가 pending으로 되돌아가 재심판이 돈다. 그리고 컴팩션 등가 게이트(ledger.py:401–405)가 대조하는 4개 도출(`derive_stage_states/completed/failure_ledger/cycle`) 중 **어느 것도 외부 판정을 안 본다** → 의미 손실이 fail-closed 게이트를 조용히 통과한다.
- **REJECT 예산 재시작이 tick과 어긋나 교착을 만든다.** 여기서 `retries`(:144–146)는 단계의 `feedback_issued`를 **처음부터 전부** 센다. tick(:216–223)은 마지막 REJECT **이후**만 센다. 반례: `max_retries=3` 소진 → operator REJECT → 재작업 후 게이트 FAIL. gate_runner는 `retries=3`이라 `feedback_issued`를 안 낸다 → `derive_stage_states`가 READY로 회귀시키는 유일한 트리거(derive_state.py:97–100)가 없다 → 단계는 FAILED로 고정 → `select_ready`가 FAILED를 건너뛰고(:55–57), tick의 FAILED 라우터는 `retries=0 < 3`이라 `continue`로 그냥 넘어간다(:224–225) → 최종적으로 `halt: blocked` "의존 그래프 점검 필요(anomaly)". **예산을 되돌려 준다고 두 곳이 말하는데 실제로는 되돌아오지 않는다.** 같은 비대칭이 `cycle_started.redo`에도 있다 — 나선이 재개방한 단계의 `feedback` 예산은 리셋되지 않는다.
- **동시성은 표지뿐이다.** `_run_gates`는 :91에서 이벤트를 한 번 읽고 그 스냅샷으로 `retries`를 세므로, 같은 단계에 게이트가 병렬로 두 번 돌면 둘 다 `feedback_issued`를 발행하고 `gate_verdict`도 각각 앉는다. `ledger.file_lock`은 append 원자성만 보장한다(ledger.py:259) — read-modify-write 구간은 무보호다.

---

## 3. `select_ready.py` — 다음 단계 선택과 완료 fold

**의미**: 상류 `gate_verdict PASS`(파일 존재 아님)만을 준비 조건으로 보는 결정론 선택기 + `is_done`.

**정적으로 확인된 방어**
- `_dep_satisfied`의 stage 분기가 `completed`(=최신 verdict PASS fold)만 본다(:38). `test_engine_smoke.py:243–253`이 **차단 방향**을 실제 이벤트로 단언하고(“PASS를 빼면 beta가 안 열린다” + 진공 방지 대조 + “산출물 파일이 있어도 안 열린다”), 뮤테이션으로 이 단언의 부재를 적발했던 경위까지 남아 있다 — 이건 boolean 픽스처가 아니라 실측 단언이다.
- RUNNING/GATING/FAILED/SKIPPED 후보 배제(:55–57)로 재중복 디스패치 차단, tie-break `(depth, seq, id)` 결정론.

**중요 결함**
- **`is_done`이 ERROR를 못 본다 — 그리고 tick의 순서가 그것을 done으로 만든다.** `is_done`(:85–99)은 `derive_completed`(최신 `gate_verdict` PASS)와 SKIPPED만 본다. 그런데 gate_runner는 ERROR에서 **`gate_verdict`를 안 낸다** → 최신 verdict는 이전 PASS 그대로 → 그 단계는 여전히 `completed`. 반례: 전 단계 PASS로 완주한 상태에서 어떤 단계의 게이트를 다시 돌려 판정기 ERROR가 나면(`stage_finished status=error`), `tick.drive`는 `is_done`을 :120에서, ERROR blocker 스캔을 :158에서 하므로 **`{"outcome":"done"}`을 반환하고 INV-P2 blocker는 영원히 안 읽힌다.** `derive_stage_states`는 그 단계를 FAILED로 알고 있지만(derive_state.py:134–136) `is_done`은 states를 SKIPPED 판별에만 쓴다.
- **`probe`가 아무 데서도 주입되지 않는다.** tick은 `sr.select_ready(pl, events, project_root)`(tick.py:287)로 3인자 호출 → `probe=None` → `state:"running"` 의존(pipeline_loader R2, 예: `blackbox-test`←구동 중인 `implementation`)은 **구조적으로 영원히 불충족**이다. 파일 주석은 이를 "정직 파킹, 증분 5+"라 하지만 소비자에게 도달하는 문구는 `halt: blocked … 의존 그래프 점검 필요 (anomaly)`(tick.py:340) — **미배선이 그래프 이상으로 오귀속된다.**
- **parallel 샤드 0건이 침묵한다.** `project_root.glob("domain/*.md")`(:80–81) 하드코딩이고, 결과가 빈 리스트여도 그대로 fan-out 목록으로 나간다. "domain 명세가 아직 없다"와 "샤드가 0개다"가 같은 값이 되고, 샤드 수를 묶는 게이트는 이 파일 범위에 없다.
- **premise 의존은 존재만 본다**(:34). `preconditions` 지문은 `_preconditions`를 **선언한 단계에만** 붙으므로(staleness.py:38–40이 `specs` 없으면 skip), 선언 안 한 단계의 premise 내용 변경은 완료 판정에 아무 흔적을 안 남긴다.

---

## 4. `testgen.py` — GWT → 수용 테스트 스켈레톤

**의미**: usecase의 AC 앵커+GWT를 결정론 추출해 전량 xfail pytest 스켈레톤을 생성. 승격=본문 채우고 xfail 제거.

**정적으로 확인된 방어**
- GWT 0건 → 빈 문자열(:60–61), CLI가 exit 1 + "GWT를 먼저 채워라"(testgen_cmd.py:31–34). 0건을 빈 초록 스위트로 만들지 않는다.
- 타임스탬프 없음, `sorted(key=(ac, when))` + 이름 충돌 시 suffix(:64–67) → 같은 입력에 바이트 동일. 멱등 주장은 코드와 일치한다.
- 본문이 `raise NotImplementedError`라 우연한 XPASS는 생성 직후엔 불가능.

**중요 결함**
- **생성물이 exit_code 게이트를 초록으로 만든다.** 전량 `@pytest.mark.xfail(..., strict=False)`(:32). pytest는 xfail 스위트에 대해 **exit 0**을 낸다. 즉 `check: {type: exit_code, cmd: pytest}` 계열 게이트는 **수용 단언 0건 상태에서 PASS**한다. 읽은 범위 안에 xfail/xpass 비율을 세는 소비자는 없다(`lib/suite_floor.py`·`lib/test_outcome.py`가 존재하나 이 5파일·gate 경로에서 참조되지 않는다 — 미확인으로 남긴다). 이것이 요청서가 말한 "스켈레톤을 실행 증거로 승격"의 정확한 형태다.
- **`strict=False`라 승격이 기계 강제가 아니다.** 구현자가 본문을 채우고 xfail을 **안 지우면** XPASS → 여전히 성공. "xfail 제거가 승격"은 산문일 뿐 어떤 판정기도 그걸 안 본다.
- **텍스트 이스케이프가 없다.** `BLOCK`(:31–40)이 `{g}/{w}/{t}`를 docstring 안에 그대로 넣는다. usecase 한 줄에 `"""`가 들어 있으면(GWT 캡처는 `[^\n]+`, 절단은 120자뿐) 생성된 모듈이 **SyntaxError** → 수집 실패. 원인(usecase 한 문자)과 증상(수용 게이트 FAIL/ERROR)이 멀리 떨어진다.
- **원천 귀속이 파일명뿐이다.** `HEADER.format(src=usecase_file.name)`(:62) — 경로도 해시도 revision도 없다. 스켈레톤이 어느 usecase 개정 위에 섰는지 대조 불가. `_AC_RE.findall` 후 `acs[0]`만 쓰므로(:50), AC-001·AC-002가 같은 단락에 있고 GWT가 하나면 **조용히 AC-001로 귀속**된다. 앵커 없는 GWT는 전부 `UNANCHORED`로 합류해 함수명만 `_2, _3`로 갈린다.
- **재생성이 승격분을 지운다.** `testgen_cmd.py:37`이 `out.write_text`를 무조건 수행 — 헤더의 "본문 손실 주의"는 경고 문자열이고 가드가 아니다. 기존 파일 존재/diff 검사 없음.

---

## 5. `tick.py` — Stop 재강제 판정 코어

**의미**: 원장만 읽어 `idle|continue|done|halt`를 낸다. 캡·래칫·staleness·ERROR blocker·debate 라우터·render/human 분기를 한 함수(`drive`)가 순서대로 건다.

**정적으로 확인된 방어**
- `main()`의 포괄 except → `halt: driver_error`(:371–373). 드라이버 고장이 done으로 안 샌다.
- 래칫·staleness import 실패는 fail-open이되 루프를 안 막는다(:91,:106) — 실패 시 조용히 통과하는 축이지만 명시돼 있다.
- iter 계수는 `stage_started`만(:82) — 위임 dispatch로 캡이 조기 소진되지 않는다. `test_engine_smoke.py:427–457`이 위임 32건 무영향·비-l2-spawn 앵커 무효·l2-spawn 앵커 재개를 실제 원장으로 단언한다(뮤테이션 사각 지목 포함).
- delegation 캡은 `delegation` 플래그만 계수(:141)해 iter와 이중계수 회피.
- `_continue` 배너로 지시 출처가 사용자 발화와 구분된다.

**중요 결함**
- **staleness 분기가 캡 앞에 있다 — 무한 루프 탈출구.** `stale`은 :108–115에서 `continue`를 반환하고, iter 캡·TTL·delegation 캡은 :124–146에서야 걸린다. 재게이트가 `gate_verdict`를 못 내는 상태(그 단계에 미판정 human 문장이 있거나 판정기 ERROR)면 지문이 갱신되지 않아 stale이 영원히 참이고, `stage_started`가 안 늘어 `iter_n`도 고정 → **iter 캡·wallclock TTL·위임 예산을 전부 우회하는 동일 지시 반복**이 된다. 파일 자신이 :117–119에서 "캡보다 앞서는 것은 완주 판정뿐"이라 적어 둔 순서 규율과 어긋난다.
- **PARTIAL이 두 파일에서 다른 뜻이다.** gate_runner:118–121은 PARTIAL을 미종결(파킹)로 다루고 residual_cmd:36도 그렇게 접는다. 그런데 `_pending_external`(:344–353)은 `_external_verdict(...)[0] is None`만 pending으로 센다 → **PARTIAL은 pending이 아니다.** 결과: GATING 상태의 PARTIAL 단계는 `pend["human"]`·`pend["render"]`가 모두 비어 :278로 떨어져 "게이트를 실행하라" continue를 받고, 게이트는 다시 PENDING_HUMAN을 돌려주며(외부 문장만 있으면 새 이벤트도 안 남는다) 같은 지시가 반복된다. **사람 파킹(:337–339)으로 가는 경로가 PARTIAL에는 없다.**
- **`done`이 ERROR blocker를 앞지른다.** 위 3절 반례와 같은 축: `is_done`(:120) → `err_stages`(:152–161). ERROR가 `gate_verdict`를 안 남기는 설계와 결합해, "판정기 ERROR는 blocker"라는 INV-P2가 **완주 국면에서만 무력화**된다. 순서를 바꾸면 닫히는 종류의 결함이다.
- **`err_stages` 스캔이 철회·재개방을 모른다.** :152–158은 원시 `stage_finished`를 직접 훑는다 — `apply_retractions` 미통과이고 `cycle_started.redo`도 안 본다(derive_state.py:126–128은 state만 되돌린다). 나선이 재개방해도 halt가 유지되며, halt는 라우터보다 앞이라 루프 안에서 해제 경로가 없다(새 `stage_finished`를 사람이 만들어야 한다).
- **의미 기반 캡만 설정 불가.** `iter`·`wallclock_s`·`delegations`는 `pl["caps"]` override(:124,:125,:140)인데 `DEBATE_CAP_PER_STAGE`(:38)는 모듈 상수로만 존재하고 `caps`에서 안 읽는다. 주석이 "양 기반 캡을 대체하지 않기 위한 유일한 의미 기반 제동"이라고 강조한 바로 그 값이다.
- **귀속 축이 얇다.** `_banner`는 `sid`(세션)와 `iter`만 싣는다. `ledger.append_event`(ledger.py:261–267)가 붙이는 것은 `v/id/ts/event/payload`(+자율 스탬프 `by`)뿐 — **cycle 번호도 commit/revision도 레코드에 없다.** 사이클 귀속은 `derive_cycle` 재계산으로만, revision 귀속은 `preconditions`를 **선언한 단계에 한해** 파일 sha16 간접으로만 존재한다. 즉 "이 PASS는 어느 커밋 위에서 났는가"는 이 5파일 범위에서 기계로 답할 수 없다.

---

## Zeus 요구 대비 (이 5파일이 실제로 지지하는 것 / 아닌 것)

- **사람 인수**: `verdict_mode: human` + `actor:"operator"` gate_check 소비 경로는 실재하고 `residual_cmd`가 문장 검증까지 한다. 다만 **문장 단위 귀속이 소비 측에서 소실**(§2 첫 결함)되어 "문장별 사람 승인"은 현재 코드로 보장되지 않는다.
- **무모킹 인수**: `checks`는 전부 실제 subprocess/파일/HTTP를 친다(모킹 없음). 반면 `testgen` 생성물은 전량 xfail이라 **수용 스위트의 초록이 실행 증거가 아니다** — 승격 강제가 없다.
- **PG runtime SSOT / Git 정의 / 8단계 SDD / Astra 설계·최종검증 / Sol·Terra 자격 검증**: 이 5파일에는 해당 배선이 **없다**. 원장 레코드에 revision/commit 필드가 없고, 역할 귀속은 `dge`/`delegate --role`(step_cmd) 문자열 수준이며, PG 투영은 `engine/projection_pg.py`(미열람)의 소관이다. 존재 여부를 이 범위로 판단하지 않는다.
- **문서 TODO와 코드 구분**: `graph_query`·`metric_threshold`·`trigger_effect`·`db_query`가 "백엔드 미구축"이라는 독스트링 서술은 **코드와 어긋난다** — `_metric_threshold`/`_trigger_effect`/`_db_query`는 실제 구현이 있고 PASS를 낼 수 있다. 오래된 것은 주석 쪽이다. 반대로 `select_ready`의 "probe 미주입" 서술은 tick 호출부와 정확히 일치한다(진짜 미배선).

## 미검증 (이번 범위 밖 · 실행 안 함)

- `pipeline_loader.load`의 `caps` 기본값, `_feedback.max_retries` 기본, `_preconditions` 파싱, `VERDICT_MODES`/`CHECK_TYPES` 정의부(1–150줄 미열람) — `pl["caps"]` KeyError 가능성은 판단 보류.
- `graph_queries.run`, `engine/projection_pg.py`, `lib/suite_floor.py`, `lib/test_outcome.py`, `lib/params.py`, `lib/atomic_jsonl.file_lock`의 잠금 실제 의미론, `handlers/stop` 훅 접합면.
- 위 반례들은 전부 **코드 경로 기반 정적 추론**이다. 원장 실물·실행 재현·플랫폼별 실측은 하지 않았고, 따라서 **하네스 전체 완료·실행 재현·채택 승인은 주장하지 않는다.** Codex 결과와 교차할 때 §2(문장 귀속·컴팩션)·§3+§5(is_done↔ERROR 순서)·§5(staleness가 캡을 우회) 세 건을 우선 대조 대상으로 권한다.