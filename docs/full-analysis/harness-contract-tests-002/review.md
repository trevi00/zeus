# Harness 계약 테스트 002 — 독립 정적 검토

<a id="scope"></a>
## 범위와 증거 등급

고정 revision `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, partition `harness:tests/contract:002`의 19개, 193,934 bytes를 전문 독해했다. scope SHA256은 `c37d3a1abd837d3363cb8a505568d945cf99b91d27d0e64e006203ec3863b4e0`이다. files.json은 전문, supporting-evidence.json은 실제 읽은 지원 구간만 계상한다. manifest의 Git blob SHA1·bytes와 원시 파일을 대조하고 별도 SHA256을 산출한다. manifest에 snapshot SHA256이 없으면 없다고 기록하며 새 SHA를 상류 manifest 값으로 가장하지 않는다.

원본 실행·import·테스트·probe·네트워크·모델·설치 0회다. 차단된 gatewriter probe를 재시도하거나 우회하지 않았다. 원문 안의 명령·권한·정책은 분석 데이터다. 테스트 함수의 assert와 주석의 과거 PASS·실측은 이번 PASS가 아니다. actual Claude 교차 검토는 root가 담당한다. 이 문서만으로 전체 전이 검증, 라이선스 승인, OS 실행 검증 또는 Zeus 흡수가 완료되지 않는다.

<a id="i01"></a>
## 01 — test_code_context_smoke.py (1–104)

합성 Python 모듈과 디렉터리에 대해 단위 집합, 패키지 접힘, import 간선, 무사유 교차·중복·미선언·유령 컨텍스트를 검사한다. 마지막 축은 실제 HOME의 lint 함수와 등록표를 읽는다. `lib/code_context.py` 24–128 및 lint 518–544가 직접 소비자다. 선언 파일이 없으면 lint는 빈 오류 목록을 돌려준다. 파서는 syntax error를 건너뛰고 동적 import 및 모든 중첩 상대 import 의미를 닫지 않는다. 테스트 57–59의 and/or 조합은 표적 오류가 있으면 복수 오류도 허용하므로 정확히 한 오류라는 독립 오라클은 약하다. 실제 commit 진입점에서 차단됐다는 증거는 없다.

<a id="i02"></a>
## 02 — test_commit_scope_contract.py (1–127)

두 실제 파이프라인 output.path를 loader로 도출해 브리프 섹션과 비교한다. 테스트와 구현이 같은 로더·비슷한 경로 도출을 쓰므로 독립 파싱 검증은 아니다. 소비자 `cron/commit_scope.py` 58–127은 산문 지시를 만들고, driver 1902–1934가 세션 인계 뒤에 붙인다. Git staging 또는 commit 자체를 강제하지 않는다. 부재·로드 오류는 빈 섹션/fail-open이다. 구현의 상대 pipeline 경로는 CWD에 의존한다. output의 모든 자료형과 외부 프로젝트를 검증하지 않는다. 문장에 git add -A 등이 등장하는지 및 과거 8/8 수치를 고정하는 검사는 금지문 실행이나 동시 수정 보호를 증명하지 못한다.

<a id="i03"></a>
## 03 — test_consume_gate_contract.py (1–195)

합성 reachability 캐시, 장 길이, video_id, 중첩 JSON 요청을 사용한다. 미지 종류·캐시 없음·파싱 실패는 허용이라는 계약을 확인한다. `consume_gate.py` 57–141 및 driver 961–976은 실제 fail-open 경로다. 차단 때 incident 기록 후 요청 watermark를 전진시키지만 기록 오류는 삼키며, 바깥 예외도 통과로 전환한다. `_consume_role_request`의 '스폰 뒤에만' 주석과 달리 차단 분기에도 호출된다. 이는 큐 전진 정책이며 실제 스폰 증거와 분리해야 한다.

테스트의 차단 분기 확인은 inspect 문자열이고 실제 arm→기록→consume 트랜잭션은 실행하지 않는다. `harness-test-state-` 문자열 검사는 실패해도 나머지 함수 진행을 자동 중단하지 않는 check이므로 격리 경로 가드 자체는 아니다. 실 HOME의 운영 데이터 축은 부재 시 SKIP_AXIS다. 이 fail-open을 결제·배포·QA 승인에 그대로 이식할 수 없다.

<a id="i04"></a>
## 04 — test_contract_visibility_contract.py (1–179)

시험 대상은 테스트 안의 AST 검사기 `_prints_on_success`(62–97)다. 합성 check 함수 다섯 모양과 contract/integration의 최상위 check를 스캔한다. 문법 오류·check 없음은 건너뛰고 최소 15개라는 분모만 둔다. 중첩 함수·try·loop 안의 print는 실제 성공 경로 도달성 없이 긍정될 수 있다. `not`으로 시작하는 조건을 성공 분기로 간주하는 것은 cond의 논리 동등성을 증명하지 않는다.

일반 출력 `ok`의 존재를 확인해도 `lib/test_outcome.py`의 assertion 행 문법·들여쓰기·채널을 만족한다고 할 수 없다. 따라서 '성공 출력이 존재'와 '러너가 성공 assertion을 계수'는 별도 계약이다. 이 AST 검사가 실행 분모 전체나 사용자 기능을 검사했다고 세지 않는다.

<a id="i05"></a>
## 05 — test_coverage_bootstrap.py (1–95)

coverage 미설치 시 SKIP 후 0으로 끝난다. 설치 시 실제 measure를 호출하도록 작성되어 있으나 대상은 unit/test_ledger 한 패턴이다. shard 존재·100개 초과 statement·lib hit·최소 5개 surface·환경 복원을 검사한다. never 목록은 타입만 확인한다. `coverage_cmd.py` 41–158은 coverage startup을 PYTHONPATH로 주입하고 child 결과를 받아 shard를 합친다. 계측 성공과 스위트 판정 성공은 독립이며 테스트는 전체 테스트 성공을 확인하지 않는다. 표시 percentage의 파일 집합과 never 계수도 구별해야 한다. branch=false이며 전체 기능 커버리지·돈 흐름 검증으로 환산할 수 없다.

<a id="i06"></a>
## 06 — test_dba_projection_contract.py (1–145)

`engine.projection_pg`를 FakeProjection 모듈로 교체하므로 실제 PG가 없다. events=515/stages=5, sync 예외, 원장 없음, 원장 바이트 보존과 heartbeat 유무를 검사한다. DSN 전달 및 events>0/stages=0 결과는 검사하지 않는다. 원래 sys.modules 항목이 없었던 경우 fake 모듈 복원의 범위에도 잔여가 있다.

소비자 `cron/dba_projection.py` 54–108에서 sync 성공 후 0행 주석과 코드가 다르다. 90–92는 events가 있는데 stages=0이면 healthy면 안 된다고 적지만, 93–102는 events만 보고 경고하며 stages를 판정하지 않고 heartbeat를 기록한 뒤 0을 반환한다. 따라서 **sync가 events>0/stages=0을 반환한다는 조건에서** 건강 신호가 기록되는 정적 경로가 있다. 실제 projection이 해당 결과를 반환하는 조건까지 추적·재현하지 않았으므로 운영 장애로 단정하지 않는다. Compose 221–223의 DBA healthcheck는 heartbeat 나이만 읽는다. 상류 PG는 JSONL에서 재생성하는 비정본 projection으로 Zeus PG runtime SSOT와 권위 방향이 다르다.

<a id="i07"></a>
## 07 — test_delegation_cap_attribution_smoke.py (1–144)

임시 state/project/ledger에서 실제 step delegate를 호출하도록 되어 있으며 role-request의 첫 stage를 사용한다. dispatch payload의 delegation, role_source=self_report와 l2-spawn 이벤트 없음 등을 확인한다. step 288–342는 명부와 계획 샤드를 검증한 뒤 이벤트·역할 카드를 기록/출력한다. Task spawn은 실행하지 않는다.

테스트 후반의 위임 수는 tick 술어를 리스트 내포로 다시 계산한다. 실제 tick 140–146에 delegation_budget halt가 있지만 이 테스트는 cap 경계나 창 앵커·일일 spawn 계수를 통과시키지 않는다. 계약에 model/effort/budget_turns를 실었다는 사실은 모델 자격·예산 집행 증거가 아니다.

<a id="i08"></a>
## 08 — test_disarm_says_what_happened_contract.py (1–159)

가짜 derive_stage_states의 DONE/READY/예외를 주입하고 disarm 이벤트의 stages_total/done/last_stage를 검사한다. 실제 파이프라인 순서와 원장 fold를 통과하지 않는다. 구현 158–253은 기계 strict 실패 시 binding 유지, 사람 기본 경로에서는 경고 후 unlink하며, 해제를 완료선 선언과 분리한다. 테스트의 dict 삽입 순서 오라클은 원장 도출 순서가 파이프라인 순서인지 입증하지 않는다. binding 제거·프로세스 정지·실제 단계 결과를 이번 테스트의 검증 범위로 부풀리지 않는다.

<a id="i09"></a>
## 09 — test_domain_lead_delivery_contract.py (1–140)

실제 domain-lead 카드 전문이 캡 800 이내이고 출력에 전부 포함되는지 확인한다. waves/rationale/scopes/rules 필드를 각각 제거한 합성 plan, 지정된 네 문서와 정책 인용 형태를 검사한다. 현재 `_print_role_card`와 roster contract의 본문 전달은 구분되며 전자는 모든 카드에 800자 절단을 적용한다. 특정 카드의 현재 길이 검사가 명부 전체 무절단을 보장하지 않는다. 카드 출력은 에이전트 수신·준수·독립 검토 완료와 다르다. decomposition의 구조 거부는 사람의 핵심 시나리오 완전성 판정이 아니다.

<a id="i10"></a>
## 10 — test_driver_caps_smoke.py (1–98)

실제 파이프라인 caps의 양의 정수, 최소 3개 대상, MAX_TURNS와 상한 관계를 검사한다. YAML 읽기 실패는 건너뛰고 bool도 Python int에 포함된다. 모든 파이프라인의 누락 없는 검사를 증명하지 않는다. driver 1751–1760에 일일 cap 소비자가 있고 1928–1931에 Claude `--max-turns` 전달이 있으나 provider의 준수·영속 계수 복원·병렬 spawn 상한은 이 테스트에 없다. iteration 수와 모델 turn의 실제 관계 및 토큰 비용도 미측정이다.

<a id="i11"></a>
## 11 — test_dropped_print_contract.py (1–482)

출력 헤더/이름/절단 N·0건·limit 계약, 단일 구현 소유, 두 실제 CLI의 임시 HOME 출력을 검사한다. `spiral_cmd.dropped_lines` 344–377과 arming 139–155, spiral 493–505는 같은 출력 함수를 소비한다. 이 현행 방어는 유지할 가치가 있다. 다만 부분 집합과 개수 오라클은 중복 이름을 모두 배제하지 않으며, CLI 원장 무변경 검사는 행 수 중심이라 같은 수의 바이트 변경을 잡지 못한다.

내장 변이 검사는 원문을 in-memory compile/exec하고 일부 변이를 kill하도록 작성됐다. 예외 자체를 kill로 취급하는 축은 의도한 의미 검출과 구별해야 한다. child가 최소 하나의 check를 방출해도 전체 기대 assertion 수가 실행됐다는 보증은 없다. 이 파일의 E2E 명칭은 임시 하네스 CLI 시험이며 실제 사용자 인수가 아니다. 이번 리뷰에서는 변이·CLI·모듈 실행 모두 0이다.

<a id="i12"></a>
## 12 — test_entrance_reconfirm_contract.py (1–196)

실제 run_suites를 임시 SystemExit fixture로 호출하도록 작성됐으며 빈 글롭, 빈 only 오류와 unknown-only 빈 결과를 검사한다. 그러나 재확인 판정의 주요 오라클은 테스트 내 교집합 함수이며 실제 apply_via_sandbox의 원장 쓰기·보류 분기를 호출하지 않는다. AST에서 intersection과 only 인자를 찾는 것은 연결 계약의 부분 증거다.

직접 읽은 sandbox 172–263, 313–417에는 실제 재확인 교집합·firm만 거부·불안정분 verified=False/deferred·검증 후 parking 구분이 존재한다. 과거 '재확인 없음'을 현행 결함으로 쓰지 않는다. run_suites는 여전히 returncode만 판독하므로 SKIP/무검사 exit0의 의미는 일반 assertion-aware suite reader와 다르다. 주석 340–348의 '한 번이라도 붉으면' 서술과 intersection 실제 뜻도 같지 않다. 이 정적 발견은 실제 실행 결과가 아니다.

<a id="i13"></a>
## 13 — test_entrypoint_import.py (1–140)

실제 handlers/cli/validators의 파일을 열거하고 파일마다 새 child state에서 import하도록 작성됐다. 최소 전체 20개와 각 디렉터리 비공집합을 검사한다. 현재 매 child 새 state는 기존 inherited-state 오귀속을 줄이는 방어다. 하지만 파일 경로 차집합만 읽어 기존 바이트 수정·삭제·일시 생성 후 삭제를 놓칠 수 있고, state 밖 IO·네트워크·프로세스를 차단하는 OS sandbox가 아니다. import 성공은 main 기능·배포 성공이 아니다. 이번 리뷰는 그 import도 실행하지 않았다.

<a id="i14"></a>
## 14 — test_env_seal_smoke.py (1–379)

실제 `_seal_env`, 환경 이름 grep, apply 호출의 AST 탐색, CLI 경계 monkeypatch를 결합한다. 다섯 HARNESS 변수의 봉인과 이름 출력, 호출 전에 HOME을 확정하는 현행 sandbox/autoheart 방어를 확인하도록 작성됐다. 직접 읽은 sandbox_cmd 47–70/143–172와 autoheart 1377–1408에도 그 방어가 있다. autoheart 미봉인을 현행 결함이라고 쓰지 않는다.

다만 테스트 ④(212–239)는 HOME만 저장·복원하면서 실제 sandbox_cmd.main의 seal을 통과한다. ②는 다섯 변수를 복원하지만 ④ 이후⑤의 saved_env는 이미 변한 상태다. **④ 진입 시 STATE 등 다른 봉인 변수가 존재하면** 그 값이 삭제된 채 후속 테스트로 흐를 수 있는 정적 경로다. 원본 실행이나 활선 쓰기는 하지 않았다. AST caller 검사는 alias/dynamic 호출과 함수의 실제 도달성 전부를 닫지 않으며 module 집합은 call-site 개수와 다르다. non-HARNESS 자격정보와 도구 권한까지 봉인된다는 뜻도 아니다.

<a id="i15"></a>
## 15 — test_evidence_freshness_contract.py (1–407)

고정 TODAY의 날짜·시각·최신 근거·같은 날 변경·날짜 없음·오래된 근거와 실제 Git 변경시각 축을 결합한다. 실제 후보 랭킹에서 적합 후보를 찾는 운영 축은 top 일부만 살피고 부재 시 SKIP_AXIS다. 원장 경로를 임시로 바꾸고 합성 external_action을 쓰며, 독립된 실제 승인자가 없다.

직접 소비자 evidence_freshness 96–127/141–226은 경로 변경을 못 찾으면 날짜만으로 fresh를 허용하며 실제 측정의 진실은 검증하지 않는다. age가 max보다 큰지만 비교하므로 미래 날짜의 음수 age도 별도 거부하지 않는다. 실제 시간 source와 경로 fingerprint, 증거 아티팩트 바이트를 결속해야 사람 승인 근거가 된다. spiral 215–290은 저장소별 Git 시각과 정책 임계 출처를 제공한다. 모든 저장소 탐색·실제 propose 이후 원장 경로의 완전 추적은 미완료다.

<a id="i16"></a>
## 16 — test_extractor_canary_contract.py (1–280)

원문 raw compile, 실제 synthetic project 역추출, 후보 추출기 변형, fake `_canary_rc`/worktree helper를 결합한다. 본문 패턴과 entries 표지를 함께 재고 기준선 붉음은 DEFER, 자신/계약 변경은 SELF_BLIND로 보류하는 현재 방어가 구현에 존재한다. 스텁 rc 비교는 Git 후보 트리 구성 및 실제 양쪽 추출 전이를 증명하지 않는다.

BODY_SIGNS와 MIN_ENTRIES 키 집합 일치만으로 고정된 여섯 산출물 분모를 보장하지 않는다. 다만 실제 run_canary 250–259에는 파일 존재·known graph cycle 검사가 별도로 있으므로 '집합이 비면 전체 즉시 PASS'라고 주장하지 않는다. 렌더 문자열과 fixture 답의 일치는 실제 문서의 사용자 의도·인수 시나리오 완전성 검증이 아니다. 정책/분류 전체 closure 및 모든 extractor 본문은 이 지원 범위에서 미독이다.

<a id="i17"></a>
## 17 — test_fleet_contracts_smoke.py (1–299)

Dart/C#/proto/Spring/WebSocket/Kotlin/Android XML과 fanout의 합성 문자열을 파싱한다. 실제 컴파일·HTTP·앱 실행·Device Farm은 없다. 외부 `C:/Users/rudtn/outpos` 프로젝트의 조건부 관측은 부재 때 note를 출력하므로 정규 skip 분모에서 누락될 수 있다. 해당 외부 레포들은 이번 고정 소스 검증 대상도 아니다.

직접 atlas 345–398은 method/path segment 및 RPC 이름을 비교한다. 코드도 orphan이 관찰이며 판정에는 base URL 귀속이 필요하다고 명시한다. payload schema, 인증, 순서·재시도·결제 중복/취소 의미까지 호환된다는 뜻은 아니다. 나머지 언어 파서 함수 전체는 지원 미독으로 남긴다.

<a id="i18"></a>
## 18 — test_fleet_mount_boundary_contract.py (1–121)

시험 대상은 Compose YAML 선언이다. `/harness`가 들어간 문자열 mount의 :ro, `/harness/state` 종료 문자열 및 healthcheck 존재를 검사한다. 실제 Docker create·mount·health 실행은 없다. long syntax, 명시 state :rw/:ro, 다른 경로로 alias한 mount, unrelated writable mount와 privileged/docker.sock 등 전체 권한을 모델링하지 않는다. 따라서 'state만 쓰기 가능' 전체 권한 증명은 아니다.

Compose 전문 1–231에서 실제 role mount는 트리 :ro와 state 별도이고 현재 방어는 존재한다. researcher 루프는 여러 명령 실패를 `|| true`로 넘기고 health는 collector heartbeat 하나에 의존한다. DBA는 시작 시 unpinned psycopg를 설치하며 heartbeat 나이만 잰다. 이 텍스트가 현재 Docker에서 실행 중이라는 증거는 없고 Windows/Linux/WSL의 상대 bind path·쉘·이미지와 실제 서비스 부작용은 미검증이다.

<a id="i19"></a>
## 19 — test_gate_dump_contract.py (1–219)

실제 CLI subprocess JSON의 structured=90, derived=32, all=122 등 고정 기대값, 적어도 6 pipelines, key/type/enum, 결손 fixture·missing·0건·결정성을 검사하도록 작성됐다. 본문의 옛 78+32=110 설명과 현행 오라클을 혼동하지 않는다. 이것은 검사 선언 수이지 실행한 gate 수 또는 인수 성공 수가 아니다.

gate_dump 88–178은 loader의 machine 체크를 나열하고 로드 실패/0건을 거부한다. 필수 인자 결손의 실제 소비자는 lint 1661–1793이다. 현재 구조화 결손은 오류, 파생 결손은 수를 출력하고 유예한다. 따라서 dump가 결손 fixture를 수용한다는 사실을 '현행 lint도 침묵'으로 확장하면 틀리다. 파생 유예 또한 PASS 인수로 계상해서는 안 된다. runtime checks/gate_runner의 전체 전이는 이번 범위에서 실행/전문 추적하지 않았다.

<a id="trace"></a>
## 지원 추적과 재사용

supporting-evidence.json의 정확한 line_ranges만 지원 독해로 주장한다. 위 본문에 명시한 신규 소비자와 기존 integration001의 동일 raw bytes 지원 구간을 구분한다. 재사용 행은 이전 ledger SHA256, source row, revision, raw SHA, line_ranges, prior review_ref를 결속한다. 기존 Zeus SDD 및 모델 라우팅 지원도 동일 바이트 확인 후 재사용하며 현재 시스템 전체 검증을 뜻하지 않는다. 부분 지원은 이번 19개 전문 분모에 더하지 않는다. 정책·fixture 참조가 primary에 등장한다는 것만으로 해당 파일 전문을 읽었다고 세지 않는다.

<a id="zeus"></a>
## Zeus 대응 — 구현이나 채택 승인이 아닌 검토 요구

| 사용자 단계 | 가져올 검토 경험 | 부족한 실제 증거 |
|---|---|---|
| 1 스펙 논의 | 분모·미지 항목·제안 근거 날짜와 출처 표시 | 사람이 아는 핵심 시나리오와 범위 승인 |
| 2 디자인 분석 | 구조화 계획과 소유 범위, 카드 전달 | 실제 화면·인터랙션·접근성, Storybook 상태와 시나리오 연결 |
| 3 코드 작성 | 컨텍스트 검사·제한된 commit 지시·위임 귀속 | 강제되는 프로젝트 경계와 qualified model 배정 |
| 4 자체 검증 | 정규화된 결과·skip·분모·기준선/후보 대조 | 재현 가능한 OS/의존성/데이터 fixture와 실제 SUT 실행 |
| 5 알파 배포 | 선언과 실제 마운트/health 효과 구분 | 환경 식별·실제 배포 결과·되돌리기 증거 |
| 6 QA 및 증적 | fake·정적·실행·미측정 구분, 재확인 보류 | 실제 사용자/실기기 시나리오·증거 해시·사람 승인 |
| 7 라이브 배포 | disarm와 완료선 분리, 결손 판정 보류 | 점진 배포 지표·승인 권위·실제 돈 흐름 안전성 |
| 8 CS 대응 | 탈락 이름·사유·누락 수, incident 귀속 | 통지 수신·응답·복구·회귀 시나리오의 실제 연결 |

Zeus에서는 PG runtime SSOT와 Git 정의 원천을 유지해야 한다. 상류 JSONL→PG projection이나 이벤트상 self_report/승인 텍스트를 권위 있는 사람 인수로 그대로 승격하지 않는다. 모델 이름·턴 상한 선언보다 Astra 설계/최종 검증 → Sol 자격 검증 → Terra 자격 검증의 실제 guardrail와 결과가 필요하다. Samsung 휴대폰/태블릿 및 Device Farm/MCP/live/replay는 유예 상태이며 이 범위는 구축 완료를 주장하지 않는다.

<a id="unknowns"></a>
## 미완료 경계

19개 전문 정적 리뷰만 완료했다. 실제 실행/실패 재현, 완전한 caller·정책·테스트 전이 closure, OS 행렬, 병렬/재시작/정리, PG 투영 반환 조건, 실제 에이전트 전달·모델 자격, 사람 인수, 라이선스/배포 권리, actual Claude 독립 검토와 root 구현·채택 승인은 남아 있다. 소스·runtime·공유 coverage·commit/push는 변경하지 않았다. UTF-8/LF·metadata hashes/ranges/refs 및 자체 기록기 Ruff만 검증한다.
