# PreTool·Notification·Tool 훅 정적 검토

고정 baldrix revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`에서 다음 네 파티션의 **16개, 68,829바이트 전문**을 읽었다. 원본 실행·테스트·프로브는 **0**이다. 전문 독해 완료와 전체 전이 검증·흡수 승인을 분리하며 후자는 **false**다.

| 파티션 | 파일 | 바이트 |
|---|---:|---:|
| baldrix:scripts/handlers:001 | 1 | 79 |
| baldrix:scripts/handlers/notification:001 | 4 | 7,095 |
| baldrix:scripts/handlers/pre_tool:001 | 9 | 55,823 |
| baldrix:scripts/handlers/tool:001 | 2 | 5,832 |

가장 중요한 발견은 다음과 같다.

- critic advisor가 자신의 환경변수를 바꿔도 별도 프로세스로 등록된 post hook에는 전달되지 않는다. 후속 소비자는 `invoke`라는 **결정**을 `critic_invoked`라는 **실행 사실**로 저장한다. 실제 critic 호출·verdict·task identity가 필요한 Zeus 승인 증거로 쓸 수 없다.
- depth guard는 env를 읽고 deny JSON을 만들지만 증가·전파를 수행하지 않는다. 지원 테스트는 깊이를 직접 주입한다. 실제 nested Agent 계보와 권한 정본은 확인하지 못했다.
- PR guard의 통상 `--squash`/`--base` 앞 word-boundary regex가 해당 플래그를 놓칠 수 있다. legacy `PENDING`과 `COMPLETED`이면서 conclusion이 없는 경우도 clean으로 분류될 수 있다. hook 설정5초는 gh 조회8초보다 짧다. 이는 정적 도출이며 실행 재현은 하지 않았다.
- general guard는 regex와 도구 이름에 의존한다. solo 예외에 첫 match가 걸리면 compound command의 뒤쪽 위험 규칙을 검사하지 않고 끝난다. malformed Bash 일부는 deny지만 Write/Edit 내부 오류는 WARN으로 통과한다. 실제 OS 쓰기 권한 경계를 제공하지 않는다.
- notification은 unknown type이 비어 있으면 trigger 필터를 통과하고, 전달 실패에도 exit0이다. hook10초와 요청당10초·기본4회 재시도 계약이 맞지 않는다. 중복 방지·수신 확인·secret 제거·송신 권한은 별도이며 smoke test는 ambient 설정을 그대로 사용한다.
- 회사 Dart 규칙·TODO/한국어 문구 경고·HANDOFF drift는 제한된 문자열/문서 관찰이다. 실제 컴파일·사용자 의도·critic 수행·인수·commit될 bytes의 검증과 다르다. branch guard도 단순 lowercase prefix와 첫 matching rule을 사용해 경계·중첩 repo·Linux 대소문자·쓰기 직전 race가 남는다.

직접 지원15개 파일의 실제 읽은 구간과 이전 지원2개의 재사용 해시를 별도로 기록했다. source settings의 등록은 확인했지만 현재 효력 있는 merged/live 설정과 Claude runtime의 응답 소비는 확인하지 않았다. Windows 절대경로의 Linux/WSL 이식도 실행 검증하지 않았다. 외부 플랫폼 문서·연구 수치·회사 원문·라이선스는 미확인이다.

Zeus에는 advisory와 외부 adapter 발상을 제한적으로 변형 검토할 수 있다. Git 정의·PostgreSQL 런타임 정본, 모델 자격과 권한, task/revision에 묶인 실제 실행 영수증을 문자열 PASS·invoke 결정·문서 존재로 대체해서는 안 된다. 현재 Zeus 본문을 새로 읽지 않았으므로 대응은 설계 매핑일 뿐 구현 동등성이나 흡수 완료를 주장하지 않는다.

[파일별 전문 기록](file-reviews.md), [coverage 호환 원장](files.json), [지원 구간·해시](supporting-evidence.json), [재사용 지원](reused-support.json), [checkpoint](checkpoint.json)에 상세 근거와 미완료를 남겼다. 공유 coverage·원본·runtime·src/tests·commit/push는 수정하지 않았다.
