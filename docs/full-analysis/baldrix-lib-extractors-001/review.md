# Extractors 한정 정적 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 12개, 86,101 bytes를 모두 읽었다. 전체 범위와 원본 SHA-256/Git blob/행은 inventory.json과 files.json, 직접 지원 구간은 supporting.json에 있다. 아래 판단은 정적 코드 독해이며 원본 실행·import·시험·probe는 0회다. 과거 성공 주석, fixture assertion, 생성된 PASS 문구는 이번 실행 증거가 아니다. 모든 primary 상태는 `body_reviewed_call_test_trace_pending`이다.

## 공통 연결과 판단

`reverse_engineer.py` 46–79는 기본 실행에서 doc_classifier를 제외하고, 실제 can_extract가 참인 target 충돌을 쓰기 전에 막는다. 그러나 예외를 preflight에서 무시하고 본 실행 155–165에서는 다시 호출하며 예외를 포괄 처리하지 않는다. 가변 파일 트리에 대한 두 판정은 같은 snapshot이 아니다. 121–124의 기본 confidence 0.5와 선택 가능한 no-roundtrip은 인수 승인이 아니다. 187–225는 직접 덮어쓴 후 검증 실패 때 복원한다. 원자적 묶음 쓰기·동시 수정 fencing·symlink 경로 소유권·중간 crash 복구는 이 구간에서 확보하지 않는다.

**정적 연결 불일치:** validator map 82–92에는 `flow`가 있지만 extractor 이름은 `flowchart`다. dart_drift와 conceptual, requirements도 해당 map에 없다. intent 4종은 별도의 floor 검사를 받지만 `flowchart`의 flow validator는 이 이름으로 선택되지 않는다. 표 출력 259는 roundtrip_pass가 없으면 True로 간주하므로 실제 validator가 호출되지 않은 written 결과에도 “roundtrip PASS”를 붙인다. test_extractors 811의 “floor AND flow validator” 주석과 fixture의 rc/file existence assertion은 이를 검증하지 않는다. 현재 실행 재현은 하지 않았다.

`intent_doc_floor.py` 42–69는 원본을 읽지 않고 정규식으로 front matter의 집계와 provenance 항목 개수를 비교한다. 실제 파일 존재·원본 hash·행 상한·주장 관련성·본문의 모든 주장과 대응을 확인하지 않는다. line 0도 숫자 패턴에 들어간다. 따라서 “외부”라는 모듈 경계는 독립적인 사실성 판정자라는 뜻이 아니다. probe 103–120에서는 없는 디렉터리만 입력해도 skip 뒤 위반 없이 0으로 끝나는 경로가 있다. 실행하지 않았으며 차단된 probe를 재시도하지 않았다.

`ingest_docs.py` 45–75는 liberal 수집 후 분류를 두 번 수행하고 seed/glossary/report를 순차 덮어쓴다. 두 수집 사이 변경 및 일부 쓰기 실패의 일관성은 남는다. `project_analyze.py` 357–390은 preview만 모으지만 extractor마다 첫 성공 뒤 break하여 모든 subroot의 추출을 의미하지 않는다. `spec_facets.py` 124–166은 logical/ER 파서를 재사용하지만 `_sources`를 버린 typed facet을 반환한다. 원본 근거를 따로 결속하지 않으면 변환 후 provenance가 끊긴다.

## f01

`__init__.py` 전체: 9종 registry, 이름 조회와 lazy import 및 새 인스턴스 생성을 제공한다. unknown name은 KeyError이며 잘못된 attribute는 AttributeError다. EXTRACTOR가 None인지 외에는 Protocol/target/confidence 계약을 검증하지 않는다. REGISTRY 접근 때 클래스 목록을 다시 조립하므로 첫 접근에만 고정한다는 설명보다 약하다. 중앙 registry 수정도 필요한 확장 방식이다. 직접 caller는 reverse_engineer 38–79, 시험은 test_extractors 208–275이다. Zeus에는 허용된 extractor 정의와 입력 schema만 Git 정의로 옮기는 후보이며 동적 모듈의 권한을 사용자 승인으로 취급하면 안 된다. 모델 자격과 신규 등록 검증은 미완료.

