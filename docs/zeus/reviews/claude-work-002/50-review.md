# PR #50: 변경 요청 / 병합 보류

검토 head: `7866032f8d485995f2ead86dc59449f273e37397`. Codex 독립 검토입니다.

**[P1] 존재하지 않는 실행·평가 증적도 completion authority가 됩니다**

worker task를 succeeded로 만든 뒤 실제 receipt/artifact를 하나도 생성하지 않고 형식만 맞춘 runner_receipt digest와 evaluation_artifact를 record하면 inspect가 state=authoritative, authority=true를 반환합니다. 같은 JSON 안의 값 비교는 출처 검증이 아닙니다.

위치: [src/codex_harness/application/completion.py:36](https://github.com/trevi00/zeus/blob/7866032f8d485995f2ead86dc59449f273e37397/src/codex_harness/application/completion.py#L36)

수정·재검증 조건: 독립 runner 원장/불변 artifact 실재와 digest, reviewer 출처 및 승인된 spec의 scenario 분모를 검증하세요. 연결 전에는 claim/advisory로 유지하고 require_authority가 허용하지 않아야 합니다.

검증: 해당 head의 대상 검사 **21 passed in 16.62s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
