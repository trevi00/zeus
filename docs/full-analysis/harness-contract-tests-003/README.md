# Harness contract tests 003

고정 revision `a3f8b3be9a0a389329de6e16a6c7db81782041a3`의 16개, 178,523 bytes를 전문 정적 검토했다. [review.md](review.md)에 파일별 오라클·fixture·분모·현재 방어·남은 공백을 기록했다. [files.json](files.json)은 원문 해시와 판단 연결, [supporting.json](supporting.json)은 실제 읽은 지원 35개 구간, [prior-ledger.json](prior-ledger.json)은 이전 원장의 정확한 행과 해시다.

직접 연결에서 확인한 주요 공백은 PATCH_GATES 표현식을 읽지 못해도 이연 경로를 허용하는 검사, 손상된 측정 시각에서 재측정을 건너뛰는 스케줄, launcher의 rc=0만으로 훅 실행을 확인하는 시험이다. 현재 사다리 정책과 과거 advisory fixture도 구분했다.

자체 기록기의 byte/blob/SHA·구간·참조·UTF-8/LF 검사와 Ruff 결과는 validation.json에 기록한다. 원본 시험·import·probe·network·install 및 live/인증정보 접근은 0회다. 자체 검사 통과는 원본 시험 통과가 아니다. 전체 closure, 실제 Claude 공동 검토, 라이선스, Windows/Linux/WSL, 사람 인수, 모델 자격, Zeus 등가 구현 및 채택은 미완료다. 원본·runtime·공유 coverage·구현·commit/push를 변경하지 않았다.
