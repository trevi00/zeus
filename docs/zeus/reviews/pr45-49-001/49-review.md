Codex 독립 검토 — **변경 요청 / 병합 보류**

대상 `5165ca38b0cd5eed0cef82dd9388203086f4048e`

[P2] 손상 이벤트를 보존한다는 새 계약이 dict 내부의 손상에는 적용되지 않습니다.

`adapters/executor.py:observe`의 malformed 검사는 최상위 dict/params dict만 검사합니다. 정상 완료 다음 `{'method': [], 'params': {}}`를 실제 Executor 관측 경로에 주면 집합 membership에서 TypeError로 실행이 중단되고 malformed_events=0입니다. `{'method':'item/completed','params':{'item':'garbage'}}`는 오히려 정상으로 취급해 sequence를 1→2로 올리고 malformed_events=0을 유지합니다.

요청: method 타입과 처리할 이벤트별 item/tokenUsage 구조를 사용 전에 검증하고 손상 입력은 원문·카운트에 보관하되 정상 progress를 바꾸지 않도록 하세요. 위 두 입력과 누락 id/type 등 중첩 손상 회귀가 필요합니다. 재현은 fixture 이벤트 공급원을 실제 Executor/원장에 연결한 계약 검증이며 실제 Codex 앱 서버 측정이 아닙니다.

독립 관련 검사: `61 passed in 30.45s` (실제 PostgreSQL 사용이 필요한 검사에는 현재 로컬 PG 연결). 제출 검사가 통과해도 위 반례는 미포함입니다.

동일 GitHub 계정의 PR에는 공식 Request changes가 불가능하므로 COMMENT review로 판정을 남깁니다. 이슈 종료나 인수 승인으로 해석하지 않습니다.
