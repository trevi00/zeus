# 첫 제한 운영 개선: 실측 러너의 증거 보존과 임시 폴더 정리

Codex 명세 `docs/zeus/operations/windows-pilot-001/NEXT-CLAUDE-TASK.md`의 구현이다. 분석·수용 기준·독립 검토는
Codex, 구현·테스트·증거·PR은 Claude. 관련 #18 #20.

이 작업은 `workdir_removed: false`를 고치는 일이지만, **더 큰 결함은 정리가 아니라 그 전에 있었다.** 정리는 증거를
먼저 지우고 있었다.

## 1. 원인 (추정하지 않고 쟀다)

`scripts/claude_real_call.py`는 임시 폴더를 `shutil.rmtree(ignore_errors=True)` 5회 + 1초 대기로 지우고 결과를
`workdir_removed`에 적었다. "Windows라서 느리다"는 설명이 가능해 보였으므로 **그 설명을 시험했다.**

러너와 같은 모양(임시 Git 저장소 + linked worktree + `git gc`로 packed objects)을 만들어 두 호스트에서 쟀다.

| 호스트 | 5회 시도 결과 | 남은 파일 | 거절 사유 |
|---|---|---|---|
| Windows 11 (git 2.55.0.windows.3) | **5회 모두 실패**, 매번 같은 파일 | 4개 — `.git/objects/info/commit-graph`, pack의 `.idx`·`.pack`·`.rev` | `EACCES` / **WinError 5**, 전부 읽기 전용 속성 |
| WSL Ubuntu 26.04 (git 2.53.0) | **1회에 성공** | 0개 | 없음 |

**대기는 원인이 아니다.** 같은 파일이 매번 같은 이유로 거절하고, 다섯 번째가 첫 번째와 같다. Linux에서는 **같은 4개
파일이 똑같이 읽기 전용인데도** 지워진다 — POSIX의 unlink는 파일 속성이 아니라 **디렉터리** 쓰기 권한을 보기 때문이다.
즉 이것은 경합이 아니라 **속성의 의미가 플랫폼마다 다른 것**이다.

두 번째 원인은 따로 쟀다. 파일 하나를 열어 둔 채 같은 정리를 돌리면 위 4건에 더해 **WinError 32
(ERROR_SHARING_VIOLATION)** 1건이 나오고, **핸들을 닫으면 지워진다.** 이건 진짜로 시간이 푸는 거절이며 속성 문제와
처방이 다르다.

재현 스크립트와 두 호스트의 원본 출력은 `docs/zeus/evidence/runner-scratch-003/`에 있다.

## 2. 더 큰 결함: 정리가 증거를 먼저 지웠다

영수증의 `provider_receipt.execution_ref`는 **임시 폴더 안**(`<scratch>/artifacts/...`)을 가리킨다. 옛 정리는 그
디렉터리를 지우고 참조만 남겼다.

**이건 가설이 아니라 이 기계에서 확인한 사실이다.** 지금 남아 있는 고아 임시 폴더 7개를 읽기 전용으로 조사한 결과:

```
zeus-claude-call-*: top=['repository', 'workspaces']   (7개 전부)
```

`artifacts/`도 `observations/`도 없다. 쓰기 가능했으므로 옛 정리가 **지우는 데 성공했고**, 읽기 전용 git 파일만 남아
폴더가 사라지지 못했다. 다시 말해 **과거 실제 호출들의 `execution_ref`는 전부 이미 끊어진 참조다.** 명세가 "삭제 후
존재하지 않는 execution_ref만 남는 것을 충분한 재검토 증거로 취급하지 않는다"고 적은 바로 그 상태다.

이 7개 폴더는 이전 실행(파일럿 포함)의 것이므로 **건드리지 않았다.** 명세의 "다른 프로세스의 파일은 변경하지 않는다"에
따른다.

## 3. 고친 방식

새 어댑터 `src/codex_harness/adapters/scratch.py`. 순서가 바뀌었다 — **보존 → 검증 → 정리.**

### 3.1 보존이 먼저다 (`Scratch.preserve`)

정리 전에 외부 증거 디렉터리(`<out>/<label>-evidence/`)로 내보낸다.

