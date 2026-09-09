# Baldrix CLI 002 — 독립 정적 의미 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, 파티션 `baldrix:scripts/cli:002`의 22개 파일 191,539바이트를 전문으로 읽었다. 다른 리뷰 문서를 먼저 참고하지 않고 소스에서 판단했다. 파일별 한국어 근거는 `semantic-notes.json`, 고정 SHA·호출·의존·테스트 연결·Zeus 대응·미해결은 `files.json`에 있다. source SHA와 크기가 모두 manifest와 일치한다.

본문은 22/22 완료, 미독 0개다. supporting은 전문 8개와 session init 701–725행의 부분 읽기 1개다. supporting을 primary coverage로 중복 승격하지 않았다. 나머지 호출·테스트·설정 검색 줄은 검색 증거로만 표시했다. **테스트 실행은 요청에 따라 0회**다. 본문 독해와 모든 subsystem 검증은 다르므로 `body_coverage_complete=true`, `partition_complete=false`, `adoption_ready=false`로 기록한다.

## 주요 발견

- **Heartbeat 경보 발행이 조용히 실패한다.** `heartbeat_check._raw_event_emit`가 가져오는 `lib.event_store.append`는 해당 모듈 전문에 없다. 존재하는 것은 `EventStore.append` 메서드다. import 실패를 삼킨 뒤 CLI가 0을 반환하므로 stale 목록 출력과 경보 저장 성공이 다르다. taxonomy 경로의 추가 구현은 미검토다.
- **오염 측정과 제거 정책이 연결되지 않는다.** measure가 계산한 tuned threshold는 histogram JSON에만 남고 detect는 고정 250ms/3개를 사용한다. ready flag는 `validated` 문자열 파일의 존재만 보며 입력 hash·정책·시각·actor에 바인딩하지 않는다. measure는 빈 데이터에도 flag를 만들고 fallback 임계값이 기준을 만족하는지 재평가하지 않는다. detect는 retract 실패가 있어도 flag를 삭제하고 exit 0을 반환한다. 다른 bulk CLI의 backup/plan 경로를 거치지도 않는다.
- **이 실패는 cron까지 전파된다.** 전문으로 읽은 `cron/run_pollution_cleanup.py`는 measure와 detect를 subprocess로 실행하고 return code가 0이면 성공으로 간주한다. 따라서 일부 retract 실패에도 advisory를 ack하고 cleanup flag를 소비할 수 있다. subprocess timeout도 없다. cron 함수가 실제 등록·승인되어 실행됐다는 뜻은 아니며 운영 실행은 하지 않았다.
- **마일스톤 되감기의 크래시 복구가 불완전하다.** Git 커밋, `ms.rewind_applied`, 다음 `ms.started`가 각각 별개다. 커밋 직후 기록 전 크래시에는 중복 되감기가 가능하고, applied 이후 started 전 크래시에는 재실행이 이미 처리됨으로 멈춰 round 전진이 누락될 수 있다. “커밋 실재 확인”이라는 문서와 달리 멱등 guard는 문자열 존재만 확인한다. `--repo`와 스파인 저장소 동일성, explicit/base revision의 경계 검증도 부족하다. 실패한 `git revert --abort` 결과를 확인하지 않는다.
- **Spine의 입력 경계와 증거 검증이 약하다.** sid regex는 빈 문자열, `.`와 `..`를 허용한다. checklist hash는 12자리 SHA1이며 읽을 때 실제 내용 hash를 확인하지 않는다. `known_good_rev`는 기록된 non-pass만 제외하므로 사람 판정이 없는 항목까지 검증 완료로 간주할 수 있다. 원장에 적힌 actor와 evidence 문자열은 권한·증거 진실을 입증하지 않는다.
- **Greenfield의 승인과 신규 출력은 문서 조건이다.** human-approved draft를 검증하는 기록·권한 gate가 없고, 기존 feature/test를 덮어쓰며 domain 및 생성 경로 이탈 검증이 없다. 하나의 package 변수를 두 생성기에 전달하는 연결은 확인했지만, 그것이 요구 의미나 실제 테스트 발견·RED 실행을 증명하지는 않는다. 읽은 테스트도 파일 내용과 구조 검사이며 Gradle 실행은 아니다. 알 수 없는 stack은 JVM으로 조용히 fallback할 수 있다.
- **정규화 PASS는 계약 완성이 아니다.** harness/kha normalizer는 존재하는 파일만 검사하여 누락 파일 또는 빈 검사 집합을 성공으로 표시할 수 있다. TODO heading도 유효 section으로 인정한다. pipeline generator의 `--check`는 생성물과 비교하지 않는 summary mode다. gsd→kha 삭제는 target 동등성과 전체 참조를 증명하지 않으며, 앞 단계 실패 후에도 delete 단계로 진행할 수 있다.
- **그래프와 상태 지표가 실제보다 강한 결론을 낸다.** shared wire 문자열이 없다고 fleet 전체가 disjoint라는 결론을 낼 수 없다. blocked·입력 누락과 의미적 무관계는 다르다. endpoint의 `--json --llm`은 JSON 뒤 설명 텍스트를 출력한다. HUD는 untracked를 제외한 Git 상태를 uncommitted 수로 보여주고 UTC timestamp를 local time으로 바꾼다. 파일·테스트 개수와 건전성은 구분해야 한다.

