# 설계 정본과 Zeus의 계약 대조 — 부분 검토

고정 harness-design 144개 중 이 보고서가 본문 전체를 검토한 설계 문서는 00-vision, 00-glossary, D-001, D-002, D-003, HARNESS-SPEC 여섯 개다. 마스터 설계서 본문 검토는 그 안에 선언된 모든 하위 시스템의 구현 검증 완료를 뜻하지 않는다. 원본에 인용된 과거 사용자 지시는 분석 자료이고 현재 세션의 권한이나 승인으로 승계하지 않는다. 외부 연구·라이선스 주장은 해당 원문을 검증하기 전까지 상류의 주장으로만 남긴다.

## 00-vision: 전체 루프와 세부 요구

페르소나 기반 GWT가 테스트 입력이 되고 설계 산출물 사이의 정합성 게이트가 있다는 요구는 Zeus SDD의 목적과 맞는다. 그러나 문서의 Java 중심 12~23단계와 Mockito/JaCoCo 100% 조건을 현재 사용자가 지정한 프론트엔드 8단계·실기기·실환경 인수 기준으로 그대로 옮길 수 없다. 설계 15→16단계 증가는 input DAG 재유도를 요구하며, 단계 번호 복사로 해결되지 않는다. 문서는 배포를 optional로 두는데 현재 Zeus 요구는 alpha/QA 승인/live/CS까지 반복되는 필수 흐름이다. 디자인 하네스 선행 조건과 wireframe→production view의 간격도 별도 완료선이다. 현재 SDD HTML은 검토 준비물이며 이 원문의 프로덕션 UI 완료에 해당하지 않는다.

원문의 '사람 개입 두 곳'과 현재 '나선별 디자인 승인·QA 증적'은 승인 대상/시점을 명시해야 한다. 과거 '메인은 관리만, 모든 실제 작업은 subagent' 규칙은 현재 '둘이 검토·논의하고 구현은 Codex' 요청으로 대체된다. 소유자 주장이나 개인용 복사 허용을 제3자 코드 공개 라이선스 허가로 해석하지 않는다. 채택 방향은 요구→시나리오→관찰→실행 증거 연결과 명시적 범위이고, 모델·도구·스택·권한·수치 기준은 Zeus 계약으로 다시 정한다.

## 00-glossary와 harness/ontology/glossary.md: 정의와 연결의 분리

정본 사전은 canary gate/poison record, event store/fold, authorization/verification, rollback/known-good/compaction/frozen snapshot을 구분한다. 이는 Zeus release·artifact·ticket·task 용어를 분리하는 데 유용하다. 그러나 사전의 heartbeat='정상 동작', silence='실패'는 Guardian 실제 코드가 구분하는 active lease/idle/unknown/material progress보다 거칠다. validatable heart='자동 OK' 역시 이후 승격 승인 개정과 결속 없이 사용하면 잘못된 권한을 암시한다. 이벤트 종수 폐쇄 9+3이라는 역사 수치는 현재 ledger EVENT_TYPES 전체를 증명하지 않는다.

harness 쪽 사전은 본문이 없는 8줄 redirect다. ontology_index.build의 glossary 분기는 그 파일 존재만 확인해 kind 노드를 만든다. 'glossary 노드 존재' 테스트는 정본 내용의 로드·용어 모순 검사·자동 드리프트 탐지를 입증하지 않는다. scripts/cron/uptake_routes.py와 해당 contract test도 이 경로를 실제 uptake 목적지에서 제외하는 이유를 명시한다. 해당 파일들의 검색 구간은 의존 근거이고 파일 전체 검토 완료로 계수하지 않는다. Zeus는 개념 식별자와 해석 원문 버전을 연결해야 하며 스텁의 존재를 기능 구현으로 세면 안 된다.

## D-001: 정본의 역할은 흡수하고 저장소 선택은 재설계

본문은 상태/이벤트=Git JSONL, 코드 파생 그래프=원천+추출기, 지식 본문=파일, inferred edge=assert/retract 원장으로 정한다. operational meta는 재생성할 수 없는 별도 로컬 상태다. golden 파일만 파생물 커밋 예외이며 생성자 재현 검증을 요구한다. 이 구분은 유용하지만 Zeus의 Git 정의/PostgreSQL 런타임 정본과 저장 위치가 다르므로 JSONL을 두 번째 런타임 정본으로 복제하지 않는다.

append-only JSONL은 자동으로 union-safe가 아니며 timestamp/event-id 정렬은 인과관계나 서로 모순된 판정의 우선순위를 증명하지 않는다. '충돌 불가' ID 주장은 실제 발급기와 재시도/독립 발생/동시 append를 검증해야 한다. projection 실패를 blocker로 만드는 원문도 범위를 구분해야 한다. Zeus는 authoritative queue와 보조 graph/embedding 장애를 분리하므로 검색 인덱스 실패가 모든 작업을 멈추게 해서는 안 된다. B→C 승격 지표는 관측/발의이지 자동 정책 개정 승인이 아니다. lib/ledger·ids·atomic_jsonl·derive_state의 전체 검토는 harness-lib 파티션에 연결한다.

