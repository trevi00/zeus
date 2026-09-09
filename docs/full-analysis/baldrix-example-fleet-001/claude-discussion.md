16개 지원 구현을 전량(각 1행~EOF) 새로 읽고, 그 다음에 루트 초기본과 관측 기록(`stdout.txt` 15줄, `intent.json`, `receipt.json`, `source-check.json`, 빈 `stderr.txt`)을 읽었습니다. 아래는 그 결과입니다.

---

# 실제 토론 — 정정 수용/거부와 잔여 한계

## A. 수용하는 정정 (초기본 철회)

**A-1. 정렬 알고리즘 — 완전 철회.**
초기본에서 저는 온톨로지 엣지 순서를 "3단계 방출 순서이며 단계 순서를 바꾸면 sha256이 깨진다"고 추론했습니다. **틀렸습니다.** `ontology_query.py:72`는 `sorted(edges)`로 `(s, p, o)` 튜플을 **단일 전역 정렬**하고, 노드는 `sorted(nodes)`로 별도 정렬합니다(:71). 제가 본 3개 블록은 주어 접두사 사전순(`enum:` < `repo:` < `value:`)의 자연스러운 결과일 뿐입니다 — `participatesIn`은 전부 주어가 `enum:`, `declares`는 전부 `repo:`, `inSeam/driftsIn`은 전부 `value:`이므로 블록이 우연히 술어와 일치합니다. 따라서 제가 파생시킨 "취약한 방출 순서 의존" 경고는 **무효**이며, 실제 결정성은 제가 평가한 것보다 **강합니다**(파이썬 `str` 정렬은 코드포인트 기준이라 로케일·OS 독립).

