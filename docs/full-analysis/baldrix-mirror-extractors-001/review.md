# mirror extractors 한정 검토

4개 17,868바이트를 새로 전문 독해했다. 고정 revision은 cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2이며 원본/테스트 실행은 0이다.

핵심 결함은 fingerprint의 의미다. normalize는 문자열 공백과 multiline 문자열의 주석처럼 보이는 줄을 바꾸므로 의미 변경을 놓칠 수 있다. coarse도 원시 바이트가 아니라 디코딩·줄바꿈 변환 후 텍스트이며 경로 정체성과 읽기 실패를 hash에 보존하지 않는다. 따라서 clean은 SDD 검증 또는 원문 동등성을 뜻하지 않는다. Cargo 구조 추출은 AST 전체가 아니고 git 실패를 빈 결과로 낮추는 경로가 있다.

직접 caller는 fast path와 fail-open, mode 변경 뒤 hash 불일치 및 manifest 선행 저장의 부분 성공 가능성을 추가한다. 테스트의 같은 함수 재계산 일치는 독립 의미 오라클이 아니다. Zeus에서는 Git raw blob/path/type와 추출 버전·scope를 결속하고 PG 영수증에 미확인 분모를 유지해야 한다. advisory 구조 인덱스만 변형 후보이며 실제 승인·인수는 별도다.

세부 의미는 file-reviews.md, 정확한 지원 구간은 supporting-evidence.json에 있다. 전체 전이 폐쇄·라이선스·실제 Claude·Windows/Linux/WSL·모델 및 채택은 미완료다.
