# Baldrix tests 005 — 한정 정적 의미 검토

<a id="scope"></a>
## 범위와 증거 경계

`baldrix:scripts/tests:005`의 22개 원문, 196348 bytes를 전문 독해했다. 고정 원본은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, 시작 Zeus HEAD는 `a98f29e3cdc913445b38fcc10f9fd1eb8942ae7f`, partition scope SHA-256은 `4fb3aa75d211c23ff7c41c2fcb7596f903aef8ffd33141a1ab86015f48ac98fa`다. 모든 primary의 기존 path-ledger 상태는 unreviewed였으며 원장 row와 원본 바이트 정체성을 files.json에 보존한다. 이전 보고서의 의미 판단이나 supporting 독해를 재사용하지 않았다. 메타데이터 작성기의 구조만 본인의 이전 작성기에서 재사용했다.

아래 `scripts/…` 및 `skills/…` 경로는 모두 `.runtime/absorption/sources/baldrix/pinned/` 기준이다. supporting-evidence.json은 실제 화면에 표시해 읽은 구간만 기록하며, 검색 hit 및 AST 함수 위치 탐색은 의미 독해 범위로 더하지 않는다. 원본 Git blob, byte 수, 별도 SHA-256, manifest snapshot SHA 존재 여부를 각각 대조한다. 원본 실행·import·probe·모델·네트워크·설치·live 상태·인증정보 접근은 모두 0이다. 차단된 gatewriter ERROR probe는 재시도하거나 우회하지 않았다.

이는 시험 코드의 목적과 실패 판정에 대한 정적 검토다. 아래 검사 개수는 선언된 최상위 test 함수 수이며 실제 실행 수나 통과 수가 아니다. 원문의 과거 실측·PASS·E2E·완료 표현은 재현된 현재 사실로 취급하지 않는다. root의 실제 Claude 토론 및 실행 관측은 별도 증거이며 이 원장에 혼입하지 않는다.

<a id="i01"></a>
## 01 — test_evaluator_dispatcher.py

32개 함수가 임시 counter의 phase별 한도, prompt 세 입력, 누출 패턴, 환경 allowlist, fallback 및 JSON 추출을 검사한다. main의 명시 목록이 AssertionError와 기타 예외를 실패로 센다. 상태 helper는 `P.STATE_DIR`를 바꾸고 복구하지 않는다. prompt의 비문자열 거절은 실제 `build_evaluator_prompt`의 위치 인자 계약과 맞는다. fallback은 현재 구현상 순수 결과 생성이며 상태를 쓰지 않는다.

직접 SUT `lib/evaluator_dispatcher.py:141–196,231–269,347–637`에서 counter 검사와 기록은 별도 호출이고, timeout/config/exception fallback은 approved를 생성하지 않는다. 이는 현행 방어다. 허용 환경에는 HOME/USERPROFILE/APPDATA 등이 남고 실제 spawn은 CWD를 지정하지 않는다. Windows batch shim만 shell=True로 분기한다. 테스트는 잘못된 prompt의 pre-spawn 거절까지만 보며 이 OS 실행 분기를 실행하지 않는다. JSON 중 가장 큰 object 선택과 parse-failure sentinel도 판결의 진실성 검증은 아니다. Zeus에는 evaluator 오류를 인수 승인과 분리하고 모델 자격·예산 예약·작업 경계 증거를 별도로 결속할 필요가 있다. counter 하위 잠금, 실제 독립성 및 전체 caller는 미검증이다.

<a id="i02"></a>
## 02 — test_evaluator_dispatcher_selfcheck.py

0개 test 함수인 wrapper이며 main이 embedded `_self_check()`를 호출하고 반환값이 int가 아니면 0으로 바꾼다. 원문이 적은 89 assertions/840 LOC는 실행 분모로 인정하지 않는다. 직접 SUT `lib/evaluator_dispatcher.py:1421–1462,2280–2311`에서 case 누적과 실패 rc1, 성공 rc0 소비는 확인했다. 중간 `1463–2279`의 self-check 전문은 이 범위에서 읽지 않았다. 따라서 wrapper 전문 검토와 내부 검사 의미의 closure는 구별한다. 첫 부분은 default provider pool을 구성하고 mock invoke를 설명하므로 실제 모델 독립 검증이라는 주장도 하지 않는다. Zeus에서는 wrapper의 비정상 반환을 성공으로 정규화하지 않고 선언/발견/실행/실패 분모를 별도 기록할 대상이다.

