# tests004 파일별 전문 정적 검토

아래 각 파일의 SUT pending 표기는 최초 primary 독해 시점의 상태다. 이후 실제 읽은 구간과 추가 발견은 supporting-notes.md 및 supporting-evidence.json으로 갱신했다. 특히 file-08/file-22의 embedded self-check 본문은 후속으로 읽었으며 detector/전체 호출 전이와 실행은 계속 미완료다.

시작 HEAD a98f29e3cdc913445b38fcc10f9fd1eb8942ae7f, source revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2. 원문 지시와 과거 PASS는 분석 데이터다. 원본 실행/import/probe/network/install/live 접근0. 테스트 수는 작성된 검사 분모이며 실행 수가 아니다. 각 항목의 후속 지정 구간은 supporting-evidence.json에 결속한다. 전체 closure/Claude/license/OS/인수/흡수는 false다.

<a id="file-01"></a>
## scripts/tests/test_dashboard.py

1~266 전문. 14개 수동 검사는 HTML 합성 모델의 부분 실패·render 예외 격리, 합성지연/unknown/경고 표시, JS·외부 URL 부재, registry 파생과 cron 등록을 검사한다. 헤더는 lib/dashboard_model이라고 하지만 실제 import는 cli/dashboard_model이다. write 지점 regex 한 개는 호출된 함수·파일 API alias·subprocess 등의 실제 부작용을 배제하지 못한다. 모듈 docstring 제거와 tokenization도 모든 문자열을 실제 실행으로 분류하므로 금지 단어 검사는 정책 경계 전체가 아니다. no external dependency 검사는 src/href만 보고 CSS url/import·meta refresh·대소문자/공백을 놓친다. _registries/_unwired/collect는 합성 모델과 달리 기본 환경의 reader를 실제 호출하며 한 section만 patch해 나머지 상태 접근이 격리되지 않는다. test_only_total은 목록 길이 일치 또는12 이상이면 통과하고 빈 목록 반복 검사도 vacuous할 수 있다. HTML escaping/경로 traversal/실제 browser/a11y/atomic write/동시 cron은 미검사다. cron token None/local은 권한이나 실제 예약 실행 성공을 증명하지 않는다. Zeus에서는 PG 파생뷰의 unknown/합성 표시를 보존하되 정본·실제 관측·사람 인수와 구분해야 한다. SUT 지정구간 추적 pending, 실행0.

<a id="file-02"></a>
## scripts/tests/test_ddl.py

1~95 전문. 3개 수동 검사가 process cwd를 임시 폴더로 바꾸고 validator main의 stdout 문자열을 검사한다. cwd는 finally 복원하지만 main 반환값/구조화 검사수는 버린다. 빈 프로젝트도 [PASS]면 성공하여 미검사와 통과를 합친다. happy fixture는 MySQL ENGINE/CHARSET/AUTO_INCREMENT이며 실제 DB 파싱·migration은 없다. negative fixture는 PK와 ENGINE 둘 다 빠져 단일 결함 검출을 분리하지 않는다. SQL 주석·문자열·여러 테이블·dialect·인코딩·read 오류·대소문자 경계는 미검사다. Zeus PG SSOT에 MySQL 문자열 규칙을 이식할 수 없고 PG DDL 및 rollback/권한/transaction을 실제 인수 오라클로 별도 정의해야 한다. 실행0, 실제 DB/OS/전이 closure 미검증.

<a id="file-03"></a>
## scripts/tests/test_debate_aggregate.py

