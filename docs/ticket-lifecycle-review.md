# 티켓 해결·종료 계약 검토

검토 대상은 Zeus `18c91d6aaebf0ee2105daa822b1027cb73dcab44`이다. Codex 검토자가 application/tickets.py, adapters/github_tickets.py와 직접 CLI/테스트를 정적으로 읽고 root가 구현과 대조했다. 이번 감사에서 실행·DB 변경·GitHub 종료는 없으며 실제 Claude의 독립 검토는 아직 없다.

## 사용자와 합의한 완료선

수정 구현과 해당 티켓 개정의 인수 기준 검증이 끝나면 해결 커밋·검증 증거·필요한 사람 승인을 연결해 닫는다. 분석이나 코드 작성만 끝났다는 이유로 닫지 않는다. 재발, 기준 변경 또는 승인 증거 무효화 시 이유를 남겨 다시 연다. 미해결 하위 작업을 이관할 때도 원래 인수 기준을 조용히 삭제하지 않는다.

## 현재 구현

- `Tickets`는 생성, 개정, advisory review, dispatch를 지원한다. close/reopen API와 해결 커밋·기준별 인수 증거 검증은 없다. CLI도 close/reopen을 제공하지 않는다.
- `GitHubTickets.sync`는 본문을 투영하고 revision/review 목록으로 synced 여부를 기록한다. 원격 CLOSED/OPEN은 이 판정에 포함되지 않는다. 본문 해시가 같으면 원격 제목만 달라진 경우에도 edit을 실행하지 않는다.
- 원격 변경 전에 pending body hash, 이후 PG link를 기록한다. ACK 유실과 PG 후속 기록 실패의 재호출 방어가 있지만 PG와 GitHub의 동시 원자적 커밋은 아니다. `creation_uncertain` 뒤 검색이 비어 있으면 중복 생성을 막지만 명시적 조정 API는 없다.
- 300초 lease와 PG 소유권 확인은 원격 요청 자체를 fence하지 못한다. lease 만료 뒤 늦은 원격 요청과 외부 수정의 경합을 별도 다뤄야 한다.
- pull은 외부 상태를 관측 증거로 저장한다. 이것이 로컬 완료 승인으로 승격되지 않는 방어는 유지한다. 외부 본문 충돌의 승인·조정 API는 없다.

관련 테스트에는 ACK 유실, 중복 생성 방어, 개정 결속 및 outbox rollback 검사가 있지만 close/reopen과 종료 중 장애 복구 시험은 없다. GitHub adapter 테스트의 `_call` 대체는 실제 GitHub 인수 증거가 아니다.

## 제안 계약 — 아직 미구현

PG에 티켓 개정·content hash·해결 commit·모든 인수 기준의 결과·불변 증거 및 검토 결정을 결속한 종료 결정을 먼저 기록한다. GitHub 반영은 별도 pending 작업으로 재개하며 실제 원격 상태를 확인한 뒤 synced로 기록한다. `resolved_pending_sync`와 원격 확인 완료를 구분하고 재시도로 종료 결정을 중복 생성하지 않는다.

close/reopen 요청은 기대 개정과 기대 상태를 검사한다. 오래된 승인·누락된 기준·실재하지 않는 증거·실패/unknown/skip을 완료 근거로 받아들이지 않는다. 사람이 필요한 인수는 모델이 쓴 actor 문자열로 대체하지 않는다. 원격 수동 종료는 관측으로 남기고 로컬 완료를 위조하지 않는다. 충돌 및 생성 불확실성은 기록된 근거와 명시적 조정으로 처리한다.

실제 검증에는 PG commit 실패 전후, GitHub ACK 유실, 재시도/중복, 동시 close/reopen, 중간 개정 변경, 외부 제목/본문/상태 수정, lease 만료 후 늦은 응답을 포함한다. 실제 PG와 승인된 별도 GitHub 시험 이슈로 전체 흐름을 확인해야 한다. 열린 개선 이슈를 시험 삼아 닫지 않는다.

구현 전 실제 Claude 공동 검토와 SDD 설계를 진행한다. 이 문서 자체는 기능 구현 또는 인수 통과 증거가 아니다.
