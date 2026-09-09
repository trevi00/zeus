## 차단 결함 (blocker)

**B1. 티켓이 릴리스 승격을 막는 하드 게이트가 됐다 — 합의한 "advisory only" 위반**
`releases.py:55,72,96,111`(propose/review/verify/promote)과 `deployment.py:144,197`이 모두 `ticket_binding(tx, candidate)`을 호출하고, `ticket_binding`은 `tickets.py:46-47`에서 **티켓의 현재 head 리비전과 일치**할 것을 요구한다. `git.py:94-95`가 `zeus_ticket`을 candidate에 실어 나르므로, 검수까지 끝난 후보에 대해 운영자가 오타 하나만 고쳐도 `verify`/`promote`가 "Ticket changed; reassessment required"로 실패한다. supervisor는 이 ContractError를 `{"status":"blocked"}`로 종결하므로 **정상 릴리스가 영구 차단**된다. 더 나쁜 창: `_promote`의 `git.merge` 성공 이후 promote 직전에 티켓이 바뀌면 main에는 병합됐는데 DB 포인터는 전진하지 못한다.
수정: 승인 이후 지점에서는 head 동일성 요구를 제거하고, `ticket_revisions`에 저장된 바이트와 `content_hash`만 검증(이미 `tickets.py:48-49`가 수행)해 **provenance 기록**으로만 남긴다. head 검증은 admission(`submit`/`claim`)에만 둔다.

**B2. 티켓 수정이 실행 완료된 작업을 폐기하고 중복 루프를 만든다**
`workflow.py:133`(complete)과 `executor.py:544`(`_commit_decision`)가 커밋 트랜잭션 안에서 `ticket_binding`을 호출한다. 900초짜리 Codex 실행과 실제 할당량을 소모한 뒤 티켓이 갱신되면 `complete()`가 ContractError → `_fail_task` → retry → 다음 claim에서 `workflow.py:76-80`이 blocked 처리. **결과물이 통째로 버려진다.** 또한 `Tickets.update`는 기존 `ticket_dispatches`를 무효화하지 않고 상태만 open으로 되돌리므로(`tickets.py:76`), 리비전 2를 dispatch하면 구 plan 메시지와 **두 개의 개선 루프가 병존**한다.
수정: 완료 경로에서는 결과를 저장하되 `superseded_ticket_revision`으로 표시(폐기 금지). `update`는 미완 dispatch를 `superseded`로 표시하고, 새 dispatch 전에 명시적 취소를 요구.

**B3. 원격 생성 ack 유실 후 티켓이 영구 동기화 불능**
`github_tickets.py:77-78`은 링크가 없는 상태에서 **발견된** 이슈의 본문이 현재 렌더와 다르면 무조건 "changed externally"로 실패한다. 트리거: 이슈 생성 → ack 유실(`creation_uncertain=True`) → 운영자가 티켓 수정 → sync. 이때 본문 해시가 달라 채택 불가, 동시에 `:72-74`가 `creation_uncertain` 때문에 신규 생성도 거부 → **DB 수동 편집 없이는 탈출 불가**. 마커(`:66`)는 우리 자신의 provenance이므로 본문 비교보다 먼저 링크를 채택해야 한다.
수정: 마커 일치 + `creation_uncertain`이면 본문 비교 **이전에** `ticket_github` 링크를 기록한 뒤 편집으로 진행. 아울러 `creation_uncertain`과 함께 `pending_body_hash`를 저장해 유실된 ack를 본문 동일성으로도 인식.

## 중간 (blocker 아님)

**M1. sync 리스 만료 시 원격 효과만 남는다.** `_claim` 리스는 300초인데 `sync`는 최대 3회의 60초 gh 호출을 한다. 초과 시 `:102`의 `_owned`가 원격 쓰기 **이후**에 실패하고, except 핸들러의 `owner == claim["owner"]` 조건도 거짓이라 **아무것도 기록되지 않는다** — 이슈는 생겼는데 링크는 없다. 수정: 각 원격 호출 전후 리스 갱신, 또는 링크 기록을 소유권과 무관한 멱등 upsert로.

**M2. 검증 스택 청소 실패가 전체 스윕을 중단시킨다.** `verification.py:101-107`의 `require`가 루프 안에 있어 낯선 디렉터리 하나가 예외를 던지면 나머지 오래된 스택도 영구히 정리되지 않는다(`supervisor.py:77`의 job은 "failed"만 기록). Postgres/Redis 컨테이너가 무기한 누적된다. 수정: 디렉터리 단위 skip-and-record.

**M3. 정리 실패가 원래 결과를 덮어쓴다.** `_cleanup`의 `docker compose down` 실패는 RuntimeError를 던진다. `_run`이 `with VerificationServices(...)` 안에서 `_reject_remaining`을 **return**하는 도중 `__exit__`이 던지면, 정당한 rejected가 예외로 바뀌어 큐에서 retry/blocked가 된다(`deployment.py:98-109`). `__enter__`의 except 경로에서도 원인 예외를 가린다. 수정: 정리 오류는 삼키고 영수증에 기록, 디렉터리는 `collect_stale`에 위임.

**M4. dispatch가 원격 텍스트를 값으로 프롬프트에 싣는다.** `tickets.py:137-139`가 `ticket_reviews`와 `external_ticket_observations`를 `what.details`에 통째로 넣는다. 이는 `digest(message)`(작업 정체성)에 포함되고 required 섹션으로 렌더된다. `pull`은 이미 원본을 아티팩트로 저장하므로(`github_tickets.py:127`) **evidence_ref만 전달**하는 편이 INV-CONTEXT-001("외부 증거는 바운드된 데이터")에 맞고 프롬프트 주입 표면도 줄인다.

**M5. 마커 위조.** 발견 검색은 본문 내 `<!-- zeus-ticket:ID -->` 부분문자열 일치다(`:66-69`). 티켓 본문에 다른 ID의 마커를 적으면 남의 이슈를 자기 링크로 채택할 수 있다. `validate_content`에서 마커 패턴을 거부하거나 첫 줄만 인정.

**M6. 빈 문자열 별칭이 상위 값을 가린다.** `configuration.py:62-69`의 `aliases()`는 layer-local 우선순위와 양방향 노출 모두 정확하다. 다만 `ZEUS_X=`(빈 값)가 같은 layer의 유효한 `HARNESS_X`를 덮어쓴다. 빈 값은 미설정으로 취급 권장.

## 확인된 정상 사항
`aliases()`의 layer-local Zeus 우선 + 두 이름 동시 노출(`:73`, `:95-101`), 기존 `.env` 불변·비밀번호 미회전(`:115-122`), 신규 설치만 `COMPOSE_PROJECT_NAME=zeus`/`ZEUS_REDIS_NAMESPACE=zeus`(`:114`)와 `bus.py:67-68`의 폴백 `codex-harness`, 검증 스택의 랜덤 루프백 포트·일회용 비밀번호·운영 마운트 없음·`verification_environment`의 화이트리스트 상속(`verification.py:13-24`), `_cleanup`의 비재귀 삭제와 심볼릭 링크 거부, `pull`의 콘텐츠 주소 관측치(중복 없음)와 `authority: external_observation_only`, `ticket_reviews`의 `advisory_only` 표기 — 모두 합의한 계약대로다.

실행은 하지 않았고 테스트 결과도 확인하지 않았다. Codex 소견과 대조 후 우선순위(B1 → B2 → B3 → M1/M3)를 합의하자.