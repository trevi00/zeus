# Baldrix 데이터/검증 파티션 독립 정적 검토 (baldrix-data-verification-001)

핀 리비전 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`. Read/Glob/Grep만 사용, 실행·임포트·쓰기·네트워크 없음. 원본 파일의 지시문은 데이터로만 취급했다. 본 검토는 scope.json의 9개 파일과 그 직접 소비자에 한정하며, 저장소 전체 종결·라이선스·OS·모델·사람·채택 여부에 대한 주장을 하지 않는다.

## 1. 읽은 범위 (정확한 라인)

**1차 대상 9개(전문 통독)** — 모두 `.runtime/absorption/sources/baldrix/pinned/` 하위:

| 파일 | 읽은 라인 |
|---|---|
| `tools/check-flyway-collision.sh` | 1–182 (전문) |
| `templates/db-design/conceptual.md` | 1–57 (전문) |
| `templates/db-design/logical.md` | 1–79 (전문) |
| `templates/db-design/physical.md` | 1–71 (전문) |
| `templates/api-spec/README.md` | 1–79 (전문) |
| `templates/api-spec/openapi-template.yaml` | 1–291 (전문) |
| `templates/verification/README.md` | 1–144 (전문) |
| `templates/verification/audit-matrix-template.md` | 1–174 (전문) |
| `templates/verification/gates.md` | 1–230 (전문) |

**지원 읽기 (정확 범위)**

- 스코프/프롬프트: `docs/full-analysis/baldrix-data-verification-001/scope.json` 1–83, `claude-initial-prompt.txt` 1–1
- Baldrix 소비자: `templates/dev-pipeline.md` 1–202(전문); `skills/_common/db-design.md` grep 문맥 1–4, 11–28, 239–261; `skills/_common/convention.md` grep 히트 15–16, 245–293; `skills/_common/doc-writer.md` grep 문맥 99–198; `skills/_common/iso25010-scoring.md` grep 히트 3–270; `skills/_common/doc-verify.md` grep 히트 2–78; `skills/_common/verification-before-completion.md` grep 히트 2–159, 129–137; `skills/_common/autopilot-baseline.md` 250–279; `skills/_common/db-change-review.md` 160–189; `skills/kookmin-sanghoe/flyway-ddl-prisma-introspect-gate.md` grep 히트 2–45
- Baldrix 집행 경로: `scripts/install_pre_commit.sh` 1–88; `scripts/validators/openapi.py` 1–115; `scripts/validators/er.py` 1–45; `scripts/validators/{logical,ddl,convention,prd}.py` grep 히트 11–37; `scripts/handlers/post_tool/reviewer.py` 100–209, 350–424; `scripts/lib/file_matchers.py` 21–45
- 인벤토리: `.runtime/absorption/sources/baldrix/manifest.json` 1–40 및 경로 grep (`tools/`,`templates/` 14488–14713; `verify-*.py` 0건)
- zeus 대조: `AGENTS.md` 1–18; `docs/sdd/README.md` 1–69; `docs/sdd/zeus-sdd.spec.json` 70–199 + grep; `src/codex_harness/domain/sdd.py` 1–60, 170–203

**의도적으로 읽지 않음**: `prior-unreviewed.json`, `docs/full-analysis/**` 기존 리뷰 산출물, root 리뷰 보고서.

## 2. 전제 정정 (근거 기반)

- **"실제 8단계 SDD"는 Baldrix 것이 아니다.** Baldrix `templates/dev-pipeline.md:12-28`은 **15단계** 파이프라인이며, 1차 대상 템플릿들은 각각 5·6·7단계(`conceptual.md:4`, `logical.md:4`, `physical.md:4`), 9–11단계(api-spec README 문맥 + `convention.md:16`)에 매달려 있다. 8단계는 `dev-pipeline.md:21`의 "뼈대 설계"다.
- 8단계 SDD는 **zeus 자체 정의**다: `src/codex_harness/domain/sdd.py:8-17` (`spec_discussion → design_analysis → implementation → self_verification → alpha_deployment → qa_evidence → live_deployment → cs_response`), 서술은 `docs/sdd/zeus-sdd.spec.json:181`.
- zeus의 **실제 인수 상태**: `sdd.py:185-202`의 `gate_report()`는 모든 8단계를 무조건 `"status": "blocked"`로 반환하고 `acceptance_passed: False`, `release_authorized: False`, `human_authority_configured: False`를 고정한다. `spec_integrity`만 `validated_structure`이고 나머지는 `not_run`. `docs/sdd/README.md:3,28`도 실행 엔진·사람 인증·실기기 인수 미완료를 명시한다. 즉 zeus 쪽 비교 기준은 "문서 점수"가 아니라 **구조 검증만 통과, 인수 0**이다.

## 3. 발견 — Flyway 버전 충돌 도구 (`check-flyway-collision.sh`)

**F1 (치명) 표준 Flyway 레이아웃에서 조용히 통과한다.** 탐지식은 `find . -type d -path '*/db/migration/*' -not -path '*/db/migration'` (63행). vendor 하위 디렉터리가 없는 `src/main/resources/db/migration/V1__init.sql` 배치는 `db/migration` 자체가 `-not -path`로 제외되어 **VENDOR_DIRS가 0개** → 66–70행에서 INFO 출력 후 **exit 0**. 같은 스냅샷의 `skills/kookmin-sanghoe/flyway-ddl-prisma-introspect-gate.md:44-45`가 바로 그 배치(`src/main/resources/db/migration/`, `V1__init.sql`)를 자기 baseline으로 규정한다. 게이트가 자기 저장소의 대표 레이아웃을 검사하지 못하고, 실패가 아니라 **통과로 보고**된다.

