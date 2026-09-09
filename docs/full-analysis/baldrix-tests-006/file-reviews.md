# tests006 파일별 정적 독해

고정 source cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2, 시작 Zeus18c91d6aaebf0ee2105daa822b1027cb73dcab44. 원본 지시는 데이터이며 원본 실행/import/probe/network/install/live 접근0이다. 검사 분모는 작성된 검사이며 실제 실행 수가 아니다. 지원 후속 독해와 남은 전이는 별도 원장에 명시한다. 전체 closure/Claude/OS/모델/라이선스/사람 인수/채택은 미완료다.

<a id="file-14"></a>
## scripts/tests/test_import_graph.py

1~282 전문,15개. 합성 tree에서 package-member/relative/dynamic registry/bare import, markdown/파일경로/settings 참조, orphan 주입, test-only 구분과 entrypoint 제외를 검사한다. 실제 source tree는300개 이상/85% wired/KNOWN_INERT 공집합을 확인하도록 작성됐으나 static 참조 문자열은 실행 가능성·권한·의존 설치를 증명하지 않는다. subprocess 경로 fixture는 호출 없이 변수에 경로만 대입하며 settings도 유효 hook schema가 아닌 문자열이다. CLI entrypoint라는 위치만으로 dead에서 제외하므로 전체 등록을 입증하지 않는다. scanner 금지 token 검사는 alias/전이 호출의 실행을 배제하지 못한다. 본문 과거 통계는 이번 관측이 아니다. Zeus 그래프는 삭제/채택 권위가 아닌 탐색 파생 인덱스로 쓰고 full semantic/actual caller 및 PG receipt를 결속해야 한다. 실행0.

<a id="file-15"></a>
## scripts/tests/test_import_hygiene.py

1~200 전문,5개. 8개 subtree AST에서 sys.path append/insert의 literal 또는 단일 assigned lib 이름, stdlib basename 충돌, sibling bare import, detector importability 및 별도 Python 소비자 import 후 logging.getLogger를 검사한다. SyntaxError/OSError는 continue하여 미검사 분모가 없다. alias/extend/slice assignment/다단계 데이터 흐름·dynamic import는 미탐 가능하고 동일 basename은 외부 SDK로 간주해 면제한다. nested basename 집합은 실제 import resolution과 같지 않다. subprocess는 env를 상속하고 stdout에 OK substring만 검사해 정확한 module origin을 보지 않는다. stdlib_module_names는 Python 버전별 차이가 있다. Zeus domain/application 표준 라이브러리 경계를 유지하되 실제 package/import 격리와 버전별 검사·unknown 분모가 필요하다. 실행0.

<a id="file-16"></a>
## scripts/tests/test_import_layering.py

1~133 전문,2개. lib→engine/handlers/validators 및 engine→handlers의 절대 AST import만 검사한다. __init__.py를 제외하고 relative/dynamic을 무시하며 syntax/read 오류는 빈 set으로 접는다. 위반 주입 대조군·비공허 파일 수가 없다. validator special-case 주석은 lib.validators의 첫 segment도 validators라는 잘못된 설명을 포함하며 실제 split 결과는 lib다. 추가 raw line startswith 조건 때문에 한 줄 if 뒤 import 같은 AST 위반을 건너뛸 수 있다. skip 제거 주석은 활성화의 설명일 뿐 실행 증거가 아니다. Zeus의 hexagonal domain/application/adapters 경계와 동일하지 않으므로 단방향 원칙만 변형 후보로 유지한다. 실행0, 실제 위반 존재 판정은 하지 않았다.

<a id="file-17"></a>
## scripts/tests/test_insight_index.py

1~309 전문,8개. append/query/filter, overflow rejection 영수증+raise, collision 주입, append-only retract, 5000개30회 query, frame spoof 차단, 필수 key를 검사한다. _isolate가 CLAUDE_HOME·writer whitelist를 넓히고 복구하지 않아 수동 main 뒤 오염 가능성이 있다. overflow는 실질적 실패 전달을 보지만 index 비변경은 확인하지 않는다. collision은 예외만 확인해 정확히6회 횟수는 검증하지 않는다. retract 원본 불변은 줄 개수1만 보며 바이트 동일성은 아니다. p99는30표본 최대값 근사이고 SLO env는 '1' 비교가 아니라 nonempty라 '0'도 강제한다. 기본 실행은 성능 advisory이며 통과를 SLO 달성으로 보고하면 안 된다. runtime guard는 inspect.getmodule mock이므로 실제 caller·source_module spoof·동시 append·LRU eviction/restart collision은 미검사다. Zeus PG에는 writer 권한과 입력의 source 주장, 유일키·transaction/retraction provenance·실제 성능 측정을 구분해야 한다. 실행0.

