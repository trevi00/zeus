# 상류 경험 기록의 주장 보존과 독립 occurrence 재계산

기존 FA-002 / GitHub [#3](https://github.com/trevi00/zeus/issues/3) / `ZEUS-7fcc5f0308e7` 개정 1의 구현입니다.
상류 curator는 같은 repair 노트를 다시 수확할 때마다 `occurrences`를 1 올리고, 프로젝트 원장의
게이트 PASS **누계**를 `ledger:PASS xN` 토큰으로 찍습니다. 그래서 `occurrences: 308`은 "308회 독립 재발"이
아니라 "수확 사이클 308회"이고, `trust: confirmed`는 bake 시간 경과 + 수확 2회면 붙습니다
([교차검토 합의](../../../full-analysis/cross-review/resolution.md), [trace T1](../../../full-analysis/harness-experience/trace.md)).
Zeus는 그 값을 승인·자격·재발 횟수로 승계하면 안 됩니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## 변경

- `domain/experience.py`: frontmatter 분리, 필드 검증(문자열·리스트·매핑만), 증거 토큰 분류,
  `experience_claim(...)`. 상류 필드는 `upstream` 아래 **원문 그대로**(문자열) 보존하고 최상위에는
  `trust`/`occurrences`/`lifecycle`를 두지 않습니다. 독립 occurrence는 사건 하나를 식별하는 토큰
  (`incident:`, `occurrence:`, `ledger-event:`, `task:`)의 집합 크기로만 재계산합니다. `ledger:PASS xN`은
  누계 카운터, `repair-notes:*`는 노트 위치라 0으로 셉니다. 식별 토큰이 없으면 상태는
  `upstream_occurrences_unverified`입니다.
- `application/experience.py`: `experience_claims` 버킷에 추가 전용 기록. ID = (규칙 버전, source, path,
  바이트 SHA-256)이라 같은 바이트 재수입은 무변경, 같은 경로의 다른 바이트(pinned/observed)는 별개
  버전이며 수입 순서(`sequence`)로 정렬합니다. 같은 ID에 다른 내용은 거부합니다. 취득 근거(observed/pinned,
  revision)는 콘텐츠 claim과 분리해 `acquisitions`에 누적합니다: 같은 바이트를 observed→pinned A→pinned B로
  다시 수집하면 claim 하나에 근거 3건이 남고 버전·occurrence는 늘지 않습니다(PR #36 검토 반례).
- `adapters/experience.py`: 명시한 파일/디렉터리만 읽고(홈 자동 스캔 없음) 원본 바이트를 아티팩트에
  보관한 뒤 기록합니다. frontmatter YAML은 기존 `project_skills.load_yaml`(문자열 전용·태그 금지·
  중복 키 거부·크기/전개 상한)을 재사용합니다. `--dry-run`은 DB·아티팩트 쓰기가 없습니다.
- `docs/contracts.md`: `INV-EXPERIENCE-001` 추가. `record_incident`(INV-RECURRENCE-001)는 이 버킷을
  읽지 않으며, 그 사실을 실제 서비스 호출로 검사합니다.

```text
uv run python -m codex_harness.adapters.experience <lessons-dir> --basis observed --path-prefix knowledge/lessons/ --dry-run
uv run python -m codex_harness.adapters.experience <lessons-dir> --basis pinned --revision <40-hex> --path-prefix knowledge/lessons/
```

## 재현과 검증

- `probe.py` / `observed-lessons-receipt.json`: 현재 PC의 실제 상류 lesson 25개(`harness/knowledge/lessons`)를
  미리보기로 파싱하고 각 파일의 SHA-256을 [분석 인벤토리](../../../full-analysis/harness-experience/inventory.json)의
  observed 항목과 대조했습니다. **25/25 일치**. 상류 `occurrences` 합계 **2,692**, 재계산한 독립 occurrence
  합계 **0**, 25건 모두 `upstream_occurrences_unverified`. 예: `repair-cp949-…` `occurrences: 308`,
  `trust: confirmed`, 증거 토큰 24개 = 카운터 23 + 노트 위치 1. `triage-…`/`wireframe-ui-…` 두 건은
  분류되지 않은 토큰 2개씩(`ledger:<stage>::<statement>` 계열 키와 `repro:DETERMINISTIC|UNKNOWN`)이며,
  계열 키는 사건이 아니라 문장 종류를 가리키므로 미분류로 남기고 식별로 세지 않습니다.
- `tests/test_experience.py`(11 검사): 상류 값 원문 보존과 0 재계산, 식별 토큰 중복 1회 계수, 중첩
  `restatement_suspects`·여러 줄 인용 스칼라 보존, 잘못된 입력 9종 명시 거부(frontmatter 없음, 스칼라
  evidence, 빈 토큰, 중복 키, 리스트 루트, `!!python` 태그, 깨진 YAML, 비UTF-8, 256KiB 초과), basis/경로
  검증, 버전 분리와 멱등 재수입, 같은 ID 다른 내용 거부, 같은 바이트의 근거 전환 누적(버전·계수 불변), **수입 25건 뒤 `record_incident` 1건이 hook을
  만들지 않음**, CLI dry-run 무쓰기와 주입 store 수입.
- Windows 전체 회귀: 아래 표. Linux는 이 PR의 CI(ubuntu 매트릭스)로 확인하며 기록 시점에는 미실행입니다.

| 항목 | 결과 |
|---|---|
| `tests/test_experience.py` + `test_architecture` + `test_project_skills` | 44 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 930 passed, 305 skipped (165s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 이번 구현은 주장 **보존과 분류**입니다. 상류 25건 중 어느 것도 사건 식별 토큰을 갖지 않으므로
  독립 재발 횟수를 이 데이터에서 복원할 수는 없습니다. 복원하려면 상류가 사건별 식별자를 남기거나
  Zeus가 자체 incident로 다시 관측해야 합니다(`independent_occurrence` 규약).
- 경험을 Codex 작업 컨텍스트에 자문으로 주입하는 경로(설계·구현에만, 진단·리뷰·판정 제외)와 예산은
  교차검토의 후속 제안이며 이 PR에 없습니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따릅니다. 이 기록은 구현·검증 증거이며 배포 승인이 아닙니다.
