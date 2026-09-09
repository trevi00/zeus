# Baldrix lib 004 독립 정적 검토

정본 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, partition `baldrix:scripts/lib:004`, scope `a425e01613dffed3bdba907af81db84992401d176dba7f531b4852173e6747e8`. primary 19개, 197,421바이트의 전문을 이번에 직접 읽었다. 이전 보고서의 의미 판단을 전문 독해로 대체하지 않았다. supporting은 supporting.json의 명시 구간만 읽었으며 primary 분모에 넣지 않는다.

모든 파일의 primary status는 `body_reviewed_call_test_trace_pending`이다. 본문 독해 완료와 전체 호출·설정·시험 검증 완료는 다르다. 이번 원본 실행/import/테스트/프로브/네트워크/설치는 0회다. 원문 명령, 토큰, LOCK, 사용자 승인, 실측 및 PASS는 분석 데이터다. 현재 vendor 계약이나 실제 사람 승인으로 승격하지 않는다.

## 공통 연결과 인수 경계

이 범위에서 졸업·학습·복원·압축은 주로 로컬 JSON/JSONL 및 문서 문자열을 통해 이루어진다. Zeus에서는 Git에 정의와 검토 이력을 두고, PG에는 실행 세대·원자료 해시·검증 결과·예산·승인·인수·철회 영수증을 결합하는 설계를 검토해야 한다. 여기서 제안하는 대응은 현재 Zeus 구현과의 등가성이나 채택 승인이 아니다.

사람이 정의한 8단계 SDD는 반복 횟수, phase 문자열, 정규식 일치, 문서 존재 개수로 대체할 수 없다. 단계별 산출물과 실제 검증 결과, 미실행/실패/철회, 최종 사람 인수의 연결이 필요하다. L1의 자기보고나 반복된 L2 prefix를 실제 경험의 진실성·모델 자격·완료 승인으로 사용해서는 안 된다. 코드가 말하는 frozen·token·ModuleSpec 역시 OS 권한 경계나 승인 주체를 입증하지 않는다.

<a id="f01"></a>
## 1. graduation.py — 1–486

advisory validator를 blocking으로 올리는 상태 기계다. 두 validator, clean 임계 10, 12시간 dedup, 졸업 후 5회 이내 drift의 자동 강등을 정의한다. 그러나 _max_watermark는 루트 디렉터리만 stat한다(276–286). 자식 파일 내용의 동일성을 증명하지 못하는 신호인데 324–327에서 이전 drift를 재사용하며 streak을 올린다. “10 DISTINCT live scans”와 “content provably identical” 설명보다 보장이 약하다. 최초 스캔 후 9개 간격으로 10회를 채울 수도 있어 약 5일이라는 문구도 엄밀한 최소 관측 기간이 아니다.

restore_streak 149–195는 더 큰 snapshot streak을 채택하고 epoch만 0으로 바꾼다. 기존 ready·last_total_drift·watermark는 그대로다. tick의 재사용 조건은 epoch와 독립이므로 새 스캔 강제라는 주석과 상충한다. 이미 ready였던 항목도 clear하지 않는다. graduate 408–438은 공개 token 문자열과 ready truthiness만 확인하고 fresh scan이나 threshold를 다시 확인하지 않는다. 실제 CLI 129–140도 바로 graduate를 호출하고 성공 메시지를 낸다. test_graduation 88–103은 epoch=0인데도 scan을 호출하지 않는 것을 기대하며, 176–187은 streak 없이 ready만 넣어 졸업시킨다. 테스트 존재가 이 약한 조건을 강화하지 않는다.

save_state 실패 bool을 graduate/demote/restore/tick이 확인하지 않고 flag·state·history를 별개로 쓴다. 고정 tmp 이름과 read-modify-write는 동시 호출 전체 원자성을 보장하지 않는다. STATE_DIR는 import로 잡은 값인데 “never module-level captured”라는 설명이 있다. validators registry 74–84도 import 시점 목록이다. graduation.py의 “scheduler 없음” 설명은 scheduler_driver 150–155의 실제 tick 등록과 상충한다. Zeus 대응: 원자료 revision별 새 검사 영수증, 고유 실행 수, 신뢰된 사람 승인 및 한 트랜잭션의 상태/이력/flag 전이가 필요하다. 현재 동시성·복원·host 동작 재현은 하지 않았다.

<a id="f02"></a>
## 2. graduation_audit.py — 1–130

