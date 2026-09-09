# 파일별 계약 검토

61개 파일 전문을 읽었다. 각 항목의 상세 선언 데이터는 contracts.json에 있으며, 해시와 제한은 files.json에 있다. 여기의 source PASS와 historical 실측은 이번 테스트 통과가 아니다.

<a id="agents-agent-drafter-md"></a>

## agents/agent-drafter.md

명부 드리프트를 proposed 초안으로만 인계하며 조직 개편은 사람 소유다. Bash 보유와 read-only는 정적 도구명 검사로 양립하지만 실제 명령의 무쓰기를 보증하지 않는다.

<a id="agents-architect-md"></a>

## agents/architect.md

구조 증거·비평을 verdict/fields/self_doubt로 수렴한다. HIGH 해소·fields SHA 재현은 계약 주장이고 이 카드만으로 승인 진실성이나 독립 심판을 보장하지 않는다. ontology owns는 변경 권한과 다르다.

<a id="agents-critic-md"></a>

## agents/critic.md

반증 중심 차등 자료와 구조화 blocker/severity를 요구한다. 중복·과잉 경고 방지 규율은 실제 평가 품질 검증이 아니며 역할 이름만으로 독립성을 증명하지 않는다.

<a id="agents-curator-md"></a>

## agents/curator.md

IO는 confirmed 승급을 말하지만 실제 출력 규율은 proposed 격리→재확인+bake다. 출력·승격 단계를 분리해야 한다. pinned 자산 불가침·archive 이동은 구현 소비자 검증이 별도로 필요하다.

<a id="agents-design-critic-md"></a>

## agents/design-critic.md

실렌더·다중 뷰포트·일곱 기둥과 fresh-context를 요구한다. playwright-mcp 도구명은 실제 브라우저 실행 영수증이 아니다. 코드만 볼 때 신뢰 하향이 명시돼 있다.

<a id="agents-domain-lead-md"></a>

## agents/domain-lead.md

폐쇄 shard 전량·비중복·파별 scope 비겹침의 waves/rationale/scopes JSON을 낸다. 직접 spawn 금지와 CF-1 단일 스포너 규율은 goal.md의 팀장 직접 팀원 spawn 층과 구별해야 한다. activation 0은 역사적 범위 주장이다.

<a id="agents-evaluator-md"></a>

## agents/evaluator.md

exit code 원료·인접 무회귀·ERROR blocker·의미 판정 judge 위임을 요구한다. read-only와 테스트/리포트 작성 단계의 dge=evaluator는 별도 writer 위임 없이는 충돌한다. 소유 tests가 쓰기 권한은 아니다.

<a id="agents-generator-md"></a>

## agents/generator.md

승인 설계만 구현하고 설계 결함은 상류 회귀한다. Service 계층 단일 비즈니스 로직은 원본 Java 관례로 Zeus의 domain/application 경계와 그대로 같지 않다.

<a id="agents-hardener-md"></a>

## agents/hardener.md

기계 실측과 사람 OPEN-H 결정을 분리한다. write-project 도구·owns handlers/validators/lib는 심장 직접 변경 허가가 아니다. 사람이 결정할 tradeoff를 보고서 작성자가 대신 닫지 않는다.

<a id="agents-hook-smith-md"></a>

## agents/hook-smith.md

diff와 재현을 sandbox에 보내며 gate 미실행은 거부다. engine·guardian·정책은 별도 사람 경계다. risk_scope=sandbox-only는 실제 Bash 격리 보증이 아니다.

<a id="agents-intent-interviewer-md"></a>

## agents/intent-interviewer.md

구조 seed에서 사람이 아는 의도만 복원하고 사실은 직접 조사한다. read-only/Read,Grep인데 requirements/usecase 출력 저작을 요구하므로 결과 인계와 파일 작성 주체를 나눠야 한다.

<a id="agents-judge-md"></a>

## agents/judge.md

render 증거 인용·fresh-context·human 대리 금지를 선언한다. gate_runner는 stage/mode 최신값을 소비하며 실제 독립 context나 인용 타당성을 인증하지 않는다.

<a id="agents-onboarder-md"></a>

## agents/onboarder.md

