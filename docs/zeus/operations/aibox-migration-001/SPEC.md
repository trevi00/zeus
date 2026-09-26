# aibox 운영 호스트 이관 — 실행 명세

상태: Codex 설계 완료 / Claude 구현·실측 인계. 2026-09-25.
현재 문서는 이관을 실행했다는 증거가 아니다. 최신 지시로 스위치 도착 전 현재 LAN에서 이관 가능하다.
상위 목표: [autonomous-operation-001](../autonomous-operation-001/SPEC.md).

## 1. 결정과 완료 조건

최신 사용자 확정: 최종 결과는 aibox 완전 이관·자가개선 자율 무인 운영과 Windows Zeus 실행 구성 제거다.
Windows를 영구 standby 운영 호스트로 유지하지 않는다. 아래 rollback은 전환 기간의 임시 보호책이다.
2026-09-25 실제 조회에서 Windows ZeusFleet-run/ZeusMonitor-collect/ZeusMonitor-web은 Running,
zeus-local-ops-redis와 zeus-ticket-ledger도 실행 중이었다. 업무 busy=0과 운영 구성 부재는 다르다.

최종 정리 게이트 C: A/B 수용 후 aibox의 원장·증거·Git·원본 자산 참조가 Windows 없이 해소되고,
백업 복원까지 확인되면 Zeus 전용 예약 작업/observer/프로세스/컨테이너를 비활성화·제거한다.
삭제 전 정확한 소유권·절대 경로·dirty/ignored 데이터·이전 hash를 확인하고 삭제 manifest를 남긴다.
공유 DB/타 프로젝트 컨테이너(flexday-pg 등), 사용자 Claude/Codex 인증·전역 설정은 삭제하지 않는다.
Windows runtime/worktree/cache는 필요한 코드·자산·실패 증거의 검증된 서버 사본 및 복구 백업을
확인한 뒤 정리한다. 원본 Claude 하네스는 흡수/보존 범위가 확인되기 전 제거하지 않는다.
서버 독립 운영·정리 증거를 남기며 이 Windows observer에 의존하는 자동 진행도 끝낸다.

최종 운영 호스트가 aibox이므로 autonomous-operation-001의 **최종 호스트 합격은 aibox에서 받는다**.
Windows에서 진행 중인 r4 검증은 정상 종료 및 증거 보존까지 맡기되, 그 결과만으로 Windows의
새 managed cutover나 전체 자율 순환 검증을 추가 착수하지 않는다. 실패하면 원인을 분류하고,
공통 코드 결함만 이전 전에 수정한다. Windows에 한정된 비필수 환경 문제는 Linux 합격을 막지 않는다.
이 판단은 기존 Windows 결과를 취소하거나 실패를 통과로 바꾸지 않는다.

최초 조사·설계에서는 서버 변경, admission 중단, 비밀 복사, 실제 이관을 수행하지 않았다.
후속 사용자 지시로 화요일 스위치 도착을 기다리지 않고 현재 LAN에서 이관하도록 순서를 변경한다.
Claude는 아래 명세대로 구현과 실행 증거를 제공하고 Codex가 변경 및 최종 수용을 독립 검토한다.
네트워크 전제 충족 후 기존 승인된 운영 범위 내에서 단계별 게이트를 통과하여 실행한다.

완료는 (A) 데이터·소유권 이관 합격과 (B) aibox 전체 자율 순환 합격으로 분리한다.
A만 통과하면 `migrated_limited`, B까지 통과해야 `autonomous_qualified`이다.
자산 전체 흡수, GPU 모델 서버 구축, PG/Redis 대버전 업그레이드는 이관 완료의 선행 조건이 아니다.

## 2. 사실, 판단, 미확인

### r4 종료 후 인계 상태 (2026-09-25 04:38:57 UTC)

Windows successor release `096c7daf74c07af9f3accecc594dce28c4b27db2028f2b84f96ea2436046ff2d`
는 verified로 종료했다. 기존/후보 test manifest 각각 4318 수집, 4245 passed, 73 skipped,
0 failed/not_run/unknown; 이미지 CLI와 실제 file task도 passed/executed이다.
image `sha256:d97e6003e66c83f83860feabd8a38013c487c45e5db5883abf912ea54d89fa36`.
`promotion=not_requested`; 운영 반영이나 aibox 합격은 아니다. 기존 rejected source는 보존한다.
결과: `D:/workspaces/zeus/artifacts/autonomous-operation-001/checklist-release-verification-r4-result.json`.
test evidence: `sha256:576fc52e55644fbe25f562d6bfe89bbc6b3958873d1fbe6735ebbc21f5a273ee`.
원본 증거 루트는 같은 디렉터리의 `checklist-verification-artifacts`이며 이관 manifest에 포함한다.
후속 대조에서 Fleet busy/held units는 0, 검증 helper는 종료, PR200은 정확한 head로 merged였다.
aibox는 당시 192.168.0.10/24로 관측돼 옛 N은 미충족이었다. 후속 지시로 아래 N을 현재 LAN 기준으로 변경했다.
다음 owner는 Claude 이관 구현/증거 담당이며 이 SPEC과 위 결과를 입력으로 사용한다.
현재 서버 이관 작업을 dispatch했다는 뜻은 아니다. 현재 LAN에서 N을 검증하여 진행한다.

### 사용자 확정 목표: aibox 운영, Windows 인수 창구

2026-09-25 추가 지시: 운영·오케스트레이션·원장·리서치·Claude/Codex 작업·빌드·자동 테스트·
자가개선 및 관제 서버는 aibox가 소유한다. Windows PC는 사람이 실제 화면을 확인하고
인수 판단을 전달하는 클라이언트다. Windows PC, Codex 데스크톱 세션, SSH 터널이 꺼져도
서버의 승인된 작업·독립 검토·복구·다음 작업 선정은 계속되어야 한다.

- 자동 브라우저 테스트/스크린샷/동영상 생성은 aibox에서 실행하고, 사람은 브라우저로 실제 앱과
  보고서를 확인한다. 스크린샷이나 Linux 브라우저 통과를 모든 실제 사용자 환경의 합격으로 확대하지 않는다.
- 인수 승인이 필요한 작업은 서버 원장에 approval_pending으로 유지한다. 사람이 접속하지 않았다는
  이유로 자동 승인하지 않는다. 승인이 필요 없는 독립 일감은 계속 진행한다.
- 현재 Windows 채팅을 깨우는 ZeusOwner-continuation은 **임시 개발 보조**다. 이것이 있어야 다음
  단계가 진행된다면 최종 합격이 아니다. aibox의 durable owner/recovery 경로로 인계하고 기존
  Windows observer는 cutover 후 비활성화한다. 서버 timer가 CLI를 무조건 반복 호출하는 것으로 대체하지 않는다.
