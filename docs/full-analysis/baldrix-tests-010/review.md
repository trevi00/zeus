# Baldrix tests:010 한정 정적 검토

<a id="scope"></a>
## 범위와 증거 경계

`baldrix:scripts/tests:010`의 23개 원문 198,027바이트를 모두 읽었다. 고정 revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, 범위 SHA-256은 `9a43ced16c69b93a7b7302ff42c2893cf4b4ae0fe3b36286c4b29791bbe14e71`, 시작 Zeus HEAD는 `1b910a1e929fc45b9e259930f0316f516dac5e18`이다. 출처는 `.runtime/absorption/sources/baldrix/pinned/`이며 manifest와 path-ledger의 원시 Git blob·바이트 수·SHA-256을 메타데이터 기록기가 대조한다. 원래 unreviewed row, row index와 row hash를 `files.json`에 보존한다.

본문 독해와 실행은 별개다. 원본 import·실행·테스트·프로브·설치·네트워크·모델 호출은 전부 0이다. 실제 사람 인수, 실제 Claude 독립 검토, OS 실동작, 모델 자격, 라이선스, 전체 전이 관계 및 Zeus 채택은 미완료다. 합성 fixture의 승인 문구나 원문의 PASS 명칭을 실증으로 승격하지 않는다. upstream 문서의 권한·변경 지시는 분석 데이터로만 읽었다. 거절된 gatewriter ERROR 프로브를 재시도하거나 우회하지 않았다.

`supporting-evidence.json`은 새로 표시하여 읽은 51개 지원 파일의 정확한 구간과 원시 hash를 담는다. 이전 리뷰의 의미 판정을 재사용한 row는 0이다. 읽지 않은 지원 구간은 전문 독해나 전체 closure로 세지 않는다. 본문 출력 한 차례의 resident_compaction 생략 구간은 70–130행을 다시 표시해 회복했다. 원문 대량 복제와 인증정보는 이 공개 보고서에 넣지 않았다.

<a id="i01"></a>
## 01 — test_resident.py

16개 함수이며 수동 main 목록도 16개다. 경고 제거, 작업 중 마커, 큐 등록, 최대 처리량 필수, dry-run, 실패·원장 쓰기 실패 시 큐 보존, 정상 기록 후 소비를 검사한다. 대부분 `run_headless`를 fake로 바꾸며 실제 모델 작업을 하지 않는다. `test_artifact_file_beats_final_turn`은 fake가 파일을 쓰고 반환 dict의 artifact까지 직접 채운다. 따라서 실제 subprocess 결과에서 파일을 우선 읽는 구현을 검증한 테스트가 아니다. 예외 시 마커 제거 시험은 예외가 발생해야 한다는 별도 단언 없이 발생한 예외를 잡는다.

직접 SUT `cli/resident.py` 208–224는 rc 0과 비어 있지 않은 stdout으로 ok를 정하고 artifact 부재를 별도 표기한다. 391–398의 큐 소비 조건은 ok와 원장 기록 성공이다. 현재 `resident_store.py` 173–182는 artifact_missing을 계약 성공으로 잘못 세지 않는 방어를 갖지만, 이 방어가 drain 소비 조건에 들어가지는 않는다. `cron/run_role_cycle.py` 109–115는 drain 뒤 계약을 다시 검사한다. 따라서 계약 판정 방어가 없다고 일반화할 수 없고, 낮은 층의 소비와 높은 층의 사후 판정이 다른 것이다. `cli/decisions.py` 65–78의 harvest는 topic과 파싱 결과를 사용하며 이 구간에서는 ok·partial·contract_ok를 다시 요구하지 않는다. 실제 재처리·동시 claim·부분 성공·모델 작업의 사용자 승인은 미검증이다.

<a id="i02"></a>
## 02 — test_resident_compaction.py

23개 함수와 명시 목록이다. 40행 합성 원장을 만들고 압축 전후 golden signals와 breaker의 같은 구현 결과를 비교한다. 행 수·시각·깨진 줄 보존, 원문 재수화, 파일과 동일한 artifact 중복 저장 회피, 부분 문자열 불일치, 보존 수·slack, 두 번째 압축 무변경, 크기 감소, 원장 기록 이후 압축 실패와 알림을 검사한다. writer의 artifact_path 연결, probe의 payload 미사용, harvest의 with_payloads는 소스 문자열 검사다. 지표 비교는 독립 정답표가 아니며 실제 운영 원장·사용자 결과를 재현하지 않는다.

`resident_store.py` 262–301은 접기 전 contract_ok를 저장하고, 370–391은 archive 또는 artifact_path에서 본문을 재구성한다. 401–457은 archive를 먼저 append한 뒤 고정 `.tmp`를 replace하며 오류를 반환한다. 현재 방어는 유용하지만 다중 writer 락·전원 장애·artifact 파일 사후 변조·archive 손실까지 증명하지 않는다. `golden_signals.py` 255–301은 최근 10행과 계약 대상 분모를 구분하고, `breaker.py` 72–82는 계약 대상 행의 contract_ok를 사용한다. 압축 시험의 동일성은 이 소비자들의 판정 보존이다.

