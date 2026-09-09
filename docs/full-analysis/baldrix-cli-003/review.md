# baldrix CLI 003 정적 의미 검토

고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, partition `baldrix:scripts/cli:003`의 **14개 파일, 179,681 bytes를 전문 읽고 검토**했다. 각 원시 파일의 SHA-256과 크기는 manifest와 일치한다. 전체 저장소 분석 완료나 Zeus 흡수 완료를 뜻하지 않는다. 상류 코드·테스트 실행은 **0회**다.

다른 파티션 리뷰를 읽기 전에 본문과 연결 코드를 바탕으로 판단했다. 이후 전역 집계 호환을 위해 CLI 002의 첫 `files.json` 레코드 형식을 확인했다. 처음 PowerShell 기본 디코딩으로 깨진 한국어와 출력이 잘린 구간은 UTF-8 및 분할 읽기로 다시 확인했다. AST 사용은 독해 이후 import 목록을 기록하는 용도였고 의미 검토를 대신하지 않았다.

## 주요 발견

1. **마일스톤 상태의 전체 이력이 gate 입력에 전달되지 않는다.** `milestone_step.py:575`는 현재 phase 하나만 보낸다. `milestone_gate.py:341–360`은 계획 중 누락된 첫 phase를 다음으로 고른다. 따라서 계획 `1,2`에서 phase 2가 끝나면 이미 끝난 phase 1이 다시 선택될 수 있다. 읽은 테스트는 첫 phase에서 2로 넘어가는 것만 확인한다. 실제 실행 재현은 하지 않았다. 같은 gate의 `phase_degraded_codes`는 전달된 `tier2_completeness`를 사용하지 않는다.
2. **실행하지 못한 검증이 실패 0으로 축약될 수 있다.** 전제 프로브는 JSON `ok:false` 개수만 실패로 세며, 비정상 종료 코드와 비JSON 출력을 실패로 반영하지 않는다. `--no-tier2`는 실제 Tier1·변이 실행 및 상태 쓰기를 중단하는 dry-run이 아니다.
3. **공개 토큰·자기신고 플래그는 사용자 인증이나 독립 승인 증거가 아니다.** milestone의 `actor="human"`, operator override의 공개 문자열, Atlas의 `ABC`, onboard의 `operator_authored`는 모두 호출자가 제공하거나 코드가 붙이는 값이다. onboard 승격은 oracle 테스트 실행을 검사하지 않는다. 읽은 테스트도 플래그만 true로 바꿔 승격 성공을 기대한다. evaluator 직접 호출은 생성자와 다른 모델 계열인지 이 경로에서 대조하지 않는다.
4. **schema 선언 감사와 실제 검증은 다르다.** 빈 폴더·없는 폴더가 `all_covered=true`이고, 상류 테스트도 이를 기대한다. `free_text` 마이그레이션은 strict 선언 감사를 통과시키지만 실제 structural validator는 dict가 아닌 schema를 건너뛴다. 이를 검증 확대나 활성화 준비 완료로 흡수하면 안 된다.
5. **단일 파일의 원자적 교체가 승격 전체의 원자성을 보장하지 않는다.** Atlas는 복사·감사·원본 frontmatter·ack 사이에 실패할 수 있다. skill 승격은 기존 `SKILL.md`를 덮어쓰며 marker 생성은 `exists` 뒤 일반 쓰기다. 예외에도 `finally`에서 marker를 지운다. Windows에서는 `gsd-` 이름의 역슬래시를 차단하지 않아 디렉터리 경계를 넘는 경로가 구성될 수 있다. 이들은 정적 분석 발견이며 공격·운영 실행을 하지 않았다.
6. **관측과 파생 그래프는 정본이나 자격 판정이 아니다.** mirror 예외가 빈/정상 모양으로 접히고, observe의 ledger 성공 횟수·verified_by는 저장된 자기신고를 집계한다. ontology demo는 같은 wire 문자열을 전역 Value로 합치고 BLOCKED 원인을 그래프에서 잃는다. phase graph의 strict는 파일 존재만 확인한다.
7. **변이 점수와 프로젝트 탐지에도 검증 범위의 한계가 있다.** mutation runner는 timeout도 killed로 세고 원본 복구 오류를 삼킨 뒤 backup을 지울 수 있다. project analyzer는 휴리스틱 스택·한 단계 디렉터리·extractor별 첫 성공만 사용한다. 연결된 validator runner는 `main()`의 일반 반환값을 무시하므로 `return 1`만 하는 검사도 PASS로 보일 수 있다.

