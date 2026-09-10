# Claude 수정 PR 재검토 003

2026-09-10. 수정된 15개 PR의 고정 head를 각각 검토했습니다. 9건을 통합 PR #65로 병합했고 6건은 반례가 남아 보류했습니다. CI 성공만으로 수용하지 않았습니다.

| PR | 판정 | 근거 |
|---|---|---|
| [#46](https://github.com/trevi00/zeus/pull/46) | 수용·병합 | [상세](46-review.md) |
| [#49](https://github.com/trevi00/zeus/pull/49) | 수용·병합 | [상세](49-review.md) |
| [#50](https://github.com/trevi00/zeus/pull/50) | 변경 요청 | [상세](50-review.md) |
| [#51](https://github.com/trevi00/zeus/pull/51) | 수용·병합 | [상세](51-review.md) |
| [#52](https://github.com/trevi00/zeus/pull/52) | 수용·병합 | [상세](52-review.md) |
| [#54](https://github.com/trevi00/zeus/pull/54) | 변경 요청 | [상세](54-review.md) |
| [#55](https://github.com/trevi00/zeus/pull/55) | 변경 요청 | [상세](55-review.md) |
| [#56](https://github.com/trevi00/zeus/pull/56) | 수용·병합 | [상세](56-review.md) |
| [#57](https://github.com/trevi00/zeus/pull/57) | 수용·병합 | [상세](57-review.md) |
| [#58](https://github.com/trevi00/zeus/pull/58) | 수용·병합 | [상세](58-review.md) |
| [#59](https://github.com/trevi00/zeus/pull/59) | 변경 요청 | [상세](59-review.md) |
| [#60](https://github.com/trevi00/zeus/pull/60) | 변경 요청 | [상세](60-review.md) |
| [#61](https://github.com/trevi00/zeus/pull/61) | 수용·병합 | [상세](61-review.md) |
| [#62](https://github.com/trevi00/zeus/pull/62) | 수용·병합 | [상세](62-review.md) |
| [#63](https://github.com/trevi00/zeus/pull/63) | 변경 요청 | [상세](63-review.md) |

## 검증

각 PR의 변경 테스트 및 관련 회귀 테스트를 실제 PostgreSQL 통합 모드에서 독립 실행했고 모두 통과했습니다. 수용 9건을 합친 source tree `a7e11c4981ff50bb8db540199a2a49f588c6c125`의 결과:

- ruff: `All checks passed!`
- full: `1055 passed, 327 skipped in 337.76s (0:05:37)`
- postgres-targets: `293 passed in 163.79s (0:02:43)`

[통합 PR #65](https://github.com/trevi00/zeus/pull/65)의 Windows/Linux/integration CI 10개 check가 모두 성공한 뒤 head를 고정해 병합했습니다. 병합 커밋 `1d3cc6ea375382ec85eedde2976337e6d2489295`의 tree는 위 로컬 검증 tree와 일치합니다. `integration-pr-ci.json`, `integration-merge.json`, `merges.json` 참조.

#51과 #52의 executor 변경을 함께 적용하면서 충돌을 해결했습니다. capacity 거부 시 half-open probe를 소비하지 않고 breaker 거부 시 invocation 예약을 회수하도록 수정했으며 두 회귀 테스트를 추가했습니다. 원래 9개 PR의 commit ancestry를 유지했습니다.

#57은 이 PC에서 실제 Docker Compose PostgreSQL/Redis를 사용하는 ReleaseRunner 경로로 재실측했습니다. 연결 테스트 통과 뒤 의도적인 incumbent 계약 실패가 rejected를 만들었고 서비스 진입/정리 각 1회, 잔여 컨테이너 없음, 후속 단계 생략을 확인했습니다. `57-docker.json` 참조. MemoryStore의 review 전제는 fixture이며 실제 모델·사람 승인 또는 운영 배포 증거가 아닙니다.

## 보류 사유와 재현

- #50: artifact 내용과 reviewer 실행을 확인하지 않아 권위가 생깁니다. 기대 시나리오 검사도 생략할 수 있습니다.
- #54: 환경값 변경 후에도 기존 통과 캐시를 재사용합니다.
- #55: 중첩 dialect 선언이 schema 검증을 우회합니다.
- #59, #60: timestamp 동률에서 최신 revision이 프로세스 hash seed에 따라 달라집니다.
- #63: observed_at 문자열이 개인정보 검사 없이 model input으로 전달됩니다.

`probes.py.txt`와 PR별 `*-probe.json`에 실행 반례를 보존했습니다. 스크립트의 checkout 경로를 각 고정 head에 맞추고 해당 venv Python으로 PR 번호를 인자로 실행합니다. #59/#60은 PYTHONHASHSEED=1,2,3을 각 자식 프로세스에 지정합니다. 환경 변경은 자식 프로세스 안에 한정되며 host clock을 변경하지 않았습니다.

검토 범위는 15개 수정 PR과 결합 동작입니다. 기존 로컬 full-analysis 미커밋 산출물은 보존했으며 그 전체 의미 분석을 완료했다고 주장하지 않습니다. 로컬 티켓 review와 GitHub Issues에는 PR 수용 여부 및 남은 조건을 동기화합니다. 이슈 종료에는 별도의 신뢰된 closure evidence가 필요하므로 기존 33개 이슈는 OPEN으로 유지합니다. 재부팅·host interruption 운영 실측도 이번 검증에 포함하지 않습니다.

원본 stdout, 고정 head, CI, 게시 readback 및 sync receipt를 이 디렉터리에 보존합니다. 합성 반례를 실모델/사람 인수로 해석하면 안 됩니다.

15건 모두 PR 리뷰 게시 후 commit/body readback을 검증했고, 로컬 advisory review와 연결 GitHub Issues 동기화를 완료했습니다(`github-reviews.json`, `ticket-sync.json`). 기존 33개 이슈는 모두 OPEN이고 보류 6개 PR의 head도 검토한 값과 일치합니다(`final-open-state.json`). 이 환경의 `ZEUS_TICKET_TRUST_COMMIT`은 설정되지 않았으며 검수자가 새 종료 권위를 임의로 만들지 않았습니다.

병합 전 CI 10/10 성공 및 병합 tree 일치는 확인했습니다. 병합 후 main에 자동 시작된 [CI](https://github.com/trevi00/zeus/actions/runs/34480807476)는 별도 실행이며, 이 보고서 게시 시점의 상태는 `merged-main-ci.json`에 기록합니다. 뒤이은 문서 전용 커밋은 `[skip ci]`입니다.
