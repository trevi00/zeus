# 파일별 독립 정적 검토

<a id="file-19"></a>
## scripts/tests/test_q_activation.py

1~201 전문. 10개가 budget cap 아래/초과 emit once·cap 상향 재설정, heartbeat CLI schema와 event enum을 검사한다. find_stale라는 이름과 달리 둘 다 시간을 넘겨 둘 다 stale인지 보며 fresh 제외를 입증하지 않는다. CLI no-stale 시험은 만든 td를 전달하거나 env에 연결하지 않아 기본 상태를 읽는다. clock은 원래 함수를 복구하지 않고 새 lambda로 바꾼다. 문서의 prune-after 삭제·실제 stale emit 주장은 해당 검사가 없다. cap 경계값 동일·emit 실패 후 플래그·동시 dispatch/세대 dedup는 미검사다. Zeus quota/heartbeat는 PG 원자적 전이·lease와 실제 발신 receipt가 필요하며 횟수는 인수 승인과 다르다. 실행0.

<a id="file-20"></a>
## scripts/tests/test_quota_tracker.py

1~222 전문. 12개가 cold load/increment/reset/remaining, 입력 유효성, corrupt raise 대 empty 및 coerce 대 filter, subsystem 분리를 검사한다. coerce bool→1을 명시 허용하고 empty 정책은 손상 상태에서 예산을 초기화할 수 있다. STATE_DIR 변경은 복구하지 않는다. atomic increment라는 설명에도 순차 호출뿐이며 lost update/락/중단·stale generation·negative/coerce float·경로 sid/subsystem 탈출을 검증하지 않는다. Zeus에서는 PG transaction과 제한 정책을 정의하고 reset을 승인 권한과 결속해야 한다. main rc1, 실행0.

<a id="file-21"></a>
## scripts/tests/test_ratio_tracker.py

1~147 전문. 10개가 파일 roundtrip/reset, 여섯 tool enum 카운트와 Bash 무증가, 경고 임계와 상수 sanity를 검사한다. 전역 파일 경로를 복구하지 않고 cooldown/시간 reset/실제 track_and_warn 통합·동시 쓰기·손상은 미검사다. threshold 검사 일부는 MIN_EDITS보다 작은 고정 modify3이면 실제 threshold 경로 없이 통과할 수 있다. Read 횟수는 전문 의미 독해가 아니고 Bash가 실제 수정을 해도 제외된다. Zeus coverage 원장은 범위/해시/판단을 요구하며 ratio를 승인 근거로 사용하지 않는다. 실행0.

<a id="file-22"></a>
## scripts/tests/test_read_paths_are_pure.py