<a id="i03"></a>
## 03 — test_event_store.py

15개 함수가 JSONL append/replay, gen 최대값, 종류별 조회, 한글 payload, 짧은 payload hash, 손상 중간 줄과 torn tail을 검사한다. `P.STATE_DIR`와 `E.DEBATES_DIR`를 임시 경로로 바꾸고 복구하지 않는다. 중간 손상의 telemetry를 stub으로 확인하는 현재 방어와, EOF 손상을 조용히 건너뛰도록 기대하는 계약을 구분한다. 앞선 손상 시험은 telemetry 자체를 별도 격리하지 않는다.

`lib/event_store.py:1–117` 및 `lib/telemetry_log.py:27–57`에서 constructor가 디렉터리를 만들고 append는 일반 파일 append이며 hash는 payload의 SHA-1 앞 12자리다. replay는 hash를 대조하지 않고 JSON object schema도 보장하지 않는다. `engine/cli.py:20–68`의 show/last-verdict도 constructor를 거쳐 읽기 명령에 디렉터리 생성 가능성이 있다. 시험은 동시 writer, 강제 종료, fsync, 변조 연결, session 경로 경계 및 non-object JSON을 검사하지 않는다. Zeus PG 원장의 트랜잭션·provenance·무결성·미완료 이벤트를 이 JSONL 시험으로 인증할 수 없다.

<a id="i04"></a>
## 04 — test_evidence_fab.py

11개 함수가 malformed/empty envelope의 CLEAN, 파일 존재·부재, 실제 Python 자식의 rc0/1/2, 첫 실패 후 성공, timeout을 검사하도록 작성됐다. 실행된다면 단순 mock만 있는 시험이 아니며 replay가 실제 subprocess와 임시 marker 파일을 사용한다. WARMUP/XTOK 환경은 덮어쓰고 pop하므로 기존 값을 복구하지 않는다. 고정 Windows형 부재 경로의 의미는 OS마다 다르다.

`lib/observers/evidence_fab.py:1–194`는 replay_cmd/cwd를 받아 shell=False subprocess를 실행하지만 자식의 파일·네트워크 부수효과를 제한하지 않는다. 원문의 NO writes/network는 자식까지 포함한 보장이 아니다. timeout/launch 오류도 실패 rc로 바뀌어 두 번 반복되면 fabrication_confirmed가 된다. 이 enum은 재현 불일치 판정이며 고의 조작을 증명하지 않는다. malformed·0개 증거는 CLEAN이므로 별도 schema/필수 증거 분모가 필요하다. `lib/replay/constants.py:1–17`의 값을 RC에서 0으로 바꿔도 detector는 이미 직접 import한 바인딩을 사용하므로 backoff 제거가 성립하지 않는다. `handlers/post_tool/agent_outcome_audit.py:272–296`는 구조 검사 결과와 별개로 D1을 호출한다. Zeus에는 승인된 replay 실행환경, 증거별 시도/오류 기록, 환경 실패와 falsification 구분이 필요하다. 해당 hook의 전체 gating 및 실행은 미검증이다.

<a id="i05"></a>
## 05 — test_example_fleet.py

2개 함수, 직접 `_ok` 7곳이 committed example YAML과 fixture 소스를 읽어 ontology/shared/touches/orphans 및 seam parity를 검사한다. 기대치는 shared wire 4종, ORDER_CREATED touches 3 seams, orphan STOCK_RELEASED 1종, DRIFT 4개·OK 2개·BLOCKED 0개다. 정확한 fixture 전체 의미는 root의 독립 검토 범위이며 여기서는 테스트 전문과 직접 SUT만 읽었다.

`cli/ontology_query.py:43–100` → `cli/seam_scan.py:52–131`는 각 extractor의 enum/message 결과로 집합을 계산한다. BLOCKED seam은 value 연결에서 제외하는 현행 방어가 있다. 서비스 기동·메시지 송수신·결제 처리나 사람 경험은 실행하지 않는다. `_ok`는 예외 없이 전역 FAILS에 쌓이고 main이 소비한다. 직접 pytest가 test 함수를 호출할 때 조건 False만으로 실패하지 않으며 FAILS는 main 시작 시 초기화하지 않는다. Zeus에는 예제 graph와 실제 서비스 인수를 구분하고 runner 독립 실패 오라클을 확보할 대상이다. 삼성 기기 및 Device Farm SDK/Replay는 구현·검증했다고 주장하지 않는다.

<a id="i06"></a>
## 06 — test_exit_contract_coverage.py

