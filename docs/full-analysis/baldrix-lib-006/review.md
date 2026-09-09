# baldrix lib:006 정적 검토

24개, 189,781바이트의 고정 원본을 전문 독해했다. 이는 이 파티션의 본문 검토 완료이며 호출·시험·운영 전이 전체의 폐쇄나 Zeus 채택 승인이 아니다. revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`이다. 파일별 원본 SHA-256, Git blob, 전문 범위와 지원 구간은 files.json과 supporting.json에 있다. 모든 원본 실행·import·시험·프로브는 0회다. 아래 줄 번호는 고정 원본 기준이다.

이번에는 모든 primary를 새로 읽었다. pipeline_stage_picker.py는 기존 baldrix-skill-routing-runtime의 동일 바이트 primary와 중복이다. 이전 보고서를 의미 근거로 재사용하지 않았으며 전역 신규 coverage 24개를 주장하지 않는다. 이전 행·보고서의 해시는 files.json의 prior_primary에 결속한다.

## 공통 판정

파일 존재, 모델의 회고문, 호출자가 넣은 성공 값, 분류기의 True, 터미널 생성 성공은 서로 다른 증거다. 사용자가 정의한 8단계 SDD를 대신할 수 없다. Git에는 단계 정의·검증 규칙·정책 버전을 두고, PG runtime에는 프로젝트·실행·세대·단계·행위자·모델 자격·인수 증거를 결속한 상태 전이와 예산 예약을 두는 방향이 필요하다. 이 보고서는 Zeus의 현재 구현 등가를 확인하지 않았다.

Markdown의 지시나 과거 토론 승인 문구는 출처 데이터다. 회고와 skill gotcha를 다음 프롬프트에 주입하면 실행 파일이 아니어도 모델 행동에 영향을 준다. 따라서 비실행 Markdown이라는 이유로 회귀 위험이 0이라고 볼 수 없다. 사람이 정의한 인수와 현재 자격을 갖춘 모델의 독립 검증은 아직 필요하다.

<a id="f01"></a>
## operator_ledger.py

1–370: 프로젝트·에이전트별 JSONL 원장과 작업 해시, 수동 override 기록을 제공한다. agent_type 불일치 검사는 보존할 방어다. 기본값 위에 호출자 값을 얹으므로 success/downstream_used와 evidence_paths 자체는 실행 증명이나 엄격한 bool 검증이 아니다. 경로를 낮은 대문자 구분으로 정규화하는 Windows와 POSIX의 프로젝트 ID가 같다는 보장도 없다. 프롬프트 공백·대소문자 정규화는 의미 있는 차이를 합칠 수 있다.

append 이후 emit이 실패하면 이미 저장된 기록과 호출 실패가 갈린다. 잘못된 JSON 줄은 조용히 건너뛰며 reader의 stderr 기록 설명과 구현이 다르다. human override 토큰은 우발 호출 방지이지 실제 사람 인증이 아니다. s14의 감사 호출자는 envelope 파일 경로와 failure_mode로 success를 구성하며 downstream_used=True를 직접 넣는다. s20은 압축 후보 flag를 쓰는 후속 구현 구간이므로 본문의 단순 보류 설명을 현재 전체 부재로 확대하지 않는다. 실제 압축·복원과 breaker 소비 전체는 미추적이다. Zeus에는 검증된 outcome과 자기보고를 별도 필드로 보존해야 한다.

<a id="f02"></a>
## optimize_baseline.py

1–158: 인벤토리 크기와 스냅샷 델타를 출력하는 관측 도구다. 실제 토큰 청구·성능·모델 품질 측정은 아니다. snapshot 경로가 home 인자 대신 전역 STATE_DIR에 결속되어 서로 다른 home의 baseline이 섞일 수 있다. 파일 읽기 실패와 0을 구분하지 않는 값도 있다. 저장 예외를 삼킨 뒤 레코드를 반환하므로 출력만으로 영속 기록을 증명할 수 없다.

main은 record 후 delta를 그리므로 방금 쓴 baseline을 다시 읽어 이전 대비 변화가 0이 되는 경로가 있다. 정적 순서 판단이며 실행 재현은 하지 않았다. 직접 외부 호출자와 시험은 미추적이다. Zeus에서는 revision·측정 환경·기간·실패 여부와 실측/추정 구분을 baseline에 결속해야 한다.

<a id="f03"></a>
## path_denylist.py

1–167: realpath/normcase와 Windows 긴 경로 조회로 self-modification 대상 경로를 차단한다. 해석 실패 시 차단하려는 방어를 보존한다. 경로 집합은 Path.home()/.claude 기준이므로 paths.py의 환경 변수 기반 assets 이동과 동등하지 않다. 존재하지 않는 Windows 경로를 일괄 차단한다는 설명과 일부 건너뛰는 분기는 구분해야 한다. 문자열 prefix는 형제 이름의 과잉 차단 가능성도 갖는다.

s15는 proposal target 검사에서 denylist를 먼저 사용한다. 그러나 이 구간만으로 실제 write 직전 재검증·symlink/junction 교체 경쟁·전체 대상 confinement까지 확인하지 않았다. s16의 operator context는 양의 pid, sid, 존재하는 cwd의 형태 검사이며 실제 사람 인증이 아니다. Zeus에서는 승인 객체와 쓰기 capability, 해시 precondition을 연결해야 한다. Windows/Linux/WSL 실제 경로 공격 검증은 미실행이다.

<a id="f04"></a>
## paths.py

1–257: 읽을 assets와 쓸 state/telemetry 경로를 분리하며 일부 접근자를 동적으로 계산한다. 분리 의도는 보존할 가치가 있다. 환경 변수의 상대 경로나 임의 경로를 OS 차원에서 제한하는 구현은 아니며 import 시 상수와 호출 시 접근자의 반영 시점이 다르다. STATE_DIR monkeypatch 지원과 telemetry 접근의 우선순위도 같지 않다.

primary quota_tracker는 lazy import로 STATE_DIR을 읽고 reflection_recall은 state_dir()를 호출한다. s02의 skill_match는 USERPROFILE/.claude/skills를 직접 구성하여 assets 접근자와 다른 근원을 가진다. pending_changes는 __file__ 근처 원본을 직접 수정한다. 이들은 동일한 격리 경계라고 볼 수 없다. Zeus에서는 Git 정의 경로와 PG runtime 위치를 명시적으로 주입하고 OS별 경로 identity를 검증해야 한다.

<a id="f05"></a>
## pending_changes.py

1–623: 여섯 pending change의 적용 함수와 카나리아를 등록한다. 코드·설정·스킬 편집, inventory subprocess, hook subprocess 및 headless Claude 호출을 포함한다. 이번에는 그 어떤 경로도 실행하지 않았다. 파일 목록 기반 rollback이 별도 probe 디렉터리, telemetry, 원장까지 복원한다는 보장은 없다. 고정 probe 이름의 정리에는 기존 소유물 여부를 별도로 확인해야 한다.

카나리아에서 BLOCKED라는 모델 응답 문자열을 찾는 것은 실제 쓰기 거부 영수증이 아니다. 실제 파일 상태와 종료 코드, 호스트 도구 호출을 함께 검증하지 않는 경로가 있다. skill 적용 경로의 토큰 게이트 대체 설명도 행동 시험이 사람 승인을 대체한다는 근거가 아니다. s19의 dry-run은 before canary를 실제 호출한다. --no-regression은 경고 help와 달리 regression=None을 전달할 수 있다. CN.run 내부 전체는 읽지 않았으므로 최종 허용 여부를 단정하지 않는다. 과거 차단된 gatewriter probe는 재시도하지 않았다. Zeus 채택 전에 격리·소유권·승인·실제 효과 증거가 필요하다.

<a id="f06"></a>
## phase_detector.py

1–88: plan/implement/review/deploy/debug 키워드 집합으로 문맥을 분류하며 strict-design을 별도로 판정한다. s02의 hook이 prompt_lower를 넘기는 연결을 읽었다. 영어 경계와 한국어 부분 문자열은 인용·부정·시스템 발화의 실제 출처를 판정하지 않는다. 이 다섯 분류는 사용자의 8단계 SDD 전이가 아니다. 추천 용도로만 유지하고 실행 권한·완료·사람 의도는 구조화한 이벤트로 별도 판정해야 한다. 직접 시험 전문은 미추적이다.

<a id="f07"></a>
## phase_events.py

1–492: 크기 제한과 상태 어휘 검사를 거쳐 JSONL append, 읽기 및 최신 상태 투영을 제공한다. 내부 self-check도 전부 읽었지만 실행하지 않았다. SID는 경로 구분자나 절대 경로를 막는 검증이 충분하지 않고 actor/generation/fencing/실행 증거를 요구하지 않는다. append의 bytes-written 확인이 없고 fsync 실패가 무시되므로 True는 crash durability 증명이 아니다. PIPE_BUF 설명을 정규 파일의 모든 OS 동시 append 보장으로 확대할 수 없다.

reader는 일부 schema 존재만 확인하고 손상 줄을 건너뛰므로 누락/빈 결과를 구분할 근거가 약하다. self-check에는 선택 의존성 import 불가를 성공 값으로 넣는 분기가 있어 출력 PASS와 검증 분모를 분리해야 한다. s17은 EventStore를 정본으로 먼저 쓰고 phase_events 결과 bool을 소비하지 않는 실제 호출자다. 파생 스트림 누락의 감지·복구 전체는 미확인이다. Zeus PG transaction/outbox와 투영 재생이 적응 지점이다.

<a id="f08"></a>
## phase_graph_builder.py

1–201: ROADMAP 헤더와 첫 의존 표기, PLAN 파일 이름으로 typed graph를 생성한다. 노드 ID 정규화와 안정적인 순서는 유용하다. 미존재 참조도 placeholder phase로 만들며 서로 다른 경로의 같은 stem이 충돌할 수 있다. 본문 인수 조건·실행 증거·DAG cycle 검증은 아니다. 선언한 decision 종류가 실제 생성된다고 단정할 수 없다.

s13 CLI는 write_graph 후 노드·edge 수를 출력한다. 그 done은 그래프 파일 생성 경로이고 계획 실현 완료가 아니다. 쓰기는 원자적 transaction이 아니며 malformed graph 처리 전체가 CLI에 포괄되지 않는다. Zeus에서는 Git 정의의 파생 인덱스로 취급하고 원본 경로/해시와 미해결 참조를 보존해야 한다.

<a id="f09"></a>
## phase_graph_query.py

1–91: 저장 그래프에서 한 홉 typed edge를 조회한다. 없는 파일/비객체가 빈 그래프로 수렴하는 경로와 JSON/OSError 예외를 구분해야 한다. endpoint/schema 검증, transitive closure 및 복구는 제공하지 않는다. 잘못된 direction을 both로 취급하지만 s13 CLI는 choices로 입력을 제한하므로 CLI 표면의 일부 방어는 있다. strict는 파일 부재를 별도 exit 2로 내보낸다. 라이브러리 직접 호출자 전체는 미추적이다. Zeus에는 unknown과 empty를 분리한 파생 조회 계약이 필요하다.

<a id="f10"></a>
## phase_tree.py

1–278: phase/step 모델, 활성 하위 phase 선택, 상태 집계와 Markdown 변환을 제공한다. leaf와 parent의 배타성·ID 유일성·증거 유효성은 문서 설명만으로 강제되지 않는다. deepest는 첫 활성 branch를 따라가므로 트리 전체 최심 활성 노드를 고르는 계약과 다르다. 쉼표/세미콜론 수에 의존한 승격은 실제 독립 작업의 수가 아니다.

DONE 접두어와 임의 evidence 문자열은 인수 영수증이 아니다. unknown 상태가 in_progress로 수렴하고 렌더링이 여러 상태를 잃어 왕복이 완전하지 않다. 6개월 pruning 설명의 실행 경로도 이 파일에는 없다. 직접 caller/test는 미추적이다. Zeus의 사람이 정의한 SDD 상태 머신과 별도로 계획 표현으로만 후보 평가해야 한다.

<a id="f11"></a>
## pipeline_gate_runner.py

1–93: stage/attested_by/docs_sha의 수동 attestation JSONL을 기록하는 advisory 도구다. 자동 완료 판정과 분리한다는 의도는 보존한다. 서명·모델 자격·해시 형식·실행 receipt를 검증하지 않고 호출자가 넣은 값을 기록한다. _written은 append 이후 반환용 값이며 실제 저장 행의 필드가 아니다. git root 조회 subprocess가 있으나 이번에는 실행하지 않았다. 직접 외부 caller/test는 미추적이다. Zeus에서는 attestation과 검증 verdict, 실제 사람 인수를 별도 provenance로 관리해야 한다.

<a id="f12"></a>
## pipeline_overlay.py

1–122: core와 언어 overlay를 결합한다. deep merge라는 표현과 달리 stage override는 얕은 dict 병합이므로 nested 값이 통째로 바뀐다. 중복 ID, 모르는 ID, 빈 applicable 목록, 필수 gate 유실의 의미를 엄격하게 검증하지 않는다. 잘못된 overlay가 None으로 수렴하면 neutral core가 남는 경로가 있으며 error가 표시되지 않는다. cwd 인자가 실제 merge 경로에 반영되지 않는다.

primary picker는 overlay 경로를 선택하지만 s01의 context_load는 resolve/parse를 직접 사용하므로 두 표면의 정의가 같다고 단정할 수 없다. gate_intent는 문자열/자료로 운반되며 실행되지 않는다. Zeus에서는 Git 버전별 overlay schema와 필수 gate 보존을 검증하고 PG 실행에 해시를 고정해야 한다. 언어 경로 입력의 전체 출처와 overlay 시험은 미추적이다.

<a id="f13"></a>
## pipeline_stage_picker.py

1–122: 산출물 중 하나라도 exists이면 단계가 완료됐다고 추정해 다음 skill을 추천한다. 마지막 완료 required stage 인덱스로 이동하므로 앞쪽 미완료를 건너뛸 수 있고, 끝에서는 마지막 stage를 계속 추천하는 경로가 있다. gate 본문, 산출물 내용·해시·신선도·인수 증거는 검사하지 않는다. 디렉터리도 exists=True가 될 수 있다.

s08의 빈 src 시험은 output='src/main.py'이며 output='src/' 자체나 다중 산출물 전체 충족을 검증하지 않는다. no_pipeline 시험은 결과 tuple 길이만 검사한다. 시험 이름을 더 강한 계약으로 확대하지 않았다. s07의 gate 선언은 요구사항/DDL 성공 등을 요구하지만 picker는 그 조건을 평가하지 않는다. 동일 바이트 이전 primary는 prior_primary로 결속했으며 신규 coverage로 재계상하지 않는다. Zeus의 8단계 순차 인수 gate 대신 사용할 수 없다.

<a id="f14"></a>
## pipeline_status.py

1–112: 파일 존재를 DONE/SKIP/TODO로 렌더링한다. picker와 같은 ANY-output 및 마지막 required 완료 인덱스 문제를 가진다. optional stage도 산출물이 있으면 DONE이 되어 total_required가 SKIP 제외 방식으로 달라지므로 분모가 고정된 required 수가 아니다. 중간 optional SKIP 다음의 TODO에 CURRENT/Next가 표시되지 않는 경로도 있다.

s01은 hook 주입을 위해 이 렌더러를 실제 호출한다. 요약은 관측 휴리스틱이고 자동 gate 통과나 사람 인수가 아니다. primary yaml이 native block list를 반환할 수 있지만 parse_output_list는 문자열 메서드를 요구하므로 유효 YAML이라는 이유만으로 소비 계약이 안전하지 않다. Zeus에는 정의 분모와 검증 완료 수, 미실행 수를 따로 표시해야 한다.

<a id="f15"></a>
## pipeline_yaml.py

1–188: safe_load와 compose로 stage를 읽고 flow list는 문자열, block list는 native list로 보존한다. bool을 'true'/'false'로 맞추는 호환 계약은 명시적이다. 그러나 필수 id/type와 키별 schema를 검사하지 않고 compose 후 각 stage의 node 구조를 가정하는 구간은 포괄 try 밖에 있다. unreadable/invalid→[]라는 설명이 모든 malformed 구조의 예외까지 덮는 것은 아니다.

project override 탐지는 '- id:' 문자열 포함 여부라 주석도 후보가 되고 형식이 다른 유효 문서는 놓칠 수 있다. KNOWN_STAGE_KEYS는 s07에 있는 reuse 같은 키를 버린다. gate list를 보존하는 것과 gate 실행은 다르다. s07 1–150만 읽었으므로 config 전체 386줄의 의미 검토를 주장하지 않는다. Zeus에는 versioned typed schema와 오류/부재 분리, SDD 정의 식별자가 필요하다.

<a id="f16"></a>
## project_paths.py

1–93: 최대 5레벨 walk-up으로 .claude와 언어 marker 파일을 찾는다. marker 존재를 사용하는 경량 발견 기능이다. 사용자 지정 root 경계·symlink 신뢰·프로젝트 소유권을 검증하지 않으며 상대 cwd는 normpath만 거쳐 상대 상태로 남을 수 있다. predicate 예외가 자동 fail-soft인 계약도 아니다. 직접 caller/test 구간은 이번에 읽지 않았다. Zeus에서는 명시적 project identity를 정본으로 두고 발견 결과를 검증 전 후보로 취급해야 한다.

<a id="f17"></a>
## prompt_origin.py

1–49: 선행 공백 뒤의 task-notification 접두어로 시스템 재호출을 추정한다. 비문자열을 False로 처리하는 방어와 중간 인용을 제외하는 범위 제한을 보존한다. 접두어는 인증된 host origin 필드가 아니므로 사용자 인용을 시스템으로 오인하거나 다른 시스템 형식을 놓칠 수 있다. s02에서 skill scan 전에 종료하는 실제 소비를 확인했다. 다른 두 소비자와 시험의 전문은 미추적이다. Zeus에는 실제 origin provenance를 받되 본문 휴리스틱은 보조 신호로 남겨야 한다.

<a id="f18"></a>
## psmux.py

1–340: multiplexer 탐색, 세션 생성/종료, 키 입력, pane 캡처를 감싼다. argv 전달과 시간 제한은 보존할 방어다. legacy command.split은 공백 경로/인용을 훼손한다. send_keys(send_enter=True)는 첫 전송 returncode를 확인하지 않고 Enter 전송 결과만 반환하므로 실패한 문자열 대신 기존 입력을 실행할 가능성을 정적으로 구분해야 한다. 실제 재현하지 않았다.

많은 helper는 missing/timeout을 False/[]로 합치며 문서의 hard failure 설명과 다르다. ensure_session=True는 같은 이름의 기존 세션이지 작업·소유권·모델 자격 확인이 아니다. s18은 argv 방식으로 worker를 띄우지만 spawn 성공이 작업 완료는 아니다. s10 시험은 binary 미설치 시 SKIP-SUITE를 명시해 분모를 분리한다. Windows/Linux/WSL 실제 binary 호환, quoting, 프로세스 트리 종료와 결과 영수증은 미검증이다. vendor 현행 주장도 확인하지 않았다.

<a id="f19"></a>
## quota_tracker.py

1–158: sid/key별 JSON 카운터에 corrupt='raise'/'empty'와 coerce/filter 정책을 둔다. s11/s12는 strike와 evaluator가 서로 다른 정책을 사용하는 직접 호출자다. 정책 차이를 보존해야 하지만 raise 정책도 OSError·빈 파일에는 {}를 반환한다. coerce는 bool/음수 같은 값도 int로 받아 quota가 안전한 비음수 정수라고 보장하지 않는다. load도 path()를 통해 디렉터리를 생성한다.

s21의 atomic_json은 임시 파일+replace를 제공하지만 load→increment→write 전체 잠금은 없다. record는 write_json_atomic의 False를 무시하고 새 count를 반환하므로 성공 영수증과 실제 저장이 어긋날 수 있다. s09는 순차 increment와 corrupt 분기를 검사하며 동시 예약 보장이 아니다. s12의 eligibility 검사와 dispatch 기록도 분리되어 있다. Zeus에서는 PG의 원자적 예약·상한·fencing과 실패 환불 정책으로 연결해야 한다. 반복 손상 시 evaluator 총 실행량이 반드시 유한하다는 주석은 이 구간으로 증명되지 않는다.

<a id="f20"></a>
## ratio_tracker.py

1–78: TEMP의 공용 파일에 Read/Grep/Glob와 Edit/Write/MultiEdit 횟수를 저장한다. shell 수정이나 실질 독해 품질을 측정하지 않는다. 세션/프로젝트별 키가 없어 다른 turn의 reset·증가가 섞일 수 있고 숫자 coercion 예외도 가능하다. s21의 교체는 증가 경쟁을 막지 못하며 쓰기 bool을 무시한다. s03은 cooldown 후 advisory 문자열로만 출력한다. Zeus에는 작업별 관측 지표로 분리하고 이것을 8단계 SDD 연구·검증 완료 증거로 사용하지 않아야 한다.

<a id="f21"></a>
## reflection_recall.py

1–151: wonder의 회고 파일을 fingerprint/depth로 골라 다음 시도용 본문을 만든다. 정렬과 최대 lesson 수, fingerprint 검사는 보존할 방어다. SID 정규식은 '..'를 허용하고 symlink containment를 확인하지 않는다. lesson 수 제한이 바이트·토큰 상한은 아니다. UTF-8 decode 예외와 비문자열 fingerprint는 fail-soft 설명에서 벗어날 수 있다.

fingerprint=None이면 filename/frontmatter 불일치를 거르는 조건이 적용되지 않는다. depth가 실제 시간순서라는 보장과 작성자·모델·원인 증명의 결속도 없다. s04가 이 블록을 directive 앞에 넣으므로 회고 본문의 지시가 다음 모델에 노출된다. Zeus에서는 인용 데이터 경계, 원 실행/실패 증거·모델 자격·사람 인수와 유효 기간을 보존해야 한다. 이전 회고를 실증된 해결책으로 자동 승격하지 않아야 한다.

<a id="f22"></a>
## reflexion_loop.py

1–138: 실패 axis 이름으로 고정 fingerprint를 만들고 threshold와 같은 횟수에만 회고를 요청한다. axis가 바뀐 pending 회고를 stale로 분리하고 depth cap을 확인하는 방어가 있다. 이름만으로 fingerprint를 만들면 같은 axis의 서로 다른 실제 결함이 섞일 수 있다. 임계 횟수에서 요청/저장에 실패한 뒤 count가 더 커지면 같은 crossing이 재발하지 않는 경로도 있다.

s04는 agent body의 validators/tests 값을 bool로 변환하고 회고를 저장한다. 이 부분만으로 실제 시험 명령/receipt를 검증하지 않는다. pending은 absent/noop에도 다음 state에서 초기화된다. 실패 시 noop과 정상 no-op을 구분하기 어렵다. 실제 wonder 저장·읽기 전체 폐쇄는 미추적이다. Zeus에서는 회고를 advisory로 유지하고 PG에 요청/미응답/저장실패를 구별하여 학습 인수를 추적해야 한다.

<a id="f23"></a>
## repeat_error_tracker.py

1–174: 도구 출력의 오류 문자열을 경로/숫자 정규화 후 SHA로 묶고 TEMP 공용 파일에 24시간 횟수를 저장한다. 파일·숫자가 달라도 반복을 묶는 기능은 유용하지만 프로젝트·세션·실제 명령 정보가 키에 없어 다른 실패를 합칠 수 있다. 정상 인용도 오류로 보며 prefilter와 fingerprint 패턴의 어휘가 달라 누락 가능성이 있다. fallback은 오류 표기가 없어도 마지막 줄을 fingerprint로 만들므로 직접 호출 시 주의가 필요하다.

s03은 error 감지 후 advisory를 출력하며 그 구간은 agent spawn을 하지 않는다. 4회 경고의 영구 규칙 반영 문장은 권한 승인이 아니다. s21의 교체만으로 동시 count 손실을 막지 못하고 쓰기 실패도 소비하지 않는다. Zeus에서는 반복 증거를 작업/명령/결과 hash와 결속하고 원인 후보·검증된 해결·승인된 학습을 분리해야 한다.

<a id="f24"></a>
## repro_probe.py

1–141: transient 정규식과 비placeholder 영어 토큰 수로 오류 문구를 분류한다. 실제 명령을 재실행하지 않는 제한은 분명하다. 그러나 Probe.passed()는 무조건 True이며 fingerprint와 문구의 결속을 재계산하지 않는다. 주석의 한 토큰 설명과 실제 두 토큰 조건도 다르다. 미등록 transient 문구는 deterministic으로 분류될 수 있고 한국어 중심 문구는 과잉 거부될 수 있다.

s05는 probe.passed와 candidate.secret_scan_clean의 truthiness로 gotcha accept를 만든다. s06 시험은 분류 문구의 기대값을 검사하는 80줄 시험이며 실제 실패 재현·원인 해결·모델 행동 회귀를 검사하지 않는다. 안전하게 재현을 생략한 사실을 '재현 성공'으로 승격하면 증거 종류가 바뀐다. Zeus에서는 signature_classified와 reproduction_executed/verified를 별도 상태로 두고 사람이 인수한 경험의 출처를 남겨야 한다. 이후 실제 staging/writing 소비 전체는 미추적이다.