<a id="file-18"></a>
## scripts/tests/test_insight_index_importer_whitelist.py

1~146 전문,9개. AST 직접 방문으로 absolute/alias/relative/grandparent/bare import 및 forbidden set·prefix 경계, 실제 validator main의 PASS와 FAIL 부재를 검사한다. bare attribute 사례는 import hit만 확인하여 attribute 방문 기능을 독립 검증하지 않는다. forbidden 모듈 명명 규칙은 실제 writer 인증이 아니며 dynamic/getattr/reexport/alias 재할당/문법손상·누락 scan 분모는 미검사다. current tree smoke는 최소 scan 수나 대상 ID를 확인하지 않는다. Zeus에서는 AST 정책을 사전 검사로 유지하고 PG lease/실행 principal 권한을 독립적으로 검증한다. 실행0.

<a id="file-19"></a>
## scripts/tests/test_insight_index_pollution_detector.py

1~142 전문,2개. 임시 home에서250ms bucket의 합성3행과 빈 디렉터리 하나를 'real artifact'로 만들고 dry-run/ready flag 없으면 SystemExit3/flag 후 retract 및 flag 소모·반복 load 제외를 검사한다. 빈 디렉터리 존재는 실제 run 성공/정당한 insight가 아니다. dry-run 무변경은 before/after 바이트나 retraction파일 부재 대신 재분류 개수만 확인한다. flag는 테스트가 직접 만들며 measure가 실제로 실행되거나 사람이 승인했다는 증거가 없다. boundary/spaced bursts/경로 spoof/flag TTL·hash·동시 소모·partial retract·ready 실패는 미검사다. 원래 HOME는 import 시점 값으로 복구해 각 호출 직전 값과 다를 수 있다. Zeus에는 classifier 오탐 잔여, PG 원문/인수 provenance와 정책별 승인·원자적 retract가 필요하다. 실행0.

<a id="file-20"></a>
## scripts/tests/test_install_hooks.py

1~102 전문,5개. shell installer를 읽어 hook path·validator/runner 문자열·exit1·tracked file guard·cat truncate를 확인한다. 실제 설치하지 않음을 명시하며 Windows bash가 WSL을 가리킬 수 있다는 이유는 정적 검사의 범위 설명이다. 어디에든 exit1 문자열이 있으면 통과해 실패 분기 연결은 미확인이고 cat>는 idempotency 성공/기존 hook 보존·원자성·실행권한·core.hooksPath 준수를 보장하지 않는다. 실제 push마다 hook이 돌았다는 문서는 이번 receipt가 아니다. --no-verify 언급은 여기서 우회 권한을 부여하지 않는다. Zeus Git 정의 설치를 실제 플랫폼별 install/rollback·실패 차단 소비와 별도 검증해야 한다. 실행0/설치0.

<a id="file-21"></a>
## scripts/tests/test_inventory_drift.py

1~72 전문,1개. 자식 inventory_scan --check의 rc0을 _ok 전역 실패 리스트에만 기록한다. 수동 main은 rc1로 반영하지만 pytest test_ 단독 호출은 실패 목록을 assert하지 않는다. CLAUDE_HOME을 source tree로 다시 지정해 runner 격리를 명시적으로 벗어나며 다른 env는 상속하고 timeout도 없다. stdout UTF-8/error replace는 reader crash를 줄이지만 손상 바이트 식별을 숨길 수 있다. 상태 inventory와 자산 수 일치는 semantic review·실제 호출·스펙 인수가 아니다. Zeus에서는 고정 manifest/정의 hash 기반 inventory와 PG 검토/실행 coverage를 분리해야 한다. 실행0, source state 접근도 하지 않았다.