8개 함수가 임시 CLI/test 소스 문자열에 문서화된 exit 3/4/5와 literal/EXIT 상수 비교를 넣어 coverage advisory를 검사한다. fixture의 rc/code 변수는 실제 CLI 실행 결과가 아니며 그 문자열을 실행하지 않는다. generic 0/1/2는 분모에서 의도적으로 제외한다.

`validators/exit_contract_coverage.py:45–154`는 CLI docstring의 좁은 패턴과 CLI stem이 포함된 test 전체 텍스트의 정규식을 비교한다. 실제 assert 구문인지, 같은 호출의 rc인지, 코드가 실행되는지 확인하지 않는다. unreadable/SyntaxError CLI는 건너뛰며 대상이 없어도 PASS다. 현재 registry 포함과 blocking 실패는 다른 계약이고 출력은 WARN이다. Zeus에는 문서화 coverage를 실제 command receipt·exit oracle coverage와 별도 지표로 남겨야 한다. 문서 삭제로 분모가 사라지는 문제와 미문서화 exit은 이 시험이 막지 않는다.

<a id="i07"></a>
## 07 — test_external_jury_retry.py

10개 함수가 scripted Fake provider, 임시 breaker, sleep no-op 및 가짜 시간을 사용해 threshold, retry, permanent/transient, circuit, legacy 동등성, 일부 juror 실패 및 TTL을 검사한다. 실제 vendor/model 호출은 없다. permanent 오류의 breaker history success는 작업 결과 성공이 아니라 breaker 해제 회계다. 일부 예상 예외 경로에는 예외 미발생을 명시적으로 실패시키는 else가 없으므로 후속 상태 assert의 범위까지만 오라클로 인정한다.

`engine/external_jury.py:1–272`는 응답한 juror만 투표 분모로 삼고 valid vote가 하나라도 있으면 consensus를 만들 수 있다. configured panel quorum이나 Astra/Sol/Terra 승계 자격을 검사하지 않는다. call_budget_sec는 예약된 미사용 인자이며 max_attempts가 총 wall time을 강제하지 않는다. `engine/dispatch_retry.py:34–70`은 BaseException까지 분류해 retry하므로 취소 전달은 별도 검증 대상이다. threshold config는 하네스 홈의 파일 설정에 의존하며 temp breaker만으로 config 격리는 완결되지 않는다. composite 저장·경합·TTL 전체 본문은 이 범위에서 미독이다.

<a id="i08"></a>
## 08 — test_extractors.py

54개 함수가 합성 Java/SQL/Drift dump/docs와 가짜 extractor로 9개 registry, 출력 경로·일부 문자열·confidence bands·provenance 수·skeleton·collision·rollback을 검사한다. FK 검사는 FOREIGN KEY 또는 user_id의 존재를 허용하고 몇몇 output 검사는 substring 수준이다. 고정 confidence 값은 실측 정확도나 확률 보정이 아니다. PRD Goals를 비워두고 SKELETON으로 표시하며 코드에서 사업 의도를 복원하지 않는 현재 방어는 유용한 후보이다.

`lib/extractors/__init__.py:1–92`, base 전문, requirements:1–75, conceptual:1–85, prd:1–115와 실제 소비부를 읽었다. 전체 9개 extractor의 모든 parser·renderer는 이 supporting 범위에서 미독이다. base의 Java 500/SQL 200 상한은 정렬 전에 수집을 자르며 SQL 검색 루트가 겹칠 수 있다. `lib/intent_doc_floor.py:1–69`의 floor는 self-reported count와 regex span 형식을 비교할 뿐 실제 파일/행의 사실·관련성은 읽지 않는다. 인용 PRD의 line은 1로 고정한다. probe read-only 시험도 root 내부 mtime 집합만 비교하므로 전체 시스템 무변경 증명은 아니다.

중요한 연결 불일치: 시험 :772–819는 clean flowchart가 floor와 flow validator 모두 통과한다고 설명하지만 `cli/reverse_engineer.py:82–92` 매핑은 flow이며 호출 :214–216은 ex.name인 flowchart를 전달한다. 이 경로에서 flow validator는 선택되지 않는다. floor rollback은 :197–213에 실제 연결돼 있다. 또한 clean fake의 f.java는 생성하지 않으므로 존재하지 않는 span도 floor를 통과하도록 fixture가 구성됐다. Zeus에서 spec→scenario→E2E 추적은 이런 형식 PASS를 사람 인수나 의미 검증으로 승격하지 않아야 한다.

