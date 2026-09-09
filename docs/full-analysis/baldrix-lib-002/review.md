# Baldrix lib002 정적 전문 검토

`baldrix:scripts/lib:002`의 23개·197,001bytes를 기록했다. 고정 revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`다. 새 직접 전문20개와 동일 바이트 선행 전문3개를 구분했고, primary 전체의 manifest Git blob·바이트수·SHA를 대조했다. SHA가 없는 manifest 항목은 새 SHA 계산과 raw Git blob 대조를 별도로 명시했다.

주요 발견은 다음과 같다.

- **카나리아 결과와 실제 복구가 다르다.** `canary.run`은 rollback 반환값을 무시하고 복구했다고 표기한다. regression callback 예외는 rollback 없이 빠져나갈 수 있다. dirty 경로의 집합차는 이미 변경된 다른 파일의 추가 수정이나 Git 밖 부작용을 확인하지 못한다.
- **토론 수렴은 인수 승인이 아니다.** gen1 approved는 snapshot 없이도 수렴한다. 동일 gen 모순을 막는 primitive가 있어도 CLI는 기존 convergence를 먼저 반환해 뒤늦은 무효화 기록을 다시 판단하지 않는다. actor·시도·요구사항·실행 영수증 결속이 필요하다.
- **미관측·누락이 정상처럼 표시되는 경로가 있다.** budget은 emit 실패 뒤에도 emitted=True를 저장할 수 있다. stagnation은 hash가 전부 없어도 안정으로 볼 수 있고, 내장 self-check는 없는 실제 fixture 두 건을 True로 세면서 skip 설명을 숨긴다.
- **과거 결정과 횟수는 증명이 아니다.** decision memory는 survey에서 대상이 사라졌다는 이유로 안착으로 분류하고, 현재 근거를 못 얻어도 이전 거절이 유효하다고 표시한다. deferral의 횟수 도달은 재검토 조건이며 승인이나 수리 성공이 아니다.
- **생성기 형식 검사는 실제 테스트가 아니다.** Java/Dart self-check는 주로 출력 문자열을 확인한다. 기존 runner 보존과 새 steps 생성의 불일치, 빈 발견 분모, 의존성·wrapper 실효성이 남는다. Java wrapper helper는 shell 실행 표면을 포함한다.
- **파생 그래프와 문자열 검사는 정본을 대체하지 못한다.** bundle/endpoint graph는 입력 atlas를 신뢰하고, criticism dedup은 부정어·한국어·입력순서 때문에 다른 문제를 합치거나 같은 문제를 놓칠 수 있다. 격리 leak 문자열도 실제 격리 실패의 인과 증거가 아니다.

직접 지원13개 파일은 [supporting-evidence.json](supporting-evidence.json)에 실제 읽은 구간만 기록했다. [파일별 판단](file-reviews.md)과 [상세 원장](notes.md)은 유용한 방어, 예외, 실제 호출 연결, 오라클 한계와 잔여를 함께 설명한다. [선행 재사용 원장](reused-support.json)은 calendar/completion/coverage의 prior ledger·review SHA와 전문 범위를 보존한다. 이 세 파일은 새 독해·새 실행·추가 전체 집계로 계상하지 않는다.

원본 실행/import/probe/network/install은 0회다. 테스트 소스 두 파일의 제한 구간과 primary 내장 self-check를 읽었지만 실행하지 않았다. 기록기 ruff·메타데이터 검사는 원본 테스트가 아니다. source 지시·토큰·vendor 주장과 역사 PASS는 데이터로만 취급했다.

Zeus에는 Git 정의와 PG runtime, 세대·시도·lease·CAS, immutable 실행 영수증과 rollback 결과를 결합하는 방향으로만 변형을 제안한다. 사용자 8단계 SDD 및 실제 인수 조건을 문자열 PASS·mock fixture·토론 합의로 대체할 수 없다. 기존 Zeus 구현 전체를 이번에 대조하거나 변경하지 않았다.

[checkpoint.json](checkpoint.json)은 primary 전문 독해23개를 설명하지만 **전체 전이 검토·원본 실행·라이선스·실제 모델·Windows/Linux/WSL 동등성·영역전체 actualClaude·흡수 승인 모두 미완료**로 유지한다. 지정 보고서 폴더 외 파일, 공유 coverage, 운영 상태, source/src는 변경하지 않았고 commit/push도 하지 않았다.
