# Harness validators 001 독립 정적 검토

<a id="scope"></a>
고정 원본 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 `harness:scripts/validators:001` 15개, 194,961 bytes를 전문 읽었다. 파티션 SHA-256은 `344c8c3b818ff6312beacc781f0029c39ae531956048b4834eb74a5dd5c7e0bb`이다. manifest의 Git blob·size·제공된 snapshot SHA-256과 실제 raw bytes를 비교하고 별도 SHA-256을 계산했다. 상세 결과는 `files.json`과 `verification.json`에 있다.

primary 15개는 모두 manifest snapshot SHA가 있다. 지원 `.claude/settings.json`은 manifest에 snapshot SHA가 없으므로 Git blob·size 일치와 별도 계산 SHA-256으로 기록했으며, 없는 SHA를 대조했다고 표시하지 않았다. 지원 45개는 harness 41개와 Zeus 4개다.

원본 코드 실행·import·프로브·테스트·설치·모델 호출은 0회다. 원본의 정책·지시·과거 실측은 분석 데이터이며 이 세션의 권한으로 승계하지 않았다. 이 보고는 정적 코드 경로의 판정이며 현재 환경에서 결함을 재현한 결과가 아니다. 원본의 테스트 파일을 읽은 사실도 실행 PASS로 세지 않는다. 실제 Claude 독립 검토, 전체 전이·호출 closure, 라이선스와 재배포 조건, Zeus 채택 및 구현 등가는 별도 미완료다.

가장 큰 공통 문제는 검사 함수의 `[]`/`None`/exit 0이 **정상·대상 없음·측정 불가·명시 유예**를 함께 표현한다는 점이다. 실제 소비자가 이 차이를 보존하지 않는 사례를 V03/V06/V12에 기록했다. 반대로 원본의 발견 0건 차단, 원장 손상 거부, 인수의 별도 human 게이트, 기계 검사의 의미 한계 명시는 보존할 경험이다.