1~144 전문. pytest 함수 없이 main이 AST 함수명 heuristic+본문 substring .mkdir(의 발견 집합과 5개 allowlist를 정확히 비교한다. 독스트링이 한계를 정직하게 명시하지만 성공 문구의 전부 쓰기 전용 확인은 실제 caller 검사 없이 고정 사유에 의존한다. syntax error/없는 root는 건너뛰고 이름에 ensure가 있으면 제외하며 alias/os.makedirs/간접 호출은 못 잡는다. 함수 내부 주석/문자열도 substring으로 오탐 가능하다. exact 집합 덕분에 전체 빈 스캔은 gone 실패하지만 실제 read purity 증명은 아니다. Zeus read-only 분석 계약에는 실제 transitive side-effect 및 격리 관측이 필요하다. 실행0.

<a id="file-23"></a>
## scripts/tests/test_reflection_recall.py

1~172 전문. 9개가 임시 HOME의 wonder write/recall, fingerprint 필터·최근 순서·cap·빈/invalid/determinism, ralph prompt 삽입을 검사한다. cap는 heading 개수만 보고 가장 최근 두 본문은 assert하지 않는다. byte-identical은 같은 현재 SUT의 default와 빈 인자를 비교하는 문자열 동등성으로 이전 revision 바이트 검증이 아니다. imported modules가 call-time HOME을 쓴다는 가정 및 모든 전이 쓰기 격리는 별도다. lesson 문장은 외부 데이터로서 신뢰/권한 분리·토큰 예산·중복세대/동시쓰기·모델이 실제 학습/수정했는지는 미검사다. Zeus 자가개선은 기록→제안→독립검토→실제시험/인수로 결속한다. 실행0.

<a id="file-24"></a>
## scripts/tests/test_reflexion_integration.py

1~145 전문. 2개가 네 번의 helper 호출에 수제 tests_passed/validators_passed와 lesson을 넣고 pending/count/파일 본문/다음 directive 재삽입을 검사한다. live/full-cycle이라는 설명은 실제 Stop event, 모델 응답, validator 실행, 상태 save/reload/락, 실제 retry 수정·성공을 포함하지 않는다. 임시 wonder 저장소의 문자열 roundtrip이다. all-pass도 self-reported boolean에 불과하고 reflection의 권고가 실제 결함 해결 증거가 아니다. Zeus no-mocked-acceptance에 따라 단위 통합 보조자료로만 변형한다. HOME finally 복구/main rc1, 실행0.

<a id="file-25"></a>
## scripts/tests/test_reflexion_loop.py

1~218 전문. 11개가 per-axis fingerprint 안정/strike2, capture stale/absent/noop/written·cap, state 구버전 기본값/유효성 및 directive 조합을 검사한다. at-most-one write라는 이름은 한 번만 호출하므로 중복 재전달 억제를 검증하지 않는다. all-pass는 새로운 sid에서만 보므로 실패→성공→실패 누적 reset도 미검사다. fingerprint는 축에 기반한 관측 proxy로 서로 다른 실제 실패·goal generation·권한을 결속하지 않는다. state roundtrip은 저장/동시성 아닌 dict 변환이며 counts≤requests 등 관계도 미검사다. Zeus에는 lease/fencing·실제 실패 receipt와 retry 제안의 인간 인수 경계가 필요하다. 실행0.

<a id="file-26"></a>
## scripts/tests/test_register_task.py

1~221 전문. 14개가 command 기본 token 부재/명시 옵션, signature, source token/주석 제거 문자열, remove 안내/함수, pythonw 이름·cmd 부재, ps1 존재/BOM, cadence/locale 호출을 검사한다. 등록·조회·삭제나 스케줄 실행은 전혀 하지 않으며 ps1 본문 무credentials/실제 창 없음·quote 보존을 증명하지 않는다. with-token True는 인자만으로 gate token을 내장하도록 고정하여 플래그 존재와 사람의 승인 권위를 혼동할 수 있다. defined-minus-declared 방어는 목록 누락을 잡지만 stale/중복 목록은 별도다. source 지시는 데이터이며 token 값은 보고서에 복제하지 않는다. Zeus 스케줄 정의와 PG generation/dedup/lease, 독립 승인·실제 실행 receipt를 분리한다. 실행0.

<a id="file-27"></a>
## scripts/tests/test_rejection_memory.py

1~296 전문. 26개가 숫자 fingerprint/상대 변화·shape/missing, 거절 억제와 stale 재개방·표시·정렬/다른 배정 보존, 측정측 evidence 및 direction을 검사한다. load를 수제 Decision 목록으로 바꾸므로 실제 저장/마지막결정순서·권한·원본 측정 freshness 검증은 아니다. 현재 근거를 못 구하면 거절을 유지하는 정책은 PG 실제 승인 expiry와 다르다. 값이 높으면 나쁘다는 가정의 검사는 source에 문자열이 있다는 수준이며 모든 producer의 의미를 확인하지 않는다. sample-count 시험도 같은 입력 동등성일 뿐 provenance를 결속하지 않는다. Zeus 거절은 근거/revision/세대/유효기간에 묶고 조회실패를 새 인수 승인으로 승격하지 않는다. 실행0.

<a id="file-28"></a>
## scripts/tests/test_repeat_error_tracker.py

1~122 전문. 8개가 Linux path 정규화 fingerprint, 빈 입력/indicator, strike2/4 메시지 및 임시 파일 잔여 부재를 검사한다. atomic-save 시험은 .tmp가 없는지만 검사해 저장 파일 자체가 전혀 없어도 통과한다. 전역 storage 복구가 없고 실제 os.replace 실패/동시성/Windows path·세션 간 충돌·중복 event/TTL은 미검사다. clean 출력도 hash를 만든다는 계약이므로 caller의 indicator 선행 방어가 필요하다. Zeus 재현/자가개선 판단은 반복 문구와 실제 실패 receipt를 구분해야 한다. 실행0.

<a id="file-29"></a>
## scripts/tests/test_repo_health.py

1~122 전문. 4개가 source 위치 .git의 bare/top-level, 로컬 snapshot branch와 ls-remote, 실제 pre-push 문자열을 검사한다. .git/로컬 branch/hook 부재나 network 오류를 일반 return하여 수동 main/pytest가 통과로 셀 수 있다. top-level은 nonempty만 보고 정확한 source root와 같음을 요구하지 않는다. env/global config/credential helper는 상속되고 실제 원격 조회 경로가 있어 이번 실행금지 범위다. 과거 bare 결함은 원인 미재현이라 명시되어 있으며 테스트로 원인을 해결한 것이 아니다. Zeus Git 정의 건강/백업 관측을 실제 인수와 분리하고 skip 분모·remote 자격을 명시해야 한다. 실행0.

<a id="file-30"></a>
## scripts/tests/test_repro_probe.py

1~80 전문. 6개가 deterministic처럼 보이는 excerpt의 Probe.passed True, transient keyword/placeholder/missing 분류를 검사한다. 원래 실패 동작을 재실행하지 않으며 문자열 분류 결과가 재현 성공이라는 증거가 아니다. fingerprint 형식/정확한 대상revision·혼합 오류·Unicode/긴 입력·false positive·worker 종료는 미검사다. 과거 차단된 probe는 재시도하지 않았다. Zeus reproduction은 격리된 실제 argv/결과 receipt를 요구하고 이 primitive는 분류 후보로만 사용한다. 실행0.

<a id="file-31"></a>
## scripts/tests/test_research_extractor.py

1~322 전문. 22개가 threshold env/범위, JSON dict/fence/오류, fake provider bypass/structured/fallback, schema prompt와 model 인자 precedence를 검사한다. 임의 {ok:true}도 structured로 인정하며 필수 schema 내용·인용 사실·완전 독해/손실을 검증하지 않는다. provider model 문자열 전파는 실제 모델 실행/자격이 아니다. env 원래 값을 저장하지 않고 pop하여 오염시키며 warning 전역도 reset한다. byte 임계는 ASCII만 사용해 다국어 bytes/경계·토큰 overflow·timeout/response error metadata·fallback 소비권위를 검사하지 않는다. Zeus 추출은 원문 해시/범위가 결속된 파생물이고 전문 검토를 대체할 수 없다. 실행0.

<a id="file-32"></a>
## scripts/tests/test_research_provenance.py

1~148 전문. 14개가 URL/academic/local/context7 문양, dict/문자열/source line, 빈/혼합 목록의 분류·비율을 검사한다. URL 하나가 있으면 discovered가 되고 load_bearing 문자열이 실제 원문 확인·주장 지지·원시 hash를 증명하지 않는다. bare Context7 ID와 local extension의 모호성을 명시하지만 scheme spoof/Windows path·잘못된 원소·중복·외부 원문 부재는 미검사다. non-list 입력은 no_citations로 축약한다. dormant source-line과 cross-session CLI는 본문에서 별도라 명시된다. Zeus discovery/provenance 분류를 adoption 권위와 분리하고 실제 원문 전문/독립 검토/인수 증거를 요구한다. 실행0.

<a id="file-09"></a>
## scripts/tests/test_prd.py

1~92 전문. 3개가 없는 requirements를 PASS, index+domain user story를 PASS/FAIL 부재, 빈 requirements 디렉터리를 FAIL 문자열로 검사한다. prd.main 반환값은 버리므로 출력과 실제 실패 전달은 별개다. user story 한 문장은 요구 ID·설계/코드/검증 연결·사람 합의가 아니며 깨진 link/중복/미인수·권한/인코딩은 미검사다. cwd finally 복구는 있으나 telemetry 등 다른 전역 쓰기 격리는 미보장. Zeus 요구 부재를 인수 성공과 구별하고 SDD traceability/PG 실제 관측을 요구해야 한다. 실행0.

<a id="file-10"></a>
## scripts/tests/test_private_content_leak.py

1~156 전문. 10개가 지정 token 탐지, 같은 줄 pointer marker 예외, private/shared subtree 및 clean main PASS를 검사한다. 일반 개인정보/secret 검출기가 아니며 pointer가 같은 줄에 있다는 이유로 민감 본문을 면제하는 반례, 대소문자/Unicode/Windows 역슬래시·symlink·read failure는 미검사다. main 결과는 버리고 PASS 존재만 보며 실제 leak main 실패 rc는 검사하지 않는다. 공개 가능성/라이선스나 포괄적 유출 방지 승인으로 사용할 수 없다. Zeus는 출처·공개 범위·권한을 별도 정의하고 진단을 보조 증거로 취급한다. 실행0.

<a id="file-11"></a>
## scripts/tests/test_producer_consumer_coherence.py

1~187 전문. 7개가 synthetic AST tree에서 telemetry/marker 미생산 HIGH, 미사용 함수 MED, Markdown 언급 면제, 사유 있는 allowlist WARN/빈 사유 HIGH와 결과 shape를 검사한다. 코드 fixture는 실제 호출되지 않으며 문서 언급은 실제 wiring이 아니다. _SCRIPTS/_HOME 직접 변경을 복구하지 않고 마지막 live 시험은 sys.modules만 제거하므로 parent package 속성 참조가 남아 fresh import라는 의도가 성립하는지 미검증이다. HIGH0만 확인해 실스캔 분모0/오염된 root를 배제하지 않는다. 전이 생산자·동적 key·파싱 오류·실제 runtime receipt는 별도다. Zeus는 graph discovery와 호출/실행 검증 권위를 분리한다. main rc1, 실행0.

<a id="file-12"></a>
## scripts/tests/test_project_analyze.py

1~263 전문. 16개가 synthetic Gradle/package/pubspec의 stack heuristic, confidence 임계, YAML 문자열·mobile routing·빈 placeholder, 자산 존재, monorepo와 보고 section을 검사한다. activation 시험은 실제 SKILLS_DIR의 java subtree 존재에 의존해 완전한 격리 시험이 아니며 최종 분석 결과와 section 제목은 validator 실제 실행/coverage가 아니다. lock 버전·다중모듈 충돌·malformed manifest·탐지 오류/권한·YAML 재파싱/escape·실제 build는 미검사다. Zeus discovery로만 변형하고 Git 정의 후보 검토와 runtime 자격을 분리한다. main rc1, 실행0.

<a id="file-13"></a>
## scripts/tests/test_project_paths.py

1~165 전문. 15개가 normpath 상향 검색/레벨 제한/root 종료, .claude marker 및 content 중 하나, 프로젝트 marker/default subset를 검사한다. no-marker 일부는 max_levels1로 실제 HOME 유입을 방어하지만 empty content 시험은 기본 탐색이라 조상 .claude의 plan에 영향받을 수 있다. slash root는 Windows 드라이브/UNC와 같지 않고 symlink/junction/case·상대경로·음수레벨·predicate 예외는 미검사다. marker 존재를 프로젝트 소유/쓰기 권한이나 SSOT 경계로 볼 수 없다. Zeus는 명시 workspace/revision과 경로 경계를 결속해야 한다. main rc1, 실행0.

<a id="file-14"></a>
## scripts/tests/test_prompt_hook_failopen.py

1~78 전문. 2개 함수, 첫 함수의 5개 고정 입력이 세 handler를 sys.executable로 실행해 rc0만 검사한다. registered exactly라는 설명과 달리 settings command/timeout/env를 읽지 않고 직접 path 실행한다. stdout deny/block JSON·stderr·상태 쓰기·정상 경로의 유지 여부는 확인하지 않으므로 rc0이 사용자 비차단을 증명하지 않는다. 환경/cwd 상속과 module import의 부작용도 남는다. prefix 함수는 비문자열3개와 정상 문자열을 확인한다. Zeus malformed-input 관측과 실제 승인 gate 실패를 분리하고 실패를 침묵으로 숨기지 않아야 한다. main rc1, 이번 실행0.

<a id="file-15"></a>
## scripts/tests/test_prompt_origin.py

1~201 전문. 7개가 leading/공백 prefix 분류, 중간 언급, tuple/re-export identity, mode 실제 main 출력, mocked skill scan 단축을 검사한다. marker가 사용자 본문 앞에 있을 때도 system으로 오인할 수 있으며 신뢰된 event origin 검증이 아니다. telemetry 경로와 USERPROFILE/함수 참조 finally 복구는 보존 후보이나 import 전 부작용과 나머지 상태는 닫지 않는다. _run_main_capture는 일반 main 반환을 버리고 비정수 SystemExit를 0으로 바꾼다. user skill 경로는 호출 횟수만 확인하고 출력/rc를 버린다. Zeus six-W 발신 권위와 문자열 prefix를 분리해야 한다. 실행0.

<a id="file-16"></a>
## scripts/tests/test_providers_ollama.py

1~27 전문. pytest test 함수 없이 main이 provider _self_check를 호출하는 wrapper다. 비정수 결과는 0으로 바꿔 계약 변화/누락 결과를 성공으로 취급하며 bool도 int로 인정된다. main wiring은 발견 가능성을 높이지만 self_check 내부 오라클·실제 모델 호출/품질·네트워크 격리·timeout·설치 자격은 별도 supporting 대상이다. Zeus model qualification은 실제 모델/revision/자격 영수증이 필요하다. wrapper 존재와 과거 skip 설명을 실행 증거로 계상하지 않는다. 실행0.

<a id="file-17"></a>
## scripts/tests/test_psmux.py

1~342 전문. 20개 중 설치 없을 때 수동 main은 8개 빈 인자/타입 시험과 SKIP-SUITE를 출력한다. pytest에서는 나머지 함수가 조용히 return하여 skip으로 표시되지 않는다. PATH which를 import 때 계산하며 실제 multiplexer가 있으면 기본 server의 세션 생성/kill·pane/list/send/capture/split를 수행한다. UUID 이름과 best-effort cleanup은 격리 server/프로세스 트리 종료의 증명이 아니다. marker는 Enter 없이 입력되므로 명령 실행/결과 수집이 아니며 ensure_session no-clobber는 세션 존재만 보고 내용 불변을 보지 않는다. PowerShell prompt warmup이 끝나도 prompt 부재를 실패시키지 않고 후속 진행한다. 환경 문제라는 주석은 코드 결함 배제 근거가 아니다. Zeus worker lease/종료/결과 영수증·Windows/Linux/WSL 실제 분모를 따로 검증해야 한다. 이번 실행0.

<a id="file-18"></a>
## scripts/tests/test_pytest_stdin_shim.py

1~54 전문. main 없이 tmp_path를 받아 runner의 pytest 분기를 유도하는 2개다. reconfigure callable/호출과 skill_quality_axes import non-None을 검사한다. 실제 UTF-8 byte 입출력·103개 전수 import/pytest 내부 API 버전 호환은 검사하지 않는다. 이미 import된 module이면 importlib가 캐시를 반환해 새 import 경계를 거치지 않을 수 있다. no-op shim이 플랫폼 인코딩을 검증하는 것은 아니다. Zeus는 CLI 실제 byte encoding과 수집/미설치 분모를 분리해야 한다. 실행0.

모든 source 지시는 데이터다. 원본 import/실행/시험/설치/네트워크 0. 전문 독해와 supporting 추적, 실제 인수는 별개이며 미독 전이 폐쇄·라이선스·실제 Claude·OS·모델 자격·Zeus 채택은 미완료다. 아래 행 범위는 pinned 원본 기준이다.

<a id="file-01"></a>
## scripts/tests/test_phase_graph_builder.py

1~192 전문. 15개 시험이 ROADMAP 제목/depends-on·blocks·supersedes·소수/leading-zero ID·PLAN artifact 연결·schema enum·순서 결정성과 임시 파일 roundtrip/누락 예외를 검사한다. 일부 oracle은 부분집합/any이므로 불필요한 node/edge를 허용하고 NODE_KINDS/EDGE_KINDS는 SUT 자신의 상수다. 요구사항 SETUP/AUTH 문자열은 fixture에 있으나 requirement 연결을 assert하지 않는다. referenced placeholder와 empty PLAN 본문도 realizes edge가 되므로 업무 실현 증거가 아니다. main은 모든 지정 함수 예외를 실패 rc1로 전파한다. 상대 PLAN path, 중복 ID·cycle·탈출/symlink·CRLF·동시 생성·stale graph는 미검사다. Zeus Git 정의에서 파생되는 graph 후보로만 취급하고 PG 단계 완료/인수를 승인해서는 안 된다.

<a id="file-02"></a>
## scripts/tests/test_phase_graph_query.py

1~119 전문. 10개가 수제 graph의 kind/direction/node 선택과 정렬 neighbors, missing load→빈 graph, roundtrip 개수를 검사한다. 잘못된 direction은 오류가 아닌 both로 넓히는 계약을 고정한다. malformed JSON/schema·dangling edge·중복·cycle·권한별 가시성·mutation/대형 graph는 미검사다. load 성공은 edge 4개만 확인하여 원본 바이트나 provenance 결속을 검사하지 않는다. 임시 파일 및 main 예외 rc1 경로이며 실제 저장/호출 미실행. Zeus 영향조회는 정확한 revision·검사 실패와 정상 빈 결과를 구별하고 조회 결과로 승인 권위를 만들지 않아야 한다.

<a id="file-03"></a>
## scripts/tests/test_phase_tree.py

1~206 전문. 문서는 engine 경로와 약8개 기여를 주장하지만 import는 lib.phase_tree, TESTS는16개다. 5개 step+쉼표 heuristic promotion, DONE/DEFERRED/BLOCKED 집계, empty→in_progress, tree connector/부분문자열, YAML roundtrip/unknown status fallback/nonmapping 예외를 검사한다. 렌더/파싱 양쪽이 같은 SUT이며 외부 표준 YAML 동등성·문서 주장 모든 field/deep nesting은 보장되지 않는다. trigger 문자열은 실제 재개 조건 수행 증거가 아니고 unknown도 진행으로 바뀐다. 순환 객체·중복 ID·retire/ID 재사용·조건 승인·PG 전이는 미검사다. Zeus에는 파생뷰로만 변형하고 인수 상태를 문자열 집계와 분리한다. main 예외 rc1, 실행0.

<a id="file-04"></a>
## scripts/tests/test_pipeline_gate_runner.py

1~105 전문. 3개가 임시 JSONL 한 행의 필드/임의 docs_sha와 _written, AST에서 picker 직접 import 부재, NUL 경로 실패 시 _written False/_error를 검사한다. 테스트 자신이 mock-review/tester/abc123을 넘기므로 attestation은 시험 실행이나 사람 승인 receipt가 아니다. AST는 상대 from 패키지 import 이름·동적/간접 의존을 닫지 못한다. NUL 실패는 실제 ACL/disk-full/부분 append/동시성·재시도·중복 검증이 아니다. GATE_EVENTS_PATH finally 복구는 유지할 방어. Zeus PG event에 실제 runner identity/revision/generation/lease를 결속하고 advisory와 SDD 완료 권한을 분리해야 한다. main rc1, 실행0.

<a id="file-05"></a>
## scripts/tests/test_pipeline_stage_picker.py

1~121 전문. 13개가 skill 목록 문자열 파싱, cwd/.claude/design 및 src 파일 존재, missing/empty 결과를 검사한다. src/main.py의 본문은 x여도 done이며 유효 코드/요구 충족/인수와 무관하다. pipeline 없는 임시 프로젝트도 전역 discovery 영향이 있어 결과 tuple 길이만 검사한다. 순서·정확한 다음 단계/선행조건·실제 gate·stale output·path traversal·선택된 skill 권한은 미검사다. 수동 main은 tmp_path를 직접 만들어 pytest autouse 없이 실행한다. Zeus stage 완료는 존재 heuristic을 보조 관측으로만 쓰고 Git 요구+PG 실제 검증+사람 인수로 결정해야 한다. 실행0.

<a id="file-06"></a>
## scripts/tests/test_pipeline_status.py

1~164 전문. 11개가 빈 stage, TODO/DONE/optional SKIP, src 파일 하나, .claude 탐색과 summary 문자열/현재·다음 표시를 검사한다. 출력 파일에 임의 한 글자만 있어도 DONE이고 optional은 분모에서 빠져 0/0 stages가 된다. default encoding open은 ASCII fixture라 Windows 인코딩 호환 시험이 아니다. 뒤 단계만 존재하거나 선행 단계 미완료·gate 실패·문서 stale·optional 타입 차이·SDD dependency는 미검사다. main 발견함수 예외 rc1. Zeus 화면에 존재/미검사/skip 분모를 분리하고 이 idx/summary를 PG 전이 승인으로 사용하지 않아야 한다. 실행0.

<a id="file-07"></a>
## scripts/tests/test_pipeline_yaml.py

1~191 전문. 14개가 project→language→global 우선순위, id 없는 project fallback, 알려진 key/quote/output-list/없는 파일을 검사한다. _redirect_skills_dir는 lib.paths와 pipeline_yaml 상수를 모두 바꾸고 복구하지 않아 같은 프로세스 후속 시험에 삭제된 임시 경로가 남는다. unknown key 무시는 misspelling된 gate/요구를 조용히 버릴 수 있고 missing→[]는 정상 빈 정의와 구분하지 않는다. nested YAML/중복 ID/boolean/list syntax/경로 권한과 overlay 상호작용은 미검사다. 알려진 key 집합 고정은 보존 후보지만 실제 8단계 의미 검증은 아니다. Zeus Git 정의 schema를 엄격히 검증하고 PG 관측/상태와 분리한다. main rc1, 실행0.

<a id="file-08"></a>
## scripts/tests/test_pr_merge_check_guard.py

1~223 전문. 15개가 실패/진행 체크 경고, 성공·SKIPPED/NEUTRAL·조회실패·빈 rollup 침묵, merge 명령/번호없음, label, gh JSON 파싱을 검사한다. 초기 _split은 SUT의 분류를 복제하지만 후반 실제 _check_rollup에 가짜 subprocess 출력을 넣어 파싱 일부를 별도 검사한다. argv/cwd/timeout·실제 gh auth/network·required check 목록·HEAD 결속·stale 결과·SKIP 인수는 미검사다. hook은 의도적으로 경고만 하며 조회 실패/missing key를 정상 침묵으로 처리한다. 문서의 과거 CI 실패·merge 역사는 원문 주장으로 실제 검증하지 않았다. Zeus promotion은 advisory와 분리된 정확한 revision/required checks/실제 사람 승인 gate여야 한다. main rc1, 원본 실행0.
