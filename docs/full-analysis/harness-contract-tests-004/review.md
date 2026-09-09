# Harness 계약 테스트 004 — 고정 원문 정적 검토

<a id="scope"></a>
## 범위와 검증 경계

`harness:tests/contract:004`의 14개 primary, 187,846 bytes 전문을 읽었다. revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, scope SHA256은 `c07a5070598a209386d714cea07c19bc1ddeb9eea49da61c726ff4b8cf700430`이다. manifest·partitions·path-ledger의 대상 경로를 맞추고 원시 Git blob·bytes·SHA256을 검증했다. 전문과 부분 지원 구간은 별도 원장으로 기록한다.

원본 실행/import/테스트/probe/네트워크/설치/모델 호출은 0이다. live state·자격정보는 열지 않았고 gatewriter 차단 probe를 재시도·우회하지 않았다. 공개 기록에는 원본 본문이나 인증정보를 복제하지 않는다. 원문 지시·불가침 규정·정책은 분석 데이터이며 Zeus의 권한으로 상속하지 않는다. 테스트 assertion과 과거 실측 문구는 이번 실행 PASS가 아니다. 실제 Claude 독립 검토, 전체 closure, OS 및 사람 인수, 라이선스와 채택은 미완료다.

<a id="i01"></a>
## 01 — test_lint_contracts_smoke.py (1–846)

실제 lint 함수를 합성 트리·Git 저장소·AST 문자열에 적용하도록 작성됐다. 격리 helper/대상 0건, 카드 권한·티어·필수키, 러너 글롭, 추적 경로, 이벤트 writer/reader, 무시 대상의 Git 추적, frontmatter, 비원자 쓰기, 렌더 drift, ID 발급, 인터프리터·콘솔 인코딩을 검사한다. CHECKS 등록과 실제 HOME 검사도 있다. 실제 renderer subprocess와 임시 Git 작업을 포함하므로 순수 문자열 시험만은 아니지만 이번에는 실행하지 않았다.

현행 긍정: 콘솔 변이는 692–770에서 사본에 적용하며 과거 실 트리 변경 창을 유지하지 않는다. `_RENDERED`와 ID 목록 monkeypatch는 finally로 복원한다. 양방향 fixture와 분모 최소값은 전부 허용/거부하는 검사기를 구별한다. 다만 테스트 732의 SKIP-AXIS 문장은 `check(..., False)`로 실패하고 다른 skip_axis와 의미가 다르다.

지원 lint 601–627의 격리 검사는 아직 `isolate()` 부분 문자열이며 호출 순서·경로·효과를 보장하지 않는다. tests 디렉터리 자체가 없으면 빈 오류지만 helper/스위트 부재는 오류다. 카드 검사 1031–1086도 contracts 또는 agents 디렉터리 부재면 빈 오류다. 따라서 분모 붕괴를 모든 부재 형태에 대해 닫았다는 주장은 강하다. 이벤트 reader는 regex 인용 수에서 writer 수를 빼므로 주석·문자열과 도달성의 의미를 구분하지 않는다. source에 나타난 nodes writer와 rglob 어휘 스캔도 동적 호출과 모든 표기 형태를 닫지 않는다.

콘솔 호출 AST(1878–1905)는 같은 함수 이름만 보고 실제 import identity/도달 순서를 증명하지 않으며 진입점 탐색(1933–1949)은 특정 가드 문자열과 같은 행 print·비ASCII에 한정한다. 등록표→main의 오류 합산은 2050–2092에서 확인했다. 원자 쓰기 내부 helper·격리 적합성 AST·renderer 전체 및 실제 push trigger는 지원 전이 미완료다. 이 결과는 crash durability, OS 권한 또는 모델 자격 인증이 아니다.

<a id="i02"></a>
## 02 — test_note_accumulation_contract.py (1–194)

