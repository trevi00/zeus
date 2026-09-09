# Baldrix cron 001 정적 검토

고정 범위 `baldrix:scripts/cron:001`의 **19개, 116,848바이트 전문**을 읽었다. manifest SHA-256·크기 대조와 파일별 의미·호출 연결은 `files.json`, 상세 판단은 `semantic-notes.json`에 기록했다. 상류 프로그램과 테스트 **실행은 0회**다. 실제 OS 예약 작업이나 운영 상태는 조회하지 않았다.

manifest의 BAT·VBS 두 행에는 `snapshot_sha256`이 없다. 두 파일은 원시 바이트의 Git blob SHA-1을 manifest object와 대조했고 새 SHA-256을 별도로 기록했다. 없는 manifest SHA-256을 일치로 표시하지 않았으며 나머지 17개는 제공된 SHA-256과 일치한다.

이 코드는 예약할 수 있는 내부 driver와 Windows 등록기를 제공한다. 파일 존재, CronJob 표, 작업 등록 성공 문구는 실제 예약·반복 실행·완료 영수증과 다르다. 신규 등록기는 pythonw를 직접 실행하지만 별도 VBS→BAT 경로는 고정 활성화 토큰을 삽입한다. 기본 등록기의 “토큰 미주입”도 상속 환경의 토큰을 제거하는 구현은 아니다. 공개 문자열·과거 operator 주석을 Zeus 승인으로 수용하지 않는다.

주요 수정 후보는 다음과 같다.

- **반복 실행 중복 방지:** driver의 lock은 조회 후 atomic overwrite이므로 배타적 획득이 아니다. 쓰기 실패에도 진행하며, stale 시간 이후 살아 있는 PID의 lock을 회수하고 release에서 소유권을 검사하지 않는다. 상태 쓰기 실패를 무시하면 성공 작업이 다시 실행될 수 있다. PG occurrence ID·lease·fencing과 완료 event를 결합해야 한다.
- **worker 종료·결과 수집:** driver timeout은 600초, 역할·수술 worker는 900초다. 중간 부모 timeout 뒤 자손 종료, artifact 수집 및 복구를 확인하는 계약이 없다. GC는 프로세스 안에서 시간 제한 없이 돌아 stale-window 계산의 전제를 깨뜨린다. 역할 cycle은 방금 등록한 작업 ID 대신 공용 queue와 원장 마지막 행을 사용한다. 이전·다른 작업이나 adhoc 결과가 계약 성공 판단에 섞일 수 있다.
- **수술 성공 판정:** `run_surgery_cycle`은 실패 종료 코드라도 dirty 파일이 있으면 커밋하고 메시지에 canary 통과를 쓴다. 지정 target 밖 변경도 담을 수 있고 Git add/cleanup 실패를 무시한다. 이 모듈이 merge하지 않는 경계는 확인했지만, 실패 작업을 통과 제안으로 남기는 문제는 별개다.
- **부분 mutation과 완료 기록:** brain push는 push 전에 ack·flag 소비를 하고 push 실패에도0이다. remote opt-in은 driver에만 있어 runner 직접 호출에는 없다. pollution 하위 명령은 일부 retract 실패에도0과 ready 소비를 반환하므로 상위도 성공 처리한다. flag를 작업 뒤 rename하는 순서는 배타적 claim이 아니며 UUID는 논리 반복 작업의 중복 키가 아니다.
- **압축과 원문 보존:** ledger scanner는 손상 JSON·비객체 행을 버린다. 이후 rewrite하면 순수 compactor의 보존 설명과 달리 그 원문은 archive에도 없다. archive append와 active 교체는 별도이며 live appender와의 잠금도 없다. PG 정본은 보존하고 파생 projection·retention을 별도로 설계해야 한다.
- **관찰을 성공으로 표시하는 경로:** brain 검사 오류가 durable QUIET으로, Git branch 조회 오류가 열린 branch 없음으로 바뀔 수 있다. 구형 checker는 quiet에서 이전 flag를 지우지 않는다. hook probe는 실제 hook을 상속 환경에서 실행하고 비정상 종료 경고를 시계열 기록에서 버린다. latency 10회 최대값, artifact 부재 기반 pollution 판정, 연속 실패 횟수는 제한된 관측이며 검증·자격·승인을 대신하지 않는다.

지원 자료 **20개**의 실제 읽은 구간과 원시 바이트 hash를 `supporting-evidence.json`에 남겼다. `win_quiet.py`와 `ledger_compaction.py`는 전문, 나머지는 부분 독해다. lock 테스트는 동시 시작이 아니라 순차 mock, 일부 unattended 검사는 소스 문자열 존재, e2e 지원 구간은 실제 ledger에 fake survey를 결합한 fixture다. 이 테스트들을 실행하거나 전체 인수로 주장하지 않았다. 검색 hit는 별도 발견 영수증이며 의미 검토 coverage가 아니다.

Zeus 대응 모듈은 scheduling/store/executor, audit·skill history, knowledge·research, monitoring의 설계상 연결로만 표시했다. 현재 Zeus 구현을 이번 범위에서 전문 검토하거나 동등성을 확정한 것은 아니다. 전체 GC/dashboard, promoter·ack, 실제 canary·역할·worker 전이, 운영 configuration, license 및 연결 원문은 미완료다.

Windows PowerShell/BAT/VBS와 Linux/WSL-native 등록을 구분했다. 후자의 등록 구현은 여기 없으며 Windows에서도 실제 설치·login/sleep·codepage·pythonw·process tree·동시 접근을 실행하지 않았다. `win_quiet`의 현재 프로세스 Popen 패치는 새 Python 자손의 코드에 자동 전파되는 정책이 아니다.

`checkpoint.json`의 본문 상태는 19/19다. 빈 `remaining.txt`는 primary 미독이 없다는 뜻이며, `partition_complete`와 `adoption_ready`는 false다. 전이 검토·실행·라이선스·독립 공동 검토의 남은 작업은 파일마다 유지했다. 이 한정 범위에서 중지한다.
