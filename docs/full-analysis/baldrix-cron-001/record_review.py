"""Record completed static body review. Never import or execute upstream code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


# Purpose, concrete semantic finding, actual caller/support connection, file-specific pending work.
data = {
    '__init__.py': (
        '내부 유지보수 cron package 설명; 실행 코드는 docstring뿐이다.',
        '파일 존재를 registration이라 부르고 flag emission을 read-only side effect라 부른다(3–6,18–24). 실제 OS 등록과 같지 않고 flag/check 파일 쓰기는 상태 변경이다. 문서의 4종 목록은 driver의 14 CronJob 및 7 GC와 다르다. platform Cron 도구와 내부 state 분리 설명은 범위 선언이며 실제 외부 연결 증거는 아니다.',
        '동일 primary scheduler_driver 100–158에 실제 내부 등록표, register_task.py/ps1에 OS 등록 구현이 있다.',
        'CLAUDE.md Mutation 표·platform Cron 실제 정책·라이선스 원문 미확인. package import 자체는 스케줄 실행이 아니다.'),
    'check_brain_push.py': (
        'live→brain 파일 및 brain→remote 누락을 관찰하고 ready/check 파일 생성.',
        '71–110: brain status 예외를 error로 저장하면서 divergence=0, remote 검사 예외도 push_gap=False로 만든다. 123의 durable QUIET은 미확인 상태에서도 나올 수 있다. bool을 int로 인정하여 divergence에 더할 수 있다. flag는 fired일 때만 덮고 quiet에서 지우지 않아 stale flag가 남는다. 파일 쓰기 실패는 묵살하고 항상0 설명과 달리 import/type 오류는 밖으로 나갈 수 있다. checker doc의 concurrent save 금지와 runner doc의 언제든 save 안전 주장이 다르다.',
        'driver brain_push_check 12시간, run_brain_push가 flag 존재를 소비. brain_store 203–265에서 save의 lock 없는 copy/union 및 torn line 생략을 직접 확인.',
        'brain_store.status/brain_git_status.at_risk 전이 구현·remote 최신성/네트워크/상태 schema 미완료. flag는 실행 승인 또는 원격 durability 영수증이 아니다.'),
    'check_l2_promotion.py': (
        'L1 나이·개수·query latency 연속 초과로 L2 준비 flag 생성.',
        '51–68의 p99는 10회 측정 최대값이다. query를 실제 재실행하나 표본 대표성·분포 추정이 없다. 97–111은 unretracted append-order 첫 행을 나이 기준으로 하므로 최초 전체 insight 또는 최소 timestamp와 다르다. 손상/잘못된 shape state와 int streak는 예외를 낼 수 있어 always0가 아니다. streak는 같은 입력을 빠르게 3회 실행해도 누적되며 evaluation cadence/id를 묶지 않는다. quiet 시 기존 flag가 남고 write 실패를 무시한다.',
        'driver l2_promotion_check 24시간→run_l2_promotion. lib/insight_index 369–405 query는 append order, retracted 필터, 전체 scan이다.',
        'query loader/retraction index와 promoter 전체 미독. latency SLO 테스트 이름은 query doc 주장만 읽었고 실행하지 않았다. 시간 역행·동시 streak 갱신 pending.'),
    'check_ledger_compaction.py': (
        'operator ledger 50행·25% 중복 문턱을 넘으면 압축 후보 flag 생성.',
        '48–64는 malformed JSON 및 dict 아닌 행을 버리고 OSError에도 부분 목록을 돌려준다. run도 이 목록으로 rewrite하므로 순수 compaction_plan의 foreign row 보존 설명과 다르게 원본 손상/비객체 행이 영구 누락될 수 있다. iterator의 filesystem 오류는 uncaught, quiet에서 flag 미삭제, telemetry/flag 쓰기 실패 무시. 절대 후보 path를 기록하지만 run은 재스캔하여 flag payload를 직접 신뢰하지 않는 점은 적절하다.',
        'driver 24시간 check/run. run_ledger_compaction은 chk 모듈의 scanner/threshold를 재사용. lib/ledger_compaction 1–80 전문은 human_override·hash 없음 유지, ts 문자열 최신값 선택이다. test_cron_jobs 68–108은 정상 fixture 및 처음부터 flag 없는 quiet만 검증한다.',
        '실제 ledger append writer lock·timestamp 정규화·malformed 보존 테스트 미완료. symlink/reparse와 동시 append 충돌 pending.'),
    'check_pollution.py': (
        'burst pollution detector 결과를 cleanup flag 및 telemetry로 노출.',
        'confirmed는 정답 라벨이 아니라 250ms bucket≥3 및 correlation artifact 부재 휴리스틱이다. lib 148–187에서 서로 다른 correlation도 같은 시간 bucket으로 묶고 cid를 검증 없이 path에 결합한다. legitimate artifact가 GC/미동기화/권한 문제로 없어도 오인할 수 있다. 44–46 detector 오류는 uncaught, flag는 quiet에서 남고 쓰기 실패는 exit0과 구분되지 않는다.',
        'driver pollution_check 6시간, run_pollution_cleanup 소비. lib/insight_index_pollution_detector 146–214의 실제 cluster/confirmation 본문을 읽음.',
        'load_entries·artifact lifecycle·측정 flag 규칙 전체 미독. 실제 오염 정답 oracle 및 false-positive 평가 미실행.'),
    'check_role_cycle.py': (
        'orchestrator survey, breaker, running marker로 역할 실행 준비 판정.',
        'survey가 순수 관찰이라는 6행 주장과 달리 lib/role_orchestrator 94–107은 등록 canary를 호출한다. survey 내부 예외가 survey-failed Finding으로 돌아오면 queue>0이 되어 작업 근거가 된다. breaker read 예외는 막지만 lib breaker는 표본 없음이면 닫힘이다. marker 개수만 보아 stale PID/liveness와 관계없이 영구 차단 가능하며 check→run 사이 배타적 예약은 없다. ready가 깨지면 flag를 삭제하고 write 오류4를 내는 점은 구형 checker보다 명시적이다.',
        'driver role_cycle_check 12시간; run_role_cycle이 assess를 재호출. role_orchestrator 94–139, breaker 51–99, test_unattended 209–277의 marker/fake survey·breaker 예외·소스 문자열 검사 독해.',
        '실제 canary 및 survey 다른 수집기 전이·marker cleanup/liveness·process race 미독/미실행. 준비 판정은 모델 자격이나 작업 승인 자체가 아니다.'),
    'check_surgery_cycle.py': (
        '수술 후보·breaker·clean tree·미병합 selfmod branch를 보고 준비 flag 생성.',
        '56–61은 Git branch 오류를 빈 목록으로 반환하여 리뷰 대기 차단을 fail-open한다. assess가 현재 branch==main을 확인하지 않는데 본선 clean으로 설명한다. Git timeout 예외는 assess의 outer catch 밖이다. local --no-merged main만 보므로 다른 worktree/remote 리뷰 상태의 전체 근거가 아니다. check→open 사이 lock/exact HEAD 없음. flag 재검사/삭제는 있지만 overwrite 시점 경쟁을 막지 않는다.',
        'driver surgery_cycle_check 24시간, run_surgery_cycle 재확인. 직접 cli.surgery candidates 및 cli.selfmod.is_clean 호출은 primary import/본문에서 추적; 이번 partition에서는 이 두 구현 전문 재검토로 승격하지 않았다.',
        '후보·clean/generated 범위와 Git porcelain 전이 검토 남음. 여러 worktree·failed Git·stale branch 테스트 미실행.'),
    'probe_hook_latency.py': (
        '실제 hook synthetic latency를 시계열에 기록.',
        '49–55에서 hook 실행 후 value만 저장하고 Signal.warn/detail의 비정상 종료 정보를 버린다. 실패한 hook의 latency도 기록되면0 성공이다. float 변환 및 HL.record 호출은 try 밖이라 never raises 설명보다 약하다. lib golden_signals는 real home/scripts cwd와 상속 env에서 SessionStart/4 prompt hooks를 실행하므로 문서의 격리 실행이 구현되지 않는다. hook_latency._trim은 파일을 다시 써 append-only 설명과 다르며 동시 append 손실 가능.',
        'driver hook_latency_probe 6시간, lib/golden_signals 182–219 및 hook_latency 69–106 실제 실행·append/trim 구간 독해.',
        '다섯 hook의 모든 전이 권한·설정·latency log path/retention const 미완료. 실제 유저 지연 또는 성공률 표본으로 사용할 수 없다.'),
    'register_task.ps1': (
        '환경 인자로 Windows ScheduledTask action/trigger/principal을 만들어 강제 등록.',
        '47–65는 Once+반복 N분, StartWhenAvailable, IgnoreNew,72h 제한, Interactive Limited 현재 USERNAME으로 -Force 등록한다. argv/exe/cwd 존재나 허용 경계는 검증하지 않고 공백 여부만 본다. 토큰 값이 caller env에만 있다는 26–27 설명은 실제 Argument에 전달되면 작업 정의에 지속되는 사실과 다르다. 실행 성공/반복 관측이나 저장 정의 재조회가 없다. BOM 경고는 source 인코딩 계약이며 라이브 PowerShell 파싱 증거가 아니다.',
        'register_task.py 179–190가 NoProfile/ExecutionPolicy Bypass -File 및 BALDRIX_TASK_* env로 호출한다. scheduler 자체와 별도 OS 등록 mutation.',
        'Windows 계정/domain 이름 해석, login/logout/sleep 및72h 중단 동작 미실행. Linux/WSL-native에는 대응 등록 구현이 없다.'),
    'register_task.py': (
        'Windows scheduler 등록·조회·삭제 CLI 및 선택적 token 삽입.',
        'command(False)는 token을 제거하지 않고 삽입만 생략하므로 inherited env에 이미 있으면 run_*가 gated라는 설명을 보장하지 못한다. --with-token은 공개 문자열을 task argument에 저장하며 actor/범위/만료 승인 근거는 없다. show는 CSV를 단순 split하고 token substring으로 판단하며 표시 주기는 실제 task trigger가 아닌60 상수다. query 실패를 미등록으로 합쳐 권한/도구 오류를 구분하지 못한다. install만 Windows guard, show/remove는 Linux에서 schtasks FileNotFound가 날 수 있다. 등록 성공 뒤 저장 정의·첫 실행 검증은 하지 않는다.',
        'register_task.ps1과 직접 env/argv 연결 전부 primary 독해. test_unattended 359–371은 command 문자열과 callable 여부만 검사하여 task 등록/예약 실행 증거가 아니다.',
        '실제 OS task state 미접근. command roundtrip, CSV escaping, locale/codepage, pythonw stdout=None 실행 및 inherited token 회귀 미실행.'),
    'run_brain_push.py': (
        '공개 enable-cron-job 문자열 gate 후 brain snapshot 및 orphan branch push.',
        'flag의 존재만 확인하고 save→ack→rename→autopush 순서다. rename 성공 여부를 무시하고 push 실패도0으로 끝나 이미 ack/consumed가 남는다. remote opt-in은 driver만 확인하며 이 모듈 직접 호출에는 없다. brain_store 203–233은 copy2 race와 torn line 생략을 인정하므로 언제든 안전한 snapshot이라는 runner 설명은 과장이다. autopush 140–185는 worktree cleanup/commit/push를 실제 수행하고 nochange도 pushed=True를 반환한다. ack key의 invocation UUID는 같은 논리 작업 dedup이 아니다.',
        'driver brain_push_run scope=REMOTE 12시간, check_brain_push flag. brain_store/autopush 지정 지원 구간, test_cron_jobs 21–63 token 검사 독해.',
        'autopush helper 원격 tip 확인·worktree 경계·credential/secret scan 전체 미독. network receipt 없음. source 문서 push 권한 선언은 Zeus 허가가 아니다.'),
    'run_l2_promotion.py': (
        'flag 존재와 token을 확인한 뒤 L1→L2 promoter 및 ack/streak reset.',
        '124–181은 promote_all 예외만 잡고 부분 L2 쓰기 rollback은 없다. promote 반환 구조는 출력 때 쓰므로 ack/consume/reset 뒤 잘못된 결과 shape에서 실패할 수 있다. consume False는 무시, .consumed 이름은 ms만 사용하고 입력 snapshot/논리 run ID와 결합되지 않는다. p99만 reset하여 age/count 조건은 다음 checker에서 반복 발화 가능. checker와 reset이 같은 JSON을 별도 read/write하여 갱신 손실 가능. token mismatch 오류에 실제 env 문자열을 그대로 출력한다.',
        'driver l2_promotion_run 24시간과 primary checker 연결. advisory_ack 및 l2_promoter는 import/call 위치만 추적, 내부 실행 의미는 미완료.',
        'promoter idempotency/transaction, ack 실패·부분 mutation·반복 trigger 회귀 미독/미실행. UUID를 recurrence dedup이나 승인 영수증으로 해석하지 않는다.'),
    'run_ledger_compaction.py': (
        '현재 ledger 재스캔, superseded archive 및 active 파일 원자 교체.',
        '99–115에서 archive append 후 active rewrite의 두 파일은 transaction이 아니다. append writer와 lock을 공유하지 않고 일정 .tmp 이름을 써 concurrent run 경쟁과 read 이후 신규 행 손실 가능. checker scanner가 생략한 malformed/non-dict 원문은 archive에도 없다. archive만 성공하고 replace 실패하면 retry archive 중복 가능. consume/ack 오류 및 flag 재생성 경쟁은 구분되지 않는다. lib compaction_plan ts 문자열 정렬은 timezone 혼합 시 시간 최신성과 다르고 task_hash schema가 dict/list면 예외 가능.',
        'chk threshold/scanner 모듈 재사용, lib/ledger_compaction 전문1–80 및 atomic_json44–127 지원 독해. test_cron_jobs111–115는 테스트 시작 부분만 읽었으므로 idempotency 테스트 완료로 집계하지 않는다.',
        'live ledger writer/locks와 전체 압축 테스트 미독. immutable PG 원장을 직접 축소하지 않고 파생 projection/retention 정책으로 변형 필요.'),
    'run_pollution_cleanup.py': (
        'token/flag 뒤 하위 CLI measure→detect --execute로 retraction 수행.',
        '68–90은 import whitelist 때문에 sanctioned subprocess를 쓰지만 실제 두 번째 gate를 measure로 스스로 생성하므로 독립 승인으로 볼 수 없다. subprocess timeout이 없고 stdout의 마지막 줄만 보존한다. 하위 detect 111–156는 일부 retract 실패에도 ready flag를 삭제하고0을 반환한다. 따라서 상위는 부분 실패를 ack·consume 성공으로 기록한다. 논리 run fingerprint나 retraction idempotency receipt 없이 invocation UUID를 새로 만든다.',
        'driver pollution_cleanup_run 6시간, checker와 flag 연결. cli/insight_index_pollution_detector111–158 및 lib/insight_index369–435에서 append-only retract/오류False 구간 독해.',
        'measure threshold/flag 발급, 전체 retraction writer 정책·실제 corruption oracle 미완료. nested subprocess 종료와 부분 결과 회수 미실행.'),
    'run_role_cycle.py': (
        '역할 enqueue→공유 resident drain1→계약 확인→decisions harvest.',
        '재확인은 있지만 배타적 claim/작업 ID 결합이 없다. resident는 전체 queue 첫 항목을 drain하므로 방금 enqueue한 orchestrator 대신 오래된 다른 topic을 실행할 수 있다. _last_run_had_contract는 공용 ledger 마지막 비손상 행만 보며 run/time/topic을 확인하지 않고 adhoc도 contract_ok=True다. harvest는 모든 과거 role 행을 재처리한다. harvest 실패해도 flag 삭제, 실패 drain은 flag를 남겨 다음 반복에 enqueue 중복 가능. nested timeout 예외가 cycle에서 처리되지 않아 alert/최종 JSON 보장이 없고 driver600초는 worker900초보다 짧다.',
        'cli/resident341–405, resident_store140–201, cli/decisions61–88, role_orchestrator94–139 직접 경로 독해. test_unattended263–267은 문자열 검사이며 test_unattended_e2e1–140은 실제 ledger+fake survey fixture다.',
        'headless host 권한·DM.record dedup·원장 payload load/직접 worker tree 전체 미완료. 입력 task와 결과 artifact를 결합한 collection/termination 인수 미실행.'),
    'run_scheduler.bat': (
        'USERPROFILE Claude scripts로 이동해 py launcher로 driver 실행·log append.',
        '14행에 enable-cron-job을 고정 삽입하여 기본 check/GC만 실행한다는 앞 주석과 다르다. 2026-06-18 operator decision 주석은 현재 사용자 승인 영수증이 아니다. cd 실패를 검사하지 않아 다른 cwd에서 모듈을 찾을 수 있다. state/log 디렉터리를 생성하지 않아 redirection 실패 시 Python 자체가 시작되지 않을 수 있다. append log에 rotation 없음. py -3은 정확한 Python/dependency revision을 고정하지 않는다.',
        'run_scheduler_hidden.vbs가 직접 이 BAT를 호출. register_task.py 신규 경로는 BAT 대신 pythonw -c driver를 사용하므로 두 독립 launcher의 gate 차이를 확인.',
        'Windows cmd 전용, WSL/Linux native 미지원. 실제 task가 어느 launcher를 참조하는지 확인하지 않았다.'),
    'run_scheduler_hidden.vbs': (
        'WScript.Shell로 BAT를 hidden+wait 호출하고 exit code 전달.',
        '8–10은 USERPROFILE 고정 Claude 경로와 sh.Run(...,0,True), WScript.Quit rc이다. 대기/exit 전달은 관찰되지만 child tree kill/result artifact collection 구현은 없다. 오래된 BAT token opt-in을 상속한다. WScript host/스크립트 파일 부재/권한 오류는 처리하지 않는다. password 없다는 설명은 task principal 실구성과 별개다.',
        '직접 호출 target run_scheduler.bat 전문과 연결. 신규 register_task.ps1 action은 이 VBS를 사용하지 않는다.',
        'WSH 사용 가능 여부, task Last Result 실제 전달 및 Windows hidden 동작 미실행. Linux/WSL-native 실행 대응 없음.'),
    'run_surgery_cycle.py': (
        'selfmod branch 생성→surgery1→dirty 파일 commit 후 리뷰 대기.',
        '111–135는 surgery rc를 기록만 하고 dirty가 있으면 실패 rc에도 commit하며 메시지에는 canary 통과를 단정한다. _dirty_paths는 target뿐 아니라 전체 non-generated porcelain 항목을 추가하여 다른 변경도 담을 수 있고 git add rc도 무시한다. Git status 실패는 빈 변경으로 취급해 cleanup branch -D를 시도한다. cleanup checkout/삭제 rc를 무시하고 현재 branch/HEAD ownership fence가 없다. topic은 초 단위라 경쟁 충돌 가능. exception/timeout에서 finally 복구가 없어 branch/파일/worker가 남을 수 있다. 실제 merge는 호출하지 않는 경계는 확인했다.',
        'driver surgery_cycle_run 24시간, check_surgery_cycle 재확인, cli.selfmod open 및 cli.surgery run 직접 argv 확인. lib win_quiet의 process-local patch는 모든 자손에 자동 전파되지 않는다.',
        'Git porcelain/clean/수술 검증 전체는 이번 지원 미독. 실패 rc+dirty commit, worker termination, exact input commit 및 review state 수집 인수 미실행.'),
    'scheduler_driver.py': (
        '14 CronJob과 7 GC를 per-job watermark/backoff로 순차 호출하는 내부 cadence driver.',
        '309–329 pass lock은 exists/read 후 atomic overwrite이고 exclusive create/CAS가 아니며 쓰기 실패도 True다. stale이면 살아 있는 PID도 회수하고 release는 소유 token 없이 unlink한다. _pid_alive는 Windows OpenProcess 권한 실패·POSIX PermissionError도 dead로 해석해 uncertainty→alive 설명과 상충한다. write_json_atomic False를 watermark/heartbeat에서 무시하여 성공 후 재실행 가능. wall clock pass 시작시각을 모든 job last_run으로 써 long pass/sleep/clock rollback이 cadence에 영향을 준다. no occurrence id/durable result/lease가 없다. outer timeout600이 role/surgery900보다 짧고 subprocess.run은 프로세스 트리·부분 artifact 회수 계약을 구현하지 않는다. GC는 in-process 무제한이라 stale-window worst-case timeout 근거도 성립하지 않는다. job별 state parse/write 예외는 job try 밖이라 one job never blocks others 설명보다 약하다. acted는 gated_remote를 제외하지 않아 실제 실행 수를 부풀린다. rc3을 모두 nothing으로 분류하고 gc False/negative int도 ok다. status/dryrun도 _state_dir ensure_dir로 디렉터리 생성 가능. 성공 stdout은 폐기하고 failure tail만 저장; UTF-8 replace는 byte 보존이 아니다. never_run은 status0이고 health는 GC 목록을 제외한다.',
        'primary CRON_JOBS100–126, GC129–158, runner615–647 및 register_task/BAT/VBS 전체 연결. atomic_json44–127, win_quiet1–80 지원 본문: atomic content replacement는 lock이 아니며 win_quiet는 현재 process Popen만 patch한다. test_scheduler_driver235–265는 순차 mock lock·stale dead PID fixture로 simultaneous acquisition을 재현하지 않는다.',
        '7 GC/dashboard 전체 동작·config 및 OS scheduler 실제 등록/실행 receipt 미확인. worker process identity/fencing/종료/결과 수집, crash recovery, blocked credential, DST/sleep/backoff 회귀 실행0. 정기 실행 선언을 실제 예약·완료 증거로 집계하지 않는다.')
}

manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8-sig'))
partitions = json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8-sig'))
partition = next(p for p in partitions if p['partition'] == 'baldrix:scripts/cron:001')
inventory = {r['path']: r for r in manifest['inventory']}
assert len(data) == len(partition['paths']) == 19
rows, notes = [], {}
for entry in partition['paths']:
    path = entry['path']
    name = Path(path).name
    raw = (PINNED / path).read_bytes()
    inv = inventory[path]
    manifest_sha = inv.get('snapshot_sha256')
    blob_sha = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    assert len(raw) == inv['bytes']
    assert sha(raw) == manifest_sha if manifest_sha is not None else blob_sha == inv['object']
    purpose, analysis, connection, pending = data[name]
    imports = []
    if name.endswith('.py'):
        tree = ast.parse(raw.decode('utf-8-sig'))
        imports = sorted({n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})
    note = {'purpose': purpose, 'analysis': analysis, 'caller_config_test_connections': connection,
            'remaining_trace': pending,
            'authority': '공개 token/env 및 원본 정책 주석은 DATA. Source-local file state/Git/Claude credentials and subprocess permissions are not Zeus authorization.',
            'platform': 'Windows Task Scheduler/PS/BAT/VBS와 Linux/WSL-native cadence 구성을 구분. Python callable여도 dependency/path/env/process behavior는 미실행. 파일 상태 상수와 state_dir 호출 시점 차이를 유지.',
            'decision': '변형 후보: 직접 채택 보류. PG canonical occurrence/lease/result events, scoped proposal approval and exact-source receipts 필요.',
            'tests': 'NOT RUN. Supporting ranges only; search hits and upstream past PASS are not execution evidence.'}
    notes[name] = note
    modules = ['application/scheduling.py', 'adapters/store.py', 'adapters/executor.py']
    if 'surgery' in name:
        modules += ['application/audit_gate.py', 'domain/skill_history.py', 'adapters/git.py']
    elif 'promotion' in name or 'pollution' in name or 'brain' in name:
        modules += ['adapters/knowledge.py', 'application/research.py']
    elif 'latency' in name:
        modules += ['domain/measurements.py', 'application/monitoring.py']
    rows.append({
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'], 'git_blob': inv['object'],
        'pinned_sha256': sha(raw), 'manifest_bytes': inv['bytes'], 'pinned_bytes': len(raw),
        'matches_manifest_sha256': True if manifest_sha is not None else None,
        'manifest_sha256_status': 'present and matched' if manifest_sha is not None else 'absent in manifest; exact raw bytes matched manifest Git blob SHA-1 instead; pinned SHA-256 freshly recorded',
        'matches_manifest_git_blob': blob_sha == inv['object'], 'matches_manifest_bytes': True,
        'read_extent': 'full', 'line_count': len(raw.splitlines()), 'disposition': 'semantically_reviewed',
        'review_ref': 'docs/full-analysis/baldrix-cron-001/semantic-notes.json#' + name,
        'semantic_review': note,
        'actual_callability': ('package docstring only' if name == '__init__.py' else
                              'python -m cron.' + Path(name).stem if name.endswith('.py') else
                              'Windows script host entry; see direct primary launcher connection'),
        'adoption_decision': note['decision'], 'claude_dependencies': note['authority'],
        'windows_linux': note['platform'],
        'zeus_modules': ['src/codex_harness/' + p for p in modules],
        'zeus_equivalence': 'Architecture mapping only. Current Zeus module implementation was not semantically read in this partition; no equivalence/adoption claim.',
        'direct_imports': imports, 'tests_executed': [], 'test_limits': note['tests'],
        'license_status': 'Upstream license and linked debates/docs/OS behavior original sources not verified.',
        'duplicate_status': 'No generated or byte-equivalence claim. Check/run token/flag boilerplate has real behavioral divergence; primary bodies individually reviewed.',
        'remaining': [pending, 'Full transitive imports/effective config and caller chain remain partial',
                      'Authorized isolated runtime/OS/concurrency/crash/termination/result-collection regression not run',
                      'License/external originals and independent exact-revision Zeus adoption gates pending']})
assert sum(r['pinned_bytes'] for r in rows) == partition['bytes'] == 116848
write('semantic-notes.json', notes)
write('files.json', rows)
ranges_by_path = {
    'scripts/lib/atomic_json.py': [(44, 127)],
    'scripts/lib/paths.py': [(82, 148)],
    'scripts/lib/win_quiet.py': [(1, 80)],
    'scripts/lib/insight_index.py': [(369, 435)],
    'scripts/lib/ledger_compaction.py': [(1, 80)],
    'scripts/lib/brain_store.py': [(203, 265)],
    'scripts/lib/brain_autopush.py': [(140, 185)],
    'scripts/lib/insight_index_pollution_detector.py': [(146, 214)],
    'scripts/lib/golden_signals.py': [(182, 219)],
    'scripts/lib/hook_latency.py': [(69, 106)],
    'scripts/tests/test_scheduler_driver.py': [(235, 265)],
    'scripts/tests/test_unattended.py': [(209, 277), (356, 376)],
    'scripts/tests/test_unattended_e2e.py': [(1, 140)],
    'scripts/tests/test_cron_jobs.py': [(1, 115)],
    'scripts/lib/role_orchestrator.py': [(94, 139)],
    'scripts/lib/breaker.py': [(51, 99)],
    'scripts/lib/resident_store.py': [(140, 201)],
    'scripts/cli/resident.py': [(341, 405)],
    'scripts/cli/decisions.py': [(61, 88)],
    'scripts/cli/insight_index_pollution_detector.py': [(111, 158)],
}
support = []
for path, ranges in ranges_by_path.items():
    raw = (PINNED / path).read_bytes()
    lines = raw.splitlines(keepends=True)
    assert sha(raw) == inventory[path]['snapshot_sha256']
    assert all(1 <= lo <= hi <= len(lines) for lo, hi in ranges)
    support.append({'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
                    'pinned_sha256': sha(raw), 'line_count': len(lines),
                    'read_ranges': [{'start_line': lo, 'end_line': hi,
                                     'raw_range_sha256': sha(b''.join(lines[lo-1:hi]))} for lo, hi in ranges],
                    'read_extent': 'full' if ranges == [(1, len(lines))] else 'partial',
                    'coverage_role': 'supporting only; no primary promotion', 'tests_executed': []})
write('supporting-evidence.json', support)
pattern = '|'.join(Path(e['path']).stem for e in partition['paths'] if Path(e['path']).name != '__init__.py')
argv = ['rg', '-n', pattern, str(PINNED / 'scripts/tests'), str(PINNED / 'commands'),
        str(PINNED / 'skills'), str(PINNED / 'agents'), '--glob', '*.py', '--glob', '*.md']
proc = subprocess.run(argv, capture_output=True)
(OUT / 'caller-test-search.stdout').write_bytes(proc.stdout)
(OUT / 'caller-test-search.stderr').write_bytes(proc.stderr)
write('search-receipt.json', {'argv': argv, 'exit_code': proc.returncode,
                             'stdout_sha256': sha(proc.stdout), 'stderr_sha256': sha(proc.stderr),
                             'meaning': 'Discovery only. Only supporting ranges and primary full bodies were semantically read.'})
write('checkpoint.json', {
    'partition': partition['partition'], 'revision': manifest['revision'], 'scope_sha256': partition['scope_sha256'],
    'primary_total': 19, 'primary_bodies_read': 19, 'primary_bytes_read': 116848,
    'manifest_sha256_missing': [r['path'] for r in rows if r['matches_manifest_sha256'] is None],
    'manifest_missing_sha256_alternative': 'BAT/VBS exact raw Git blob SHA-1 matched manifest object; fresh pinned SHA-256 recorded without claiming a missing manifest SHA match.',
    'primary_remaining': [], 'body_coverage_complete': True, 'partition_complete': False,
    'adoption_ready': False, 'tests_executed': 0, 'supporting_records': len(support),
    'schedule_receipt_status': 'No live OS task registration or recurring execution state accessed. Source registration/cadence claims only.',
    'remaining': ['Per-file direct/transitive trace pending, runtime/concurrency/OS/worker collection execution0, license and independent adoption gates open'],
    'stop_reason': 'Bounded static primary scope complete. No upstream execution, shared coverage, source/runtime modification or commit/push.'})
(OUT / 'remaining.txt').write_text('', encoding='utf-8')
write('artifact-hashes.json', [{'path': p.name, 'sha256': sha(p.read_bytes())}
                              for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'artifact-hashes.json'])
print('19 primary bodies, 116848 bytes; manifest hashes match; upstream executions0;', len(support), 'supporting records')
