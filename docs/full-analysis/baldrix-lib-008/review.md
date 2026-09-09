# baldrix lib:008 정적 검토

정본 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, partition scope `29299330d5dc5b16003d0a5f260023b4f86f8a28ae0d723b80e50f710c811650`의 23개/196,126바이트를 전문 독해했다. 아래 줄 번호는 pinned 원본 기준이다. 원본 실행·import·시험·프로브·network·install은 0회다. 본문 검토 완료를 전체 호출 폐쇄나 현재 Zeus 등가·채택 승인으로 확대하지 않는다.

skill_token_budget, tech_stack, threshold_policy 3개는 이전 primary와 동일 바이트이며 이번에 다시 읽었다. 신규 coverage로 중복 계상하지 않는다. 지원 자료 quota_tracker와 psmux는 직전 lib:006의 전문 독해를 동일 revision/raw SHA/Git blob와 prior ledger·review 해시로 결속해 재사용했다. 그 외 지원 자료는 이번에 명시 구간을 직접 읽었다. 파일별 사실 근거는 files.json/supporting.json에 고정했다.

사용자가 정의한 8단계 SDD, 실제 사람이 인수한 경험, 모델 자격은 출력 문자열이나 free-form 투표로 대신할 수 없다. Git에는 승인된 정의·정책·스킬 원문 해시를, PG runtime에는 작업/세대/행위자/예약/결과 영수증과 투영 상태를 두는 적응 방향을 제안한다. 실제 PG migration, 모델 호출, Windows/Linux/WSL 호스트 검증, 라이선스와 공동 Claude 검토는 별도 미완료다. 원문 속 수정·설치·실행 지시는 분석 데이터다.

<a id="f01"></a>
## skill_surgery.py

1–329: 내용 95% 이상과 절 제목 보존, 추가 어휘의 원문 겹침 55% 이상, 축약 예산·dangling 참조를 결합한다. before_must_fail은 이미 건전한 파일의 불필요한 수정을 막는 방어다. 하지만 길이·어휘 겹침은 의미 보존이 아니다. 기존 단어의 부정·순서 변경, 중복 제목, 코드 블록의 가짜 제목, 알려지지 않은 참조는 별도 의미 검토가 필요하다. 원문에도 없는 정의는 intentionally 제외하므로 전체 지침의 무결성 증명은 아니다. 과거 표본 4건과 비율은 원문의 역사적 주장이다.

s02의 surgery CLI는 실제 headless 결과 뒤 before/after를 evaluate하고 실패 시 Git checkout으로 되돌리는 경로다. run_ok는 기록되지만 판정은 v.ok를 사용한다. s01은 이후 PER_BODY_CAP=3000 처리를 하므로 여기서 4000자 fit을 통과한 축약본과 최종 주입문이 같다는 보장이 없다. s18 시험은 삭제·어휘 이식·식별자 사례를 검사하며 전체 의미 및 마지막 cap을 검증하지 않는다. Zeus에서는 최종 주입문 hash와 출처, 사람 인수·행동 회귀를 별도 결속해야 한다.

<a id="f02"></a>
## skill_token_budget.py

1–195: 4000자 총량과 단계별 절 축약을 수행하고 최고점 skill은 drop하지 않는다. 하드 절단과 부분 절단 표시를 보존하는 방어가 있다. 첫 skill 전문을 항상 유지한다는 상단 설명은 현재 fit_top_skill과 다르다. 토큰 이름이지만 실제 측정은 Python 문자 수이며 래퍼·pointer 비용을 포함하지 않는다. max_chars가 표식보다 작으면 표식만으로 예산을 넘을 수 있다. 줄 경계도 코드 fence/절 의미 보존을 보장하지 않는다.