append 기록의 action/validator/최근 token/분포를 보여주는 읽기 도구다. CLI history 84–126이 실제 소비한다. 잘못된 JSON·비객체·읽기 실패를 버리거나 빈 목록으로 접으므로 total_records는 성공적으로 읽힌 행의 수이고 모든 실제 flip의 수가 아니다. 원본 writer가 기록 실패를 삼키므로 “누가 무엇을 바꿨는가”라는 설명과 달리 token 문자열만으로 행위자를 증명하지 않는다. 시각을 비교하지 않고 append 마지막 행을 최신으로 간주한다. “현재 trail 비어 있음”은 역사적 서술이다. Zeus 대응: 누락/손상 수와 승인자·커밋 영수증을 포함한 감사 view. 독립 audit 시험 및 실제 원장은 읽지 않았다.

<a id="f03"></a>
## 3. ground_or_drop.py — 1–87

atlas의 존재 여부로 claims를 분류한다. named_repo가 known-absent이면 우선 deficit으로 보내고, 알려진 repo/seam 참조는 kept, 미해결은 기본적으로 kept_unresolved다. 이 코드는 참조의 존재만 보며 정확성·사람의 승인을 확인하지 않는다. absent 집합은 nodes의 present=false에서만 오므로 manifest에 전혀 없는 이름이 자동으로 absent가 되지 않는다. seam 양끝이 실제 present인지도 여기서 검증하지 않는다. forces_deficit는 rerouted_absent만 본다.

meeting_ingest 47–78은 draft claims를 그대로 받아 기본 defer=true로 호출하고 deficit만 coverage에 넘긴다. --draft의 “human-approved” 도움말은 인증된 승인 검사가 아니다. --phase2도 실제 atlas 비율을 자동 확인하지 않는다. bundle/coverage 전체 closure는 미검증이다. Zeus 대응: 미해결 주장 보존은 유용하지만 수용/승인은 별도 PG 상태여야 한다. 예상 이름 test_ground_or_drop.py는 없었으며 다른 시험 전수 검색·독해는 완료하지 않았다.

<a id="f04"></a>
## 4. guard_patterns.py — 1–307

DENY/WARN/명령 자동 보정/민감 경로 규칙을 데이터로 분리했다. 실제 guard 213–243은 첫 DENY를 처리하고 solo_override면 경고 후 종료하며, 이후 첫 autocorrect를 적용한다. 패턴은 shell AST·프로세스 권한이 아닌 문자열 검사다. company 경로 규칙도 데이터 자체에 company-mode 조건이 없다. 주석에 적힌 프로젝트별 적용을 그 규칙만으로 확인할 수 없다. 자동 보정은 문자열 전체에서 --no-verify를 제거하므로 quoted data와 실제 옵션을 구별하지 않는다.

guardian의 명시적 제외와 미보호 범위는 source가 인정하는 한계다. 인용 heredoc 경고의 과거 실험·TP/TN·전송 손상 서술은 이번 측정이 아니다. test_guard_patterns 162–187은 인용된 입력에서 경고하지 않는 오라클을 포함한다. Zeus 대응: 사람이 정한 권한 정책을 typed operation으로 적용하고, 문자열 경고를 OS 차단 영수증으로 사용하지 않아야 한다. 정책 전체 우회 탐색·실행 시험은 하지 않았다.

<a id="f05"></a>
## 5. handoff_drift.py — 1–442

Current Phase Block YAML을 phase_tree로 바꿔 시각화와 drift를 비교한다. alias, step 문자열 상태 토큰, deepest in-progress, step 수 분모를 처리한다. 이 분모는 문서 step 수이며 실제 실행·SDD 단계 완료 수가 아니다. code_blind_readiness는 정확한 fence가 없으면 opt-out True, parse 가능하면 in-progress 노드가 없어도 True다. “재개 가능”은 여기서는 문서 파싱 가능 수준이다. 다른 advisory 함수는 parse 실패를 None으로 돌려 정상과 같은 침묵이 된다.

promote_sub_phase 272–390은 텍스트를 재구성한다. 들여쓰기가 target보다 깊기만 하면 step을 잡으므로 이미 중첩된 다른 구조의 step도 포함할 여지가 있다. 기존 sub_phases에 새 키를 붙이거나 multiline/인용 값을 처리하는 전체 문법 보장이 없다. DONE 접두사 추론과 _step_status_token의 단어 판정도 다르다. phase_tree 251–278은 알 수 없는 상태를 in_progress로 바꾸며 evidence를 문자열 자료로 운반할 뿐 검증하지 않는다. Zeus 대응: 문서 projection과 PG 실행 상태를 분리하고 문서 정규화가 완료 판정을 만들지 않도록 해야 한다. PyYAML import·render·쓰기·외부 validator는 실행하지 않았다.