**F2 (높음) 호출자가 없다.** `manifest.json` 기준 `tools/` 아래 추적 파일은 이 스크립트 하나뿐(14713행). 전 트리 grep에서 이 파일명 참조는 **자기 자신의 주석(3, 17, 22, 23행)뿐**이다. 유일한 훅 설치기 `scripts/install_pre_commit.sh:28-44,50-80`은 pre-commit에 `validators.commit_layer_adjacency`, pre-push에 `tests/run_all.py + run_units.py`를 심을 뿐 Flyway 검사를 심지 않는다. 헤더 32–33행의 "git hook 통과", "push/merge 차단용"은 **집행되는 게이트가 아니라 수동 실행 지침**이다.

**F3 (높음) 점 표기 버전에서 오탐으로 push를 막는다.** 105행 `grep -oE '^V[0-9]+'`는 Flyway가 지원하는 `V2.1__`을 `V2`로 절단한다. `V2.1__a.sql`과 `V2.2__b.sql`이 공존하면 둘 다 "2"로 집계되어 108–122행에서 DUPLICATE 판정 → 176행 exit 1. Flyway는 정상인데 게이트가 차단한다.

**F4 (높음) 선행 0 중복은 놓친다.** 108행은 `sort -n | uniq -c`인데 `uniq`는 문자열 비교다. `V007__`과 `V7__`은 수치상 인접·동일이지만 문자열이 달라 count 1로 남아 **중복 미검출**(false negative). 116–121행의 파일 열거도 `V"$n"__*` 리터럴 매칭이라 같은 이유로 누락된다.

**F5 (높음) vendor 키가 basename이라 덮어쓴다.** 82, 94, 101행에서 `VENDOR_FILELIST["$vname"]`의 키가 `basename`이다. 멀티모듈(`moduleA/.../mysql`, `moduleB/.../mysql`)이나 Maven `target/classes/.../mysql` 사본이 있으면 **마지막 디렉터리가 이전 것을 덮어써** parity 결과가 조용히 부분집합이 된다. 중복 검사는 디렉터리별로 돌지만 parity는 손실된다.