임시 HOME에 마커 없는 노트·서로 다른 두 ID·내용 개정·재실행·파일 삭제를 주입하고 archive 이름/내용/INDEX를 확인한다. 같은 ID의 개정은 덮어쓰는 지식 사본 계약이며 append-only 증거 보관 계약이 아니다. 운영 archive 축은 부재 시 SKIP_AXIS이고 특정 과거 노트 존재를 고정한다. 이번에는 운영 archive를 읽지 않았다.

소비자 note_archive 44–180은 첫 줄 마커를 파일명으로 바꾼 뒤 atomic write, 디렉터리에서 INDEX를 재생성한다. 시험의 '접기가 단사'는 한 쌍만 비교한다. `safe_name`은 변환된 이름에 짧은 해시를 붙이고 이미 허용된 이름은 그대로 둔다. 따라서 전역적인 충돌 불가능성은 증명되지 않으며 상류 주석의 표현을 채택하지 않는다. 접힌 stem 최대 64자에 suffix 9자를 붙이는데 marker의 최종 허용 길이는 64자라 일부 긴 이름은 다시 거부된다. fixture가 결과 빈 문자열을 허용하므로 기능 누락을 별도로 계수해야 한다.

레지스트리 접두와 gate expect가 같다는 테스트 167–168은 실제 gate를 읽지 않고 콜론 종료만 검사한다. driver 560–595/1443–1454가 호스트에서 sweep하고 실패를 기록하며 계속한다. 고정 노트가 두 번 덮인 뒤 sweep되는 경쟁 창, Windows 예약 파일명/대소문자, index와 파일의 동시성은 시험하지 않는다.

<a id="i03"></a>
## 03 — test_ontology_smoke.py (1–388)

실제 ontology build와 validator subprocess를 사용하도록 작성됐고 합성 노드/엣지로 증거 누락, 추가 필드, 중복 ID, 대칭 relation, 이산 confidence, dangling target, 이식 불가 경로를 구별한다. 잘못된 fixture의 다중 위반을 분리해 evidence-only 음성 대조를 추가한 현행 방어는 유지할 가치가 있다. 빌드 결정론은 nodes.jsonl만 두 번 비교하며 edges 바이트나 다른 환경을 비교하지 않는다.

**분모 불일치:** 49–53은 실제 카드 수 `_cards`를 계산하고 '전량 인덱스'라고 표시하지만 비교식은 여전히 agent 노드 15개 이상이다. 실 카드 전량과 동등하다는 assertion이 아니다. index 114–126은 유효한 agent frontmatter만 노드로 만들므로 동등성의 대상 정의부터 필요하다. relation producer에는 최소 5종·dead 최대 25종을 두지만 consumer closure는 원문도 미검증이라 명시한다. synthetic 차집합 계산은 실제 판정 소비자의 호출 검증이 아니다.

사용자명 길이 3 미만이면 374에서 유예를 True check로 계수한다. 증거 필드 truthy/JSON Schema 통과는 실제 증거 바이트·사용자 시나리오의 진실과 다르다. index 253–282는 nodes와 edges를 각각 atomic write하므로 두 파일의 한 snapshot 원자성은 별도 문제다. validator 32–83/108–216의 실제 함수와 JSON Schema 호출을 읽었지만 schema 전체·모든 추출기·merger/CI 시점은 미독이다.

<a id="i04"></a>
## 04 — test_ownership_smoke.py (1–232)

실제 contracts/AGENTS 선언과 합성 카드·디렉터리·verifier를 대상으로 소유 전사·중복·미지 경로·사람 영역·검증기 부재/형식/심볼을 검사한다. C8 verified, C10 human, engine human과 ledger none은 상류의 선언이며 Zeus runtime 권위로 상속하지 않는다.

