# integration 테스트 002 독립 정적 검토

<a id="scope"></a>
## 완료선과 검토 방법

`harness:tests/integration:002`의 17개, 190,937 bytes 원문을 전문 독해했다. 고정 revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, partition scope는 `31cb8f035753cb90eb859a127d72fc32c3a0a8cd725a58ba6ccbb484535b2e8b`다. manifest의 raw Git blob ID·bytes·존재하는 snapshot SHA-256와 읽은 파일을 대조했다. 파일별 실제 해시·줄 수·범위는 `files.json`, 지원 구간과 동일 바이트 선행 독해 재사용은 `supporting-evidence.json`에 고정한다. 원문 기술 주장은 분석 자료이며 Zeus의 실행 지시나 현재 권고로 승계하지 않았다.

원본 import·실행·테스트·프로브·모델·네트워크·설치 모두 0이다. 차단된 gatewriter ERROR 프로브는 재시도하거나 우회하지 않았다. 메타데이터 기록기만 실행한다. 전문 독해 완료는 assertion PASS, 현행 결함 재현, 전체 전이 폐쇄, 라이선스 검토, 실제 Claude 독립 검토, 채택·흡수·구현 완료를 뜻하지 않는다. 읽지 않은 호출부와 실환경은 미완료다.

## 우선 판단

1. **테스트 격리는 state와 HOME 및 외부 시스템을 별도로 다뤄야 한다.** wrappers의 ontology index는 실제 홈에 쓰는 경로이며, fleet의 실제 PG/Kafka 접촉도 임시 state로 격리되지 않는다. fleet-status의 `list`조차 구현상 DDL을 포함한다. 아래 i02·i13은 실행하지 않은 정적 경로 확인이다.
2. **사람 승인과 confirmed 표시는 검증 주체와 근거를 보증하지 않는다.** CLI·cycle·engine·debate 테스트가 직접 operator/judge/architect 이벤트를 만든다. curator는 동일 증거 재병합과 시간 경과로 confirmed를 만들고, evolve는 caller의 `executed=True`로 수렴할 수 있다. 실제 사람 인수·모델 자격의 대용으로 채택할 수 없다.
3. **축 누락과 시험 오라클의 범위를 보존해야 한다.** dispatch/health의 소문자 `skip` 출력은 러너의 `SKIP-AXIS:` 문법이 아니다. `fleet` 전체 미실행은 표준 `SKIP:`라 별도로 인식된다. ‘전체 루프’, ‘원문 보존’, ‘실행’, ‘루프 계속’이라는 라벨보다 실제 predicate가 좁은 사례가 있다.
4. **현재 수정된 방어도 보존한다.** curator pinned 상태 보호, bus 배달 실패 시 watermark 보류, suite 검사 0건의 vacuous 분류, gate 후 최신 FAIL 철회, cycle 재승인, health의 backlog 생성 나이와 마지막 터치 분리·0건 판정 불능이 현행 원문에 있다. 역사적 주석을 현재 고장 재현으로 바꾸지 않는다.

<a id="i01"></a>
## 01. test_cli_smoke.py

1–169 전문. 임시 프로젝트의 `alpha` file_exists → `beta` file_content와 human gate를 만들어 실제 Python CLI arm/step/status/disarm 및 dispatch Stop을 subprocess로 호출하는 연결 시험이다. 61–75의 호출은 임시 state를 주지만 HOME과 실행 runtime은 실제 트리에 의존한다. 파일을 테스트가 작성하고, 130–148 부근 human PASS는 residual CLI로 테스트가 기록한다. 실제 사용자·Claude가 핵심 시나리오를 수행하지 않는다.

arm 바인딩·원장, unknown check 거부, Stop block·heartbeat, gate PASS·pending, 승인 후 done 등은 구체적인 오라클이다. 반면 다른 cwd/비장전 Stop에서 빈 stdout만 보는 assertion 및 disarm 바인딩 소실만 보는 assertion은 해당 subprocess 성공을 모두 증명하지 않는다. residual의 현재 구현은 등록 stage/mode/statement를 검사하지만 PASS 이벤트의 `actor=operator`를 CLI 자체가 넣는다. 사람 서명·evidence hash 검사는 이 읽은 경로에 없다. run/reenforce/ledger/gate_runner 지원은 동일 바이트 이전 구간 재사용이고 전체 handler 전이 폐쇄는 미완료다.

