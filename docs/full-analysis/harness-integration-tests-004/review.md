# harness integration 004 정적 검토

<a id="scope"></a>

`harness:tests/integration:004`의 17개 테스트, 173,845 bytes를 전문 독해했다. 정본 revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, partition SHA-256은 `a2f4e64585fba3f48a8eb84ea7014eda4d89b6dc7cb52b2f7a229c7cd330b577`이다. 각 파일의 raw Git blob·bytes·SHA-256·줄 수와 실제로 읽은 지원 구간은 별도 JSON 원장에 결속한다. 원문 지시·스킬·역사적 측정치는 실행 지시가 아닌 분석 데이터다.

지원 파일 `.mcp.json`은 manifest에 snapshot SHA-256이 없다. raw Git blob과 bytes를 정본과 비교하고 현재 SHA-256을 별도로 계산해 기록했으며, 존재하지 않는 manifest SHA와 일치했다고 주장하지 않는다. 나머지 이번 원장 항목의 확인 결과는 checkpoint에 남긴다.

원본 실행/import/프로브/네트워크/모델/설치는 0이다. 거절된 gatewriter ERROR 프로브를 재시도하거나 우회하지 않았다. 이번 기록은 테스트 PASS, 동적 결함 재현, 실제 Claude 독립 검토, 사람 인수, OS 승인 또는 채택 완료가 아니다. 소유한 이 폴더 외 source/runtime/Zeus 구현/공유 coverage/commit/push는 변경하지 않았다.

중요한 발견은 다음 세 가지다. 첫째, 재주입 브리프의 승인 표시는 자동 장전의 HMAC 요구와 다르다. 둘째, 검색 카나리아는 질의별 한 건 이상 hit 비율을 계산하고 실제 검색 소비자를 호출하지 않는다. 셋째, 역할 카드 전문 계약의 검사와 실제 step 배포의 800자 절단이 분리돼 있다. 아래 각 절은 현재 존재하는 방어와 이 시험이 검증하지 않는 부분을 함께 기록한다.

<a id="i01"></a>

## 01. test_mutation_baseline_smoke.py — 245줄

6줄짜리 임시 Python 프로젝트에 Git init/config/add/commit을 하고 실제 worktree mutation 러너를 호출하는 시험이다. 붉은 baseline·글롭 0건·초록 baseline을 같은 target으로 비교한다. 이번에는 이 Git 작업과 Python 실행을 하지 않았다. fixture의 Git 명령 결과를 검사하지 않으며 실제 환경의 Git 설정·hooks·프로세스 정리까지 격리했음을 보증하지 않는다.

현재 mutation 121–126은 baseline 실패 또는 `<no-suites>`를 score=None 및 error로 반환한다. quality_cmd 122–174는 이를 exit 2로, 낮은 점수를 exit 1로 구별한다. 과거 ‘붉은 원본이 mutation 만점’ 문제는 이 현행 방어와 구분한다. CLI 계약 검사는 mutation 결과를 fake dict로 주입하므로 실제 score와 계약 하한의 수렴까지 시험하지 않는다. 계약의 0.8은 ontology/contracts.yaml 539–548에 명시된 제한된 lib 표본의 역사적 근거이며 현행 전체 저장소 실측은 아니다.

mutation 60–153은 문자열 후보·파일 앞부분 cap·초 단위 worktree 이름·전체 줄 첫 replace를 사용한다. 문자열을 지운 코드에서 후보를 확인한 뒤 원본 줄에서 첫 occurrence를 바꾸므로 문자열과 코드에 같은 연산자가 있으면 대상 위치가 다를 수 있다. 등가 변이를 자동 판별하지 않으며 생존자 재확인도 없다. run_suites 172–252는 글롭 0을 막지만 개별 suite는 rc 중심이다. 현재 suite_cmd의 구조적 silent_fail/vacuous 판정과 같지 않다. worktree 제거 결과와 Git hooks 완전 격리도 이 시험에서 닫히지 않는다. 이는 검출력 평가 후보 자산이며 실제 사용자 인수 점수로 쓰지 않는다.

<a id="i02"></a>

## 02. test_ownership_vitals_smoke.py — 194줄

합성 이벤트로 소유자/그림자 행위자/장애 지표와 schema 거절을 검사하고, fake HOME에서 incident CLI를 실제 호출해 원장 1건 기록 및 미등록 컴포넌트 무기록을 확인한다. 이 경우 synthetic=false도 fixture 작성자가 지정한 값이다. 실제 장애·담당자 응답·복구 증거가 아니다.

