# PR #54: 변경 요청 / 병합 보류

검토 head: `b2f36cb29430c37e8435c5f90479f3cd758ef1f4`. Codex 독립 검토입니다.

**[P1] 정책 변경 뒤에도 과거 all_checked 캐시가 반환됩니다**

허용된 실제 Python child replay를 검사한 다음 같은 task/revision/claims에 해당 명령을 금지한 정책으로 다시 검사하면 기존 all_checked와 옛 policy_hash가 반환됩니다. 새 inspector를 직접 실행하면 not_checked입니다. cache key에 정책이 없습니다.

위치: [src/codex_harness/application/evidence_inspection.py:33](https://github.com/trevi00/zeus/blob/b2f36cb29430c37e8435c5f90479f3cd758ef1f4/src/codex_harness/application/evidence_inspection.py#L33)

수정·재검증 조건: 정규화한 policy hash와 결과를 결정하는 실행 환경을 identity에 포함하고 require_all_checked에서도 소비 시 요구하는 binding을 검증하세요. 정책 강화/환경 변경 음성 검사를 추가하세요.

검증: 해당 head의 대상 검사 **12 passed in 7.64s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