<a id="f06"></a>
## 6. handoff_surface.py — 1–61

프로젝트 HANDOFF 앞 4,000바이트를 UTF-8 ignore로 해석한다. 읽기 출력 상한은 있지만 read_bytes로 파일 전체를 메모리에 읽은 뒤 자른다. 양수 max_bytes 검증이 없고 잘린 YAML/명령/근거의 완결성을 보장하지 않는다. SessionStart 108–127은 상수를 쓰면서 별도의 bounded read를 구현한다. 따라서 helper가 유일한 실제 읽기 경로라는 설명은 그대로 성립하지 않는다. source의 5,036바이트 실측은 역사적 주장이다. Zeus 대응: 복원 projection에 truncation·원본 hash·남은 범위를 표시하고 앞부분만으로 권한/완료를 인수하지 않아야 한다. host의 실제 주입 결과는 미검증이다.

<a id="f07"></a>
## 7. harness_audit.py — 1–125

IMPACT 축별 파일/줄/설정 개수를 계산한다. commands/harness-audit 55–65가 이 숫자를 LLM 점수 근거로 쓰라고 안내한다. 존재 개수는 품질·실행 효과·권한 강제의 증거가 아니다. Memory는 brain snapshot 경로를 읽으므로 live memory와 다를 수 있고, validators_count는 전달받은 home 대신 전역 SCRIPTS_DIR를 써 다른 루트를 혼합할 수 있다. 오류를 0/False로 접어 부재와 미수집을 구분하지 않는다. allow/deny의 list 스키마도 완전히 검사하지 않는다. Zeus 대응: inventory 지표를 수집 범위/상태와 함께 내고 실제 검증·자격·인수는 별도 영수증으로 요구해야 한다. audit 점수나 전체 스캔을 실행하지 않았다.

<a id="f08"></a>
## 8. heartbeat.py — 1–176

SID별 파일 시각/count를 갱신하고 stale/list/prune을 제공한다. 문자 제거 방식 SID 정규화는 다른 원본 SID를 같은 파일로 합칠 수 있다. 미래 timestamp는 age 음수로 active가 되고 naive timestamp는 host 시간대 영향을 받는다. read-modify-write count에는 세대/소유자 fencing이 없고 prune과 새 emit 경합도 별도 처리하지 않는다. 활성 파일은 실제 worker 생존이나 lease 소유 증거가 아니다.

heartbeat_check 53–74는 timestamp 누락/손상을 건너뛰어 stale(sid)의 True 정책과 다르다. 36–42의 emitter는 존재하지 않는 event_store module-level append를 import하고 예외를 삼킨다. event_store 1–117을 새로 읽어 클래스 메서드만 있음을 확인했다. 따라서 stale 발견과 이벤트 저장 성공은 분리해야 한다. Zeus 대응: PG lease 세대·owner·heartbeat 영수증·누락 상태. 실제 heartbeat 자동 발행자 전체와 알림 전달은 미검증이다.

<a id="f09"></a>
## 9. hook_io.py — 1–138

stdin JSON, stdout JSON, 추가 컨텍스트, Stop/PreTool response를 만든다. import 시 UTF-8 재설정을 시도하며 실패를 삼킨다. “Windows UTF-8 보장”은 재설정 실패까지 포함한 절대 보장이 아니다. 입력은 크기 제한 없이 읽고 잘못된 데이터는 {}로 바꾼다. Literal 타입은 runtime event schema 검증이 아니다. 빈 output은 무출력이고 Stop block=False/continue=True도 무출력이 된다.

mode_detector 120–133은 additional_context를 실제 출력하지만 모든 예외를 exit 0으로 바꾼다. JSON 생성과 host가 이를 수용·강제했다는 사실은 다르다. source의 vendor schema 설명은 현재 vendor 사실로 확인하지 않았다. Zeus 대응: adapter별 schema/version·오류/전달 영수증 및 플랫폼별 host 검증이 필요하다. 원본 import와 hook 실행은 하지 않았다.

<a id="f10"></a>
## 10. hook_latency.py — 1–167