vitals 48–52는 total을 먼저 증가시킨 뒤 synthetic을 제외한다. 테스트도 synthetic 포함 total=5를 기대한다. 따라서 ‘synthetic 전 지표 제외’ 라벨은 전체 분모까지 제외한다는 뜻으로 확대할 수 없다. owner_share는 귀속된 비합성 이벤트 기반이고 0/0을 None으로 하는 현행 방어가 있다. role/actor/agent는 payload 문자열이며 사람이나 실행자 신원의 인증은 아니다.

incident_cmd 33–138은 component vocabulary와 payload를 검증하고 기록한다. ownership_events 24–74의 bool/depth/severity 검사는 직접 확인했다. owner_wakeup/finding/timeout은 harness_lint 104–112의 사유 있는 DEFERRED다. 주석 위치를 확인하도록 고친 현행 시험은 인정하지만 해당 3종의 실제 tail dispatcher가 구현됐다고 주장하지 않는다. check_ownership 437–495의 경로 중첩 금지는 실제 코드이며 상위/하위 carve-out 전이는 유예다. health의 문자열 존재 검사와 실제 sec_ownership 648–689의 소비를 구별한다.

<a id="i03"></a>

## 03. test_params_smoke.py — 165줄

임시 params.json을 registry→LKG→seed로 손상시키고 복구·marker·tune 거절을 확인한다. HOME/STATE 이전 값을 finally로 복원한다. fallback status와 방향 검사는 실제 임시 파일 구현을 사용한다. gate causation 축은 chat intake의 실 file/content gate와 합성 입력을 사용하며 evidence_refs에 점이 들어 있다는 조건은 참조 대상의 내용·실행·사람 승인 영수증 검증이 아니다.

params 54–158은 registry 항목의 numeric/tighten 형식과 방향을 검사하지만 전체 필수 키, bool/NaN 등 값 경계, 동시 갱신·백업과 본본의 원자성은 이 시험에서 확인하지 않는다. fallback marker는 최초 layer를 보존하므로 LKG에서 seed로 바뀐 현재 layer가 marker에 갱신된다고 보장하지 않는다. 정상 load도 marker unlink를 시도한다. 이를 순수 read-only getter로 가정하면 안 된다.

config/params.json 16–17은 pollution.bucket_min 증가를 ‘강화’로 정의한다. 실제 detect 83–85는 bucket_min 미만을 제외하므로 증가할수록 탐지 대상이 줄 수 있다. 방향의 명칭과 실제 보호 목적이 동일한지는 별도 정책 검토가 필요하다. 또한 pollution.retract 118–121은 실제 params 조회값이 아니라 모듈 seed를 detector receipt에 기록한다. params 변경을 소비하는 것과 그 실행값을 감사 기록에 남기는 것은 별개다.

sandbox의 hooksPath/PYTHONNOUSERSITE는 시험에서 소스 문자열로 확인한다. 직접 읽은 _git 74–81에는 hooksPath 설정이 있으나 mutation의 직접 Git 명령까지 모두 이 wrapper를 사용하지 않는다. run_suites는 사용자 site를 PYTHONPATH로 다시 허용하며 완전한 venv 격리는 원문도 미이행이라고 적는다. Windows/Linux/WSL 실동작을 검증한 것은 아니다.

<a id="i04"></a>

## 04. test_polish_smoke.py — 194줄

임시 `.claude/settings.json`에 delegate 설치/백업/제거·stale marker를 시험한다. 실제 사용자 프로젝트에 설치한 것이 아니다. delegate_cmd 36–147은 Git Bash 경로와 특정 command 문자열 치환을 사용한다. status는 marker의 launcher 존재와 hooks의 truthiness를 보고 실제 hook commands 전체의 정확한 연결을 검증하지 않는다. remove는 hooks JSON에 harness root 문자열이 있으면 hooks 전체를 제거할 수 있어 설치 후 외부 hook을 섞은 경우 보존 계약은 이 fixture로 닫히지 않는다. 두 설정 파일의 crash 원자성도 미검증이다.

heartbeat 시험은 write_json_atomic에 PermissionError를 주입해 1회 재시도와 지속 오류의 관용 처리를 확인한다. 실제 Windows 파일 경합이나 Linux 잠금 재현은 없다. 구현 35–45는 OSError 전반에 같은 재시도·stderr·None 처리를 한다. 성공적인 heartbeat 기록과 오류 상황을 단순 None만으로 구별할 수 없으며 실제 알림 전달도 시험하지 않는다.

사람 대기열은 합성 spiral_approved 이벤트와 sandbox report 파일로 만든다. health 692–736의 조회는 latest_verdict 기준으로 승인된 후보를 대기열에서 제외하고 parking_fitness를 호출한다. 서명/사람 신원/승인 artifact를 확인하는 인수 검사는 아니다. strict completion은 `proof.txt`에 x를 쓰면 통과하는 존재 검사다. completion_line 63–87의 total>0 방어는 있지만 의미·배포 실행 영수증은 별도다. ‘PASS=커밋’ 브리프 문자열 확인도 commit 실행 증거가 아니다.

