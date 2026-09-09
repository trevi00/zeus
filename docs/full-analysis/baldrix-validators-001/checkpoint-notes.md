# validators 001 중간 독해 checkpoint

고정 partition `baldrix:scripts/validators:001`, 27개 194606 bytes, scope `65be5a814113bf702f72c324932604ae34e638b30e00c68cdc03b376b09afcb9`. 상류 실행0, 아직 완료 아님. 원본 SHA 검증 메타데이터는 최종 기록기에서 수행할 예정.

전문 독해 완료 8개: __init__.py 123행, code_blind_proceed.py67, collab.py68, coverage_gate.py85, atlas_frontmatter.py185, atlas_structure.py176, ci.py197, codegen.py217. Supporting 본문 이번 범위 아직0.

독립 판단:

- __init__: main()->None stdout PASS/FAIL, never-raises/cwd contract 문서. 실제 get_validator dynamic import+호출은 예외를 막지 않고 반환값을 run_validator에서 폐기한다. graduated import 오류는 빈 목록으로 fail-open하여 blocking validator가 사라질 수 있다. 등록표는 builtin37? 정확 count 아직 미집계. graduated scan 일부 HIGH만 계산하는 범위를 일반 전체 검증과 구분. 원본 verify port 1:1 주장 원본 동등성 미확인.
- code_blind_proceed: noHANDOFF/importerror/readOSError 모두 PASS-skip. readiness 자체 예외/UnicodeDecodeError uncaught. 실패시 telemetry 실제 쓰기. main returns None so CLI FAIL stdout이어도 process0. skip와 readiness 성공 분모 구분 필수.
- collab: .github 없으면PASS, 있으면 workflow 파일 존재만FAIL/PASS. CODEOWNERS/PR template/CONTRIBUTING은 위치 하나만보고WARN. 파일존재는 실CI/branchprotection/코드오너인수가 아님. stdin/out reconfigure importtime무조건; subprocess/stdinNone/redirectStringIO에서오류가능.
- coverage_gate: advisory mainint0, fleet없음/subprocess실패/JSON오류 PASS-skip. --fleet 상대경로 존재확인은 caller cwd지만 하위cli cwd는 scripts로 바뀌어 동일상대경로가 다른파일을 가리킬수있다. liblayer에서cli import막고subprocess호출은실행권한격리아님. env상속, timeout60초부분자식/결과회수미확인. atlas dictshape/evaluate 예외 uncaught. 실제 ready→OK 문자열, notreadyWARN, 항상0. args parser는 noargs registry호출시 hostsys.argv 오염가능.
- atlas_frontmatter: ATLAS_DIR importedassetpath 고정, cwd계약과다름. doc enum에없는 procedure 허용. date regex는달력유효성/순서안봄WARN, id정규식underscore허용하며중복ID안봄. globs truthystring도통과하므로list계약미강제. supersedes는실target검사없이항상manualWARN, Consequences도WARN, deprecated superseded_by 존재/의미검사없음. meta타입을str가정 .strip예외, parser/IO오류uncaught. warnings있어도overallPASS.
- atlas_structure: registry없음/읽기실패/빈parse면도메인정합검사전체생략. depth code는dir component수로문서file포함깊이와달라예시domain/sub/type/file이3; depth4조건은registered첫segment만확인해type/subdir구조검사안함. DEPTH_BASELINE/MAX,base_depth인자미사용. md파일만capacity,시스템dirskip은domaincount만 depth/cap전체. arbitrarycommunity30/50근거외부원문미확인. filesystemerroruncaught/stdinreconfigure문제.
- ci: YAMLparser없음, anywhere push/pull_request/test/tool단어(주석/이름포함)로실행확인문구. ci.yml fallback이면trigger없어도CI인식, definedtriggerregex미사용. missingworkflowsPASS; filesreaderrorsignore/Unicodebytesignore. uvonly validPythonworkflow는toolregex에서미인식가능. 각CIfile에모든projecttype요구하여분리job오탐. keywordcoverage≠realcoverage/pass, no run/permissions/pinnedactions/skip/pathfiltercheck. mainNone/processexit0.
- codegen: Java src없으면PASS. ControllerServiceRepository명관례강제; DI패턴못찾으면PASSinfo, comment/stringregex가능. simpleclassname충돌FQCNoverwrite, XMLregexnamespace뿐method/SQL/실행검증아님. Mybatis XML없음FAIL이annotationmapper를고려안함. API endpoint/Controllerannotation 개수비는서로다른분모(class RequestMapping포함,pathoperation별다름), warnings라설명한부족도실FAIL. only첫spec경로, noerrorscatch, allmainNone.

미독19개: ai_spec_eval_coverage.py, claim_verifier.py, commit_layer_adjacency.py, context_coupling.py, contract.py, convention.py, ddl.py, design_slop_a11y.py, doc_code_drift.py, er.py, exit_contract_coverage.py, falsy_zero.py, flow.py, git_flow.py, handoff_drift.py, harness_bridge_state_block.py, hashline.py, insight_index_importer_whitelist.py, logical.py.

다음: 미독 primary 전문 → 직접 consumer(run_all/post-tool-reviewer/validate_project)의13개실제 main·stdout해석 구간/테스트 일부 → per-file metadata와지원구간hash. 기존 blocked gatewriter probe 실행·우회금지. 새폴더외쓰기/상류실행/commit/push금지.