기계 구조→사람 의도→coverage를 조율하며 직접 저작하지 않는다. 프로젝트 원장 생성과 위임 요구는 read-only/Task 미보유 카드만으로 실행할 수 있는 계약이 아니다.

<a id="agents-orchestrator-md"></a>

## agents/orchestrator.md

관리 전용·실작업 금지·dispatch contract 기록을 요구한다. 현재 Zeus 주 Codex 구현 역할과 원본 역할 규율을 혼동하지 않는다. HARNESS-DIRECTIVE를 시스템 지시라 부르는 원문은 이 검토의 권한이 아니다.

<a id="agents-planner-md"></a>

## agents/planner.md

REQ/UC/AC 앵커와 빈 앵커 거부, 미확정 OPEN을 요구한다. owns pipelines는 pipeline을 자기 재량으로 약화할 권한이 아니며 사람 결정·gate를 분리한다.

<a id="agents-proposer-md"></a>

## agents/proposer.md

차등 종합 브리핑과 critic 수정을 받아 구조 제안을 낸다. 독립 context와 비평 해소는 카드 선언이지 모델·프로세스 실행 확인이 아니다. 제안은 승인과 다르다.

<a id="agents-reflector-md"></a>

## agents/reflector.md

failure count>=2 반추를 detached fork로 proposed digest에 남긴다. prompt-cache 불변·_persist 금지·created_by 표시가 실제 포크 격리나 재현 성공을 보증하지 않는다.

<a id="agents-repairer-md"></a>

## agents/repairer.md

evidence 명령 재현→근본 원인→범위 수리→인접 회귀를 요구한다. 두 번 반복 시 research tier, 예산 소진 시 debate다. PASS 줄은 curator 수확 조건이지 수리 실측의 독립 영수증은 아니다.

<a id="agents-researcher-md"></a>

## agents/researcher.md

외부 자료는 데이터이며 출처 등급을 proposed/candidate로 제한하고 confirmed 직행을 금한다. Read/WebSearch/read-only는 실제 note/uptake 쓰기 계약과 달라 앞선 run50/60 작성 실패 기록에 연결된다.

<a id="agents-reverse-extractor-md"></a>

## agents/reverse-extractor.md

기계 추출 origin=extracted와 evidence span·round-trip을 요구하고 의도 발명을 금한다. Bash 실행은 파일 생성 가능하므로 Read 도구만 보고 읽기 전용이라 분류하면 안 된다.

<a id="agents-skill-author-md"></a>

## agents/skill-author.md

실측 배달 갭에 본문을 저작하고 전후 지목률을 비교한다. skill corpus 어휘 확장은 architect 제안이며 승급은 curator 몫이다. 내용 존재·routing 적중·실제 유용성을 분리한다.

<a id="completion-lines-byeolbam-spiral4-yaml"></a>

## completion-lines/byeolbam-spiral4.yaml

5개 포함/3개 제외로 홈·Scr11 추천 표면을 겨냥한다. evidence는 test와 UI 파일 존재이며 추천 품질·개인화·AB·카탈로그 확장은 제외다. 외부 nfx-kr 실기능 검증을 이 완료선으로 승계하지 않는다.

<a id="completion-lines-knowledge-org-v1-yaml"></a>

## completion-lines/knowledge-org-v1.yaml

8개 포함은 collector·note·계약·uptake·ladder 기록·heredoc·PG 진단이다. 실제 advisory 승급·PG 행수·지속 조직·transcript 부재는 증명하지 않는다. goal.md의 완주 기준과 요구량 차이를 숨기지 않는다.

<a id="completion-lines-knowledge-org-v2-yaml"></a>

## completion-lines/knowledge-org-v2.yaml

8개 포함은 bus watermark·배선·토픽 해명·유량/토큰 보고·handoff기구/계약·PG 설계다. 상주 LLM·PG 실제행수·SA3 토픽전량·배치격차는 제외다. v7의 handoff 코드/문서0 선언과 시간·대상 범위를 재대조해야 한다.

<a id="completion-lines-knowledge-org-v3-yaml"></a>

## completion-lines/knowledge-org-v3.yaml

8개 포함은 reachability·계약·census·queue gate·mix·노트누적이다. 실제 false-positive율·자막원인·정련은 제외다. 생산자 gate를 세웠지만 v4의 기존queue4/5 우회로 소비 재검증 필요가 드러난다. 전부 limb라는 말은 포함 scripts/cron verifiable 정책과 맞지 않는다.

