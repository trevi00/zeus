# lib002 전문 독해 원장

revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2, scope7ffc0ba9a878c1b400f70492ceebaebfb6500eea21636f4a3e6ae7a23c1e0b6b. 원본 실행/import/probe/network/install0. 이 파일의 항목은 전문 읽음이며 호출/테스트 전이 closure는 별도다.

## breaker.py
109줄 전문. 기록을 오래된 순서로 가정하고 마지막 연속 실패를 계산한다. 빈 표본은 openFalse라 unavailable과 cold start를 분리하지 않는다. threshold 타입/양수 검증이 없어0/음수는 성공 streak0에도 open이 될 수 있다. bool 결과와 timestamp문자열만 사용하고 task/revision/worker identity·recurrence dedup·age window는 없다. role은 corrupt와 contract_expected 아닌행을 제외해 관측분모가 줄며 contract_ok의 실제 의미는 supporting미독이다. surgery는 jsonscalar.get/Unicode 오류를 별도 방어하지 않고 OSError는 빈 결과, malformedJSON은skip; 'false'문자열도True다. 성공 하나가 자동닫힘이라는 정책이나 차단기 이후 어떤 producer가 새 성공을 만들 수 있는지 half-open/예약/수명 연결은 미확인. 실패3회가 실제 같은 결함/수리불능을 증명하지 않는다. pure _judge와 effectful reader 분리는 유용하나 Zeus PG attempt-bound breaker와 unknown 상태로 변형; 실제 canary/인가권위로 원형 채택하지 않는다.

## budget.py
162줄 전문. 응답 문자열 문자수만 누적해 입력/context/retry/provider 토큰·비용을 포함하지 않는다. vendor15x/Agent response-only 주장은 외부 사실 미검증. sanitizer가 문자를 삭제해 sid 충돌하고 Windows reserved/Unicode 이름과 caller 타입검증은 부족하다. STATE_DIR import고정; read malformed/missing→default0, 필드 int변환은예외/negative/bool허용. record는 mkdir+load/increment/write이며 writebool 무시, 동시 누락·중복호출 count 증가 가능. check_and_emit는 emit 예외도삼킨 뒤 emittedTrue/write/returnTrue라 once-per-crossing 이벤트 영수증이 아니다. cap 상향도 다음 검사 total<cap일 때만 flagreset, 부족한 상태/파일부모누락/쓰기실패는 미표시. cap zero/negative/invalid 타입 검증없고 >=는 문서 초과와 다르다. reset은 operator명시라고 설명하지만 함수권한검사는없다. advisory와 hard cap 구분은 유용; Zeus 실제 provider usage receipt와 PG atomic reservation/비용정책별도.

## bundle_assembler.py
82줄 전문. atlas/grounded/coverage dict를 묶고 endpoint query와 narration을 호출하는 순수 조립함수다. coverage verdict/banner를 검증 없이 복사하여 source provenance/expectedscope/승인/8단계 SDD를 만들지 않는다. proposal 및 pending_repo_access 표기는 상태문자열이지 apply guard가 아니다. 일부 set/sorted만 적용하며 claims/nodes/blast_radius 및 nested input을 그대로 반환해 입력순서/alias mutation에 영향을 받는다. sorted/ts-free로 byte-identical이라는 말은 입력동일·후속serialization조건에 한정; 자체 bytes/hash/encoding 직렬화는 없다. malformed type/mixed sort/필수coverage키누락은예외. present defaultTrue, glossary non-dict{}는 불명 숨김. claims를grounded라명명해도 ground_or_drop 전체 구현/실제 근거 미독. touched 미지endpoint/없는repo 영향은 endpoint_graph와coverage연결필요. Zeus immutable spec bundle/expected requirements와 evidence graph로변형, kickoff와인수완료를분리.

## cooldown.py
44줄 전문. import 때 TEMP/TMPDIR/기본/tmp를 고정하며 Windows TEMP빈값/비정상경로도 그대로. category 일부문자를_로바꿔충돌, project/session/user identity없음. caller 임의 cooldown_file를 쓰거나삭제할수있고 symlink/containment 제한없음. exists/mtime/open은비원자라동시emit가능; futuremtime/clockrollback는오랫동안suppress,NaN/negative duration은의도없는허용가능. broad예외True는실패시알림허용정책이며 exactly-once나차단보장아님. body timestamp는쓰지만판정은mtime. 원형시간debounce만변형후보,실패·권한차단을suppress하는용도제외. Win/Linux/WSL tempfile와clock실측0.

