# U002 구현 기록: 실제 Claude 팀원 실행

Codex 명세 `docs/zeus/autonomy/design-002/README.md`(기준 `02efbd0`)의 구현이다. 계약 ID는
`INV-CLAUDE-WORKER-001`(`docs/contracts.md`). 분석·수용 기준·독립 검토·병합 판단은 Codex, 구현·테스트·실행
증거·PR 제출은 Claude 책임이다. 이 문서는 무엇을 만들었는지, 무엇을 실측했는지, **무엇을 통제하지 못했는지**를
같은 비중으로 적는다.

## 1. 범위

명시적으로 배정한 `worker:implementation`의 `implement` 작업을 실제 Claude Code로 실행하고, 기존 Redis six-W →
PG 예약·감사 → 실행 → 독립 증거 검사 → outbox 경로에 연결한다. 기존 Codex 기본 실행은 그대로 둔다. 무인 PR 반복,
카나리아, 운영 전환은 범위 밖이다(U004/U005).

## 2. 기존 경로 재사용

새 버스·조직 계층·원장을 만들지 않았다. 아래는 전부 기존 구현을 그대로 쓴다.

| 재사용한 것 | 그대로 쓰는 이유 |
|---|---|
| `Workflow.submit/claim/complete`, outbox, `organization.json` | 작업 수락·fencing·권한은 provider와 무관하다 |
| `InvocationLedger.reserve/settle/abandon` | 예약 키는 (bucket, task, generation, attempt, invocation)이라 provider 축이 없다 |
| U001 `Observer`/`Collector`, unconfirmed 표식, termination·reconcile | 진입 전후 경계의 의미가 provider마다 다르지 않다 |
| `Breaker`, `execution_fence`, `execution_recovery`, `evidence_inspection` | 차단·회수·독립 검사는 실행 주체와 독립이다 |
| `GitWorkspace.prepare/capture`, `completed_output`, `preflight` | worktree와 출력 검증은 공용 |
| `model_routing.select_model` | Codex 모델 정책은 **바꾸지 않았다** |

## 3. 설계

### 3.1 배정과 권한 (C01)

두 축이 모두 참일 때만 두 번째 provider가 실행한다.

- **Git 관리 정책** `src/codex_harness/resources/providers.json`: 어떤 (role, action, workload, read_only)
  조합이 **허용 가능한가**. 기본 provider는 `codex`.
- **호스트 설정**: 그중 무엇이 **켜져 있는가**. `ZEUS_CLAUDE_ASSIGNMENTS=worker:implementation/implement`,
  `ZEUS_CLAUDE_MODEL`, `ZEUS_CLAUDE_MAX_BUDGET_USD`(필수), `ZEUS_CLAUDE_TIMEOUT_SECONDS`·`ZEUS_CLAUDE_EXECUTABLE`(선택).

거절은 셋이며 모두 spawn 전이다.

1. 설정이 패키지 정책에 없는 조합을 지목하면 **설정 전체**를 거절한다(부분 수용으로 범위가 넓어지지 않게).
2. 허용·활성 조합인데 필수 통제(명시 모델, 예산 상한)가 없거나 형식이 틀리면 거절한다. **기본 provider로 대체하지
   않는다** — 대체하면 영수증이 실행하지 않은 provider의 이름을 달게 된다.
3. 활성 조합을 허용되지 않은 모양(read_only, 다른 workload)으로 쓰면 거절한다.

메시지·작업 details·모델 출력은 이 판단에 참여하지 않는다. 정책 버전·정책 digest·설정 digest가 예약 행
(`invocation_reservations.request.assignment`)과 실행 영수증에 함께 남는다.

### 3.2 모델 축 분리 (C04)

`select_model`은 그대로 Codex 모델만 정한다. Claude 모델은 설정에서만 오고(`model_source: explicit_setting`),
`model_pattern`이 Codex 모델 이름(`gpt-6-astra` 등)을 거절한다. 영수증의 `model_selection`은 provider 정책 버전을
달고 "Codex routing never names this provider's model"을 명시한다. 요청 모델 / provider가 보고한 모델 /
확인 불가는 `usage_record`에서 서로 다른 필드다.

