# 확정 스냅샷은 모든 행을 엄격히 검사하고 분모를 통째로 보고한다; 없음은 비어 있음이 아니다

기존 FA-030 / GitHub [#31](https://github.com/trevi00/zeus/issues/31) / `ZEUS-993045a59e5c` 개정 1의 구현·검증 기록입니다.
상류 brain snapshot status CLI의 격리 실행([resolution](../../../full-analysis/baldrix-distribution-config-001/resolution.md))에서
깨진 JSON 행·비객체 행이 모든 위치에서 버려지고, 누락 파일과 잘못된 graduation JSON이 빈 상태로 처리되며, schema_version/id
존재가 강제되지 않은 채 7회 중 6회가 rc0이었고, CI의 snapshot job이 paths 필터로 생략될 수 있음이 확인됐습니다. 새 이슈나
분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus의 기존 import(`skill_import`)는 검증된 append-only prefix만 전진시키고 torn tail을 인식합니다(INV-SKILL-IMPORT-001).
  그러나 "확정된 스냅샷 묶음" — 여러 필수 파일·필드·버전·참조 관계 — 을 하나의 검사로 검증하고, 검사 결과와 바이트·revision을
  결속해 import 전에 막는 경로는 없었습니다. Zeus CI(`validation.yml`)는 paths 필터 없이 모든 push/PR에 전 job을 실행합니다.
- `domain/snapshot_integrity.py` (stdlib만):
  - `parse_manifest`: version 1, 필수 파일마다 kind(jsonl/json)·schema_version·required_fields(기본 schema_version, id)·
    references(필드 → 필수 파일)·allow_empty. 상대 경로 밖·미지 kind·0 버전·미등록 참조·비bool allow_empty 거절.
  - `verify_file`: missing / unreadable(예외) / corrupt / version_mismatch / empty(allow_empty일 때만) / valid. JSONL은 모든
    행을 검사(비객체, 필수 필드 누락, 버전 불일치, 빈 id, NaN, 파싱 실패 → corrupt 계수, 절대 버리지 않음). 마지막 줄바꿈이 없는
    torn tail은 `live` 모드에서만 "아직 확정 집합이 아닌 줄"로 허용하고 `confirmed` 모드에서는 corrupt.
  - `verify_snapshot`: 파일별 리포트 + 참조 해소(dangling 목록) + 분모(files_required/present/valid/empty/missing/unreadable/
    corrupt, lines_total/corrupt, records_valid, torn_tails, dangling_references, extra_files) + snapshot_hash. `valid`는 모든
    필수 파일이 valid/empty이고 dangling이 없을 때만.
  - `required_checks(changed_paths, policy)`: 경로 prefix → 검사 이름 정책(빈 목록 거절). 의무 검사 목록, unmapped 경로,
    상태(`checks_required` / `unmapped_changes` / `no_checks_required`)를 돌려주며 "검사 없음은 통과가 아니다"를 명시.
- `application/snapshot_imports.py`: `SnapshotImports.import_snapshot(files, manifest, binding, mode)` — binding(source/tool
  revision 40-hex 또는 unversioned, environment) 검증 → 검증 → 모든 바이트를 아티팩트(latin-1 byte-preserving + sha256)로
  보관 → `snapshot_imports` 행(status, importable, report, 파일 ref). 무효 스냅샷도 기록되지만 `importable: False`.
  `require_valid(tx, id)`는 문제 계수를 들어 거절합니다.
- `docs/contracts.md`: `INV-SNAPSHOT-001` 추가.

## 재현과 검증

- `tests/test_snapshot_integrity.py`(6 검사; import는 MemoryStore + PostgreSQL 격리 스키마):
  - manifest 거절 7종.
  - 정상 스냅샷 valid(레코드 4, 분모 완전); 깨진 행 → corrupt 계수 1(레코드는 여전히 4, 버리지 않음); 비객체·id 없음·버전 3·
    빈 id·NaN 각각 이름 있는 오류; **missing / unreadable / 필수인데 empty(corrupt) / 허용된 empty** 네 상태; 잘못된
    graduation JSON은 corrupt(빈 상태 아님), 버전 9는 version_mismatch; ghost를 철회하는 행은 dangling → invalid; 추가 파일은
    `extra_files`.
  - torn tail: live에서 valid + torn_tails 1(레코드 미포함), confirmed에서 corrupt; 미지 모드 거절.
  - 변경 → 검사: 빈 검사 목록 정책 거절; brain 변경은 snapshot_integrity 의무; README 변경은 unmapped; 변경 없음은
    `no_checks_required`("passed check 아님").
  - import(memory+PG): 유효 스냅샷 importable + 멱등 + 원본 바이트 아티팩트; 깨진 스냅샷은 `invalid`로 기록되고 실패 바이트 보존,
    `require_valid`가 `files_corrupt=1, lines_corrupt=1`로 거절; 잘못된 binding 3종 거절; 파일 누락 스냅샷은 ref None + missing.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_snapshot_integrity.py` + `test_architecture.py` (HARNESS_INTEGRATION=1) | 10 passed in 0.58s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; main `1488468` 위에서) | 955 passed, 311 skipped (168s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 이 검사는 아직 어떤 실제 snapshot 생산자에도 연결되지 않았습니다(Zeus는 상류 JSONL을 런타임 원장으로 이식하지 않음). 실제
  Windows/Linux/WSL 설치·업데이트·복구, 패키지 루트/런타임 쓰기 루트 구분, 프로젝트 root/하위 cwd의 스택 선택은 실측하지
  않았습니다. `required_checks`는 정책 함수이며 CI 자체를 바꾸지 않습니다(Zeus CI는 원래 paths 필터가 없고, `[skip ci]` 커밋에는
  검사 결과가 없다는 사실을 계약에 적었습니다).
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.
