# tests001 per-file full-body review

26 fresh full bodies; source execution0; adoption false.

<a id="file-01"></a>

## scripts/tests/__init__.py

0bytes / 0lines / fresh direct full-body read / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

0바이트 빈 package marker 전문. 런타임 검사/fixture/승인 없음. 빈 파일을 성공 테스트 한 건으로 세지 않는다. 테스트 package import 경로 역할만 보존 후보, 라이선스 및 실제 수집 OS 동작은 미실행이다.

Direct ranges: []

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-02"></a>

## scripts/tests/conftest.py

3406bytes / 83lines / fresh direct full-body read / `e7f56d0c8ef2a3491e14ce7c7cbedf8165d2abd419207013ebd777eb0573d50d`

1~83 전문. pytest autouse로 CLAUDE_HOME을 tmp_path로 돌리고 insight index whitelist를 넓히며 두 cache를 비운다. 테스트용 writer 허용 확대는 production 권한 검증과 다르다. insight_index import가 env 변경보다 앞이므로 module 상수 및 fixture 이전 collection import의 side effect는 막지 못한다. fixture teardown은 monkeypatch 환경/whitelist만 자동복원하고 cache 이전 내용은 복원하지 않는다. private pytest DontReadFromInput class에 reconfigure noop을 영구 추가하여 stdin 호환 실패를 가리며 실제 콘솔 UTF8 효과를 검사하지 않는다. pytest 아닌 main 실행에는 이 fixture가 없고 파일시스템/네트워크/다른 HOME 경로를 sandbox하지 않는다. Zeus는 환경 주입 전 import 금지 및 실제 read-only 격리를 실행 영수증에 결속하고 whitelist 완화 검사를 실제 승인 테스트로 승격하지 않는다. 정확 SUT 부분은 후속 지원 추적 pending.