<a id="i05"></a>

## 05. test_pollution_smoke.py — 156줄

임시 JSONL에 burst/분산 이벤트와 seeded_live marker를 직접 써 detect·retraction·derive·CLI dry-run/execute를 검사한다. 같은 250ms bucket의 5건, caller가 선택한 session 이름, marker 파일의 존재가 판정 근거다. 실제 정상 운영과 합성 오염을 인증된 provenance로 구분한 결과가 아니다. 임계는 fixed bucket이라 경계에 걸친 burst와 여러 세션이 합쳐진 bucket까지 이 fixture가 검증하지 않는다.

원본 이벤트의 물리 잔존과 retraction을 다시 철회해도 부활하지 않는 현재 derive 방어는 인정한다. AUDIT_EVENTS membership은 compaction 실행 후 전체 원문 보존의 시험과 다르다. retract는 reason과 batch 상한을 요구하지만 실제 ID의 존재·독립 승인·검출된 계획 digest에 대한 재검증은 이 읽은 함수의 계약에 없다. CLI의 --execute는 사람 인증이 아니다. detector receipt의 seed/실측 파라미터 차이는 i03과 연결한다.

detect는 docstring상 read-only이나 params.get을 호출하고 그 load는 marker를 쓰거나 지울 수 있다. 따라서 원장 무변경과 모든 상태 무변경을 나눠야 한다. 원문을 실행하지 않아 실제 상태 변경은 0이다. Zeus에서는 PG 원장과 파생 뷰의 tombstone 이력으로 옮길 후보이며 자동으로 FAIL을 가리는 정책의 채택 승인은 아니다.

<a id="i06"></a>

## 06. test_preconditions_smoke.py — 152줄

파일 내용과 JSON 값의 지문 변화, 도입 전 None/빈 지문을 stale로 보지 않는 정책, gate→staleness→tick의 재검증 지시를 임시 프로젝트로 시험한다. ‘합성 경로’와 ‘실 인코딩 경로’는 파일에 쓴 문구이며 실제 인코더 실행이 아니다. 마지막 gate는 산출물 존재만 확인하므로 어떤 외부 변화든 진짜 시나리오를 다시 측정했다는 뜻은 아니다.

preconditions 33–100은 UTF-8 대체 디코딩 text의 축약 SHA 및 JSON dotted value를 사용한다. raw binary 환경 동일성을 증명하는 방식과 다르다. 잘못된 JSON/부재는 ABSENT로 합쳐지고 unknown 문법은 고정 문자열이다. pipeline_loader 366–374는 문자열 목록 형식만 검사한다. unknown 문법이 값으로 표면화된다고 실행 자체가 거절되는 것은 아니다. 지문 없는 과거 verdict를 유효하게 두는 명시적 호환 정책은 엄격한 초기 인수와 구별해야 한다.

staleness 18–46은 완료 단계와 최신 지문을 대조하지만 tick 103–107은 계산 예외를 빈 stale로 바꾼다. 이 오류 경로와 경로 탈출·부재·권한·raw-byte 변화는 본 시험에 없다. thome에 config를 복사해도 이 fixture는 HOME을 실제로 전환하지 않아 복사본만으로 모든 설정 소비가 격리되는 것은 아니다. 프로젝트와 원장은 명시적 tmp 경로이고 공통 isolate의 범위는 별도 기록한다.

<a id="i07"></a>

## 07. test_probe_smoke.py — 158줄

counterfactual은 임시 spec의 REQ 앵커를 지운 뒤 machine gate가 반응하고 파일을 되돌리는지 검사한다. human gate는 probe의 분모 밖이다. 원문 실행 없이 source만 읽었으며 blocked gatewriter 프로브를 재시도하지 않았다. baseline FAIL→INCONCLUSIVE와 LIVE/DEAD/복원 후 vacuous 구분은 현재 존재하는 방어다.

counterfactual 44–109는 첫 실물 output 하나와 고정 이름 `.cfprobe.bak`를 쓰고, 주입 후 PASS가 아닌 모든 verdict를 live에 넣는다. 의미 있는 FAIL과 도구 ERROR를 구별해 증명하는 오라클은 아니다. finally 복원은 정상적인 예외 흐름의 방어이며 동시 호출·기존 backup 충돌·프로세스 강제 종료·메타데이터/전체 바이트 복원까지 보장하지 않는다. 테스트는 REQ 문자열 및 restored PASS를 검사하며 hash equality를 보지 않는다.