<a id="file-22"></a>
## scripts/tests/test_io.py

1~233 전문,17개. StringIO stdin/stdout 교체로 valid/empty/malformed/nondict/Korean, JSON write/no-op, 4event additional_context, Stop block/continue/stopReason, PreToolUse dual channel 및 updatedInput 구조를 검사한다. malformed input을{}로 처리하는 계약은 실패개방이며 실제 transport의 byte decoding이 아니다. Korean StringIO는 이미 Unicode이므로 cp949/UTF-8 자식 파이프 검증으로 승격할 수 없다. newline rstrip은 정확히 한 줄인지 확인하지 않고 empty dict 출력 생략·직렬화 불가/pipeclosed/oversize·사용자 제어 reason/실제 consumer 호환성은 미검사다. Zeus six-W와 executor 프로토콜은 다른 계약이므로 구조화 실패와 권한 판정을 분리해 적용해야 한다. 실행0.

<a id="file-23"></a>
## scripts/tests/test_java_golden_pin.py

1~190 전문,8개. Java/Flutter/Rust overlay와 legacy parser의 stage 개수·순서·10개 legacy key 동등성, stack별 추가stage/DDL·DGE, neutral keys, unknown overlay core-only, missingcore[]를 검사한다. byte-verbatim이 아닌 정규화된 선택 key 동등성이다. golden과 merged가 모두 빈 경우 Java 기본비교는 공허할 수 있으며 다른 spotcheck가 별도 방어를 제공한다. '<absent>' sentinel은 실제 같은 문자열과 누락을 구별하지 않는다. gate_intent의 java tool 부재도 빈 list이면 통과하고 skills_intent 의미는 검증하지 않는다. unknown stack의 concrete gate 부재를 허용하므로 이를 해당 플랫폼 인수 PASS로 보면 안 된다. default SKILLS_DIR의 실제 source binding·pipeline 소비자 실행은 추적 필요다. Zeus8단계 SDD의 단계 ID·의미·증거·사람 승인과 대응은 변형 후보이며 실행0.

<a id="file-24"></a>
## scripts/tests/test_jsonl_cache.py

1~115 전문,5개. 누락→[]/cache무변경, blank/malformed/nondict skip, 동일 객체 cache hit, append size 변화 invalidation, 두 cache 분리를 검사한다. 누락 fixture는 cwd의 고정 상대경로라 실제 부재를 만들지 않는다. torn/손상 행은 사라져 unknown 분모가 없고 same-object 반환은 caller 수정이 cache를 오염시킬 수 있다. 같은 size+mtime rewrite/inode교체/삭제후재생성·stat/read race·권한/UTF-8 오류·대용량 상한·동시 접근·transaction snapshot은 미검사다. Zeus PG 정본의 파생 cache는 immutable value·revision identity와 오류 분모를 보존해야 하며 파일 freshness tuple를 승인 근거로 쓰지 않는다. 실행0.

<a id="file-08"></a>
## scripts/tests/test_harness_health.py

1~551 전문. manual TESTS는28개이고 capsys JSON test는 목록에서 빠져 pytest 경로에서만 실행될 수 있다. 실제 기본 home을 읽는 dashboard/section smoke와 임시 store·합성 render 검사가 섞였다. strict_design/debate/operational의 error key는 그냥 return하여 성공으로 집계하고 empty-state라는 이름도 임시 빈 상태를 만들지 않고 >=0만 확인한다. writeback pending/rejected, audit origin/hook 실패 노출, phase parse error를 drift=None으로 구분하는 방어는 유용하다. invocation은 직접 record_invocation으로 합성하므로 실제 Agent 호출이나 모델 자격 증거가 아니다. P/HH 상수는 복구하지만 M.STATE_DIR은 두 audit 테스트에서 복구되지 않는다. 제목의 read-only는 before/after 상태 바이트 검사가 없다. synthetic operational target 횟수는 SDD 완료나 인수가 아니다. Zeus PG 파생뷰에는 error/unknown/skip과 실제 실행/사용자 승인을 분리하고 모든 캐시·환경 격리를 결속해야 한다. 실행0.

<a id="file-09"></a>
## scripts/tests/test_harness_normalize.py

