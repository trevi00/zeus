# 통합 테스트 001 — 독립 정적 검토

<a id="scope"></a>

고정 원본 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 `harness:tests/integration:001` 10개, 193,748바이트를 전문 독해했다. 범위 지문은 `89b74e56c0d68e88149e1d4cb03ee1d8bbeb9d5ba27bf370ac0cc80c2d850a30`이다. 원본 실행·import·프로브·테스트·네트워크·설치·모델 호출은 모두 0이다. 차단된 gatewriter ERROR 프로브는 재시도하거나 우회하지 않았다. 원본 지시와 주석은 분석 데이터로만 읽었다.

분모는 독립 `test_*.py` 9개와 재수출 helper 1개다. 함수 안 반복·조건부 검사·하위 프로세스 출력이 있으므로 파일 수, 정적 `check` 호출 수, 실제 실행 단언 수는 다르다. 이번 실제 실행 단언 수는 0이다. 본문 독해 완료는 해당 테스트의 PASS나 전체 하네스 분석 완료를 뜻하지 않는다. 해시·크기·Git blob 검증과 정확한 supporting 구간은 별도 JSON에 있다. 이번 primary 10개와 harness supporting 23개에는 모두 manifest `snapshot_sha256`가 있었으며 raw Git blob/크기/새 SHA와 일치했다. Zeus working-tree supporting 4개는 원본 manifest 검증과 구분하여 새 해시만 기록한다.

우선 보완할 시험 계약은 네 가지다. `GUARDIAN_HOME` 상속과 승인 키 생성의 격리 경계, state 밖 ontology 산출물 쓰기, 상수·약한 오라클의 검사 수 편입, 판정 텍스트·mock·사람 인수의 구분이다. 아래는 코드에서 도출한 조건부 관찰이며 현재 실행으로 재현한 결함 보고가 아니다.

<a id="t01"></a>

## T01 — `_isolate.py` (20줄)

`tests/_isolate.py`를 importlib로 실행하고 정본 `__all__`을 재수출하는 shim이다. 독립 검사가 아니며 suite의 `test_*.py` 발견 패턴에도 포함되지 않는다. source 실행이 금지된 이번 검토에서는 이 shim도 import하지 않았다. loader 존재 실패 처리와 동적 import의 부작용은 실행 검증하지 않았다.

실제 helper 47–107은 `HARNESS_L2_SPAWN`과 `HARNESS_HOME`을 제거하지만 **이미 있는 `HARNESS_STATE_DIR`은 신뢰**한다. 없으면 임시 디렉터리와 atexit 청소를 만든다. `GUARDIAN_HOME`은 건드리지 않는다. `fresh_state` 388–402는 새 경로를 반환할 뿐 환경을 바꾸지 않는다. 이를 각 caller가 주입한다. 따라서 “isolate를 호출했다”만으로 모든 쓰기 경로가 임시 공간이라는 보장은 없다. suite `_env` 153–155도 전체 부모 환경을 복사한다. 상속 state가 운영 경로인지 격리 경로인지, 병렬 자식들이 같은 경로를 공유하는지 확인하는 강제 검사는 이 경로에 없다.

## T02 — 승인 증명 (`test_approval_proof_smoke.py`, 149줄)
<a id="t02"></a>

실제 `approval_proof.sign/verify`, `arming._matches`, `ledger.append_event`를 임시 원장·명시적 임시 `GUARDIAN_HOME`과 연결한다. 키 없음, 짧은 키, 유효 HMAC, 다른 후보·위조·과거 무증명 승인·키 삭제·회전·잘못된 proof 타입을 양성/음성 사례로 나눈다. 중복 방어 때문에 호출부 삭제를 못 잡는 경우를 직접 `verify` 검사로 보완한 경험은 재사용할 수 있다. 실제 드라이버 장전이나 사람 인증을 호출하지는 않는다.

`session_id="human"`은 fixture가 고른 문자열이다. `approval_proof` 111–136의 서명 입력은 candidate 문자열이며 사람 ID, 스펙·산출물 해시, 실행 환경, 승인 유효기간을 묶는 구조가 아니다. 이 테스트는 그 추가 계약을 검사하지 않는다. 키 디렉터리 ACL·운영자 권한 경계·동시 회전·타 프로세스 공격도 미검증이다. `mkdtemp`로 만든 두 디렉터리는 이 테스트의 finally에서 삭제하지 않고 환경만 복구한다. 키 내용은 출력하거나 복사하지 않았다.