- Windows scheduled task/PowerShell launcher/DPAPI 저장 경로는 그대로 복사할 대상이 아니다.
  Linux service lifecycle·secret adapter로 기능을 이전한다. 현재 ScheduledTaskHostTarget은 Windows
  전용이며, 기존 ProcessHostTarget을 재사용할지 systemd adapter가 필요한지 구현 전에 책임 경로를 확정한다.
- 사용자 인용의 BaldrixCronScheduler 존재·활성 상태는 이 조사에서 아직 확인하지 않았다.
  원본 스케줄 목록을 실측하고 Zeus 관련된 것만 이전/흡수한다. 회사·개인 타 작업은 임의 중단하지 않는다.

Windows에 남길 수 있는 예외는 아래뿐이며, 항상 이 PC를 켜야 하는 의존성으로 만들지 않는다:

| 예외 | 처리 |
|---|---|
| Windows 전용 앱 빌드·native 기능·Job Object/PowerShell 회귀 | GitHub Windows CI 또는 필요할 때 켜는 Windows runner; 결과는 서버 원장으로 수집 |
| Windows 실제 UI/브라우저·주변장치 인수 | 사용자가 이 PC에서 수행; 그 제품 시나리오에만 승인 게이트 적용 |
| 삼성 폰·태블릿 실제 기기 검증 | 기기 접근 runner가 필요하며 Linux 자동 브라우저로 대체 불가; 이번 이관 범위 밖 |
| 아직 이관되지 않은 source 데이터·rollback 보관 | 읽기용 보존; 서버 운영의 일상적인 원장/증거 참조는 서버 안에서 해소 |

추가 수용 B5: Windows worker/observer가 비활성인 상태에서 Windows 클라이언트·SSH 연결을 끊고
B1–B3을 수행한다. 서버 journal·원장·증거로 다음 단계가 이어졌음을 확인하고 Windows 재접속 시
진행 상태와 인수 대기 결과를 볼 수 있어야 한다. 실제 PC 전원 종료를 강제할 필요는 없다.

네트워크 선행 조건의 본질은 고정 IP/안정적인 연결/비중복 라우팅이다. 2.5G는 correctness 조건이 아니다.
사용자가 1G 구성을 선택하더라도 동일 수용 기준을 적용할 수 있으며 이 SPEC 때문에 2.5G 장비를
추가 구매할 필요는 없다. 최종 장비 선택·가격은 이번에 검증하지 않았다. 큰 최초 데이터 이전은
관제 화면 조회와 별개의 전송 비용이 있으므로 양을 실측한다. 최신 지시로 스위치 설치 전 이관을 허용한다.

2026-09-25 읽기 전용 관측:

- 사용자 제공 `C:/Users/rudtn/aibox-context.md`는 2026-09-23 사양·로그인 보고이다.
- `ssh aibox` 성공: hostname trevi, Ubuntu 26.04.1 LTS, kernel 7.0.0-34-generic,
  systemd 259.5, 루트 ext4 약 3.5T 가용, 주소 192.168.0.10/24. 아직 새 네트워크가 아니다.
- aibox Docker 실행 중. 공용 postgres:18, redis:8 및 타 프로젝트 서비스들이 있다.
  PG5432·Redis6379 등은 0.0.0.0/[::]에 게시돼 있다. 방화벽 밖 도달성은 이번에 시험하지 않았다.
- Zeus 저장소 compose는 pgvector/pgvector:pg17, redis:7.4-alpine을 선언한다.
  Windows에서 실제 zeus-local-ops-redis 및 일회용 검증 PG17/Redis7.4를 관측했다.
  실제 운영 PG 이미지·버전·확장 목록은 이관 manifest에서 별도로 확정해야 한다.
- PR200 병합 b2bde3bf417df75172dc4fb90814b432385fd8fd. 원래 rejected release b5650fe9의
  이력은 유지됐고 successor 096c7daf의 r4 검증은 조사 시작 시 실행 중이었다.
- Fleet.register는 기존 config와 다른 config를 거절한다. lane config에는 repository/runtime/
  schema/redis_namespace가 들어간다. 따라서 DB 복원 후 경로 문자열만 바꾸고 재등록하는 방식은 안 된다.
- lane_dsn은 지정 schema만 search_path로 설정하고 documents 테이블을 검사한다.
  RedisBus는 consumer group workers와 XAUTOCLAIM/XACK를 사용한다.
  FileArtifacts는 sha256 본문과 metadata 파일을 읽어 검증한다.

판단: aibox는 상시 Linux 운영에 적합한 후보지만 위 사양이나 SSH 성공은 운영 합격이 아니다.
GPU는 현재 Claude/Codex 외부 호출 경로의 필수 자원이 아니다. 초기 동시성은 현 승인값을 유지한다.
미확인: 현재 전체 PG/Redis 데이터 크기, 모든 schema/namespace와 로컬 증거 루트,
실제 컨테이너 인증, Linux 서비스 소유권, 복구 소요시간. 아래 게이트가 확인 책임을 갖는다.

## 3. 순서·중복 비용

| 선택 | 필요한 검증 | 평가 |
|---|---|---|
| Windows 전체 합격 후 이전 | 남은 Windows cutover·rollback·자율 순환 + 이전 + Linux 호스트 검증·자율 순환 | Windows도 운영 호스트로 계속 써야 할 때만 가치가 큼 |
| 코드 수용·현재 실행 정리 후 이전 | 현재 결과 보존 + 이관 검증 + Linux 최종 호스트·자율 순환 | 채택. Windows 전용 최종 운영 검증의 추가 비용을 피함 |

코드 리뷰, 정확한 commit의 CI/회귀, 계약, 실패 진단은 재사용한다. 호스트 인증, 경로·권한,
신호·컨테이너 종료, 서비스 재시작, 포트, 데이터 복원, 운영 소비 revision/image/profile,
rollback 및 실제 전체 순환은 aibox에서 새 영수증이 필요하다. Ubuntu GitHub CI도 aibox 증거가 아니다.

비용식: Windows-first = W남은호스트검증 + M이관 + L최종검증;
aibox-first = W현재실행정리 + M이관 + L최종검증. 절감은 새로 추가할 Windows 호스트 검증분이다.
시간/토큰 실측이 없어 시간·비율은 추정하지 않는다. 단계별 wall time, 모델 호출·토큰,
복사 byte, 정지 시간을 기록한다. 2.5G는 이론 상한이며 디스크·양단 NIC·프로토콜 실효속도를 따로 잰다.

## 4. 전체 경로와 목표 배치

