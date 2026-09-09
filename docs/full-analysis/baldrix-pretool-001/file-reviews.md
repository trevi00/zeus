# 파일별 전문 의미 기록

<a id="file-01"></a>

## scripts/handlers/__init__.py

한 줄 package docstring이다. hooks dispatcher stdin을 받는다고 설명하지만 자체 dispatcher/권한 검증/호출 함수는 없다. package 존재 의미만 있으며 generated/복제 면제 주장 없이 전문 읽었다. Zeus package 구조에 별도 흡수할 동작이 없다.

<a id="file-02"></a>

## scripts/handlers/notification/__init__.py

설정 예시와 Channel/NotificationConfig/load_config/dispatch 재수출이다. import 시 config→lib.paths와 dispatcher→lib.webhook 의존성이 로드되므로 완전한 무의존 표식 파일이 아니다. 예시 enabled=true와 webhook/token은 설정 데이터이며 송신 권한이 아니다. `enabled` 없으면 no-op이라는 선언은 정상 schema일 때만 해당한다. 이 파일 자체는 타입별 trigger를 적용하지 않는다. Zeus에서는 domain port와 외부 송신 adapter를 분리하고 명시 승인 범위가 필요하다.

<a id="file-03"></a>

## scripts/handlers/notification/config.py

frozen dataclass와 tuple/frozenset으로 채널 설정을 읽는다. 파일 open/json 오류만 except 안이고 그 뒤 cfg/notif `.get`는 list/scalar면 예외이므로 any-error disabled 계약이 완전하지 않다. enabled는 bool schema 검사가 아니라 truthiness라 문자열 false도 활성화한다. channels가 dict/string이면 대부분 조용히 빈 채널로 되며 triggers 문자열은 문자 집합으로 바뀐다. URL/HTTPS/host/토큰/길이/유효 타입 검증과 secret 참조 저장이 없다. SETTINGS_PATH와 load_config 기본인자는 import 때 CLAUDE_HOME에 고정되어 나중 env/상수 변경만으로 격리가 안 된다. 실제 pinned settings에는 notifications 키 검색 hit가 없었으나 전체 설정 본문을 읽지는 않았으므로 현재 live 설정 부재를 주장하지 않는다. 일반 프로젝트 config와 채널 권한·유효성·미설정 상태를 분리해야 한다.

<a id="file-04"></a>

## scripts/handlers/notification/dispatcher.py

Slack/Discord/Telegram용 body를 만들고 registry로 채널들을 순차 호출한다. config load와 channel iteration/type access는 sender try 밖이라 never-raises는 제한적이다. 호출자가 cfg.triggers를 전달해도 dispatch는 trigger를 검사하지 않는다. 알 수 없는 채널은 실패 tuple로 남기며 빈 채널/disabled는 같은 빈 결과다. Markdown escape·mention 차단·payload 제한·중복 방지·idempotency·전송 승인은 없다. Telegram bot token을 URL에 직접 포함하고 arbitrary webhook 주소로 POST하므로 외부 정보 송신과 secret 관리 경계가 있다. 지원 lib.webhook 전문은 기본4회 요청+1/2/4초 backoff, 요청당10초이며 2xx를 성공으로 판단한다. Telegram 응답 body의 ok=false나 수신자 확인은 읽지 않는다. retry시 이미 전달된 메시지를 중복 보낼 수 있고 전체 deadline/redirect/내부주소/프록시 제한은 없다. Zeus에 외부 송신 adapter 발상만 변형 검토; 실제 전송/수신 검증은0이다.

<a id="file-05"></a>

## scripts/handlers/notification/on_notification.py

