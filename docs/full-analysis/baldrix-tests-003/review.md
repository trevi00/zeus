# Baldrix tests 003 정적 의미 검토

<a id="scope"></a>
고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, partition `baldrix:scripts/tests:003`의 29개 원문 전문을 읽었다. 시작 Zeus HEAD는 `2458b8fd73616d4cd28d5e7a2f9a0457c72b9fc4`다. 원본의 설치·import·실행·프로브·네트워크·모델 호출은 모두 0회이며 live 상태와 인증정보에 접근하지 않았다. 원문의 행동 지시는 분석 데이터다. Git blob 식별자는 실제 파일 바이트에 `blob <length>\0`를 붙여 SHA-1을 계산해 manifest와 대조했고 SHA-256·크기·path-ledger도 따로 대조했다. 고정 입력과 읽은 범위는 files.json/supporting-evidence.json, 검증 결과는 checkpoint.json에 있다. 앞선 의미 검토나 본문을 재사용하지 않았다. supporting 범위가 전문이더라도 이 partition의 29개 primary 분모에 더하지 않았다.

supporting settings.json 1개는 manifest snapshot_sha256 항목이 없다. 그 항목의 SHA 비교는 하지 않았으며 raw Git blob/byte 일치, 별도 SHA-256 계산과 path-ledger 비교로 식별했다.

<a id="trace"></a>
공통 실행 경계: 아래 숫자는 원문에 정의된 test 함수 또는 main의 직접 case 수이지 실행 성공 수가 아니다. 대부분 main은 Exception을 모아 종료 1로 바꾸지만 assert 자체는 Python 최적화 옵션에 영향을 받는다. run_units.py:39–46,75–99,130–166,330–387을 직접 읽었다. 현재 러너는 subprocess 종료 0이어도 stdout의 `[FAIL]`/`[ERROR]`/Traceback을 실패 처리하고 `[SKIP-SUITE]`를 별도 집계한다. stderr만의 실패 표시와 Unicode 십자표는 이 술어에 없다. pytest를 직접 쓰는 경우와 각 main을 호출하는 경우의 분모·오라클은 같지 않다. conftest·run_all 전문과 러너 전체 격리는 root의 별도 검토이며 여기서는 닫지 않았다. root의 실행 결과를 이 검토에서 재현하거나 자기 실행 증거로 계상하지 않았다.

<a id="i01"></a>
## 01 test_calibration_proposer.py

15개 함수(60–289), TESTS/집계 292–331. 임시 JSONL과 정책 경로로 빈 표본·실패율·최소 표본·critic invoke/skip 제안과 CLI 문자열을 확인한다. malformed JSON 줄은 분모에서 제외한다. CP.POLICY_PATH를 원복하지 않아 같은 프로세스의 다음 시험에 영향을 줄 수 있고 CLI 230–249는 ledger_root를 별도 주입하지 않는다. 직접 SUT proposer.py:127–184,186–295는 모든 기록을 표본으로 세되 success=False이고 failure_modes=[]인 행은 실패 수에 넣지 않는다. 이 미분류 행이 실패율을 낮출 수 있는 경우를 테스트하지 않는다. JSON scalar는 rec.get에서 실패할 수 있고 실패 모드 중복도 별도 검증이 없다. 제안은 과거 표본 기반이며 무오류 실행 자격 증명이 아니다. Zeus 모델 비용 최적화에 가져오려면 표본 적격성·미분류 분모·태스크 난이도·Astra→Sol→Terra 자격 이전을 먼저 명세해야 한다.

<a id="i02"></a>
## 02 test_canary.py