```text
Git 명세/승인 portfolio + 웹 요청/리서치
 → admission → Fleet 주 원장 → lane PG + Redis Streams
 → 격리 Claude → 독립 Codex → exact checks → release → managed activation
 → 관측/실패 연구/수정 → 다음 유용한 일감
```

Git은 정의, PG는 실행 원장, Redis는 전달 상태, artifacts는 증거 본문이다.
PG 잠금은 **같은 DB 안에서만** 유효하다. 복사된 Windows DB와 aibox DB의 잠금은 서로를 막지 못한다.
두 호스트 동시 writer를 방지하는 source fence와 host activation receipt가 반드시 필요하다.

목표 경로(새 Linux 컨벤션):

| 용도 | 경로/식별 |
|---|---|
| Git·작업 트리 | /srv/zeus/repo, /srv/zeus/worktrees/<task-id> |
| 불변 런타임 | /srv/zeus/releases/<revision>, current는 수용된 포인터 |
| 실행·lane 상태 | /srv/zeus/runtime/control, /srv/zeus/runtime/lanes/<lane-id> |
| 증거·이전 백업 | /srv/zeus/artifacts/<task>/<run>, /srv/zeus/backups/<migration-id> |
| 짧은 임시 경로 | /srv/zeus/tmp/<run> |
| 비밀 | 서비스 UID의 보호된 저장소, Git·artifacts·명령행 밖 |
| 전용 스택 | compose project zeus-aibox, 독립 volumes/networks |
| PostgreSQL | 전용 DB zeus_aibox, schema zeus_aibox_control 및 zeus_aibox_<lane> |
| Redis | 전용 인스턴스, source namespace를 최초 이전에서 보존; host identity는 별도 aibox |

source namespace 보존은 Redis stream key/payload를 재작성하지 않기 위한 결정이다.
이름을 바꾸는 별도 migration은 이번에 필요 없다. 전용 인스턴스로 기존 aibox Redis와 격리한다.
PG·Redis major/version/확장을 source와 맞추고 image digest를 고정한다. 공용 ~/infra/dev를 덮어쓰지 않는다.
GPU driver, 기존 개발 도구와 타 서비스는 건드리지 않는다. Python/venv는 Linux에서 lockfile로 재생성한다.

## 5. 선행 게이트 N — 네트워크 확정

최신 순서 변경: 화요일 스위치 설치를 기다리지 않는다. 2026-09-25 SSH로 관측한 현재 주소는
192.168.0.10/24, NIC의 실제 협상 속도는 100Mbps다. NIC 최대 사양과 현재 링크 속도는 다르다.
현재 LAN에서 SSH/외부 HTTPS/NTP/라우트·전송 안정성과 서버 로컬 DB/Redis 주소를 확인하면 N을
충족할 수 있다. 현재 주소가 영구 고정이라고 주장하지 않으며, 복사 전 재조회하고 중단 시 hash 기반 재개한다.
current LAN에서 staging 및 실제 cutover 모두 허용하되 나머지 데이터·단일 owner·rollback 게이트는 유지한다.
고정 172.30.1.x 주소나 특정 NIC 속도는 이번 이관의 필수 조건에서 제외한다.

화요일 네트워크 변경은 별도 유지보수다: 새 admission pause → 외부 호출/drain 또는 안전한 checkpoint
→ 네트워크 변경 → DHCP 예약/SSH alias 갱신 → SSH·모델/GitHub·관제·route·owner 재검증 → 재개.
DB/Redis와 서비스 간 주소는 loopback/Docker service name을 사용하고 LAN IP를 원장 identity로 쓰지 않는다.
네트워크 단절 중 외부 효과가 unknown이면 정상 reconciliation 전 재호출하지 않는다.
IP 변경만으로 데이터 재이관이나 전체 suite 재실행을 요구하지 않고, 바뀐 경계와 실패한 검사만 재검증한다.

예정된 화요일 작업은 2.5G 스위치 설치 → KT 공유기의 NIC MAC DHCP 예약 → 실제 172.30.1.x 주소 확정 →
Windows SSH alias HostName 갱신 순서. HostKeyAlias와 기존 host key 신뢰를 보존하며
키가 달라지면 자동 삭제/무조건 수락하지 않는다. IP 마지막 자리는 추측하지 않는다.

양단 SSH 재연결, DNS/외부 모델·GitHub HTTPS, NTP 및 link 속도/실효 전송을 확인한다.
172.30.1.0/24와 Docker bridge/VPN/WSL 라우트의 겹침을 검사한다. 겹치면 Zeus 전용
네트워크의 검증된 비중복 subnet을 정하고 기존 다른 프로젝트 네트워크를 임의 재구성하지 않는다.
대규모 복사는 현재 실효속도로 진행 가능하다. 전송 중단·hash 불일치는 재개/복구 대상으로 기록한다.

DB/Redis는 전용 Docker network 및 필요 시 loopback만 게시한다. 관제는 우선 loopback+SSH tunnel.
LAN 공개가 필요하면 기존 인증과 접근 통제를 확인한 별도 endpoint를 사용한다.
기존 infra의 광범위 게시 포트는 별도 기록하며 수정 승인을 이관과 혼합하지 않는다.
UFW만 보고 Docker 게시 포트가 차단됐다고 주장하지 않는다.

## 6. 구현 배치 — 이관 coordinator와 한 장의 manifest

Claude는 기존 Fleet/HostDelivery/release API를 먼저 재사용하고 부족한 부분만 확장한다.
외부 shell에서 무작위 PG UPDATE로 registry·상태를 변경하는 우회는 금지한다.
`migration_id`가 있는 재개 가능한 coordinator, 검증된 manifest, Linux service descriptor,
복사/복원/비교/rollback 명령을 한 배치로 제공한다. 부분 실패는 같은 ID로 재개하고 중복 복원하지 않는다.

상태: planned → network_ready → staged → draining → source_fenced → snapshot_sealed
→ restored_paused → limited_active → qualified. 실패는 failed/rollback_required로 이유를 기록한다.
각 전이에 actor, host, UTC, config/commit/image/profile hash, 입력·출력·exit·증거를 남긴다.

manifest는 비밀을 제외한 source/target DSN identity, schema map, runtime/path map,
Git commit+dirty/ignored 보존 목록, artifact root·hash·크기, PG bucket count/digest,
Redis key/group/PEL·expiry, 서비스/스케줄/컨테이너 소유자, source fence, rollback 위치를 포함한다.
경로 검색 결과를 증거로 삼되 오래된 로그 속 Windows 경로를 무조건 바꾸지 않는다.

