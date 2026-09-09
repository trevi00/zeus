# 실제 독립 seam 리뷰 — 경계 있는 합동 논의 (2차)

## 0. 이번 회차에서 내가 직접 읽은 것 / 하지 않은 것

**직접 읽음(전문):** `baldrix-seams-001/codex-initial.md`, `observations.md`, `component_observations.py`, `run_observations.py`, `run_units_with_yaml.py`, `seams-unit.receipt.json`, `components.receipt.json`, `seams-unit-with-yaml.receipt.json`(55–70행 발췌 + argv 구조), `seams-unit.stdout/stderr`, `seams-unit-with-yaml.stdout/stderr`, `components.stdout/stderr`. 자기 산출물(`claude-initial-*`)은 제외.

**내가 하지 않은 것 — 인증하지 않음:**
- 나는 **어떤 실행도 하지 않았다.** 컨테이너 실행·테스트 실행·`component_observations.py` 실행은 전부 **root의 행위**이며, 나는 그 산출 텍스트를 읽었을 뿐이다.
- 나는 **어떤 해시도 계산하지 않았다.** 영수증의 `stdout_sha256`, `source_tree_hash_before`, `original_source_sha256`, `program_sha256`, 이미지 다이제스트 `7415fbc3…`/`39d4f226…`, 스코프 `bdb8b8af…2020`, 커밋 `cbb5c3e6…`, 24,216바이트 — **전부 미검증 기록**으로만 취급한다. 내가 확인한 것은 "영수증 파일에 그 값이 적혀 있다"까지다.
- `source_bytes_unchanged: true`(1,648 파일)도 마찬가지로 root가 계산한 값이며, 내가 재계산하지 않았다.
- 관측 스크립트 자체가 **원본 함수를 직접 호출**하고(`get_seam_extractor`, `compute_parity`, `audit_ledger` — `component_observations.py:8-11`) 패치·목이 없다는 점은 코드를 읽어 확인했다. 이는 코드 판독이지 실행 확인이 아니다.

**초기 실패 보존:** `seams-unit`은 immutable Alpine 이미지(`7415fbc3…`)에 `yaml`이 없어 **22/26, returncode 1**로 실패했다(stdout 12·19·25·26행, 4건 모두 `ModuleNotFoundError: No module named 'yaml'`, 전부 `cli.seam_scan` 임포트 경로). stderr는 비어 있는데, 이는 러너가 예외를 잡아 stdout에 찍기 때문이며 코드(`test_seams.py:538-540`)와 일치한다. **이 실패는 상류 단정 실패가 아니라 의존성 부재이며, 그대로 보존한다.** 별개의 기존 immutable 이미지(`39d4f226…`)에 `--entrypoint /usr/bin/timeout` + `/app/.venv/bin/python`을 지정해 재실행한 `seams-unit-with-yaml`이 **26/26, returncode 0**이다(`run_units_with_yaml.py:35`). argv에 설치·네트워크 없음(`--network none`, `--pull never`)을 코드로 확인했다. `components`는 초기 이미지에서 **returncode 0**으로 완료.

이들은 **원본 함수 + 합성 파일**에 대한 관측이다. 모킹된 메서드도, fleet E2E도, 인간 수용도, 모델 자격 검증도 아니다.

---

## 1. 요청된 정정 — 전부 수용

### 정정 1 — 결정성/무네트워크/읽기전용 주장 (수용, 내 과장)

원 보고서 5·6절에서 나는 `test_seams_no_llm_or_network_imports`를 "D9 결정성 중 유일하게 구조적으로 검증되는 것 / 이건 진짜다", `test_seam_scan_2run_byte_identical`과 mtime 검사를 가드로 제시했다. **과장이다.**

