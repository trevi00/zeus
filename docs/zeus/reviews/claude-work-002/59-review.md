# PR #59: 변경 요청 / 병합 보류

검토 head: `922e8c76152b4e1ad3ff59c447bb7f413f9ce92d`. Codex 독립 검토입니다.

**[P2] 두 번째 소스 revision이 누적되면 seam view를 만들 수 없습니다**

같은 enum의 revision A와 B를 정상 record_observation으로 기록한 뒤 view를 부르면 서로 다른 sources 오류입니다. append-only 원장의 모든 과거 관측/비교를 한 view에 전달하므로 일반적인 반복 개발만으로 영구 실패합니다.

위치: [src/codex_harness/application/seam_ledger.py:100](https://github.com/trevi00/zeus/blob/922e8c76152b4e1ad3ff59c447bb7f413f9ce92d/src/codex_harness/application/seam_ledger.py#L100)

수정·재검증 조건: view 입력을 명시적 release/revision/observation ID로 한정하고 comparison이 참조한 정확한 관측을 선택하세요. 과거 기록 보존과 최신/과거 view 재생성을 함께 검사해야 합니다.

검증: 해당 head의 대상 검사 **10 passed in 1.42s**, Ruff 통과. 개별 대상 검사에 PostgreSQL 통합을 활성화했습니다. 통과 횟수는 파일 간 중복을 포함하므로 고유 테스트 수로 합산하지 않습니다.

실제 모델·사람 인수·실기기·재부팅 검증은 수행하지 않았습니다. PR 수용과 연결 이슈의 완료/종료는 별도입니다.
