# Harness scripts/lib 전수 의미 검토 — 진행 중

고정 커밋 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, 분모는 `scripts/lib/**/*.py` 43개(412,993 bytes)이다. 본문 43개를 모두 읽었다. 이 문서는 다른 harness 경로 전체 검토를 대신하지 않는다. `files.json`은 호출·테스트·Zeus 대응 추적이 끝나기 전까지 완료 상태를 부여하지 않는다. 43개 observed 사본과 pinned 사본은 CRLF 정규화 후 모두 같다. 운영 config/key/state를 읽거나 실행하지 않았다. 원본 및 Zeus 구현을 수정하지 않았다.

아래 판단은 소스 의미 검토의 발견이며, 별도 실행 영수증을 명시하지 않은 동작은 아직 실측이 아니다. 공통 흡수 조건은 Git 정의 / PostgreSQL 런타임 SSOT, task-generation 및 lease fencing, 6W 메시지, source/current-revision 바인딩, 실제 독립 lead·conductor 검토, 실제 CLI canary다. 기존 사람 승인·키·정책 결정은 이관하지 않는다. 라이선스·전체 의존성 승인도 이 파티션만으로 성립하지 않는다.

## agent-depth
`current_depth/would_exceed/child_env`는 ORCH_DEPTH 환경의 재귀 상한 3을 전달한다. 잘못된 값/음수는 0이므로 실패 폐쇄 인증이 아니다. child env가 전달되지 않으면 깊이는 잊힌다. hook의 사전 경고 아이디어만 적응하고 Zeus의 durable parent-task ancestry와 dispatch lease를 실제 권한으로 유지한다.

## approval-proof
candidate 문자열 하나의 canonical JSON을 HMAC-SHA256 서명한다. guardian 위치는 env 또는 sibling; raw key 32 bytes 이상을 그대로 쓰고 누락/읽기 실패/짧은 키는 검증 실패다. candidate 이외 revision/nonce/expiry/거절 순서는 서명에 없다. 승인 문자열 재생은 원문도 인정하는 미해결점이다. `compare_digest`의 비ASCII 문자열 입력은 TypeError 가능하다. 같은 읽기 가능한 대칭 키로 생성과 검증이 가능하므로 독립 역할 증명과 다르다. 직접 이식 거절; Zeus 독립 fenced decision과 증거 바이트 바인딩을 유지한다.

## arming
`load_rules/validate_rules/resolve_arm/_matches/decide`가 후보 정책, 승인, grade, freshness, 실행 매개변수를 결합한다. rules 파일 오류는 RulesInvalid; auto는 명시 approved=true가 필요하고 autonomous approval은 배제한다. 그러나 HMAC은 위의 replay 한계를 상속한다. 숫자 score는 NaN/Infinity를 거부하지 않는다. arm 경로는 문자열 변환 검증이라 잘못된 객체도 문자열로 통과하며 project/pipeline/cwd 존재 preflight는 ledger/실행 유효성을 증명하지 않는다. canonical alias는 주입 home과 별도 global paths 해석을 혼용한다.

`already_armed`는 l2-arm external_action intent만 있어도 배제하므로 실패 후 재시도까지 막을 수 있다. `_grade_gate`는 missing function/path/exception을 차단하지만 반환 mapping의 unknown grade는 inviolable이 아니어서 허용된다(unknown closed라는 주석과 다름); 비mapping은 `.get`에서 예외다. mixed inviolable+modifiable은 경고 후 허용한다. `_freshness_gate`의 None은 out-of-scope 허용, callable 누락/실패는 차단한다. decide의 grade/freshness 제외는 skip_blocked와 별개로 다음 후보를 본다. considered는 실제 평가 수가 아니라 입력 길이다. nonempty default idle도 최종 human 판단으로 나타날 수 있다.

`landing_census/explain`은 실행과 분리된 감사 표면이다. freshness 미측정은 별도 표시하지만 landable 수에는 포함된다. grade와 freshness 축을 분리한 설명은 적응할 가치가 있다. Zeus scheduler/adoption eligibility가 확정 증거를 재검증해야 하며 문자열 정책이나 후보 자기 주장을 권한으로 승격시키지 않는다.

## atomic-jsonl
O_EXCL lockfile, 10초 timeout, 30초 mtime stale 회수, fsync append와 tmp replace를 제공한다. 장시간 정상 보유자의 lock을 회수할 수 있고 이전 보유자가 successor lock을 unlink할 수 있다(소유 token 없음). 동일 `.tmp` 이름은 외부 직렬화를 가정하며 directory fsync는 없다. JSONL SSOT 직접 이식 거절, immutable export 도구 수준만 참고. Zeus DB transaction/unique constraint/fence로 대체한다.

