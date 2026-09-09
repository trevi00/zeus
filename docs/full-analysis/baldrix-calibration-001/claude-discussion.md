## 0. 이 턴에서 새로 읽은 범위 · 초기 보고 취급

읽음(전문): `codex-initial.md`, `observations.md`, `components.stdout.txt`, `threshold-unit.stdout.txt`, `components.receipt.json`, `threshold-unit.receipt.json`.
추가로 정정 검증을 위해 새로 읽은 소스 범위: **`lib/skill_token_budget.py` 60-195 전문**(`fit_top_skill`, `_fill_remaining`, `apply_token_budget` 본문), **`lib/breakers/composite.py` 125-159**(`_key_filename`, `_default_record`, `_trim_history`).

제 첫 보고서는 **역사적 증거로 그대로 보존**하며 재작성하지 않습니다. 아래는 그 위에 얹는 정정·합의·이견 기록입니다. 여전히 실행/import/쓰기/네트워크/자격증명 없이 정적 독해만 했고, root의 receipt는 제가 재현하지 않은 **타인의 관측**으로 인용합니다.

---

## 1. 지적된 10건에 대한 명시적 응답

**(1) 라인 수 — 정정 수용.** 제가 쓴 "47/296/252/101/195/162"는 Read 도구의 마지막 줄 번호(=trailing newline 이후 카운트)를 그대로 옮긴 것으로, `splitlines` 기준 47/295/251/100/194/161이 맞습니다. 제 수치는 `__init__`을 제외하고 모두 +1이었습니다. 바이트 수 43,851과 scope SHA-256은 **제가 검증하지 않은 채 인용만** 했고, raw Git blob 대조는 root 소관으로 둡니다.

**(2) `apply_token_budget` — 정정 수용, 주장 철회.** 저는 `skill_token_budget.py` 1-60만 읽고 그 파일의 docstring 8-9행("First (highest-scored) skill always keeps full content")과 `skill_match.py:420-422`의 주석을 근거로 "1위 본문이 예산을 우회한다"고 썼습니다. 본문(144-195)을 실제로 읽으니 `apply_token_budget`은 `fit_top_skill(top_content, max_chars)`(165행)을 호출해 1위 본문도 예산 안으로 넣고 `remaining_budget = max_chars - len(fitted)`(168행)을 씁니다. **우회는 더 이상 없습니다.** 그 파일 상단 docstring과 skill_match의 해당 주석이 stale입니다(그 자체가 별도 결함).
→ 결과적으로 guard(`total > 4000`)와 실제 절단 사건의 괴리는 제가 쓴 것보다 **작습니다**. 남는 차이는 (a) `skill_match.py:426-435`의 `PER_BODY_CAP=3000` 절단이 총합 4000 이하에서도 `was_truncated`를 세우는 점, (b) 절 사다리/`_fill_remaining` 효과를 시뮬레이터가 모델링하지 않는 점입니다. 이건 "guard가 틀렸다"가 아니라 "guard는 절단 발생 여부의 근사이며 등가성이 미입증"으로 낮춥니다.
반대로 **base_score vs 기록된 boosted score 불일치(`skill_match.py:411` vs `449-451`)와 `matched_skills[:5]` 절단은 유지**합니다. 다만 등급을 정확히 하면: 이 둘은 **조건부로 eligible 항목이 코퍼스에서 누락될 수 있다**는 구조적 결함이고, 런타임에서 실제 오분류가 몇 건 일어났는지는 **측정된 바 없습니다**. 제가 "최대 +3만큼 어긋난 규칙을 튜닝한다"고 단정한 부분은 "기록 필드와 판정 필드가 다르며 그 차이는 최대 +3"으로 정정합니다.

**(3) `module`/`constant` — 정정 수용.** 두 필드는 `qualified()`(registry 45-46)를 통해 `assert_locked_disjoint()`(140행)와 `apply_threshold_override`의 적용 시점 LOCKED 재확인(threshold_policy 137-138)에서 **실제로 소비**됩니다. "어디에서도 읽히지 않는 문서 필드"는 틀렸고, 그 범위를 **`process_lifetime`(어떤 실행 경로도 읽지 않음)과 `target_metric`/`guard_metric`(rationale 문자열 출력 전용, threshold_proposer 175행)** 으로 좁힙니다.
FP_THIN_RATE 별칭 건도 낮춥니다: 이름 문자열 식별의 약점은 사실이지만, **현재 잠긴 상수가 변경되었다는 증거가 아니며**, 실제 안전성은 (a) 호출부가 `resolve_threshold`로 배선되었는지, (b) REGISTRY 멤버십 검사에 함께 걸립니다. 그 두 가드는 유효하며 유지 대상입니다.

