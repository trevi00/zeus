# PR #51: 변경 요청 / 병합 보류

검토 head: `820d35358eb56f86e41da5689c83f5fba985f8f9`. Codex 독립 검토입니다.

**[P1] 취소된 작업의 예약이 다른 작업의 실행 용량을 영구 점유합니다**

capacity=1에서 작업 A를 reserve하고 worker 중단 후 Workflow.cancel을 적용하면 예약은 reserved로 남습니다. 다른 작업 B의 reserve는 계속 capacity 오류가 납니다. 정리는 같은 task의 다음 attempt에만 있어 재시도 없는 취소/최종 실패에는 도달하지 않습니다.

위치: [src/codex_harness/application/invocation_ledger.py:53](https://github.com/trevi00/zeus/blob/820d35358eb56f86e41da5689c83f5fba985f8f9/src/codex_harness/application/invocation_ledger.py#L53)

수정·재검증 조건: 현재 실행의 생존/종료를 fence와 함께 확인하는 복구 경로를 추가하세요. 중단→취소/최종 실패→다른 작업 admission을 실측하고 usage는 unknown으로 보존해야 합니다.

검증: 해당 head의 대상 검사 **44 passed in 12.30s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