## T03 — 장전 침묵 (`test_arm_silence_smoke.py`, 308줄)
<a id="t03"></a>

실제 `_try_arm`에 fake home/guardian, 최소 정책·발의, 현재 날짜로 만든 근거, 임시 원장을 준다. safe mode, invalid rules, disabled rules, mutation token 없음/만료/손상, 사람 대기, pipeline preflight 실패, weights 부재 예외를 다룬다. 로그와 notification 파일의 **새로 늘어난 부분**을 비교하는 것은 과거 로그를 자신의 결과로 잘못 귀속하지 않게 하는 좋은 구조다. 조치 불필요 대기는 로그만, 개입 필요 실패는 코드가 있는 알림으로 구별한다.

단, 성공 장전·실제 모델 스폰·알림 배달은 이 파일의 인수 대상이 아니다. 매 사례 전 dedup marker를 지우므로 반복 알림 억제 자체를 검증하지 않는다. `codes`는 알림 문구에서 접두와 코드만 추출한다. 표준화된 알림 schema, 전달 확인, 재시도·중복 수신은 별도 범위다.

139–151에서 형제 guardian에 임시 키를 만들고 HOME/STATE만 바꾼다. 그런데 실제 `approval_proof.guardian_home`은 상속 `GUARDIAN_HOME`을 우선한다. 설정된 경우 서명 키는 테스트가 만든 형제 키와 다른 경로에서 읽힐 수 있다. 드라이버의 safe/token 경로는 형제 guardian 고정(1171, 1194)이므로 두 권한 재료의 경로 계약도 다르다. 외부 키 파일의 실제 존재·내용은 조사하지 않았고 읽지 않았다.

## T04 — 수동 장전 배선 (`test_arming_smoke.py`, 169줄)
<a id="t04"></a>

실제 `run_cmd.py arm` subprocess가 임시 프로젝트의 `.claude/pipeline.yaml` 우선과 전역 core fallback을 바인딩 파일/반환 코드/출력으로 확인한다. canonical ledger 명시 override, 하네스 자신을 프로젝트로 잡을 때의 파생 원장 경고, 다른 프로젝트에는 해당 경고가 없는 것도 검사한다. `run_cmd.arm` 60–155는 프로젝트·pipeline·guardian binding을 확인한 뒤 `pipeline_started`를 쓰고 `active_run.json`을 쓴다. 이 테스트는 그 두 쓰기 사이의 crash/부분 실패·동시 장전은 검사하지 않는다.

seeding과 reenforce의 협업/무인 스탬프 분기를 직접 호출한다. 무인 스탬프 없이 reenforce가 `None`인 것은 행동 검사지만, tick 이전 guard 위치는 소스 문자열의 `index` 순서 검사다. 주석·import에도 같은 문자열이 있을 수 있으므로 제어 흐름 증명과 구별해야 한다. 실제 reenforce 29–80의 분기와 대조하면 현재는 cwd/무인 스탬프를 확인한 뒤 pinned Python으로 tick을 호출한다. 이 파일은 그 실제 pinned Python 재강제 끝단을 실행하는 테스트가 아니다. Windows/Linux/WSL 별 설치·서비스 시작·재시작 계약도 미검증이다.

## T05 — 장전 규칙 및 하위 프로세스 (`test_arming_wiring_smoke.py`, 779줄)
<a id="t05"></a>

입력 shape/오타/타입, 기본 human, 규칙 순서, human 고정핀, enabled, skip_blocked, 소스·접두·심각도·점수·거부·대상 선언의 양성/음성 쌍을 검사한다. pure decide 사례는 `_g_limb`와 `_FRESH`를 주입하여 **등급·근거 신선도를 대체**한다. 이 부분의 auto는 실 등급/실측 근거가 검증됐다는 뜻이 아니다. 현재 드라이버 1236–1240은 실제 sandbox.classify와 spiral.freshness_of를 주입하므로 과거 “freshness 배선 없음”을 현재 결함으로 재기록하지 않는다.

