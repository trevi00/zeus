## 결과: 남은 차단 결함 1건

합의한 나머지 계약은 코드에서 확인됐다. 다만 반례3(freeze 해제 불능)이 **부분적으로만** 해소됐고, 한 경로가 남는다.

### BLOCKER — blocked 상태의 intent는 티켓을 영구히 동결시킨다
- **경로:** `Tickets.update`(`tickets.py:80-83`)는 해당 티켓의 promotion_intent 상태가 `completed`/`abandoned`가 아니면 편집을 거부한다. `ReleaseRunner.abandon`(`deployment.py:237`)은 `HEAD == intent["candidate"]["base"]`를 요구한다. 그런데 `_promote`가 `blocked`을 반환하는 분기(`:194-195`)는 정의상 **HEAD가 base도 expected_head도 아닌** 상태다.
- **트리거:** intent가 `prepared`로 기록된 뒤(로컬 전송, merge 이전) main이 제3의 커밋으로 전진 → 다음 `_promote`가 `{"status":"blocked"}` → 큐에서 종결. 이후 `release-abandon`은 `:237`에서 "Git has advanced"로 거부, `Tickets.update`는 `:82-83`으로 거부, `release-retry`로 재시도해도 같은 blocked 분기로 되돌아온다.
- **결과:** 릴리스는 `verified`로 남고 intent는 `prepared`로 고정되며, **그 티켓은 영구히 편집 불가**가 된다. 문제를 고치려는 편집조차 막히므로 DB 수동 개입 외에 탈출구가 없다. (`abandon`이 clean worktree도 요구하므로 `:239`, 작업 트리가 더러운 상태에서는 더 좁아진다.)
- **수정 제안:** `abandon`의 "증명 가능한 미병합" 판정을 HEAD 정확 일치가 아니라 **비조상성**으로 바꾼다 — `git merge-base --is-ancestor <candidate.revision> HEAD`가 거짓이면 후보는 main에 들어가지 않았음이 증명된다. `external_started`/`merge` 미기록 조건과 controller 리스 조건은 그대로 유지한다. 이렇게 하면 blocked 상태에서도 안전하게 취소·동결 해제가 가능하고, 원격 불확실 케이스는 여전히 fail-closed로 남는다. dirty worktree 요구는 병합 여부 증명과 무관하므로 abandon 경로에서는 완화하거나 별도 경고로 낮추는 편이 낫다.
- **회귀 테스트:** intent를 prepared로 만든 뒤 main에 무관한 커밋을 추가 → `_promote`가 blocked → `abandon`이 성공하고 intent가 abandoned, 릴리스가 cancelled → `Tickets.update`가 통과. 반대로 후보가 이미 main의 조상이면 abandon이 거부되는지, `external_started`가 있으면 여전히 거부되는지.

### 보조 관찰 (차단 아님)
`run()`의 TicketSuperseded 핸들러(`deployment.py:59-62`)는 `tx.get("releases", ...)` 결과를 존재 검사 없이 `.update` 한다. 릴리스 레코드가 없는 상태에서 예외가 오면 AttributeError로 바뀐다. 도달 경로가 좁지만 `require(release is not None)` 한 줄이면 된다.

### 제한된 검사에서 확인된 사항
- **stale 종결이 재시도를 소모하지 않음:** `workflow.complete:133-139`가 결과를 보존한 채 `superseded`로 종결하고 outbox 보고를 만들지 않는다(하위 효과 없음). `decide_one`의 admission(`executor.py:471-476`)은 attempt 증가 전에 `continue`하고, commit 경로(`:552-553`)도 결과를 보존한 채 superseded로 종결한다. 내 반례2는 해소됐다.
- **verify 창:** `releases.verify:103-107`이 실제 canary 검사를 보존한 채 `superseded_by_ticket_revision`으로 기록하고, `_run:147-148`이 그 상태를 그대로 전달하며, `ReleaseRunner.run:55-63`이 이를 blocked이 아닌 전용 종결로 만든다. 큐의 `claim`은 이 상태를 집지 않으므로 종결이다. 반례1 해소.
- **merge→DB 경쟁:** `_promote:171-176`이 intent 기록과 `ticket_binding`을 동일 트랜잭션에 두고, `:209-210`이 merge 직전에 다시 확인하며, `update`의 동결이 prepared/merged 구간을 덮는다. 원자성 지적 해소.
- **abandon의 보수성:** `external_started`/`merge` 기록이 있으면 거부(`:235-236`), controller 리스가 살아 있으면 거부(`:232-234`) — 원격 모호성은 여전히 fail-closed다.
- **GitHub 복구:** 관측된 본문 해시를 pending 교체 **전에** 고정하는 방식은 내가 지적한 "연속 유실 시 pending#1 소실" 반례를 해시 목록 없이 덮는다. 설계상 타당하다고 본다.

## 범위 한정
이 검토는 위 파일들의 변경 지점에 한정한 정적 읽기다. 테스트를 실행하지 않았고, 통과했다는 보고도 검증하지 않았다. Windows/Linux 실제 런타임, 실제 Docker·GitHub 동작, 그리고 2,592개 로컬 원본 경로의 의미 흡수는 여전히 인증 대상이 아니다. 위 blocker 1건 외에는 이번 범위에서 추가 차단 결함을 찾지 못했다.