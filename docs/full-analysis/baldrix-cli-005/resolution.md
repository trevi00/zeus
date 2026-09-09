# CLI 005 공동 검토 결정

Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 CLI 6개·83,631바이트를 root Codex와 실제 Claude가 각각 전문으로 읽고 독립 판단을 비교했다. [Codex 초안](codex-initial.md), [Claude 초안](claude-initial.md), [토론 입력](discussion-prompt.txt), [Claude 토론](claude-discussion.md)을 원문으로 보존한다. 최종 판단은 아래의 정정과 한정을 따른다.

실제 Claude 세션은 `a3e795e3-66bb-4969-b311-aa4ab3e76bf1`이다. 초기 450.11초, 토론 245.52초 모두 returncode=0/is_error=false이며 원시 JSON·stderr·해시·모델 사용량은 각 receipt에 있다. Claude에는 Read/Glob/Grep만 허용했다. Claude 정적 검토와 root의 격리 실행은 다른 증거다. 원본 하네스와 기존 codex-harness를 수정하지 않았다.

## 실제 실행

[원본 단위 테스트 영수증](test_telemetry_report.receipt.json)은 `scripts/tests/test_telemetry_report.py` **19 passed**다. [UTC 관측](components-UTC0.stdout.txt)과 [KST 관측](components-KST-9.stdout.txt)은 같은 원본 함수를 network-none/read-only/non-root Linux 컨테이너에서 호출했다. 이미지 ID, 인자, 프로그램 및 출력 해시, 원본 1,648개 바이트 불변을 영수증으로 남겼다. 입력 fixture를 만들었으며 원본 함수나 의존 객체를 mock으로 대체하지 않았다.

| 관측 | 결과 |
|---|---|
| UTC 문자열의 epoch | UTC에서 정확, KST에서 −32,400초 |
| 1분 전 이벤트를 1시간 창으로 조회 | UTC에서는 유지, KST에서는 탈락 |
| 오류지만 duration 없는 hook | 보고 결과 `{}`로 사라짐 |
| bool duration | True가 1ms로 집계됨 |
| 숫자 timestamp | AttributeError |
| NaN 시간 창 | 파싱 단계에서 수용됨 |
| package.json / pubspec.yaml 프로젝트 | ts-fe / flutter로 발견, 검사 0개, 종료 코드 0 |

19개 단위 테스트의 성공이 이 결함을 부정하지 않는다. 원본 시간 테스트는 오프셋 오차를 허용하며 오래된 이벤트의 제거를 단정하지 않는다. 두 시간대의 같은 결과를 모든 운영체제·환경의 동일성으로 확대하지 않는다. 이 관측은 E2E, 실제 validator 수행, 사용자 인수, 모델 자격, Windows/WSL 원본 실행 또는 운영 배포가 아니다.

## 합의한 변경 요구

1. **상태와 실행 사실을 연결한다.** team_watch는 마지막 DONE을 실패 문자열보다 먼저 본다. commands/harness-team.md의 예시 wrapper는 작업 rc와 무관하게 DONE을 덧붙인다. wrapper가 완주하고 꼬리가 유지되면 실패가 DONE이 될 수 있다. 처음 발견한 파일 목록만 갱신하므로 나중에 나타난 worker와 미출현 필수 worker는 누락된다. 전원 FAILED는 자동 완료 조건을 충족하지 않는다. 예상 목록·attempt ID·exit·산출 검증을 PG 기록으로 분리해야 한다. mailbox 조회는 디렉터리 생성 경로를 거치고 전체 메시지 수를 세므로 미처리 큐 깊이와 다르다.
2. **지표의 분모와 누락을 표시한다.** UTC를 명시적으로 파싱하고 invalid/unknown timestamp를 구분한다. duration 누락과 오류를 보존하며 finite numeric 범위를 검사한다. 현재 JSONL만 읽는 all-time과 회전 이력을 구분한다. evaluator-accuracy의 verdict/자기점수 분포는 독립 정답 오라클의 정확도가 아니다. top 후보 빈도는 실제 주입·소비나 비용 대비 품질이 아니다. 기존 FA012와 연결된다.
3. **검사 적용 대상과 수행 결과를 분리한다.** ts-fe/flutter 무배선·검사 0개를 배포 PASS로 소비하면 안 된다. validate_project는 일반 main 반환값을 버리고 stdout 문자열을 분류한다. 실제 13개 validator가 이 때문에 실패를 놓친다는 전수 증거는 아직 없다. 필수 검사, 수집/실행 건수, 환경과 시나리오 귀속이 필요하다. 기존 FA009·FA014와 연결된다.
4. **정책 변경과 writeback에 불변 승인·복구 계약을 둔다.** 실제 함수는 `apply_threshold_override`다(Codex 초안의 이름 오기 정정). no-op은 유효 현재값을 보지만 `_is_risky`는 registry default를 기준으로 한다. NaN/step·ready-flag 내용·변경과 감사의 비원자성이 남는다. writeback은 캡처한 동일 바이트로 해시와 hunk를 처리하는 개선이 있다. 그러나 token read/check/unlink에서 unlink 실패를 삼켜 동시 single-use가 보장되지 않는다. 토큰은 patch hash·정규 target 신원에 결속되지 않는다. capture→replace 경합·다중 파일 부분 변경·감사 실패, rollback sidecar 내용/대상집합 대조와 부분 복구를 설계해야 한다. 운영 writer·토큰 소비·rollback은 실행하지 않았다.
5. **분석 명령의 실제 효과를 표시한다.** 정확한 trending 경로는 `open_gaps → _unapplied_changes → CHANGES[*].canary`다. root 토론 입력의 `_operator_pending_canary`는 잘못된 이름이었다. pending_changes 두 canary 구간에서 모델 subprocess와 소스 트리 probe 파일 쓰기를 확인했다. gaps/dry-run의 읽기 전용 보장은 철회한다. 다른 canary의 전이 효과는 미완료이며 이번에 실행하지 않았다. raw resident 원장만 읽는 report는 compaction 이후 payload 재수화도 하지 않는다.

