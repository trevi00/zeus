# mirror extractors 전문 정적 독해

이번 4개 모두 새 전문이다. 선행 전문/지원 재사용 0, source 실행/import/probe/network/install0. 문서와 주석의 계약 선언은 검증 결과가 아니다.

## __init__.py
1~77 전문. rust/cargo alias와 pathglob을 lazy import하여 EXTRACTOR singleton을 반환한다. 미등록 이름은 KeyError로 거절하고 registry 목록을 결정적으로 정렬하는 방어는 보존할 수 있다. name의 truthy 비문자열은 strip에서 실패한다. detect는 import 및 detect 예외를 모두 버리고 fallback을 반환하므로 잘못된 플러그인과 실제 언어 미탐지를 구분하지 못한다. fallback 모듈도 import 실패했는데 기본 pathglob 문자열을 반환할 수 있다. Protocol 준수나 반환 인스턴스 형식은 검사하지 않으며 추가 확장은 registry 수정까지 필요하다. base re-export와 rust/pathglob 직접 구현 전문을 함께 읽었다. caller mirror_drift의 manifest extractor 및 자동 선택이 실제 구성 입력이다. OS별 디렉터리 접근 실패는 fallback으로 숨을 수 있다. Zeus는 추출기 이름/버전/실패를 PG 분석 영수증에 남기고 unknown과 coarse를 명시해야 한다. 실제 플러그인/언어 인수·전체 caller 폐쇄·라이선스는 남는다.

## base.py
1~190 전문. Protocol 및 git 목록/상태, glob, scope/fingerprint를 제공한다. git 명령 timeout과 오류의 None 구분은 유용하나 read-only라는 선언도 실제 subprocess 실행을 포함한다. ls-files는 -z 없이 줄 분리/strip하므로 Git quoted Unicode·개행·양끝 공백 경로를 정확히 복원하지 못한다. .git은 exists만 검사하여 worktree 파일은 허용하지만 cwd가 저장소 하위면 None이다. 사용자 Git 환경/config 상속도 남는다.

normalize 70~83은 모든 줄의 공백을 re.sub로 합친다. 따라서 문자열 "a  b"와 "a b"가 같아지고 Rust raw multiline string 안의 // 시작 줄도 주석으로 삭제될 수 있다. 'NEVER touches string-literal' 및 'distinct real code cannot collide'라는 주석은 구현과 모순이다. AST나 lexer가 아니며 full-line doc comment 변경 의미도 제외한다. glob **/를 .*로 바꾸어 경계 없는 문자열까지 매치할 수 있고 대괄호 패턴은 literal 처리한다. 165~177 coarse도 read_text errors=replace 및 universal-newline 뒤 UTF8 재인코딩하므로 원시 바이트 해시가 아니다. CRLF/LF 및 서로 다른 잘못된 UTF8이 같아질 수 있다. 파일 경로/길이/type을 해시 입력에 넣지 않아 동일 내용 rename을 놓치고 read OSError 파일은 조용히 제외한다. symlink target 읽기와 변경 중 snapshot 일관성도 미보장이다. empty scope는 빈 내용 hash, duplicate scope name은 dict overwrite이며 fp에는 globs/mode/추출기 버전 자체가 없다. Zeus에서는 raw blob/path/mode/범위 선언을 버전과 함께 결속하고 읽기 실패를 실패 분모에 남겨야 한다. 현재 것은 advisory drift 후보이며 SDD 인수 오라클로 채택하지 않는다.

## pathglob.py
1~53 전문. 항상 detect True인 fallback, None comment syntax, services/source 두 coarse scope와 확장자 목록을 제공한다. coarse_reason을 드러내는 의도는 보존하되 실제 raw 여부는 base와 다르다. C/C++/헤더/설정 등 목록 밖 파일과 untracked는 source scope 밖이다. services와 source는 중복될 수 있고 총 파일 수를 검사 분모로 쓰면 안 된다. extract_structure는 git None도 빈 목록으로 바꾸며 전체 tracked 경로의 상위 디렉터리 수만 센다. source scope에 포함된 파일 수나 AST/의존 관계가 아니다. imported Path는 미사용이며 toolchain-free는 git subprocess까지 없다는 뜻이 아니다. Zeus는 검색 편의용 목록과 원문 의미 검증을 분리하고 미지원/미확인 파일 분모를 유지해야 한다. Windows 경로는 git POSIX 출력 복원 한계에 종속된다. 실제 언어 동등성 및 전체 테스트는 미검증이다.

## rust.py
1~99 전문. cwd 또는 바로 아래 Cargo.toml로 detect하고 여러 후보면 정렬상 첫 디렉터리를 선택한다. 깊은 workspace는 미탐지하고 전체 다중 workspace를 대표하지 못한다. normalized src/services, coarse Cargo manifests가 기본 범위이며 Cargo.lock/build.rs 및 src 밖 코드는 누락 가능하다. cargo metadata --no-deps, 60초 timeout은 외부 실행이며 --locked/--offline 및 격리 env가 없어 파일/네트워크 무부작용을 보증하지 않는다. 이번에는 실행하지 않았다. 성공 JSON을 타입 검증 없이 packages/targets로 순회하여 kind=[]의 IndexError나 비객체 구조의 AttributeError/TypeError는 catch 대상 밖이다. 추출은 crates/dependency names/target kind뿐이며 문서가 말하는 AST signatures/module tree 전체는 아니다. 실패 또는 빈 crates는 tracked *Cargo.toml 경로 stand-in으로 낮추고 각 항목 degraded=True를 남기는 것은 유용하다. git 실패의 빈 전체 결과에는 구분된 error가 없다. 절대 manifest_path와 fallback 상대경로도 다르다. Zeus는 toolchain/lock/source revision/환경과 추출 실패를 별도 영수증으로 묶어야 하며 이 결과로 compile 또는 사람 인수를 승인하지 않는다. vendor 원문·플랫폼·라이선스·실제 cargo 효과는 pending이다.