1~810 전문(1~240,241~520,521~810). 37개 수동 검사가 임시 events JSONL로 세션 요약·필터·JSON/table/planner-context, early-cap 별도 이벤트, blocker 축/중요도/다양성/window, research provenance, 옛 timestamp/event 키를 검사한다. fixture hash는 임의 짧은 문자열이고 승인·citation도 직접 작성하여 actual reviewer/원문/정본 hash 검증이 아니다. malformed JSON 행 skip 후 approved summary를 기대하므로 손상 분모가 사라질 수 있다. since는 한 ISO fixture뿐이며 시간대·정렬 역전·NaN·큰 epoch·충돌 timestamp는 미검사다. 과거 rejected를 veto로 삼지 않는 표시는 보존 가능하지만 context tag escaping/증거 injection·cross-project 범위는 미검사다. research URL/load_bearing 문자열만으로 citation_grounded를 기대하며 링크 내용·인과적 발견·IKD를 검증하지 않는다. 다양성·severity 검사는 출력 substring 중심이고 실제 reviewer 독립성·정답 labels가 없다. 721~746 live-debates 검사는 기본 state_dir을 읽으며 부재면 plain return, 디렉터리/검사 행0도 PASS가 될 수 있다. run_units 격리 시 이 'live' 회귀가 공집합을 볼 수 있다. 모든 manual 예외는 rc1에 반영하지만 warning/skip 수는 별도 기록하지 않는다. Zeus PG에서는 source/reviewer/attempt/proposal hash와 결함·미검사 분모를 결속하고 집계지표를 8단계 SDD 승인으로 쓰지 않아야 한다. 실행0, 직접 aggregate 구현/호출 추적 pending.
<a id="file-04"></a>
## scripts/tests/test_debate_convergence.py

1~305 전문. pure convergence와 EventStore/CLI run을 temp DEBATES_DIR로 연결한다. 같은 세대 verdict/sha 충돌을 fail-close하고 세 번째 동일 이벤트로 충돌을 지우지 않는 검사, 이전 세대 충돌 hash 재사용 금지, severity invalidation, missing verdict/snapshot, max_gen 경계3점은 유용한 반례다. 다만 첫 세대 approved는 snapshot이 없어도 converged를 기대하며 실제 사람 승인·공동검토·구현 증거와 무관하다. snapshot key 순서만 normalize 검증하고 list 순서/중복ID/빈 내용·bool gen·타입·actor·서명은 미검사다. idempotency는 순차 두 번이고 stale writer/동시 append·예전 convergence 이후 변경된 verdict는 미검사다. exit3=수렴, exit4=오류라는 SUT 계약을 기대하므로 rc0=성공으로 단순 해석할 수 없다. argparse 실패는 else assert가 있어 실질적이다. globals test_ 수집은 callable 검사가 없지만 수동목록 누락은 피한다. Zeus에서는 토론수렴과 SDD 요구별 인수·PG 정책 revision/attempt 승인 전이를 분리해야 한다. 실행0, SUT/전체closure pending.

<a id="file-05"></a>
## scripts/tests/test_debate_landing_contract.py

1~184 전문. importlib로 CLI 소스를 실행 로드하는 테스트이며 _main 내부 check가 전역 FAILS에 기록해 반환1로 실패시킨다. test_ 함수가 없으므로 pytest 기본 수집은 이 계약을 실행하지 않는다. main=_main 별칭은 수동 runner 배선이며 과거 누락 설명은 과거 실행 영수증으로 삼지 않는다. event/type/없음, convergence 상태, landing 문자열, unknown 분모를 검사하지만 한 readable proposal만 있으면 나머지 미판독 행이 있어도 unreadable=False를 기대한다. AST 금지 import/call명 검사는 alias/getattr/dynamic import/다른 write API·전이 부작용을 배제하지 못한다. landing은 존재하는 문자열만 세고 파일 실재·요구 의미·revision·테스트·인수는 일부러 검사하지 않는다. 145의 source HOME/state/debates 명시 경로는 CLAUDE_HOME 격리를 우회하며 실제 트리에 의존한다. sessions>0 대조군은 vacuous 방어지만 pinned source-only에서 해당 상태가 없으면 실패하는 미충족 전제다. 원본은 실행하지 않았다. Zeus는 landing관측·수렴·채택을 별도 PG 상태로 보존하고 무증거 인수로 승격하지 않아야 한다.

<a id="file-06"></a>
## scripts/tests/test_debate_output_audit.py

