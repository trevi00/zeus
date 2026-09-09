# 파일별 정적 검토

<a id="file-01"></a>
## scripts/tests/test_strike_research_consume.py

1~247 전문. 13개가 임시 artifact의 accepted/forensic/escalation/missing 및 replay, dispatch payload, 후보 source 우선순위·artifact surfacing·invalid fingerprint를 검사한다. fixture 제목은 전역 FP인데 몇 시험 파일명은 다른 FP로 본문/identity 불일치가 존재한다. source는 local file이라는 산문이며 실제 조사·재현·승인 receipt가 아니다. collision 시험은 secret_scan_clean=True를 직접 주입하고 순차 쓰기만 검증한다. settings escalation에서는 code를 검사하지 않고 replay도 변경된 본문/다른 세대·동시 소비를 검사하지 않는다. stage는 활성화/실행과 구별되며 confirm token 문자열은 사람 승인 권위가 아니다. Zeus는 후보 hash/revision·실제 source review·PG lease/dedup와 독립 인수를 결속해야 한다. main 예외 rc1, 실행0.

<a id="file-02"></a>
## scripts/tests/test_structural.py

1~310 전문. 21개가 schema required/type/enum/additionalProperties/array/bounds, evidence 경로 존재, tool allowlist와 layer 우선순위를 검사한다. 없는/invalid spec은 빈 것으로 처리하고 비문자열 evidence와 빈 allowlist는 skip→ok로 고정한다. 파일 존재는 주장 지지/내용 hash/원본 읽기·실제 tool 수행/허가가 아니다. C:/missing 경로는 POSIX에서 상대경로이고 생성하지 않은 고정경로에 의존한다. dataclass shape 고정이라는 설명도 실제 field 집합이나 enum 순서를 검사하지 않는다. bool-as-int/NaN·복합 schema·경로탈출·symlink·race·denominator는 미검사다. Zeus no-mocked-acceptance에서는 structural ok를 실증/사람 인수로 승격하지 않고 필수 계약 누락을 명시해야 한다. 실행0.

<a id="file-03"></a>
## scripts/tests/test_stub_faker_lint.py

1~140 전문. 11개가 Java/JS comment/string 배제, body scope·partial hollow, Given/When/Pending 면제, delegate suspect, unknown framework 및 gate status를 검사한다. _ok는 assert하지 않고 전역 _FAILS에만 누적하므로 pytest 수집 경로에서 의미 실패가 전파되지 않는다. 수동 main만 이를 rc1로 만들며 리스트도 reset하지 않는다. default token은 같은 SUT 상수, delegate 이름 존재는 실제 assertion의 효과가 아니다. pending 면제와 unknown을 명시한 방어는 보존 후보이나 실제 BDD 실행/coverage·regex 변종/CRLF·동적 호출은 미검사다. Zeus에 보조 형식 진단으로만 변형하고 실제 테스트·사람 인수로 연결해야 한다. 실행0.

<a id="file-04"></a>
## scripts/tests/test_stub_faker_mutation.py

1~170 전문. 6개가 operator site/comment 제외·apply/restore, fake runner의 strong/weak/compile-fail/baseline-red를 검사한다. _ok 전역 누적은 pytest 실패를 전달하지 않는다. strong fake는 조건식의 if False 때문에 실제 a<=b 문자열 여부만 보고 결과를 만들며 실제 Gradle/npx/컴파일러는 없다. shipped tree byte-identical은 파일 하나의 read_text 비교일 뿐 전체 raw tree/권한·개행 불변을 입증하지 않는다. compile-fail all(mutants) 조건은 빈 목록도 참이고 deterministic/K cap/string 제외는 설명보다 오라클이 좁다. clone symlink·dependency 설치/프로세스 종료·restore 실패·중단·동시성 미검사. Zeus mutation은 실제 격리 runner/정확한 원본·변이 hash/유효 테스트 분모가 필요하다. 실행0.

<a id="file-05"></a>
## scripts/tests/test_subagent_invocation_log.py

1~533 전문. 34개가 JSONL append/선택 필드/tool 정렬·중복/None, sid/agent/origin 거부, corrupt line skip·검색/시각 창·session listing·mtime GC를 검사한다. STATE_DIR 두 참조를 바꾸고 복구하지 않는다. corrupt 대조군의 valid JSON은 sid/ts도 없어도 reader에 남으며 정렬·기록은 실제 agent dispatch/허용 tool enforcement가 아니다. 시각 테스트는 2000~2099의 넓은 범위로 정확한 half-open 경계/offset·clock jump를 검사하지 않는다. GC는 mtime에 의존하며 concurrent append/중단·보존권한·symlink·deterministic receipt·세대 replay는 미검사다. OS isolation residual을 forensics로 보강한다는 설명은 OS 차단을 대체하지 않는다. Zeus PG audit는 실제 executor identity/generation/lease와 연결하고 Git agent 정의와 분리한다. 실행0.