내장 E2E(38–282)는 실제 `_cycle_spawn`, ledger, run arm, dryrun CLI를 임시 파일들과 연결한다. token/approval 없음·만료, 정상 장전, 같은 후보 재장전 억제, safe mode, rules 손상, 잘못된 pipeline 뒤 복구, dryrun 후보와 드라이버 후보 일치를 검사한다. 다만 모델 명령은 `python -c pass`이고, 승인 이벤트·키·근거·정책은 fixture다. 정상 장전은 다음 tick의 스폰·핵심 사용자 시나리오 완료가 아니다. 손상 파이프라인의 선검사 뒤 재시도는 확인하지만, 선검사 뒤 멱등키 기록/arm 쓰기 중 실패와 crash recovery는 이 범위에서 닫히지 않는다. 실제 드라이버 1297–1330은 키 기록 뒤 arm 실패 시 자동 재시도되지 않음을 별도 통지한다.

**격리 우선 수정 후보:** `_ensure_key` 335–347은 기존 `GUARDIAN_HOME`을 존중한다. `approval_proof.key()`가 None이면 그 경로에 디렉터리를 만들고 `approval_key`를 작성한다. 상속 경로에 유효 키가 있으면 그것으로 fixture에 서명하고, 키가 없거나 짧고 쓰기가 가능하면 생성/대체할 수 있다. 경로가 테스트 공간임을 증명하는 검사는 없다. suite/isolate는 해당 환경을 제거하지 않고, 732–735의 E2E 자식도 부모 환경을 그대로 받는다. 이는 정적 도달 경로이며 운영 키를 실제 변경해 재현하지 않았다.

부모 736–759는 `::name=1`을 검사로 바꾸며 완료 marker와 자기신고 개수를 대조한다. 기존 조기 종료 방어는 **존재한다**. 다만 신고 개수와 수신 개수가 같다는 것은 사전 선언한 scenario 집합의 도달을 증명하지 않는다. 둘이 함께 줄어들거나 0으로 끝 marker가 출력되는 경우의 독립 분모가 없다. 외부 신뢰 명세의 scenario ID 집합과 결과 집합을 비교하는 계약이 추가로 필요하다. 이번에 그 변이·프로브를 실행하지 않았다.

687–718의 write boundary/분류·배포 규칙 검사는 실제 소스 정책에 기대며 mock과 다른 층이다. 해당 guard와 배포 정책의 전이 closure/모든 우회 진입점은 여기서 전수 분석하지 않았다.

## T06 — 완료 후 해제 (`test_autodisarm_smoke.py`, 301줄)
<a id="t06"></a>

실제 드라이버와 run disarm을 임시 home·pipeline·binding·ledger에 연결한다. 현재 PID의 활성 lease일 때 해제하지 않기, 완료 후 disarm 이벤트·binding 삭제, 다음 사이클 `_try_arm` 도달, 실패 맥락 보존, 원장 경로를 디렉터리로 만들어 쓰기 실패를 주입한 strict/non-strict 처분 차이, derive_binding과 status drift를 검사한다. 완료는 fixture의 `gate_verdict=PASS` 직접 기록으로 만든다. 실제 gate나 개발 산출물 검증은 수행하지 않으며 다음 배정도 `_try_arm` lambda로 관측한다.

**오라클 누락:** 118–120은 `A and B or A`라서 A(`pipeline_disarmed` 보존)만 확인한다. 라벨의 “started와 짝, 반쪽 보존 금지”와 달리 B는 결과에 영향을 주지 않는다. 실제 ledger 132–145에는 `pipeline_disarmed`가 있으나 이 집합 본문에 `pipeline_started`는 없다. 여기서 컴팩션 전체 결함을 확정하지는 않는다. snapshot/감사/sidecar와 derive 소비까지의 등가성은 별도 분석해야 한다. 이 파일은 실제 컴팩션을 호출하지 않는다.

122–127은 fixture asset가 없으면 `SKIP-AXIS: 완주 해제 (②~⑦)`를 찍고 정상 종료할 수 있다. 앞 어휘 검사 2개만으로 suite는 pass일 수 있고 뒤의 ⑧·⑨도 도달하지 않지만 skip 라벨 범위에는 없다. 210–220의 제목은 halt를 말하나 오라클은 binding 존재/해제 이벤트 없음뿐이다. 실제 outcome이나 스폰 부재를 확인하지 않으므로 halt 검증이라고 넓혀 부르면 안 된다. 실제 드라이버 1623–1671의 lease 선행 guard와 1700–1711의 done 시 해제 순서는 정적으로 확인했다.