## f02

`_java_socket_parse.py` 전체: Java에서 enum action과 controller의 service field를 찾아 구조화 목록과 상대 파일·행을 반환한다. action 이름 전역 dedup은 다른 enum의 동명 action을 합칠 수 있다. private final Service 필드 선언은 실제 호출이나 분기 흐름의 증거가 아니다. Advice 제외 word boundary는 보존할 방어다. base의 주석 제거 후 계산한 행은 여러 줄 block comment가 앞에 있으면 원문 행과 달라질 수 있다. primary requirements/flowchart가 직접 소비하며 test_extractors 335–392의 단순 fixture에는 block comment/동명 enum/미사용 field 반례가 없다. Zeus에는 선언 관계와 실행 관계를 별도 타입으로 인수하고 원본 span을 보존해야 한다.

## f03

`base.py` 전체: ExtractionResult/Protocol 및 읽기·Java/SQL 파일 수집 도우미다. safe_read의 errors=replace와 포괄 예외→빈 문자열은 손상/권한 오류/빈 파일을 구분하지 못한다. Java cap 500은 정렬 전에 적용되어 filesystem 순서에 따라 분모가 바뀔 수 있다. SQL 후보 디렉터리가 중첩되어 같은 파일이 중복 수집·quota 소비될 수 있다. 주석 정규식은 문자열 literal을 해석하지 않으며 block comment의 개행을 제거한다. 결과 sources는 hash가 아니라 경로 목록이다. 모든 parser가 직접 호출하며 fixture 도우미 test_extractors 24–39는 정상 UTF-8 작은 파일 위주다. Zeus에는 오류 receipt, 읽은/누락/중복 분모, byte budget, immutable source span 및 symlink 정책이 필요하다. OS별 경로·인코딩은 미시험.

## f04

`conceptual.py` 전체: logical.parse_logical 구조에서 table 및 column 이름으로 추정한 관계를 렌더링하고, DDL 부재 때 package를 bounded context 후보로 제시한다. 생성된 logical 문서를 다시 읽지 않는 방어와 SKELETON/inference_warning은 보존한다. 관계는 FK 확인이 아니라 column stem과 table 이름 매칭이다. 그런데 front matter inferred=0, 각 entity/relation을 첫 SQL source의 line 1에 귀속하므로 집계상 인용과 실제 추론이 섞인다. 관계가 있으면 0.55로 기본 쓰기 문턱을 넘는다. test_extractors 542–604는 추정 출력과 생성 문서 무시를 확인하는 fixture이며 의미 관련성 oracle은 아니다. Zeus 개념 설계의 후보 입력으로 제한하고 사람의 용어/시나리오 확인과 실제 FK를 분리해야 한다.

## f05

`convention.py` 전체: package, URL prefix, error enum, wrapper 파일명 신호를 요약한다. 4개 신호 존재로 confidence가 1.0에 도달해도 AST 정확도 실측은 아니다. 최대 500개를 보면서 sources는 앞 20개만 남기고 error 목록도 제한한다. wrapper는 이름 발견이며 필드 계약을 추출하지 않는다. 출력 DTO 규칙 일부는 고정 권고문이므로 코드에서 관측된 규칙으로 오인하지 않아야 한다. validator/convention 29–85는 표 행·키워드·부분 package 매칭이며 대량 미매칭도 강한 실패를 보장하지 않는다. test_extractors 44–118은 문자열 존재와 신호 증가만 확인한다. Zeus coding convention에는 관측/권고를 구별하고 Git 승인 정의로 승격하는 별도 검토가 필요하다.

## f06