합성 probe 전용 채널을 분리해 실제 timed telemetry와 혼합되는 과거 문제를 줄였다. 1,221/1,213/8행 서술은 이번 실측이 아니다. record는 행 수를 반환하지만 trim은 전체 파일 read/write이고 동시 append 보존 트랜잭션이 없다. 변환 오류는 try 이전에 발생하며 음수/NaN·중복 실행·host version 검증은 없다. 최근 20개와 이전 중앙값은 유용한 분모지만 같은 이름의 서로 다른 host/코드 버전이 섞일 수 있다. 추세 상승만으로 원인이 “우리가 무겁게 만든 것”이라고 확정할 수 없다.

cron probe_once 44–72는 golden_signals의 non-None value를 모두 저장한다. 실제 golden_signals 182–215는 실패 횟수를 warn/detail에만 넣고 total 값은 유지하므로 실패/timeout 표본도 이름·ms만 남아 성공 표본처럼 추세에 섞일 수 있다. 실제 home/scripts에서 300초 subprocess를 실행하며 별도 env 격리가 없다. “한가한 기계에서 격리”라는 설명은 이 호출의 보장이 아니다. settings SessionStart의 5초 timeout과도 다르다. Zeus 대응: probe의 코드/host/실패/timeout·관측 창을 보존해야 한다. probe는 실행하지 않았다.

<a id="f11"></a>
## 11. import_graph.py — 1–327

AST import·문자열 registry·문서·경로·test 표면을 분리하는 정적 후보 도구다. 모듈을 실행하지 않는 구현이지만 이번에는 이 분석기도 실행하지 않았다. .wired는 실제 production 진입점에서의 전이 closure가 아니라 test 외 한 참조가 있다는 뜻이다. 호출되지 않는 모듈의 import, 주석/설명 속 파일명, 문자열 상수도 표시될 수 있다. basename 충돌은 setdefault의 첫 항목이 이기고 referrers는 5개로 잘린다. 읽기/파싱 실패는 생략된다. 모든 동적 호출을 해석하지 못한다.

dashboard_model 146–162는 test_only와 unreferenced를 각각 호출하므로 전체 스캔을 두 번 할 수 있다. “미배선 21개” 등의 수치는 과거 서술이다. Zeus 대응: 삭제 후보 탐색에 쓰되 inventory/참조 존재를 실행 도달성으로 승격하지 않고 실제 caller 구간을 남겨야 한다. 그래프 전체 비교·성능·fixture 시험은 미실행이다.

<a id="f12"></a>
## 12. insight_index.py — 1–436

L1에 요약·correlation·source_module·선택 body_ref를 append하고 별도 tombstone으로 철회한다. writer 허용은 제공된 source_module 문자열이며 문서도 advisory임을 인정한다. caller 불명 시 금지 집합 검사도 열리고 query에는 해당 runtime 검사 호출 자체가 없다. ModuleSpec의 이름은 신뢰된 actor 영수증이 아니다. ID 충돌 검사는 프로세스 최근 1,024개뿐이고 내용 중복 방지가 아니다. timestamp int 검사는 bool도 허용한다. overflow rejection의 저장 실패는 삼킨다.

query(limit=0)는 [-0:]라 전체를 반환한다. cache의 mutable row를 그대로 돌려줘 소비자 수정이 후속 query에 보일 수 있다. 철회는 대상 존재/원자료/사람 승인 확인 없이 기록된다. learner 120–184는 마지막 assistant message를 170자로 접어 work_unit_digest로 쓰고 body_ref=None으로 남긴다. 저장 return None을 확인하지 않은 채 digest emitted 표시로 진행할 수 있다. 이 요약은 실제 경험 성공 영수증이 아니다. Zeus 대응: 원자료 hash·run ID·실측/자기보고 구분·저장 확인 및 철회 provenance. AST whitelist 전체·SLO 시험은 미검증이다.

<a id="f13"></a>
## 13. insight_index_pollution_detector.py — 1–257

250ms bucket에 3개 이상인 행을 후보로 삼고 correlation 경로가 없으면 “confirmed”로 분류한다. 고정 bucket 경계는 짧은 burst를 분할할 수 있고, calibration은 source/event별 occupied window를 분모로 쓰지만 후보 군집은 전체 행을 섞어 센다. 파일 존재는 실행의 사실성·자격을 증명하지 않으며 다른 컴퓨터에서 복원한 정상 경험도 현재 경로가 없을 수 있다. 반대로 임의 경로가 존재하면 통과한다. correlation 경로 자체의 프로젝트 containment도 확인하지 않는다.