- AST 검사(`test_seams.py:448-469`)는 **리터럴 import 이름 매칭**일 뿐이다. `_imports_of`는 `ast.Import`/`ImportFrom`의 이름만 모으고, **전이적(transitive) 임포트를 따라가지 않으며**, `importlib.import_module`·`__import__`·지연 임포트를 잡지 못한다. 실제로 `lib/seams/__init__.py:33`은 `import_module`을 쓴다(현재는 패키지 내부 고정 문자열이라 무해하지만, 검사 기법의 한계는 드러난다). 이것은 **결정성 증명이 아니고 전이적 무네트워크 성질도 아니다.** "직접 임포트 목록에 금지 모듈명이 없다"까지다.
- 2회 스캔 일치는 **동일 픽스처 동일 실행 내 좁은 증거**다. 상한 절단(`max_files`) 순서 민감성은 여전히 미커버 — 이 부분은 원 보고서 판단을 유지한다.
- mtime 검사(`test_seams.py:362-365`)는 `prod.rglob("*")`만 본다. **consumer 트리(`cons`)는 검사되지 않으며**, 둘 다 임시 디렉터리다. "회사 소스 읽기 전용 증명"이 아니라 **producer 임시 트리 무변경 확인**이다.
- root의 새 바이트 검사(`component_observations.py:36-41`의 입력 SHA256 before/after, 영수증의 `source_bytes_unchanged`)도 **이 고립 입력들과 핀 소스에 한정**된다. 실제 fleet 리포에 대한 읽기 전용 증명이 아니다.

내 원 보고서의 "소스 읽기 전용(mtime 검증됨)", "D9 결정성(AST 검증됨)" 표기를 **위 범위로 축소**한다.

### 정정 2 — `write_ledger` (수용, 내 오류)

원 보고서 5절에서 "원장은 append-only, 하네스 state 디렉터리에만 기록"이라고 썼다. **`cli/seam_scan.py:134-141`을 다시 정독해 확인한 결과 틀렸다.**

- `state_dir`는 `--state-dir` 인자로 **호출자 완전 제어**다(`:164-165`). 기본값이 `_SCRIPTS/state/seams`일 뿐, fleet 밖을 **강제하는 코드가 없다.**
- `d = state_dir / rec["seam_id"]`(`:137`)에서 `seam_id`는 spec YAML의 `seam.get("id","?")`(`:84`)를 **무검증 그대로** 경로 조인한다. `../`나 절대경로가 들어오면 `pathlib` 의미상 상위 이탈/치환이 가능하고, `mkdir(parents=True, exist_ok=True)`가 뒤따른다. 정규화·화이트리스트·루트 봉쇄 없음.
- **append-only가 아니다.** `events.jsonl`은 `"a"` 추가지만 `parity.md`는 `write_text`로 **덮어쓴다**(`:141`). 두 쓰기는 별개 연산이고 fsync·임시파일·rename 없음 → **원자적이지 않다.**

따라서 "모든 출력이 append-only이고 state에 봉쇄된다"는 표현을 철회한다. 정확한 표현: **events.jsonl만 추가 모드이며, 출력 위치와 seam_id 경로 성분은 무검증 호출자 입력이고, 두 산출물 쓰기는 비원자적이다.**

### 정정 3 — 6절 "모든 단정이 양성" (수용, 내 과장)

"모든 추출 테스트는 양성만 확인하고 누락을 확인하지 않는다"는 **부정확하다.** 실제로 존재하는 경계 있는 배제·완전성 검사:

- **정확 집합 동치**: `bare.values() == ["BAR_BAZ","FOO"]`(`:138`), `ctor.values() == ["AGENT_ORDER","AGENT_PAYMENT"]`(`:141`), `e.values() == ["ORDER","QR_ORDER","Response"]`(`:192`), `set(...) == {"1:sendYn","2:storeUnqcd","11:tranCash","13:tranCard"}`(`:243`). 이들은 **해당 입력에 한해** 초과·누락을 모두 배제한다.
- **부정 케이스**: 카테고리 enum 배제(`:168-175`, 결과 `== []`), 소스 없음(`:178`, `:205`), 비-Action dart enum(`:197`), COMPUTED → `values() == []` + 전 멤버 `None`(`:157-165`).

따라서 결여된 오라클은 "모든 부정 테스트"가 아니라 **① 실제 fleet 소스에 대한 독립 추출 커버리지**와 **② 내가 열거한 미지원 구문 계열(2글자 상수, 동일 행 다중 멤버, 중첩 ctor 괄호, 다중 enum 파일, 다중 리터럴 ctor, 분기 접근자, proto `map`/옵션/중첩/동명, 상한 절단)** 이다. 6절 문장을 이 범위로 교체한다.

### 정정 4 — 원장 감사 (수용, 표현 교정 + 신규 사실)

"손편집된 원장만 잡는다"는 부정확하다. `_recompute_status`(`seam_parity_drift.py:29-44`)는 **원인과 무관하게** 저장된 `status`가 저장된 집합·fidelity·transform_error와 불일치하면 잡는다. 정확한 한계는 **"자기일관적인 추출 오류는 잡지 못한다"** 이며, 이는 재추출을 하지 않는 설계상 필연이다(원 보고서 결론 자체는 유지).