registry relocation은 target-paused 한정 명시적 migration use case로 구현한다:
source config digest와 snapshot digest를 요구하고 활성 작업/lease/activation이 있으면 거절한다.
원래 config를 보존하고 target config+mapping+receipt를 한 transaction으로 기록한다.
같은 요청은 멱등, 다른 요청/stale hash는 거절. history의 task/attempt/review/artifact identity는 유지한다.
원본 DB와 dump는 변경하지 않는다. target의 mutable binding만 allowlist로 바꾸며 이전/이후 값을 증명한다.
queued immutable manifest가 옛 경로를 실행에 쓰면 덮어쓰지 말고 원본을 보존한 linked successor를
정상 API로 만든다. 이미 완료된 일은 재큐잉하지 않는다. 필요한 API가 없으면 이 구현 배치에서 추가한다.

## 7. admission 중단·비우기·일관된 snapshot

1. 현재 r4 및 Fleet/리뷰/CI/release/helper 상태를 대조한다. 작업을 중복 시작하지 않는다.
2. **새 admission만 먼저** 막고 이미 맡긴 작업은 종료·정산·증거 수집까지 drain한다.
   웹 제출은 maintenance로 명확히 거절하거나 별도 durable 대기열로 받고 몰래 유실하지 않는다.
3. source admission pause를 정상 API로 기록. 실행 중/dispatching/unknown Fleet,
   예약 호출·unconfirmed provider 효과·release lease·promotion intent를 전부 판정한다.
   queued backlog는 삭제하지 않는다. unknown은 성공이나 빈 상태가 아니며 정상 reconciliation이 필요하다.
4. outbox/consumer 처리·관측 spool/보류 알림을 수집한다. 남은 부채는 이유와 owner를 고정한다.
5. scheduled Fleet, research, repair, release controller, 웹 writer, CLI helper, chat continuation 등
   다시 writer를 만드는 경로를 목록화하고 중지/비활성화한다. 현재 owner observer 역시 이관 시
   Windows 자동 cutover를 재개하지 못하게 fence한다. **지금 설계 턴에서는 설정을 변경하지 않는다.**
6. 실제 프로세스·Docker labels·DB lease를 대조하여 writer 0을 확인하고, source 재시작 경로도
   migration marker에서 fail-closed인지 시험한다. 단순 PID 없음/서비스 stop 성공만으로 충분하지 않다.
7. 더 이상 쓰기가 없는 barrier에서 PG/Redis/artifacts snapshot을 seal한다.
   PG와 Redis에는 공통 snapshot transaction이 없으므로 quiescence가 일관성 조건이다.

## 8. PG·Redis·파일 복원

PG: 실제 운영 DB의 Zeus control 및 모든 lane schema, 관련 sequence/extension/권한을 inventory한다.
전용 DB면 전체 logical dump(custom format)와 필요한 roles 정의를 보관한다. shared DB이면 Zeus schema
범위와 의존성을 명시하고 타 프로젝트 데이터는 옮기지 않는다. live PG volume 파일 복사는 사용하지 않는다.
target staging DB에 restore하고 reviewed schema mapping을 적용한다. JSON 원장은 전체 치환 금지.
원본 bucket/id/canonical body hash를 비교하고 허용된 binding 변경은 별도 delta receipt로 비교한다.
과거 audit는 바꾸지 않는다. control/lane마다 search_path를 검사하고 public fallback을 거절한다.

Redis: PG가 SSOT라는 이유로 빈 Redis로 시작하거나 outbox 전부를 재발행하지 않는다.
stream entries, last-generated/last-delivered IDs, groups, consumers, pending 목록,
dedup keys, TTL 의미를 inventory한다. source 전용 인스턴스라면 쓰기 중지 후 완전한 RDB 또는
검증된 AOF 세트로 복원한다. shared 인스턴스면 Zeus key allowlist의 DUMP/RESTORE 기반 절차를
fixture와 실제 복원 비교로 검증한다. entries만 XRANGE/XADD해 PEL을 버리는 구현은 금지한다.
만료시간은 절대 expiry로 보존하고 downtime에 실제 만료된 것을 구분한다. lock TTL을 늘려 살리지 않는다.
PEL은 0이거나 각 pending이 PG 효과/owner와 대응해야 한다. target 재전달은 기존 inbox/dedup을 거쳐
동일 메시지의 부작용이 한 번만 반영되는 것을 검증한다. XACK만으로 업무 성공을 만들지 않는다.

Artifacts: 모든 참조 루트를 합집합으로 조사하고 본문+metadata를 hash 검증하여 복사한다.
raw 로그·JUnit·관측 spool·미수집 알림·호출 원장·handoff receipts·DB 밖 rollback 증거도 포함한다.
내용주소 bytes를 수정하지 않는다. old path는 location mapping/resolver로 찾고 새 파일에서 SHA를 재검증한다.
case 충돌/심볼릭 링크/외부 경로를 보고하고 무조건 따라가지 않는다. 독립 review canary까지 참조가
실제로 읽혀야 한다. 복원 후에도 Windows와 D의 원본은 삭제하지 않는다.
호출 사용량은 source history를 보존하고 target host별 누적을 이어 집계한다. 0으로 초기화하지 않는다.

## 9. 컨테이너 인증·Linux 생명주기

host Claude/Codex 로그인 성공은 container/service 인증 성공이 아니다.
Windows DPAPI 파일을 Linux에서 복호화할 수 있다고 가정하지 않는다. aibox 서비스 UID용
정식 인증 경로와 보호된 secret 전달을 준비한다. Claude는 setup-token → OAuth env의 기존 adapter
allowlist, Codex는 기존 auth adapter와 최소 read-only secret mount를 검증한다.
호스트의 .claude/.codex 전체를 writable mount하지 않는다. API key 등 우선순위 충돌 변수 차단,
토큰 argv/log/receipt 노출 0, 실패 시 401을 명확히 보고하고 반복 모델 호출하지 않는다.
각 provider의 실제 격리 호출과 packaged worker profile/hook hash·로드 여부를 증거로 남긴다.

서비스는 명시적 UID(trevi 또는 검증된 전용 UID), absolute ExecStart/WorkingDirectory와 비대화형
PATH를 사용한다. shell 로그인 init에 의존하지 않는다. systemd 유일 owner, control-group 종료,
유계 stop/restart·재시작 제한을 적용하고 application lease/fence도 유지한다.
Docker daemon이 만든 container는 systemd cgroup 종료만으로 정리되지 않을 수 있으므로
run label/id 기반 stop·잔여 검사·불명확 효과 reconciliation을 별도로 시험한다.
SSH 종료, SIGTERM, 강제 종료 후 재시작, DB/Redis 단절, 늦은 결과, 중복 시작,
flock/rename/fsync/UID 권한, disk-full 관측을 허용된 test 영역에서 검증한다.
실서버 재부팅을 이번에 요구하지 않는다. service restart는 reboot 증거가 아니며 cold boot는
미검증 항목으로 정확히 남긴다. 사용자와 다른 서비스의 재부팅을 유발하지 않는다.