<a id="i09"></a>
## 09 — test_falsy_zero.py

14개 함수는 Python 문자열의 numeric `or` guard, clock fallback, suppression, zero-equivalent coercion, syntax-error failsoft 및 현재 production tree의 HIGH 부재를 검사한다. 마지막 main 출력 검사는 PASS 또는 WARN 어느 쪽도 허용한다. 과거 l2_promoter/agents 결함 설명은 역사적 원인이며 현재 tree 결함 재현으로 세지 않는다.

`validators/falsy_zero.py:215–305`는 SyntaxError/읽기 오류를 빈 findings로 바꾸고 지정 production 하위 폴더만 스캔하며 HIGH도 main에서는 WARN이다. 따라서 AST 규칙 미적용/읽기 실패와 무결함이 결과 []로 합쳐질 수 있다. 실제 numeric-name/coercion helper 전문은 미독이며 scan_tree 대상 전부를 의미 검토한 것도 아니다. Zeus 자체검증과 토큰 효율화에 도입할 때 skip/parse 실패 분모, rule 버전, 표본 기반 검출 한계를 함께 기록할 후보이다.

<a id="i10"></a>
## 10 — test_file_matchers.py

18개 함수가 POSIX형 경로 및 일부 Windows backslash 문자열을 대상으로 18 predicate를 검사한다. 파일 존재나 실제 hook 실행 없이 경로 분류만 시험한다. frontend/src, backend, 특정 ci.yml 등 정해진 레이아웃 밖의 파일은 검사 대상에서 빠질 수 있다.

`lib/file_matchers.py:1–137`에서 일부 helper만 자체 정규화하지만 `handlers/post_tool/reviewer.py:309–345`는 모든 DAG matcher 전에 backslash를 slash로 바꾼다. 따라서 모든 helper가 backslash를 자체 처리하지 않는다는 사실만으로 현재 reviewer의 Windows 결함이라고 단정하지 않는다. reviewer :603–607에서 DAG 호출도 확인했다. cooldown/hash 조건 때문에 matcher true가 실제 검사 실행과 같지 않다. Zeus에서는 프로젝트별 경로 계약과 trigger→실제 검사 receipt 연결이 필요하며 WSL mount·case·UNC·symlink 실동작은 미검증이다.

<a id="i11"></a>
## 11 — test_fleet_atlas.py

7개 함수, `_ok` 31곳이 손으로 만든 scan report와 임시 Dart 3-repo 소스에서 blast radius, shared values, deterministic render, DRIFT/ABSENT/undeclared/deferred 표시를 검사한다. two-run 동일성은 같은 프로세스·같은 입력에서의 비교다. 일부 render 분기의 구체 문자열 기대가 있으나 UI 시각·접근성 및 실제 네트워크 인수는 없다.

`cli/fleet_atlas.py:39–115`는 seam_scan을 호출하고 BLOCKED를 shared 분모에서 제외한다. source docstring의 no extractor runs와 달리 scan의 실제 호출 체인은 extractor를 읽어 실행한다. 여기서 LIVE는 non-BLOCKED 정적 seam 상태다. `_ok`와 main 소비의 차이는 example_fleet와 같고 전역 _FAILS도 초기화하지 않는다. Zeus human-friendly VIEW 후보이나 그림이 실제 서비스 상태나 인수 완료를 보증하지 않도록 sample provenance와 미포함 계약을 표시해야 한다. render 구현 전문은 미독이다.

<a id="i12"></a>
## 12 — test_flow.py

3개 함수가 임시 CWD의 flow 디렉터리 부재, mermaid fence 존재, fence 부재를 stdout 문자열로 검사한다. empty CWD에 PASS를 기대하므로 0개 검사를 의도적으로 성공 문구로 표현한다. SUT main의 반환값은 검사하지 않는다.

`validators/flow.py:1–112`는 fence 표식과 HTML 주석, PRD US-ID substring을 검사하며 미포함 US는 WARN이다. 완전한 Mermaid parser/render나 흐름 의미·분기·예외·사용자 경험 검증은 없다. 모듈 import 시 stdin/stdout reconfigure도 있어 capture 환경 호환은 별도 문제다. Zeus SDD 2단계 디자인 형식 검사로 분류하고, 6단계 실제 사람 QA와 연결하려면 사용자 시나리오와 rendered interaction 증거가 별도로 필요하다.

<a id="i13"></a>
## 13 — test_frontmatter_norm.py