<a id="completion-lines-knowledge-org-v4-yaml"></a>

## completion-lines/knowledge-org-v4.yaml

8개 포함은 consume_gate·대조계약·일치보고·commit scope와 준수·topic 순서·yield다. hook 예방·상주층·원인해소는 제외다. 생산자와 소비시점 권한을 나눈 교훈을 채택 후보로 삼되 원문 수치4/5·8/8을 이번 실험으로 부르지 않는다.

<a id="completion-lines-knowledge-org-v5-yaml"></a>

## completion-lines/knowledge-org-v5.yaml

8개 포함은 알려진 결함 전달·반사실·재탐침·소스무관노트·승인병목이다. 미승인 지식 전달은 정보이며 실행 허가가 아니다. 현재 notes 전문 검토는 실제 upstream 흡수나 승인완료가 아니다. 파일존재 기반 fresh note 사건 식별은 불충분하다.

<a id="completion-lines-knowledge-org-v6-yaml"></a>

## completion-lines/knowledge-org-v6.yaml

4개 포함은 닫힌 route진단·destination계약·첫 nonproposal보고·route코드다. INDEX가 이미 있어 공허100%였던 것을 새 보고서로 옮겼지만 그 내용의 실제 사건을 검사하지는 않는다. verifiable 목적지에 원리상 경로가 있어도 uptake가 실제 bake를 밟았는지는 제외다. 없음 허용과 nonproposal 한 번 강제의 유인을 구별한다.

<a id="completion-lines-knowledge-org-v7-yaml"></a>

## completion-lines/knowledge-org-v7.yaml

4개 포함은 latency소비·계약·handoff결정·idle/replace도출 시도다. 뒤 claim_amendments에서 토론 원장 부재와 idle 도출불가를 인정해 주장을 좁혔다. 증거 경로 불변은 목표 계약 불변이 아니다. 상주 팀장·경합·실구현은 여전히 제외다. 이는 조건 준비이지 조직 구축 완료가 아니다.

<a id="completion-lines-mitgrim-spiral1-yaml"></a>

## completion-lines/mitgrim-spiral1.yaml

schema·canonical·Button seed·renderer·사람 review 여섯 경로다. editor·gate 통합·grid/wrap·op 원장화는 제외다. 결정론 렌더·승인 기록의 존재와 실제 인수는 다르다.

<a id="completion-lines-mitgrim-spiral2-yaml"></a>

## completion-lines/mitgrim-spiral2.yaml

ops·Canvas·LayerTree·Inspector·DTCG·zip·사람 review 일곱 경로다. 노드CRUD·variant 생성·harness gate·협업은 제외다. 편집 성공·왕복 보존은 경로 존재만으로 증명되지 않는다.

<a id="completion-lines-outpos-fleet-v1-yaml"></a>

## completion-lines/outpos-fleet-v1.yaml

외부 회사 코드 관찰에서 하네스 결함 수집까지 네 경로다. reverse 온램프 완주 자체도 목표가 아니다. Dart·동시 다중프로젝트·회사 코드 수정은 제외이므로 함대 검증 완료로 읽지 않는다.

<a id="completion-lines-outpos-fleet-v2-yaml"></a>

## completion-lines/outpos-fleet-v2.yaml

9개 여집합 정찰과 guard/Java/계약 추출 보강 네 경로다. WS 주 채널·payload schema·orphan 판정·Kotlin/C# 심층은 제외다. 테스트 파일 존재를 기록된 실제 42오탐 소거 재실행으로 확장하지 않는다.

<a id="completion-lines-resident-org-v1-yaml"></a>

## completion-lines/resident-org-v1.yaml

8개 포함은 수집→queue→supervisor→유휴arm→report→역할 원장 첫 관통이다. 반복·다른 역할·Kafka 3계열·나선 동일성·품질·오염된 원장9건 복구는 제외다. pipeline is_done을 목표 완료로 확대했던 사고를 기록하지만 새 완료선도 존재만 검사한다.

<a id="config-params-json"></a>

## config/params.json