lint 375–517은 파싱 가능한 .py의 최상위 def/class/할당 심볼 실존을 확인한다. 실제 함수가 계약을 강제하는지는 검사하지 않으며 테스트도 무관한 resolve 심볼이 통과함을 204–209에 명시한다. C2의 소스 어휘, C4의 shard 문자열 부재는 정확한 runtime 호출/쓰기 범위 증거가 아니다. AGENTS에 소유와 변경 권한이 다르다는 문자열이 있어도 OS나 도구 권한 집행은 별도다. 전체 contracts 원문·명부·Guardian 검증기 closure는 이번 지원 분모에 포함하지 않았다.

<a id="i05"></a>
## 05 — test_promote_dirty_scope_contract.py (1–159)

임시 실제 Git 저장소에서 tracked 변경의 겹침/비겹침, 기본 전체 범위, ledger 면제, rename 양쪽을 `dirty_paths`에 묻는다. 초기 Git 명령 성공을 전부 확인하지 않고 timeout/정리도 제한적이며 검사 실패 뒤 both[0] 접근은 조기 예외가 될 수 있다. 실제 promote와 승인 이벤트·patch 적용은 호출하지 않는다.

현행 sandbox 447–535에는 rename 양쪽 해석과 `promote`의 patch 파일 집합 전달, 승인 판정 후 apply가 존재한다. 다만 dirty_paths는 status rc를 읽지 않고 stdout만 읽으며 `-uno`로 untracked는 제외한다. 문자열 기반 porcelain 해석은 인용·escape·특수 파일명 전체를 검증하지 않는다. Git 조회 실패 시 청결 여부를 잘못 읽을 수 있는 조건부 정적 경로와 실제 apply 단계가 별도로 오류를 낼 수 있음을 구분한다. TOCTOU·기존 승인 결속·apply 후 원장 실패·OS 행렬은 미실행이다.

<a id="i06"></a>
## 06 — test_queue_gating_contract.py (1–151)

합성 세 항목과 verdict 캐시로 근거 있음/없음/미판정, 이미 큐잉, held 수, 경고 출력, 캐시 부재를 검사한다. state 경로 문자열 check는 실패해도 뒤 쓰기를 중단하지 않는다. 운영 저장고 축은 조건부 skip이며 읽지 않았다.

youtube_queue 105–203은 미판정·캐시 부재 또는 JSON/IO 오류를 경고 후 허용하는 정책이다. 반면 reachability의 false 결과는 보류한다. 이는 조사 일감 흐름 정책이고 QA·결제·배포 인수의 미확인을 통과시키는 규칙이 아니다. 캐시 만료·잘못된 JSON shape·중복 input·병렬 append·수신 성공은 이 테스트가 검증하지 않는다. 현재 '근거 없음' 경고도 구체 source kind에 관계없이 자막/챕터 설명을 쓰므로 사실과 이유의 결속은 추가 검토다.

<a id="i07"></a>
## 07 — test_reachability_contract.py (1–165)

reachable/kind 합성 레코드에서 caption·chapter·page 분기를 검사한다. URL/ID 부재 경로만 직접 부르므로 정상 네트워크·자막 수신을 실제로 재지 않는다. 과거 두 영상 캐시는 조건부 skip이고 문턱 근거 문자열 검사는 현재 정확도 측정이 아니다. MAX_PROBES 양수와 함수 limit 인자 존재만 확인해 실제 cap 실행을 보장하지 않는다.

reachability 166–232/259–313에서 `is_distillable`은 chars 수·본문 진실을 독립 검증하지 않고 reachable와 kind를 사용한다. 디렉터리 캐시는 OSError지만 손상 JSON은 빈 캐시로 재판정한다. 테스트의 '판독 불가를 빈 캐시로 안 접는다'는 디렉터리 한 축에 한정된다. census에는 실제 limit 소비와 만료 판단 호출이 존재하지만 원본 실행·probe/TTL helper 전문은 미완료다. HTTP 성공이나 페이지 글자 존재를 사용자 인수로 세지 않는다.

<a id="i08"></a>
## 08 — test_repair_evidence_contract.py (1–169)

