# PR #50 재검토 004: 변경 요청 / 병합 보류

검토 head: `ffe395a135a9b772831af6f6b4c0c1db80052840`

[P1] reviewer의 succeeded task를 확인하지만 그 실행이 현재 target/spec/평가 결과를 검토했는지는 확인하지 않습니다. 실제 Workflow로 다른 작업(unrelated-task-never-this-target)을 검토한 reviewer task를 완료시키고, 호출자가 만든 현재 작업의 evaluation artifact에 그 execution_ref를 연결했습니다. expected_scenarios까지 명시했는데 require_authority가 authority=true를 반환했습니다. reviewer execution의 검증된 출력에서 대상 task/generation/attempt/spec, 시나리오 결과 및 판정을 도출·검증해야 합니다. 임의 evaluation 문서에서 일방적으로 참조하는 것만으로는 결속이 아닙니다. 현재 실행을 대상으로 한 명시적 거절 결과도 승인으로 바꿀 수 없는 회귀 테스트가 필요합니다.

대상: [소스](https://github.com/trevi00/zeus/blob/ffe395a135a9b772831af6f6b4c0c1db80052840/src/codex_harness/application/completion.py)

독립 대상 테스트: `23 passed in 21.50s`, Ruff 통과. 최초 확인 시 CI 10/10 SUCCESS였습니다. 실 PostgreSQL 모드로 대상 테스트를 실행했으며 모든 테스트가 DB를 사용하는 것은 아닙니다. #59/#60의 전체 seam 테스트는 통합 검증에도 포함합니다.

반례 코드와 결과는 [검토 보고서](https://github.com/trevi00/zeus/tree/main/docs/zeus/reviews/claude-work-004)에 보존합니다. 합성 fixture를 통한 소스 동작 검증이며 실모델·사람 인수·운영 완료 판정이 아닙니다. 연결 이슈의 종료 증거는 별도로 충족해야 합니다.