<a id="file-06"></a>
## scripts/tests/test_subagent_isolation_contract.py

1~187 전문. 7개가 worker/merge 주석, expected_tools 선언, evaluator forbidden 경로 문자열·HANDOFF residual을 검사한다. all-agents nonempty 방어는 있지만 도구 선언/경로 언급은 실제 플랫폼의 접근통제가 아니다. forbidden 설명은 다섯 경로지만 assert는 세 경로만, 해당 문자열이 forbidden block에 있는지도 보지 않는다. HANDOFF 부재는 일반 return으로 통과 집계된다. Read/Grep만으로 다른 상태를 읽을 수 있는지, 실제 모델/OS 프로세스 권한은 미검사다. 문서의 플랫폼 default ALL tools·기존 closure 주장은 외부 원문 미확인이다. Zeus는 독립 프로세스/영수증·권한 경계와 actual model 인수를 별도로 요구해야 한다. 실행0.

<a id="file-07"></a>
## scripts/tests/test_subagent_refs.py

1~194 전문. 8개가 fake agent 파일의 name 존재/미존재, builtin/template 면제, gsd→kha rewrite/미매핑·idempotent를 검사한다. 가짜 agent는 frontmatter 없이 제목만 있어 실제 callable/schema가 아니다. validator 반환은 버리고 stdout만 보며 quote-preservation 시험도 새 이름 포함만 검사해 실제 quote 유지/정확한 비대상 보존을 입증하지 않는다. fixer 파일 쓰기/atomicity·동적 routing/Agent vs Task·전이 참조는 미검사. 수동 main은 tmp_path를 자체 생성해 pytest autouse와 다르다. Zeus는 Git role ID/schema와 실제 dispatch 계약을 결속하고 단순 rename을 의미 동등성으로 보지 않는다. 실행0.

<a id="file-08"></a>
## scripts/tests/test_subprocess_decode_guard.py

1~143 전문. 11개가 subprocess text 출력 소비/encoding 누락 AST, returncode-only·bytes·unrelated·syntax-error 면제, live findings empty와 advisory rc0를 검사한다. 실제 cp949 자식 바이트/reader thread 오류를 재현하지 않는다. encoding 값의 옳음/None/alias/dynamic kwargs·다른 함수로 반환되는 출력·수집 분모/파싱 실패는 미검사다. live tree clean에 nonzero scan 분모가 없고 advisory main은 오라클상 rc0를 요구한다. Zeus 실제 stdout/stderr encoding+프로세스 결과를 보존하고 syntax skip를 성공으로 집계하지 않아야 한다. 과거11건 실패 설명은 실행 증거로 계상하지 않는다. 실행0.

<a id="file-09"></a>
## scripts/tests/test_surgery.py

1~180 전문. 11개가 mocked branch/dirty guard, subprocess --max 필수, source 문자열 인수/refresh와 production 후보 집합을 검사한다. unchanged는 evaluate(...).ok or True로 항상 참이고 실제 수술 실패를 호출하지 않는다. 후보가 없으면 membership/첫6개 before_must_fail 검사는 vacuous하다. refresh after pass는 같은 body에 두 문자열 존재만 확인해 제어흐름을 보장하지 않는다. no commit 문자열검사는 간접 호출/ps1 등을 닫지 않는다. dirty 시험의 rc는 버리고 worker 호출 부재만 본다. docstring rollback 약속과 달리 실제 실패 후 원상복구·동시 변경/정확한 preimage·모델 평가를 시험하지 않는다. Zeus 자가수정은 branch명/문구가 아닌 revision-bound 승인·독립 실제 검사·PG runtime·rollback receipt로 결속해야 한다. 실행0.

<a id="file-10"></a>
## scripts/tests/test_team_mailbox.py