## 10. Cutover와 rollback

cutover: N 완료 → 코드/설정 리뷰 → 격리 staging restore 연습 → source drain/fence →
최종 snapshot seal → target restore 및 hash 대조 → target admission paused로 단일 owner 시작 →
read-only 관제 확인 → 제한된 canary admission → A 수용 → B 자율 순환 → portfolio admission 확대.
canary 시작부터 target은 새로운 authoritative writer다. 실행 runtime revision/image/profile,
DB identity/schema/Redis namespace와 host receipt가 모두 맞아야 한다. `current` symlink 변경만으로 합격 아님.
Windows owner 재시작 시도는 실제로 거절돼야 하며 SSH가 끊겨도 aibox 단일 owner는 계속 관리돼야 한다.

rollback R0 (target 쓰기 전): target을 fence하고 writer 0 확인 후 source snapshot·runtime 그대로 복구,
source 단일 owner/포인터 확인 후 admission 재개. source가 계속 바뀌었다면 R0 조건 불성립.

rollback R1 (target에 새 기록/외부 효과 발생 후): target admission stop → drain/reconcile → target fence →
target 최신 PG/Redis/artifacts를 역이관·검증 → Windows 호환 runtime/경로 binding 새 영수증 → 단일 owner 재개.
**옛 Windows snapshot만 켜면 새 기록이 유실되고 외부 효과가 반복될 수 있으므로 금지**한다.
원래 snapshot 대신 새 isolated Windows restore DB를 사용하며 reverse schema/path map을 검증한다.
GitHub merge/배포 등 외부 효과는 역이관으로 취소되지 않는다. 실제 상태를 대조하고 재실행하지 않는다.
target에 접근 못 하여 최신 상태를 보장할 수 없으면 두 쪽 admission을 닫고 사고로 보고한다.
무자료 failover나 무손실 보장은 하지 않는다. 최소 한번 post-write 역이관을 canary 데이터로 연습한다.

## 11. 수용 행렬과 증거

| ID | 합격 조건 | 필요한 증거 |
|---|---|---|
| N | 현재 LAN의 SSH·비중복 route·서비스 외부 접근 | 현 주소/route/link·연결 영수증; 고정 IP 변경은 후속 유지보수 |
| A1 | source admission 중단, 진행 작업 정산, 단일 writer | jobs/units/leases/container/schedules 대조 및 source 재시작 거절 |
| A2 | snapshot/restore 일치 | PG bucket/id hash, mapping delta, Redis IDs/groups/PEL/expiry, artifacts hash |
| A3 | 부분 실패·재시도 멱등 | 복원 중단 후 같은 migration_id 재개, 다른 digest 거절 |
| A4 | 인증·프로필 | Claude/Codex 실제 container 호출, secret 비노출, profile/hook receipt |
| A5 | Linux 소유권·복구 | 정상 종료/강제 종료/SSH 끊김/서비스 restart/중복 owner·Docker 잔여 판정 |
| A6 | 데이터 부채·장애 | PG/Redis unavailable, unknown 효과는 blocked, missing artifact는 수용 거절 |
| A7 | 정확한 runtime 반영 | source revision/image/profile와 서비스 실소비 identity, canary 결과 |
| A8 | rollback | R0 및 post-write R1 연습, 최신 원장/외부 효과 재실행 없음 |
| B1 | 실제 전체 순환 | 연구→SSOT→설계→Claude→독립검토→검증→운영 반영 연결 증거 |
| B2 | 실패 자가회복 | 통제된 recoverable 실패·동일 두 strike 조사·수정·독립 수용, 채팅 수동 relay 없음 |
| B3 | 연속/병렬 진행 | 유용한 서로 다른 2건 자동 선정·완료; 막힌 family와 독립 일감 진행·충돌 없음 |
| B4 | 관제·로그 | goal부터 outcome까지 링크, 일반/개발/운영 로그와 누락 알림, rejection·비용·상태 조회 |

주입 오류와 실제 장애, fixture와 실제 호출, skipped/not_run을 분리한다. 기대한 거절은 합격 가능한
안전 결과지만 unknown을 성공으로 바꾸지 않는다. 모든 행이 pass 또는 범위에 근거한 N/A여야 한다.
Linux 최종 전체 suite/실제 PG+Redis·릴리스 canary는 exact candidate에서 수행한다.
Windows 기능 호환 CI는 계속 유지하지만 Windows 전체 운영 순환을 반복하는 요구는 없다.
GPU/vLLM, 타 인프라 업그레이드, 하드웨어 장애/실제 reboot는 이번 행렬 밖이다.

## 12. Claude 인계·검토 방식

Claude는 이 SPEC을 SSOT로 사용하고 처음에 inventory/실행 가능한 runbook 및 미충족 선행 조건을
한 번에 보고한다. API 부족·경로/registry 의존·역이관 문제는 한 설계 배치로 모아 구현한다.
명세 밖 기능을 추가하지 않는다. PR에는 migration 변경, systemd/compose, 회귀, sanitized manifest,
실행별 실패 이력과 hash를 포함한다. 큰 증거는 /srv/zeus/artifacts에 보존하고 Codex가 읽을 수 있게 한다.
Codex는 동일 수용 행렬로 독립 검토한다. N 완료 전에 실제 이관하지 않으며,
원장 수정·복원·source fence/cutover는 각 전이 증거를 남겨 수행한다.
이번 설계에서 조사 중인 서버를 production-ready로 표현하거나 기존 Windows 결과를 Linux 합격으로 재분류하지 않는다.

## 13. 근거 (2026-09-25 열람)

- PostgreSQL 18 `pg_dump`: portable logical archive, globals 별도, schema-only 선택의 의존성 한계.
  https://www.postgresql.org/docs/18/app-pgdump.html — 실제 source major/client 호환은 실행 전에 확인.
- Redis persistence: RDB/AOF 특성 및 multi-part AOF backup 일관성.
  https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/ — 최신문서의 Redis8 기능을 7.4에 가정하지 않음.
- Redis XPENDING: group별 미확인 전달 상태. https://redis.io/docs/latest/commands/xpending/
- Docker: published port와 UFW 상호작용. https://docs.docker.com/engine/network/packet-filtering-firewalls/
- Claude Code authentication: setup-token과 OAuth 환경변수 경로.
  https://code.claude.com/docs/en/authentication — host 로그인은 컨테이너 인증 실측을 대체하지 않음.
- aibox 설치본 `/usr/share/man/man5/systemd.kill.5.gz`, systemd259.5: control-group 종료 동작.
  원격 upstream 문서는 403으로 못 읽어 설치본 man을 읽음. 설정만으로 Docker 소유권을 증명하지 않음.
