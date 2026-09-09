## 0. 실측 범위 (읽은 것 / 안 읽은 것)

**전문 정독 (지시 대상 3개, pinned `cbb5c3e…` 트리):**
- `scripts/lib/breakers/__init__.py` (27줄)
- `scripts/lib/breakers/config.py` (215줄)
- `scripts/lib/breakers/composite.py` (483줄)

**추적 목적 부분 정독:** `lib/atomic_json.py`(전문), `lib/paths.py`(CLAUDE_HOME/STATE_DIR 구간), `handlers/post_tool/agent_outcome_audit.py`(D3 구간 405-456 + 헤더), `engine/external_jury.py`(27-272), `engine/dispatch_retry.py`(전문), `engine/jury_advisory.py`(120-165), `cli/breaker_override.py`(전문), `lib/calibration/breaker_proposer.py`(1-166), `tests/test_composite_breaker.py`(전문), `tests/test_breaker_config.py`(전문), `tests/test_external_jury_retry.py`(grep+40-110), `tests/run_units.py`(격리·discovery 구간), `cli/dashboard_model.py`(breakers 섹션), `lib/providers/*`(timeout grep), `commands/harness-debate.md:61`.

**미독(명시):** `lib/breaker.py`(동명이인 모듈, 존재만 확인), providers 본문, `lib/event_store.py`, `run_all.py`, `operator_ledger` 전체, 다른 리뷰어 산출물(`docs/full-analysis/*`, `docs/tickets/verification.json`) — 지시대로 열지 않음.

**검증 불가:** "3파일 28465 bytes" — 셸 금지 조건에서 바이트 계수 수단이 없다. 파일 3개 전문을 읽었다는 사실만 주장하고, 바이트 합은 **미검증**으로 남긴다. scope 해시 두 개도 대조 대상 원본이 없어 미검증.

---

## 1. 가장 큰 발견: hook 경로에서 이 breaker는 **회로가 아니다**

`handlers` 트리 전체 grep 결과, composite breaker 참조는 `agent_outcome_audit.py:412,415` 단 한 곳이며 호출은 **`record_failure()` 하나뿐**이다. `try_acquire`·`record_success`·`any_mode_keys`는 handlers 어디에도 없다(grep 결과 0건).

귀결(코드로 확정되는 것들):

1. **OPEN이 아무것도 막지 않는다.** spawn 전에 `try_acquire()`를 부르는 hook이 없으므로 상태 머신의 출력이 소비되지 않는다. `__init__.py:14-17`의 "open-state action is OPERATOR VISIBILITY"는 좁게는 참이지만, 실질은 *가시성조차 성립하지 않는다*(§2).
2. **CLOSED로 돌아올 경로가 없다.** `record_success`가 호출되지 않고 `try_acquire`도 없으니 OPEN→HALF_OPEN→CLOSED 전이가 절대 발생하지 않는다. 한 번 trip한 (agent, mode) 키는 **영구 OPEN**이고, 이후 실패는 `composite.py:372-376`의 "extend the trip" 분기로만 들어가 **이벤트를 하나도 emit하지 않는다**. 즉 최초 `breaker.opened` 1회 이후 그 키는 영구 침묵.
3. **3/10의 rate 의미가 성립하지 않는다.** history에 `True`가 절대 들어가지 않으므로 window는 "최근 10개 실패"이고 `failures_in_window`는 항상 `len(history)`다. `composite.py:19-23`의 "≈30% rate ... vs Hystrix 50%"는 이 경로에서 거짓 — 실제 규칙은 "누적 실패 3회(감쇠 없음)"다. 시간 감쇠도 없으므로 6개월 전 실패 2건 + 오늘 1건 = trip.
4. **secondary(cross-mode) 규칙은 전 라이브 경로에서 휴면.** hook은 `any_mode_keys` 미전달, external_jury는 `external_jury.py:160`에서 의도적 미전달. `_secondary_trip`(443-482)을 실행하는 것은 단위 테스트뿐이다.

이것은 "구현이 잘못됐다"기보다 **소비 경로가 절반만 배선된 상태**이고, 그 결과 D3 문서가 서술하는 계약(감도 보정, 반개방 probe, 이중 보정)이 hook 경로에서는 **하나도 실측되지 않는다**.

## 2. 유일한 실제 try_acquire 소비자와 그 가시성 붕괴

