# PR #60: 변경 요청 / 병합 보류

검토 head: `a321c70b0d04ac7f65ca591e7bd2ad19386c57e1`. Codex 독립 검토입니다.

**[P2] 선행 seam 추출·view 결함이 수정되지 않은 상태입니다**

required scopes와 byte identity 분리는 유용하지만 #56의 AnnAssign 누락/HIGH 반례가 이 head에서도 재현됩니다. #59의 전체 과거 관측 혼합 경로도 상속합니다. 따라서 complete scope가 실제 누락을 검증한 것으로 해석될 수 있습니다.

위치: [src/codex_harness/adapters/seam_extraction.py:66](https://github.com/trevi00/zeus/blob/a321c70b0d04ac7f65ca591e7bd2ad19386c57e1/src/codex_harness/adapters/seam_extraction.py#L66)

수정·재검증 조건: 선행 #56/#59 수정본에 rebase한 뒤 멤버 분모와 두 revision view 시나리오를 포함해 scope gate를 재검증하세요. 이 PR만 먼저 병합하지 않습니다.

검증: 해당 head의 대상 검사 **9 passed in 1.05s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
