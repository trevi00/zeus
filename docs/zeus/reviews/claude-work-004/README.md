# Claude 수정 PR 재검토 004

2026-09-10. 이전에 보류한 6개 PR의 새 head를 고정해 검토했습니다. 4건은 통합 PR #66으로 병합했고 #50과 #55는 추가 반례가 재현되어 보류했습니다.

| PR | 판정 | 근거 |
|---|---|---|
| [#50](https://github.com/trevi00/zeus/pull/50) | 변경 요청 | [상세](50-review.md) |
| [#54](https://github.com/trevi00/zeus/pull/54) | 수용·병합 | [상세](54-review.md) |
| [#55](https://github.com/trevi00/zeus/pull/55) | 변경 요청 | [상세](55-review.md) |
| [#59](https://github.com/trevi00/zeus/pull/59) | 수용·병합 | [상세](59-review.md) |
| [#60](https://github.com/trevi00/zeus/pull/60) | 수용·병합 | [상세](60-review.md) |
| [#63](https://github.com/trevi00/zeus/pull/63) | 수용·병합 | [상세](63-review.md) |

## 검증

- ruff: `All checks passed!`
- full: `1080 passed, 330 skipped in 347.07s (0:05:47)`
- postgres-targets: `39 passed in 9.29s`

통합 PR #66의 Windows/Linux/integration CI 10/10 성공 후 병합했습니다. 검증 tree `3bf80cde895f26c1a8c0f5fc92b5102bf441b672`와 병합 커밋 `a99d827b6cb683ace530d9aa89f8b4e919d378e7`의 tree가 일치합니다. 문서 충돌은 양쪽 계약을 보존하여 해결했고 별도 제품 코드 수정은 없습니다.

이전 LANG 환경값 변경, timestamp 동률 seed 1/2/3, observed_at 개인정보 반례를 새 head에서 실행해 #54/#59/#60/#63의 수정 효과를 확인했습니다. Python 도구 identity는 버전·구현·실행 경로 digest 범위이며 모든 외부 바이너리의 지문을 확인한다는 뜻이 아닙니다. sequence 없는 과거 관측의 실제 기록 순서는 복구할 수 없으며 fallback은 timestamp/id입니다.

PostgreSQL 대상 목록 작성 때 test_seam_scopes.py라는 잘못된 파일명을 사용한 실행은 collection 전에 종료되었습니다. 원본은 `integration-invocation-error.json`/`integration-invocation-error.log`에 보존했습니다. 실제 파일 test_seam_scope.py로 실행한 성공 결과를 별도로 확인했으며 전체 테스트를 불필요하게 반복하지 않았습니다.

## 남은 결함

- #50: 다른 target을 검토한 succeeded reviewer task를 참조하는 caller evaluation으로 현재 작업이 authoritative가 됩니다. 기대 시나리오를 명시해도 우회됩니다. reviewer 실행의 검증된 출력과 대상·판정 사이의 결속이 필요합니다.
- #55: annotation의 examples[0]이 $ref 대상으로 사용되면 preflight를 거치지 않는 활성 schema가 됩니다. 중첩 draft-07 선언으로 prefixItems 검사를 무력화하면서 2020-12 checked receipt를 발행합니다.

`probes.py.txt`는 두 새 반례, `previous_probes.py.txt`와 `check_previous.py.txt`는 수용 4건의 이전 반례 재실행 코드입니다. 각 script의 checkout 경로를 PR별 고정 head에 맞추고 해당 venv Python으로 실행합니다. 결과는 PR별 `*-probe.json`에 있습니다. 실행 fixture는 실제 모델/사람 인수 증거가 아니며 운영 배포·재부팅 검증도 이번 범위가 아닙니다.

기존 로컬 full-analysis 미커밋 자료는 보존했습니다. 이번 검토 범위는 수정된 6개 PR과 결합 동작이며 전체 reference 저장소 의미 분석 완료 판정이 아닙니다. 로컬 티켓과 GitHub 이슈에 판정 및 남은 조건을 기록하고, 신뢰된 종료 증거가 별도로 필요한 기존 33개 이슈는 OPEN으로 유지합니다.