1~395 전문. 14개가 envelope/type, inbox/outbox JSONL 분리·순차 cursor/advance false·readall·depth, malformed skip/cursor 전진, 세 worker·수제 task/done roundtrip, CLI와 traversal 경로를 검사한다. STATE_DIR 변경을 복구하지 않는다. 실제 workflow라는 이름은 같은 프로세스가 양쪽 메시지를 만들어 읽는 것이라 worker 실행/완료 receipt가 아니다. malformed 불완전 append를 cursor가 영구히 넘길 수 있는지·중간 generator 중단·동시 reader/writer/rotation·재전달·sender/recipient 결속·세대 fence는 미검사다. traversal 오라클의 startswith OR는 sibling-prefix 탈출도 허용할 수 있다. Zeus six-W/PG mailbox는 ack와 실행결과·권한/세대를 결속해야 한다. 실행0.

<a id="file-11"></a>
## scripts/tests/test_team_policy.py

1~386 전문. 고정 시간·수제 read/watermark/termination 함수로 baseline/growth/stall·pane veto·mailbox change·unknown 방어, quorum·kill/escalate·frozen denominator 및 CLI 순차 idempotency를 검사한다. stopped worker를 alive False/응답됨으로 표현하는 것과 실제 결과 인수는 다르다. 2명 threshold1이라는 주석은 엄격 과반과 다르므로 직접 수식 확인이 필요하다. CLI kill은 list append(True) mock이고 event는 substring 존재만 확인한다. kill 실패/반쯤 종료·새 세대 재사용·동시 pass/중복 worker·stale watermark/시계역행·조작된 pane/출력/응답 identity는 미검사다. 실제 E2E·OS 종료·모델 quorum 승인을 주장하지 않는다. Zeus PG frozen membership/generation·실제 worker 종료 receipt와 독립 사람 인수가 필요하다. 실행0.

<a id="file-12"></a>
## scripts/tests/test_team_runtime.py

1~352 전문. 14개가 naming/빈 인자, in-process worker의 done/error/task echo/deadline와 psmux 실행 경로를 선언한다. psmux 부재는 일반 return이라 전체 main14개 통과에 포함된다. real subprocess 시험은 모듈을 reload하여 실제 STATE_DIR로 돌아가고 mailbox를 직접 쓰고 지운다. 고유 sid/best-effort cleanup은 운영 server/credential/env 격리를 보장하지 않는다. done 후 세션이 남아도 실패하지 않고 강제 정리하며 natural exit idempotency도 True/False 모두 허용한다. 문서의 clean termination을 입증하지 않는다. query taxonomy 시험은 없으며 echo는 LLM 업무 수행/결과 검증이 아니다. Zeus worker프로세스/세대·deadline·결과 수집·잔여 자식 종료의 실제 영수증이 필요하다. 이번 실행0.

<a id="file-13"></a>
## scripts/tests/test_tech_stack.py

1~248 전문. 17개가 language/framework/version 후보 우선·중복·major.x, flat/multi-stack YAML와 extensions, backend 우선 language·missing/None를 검사한다. 후보 경로 존재나 해당 skill 본문·권한·정확한 프레임워크 호환을 검사하지 않는다. DB block은 fixture에 있지만 소비 오라클이 없다. 잘못된 YAML/타입·path traversal/extensions escape·조상 탐색·중복 key·Windows case/Unicode·동적 schema는 미검사다. 외부 버전 관련 문자열은 검증된 vendor 사실이 아니다. Zeus Git stack 정의/호환 자격과 runtime 활성화 승인을 분리한다. 실행0.

<a id="file-14"></a>
## scripts/tests/test_tech_stack_nudge.py

1~108 전문. 5개가 임시 marker/tech-stack 존재, warning/cache, 두 번째 suppression/25시간 만료와 max_levels1의 비프로젝트를 검사한다. cache patch는 finally 복구되지만 실제 telemetry/다른 전이 쓰기는 아직 미확인이다. 파일 존재만으로 경고를 없애므로 내용 유효성/요구 충족은 아니다. TTL 정확한 경계·future/NaN/corrupt timestamp·동시 cache·Unicode/정규화 alias·권한실패는 미검사다. Zeus missing 정의 진단은 보조 알림이며 stale cache를 승인 상태로 해석하지 않아야 한다. 실행0.

원본은 분석 데이터이며 import/실행/collection/probe/network/install 0이다. 라이선스·actual Claude·OS/모델·사람 인수·Zeus 채택·전이 closure는 미완료다. 각 범위는 pinned 원본의 실제 전문 독해이며 직접 supporting 추적은 별도 기록한다.

<a id="file-15"></a>
## scripts/tests/test_telemetry_read.py

