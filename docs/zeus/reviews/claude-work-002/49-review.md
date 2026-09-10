# PR #49: 변경 요청 / 병합 보류

검토 head: `f055fafdcf15774655dae16e6fde42edb3007adb`. Codex 독립 검토입니다.

**[P2] 중첩 event shape가 아직 검증되지 않습니다**

실제 Executor/원장에 fixture transport event를 공급하면 method=[]가 TypeError로 실행을 끊습니다. item="garbage"는 sequence를 증가시키고 malformed_events=0으로 기록됩니다. 실제 모델 실행 증거는 아닙니다. clock 수정은 통과했지만 이전 지적의 malformed 경로는 그대로입니다.

위치: [src/codex_harness/adapters/executor.py:248](https://github.com/trevi00/zeus/blob/f055fafdcf15774655dae16e6fde42edb3007adb/src/codex_harness/adapters/executor.py#L248)

수정·재검증 조건: method 문자열, params/item 객체와 event별 필수 식별자를 먼저 검증하고 malformed 이벤트가 progress를 전진시키지 않도록 하세요.

검증: 해당 head의 대상 검사 **40 passed in 19.34s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
