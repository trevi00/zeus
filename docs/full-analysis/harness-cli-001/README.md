# harness CLI 001 체크포인트

정확한 파티션은 `harness:scripts/cli:001`이다. pinned `a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 13개, 168,396바이트 전문을 읽었다. inventory.json은 전 경로 분모, files.json은 해시와 파일별 판정, review.md는 독립 의미 분석, supporting.json은 실제 읽은 호출·설정·시험 구간이다. 모든 primary 상태는 `body_reviewed_call_test_trace_pending`으로 유지한다.

이번 **원본·테스트 실행은 0회**다. build-index.py는 원본을 import하지 않고 바이트·해시·보고서 메타만 확인한다. 주석의 과거 PASS·실측·사용자 승인·패널 리뷰는 이번 관측이나 권한으로 상속하지 않았다. 구현·runtime·공유 coverage·원본·commit·push를 변경하지 않았다. 과거 보안 차단 probe도 재시도하지 않았다.

검토에서 드러난 주요 경계는 다음과 같다.

- arming dryrun과 driver가 decide를 공유해도 safe mode·토큰·preflight를 포함한 전체 장전 조건은 같지 않다.
- autoheart dryrun은 직접 승인 기록을 하지 않아도 subprocess·worktree 부작용이 있다. home, 후보, 참조 앵커가 서로 다른 게이트의 대상이므로 전체 후보 검증으로 합쳐 말할 수 없다.
- completion의 strict 성공은 증거 경로 실존이며 내용·실행·사람 인수가 아니다. cycle의 circuit 거부도 앞서 기록한 plan/finished를 되돌리지 않는다.
- classify의 정규식 결과와 coverage의 문장 도달은 실행 영수증·요구사항 검증을 대신하지 않는다. coverage --json에는 후행 텍스트가 붙는다.
- debate actor와 캡처 operator는 이름만으로 독립 모델/사람을 인증하지 않는다. delegate의 단순 존재 검사와 전체 hooks 제거는 실제 설치분 식별과 별개다.

Zeus에서는 CLI를 application use case 어댑터로 두고 Git 정의와 PG runtime 권한을 분리해야 한다. 제안·계측·확정 판정·승인·반영은 각각 후보/정책/환경/시험 분모와 인증된 주체에 결속해야 한다. 파일 존재나 반복된 스냅샷의 수렴으로 사용자 8단계인 스펙 논의 → 디자인 분석 → 코드 작성 → 자체 검증 → 알파 배포 → QA 및 증적 → 라이브 배포 → CS 대응을 대체할 수 없다.

실제 읽은 `src/codex_harness/domain/sdd.py`의 gate_report도 구조 검증 외의 실행과 인증된 사람 결정을 요구하며 release 권한을 주지 않는다. Astra/Sol/Terra 매핑은 unqualified이고 자동 하향은 false다. 원본의 fable 카드 문자열·패널 actor·결정론 gate는 실제 모델 자격이 아니다. Windows UTF-8 진입부와 Git Bash 전제 역시 Win/Linux/WSL 실행 검증으로 확대하지 않았다.

흡수 후보는 제안과 승인 분리, 보류와 거부 구분, 미실행 분모 표면화, 실제 caller와 같은 판정 함수 공유 및 음성 방향 시험이다. 나머지 구현·권한·시험 연결과 실행 영수증, 독립 공동 검토는 remaining.json에 남겼다. 이번 결과는 bounded 전문 검토 체크포인트이며 채택 승인이나 저장소 전체 분석 완료가 아니다.
