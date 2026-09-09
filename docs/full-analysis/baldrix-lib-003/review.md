# Baldrix lib 003 독립 정적 검토

정본은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`이다. primary 10개, 188,707바이트의 전문을 읽었다. 실제 읽은 supporting 구간은 supporting.json에만 계상한다. 본문에 있는 실측·LOCK·승인·테스트 PASS는 원저자의 과거 주장이다. 이번 원본 실행, import, 테스트, 프로브는 모두 0회다. 각 항목의 상태는 `body_reviewed_call_test_trace_pending`이며 전체 호출 전이 검증이나 채택 승인을 뜻하지 않는다.

## 공통 판단

평가 표, 평가 실행, 완료 승인, 영구 저장 성공은 별개의 사실이어야 한다. 이 범위에는 provider 문자열과 모델의 JSON 응답을 검증된 실행 영수증처럼 해석할 여지가 있다. 로컬 JSON/JSONL을 runtime 판정의 근거로 쓰는 구조는 Zeus의 PG runtime SSOT와 직접 같지 않다. Git에는 사람이 검토한 정의·정책·SDD 산출물을 두고, 실행·예산 예약·완료·권한·인수 영수증은 세대와 식별자를 묶은 PG 트랜잭션으로 관리하는 방향을 검토할 수 있다. 이는 대응 제안이며 이번에 Zeus 구현을 읽어 등가성을 입증한 결과가 아니다.

사람이 정한 8단계 SDD의 순서와 단계별 산출물 수용 조건은 단순 파일명, `phase_id`, `approved` 문자열이나 표 수로 증명되지 않는다. 경험 인수에는 원자료·실패·후속 수정·재현 범위·사람의 승인 주체가 필요하다. 본문의 경험 서술을 자동으로 정책이나 실행 권한으로 승격하면 안 된다. Windows/Linux/WSL에서 동일한 인증 환경, 프로세스 종료, 경로, 파일 잠금, 시계·타임존을 검증한 영수증은 이 정적 검토에 없다.

<a id="f01"></a>
## 1. ensemble_evaluator.py

전문 1–895. 입력 표의 ID/provider/verdict/bool 일부를 검사하고, `ceil(N/2)`와 최다 표로 집계하며 동률은 escalate로 처리한다(298–471). 이는 엄격한 과반과 다르다. 예를 들어 4표 중 approved 2, iterate 1, escalate 1은 승인 가능하다. ID/provider의 중복이나 실제 독립 호출 영수증을 확인하지 않으므로 표의 수가 독립 평가자의 수를 보장하지 않는다. provider는 공백 제거 없이 접두사를 검사하고 허용 플래그로 검사를 완화한다. 실 모델 자격 검증이 아니다.

completeness는 집계 승인 조건이 아니다. 자체 시험 637–646은 completeness가 false인 표가 포함돼도 approved를 기대한다. paradox 플래그가 false이면 승인을 escalate로 바꾸지만 split은 그대로 false일 수 있다. 따라서 split만 확인하는 소비자는 이 구분을 놓칠 수 있다. 이벤트 emit 예외는 삼킨다. `ensemble.aggregated`는 이번 event_taxonomy의 알려진 이름에 없다. 앞부분의 미연결/advisory 설명과 마지막 CLI 안내는 dispatcher의 실제 집계 호출(1182–1215)과 시점이 맞지 않는다.

489–883의 자체 시험도 전문으로 읽었으나 실행하지 않았다. meta_rules ImportError를 성공 취급하고 skipped 설명을 성공 출력에서 숨기는 분기(805–883)가 있어 출력 PASS를 전체 의존성 검증으로 볼 수 없다. Zeus 대응: 평가 실행별 중복 방지, 자격 증거, 객관 수용 조건 및 저장 영수증을 집계와 별도로 요구해야 한다. 전체 최종 gate 호출자는 미검증이다.

<a id="f02"></a>
## 2. evaluator.py

전문 1–294. 모델명 환경 설정, 축 점수 자료형, paradox/completeness/clamp 도우미를 제공한다. 모델의 접두사 금지와 환경 변수 예외는 실제 생성자·평가자 식별이나 승인 출처 검증이 아니다. 자료형 주석과 dataclass만으로 1–5 점수나 bool 입력이 강제되지 않는다. bool의 truthiness 및 int 하위형 관계 때문에 호출자가 엄격한 스키마를 선행하지 않으면 문자열 값 등을 의도와 다르게 해석할 여지가 있다. clamp는 approved에 한정되며 알 수 없는 verdict를 전면 검증하는 스키마가 아니다.

dispatcher의 성공 표는 독립적으로 모델 응답에서 구성되고 fallback에만 이 completeness 함수를 사용한다. 따라서 도우미의 존재를 모든 호출 경로의 완료 차단으로 확장할 수 없다. 전문 안의 테스트 조건 설명은 실행 영수증이 아니다. Zeus 대응: 사용자 정의 단계의 검증 결과를 typed receipt로 전달하고, 누락·실패·미실행을 서로 다른 상태로 보존해야 한다. 외부 evaluator 전용 시험의 전수 대조는 남아 있다.

<a id="f03"></a>
## 3. evaluator_dispatcher.py

전문 1–2311. quota 조회/증가, 프롬프트 구성, subprocess 호출, JSON 추출, fallback, 앙상블, 축 로그 및 residual 원장 변경을 한 모듈이 담당한다. 문서의 격리 주장은 구현의 범위보다 넓다. 금지 문자열 검사는 프롬프트 내부 규칙이며 artifact가 신뢰할 수 있는 명령이 되는 것을 막는 OS 경계가 아니다. 환경 필터는 HOME/USERPROFILE/APPDATA/PATH 등 일부를 남기며 subprocess의 cwd를 새 격리 디렉터리로 바꾸지 않는다(347–585). read-only CLI 인자는 인증·네트워크·컨텍스트의 전체 격리 증거가 아니다. Windows cmd/bat 분기는 shell을 사용한다. 270초 timeout은 자손 프로세스 전체 종료 보장을 입증하지 않는다.

기본 pool은 Codex와 가용한 Claude로 구성된다(862–945). Claude가 있으면 같은 생성자 계열 허용을 자동 설정한다(1120–1134). 과거 운영자 결정이라는 주석은 이번 사용자 권한이나 실 모델 자격 증명이 아니다. 기본 Codex lambda와 모델 해석 도우미의 연결 또한 문자열 설명만으로 입증되지 않는다. custom invoke는 호출자가 제공하며 이 모듈이 동일 격리·timeout을 강제하지 않는다. pool 순회는 순차 호출이다.

성공 JSON 표 구성은 `paradox_guard_passes=True`를 실행 성공 의미로 넣는다(946–998). 객관 validators_passed/units_passed/known_defects는 fallback에서 쓰지만 성공 표 경로를 다시 차단하지 않는다. 최종 aggregate 후 원장 기록이 먼저 이루어지고 verifier cross-check는 결과를 바꾸지 않는 관측 신호다(1182–1215). JSON 추출은 답변 중 객체를 골라낼 뿐 최종 응답/실행과 결합한 인증된 envelope가 아니다. 점수의 int 필터가 1–5 범위나 축 이름까지 보장하지 않는다.

quota_tracker 전문에서 load→증가→atomic write가 하나의 잠금/트랜잭션이 아님을 확인했다. 실제 milestone_step 167–215도 should_dispatch→외부 호출→record_dispatch 순서이며 실패 호출은 quota 기록 전 반환한다. 동시 승인과 갱신 손실, 실패 반복 비용의 상한은 미보장이다. 읽기 경로도 quota 디렉터리를 생성한다. 손상/읽기 실패를 0으로 처리하는 정책을 비용이 항상 몇 회로 한정된다는 증명으로 볼 수 없다.

1262–1418의 known_defects 읽기는 누락/손상을 0과 섞고, 원장 변경은 append-only라는 설명과 달리 일치 파일의 last_eval_ts/last_verdict를 덮어쓴다. 실행 세대·artifact hash·fence 없이 모델 verdict가 먼저 복제될 수 있다. 1421–2311 자체 시험에는 mock 호출, 임시 원장 쓰기, 환경 변경, provider 가용성 조회가 있다. 일부 예외를 성공으로 받아들이거나 skip을 성공 출력에서 숨긴다. 이번에는 실행하지 않았다. scripts 검색에서 실제 단일 호출자는 milestone_step을 확인했지만 production ensemble 최종 gate의 closure는 확인하지 못했다. Zeus 대응: 호출 전 예산 예약, 실패 비용 기록, 검증 영수증에 묶인 완료 트랜잭션, 평가 자격 및 사람이 승인한 예외가 필요하다.

<a id="f04"></a>
## 4. event_store.py

전문 1–117. 세션 디렉터리와 JSONL을 만들고 append/replay/last 조회를 제공한다. session_id 경로 제한이 없고 생성자에서 디렉터리를 만든다. payload SHA-1 일부는 actor/gen/event_type/순서를 결합하지 않으며 replay 때 재검증하지 않는다. 중간 JSON 손상은 telemetry를 내고 그 행을 버리며 마지막 손상 행은 조용히 버린다. 정상 JSON의 자료형이나 파일 읽기의 모든 오류를 처리하지 않으므로 “never raises” 설명은 모든 입력·I/O에 대한 보장이 아니다.

telemetry_log 27–31은 일반 append write이며 명시적 lock/fsync/원자적 다중 writer 보장이 없다. engine/cli 전문은 생성자로 읽기 경로도 디렉터리를 만들고 last verdict를 출력함을 보여준다. test_event_store 175–217은 손상 후 정상 행 반환 및 tail 경고 생략을 기대한다. 실행·동시성 시험은 하지 않았다.

중요한 직접 연결: agent_outcome_audit 138–158은 `from lib.event_store import append`를 시도하지만 이 파일에는 module-level append가 없고 `EventStore.append`만 있다. 그 예외가 삼켜져 해당 emitter 경로에서 기록이 없어질 수 있다. 이는 pinned 코드 연결의 정적 불일치이며 현재 host에서 재현한 결과가 아니다. Zeus 대응: 손상/누락의 명시 상태, 이벤트 ID·세대·인증된 actor·transaction commit 영수증이 필요하다.

<a id="f05"></a>
## 5. event_taxonomy.py

전문 1–123. 알려진 이름 집합과 알 수 없는 이름의 telemetry 경고를 제공한다. emit을 먼저 실행한 다음 이름을 검사하므로 허용 목록 기반 차단기가 아니다. emit 예외를 삼키며 알려진 이름이라는 이유로 저장 성공이 보장되지 않는다. payload 스키마·권한·세대·중복은 검사하지 않는다. heartbeat 예약 설명과 실제 집합 내용도 일치하지 않는 부분이 있다. ensemble.aggregated가 알려진 집합에 없다는 사실은 이벤트 호출 자체를 금지하지 않는다.

직접 caller는 agent_outcome_audit 147–158이다. 그 caller의 원시 emitter 이름 불일치와 결합하면 taxonomy 검증이 있어도 기록 성공을 주장할 수 없다. Zeus 대응: 관측 경고와 영구 이벤트 수용 결과를 분리하고 schema/version/발행 주체를 검증해야 한다. 독립 taxonomy 시험 본문은 이번에 읽지 않았다.

<a id="f06"></a>
## 6. file_matchers.py

전문 1–137. 경로 문자열로 18종 산출물·코드를 분류한다. 파일 존재, 문서 내용, 8단계 SDD의 완료·순서·품질을 검증하지 않는다. suffix/substring의 대소문자와 앞 슬래시 조건 때문에 상대 경로·Windows 대소문자·다른 언어 구조에 따라 누락 또는 넓은 매칭이 가능하다. openapi 접미사는 정확한 basename 검사가 아니다.

reviewer 38–45에서 import한 함수가 167–205 DAG에 저장된다. 309–359는 슬래시를 정규화하고 cooldown/hash 조건으로 검사 실행 후보를 만든다. 445–457에서 같은 이름 is_code_file을 다시 정의하지만 이미 DAG에 저장된 함수 참조를 바꾸지 않는다. 따라서 알림용 코드 판정과 DAG 판정이 다른 범위를 가질 수 있다. 다운스트림 validator 전체의 실효성/실행 성공은 미검증이다. Zeus 대응: 경로 분류를 진입 힌트로만 쓰고 사람이 정의한 SDD 산출물 ID 및 실제 검증 영수증으로 완료를 판단해야 한다.

<a id="f07"></a>
## 7. frontmatter.py

전문 1–62. BOM을 허용하는 UTF-8 읽기, 간단한 delimiter/colon 분해, raw 문자열 반환, 섹션 추출 도우미다. 완전한 YAML parser가 아니다. delimiter는 줄 단위 fence만으로 제한되지 않고 중복 키는 마지막 값이 남는다. 섹션 검색도 코드 fence 문맥을 파싱하지 않으며 제목 접두사의 여분 문자열을 허용한다. unreadable/malformed None은 호출자에게 정책 부재처럼 보일 수 있다.

agent_outcome_audit 88–126은 없거나 읽지 못한 schema를 건너뛰며 JSON schema 해석 실패도 해당 층을 끈다. skill_match 367–410은 parser 실패 파일을 제외하고 pipeline boost로 매칭을 강제할 수 있다. 시험 test_frontmatter_norm 99–112는 BOM만의 회귀 의도를 보여준다. Zeus 대응: 권한/자격/수용 조건 정의는 명시 schema와 오류 상태로 검증하고 조용한 부재와 구분해야 한다. 모든 parser 소비자 및 악성 문서 시험은 미검증이다.

<a id="f08"></a>
## 8. frontmatter_norm.py

전문 1–60. 공백/쉼표 목록, 정확한 H2 제목 검사, 첫 필드 치환을 중앙화했다. 인용된 쉼표나 공백을 포함한 YAML 문자열의 의미를 보존하는 tokenizer는 아니다. ensure_field는 첫 중복 키를 바꾸지만 frontmatter parser는 마지막 키를 사용하므로 “수정한 값”과 “읽힌 값”이 다를 수 있다. re.sub replacement에 값을 직접 넣어 backslash 치환 문법이나 줄바꿈에 대한 일반 입력 계약도 별도로 필요하다. 실제 harness_normalize 77–94의 값은 HARNESS_COMMANDS에서 오므로 이 경로에 외부 입력이 직접 도달한다고 주장하지 않는다.

test_frontmatter_norm 1–120은 기본 목록/제목/첫 필드/BOM 기대값을 포함하지만 인용·중복 키의 end-to-end 의미 대조를 여기서 보지 못했다. Zeus 대응: 하나의 schema/parser로 정의 편집과 실행 해석을 맞추고 원문 변경을 사람의 정책 승인으로 대신하지 않아야 한다. normalization 명령은 실행하지 않았다.

<a id="f09"></a>
## 9. git_flow_override.py

전문 1–103. 최대 6단계 상위 디렉터리에서 override 문서를 찾아 제한된 키를 읽는다. solo는 mode=solo와 direct_push_main=allow를 모두 요구하며 company는 별도 조건이다. parser는 첫 중복 키를 택해 일반 frontmatter의 마지막 키 정책과 다르다. UTF-8 BOM 처리도 다르다. 가장 가까운 잘못된 파일에서 빈 설정을 반환하며 상위 정책까지 계속 탐색하지 않는다. 탐색은 프로젝트 경계/신뢰 주체를 강제하지 않고 resolve 등의 모든 예외를 내부에서 처리하지 않는다.

guard 205–253은 Bash만 검사하고 solo_override 태그가 붙은 DENY를 WARN 후 허용으로 바꾼다. 이것이 parser의 실 권한 효과다. 주석의 사용자 결정과 실제 현재 사용자 승인은 별개다. test_git_flow_override 28–87은 두 키 조건, 본문 무시, 허용 키, 임시 디렉터리의 상위 정책 유입 가능성을 보여준다. 규칙 regex 전체와 host 도구 정책은 이번에 검증하지 않았다. Zeus 대응: Git 정의를 runtime 권한으로 사용하려면 승인 주체·프로젝트 경계·정의 revision을 고정해야 한다.

<a id="f10"></a>
## 10. golden_signals.py

전문 1–375. latency/traffic/errors/saturation에 값·분모·맹점을 함께 보여주고 표본 없음은 None으로 나타내는 점은 유용하다. 종료 성공과 계약 결과를 분리하는 resident_store 140–183 및 test_golden_signals 90–109도 같은 의도를 뒷받침한다. 그러나 이 시험의 “실측 2회” 설명은 이번 실측이 아니다. resident의 압축 후 contract bool을 신뢰하는 경로는 원자료·계산 버전·인수 승인을 별도로 보존해야 한다.

손상 resident 행과 읽기 실패/손상 dispatch 행은 지표 표본에서 빠진다(77–101). 정상 JSON의 비객체 값은 후속 처리 오류를 낼 수 있다. _span_days는 timezone 부분을 버리고 mktime을 사용해 혼합 offset/DST에 영향을 받을 수 있다. 실행 시간의 0 필터, 문자열 변환, 현재 DEFAULT_TIMEOUT=900을 과거 전 행의 분모로 쓰는 방식은 실제 실행별 상한과 다를 수 있다. 최근 10개와 전체 기간 구분은 유용하지만 완전한 수집 커버리지나 lease 활성성을 증명하지 않는다.

명시 --probe는 실제 home/scripts의 hook subprocess를 실행하는 효과가 있다. 이번에는 호출하지 않았다. config settings 306–317은 SessionStart를 절대 Windows 경로와 timeout 5로 호출한다. 합성 probe의 timeout/환경을 실제 host 훅 계약과 같다고 볼 수 없다. 6시간 스케줄 주장은 이번 scheduler 설정까지 추적하지 않았다. cli/signals 전문의 EXIT_NOTHING은 flat이 비었을 때만 반환한다. 신호 객체가 모두 unknown이어도 warn이 없으면 EXIT_OK가 가능하므로 0만 읽는 소비자는 데이터 부재를 건강 상태로 오해할 수 있다. Zeus 대응: 수집 누락·손상·표본 없음과 정상의 별도 상태, 실행별 시간/예산, 플랫폼별 실제 영수증이 필요하다.
