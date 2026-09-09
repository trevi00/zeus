## 판정 요약

38개 1차 파일 전량 + 직접 소비자(seam_scan / lib.seams 7모듈 / fleet_atlas / ontology_query / seam_gate) 전량을 정적으로 읽었습니다. **README.md:53-59의 예상 출력 6줄은 정적 재구성과 일치**하며, "ErrorType out_of_scope", "세 extractor 모두 발화", "54+26 테스트" 주장도 코드로 뒷받침됩니다. 다만 **생성 artifact 재생성 검증 부재**, **seam_gate 기본 정책과의 영구 충돌**, **"verbatim/identical" 문구의 사실 불일치**, **envelope 계약의 범위 공백**이 실질 발견입니다. 아래 모든 판단은 정적 재구성이며 실행 결과가 아닙니다.

---

## 검증된 방어

**V1 — 6개 seam 결과가 정적으로 재현됨.** `KdsServerAction`(4값) vs `KdsClientAction`(4값) 동일, `PosLinkClientAction`(4) vs `SocketClientAction`(4) 동일, `SocketServerAction`(7) vs `PosLinkServerAction`(5) → producer_only 2개(`UNION_POS_ORDER`/`YOGIYO_ORDER`, SocketServerAction.java:13-14), agent proto 1..8 vs poslink 1..10 → consumer_only 2개, syn-tran 1..10 vs poslink 1..10 동일, waiting 3 vs 3 동일. UNDECLARED는 `TranResult`(syn-tran/protos/tran.proto:32-35) 1건 — 나머지 계약은 전부 선언 쌍에 포함(seam_scan.py:113-122).

**V2 — "ErrorType은 범위 밖" 주장이 코드로 성립.** java_socket.py:57-61의 `_is_socket_action`이 `implements ... SocketAction` 또는 `SocketServiceType.` 참조를 요구 → SocketError.java:7(`implements ErrorType`), ErrorType.java:7, SocketAction.java:4(interface), SocketData.java 모두 미추출. Dart 쪽 socket_error.dart / waiting_error.dart는 `implements *Action`이 없고 파일명도 `*_action.dart`가 아니어서 dart_socket.py:103-110에서 배제. 각 repo의 `socket_action.dart`는 `*_action.dart`로 끝나지만 `enum` 키워드가 없어 bare 경로도 미발화.

**V3 — 배치가 extractor 탐색 규약과 정확히 맞음.** java는 `src/main/java` 필수(lib/extractors/base.py:70-74) → syn-poslink 경로 일치; dart는 `lib/` 필수(dart_socket.py:82-92); proto는 `rglob("*.proto")`(proto.py:46-56)라 `protos/` 하위도 탐지.

**V4 — 테스트 수 주장 정확.** README.md:9의 `test_extractors.py`(54) / `test_seams.py`(26)는 `^def test_` 카운트와 정확히 일치.

**V5 — 문서화된 명령이 read-only.** reverse_engineer.py:119의 `--write`는 opt-in이므로 README.md:62의 예시는 dry-run.

**V6 — 커밋된 artifact가 생성기 출력 형식과 일치.** ontology.jsonl의 키 순서(`id,kind,type` / `kind,o,p,s`)와 정렬(`value:10:...` < `value:1:tranId`)이 ontology_query.py:122-124의 `sort_keys=True` + `sorted()` 출력과 형식상 합치 → 수기 편집 흔적 없음. FLEET-MAP.md 헤더/표 구조도 fleet_atlas.py:119-168과 합치.

**V7 — 마커 3벌 중복은 의도적.** scope.json에서 syn-agent/syn-kds/syn-wating의 `socket_action.dart` 3개가 동일 sha256(`428584dd…`).

---

## 발견

### F1 (중) seam_gate 기본 정책과 fixture가 영구 충돌
seam_gate.py:43 `_DEFAULT_FAIL_ON = ("DRIFT", "BLOCKED")`인데, 이 fleet은 설계상 DRIFT 2건이 고정입니다(README.md:40-43, FLEET-MAP.md:22·24). 기본 인자로 seam_gate를 이 fleet에 걸면 항상 exit 1(seam_gate.py:114)이 되어, 게이트 데모 용도로는 그대로 쓸 수 없습니다. README "Run it"(48-63)은 seam_scan과 reverse_engineer만 안내하고 seam_gate는 언급하지 않아, 사용자가 스스로 `--fail-on`을 비워야 한다는 사실이 문서에 없습니다.