### 3.3 어댑터 계약 (C02, C03)

`SUPPORT`에 `claude_cli` 행과 **세 번째 상태 `unconfirmed`**를 추가했다.

| 옵션 | app_server | claude_cli | 근거 |
|---|---|---|---|
| model / timeout / output_schema | supported | supported | |
| max_budget_usd / permission_mode | (없음) | supported | CLI가 직접 받는다 |
| read_only | supported | **unconfirmed** | 도구·권한 제한이라는 기제는 있으나 그 효과를 이 하네스가 검증하지 않았다. 참으로 요청하면 거절하고, 거짓이면 주장하는 바가 없으므로 수용한다 |
| session_resume | (없음) | unsupported | native resume는 이번 범위가 아니다 |
| system / temperature / max_output_tokens / response_format | unsupported | unsupported | 있으면 이름과 함께 거절 |

프로세스 입출력:

- 프롬프트는 **stdin**으로만 간다. argv에도 shell 문자열에도 넣지 않는다. 기록되는 명령에서는 schema·settings처럼
  비밀이 섞일 수 있는 값을 digest로 치환한다.
- stdout/stderr를 각각 별도 스레드로 **동시에** 비운다. 줄 바이트 한도, 전체 바이트 한도, 큐 깊이가 있고, 한도를
  넘어도 읽기는 EOF까지 계속한다(자식이 파이프에 막히지 않게). `POLICY.claude_line_bytes`(1 MiB),
  `claude_stream_bytes`(8 MiB), `claude_event_queue`(2000), `claude_events_retained`(400).
- stdin은 쓰기 전용 스레드가 담당한다. stdin을 읽지 않는 자식은 그 스레드만 막고 본체는 계속 돈다.
- monotonic deadline 하나가 실행 전체를 덮고, 이벤트가 없어도 tick·cancel이 계속 동작한다.
- 설치된 CLI의 `--help`에서 **쓰려는 모든 옵션의 존재를 확인**하고, 없으면 진입 전에 거절한다.

### 3.4 초기화도 외부 효과 (C05)

`enters_on_open` 축을 뒀다. Codex의 `AppServer`는 `__enter__`가 곧 프로세스 시작이라 그 시점이 진입이고(기존 동작
유지), Claude 어댑터는 `__enter__`가 검증만 하고 `run()`이 `Popen` **직전에** `on_enter()`를 부른다. 진입 후에는
hook·초기화가 이미 작업 트리를 건드렸을 수 있으므로 어떤 예외도 "진입 안 함"으로 읽지 않는다. 예약·필수 감사·
unconfirmed 표식은 진입 전에 함께 커밋되고, 진입 후 실패는 U001의 termination·blocked·reconcile을 그대로 탄다.

### 3.5 프로세스 종료 (C06)

자기가 만든 트리만 종료하고 **종료를 증명**한다. POSIX는 `killpg` 후 프로세스 그룹이 비었는지 최대 10초 폴링하고,
Windows는 `taskkill /T /F`의 반환값(0 또는 128=이미 없음)과 부모 종료를 함께 본다. 증명 실패는 unknown이며
`ContractError`로 올라가 blocked가 된다(다음 실행 불가). 전역 kill·운영 서비스 재시작은 없다.

**리더 스레드가 읽는 중인 파이프는 닫지 않는다.** 이건 구현 중 실제로 밟은 결함이다(§5.3).

### 3.6 이벤트와 결과 (C03)

provider 원본 줄을 Codex 알림 모양으로 위장하지 않는다. `domain/provider_stream.py`가 provider별 reader를 두고,
Claude 이벤트의 `method` 라벨은 `claude/<원본타입>[/<subtype>]`으로 네임스페이스가 붙는다. 정규화 이벤트는 원본
줄(`raw`)을 옆에 달고 다닌다.

| 관측 | 결과 |
|---|---|
| 정상 구조화 출력 | `accepted` (단, schema는 **여기서** 검증) |
| exit 0, 출력 없음 | `empty_answer` |
| 도구만 돌고 출력 없음 | `tool_only` |
| terminal 없음 / 상충 terminal / 잘린 스트림 / 시작 실패 | `provider_failure` (`claude-provider-*`) |
| `is_error` 결과, budget 종료, max turns | `provider_failure` (사유별 cause) |
| schema 불일치·잘못된 JSON | `invalid_output` (`claude-output-*`) |
| 동일 terminal 재전달 | redelivery로 세고 결과를 바꾸지 않는다 |