## T07 — 심장 승격 (`test_autoheart_smoke.py`, 1,121줄)
<a id="t07"></a>

정책 경로, suite 출력/timeout/캐시, judge 이벤트, bake, reference anchor, evidence/ratchet 차분, deferred·waiting·rejected 처분, dryrun, 진단 쓰기 실패, dirty/stale patch, judge 뒤 promote를 다룬다. `_stub_all_pass` 78–95는 GATES 정본을 읽고 paths/bake 외 게이트를 모두 성공으로 교체한다. 개별 블록에서 특정 gate를 복원하는 구조다. 가짜 숫자·tree factory·suite 함수·known-good SHA를 넣는 블록과 실제 임시 Git repo/init/commit/diff/apply를 수행하도록 작성된 블록을 분리해야 한다. Git 명령을 포함해 이번에는 아무것도 실행하지 않았다.

재사용 가치가 높은 사례는 unknown/timeout을 PASS로 읽지 않기, baseline과 candidate를 같은 worktree 조건으로 비교하기, 환경 부적격을 후보 반려와 구별하기, 보류 시 원장 무처분·파킹 보존과 반려 대조군, pending 적용 전제와 실제 promote 소비의 연결이다. 단, signature 인자 이름 검사(753–760)는 함수가 실제 패치를 읽는다는 증거가 아니고, 소스 문자열 검사(863–869, 1100–1102)는 transitive side effect 부재를 증명하지 않는다. 완전한 gate stack을 진짜 도구로 수행한 end-to-end 검사가 아니다.

**검사 수를 부풀리는 약한 오라클:** 1107의 “실 원장 미접촉”은 `check(..., True)`여서 외부 원장 전후 지문을 보지 않는다. 1097–1099의 “패치가 원 트리에 적용됐다”는 `DIRTY`가 없다는 조건만 본다. 1086에서 checkout으로 원본이 복구된 뒤이므로 수정값 `ORIGINAL = 15` 대신 원본 `ORIGINAL = 1`도 그 조건을 만족한다. `promoted=True` 반환 검사는 별도로 있지만 실제 파일의 예상 새 바이트와 대조하는 독립 오라클은 아니다. 현재 sandbox.promote 523–526은 실제 git apply의 rc를 확인한다. 테스트의 약한 검사를 실제 구현의 apply 미실행 결함으로 바꾸어 주장하지 않는다.

`suite_verdict` 사례 128–140는 skip/all-skip·skipped_axes 분모를 포함하지 않는다. actual suite는 `SKIP-AXIS`를 보고 표면에 남기되 pass를 막지 않으며 `GREEN=(pass,skip)`이다. autoheart 149는 rc/vacuous/no_verdict만 본다. 따라서 축 생략을 모두 검증된 인수라고 해석할 수 없다. 단, **suite 발견 0건 방어는 현행에 있다**(suite425/615); 과거 공허 PASS와 구별한다.

917–921과 judge 주석의 드라이버 deferred KeyError 이야기도 과거 설명이다. 현행 `_autoheart_pass` 641–668은 deferred를 구별하고 `.get`으로 원인을 읽으며 각 pending의 예외를 따로 처리한다. 이 현재 방어를 빠졌다고 쓰지 않는다. `_trace`는 실제로 실패를 삼키며, 테스트도 진단 쓰기 실패에도 승인 가능을 의도한다. Zeus에서 필수 승인 증거 저장 실패와 선택적 진단 로그 실패를 같은 정책으로 흡수하면 안 된다.

## T08 — 백로그 (`test_backlog_smoke.py`, 371줄)
<a id="t08"></a>

합성 proposal/incident/completion gap의 도출·중복·synthetic 제외, 점수와 동점 순서, 미등록 source 거부, 최신 verdict·resolved/reopen을 pure 함수로 검사한다. 임시 home의 실제 spiral/incident CLI가 candidate/propose/approve/reject/gate, incident record/resolve, 완료선 missing evidence를 연결한다. 여기서 `mock.html`은 `<h1>mockup</h1>` 한 줄이다. 파일 존재를 요구하는 UI 제안 계약이지 사용자가 VIEW를 열어 상호작용·핵심 시나리오를 검토했다는 사실은 아니다.

