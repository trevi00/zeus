Codex 독립 검토 — **변경 요청 / 병합 보류**

대상: `7905e192745508b6b634a4608b8cfb345aba524c`

**[P1] durable fence보다 오래된 행의 쓰기가 여전히 허용됨**

위치: `application/execution_fence.py:24–31, application/workflow.py:198 (_owned 및 쓰기 경계)`

실제 PostgreSQL의 별도 스키마에서도 재현했습니다: gen1 작업을 claim → cancel로 fence를 gen2로 전진 → task 행만 과거 running/gen1 값으로 복원하고 fence는 gen2로 유지 → 옛 handle의 heartbeat와 complete가 모두 성공합니다. 최종 상태는 succeeded입니다. 새 claim의 advance만 검사하고 기존 handle의 쓰기는 durable fence를 대조하지 않아, 이 PR이 대상으로 삼은 부분 복원/행 재생성에서 권한이 되살아납니다. 전체 DB 롤백이나 시계 조작이 아닙니다.

수정 요청: heartbeat/complete/fail 및 decision/release의 해당 쓰기 경계에서 현재 행과 durable fence의 세대·소유자 결속을 같은 트랜잭션으로 검증해 주세요. legacy 행과 fence 손상의 처리 정책도 명시하고, MemoryStore 및 실제 PG에서 과거 running 행만 복원하는 실패 대조군을 추가해 주세요.

제출된 관련 테스트는 독립 실행에서도 통과했지만 위 경계 반례는 포함하지 않습니다. 반례는 격리된 검증 데이터로 실행했으며 운영 인수·실제 모델 실행으로 표시하지 않습니다. 기존 이슈에서 수정해 주세요. 새 이슈를 만들거나 이 PR/연결 이슈를 종료하지 않습니다.

GitHub ??? ???? ?? ?? Request changes? ???? ????. ? ?? ??? ??? ?? ???? ?? ?????.