17개 함수가 빈 값·whitespace·간단 inline list·section header·ensure_field·UTF-8 BOM 파싱을 검사한다. 순수 문자열과 임시 BOM 파일이며 완전한 YAML 문법 시험이 아니다. malformed comma list를 정규화해서 허용하는 기대도 포함한다.

`lib/frontmatter_norm.py:1–60`은 단순 split/regex이고 `lib/frontmatter.py:1–62`는 utf-8-sig로 BOM을 제거하는 현행 방어를 가진다. quoted comma, nested YAML, duplicate 의미, 잘못된 입력 타입은 이 시험 밖이다. `lib/skill_score.py:210–261`에서 정규화된 intent/keyword/path/pattern을 실제 점수에 사용하는 것을 확인했다. 스킬 추천의 정확도나 자동 적용 권한까지 검증한 것은 아니다. Zeus의 명세 metadata schema 및 라우팅 계약에 맞춰 변환할 후보이며 원문 정책을 상속하지 않는다.

<a id="i14"></a>
## 14 — test_git_concurrent_race.py

3개 함수가 실행된다면 임시 실제 Git 저장소에서 4개 worktree add, 4개 분리 worktree commit, 3개 shared-target cherry-pick을 스레드로 동시에 시작한다. 단순 mock이 아니지만 synchronization barrier 없이 실제 경합 발생을 계측하지 않는다. Git 부재 때 각 함수가 조용히 return하고 main은 OK로 센다. 원본 시험 및 Git 명령은 이 검토에서 실행하지 않았다.

primary 자체 :38–67,78–282에 SUT subprocess/fixture/oracle이 들어 있다. local user와 gpgsign은 설정하지만 inherited global Git config, hooksPath, signing 외 설정을 완전히 격리하지 않는다. cherry-pick은 적어도 한 winner, winner 파일 존재, log 길이, fsck rc를 검사한다. losers의 일반 오류도 -1로 합치고 cleanup quit/reset rc를 무시한다. 파일 내용·전체 예상 commit 대응·fsck 진단을 검사하지 않으므로 no silent corruption 주장은 검사 조건만큼 한정된다. Zeus 협업 실행기에서 OS별 actual Git race와 상태 정합성을 따로 검증할 후보이고 PG 트랜잭션의 대체 증거는 아니다.

<a id="i15"></a>
## 15 — test_git_flow.py

24개 함수가 commit/branch 문자열과 임시 override 파일을 검사한다. import된 subprocess와 달리 시험 본문은 실제 임시 Git repo를 만들지 않으므로 docstring의 isolated git repos 설명은 실제 시험 분모와 다르다. Merge/Revert와 회사 prefix/branch 규칙은 원문의 기대이며 Zeus 정책으로 자동 채택하지 않는다.

`validators/git_flow.py:64–173`의 실제 main은 Git subprocess로 branch/최근 10개 commit을 읽고 stdout FAIL/WARN/PASS를 낸다. 이 CLI 효과·timeout·detached HEAD는 해당 primary가 검사하지 않는다. `_detect_override`는 `lib/git_flow_override.read_settings`의 상위 6단계 검색을 사용하므로 absent 시험은 실제 상위 설정에 영향받을 수 있다. 별도 override 시험의 max_levels=1 방어와 구별한다. Zeus의 source control 검사 후보이며 review 승인·push 권한·배포 완료 증거가 아니다.

<a id="i16"></a>
## 16 — test_git_flow_override.py

7개 함수는 임시 frontmatter의 key whitelist, body 무시, solo와 direct_push_main의 AND, malformed fence 및 company 독립성을 검사한다. missing-file 시험은 max_levels=1로 Windows temp의 상위 사용자 설정을 읽지 않도록 하는 현행 방어다.

`lib/git_flow_override.py:1–103`은 첫 파일을 찾으면 frontmatter 구간만 파싱해 반환하며 parser는 완전한 YAML이 아니다. `handlers/pre_tool/guard.py:218–233`에서 실제 Bash deny 일부를 solo에 따라 WARN으로 낮추는 소비를 확인했다. 고정 문자열 설정은 사용자의 개별 작업 승인·프로젝트 경계 증거가 아니다. parent-walk에서 repository boundary를 제한하거나 BOM/duplicate/경합을 검증하는 시험은 없다. Zeus에는 정의 정책과 실행 승인 기록을 분리할 필요가 있다.

<a id="i17"></a>
## 17 — test_golden_signals.py