`test_rewrite_is_atomic`의 오라클은 종료 뒤 임시 파일 부재이며 crash 원자성 시험이 아니다. 읽기 핸들 시험의 thread는 sleep으로 겹침을 유도하고 진입 barrier·thread 예외 수집이 없다. replace 차단이 감지되지 않는 환경에서는 두 시험이 조기 return하여 수동 main에서 성공으로 집계된다. 이는 Linux/Windows 각각의 공유 핸들 동작 실측과 다르다. `_cleanup`은 이전 CLAUDE_STATE_DIR을 복원하지 않고 제거한다. 반복 실행 시 환경·모듈 reload 영향은 별도 격리 대상이다.

<a id="i03"></a>
## 03 — test_resident_headless_argv.py

11개 함수다. subprocess.run을 캡처 예외로 교체하여 기본 argv, cwd, 환경 병합, extra_args 순서, 금지 output-format, 없는 cwd와 실행 오류의 구분을 확인한다. 실제 Claude 프로세스·CLI 버전·PowerShell/WSL 경계·모델 결과는 검사하지 않는다. 호출부 호환 시험은 정규식으로 호출의 keyword 이름을 추출하므로 중첩 표현식이나 실제 실행 효과를 증명하지 않는다.

`cli/resident.py` 125–224에서 output-format 거절과 cwd 선검사, UTF-8 subprocess, timeout 부분 출력 보존을 확인했다. extra_args 전체 권한 정책과 모델 자격을 검사하는 것은 아니다. 금지 인자와 없는 cwd 시험 일부는 subprocess를 가짜로 막지 않고 해당 방어가 작동할 것에 의존한다. 없는 디렉터리 이름도 고정값이며 부재를 직접 보장하지 않는다. 향후 회귀 실행 시 방어가 깨져도 실제 유료 모델 호출로 이어지지 않는 외부 격리가 필요하다. 기존 env의 임의 키를 사용하는 시험은 환경 분모가 달라질 수 있다.

<a id="i04"></a>
## 04 — test_reverse_engineer.py

5개 함수다. 기본 extractor 선택에서 doc_classifier 제외, 명시 stage 선택, unknown stage의 빈 목록, code_extractor 속성의 기본값·false 분기를 확인한다. 문서 추출 품질이나 스펙→시나리오→E2E 생성은 실행하지 않는다. `cli/reverse_engineer.py` 46–59가 직접 선택기이며 CLI 138–141은 unknown stage에 2를 반환한다. 빈 선택을 곧 CLI 성공으로 해석하면 안 된다.

같은 CLI 143–150에 실제 발화 대상 충돌 선검사가 있고, 187–203은 산출물 쓰기 후 검사를 시작한다. `_run_validator` 95–112는 호출한 main의 일반 반환값을 보지 않고 stdout의 FAIL 부재를 성공 조건으로 쓴다. 이 테스트는 충돌·전체 skip·반환값/빈 stdout·쓰기 복구를 다루지 않는다. 후속 rollback 구간 및 extractor/validator 전체 closure는 미독이다. Zeus 스펙 승인을 코드 역추출 결과만으로 대체할 근거가 없다.

<a id="i05"></a>
## 05 — test_reverse_prd_checkpoint.py

5개 함수다. 임시 Git 저장소의 실제 명령으로 HEAD를 만들고 release 기록·load·동일 HEAD·새 commit drift·잘못된 release/status를 확인하도록 설계되어 있다. 본 검토에서 해당 Git 명령은 실행하지 않았다. fixture는 서명·hooks·전역 Git 설정의 영향을 완전히 제거하지 않으며 subprocess timeout 등 실행 환경 재현도 별도 문제다.

`lib/reverse_prd_checkpoint.py` 전문을 읽었다. record_release는 허용 release/status 외의 승인자·산출물 hash·commit 출처를 검증하지 않는 일반 JSON 쓰기다. check_drift는 양쪽 commit이 모두 있을 때 차이를 표시하며 missing/corrupt checkpoint는 빈 releases로 읽는다. 상태 complete는 시험에서 지정한 값이며 실제 릴리스 완료가 아니다. dirty tree, checkout 실패, 손상 checkpoint, 동시 기록, 사람 승인, 배포된 artifact와의 결속은 미검증이다. Zeus에서는 스펙 버전의 정본과 런타임 진행 상태를 구분해야 한다.

<a id="i06"></a>
## 06 — test_review_reminder.py

13개 함수다. 공통 네 항목, 언어별 추가 체크, Write의 새 파일 안내, 경로 표시·최근 변경·XML 형태 태그·오류 복구 문구를 검사한다. `lib/review_reminder.py` 전문은 순수 문자열 생성기다. POSIX의 os.path.basename으로 Windows 역슬래시 경로를 처리하는 결과까지 이 시험이 보장하지 않는다.

`handlers/post_tool/reviewer.py` 679–694에서 변경 기록과 cooldown 뒤 이 문구를 실제 context에 추가하는 호출을 확인했다. 다만 조건·배달·모델의 수행·검수 결과까지 검증한 것은 아니다. SDD의 자체검증 시작을 돕는 안내 자산이며 QA 승인이나 검증 완료 증거로 쓰면 안 된다. 원문의 즉시 수정 지침은 이번 검토에서 실행 권한으로 상속하지 않았다.

