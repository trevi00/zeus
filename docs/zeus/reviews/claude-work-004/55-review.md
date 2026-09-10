# PR #55 재검토 004: 변경 요청 / 병합 보류

검토 head: `bc807478232963d2664839b411c225f92eca7ccf`

[P1] 실제 schema 위치의 중첩 $schema는 거부하지만 $ref 대상이 annotation 데이터이면 검증을 우회합니다. examples[0]에 draft-07 $schema + prefixItems(integer)를 넣고 properties.x.$ref="#/examples/0"으로 참조하면 x=["not-an-integer"]를 checked로 승인하고 receipt에는 2020-12를 기록합니다. 일반 annotation 데이터는 그대로 허용하되 참조되어 실행되는 schema에는 동일한 preflight를 적용하거나 annotation/외부/지원하지 않는 참조 대상을 명시적으로 거부해야 합니다. 모든 활성 $ref를 순환 안전하게 해석하고 동일한 resolution 범위를 validator에도 적용해야 합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/bc807478232963d2664839b411c225f92eca7ccf/src/codex_harness/adapters/output_schema.py)

독립 대상 테스트: `44 passed in 20.17s`, Ruff 통과. 최초 확인 시 CI 10/10 SUCCESS였습니다. 실 PostgreSQL 모드로 대상 테스트를 실행했으며 모든 테스트가 DB를 사용하는 것은 아닙니다. #59/#60의 전체 seam 테스트는 통합 검증에도 포함합니다.

반례 코드와 결과는 [검토 보고서](https://github.com/trevi00/zeus/tree/main/docs/zeus/reviews/claude-work-004)에 보존합니다. 합성 fixture를 통한 소스 동작 검증이며 실모델·사람 인수·운영 완료 판정이 아닙니다. 연결 이슈의 종료 증거는 별도로 충족해야 합니다.