1~257 전문. 21개 수동 검사는 합성 텍스트의 영문/한국어 prior context·state 경로·sid·역할교체 문구, dedup/빈값/비문자, advisory 및 temp JSONL append를 검사한다. full event pipeline이라도 직접 primitives를 호출하며 실제 orchestrator/Agent 격리 경로가 아니다. clean inverse는 scanner와 advisory만 검사하고 파일 비생성/기존 로그 불변을 검사하지 않는다. sid/문구 탐지와 actual 정보 유출은 동치가 아니며 인용문·encoded/변형 경로·대소문자/다국어 우회·scope 같은 의미 요소는 미검사다. non-string을 empty로 처리하는 기대값은 malformed input과 clean을 합친다. 태그/actor/leak escaping 및 real timestamps/provenance는 미검사다. Zeus에서는 advisory 신호와 실제 executor sandbox·정보흐름/모델 독립성을 분리해야 한다. 실행0, 지정 SUT/명령 연결 및 전체 인수 pending.

<a id="file-07"></a>
## scripts/tests/test_debate_output_audit_contract.py

1~180 전문. _main/check 전역 FAILS형 계약이며 main alias로 수동 runner에 연결된다. pytest test_ 수집은 없다. 정본 ledger 인용을 허용하고 bare sid/전사 어구는 탐지하며 혼합 입력에서 실제 누출 토큰을 남기는 양방향 대조군, Windows 슬래시·역슬래시/상대경로 접두와 myledger 대조군은 실제 폭을 검사한다. 공유 pre-spawn regex가 ledger/events를 계속 잡고 bare sid를 계속 놓치도록 기대해 관측층과 차단층의 의미 차이를 의도적으로 보존한다. _BARE_SID/_LEDGER_CITATION 이름 존재 검사는 동작이나 구현위치 불변 전체를 증명하지 않는다. 파일 실재·경로 canonicalization/정본 권한·encoded텍스트·정당한 sessionID 언급은 미검사다. 140~142 대조군의 failure detail이 실제 테스트 문장과 다른 짧은 문자열을 scan해 진단이 오해를 줄 수 있다. Zeus PG에 unknown/false-positive와 actual information-flow 증거를 분리하고 문자열 allowlist를 승인 근거로 삼지 않아야 한다. 실행0/OS 실제관찰0.

<a id="file-08"></a>
## scripts/tests/test_debate_stagnation.py

1~27 전문. 독자적 test 함수 없이 lib.debate_stagnation._self_check를 호출하는 얇은 manual wrapper다. 46 assertions라는 docstring은 실행 분모 증거가 아니며 실제 self-check 본문 지정범위를 읽기 전에는 오라클 검토가 미완료다. int 반환은 그대로 전달하지만 None/문자열 등 잘못된 반환도0으로 바꾸므로 실패 신호를 삼킬 수 있고 bool도 int로 취급한다. pytest 기본 수집에서는 main을 실행하지 않는다. Zeus는 embedded 검사별 분모·반환 계약·실제 receipt를 명시하고 stagnation 신호를 목표완료/8단계 인수로 승격하지 않아야 한다. 원본 실행0, self-check/전이 추적 pending.

<a id="file-10"></a>
## scripts/tests/test_debate_trigger.py

1~248 전문, 수동 11개 검사. 임시 skill graph와 STATE_DIR/cache 복구, mtime 14일/30일, 관련 skill 상한 3, 짧은 keyword 제외, advisory 문자열과 시스템 재호출 prefix를 검사한다. notification 차단 검사는 실제 main 대신 테스트 안에서 조건식을 다시 조립한다. 따라서 hook 연결·실제 사용자 의도·skill 능력은 입증하지 않는다. mtime은 세션 정본이나 실행 영수증이 아니며 중복·손상·미래시각·경계시각 검사가 없다. Zeus는 추천을 승인과 분리하고 PG 프로젝트/세션 시각과 신뢰된 발신자 정보를 써야 한다. 실행0, 직접 SUT 및 hook 전이는 미완료.

<a id="file-11"></a>
## scripts/tests/test_debate_trigger_advisory.py

1~227 전문, 14개 수동 검사. 양쪽 advisory 요청 시 마지막 slot 교대, 단독/없음, ack token, 상태 기본값/왕복/손상, 임시 ProposalRecord와 최대 2개 렌더링을 검사한다. 제목의 TTL decay는 실제 main/감소 루프를 호출하지 않아 검증하지 않는다. P.STATE_DIR 변경은 복구되지 않으며 손상 JSON을 turn0으로 취급한다. ack가 인용문인지 실제 명령인지, 동시 갱신·프로젝트 분리·오래된 proposal·권한은 미검사다. Zeus의 ack는 사람 승인 영수증이 아니며 PG 세대/CAS/만료를 가진 추천 상태로 변형해야 한다. 실행0.