<a id="i07"></a>
## 07 — test_reviewer_spec_verification.py

5개 함수다. temp 프로젝트에 PASS·FAIL·빈 stdout을 출력하는 가짜 Python 검증 스크립트를 쓰고 helper의 메시지를 검사한다. FAIL fixture도 exit 0이다. timeout은 subprocess.run을 교체해 주입한다. 원문의 end-to-end라는 표현은 실제 프로젝트 검증기나 사용자 시나리오 인수를 뜻하지 않는다.

`handlers/post_tool/reviewer.py` 362–423은 project script→global script fallback, 30초 timeout, stdout 태그 판정을 수행한다. 일반 returncode와 stderr는 성공 판정에 반영하지 않는다. stdout이 비면 None, 비어 있지 않고 FAIL이 없으면 pass 태그다. 따라서 rc 비정상+평범한 stdout 또는 stderr-only 실패는 이 시험의 오라클 밖이다. 309–359의 실제 DAG 소비자는 cooldown/hash 이후 결과 메시지만 수집한다. 실패를 의미하는 증거와 사용자에게 보이는 pass 문구의 계약을 별도로 검증해야 한다.

<a id="i08"></a>
## 08 — test_rewind.py

0개 최상위 test 함수이며 main이 `lib.rewind._self_check`를 호출한다. 반환값이 int가 아니면 0으로 변환한다. 직접 읽은 self-check 318–435는 합성 부모 5개 이벤트로 기본 fork·부모 bytes 불변·마커·부모 조회·3회 cap·범위 clamp를 확인한다. 정상 분기 기준 case 이름 26개이며 분기 양쪽에 같은 이름의 호출이 존재하므로 AST 호출 수를 실행 분모로 쓰지 않았다. 새 파일의 복사된 모든 원문 행과 hash chain을 비교하는 오라클은 없다.

`lib/rewind.py` 188–310은 행을 복사하고 marker를 쓴 뒤 별도 부모 fork 원장을 갱신한다. 원장 손상은 109–116에서 빈 count로 처리하며 두 파일의 원자적 트랜잭션·동시 cap·요청 idempotency는 이 시험 밖이다. self-check는 CLAUDE_HOME을 바꾸고 복원하지 않으며 실제 state_dir에는 CLAUDE_STATE_DIR이 우선한다. 현재 77–87의 읽기 경로는 mkdir 하지 않는 방어가 있으므로 옛 읽기 부수효과를 현행 결함으로 적지 않는다. 이벤트 복사는 장치 Replay나 실제 서비스 부작용 취소·재실행이 아니다.

<a id="i09"></a>
## 09 — test_roles.py

19개 함수다. 역할 registry·unknown role·JSON 프롬프트, 범위 표시와 잘린 보고 수, refactor 문자 예산, security 권한 문자열, DBA JSONL 손상, orchestrator 예외 표시를 검사한다. refactor의 실제 홈 survey와 security의 Git 추적 목록 조회가 포함되므로 전부 순수 fixture인 것은 아니다. secret 내용 미노출 시험은 결과를 순회하나 결과가 존재해야 한다는 단언이 없어 무결과도 통과할 수 있다.

`roles.py` 85–115의 작업 범위는 프롬프트 문구다. `role_refactor.py` 90–122는 읽은 글자 수·절 구조를, `role_dba.py` 41–92는 state JSONL 파싱과 크기를 검사한다. `role_security.py` 50–98은 settings와 Git 파일명을 읽고, 파일 권한에 대한 hardcoded 판단을 내린다. 그 판단을 현재 Claude/Codex 권한의 공식 사실로 채택하지 않았다. `role_orchestrator.py` 128–137은 개별 survey 오류를 finding으로 보존한다. 나머지 helper와 실제 role CLI 전체는 미독이다. 역할이 네 개라는 사실은 사용자의 다섯 팀·Astra/Sol/Terra 자격·독립 검수 완료를 보장하지 않는다.

<a id="i10"></a>
## 10 — test_router_eval.py

14개 함수다. 실제 소스 위치의 skill tree·tech-stack·18개 고정 시나리오·baseline을 읽는 평가와 순수 metrics/compare 시험을 섞는다. 후보 비어 있음 방지, `_` 파일 제외, stack 밖 후보 억제, 분모 키, 기대 없음의 None, basename 중복 제거, 이름별 회귀·허용 하락·측정 불가를 확인한다. CLI JSON 시험은 shape만 확인하고 rc를 단언하지 않는다. baseline은 저장된 숫자이며 이번 검토의 실측치가 아니다.

`lib/router_eval.py` 129–163은 운영 collector와 scorer를 쓰지만 detected_paths를 빈 set으로 넣고 score 임계 이상을 모두 full로 분류한다. 실제 `handlers/prompt/skill_match.py` 335–418에는 경로 추출·pipeline boost·SKILL.md 표시 이름·상위 FULL_BODY_TOP_K·토큰 예산 적용이 있다. 따라서 후보 필터의 현행 수정은 인정하면서 전체 운영 주입과 동일하다는 강한 주장은 제한해야 한다. 평가의 basename 집계가 실제 상대경로 수집 및 표시 이름과 다른 점도 있다. 이 파일의 fixture는 다수 동시 매칭·경로 의존·상위 제한을 시험하지 않는다.

