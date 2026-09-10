# FA-017 / GitHub #18 종료 검토 자료

해결 커밋: `2b890f9fafa86fe20ae9ff03819444272eaaa6e6`.
이 자료는 #18의 기존 인수 조건 7개를 대상으로 한다. Zeus 전체 흡수,
운영 배포, 삼성 기기 검증을 이 이슈의 종료 조건에 추가하지 않는다.

## 수정과 공동 검토

Codex는 실패 영수증 재전달이 다른 agent/actor/복구 순번을 받아들이는 결함을
메모리와 실제 PostgreSQL에서 재현했다. Claude는 손상된 생성 시각이나 누락된
상태가 전체 작업 선택을 중단시킬 수 있는 경로를 찾았다. 두 검토자가 발견을
대조한 뒤 Codex가 수정했다. [의논과 판단](discussion.md),
[Claude 최종 검토](claude-final.md)에 원인과 보완 결과가 있다.

실패 재전달에도 엄밀한 실행 신원 비교를 적용하고 기존 영수증 해시는 유지한다.
잘못된 대기열 메타데이터는 행별로 차단하고 통지한다. 생성 시각은 추측해서
채우지 않으며, 정상적인 생성 시각은 UTC 시각과 작업 ID로 정렬한다.
[규범 계약](../../../contracts.md)의 `INV-EXECUTION-IDENTITY-001`과
`INV-EXECUTION-TIME-001`이 지원 범위와 시간 가정을 명시한다.

## 같은 커밋의 검증

| 실행 환경 | 관측 |
| --- | --- |
| Windows 전체 | 911 통과 / 299 건너뜀 |
| Windows 실제 PG·Redis 대상 | 323 통과 / 1 건너뜀 |
| WSL 전체 | 917 통과 / 293 건너뜀 |
| WSL 실제 PG·Redis 대상 | 323 통과 / 1 건너뜀 |
| Linux·Windows 원격 CI | [실행 34429521115](https://github.com/trevi00/zeus/actions/runs/34429521115) 5개 작업 모두 통과 |

공유·중첩 UTF-8 경로의 실제 자식 프로세스가 동일 시각의 여러 작업을 구분한다.
재시도와 heartbeat, 완료 중 다른 작업의 행 보존을 확인한다. 실패 재전달은
실제 task-result 처리로 생성한 actor 형태의 결정 작업에도 검증한다.
실제 PG 쓰기 실패·잠금·프로세스 중단과 Redis 중복 전달/회수 검사도 포함한다.

CI 통합 작업은 1,207 통과 / 3 건너뜀과 Docker 검증 10 통과를 기록했다.
Windows Python 3.12/3.14는 각각 912 통과 / 298 건너뜀,
Linux Python 3.12/3.14는 각각 917 통과 / 293 건너뜀이다.

원본 로그와 해시는 `full-tests.*`, `target-tests.*`, `wsl/receipt.json`에 있다.
`pre-final-*`는 보강 전 실행 기록이며 최종 인수 증적이 아니다. 그때의 native
경로는 재실행으로 갱신되었으므로 최종 `target-tests.json`에 기록된 해시만
현재 `native-processes/` 파일에 대응한다. 예비 영수증의 예전 해시를 최종
파일 검증에 사용하지 않는다.

## 인수 시 확인할 한계

- project/retrospective 3/5 값은 확장 필드 보존을 확인하기 위한 명시적 입력이다.
  실제 회고 수집 기능이나 Claude 자산 전체 흡수를 완료했다는 증거가 아니다.
- 실행 소유자는 로컬 실행의 펜싱 토큰이다. 다중 사용자 인증/테넌트 격리를
  구현하거나 검증했다는 의미가 아니다.
- 실제 OS 시계 변경·절전/VM 재개·다중 호스트 시간은 실측하지 않았다. 실제
  재시작/기한 경과/PG 잠금 검사와 순수 시각 입력/저장된 관측 변경 검사를
  구분한다. 재시작 이후 UTC가 유효하다는 가정과 탐지할 수 없는 오프라인
  시계 변경이 있음을 인수 조건 5의 증적에 명시한다. 이 범위 설명은 이전
  실행 시간 문서의 광범위한 파일럿 검증 요구와 #18의 종료 범위를 구분한다.
- 건너뛴 테스트, CLI 종료 0, 모델 검토를 사람의 시나리오 승인으로 간주하지
  않는다. 실제 모델 실행·기기 QA·프로덕션 배포를 했다고 주장하지 않는다.

## 종료 입력과 남은 승인 단계

`acceptance/criterion-1.json`부터 `criterion-7.json` 및 `environment.json`은
현재 티켓 revision/content hash와 해결 커밋에 묶인 자동 검증 관측이다.
`outcome: passed`는 문서에 명시된 범위의 자동 계약 검사 결과이며 사람의
승인이나 이슈 종료가 아니다. `imports.json`은 로컬 불변 아티팩트 참조를,
`acceptance.json`은 실제 `prepare-close` 명령에 사용할 입력을 제공한다.
`superseded-acceptance-timestamps/`는 검토 중 발견한 관측 시각/참조 묶음을
수정하기 전 기록이다. 현재 종료 입력으로 사용하지 않는다. 수정본은 원래
관측 시각을 유지하며 그 시각보다 나중에 나온 결과를 해당 문서에서 제외했다.

현재 배포에는 외부에서 등록한 사람 승인 정책이 설정되지 않았다. 따라서
서명 패킷 생성과 종료를 아직 실행하지 않는다. 이 제한은
[Zeus 종료 정책](../ticket-lifecycle-002/README.md)의 요구이며 GitHub 요구가 아니다.
에이전트가 생성한 키를 사람의 키로 등록하거나 대신 서명하지 않는다.

사람 승인자 등록 후 현재 관측의 나이를 정책과 대조한다. 만료된 관측은
시각만 바꾸지 않고 재검증한다. 그런 다음 다음 순서로 진행한다.

1. `zeus ticket prepare-close ZEUS-3875a025c20d --file docs/zeus/implementation/fa017-closure-001/acceptance/acceptance.json --output packet.json`
2. 생성된 패킷과 연결된 한계/증적을 사람이 검토하고 `zeus-ticket-close-v1`
   네임스페이스로 외부 서명한다.
3. Codex가 제공받은 서명을 `zeus ticket close`로 검증하여 로컬 원장을 닫고
   `zeus ticket sync ZEUS-3875a025c20d --repo trevi00/zeus`로 GitHub에 반영한다.

지금까지의 검토와 증적 수집은 운영 배포를 승인하지 않는다.