Direct ranges: [{"path": "scripts/lib/insight_index.py", "read_ranges": [{"start": 85, "end": 142, "raw_range_sha256": "b33888ed1698a1cef6162fd75af17eea9decee657b818a64637ff55544728ae3"}, {"start": 161, "end": 188, "raw_range_sha256": "ba4f89d118ecfca9ee48dc97815fdad94eeb0dac57b9cc502323469f74a8b618"}]}, {"path": "scripts/lib/paths.py", "read_ranges": [{"start": 12, "end": 110, "raw_range_sha256": "7f9192b09d7f5d4d6d5f61832330c15c8b465f2ef391bc9bfe8d0ed26899b7e8"}, {"start": 145, "end": 158, "raw_range_sha256": "53614df85db3d4410393ed53f5d1e849447a5852c659f2b43d8617f7043426dc"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-03"></a>

## scripts/tests/probe_intent_docs.py

6027bytes / 124lines / fresh direct full-body read / `9f4d30b32082fae9b92db90f49c9a38ba97b44680631d68cf280576b5acc2612`

1~124 전문. 별도 probe라 해도 cli와 같은 lib.intent_doc_floor.verify_doc를 재사용하고 extractor를 직접 실행하여 결과 frontmatter를 센다. 기존 디스크 문서를 읽어 검증하는 루프가 아니다. self-check는 여섯 형식 fixture이며 빈 skeleton 통과를 의도한다. provenance span 존재와 숫자 비율은 source 의미·사실·실제 파일 존재·사람 인수 오라클이 아니다. get_extractor는 try 밖이라 registry 오류는 전체 중단, can_extract/extract 오류는 error로 보고 rc1, 모든 비디렉터리나 모두 skip은 rc0이다. 기본 인수 없음도 실제 repo 검사 대신 self-check다. --self-check가 첫 인수면 뒤 --write 검사보다 먼저 반환한다. read-only 선언은 extractor 전이 부작용을 보증하지 않는다. Zeus에서는 전체 요구/claim 분모, 실제 span 원문 대응과 독립 의미 검토가 추가돼야 한다. 실행0, transitive extractor/라이선스/OS 효과 미확인.

Direct ranges: [{"path": "scripts/lib/intent_doc_floor.py", "read_ranges": [{"start": 32, "end": 69, "raw_range_sha256": "873d79609e9c1dd16426066a32fabbae4d1a0fa65e29dec9fbbcb0af075edfc8"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-04"></a>

## scripts/tests/run_all.py

13346bytes / 304lines / fresh direct full-body read / `a1d1a5e37a22758d1579ac439cad844c113208daf44ca73ca6998fc3f3dce9ee`

1~304 전문(큰 첫 출력의 잘린 166~304를 별도 재독해). validator registry별 main 존재를 먼저 import로 검사하고 test module missing만 skip, transitive ModuleNotFound는 다시 던진다. missing test를 skip 분모로 드러내는 방어는 보존한다. 그러나 import 단계는 per-test try/cwd 복원 밖이고 SystemExit는 main 검사의 Exception에 잡히지 않아 runner 중단 가능하다. test SystemExit는 subprocess 재실행하므로 이미 수행한 side effect가 반복될 수 있다. in-process에는 timeout 없고 sys.modules/env 등의 상태가 유지된다. 실패 토큰은 stdout만 정규식 검사하여 stderr-only 오류나 다른 표기는 빠지고 정상 negative-test 출력은 오탐할 수 있다. 모든 skip도 rc0이며 pytest rc0는 세부 skip 분모를 모듈 PASS에 합친다.

격리 재실행은 환경 플래그만으로 우회 가능하고 home 빌드/import/자식 예외 또는 timeout에 None을 반환해 원래 홈에서 계속할 수 있다. 주석의 과거35/35는 이번 증거 아니다. telemetry 단일 module global 임시 변경은 전체 저장 경로를 격리하지 않는다. run_units의 junction/symlink 자산은 실제 read-only가 아니다. Zeus는 격리 실패를 blocked로 기록하고 모듈 count와 실제 case 실행/skip를 분리해야 한다. 실제 runner/validator 실행0, 관련 SUT는 primary run_units/conftest 및 후속 지원을 구분한다.

Direct ranges: [{"path": "scripts/validators/__init__.py", "read_ranges": [{"start": 1, "end": 83, "raw_range_sha256": "8cb043caa84080557c4ba69ed2a761961c52c76ae569bed8f0e1e549f7a2fa28"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-05"></a>

## scripts/tests/run_units.py

17340bytes / 407lines / fresh direct full-body read / `604dcf79343099bd6bfd87586591daa7db06eef5a88c922890a2b01e13ce9f68`

1~407 전문(첫 출력 잘린 1~196을 별도 재독해). validator registry 밖 test_*.py를 찾고 fixture 이름 세 가지를 top-level def 정규식으로 검사하여 pytest를 라우팅한다. class method/async/custom fixture는 놓칠 수 있고 pytest 없음은 warning 후 main fallback이므로 검사 의미가 달라진다. pytest 수집0 rc5 실패는 유용하지만 all-skipped rc0와 assertions 실행 수를 분리하지 않는다. main 없는 파일은 probe import rc3이면 skip이며 import가 sys.exit(3)해도 no-main으로 오인 가능하다. 검사 전 import probe와 본 실행이 분리돼 side effect가 두 번 발생한다. source stderr는 rc0에서 버리고 stdout failure token만 판정한다. SKIP-SUITE 문자열만 별도 skip, 일반 SKIP/0tests 출력은 PASS가 될 수 있다. 모든 skip도 rc0이다.

CLAUDE_HOME 임시 홈은 실제 assets를 junction/symlink로 연결하므로 쓰기 금지 권한이 없다. required asset가 존재하지 않으면 continue해서 없어도 성공이며 link 생성 실패는 None 후 비격리 실행이다. reset은 이름만으로 보존 링크를 골라 오류를 무시하고 cleanup도 실패를 숨긴다. 링크 대상 변경/추가 symlink 및 남은 자식 작업의 쓰기 전이 폐쇄가 없다. subprocess timeout은 직계 자식 종료일 뿐 전체 트리 종료 보장이 아니다. Windows cmd mklink/rmdir와 POSIX symlink 차이, UTF8 child 및 부모 env 상속은 미실행이다. Zeus는 source-only read-only 환경과 process tree 종료, PG attempt authority를 쓰고 이 자체 runner를 안전격리 증명으로 채택하지 않는다.

Direct ranges: [{"path": "scripts/validators/__init__.py", "read_ranges": [{"start": 1, "end": 83, "raw_range_sha256": "8cb043caa84080557c4ba69ed2a761961c52c76ae569bed8f0e1e549f7a2fa28"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-06"></a>

## scripts/tests/test_ac_tree.py

6923bytes / 217lines / fresh direct full-body read / `b050b03810c68e6cf1d2672e18d8a85861272b50b86d3fab2c96c1c04b6faf80`

1~217 전문. 17개 수동 TESTS의 실패/예외를 누적하여 rc1, predicate lambda와 list emitter로 gate/advisory 조합을 검사한다. callable/axis/description, advisory bool/None/range 거절은 보존할 오라클이다. 빈 leaves approved와 predicate가 다른 동일 axis/description leaf ID 동일을 명시적으로 기대한다. 이는 사용자 요구 0개를 승인하거나 의미 바뀐 검사의 ID를 인수 증거로 재사용해도 된다는 뜻이 아니다. mean_low 테스트는 개별값2가 있어 낮은 평균 경로만 독립검증하지 않는다. gate 반환 strict bool, predicate 예외, emit 영속 실패, 중복 ID/누락 요구 분모 등은 이 본문에 없다. emitter는 메모리 list라 PG 감사/실제 사람 승인과 다르다. Zeus는 요구·오라클·revision/attempt에 결속한 실제 receipt를 별도 확인한다. SUT ac_tree 직접 구간 추적 pending, 테스트 실행0.

Direct ranges: [{"path": "scripts/lib/ac_tree.py", "read_ranges": [{"start": 101, "end": 146, "raw_range_sha256": "f6509c889a35342fb8a40ec7871eb2f9406e016a4c86e132f6beda2b52b0a88a"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-07"></a>

## scripts/tests/test_action_evolver_selfcheck.py

796bytes / 26lines / fresh direct full-body read / `5b4c3b13720cccc7d9f0c96eee0c485453f0b92f83eccf7733e5d3f8138646ac`

1~26 전문. main이 cli.action_evolver._self_check를 직접 import/call하여 int는 그대로, 나머지는 rc0으로 바꾼다. None이나 잘못된 반환도 성공이므로 엄격한 결과 계약이 아니다. bool도 int라 True는 실패코드1, False는0이 된다. test_ 함수가 없어 일반 pytest는 수집0이나 수동 runner에서는 main이 실행된다. 자기검사를 연결하는 얇은 wiring이며 별도 독립 오라클은 없다. self_check가 호출하는 event/반사 연쇄의 fixture와 복원 범위는 직접 지원을 더 읽어야 한다. 현재 원본 실행0이며 자가개선의 실제 효능·사람 인수를 증명하지 않는다.

Direct ranges: [{"path": "scripts/cli/action_evolver.py", "read_ranges": [{"start": 375, "end": 509, "raw_range_sha256": "98ce1d37e7d9bc4f4174b7689cc743992ce67ba1cd96d2a85f0d64cb019b6395"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-08"></a>

## scripts/tests/test_advisory_ack.py

6489bytes / 182lines / fresh direct full-body read / `30707569b3948b9ba255b9fedc58649559a2130e9afd71061df414523fb52961`

1~182 전문. 세 함수가 두 registry 인스턴스의 파일 roundtrip/중복 false/독립 저장, alias 인수 오류와 monkeypatch argv 위임, AST argparse import 부재를 검사한다. registry ack_path를 직접 변경하고 복원하지 않아 in-process 뒤 테스트에 삭제된 임시 경로가 남는다. DD.main만 finally 복원한다. alias 성공은 fake_main의0이며 실제 ack CLI 동작을 검사하지 않는다. AST 금지는 동적 import나 다른 CLI parsing 표면까지 막지 않는다. ack 문자열 저장은 사람이 특정 revision을 승인했다는 증거가 아니다. 동시 append, 오류/부분 저장, 키 검증 및 재사용 승인 부재는 pending. Zeus는 advisory 확인과 인수/채택 권한을 구분하고 PG generation 결속을 요구한다. 수동 TESTS 3건 예외/실패 rc1, source실행0.

Direct ranges: [{"path": "scripts/lib/advisory_ack.py", "read_ranges": [{"start": 47, "end": 113, "raw_range_sha256": "41e2af07ea249cdbcd0080f24cda312f3d5f47138814c3a87cbe949f57b7add7"}]}, {"path": "scripts/cli/advisory_ack.py", "read_ranges": [{"start": 38, "end": 60, "raw_range_sha256": "38a0545a3394056348c2935153caaebe0e3f9ed68395f17ad445a8238ae5516a"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-09"></a>

## scripts/tests/test_advisory_research_dispatch.py

5060bytes / 119lines / fresh direct full-body read / `8f148fbd139935732c48550b380c5fa246740d554c87f839a28f880ebfcb0f5b`

1~119 전문. 여섯 함수는 공백 정규화 fingerprint, HIGH만 dispatch, cross-session blocklist 및 per-fingerprint quota를 순차 파일 fixture로 검사한다. paths.STATE_DIR를 바꾸고 복원하지 않는다. corrupt blocklist를 empty로 보고 재dispatch 허용하는 fail-open을 테스트가 의도적으로 고정한다. should_dispatch와 record를 순차 호출하므로 경쟁/원자적 quota 소비, 실제 researcher 시작/실패 회수는 검사하지 않는다. hash 이름/길이 일치가 같은 의미나 source revision 결속을 증명하지 않는다. Zeus는 PG recurrence dedup·lease·권한 및 corrupt-state 차단을 별도로 설계하며 과거 blocklist를 영구 승인으로 보지 않는다. 수동 main 예외를 rc1에 반영, 실행0, 직접 SUT 폐쇄 pending.

Direct ranges: [{"path": "scripts/lib/advisory_research_dispatch.py", "read_ranges": [{"start": 42, "end": 88, "raw_range_sha256": "fd0c63a1d2ab3485e4cfd28eec6ab7af9942c6594be49d500b09f023dda43eeb"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-10"></a>

## scripts/tests/test_agent_invocation_audit.py

17286bytes / 484lines / fresh direct full-body read / `4fbcf7c9b93ffe468059872b9656809ea18af536313b930d61fa0a82e8fbb39c`

1~484 전문(440~484는 출력 절단 후 재독해). 20개 수동 테스트가 handcrafted Claude PostToolUse JSON을 subprocess hook에 넣고 임시 JSONL을 읽도록 작성됐다. ORCH_SID/명시 sid/prefix/fallback, traversal 거절, origin 및 frontmatter tools, 무출력/잘못된입력/noop를 검사한다. 실제 Claude 플랫폼 이벤트·도구 자격·인증된 session은 없다. 일반 helper는 ORCH_SID 제거와 CLAUDE_HOME 임시 주입을 하나 malformed/empty stdin 두 case는 env 격리 없이 실행하도록 돼 있고 text subprocess encoding도 명시되지 않는다. JSONL 독해는 손상 줄을 버려 추가 corruption을 검출하지 않을 수 있다. 무출력 case는 returncode를 확인하지 않는다. 2MiB prompt는15초 내 반환과 한 record만 검사하고 자원/정확한 절단을 입증하지 않는다. dual-prefix 우선 테스트는 선호 prefix를 입력 첫 위치에 두어 반대 순서의 우선 정책을 구별하지 못한다. declared tool 목록은 실제 사용 가능성/사용 receipt가 아니다. Zeus는 hook 관찰과 실제 executor 권한·generation을 분리하고 PG event dedup 및 raw receipt 결속을 요구한다. 이번 테스트 실행0, settings/SUT 실제 구간은 후속 추적 pending.

Direct ranges: [{"path": "scripts/lib/agent_tool_audit.py", "read_ranges": [{"start": 36, "end": 106, "raw_range_sha256": "bb99a6f575477e9cd2d4842a1b37331722c992308c200598ed7c2384b87c3d9d"}]}, {"path": "scripts/handlers/post_tool/agent_invocation_audit.py", "read_ranges": [{"start": 97, "end": 221, "raw_range_sha256": "88b12ecce5fa96c99d9e8ce403b5fde8f3a8b1a6305228f0a37ab4b91e66ca93"}]}, {"path": "settings.json", "read_ranges": [{"start": 242, "end": 254, "raw_range_sha256": "795a01516c5171402767cf055b79788e754e563d8a2f847cff92161dc80835d2"}, {"start": 262, "end": 274, "raw_range_sha256": "0be6f20118a55d152c8b0e0b4f7d9b7915832dbad5416d71f2172449131e333b"}, {"start": 294, "end": 306, "raw_range_sha256": "836abc7d5d7e897a8d10ab3c2b667b29ccd782d1facaa3ced677342939edf987"}]}, {"path": "agents/harness-critic.md", "read_ranges": [{"start": 1, "end": 12, "raw_range_sha256": "ec1eec5abda77dff18957d530a033d1fe0f01ab649a51cee2eeb68dcc06f8432"}]}, {"path": "agents/harness-planner.md", "read_ranges": [{"start": 1, "end": 12, "raw_range_sha256": "0dd3e01d62964fdac2ef8f0d6fa73d59bd06a5ba436a830da6ee5c5269fbfb27"}]}, {"path": "agents/harness-architect.md", "read_ranges": [{"start": 1, "end": 12, "raw_range_sha256": "c98bbd637148debe508161d1448d557c7798e2b676b2ccbbc80c38b07493c188"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-11"></a>

## scripts/tests/test_agent_outcome_audit.py

11892bytes / 331lines / fresh direct full-body read / `3e833bfceb47157a946f2bf4bdbcbaaa738d5d4b9e9959c3c3692e462c553a60`

1~331 전문(절단된 본문을 별도 전량 재독해). 9개 수동 테스트가 hook subprocess에 synthetic Agent response를 넣고 임시 ledger/budget/heartbeat를 검사하도록 작성됐다. free text만으로 success=True, 존재하는 'ok' marker로 evidence 성공을 기대한다. 이는 실제 작업·원문 의미·사람 인수의 성공 오라클이 아니다. env ORCH_CRITIC_DECISION='invoke'를 critic_invoked=True로 기록하는 시험도 실제 critic 호출 증거가 아니다. plagiarism case는 verified_by 문자열 포함만 보고 실패상태까지 검사하지 않는다. budget/heartbeat는 순차 누적 수만 검사하고 subprocess rc를 몇 case에서 생략한다. 전체 env 상속으로 ORCH_SID 등 다른 컨텍스트는 남고 임시 CLAUDE_HOME/PROJECT_ROOT는 sandbox가 아니다. ledger path는 SUT project_id_for를 재사용하며 손상 JSONL 줄을 조용히 제외한다. sys.path를 반복 prepend하고 복원하지 않는다. Zeus는 dispatch 관찰/response형식/의미검증/실제 reviewer/사람인수의 상태를 별도 PG receipt로 구분해야 한다. 실행0, SUT budget·heartbeat·audit 전이 폐쇄 pending.

Direct ranges: [{"path": "scripts/handlers/post_tool/agent_outcome_audit.py", "read_ranges": [{"start": 260, "end": 355, "raw_range_sha256": "4e9123f27078bf15170ab1f77ee7a1a1f9f34b3e4a470597fdc285a6aeccbb6e"}, {"start": 375, "end": 452, "raw_range_sha256": "70714f29865a25a49ed0aeb99b73402f36fbfe1b36a2a7921d34e117c162fdea"}]}, {"path": "settings.json", "read_ranges": [{"start": 242, "end": 254, "raw_range_sha256": "795a01516c5171402767cf055b79788e754e563d8a2f847cff92161dc80835d2"}, {"start": 262, "end": 274, "raw_range_sha256": "0be6f20118a55d152c8b0e0b4f7d9b7915832dbad5416d71f2172449131e333b"}, {"start": 294, "end": 306, "raw_range_sha256": "836abc7d5d7e897a8d10ab3c2b667b29ccd782d1facaa3ced677342939edf987"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-12"></a>

## scripts/tests/test_agent_tool_audit.py

12956bytes / 343lines / fresh direct full-body read / `8c3c1b827db8ed3555e536477a6789796e483b2a3cb3e9dbc513022e22fcc088`

1~343 전문. 28개 TESTS는 실제 repo agent frontmatter 몇 개 및 임시 markdown에서 tool 이름 parsing, self-report missing/used와 declared set 비교, advisory/severity 문자열, traversal 이름 거절을 검사한다. _AGENTS_DIR contextmanager 복원은 유효하다. unknown agent overclaim=[]와 clean severity에서 mismatch도 empty render를 명시적으로 허용한다. 이름/정규식 방어는 보존하되 declared≠effective available이고 도구 이름 언급≠실제 호출이다. live check라는 주석도 정적 frontmatter 조회이지 실제 WebFetch/WebSearch의 네트워크 검증이 아니다. invalidate 문자열/CANNOT 문구 검사는 downstream veto를 입증하지 않는다. 실제 agent 원문 및 SUT 직접 구간 추적 필요. Zeus에서는 runner 자격/허용 도구/실제 tool receipt를 구분하고 텍스트 self-report를 승인 권위로 만들지 않는다. OS path/Unicode 및 플랫폼 자격 미실행, 수동 실패/예외 rc1.

Direct ranges: [{"path": "scripts/lib/agent_tool_audit.py", "read_ranges": [{"start": 36, "end": 106, "raw_range_sha256": "bb99a6f575477e9cd2d4842a1b37331722c992308c200598ed7c2384b87c3d9d"}]}, {"path": "agents/harness-critic.md", "read_ranges": [{"start": 1, "end": 12, "raw_range_sha256": "ec1eec5abda77dff18957d530a033d1fe0f01ab649a51cee2eeb68dcc06f8432"}]}, {"path": "agents/harness-planner.md", "read_ranges": [{"start": 1, "end": 12, "raw_range_sha256": "0dd3e01d62964fdac2ef8f0d6fa73d59bd06a5ba436a830da6ee5c5269fbfb27"}]}, {"path": "agents/harness-architect.md", "read_ranges": [{"start": 1, "end": 12, "raw_range_sha256": "c98bbd637148debe508161d1448d557c7798e2b676b2ccbbc80c38b07493c188"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-13"></a>

## scripts/tests/test_agents_capability.py

3583bytes / 134lines / fresh direct full-body read / `8f4dbac35e6dac2134ad69db2f94339f016f47caa6d73250155562aec9a842cb`

1~134 전문. 11개 test_ 전역을 수동 호출하여 두 path token 탐지, format, expects_paths 삽입/중복변경없음/추가/삭제를 synthetic frontmatter로 검사한다. 실제 경로 존재·접근권한·agent 런타임은 검사하지 않는다. '.planning' 및 HOME 표현의 문자열 탐지와 실제 OS 경로 해석은 다르다. content 전체 보존, malformed/중복 YAML key, CRLF·Unicode, 쓰기 rollback은 미검사다. 변수 new를 일부 case에서 사용하지 않아 특정 삽입/업데이트 결과가 완전히 검증되지 않는다. Zeus는 기대 자산 선언과 실제 자격·artifact access receipt를 구분하고 문자열 스캔은 advisory 후보로 유지한다. SUT 지원 pending, 실행0, 오류 main rc1.

Direct ranges: [{"path": "scripts/cli/agents_capability.py", "read_ranges": [{"start": 51, "end": 118, "raw_range_sha256": "29f552a157f25cba183798f8eab4f465ff9bd24fb0a32b2f8cf54686cc6b8ba4"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-14"></a>

## scripts/tests/test_agents_normalize.py

3383bytes / 130lines / fresh direct full-body read / `d76dcbd6c4acf8be74cbc6744e8b20903d208846531aa18adb387cead5a086c4`

1~130 전문. 10개 test_ 전역 수동 호출로 모델 map24개와 opus/sonnet/haiku 분포, frontmatter 삽입/치환/멱등/unknown 및 no-frontmatter 무변경을 검사한다. 24개 및11/12/1 고정은 당시 설정의 스냅샷 오라클이며 실제 모델 존재·지원·성능·허용 예산·역할 자격을 증명하지 않는다. unknown과 malformed no-frontmatter 무변경도 승인된 배치 성공으로 보아서는 안 된다. 일부 검사 changed 및 substring만 확인하여 전체 YAML/본문 보존·파일 쓰기 side effect를 검증하지 않는다. Zeus에서는 모델 카탈로그와 실제 실행 자격을 revision/정책에 결속하고 이 매핑을 그대로 채택하지 않는다. Python/OS 인코딩·CLI 쓰기/rollback은 미실행이다.

Direct ranges: [{"path": "scripts/cli/agents_normalize.py", "read_ranges": [{"start": 78, "end": 112, "raw_range_sha256": "8fbabbca1be3c4cbae742676333c60198fc2cf3315f427a60b01a23a05d7bb3e"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-15"></a>

## scripts/tests/test_ai_spec_eval_coverage.py

8168bytes / 214lines / fresh direct full-body read / `6d9150948cfa1f87f1a1f1a33231a41b65420786ad64425ac608381603c286fc`

1~214 전문. 15개 수동 테스트는 manifest block/YAML parsing, 숫자 bool 거절, ID/중복/파일존재/비어있지않음, scan 및 advisory registry 제외를 검사한다. 1바이트 stub가 PASS임을 의도적으로 고정하고 golden_set_size는 실제 사례 수를 세지 않는다. fixture의 assert True 파일도 실행하지 않는다. no spec는 clean noop이고 graduation 기본false assertion은 읽는 state에 종속돼 hermetic 주장이 자동 성립하지 않는다. forbidden import 네 문자열 부재는 transitive 실행/network 부재의 보장이 아니다. empty failure modes 거절 및 bool 거절은 보존하되 finite float/허용경로/파일동일성/실제 평가결과는 더 검증해야 한다. Zeus SDD는 형식 참조 무결성과 실제 requirements/인수 evidence coverage를 분리하고 stub PASS를 승인으로 소비하지 않는다. source/test실행0, SUT/config 지원 pending.

Direct ranges: [{"path": "scripts/validators/ai_spec_eval_coverage.py", "read_ranges": [{"start": 124, "end": 176, "raw_range_sha256": "3c9e210f99c5e0c323b81ca160460a7653a53a923695c0d681cab24b7749904e"}]}, {"path": "scripts/validators/__init__.py", "read_ranges": [{"start": 1, "end": 83, "raw_range_sha256": "8cb043caa84080557c4ba69ed2a761961c52c76ae569bed8f0e1e549f7a2fa28"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-16"></a>

## scripts/tests/test_allsolution_metrics.py

3641bytes / 93lines / fresh direct full-body read / `4b797354f60992f0c1f9a29636e3640cb2f069cac126456a801cc6a41bf6e3aa`

1~93 전문. 네 함수가 mock.patch로 STATE_DIR를 임시 변경/복원하고 phase/status 저장, invalid 거절, 3개 synthetic run의 break rate, 빈 summary 안내를 검사한다. reached 분모는 fixture가 기록한 phase이며 전체 예정 단계/중단 전에 미도달한 항목의 완료율이 아니다. escalated를 broke와 같이 세고 skipped 저장은 성공한 event write지 단계 성공이 아니다. 중복/동시 기록·손상/순서/재실행 세대는 미검사다. 일부 record_phase 반환은 확인하지 않으며 실사용 빈도/신뢰구간/실제 자가개선 효과는 없다. Zeus PG 사건계수와 성공 인수를 분리하고 생성/attempt별 중복 제거를 요구한다. 수동 예외 rc1, 실행0.

Direct ranges: [{"path": "scripts/lib/allsolution_metrics.py", "read_ranges": [{"start": 80, "end": 112, "raw_range_sha256": "ba54018a5229a5e72d94aea88192abc1c309e8da5f81891f2f97e7f63213fe5c"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-17"></a>

## scripts/tests/test_ambiguity_report.py

3012bytes / 88lines / fresh direct full-body read / `126883dbed5707da975f23f04c812860a97ff8cc43b9f1ead89bb74440569653`

1~88 전문. 네 함수는 실제 scorer를 피한 duck _Score로 weighted contribution, dominant axis, delta, render substring을 검사한다. aggregate 감소와 한 축 regression 동시 존재를 improved=True로 기대하므로 모든 축 개선 또는 실제 모호성 해소를 뜻하지 않는다. render_round는 improved 또는 no change 어느 것이든 허용해 방향성 오류를 놓칠 수 있다. weights/threshold 일관성, NaN/Inf/결측/타입/동률은 검사하지 않는다. Zeus는 score를 interview 보조 지표로만 사용하고 실제 요구 확인과 사람 인수 상태를 별도로 둔다. scorer/calibration/OS 미실행, 지원 연결 pending.

Direct ranges: [{"path": "scripts/lib/ambiguity_report.py", "read_ranges": [{"start": 20, "end": 45, "raw_range_sha256": "99d814cc5e02dd36ae81487bb7a4ef179a54146b68f17479f99494840f0852d8"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-18"></a>

## scripts/tests/test_ambiguity_score.py

847bytes / 27lines / fresh direct full-body read / `2238e2c8ec9c663bc83d8fdc6f69666b6dbf453f9a8f64c9d1f1c5d20c53602d`

1~27 전문. main이 SUT inline _self_check를 부르고 비int 반환을0으로 바꾸는 wrapper이며 pytest test_ 함수가 없다. 문서의59 assertion은 이번 실행 수가 아니다. actual scorer 자기검사의 fixture 오라클, 예외 및 import 부작용은 지원 구간을 직접 읽어 구분해야 한다. 독립 모호성 검증·사용자 인터뷰 성공·모델 자격을 증명하지 않으며 source실행0. Zeus에서는 self-check wiring을 actual acceptance로 승격하지 않는다.

Direct ranges: [{"path": "scripts/lib/ambiguity_score.py", "read_ranges": [{"start": 455, "end": 689, "raw_range_sha256": "ab1c392758e04703a2756ca60d43b0bfcd13517b8527c7b92cebf807aef09306"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-19"></a>

## scripts/tests/test_assets_home_split.py

6460bytes / 152lines / fresh direct full-body read / `e632786b421ede0907bae8f291312c89133d2baefe563e63802eb50b3cb59894`

1~152 전문. 다섯 함수가 새 subprocess의 paths import 시점 상수 및 helper 결과를 JSON으로 받아 두 HOME 축 독립을 검사한다. 네 override를 제거하는 방어는 유용하나 나머지 env/global Python 설정은 상속하고 기본 probe는 실제 HOME 경로 값을 조회하도록 돼 있다. startswith 문자열 검사는 경로 containment가 아니며 실제 파일의 읽기 권한/쓰기 차단을 검증하지 않는다. 마지막 테스트도 디렉터리와 markdown 존재만 확인하고 본문 read는 없다. '읽기 자산' 분류는 read-only mount/ACL이 아니다. 동적으로 생성하는 -c raw 문자열 경로 quoting과 Windows/Unicode 경계는 미실행이다. Zeus의 Git 정의·PG runtime 구분 후보지만 live 원본 조회 없이 hermetic snapshot fixture로 변형해야 한다. 수동 오류 rc1, 이번 probe실행0.

Direct ranges: [{"path": "scripts/lib/paths.py", "read_ranges": [{"start": 12, "end": 110, "raw_range_sha256": "7f9192b09d7f5d4d6d5f61832330c15c8b465f2ef391bc9bfe8d0ed26899b7e8"}, {"start": 145, "end": 158, "raw_range_sha256": "53614df85db3d4410393ed53f5d1e849447a5852c659f2b43d8617f7043426dc"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-20"></a>

## scripts/tests/test_atlas_frontmatter.py

3620bytes / 115lines / fresh direct full-body read / `3b9d5996a4ab75b4d4d1bd394241305bdd8caf385ae76635ebc75956ea7c6b87`

1~115 전문. 여섯 함수는 synthetic note 파일의 frontmatter 없음, valid, 필수status 누락, enumtype, badID warning, glob누락을 검사한다. main scan 범위/ATLAS_DIR없음 skip·telemetry·exit policy는 검사하지 않는다. 빈값/중복키/YAML 타입/created-updated 일관성/본문내용/링크원문도 미검사다. warning과FAIL을 구분하는 오라클은 보존하되 형식청결을 의미 또는 사람승인으로 승격하지 않는다. 주석의 run_units 자동수집 주장은 실제 validator registry membership에 따라 run_all로 라우팅될 수 있다. Zeus는 source artifact schema와 인수 coverage 분모를 분리한다. 실행0, validator 지원 pending.

Direct ranges: [{"path": "scripts/validators/atlas_frontmatter.py", "read_ranges": [{"start": 60, "end": 142, "raw_range_sha256": "b7fe53fb3a3e224f1bb1c5ed7f586f9958626b2a50efd53df259e49f2c80ec0b"}]}, {"path": "scripts/validators/__init__.py", "read_ranges": [{"start": 1, "end": 83, "raw_range_sha256": "8cb043caa84080557c4ba69ed2a761961c52c76ae569bed8f0e1e549f7a2fa28"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-21"></a>

## scripts/tests/test_atlas_structure.py

2719bytes / 80lines / fresh direct full-body read / `9883053dc6050c2aaa3f70e9ddaf037ad6a8a39854c9a591aea75a8084e4aa0f`

1~80 전문. 세 함수가 _system/archive 분류, 폴더깊이0/2/3, markdown 한정 listing을 검사한다. main의 레이아웃 정책/실제 archive 제외와 전체 실패분모를 검사하지 않는다. names dict/set은 같은 이름의 다른 경로를 합칠 수 있고 case 확장자/symlink/권한오류/깊이폭발은 미검사다. helper fixture가 'pure'라 해도 temp tree 읽기와 filesystem동작을 포함한다. Zeus에서는 taxonomy 인덱스 보조로만 쓰고 SDD 문서 의미/실제자산 검증과 구분한다. 실행0, OS/전체caller 폐쇄 pending.

Direct ranges: [{"path": "scripts/validators/atlas_structure.py", "read_ranges": [{"start": 65, "end": 95, "raw_range_sha256": "71882348e066cb67cd7e86da51d0109448b3ddf4d4a7fbe154a969d7b75642ff"}]}, {"path": "scripts/validators/__init__.py", "read_ranges": [{"start": 1, "end": 83, "raw_range_sha256": "8cb043caa84080557c4ba69ed2a761961c52c76ae569bed8f0e1e549f7a2fa28"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-22"></a>

## scripts/tests/test_atomic_json.py

8950bytes / 237lines / fresh direct full-body read / `da0171daab1c67fe77a259637744ecddf9ee4409b26fd9337f4cb925354c981d`

1~237 전문. 16개 test_ 함수가 missing/corrupt/type 기본값, UTF8/ASCII, overwrite/임시잔여/실패 및 열린 reader retry를 검사한다. corrupt를 empty로 보는 계약은 저장 복구와 정상 빈 상태를 구분하지 못하므로 승인 gate엔 그대로 채택하지 않는다. transient reader는 sleep 동기화라 실제 lock 겹침이 보장되지 않고 stuck-reader는 probe가 False면 그냥 return하여 main 및 pytest가 PASS로 셀 수 있다. bounded assertion도 상수만 검사하고 실제 elapsed/트리종료 측정이 아니다. shared retry 우회 검사에서 AST/read오류 파일은 continue하며 tmp라는 변수명의 .replace 토큰만 탐지하므로 다른 변수/os.replace/alias를 놓친다. module docstring 단순 replace와 tokenize도 전체 dataflow 오라클이 아니다. crash/fsync/동시 RMW·CAS/permission 보존은 미검사다. Zeus PG 정본·stale write 방어를 이 파일 원자replace 시험으로 대체할 수 없다. 실행0, Windows/POSIX 주장은 fixture 설계이며 실제효과 미확인.

Direct ranges: [{"path": "scripts/lib/atomic_json.py", "read_ranges": [{"start": 30, "end": 127, "raw_range_sha256": "bbf18d9c35c5a1685043b38ae1a038f1dd302b89c4c6091f64c1782acbd6b77d"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-23"></a>

## scripts/tests/test_autopilot_compaction.py

3330bytes / 90lines / fresh direct full-body read / `25e884e91d3ec2a06c1b7a2fb6a601fdfd9b24a1fcc6cb7b2b3e96949616b748`

1~90 전문. 여섯 함수는 _ok가 실패를 global _FAILS에 append하는 방식이고 assert/raise하지 않아 pytest 직접 실행은 실패 조건도 test PASS가 될 수 있다(main만 누적을 rc1로 반영). _FAILS를 main 시작에 비우지 않아 반복 실행도 이전 실패가 남는다. byte-identical 테스트는 None/parts길이일 뿐 실제 caller 출력 바이트 비교가 아니다. _simulate는 wire를 복제하여 원래 Stop hook과의 실제 연결이 없고 directive 문구가 안전캡 불변이라 해도 cap 동작을 검사하지 않는다. 실제 context compact/복구/지속성/토큰량은 미검사다. Zeus는 immutable checkpoint handoff와 stale authority를 실제 executor에 검증해야 하며 모델 지시문을 완료로 보지 않는다. source실행0, SUT/caller 지원 pending.

Direct ranges: [{"path": "scripts/lib/autopilot_compaction.py", "read_ranges": [{"start": 26, "end": 58, "raw_range_sha256": "a2a5a1061d14448dddcdcb5d917730d9f91d101e4a6c85ca59a63c5f00d93bc2"}]}, {"path": "scripts/handlers/stop/autopilot_continue.py", "read_ranges": [{"start": 238, "end": 249, "raw_range_sha256": "85f3be0bce7e8e1e4fe995274f73da86938cef2bdebe1bb6fbcee9b01bfdfcc9"}, {"start": 627, "end": 701, "raw_range_sha256": "f6dd07339e38f52eb7ec5179eeffcb62b995025c4a38a4bef1ee76c958564e22"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-24"></a>

## scripts/tests/test_autopilot_continue.py

23780bytes / 649lines / fresh direct full-body read / `c202b3571f77bd7e06127196aa36ad9e2bd369ffaeec7b820786b61104f0907d`

1~649 전문. 24개 TESTS에 parser synthetic strings, hook subprocess noop, in-process 상태/출력, shared sid evaluator freshness, helper 예외 fail-closed, capture stream import 안전이 있다. malformed/nonobject 거절과 stale/missing evaluator 및 helper 실패에 완료를 막는 기대는 보존한다. 그러나 'ground truth' happy path도 model tag의 validators/tests true와 수동 axis_scores approved 기록이며 실제 validator/test/독립 evaluator 또는 사람 인수 실행은 없다. standalone sid는 tag만으로 done을 기대한다. 10초 subprocess helper는 전체 env를 상속하고 CLAUDE_HOME을 격리하지 않으며 silent_when_no_active는 실제 상태를 볼 수 있음을 인정하고 stdout조차 assert하지 않는다. payload.cwd는 subprocess cwd 또는 권한 격리가 아니다.

STATE_DIR/ORCHESTRATOR_DIR global 변경은 복원하지 않고 stdin/out만 finally복원한다. SystemExit의 모든 code를 무시한 뒤 state/substring을 검사하므로 종료계약 오류가 숨을 수 있다. shared helper는 fresh ts를 직접 floor+1로 써서 미래 시각·source revision·artifact 변조/중복 이벤트를 검증하지 않는다. one optional monkeypatch 인수는 runner regex가 pytest로 라우팅할 수 있고 autouse fixture와 수동 main의 의미가 다르다. header retry json_error 증가 주장은 parser오류분류 외 실제 counter증가 검사가 없다. Zeus는 문자열결정 대신 PG 세대·attempt·독립검사receipt/실제인수를 결속하고 Stop은 계속/중지 관찰로 분리한다. source실행0, 전체 hook/engine전이는 지원한 구간 밖 pending.

Direct ranges: [{"path": "scripts/handlers/stop/autopilot_continue.py", "read_ranges": [{"start": 238, "end": 249, "raw_range_sha256": "85f3be0bce7e8e1e4fe995274f73da86938cef2bdebe1bb6fbcee9b01bfdfcc9"}, {"start": 627, "end": 701, "raw_range_sha256": "f6dd07339e38f52eb7ec5179eeffcb62b995025c4a38a4bef1ee76c958564e22"}]}, {"path": "settings.json", "read_ranges": [{"start": 242, "end": 254, "raw_range_sha256": "795a01516c5171402767cf055b79788e754e563d8a2f847cff92161dc80835d2"}, {"start": 262, "end": 274, "raw_range_sha256": "0be6f20118a55d152c8b0e0b4f7d9b7915832dbad5416d71f2172449131e333b"}, {"start": 294, "end": 306, "raw_range_sha256": "836abc7d5d7e897a8d10ab3c2b667b29ccd782d1facaa3ced677342939edf987"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-25"></a>

## scripts/tests/test_autopilot_flip_policy.py

8625bytes / 228lines / fresh direct full-body read / `a439d3b554f5530204cf28a7b145aab20b91c384eaef9de6b057e4579febf7b9`

1~228 전문. 12개 수동 TESTS는 default literal0/int, invalid입력, 파일 append/카운터 coercion/extra 및 real telemetry path라고 부르는 임시파일 쓰기를 검사한다. 원격/실제 autopilot/pane 자연 trigger가 아니라 직접 호출한 local fixture이며 rotation도 실제 발생을 검사하지 않는다. paths와 telemetry_log global을 바꾸고 복원하지 않는다. timestamp는 Z/T 포함만 검사하고 actual 시간/정확 event일치가 아니다. status semantic enum/negative·NaN counters/kwargs reserved override/동시write·실패전파는 미검사다. Zeus는 과거 실행횟수/성공로그만으로 병렬 default를 승격하지 않고 실제 세대별 독립 검증과 승인에 결속한다. 실행0, 실제 OS모델/정책효과 pending.

Direct ranges: [{"path": "scripts/lib/autopilot_flip_policy.py", "read_ranges": [{"start": 32, "end": 67, "raw_range_sha256": "73b875a1d0c8b09b84b32d583dde23320685b8fa4268fe0a2f01bb670ceee99e"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.

<a id="file-26"></a>

## scripts/tests/test_autopilot_kha_bridge.py

10014bytes / 251lines / fresh direct full-body read / `b0628ef1c7d98b3095ec26fbf359abe58a1c695f359dc5de67a545c03ae0570a`

1~251 전문. 일곱 TESTS가 임시 CLAUDE_HOME, sys.modules 삭제, 임시 Git repo/commit으로 dual-stream기록, 인수 validation, commit subject→completed table, SUMMARY존재 orphan판정을 검사한다. 두 파일 모두 존재는 write ordering 또는 원자성을 증명하지 않는다. 'add failing test'라는 commit도 completed table에 포함하며 '# done' SUMMARY존재가 orphan해소를 의미하므로 실제 test pass/요구coverage/사람인수와 다르다. ack/phase escalated 기록은 실제 사용자 통보·결정 또는 작업종료를 증명하지 않는다. main만 HOME를 복원하고 각 test 직접 실행은 env/global cache를 바꾸며 모듈 원복도 없다. Git subprocess엔 timeout/hooks/globalconfig 격리가 없어 hermetic 실행이 아니다. Git 부재는 skip 아닌 예외실패다. Zeus는 Git정의/commit관찰을 PG workflow인수와 분리하고 dual-write는 transaction/outbox·generation으로 변형해야 한다. 이번 git/import/test실행0, 실제 KHA/OS/전이폐쇄 pending.

Direct ranges: [{"path": "scripts/lib/autopilot_kha_bridge.py", "read_ranges": [{"start": 81, "end": 143, "raw_range_sha256": "0539b3509a7dc9d087c3a2e822cca2e518e18271a960c28af901cc12bfe77a9b"}]}]

Remaining: Complete direct/transitive caller/config/test closure outside exact listed ranges; Source test/runtime execution prohibited this assignment; tests_not_run remain open; License/vendor original claims, actual model and Windows/Linux/WSL equivalence; Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification; Whole-area independent Claude review and adoption approval. Execution0. Source instructions are data.