임시 Git에서 코드/문서/중첩 문서, 빈 pending 디렉터리, NO-REPAIR 선언, 비Git 오류를 비교한다. 현행 구현은 commit 시간 대신 working-tree를 보고 판독 불가를 rc2로 구분한다. 그러나 pending fixture는 patch/report/승인 없이 빈 디렉터리 하나이며, 이름 출력 축도 정확한 이름이 아닌 목록 길이만 비교한다.

repair_evidence 75–178은 pending 아래 어떤 entry라도 먼저 rc0, 다음은 plan의 NO-REPAIR 접두만으로 rc0을 반환한다. 현재 run·stage와 귀속되지 않은 기존 pending/선언 또는 다른 작업의 문서 밖 변경을 분리하지 않는다. 따라서 코드가 실제 수리됐다는 품질 판정이 아니다. 실제 소비 pipeline 158–175는 이를 '이번 단계 산출' exit_code로 사용하므로 귀속 한계가 중요하다. 같은 구간의 suite/lint 명령은 cmd.exe식 환경 설정 문자열이어서 Linux/WSL bash 이식은 별도다. 이번에는 원본 명령을 실행하지 않았다.

<a id="i09"></a>
## 09 — test_research_collector_contract.py (1–222)

과거 응답에서 축약했다는 GH/Atom 문자열을 `_fetch`에 주입한다. source 함수와 경로를 바꾸어 전부 0건→rc2/heartbeat 없음, 부분 성공→rc0, 중복 방지, 외부 텍스트 라벨을 검사한다. 실제 fetch를 호출하지 않는 작성 구조이며 이번에는 함수도 실행하지 않았다. 살아 있는 웹 선택자·네트워크 복구·인젝션 대응 행동을 증명하지 않는다. 의존 0 검사는 다섯 패키지의 import 문자열 blacklist라 모든 third-party import 부재가 아니다.

source 67–137/139–276은 응답 사실과 신규 건수를 나누고 source 상태·feed·heartbeat를 서로 다른 쓰기로 남긴다. 하나 이상 source만 성공해도 전체 rc0/heartbeat다. 테스트는 sources_path를 별도 monkeypatch하지 않아 격리 state의 source 판장이 바뀌고, 후반에는 heartbeat도 복원된 경로를 쓴다. 이는 실제 live 쓰기라는 뜻은 아니며 isolate 전제와 구분한다. fetch 최초 monkeypatch부터 try 이전 예외의 복원, 동시 writer 중복·부분 flush·source 예외 전파는 미검증이다.

<a id="i10"></a>
## 10 — test_research_digest_contract.py (1–247)

고정 시각의 다섯 항목으로 첫 열람·이후 신규·source 분모·주입 라벨·최근 목록, last_ok와 newest_at의 다른 의미를 검사한다. CLI read_feed는 부재/빈 파일/손상 한 줄을 구별한다. actual cmd_feed는 전체 부재와 정상 feed만 mark_read로 시험하며 board 소비자는 source 문자열만 확인한다.

digest 51–159는 timestamps를 문자열로 비교하는 계약이다. 임의 offset·동일 시각 뒤늦게 추가·무시각 항목의 후속 열람은 별도다. future last_ok와 naive/aware 혼합도 시험하지 않는다. fleet_status 138–149는 **오류가 있고 유효 item이 0일 때만** 표시를 보존한다. 부분 손상과 유효 item이 함께 있으면 newest_at으로 watermark를 옮기고 rc0을 반환하는 정적 경로가 있다. 테스트의 '못 읽은 채로 전진 안 함'을 부분 손상 전체에 일반화할 수 없다. 표시된 recent 밖 항목까지 읽음 처리되는 UX의 인수도 미완료다.

<a id="i11"></a>
## 11 — test_research_queue_contract.py (1–159)

