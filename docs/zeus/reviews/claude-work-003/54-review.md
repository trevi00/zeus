# PR #54 재검토 003: 변경 요청 / 병합 보류

검토 head: `b1d8d4092a9d2426827d98894931bd419922f8e7`

[P1] 캐시 identity가 환경변수 이름만 포함합니다. 실제 Python replay를 LANG=review-pass에서 통과시킨 뒤 LANG=review-fail로 변경하면 캐시는 all_checked를 반환하지만 새 inspector는 verified_mismatch입니다. replay에 사용한 유효 환경의 값 및 도구 identity를 안전한 digest로 결합하고 같은 snapshot을 실행에 사용해야 합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/b1d8d4092a9d2426827d98894931bd419922f8e7/src/codex_harness/adapters/evidence_inspection.py)

독립 검증: `12 passed in 8.75s`; Ruff 통과. PostgreSQL 통합 모드를 켜고 해당 PR 변경 테스트와 관련 회귀 테스트를 실행했습니다. CI 10/10 성공도 확인했습니다.

검증 범위는 이 PR의 변경과 이전 반례 및 추가 경계 조건입니다. 저장소 전체·실모델·사람 인수·운영 배포 완료 판정은 아닙니다. 이슈 종료 권위는 별도이므로 OPEN을 유지합니다.
