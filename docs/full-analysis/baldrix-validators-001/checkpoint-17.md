# 17/27 본문 checkpoint (이전 8개 기록 보존)

추가 전문 독해9개: convention97행, er122, logical143, ddl186, flow112, handoff_drift105, exit_contract_coverage158, commit_layer_adjacency200, context_coupling155. 실행0·supporting0. 전체완료/흡수승인 아님.

- convention: 임의 pipe3행을패키지테이블,DTO/error키워드를규칙검증으로취급. package는경로전체가아닌segment집합, mismatch>10이면경고조차사라짐. convention없음PASS,Java없음PASSskip. 실제코드행위/컨벤션적용검증아님. IO예외/stdinreconfigure unguarded, mainNone.
- er: 첫found파일만. 임의heading또는entity단어로정의존재PASS,관계단어한개로관계존재PASS;실엔티티/관계참조/cardinality검사없음. Mermaid제목만검사. snake_case문서단어가있어야warnings;메타heading특정목록외모두entity로오인. 설계및행동인수아님.
- logical: pipe행/PK/FK/INDEX각키워드만전체문서존재검사. crosscheck는heading개수 ER<=logical이면M:N해소OK단정하지만대응ID/키/관계확인없음. 인식0은WARNskip,ER없음조용히생략. 요구비어있지않음/semanticcoverage와무관.
- ddl: 비재귀정해진SQLglob→migration하위미포함. regex가schema-qualified/quoted PG테이블미지원,comment/stringCREATE도인식, 같은tablename최후blockoverwrite. CREATE는잡았는데tableblocks빈경우모든PK정의PASS. 전역ENGINE/CHARSET존재를강제FAIL→PG정본Zeus에그대로적용불가(문서권장인데실FAIL). logicalheadingset존재만비교,컬럼/타입/FK/index실검증없음. DB실행없음.
- flow: Mermaid열린fenceprefix만존재검사,문법/render검증아님;HTMLcomment검사는narrowlexical. USID는regexUS-숫자지만coverage는substring이어서US-1이US-10에도커버. 문서ID언급≠행동경로추적,missingidsWARN. directory없음PASS;filereaderrorsuncaught.
- handoff_drift: missing/format없음/anchor없음PASSoptout. import/read/parsefailWARN;code_blind함께있어도dependencyfail는PASS/WARN으로미검사통과가능. render exception은CurrentPhaseBlock문자포함ValueError면skip으로분류. check_drift/is_anchor 예외uncaught; detectpromotable실패는[]로무시. 실제Currentphase외작업완결성모름.
- exit_contract_coverage: fixedsourcecli/tests,syntaxerror/IOskip,문서규칙에맞는3/4/5만분모. test파일에cli stem부분문자열있으면그파일전체code/rc==digit및EXITconstantregex를관련검증으로집계→다른CLI/주석/assert없는comparison도매칭. intregex한자리뒤boundary없어30을3으로셀수있음. 모듈상수Assignliteral만해석(tupleAssign/AnnAssign빠짐),동적상수모름. no cli/no docs면everycontracttestedPASS. telemetry 실제쓰기;builtin인데WARN뿐이므로alwaysblocking등록설명과다름. 과거100%주장실행증거아님.
- commit_layer_adjacency: AstImport가여러alias중첫internal만봐lib,cli조합에서뒤reverse누락. 모든relative를intralayer가정level2이상crosslayer누락;dynamicimport/subprocess안봄. staged목록을얻고indexblob대신workingfile읽어정확staged내용검증아님. no-staged는lastcommit변경만봐unstaged/untracked누락;rootcommitHEAD~1실패[]→PASS. fixedsourcescripts이며callerCWD프로젝트아님,gitquote된경로/-z없음비ascii filename누락. OSError/SyntaxError를clean으로처리. allscope제외cron/tests도모델밖. stdoutFAILonlymainNone.
- context_coupling: closedregex currentclaim detector explicitlypartial. same줄날짜/정의상/당시이면현재주장까지전체면제,context-ok문자열위치무관면제. surfaces(home)다른root줘도handoff는_HOME고정읽어testisolation분리됨. agents루트md만,일부surface미포함;empty도absencePASS. IOreplace/uncaught. builtin등록되어도mainWARNonly,graduatetoken설명은실제단계검토필요. remoteD038원문/복제동등성미확인.

남은10 primary: ai_spec_eval_coverage.py, claim_verifier.py, contract.py, design_slop_a11y.py, doc_code_drift.py, falsy_zero.py, git_flow.py, harness_bridge_state_block.py, hashline.py, insight_index_importer_whitelist.py.

다음에 반드시 10개 전문 및 caller13검사해석/테스트지원구간읽기후최종원장. AST/검색은semantic대체금지.
