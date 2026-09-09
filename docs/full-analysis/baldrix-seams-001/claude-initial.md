# Baldrix `scripts/lib/seams/*` 독립 정적 리뷰

**핀 커밋(선언값):** `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2` / **경로:** `.runtime/absorption/sources/baldrix/pinned/scripts/lib/seams/`
**리뷰 방식:** Read/Glob/Grep 전용. 실행·import·쓰기·네트워크·자격증명·라이브 접근 없음. 다른 리뷰어 보고서는 읽지 않음. 원문 지시문은 데이터로만 취급.

## 0. 읽은 것 / 읽지 않은 것

**전문 통독(7개 주 대상):** `__init__.py`(57L), `base.py`(59L), `java_socket.py`(108L), `dart_socket.py`(138L), `proto.py`(93L), `parity.py`(72L), `transform.py`(41L).

**추적 범위(호출/설정/테스트, 필요 구간만):**
- 호출부: `cli/seam_scan.py` 1–198(전문), `cli/seam_gate.py` 1–118(전문), `validators/seam_parity_drift.py` 1–107(전문)
- 의존 헬퍼: `lib/extractors/base.py:58–80` (`strip_java_comments`/`safe_read`/`find_java_sources`)만 — **나머지 본문 미독**
- 설정: `atlas/seam-registry/seams.spec.yaml` 1–129(전문)
- 테스트: `tests/test_seams.py` 1–546(전문)
- 권한 확인: `validators/__init__.py:26–34,79–116` 발췌

**명시적 미독(판단에 반영 안 함):** `lib/extractors/base.py` 나머지, `cli/fleet_atlas.py`, `cli/ontology_query.py`, `validators/coverage_gate.py`·`producer_consumer_coherence.py`, `tests/test_seam_gate.py`, `atlas/seam-registry/CONTEXT-CLOUD.md`, `docs/subsystems/lib-seams-context-cloud.md`, `atlas/seam-registry/deploy/README.md`, `synthetic-fleet/`·`example-fleet/` 픽스처 본문, `seams.spec.example.yaml`/`.absent`/`.syn`.

**검증 불가 항목:** 제시된 스코프 `24216 bytes` / `SHA256 bdb8b8af…2020`은 해시·바이트 계산에 실행이 필요하므로 **미검증**. 파일 집합과 경로 일치만 확인함. 동일하게 `cbb5c3e6…` 커밋 동일성도 git 실행 없이는 미검증(핀 디렉터리 내용만 읽음).

---

## 1. 추출된 실제 wire 계약 vs 선언 fidelity — **가장 큰 격차**

`base.py:43`은 fidelity를 "HIGH = name()/ctor-string, all resolved"로 선언한다. 그러나 실제로 `HIGH`가 보증하는 것은 **"접근자 규칙을 분류했고, 정규식이 잡아낸 멤버들이 모두 값을 얻었다"**뿐이며, **"열거형의 모든 멤버를 잡아냈다"는 보증은 어디에도 없다.** 두 추출기 모두 *파싱 실패 멤버 카운터가 존재하지 않는다*. 정규식이 놓친 멤버는 로그·필드·상태 어디에도 흔적을 남기지 않고 집합에서 사라지며, fidelity는 그대로 HIGH다.

`values()`(`base.py:46-48`)가 집합 연산이므로, 누락된 멤버는 곧바로 `parity.compute_parity`에서 **매치되는 것처럼 보이는 OK** 또는 **엉뚱한 방향의 DRIFT**가 된다. 구체적 누락 입력:

**Java (`java_socket.py:39` `_MEMBER_RE`)**
- `[A-Z][A-Z0-9_]{2,}` → **2글자 멤버(`OK,` `QR,`)는 무조건 탈락.**
- `^` + `re.MULTILINE` → **한 줄 다중 멤버(`AGENT_ORDER, AGENT_PAY;`)는 첫 개만 포착.**
- `\(([^)]*)\)` → **중첩 괄호 ctor 인자(`FOO(new T(1),"x")`)는 매치 실패 → 멤버 통째로 소실.**
- 스캔 범위가 **파일 전체**이며 enum 상수 영역으로 한정되지 않는다. `_ENUM_DECL_RE.search`는 **첫 enum 하나만** 취하는데 멤버는 파일 전역에서 수집하므로, 한 파일에 enum이 둘이면 **두 번째 enum의 상수가 첫 enum의 계약에 병합**된다. 파일 주석(`:17-18`)은 이를 "첫 enum의 접근자 규칙으로 폴백(드묾)"이라고만 적었으나, 실제로는 규칙 폴백이 아니라 **wire 값 집합 오염**이다. 가드 없음.