부수 결함: seam_gate.py:42 docstring은 "UNDECLARED는 기본적으로 advisory"라고 하지만, `evaluate()`는 `report["seams"]`만 순회하고(51-57) UNDECLARED는 `report["undeclared"]`에 있으므로 `--fail-on UNDECLARED`는 오류 없이 **무동작**입니다.

### F2 (중) 생성 artifact의 재생성 검증이 없음
pinned 트리 전체에서 `synthetic-fleet|fleet.syn.yaml|seams.syn.spec`를 참조하는 파일은 ontology_query.py, atlas/seam-registry/seams.spec.yaml, atlas/seam-registry/deploy/README.md 3개뿐이고 **tests/ 및 CI 참조는 0건**입니다. FLEET-MAP.md와 ontology.jsonl은 생성 artifact인데(V6) 소스 enum 한 줄만 바뀌어도 조용히 stale이 되며 이를 잡는 장치가 없습니다. fleet.syn.yaml:1과 README.md:16-19의 "CI-exercisable"은 "CI에서 돌릴 수 있는 형태"로는 성립하지만 "검증되고 있다"는 근거는 이 스코프 안에 없습니다.

### F3 (중) "verbatim / identical" 문구가 파일 사실과 불일치
syn-tran/README.md:3 "copied **verbatim** into poslink", README.md:26 "copied into ↓ (identical)", syn-poslink/protos/tran.proto:8 "IDENTICAL한 복사본"이라고 하지만, poslink 사본에는 canonical의 `TranResult`(syn-tran:32-35)와 `service TranService`(38-41)가 없고 package도 `syn.tran` → `kr.outlier.poslink.tran`으로 다르며 java 옵션 2줄이 추가되어 있습니다. 실제 동일성은 **TranDTO 10필드 한정**입니다.

더 중요한 것은 이 비대칭이 drift로 분류되지 않는다는 점입니다. proto.py:71-88이 message 단위로 계약을 만들고 seam은 선언된 message 쌍만 비교하므로, 응답 메시지 부재는 `syn-tran/TranResult` UNDECLARED(FLEET-MAP.md:57)로만 표면화됩니다. README.md:40-43의 "의도적 drift" 목록에 없는 세 번째 비대칭이며, 문서는 이를 drift가 아닌 advisory로 제시합니다. (fixture의 의도적 차이일 수 있으므로 운영 사고로 규정하지 않습니다.)

### F4 (중) envelope 계약이 in-scope도 out_of_scope도 아니고, 3 repo 3형태
- `errorCode` 타입: syn-agent/socket_data.dart:32 `String?`, syn-kds:38 `String?`, syn-wating:32 `int?`. 그런데 같은 repo의 코드 enum은 정수입니다(syn-agent/socket_error.dart:4-9의 910xxx, syn-wating/waiting_error.dart:4-9).
- `toJson`: syn-kds:58은 `if (errorCode != null)` 조건부 방출, syn-agent:52 / syn-wating:52는 null 포함 무조건 방출.
- `fromJson`의 data: syn-agent:17은 `(json['data'] as Map).cast<…>()`(누락 시 throw), syn-kds:23 / syn-wating:17은 `?? const {}`(관용).
- syn-poslink/socket/SocketData.java:9-13에는 응답용 `errorCode` 필드 자체가 없음.

seams.syn.spec.yaml:6-9의 out_of_scope는 ErrorType과 REST만 선언하고, coverage banner(seam_scan.py:40-41)도 enum + proto field 한정입니다. 즉 응답 봉투는 **어떤 seam으로도 잡히지 않고 "honest coverage" 절(FLEET-MAP.md:59-62)에도 공시되지 않는 공백**인데, README.md:44-45는 envelope을 "faithful idiom"으로 제시합니다. fixture 내부 불일치이지 운영 인시던트는 아닙니다.

