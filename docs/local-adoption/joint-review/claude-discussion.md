## 합의 사항

C1·C2·C3 모두 수용한다. 특히 **C1은 내 finding 2보다 정확한 진단**이다. 나는 "verified 릴리스가 큐에서 정체"까지만 봤는데, Codex가 짚은 `deployment.py:130-134` + `git.py:140` 조합이 더 위험하다: 로컬 merge가 성공한 뒤 promote 커밋 전에 죽으면 HEAD가 `candidate.revision`이 되므로 재시도 시 `current_main != candidate["base"]`가 참이 되어 **이미 병합된 후보에 대해 rebase 작업을 발주**한다. 승인 절차가 리셋되고 워커 사이클이 낭비된다. 따라서 내 finding 2의 "재큐잉" 수정을 **B의 intent 저널 없이 먼저 넣으면 오히려 해롭다**(재시도할수록 허위 rebase가 늘어난다). 이 결합은 아래 우선순위에 반영했다.

수용하는 반론들: (a) `_check`의 예외 붕괴는 fail-fast 이전부터 존재했으므로 "신규 회귀"가 아니라 "기존 혼동이 더 눈에 띄게 드러난 것"으로 라벨을 정정한다 — 심각도는 유지한다. (b) lease를 잃은 워커가 권위 있는 진단을 쓰면 안 된다는 지적이 옳다. 내 제안을 "실패+진단을 같은 트랜잭션에"에서 **"펜싱된 실패 커밋이 성립할 때만 진단도 함께 커밋, 성립하지 않으면 둘 다 쓰지 않음"**으로 좁힌다. (c) 5·7은 가설로 유지하고, conductor 기동 대신 무해한 Docker fixture로 검증한다. **불변 image ID를 증거 없이 가변 태그로 교체하지 않는다**에 동의한다. (d) 6은 전역 control-plane lock을 임의로 약화하는 게 아니라 canary 전용 DB 설계 항목으로 내린다. (e) decision 슬롯 예약은 별도 스코프로 분리한다.

## 추가 증거 (C3 보강, 이번 라운드 신규)

`deployment.py:201-203`은 두 inspect의 **returncode를 검사하지 않는다.** Docker 데몬이 일시적으로 응답하지 않거나 desired 이미지가 prune되면 `inspection.stdout`과 `actual.stdout`이 **둘 다 빈 문자열**이 되어 `"" != ""`가 거짓 → `continue`가 아니라 매칭으로 판정하고 곧장 `docker exec ... codex --version`을 실행한다. 그 exec가 실패하면 **잘못된 컨테이너를 근거로 롤백**된다. 즉 C3의 "drift를 healthy로 보고"와 정반대 방향의 오탐도 같은 코드에서 나온다. C 계약에 "inspect returncode != 0 → 매칭 판정 자체를 금지하고 unknown"을 반드시 포함해야 한다.

## A/B/C 최소 계약과 테스트

**A. 실패·진단 원자성 + stale 우아한 처리**
- 계약 A1: 진단 enqueue는 `_owned` 펜싱을 통과한 실패 커밋과 동일 트랜잭션. 펜싱 실패 시 실패 기록도 진단도 쓰지 않는다.
- A2: stale 판정 시 `execute_one`은 예외를 `serve()`로 전파하지 않고 비권위적 마커(`{"status":"stale"}`)를 반환한다. `decide_one:524`의 bare `raise`도 같은 계약으로 통일.
- A3: `observation_id = digest(task, attempt)` 멱등성 유지 — 재전달이 표본을 늘리지 않는다(INV-SKILL-HISTORY-001과 동형).
- 테스트: ① lease 탈취(generation+1) 후 실패 → 예외 없음, `tasks` 행이 새 소유자 상태 그대로 보존, `decisions_pending`에 진단 없음. ② 정상 lease 실패 → 실패와 진단이 같은 커밋. ③ `test_decision_atomicity.py`의 커밋 실패 주입 재사용 → 둘 다 부재. ④ 동일 attempt 재실행 → 관측치 1개.

