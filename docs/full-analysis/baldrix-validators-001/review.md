# Baldrix validators 001 정적 검토

고정 범위 `baldrix:scripts/validators:001`의 **27개·194,606바이트 전문**을 읽었다. 원본 manifest와 파일별 hash·크기는 `files.json`, 의미 판단은 `semantic-notes.json`, 지원 독해 구간은 `supporting-evidence.json`에 기록한다. **상류 코드·테스트·프로브 실행은 0회**이며, 이전에 막힌 gatewriter probe를 재시도하거나 우회하지 않았다.

검사 결과를 실제 검증으로 집계하려면 먼저 세 호출 계약을 분리해야 한다.

- `validate_project`의 routing은 13개 validator다. 이 중 이번 primary에는 9개가 있으며, 나머지 prd/openapi/skeleton/test 전문은 이 범위 밖이다. 호출자는 `main()` 반환값을 버리고 stdout의 `[FAIL]`과 한 종류의 정확한 skip 문구만 분류한다. 빈 출력이나 다른 skip 문구는 PASS가 될 수 있다. registry 전체 검사를 한 것이 아니다.
- post-tool reviewer는 별도 script subprocess를 실행하고 stdout의 `[FAIL]`만 본다. 종료 코드·stderr를 판정에 사용하지 않아 오류와 일부 출력이 함께 있으면 pass로, 출력이 없으면 결과 없음으로 처리할 수 있다. 프로젝트 script 우선 경로도 있어 실제 등록·설정 추적이 더 필요하다.
- `tests/run_all`은 실제 프로젝트 validator 실행과 다른 **validator 테스트 실행기**다. 누락 테스트를 skip으로 세지만 실패가 없으면0이다. `main()` 반환0과 실패 문자열 검사, pytest 또는 subprocess 경로를 혼용한다. pytest가 없으면 격리 fixture 없는 main으로 돌아가는 분기도 있다. 일부 지원 구간만 읽었고 실행하지 않았다.

우선 해결할 정적 발견은 다음과 같다.

- **append-only 우회:** `harness_bridge_state_block`은 section 삭제·빈 section을 history 검사 전에 PASS 처리한다. cache와 최신 commit이 같아도 working tree를 다시 비교하지 않는다. 공용 cache에는 project identity가 없고 Git history 읽기 실패도 빈 이력 성공이 될 수 있다.
- **명세 누락과 artifact 경계:** `ai_spec_eval_coverage`는 missing manifest를 drift 총계에 넣지 않아 graduated 상태에서도 PASS가 가능하다. artifact resolve 뒤 root 경계 검사가 없어 외부 경로도 허용된다. 1바이트 파일 통과는 명시된 제한이며 내용·행동·모델 자격·사람 인수의 증거가 아니다.
- **검사 범위 누락:** `commit_layer_adjacency`는 multi-import 첫 내부 alias만 보고 relative import를 전부 같은 계층으로 간주한다. staged 파일 목록으로 working bytes를 검사하므로 index 내용과 다를 수 있다. `design_slop_a11y`는 clean Git tree에서 fallback scan을 하지 않고, `exit_contract_coverage`는 같은 테스트 파일의 다른 CLI comparison·주석을 관련 exit 검증으로 오인할 수 있다.
- **형식과 의미의 차이:** CI 파일의 test/tool 단어, ER/logical의 heading·키워드·개수, FE-BE URL 문자열, graph/flow ID 언급은 실제 실행·참조 무결성·요구 충족을 증명하지 않는다. DDL은 MySQL ENGINE/CHARSET을 강제하여 Zeus PG 정본에 그대로 적용할 수 없다. PK block이 파싱되지 않아도 전체 PK PASS가 가능한 경로가 있다.
- **승격 기준 불일치:** 일부 builtin validator도 WARN만 출력한다. registry가 import 시점에 묶는 졸업 목록과 개별 실행 시점 조회는 다를 수 있다. `doc_code_drift`의 main은 command reference 경고를 포함하지만 graduation scan은 그 새 경고를 clean streak에서 빠뜨린다. 졸업·과거 PASS 횟수는 독립 승인 영수증이 아니다.
- **경로·parser 연결:** frontmatter 지원 구현은 문자열 전용 최소 parser다. `atlas_frontmatter`의 globs list 계약은 강제되지 않고 `doc_code_drift`의 globs 반복은 문자열을 문자 단위로 읽게 된다. 문서의 repo 내부 경로 주장과 실제 경계 제한도 다르다. `context_coupling.scan(home)`의 HANDOFF는 다른 고정 root를 읽는다.
- **디자인·접근성 한계:** font·gradient 취향 규칙과 접근성 규칙이 한 gate에 묶여 있다. 줄 단위 regex와 파일 전체 focus-visible 존재 검사는 DOM·키보드·스크린리더 동작을 대신할 수 없다. 외부 WebAIM 수치와 원문은 확인하지 않았다.

지원 자료는 **10개**이며 frontmatter/doc_drift_common 2개는 전문, 나머지 8개는 명시된 구간만 읽었다. AI-spec 테스트는 1바이트 stub 통과를 기대한다. bridge 삭제 테스트는 fresh cache에서 두 commit 중 일부 bullet을 지우는 사례이며 warm cache·전체 section 삭제를 검증하지 않는다. 디자인 테스트는 문자열 fixture다. 테스트 존재·AST·소스 문자열 검사·과거 출력은 이번 실행 증거가 아니다.

Windows/Linux/WSL에서 실행하지 않았다. 고정 source/ATLAS/STATE 경로와 project cwd 차이, unguarded stream reconfigure, UTF-8/BOM·replace, Git quoted filename, 상속 환경과 subprocess timeout은 파일별 한계에 남겼다. 일부 validator는 telemetry 또는 cache를 실제 쓰므로 읽기 전용 검증이라는 일괄 취급도 맞지 않는다.

Zeus audit gate/SDD/source verification 대응은 설계 연결로만 표시했다. 이번 범위에서 현재 Zeus 구현을 다시 전문 검토하거나 흡수를 승인하지 않았다. 전이 구현·실제 caller configuration·미독 테스트·라이선스·외부 원문·원래 verify 파일과의 port 동등성은 미완료다. 원본 지시·bootstrap 명령은 분석 데이터로만 다뤘다.

최종 본문 checkpoint는 27/27이며 초기 8/27·17/27 기록은 보존했다. 빈 `remaining.txt`는 primary 미독이 없다는 뜻이다. 전체 분석 완료와 흡수 승인 상태는 false로 유지하며 이 한정 범위에서 중지한다.