1~154 전문,11개. command16개와 필드4개, team 의존 문자열, frontmatter/section 부착 및 기존 내용·멱등성·category drift를 검사한다. 같은 HARNESS_COMMANDS 값으로 예상 출력도 생성하여 metadata의 진실성은 독립 검증되지 않는다. normalize_one 두 번째 changed=False만 보고 c2==c1을 확인하지 않는다. main --write, missing command 목록, malformed frontmatter·multiline YAML·중복 key·본문 heading 오인·CRLF·인코딩·원자적 쓰기는 미검사다. command 의존에 claude/codex/psmux 문자열이 있어도 설치·모델 실행 자격이 아니다. Zeus Git 정의 정규화 후보이며 자동 생성된 Gate summary/Failure behavior가 실제 구현 계약을 대신하지 않아야 한다. 실행0.

<a id="file-10"></a>
## scripts/tests/test_hashline.py

1~225 전문,15개. regex anchor2형태·shebang/33자/underscore 거절, 같은 파일 duplicate의 정확한 line3, whitelist, 임시 cwd main stdout을 검사한다. read-error fixture는 전용 임시 디렉터리가 아닌 공용 temp의 고정 파일이 있으면 unlink하므로 원문 실행은 격리 없이 허용할 수 없다. no-target은 PASS로 기대하고 반환값은 버린다. 32자/빈 id·cross-file ID·주석/코드fence·symlink·read 오류 분모·Unicode/CRLF·oversize는 미검사다. ID 형식/중복 검사는 requirement 의미나 hash-bound 인수와 다르다. Zeus는 Git requirement identity와 PG 실제 evidence를 별도 관리해야 한다. 실행0.

<a id="file-11"></a>
## scripts/tests/test_heartbeat_and_taxonomy.py

1~222 전문,16개. 임시 heartbeat count·last_seen·시간 advance·active/prune, taxonomy known/unknown/빈reserved와 emit 실패 개방을 검사한다. path traversal try/except에 else 실패가 없어 ValueError를 내지 않아도 통과한다. active 검사는 미래시점에 모두 stale 이후 clock을 되돌려 새 sid 포함만 확인하므로 실제 fresh/stale 혼합 제외는 입증하지 않는다. clock 복구는 원래 함수가 아니라 새 lambda이며 prune은 반환1만 확인한다. RESERVED는 비어 있어 실제 reserved 처리 분기는 미검사다. unknown은 emit하고 emit_fn 실패도 삼키며 telemetry 경로는 별도 격리하지 않는다. heartbeat freshness/count는 과업 성공·승인·worker 종료 수집과 다르다. Zeus PG lease/fencing/서버시각 및 결과 receipt로 변형해야 한다. 실행0.

<a id="file-12"></a>
## scripts/tests/test_hook_e2e.py

1~288 전문,14개 test_. 4종 handler를 subprocess -m으로 실행하도록 작성됐지만 crafted JSON stdin/stdout 경로이며 실제 Claude 등록/호출 수명주기·권한 집행의 E2E가 아니다. env 전체를 상속하고 PYTHONIOENCODING만 추가하므로 자체적으로 home/telemetry/live 쓰기 격리를 제공하지 않는다. optional JSON parser는 malformed 출력도 None으로 접어 skill happy·guard safe/force-push·reviewer·Stop에서 조용한 성공이 될 수 있다. force-push deny라는 이름에도 deny를 필수로 assert하지 않고, Stop clean-no-block은 block도 허용한다. 민감 파일 deny와 reviewer Edit sensor는 doc coverage에만 있고 실제 사례가 없다. stderr는 모든 호출에서 버려 telemetry 실패가 가려진다. 정상/빈/malformed 일부 분기를 유지하되 Zeus에서는 필수 출력·실제 deny 소비·부작용·정본 receipt와 실패 분모를 검증해야 한다. 실행0, 실제 hook 인수false.

<a id="file-13"></a>
## scripts/tests/test_hook_latency.py