- 로컬 코드: application/fleet.py(register/pause), adapters/fleet_runtime.py(lane_dsn/verify_lane_schema),
  adapters/bus.py(groups/claim/ack), adapters/artifacts.py(hash/metadata), compose.yaml.

이번에는 문서 작성과 읽기 전용 조회만 수행. 컨테이너 인증·restore·cutover·rollback 테스트는 미실행.

## 14. 자율 서버 소유 구현 — G1/G2/G3 (2026-09-25 추가)

출처: Codex `qualification-owner-review.md`의 "Follow-up: consolidated G1/G2/G3 recommendation"(설계 및 고정 수용
행렬). 기준 코드: 수용된 merge `426567fd678f09455fdba7c7ed888b9396d41409`. 이 절은 위 1–13절의 기준·이력을 바꾸지
않고 추가한다. 계약 ID는 `INV-OWNER-ACTIONS-001`(docs/contracts.md). 이 절은 구현 명세이며 B1–B5 실측 합격이 아니다.

### 14.1 결정

- **새 스케줄러·새 리뷰 엔진·새 배포 권한을 만들지 않는다.** 빠진 것은 서버 소유자 하나: 범위 연구 수용(G1),
  정확한 승인 배포 plan 게시(G2), 실제 canary 인계(G2), 그리고 managed Fleet의 systemd 감독 결합(G3)이다.
- 결정 권한은 기존 소유자에 남는다. `Continuation.accept_research`(검증·불변·멱등 영수증), `Releases`/`HostDelivery`
  (승인·단계·merge·canary 게이트·rollback), 기존 guarded `decide_one`(lease·시도 예산·실행 예산·증거 영수증),
  `ManagedFleetTarget`(materialize·verify·drain·stop·heartbeat·startup receipt).
- 후보(candidate)는 명령·unit 이름·권한·경로·target·검사 목록을 고를 수 없다. 모두 Git-pinned owner policy
  (`urn:zeus:owner-actions-policy:1`)와 owner target registry의 값이다.
- 승인·canary 증거를 합성하지 않는다. unknown 효과는 보류(held) 상태로 남고, 모델 호출을 타이머로 재시도하지 않는다.

### 14.2 G1 — 서버 소유 범위 연구 수용

`application/owner_actions.py`의 `OwnerActions`가 `research_required` 의도마다 정확한 binding(의도, 정책,
family, 현재 전체 attempt 집합과 각 lane 관측 evidence/inspection, 혼합 원인 시 각 원인, 현재 accepted dispatch/run)을
`Continuation.research_facts`(= `accept_research`가 쓰는 동일 reader)로 구성한다. 이미 같은 family의 이전 영수증이
소비한 dispatch는 제외한다. partial capture(owner scope supplement 필요)는 이름 있는 대기로 둔다.

1. 같은 binding digest에 정확히 묶인 **이미 실행된** 독립 평가(`owner_assessment` decision, succeeded, 명시적
   accepted/rejected, execution_ref)가 있으면 재사용한다(새 호출 없음).
2. 없으면 의도 행을 `assessing`으로 옮기는 **같은 트랜잭션**에서 `decisions_pending` 행 하나(actor `conductor`,
   phase `owner_assessment`, 입력 = binding + 묶인 보고서 텍스트/증거 ref + 질문)를 쓰고, 기존 DB-free guardian
   (`continuation_process`)으로 `zeus owner-actions assess`(= `BudgetedExecutor` 아래 guarded `decide_one`)를 한 번
   띄운다. launch는 최대 2회이며 두 번째는 첫 launch가 결정을 claim하지 못하고 증명된 종료/fence일 때만이다.
   Claude 보고서는 입력일 뿐 스스로를 승인하지 못한다.
3. accepted만 영수증 조립으로 간다. 평가 문서(`urn:zeus:owner-assessment:1`, 시계 없음)를 content-addressed로
   저장하고, 권위 행에서만 schema-1(단일 원인) 또는 schema-2(혼합 원인: 각 원인, 영속 lineage, capture, promotion
   binding, attestation = 평가 문서)를 결정적으로 조립한다. 조립된 영수증을 `invoking`으로 **먼저 영속**한 뒤
   `accept_research`를 호출한다. 동일 재호출은 cached, 변경된 증거는 refused로 남고 가족은 held.
4. rejected/unknown(차단·실패·미완·launch cleanup 미증명)은 이름 있는 종결 상태다. 변경된 증거는 **새 action**
   (새 정확 identity)이며 이전 action은 이력을 유지한다. 이후 기존 Fleet continuation tick이 영수증을 다시 검증하고
   보류를 한 번 해제하며 범위 수정을 이어간다.

### 14.3 G2 — 정확한 승인 plan 게시와 실제 canary 인계

- **Plan**: continuation `DELIVERY/awaiting_owner` 의도에 대해, lane `Releases` 기록이 기존 `release_gate`
  (`HostDelivery.approval`)로 approved이고 이 후보의 delivery가 없으며(`absent` 또는 다른 revision만 있는 `stale`)
  target에 진행 중 delivery가 없을 때만, owner delivery policy + 정확한 release 기록으로 `urn:zeus:host-delivery:1`
  plan을 만든다(target_descriptor revision = 검토된 후보, image/profile = `unchanged`; 새 환경은 별도 자격).
  (15절 D4 적합성 교정: "진행 중 delivery"는 intent가 아직 없는 등록 plan까지 포함한다. 이전 구현은 intent만 보아
  H1/H2가 모두 `expected_descriptor: null`로 묶였다.)
  plan 바이트·경로·ref를 `publishing`으로 먼저 영속하고, owner source repo에 고정 author/날짜의 결정적 commit을
  `refs/zeus/owner-plans/<plan_id>`에 **없을 때만** 생성한다(다른 내용의 기존 ref = `plan_ref_conflict`, 덮어쓰지 않음).
  재시작 시 같은 commit을 재도출·인식한다. Git에서 되읽은 plan만 기존 `HostDelivery.register`로 등록한다.
- **Canary 요청**: plan의 canary가 `fleet_worker_operation`이면 등록 **전**에 target state에
  plan 전용 `owner-canary-request.<plan_id>.json`(plan id/digest/target/revision/expected predecessor)을 쓴다.
  receipt도 plan 전용 `owner-canary-receipt.<plan_id>.json`이다. 같은 target의 다른 plan 등록은 소비 중 plan의
  요청·receipt를 대체하거나 답하지 못한다(G-H1 finding). delivery가 열린 completed plan은 tick마다 불변 action
  행에서 재구성한 자기 요청을 없거나 다를 때만 다시 쓴다(target 전역 요청 시절 등록 plan의 명시적 호환 경로).
  기존 `owner_qualified_canary`는 이 요청이 소비 중 descriptor와 정확히 일치하고 receipt가 없을 때만 `pending`을 반환하며, `HostDelivery._consume`은
  plan 자신의 consumption deadline까지만 기다린다. 만료 시 기존과 같은 거부 → rollback. 요청이 없거나 불일치하면
  동작은 이전과 동일(즉시 missing → rollback). 게이트 완화 없음.