**(4) BR4 산술 — 정정 수용.** `min(base*2, cap//2)`에서 `cap=3600`이면 `cap//2=1800`이므로 제안값이 현재 base보다 낮아지는 조건은 **base > 1800**입니다. 제가 쓴 "900 초과"는 오산입니다. 그리고 현재 소스는 `composite`의 기본 `BACKOFF_BASE_SEC=60`을 import하므로 이 시나리오는 **상수 변경 가정 하의 가설**로 라벨해야 하며, `breakers/config`의 configured override는 이 경로에서 애초에 **무시**되므로 override로는 도달하지 않습니다.

**(5) `trip_count == 0` — 정정 수용.** `composite.py:425`가 close 시 0으로 리셋하는 것은 사실이나, 0은 "현재 닫힘"의 증명이 아닙니다. 한 번도 트립하지 않은 경우, 그리고 임의 파일 입력의 경우 모두 0일 수 있습니다. "정상 전이/리셋" 전제로 범위를 좁힙니다.
BR3 도달 불가 주장도 **조건부**로 정정합니다: `history_len >= min_history*2`가 불가능한 것은 (기본 `trip_window=10` 보존 + 기본 `min_history=10`) 조합에서만이며, 호출자가 `min_history`를 낮춰 부르거나, `trip_window`가 상향되었거나, `analyze_breaker`가 트리밍하지 않는 **임의 파일 입력**이면 도달합니다. "무조건 죽은 분기"가 아니라 "기본 보존 정책 하에서 도달 불가"입니다.

**(6) holdout이 선택에 참여 — 지적 수용, 초기 보고에 없던 항목 추가.** `threshold_proposer.py:163`이 `gate.target_delta_holdout`을 튜플에 담고 168행이 그 값으로 정렬해 최종 후보를 고릅니다. 즉 **holdout은 "proposer가 본 적 없는 창"이 아니라 선택 통계량의 입력**입니다(현재 이 항목의 후보가 최대 2개라 선택압은 작지만, 계약은 이미 깨져 있습니다). docstring의 "NEVER sees the held-out later window"는 게이트 통과 여부에 대해서만 참입니다.
동시에 제 §2 표현도 낮춥니다: 유한 표본의 지표 차이가 양수라는 것은 **정상성(stationarity)조차 입증하지 않습니다**. 유용성·실제 인간 성공은 더더욱 아닙니다. 그리고 "라벨이 어디에도 없다"는 과대 진술이므로, **"이 metric/guard 두 함수와 proposer가 소비하는 ledger 필드는 어떤 관련성/인간 결과 라벨도 사용하지 않는다"** 로 한정합니다(저장소 전역 주장 철회 — 미열람 범위 다수).

**(7) 토큰/flag — 지적 수용, 표현 정정.** 제 §4 제목 "인증된 수락이 실제로는 인증되지 않음"은 부정확합니다. 정확히는 **애초에 인증이 아니었습니다**: 토큰은 방향 라벨 문자열이지 신원/승인 receipt가 아닙니다. 또한 정적 취약점은 **현재 라이브 설정이 무단 변경되었다는 증거가 아닙니다**. flag 소비는 `try/except OSError: pass`(threshold_policy 166-170)라 **시도될 뿐 트랜잭션적 exactly-once가 아니며**, 쓰기→삭제→이력 순서라 삭제/이력 실패가 성공 보고와 공존합니다. LOCKED 재확인, REGISTRY 멤버십, no-op 단축, 토큰 문자열 비교는 서로 **다른 성질의 검사**이며 뭉뚱그리지 않겠습니다(no-op이 토큰 없이 False를 반환하는 것 자체는 정책 변경이 아니므로 우회가 아닙니다).

**(8) fail-soft — 지적 수용.** 제 "보존 가드 #6"(malformed 라인 무시)은 지나치게 넓었습니다. 실제로 남는 구멍: 비객체 레코드(`[]`)는 소비자의 `.get` 호출에서 **AttributeError**(root 관측 확인), 잘못된 UTF-8은 `UnicodeDecodeError`가 `OSError` catch 밖(proposer 168-183, operator_ledger 290-301), JSON `Infinity`→`int(inf)`는 OverflowError, `cool_off_until - opened_at`은 타입 미검증. **기본값 폴백은 사용자 결과가 안전하다는 증명이 아닙니다.** "관측 없음"과 "레코드가 깨졌음"은 서로 다른 분모를 받아야 한다는 점도 동의합니다.

