# PR #46: 변경 요청 / 병합 보류

검토 head: `318ce36c2e882f8e9e528ad309b63c8ac7631bb0`. Codex 독립 검토입니다.

**[P1] 인증 없는 철회가 거부를 없애고 이전 PASS를 되살립니다**

동일 statement의 authenticated PASS → REJECT 뒤 actor 문자열만 있는 RETRACT를 넣으면 fold complete가 false → true가 됩니다. record_gate_verdict도 retracts가 있으면 provider 검증과 runner receipt 검증을 모두 건너뜁니다. 이전 foreign-run 철회는 수정됐지만 같은 binding의 권한 우회는 남습니다.

위치: [src/codex_harness/application/sdd.py:64](https://github.com/trevi00/zeus/blob/318ce36c2e882f8e9e528ad309b63c8ac7631bb0/src/codex_harness/application/sdd.py#L64)

수정·재검증 조건: 철회도 원 결정과 같은 신뢰 수준의 provider 검증을 요구하고 대상 actor/binding에 결속하세요. 인증 실패·다른 actor·인증된 철회의 양성/음성 검사를 추가해야 합니다.

검증: 해당 head의 대상 검사 **27 passed in 3.85s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