## D-002: Claude Code 종속 기능의 경계

훅/스킬/커맨드/에이전트를 CC 네이티브로 쓰고 자체 런타임을 소유하지 않는다는 선택이다. CC 기능이 없는 곳에 보조 프로세스를 얼마나 둘지는 후속 의제로 남긴다. Zeus는 이미 executor/workflow/supervisor를 소유하므로 이 런타임 선택 자체는 기각하고, 도구 공급자의 세부 API를 adapter로 격리한다는 목적을 수용한다. 훅 이름·exit code·Stop 이벤트·권한 스코프·세션 이어받기의 동등성은 Codex 실제 CLI 계약과 실행 증거로 확인해야 한다. '787커밋 실증'은 현재 API 호환 증명이 아니다.

## D-003와 engine/cohesion.py: 발의 구현은 분해 구현이 아니다

D-003은 예산 초과 때 응집도가 높으면 논리 부모를 유지한 직렬 청크, 낮으면 구조 분해·부모 색인·part-of를 제안한다. 가동 표기의 실제 근거인 cohesion.py는 git co-change와 탐욕 Jaccard 군집으로 분해 **발의만** 한다. 시드 churn=8, cluster=2, merge=.3은 정책 자동 보정 구현이 아니라 상수다. git log는 최근 400커밋·name-only·40 hex SHA 판별이며 파일명 quoted path/공백 strip·SHA-256 repo에 대한 일반화가 없다. OSError/Timeout은 collect_history가 직접 잡지 않고 호출자 _curator_pass의 fail-open 로그로 간다. rc 비정상/이력 없음은 판정 불가로 명시하는 점은 수용할 만하다.

companion_clusters는 입력 순서대로 대표 집합을 확장하고 첫 일치에서 멈춘다. 동반 집합 무리 수는 순서에 영향받을 수 있고 변경 이유를 직접 증명하지 않는다. owner:none 판별은 손상 시 빈집합으로 돌아 생성물을 발의 대상에서 제외하지 못한다. _curator_pass는 대상 stem만으로 decomposition 파일명을 만들어 같은 stem의 서로 다른 경로가 충돌할 수 있다. dismissed 처분이 파일에 남으면 증거/소스 버전이 바뀌어도 다시 발의하지 않고, fresh 파일 생성 뒤 알림 append 실패 시 다음 실행은 fresh=False여서 통지가 재시도되지 않는다. '통지 큐가 있다'와 '사용자에게 전달되었다'를 구분해야 한다.

check_context_coupling의 과거 앵커는 같은 줄 날짜/당시/였다/정의상 중 하나면 줄 전체를 면제한다. 한 줄에 역사와 현재 주장이 섞이면 현재 주장도 빠질 수 있다. decision_refs는 외부 설계 저장소 부재를 메시지로 알리고 오류목록 []를 반환하므로 '검사 미실행'이 전체 exit-code PASS에 섞일 수 있다. 자동화에서 별도의 unknown/skipped 상태가 필요하다.

test_context_programming_smoke.py 본문은 전부 읽었다. 순수 Jaccard·문턱·과거 앵커 부정/긍정 검증은 있지만 l2_driver 배선은 code_only 문자열 존재로 검사한다. 알림 실제 전달·발의 충돌·동시성·기각 후 증거 변경을 실행하지 않는다. live 축은 실제 Git 이력이 필요하므로 .git 없는 blob snapshot만으로는 공백 이력을 검사 실패로 읽는다.

후속으로 원본 이력을 별도 bare 저장소에 복제하고 HEAD가 pinned commit과 같은지 확인했다. 그 이력과 pinned 파일만 network-none/read-only/nonroot/cap-drop Docker에 마운트하여 **기대값이나 원본 테스트를 바꾸지 않고 스위트가 PASS**했다. 최초 시도는 readonly source에 중첩 .git mountpoint가 없어 container 생성 단계에서 rc125였고, inert 스냅샷에 빈 mountpoint 디렉터리만 만든 재실행은 rc0이었다. 두 context-programming-receipt JSON 모두 보존했다. 활성 하네스·원본 설정·인증·호스트 Git 설정은 마운트하지 않았다. 이 PASS는 앞서 구분한 문자열 배선 검사의 한계를 해소하지 않는다.

## 처분

용어 구분, 정본/파생물 분리, GWT 입력 계약, 상태를 상시 프롬프트에서 빼는 원칙, 근거 있는 분해 발의는 adapt 후보다. CC 네이티브 실행 전제·Git JSONL 런타임 정본·원문 권한/승인·스텁으로 기능 완료·고정 수치로 모델 자격 승계는 수용하지 않는다. 이 문서는 부분 의미 검토이며 새 Zeus 기능 구현, 전수 분석 완료, 도입 승인, 실제 배포를 뜻하지 않는다.