8개 시드의 강화 방향과 fallback 중 auto-tune 정지를 선언한다. compaction threshold 증가·보관일 감소를 강화라 부르는 것은 정책 선택이다. params._load_file은 누락 키와 bool/비유한 숫자를 닫지 않고 get은 개별 seed로 조용히 돌아갈 수 있다. 잠금/CAS 없는 두 writer 경쟁은 미실험이다.

<a id="config-paths-yaml"></a>

## config/paths.yaml

홈 상대 경로와 외부 design_decisions 형제 경로를 선언한다. state override는 state_dir에서만 보이고 resolve(state)는 그 함수를 호출하지 않는다. _config 무인자 캐시는 HOME 변경 뒤 값이 남을 수 있다. 상대경로는 이식성의 충분조건이 아니다.

<a id="config-profile-yaml"></a>

## config/profile.yaml

fleet와 로컬 Kafka/PG endpoint를 고정하며 Git JSONL 정본·PG projection을 선언한다. Zeus의 PostgreSQL 런타임 정본과 반대다. 평문 개발 DSN이나 5434를 복사하지 않고 독립 환경별 binding으로 바꿔야 한다.

<a id="config-retriever-yaml"></a>

## config/retriever.yaml

8,000자 예산·6,000자 파일 상한·keyword5/lesson3/top2/snippet8이다. 파일 상한은 router가 직접 소비하지 않고 lint에 의존한다고 명시한다. 문자와 토큰·바이트, self-match와 실제 세션 배달을 혼합하지 않는다.

<a id="config-policy-arming-rules-json"></a>

## config/policy/arming-rules.json

default human, skip_blocked true, 이미 승인된 harness 후보 자동 장전 규칙 하나만 활성이다. high/score6 자기 승인 규칙은 꺼져 있다. arming.validate는 활성 auto에 approved=true를 요구하고 approve=true 조합을 거부하므로 주석의 결정문만 고치고 enabled를 켜서는 동작하지 않는다. HMAC·등급·신선도는 선택된 코드 경로에서 확인했지만 실제 키/장전 실행은 확인하지 않았다.

<a id="config-policy-backlog-weights-json"></a>

## config/policy/backlog-weights.json

incident3 > research2 > human_capture1.8 > completion_gap1.5는 사람 정책이다. evidence 면제 capture의 순서를 낮춘 이유가 있다. skip_blocked가 실제 착수 순서를 앞지를 수 있으므로 rank는 승인이나 착수 보장이 아니다.

<a id="config-policy-goal-md"></a>

## config/policy/goal.md

Git JSONL 정본 위 수집→연구 검토→버스→팀장 조직을 목표로 한다. LLM 판단과 gate 판정, 상주 id와 프로세스를 분리한다. 지식 v1 경로 100%를 완주라 하지만 실제 승격·PG 행수를 요구한 본문과 v1 존재 검사 범위가 다르다. 상주 LLM 조직은 뒤 완료선 v7도 구축하지 않았다.

<a id="config-policy-validator-ladder-json"></a>

## config/policy/validator-ladder.json

clean streak5/fp0, seed blocking6+self-improve blocking3+advisory pattern_decisions1이다. cmd null은 구현 부재와 같지 않고 호출 경로 확인이 필요하다. 등급 상태는 현재 실행·실제 사람 승인 증거가 아니다.

<a id="config-policy-write-boundary-json"></a>

## config/policy/write-boundary.json

deny/ask·inviolable/verifiable·collab_ask를 경로로 분리하고 원장·정책·완료선·명부의 자기 변경을 제한한다. 합법 subprocess writer가 hook 밖이라는 한계를 스스로 적는다. owner human인 agents/README가 verifiable인 차이는 소유와 변경 경로를 나눠 검토해야 하며 자동 적용 가능성은 이 파일만으로 확정하지 않는다. 이 정책을 Zeus 실행 권한으로 승계하지 않는다.

<a id="ontology-contracts-yaml"></a>

## ontology/contracts.yaml

components와 owns의 정확히 한 소유자, C1~C10, agent card 어휘, code contexts, skill corpus와 test quality를 선언한다. verified는 심볼 실존·정적 계약 표지이지 이번 실측 PASS가 아니다. C4는 shard 쓰기 scope 미강제, C5는 완료 신호/검증 분리, C9는 advisory, C10은 사람 결정이다. mutation floor0.8은 n4/lib/cap8의 제한된 표본이며 주석 limb와 ontology verifiable 등급이 갈린다.