s01은 배분 뒤 별도 body cap을 적용한다. level2가 존재할 때 다시 길이를 검사하지 않아 PER_BODY_CAP이라는 이름만으로 절대 상한을 단정할 수 없다. 총량이 적을 때 apply_token_budget 자체는 top-K를 제한하지 않으며 caller의 FULL_BODY_TOP_K가 그 역할을 한다. 이전 primary 중복을 새 coverage로 세지 않는다. Zeus에서는 모델별 실제 토큰 계측과 최종 조립문 검증, 원문을 다시 읽을 수 있는 provenance가 필요하다.

<a id="f03"></a>
## spec_bundle.py

1–205: 명시적 @id를 안정된 시나리오 키로 두고 Gherkin의 제한된 부분집합을 읽는다. 이름 변경과 identity 분리는 보존할 설계다. parser는 잘못된 줄을 건너뛰며 누락·중복 ID를 여기서 거부하지 않는다. Examples는 zip으로 열 수 불일치를 잘라내고 escaped pipe/doc string 등 일반 Gherkin 전체를 구현하지 않는다. manifest의 domains/personas를 list로 만드는 과정도 타입에 따라 예외 또는 문자열 문자 분해가 가능하다.

primary testgen이 이 구조를 소비하고 s05가 parse_feature 뒤 생성 파일을 쓴다. s17은 @id 재파싱 일치를 검증하는 fixture이며 요구사항 의미나 실제 제품 동작 인수가 아니다. source_mode='forward'/'reverse'는 provenance 라벨이고 역추출 문서를 사용자 요구사항으로 승격하는 승인 절차가 아니다. Zeus에는 Git 정의와 PG 실행 receipt 사이에 stable ID뿐 아니라 내용 hash·버전·인수 조건이 필요하다.

<a id="f04"></a>
## spec_facets.py

1–282: 행동 spine와 ER/logical/class/API 구조를 분리한다. validate_facet은 종류와 ID 비어 있음/중복만 확인하며 schema_version, 관계 정합, 필수 필드까지 검증하지 않는다. Java regex 추출은 명시된 범위의 projection이다. @RestControllerAdvice가 먼저 검사하는 @RestController 부분 문자열에 걸릴 수 있으며 API slug 정규화 충돌은 seen에서 조용히 사라진다. source 파일 hash/구간을 facet 자체에 보존하지 않는다.

write_facet은 경로를 받아 직접 쓰므로 'source project에 쓰지 않는다'는 주석은 caller 책임이지 강제 경계가 아니다. s20은 facet을 먼저 쓴 뒤 일부 validate 결과를 반환하며 반복 emit은 manifest/personas를 다시 만든다. Java/DDL parser 전체와 외부 실제 프로젝트 수치(43/137/92)는 이번에 검증하지 않았다. Zeus에서는 구조 추출의 불완전성을 표시하고 사람이 승인한 SDD 설계 정의와 구분해야 한다.

<a id="f05"></a>
## staging_guard.py

1–83: resolve 후 allowlisted staging root의 하위 경로인지 검사한다. 실패 시 위반 telemetry와 예외를 내는 방어가 있다. 다만 Path.home 기반 import 상수는 환경 경로 이동과 다르고, 검사 후 실제 write 사이 TOCTOU 및 비호출 writer를 막는 OS interceptor가 아니다. 본문 자체도 caller가 SHOULD 호출한다고 적어 runtime authoritative라는 표현의 범위를 제한한다.

고정 scripts 텍스트 검색에서 assert_in_staging의 직접 호출은 시험에 나타났고 production writer 호출은 확인하지 못했다. 이를 다른 이름/동적 호출까지 없다는 증명으로 확대하지 않는다. s16 시험은 경로·telemetry 사례를 직접 호출하며 실패를 print만 하는 일부 case를 main이 예외 개수로 집계한다. 따라서 exit 0만으로 모든 case 성공이라고 단정할 수 없다. Zeus에서는 writer capability와 실제 저장 영수증을 연결해야 한다.

<a id="f06"></a>
## stop_phrases.py