<a id="i02"></a>
## 02. test_cli_wrappers_smoke.py

1–120 전문. restore는 `deadbeef` fixture와 원장 event/복원 대상 필드까지 검사하며 실제 복구를 수행해 검증하는 시험이 아니다. fake HOME에 config를 복사하는 가지와 실제 HOME을 사용하는 가지가 섞인다. 71–76의 PG 부재 설정은 profile 원문 `:5434/`를 `:1/`로 단순 치환하며 치환 건수·최종 DSN을 검증하지 않는다. 따라서 입력 profile 형식이 다르면 실제 설정 endpoint를 사용할 수 있다는 조건부 위험이다. 실제 endpoint 접속·권한·현재 서버 상태는 조사하지 않았다.

78–84 ontology index 호출에는 fake env 인자가 없다. `ontology_cmd:41–51 → ontology_index.build`는 실제 HOME의 var에 인덱스 파일을 쓰고 validator subprocess를 실행한다. `HARNESS_STATE_DIR`만으로 이 쓰기를 격리할 수 없다. `fleet_status_cmd:171–180 → projection_pg.summary:56–67`은 이름이 list여도 `_DDL`을 수행한 후 조회하므로 순수 SELECT라고 보아서는 안 된다. recall의 빈 root는 가짜 홈이며 ghostpatch 거부 역시 실제 패치 성공 경로가 아니다. classify 실제 홈 읽기의 전이 폐쇄와 ontology validator 본문 전체는 미완료다.

<a id="i03"></a>
## 03. test_closedloop_smoke.py

1–154 전문. 합성 FAIL 반복→PASS 해소 ledger를 digest/curator 입력으로 사용한다. 제안의 trust와 착지·SAFE MODE 비차단은 실제 함수·fixture subprocess 계약이지만 수리 품질과 일반화 성공을 검증하지 않는다. 96–118의 reflector `_spawn`은 명령 수집 lambda로 바꿔 프로세스가 실제 생기지 않는다. 원래 함수를 복원하지 않고, 임시 state 환경도 이전 값 복구 대신 삭제한다. 단발 별도 프로세스 러너와 반복 import 실행의 격리 계약은 다르다.

실제 reflector_fork:32–98은 Windows detach flags로 Popen을 요청한 뒤 watermark를 쓰며 자식 완료·digest 성공 receipt를 기다리지 않는다. 이 테스트의 ‘fork 1회’는 요청 수에 대한 오라클이다. 종료 이후 자식 수명, 실패 재시도, 로그 수거는 미검증이다.

<a id="i04"></a>
## 04. test_context_programming_smoke.py

1–182 전문. 실제 CLAUDE.md의 상태 표현 부재·포인터 문자열과 fake 문서의 lint 거부/역사 표현 예외를 검사한다. 1..8 토큰 존재는 사용자의 8단계 SDD가 실행된 증명이 아니다. cohesion은 fixture Jaccard/군집과 실제 Git 히스토리 신호를 함께 사용한다. 현재 테스트는 실 히스토리 비어 있음 및 알려진 과거 churn 고정값 문제를 구분하며, 실제 `collect_history`와 `scan`을 별도 호출하므로 움직이는 HEAD에 대한 동일 snapshot은 고정하지 않는다.

cohesion:63–125는 Git log 실패를 빈 이력으로 돌리고 scan에서 ‘판정 불가’를 반환한다. 생성물 대상은 발의에서 제외하고 결과는 사람 확정을 위한 발의다. l2_driver 안의 cohesion·decomposition·trust·notifications 문자열 존재 검사는 writer의 실제 호출·오류·착지·알림 소비를 실행한 증거가 아니다. 그 writer 전체는 이번 지원 범위 밖이다.

<a id="i05"></a>
## 05. test_curator_smoke.py

1–350 전문. fake HOME에서 reflection digest 유입, unresolved 보류, merge 횟수, 주입 시각을 이용한 stale/archive, frontmatter CRLF/BOM/빈·손상 보호, injection 거부, pinned 보호를 검사한다. pinned merge의 trust/lifecycle/last_active_ts 보존과 evidence 누적을 현재 테스트와 curator:117–134가 함께 보호한다. ‘pinned 자동 승급 결함이 그대로 있다’는 과거 주장을 현재 결함으로 취급하지 않는다. 빈 frontmatter 검사는 asset gate stub을 사용해 해당 분기만 분리한다.