## doc_drift_common.py
57줄 전문. 외부소스를import하지않고UTF8 read하는장점. OSError만None이라Unicode오류/주입reader예외는전파. _module_reader는전역 mutable hook으로동시테스트/tenant분리없음. regex는backtick영문ASCII .py만대상이며language/path공백/Unicode/fragment/Windowsseparator미포함,../허용하여caller containment필요. _section_body는첫## heading substring만잡고 codefence안 heading도해석;lowercase비교/nested### 포함,동명후속section무시. extracted 원본동등성·생성자근거미확인; doc/code 의미증명아님. Zeus 안전한 boundedread+명시unknown adapter 후보.

## engines.py
59줄 전문. frozenmetadata2개tuple을조회하며실제dispatch/등록검증없다. dataclass 타입/unique name/path 검증없고 module registry reassignment가능. STATE_DIR import고정; unknownNone. debate4gen hard cap 설명은 runtimecap/현재설정검증아님. inventory자동반영/사용자승인지시/역사defer는소스데이터이며caller미독. Zeus Git declarative registry+domain typedcontracts 대응후보,실행기능으로흡수했다고보면안됨.

## canary.py
245줄 전문. before false→apply→after true→optional regression의 차등검증 의도는 유용하나 source의 증명/선언밖미수정/되돌림보장은 과장된다. arbitrary callback은 외부송신·commit·files밖쓰기 제한이 없고 canary bool은 문자열false도참이다. before callback 부작용은 dirty_before_all보다 먼저라 기준에 섞이고 earlyreturn시cleanup없다. dirty set차는 이미dirty인미선언파일의추가수정,ignored/outside repo,생성후삭제 흔적을모른다. repo_dirty git오류는empty set;porcelain quoting/rename/비ASCII경로 파싱이 robust -z아니다. timeout/실행파일missing은 바깥으로 전파할수있다. revert는 ls-files의모든실패를untracked로분류하고 repo/f에 containment없어 절대경로/..도가능;디렉토리rmtree(ignore_errors=True)는미삭제여도True가능. tracked디렉토리선언의미추적자식은checkout만으로남는다. extra callback 자유부작용,동시사용자쓰기 lease없음. 모든run의revert bool 무시로실제실패여도되돌렸다고보고. regression()은try밖이라예외시rollback안하며선택생략도가능. rollback성공revert stage결과가없어마지막실패=되돌림완료라는설명불성립. 시간측정wallclock이며증거artifact/argv/hash/actor/SDD acceptance바인딩없다. Zeus 격리워크트리+원시실행영수증+before/after동일오라클+검증된rollback을별도상태로구현할후보;실제모델/인수canary로승격금지.

## changelog_io.py
132줄 전문. source는append-only라고하나읽은파일전문을header아래최신entry삽입후w전체재쓰기;잠금/atomic/fsync없어경합손실.500줄trim후추가trim안내를붙여실제엄격500상한아님. file_path raw경로/backtick/newline이스케이프없어로그주입/경로노출가능. Write가CREATE라는분류는기존파일덮어쓰기와다르고실제성공/diff/contenthash확인없음. naive localtimestamp timezone없는동일초중복. harnesshome와nested .claude resolve동등성으로오염막지만exceptionFalse는guard우회. constantpaths의첫테스트temp문제는source설명이며실제실효env미검증. 읽기도error와empty동일,전체read후max_entries(negative가능),symlink권한경계없음. Windows separator정규화는basename portability개선. Zeus PG immutable change event/정확diffreceipt로변형,형식일지와실제작업증거분리.

## endpoint_graph.py
97줄 전문. atlas의node/seam/value로분류하고1hop graph를파생하는순수query. source의hallucination절대불가/여기가truth주장은미증명;atlas신뢰·현재revision·완전성·grounding실행여부를확인안함. repo우선분류로이름충돌의다른종류가가려지고duplicate seam첫값승리. repo identity를첫dot로잘라namespace충돌,missing/malformed필드예외. 직접query_repo미지repo도resolvedTrue/presentFalse,query_value미지value도resolvedTrue 빈목록이라publicquery우회consumer주의. present bool 문자열false참. 공유wire value는인과의존그자체아니며1hop/동명JOIN 밖 transitive impact없음. 입력의edges/sharedlist일부alias유지,sorted일부만이라전체serializationdeterminism별도. Zeus 파생 ontology/topology index 후보이며 Git정의/PG관측 출처·missing범위와결합필요.