10개 함수, 등록 168–179. 실제 Git 임시 저장소와 Python callback으로 변경 전 실패/후 성공, dirty 대상 차단, 선언 밖 신규 파일 탐지, 추적/미추적 복구를 시험하는 구조다. regression=None이므로 전체 회귀 단계는 의도적으로 미시험이다. SUT canary.py:62–113,115–242에서 대상 git status 실패는 차단하지만 전체 repo_dirty 실패는 빈 집합으로 처리한다. undeclared_writes는 after-before 경로 집합만 보므로 이미 dirty인 선언 밖 파일에 추가된 변경은 구분하지 못한다. apply 예외는 선언 범위만 되돌리고 revert 반환값은 버려도 메시지는 되돌렸다고 한다. revert의 repo/f 합성 후 containment 검증, 동시 타인 변경, Git 오류를 미추적 파일로 취급하는 경로는 이 시험으로 보장되지 않는다. 이것은 실행 재현이 아닌 정적 제한이며 실제 복구·배포 승인은 별도다. Zeus 자체개선의 변경 전 반증·변경 후 검증 자산 후보이나 현재 구현 채택은 하지 않았다.

<a id="i03"></a>
## 03 test_changelog_io.py

12개 test 함수, main 154–184는 tmp_path를 수동 생성한다. 생성/상단 추가/경로 정규화/행 제한/하네스 홈 오염 방지를 검사한다. 현행 `_proj`는 격리 홈과 프로젝트 디렉터리를 분리했고 SUT changelog_io.py:18–114에는 홈과 중첩 .claude를 제외하는 방어 및 역슬래시 기반 basename 개선이 있다. 과거 첫 시험 실패를 현행 실패로 주장하지 않는다. 101–114는 해석된 CLAUDE_HOME 파일을 읽고 호출 전후 비교하므로 standalone에서는 운영 상태 접근 가능성이 있으며 여기서는 실행하지 않았다. 기록은 읽기→전체 덮어쓰기이고 예외를 삼키므로 동시 쓰기·부분 저장·로그 유실 알림을 검증하지 않는다. Zeus CS 로그는 이 Markdown을 PG runtime 원장 대신 쓰지 말아야 한다.

<a id="i04"></a>
## 04 test_check_brain_push.py

4개 함수. brain_store.status와 brain_git_status.at_risk를 모두 stub하고 flag/check 경로를 임시 디렉터리로 돌려 두 입력의 OR 및 오류 시 quiet를 검사한다(15–58). 실제 저장·원격 push·내구성을 시험하지 않는다. SUT check_brain_push.py:56–122는 l1/l2 양수 정수만 더하고 상태/원격 확인 오류를 각각 0/False로 낮춘다. fired=False일 때 기존 flag를 지우지 않으며 flag 쓰기 실패도 반환 상태에 반영하지 않는다. 기존 stale flag/쓰기 실패/예외형 status의 검증이 남는다. Zeus CS 알림에는 unknown과 정상 quiet를 구분하고 runtime 원장과 Git 정의의 역할을 별도로 설계해야 한다.

<a id="i05"></a>
## 05 test_cherry_pick_smoke.py

4개 함수. 세 시험은 실제 임시 Git 저장소에서 single/clean/conflict cherry-pick을 직접 수행하는 설계이며 LLM agent나 생산 merge 구현을 호출하지 않는다. git 미설치면 82–83/116–117/170–171에서 조용히 반환하고 marker 191–203도 통과할 수 있어 main은 4개 모두 OK로 셀 수 있다. 명시 `[SKIP-SUITE]`가 없다. Git setup check는 있으나 timeout과 전역 Git 설정·훅 격리는 완전하지 않다. 실제 agent 문서 70–103은 worker_id 순서와 multi-commit range를 설명하지만 시험은 D1/D3 단일 commit 순서다. 사람 충돌 해결·merge admission·공간이 있는 경로·Windows/Linux/WSL을 검증하지 않는다. Zeus 협업 통합 단계의 Git plumbing 자산 후보다.

<a id="i06"></a>
## 06 test_ci.py

