# 계약 추출은 분모를 세고, 변환은 전체 입력 위에서 검증하며, 판정은 자문이다

기존 FA-024 / GitHub [#25](https://github.com/trevi00/zeus/issues/25) / `ZEUS-8bbe68a96580` 개정 1의 구현·검증 기록입니다.
상류 seam registry의 격리 실측([resolution](../../../full-analysis/baldrix-seams-001/resolution.md))에서 부분 value_map과
affix가 서로 다른 입력을 하나로 합쳐 OK를 반환하고, 모르는 affix 옵션이 무시되어 no-op affix가 identity 가드를 우회하고,
Java/Dart/Proto가 멤버를 빠뜨리고도 HIGH를 주고, tag:name 비교가 타입 변경을 못 보고, 다른 package의 같은 짧은 이름이
버려지고, 원장 마지막 줄 손상이 이전 DRIFT를 사라지게 하는 것이 확인됐습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus에는 seam/계약 추출 기능이 없었습니다. 이 PR은 상류의 정규식 추출기를 옮기지 않고, 계약·변환·비교·원장을 **타입이
  있는 데이터**로 정의하고 실제 파서가 있는 스택(Python `ast`) 하나만 구현하며 나머지 스택은 명시적으로 unsupported로
  둡니다.
- `domain/seams.py` (stdlib만):
  - `contract_identity(stack, package, name)`: 세 토큰의 digest. 같은 짧은 이름도 package가 다르면 다른 계약.
  - `parse_transform`: kind별 닫힌 키 집합(identity / value_map / affix). 모르는 옵션(`strip_prefx`)·빈 value_map·빈 affix
    거절. `effective_transform(transform, values)`: **전체 입력(passthrough 포함)** 위에서 매핑을 계산해 충돌(`collisions`)과
    빈 target을 이름 붙이고, 선언은 non-identity인데 실제로 아무것도 바꾸지 않으면 `declared_effective_mismatch`로 보고합니다
    (매핑으로 신뢰하지 않음).
  - `parse_observation`: identity 일치, kind, 멤버(name/type/tag/span, 중복 거절), fidelity(HIGH는 unresolved 0일 때만),
    분모(`symbols_found`, `unresolved`), source(path/blob sha/revision/parser).
  - `parse_policy`/`compare`: 방향(producer_to_consumer / consumer_to_producer / both)·비교 키(name 필수, type/tag 선택)·
    요구 fidelity(HIGH만). LOW/UNKNOWN은 BLOCKED, 충돌은 NEEDS_TRANSFORM, 방향별 producer_only/consumer_only/changed로
    DRIFT/OK. 결과는 `authority: advisory`, `blocking_eligible: False`이고 "textual agreement ≠ compiler/serialization/product
    compatibility"를 명시합니다.
  - `audit_records`: 가져온 원장의 valid/corrupt를 나눠 세고 corrupt가 있으면 `partial`.
- `adapters/seam_extraction.py`: `extract(stack, root, path, revision)` — Python은 `ast`로 최상위 `Enum`/`IntEnum`/
  `StrEnum`/`Flag`/`IntFlag` 클래스를 찾아 리터럴(int/str) 멤버만 HIGH로, 호출·식은 unresolved(LOW)로 셉니다. 멤버·클래스의
  `span`은 **원본 바이트** offset(주석 제거·행 재번호 없음)이며 `blob_sha`·`revision`·`parser` 버전을 싣습니다. 읽기 실패·
  디코딩 실패·문법 오류·크기 초과(부분 읽기 없음)·미지원 스택·없는 파일은 각각 이름 있는 UNKNOWN 관측입니다.
  `discover(root, stack, max_files)`는 정렬 후 cap을 적용하고 `omitted`를 셉니다.
- `application/seam_ledger.py`: `SeamLedger.record_observation`(blob/parser/revision당 한 행, 바인딩 revision 일치 요구),
  `compare`(기록된 관측 두 개 + transform + policy → 멱등 행), `approve_blocking`(검토자·40-hex 정책 revision·사유가 있을 때
  DRIFT만 blocking-eligible; NEEDS_TRANSFORM/OK는 거절), `import_jsonl`(줄 단위로 valid/corrupt를 보존; 이전 DRIFT는 손상된
  tail에 지워지지 않고 audit은 `partial`).
- `docs/contracts.md`: `INV-SEAM-001` 추가.

## 재현과 검증

- `tests/test_seam_contracts.py`(7 검사; 추출은 실제 파일·실제 파서, 원장은 MemoryStore + PostgreSQL 격리 스키마):
  - 변환: 부분 value_map의 passthrough 충돌(상류 OK → 여기선 collisions), prefix strip 충돌, 모르는 affix 옵션 거절, 빈 affix
    거절, identity에 붙은 value_map 거절, 잘못된 5종, no-op 보고, 빈 target.
  - identity: package가 다르면 다른 id; 잘못된 토큰 4종; HIGH+unresolved 거절; 중복 멤버 거절; 위조 identity 거절; 정책
    검증(LOW 요구·name 없는 compare 거절).
  - 비교: 방향별 DRIFT, 충돌 → NEEDS_TRANSFORM, 구분되는 rename → OK, **타입 변경은 `type`을 비교할 때 보이고 name-only
    정책에서는 안 보임(정책이 약하다는 사실을 명시)**, LOW/UNKNOWN → BLOCKED(분모 동봉).
  - Python 추출: docstring·주석 뒤의 enum에서 `PAID = 2`의 byte span이 **디스크 원본 바이트**(Windows CRLF)와 일치, 한 글자
    멤버 유지, `_ignored` 제외, 호출 값은 LOW+unresolved 1, 다른 package의 `Status`는 다른 id, 문법 오류/잘못된 UTF-8/없는
    파일/2MiB 초과/Java 스택 각각 UNKNOWN 상태, 정렬 후 cap과 omitted 계수.
  - 원장(memory+PG): 같은 blob·parser·revision은 한 행, 바인딩 revision 불일치 거절, 비교 멱등, 미기록 관측 거절, 검토자
    아닌 승인 거절, `HEAD` 정책 revision 거절, DRIFT 승인 후 멱등, NEEDS_TRANSFORM 승인 거절.
  - 원장 import: 정상 DRIFT·OK 뒤 잘린 줄과 미지 verdict → valid 2/corrupt 2/`partial`, DRIFT 1 보존, 멱등.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_seam_contracts.py` (HARNESS_INTEGRATION=1, PG 격리 스키마) | 11 passed in 0.65s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 955 passed, 311 skipped, 1 failed — 실패는 이 변경과 무관한 간헐 실패 `test_execution_fence…reissue_generation[memory]`(1초 lease 만료 타이밍; 단독 재실행 통과) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 추출기는 Python 최상위 enum(리터럴 값)만 지원합니다. 중첩 클래스·Java/Dart/Proto·message 종류는 registry에 없어
  UNKNOWN(`unsupported_stack`)이며, 추가하려면 실제 파서 기반 추출기와 registry 항목이 필요합니다.
- name/type/tag 일치는 텍스트 비교이지 컴파일·직렬화·실제 제품 호환성이 아닙니다(INV-SEAM-001). 사람이 검토한 핵심 시나리오
  증거와 Windows/Linux/WSL 실측은 별도입니다. blocking 승인의 정책 revision은 Git 커밋 형식만 검증하고 존재 여부는
  확인하지 않습니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.