CLI measure 54–99는 조정값을 snapshot에 적지만 ready flag에는 validated만 쓰고, detect 111–156은 기본 250/3을 계속 쓴다. 조정 후 ratio를 재확인하지 않는 분기도 있다. execute 중 일부 retract 실패가 있어도 flag를 지우고 exit 0을 반환한다. 따라서 측정 승인·계획·실제 철회 영수증이 묶이지 않는다. Zeus 대응: 오염은 검토 후보로 유지하고 확정 철회는 원자료·계획 hash·사람 인수와 결합해야 한다. threshold 실측/철회 실행은 하지 않았다.

<a id="f14"></a>
## 14. intent_doc_floor.py — 1–69

정규식으로 YAML 모양의 signal_summary와 provenance 개수를 비교한다. inferred<=cited와 빈 file 문자열만 확인하며 원본 파일 존재·line 범위·claim 관련성은 확인하지 않는다. line=0도 regex에 맞는다. provenance 정규식에 맞지 않는 잘못된 행은 검출 대상에서 사라질 수 있고, 0개 skeleton은 빈 성공이다. 재계수도 extractor의 라벨을 다시 읽는 것이므로 독립 의미 검증이 아니다.

reverse_engineer 187–227은 write 후 floor 실패 시 이전 내용 복원을 시도하지만 no_roundtrip이면 floor를 건너뛴다. 파일 쓰기와 검사/롤백의 전체 원자성은 보이지 않는다. Zeus 대응: SDD 역설계 산출물의 provenance 표면 검사로만 쓰고 원문 구간 독해와 인수는 별도로 요구해야 한다. 예상 이름 test_intent_doc_floor.py는 없으며 대체 probe 시험 본문은 이번에 읽지 않았다.

<a id="f15"></a>
## 15. jsonl_cache.py — 1–65

mtime_ns/size를 키로 caller별 cache를 유지한다. 파일 손상·비객체는 건너뛰고 읽기 OSError 중간이면 부분 결과를 반환하되 cache하지 않는다. 반환값에 partial/corrupt 수가 없어 상위 기억 조회는 완전한 목록처럼 사용할 수 있다. 같은 mtime/size가 반드시 같은 내용이라는 계약은 외부 복원·동일 크기 덮어쓰기·mtime 보존을 포괄하지 않는다. 조회한 동일 list/dict를 소비자가 수정할 수 있다. UnicodeDecodeError 등 모든 오류를 잡는 것도 아니다.

test_jsonl_cache 25–70은 손상 행 생략과 같은 객체 반환을 의도적으로 기대하고 정상 append에 의한 size 변경을 확인한다. 동시 읽기/복원/수정 격리는 그 구간의 오라클에 없다. L1/L2가 이 helper를 직접 호출한다. Zeus 대응: immutable projection, 명시적인 수집 상태와 source revision. 실제 성능/플랫폼 시험은 미실행이다.

<a id="f16"></a>
## 16. l2_facts.py — 1–575

SPO 내용 hash ID, confidence, evidence sidecar, retraction을 제공한다. 동일 ID의 여러 행을 latest-wins로 접지만 물리적 append는 계속된다. confidence는 caller가 준 support_count 함수이며 사실의 정확도나 독립 증거의 확률이 아니다. object_datatype enum은 object 실제 타입과 대조하지 않고 source_module 문자열도 실제 caller 이름과 일치시키지 않는다. writer frame whitelist에는 시험 모듈도 들어 있다. in-process 검사와 이름은 OS 주체·모델 자격의 인증이 아니다.

query(limit=0)는 전체를 반환한다. evidence 추가는 대상 fact/L1 존재·중복·철회 상태를 검사하지 않고 fact append와 별도 파일에 쓴다. is_insight_floor 521–545는 모든 edge 수와 correlation 종류를 세며 L1 철회/중복 ID를 제거하지 않는다. “distinct sessions”는 correlation 값이 실제 session인 경우에만 의미가 있다. 이 함수가 모든 읽기 경로에 자동 적용되는 것도 아니다. Zeus 대응: PG 외래키·unique evidence edge·활성 원자료 기준 분모·독립 세션/실행 증거와 사람의 승격 승인. 전체 reader injection과 권한 시험은 미검증이다.

<a id="f17"></a>
## 17. l2_promoter.py — 1–364

