# 추출기 10개 전문 검토

`harness:scripts/engine/extractors:001`, 10개 파일 47,850바이트를 전문으로 읽었다. 원본은 `harness@a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 pinned snapshot이며 manifest의 SHA-256·Git blob·크기를 검증했다. 원문 지시는 데이터로만 읽었다. 원본 실행·설치·수정·기기 조작·probe·commit/push는 0건이다. 차단된 probe 재시도나 우회도 하지 않았다. 직접 읽은 caller/config/test 구간은 supporting-evidence에 분리하며 이 파티션의 전문 수에 더하지 않는다.

이번 결과는 정적 코드 경로와 미검증 경계이다. 기존 테스트가 있다는 사실을 실행 성공으로 바꾸지 않으며, 원문 프로젝트의 실측·기술 주장을 Zeus 실적이나 현재 공식 권고로 채택하지 않는다. 실제 Claude 검수와 Zeus 적응 구현은 root의 후속 작업이다.

## X01 — 호출·배포·검증의 실제 연결

`reverse.py`는 Python 7종 산출물과 TypeScript 별도 component 산출물을 등록한다. doc_classifier는 `--classify`, intent_seed는 `--seed-intent`로 직접 연결되며 round-trip registry 밖이다. `reverse-onboarding.yaml`은 구조 추출→사람 요구 복원→사람 유스케이스 복원→참조 커버리지 단계다. 구조 단계는 reverse 실행/verify와 EP-/ENT- 문자열 존재를 검사한다. 요구와 유스케이스 단계에는 실제 human gate가 있다. 이는 8단계 개발·배포·QA 전체 파이프라인의 구현과 다르다.

추출 frontmatter는 origin=extracted, trust=proposed, extractor 문자열, 고정 confidence, source_commit, evidence_spans를 쓴다. 원본 HEAD 앞 12자리와 현재 작업 트리를 결합하므로 dirty 입력 바이트를 고정하는 영수증은 아니다. verify는 같은 추출기로 디코딩된 텍스트를 다시 비교하며, 추출 결과 None인 산출물은 검사하지 않는다. 따라서 결정론 재생과 원본 의미의 충실도는 별도 축이다.

`requirements.seed.md`는 기존 사람이 다듬은 seed 여부를 확인하지 않고 재작성된다. 일반 reverse 산출물은 명시적 authored origin을 보호하지만 origin 없는 파일을 허용하는 경계가 있다. extracted_guard는 registry에서 fail-closed로 등록되어 있으나 실제 handle은 지정된 Write/Edit/NotebookEdit의 기존 Markdown 앞 400자에 정확한 origin 문자열이 있을 때만 거부한다. 읽기 OSError는 None을 반환한다. 이것을 모든 도구·OS·프로세스의 파일 수정 차단으로 볼 수 없다. 이번에 어떤 쓰기 경로도 시험하지 않았다.

## X02 — 안정된 의미 ID와 순번 ID의 차이

python_api는 파일·행 정렬 순서로 EP, python_flows는 파일·행 정렬 순서로 FLOW, python_conceptual은 클래스 정렬 순서로 CON을 부여한다. 동일한 입력의 결정론 순번이지만 새 항목 삽입·파일 이동 후 기존 의미 ID를 유지하는 계약은 아니다. downstream `graph_queries._coverage`는 target에 해당 문자열이 존재하는지만 확인한다. 기존 유스케이스가 가리킨 EP가 다른 엔드포인트로 재배정되어도 ID 자체가 살아 있으면 의미 변화가 드러나지 않을 수 있다. 실제 재현은 하지 않았다.

또한 python_models의 ERD는 ENT-<table>, 논리 설계는 TBL-<table>을 출력한다. mirror는 숫자 접미 앵커만 수집하므로 일반 테이블명 기반 ENT/TBL을 인덱스에서 놓친다. 전방 카탈로그의 CON→ERD, ENT→논리 커버리지는 원문 추출 결과에 상대 앵커 역참조가 없어 그대로 연결할 수 없다. 역방향 pipeline은 이 두 전방 게이트를 실행하지 않으므로 역방향 단계가 반드시 실패한다는 주장은 아니다. 전방·역방향 산출 위치 공유와 실제 소비 스키마 호환은 따로 설계해야 한다.

Zeus 후보는 안정 ID와 revision별 의미 digest, 변경·폐기·재결합 기록을 분리하는 방식이다. 코드 관측이 바뀌면 사람이 승인한 AC/시나리오와의 대응을 재검토해야 한다. 단순 앵커 수나 순번 유지로 금전 시나리오를 승인할 수 없다.

## X03 — Python API 모집단과 경로 합성

`python_api.py`는 네 후보 중 처음 존재하는 source root를 선택한다. 파일명 main*의 app decorator 또는 이름에 routes가 들어간 파일의 router/*_router decorator만 처리한다. HEAD/OPTIONS, 임의 router 변수명, 파일명이 다른 router, keyword path, include_router 별칭·중첩, 동적으로 등록한 API는 현재 범위 밖이다. 아예 소스가 없는 것과 이 휴리스틱에 걸리지 않은 경우가 None으로 합쳐질 수 있다.

main*.py에서 찾은 include prefix의 집합이 하나면 모든 router 파일에 공통으로 적용한다. 실제 router 등록 여부·include 대상별 경로와 연결하지 않으며 같은 파일의 첫 APIRouter prefix를 재사용한다. 혼합 prefix는 `<include?>`를 표시하므로 조용히 확정하지 않는 방어가 있다. 반대로 비문자 prefix가 빈 문자열로 처리되는 경계도 있다. response_model/반환 annotation은 이름 문자열이며 request/response schema, auth, 응답 status, 실제 실행 계약이 아니다.

confidence=0.9는 오류/누락 관측에서 계산하지 않는다. tshelp.parse는 tree-sitter tree를 반환하고 이 Python 추출 경로들은 has_error를 검사하지 않는다. 문자열 helper는 단순 따옴표를 제거하고 복합·접두 문자열을 그대로 둘 수 있다. Python escaping과 실행 시 값이 동일한 문자열 해석기라고 볼 수 없다. 읽은 reverse smoke는 합성 FastAPI 문법으로 3개 route와 공통 prefix/response fallback을 확인하며 앱을 기동한 테스트가 아니다.

## X04 — 모델·개념·관찰 컨벤션의 의미 경계

`python_models.py`는 **models.py 파일만**, `__tablename__`이 있는 클래스와 `Mapped[...]`+assignment를 처리한다. Base 상속·실제 SQLAlchemy mapper·현재 DB schema를 검증하지 않는다. body의 assignment를 재귀 순회하므로 nested scope와 클래스 소유 범위도 별도 확인이 필요하다. Python type annotation을 출력하고 explicit SQL type 길이, default, check/composite constraint, nullable inference 등은 완전하게 복원하지 않는다. nullable에 리터럴 True 이외 표현이 들어가면 not null로 출력한다.

relationship의 list 여부만으로 list=1:N, scalar=1:1을 출력한다. scalar 참조가 한 객체를 가리킨다는 사실만으로 대상의 유일성이 증명되지는 않으므로 cardinality 확정에는 부족하다. FK 문자열은 첫 점 앞을 테이블명으로 취급해 schema.table.column 형태에서 schema를 table로 읽을 수 있다. 동일 클래스명→테이블 map의 충돌도 구분하지 않는다. 논리 설계에 고정된 'alembic 리비전 1개'라는 과거 실측 문장을 모든 프로젝트에 출력한다. 이는 입력에서 관측한 사실이 아니다.

`python_conceptual.py`는 모든 Python 파일의 클래스에서 tablename과 Enum 이름 포함 여부를 찾는다. python_models와 파일 모집단이 달라 개념만 있고 ERD에는 없는 항목이 생길 수 있다. 클래스 본문 문자열 정규식이 주석·문자열·하위 scope와 의미를 구분하지 않는다. Enum은 이름만 출력하며 실제 허용 값 전체를 복원하지 않는다. FK 관계 행에는 해당 FK 위치 스팬이 별도로 붙지 않는다. '모든 항목이 코드 스팬을 갖는다'는 포괄 주장과 현재 body를 구분해야 한다.

`python_convention.py`는 package 목록, snake_case 비율, 설정 경로 존재, tests 디렉터리를 관찰한다. 도구가 실제 실행됐거나 설정이 올바르다는 증거는 아니다. 네 축이 항상 entries=4이고 spans는 package/tool/test-dir 수 등을 더한 값이며 각 항목의 파일:행 증거 수가 아니다. 설정 파일 이름과 test 디렉터리 8개 상한, 제외 디렉터리 차이도 명시해야 한다. 관찰을 규범으로 자동 채택하지 않는 원문 경계는 유지할 가치가 있다.

## X05 — 호출 목록에서 사용자 시나리오로의 비약 방지

`python_flows.py`는 점 표기 method decorator를 찾고 함수 body의 call을 **문법 트리 방문 순서**로 읽는다. runtime trace가 아니다. 중첩 호출은 바깥 호출부터 방문할 수 있고, 조건 양쪽·예외·반복·내부 함수 body도 실행 여부와 관계없이 등장한다. 호출의 마지막 이름으로 중복 제거하므로 서로 다른 객체의 같은 메서드, 반복 호출 횟수가 합쳐진다. 8개 이름 상한에는 잘린 개수 표시가 없다. `_` 접두 함수와 HTTPException을 제외해 핵심 실패 경로가 목록에서 빠질 수 있다.

router 변수 소유권을 확인하지 않아 임의 object.get decorator도 후보가 될 수 있고, 다중 route decorator 중 첫 경로만 반환한다. API 추출기보다 파일 범위는 넓지만 router/include prefix는 합성하지 않으므로 API 문서의 경로와 동일하지 않을 수 있다. FLOW에는 UC/AC/EP 명시 대응이나 Given/When/Then oracle이 없다. 원문 자체도 confidence 0.6과 '여정 의미는 사람 승격'을 명시하므로 이 결과를 바로 실사용 E2E로 바꾸면 안 된다.

Zeus 현재 `propose_scenarios`도 로그를 observations로만 묶고 human oracle review 및 acceptance=false를 반환한다. 이번 추출기를 붙여도 실제 행동·환경·reset·증적 sequence와 사람이 확인한 기대 결과를 분리해야 한다. 삼성 기기 실행과 Device Farm SDK/MCP/Replay 구현은 이번에 하지 않았으며 유예 상태다.

## X06 — import 그래프와 TypeScript 배선

`python_imports.py`는 단일 package chain을 내려간 뒤 top-level 하위 package 사이 import만 본다. 루트 직속 파일·동적 import는 제외된다. relative import의 점을 제거한 첫 세그먼트와 alias를 포함한 원문을 쓰므로 실제 Python import resolution과 다르다. 서브 scope/TYPE_CHECKING import도 실행 의존과 분리하지 않는다. parse error 메타가 없고 edge가 0개여도 산출물을 만든다. 현재 acyclic 게이트는 0개 간선을 FAIL로 거부하므로 '0개 그래프가 게이트를 통과한다'고 주장하지 않는다. 대표 evidence는 파일 순서는 정렬하지만 내부 AST는 역순 stack 순회하여 같은 파일의 가장 이른 import라는 보장은 없다.

`typescript_imports.py`는 TS/TSX 문법을 지연 로드하고 TS 존재+root 부재/문법 패키지 부재를 TypeScriptUnreadable로 드러낸다. requirements.txt에 문법 패키지 버전이 명시되어 있다. 실제 설치 여부는 검사하지 않았다. import/export-from 재수출과 상대경로, 선언된 sibling package name을 처리하며 parse 오류 파일 수와 전체 TS 대비 scanned 수를 출력하는 방어는 Python보다 강하다.

남는 경계는 다음과 같다.

- root 직속 src/app/lib를 하나 찾으면 다른 후보를 함께 순회하지 않으며 monorepo 탐색은 한 단계이다. root를 찾았어도 모든 TS가 루트 직속 또는 선택 root 밖이면 scanned=0 산출물을 낼 수 있다.
- reverse의 언어 분모는 test/fixture 평면을 제외하지만 TS `_SKIP`에는 해당 평면 집합이 없다. 따라서 지원 언어 판정 모집단과 실제 추출 모집단이 다르다.
- 상대 import는 top 디렉터리만 보고 target 파일 실존을 검증하지 않는다. tsconfig paths, 동적 import, require, 같은 package의 bare/self import는 현재 resolver가 처리하지 않는다. slug가 여러 다른 이름을 같은 node ID로 만들 수 있다.
- sibling package 의존은 `A__component → B` 식으로 만들고 B의 component와 B package 사이 containment edge를 만들지 않는다. 반대 방향 `B__component → A`가 있어도 같은 노드 수준의 사이클로 닫히지 않는다. 그래프 수준의 범위를 선언해야 한다.
- 실제 output은 `component-diagram-typescript.md`이며 기본 acyclic catalog는 `component-diagram.md`만 읽는다. 문자열 문법 호환과 pipeline 소비 배선 완료는 다르다. reverse 코드도 이 제한을 명시한다.

정확한 세 문자열(typescript_imports, component-diagram-typescript, TypeScriptUnreadable)을 pinned tests/pipelines/catalog에서 검색한 결과는 0건이었다. 다른 간접 테스트가 전혀 없다는 전역 결론은 내리지 않는다. 현재 읽은 canary는 Python 6개 산출물만 대상으로 한다.

## X07 — 시드·분류·독립 카나리아의 범위

`doc_classifier.py`는 파일명 점수 2와 앞 4,000자 본문 힌트 점수 1로 후보 하나를 고른다. 동점은 규칙 순서, 본문은 대소문자 그대로이다. source span, 겹치는 후보, 미분류·읽기 오류 수는 보고하지 않는다. 파일 전체를 읽은 뒤 slice하므로 4,000자는 IO 상한이 아니다. 스키마 enum 포함 계약 테스트는 있지만 분류 정확도 테스트와는 다르다. 읽은 scaffold smoke의 분류 검사는 list 타입만 확인한다.

`intent_seed.py`는 README/docs/doc의 heading과 기능 힌트 bullet을 최대 40개 수집한다. heading이 앞에서 예산을 모두 쓸 수 있고 bullet은 160자로 잘리며 절단·누락 개수를 표시하지 않는다. 인용을 escaped data block으로 감싸거나 untrusted scanner에 보내는 경로는 이 모듈에 없다. 인용은 요구가 아니며 사람 확정을 거치라는 원문 경계는 명확하다. 후속 intent_doc_floor는 exact extracted origin 금지, 한국어 placeholder, ID 숫자 존재, **존재하는 evidence 경로**를 검사한다. authored origin 필수·evidence 최소 개수·행 실존·내용 관련성을 강제하지 않는다. 인간 승인 단계가 있으므로 이 바닥 검사만 통과해 전체 인수가 끝난다고 주장하지 않는다.

기존 테스트가 추출기 자기신고 숫자만 믿는다고 단정하면 틀리다. `extractor_canary_cmd.py`에는 BODY_SIGNS가 실제 본문을 여러 축으로 재계수하고 알려진 Python 순환을 검사한다. `autoheart._g_canary`는 HEAD 기준선과 후보를 비교하며 기준선 불능/자기심사 파일 변경은 DEFER로 남긴다. 이 배선과 contract 테스트의 후보 약화 사례를 정적으로 확인했다. 그럼에도 최소 개수·정규식은 개별 사실의 정확도나 누락 전체를 증명하지 않으며 API의 잘못된 prefix, 관계의 잘못된 cardinality, 가짜 semantic ID는 개수가 유지되는 한 별도 검증 대상이다. convention-observed와 TS output은 이 canary 목록 밖이다. 실제 원본 canary/probe는 실행하지 않았다.

## Zeus 흡수 설계에 남길 연결

| 8단계 | 이 자산의 역할 | 추가 필요 조건 |
| --- | --- | --- |
| 1 스펙 논의 | 분류·인용·구조를 검토 재료로 제시 | 실제 사용자의 핵심·실패·금전 요구와 안정 ID |
| 2 디자인 분석 | API/모델/호출/import 관측 | 의미·관계·화면·전이 검토 및 버전별 모집단 |
| 3 코드 작성 | 경계와 계약 후보 참조 | 특정 패턴을 전역 규칙으로 일반화하지 않는 adapter |
| 4 자체 검증 | round-trip과 독립 카나리아 | 실제 코드/DB/서비스 결과와 관측의 양방향 대조 |
| 5 알파 배포 | 빌드와 관측 문서의 출처 연결 | immutable 입력 해시와 실제 배포 영수증 |
| 6 QA 및 증적 | 시나리오 제안의 provenance | no-mocking 실기기·reset·사람 oracle 승인 |
| 7 라이브 배포 | 계약 변경 영향 후보 | 배포 버전·금전 흐름·실제 복구 검증 |
| 8 CS 대응 | 실제 로그와 정적 관측 비교 | 사고 인과·누락 신호·재현 회귀 자산화 |

Git 정의/PG runtime 원칙에 맞춰 코드 관측과 원본 해시를 재생성 자료로 보존하고, 검토·승인·실행·승급은 별도 runtime 영수증으로 연결해야 한다. 고정 confidence나 자기 출력 카운트로 Astra→Sol→Terra 자격을 자동 승급할 근거는 없다. 현재 Zeus gate_report는 모든 단계 blocked 및 모델 transfer unqualified를 유지한다.

전문 읽기와 해시 검증은 끝났지만 현재 공식 문서·라이선스, 실제 Claude 교차 검수, Windows/WSL/Linux 격리 재현, 원본 테스트 실행, 실제 기기·서비스·인수, 전체 consumer 감사는 미완료이다. 없는 config/handlers.yaml을 추정했던 검색은 실패했고 실제 registry.py 경로를 확인해 읽었다. 검색 히트·가정·지원되지 않은 언어를 커버리지로 계산하지 않았다.