잘못된 줄은 개별적으로 세고 격리하며 뒤따르는 정상 terminal을 막지 않는다.

### 3.7 usage와 비용 (C04)

**terminal result 메시지에서만** 읽는다. assistant 메시지와 재전달·부분 메시지는 같은 작업의 수를 다시 들고 있으므로
더하지 않는다. `parts`에 `input_tokens/output_tokens/cache_creation_input_tokens/cache_read_input_tokens`를 각각
남기고 `basis: result_total_including_cache`로 무엇의 합인지 밝힌다. 없는 값은 null이며 0이 아니다. provider가 보고한
비용은 `cost_source: provider_estimate`로, **청구액이 아니라고** 명시한다.

### 3.8 세션 (C07)

task/attempt마다 새 UUID를 `--session-id`로 준다. `--continue`·마지막 세션 자동 선택은 쓰지 않고 native resume는
`session_resume: unsupported`로 선언한다. checkpoint에 provider, provider_identity, provider_session_id, transport,
agent, task, generation, attempt, invocation, basis revision, workspace_identity, policy_digest, config_digest를
묶는다. 복구는 provider와 workspace가 같을 때만 채택하며(`bound()`), provider 키가 없는 옛 기록은 Codex 기록으로
읽는다(그게 사실이므로). 새 attempt는 기존 context compiler로 권위 있는 checkpoint/artifact를 받는다.

### 3.9 통신 (C08)

provider 스트림은 실행 내부 데이터다. six-W 메시지는 기존 `Workflow.complete`가 검증된 sender/recipient로 만든다.
모델이 출력한 six-W JSON은 결과 본문 안의 **텍스트**일 뿐 권한이 없다.

### 3.10 환경과 유효 설정 (C09, C11)

자식 환경은 **허용 목록**으로 만든다. Zeus의 PG/Redis 자격증명과 운영자 설정은 넘기지 않고, 넘기지 않은 이름만
기록한다(값은 어디에도 기록하지 않는다). 인증은 호스트가 이미 쓰는 방식 그대로 두며, 재현성을 이유로 구독 인증을
API 키로 바꾸지 않는다.

호스트의 기존 전역 권한 설정 파일은 **읽지도 고치지도 않는다**. 이번 실행의 도구 권한은 `--settings`에 실린 일회성
JSON 하나뿐이고, 그 값은 명령 기록에서 digest로 치환된다.

provider가 시작 시 보고한 것(`system/init`)을 `effective_configuration`으로 남긴다. 이것이 "통제가 실제로 걸렸는가"의
근거다(§5.4에 실측값).

## 4. 바뀐 파일

| 파일 | 성격 | 내용 |
|---|---|---|
| `src/codex_harness/resources/providers.json` | 신규 | Git 관리 실행 정책 |
| `src/codex_harness/domain/providers.py` | 신규 | 정책·설정 파싱과 provider 선택, 세 가지 거절 |
| `src/codex_harness/domain/provider_stream.py` | 신규 | provider별 이벤트 reader (Codex는 기존 로직 그대로 이동) |
| `src/codex_harness/adapters/providers.py` | 신규 | 패키지 정책 로드 + 호스트 설정 결합 |
| `src/codex_harness/adapters/claude_cli.py` | 신규 | Claude Code CLI 전송, 프로세스·스트림·종료·분류 |
| `src/codex_harness/adapters/executor.py` | 수정 | provider 선택, 진입 시점 축, provider별 stream, 세션 결속 |
| `src/codex_harness/domain/invocation.py` | 수정 | `claude_cli` 지원표, `unconfirmed` 상태, provider별 usage |
| `src/codex_harness/domain/policy.py` | 수정 | 스트림 한도 4개 |
| `src/codex_harness/application/invocation_ledger.py` | 수정 | usage source 허용 목록을 도메인 상수로 |
| `src/codex_harness/application/breaker.py` | 수정 | provider 실패 판정을 `-provider-` 접미 규칙으로 |
| `src/codex_harness/adapters/execution_output.py` | 수정 | 출력 실패 cause에 provider 라벨, 어댑터 관측 도구 사용 수용 |
| `scripts/claude_real_call.py` | 신규 | C10 실측 러너(픽스처 모드 포함, 호출 상한 자체 강제) |
| `tests/claude_protocol_child.py` | 신규 | 프로토콜 시험 자식(장애 주입 도구) |
| `tests/test_claude_assignment.py` / `test_claude_cli_process.py` / `test_claude_execution.py` | 신규 | C01–C09 |
| `docs/contracts.md` | 수정 | `INV-CLAUDE-WORKER-001` |