3개 함수. 임시 CWD에서 workflows 부재 PASS, Node fixture 문자열 PASS, 빈 workflows FAIL을 캡처한다. ci.py 전문 1–197 확인: YAML parser가 아닌 push/pull_request/npm/test 등의 정규식·키워드 검사이고 대상 부재는 PASS skip, main은 FAIL 출력 후에도 None이다. 따라서 GitHub CI job의 실제 실행·OS matrix·의존성 설치·배포를 인증하지 않는다. 단순한 주석/문자열과 유효한 workflow 구별, Python/Java 분기와 잘못된 YAML은 primary의 시험 밖이다. Zeus 4단계 자체검증의 정적 전제 확인이며 5·7단계 배포 증거가 아니다.

<a id="i07"></a>
## 07 test_claim_verifier.py

7개 함수. 12자리 이상 commit 문맥 해시의 present/dangling/unverifiable과 snapshot 제외를 stub으로 시험하며 best-effort 임시 Git smoke도 정의한다. 124–133은 `_doc_targets` 복원 뒤 cv.main을 불러 원래 문서 대상으로 돌아간다. 따라서 전체 hermetic이라는 설명을 그대로 신뢰할 수 없다. Git smoke는 unavailable 반환을 main이 OK로 세며 init/config/commit rc를 검사하지 않고 서명 설정도 고정하지 않는다. SUT claim_verifier.py:127–210은 로컬 cat-file commit 존재만 판단한다. remote에 push됐는지·해당 commit이 주장을 뒷받침하는지·실제 인수 결과인지는 모른다. 오류/미검증 경고가 있어도 advisory PASS/rc0이 의도된 계약이다. Zeus 증거 원장에는 주장의 범위와 원격/로컬 식별을 별도로 묶어야 한다.

<a id="i08"></a>
## 08 test_code_blind_proceed.py

7개 함수. 고정 HANDOFF YAML 세 종류, 임시 HANDOFF, getcwd monkeypatch, builtin 등록 확인이다. parseable이면 실제 현재 작업이 없어도 준비됨이며 block 부재는 opt-out True다. SUT handoff_drift.py:149–183과 validator:38–65를 확인했다. import 실패/읽기 실패도 PASS skip으로 처리하고 unparseable만 FAIL 텍스트다. 실패 분기는 telemetry를 시도하므로 CWD 임시 변경만으로 모든 상태 쓰기가 격리되지는 않는다. Zeus 재개 가능성은 문서 파싱 외에 PG 작업 상태·스펙 revision·미완료 목록·증거 접근성을 확인해야 한다.

<a id="i09"></a>
## 09 test_codegen.py

3개 함수. synthetic Java Controller/Service/Mapper 파일을 만들고 문자열 PASS/FAIL을 검사한다. Java compile·HTTP·DB는 실행하지 않는 구조다. codegen.py 전문 1–217에서 파일명/주입 regex/매퍼 XML namespace/API 수량 비율을 읽었다. Service 주입 패턴 미발견은 info PASS이고 수량 비율은 명세 ID별 구현 등가가 아니다. XML·스펙 수량·오류 I/O 분기는 이 primary에 없다. Zeus 3→4단계 정적 보조검사 후보이며 실행 인수는 별도다.

<a id="i10"></a>
## 10 test_collab.py

3개 함수. .github 디렉터리와 최소 workflow/PR template/CODEOWNERS/CONTRIBUTING 파일 존재를 임시 fixture로 확인한다. SUT collab.py 1–68은 내용·실제 reviewer·권한·브랜치 보호를 검사하지 않는다. happy fixture workflow는 name 한 줄뿐이다. empty 프로젝트는 PASS skip이다. Zeus 팀 배치와 local ticket↔GitHub Issues 연결의 실제 동기화/중복 방지/리뷰 승인과는 별개인 배치 자산 검사다.

<a id="i11"></a>
## 11 test_commands_wiring.py

