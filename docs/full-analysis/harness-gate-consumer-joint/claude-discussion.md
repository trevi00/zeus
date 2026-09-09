## 읽은 추가 범위

`docs/full-analysis/harness-gate-consumer-joint/codex-initial.md`(전문 50줄), 같은 폴더 `supporting-evidence.json`(전문 — Codex의 15개 supporting 범위 확인). pinned 원문 추가: `engine/pipeline_loader.py` 309–467(앞서 150–309 기독), `validators/usecase_lint.py` 전문, `templates/_common/usecase.template.md` 전문, `handlers/stop/reenforce.py` 전문, `select_ready(` 호출부 grep(scripts/ 전역). 실행·쓰기 0, 차단 이력의 정상 gate-writer ERROR probe 미시도. **이 토론은 그 실행의 영수증이 아니다.**

---

## A. 합의 (양측 정적 근거 일치)

1. **문장 귀속 소비 누락** — `gate_runner._external_verdict`(:47)가 stage+mode만 필터. writer(step_cmd:479–490, residual_cmd:93–102)는 statement를 강제·기록하는데 소비자가 버린다. Codex의 "A=FAIL 뒤 B=PASS면 최신 B가 두 문장을 덮는다"가 내 반례(A=PASS가 B를 열어줌)와 같은 결함의 두 방향이다. Codex 표현대로 **기록 누락이 아니라 기록된 귀속의 미소비**로 적는 데 동의하고, "귀속 장치 전무"라는 어감은 쓰지 않는다(`by` 자율 스탬프는 실재).
2. **PARTIAL 대기 불일치** — gate_runner:118–121·residual_cmd:36은 미종결, `tick._pending_external`(:350)은 None만. GATING+PARTIAL이 파킹이 아닌 재게이트 지시로 간다. "항상 무한"이 아니라 **자동 재지시가 성립하는 정적 경로**로 한정(§C-5 참조).
3. **retraction raw scan** — `_external_verdict`와 tick의 직접 주사들이 `apply_retractions`를 안 탄다. Codex가 지적한 **반대 방향**(철회된 `cycle_started`가 raw scan에서는 여전히 외부 판정을 철회시킴)은 내가 놓친 축이고 타당하다. 즉 과다 인정과 과다 철회가 동시에 열려 있다.
4. **ERROR 이후 completed/순서** — 정상 ERROR 분기는 `gate_check(ERROR)+stage_finished(error)`이고 `gate_verdict`를 안 낸다 → `fold_latest_verdicts`가 과거 PASS를 유지 → `is_done`(tick:120)이 `err_stages`(tick:158)보다 앞선다. 정적 연결이며 **정상 writer ERROR 실행 재현의 대체 증거가 아니다.**
5. **metric/trigger의 exit 무시** — `_metric_threshold`(:199–208)·`_trigger_effect`(:229–238)가 종료 코드를 판정에 안 쓴다(`_db_query`:251·`_exit_code`는 씀). "모든 명령 검사가 같다"는 뜻이 아니라는 Codex 한정에 동의.
6. **cap 전 stale 지시** — tick:108–115가 :124–146보다 앞. 사실관계 합의, 결론은 §C-5로 좁힌다.
7. **testgen xfail·provenance** — `xfail(strict=False)`+`NotImplementedError`는 행동 oracle이 없고, "구현 전 그린 금지"가 프로세스 exit 0 차단으로 구현돼 있지 않다. `src=usecase_file.name`(basename)뿐이라 원천 revision 대조 불가.
8. **feedback/REJECT 예산 비대칭** — gate_runner:144(전체 계수) vs tick:216–223(REJECT 이후 계수). 재개 신호(`feedback_issued`→READY, derive_state:97–100)가 발행되지 않아 FAILED 고착 경로가 성립.
9. **Codex 단독 지적 중 내가 확인·채택하는 것**
 - `_gates` 최소 1 미강제: loader:333–334가 `gate:` 부재/빈 목록을 그대로 `[]`로 두고 검사하지 않음 → `_run_gates` 빈 루프가 PASS 분기에 도달. `stages` 0이면 `is_done`도 공허 참. (현행 정본이 빈 목록을 쓰는지는 미확인.)
 - `gate_waivers`: loader:458이 raw dict 그대로, 사유 비어있음·서명 미검사 → `gate_ratchet`(:43) 면제가 키 존재만으로 성립.
 - `gate_ratchet`은 **문장 삭제만** 본다 — 같은 문장으로 cmd/regex/threshold를 느슨하게 바꾸는 약화는 탐지 밖.
 - `preconditions`는 게이트 **실행 후** 계산(gate_runner:133) → 실행 전후 동일성의 증거가 아니다. 내 초기 보고보다 정확하다.
 - `tick:121`의 완료 detail("전 단계 gate_verdict PASS")이 SKIPPED 포함을 말하지 않는다.
 - loader:466의 `sha`(파이프라인 파일 해시)는 모델에 있으나 **어떤 gate_check/gate_verdict payload에도 안 실린다** — Codex가 요구한 "gate 정의 해시" 좌표가 있는데 안 쓰이는 형태.