## backlog
proposal/incident/completion/capture를 후보로 만들고 weights/severity로 정렬한다. proposal의 증거는 nonblank string 검사이며 claim 진실성 증명이 아니다. incident는 fingerprint의 최초 항목을 쓰므로 최신 심각도가 반영되지 않을 수 있다. capture timestamp/event id도 사실 검증 대신 출처다. resolved proposal은 union으로 재개되지 않고 completion의 claim40 식별자는 충돌 가능하다. latest verdict는 입력 순서상 최신이며 서명 검증은 호출자 몫. score NaN/Infinity가 정렬을 흐릴 수 있다. 후보 발견과 승인 분리만 적응한다.

## code-context
1-depth 파일/디렉터리를 unit으로 보고 AST imports를 계약 partitions와 비교한다. 동적 import·syntax error·상대 package imports를 놓치며 `..`를 통한 unit 횡단도 빠질 수 있다. kernel destination은 전역 허용이고 cross_allow endpoint/실제 edge 정합성은 약하다. 이 검사는 정적 보조 lint이며 hexagonal 경계의 실행 증명은 아니다.

## codex-provider
family/model allow rules, `codex exec` argv, allowlisted env, JSON 추출, Member registry/pool을 제공한다. model None은 실제 모델 정체를 모른다. env allowlist에 CODEX_HOME 등이 남아 실제 config/CWD instructions를 격리하지 않는다. stdin prompt는 안전해도 system은 inline tag일 뿐 권한 채널이 아니다. Windows shim shell=True 경로의 argv escaping은 별도 검증이 필요하다. capture_output은 무제한이며 timeout 후 descendant 정리는 보장하지 않는다. provider 오류는 CodexUnavailable로 advisory absence 처리한다.

extract_json은 fence/전체 dict/최대 brace 후보를 사용하나 문자열 내부 brace를 구분하지 않고 O(n²) 탐색한다. registry의 family는 실행 독립성 증거가 아니며 factory 반환 member family와 선언 불일치 검증도 부족하다. pool 분리 아이디어는 적응하되 Zeus adapter가 실제 프로세스 영수증·모델 설정·독립 task 역할을 기록해야 한다. 실제 사용자 CLI/인증 실행은 이 리뷰 범위 밖이다.

## completion-line
goal/included/excluded/interpretation 구조를 검사하고 파일 존재 또는 glob로 included coverage를 평가한다. 경로 confinement이 없으며 directory도 evidence로 통과한다. malformed excluded의 일부 타입은 예외, assess는 validate를 자동 호출하지 않는다. 존재는 동작/완료의 증거가 아니다. 포함·제외·해석을 공개하는 형식만 적응하며 사용자 전수 요구를 임의 제외로 축소하지 않는다.

## debate-rules
`evaluate_convergence`는 같은 gen architect verdict/fields 충돌을 영구 sentinel로 봉인하고 같은 gen critic HIGH가 있으면 approved를 rejected로 내린다. fields canonical SHA1 재현을 요구하지만 gen1 approved는 fields와 critic 자체가 없어도 수렴한다(추가 probe 재현). records의 event type과 debate identity는 함수가 검증하지 않아 호출자가 분리해야 한다. bool gen도 int로 취급한다. `detect_stagnation`은 같은 비승인 verdict+hash 변화없음인데 누락 hash도 정체로 접으며 gen 간격 연속성은 검사하지 않는다. blocker plateau는 0건의 평탄도 신호로 만들고 동일 gen은 latest count를 택한다. oscillation의 hash는 conflict gen도 포함할 수 있다. blocker cluster는 한글 suffix 근사/first representative greedy/Jaccard이며 multiplicity는 독립 비평자 수가 아니다. collect_blockers는 docstring의 gen 정렬과 달리 입력 순서 그대로다. 순수 중단 신호와 conflict 표시는 적응할 수 있지만 Zeus의 독립 lead·conductor 승인, 증거 연결 및 revision 검증을 대체하지 않는다. engine/debate 호출 전체 계약 대조는 아직 남았다.

## decomposition
wave MECE, dispatch order, scopes를 검사한다. glob overlap는 definite prefix/equality 근사여서 `*`/`?` 등의 실제 중첩을 완전 판정하지 못한다. 선언 scope가 실제 쓰기를 막지는 않는다. harvested subagent_result는 shard만 보고 stage/run을 무시하여 다른 실행 결과를 흡수할 수 있다. dispatch coverage는 acceptance delivery가 아니다. Zeus task-generation+role+shard identity 및 실제 artifact 연결로 적응한다.

## derive-state
retraction을 접은 event reducers가 7개 stage state, 완료 집합, cycle, failure family, binding, acceptance/role delivery를 만든다. PASS→DONE, FAIL/ERROR→FAILED, finished 단독은 anomaly다. 그러나 `fold_latest_verdicts`는 PASS/FAIL만 소비하므로 PASS 다음 ERROR에서도 `derive_completed`는 과거 PASS를 유지한다. stage-state와 completed의 의미가 갈린다. snapshots를 신뢰하고 cycle event는 감소시킬 수 있다. stage PASS는 gate 정의 변화와 무관하게 모든 failure family를 해결한다.