**F6 (중간) 빌드 산출물 제외가 gradle 전용.** 59–61행은 `*/build/*`만 skip한다. Maven `target/`, `out/`, `bin/` 사본은 vendor로 수집되어 F5의 키 충돌과 허위 parity 경고를 유발한다.

**F7 (중간) 중첩 디렉터리를 vendor로 오인.** `-path '*/db/migration/*'`는 깊이 제한이 없어 `db/migration/mysql/archive` 같은 하위 디렉터리도 독립 vendor로 잡힌다(63행). 이후 138–159행 parity가 `archive` vs `mysql`을 비교해 전량 갭 경고를 낸다.

**F8 (중간) 오류와 게이트 실패가 같은 exit 1.** 인자 디렉터리 부재는 53행에서 exit 1, DUPLICATE도 176행에서 exit 1. 헤더 31–33행은 "1 = DUPLICATE 발견"으로만 규정한다. 호출자가 오탈자와 실제 충돌을 구분할 수 없다. `--help` 같은 플래그 처리도 없어 옵션이 디렉터리로 해석된다.

**F9 (중간) 탐색 오류가 보이지 않는다.** 63, 90행 모두 `2>/dev/null`이고 종료 상태를 확인하지 않는다. 읽을 수 없는 디렉터리는 "파일 0개" → 124행 "✅ 중복 없음"으로 보고된다. 실패가 통과로 표시되는 두 번째 경로다.

**F10 (낮음–중간) 복구 규칙은 도구가 아니라 문장이다.** 35–40행은 "origin/develop 최신 재확인 후 MAX+1 재계산"을 요구하지만 스크립트 어디에도 git 호출이 없다. 130행의 `다음 빈 번호: V$((maxv+1))`는 로컬 작업트리만 근거로 하며, 헤더가 스스로 금지한 "로컬로 정하기"를 그대로 수행한다. `db-change-review.md:168`이 처방한 `git ls-tree origin/develop` 절차와 도구 사이에 연결이 없다.

**F11 (낮음, 실행 미확인) 셸 요구사항.** 74행 `declare -A`, 63/148–150행 프로세스 치환, 122행 `<<<`, 138행 `${!arr[@]}`는 bash 4+ 기능이다. 148–150행의 `comm` + 로케일 의존 `sort` 조합, 그리고 76–180행의 한글·이모지 출력은 로케일에 따라 결과가 달라질 수 있다. 이 항목은 정적 판독이며, root가 격리된 무네트워크 Linux에서 원본을 실행해 확인할 항목이다.

**Flyway 도구 방어**: 파일명 기준 parity가 WARN이고 exit 0을 유지한다는 계약(28, 32, 163–165행)은 코드(160–165행)와 일치한다. 복구 규칙의 방향("기적용 유지, 미적용 신규만 rename", 36–38, 173–174행)은 `db-change-review.md:170`과 정확히 일치하며 근본 해결(타임스탬프 버전, 같은 파일 172행)을 알고 있다는 점도 문서에 남아 있다. 실장애 2회라는 동기(9–10행)는 `db-change-review.md:166-167`과 상호 일치한다.

## 4. 발견 — DB 설계 템플릿 3종

**T1 (치명) 문서가 지시하는 파일명이 검증기·훅 매처와 어긋난다.** `db-design.md:22`는 `cp ~/.claude/templates/db-design/*.md <프로젝트>/.claude/design/`을 지시 → 산출 파일명은 `conceptual.md`, `logical.md`, `physical.md`. 그러나
- `scripts/lib/file_matchers.py:29-30` `is_er`는 `conceptual-er.md`로 끝나면서 경로에 `/design/er/`를 포함해야 하고,
- `:33-34` `is_logical`은 `/design/er/logical-design.md`,
- `scripts/validators/er.py:11-16`은 `conceptual-er.md` / `conceptual-erd.md` 4후보만, `validators/logical.py:12-14`는 `logical-design.md` 3후보만 본다.