현재 `_crystallize:109–133`은 기존 문서와 gate 검사 후 occurrences를 증가시키고 evidence는 집합 합산한다. 새로운 독립 run 또는 고유 PASS receipt가 추가됐는지를 조건으로 삼지 않고 bake 경과 시 trust를 confirmed로 만든다. 테스트도 같은 digest를 재사용하고 created_ts를 과거로 써서 이 승급을 기대한다. 이는 반복 독립 실측의 증명이 아니다.

`harvest_repairs:256–272`는 원장의 임의 gate_verdict PASS 개수만 확인하며 각 note 제목/수리 diff/실패 계보와 PASS의 동일성을 연결하지 않는다. 테스트의 stage x PASS 하나로 A/B notes를 수확하는 fixture가 이 좁은 계약을 반영한다. 동일 제목 병합, 시간 경과와 관련 없는 PASS를 Zeus의 검증 자격으로 옮겨서는 안 된다. asset gate 전체·reflection digest 실제 생성·실수리 성공은 미완료다.

<a id="i06"></a>
## 06. test_cycle_approval_smoke.py

1–112 전문. stage alpha의 단일 human statement에 테스트가 operator gate_check PASS를 기록한다. 동일 stage 재시작에서 이전 승인 소거, 다른 stage 재시작에서 보존, 새 PASS로 복귀를 확인한다. 프로젝트 산출물 자체는 변경하지 않으므로 artifact 변경 검출 시험이라고 부를 수 없다. 복사한 fake config HOME도 환경으로 연결하지 않아 실제 loader 어휘에 의존한다.

재사용 gate_runner:28–49의 external verdict 조회는 stage/mode와 operator 또는 judge를 거른다. statement까지 일치시키는 조회는 아니므로 같은 stage/mode의 여러 문장을 구별하는 인수 오라클은 이 단일문장 fixture로 검증되지 않는다. 실제 사람의 승인 권한·서명·산출물 버전 binding은 별도다.

<a id="i07"></a>
## 07. test_debate_smoke.py

1–242 전문. gen/SHA 일치, 동세대 모호함, critic HIGH, 정체/진동/조기 cap은 합성 record에 대한 구체적 함수 시험이다. engine open→record→check→decision card→멱등 재생과 tick의 debate/사람/재시도/cap 연결도 합성 actor와 verdict로 구동한다. 실제 critic·architect 모델 또는 독립 검수자가 참여하지 않는다.

debate:76–103은 actor/verdict 어휘와 유출 패턴을 검사해 원장에 쓰며 읽은 함수에 actor 인증·독립 모델 receipt가 없다. 126–175는 규칙 수렴에서 trust confirmed decision을 작성한다. 따라서 ‘수렴’은 이 프로토콜의 판정이며 사실 정답·사람 승인과 다르다. compaction assertion은 일부 event 종류 존재와 check 오류 부재를 확인하며 모든 세대 원문의 byte 동일성·유실 없음 전체 오라클은 아니다. compactor 및 convergence 규칙 전체 지원 재독해는 이번 범위 밖이다.

<a id="i08"></a>
## 08. test_decomposition_smoke.py

1–202 전문(출력 절단됐던 143–172 재독해 포함). 계획의 shard 누락/중복/unknown/rationale, dispatch order·collect, transcript marker와 tail, driver stamp별 실제 harvest 함수 진입을 시험한다. registry/validator/step/status의 일부 연결은 문자열 검사다. 실제 병렬 agent, 파일 쓰기 fence, 모델 자격 또는 팀 산출물 정확성은 검증하지 않는다.

decomposition:161–188에서 dispatch는 stage를 제한하지만 subagent_result는 shard명만으로 귀속하며 stage를 모른다고 명시한다. 같은 shard를 다른 stage/cycle에서 재사용할 때 귀속 정확성은 이 fixture가 증명하지 않는다. subagent_harvest:68–150은 transcript 경로를 읽고 일부 앞/뒤 줄에서 marker를 찾으며 stamp+binding이면 shard None도 기록한다. source는 완료 신호와 검증을 구분한다. scope checker:89–138은 동일/상위 디렉터리 glob 겹침만 확실히 판정하는 보수적 휴리스틱이고 실제 쓰기 권한 강제의 증명이 아니다.