acceptance는 실제 acceptance refs 의미보다 nonempty 선언을 보고, run identity가 없다. compaction이 한 번이라도 있으면 이후 결과까지 INDETERMINATE로 처리하면서 접힌 분모를 복구하지 않는다. role delivery는 spawn key 및 PASS/FAIL 누계이고 실제 spawn 유무/시점 창을 제한적으로만 안다. summary는 latest 대신 best rank라 과거 delivered가 나중 failure를 덮을 수 있다. reducer 구조만 적응하고 Zeus typed events, monotonic revisions, result authority, immutable coverage denominator로 대체한다.

## evaluator
advisory paradox guard는 test_pass/3회/citations 등의 자기 보고를 검사한다. prompt leakage 정규식은 휴리스틱이다. AxisScore는 bool/비유한 점수·citation 타입 문제를 기록하지만 as_row 변환의 inf는 OverflowError 가능하고 NaN 직렬화도 가능하다. numeric string은 validation/aggregate 사이 의미가 갈린다. aggregate quorum은 answered 분모의 ceil(n/2)라 3명 중 1명만 답해도 합의가 성립할 수 있다. duplicate/undeclared votes나 vote-family 일치 검증은 aggregate 자체에 없다. provider family 분리는 실행 독립성의 증거가 아니다. advice만 적응하고 production 승인에는 실제 독립 증거·닫힌 electorate가 필요하다.

## evidence-freshness
증거 문자열 어디서든 가장 최신 ISO 날짜를 취한다. 미래 날짜는 negative age로 fresh, source가 수정할 수 있는 날짜이므로 권한 경계가 아니다. 7일 경과·파일 마지막 변경 비교는 보수적 날짜-only 모드가 있지만 unknown last change는 무시된다. cited-path 정규식도 제한적이다. freshness를 판정불능/오래됨으로 분리하는 형식은 적응하되 immutable hashes와 source revision을 실제 근거로 삼는다.

## external-text
EN/KR injection substrings와 role markers를 찾아 banner로 감싼다. wrapping은 source/text 내부 위조 banner와 명령을 제거하지 않는다. 출처가 비신뢰라는 표시만 적응하고 필터 통과를 신뢰나 실행 허가로 삼지 않는다.

## git-flow
frontmatter override의 소수 allow keys를 파싱한다. 파일 부재/OS 오류는 빈 설정이며 closing delimiter 검증이 약하다. solo mode+allow가 opt-in이고 unknown push gate는 `(name,None)`이라 호출자가 차단해야 한다. 순수 정책 파서이지 git 작업 자체는 없다. closed gate registry만 적응하고 외부 저장소의 과거 허용을 Zeus에 이관하지 않는다.

## guardian-contract
7개 guardian state 문서의 shape validators다. 필요 키와 일부 bool/int를 엄격히 검사하지만 freshness·positive epoch·owner·proof는 확인하지 않는다. NaN/Infinity 및 일부 malformed nested/nonhashable 값은 약한 경로/예외가 있다. JUDGES 6개는 notification을 별도 취급한다. shape success를 건강·승인으로 올리지 않는다. Zeus supervisor typed receipts로 적응한다.

## hollow-audit
tokenize/AST로 문자열·docstring을 지운 뒤 substring assertion을 찾고 hollow/weak/absent로 분류한다. tokenizer 실패 시 raw 반환, Unicode byte-column 혼용, scope/reassignment 추적 부재가 있다. regex로 해석 가능한 파일만 다루며 unresolved는 None이다. 이것은 비어 있는 검사의 휴리스틱 탐지이지 테스트 강도 증명은 아니다.

## hook-journal
hook telemetry append는 lock/fsync 없고 failure가 호출자로 올라갈 수 있다. malformed JSON은 count 없이 건너뛴다. Pre/Post를 total로 각각 세고 missing decision은 allow다. ask→Post는 session 없는 tuid로 짝지어 human이라고 추론하므로 실제 승인 증명과 다르다. denied pending도 ask_pending에 섞일 수 있다. expire rewrite는 concurrent append를 잃을 수 있다. bounded telemetry 필드와 deny→Post 경고는 적응하되 authorization과 분리한다.

## hook-protocol
UTF8 streams, JSON input Ctx, event별 output rendering, env L2 spawn flag를 제공한다. malformed input은 `{}`, unknown event는 plain output이다. PreToolUse deny dual shape, Stop/SubagentStop/UserPrompt/Post/SessionStart의 context/block 차이가 있다. hook protocol snapshot이며 현재 제품 호환성은 별도 확인이 필요하다. env flag와 hook exit는 Zeus runtime authority가 아니다.

