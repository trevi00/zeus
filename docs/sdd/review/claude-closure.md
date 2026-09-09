## 여섯 blocker: 모두 해소 확인

- **BL1** `adapters/sdd.py:118`이 활성 시나리오 1개만 허용하고, `:159`가 `test_0001_<hash>` 형태로 순번을 메서드명에 넣는다. 다중 시나리오는 리셋 통합이 생길 때까지 export 자체가 거부되므로 순서 의존·상태 누수가 발생할 표면이 사라졌다.
- **BL2** `sdd_cli.py:55-56`이 replay 출력에 `.py.review`를 강제한다. `tests/test_sdd.py:191`이 `test_replay.py` 대상 export가 실패하고 **파일이 생성되지 않음**까지 단정한다.
- **BL3** `adb_inventory`(`:105-107`)가 정규식으로 transport 행만 뽑고 daemon 진단은 무시한다. 예외로 죽던 경로가 사라졌고 `tests/test_sdd.py:99-104`가 파서 입력만으로 검증한다(기기 실행 아님).
- **BL4** `:100`이 `physical_candidate`가 하나도 없으면 `blocked`을 반환한다. 에뮬레이터만 붙은 경우가 "발견됨"으로 오독되지 않는다.
- **BL5** `domain/sdd.py:75,80,113,116,119-123`에서 요구사항에 status가 생겼고, ID 영구 보존·동일 ID 하의 statement/risk 불변·은퇴 ID 부활 금지·활성 시나리오의 은퇴 요구사항 참조 금지가 모두 강제된다. 내가 지적한 미보호 절반이 닫혔다.
- **BL6** `:135-141`의 `exact_text`가 locator를 재획득하고 `StaleElementReferenceException`을 재시도로 흡수한다. 부분일치 조건 대신 **정확 일치**를 유지한 판단에 동의한다 — 오라클은 정확 문자열이어야 한다.

Codex가 독자적으로 잡은 두 건도 확인된다: 제안 identity에 `iteration_id`가 포함되어 iteration 간 충돌이 사라졌고(`application/sdd.py:141`, 테스트 `:244-255`), 아티팩트 put을 트랜잭션 **밖**으로 빼고 재진입 후 `_current`와 `current == observation`을 재확인한다(`:142-149`). 파일 락 → DB 락 순서가 유지되고 펜싱도 남아 있다.

## 남은 구체 사항 (차단 아님)

1. **리뷰 출력에는 확장자 가드가 없다** — `sdd_cli.py:57-59`, `:73`. `zeus sdd view --output tests/foo.py`는 HTML을 `.py`로 쓰고, 이후 pytest 수집 시 SyntaxError를 내 후보 스위트를 깨뜨릴 수 있다. BL2와 동일 계열의 마지막 잔여물이다. 최소 수정: 리뷰 출력에 `.html` 요구.
2. **가드 위치가 얕다** — `.py.review` 검사가 CLI에만 있고 `write_export`(`adapters/sdd.py:50-59`)에는 없다. 다른 호출자가 생기면 우회된다. `write_export(kind=...)`로 내리는 편이 안전하다.
3. **사소**: `adb_inventory`의 `no` 대안은 `no permissions ...`를 state `"no"`로 잘라 기록한다. `state == "device"`만 심층 조회하므로 기능 영향은 없다.
4. **다음 슬라이스**: 알림 해소 API 부재(`application/sdd.py:41-47`은 항상 `status: open` 재설정), `then` 오라클↔바인딩 1:1이 export 시점에만 강제, `read_spec`의 저장소 밖 경로에서 `relative_to` ValueError, 중단 시 고아 아티팩트.

## 준비 인수와 기기 인수의 구분

**준비 인수(preparation acceptance)** — 이번 슬라이스에서 코드 수준으로 확인된 범위: 엄격 스키마와 미지 필드 거부, ID 영속/은퇴 규칙, 저널 해시 체인과 CAS, 관측→제안에서 `expected` 부재와 `acceptance_passed: False` 고정, 8단계 전면 `blocked`, DB 없이 동작하는 오프라인 리뷰, export 수집 방지 가드, 전이 기록의 `recorded_unqualified`와 `select_model`이 여전히 Astra 반환(테스트 `:293`).

**기기 인수(device acceptance)** — 성립하지 않는다. ADB와 기기가 없어 실기기 실행이 **한 번도 일어나지 않았고**, 브라우저 확인도 없었다. `physical_candidate`는 발견 단계의 주장이지 승인이 아니며, 리셋 영수증·인증된 인간 승인·알파/라이브 승격은 전부 미구성 상태다. 생성된 replay 초안은 검토 대상 텍스트일 뿐 실행 증거가 아니다.

따라서 이번 결과는 **SDD 준비 계층의 경계 확인**이며, Device Farm 구축, SDD 실행 엔진 완성, 프로덕션 준비 어느 것도 아니다. 보고된 16 passed 역시 내가 실행해 확인하지 않았다.