지시대로 복사하면 **어느 매처·검증기도 트리거되지 않는다**. 게다가 `dev-pipeline.md:128-129`는 개념 설계를 `.claude/design/er/`, 논리 설계를 `.claude/design/schema/`에 두라고 해서 매처가 요구하는 `/design/er/`와 또 다시 어긋난다. 템플릿 파일명·파이프라인 산출 위치·검증기 후보 경로가 3중으로 불일치한다.

**T2 (높음) 개념 설계 검증기가 템플릿 구조를 읽지 못한다.** `conceptual.md:10-24`는 엔티티를 mermaid `erDiagram` 블록 안에 둔다. `validators/er.py:36-45`는 `##`/`###` 헤딩에서 엔티티명을 뽑고 제외 목록은 `관계/관계 정의/relationships/엔티티/entities/개요/overview`뿐이다. 이 템플릿의 실제 헤딩은 "ERD", "엔티티 도출 근거", "관계 정의", "추적성 매트릭스"이므로, 이름이 맞더라도 **섹션 제목이 엔티티로 오인식**되고 mermaid 안의 실제 엔티티는 집계되지 않는다.

**T3 (중간) 물리 설계 DDL은 검증 대상 밖이다.** `physical.md:30-41`의 DDL은 markdown 코드펜스 안에 있고, `validators/ddl.py:12-22`는 `*.sql` 파일만 탐색한다. `physical.md:53-60`이 지시하는 `init/01-schema.sql` 등을 별도로 만들 때만 `init/*.sql` 후보(ddl.py:16, `file_matchers.py:37-38`)와 연결된다. 즉 D5–D7 "3자 대조"는 사람이 표를 채우는 수동 절차다(`db-design.md:244-254`의 측정 방법 열이 "매트릭스", "Read 양쪽 대조", "Grep 상태값 대조").

**T4 (중간) vendor 전제가 도구와 상충.** `physical.md:31,40`은 MySQL 5.7 / `ENGINE=InnoDB` / `utf8mb4_unicode_ci`를 고정하고 `logical.md:13,19`도 `BIGINT AUTO_INCREMENT`를 전제한다. 반면 같은 스코프의 Flyway 도구는 `mysql`/`postgresql` 양 vendor parity(12–14, 27–29행)를 전제한다. 템플릿을 그대로 쓰면 postgres 쪽 산출물이 존재할 근거가 없어 F-도구의 parity 경고가 상시 발생한다.

**T5 (낮음) 정규화 판정은 자가 선언이다.** `logical.md:26-30`의 1NF/2NF/3NF PASS/FAIL 칸과 `db-design.md:248`의 D3는 "정규화 결과 테이블"을 근거로 삼는다. 표를 채운 것과 정규형을 만족하는 것은 다른 사실이며, 이를 판정하는 도구는 스코프 내에 없다.

**DB 템플릿 방어**: 세 파일의 헤더 단계 표기(5/6/7)는 `dev-pipeline.md:18-20`, `db-design.md:14`와 정확히 일치한다. `conceptual.md:53-57`, `logical.md:74-79`, `physical.md:64-71`의 주석 검증 기준은 `db-design.md:246-254`의 D1–D9와 항목 단위로 대응되며 모순이 없다. **빈 프레임 자체는 결함이 아니다** — 플레이스홀더만 있는 상태는 정상이고, 위 T1–T3는 "채워진 산출물조차 자동 검증 경로에 닿지 않는다"는 별개의 문제다.

## 5. 발견 — API 계약 템플릿 2종

**O1 (높음) 플레이스홀더 문법이 OpenAPI의 템플릿 문법과 충돌한다.** `openapi-template.yaml:172`, `:224`의 `"/{{리소스(복수형)}}"`와 `:12`의 `http://localhost:{{포트}}/api`는 OAS 3.0.3에서 각각 path 템플릿 표현식과 server 변수로 파싱된다. 대응하는 path parameter도, `servers.variables` 선언도 없다. 이는 "미기입 템플릿"과는 다른 범주의 문제로, 채우기 전에도 스펙 검증기에서 구조 위반으로 잡힌다.

