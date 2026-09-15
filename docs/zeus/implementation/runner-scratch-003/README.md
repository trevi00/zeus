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

**단, 정상 종료일 때만 지운다.** 예외로 끝난 실행은 무엇이 만들어졌는지 완전히 알 수 없으므로 scratch를 남기고
영수증의 `recovery`가 그 경로를 가리킨다(§5.5 R2). 검토 반례를 되돌려 확인하는 동안 실제로 폴더 2개가 남았고,
**내가 만든 것만** 골라 새 정리로 지웠다(각각 읽기 전용 12개를 풀었다). 다른 실행의 7개는 건드리지 않았다.

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

## 5.5 독립 검토(review 5204956724) 반영 — R1~R4

Codex가 실제 격리 PostgreSQL·Redis·Git·프로토콜 자식으로 네 곳을 재현했다. **네 건의 공통 성질은 "증거가 보존됐다"는
판정을 증거 아닌 것이 내리고 있었다는 것이다.** 전부 실제 결함으로 인정하고 고쳤다.

| 지적 | 무엇이 틀렸나 | 고친 방식 |
|---|---|---|
| **R1** 같은 라벨 재실행이 이전 증거를 덮어씀 | 증거 경로가 `<label>-evidence`로 고정이고 고정 이름에 `write_bytes`했다. 첫 영수증은 그 파일의 digest를 계속 인용하는데 두 번째 실행이 그 위에 썼다 | 실행 시작 시 만든 **run id**(시각+난수)에 **영수증과 증거를 함께 결속**한다. 증거는 `<label>-evidence/<run_id>/`, 영수증 이름에도 run id가 들어간다. 파일 개수로 번호를 매기지 않으므로 동시 실행도 서로를 못 만난다. `preserve`는 `O_EXCL`로 만들어 **이미 있는 이름에는 부분적으로도 쓰지 않는다** |
| **R2** 실행 후 수집 실패에서 실제 artifact가 삭제됨 | 보존 목록은 실행이 끝까지 간 뒤에야 채워졌다. 그 전에 예외가 나면 "목록이 없다 → 보존할 것이 없다 → complete"가 되고 finally가 scratch를 지웠다 | **완료 여부를 장부가 아니라 파일시스템이 정한다.** `swept_evidence`가 `artifacts/`·`observations/` 아래 실제 파일을 전부 쓸어 담는다. 쓸어 담은 것이 있는데 하나도 못 지켰으면 incomplete다. 그리고 **예외로 끝난 실행은 무조건 scratch를 남긴다** — 무엇이 만들어졌는지 완전히 알 수 없기 때문이다 |
| **R3** 실패한 diff를 검증된 빈 증거로 기록 | `git diff`의 stdout만 보존하고 exit code·timeout·stderr를 보지 않았다. exit 128에 빈 stdout이면 **성공한 빈 diff와 구별되지 않는다** | 증거를 만드는 명령은 `command_record`로 **출력과 종료 상태를 함께** 보존한다. 실패했으면 `candidate.diff`를 만들지 않고 `candidate.diff.failed.json`을 남긴 뒤 incomplete로 기록한다. 성공한 빈 diff·비정상 종료·시간 초과가 서로 다른 결과다 |
| **R4** 보존 실패인데 passed=true / exit=0 | 최종 판정에 보존 상태가 들어 있지 않았다. 무인 호출자는 성공으로 읽는다 | **두 주장을 갈랐다.** `task_succeeded`(작업 자체)와 `evidence_complete`(러너가 증거를 아직 쥐고 있는가). `passed`는 둘 다 참일 때만이고, 증거가 불완전하면 **비정상 종료(1)** 하며 `recovery`에 남은 scratch 경로와 실패 목록을 적는다. 출력 디렉터리가 거절해 영수증을 못 써도 요약을 출력하고 1로 끝난다(원장 정산은 그 전에 이미 끝나 있다) |