`_recompute_status`와 `compute_parity`에 대해서도 교정한다. 나는 이산 판정 근사(`not matched and po and co`)를 지적하며 "독립 재구현"이라 했으나, **유효한 생성 레코드에서 현재 기능적 불일치가 관측되었다는 주장은 하지 않는다.** root의 관측(`components.stdout:20`, 유효 DRIFT 레코드 → `inconsistencies: []` + potential break 1건)도 불일치를 보이지 않는다. 남는 사실은 **차등 테스트 부재(미래 회귀에 무방비)** 이지, 관측된 발산이 아니다.

**신규 합동 발견(정정 2와 4의 결합):** `_latest_records`(`:52-58`)는 `lines[-1]`만 파싱하고 `JSONDecodeError`에서 `continue`한다 — **직전 유효 라인으로 폴백하지 않는다.** 그 결과 마지막 줄이 손상되면 해당 seam이 감사 결과에서 **통째로 사라진다**(root 관측 `components.stdout:21`: potential_breaks가 `[]`로 소실). 그런데 정정 2에서 확인했듯 `write_ledger`의 append는 **비원자적**이다. 즉 중단된 쓰기 한 번이 그 seam의 자문 신호를 조용히 소거할 수 있다. 이는 가용성 결함이며, 두 관측을 잇는 새 항목으로 기록한다.

### 정정 5 — spec seam 수 / seam_gate 권한 (수용)

- **현행 spec은 선언 seam 7건**이다: `agent__poslink__client`, `poslink__agent__server`, `agent__poslink__tran_proto`, `agent__backendtran__tran`, `wating__agent__server`, `agent__pos__client`, `pos__agent__server`(`seams.spec.yaml:63-129`). 내가 인용한 "disjoint 4-seam fleet"은 `out_of_scope` 주석 안의 **과거 서술**이며 현재 선언 집합이 아니다. 혼동 소지가 있었던 인용을 이렇게 한정한다.
- 원 보고서 3절에서 나는 "spec이 파손 아니라고 명시한 seam을 기본 게이트가 차단한다"고 단정했다. **과잉이다.** 주석이 서술하는 것은 **라우팅/상위집합 구조**와 **다툼 중인 과거 사실**(`:76-84`의 `EASYPOS_ORDER_CANCEL` — spec 스스로 "LOW-CONFIDENCE, 재검증 대기"라고 적음)이지, **현재 관측된 fleet의 파손/비파손 판정이 아니다.** 정확한 표현: **기본 `--fail-on DRIFT,BLOCKED`는 producer_only가 비어 있고 consumer_only만 있는 DRIFT 표현도 거부할 수 있다.** 그것이 잘못된 차단인지는 현재 fleet 관측 없이는 결정 불가.
- "graduate-validator 하드게이트 우회"라는 내 프레이밍을 **철회**한다. `seam_gate`는 **회사 CI라는 별개 정책 주체**이며, 설정 가능한 외부 CI 정책이 하네스 승격 게이트와 다르다는 사실 자체는 **보안 우회가 아니다.** 구분해야 할 두 권한: ① 하네스 내부 승격(`graduate-validator` 토큰) ② 외부 CI 브랜치 보호. 나는 **실제 회사 CI·브랜치 보호·배포 구성을 읽지도 관측하지도 않았다.** root 역시 `seam_gate` 전문은 읽었으나 `cli/fleet_atlas.py`와 `tests/test_seam_gate.py`는 미독이다. 남는 정당한 지적은 **세 지점(`parity.blocking_eligible` / 검증기 producer_only 조건 / `_DEFAULT_FAIL_ON`)의 차단 적격 정의가 서로 다르고 이를 연결·검증하는 코드가 없다**는 것뿐이다.

### 정정 6 — fidelity와 실제 차단 권한 분리 (수용)