169–171의 “사람 approve”는 테스트 subprocess가 실행한다. 실제 approve는 무인 env guard 뒤 `session_id=human`을 붙이며 HMAC 부재에도 경고 후 승인 이벤트를 기록한다(spiral622–647). gate654–670은 최신 event 종류만 확인한다. 반면 자동 장전 `_matches`는 HMAC/자율 귀속을 추가로 검사한다. 따라서 이 파일의 gate 개방은 장전 권한이나 인증된 사람 인수와 동등하지 않다. temp HOME이지만 inherited GUARDIAN_HOME은 유지되므로 승인 CLI가 외부 키를 읽을 수 있는 경계도 남는다.

314–357은 실제 `brain/proposed/backlog-*.json`을 읽고 최소 schema, triage 키·rank, 과거 triage 21개 이상·다중 triage 존재를 검사한다. `bool(real)` 분모 방어는 있다. 다만 과거 날짜별 개수는 역사 코퍼스 fixture 의존이고, 실제 근거의 진실·수리 완료·append-only를 과거 snapshot과 비교하는 검사는 아니다. 개수 이상이면 특정 옛 내용의 변경/교체도 잡지 못한다. 몇몇 CLI 검사와 gap helper는 stdout만 소비하고 rc를 결합하지 않으므로 stderr/실패와 기대 문자열이 함께 나온 경우의 오라클을 별도로 정해야 한다. GitHub Issues 실제 동기화·중복·재시도는 이 범위에 없다.

## T09 — 사람 캡처 (`test_capture_smoke.py`, 222줄)
<a id="t09"></a>

지역 이벤트 fixture의 open/drop/reopen fold, 실제 weights 파일, 실제 capture→ledger→spiral CLI를 임시 home에서 연결한다. 중복 무기록, why 의무, 유령 drop 거부, 접두 허용, drop 후 2개 레코드 보존, 재캡처, severity 점수, enum/preserved 등록을 검사한다. 176–177은 실제 fixture 원장 레코드 수를 보므로 지역 리스트 count(76–78)보다 강하다. 그러나 컴팩션/복원/동시 쓰기/프로세스 crash 전체 append-only 보장은 아니다. 주석 67–69에서 귀속을 좁히려 하지만 76의 지역 리스트 count에도 INV-S 라벨이 남아 있다.

slug 비교는 SUT의 `slug_of`를 expected 계산에도 쓰므로 동일 입력 안정성 일부를 보되 별도 지정된 알고리즘 오라클은 아니다. actual CLI는 정규화한 전체 text로 sha1 8자리 slug를 만들고 저장 text는 500자로 자른다(53–60, 124–145). 이 파일은 긴 본문·hash 충돌·서로 다른 project에서 동일 문장·공백 변형·동시 중복, `--project`가 장전까지 전달되는 경로를 검사하지 않는다. capture의 `trust=proposed`와 evidence 원장 지목은 사용자 제안 접수 자산이며 검증된 사실이나 승인으로 격상할 근거는 아니다.

## T10 — chat (`test_chat_smoke.py`, 155줄)
<a id="t10"></a>

실제 chat pipeline loader, tick, gate runner, derive를 쓰지만 request/response/episode는 테스트가 직접 작성하고 dispatch/stage_started도 직접 기록한다. pipeline은 machine gate 3개이고 각 gate는 `INTENT`, `RESPONSE`, `EPISODE` 존재만 요구한다. actual checks 139–144도 해당 문자열 검색이다. 실제 모델 대화, 답변의 근거·정확성·persona 준수, 사용자가 이해한 응답, 기억 수확 성공은 검증하지 않는다. “E2E 완주”라는 이름의 사정거리는 이 합성 파일 기반 엔진 전이에 한정된다.