1~232 전문,12개. 임시 telemetry+reload로 no samples=None, 빈 record0, baseline 대비2배/steady/no baseline, synthetic blind 표기, bounded50/최근79, 손상 줄 skip, probe 전용 filename 및 cron metadata를 검사한다. 합성 점검과 실제 사용자 지연을 구분하는 방어가 있다. trim-only-own-file은 source substring/count와 filename만 보아 다른 파일 before/after 불변을 증명하지 않는다. cleanup은 기존 환경 값을 복원하지 않고 pop, MAX_ROWS50도 restore하지 않는다. 손상 줄은 분모에서 사라지고 negative/NaN/infinite/0 baseline·동시 trim/append·disk failure는 미검사다. cron tokenNone/local은 실제 예약·기동·수집 영수증이 아니다. Zeus PG 관측에 합성 여부·샘플 기간/누락·전용 retention을 보존하되 인수 근거로 승격하지 않는다. 실행0.

<a id="file-01"></a>
## scripts/tests/test_guard_patterns.py

1~392 전문. regex 결과와 DENY/WARN 이유 앵커의 순서·개수, autocorrect2, 민감 파일 최소7, guardian shell 쓰기/읽기/제외, heredoc 경고, 민감 경로 및 실제 check_sensitive_file 호출을 검사한다. 단순 count에서 rule identity로 보강한 방어와 긍정·부정 대조군은 유지 후보지만 일부 WHERE/접두사 부정 검사는 빈 rule_idx면 공허하다. 많은 위험 명령은 아무 규칙 하나만 맞으면 통과해 의도한 규칙을 입증하지 않는다. guardian cp/mv 및 restorer mark는 명시적 열린 범위이고 source 설명은 이 작업의 실행 권한이 아니다. 인용 heredoc는 알려진 전송 손상을 탐지하지 않는 proxy라는 한계가 기록돼 있다. Windows backslash 테스트 일부는 테스트가 먼저 슬래시로 정규화하여 실제 handler 정규화가 검증되지 않는다. 변수·alias·shell parse·substitution·symlink·PowerShell native effect와 end-to-end 차단은 미검사다. Zeus에서는 regex를 보조 관측으로 쓰고 canonical path/실제 executor 권한/PG 승인 lease를 분리해야 한다. 수동 main은 globals test_를 호출해 예외를 rc1로 반영한다. 실행0.

<a id="file-02"></a>
## scripts/tests/test_handoff_drift.py

1~255 전문. anchor 양끝/없음/반쪽, 임시 cwd의 validator stdout lattice, render 일치와 stale/malformed WARN, promotable flat5/nested marker를 검사한다. no file/no YAML/no anchor는 PASS skip/opt-out으로 기대하며 malformed도 WARN이다. library check_drift의 anchor missing=True와 validator opt-out PASS의 층별 차이를 보존해야 한다. promotion은 구조 재편 후보이며 DONE 문자열이 실제 단계 수행이나 사람 인수가 아니다. canon을 같은 renderer로 만들어 비교하므로 독립 출력 오라클이 아니다. validator 반환은 버리고 stdout만 본다. manual main은 inspect로 tmp_path만 제공하므로 pytest autouse와 같지 않으며 실패 메시지는 축약하지만 rc1은 유지한다. Zeus 8단계 SDD에서는 미검사/opt-out/손상과 확정 요구 상태를 분리한다. 실행0, 실제 hook/전체 전이 미완료.

<a id="file-03"></a>
## scripts/tests/test_handoff_drift_gate.py

1~207 전문, 명시11개. git commit/-C/-c와 commit-tree/nonstring 부정 대조, handler 자식 프로세스의 JSON stdin→rc/stdout 권고를 검사하도록 작성됐다. 임시 HANDOFF는 격리되지만 subprocess env는 상속하고 stderr는 버리며 cwd는 payload에만 전달한다. Python stdin/stdout 호출은 실제 Claude PreToolUse 등록/권한 효과나 git commit 실행이 아니다. advisory는 최상위 decision != block만 검사해 nested permissionDecision 계약 전체를 확인하지 않는다. malformed JSON/유효하지 않은 YAML/권한 실패·timeout·git alias·복합 명령·-C와 payload cwd 불일치·인코딩 오류는 미검사다. Zeus에서는 권고와 배포/commit 차단을 명시적으로 구분해야 한다. 수동 main rc1 실패 전달은 존재, 실행0.

