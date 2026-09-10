# PR #59 재검토 003: 변경 요청 / 병합 보류

검토 head: `4b715b643eb49e49d0f3cf83e20dd1e10f45b942`

[P2] 같은 recorded_at을 가진 A→B revision에서 기본 view가 set 순서에 의존합니다. PYTHONHASHSEED=1은 B, 2/3은 과거 A를 선택했습니다. 트랜잭션 내 단조 증가 순서 등으로 최신 revision 선택을 결정하거나 명시 revision을 필수화해야 합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/4b715b643eb49e49d0f3cf83e20dd1e10f45b942/src/codex_harness/application/seam_ledger.py)

독립 검증: `10 passed in 1.94s`; Ruff 통과. PostgreSQL 통합 모드를 켜고 해당 PR 변경 테스트와 관련 회귀 테스트를 실행했습니다. CI 10/10 성공도 확인했습니다.

검증 범위는 이 PR의 변경과 이전 반례 및 추가 경계 조건입니다. 저장소 전체·실모델·사람 인수·운영 배포 완료 판정은 아닙니다. 이슈 종료 권위는 별도이므로 OPEN을 유지합니다.