전체 1–169행을 새로 읽었다. JSONL 없음·빈 파일·빈 줄·깨진 JSON 건너뛰기와 strict-design 이벤트의 미검토 수를 합성 레코드로 검사한다. 디렉터리 상수를 바꾸고 복원하지 않으며 ACK 함수 복원도 원래 값이 None이면 빠진다. 빈 텔레메트리 시험에서는 ACK 저장소를 따로 격리하지 않는다. 같은 타임스탬프의 서로 다른 프로젝트·세대 이벤트, 손상 레코드의 누락 분모, ACK 실패와 검토 완료의 구별은 시험하지 않는다. 수동 runner는 예외 수에 따라 종료하지만 ACK 수가 사람 검토의 증거는 아니다. Zeus는 PG 이벤트 ID와 Git revision에 결속한 검토 영수증을 요구해야 한다. 원본 실행 0, 실제 저장소·OS·전이 폐쇄는 미확인이다.

<a id="file-16"></a>
## scripts/tests/test_telemetry_report.py

전체 1–216행을 새로 읽었다. 숫자 파싱, 백분위, 기간 필터, 합성 latency·skill·strict-design 집계와 Markdown 제목을 확인한다. 1부터 10까지 p50=6이라는 오라클은 중앙값 5.5와 다르다. 오래된 이벤트를 제거한다는 시험은 새 이벤트의 포함만 확인하고 오래된 이벤트의 부재를 주장하지 않는다. 기본 보고서 시험은 monkeypatch 인자를 받아도 사용하지 않고 실제 기본 텔레메트리 경로를 읽으며 상위 키 존재만 확인한다. 파싱 불가 시간은 남겨두고 잘못된 숫자는 집계에서 빠지므로 품질·지연 분모와 결측률을 별도 보존해야 한다. 이 합성 집계는 실제 hook 성능, 모델 자격, 인수가 아니다. Zeus에서는 관측 창·표본·결측·revision을 PG에 함께 기록해야 한다. 원본 실행 0, 직접 구현 대조 외 환경 동작은 미확인이다.

<a id="file-17"></a>
## scripts/tests/test_test.py

전체 1–88행을 새로 읽었다. 임시 cwd의 test validator stdout을 검사하지만 main 반환값은 무시한다. 빈 FooTest 클래스가 PASS이고 시험 디렉터리가 없을 때도 PASS/skip이며, test 디렉터리 안의 Helper만 있으면 FAIL이다. 따라서 실행 가능한 assertion이나 컴파일·수집 성공을 보장하지 않는 이름/파일 존재 검사다. Zeus의 무 mock 인수에서는 빈 테스트를 검증 완료로 올릴 수 없고 별도 실행 영수증과 요구사항 연결이 필요하다. 실패 종료코드 전달과 플랫폼별 파일 탐색은 미확인, 원본 실행 0이다.

<a id="file-18"></a>
## scripts/tests/test_test_depth.py

전체 1–122행을 새로 읽었다. 합성 Python 본문을 AST 분류하고 validator 등록·WARN 출력을 확인한다. print("[FAIL]"), _check 호출도 깊은 검사로 취급하므로 실제 assertion 전파를 증명하지 않는다. helper가 무효여도 이름으로 통과할 수 있다. main이 FAIL 대신 WARN을 내는 것을 명시적으로 기대하며 반환값은 검사하지 않는다. AST 패턴은 시험 품질의 보조 신호만 유지하고 SDD 검증이나 사람 인수와 분리해야 한다. 구문 오류·파일 없음·가짜 assertion·실제 runner 수집 경계는 미확인이다. 원본 실행 0이다.

<a id="file-19"></a>
## scripts/tests/test_testgen.py

전체 1–179행을 새로 읽었다. feature 파싱 후 Java·Flutter·Rust 템플릿과 요구 ID의 roundtrip을 검사한다. PendingException, UnimplementedError, todo는 의도된 미구현 표식이다. 같은 파서와 생성기가 만든 feature의 ID 일치 100%는 step 실행이나 요구사항의 의미 검증이 아니다. 빈 spec과 알 수 없는 프레임워크는 방어하지만 ID 중복·재사용·retire, 인용부호/유니코드·식별자 충돌, 실제 Cucumber 표현식 매칭, 기존 파일 덮어쓰기 방지는 시험하지 않는다. Zeus 8단계 SDD에서는 생성물을 제안 상태로만 두고 독립 oracle과 실행·사람 인수를 별도로 결속해야 한다. 원본 실행 0, 프레임워크 통합 미확인이다.

<a id="file-20"></a>
## scripts/tests/test_thin_skill_advisor.py

