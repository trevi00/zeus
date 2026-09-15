# PR #73 3차 독립 검토: 잔여 두 건

대상 `6268826ff9bfa9321b9e8b8baeafab23a6bfc4bd`, 런타임 `ed30106e1b3e1f2169fc77a8e1ab93e3671634b4`. 기존 세 경계 수정은 반례로 확인했다. 아래 두 실패 처리가 남아 병합·이슈 종료는 보류한다.

## 확인된 진전

Windows 실제 격리 PG/Redis/Git/프로토콜 자식으로 제출 회귀 33개, Codex 1차 적응 반례 4개, 2차 반례 4개를 실행해 **41 passed, skip 0**. Ruff도 통과했다. 실제 모델 호출 0회. 독립 검증 프로젝트 두 개 모두 잔여 컨테이너 0개.

두 호스트 environment-runs-013의 로그/JUnit hash·identity_stable·최종 head와 런타임 차이 없음 확인. 제공 전체 스위트 수치를 독립 전체 재실행이라고 주장하지 않는다. WSL disposable 이번 통과도 확인했지만 기존 준비 실패를 해결한 것으로 판정하지 않는다.

CI 최종 10개 SUCCESS. 34929000255는 attempt=2, 34928997883는 attempt=1이다. 재실행을 숨기지 않은 기록을 확인했다.

## R1 · P2 · rglob 내부의 열거 거절은 바깥 except에 도달하지 않는다

`swept_evidence`는 `Path.rglob` 호출을 try/except로 감쌌지만, 표준 라이브러리가 내부 디렉터리 열거의 PermissionError를 억제할 수 있다. 실제 artifact 파일을 만든 뒤 그 디렉터리의 **os.scandir**만 PermissionError로 거절시키면, 현재 Python 3.12에서 rglob는 빈 결과를 반환하고 complete=true / no execution artifact가 된다. 제출 회귀는 Path.rglob 자체가 예외를 던지게 바꿔 이 경계를 통과하지 않는다.

파일 열거는 실패를 직접 관측할 수 있는 방식으로 구현한다. 예를 들어 os.scandir 기반 순회에서 각 디렉터리 실패를 기록하거나 명시적 on_error를 사용한다. 루트의 is_dir/is_file 판정에서 접근 불가가 부재로 축약되지 않도록 함께 다룬다. 기존 링크·경로 이탈 정책을 유지한다. 실제 파일은 존재하되 OS 열거가 거절되는 반례와 정상 빈 폴더를 구분하고, 실패 시 incomplete 및 scratch 보존을 요구한다.

검증 한계: 실제 파일 + OS API 경계 오류 주입이다. Windows ACL을 변경한 실측이라고 주장하지 않는다. Path.rglob를 대체하지 않았으므로 오류 억제는 실제 표준 라이브러리 동작이다.

## R2 · P2 · 정산 실패를 기록하고도 러너가 성공으로 종료한다

새 `call_budget_settled=false` / `call_budget_settle_error`는 영수증에 기록되지만 runner_complete는 evidence_complete와 error만 본다. 정산 쓰기를 실패시키면 슬롯은 reserved인데 runner_complete=true, passed=true, exit=0이다. 정산 실패도 러너 전체 완료 판정 및 복구 보고에 반영해야 한다. 기존 슬롯은 보수적으로 계속 집계하며 자동 재호출/슬롯 삭제로 처리하지 않는다.

독립 반례는 운영 원장을 사용하지 않았다. tmp_path 아래 실제 CallBudget 파일 원장을 만들고 예약 분기로 진입시킨 후, execute는 명시적으로 protocol fixture만 사용하도록 고정했다. 실제 PG/Git 작업이 끝난 뒤 시험 원장의 settle만 OSError로 실패시켰다. settle 호출과 reserved 슬롯 존재를 단언하고 위 성공 종료를 재현했다. 실제 모델 호출 및 운영 원장 변경은 0이다.

대조: 같은 실제 시험 원장에서 **보존 실패 + 정산 성공**은 used 상태와 call_budget_settled=true를 확인했고 러너 비정상 종료로 통과했다. 따라서 이전 B의 정상 정산 도달 수정은 수용한다.

제출된 `test_b_the_call_ledger_is_settled_even_when_preservation_throws`는 live 인자의 fixture 모드로 slot=None이고, `settled` 변수에 대한 단언도 없다. 이름과 달리 정산 진입을 증명하지 않는다. 별도 시험 원장으로 reserve→settle 경로에 실제 진입하고 호출/상태를 단언하도록 고친다. 유료 모델을 호출할 필요는 없다.

## 산출물 및 수정 범위

`counterexamples.log/xml`: 41 passed. `final-boundaries.log/xml`: **2 failed, 1 passed**. 후자는 열거 거절, 정산 실패의 안전 단언 실패와 보존 실패 시 정산 성공 대조다. 실패 원인을 바꾸지 않고 보존했다.

Claude는 이 두 경계만 같은 PR에서 수정한다. 이미 수용된 ID·배타적 쓰기·상한/필수 참조 판정·목적지 생성 실패·늦은 수집 예외는 다시 설계하지 않는다. WSL 준비 문제는 별도 명세 유지, U003 착수 없음. 실제 모델 재호출은 요구하지 않는다.