<a id="file-12"></a>
## scripts/tests/test_decision_memory.py

1~236 전문, 수동 15개. 임시 결정 기록의 role/source_ts/target 중복, 재등장 횟수, 정렬·렌더링 상한, 빈 입력, CLI 상태 rc 및 role prompt의 recall 실패 처리를 검사한다. 사라진 target은 테스트가 supplied active set에서 빼며 이를 landed로 간주한다. 실제 해결·commit·요구사항 충족은 검사하지 않는다. main은 환경변수를 복구하나 직접 test_ 호출은 각 임시 CLAUDE_STATE_DIR을 남길 수 있다. CLI JSON 본문은 확인하지 않는다. done_signal이 실제로 만족됐는지, 동시 기록, 변경된 같은 ID, 손상과 범위 누락은 미검사다. Zeus에서는 반복 발견을 관측으로 보존하고 실제 해결 증거 없이 완료로 전이하지 않아야 한다. 실행0.

<a id="file-13"></a>
## scripts/tests/test_deferral.py

1~263 전문, 수동 12개. synthetic surgery 로그의 횟수 29/30, 미지원 counter/예외, prose와 marker, operator/trending 노출을 검사한다. 실패한 surgery도 횟수에 포함되며 횟수는 성공이나 승인과 같지 않다. applied 문구가 deferral보다 우선하는 경계를 기대한다. 환경 복구는 원래 값을 복원하지 않고 pop하며 module reload 영향도 있다. 217~227 live 문서 검사는 claude_home 경로를 사용하고 파일이 없으면 그냥 반환하여 수동 PASS가 된다. 원문 auto-merge 설명은 권한이 아니다. Zeus PG에는 관측 횟수·성공·보류 정책·사람 승인을 별도로 기록하고 결함의 잔존 노출을 유지해야 한다. 실행0, 실제 live 접근0.

<a id="file-14"></a>
## scripts/tests/test_design_slop_a11y.py

1~102 전문, 7개 검사. CSS font/gradient/outline, JSX alt·링크 문구·tabIndex·inline 색상, HTML lang과 임시 파일 탐색을 검사한다. 이름의 exit0은 실제 validator main 호출이나 rc 확인이 없다. focus-visible 문자열 존재와 outline 억제가 같은 실제 요소에 작동하는지, DOM·키보드·스크린리더·대비·오류 파일 분모를 검증하지 않는다. 디자인 취향 규칙과 접근성 요구사항을 같은 인수 오라클로 쓰면 안 된다. Zeus SDD에는 요구사항별 실제 동작 및 사람 확인을 연결해야 한다. 실행0.

<a id="file-15"></a>
## scripts/tests/test_dispatch_retry.py

1~116 전문, 6개 검사. 첫 성공은 sleep 없음, transient 두 번 뒤 성공, permanent 즉시 재발생, 마지막 오류/정확히 3회, capped 지연열, 60회 jitter 범위를 확인한다. sleep과 jitter를 주입하므로 실제 시간·네트워크·취소·프로세스 종료는 검증하지 않는다. 무작위 범위 표본은 분포/독립성 증명이 아니다. 잘못된 attempts/음수 delay/classifier 예외/jitter 예외/부분 성공 후 재시도 중복 효과는 미검사다. Zeus에서 retry는 PG attempt와 멱등 효과 키, lease/fencing 및 예산을 필요로 한다. 실행0.

<a id="file-16"></a>
## scripts/tests/test_doc_classifier.py

