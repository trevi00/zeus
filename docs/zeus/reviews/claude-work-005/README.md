# Claude 수정 PR 재검토 005

2026-09-10–11. 마지막 보류 PR #50/#55를 재검토하고 Codex의 추가 보완을 포함한 [통합 PR #67](https://github.com/trevi00/zeus/pull/67)로 병합했습니다. 두 PR의 수정 이력을 그대로 보존했습니다.

- [#50 상세](50-review.md): 무관한 reviewer 실행과 거절→승인 변조는 Claude 수정으로 차단됐습니다. 추가 발견한 제외 승인자·revision·사유 변조는 Codex가 보완했습니다.
- [#55 상세](55-review.md): 활성 reference와 annotation 우회는 Claude 수정으로 차단됐습니다. 정상 정의 이름을 annotation으로 오인하는 문제는 Codex가 보완했습니다.

## 검증

- ruff: `All checks passed!`
- full: `1105 passed, 342 skipped in 301.73s (0:05:01)`
- postgres-targets: `75 passed in 34.29s`

원래 두 PR의 대상 테스트도 각각 23/44개 통과 및 Ruff 통과였습니다. Codex가 추가한 회귀 테스트는 보완 전 6 failed, 1 passed, 3 skipped로 문제를 재현했습니다(`boundaries-before.log`). 제외 근거 변조 3가지와 정상 schema 이름 3가지가 실패했습니다. 보완 후 malformed reviewer 결과 검사도 추가했으며 전체 및 PostgreSQL 대상 스위트에서 실행했습니다. 실제 annotation 참조 거부와 정상 재귀 참조, 무관한 검토 및 명시적 거절 반례도 유지됩니다.

통합 head `7c4d69a`의 CI 10/10 SUCCESS 후 병합했습니다. 병합 커밋 `261d1c40b3ae3d4f323d0f65f65d2828d8e66815`의 tree `d21d034c5a75b896f56522af2625901e7d1c2ec1`는 로컬 검증 tree와 일치합니다. `integration-pr-ci.json`, `integration-merge.json`, `merges.json` 참조.

## 범위와 종료 조건

이번 수용은 Codex 보완을 포함한 결합 결과에 대한 판정이며 원본 두 head에 결함이 없었다는 뜻이 아닙니다. 제품 소스 변경은 reviewer 결과 검증과 schema 위치 판별 두 곳이고 계약 문서 충돌은 양쪽 내용을 보존했습니다.

테스트 fixture는 실제 모델·사람 인수나 운영 배포 증거가 아닙니다. reference 저장소 전체 의미 분석이나 기존 로컬 full-analysis 미커밋 자료의 전체 검토를 완료했다고 주장하지 않습니다. 기존 로컬 변경은 보존했습니다. 기존 33개 이슈는 별도의 신뢰된 종료 증거 조건이 남아 OPEN으로 유지하며 이번 코드 수용 결과를 로컬 티켓과 GitHub에 동기화합니다.
