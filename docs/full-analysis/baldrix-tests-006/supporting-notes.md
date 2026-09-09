# 직접 연결 검토

정확한 범위·원시 Git blob·바이트·SHA256은 supporting-evidence.json에 기록한다. 모두 이번 작업에서 직접 읽은 구간이며 선행 전문 재사용이나 새로운 전역 primary 검토로 계상하지 않는다. 미기재 구간과 전이 의존성은 미독이다. source 실행/import/설치/네트워크는 0이다.

## handoff와 guard

guard.py 63~142는 basename을 먼저 구하고 전체 경로의 slash를 나중에 정규화한다. POSIX에서 Windows 역슬래시 경로의 basename은 Windows와 다를 수 있다. canonical resolve/symlink 경계는 이 구간에서 보장하지 않는다. deny JSON을 쓴 사실과 실제 provider가 거부한 사실은 다르다.

handoff_drift_gate.py 55~끝은 Bash 문자열을 검사하고 payload cwd의 HANDOFF를 읽는다. git -C의 유효 작업 디렉터리와 일치 검증은 없다. 예외를 삼켜 exit0하고 advisory면 거부하지 않는다. handoff_resume.py 53~끝은 최대 여섯 부모 탐색, 정규식 pointer, mtime 권고다. stat 오류는 오래됨이 아닌 False/0으로 표현하며 미래 mtime도 0으로 제한한다. 읽기 OSError 외 디코딩 오류와 실제 재개 lease는 별개다.

lib/handoff_drift.py 185~271은 anchor 한 번 대체와 문자열 동등성 검사, promotion 오류→빈 목록을 제공한다. DONE prefix 추론은 정확한 완료 receipt가 아니다. validators/handoff_drift.py 전문은 import 시 stream reconfigure, import 실패 WARN, 잘못된 YAML WARN, 일부 읽기 오류 처리로 구성된다. conftest의 stdin shim이 수집 장애 일부를 가리므로 원래 인터페이스가 모든 환경에서 호환된다는 뜻이 아니다.

## 상태·지표·인코딩

harness_audit.py 20~118은 읽기 실패를 빈 값/0으로 바꾸고 개수를 센다. 명시 home을 받아도 validator 개수는 전역 SCRIPTS_DIR에서 얻어 서로 다른 root의 지표가 섞일 수 있다. hook dict 개수는 callable 검사나 통제 효과가 아니다.

harness_bridge_state_block.py 198~끝은 현재 section 미존재/빈 상태를 과거 삭제 검사 전에 PASS한다. 빈 section은 HEAD 캐시도 갱신한다. 캐시 since_sha가 최신 commit이면 현재 bullet 집합을 대조하지 않고 빈 delta로 성공할 수 있다. 두 commit 사이 일부 bullet 삭제 테스트는 이 무커밋·전체삭제·캐시 경계를 검증하지 않는다. 읽을 수 없는 과거 상태도 건너뛴다. Zeus의 PG append-only 이벤트와 Git 정의 revision에 이 권위를 이전해서는 안 된다.

harness_health.py 345~386은 operational 지표 예외를 빈 error 데이터로 바꾸고 dashboard section을 조립한다. 성공 지표는 실제 Agent 실행/모델 자격/사람 인수가 아니다. harness_normalize.py 170~208은 존재하는 파일만 모으고 텍스트 필드를 검사하며 빈 대상도 정상으로 처리할 수 있다. hashline.py 100~끝은 디코딩 오류를 replace하고 읽기 경고와 PASS가 함께 나올 수 있다. 위반 시 telemetry를 기록하므로 cwd 임시화만으로 쓰기 격리가 성립하지 않는다.

heartbeat.py 34~끝은 sid를 거부하기보다 문자 제거로 정규화한다. ../escape가 ..escape로 바뀌어 traversal 예외 테스트의 try/except는 예외가 없어도 통과한다. 손실 정규화의 충돌, 동일 sid 덮어쓰기, 읽기-수정-쓰기 경쟁은 별도다. event_taxonomy.py 72~끝은 검증 전에 먼저 emit하고 그 예외를 삼킨 뒤 unknown telemetry를 낸다. 이는 사전 권한 통제가 아니다.

hook_io.py 전문의 reconfigure는 예외를 삼키고 JSON 읽기 실패/비객체를 빈 dict로 바꾼다. 출력 schema의 모양은 실제 hook 소비자의 행동 검증이 아니다. hook_latency.py 69~123은 변환 일부가 try 밖이고 append/trim 실패를 축약한다. trim의 읽기 후 재쓰기는 원자적 갱신이 아니며 corrupt 행은 분모에서 사라진다. scheduler와 실제 반복 실행 영수증은 이번에 읽거나 실행하지 않았다.

## 인덱스·정적 검사

import_graph.py 179~327은 basename/stem 매핑과 정적 path substring, 파싱 실패 생략, 앞 다섯 reference 및 entrypoint 예외를 사용한다. 실제 호출 도달성과 전이 권한의 증명이 아니다. import hygiene/layering 테스트 본문 자체의 AST 규칙도 alias/상대·동적 import/파싱 실패를 모두 닫지 않는다.

