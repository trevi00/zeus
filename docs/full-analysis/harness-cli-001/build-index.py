"""Inert pinned-byte metadata recorder; no upstream imports or execution."""
import hashlib
import json
from pathlib import Path

BASE = Path('C:/Users/rudtn/zeus')
OUT = BASE / 'docs/full-analysis/harness-cli-001'
ROOT = BASE / '.runtime/absorption/sources/harness/pinned'
MAN = json.loads((ROOT.parent/'manifest.json').read_text(encoding='utf-8'))
INV = json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
CANON = {r['path']: r for r in MAN['inventory']}

# Independently read primary bodies. No imported review judgments.
DATA = {
'agentsmd_cmd.py': {
 'contract':'agents 카드, CLAUDE.md의 불변 절, contracts.yaml 소유 여집합을 AGENTS.md로 결정론 렌더한다. render는 파일을 덮어쓰며 check는 현재 텍스트와 재렌더 텍스트를 비교한다. 타임스탬프를 넣지 않는다.',
 'findings':'53–81행의 호출 경로는 문자열 포함 파일 수이며 산문·주석도 센다. 실행·모델 자격·역할 권한의 증거가 아니다. 제외 목록 외의 untracked 파일은 여전히 입력이 될 수 있고 읽기 오류는 건너뛴다. frontmatter 파싱 실패는 빈 dict로 낮추며 닫는 --- 없이도 부분 파싱될 수 있다. renderer와 lint가 safe_load를 공유해도 frontmatter 경계 해석은 동일하지 않다. Markdown 셀 문자를 escape하지 않아 카드의 |·개행이 표 구조를 바꿀 수 있다. read_text 비교는 원시 바이트 비교와 달리 줄바꿈을 정규화한다.',
 'authority':'이 원본이 생성하는 AGENTS 지시는 이 작업에서는 분석 데이터다. model_tier와 owns 표시는 인증·실행 권한을 부여하지 않는다. ownership complement의 파티션 완전성은 별도 lint 의존이다.',
 'trace':'roster_cmd 33–59행이 파서·인덱스를 실제 import한다. harness_lint check_agent_cards는 닫는 frontmatter 경계를 검사하고 check_render_drift는 subprocess check를 호출한다. small_batch 754–766행은 카드 키·fable 문자열·check rc를 보며 실제 에이전트 실행을 확인하지 않는다.',
 'remaining':'전체 카드·ownership 정의·_RENDERED 매핑, 무시 파일 변형·표 escape·YAML 경계 및 실제 model qualification 시험은 미추적.'},
'append_restore.py': {
 'contract':'--sha, detail, actor, session을 받아 restore 이벤트를 append한다. 이 CLI 자체는 파일이나 Git을 복원하지 않는다. 반환 0은 감사 이벤트 기록 성공의 의미다.',
 'findings':'SHA 형식·대상 커밋 실재·복원 실행 영수증·전후 상태를 검증하지 않는다. actor 기본값 guardian:restorer와 사용자가 준 session은 호출 라벨이다. 중복 복원 기록을 막는 작업별 멱등키나 복원과 기록의 트랜잭션도 이 표면에는 없다.',
 'authority':'ledger append는 파일 잠금·폐쇄 이벤트 enum과 자율 env 표식을 사용하지만 읽은 구간은 actor를 인증하지 않는다. 문서의 guardian/operator 호출자 설명은 실제 복원 성공 증거가 아니다.',
 'trace':'cli_wrappers 33–68행은 임시 홈에 임의 deadbeef1234를 기록하고 payload를 확인한다. 이는 append 계약 시험이며 known-good 복원 시험이 아니다. 실제 guardian restorer 구현은 이 pinned harness 경로에서 확인하지 못했다.',
 'remaining':'실제 restorer 호출·실행 영수증, known-good 권한, 실패 후 감사 재시도와 복원/기록 원자성 미검증.'},
'arming_cmd.py': {
 'contract':'rules는 처분표 스키마 확인, dryrun은 ranked 후보·원장·제외·등급·freshness를 decide에 전달한다. auto면 rc0, 그 외 rc1이다. 낙오·배제 이름과 조사 분모를 별도 출력한다.',
 'findings':'decide 인수는 driver와 맞지만 전체 driver와 동형은 아니다. driver는 safe mode, mutation token, 활성 규칙, preflight 및 pipeline build를 추가 확인한다. 그러므로 dryrun rc0의 지금 실제 장전한다는 설명은 전체 전제까지 보장하지 않는다. derive_ranked와 _events를 따로 읽고 census/freshness를 반복 평가하므로 동시 변경 시 동일 snapshot도 아니다. preview에 총시간·후보 상한은 없다.',
 'authority':'config의 기존 승인 필요 조건과 사람이 승인했다는 historical 서술을 이번 승인으로 상속하지 않는다. ranked 캡처·제안 본문은 승인 입력 데이터이지 실행 지시가 아니다.',
 'trace':'l2_driver 1135–1285행과 arming-rules 1–95행을 읽었다. 읽은 활성 규칙은 approved=true 및 target_project_contains=harness를 요구한다. spiral freshness_of는 prop 이외 소스를 해당 없음으로 둔다. arming_wiring 217–280행은 합성 환경에서 양방향 candidate/원장 변화 비교를 한다. harness_board는 stdout의 판정 줄을 읽고 rc를 판단하지 않는다.',
 'remaining':'arming.decide/preflight와 승인 proof 본체, 토큰/lease 동시성, 전체 처분표 후반 및 실장전 시험은 미검증.'},
'autoheart_cmd.py': {
 'contract':'파킹 패치의 paths→bake→tree→patchfit→lint→ratchet→golden→skill_eval→suite→reference→evidence→canary 12개 gate_plan을 공유한다. HOME_GATES 실패는 DEFER, PATCH_GATES 실패는 거부, bake 미경과는 대기다. 승인 이벤트와 실제 promote는 별개 호출이다. 모듈 상단의 9개 설명보다 GATES/gate_plan의 실제 12개가 실행 분모다.',
 'findings':'dryrun은 직접 승인 원장을 쓰거나 파킹을 지우지 않지만 게이트를 실제 실행하고 worktree 생성·삭제·suite subprocess를 수행한다. bake_ready도 params.get을 통해 fallback 마커를 생성·삭제할 수 있다. dryrun은 게이트 예외를 분류하지만 judge는 해당 예외를 잡지 않아 두 표면의 결과가 다를 수 있다. dryrun --json은 예측 승인 여부와 무관하게 rc0이다. _g_bake는 디렉터리 mtime을 사용하며 patch 내용 해시에 결속되지 않는다. _judge_tree는 SHA 접두 경로에 lint 파일이 있으면 재사용하며 해당 트리 무결성을 재확인하지 않는다. _known_good_sha의 guardian 경로는 GUARDIAN_HOME으로 주입 가능하므로 OS 신뢰 경계는 별도 입증이 필요하다.',
 'authority':'문서의 사용자 결정으로 사람을 뺐다는 주장은 원본의 역사적 권한 설명이다. Zeus의 독립 연구·conductor·인증된 사람 인수·실제 실행 영수증을 대신하지 않는다. judge는 파킹 patch 존재에서 시작하며 이전 격리 검증·제안 상태·불가침 등급 검사를 인증된 영수증으로 결속하지 않는다. 승인 payload에는 pending/파일명/등급/요약이 있지만 실제 patch SHA·기준 HEAD·환경·전체 시험 분모 봉인이 없다. 동시 HEAD/patch 변경과 승인→promote 실패의 창이 남는다.',
 'trace':'_g_reference는 앵커의 lint/runner로 home을 검사하며 후보를 검사하지 않는다. 후보는 _g_ratchet/_g_evidence/_g_canary의 별도 worktree다. 후보 자신의 suite runner가 증거 수를 만들고 참조 runner 비교는 home에 대해 이뤄진다. _g_ratchet는 게이트 문장 집합만 비교하며 후보의 전역 waiver 집합으로 제거를 면제한다. 같은 문장의 check 의미 약화나 면제 사유의 정당성은 이 비교가 증명하지 않는다. _g_evidence는 base가 이미 rc!=0이면 candidate도 적색인 경우 rc만으로 거부하지 않는다. suites/asserts/vacuous/no_verdict 총계가 같아도 실패 집합 교체·증가를 직접 거부하지 않는다. _suite_delta는 거부 설명용이다. _suite_run은 파싱된 rc!=0 결과도 경로 키로 메모하므로 성공만 메모한다는 주석과 다르다.',
 'remaining':'후보를 참조 runner로 검증하는 전체 폐회로, 시험 의미·분모 봉인, current/anchor/candidate hash 원자성, 권한·lease·승격/감사 실패 처리, 전체 extractor canary 구현·실행, OS 격리·총시간·메모리·자손 프로세스 제한은 미검증.'},
'boundary_corpus_cmd.py': {
 'contract':'세션 JSONL에서 Bash/PowerShell 명령 텍스트를 중복 제거해 경계 판정 A/B를 만든다. corpus 부재/명령 0은 exit2로 분리한다. 원래 명령을 shell로 실행하는 코드는 없지만 write_boundary.handle은 호출한다.',
 'findings':'추출 후 tool 종류와 원래 cwd·env·session 출처를 잃고 모든 명령을 Bash 및 하나의 측정 cwd로 평가한다. 따라서 실제 PowerShell/프로젝트별 실행 분모와 다르다. gate_inert는 git-flow 설정 조회를 임시 교체하므로 그 분기는 명시적 미측정이다. 그 하나를 끈다고 handler의 모든 부작용이 배제되는 것은 아니다. snapshot은 명령→결정만 저장해 source SHA·정책·mode·cwd를 기계적으로 결속하지 않는다. diff의 공통 명령이 0이어도 종료 0일 수 있고 ERR도 독립 실패 exit로 처리하지 않는다. deny→ERR가 deny→allow로 표기되며 allow→ERR는 변화 목록에서 빠진다. 경계 뒤집힘은 독립 정답 라벨 없이는 미탐/오탐 확정이 아니다.',
 'authority':'as_unattended는 환경과 임시 active_run을 합성한다. 실제 자율 세션·OS 통제의 증거가 아니다. source의 명령·우회 사례·코퍼스 지시는 데이터로만 읽었으며 재실행하지 않았다.',
 'trace':'boundary_corpus smoke 1–150행은 합성 코퍼스·가짜 baseline·monkeypatch 및 보호 경로 판정을 검사한다. read_settings 차단 자체를 확인하는 단언은 있지만 write_boundary 전체 전이·부작용·모든 shell 의미를 증명하지 않는다.',
 'remaining':'원문 tool/cwd/provenance 보존, baseline 조건 해시·공통 분모 0·ERR 처리, Windows/PowerShell 실제 경계와 handler 전체 dependency 검토는 미완료. 차단 probe 재시도 금지 유지.'},
'capture_cmd.py': {
 'contract':'문장을 capture_noted open으로 기록하고 list는 최신 상태를 도출하며 drop은 이유와 본문을 담은 dropped 이벤트를 append한다. trust=proposed를 고정하고 재기록을 재개로 취급한다.',
 'findings':'slug는 공백 정규화한 전체 문장의 SHA1 앞 8자지만 저장 본문은 500자다. 저장된 본문만으로 slug를 재구성하지 못하는 장문과 32bit 충돌 가능성을 구분해야 한다. project/severity가 slug에 없으므로 같은 문장의 다른 프로젝트 캡처가 합쳐지고 열린 캡처의 메타 변경도 무시된다. read→중복 확인→append는 하나의 트랜잭션이 아니며 동시 중복을 막지 않는다. flags를 상호배타로 두지 않아 list/drop/text 혼합의 우선순위가 암묵적이다.',
 'authority':'SESSION=operator는 pollution 오탐 회피용 라벨이지 사람 인증이 아니다. 캡처 본문은 사람의 의도 제안이며 검증된 관찰·인수·배정 승인과 다르다. --project는 텍스트 선언이며 실제 프로젝트 identity를 입증하지 않는다.',
 'trace':'backlog.open_captures는 slug별 최신 이벤트를 고르고 state!=dropped인 항목을 모두 반환한다. 알 수 없는 state를 reader가 폐쇄 거부하지 않는다. spiral.derive_ranked가 캡처를 실제 전달한다. capture smoke 110–172행은 임시 원장에 기록/중복/list/drop을 검사한다.',
 'remaining':'충돌·장문·다중 프로젝트·동시 중복, unknown state·철회 fold 및 캡처가 인수/승인으로 승격되는 전체 경로 미검증.'},
'classify_cmd.py': {
 'contract':'명령 subprocess 또는 stdin 텍스트와 rc를 test_outcome에 전달해 pass/skip0, behavior/silent1, infra2, vacuous3, unknown4, timeout5로 분류한다. 임의 명령의 정규식 분류는 근거 추정이며 실제 원인 증명은 아니다.',
 'findings':'--stdin에서 --rc 누락도 0으로 가정한다. command의 모든 -- 토큰을 제거해 대상 명령 의미를 바꿀 수 있다. --suite와 --quiet-ok 충돌은 명령 실행 후 검사한다. argparse 자체의 잘못된 옵션/타입은 여전히 기본 exit2이므로 사용법 오류64 계약이 모든 입력에 적용되지 않는다. subprocess는 전체 stdout/stderr를 수집하고 합칠 때 구분자를 넣지 않는다. timeout은 자손·네트워크·메모리 격리가 아니다.',
 'authority':'--quiet-ok는 호출자의 선언이며 도구별 자격 인증이 아니다. --stdin의 supplied rc는 runner 영수증과 다르다. skip과 pass가 같은 종료 코드여도 실제 검증 미실행을 보존해야 한다.',
 'trace':'test_outcome 217–345행에서 rc0의 RAN_OK/단언 문자열과 quiet_ok가 pass를 만들며 rc!=0에서는 infra 서명이 우선한다. suite_runner 171–191행은 stdin 예제의 exit 대응, 334–339행은 명령 없는 사용법만 검사한다.',
 'remaining':'완전 argv 보존·사전 인수 검증·필수 rc·출력 provenance·서명 오탐/미탐·OS별 timeout과 실제 외부 runner 연계는 미검증.'},
'completion_cmd.py': {
 'contract':'완료선 YAML의 included/excluded/goal/interpretation을 검증하고 evidence 경로 존재를 평가한다. list와 soft assess의 rc0은 완료가 아닐 수 있으며 --strict만 미도달 rc1이다.',
 'findings':'supporting completion_line.assess는 exists 또는 glob을 사용한다. 디렉터리·빈 파일도 근거 실존으로 충족하며 내용을 읽거나 결과·현재 revision·환경·실행 여부를 검증하지 않는다. YAML root는 다른 디렉터리를 가리킬 수 있고 name은 경로 성분 제한이 없다. list는 선언 위반을 출력하고 계속해 rc0으로 끝낸다. malformed YAML/비매핑의 오류 처리가 공통 스키마로 닫혀 있지 않다.',
 'authority':'완료선 선언은 Git 정의 자산으로 유지하되 실존 충족률을 사용자 8단계 SDD 완료나 인간 경험 인수로 승격할 수 없다. note가 내용 판단은 다른 곳의 몫이라고 명시한다.',
 'trace':'completion_line.py 1–87 전문을 읽었다. spiral.derive_ranked의 completion gaps 소비와 polish smoke 137–166행을 연결했다. 시험은 proof.txt에 x를 써서 strict rc0을 검사하므로 내용 검증을 의도하지 않는다.',
 'remaining':'완료선별 실제 gate/receipt 연결, 내용·버전·인수 유효성, path confinement/비정상 YAML 및 전체 설정은 미검증.'},
'coverage_cmd.py': {
 'contract':'임시 sitecustomize/coverage 설정과 환경변수로 자식 Python을 계측하고 combine 후 파일·표면별 문장 커버리지를 계산한다. 기본은 문턱 없는 측정이며 --fail-under만 수치 기준을 더한다.',
 'findings':'branch=false다. 계측 shard가 있다는 사실은 모든 자식/시험이 계측됐다는 증거가 아니다. run_all 결과를 len만 사용하므로 실제 시험 실패·skip·timeout 상태가 최종 측정 PASS와 연결되지 않는다. never 목록에만 있는 파일의 문장 수는 비율 분모에 더하지 않으므로 미발견 표면을 포함한 전체율로 확대할 수 없다. --json은 JSON 뒤 PASS 또는 FAIL 문자열을 덧붙여 일반 JSON 파싱을 깨뜨린다. jobs/timeout/fail-under는 유효 범위·유한값 검사가 없으며 임시파일 삭제가 raw shard 재검산을 어렵게 한다.',
 'authority':'문장 도달은 검증 의미·요구사항 충족·사용자 인수와 다르다. source의 pip install 안내는 실행하지 않았다. 계측 환경 복구와 OS/부트스트랩 격리도 별도 경계다.',
 'trace':'suite_cmd.run_all 254–274행은 파일 glob과 thread 기반 subprocess 병렬화를 수행한다. coverage_bootstrap 1–90행은 한 ledger 시험의 shard/분모/환경 복구와 빈 패턴을 보며 coverage 미설치면 SKIP rc0이다. 전체 코퍼스 커버리지 시험이 아니다.',
 'remaining':'누락 shard/파일 분모, 실제 시험 결과 결속·JSON 계약·병렬 상태/coverage 버전 의존·네트워크/자원 제한 및 Win/Linux/WSL 실행은 미검증.'},
'cycle_cmd.py': {
 'contract':'spiral pipeline의 계획에서 ^REDO: stage-id 줄을 추출해 cycle_plan→cycle_finished→cycle_started를 append한다. REDO0이면 converged를 반환한다. 알 수 없는 정규식 일치 stage는 거부한다.',
 'findings':'오타·들여쓰기·다른 구문으로 REDO가 매치되지 않는 것도 REDO0 수렴이 된다. plan 승인·내용 해시·현재 단계 완료·quiescence를 검사하지 않는다. circuit.gate는 plan/finished 두 이벤트 뒤에 호출되어 circuit OPEN 거부도 원장 일부를 이미 바꾼다. 세 append가 단일 트랜잭션이 아니고 중복 호출·동시 cycle 번호 제어가 없다. --ledger 또는 --pipeline 한쪽만 주면 그 값을 무시하고 active_run 양쪽을 사용한다.',
 'authority':'계획 파일과 REDO 부재가 인수 결정은 아니다. 재개방은 기존 PASS 유효성·run/cycle identity·예산의 변경이므로 PG runtime에서 권한과 원자성을 결속해야 한다.',
 'trace':'derive_cycle 214–228행은 철회를 적용하고 pipeline_started/cycle_started/compaction을 fold한다. spiral smoke 95–145행은 PASS→redo→재PASS·REDO0·ghost 및 nonspiral을 검사한다. circuit 거부 이전 기록과 중복 재개방은 읽은 시험 구간에서 확인되지 않았다.',
 'remaining':'circuit 전체 구현·실제 plan caller·중복/동시성·부분 실패·오타와 무의미 수렴·입력쌍 검증 및 실행 증거 미완료.'},
'debate_cmd.py': {
 'contract':'open/verdict/check/status/doubts를 엔진에 위임한다. check는 continue0/converged3/error4/park5라 일반 성공0 관례와 다르다. verdict는 JSON object만 허용하며 actor를 폐쇄 열거하고 넓은 예외를 rc4로 표면화한다.',
 'findings':'actor 이름은 독립 패널 실행 증명이나 모델 자격이 아니다. CLI는 gen의 양수/현재세대, --json/--json-file 상호배타를 보장하지 않고 파일 쪽을 우선한다. check는 순수 조회가 아니라 decision 파일과 종결 이벤트를 만들 수 있다. source 문자열 스캐너의 leak_flags는 관측이며 인증·차단을 대체하지 않는다.',
 'authority':'명령 Markdown의 별도 컨텍스트 패널 절차는 source 지시 데이터다. 실제 별도 모델 reviewer를 실행했다는 근거가 아니다. 구조 스냅샷 수렴과 trust:confirmed 카드가 Zeus의 독립 검토·승격 권한을 대신하지 않는다.',
 'trace':'debate.md 1–18행은 정확한 exit 분기를 규정한다. engine.debate 76–162행은 verdict 기록, closed replay, 수렴시 카드→원장, cap 종료를 보여준다. debate smoke 110–141행은 합성 패널 값의 LOCK 재현·카드 문자열·early cap·판정 부재를 검사한다. 실제 Claude/Codex 패널 시험은 아니다.',
 'remaining':'rules.evaluate_convergence 전체·독립 실행 proof·세대/후보 hash·동시 종결·카드/원장 원자성·외부 코드 인코딩 및 CLI exit end-to-end 시험 미완료.'},
'delegate_cmd.py': {
 'contract':'다른 project의 .claude/settings.json에 현재 harness hook 명령을 절대경로 핀으로 복사하고 marker를 쓴다. 기존 truthy hooks는 거부하고 settings 백업을 만든다. status는 marker·런처 파일·hooks 존재를 확인한다.',
 'findings':'source settings는 이미 launcher 변수를 따옴표로 감싼다. 공백 있는 home을 치환할 때 다시 따옴표를 넣어 중첩 따옴표가 생길 수 있어 shell argv 검증이 필요하다. status는 hooks가 현재 기대 명령/이벤트/해시와 같은지 확인하지 않아 다른 hooks도 on으로 판단한다. remove는 전체 hooks JSON에 home 문자열이 있으면 hooks 전체를 지워 설치 후 추가된 타인 hook까지 제거할 수 있다. 파일과 marker 쓰기는 원자적 한 쌍이 아니며 backup은 복원에 사용하지 않는다. home 이동 후 remove는 현재 home 문자열 비교라 옛 위임 hooks를 남기고 marker만 제거할 수 있다.',
 'authority':'설치는 source가 사람 표면이라고 부르지만 CLI 자체의 인증은 없다. 이번에는 설치/제거/런처 실행을 전혀 하지 않았다. Claude hook 의미와 Git Bash 전제를 Zeus adapter에 그대로 적용하지 않는다.',
 'trace':'settings.json 1–40행의 실제 따옴표를 확인했다. polish smoke 31–69행은 단순 임시 경로·8개 이벤트·기존 키·백업·marker·런처 부재를 검사한다. 공백 경로의 실제 Bash 실행이나 혼합 hooks 보존은 읽은 구간에 없다.',
 'remaining':'정확한 위임분 식별·CAS 및 rollback·부분 쓰기·인증·공백 경로 shell parsing·Windows/WSL 네이티브 실행·전체 settings/dispatch 의미는 미검증.'},
'endpoint_cmd.py': {
 'contract':'project 디렉터리에서 atlas를 구성하고 overlay 오류를 rc1로 내며 query는 resolved 여부로 rc0/1을 반환한다. atlas는 노드·seam·shared value 요약이고 query는 항상 JSON이다.',
 'findings':'resolved는 이름이 카탈로그/atlas에서 식별됐다는 뜻이며 artifact present·seam PASS·blocking 인수와 다르다. atlas는 부재 seam도 등재하므로 atlas rc0 역시 계약 충족이 아니다. query는 선언된 1-hop와 shared wire value 연결이며 실제 모든 호출·런타임 영향 범위를 계산하는 것이 아니다. 입력 파일·catalog·runtime 이벤트의 같은 snapshot hash가 없다.',
 'authority':'atlas는 파생 색인이다. PG runtime 권한이나 배포·변경 승인으로 승격할 수 없다. 동명의 artifact/seam/value는 classify의 artifact 우선순위를 따른다.',
 'trace':'endpoint_graph 24–168행을 읽었다. catalog_for 오버레이 및 project events, seams parsing/parity/scope를 호출한다. endpoint smoke 135–165행은 overlay 오류·대표 artifact 해결·unknown rc1을 검사하며 atlas seam 1 문자열 단언은 전체 topology 증명이 아니다.',
 'remaining':'graph_queries/seams 전체 구현·실제 catalog/config·자동 승급 원장·이름 충돌·source identity·통합 graph 영향 및 실행 시험 미완료.'},
}