- **실제 canary**: 소비 중 후보 instance의 자기 startup receipt가 확인되면 binding(plan, descriptor, instance)으로
  canary action을 만들고, job id를 먼저 영속한 뒤 owner policy의 고정 canary operation을 Fleet에 admit한다.
  실제 operation이 accepted이고 그 독립 lead review(`review_lead`, succeeded, accepted, execution_ref)가 있을 때만
  descriptor+instance-bound owner receipt `passed: true`를 쓴다. rejected는 `passed: false`(즉시 rollback), unknown·
  instance 변경·delivery 이동은 receipt 없음(deadline에서 rollback). 한계: canary는 plan의
  `consumption_timeout_seconds`(≤900s) 안에 끝나야 하며, 넘으면 안전 방향(rollback)으로 끝난다.

### 14.4 G3 — managed Fleet의 systemd 감독 결합

- target kind `managed_fleet_systemd`는 `managed_fleet`과 동일한 registry 필드·sealed runtime·descriptor·entry·
  receipt·heartbeat·drain을 쓰고, `service`는 코드 고정 `zeus-aibox-managed-fleet`만 허용한다. plan은 unit을 지정할 수 없다.
- 컨트롤러(HostDelivery)는 target guard 안에서 launch request(`managed-launch.json`: target, descriptor digest,
  sealed manifest digest, workload)를 쓰고 그 unit 하나를 `systemctl start`할 뿐이다. `stop`/`kill`/`restart`를
  호출하지 않는다(정지는 기존 pause → idle heartbeat → stop 파일). 필요한 polkit 권한은 이 unit의 `start` 하나다
  (`deploy/aibox/polkit/50-zeus-aibox-managed-fleet.rules.in`). 광범위한 zeus unit 권한을 주지 않는다.
- unit(`zeus-aibox-managed-fleet.service`, `KillMode=control-group`, bounded restart, `RestartPreventExitStatus=78 2`)의
  ExecStart는 host launcher `launch --role managed-fleet`: fence, activation receipt, owner의 Fleet owner 기록
  (`fleet-owner.json`), bootstrap Fleet unit 정지 관측을 확인한 뒤 안정 컨트롤러 코드의
  `managed_runtime supervise --state-dir <root>/runtime/managed-fleet`를 exec한다. `supervise`는 (재)시작마다
  launch request·target 스냅샷·descriptor·sealed manifest·stop 요청·직전 instance 생존 여부·Fleet activation gate
  (pause 후 settled debt)를 재검증하고, 통과 시에만 기존 `launch`(run_owned)를 unit 자신의 cgroup에서 실행한다.
  미해결 debt는 새 작업을 거부한다.
- **단일 runner**: owner가 `fleet-owner.json`을 기록하면 bootstrap `fleet` 역할은 `fleet_owner_managed`로 거부되고,
  managed 역할은 bootstrap unit이 inactive/failed로 관측될 때만 시작한다.
- **레이아웃 구분**: `/srv/zeus/releases/current`는 안정 컨트롤러(delivery controller, owner-actions, launcher/supervise)
  코드다. 후보 runtime의 실제 소비 identity는 managed target descriptor + sealed runtime root + startup receipt다.
  둘은 분리되며 `current`를 후보 identity로 쓰지 않는다.
- `zeus-aibox-owner-actions.service`: `owner-actions run --policy $ZEUS_OWNER_ACTIONS_POLICY`의 gated wakeup loop.
  idle tick은 모델 호출·쓰기·프로세스 시작이 없다.

### 14.5 고정 수용 행렬 (구현 시험; 모든 모델·canary·systemd는 labelled fixture/simulation)

| 고정 검사 | 시험 |
|---|---|
| accepted/rejected/unknown 범위 평가 | `test_owner_actions.py` accepted → 영수증 → 기존 tick 보류 해제; rejected·blocked·unfinished → 이름 있는 종결, 재호출 없음 |
| stale/혼합 attempt 구성 | 변경된 attempt → 이전 action refused, 영수증 없음; 실제 혼합 원인 family → schema-2 조립·수용·1회 해제 |
| 모델 전/후, 영수증 후, Git 게시 전/후, 등록 후 crash | spawn 실패 → 1회 재launch; 응답 유실 → 재호출 없음; `invoking` 후 crash → 동일 영수증 cached; Git 전/후 fault → commit 1개; 등록 응답 유실 → cached |
| 중복 wakeup, 중복 호출/효과 없음 | 두 coordinator·재시작 반복 tick에서 store/Git/lane 불변, launch 1회 |
| 정확한 plan 권한 | owner policy + release 기록만; 미승인·타 repository·target 사용 중·다른 ref 내용 → 게시 없음 |
| canary rejected/unknown 활성화 불가 | 실제 process target: 요청 일치 시 pending, 통과 receipt만 ACTIVE; deadline·실패·불일치 → rollback; unknown canary → receipt 없음 → rollback |
| managed materialization 재사용 | 기존 `test_managed_runtime.py` 불변 통과 + systemd kind 동일 경로 |
| delivery controller 재시작 후 소유 명확 | 새 controller 객체가 실행 중 instance를 인식, 두 번째 start 없음 |
| target 재시작/replay, 두 번째 Fleet 없음 | 활성 unit start 재요청 no-op; crash 후 restart는 같은 검사로 새 instance 1개; 이전 child 생존 시 `previous_instance_alive` 거부 |
| source fence/debt가 시작 차단 | launcher fence·activation·owner 기록·bootstrap 상태; supervise debt held/unknown/gate down 거부 |
| 정확한 실제 receipt/heartbeat | sealed runtime 자기 startup receipt·idle heartbeat, launch request·supervisor journal |
| predecessor rollback | systemd 결합에서 실패 후보 → 정확한 predecessor 재시작(`systemctl start`만) |

### 14.6 이 구현이 증명하지 않는 것 (live qualification 잔여)

실제 Codex/Claude 호출, 실제 canary, 실제 systemd cgroup·재시작·polkit 동작, PG/Redis 실측, B1–B5 finite
qualification. unit·polkit·정책·target registry·continuation/backlog 설정 설치는 owner 조치이며 이번 세션에서
수행하지 않았다. 후보 unplanned restart는 새 instance id를 만들므로 다음 delivery는 기존 `target_instance_mismatch`
게이트로 보류될 수 있다(안전 방향, owner 조정 필요).

