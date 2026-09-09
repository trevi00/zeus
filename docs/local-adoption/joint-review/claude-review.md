## 리뷰 결과 (Claude 독립 검토)

읽은 범위: `AGENTS.md`, `docs/contracts.md`, `docs/local-adoption/hardening.md`, `supervisor.py`, `adapters/{deployment,configuration,store,executor,bus,git,commands}.py`, `application/{releases,service,workflow,scheduling,audit_gate}.py`, `cli.py:76-119`, `compose.yaml`, `resources/001.sql`, `scripts/{setup,supervise,monitor}.py`, 신규 테스트(`conftest`, `test_release_runner`, `test_supervisor`, `test_dispatch_fairness`). 전수 검토가 아니라 세 초점(배포/supervisor 크래시 복구, 이식성, 큐 진행성)에 한정했다.

---

### 확정 결함 (소스 근거 있음)

**1. `_check`가 "후보 결함"과 "실행 인프라 실패"를 구분하지 않아 정상 후보가 영구 거부됨 — 최우선**
- 근거: `deployment.py:25-33` (`except Exception` → `passed:False`), `:78-80`, `:88-90`(둘 다 기본 `timeout=300`), `_reject_remaining`(`:43-53`)이 `releases.verify` 호출 → `releases.py:98-99`에서 `status="rejected"` 확정. 재검수 불가: `releases.py:75`는 `{candidate, reviewed}`만 허용하고, `propose`는 동일 identity에 기존 레코드를 그대로 반환(`:54-56`).
- 트리거: 콜드 캐시에서 `uv sync --frozen`(의존성에 `fastembed`→onnxruntime/numpy, `pyproject.toml:7`)이 300초 초과, 또는 incumbent+candidate 두 스위트 각각 300초 초과(하드닝 문서 기준 Windows 전체 617개 **170초**, 여기에 canary는 `HARNESS_INTEGRATION=1` 강제 `deployment.py:82`), 또는 docker 데몬 재시작·일시적 네트워크.
- 결과: 검수까지 통과한 개선 후보가 **영구 rejected**. rework 메시지도 생성되지 않으므로(rework는 `executor.py:577-606`의 리뷰 거부 경로에만 존재) 해당 improvement 루프가 조용히 종료된다. 자기개선 진행성 손실이 가장 크다.
- 수정: `_check`에서 `TimeoutExpired`/`OSError`(도구 부재)를 `passed=False`가 아니라 `retryable_error`로 분리. 재시도 가능 오류면 `releases.verify`를 호출하지 말고 릴리스를 `reviewed`로 유지, 큐 행만 재시도 예약. install/tests 타임아웃을 `POLICY`로 분리(현재 300초는 실측 170초 대비 여유가 없음).
- 회귀 테스트: `test_release_runner.py`에 케이스 추가 — `_check`가 install 단계에서 `subprocess.TimeoutExpired`를 던지도록 하고, ① `releases` 상태가 `reviewed`로 유지되고 ② `verify`가 호출되지 않았으며 ③ 두 번째 `run()`에서 정상 승격되는지 확인. 현재 `test_failed_prerequisite_stops_downstream_execution:50`은 `rejected`를 단정하므로 이 구분이 없다는 점 자체가 증거다.

**2. `release_queue`에 재시도 경로가 없어 verified 릴리스가 영구 정체**
- 근거: `supervisor.py:87-88`은 `status == "queued"`만 집는다. `:95-99`는 예외를 `{"status":"failed"}`로 저장하고, `deployment.py:37-41`도 결과 상태를 그대로 기록. `release_queue`에 `queued`를 쓰는 곳은 `executor.py:574`(conductor 승인 시 1회)뿐.
- 트리거: `_promote` 중 `git.merge`가 `git.py:138`의 `require(not status --porcelain)`에 걸림(메인 워크트리 dirty — **지금 이 작업 트리 상태가 정확히 그렇다**), `gh` 일시 오류, docker 오류.
- 결과: 릴리스 레코드는 `verified`(+이미지 빌드 완료)인데 큐 행은 `failed`로 고정 → 다시 승격 시도되지 않음. `monitor()`는 active 배포만 보므로 아무도 인지하지 못한다. 배포 파이프라인이 조용히 멈춘다.
- 부수: `supervisor.py:99`가 실행 **전** 스냅샷 `row`로 `{**row, ...}`를 덮어써 `ReleaseRunner.run`이 쓴 필드를 잃는 lost update.
- 수정: 큐 행에 `attempt`/`next_attempt_at`을 두고 재시도 가능 실패는 `queued`로 복귀(backoff, max_attempts). `deploy_queued`가 "레코드는 verified인데 active가 아닌" 릴리스도 회수. supervisor의 중복 기록 제거(러너가 이미 기록).
- 회귀 테스트: MemoryStore + 첫 tick에서 `RuntimeError`를 던지고 두 번째에 성공하는 러너 stub → 두 번째 `deploy_queued`에서 승격되고 큐 행이 `active`에 도달하는지.