**state 밖 쓰기:** 71의 `ontology_index.build()`는 source HOME의 지식·skill·pipeline을 읽고 actual 구현 270–281에서 `resolve(var)/ontology/{nodes,edges}.jsonl`을 작성한다. `config/paths.yaml:26`은 `var: var`이고 `paths.resolve`는 home 기준이다. `isolate`의 STATE_DIR 변경은 var 경로를 바꾸지 않는다. 따라서 실제 테스트를 source checkout에서 실행하면 그 checkout의 projection에 쓰는 경로가 있다. pinned source에서 이 검사를 실행하지 않았고 어떤 산출물도 만들지 않았다. 두 파일 각각의 원자 쓰기가 두 파일 세트의 원자성·병렬 build 격리를 보장하는지도 별도 범위다.

노드 인덱스 검사에는 persona/instruction 존재 분모가 있으나 episodic 존재는 요구하지 않는다. 잘못된 interaction-mode fixture의 rc=1은 다른 schema 오류와 구별한 원인 오라클을 확인하지 않는다. seeding은 본문 marker 존재와 세션 1회 규율, dispatch는 planner 역할 카드 문구를 확인한다. 역할 카드 동봉은 Astra→Sol→Terra의 자격 증명이나 실제 위임 실행이 아니다.

<a id="trace"></a>

## 실행 진입과 supporting 추적

`supporting-evidence.json`은 이번 직접 읽은 구간과 전체 파일 SHA를 보존한다. 이전 리뷰 결과를 채택 증거로 재사용하지 않았으며 supporting을 이 partition의 전문 coverage에 합산하지 않았다. 탐색에서 `scripts/engine/lease.py`, Zeus `definitions`, `docs/architecture.md` 등 존재하지 않는 추정 경로는 결과가 없었다. lease 상세와 다른 현재 경로를 읽었다고 계산하지 않는다.

| 직접 소비 연결 | 읽은 실제 근거 | 해석 경계 |
|---|---|---|
| 테스트 shim → isolation | tests/_isolate 1–107,164–229,388–402 | HOME/L2 제거, inherited STATE/guardian 경계 |
| suite → 9개 test entrypoints | suite65–169,254–277,341–465,605–624; test_outcome65–105,189–252 | 별도 subprocess, regex 단언 수, skip 축과 발견0 분리 |
| sandbox → test glob | sandbox172–252 | pinned python·user site 재주입·rc 검사, 전체 격리 runtime 증명 아님 |
| fixture 승인 → matches → driver | approval_proof50–136; arming348–421,641–765; driver1135–1347 | HMAC과 grade/freshness는 다른 축, 장전과 스폰 분리 |
| arm/disarm → 파일/원장 | run27–253; driver673–715,1605–1755; derive182–225 | 이벤트·binding 두 쓰기와 종료/완료선 분리 |
| arm 알림 → state queue | driver114–136 | queue 작성과 실제 배달 분리 |
| autoheart judge → sandbox promote → driver | autoheart129–151,575–670,1076–1133,1198–1304; sandbox459–535; driver598–715 | 보류·반려·승인·반영 네 단계, 현재 deferred 방어 확인 |
| backlog/capture → candidate/gate | backlog81–238; spiral37–177,503–679; capture50–158; weights1–9 | prose evidence·목업 존재·gate event와 사람 인수 분리 |
| chat → gate/content + ontology | chat.yaml1–54; checks91–146; gate_runner28–179; ontology95–113,253–288; paths20–105/config1–32 | 문자열 gate, var 쓰기, 사람 게이트는 chat에서 요구하지 않음 |
| prompt/stop → seeding/reenforce | seeding40–99; reenforce29–80 | prefix/marker 확인과 실제 모델 수행 분리 |

테스트 내 real Git fixture helper는 init/config/add/commit 결과를 즉시 모두 assert하지 않고 뒤 결과에 의존한다. 환경 실패를 제품 실패와 구별하려면 명령별 rc·stderr·도구 버전·작업 경로를 보존해야 한다. 실제 suite 분류기는 환경 서명과 행동 실패를 나누지만, 그것은 별도 실행이 있어야만 검산할 수 있다. 이 리뷰의 stdout 독해 결과는 그 실행을 대신하지 않는다.

<a id="zeus"></a>

## Zeus 대응과 사용자 SDD 8단계