## 원시 검토의 정정

- NOT_STARTED는 발견 후 파일이 사라지거나 missing path를 직접 분류할 때 가능하다. 모든 접근 불가가 그 상태로 변환되는 것은 아니다. 자동 종료 누락과 Ctrl+C 등 외부 종료도 구분한다.
- telemetry 상수는 **import 전** CLAUDE_TELEMETRY_DIR을 존중한다. import 후 env 변경에 대한 동적 조회 불일치가 잔여다. 과거 사고 주석을 현재 코드로 오인한 Claude 초안을 정정했다.
- NaN의 safe 분류는 raise_safe/lower_safe 비교 경로의 정적 성질이다. `either`는 항상 risky다. registry 주석의 FULL_BODY_MIN_SCORE만 배선됐다는 설명은 전수 caller 검증을 대신하지 않는다. 모든 gate 무력화/Infinity 전면 차단은 철회한다. registry에 min/max 필드는 없고 step 필드는 있지만 적용 경로가 검증하지 않는다. 부분 YAML은 남은 정상 키를 보존할 수 있다.
- threshold의 공개 문자열과 writeback 난수 토큰은 다르다. 토큰 보유·pid/sid/cwd 형상만으로 승인한 사람과 검토 revision이 입증되지는 않는다.
- path_denylist에는 realpath, normcase, Windows long-path 방어가 있다. 문제는 positive skills allowlist가 원래 문자열을 검사하고 Edit에 정규 경로를 되돌려 넣지 않는 점이다. CLI는 상대 경로만 home/.claude에 붙여 resolve하고 절대 경로는 그대로 반환한다. 모든 경로가 같은 방식으로 resolve된다는 토론 표현을 한정한다.
- CRLF는 old-side context/삭제 줄과 LF diff 비교에서 mismatch가 날 수 있다. 모든 hunk가 실패하지는 않는다. pure insertion과 혼합 개행은 별도다. apply·parser 전체 실행이나 CRLF 실제 테스트는 하지 않았다.
- compaction은 최근 20 **행** 밖을 즉시 모두 접는 것이 아니다. payload가 있는 행의 keep/slack 조건에 따라 접고 archive/on-disk payload를 남긴다. 정확한 문제는 이미 접힌 보고에 inline 본문이 없을 때 trending report가 재수화하지 않는 것이다.
- 테스트 파일명 부재는 테스트 전무의 증거가 아니다. Claude 지원 전문 수량 4→5, 경로 tests→scripts/tests를 정정했다. coverage는 실제 독해 구간으로 제한한다. source의 E2E 이름이나 HANDOFF DONE은 현재 인수 실적이 아니다.

## 잔여와 채택 경계

root 지원 독해는 supporting-evidence.json에, Claude의 추가 독해는 원시 응답에 귀속한다. 다른 파티션을 자동으로 root 전문 검토로 승격하지 않는다. 전체 canary/validator 호출, policy proposer·배선, worker session 매핑, 동시성·손상·복구, Windows/Linux/WSL 및 사람 시나리오, 라이선스와 최종 채택을 계속해야 한다. 원본 보호 경로 probe를 실행했다고 주장하지 않는다.

전체 분석과 흡수는 미완료이며 Zeus 운영 기능을 새로 활성화하지 않았다. 이번 실제 Claude와 토론한 6개 이외의 cron·CLI 파티션은 별도 Codex 분석자의 정적 검토이며 Claude 공동 검토 완료로 합산하지 않는다. 합의된 기능 구현은 사용자 요청대로 전수 분석 후 주 Codex가 맡는다.