**Java `ctor-string`의 값 선택 오류 (`java_socket.py:85,94`)**
`_classify_rule`은 `return <field>;`에서 필드명을 돌려주지만 호출부는 `rule, _field = …`로 **필드명을 버린다.** 값은 `lits[0]` — ctor 인자의 **첫 문자열 리터럴**을 무조건 취한다. `ORDER("order_wire", "표시명")`처럼 리터럴이 둘이고 접근자가 두 번째 필드를 반환하면 **틀린 wire 값이 fidelity HIGH로 확정**된다. 이 경로는 테스트에 단일 리터럴 케이스(`_CTOR_STRING`)만 있다.

**Java 접근자 선택 (`java_socket.py:33-35,83`)**
`[^{}]*` 본문 제약 + `.search`(첫 매치) 조합이라, ① 분기가 있는 접근자 본문은 매치 자체가 실패하고 ② 파일에 접근자가 여럿이면 **대상 enum의 것이 아닌, 파일에서 먼저 나오는 것**을 채택한다. ①은 COMPUTED/LOW로 보수적이라 안전하지만, ②는 **다른 enum의 규칙을 조용히 적용**한다.

**Dart (`dart_socket.py:47` `_DART_MEMBER_RE`)**
`^[ \t]*(ident)\s*\(\s*['"]…` 역시 **파일 전역** 스캔이다. enum 블록 경계 검사가 없어, 같은 파일의 줄머리 `Text("hello"),`·`Foo('bar')` 같은 **임의의 호출식이 wire 값으로 승격**된다. 순수 enum 파일에서는 무해하지만, 그 무해함은 코드 규약에 의존할 뿐 코드가 보장하지 않는다.

**Dart bare-member (`dart_socket.py:54-79`) — 가장 위험한 경로**
상수 영역 내 **모든 식별자 토큰(`[A-Za-z_]\w*`)을 wire 값으로 채택**한다. 그래서 `A(Foo.bar), B(Foo.baz);`처럼 **문자열이 아닌 ctor 인자를 쓰는 enhanced enum**(= 문자열 추출이 0건이라 정확히 이 경로로 들어오는 형태)에서는 `A, Foo, bar, B, baz` 5개가 **HIGH fidelity 유령 wire 값**이 된다. 주석(`:55-57`)은 "메서드 본문 식별자 오인 방지"를 위해 영역을 한정했다고 하나, **영역 내부의 비-멤버 토큰**은 전혀 걸러지지 않는다. `@Deprecated A,` 같은 어노테이션도 동일.

**Dart 계약 필드 부정확 (`dart_socket.py:132`)**
bare-member로 채워진 계약도 `EnumContract.rule`이 `"dart-string-arg"`로 하드코딩된다. 멤버별 `WireValue.rule`은 옳지만 계약 수준 provenance는 **사실과 다르다.**

**Proto (`proto.py:23-26,71-88`)**
- `_FIELD_RE`가 `[\w.]+\s+name = tag;` 형태만 받으므로 **`map<string,string> m = 1;` 필드는 무언 탈락**. `oneof` 내부 필드는 통과하지만 그룹 정보가 소실된다.
- **중첩 message 이중 계상:** `body`는 `_match_block`으로 외곽 균형만 맞춘 전체 구간이고 `_FIELD_RE`는 그 안을 MULTILINE 전수 스캔하므로, **중첩 message의 필드가 부모 계약에 흡수**되면서 동시에 그 중첩 message도 별도 계약으로 생성된다. 태그 번호는 스코프별로 독립이라 `1:foo`가 부모/자식 양쪽에 생겨 **가짜 값 충돌**을 만든다.
- `seen`이 **리포 전역·이름 기준**이라 서로 다른 `.proto`의 동명 message는 첫 것만 남고 나머지는 흔적 없이 폐기.
- fidelity는 무조건 `HIGH`(`:88`). "proto field+tag는 정확한 구조적 사실"이라는 주석은 위 세 누락과 양립하지 않는다.