### F5 (하~중) b2 트리거 서사가 QR_ORDER에 과도하게 귀속됨
README.md:38-39는 QR_ORDER를 b2 트리거의 근거로 제시하지만 실제 shared_values는 11개(FLEET-MAP.md:38-48)이고, `HEARTBEAT`는 4개 seam에 걸칩니다 — 4개 action enum 전부가 heartbeat 멤버를 갖기 때문입니다. QR_ORDER를 제거해도 트리거는 계속 발화합니다. 또한 proto 필드 1..8이 공유값이 되는 이유는 `syn-poslink.TranDTO`가 두 seam의 consumer이기 때문(seams.syn.spec.yaml:41-51)이라, "값이 두 seam을 가로지른다"기보다 동일 소비 노드의 중복 계상에 가깝습니다. 그리고 이 JOIN은 **선언된 fixture 그래프의 멤버십일 뿐 관측된 트래픽이 아닙니다**(ontology_query.py:43-73은 seam_scan 보고서만 소비).

### F6 (하) 그래프가 proto message를 "Enum"으로 표기
ontology.jsonl:4·9·10 등 4개 노드가 proto message인데 `type: "Enum"`입니다. ontology_query.py:58이 스택 구분 없이 `nodes[f"enum:{repo}.{enum}"] = "Enum"`으로 고정하고 docstring:20-21이 4타입 닫힌 스키마를 선언하기 때문입니다. 커밋된 그래프만 보면 proto message와 Dart/Java enum을 구분할 수 없습니다.

### F7 (하) 경로 해석이 프로세스 CWD에 결합
fleet.syn.yaml:11-15는 상대경로이고 seam_scan.py:59는 `root = Path(path)` — fleet 파일 위치가 아닌 **CWD 기준**입니다. scripts/ 밖에서 호출하면 6개 seam 전부 BLOCKED + exit 1이 됩니다(seam_scan.py:94-97, 194). README.md:48이 "from the scripts/ dir"로 안내하고 `python -m cli.*` 자체가 사실상 그 CWD를 요구하므로 자기일관적이지만, 인자/`--help` 레벨의 강제나 진단 메시지는 없습니다.

### F8 (하) 시연 폭의 한계 — 허위 주장은 아님
parity 4상태 중 OK/DRIFT 2개만, Java 3규칙 중 `name()`만(SocketServerAction.java:17-20 등), Dart 2규칙 중 `dart-string-arg`만, transform 3종 중 `identity`만(seams.syn.spec.yaml 6개 전부), BLOCKED 0건이 발화합니다. dart_socket.py:22-28이 실 fleet 형태라고 기술한 bare-member 규칙은 이 fixture에 재현되지 않습니다. 다만 test_seams.py에 해당 경로 문자열이 11회 등장해 단위 테스트 커버리지는 별도로 존재하므로, 이는 README.md:5-13의 NO-GO 자기고지와 모순되지 않는 **시연 폭 한계**로 봅니다.

---

## 읽은/읽지 않은 범위

- **전량 정독**: 38개 1차 파일 전부(root 5, syn-agent 11, syn-kds 5, syn-poslink 9, syn-tran 2, syn-wating 6). seam_scan.py, lib/seams/{`__init__`,base,parity,transform,dart_socket,java_socket,proto}.py, fleet_atlas.py, ontology_query.py, seam_gate.py.
- **부분만 읽음**: lib/extractors/base.py는 58-81행(4개 함수)만 — 나머지 미독. reverse_engineer.py는 10-14·117-125행만 — 파이프라인 본문 미독. tests/test_seams.py·test_extractors.py는 grep 카운트만, 본문 미독. atlas/seam-registry/seams.spec.yaml 및 deploy/README.md는 grep 히트만 확인, 미독.
- **조회하지 않음**: 인용된 debate 레코드(`debate-1782485457-64b83a`, `debate-1782448430-dd1648` 등), 실 회사 fleet 소스, 이전 리뷰 보고서.
- **실행 없음**: 파서/CLI를 돌리지 않았습니다. F1·F2·V1의 출력 주장은 전부 코드 경로 정적 재구성이며, 실제 실행 시 제가 읽지 않은 lib/extractors/base.py 나머지나 PyYAML 동작 차이로 달라질 수 있습니다. 필요하면 read-only·no-network 컨테이너에서 `seam_scan --no-write --json` / `seam_gate --json`로 F1과 V1을 유계 확인하는 것이 다음 단계로 적절합니다.

**주장하지 않은 것**: 저장소 전체의 무결점 여부, 라이선스/저작권, 실제 모델·OS·인간 SDD 수용 여부, 채택·운영 상태에 대한 어떤 결론도 내리지 않았습니다.