## 5. 검증

### 5.1 수용 기준별 대응

| ID | 구현 위치 | 테스트 | 실제 환경 |
|---|---|---|---|
| C01 | `domain/providers.py`, `resources/providers.json`, `Executor._run` | `test_claude_assignment.py` 19건, `test_claude_execution.py`의 배정 4건 | Windows 실제 호출 2회가 이 경로로 선택됨 |
| C02 | `claude_cli._command`/`_write_prompt`/`_drain` | `test_c02_*` 3건 (한글·공백 경로, stdin hash 일치, argv 미노출, 환경 차단) | 실제 호출: stdin 3355 bytes, stderr 0, 프롬프트 argv 노출 0 |
| C03 | `claude_cli._result`/`_provider_failure`/`_normalize`, `completed_output` | `test_c03_*` 17건(11개 시나리오 파라미터 포함) | 실제 호출: terminal success, `answer_source=structured_output`, 잘못된 줄 0 |
| C04 | `domain/invocation._claude_usage` | `test_c04_usage_comes_only_from_the_terminal_message_and_names_its_parts`, `test_codex_routing_is_unchanged...` | 실제 호출 usage parts와 비용 추정치 기록 |
| C05 | `Executor._run`의 예약·감사·표식·`mark_entered` | `test_c05_*` 4건 (사전 실패 3종 spawn 0, 사후 실패 blocked, provider 교체가 차단을 지우지 않음) | 실제 호출: 예약→감사→settle 순서로 PG에 기록 |
| C06 | `claude_cli._terminate`/`_group_empty`/루프 | `test_c06_*` 7건 (무출력·stdin 미소비·포화·긴 줄·lease 상실·취소·자손 종료·미확인 종료) | Windows 실측(자식·손자 실제 종료 확인). WSL은 §5.2 |
| C07 | `Executor._run`의 `bound()`와 checkpoint state | `test_c07_*` 4건 | 실제 호출: 요청/보고 session id 일치, checkpoint에 provider 결속 |
| C08 | `Workflow.complete` + `claude_settings` 경계 | `test_the_models_own_six_w_output_carries_no_authority`, `test_a_message_that_asks_for_a_provider_changes_nothing` | 실제 호출: `task.result` 1건만 발행, 실제 Redis 네임스페이스로 전달 |
| C09 | `_StreamState.observe`(redaction), `_provider_failure`(digest만) | `test_c09_*` 2건 | 실제 호출 stderr 0 bytes |
| C10 | `scripts/claude_real_call.py` | 픽스처 모드 1회 | **Windows 실제 호출 2회 성공**, WSL 미실행(§5.5) |

### 5.2 프로세스 경계의 호스트별 실측

`tests/test_claude_cli_process.py`는 실제 자식 프로세스를 띄우므로 Windows와 WSL에서 각각 돌린다. 이 파일의 자식은
프로토콜 시험용이며 모델 실측이 아니다(어댑터가 launcher를 기록해 영수증에서 구분된다).

### 5.3 구현 중 발견해 고친 결함

1. **확인되지 않은 종료에서 실행이 행에 걸렸다.** `run()`의 정리 단계가 리더 스레드가 `readline()`에 묶여 있는 동안
   파이프를 닫아, 파이프 버퍼 락을 기다리며 자식이 살아 있는 내내 멈췄다. 프로토콜 스위트 전체가 625초 걸리던 원인이
   이것이었고, 스레드가 끝난 파이프만 닫도록 고친 뒤 **38.6초**가 됐다. 운영상 의미는 더 크다: 종료를 증명하지 못한
   실행이 unknown을 보고하는 대신 provider 수명만큼 멈춰 있었을 것이다.