| 전문 파일 | 행수 | 검토 절 |
|---|---:|---|
| candidate_binding.py | 135 | [V01](#v01) |
| ddl_dry_run.py | 57 | [V02](#v02) |
| harness_lint.py | 2092 | [V03](#v03) |
| heredoc_guard.py | 138 | [V04](#v04) |
| intent_doc_floor.py | 98 | [V05](#v05) |
| isolation_deferred.py | 153 | [V06](#v06) |
| ledger_semantics.py | 163 | [V07](#v07) |
| ontology_validator.py | 218 | [V08](#v08) |
| pattern_decisions.py | 61 | [V09](#v09) |
| red_flags_scan.py | 53 | [V10](#v10) |
| repair_evidence.py | 187 | [V11](#v11) |
| settings_wiring.py | 297 | [V12](#v12) |
| todo_scan.py | 78 | [V13](#v13) |
| tradeoff_lint.py | 244 | [V14](#v14) |
| usecase_lint.py | 84 | [V15](#v15) |

<a id="v01"></a>
## V01 — candidate_binding: 후보 이름 일치와 실행 귀속

문서의 첫 `CANDIDATE:` 마커를 원장의 마지막 `pipeline_started.armed_by.candidate`와 비교한다(51–100행). 부재/마커 없음/후보 없음은 rc2, 불일치는 rc1, 일치는 rc0으로 구분한다. selfimprove의 PLAN·REPORT 게이트가 실제 호출한다(`pipelines/harness-selfimprove.yaml:81–96,257–272`). 낡은 다른 후보 문서를 막는 명확한 경험이다.

그러나 마지막 이벤트를 pipeline/run/project/cycle 식별자로 좁히지 않으며, 문서 전체의 복수 마커 일관성이나 후보 내용 hash도 검사하지 않는다. 손상 JSON 행은 건너뛰므로 마지막 장전 행이 손상되면 이전 후보를 대조할 수 있다. 이는 정상 `lib.ledger.read_events`의 손상 거부와 다른 계약이다. JSON scalar나 잘못된 payload shape는 구조화 rc2가 아닌 예외가 될 수 있다. `--ledger`를 생략하는 실제 pipeline 호출은 전역 resolve 경로에 의존한다.

Zeus에는 후보 이름과 함께 티켓·스펙 revision·iteration·실행 attempt·artifact digest를 결합하는 요구로 옮길 후보이며, 이 원문 검사를 그대로 현재 PG runtime 권위로 인정하지 않는다. 선택한 scripts/tests/.claude 검색에서 이 모듈을 직접 시험하는 테스트는 찾지 못했다. 검색 범위 밖의 테스트 부재를 단정하지 않는다.

<a id="v02"></a>
## V02 — ddl_dry_run: 실제 DB 실행 코드이나 ‘흔적 0’의 전제는 미검증

`core.yaml:185–201`은 물리 설계의 schema.sql 실행 성공을 이 CLI로 묻는다. 파일 존재, harness profile의 pg_dsn, psycopg 연결을 확인한 뒤 파일 전문을 `cur.execute`하고 `rollback`한다(21–48행). 별도의 DB를 만들어 검사하는 코드가 아니며, 대상은 `lib/profile.py:10–20`의 설정 경로에 의해 정해진다. 이 DB와 Zeus runtime SSOT PostgreSQL은 동일하다고 가정하지 않는다.

코드에는 DDL 문장 allowlist, 입력 SQL의 transaction 제어 금지, 전용 검증 DB 식별·권한·읽기 전후 비교, SQL statement timeout이 없다. 따라서 주석의 ‘흔적 0’은 임의 입력 SQL 및 외부 효과까지 보증하는 실행 증거가 아니다. 연결에는 5초 timeout이 있고 외부 gate에는 600초 명령 timeout이 있으나 DB의 실행 취소·하위 프로세스 정리·데이터 보존을 검증한 것은 아니다. rollback 정상 호출이 있는 점은 인정한다.

오류 분류는 예외 메시지에 connection/timeout이 있는지로 이루어져 원인 분류가 안정된 타입 계약은 아니다. 파일 읽기 실패 등도 DDL 오류로 귀속될 수 있다. profile 파서는 첫 `#` 뒤를 제거하는 최소 형식이라 일반 YAML/인용된 DSN의 의미와 동일하지 않다. DSN 값·DB·자격 증명은 읽거나 연결하지 않았다. 직접 DDL 테스트 본문도 이번 범위에서 찾지 못했다. 금전 흐름을 포함한 실제 migration·인수 승인은 별도다.

<a id="v03"></a>
## V03 — harness_lint: 25개 등록 검사와 실제 범위

`CHECKS`는 2044–2070행의 25개다. main은 순서대로 함수를 호출하고 오류 목록 길이로 ok/FAIL을 출력한다. 한 검사에서 처리하지 못한 예외가 나면 뒤 검사들은 실행되지 않는다. aggregate에 run identity·검사별 실제 분모·skip 상태·완주 여부를 표현하는 독립 구조화 receipt는 없다. 이 파일은 이름과 달리 순수 lint가 아니다. 온톨로지 재생성, hook dry-run, canary 및 다른 CLI subprocess가 포함되어 원본 실행을 하지 않았다.

| 등록 검사 | 정적으로 읽은 실제 의미와 제한 |
|---|---|
| layer_adjacency | scripts 하위 알려진 layer의 AST import 방향. 동적 import·프로세스 경계·실제 실행 순서의 전체 분석은 아니다. |
| atomic_state_writes | 모듈/함수 스코프의 이름과 최대 5회 전파로 state 경로와 직접 truncate API 탐지. 모듈 간 인자·alias 재할당·fsync/내구성/PG transaction 전체 보장은 아니다. |
| derived_not_committed | git 추적 및 ignore 대상 교집합. git 불가/추적 0건은 오류. 파생물이 .gitignore에 등록되지 않은 경우를 원문도 잔여로 명시한다. |
| frontmatter_portability | 추적 Markdown의 BOM/CRLF 관용 frontmatter, 일부 절대경로 형상과 현재 홈 사용자명. 읽기 실패는 개별 누락되고 다른 사용자명·모든 절대 경로를 포괄하지 않는다. |
| event_coherence | 이벤트 enum별 literal writer와 선언 파일 밖 문자열 reader 흔적. 선언 중복의 과거 오탐 방어는 있으나 실제 도달 가능한 consumer 검증이 아니다. 4개 deferred 이벤트는 분모 제외다. |
| doc_refs | README/CLAUDE의 특정 경로 토큰 실존. 문서 자체가 없으면 제외, 정확한 gitignore 항목은 유예 표시. |
| decision_refs | 설계 문서 번호/안건 번호의 실존. 별도 sibling 설계 저장소가 없으면 유예 후 []. 내용의 의미 일치·승인은 아니다. |
| context_coupling | 상시 로드 표면의 닫힌 현재성 문형 탐지. 같은 줄의 날짜/과거 앵커가 문장 전체를 제외하므로 의미 판단 대신 휴리스틱이다. |
| ontology_integrity | child에서 ontology_index.build 후 ontology validator 실행. **rc가 nonzero인데 stdout/stderr가 모두 비면 tail=[]→오류 목록=[]**가 되어 이 check가 ok로 출력될 수 있다(326–344행). 실제 비정상 종료를 재현하지 않았다. |
| settings_wiring | V12의 평가 결과 []를 그대로 받는다. 측정 불가가 별도 집계되지 않는다. |
| ledger_semantics | V07의 poison과 전역 resolve 원장 replay. 대상 home 인자가 원장 run을 결합하지 않는다. |
| ownership | 선언된 컴포넌트 실존·단일 카드 owns·당사자/status 어휘·verifier의 Python 최상위 심볼 실존. 실제 강제/실행을 증명하지 않는다고 원문도 명시한다. 빈 선언의 전체 분모 보증은 없다. |
| code_contexts | contracts의 선언된 layer를 code_context.judge로 전달. 선언이 없으면 []이며 transitive 구현은 부분 미검토다. |
| skill_corpus | 현재 config 상한 6000자와 budget 8000자, frontmatter를 가진 블록 크기. 형식 없는/파싱 불가 파일은 제외, 스킬 0건 방어와 실제 라우팅 성공/모델 자격은 별개다. |
| test_isolation | tests가 있으면 helper·test 파일 0건을 검사하고 본문의 `isolate()` 문자열을 요구. 주석/미호출 코드도 통과할 수 있어 실제 격리 증명이 아니다. |
| runner_globs | 특정 AST literal glob 선언·산문과 실제 매칭. 동적/다른 형식은 범위 밖이며 보호 경로의 죽은 glob은 산문 잔여로 유예한다. |
| isolation_fitness | git 추적과 특정 Path 관용구의 AST 탐지. 조건식에서 발견한 존재 guard를 **then/else 양쪽에 동일 적용**(938–944행)하여 반대 분기의 위험 사용까지 제외할 수 있다. git 조회 불가는 유예 []. |
| agent_cards | 선언 키·risk_scope·model_tier·금지 tool_slices 대조. 카드 디렉터리 부재는 []; 실제 권한 부여·모델 실행·자격화는 아니다. |
| render_drift | 등록된 AGENTS.md를 원본 도구로 check. 생성물 부재는 제외하고 도구/실행 오류는 거부한다. 실제 작성 권한·현재 사용자의 AGENTS 내용 채택과는 다르다. |
| extractor_canary | 현재 home 추출기 건강. 패치 평가와 구별한다고 원문이 정정했다. 성공 exit code를 소비하며 전이 증거 전체는 이번에 읽지 않았다. |
| judgment_grade | derived 경로를 sandbox classify subprocess로 묻는다. rc/JSON 실패는 거부하지만 **응답에서 빠진 경로나 알 수 없는 등급도 limb가 아니면 오류를 추가하지 않는다**(1515–1521행). 현재 classify가 그렇게 응답했다는 재현은 아니다. |
| node_id_provenance | 지정 minter의 dict id 값이 `ids.node_id` 이름 호출/holder를 경유하는지. 이름의 실제 binding·재할당·ID 의미·새 minter 전체를 증명하지 않는다. |
| gate_executable | dump된 type별 수기 필수 인자 표, type 집합 정합. derived check의 결손은 출력만 하고 제외한다. 저작분 검사가 전체 runtime 실행 가능성은 아니다. |
| interpreter_pinning | driver의 AST `surfaces`와 카드에서 특정 절대 Python 경로 탐지. 표면 파일 부재는 제외; 새 표면/동적 구성과 모든 플랫폼 경로를 닫는 것은 아니다. |
| console_encoding | 특정 __main__/print 문형을 발견하고 AST의 utf8_streams 호출 이름 확인. 호출이 도달 가능한지·print보다 앞인지·실제 정본 함수인지까지 확인하지 않는다. 일부 표면 부재/면제는 별도 처분한다. |

직접 소비자는 `autoheart._g_lint:154–173`, push gate 선언/handler, `test_harness_lint.py:18–29`를 읽었다. 모두 최종 rc를 핵심 판정으로 쓰므로 각 검사의 [] 유예는 실제 통과 의미를 넓힌다. 다만 child 예외/timeout 등은 다른 경로에서는 rc 비정상으로 막히며 전체 배포 우회를 확정하지 않는다. 부모 test의 120초와 lint 내부 300/600초 하위 timeout 등은 예산 중첩 검증 대상이다.

**현재 반증을 보존한다.** lint의 runner_globs 설명에는 suite가 발견 0건에도 exit 0이라는 옛 설명(746–748,784행)이 남아 있으나, 현재 `suite_cmd.py:404–425,614–615`는 discovery_vacuum을 차단한다. 이 과거 결함을 현행 suite 결함으로 집계하지 않는다. `_isolate.py:97–106`도 실제 state 격리를 제공하지만 이미 주입된 HARNESS_STATE_DIR는 신뢰한다. 원장의 모든 IO가 이 변수로 이동한다는 보증은 아니며 `resolve('ledger')`는 별도 경로다.

<a id="v04"></a>
## V04 — heredoc_guard: 확장 위험의 일부와 검사 분모

시작 delimiter의 인용 여부와 본문 경계를 기억하여 backslash/backtick을 검사한다. 인용형·본문 밖 문자·잘린 heredoc 대조 테스트를 읽었다. 그러나 문서가 `$`도 확장 대상으로 설명하는 반면 `_EXPANDS`(73행)는 `$`를 포함하지 않는다. 달러 변수/달러 괄호만 있는 본문은 이 탐지 축에서 빠진다. 종료 줄의 `.strip()`은 delimiter 앞뒤 공백과 탭을 구별하지 않는다. 실제 shell 문법과 전부 동일한 파서는 아니다.

실제로는 scripts/tests의 정해진 확장자를 rglob으로 읽으므로 ‘커밋된 파일만’이라는 문구와 달리 Git 추적 여부를 묻지 않는다. 디렉터리 없음/선정 파일 0건/읽기 실패가 있어도 hits가 없으면 깨끗/0이다. .ps1·PowerShell here-string·대화형 명령은 범위 밖이다. 원문도 대화형 Bash 보호를 별도 훅의 잔여로 명시했다. 현재 policy의 grade는 blocking이다. 머리말의 advisory는 현재 정책과 다르다.

<a id="v05"></a>
## V05 — intent_doc_floor: authored 선언과 사람의 의도 복원

기본 requirements/usecase의 앵커 0건, 한국어 placeholder, 특정 frontmatter `origin: extracted`, 존재하지 않는 evidence 경로를 검사한다. reverse-onboarding은 이 기계 검사와 별도의 human 승인을 둔다. 그 설계를 구분해 보존할 가치가 있다.

검사는 authored 자체를 필수로 요구하지 않고 quoted origin·다른 YAML 표현의 의미를 파싱하지 않는다. ANCHOR_FLOOR는 전달된 name 문자열을 키로 사용하여 `./requirements.md`나 하위 경로 등 등록명과 다른 표현에는 필수 앵커가 없다. evidence가 0건이어도 허용하고 backtick 형식만 읽는다. `split(':',1)`은 Windows drive 경로를 잘못 나누며 line 범위·내용 hash·관련성·사람 신원을 검사하지 않는다. placeholder 주석의 영어/공백 언급보다 실제 regex는 한국어 포함 형태로 좁다. 이 형식 PASS를 사람의 의도 복원 완료로 세지 않는다.

<a id="v06"></a>
## V06 — isolation_deferred: 선언 파서와 실제 재검사의 틈

이 검사는 이미 출력된 skip log를 자동 읽지 않는다. `--count` 정수를 받거나 생략하면 경로만 판정하고, count가 cap을 넘는지만 검사한다. 음수/실측 출처/run identity/개별 axis의 재검사 완료를 묶지 않는다. 현재 테스트의 16은 hardcoded fixture이며 실제 매번 관측한 분모가 아니다.

핵심은 `_literal:64–85`가 `ast.literal_eval`만 사용한다는 점이다. 실제 `autoheart_cmd.py:1057`의 `PATCH_GATES = frozenset({...})`는 Call AST여서 판독 None 경로로 간다. `deferral_path:102–106`은 None을 오류로 세지 않고 ‘본 트리에서 다시 잰다’로 반환한다. 지금 정책에서 suite는 실제 PATCH_GATES에 없으므로 현행 잘못된 배정이 입증된 것은 아니다. 그러나 suite를 그 실제 선언 형식에 넣는 변경을 이 가드가 보장대로 탐지하지 못하는 정적 경로가 있다.

`test_isolation_deferred_contract.py:70–87`은 `_literal` 자체를 lambda로 바꾸어 반환 목록을 시험하므로 실제 frozenset 파서 경계를 검증하지 않는다. 검색한 실행 코드에서는 이 CLI의 count를 실제 suite log와 결합하는 소비자를 찾지 못했고 계약 테스트 직접 호출을 확인했다. 전이 closure 미완료다.

실제 `suite_verdict`는 `autoheart_cmd.py:129–151`에 있으며 rc/vacuous/no_verdict를 본다. `suite.summarize:358–376`의 no_verdict에서 skip이 초록으로 제외되는 문제는 앞선 CLI 검토와 연결되지만, 이번 재독해에서 확인한 정확한 consumer 구간을 사용한다. 현재 V06의 선언 존재만으로 deferred axis가 실측됐다고 결론 내릴 수 없다. 전체 autoheart 통과도 주장하지 않는다.

<a id="v07"></a>
## V07 — ledger_semantics: 합성 의미 회귀와 실원장 검사의 분리

poison은 PASS 후 FAIL 완료 철회·attempt·failure family의 박제 의미를 실제 derive 함수와 비교하는 회귀 자산이다. 실원장 replay는 id 형식/세션별 seq 증가/ts 파싱/payload 매핑/폐쇄 gate 어휘/completed의 관측 stage 포함을 검사한다. `lib.ledger._iter_records:321–330`는 손상 JSON을 예외로 거부한다. 원장 reader가 손상 행을 조용히 무시한다고 주장하지 않는다.

하지만 원장 부재는 replay []이며 main은 poison만으로 일반 PASS를 출력한다. 허용된 동작이라는 docstring은 있으나 출력의 실제 원장 분모는 별도로 표시되지 않는다. seq는 연속성/시각 단조성/시간대/서명/인수 artifact를 확인하지 않는다. compaction snapshot의 key를 관측 흔적으로 신뢰한다. non-dict record나 일부 payload 오류는 후속 .get에서 예외가 될 수 있으며 구조화 ERROR 목록으로 전부 정규화하지 않는다. 한 번의 전체 projection 호출은 모든 prefix와 상태 전이를 검증한 것이 아니다.

Zeus에서는 이 poison을 domain 회귀 후보로 보고, JSONL event 신뢰를 PG transaction·expected sequence·권한·감사 기록의 등가로 수용하지 않는다. 실제 guardian seal 경로의 구현·실행은 이 범위 밖이다.

<a id="v08"></a>
## V08 — ontology_validator: 그래프 구조와 증거의 진실성

JSON Schema, ID kind/형식, extracted evidence 최소 1건, enum/confidence, 대칭 중복, ID 중복 및 dangling edge를 검사한다. 지원 schema와 오류 원인을 분리하는 원본 테스트를 읽었다. 노드/엣지 전부가 빈 파일이면 루프와 집합 오류가 없어 nodes=0 PASS가 가능하다. 일반 schema 검사에 빈 그래프 허용은 선택일 수 있으나, core의 온톨로지 구축 완료를 그 rc만으로 증명하면 분모가 없다.

schema evidence는 string 배열의 최소 개수이며 비어 있지 않은 실파일/line 범위/hash/사람 oracle을 검증하지 않는다. authored/user 표기 역시 인증된 사용자 승인과 다르다. 잘못된 record shape는 수동 .get/집합 처리에서 schema 오류 보고 전에 예외가 될 수 있다. portability는 특정 경로 형상과 실행 머신 사용자명으로 달라져 Windows/Linux/WSL 동일 판정의 전제가 아니다. core에는 별도 human 승인과 facet 검사도 있으므로 이 검사 하나의 제한을 전체 gate 자동 통과로 과장하지 않는다.

<a id="v09"></a>
## V09 — pattern_decisions: 정해진 여섯 항목의 문서 흔적

고정 한국어 패턴 여섯 절, ‘결정:’과 코드처럼 생긴 backtick app/web 경로 또는 ‘사유’ 문자열을 검사한다. 사용/미사용을 실제로 분기하지 않으며 경로 실존·결정 내용·사용 이유·현재 스택 적합성도 확인하지 않는다. 코드를 무조건 해당 패턴으로 바꾸라는 규칙으로 Zeus에 이식하지 않는다. policy는 advisory/cmd:null로 프로젝트 인자 부재 때문에 스윕 제외임을 명시한다. 직접 pipeline 배선과 전용 테스트는 선택 검색에서 찾지 못했으며 실행 완료를 주장하지 않는다.

<a id="v10"></a>
## V10 — red_flags_scan: 절 표식과 실효성

skills 디렉터리 부재는 rc2지만 README를 제외한 Markdown이 0개면 ‘전 스킬 준수’/0이다. 본문 어디에든 `## Red Flags` 문자열이 있으면 되고 절 내용·실제 위반 탐지·사용자의 핵심 시나리오는 검사하지 않는다. 원본 테스트는 정상 트리와 절이 빠진 한 파일을 대조한다. 현재 정책은 blocking으로 승격되어 있어 머리말의 advisory 설명을 현재 grade로 쓰지 않는다.

<a id="v11"></a>
## V11 — repair_evidence: 이번 사이클 산출이라는 문장보다 넓은 구현

실제 순서는 pending 디렉터리의 항목이 하나라도 있으면 PASS, PLAN에 `NO-REPAIR:`로 시작하는 줄이 있으면 PASS, 아니면 현재 Git status의 일부 변경이면 PASS다(139–157행). pending 항목이 파일/빈 디렉터리인지, 현재 candidate/cycle/patch인지 검사하지 않는다. `NO-REPAIR:` 뒤의 비어 있지 않은 사유도 요구하지 않는다. 변경 파일 역시 시작 전 기준선·actor·iteration으로 귀속하지 않아 이전부터 있던 무관한 dirty 변경을 배제하지 못한다.

원문은 과거 ‘앵커 이후 커밋’을 보던 오류를 고친 경험을 설명하지만 ‘작업 트리를 보면 남의 것이 사라진다’는 주장은 구현의 실제 범위보다 강하다. 중첩 Markdown은 DOC_NAMES와 정확히 같지 않으면 산출에 포함될 수 있다. Git porcelain 문자열 파싱은 quoting/rename/비ASCII 경로의 정확한 이름 복원을 보증하지 않는다.

원본 테스트는 합성 저장소·빈 pending 디렉터리·명시 무산출을 성공 케이스로 둔다(`test_repair_evidence_contract.py:65–129`). 이는 현재 계약을 설명하지만 현 사이클 귀속의 증거는 아니다. 자명한 트리 건강 PASS를 보완하려는 목적은 흡수하되, Zeus에는 버전 결합된 산출/정당한 무변경 판단/별도 사람 승인을 분리해야 한다. 이 보고는 해당 구현을 바꾸지 않았다.

<a id="v12"></a>
## V12 — settings_wiring: 실제 실행 못 한 배선도 정상으로 투영될 수 있다

상대 dispatch 명령 형식, 8이벤트, ASCII/LF 및 .gitattributes, registry의 이벤트 이름을 검사한다. 머신 Bash pin을 우선하고 실제 launcher 경로를 볼 수 있는지 확인하는 경험은 Windows Git Bash/WSL 스텁 혼동을 다룬다. 그러나 실제 설정의 matcher/type/timeout 실행 semantics와 registry handler import·도달성을 이 정적 대조가 전부 보장하지 않는다.

`dry_run_event:135–137`은 쓸 수 있는 Bash가 없으면 정상과 같은 None을 반환한다. `check_statusline`도 같은 경우 실행을 건너뛴다. evaluate와 health `sec_wiring:411–414`는 오류 목록이 비면 full(dry-run)/ok=True로 투영한다. `test_health_smoke.py:64–90`은 이 조용한 skip을 기대하는 테스트다. 측정 불능을 대상 결함으로 오귀속하지 않으려는 의도는 타당하지만, 미실행 상태가 성공과 같은 반환형이면 소비자는 차이를 잃는다.

더 직접적인 경로도 있다. `dispatch.sh:13–19`는 python pin이 없으면 stderr 경고 후 exit 0이며 handler를 실행하지 않는다. 이 경고는 `_SHELL_BREAKAGE` 어휘가 아니고 빈 stdout도 허용되므로, dry-run이 launcher를 띄웠다는 사실만으로 8개 handler 발화를 증명할 수 없다. 실제 payload의 cwd도 빈 문자열이다. stdout이 있더라도 JSON parse 가능만 검사하여 schema/결정과 행동 결과의 결합은 없다.

`--quick`/evaluate(dry_run=False)는 이벤트 spawn만 끄며 check_statusline 및 Bash 가용성 확인의 subprocess까지 끄지 않는다. 이벤트 검사는 임시 STATE_DIR를 주입하지만 statusline에는 같은 격리 env가 없고, 원장/프로젝트 쓰기를 포함한 전체 효과 격리도 확인하지 않는다. 이 때문에 이번 정적 리뷰에서는 quick조차 실행하지 않았다. 설정 timeout 10–30초와 dry-run 60초도 실제 훅 시간 계약과 같지 않다.

Zeus의 환경 검증 후보는 `shape_valid`, `launcher_available`, `handler_executed`, `effect_observed`, `not_run`을 나누고 Windows/Linux/WSL별 toolchain·cwd·pin·권한·실행 증거를 묶는 것이다. 현재 구현을 등가로 승인한 것이 아니다.

<a id="v13"></a>
## V13 — todo_scan: 선언된 사각과 현재 grade

scripts의 Python 파일에서 TODO/FIXME/XXX 문자열을 찾고 scanner 자신의 resolve 경로는 제외한다. 자기검출이 영구 오탐을 만들었던 경험과 사각을 원문이 명시한다. 다만 다른 문자열 리터럴/설명도 적중하며 scripts 부재/선정 파일 0건은 깨끗/0이다. 이름이 같은 복사본은 실제 self 경로가 아니므로 동일한 제외가 적용되지 않는다. 현재 policy는 blocking이고, 현재 driver는 advisory 스윕만 호출하므로 grade 승격 자체가 모든 실행 경로에서 차단한다는 뜻은 아니다. blocking 실행은 ladder CLI에서 별도 반환 계약을 갖는다.

<a id="v14"></a>
## V14 — tradeoff_lint: 닫힌 지표는 실행 명령의 무제한 발급을 줄이지만 실측은 별도

지정 axis의 tradeoff fence를 파싱하고 대안 2개 이상/사유/chosen/revisit metric/op/value를 검사한다. 문서 안 source_cmd/cmd/extract를 금지하고 등록 catalog를 지목하게 만든 점은 흡수할 경험이다. core는 선택 타당성을 판정 밖이라고 명시하고 별도 human 승인을 둔다.

형식 자체에도 한계가 있다. `str(None)`은 비어 있지 않아 null option/reason/chosen이 문자열 검사를 통과할 수 있고, value는 float 변환만 하여 bool·NaN·Infinity의 적합성을 닫지 않는다. 서로 다른 대안인지나 선택지가 유효한지는 검사하지 않는다. `_ops` 실패는 어휘 밖 FAIL로 접어 ERROR와 구별하지 못한다. catalog의 shape/entry 실행 계약도 lint가 직접 확인하지 않는다.

지원 `ontology/metrics.yaml:61–89`의 실제 세 명령은 내부 git subprocess의 returncode를 확인하지 않고 stdout의 개수/행수를 출력한다. Git 조회가 실패하여 stdout이 비는 경우에도 0이라는 수치가 나올 수 있다. catalog 계약 테스트(`test_tradeoff_lint_contract.py:220–239`)는 각 지표의 `>=0` 및 got 존재를 확인하여 이 분모 실패와 실제 0을 구분하지 못한다. `_metric_threshold`도 source cmd의 nonzero를 직접 거부하지 않는다. 실행하지 않은 정적 지적이며 현재 지표 값이 잘못됐다고 단정하지 않는다. 실제 모니터링이 언제 이 revisit 조건을 소비하는지는 이번 bounded 추적으로 완료하지 못했다.

<a id="v15"></a>
## V15 — usecase_lint: AC/GWT 표식과 실행 가능한 시나리오

UC heading 0건은 거부한다. AC는 UC body 안 문자열로 세고 서로 다른 UC 이름 사이 중복만 거부하여 같은 UC 안 반복과 중복 UC heading을 닫지 않는다. GWT는 Given/When/Then이 어디엔가 있고 ‘실패’ 문자열이 있는지로 판단하므로 각각 연결된 정상/실패 시나리오·구체적 Then oracle이 있는지와 다르다. 다음 UC heading까지를 section으로 잡아 다른 부록 heading의 표식도 포함할 수 있다.

CLI의 `--gwt-min` 단독은 AC 검사를 끄지만 현재 core는 --ac-ids와 --gwt-min을 별도 gate로 모두 실행한다. 이 실제 방어를 반영한다. core의 ‘모든 AC 고유’와 ‘정상+실패 각 최소 1’ 문장은 구현이 검사하는 문자열 범위보다 넓다. 원본 테스트의 정상 fixture도 한 GWT 줄과 실패 마커를 사용한다. 실제 E2E의 행동·관찰·oracle 생성은 이 validator의 역할이 아니다. 사람의 usecase 승인은 core에 별도로 존재하지만, 읽은 gate_runner의 외부 판정은 stage+mode로 소비하여 statement/hash/사람 신원 전체 결합을 이 범위에서 증명하지 못한다. cycle redo 때 이전 외부 판정을 철회하는 기존 방어는 존재한다.

<a id="trace"></a>
## 직접 읽은 소비 경로와 근거 범위

`supporting-evidence.json`의 각 항목은 실제 읽은 inclusive line ranges와 파일 전체 hash를 갖는다. 전문 primary가 아닌 지원 구간은 coverage에 추가하지 않는다. 이번에는 이전 지원 결과를 재사용하지 않고 해당 구간을 다시 읽었으므로 previous-reference reuse 항목은 없다. 검색 결과의 파일명·일치 줄은 discovery이며 전문 검토로 계산하지 않는다.

주요 경로는 pipeline→checks._exit_code→gate_runner, lint→settings/ledger/ontology 검사, autoheart/푸시 gate→lint, health→wiring, validator policy→pr4→ladder/driver, 문서→metric catalog→metric evaluator다. 지원 test는 조건/정상 대조/빈 환경/실제 파서 대신 lambda를 쓰는 범위를 확인했다. 전이 closure와 모든 선언의 실제 실행 여부를 끝까지 확인했다는 뜻은 아니다.

`checks._exit_code:25–59`는 validator의 rc2도 다른 nonzero와 함께 FAIL로 소비한다. 따라서 개별 validator가 ERROR/2를 구분한다고 pipeline blocker의 ERROR 의미까지 보존되는 것은 아니다. 그래도 nonzero를 PASS로 흡수하지 않는 점은 보존한다. shell=True와 selfimprove의 cmd.exe `set "HARNESS_HOME=%CD%" && ...`는 Linux/WSL의 동일 계약으로 가정하지 않는다.

<a id="zeus"></a>
## Zeus SDD·권위·흡수 경계

Zeus의 SDD 8단계, propose_scenarios/gate_report, request_advance, model_routing의 지정 구간을 현재 working tree에서 다시 읽었다. 파일 해시는 지원 기록에 있으나 upstream manifest의 revision으로 오표기하지 않는다. 현재 proposal_only/acceptance false/release_authorized false와 unqualified 모델 정책은 이 리뷰로 변경하지 않았다.

| 사용자 요구 | 이 범위에서 얻는 경험 | 아직 없는 증거 |
|---|---|---|
| 1 스펙 논의 | UC/AC 분모, 의도 발명 방지의 문서 규칙 | 인증된 사람의 scope·oracle 및 스펙 revision |
| 2 디자인 분석 | tradeoff 형식과 고정 지표, 문서-산출 연결 | 실제 인터랙션·시각 검토·선택의 타당성 |
| 3 코드 작성 | 계층/소유/역할/쓰기 경계 검사 | 실행된 위임·모델 자격·현 cycle 산출 귀속 |
| 4 자체 검증 | 원장 poison, 검사 원인 분리, 발견 0 차단 | 전체 환경 분모·실제 행동·reset·실측 oracle |
| 5 알파 배포 | DB 실행 게이트의 구현 경험 | 알파 artifact/환경/rollback receipt |
| 6 QA·증적 | 기계와 human 게이트 구분 | 인증된 사람 승인과 version-bound 인수 증거 |
| 7 라이브 점진 배포 | 보류와 거부의 구분, push/승격 검사 소비 | production progressive rollout·실측 중단 기준 |
| 8 CS·반복 개선 | 과거 실패의 독립 회귀·유예 표시 | 현 사고→티켓→원인→회귀→실측 종료의 닫힌 연결 |

테스트용 합성 데이터와 mock은 원문 검증기 개발 경험으로 기록하되 사용자가 금지한 mocked acceptance로 채택하지 않는다. Astra→Sol→Terra 전이는 model_tier 문자열이나 validator 사다리 grade와 다른 자격 체계다. 동일 평가·guardrail/toolchain·실제 수행 증거·승인 주체가 필요하며 현재 자동 하향 자격이 있다고 주장하지 않는다. 삼성 휴대폰/태블릿·Device Farm SDK/MCP/live/replay는 유예이며 이 범위에서 구현·실기기 검증하지 않았다.

Zeus의 Git 정의/PG runtime 권위를 기준으로 원본 JSONL·state 파일·candidate 문자열·local ledger를 별도 권위로 복제하지 않았다. 개발·테스트·배포가 이어지려면 측정 불능/미실행/실패/성공의 타입, 대상 분모, 버전과 실행 주체를 보존하는 설계가 필요하다는 검토 의견이다. 현재 기술의 최적해나 채택 승인이 아니다.

<a id="unknowns"></a>
## 미완료와 정확한 종료선

전문 정적 검토 15개만 완료했다. 지원 구간 밖 구현, 전체 정상·오류·인가 전이 closure, 실제 Windows/Linux/WSL 환경, DB rollback/외부 효과, 라이선스·파생물 재배포 조건, 독립 Claude 검토, Zeus 구현/인수 승인은 미완료다. 이번에 검사한 원본들의 테스트 실행은 없다. 원본에 남은 과거 실측 숫자를 현행 측정치로 인용하지 않았다.

기존에 차단된 gatewriter ERROR 프로브를 재시도하거나 우회하지 않았다. source/src/tests/runtime/공유 coverage/다른 리뷰 파일/commit/push 변경은 0이다. 이 폴더의 recorder와 JSON·hash·anchor·Ruff 검사만 자체 검증하며, 이는 원본 validator 실행 증거와 분리한다.