**A-2. UTF-8 누락 우려 — 완전 철회.**
4개 CLI 모두 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`를 호출하고(`seam_scan:170`, `ontology_query:112`, `fleet_atlas:181`, `seam_gate:93`), 파일 쓰기도 전부 `encoding="utf-8"` 명시입니다(`fleet_atlas:194`, `seam_scan:139,141`, `seam_gate:112`). 초기본의 조건부 `UnicodeEncodeError` 위험 주장은 유지하지 않습니다.

**A-3. protobuf 배너 "다른 플릿에서 새어 나옴" — 추론 철회.**
`_extract_repo`(`seam_scan:64`)는 `iter_seam_extractors()`로 **등록된 3개 추출기를 모든 리포에 전부 실행**하므로 `ProtoSeamExtractor`가 실제로 돌고 `rglob("*.proto")`가 0건을 반환한 것입니다. 스캔되지 않은 것이 아닙니다. 초기본의 "하드코딩 유출" 인과 추론을 철회합니다.

**A-4. "재현 불가" — 문서 결함으로 축소.**
`ontology_query dump`가 존재하고(`:120–125`), 루트 관측 4행이 커밋 바이트와 `same_bytes: true`(sha `9f2ce280…`)를 측정했습니다. 저도 정적으로 `json.dumps(..., sort_keys=True)` 키 순서(`id,kind,type` / `kind,o,p,s`)가 커밋 파일과 일치함을 확인했습니다. **재생성 능력은 있고, README에 그 명령이 없는 것**이 결함입니다.

**A-5. "무단 원본 수정" 프레이밍 — 철회.**
`--out` 경로 쓰기는 정상 생성기 동작입니다. 루트 실행도 핀 소스를 쓰지 않았습니다(`source_bytes_unchanged: true`, 1,648파일).

**A-6. "DRIFT/BLOCKED 우선순위 판정 경로 미커버" — 철회.**
`evaluate`(`seam_gate:53–57`)는 `s["status"] in fail_on` **단순 멤버십 필터**이고, `scan`은 BLOCKED에서 조기 `continue`하여 한 심에 단일 상태만 부여합니다(`seam_scan:94–105`). 우선순위 정책 자체가 존재하지 않으므로 커버할 경로도 없습니다.

**A-7. 부재 픽스처 커버리지 "미검증" — 사실로 해소.**
grep 결과 `tests/test_context_cloud.py:41–42`가 `fleet.absent.yaml` / `seams.absent.spec.yaml`을 로드합니다. 선택 2개 테스트에 없다는 것을 저장소 전역 부재로 확대하지 않습니다. (해당 파일 본문은 판독하지 않았으므로 **참조 사실만** 주장하며, 단언 내용은 미검증입니다.)

## B. 유지하는 초기 소견 (루트도 동의)

**B-1. LIVE ≠ 관측된 트래픽.** `_shared_values` 독스트링(`fleet_atlas:62–63`)이 LIVE를 명시적으로 **non-BLOCKED**로 정의함을 확인했습니다. 정의는 수용합니다. 그러나 그 실질은 "선언되었고 파싱 가능하며 차단되지 않음"이며, 브로커·핸들러·엔트리포인트가 없는 이 픽스처에서 **동일 열거 문자열 멤버십이 곧 메시지 전달은 아닙니다.** FLEET-MAP의 독자 대면 어휘 "genuinely crosses ≥2 LIVE seams"는 여전히 코드 의미보다 강합니다.

추가로: LIVE는 OK가 아니므로 `ORDER_CREATED`가 지나는 3개 심 중 **2개(`order__inventory`, `order__payment`)는 그 자체가 DRIFT 상태**입니다. "온톨로지 활성화" 헤드라인은 값 수준에서 참이지만, 그 심들이 계약상 온전하다는 뜻은 아닙니다.

**B-2. 값 정체성 무범위 병합.** `nodes[f"value:{v}"]`(`ontology_query:64,67`)는 전역 문자열 키이며 계약/타입/채널 범위가 없습니다. 서비스 간 공유 Java 타입이 없는 것 자체는 정상이라는 루트 지적을 수용하되, **JOIN의 유일한 근거가 문자열 동일성**이라는 사실은 유지합니다.

**B-3. 방향성 소실.** `producer_only`와 `consumer_only`가 **동일한 `driftsIn` 술어로 합쳐집니다**(`ontology_query:66–68`). `participatesIn`에도 역할이 없습니다. 그래프만으로는 방향·역할을 복원할 수 없습니다.

**B-4. 선언과 관측의 구분 부재 — 가장 강한 소견(강화됨).** `build_graph`는 BLOCKED 검사(`:61`)보다 **먼저** `declares`/`participatesIn` 엣지를 생성합니다(`:55–60`). 루트 관측 9행이 이를 실측합니다: 부재 픽스처 그래프에 `repo:ghost --declares--> enum:ghost.OrderInbound`가 존재하며, **추출로 확인된 적 없는 계약을 그래프가 단언**합니다. `seam_scan` 독스트링(:9)이 BLOCKED를 "D4 — never partial/fabricated"로 규정하는데, 그래프 계층은 그 원칙을 지키지 않습니다. 아틀라스 계층은 지킵니다(`present:false`, `absent_reason`, `blocked_seams`). 즉 **동일 원칙이 계층별로 불일치**합니다. 그래프에는 소스 리비전·입력 다이제스트·fidelity·상태가 전혀 실리지 않습니다.

**B-5. cwd 결합 — 해소되어 확정.** `_extract_repo`는 `Path(path)`만 하고 YAML 위치로 해석하지 않습니다(`seam_scan:60`). 루트 관측 8행이 `/tmp`에서 절대 YAML 경로로 **6개 전부 BLOCKED**임을 실측했습니다. 반면 테스트 `_load`는 `str(_SCRIPTS / r["path"])`로 절대화합니다(`test_example_fleet:36`). **결과적으로 회귀 테스트가 이 취약점을 구조적으로 우회하므로 CI에서 절대 드러나지 않습니다.** README의 `cd` 지시는 자기 예제에 한해 유효합니다.

**B-6. 배너/deferred 이중 표현.** `scan`은 `coverage_scope`(스펙 유래)와 `coverage_banner`(상수)를 모두 반환하는데(`:125–127`), `render_md:121`은 **배너만** 출력합니다. 그래서 "ErrorType/REST NOT audited"와 빈 "honest coverage" 섹션이 공존합니다. 루트의 "선택/발견/미지원 측정 커버리지 부재" 지적을 수용합니다 — 실제로 "13개 .java 스캔, 0개 .proto 발견" 같은 측정치가 어디에도 없습니다.

**B-7. `stock__notification`.** 루트 지적대로 이 ID를 파싱하는 구현을 찾지 못했습니다. **불투명 선언 ID**로 격하하고, ID→리포 역추론은 미래 설계 주의사항으로만 남깁니다.

**B-8. README 비배포 방어 유지.** `README:8`의 명시적 선언과 `:41–52`의 의도적 드리프트 사전 선언은 유지합니다. 4건의 producer-only는 **테스트 입력 설계**이며 프로덕션 결함 4건이 아닙니다. 열거 이름에서 환불/취소/재고 안전성을 유도하지 않습니다.

## C. 부분 이견 (루트 표현의 정밀화)

**C-1. 배너의 출처.** 루트는 "등록된 추출기 능력 집합에서 온다"고 했으나, `COVERAGE_BANNER`는 `seam_scan.py:40–41`의 **모듈 수준 리터럴 상수**입니다. `_SEAM_REGISTRY`로부터 계산되지 않습니다. 현재 값이 등록 집합과 일치하는 것은 사실이나 **동기화가 수동**이며, 4번째 추출기를 추가해도 배너는 갱신되지 않습니다. 이것이 실제 유지보수 결함입니다.

**C-2. `--out` 쓰기.** 일반론은 수용합니다. 다만 축소된 주장은 유지합니다: README `:62`는 `--title`을 전달하지 않고, 루트 관측 5·6행이 **기본 제목은 `f359addc…`로 커밋본 `ceaf7cf0…`와 다르다**고 실측했습니다. 즉 **문서화된 명령을 그대로 실행하면 핀된 추적 아티팩트를 다른 바이트로 덮어씁니다.** 이는 생성기 결함이 아니라 README 결함이며, 그대로 유지합니다.

**C-3. 게이트 관대함의 등급.** "권한 우회가 아니라 설정 검증·커버리지 정책 범위"라는 프레이밍을 **수용**합니다 — 여기에 인가 경계 자체가 없습니다. 기본값이 fail-closed(`_DEFAULT_FAIL_ON = ("DRIFT","BLOCKED")`, 관측 10행 exit 1)라는 방어도 명시적으로 유지합니다. 다만 **CI 정확성 결함**으로서의 심각도는 유지합니다: `--fail-on TYPO`가 `✅ PASS 6/6`, exit 0을 내는데(관측 12행), 독스트링 `:19`는 "2 = bad args"라는 **정확히 이 경우에 맞는 종료 코드를 문서화해 놓고 그 경로가 도달 불가능**합니다. 미지 상태 문자열은 exit 2여야 합니다.

## D. 신규 소견 (16개 판독에서 새로 나옴)

1. **줄바꿈 — OS 바이트 분기 (구체적 기전).** `fleet_atlas:194`의 `Path(args.out).write_text(md, encoding="utf-8")`와 `seam_scan:139,141`은 모두 `newline=""`를 지정하지 않습니다. 기본 `newline=None`은 범용 줄바꿈 변환이므로 **Windows에서는 `\n`이 `\r\n`으로 기록**됩니다. `dump`의 stdout도 마찬가지입니다(`reconfigure(encoding=...)`는 줄바꿈 변환을 끄지 않음). 따라서 루트의 바이트 동일성 측정은 **리눅스 컨테이너에 한정**되며, Windows 네이티브에서는 동일 입력·동일 정렬에도 **아티팩트 바이트가 달라집니다.** 루트의 "플랫폼 줄바꿈 동작 잔존" 서술에 동의하며, 기전을 위와 같이 특정합니다.

2. **경계 절단의 순서 의존.** `find_java_sources`(`extractors/base.py:70–80`)는 `max_files=500` 도달 시 **정렬 전에** `break`합니다. `find_dart_sources`(2000), `find_proto_sources`(500)도 동일합니다. 즉 500개를 넘는 리포에서는 **어느 500개가 선택되는지가 파일시스템 순회 순서에 좌우**되어 OS 간 결정성이 깨집니다. 이 픽스처(13파일)에서는 발동하지 않지만, 실제 플릿에 적용할 때의 실질 위험입니다.

3. **`_ok`의 pytest 무효화 (귀결).** 루트의 사실 서술을 수용하고 귀결을 명시합니다: `_ok`는 조건이 거짓이어도 예외를 던지지 않으므로(`test_example_fleet:26–29`), 파일명·함수명이 pytest 수집 규약을 따름에도 **pytest로 수집하면 모든 단언이 거짓이어도 2 passed로 보고**됩니다. 실패는 오직 `main()`을 직접 실행할 때만 종료 코드로 드러납니다. `_FAILS`가 모듈 전역이라 반복 호출 시 누적되는 문제도 확인했습니다. 루트 관측 1행의 2/2 통과는 **직접 실행 경로**(`argv`에 `-m pytest` 없음)이므로 유효합니다.

4. **`passed_count` 과대 보고.** `passed = [... if s["status"] not in fail_on]`(`seam_gate:58`)은 BLOCKED·LOW_FIDELITY·NEEDS_TRANSFORM을 **"통과"로 집계**합니다. 관측 11행이 실증합니다: BLOCKED 1건이 있는데 `passed_count: 2, total: 2`. "declared seams passing: 2/2"는 검증 정도를 과대 표현합니다.

5. **README가 위험한 좁힘을 가르침.** `README:63`이 `--fail-on DRIFT`를 지시하는데, 이는 정확히 **BLOCKED 보호를 제거하는 좁힘**입니다. 예제 플릿에는 BLOCKED가 없어 무해하지만, 복사되는 패턴으로는 관측 11행의 상황(BLOCKED가 조용히 통과)을 그대로 만듭니다. 문서와 게이트 관대함을 잇는 고리입니다.

6. **주석 제거로 인한 provenance 행번호 이동.** `_BLOCK_COMMENT_RE`가 `re.DOTALL`로 `/* */`를 **개행 포함 삭제**합니다(`extractors/base.py:55,59`). 여러 줄 javadoc이 있는 파일에서는 이후 `WireValue.line`이 어긋납니다. 이 픽스처는 javadoc이 전부 한 줄이라 발동하지 않고, `base.py:10–11`이 `line`을 "PROVENANCE only — never the parity key"로 규정하므로 **parity/상태에는 영향 없음**입니다. provenance 정확도에 한정된 결함입니다.

7. **`_MEMBER_RE` 오탐 형태.** `^[ \t]*([A-Z][A-Z0-9_]{2,})\s*(?:\(...\))?\s*[,;]`(`java_socket.py:39`)는 열거 상수가 아닌 줄머리 대문자 식별자 뒤에 `;`가 오는 형태도 포착할 수 있습니다. 이 픽스처에서는 발동하지 않습니다. 반대로 마커 인터페이스 4개가 제외되는 기전은 확인했습니다 — `_IMPL_SOCKETACTION_RE`가 `implements` 키워드를 요구하는데 인터페이스 정의에는 없기 때문입니다(초기본의 관찰이 기전으로 확정).

8. **부재 리포에도 계약이 귀속됨.** `_node_contracts`(`fleet_atlas:41–44`)는 심 선언에서 계약명을 모으므로, 관측 9행에서 `ghost`가 `contracts: ["OrderInbound"], present: false`로 나옵니다. 아틀라스는 `present:false`로 **완화**하므로 B-4의 그래프 문제와 달리 오도 위험이 낮습니다.

9. **이중 스캔.** `seam_gate` 비-JSON 경로는 `scan()`(`:100`) 후 `build_fleet_atlas()`(`:106`)가 다시 `scan()`을 호출합니다. 결정과 표시 지도가 **하나의 불변 판독을 공유하지 않습니다.** 실질 위험은 낮으나(파일시스템 불변 가정) 전체 파싱이 2회입니다.

10. **`fleet_atlas` 독스트링 모순.** `:16–17`의 "no extractor runs"는 `build_fleet_atlas → scan → iter_seam_extractors`와 정면 충돌합니다. 루트 지적을 확인·수용합니다.

## E. 잔여 시험 및 채택 한계

측정된 것: 원본 2/2 통과, 4 DRIFT + 2 OK, 26노드/36엣지, ontology 바이트 동일, 명시 제목 아틀라스 바이트 동일·기본 제목 불일치, 게이트 4종 종료 코드, `/tmp` 6 BLOCKED, 빈 선언 0/0 통과. 모두 **`--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, 65534, 256m/1cpu, 60초 타임아웃**의 리눅스 컨테이너 1회분이며, 소스는 변경되지 않았습니다(1,648파일).