read_hook_input→load_config→trigger→dispatch→telemetry entry다. trigger가 nonempty라도 notif_type이 빈 문자열이면 필터를 통과한다. malformed 입력은 helper에서 {}가 되고 config가 enabled면 str({})를 송신할 수도 있다. body fallback만1500자이며 실제 message/content는 길이 제한·비밀 제거가 없다. 실패 result도 notifications-sent에 기록하고 exit0라 송신 성공을 rc로 판단하면 안 된다. log에는 cwd와 exception 문자열이 남아 주소/민감 값 누출 경로가 될 수 있다. settings318–329의 command 등록은 Windows 절대경로+10초 timeout인데 한 채널 webhook 최악 지연도 이를 초과한다. hook 종료시 전체 채널 결과·telemetry가 미수집될 수 있다. smoke test 전문은 ambient env/settings 그대로 자식 실행하며 no-channel을 가정할 뿐 강제하지 않는다. 이번에는 실행하지 않았고 실제 채널/live state를 접근하지 않았다.

<a id="file-06"></a>

## scripts/handlers/pre_tool/__init__.py

한 줄 패키지 설명으로 extracted hook logic 목적지라고 한다. 실행·등록·강제 기능은 없다. 이전 scripts 원본과 byte equivalence/추출 생성자를 확인하지 않았으므로 생성물 면제를 쓰지 않는다. Zeus 개별 검토 동작 없음.

<a id="file-07"></a>

## scripts/handlers/pre_tool/agent_depth_guard.py

Agent 이름의 tool만 JSON payload와 ORCH_DEPTH 기반 검사 후 deny JSON을 출력한다. root depth0에서 next<=3을 허용하나 자체 depth 증가·자식 env 전달은 전혀 없다. 지원 agent_depth 전문은 env unset/invalid/negative를0으로 낮추는 helper일 뿐이며 lib 범위 ORCH_DEPTH 검색에서도 실제 increment writer는 발견하지 못했다. 다른 spawn pipeline 전체는 미독이므로 전역 writer 부재로 단정하지 않는다. Agent alias/다른 executor/직접 process spawn은 범위 밖이고 env는 권한 정본이 아니다. import 실패는 silent pass지만 top-level stream.reconfigure 및 would_exceed_cap/current_depth/output은 광범위 fail-soft 보호 밖이다. denial시 telemetry쓰기, tool_input malformed error는 telemetry try가 삼킨다. settings Agent command 등록은 확인했으나 Claude 런타임의 deny 소비/실제 nesting은 미검증. 지원 테스트는 env값을 직접 주입해 경계와 JSON만 검사한다. Zeus에는 task lineage·server-side depth·모델 위임 자격·예산을 PG 정본에 연결해야 한다. 본문 15x/telephone-game 외부 주장 원문은 미확인이다.

<a id="file-08"></a>

## scripts/handlers/pre_tool/critic_policy_advisor.py

Agent의 subagent_type으로 resolve를 읽고 additionalContext와 telemetry에 decision을 남긴다. critic를 호출하지 않는 advisory이며 unknown agent의 invoke도 실제 모델 자격/검토 실행을 보장하지 않는다. 지원 resolve155–210에서 정책 override가 default보다 우선이고 unknown은 invoke다; 정책 loader/등록/서명 전체는 미독이다. 중요한 연결 결함: os.environ[ORCH_CRITIC_DECISION]는 자식 hook 프로세스 안만 바뀐다. settings201–221/261–275는 pre/post를 별도 python command로 등록하므로 후속 agent_outcome_audit로 값이 전파되지 않는다. 후속434–456은 env==invoke를 critic_invoked로 저장한다. 외부에서 env가 주어져도 결정과 실제 수행을 혼동하며 agent/task/revision 매칭도 없다. 지원 테스트 전문은 subprocess의 stdout 내용만 검증하고 후속 프로세스·ledger와의 연결을 검사하지 않는다. fail-soft logging은 일부단계만 감싸고 stream configure/output/env변경 등은 밖이다. Zeus에는 결정·실행·검토 verdict를 별도 identity/receipt로 저장해야 한다.

<a id="file-09"></a>

## scripts/handlers/pre_tool/dart_strict_type_advisor.py