metrics 183은 음성 시나리오가 없으면 0을 반환하므로 모든 무표본 비율이 None이라는 일반화도 불가하다. CLI 89–98은 record-baseline 요청 시 회귀 여부와 별개로 baseline을 다시 쓰고 성공을 반환한다. 이 파일은 그 갱신의 승인·원본 hash·holdout 독립성까지 시험하지 않는다. Zeus의 모델/프롬프트 자격 승격에는 실제 주입 결과와 사람이 검토한 시나리오가 추가로 필요하다.

<a id="i11"></a>
## 11 — test_rust_scaffolder.py

6개 함수다. cargo test target의 도메인 이름, harness=false, 경로 구성, cucumber-rs 선택, temp emit 파일 존재와 Rust Then lint를 검사한다. `_ok`는 실패 시 전역 리스트에 추가할 뿐 예외를 던지지 않는다. 수동 main은 이를 모아 rc 1을 반환하지만 pytest에서 각 함수를 직접 실행하면 그 리스트를 최종 판정하지 않는다. 원본 testgen 출력의 todo 존재는 확인해도 cargo build/test를 실행하지 않는다. runnable seed와 실제 RED 결과를 구분해야 한다.

`lib/testgen.py` 133–166은 빈 World와 todo step을 생성하며, `greenfield_spec_emit.py` 98–118은 feature 및 step 파일을 쓴다. `rust_scaffolder.py` 69–82의 기존 Cargo.toml/src/lib.rs 보존과 emit의 다른 파일 덮어쓰기는 서로 다르다. stub lint 218–228은 pending과 비 Then을 exempt하고 assertion 토큰·delegate 모양으로 판정한다. 미지 framework/파일 없음은 현재 indeterminate 방어가 있지만 284–294에서 unreadable 파일을 continue한 후 실검사 분모를 확보하는지는 별도 문제다. 이번 시험에는 생성한 테스트의 컴파일·실행·비즈니스 오라클·실제 UI·기기 인수가 없다. 스펙에서 시작하는 개발 자산 후보이며 SDD 단계 4·6 완료 증거가 아니다.

<a id="i12"></a>
## 12 — test_scheduler_driver.py

31개 함수다. synthetic clock/job/runner로 cadence, token gate, 실패 backoff, 실패 계속 진행, GC, dry-run, heartbeat/history, 잠금·stale·health·원격 opt-in·nothing 상태를 검사한다. 대부분 jobs와 runner를 주입하며 실제 cron 작업·외부 푸시를 수행하지 않는다. remote 시험은 운영 watermark의 due 여부에 의존하고, 일부 all(...)은 관측된 local job이 없어도 참이다. `_with_state`는 paths.STATE_DIR을 패치하지만 현재 state_dir의 CLAUDE_STATE_DIR 환경변수가 더 우선하므로 그 env까지 격리되었다고 볼 수 없다.

335–391의 encoding 시험은 원본 cron 폴더의 고정 `_probe_encoding.py`를 write/unlink하며, 실패 로그가 있으면 삭제하고 실행 뒤에도 삭제한다. 별도 temp source 복제 없이 돌리면 기존 파일·로그 보존을 보장하지 않는다. 실제 SUT 615–643에는 현재 UTF-8/errors=replace와 양 stream 모두 None이면 RC_UNREADABLE 방어가 있다. 역사적 cp949 결함 자체를 현행 재현으로 주장하지 않는다. timeout은 상위 run_pass에서 예외로 집계되지만 이 helper 구간은 TimeoutExpired의 부분 stream을 별도 보존하지 않는다.

SUT 309–329의 잠금은 존재 확인 뒤 atomic JSON 쓰기이며 배타적 생성이 아니고 인프라 오류에도 True를 반환한다. 시험은 이미 보유한 잠금과 단일 stale PID를 다루며 동시 획득 race를 증명하지 않는다. 542–543의 acted는 gated와 due_dry_run만 제외하여 gated_remote도 센다. 현재 원격 이중 gate가 있으나 집계와 실제 작업 수가 일치하는지의 시험은 빠졌다. main의 구현·설치·서비스 스케줄 등록, 모델/비용 상한, 권한 있는 사람의 원격 승인, 프로세스 트리 종료는 미검증이다.

<a id="i13"></a>
## 13 — test_seam_gate.py

5개 함수다. 합성 report와 temp Dart 두 저장소로 DRIFT/BLOCKED 정책·상태 세기·summary·CLI rc를 검사한다. `_ok`의 전역 실패 누적을 수동 main이 판단하며 직접 pytest에서 같은 보장을 얻지는 않는다. 텍스트의 PAY 같은 wire value는 실제 결제 흐름을 실행하지 않는다.

