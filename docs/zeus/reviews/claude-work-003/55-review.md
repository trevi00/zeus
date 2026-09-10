# PR #55 재검토 003: 변경 요청 / 병합 보류

검토 head: `5fbb7a4b4797f556d622a3e4043b11ed66d74ef4`

[P1] 중첩 $schema 선언으로 dialect 제한을 우회합니다. properties.x에 draft-07 $schema와 prefixItems integer를 함께 선언하면 x=["not-an-integer"]를 checked로 승인하면서 receipt에는 2020-12를 기록합니다. schema 위치의 중첩/$defs/$ref 대상 dialect를 일관되게 검증해야 합니다. 예제 annotation 객체와 실제 schema는 구분해야 합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/5fbb7a4b4797f556d622a3e4043b11ed66d74ef4/src/codex_harness/adapters/output_schema.py)

독립 검증: `44 passed in 22.10s`; Ruff 통과. PostgreSQL 통합 모드를 켜고 해당 PR 변경 테스트와 관련 회귀 테스트를 실행했습니다. CI 10/10 성공도 확인했습니다.

검증 범위는 이 PR의 변경과 이전 반례 및 추가 경계 조건입니다. 저장소 전체·실모델·사람 인수·운영 배포 완료 판정은 아닙니다. 이슈 종료 권위는 별도이므로 OPEN을 유지합니다.
