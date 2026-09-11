# PR #71 — U001 4차 검토

검토 head: `25470b823802997ddd0cfdbc2d030fc4f5d83a37`. runtime/test head: `09dbb9e50b290262e7a3500afced81c133282128`.

**이전 네 경계 중 예약 검사(R1), pending-only 알림 복구, 공개 오류 메시지(R4)의 수정은 수용합니다. run 잠금/회수(R3)에 아래 두 결함이 남아 병합은 보류합니다.** 기존 reconcile(R2), 숫자 세그먼트, 알림 ACK 소유권의 수용 판단은 유지합니다. 이미 수용한 부분을 다시 설계할 필요는 없습니다.

## 검증

- 독립 Windows 일회용 Docker PG/Redis: 관측 테스트 일곱 파일 **113 passed, 0 skipped**, 생성한 스택만 정리 완료. fake provider이며 실제 모델 호출 증거가 아닙니다.
- executor/recovery/workflow 기본 회귀: **92 passed, 39 skipped**(integration 환경 미설정), Ruff 통과.
- Windows 실제 파일/잠금 반례 **1개 재현**. WSL 실제 파일/UnixFileLock 반례 **2개 재현**. 반례 성공은 제품 수용 pass가 아닙니다. 시간 경계는 mtime 조작으로 시험했으며 8일간 실행했다고 주장하지 않습니다.
- WSL은 검토 환경에 설치된 lockfile-pinned **filelock 3.32.5**의 순수 Python 소스를 재사용했고, 실제 선택 클래스는 **UnixFileLock**입니다. 패키지 버전/소스 hash를 보존했습니다. Windows 네이티브 모듈을 Linux에서 실행한 것이 아닙니다. 모든 쓰기/삭제는 소유한 임시 디렉터리에서만 수행했습니다.
- 최종 head push/pull_request CI 두 run은 각각 **attempt 1, success**, 총 **10/10 SUCCESS**입니다.
- environment-runs-006 두 영수증의 단계 stdout/stderr hash, JUnit byte hash, identity_stable을 대조했습니다. Windows 1557 passed/14 skipped, WSL 1563 passed/8 skipped, Docker 각 17 passed. runtime head와 최종 head의 src/scripts/uv.lock/pyproject 차이 없음. 이번 검토에서 WSL 전체 스위트를 독립 재실행한 것은 아닙니다.

## R3-A · P1 — 잠금을 얻지 못한 작성자도 다른 작성자의 run을 종료시킴

위치: `src/codex_harness/adapters/observation_spool.py`의 `FileSpool.close`, `SpoolDirectory.run_finished/reclaimable/prune`.

같은 run에 첫 작성자 A가 잠금을 보유한 상태에서 B의 append를 시도하면 올바르게 거절됩니다. 그러나 B가 실패 후 정상적인 cleanup인 **close()**를 호출하면, B는 잠금을 한 번도 얻지 않았는데도 공유 `<run>.closed` 파일을 씁니다. 수집기는 closed marker를 잠금보다 우선 신뢰하므로 A가 살아 있어도 run_finished/reclaimable이 true가 됩니다.

Windows에서 **writer_alive=true와 run_finished=true/reclaimable=true가 동시에 성립**함을 재현했습니다. WSL에서는 더 나아가 ACK된 A의 활성 파일과 lock 경로가 prune으로 삭제됐습니다. A의 다음 append는 성공을 반환하지만 **collectable segments=0**입니다. 기존의 “두 번째 작성자 거절” 테스트가 실패 후 close 경로를 검사하지 않아 이 문제가 남았습니다.

수정 요구:

- closed marker 발행은 실제 run 소유자에게만 허용하십시오. 잠금 미획득 객체의 cleanup과 반복 close는 다른 작성자의 상태를 바꾸면 안 됩니다.
- 종료 표식·잠금 해제·활성 파일 닫힘의 순서를 일관되게 하고, 종료된 객체/run의 재개 가능 여부를 명시적으로 제한하십시오.
- GC가 표식/잠금을 확인한 뒤 삭제할 때까지 작성자 권한이 바뀌는 경계도 보호하십시오. 잠금 파일을 unlink하여 서로 다른 inode를 잠그는 작성자가 생기지 않아야 합니다.
- 현재 두 번째 작성자 거절 테스트에 finally/close를 추가하고, 첫 작성자의 후속 레코드가 Windows/WSL 모두에서 수집되는지 검증하십시오.

## R3-B · P2 — liveness probe가 종료 run의 보존 시계를 다시 시작함

위치: 같은 파일의 `writer_alive`, `run_finished`, `run_age`, `_run_files`.

잠금을 획득할 수 있는지 시험한 **뒤** run_age를 계산하며, run_age에는 `.lock` 파일 mtime도 포함됩니다. UnixFileLock 3.32.5는 성공적으로 잠금을 획득할 때 해당 파일을 갱신합니다. 따라서 조회 자체가 회수 기준의 최신 시각을 현재로 바꿉니다.

실제 WSL에서 descriptor와 잠금을 해제해 죽은 프로세스와 같은 OS 상태를 만들고 segment/lock mtime을 모두 8일 전으로 설정했습니다. 조회 전 age는 **691200초**, `run_finished()` 직후 age는 **0초**, 결과는 **false**였습니다. 반복 probe 역시 false입니다. 수집기가 보존 기간보다 자주 확인하면 crash run의 health/lock 및 종료 판정이 필요한 부분 꼬리의 정리가 계속 연기됩니다. 테스트에서 `now=time.time()+8일`을 넘기면 이 갱신 부작용이 가려집니다.

수정 요구: 읽기/잠금 probe가 쓰는 metadata를 보존 기준으로 사용하지 마십시오. 작성자의 마지막 내구성 있는 기록/종료 시각과 수집기의 조회 시각을 분리하고, 현재 시각으로 호출하는 반복 수집이 죽은 run의 정리를 미루지 않는지 검증하십시오. 명시적 closed 없이 죽은 run, 잘린 꼬리, ACK 후 남은 health/lock 파일을 포함하십시오. 살아 있는 run 보호는 그대로 유지해야 합니다.

## 범위와 다음 제출

수정은 **R3의 소유권과 보존 시각 두 항목**으로 좁힙니다. 나머지 세 경계는 이번 수정과 테스트로 수용했으며, 관련 회귀만 유지하십시오. 같은 PR에 두 반례를 안전 결과 테스트로 바꾸어 추가하고 Windows/WSL 실측·정확한 head·실패 이력을 제출하면 재검토합니다.

이전 readiness/PowerShell timeout의 원인 미확정 후속 항목은 #16/#18에 이미 기록되어 있습니다. 이번 CI가 재실행 없이 통과한 것은 확인했지만 과거 원인 해결로 바꾸어 기록하지 않습니다. U001 병합, #17/#1/#11 종료, U002 착수는 아직 승인하지 않습니다.