<a id="i09"></a>
## 09. test_dispatch_smoke.py

1–335 전문. 실제 settings/registry 이벤트 집합과 launcher 문자열을 검사한 다음 fake HOME/config/state에 실제 dispatch.py subprocess를 호출한다. Write/Edit/Bash/PowerShell command는 정책 입력 문자열이며 그 명령을 실제 shell에서 실행한 시험이 아니다. unattended stamp, project/outside, scratchpad, extracted/user 문서, heartbeat/seed/banner/notification 경로를 검사하지만 실제 사용자 세션 E2E와 구분한다.

크래시 handler용 sys.modules stub은 복원되지 않아 격리된 단발 프로세스 전제가 있다. Bash가 발견되면 실제 launcher subprocess도 수행하는 원문이지만 우리 리뷰는 실행하지 않았다. PATH의 bash 선택만으로 Git Bash/WSL/배포판·경로 변환 동일성을 보장하지 않는다. Bash 부재 출력 `  skip 런처 서브테스트`는 suite의 `^SKIP-AXIS:`에 잡히지 않는다. 다른 assertion이 성공하는 경우 하위 축 누락이 표준 미검증 축 목록에 자동 반영된다고 주장할 수 없다. 전체 write_boundary 파서·registry handler 전이, Windows/Linux/WSL 실동작은 미완료다.

<a id="i10"></a>
## 10. test_endpoint_graph_smoke.py

1–179 전문. JSON 계약/Markdown 표 fixture에서 atlas·분류·artifact 1-hop·shared value·seam drift·unknown·overlay를 검사한다. amount 같은 필드명이 있어도 결제·금액 정합 실제 흐름은 없다. endpoint_graph:24–89는 현재 프로젝트 overlay, scope, auto promotion을 반영해 atlas를 만들며 부재 seam도 ABSENT로 유지한다. 소비 query:112–168은 이 atlas dict를 탐색한다.

실제 CLI가 fake project를 조회하는 가지가 있다. atlas의 ‘seam 1개 이상’ 라벨을 `"seam 1" in stdout`으로 검사하는 부분은 일반적인 `count >= 1`과 다르다(2..9는 잡지 못하고 10..19에는 맞을 수 있다). 현재 graph_queries의 공허 PASS 방어를 이번 시험 이름만으로 부정하지 않는다. 실제 API·DB·계약 배포 및 graph_queries/seams 전체 연결 폐쇄는 미완료다.

<a id="i11"></a>
## 11. test_engine_smoke.py

1–500 전문. real core/dev 선언을 load하여 stage/gate 수와 대표 어휘 매핑·premise 구조를 보고, 잘못된 check/lexeme/dependency/validator 경로가 loader에 거절되는지 검사한다. machine gate가 충분하고 비어 있지 않다는 현행 assertion이 있으며 과거 literal True만 남아 있다고 보지 않는다. compileJava·DB·HTTP 등 mapping의 type이 일치하는 것은 해당 도구를 실행한 증거가 아니다.

임시 A/OK 파일과 mini pipeline의 gate/tick 연동은 실제 함수 시험이다. PASS 이후 파일 삭제 시 beta 차단 및 복원 후 재PASS라는 회귀 대조가 있다. human/render PASS와 judge 인용 파일은 테스트가 직접 공급하므로 렌더·사람 인수가 아니다. ERROR graphquery fixture와 operator blocker assertion은 정적으로만 읽었다. 이 본문의 ERROR 가지도 실행·우회 프로브로 사용하지 않았다.

iteration은 stage_started, delegation은 dispatch, l2-spawn은 창 reset이라는 합성 ledger 시험이다. 모델 토큰/비용/품질 자격 측정은 아니다. tie-break 반복은 해당 fixture의 선택 안정성 범위이며 다수 동순위 후보의 일반 오라클이 아니다. 전체 loader/check/selector/debate 동작 및 설치 환경의 31/34개 단계 의미는 미완료다.

<a id="i12"></a>
## 12. test_evolve_smoke.py

1–167 전문. fake HOME 계보에서 모호도/유사도·동결·novelty·정체·generation cap·CLI status를 검사한다. `executed=False`의 안정 상태와 `executed=True` 수렴을 구별하지만 실제 산출물 executor를 호출하지 않는다. CLI `--executed`도 실행 receipt를 만들지 않는다.

