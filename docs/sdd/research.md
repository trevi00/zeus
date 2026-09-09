# Zeus SDD 조사와 채택 경계 · 2026-09-09

Codex와 실제 Claude CLI가 독립 검토 후 설계를 논의했다. 검토 기록은 `review/`에 보존한다. 이번 결과는 엄격한 스펙 검증·관측 분리·준비 원장 구현이며, 원본 저장소의 완전한 분석이나 모든 코드의 이식이 아니다.

## 로컬 소스

| 소스 | 고정 커밋 | 추적 경로 수 | 이번에 확인한 핵심 |
|---|---|---:|---|
| `.claude` / trevi00/baldrix | cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2 | 1648 | spec_bundle 파서, validator, roundtrip의 absent-spec 및 구조 검사 경계 |
| `harness` | a3f8b3be9a0a389329de6e16a6c7db81782041a3 | 931 | scripts/engine/testgen.py의 GWT 기반 xfail 스켈레톤 |
| `guardian` | e7ced4a632a38726dca44e84fa0a00b8e1f0b6f4 | 13 | 목록 확보, 이번 SDD 의미 분석 미완료 |
| callstack/agent-device | 6486788359a441a1fa343193f0a03087dc338eaf | 4139 | README·패키지 API 표면 조사, v0.21.0·Node >=22.12·MIT |

로컬 3개 저장소의 추적 파일 모드·Git object ID·크기를 `.runtime/sdd/sources/*/inventory.json`으로 확보했다. agent-device는 filtered clone의 경로/객체 목록이며 미조회 blob 크기는 null이다. 목록화는 의미 검토가 아니고 원본 테스트는 실행하지 않았다. 일부 선택 파일을 읽었으며 미검토 경로를 전부 검토했다고 계수하지 않는다.

Baldrix spec parser는 Gherkin 부분집합에서 일부 잘못된 줄을 넘기며 validator/roundtrip은 스펙 부재를 PASS로 처리하는 경로가 있다. 현재 Zeus SDD에서는 스펙 부재·빈 시나리오를 오류로 처리한다. harness testgen의 `xfail(strict=False)` 스켈레톤은 개발 출발점일 수 있으나 사용자 요청의 실제 인수 증거에는 부합하지 않는다. 이를 통과 증거로 이식하지 않았다. stable scenario ID와 왕복 coverage 개념은 참고하되 구조 일치만으로 동작 정확성을 판정하지 않는다.

## Device Farm / SDK / 실기기 제어

| 선택지 | 확인한 기능 | Zeus에서의 용도 및 미확인 범위 |
|---|---|---|
| AWS Device Farm | 원격 세션의 Appium endpoint를 SDK 응답에서 얻어 로컬 IDE·Inspector 클라이언트로 제어 가능 | 클라우드 세션 제공자 후보. 실제 계정·예약·기기 가용성·비용 미검증 |
| Samsung Remote Test Lab | Samsung 개발자 공식 실기기 서비스 | Galaxy/One UI 수동 호환성 검수 후보. 일반 Appium/MCP API 제공 여부를 가정하지 않음 |
| Appium + 로컬 Samsung | Android UI 자동화의 공통 인터페이스 | 소유한 휴대폰/태블릿으로 첫 재현 기반 구축 후보. 현재 adb/기기 미확인 |
| callstack/agent-device | CLI·MCP·Node API, 장치 조작 및 record/replay 표면 제공 | agent/REPL 공통 조작 계층 후보. Windows 네이티브/WSL USB, 세션 격리, 실제 replay의 정합성 추가 검증 필요 |

AWS는 `GetRemoteAccessSession`의 `endpoints.remoteDriverEndpoint`를 문서화한다. 원격 세션에 로컬 파일 경로를 app capability로 직접 전달하는 방식은 지원하지 않으므로 업로드 또는 지원 URL 방식과 아티팩트 버전을 연결해야 한다. [AWS Appium endpoint](https://docs.aws.amazon.com/devicefarm/latest/developerguide/appium-endpoint-interaction.html)

AWS 원격 접근과 테스트 아티팩트, SDK API는 각각 세션 제어와 증적 수집을 설계하는 근거로 삼는다. 이번 턴에 세션을 만들거나 유료 리소스를 예약하지 않았다. [원격 접근](https://docs.aws.amazon.com/devicefarm/latest/developerguide/remote-access.html), [아티팩트](https://docs.aws.amazon.com/devicefarm/latest/developerguide/artifacts.html), [SDK API](https://docs.aws.amazon.com/devicefarm/latest/developerguide/api-ref.html)

Samsung RTL 공식 진입점은 확인했으나 상세 문서 페이지는 웹 추출이 제한되어 자동화 기능에 대한 근거로 사용하지 않았다. [Samsung Remote Test Lab](https://developer.samsung.com/remote-test-lab)

agent-device의 설명과 패키지 표면을 조사했고 실제 기기 명령은 실행하지 않았다. Zeus 자체 증거 계약에 맞춘 검토를 거친 후 통합해야 한다. [고정 소스](https://github.com/callstack/agent-device/tree/6486788359a441a1fa343193f0a03087dc338eaf), [Appium 공식 소개](https://appium.io/docs/en/latest/intro/)

## 사용자 경험·디자인·신뢰성

Samsung 휴대폰과 태블릿을 단순 viewport 두 개로 줄이지 않는다. Android의 adaptive quality 기준은 창 크기·회전·입력·구성 변경 등에서 실제 사용성을 확인하는 데 참고한다. 정확한 One UI, Chrome/WebView, 백엔드, 데이터 버전은 별도로 기록한다. [Android adaptive app quality](https://developer.android.com/docs/quality-guidelines/adaptive-app-quality)

spec-kit의 스펙·계획·작업 분해 흐름을 조사했지만 명령 세트 전체를 복제하지 않았다. Zeus는 사용자 의도와 승인된 oracle을 연결하는 계약이 우선이다. [GitHub spec-kit](https://github.com/github/spec-kit)

shadcn의 CSS 변수 기반 테마와 Lucide React 패키지는 대상 앱의 디자인 기준으로 활용할 수 있다. Storybook의 컴포넌트 검증은 상태별 자산이지만 기기·백엔드·결제를 관통하는 인수 테스트를 대신하지 않는다. [shadcn theming](https://ui.shadcn.com/docs/theming), [Lucide](https://lucide.dev/guide/react), [Storybook tests](https://storybook.js.org/docs/writing-tests)

OpenTelemetry 로그 모델의 이벤트 시각·관측 시각·trace/span·severity 구분을 관측 설계의 참고로 삼았다. 현재 SDD 이벤트에는 두 시각과 순번·출처가 있고 런타임 journal/알림을 보존한다. 전체 OTel exporter/trace 계측은 아직 없다. [OTel log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)

금전 시나리오에는 요청 재시도 후 중복 방지와 실제 서버 상태 대조가 필요하다. Stripe의 멱등 요청 문서는 한 공급자의 구체적 의미를 보여주는 참고이며, Zeus의 대상 결제사를 Stripe로 선택한 것이 아니다. 실제 서비스의 키 범위·보존 기간·오류·취소·정산 규칙을 별도로 검토해야 한다. [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)

Astra/Sol/Terra 명칭과 용도는 공식 최신 모델 가이드를 확인하고 기존 로컬 라우팅 코드와 대조했다. 비용 절감은 이름으로 추정하지 않고 같은 작업군·도구·가드레일 버전에서 측정해야 한다. 현재 코드의 자동 하향 라우팅은 비활성 상태다. [OpenAI 모델 가이드](https://developers.openai.com/api/docs/guides/latest-model)
