# Claude 팀원 프로필 적용 결과

2026-09-16. Codex 분석·독립 검토, Zeus를 통해 실행한 Claude 구현.

## 구현 및 실제 적용

- `worker-v1`은 Git/package에 담긴 지침·출처 manifest·독립 훅으로 구성된다. 신뢰된 실행 정책의 `runtime.worker_profile`로 선택하며 미지정 실행은 기존 동작을 유지한다. 전체 로컬 하네스 흡수 완료를 뜻하지 않는다.
- `.claude`와 `harness`의 선정된 운영 원칙을 새로 작성한 지침에 반영했다. `guardian`은 책임 분리 참고에 한정했다. 원본 홈 설정이나 원본 훅을 그대로 실행하지 않는다. 범위와 출처는 `sources.json`에 고정했다.
- 실행별 prompt/settings 전달 기록과 실제 hook 관측을 분리한다. 본문·훅 digest를 검사하며 실제 테스트는 후보 checkout의 `src`와 숙주 Python을 사용한다.
- 실제 Claude canary가 `zeus cycle status`에 `remaining_executions`를 추가했다. 저장 행은 바꾸지 않으며 변경 범위는 CLI와 해당 테스트 두 파일이다.
- 실제 CLI stream에서 테스트 **23 passed / 1 skipped**, Ruff 성공을 관측했다. skip은 PG 통합 환경 미제공이다. Codex가 별도 실제 PG/Redis 환경에서 같은 범위를 실행한 결과는 **24 passed / 0 skipped**, Ruff 성공이다.
- 실제 세션 `7f15f0fa-1001-492a-b2a2-ab4b71084145`에서 `SessionStart` **1회**, `PostToolUse(Bash)` **5회**를 읽었다. 외부/읽기 불가 영수증은 0개다. 이 기록은 준수·승인 판정이 아니다.
- 프로필 revision `945bdcb`의 독립 전체 PG/Redis 검증은 **1851 passed / 20 skipped**, Ruff 성공이다. 이후 canary 변경은 위 24건 집중 검증으로 확인했으며 최종 결합 revision의 전체 플랫폼 검증은 PR CI로 구분한다. 구현 두 호출·canary·review에서 수집한 관측은 총 183건이고 네 수집 영수증 모두 sink 실패 0건이다.

실행에 사용한 trusted policy 설정은 다음 두 값이다. 일반 `zeus serve`가 이 프로필을 자동 선택하게 바뀐 것은 아니다. 다음 운영 배정도 이 정책을 명시적으로 선택해야 한다.

```json
{
  "worker_profile": "worker-v1",
  "profile_evidence_root": "D:/workspaces/zeus/artifacts/<run>/profiles"
}
```

## 호출과 검토의 실제 상태

| 실행 | 결과 |
|---|---|
| Claude 구현 1 | 900초 기한 종료. 초안을 `34cd979`에 보존했으며 성공 처리하지 않음. 프로세스 트리 잔여 0을 종료 영수증으로 확인 |
| Claude 구현 2 | 기존 초안 마무리와 집중 검증. `945bdcb` 제출 성공. 전체 PG/Redis 검증은 Codex로 분리 |
| 프로필 적용 Claude canary | `bb026ab` 제출 성공. 실제 테스트 및 훅 관측. CLI가 보고한 비용 추정 USD 0.81071175; 청구액 보증 아님 |
| 실제 Codex 팀장 검토 | 코드에 `accepted: true`를 반환하고 자체 focused pytest 23 passed / 1 skipped, Ruff 성공. 그러나 검토 checkout에 untracked 문서·로그 3개를 남겨 실행기의 청결성 검사에서 거절됨 |

마지막 결과는 **자동 수용 완주가 아니다**. decision은 `retry`, cycle은 `stopped / execution_retry`, 실행 수는 **2/2**다. 원장 상태를 성공으로 덮어쓰거나 자동 재호출하지 않았다. 반환된 모델 판정과 원장에 커밋된 판정은 구분한다. 모델 호출은 이번 단계의 CLI 호출 4회(Claude 3, Codex 1)를 사용했고 기계 원장의 기존 8회를 포함한 상한 12를 유지했다.

Codex 주 세션은 프로필 전체와 canary 변경을 별도로 검토한다. 실제 팀장 모델의 판정 범위는 canary 두 파일뿐이다. 최종 전체 테스트·플랫폼 CI는 PR 체크와 독립 검증 산출물로 확인하며, 이 모델 판정을 그 대체물로 쓰지 않는다.

## 운영에서 발견한 두 연결 문제

1. 기존 evidence replay가 Windows에서 `C:/Python314/python.exe`를 선택해 검증 모듈을 찾지 못했다. 원래 `incomplete` 영수증은 보존했다. 숙주 venv의 절대 경로와 후보 PYTHONPATH로 수행한 독립 검증을 별도 artifact로 제공하고, 검토 입력에 추가한 사실을 PG event로 기록했다. 따라서 이번 검토에는 운영자의 증거 보충이 있었다.
2. 팀장 세션은 전역 작업 프레임 지침에 따라 checkout에 `review-frame-1c7c05af.md`와 테스트 로그 두 개를 만들었다. 추적 코드·인덱스 diff는 비어 있지만, Zeus의 계약은 untracked를 포함한 깨끗한 checkout이므로 수용 커밋이 거절됐다. 기존 복구 기능은 이 완료 판정을 모델 재호출 없이 재커밋하는 인터페이스를 제공하지 않는다. 임의 DB 수정으로 수용하지 않았다.

다음 운영 개선은 이 둘을 하나의 **검토 실행 계약**으로 묶는다: 증거 replay의 명시적 interpreter/cwd/environment 결속, 읽기 전용 검토 지침과 D 드라이브 외부 기록 경로의 일치. 전역 검토 범위를 다시 확대하거나 청결성 검사를 완화하는 작업이 아니다. 상한을 가진 다음 실제 작업에서 정상 수용을 다시 확인해야 한다. 작은 테스트 이름 개선 등은 이 운영 관문과 분리해 비차단으로 남긴다.

## 증거 보존

- 원본: `D:/workspaces/zeus/artifacts/team-profile-001/` 아래 구현 두 호출, canary, 실제 팀장 검토, 독립 검증. tracked `evidence-summary.json`은 주요 파일의 SHA-256과 상태만 보관한다.
- 실행/후보: 구현 task `2558f51c-f2c7-4858-8105-159aa9738226`, canary task `fee94c1f-ee53-4df7-bf43-d87f31c627b3`, review decision `1c7c05af-3307-4579-bdd7-06024fe9b367`.
- canary execution: `sha256:2170805cb9fee875724127c3519f651aa28c56023b854a1a92790ada910cdf55`.
- Codex 반환 판정: `sha256:6e8948b0fa4e51f9ce8980d5b435f0686e2fe3d7ff26e27b6e34d9cb232b8245`.
- 이전 운영의 300초 timeout 검토는 기존 reconcile/discard로 정리했다. `blocked`와 미확정 사용량은 유지했으며 성공·재큐잉으로 바꾸지 않았다.

일반·개발·운영 관측은 기존 Observer/PG/스풀 경로를 사용했다. 지속 PG/Redis 서비스는 유지하고 일회용 검증 스택만 자체 정리한다. 배포·자동 병합·재부팅·전역 홈 설정 변경은 하지 않았다. GitHub 이슈 #13과 #20의 전체 조건을 충족한 것은 아니므로 닫지 않는다.