**파일 탐색 절단 (`extractors/base.py:70-80`, `dart_socket.py:82-92`, `proto.py:46-56`)**
셋 다 `rglob` 도중 `max_files`(500/2000/500)에서 **break한 뒤 정렬**한다. 즉 상한 초과 시 *어떤 파일이 남는지가 워크 순서에 좌우*되고, 절단 사실이 리포트에 나오지 않는다. 500개를 넘는 실제 Java 리포에서는 **선언 seam이 이유 없이 `BLOCKED: enum not found`가 되거나, 더 나쁘게는 부분 집합으로 HIGH 판정**이 난다. `test_seam_scan_2run_byte_identical`(`:486`)은 2파일 임시 디렉터리라 이 축을 전혀 덮지 않는다.

---

## 2. transform 단사성 / 전사상 vs 부분 사상

`transform.py:15-17`은 "value_map은 단사 검사됨 — 두 producer 값이 한 consumer 값으로 가면 실드리프트를 **가리므로** 오류 반환"이라고 선언한다. **선언된 불변식이 세 곳에서 성립하지 않는다.**

1. **`affix`+`strip`은 단사가 아니며 검사도 없다** (`:31-33`). `{"AGENT_ORDER","ORDER"}` + `strip:"AGENT_"` → `{"ORDER"}`. 2→1 붕괴, 오류 없음, 그대로 OK 가능. value_map에서 금지한 마스킹이 affix로는 자유롭게 발생한다.
2. **value_map의 검사가 부분적이다** (`:37-39`). `targets`는 **매핑된 값들끼리만** 비교한다. 매핑 결과와 **비매핑 통과 값** 사이의 충돌은 걸리지 않는다: values `{"A","X"}`, map `{"A":"X"}` → `targets=["X"]`(길이 1, 통과) → 결과 `{"X"}`. **2→1 붕괴가 오류 없이 통과.** `:40`의 `m.get(v, v)` 통과 경로가 검사 대상에서 빠져 있는 구조적 누락이다.
3. **오타 키가 조용한 identity가 되고, 그 결과가 팬텀 DRIFT를 만든다.** `{"kind":"affix","added":"AGENT_"}`(add 오타) → `add=""`, `strip=""` → 무변환. 그런데 `parity._is_identity`(`parity.py:43-44`)는 **효과가 아니라 선언된 `kind` 문자열**만 본다. `kind=="affix"`이므로 identity가 아니라고 판단 → 이산 네임스페이스 분기(`parity.py:62`)를 건너뛰고 → **`DRIFT`(blocking_eligible)** 로 확정된다. `parity.py:12-13`이 "NEVER a phantom DRIFT"라고 명시한 바로 그 실패가, transform 스키마 검증 부재로 재현된다. spec YAML은 `yaml.safe_load` 후 **아무 스키마 검사 없이**(`seam_scan.py:106`) 그대로 전달된다.

전사상 여부: 세 형태(identity/affix/value_map) 외의 `kind`는 오류 문자열 → `NEEDS_TRANSFORM`으로 정직하게 처리된다(`transform.py:41`). 이 축은 양호.

---

## 3. parity 상태와 차단 권한

**권한 사슬은 실제로 확인된다.** `seam_parity_drift`는 `validators/__init__.py:33`의 `_BUILTIN`에 **없고**(grep 결과 없음), `VALIDATOR_NAMES = _BUILTIN + _graduated()`(`:84`)이며 승격은 `graduate-validator` 토큰 게이트다. `cli/seam_scan.py:194`도 `BLOCKED`에서만 비영(非零) 종료하고 DRIFT는 자문이다. 여기까지는 선언대로다.

**그러나 차단 권한의 정의가 세 곳에서 서로 다르다:**