## deferral.py
128줄 전문. 문서앞800자첫HTML marker의알려진counter>=정수조건으로보류/해제평가. unknown/malformed/counter예외는None=열림이라는선택은결함숨김방어지만깨진저장소를0으로읽으면known조건을계속보류할수있다. 카운터는모든JSONdict행수이며중복/불완전/서로다른task도시도횟수로누적;not r.get(ok)는문자열false를성공취급. surgery counter소스읽기Unicode예외는parse가삼켜None,of_file은errorsreplace로손상marker를무시할수있다. huge digit intneed는try밖ValueError가능,negative본문형/수동COUNTERS변경무방어. marker가codefence/인용에있어도해석. frozen NamedTuple이어도직접생성값type검증없음. 보류해제는다시질문/큐에올릴자격이지승인·수리성공아님;8단계SDD의사람인수·모델자격을30회로대체금지. caller role_orchestrator/trending전이아직미독.

## critic_policy.py
256줄 전문. invoke→skip과반대방향에다른literal token을요구하는recorded policy writer이며원문도현재실제Criticspawn/enforcement가없다고명시한다. unknown invoke기본과advisory의분리는유용. token문자열은인증된운영자/승인artifact가아니고out-of-band YAML edits는그대로resolve된다. tinyYAML은version임의정수미검증/일부손상silentdrop/중복lastwins;agent_type nonempty만검사하여개행/colon삽입하면dump가다른정책행으로분해될수있다. resolve후load재호출의TOCTOU와wholewrite경합/nonatomic/부모mkdir있음. no-op은token검사전False. IOErrordefault와Unicode예외구분. import는REGISTRY메모리추가이며apply_override는ack()를실제호출하지않음;registrydoc의human-audited ack는사람신원영수증아니다. Zeus 모델자격/독립review정책은Git승인바인딩+실제executor자격검사로변형,source token상속금지.

## criticism_dedup.py
285줄 전문. severity어휘정규화와greedy firstrepresentative Jaccard cluster,통계pure함수. UNSPEC분리는유용하지만rank0인unknown이LOW와합쳐지면maxLOW가되어unknown잔여가cluster표시에서가려질수있다. 영어ASCII토큰만으로한국어본문은empty, no/not를stopword로지워반대주장도같아질수있음. 숫자/target문자열이유사도를지배할수있고threshold범위/finite검사없음;0이면empty도합쳐짐,NaN이면모두별개. same_target_required라도둘중target없으면합침. 입력순서에결과의존,transitiveclustering아님;대상/축/project/revision/generation/독립revieweridentity필수조건아니다. duplicate3회는같은모델재진술일수있어consensus/확인된결함아님. frozenreport내dict는mutable.19schema/77sessions/21%paper/측정0%/deferredexternaljury는미검증소스주장. Zeus advisory검색/중복후보표시로만변형하고증거·독립투표제거권위로채택금지.

## debate_sessions.py
78줄 전문. events.jsonl파일존재를세션정의로일원화하고orphan따로목록하는장점. empty/corrupt/fabricatedfile도count하며directoryname/sessionid/schema/시도증거없음. symlinkdir/file을따라가scope밖세션도읽을수있음. iterdir OSError는[]라일부접근실패시전체없음,orphan0=정상이라는설명과불명혼합. recent_count는events파일아닌디렉토리mtime를봐append활동이갱신되지않을수있고OS파일시스템차이있다. futuremtime/windownegative/NaN/타입미검사. 원본수치0개/6caller일치주장·실효caller는아직미확인. ZeusPG created/last_activity/attempt수명과unknown분모로변형;파일흔적을실행세션성공으로계상하지않음.

