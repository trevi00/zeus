# Engine 001 검토

[최종 공동 검토](resolution.md): 11개·80,138바이트 전문, root 지원 24개, 실제 Claude 독립 검토와 동일 세션 토론.

- 원본 retry 단위 테스트 6 PASS. 주입 callback 기반이며 실제 모델·인수 검증 아님.
- 원본 함수 격리 관측: 과거 shard가 최신 세대를 덮음, 손상 shard 삭제, phase/sidecar/ack 계약 불일치 확인. 실제 입력 파일과 원본 함수를 사용하고 mocking 없음.
- 최초 PyYAML import 실패도 당시 program/runner와 함께 보존. 성공만 남기지 않음.
- 실제 provider·worker·validator·Stop hook·실기기·Windows/WSL 원본 실행 0.

`files.json`, `supporting-evidence.json`, `checkpoint.json`은 읽기 범위와 원문 identity 기록이다. `claude-initial*`, `claude-discussion*`은 원시 검토 응답과 실행 영수증이며, 최종 문서의 정정을 함께 적용한다. 전체 분석·흡수·시범 운영 준비는 미완료다.