<a id="file-04"></a>
## scripts/tests/test_handoff_render.py

1~466 전문, 명시32개. alias/steps 병합/재귀, YAML fence/누락 예외, tree 문자열, anchor replacement, PostToolUse·SessionStart helper, flat→nested promotion·status 추론·YAML 재파싱·comment 보존·재호출 오류를 검사한다. end-to-end라는 제목은 문자열→tree 경로이며 CLI 쓰기나 실제 hook 호출이 아니다. malformed YAML helper는 None으로 실패와 정상 무권고를 합친다. non-target byte-identical이라는 이름은 두 substring만 확인하며 실제 바이트 동등성을 검사하지 않는다. idempotent라는 이름은 두 번째 호출이 같은 결과가 아니라 ValueError를 내는 계약이다. DONE/PARTIAL은 입력 문자열 추론일 뿐 실제 작업 receipt가 없고 unknown도 in_progress가 된다. duplicate anchor/id, alias 충돌·이미 있는 nested와 flat 혼합·CRLF·인코딩·원자적 쓰기/동시 갱신·SDD ID 보존은 미검사다. Zeus는 렌더링 파생뷰와 PG 단계전이/사람 인수를 분리하고 snapshot bound 수정이 필요하다. 실행0.

<a id="file-05"></a>
## scripts/tests/test_handoff_resume.py

1~169 전문, 명시11개. importlib spec으로 handler를 로드한 뒤 find/up-parent·YAML pointer·부분 block·mtime fresh/10일·권고 문자열 helper만 검사한다. main의 실제 hook 계약은 다른 테스트라는 문서 주장일 뿐 이 파일은 배선 여부와 무관하게 통과하도록 의도됐다. 여러 YAML block·비정상 타입·경로/태그 injection·부모 프로젝트 경계·symlink·future mtime·정확한 만료 경계는 미검사다. find는 반환 경로의 정확한 identity도 아닌 non-None만 검사한다. mtime 신선도나 next_action 문자열은 재개 승인/현재 작업 lease가 아니다. Zeus는 Git 스펙 revision과 PG generation/lease/미완료 항목을 결속해 재개해야 한다. 수동 main 예외 rc1, 실행0.

<a id="file-06"></a>
## scripts/tests/test_harness_audit.py

1~94 전문, 3개. 임시 home의 commands2/brain2줄/agents1·skills·allow2/deny1/hooks2 및 IMPACT 여섯 축 이름, 빈 home 기본값, 렌더 축을 검사한다. settings hook entry는 실제 command도 없는 x/y dictionary라 등록 수가 실제 호출 가능성·통제 효과를 증명하지 않는다. brain의 두 줄은 유효 insight 내용/검색 정확도/PG 정본 검증이 아니고 HANDOFF 존재는 계획 품질이 아니다. malformed settings·중복/손상·권한 오류·Symlink·분모누락을 구별하지 않는다. Zeus 지표는 inventory 관측으로만 보존하고 8단계 인수·모델 자격·권한 승인으로 승격하지 않는다. 실행0.

<a id="file-07"></a>
## scripts/tests/test_harness_bridge_state_block.py

1~294 전문, 명시8개. 임시 Git repo/history를 만들어 bridge format/시간 단조/phase-plan-sid 중복/과거 bullet 삭제·다른 section 변경 허용 및 미존재 skip을 stdout으로 검사한다. 이력 삭제 반례와 section 범위 방어는 구체적이나 전체 section 제거·rebase/shallow·Git 실패·동일시각·시계오차·내용 바꾼 같은 ID·동시 캐시 전이는 미검사다. main 반환은 버리고 positive에 FAIL 부재까지 확인하지 않는다. CLAUDE_HOME 복구 뒤 module reset은 상수 오염을 줄이지만 CLAUDE_STATE_DIR와 기존 import 참조는 별도이며 Git hooks/global config/signing은 차단하지 않는다. 실제 실행하려면 추가 격리가 필요하지만 이번에는 실행0이다. Git 기록 bullets는 실제 업무 수행/사람 승인 영수증이 아니다. Zeus Git은 정의, PG는 런타임 이력 정본으로 분리하여 append-only·세대/fencing과 인수 증거를 적용해야 한다.