## Zeus 대응과 채택 판단

직접 읽은 Zeus `application/audit_gate.py`는 source·검사 영수증·독립 lead/conductor·활성 revision/policy/graph 바인딩과 실행 시 전이 artifact 재검사를 요구한다. `domain/model_routing.py`는 자격 없는 업무를 Astra에 남기고, 단순도나 좁은 pilot 영수증을 모델 이양 권한으로 사용하지 않는다. 상류 공개 토큰·모델 verdict·횟수·경과일로 이를 대체하지 않는다.

채택 후보는 단계별 관측, 파생 graph 조회, 검증 누락을 드러내는 체크리스트와 inert candidate 구분이라는 개념이다. CLI는 유스케이스 호출로 얇게 유지하고 정의는 Git, 실행 상태·승인·generation·실패 복구는 PostgreSQL 정본으로 변형해야 한다. 모델 선택은 자격 정책을 통과한 별도 결정이어야 한다. 파일 원장·일회성 문자열·비원자 marker 구현은 그대로 복제하지 않는다. `output_schema: free_text` 일괄 삽입을 검증 우회 용도로 채택하는 것은 제외한다.

이 비교는 대응 설계 판단이다. 현재 Zeus의 모든 관련 모듈을 전수 비교한 동등성 인증도, 코드 변경 제안의 승인도 아니다. `project_skills`와 `store`는 AGENTS의 책임에 따른 대응 모듈로 기록했으며 이번 범위에서 전문 비교하지 않았다.

## 증거와 남은 범위

`files.json`은 14개 고정 분모와 파일별 hash·목적·권한·호출 가능성·OS 차이·판단·미해결을 담는다. `semantic-notes.json`에 각 파일의 구체적 근거가 있다. `supporting-evidence.json`은 **상류 17개 파일의 실제 읽은 구간**과 **Zeus 2개 파일 전문**의 해시를 구분한다. 상류 supporting 전문은 onboard 테스트, schema 감사 테스트, phase graph query의 3개이고 나머지는 부분 독해다. supporting을 다른 primary 파티션의 완료 상태로 승격하지 않았다. 검색 영수증은 발견용이며 검색 결과의 본문까지 읽었다고 주장하지 않는다.

미완료는 전이 의존성 전수 독해와 실효 설정·전체 호출자·모든 테스트 연결이다. 특히 `milestone_materials`, checklist, mutation worktree 구현, quota counter, provider/parser 나머지, EventStore 전이 경로, mirror extractor/fingerprint, frontmatter/parser, seam scanner/fleet, pipeline core/merge, extractor registry와 개별 validator, advisory ack, 실제 skill matcher 및 promotion 정책 전문이 남는다. 외부 링크·원본 라이선스·과거 debate/fleet 조사·복제 출처·생성물 동등성도 미확인이다.

Windows/Linux/WSL에서 상류 테스트는 모두 미실행이다. 독립 격리 테스트 및 경로·경합·크래시·빈 분모·오염된 oracle 회귀를 수행한 뒤 정확한 revision에 묶인 독립 검토가 필요하다. 따라서 checkpoint는 `body_coverage_complete=true`지만 `partition_complete=false`, `adoption_ready=false`다. 이번에 허용된 기록기만 실행했고 source/src 수정, commit, push, 운영 기동은 하지 않았다.