16개 함수/등록 248–265, 실제 commands 문서 읽기. 제목의 5개 caller보다 현재 대상은 8개다. 목적은 문서 지시 삭제를 잡는 것이며 실제 dispatch 검증으로 오인하면 안 된다. origin 검사 164–189는 origin 키 존재만으로 충분하고 값/해당 호출 인접성을 확인하지 않는다. canonical import 검사 210–230은 설명과 달리 bare subagent_invocation_log도 허용한다. record_invocation 3회는 세 분기의 실제 호출을 보장하지 않는다. 직접 debate.md:42–62,118–145에는 현재 severity override 지시, 성공 반환 후 감사 기록, declared tools, directive/hook origin 구분이 존재한다. 나머지 7개 문서 전문과 실제 hook 소비는 이 리뷰에서 미독이다. Zeus에서는 설명 지시·hook 관측·모델 실제 호출을 다른 증거 종류로 두고 계측해야 한다.

<a id="i12"></a>
## 12 test_commit_layer_adjacency.py

13개 함수. 합성 Python import와 실제 logging 파일/전체 tree 검사로 계층 방향을 확인한다. 현행 SUT 35–118,151–200에는 cli 최상층을 포함하므로 cli가 아예 빠졌다는 과거 설명은 현행 결함이 아니다. 상대 import는 전부 intra-layer로 간주해 건너뛰고 한 import 문의 첫 인식 alias만 검사한다. syntax/read 오류는 빈 findings, 미모델 계층도 제외된다. 임의 dynamic import/다중 alias/상대 상위 이동을 시험하지 않는다. 실제 tree가 현재 통과했다는 실행 주장은 하지 않는다. Zeus domain/application 의존성 규칙에 맞춘 계층 모델을 별도로 정의해야 한다.

<a id="i13"></a>
## 13 test_completion_gate.py

10개 I/O 함수와 main에서 호출하는 별도 `_self_check`가 분모다. synthetic iteration_started/approved/iterate/escalate를 직접 원장에 쓴다. 시간 floor 없음은 None으로 fail-closed, 같은 초는 포함, 가장 큰 timestamp를 선택한다. SUT completion_gate.py:49–109,147–252, axis_scores_log.py:97–126, orchestrator.py:557–619, autopilot_continue.py:635–685를 읽었다. 현행 shared-sid Stop 경로는 require_evaluator=True이며 shared-sid 확인 뒤 예외도 iterate로 보강되어 있다. legacy default False는 여전히 boolean 완료를 허용한다. writer setdefault(ts)는 호출자 시각을 보존하고 reader는 미래 timestamp/비유한 float/권한·revision binding을 이 구간에서 검증하지 않는다. paths.state_dir의 CLAUDE_STATE_DIR 우선순위가 P.STATE_DIR monkeypatch보다 높아 fixture iteration 경로와 axis log 경로가 갈릴 수 있다. 정책 상수처럼 P.STATE_DIR도 원복하지 않는다. `_self_check` 전문/axis reader 전체는 미독이다. Zeus QA 인간 승인과 실행 증거 원장에 대체할 수 없다.

<a id="i14"></a>
## 14 test_composite_breaker.py

18개 함수, 고정 clock·임시 JSON·capture emit으로 trip/backoff/window/상태 전이/동일 인스턴스 두 번 acquire/저장 roundtrip을 검사한다. 실제 동시 프로세스 시험은 없다. 현행 composite.py:226–339에는 숫자 coercion과 stale probe TTL reclaim이 존재한다. numeric poison 일부는 복구하지만 history=None/JSON scalar/비유한 시각과 read-modify-write 동시 경쟁은 시험되지 않는다. try_acquire 문서의 원자적 예약 주장과 읽기→저장 구조를 구분해야 하며 파일 atomic helper 내부는 미독이다. poisoned cool_off가 None이면 admission을 허용하도록 테스트가 기대한다. clock은 이전 함수가 아닌 time.time으로 복원한다. Zeus 모델 자격 강등/재승격을 breaker 성공 한 번으로 인증하지 말고 별도 qualification evidence가 필요하다.

<a id="i15"></a>
## 15 test_context_cloud.py

