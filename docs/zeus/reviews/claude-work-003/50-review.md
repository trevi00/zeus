# PR #50 재검토 003: 변경 요청 / 병합 보류

검토 head: `ac436349760d09f7833c2e031a8b1486fbc2e6fa`

[P1] 파일 존재와 호출자 문자열만으로 완료 권위를 만들 수 있습니다. 실행·평가 artifact 내용이 fixture label뿐이고 실제 reviewer/provider 호출이 0회여도 require_authority가 authoritative=true를 반환했습니다. expected_scenarios를 생략하면 스펙 시나리오 완전성 검사도 생략됩니다. 실행/평가 내용의 task·attempt·spec 결합과 검증된 reviewer 실행을 확인하고 스펙에서 기대 시나리오를 필수로 도출해야 합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/ac436349760d09f7833c2e031a8b1486fbc2e6fa/src/codex_harness/application/completion.py)

독립 검증: `23 passed in 18.87s`; Ruff 통과. PostgreSQL 통합 모드를 켜고 해당 PR 변경 테스트와 관련 회귀 테스트를 실행했습니다. CI 10/10 성공도 확인했습니다.

검증 범위는 이 PR의 변경과 이전 반례 및 추가 경계 조건입니다. 저장소 전체·실모델·사람 인수·운영 배포 완료 판정은 아닙니다. 이슈 종료 권위는 별도이므로 OPEN을 유지합니다.