---

## B. 템플릿 → lint → 생성기 3자 불일치 (신규 합의, 원문 대조 완료)

- `templates/_common/usecase.template.md:18`: `- Given <전제> / When <행위> / Then <결과>` — **한 줄, 슬래시 구분**.
- `usecase_lint.lint`(:50–56): UC 본문에 `"Given"/"When"/"Then"` **문자열 존재**와 `"실패"` 존재만 본다. 배치·개행·AC 연결을 안 본다.
- `testgen._GWT_RE`(:17–19): Given→When, When→Then 사이에 **실제 `\n`을 요구**한다.

정적 귀결: 템플릿을 그대로 따른 usecase는 lint PASS이면서 `testgen.extract`가 0건 → `generate()`가 `""` → `testgen_cmd`가 rc 1로 "GWT 0건, usecase를 먼저 채워라"를 낸다. **정본 템플릿을 지킨 사용자가 생성기에게 거부당한다.** `test_engine_smoke.py:190`의 lint 합격 예시(`- Given a / When b / Then c`)도 같은 한 줄 형식이라 이 경계 위에 있다. lint의 AC 전역 고유는 `seen[ac] != uc`(:47)이므로 같은 UC 안 재등장은 허용되고, testgen은 단락 첫 AC(`acs[0]`, :50)에만 묶으므로 중복이 조용히 병합된다. 세 곳이 **같은 문법 oracle을 공유하지 않는다**는 Codex 결론에 동의한다(정적 비교이며 테스트 실행 결과 아님).

---

## C. 내 초기 보고의 정정·한정

1. **HTTP(요청 1 수용).** "DNS/접속 실패는 반드시 ERROR여야 한다"는 주장을 철회한다. SUT 가용성 자체가 요구라면 접속 불능=FAIL이 타당한 계약이고, 이는 설계 선택이지 입증된 결함이 아니다. 남는 것은 두 개의 좁은 경계뿐: ① **`expect_status`가 2xx가 아닌 게이트는 PASS가 구조적으로 불가능하다** — `urlopen`은 4xx/5xx에 `HTTPError`를 올리고 `_http_probe`(:153–156)가 상태 비교 **이전에** except로 잡아 FAIL을 낸다(기대 404 게이트의 정적 반례). ② 환경측(프록시/DNS/TLS) 실패와 제품측 거부가 **같은 FAIL 값**으로 접혀 `repair_tier`(문턱 2회) 승급 입력에 동일하게 들어간다 — evidence의 예외 타입명은 사람이 읽을 수 있으나 기계 축은 없다.
2. **Windows/WSL(요청 2 수용).** "정확히 127"과 그로부터의 결론을 철회한다. 실제 셸(cmd/PowerShell/bash), WSL interop, `runtime.yaml` 값에 따라 결과가 달라지며 **실행 0건**이다. 유지되는 것은 이식성 위험뿐: `_exit_code`가 `shell=True`(:45)로 셸을 특정하지 않고, `_pinned_cmd`가 머신 로컬 절대경로(paths.py:62–80)를 문자열 치환하며, 실패 시 그 결과가 ERROR가 아닌 **FAIL 계열로 원장에 앉을 수 있다**는 것. `root.glob`의 대소문자 민감도 차이도 같은 등급의 위험으로 낮춘다(미실행).
 **probe 문구**: "아무 데도 주입되지 않는다"를 측정 범위로 한정한다 — pinned `scripts/` 전역 grep 기준 호출부는 `tick.py:287`과 `step_cmd.py:97` 둘이고 **둘 다 3인자(probe 없음)**다. 트리 밖 소비자나 향후 배선은 이 범위에서 판단하지 않는다.