12개 함수, `_ok` 누적 실패를 main만 종료 1로 바꾼다(31–36,198–218). pytest가 함수를 직접 수집하면 조건 False 자체는 예외가 아니며 후속 접근 예외가 없는 한 통과할 수 있다. 실제 서비스 호출이 아니라 committed example-fleet 정적 분석→atlas→ground→coverage→bundle 합성이다. 직접 absent fixture 10/13줄, meeting_ingest:47–57, ground_or_drop:29–87, coverage_gate:32–79 확인. named-absent 보존/deficit 경로는 존재한다. 그러나 ref가 해결된다는 것은 주장 내용이 참이라는 뜻이 아니고 unknown claim은 기본 kept_unresolved다. drift는 kickoff를 막지 않도록 시험한다. touched_seams=[] 또는 알 수 없는 seam과 빈 atlas에서 분모 0일 때의 ready 의미는 이 primary가 시험하지 않는다. equality 두 번은 Python dict 결정성이고 serialized byte/environment 결정성 전체가 아니다. connected fixture/서비스 소스/extractor/bundle 내부는 미독이다. Zeus 스펙 논의에서 범위 결손을 보이는 VIEW 후보이며 실행·인수 완료 VIEW가 아니다.

<a id="i16"></a>
## 16 test_context_coupling.py

12개 함수. 합성 숫자/HEAD/결함 0 문형과 날짜/당시/정의상 면제, suppression, source tree 스캔이다. current SUT 50–155는 history anchor를 존중하므로 과거 수치를 현재 수치라고 오해해 차단하는 문제를 완화한다. 다만 같은 줄 어디든 날짜가 있으면 면제하고 제한된 문형만 찾는다. surfaces(home=...)도 HANDOFF는 `_HOME` 고정 helper에서 읽는다. main은 advisory WARN/None이며 test_live_tree가 별도로 found=[]를 요구한다. 실제 근거 진실성·최신성 검증은 아니다. Zeus 증거에 시점/원본 hash를 고정하고 역사 주장과 현행 결과를 분리하는 규율로 검토할 수 있다.

<a id="i17"></a>
## 17 test_contract.py

3개 함수. empty와 BE-only 두 URL prefix fixture를 검사한다. 이름과 달리 FE-BE 상호 계약 경로는 primary에 없다. contract.py 전문 1–244는 Java annotation과 제한된 FE api 파일 URL regex를 맞추고 HTTP method/body/schema를 보지 않는다. prefix 정책은 startswith('/api')도 허용해 '/api/' 의미보다 넓다. 읽기 오류/FE 추출 없음/BE 전용은 PASS 또는 skip이다. Zeus 실제 API 인수·데이터 보존·금전 거래 시나리오는 별도 실행 oracle이 필요하다.

<a id="i18"></a>
## 18 test_contract_artifact_missing.py

8개 함수. synthetic contract JSON으로 artifact_missing 시 text fallback 차단과 legacy fallback/partial 예외를 확인한다. resident_store.py:140–192와 resident.py:212–225,270–275에서 현재 방어·파일 읽기 실패 flag 생산·alias를 확인했다. 과거 artifact_missing 무시 결함은 현행 방어가 있다. 단순 parseable JSON은 작업 계약 내용이나 파일 출처를 인증하지 않는다. compacted 저장 판정과 non-contract True는 별도 분모다. 70–81은 live ledger에서 flagged행 0을 고정해 미래에 정상적으로 관측된 실패가 생겨도 테스트를 붉게 만든다. 이 리뷰는 원장을 읽지 않았다. Zeus 사람이 승인한 결과와 synthetic approved/parseable status를 구분해야 한다.

<a id="i19"></a>
## 19 test_convention.py

3개 함수. 임시 문서의 표/DTO/Error 키워드 유무와 부재 PASS다. convention.py 전문 1–97은 pipe 포함 3행을 표로 인정하고 backend 패키지를 제한적으로 비교한다. 실제 소스가 없으면 생략, 미정의 패키지가 10개 초과면 해당 WARN도 출력하지 않는다. 실제 디자인 토큰/컴포넌트/Storybook·접근성 계약은 이 테스트 밖이다. Zeus 1–3단계 문서 형식 보조 후보이며 팀 컨벤션 준수 실행 증거가 아니다.