현재 eligible은 skill_candidate/orchestrator이고 그룹은 source/axis/event/summary 앞 30자다. 상단의 wonder/debate/evaluator·correlation 그룹 설명과 다르다. 30자 뒤의 반례/부정/실패 맥락이 사라져 다른 경험이 합쳐질 수 있다. correlation을 session proxy로 쓰므로 실제 독립 세션 증명이 아니다. 입력 ID 중복도 group 크기에 포함되고 timestamp가 모두 없으면 wallclock을 사용해 모든 입력에 대해 순수 결정론이라는 설명은 성립하지 않는다.

promote_all은 매번 fact와 모든 evidence를 다시 append한다. “재실행 0 new facts” 설명과 facts_emitted 증가가 다르다. test_l2_promoter 263–275는 ID 집합만 비교하며 물리 행/evidence 중복을 검사하지 않는다. cascade 323–364는 unique L1이 아닌 edge 행을 세고 L1 존재를 확인하지 않는다. 동일 3개 근거를 두 번 승격한 뒤 하나를 철회하면 나머지 2개 근거의 edge 4개가 threshold를 넘길 수 있다는 정적 경로가 있다. read floor도 철회된 edge를 세므로 두 계층이 독립 증거 수와 어긋난다. 증거 0개 fact는 cascade에서 건너뛴다.

L2 append 후 evidence 일부 실패는 원자적으로 되돌려지지 않는다. cron 158–181은 예외가 없으면 ack/consume/reset을 진행하므로 evidence 누락이 완료와 함께 남을 수 있다. 기본 도출 함수의 auto-OK 주석은 현재 사람의 인수 승인과 다르다. Zeus 대응: candidate/검증/승격을 분리하고 증거 uniqueness·철회 전파·트랜잭션 영수증 및 실제 경험의 반례를 보존해야 한다. 이번 재현·cron 실행·실제 학습 효과 측정은 없다.

<a id="f18"></a>
## 18. ledger_compaction.py — 1–80

task_hash별 문자열 timestamp의 최신 행을 남기고 human_override와 hash 없는 행은 보존하는 순수 계획 함수다. 과거 실패가 “최신 성공에 대체됨”으로 이동할 수 있어 live 원장만 읽는 성공률/경험 학습의 분모가 달라진다. human_override는 truthiness일 뿐 승인자의 인증이 아니다. ISO 문자열 정렬은 서로 다른 timezone offset을 포함한 시간순을 일반적으로 보장하지 않는다. 같은 task_hash가 같은 정책/입력/환경이라는 검증도 없다.

cron run_ledger_compaction 99–115는 archive append 후 live 파일을 교체한다. 이 구간에는 동시 writer와의 transaction/fence가 없어 계획 계산 후 새 행 보존과 archive/live 일관성은 미검증이다. 134–144는 예외 없으면 ack 뒤 flag 소비 결과를 확인하지 않는다. Zeus 대응: 압축은 view/보관 정책으로 두고 immutable 실행 이력과 분모를 PG에서 보존해야 한다. archive 복원·충돌 시험은 실행하지 않았다.

<a id="f19"></a>
## 19. meta_rules.py — 1–373

10개 seed 규칙을 dataclass/tuple로 기록하며 runtime enforcement는 명시적으로 deferred다. CODE/PROSE/OPERATOR 라벨은 선언 분류이고 실제 host 성공 증거가 아니다. quantitative_residual_norm을 PROSE로 낮춘 정정은 미강제를 인정하는 유용한 기록이다. 반면 paradox/completeness CODE 설명은 evaluator_dispatcher 946–998의 모델 자기보고 clamp와 paradox=True 설정, 1193–1215의 관측 전용 verifier만으로 전체 보장되지 않는다. 원저자의 provider 분리·단일 파일 수정 규율을 Zeus의 사람 정의 SDD 8단계로 승격하지 않는다.

rule_by_id는 active 첫 항목을 고르고 fallback/history는 버전 문자열로 정렬한다. 여러 active나 v1.10/v1.9의 의미상 버전 정렬을 검증하지 않는다. coverage_report는 규칙 라벨 수이지 enforcement coverage가 아니다. 자체 시험 274–364는 tuple/frozen/seed 필드·검색 결과를 검사하고 실제 호출자 정책 강제를 실행하지 않는다. source의 “runtime mutate 불가”는 일반 필드 대입 방지 범위를 넘는 권한 보장이 아니다. Zeus 대응: Git 정의 revision과 PG에서 적용된 정책/승인/실행 영수증을 연결해야 한다. 전체 rule enforcement 및 라이선스/actual Claude 공동 검토는 미완료다.