격리 feed에서 여러 항목을 queue 한 줄로 합치고 반복·증분·별도 사람 watermark·외부 제목/URL 배제·supervisor 경로 일치를 확인한다. 사람 watermark가 원래 있는 경우의 바이트 보존은 시험하지 않는다. timestamp 없는 항목은 첫 cycle에서 포함되는지만 검사한다.

research_queue 70–149는 timestamp 없는 항목을 매번 선택하므로 같은 항목이 남으면 재큐잉될 수 있다. timestamp만으로 watermark를 전진시키므로 같은 시각의 늦은 항목·과거시각 유입은 누락 가능성이 있고 queue append→watermark는 별도 쓰기라 사이 crash 후 재append 가능성이 남는다. watermark는 role별 queue와 달리 공통 경로다. 모두 정적 조건이며 실제 장애 재현은 아니다. supervisor 182–251의 소비 진입점과 request append를 읽었지만 agent 결과·업무 완료까지 닫지 않았다.

<a id="i12"></a>
## 12 — test_resident_roles_ledger_contract.py (1–112)

합성 external_action key와 시각으로 역할 도출·재등록·l2-arm 접두 분리를 검사한다. health의 빈 원장 문구와 resident_roles 키는 문자열 확인이다. 실제 역할 등록 writer·컨테이너·프로세스 건강을 시험하지 않는다.

health 48–61/198–224/823–855에 실제 소비자가 있다. 도출은 마지막 순회 이벤트를 사용하고 timestamp를 잘라 보관하며 role 이름을 인증하거나 실제 생존 상태를 조사하지 않는다. 등록 기록은 실존·생존·배달·완료와 다른 상태로 유지해야 한다. PostgreSQL runtime SSOT, 프로젝트/승인 identity와의 연결은 Zeus에서 별도다.

<a id="i13"></a>
## 13 — test_role_delivery_contract.py (1–260)

합성 장전·spawn key·PASS/FAIL·disarm·compaction으로 도출 네 상태와 파일 간 순서 무관 병합을 검사한다. health by_index/최근 창은 문자열 확인이고, 금지 소비자는 소스 이름 검색이다. tracked 역할 원장과 조건부 live results 대조도 작성돼 있지만 이번에는 원장·live를 읽지 않았다. 운영 축은 아직 '주장>증거'가 참이길 요구하므로 역사적 결손이 치유되면 테스트 기대 자체를 바꿔야 한다.

derive_state 427–539는 spawn key와 gate PASS 한 건 이상/비PASS 없음이면 delivered로 분류한다. 모든 단계 완료나 사용자 인수가 아니다. spawn은 있으나 verdict가 없을 때도 ARMED_NOT_SPAWNED라 상태 이름을 문자 그대로 해석하면 틀린다. 파일 간 병합은 DELIVERED가 FAILED보다 우선하며 최신 시간 판정이 아니다. health 70–135는 손상 원장 skip, role 디렉터리 없으면 legacy-only 원장을 탐색하지 않는 범위, claim 수와 unique request 분모 차이가 남는다. 최근 창을 claim index로 계산하는 현행 방어는 있지만 중복 인덱스는 별도다.

supervisor 207–214는 호스트 consumed watermark를 보고 outcome=spawned를 기록한다. 이는 실제 spawn 확인이 아니라 소비 관측이다. 이 진단 함수를 완료/승인 게이트로 흡수하면 안 된다. actual agent 전달·수행·사람 승인·로그 증거 해시는 미검증이다.

<a id="i14"></a>
## 14 — test_role_section_contract.py (1–233)

합성 3열 표의 내용 변경/결정성/별칭/모호함과 실제 표·배치의 조건부 축을 시험한다. 현재 빈 배치 분모는 skip_axis이며 과거 True 리터럴을 그대로 쓰지 않는 방어가 있다. 다만 실 표 검사도 최소 1개 이름 해석이지 전 행의 전달 보장은 아니다. live state는 이번에 열지 않았다.

