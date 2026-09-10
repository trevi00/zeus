# 파생 VIEW는 출처·역할·방향을 지키고, 게이트 어휘는 닫혀 있으며, 의무 0건은 통과가 아니다

기존 FA-027 / GitHub [#28](https://github.com/trevi00/zeus/issues/28) / `ZEUS-92ca5e645c56` 개정 1의 구현·검증 기록입니다.
상류 예제 fleet의 격리 실측([resolution](../../../full-analysis/baldrix-example-fleet-001/resolution.md))에서 그래프의 LIVE가
"매치되고 BLOCKED 아님"(실제 전달 아님)이고, producer/consumer 역할·drift 방향·BLOCKED가 그래프에서 사라지며, 없는 fixture가
참여 edge로 그려지고, `--fail-on TYPO`가 전부 통과하며, 빈 seam 목록이 0/0 성공이 되는 것이 확인됐습니다. 이 PR은 FA-024(#56)
위에 쌓여 있습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- FA-024가 관측·비교를 타입 있는 원장 행으로 만들었고, 이 PR은 그 행들의 **파생 VIEW**와 게이트를 정의합니다. SDD 리포트에는
  단계별 분모를 추가합니다.
- `domain/seam_view.py` (stdlib만):
  - `parse_gate_policy`: `fail_on`은 DRIFT/NEEDS_TRANSFORM/BLOCKED만(오타·OK·빈 목록·중복 거절), `required_seams`는 비어 있을
    수 없음, version 1.
  - `build_view(observations, comparisons, policy)`: 노드는 `provenance`(observed/extracted_partial/unavailable/declared_only)
    ·fidelity·source·멤버 수, 엣지는 roles·direction·verdict·양쪽 fidelity·effective transform·collisions·producer_only/
    consumer_only/changed·comparison id·`blocking_eligible`. `live`는 두 HIGH 관측 간 OK일 때만. 정책이 요구하지만 비교가 없는
    seam은 `declared_only` 엣지(verdict None)로 남습니다. 노드·엣지는 정렬돼 입력 순서와 무관하게 byte-equal이며, `receipt`
    (generator, inputs_hash, view_hash, `derived: True`)를 싣습니다. 같은 seam에 다른 비교 두 개가 들어오면 거절합니다.
  - `gate(view)`: required seam마다 상태(verdict 또는 missing)를 세고, `fail_on`에 있는 verdict가 하나라도 있으면 `fail`,
    모두 OK면 `pass`, 그 외(BLOCKED/NEEDS_TRANSFORM/missing 등)는 `undecided`. `required/checked/ok` 분모 동봉. 자문 권한.
- `application/seam_ledger.py`: `view(policy)`가 기록된 관측·비교로 VIEW를 만들어 `seam_views`에 inputs_hash 키로 저장(재생성
  시 view_hash가 다르면 거절 — 결정성 위반 감지). 파생 행이며 정본이 아닙니다.
- `domain/sdd.py`: `gate_report`에 `denominators`(선언 시나리오·가져온 관측·runner 실행·검증된 assertion·사람 인수)를 추가.
  runner 실행/assertion/인수는 실제 증거 경로가 없으므로 정직하게 0입니다.
- `docs/contracts.md`: `INV-SEAM-VIEW-001` 추가.

## 재현과 검증

- `tests/test_seam_view.py`(6 검사; 원장 검사는 MemoryStore + PostgreSQL 격리 스키마):
  - 정책: TYPO/OK/빈 fail_on/빈 required/중복/버전/키 누락 거절.
  - VIEW: HIGH 관측은 observed, LOW는 extracted_partial, UNKNOWN은 unavailable(멤버 0); DRIFT 엣지의 roles·direction·
    producer_only 보존, live False; OK 엣지만 live; BLOCKED 엣지는 fidelity(LOW/UNKNOWN)와 함께 live False; 정책만 요구한 seam은
    declared_only. 게이트: DRIFT seam → fail(failing 목록), 비교 없는 seam은 missing, BLOCKED는 undecided, 분모 4/3/1.
    **상류가 `--fail-on DRIFT`로 통과시킨 BLOCKED seam은 여기서 undecided**, `fail_on BLOCKED`면 fail; OK만 요구하면 pass;
    required에 ghost가 섞이면 undecided.
  - 결정성: 입력을 뒤집어도 VIEW와 view_hash가 같고 JSON도 동일; 입력이 바뀌면 inputs_hash/view_hash가 바뀜; 같은 seam의
    상충하는 비교 거절.
  - 원장(memory+PG): view 행이 derived이고 같은 입력은 같은 행, 정책이 바뀌면 다른 행(fail).
  - SDD 리포트 분모: 선언 시나리오 수, 가져온 관측 1, 실행/assertion/인수 0, `acceptance_passed` False.
- `tests/test_seam_contracts.py` + `tests/test_sdd.py`와 함께 33 passed.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_seam_view.py` + `test_seam_contracts.py` + `test_sdd.py` (HARNESS_INTEGRATION=1) | 33 passed in 4.24s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; FA-024 `9ba590b` 위에서) | 961 passed, 312 skipped (163s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- VIEW는 JSON 구조이며 HTML/그래프 렌더러는 없습니다. Windows/Linux/WSL 실제 실행·줄바꿈·상대경로 실측은 하지 않았습니다.
  사람이 정의한 핵심 사용자·실패·금전 시나리오의 E2E 인수와 Astra→Sol→Terra 자격은 이 VIEW의 소비자가 아니며(INV-SEAM-VIEW-001),
  SDD 분모의 실행/assertion/인수는 실제 runner·사람 승인 경로가 생길 때까지 0입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.
