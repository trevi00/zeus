## 결함 (우선순위순)

**1. (중) 깨진 배포가 영구히 롤백되지 않을 수 있음 — false-negative health**
`deployment.py:36-39`가 docker **exit 125를 무조건 `observation_error`**로 분류한다. 125는 데몬 연결 실패뿐 아니라 컨테이너 생성/OCI 설정 실패, 즉 *실제로 기동 불가능한 후보 이미지*의 대표 증상이기도 하다. 여기에 `_probe_status`(`:248`)가 unknown일 때 카운터를 증가시키지 않는 수준을 넘어 **0으로 리셋**한다(`test_release_health.py:106`이 이 동작을 고정). 두 규칙이 겹치면 (a) 기동 불가 이미지는 매 tick `unknown`으로만 보고되어 임계치에 영원히 도달하지 못하고, (b) 실제 실패와 일시적 데몬 불가가 번갈아 발생하는 현실적 패턴에서도 카운터가 매번 초기화된다. `monitor()`가 조기 반환하므로 supervisor의 `rolled_back` 분기도 발동하지 않아 잘못된 이미지가 계속 active로 남는다.
수정: 125 단독 규칙을 제거하고 stderr 데몬 패턴으로만 판정. unknown은 증가도 리셋도 하지 않고 카운터를 **보존**.
테스트: executed 실패 2회 → unknown 1회 → executed 1회에서 롤백 1회. `docker run`이 125 + "executable file not found" stderr일 때 `executed`로 분류되는지.

**2. (중) 연속 실패 카운터가 컨테이너 ID로 키잉되어 누적되지 않음**
`deployment.py:292`가 `_probe_status(..., component=container["ID"])`를 쓰고, 키는 `release_id + ":" + component`(`:244`)다. 컨테이너 ID는 재생성마다 바뀌고, supervisor는 drift·wake 시 컨테이너를 교체하므로 컨테이너 단위 실패는 매번 새 키에서 1부터 시작한다 → `health_failure_threshold=3`에 사실상 도달 불가. 부수적으로 `health_probes` 행이 무제한 증식한다. 이미지 프로브(component="image")만 정상 누적되므로 "배포된 컨테이너 안에서 CLI가 죽는" 사례가 롤백되지 않는다. 현재 테스트는 ID가 고정 fixture라 이 경로를 잡지 못한다.
수정: 안정 식별자인 **서비스 이름**으로 키잉.
테스트: 컨테이너 ID를 매 호출 바꾸면서 동일 서비스가 3회 연속 실패 → 롤백 1회.

**3. (하) 원격 merge 이후 크래시가 `blocked_remote`로 분류되지 않음**
`deployment.py:179`의 일반 blocked 분기가 `:181`의 remote 분기보다 먼저 평가되고 `external_started`를 보지 않는다. publish + `gh pr merge` + 로컬 ff가 끝난 뒤 receipt 기록(`:198-200`) 전에 죽으면 HEAD ≠ base, `merged` 미기록이므로 **일반 `blocked`("Git position differs")**로 나온다. 원격에 이미 병합된 PR이 존재하는, 가장 조심해야 할 창구가 원격 신호 없이 보고되는 셈이다. `test_release_recovery.py:91-104`는 publish 중단만 덮는다.
수정: 일반 blocked 판정 전에 `intent["remote"] and intent.get("external_started")`를 우선 검사.
테스트: publish·merge 성공 후 receipt 전 크래시 → `blocked_remote`, merge 재호출 0회.

## 테스트·계약 종합 평가

합의한 A/B/C 계약은 위 3건을 제외하면 충족됐다고 본다.

- **A**: `_fail_task`가 실패 커밋과 진단 enqueue를 단일 트랜잭션으로 묶고(`executor.py:433-448`), `_lost_execution`이 stale을 예외 대신 마커로 반환하며 `decide_one`(`:528-532`)과 어휘가 통일됐다. "lease를 잃은 워커는 권위 있는 진단을 쓰지 않는다"도 성립한다. 유효 lease 상태의 진짜 계약 위반에서만 `raise error`가 남는데, 이는 합의대로 수용 가능.
- **B**: intent 저널이 되돌릴 수 없는 연산 **직전**에 기록되고, 복구는 정확한 candidate revision 또는 기록된 merge에만 재개하며 `porcelain`·tree를 재검증한다(`:174-178`). 허위 rebase 방지가 3종 크래시 × memory/postgres로 검증됐고, 큐는 단일 DB lease·attempt 3·지수 backoff·동시 claim 1개까지 커버된다. rejected checks 보존과 stale 컨트롤러 거부도 확인.
- **C**: `release_check_seconds=900`과 외부 단계 전후 fence로 1200초 lease가 유지되고, observation_error가 `verify`를 호출하지 않아 검수 상태가 보존된다. monitor의 unknown/degraded/healthy 어휘와 "idle 부재는 drift 아님"도 계약대로다.

즉 남은 것은 새 계약 자체의 결함이 아니라 **판정 경계 3곳**(125 분류, 카운터 키, remote 라벨 우선순위)이다. 1·2는 롤백이 필요한 순간에 발동하지 않는 방향의 오류이므로 함께 처리하길 권한다. 소스 테스트는 별도로 실행 중이며, 나는 실행 결과를 확인하지 않았다.