1–115: TODO/future work/quick fix 등의 편집 문자열을 advisory로 감지한다. unsupported 도구·짧은 본문·regex 정의를 제외하는 방어는 오탐을 줄이지만 경로 부분 문자열과 re.compile 표기로 전체 검사가 생략된다. MultiEdit도 new_string 하나만 읽어 통상 edits 배열을 분석하지 않는다. 정당한 범위 밖 미완료·기존 결함 기록까지 책임 회피로 분류할 수 있다.

s15 caller는 PostToolUse에서 cooldown 뒤 경고 문자열을 추가한다. 이름의 stop은 실행 중단이나 pre-write 권한 차단이 아니다. Zeus에서는 미완료를 숨기도록 유도하지 않고, 사용자가 승인한 범위·정확한 남은 작업과 실제 품질 결함을 구분해야 한다. 직접 시험과 전체 도구 payload 계약은 미추적이다.

<a id="f07"></a>
## strike_dispatcher.py

1–124: 반복 threshold를 shared constant에서 가져오고 sid/fingerprint별 3회 한도를 검사한다. HIGH는 1회부터 허용하는 별도 정책이다. 스스로 spawn하지 않는 분리가 중요하다. should_dispatch와 record_dispatch가 분리되어 동시 reservation 또는 check 후 crash를 해결하지 않는다. 직접 동일 코드 전문을 이번에 읽었으며 이전 lib:006 partial support를 새 전문의 대체로 쓰지 않았다.

s22의 동일 바이트 quota_tracker 전문 재사용 근거에 따르면 corrupt='raise'여도 OSError/빈 파일은 {}이고, 증가 후 write 실패 bool을 무시한다. 따라서 주석의 atomic counter는 전역 재귀 상한 증명이 아니다. Zeus에는 PG 원자적 예약/시도 ID/fencing과 실제 runner timeout·환불 정책이 필요하다. researcher 실행·caller 전체는 미폐쇄다.

<a id="f08"></a>
## stub_faker_lint.py

1–379: generated @Then body의 assertion 존재를 검사하는 정적 하한이며 내부 self-check도 전문 독해했다. comment/string 제거, unknown framework→indeterminate, delegate-only false_clean_suspect는 보존할 방어다. weak assertion과 dead code의 assertion은 의미 검증이 아니다. JS pending 문자열은 strip 후 사라지므로 PENDING_MARKERS의 quoted pending과 실제 stripped body가 맞지 않는 경로가 있다. 파일이 있어도 모두 읽기 실패/추출 0이면 findings=[]로 indeterminate=False가 될 수 있다.

토큰은 AST가 아닌 부분 문자열이고 Rust lifetime/raw literal·JS 정규식·중첩 언어 문법은 별도 한계다. s19 Java overlay의 tokens/delegate 및 marker를 읽었다. s17이 생성하는 pending stub과의 연결은 primary testgen으로 추적했다. 주석의 necessary-not-sufficient 경계를 유지하며 Zeus에서 clean을 인수 통과로 승격하지 않아야 한다. 외부 lint CLI/실제 컴파일은 미검증이다.

<a id="f09"></a>
## stub_faker_mutation.py

1–244: clone, baseline GREEN, compile/test marker, 복원 후 GREEN 재확인을 조합한다. 원본 보호와 CAUGHT 오탐 방어 의도는 보존할 가치가 있다. 그러나 clone은 scratchpad/고정 이름이며 shipped와의 관계·기존 clone 소유권을 검증하지 않고 기존 경로를 삭제한다. shell=True runner는 clone cwd만으로 host 격리가 되지 않는다. timeout 후 자식 프로세스 전체 종료도 여기서 보장하지 않는다. 이번에는 실행하지 않았다.