## cucumber_scaffolder.py
197줄 전문 및selfcheck153~197미실행. 문자열build/runner를생성하고write는기존build/settings/runner보존하지만existing내용과새package의일치검사없어nooverwrite만으로glue불일치예방못함. package는Pythonisidentifier라Javareserved/허용identifier동등성없고project_name은Gradle quote에unescaped삽입. domains인자는실제로사용하지않아domain별placeholder설명과다름. Gradledeps버전문자열고정이나lock/checksum/toolchain/wrapper버전없음. ensure_gradle_wrapper는gradlew존재만으로True라jar필요계약과충돌,subprocess rc무시하며shellTrue/ambientgradle/build파일을실행하므로순수scaffolder아님. wrapperwritten목록은기존파일도포함;정확수정영수증아니다. writer checkthenwrite TOCTOU/부분완성/symlink경계없음. 내장테스트는문자열substring과invalidpackage1건뿐실제Gradlediscover/compile/firstRED증거아님. Zeus SDD scaffold준비단계변형후보;N>=1발견·의도한assertion 실패·진짜인수·승인정본분리필수. 원본Gradle실행/network/install0.

## dart_scaffolder.py
150줄 전문 및selfcheck111~150미실행. purestringseed+effectfulwriter분리. GHERKIN_VERSION caret라dependency잠금아니며API/stopAfterTestFailed가nonzero exit를보장한다는vendor주장은원문미확인. 서로독립hardcode convention이므로testgen과절대로어긋나지않는다는문구불성립. _pkg_name은digit시작/reservedname허용,collisions가능;domains는raw import/identifier에삽입하여quote/newline/../이름오류검증없음. 빈domains/feature0에서발견분모보장없음. existingrunner/world보존은좋으나새generatedsteps와버전/집합불일치를감지안함. write checkthencreate에원자성/rollback/symlinkcontainment없음. 자체selfcheck는substring형식만확인하고실제Dart컴파일/gherkin실행·firstRED·제품인수아님. sourceprotocol은data,Zeus8단계의생성물/실행영수증/인수분리후보.

## debate_doubts.py
166줄 전문. globaldebates를스캔해모든payload의self_doubt키를수집하며actor/event/verdict/gen검증없다. malformedJSONskip,scalar.get나timestamp타입오류는파일전체나머지를broadexcept로버려unknown이빈목록처럼보임. directoryiter오류는바깥예외. since invalidNone은필터없이전체,negative는future;timestampNaN처리미검증. doubt문자열type/길이제한없이수집하고renderlen/slice는dict/int에서오류가능. session단위ack는새generation/newdoubt도이미seen으로만들고seen≠문제해결/사람승인. importSTATE_DIR/path고정,sys.path수정,stdoutreconfigure무조건호출로embeddedstream호환성미검증. docs cli.debate_doubts와실제lib본체의shim동일성은support필요. exportjson defaultstr로타입오류를숨길수있음. Zeus immutable doubt event+건별ack와pending잔여표시로변형;토론자기보고를정답/학습자격승격금지.

## debate_output_audit.py
141줄 전문. sharedLEAK_PATTERN_REGEX를import하고postparse관측에서ledger/events예외+bare sid보정을한다. 경로/과거gen단어는격리실패의인과증거가아니며허용입력/교육내용/정당인용구분없음. _LEDGER_CITATION의../와임의prefix를허용하는lexicalwhitelist는정본경로resolve가아니고case sensitivity가공유pattern과불일치할수있다. 모든events언급이legit인경우토큰제외하는분리는유용하지만actualpermission/컨텍스트leakabsence를증명하지못함. bareSID는timestamp6digits+loweralnum4만봐다른형식/uppercase누락;sharedpattern먼저bareSID나중이라문서전체firstoccurrenceorder보장아님. nonstringinput[]는미검사와clean혼합,메시지무제한/dedup매번set로O(n²)가능. import의evaluator_dispatcher전이/부작용미확인. render는leaks가있다는이유로verdictreliabilityreduced를선언하지만실제평가변경은caller에달림. 과거실측/플랫폼vendor계약미검증. Zeus leak의심관측과실제입출력권한/승인증거분리.