`try_acquire`를 실제로 쓰는 곳은 `external_jury._dispatch_with_breaker`(157-186) 하나다. 이 함수 자체의 설계는 견고하다: acquire 게이트 → `call_with_retry` → `finally`에서 정확히 1회 record(재시도는 breaker에 비가시), permanent-after-acquire→`record_success`(도달=가용, 판단 타당), UNKNOWN 예외→transient(fail-toward-breaker, `external_jury.py:42-53`).

그러나 **가시성 사슬이 끊겨 있다**:
- `jury_advisory.py:143` — `emit_fn=emit_fn or _noop_emit`. `harness-debate.md:61`이 지시하는 실제 호출 형태는 `jury_advisory(architect_prompt, architect_verdict=...)`로 **emit_fn을 넘기지 않는다** → 전 breaker 이벤트가 no-op으로 버려진다.
- `cli/dashboard_model.py:121-123`의 "회로 차단기" 섹션은 `lib.breaker`(role/surgery 계열, **다른 모듈**)를 읽는다. composite breaker 상태를 보여주는 운영자 화면은 없다.
- 결론: 라이브 jury 경로에서 breaker가 열려도 **이벤트 0, 대시보드 0**. 남는 흔적은 `failures` 문자열 `circuit_open (backing off)`(163)뿐이고, 이는 advisory payload에도 실리지 않는다(`jury_advisory.py:148-151`은 실패를 `skipped_reason`으로 접는다).

또한 `jury_advisory`가 `except Exception`으로 전부 삼키므로(147), breaker 인프라 자체의 예외는 `jury_error:<Type>`로 **provider 장애와 구분 불가**하게 뭉개진다.

## 3. 단일 probe / 동시성 / CAS / lease

- **CAS 없음.** `_load` → 수정 → `_save`는 read-modify-write이고 잠금이 없다. `write_json_atomic`은 파일 단위 원자성만 준다(마지막 writer 승). `try_acquire`의 독스트링(286-288) "Performs the OPEN→HALF_OPEN transition AND sets probe_in_flight **atomically**"는 **부정확하다** — 두 프로세스가 동시에 OPEN을 읽으면 둘 다 승격·둘 다 True를 받는다. 단일 probe 불변식은 *순차 호출자에 대해서만* 성립한다. 클래스 독스트링(169-172)이 thread-unsafe를 인정하지만, try_acquire 독스트링의 "atomically"가 그 인정을 국소적으로 뒤집는다.
- **쓰기 손실 무시.** `_save`(260-262)는 `write_json_atomic`의 반환값을 버린다. `atomic_json.py:27-40`이 스스로 "Windows에서 목적지 핸들 점유 시 replace 실패 → 쓰기 **손실**, 28개 호출부 중 27개가 반환값 무시"라고 실측을 적어 놨는데, breaker `_save`가 바로 그 27개 중 하나다. 손실되는 것이 trip 기록이거나 probe 예약이면 **탐지 누락 또는 이중 probe**로 직결된다.
- **lease 회수(PROBE_TTL) 근거가 자기 코드와 모순.** `composite.py:88`은 "Generous (a real probe resolves in seconds)"라며 120s를 정당화하지만, 이 TTL이 실제로 적용되는 유일한 소비자(jury)의 probe는 provider 호출이다: `providers/openai.py:71,80` timeout **300**, `ollama.py:103,112` **300**, `anthropic.py:100` **180**. `call_with_retry` 기본 3회 시도(백오프 총합은 ≤1.5s로 무의미) → **단일 정상 시도가 TTL을 2.5배 초과**할 수 있다. 즉 회수 조건은 "홀더 사망"이 아니라 "느린 정상 probe"에서 일상적으로 성립한다 → 죽었다고 단정한 살아있는 probe를 회수(324-335) → 이중 dispatch + 두 record의 경쟁(늦은 실패가 앞선 close를 덮어써 trip_count/state가 뒤엉킴). wedge를 고치면서 double-admit을 도입한 교환인데, 교환 비용이 실측 근거 없이 산정됐다.
- **예약 없는 True 경로.** `try_acquire`의 HALF_OPEN 분기에서 `probe_in_flight`가 False면 316-318이 **예약도 하지 않고, 이벤트도 없이** True를 반환한다. 이 상태(HALF_OPEN + flag False)는 정상 전이로는 안 생기지만 찢어진 쓰기·수동 편집·`_load` 강제 보정으로는 생긴다. 그때 동시 호출자 전부가 무제한 통과한다. 단일 probe 불변식의 구멍.

