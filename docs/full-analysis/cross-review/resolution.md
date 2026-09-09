# Codex–Claude 교차 검토와 정정

실제 Claude 세션 `311d6fca-5cb4-4122-a88b-7f6b55b1735e`의 첫 독립 검토와 후속 논의다. Read/Glob/Grep만 허용했고 구현·실행은 주 Codex가 담당했다. `claude-initial.md`와 두 JSON receipt, `claude-discussion.json`을 보존한다. 지정 경험/Guardian 논점의 검토이며 전체 2,736개 추적 경로나 추가 로컬 자산의 전수 검토를 대체하지 않는다.

## 합의된 부분

- 원본 레코드 identity와 내용 중복 그룹을 분리한다. 회수는 원본 identity로 적용하고 동일 내용의 다른 유효 출처를 함께 회수하지 않는다. pinned/observed는 별도 출처 버전이다. Temp 경로·fixture처럼 보이는 시각만으로 테스트 오염을 확정하지 않는다.
- curator의 전역 PASS 누계와 harvest 반복은 독립 검증 횟수가 아니다. source occurrence/trust/evidence는 원본 주장으로 보존하며 Zeus의 승인·자격·재발 횟수로 승계하지 않는다.
- 외부 경험은 별도 provenance와 예산을 가진 자문 자료다. diagnose가 workload=design으로 표시되므로 workload만으로 주입을 허용하면 안 된다. 리뷰/판정 경로는 별도 정책으로 보호한다.
- 실제 source-body 로컬 경로와 Zeus artifact handle을 구분한다. 출처 문자열을 유효한 artifact 참조처럼 취급하지 않는다.
- Guardian console의 readable secret/같은 origin HTML과 host worktree 복원은 그대로 옮기지 않는다. 감시·복구·통지의 목적은 Zeus의 현재 권한, PostgreSQL, release image/CAS 경계로 다시 구현한다.
- Baldrix limit=0의 전체 반환과 점 성분 SID 허용은 API 경계 결함이다. 다만 추적한 autopilot 호출자의 SID는 기존 로컬 상태 파일에서 오므로 외부 입력을 통한 임의 파일 접근이 이미 입증됐다고 과장하지 않는다.

## Claude가 정정한 부분

Guardian restorer 최초 source-only 실행은 설정 의존으로 실패했다. 합성 config와 고정 harness sibling을 격리 제공한 뒤 pinned/observed 스위트가 통과했으므로 이전 not-run 결론은 해소됐다. 실패와 성공 영수증 모두 유지한다.

message-id 중복 제거와 notification tail 잘림 감지는 다른 문제다. 기존 중복 제거가 있다는 이유로 해시 체인의 목적 전체를 기각한 근거는 철회했다. Zeus PG outbox는 위치 watermark가 없으므로 같은 잘림 형상은 없고, 전달 단계별 증거는 별도로 매핑한다.

인간용 cp949 산문 출력 정책을 JSON/기계 채널에 일반화하지 않는다. Zeus CLI JSON stdout의 UTF-8 계약은 유지한다.

## 주 Codex가 후속 논의를 다시 점검한 부분

Claude는 상위 Docker env가 UTF-8이므로 Guardian encoding suite가 cp949 축을 재지 않았다고 적었다. 이는 **해당 스위트에 대해서는 잘못된 결론**이다. `test_console_encoding_smoke.py:_cp949_env`가 자식 env를 `PYTHONIOENCODING=cp949`로 덮어쓰고 UTF8 모드를 제거하며 보호 없는 실패 대조군도 실행한다. 따라서 cp949 pipe 경로는 실측됐다. 다만 Windows 콘솔 호스트 직결, 실제 tasklist/OS scheduler는 여전히 별도 미검증이다.

또한 Zeus `bus.publish`는 단순 전송 시도만 하고 반환하는 함수가 아니다. Redis XADD 응답을 기다려 stream ID를 반환하고 오류는 예외로 전파된다. `flush_outbox.sent`는 broker publication 성공을 의미하며 최종 소비자 처리/사용자 알림 수신 확인은 아니다. 기존 Redis pending/ack·inbox 멱등을 무시하고 'ACK가 전혀 없다'고 해석하지 않는다. 최종 알림 확인이 필요한 요구에는 별도 destination receipt를 설계한다.

`LocalEmbeddings`는 FastEmbed 모델 이름과 캐시 디렉터리, threads=2, batch_size=8만 지정한다. 이 코드 읽기로 모델 바이너리/런타임/플랫폼 간 벡터 결과의 동일성을 보장할 수 없다. deterministic retrieval 주장을 하려면 모델 artifact·tokenizer·runtime·입력 정규화·수치 허용오차를 추가 결속하고 실제 반복/환경 검증해야 한다. 어휘 검색의 결정론과 분리한다.

## 현재 Windows에서 실제 재현한 결함

`windows-encoding-probe.json`은 현재 `.venv` Python과 실제 `run_process`를 호출한 영수증이다. native default, 명시 locale mode, cp949 adversarial, 실제 verification_environment를 거친 locale mode 네 경우 모두 비-cp949 문자를 출력하다 rc1/UnicodeEncodeError였다. 자식 `PYTHONIOENCODING=utf-8`을 명시한 같은 출력은 rc0이었다. verification_environment는 부모가 지정한 PYTHONIOENCODING/PYTHONUTF8도 허용목록에서 제거한다.

따라서 부모의 UTF-8 decoding 설정만으로 기계 채널 계약이 완성되지 않는 결함은 현재 환경에서 확인됐다. 이 프로브는 데이터베이스에 연결하지 않았고 release 후보 거부 전체 흐름을 실행하지 않았다. 배포 전체 실패를 재현했다고 주장하지 않는다. 수정 후보는 Python 기계 채널에 명시 인코딩을 주입하는 것으로, 모든 외부 프로그램/사용자 터미널의 인코딩을 무조건 바꾸는 조치는 아니다.

신규 구현은 전체 분석 요청에 따라 보류 중이다. 이 합의는 설계 입력이며 기능 도입 승인·배포 승인을 생성하지 않는다.
