# 외부 1차 자료 대조

2026-09-09에 읽었다. 라이브 웹의 특정 문장·구현을 대조한 범위이며 외부 저장소 전체 분석·라이선스 승인·선택한 엔진 버전의 인수 결과는 아니다.

- [Redgate Flyway versioned migrations](https://documentation.red-gate.com/fd/versioned-migrations-273973333.html): 고유 버전, 숫자 순서, 점·밑줄 구분 및 0-padding을 설명한다. 영구 환경에 이미 적용한 파일의 변경보다 새 버전으로 진행하도록 안내한다. 원본 검사기의 단순 정수 접두사 처리와 지원 범위를 비교하는 데 사용했다.
- [Flyway MigrationVersion.java](https://github.com/flyway/flyway/blob/main/flyway-core/src/main/java/org/flywaydb/core/api/MigrationVersion.java): 열람된 main 본문은 밑줄을 점으로 바꾸고 각 부분을 BigInteger로 읽어 비교한다. 이 본문에서 선행 0의 숫자 동등성을 추론할 수 있다. 움직이는 main이며 실행하지 않았으므로, 향후 선택한 Flyway 버전의 실제 동작 증거로 사용하지 않는다. Bash V01/V1 관측은 별도의 실제 실행 증거다.
- [MySQL 5.7 ALTER TABLE 검색 본문](https://dev.mysql.com/doc/refman/5.7/en/alter-table.html?source=post_page---------------------------): 공식 검색 본문은 CHECK를 파싱하지만 적용하지 않는다고 설명한다. 별도로 연 5.7 CREATE TABLE 주소는 9.7 문서로 리다이렉트되었다. 9.7 본문을 5.7 증거로 인용하지 않는다. 이 배치에서는 MySQL을 실행하지 않았다. 로컬 db-design 스킬에 이미 해당 경고가 있다는 원문 사실과 DB 인수 결과를 구분한다.

원문을 대량 복제하지 않았다. 문서의 설명·현재 source main·고정된 Baldrix 코드·실행한 Bash·미실행 DB 엔진은 서로 다른 근거다.
