# Guardian 전수 의미 검토 — Codex 독립 검토

검토일: 2026-09-09. 원본: https://github.com/trevi00/harness-guardian.git. 고정 commit `e7ced4a632a38726dca44e84fa0a00b8e1f0b6f4`, tree `aa3f68af50140879972fa4c88905afa87317c6de`. Zeus 대조 HEAD `0548efaf1bc8833c750c80b242de03b5a73d7799`의 현재 파일을 읽었으며 대조 파일의 바이트 해시는 `zeus-comparison.json`에 남긴다. observed는 별도 commit이 아니라 manifest에 기록된 로컬 바이트이다.

분모는 추적 경로 정확히 13개이다. 13개 모두 파일 본문·호출·상태·실패·테스트를 의미 검토했다. 미검토 추적파일은 없다. 이는 도입 승인 또는 운영 검증 완료 선언이 아니다. 비추적 운영 `config.json`, `approval_key`, `mutation_token.json`, 실제 state와 secret는 읽거나 복사하지 않았다. 따라서 실효 ACL, 실제 scheduler 등록, 현재 operator 승인, 운영 임계값은 **검증하지 않았다**. 기존 권한·승인 증명은 Zeus에서 재사용하지 않는다.

## 증거와 실행 범위

`files.json`은 13개별 Git blob·size·SHA-256·처분·검토 절·실행·한계를 연결한다. 획득 manifest는 변경하지 않았다. `.gitignore`는 원래 누락되어 원본 저장소에 `git show <fixed revision>:.gitignore` 읽기만 수행했고, 이후 제공된 고정 스냅샷과 함께 검사했다. `source-differences.json`은 원본 SHA와 LF 정규화 비교를 구분한다.

상용/오픈소스 LICENSE 파일, 의존성 lock, CI, 패키징, installer는 추적 13개에 없다. Python 표준 라이브러리와 git 실행파일, Windows tasklist/Task Scheduler, 외부 harness CLI에 의존한다. 명시적 라이선스 부재이므로 외부 코드 재배포 허가를 추정하지 않는다. 사용자 소유 참조를 바탕으로 Zeus 계약에 맞춰 독자 구현하는 adapt를 권고하며 출처와 제한을 보존한다.