| 보존물 | 무엇 |
|---|---|
| `execution-artifact.json` | `execution_ref`가 가리키던 실행 영수증 원본 |
| `candidate.diff` | 요약이 아닌 **전체 diff**(base→candidate) |
| `runner-tests-after.log` | 러너가 직접 돌린 pytest의 **전체 stdout/stderr** |

각 사본은 **디스크에서 다시 읽어 sha256으로 확인**한다(쓴 바이트가 아니라 읽힌 바이트가 근거다). 영수증에는 이름·크기·
digest·경로와 `revisions.base`/`revisions.candidate`가 남고, `provider_receipt.preserved_copy`가 살아 있는 사본을
가리킨다. **보존이 완전하지 않으면 정리를 하지 않는다** — 유일한 사본을 없애는 일이기 때문이다.

### 3.2 정리는 원인별로 다르게 답한다 (`Scratch.remove`)

- **자기 root 안의 읽기 전용 파일**: 이 실행 자신의 git이 만든 것이므로 속성을 풀고 지운다. 지운 파일은 **경로를 전부
  기록**한다.
- **열린 파일**: 유계 실패다. 경로와 사유(`in_use`, WinError 32)를 적고 **그대로 둔다.** 강제로 여는 것은 이 프로세스의
  일이 아니다. `recleanable: true`로 "핸들이 닫히면 다시 지울 수 있다"를 밝힌다.
- **부모 디렉터리의 `not_empty`**: 별개 장애가 아니라 위의 결과다. 기록은 하되 `blocking_refusals`에서 뺀다.
- **링크(symlink·junction)**: **링크로서 지우고 따라 들어가지 않는다.** 건너편은 남의 것이다.
- **containment**: 모든 대상의 최종 resolved path가 러너가 만든 정확한 root 안인지 확인한다. 벗어나면 **중단하고
  보고한다**(`ScratchEscape`). 그 시점부터 아무것도 지우지 않는다.
- 제한 시간이 있고, 넘기면 `timed_out: true`로 멈춘다.

## 4. 결과 (픽스처 모드 실측)

같은 러너를 끝까지 돌렸다(모델 호출 0회).

```
workdir_removed: true            (이전: false)
cleared_read_only: 12개 (전부 경로 기록)
refusals: []   remaining_count: 0   seconds: 0.063
preserved complete: true — execution-artifact.json 13265B, candidate.diff 2795B,
                            runner-tests-after.log 1962B, 셋 다 재읽기 digest 일치
```

실행 후 남은 것: 이 실행의 임시 폴더 0개, compose 컨테이너 0개, 자식 프로세스 0개. 다른 실행의 폴더 7개는 그대로 두었다.

## 5. 테스트 (`tests/test_scratch_cleanup.py`, 13건)

전부 **실제 임시 파일과 실제 git**으로 돈다. 유료 모델은 한 번도 부르지 않는다 — 여기서 재는 것은 파일시스템 동작이고,
모델을 부른다고 더 알게 되는 것이 없다.

| 검사 | 요구하는 것 |
|---|---|
| packed git 저장소가 지워지고 읽기 전용 파일이 이름으로 남는다 | 재현된 조건에서 `removed: true`, 거절 0 |
| **옛 5회 루프는 이것이 지우는 것을 못 지운다** | 대조. 5회 전부 실패하고 남은 것이 읽기 전용임을 단언한 뒤, 새 정리가 지운다 |
| 열린 파일은 유계 실패이지 강제 종료가 아니다 | `in_use` + WinError 32, 파일 보존, `recleanable: true`, 닫은 뒤 지워짐 |
| 두 원인은 결코 하나로 보고되지 않는다 | `blocking_refusals`는 `in_use`만, `not_empty`는 결과로 분리 |
| 링크는 링크로 지우고 건너편은 그대로 | symlink 불가 호스트에서는 **junction**으로 같은 경계를 잰다(권한 없이 가능) |
| root 밖으로 resolved되면 거절·보고 | 중단되고 **아무것도 지워지지 않는다** |
| scratch 밖 경로 보존 거절 | `ScratchEscape` |
| 증거는 정리 전에 디스크에서 검증된다 | 사본이 scratch보다 오래 살고 digest가 일치 |
| 보존 실패는 조용하지 않다 | 기록되고 `complete: false` |
| 이웃 디렉터리는 건드리지 않는다 | 다른 실행 데이터 보존 |
| 정리는 유계다 | 기한 초과 시 `timed_out` |
| root는 이 실행이 만든 바로 그것이다 | containment 양방향 |
| 없는 root로는 만들 수 없다 | |