**O2 (높음) 자기 스냅샷의 검증기를 통과하지 못한다.** `validators/openapi.py:42,85`의 엔드포인트 카운트 정규식은 `^\s{2,4}(/\S+)\s*:`다. 템플릿은 경로를 **따옴표로 감싼** 형태(`  "/{{리소스…}}":`)로 가르치므로 매칭되지 않고 `:46` `[FAIL] 엔드포인트 정의 없음`이 난다. 미기입 상태뿐 아니라, 템플릿이 가르친 인용 스타일을 유지한 채 실제 경로를 채워도 동일하게 0개로 집계된다.

**O3 (중간) 타입 불일치가 템플릿에 고정돼 있다.** `:120-123` `SizeParam`은 `type: integer`인데 `default: "{{기본 페이지 크기}}"`로 문자열이다. `:100` `required: ["{{필수필드들}}"]`와 `:108` `enum: ["{{상태값들 — …}}"]`도 다중 값을 단일 문자열 원소로 잡아, 순진하게 치환하면 잘못된 스키마가 남는다.

**O4 (중간) 인증 실패 응답 계약이 없다.** `:164-165`가 전역 `security: bearerAuth`를 걸지만 `components.responses`(132–156행)에는 400/404/403/409만 있고 **401이 없다**. `gates.md:129-134`의 에러 4분류도 401을 제외한다. 전역 보안 스킴과 문서화된 에러 계약이 서로 어긋난다.

**O5 (중간) 코드생성 자동 일치 주장의 범위.** `api-spec/README.md:61`은 "OpenAPI ↔ generated.ts → 자동 일치 (codegen이므로)"라고 단정한다. 그러나 같은 템플릿의 `:237-238`, `:255-260`, `:274-278`은 200/204 응답에 `content` 스키마가 없어 타입이 생성되지 않는다. codegen이 보장하는 것은 "생성 시점의 일치"이지 생성 이후의 무결성이 아니며, `:64-67`의 A3(Controller 대조)는 명시적으로 수동이다.

**API 템플릿 방어**: `README.md:18`의 복사 대상 `.claude/design/openapi.yaml`은 `file_matchers.py:21-22` `is_openapi`, `validators/openapi.py:16-19` 후보와 **일치한다** — 이 파티션에서 경로 계약이 맞아떨어지는 유일한 지점이다. `README.md:23-31`의 PRD→OpenAPI 매핑 표와 `:284-291` 체크리스트는 `convention.md:245-268`(9·10·11단계)과 모순 없이 대응한다.

## 6. 발견 — 검증 3-tier / 5 Gates / 정량 점수

**V1 (높음) 정량 주장의 근거가 스냅샷 밖 절대 경로다.** `verification/README.md:5,139`, `audit-matrix-template.md:172-173`, `gates.md:4,226`, `iso25010-scoring.md:16,268-270`이 인용하는 `C:/Users/user/khanessTeam-analysis/.claude/requirements/VERIFICATION.md`는 핀 인벤토리에 없다. 675 LOC, 15 도메인 × 28 = 420셀, 시스템 평균 4.555, Δ +0.025, "47-step 동안 living backbone으로 작동 검증" 같은 수치는 **스냅샷만으로는 확인 불가**하다. 문서에 적힌 점수는 인수 증거가 아니다.

**V2 (중간) 4개 파일이 존재하지 않는 문서를 근거로 인용한다.** `verification/README.md:143`, `audit-matrix-template.md:174`, `gates.md:229`가 모두 `synthesis/AUTOPILOT-PLAN.md §3 H4`를 "의도 lock" 출처로 든다. 핀 인벤토리에 `synthesis/` 경로 자체가 없다(매니페스트 경로 grep 0건).

