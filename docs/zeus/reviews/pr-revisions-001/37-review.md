Codex 수정본 독립 재검토 — **이전 지적 해결, 명시 범위 수용 / 병합 가능**

대상 `16c05c2f4748b4cc54717496b5e4c0305b30387e`.

task/decision/release 기존 handle의 쓰기에서 durable fence를 대조합니다. 실제 PG에서 gen1 행만 복원하고 fence2를 유지한 뒤 heartbeat/complete/fail 모두 거부되고 전체 원장 불변인 것을 독립 재현했습니다. fence가 아예 없는 레거시 행을 허용하는 정책은 명시된 예외이며, 전체 DB 백업 롤백이나 운영 재부팅 보호까지 주장하지 않습니다.

독립 관련 검사 `162 passed, 1 skipped in 40.39s`. #37/#43/#44를 현재 main에 함께 결합한 Ruff와 Windows 전체 회귀 `950 passed, 310 skipped in 220.86s (0:03:40)` 통과, 검증 tree `d18c8b2ca94e2a5913c37e4da7a522931e999b5b`. PR별 CI 10개 성공, 자동 이슈 종료 연결 없음. Skip은 PASS가 아닙니다.

이 판정은 해당 코드의 수용이며 연결 이슈 전체 인수/종료 및 운영 배포 승인이 아닙니다. 실제 모델/실기기/호스트 재부팅을 추가 측정하지 않았습니다.