사전 테스트 코드와 실행되는 sibling 의존성을 읽은 뒤 immutable image `sha256:39d4f226fa8b1ae6087b283b16d0176e9181f8aaf31dcbf0c9145e513453725a`에서 실행했다. 모든 Docker 호출은 `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, readonly source bind, 512 MiB/1 CPU/100 PID, 128 MiB `/tmp` scratch, in-container timeout을 사용했다. 원본 설정·인증·상태·Docker socket은 마운트하지 않았다. fixture가 만드는 Git/JSON/복원 대상은 container `/tmp`에만 존재했다. 호스트 설치·운영·복원은 실행하지 않았다.

| 스위트 | pinned | observed | 검증 범위와 남은 한계 |
|---|---|---|---|
| test_console_encoding_smoke.py | PASS | PASS | cp949 실패 대조군, issue/status/거부 rc·한글, AST 가드/독립 import. HTTP console 서버의 인증·요청·UI는 실행하지 않음. |
| test_notify_relay_smoke.py | PASS | PASS | 비장전 릴레이·watermark 무중복·append 증분. 외부 webhook은 실행하지 않음. |
| test_recovery_smoke.py | PASS | PASS | 봉인 파손→fixture 복원, 신규 파일 제거, 원장 전진, 사건 cap·safe mode·회복·복원 수단 부재. |
| test_restorer_smoke.py | PASS, 의존 보완 후 | PASS, 의존 보완 후 | mark의 clean/실패/판정경로 래칫·복원·원장 감사·assert regex 대조 12단언. 최초 source-only는 `/harness/config/paths.yaml` 부재로 실패했으며 그 receipt도 보존. |
| test_watchdog_smoke.py | PASS | PASS | 비장전/협업 휴면, 심박 정체/부재·무전진·safe mode·회복. Linux에서 tasklist가 없으므로 `_l2_session_alive`의 예외→True 경로를 탄다. Windows PID 생존 판별 성공 증거가 아니다. |

스모크는 pytest 수집 대신 원래 선언된 `python tests/test_*.py` main을 실행했다. `*.receipt.json`은 argv, rc, stdout/stderr를 그대로 보존한다. restorer의 재실행은 guardian 원문 파일 전부의 바이트 동일성을 검사한 assembled 복사본에 **새 합성** `config.json = {harness_home: /harness, python_exe: /usr/local/bin/python}`만 추가했다. sibling `/harness`는 획득된 pinned 소스 readonly이다. `*.with-source-dependencies.receipt.json`에 합성 설정과 해시, harness manifest 해시, 직접/전이 의존 9개 해시를 기록했다. 테스트의 기대값/원문은 수정하지 않았다.

추가 `review-probes.py`도 같은 격리에서 실행했다. 두 receipt는 다음을 실증한다: (1) 통지 파일 2줄→새 1줄로 잘리면 pinned는 C를 누락하고 observed는 경보 후 C를 재릴레이, (2) 유효 JSON 배열 `[]` 통지는 둘 다 AttributeError, (3) 봉인 구간 개서는 TAMPER지만 신규 `.compacted.synthetic`를 추가하면 RESEAL_REQUIRED, (4) CLI duration nan/inf/음수/0 거부. 프로브 rc 0은 기존 결함 관측의 성공이며 결함이 해결되었다는 뜻이 아니다.

## F01 — .gitignore

목적: 코드만 정본으로 두고 config, state, alerts, safe mode, mutation token, approval_key, console_secret, bytecode를 제외한다. 호출자는 Git이며 실행·runtime 상태 전이는 없다. 키가 Git에 들어가는 문제를 설명하지만 ignore는 접근제어/비밀보관/이미 커밋된 키 제거를 제공하지 않는다. observed `.gitignore`는 수집 범위에 없어 고정본만 검토했다. 채택은 **adapt**: Zeus runtime/auth와 deployment state를 Git 정의에서 분리하고 secret를 agent mount에서 배제한다. 기존 키 복제는 **reject**. 문자열 소스 검토이며 실제 키나 ACL 테스트는 하지 않았다.

## F02 — README.md

guardian의 out-of-band 불가침 core, 별 프로세스 watchdog, 무전진/심박, safe mode operator 해제를 설명한다. operator용 PowerShell 설정/Task Scheduler 예시는 문서로만 읽었고 실행하지 않았다. README의 5분 주기와 watchdog 주석의 10분×9=90분 seed는 일치하지 않아 실제 설정 없이 정책을 복제하면 안 된다. “전체 불가침 core”와 console의 limb 선언도 등급이 다르다. README는 discovery이며 코드가 실제 판정이다. **adapt** 별 수명/권한 책임분리, **reject** 로컬 사용자명·Python313 절대경로·파일 삭제로 승인 해제. observed는 CRLF만 다름.

## F03 — console.py

`main`→`_cfg/_secret`→127.0.0.1 `ThreadingHTTPServer`; GET `/` secret 포함 PAGE, `/board` harness_board subprocess 실행 후 HTML 반환, `/audit` 로그/원장 feed. POST `/act`→JSON parse→secret compare→`_actions` 폐쇄 registry→`_build_argv` 허용 플래그→실행 전 `_audit`→`_run`→결과 audit. token issue/revoke, arm/disarm, mark, watchdog는 mutation으로 표시하지만 조회도 기록한다. shell=False argv는 좋은 경계이나 localhost와 읽을 수 있는 secret는 인간 인증이 아니다(원문도 이를 인정).

`_run`은 timeout=124, OSError=125로 구분하고 UTF-8 replacement decoding을 쓴다. 그러나 timeout 메시지가 “실패 아님”이라고 해서 mutation이 없었다는 뜻은 아니다; 자식이 이미 실행한 side effect와 descendant lifetime은 별도 문제다. `notifier.alert`가 durable log 실패를 삼키므로 “모든 변이 요청 증적이 반드시 남는다”는 보장은 성립하지 않는다. malformed JSON은 400이나 JSON 배열/비dict args의 타입 검증, Content-Length 상한/요청 read deadline, mutation 직렬화·idempotency가 없다. HTTP access logging은 무시하므로 GET 관측은 모두 감사된다는 주장과도 다르다. server bind의 모든 OSError를 이미 실행 중으로 보고 rc0 반환하여 다른 장애도 정상으로 오인할 수 있다. PAGE `put`은 command output을 escape 없이 insertAdjacentHTML에 넣고, `_board_html`은 harness HTML을 같은 origin iframe으로 제공한다. 감시 대상이 생성한 HTML/출력이 secret를 가진 조작 창과 동일한 신뢰영역이다. 공격 성공 HTTP 시나리오는 실행하지 않았으며 이는 코드상의 injection surface 판단이다.

observed 실질 변경: dead enum `pipeline_done/heart_promoted`를 제거하고 heart_change 4종 추가, `_ledger_paths`로 project+canonical 합집합, dedup은 파일경로 기준, 40→80 tail, dict guard, pending/by/sid 표시, ts 정렬, 잘린 전체/종류별 수 표시. 실제 sibling `ledger.EVENT_TYPES`와 대조해 새 4종이 존재함을 확인했다. `_ledger_path`는 observed에서 남지만 feed는 새 함수를 소비한다. 합집합 간 동일 이벤트 중복제거는 없고 raw event type/ts/detail 값 타입 검증은 부분적이다. 날짜를 초 단위 문자열로 잘라 정렬해 timezone/동률 ordering은 강한 순서가 아니다.

**adapt** 등록된 use case만 조작, 감사 시도+결과, 관측 대상의 합집합과 잘린 수 표시. Zeus monitoring read model/SSOT event query에 통합하고 mutation은 application authorization/six-W provenance로 따로 권한 검사한다. **reject** secret GET 배포와 파일 토큰 승인, 원본 HTML 같은-origin 신뢰. cp949 스모크 PASS는 HTTP 기능 검증을 대신하지 않는다.

## F04 — issue_token.py

CLI `main`→`_hours`→`issue` 또는 `revoke/status`; `_f`는 GUARDIAN_HOME/mutation_token.json. issue는 secrets.token_hex(16), issued_at, expires_ts=time+hours를 direct write 후 출력한다. revoke는 파일 삭제, status는 만료 시각 비교한다. CLI는 양의 유한 duration, 기본72h를 요구하지만 direct `issue(hours)`는 이를 재검사하지 않고 status는 malformed JSON/누락 key를 처리하지 않는다. 큰 유한 hours의 곱 overflow, 동시 issue/revoke와 atomic write, 신원/승인 귀속은 별도 방어가 없다. `_utf8_streams`는 encoding을 바꾸지 않고 errors=replace하여 cp949 출력 때문에 “쓰기는 성공했으나 rc1”이 되는 문제를 완화한다. UI hours 기본12와 CLI72도 다르다. observed CRLF만 다름. **adapt** 유효기간·회수·실패와 실행결과 일치, **reject** 공유파일 존재/만료가 Zeus authorization을 대체하는 설계. 스모크와 duration 프로브는 PASS, 운영 토큰은 읽지 않음.

## F05 — ledger_seal.py

`seal`→nonblank normalized lines SHA-256 prefix+lines, compacted sidecars hash→guardian state seal. `verify`는 UNSEALED/OK/TAMPER/RESEAL_REQUIRED를 구분; `restorer.mark`가 seal, `watchdog.run`이 default canonical ledger verify. append-only prefix를 보존하고 원장 외부에 checkpoint를 두는 목적은 유효하다. 바이트가 아니라 빈 줄 제외+개행 정규화한 텍스트를 hash하므로 byte integrity는 아니다. seal 자체 direct write/동시 read는 원자성이 없고 전체 원장/sidecar를 메모리로 읽는다. 신규 sidecar가 있으면 prefix 불일치/축소를 compaction 가능성으로 낮추는데 그 파일의 정당한 compaction 관계는 검증하지 않는다. CLI UNSEALED는 rc0; watchdog는 TAMPER만 소비하고 검증 예외도 무시한다. 추가 프로브에서 신규 sidecar로 TAMPER→RESEAL_REQUIRED 강등을 실증. observed CRLF만 다름. **adapt** 증거 digest/append-only/checkpoint와 판정불능 구분; **reject** PostgreSQL 원장을 파일복원하거나 UNSEALED/RESEAL을 healthy로 간주. 원본 ledger state 재사용 없음.

## F06 — notifier.py

`alert(home,cfg,message)`는 timestamp→alerts.log append 시도→stderr→선택 webhook POST(5s); watchdog·restorer·console가 호출한다. log OSError와 webhook 예외는 stderr만 남기며 반환은 None이다. notifier 독립 표준라이브러리는 운명분리 의도에 맞지만 log 실패에도 caller가 watermark 전진하므로 durable delivery 보장은 아니다. webhook response를 명시적으로 close하지 않고 retry/ack/idempotency가 없다. 전체 메시지 untrusted newline도 raw log에 들어간다. observed CRLF만 다름. **adapt** 감시자 별도 알림·bounded IO·실패도 관측 가능, Zeus PostgreSQL outbox/event-id delivery receipt로 처리한다. **reject** 전송 실패를 성공 watermark로 소거. relay 스모크/복구 스모크는 local log 경로를 검증하며 실제 webhook는 not run(외부 전송 권한 없음·network-none).

## F07 — restorer.py

`mark`→config/python→tracked dirty 검사→tests glob→harness judgment_paths subprocess→각 suite main 실행→이전 known_good 비교→HEAD+증거 저장→best-effort seal→alert. 래칫은 suite 이름집합/출력 단언수 감소, literal True regex 증가, judgment path 집합 감소를 차단한다. `--allow-shrink --why`는 CLI에서만 이유를 강제하고 direct mark API는 생략할 수 있다. caller console는 shrink 플래그를 허용하지 않는다. mark의 git status/rev-parse rc를 확인하지 않고 검사 후 다시 HEAD/tree clean을 결속하지 않아 테스트 중 변경되는 트리와 SHA의 exact revision 결속이 약하다. 스위트 key는 basename이어서 서로 다른 하위디렉터리 동일 이름이 충돌한다. 출력 FAIL을 세지만 returncode가0이면 mark가 실패 단언을 직접 거부하지 않는다. 단언0/vacuous도 최초 anchor에 허용된다. literal True regex는 일반 assertion 약화를 증명하지 못한다. 판정 경로 도출은 감시 대상 script 실행에 의존하므로 import 독립은 권한/검증 독립과 다르다.

`restore`→known_good sha→top-level targets(ledger 제외)→git checkout→known_good 이후 HEAD에 추가된 tracked file 제거→alerts→append_restore subprocess best effort. 원장은 되감지 않지만 현재 작업 트리/index를 넓게 바꾸는 행위이다. ls-tree stdout `.split()`은 공백있는 경로 처리에 약하고, Git rc 누락, staging/new uncommitted path 분류, 삭제 실패 뒤 rc0, 감사 subprocess timeout/unicode 실패가 이미 복원된 뒤 예외로 나오는 문제를 가진다. 기본 주석보다 실제 자동 trigger는 watchdog seal 파손만이다. 봉인 파손 증거는 원장 손상이며 그것이 코드 트리 전체 손상의 증거는 아니다; fixture 테스트 성공도 이 인과를 증명하지 않는다.

observed CRLF만 다름. **adapt** 검증된 이전 버전만 선택, 독립 incumbent tests, anchor 약화 추적, 원장 전진, bounded recovery, mutation 전후 감사. **reject** host worktree checkout/unlink 복원과 basename assertion count를 강한 canary 인증으로 사용. Zeus는 `ReleaseRunner`의 image digest·candidate tree·incumbent tests, `Releases`의 compare-and-set 이전 deployment pointer를 유지해야 한다. 스모크가 전량 PASS해도 mark TOCTOU/동시성/경로 edge case 증명은 없으며 추가 회귀가 필요하다.

## F08 — tests/test_console_encoding_smoke.py

독립 실행 main, subprocess에 cp949 강제와 무가드 음성 대조군, 임시 GUARDIAN_HOME issue/status/invalid hours·restorer early rejection, decode 한국어, AST print stdout/stderr 분리, guard 정의+호출, 금지 import 집합 대조를 수행한다. AST `_has_guard`는 제어흐름상 항상 reachable인지까지 증명하지 않는다. 이 테스트의 이름에 console가 있어도 console HTTP를 기동하지 않는다. 임시 token만 생성/삭제한다. observed CRLF만 다름. 양 variant PASS. **adapt** negative control, 변경을 재는 test 입력, 실제 rc·인코딩 pair 검증; 전체 integration coverage로 확대 주장하지 않음.

## F09 — tests/test_notify_relay_smoke.py

임시 harness/guardian config, importlib.reload로 환경 binding 갱신, 비장전에서도 run 릴레이, 같은 파일 무중복, 추가 행 증분을 확인한다. probe_hook_chain은 fixture에 존재하지 않아 실제 stderr에 실패 경보가 남아도 run rc0이다. 이는 실 설치 훅 검증 PASS가 아니다. watermark cap·truncate·replacement·malformed schema·disk/webhook 장애는 스모크에 없으며 추가 리뷰 프로브가 truncate/scalar를 보완했다. observed CRLF만 다름. 양 variant PASS. **adapt** append/event delivery 회귀와 손상 입력 확장.

## F10 — tests/test_recovery_smoke.py

tmp Git good+corrupted commit을 만들고 임시 seal tamper로 watchdog→restorer를 실호출한다. 신규 evil file 제거, 원장 후속행 보존, 사건당1회 cap, 3회 safe, operator 삭제 감지+카운터리셋, missing known-good 즉시 safe를 확인한다. 원본 운영 호출은 없다. 본 fixture에는 python_exe/append_restore가 없어 audit append는 경보로 skip하며 별도 restorer suite가 감사 경로를 재어준다. observed CRLF만 다름. 양 variant PASS. **adapt** mutation recovery의 부정/긍정 시나리오; 코드전체 복원의 정책 정당성을 이 테스트에서 추론하지 않는다.

## F11 — tests/test_restorer_smoke.py

tmp repo와 별 guardian fixture를 생성하고 pinned sibling paths.yaml/judgment_paths/hook_protocol을 복사한다. synthetic pipeline·registry가 정확히 역할집합 하나를 줄이는 fixture와 되돌리면 PASS인 대조군을 갖는다. known_good가 없는 restore 거부, clean mark, dirty/test-fail 거부, path shrink와 anchor 보존, restore+ledger 보존+append+alert, regex declaration 일치를 확인한다. 끝에서 source ROOT/config.json을 직접 읽는 숨은 환경 의존이 있다. 필요한 config를 합성하고 9개 dependency를 사전 검토해 PASS했다. 의존성 `append_restore→ledger→ids/atomic_jsonl/paths`, stamp→hook_protocol은 fixture의 HARNESS_HOME 아래에 append한다; ledger.compact의 deferred import들은 이 실행 경로에서 호출되지 않는다. 본 검토는 이 dependency closure만 다루고 harness 전수 coverage를 대신하지 않는다. observed CRLF만 다름. **adapt** 진단 출력, gate-only perturbation과 positive control, source-bound fixture; **reject** 배포머신 config가 있어야 테스트 가능한 습관.

## F12 — tests/test_watchdog_smoke.py

임시 config/state/ledger로 비장전/협업→정상, active lease+자기 PID+stale heartbeat→연속 fire, fresh heartbeat→reset, channel 삭제→safe, no lease+continue→progress fire를 구성한다. 1.2s sleep으로 1s threshold를 넘긴다. subprocess timeout30. Linux tasklist 예외가 alive=True라 fixture 목적의 Windows pid 확인 자체는 대체되지 않는다. grace/circuit corruption·watchdog concurrent runs·safe mode 실제 downstream 차단·fresh heartbeat but stuck work는 이 suite에서 재지 않는다. observed CRLF만 다름. 양 variant PASS. **adapt** 기대작업 유무와 건강/정체 입력의 구분을 명시한 시나리오.

## F13 — watchdog.py

외부 scheduler one-shot `run`: cfg/default load→notification relay→synthetic guard_boot deny probe(armed 무관)→active_run unattended 여부→operator safe clear 처리→spawn grace→lease/PID/heartbeat→driver marker→circuit trips→material event progress→seal verify→fire counter/복원 cap/safe 선언→state atomic replace. 건강이면 live_fails/incident_restores reset. 진척은 active session 없고 driver outcome continue이며 last event id 동일할 때만 누적하므로 정상 장기턴·유휴를 구분하려는 진화가 코드에 반영되어 있다. 복원은 seal: trigger만. safe_mode_after에 먼저 도달하면 복원 없이 safe다.

실제 보장 한계: config harness_home 부재는 rc0, 손상 JSON은 기본값인데 JSON list/nonmapping·타입 불일치는 예외, loop run marker 부재는 경보 아님, circuit 손상·seal 예외는 무시, probe 예외는 stderr fail-open이다. grace는 mutable mtime으로 전체 health를 조기에 유예하고 피감시 시스템이 갱신 가능하다. PID는 tasklist stdout substring이며 birth-time 검증이 없고 판별 예외를 True로 바꾼다. last event id만 바뀌면 진척으로 읽을 수 있어 실제 task completion 진척과 다르다. 동일 `.tmp` 파일명은 동시 one-shot 간 충돌 가능하고 watchdog 전체 lock은 없다. safe file 직접 write·exists 검사도 경쟁한다. safe mode가 내려진 상태에서 healthy rc0가 될 수 있으므로 rc0를 “safe mode 해제됨”으로 해석하면 안 된다.

observed는 relay prefix SHA-1 chain을 추가하여 잘림/교체 경보 후 watermark0 재설정·재릴레이, 빈 파일이면 chain 제거를 저장한다. initial legacy watermark에는 chain이 없어 이전 내용 교체를 즉시 잡지 못하는 이행 gap이 있다. chain은 비키드이며 같은 계정·쓰기 가능한 checkpoint 공격을 막는 인증이 아니라고 원문도 명시한다. truncation 개선은 추가 프로브로 검증했다. full-file read와 prefix rehash O(n), cap10, JSON 배열 AttributeError, notifier 실패 뒤 watermark 전진은 유지된다.

**adapt** liveness/material-progress/observation-error 분리, idle/active lease grace, 사건별 recovery cap와 durable circuit escalation, notifier pipeline 건전성. **reject** heartbeat 없음/원장 변동/CLI 시작을 하나의 “건강”으로 축약, 판별불능을 안전 확인으로 바꾸기, 봉인파손→host-tree복원. Zeus에 외부 감독자의 생존 감시는 별도 OS service boundary로 설계해야 하며 자기 프로세스의 `tick`만으로 supervisor 자체 사망을 감지한다고 주장할 수 없다.

## Zeus 대응과 흡수 제안

| guardian 기제 | 현재 Zeus 경로·상태 | 결정 및 필요한 독립 확인 |
|---|---|---|
| 외부 supervisor / wake | `supervisor.py:tick/main`, Docker compose infra readiness, queued/pending task+lease, Redis backlog, FileLock singleton | **adapt** existing task-aware wake 유지. 프로세스 생존+작업 기대+실질 결과의 독립 health records 추가가 후보. task queue가 있는 정상 lease waiting과 stuck work를 분리. OS service/task scheduler의 실제 supervisor restart는 별도 운영 검증 필요. |
| known-good / rollback | `adapters/deployment.py:ReleaseRunner._run/_promote/monitor/_probe_status`, `application/releases.py:verify/promote/rollback` | **retain/adapt** exact image digest+tree/기존 tests+candidate tests+실 CLI canary+CAS 이전 deployment. source checkout 복원은 거절. 첫 deployment에 rollback target 없음도 unhealthy로 명시하는 현재 분리를 유지. |
| 관측 불능과 실행 실패 | `ReleaseRunner._check/_probe_status/monitor`, `tests/test_release_health.py` | 현재 unknown은 failure counter 증가/rollback을 하지 않고 executed failure만 임계치 후 rollback. Guardian의 무시/FalseHealthy보다 강한 의미를 유지. `codex --version`만 건강하게 실행되어도 작업진척 증명은 없으므로 별 dimension 추가. |
| 실패 격리와 queue 생존 | `supervisor.py:maintain_views/refresh_embeddings`, `tests/test_supervisor.py` | graph/embedding/cleanup 실패를 health에 보존하고 authoritative queue와 분리하는 현재 구조 유지. notifier 실패도 같은 원칙으로 처리하되 delivery ack는 별도로 남김. |
| 통지 tamper / 감사 시각화 | guardian observed relay and console; Zeus outbox/runtime events/monitoring adapters | **adapt** event ID based durable delivery, provenance, observer error, truncated count 표시. PostgreSQL SSOT를 JSONL watermark/파일별 합집합으로 복제하지 않음. six-W envelope에 actor/task/source revision/observation/evidence를 결속. |
| safety core / mutation token | guardian README/.gitignore/issue_token/console | **adapt** supervisor와 agent 권한 분리, closed use-case routing; **reject** 원본 token/key, inherited operator approvals, shared readable secret로 human auth 대체. Zeus 새 승인 계약과 독립 CLI 리뷰를 거쳐야 함. |

`tests/test_release_health.py`, `tests/test_supervisor.py`는 이 검토에서 위치/선언 매핑 자료이며 Zeus 테스트를 이번 guardian 실행으로 통과시켰다고 주장하지 않는다. 구현 변경과 그 검증은 주 Codex가 수행한다. 온톨로지/토폴로지에 supervisor process, active image, release, task lease, health observation, notification delivery, recovery incident를 구분해 model할 것을 제안한다. GraphRAG는 이 원문·receipt의 derived index이고 승인 근거 원본을 대체하지 않는다.

## 종결 상태와 남은 승인

13/13 파일의 의미 검토와 원래 5개 스모크 pinned/observed 실행은 끝났다. 미검토 tracked path 없음. 코드 수정/원본 운영 조작/권한 이전은 없음. 네트워크 webhook, Windows tasklist 성공, 실제 scheduled watchdog/console HTTP/실제 downstream safe_mode 강제, mark concurrency와 TOCTOU, console hostile HTML 등은 운영 또는 신규 회귀 영역으로 **not run**이며 전반적 무결함/실 운영 안전성을 주장하지 않는다.

도입 후보는 별 actor 연구 lead와 conductor가 이 고정 source+Zeus revision+receipt를 독립 확인해야 한다. 실제 Claude와 주 Codex의 의견 결합, Zeus 구현, exact-revision tests, actual Codex CLI canary, promotion/rollback 검증이 아직 이 문서만으로 충족되지 않는다. 따라서 상태는 **source_semantic_review_complete / upstream_suites_executed / adoption_not_approved / not_incorporated**이다.
