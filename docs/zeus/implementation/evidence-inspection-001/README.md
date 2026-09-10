# 증거 검사는 무엇을 검사했는지 이름 붙이고, 재실행은 정책만이 허가한다

기존 FA-022 / GitHub [#23](https://github.com/trevi00/zeus/issues/23) / `ZEUS-a9984f5b7caf` 개정 1의 구현·검증 기록입니다.
상류 observer의 격리 실측([resolution](../../../full-analysis/baldrix-observers-001/resolution.md))에서 디렉터리·빈 증거·
재실행 없는 passed·권한 오류가 CLEAN이었고, entry.cwd 아래 실제 파일이 탐지기 cwd 기준으로 검사되어 FABRICATION_CONFIRMED가
됐으며, 봉투가 고른 재실행 명령이 스크래치 파일을 쓰고 CLEAN을 반환했고, 잘못된 UTF-8 출력과 NUL 경로는 예외를 냈습니다.
새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus의 구현 작업 결과는 `{summary, tests: [str]}`이고 `tests`는 모델이 적은 문장이었습니다. 릴리스 러너는 정책이 정한 검사를
  따로 실행하지만, 작업자의 주장 자체를 그 작업의 workspace에서 검사·기록하는 경로는 없었습니다.
- `resources/evidence-policy.json`: Git 정의 재실행 정책 — 허용 argv prefix(`python -m pytest`, `uv run …pytest`,
  `ruff check` 계열), 명령당/전체 시간 상한, claim 수·출력 바이트·재실행 횟수 상한, 파일 크기 상한.
- `domain/evidence.py` (stdlib만): `parse_policy`(닫힌 스키마, 유한·양수·상한, bool 거절, per ≤ total), `parse_claim`
  (file: 상대 경로·NUL/절대/`..`/드라이브 거절·sha256·1-based range; command: argv 토큰·expected_exit; 자유 문장은 호스트 셸
  규칙으로 토큰화한 expected_exit 0 command claim), `authorized(argv, policy)`(prefix 정확 일치만), `classify_replays`
  (실패 우선 → 종료 코드 불일치는 `flake_pattern` → 기대와 같으면 `checked`, 다르면 `verified_mismatch`), `denominator`,
  `verdict`(`all_checked`/`incomplete`/`no_claims`; CLEAN 없음).
- `adapters/evidence_inspection.py`: `EvidenceInspector`. 파일 검사는 workspace 아래로 resolve해 밖으로 나가면 `error`,
  없음/디렉터리는 `missing`, 권한/stat 오류는 `unknown`, 해시·범위 불일치는 `verified_mismatch`, 해시 없는 주장은 "존재만
  검사"로 명시. 명령 재실행은 정책 prefix가 아니면 `not_checked`(주장은 권한이 아님), 허가되면 최소 환경(PATH 등 +
  `PYTHONIOENCODING`)·명시적 cwd·유한 deadline·출력 캡으로 자식을 띄우고, timeout이면 프로세스 트리를 종료하고 `terminated`를
  기록하며, 실행 파일 없음/권한/spawn 오류는 `replay_failed`의 원인으로 남깁니다. stdout/stderr 원시 바이트는 latin-1
  byte-preserving 텍스트 + SHA-256으로 아티팩트에 저장하고, UTF-8 디코딩 실패는 출력의 속성으로 기록합니다(대체 없음).
  claim 수·전체 시간 예산을 넘긴 주장은 `not_checked`(사유 명시).
- `application/evidence_inspection.py`: `EvidenceInspections.inspect(task, candidate, claims, cwd)`가 task/generation/
  attempt/owner·후보 revision·base·tree·workspace에 결속한 행을 `evidence_inspections`에 남깁니다(같은 입력은 같은 행).
  기록 실패는 `evidence_inspection_notices`에 알림을 남기고 예외를 올립니다 — 성공으로 기록되지 않습니다.
  `require_all_checked(tx, id)`는 `all_checked`만 통과시킵니다.
