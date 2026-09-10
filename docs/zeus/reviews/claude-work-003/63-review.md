# PR #63 재검토 003: 변경 요청 / 병합 보류

검토 head: `0235421248867cf0a47b71bbb0f25447e529a7e5`

[P1] 새 observed_at 매핑이 privacy scan을 우회합니다. observed_at="password=UNSCANNED_SENTINEL"이 model input으로 그대로 전달되지만 ready/unchecked=[]이고 checked는 content/project_path/kind뿐입니다. timestamp를 타입 검증·정규화하고 전달되는 모든 텍스트를 검사하거나 잘못된 형태를 거부해야 합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/0235421248867cf0a47b71bbb0f25447e529a7e5/src/codex_harness/domain/profile_privacy.py)

독립 검증: `11 passed in 0.99s`; Ruff 통과. PostgreSQL 통합 모드를 켜고 해당 PR 변경 테스트와 관련 회귀 테스트를 실행했습니다. CI 10/10 성공도 확인했습니다.

검증 범위는 이 PR의 변경과 이전 반례 및 추가 경계 조건입니다. 저장소 전체·실모델·사람 인수·운영 배포 완료 판정은 아닙니다. 이슈 종료 권위는 별도이므로 OPEN을 유지합니다.