SUPPORT = {
'scripts/cron/l2_driver.py':[[598,675],[1135,1285]],
'scripts/lib/completion_line.py':[[1,87]], 'scripts/lib/backlog.py':[[70,112]],
'scripts/lib/derive_state.py':[[214,240]], 'scripts/engine/debate.py':[[76,162]],
'scripts/engine/endpoint_graph.py':[[24,168]],
'tests/integration/test_cli_wrappers_smoke.py':[[25,76]],
'tests/integration/test_small_batch_smoke.py':[[754,780]],
'tests/integration/test_arming_wiring_smoke.py':[[217,280]],
'tests/integration/test_autoheart_smoke.py':[[1,115],[820,895]],
'tests/contract/test_boundary_corpus_smoke.py':[[1,150]],
'tests/integration/test_capture_smoke.py':[[110,172]],
'tests/contract/test_suite_runner_smoke.py':[[171,210],[330,355]],
'tests/contract/test_coverage_bootstrap.py':[[1,90]],
'tests/integration/test_polish_smoke.py':[[25,85],[133,167]],
'tests/integration/test_spiral_smoke.py':[[95,145]],
'tests/integration/test_endpoint_graph_smoke.py':[[135,177]],
'tests/integration/test_debate_smoke.py':[[110,150]],
'config/paths.yaml':[[1,32]], '.claude/settings.json':[[1,40]],
'config/policy/arming-rules.json':[[1,95]],
'scripts/cli/health_cmd.py':[[35,53]], 'scripts/cli/sandbox_cmd.py':[[59,69]],
'scripts/cli/spiral_cmd.py':[[133,168],[266,305]],
'scripts/lib/ledger.py':[[243,320]], 'scripts/cli/suite_cmd.py':[[254,292]],
'brain/spikes/harness_board.py':[[225,244]], '.claude/commands/debate.md':[[1,18]],
'scripts/lib/test_outcome.py':[[217,345]], 'scripts/lib/params.py':[[71,118]],
'scripts/validators/harness_lint.py':[[1031,1068],[1389,1447]],
'scripts/engine/sandbox.py':[[383,438],[475,551]], 'scripts/cli/roster_cmd.py':[[30,65]],
}
MAP = {
'agentsmd_cmd.py':['roster_cmd','harness_lint','small_batch'],
'append_restore.py':['ledger.py','cli_wrappers','paths.yaml'],
'arming_cmd.py':['l2_driver','arming-rules','spiral_cmd','arming_wiring','harness_board'],
'autoheart_cmd.py':['autoheart_smoke','l2_driver','health_cmd','sandbox_cmd','engine/sandbox','params.py','suite_cmd'],
'boundary_corpus_cmd.py':['boundary_corpus_smoke'],
'capture_cmd.py':['backlog.py','ledger.py','spiral_cmd','capture_smoke'],
'classify_cmd.py':['test_outcome.py','suite_runner_smoke'],
'completion_cmd.py':['completion_line.py','polish_smoke','spiral_cmd','paths.yaml'],
'coverage_cmd.py':['suite_cmd','coverage_bootstrap'],
'cycle_cmd.py':['derive_state.py','spiral_smoke','ledger.py'],
'debate_cmd.py':['engine/debate.py','commands/debate.md','debate_smoke','ledger.py'],
'delegate_cmd.py':['settings.json','polish_smoke'],
'endpoint_cmd.py':['endpoint_graph.py','endpoint_graph_smoke'],
}