전체 1–143행을 새로 읽었다. 합성 주입 점수·최소 표본·중앙값·thin 비율·현재 이름 교집합·정렬/중복 제거·창 제한·깨진 JSON을 확인한다. 실제 관련성 정답 라벨 없이 점수 임계치를 검사하므로 precision/specificity나 실제 주입 성공을 입증하지 않는다. CLI와 라이브러리 숫자 상수의 is 비교는 작은 정수 재사용 때문에 import 연결의 강한 증거가 아니다. bool/NaN·비정상 점수·시간 순서·이름 충돌과 실제 hook 소비는 미검사다. Zeus에서는 조언으로만 보존하고 모델 자격·승인·인수에 사용하지 않는다. 원본 실행 0, 전체 호출 폐쇄 미확인이다.

<a id="file-21"></a>
## scripts/tests/test_threshold_registry_locked.py

전체 1–76행을 새로 읽었다. 현재 registry의 잠긴 이름과의 교집합 없음, STRIKE_THRESHOLD 한 항목 주입 시 FAIL, validator 목록 등록을 검사한다. stdout 중심이며 main 반환값은 무시한다. 빈 registry도 교집합 검사를 통과할 수 있고 잠긴 이름의 별칭·우회 쓰기·런타임 불변성은 입증하지 않는다. Zeus에서는 잠긴 정책과 revision을 Git 정본으로 관리하고 실제 변경 경로의 승인/차단 검사를 별도로 해야 한다. 원본 실행 0이며 실제 모든 잠긴 임계치와 소비자 폐쇄는 미확인이다.

<a id="file-22"></a>
## scripts/tests/test_threshold_tuning.py

전체 1–220행을 새로 읽었다. registry, 합성 40개 반복 이벤트의 metric, holdout gate, ready 제안 파일·confirm token·소비 후 재사용 거절을 검사한다. 두 날짜에 같은 패턴을 반복한 표본은 독립 일반화 근거가 아니며 precision proxy에는 실제 품질 라벨이 없다. 본문 길이 결측을 NaN으로 막는 방어는 유지할 후보다. paths patch 후 모듈 reload로 묶인 경로를 다시 복원하지 않아 삭제된 임시 경로가 모듈에 남을 수 있다. 올바른 token 문자열은 사람 승인 자체가 아니며 제안 값 변경·동시 이중 소비·기록 실패·오래된 revision·rollback은 시험하지 않는다. Zeus는 PG 변경 거래와 Git 정책 revision, 자격 있는 모델 검토 및 사람 인수 영수증을 별도로 요구해야 한다. 원본 실행 0, 실제 승인·모델·OS·폐쇄 미완료다.

<a id="file-23"></a>
## scripts/tests/test_tier1_counts.py

전체 1–208행을 새로 읽었다. pytest/unittest의 임시 성공 시험 subprocess와 여러 프레임워크 출력 문자열 파싱, command 결과의 수 분류를 검사한다. 여기서는 subprocess도 실행하지 않았다. 테스트 runner 출력은 fixture이며 실제 own runner 실행 근거가 아니다. 239 passed와 1 skipped를 tests=240으로 세고 failed·passed·xfailed도 합계에 포함하므로 총수와 통과/인수 수를 구분해야 한다. subprocess 반환코드·상속 환경/플러그인 격리 확인이 약하고 외부 프레임워크는 문자열만 본다. unknown을 zero와 구별하는 방어는 유용하지만 dict의 ok 자체는 영수증이 아니다. Zeus의 SDD 단계 완료는 skip·실패·미확인 분모를 분리한 실행 증거로 결정해야 한다. 원본 실행 0, 실제 수집·OS·모델 인수 미확인이다.

<a id="file-24"></a>
## scripts/tests/test_timefmt.py

전체 1–112행을 새로 읽었다. naive 지역 시간, Z/z/+00 및 명시 offset, 잘못된 입력을 검사한다. 일부 기대값은 같은 datetime.timestamp 기본 동작에 의존한다. local과 UTC가 달라야 한다는 조건은 표준 offset과 daylight 플래그로 판단해 시험 날짜의 실제 offset이 0인 DST 지역에서 거짓 실패할 수 있다. DST 중복/존재하지 않는 시각, 음수 epoch·범위 초과·시계 역행은 미검사다. Zeus는 PG 사건 시간에 명시 UTC와 수집 시각/세대를 보존해야 하며 파싱 성공은 worker 영수증의 신선함이나 승인 증거가 아니다. 원본 실행 0, Windows/Linux/WSL 실제 확인은 미완료다.