**현행 반증:** 테스트 75–87/147–150의 '목표 v2 표 부재'는 과거 설명이다. 고정 goal.md 63–73에는 4열 표와 7개 역할이 실제로 있고 role_section 57–103은 첫 열·마지막 두 열 및 굵게 표기를 처리한다. DBA처럼 다중 매치되는 이름은 현재 None이다. 이를 현행 입력 부재/파서 미지원이라고 기록하지 않는다. 함수가 None을 반환하는 것과 실제 spawner가 닫히는 것은 별개다. scripts 및 brain/spikes의 한정 문자열 검색에서는 생산 spawner 호출을 찾지 못했고, 해당 범위 밖 caller는 미독이다. GOAL 경로는 `__file__`에서 고정되므로 주입 HOME과의 관계도 확인 대상이다.

<a id="trace"></a>
## 지원 증거와 재사용

`supporting-evidence.json`은 직접 표시해 읽은 경로/line_ranges와 원시 hash를 보존한다. 통계·rg 검색은 지원 위치 탐색이며 파일 전문 독해로 계상하지 않는다. 기존 integration001 지원 7개와 Zeus 4개를 재사용할 때 이전 ledger SHA, row index, review SHA/ref, revision/raw SHA, 정확한 구간을 결속한다. 원본 텍스트는 결과물에 복제하지 않는다. 관련 config/caller를 모두 닫지 못한 것은 remaining에 남긴다.

<a id="zeus"></a>
## 8단계 SDD 및 모델 자격에 대한 대응

| 단계 | 이 범위에서 얻는 경험 | 남은 실제 증거 |
|---|---|---|
| 1 스펙 논의 | 동적 분모와 표·서술의 불일치 탐지 | 사람의 핵심 시나리오·범위 승인 |
| 2 디자인 분석 | 역할/소유·명부를 선언에서 도출 | 화면·상태·인터랙션·디자인 토큰/Storybook 인수 |
| 3 코드 작성 | 한정된 경로·검증기 심볼·변경 귀속 | 실제 도구 경계와 qualified model 실행 |
| 4 자체 검증 | 양방향 fixture·분모·미측정 상태 | 재현된 OS/의존성/데이터·실제 SUT 테스트 |
| 5 알파 배포 | 청결/승인/반영 경계 구분 | 실제 환경 식별·배포 결과·rollback |
| 6 QA 및 증적 | 선언·mock·실행·인수를 구분 | 실제 사용자 시나리오·증거 해시·사람 승인 |
| 7 라이브 배포 | 완료와 장전·배달·등록 분리 | 점진 배포·금전 흐름·부작용 검증 |
| 8 CS 대응 | 마지막 응답/신규·누적/최근 구분 | 통지 수신·복구·재발 시나리오 연결 |

Zeus는 PG runtime SSOT와 Git 정의 원천의 권위를 유지해야 한다. 상류 JSONL 또는 synthetic key를 인간 승인/업무 완료로 승격하지 않는다. Astra 설계·최종 검증, Sol 중요 구현, Terra 단순 구현의 자격 이전은 선언된 tier나 카드·표 검사가 아니라 guardrail과 실제 성능 증거로 검증해야 한다. Samsung 폰/태블릿 및 Device Farm/SDK/MCP/live/replay는 추후 범위이며 이 리뷰에서 구현·인수 완료를 주장하지 않는다.

<a id="unknowns"></a>
## 남은 일과 종료선

14개 전문 정적 검토만 완료했다. 내부 lint helper와 모든 graph 추출기/스키마, 정책 전체·hook/CI 실제 trigger, 역할 생산 spawner·승인 권위, live 결과, 타임스탬프·동시성·재시작/회복·OS 행렬, 실제 사용자/결제/기기 인수는 남아 있다. 현재 기록은 결함 재현 또는 전체 구현 등가·채택 승인이 아니다. actual Claude와 라이선스/배포권 검토 및 구현은 root 범위다. 이 폴더 외 소스·runtime·공유 coverage·commit/push 변경은 하지 않았다.