## 15. Delivery requalification D1–D6 구현 프레임 (2026-09-26 추가)

출처: `RESULT-delivery-requalification-design.md`(설계)와 `delivery-requalification-design-owner-review.md`(수용 +
구속 교정). 기준: `origin/main` = `deab096ccc1fca3593d94a1b00266df43c9823fe`(작업 시작 시 원격 재확인, 변화 없음).
브랜치 `fix/delivery-requalification`, 격리 worktree `delivery-requalification-001`. 이 절은 1–14절과 PR206/owner
upgrade 수용을 바꾸지 않는다. 구현 명세이며 GitHub 운영 검증이 아니다.

### 15.1 구속 교정 (owner review; 설계보다 우선)

1. **push 결과는 ref별 전체 상태로 분류한다.** `refs/heads/main` 한 줄의 `[rejected]`·`[remote rejected]`만 확정
   거부(효과 없음)다. `[remote failure]`, 상태 줄 없음·형식 오류·다른 ref·중복 줄, timeout, transport 오류는 모두
   unknown이며 재시도·withdraw 전에 원격 이력과 PR로 reconcile한다(원격이 이미 candidate인 lost-response 포함).
2. **fast-forward 전용.** lease push 전에 `is_ancestor(candidate.base, candidate.revision)`을 명시 검사하고, lease는
   항상 `--force-with-lease=refs/heads/main:<base>`(완전 ref + 정확 기대값)이다. 추적 ref 약칭·`--force`·허용적
   refspec은 쓰지 않는다. divergent 후보는 push 0회.
3. **U1 교정.** 서버가 old-id를 무시한다면 사후 tree qualification은 덮어쓴 main을 되돌리지 못한다. 근거는 문서화된
   git receive-pack old-id 계약 + 명시적 ancestry다. bare-repo 시험은 stock Git 동작의 증거일 뿐 GitHub 운영 증거가
   아니다. GitHub 고유 수용·권한은 미실행으로 남긴다.
4. **새 효과 전 기존 게이트 유지.** 새 push 전에 PR 정체(OPEN, 같은 head)와 plan의 required check 통과를 그 시점
   관측으로 다시 요구한다. 이력 기반 인식(R1/R2)은 이미 일어난 효과의 복구이지 새 push 권한이 아니며, 간접 PR 인식은
   CI 승인이 아니다. 레거시 `Deployment`의 review/check 권한은 그대로 둔다.
5. D2 미정착 target 검사는 `failed`/`blocked`이면서 descriptor가 묶였고 rollback 검증이 없는 intent도 멈춘다. D4의
   terminal 분류는 switch 안전 증명이 아니다.
6. D3 `merged_tree_mismatch` 예외: host 미접촉일 때만 은퇴를 허용하되 `merged_revision`/효과 이력을 보존하고 "GitHub
   효과 없음"으로 표기하지 않는다(`main_effect: merged`). intent 기록 후 `queue.finish` 전 재실행은 외부 효과 없이
   queue 종결만 reconcile한다.

### 15.2 SSOT 재사용/확장 결정

| 소유자 | 결정 |
|---|---|
| `GitWorkspace` (INV-RELEASE-001) | 확장: `merge_state` 읽기 전용 관측, GitHub merge = ancestry + lease fast-forward, `MergeRefused`. `gh pr merge` 호출 제거 |
| `HostDelivery` (INV-HOST-DELIVERY-001) | 확장: pre-merge 관측·predecessor 바인딩, 새 push 전 PR/check 재검증, terminal `withdrawn`, `withdraw` |
| `ReleaseQueue` | 재사용(변경 없음): withdraw의 fence는 tick과 같은 enqueue+claim/finish(거부 시 defer) |
| `OwnerActions` (INV-OWNER-ACTIONS-001) | 교정: busy 규칙이 `host_delivery_plans`까지 읽음(SPEC 14.3) |
| `Continuation` (INV-CONTINUATION-001) | 확장: owner 문서 `continuation-delivery-requalification:1`, 상태 `superseded`, 경로 `requalification`(capacity grant 선례) |
| 새 scheduler·새 승인 권한·plan 스키마 변경 | 없음 |

### 15.3 고정 수용 행렬 → 시험 위치

| 행렬 항목 | 시험 파일 |
|---|---|
| 현재 후보 lease push 1회, `gh pr merge` 미호출 / divergent 0 push / main drift(사전·race) / 확정 거부 / `[remote failure]`·timeout·형식 오류 unknown(원격=candidate 및 원격=base) / 로컬 ff 실패 | `tests/test_git_merge_cas.py`(bare repo, 네트워크 없음) |
| publish 전 drift, merge 전 drift, predecessor in-flight/moved/미정착 failed, H1/H2 모양, lost response, unknown push, 외부 merge(같은/다른 tree), PR·check 게이트 유지, 재시작·중복 tick | `tests/test_host_delivery_requalification.py`, `tests/test_host_delivery.py`(post-merge CAS 유지) |
| withdraw 성공·replay cached·conflict·거부 코드·fence·queue-finish 틈·재시작 후 비선택·요청 파일 보존·CLI | `tests/test_host_delivery_requalification.py`, `tests/test_host_delivery_cli.py` |
| D4 busy 규칙(intent 없는 등록 plan) | `tests/test_owner_delivery.py` |
| requalify 성공·replay·conflict·거부·crash 사이·중복 admission·실패한 대체·route-set audit·manifest base | `tests/test_continuation_requalification.py`(기존 `tests/test_continuation.py` 표 검사 유지) |
| 레거시 `Deployment` merge 호출자 | `tests/test_release_runner.py`(기존 유지) |

### 15.4 수정 파일

`adapters/git.py`, `adapters/host_delivery.py`, `application/host_delivery.py`, `domain/host_delivery.py`,
`application/owner_actions.py`, `domain/continuation.py`, `application/continuation.py`, `adapters/continuation.py`,
`adapters/continuation_cli.py`, `docs/contracts.md`, `docs/zeus/operations/autonomous-operation-001/HOST-DELIVERY.md`,
`CONTINUATION.md`, 이 SPEC, 위 시험 파일. `_prepare_switch`, host adapter, canary, `Releases`, `ReleaseQueue`,
deploy/unit/설정 파일은 변경하지 않는다.

### 15.5 이 구현이 증명하지 않는 것

GitHub 서버의 old-id 강제·권한·간접 merge 표시 시점(U1/U2), 운영 PG/Redis, 실제 withdraw/requalify 실행(R0–R7은
Codex 수용 후 owner 조치), controller 재시작. controller hold는 유지된다.