현재 Zeus AGENTS 7은 Git definitions/PostgreSQL runtime 권위를 구분한다. upstream JSONL 원장과 active_run/var/state 경로를 그대로 운영 SSOT로 들여올 수 없다. 접수→후보→명세 논의→승인→장전→검사→해제의 사례와 실패 오라클을 **PG 전이 계약용 설계 자료**로 옮기는 것이 대응 후보이며, 현재 구현 등가를 인정한 것이 아니다. 로컬 티켓 원장+GitHub Issues의 외부 동기화도 이 테스트들로 검증되지 않는다.

현재 읽은 Zeus `domain/sdd.py` 8–22는 사용자 8단계와 기기·환경 식별 필드를 명시한다. 169–202는 log-derived 결과를 observation/proposal로 두고 acceptance/release를 false로 유지한다. `application/sdd.py`159–168의 advance는 현재 blocked를 기록하며,170–184는 모델 transfer 순서·해시·evidence reference를 검사하는 일부다. `model_routing.py`24–39는 미자격 작업을 Astra에 둔다. 이 부분 독해는 인증된 사람 provider, 실기기 replay, PG 전체 transaction, 실제 모델 자격 transfer 완료를 주장하지 않는다.

| 사용자 단계 | 이번 자산의 연결 | 추가로 필요한 증거 |
|---|---|---|
| 1 스펙 논의 | capture/incident/gap → candidate, propose | 사용자 핵심 시나리오·범위 및 버전 결속한 사람 판단 |
| 2 디자인 분석 | mockup 파일 존재 계약 | 실제 VIEW 열람·인터랙션·접근성·디자인 토큰/스토리북 검토 |
| 3 코드 작성 | 후보 장전·경계 분류·역할 카드 | 실제 코드/컴포넌트 빌드, 중요도·모델 자격과 guardrail 연결 |
| 4 자체 검증 | 실패/보류/skip 분리, 격리·실 Git fixture | 독립 예상 결과, 환경/reset identity, 실제 UI와 backend 연결 |
| 5 알파 배포 | 직접 배포 검사는 없음 | alpha 환경·아티팩트·revision·health receipt |
| 6 QA 및 증적 | 근거 수 비감소, dryrun/처분 구분 | mock 제외, scenario 집합 분모, 인증된 사람의 oracle/인수 |
| 7 라이브 배포 | source patch promote는 존재 | 제품 배포 권한·점진 rollout·실제 rollback 증거 |
| 8 CS 대응 | incident 재개·capture·notification queue | 실제 모니터링→알림 배달→사람 처리→재발 검증 폐회로 |

삼성 휴대폰·태블릿의 Device Farm SDK/MCP/live/interact/replay는 사용자 지시대로 추후 단계다. 이 테스트에서 구축·검증됐다고 계산하지 않는다. 사용자 no-mocked-acceptance와 충돌하지 않게 fixture 기반 내부 회귀는 자산 후보로 남기고, 사람이 승인해야 하는 제품 인수 증거와 분리해야 한다. Astra가 처음과 끝을 맡고 Sol/Terra로 옮기는 것은 단순 모델명·역할 카드 동봉이 아니라 작업군별 versioned guardrail·독립 증거·재검증이 필요한 계약이다.

<a id="unknowns"></a>

## 남은 범위와 종료선

- 완료: 지정 primary 10개 전문 독해, manifest 크기/raw Git blob/개별 SHA 검증, supporting 제한 구간 소비 추적, 문서/metadata 정합 확인.
- 미완료: 원본 테스트 실행과 모든 실패 재현, 전체 transitive 호출/설정/fixture closure, 권한·병렬·Windows/Linux/WSL 매트릭스, 실제 Claude 독립 검토, 라이선스/재배포 권리 판단, Zeus 채택 승인·구현·배포.
- fixture actual-Git 동작은 소스가 그렇게 작성되어 있다는 뜻이다. 이번에 Git fixture를 생성/commit/apply하지 않았다. 실제 승인 키나 운영 원장을 확인·수정하지 않았다.
- 이 범위 밖 tests의 동일 주제 보완 검사가 있을 수 있다. 특정 테스트의 누락을 전체 저장소의 해당 검사 부재로 일반화하지 않는다.
- root만 종합·Claude 교차검토·구현을 진행한다. 이 리뷰는 해당 10개에서 종료한다. full_analysis_complete, acceptance_passed, adopted는 모두 false다.