PARTIAL 기록은 proxy/why-human 문자열을 남겨 PENDING_HUMAN을 유지한다. 이후 residual CLI pass를 시험이 직접 호출해 PASS로 만든다. residual 88–109는 등록 문장을 확인하지만 actor='operator'를 자체 기록한다. 이는 사람 인수 대체가 아니다. BLINDSPOTS 검사는 특정 header 아래 bullet 수가 0보다 큰지의 선언 검사이며 실제 제품의 빠진 시나리오 전수를 찾은 것이 아니다.

<a id="i08"></a>

## 08. test_prompt_rollup_smoke.py — 198줄

실제 임시 SQLite에 만료 9건/보존 2건을 넣고 digest 파일 자리에 디렉터리를 놓아 내용 쓰기 실패를 유도한다. 기존 mkdir 실패만으로 순서를 검사하던 약점과 달리 현재 fixture는 첫 write 실패 후 11건 보존을 확인한다. 두 짧은 ‘응’ 샘플과 digest-name 디렉터리 제외도 현행 방어다. 이를 과거 공허한 시험으로 평가하지 않는다.

성공 경로는 expired/deleted=9, retained=2, 대표 문장 상한·군집·주기·analysis와 digest 접두사 분리를 검사한다. 다만 ‘대상 0건이어도 영수증’ 라벨의 159–160은 앞서 9건을 처리해 만든 파일 존재만 확인한다. 0건인 별도 rollup 실행은 없다. ‘원문이 요약에 없다’는 대표 문장의 일부가 남는다는 의미와 구별해야 하며 단발 원문/ID 제외라는 제한된 오라클이다.

구현 rollup 123–196은 select 이후 digest 첫 write, `DELETE WHERE ts < cutoff`, VACUUM, journal expire, digest 두 번째 write를 수행한다. 동일 cutoff는 쓰지만 조회한 ID 집합으로 삭제하는 것은 아니다. 중간에 backdated 행이 들어오는 경우의 집합 동일성은 별도 검증이 필요하다. 첫 digest 쓰기 뒤 예외나 두 번째 덮어쓰기 중 crash, 유효하지 않은 digest 파일이 주차 marker로 남는 경우, 동시 rollup은 시험하지 않는다. handle은 공통 isolate의 기본 DB/state를 호출할 수 있고 모든 예외를 로그 후 None으로 처리한다. 원문 자동 폐기 정책을 ‘하네스 전체 로그 보존’ 요구에 그대로 채택하지 않는다.

<a id="i09"></a>

## 09. test_promptlog_smoke.py — 277줄

SQLite 실제 적재·길이 절단 표시·군집 결정론·prune 기본 예행과 --yes 삭제를 검사한다. 첫 handle은 명시한 p.db가 아니라 공통 isolate가 정한 기본 state DB를 사용한다. 이번 실행은 0이며 실 사용자 프롬프트를 적재하지 않았다. payload 예외 주입과 record의 손상 DB 예외는 서로 다른 경로다. 손상 DB를 handle에 직접 연결해 모두 검증한 것으로 세지 않는다. 원장 writer 문자열 부재는 AST/실제 효과 전수 증명이 아니다.

현행 성능 축은 12×5회의 최소값과 이웃 SQLite batch 차이의 중앙값이다. 이전 평균 통계만 사용한다는 평가는 틀리다. 다만 고정 순서와 짧은 부하 창의 host 측정이며 실제 prompt path의 p95/p99·동시 부하·모든 OS 체감 지연이 아니다. `ms == min(runs)`는 바로 대입한 값의 동일성이고, 대조군 길이가 같다는 것은 ‘같은 창’의 동시 측정을 증명하지 않는다. 고정 30ms sleep 대조는 통계 반응을 보지만 실제 record에 간헐/증가 지연을 주입하는 현재 테스트는 아니다. 주석의 과거 실측을 재실행하지 않았다.

promptlog 125–133은 기록 예외를 조용히 삼킨다. 입력 비차단과 로그 손실 notification 요구는 별도 계약이다. cluster_rows 45–101은 숫자 접기, greedy 순서와 짧은 대표 문장/ID를 남긴다. 원문과 의미가 완전히 동일한 재현 시나리오를 도출하는 시스템은 아니다. prune는 --yes를 받으면 별도 digest 의무 없이 삭제한다. 사용자 경험의 핵심 장면과 자동화 자격은 사람 검토를 거쳐야 한다.

<a id="i10"></a>

## 10. test_proposal_retire_smoke.py — 316줄