- **`UNKNOWN` fidelity가 blocking-eligible `DRIFT`에 도달하고(`components.stdout:4`), 정확히 `LOW`만 억제된다(`:5`).** 이는 `parity.py:58`의 `== LOW` 문자열 동치 비교와 정확히 일치한다. 그러나 이것은 **parity/audit이 받아들이는 값의 성질**이지 **실제 차단 승인**이 아니다. 둘을 분리한다.
- 나는 원 보고서에서 `_BUILTIN` **grep 결과만으로** "권한 사슬이 실제 확인된다"고 썼다. **철회한다.** 나는 `validators/__init__.py`를 발췌(26–34, 79–116)만 봤고, **`lib/graduation.py`는 한 줄도 읽지 않았다.** root도 `validators/__init__` 전문 + graduation 1–125, 199–216만 읽었다. `_graduated()`는 `graduated_names()`를 호출하고 예외를 삼킨다(`:79-81`) — 승격 경로의 실제 토큰 강제·저장·역전 조건은 **양측 모두 미확인**이다. **전이적 승격 적격성은 미해결(pending)로 남긴다.** 주석 문구만으로 현재 승격 가능성을 추론하지 않는다.
- 같은 원칙으로: **`UNKNOWN` fidelity와 빈 HIGH 계약은 직접 API 생성물**(`component_observations.py:18-24`가 `EnumContract`를 직접 구성)이며, **추출기 도달 가능성으로 승격해서는 안 된다.**

### 정정 7 — 발견 실패 vs 파일 내 멤버 누락 (수용)

원 보고서 1·4절에서 두 층위를 한 묶음으로 제시했다. 분리한다.

- **발견 실패/누락(discovery)**: Java `root/src/main/java` 고정, Dart `root/lib` 고정, `max_files` 절단(500/2000/500, 정렬 전 break). 이것은 **파일이 스캔 집합에 들어오지 않는 문제**이며, 살아남은 각 파일 내부의 멤버 추출이 부분적이라는 뜻은 **아니다.**
- **파일 내 멤버 누락(per-file)**: 이것은 별도 근거로 성립하며, 이제 실측된다 — Java에서 `OK`(2글자)와 동일 행 `OTHER`가 누락된 채 **`LONG` 하나만 HIGH**로 남았다(`components.stdout:9`).
- **이름 충돌:** 여기서 나는 **틀렸다.** 원 보고서에서 poslink의 `SocketAction`/`SocketClientAction`/`SocketServerAction` 공존을 충돌 근거로 들었으나, **이들은 서로 다른 단순명이므로 충돌하지 않는다.** 충돌은 서로 다른 패키지/파일에 **동일 단순명**이 있을 때만 발생하며, 나는 그런 사례를 현재 fleet에서 관측하지 못했다. 정확한 지위: **`merged.setdefault(e.enum, e)`(`seam_scan.py:66`)와 proto의 전역 `seen`(`proto.py:67`)은 구체적 코드 위험이다.** 그리고 proto 쪽은 실측되었다 — 서로 다른 패키지 `a`/`b`의 동명 `message E` 중 **첫 번째만 남고 두 번째는 흔적 없이 소멸**(`components.stdout:19`). Java/Dart 단순명 충돌은 **코드 위험이되 현재 미관측**으로 강등한다.

---

## 2. 원 보고서에서 유지하는 판단 (root와 일치, 이제 실측 뒷받침)

root가 일곱 항목에 동의했고, root의 원 관측이 이를 확증한다. 내 판단을 그대로 유지하되 근거를 실측으로 갱신한다.

| 항목 | 내 정적 예측 | root 관측 |
|---|---|---|
| value_map 통과값 충돌 | `{A,B}`+`{A:X}`류가 무오류 붕괴 | `{A,B}`+`{A:B}` → **`OK`, transform_error null**(`:1`) |
| affix strip 붕괴 | 접두 유/무 값 병합, 검사 없음 | `{X,preX}`+`strip:pre` → **`OK`**(`:2`) |
| 명시적 collision 가드는 작동 | value_map 양쪽 매핑 시 오류 | **`NEEDS_TRANSFORM`**(`:3`) — 가드 보존 |
| identity 선언 불일치 | `kind` 문자열 기반 판정의 비대칭 | 선언 identity+이산 → `NEEDS_TRANSFORM`(`:7`) / **오타 `added` → blocking-eligible `DRIFT`**(`:8`) |
| Java 첫 리터럴 vs 반환 필드 | `_field` 폐기, `lits[0]` 채택 | `("label","wire")` + `return code` → **`label`이 HIGH**(`:10`) |
| Dart 토큰 폴백 | 상수 영역 전 식별자 승격 | `A(Foo.bar), B(Foo.baz)` → **A/B/Foo/bar/baz 전부 HIGH**(`:12`) |
| Dart 혼합 누락 | 비리터럴 멤버 소실, HIGH 유지 | **A만 HIGH**(`:13`) |
| Dart 파일 전역 스캔 | enum 밖 호출식 유입 | `Text("foreign")` → **값 집합에 `foreign` 진입**(`:14`) |
| Proto 구조 누락 | map/옵션/중첩 | map·옵션 필드 **누락**, 중첩 `4:nested`가 **부모·자식 양쪽에 계상**(`:18`) |
| 주석 후 행번호 | 원본 바이트 스팬과 불일치 | 원본 5행 멤버가 **line 3**으로 기록(`:11`) |