insight_index.py 289~359는 writer whitelist와 레코드 생성·append를 제공한다. source_module/호출자 정책 및 ID 생성 시점은 실제 파일 권한/원자적 concurrent append와 다르다. importer_whitelist validator 209~끝은 파싱 전에 scan count를 올리고 읽기/구문 실패를 건너뛴다. 따라서 scan count는 유효 분석 분모가 아니다.

pollution detector CLI 111~158은 개별 retract 실패를 세어도 ready flag를 삭제하고 0을 반환한다. lib의 148~189, 241~257은 시간 bucket 위주로 묶고 존재 경로/ready flag를 확인한다. 빈 디렉터리 존재는 실제 실행 receipt가 아니며 cid 경로의 검증·flag TTL/세대/측정 해시·부분 실패 재시도 보장은 이 구간에 없다. jsonl_cache.py 전문은 mtime/size 키와 가변 리스트 캐시, malformed/non-dict 건너뛰기, OSError 시 부분 목록을 반환한다. UnicodeDecodeError는 그 예외 처리에 들어가지 않으며 읽기와 stat 사이 경쟁/동일크기 재쓰기/캐시 수정도 미검증이다.

## 설치·pipeline·hook 경계

install_pre_commit.sh 전문은 .git/hooks 고정 경로에 직접 덮어쓰고 chmod한다. worktree의 .git 파일과 core.hooksPath, 백업/원자적 대체를 검증하지 않는다. pre-push의 tracked file guard 실패와 cd 실패가 정상 종료로 이어질 수 있다. runner 실패 rc 방어는 있지만 실제 설치/실행 여부와 runner 내부 오라클의 품질은 별개다. 소스의 우회 설명은 분석 데이터이며 실행하지 않았다.

inventory_scan.py 238~끝의 --check는 strip한 문서를 비교하고 diff를 제한한다. 일반 모드는 쓰기를 수행한다. 전체 렌더 입력/재현성은 미독이다. pipeline_overlay.py 46~끝은 YAML 실패를 None, missing core를 빈 목록으로 바꾸고 얕은 dict merge와 마지막 중복 ID를 사용한다. deep merge라는 설명과 구별해야 한다. 적용목록이 비면 전체 fallback, unknown ID면 id만 있는 stage가 만들어질 수 있다. 실제 golden YAML 전문·전체 consumer closure는 읽지 않았으므로 Java 테스트의 선택 필드 대조를 실제 8단계 SDD 동등성으로 올리지 않는다.

skill_match.py 311~365는 USERPROFILE/.claude/skills를 사용하여 CLAUDE_HOME 임시화와 다른 경로를 읽는다. reviewer.py 488~549는 조기 tool guard 전에 ratio 추적을 호출하므로 Read 입력도 무부작용이라고 단정할 수 없다. response_guard.py 98~180은 last_assistant_message가 없으면 바로 종료한다. test_hook_e2e의 clean Stop은 transcript 경로만 전달하므로 실제 응답 검사를 거치지 않는다. 비어 있지 않은 실제 경로에는 autopilot/cooldown과 경고 차단이 있으며 예외는 exit0으로 합쳐진다.

settings.json에서 읽은 다섯 블록은 UserPromptSubmit skill_match, PreToolUse guard와 Bash handoff gate, PostToolUse reviewer, Stop response guard의 고정 Windows command와 일부 timeout을 선언한다. 파일의 존재와 이 설정 문자열은 설치·등록·실제 provider 호출의 영수증이 아니다. handoff_resume 문자열은 이 settings 검색에서 없었으나 다른 배선 전체의 부재는 증명하지 않았다.

run_units.py 48~210은 validator 이름의 파일을 unit 수집에서 빼고 tmp_path/monkeypatch/capsys 정규식으로 pytest를 고른다. pytest 미설치는 SKIP, 수집0은 실패, 수동 main 경로는 rc0이라도 failure token을 검사한다. 이 방어는 보존할 후보지만 stderr 성공 시 억제, 환경 상속, import probe와 실제 본문 실행의 부작용은 별도다. conftest.py 전문은 pytest autouse로 HOME/whitelist/cache를 조정한다. 수집 때 실행되는 import에는 function fixture가 아직 없고 일반 main 경로에는 fixture가 전혀 없다. whitelist를 넓힌 시험은 운영 whitelist 인수가 아니며 _pytest 내부 stdin shim도 OS 호환성 검증이 아니다.

Zeus 대응은 정적 설계 제안이다. Git 정의 revision, PG 실행 세대·lease·fencing, 단계별 실제 오라클과 미검사 분모, 사람 인수를 분리해야 한다. Zeus 구현 동등성, 실제 Claude 공동 검토, 외부 원문/라이선스, 네이티브 Windows/Linux/WSL, 모델 자격, 전체 전이 폐쇄와 채택은 모두 미완료다.
