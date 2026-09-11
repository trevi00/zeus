# 로컬 Claude 하네스 흡수: 첫 현황 보고 (status-001)

역할: Claude가 분석·설계·구현·테스트·증거 작성·PR 제출을 맡고, Codex가 범위·설계·증거를
독립 검토하고 병합과 이슈 종료를 판단한다. 이 문서는 구현자의 보고이며 인수 승인이 아니다.
기준 리비전: Zeus `main` `50ebc2d` (`ledger-crosscheck.json`의 `committed_revision`).
관련 이슈: [#1](https://github.com/trevi00/zeus/issues/1), [#11](https://github.com/trevi00/zeus/issues/11).
이 묶음은 문서와 읽기 전용 점검 스크립트만 담는다. 원장(`docs/full-analysis/*.json`)은 바꾸지 않았다.

재현 명령 (Windows Git Bash, 2026-09-11):

```
python docs/zeus/absorption/status-001/crosscheck.py --repo . --live C:/Users/rudtn/zeus \
  --source baldrix=C:/Users/rudtn/.claude --source harness=C:/Users/rudtn/harness \
  --source guardian=C:/Users/rudtn/guardian --source harness-design=C:/Users/rudtn/harness-design \
  --out docs/zeus/absorption/status-001
uv run ruff check docs/zeus/absorption/status-001/crosscheck.py   # All checks passed!
```

`uv run pytest`는 이 묶음이 패키지 코드를 바꾸지 않으므로 실행하지 않았다.
원본 저장소의 훅·설치 스크립트·테스트는 실행하지 않았다.

## 1. 기존 분석 원장의 신뢰 가능한 현황과 불일치

신뢰 가능한 것은 커밋된 `docs/full-analysis/path-ledger.json`(2,736 항목, 항목마다
git blob·bytes·sha256·disposition·review_records)과 `partitions.json`(349 파티션,
`scope_sha256`)이다. 두 파일은 서로 맞는다: 2,736 경로 전부가 정확히 한 파티션에
속하고, 파티션 밖의 경로나 두 번 실린 경로는 없다.

| 구분 | 커밋 `main` 50ebc2d | 라이브 트리 `C:\Users\rudtn\zeus` (미커밋) | `docs/full-analysis/README.md` 본문 |
|---|---|---|---|
| 기록 있음 | 1,989 | 2,029 | 1,828 |
| unreviewed | 747 | 707 | 908 |

불일치와 그 원인:

- `docs/full-analysis/README.md`의 "1,828 / 908" 문장은 오래된 스냅샷이다. 커밋된
  coverage.json과 40개 차이가 아니라 161개 차이가 난다. README는 원장이 아니므로
  집계 문장을 원장에서 생성하거나 삭제해야 한다.
- 라이브 트리의 path-ledger 변경 40건은 전부 `unreviewed`에서 올라간 전이다
  (baldrix 23건 → `semantically_reviewed`, `baldrix-atlas-system-001`; harness 17건 →
  `body_reviewed_call_test_trace_pending`, `harness-proposed-003`). 같은 바이트를 두 번
  세지 않았다. 라이브 goal-progress.md의 "2,029 / 707"은 이 라이브 원장과 맞는다.
- 라이브 트리에는 미커밋 분석 폴더가 10개(125파일, 1,669,230 bytes) 있는데 라이브
  원장은 그중 2개(`baldrix-atlas-system-001`, `harness-proposed-003`)만 참조한다.
  나머지 8개(`atlas-system-proposals-joint-001`, `baldrix-java-001/002`,
  `baldrix-typescript-001`, `baldrix-pipeline-mobile-001`, `harness-proposed-004/005`,
  `java-typescript-joint-001`)는 어느 원장에도 없다. Codex 자신의 인벤토리
  (`docs/zeus/reviews/claude-work-002/unpublished-analysis-inventory.json`)도 이를
  "inventory and summary inspection only; not complete semantic source review"로 적었다.
  `java-typescript-joint-001`은 3개 파일(claude-initial, root-initial, scope)뿐인 미완성이다.
- `coverage.json`은 `whole_analysis_complete: false`, 2,736 항목 전부
  `adoption_status: not_approved_not_incorporated`다. 즉 흡수된 자산은 아직 0개다.
- 원본 실행 기록은 대부분 파티션이 "원본 실행 0건"이다. 실행을 시도한 공동 검토는
  `baldrix-gsd-runtime-001` 하나이며 격리 Linux의 첫 suite가 60초에 취소됐다
  (goal-progress.md 기재). 따라서 disposition의 `semantically_reviewed`는 정적 독해
  완료를 뜻하고, 실행 증거를 뜻하지 않는다.
- 고정 커밋은 현재 로컬 HEAD와 같다(baldrix `cbb5c3e6`, harness `a3f8b3be`,
  guardian `e7ced4a6`, harness-design `20147dde`). 그러나 작업 트리는 고정 커밋에서
  벗어나 있다. 아래 2절의 드리프트 항목 참조.

## 2. 전체 대상과 남은 분석 작업의 분모

분모는 네 층이며 서로 더하지 않는다.

| 층 | 분모 | 근거 |
|---|---|---|
| A. 고정 추적 경로 | 2,736 (baldrix 1,648 / harness 931 / guardian 13 / harness-design 144) | path-ledger.json, 커밋·blob 고정 |
| B. 로컬 추가 관측 자산 (바이트 고정) | 3,434 | docs/full-analysis/README.md, local-assets-status.json |
| C. 로컬 표면 메타데이터 항목 | 9,420 (baldrix 8,747 / harness 656 / guardian 17) | local-surface-summary.json, 메타데이터만 |
| D. 작업 트리 드리프트 (2026-09-11 관측) | 112 항목 (baldrix 8M+3U / harness 12M+87U / guardian 2M / harness-design 0) | `working-tree-drift.json`, 파일별 sha256 |

층 A의 남은 작업 (커밋 원장 기준):

| disposition | 개수 | 남은 일 |
|---|---|---|
| semantically_reviewed | 1,183 | 실행 증거·흡수 판단 없음. 흡수 후보 등록 필요 |
| body_reviewed_call_test_trace_pending | 652 | 호출자·상태·저장소·실패·테스트 추적 미완 |
| semantic-reviewed-execution-not-attested | 93 | 격리 실행 증거 없음 |
| semantically_reviewed_static_only | 61 | 정적 한정. 실행 계획 필요 |
| unreviewed | 747 (10,829,817 bytes, 전체 27,667,767의 39%) | 전문 독해부터 |

unreviewed 747의 분포(상위): harness `brain/` 164, baldrix `atlas/` 134, baldrix `skills/`
134, harness-design `design/` 59, harness `knowledge/` 62, baldrix `state/` 48, harness
`ledger/` 38, harness-design `analysis/` 28, baldrix `commands/` 21, `templates/` 17.
349 파티션 중 112개에 unreviewed가 남아 있다. 파티션별 수는 `ledger-crosscheck.json`
`partitions.rows`에 있다.

층 B/C의 남은 작업: baldrix 메타데이터 8,747 중 `unreviewed_observed_asset` 3,045,
`excluded_private_session_or_credential_surface` 4,656, `generated_cache_metadata_only`
1,020, 분류 보류 26; harness 656 중 unreviewed 385, cache 259, 보류 12. 사적 세션·
인증 정보 4,656건은 제외 사유가 기록되어 있으며 이번 작업에서도 공개 저장소에 올리지 않는다.

층 D는 고정 커밋 이후 사용자의 하네스가 계속 운영되며 생긴 변화다. 수정된 추적 파일
22개(baldrix 8, harness 12, guardian 2)의 기존 검토는 고정 blob에 대해서만 유효하다.
harness 미추적 87개는 대부분 `knowledge/lessons`, `knowledge/research`, `ledger/role-runs`
같은 경험 기록이다. 매니페스트는 경로·바이트·sha256만 담고 내용은 담지 않는다.

## 3. 기존 미커밋 분석 자료의 처리 제안

- 라이브 트리의 10개 폴더와 수정된 원장 3파일은 Codex 세션의 진행 중 작업이다.
  나는 이를 삭제·덮어쓰기·일괄 커밋하지 않으며, 같은 파티션을 중복 검토하지도 않는다.
- 제안: Codex가 자기 작성분을 자기 이름으로 커밋한다. 원장에 반영된 2개 폴더는 현재
  라이브 원장 전이(40건)와 함께, 원장에 없는 8개 폴더는 "inventory and summary
  inspection only" 상태 그대로 커밋하고 disposition은 올리지 않는다.
  `java-typescript-joint-001`은 미완성 표시를 유지한다.
- 커밋 전까지 해당 파티션(`baldrix:atlas/atlas-system`, `baldrix:skills/java`,
  `baldrix:skills/typescript`, `baldrix:skills/_pipeline`(mobile), `harness:brain/proposed
  003–005`)은 내 작업 목록에서 제외한다. 커밋 후 Codex가 지정하면 독립 검토자로 읽는다.
- 라이브 트리의 `.runtime/absorption/sources/*`는 Git 객체 보존본이므로 그대로 둔다.

## 4. 현황 구분표

| 구분 | 값 | 비고 |
|---|---|---|
| 전체 대상 | 층 A 2,736 / 층 B 3,434 / 층 C 9,420 / 층 D 112 | 2절 |
| 검토 완료 (정적 전문 독해) | 1,183 (라이브 1,206) | 실행 증거 아님 |
| 본문 검토·추적 미완 | 652 (라이브 669) | |
| 미검토 | 747 (라이브 707); 층 B/C unreviewed 3,430 | |
| 실행 미검증 | 정적 검토 전부. 실행 시도 1건(gsd-runtime, 취소) | 실행 증거가 있는 파티션 0 |
| 흡수 후보 | 등록부 없음. 28개 공동 resolution.md에 adopt/adapt/defer/reject 판단이 산문으로 있음 | 문자열 hit는 세지 않음 |
| 구현 완료 (흡수) | 0 | adoption_status 전부 not_approved_not_incorporated |
| 구현 완료 (Zeus 자체 FA 작업) | 45 implementation 기록, PR #36–#64·#69 병합 | 흡수와 별개 |
| 독립 검토 대기 | 이 PR 1건. 열린 다른 PR 없음 | |

## 5. 우선순위와 첫 번째 작업 묶음의 수용 기준

우선순위 (Codex 판단 전 제안):

1. **status-001 (이 PR)**: 분모 고정과 드리프트 매니페스트. 문서만.
2. **absorb-002 흡수 결정 등록부**: 자산별 `adopt/adapt/defer/reject` 레코드 형식과
   기존 28개 공동 resolution의 판단을 옮겨 적는 백필. 형식은 설계 변경이므로 6절
   질문 3에 Codex 답을 받은 뒤 시작한다.
3. **absorb-003 이후 미검토 파티션 독해**: Codex가 쥔 파티션을 제외하고 흡수 가치가
   높은 순서로. 첫 후보는 baldrix `atlas/` 비-system 파티션(autopilot 16, debate-engine
   14, memory-architecture 13, evaluator-system 12, hook-system 12, skill-promotion 12,
   mutation-tokens 10, seam-registry 8, dge-cycle 7 = 104 경로). 이미 검토된
   `lib-001…009`·`cli-001…005` 코드에 대해 "선언된 계약 대 구현" 대조가 가능해
   흡수 후보를 가장 빨리 낼 수 있다. 그다음 harness `ledger/role-runs` 32와
   `knowledge/research` 53(입증된 행동 기록), harness-design 90, baldrix `state` 25,
   `commands` 15, `skills/_outpos·kotlin` 28, `templates/prd` 9, `docs/subsystems` 10.
4. 실행 증거: `execution-not-attested` 93과 `static_only` 61은 격리 Docker 실행 계획이
   필요하다. 어떤 하위 시스템을 먼저 실행할지는 6절 질문 6.

첫 번째 파티션 묶음(absorb-003, `baldrix:atlas/autopilot:001` + `atlas/debate-engine:001`
+ `atlas/dge-cycle:001`, 37 경로)의 수용 기준:

- 문제와 수용 기준 → 원본 근거 → 설계 → 구현 → 검증 순서의 README.
- `files.json`: 37 경로 전부 path-ledger의 blob·bytes·sha256과 일치, 각 파일에 disposition.
- `review.md`: 파일마다 선언된 계약 → 진입점 → 호출자 → 상태 변화 → 저장소 → 실패
  처리 → 테스트를 이미 검토된 코드 파티션의 blob 위치로 연결. 문서와 코드의 모순은
  항목별로 적고, "선언된 교훈"과 "입증된 행동"을 분리한다.
- 실행하지 않은 테스트는 `tests_not_run`에 이유와 후속 조치와 함께 적는다. 원본 실행 0건이면 0건이라고 적는다.
- 흡수 후보는 자산별 adopt/adapt/defer/reject와 사유, 기존 Zeus 기능과의 겹침·충돌,
  SDD 8단계·핵심 시나리오·로그→시나리오→E2E·운영 피드백·모델 자격 이관 중 어디에
  기여하는지, 라이선스·의존성 확인을 함께 적는다. 등록부 형식이 확정되기 전에는
  review.md 안의 표로 둔다.
- 원장 갱신은 `unreviewed → X` 전이만 담은 델타 파일로 제출하고, 델타 적용은 재실행
  가능한 스크립트로 한다(질문 7). 파티션 `scope_sha256`은 바뀌지 않아야 한다.
- 사적 세션·인증 정보·개인 대화 원문은 포함하지 않는다.
- `uv run ruff check .`와 `uv run pytest` 결과, 정확한 head SHA, 실패 이력을 PR 본문에 적는다.

## 6. Codex가 판단해야 하는 설계 질문

1. **드리프트 결합 방식.** 고정 커밋을 유지하고 층 D를 sha256 매니페스트로 붙이는
   방식(제안)과, 사용자가 원본 저장소에 커밋해 새 커밋으로 재고정하는 방식 중 무엇을
   택하는가. 재고정하면 수정된 추적 파일 22개의 기존 검토가 무효가 된다.
2. **미커밋 125파일.** 3절 제안대로 Codex가 직접 커밋하는가. 커밋 전까지 해당 파티션을
   내 범위에서 제외하는 데 동의하는가.
3. **흡수 결정 등록부 형식.** path-ledger의 `adoption_status` 열거형을 확장하는 방식과,
   `docs/zeus/absorption/decisions/` 아래 자산별 JSON(원본 blob·검토 기록 `ref`·판단·
   Zeus 겹침·SDD 연결)을 두고 path-ledger는 커버리지 원장으로만 남기는 방식(제안) 중
   무엇을 택하는가.
4. **harness-design 144 경로.** 사용자 지시의 3개 디렉터리 밖이지만 기존 원장이
   "design deps"로 고정했다. 범위에 남기는가. 남기면 확장 사유를 원장에 적는다.
5. **로컬 추가 자산의 경계.** `unreviewed_observed_asset` 3,045+385 중 무엇을 본문
   검토 대상으로 하는가. 제안: `skill-candidates`·`memory`(L1/L2)·`jobs`(운영 로그,
   로그→시나리오 원천)는 본문 검토, `plugins` 623은 서드파티이므로 라이선스·메타데이터만,
   `projects/`·`file-history/`·`sessions/`는 개인 대화로 보고 사용자가 따로 허용하기
   전에는 메타데이터만.
6. **실행 증거 우선순위.** `execution-not-attested` 93·`static_only` 61 중 흡수 전에
   격리 실행이 필수인 하위 시스템은 무엇인가. 실행은 Zeus의 Docker 격리 경로만 쓰고
   사용자 하네스에서는 하지 않는다.
7. **원장 갱신 충돌.** `coverage.json`·`path-ledger.json`을 Codex의 라이브 트리와 내
   PR이 동시에 고치면 충돌한다. 제안: 내 묶음은 델타 JSON만 제출하고, 델타를 원장에
   적용하는 스크립트를 함께 넣어 Codex가 병합 시 재실행한다.

## 첨부

- `ledger-crosscheck.json`: 커밋 원장 집계, 라이브 원장 전이 40건, 파티션별 unreviewed.
- `working-tree-drift.json`: 네 원본 저장소의 HEAD, 수정·미추적 항목의 경로·바이트·sha256.
  운영 중인 하네스라 재실행 시 값이 달라질 수 있다(같은 날 두 번 실행에서 baldrix
  `brain/l1/insight-index.jsonl`의 바이트가 달랐다). 이 파일은 관측 시점의 스냅샷이다.
- `crosscheck.py`: 위 두 파일의 생성기. 읽기 전용.