## debate_convergence.py
222줄 전문. same-gen verdict/snapshot모순sentinel을끝까지유지하고이전conflictsha사용금지, severityinvalidate가declared승인을덮는방어유용. 그러나actor architect검사/session/revision/attempt/출처검증없고bool gen도int로수용. truthy nondictpayload.get예외. fields가임의nonemptyJSON이면hash가능,NaN/Infinity도canonicalJSON기본허용;Unicode encode예외는try밖. absent/empty/nonserializable는None으로합쳐같은verdict두손상이idempotent로취급될수있고'byte-identical'은원시event전체동등성아니다. gen1 approved는snapshot없어도convergedTrue라snapshot_missingFalse;gen>1은이전snapshot내용일치만필요하고이전declaredapproval/severityvalidity는요구하지않음. max_gen은전체hardcap가아니라missing snapshot의earlyerror용으로만사용:유효snapshot이면gen상한넘어도승인가능. typedSDD/필수조건/실행영수증/사람인수는없다. Zeus 토론수렴을설계진입신호로만변형,8단계완료/흡수승인과분리.

## decision_memory.py
412줄 전문. 결정보존/재질문억제용JSONL이며survey목록에서대상이사라지면안착한다는source주장은측정누락/오류/명칭변경과실제수리를구별못함. role+target12SHA는task/repo/revision/attempt없고대상꾸밈으로ID가달라져반복을놓칠수있음. evidence숫자추출은단위/의미/본문변화를버리고200자fallback도충돌가능. tolerance20% higher정책은모든지표에안맞고NaN/Inf/negativeTol/type미검증;무현재근거일때staleFalse유지하면서render는근거같고아직유효라강하게말한다. source_ts는optional,같은batch seen갱신없어중복기록;동시load+append노락이고전체partialappend오류도0반환하여재시도중복가능. invalidJSONskip/scalar와unhashableid/source_ts는예외,neverraise설명은실제try범위와다름. missingassign_to→none=거절이되어불완전결정이유효거절로억제될수있음. timestamp문자열정렬/동초tie는로그순서에의존. _match set순회와_evidence_for insertion순회는중복substring대상의임의선택;recall은load여러번해동시스냅샷불일치. prompt삽입문자열unescaped/제한은일부field뿐. Zeus PG immutable candidate+identity/CAS와reopen근거,unknown분리후변형;과거판단/횟수/수치감소≠승인/사람인수.

## debate_stagnation.py
736줄 전문(1~370,371~736)과selfcheck434~736정적독해. verdictfields에서같은snapshot_sha1을파생하지만explicitontology_hash가actor/형식검증없이override하고동일genlastwins라convergence의conflictsentinel정책과다르다. payload/ontology nondict.get예외,gen bool/negative허용;blockers int만읽어실제list형blocker누락,bools도count. '연속Kgen'은관측된gen정렬tail이라중간누락을잇는다. missing모든hash에서unique0<=1로stagnationTrue여전히가능;changes는고유hash수-1이지전환횟수가아님. oscillation은tail어디든ABA면현재끝hash가복귀안했어도detect. plateau는0,0,0도detect하며개수같은서로다른문제와심각도/수리/독립review분모를모름. mixed는last>=first만보고중간값이first보다작지않다는doc조건을검사안함. 세추천ANY는현재approved여도다른plateau로hardcap권고가능;actualcancel/worker종료없음. sourceCLI마지막notwired와상단consumer설명은caller에서확인필요. selfcheck의실제livehome경로 fixture없으면두caseTrue로세고skipdetail는ok일때출력에서삭제,최종passed분모에skip포함. syntheticontology_hash fixtures는실제producer없다는source설명과다름. 이번live경로접근/실행0. Zeus advisoryprogress신호와unknown/중복/actor/expectedgen분모,실제deadline/cancelreceipt를분리한변형후보.

## Supporting 연결과 판정 정밀화
새독해는 supporting-evidence.json의정확구간만이다. cli/debate_converge_check39~95는priorconvergence를먼저반환하여뒤늦은severityinvalidate/모순verdict를재평가하지않는다. primary의방어를caller replay가우회할수있는정적전이이며checkthenappend는원자예약아니다. cli/debate_stagnation_check85~146는입력verdict approved에서selfskip하여primaryANY권고가항상승인된토론을멈춘다는일반화를막는다. 그러나입력verdict는caller문자열이고forensic+terminal두append는transaction아니다. lib의notwired문구는이CLI및commands43~82의실제호출지시와불일치한다. 문서의'부분실행불가능'은두append실패/프로세스중단을입증하지못한다.