## 호출·설정 연결과 문서 모순

session init의 `_milestone_liveness_line` 전문 구간은 이미 lib scan을 호출한다. main의 해당 함수 호출은 793행 검색으로 확인했다. 따라서 CLI docstring의 “배선 전, 수동 호출만”은 현재 소스와 어긋난다. 다만 init 전체와 실제 hook configuration은 검토하지 않았으므로 live hook 등록 인증으로 올리지 않는다.

`commands/harness-milestone.md`는 feedback, rewind, liveness 호출을 안내하고, `harness-greenfield.md`는 emit 호출 전 승인 절차를 설명한다는 검색 연결을 확인했다. 문서 전체를 읽거나 실제 승인 과정을 실행한 것은 아니다. 이 지시는 현재 작업에 상속하지 않았다. 모든 경로별 직접 import와 발견된 caller/config/test 줄은 원장에 남겼으며, 검색 결과가 없는 것을 호출 불가능으로 단정하지 않았다.

## Zeus 대응과 남은 검증

CLI는 application use case를 호출하고 정책은 domain에 두는 경계를 유지한다. 상태·경보·마일스톤 기록은 PostgreSQL 권위, 정의·정책·생성물 제안은 Git 권위로 묶어야 한다. six-W, source/current revision, generation/lease, immutable artifact, 실제 실행 receipt와 독립 연구 책임자·conductor gate를 대신할 파일 flag나 문자열 token은 채택하지 않는다. SDD 출력은 준비/제안 단계로 유지하며 독립 승인과 인수 증거 전 배포 권한으로 올리지 않는다. 이는 구조적 대응 제안이지 현재 Zeus 코드 전체의 동등성 인증이 아니다.

seam_scan/narration/providers, pipeline merge/config/golden outputs, graduation/audit, spec emit/testgen/scaffolders, handoff parser, health producer, heartbeat/taxonomy, insight store, milestone gate/liveness/verdict와 각 전이 의존 구현은 추가 검토가 필요하다. 읽은 테스트는 greenfield와 harness normalizer 두 파일이며 모두 not run이다. 나머지 tests는 검색 연결만 있다. 원본 라이선스·외부 논문/링크·개인 state 보고서·과거 commit 실적도 미확인이다. 생성기 원본과 출력의 byte/semantic 동등성은 아직 주장하지 않는다.

이번 파티션에서는 upstream 실행, 운영 state 접근, 원본/설정/src 수정, commit/push를 하지 않았다. 산출물은 `C:/Users/rudtn/zeus/docs/full-analysis/baldrix-cli-002/`에만 작성했다. 지정 22개 본문 범위에서 중지한다.
