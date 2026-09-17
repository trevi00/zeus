# Java·TypeScript 38개 자산 선정 판정

2026-09-17, Codex. 원본 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`,
Zeus 기준 `f331c4a`. 이번에 끝낸 것은 대기 중이던 **자산 선정 판단**이다.
원문 재배포, 새 스킬 설치, 모델 자격 인증 또는 전체 흡수 완료가 아니다.

## 검토 근거와 보존

기존 Java-001 19개와 TypeScript-001 19개 본문 검토 기록 및 독립 Claude 최초
의견을 재사용했다. 이번 Codex는 그 의견과 주요 소비 경로/상충 구절을 대조했다.
38개 본문을 다시 전문 독해했다고 주장하지 않는다. 이전 Claude 의견에 대한 아래
정정은 Codex 판정이며, Claude가 재동의한 토론 결과로 표시하지 않는다.

38개, 365,311 bytes 모두 범위 manifest·본문 검토 기록·실제 pinned 파일 사이의
SHA256와 Git blob이 일치했다. 입력 기록 31개와 원문 사본은
`D:\workspaces\zeus\artifacts\java-typescript-decision-001\snapshot`에 보존했다.
경로별 신원과 기록 해시는 EVIDENCE.json, 선정 결과는 SELECTION.json이다.
원본 미커밋 자료, 전체 분석 원장과 집계는 변경하지 않았다. D의 사본은 다른 PC에
공유된 저장소가 아니다. 원본 예제 실행과 신규 모델 호출은 0회다.

## 기존 의견에서 정정한 것

1. **접근 불가와 설정 의존을 구분한다.** Claude F1/F2의 절대적 표현은 좁힌다.
   pinned `scripts/lib/tech_stack.py:134–172`와
   `scripts/handlers/prompt/skill_match.py:256–308`에는 설정 부재 시 재귀 fallback과
   명시적 extensions가 있다. OUTPOS/ecommerce는 해당 설정에서 자동 선택되지 않는
   것이며, 모든 호출에서 접근 불가능한 것은 아니다. 특정 프롬프트에서 전달됐다는
   실행 증거도 없다.
2. **원본의 결함을 Zeus 결함으로 복제하지 않는다.** 원본 matcher:374–394는
   표시 파일명을 메타데이터/점수 키로 쓴다. Zeus
   `adapters/skill_routing.py:76–100`은 경로 identity로 키잉하며 중복 경로를 거절한다.
   `domain/project_skills.py:57–73`은 minor 버전의 major 후보도 만든다. 이 두 경계를
   고치는 새 런타임 티켓은 만들지 않는다. React framework 버전과 TS 언어 버전을
   자동으로 동일시할 수는 없으므로 프로젝트 선언의 명시적 stack/extension은 남는다.
3. **35개가 전부 무검사·무신호라는 주장은 과하다.** 9축 강제 적용과 일반
   frontmatter WARN은 다른 검사다(`skill_frontmatter.py:110–139`). pinned CI의
   skills-only path 누락은 확인했지만 현재 Zeus CI가 같은 결함이라는 근거는 아니다.
   Claude F3의 제목 15건과 본문 14개 unresolved + 2개 empty는 서로 다른 수다.
   그 제목 수치를 확정 통계로 채택하지 않는다.
4. **본문 크기 미확인은 해소했다.** quality_axes opt-in 세 문서는 각각
   Gradle 6,037 / gRPC 6,601 / Testcontainers 6,272 bytes다. 모두 8,192 아래다.
   이는 원시 byte 크기 확인이며 9개 gate 전부의 실행 PASS가 아니다.
5. **tsconfig 두 예제가 모두 유효하다는 Claude F17은 수용하지 않는다.**
   pinned `5.x/strict-config-and-runtime-contracts.md:45–46` 및
   `5.x/config-drift-and-upgrades.md:70–71`의 `moduleResolution: node20`를 그대로
   가져오지 않는다. TypeScript 5.9의 `module: node20` 도입과 moduleResolution의
   허용값은 별개다. 공식 문서 두 편을 2026-09-17 열어 확인했다:
   [moduleResolution](https://www.typescriptlang.org/tsconfig/moduleResolution.html),
   [TypeScript 5.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html).
   대상 프로젝트의 고정 compiler로 config 로딩·빌드·실행을 확인하는 조건으로만 채택한다.
6. **프로젝트 정책을 전역 정책으로 만들지 않는다.** OUTPOS의 MyBatis/JPA 금지는
   일반 Spring 프로젝트 전체의 금지가 아니다. 회사 ErrorType 설명과 gRPC 예제의
   `getHttpStatus`/HTTP 분류 불일치는 보류 근거이나 실제 비공개 타입의 컴파일 실패를
   재현했다고 주장하지 않는다(`outpos/backend.md:576–585`, `outpos/grpc.md:205–215`).
   Boot 2/3, JDK 17/25, MySQL 버전별 예제도 대상 버전 없이 일괄 적용하지 않는다.
7. **테스트의 대상을 구분한다.** React testing의 route.fulfill은 합성 UI 오류 시험이다.
   Testcontainers 문서도 LocalStack으로 AWS 호출 0을 명시한다. 실제 DB 컨테이너와
   클라우드 emulator를 한꺼번에 실서비스 인수라고 부르지 않는다. BFF/서버 인가,
   사용자 간 캐시 격리, 실제 사용자 시나리오는 별도 실환경 오라클이 필요하다.
8. **주입량과 준수는 다르다.** PER_BODY_CAP 주석과 실제 caller 순서를 구분한다.
   축약 시 특정 문단이 항상 사라진다는 의견은 실제 입력 영수증 없이는 확정하지
   않는다. requires 문자열, 코드 예제, coverage 목표, PASS 표기는 행동 인수가 아니다.

## 선정과 적용 순서

각 파일의 결정·그룹·검증 조건은 SELECTION.json에 빠짐없이 기록했다.
`adapt`는 원칙을 대상 프로젝트에 맞게 재작성할 후보로 선정한 것이며 설치 완료가
아니다. `hold`는 원문 템플릿 적용을 보류하되 유용한 원칙까지 폐기한 뜻은 아니다.

| 그룹 | 결정과 목적 | 실제 적용 때의 완료 조건 |
|---|---|---|
| SDD | 요구→설계→구현→검증 연결을 기존 단계에 적용 | 요구 ID, 생성물, 독립 인수 오라클이 같은 spec에 결속; 테스트 기대값 변경으로 통과시키지 않음 |
| JVM | 도구 버전·계약·자원 소유·실제 의존성 시험 원칙 채택 후보 | 선택한 JDK/Gradle/dependency digest에서 build와 실제 통합, 취소·실패·정리 확인 |
| JAVA-LEGACY | OUTPOS·JWT·DB 및 버전 의존 virtual-thread 템플릿 보류 | 대상 타입/버전/권한 명세 확인 후 예제 재작성; 회사 전용 규칙과 역사적 주장을 분리 |
| TS-CONTRACT | 타입·runtime schema·설정 이행 원칙 채택 후보 | 고정 compiler config/build; HTTP 실패·인가·외부 입력 검증은 별도로 실행 |
| UI | 상태 소유/수명·토큰·컴포넌트 계약·가시성 채택 후보 | loading/empty/error/success Storybook와 실제 브라우저·키보드·반응형 검증 |
| WEB-AUTH | 서버 인가와 클라이언트 전달/캐시 구분 채택 후보 | 실제 백엔드로 권한 철회·다른 사용자·객체 소유·오류 응답·캐시 격리 확인 |
| UI-TEST | mock 단위 시험과 실제 E2E의 분모 분리 | 핵심 사용자 시나리오는 page.route/MSW/emulator 없이 서비스→DB→UI와 사람 인수 연결 |
| OPTIONAL-STACK | Nuxt/Vue 자산 보존, 해당 스택 선정 전 적용 보류 | 선택한 버전에서 SSR/cleanup/요청 역전/컴포넌트 계약의 실제 시험 |

다음 적용 대상은 UI·TS-CONTRACT·WEB-AUTH·UI-TEST를 묶은 **프로젝트 단위 시나리오
팩**이다. 기존 프로젝트 스킬 라우터와 8단계 SDD를 사용하고 별도 라우터를 만들지
않는다. code-tutor-ai의 실제 제품 범위·스택·핵심 사용자 시나리오를 먼저 확인한 뒤
한 명세로 Claude에게 구현을 맡긴다. 지금 전역 worker-v1에 38개를 붙이지 않는다.
PR118 프로필은 이미 5,977/6,000자로, 프로젝트 지침은 프로젝트 컨텍스트에 둔다.

## 완료와 잔여 경계

이번의 38개 선정 대기는 해소됐다. 원본 전체 분석, 미확인 전이 의존성, 재배포 권리,
실제 제품/사람 인수, 모델 등급별 자격 증거는 여전히 남는다. 이 판단으로 전체 분석
집계를 올리거나 #1/#11/#13을 닫지 않는다. 미흡한 문구·번호·옛 통계는 적용 때 함께
정리할 사항이며 제한 운영을 막는 새 결함으로 올리지 않는다.