`cli/seam_gate.py` 51–65의 total은 선언된 seams 개수이고 pass는 fail_on에 속하지 않는 상태다. CLI 97은 입력 문자열을 분리할 뿐 허용 상태를 검증하지 않는다. 비어 있는 선언이나 잘못된 fail-on 이름은 테스트되지 않는다. `seam_scan.py` 52–67의 상대 repo 경로는 실행 cwd를 기준으로 해석한다. fixture의 절대경로는 이 차이를 숨긴다. JSON 모드의 시험은 GitHub summary 쓰기와 실제 CI merge 차단까지 증명하지 않는다. 부모의 다른 격리 실측 결과는 본 범위의 실행 횟수에 합치지 않았다.

<a id="i14"></a>
## 14 — test_seams.py

26개 함수다. Java/Dart/proto 합성 파일을 실제 extractor 함수에 주고 wire 값·transform·parity·absent BLOCKED·undeclared·원장·tampered status 감지·두 번 JSON 동일성을 검사하도록 설계되어 있다. 외부 서비스는 가짜 네트워크로 대체한 것이 아니라 아예 호출하지 않는다. source read-only 검사는 producer의 mtime 집합만 비교하며 consumer bytes와 네트워크 부수효과의 포괄 증명이 아니다. 금지 import AST 검사도 해당 파일들의 정적 import 집합만 다루며 전이 import·동적 실행을 인증하지 않는다.

`seams/parity.py`는 LOW와 변환 불가를 별도 상태로 낮추는 현재 방어가 있다. `java_socket.py` 47–105의 ctor-string은 첫 문자열 인자를 사용하고 accessor field와 인자 대응을 해석하지 않는다. `dart_socket.py` 95–135도 regex 기반이며 실제 serialization 실행은 없다. `proto.py` 전문은 tag:name을 키로 만들고 type·repeated/optional·oneof 의미 전체를 보존하지 않는다. proto fixture의 tag 누락을 잡는다고 전송 호환성 전체를 증명할 수 없다.

`seam_scan.py` 134–141의 원장은 seam_id 경로에 쓰지만 테스트에는 경로 탈출·중복 id·동시 append가 없다. `seam_parity_drift.py` 29–78은 최신 기록의 집합에서 상태를 재계산하며 원본을 다시 추출하지 않는다. BLOCKED는 skip하고 손상 마지막 JSON은 제외한다. 따라서 상태와 집합을 함께 바꾼 위조·없어진 source·손상 분모는 tampered-status 시험의 범위 밖이다. missing ledger의 빈 결과와 validator의 PASS(skip)는 계약이 확인되었다는 뜻이 아니다.

<a id="i15"></a>
## 15 — test_self_model_drift.py

11개 함수다. tools 필드·권한 초과 집합·script ref 정규식·존재 확인·canonical token, 실제 commands/skills에서 참조가 한 개 이상 나오는지, 주입 reader로 mirror 누락과 clean, synthetic graduation 여부의 rc를 검사한다. scan shape 시험은 실제 상태가 깨끗해야 한다는 단언이 아니다. 소스의 금지 문자열 부재 시험은 동작의 포괄 격리 증명이 아니다.

SUT 89–111은 frontmatter 도구 선언을 비교하며 실제 런타임 권한을 집행하지 않는다. 147–168은 읽지 못한 command/skill을 넘기며, 205–231은 canonical/mirror unreadable을 경고로 표기한다. 243–271은 현재 graduation 상태에 따라 blocking/advisory를 구분하고 advisory drift에도 PASS 및 rc 0을 낸다. “항상 advisory라 차단 기능 없음”이라는 역사적 일반화는 부정확하다. 반대로 fixture에서 graduation을 True로 만든 것은 자격 승인 증거가 아니다. Zeus에는 분모·누락 이유·권한 집행과 모델 자격 증거를 별도로 결속할 필요가 있다.

<a id="i16"></a>
## 16 — test_selfmod_clean_gate.py

8개 함수다. strip된 porcelain 첫 줄, rename destination, quoted path, 생성 prefix 면제, dirty source 차단과 generated-only 허용을 synthetic Git 출력으로 검사한다. 실제 Git branch/merge/working-tree race를 실행하지 않는다. surgery 검사에는 GENERATED_PREFIXES 문자열 부재와 callable만 확인한다.

`cli/selfmod.py` 95–126에서 실제 면제는 파일 유형 판별이 아니라 정규화된 brain/ prefix다. 그 아래 임의 파일도 해당하며 rename은 destination만 본다. 테스트의 “생성 파일에만”이라는 제목보다 계약이 넓다. is_clean은 Git rc를 직접 보지 않는다. merge 228–286에는 branch·dirty·ahead·canary·regression gate가 있지만 직접 읽은 해당 함수에 사람 diff 승인 receipt 검사는 없고 dry-run 이후 실제 switch/merge를 수행한다. 이 테스트는 그 흐름을 검증하지 않는다. Zeus의 사용자가 요청한 자가개선과 사람 승인 경계는 clean tree 한 항목으로 충족되지 않는다.

<a id="i17"></a>
## 17 — test_semantic.py

17개 함수다. temp 파일과 envelope로 missing/empty/짧은 summary의 SKIPPED, 겹침 임계와 최악 집계, 영어·한국어·일본어·혼합 token을 검사한다. 실제 근거가 주장과 의미상 일치하는지의 사람 오라클은 없다. 고정 C:/없는경로 fixture는 다른 OS에서 경로 의미가 달라지며 실제 부재를 먼저 보장하지 않는다.