2. 비어 있는 결과가 `invalid_output`으로 뭉개졌다. terminal이 출력 자체를 담지 않은 경우와 출력이 망가진 경우는 다른
   관측이므로 `empty_answer`/`tool_only`로 갈랐다.
3. 이물 stderr가 실패 dict에 실려 바깥(작업 행·notice)으로 나갈 수 있었다. digest와 바이트 수만 나가고, 축약·redaction된
   꼬리는 접근 제한 영수증에만 남긴다.
4. **실제 호출 상한이 호스트별이 아니라 디렉터리별이었다.** Windows 2회가 WSL 몫까지 써버려, WSL 실행이 잘못된 사유로
   거절됐다. 호스트별 상한(기본 2)과 전체 상한(기본 4)으로 갈랐다. WSL 실행이 이 결함을 드러냈다.
5. **Linux에서 PATH가 interop으로 Windows 실행 파일에 닿는데 러너가 그걸 받아들였다.** 그대로 뒀다면 WSL 영수증이
   Windows 프로세스를 잰 결과를 Linux 측정처럼 보이게 했을 것이다. 이제 `executable_kind`로 판별해 거절하며,
   `--allow-interop`을 명시해야만 실행되고 그때 영수증이 무엇을 뜻하는지도 함께 남는다.

### 5.4 실제 Claude 호출 (Windows)

`docs/zeus/evidence/claude-real-call-001/` (호출별 영수증, 러너가 상한 2회를 스스로 강제한다).

| 항목 | 1회차 | 2회차 |
|---|---|---|
| CLI / 모델 | 2.1.269 / `claude-fable-5-1` (보고 모델 일치) | 동일 |
| 소요 / 턴 / 도구 | 23.2s / 8턴 / 7건 | 22.1s / — |
| provider 보고 비용(추정) | USD 0.339 | USD 0.257 |
| usage (합, 캐시 포함) | 49,240 | 기록됨 |
| 러너 독립 측정 | 작업 전 `3 failed` → 작업 후 **`3 passed`**, 변경 파일 `slug.py`만, 테스트 파일 무변경 | 동일 |
| PG / six-W / 관측 | task succeeded, `task.result` 1건, 관측 18건 수집 | 동일 |

**자기보고와 실측의 분리가 실제로 갈렸다.** 모델은 테스트를 돌렸다고 보고했지만 그 주장은 산문이 섞인 문자열이라
증거 검사기가 기계적으로 재생하지 못했다(1회차 `verified_mismatch 1`, 2회차 `not_checked 2`, 두 번 다 verdict
`incomplete`). 하네스는 그 주장을 증거로 승격하지 않았고, 통과를 말하는 근거는 **러너가 직접 돌린 pytest**다.

### 5.5 통제한 것과 통제하지 못한 것 (2회차 `system/init` 실측)

| 상속 경로 | 결과 |
|---|---|
| MCP 서버 | `mcp_servers: []`, 오류 0 — `--strict-mcp-config`로 차단됨 |
| 플러그인 | `plugins: []`, 오류 0 |
| 훅 | 스트림에서 hook 이벤트 0건 |
| 도구 집합 | `Bash, Edit, Glob, Grep, Read, Write` + `StructuredOutput` — `--tools`가 걸렸고 `Task`는 없다(부에이전트 호출 불가) |
| 권한 모드 | `acceptEdits` (요청대로) |
| 인증 | `api_key_source: "none"` — **구독 인증 그대로**, API 키로 바뀌지 않았다 |
| **스킬·커스텀 커맨드·서브에이전트 정의** | **차단되지 않았다.** `slash_commands: 53`, `agents: 5`가 여전히 로드된다 |
| CLAUDE.md | 로드된다(`memory_paths` 보고). 컨텍스트이지 실행이 아니다 |
| 관리자(managed) 설정 | 적용된다 |