미해결로 남는 것:

- **Windows 네이티브 / WSL 미실행** — D-1(줄바꿈)과 D-2(절단 순서)는 **정적 추론이며 실측되지 않았습니다.** OS 간 바이트 동일성은 증명되지 않았습니다.
- **Java 컴파일러 부재** — 13개 `.java`가 실제로 컴파일되는지 확인되지 않았습니다(관측 14행). 정규식 추출은 컴파일 가능성을 함의하지 않습니다.
- **서비스 실행·E2E·인수 시나리오 없음**(관측 15행). 사가 인과, 전달 보장, 호환 방향, 취소/환불 거동은 어느 것도 시험되지 않았습니다.
- **미판독**: `tests/test_context_cloud.py` 본문, `lib/extractors/` 구체 모듈 9종, 나머지 CLI. 이들에 관한 주장은 하지 않습니다.
- **권고되나 미수행인 시험**: (i) `--fail-on TYPO`에 대한 exit 2 회귀, (ii) `dump`/`render_md --title` 바이트 비교를 회귀 테스트에 편입, (iii) `_load`의 절대화를 제거한 cwd 상대 경로 회귀, (iv) `_ok` → 실제 `assert` 전환 후 pytest 수집 검증, (v) BLOCKED와 DRIFT가 공존하는 픽스처에서의 요약 렌더링.

전체 소스 종결, 실서비스·모델·OS·재무 인수, 라이선스, 인적 SDD 수용, 채택 가부에 대해서는 **결론을 내리지 않습니다.** 초기본과 루트 보고 모두 갱신 가능한 증거로 취급하며, 위 A절은 제 초기 판단의 명시적 정정입니다.