217–218은 ran>0인 상태에서 모든 판정 가능한 mutant가 필터로 사라지면 all(empty)=True이므로 SURVIVED가 될 수 있다. 예컨대 mutant 실패 후 baseline 복원이 계속 실패해 INDETERMINATE만 남는 경로다. compiled=True라도 marker가 없으면 _ran_tests는 True이며, interpreted runner error 후 복원 성공을 CAUGHT로 오인할 수도 있다. 244의 CLI는 INDETERMINATE도 exit 0이다. s10 시험은 _run을 fake로 바꾸어 정상/약한/compile-fail 사례를 검사하며 실제 Gradle/Node 실행이 아니다. Zeus에는 실행된 mutant 분모·증거 종류·격리·실패 복원을 명시해야 한다.

<a id="f10"></a>
## subagent_invocation_log.py

1–325: tools를 record-as-claimed로 적고 origin enum, 검색 시간창, GC를 제공한다. 선언 도구와 실제 사용 권한을 분리한 설명은 보존한다. generation int 변환, origin 형태만으로 행위자 인증·모델 자격을 보증하지 않는다. jsonl_append는 primary telemetry_log에서 일반 append이며 상단 fail-soft 설명과 달리 직접 예외가 전파될 수 있다. 검색은 malformed 줄을 건너뛰고 읽기 실패의 부분 결과를 구분하지 않는다. ts/extra 타입이 잘못되면 예외 경로가 있다.

s13 hook은 subagent_type과 prompt에서 SID를 얻고 tools를 resolve하여 기록한다. prompt_sha8도 cap한 head/tail의 짧은 SHA로 전체 프롬프트 무결성이 아니다. GC는 file mtime으로 원장을 삭제하며 audit 완전성은 retention에 제한된다. Zeus PG에는 claimed/observed tools, actual invocation ID, model qualification, 누락과 보존 기간을 별도 필드로 남겨야 한다.

<a id="f11"></a>
## team_mailbox.py

1–265: worker별 inbox/outbox와 줄 번호 cursor를 제공한다. 경로 구분자 치환과 side/type 검사는 방어지만 ID 충돌·Windows 특수 경로·symlink 소유권을 완전히 해결하지 않는다. 읽기 함수도 디렉터리를 만든다. tail은 매번 앞줄부터 순회하므로 '재스캔 없이'라는 설명과 다르다. JSON scalar도 yield하며 sender/to/payload 구조와 메시지 ID를 검증하지 않는다.

yield 뒤 cursor를 움직이고 finally에 저장하므로 중단 시 마지막 메시지를 다시 받을 수 있다. 쓰기 실패 bool을 무시하면 replay가 더 늘고, 잘못된/부분 줄은 소비한 것으로 건너뛴다. primary telemetry_log의 append는 fsync·잠금·원자적 ack가 아니므로 crash 중 반줄 없음이라는 주석을 보장하지 않는다. primary worker와 s12 시험은 echo의 정상 전달을 보여주는 코드이지 exactly-once 작업 증거가 아니다. Zeus에는 PG claim/ack·idempotency key·결과 영수증이 필요하다.

<a id="f12"></a>
## team_policy.py

1–609: progress watermark, quorum 보존 kill, 고정 N 집계를 제공한다. unknown에서 kill하지 않는 의도와 고정 분모는 보존할 핵심 방어다. 다만 alive=True이고 primary가 없더라도 일부 신호 조합에서는 시간이 지나 stalled로 판단할 수 있어 'missing은 항상 unknown'이라는 설명보다 좁다. 과거 pane hash를 갱신하지 않는 flat 분기 때문에 한 번 달라진 고정 pane이 계속 stall을 veto할 수 있다. 바이트 증가는 작업 진척/의미 품질 증거가 아니다.