## idempotency
`once`는 `already_done` 검사 뒤 external_action intent를 append한다. check와 append가 단일 lock/CAS가 아니라 동시 실행 시 중복 기록/수행 가능하다. intent 전기록 후 crash는 영구 완료로 간주되어 작업이 빠질 수 있다. DB unique intent + running/completed/failed reconciliation으로 대체한다.

## ids
slug는 lower/punctuation normalization으로 충돌할 수 있고 event id는 session.seq로 전역 권한을 제공하지 않는다. bool seq가 int 취급될 수 있으며 parsing은 구조 전체 유효성 검사가 아니다. 사람이 읽는 label만 적응하고 durable UUID/DB uniqueness를 유지한다.

## judge-integrity
tests 경로와 basename test_ 패턴을 판사로 간주한다. assertion 감소/vacuous 증가/skip 증가는 WEAKENED, 기타 변경은 UNDECIDABLE라 차단한다. 새 테스트는 내용 강도가 없어도 강화로 분류할 수 있고 이름 밖 validator는 무시된다. 동일 텍스트는 INTACT일 뿐 behavioral sufficiency가 아니다. incumbent test bytes 고정과 별도 reviewer 판단으로 적응한다.

## judgment-paths
autoheart의 literal runner registry AST와 pipeline cmd regex에서 판사 경로를 도출한다. nonliteral은 실패하고 존재하는 파일만 추가하므로 사라진 파일은 registry 분모에서 누락될 수 있다(anchor가 있으면 축소 탐지). pipeline regex는 주석과 진짜 명령 의미를 완전히 구분하지 않는다. named registry 일원화만 적응하고 Git tracked immutable denominator를 유지한다.

## lease
JSON lease epoch가 acquire/revoke/guard와 heartbeat를 fence한다. 파일 삭제/손상 후 epoch가 1로 재발급될 수 있고 guard가 owner를 비교하지 않아 이전 epoch1이 새 lease를 통과할 수 있는 ABA 가능성이 있다. 프로세스/파일 존재가 durable identity를 대신한다. Zeus PostgreSQL generation/owner/deployment fence로 대체하며 직접 이식하지 않는다.

## ledger
닫힌 event type/schema, locked append, next session.seq, environment provenance, preserved audit classes와 compaction을 제공한다. next_seq의 compact JSON substring 전제는 다른 whitespace 포맷의 기존 id를 놓칠 수 있다. record JSON이 object인지 일관되게 검사하지 않는다. origin env stamp는 인증 증명이 아니다.

compaction은 head snapshot + preserved audit + tail 후 네 reducer equality를 비교하지만 모든 의미를 비교하지 않는다. sidecar append 후 replace는 단일 transaction이 아니며 초 단위 이름 충돌과 keep_tail=0 경계가 있다. 접힌 원 이벤트를 이후 retract하는 의미도 snapshot에 묻힐 수 있다. event projection 아이디어만 적응하고 DB SSOT/immutable evidence, transaction/fencing을 유지한다.

## overlap
evidence-string set Jaccard(.6)로 중복 후보를 알린다. empty는 0이고 shared first8은 생략 수를 알리지 않는다. unhashable evidence는 실패한다. 같은 문자열은 같은 독립 경험이 아니며 문자열 차이는 독립성도 아니다. 중복 발견 보조로만 적응한다.

## ownership-events
component/severity/depth/causedby/synthetic와 owner wake/result 스키마를 검사한다. proposal ref는 존재 검증이 아니고 positive timeout은 NaN/Infinity를 막지 않는다. 선언된 event schema가 실제 writer 연결을 보장하지 않는다. Zeus role task contract와 실제 artifact edges에 맞추어 적응한다.

## ownership-vitals
synthetic을 attribution에서 제외하나 total 증가 뒤 continue이므로 전체 분모에는 남는다. last_ts는 timestamp max가 아니라 event order다. attribution share와 last activity는 staleness/소유자 건강을 증명하지 않는다. 정의된 기대 역할 대비 missing/stale 증거를 별도로 계산하도록 적응한다.

## params
registry→backup→seed fallback을 쓰고 읽기 중 fallback marker를 쓰거나 지운다. 숫자 검사는 bool/NaN/Infinity를 허용하고 required key 전체 검증이 없다. set의 tightening comparison은 NaN에서 우회될 수 있다. marker clearing에 선행 load 의존, backup/write에 lock이 없어 경쟁한다. 안전 정책은 runtime fallback 값보다 versioned validated Git policy로 유지한다.

## paths
home/state env 주입과 간이 paths.yaml, 필수 runtime python pin을 제공한다. `_config` lru cache는 home을 키로 쓰지 않아 env 변경 후 설정이 오래 남을 수 있다. resolve는 선언된 absolute/escape를 막지 않지만 normalize_rel은 resolve/normcase로 home confinement을 검사한다. Zeus configuration adapter에서 경계와 캐시 identity를 명시한다.