## HARNESS-SPEC: 전체 본문과 부록에서 확인한 추가 모순

이 파일은 항목 정본을 종합한 뷰이며 충돌 시 결정 문서가 이긴다고 스스로 선언한다. 부록 A는 결정→절 위치의 매핑이고 구현/실행의 완전성을 증명하는 표가 아니다. D-050 결정이 실제 인벤토리에 있지만 이 마스터의 동기화는 D-049까지다. 2026-08-13 머리말의 '갭 0'과 부록 C의 미해소 모순 여섯 개는 시간/범위가 달라 현재 완료 주장으로 함께 사용할 수 없다. C-1~6의 사람 개입, 승격 자동성, CLI 개수, 에이전트 통신, 상태 숫자, fleet 가용성을 그대로 보존하고 Zeus 사용자 요구로 각각 새 결정을 내려야 한다.

구체적으로 §7 lease의 '단일 트랜잭션·양측 fencing'은 선언이다. harness-lib 검토가 확인 중인 파일 삭제/손상 후 epoch 재사용과 owner 미확인은 이 보장과 충돌하는 후보이며 실제 probe 결과와 결속해야 한다. §22 외부 액션 멱등성을 Temporal activity 캐시와 동형이라고 부르는 것도 파일 dedup 검사+append 사이 경쟁/외부 side effect lost-ack를 증명하지 않는다. §12 known-good '원자 swap'은 Guardian restorer의 여러 git checkout/unlink 연속 동작과 다르다. 그 절의 Inconclusive 자동 rollback은 Zeus의 observation_error 별도 상태와도 다르다. 어느 쪽이든 특정 의미/정책을 선택한 것이지 동일 구현으로 취급하지 않는다.

§4 전제 지문을 완료 fold 밖의 행동 선택에 둔 이유는 재생 결정론을 보존하기 위해서다. 반면 '지문 없는 과거 판정은 낡음이 아니다'는 이행 정책이므로 과거 판정을 신선하다고 검증한 것과 구분해야 한다. §5 unknown 이벤트 무시와 §6 출력 존재≠PASS, evaluator 오류=ERROR/blocker가 함께 작동하려면 fold 소비자가 ERROR/REJECT/PARTIAL/새 revision을 어떻게 처리하는지 모든 읽기 경로를 대조해야 한다. stale success를 읽는 별도 helper 하나가 있어도 게이트가 우회될 수 있다.

§6 완료선은 증거 경로 존재까지 검사한다고 정직하게 제한한다. 이를 '재탐색 없는 착수'나 의미 검토 승인으로 확장해서는 안 된다. 같은 절의 included/excluded 구조는 범위 누락 방지에 유용하지만 excluded 최소 1건을 강제하면 실제 범위의 완결 여부와 무관하게 제외 항목을 만들 동기가 생긴다. Zeus에서는 계약상 범위와 미검토를 원장에 남기고 분모를 줄이지 않는 것으로 해결한다. scopes 검사는 동일/상위 디렉터리만 다룬다는 한계가 있으며 일반 glob의 비겹침 증명이 아니다.

§8 fixed prompt/frozen snapshot/byte-identical prefix는 토큰 재사용 목적이며 correctness와 독립이다. §11 frugality proof의 쌍대 대조·무회귀·임계·증거는 수용 가치가 있지만 캐시 token fraction을 비용 감소율로 읽지 않고 실제 모델별 입력·캐시·출력 단가/실행 수/품질을 함께 재야 한다. Astra→Sol→Terra는 고정 이름 교체가 아니라 같은 계약·대표 실패·난도별 회귀를 통과한 작업 유형에만 하향하는 현재 사용자 요구로 재설계한다.

§13 reverse는 구조/의도/행위를 분리하고 코드에 없는 의도를 사람이 복원하도록 한다. 현재 사용자 '핵심 시나리오는 사람 머릿속'과 맞는다. 구조 추출 confidence 숫자만으로 인수 시나리오의 기대값을 자동 발명하지 않는다. §16 orphan/DRIFT를 관찰로 두고 배포 버전·소유 귀속 선언 뒤 판정화하는 것도 유용하다. §17 디자인 토큰/Code Connect/Figma 외부 표현, design-critic 실제 멀티뷰포트 렌더는 현재 SDD 준비물에 아직 없는 기능이다. 외부 SDK/표준의 현재 호환성은 별도 1차 출처 연구와 실측이 필요하다.

§23 hook failure policy는 완료 판정의 fail-closed와 훅 프로세스 크래시의 fail-open을 분리한다. 이 분리를 잃으면 '거부됐으니 안전' 테스트가 모든 입력에서 죽는 판정기도 통과시킨다. HK-1 이벤트당 단일 디스패처는 순서 비보장 문제에 대한 구현 후보지만 Baldrix settings의 여러 병렬 훅을 그대로 복사해서 같은 보장을 주장할 수 없다. OTel projection도 이벤트·phase·actor·evidence를 내보내는 설계이며 원문 프롬프트 전문 로깅을 의미하지 않는다.
