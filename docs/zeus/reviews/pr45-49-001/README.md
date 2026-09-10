# Codex 독립 PR 검토 #45–#49

검토 대상을 #49까지 고정했습니다. 각 JSON의 headRefOid 기준이며 이후 개정은 재검토가 필요합니다.

| PR | 판정 | 독립 관련 검사 | 발견 / 수용 범위 |
|---|---|---|---|
| #45 | 변경 요청 | 73 passed | 최종 compiler에서 생략된 본문을 delivery.full=1로 집계 |
| #46 | 변경 요청 | 24 passed | 임의 영수증으로 human_scope PASS, 제공자 미검증, foreign run 철회가 현재 PASS 제거 |
| #47 | 병합 | 21 passed | replay 초안에 spec/scenario/oracle/requirement 귀속 |
| #48 | 변경 요청 | 28 passed | 서로 다른 로컬 Git 저장소 모두 local로 취급, 다른 저장소 병합 허용 |
| #49 | 변경 요청 | 61 passed | 중첩 손상 이벤트 누락/정상 상태 갱신, 실제 CI에서 수집 시각 동등성 실패 |

#47 main 결합 검증: Ruff 통과, `930 passed, 306 skipped in 229.78s (0:03:49)`, tree `f4619377257db79779f88d03bfe84942605a07a7`. 실제 병합 트리와 일치 확인.
각 관련 검사에는 실제 PostgreSQL이 필요한 경로를 활성화했습니다. 전체 Windows 회귀의 skip은 통과가 아닙니다.

반례 스크립트는 제어된 입력과 실제 compiler/application/ledger/local Git을 사용합니다. #49의 이벤트 공급원은 fixture입니다.
모델 행동, 사람 승인, 실기기 실행, 운영 배포를 측정한 것으로 표시하지 않습니다. #47 또한 미실행 검토용 초안 생성 범위입니다.

각 PR에 COMMENT review로 판정을 게시했습니다. 동일 GitHub 계정은 자기 PR에 공식 Request changes/approval을 할 수 없습니다.
기존 #36–#44 결과와 합쳐 이번 검토는 14건 중 4건(#40/#41/#42/#47) 병합, 10건 수정 요청입니다.
이슈 전체 인수를 자동 승인하지 않았으며 재부팅/호스트 주기 검증은 수행하지 않았습니다.

파일별 해시는 manifest.json에 기록합니다. 49-ci-review.md는 실제 GitHub 실패 로그를 링크하고 원인을 설명합니다.
원본 CI 전체 로그는 private runtime에 보관하고 이 디렉터리에는 게시한 분석만 포함합니다.