.dart Write/Edit/MultiEdit 신규 문자열의 regex 경고다. 문서4패턴 중 bare{}의 Map<dynamic,dynamic> 검사는 구현 목록에 없다. Map/List/Set generic, MaterialPageRoute, Dio형 이름만 보며 compiler type inference/실제 receiver binding은 확인하지 않는다. client/api 같은 일반 이름 오탐, 다른 dio 변수명/별칭/주석/string/분할 edit는 누락·오탐한다. typearg 없는 regex 뒤 prev==> 검사는 이미 regex가 <>를 허용하지 않아 실질 방어가 아니다. 5개 findings에 이르면 dedup 이전에 return해 중복만5개도 출력하고 다른 범주를 가린다. 입력 json scalar/tool_input scalar/MultiEdit nondict·nonstring은 uncaught 가능; file_path str coercion 하나로 전체 fail-open 보장하지 못한다. stream reconfigure가 import시 무조건, timed가 telemetry를 기록한다. settings5초 등록 및 write tools만 확인. 실제 Dart analyzer/프로젝트설정/지원 tests는 미검증. Zeus에 품질 승인 아닌 optional lint 힌트로만 변형한다.

<a id="file-10"></a>

## scripts/handlers/pre_tool/guard.py

Write/Edit/MultiEdit 경로 검사와 Bash DENY→autocorrect→WARN 순서다. lib.guard_patterns 전문이 실제 정책을 소유한다. 플랫폼의 신뢰할 JSON 분류에 의존하고 다른 tool/direct Python filesystem/다른 shell executor는 검사하지 않는다. Windows os.path.basename과 POSIX의 backslash 처리 차이, path resolve/symlink/.. 미정규화가 있다. sensitive basename regex는 비밀 값 내용 검사도 쓰기 capability 강제도 아니다. 원본 settings/guardian 보호 선언은 일부 명시 path/tool 경로만이고 Bash/direct I/O를 모두 막지 못한다. 회사 cmmcloud regex는 프로젝트 activate 검사 없이 command 어느 곳에나 적용되어 read/echo도 막을 수 있다.

DENY regex는 셸 AST가 아니어서 인용문/주석도 명령으로 보고 variable/alias/flag 분할·PowerShell 다른 문법은 놓친다. 특히 solo_override 첫 matching rule을 WARN으로 낮추며 즉시 exit하므로 같은 compound command 뒤의 다른 DENY를 계속 검사하지 않는다. 실제 exploit은 실행하지 않았다. 지원 git_flow_override는6개 ancestor까지 올라가 파일을 찾고 solo+direct_push_main allow 두 필드를 요구하지만 현재 git root에 묶이지 않아 부모 설정이 영향을 줄 수 있다.

docstring의 long-command timeout autocorrect는 실제 BASH_AUTOCORRECT에 없고 --no-verify 문자열 제거 두 규칙만 있다. re.sub는 전체 command의 같은 문자열을 지워 commit message/다른 인자까지 바꿀 수 있다. 수정 이후 재검사나 후속 WARN 검사도 없다. 예외 fail-closed는 Bash로 판별될 때만 deny, Write/Edit 내부 오류는 WARN 허용이다. raw tool_name/command key 둘 다 깨지거나 escaped key면 안전하게 non-Bash라고 증명할 수 없지만 docstring은 provably라 과장한다. module import/stream configure 전에 나는 오류는 main except 밖이고 output실패는 삼키므로 deny 영수증 보장이 없다. timed/오류 telemetry 쓰기 및 traceback 출력이 있다. 지원 test_guard_failclosed 전문은 in-process mock stdin/stdout과 일부 문자열 판정이다; 실제 Claude 소비·OS 경계·전체 셸 의미를 검증한 것으로 승격하지 않는다. Zeus 원형 권한 게이트 채택 제외, executor capability/승인과 제한된 lint를 분리한다.

<a id="file-11"></a>

## scripts/handlers/pre_tool/handoff_drift_gate.py