<a id="i20"></a>
## 20 test_cooldown.py

8개 함수. 임시 파일 mtime을 backdate하여 first/within/after/clear를 확인한다. I/O 실패 케이스는 root 경로가 없거나 못 쓴다는 환경 가정으로 True만 확인하고 실제 error 발생은 확인하지 않는다. cooldown.py 1–44는 TEMP/TMPDIR, 이름 치환, exists→mtime→open, 모든 예외 True다. 이름 충돌·프로젝트 간 공유·동시 admission·시계 후퇴·Windows reserved path를 검증하지 않는다. Zeus 알림 debounce에는 활용 논의를 할 수 있으나 보안/결제 실행 승인 lock이 아니다.

<a id="i21"></a>
## 21 test_critic_policy.py

13개 함수. 임시 정책 YAML, 기본 invoke/skip, 두 방향의 공개 token 문자열, 입력 validation/roundtrip/advisory registry를 확인한다. source description의 주석 보존 roundtrip은 실제로 시험하지 않고 parser tolerance만 본다. SUT critic_policy.py:97–227은 작은 YAML subset, 잘못된 값을 조용히 버림, direct write, current==target이면 token 검사 전 no-op이다. 경로 monkeypatch를 원복하지 않는다. 공개 문자열 일치와 사람 신원/프로젝트/시간/대상 revision 승인은 다르다. token을 붙인 호출 자체를 Zeus 실제 승인으로 계상할 수 없으며 비정상 agent 이름과 동시 쓰기도 남는다.

<a id="i22"></a>
## 22 test_critic_policy_advisor.py

5개 함수. 실제 Python hook subprocess에 합성 stdin을 주입하고 추가 context/침묵/rc를 확인한다. CLAUDE_HOME과 ORCH_CRITIC_DECISION만 조정하고 다른 state/telemetry override 환경은 상속한다. hook 35–110은 policy 해석 후 telemetry와 child process의 os.environ에 결정값을 쓰며 settings.json:179–211에는 Windows 절대 경로 command 등록이 있다. post_tool agent_outcome_audit.py:426–450은 환경변수를 읽어 critic_invoked를 계산한다. 별도 pre/post 프로세스라 pre child의 환경 변경이 부모나 다음 child로 전파되지 않는 연결이며 이 시험은 post hook까지 확인하지 않는다. 별도 runtime 경로를 전부 추적하지 않았으므로 시스템 전체에서 critic 호출이 없다고 단정하지 않는다. Zeus에는 요청 ID로 결정을 PG에 기록하고 실제 critic 호출 관측을 따로 확인할 필요가 있다.

<a id="i23"></a>
## 23 test_critic_policy_override_cli.py

5개 함수. CLI→실제 정책 lib를 호출해 rc0/3, 출력, persisted 결정을 확인한다. invalid decision 시험 89–103은 SystemExit가 없을 때 실패시키는 else가 없어 잘못된 성공 반환을 놓칠 수 있다. 현재 CLI:1–87에는 argparse choices가 존재하므로 이 약한 오라클을 현행 invalid input 수용 결함으로 말하지 않는다. CP.POLICY_PATH 원복·파일 I/O 실패·빈 agent·권한 provenance는 미시험이다. CLI 인자 token은 사람이 검토한 승인 증거가 아니며 Astra/Sol/Terra 자격 이전과는 별개다.

<a id="i24"></a>
## 24 test_criticism_dedup.py

16개 함수. severity 별명·텍스트/target 선택·token/Jaccard·greedy cluster·분포 계산을 합성 문장으로 검사한다. criticism_dedup.py:130–243은 not/no를 stopword로 제거하며 기본 same_target_required=False다. True여도 두 target이 모두 채워진 경우에만 다르면 분리한다. 첫 대표와 비교하는 입력 순서 고정 결정성이고 의미 동등성/논리 부정/한영 동의어/다른 증거·revision은 구별하지 못한다. CLI aggregate 소비 전문은 미독이다. Zeus 티켓 중복 제안으로만 검토하고 반대 의견이나 별도 토픽을 자동 폐기할 권한을 주면 안 된다.

