# baldrix validators 002 정적 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 `baldrix:scripts/validators:002` **24개, 154,041바이트 전문을 읽었다.** scope SHA는 `52b3115d99350cd64144a35b4b1dc0398ec925bbaf8d24555eba83b42d43743a`다. 전문 독해와 파일별 의미 검토만 완료했다. 상류 실행·테스트·프로브는 **0**이며 전체 분석 완료 및 흡수 승인은 **false**다.

가장 중요한 결론은 검사 이름·builtin 등록·PASS 출력이 실제 방어를 보장하지 않는다는 것이다.

- `subprocess_decode_guard`는 builtin이지만 blocking 판단에 졸업 상태도 요구한다. 실제 `graduation.TRACKED`는 다른 두 검사만 허용한다. 이 고정 revision의 정상 졸업 API로는 해당 검사를 blocking으로 올릴 수 없다. 부모 디코딩 문제를 탐지하는 발상은 유용하지만 Windows/Linux/WSL 실행 증거를 대체하지 않는다.
- `skill_staging_isolation`은 허용 루트 변수 이름과 경로 왼쪽만 믿고 절대경로·`..`·`.parent`를 안전하게 처리할 수 있다. 런타임 가드는 자동 강제가 아니라 호출자 책임이며 읽은 detector 쓰기 지점에는 가드 호출이 없다. 후보 ID 전체 생성 경로는 미독이므로 실제 침해 재현으로 주장하지 않는다. 지원 테스트는 실패를 출력만 하는 경우도 있어 pytest 통과와 방어 성공을 구분해야 한다.
- `spec_roundtrip`은 feature의 ID 집합을 비교한다. 지원 테스트는 feature 복사만으로 100%를 기대하며 step 구현이나 실행된 assertion을 요구하지 않는다. 빈 bundle·ID 없는 scaffold의 clean과 행동 검증 성공을 구분해야 한다. Zeus SDD에는 요구 의미·ID 재사용·retire·nooverwrite export와 실제 인수 결과를 별도로 유지해야 한다.
- `producer_consumer_coherence`는 전역 이름·키 존재를 실제 연결처럼 사용한다. 다른 함수·프로젝트·테스트의 같은 이름이 미연결 기능을 가리고 Markdown 부분 문자열도 연결로 인정된다. 코드의 면제 주석은 독립 승인과 같지 않다.
- mock review 검사는 과거 attestation 한 건이나 문서 하나의 변경으로 clean이 될 수 있다. emitter가 caller에게 받은 이름·SHA를 기록했다는 사실은 사람 인수·신원·현재 revision 승인 증거가 아니다.
- 스킬 품질 검사는 섹션 이름·줄 수·라벨·토큰 존재를 센다. 실제 source 인용·품질·보안·모델 자격을 검증하지 않는다. Source liveness는 인증 오류 후 SSL 검증을 끄는 fallback과 DEAD/NETWORK 이후 PASS가 있어 신뢰 게이트로 채택할 수 없다. 원문 링크와 ISO 표준은 이번에 확인하지 않았다.

검사 분모도 다르다. 파일 없음·읽기 실패·파싱 실패·미지원 스택·면제 문서를 PASS에 섞는 경로가 있고, Gotchas를 한쪽은 소제목 수, 다른 쪽은 bullet 수로 센다. `validate_project`의 실제 13개 routing 중 이 파티션에서는 prd/openapi/skeleton/test 네 개만 호출된다. 다른 builtin 검사가 이 CLI에서 실행된다고 추론할 수 없다. main 반환값을 버리고 stdout 토큰을 해석하는 소비자는 WARN과 다른 SKIP 문구를 PASS로 분류할 수 있다.

Zeus에는 정적 lint를 관찰 결과로 변형하는 방안을 검토한다. Git 정의와 PostgreSQL 런타임 정본, exact-revision 실제 실행 영수증, 권한·모델 자격·독립 검토를 이 lint의 성공 횟수로 대체하면 안 된다. 현재 Zeus 구현 본문은 이번 파티션에서 새로 읽지 않았으므로 대응 모듈은 설계 매핑이며 동등성 주장이나 구현 반영이 아니다.

[파일별 원장](files.json), [상세 의미 기록](semantic-notes.json), [추가 독해 및 정정](final-body-notes.md), [지원 파일의 실제 읽은 행·해시](supporting-evidence.json), [checkpoint](checkpoint.json)를 남겼다. 최초 9개 checkpoint 원시 바이트는 보존했다. 초기 spec_bundle 경로 산술 추정은 loader 독해 후 정정했고, 발견 범위와 cwd 불일치는 남아 있다.

직접 지원 20개 파일은 기록된 구간만 읽었다. 이전 파티션 primary와 겹친 지원은 새 primary로 승격하지 않았다. 전체 caller/config/test 전이 closure, 실제 OS·예외·격리·인수 실행, 라이선스/외부 링크, 독립 공동 검토는 남아 있다. 차단 probe를 재시도하거나 우회하지 않았으며 원본·runtime·공유 coverage·구현·commit·push는 변경하지 않았다.