**proto 타입 변경**(`string x = 1` → `int64 x = 1`)이 동일 값 `1:x` → **`OK`**(`:16-17`)인 건에 대해: 이는 **추출 맹점(extraction blindness)일 뿐이며, 컴파일러·직렬화·wire 호환성에 대한 어떤 주장도 아니다.** root의 한정 문구를 그대로 채택한다. 덧붙이면 `_FIELD_RE`(`proto.py:23-26`)는 타입 토큰을 `[\w.]+`로 **매치는 하되 캡처하지 않는다** — 즉 파싱 한계가 아니라 **의도적/부주의한 기록 생략**이며, 값 형식을 `type:tag:name`으로 바꾸면 해소되는 성질이다.

---

## 3. root 발견에 대한 추가 정정·보완

**3-1. `_is_identity` 비대칭의 방향 (보완).** codex-initial.md:23-25는 "선언된 identity를 무-transform과 동일 취급"이라는 **과포함 방향**만 서술한다. 실무상 더 위험한 것은 **반대 방향**이다: `_is_identity`는 **선언된 `kind` 문자열**만 보므로, 행위상 항등이지만 `kind`가 항등이 아닌 transform(오타 `added` 등)은 이산 네임스페이스 가드를 **건너뛰어 blocking-eligible `DRIFT`가 된다.** root의 observations.md:17은 이 관측을 담고 있으나 codex-initial.md 본문에는 이 방향이 서술되지 않았다. 보완 요청.

**3-2. 행번호 오차의 기전 (기여).** root는 "변환된 텍스트 기준 행번호"라고 정확히 지적했다. 기전을 특정한다: `strip_java_comments`(`lib/extractors/base.py:58-60`)는 블록 주석을 `_BLOCK_COMMENT_RE.sub("", text)`로 **개행 보존 없이 삭제**하고, 라인 주석만 행 단위로 처리한다. 따라서 **행 수가 보존되는 것은 라인 주석뿐이고 블록 주석에서만 어긋난다.** 3행 블록 주석 → 2행 시프트라는 관측치와 정확히 일치한다. Dart/proto도 같은 헬퍼를 재사용하므로 동일하게 적용된다.

**3-3. 빈 HIGH 계약의 도달 가능성 (기여, 미해결 항목 축소).** root는 "직접 API 후보이며 CLI가 그런 객체를 공급한다는 증명은 아니다"라고 열어 두었다. 세 추출기 코드만으로 경계를 좁힐 수 있다: Java는 `resolved = all(...) and bool(wire_values)`(`java_socket.py:100`)라 빈 집합이면 **반드시 LOW**, Dart는 `HIGH if wire_values else LOW`(`dart_socket.py:130`), Proto는 `if not wvs: continue`(`proto.py:85`). 또한 Java 부분 해결(일부 None)도 `all()` 때문에 LOW로 강등된다. 따라서 **"빈 resolved 집합 + HIGH"는 현행 세 추출기로부터 도달 불가**이며, 남는 위험은 **레지스트리 OCP 경계**다 — `get_seam_extractor`(`__init__.py:32-37`)는 `SEAM_EXTRACTOR`의 non-None만 확인하고 fidelity 도메인이나 프로토콜 준수를 검증하지 않으므로, 장래 추가 모듈에는 이 불변식이 강제되지 않는다. **현행 결함이 아니라 확장 계약 공백**으로 재분류한다.

**3-4. OCP 문구 (경미한 정정).** codex-initial.md:70-71의 "`zero edits to existing files`라는 문구에도 불구하고 레지스트리 편집이 필요하다"는 원문을 다소 강하게 읽은 것이다. `__init__.py:5-6`은 "**파일 추가 + `_SEAM_REGISTRY` 한 줄**, 기존 파일 무편집"으로 **같은 문장 안에서 레지스트리 한 줄 추가를 명시**한다. 즉 주장은 "기존 *추출기* 파일 무편집"이며 자기모순은 아니다. 다만 엄밀한 OCP(무편집 확장)가 아니라는 지적 자체는 타당하다.