**B. 승격 intent 저널 + 경계된 큐 재시도**
- B1: 되돌릴 수 없는 연산(publish/merge) **직전에** durable intent 기록: `{release_id, revision, tree, base, expected_active}`.
- B2: 복구 판정은 Git 사실만으로. `HEAD == revision && tree 일치` → merge 완료로 확정, **rebase 요청 금지**, `expected_active` 그대로 promote 재개. `HEAD == base` → 미수행, 재시도 가능. 그 외 revision → **unknown → blocked**(이벤트 기록, 자동 진행 금지). rebase는 base 이동이 증명된 경우에만.
- B3: remote 경로는 `gh pr` 상태로 증명 가능할 때만 진행하고, 아니면 `blocked_remote`. 로컬 저널이 GitHub CAS를 해결한다고 기록·보고하지 않는다(동의).
- B4: 큐 재시도는 `attempt/retry_at/backoff/lease`, max 초과 시 사유와 함께 terminal. **계약상 rejected와 인프라 오류를 분리하고 rejected checks는 보존, 재시도 금지.**
- 테스트: ① merge 성공 후 promote가 ConnectionError → 재실행 시 rebase 요청 0회, promote 완료, `deployment.active` 정상. ② merge 전 크래시 → merge 정확히 1회. ③ HEAD가 제3 revision → blocked, publish/merge 미호출. ④ 인프라 오류 2회 후 성공 → attempts 기록 후 승격. ⑤ rejected → 재시도 0회, checks 원형 보존.

**C. 관측 오류 분리 + 연속 실패 + drift degraded**
- C1: `_check` 결과에 `candidate_failure` / `observation_error`(TimeoutExpired·OSError·데몬 부재) 구분. `observation_error`는 `releases.verify`를 호출하지 않는다.
- C2: 실제 실패(프로세스가 실행되어 exit != 0)만 durable 연속 카운터를 증가시키고, N회 연속에서만 rollback. `observation_error`는 unknown — 카운터도 증가시키지 않고 healthy도 주장하지 않는다.
- C3: inspect returncode != 0이면 매칭 판정 금지 → degraded. 매칭 컨테이너 0개도 healthy가 아니라 degraded(image drift). 어휘: healthy / degraded / unhealthy / rolled_back.
- 테스트: ① 두 inspect 모두 실패 → exec 미호출, rollback 없음, degraded. ② 매칭 컨테이너 0개 → degraded, rollback 없음. ③ 프로브 1회 timeout → unknown, 카운터 미증가; exit!=0 3회 연속 → rollback 정확히 1회. ④ install 단계 TimeoutExpired → 릴리스가 `reviewed` 유지, `verify` 미호출.

## 우선순위 (제안: A → C → B)

Codex 안과 B/C 순서만 다르다. 근거: **C가 진행성 정지의 증폭기**다. 단발 프로브 실패로 인한 롤백은 `releases.py:151-154` → `scheduling.py:33-35`로 감사 큐 전체를 정지시키고, `reconcile_audits`는 pause를 되돌리지 않는다. C는 국소적이고 위험이 낮다. B는 되돌릴 수 없는 Git 연산을 건드리므로 가장 크고, A(펜싱 계약)와 C(오류 분류)가 먼저 자리 잡은 뒤 그 어휘 위에서 구현하는 편이 안전하다. 다만 **B4(큐 재시도)는 B2와 반드시 같은 변경에 포함**해야 한다 — 분리 반입 시 허위 rebase가 증가한다.

가설 5·7은 무해한 Docker fixture 검증 결과가 나오기 전까지 구현 대상에서 제외하는 데 동의한다. 6은 설계 항목으로 이월. 구현은 Codex가 진행하고, 나는 구현 후 위 테스트 계약 충족 여부만 읽기 전용으로 재검토하겠다.