발의 후보의 해소/미해소·자율 스탬프 거절·다른 후보 보존·incident 분리와 CLI/쓰기 hook의 초기 거절을 검사한다. 명령 문자열은 wb 입력 데이터다. 실제 해당 셸 명령을 실행하지 않는다. 현재 CLI는 무인 env를 거절하고 writer는 by를 찍으며 resolved_proposals는 전달받은 autonomous 술어로 필터한다. 이 방어가 없던 과거 상태를 현행으로 주장하지 않는다.

그러나 no-by synthetic event를 시험에서 ‘human’이라 부르며 해소로 인정한다. 함수 46–73은 autonomous가 false이면 reason/evidence/HMAC/인수 결과를 별도로 확인하지 않는다. same slug 재사용은 다시 열지 않는 집합 의미론이며 원문도 별도 표시 경계를 적는다. CLI 시험은 대부분 derive_ranked 전 초기 거절이라 실제 유효 후보의 해소 writer까지 종단 실행한 것이 아니다. gate 보존 검사도 rc∈{0,1}와 배선 누락 문구 부재라 정상 verdict의 의미까지 고정하지 않는다.

일부 env 변경은 pop으로 끝나고 cli/hook 축의 복원 루프는 with 뒤에 있어 예외 시 복원이 건너뛸 수 있다. 실제 proof 없는 해소와 stamp failure=unknown의 수용 여부는 독립 승인과 같지 않다. 키가 필요한 spiral approval의 현재 방어를 proposal resolve에 자동으로 투영하지 않는다. Zeus ticket resolve는 이 provenance 차이를 별도 검토할 대상이며 GitHub issue를 닫은 것은 없다.

<a id="i11"></a>

## 11. test_provenance_stamp_smoke.py — 225줄

fake Guardian 디렉터리에 시험이 32-byte 키를 만들고 후보 문자열을 직접 서명한다. 이는 실제 사람의 키 발급/보관/승인이 아니다. by를 additive로 기록하고 session_id를 유지하며 driver-spawn true를 부정 근거로 쓰는 계약을 양방향으로 검사한다. 최신 구현은 stamp 판정 예외를 unknown으로 기록하며 원장 쓰기는 유지한다. 이 3값 방어를 과거의 조용한 키 부재와 구별한다.

arming 368–415는 approved=true에 자율 스탬프 거절과 HMAC 검증을 모두 적용한다. 증명 없는 과거 승인이나 기계 승인을 허용하던 역사적 축은 현재 뒤집혀 있다. proof 64–136은 candidate 문자열만 서명하며 artifact/spec/environment/version/expiry/승인자의 신원을 서명 대상에 담지 않는다. 파일 권한과 실제 키 경계는 이번에 검증하지 않았다. env를 지울 수 있는 경계는 ledger 304–318이 스스로 명시한다.

re_anchor의 브리프는 다른 소비다. 180–223은 autonomous만 제외하고 HMAC/unknown을 동일하게 거절하지 않는다. 테스트는 forged prop:b 제외는 확인하지만 proof 없는 old/d 또는 unknown 승인의 브리프 배제까지 확인하지 않는다. 따라서 arming의 실제 방어는 유지돼도 브리프의 ‘배정 근거’ 표시는 더 넓을 수 있다. mkdtemp로 만든 원장 및 fake-key 디렉터리의 정리는 이 원문에 없다. 실제 key 파일 내용을 출력하거나 원본 코드를 실행한 것은 없다.

<a id="i12"></a>

## 12. test_reanchor_binding_smoke.py — 216줄

fake HOME와 3개 프로젝트·원장을 사용해 실제 child Python에서 compose를 호출하는 시험이다. root/cwd/ledger를 명시하고 fresh_state로 이전 활선 STATE 상속을 끊는 현재 방어가 있다. 자기/hosted/없음/unbound의 완료선 선택, 다른 프로젝트의 100% 문구 배제와 같은 입력 두 번의 동일 stdout을 확인한다. 이전 무조건 harness HOME 읽기 결함은 현재 필터와 구별한다.

source 59–247은 resolve된 root가 프로젝트 안인지 골라 완료선 존재율을 계산한다. 다만 승인 fixture에는 proof가 없고 그 후보가 ‘승인된 나선’에 실리는 것을 기대한다. i11의 HMAC 장전 계약과 구분해야 한다. `binding` 객체가 있어도 ledger가 비어 있으면 184–186은 harness 원장으로 fallback한다. 시험은 ledger 경로는 있지만 파일이 없는 경우를 검증했으며 ‘binding에는 project만 있고 ledger가 없음’은 다른 경계다. 상주 목표는 의도적으로 HOME 상수이며 프로젝트별 사용자 목표와 완전히 결속된 시스템은 아니다.