1~221 전문, 16개 검사. filename/content/default 분류, 보수적 discovery와 README 제외, glossary/seed 렌더링, registry, liberal CLI 실제 연결 및 dry-run 무쓰기, 반복 출력 동일성을 검사한다. CLI 임시 출력 파일까지 읽어 last-mile 단절을 잡는 방어가 있다. 빈 bucket은 none 텍스트로 렌더링되며 요구사항 승인 의미가 아니다. confidence>0은 정확도 평가가 아니고 정답 코퍼스·충돌 우선순위·잘린 입력·symlink·기존 출력 덮어쓰기·권한/인코딩 오류는 미검사다. Zeus 8단계 SDD에서 추출 seed는 원문 provenance가 있는 제안이며 요구사항 ID/사람 확인/인수 기준으로 별도 확정해야 한다. 실행0.

<a id="file-17"></a>
## scripts/tests/test_doc_classifier_explained.py

1~100 전문, 4개 검사. explained와 기존 classify bucket 동등성 3사례, filename/content/default 이유, 정렬·필드 집합 및 CLI report JSON 파일을 검사한다. 같은 구현 사이의 일치는 정답 정확도를 입증하지 않는다. complete라는 이름과 달리 생성한 두 파일의 정확한 집합/개수를 assert하지 않으며 by_path는 사용하지 않는다. CLI는 nonempty list와 허용 bucket만 확인해 이유/원문 hash와 seed 일치가 미검증이다. Zeus PG 추출 영수증에는 전체 입력 분모·누락 이유·원문 hash·분류 근거 및 사람 확정을 결속해야 한다. 실행0.

<a id="file-18"></a>
## scripts/tests/test_doc_code_drift.py

1~234 전문, 수동 18개. stub AST symbol/re-export/__all__, fenced/prose claims와 false positive, deprecated/nonartifact skip, path/command 존재, graduated main rc를 검사한다. scan과 graduation을 mock한 rc 검사는 실제 운영 설정 확인이 아니다. live scan에는 notes>=100/artifacts>=10/command_docs>=100이라는 비공허 분모 방어가 있으나 환경 의존이며 source-only에서 성립을 주장할 수 없다. reader stub도 실제 path 존재 전제가 있고 source forbidden-token 검사는 전이/alias 안전 증명이 아니다. 심볼 존재는 signature·동작·문서의 인수 의미 동등성이 아니다. Zeus는 scan 성공/skip/unknown 분모를 보존하고 graduation을 승인된 정책으로 관리해야 한다. 실행0, live 접근0.

<a id="file-19"></a>
## scripts/tests/test_endpoint_graph.py

1~108 전문, 6개 함수. committed fleet YAML 경로를 rewrite하고 build_fleet_atlas를 호출하여 repo/seam/value/unknown 분류와 ORDER_CREATED의 3 seam JOIN을 확인한다. 이는 작성된 example 정적 추출 연결이며 서비스나 메시지 전달의 실제 통합 인수가 아니다. _ok는 assert 대신 전역 _FAILS에 누적하므로 pytest가 test_만 실행하면 false 조건을 즉시 실패로 보고하지 않는다. main만 최종 실패를 반영하고 재호출 초기화도 없다. 실제 추출기·YAML·별칭·다중 hop·drift 누락은 별도 추적 대상이다. Zeus SDD 관계 그래프는 영향 후보로 사용하고 PG 실제 실행/인수 증거와 구분해야 한다. 실행0.

<a id="file-20"></a>
## scripts/tests/test_endpoint_graph_subsumes_ontology.py

1~135 전문, 5개 검사. 같은 example에서 atlas와 ontology graph를 구성해 shared 값/JOINS 동등성을 대조하고 PAYMENT_DECLINED의 matched1+drift 및 STOCK_RELEASED orphan이 endpoint에서 보이지 않는 잔여를 명시한다. 비어 있지 않은 JOIN 방어가 있으나 query_value 사례 단독 루프는 빈 graph이면 공허하다. shared equality는 공통 scan에 의존하는 정의적 일치이고 독립 관측이 아니다. _ok 누적 방식은 pytest 단독 호출에서 실패가 전달되지 않는 같은 문제를 갖는다. 일부 JOIN 동등성으로 ontology 전체 기능 대체나 채택 승인을 주장하면 안 된다. Zeus는 drift/orphan과 unknown 분모를 유지하고 실제 스펙/코드 연결의 한계를 노출해야 한다. 실행0.

<a id="file-21"></a>
## scripts/tests/test_engines.py