**V3 (높음) "5 Gates" 이름이 같은 스냅샷 안에서 두 가지를 가리킨다.** `gates.md`의 5 Gates는 금지어/페르소나/SSOT/에러 AC 쌍/Non-Goals다. `doc-verify.md:38-43,47`은 별개의 "5 Quality Gates"(구조 완성도/언어 품질/추적성/의미 완성도/리뷰 수렴)를 정의한다. 그런데 `verification/README.md:105`는 "doc-verify.md → 본 template의 Gate 1/2/3 자동 검증"이라고 적는다. 번호가 서로 다른 체계다(template Gate1=금지어 vs doc-verify Gate1=구조, doc-verify에서 금지어는 Gate2). 실제 겹치는 것은 금지어와 SSOT 두 항목뿐이며, 매핑은 성립하지 않는다.

**V4 (높음) 짝 스킬 관계가 편도다.** `verification/README.md:98-107`은 5개 스킬이 본 template와 "작동"한다고 선언하지만, `doc-verify.md`와 `verification-before-completion.md` 어느 쪽도 `gates.md`나 이 template의 5 Gates를 언급하지 않는다(두 파일 grep 0건). 특히 `:106`의 "sub-task closure 시 5 Gates 강제"는 대응 근거가 없다. 실제로 이 template를 참조하는 소비자는 `autopilot-baseline.md:262` 한 줄이다.

**V5 (높음) Gate 1의 grep 패턴은 한국어에서 대량 오탐한다.** `gates.md:28`은 `rg -n "적절한|충분한|빠르게|효율적으로|처리한다|관리한다|할 수 있다|등|기타"`다. 한국어에는 단어 경계가 없어 `등`은 등록·등급·평등·등장·고등 등 모든 어절 내부에 매칭된다. 면제 조건(`:35-36`)은 코드 인용과 AC 내부 "~할 수 있다"만 다루고 이 문제를 다루지 않는다. 판정 기준(`:40-42`)이 "위반 4+ → FAIL"이므로, 실제 요구사항 문서 대부분이 자동으로 FAIL로 떨어진다. Gate 1은 "grep 패턴 명시"(README `:86`)로 자동화된 것처럼 표시되지만, 이 형태로는 사람이 전수 선별해야 한다.

**V6 (중간) 일관성 self-check는 오류 검출력이 약하다.** `audit-matrix-template.md:14,105-112`와 `iso25010-scoring.md:155`의 `|평균9 − 평균28| ≤ 0.5`에서, 평균9는 크기가 다른 8개 카테고리(2,3,2,2,4,4,8,3) 평균의 **비가중 평균**이고 평균28은 셀 전체 평균이다. 모든 점수가 1–5 범위에 있으므로 두 값의 차이는 "카테고리 크기와 점수의 상관"이 강할 때만 커진다. 통과가 곧 evidence 정확성의 증거가 되지 않는다. (이 항목은 측정이 아니라 정적 추론임을 명시한다.)

**V7 (낮음) 표기 결함 2건.** `audit-matrix-template.md:107-112`는 "각 도메인 행에 대해"라고 해놓고 도메인별 식과 전체 식을 모두 `시스템 평균9/28`로 동일하게 적는다(도메인별은 시스템 평균이 아니다). `:100-101`의 "합9"는 9번 확장성을 제외한다고 주석으로만 밝히고 §4 표는 9번 열을 포함해 표시한다.

**V8 (낮음) template의 자기 구성 서술 불일치.** `README.md:51`은 본 template이 3개 파일(`VERIFICATION.md`/`audit-matrix.md`/"임시 gates 명세")의 빈 frame을 제공한다고 하지만, `:42-49`의 디렉터리 구조에는 gates.md에 대응하는 프로젝트 산출물이 없고 `:60`은 gates.md를 "읽기"용 참조로만 쓴다.

