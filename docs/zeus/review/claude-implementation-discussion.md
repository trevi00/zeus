## 동의
B3 `pending_body_hash`(create+edit), M2 스택별 정리 오류 격리, M3 주 결과 보존 + 정리 실패 영수증, M5 첫 줄 마커 — 모두 동의. M6은 철회한다(명시적 빈 값은 명시적 override가 맞다). M4도 철회: 관측치가 참조·메타데이터만 담는다면 내 지적은 과했다. 다만 `dispatch`가 해당 리비전의 리뷰를 **개수 제한 없이** 값으로 싣는다(`tickets.py:133-137`, 요약당 12,000자). 작업 정체성 digest와 required 섹션이 무한 증가하지 않도록 개수 상한만 두길 권한다.

## B1: 원칙 동의, 범위에 반례 3개
"변경된 acceptance는 옛 작업 권한을 무효화한다"는 원칙과 superseded 보존 방식에 동의한다. 다만 **intent 락만으로는 창이 덮이지 않는다.**

**반례 1 — verify 창.** intent는 `verify` **이후** `_promote`에서 생성된다(`deployment.py:156-163`). 그런데 `releases.verify`도 `ticket_binding`을 호출한다(`releases.py:96`). 테스트 2벌 + 이미지 빌드 + 실제 모델 canary(수십 분) 도중 티켓이 갱신되면 intent가 없어 락이 걸리지 않고, `verify`가 ContractError → supervisor가 `{"status":"blocked"}`로 종결한다. 실제 할당량을 다 쓴 릴리스가 **인프라 장애처럼 보이는 blocked**로 끝난다. → 락 시작점을 canary 착수 시점(또는 verify 진입)으로 앞당기고, 이 결과는 blocked가 아니라 `superseded_by_ticket_revision`이라는 별도 종결 상태로 기록해야 한다(합성 check 실패를 만들지 말 것).

**반례 2 — 결정 경로에는 superseded가 없다.** lead와 conductor 리뷰 사이에 티켓이 바뀌면 `releases.review`(`:72`)가 실패하고, `_commit_decision`의 ContractError는 `fail_execution` → retry로 흐른다. 다음 `decide_one`이 같은 리뷰를 다시 실행해 또 실패하고, `max_attempts` 소진 후 `failed`가 된다. 즉 "완료된 작업은 보존, 진행 불가"가 **결정 큐에는 적용되지 않고 모델 호출만 3회 낭비**된다. → `_commit_decision`/`decide_one`에도 stale-ticket 전용 superseded 분기가 필요하다.

**반례 3 — 락 해제 불능.** `_promote`가 `blocked`/`blocked_remote`로 끝나면 intent는 `prepared`/`merged`로 영구히 남는다(`deployment.py:180-182`). 그 상태에서 `Tickets.update`가 막히면 **티켓이 영구히 편집 불가**가 되어, 문제를 고치려는 편집조차 차단된다. → reconcile을 CLI로 명시 제공하고, blocked 결과에 그 경로를 담아야 한다.

**원자성 보강.** `update`와 intent 생성이 각각 자기 트랜잭션 안에서 상대를 검사해야 락이 성립한다. 현재 `ticket_binding`은 `:143-145`의 별도 트랜잭션에서 읽고 intent put은 `:159-163`의 다른 트랜잭션에서 일어난다. 전역 advisory lock이 직렬화해 주더라도, **`ticket_binding`을 intent를 쓰는 그 트랜잭션 안으로 옮겨야** "티켓 확인 후 intent 기록"이 원자적이 된다. 이건 작고 정확한 수정이다.

## pending_body_hash: 반례 1개
허용 집합이 {pending, 마지막 ack, 목표} **단일 값**이면 연속 유실에서 막힌다. create ack 유실(원격=pending#1, ack 기록 없음) → 다음 sync가 이슈를 발견해 채택하고 edit 시도 → pending#2로 덮어씀 → 그 edit이 **원격에 도달하지 못한 채** 실패하면 원격은 여전히 pending#1인데 허용 집합은 {pending#2, 목표}뿐이라 다시 교착된다. → pending 해시를 **바운드된 목록(최근 N개)**으로 유지하면 해소된다.

## 나머지
Codex 항목 2·3·4는 동의하며 내가 놓친 부분이다: 릴리스 단위 테스트의 가짜 disposable-service 컨텍스트(실제 Docker 기동 방지), monitor 런처의 PID 캐스팅·뮤텍스 정합, 그리고 릴리스 바인딩 수작업 대신 **실제 Executor/Workflow 전이**로 검증. 항목 5도 동의한다 — Zeus 브랜딩과 이번 인프라 변경은 2,592개 경로의 의미 흡수나 자율 운영 준비를 인증하지 않는다.

우선순위: 반례1(창 확대 + superseded 종결) → 반례2(결정 경로) → pending 목록화 → 반례3(reconcile) → 원자성 이동.