Bash 문자열에 git commit regex가 보이면 payload.cwd/HANDOFF.md를 읽어 drift advisory를 낸다. echo/주석 안 git commit 오탐, --옵션/quoted -C 공백경로/alias 변형 누락이 있고 git -C나 앞선 cd가 실제 대상을 바꿔도 payload.cwd만 검사한다. staged tree/commit될 exact bytes가 아니라 worktree 문서이므로 커밋 인수 증거가 아니다. commit이 곧 origin push라는 출력도 실제 동작과 별개다. 지원 emit_drift_advisory393–440은 read/render/check 예외를 None으로 바꿔 문서 없음/parse 실패/clean을 합친다. 렌더러/parser 전문은 이번 범위 미독이다. advisory본문 내용은 재사용하지 않고 존재 여부만 확인 후 고정 문구로 교체한다. top-level stream exception은 fail-open범위 밖. settings Bash5초 등록은 확인, 실제 사용/테스트는0. Zeus handoff 상태와 commit-revision 불변 증거를 분리한다.

<a id="file-12"></a>

## scripts/handlers/pre_tool/outpos_guard.py

회사 두 repo marker가 file_path 부분 문자열로 있으면 .dart 신규내용18규칙을 검사한다(문서15rules와 다름). 12 block/6 warn이며 회사 과거 표본에서 사용0을 금지로 일반화한 정책이다. 회사 SoT violations.md/실제 코드/승인·라이선스는 미확인이라 Zeus 공통정책으로 채택하지 않는다. 규칙은 AST/완성파일이 아니라 replacement 문자열이어서 split Edit 조합, print 공백/같은줄, doublequote relative import, 별칭 호출 등이 우회·오탐 가능하다. path activation은 lowercase지만 exemption/scope는 case-sensitive 부분 문자열이며 정확한 repo/path 경계·resolve가 없어 중첩 파일명으로 면제 가능하다. 파일 정수는 _is_outpos_path에서 str로 걸러지는 경우뿐; tool_input/MultiEdit/content malformed는 보호 밖이다. 주석·문자열·문서에 금지 토큰만 있어도 block할 수 있고 controller extends 검사도 어느 부모인지 확인하지 않는다. block 있으면 warn은 출력하지 않고 각 rule 첫match만 보고해 occurrence분모 없음. scope외/빈입력과 clean이 silent0로 합쳐진다. settings등록·지원test1–123 확인; log_utils 면제테스트의 inline print는 원래 line-start regex에 안 잡히므로 면제분기를 입증하지 못한다. 실제 Dart 실행/회사 인수는0이다.

<a id="file-13"></a>

## scripts/handlers/pre_tool/pr_squash_guard.py

gh merge 전 checks 조회 및 squash/create base 뒤처짐 경고다. _GH_MERGE_SQUASH와 _GH_CREATE_BASE는 --flag 앞에 word boundary를 두어 통상 공백 뒤 --squash/--base가 nonword→nonword라 matching되지 않는다. 실행 재현 없이 regex 의미로 도출한 정적 결함이며 live probe는0이다. merge-check branch는 다른 regex로 동작 가능하지만 -R/--repo·URL PR·cd/다른 cwd를 제대로 파싱하지 않아 잘못된 PR을 조회할 수 있다. 인용문/주석 오탐도 있다.

_check_rollup은 legacy state=PENDING에 status가 비면 pending에 넣지 않고 COMPLETED+빈 conclusion도 clean이 된다. required checks 분모·head SHA·최신 실행·승인·branch protection은 보지 않으며 SKIPPED/NEUTRAL·빈rollup·조회실패는 침묵한다. 후속 merge까지 race도 있다. Git fetch는 네트워크와 local refs/FETCH_HEAD 쓰기 부작용이 있으며 실패를 무시한 오래된 origin과 비교할 수 있다. headRefName이 fork일 때 로컬동명 branch/없는branch 혼동, quoted base미해석이 있다. stale-count>0만으로 base-only 파일이 반드시 overwrite된다는 본문 주장은 실제 merge tree/oracle 검증 없이 일반화되었으므로 채택하지 않는다. 추천 rebase/force-push는 지시가 아닌 데이터다.