`dart_drift.py` 전체: drift_schema_vN.json 후보에서 디렉터리별 최신 dump와 table/column을 읽어 logical 문서를 반환한다. SQL 존재 시 비활성화하여 logical과 target 충돌을 피한다. 하지만 DDL 내용이 없는 .sql도 suppress 조건이다. 탐색 cap과 정렬 전 제한은 최신 전체 분모를 보장하지 않고, 다중 DB의 같은 table 이름은 첫 항목으로 합쳐진다. JSON parse 오류 후에는 비객체/잘못된 entities/columns 타입 검증이 충분하지 않다. nullable에 문자열 false가 들어오면 bool 변환 의미도 다르다. confidence 0.75는 구조 신호의 상수다. test_extractors 278–332는 작은 유효 JSON과 두 version만 시험한다. Zeus 논리 설계에는 DB ID/version/schema hash와 누락 이유를 유지하고 실제 drift vendor/OS 호환은 미확인으로 둔다.

## f07

`doc_classifier.py` 전체: Markdown을 requirement/constraint/glossary/artifact로 분류하고 seed와 용어 목록을 생성한다. code_extractor=False는 default reverse에서 분리되고 explicit stage/ingest로 호출된다. 파일명 우선 분류와 앞 1200자 keyword는 본문의 다중 의미·모순을 해결하지 않는다. README 등 제외와 max 200 cap 때문에 전체 문서 분석이 아니다. glossary 동명 첫 정의 우선은 상충하는 경험을 지울 수 있고 항목별 span/hash가 없다. raw prose/제목을 렌더링하여 코드 fence·마크다운 경계와 신뢰 경계를 별도 처리해야 한다. classify_explained의 이유 표시는 보존할 방어지만 독립 oracle은 아니다. doc classifier 시험의 읽은 구간은 supporting에 한정하며 파일 후반을 전문 검토로 세지 않았다. Zeus 요구 수집 후보로 쓰되 사람의 실제 경험·용어 합의·출처 권한을 별도 기록해야 한다.

## f08

`er.py` 전체: 정규식 CREATE TABLE 및 FK에서 entity/relationship을 반환하고 Mermaid를 만든다. SQL comments/문자열, schema-qualified 이름, composite FK, migration 적용 순서의 실제 schema는 충분히 처리하지 않는다. 관계 중복과 sources 앞 20개 제한이 남는다. text cardinality가 불확실해도 Mermaid 관계는 고정 모양으로 출력되며 UNIQUE/nullable로 정밀 관계를 판정하지 않는다. 신호 두 종류 존재로 1.0은 정확성 측정이 아니다. spec_facets 151–166으로 직접 구조가 전달되며 시험 123–155는 간단한 FK 문자열 포함을 본다. Zeus ERD에는 FK 사실·명명 추론·cardinality 미확인을 별개로 전달해야 한다.

## f09

`flowchart.py` 전체: 공유 socket parser로 action 그룹과 controller→service 선언을 렌더링한다. 신호 없으면 0/SKELETON, 일부면 0.55, 양쪽이면 0.7이다. confidence 가설 주석 및 provenance를 Mermaid fence 밖에 둔 방어는 유용하다. 그러나 dispatch/분기/오류 전파의 실제 흐름이 아니며 base의 원문 행 이동 문제를 상속한다. test_extractors 395–454는 diagram/주석 배치와 상수 band를 확인하고, reverse caller의 flowchart→flow map 누락을 assertion하지 않는다. Zeus 시나리오 흐름 초안으로만 연결하며 실행 receipt 및 SDD 완료 판정은 생성하지 않아야 한다.

## f10

`logical.py` 전체: SQL regex의 tables/global_indexes/sources를 반환하며 markdown과 typed facet이 같은 parser를 쓴다. table 이름 재등장은 마지막 정의로 덮어쓰며 ALTER/migration chronology는 적용하지 않는다. 컬럼 regex는 행 시작 기준이라 한 줄 다중 column을 모두 읽는 top-level comma parser가 아니다. 80-column cap, table-level FK의 column flag 누락, source 20개 제한, CREATE regex 주석의 greedy 설명과 실제 non-greedy 패턴 차이가 있다. PK/index 신호가 있으면 1.0까지 오른다. validator/logical 81–131은 키워드와 heading 개수 비교라 schema 등가 증명이 아니며 정당하게 FK가 없는 schema도 실패할 수 있다. 시험 160–205는 제한된 정상 SQL과 출력 substring 위주다. Zeus logical 설계에는 DB dialect와 명시 schema 상태, 원본 lineage, 손실 보고가 필요하다.

