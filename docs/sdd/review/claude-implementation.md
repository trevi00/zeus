## 차단 결함 (blocker)

**BL1. 재생 코드의 실행 순서·리셋이 계약과 어긋난다** — `adapters/sdd.py:144,150`
`appium:noReset: True`인데 테스트 메서드명이 `test_<digest[:16]>`다. unittest는 메서드를 **알파벳 순**으로 실행하므로 시나리오 순서가 스펙 순서와 무관해지고, 시나리오 간 리셋도 없다. `reset_contract`는 자유 텍스트로만 존재하고(`domain/sdd.py:46`) 생성 코드 어디에도 반영되지 않는다. 결과: 상태가 누수되는 순서 의존 스위트가 "결정적 재생"으로 제시된다.
최소 수정: 활성 시나리오 순번을 메서드명에 넣고(`test_0001_...`), 시나리오별 리셋이 바인딩/구조화된 계약으로 존재하지 않으면 **다중 시나리오 export를 거부**한다. 테스트: 3개 시나리오 export 시 순번 존재, 리셋 부재 시 export 실패.

**BL2. "unexecuted" 라벨이 강제력이 없다** — `adapters/sdd.py:50-59`, `sdd_cli.py:25`
`--output`이 임의 경로다. `tests/test_replay.py`로 내보내면 pytest가 수집하고, 릴리스 canary의 후보 스위트(`deployment.py:105`)가 이를 실행해 `setUp`이 RuntimeError → **정상 후보가 거부**된다. 반대로 `ZEUS_TARGET_ENV`/`ZEUS_APPIUM_URL`이 설정된 머신에서는 `python <file>`(`:165`의 `unittest.main()`)로 실기기 실행이 가능하다.
최소 수정: replay export는 `repository_root()` 내부(특히 `tests/`) 경로를 거부하고, 수집되지 않는 확장자로 쓰거나 명시적 `--force-inside-repository`를 요구한다. 테스트: 저장소 내부 경로 export 거부.

**BL3. adb 출력 파싱이 예외로 죽는다** — `adapters/sdd.py:88-93`
`adb devices -l` 최초 실행 시 `* daemon not running; starting now at tcp:5037` 같은 줄이 섞이면 `parts[:2]`가 `["*","daemon"]`이 되어 `require(re.fullmatch(...))`가 ContractError를 던진다. 계약상 이 상황은 `unavailable`이어야 하는데 **probe 전체가 실패**한다.
최소 수정: 정규식 불일치 줄은 raise 대신 skip하고 `^\S+\s+(device|offline|unauthorized|authorizing|no)` 형태만 파싱.

**BL4. 물리 삼성 기기가 없어도 `discovered`** — `adapters/sdd.py:105`
에뮬레이터나 비삼성 기기만 붙어 있어도 top-level이 `discovered`가 되어 "기기 확보"로 오독될 수 있다. 합의한 C5(에뮬레이터 대체 불가)가 개별 `physical_candidate`에만 반영돼 있다.
최소 수정: `any(d.get("physical_candidate"))`가 아니면 `blocked` + 사유. 테스트: `emulator-5554` 픽스처 → blocked.

**BL5. 요구사항 ID에는 은퇴 보호가 없다** — `domain/sdd.py:72-80` vs `:115-119`
시나리오 ID 재사용만 막혀 있고 requirement ID는 자유롭게 삭제·재사용된다. `risk: financial` 요구사항 ID를 삭제 후 다른 의미로 재사용하면 과거 시나리오 결속과 증거의 의미가 조용히 바뀐다(내가 앞서 제기한 C4의 미보호 절반).
최소 수정: `previous`의 requirement ID도 존재를 요구하고, 의미 변경은 새 ID로만. 테스트: 삭제 후 동일 ID 재사용 거부.

**BL6. `assert_text`의 stale element** — `adapters/sdd.py:163`
앞서 찾은 `element`를 클로저로 캡처해 `.text`를 읽는다. Selenium `WebDriverWait`의 기본 무시 예외는 `NoSuchElementException`뿐이라, 화면 재렌더 시 `StaleElementReferenceException`이 그대로 터져 **정상 동작이 실패로 관측**된다. 최소 수정: locator 기반 조건(`EC.text_to_be_present_in_element`)으로 교체.

## 다음 슬라이스 (차단 아님)
- 알림 해소 API가 없어 `_notify`가 항상 `status: "open"`으로 재설정된다(`application/sdd.py:41-47`).
- `then` 오라클↔바인딩 1:1 강제가 export 시점(`adapters/sdd.py:121`)에만 있고 스펙 검증 단계에는 없다.
- `timestamp`는 None 허용, `observed_timestamp`는 필수인 비대칭이 표현식으로만 드러난다(`domain/sdd.py:150`).
- `observe()`가 트랜잭션 밖에서 아티팩트를 먼저 써 실패 시 고아 아티팩트가 남는다(`application/sdd.py:110`).
- `read_spec`이 저장소 밖 경로에서 `relative_to` ValueError를 낸다(`adapters/sdd.py:35`).

## 확인된 정합 사항
`gate_report`가 전 단계를 `blocked`/`not_run`으로 고정하고 `release_authorized: False`를 명시(`domain/sdd.py:183-195`). `propose_scenarios`가 `expected`를 만들지 않고 `authority: proposal_only`, `acceptance_passed: False`를 고정(`:171-175`) — 로그→오라클 누출은 이 경계에서 막힌다. 이벤트 저널의 해시 체인·순번·헤드 일치 검증(`application/sdd.py:90-95`). 스냅샷 대 `spec_hash` 재검증(`_spec`, `:18-21`)과 티켓/헤드 결속(`_current`). 전이 기록은 `recorded_unqualified` + `routing_authority: False`이며 와일드카드 task_family 금지(`:165-186`). replay가 financial 요구사항을 거부(`adapters/sdd.py:115`)하고 input에 인라인 자격증명을 금지(`:124`). 검토 HTML은 `<`/`>`/`&`를 이스케이프해 JSON script 태그에 넣는다(`:65`, html:26).

실행·기기·인수 승인은 어느 것도 인증하지 않으며, 보고된 13 pass도 검증하지 않았다.