## preconditions
텍스트 hash 16 hex, dotted JSON key, interpretation 제외로 관찰 전제 변화를 찾는다. decode replacement/newline normalization 및 truncation 때문에 원문 full hash가 아니다. missing key와 malformed JSON은 absent로 합쳐지고 unknown spec은 고정 문자열, recorded 부재는 legacy 허용이다. immutable raw bytes hash와 mandatory adoption binding으로 대체한다.

## profile
작은 key:value profile 설정이며 기본 solo, fleet만 명시 인식한다. unknown key/value를 유지하고 IO 오류는 올라온다. 환경 모드 설정을 권한으로 재사용하지 않는다. Zeus deployment policy adapter에 명시 enum을 사용한다.

## prompt-clusters
digits→0/3grams Jaccard .5와 첫 대표 greedy clustering이다. 순서 의존이며 transitive equivalence가 아니다. first/last는 입력 순서, representative는 raw prompt 첫200자로 개인정보/명령 문자열을 보존할 수 있다. cluster를 사용자 재승인이나 독립 경험 수로 쓰지 않는다.

## repair-tier
stage::statement 누적 FAIL을 두 번부터 recurrence로 분류한다. 성공/cycle/retraction/compaction을 충분히 재설정하지 않고 duplicate statement는 중복 계수한다. WEBSEARCH_ALLOWED 및 과거 사용자 결정은 지금의 권한이 아니다. task-scoped recurrence와 독립 failure evidence를 적응한다.

## repro-probe
실제 재실행이 아니라 기록 분류다. transient substring(lock/429/killed 등)은 오탐 가능하고 dispatch가 끼면 repair-between으로 간주한다. single PASS를 DETERMINISTIC, no outcomes UNKNOWN을 crystallizable로 허용하는 것은 재현 입증이 아니다. 지식 승격의 증거로 직접 사용 거절; 실제 immutable trials/independent outcomes를 요구한다.

## research-digest
captured/new/flagged 및 source last_ok 건강을 분리한다. 중복으로 신규0과 수집 응답 실패를 구분하는 장점이 있다. lexical timestamp 비교/naive-aware 혼용, future response, malformed source 누락 및 expected sources 부재가 한계다. recent는 제한하나 flagged는 무제한이다. discovery-only digest로 적응하고 source heartbeat/error와 기대 분모를 기록한다.