<a id="ontology-facets-yaml"></a>

## ontology/facets.yaml

8개 관점 축과 trust/lifecycle 분리, project>stack/version>stack>공통의 우선순위를 선언한다. core의 axis-2 문자열 gate와 이 파일의 named axes는 다른 형식이다. project 산출물 검사를 전역 facets 검증으로 오독하지 않는다.

<a id="ontology-glossary-md"></a>

## ontology/glossary.md

설계 저장소로 향하는 redirect stub 전문을 확인했다. root가 이미 검토한 파일이며 중복 승격하지 않는다. 새 개념의 정의나 현재 이동 완료는 이 파일에 없다.

<a id="ontology-graph-queries-yaml"></a>

## ontology/graph-queries.yaml

coverage/partition/acyclic/code graph/contract parity/pending 카탈로그다. usecase 명사를 CON으로 보는 대신 UC 역참조를 검사하고 상태 엔티티는 _state 명명 관례로 축소한다. pending Service 정상/예외 매핑은 미구현이다. coverage는 정확한 토큰 경계가 아닌 substring 검색이므로 REQ-1과 REQ-10 같은 충돌 후보가 남는다. parity 자동 승급은 별도 정책 경로라 validator ladder와 혼동하지 않는다.

<a id="ontology-metrics-yaml"></a>

## ontology/metrics.yaml

자유 문서 명령을 폐쇄 카탈로그로 옮긴 설계다. 실제 세 cmd는 git ls-files의 종료코드를 검사하지 않아 Git 실패를 빈 목록0으로 보일 수 있다. 주석의 YAML block scalar는 shell quoting 자체를 없애지 않는다. tracked Python LOC와 test 파일 수는 전체 로컬 자산·실행시간·품질이 아니다.

<a id="ontology-schema-json"></a>

## ontology/schema.json

5평면·21kind·29artifact type·31relation·origin/evidence와 confidence5값을 정의한다. root는 $defs 저장소이고 ontology_validator가 node/edge $ref를 붙여야 실제 검사한다. edge additionalProperties 폐쇄가 없고 lifecycle은 string, capability와 artifact_type의 kind 제한은 주석뿐이다. evidence 비어 있지 않은 배열도 원문 해시·실행 출처의 진실성을 인증하지 않는다.

<a id="pipelines-chat-yaml"></a>

## pipelines/chat.yaml

intake/respond/consolidate 3단계는 INTENT/RESPONSE/EPISODE 세 substring만 확인한다. source·persona 준수·재사용 가치·proposed 격리는 산출 지시이며 gate가 증명하지 않는다. evaluator의 episode 저작 권한은 별도다.

<a id="pipelines-core-yaml"></a>

## pipelines/core.yaml

31단계·81 raw gate. 17 planner와 14 개발/검증/운영 단계며 seq 중복은 표시일 뿐 input DAG가 순서다. 요구 고유 ID·모든 persona·각 JSON 예시는 substring 한 개로는 전칭을 증명하지 못한다. Java/JaCoCo/MyBatis 중심과 optional frontend/mobile/monitoring/CD/batch를 사용자 필수 8단계 SDD와 그대로 동일시하지 않는다. e2e는 implementation이 명시 input에 없고 selfimprove verify도 repair input이 빠져 있다.

<a id="pipelines-gate-lexicon-yaml"></a>

## pipelines/gate-lexicon.yaml

exact 2개 우선, pattern10개 순서로 폐쇄 check8종을 유도한다. 성공/PASS 패턴이 전칭 패턴보다 먼저이며 type만 파생해 cmd/url/target이 미결정인 경우 runtime ERROR다. 문형 등록은 실제 실행 가능성이나 의미 정확성 검증이 아니다.

<a id="pipelines-harness-selfimprove-yaml"></a>

## pipelines/harness-selfimprove.yaml