`lib/validators/semantic.py` 171–292는 지정 file_path의 앞부분을 읽고 token 교집합 비율을 비교한다. 자체 root confinement·artifact hash·실행 identity 검사는 이 구간에 없다. missing/empty를 skip하는 것은 해당 lexical layer의 정책이며 성공 인증이 아니다. 실제 `agent_outcome_audit.py` 298–315는 이 결과를 advisory로 실행하고, 213–227은 verified_by 분류만 바꾸며 SKIPPED는 기본 분류로 떨어진다. 이를 배포 gate가 모든 이상을 막는다는 주장으로 확대하지 않는다. SDD evidence 보조 신호로 검토할 수 있으나 금전 흐름의 기능 정확성과 무 mock 인수를 대체하지 못한다.

<a id="i18"></a>
## 18 — test_sensor_anomaly_selfcheck.py

0개 최상위 test 함수이며 main은 `cli.sensor_anomaly._self_check`의 비 int 반환을 0으로 바꾼다. 직접 읽은 self-check 380–480은 11개 case 판정을 만든다. 임시 합성 operator ledger의 verified_by 쏠림, self_only, 반복 failure mode, 같은 task_hash의 다른 결과, 오래된 표본 제외, min_count를 확인한다. timestamp를 현재 시각 기준으로 만든 현행 수정이 있으므로 예전 고정 날짜 만료를 현행 실패로 적지 않는다.

SUT 119–150은 깨진 JSON·비 dict·읽기 오류를 제외하며 파싱 불가 timestamp는 since 필터에서 제외하지 않는다. 310–336의 records_scanned는 이 선별 뒤의 값이다. 전체 이벤트 분모나 독립 검증자 실재를 인증하지 않는다. self-check의 CLAUDE_HOME 변경은 복원되지 않고 별도 CLAUDE_STATE_DIR도 덮지 않는다. unittest가 아닌 wrapper만 pytest로 실행하면 수집할 test가 없다는 점도 중요하다. 실제 알림 전달·model promotion 차단·사용자 인수는 미검증이다.

<a id="i19"></a>
## 19 — test_session_init.py

11개 함수다. 실제 repository HANDOFF 앞부분의 크기·Resume entry·phase_id·history 부재, 임시 ack store의 중복 제거와 status line, ready 직접 주입, 실제 graduation tick의 무예외 smoke, fake brain status 합계·예외를 검사한다. 임시 store 한 곳만 바꾼 compose 시험은 모든 status producer를 동시에 격리하지 않는다. fail-soft smoke는 내부 실패가 삼켜져도 성공한다.

`handlers/session/init.py` 108–136은 현재 byte 단위 HANDOFF 절단을 사용한다. 따라서 문자 절단 과거 결함은 현행 방어와 구분했다. 350–386은 validator scan tick과 ready 안내를 분리한다. 775–839에는 다수 상태 수집 및 실제 main의 GC/maintenance 호출이 있지만 이 테스트는 main 전체의 실행·입출력·부작용·총 context budget을 검사하지 않는다. `ready=True` fixture와 안내 token은 실제 validator 졸업·사람 승인·알림 수신을 의미하지 않는다. CS 단계의 관찰 표면 후보이며 SDD 완료 판정은 별도다.

<a id="i20"></a>
## 20 — test_settings_guard.py

14개 함수다. synthetic 권한 dict와 temp settings로 특정 rule 제거, covering rule 요구, 다른 경로·allow·비 file tool 거절, 다른 key 유지·마지막 comma·거절 시 원문 불변·손상 JSON을 검사한다. 마지막 시험은 소스 위치 settings의 ineffective_rules 개수만 상한 검사한다. 본 검토는 그 settings 파일이나 실제 인증정보를 열지 않았다.

`lib/settings_guard.py` 40–110의 효과 분류는 hardcoded Write/Read/NotebookEdit/MultiEdit 대 Edit 가정이고, 실제 도구 권한을 실행하여 측정하지 않는다. 현재 사실이나 Codex 권한 변환 규칙으로 추천하지 않는다. `_BUCKETS`는 deny와 ask 모두인데 primary에는 ask 행동 시험이 없다. 113–163은 지울 줄을 유일하게 찾고 JSON 구조의 다른 변화가 없는지 재검사하는 현재 방어가 있다. 쓰기는 일반 write_text이며 동시 변경·중간 실패·실제 경로 glob·Windows/WSL 적용은 미검증이다. 사용자의 전역 권한 요청을 이 원문 rule 제거의 채택 승인으로 해석하지 않았다.

<a id="i21"></a>
## 21 — test_similarity.py

7개 함수다. ontology snapshot의 빈 집합·필드 누락·교집합 없음·동일·부분 교집합·type 불일치·id 없는 field 제외에 대한 수식 오라클이다. missing/empty 양쪽이 1.0인 것은 수식의 경계값이며 스펙 완전성의 증거는 아니다. 중복 id, 필드 타입 손상, 데이터 출처·검증자 identity는 시험하지 않는다.