21개 함수가 임시 resident ledger/marker, 합성 시각과 기록, mock TimeoutExpired로 unknown/0 분리, 최근 분모, 계약 요구 실행만의 실패율, timeout 부분 결과, JSON CLI, epoch 0 보존을 검사한다. `CLAUDE_STATE_DIR` 복구는 main 전체 finally에 있으므로 pytest의 개별 함수 호출에는 그 복구가 없다. timeout 시험의 artifact는 subprocess 전에 작성된 합성 파일이며 실제 모델 출력이나 파일 완결성을 인증하지 않는다.

`lib/golden_signals.py:45–123,220–367`, `lib/resident_store.py:80–183`에서 corruption 기록은 지표 전 필터링되고 계약 충족은 dict JSON 파싱으로 판정한다. `{}` 또는 임의 dict도 구조적으로 가능하며 의미·스키마·작성 주체는 보지 않는다. partial text를 인정하지 않는 현행 방어는 있으나 partial artifact는 파싱 가능한 dict면 인정한다. `cli/resident.py:136–224`에는 timeout partial stdout/stderr/artifact 보존이 현재 구현돼 있어 과거 손실을 현행 결함으로 세지 않는다. 스캔 중 일부 milestone 읽기 실패는 `lib/milestone_liveness.py:225–241`에서 skip될 수 있어 전체 예외 경고 시험이 부분 손실을 입증하지 못한다. `_span_days`는 UTC형 문자열을 local mktime으로 계산한다. Zeus에서는 분모·unknown·전체/최근 창 자산을 흡수 후보로 삼되 실제 CS 알림 전달, PG 사건, artifact attempt 정체성 및 모델 자격을 추가 검증해야 한다.

<a id="i18"></a>
## 18 — test_graduate_validator.py

10개 함수가 임시 g.STATE_DIR와 합성 mutation token으로 CLI usage/status/graduate/demote/tick rc를 검사한다. ready는 직접 True로 심으므로 실제 10회 재검증·사람 승인·자격 승계 증거가 아니다. `_Ctx`의 상태와 token 복구는 있다.

중요한 격리 경계: :117–121의 tick 시험은 STATE_DIR만 바꾸지만 `lib/graduation.py:67–74` watermark root는 별도 홈·assets에 결속되고 `cli/graduate_validator.py:75–81` → `validators/__init__.py:87–107`는 실제 doc_code_drift/self_model_drift.scan을 호출한다. 따라서 temp empty home만 읽는다는 주장은 성립하지 않는다. doc_code_drift는 ATLAS를, self_model_drift는 source 위치 기반 _HOME을 사용한다. tick은 accounting 파일도 쓰므로 read/accounting only라는 설명은 read-only 보장이 아니다. 이 검토에서는 실행하지 않았다. Zeus에서는 검사 target과 state·telemetry 경계를 모두 결속하고, rc0와 승격 durable commit을 별도로 검사해야 한다.

<a id="i19"></a>
## 19 — test_graduation.py

19개 함수가 주입 scan_fn/watermark/clock과 임시 JSON 상태로 streak, 12시간 dedup, threshold ready, 예외 회복, token, demotion, K 경계 및 audit append를 검사한다. fixture의 drift count 0은 실제 검사를 의미하지 않는다. :88–103은 watermark가 그대로면 scan 없이 streak가 증가하도록 명시적으로 기대한다. fresh graduate의 K회 안 drift는 자동 advisory로 낮추며 K 이후 blocking 유지라는 현재 조건도 구별했다.

`lib/graduation.py:276–400`은 파일 content hash가 아닌 root 디렉터리 mtime의 최대값을 재사용한다. 내용 변경·삭제·mtime 복원·서로 다른 root 변경을 완전히 대표하는 지문이 아니므로 'content provably unchanged'를 사실로 받아들이지 않는다. `graduate:408–438`는 ready truthy 및 공개 상수 token으로 전이하고 save_state(False)를 무시한 뒤 history와 성공 entry를 반환한다. JSON state와 history/flag는 한 트랜잭션이 아니다. registry의 VALIDATOR_NAMES는 import 시 snapshot이어서 이미 import된 프로세스의 즉시 갱신까지 concat 시험이 증명하지 않는다. Zeus 모델 자격 승계는 실제 다른 작업 표본·Astra 검증·버전별 guardrail·PG 승인 전이를 요구하며 이 validator streak를 모델 능력 증명으로 사용하지 않아야 한다.

<a id="i20"></a>
## 20 — test_graduation_audit.py