evolve:185–263의 현재 함수는 lease를 획득/반납하며 candidate similarity와 caller boolean으로 CONVERGED를 고른다. grade는 기록되지만 이 수렴 분기에 합격 문턱으로 쓰이지 않는다. 경쟁 세션·lease 만료·crash·stale snapshot에 대한 fixture는 없다. SDD의 spec 안정과 실행 검증을 분리하는 아이디어는 검토 후보지만 여기의 boolean을 Zeus QA 또는 Astra→Sol→Terra 자격으로 사용할 수 없다.

<a id="i13"></a>
## 13. test_fleet_smoke.py

1–212 전문. 이 파일은 실행한다면 실제 localhost TCP 9092/5434, Kafka producer/consumer/admin 및 configured PG를 이용한다. port 연결 확인은 서비스 identity·인증·profile endpoint 일치를 증명하지 않는다. infra 부재 시 `SKIP:`와 exit 0으로 순수 profile 검사까지 전체 생략한다. 표준 skip은 러너가 판정하지만 인프라가 검증됐다는 PASS가 아니다.

첫 fleet profile의 랜덤 topic은 변수로 보존하지 않고 publish를 요청하며 cleanup은 뒤의 roundtrip topic만 대상으로 한다. 두 번째 force topic은 동일 ledger의 watermark로 new lines가 없으면 producer 생성 전에 published 0이므로 ‘둘 다 반드시 생성됨’으로 과장하지 않는다. 첫 publish 성공 시 생긴 topic을 이 테스트가 직접 삭제하는 경로는 보이지 않는다. roundtrip은 2건·field를 비교하고 PG sync/idempotent summary도 본다. PG schema DDL 및 run/stage writes는 외부 공유 DB 효과다. SQL cleanup이 finally 밖이므로 중간 예외 시 cleanup 도달은 보장되지 않는다. 현재 topic 삭제는 future 결과를 기다리는 방어가 있어 역사적 무대기 삭제 결함으로 표현하지 않는다.

bus_tailer:29–136은 JSONL 읽기→Kafka 미러와 state watermark이며 partial line 및 flush 잔량/영구 실패 callback에 watermark를 보류한다. 이 현행 방어를 보존한다. projection_pg:15–67은 JSONL 파생 PG임을 명시하고 실행 DDL/upsert/delete/insert를 갖는다. Zeus의 PG runtime SSOT 방향과 동일한 구조가 아니다. 실제 외부 데이터 삭제·생성·접속은 이번 리뷰 0회다.

<a id="i14"></a>
## 14. test_gate_active_smoke.py

1–135 전문. checks.run spy가 원본에 위임하며 gate_active marker의 실행 중 존재, PASS/FAIL 후 제거를 확인한다. marker 자체는 진행 상태 표지이고 상호배제 lock 증명이 아니다. ERROR/예외/crash/동시 gate에 대한 해제·경쟁은 검사하지 않는다. status용 marker·heartbeat·delegation은 테스트가 직접 생성해 stdout 라벨을 확인하므로 실제 프로세스 생존·정확한 age 측정은 별도다. 상태 환경은 finally에서 이전 값 복원 대신 삭제한다. 실제 gate_runner의 marker try/finally 지원은 동일 바이트 선행 구간 재사용이다.

<a id="i15"></a>
## 15. test_gate_ratchet_smoke.py

1–153 전문. fake gate_check 기록과 pipeline에서 문장/단계 제거, 추가, 사유 waiver, 실제 tick 호출을 검사한다. fake config 사본은 HOME으로 연결되지 않는다. waiver 가지의 `outcome != halt OR reason != operator_blocker`는 ‘해당 blocker가 아님’을 뜻하며 어떤 이유로도 halt하지 않는 ‘루프 계속’을 보장하지 않는다.

gate_ratchet:24–53의 비교는 판정받은 statement 문자열 집합이며 같은 문장을 두고 검사 방식·expect·evidence 범위를 약화하는 경우는 이 비교의 대상이 아니다. waiver는 statement key가 있으면 제외하며 여기서 인증된 사람 승인 증거를 검사하지 않는다. tick:84–95는 scan 예외를 빈 약화 집합으로 처리하는 fail-open이다. 테스트는 이 예외 분기를 다루지 않는다. source loader의 waiver 내용 검증 전체와 실제 정책 변경 승인 경계는 미완료다.