**3. `execute_one`에는 `decide_one`에 추가된 lease 상실 가드가 없어 에이전트 프로세스가 죽음**
- 근거: `executor.py:414-415`는 `except` 블록 안에서 곧장 `fail_execution` 호출 → `workflow.py:151`의 `_owned`가 `ContractError`를 던지면 그대로 전파. 반면 `decide_one`은 `:509-524`에서 정확히 이 경우를 처리한다(이번 원자성 작업의 산물). `cli.py:104-113`의 실행 루프에는 `try`가 없고, `compose.yaml:30-59`에 `restart:` 정책도 없다.
- 트리거: Postgres 순간 단절로 heartbeat(`_run`의 20초 on_tick, `executor.py:219-221`)가 실패해 lease 만료 → 이후 작업 실패 → `fail_execution`이 ContractError.
- 결과: 에이전트 컨테이너 종료. 더 나쁜 것은 `:422-431`의 diagnose 관측치가 기록되지 않아 **incident→recurrence hook 경로 자체가 소실**(INV-RECURRENCE-001 관점의 진행성 손실). supervisor가 backlog를 보고 다시 깨우면 같은 실패를 반복할 수 있다.
- 수정: `decide_one:515-524`와 동일한 가드를 `execute_one`에 미러링하고, 실패 커밋과 diagnose 관측치를 **같은 트랜잭션**으로 묶는다(현재는 별도 트랜잭션 2개라 중간 크래시 시 관측치 유실).
- 회귀 테스트: MemoryStore로 실행 중 `generation`/`lease_owner`를 교체한 뒤 실패 유발 → `execute_one`이 예외를 던지지 않고 retry 마커를 반환하는지, 그리고 커밋 실패 주입 시 실패 기록과 diagnose 행이 **둘 다 없는지**(`test_decision_atomicity.py`의 실패 주입 패턴 재사용).

**4. `monitor()`의 1회성 프로브 실패가 즉시 롤백을 유발하고, 롤백이 연구/감사 큐를 영구 정지시킴**
- 근거: `deployment.py:186-190` — `docker run ... codex --version`(timeout 45초) 한 번 실패로 무조건 `releases.rollback`. 롤백은 `releases.py:151-154`에서 `research_control.activation`을 `paused`로 전환. 그 결과 `scheduling.py:33-35`가 0을 반환해 감사 스케줄링이 전면 중단되고, `audit_gate.py:39-42`가 모든 adoption을 거부한다. `releases.py:26-29`의 `reconcile_audits`는 pause를 절대 되돌리지 않는다.
- 트리거: Docker Desktop 콜드 스타트/이미지 레이어 로드로 45초 초과, 데몬 재시작 중 supervisor의 60초 유지보수 tick(`supervisor.py:138-148`).
- 결과: 건강한 릴리스가 롤백되고 컨테이너가 이전 이미지로 교체되며, 자기개선/감사 큐가 정지. 해제 조건은 `audit_lifecycle_version==1` 후보의 새 승격뿐인데, 결함 1·2가 그 경로를 막고 있어 사실상 복구 불가 조합이 된다.
- 수정: health 레코드에 연속 실패 카운터를 두고 N회 연속 실패에서만 롤백. `TimeoutExpired`/데몬 부재는 `unhealthy`가 아니라 `unknown`으로 처리(INV-METRIC-001의 "증거 없음은 unknown"과도 정합).
- 회귀 테스트: 첫 프로브만 실패하고 두 번째는 성공하는 `_check` stub → 롤백이 일어나지 않고 `research_control`이 `active`로 남는지. 연속 실패 시에는 롤백되는지도 함께.

---

### 검증 필요 가설 (런타임 확인 전 단정 불가)

**5. desired 이미지를 태그가 아닌 순수 image ID로 Compose에 주입**
- 근거: `deployment.py:101-103`이 `docker image inspect --format {{.Id}}` 결과(`sha256:<hex>`)를 `images` 버킷에 저장 → `supervisor.py:128,170`이 그대로 `HARNESS_AGENT_IMAGE`로 전달 → `compose.yaml:33`의 `image:` 필드. `sha256:<hex>`는 유효한 *named reference*가 아니므로 Compose의 참조 파싱/`ps --format json`의 `Image` 문자열 정규화 동작에 의존한다.
- 잠재 결과: (a) 매 tick `up --no-build` 실패 → `supervisor.py:171-172`가 예외 → 5초 주기 오류 루프, 또는 (b) `row["Image"] != desired`가 항상 참이 되어 `replace`가 매번 발동, 컨테이너 무한 재생성.
- 확인 방법: `HARNESS_AGENT_IMAGE=sha256:...`로 `docker compose up -d --no-build conductor` 후 `docker compose ps --format json`의 `Image` 값 비교(1회 실행이면 충분).
- 결과와 무관하게 권장: `images` 레코드에 `image`(태그 `codex-harness:candidate-<rev>`)와 `image_id`를 **둘 다** 저장해 Compose에는 태그를, 동일성 검증(`monitor()`의 `:201-203`)에는 ID를 쓴다.

