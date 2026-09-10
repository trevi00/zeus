# PR #55: 변경 요청 / 병합 보류

검토 head: `fc35ed0dcd9d3a9af31ddb712761b614d88055c6`. Codex 독립 검토입니다.

**[P1] 선언한 JSON Schema dialect와 실제 검증 dialect가 다릅니다**

schema에 $schema=draft-07, type=array, prefixItems=[{type:integer}]를 주고 ["not-an-integer"]를 검사하면 answer가 수용되고 schema=checked입니다. preflight 영수증은 2020-12를 주장하지만 jsonschema.validate가 draft-07을 선택해 prefixItems를 무시합니다.

위치: [src/codex_harness/adapters/execution_output.py:64](https://github.com/trevi00/zeus/blob/fc35ed0dcd9d3a9af31ddb712761b614d88055c6/src/codex_harness/adapters/execution_output.py#L64)

수정·재검증 조건: 지원 dialect를 2020-12로 고정하거나 다른 선언을 거절하고 실제 validator와 영수증을 일치시키세요. 지원 목록의 format도 assertion인지 annotation인지 명시해야 합니다. tool_usage의 params=None 방어도 추가 검토 대상입니다.

검증: 해당 head의 대상 검사 **43 passed in 16.98s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