<a id="i16"></a>
## 16. test_governance_mining_smoke.py

1–145 전문. 완료선 4절 shape·excluded 비어 있음·evidence 존재, 실제 선언 1건 이상, host interpretation 제외, 분해 scope 겹침, 폭 seed와 경고, 증거 overlap 의심을 검사한다. 53–60의 실제 선언 루프는 `>=1` 분모 보호가 있다. completion_line:63–87의 complete는 경로 또는 glob hit 존재까지만 뜻하며 내용의 옳음은 별도라고 스스로 명시한다. 따라서 Java 질의 실전검증이라는 claim이 evidence 파일 존재로 확인돼도 실제 Java 실행은 아니다.

gate 해석 동봉, curator restatement 배선, residual REJECT 및 tick retry reset은 소스 substring assertion이다. 실제 호출되거나 폐기 이후 계보만 세는지 실행한 증거가 아니다. scope 휴리스틱과 폭 조언도 파일 쓰기 강제·적정 병렬폭 실측과 구분한다. 선언 파일 전체 의미·preconditions 전체·overlap 전체·reject 소비 전체는 미완료다.

<a id="i17"></a>
## 17. test_health_smoke.py

1–312 전문. real tree shape와 fake settings/CRLF/registry/비ASCII 변조 대조, 실제 Bash dry-run/probe, health 집합과 age·미측정 분모, actual corpus, 임시 Git backlog canary를 섞는다. Git init/add/commit subprocess 반환값을 fixture helper가 반환하지만 caller가 매번 성공을 assert하지 않아 최종 predicate 실패 원인 분리가 좁다. 우리 리뷰에서 이 Git fixture도 실행하지 않았다.

현재 backlog canary는 2020년 생성, 새 파일, 후속 touch를 통해 생성 나이와 idle을 분리하고 파일 0건은 probed False로 확인한다. KNOWN_DEGRADED는 현재 빈 dict이며 과거 guardian 예외를 현행 allowlist로 보지 않는다. guard/suite 미측정·stale latency를 실제 건강 PASS와 분리하는 predicate도 있다.

Bash 부재 시 62행 소문자 skip은 축 포맷이 아니며 109–130의 probe 가지는 별도 skip 표식 없이 생략된다. `_hook_bash`는 runtime pin 우선+실제 launcher 경로 가시성을 검사하지만 latency `probe_event:43–54`는 PATH의 bash를 다시 선택한다. 따라서 wiring에 대한 현재 WSL alias 수리가 latency에도 동일 적용됐다고 말할 수 없다. health:411–414의 full 표시는 evaluate의 오류 목록으로 만들며 dry_run_event:135–137은 Bash 미가용도 None으로 반환한다. 테스트는 실트리·PATH·runtime pin·guardian/ontology corpus에 의존한다. latency >50ms는 고정 하한 오라클이며 빠른 정상 spawn을 일반적으로 판별하지 못한다. 실제 세션 지연·Linux/Windows/WSL matrix·guardian 검수는 미완료다.

<a id="trace"></a>
## 직접 소비·격리·분모 추적

신규 읽은 지원 파일은 `supporting-evidence.json`의 정확한 inclusive line range만 해당한다. 함수명 검색 hit는 본문 독해 coverage로 세지 않는다. 이 보고서의 파일별 구현 인용은 그 범위에 한정한다. 일부 파일 검색에서 존재하지 않는 경로와 PowerShell brace 문법 오류가 있었으나 읽기만 재탐색했고 source 실행은 하지 않았다.

공통 `_isolate`, suite runner, outcome 분류, paths/config, gate_runner, run CLI, seeding/reenforce, ontology index, ledger/derive_state는 이전에 본인이 읽은 integration001 지원 구간을 **동일 파일 SHA-256 재확인 후** 재사용한다. 각 항목의 `previous_review_reuse`/`prior_ref`, 이전 supporting ledger, 실제 range를 남긴다. 그 밖의 이전 리뷰 결론을 새 독립 증거로 세지 않는다.

