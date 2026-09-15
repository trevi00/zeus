# PR #73 2차 독립 검토: 세 경계 수정 요청

대상 head `63de1c5faa751ba0b627d203d77d2f1142a1bc31`, 런타임 `f6e9c05ffa22fc22cd4669d52922ad4971f22d16`. 2026-09-15. 기존 네 반례는 수정 확인했다. 아래 세 경계가 남아 현재 병합·이슈 종료는 하지 않는다.

## 수정 확인

- 이전 Codex 반례 네 건을 새 함수 계약(diff command record/run_id)과 영수증 경로에 맞춰 실행: **4 passed**. 기존 안전 단언은 유지했다. 실패 시 남기는 우리 시험용 scratch만 추가 정리했다. 원본 claude-work-018은 수정하지 않았다.
- PR의 scratch 13개 + runner evidence 12개: **25 passed, skip 0**. 실제 격리 PG/Redis/Git/프로토콜 자식으로 실행했다. 실제 모델 호출 0회. 두 독립 검증용 compose 프로젝트 모두 잔여 컨테이너 0개.
- 같은 라벨의 서로 다른 run ID 두 개를 동시에 보존하여 목적지 분리 및 두 결과의 모든 hash 일치 확인. 동일 이름 배타적 쓰기는 제출 회귀에서 확인했다.
- 전체 Ruff 통과. 최종 head의 CI 두 run(34925768380/34925766290)은 각각 attempt=1/SUCCESS, 총 10개 check 통과.
- environment-runs-012의 Windows/WSL stdout·stderr·JUnit hash, identity_stable, 영수증 head와 최종 head 사이 src/scripts/uv.lock 차이 없음 확인. 전체 스위트는 제공 증거를 검증했으며 독립 전체 재실행이라고 주장하지 않는다.

## A · P2 · 빈 목록 분기가 capped와 필수 참조 검사를 건너뛴다

`scripts/claude_real_call.py:501`에서 entries가 비면 바로 complete=true로 반환한다. 아래 두 검사는 이후에 있어 실행되지 않는다.

1. 실제 artifact를 만들고 sweep cap을 그 크기보다 작게 설정하면 capped=true이지만 선택된 entries는 빈 목록이다. helper는 complete=true와 "no execution artifact"를 반환한다. 반례는 2바이트 파일과 1바이트 상한을 사용하며, 기본 64MiB에서도 모든 파일이 상한보다 크면 같은 분기다.
2. receipt가 execution_ref를 명시하지만 파일이 없고 다른 entries도 없으면 역시 complete=true다. 뒤의 NotPreserved 검사를 우회한다.

비어 있는 **선택 결과**를 실제 증거 부재로 취급하지 않는다. capped·열거 실패·필수 참조 검증을 빈 목록 반환보다 먼저 적용한다. 진짜 빈 scratch의 정상 수용은 유지한다. 이 두 반례는 helper 판정을 검증했으며 정상 실제 모델 실행에서 삭제가 발생했다고 주장하지 않는다.

## B · P2 · 보존 디렉터리 생성 실패가 최종 보고·정산을 건너뛴다

`scratch.py:118`의 destination.mkdir는 예외 처리 밖이고, `call:600`의 preserve_evidence 호출 역시 finally 내부에서 보호되지 않는다. 실제로 `<out>/review-evidence`를 파일이 차지한 상태에서 실제 fixture 작업을 수행하자 FileExistsError가 전파되어 영수증과 복구 보고가 쓰이지 않았다. scratch는 남지만 어디서 복구할지 최종 보고가 없다.

실제 호출인 경우 CallBudget.settle도 이 호출 뒤에 있어 도달하지 못한다(이번 검증은 fixture이며 유료 슬롯은 사용하지 않았다). 최종 receipt write 예외 처리만으로는 이 앞 경계를 보호하지 못한다.

목적지 생성·열거·보존 예외를 구조화된 incomplete로 기록하고 scratch를 보존한다. 원장 정산은 보존 오류와 독립적으로 시도하고, 영수증 쓰기까지 실패하면 비밀 없는 stdout 복구 보고와 비정상 종료를 보장한다. 실제 생성 거절을 회귀로 사용한다.

## C · P2 · 늦은 수집 예외인데 passed=true / exit=0이다

`uncertain = bool(receipt.get("error"))`는 scratch 삭제만 막고 최종 passed에는 반영하지 않는다. 실제 fixture execute를 완료한 뒤 그 반환 경계에서 수집 오류 하나를 주입하면 error가 있고 scratch도 남는데 task_succeeded=true, evidence_complete=true, passed=true, exit=0이다. 이 상태는 execute의 마지막 observer.close/drop 같은 단계가 실패해도 도달할 수 있다.

작업 성공과 사본의 보존 사실은 유지하되, 예상 밖 실행·수집 오류가 있는 러너 전체는 실패로 종료하고 복구 대상을 보고한다. 모든 사본이 보존됐으면 evidence_complete를 억지로 false로 바꿀 필요는 없다. 별도의 runner 완료 판정이 오류를 반영하면 된다. 실제 작업을 생략한 가짜 성공이 아닌, 작업 완료 뒤의 경계 오류 주입으로 검증했다.

## 검증 산출물과 다음 단계

`test_remaining.py`의 안전 결과 네 건은 A의 두 경우, B, C에서 각각 실패했다. **25 passed / 4 failed** 로그와 JUnit을 첨부했다. `test_adapted.py`의 별도 **4 passed**도 첨부했다. 둘을 혼동하지 않는다.

이전 R1/R3의 정상 수정은 다시 설계하지 않는다. Claude는 A/B/C만 같은 PR에서 수정하고 실패 조건의 회귀를 추가한다. WSL readiness는 기존 별도 명세대로 처리하며 이 PR에서 녹색을 얻으려고 재시도할 필요가 없다. 최신 WSL 단계 실패는 확인했고 무인 운영 자격 통과로 취급하지 않는다. U003 착수 없음.
