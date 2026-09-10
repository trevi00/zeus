Codex 독립 검토 — **변경 요청 / 병합 보류**

대상 `8a7cab51f712f2ed225973c991d14b18caa579dd`

[P2] 최종 컴파일에서 생략된 본문을 delivery.full로 집계합니다.

`adapters/skill_history.py:_prepare_history`는 선택 매니페스트의 tier를 복사하지만, Executor는 그 뒤 `compile_context`에서 예산에 따라 스킬을 생략합니다. `record_history`는 최종 packet.evidence를 반영하지 않습니다. 실제 compiler+원장에 50,000자 full 스킬과 22,000-byte 예산을 넣은 대조에서 `included_ids=[]`인데 감사는 `delivery.full=1`을 반환했습니다. 실제 모델 실행이 아닌 제어된 컴파일·저장 재현입니다.

요청: 최종 packet에서 admitted/omitted를 계산해 기록하고, 선택 단계 tier와 최종 컨텍스트 포함을 구분하세요. 제공자 제출/수신 전 기록을 실제 모델 도달로 표현하지 말고 각 증거 단계와 한계를 명시하세요. 예산 생략·본문 advisory 변환·실행 실패 경로를 회귀에 포함해야 합니다. 현재 변경으로 'body arrival' 정확성을 승인할 수 없습니다.

독립 관련 검사: `73 passed in 12.39s` (실제 PostgreSQL 사용이 필요한 검사에는 현재 로컬 PG 연결). 제출 검사가 통과해도 위 반례는 미포함입니다.

동일 GitHub 계정의 PR에는 공식 Request changes가 불가능하므로 COMMENT review로 판정을 남깁니다. 이슈 종료나 인수 승인으로 해석하지 않습니다.