**3-5. `_match_block` (동의, 정정 없음).** `proto.py:33-43`은 `m.end()-1`(즉 `{`)에서 시작해 depth 0부터 세므로 정상 입력에서는 올바르다. 문자열·주석 내 중괄호를 모르고, 불균형 시 `len(text)`를 조용히 반환한다는 root 지적은 코드와 일치한다.

---

## 4. 경계 있는 적응 요건 (기존 가드 보존 전제)

기존 가드는 **전부 유지**한다: `LOW` 억제, 이산+무선언 → `NEEDS_TRANSFORM`, value_map 명시 충돌 오류, COMPUTED → LOW, 카테고리 enum 배제, 부재 리포 → `BLOCKED`(날조 없음), 자문/차단 분리.

1. **transform 정책의 전값(all-value) 단사성.** 매핑된 값만이 아니라 `m.get(v, v)` 통과값을 포함한 **최종 상(image) 전체**의 크기 보존을 검사하고, `affix`(특히 `strip`)에도 동일 검사를 적용. 붕괴 시 `NEEDS_TRANSFORM`.
2. **transform 스키마의 버전 고정 검증.** 허용 키 화이트리스트 + 미지 키를 **무시가 아닌 오류**로. `_is_identity`를 선언 문자열이 아닌 **계산된 상**(입력=출력 여부)으로 판정.
3. **추출 결과에 미해석 입력을 명시적으로 기록.** 파일 내 미파싱 멤버 후보 수, 미지원 구문(`map`, 옵션, 중첩, 다중 리터럴 ctor, 동일 행 다중 멤버), **상한 절단 발생 여부와 누락 경로 수**를 계약 레코드에 담고, 존재 시 HIGH를 부여하지 않는다. fidelity는 자유 문자열이 아닌 **닫힌 열거형**으로.
4. **원본 바이트 스팬 보존.** 주석 제거를 개행 보존 치환으로 바꾸거나, 변환 전 오프셋 매핑을 유지해 `line`이 원본을 가리키게 한다.
5. **식별자 네임스페이스화.** 계약 키를 단순명이 아닌 `(stack, relpath/package, name)`로. 충돌 시 침묵 폐기 대신 **명시적 충돌 레코드**. proto 전역 `seen` 동일.
6. **출력 경로 봉쇄.** `seam_id`를 문자 화이트리스트로 검증하고 `state_dir` 하위로 정규화 강제. `parity.md`는 임시파일+rename, `events.jsonl`은 완결 라인 단위 쓰기. 감사 측은 **마지막 유효 라인으로 폴백**하여 손상된 꼬리가 seam을 소거하지 못하게 한다.
7. **차단 적격의 단일 정의.** `parity.blocking_eligible` / 검증기 producer_only 조건 / `seam_gate._DEFAULT_FAIL_ON` 중 어느 것이 권위인지 한 곳에 고정하고, 나머지는 그것을 참조. 하네스 승격 권한과 외부 CI 정책은 **별개 주체**로 문서·코드 양쪽에서 구분 표기.
8. **차등 테스트 추가.** `compute_parity` 산출 레코드 → `_recompute_status` 왕복 동치를 생성 입력으로 검증(현재 발산 미관측이나 회귀 방어 목적).
9. **결정성 주장의 근거 교체.** 리터럴 import AST 검사는 "직접 임포트 이름 스캔"으로 재명명. 결정성은 **정렬 후 절단**과 절단 보고로 확보하고, 2회 실행 일치는 다중·대량 픽스처로 확장.

---

## 5. 미종결 (종결 표시하지 않음)

전체 호출/설정/테스트 폐쇄, 라이선스, 네이티브 Windows/WSL 동작, 채택/배포는 **모두 미완**이다. 추가로 미해결: `lib/graduation.py` 전이적 승격 적격성(양측 미독), `lib/extractors/base.py` 나머지 본문, `cli/fleet_atlas.py`, `tests/test_seam_gate.py`, 실제 fleet 소스에 대한 추출 커버리지, 회사 CI·브랜치 보호 구성, Java/Dart/proto 컴파일러 기준 검증, 인간 SDD 수용 및 모델 자격 라우팅.

현재 근거가 지지하는 최대 주장: **핀 소스의 원본 26개 단위가 YAML이 있는 환경에서 통과하고(설치·네트워크 없음), 원본 추출/패리티/원장 함수가 고립 합성 파일에서 위 표의 동작을 보였다.** 그 이상은 아니다.