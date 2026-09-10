# PR #58: 변경 요청 / 병합 보류

검토 head: `ffe49cac4e3e757e71c618b8fa281703616ab58f`. Codex 독립 검토입니다.

**[P1] 새 실행 판정의 실패가 기존 승인 소비자에 전달되지 않습니다**

pytest stdout="3 skipped in 0.02s", rc=0이면 새 classifier는 passed=false/empty_check입니다. 그러나 category=executed라 receipt는 exit_status=0, inspection_blocked=false입니다. Research의 승인 조건은 이 두 값만 보므로 성공으로 취급합니다. 선행 #57도 배포 검증 이중 진입 문제가 있습니다.

위치: [src/codex_harness/adapters/source_execution.py:139](https://github.com/trevi00/zeus/blob/ffe49cac4e3e757e71c618b8fa281703616ab58f/src/codex_harness/adapters/source_execution.py#L139)

수정·재검증 조건: passed/outcome을 ExecutionReceipt 및 승인 소비자까지 결속하세요. all-skip·빈 출력·stderr-only의 실제 runner→receipt→Research 승인 거부 통합 검사가 필요합니다.

검증: 해당 head의 대상 검사 **7 passed in 5.95s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