spiral 5단계·21gate로 주석/arming의 과거 4단계13gate보다 늘었다. triage/report candidate_binding은 최신 원장 ID를 비교하지만 문서 해시·내용·실행 generation을 묶지 않는다. verify는 repair 의존이 명시되지 않아 DAG상 병렬 ready 가능성을 남긴다. research git diff는 staged/untracked 및 일부 보호 경로를 보지 않는다. baseline과 known_good는 별도 외부 앵커이며 재표시 잔여가 명시된다. Windows cmd set 구문은 Linux/WSL로 그대로 이식할 수 없다.

<a id="pipelines-overnight-python-yaml"></a>

## pipelines/overnight-python.yaml

8단계 todo CLI 실험은 사용자의 8단계 SDD가 아니다. 모듈4종 존재 gate는 cli.py 한 파일만 보고 import는 namespace package도 가능하다. unittest discover는 0 test 성공 종료 여지가 있고 REQ 한 개 존재는 전체 추적이 아니다. CLI list rc가 명시 검사되지 않으며 고정 smoke/clig 파일은 공유 실행·실패 정리 위험이 있다.

<a id="pipelines-repair-trial-yaml"></a>

## pipelines/repair-trial.yaml

의도적으로 불완전한 SPEC과 hash oracle의 간격을 수리 루프에 부하로 준다. acceptance 파일은 premise이며 immutable 봉인이 선언돼 있지 않고 테스트 수리라는 문구가 대상 코드와 oracle 변경을 혼동시킬 수 있다. REPORT RESULT만으로 수리 횟수·재현을 인증하지 않는다.

<a id="pipelines-reverse-onboarding-yaml"></a>

## pipelines/reverse-onboarding.yaml

기계 구조 추출→사람 의도 복원→coverage 4단계다. 첫 gate 자체가 reverse.py를 실행해 출력 파일을 쓰는 계약이므로 순수 read-only evaluator와 다르다. round-trip은 같은 추출기의 자기 일치이지 원래 의도나 runtime 동작 증명은 아니다. 의도·온보딩 human gate는 소스 모델 이름으로 대체할 수 없다.

<a id="pipelines-role-request-yaml"></a>

## pipelines/role-request.yaml

유휴 상태에서 기존 arm/spawn 경로를 재사용해 상한을 중복하지 않는 설계다. 1단계2마커는 요청 ID 정확성·canary 품질을 확인하지 않는다. 리포트까지만 요구하고 발의를 강요하지 않는 점은 유지하되 목표 완주와 구별한다.

<a id="pipelines-source-note-yaml"></a>

## pipelines/source-note.yaml

2단계5마커는 첫 줄·정확한 ID·모든 주장 출처·양방향 실험·destination 기록을 실제로 강제하지 않는다. reachable false와 미판정 진행은 수집 정책이며 승인 정책이 아니다. 기존 제안 추가와 신규 외부 지식 도입의 판정 권한을 분리한다. 앞선 61개 연구자료와 직접 연결되지만 그 검토 상태를 승격으로 읽지 않는다.

<a id="pipelines-youtube-note-yaml"></a>

## pipelines/youtube-note.yaml

2단계5마커이며 제목/설명만 읽은 부족 자료도 정직한 none으로 통과할 수 있다. 본문의 file_content는 부재를 못 본다는 일반화와 달리 checks.py에는 forbid가 있지만 이 다섯 gate는 안 쓴다. 금지 문구 test 존재는 transcript 미저장 실측이 아니다. 별도 원장은 pipeline identity 결함의 우회다.

<a id="pipelines-fixtures-repair-trial-spec-md"></a>

## pipelines/fixtures/repair-trial/SPEC.md

7개 요구의 수식 계산기이나 implicit multiplication·오류 메시지·지수/단항 우선순위는 충분히 명시하지 않았다. 테스트가 최종 판정한다는 요구는 oracle가 요구 의미를 몰래 확장하지 않는 검토를 대신하지 못한다.

<a id="pipelines-fixtures-repair-trial-acceptance-test-py"></a>

## pipelines/fixtures/repair-trial/acceptance_test.py

unittest와 외부 calc에 의존하는 7개 test 메서드다. 우결합 지수·단항 precedence·implicit multiplication·정확한 오류 문자열 SHA를 요구한다. 작은 결과 공간의 SHA는 비밀 oracle가 아니며 요구에서 유도 불가한 정확한 오류 메시지를 수리 성공으로 요구하는 것은 실제 SDD 인수에 부적합하다. 실행하지 않았다.