## roster
agents/*.md 파일명으로 역할 목록을 읽는다. 파일 존재는 role card 유효성/실행 가능성/실제 독립성을 증명하지 않는다. Git role definitions와 capability validation으로 적응한다.

## seams
표/text fieldset 파싱과 identity/snake/value-map transform, exclusions, fidelity, drift와 promotion streak를 계산한다. 일부 블록만 parse해도 HIGH, depth>8 fields는 조용히 탈락할 수 있다. value_map collision은 검사하나 snake_case collision은 없다. reason str(None)도 nonblank가 되고 unknown fidelity는 HIGH처럼 취급한다. empty/empty는 transform 선언에 따라 OK가 될 수 있다.

promotion은 OK3+distinct states2를 요구하나 None hash와 known hash가 둘로 집계될 수 있고 undecidable은 streak를 보존한다. source revision/query spec 바인딩이 없다. seam 계약·DRIFT·판정불능 분리는 적응하되 실제 source-bound distinct trials로 승격한다.

## skill-contract
frontmatter/body/domain/stack/triggers/priority/id와 corpus 중복을 검사한다. frontmatter가 없는 개별 파일은 skipped라 일부 파일에서 제거하면 검사를 피할 수 있다(전체0만 not ok). trigger의 비문자 값은 str로 바뀌고 stack unhashable은 예외 가능하다. RULES18은 실제 검사 실행 수가 아니다. vocabulary drift regex는 parser failure를 적색으로 하지만 comments/source syntax에 약하다. 분모는 전체 tracked skill paths여야 한다.

## skill-eval
PRF/declared-vs-observed/self-match/multi-file/stack masking/delivery를 계산한다. 선언으로 만든 selfmatch는 운영 routing accuracy가 아니다. slice unused monolith_minchars, multi-file>1 지표는 실제 router를 실행하지 않는다. no-hit 집계는 unattributed도 분모에 넣고 positive recent 없으면 전체 기간으로 돌아간다. structural score와 실제 workload evidence를 분리하여 적응한다.

## stuck
repeat verdict/error, barren dispatch, stage pingpong, driver error의 bounded patterns를 찾는다. statement tuple 순서에 민감하고 dispatch는 실제 process 시작 증명이 아니다. stage finish가 중간에 있어도 pingpong으로 보일 수 있다. caller의 task-scope filtering을 가정한다. 경고 신호로 적응하며 자동 권한 확대·무한 재시도를 유발하지 않는다.

## suite-floor
현재 candidate tree tests glob을 canonical로 삼아 요청 suite가 이를 덮는지 검사한다. 빈 분모 실패는 장점이나 candidate가 파일을 지우면 기존 분모 자체가 사라져 감지하지 못한다. file type/contents 검증도 별도다. incumbent Git test definitions와 assertion-strength 검토로 적응한다.

## test-outcome
pass/skip/vacuous/silent_fail/red_behavior/red_infra/red_unknown/timeout을 분리하고 실패명20 이후 dropped count를 남긴다. rc0+FAIL은 silent_fail, 0 assertion은 vacuous/skip로 구분한다. regex infra 문자열은 실제 behavioral failure를 오분류할 수 있고 stdout/stderr 합치는 계약은 호출자에 달려 있다. green에 skip을 넣지만 delivers_verdict는 제외하므로 호출자 혼동을 경계한다. 판정 어휘는 적응하고 runner가 직접 기록한 returncode/timedout/bytes 증거를 실제 권위로 삼는다.

## 실제 실행 증거
`*.receipt.json`은 실제 subprocess/Docker argv, immutable image digest, test/probe SHA256, 시작 시각·경과·returncode·stdout·stderr를 보존한다. 실행기는 `run-reviewed-tests.py`, 추가 관찰은 `review-probes.py`다. source-only readonly mount, read-only root, network none, cap-drop ALL, no-new-privileges, memory/CPU/PID/tmpfs/deadline 제한을 사용했다. 테스트는 원문 바이트를 실행했다. 테스트 실행 전 executable AST 또는 원문 전체를 읽고 호출되는 의존 경로의 실행 방식을 확인했다. AST 출력은 실행 전 코드 독해를 줄이는 표현 방식이며, **원본 테스트 파일 자체의 전수 의미 검토 완료를 주장하지 않는다**. 원본 implementation 43개는 본문 전체를 읽었다.

현재 upstream 실제 PASS 8건: `test_codex_provider`, `test_evaluator_smoke`, `test_jury_quorum_smoke`, `test_research_digest_contract`, `test_code_context_smoke`, `test_hollow_audit`, `test_ownership_vitals_smoke`, `test_skill_contract`. CODEX_LIVE=0이며 jury는 fake member 왕복이다. 이 실행은 실제 Codex/다중 provider 독립 심의가 아니다. Docker image 안 codex executable 발견은 available() 결과일 뿐 로그인/가용성/실제 왕복을 입증하지 않는다. hollow 실측은 py-targeted 87 / weak 76 / hollow 0, skill contract 실측 examined 63이며 과거 주석 숫자를 현재 분모로 쓰지 않았다.

추가 18개 synthetic observation은 `review-probes.receipt.json`에 보존했다. rc0는 재현 코드 오류가 없다는 의미로, 안전성이 통과했다는 뜻이 아니다. lease ABA, old release로 new lease 해제, idempotency 동시 두 번 허용, PASS→ERROR divergence, 표준 공백 JSON event-id 재사용, unknown grade 허용, malformed depth0, 미래 증거 fresh, UNKNOWN repro 승격 허용, synthetic total 포함, NaN timeout 허용, missing precondition 무변화, NaN policy tightening, None+known seam 자동승급, gen1 빈 debate 수렴, 축소/중복 electorate, 외부 경로 완료증거, parent-relative import 누락, candidate test 삭제로 floor 통과를 관찰했다(일부 probe가 두 축을 함께 기록).

## 확인한 호출과 계약의 의미
`ontology/contracts.yaml:261`은 kernel 7 / ledger 3 / domain 32 / provider 1의 정확한 43개를 선언한다. domain은 순수라고 부르지만 approval_proof/key, arming/load_rules, judgment_paths/derive, lease, roster, suite_floor 등 I/O가 있어 이름만으로 hexagonal domain에 옮기면 안 된다. provider를 domain과 분리하고 CLI가 조합하는 방향은 Zeus와 맞는다. `cross_allows`의 arming→ledger는 env provenance 소비이며 실제 사용자 서명/독립 승인 권한을 만드는 것은 아니다.

`scripts/engine/select_ready.py` 전체를 읽었다. `select_ready`와 `is_done` 모두 먼저 derive_completed를 소비하므로 ERROR 후 과거 PASS가 남는 문제는 단순 표시 불일치가 아니다. downstream stage dependency는 completed만 보며 is_done도 FAILED 상태를 보기 전에 completed를 인정한다. D-050은 cycle redo 시 두 reducer를 맞춘 최신 결정이지만 ERROR 상태의 동일 일치까지 보장하지 않는다. D-050 원문 위치는 주 Codex에 요청했으며 이 파티션은 아직 원문을 독립 읽었다고 주장하지 않는다.

`scripts/cron/l2_driver.py:1044,1297,1871`의 idempotency 호출 문맥을 읽었다. arm-role/arm-candidate는 preflight 후 intent를 기록하고 실제 arm을 호출한다. 실패 전에 할 수 있는 검사는 앞당겼지만 기록 뒤 crash window는 남는다. spawn은 **직전 lease.acquire**를 통해 직렬화하므로 단독 idempotency race를 이 경로의 실제 동시스폰으로 바로 일반화하지 않는다. arming 호출은 sandbox.classify와 spiral_cmd.freshness_of를 주입하므로 unknown-grade 추가 probe는 lib 계약의 약점이며 현재 classifier가 unknown을 실제 반환한다고 주장하지 않는다.

`scripts/cli/judge_cmd.py` 전체: build_pool→verify_pool→machine gate→envelope 검사→멤버별 ask/parse_axes/guarded_vote→decide_quorum→projection 기록이다. 실제 CLI는 unique pool을 먼저 검사하고 한 멤버에 한 표만 넣어 duplicate aggregate 입력을 예방한다. 그러므로 duplicate probe는 현재 CLI exploit이 아니라 domain API 방어 한계다. ontology_match는 bool() 변환이므로 문자열 "false"도 True; gates pass는 호출자 자기 선언; score bool은 float 변환으로 보존되지 않는다. 따라서 단독/축소 quorum과 함께 advisory로만 해석해야 한다. 전원 부재는 quorum 기록 전 반환하여 부재 실행의 지속 기록도 불완전하다.

`scripts/cli/fleet_status_cmd.py` 전체: read_feed는 깨진 줄 count를 반환하지만 valid rows가 하나라도 있으면 cmd_feed가 rc0 및 mark-read 이동을 허용한다. 부분 해독 실패가 남은 데이터의 열람 watermark에 묻힐 수 있다. source-health absent와 feed-empty 구분은 적응할 가치가 있다. projection_pg import는 I/O 없고 psycopg는 sync/summary에서 지연 import; 이번 feed 테스트에서는 DB를 호출하지 않았다.

`scripts/cli/hollow_cmd.py` 전체: unresolved/non-py 분모를 따로 내고 positive hollow만 래칫 대상으로 삼는다. 파일명(basename) 단위 freeze여서 폴더가 다른 동명 테스트를 합친다. negated hollow는 rows 전체에 있지만 hollow/weak/absent 합계에는 빠질 수 있어 현재 테스트 코퍼스에서 합계가 맞는 것이 모든 입력 정합성 증명은 아니다.

`scripts/cli/incident_cmd.py` 전체: component schema 검사 후 ledger append, resolve는 known fingerprint와 latest unresolved를 확인한다. note는 argparse required만으로 nonblank 검증이 아니며 _all_events는 malformed line을 조용히 버린다. `test_ownership_vitals_smoke`의 'synthetic 전 지표 제외' 설명과 total==5 기대값은 서로 다르다. synthetic 전체 이벤트 분모 포함을 명시하고 건강/기여 비율의 population을 분리해야 한다.

`scripts/validators/harness_lint.py`의 top-level imports 및 check_code_contexts/check_ownership 실행 경로를 읽었다. code_contexts wrapper는 contracts 파일 없으면 빈 위반 목록을 반환하므로 lib의 엄격한 파티션보다 wrapper가 약하다. ownership fixture는 임시 home의 empty contracts를 읽고 파일/owns 중첩을 비교한다. 전체 harness_lint 소스 완료는 다른 파티션 몫이다.

`scripts/cli/skills_cmd.py` 전체: 계약 부재는 SystemExit, files 없는 경우 examined0 실패, 개별 no-frontmatter는 이름을 남기지만 corpus 성공에는 영향을 주지 않는다. load_files(home)가 먼저 global resolve("skills")를 쓰므로 전달 home과 global home이 다르면 alternate root/relative_to 오류가 생길 수 있다. 선언 분모와 적용 분모가 갈라지는 문제를 Zeus에서는 immutable tracked skill denominator로 다룬다.

## Zeus 대응 근거
이번에 직접 전체 읽은 Zeus 파일과 해시는 `zeus-comparison.json`에 남긴다. 검토 시점 작업 트리 바이트를 대상으로 하며 배포된 동작을 시험한 것은 아니다.

| upstream 기능 | Zeus에서 보존/적응할 위치와 구체 근거 |
|---|---|
| ledger/idempotency/atomic_jsonl/lease/derive_state | `application/workflow.py` submit/handle은 check+write를 Store transaction에서 수행하고 _owned는 status+generation+lease_owner+lease expiry를 함께 검사한다. `adapters/store.py`는 PG transaction advisory lock과 documents PK로 전역 writer 직렬화한다. 외부 작업은 transaction 밖이다. JSONL 상태를 SSOT로 복사하지 않는다. |
| 승인/arming/evaluator/debate/repro/seams/freshness/preconditions | `application/audit_gate.py`는 정확한 approval ID, lead:research+conductor의 accepted review와 successful inspection, source/proposal/revision/policy/graph binding 및 transitive artifact 바이트를 다시 검사한다. 문자열 날짜/표 개수/유사도/과거 PASS를 이 권한으로 대체하지 않는다. |
| codex_provider | `adapters/codex.py`는 executable resolver, stdin, ephemeral exec, output schema preflight 및 JSON schema 검증을 사용한다. source provider의 regex JSON 추출·factory family label 대신 이 adapter와 실제 실행 증거를 유지한다. 이 파티션은 commands.run_process 세부 또는 실제 CLI canary 검증을 완료하지 않았다. |
| ownership/roster/decomposition/depth | `domain/model.py` Organization은 conductor1→lead→worker 계층과 같은 team 제약, direct reporting edge, worker approval 거부를 검사한다. `application/workflow.py`는 task identity/generation과 result sender를 검증한다. env depth나 파일명 role은 권한이 아니다. |
| metrics/repair/prompt clusters/skill_eval/test_outcome | `domain/measurements.py` Definition이 population/numerator/denominator/version/query/window/minimum sample을 명시한다. 미래/naive/중복/legacy missing evidence는 unknown, task first attempt와 logical terminal success를 분리한다. synthetic 또는 과거 PASS 총계를 독립 경험으로 바꾸지 않는다. |
| params/skill admission | `domain/policy.py`는 dataclass 정책 snapshot을 제공하고 `domain/skill_admission.py`는 finite_number threshold를 요구한다. registry NaN fallback tuning을 직접 이식하지 않는다. |
| external_text/context/paths/hook protocol | `domain/model.py` compile_context는 required contract를 우선하고 provenance/source revision과 trust=evidence-not-instructions, omitted 이유를 봉인한다. hook_apply는 repository-relative script/hash 또는 exact executable alias를 검사한다. source banner/regex의 통과를 신뢰로 해석하지 않는다. |
| suite_floor/judge_integrity/health/guardian | 기존 guardian 보고서의 supervisor/deployment/releases 비교를 함께 참조한다. candidate tree 분모가 아니라 incumbent policy/test/revision과 실제 release verification을 유지한다. 이번 lib partition에서는 실행 release/rollback을 수행하지 않았다. |

## 미완료
43개 본문 및 observed 정규화 동등성 확인, 8개 upstream 실제 실행, 18개 synthetic edge probe를 완료했다. 나머지 caller/test/config 세부 대조와 아직 실행하지 않은 관련 upstream tests는 `files.json`에 남겨 두었다. 실행 전 읽은 test_lease/ledger/stuck/guardian/skill_eval은 transitive 호출 독해 또는 fixture/environment 정리 이후 실행할 예정이다. 원본 키/state/settings에 의존하는 live 축은 금지된 원본 접근으로 해소하지 않는다. 이 상태는 전수 의미 검토 완료나 흡수 승인이 아니다.


## ?? ? ?????
??? ??? ?? codex-harness? ?? ?? ???? ????? ?? Zeus ?? ??? ???. ? Codex? C:/Users/rudtn/zeus? ?? ???? ? ? ???? ??/?? ???? ????. ??? Zeus? ?? ?? ??? ?? codex-harness ?? ??? ?? ????? ? Zeus? ?? ??? ??? ???. remote push/merge/?? ?? ??? ???? ???.

?? ?? upstream PASS 3?: test_lease_smoke, test_params_smoke, test_preconditions_smoke. ? 11?? ?? ??18?, ??? ???? ??. ?? expectation/source? ??? ???. pipeline_loader/gate_runner/staleness/tick/gate_ratchet ?? ??, checks? file_exists/file_content/run/_against_rules ?? ??? ?? ? ???? source-only ???? ?? ???? ????.

D-050 ??? supporting source `harness-design` revision `20147dde412c1f2d84178d5c3665157ced1e7334`, `design/decisions/D-050-autonomous-cycle-reopen-confirmed.md`?? ?? ???. ?? ??? ??? ?? ???? ???? ???. pipeline_started compaction ??, attempts ??? state ?? ?? ??, circuit ??/?? ? ??, derive_cycle ??? ??? ??? ?? lib ??? ????.

?? ??: gate_runner ?? ERROR writer? gate_verdict(ERROR)? ??? gate_check(ERROR)+stage_finished(status=error)?. ?? PASS?gate_verdict ERROR ??? reducer API ?????. source ?? producer? PASS ?? rules gate-patterns? malformed regex? ???? ?? gate_runner ERROR?tick/??? ?? ?? ??? ???? ?? probe? ????? ?? ?? ???? **?? ??/???? ???**. ? ?? ??? ????? ???? ???.
