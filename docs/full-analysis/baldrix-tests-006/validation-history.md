# 기록 검증 이력

원본 프로그램은 실행하지 않았다. 자체 기록기 첫 실행(도구 chunk 70a320)은 supporting 범위의 끝 261이 실제 EOF 257을 넘는다는 assert에서 중단했다. 이는 독해 성공이나 source 시험 실패로 계상하지 않는다. 실행 당시 기록기는 record_review.range-failure.executed.txt로 보존했다. 실제 마지막 241~257행을 다시 읽은 chunk 5f75b0으로 확인하고 범위만 257로 정정했다. 정정 후 기록기 실행 e70be4는 24개/198562바이트, supporting 29개, Git blob/bytes 일치를 확인했다. 첫 실행의 Ruff는 통과했으며 최종 검증 결과는 metadata-check.json에 기록한다.

기록기는 tests004의 메타데이터 구조를 출발점으로 사용했지만 scope/HEAD/primary bytes와 모든 supporting 명세를 이번 실제 독해에 맞춰 바꿨다. 이전 검토 결론이나 primary 전문을 재사용한 것이 아니다. 원시 source·공유 원장·운영 상태·기존 보고서는 수정하지 않았다.

최초 metadata 검사(39e3ac)는 검사 코드 자신의 물음표 탐지 리터럴을 손상으로 오인해 중단했다. 당시 코드는 check_metadata.self-scan-failure.executed.txt에 보존했다. UTF-8 검사는 모든 텍스트에 유지하고 반복 물음표 검사는 설명 문서와 JSON으로 한정했다. 이 중단으로 artifact index가 생성되지 않아 후속 해시 조회도 해당 파일 미존재를 출력했다. 최종 재실행에서 생성·재검증한다. review.md 한국어 본문은 같은 chunk에서 실제 readback하여 의미 보존을 확인했다.