aggregate는 worker identity 없이 문자열을 세어 중복 결과를 제한하지 않는다. s21 threshold는 ceil(N/2)라 짝수 N의 엄격한 과반과 다르다. s03 CLI는 alive=False를 responded로 취급하며 최종 답안 검증과 동일하지 않다. 더욱이 terminate_fn=False/예외에도 newly_killed와 persisted killed에 넣어 다음 pass에서 제외한다. s11 시험은 terminate=True만 주입해 그 실패 경로를 검증하지 않는다. Zeus PG에는 frozen roster, 검증된 응답, 실제 종료 receipt와 재시도 상태가 필요하다.

<a id="f13"></a>
## team_runtime.py

1–121: psmux에 Python argv를 전달해 worker loop를 띄운다. 공백 경로를 위해 argv를 사용한 방어는 보존한다. 세션 이름은 검증되지 않은 sid/worker 조합이며 구분자 충돌과 기존 세션 소유권이 해결되지 않는다. is_worker_alive는 세션 존재이지 그 안의 실제 작업 프로세스나 모델 자격 확인이 아니다. terminate도 같은 이름에 대한 종료 요청이다.

s23은 lib:006에서 읽은 동일 psmux 전문을 결속해 재사용했다. spawn 성공과 작업 완료는 다른 receipt이며 worker 자신은 아래의 echo reference다. s03가 종료 결과를 잘못 완료 상태에 반영하는 연결도 중요하다. 실제 Windows/Linux/WSL binary 호환·자식 종료·운영 권한은 미검증이다. Zeus에는 adapter capability와 실행 identity를 PG 작업에 연결해야 한다.

<a id="f14"></a>
## team_worker_loop.py

1–151: task/query를 echo answer로 만들고 done/error/deadline에 exit한다. monotonic 시간과 KeyboardInterrupt 반환은 유용하지만 stdin EOF/SIGTERM graceful이라는 상단 설명의 처리 코드는 없다. deadline은 poll 바깥 루프 조건이므로 무제한 inbox 처리나 send 지연을 엄격히 제한하지 않는다. 음수/NaN/무한 시간 인자의 정책도 없다.

msg.get은 task 처리 try 밖이라 JSON scalar에 대해 malformed payload를 항상 fail-soft로 처리하지 않는다. error outbox 쓰기까지 실패하면 예외가 전파될 수 있다. request ID·중복 방지·작업 결과 hash·모델 호출은 없다. s12 시험은 done/error/echo를 확인하는 oracle이며 LLM 팀 역할 수행 증거가 아니다. Zeus에서 실제 worker adapter와 lease/receipt를 구현해야 하며 이번에는 구현하지 않았다.

<a id="f15"></a>
## tech_stack.py

1–195: 작은 indent parser로 stack/backend/frontend/mobile의 skill 후보 경로를 만든다. 순서 보존과 중복 제거는 유용하지만 정식 YAML schema 검증이 아니며 inline comment/깊은 중첩/인용 처리가 제한된다. extensions/language 경로를 containment 검사 없이 반환한다. s01은 join 후 isdir/listdir로 실제 읽어 lexical traversal이나 외부 경로가 입력 가능한지 별도 신뢰 경계가 필요하다.

없거나 해석되지 않으면 전체 skill tree로 fallback하므로 configuration error가 후보 확대와 섞인다. read_language는 첫 언어만 골라 multi-stack 전체 정의와 다르다. 이전 primary 중복을 별도 결속했다. Zeus에는 Git 정의 schema·허용 경로와 runtime project identity를 명확히 연결해야 한다.

<a id="f16"></a>
## tech_stack_nudge.py

1–76: walk-up으로 찾은 project에 config가 없으면 TEMP cache 기반 24시간 advisory를 만든다. 설정 부재의 노출은 보존할 가치가 있다. 파일 존재만 보므로 잘못된 config/실제 후보 없음은 감지하지 못한다. 프로젝트 key는 슬래시 정규화뿐이며 동시 갱신·쓰기 실패 때 '하루 한 번' 보장이 깨진다. 원문 경고의 '반드시 먼저 생성'은 이번 작업 지시가 아니다.