**되돌려 확인했다.** 수정을 검토 시점 코드(`b9d5345`)로 되돌리면 새 회귀 **12건이 전부 실패**한다(실제 격리 스택 위에서).
복원하면 25건(신규 12 + 기존 13) 전부 통과한다.

기존 `test_a_preserved_copy_that_cannot_be_written_is_reported_not_assumed`는 `Path.write_bytes`를 가로채고 있었는데
새 코드가 `os.open`으로 쓰므로 무력해졌다. 주입 대신 **실제 장애**로 바꿨다 — 목적지 이름을 디렉터리가 이미 차지하게
해서 배타적 생성이 진짜로 실패하게 한다.

### 5.5.1 새 회귀 (`tests/test_runner_evidence.py`, 12건)

전부 실제 격리 PostgreSQL·Redis·Git·프로토콜 자식으로 러너를 `--fixture`로 끝까지 돌린다. 유료 모델 호출 0회.

- R1 — 재실행이 첫 증거의 digest를 그대로 두는가, 같은 이름에 두 번 쓰면 `FileExistsError`가 나는가, 영수증과 증거가
  같은 run id를 다는가
- R2 — 실행 직후 수집 예외를 주입해도 **디스크의 artifact가 살아남는가**(쓸어 담기가 장부가 놓친 것을 찾는가),
  "만들어진 증거 없음"과 "목록 없음"이 다른 답인가, 쓸어 담았는데 못 지키면 incomplete인가
- R3 — 실패한 diff가 verified가 아닌가, **성공한 빈 diff는 여전히 complete인가**(대조), 시간 초과가 별개인가
- R4 — 필수 증거를 잃은 실행이 passed가 아니고 exit도 0이 아닌가, 작업 성공과 증거 완결이 **두 값으로** 남는가,
  영수증을 못 써도 보고하고 실패하는가

## 5.6 2차 독립 검토(review 5205365197) 반영 — A·B·C

기존 네 반례와 제출 회귀 25건은 통과했고, 세 경계가 남았다. **세 건의 공통 성질은 "이 경로로 빠져나가면 판정을
안 한다"였다** — 빈 목록이면 검사를 건너뛰고, 예외는 보고를 건너뛰고, 오류는 종료 코드를 건너뛴다.

| 지적 | 무엇이 틀렸나 | 고친 방식 |
|---|---|---|
| **A** 빈 목록이면 상한 초과·필수 참조 검사를 건너뜀 | `entries`가 비면 즉시 `complete=true`로 반환했고, capped·필수 참조 검사는 그 뒤에 있어 실행되지 않았다. **빈 "선택 결과"를 증거 부재로 읽은 것이다** — sweep이 상한에 걸려 아무것도 못 고른 경우와 `execution_ref`가 가리키는 파일이 없는 경우가 둘 다 이 분기로 들어온다 | **복사는 조건부, 판정은 무조건.** 빈 목록이어도 리포트를 만들고 그 뒤에 capped·열거 실패·필수 참조·sweep 미보존을 **똑같이** 적용한다. 열거 실패(`rglob`이 거절)도 새 사유로 넣었다 — **못 보는 것은 없는 것과 다르다.** 진짜 빈 scratch는 그대로 수용한다 |
| **B** 보존 디렉터리 생성 실패가 최종 보고·정산을 건너뜀 | `destination.mkdir`이 `preserve`의 예외 처리 **밖**이었고, `call`의 `preserve_evidence` 호출도 보호되지 않았다. `<out>/<label>-evidence`를 파일이 차지하면 `FileExistsError`가 그대로 올라가 영수증도 복구 보고도 쓰이지 않았다. scratch는 남는데 **어디서 복구할지 아무도 모른다** | 목적지 생성 실패를 **예외가 아니라 결과**로 돌려준다(구조화된 incomplete). `preserve_evidence` 호출 자체도 감싸서 어떤 예외든 incomplete 기록이 된다. **원장 정산은 보존 오류와 독립적으로 시도**하고 그 성패를 영수증에 적는다 — 예약만 되고 정산 안 된 슬롯은 계속 세어지기 때문이다 |
| **C** 늦은 수집 예외인데 passed=true / exit=0 | `uncertain`이 scratch 삭제만 막고 최종 판정에는 들어가지 않았다. 작업은 끝났고 사본도 다 지켜졌는데 **그 사이에서 무언가가 관측되지 않은 채** 성공으로 끝났다 | **세 번째 값 `runner_complete`**를 뒀다 = 증거 완결 **그리고** 예상 밖 오류 없음. `passed`는 `task_succeeded and runner_complete`이고, `runner_complete`가 거짓이면 **exit 1**에 `recovery`가 오류 종류와 남은 scratch를 가리킨다. 지적하신 대로 **`evidence_complete`를 억지로 거짓으로 만들지 않는다** — 사본이 다 지켜졌다는 사실은 사실대로 남는다 |