**되돌려 확인했다.** 새 정리를 옛 5회 루프로 되돌리면 첫 두 건이 실패한다.

## 6. 호스트 증거 (`docs/zeus/evidence/environment-runs-011/`, head `6d2bc2b`)

| 호스트 | ruff | full-suite-integration | disposable-docker | `test_scratch_cleanup` |
|---|---|---|---|---|
| Windows 11 | 통과 | **1712 passed, 14 skipped** (541s) | **17 passed** | **13 passed, skip 0** |
| WSL Ubuntu 26.04 | 통과 | **1714 passed, 12 skipped** (229s) | **실패** (아래) | **13 collected, 12 passed, skip 1** |

WSL의 skip 1은 읽기 전용 속성이 삭제를 막는 것이 Windows에서만 일어나기 때문이다. 그 차이 자체가 §1의 측정이다.
두 호스트 로그·JUnit에서 canary 0건, `password=` 0건.

### 6.1 WSL disposable-docker 단계는 이번 회차에 초록이 나오지 않았다

**3회 연속 실패했고, 네 번째를 돌리지 않았다.** 초록이 나올 때까지 돌리는 것은 고르는 일이므로 하지 않는다.

| 시도 | 실패한 검사 | 지점 |
|---|---|---|
| 1 | `test_verification.py::test_real_disposable_database_and_redis_are_isolated_and_removed` | `verification.py:98`, 포트 연결 기한 30.0s |
| 2 | `test_host_interruption.py::test_postgres_pause_is_not_a_clock_step[2]` | 동일 |
| 3 | `test_verification.py::test_real_disposable_database_and_redis_are_isolated_and_removed` | 동일 |

세 번 모두 같은 파일의 같은 30초 기한에서 `ConnectionRefusedError`로 끊겼다. 세 시도의 산출물은
`attempt-1/2/3-wsl-disposable-docker-readiness/`에 전부 보존했다.

**이 브랜치 탓인지 갈랐다.** `git diff --name-only origin/main...HEAD`가 바꾸는 파일은 7개이고
`verification.py`·`test_verification.py`·`test_host_interruption.py`는 **그 안에 없다.** 새 코드
(`scratch.py`)는 이 세 검사가 전혀 부르지 않으며, **전체 스위트는 세 번 모두 통과했다**(1714 passed) — 새 테스트
13건 포함. 실패는 disposable-docker 단계에서만 났다.

**다만 발생률이 달라진 것은 감추지 않는다.** 직전 회차까지 이 호스트는 8회 중 4회 실패였고, 이번 3회를 더하면
**11회 중 7회**이며 오늘은 **3연속**이다. "기존 flake와 같다"는 실패 지점이 같다는 뜻이지 빈도가 같다는 뜻이 아니다.
빈도가 왜 올라갔는지는 **재지 않았고**, 이 명세의 범위(러너의 증거 보존·임시 폴더 정리) 밖이다. Codex가 별건으로
다룰지 정하면 된다. 관련 기록은 #16/#18.

## 7. 하지 않은 것

- 다른 실행이 남긴 임시 폴더 7개를 지우지 않았다. 남의 파일이다.
- 전체 임시 폴더 삭제·재부팅·프로세스 전역 kill 없음.
- 실제 모델 호출 0회. 원장 슬롯도 쓰지 않았다.
- 열린 파일을 강제로 닫지 않는다. 핸들 소유자를 찾아 죽이는 것은 이 범위가 아니며, 유계 실패로 보고하는 쪽을 택했다.
- 과거에 이미 끊어진 `execution_ref`를 복구하지 못한다. 그 바이트는 남아 있지 않다. 이 수정은 **앞으로의 실행**에만
  적용된다.
