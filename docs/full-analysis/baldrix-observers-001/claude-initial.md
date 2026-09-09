# Baldrix D1 `observers` / `evidence_fab` 독립 정적 리뷰

**핀**: cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2 (경로상 `pinned/`)
**스코프 검증**: 선언된 7819바이트 / SHA256 `3febc60e…4ccd1`은 **검증 불가**. 이 세션에서 Bash가 비활성이고 Read/Glob/Grep으로는 바이트 수·해시를 계산할 수 없음. 읽은 실체는 `__init__.py` 26줄, `evidence_fab.py` 195줄이며 이 두 본문에 대해서만 판단함. 커밋 해시가 실제 HEAD와 일치하는지도 `git rev-parse` 없이 확인 못 함(경로 이름 외 근거 없음).

---

## 1. 실제로 무엇을 검출하는가

두 팔(arm) 구조는 docstring 그대로 코드에 있다. 다만 **실효 검출력은 arm (a) 한 줄뿐이다.**

- **arm (a)** (`_file_path_missing`, evidence_fab.py:88-101): `entry.file_path`가 비어있지 않은 str일 때 `os.stat`이 `FileNotFoundError`면 fabrication. 그 외 `OSError`는 전부 무죄.
- **arm (b)** (`_classify_replay`, :127-164): `test_result == "passed"` **그리고** `replay_cmd`가 비어있지 않은 list/tuple일 때만 subprocess 재실행.

### 치명적: arm (b)는 프로덕션에서 죽은 코드
`replay_cmd`를 grep한 결과 pinned 트리 전체에서 **`evidence_fab.py`와 자기 자신의 테스트 파일 2곳에만** 존재한다. 어떤 에이전트 frontmatter의 `output_schema`도, 어떤 프롬프트/문서도 서브에이전트에게 `replay_cmd`를 내보내라고 요구하지 않는다. `test_result`도 마찬가지로 실사용 스키마에 없다(`state/swarm-research/SUMMARY.md` 산문 언급 제외).

→ 실제 봉투는 arm (b) 진입 조건을 절대 만족하지 못한다. **"N=2 replay로 조작된 테스트 통과 주장을 검증한다"는 주장은 현재 커밋에서 미실현이다.** 남는 것은 `os.stat` 존재 확인뿐.

### 치명적: arm (a)는 D2와 완전 중복
`lib/validators/structural.py:211-221`의 layer 2가 동일한 로직(`os.stat` → `FileNotFoundError` → `EVIDENCE_FABRICATION`)을 이미 수행한다. 호출부 `_resolve_failure_mode`(agent_outcome_audit.py:230-257)는 D2의 EVIDENCE_FABRICATION과 D1의 FABRICATION_CONFIRMED를 **같은 문자열 `"evidence_fabrication"`으로 접는다**. 즉 D1 전체가 D2 layer 2 대비 순증분 검출력 0이다.

---

## 2. 증거 출처(provenance)와 비교 의미론

**비교 자체가 없다.** arm (a)는 "경로가 파일시스템에 존재하는가"만 묻는다.

- 파일 **내용**과 주장(summary)의 관계를 전혀 보지 않음.
- `line`/`line_number`/범위 필드에 대한 처리가 **코드에 아예 없음**. 라인 번호를 날조해도 통과.
- 인코딩·타입 검사 없음(파일을 열지 않으므로).
- **에이전트 자신이 방금 만든 파일**이면 무조건 통과. 위조자에게 요구되는 비용은 `open(p,'w')` 한 번.

경로 해석도 취약하다: 상대경로는 **훅 프로세스의 cwd** 기준으로 stat된다(agent_outcome_audit.py는 cwd를 고정하지 않고 `os.getcwd()`를 ledger용으로만 씀). 서브에이전트의 작업 디렉터리와 다르면 존재하는 파일이 fabrication으로 오탐되거나, 반대로 동명의 무관한 파일이 무죄 판정을 만든다.

이 공백을 조직이 이미 인지하고 있다는 증거가 호출부에 있다 — D2.5 semantic, D2.6 cross_ref, D2.7 boilerplate가 전부 "file_path는 존재 + summary는 그럴듯 + 파일은 도메인 무관" 시나리오를 메우려고 나중에 추가됐다(agent_outcome_audit.py:353-357 주석). 즉 **D1은 설계상 fabrication 검출기가 아니라 dangling-path linter다.**

---

## 3. 오탐/미탐 경계

### 미탐 (false negative) — 적대적 상황에서 사실상 100%
1. `replay_cmd`를 아무도 안 보내므로 arm (b) 미발동(위 §1).
2. 설령 스키마가 생겨도 **오라클이 피검자 통제 하에 있다**. 위조 에이전트는 `replay_cmd: [python, -c, "exit(0)"]`을 넣으면 즉시 CLEAN이다. 검출기는 그 명령이 주장한 테스트와 **어떤 관계라도 있는지 전혀 확인하지 않는다**(:139 `[str(x) for x in cmd]` 후 그대로 실행).
3. `test_result != "passed"`면 즉시 CLEAN(:133). "passed"라는 문자열을 안 쓰면 replay 회피.
4. 첫 시도 성공 시 2차 미실행(:152-154). 즉 pass→fail 순서의 50% flaky는 항상 CLEAN. 재시도는 **무죄 방향으로만** 비대칭이다.

