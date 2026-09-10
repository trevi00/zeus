PR #69 재검토 — claude-work-006

검토 head: `567d75b89be4ded5e077825d13d94c3d9f619f92`. CI 10/10 SUCCESS와 closingIssuesReferences=[]를 확인했습니다. 두 호스트의 로그 6개는 Git blob 기준 stdout SHA-256과 전부 일치하고 stderr는 모두 빈 값입니다. 이는 첨부 자료의 무결성 확인이며 이번 검토에서 전체 스위트를 재실행했다는 뜻은 아닙니다.

판정: 수정 전 병합 보류. 다음 조건을 같은 PR에서 해결해야 합니다.

1. **P1 — 기존 Compose 자산 삭제 위험** (`scripts/environment_evidence.py:65-66,92`): 임의의 `--project`를 그대로 up/down에 사용하며 기존 컨테이너·볼륨·네트워크 소유권 확인이 없습니다. 기존 프로젝트 이름을 주면 그 프로젝트의 `down --volumes --remove-orphans`가 실행됩니다. 실행별 고유 프로젝트와 소유권 확인, 명시한 compose 파일, 실행이 소유한 자산에만 한정한 정리가 필요합니다. 포트 충돌도 기존 서비스를 변경하기 전에 거부해야 합니다.
2. **P1 — 실패를 성공으로 기록/반환** (`:62-63,77-100`): subprocess 경계에 통제된 실패를 주입해 재현했습니다. setup 실패와 teardown 실패는 모두 `passed=true`; Ruff 성공 뒤 pytest timeout은 단계 1개만 남아도 `passed=true`; pytest exit=1은 receipt=false지만 main은 정상 반환하여 CLI가 0으로 종료합니다. 모든 필수 단계 완료, setup/up/teardown 성공을 요구하고 실패 시 nonzero 종료해야 합니다. timeout/실행 오류도 영수증에 기록하고 정리 실패가 기존 실패 증거를 없애지 않아야 합니다. 이 반례 검사는 synthetic이며 실제 Docker/복구 증거가 아닙니다.
3. **P1 — 실제 시험 대상과 컨테이너 결속 없음** (`:33,65-84`): 부모 환경 전체를 상속하고 DB/Redis/repository 변수를 고정하지 않습니다. `settings()`는 부모 ZEUS_/HARNESS_ 값을 .env보다 우선하므로 시험이 다른 DB/Redis/저장소를 사용하면서 receipt는 방금 만든 컨테이너를 기록할 수 있습니다. 격리된 실행 환경에서 양쪽 alias를 소유 스택으로 고정하고 연결한 서비스 identity를 확인해야 합니다. 비밀 DSN은 공개 로그에 기록하지 마십시오.
4. **P2 — 실행 소스 결속 부족** (`:54-56`): `--untracked-files=no`는 당시 새 러너를 제외합니다. receipt의 e2e3235에는 이 러너 자체가 없으며 tree_dirty=false만으로 실행 바이트를 재구성할 수 없습니다. 새 실행에는 runner/compose/lock 및 실제 입력 manifest digest, 명시적 추적/미추적 상태를 기록하십시오. 기존 영수증을 소급해서 고치지 말고 원본으로 유지하고 한계를 설명해야 합니다.
5. **문서 정정**: 기존 `docs/zeus/implementation/outbox-isolation-001`에는 실제 Windows PG/Redis 58개 통과와 WSL 742 passed/146 skipped가 있습니다. 'Linux는 CI뿐/로컬 Redis 실패 상태'라는 전면적 설명을 현재 main의 두 호스트 전체 integration 실행을 추가했다는 설명으로 정정하십시오. 새 스택의 재부팅 후 실행은 before/after boot identity, 보존된 원장/작업 identity와 복구 불변식 없이는 재부팅 복구 증거가 아닙니다. PR 자체의 'not a reboot' 한계는 적절합니다.

기존 영수증의 1433/1439 및 각 Docker 16 passed 보고는 보존할 가치가 있습니다. 다만 요약 통과 수만으로 #12/#16/#17/#18/#21/#23/#26의 개별 종료 조건을 모두 충족했다고 판단하지 않습니다. 해당 기준별 test node / 실제 서비스 / 실패 주입 / 결과 / 미실행 범위를 대응시켜야 합니다. 새 제품·사람·모델 증거를 fixture로 대체해서는 안 됩니다.

원저자와 검토자가 같은 GitHub 계정이므로 COMMENT 리뷰로 수정 요청을 기록합니다. 병합·이슈 종료는 하지 않았습니다.