7개 함수가 임시 state의 ready flag를 직접 심고 실제 graduation producer 함수로 graduate/demote 이력을 생성해 reader 순서·집계·tail limit0·corrupt 줄 skip·CLI history rc를 검사한다. producer를 쓰므로 schema roundtrip 자산이지만 승인 주체는 합성 token이고 실운영 승격이 아니다. g.STATE_DIR는 finally로 복구한다.

`lib/graduation_audit.py:38–130`은 손상·non-object 줄을 버리고 파일 부재와 읽기 실패를 []로 합친다. summary의 최근값은 timestamp 최대가 아니라 append 마지막이며 경고나 누락 분모를 보고하지 않는다. producer의 실패 없는 임시 파일 roundtrip은 history 저장 실패·state/history 불일치·동시 쓰기·변조 검증이 아니다. Zeus에는 audit view를 PG 원장의 권위 있는 사건과 연결하고 읽기 실패/부분 손상 상태를 별도로 표시할 필요가 있다.

<a id="i21"></a>
## 21 — test_greenfield_spec_emit.py

4개 함수, `_ok` 17곳이 synthetic usage-metering draft에서 GWT/@id, Java package/runner GLUE, generated Steps·build.gradle 존재 및 spec_roundtrip CLEAN을 검사한다. :87의 glob iterator is not None은 존재 오라클이 아니지만 :88–89에 실제 목록 길이 검사도 있어 전체 package 검사가 공허하다고 단정하지 않는다. `_ok` 누적은 main에서만 실패로 소비한다.

`cli/greenfield_spec_emit.py:44–178`는 human-approved라는 help 문구와 달리 승인 receipt 확인 없이 JSON draft를 읽어 생성한다. domain·package 기반 경로를 쓰고 기존 feature/step을 덮어쓰므로 NEW root의 강제 검증이나 overwrite 시험이 필요하다. 시험은 wrapper=False이며 실제 Gradle/Java/서비스 실행을 하지 않는다. `lib/testgen.py:70–104,270–305`는 PendingException과 ID 집합 비교, `validators/spec_roundtrip.py:45–131`는 생성 feature의 ID coverage만 본다. pending test여도 CLEAN일 수 있는 설계다. Java overlay의 runner_cmd `gradlew test`와 실제 Windows/Linux/WSL 도구 계약도 미실행이다. Zeus SDD 1→3 초안 생성 자산이며 4단계 first RED/실행 분모와 6단계 사람 인수·7단계 배포는 별도 증거가 필요하다.

<a id="i22"></a>
## 22 — test_guard_failclosed.py

10개 함수가 합성 stdin/stdout으로 guard.main을 호출하고 JSON deny/warn/allow를 판독한다. 위험 문자열은 실제 shell에 전달하지 않는 fixture이며 이 검토에서는 그 함수조차 실행하지 않았다. `_run`은 SystemExit 코드를 무시하고 빈 출력은 ALLOW로 분류한다. empty stdin은 ALLOW/WARN 둘 다 허용한다.

`handlers/pre_tool/guard.py:143–293`는 parse/internal 오류 때 Bash형 신호를 찾아 deny하는 현재 방어를 가진다. 과거 malformed Bash fail-open을 현행 결함으로 세지 않는다. 다만 정확한 Claude Bash 도구 이름/command key에 대한 schema이며 PowerShell·WSL·Codex exec 도구의 포괄 권한 시험은 아니다. timed decorator와 오류 telemetry는 실제 파일 쓰기를 할 수 있고 primary는 그 root를 격리하지 않는다. `lib/telemetry_log.py:87–124`는 SystemExit까지 error로 계측해 정상 deny/allow의 exit0도 hook-latency error로 기록할 수 있다. Zeus에서는 권한 처리와 telemetry의 작업 결과 의미를 분리하고 실제 플랫폼 adapter가 소비하는 structured deny를 검증해야 한다. live guard 동작·환경 정책·차단 probe는 미검증이다.

<a id="trace"></a>
## 실행 진입과 검사 분모

`scripts/tests/run_units.py:39–194,263–301,314–403`을 새로 읽었다. registry에 있는 suffix는 run_units의 unit 분모에서 제외되고, pytest는 특정 fixture 인자 정규식에 의해 선택된다. 나머지는 callable main probe 후 subprocess로 실행한다. rc0+stdout failure token 부재는 성공으로 처리하며 stderr-only 실패 문구는 성공 경로에서 억제한다. 의미 검사 없이 return하는 Git 부재 경로는 SKIP-SUITE 문구가 없어 성공으로 보일 수 있다. 반대로 현재 SKIP-SUITE와 pytest collection 0 실패 처리는 존재하는 방어다. pytest missing 문자열로 rc=-1을 만드는 경로는 실제 pytest의 실패 메시지도 잘못 분류할 수 있다. 여기서는 정적으로 확인했으며 root의 별도 실행 재현과 혼합하지 않는다.