3. **smoke 표현(요청 3 수용).** "boolean fixture가 아니라 실측"이라는 표현을 철회한다. `test_engine_smoke.py`는 실제 함수·실제 원장 파일을 쓰는 **임시 fixture 코드**이고, 이번에 **실행하지 않았다** — 내가 읽은 것은 단언의 형태뿐이다. 인수 검증도, PASS 증거도 아니다. 마찬가지로 `checks`가 `subprocess`를 직접 친다는 사실은 **무모킹 인수를 보증하지 않는다**: `cmd`가 `echo`·테스트 스텁·항상 0을 내는 래퍼여도 같은 코드 경로다. 무모킹 여부는 checks가 아니라 파이프라인 인스턴스의 cmd 내용이 결정한다.
4. **RUNNING/GATING(요청 4 수용).** `select_ready`는 이벤트를 읽는 **관측 선택기**이고 원자적 claim/lease가 아니다. ":55–57이 재중복 디스패치를 막는다"를 방어 항목에서 내린다. 남는 것은 §2에 적은 race 자체(`_run_gates`가 :91 스냅샷으로 `retries`를 세므로 병렬 게이트 실행이 `feedback_issued`를 중복 발행할 수 있다)뿐이며, 이 역시 정적 추론이다.
5. **staleness(요청 5 수용, reenforce 전문 대조).** "iter·TTL·위임 예산을 전부 우회하는 무한 루프"를 **"tick 내부 3캡을 우회하고 외곽 프록시 캡에만 의존하는 경로"**로 낮춘다. `reenforce.handle`이 실제로 거는 외곽 제한: `active_run.json` 바인딩+cwd 일치(:39–46), 무인 장전은 드라이버 스폰 세션만(:53–54), `TICK_TIMEOUT_S=25`(:26), 그리고 `continue`에만 적용되는 **트랜스크립트 바이트 프록시 캡**(:97–108, 기본 8,000,000B)이 초과 시 non-block으로 루프를 세운다. 그 위에 드라이버 일일 스폰 캡이 더 있다(이번 범위 밖).
 **순서 변경만으로 해결되는가 — 아니다.** ① `iter_n`은 `stage_started`만 세는데(tick:82) stale 재게이트 지시는 새 `stage_started`를 만들지 않으므로 iter 캡은 순서를 바꿔도 안 걸린다. ② wallclock TTL의 `t0`는 최근 `l2-spawn` 앵커(:72–79)라 **새 세션마다 리셋**된다 — 창 단위 halt는 나되 드라이버가 재개하면 같은 지시가 다시 선다. ③ 더 정확한 반례는 stale과 ERROR의 합성이다: 완료 단계의 재게이트가 판정기 ERROR를 내면 `gate_verdict`가 안 나와 지문이 갱신되지 않고(그래서 stale 유지) 동시에 `last_status=error`인데, stale 분기(:108)가 `err_stages`(:158)보다 앞서므로 **operator_blocker halt에 영원히 도달하지 못한다.** 따라서 필요한 것은 순서 교정 + 재검증 시도를 원장에 남기는 어휘(reducer가 세는 축)이고, 소비자도 함께 바뀌어야 한다(`derive_stage_states`는 stale을 모르고, `staleness.scan`은 `completed`만 훑으며, reenforce는 outcome 3값만 본다). 순서만 바꾸면 halt 사유가 `wall_clock`으로 바뀌어 **원인이 stale이라는 사실이 오히려 가려진다.**
6. **testgen 구문 파손(요청 6 수용).** "특수 문자면 깨진다"를 철회하고 조건을 명시한다: 파손이 성립하려면 `given/when/then`의 **앞 120자 슬라이스 안에** docstring을 조기 종료시키는 시퀀스(`"""`, 또는 절단으로 생긴 `"`가 닫는 `"""`에 인접해 `""""`가 되는 경우)가 들어가야 한다. 백슬래시는 대개 경고(invalid escape)이지 SyntaxError가 아니다. 캡처가 `[^\n]+`이고 이스케이프가 전혀 없다는 것(:32–39, :68–69)이 정적 근거이며 **재현은 미실행**이다.
 **`strict=True`만으로는 부족하다**는 지적도 수용한다: 본문이 `raise NotImplementedError`인 한 결과는 XFAIL이고 strict는 XPASS만 실패로 바꾼다. 즉 strict는 "채우고 마커를 안 지운 경우"만 잡고, **스켈레톤 상태의 exit 0**은 그대로 남는다. 이를 닫으려면 비-xfail 수용 테스트 수를 AC 수와 대조하는 별도 게이트가 필요하고, 그런 소비자는 읽은 범위에 없다(`lib/suite_floor.py`·`lib/test_outcome.py`는 존재하나 이 경로에서 참조 확인 못 함 — 미검증).