`lib/similarity.py` 전문의 dict comprehension은 같은 id를 마지막 값으로 덮고 고정 0.5/0.3/0.2 비중을 계산한다. 실제 `engine/debate.py` 72–91은 이를 similarity_log로 기록하며 backup이고 convergence 판정에 사용하지 않는다고 명시한다. 이 직접 caller를 확인했으므로 빈 snapshot 1.0만으로 곧 토론 자동 승인이라고 주장하지 않는다. 실제 convergence 전체 closure와 사람 판단은 별도 검토 대상이다.

<a id="i22"></a>
## 22 — test_skeleton.py

3개 함수다. temp cwd의 비 Java/Java 정상 뼈대/없는 build 파일을 만들고 stdout PASS·FAIL만 확인한다. helper는 validator 반환값을 사용하지 않는다. 정상 fixture는 Gradle 의존성 문자열과 application.yml만 놓으며 Java 컴파일·서버 실행·DB·실제 사용자 요청을 수행하지 않는다.

`validators/skeleton.py` 전문은 src/main/java가 없으면 PASS(skip), Gradle 내용의 regex와 파일·패키지 디렉터리 존재를 검사하고 main은 int 상태를 반환하지 않는다. source-level 실패는 stdout으로 전달된다. primary의 수동 main은 예상 FAIL을 캡처해 자체 assertion으로 처리하므로 이 wrapper의 성공과 validator가 실제 프로젝트를 통과시켰다는 사실은 다르다. Maven·kts·패키지 경로 분기는 이 세 fixture로 전체 커버되지 않는다. Zeus 단계 3의 구조 확인 후보이며 단계 4·5·6 완료 표시는 아니다.

<a id="i23"></a>
## 23 — test_skill_candidate_detector.py

0개 최상위 test 함수와 네 unittest TestCase의 33개 메서드다. main이 네 class를 명시적으로 suite에 넣고 wasSuccessful로 반환하므로 class가 있다는 이유만으로 run_units가 아무것도 실행하지 않는다고 해석하면 안 된다. 앞선 두 class는 tracker/candidate root와 threshold=3을 패치한다. 기본 threshold=10 확인은 별도 class이며 대부분의 생성 흐름이 운영 기본값 10에서 시험되지는 않는다. 합성 payload의 반복 수·pattern 분류·manifest·session 분리·invalid silent·write failure silent·secret fixture·reflection adapter metadata와 안정된 cid를 검사한다.

실제 detector 47–48의 기본 root는 Path.home()/.claude이며 CLAUDE_HOME override가 아니다. reflection TestCase는 임시 reflection 파일만 만들고 insight root는 패치하지 않는다. `_build_candidate_from_reflection` 284–288의 no-write 설명과 달리 368–385는 insight_index.append를 호출한다. 직접 읽은 insight_index 338–341은 home/memory 원장에 append하므로 별도 실행 격리가 필요하다. 성공 실패는 swallowed exception 때문에 reflection 반환만으로 관측되지 않는다. 이 부수효과는 이번 검토에서 실행하지 않았다.

process_payload 115–124는 pattern tracker를 먼저 저장한 뒤 candidate를 secret scan한다. secret 시험은 `_build_candidate` 반환의 trace에 합성 패턴을 넣어 blocked marker만 확인한다. 원시 tool_input의 pattern이 tracker에 남는 경계는 검사하지 않는다. WebFetch는 netloc, Bash/WebSearch는 앞 두 token을 사용하며 이 원문 설계가 민감 값 최소화까지 보장한다는 결론은 불가하다. session slug의 절단·치환, candidate의 짧은 session prefix와 pattern hash 충돌, 중복 이벤트·동시 갱신·두 파일 쓰기 중간 실패도 미검증이다.

현재 _write_candidate 552–584에는 source priority 역전 덮어쓰기 방어가 있다. 동급은 refresh하며 JSON과 Markdown은 별도 쓰기다. 이 테스트에는 priority 소비·activation CLI·운영자 identity 검증이 없다. `handlers/post_tool/skill_candidate_extractor.py` 35–50은 env=1일 때만 호출하고 오류를 rc 0으로 삼킨다. pending_review·requires_operator·confirm_token은 출력 선언이며 사람이 검수하고 스킬이 안전하게 승격됐다는 증거가 아니다. Zeus log→scenario→코드 생성으로 흡수하려면 반복량과 실제 개선 효과를 구분하고 실패 알림·근거 보존·원장 transaction·승인 소비를 연결해야 한다.

<a id="trace"></a>
## 실행기와 격리의 공통 경계

`scripts/tests/run_units.py` 39–403을 연속으로 모두 읽었다. validator와 같은 suffix를 제외하고 test 파일을 수집한다. `tmp_path|monkeypatch|capsys`가 있는 최상위 def 정규식으로 pytest 경로를 고르고, 나머지는 main 존재 import probe 뒤 파일 subprocess를 실행한다. 이 정규식은 class/async/custom fixture의 완전한 탐지가 아니다. 본 범위의 resident에는 monkeypatch=None이 있어 pytest가 선택될 수 있고, reviewer의 monkeypatch_run은 그 whole-word 정규식에 해당하지 않는다. pytest에서 resident main의 env 복원은 수행되지 않는다.

