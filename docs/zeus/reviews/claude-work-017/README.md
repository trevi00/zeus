# PR #72 3차 검토: U002 코드 수용

대상 `02f5a596d027f61c89b06613b84c2c6d93d1c5d7`, 런타임 `1df79723d087d98ad46ce08f31cf9b254410be82`. 이전 R1 잔여의 실패 정리를 수용한다. 앞서 수용한 R2/R3/R4 및 검토 폴더 lint 예외를 유지한다. 이번 변경과 기존 반례 회귀 범위에서 병합을 막는 잔여 결함을 찾지 못했다.

## R1 판단

Job 배정에 실패한 프로세스도 Popen이 소유한 handle로 직접 kill하고 wait로 종료를 확인한다. 실제 CREATE_SUSPENDED 생성에 `_assign=False`만 주입한 독립 반례를 재실행했으며, 이전 `still_alive_after_refusal=[true]`가 `[false]`로 바뀌었다. 생성 전체를 스텁으로 바꾼 검사가 아니다.

종료 증명이 없으면 TreeOwnershipLeak으로 구별하고 adapter가 on_enter를 호출해 기존 U001의 미확정 실행 차단·reconcile 경로로 전달한다. 성공적으로 정리한 거절은 재시도 가능 상태를 유지한다. 파이프는 실패 정리 경로에서 닫힌다. 새 회귀는 실제 assign/resume 실패와 종료 증명 상실의 의미, executor 차단 및 재호출 거절을 검사한다.

## 검증

- 독립 Windows PostgreSQL+Redis 검사: integration.log 및 integration-result.json에 정확한 결과와 정리 완료 기록. 모델 transport는 프로토콜 시험 자식이며 실제 Claude 호출이 아니다.
- Ruff 전체 통과. 독립 ownership_failure.py가 실제 Windows 실패 경계의 안전 결과를 확인했다.
- 최종 CI 10/10 SUCCESS. push run 34909372939는 attempt 1, pull_request run 34909374419는 attempt 2 성공. PR 첫 시도의 integration 실패를 ci-first-attempt.json에 보존했다. 재실행 없이 통과했다고 표현하지 않는다.
- environment-runs-010의 단계별 stdout/stderr hash, JUnit byte hash, identity_stable을 확인했다. 영수증 head와 최종 head 사이 src/scripts/uv.lock 차이 없음.
- 제출 전체 수치: Windows 1699 passed/14 skipped, WSL 1702 passed/11 skipped, disposable Docker 각각 17 passed. 이번 독립 전체 스위트 재실행 수치가 아니다. Windows 전용 Job 경계 3건의 WSL skip을 결함 은폐나 Linux 실측으로 바꾸지 않는다.
- 검토 도중 영수증 검사 스크립트가 이전 environment-runs-009를 가리켜 코드 일치 단언에 실패했다. 참조를 최신 010으로 바로잡고 재검증해 통과했다. 이 실패는 제출 코드/영수증의 결함이 아니다.

## 수용의 범위와 다음 운영 단계

이 판단은 U002 코드·프로토콜·프로세스/원장 경계 수용이다. 기존 실제 Claude 호출 2건은 이전 구성의 Windows 증거이며, 이번 검토의 신규 모델 호출은 0회다. WSL native Claude 호출·운영 전환·지식 자동 승격을 완료했다고 판단하지 않는다.

다음은 이미 정한 Windows 제한 운영 구성 검증이다. 수정 수용 뒤 별도 캠페인에서 restricted를 켠 작은 임시 작업 **추가 1회, 300초, USD 1 provider 예산 설정, 자동 재시도 0회**를 검증한다. 기존 호출 슬롯을 삭제하거나 label/out을 바꿔 한도를 우회하지 않는다. 이 검증을 통과한 구성으로 작은 Zeus 개선 티켓 1개, 동시 작업 1개, Codex 검토·병합 방식의 제한 운영을 시작한다. 이번 PR 병합 자체로 운영 설정을 켜지는 않는다.

WSL Docker readiness의 제출 실패 누적 4/8은 해결되지 않은 별도 환경 문제로 유지한다. 정상 스택 준비 확인 없이 실작업을 시작하지 않는다. #20 전체 모델 자격·전역 예산, #17 전체 로그/중단/인수 조건, #1/#11 전체 자산 분석은 이 코드 병합만으로 종료하지 않는다. 이슈 댓글·로컬 원장에 수용 범위를 기록하며 U003은 아직 착수하지 않는다.

Independent Windows isolated PostgreSQL + Redis: **255 passed, 0 skipped in 144.05s**. Disposable stack cleanup completed.