role_orchestrator48~86/140~190: deferral미달항목을queue에서제외하고head의'적용됨'문자열도제외조건이다. DM예외는past[]라기억불명표시없이계속;target그대로인용과none=조치불필요는prompt규약이다. 배정은제안·자동spawn아님이라는범위구분을확인했다. 주어진source문서의운영자회피/역할지시는분석데이터이며현재Zeus권한지시로상속안한다.

greenfield_spec_emit90~146: 같은pkg를testgen과Java scaffold에전달하지만이미있는runner를scaffold가보존하는경로의불일치는남는다. 먼저feature와testgeneratedfile를직접write하여scaffolder no-clobber가pipeline전체nooverwrite는아니다. Dartdomain전달은같아도명명/compile계약별도. 실행0.

test_canary84~158은신규미선언파일cleanup,선언dir범위,정상tracked/untracked복원,cleanup호출,after실패,regression생략happy path를assert한다. 기존dirty파일추가변경/rollback실패/exception/ignored/outside부작용을이구간에서는검사하지않는다. _repofixture와나머지범위미독;원본테스트실행0. test_debate_convergence176~230은gen1approved snapshot없음허용을의도적으로assert하고missing-boundary3점을검사한다. 실제인수·runneroracle가아니고주입event정책단위테스트이며fixture/나머지범위미독.

resident_store132~190의contract_ok는noncontract True,compacted는저장bool,partial/artifact_missing은artifact의parse_contract성공으로판정한다. 따라서breaker의쓸모있는결과는현재코드상계약파싱수준이고실제검증·수리성공아니다;parse_contract전문은아직미독. meeting_ingest35~60은atlas→ground_or_drop→coverage→assemble를확인했으나외부grounding/atlasclosure미완료. evaluator_dispatcher110~153의공유regex는IGNORECASE이고슬래시경로/단어만스캔하여postauditcase예외차이를확인했다;dispatcher전문/실제provider미검증.

critic_policy_advisor68~110는resolve후자기process os.environ을설정하고additionalContext출력만한다. 다른posthookprocess에그env가전파된다는증거는없다. reviewer430~464/671~708은logging은cooldown없고review/errorfeedback은cooldown으로제어하며broadexcept후exit0이다. agent_invocation_audit186~225는subagent_invocation_log호출이며동명이함수때문에budget.record_invocation연결로오인하지않았다. 이지원구간은budget직접caller증거가아니다.

## 선행 전문 재사용3개
calendar_gate.py482줄은baldrix-stop-001/supporting-evidence.json full_body와codex-initial/resolution의calendar항목을재사용한다. scanner는날짜주입/오류목록/별도순수판정이유용하나missing/noledger/nooverdue와reader오류가caller에서모두no-block으로합쳐질수있다. 상태defects0/duedate수정은actualfix/authorizeddeferral증거아니다. rawschema/unknown/중복/경로/사람인수closure미완료. 호출calendar_gate_emitter가errors를버리고Stop등록배열에없다는선행범위제한을보존한다.

completion_gate.py438줄과coverage_gate.py80줄은baldrix-completion-authority-001/files.json full_body 및codex-initial/resolution을재사용한다. completion은명시evaluator요구경로의방어가있지만typedbool/numeric엄격성·task/attempt/runnerreceipt없고freshness timestamp/동일초/NaN/unknown읽기/중복count와scopebinding한계가있다. approved는cap보다먼저판정하므로cap을무조건정지로해석하면안됨. coverage는explicit set/잔여banner파생이지만emptyatlas0/0ready,present기본True,미지touchedseam누락,이름dot추출과duplicate/truthiness조건이있다. readiness는SDD인수/배포승인아니다. 이번meeting_ingest직접지원은추가구간이며선행원본실행/actualClaude를이번새실행으로계상하지않는다.

라이선스와vendor원문·역사승인·전체model/OS/runtimeclosure는미확인이다. Zeus8단계SDD의요구명확화→명세→설계→구현→검증/인수각전이는versionedrequirement/정확실행영수증/사람승인정본에묶어야하며본분류가기존8단계정의를대체하지않는다. source정적토론수렴·카운터·형식selfcheck·mockfixture는인수대체불가. 대응은Gitdefinition/PG runtime·generation/CAS/lease·immutableevidence를갖춘변형제안에한정한다.
