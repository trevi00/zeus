# lib001 중간 checkpoint

partition baldrix:scripts/lib:001,25개195823bytes,scope ba87eac33577c72c077359654419d3634747d503310ee8625b4689632ffd1f31. 원본 revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2. 실행/import/test/probe0. 현재 새 전문11개와 동일바이트 선행전문4개 재사용 준비 단계이며 전체완료 아님. 최종 기록기에서 rawGitblob/bytes/SHA·prior ledger hash를 대조해야 한다.

## 새로 전문 읽은11개

- __init__.py: 한 줄 shared utilities package 설명. 실행/reexport/등록 기능 없음. 원형 채택할 동작 없음; 추출 생성자/동등성은 주장하지 않음.
- advisory_research_dispatch.py: HIGH를 이미 확인된 결함이라 선언하지만 upstream validator002의 휴리스틱 HIGH는 실제 결함 증거가 아니다. 이름:key lowercase/공백정규화 SHA1 12자리 global fingerprint는 프로젝트/revision/findingidentity없어 서로다른 사례가 blocklist를 공유한다. _BLOCKLIST import생성 sideeffect는 QuotaCounter전문미독. on_corrupt empty이면 재연구 허용; 매번손상/다른세션반복에도 최대1추가라는 주장은 코드로증명안됨. should_dispatch와 record_dispatch분리라 동시중복예약보장없음. blocklistclose는 caller결과무검증,TTL/revision변경재검토없음. 실제spawn은없는결정helper. strike_dispatcher/quota/consumer남음. Zeus PG세대dedup·실제연구결과/출처·자가개선자격과분리.
- agent_tool_audit.py: agents소스고정frontmatter의tools와자기보고집합을비교. 파일없음/parse없음/toolsempty모두 mismatch[]/clean이라불명과정상혼합. frontmatter선언≠실제tool가용성/실행권한/원문검증영수증. list/set annotation강제없어문자열입력은한글자씩,nonstring항목strip예외. agentname slash/..방어는있지만Windows colon/reserved이름완전검사아님. classify_severity는citations truthiness와mismatch유무로invalidate선언할뿐실제architect결과강제는caller책임. render기본advisory는새invalidate정책을caller가안쓰면옛의미유지;overclaim사용시문구claimed_missing부정확. lib.frontmatter기존지원재사용가능. Zeus모델자격/실제toolreceipt필수.
- allsolution_metrics.py: record_phase whitelist및writebool,caller ts를int,detail300clip. sid sanitizer충돌/Windowsreservednames/Unicode path경계남음. run_phases는JSONscalar도append하고summary는.get로crash가능. break_summary reached는문서상도달한run수지만실제기록행수여서재시도/중복append분모증가;skipped도reached에포함. 손상파일/미계측run은분모제외·0률이unknown과혼합. phase순서/단한종료/세션별최종값/원인/실행자검증없음. broad글로벌state읽기,JSONL잠금/fsync/멱등성없음. 원형성과/모델자격지표채택금지,관측adapter변형.
- ambiguity_report.py: pure ducktypedformatter지만 bool(score.passes_gate)는문자열false도True,weights길이/type/finite/aggregate-consistency미검사. contributions를먼저4자리round해dominant선택,동률firstcoverage이며weights변경한두round의delta도동일기준인것처럼보일수있음. 작은개선은round뒤없어짐. 음수delta를개선이라표시하는것은점수지표정의지실제사용자명확성/SDD인수아님. sourceambiguityscore전문남음.
- autopilot_flip_policy.py: current_default0자체는다른승인/논쟁없어수정못하게하는runtimeguard없음. env해석은caller문서책임;통계→default자동flip없다는분리는유익. log_parallel_run_outcome는sid/statusnonempty만,countsnegative/bool/형변환허용,extra로sid/status/count도덮어쓰기;실제worker종료/merge충돌증거없음. telemetry문서state/telemetry와기존lib.paths실경로CLAUDE_HOME/telemetry차이. 실패telemetry의성공bool없고행수는성과/자격아님. caller/환경우선순위전이남음.
- atomic_json.py: 같은디렉토리randomtmp+flush/fsync+replace는부분쓰기독자노출줄이나read-modify-write경합/lastwriterwins/ACL유지/parentdirfsync/lock은없음. fsync오류를삼켜crashdurable보장제한. tmpopen w라확률충돌/symlinkO_EXCL아님;mkdir안함;os.fspath/urandom은try밖이라anyfailureFalse계약예외. replace_with_retry tries<=0이면max1loop인데i==tries-1불일치로실패뒤raise없이끝나writeTrue가능. 모든OSError재시도,negativewait예외;OS실측본문은이번실행아님. read_json default타입검사는dict/list만이라는doc보다모든nonNone형에적용,isinstance Trueint허용;schema/NaN미검사. Zeus PG CAS/transaction및명시writeack대응.
- autopilot_compaction.py: modulo주기결정+문구생성뿐실제compact/export/checkpoint영속성검증없음. int에bool포함,every형검사없고float/NaN/String는비정상/예외가능. sid문구/path에무검증삽입,hardcoded~/.claude/state와실효stateenv차이. 종료조건아니라는문구는runtimecap유지증명이아님;상태파일에요약쓰기지시가schema/counter를보존하도록강제안함. selfcheck본문읽었으나실행0,off일때None만으로caller전체byteequivalence단정안함. Zeusimmutablecontextartifact/checkpointfence와원상태분리.
- autopilot_pane_events.py: pane별shard는서로다른paneappend경합을줄이나같은pane에복수writer/재사용sid/did는막지못함. fields로type/pane_id/status/exit_code/ts덮어쓰기허용하여파일name과recordidentity불일치가능. paneid slash/backslash/..차단하지만Windowscolon/reserved·sid_dir신뢰·symlink경계남음. JSONsyntax만skip해scalar/잘못된schema리턴,readIO/Unicode예외;누락shard와empty동일. aggregation/중복수집/watermark/workerlease는caller범위미독. 문서python-m호출권고와달리__main__없어python-m실행은import만(이벤트발행CLI없음). Zeusworkerreceipt PGidentity와serialcollection별도.
- autopilot_pane_spawn.py: visibility-onlytail-f이며worker/LLMspawn/workertermination기능없음. psmux세션존재시log_path/worktree/pidowner일치없이기존이름재사용;sid는nonempty만이고decisionid일부검증이라이름충돌/메타문자adapter전이남음. teardown은가시성panekill일뿐workerkill증거아님. wait시간monotonic이나NaN/inf허용,내부psmuxcalltimeout/최종호출/interval로전체deadline초과가능. capturemarker는예전scrollback재사용/출력자기보고로실제새실행미확인. tailcoreutils+psmuxWindows/Linux/WSL환경미검증. doc--tailCLI예시와달리__main__없어명령인자소비없음. caller수명/실결과collect미독.
- autopilot_worktree_probe.py: 함수이름is_onedrive지만첫bool은detected가아니라safe라는반대계약주의. envskip=1/unsetnonWindows는safe반환,WSL마운트WindowsOneDrive도Linux라skip. startswithonedrive일반디렉토리오탐/다른cloudfolder놓침. resolve실패fallback이고envrootinvalidskip,실제filecloud/reparse/동기화건강상태검사없음. env설정이안전성승인으로바뀌면안됨. 외부MSLearn/실제OneDrive/permissionprobe실행0. callerhalt/rollback조건전이남음.

