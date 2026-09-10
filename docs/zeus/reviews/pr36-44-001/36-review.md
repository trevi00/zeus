Codex 독립 검토 — **변경 요청 / 병합 보류**

대상: `833cc4a0e649f89a766daf3492e92fae87dc2d65`

**[P2] 동일 바이트의 관측 근거를 갱신할 수 없는 ID 충돌**

위치: `domain/experience.py:101, application/experience.py:15–25`

같은 source/path/bytes를 먼저 observed로 기록한 뒤 pinned(commit A)로 기록하면 ID는 같지만 source.kind/revision이 달라 `Experience claim ID reused with different content`로 거절됩니다. pinned(commit A)→pinned(commit B)의 동일 파일도 같은 문제입니다. 독립 반례에서 같은 ID와 정상적인 근거 전환 거절을 확인했습니다.

수정 요청: 불변 콘텐츠 claim과 관측/커밋별 취득 근거를 분리하거나, ID/버전 정책에 근거를 일관되게 결속해 주세요. 같은 바이트 재수집으로 독립 사건 수를 늘리지 않으면서 observed→pinned 및 서로 다른 pinned revision을 보존하는 테스트가 필요합니다.

제출된 관련 테스트는 독립 실행에서도 통과했지만 위 경계 반례는 포함하지 않습니다. 반례는 격리된 검증 데이터로 실행했으며 운영 인수·실제 모델 실행으로 표시하지 않습니다. 기존 이슈에서 수정해 주세요. 새 이슈를 만들거나 이 PR/연결 이슈를 종료하지 않습니다.

GitHub ??? ???? ?? ?? Request changes? ???? ????. ? ?? ??? ??? ?? ???? ?? ?????.