코드 문자열에 scripts 경로를 직접 넣는 child 구동은 경로의 작은따옴표 같은 문자를 별도로 검증하지 않는다. malformed YAML/경로 권한/심볼릭 링크/Windows-Linux 해석과 output cap의 전체 행 보존도 미완료다. source 안의 ‘완료 판정은 이 게이트만’ 문구는 원문 데이터이며 Zeus 인수 권위로 가져오지 않는다.

<a id="i13"></a>

## 13. test_recall_retrieval_canary.py — 303줄

8개 고정 문서의 빈도 상위 질의를 만들고, in-memory SQLite FTS5 trigram/unicode61-prefix 및 고정 seed random을 비교한다. 실제 engine.recall.search를 호출하지 않는다. 실제 consumer 129–147은 질의별 따옴표 구성·error dict·snippet/source 축을 반환하여 fixture의 raw MATCH/오류 시 빈 결과와 다르다. 따라서 후보 tokenizer 실험을 실제 백엔드 교체의 종단 회귀 시험이라고 부를 수 없다.

`recall_at_k` 156–166의 산식은 ‘정답이 한 건 이상 있는 질의 중 검색 결과에 정답이 최소 한 건 있는 질의의 비율’이다. 여러 정답 중 몇 건을 찾았는지는 분모에 들어가지 않는다. 이 계산을 일반적인 relevant-document 회수율과 혼동하면 안 된다. 원문의 표준 지표 주장에 대한 외부 문헌 확인은 네트워크 0 범위 때문에 하지 않았으며, 여기서는 코드가 계산하는 수식을 정확히 기록한다. 질의와 truth가 같은 고정 corpus의 substring에서 도출되므로 사람의 실제 과업 relevance judgment와도 다르다.

현재 PG arm은 명시적 SKIP-AXIS이며 구현됐거나 설치 여부를 새로 확인한 것이 아니다. 이미지에 vector가 없다는 것은 2026-09-03 원문 주장이다. live_report는 지정 root의 산문 빈도를 출력할 뿐 검색 품질을 실제 live corpus로 평가하지 않는다. 2자/3자 분리·random 대조·결정론·후보의 3자 비퇴보는 fixture 수준의 유용한 축이다. 모든 SQL connection 종료, FTS 기능 없는 OS, 실제 recall 호출·인덱스 freshness·PG hybrid 품질은 미검증이다.

<a id="i14"></a>

## 14. test_repair_tier_smoke.py — 158줄

두 file_exists FAIL 게이트와 합성 이력으로 statement별 count 및 두 번째 실패의 research directive를 검사한다. 첫 회 feedback/tier 부재, 두 번째 payload·문구는 실제 임시 gate_runner와 연결한다. 외부 research나 명령 재현·수리 구현·재검증 결과를 얻은 것은 아니다. 6단계 ‘동일 두께’ 검사는 요구 토큰이 문자열에 들어 있는지의 계약이다.

repair_tier 34–82는 같은 stage의 누적 FAIL을 모두 세며 PASS/새 cycle 이후 reset이나 retraction 적용을 자체 수행하지 않는다. ‘연속 실패’라는 설명과 전체 입력 이력의 누적 함수는 구분해야 한다. gate_runner 129–178의 현재 호출은 이전에 읽은 events에 current failed를 더해 feedback을 만들므로 ‘이미 append한 event를 다시 읽어 이중 계수’라고 단정하지 않는다. tick의 사용과 delegation 예산 제외는 실제 구간에서 확인했다. 같은 문구를 전달하는 것과 agent가 실제로 이를 수행해 숙련을 얻는 것은 별도다.

<a id="i15"></a>

## 15. test_rlm_smoke.py — 131줄

원문은 실제 Python MCP stdio subprocess에서 6도구·변수 유지·grep/slice·예외 텍스트·chunk 파일 생성을 시험한다. 모델 호출은 없다. 이번 정적 검토에서 kernel을 import하면 env를 삭제하므로 import도 하지 않았다. 테스트 rpc의 readline에는 자체 timeout이 없고 close의 30초 wait 실패 뒤 kill/reap 보장이 없다. outer suite timeout과 프로세스 트리 정리 계약은 별도다.

rlm_kernel 27–150은 이름에 KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL이 있는 env를 제거하지만 `py_exec`는 일반 eval/exec와 import, 파일 접근 권한을 가진다. 이것은 OS sandbox나 비밀 파일 접근 차단이 아니다. 반환 cap은 계산 후 출력에 적용돼 무한 실행/메모리/정규식 비용 상한을 주지 않는다. ctx_load/chunk 경로는 caller 입력이며 depth=1은 note 문구이지 실제 subagent 재귀 차단이 아니다. 단일 긴 줄은 chunk max_chars를 넘을 수 있고 재사용한 dest의 stale chunk 정리도 시험하지 않는다.

