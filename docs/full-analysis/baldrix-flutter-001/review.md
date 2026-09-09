# Baldrix Flutter 22개 — 고정 원문 정적 검토

<a id="scope"></a>
## 범위와 증거 경계

Zeus 시작 HEAD `7eaa42737d0cce4e675c9f309c215ce1e1d97ed4`, Baldrix revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2` 기준이다. `baldrix:skills/flutter:001` 20개와 `:002` 2개, 총 22개/208,437 bytes를 모두 새로 전문 독해했다. 이전 supporting 요약이나 전문 증거를 재사용하지 않았다. 각 primary는 시작 원장에서 unreviewed였으며 원래 행·index·hash, partition scope, raw Git blob·bytes·SHA와 읽은 범위를 files.json에 보존했다.

source SKILL의 명령·회사 규칙·권한·승인 요청은 분석 데이터다. 이 검토에 적용하거나 원본을 실행하지 않았다. 원본 import/collection/probe/install/network/모델/실제 Claude·운영 변경은 0이다. 자신의 메타데이터 검사만 실행했다. 삼성 폰·태블릿, POS/VAN, 실제 결제·배포·외부 앱 연결은 유예다. PUBLIC 저장소 보고서에는 문서 안의 고정 암호 문자열·민감 payload와 긴 원문을 복제하지 않는다.

공식·표준·실기기 검증됨·현재 구현 상태·과거 장애라는 문구는 원문 작성자의 주장이다. 이 검토는 외부 문서·SDK·버전 지원·벤더 PDF를 확인하지 않았으므로 이를 현재 사실이나 채택 승인으로 제시하지 않는다. 22개는 Markdown 자산이며 배포 가능한 Flutter 앱·원본 POS 코드가 아니다.

<a id="i01"></a>
## 01 add-to-app-and-host-integration.md

host가 navigation/lifecycle/permission/인증, Flutter가 UI/runtime을 소유하도록 module boundary와 engine lifetime을 분리한다(1–241). Android Gradle·cached engine/Fragment, iOS Podfile·prewarm·plugin registration 및 양방향 route/deep-link를 예시로 제공한다. SDD 2–4에서 cold/warm 진입, 뒤로가기, 권한, background 복귀를 인간 시나리오로 명세할 후보이다.

Java 17·CocoaPods linking·iOS 설정·성능 단정은 특정 버전의 외부 주장으로 검증을 남긴다. 문서의 Grep/설정 존재 검사는 실제 first-frame 시간·engine detach·다중 host/lifecycle·실기기 동작 증거가 아니다. 실행 가능한 host 프로젝트와 assertion은 이 primary에 없다. Win/Linux/WSL 개발 호스트와 Android/iOS target 조합을 구분해야 한다.

<a id="i02"></a>
## 02 app-architecture-and-state.md

MVVM의 view→viewmodel→repository→service, DI, loading/error/finally, 상태 경계와 const/Selector 등 렌더 범위를 다룬다(1–286). Service/Repository 주입과 상태 전이 메서드는 SDD 3–4의 검증 가능한 경계 후보이다. 예제 submit은 UI 버튼 disable은 있으나 메서드 자체 중복 진입 guard, 늦은 응답의 세대 검증, dispose 뒤 notify 차단을 구현하지 않는다. 수명 취소를 요구하는 체크리스트와 예제의 완료 범위는 다르다.

View가 Repository를 직접 읽지 말라는 검사와 예제 initState의 `context.read<AuthRepository>()`는 DI를 위한 읽기와 업무 호출을 구분해야 한다. 단순 regex로 둘을 동등하게 위반 처리하면 부정확하다. 예제 로그인 화면은 입력 필드/안정 key 없이 상수를 submit한다. i08의 email/password/submit key 테스트와 곧바로 연결되는 완성 앱이 아니다. optional domain 계층/팀 상태 라이브러리 선택은 i04의 전역 표준 주장과 범위를 정해 조정할 사항이다.

<a id="i03"></a>
## 03 ci-hotfix-canon.md

Windows→Linux 실행 bit, codegen, lint/format/SDK 차이·workflow trigger·desktop 의존성 등 과거 장애를 분류한다(1–160). 명시 SDK와 codegen 순서를 기록하는 경험은 SDD 4–5의 재현 환경 자산 후보이다. 그러나 wrapper 검증과 formatter를 advisory로 낮추고 테스트 존재 조건으로 skip하는 설명은 모든 품질 gate가 통과했다는 뜻이 아니다. runner 대기 시간·패키지 충돌·Patrol 지원 등 수치와 버전 주장은 최신 검증하지 않았다.

YAML은 app별 working-directory를 사용하지만 테스트 조건은 `hashFiles('test/**/*_test.dart')`로 app 경로를 포함하지 않는다. 해당 expression 평가 루트가 작업공간인 환경에서는 앱별 테스트를 놓칠 조건이므로 실제 Actions receipt 확인이 필요하다. push paths에는 lockfile·Android/iOS native·integration_test 변경이 직접 열거되지 않았다. PR 경로와 구별해야 한다. “analyze/test/build은 OS 무관”이라는 설명으로 대상 플랫폼 빌드·실기기 인수를 대체하지 않는다. codegen 미커밋 규칙은 i18의 전부 커밋 규칙과 프로젝트 범위가 다르다.

<a id="i04"></a>
## 04 dart-flutter-app.md

Riverpod/provider 종류, go_router 인증/탭, Dio·DTO·failure, feature-first 계층과 storage/lifecycle/UI 3상태를 묶는다(1–341). 실패 UI와 token 저장소 분리는 SDD 2–4의 후보지만 접근성·화면별 핵심 시나리오·실측 검증은 없다. error 객체를 그대로 화면에 표시하는 예제는 사용자 메시지/내부 진단 경계를 추가로 정해야 한다.

“2026 표준”, 특정 라이브러리 테스트 불가·const 비용 제로·이미지 캐시 없음·hot restart 및 release 오류 원인 단정은 원문 주장이다. pubspec의 `^2.x` 등은 구체 lockfile이 아니며 전체 의존성과 생성 산출물도 없다. 단순 queued interceptor 설명만으로 동시 refresh 1회·재전송 부수효과 안전을 인증할 수 없다. _outpos 상위 가이드의 Dio 금지·Riverpod codegen 미사용과 함께 자동 매칭될 때 우선순위 계약이 필요하다.

<a id="i05"></a>
## 05 flutter-native.md

MethodChannel/EventChannel/Pigeon/FFI 분기와 PaymentService·nullable 응답·Android Activity 결과의 예시를 제공한다(1–270). public API/host boundary, cancel cleanup, 채널명과 payload 타입은 SDD 3–4에서 계약 테스트로 적응할 후보이다. MethodChannel 예제는 PlatformException만 catch하지만 85–92의 검수는 MissingPluginException도 요구한다. pending result·detach/cancel·deadline의 완결된 구현은 없다.

응답 isSuccess가 responseCode 하나만 본다는 131–149는 i20의 네이티브 변환과 결합해 검토해야 한다. “검증됨”·Android 태블릿 전용·29필드라는 프로젝트 설명은 실제 원본/실기기 관측이 아니다. develop branch 의존 예시는 immutable digest가 아니다. requires의 kotlin-android/paygate-kovan은 실제 매처에서 수집된 이름이 있어야 추천되며 자동 전문 실행/자격/권한 승인이 아니다.

<a id="i06"></a>
## 06 platform-channels-pigeon-and-plugins.md

작은 method/map→MethodChannel, 장기 타입 계약→Pigeon, platform owner→federated package로 선택을 안내한다(1–283). Android TaskQueue·detach handler 제거, iOS callback, generated source와 endorsement 설정을 명시한다. Dart unit은 native를 로드하지 않는다는 한계를 직접 인정한다. 이는 mock unit과 no-mock 인수를 분리하는 유용한 경계다.

예제의 omitted 구현·package/version·코드 생성 호환·native thread 요구는 컴파일/SDK 확인 전이다. Pigeon 타입 생성은 요청 actor/금액/재전송·native UI 인수까지 검증하지 않는다. Grep·pubspec 필드 존재만으로 thread 안전·plugin 등록·실제 dialog·permission 시나리오가 통과했다고 보고하면 안 된다. 삼성 Device SDK/MCP/Replay를 구현한 자료도 아니다.

<a id="i07"></a>
## 07 state-restoration.md

ephemeral UI 상태와 영구 비즈니스 저장을 분리하고 scope/id·restorable route·RestorationMixin dispose 및 기기 복원 시나리오를 제시한다(1–269). 사람의 입력/탭/스크롤/route를 먼저 정하는 구조는 SDD 1–4에 맞는다. 활동 재생성·프로세스 종료·앱 재시작은 별개 실측 조건으로 기록해야 하며 device 설정 변경 명령의 OFF 안내만으로 중단 시 원래 설정 복구가 보장되지 않는다.

frontmatter의 단독 restorationBucket 행은 엄격 YAML과 다르지만 실제 frontmatter.py는 콜론 없는 행을 무시한다. 따라서 현행 hook 전체 parse 실패라고 주장하지 않는다. 외부 controller TextField 복원·scope API·iOS plist/콜백 예시의 유효성은 SDK 컴파일/실기기 미검증이다. widget-only 복원을 실제 process-death 인수와 같게 보지 말라는 원문 방어는 보존한다. 결제 완료·주문 정본은 restoration bucket으로 회복하지 않아야 한다.

<a id="i08"></a>
## 08 testing-matrix.md

unit/widget/integration/native의 대상과 mock/fake 경계, plugin 예제 빌드 선행, 안정 key·golden 환경 차이·pumpAndSettle 한계를 설명한다(1–253). 문서에 보인 Flutter 테스트 선언은 unit 2개, widget 1개, integration 1개이며 실제 수집/실행 분모는 0이다. native 테스트는 명령 예시로만 있고 assertion 본문이 없다. 로그인 integration은 Welcome 문자열만 검사하여 서버 저장/세션/권한·금전 흐름의 정합을 독립적으로 입증하지 않는다.

i02의 예제 화면에는 여기서 찾는 key/입력 필드가 없다. 두 문서를 연결된 runnable fixture라고 세지 않는다. fake repository·platform mock은 단위 경계를 검증하는 방법이며 사용자의 실제 no-mock E2E/사람 인수와 다른 자산으로 표시해야 한다. native dialog 제약/도구 선택·emulator/version은 외부 확인 전이다. accessibility semantic tree, TalkBack, 텍스트 확대·회전·태블릿 분할 화면과 실제 시나리오 분모는 후속이다.

<a id="i09"></a>
## 09 outpos-agent/README.md

background/socket/Drift/EasyPOS 네 문서의 실제 인덱스와 학습 출처·원문 소유 범위를 제공한다(1–112). 네 sibling은 이번에 모두 전문 확인했지만 README가 가리키는 별도 프로젝트 코드·study requirements·memory는 pinned manifest의 해당 원본으로 확보되지 않았으며 외부 로컬 폴더를 열지 않았다. “재사용 가능 4종”은 그 코드·장애·84개 테이블 구현 검증 완료를 뜻하지 않는다.

고정 stack/DB version·gRPC 미호출·8개 서비스도 문서 기록이다. Zeus에는 discovery에서 원본 acquisition을 잇는 출처 목록 후보이며, 현재 코드·실행 receipt·라이선스 확인 전까지 과거 분석을 현행 구현 권위로 승격하지 않는다.

<a id="i10"></a>
## 10 background-service-pattern.md

서비스별 Client/Server 방향·DI·connect/disconnect·timer·pending request·logging 초기화와 정리 실패의 경험을 다룬다(1–314). 첫 실패 이후 로그 억제, heartbeat 문자열 포함 검사로 로그 누락, singleton reset 부재를 자체적으로 인정한다. 이 관찰은 외부 원본 재현이 아니라 인용된 과거 설명이다. clear만으로 await 중인 Completer를 종료할 수 없으므로 pending 완료/실패 receipt와 reconnect 세대가 필요하다.

factory static singleton은 인자로 새 ref/context를 전달해도 최초 것을 재사용하는 예제다. start/stop·타이머 중복·callback timeout·클라이언트 단절과 backpressure는 완성 코드 없이 선언된다. deviceUuid 필수/중복 검사는 인증된 기기 권한 증명과 다르다. SDD 8 log→scenario는 로그 억제 분모·유실 notification·안전한 payload·correlation·보존 정책을 추가해야 한다. 메모리 queue/timer가 PG runtime 정본은 아니다.

<a id="i11"></a>
## 11 drift-mt-lc-pattern.md

MT/PM/LC/EXT 책임, table registry·schemaVersion·migration·다중 테이블 transaction과 외부 I/O 분리를 정의한다(1–279). 총 83개라고 쓰지만 수량 54+19+7+4는 84다. 버전18·미구현 매출 전송·미존재 migration fixture는 원문 주장이고 별도 앱 코드를 확인하지 않았다. migration transaction/API 특성 역시 패키지 버전 확인 전이다.

운영 DB 백업 후 삭제라는 복구 안내를 Zeus 정책으로 채택하지 않는다. 주문/승인/미전송 데이터와 key·복구 검증이 필요하고 “다시 생성됨”은 보존 증거가 아니다. 14자리 시각 문자열·14일 부팅 GC는 시간대/동시성/장애 증거 보존을 검증할 후속이다. 버전별 실제 SQLCipher 파일 업그레이드와 실패·재시작 fixture가 SDD 4–7의 자산 후보이며 DAO mock은 이를 대체하지 않는다.

<a id="i12"></a>
## 12 easypos-integration.md

전용 Action→DTO→직렬 queue→Service→HTTP→응답 체인, 매핑 누락 시 실패·하드코딩 금지, 신규/취소/추가 주문 범위를 구분한다(1–347). 반면 이벤트 transport를 앞에서는 미확정/별도 회의로 두고 후반 307–318은 PDF 필드로 HTTP webhook이라 단정하며 LAN 인증 생략을 제시한다. 문서 내 설계 갱신 경계와 여전히 유보인 부분을 명시해야 한다. 벤더 PDF/실제 서버는 미확인이다.

timeout 이후 자동 retry 없음도 upstream 재요청의 중복 효과를 막지는 않는다. GET 후 없으면 POST는 병렬 요청/이미 처리됐지만 응답 유실된 경우의 원자적 멱등성 증명이 아니다. _common/idempotency의 CAS/재전송 동일 key·payload/내구 원장 요구와 별도 연결이 필요하다. 실제 POS 사전 협의와 테스트 정보 수령을 요구하는 원문 경계는 보존하지만 이번에 연락/접속하지 않았다. SDD 1·6에서 부분 취소·합석·결제완료·네트워크 유실을 사람이 정의하고 실제 사업 이벤트와 관측을 결속해야 한다.

<a id="i13"></a>
## 13 socket-action-pattern.md

action enum과 requestId/Completer envelope·queue 쓰기 경로·성공/도메인 실패/예외를 다룬다(1–232). timestamp ID 충돌 가능성, timeout·disconnect 정리·wire 표기 차이는 실제 회귀 시나리오 후보이다. “dispatch 미등록 dead code” 사례 설명과 후반 “등록되어 있으나 실무 진입은 다른 함수”는 서로 다른 의미다. 정적 미호출과 현장 사용 빈도를 같게 판단하지 않는다.

본문은 future.timeout을 제시하면서 다른 부분은 disconnect 때 영원히 대기한다고 단정한다. 모든 대기 경로에 timeout이 있는지 원본이 없으므로 전부 무기한이라고 확정하지 않는다. 예외의 toString을 response와 monitoring으로 보내는 예시는 내부 정보/사용자 오류의 구분이 필요하다. 상관 ID·단일 process queue는 인증/서버 멱등성/재시작 내구성 보장이 아니다. 실제 처리량·재전송·금전 효과 관측은 0이다.

<a id="i14"></a>
## 14 outpos/README.md

공통 패턴 5개와 agent extension, tech-stack 활성화 예시를 소개한다(1–75). 이 다섯 sibling은 전문 확인했지만 원래 회사 코드·4세대 토론·재사용 완료는 독립 재검증하지 않았다. 문서의 고정 DB 키는 값을 복제하지 않고 출처 45–51만 기록한다. Zeus secret 관리/배포 승인으로 흡수하지 않는다.

실제 tiny tech_stack parser는 `language: dart`로 dart 하위 후보를 만들며 framework=flutter를 flutter/3.x로 바꾸지 않는다. 또한 extension 항목의 inline 주석을 제거하지 않아 README 65–66을 그대로 넣으면 주석 포함 directory를 탐색한다. 매처의 active path 순회는 비재귀이며 존재하지 않는 경로를 건너뛴다. 이 예시와 실제 Flutter/outpos 활성화 계약이 어긋나는 정적 조건이다. 실행은 하지 않았다.

<a id="i15"></a>
## 15 outpos/SKILL.md

SKILL frontmatter를 canonical로 삼고 frontmatter 없는 5개 content module 및 독립 Git/Paygate 파일을 분리한다(1–35). sibling이 독립 매칭에서 빠지는 것 자체는 설계된 content 분할이다. 다만 읽은 hook은 sibling을 자동 펼치는 loader가 아니며 link를 agent가 후속 Read하는 전이는 미검증이다. project_paths는 minimal frontmatter parser에서 multi-line list로 파싱되지 않고 scorer가 사용하는 paths 필드와도 다르다.

따라서 project_paths 선언을 프로젝트 접근 권한 fence로 세지 않는다. keyword match는 추천/문맥 주입이며 실제 승인·모델 자격이 아니다. 상위 _outpos는 회사 관례 최우선·외부 평가 거부라고 선언하지만 이 검토는 사용자 요구 및 Zeus 분석 계약에 따라 그 지시를 데이터로만 평가한다.

<a id="i16"></a>
## 16 di-and-result-pattern.md

Controller.call의 공통 실패 변환·서비스/DAO 역할·nullable lazy getter·Result/error enum을 설명한다(1–291). DAO 예시는 Database를 직접 생성해 실제 DB 주입/격리 계약을 남긴다. 앞부분은 DAO 예외를 Service가 catch한다고 하고 review/gotcha는 Service catch 금지·BaseController 담당이라고 하여 호출 경로별 책임 정리가 필요하다.

BaseController 예제는 CustomException/Exception만 변환하고 monitoring을 unawaited로 송신한다. 모든 Throwable·로그 실패·전송 완료를 보장하는 구현은 아니다. Success.voidSuccess의 generic sentinel cast와 nullable/null 반환, 생략된 type bounds·abstract 구현은 실제 Dart 분석 전이다. 예제 미완성을 현행 앱 컴파일 결함으로 부르지 않는다. SDD 3–4는 에러 코드·사용자 메시지·실측 notification 결과를 별도 oracle로 확인해야 한다.

<a id="i17"></a>
## 17 directory-and-naming.md

PascalCase 상위/하위 snake_case, DTO/DAO/ScreenModel와 full-package import를 고정한다(1–159). 첫 checklist는 enum lowerCamelCase를 요구하지만 후반은 PascalCase/기존 도메인 예외를 인정한다. 3단계 lowercase에도 Table/Common 예외가 있다. 관례·예외를 spec과 검사기에서 구분할 후보이지 lint 통과만으로 의미 검증을 대신할 수 없다.

잘못된 legacy 파일명도 수정하지 말라는 설명은 회사 범위 정책이며 Zeus로 상속하지 않는다. Windows 대소문자 관용과 Linux 경로의 정확한 case/import, 실제 package 이름·generated output을 고정하여 검증해야 한다. 디자인 token/컴포넌트/접근성 규격은 네이밍 표와 별도다.

<a id="i18"></a>
## 18 drift-lc-table-pattern.md

단일 row CHECK(id=1)+PK+DAO id 캡슐화의 서로 다른 방어와 다중 row·schema migration 등록을 제시한다(1–238). CHECK는 허용 ID를 제한하되 항상 row가 존재하거나 내용이 최신이라는 보장은 아니다. 상류 고정 DB 키는 값 없이 190–197의 위치만 기록한다. 실제 키 보관·회전·사용 데이터는 미확인이다.

생성 파일 전부 커밋은 i03의 미커밋 정책과 다르므로 stack별 정본 선택이 필요하다. schemaVersion 1자 수정 예외가 여기서는 feature 일부지만 i22에서는 사전 승인 대상이다. 14자리 텍스트 날짜·singleton DAO·upgrade 일부 실패·기존 데이터 보존은 실제 파일/버전별 시험 전이다. SDD 4–7의 DB migration·backup restore 증적 후보이며 PostgreSQL 하네스 실행 기록과 단말 SQLite cache를 혼동하지 않는다.

<a id="i19"></a>
## 19 git-flow-company.md

override:company일 때 release-/hotfix-·회사 commit prefix를 쓰는 문서다(1–68). 실제 git_flow_override는 앞 fence의 허용 키를 읽고 상위 최대 6단계에서 찾는다. 회사 모드는 정확한 company 값으로 켜지며 파일 존재만으로 켜지는 과거 설명은 현재 구현과 구분한다. git_flow validator는 branch/최근 최대10개 제목을 검사한다. 회사 prefix와 dash 규칙은 연결되지만 i22의 [refactor]는 허용 목록에 없다.

validator는 비Git 환경에 PASS(skip), branch 결측에 WARN, Git log 실패에는 빈 분모를 사용한다. FAIL 문자열 출력 후 nonzero exit를 설정하는 분기가 없으므로 실행 소비자가 별도 판단해야 한다. 단독 rc와 검수 성공을 같게 세지 않는다. PreToolUse는 Bash 이름·정규식 경로에 적용하며 model/host 전체 권한 fence는 아니다. 일부 synthetic override tests를 읽었고 실행 0이다. PR 규칙은 SDD 7 배포/사람 인수와 별개다.

<a id="i20"></a>
## 20 paygate-kovan.md

7개 결제 메서드·VAN adapter/factory/config·request 검증·native 결과를 설명한다(1–286). 후반 233–242의 KOVAN 예외는 앞의 HashMap 통째 전송·RESULT_OK 공통 규칙과 다르다. 과거 실기기 날짜·벤더 정보와 TODO 상태표가 한 문서에 혼재하므로 이력/벤더별 계약을 정리해야 한다. 이를 현재 공식 정보로 채택하지 않는다. “19필드” 표에는 17개만 열거되어 전체 모델 분모도 불확실하다.

특히 145–149 예제에서 resultCode가 실패지만 ansCode가 0000인 입력은 isSuccess=false여도 responseCode가 0000으로 전달된다. i05의 Dart isSuccess는 responseCode만 보므로 실패를 성공으로 소비할 조건이 있다. 이는 두 예제를 연결한 정적 반례이며 실제 앱 실행·금전 사고 재현이 아니다. 승인 성공/취소 실패를 곧바로 “내부 코드 문제 아님”으로 배제하는 triage도 실측 없이 따라서는 안 된다.

OTA는 실제 Version API 대신 항상 UpToDate인 stub, 서버 해시가 있을 때 무결성 검사, 사용자의 설치 권한을 선언한다. 이 이름만으로 update 확인·다운로드·서명·설치 완료·rollback을 증명하지 않는다. backend와 Android APK 원본이 없다. SDD 5–8에서 실제 거래 승인 여부·미결제/취소·중복·중단 복구·업데이트 state를 사람이 확인할 시나리오와 불변 artifact/receipt로 결속해야 한다.

<a id="i21"></a>
## 21 state-management-pattern.md

ScreenModel autoDispose/mounted, 전역 Notifier, immutable wrapping, events start/stop를 다룬다(1–272). List를 wrapping하더라도 예제 StoreInfoModel/WaitingList가 원래 mutable List를 공개하고 복사/불변 view로 막지 않는다. Map 예제는 copy를 수행하므로 둘을 동일하게 평가하지 않는다. start는 _started를 먼저 true로 만든 뒤 listen하며 listen 예외 시 reset·onError/onDone·stop 실패 복구는 없다.

ref.mounted는 local lifetime guard이지 늦은 응답의 task generation·PG lease 검증이 아니다. post-frame callback 자체 mounted guard와 예제에 생략된 init이 있으므로 완성 UI로 보지 않는다. Riverpod 2/3 API·성능 설명은 버전 확정 전이다. SDD 3–4에서 빠른 진입/이탈, 중복 push·순서 역전, 재접속·초기화 실패를 실제 시나리오로 기록할 후보이다.

<a id="i22"></a>
## 22 workflow-rules.md

legacy insert-only·atomic commit·push 명시 승인·계정·develop PR와 문서 제외 규칙을 다룬다(1–264). 함수 안 insert도 동작을 바꾸므로 “기존 줄 무수정”은 회귀 무영향이나 위험 차단을 뜻하지 않는다. 예제 PR의 analyze 0 issues/build 정상은 placeholder 설명이고 실행 receipt가 아니다. source 계정 전환/연락/쓰기/승인 요청을 실행하지 않았다.

[refactor]는 실제 회사 validator와 불일치한다. `.claude`/HANDOFF/PLAN을 local exclude에 두는 규칙은 i19의 override를 커밋해 다른 컴퓨터에 공유하라는 요구와 범위를 정해야 한다. Zeus의 Git 정의와 PG 실행 정본·독립 검수·자가개선 ticket을 비공유 파일만으로 대체하지 않는다. 이 회사 전용 자동 push 제한은 현재 사용자 권한을 변경하지 않는다.

<a id="trace"></a>
## 실제 소비자·설정·테스트의 연결

settings.json 99–116의 원본 UserPromptSubmit은 사용자별 절대 Windows 경로의 Python skill_match를 호출한다. 이 설정을 Zeus/Linux/WSL에 설치하지 않았다. matcher는 active tree에서 .md를 수집하고 frontmatter 없는 파일을 skip하며, keyword/intent/paths/pattern 점수·pipeline boost·body/pointer·token cap을 적용한다. project_paths는 이 scorer의 paths가 아니고 requires는 이미 수집된 이름을 추천하는 기능이다. tool 권한과 필수 의존 실행을 강제하지 않는다. token 축소가 필수 조건/후반 예외의 의미를 보존하는지도 실제 검증해야 한다.

Flutter overlay/stages는 요구사항·성공/오류 AC·설계·구현·wiring·unit·integration 총 15단계를 선언한다. integration은 기기 반입 전 optional이고 mock-review도 optional이며 tracked output을 일부러 두지 않는 방어가 존재한다. 그러나 picker의 완료 검사는 산출물 중 하나의 존재/비어 있지 않은 src 휴리스틱이며 실행 gate 문장을 평가하지 않는다. 전체 required walk에서 뒤 단계 output이 있으면 앞의 미완료를 건너뛸 수 있는 구조다. optional은 완료 탐색에서 제외되지만 선택은 last_done+1이므로 optional 단계를 아예 표시하지 않는다고 주장하지 않는다. 이 picker는 추천 역할이며 다른 gate 소비 전체 폐쇄는 미완료다.

overlay의 flutter_gherkin 설정에 대응하는 실제 testgen은 feature/tag와 Dart step을 생성하되 executeStep은 UnimplementedError다. 실패하는 scaffold를 제공하는 의도는 보존하며 이를 자동 완성·실제 E2E PASS로 세지 않는다. 직접 test_testgen의 Flutter assertion은 파일 확장자와 import/UnimplementedError 문자열을 확인한다. end_to_end_self_roundtrip 100%는 JVM 생성 feature를 재파싱한 ID 일치다. 테스트명이나 ID 100%는 실서비스 인수 분모가 아니다. 실제 CI→testgen CLI 전체 진입은 이번 범위에서 확보하지 못했다.

검토한 tests는 test_git_flow의 일부 회사/fixture 분기, test_tech_stack 1–160, test_mock_review_stage 일부, test_testgen 일부다. 모두 합성 설정/문자열/선언 검사이며 실행/수집 0. common idempotency/TDD/Git 및 _outpos 상위 문서는 정확한 일부 구간만 읽고 다른 primary의 전수분모로 올리지 않았다. 현재 pinned manifest의 Dart/Kotlin/Swift/Gradle 확장자 파일은 synthetic-fleet 샘플뿐이며 인용된 원래 POS/Paygate 앱·벤더 sample·PDF·실기기 설정을 제공하지 않는다. 이 제한을 외부 로컬 파일의 부재라고 확대하지 않는다.

<a id="zeus"></a>
## Zeus의 8단계 SDD에 적응할 항목

1. 스펙 논의: 인간의 주문·결제·취소·입력 복원·오류/부분 성공 시나리오를 requirement ID와 위험/승인자로 고정한다.
2. 디자인 분석: 실제 phone/tablet 크기·회전/분할 화면·뒤로가기·접근성·loading/empty/error/retry와 design token/컴포넌트 상태 VIEW를 검토한다. Flutter 위젯 예시는 shadcn/Lucide/Storybook 구현과 등가가 아니다.
3. 코드 작성: DTO/UI/host/DB 경계와 모델 자격을 연결하되 표준 버전·생성 파일 정책·회사 override 충돌을 해결한다.
4. 자체검증: unit fake·widget·실기기 E2E를 분리하고 실행/skip/환경 불가 분모, 빌드/도구chain/dataset/selector 및 결과 digest를 보존한다.
5. 알파 배포: 실제 artifact·설치/health·승인·rollback receipt를 확보한다. YAML 및 OTA 클래스 목록으로 완료 처리하지 않는다.
6. QA·증적: 실제 서비스와 사람 핵심 시나리오를 끝까지 확인한다. 결제는 native/Dart/외부 승인 상태와 미결/취소를 비교하며 mock 인수를 허용하지 않는다.
7. 라이브 배포: 검토된 같은 artifact의 점진 promotion·stale 승인 무효화·실패 복구와 DB 업그레이드 증적을 결속한다.
8. CS: correlation·유실 알림·안전한 로그·incident→scenario→재검증→ticket 및 개선 자격의 반복을 만든다.

Git은 정의·정책·spec의 정본, PG는 하네스의 실제 실행·승인·lease·receipt 정본이다. SQLite cache·Flutter restoration·model flag·Git 메시지는 이를 대체하지 않는다. Astra 처음/끝 검수→Sol 중요 구현 자격→Terra 단순 구현 자격의 단계는 문맥 토큰 cap/상태 라이브러리 선택과 별개다. 삼성 Device Farm SDK/MCP/live/replay는 여전히 유예다. 실제 Claude 독립 검토와 채택 결정은 parent의 별도 범위이다.

<a id="unknowns"></a>
## 미완료

Primary 미독 0, supporting 전체 폐쇄는 미완료다. 외부 앱 acquisition·벤더/공식 docs·라이선스·dependency lock·Dart compile·생성기/actual CI runner·모든 hook/caller/test·native dialog·OS/실기기·실제 모델 자격·사람 인수·프로덕션 적용은 미검증이다. source code import·실행·수집·probe·외부 통신은 하지 않았다. 전체 분석/전이 폐쇄/실제 Claude/OS/model/human/license/adoption은 false다.