**되돌려 확인했다.** 이 세 수정을 되돌리면 새 회귀 **8건이 실제 격리 스택 위에서 전부 실패**한다. 복원하면 33건(신규 8
+ 기존 25) 전부 통과한다. 되돌려 확인하는 동안 임시 폴더 3개가 남았고 **내가 만든 것만** 골라 지웠다.

정직하게 적자면, 되돌렸을 때 실패한 8건 중 대조 2건(`..._a_scratch_that_really_is_empty_is_still_accepted`,
`test_c_a_clean_run_still_passes`)은 안전 위반이 아니라 **새 필드가 없어서** 실패한다. 나머지 6건이 안전 결과를
요구하는 쪽이다.

### 5.6.1 새 회귀 8건

- A — capped와 missing_reference 두 경우가 각각 incomplete인가(Codex 반례 그대로), **진짜 빈 scratch는 여전히
  수용되는가**(대조), 열거 실패가 빈 디렉터리로 읽히지 않는가
- B — 목적지를 파일이 막고 있을 때 영수증·복구 보고가 쓰이고 exit이 0이 아닌가, **보존이 예외를 던져도 원장이
  정산되는가**
- C — 작업 완료 뒤 경계 오류가 passed를 거짓으로 만들고 exit 1인가(`task_succeeded`는 참으로 남는가),
  **깨끗한 실행은 여전히 통과하는가**(대조)

## 5.7 3차 독립 검토(review 5205932884) 반영 — 열거와 정산

기존 반례와 제출 회귀 41건은 통과했고 두 건이 남았다. **둘 다 "실패를 기록은 하는데 그 기록이 아무것도 바꾸지
않는다"였다.**

| 지적 | 무엇이 틀렸나 | 고친 방식 |
|---|---|---|
| **R1** 열거 거절이 `rglob` 안에서 숨겨짐 | `Path.rglob` 호출을 try로 감쌌지만 **표준 라이브러리가 내부 디렉터리 열거의 `PermissionError`를 삼킨다.** 실제 artifact가 있는 디렉터리의 `os.scandir`만 거절시키면 rglob는 **빈 결과**를 돌려주고 `complete=true` / "보존할 것 없음"이 된다. 내 회귀는 `Path.rglob` 자체를 던지게 바꿔 이 경계를 **지나쳐 갔다** | 열거를 **직접 관측 가능한 방식**으로 다시 썼다(`Scratch.list_evidence`). `os.scandir`로 직접 순회하며 **디렉터리마다 실패를 값으로 돌려준다.** 루트 판정도 `is_dir()` 대신 `os.stat`을 try로 감싸 **접근 불가가 부재로 축약되지 않게** 했다. 파일 크기를 못 읽는 경우도 "빈 파일"이 아니라 오류로 적는다. 링크·경로 이탈 정책은 그대로다 |
| **R2** 정산 실패를 기록하고도 성공으로 종료 | `call_budget_settled=false`를 영수증에 적으면서 `runner_complete`는 그것을 보지 않았다. 슬롯이 `reserved`인 채로 `passed=true`, `exit=0`이 된다 | `runner_complete`에 **정산 실패를 포함**했다. `recovery.call_budget`이 슬롯 id·정산 여부·오류를 가리키며, **슬롯은 보수적으로 계속 집계**하고 자동 재호출이나 삭제는 하지 않는다 |

