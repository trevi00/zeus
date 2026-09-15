# 환경 준비 신뢰성: 준비 완료를 소켓이 아니라 응답에 결속

Codex 명세 `docs/zeus/reviews/claude-work-018/READINESS-FOLLOWUP.md`와 PR #73 수용 검토의 후속 지시를 구현한다.
분석·수용 기준·독립 검토는 Codex, 측정·구현·증거·PR은 Claude. 관련 #18 #20.

**먼저 쟀고, 그 다음 고쳤다.** 기한을 늘리거나 실패를 skip으로 돌리지 않았다.

## 1. 무엇이 실패했다고 기록돼 있었나

세 가지 증상이 원장에 있었고, 같은 원인으로 확정되어 있지 않았다.

| # | 어디서 | 증상 |
|---|---|---|
| A | WSL, 환경 증거 실행 | `Verification endpoint 127.0.0.1:NNN not connectable after 30.0s: ConnectionRefusedError` |
| B | CI, `test_postgres_pause_is_not_a_clock_step` | `server closed the connection unexpectedly` |
| C | CI, `test_host_probe_never_falls_back_to_public_tasks` | `FATAL: the database system is starting up` |

A는 **포트가 열리지 않는** 문제다. B와 C는 **포트가 열린 뒤** 벌어지고, 당시 준비 판정(`_await_endpoint`)은 TCP 연결만
보므로 **둘을 아예 볼 수 없었다.**

## 2. 측정 (`scripts/readiness_probe.py`, `docs/zeus/evidence/readiness-004/`)

반복 계획을 **실행 전에 코드에 고정**했다: 조건 2종(`standalone`, `after_teardown`) × 6회 × 2호스트 = **24 사이클**.
초록이 나올 때까지 돌리지 않았고, **통과한 것까지 전부** 기록했다.

`up --wait`를 쓰지 않는다. `--wait`는 health가 초록이 될 때까지 막으므로, 그 뒤에 시작한 관측자는 **이미 닫힌 창만**
볼 수 있다. 그래서 health 보고 자체를 재는 대상 중 하나로 두고, 하나의 시계 위에 같이 적었다 — 컨테이너 health 전이,
포트 게시, 호스트 TCP 수락, **실제 PostgreSQL 질의 응답**, **실제 Redis PING 응답**, 각 서비스의 identity.

**정확히 말하면 "스택 시작과 동시"가 아니다.** 시계는 `compose up` 호출 직전에 시작하지만, 관측 루프는 `up -d`가
**반환한 뒤** 시작한다. 기록된 것은 시작 시각이고, 탐침이 그 사이를 보고 있었던 것은 아니다.

### 2.1 창은 언제나 있다

| 호스트 | 사이클 | TCP 거절 | 응답 실패 | TCP 수락→응답 (postgres) | 창 안에서 본 거절 |
|---|---|---|---|---|---|
| Windows 11 | 12 | 0 | 0 | 0.22 ~ 0.34s | **43건** — `closed_unexpectedly` 42, `starting_up` 1 |
| WSL Ubuntu 26.04 | 12 | 0 | 0 | 0.52 ~ 0.77s | **144건** — `closed_unexpectedly` 142, `starting_up` 2 |

**24번의 시작 전부**에서, 게시된 포트가 TCP를 받아들이는데 PostgreSQL은 아직 세션을 처리하지 못하는 구간이 있었다.
그리고 그 구간에서 관측된 거절 문구가 **CI의 B와 C 그대로**다. 한 사이클(포트 53446) 안에서 두 문구가 **차례로**
나왔다 — B와 C는 독립된 두 고장이 아니라 **같은 창의 두 단계**로 관측된다. 다만 CI 두 실패가 이 창에서 났다는 것을
CI에서 직접 재지는 않았으므로, 여기서 말할 수 있는 것은 **같은 기제가 두 호스트에서 항상 존재한다**는 것까지다.

### 2.2 health 관측 순서 — 여기서 내가 과하게 말했고, 되돌린다

`첫 성공 응답 관측 − health 관측`(양수 = health를 **먼저 관측**):

| 호스트 | 값 | health를 먼저 관측한 횟수 |
|---|---|---|
| Windows 11 | 전부 음수 (−1.42 ~ −0.28) | **0 / 12** |
| WSL Ubuntu 26.04 | −1.52 ~ **+0.031** | **3 / 12** |

**앞선 제출에서 나는 이것을 "health가 비준비 구간 안에서 초록이 됐다"고 적었다. 그건 데이터가 말하는 것보다 많다.**
독립 검토가 같은 파일을 다시 집계해 그 세 건을 보였다:

