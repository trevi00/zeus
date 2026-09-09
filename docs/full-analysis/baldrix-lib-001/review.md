# Baldrix lib001 정적 전문 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 `baldrix:scripts/lib:001` 25개·195,823bytes를 설명했다. 직접 새 전문21개와 동일바이트 선행 전문4개를 구분한다. 모든 primary의 raw Git blob/바이트수/SHA를 manifest와 대조했다. 선행 전문 재사용은 prior ledger·review의 해시와 원문 SHA를 묶었으며 전체 집계에서 중복 증가시키지 않는다.

가장 중요한 발견은 다음과 같다.

- `alert`는 webhook의 실패 tuple을 확인하지 않고 전송 성공처럼 표시할 수 있다. 로컬 append나 확인 ack는 원격 수신 영수증이 아니다.
- `brain_git_status`는 내용 보존 대신 ID 부분집합과 로컬 remote-ref를 검사한다. 같은 ID의 내용 변경과 오래된 remote-ref는 놓칠 수 있다. cron은 save 완료 ack와 flag 소비 뒤 push하므로 push 실패에도 완료 ack와 반환0이 가능하다.
- `brain_autopush`의 동일 home 임시 worktree는 동시 실행을 분리하지 않는다. 일부 git rm/add 반환값을 무시하고, no-change를 실제 push 없이 pushed=True로 표현한다. FF-only 방어와 별개로 권한·내용·작업자 수명 증거가 필요하다.
- keyword 6W 점수는 요구사항의 실제 구체성을 증명하지 않는다. coverage0이면 나머지 점수의 최대 합0.15가 기본 threshold0.2보다 작아 unknown marker가 많아도 통과한다. 내장 테스트의 keyword PASS는 SDD 인수로 사용할 수 없다.
- pane 존재·marker, merge 응답 JSON, 과거 commit subject, completed ack, 반복 횟수는 실제 worker 종료·결과 수집·테스트 성공·모델 자격의 대체 증거가 아니다.
- atomic 파일 교체는 동시 read-modify-write 손실을 막지 않는다. QuotaCounter도 write bool을 무시한다. TF-IDF cache의 pickle은 원본 신뢰와 권한 검토가 필요한 실행 표면이다.

선행 완료권위 검토의 empty AC 승인, 문자열 bool, predicate와 결속되지 않은 leaf ID 및 불충분한 로그 identity를 재사용했다. Stop의 retry에서 상태 필드가 사라지는 문제는 caller 재구성 문제로 구분했다. 이번 범위 전체에 대한 actualClaude 검토나 실제 실행을 주장하지 않는다.

[파일별 판단](file-reviews.md), [후속 상세 기록](notes-25.md), [파일 원장](files.json), [직접 지원 구간](supporting-evidence.json), [선행 재사용](reused-support.json), [checkpoint](checkpoint.json)를 함께 읽어야 한다. `checkpoint-15.md`는 이전 미완료 시점의 원시 기록으로 보존했으며 최종 상태는 checkpoint.json이다. 초기 기록기의 regex 누락 실패와 수정 기록기도 보존했다.

지원15개 파일은 실제 읽은 구간만 기재했다. 테스트3개 파일의 일부와 primary 내장 self-check를 읽었지만 실행하지 않았다. 소스 실행/import/probe/install, 운영 기동, 구현 변경, commit/push는 모두0이다. 과거 테스트·Claude 영수증은 해당 선행 범위에만 귀속된다.

전체 caller/config/test 전이, 원본 라이선스·외부 링크, Windows/Linux/WSL 실동작, actualClaude 영역전체 검토, Zeus 구현 동등성·모델 자격·사람 인수는 미완료다. 따라서 primary 전문 독해 checkpoint만 끝났고 partition 전체 검증 및 Zeus 흡수 승인 상태는 false다. Zeus에는 Git 정의/PG runtime, 세대·시도·실행자·원시 영수증을 결합하는 방향으로 변형 검토해야 한다.

정밀화: `replace_with_retry(tries<=0)`의 오류 미전파는 공개 helper의 비정상 인자 경로다. 기본 `write_json_atomic`는 고정 양수 기본값으로 호출하므로 그 정상 호출이 이 반례만으로 성공을 거짓 보고한다고 일반화하지 않는다. 기본 writer의 fsync 오류 무시와 caller의 write bool 무시는 별도 정적 사실이다.

기록기 실행 당시 원시 바이트는 record_review.executed.txt(실패)와 record_review_v2.executed.txt(성공)에 보존했다. .py는 실행 뒤 E741 변수명만 정리한 열람 및 재현용 사본이다. 두 버전은 실패 원인과 성공 경로를 구분하기 위한 기록이며 원본 하네스 테스트가 아니다. 해당 폴더의 ruff check는 통과했다.

Root publication check subsequently normalized CRCRLF to LF in the reading/reproduction copy record_review_v2.py. The executed .txt bytes and historical receipts remain unchanged; see root-eol-normalization.json.