- `adapters/executor.py`: `implement` 결과의 `tests` 주장을 작업의 workspace에서 검사해 `result['evidence_inspection']`
  (`inspection_id`, `verdict`, `denominator`)로 남깁니다. 검사 자체가 실패하면 `verdict: inspection_error`로 남깁니다.
  작업 완료(`succeeded`)는 그대로 실행자 자기보고이며, 검사 verdict는 소비자(릴리스 검토 등)가 `require_all_checked`로
  요구할 근거입니다.
- `docs/contracts.md`: `INV-EVIDENCE-001` 추가.

## 재현과 검증

- `tests/test_evidence_inspection.py`(8 검사; 재실행은 전부 실제 자식 프로세스, 원장 검사는 MemoryStore + PostgreSQL 격리 스키마):
  - 정책·주장 스키마(잘못된 정책 7종, 잘못된 주장 14종 거절), 패키지 정책이 `rm`·`python -c`를 허가하지 않음, 분류 함수,
    verdict/denominator에 CLEAN 없음.
  - 파일 검사: 해시 일치 `checked`, 해시 불일치·범위 초과 `verified_mismatch`, 해시 없는 주장은 존재만, **탐지기 cwd에만 있는
    파일은 `missing`**, 디렉터리 `missing`, 없는 파일 `missing`, `..` 탈출 `error`.
  - 명령 재실행: exit 0 `checked`(재실행 2회, argv 동일), exit 3 `verified_mismatch`, **잘못된 UTF-8 출력**은 checked이되
    `decoding: invalid_utf8`이고 아티팩트 원시 바이트가 `b"ok\xff\xfe"`와 해시 그대로, 없는 실행 파일 `replay_failed
    (executable_missing)`, 두 번째 실행에서 exit이 바뀌는 명령 `flake_pattern`, `rm -rf /`는 `not_checked`(실행 없음),
    10,000바이트 출력은 4,096바이트로 잘리고 `truncated`.
  - 예산: 30초 sleep 명령은 1초 deadline에서 종료(`terminated`, 전체 25초 미만), 3번째 claim은 claim 예산으로 `not_checked`,
    전체 시간 예산 소진 후 `not_checked`, 없는 workspace는 `error`.
  - 원장(memory+PG): 결속 필드, 같은 입력 멱등, `require_all_checked`가 incomplete를 거절(분모 명시), 빈 주장은 `no_claims`,
    typed lease·후보 revision 없으면 거절.
  - 기록 실패: 두 번째 트랜잭션이 실패하는 store → 행 없음 + 알림 1건(verdict·원인) + 예외.
  - Executor: 실제 Git clone workspace에서 `implement`를 실행하는 픽스처 runtime이 `tests`에 `python -c …`와 `rm -rf build`를
    적으면, 전자는 workspace에서 재실행되어 `checked`, 후자는 `not_checked`, verdict `incomplete`, 행이 task·후보 revision에
    결속되고 cwd가 workspace.
- 기존 Executor·workflow 검사 6개 파일 125 passed(배선 후).
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_evidence_inspection.py` + Executor 관련 6개 파일 (HARNESS_INTEGRATION=1, PG 격리 스키마) | 133 passed, 6 skipped in 16.40s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 957 passed, 311 skipped (162s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 재실행은 격리 컨테이너가 아니라 작업 workspace의 자식 프로세스입니다(최소 환경·deadline·출력 캡·프로세스 트리 종료). 파일
  시스템/네트워크 capability 격리는 없으며 그래서 허가 prefix를 정책으로 좁혔습니다. Linux/WSL의 프로세스 트리·인코딩·경로는
  이번에 실측하지 않았습니다.
- `checked`는 결정론적 검사 결과이지 과거 실행의 진위·의미 검증·사람 인수·SDD 인수·모델 자격이 아닙니다(`authority` 필드,
  INV-EVIDENCE-001). 검사 verdict를 소비하는 릴리스/승격 경로 연결은 별도 단계입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.