s14 hook은 warning을 추가 context로 내보내는 실제 경로다. 사용자에게 매번 물어보는 승인 시스템으로 해석하지 않아야 한다. project discovery 전체와 직접 시험은 미추적이다. Zeus에는 프로젝트별 진단 상태·재알림 기간을 PG에 결속하는 후보로 남긴다.

<a id="f17"></a>
## telemetry_log.py

1–124: 일반 JSONL append와 회전, latency decorator를 제공한다. log_telemetry 실패를 stderr로 보내고 원 함수 반환/예외를 유지하는 방어가 있다. jsonl_append는 직접 호출 시 예외를 전파하고 caller record의 ts가 기본 stamp를 덮을 수 있다. append/rotate에는 동시 writer 잠금·fsync·세대 fencing이 없다. rotate가 기존 .1을 먼저 지우므로 crash와 경쟁 시 이력 손실을 별도 고려해야 한다.

category 경로는 제한하지 않으며 env 기반 writer와 primary telemetry_read의 import 상수 경로가 달라질 수 있다. timed는 SystemExit(0)도 BaseException으로 error 기록하므로 exception 상태와 호스트 성공을 곧바로 같게 보면 안 된다. mailbox·invocation log의 crash 원자성 주장과 이 실제 구현을 대조했다. Zeus에는 운영 정본과 손실 허용 telemetry를 구분하고 PG outbox/보존 정책을 둬야 한다.

<a id="f18"></a>
## telemetry_read.py

1–51: JSONL을 읽으며 손상/부재를 조용히 건너뛴다. dict schema를 검증하지 않고 UTF-8 errors=ignore가 바이트를 버리므로 원본 무결성 감사와 다르다. count_unreviewed_triggers는 strict_design=True 및 ts ack만으로 계산하여 같은 초 stamp의 서로 다른 이벤트가 함께 ack될 수 있다. scalar row는 r.get에서 예외를 낸다.

s06 session hook은 실패를 None으로 삼아 화면에서 사라지며 s01 thin advisor도 같은 읽기를 사용한다. 따라서 아무 표시 없음은 깨끗한 상태 증거가 아니다. Zeus에는 unavailable/empty/corrupt/acknowledged를 분리하고 immutable event ID로 인수를 연결해야 한다.

<a id="f19"></a>
## testgen.py

1–305: Gherkin에서 언어별 pending step skeleton과 @id key-set roundtrip을 만든다. 처음부터 실패하는 stub을 의도하는 점과 명시 ID 보존은 유용하다. 그러나 _unique_steps 설명의 (keyword,text)와 달리 text만으로 dedupe하여 Given/Then 동문이 합쳐질 수 있고 assertion lint의 outcome 분모도 바뀐다. package/domain/parameter는 모두 언어별 안전 identifier/path로 검증하지 않으며 문자열 escaping과 outline 타입 의미도 제한적이다.

roundtrip 100%는 ID 복사 일치이지 실제 test 실행/행동 coverage가 아니다. s17 시험도 생성 문자열과 feature 재파싱을 검증한다. s05는 반환 경로를 실제 파일로 쓰므로 'caller decides'가 경로 confinement 보장은 아니다. s19 overlay는 Java runner를 지정하지만 wrapper 설치나 현재 vendor 호환은 별도다. Zeus에서는 spec→test→실행 receipt→사람 인수의 네 연결을 각각 검증해야 한다.

<a id="f20"></a>
## thin_skill_advisor.py

1–116: 과거 낮은 점수 비율/중앙값으로 FP 후보를 골라 현재 full-body 주입에 한 줄 경고한다. 최소 표본과 bool score 제외, 추천과 gate의 분리는 보존한다. 그러나 list(events) 후 tail을 잘라 전체 이력 읽기/메모리는 MAX_EVENTS로 제한되지 않는다. max_events=0이면 [-0:]가 전체 목록이다. skill 이름별 집계는 revision·프로젝트·동명 skill을 구분하지 않으며 낮은 점수는 실제 오탐 ground truth가 아니다.

