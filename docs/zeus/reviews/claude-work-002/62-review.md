# PR #62: 변경 요청 / 병합 보류

검토 head: `571e6cef57df4b817f634fa53d1cfe1db48234c9`. Codex 독립 검토입니다.

**[P2] 다른 config의 precheck 결과를 적용 허용 증적으로 수용합니다**

run.config_hash=A, 실제 stdout.plan.config_hash=B인 receipt를 record한 뒤 require_approved하면 통과합니다. source_revision/environment/tool 비교만으로 어떤 migration config를 검사했는지는 결속되지 않습니다.

위치: [src/codex_harness/application/migration_receipts.py:53](https://github.com/trevi00/zeus/blob/571e6cef57df4b817f634fa53d1cfe1db48234c9/src/codex_harness/application/migration_receipts.py#L53)

수정·재검증 조건: stdout의 operation/config_hash와 제출 binding을 비교하고 소비 시 expected config/root/tool을 요구하세요. 다른 config/root의 성공 receipt 재사용은 거절되어야 합니다.

검증: 해당 head의 대상 검사 **14 passed in 8.12s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