1~97 전문, 수동 7개. registry tuple·debate/ralph 존재·필드 nonempty·알려진 경로 substring·unknown None·frozen assignment를 검사한다. broad Exception으로 불변성 검사를 통과시켜 정확한 예외를 확인하지 않는다. 경로가 실제로 안전하고 존재하는지, 중복 등록·state 격리·실제 엔진 기동/완료 수집·모델 자격은 미검사다. Zeus에서는 registry 메타데이터를 능력 증명으로 쓰지 않고 PG 실행 영수증과 플랫폼별 자격을 따로 결속해야 한다. 실행0.

<a id="file-22"></a>
## scripts/tests/test_ensemble_evaluator.py

1~27 전문. main이 embedded _self_check를 호출하는 wrapper이며 pytest test_가 없다. int 아닌 반환은 0으로 바꿔 비정상 계약을 PASS로 숨길 수 있고 bool은 int로 처리한다. quorum 검사 분모/오라클은 실제 self-check 본문을 읽어야 정해지며 wrapper 설명만으로 다중 모델 관측을 주장하지 않는다. Zeus 실제 독립 모델 자격·실행·동일 artifact hash·비동의 처리·사람 인수는 별도 필수다. 실행0, embedded 직접 추적 미완료.

<a id="file-23"></a>
## scripts/tests/test_er.py

1~91 전문, 수동 3개. 임시 cwd/.claude/design/er conceptual 문서의 empty PASS, 관계 표기 happy PASS, 아무 엔티티/관계도 없는 FAIL을 stdout substring으로 검사한다. main 반환값을 버리므로 프로세스 실패 계약은 미검사다. negative가 두 요소를 동시에 빼 독립 방어를 입증하지 않으며 텍스트 표기는 실제 ER 의미·카디널리티·참조 무결성·PG schema와 같지 않다. Zeus SDD에서 빈 문서는 skip/미검사 분모로 유지하고 확정 데이터 모델/마이그레이션/인수 증거를 별도 요구해야 한다. cwd는 finally 복구된다. 실행0.

<a id="file-24"></a>
## scripts/tests/test_evaluator.py

1~306 전문, 명시 TESTS 27개. 빈 기본 모델 위임, provider family prefix와 override, 세 조건 paradox guard, citation 경계와 잘못된 문자열, completeness 및 approved clamp, frozen/schema 필드를 검사한다. 빈 모델이나 gpt 문자열은 실제 모델/독립 provider 자격 증명이 아니다. citations는 호출자가 제공한 개수이며 원문·독립성·내용 관련성을 확인하지 않는다. AxisScores에 True를 넣고 bool인지 확인하는 것은 잘못된 입력 거부 검사가 아니다. 음수·bool defect count, truthy 문자열, 비정상 verdict, 실제 validator skip 분모, provider 호출은 미검사다. 실패 시 approved→iterate 방어는 유지하되 Zeus에서는 실제 영수증에 기반한 판정 입력과 8단계 사람 인수를 요구해야 한다. 실행0.

<a id="file-09"></a>
## scripts/tests/test_debate_stagnation_check.py

1~153 전문. 6개 test_ 함수가 temp EventStore와 mock recommender로 FIRE 추천+convergence 한 번, no-fire forensic-only, approved self-skip, missing/error fail-close, argparse2를 검사한다. detector는 의도적으로 mock하여 신호 정확성은 sibling self-check와 별도다. 순차 두 번은 동시 idempotency·두 append 사이 crash·stale gen/fencing을 검사하지 않는다. approved를 외부 인수로 주면 원장 verdict가 없어도 no-append를 기대하여 caller 주장 권위를 그대로 받는 경계다. mock은 signal 객체 일부만 제공하며 SUT가 새 필드/실제 shape를 필요로 할 때 호환성 검사와 다르다. EventStore를 만드는 clean/empty 검사도 디렉터리 부작용 여부는 보지 않는다. rc3 FIRE/rc4 오류, 반환구조를 구분하는 방어는 보존하되 Zeus에서는 PG attempt·상태전이·실제 검토 provenance로 변형해야 한다. 원본 실행0, SUT/caller 전체closure pending.