settings의 hook timeout5초는 gh check 자체8초 및 다른 gh/git 누적시간보다 짧다. timeout후 침묵/부분 side effect를 성공으로 간주하면 안 된다. 지원 test_pr_merge_check_guard1–220은 초기 classifier 복제와 뒤의 mocked subprocess JSON 검사이며 실제GitHub/timeout/stale regex는 미검증이다. top-level direct-script except는 silent0, import stream 오류는 밖, timed telemetry쓰기. Zeus exact-head checks·실행 영수증·merge 승인과 advisory를 분리해야 한다.

<a id="file-14"></a>

## scripts/handlers/pre_tool/project_branch_guard.py

Path.home/.claude/state/branch-guard-config.json을 읽어 file_path prefix에 해당하는 첫 guard의 Git 현재 branch가 allowed와 같으면 허용, 다르면 deny JSON이다. _normalize는 무조건 lowercase하여 Windows에는 일부적절하나 Linux case-sensitive 구별을 잃고 separator boundary 없이 /repo2도 /repo와 매칭한다. 상대경로·..·symlink·nested repo/worktree·실제 대상파일 Gitroot는 정규화하지 않는다. 중첩 guard 중 첫 matching rule이 allow하면 뒤 더엄격한 rule은 검사하지 않는다. Git returncode를 안 보고 stdout만 비교하며 unknown/timeout은 deny라 config error silentallow와 비대칭이다. config malformed g/scalar/tools 값이면 outer exception이 전체 후속 검사도 생략한다. tool_filter 빈목록은 default3개로 바뀌고 Bash/directwrites는 범위 밖이다. branch 검사와 실제쓰기 사이 race가 있으며 파일수당Git조회누적이 settings5초를 넘을 수 있다. config CLI/실효 live설정/테스트는 미확인, writes는 없지만 Git/env 접근은 있어 source 실행하지 않았다. Zeus repoidentity+권한+lease/revision검증으로 변형해야 한다.

<a id="file-15"></a>

## scripts/handlers/tool/__init__.py

단일 package docstring이며 hook extraction 목적지 설명뿐이다. 자체 runtime 호출·검증 기능과 자동 활성화는 없다. 생성자/원본 동일성은 검증하지 않았다. 구조만 참고하며 독립 기능 채택 대상 아님.

<a id="file-16"></a>

## scripts/handlers/tool/rationalization.py

PostToolUse Write/Edit/MultiEdit 신규내용에서 한국어7개 부분문자열을 찾고 실제 파일의 TODO 포함줄3개 이상이면 advisory를 출력한다. 사용자의 정당한 범위 결정·인용문·부정문·테스트 fixture도 감지하므로 우회 의도나 critic 실제수행 여부를 입증하지 않는다. 새내용만 봐서 삭제·빈쓰기·기존문구 문맥은 빠지고 MultiEdit 줄번호는 여러 replacement 연결문의 번호이지 실제 파일 줄이 아니다. tool response 성공을 확인하지 않아 실패한 tool의 시도내용도 평가한다. 파일경로는 host에서 제한없이 read하고 stat10MB 검사와 read 사이 race가 있으며 read 실패/큰파일은 TODO0으로 합친다. content길이·findings 수는 모두 메모리에 수집한 뒤 출력만10개/80자로 제한한다. 출력snippet을 additionalContext에 되돌리므로 data/instruction 경계를 유지해야 한다. lib.hook_io 전문은 malformed를{}로 처리하고 UTF8 configurable guard가 있어 다른 hook들의 무조건 reconfigure보다 견고하나 실제Claude schema 검증은 이번미확인이다. settings PostToolUse등록 확인, feedback문서·전체tests·실제인수는 미확인. Zeus에는 주관적 advisory로만 검토하며 정책 강제나 mocked acceptance 대체가 아니다.