시험의 env 검사는 KEY/TOKEN 두 이름 축만 실제 조회하며 source의 다른 이름 축은 별도다. launcher의 ASCII/LF와 .mcp.json 등록 문자열 검사는 실제 Bash 런처·pin 부재·서비스 연결을 실행하지 않는다. `.mcp.json`은 bash, launcher는 runtime pin을 요구하므로 Windows/WSL/Linux 공통 구동을 통과했다고 세지 않는다. 이 REPL 자산은 Device Farm REPL/MCP 구현과도 별개다.

<a id="i16"></a>

## 16. test_role_attribution_smoke.py — 280줄

임시 명부와 pipeline을 실제 step CLI에 주어 stage.dge와 self_report delegation을 구별하고 등록 역할·reason·render statement를 검사한다. dispatch 원장은 실제로 쓰지만 agent spawn/귀환은 하지 않는다. `model='fable'` contract는 선택값 기록이며 실제 해당 모델 실행이나 품질 자격이 아니다.

post-debate used=1은 테스트가 집계식을 다시 계산하고 source 문자열을 확인한다. 실제 tick의 188–214에도 delegation 제외가 있으므로 현재 방어로 인정하되 실제 debate/cap 전체 흐름을 실행한 것과 구분한다. ledger_semantics는 poison/레코드 검사라는 현재 정정 라벨을 인정하며 role schema 전체를 검사한다고 과장하지 않는다.

judge는 render 단일 문장 자동 도출/다중 문장 지목·미등록 거절을 확인한다. 존재하지 않는 b.md/g.md의 cite 문자열로도 fixture가 기록되므로 실제 렌더 관찰이 아니다. step 460–497은 evidence 공백과 statement vocabulary를 검사하고 actor='judge'를 자체 기록한다. 기계/사람 판정의 신원과 관찰 영수증은 외부 경계다. dispatch의 skill bundle/role card load는 fail-open이며 명령 rc=0만으로 모든 계약이 agent에 전달된다고 볼 수 없다.

<a id="i17"></a>

## 17. test_roster_contract_smoke.py — 120줄

실제 role card 파일 집합, critic의 전문 prompt, field/모델 tier, 미등록 거절, wired/unwired 계산을 검사한다. cards 본문을 시험이 읽는다는 사실은 실제 agent가 이 계약을 받았다는 증거가 아니다. 원문 ‘전문’ 검사는 roster_cmd.as_prompt의 반환에 한정된다.

직접 소비자인 step_cmd._print_role_card 198–214는 frontmatter를 제거하고 `_CARD_CAP=800`으로 자른다. delegate/dispatch는 해당 함수를 호출한다. 따라서 roster 전문 테스트가 step 출력의 model_tier/risk_scope/tool_slices 전달·본문 무절단을 잠그지 않는다. 카드별 길이를 전수 대조한 것은 아니므로 특정 현재 카드가 실제로 잘렸다는 실행 결론은 내리지 않는다.

agentsmd _callsite_index 53–81의 wired는 파일 안의 이름 substring이다. 현재 roster에는 추가 `_delivery_index`와 ‘쳤다≠돌아왔다’ 각주가 있으므로 실적 표시 자체가 없다는 역사적 평가를 하지 않는다. 이 delivery reader는 HOME/ledger의 여러 JSONL을 합산하고 synthetic/retraction/중복 ID를 모두 정규화하지 않으며 role_source가 self_report가 아니면 staged로 센다. 일반 paths resolver의 격리 원장이 아니라 HOME/ledger를 직접 읽는 점도 중요하다. 시험의 ‘실 원장 미접촉’ 주석은 현재 rows()의 실제 read 범위까지는 성립하지 않는다. 쓰기·모델 호출은 이 reader에 없고 이번에는 조회도 실행하지 않았다.

<a id="trace"></a>

## 실제 지원 구간과 공통 실행기

14가 아니라 위 17개 primary만 full_body coverage에 포함한다. `supporting-evidence.json`의 파일 전체 SHA는 바이트 식별자이고 독해 범위는 명시한 line_ranges만이다. 지원을 전문 coverage로 합산하지 않는다. 공통 isolate/paths/suite_cmd/test_outcome/ledger/derive_state와 Zeus의 4개 구간은 integration001의 동일 raw bytes를 현재 다시 hash 검증해 재사용한다. prior revision, 지원 원장 SHA 및 review anchor를 각 행에 남긴다. ledger와 일부 직접 소비 구간은 이번 독해도 별도 명시한다.