def meta(root,p):
    raw=(root/p).read_bytes()
    return {'bytes':len(raw),'lines':len(raw.decode('utf-8-sig').splitlines()),
            'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def dump(name, data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

support=[]
for p,ranges in SUPPORT.items():
    m=meta(ROOT,p); c=CANON[p]
    assert m['git_blob']==c['object'] and m['bytes']==c['bytes'],p
    if c.get('snapshot_sha256'): assert m['sha256']==c['snapshot_sha256'],p
    assert all(1<=a<=b<=m['lines'] for a,b in ranges),p
    support.append({'source':'harness','path':p,'revision':MAN['revision'],**m,
       'read_ranges':ranges,'disposition':'supporting_selected_body_read','tests_executed':[],
       'limit':'해시는 파일 전체에 적용되며 의미 검토 범위는 명시 구간뿐이다. 시험 파일 읽기는 실행 증거가 아니다.'})
for p,ranges in {'AGENTS.md':None,'docs/research-standard.md':None,
                 'src/codex_harness/domain/sdd.py':[[8,22],[185,202]]}.items():
    m=meta(BASE,p)
    support.append({'source':'zeus','path':p,**m,'read_ranges':ranges or [[1,m['lines']]],
                    'disposition':'supporting_selected_body_read','tests_executed':[]})
dump('supporting.json',support)
rows=[]
body=['# CLI 001 독립 정적 검토\n',
      '13개 primary 전문을 읽었다. 주석의 과거 실측·PASS·사용자 결정은 원본 작성자의 역사적 기록이며 이번 실행·승인으로 상속하지 않았다. 아래 정적 경로 분석은 현재 배포 결함 재현이 아니다. supporting.json 밖의 구현과 다른 리뷰의 판정은 근거로 사용하지 않았다.\n']
for item in INV['paths']:
    p=item['path']; name=Path(p).name; n=DATA[name]; m=meta(ROOT,p);c=CANON[p]
    assert m['bytes']==c['bytes'] and m['git_blob']==c['object'],p
    if c.get('snapshot_sha256'): assert m['sha256']==c['snapshot_sha256'],p
    refs=[r['path'] for r in support if any(x in r['path'] for x in MAP[name])]
    body.extend([f'## {name}\n',f'원본 `{p}` 1–{m["lines"]}행 전문. SHA256 `{m["sha256"]}`.\n'])
    for title,key in [('계약·입출력','contract'),('실행·상태·오류·반복·예산','findings'),('권한·신뢰 경계','authority'),('실제 호출·설정·시험 추적','trace'),('남은 검증','remaining')]:
        body.append(f'**{title}** — {n[key]}\n')
    if name=='autoheart_cmd.py':
        body.append('**역사적 주장과 후속 해결** — 1243–1258행은 보류 소비자가 KeyError를 내던 과거 상황을 현재형으로 설명한다. 그러나 pinned l2_driver 641–668행은 deferred를 따로 출력하고 파킹별 예외로 다음 항목을 계속한다. 이 문제는 읽은 후속 코드에서 대응돼 있으며 현재 같은 KeyError가 난다고 주장하지 않는다. 반면 승인을 쓴 뒤 promote가 실패하면 다음 순회가 proposed만 고르는 점은 여전히 남는다. canary의 후보 적색 주석은 보류라고 표현하지만 실제 False는 PATCH_GATES 거부로 가서 파킹 삭제 경로에 연결된다. `_g_evidence`가 HEAD를 직접 재는 구현과 1284행의 다음 회 원장 기준 주석도 다르다.\n')
    body.append('연결 파일: '+', '.join('`'+x+'`' for x in refs)+'. 정확한 구간은 supporting.json. 원본·시험 실행 0회.\n')
    rows.append({'source':'harness','path':p,'revision':MAN['revision'],
      'git_blob':m['git_blob'],'bytes':m['bytes'],'pinned_sha256':m['sha256'],
      'observed_sha256':None,'disposition':'body_reviewed_call_test_trace_pending',
      'read_ranges':[[1,m['lines']]],'review_ref':'docs/full-analysis/harness-cli-001/review.md#'+name.replace('.',''),
      'supporting_refs':refs,'tests_executed':[],
      'tests_not_run':[{'path':x,'reason':'이번 할당은 정적 분석 전용. 전체 dependency/격리 검토 및 별도 실행 영수증 필요.'} for x in refs if x.startswith('tests/')],
      'test_limits':'이번 원본·원본 테스트·생성 코드 실행 0회. Supporting 선택 구간만 읽음. 역사적 PASS와 현재 실행 증거 분리.',
      'remaining':[n['remaining'],'실제 실행 영수증·독립 검토·후보/환경/정책 결속 이후에만 채택 판단 가능'],
      'adoption_approved':False})
assert len(rows)==13 and sum(r['bytes'] for r in rows)==168396
dump('files.json',rows)
(OUT/'review.md').write_text('\n'.join(body),encoding='utf-8')
dump('remaining.json',{'primary_body_reviewed':13,'primary_body_pending':[],
 'status':'body_reviewed_call_test_trace_pending','tests_executed':[],
 'paths':[{'path':r['path'],'remaining':r['remaining']} for r in rows],
 'global':['원본·원본 테스트 실행 금지 범위이므로 모든 실행 검증이 남는다.',
 '실제 supporting 구간 밖을 전체 구현 등가 또는 완전 caller/config/test 검증으로 승격하지 않았다.',
 '실제 guardian restorer, OS 권한/격리, 모델 자격 및 Win/Linux/WSL 이식성 검증은 남는다.',
 '인증된 사람 경험 인수와 사용자 8단계 SDD·PG runtime SSOT로의 구현 흡수는 이 보고서의 완료 범위가 아니다.'],
 'blocked_probe_retried':False,'adoption_approved':False})
dump('validation.json',{'partition':INV['partition'],'scope_sha256':INV['scope_sha256'],
 'revision':MAN['revision'],'primary_paths':13,'primary_bytes':168396,
 'manifest_sha256':meta(ROOT.parent,'manifest.json')['sha256'],
 'partitions_sha256':meta(BASE,'docs/full-analysis/partitions.json')['sha256'],
 'full_body_read':13,'git_blob_matches':13,'sha256_recorded':13,
 'manifest_sha256_comparisons':sum(bool(CANON[r['path']].get('snapshot_sha256')) for r in rows),
 'supporting_files':len(support),'source_executions':0,'tests_executed':[],
 'validation_kind':'inert_metadata_integrity_only','adoption_approved':False})
print(json.dumps({'paths':len(rows),'bytes':sum(r['bytes'] for r in rows),'supporting':len(support),'source_executions':0}))