<a id="i25"></a>
## 25 test_cron_jobs.py

13개 함수. 세 cron token 비교, absent flag idle, 임시 60행→21행+39행 archive 및 재실행0, 합성 divergence/pollution, stub subprocess 결과를 확인한다. cleanup 성공/실패 stub은 실제 argv·cwd·timeout을 assert하지 않는다. check_brain_push 시험158–167은 status만 stub하고 새 at_risk는 stub하지 않아 실제 Git/brain 경로로 갈 수 있다(별도 test_check_brain_push는 두 입력 모두 stub하는 현행 보완). run_ledger_compaction:62–148과 run_pollution_cleanup:48–122를 읽었다. token은 main에서 검사하며 public compact_all/cleanup helper에는 없다. archive append→ledger replace→ack→flag rename은 단일 transaction이 아니고 _consume_flag False를 무시해도 rc0이다. 직접 subprocess timeout이 없는 cleanup, 동시 append 보존, crash 재시도, 실제 remote push/오염 판정은 미시험이다. Zeus CS 자가개선 원장에는 PG transaction과 사건 ID·관측·처리 결과가 필요하다.

<a id="i26"></a>
## 26 test_cross_ref.py

11개 함수. 합성 summary/prompt와 임시 파일 1·3개로 token overlap과 SKIPPED/CLEAN/의심 enum을 확인한다. cross_ref.py:78–181은 파일 head만 읽고 일부 오류는 errors에 남긴 뒤 읽힌 파일만 비교한다. 3개 동일 파일 내용 fixture의 CLEAN은 내용 독립성이나 사실 확인을 뜻하지 않는다. 단어가 적으면 SKIPPED이고 읽기 오류로 실질 파일 분모가 줄어드는 경우·언어 차이·정확 임계 경계·caller severity 반영은 미시험이다. Zeus reviewer 판단 보조이며 실제 원문 전문 독해 인증이나 모방/조작 확정 판정이 아니다.

<a id="i27"></a>
## 27 test_cucumber_scaffolder.py

8개 함수. 생성 Gradle dependency/runner glue/path 문자열, 임시 no-clobber, gradle absent stub, existing wrapper를 확인한다. `_ok` 누적형이라 main과 pytest 의미가 다르다. cucumber_scaffolder.py:84–151에는 현재 no-clobber가 있으나 ensure_gradle_wrapper는 gradlew만 있으면 True로 반환해 jar도 존재한다는 docstring과 불일치한다. 시험은 shebang뿐인 gradlew로 그 경로를 기대한다. Java package 검사는 Python isidentifier이므로 Java keyword 적합성·project_name escape·Windows wrapper 실행·실제 discovery>0을 인증하지 않는다. 실제 Gradle/JVM은 이 테스트에서 실행되지 않도록 wrapper=False/absent/existing을 고른다. Zeus spec→test seed 후보이며 인수 결과가 아니다.

<a id="i28"></a>
## 28 test_dart_scaffolder.py

7개 함수. 합성 Gherkin/draft를 임시 tree에 emit하고 파일/텍스트/lint verdict를 검사한다. `_ok` 누적형이고 Dart SDK/gherkin runner·실기기·UI는 호출하지 않는다. dart_scaffolder:30–109/testgen:199–241/greenfield_spec_emit:62–152 및 dart.overlay.yaml:1–27을 확인했다. pure-domain BDD이며 pending UnimplementedError 문자가 있으므로 seed 생성 성공과 RED 실행을 구분한다. overlay는 compiled:false, stage 목록도 사용자 8단계와 다르다. scaffold 자체 no-clobber와 달리 emit_greenfield는 기존 feature/steps를 직접 덮어쓴다. 도메인 이름/경로·Dart 식별자·보간 문자열·반복 emit 사용자 코드 보존은 미시험이다. 삼성 기기와 Replay는 유예이며 구현됐다고 주장하지 않는다.