| standalone 사이클 | 마지막 거절 | health 관측 | 첫 성공 응답 관측 | health 관측 뒤 거절 |
|---|---:|---:|---:|---:|
| 3 | 1.458 | 1.530 | 1.561 | **0** |
| 4 | 1.445 | 1.516 | 1.542 | **0** |
| 5 | 1.440 | 1.511 | 1.538 | **0** |

탐침은 health를 조회한 **뒤** 서비스 요청을 차례로 보낸다. 세 건 모두 health 관측 다음의 **첫 요청이 성공했다.**
그러므로 "health 시점에 서버가 답할 수 없었다"를 배제하지 못한 것이 아니라, **그 반대를 배제하지 못한다** — 서버는
health 관측 전에 이미 답할 수 있었고 다음 요청 전까지 아무도 묻지 않았을 뿐일 수 있다.

**확인된 것은 관측 순서와 관측 시각 차이뿐이다.** 실제 구간을 입증하려면 health 시각 **이후의 요청 거절**이나 동시
탐침의 요청 시작·종료 구간이 필요하고, 둘 다 이 데이터에 없다. 주장을 유지하려고 다시 돌리지 않았다.

남는 것은 §2.1이고 그것으로 충분하다. **TCP 수락 뒤 실제 거절이 24/24로 있었다**는 기록은 유효하며, 열린 소켓이
응답이 아니라는 근거는 그것 하나로 선다.

### 2.3 재현하지 못한 것

**증상 A(30초 동안 포트 미연결)는 24 사이클에서 한 번도 재현되지 않았다**(`tcp_never_accepted` 0/24). 원인은
**미확정**이다. 이 수정은 A를 고치지 않으며, 고쳤다고 말하지 않는다.

## 3. 고친 것 (`src/codex_harness/adapters/verification.py`)

준비 완료의 정의를 바꿨다. **기한(30초)은 그대로 두고, 그 기한이 감싸는 조건을 강하게 했다.**

| 이전 | 이후 |
|---|---|
| TCP 연결이 수락되면 ready | **서비스가 실제 요청에 답하면** ready — postgres는 `SELECT system_identifier FROM pg_control_system()`, redis는 `PING` + `INFO server` |
| (없음) | 답한 상대가 **이 프로젝트가 띄운 컨테이너인지** 확인한다. 같은 identity를 `docker exec`로 컨테이너에게도 물어 **양쪽이 같아야** 통과 |
| 실패는 `ConnectionRefusedError` 한 가지 | 거절을 **종류별로 세어 이름으로** 남긴다: `refused` / `closed_unexpectedly` / `starting_up` / `timed_out` / `other`. **원문과 자격증명은 남기지 않는다** |
| 영수증에 `ready_after_seconds`만 | `tcp_after`, `ready_after`, `identity`, `refusals_during_startup`을 함께 남긴다 |

**오접속 방지**가 필요한 이유는 identity 자체다. 게시 포트는 데몬이 고르고 재사용된다. "서비스가 떴다"가 "우리
서비스가 떴다"를 뜻하려면 양쪽에 같은 질문을 하고 같은 답을 요구해야 한다.

### 3.1 2차 검토(review 5207324942) 반영 — 기한과 예외 체인

| 지적 | 무엇이 틀렸나 | 고친 방식 |
|---|---|---|
| **R1** 기한이 응답·identity 확인을 제한하지 않음 | deadline을 **거절 뒤에만** 봤다. 응답이 기한 뒤에 성공하면 그대로 ready가 됐다. PostgreSQL은 `connect_timeout`뿐이라 **연결 이후 멎으면** 호출이 붙잡힌다. identity 조회는 `_command`의 150초를 따로 썼다 | **하나의 기한이 모든 단계를 덮는다** — 소켓·인증·질의·결과 수신·docker identity 조회. 각 시도는 남은 시간만큼만 살고(`_bounded`, 자기 스레드에서 join 대기), **성공한 응답도 기한 안에 끝났는지 다시 검사한다.** 단계마다 새 30초를 주지 않는다 |
| **R2** 원문 오류가 예외 체인으로 공개됨 | `raise … from exc`가 원문을 보존하고 traceback이 체인을 찍는다. 내 회귀는 `str(raised.value)`만 봐서 체인을 보지 않았다 | 분류와 개수만으로 거절을 만들고 **체인을 끊는다**(`from None`). 회귀는 이제 `traceback.format_exception` 전체에 sentinel이 없음을 요구한다 |