`suite_cmd`는 `tests/**/test_*.py`를 별도 subprocess로 발견·실행하고 출력 assertion과 표준 skip을 분류한다. `_env`는 HARNESS_HOME/state를 정리하지만 각각의 원본 테스트가 HOME 쓰기와 모든 외부 endpoint를 차단하는 것은 아니다. `_isolate`도 source var와 PG/Kafka까지 자동 임시화하는 장치가 아니다. 미지원 HOME/guardian/runtime key/외부 서비스 설정은 fixture 계약에 명시해야 한다. 이 17개 스크립트의 check 호출 수는 조건문·반복·환경에 따라 달라지므로 정적인 호출점 수를 실제 실행 분모로 보고하지 않는다. 이번 실행 분모는 0이다.

`test_outcome`의 현행 판정은 assertion 0 + 표준 SKIP 부재를 vacuous로 구분한다. 다른 assertion이 있는 부분 생략은 suite의 `SKIP-AXIS:` 수집을 통해야 별도 축이 된다. 원문의 소문자 skip은 그 문법과 일치하지 않는다. 이 보고서는 모든 OS에서 실제로 누락됐다는 측정 결과를 주장하지 않는다.

<a id="zeus"></a>
## Zeus 대응과 사용자 SDD 요구

Zeus 대조는 동일 바이트 선행 독해의 AGENTS, domain/application SDD, model_routing 구간을 재사용한 제한적 비교다. runtime PG 권위, 제안 acceptance false, 단계 advance 차단, 자격 없는 모델의 Astra 유지가 기준이며 전체 현행 구현 등가는 미검증이다.

| 사용자 단계 | 이 범위에서 얻을 수 있는 검토 자산 | Zeus에서 따로 증명할 것 |
|---|---|---|
| 1 스펙 논의 | 완료선·해석·모호도·반론/폐기 기록 | 실제 사용자 핵심 시나리오, 버전과 승인 주체 |
| 2 디자인 분석 | endpoint 계약·scope·render pending | 인터랙션과 시각 결과, 실제 디자인/스토리북 증거 |
| 3 코드 작성 | 분해 계획·정해진 쓰기 범위·delegate 수거 | 실행 권한 fence와 작업별 산출물 귀속, 자격 있는 모델 |
| 4 자체 검증 | 음성 대조 fixture·FAIL 철회·검사 분모 | 실환경 같은 결과, 도구/빌드/테스트 receipt |
| 5 알파 배포 | profile·wiring·runtime pin 검토 | 실제 설치·배포·rollback 및 환경 identity |
| 6 QA·증적 | cycle 승인 reset·pending/partial 구분 | 사람 승인 서명·정확한 statement/버전/evidence binding, no mocked acceptance |
| 7 라이브 배포 | cap·blocker·완료선/여집합 관념 | 점진배포와 관측·복구, 금전 흐름 실검증 |
| 8 CS·반복 | health backlog/age·reflector·curator provenance | 로그→사건→시나리오→재현→수리 검증의 독립 증거와 알림 소비 |

fixture 기반 커널 테스트는 자산 후보지만 사람 인수의 대체물이 아니다. `operator`, `judge`, `architect`, `executed`, `confirmed` 자기 기입은 Astra→Sol→Terra 능력 이전 자격이 아니다. 고유 task/run·spec/artifact hash·실행 환경·독립 검증 주체·실측 결과를 연결하는 별도 계약이 필요하다. JSONL 정본→PG projection 구조를 그대로 Zeus runtime SSOT에 흡수하지 않는다. local ticket+GitHub Issues의 실제 동기화·통지 delivery·자가개선 채택은 이 범위에서 검증되지 않았다. Samsung 실기기/Device Farm SDK/MCP/live/replay는 유예 상태이며 구현했다고 주장하지 않는다.

<a id="unknowns"></a>
## 남은 일

- 모든 원본 실행·현재 결함 재현·외부 서비스/OS matrix·실사람/실기기 인수는 미실행이다.
- dispatch write_boundary 및 전체 handler registry, loader/lex/catalog/seams, reflector·asset gate·curator 상류, debate rules/compactor, lease 경쟁, guardian approval key, 모든 설정·fixture·caller의 전이 폐쇄는 미완료다.
- 현행 미검증 구현이 사용자 8단계 SDD·PG 권위·모델 자격과 등가라는 결론, 기술 주장의 최신성 검증, 라이선스/재배포 검토, 실제 Claude 독립 검토와 채택 승인은 없다.
- 수정 제안·우선순위 논의 이후 실제 구현은 root 담당이다. 이번 작업은 이 폴더의 문서·기록기·검증 기록으로 끝낸다.