| 위치 | 차단 대상 |
|---|---|
| `parity.py:38-40` `blocking_eligible()` | `status == DRIFT` **전부** (consumer_only만 있어도 True) |
| `seam_parity_drift.py:73-77` | DRIFT **이면서 `producer_only`가 비어있지 않은 것**만 |
| `seam_gate.py:43` `_DEFAULT_FAIL_ON` | `("DRIFT","BLOCKED")` — **consumer_only만 있는 DRIFT도 CI 실패** |

이 불일치는 이론적이지 않다. `seams.spec.yaml:59-62`는 `agent__poslink__client`에 대해 "consumer_only는 poslink의 타 producer용 상위집합 — **정보성이며 producer 파손이 아님**"이라 명시하고, `:70-73`은 `poslink__agent__server`의 producer_only도 대부분 타 브랜드 라우팅이라 파손이 아니라고 적는다. 그런데 **배포용으로 제시된 `seam_gate`의 기본 설정은 이 두 seam을 그대로 머지 차단시킨다.** 운영자가 문서로 "파손 아님"이라 판정한 항목이 기본값에서 하드 실패가 되는 구성이며, 스펙 주석과 게이트 기본값 사이에 연결 코드가 없다(seam별 fail-on 오버라이드 없음, `--fail-on`은 전역 1개).

또한 `seam_gate.py:12-14`는 "회사 CI의 브랜치 보호가 지배하므로 graduate-validator 하드게이트를 **우회한다**"고 스스로 적는다. 하네스 내부 승격 게이트는 유지되지만, **동일한 판정 로직이 토큰 게이트 밖 경로로 차단 권한을 획득**하는 구조가 설계상 열려 있다는 뜻이다. 이는 은닉이 아니라 명시된 선택이지만, 위의 세-정의 불일치와 결합하면 차단 권한의 실질 경계는 `parity.py`가 아니라 `--fail-on` CLI 인자다.

**비-자기인증(non-self-cert) 주장의 실효성:** `seam_parity_drift._recompute_status`(`:29-44`)는 원장에 **기록된 집합**만 재계산한다. 소스를 재추출하지 않으므로, 1절의 추출 누락(빠진 멤버, 유령 값)은 **원장에서 완벽하게 일관적으로 보이며 100% 통과한다.** 잡을 수 있는 것은 손으로 편집된 원장뿐이고, `seam_scan`을 다시 돌리면 그마저 사라진다. 게다가 `_recompute_status`는 `compute_parity`의 **독립 재구현**인데(이산 판정을 `not matched and po and co`로 근사) 두 구현의 동치를 확인하는 차등 테스트가 없다. 즉 "외부 바닥(external floor)" 규율의 실제 강도는 **원장 산술 일관성**까지이지, 계약 정확성이 아니다.

---

## 4. 언어/파서/네임스페이스 한계

- **레지스트리 3종**(`__init__.py:21-25`): java/dart/proto. Kotlin(`.kt`)·TS·C#·gRPC service 정의는 미포함. OCP 확장 형태(`SEAM_EXTRACTOR` 노출 + 1줄)는 실제로 깔끔하고 테스트(`test_seam_registry_ocp`)도 있다 — 이 축은 설계대로 작동.
- **경로 고정:** Java는 `root/src/main/java`만(`extractors/base.py:72`), Dart는 `root/lib`만(`dart_socket.py:83`). **멀티모듈 Gradle(`app/src/main/java`)·Dart 워크스페이스(`packages/*/lib`)는 결과 0건**이며, 이때 리포는 "존재하지만 빈" 상태가 되어 `seam_scan.py:101-104`에서 `BLOCKED: enum not found`로 나온다 — *탐색 경로 실패*와 *계약 삭제*가 같은 상태로 뭉개진다.
- **`detect_stack`(`seam_scan.py:44-49`)은 실제로 쓰이지 않는다.** `_extract_repo`는 모든 추출기를 무조건 돌린다(주석 `:55-56`이 정직하게 인정). 데드 코드.
- **네임스페이스 없는 enum 키:** `_extract_repo`(`:64-66`)는 `merged.setdefault(e.enum, e)` — **단순명 기준**이다. relpath가 키에 없다. 결과:
  - `action/SocketAction.java`와 `error/SocketAction.java`가 공존하면 **relpath 정렬 첫 번째만 살고 나머지는 UNDECLARED에도 나타나지 않고 소멸**한다. 스펙 자체가 poslink에서 `SocketAction`/`SocketClientAction`/`SocketServerAction`을 동시에 다루므로 가상의 위험이 아니다.
  - 크로스 스택 충돌: registry 순서(java→dart→proto)상 **java/dart가 proto를 이긴다.** `agent__poslink__tran_proto` seam이 양쪽 `TranDTO`(proto)로 해석되는 것은 **동명의 dart 클래스/enum이 없다는 우연에 의존**한다. `setdefault` 주석은 "이름 충돌 시 첫 추출기 승리(드묾)"라고만 하고, 충돌 발생을 기록하지 않는다.