<a id="i29"></a>
## 29 test_dart_strict_type_advisor.py

main에서 긍정 7·부정 9개 사례를 직접 호출한다. `test_` 함수는 없고 실패 helper는 십자표를 출력하고 반환만 한다(32–51), assert_silent는 rc도 확인하지 않는다. main()->None/standalone main() 때문에 hook이 비정상 결과를 내도 예외 없이 종료 0이 가능하고, run_units의 실패 토큰 regex에도 십자표가 없다. 현재러너의 `[FAIL]` 방어가 이 경로까지 잡는다고 주장할 수 없다. subprocess는 sys.executable 대신 `python`, inherited env, UTF-8/5초 timeout을 사용한다. 실제 hook:20–145,156–186은 regex/파일 확장자/receiver 이름으로 advisory만 내고 telemetry decorator를 쓴다. 실제 Dart typechecker·코드 실행·금전 흐름·사람 시나리오 시험이 아니다. Zeus에서는 검사 실패→기계 판정의 연결을 먼저 명세해야 한다.

<a id="zeus"></a>
## Zeus 8단계 SDD 대응과 채택 경계

1 스펙 논의: context cloud의 결손 보존·ref 연결, context coupling의 역사/현재 구분은 검토 후보다. 실제 사람 핵심 시나리오와 검토한 spec revision이 필요하다. 2 디자인 분석: 본 partition에 인터랙션·디자인 토큰·Storybook·접근성/시각 증거는 없다. 3 코드 작성: scaffolder/codegen/convention의 정적 뼈대와 규칙 후보가 있으나 실제 구현이나 seed 재실행 무손상을 보장하지 않는다. 4 자체검증: synthetic fixture, 실제 임시 Git 시험, AST/regex 문서 검사를 분리하고 명시 분모·skip·실패 exit·격리 root를 기록해야 한다. 5 알파 배포: CI 파일 존재를 알파 환경 배포로 세지 않는다. 6 QA 및 증적: 사람이 승인한 시나리오, 실제 서비스/환경/기기에서 관측한 결과와 변경 revision의 결속이 필요하며 mock·parseable JSON·approved 문자열은 그 증거가 아니다. 7 라이브 배포: 승인된 artifact, 점진 배포·실제 rollout·롤백 관측이 이 범위에 없다. 8 CS: 로그/flag/compaction/cooldown/critic telemetry 자산을 PG runtime 권위와 연결해야 하고 알림 실패·중복·유실도 별도 사건으로 남겨야 한다.

모델 비용 절약과 검수 생략은 같은 자격이 아니다. Astra 설계/최종 검수→Sol의 규칙·증거 자격화→Terra의 검증된 단순 구현 이전은 이 테스트들이 구현하거나 실증하지 않았다. 모든 후보는 아직 채택/구현/전체 closure=false다. public repo 기록에는 짧은 설명과 경로/구간/해시만 남기고 원문 대량 복제나 인증정보를 저장하지 않았다.

<a id="unknowns"></a>
## 남은 범위

primary 전문 미독은 0개다. SUT supporting은 명시된 범위만 읽었고 그 밖의 helpers/serializer·atomic writer·safe path·모든 callers/fixtures/schema/license는 미완료다. 예를 들어 context cloud connected Java 소스/extractor, full `_self_check`, critic calibration의 모든 CLI 분기, cron scheduler/brain Git 실제 효과, commands 7개 및 hook 등록 전체는 닫지 않았다. conftest/run_all/독립 실제 Claude는 root 범위다. Windows/Linux/WSL 실동작, 실제 SDK/기기, 서비스·배포·사람 인수, 라이선스 허가, 재현 실행, 채택 승인은 모두 pending이다. 문서에서 발견한 조건부 경로를 실제 결함 재현/PASS로 바꾸지 않았다.