runner가 만든 임시 홈은 assets junction을 공유하고 필수 junction 실패 시 NO isolation으로 계속한다. 기존 CLAUDE_STATE_DIR/CLAUDE_TELEMETRY_DIR와 helper의 import-bound 경로까지 모두 지우는 것이 아니다. 자체 시험의 fixture 또는 임시 state만으로 전체 환경 격리를 선언하지 않는다. run_all/conftest의 전문과 실제 subprocess 환경은 root 별도 검토이며 여기서는 closure 완료가 아니다. 각 파일의 named main list와 최상위 함수 수를 대조한 분모를 files.json에 남겼다. pytest direct 수집에서 `_ok` 실패 누적을 소비하지 않는 세 파일은 example_fleet/fleet_atlas/greenfield_spec_emit다.

<a id="zeus"></a>
## Zeus 연결 조건

1. 스펙 논의: code-derived capability, 합성 meeting draft, 실제 사람의 목표·실패/금전 시나리오를 구분하고 승인된 spec revision과 scenario ID를 결속한다.
2. 디자인 분석: flow/fleet VIEW·Storybook/디자인 토큰은 검토 입력이다. fence 존재·정적 JOIN·출처 형식 통과는 interaction 인수가 아니다.
3. 코드 작성: testgen 초안에는 pending 상태·정확한 생성 경로·원본 보존 여부를 표시한다. Astra 설계→Sol guardrail→Terra 단순 구현의 자격 승계는 실제 난이도별 검증 표본으로 별도 증명한다.
4. 자체 검증: declared/discovered/executed/asserted/skipped/failed 분모, OS·tool version·input hash·환경·exit/timeout receipt를 구분한다. mock은 내부 회계 시험으로 쓰되 실제 인수로 세지 않는다.
5. 알파 배포: 이 22개에는 알파 기동·배포 health의 실제 증거가 없다. artifact와 환경별 배포 receipt를 별도 확보해야 한다.
6. QA 및 증적: 실제 사람의 핵심 시나리오와 실측 E2E를 승인 주체·시간·revision·환경으로 결속한다. 삼성 태블릿/폰, Device Farm SDK MCP/live/replay는 추후 단계다.
7. 라이브 배포: 고정 token 문자열이나 JSON ready flag를 프로덕션 승인으로 사용하지 않는다. 점진 배포·rollback·CS 관측은 PG runtime SSOT에서 상태 전이로 관리할 대상이다.
8. CS 대응: unknown과 0, 부분 손상, environment failure와 assertion failure를 구분하는 지표 자산을 가져오되 실제 notification 전송·사건 수습과 ticket 연동을 별도로 검증한다.

Git은 정의의 버전 기준, PG는 runtime 상태의 권위라는 Zeus 요구와 대조했다. 이 문서는 Zeus 구현 등가나 채택 승인이 아니다. 추가 구현은 root가 Codex/실제 Claude 독립 검토 결과를 비교한 뒤 진행한다.

<a id="unknowns"></a>
## 남은 범위

Primary 본문 미독은 0이다. embedded evaluator self-check 중간 본문, 모든 extractor/parser·provider/breaker·quota/atomic helper·spec bundle assembler·실제 fixture 서비스·run_all/conftest와 전체 caller closure는 미완료다. supporting-evidence.json에 없는 구간을 읽었다고 주장하지 않는다. 특히 file-level SHA는 전체 바이트 동일성을 확인하는 값이며 그 파일 전문의 의미 독해를 뜻하지 않는다.

원본 테스트 실행, 현재 원본 결함 재현, 실제 Claude 독립 검토, 라이선스/재사용 권리, Windows/Linux/WSL 실동작, 모델 자격, 실제 서비스·삼성 기기·사람 인수, 알파/라이브 배포, Zeus 흡수·적용은 모두 pending이다. 자체 검사만 UTF-8/LF·raw blob/bytes/SHA·range·review anchor·metadata/Ruff 대상으로 실행했다. PUBLIC 문서에는 인증정보나 긴 원문 복제를 넣지 않았다.