`--setting-sources ""`는 설정 파일 계층(따라서 MCP·플러그인·훅)을 제외했지만 홈의 스킬·커맨드·에이전트 정의까지
막지는 못했다. 그것까지 막는 건 `--bare`인데, `--bare`는 구독 인증을 읽지 않고 `ANTHROPIC_API_KEY`를 요구하므로
**재현성을 이유로 인증 방식을 몰래 바꾸지 않는다**는 명세에 따라 쓰지 않았다. `Task`를 거부해 서브에이전트 실행
경로는 닫혀 있지만, 로드된 커맨드·스킬 정의 자체는 남는다. 이 한 칸이 이번 범위에서 통제하지 못한 경로다.

### 5.6 실행하지 않은 것

- **WSL 실제 Claude 호출**: WSL(Ubuntu 26.04)에 Claude Code가 설치돼 있지 않다(로그인 셸에서 `claude: command not
  found`, node 없음). PATH가 interop으로 `/mnt/c/.../claude.exe`에 닿기는 하지만 그건 Windows 프로세스를 재는 것이라
  Linux 프로세스 경계의 증거가 되지 않는다. 러너가 이를 `windows_binary_via_interop`로 판별해 거절하고 그 사유를
  영수증(`wsl-ubuntu-26.04-not-executed-receipt.json`)에 남긴다. WSL에 설치하는 일은 사용자 기기 변경과 계정 인증이
  필요해 임의로 하지 않았다. **필요하면 Codex/사용자가 결정할 항목이다.** 프로세스·스트림·종료 경계 자체는 WSL에서
  프로토콜 자식으로 실측했다(§5.2).
- 실제 모델 호출은 호스트당 2회 상한 안에서 Windows 2회만 했다. 러너가 영수증 개수로 상한을 강제한다.
- 네트워크 게시·제품 배포·실금전 작업·운영 교체·전체 무인 반복은 범위 밖이며 하지 않았다.
- Windows에서 임시 작업 디렉터리 삭제가 완전히 끝나지 않는다(`workdir_removed: false`). 시스템 임시 디렉터리 안이라
  증거 디렉터리는 깨끗하지만, 사실대로 영수증에 남긴다.

## 6. Codex에 보고하는 설계 판단

1. **지원 상태를 셋으로 늘렸다**(`supported`/`unsupported`/`unconfirmed`). `read_only`는 기제는 있으나 효과를 검증하지
   않았으므로 "지원한다"고도 "무시한다"고도 말할 수 없었다. 참으로 요청하면 거절한다.
2. **진입 시점을 provider별 축으로 뒀다**(`enters_on_open`). Codex는 `__enter__`가 곧 외부 효과라 기존 위치가 옳고,
   Claude는 `Popen` 직전이 옳다. 두 위치를 하나로 합치면 한쪽이 틀린다.
3. **비어 있는 결과와 tool-only를 `invalid_output`에서 분리했다.** Codex 경로는 "빈 agent 메시지 텍스트"를 보고,
   Claude 경로는 "terminal이 출력 필드를 아예 안 담음"을 본다. 서로 다른 관측이라 다른 이름을 줬다. 어느 쪽도 성공이 아니다.
4. **provider 이벤트를 Codex 모양으로 정규화하지 않았다.** 대신 reader를 provider별로 뒀고 라벨에 `claude/`를 붙였다.
   기존 Codex 진행 기록 동작과 테스트는 그대로다.
5. **호스트 권한 설정 파일을 손대지 않는 대신 일회성 `--settings` JSON을 썼다.** 공백이 든 권한 규칙이 옵션 값 분리에
   깨지지 않고, 실행이 끝나면 남지 않는다.
6. **실제 호출 상한을 러너가 강제한다.** 기억이나 규율이 아니라 영수증 개수로 센다. 세 번째 Windows 호출은
   `not_executed_reason`으로 거절된다.
7. **`--setting-sources ""`의 한계를 §5.5에 실측으로 적었다.** 통제됐다고 주장할 수 있는 것과 아닌 것을 provider 자신의
   보고로 갈랐다. 스킬·커맨드·에이전트 정의까지 막으려면 인증 방식을 바꿔야 하므로, 결정이 필요하면 Codex가 한다.