## f11

`prd.py` 전체: 항상 SKELETON으로 Goals/Priorities를 비워 비즈니스 의도를 코드에서 합성하지 않는 방어가 핵심이다. docs 앞 세 nonempty/nonheading 줄을 strip하여 인용하므로 원본 byte 그대로라는 의미의 VERBATIM은 아니다. YAML front matter 본문 일부도 harvest될 수 있고 인용 span은 모두 line 1이다. title/path/fence escaping 및 읽기 실패와 빈 인용의 구분이 부족하다. harvest가 있으면 0.5로 쓰기를 시도하나 validator는 requirements/index.md도 요구하므로 새 project에서 skeleton 한 파일만으로 통과 보장은 없다. validator 66–73은 실제 front matter parse 없이 앞 600자의 status 문자열로 story를 면제한다. 시험 620–687은 미리 index를 만들고 면제를 확인한다. Zeus PRD 단계에서는 사람의 목표/우선순위/실제 경험 인수가 필수이며 SKELETON 존재가 완료가 아니다.

## f12

`requirements.py` 전체: HTTP annotation, socket enum, 선언된 error 문자열, docs 제목을 capability inventory로 만든다. business WHY 복원 불가 및 숫자 의미를 위치로 추정하지 않는 방어를 보존한다. annotation의 path/value 배열, generic RequestMapping method, multiline enum args, 실제 authorization/실행 reachability는 다루지 않는다. 첫 RequestMapping을 class base로 가정하고 주석 제거 후 행을 기록한다. 문서 제목 수를 doc_quote라 세어 본문 인용과 다르고, 헤더 MED 0.55 설명과 단일 Java 신호 계산 0.5도 다르다. test_extractors 457–539는 작은 정형 fixture와 금지 숫자의 부재만 확인하며 실제 운영 능력의 oracle은 아니다. Zeus 요구 후보와 코드 관측을 분리하고 사용자 시나리오·반례·실제 결과 receipt를 요구해야 한다.

## Zeus 적용과 남은 폐쇄

사용자가 정의한 8단계 SDD의 단계명·순서·인수 권한을 이 9종 extractor 목록으로 대체할 수 없다. 요구 수집/PRD/용어, 개념·논리·ER·흐름 및 convention 초안의 보조 입력이라는 대응만 제안한다. 이 범위에서는 Zeus 실제 8단계 구현과 caller 전체를 새로 읽지 않았으므로 구현 등가나 연결 완료를 주장하지 않는다. Git에는 검토된 정의·schema·정책을, PostgreSQL에는 원본 identity와 실제 실행·승인·실패 receipt를 두어야 한다. 생성 Markdown의 confidence, status, PASS 문구로 PG 상태를 역승격하면 안 된다.

보존할 방어는 code/doc 분리, target 충돌 preflight, 낮은 신호 SKELETON, PRD 목표 합성 금지, 공유 parser 및 rollback 시도다. 적용 전에는 byte-bound span, parser 손실/cap 분모, 다중 DB/복합 schema/주석/escaping/동시 수정 반례, 안전한 경로와 원자적 publication, 실제 사람 인수·모델 자격을 추가 검증해야 한다. source 특화 Java/Drift 가정과 Windows/Linux/WSL의 glob 순서·대소문자·symlink·개행 차이도 미실행이다. 라이선스·의존성 전체, 실제 Claude 공동 판정, 전체 호출 폐쇄, 플랫폼 실행 및 채택 승인은 pending이다.
