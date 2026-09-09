# 핵심 실행기 001 독립 정적 검토

범위는 `harness:scripts/engine:001`의 18개 파일, 190,174바이트이다. 고정 revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`이며 `manifest.json`의 크기·Git blob·SHA-256과 대조했다. 모든 지정 파일의 전문을 읽었다. 출력이 절단된 fleet_contracts 후반과 ladder_probe 첫머리는 별도로 다시 읽었다. 다른 리뷰 문서를 선참조하지 않고 원본 구현과 직접 소비자를 읽어 판단했다.

**원본 실행 0건, 설치·원본 수정·기기 조작·commit/push 0건이다.** 과거 자동 보안 차단을 받은 gate writer probe는 재시도하거나 우회하지 않았다. 아래 결과는 정적 도달 경로와 계약 공백이며 실행으로 재현한 결함이라고 표현하지 않는다. 기존 테스트의 존재와 내용을 확인했지만 실행하지 않았다. 전체 하위 시스템 감사, Zeus 구현 등가, 흡수 승인, 실제 Claude 검수 완료를 뜻하지 않는다.

## E01 — 명령 결과·증적·플랫폼 계약

`checks.py`는 8종 registry, PASS/FAIL/ERROR 구분, 미등록 type ERROR, 예외 ERROR, exit 반복 횟수의 양수 확인과 첫 실패 중단을 구현한다. 반면 다음 경계가 있다.

- `_metric_threshold`는 `_source_text`가 돌려준 명령 종료 코드를 기록만 하고 숫자 비교에 반영하지 않는다. 명령이 실패했어도 stdout/stderr에 문턱을 만족하는 숫자가 있으면 PASS 경로가 열린다.
- `_trigger_effect`도 관측 명령 종료 코드·관측 시각·대상 run/commit 결합 없이 합쳐진 stdout/stderr의 정규식으로 PASS를 정한다. config 존재와 관측 명령 존재는 강제하지만 실제 이번 트리거의 성공을 증명하지 않는다. `_db_query`는 비정상 종료를 FAIL로 처리하므로 세 경로가 동일하지 않다.
- `http_probe`는 HTTP status만 읽는다. 기대하는 오류 status가 있어도 `urlopen`의 예외 경로는 항상 FAIL이다. 응답 본문 계약은 검사하지 않는다.
- `file_exists`는 디렉터리도 매치로 센다. `file_content`는 여러 파일을 합친 텍스트에 존재 규칙을 한 번 적용하므로 파일별 의무와 다르다. forbid와 expect/against를 동시에 주면 forbid 경로에서 먼저 반환한다. 이런 조합을 loader가 금지하는지까지는 이번 범위에서 검증하지 않았다.
- 명령은 `shell=True` 문자열이며 Bash/PowerShell/cmd 선택이 명시되지 않는다. Python 경로는 따옴표로 감싸지만 shell 문법·프로세스 트리 종료·출력 전체 크기·반복 전체 시간 상한은 이 함수들의 계약에 없다. 600초는 각 실행 상한이다. `repeat`에는 양수 외 상한이 없어 외곽 루프 예산이 실행 중 명령 묶음을 즉시 제어한다고 볼 수 없다.

읽은 `test_checks_smoke.py`는 정규식, 파일 metric, echo로 만든 관측/DB 출력, repeat 양성·실패를 검사한다. 실제 CI 사건이나 DB 동작의 증거는 아니다. Zeus에서는 shell 종류와 argv, 환경/빌드 식별자, 관측 실행 ID, 종료 코드, 유한 출력·실행 예산을 adapter 계약으로 묶을 후보이다.

## E02 — 사람·렌더 판정의 대상 귀속

`gate_runner.py`는 machine 결과를 원장에 쓰고 ERROR면 gate_verdict를 만들지 않으며, 외부 판정 부재/PARTIAL은 PENDING_HUMAN으로 남긴다. cycle_started.redo가 있는 단계의 외부 판정을 철회하는 방어도 실제 존재한다.

그러나 `_external_verdict`는 stage+mode만 대조한다. 실제 `step_cmd judge`는 render 문장이 여러 개면 `--statement`를 요구하고 해당 문장을 원장에 쓰지만 소비자는 statement를 쓰지 않는다. 같은 단계·같은 mode의 최신 판정 하나가 여러 문장의 결과로 재사용될 수 있다. 소비자는 actor/by, 산출물 해시, 파이프라인 revision, gate 실행 ID도 확인하지 않는다. ledger writer에는 자율 세션의 `by` 스탬프가 있으므로 귀속 장치가 전혀 없다고 할 수는 없다. 다만 이 소비 경로는 그 값을 사용하지 않는다. 외부 명령의 보안 경계 전체를 우회했다고 주장하지 않는다.

`gate_active.json`은 주석대로 advisory marker이며 잠금이 아니다. 서로 다른 실행이 하나의 marker를 덮고 지울 가능성은 남는다. feedback 횟수는 해당 stage의 모든 과거 feedback을 세며 cycle별 초기화는 이 함수에 없다. evidence_refs는 50개로 잘린다. 원장에는 각 check가 남더라도 verdict 직접 인과 링크가 전부 남는다고 볼 수 없다. 검사 뒤 계산한 precondition 지문은 실행 전후 산출물의 동일성을 증명하지 않는다.

## E03 — 자가개선의 재확인과 반복 수확은 다름

`curator.py`는 proposed digest 중 해결된 failure family를 고르고 repro 분류와 golden gate를 거친다. 새 lesson은 proposed이며 bake, pinned 예외, agent lifecycle, CRLF/BOM 관용 frontmatter 등 실제 방어가 있다. 기존 자산의 frontmatter가 읽히지 않으면 병합을 거부한다. 이 방어를 과거 주석의 미구현 상태로 되돌려 보고하지 않는다.

하지만 `harvest_repairs`의 전제는 프로젝트 원장 어디엔가 PASS가 하나 이상 존재하는 것이다. 노트 항목·수리 commit·실제 실행·시간과의 인과 결합은 없다. 같은 제목 키를 다시 수확하면 새 성공 사건이 없어도 occurrences가 증가하고 bake 이후 trust가 confirmed로 바뀔 수 있다. `l2_driver._curator_pass`는 매 사이클 같은 노트를 수확한다. 읽은 테스트도 같은 원장을 두고 재수확 병합을 기대한다. 따라서 증가한 occurrences를 독립적인 수리 재성공 횟수라고 해석할 수 없다.

키 `repair::{title}`에는 프로젝트 ID가 없어 서로 다른 프로젝트의 동명 수리가 같은 lesson에 합쳐질 수 있다. body는 최초 12줄만 생성 시 교체하고 이후 병합은 예전 body를 유지한다. digest에 해결·미해결 계보가 함께 있으면 해결된 것이 하나라도 있을 때 digest 전체를 archive로 옮긴다. 원본 digest는 남지만 proposed 재소비 경로에서 미해결 부분이 빠질 수 있다. 거부된 결정화도 resolved_any를 true로 만들 수 있다. lifecycle의 사용자 보호와 달리 `_crystallize` 병합은 기존 자산의 created_by를 별도로 제한하지 않는다. pinned는 상태 전이를 막아도 evidence/occurrences는 쓴다.

Zeus 후보는 프로젝트·사건·수리 revision·검증 영수증을 고유 키로 삼는 중복 제거와 인과 추적, 미해결 항목별 대기, 사용자 소유권, 트랜잭션이다. 제안·축적·검증·채택의 상태를 분리해야 한다. 이 문서에서 구현하지 않았다.

## E04 — 자산 필터와 golden 검증 범위

`asset_gate.py`는 필수 frontmatter 키 존재, 본문 4,000자, 소수 injection 정규식과 절대 단언 문자열을 검사한다. 값의 타입·허용 enum·출처의 진위·토큰 수는 검증하지 않는다. 스캐너 스스로 최종 경계가 아닌 휴리스틱임을 명시하며, debate는 매치를 차단하지 않고 leak_flags에 동봉한다. 이를 명령 실행 권한이나 사람 승인 검증의 대체로 흡수할 수 없다.

`golden.py`는 사례를 명령+기대 종료 코드+출력 문자열로 실행한다. 파일 부재·명령 없는 항목 제외 후 0개면 `gate()`가 true이다. 이는 docstring의 fail-closed라는 일반 표현과 구분해야 할 명시적 0건 허용이다. 현재 고정 cases.yaml에는 사례가 실제로 있으므로 현행 원본이 항상 0건이라고 주장하지 않는다. 일부 사례는 고정 fixture이고 일부는 원장·환경 상태를 읽는다. held-out은 라우팅 경로 미포함과 실패 메시지 일부 비노출이지 저장소 읽기 권한의 격리가 아니다. 기대값은 이번 보고서에 재인용하지 않았다.

curator의 두 유입은 갱신 **전** golden만 호출한다. 갱신 후 재실행·되돌림을 이 경로에서 찾지 못했다. `{python}` 치환에는 checks와 달리 경로 따옴표가 없어 공백 경로 이식성 확인이 필요하다. Zeus의 승급 기준은 0건·환경 미충족·후보 비소비·검증 불능을 성공과 분리해야 한다.

## E05 — 진화 루프의 하드캡·lease·실행 권위

`evolve.py`는 명세 모호 표지 비율, 필드명/타입/값 유사도, 동결 필드, 정체 패턴, 30세대 상태를 계산한다. 이는 텍스트·시그니처 휴리스틱이며 사람의 요구 충족 측정과 다르다. 현재 `evolve_cmd.py`는 `--executed` boolean과 `--grade`, `--frozen`을 직접 넘긴다. 높은 유사도와 executed=true이면 실제 테스트 영수증 없이 CONVERGED를 기록한다. 빈 시그니처 둘도 similarity=1이다. 테스트는 이 boolean 경로를 명시적으로 기대한다.

정적 동시성/재개 경계는 다음과 같다. state 재구성이 lease 취득 **전**이어서 두 호출이 같은 state를 읽고 순차 lease를 얻으면 낡은 세대 기준으로 추가할 여지가 있다. 취득 후 재독이나 append 직전 lease.guard는 이 함수에 없다. lease 구현 자체에는 잠금 내 획득과 guard가 있으므로 lease가 전혀 안전하지 않다는 주장은 아니다. open의 중복 검사와 append도 이 함수 안에서 단일 트랜잭션이 아니다.

gen>=30은 EXHAUSTED 상태를 선택하지만 다음 step 호출을 거부하지 않는다. 유사도 분기가 cap보다 앞이어서 상한 세대의 안정 후보는 ONTOLOGY_STABLE/CONVERGED가 된다. frozen의 새 비어 있지 않은 목록은 이전 목록을 대체할 수 있고, 기록된 JSON 파손 행은 조용히 건너뛴다. generation은 이벤트 수로 계산된다. Zeus의 PG 원장에는 세대 expected version, 소유권 fencing, 종결 상태와 재개 승인, 고정 조건 단조성, 실행 영수증이 필요하다.

## E06 — debate 수렴은 독립 패널 완료의 증거가 아님

`debate.py`는 3역할 어휘, 원장 기반 결과 재생, 같은 세대 충돌, HIGH 비평의 승인 강등, 조기 종료, 패자 논거·self-doubt 보존을 제공한다. 다만 직접 읽은 `debate_rules.evaluate_convergence`는 gen1 architect approved만으로 수렴한다. 해당 세대 critic/proposer 참여, 모델·실행 주체 인증, 실행 검증 완료가 필수 전제가 아니다. `debate_cmd`도 actor와 JSON을 인자로 기록한다. 사용자 요구인 Codex와 실제 Claude의 독립 검토를 이 이벤트 형식만으로 충족했다고 말할 수 없다.

check는 원장을 읽은 뒤 카드 쓰기와 closed 이벤트 쓰기를 별도로 수행한다. 순차 재호출은 멱등이나 동시 check의 단일 종결·카드/이벤트 원자성은 읽은 경로에 없다. debate ID는 초 단위 시각+안건 짧은 해시이므로 같은 초·동일 안건의 구분도 제한된다. 외부 입력 debate_id는 카드 파일명에 쓰이지만 이 함수에는 경로 형식 검사가 없다. 이것을 악용하는 probe는 수행하지 않았다. project_root를 주면 실제 저장 경로와 반환된 knowledge/decisions 경로도 달라질 수 있다.

## E07 — circuit과 실제 오류 처리

`circuit.py`는 stuck/fruitless, 냉각 배증, half-open trial, 24시간 storm, 유한 이력을 순수 함수로 판정한다. 정기 드라이버가 open에서 알림·halt를 만들고 성공 스폰 뒤 trial을 기록하는 연결을 확인했다. 토큰·비용 트리거는 모듈이 직접 유예한다고 명시한다. 외곽 tick에는 iteration/wallclock/delegation cap, 드라이버에는 일일 spawn cap이 실제 있다. 따라서 예산이 전혀 없다고 할 수 없다.

시험 성공은 trial 시각 이후의 임의 gate_verdict PASS로 판단하고 spawn_key·stage와 결합하지 않는다. 메타 읽기 실패는 초기 상태로 돌아가고, 드라이버는 circuit 판정 예외에서 closed로 처리해 스폰을 계속한다. 이 선택은 로그에 드러나므로 침묵 실패라고 표현하지 않는다. 모듈의 load→assess→save와 trial 쓰기에는 통합 잠금이 없지만 외부 드라이버의 전체 lease 획득 순서까지는 이번에 전문 감사하지 않았다. 따라서 동시 스폰이 실제로 발생했다는 결론은 유보한다.

## E08 — 프로브가 측정하는 것과 실제 변경 범위

`counterfactual.py`는 기준선 PASS→주입→복원 PASS 비교와 문장별 결과를 만든다. 실제로는 프로젝트 target 옆의 고정 `.cfprobe.bak`에 복사한 뒤 **원 target을 수정**한다. 임시 복사본에만 주입한다는 첫 설명과 다르다. finally는 일반 예외 복원 경로이며 프로세스 종료·동시 수정·기존 백업 충돌을 보장하지 않는다. gate 명령은 세 차례 같은 project root에서 실행되므로 부수 효과의 격리도 이 함수가 제공하지 않는다. 주입 결과 `!=PASS`면 live에 넣어 ERROR까지 검출력으로 계산한다. 전체 게이트 중 하나가 반응해도 stage verdict LIVE이며 모든 문장의 효력을 증명한 것은 아니다. CLI는 LIVE를 exit0으로 전달한다. **이 프로브는 이번에 실행하지 않았다.**

`mutation.py`는 HEAD worktree, baseline green, 0 suite 거부, pycache 제거 후 개별 문자열 변이를 측정한다. baseline 실패를 높은 kill score로 오인하던 과거 경로는 현재 방어된다. dirty 원본 허용은 dirty 변경을 측정한다는 뜻이 아니다. 치환 후보는 문자열을 제거한 code에서 찾지만 실제 치환은 원본 줄의 첫 연산자를 바꾼다. 동일 연산자가 앞선 문자열에 있으면 다른 곳을 바꿀 가능성이 있다. target_rel의 resolve/하위 경로 검사, 격리된 의존·환경·네트워크 제한은 이 함수에 없다. run_suites는 사용자 site 경로와 환경을 일부 상속하며 완전 venv 격리는 미완료라고 명시한다. `quality_cmd`는 현재 점수 하한 미달 시 exit1이므로 모듈 첫머리의 '진단이지 차단 아님'은 전체 CLI 동작을 설명하지 못한다.

`ladder_probe.py`는 임시 guardian 설정과 합성 원장을 만든 뒤 실제 watchdog.py를 호출하는 검사이며 살아 있는 상태 파일의 형태 감사는 별도이다. 고정 sibling guardian 경로와 sys.executable을 쓰고 `_fires`는 실행 returncode를 확인하지 않은 채 alerts.log의 `progress` 부분 문자열을 본다. 양성 기준선이 vital을 별도로 판정하므로 모든 실패가 성공으로 되는 것은 아니나, 반전 케이스의 실행 불능과 조건 미발화를 구별하는 증거는 약하다. 기기 Farm이나 실제 서비스 E2E와는 다른 검사다.

## E09 — 그래프·atlas·mirror의 주장 한계

`code_graph.py`는 Java 클래스/인터페이스, 필드·어노테이션·메서드를 tree-sitter로 추출한다. parse_errors는 오류 있는 파일 수이며 심볼 refs 해석이나 빌드 성공이 아니다. 내부 클래스 FQN과 short name 충돌, 완전 수식/제네릭 타입, constructor-only injection 등은 현재 구조/이름 매칭의 별도 검증 대상이다.

`graph_queries.py`에는 앵커 0건, 간선 0건, 진입점/Service/mapper XML 부재 방어와 overlay 파손 ERROR가 실제 있다. 그러나 coverage/partition은 문자열 포함이며 acyclic은 문서 전체 정규식이다. code queries는 parse_errors를 evidence에 실어도 verdict의 차단 조건으로 사용하지 않는다. MyBatis statement를 set으로 합쳐 중복 ID 다중 정의를 따로 세지 않고, XML 없는 interface 전체를 역으로 검사하지 않는다. data_boundary는 미소유 파일·테이블을 검사 대상에서 제외한다. Python 파일이 존재해도 모든 stem이 owners 밖이면 실제 판정 모집단 없이 PASS가 가능하며, Java는 unattributed를 드러내지만 이를 자동 FAIL로 삼지 않는다. 모델 별칭과 변수 경유 인스턴스 쓰기·SQL 동적 식별자는 전체 검출되지 않는다. '쓰기는 예외 없음' 문구와 달리 허용 숫자 max_foreign은 쓰기+미선언 읽기의 합에 적용된다.

contract parity는 DRIFT와 실효 blocking의 조합만 FAIL로 하고 LOW_FIDELITY/NEEDS_TRANSFORM은 advisory PASS로 남긴다. 원장을 못 읽으면 자동 승급을 끄므로 이미 강화된 자동 차단이 약해질 수 있다. 이를 fail-closed gate와 같은 타입의 PASS로 소비하는 경우 품질 신호를 분리해야 한다. 전역 카탈로그는 process cache이며 프로젝트 overlay가 기존 spec을 덮는다. `gate_ratchet.py`는 stage+statement의 삭제만 확인하므로 같은 문장 아래 regex·문턱·check·scope 변경을 추적하지 못한다. tick에서는 ratchet 예외를 빈 위반으로 처리한다. 면제 사유의 별도 loader 검증은 이번에 확인하지 않았다.

`endpoint_graph.py`는 동일 catalog/parity/scope/자동 승급 로직으로 문서·seam·필드의 1-hop 영향을 설명한다. overlay 파손과 소스 부재를 드러내고 CLI도 overlay 오류를 반환한다. 다만 이름이 같다는 이유로 JOIN한 필드는 의미·타입·실제 호출 관계를 보증하지 않는다. 이 atlas는 재생성 가능한 관측 지도이며 배포 영향의 완전한 분석이 아니다.

`mirror.py`는 root Markdown 앵커와 제한된 확장자 파일 목록을 만들고 ref 존재에 따라 KEEP/ABSENT/DROP을 분류한다. 첫 문자열 출현 파일을 소유자로 고르므로 정의와 역참조를 구분하지 않는다. ref의 path:line은 파일 존재만 보며 행 번호나 주장 내용은 확인하지 않는다. wiki 문서 0개는 거부하지만 앵커 0개+제목뿐인 wiki 파일 한 개는 `bool(docs)` 조건을 만족시켜 ready가 될 정적 경로가 있다. Dart/Kotlin/TSX 등은 현재 코드 확장자 목록에 없다. HEAD만 기록하므로 dirty 입력 바이트나 원문 주장의 진실성 영수증도 아니다.

## E10 — 함대 추출과 응집도 발의

`fleet_contracts.py`는 Dart enum HTTP, C# attribute, Spring mapping, proto RPC, WS action, Kotlin Retrofit, Android Intent, 생성자 fan-out을 정규식으로 읽는다. 모듈 서두의 WS/Intent 미지원은 이후 함수 추가를 반영하지 못한 과거 설명이다. 다만 기본 atlas CLI는 Dart HTTP+proto와 Spring/C#만 조립하고 WS는 별도 명령이다. Kotlin·Intent 함수의 더 넓은 소비는 이번에 확인한 CLI 범위를 넘어 추적하지 않았다. DTO schema·배포 버전·base URL 귀속·실제 호출 의미는 빠져 있어 코드도 고아를 위반이 아닌 관찰이라고 명시한다. 이식 시 앱별 하우스 문법과 검사 모집단을 선언해야 한다.

fanout은 이름과 줄 prefix 휴리스틱이다. CLI `--type`은 전체 tally 대신 이미 상위 15개 data carrier/상위 5개 overall로 잘린 결과에서 찾는다. 따라서 5개 이상 호출된 타입도 상위 밖이면 '5곳 미만이거나 정의 클래스 아님'이라고 안내할 수 있다. 실측을 재현한 것이 아닌 정적 경로이다.

`cohesion.py`는 git co-change와 탐욕 Jaccard 군집을 사용해 분해를 **발의**한다. 변경 이유의 근사치이며 연구·다른 프로젝트 실측 주장은 현재 검증한 사실과 구분한다. git 실패는 '이력 없음/판정 불가'로 보고하고 계약 읽기 실패는 derived 제외를 비워 발의를 허용한다. 드라이버는 상시 로드 표면만 검사하고 proposed에 쓰며 신규 발의 때 notification 큐를 남긴다. 통지 큐 뒤 실제 사용자 전달까지는 이 구간으로 입증하지 않는다. 텍스트 군집을 자동 구조 개편의 승인으로 삼지 않는 경계는 유지할 후보이다.

## Zeus 대응과 남은 실행 증거

Zeus AGENTS는 Git 정의/PG runtime SSOT를 요구한다. 읽은 `PostgresStore.transaction`은 control-plane advisory transaction lock을 사용한다. upstream의 ledger/evolve JSONL, circuit 메타 JSON, lesson 상태 frontmatter, decision 카드와 이벤트 분리 쓰기를 그대로 runtime 정본으로 복제하면 이 계약과 충돌한다. 제안·실험·관측·승급 기록은 PG aggregate/version/인과 ID로 적응하고 Git에는 승인된 정의와 재현 가능한 export를 두는 설계 후보로 넘긴다. 현재 Zeus 전체 운영 경로의 PG 보장을 검증했다는 뜻은 아니다.

현재 Zeus `model_routing.py`는 미자격 구현도 Astra로 유지하고 SDD report는 model transfer를 unqualified로 표시한다. upstream debate/evolve의 문자열 수렴·boolean 실행·교훈 반복 수확은 Astra→Sol→Terra 동등 수행 자격의 증거가 아니다. 별도의 실제 작업 분포·불변 가드레일·실행 모델 영수증·비용/품질 관측·실패 시 회수 기준이 먼저 필요하다.

| 사용자 8단계 | 가져올 후보 | 이 검사만으로 통과할 수 없는 부분 |
| --- | --- | --- |
| 스펙 논의 | debate의 비평·미해결 의심 보존 | 실제 Claude 독립 참여와 사람이 가진 핵심 의도 |
| 디자인 분석 | diagram/contract atlas와 명시적 검사 범위 | 렌더 실물·사용자 경험·의미 정합 |
| 코드 작성 | 코드 구조·함대 계약·fan-out | 실제 서비스 동작과 버전별 플랫폼 계약 |
| 자체 검증 | 오류 분리·음성 대조·기준선 확인 | mocked/echo 관측을 제외한 실제 환경 재현 |
| 알파 배포 | 실행 ID·환경·빌드에 결합할 영수증 구조 | 실제 배포와 health 본문·연동 관측 |
| QA 및 증적 | 문장별 증거·PARTIAL 파킹 | 인증된 사람 승인, 삼성 실기기 시나리오 |
| 라이브 배포 | bounded loop와 중단 신호 | 점진 배포·실제 복구·금전 흐름 검증 |
| CS 대응 | failure family·curator·circuit·notification | 사고별 인과·중복 제거·실제 알림 전달·회귀 재현 |

삼성 기기 단계는 유예 상태이며 Device Farm SDK/MCP/replay를 구현했다고 주장하지 않는다. Zeus 현재 SDD report 역시 모든 단계 blocked이며 승인 권한이 없다. 전문 정적 읽기의 완료와 구현·인수 완료를 분리한다. 후속으로 실제 Claude 교차 검수, 안전 경계 설계, 격리 테스트와 플랫폼별 재현, 라이선스·현재 공식 자료 검증, 적응 구현과 승인이 남는다.