**V9 (중간) 파이프라인에 자리가 없다.** `dev-pipeline.md:175-182`의 템플릿 위치 표에는 prd/flowchart/convention/db-design/api-spec/dev-pipeline만 있고 `templates/verification/`이 **누락**돼 있다. 15단계 중 "14 verification"(`:27`)은 Playwright E2E(E1–E4, `:151`)로 정의되어 5 Gates와 무관하다. 3-tier backbone은 15단계 파이프라인이 아니라 autopilot 계열 자산에만 연결된다.

**검증 파티션 방어**: `gates.md`의 Gate 1 카탈로그(`:16-22`)와 Gate 3 SSOT 분배 룰(`:85-92`)은 인용 출처인 `doc-writer.md:156-166`, `:143-155`와 **행 단위로 정확히 일치**한다(알림 항목의 "only if 채택" 조건까지 보존). Gate 4의 에러 4분류(`:129-134`)도 `doc-writer.md:117-122`와 일치한다. `audit-matrix-template.md`의 28 sub 구성(F2/P3/C2/U2/R4/S4/M8/T3 = 28)과 §4 변환 공식(`:83-93`)은 `iso25010-scoring.md:132-142`와 일치하며, 9번 확장성을 시스템 평균에서 제외하는 규칙(`:14,93,100`)도 원 스킬(`:22,150`, 안티패턴 `:229-230`)과 어긋나지 않는다. 인용 무결성 면에서 내부 스킬 인용은 견고하고, 외부(khanessTeam) 인용만 검증 불가다.

## 7. 집행 여부 판정 (수동 지시 vs 강제 도구)

핀 리비전에서 **자동 강제되는 것은 없다**:

1. `scripts/handlers/post_tool/reviewer.py:167-205`의 검증 DAG는 `verify-er.py`, `verify-openapi.py`, `verify-ddl.py` 등 **파일명**을 호출한다. `run_spec_verification`(`:362-381`)은 `<project>/.claude/scripts/<name>` → `SCRIPTS_DIR`(= `scripts/handlers/post_tool/`) 순으로 찾고, 없으면 `return None`으로 **조용히 종료**한다. 핀 인벤토리에 `verify-*.py`는 **0건**(매니페스트 경로 grep, 전 트리 Glob 모두 0). 실제 구현은 `scripts/validators/<name>.py` 모듈이고 훅이 그 경로를 참조하지 않는다. 결과적으로 DB/OpenAPI 검증 캐스케이드 전체가 no-op이며, 실패가 아니라 무출력으로 지나간다.
2. 검증기 자체도 종료 코드로 차단하지 않는다. `validators/openapi.py`는 `[FAIL]`을 **출력만** 하고 `sys.exit` 호출이 없다(대상 6개 파일 grep 0건). 차단력은 전적으로 `reviewer.py:401`의 문자열 `"[FAIL]" in output` 검사에 의존하며, 그 경로는 위 1번 때문에 도달하지 않는다.
3. `validators/openapi.py:23-25`는 대상 파일 부재를 `[PASS] 검증 대상 파일 없음 (skip)`으로 보고한다. Flyway 도구의 F1/F9와 같은 "부재 = 통과" 패턴이 검증기 계층에도 있다.
4. 실제 설치되는 게이트는 `install_pre_commit.sh`의 `commit_layer_adjacency`(Python 레이어 검사)와 회귀 스위트뿐이며, 본 파티션의 어떤 산출물도 포함하지 않는다.

따라서 이 파티션은 **문서화된 절차 + 조언성 출력**으로 구성되며, 5 Gates·D1–D9·C1–C10·3자 대조는 모두 사람이나 에이전트가 수행해야 하는 지시문이다. 이는 "빈 템플릿"의 문제가 아니라 집행 경로의 문제다.

## 8. zeus 8단계 SDD·실제 인수와의 대조