**(9) R2 조기 continue — 지적 수용, 제가 놓친 항목.** `proposer.py:238`의 `continue` 때문에, `DEFAULT_INVOKE`에 없는 invoke 에이전트가 전체 failure_rate는 낮지만 실패의 대부분이 fabrication인 경우 **R4 경고가 억제되고 skip 제안만 남습니다.** 제가 "R4가 R2/R3 미발동 시에만 평가된다"고 관찰만 하고 이 결과를 도출하지 못했습니다.
중복 mode가 fab 분수를 부풀리는 건 제 §5와 일치하며 root 관측(`duplicate_modes: failures 1, evidence_fabrication 3` → 분수 3.0)이 이를 실측했습니다. 명시적 `agent_types` 인자는 정렬/중복 제거를 거치지 않으므로(정렬은 206-212의 자동 검출 분기에만 존재) docstring의 "알파벳 순 정렬" 결정성 주장은 인자 경로에서 성립하지 않습니다 — 수용.
producer 진실성(critic_verdict가 항상 None 등)에 대한 제 §5 결론도 **훅 한 곳(`agent_outcome_audit.py:400-471`) 표본 하나**에 근거하므로 "완전한 producer 폐쇄 확인"이 아님을 명시합니다.

**(10) 추가 지적 수용.** ① `propose_threshold_changes(telemetry_root=...)`는 시그니처(98행)에만 있고 실제 읽기 경로(122-123행)는 이를 무시합니다 — 제가 놓쳤습니다. ② `cur_target = float(metric_fn(trailing, current))`(137행)은 후보 루프의 `try`(151-154) **밖**이라 현재값 계산 예외는 전파됩니다. ③ score가 NaN이면 `>=` 비교가 모두 False가 되어 조용히 제외되고(유한성 미검증), `body_chars=True`는 `isinstance(_, int)`가 참이라 1자로 계산되며, 부분 결측 코퍼스의 guard 분모에 최소 표본 요건이 없습니다. ④ registry에는 값 도메인/step 부호·유한성/교차 필드 관계 검증이 전혀 없습니다(frozen dataclass와 `Literal`은 런타임 검증이 아님). ⑤ 유지할 가드로 **min_sample 검사와 게이트의 non-finite 거부**를 계속 명시합니다.

---

## 2. 합의 (독립 도달, 표현 차이만 있음)

- `entry.default` 고정 기준선 → 유효 override 무시, 방향 판정도 default 대비. **root 실행이 이를 실측**했습니다: `effective_after_different_value: 999`인데 `proposal_after_override: current 3.0 / suggested 4.0`. 제 §3이 정적 추론이었던 것이 이제 관측으로 뒷받침됩니다.
- ready-flag가 값을 구속하지 않음 → `apply_different_value: true`(suggested 4 flag로 999 적용), `apply_with_corrupt_flag: true`(1000), `apply_nan_with_empty_flag: true` + `effective_is_nan: true`. 제 §4-1/§4-2가 실측으로 확인되었고, **빈 파일도 존재 검사를 통과**한다는 점은 제 정적 분석보다 강한 결과입니다.
- `full_body_admit_precision`의 공허 케이스 1.0 → 모든 점수 위로 올리면 "완벽"해 보임. `zero_admissions_metric: 1.0`, `zero_admissions_gate: accept true`. 다만 **이는 게이트 직접 호출**이고 단일-step proposer가 999를 제안한다는 뜻이 아닙니다 — 제 §2의 실제 주장은 "전부 score 3인 코퍼스에서 3→4가 한 스텝으로 승인된다"였고, 그 형태가 도달 가능한 버전입니다. 두 진술을 분리해 유지합니다.
- 미분류 결과가 분모만 채움 → `unknown_outcomes: sample 10 / success 0 / failure 0 / success_rate 1.0`. 제 §5와 일치. 다만 근원 지목은 제가 `operator_ledger.apply_override`(human_override 레코드, `_coerce_record` 기본 `success=False, failure_modes=[]`)로 좁혔고, root는 일반 미분류로 넓게 잡았습니다. 둘 다 유효하며 root의 합성 주입은 메커니즘 확인이지 실제 발생 빈도의 증거는 아닙니다.
- BR2가 100% 실패 창에서도 "임계 상향"을 권고 → `all_failures_proposal: failure_rate 1.0 → suggested 4`. 제 §6의 "정답 없는 관대 방향 이동" 주장의 가장 날카로운 사례이며, root의 표현이 제 것보다 정확합니다.
- 유지할 가드: 제안/승인 분리, min_sample, 게이트의 fail-closed(코퍼스·replay·non-finite), 런타임 locked-disjoint(ValueError, `-O`에서도 생존), 적용 시점 LOCKED 재확인, 멤버십 필터. 양측 동일.