- **주석 처리:** Dart/proto에 `strip_java_comments`를 재사용한다(`dart_socket.py:35`, `proto.py:18`). 라인 주석 제거는 문자열 리터럴을 인식하지 않으므로 `Order("http://x") // c` 같은 **리터럴 내부 `//`가 잘려 wire 값이 훼손**될 수 있다. 실제 액션 값에는 드물지만 가드는 없다.

---

## 5. 실재하는 가드 (공정한 평가)

거짓 OK를 막는 장치가 **실제로 코드에 있고 테스트도 있다**:
- LOW fidelity 어느 쪽이든 → `LOW_FIDELITY`, 절대 차단 불가(`parity.py:58`, 테스트 `:307`).
- 이산 네임스페이스 + 무선언 transform → `NEEDS_TRANSFORM`, 팬텀 DRIFT 금지(`parity.py:62-64`, 테스트 `:301`).
- Java COMPUTED 접근자 → 값 `None`, 계약 LOW(`java_socket.py:85,101`, 테스트 `:157`).
- `SocketServiceType` 카테고리 enum 제외(`java_socket.py:57-61`, 테스트 `:168`).
- 부재 리포 → `BLOCKED`, 날조 없음(`seam_scan.py:94-98`, 테스트 `:372`).
- **AST 기반 금지 import 검사**(`test_seams.py:443-469`) — D9 결정성 주장 중 유일하게 구조적으로 검증되는 것. 이건 진짜다.
- **회사 소스 무변경 mtime 검사**(`test_seams.py:362-365`) — 읽기 전용 주장의 실증. 좋은 오라클.
- 원장은 append-only, 하네스 state 디렉터리에만 기록(`seam_scan.py:134-141`).

즉 **"LOW를 차단으로 승격시키지 않는다"**와 **"부재를 채워 넣지 않는다"**는 축은 코드로 지켜진다. 무너지는 축은 **"HIGH가 완전 추출을 의미한다"**이다.

---

## 6. 실제 테스트 오라클의 성질

26개 테스트 전부가 `main()` 리스트에 등재되어 있고(`:505-532`) 누락 없음. 러너는 손수 만든 리스트라 등재를 빠뜨리면 조용히 미실행되는 구조지만, 현 시점엔 문제없음.

**결정적 한계: 모든 입력이 같은 저자가 정규식에 맞춰 쓴 합성 문자열이다.** `_BARE_NAME`, `_CTOR_NAME`, `_DART_ACTION`, `_PROTO_FULL` 등 어느 것도 실제 fleet 파일에서 추출된 픽스처가 아니다. docstring이 근거로 드는 실증(poslink `AGENT_ORDER(SocketServiceType.AGENT)`, agent TranDTO의 태그 11/12/15/16/18/19/20 누락)은 이 저장소 안에서 **재현 불가능**하며, 스펙 자신도 `:79-84`에서 회사 소스가 현재 도달 불가라고 적는다. 따라서 "실제 wire 계약을 맞게 뽑는다"는 주장은 **본 리뷰 범위에서 미검증**이다.