**제출했던 `test_b_the_call_ledger_is_settled_even_when_preservation_throws`가 정산에 진입하지 않았다는 지적도
맞다.** fixture 모드에서는 슬롯을 예약하지 않으므로 `slot=None`이었고, `settled` 변수에 대한 단언도 없었다. 이름이
증명하지 않는 것을 말하고 있었다. **예약→정산 경로에 실제로 들어가는 회귀 3건으로 교체했다** — `tmp_path` 아래 진짜
`CallBudget` 파일 원장을 만들고 preflight만 real 모드로 바꿔 분기에 진입시키되, provider는 여전히 프로토콜 자식이다.
유료 호출 0회, 운영 원장 변경 0.

**되돌려 확인했다.** 두 수정을 되돌리면 새 5건 중 **3건이 실패**한다(열거 거절, 크기 판독 불가, 정산 실패). 나머지
2건은 대조이며 **이전 코드에서도 통과한다** — 보존 실패 시 정산이 도달하는 것과 깨끗한 실행이 통과하는 것은 이미
2차에서 수용된 동작이라, 여기서 새로 무는 것이 아니라 **깨지지 않았음을 지키는** 회귀다. 복원하면 36건 전부 통과한다.

## 6. 호스트 증거 (`docs/zeus/evidence/environment-runs-013/`, head `ed30106`)

| 호스트 | ruff | full-suite-integration | disposable-docker | 회귀 |
|---|---|---|---|---|
| Windows 11 | 통과 | **1732 passed, 14 skipped** (597s) | **17 passed** | `test_runner_evidence` **20 passed**, `test_scratch_cleanup` **13 passed**, skip 0 |
| WSL Ubuntu 26.04 | 통과 | **1734 passed, 12 skipped** (247s) | **17 passed** | `test_runner_evidence` **20 passed**, `test_scratch_cleanup` 13 중 skip 1 |

회귀 20건은 두 호스트에서 **전부 실제로 돌았다**(skip 0). 실제 격리 PostgreSQL·Redis·Git·프로토콜 자식으로 러너를
`--fixture`로 끝까지 구동하며, **실제 모델 호출 0회**다. WSL의 skip 1은 읽기 전용 속성이 삭제를 막는 것이 Windows에서만
일어나기 때문이고, 그 차이 자체가 §1의 측정이다. 두 호스트 로그·JUnit에서 canary 0건, `password=` 0건.

### 6.1 WSL disposable-docker 단계는 이번 회차에 통과했다

직전 네 회차에서 실패하던 단계가 이번 1회 시도에서 **17 passed**로 끝났다. 초록이 나올 때까지 돌린 것이 아니라
**1회 돌린 결과가 이것**이다.

**이것을 고쳤다고 말하지 않는다.** 이 브랜치는 `verification.py`도 그 두 테스트 파일도 건드리지 않았고, 원인은 여전히
미확정이다. 한 번 통과한 것은 한 번의 관측이며, 누적하면 이 호스트는 **13회 중 8회 실패**다. Codex가 별도 작업
(`docs/zeus/reviews/claude-work-018/READINESS-FOLLOWUP.md`)으로 다루기로 한 판단은 그대로다.

## 7. 하지 않은 것

- 다른 실행이 남긴 임시 폴더 7개를 지우지 않았다. 남의 파일이다.
- 전체 임시 폴더 삭제·재부팅·프로세스 전역 kill 없음.
- 실제 모델 호출 0회. 원장 슬롯도 쓰지 않았다.
- 열린 파일을 강제로 닫지 않는다. 핸들 소유자를 찾아 죽이는 것은 이 범위가 아니며, 유계 실패로 보고하는 쪽을 택했다.
- 과거에 이미 끊어진 `execution_ref`를 복구하지 못한다. 그 바이트는 남아 있지 않다. 이 수정은 **앞으로의 실행**에만
  적용된다.