## 4. 실패·성공·"응답 도달"의 권위

- jury 경로의 권위 정의는 명시적이고 방어 가능하다: **도달=가용**(permanent 예외는 코드 버그이므로 trip 금지, 155-156, 175-177), 미분류 예외는 transient(=breaker 쪽으로 실패). 이 비대칭은 정당하고 유지 가치가 있다.
- 반면 hook 경로의 권위는 `_resolve_failure_mode(d1_verdict, d2_result)`(406)에 위임돼 있고, **성공을 기록하지 않기로 한 선택**(427-431: 파일 없는 키를 만들면 디스크가 는다)이 §1.3의 rate 왜곡을 만든 원인이다. "디스크 절약"을 위해 분모를 통째로 버린 셈이라, 비용/효과가 뒤집혀 있다.
- `record_failure`가 OPEN에서 history만 append하고 저장(372-376)하므로, 영구 OPEN 키의 파일은 계속 갱신되지만 window(10) 상한이 있어 무한 증식은 아니다 — 단 `trip_window`가 0이면 아님(§6).

## 5. 파일 손상 · 경로 · 시계

- **손상 내성은 실제로 잘 돼 있다.** `_load`(226-258)가 state·history·trip_count·3개 타임스탬프를 fail-soft로 강제 변환하고, 그 근거(post_tool hook에서의 raise = fail-CLOSED wedge)를 정확히 적었다(238-243). 테스트 2건이 이를 실측한다(369-397). **유지해야 할 방어.**
- **그러나 같은 논리가 config에는 적용되지 않았다.** `record_failure`는 `_load`보다 **먼저** `resolve_thresholds()`를 부른다(345). `_load_policy`(142-148)는 `OSError`만 잡는다 → 깨진 UTF-8 yaml은 `UnicodeDecodeError`(ValueError 계열)로 **미포착 전파**. hook에서는 `_safe_call`이 삼켜서 breaker 기록만 통째 소실(조용한 탐지 중단), jury에서는 `finally` 안에서 터져 원 예외를 가리며 패널 전체를 죽인다(`ask_jury` 루프에 `_dispatch_with_breaker`용 try가 없음, 234-239 — legacy 경로의 per-member 예외 방어와 비대칭).
- **경로:** `_key_filename`(130-134)은 `/`·`\`만 치환한다. traversal은 막지만 **단사(injective)가 아니다** — `a/b`와 `a_b`가 같은 파일로 붕괴하고, `agent_type`에 `__`가 있으면 `breaker_proposer._parse_key_filename`(134-142)의 역변환이 키를 잘못 쪼갠다. 또 `project_id`는 **무검증으로 join**된다(137-140). 현 호출자는 hex(`project_id_for`) 또는 리터럴 `_external_jury`뿐이라 **현재 악용 경로 없음**이지만, 공개 생성자 인자이므로 방어 깊이는 비어 있다. `..`가 project_id면 상위로 나간다.
- **시계:** `_now`는 `time.time()`(wall clock). cool_off는 절대 epoch로 영속화되므로 프로세스 간 공유상 불가피한 선택이지만, **역행/도약에 대한 클램프가 없다**. 시계가 앞으로 튀면 조기 probe, 뒤로 튀면 최대 `cool_off_until - now`만큼 과잉 침묵(cap보다 훨씬 길어질 수 있음). `now - reserved_at`이 음수가 되는 경우 TTL 회수는 영원히 불가 → wedge 재현. 값 하나(`cool_off - now > backoff_cap`이면 경과 처리) 로 막을 수 있는데 없다.
- 첫 backoff는 `2^1*60 = 120s`다(387-388, trip_count가 먼저 증가). `BACKOFF_BASE_SEC=60`이라는 이름과 `테스트 주석 "60s for first trip"`(test:176)이 어긋난다 — 동작은 일관, 문서/주석이 틀림.

## 6. hot reload · 정책 토큰 · 값 검증 (config.py)

- **핫 리로드 비용/이득:** 캐시 없이 매 record마다 yaml을 읽는다(156-163). hook 빈도에서 비용은 무시 가능. 그러나 **생명주기 중간 변경의 파괴성**이 검토되지 않았다: `trip_window`를 줄이면 `_trim_history`(156-160)가 **디스크의 과거를 영구 절단**한다. 되돌려도 복구 불가. 조회 파라미터가 아니라 파괴적 마이그레이션인데 "안전(ambiguous→safe token)"으로 분류돼 있다.
- **토큰 게이트의 방향 분류에 실질 구멍:**
  - `apply_override("trip_window", 1, token=TOKEN_SAFE)` → 통과. 그러면 history가 최대 1개, `failures_in_window ≤ 1 < trip_per_mode(3)` → **primary trip이 영구히 불가능**. "안전 토큰"으로 회로를 완전히 무력화할 수 있다. `_KEY_DIRECTION_POLICY`의 "ambiguous"는 이 단조적 무력화를 놓친다(69-70의 근거 "큰 window는 더 많은 sample 필요"는 축소 방향을 보지 않음).
  - 키 간 **정합성 검증 없음**: `trip_per_mode > trip_window`, `backoff_base > backoff_cap` 같은 무의미 조합을 막지 않는다. 상한도 없어 `trip_per_mode=10**9`(강한 토큰)도 통과.
- **검증이 쓰기 게이트에만 있고 읽기 경계에 없다.** `apply_override`는 `value > 0`을 강제하지만(179-180), `resolve_thresholds`는 `isinstance(v, int)`만 본다(162). 파서는 `int("-5")`, `int("0")`을 통과시킨다(120-126). yaml은 **평범한 사용자 소유 파일**이며 문서가 경로까지 공개한다(22). 손으로 한 줄 고치면 토큰 게이트는 전부 우회된다. 실제 결과:
  - `trip_per_mode: 0` → `failures >= 0` 항상 참 → **첫 실패에 즉시 trip**.
  - `trip_window: 0` → `_trim_history`가 `len<=0` 거짓 → `history[-0:]` = **전체 리스트**(파이썬의 `-0` 함정) → 히스토리 무한 증식 + 확정 trip.
  - `backoff_cap_sec: 0` 또는 음수 → cool_off가 현재/과거 → 침묵 구간 소멸.
  즉 **"asymmetric token gate"는 권한 경계가 아니라 CLI 편의 가드**다. `config.py:1-36`과 README의 서술은 이를 권한 통제처럼 읽히게 한다 — claim과 oracle의 분리가 필요한 지점.
- `_save_policy`(151-153)만 harness의 원자 쓰기 관례를 벗어나 `write_text` 직접 사용 → 찢어진 쓰기 시 override 전량 조용히 소실(방향은 default=더 민감 쪽이라 상대적으로 덜 위험하지만, 운영자 의도 소실은 무고지).
- 파서 상태기계: `in_overrides`는 `overrides:`에서만 켜지고 `version:`에서만 꺼진다(109-115). `overrides:` 뒤의 **다른 최상위 블록의 들여쓴 줄까지 흡수**한다(예: `notes:` 하위의 `trip_per_mode: 9`). 관대함이 아니라 오독이다.
- **정책 소비의 baseline 드리프트:** `breaker_proposer`는 `composite`의 **모듈 상수**를 기준으로 제안을 만든다(52-57, 63). yaml override가 적용된 뒤에도 제안은 default 대비로 계산되고, 독스트링 37-39는 "임계 = 모듈 상수, 적용은 코드 편집"이라고 **v15.16 이전 사실**을 말한다. 제안기와 실행기가 서로 다른 진실을 본다.

## 7. cross-mode / key identity

- 키 정체성은 `(agent_type, failure_mode, project_id)` 3튜플이며 파일명은 앞 2개, 디렉터리는 project_id다. hook은 `project_id_for(project_root)`(sha256 앞 12hex), jury는 전역 sentinel `_external_jury`(37) — **project 격리와 vendor 전역성의 의도적 분리**이고 근거도 타당(vendor 장애는 프로젝트 스코프가 아님).
- 다만 jury의 `agent_type=m.provider`는 alias 정규화 전 값(`JuryMember.provider`가 "canonical name or alias", 58)이다. 같은 vendor를 alias로 부르면 **별개 breaker 파일**이 생겨 trip이 분산된다. `get_provider`가 alias를 흡수한 뒤의 canonical 이름을 키로 쓰지 않는 것은 키 정체성 누수다(providers 본문 미독이므로 alias 실존 여부는 **미검증 가설**로 표시).
- secondary 창(`combined[-trip_any_window:]`, 478-481)은 **서로 다른 타임라인을 이어붙인 뒤 꼬리를 자른다**. 결정적이긴 하나 시간적 의미가 없고, 자기 history를 먼저 넣으므로(469) 형제가 길면 **현재 실패가 창 밖으로 밀려날 수 있다**. "최근 20개 이벤트"라는 서술과 실제 계산이 불일치. 현재 휴면이라 실해는 없지만, 배선하는 순간 발현된다.

## 8. 테스트: mock과 실호출, claim과 oracle

- 두 breaker 테스트 스위트는 **실호출 없음**(파일 IO + 시계 monkey-patch), jury 테스트는 `_Fake` provider mock. 즉 여기서 나오는 초록은 **로직 오라클**이지 provider/OS 실동작 오라클이 아니다.
- **테스트 밀폐성 조건부 결함:** `test_composite_breaker.py`는 `CFG.CONFIG_PATH`를 격리하지 않고 `TRIP_PER_MODE=3` 전제를 그대로 단언한다(126-137 등). `test_external_jury_retry.py:105`도 "default trip_per_mode=3" 전제. 런타임은 `resolve_thresholds()` → 실 CLAUDE_HOME의 yaml을 읽는다. `run_units`는 임시 CLAUDE_HOME + junction 격리를 하고 `_ASSET_SUBDIRS`(210-213)에 `config`가 **없으므로** 격리 하에서는 안전하다. 그러나 같은 파일이 스스로 적어 둔 **degraded 경로**(263-266, "NO isolation", 228-232의 POSIX 사고 기록)에서는 실 홈이 그대로 쓰이고, `python tests/test_composite_breaker.py` 직접 실행(테스트 헤더가 안내하는 사용법)도 비격리다. **이 저장소가 출하한 CLI로 운영자가 `trip_per_mode=4`를 적용하면, 그 두 상황에서 breaker 테스트가 붉어진다.** 기능과 그 기능의 테스트가 서로를 깬다.
- `test_breaker_config._redirect_config`(47-50)는 `CFG.CONFIG_PATH`를 갈아끼우고 **복원하지 않는다**. 서브프로세스 실행이라 현재는 무해하지만, in-process 실행으로 바뀌면 오염원이다.
- `test_secondary_trip_across_modes` 주석(288-289)의 산술("2+2+2=6")이 틀렸다(실제 1+2+2=5). 단언은 통과하지만, **경계값(정확히 5)에서 통과하는 테스트를 여유값(6)이라고 오해한 채** 남아 있어 임계 변경 시 조용히 의미가 바뀐다.
- **runner 영수증 부재:** pinned 트리에서 `test_composite_breaker`를 언급하는 파일은 테스트 파일 자신 1개뿐이다. `HARNESS-ADVANCEMENT-ROADMAP.md:120`의 "run_units 158/158 · run_all 28/28"은 **산문 주장**이며 기계 생성 출력 아티팩트를 찾지 못했다. 이 검토에서 나는 아무것도 실행하지 않았다(지시대로) — 따라서 **현재 통과 여부는 미실측**이고, 과거 PASS 기록은 source 역사로만 취급한다.

## 9. Zeus 연결 — 등가성 제안만 (구현 미검토이므로 판정 아님)

Zeus의 PG runtime/Git 정의, runner 영수증, AstraSolTerra 자격, 인간 SDD·no-mocked-acceptance 축과 **등가로 대응시킬 수 있는 항목**만 제시한다. 아래는 Zeus 측 구현을 읽지 않았으므로 채택·통과·동치 판정이 아니다:

1. **"배선되지 않은 게이트"를 수용 기준에서 제외하라.** §1이 보여주듯 상태 머신이 존재하고 테스트가 초록이어도 소비자가 없으면 런타임 효과는 0이다. Zeus의 no-mocked acceptance는 "게이트를 호출하는 실 경로의 영수증"을 요구해야 등가다 — 단위 테스트 초록은 등가물이 아니다.
2. **가시성은 emit_fn 기본값이 아니라 배선으로 증명하라.** §2처럼 기본 no-op + 호출부 미전달이면 "operator visibility" 불변식은 문서상으로만 성립한다.
3. **토큰 게이트를 권한 경계로 계산하지 말라.** §6 — 게이트 뒤의 상태가 평문·무서명·사용자 쓰기 가능 파일이면 CLI 게이트는 UX다. Zeus에서 "정책 토큰"을 권한으로 셈하는 곳이 있다면 같은 검사가 필요하다(등가성 제안, 미검증).
4. **읽기 경계 검증.** 쓰기 게이트에만 검증을 두는 패턴(`apply_override` vs `resolve_thresholds`)은 Zeus의 config 소비 지점에도 동형으로 존재할 수 있다.
5. **runner 영수증의 밀폐성 조건을 영수증에 포함시켜라.** §8 — "격리됨/degraded" 여부가 기록되지 않으면 같은 명령의 두 실행이 다른 것을 검사한다(`run_units.py:228-232`가 이미 그 사고를 자기 트리에서 실측 기록했다).

전체 closure·라이선스·OS 실동작·채택 여부에 대해서는 **판정하지 않는다(false로 표시)**. 모델/provider 규격, 과거 논쟁, CONVERGED 인용은 source 역사로만 읽었고 현재 권위로 쓰지 않았다.

## 10. 유지해야 할 방어 (되돌리지 말 것)

- `_load`의 fail-soft 강제 변환 전부(226-258) + 그 근거 주석 + 대응 테스트 2건. hook 경로 raise를 wedge로 규정한 판단이 정확하다.
- jury의 "도달=가용" 분류와 UNKNOWN→transient(fail-toward-breaker).
- `finally` 단일 record(재시도 비가시) 규율 — 재시도가 breaker를 N배 오염시키는 흔한 결함을 정확히 막는다.
- `_key_filename`의 traversal 차단(단사성 문제와 별개로 유지).
- composite 모듈 상수를 default로 남긴 back-compat 유지, 그리고 `thresholds` 주입이 fork가 아닌 additive라는 점.
- `write_json_atomic`의 fsync + Windows replace 재시도.

## 11. 심각도 순 요약

| # | 항목 | 근거 | 성격 |
|---|---|---|---|
| 1 | hook 경로에 try_acquire/record_success 없음 → OPEN이 무효, 영구 OPEN, rate 의미 붕괴 | handlers grep 0건, `agent_outcome_audit.py:405-431`, `composite.py:372-376` | 배선 결손(실측) |
| 2 | 라이브 jury 경로 breaker 이벤트 전량 no-op + 대시보드 미연결 | `jury_advisory.py:143`, `harness-debate.md:61`, `dashboard_model.py:121-123` | 가시성 결손(실측) |
| 3 | `trip_window` 축소가 safe 토큰으로 primary trip 무력화 | `config.py:69,192` × `composite.py:348,380` | 정책 결함 |
| 4 | yaml 읽기 경계 무검증(0/음수/`-0` 슬라이스) → 게이트 우회 | `config.py:120-126,162`, `composite.py:156-160` | 검증 결손 |
| 5 | PROBE_TTL 120s < provider timeout 180~300s → 살아있는 probe 회수·이중 dispatch | `composite.py:88,324` × `providers/*.py:71,100,103` | 근거 오류 |
| 6 | try_acquire "atomically" 주장 vs CAS 부재 + `_save` 반환값 무시 | `composite.py:286-288,260-262`, `atomic_json.py:27-40` | 문서-구현 괴리 |
| 7 | 깨진 yaml → `resolve_thresholds` 미포착 예외(hook 무음 중단 / 패널 사망) | `config.py:146-148`, `external_jury.py:180-185,234-239` | 하드닝 비대칭 |
| 8 | 테스트가 CONFIG_PATH 비격리 → 자기 CLI 사용 시 조건부 red | `test_composite_breaker.py` 전반, `run_units.py:210-214,263-266` | 밀폐성 결함(조건부) |
| 9 | proposer baseline이 override를 안 봄 + 독스트링 stale | `breaker_proposer.py:37-39,52-57` | 드리프트 |
| 10 | secondary 창의 비시간적 연결, 키 파일명 비단사, project_id 무검증 join, wall-clock 클램프 부재 | `composite.py:130-140,469-481` | 휴면/방어깊이 |

독립 판단은 위와 같고, 다른 리뷰어 산출물은 열지 않았다. 대조 토론 시 §1·§2(배선/가시성)와 §3~§4(권한·검증 경계)가 쟁점이 될 것으로 본다. 필요하면 이 보고서를 `docs/full-analysis/` 아래 파일로 저장하겠다 — 저장 경로를 지정해 주면 그때 기록한다(현재까지 쓰기 작업 없음).