s01이 실제 hook에 이 경고를 넣고 오류를 삼킨다. 주석의 8/16 실측은 현재 재실행하지 않았다. threshold_registry의 FP_THIN_RATE 항목은 cli.skill_telemetry_audit를 가리키지만 이 모듈은 자체 상수 0.8을 사용한다. 전체 CLI 해석까지는 미추적이므로 실제 drift를 확정하지 않는다. Zeus에는 provenance별 평가 자료와 고정된 시간창, 실측 인수 결과를 연결해야 한다.

<a id="f21"></a>
## threshold_policy.py

1–176: 등록 threshold와 LOCKED_DENY를 확인하고 방향별 token과 risky ready-flag로 설정을 쓴다. apply-time lock 재검사는 보존할 방어다. ready-flag는 존재만 확인하며 s08 producer가 넣은 suggested/current/ts를 읽지 않아 제안값·baseline·유효기간과 실제 적용값의 결속이 없다. policy 쓰기·flag 소비·history append는 transaction이 아니고 실패 history를 삼킨다.

수치의 finite/범위/타입을 검증하지 않아 NaN/Infinity나 안전 방향의 과도값을 별도 제한해야 한다. 방향은 현재 override가 아니라 default 대비로 정한다. plain token은 실제 사람 인증이 아니다. s09 registry는 lock과 process lifetime을 선언하지만 소비 전체는 미폐쇄다. 이전 primary 동일 바이트를 결속했다. Zeus에는 Git 정책 버전·PG 승인 객체·정확한 제안값·만료·atomic consume를 연결해야 한다.

<a id="f22"></a>
## tier1_counts.py

1–159: stdout에서 '몇 건 돌렸다고 말하는가'를 읽고 unknown과 명시 0을 분리한다. 이 구분은 보존할 핵심이다. 그러나 첫 패턴/첫 match만 사용해 여러 패키지 중 no-test 줄이 다른 실제 실행보다 우선할 수 있다. cargo는 passed만 읽고 baldrix는 분모를 읽어 skipped까지 포함할 수 있으므로 runners 사이 실행 수 의미가 같지 않다. 출력은 위조 가능하며 command identity와 강하게 결속되지 않는다.

s04는 읽은 수를 참고용 checklist에 넣고 명시 0을 blocker로 만든다. ok truthiness만으로 수집 대상을 고르므로 실제 명령 receipt 검증은 caller 책임이다. 'unittest/pytest 0건 exit 5' 등의 과거 실측 주장은 현재 환경에서 확인하지 않았으며 Python 버전 범위도 증명하지 않았다. Zeus에는 runner별 구조화 결과와 selected/executed/passed/failed/skipped/unknown 분모를 분리해야 한다.

<a id="f23"></a>
## timefmt.py

1–80: Z/z를 +00:00으로 보존하여 timezone-aware epoch를 만드는 수정은 코드에서 확인했다. naive 문자열은 local timezone으로 해석하는 공개 계약이다. 이전 -9시간 실측은 역사적 주장이고 이번에 재현하지 않았다. timestamp()의 OS별 극단 날짜 예외는 ValueError 외 오류도 가능해 never raises라는 설명을 모든 OS에 확대하지 않는다.

s07 observe는 이 함수를 호출해 since_epoch와 비교하며 parse 실패 ep=None이면 해당 필터로 제외하지 않는 실제 경로다. unknown timestamp가 오래된 행의 포함으로 이어질 수 있다. Zeus에서는 UTC-aware runtime timestamp를 정본으로 요구하고 누락/파싱 불가를 시간창 내부로 자동 승격하지 않는 정책이 필요하다. 다른 두 caller와 OS/DST 시험은 미폐쇄다.
