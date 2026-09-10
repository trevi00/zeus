# PR #52: 변경 요청 / 병합 보류

검토 head: `ae0f373a6b47d9622a90dfce99fb359b506cbfe9`. Codex 독립 검토입니다.

**[P2] 만료된 half-open probe의 성공 보고가 breaker를 닫습니다**

probe TTL 2초로 예약 후 만료 시각을 지난 now에서 success를 report하면 applied=true, state=closed가 됩니다. 현재 검증은 generation만 비교하며 slot 소유자, 만료, 소비 여부를 재확인하지 않습니다. 호스트 시계는 바꾸지 않고 명시적 now 입력으로 재현했습니다.

위치: [src/codex_harness/application/breaker.py:129](https://github.com/trevi00/zeus/blob/ae0f373a6b47d9622a90dfce99fb359b506cbfe9/src/codex_harness/application/breaker.py#L129)

수정·재검증 조건: report 트랜잭션에서 현재 reservation과 token의 task/generation/attempt/owner 및 만료를 비교하세요. 만료·unknown으로 해제된 token의 후속 성공은 무효로 처리해야 합니다.

검증: 해당 head의 대상 검사 **68 passed in 26.73s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