**6. canary 테스트가 운영 DB를 가리키고, advisory lock이 DB 전역이라 상호 간섭**
- 근거: `deployment.py:82-84`가 `HARNESS_DATABASE_URL = self.service.store.dsn`(운영 DSN)로 두 스위트를 돌린다. `store.py:83-85`는 모든 트랜잭션이 `pg_advisory_xact_lock(734219)` + `lock_timeout=10s`. `conftest.py:23`의 격리는 **schema** 단위이므로 lock은 여전히 공유된다.
- 잠재 결과: canary 실행 중 라이브 에이전트/supervisor와 락 경합 → 양쪽 어디서든 lock timeout → 결함 1을 통해 정상 후보의 영구 거부, 또는 결함 3을 통한 에이전트 종료.
- 확인 방법: 하네스 가동 중 canary 테스트를 실제로 병렬 실행해 `lock_timeout` 오류 발생 여부 관측(하드닝 문서의 "동시 실행" 검증은 두 OS 테스트 간 병렬이지 라이브 하네스와의 병렬이 아님).
- 수정: advisory key를 search_path/스키마에서 파생시키거나, canary 전용 데이터베이스 DSN을 사용.

**7. Windows 바인드 마운트 경로 정규화 불일치 (이식성, 저비용 수정)**
- 근거: `configuration.py:76-77`은 의도적으로 `.as_posix()`로 정규화하는데, `deployment.py:160-161`의 `file_canary`는 `source={root}`(기본 `%TEMP%`, 역슬래시)와 `source={self.auth}`를 그대로 `--mount` CSV에 넣는다.
- 잠재 결과: Windows 호스트에서 모델 canary만 실패 → 정책상 `cli_file_task` 실패 → 결함 1 경로로 후보 영구 거부.
- 수정: `Path(...).as_posix()` 적용, 캐너리 디렉터리를 `%TEMP%`가 아니라 `runtime_dir()` 아래(이미 compose에 공유되는 경로)로.

---

### 최근 3개 변경에 대한 판정

- **결정 원자성(`_commit_decision`)**: 회귀 없음. `_owned`가 트랜잭션 진입 직후(`executor.py:530`)와 커밋 직전(`:607`) 모두 호출되고, incident/release review/hook/outbox가 모두 `transaction=tx`로 전달된다(`service.py:43`, `releases.py:53,67`). 남은 틈은 두 곳: (a) 결함 3의 `execute_one` 비대칭, (b) `decide_one:524`의 bare `raise`가 `serve()`에 핸들러 없이 전파되는 경로(행이 사라진 경우에만 도달하므로 우선순위는 낮지만, 같은 프로세스 종료 경로다).
- **선행 단계 fail-fast**: 의도(미실행 단계를 `not_run`+사유로 기록)는 INV-RELEASE-001에 정합하고 구현도 맞다. 다만 **`_reject_remaining`이 종결적 `verify`를 호출**하는 점이 결함 1의 회귀를 만든다 — 인프라 실패까지 후보 결함으로 확정한다. 이것이 이번 변경이 도입한 가장 실질적인 회귀다.
- **큐 공정성**: `cli.py:104-109`의 교대 자체는 정확하고 `test_dispatch_fairness.py`가 한쪽 비었을 때까지 커버한다. 회귀는 발견하지 못했다. 다만 이 수정은 **프로세스 내부** 공정성만 다루고, 실제 기아 원인은 `POLICY.max_active_executions = 2`(`policy.py:8`)가 6개 에이전트의 `tasks`+`decisions_pending`을 **전역으로** 합산한다는 점이다(`workflow.py:62-65`, `executor.py:438-441`). 워커 두 개가 600초 lease를 잡으면 어느 큐를 먼저 보든 모든 lead의 review/diagnose가 전역으로 막히고, 강제 종료 후에는 만료 전까지 슬롯이 점유된다. decision 슬롯을 별도 카운트하거나 최소 1슬롯을 예약하는 후속 수정을 권한다.

부수 관측(수정 제안 없이 기록만): `serve()`가 `ContractError/JSONDecodeError/KeyError` 외 예외를 잡지 않아(`cli.py:101`) `workflow.handle` 중 psycopg 오류 등이 나면 dead-letter 없이 프로세스가 죽고, 메시지는 60초 후 xautoclaim으로 재전달되어(`bus.py:84-85`) supervisor의 backlog 기동(`supervisor.py:167`)과 함께 재시작 루프가 될 수 있다. 결함 3과 근본 원인(실행 루프의 예외 경계 부재)이 같다.

Codex의 독립 findings를 보내주면 대조해서 중복/상충을 정리하고, 구현 우선순위(제안: 1 → 3 → 2 → 4, 이후 5·6·7)를 합의하겠다.