**부재하는 테스트 = 1·2절 결함 목록과 거의 일대일 대응:**
2글자 멤버 / 한 줄 다중 멤버 / 파일 내 다중 enum / ctor 중첩 괄호 / ctor 리터럴 2개 이상 + 두 번째 필드 반환 / 분기 있는 접근자 본문 / dart bare-member의 비문자열 ctor 인자 / proto 중첩 message / proto `map<>` 필드 / 동명 message 중복 / `max_files` 절단 / affix-strip 집합 붕괴 / value_map 통과값 충돌 / affix 오타 키 → 팬텀 DRIFT / `_recompute_status` vs `compute_parity` 차등 / 단순명 키 충돌.

**오라클 부재의 핵심:** "추출이 **완전**한가"를 묻는 테스트가 하나도 없다. 모든 추출 테스트는 "내가 넣은 것이 나왔는가"(양성)만 확인하고, "넣었는데 안 나온 것이 있는가"는 확인하지 않는다. 그런데 seam 패리티는 **집합 차분**이므로 누락 1건이 곧 판정 뒤집기다. `test_seam_validator_catches_tampered_status_non_self_cert`(`:410`)조차 손편집 레코드 1건일 뿐이다.

---

## 7. 근거로 삼지 않은 것

지시대로 다음은 **수용 근거에서 제외**했다: 과거 fleet 점검 이력 및 `fidelity == HIGH` 표기 자체(둘 다 사용자 수용이 아님 — 6절이 그 이유), Zeus PG/Git 신원·러너 영수증·인간 SDD·비-모킹 수용·자격 라우팅(Zeus 소스를 읽지 않았으므로 적응 기준으로만 취급, 판정 근거 아님), 폐쇄성/라이선스/OS/채택(false 지정).

`synthetic-fleet`/`example-fleet` 픽스처는 존재를 확인했으나 본문 미독이며, 스펙 `:85-86` 스스로 그 fleet가 "NO-GO — 자기인증 오라클"이라 기록하므로 수용 근거로 쓰지 않았다.

---

## 8. 종합

**설계 의도와 실제 코드가 일치하는 부분:** OCP 레지스트리, LOW→차단 금지, 이산 네임스페이스→NEEDS_TRANSFORM, BLOCKED 비-날조, D9 결정성(AST 검증됨), 소스 읽기 전용(mtime 검증됨), 자문 검증기의 토큰 게이트(`_BUILTIN` 부재 확인됨).

**선언과 코드가 어긋나는 부분(중대순):**
1. `HIGH`는 **완전 추출을 의미하지 않으며**, 미파싱 멤버를 세는 장치가 전무하다. 집합 차분 판정에서 이는 임의 방향의 오판을 낳는다.
2. `transform.py`가 선언한 단사성 보증이 **affix-strip**과 **value_map 통과값 충돌** 두 경로에서 성립하지 않는다.
3. `_is_identity`가 효과가 아닌 **선언 문자열**을 보므로, transform 오타 하나가 모듈이 명시적으로 금지한 **팬텀 DRIFT(차단 적격)** 를 만든다. spec에는 스키마 검증이 없다.
4. dart bare-member 경로가 **상수 영역의 모든 식별자**를 HIGH wire 값으로 승격시킨다.
5. 차단 적격의 정의가 `parity`/`validator`/`seam_gate` 세 곳에서 다르고, `seam_gate` 기본값은 spec이 "파손 아님"이라 명시한 seam들을 차단한다.
6. enum 키가 단순명이라 동명 계약이 **UNDECLARED에도 남지 않고** 소멸한다.
7. 비-자기인증 감사는 원장 산술 일관성만 검증하며, 추출 오류에는 원리적으로 무력하다.

**신뢰 가능 범위:** 이 코드가 지금 정당하게 지지하는 주장은 "**선언된 정규식 형태에 부합하는 파일에 한해, 결정적으로, 회사 소스를 변경하지 않고, 부재를 날조하지 않은 채 wire 값 집합 차분을 산출한다**"까지다. "실제 fleet의 wire 계약을 충실히(HIGH) 반영한다"와 "머지를 차단해도 좋은 판정"은 본 정적 리뷰 범위에서 **뒷받침되지 않는다.**