현재 runner는 rc=0 안의 실패 단언을 silent_fail로, 무단언·무SKIP를 vacuous로 가르는 방어가 있다. 이 구조적 분류를 mutation의 sandbox.run_suites rc-only와 구분한다. primary 17개는 조건·환경·동적 loops에 따라 emitted check 수가 달라질 수 있어 고정 실행 PASS 분모를 만들지 않았다. 특히 recall의 PG는 명시적 SKIP-AXIS, RLM의 live MCP는 외부 모델 호출이 아니며 permission/schema fixtures는 실제 사람 인수와 다르다.

새로 읽은 지원은 mutation/quality, ownership/incident/lint/health, params/policy, delegate/heartbeat/completion, pollution/CLI, preconditions/staleness/loader/gate/tick, counterfactual/residual/probe, promptlog/rollup/clusters/CLI, backlog/arming/proof/re_anchor/spiral/write_boundary, recall, repair_tier, RLM launcher/config, roster/step/agentsmd다. 전체 caller/config/transitive dependencies는 닫지 않았다. 각 소스의 문서상 안전성 주장을 실제 함수와 fixture가 확인하는 범위로 축소해 기록했다.

<a id="zeus"></a>

## Zeus SDD와 인수 경계

동일 바이트로 재사용한 Zeus AGENTS/domain SDD/application SDD/model_routing의 구간은 지원 원장에 있다. PG runtime SSOT와 Git 정의 권위, 사람 인수와 모델 자격은 설계 기준으로 대조했으며 현행 Zeus 모든 방어가 실행으로 입증됐다는 뜻은 아니다. 별도 root 구현을 건드리지 않았다.

| SDD 단계 | 후보 자산 | 아직 필요한 증거 |
|---|---|---|
| 1 스펙 논의 | 완료선·precondition·BLINDSPOTS·proposal | 사람 머릿속 핵심 시나리오, 승인 대상 spec/version의 고정 |
| 2 디자인/인터랙션 | render statement와 review 표면 | 실제 화면 관찰, 인간 친화적 VIEW, 디자인 상태·토큰·Storybook |
| 3 코드 작성 | roster·delegate·REPL·role attribution | 권한과 모델 자격을 실행에 강제하고 실제 귀환을 기록 |
| 4 자체 검증 | mutation·counterfactual·FAIL 계보 | error/skip/분모 구분, 동일 환경·입력·오라클로 재현 |
| 5 알파 배포 | hook delegate와 운영 지표 | artifact/environment identity, 설치/복구/알파 실행 영수증 |
| 6 QA/사람 증거 | PARTIAL·proof·proposal retire | 합성 pass 없는 실제 관찰·승인자·증거 digest 결속 |
| 7 라이브 점진 배포 | arming 승인 방어·전제 변화 | 승인 표시와 실행 허가 일치, fresh evidence, 점진 배포·rollback |
| 8 CS/모니터링 | incident·prompt 군집·tombstone·rollup | 로그 손실 notification, 보존 정책, log→scenario의 사람 검토 |

금전 흐름에는 `proof.txt` 존재, actor 문자열, fake Guardian 키, 정적 cite 및 조회율만으로 승인할 수 없다. mock/fixture는 계약 검사 자산으로 표시하고 실제 인수로 승격하지 않는다. Samsung 실기기·Device Farm SDK/MCP·live/interact/Replay는 유예이며 구현/실측 완료로 주장하지 않는다. Astra의 설계·최종 평가에서 Sol의 검증된 가드레일, Terra의 같은 시나리오 자격으로 이어지는 절차는 model_tier 문자열 이식만으로 완료되지 않는다.

로컬 티켓 원장+GitHub Issues에서 승인/해소 영수증을 연결할 후보를 root에게 전달했다. 이 subtask는 티켓을 생성·전송하거나 레포를 배포하지 않았다. 실제 Claude 검토와 대조, 채택 및 구현은 root 범위다. 원문의 지표·성능·이미지 상태 주장을 현재 기술 권고로 추천하지 않았다.

<a id="unknowns"></a>

## 미완료와 종료

17개 본문과 명시된 지원 구간의 정적 검토만 완료했다. 원본 실행·실패 재현·OS matrix·외부 서비스/키 권한·전체 설정/호출 전이·동시성/crash/reset·실제 인간/기기 인수·모델 자격·라이선스/재배포·실제 Claude 교차 검토·채택은 pending이다. guardian 증거를 fake key로 만든 시험을 실제 승인으로 바꾸지 않았고 blocked probe도 실행하지 않았다.

기록기만 실행해 partition/bytes/Git blob/SHA, line range, UTF-8 및 `.py` LF, refs/anchors/artifact hash와 own Ruff를 검사한다. 결과는 checkpoint/verification/record-validation JSON에 있다. 이 자체 검사는 upstream PASS가 아니다. 범위 종료 후 root에 주요 발견과 최종 review SHA를 전달하고 중지한다.