## 선행 전문 재사용 예정4개

agent_depth.py59행: baldrix-pretool-001/supporting-evidence.json와notes.md의depth논의,기존직접전문독해. envunset/invalid/negative0,증가전파없음. lib001새실행없음.

ac_tree.py201행,axis_scores_log.py262행: baldrix-completion-authority-001/files.json full_body,rootreader. resolution.md전문읽어기존실제실험/토론범위와정정을읽었다. emptyAC·truthyfalsegate·IDpredicate미결속,emitter실패approved;axis로그ts/NaN/selfreportedpayload와실행권위부족등. 기존Alpine관측·actualClaude는선행범위증거이며이번lib001전체검증/새실행/전체actualClaude로승격하지않는다.

autopilot_state.py343행: baldrix-stop-001/supporting-evidence.json full_body,rootreader. resolution.md전문읽어read/writebool/상태갱신/루트선택과재시도필드유실의caller결함을구분했다. state자체모든함수분석설명은codex-initial추가읽기필요. 기존원본Stop실행4자식은이번실행0와분리한다.

## 남은primary10개

advisory_ack.py,alert.py,ambiguity_score.py,atlas_embeddings.py,autopilot_kha_bridge.py,autopilot_phase1_merge.py,bash_tool_routing.py,brain_autopush.py,brain_git_status.py,brain_store.py.

직접caller/config/tests지원새독해아직0. 모든전이closure·라이선스·Windows/Linux/WSL등가·actualClaude전체·Zeus흡수false를유지한다.