### 오탐 (false positive) — 정직한 실행에서 실재
1. **기본 timeout 30초 vs 훅 timeout 10초.** `settings.json:263-271`에서 이 PostToolUse 훅의 timeout은 **10초**다. `_DEFAULT_REPLAY_TIMEOUT_SEC = 30.0`(:64) + `REPLAY_BACKOFF_SEC = 5.0`(replay/constants.py:17) + 2차 30초 = 최악 65초/엔트리, 엔트리 수 상한 없음. 재시도 경로에 들어가는 순간 훅이 외부에서 강제 종료되어 **D3 breaker 기록도 D5 ledger 기록도 남지 않는다.** arm (b)는 자기 실행 예산과 구조적으로 양립 불가다.
2. 느리지만 정직한 테스트(>timeout) → rc 124 두 번 → FABRICATION_CONFIRMED. **지연을 사기로 귀속**한다.
3. `cwd`가 존재하지 않으면 `OSError` → rc 127 두 번 → FABRICATION_CONFIRMED(:123-124). 환경 문제를 사기로 귀속.
4. 환경변수/서비스 의존 테스트는 훅 프로세스 환경에서 재현되지 않아 동일 경로로 오탐.

### 예외 처리 구멍
- `_file_path_missing`의 `except OSError`는 **`ValueError`를 잡지 못한다.** Windows에서 NUL 문자가 포함된 경로 문자열은 `os.stat`이 `ValueError: embedded null character`를 던진다. docstring이 말하는 "invalid encoding"은 OSError가 아니다. → `detect()`가 예외를 밖으로 던진다.
- `_replay_once`의 `except (FileNotFoundError, OSError)`도 `text=True` 디코딩 실패(`UnicodeDecodeError`, ValueError 서브클래스)를 못 잡는다. 한국어 로케일 Windows(cp949)에서 임의 바이트를 뱉는 명령이면 예외 누출. `encoding=`/`errors=` 미지정은 실환경 기준 실질 결함.
- 두 경우 모두 현재 호출부의 `_safe_call`이 삼켜서 `d1_verdict = None`이 되므로 **조용히 무죄**가 된다. 모듈 계약(`detect(envelope) -> EvidenceVerdict`, :38-39)은 위반이지만 시스템은 침묵한다.

### 에이전트 통제 파라미터 = DoS/실행 표면
`timeout`, `cwd`, `replay_cmd`가 전부 피검자 출력에서 온다. `timeout: "inf"`는 `float()`를 통과해 무한 대기가 된다(:147-150). 그리고 근본적으로 이 설계는 **서브에이전트 출력에 담긴 임의 argv를 오케스트레이터 훅이 자동 실행**한다(`shell=False`는 셸 메타문자만 막을 뿐 임의 실행 자체를 막지 않는다). "사기 검출기"가 사기꾼에게 코드 실행 프리미티브를 제공한다. 현재 arm (b)가 죽어 있어 노출되지 않을 뿐이며, 스키마를 붙이는 순간 활성화된다.

---

## 4. 호출자 해석 / 관찰자 vs 차단 권한

- **차단 권한 없음이 맞다.** `detect`는 PostToolUse(사후)에서만 호출되고 훅 출력은 비어 있다(agent_outcome_audit.py:29). 에이전트에게 피드백도, 승인 게이트도 없다.
- 그런데 **트립된 breaker를 읽는 주체도 없다.** `try_acquire`(차단 측 API) 호출자는 `engine/external_jury.py:162` 하나뿐이고, 이는 external-jury 재시도 도메인이다. `handlers/` 전체에서 Agent 디스패치 전에 `(agent_type, "evidence_fabrication")` breaker를 조회하는 pre_tool 게이트는 **존재하지 않는다.**
- 게다가 성공 경로는 명시적 no-op(:427-431) — `record_success`가 이 훅에서 한 번도 호출되지 않는다. 회복은 cool_off 후 `try_acquire`를 통한 HALF_OPEN 승격에만 의존하는데 그 호출자가 없다. 결과: **evidence_fabrication breaker는 실패만 단조 누적하고, 한 번 OPEN되면 영구 OPEN이며, 아무도 읽지 않는다.**
- `FLAKE_OBSERVED`는 **어디에서도 소비되지 않는다.** grep 결과 이 심볼은 evidence_fab.py 내부와 자기 테스트에만 등장한다. 호출부는 `d1_verdict`를 `_resolve_failure_mode`에만 넘기고, 거기서 FABRICATION 외 값은 전부 버려진다 — ledger 필드도, `_event_emit`도 없다. **"telemetry only"라는 주석(:162)은 현재 커밋에서 사실이 아니다. flake는 완전히 소실된다.**
- 반면 `evidence_paths`는 ledger에 기록된다(:441-446) — 여기서도 file_path 문자열만.