새 회귀 5건: 기한 뒤 성공 두 경로(중단되는 쪽·반환되는 쪽), **연결 뒤 무응답에서도 호출이 유계로 돌아오는 것**,
identity 조회 지연 거절, **예외 체인에 원문이 없는 것**. 되돌리면 5건 전부 실패한다.

## 4. 수정 후 측정 — 흡수한 것이 0이다

같은 두 호스트에서 `VerificationServices`로 실제 스택을 **각 6회**(고정) 띄웠다.

| 호스트 | 성공 | tcp_after | ready_after | 흡수한 거절 |
|---|---|---|---|---|
| Windows 11 | 6/6 | 0.00 ~ 0.02s | 0.15 ~ 0.30s | **0건** |
| WSL Ubuntu 26.04 | 6/6 | 0.00s | 0.12 ~ 0.20s | **0건** |

**이 12회에서는 새 검사가 할 일이 없었다.** `up --wait`가 창을 먼저 닫았기 때문이다. identity 대조는 12회 모두
통과했다(postgres system_identifier, redis run_id).

그러므로 **전후 발생률이 좋아졌다고 주장하지 않는다.** 여기서 말할 수 있는 것은 두 가지뿐이다 — 창은 24/24로
존재하고, health가 그 창 안에서 초록이 되는 일이 WSL에서 3/12로 일어났다. 새 검사는 **그 조건에서만 값을 하는
보험**이며, 이번 12회는 그 조건이 오지 않았다.

## 5. 회귀 (`tests/test_verification.py`, 준비 관련 6건)

Docker 없이 **실제 소켓**으로 창을 재현한다 — 연결을 받아들이고 바로 끊는 리스너가 곧 `closed_unexpectedly`다.

| 검사 | 요구하는 것 |
|---|---|
| `test_readiness_refuses_a_port_that_accepts_and_cannot_answer` | **CI 증상 재현**. 소켓은 열리는데 서비스가 답하지 않으면 ready가 아니다 |
| `test_readiness_names_the_refusals_it_saw_without_quoting_them` | 다섯 종류를 이름으로 가르고, 실패 메시지에 **비밀번호가 없다** |
| `test_readiness_still_refuses_a_port_that_never_accepts` | 증상 A는 그대로 유계 실패다 |
| `test_readiness_waits_for_the_answer_rather_than_the_socket` | ready 시각이 **소켓이 아니라 응답**을 따라간다. 지나온 창이 영수증에 남는다 |
| `test_readiness_refuses_a_service_that_is_not_this_projects` | 답했어도 **우리 것이 아니면** 거절 |
| `test_readiness_binds_the_receipt_to_what_answered` | 영수증이 시간과 identity를 함께 든다 |

**되돌려 확인했다.** 수정을 되돌리면 이 6건이 전부 실패한다.

## 6. 호스트 증거 (`docs/zeus/evidence/environment-runs-015/`, head `2b3455b`)

| 호스트 | ruff | full-suite-integration | disposable-docker |
|---|---|---|---|
| Windows 11 | 통과 | **1740 passed, 14 skipped** (602s) | **22 passed** |
| WSL Ubuntu 26.04 | 통과 | **1742 passed, 12 skipped** (237s) | **22 passed** |

disposable-docker가 17건에서 **22건**으로 늘어난 것이 준비 관련 회귀 6건 중 5건이다(1건은 실행 시간이 짧아 전체
스위트에서 함께 돈다). 두 호스트 로그·JUnit에서 canary 0건, `password=` 0건. 양쪽 모두 1회 시도에서 통과했고,
**이것을 증상 A의 해결 근거로 쓰지 않는다**(§2.3).

## 7. 하지 않은 것

- 기한을 늘리지 않았다(30초 그대로). 실패를 skip으로 돌리지 않았다.
- 증상 A(포트 미연결)는 재현하지 못했고 고치지 않았다. **원인 미확정**으로 남긴다.
- 재부팅·절전·WSL 종료·Docker Desktop 재시작·전역 Docker 설정 변경 없음. 운영 컨테이너와 다른 작업의 데이터는
  건드리지 않았다. 프로브는 자기 compose 프로젝트만 만들고 지운다.
- 유료 모델 호출 0회.
- CI 두 실패가 §2의 창에서 났다는 것을 **CI에서 직접 재지 않았다.** 같은 기제가 두 호스트에 항상 있다는 것까지가
  측정이고, 그 너머는 추론이다.
- 전후 발생률 차이의 통계적 유의성은 주장하지 않는다(§4).