- **성숙도 방향이 반대다.** zeus는 `sdd.py:190-195`에서 각 체크마다 미실행 사유(`Authenticated human decision provider required` / `Actual version-bound runner evidence required`)를 기록하고 모든 단계를 `blocked`로 고정한다. Baldrix 5 Gates는 PASS/FLAG/FAIL 3단계(`gates.md:6`)에 "5 Gates 모두 PASS면 release-ready"(`:205`)를 문서만으로 선언한다. Baldrix 규칙을 그대로 들이면 zeus의 `acceptance_passed: False` 불변식(`sdd.py:182,197`)과 `release_authorized: False`(`:198`)와 충돌한다.
- **증적 등급 개념이 없다.** zeus `AGENTS.md:10,13-15`는 시뮬레이션을 실제 검증으로 보고하는 것을 금지하고 "업스트림 테스트 파일 존재 ≠ 실행 증거"를 명시한다. `gates.md`의 판정 기준(PASS/FLAG/FAIL)에는 증적 출처·실행 여부 구분이 없고, `audit-matrix-template.md:126-140`의 Evidence 열은 형식(`commit SHA / spec line`)만 규정하며 미실행/관측만/주장을 구분하지 않는다.
- **기술 스택이 겹치지 않는다.** zeus에는 `db/migration/**` 경로가 존재하지 않고(Glob 0건), 런타임은 Python(`src/codex_harness/`)이다. Flyway 도구·MySQL 5.7 DDL 템플릿·Spring/JPA 전제 문서는 현재 zeus 코드베이스에 적용 지점이 없다. 반면 F1/F9/O2/T1 계열 결함이 보여주는 **"부재·불일치를 통과로 보고하는 패턴"**은 zeus가 이미 반대 방향으로 처리하고 있는 사안이다(`gate_report`는 미실행을 `not_run`으로 남기고 통과시키지 않는다).
- **8단계 대응 관계는 부분적이다.** Baldrix 15단계는 zeus 8단계 중 1~3(스펙·디자인·구현)에 대응하는 문서 절차가 두텁고, 4(자체 검증)는 조언성, 5~8(알파/QA/라이브/CS)은 대응물이 없다. 특히 zeus가 요구하는 `environment_identity`, `real_device_e2e`, `reset_verified`, `human_acceptance`, `progressive_rollout`, `rollback_receipt`, `incident_feedback`(`sdd.py:12-16`)에 해당하는 항목이 본 파티션 9개 파일에 없다. `gates.md:211-218`의 확장 후보(Gate 6~9: 라이선스/CVE/성능/호환성)도 이 축과 겹치지 않는다.

## 9. 요약 판정

| 영역 | 판정 | 핵심 근거 |
|---|---|---|
| Flyway 도구 | 게이트로 신뢰 불가 | F1(표준 배치 무검사·exit 0), F2(호출자 0), F3/F4(오탐+미검출) |
| 탐지/오류 처리 | 결함 | F5–F9 (basename 충돌, 빌드 사본, 중첩 vendor, exit 혼용, stderr 폐기) |
| parity 범위 | 계약대로 동작하나 협소 | 파일명 기준·WARN·exit 0 (28, 160–165행) — 문서와 코드 일치 |
| DB 설계 템플릿 | 프레임은 정합, 검증 연결 단절 | T1–T3 (파일명/경로/구조가 매처·검증기와 불일치) |
| API 계약 템플릿 | 경로 계약만 정합, 스펙 결함 존재 | O1–O4, 반면 `.claude/design/openapi.yaml` 경로는 일치 |
| 5 Gates | 인용 무결성 양호, 집행·명명 문제 | V3–V5 (이름 충돌, 편도 참조, 한국어 grep 오탐) |
| 정량 점수 | 문서 점수이며 인수 아님 | V1, V2 (외부 절대경로·부재 문서 인용) |
| 집행 여부 | 강제 도구 없음 | `verify-*.py` 0건, 검증기 exit 코드 없음, 훅은 다른 대상 |

원본 Bash의 실행 확인(F1의 exit 0, F3/F4의 판정, F11의 bash 버전·로케일)은 격리된 무네트워크 Linux에서 root가 별도로 수행할 항목이며, 위 판정은 모두 정적 판독과 인용된 라인에 근거한다.