7. **컴팩션(요청 7 수용, ledger 재확인).** "render 게이트가 pending으로 되돌아간다"는 전역 주장을 철회한다. `compact`(ledger:349–414)는 `head=events[:-keep_tail]`만 접고, `latest_verdicts` 시드(:378,:390)가 `derive_completed`를 보존하므로 **이미 completed인 단계는 자동으로 pending이 되지 않는다.** 정확한 사실관계는: `gate_check`은 `PRESERVED_EVENTS`(:132–145) 밖이고 `_is_audit`(:152–156)은 `actor=="operator"`만 살린다 → `actor:"judge"`인 render 판정(step_cmd:494)은 접힌 head 구간에서 사라진다. 손실은 **잠재적**이고, `staleness` 재검증·`cycle_started.redo`·수동 재게이트로 **게이트를 다시 돌릴 때만** 표면화한다(그때 `_external_verdict`가 빈손 → PENDING_HUMAN). 그리고 등가 게이트(:401–405)가 대조하는 4개 도출 중 외부 판정을 보는 것이 없어 이 손실이 fail-closed 검사를 통과한다는 점은 유지한다.

**추가 자기 정정**: 초기 보고에서 `pl["caps"]` KeyError 가능성을 보류 항목으로 남겼는데, loader:455가 `raw.get("caps") or {}`로 기본값을 준다. 위험 없음 — 철회한다.

---

## D. 이견·보완 (Codex 대비)

- **C03의 "선언 precondition의 변경 등 앞선 분기가 있으면 결과가 달라질 수 있다"** — 달라지는 방향이 완화가 아니다. stale 분기가 앞서면 outcome은 `done`이 아니라 `continue`가 되지만, §C-5 ③에서 보였듯 그 경우 **operator_blocker halt는 여전히 도달 불가**다. 즉 앞선 분기는 ERROR 은폐를 고치는 게 아니라 은폐 형태를 바꾼다.
- **C04의 "빈 gate 목록이 PASS 분기에 도달"** — 여기에 하나 덧붙인다. 그 PASS는 `evidence_refs=[]`인 `gate_verdict PASS`로 원장에 앉고, `derive_completed`가 이를 다른 PASS와 구분하지 않는다. 즉 **증거 0건 완료와 증거 다수 완료가 같은 값**이며, `derive_state`가 acceptance coverage에서 지킨 "0/0을 1.0으로 접지 않는다"는 규율이 게이트 판정 축에는 적용돼 있지 않다.
- **C01의 "actor/by/산출물/정의 해시를 대조하지 않는다"** — 지지하며 근거를 하나 보탠다. loader가 `sha`(정의 해시)를 이미 만들지만(:466) gate_runner의 두 append(:104,:138,:172)에 실리지 않는다. **좌표가 없어서가 아니라 안 실어서** 비어 있는 자리다.
- Codex가 Zeus 현 상태를 "잘못된 upstream PASS를 흡수한 운영 상태가 아니라 구현 전 준비 상태"로 구분한 것에 동의한다. 계속 blocked를 반환하는 것은 목표 달성이 아니라는 결론도 같다.

---

## E. 미검증 (양측 공통으로 남음)

원본 실행 0 — 차단 이력의 **정상 gate-writer ERROR probe**, 게이트/CLI/외부 서비스 실행, 컴팩션·retraction·동시성의 실제 재현, Win/Linux/WSL 실제 설치 및 실행, 기대-404 probe의 런타임 확인, testgen 파손 입력의 실제 수집 실패, `suite_floor`/`test_outcome`이 게이트 경로에 연결돼 있는지, 현행 정본 파이프라인이 빈 `gate:`나 `forbid+expect` 조합을 실제로 쓰는지, `projection_pg`의 PG SSOT 배선, device·결제 인수, 전체 소스 검토.

**이 문서는 문제 목록의 정적 합의일 뿐이며, Zeus의 수정 완료·실행 재현·채택 승인 어느 것도 표시하지 않는다.**