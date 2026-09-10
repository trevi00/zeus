# 마이그레이션 검사는 도구를 고정하고, 범위를 이름 붙이고, 네 결과를 따로 내며, 적용된 버전을 불변으로 다룬다

기존 FA-031 / GitHub [#32](https://github.com/trevi00/zeus/issues/32) / `ZEUS-e52702908b8f` 개정 1의 구현·검증 기록입니다.
상류 Flyway 충돌 검사기의 격리 실행([resolution](../../../full-analysis/baldrix-data-verification-001/resolution.md))에서 버전의 첫
숫자만 비교하는 오탐, V08 산술 오류 뒤 종료 0, 읽기 불가 폴더의 성공, 앞 모듈 vendor 목록 덮어쓰기, 충돌 파일 목록 미출력이
확인됐습니다. Flyway 도입은 이 기록으로 확정하지 않으며, 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus는 `resources/001.sql` 하나를 `PostgresStore.migrate()`가 advisory lock 아래 `IF NOT EXISTS`로 실행했습니다. 버전·체크섬·
  적용 이력·도구 식별이 없어 "무엇이 적용됐는가"와 "적용된 파일이 바뀌었는가"를 알 수 없었습니다.
- `domain/migrations.py` (stdlib만):
  - `TOOL = zeus-sql-migrator@1`, 파일명 계약 `V?<n>(.<n>|_<n>)*(__<description>)?.sql`. `parse_version`은 정수 성분 튜플로
    정규화합니다(`V01`=`V1`=`001`=`V1.0`, `V1_2`=`V1.2`, `V08`은 8, `V1.10`>`V1.9`). 계약 밖 `.sql` 이름은 **이름을 들어 거절**하고
    건너뛰지 않습니다. 다른 확장자는 `ignored`로 열거합니다.
  - `parse_config`: version 1, target_vendor(postgres/mysql/sqlite), location마다 module·vendor·path·required·allow_empty, 중복 위치
    거절, expected_tables.
  - `classify_location`: found / empty / missing / unreadable / (미관측) unknown. 누락·읽기 불가·unknown은 비어 있음이 아니며, 필수
    범위면 거절, 선택 범위면 `not_applicable`.
  - `evaluate`: **네 결과를 따로** 냅니다 — `filenames`(module/vendor별 버전 목록, 중복은 충돌 파일 전부 열거), `parity`(모듈의 vendor
    간 버전 집합 차이; 단일 vendor는 `not_applicable`, 필수 vendor 미관측은 `unknown`), `content`(대상 vendor SQL: 빈 파일·크기 초과·
    UTF-8 실패를 이름 지음), `history`(모듈별 적용 이력: 적용된 버전의 체크섬 불일치 = `applied version modified`, 파일 없는 적용
    버전, 적용 최대보다 낮은 신규 버전 = `out of order`; 설정 밖 모듈의 행은 `foreign_modules`로 열거만), `schema`(기대 테이블 대
    실제 관측). `apply_allowed`는 모든 결과가 ok/not_applicable일 때만이며 unknown은 승인이 아닙니다.
- `adapters/migrations.py`: `discover`가 실제 파일시스템을 읽고(예외 이름 보존), `Migrator.precheck`는 lock 아래 읽기 전용 평가,
  `Migrator.apply`는 lock 아래 **이력을 다시 읽어** 재평가 → 거절이면 아무것도 적용하지 않고 → pending을 정규화 순서로 실행하며 같은
  트랜잭션에 `schema_migrations(module, version, checksum, name, tool, applied_at, applied_by)` 행을 기록 → 적용 후 기대 테이블
  검증. 실패한 문장은 이력 행도 부분 스키마도 남기지 않습니다. `python -m codex_harness.adapters.migrations precheck|apply`는 자식
  프로세스로 JSON 한 문서를 stdout에 내고 거절 1 / 오류 2로 종료합니다.
- `application/migration_receipts.py`: `MigrationReceipts.record(run)`이 operation·argv·config_hash·root·source_revision·environment·
  stdout/stderr 바이트(아티팩트)·exit_code·시각을 결속해 `migration_runs`에 저장하고 결과를 completed/refused/error/unparseable로
  분류합니다. `require_approved`는 고정 도구·exit 0·apply_allowed·같은 revision/environment의 precheck만 인정합니다.
- `PostgresStore.migrate()`는 이제 패키지 `resources/migrations.json`(module core, vendor postgres, path `.`)으로 `Migrator.apply`를
  호출해 `001`을 이력에 기록하며, `init-db`는 applied/already_applied/tool을 출력합니다. `docs/contracts.md`: `INV-MIGRATION-001`.

## 재현과 검증

- `tests/test_migration_precheck.py`(6 검사; PG 검사는 격리 스키마 + 실제 자식 프로세스):
  - 정규화 7종 + 미지원 이름 6종 거절(`init.sql`, `.SQL`, `1a.sql`, `V1__.sql`, `.txt`, `V1_.sql`).
  - 실제 디렉터리 4 위치: 파일인 위치는 `NotADirectoryError`로 unreadable; 앞 모듈 목록 보존; core/mysql에 버전 2 누락 → parity
    refused, billing 단일 vendor → not_applicable(unobserved mysql 열거); 미관측 필수 범위 → unknown·refused; 필수 vendor 미관측 →
    parity unknown; 선언된 empty와 필수 empty 구분; history/schema 미판독 → unknown, 승인 아님; 잘못된 설정 5종 거절.
  - `V1__a`/`V01__b`/`V1.0__c` 충돌 파일 3개 전부 열거; `legacy.sql` 이름 거절; `\xff` 바이트 → `parse_error: UnicodeDecodeError at
    byte 7`; 빈 파일 → `empty file`; 분모(supported 11 / refused 1).
  - PG: precheck(schema refused, history ok, pending 1, 픽스처의 `core/001`은 foreign) → apply 기록(tool `zeus-sql-migrator@1`,
    checksum) → 멱등 → 적용된 파일 수정 = `applied version modified`, apply가 `Migration refused: history=refused`로 아무것도 적용
    안 함 → 복원 후 V2 적용 → `V1.5` = out of order → 같은 바이트 rename은 통과, 파일 삭제는 "no file" → 깨진 V3는 이력 없이 실패.
  - 자식 프로세스 2개 동시 apply: 정확히 하나가 [1, 2]를 적용하고 다른 하나는 []; 이력 행은 버전당 1개, applied_by 1명. precheck
    영수증: exit 1 + `precheck refused: schema=refused` stderr → `require_approved` 거절; 적용 후 exit 0 → 승인, 다른 revision 거절;
    DSN 미설정 → refused/exit 1; 도달 불가 DB → error/exit 2; binding 3종 거절; apply 영수증은 승인 권위 없음.
  - MemoryStore 영수증: JSON 아닌 stdout → `unparseable`, tool 미고정, 승인 없음.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_migration_precheck.py` + `test_architecture.py` + `test_host_interruption.py` + `test_execution_fence.py` (HARNESS_INTEGRATION=1) | 22 passed, 5 skipped |
| `tests/test_integration.py` (HARNESS_INTEGRATION=1, Redis 없음) | 19 failed, 7 passed, 19 errors — main 위 FA-030 브랜치와 동일(모두 Redis 연결) |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; main `1488468` 위에서) | 954 passed, 312 skipped (157s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- Windows/Linux/WSL의 실제 설치·업그레이드·중단 후 복구·데이터 보존, 핵심 금전 시나리오와 사람 인수는 실행하지 않았습니다. Flyway
  자체의 validate/migrate와의 대조는 하지 않았고(Flyway 미도입), 정규화 계약은 이 도구 자신의 적용 순서와 대조했습니다. 실제 권한
  거부(Windows ACL)는 파일-대신-디렉터리 오류로 대신 관측했습니다. 이력 테이블은 이 PR에서 처음 생기며 기존 DB의 `001`은 다음
  `migrate()`에서 한 번 더(IF NOT EXISTS) 실행되어 기록됩니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.