기본 파일 실행은 rc와 stdout failure token을 보며 성공 시 stderr는 숨긴다. rust_scaffolder와 seam_gate의 _ok 누적 방식은 수동 main에서는 실패를 반영하지만 일반 pytest 함수 반환만으로는 그렇지 않다. skill_candidate_detector는 자체 unittest suite와 rc가 있어서 구분해야 한다. 두 self-check wrapper의 pytest 수집 0건도 명시적으로 분리해야 한다. runner의 숫자는 module 분모이고 각 파일의 함수/메서드/case 수와 같지 않다. 이 보고서에 기록한 선언 개수는 실행 통과 수가 아니다.

현재 POSIX symlink 분기와 pytest 경로가 있으므로 과거 “Linux 격리 분기 없음”을 현행 결함으로 주장하지 않는다. 그러나 링크는 OS 쓰기 금지가 아니고 scripts는 원본 자산으로 연결된다. 생성 실패 시 NO isolation으로 진행하며, 기존 CLAUDE_STATE_DIR과 Path.home 기반 경로를 전부 제거하지 않는다. pytest conftest는 CLAUDE_HOME·일부 insight whitelist/cache만 바꾼다. source 파일에 직접 쓰는 scheduler fixture와 별도 home/state root를 모두 보호하려면 실행 시 독립적 파일시스템 경계가 필요하다. 본 검토의 metadata 실행은 원본을 import하지 않는다.

<a id="zeus"></a>
## Zeus의 8단계 SDD와 연결

| 사용자 단계 | 이 범위에서 얻는 자산 후보 | 아직 없는 완료 증거 |
|---|---|---|
| 1. 스펙 논의 | reverse stage 분리, release 기준 commit, reviewer 메시지 | 사람 머릿속 핵심 시나리오의 확인·범위 승인·명세 hash |
| 2. 디자인 분석 | seam 선언과 근거 위치, 코드/스펙 관찰 | 화면·상호작용·디자인 토큰·Storybook의 사람 검토 |
| 3. 코드 작성 | Rust testgen seed, 구조 검사, 작업 범위 프롬프트 | 생성 코드의 실제 구현·팀별 책임·모델 자격 |
| 4. 자체검증 | 오라클·실패·분모 분리, 원장 보존, 계약 결과 구분 | 실환경 실행 receipts·실제 검사 수·재현되는 환경 identity |
| 5. 알파 배포 | scheduler 및 CI report 계약의 출발점 | Linux/Windows/WSL 설치·기동·배포 identity·alpha health |
| 6. QA·증적 | lexical/seam 보조 신호, 사람용 알림 문구 | 무 mock 인수·금전 흐름·삼성 실기기 실측·승인 receipt |
| 7. 라이브 배포 | branch/clean/regression gate의 구분 | 승인된 revision·점진 배포·rollback·서비스 결과 |
| 8. CS | anomaly/heartbeat/brain divergence/candidate 발견 | 실제 알림 수신·사고 대응·시나리오 환류의 효과 검증 |

Zeus의 PG 런타임 정본과 Git 명세 정본을 기준으로 보면, 파일 기반 queue/원장/ready/complete 값은 비교할 소스 계약이다. 그것을 그대로 PG 상태 권위나 승인 증거로 삼을 수 없다. 각 전이에 attempt·spec/scenario/source/env identity, 실제 오라클과 실행 분모, 사람이 승인한 대상·범위, idempotency 및 실패 보존을 연결하는 설계가 필요하다. 이 보고서는 그 설계의 구현 또는 채택 승인서가 아니다.

Astra의 설계·최종 검증을 Sol의 guardrail과 Terra의 반복 가능한 구현으로 내려보내려면 독립 시나리오에서 동일 결과와 실패 감지 성능을 먼저 확보해야 한다. router 점수·역할 문자열·반복 횟수·ready 필드만으로 모델 자격을 줄 수 없다. Samsung 기기·Device Farm SDK/MCP·live interact·Replay는 후속 범위이며 여기서 구현하거나 시험했다고 주장하지 않는다.

<a id="unknowns"></a>
## 미완료와 다음 검증 입력

primary 본문 미독은 0이다. supporting은 원장에 표시한 구간만 읽었고, 특히 원자적 쓰기 helper, 전체 alert transport, role-cycle의 마지막 행 결속, 모든 cron job/GC·설치 서비스, reverse 후속 rollback과 extractor closure, router 전체 예산·메타/스코어 의존성, graduation 전체, reflection parser/activation, 실제 convergence·rewind 소비 및 프로세스 종료는 미완료다. 검색 hit와 AST 위치 파악은 supporting 전문으로 계상하지 않았다. 기술 가정은 현재 공식 권한/SDK 사실로 검증하지 않았으며 외부 추천으로 사용하지 않는다.

완료한 것은 고정 23개 파일의 의미 독해와 명시한 직접 구간 추적 및 자체 메타데이터 검사다. 원본 실행 0, 실제 Claude 검토·라이선스·OS·모델·사람 인수·전체 closure·흡수 승인 미완료 경계를 `remaining.json`과 `checkpoint.json`에도 유지한다. 자체 Ruff와 hash/range/ref 검사 결과는 `record-validation.json`에 별도로 보존한다. 운영 파일·공유 coverage·티켓·Git commit/push는 변경하지 않았다.