## 5. 실제 테스트 오라클

`tests/test_evidence_fab.py` 11개 함수, 커스텀 러너(pytest 아님, `TESTS` 리스트 + `main()`). 모킹은 없고 실제 `sys.executable` 서브프로세스와 tempdir를 쓴다 — 그 점은 진짜다. 다만:

- **백오프 패치가 작동하지 않는다.** 테스트는 `RC.REPLAY_BACKOFF_SEC = 0`(:29, :236)으로 `lib.replay.constants` 속성을 바꾸지만, evidence_fab.py:49는 `from ..replay.constants import REPLAY_BACKOFF_SEC`로 **임포트 시점에 값 5.0을 복사**했고 `_classify_replay`는 자기 모듈 전역을 읽는다(:157). 따라서 재시도 경로 테스트 5회는 각각 실제로 5초씩 잔다. 기능적 실패는 아니나 "fast suite"는 거짓이고, 같은 이유로 **constants.py:15-16이 안내하는 캘리브레이션 튜닝 방법("process start에 re-bind")도 무효다.** 유효한 패치 대상은 `lib.observers.evidence_fab.REPLAY_BACKOFF_SEC`뿐이다.
- 오라클이 **구현을 그대로 재진술**한다. 스키마에 없는 `replay_cmd`/`test_result`를 테스트가 직접 만들어 넣으므로, "실제 봉투에는 이 필드가 없다"는 §1의 결함을 구조적으로 볼 수 없다.
- 미커버: 상대경로/cwd 불일치, NUL·ValueError 경로, 비ASCII 출력 디코딩, `cwd` 부재 오탐, 에이전트 통제 timeout, 10초 훅 예산 초과, FLAKE 결과의 하류 소비, D2와의 중복. `timeout` 테스트(:200-217)는 rc=124 매핑만 확인하고 그것이 정직한 느린 테스트를 사기로 분류한다는 의미는 묻지 않는다.
- 이 파일은 실행하지 않았다(실행 금지 스코프). PASS 여부는 관찰하지 않았고, 과거 PASS 기록도 근거로 쓰지 않았다.

## 6. 정당한 방어 논리

- 훅은 fail-soft이고 모든 단계가 `_safe_call`로 감싸져 절대 예외를 밖으로 내지 않는다 — 관찰자로서 안전 요건은 충족.
- LLM 채점이 없다는 `judge_generator_separation` 주장은 이 두 파일에 한해 **사실**이다(os.stat + returncode만 사용).
- "shape 이상은 schema_violation 영역"이라는 관대함 정책은 D2가 실제로 그 역할을 하므로 일관된다.
- `__init__.py`는 재수출 3줄로, 지적할 결함이 없다.

---

## 종합

주장("결정론적 evidence_fabrication 검출, 2팔 구성, flake는 텔레메트리")과 코드가 어긋나는 지점이 세 층에서 확인된다: **arm (b)는 입력 스키마가 없어 발동하지 않고**, **발동하더라도 10초 훅 예산과 양립 불가하며**, **flake 판정은 아무 데도 기록되지 않는다.** 실효 기능은 D2가 이미 동일하게 수행하는 `os.stat` 존재 확인이고, 그 판정이 트립하는 breaker는 어떤 게이트도 조회하지 않는다. 검출 대상이 적대적 위조자일 때 오라클이 피검자 통제 하에 있다는 점(arm b)이 설계상 가장 근본적인 한계다.

**우선 수정 제안(영향 순)**: ① flake/verdict를 호출부에서 실제로 emit하거나 주석을 사실에 맞게 고칠 것 ② `REPLAY_BACKOFF_SEC`를 모듈 참조(`from ..replay import constants` 후 `constants.REPLAY_BACKOFF_SEC`)로 바꿔 constants.py의 튜닝 계약을 복구할 것 ③ replay 예산(30+5+30)을 훅 timeout 10초 이하로 강제하고 엔트리 수 상한을 둘 것 ④ `ValueError`/`UnicodeDecodeError`를 두 예외 핸들러에 포함하고 `subprocess.run`에 `encoding`/`errors` 명시 ⑤ arm (b)를 유지한다면 `replay_cmd`를 에이전트 출력이 아닌 오케스트레이터 측 화이트리스트에서 결정할 것.

**미독 스코프**: `structural.py`(grep 발췌만), `breakers/composite.py`(grep 발췌만), `semantic.py`/`cross_ref.py`/`boilerplate.py`, `event_store`/`operator_ledger`/`event_taxonomy`, `calibration/proposer.py`, 그 외 테스트 파일 전체. Zeus 측 코드는 읽지 않았으므로 Zeus 신원·러너 영수증·모델 라우팅에 대한 판단은 하지 않았다. 다른 리뷰어 리포트는 열지 않았다.