## 3. root가 잡고 제가 놓친 것 (수용, 초기 보고 결손)

1. holdout이 최종 후보 **선택**에 참여(§1-6).
2. `telemetry_root` 미사용, `cur_target` 예외 미포착.
3. R2 조기 continue의 R4 억제, 명시적 `agent_types` 정렬/중복 미정규화.
4. `analyze_breaker`가 malformed JSON에서 None이 아니라 **zero-history CLOSED 통계**를 반환(`read_json(path, default={})` → dict이므로 None 분기 미통과). docstring과 모순. 관측: `corrupt_breaker_stats: history_len 0, state closed`. 제가 `int()` 예외만 보고 이 경로를 놓쳤습니다.
5. BR2의 `continue`가 동일 breaker의 BR4 backoff 제안을 억제.
6. `_key_filename`이 `/`·`\`→`_` 치환으로 **비가역**이며(composite 130-134), `agent_type`에 `__`가 있으면 `split("__",1)`이 오분할. 저는 `('?','?')` 폴백만 언급했습니다. 이번에 소스로 확인해 수용합니다.
7. `BreakerStats`에 project 식별자·증거 경로가 없어 전체 프로젝트 스캔 시 동일 (agent, mode) 행이 구분 불가.
8. `success_rate = 1 - failure_rate`(89-90행)라 미분류가 성공률을 올림. 다만 이 프로퍼티는 R1-R4 어디에서도 쓰이지 않고 `calibration_review`도 출력하지 않으므로, 영향은 **공개 dataclass 표면의 오도**에 한정된다는 점을 덧붙입니다.
9. UnicodeDecodeError가 `OSError` 밖.

## 4. 제가 유지하는 것 중 root가 다루지 않았거나 약하게 다룬 것

- **패키지 docstring 대 실제 범위**: `__init__.py:16`은 "breaker calibration은 다음 cycle"이라 하면서 25-36행에서 breaker proposer를 export합니다(root도 지적). 여기에 더해 **`breaker_proposer.py:37-40`이 "적용 = composite.py 코드 편집 = invariant 영역"이라고 단언하지만, 실제로는 `lib/breakers/config.py`(v15.16)의 토큰 게이트 yaml override 경로가 존재하고 `calibration_review._breaker_apply_command`(129-143)가 그 CLI를 출력**합니다. 제안 본문과 적용 메커니즘 서술의 정면 충돌은 제 고유 발견으로 유지합니다.
- **`cli/calibration_review`가 "dry-run only"를 표방하면서 ready-flag를 씁니다**(258-261 → `_emit_ready_flag`). 위험 방향 2요소 중 하나가 "리뷰 명령 1회 실행"으로 충족됩니다. 단, §1-7에 따라 이는 **정적 구조 관찰**이며 현재 라이브 무단 변경의 증거가 아닙니다.
- **`composite.py`가 `th.*`(유효 설정)로 판정하는데 breaker_proposer는 모듈 상수를 current_value로 보고**하는 불일치(threshold 쪽 default 고정과 동형).
- **비원자적 read-modify-write**: `threshold_policy.py:162-163`, `breakers/config.py:151-153` 모두 평범한 `write_text`. 저장소에 `atomic_json`이 있는데 미사용. 잘린 yaml은 `_safe_yaml_load`가 **에러 없이 부분 파싱**하므로 override가 조용히 사라집니다. root도 "fencing 없음"을 언급했으나 부분 파싱으로 인한 무음 롤백은 제 쪽이 구체적입니다. 다만 **동시 프로세스 실측은 양쪽 모두 없습니다**(receipt의 limits가 명시).
- **텔레메트리 회전**: `log_telemetry`가 `.1`로 회전하는데 `telemetry_read.iter_events`(22행)는 base 파일만 읽어 코퍼스가 소리 없이 잘립니다.
- **`threshold_metrics`의 예산 상수 출처 주석 오류**(`skill_match.py:48/54`를 미러라고 적었으나 실제 소유자는 `skill_token_budget.py:31/39`), 동기화 강제 검사 없음. §1-2 정정 이후에도 이 항목은 유지됩니다.

## 5. 실행 receipt가 입증한 것 / 입증하지 않은 것

두 receipt 모두 `returncode 0`, 네트워크 none, read-only 바인드, `--user 65534`, `source_bytes_unchanged: true`, `source_files 1648`, 동일 tree hash. 따라서 **관측이 소스를 변경하지 않았다**는 점은 receipt로 뒷받침됩니다(제가 재현하지는 않았습니다).

입증되지 **않은** 것(양측 동의): 인간 승인, 모델 품질/관련성, 실제 사건 분포, 프로세스 동시성, 네이티브 Windows/WSL 수용, 라이선스, 채택/파일럿 준비도, 전체 caller/test 폐쇄. 원본 유닛 16 PASS는 **mocked registry/path + 합성 텔레메트리** 위의 결과이므로 "현재 동작이 올바르다"의 증거가 아니라 "그 계약들이 그 조건에서 유지된다"의 증거입니다. 특히 `test_policy_resolve_default_and_token_apply`는 정확히 suggested 값만 적용해 보므로, root의 component 프로그램이 보여준 **값 미구속/손상 flag/빈 flag/NaN** 은 유닛 스위트가 전혀 덮지 않는 영역입니다.

`components.stdout.txt`의 `scalar_record_exception` 키가 부정확하다는 점(주입값은 스칼라가 아니라 비객체 배열 `[]`)은 `observations.md` 28-29행에 이미 문서화되어 있으므로, 저는 이를 **명명 오류이나 자기 정정된 상태**로 기록합니다.

## 6. 남은 공백 (이번 턴 이후에도 미열람)

`critic_policy.py`, `graduation.py`(토큰 상수 정의), `atomic_json` 구현, `paths.py`(STATE_DIR/TELEMETRY_DIR/회전 임계 실제 값), `composite.py` 전문(현재까지 grep + 125-159만), `tests/test_calibration_proposer.py`·`test_breaker_proposer.py` 본문, `cli/breaker_override.py`, `critic_policy_override` CLI 존재 여부, `_resolve_failure_mode`/`_resolve_verified_by` 본문, run_all/run_units 전체 결과. root 쪽은 `component_observations.py`/`run_observations.py` 프로그램 본문을 제가 읽지 않았으므로, 관측 수치는 **stdout과 observations.md의 자기 기술에 의존**합니다(프로그램 로직 독립 검증 안 함).

## 7. Zeus 적응 제안 (Zeus 구현 미검토 — 등가성 주장 아님)

1. **기준선은 유효 설정**: 제안·표시·권한 판정 모두 effective 값에서 출발하고, in-code default는 검증 대상이지 기준선이 아니어야 합니다(§1-3/§2의 실측된 3 vs 999 괴리).
2. **승인 아티팩트는 값을 구속**: 이름+정확한 값+코퍼스 다이제스트+홀드아웃 다이제스트+만료+발급자. 존재 검사만으로는 빈 파일도 통과합니다(실측).
3. **exactly-once 소비**: 쓰기 전 소비, 실패 시 롤백, 소비 실패를 성공으로 보고하지 않기. 현재는 best-effort unlink입니다.
4. **제안 생성과 승인 아티팩트 발행을 같은 명령에 두지 않기.**
5. **선택과 검증의 분리**: 후보 선택은 trailing에서만, 최종 평가 집합은 선택에 일절 관여시키지 않기(§1-6).
6. **지표는 인간/러너 결과에 접지**: Astra/Sol/Terra 자격 판정, 실행 receipt, 인간 SDD 승인 같은 외생 신호를 목표로 쓰고, 점수 분포 통계는 게이트 자격이 될 수 없습니다. 비용 최적화가 조작 가능한 분모나 자기충족 지표로 승격되지 않게 할 것.
7. **분모 위생**: 시도(attempt) 단위 dedup, 미분류/파싱실패/무관측을 각각 별도 카운터로, 명시적 시간창, 감사·override 레코드를 결과 분모에서 배제.
8. **값 도메인 검증**: 유한성·형(정수/실수)·범위·step 부호를 registry 스키마에 두고 적용 시점에 강제. NaN/Inf가 정책 파일까지 도달한 것은 실측된 결과입니다.
9. **PG 트랜잭션 + Git 정책 신원**: 설정 갱신을 원자적 커밋으로, 부분 파싱이 무음 default 복귀가 되지 않게 버전/체크섬 필수.
10. **fail-soft를 fail-silent와 구분**: 폴백 발생 자체를 관측 가능한 사건으로 기록.

전면 폐쇄, 라이선스, 네이티브 OS, 모델·인간 수용, 채택 준비도는 **여전히 false**이며, 이 문서는 비교/논의 기록일 뿐 채택 권고가 아닙니다.