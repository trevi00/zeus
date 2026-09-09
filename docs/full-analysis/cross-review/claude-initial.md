# 로컬 경험 흡수 설계 — 독립 검토 소견

검토는 읽기 전용으로만 수행했습니다. 쓰기·셸·실행 없음, 자격증명/설정/활선 상태 접근 없음.

---

## 0. 근거와 범위의 한계

- 소스 고정: `baldrix` rev `cbb5c3e6…`, `guardian` rev `e7ced4a6…` (`sources/*/manifest.json`).
- **인벤토리의 모든 `disposition`이 `"unreviewed"`이고 `semantic_review_complete: false`, `tests_executed: false`** (`sources/guardian/manifest.json:4-121, 208-209`).
- `observed/*`는 `"basis": "observed_local_bytes_not_commit"` (`guardian/manifest.json:127`) — 커밋 결속 증거가 아닙니다(`docs/research-standard.md:8-11`).

따라서 이 문서는 **지정된 부분 범위의 컴포넌트 소견**이며 저장소 완결 라벨을 상속할 수 없습니다(`AGENTS.md:16-17`, `docs/research-standard.md:28-30`). 승인이 아니라 승인 기록의 입력입니다.

---

## 1. 제안 설계 항목별 판정

### 1-1. 내용주소 경험 코퍼스(두 판 명시) — **채택**, 단 새 저장소를 짓지 말 것

Zeus에 이미 내용주소 저장소가 있습니다: `adapters/artifacts.py:13` `FileArtifacts`, `_put`(:24-41, sha256 키), `_body`(:43-48, 읽을 때마다 해시 재검증). 별도 CAS를 만들면 정본이 둘이 됩니다.

pinned/observed 두 판은 manifest의 `basis` 필드를 그대로 보존해 origin으로 실으십시오.

### 1-2. 툼스톤 우선 → **중대한 결함 있음. 이대로 구현하면 안 됩니다**

세 가지가 겹칩니다.

**(a) 회수는 내용이 아니라 원본 id를 지칭합니다.**
`baldrix .../lib/insight_index.py:408-436` `retract()`는 `{"retracted_id": ...}`를 씁니다. 그 id는 `_gen_id`(:224-236)가 만든 `<event_type>-<ts>-<6hex>`입니다. 코퍼스를 내용주소로 재키잉하면 관측된 툼스톤 16건(`baldrix/observed/memory/insight-index-retractions.jsonl`)이 전부 고아가 됩니다.

**(b) 오염 레코드는 `id`와 `body_ref`만 다릅니다 — 다대일 붕괴.**
실측(`baldrix/observed/memory/insight-index.jsonl:136,139,140,141`): 네 레코드의 `summary`·`correlation_id`·`axis`·`tags`가 완전히 같고 `id`와 죽은 Temp 경로 `body_ref`만 다릅니다.
- content_key가 `id`를 **제외**하면 → 여러 건이 1건으로 붕괴, 툼스톤 16개가 1건을 가리킵니다.
- content_key가 `id`를 **포함**하면 → dedup이 아무것도 못 합니다.

"툼스톤 먼저, 그다음 dedup"만으로는 어느 쪽도 풀리지 않습니다.

**권고: 키를 둘로 나누십시오.** `identity_key`(원본 id 보존) — 툼스톤이 지칭하는 축. `content_key`(id·body_ref 제외 정규화) — dedup 축. 그리고 `identity_key → content_key` 매핑을 유입 시점에 봉인하십시오.

**(c) 툼스톤 집합이 불완전합니다.**
`insight-index.jsonl:138` `skill_candidate-1700000099000-e915a4`는 같은 테스트 오염(`correlation_id: "dddd…"`, Temp `body_ref`)인데 회수 목록에 **없습니다**. 회수 여부를 신뢰 신호로 쓰면 안 됩니다. 별도의 결정론 오염 판정이 필요합니다 — 고정 픽스처 타임스탬프(`ts_unix_ms == 1700000000000`), `body_ref`의 `AppData\Local\Temp` 접두.

### 1-3. 충돌 fail-closed — **채택**, 단 키를 틀리면 전량이 충돌합니다

Zeus 관례와 정합합니다: `application/service.py:46` `"Message ID reused with different content"`, `:51` `"Occurrence ID reused with different content"`, `adapters/artifacts.py:29` `"Artifact integrity failure"`.

**함정**: pinned와 observed가 같은 `path`에서 다른 바이트인 것은 충돌이 아니라 **정의상 정상**입니다. guardian 12개 파일의 sha256이 pinned/observed 사이에서 전부 다릅니다(`guardian/manifest.json` inventory vs observed 블록). 충돌 판정 키는 반드시 `(source, origin, path)`여야 합니다. `path`만으로 걸면 12/12가 충돌로 뜹니다.

### 1-4. 자문 검색을 설계/구현에만 — **방향은 옳으나 현행 코드가 정반대이고, 게이트 축을 고르는 데 함정이 있습니다**

`adapters/executor.py:114-127`의 `self.knowledge.hybrid_query` 주입은 **역할 무관 전역**입니다. `_run`(`:85-87`)은 판정 경로에서도 그대로 불립니다:
- `:509` — `review_lead` / `review_conductor` / `diagnose`
- `:497` — `audit_review`
- `:503` — `threshold_review`

**게이트를 `workload`로 잡으면 안 됩니다.** `:516`이 `workload="design" if phase == "diagnose" else "final_validation"` 입니다 — **`diagnose`가 "design"으로 분류돼 있습니다.**

그런데 `diagnose`는 `root_cause`/`scope`를 확정하고, 그것이 `domain/model.py:120-123` `Incident.fingerprint`가 되어 INV-RECURRENCE-001 재발 판정을 좌우합니다. 과거 경험을 여기에 주입하면 `:511-513`의 프롬프트가 이미 금지한 *"generic error similarity로 알려진 cause ID 재사용"* 을 검색이 조장합니다.

**권고**: `_run` 시그니처(`:85-87`)에 `corpus: bool = False`를 추가하고, phase/agent 화이트리스트로만 True. 기본은 닫힘.

### 1-5. 결정론적 한/영 단기 검색 — **`recall.py` 이식은 기각합니다. 상류가 이미 자기 손으로 기각했습니다**

`harness/pinned/scripts/engine/recall.py:9-10, 41`은 `tokenize='trigram'`을 쓰며 "한국어(CJK)는 부분문자열 매칭으로 검색된다 — 실측 검증 완료"라고 적습니다.

같은 저장소의 `tests/integration/test_recall_retrieval_canary.py:13-19`가 그 주장을 **실측으로 반박합니다**:
> 현행 팔(FTS5 trigram)은 2음절 한글 질의를 원리상 못 맞힌다 … 한글 낱말 출현 130,241 중 76,658(58.9%)이 2자이고 상위가 정확히 핵심 어휘다 — 확정·기각·원장·판정·검증·실측·정본·승격.

그리고 `:275-284`가 `unicode61 + prefix`만이 2자를 회복하며 3자 회귀가 없음을 단언합니다.

**Zeus에는 더 나은 것이 이미 있습니다**: `adapters/knowledge.py:226-241` `query()`의 `body ILIKE %텍스트%`는 부분문자열이라 2자 한글에 강하고, 이는 상류 카나리아가 쓴 정답 라벨 정의(`test_recall_retrieval_canary.py:151-153`, "부분문자열 포함 = 토크나이저와 무관한 바닥 진실")와 같은 성질입니다. SQLite FTS5를 새로 들일 근거가 없습니다.

**흡수할 것은 백엔드가 아니라 그 카나리아(자) 자체입니다** — 2자/3자로 가른 recall@k, 무작위 대조군(`:138-148`), 양방향 회귀 축(`:282-284`), 결정론 단언(`:287-288`).

**결정론 주장의 미검증 전제**: `hybrid_query`는 RRF 뒤 `sorted(..., key=(-score, id))`(`knowledge.py:214, 224`)로 타이브레이크가 있어 순서는 결정론입니다. 그러나 `LocalEmbeddings`(`executor.py:116`)의 결정론은 이 범위에서 확인하지 못했습니다. "결정론"이라 부르려면 어휘 경로(`query()`)만 쓰거나 embedder 결정론을 따로 증명해야 합니다.

### 1-6. 경계된 컨텍스트/ref 핸들 — **필수. 그리고 이름 하나가 채택 게이트를 통째로 막습니다**

`docs/research-standard.md:85-88`: `*_ref`/`*_refs`는 완전한 artifact 핸들이어야 하고, **없거나 손상된 선언 자식은 채택을 차단**합니다.

baldrix 레코드의 `body_ref`는 이름이 `_ref`로 끝나지만 죽은 로컬 경로입니다:
`insight-index.jsonl:136` → `"body_ref": "C:\\Users\\rudtn\\AppData\\Local\\Temp\\scd-pr-b-cmbyo0a6\\reflection_001_….md"`

그대로 실으면 Zeus 채택 게이트가 코퍼스 전량을 차단합니다.

**권고**: `body_ref`를 그 이름으로 옮기지 마십시오. `source_body_path`(불활성 문자열 데이터)로 강등하고, Zeus artifact 핸들은 코퍼스 레코드 자체에 대해 새로 발급하십시오.

**예산**: `FileArtifacts.text/read`(`artifacts.py:56-65`)가 이미 상한을 강제합니다. 다만 `executor.py:200`의 `compile_context(..., 28000, 6000)` 예산에 코퍼스 항목이 들어가면 skill/knowledge 항목을 밀어냅니다. `:201-206`은 `"Skill counts increased context size"`만 보고 총량 밀어냄은 보지 않습니다. 코퍼스 항목에 별도 상한과 `ContextItem.priority`(`domain/model.py:132`)를 명시하십시오.

### 1-7. 정책/승인/자격 자동 이전 금지 — **동의하며, 아래 2-1 때문에 필수입니다**

---

## 2. 모순

### 2-1. trust / lifecycle / pinned / 회수 — **상류의 관측 데이터가 상류의 설계를 반증합니다. 가장 중요한 발견입니다**

**설계 주장**: `harness/pinned/scripts/engine/curator.py:112-131` — trust `proposed→confirmed` 승급 근거는 "재확인 실적(occurrences≥2) + bake 경과"이고, 근거는 *"원장 게이트 PASS 재실적 = O-47의 게이트 PASS 검증 이벤트 경로, 자기보고 아님"*(`:114-116`).

**관측 사실**: `harness/observed/knowledge/lessons/repair-cp949-unicodeencodeerror-629cb3e3.md`
- `occurrences: 308`, `trust: confirmed`
- `evidence:` `ledger:PASS x1` … `ledger:PASS x45`, `repair-notes:harness`

그 evidence 토큰을 만드는 곳은 `curator.py:271-272` `f"ledger:PASS x{passes}"`이고, `passes`는 `:257-258`에서 **원장 전체 PASS 누계**입니다. 같은 repair-notes 엔트리를 다시 수확할 때마다 새 문자열이 하나 늘어납니다.

**따라서 `occurrences: 308`은 "같은 실패가 308회 독립 재발"이 아니라 "curator harvest 사이클이 308번 돌았다"입니다. 동일 재시도와 독립 재발이 구분되지 않습니다.**

파급 두 가지:
1. `trust: confirmed`가 무의미해집니다 — bake(86400s)만 지나면 harvest가 두 번 돌아 승급합니다.
2. 재진술 탐지가 붕괴했습니다. `curator.py:147` `_ov.restatement_of`가 evidence 자카드를 쓰는데 공유 토큰이 전역 카운터입니다. 실측: `repair-9-seam-shim-health-tamper-b402696f.md:36-41` → `jaccard: 1.0`, `shared: [ledger:PASS x25, repair-notes:harness]`. 내용이 전혀 다른 두 교훈이 **완전 재진술**로 표시됐습니다.

**Zeus 규율이 상류보다 엄격합니다.** `application/service.py:53-59`가 정확히 이 문제를 옳게 풉니다 — `independent_occurrence`(기본값 `occurrence_id`)로 재시도와 독립 발생을 분리하고, `executor.py:564`가 `data.get("source_task_id")`를 그 권위로 넘깁니다.

**권고**: 상류의 `occurrences`/`trust`/`evidence`를 이식하지 마십시오. 재계산 가능한 것만 Zeus의 `independent_occurrence` 규약으로 재계산하고, 불가능한 과거 레코드는 `upstream_occurrences_unverified`로 강등해 라벨이 아니라 데이터로 남기십시오.

### 2-2. 진행 vs 하트비트 — **상류가 옳고, Zeus에 축이 하나 없습니다**

상류는 두 축을 명시 분리합니다(`guardian/observed/watchdog.py:6-8`): liveness(하트비트 부재/정체, `:196-202`)와 material progress(원장 무전진, `:254-259`). 자기 오탐 이력까지 코드에 박아 뒀습니다 — `:188-196`(수리 5·6차: "세션이 살아 있으면 정체는 정상"), `:241-247`(수리 8·9차: "드라이버가 `continue`라 판정했을 때만 정체").

Zeus:
- `adapters/executor.py:218-222` `observe()`의 heartbeat는 **타이머**입니다(20초마다 무조건).
- `application/workflow.py:122-127` `heartbeat()`는 `lease_until`만 연장합니다.
- 실질 진행 신호인 `execution_progress`(`executor.py:225-246`의 `last_completed`)는 기록만 되고 **정체 판정에 아무도 쓰지 않습니다**. 소비처는 복구 경로(`executor.py:183`)뿐입니다.
- `supervisor.py:161-165`는 `lease_until`만 보고 `busy=True`로 읽습니다.

**결과**: 진행 없이 이벤트만 도는 턴이 `POLICY.task_seconds`(900)까지 리스를 계속 연장하고 아무도 못 봅니다.

**구현 후보**: `execution_progress.last_completed` 무변화 연속 횟수를 별도 축으로. 상류 규율 그대로 (a) 활성 리스 중에는 발화 유예, (b) 상위 신호가 "일이 있다"일 때만 정체로 계수. **자동 복구는 붙이지 마십시오**(2-3 참조).

### 2-3. 경계된 수리 — **상류 스스로 좁혔고, 주석과 코드가 아직 어긋나 있습니다**

`guardian/observed/watchdog.py:286-296`: 사용자 승인(2026-08-16) 이후 자동 복원은 **자산 손상 증거(seal TAMPER) 전용**입니다 — `:293` `corruption_signal = any(m.startswith("seal:") for m in fired)`. 실증 사유가 `:289-291`에 있습니다: *"사망 발화 복원이 멀쩡한 작업 트리를 2회 역행시킴"*.

**상류 내부 모순**: 바로 위 `:288-289` 주석은 여전히 *"복원은 무전진(progress …)·봉인 파손"* 이라고 적혀 있는데 코드는 seal만 봅니다. 흡수 시 **코드(seal 전용)를 정본으로** 삼으십시오.

Zeus 대응물이 이미 더 보수적입니다: `adapters/deployment.py:281-298` `_probe_status` — 관측 불능(`observation_error`)은 실패로 세지 않고(`:284-288`, INV-RECOVERY-001), 임계 도달 시에도 **이전 배포로 롤백**할 뿐 작업 트리를 되돌리지 않습니다. 사건 종료 시 카운터 리셋(`:287` `0 if check["passed"]`)도 이미 있어 `watchdog.py:316-319`와 동등합니다.

**판정**: guardian의 restorer/watchdog 복원 체인은 **기각**. 특히 `restorer.py:280-289`(known-good 이후 추가된 tracked 파일 `unlink`)는 Zeus에 대응물이 없고 만들 이유도 없습니다. 흡수할 것은 규율 한 줄뿐입니다 — *"관측 대상 ≠ 복원 대상"*, 그리고 그것은 이미 Zeus에 있으므로 문서화만 하면 됩니다.

### 2-4. Unicode — **두 상류가 정반대 결론이고, guardian 쪽이 맞습니다**

- harness: 테스트가 `lib.hook_protocol.utf8_streams()`를 부르고 러너가 자식에 `PYTHONIOENCODING=utf-8`을 실어 줍니다(`test_curator_smoke.py:343-349`, `test_recall_smoke.py:95-101`).
- guardian: `issue_token.py:105-154` `_utf8_streams()`는 **인코딩을 바꾸지 않고 `errors`만 `replace`로** 바꿉니다(`:150-154`). A/B 실측이 `:136-148`에 있습니다:

| | 결과 |
|---|---|
| 무보호 | CRASH (UnicodeEncodeError) |
| `encoding=utf-8, errors=replace` | `[token] 諛쒓툒 …` ← 한글 전부 깨짐 |
| `errors=replace` 만 | `[token] 발급 ? 72.0h 유효` ← 읽힌다 |

cp949는 한글을 담습니다. 못 담는 것은 em-dash 하나입니다. `console.py:619-644`가 같은 결론을 독립으로 재확인합니다.

또한 guardian은 harness의 `utf8_streams`를 **의도적으로 import하지 않습니다**(`issue_token.py:130-134`) — 격리가 존재 이유이므로 정본 두 벌을 의도적 비용으로 치릅니다.

실물 사고 근거: `harness/observed/.../repair-cp949-unicodeencodeerror-629cb3e3.md:47` — *"붉은 65건의 서명이 전부 동일: `UnicodeEncodeError: 'cp949' codec can't encode character '—'`"*.

**Zeus 적용**: 사람이 직접 치는 CLI stdout(`cli.py`의 `emit`)이 한국어 Windows 콘솔에서 죽는지는 이 범위에서 확인하지 못했습니다 — 미검증으로 남깁니다(§5-2).

### 2-5. guardian 내부의 방향 불일치 (요청 축 밖이나 흡수 판단에 필요)

`watchdog.py` `_l2_session_alive`: lease 파일 부재/손상은 "세션 없음"(`:74-75`, 발화 방향), `tasklist` 판별 불능은 "생존"(`:80-82`, 발화 억제 방향). 같은 함수가 두 실패에 **반대 방향으로 접힙니다**. Zeus로 옮길 때는 Inconclusive를 한 방향으로 고정하십시오 — `deployment.py:284`의 명시 3태(`unknown`)가 더 낫습니다.

### 2-6. observed 델타(롤링 해시 체인)는 **미검증입니다**

`guardian/observed/watchdog.py:351-411`이 pinned(`:336-359`)에 없던 rolling hash chain을 추가했습니다 — 잘림(`:377`)·교체(`:379-383`) 탐지, 감지 시 워터마크 0 복귀 + 재릴레이(`:384-391`). 근거도 정직합니다(`:363-369`: 같은 OS 계정으로 도니 경계가 아니라 방어심층).

그런데 `guardian/observed/tests/test_notify_relay_smoke.py`는 워터마크 무중복(`:45-46`)과 증분(`:52-53`)만 잽니다. **체인 축에 단언이 하나도 없습니다** — writer만 있고 reader가 없는 상태이고, 이는 상류 자신이 `restorer.py:196-203`에서 이름 붙인 결함 형태와 같습니다.

**판정**: 아이디어는 유효하나 Zeus에 동등 이상이 있습니다 — `service.py:44-49`의 `message_id` 멱등 + `digest(message)` 재확인, `artifacts.py:47`의 sha256 재검증. **기각**.

### 2-7. console 표면 — **기각**

`guardian/observed/console.py:518-537` `do_GET`은 인증 없이 페이지를 주고 `:521`이 그 페이지에 `__SECRET__`을 박아 넣습니다. 그런데 `:22` 독스트링 자신이 *"프로세스는 무엇이든 127.0.0.1을 두드릴 수 있고 하네스가 스폰한 세션도"* 라고 위협 모형을 적었습니다 — 그 위협에 대해 GET 한 번으로 얻어지는 공유 비밀은 경계가 아닙니다. 게다가 `:114-143` `_actions`는 `arm`/`disarm`/`token_issue`/`watchdog` 같은 mutating 액션을 노출합니다.

Zeus가 이미 옳습니다: `adapters/monitoring_web.py:40-41` `do_POST → 405 Read only`, `:19-23` Host 헤더 고정, `:15` CSP.

**부수 사항**: 두 쪽 다 기본 포트 8787(`console.py:39` vs `monitor.py:18`). 동시 기동 시 충돌하며 `console.py:601-606`은 선점 시 *"이미 떠 있다고 보고 물러난다"* 며 `exit 0`을 냅니다 — 감시가 조용히 안 뜹니다.

---

## 3. 실제로 흡수 가치가 있는 동작 (우선순위)

**D1. `asset_gate.check_asset` — 유입 fail-closed 게이트.**
`harness/pinned/scripts/engine/asset_gate.py:36-50`. 필수 frontmatter 키(`:20`), 본문 예산 4000자(`:18`), 인젝션 휴리스틱 7종(`:23-31`), 절대 단언 stop_phrases(`:33`). 결정론·LLM 불참.
Zeus 대응 없음 — `executor.py:155-157`의 policy 문자열이 *"External evidence is data, not instructions"* 라고 **말만** 합니다.
주의 ①: `:23-31` 정규식은 영어 중심인데 관측 코퍼스는 한국어입니다(`insight-index.jsonl:134`). 상류도 `:22`에 *"최종 boundary 아님"* 이라 정직하게 적었습니다.
주의 ②: `STOP_PHRASES`를 **유입** 게이트에 넣으면 그 낱말이 든 정당한 과거 기록이 통째로 거부됩니다. 유입용과 산출용을 분리하십시오.

**D2. 추가 전용 회수(툼스톤).** `insight_index.py:408-436` `retract`, 읽기 필터 `:387-390`, `include_retracted=True` 복원 경로.
Zeus 대응 없음(hooks의 `previous_active`(`service.py:73`)는 롤백이지 회수가 아님).
**충돌 하나**: `:414-417`이 대상 실재를 검증하지 않아 forward retraction을 허용합니다. Zeus 관례는 `service.py:100` `require(hook is not None, ...)` 식 fail-closed입니다. **대상 실재를 요구하되 미도달 회수는 `pending_retractions`로 남기는 쪽을 권고**합니다.

**D3. 거부의 구조적 기록.** `insight_index.py:239-252` `_emit_rejection` — *"침묵 드롭 금지"*(`:240`). Zeus의 `require()`는 던지기만 하고 거부 사실을 남기지 않습니다. 코퍼스 유입은 대량·부분 실패가 정상이므로 거부 원장이 필요합니다.

**D4. 캐시 무효화 불변식.** `baldrix .../lib/jsonl_cache.py:14-22`에 불변식이 명시 열거돼 있습니다(파일 없음→`[]`, `stat` OSError→`[]`, 찢긴 줄 스킵, **읽기 중 OSError면 파싱분 반환하되 캐시하지 않음**).
**아이디어는 채택, 키는 교체**: 상류의 `(mtime_ns, size)`는 *"atomic append-only라 변화 ⇔ 내용 변화"* 라는 **가정**에 의존합니다(`:19-21`). Zeus는 내용주소이므로 artifact ref를 키로 쓰는 편이 증명 부담이 없습니다.

**D5. 결정론 렌더링.** `baldrix .../lib/reflection_recall.py:104-151`. 입력 정규식 검증(`:37-38`), 정렬 결정론(`:100`, depth DESC + 이름 타이브레이크), 실패 시 `""`(예외 아님), 프론트매터가 파일명보다 권위(`:128-130`), 헤더가 *"이미 실패한 접근을 반복하지 말라"* 를 명시(`:145-146`).
제안하신 "자문 검색"의 좋은 형태입니다 — 검색이 아니라 **렌더링의 결정론**. 다만 body 길이 상한이 없습니다. Zeus에서는 예산을 거십시오.

**D6. BOM/CRLF/선행 공백 관용 파싱.** `curator.py:41-49, 56-62`.
사고 서사가 `:42-48`에 있습니다: `^---\n`이 CRLF에서 실패 → `fm={}` → 병합이 원본 frontmatter를 본문으로 밀어냄 → `pinned` 소실. *"고정하는 행위가 다음 30분 사이클에 그 고정을 지우는 경로"*. Windows 편집기 기본 저장이 CRLF라서.
짝 규율도 같이: **읽기는 관용, 쓰기는 엄격**(`:41`), **판정 불능이면 덮어쓰지 않는다**(`:100-106` `if not fm: return "rejected"`).
Zeus 점검 대상: `adapters/skill_routing.py:23` `require(len(parts) == 2, 'Malformed skill frontmatter fence')`가 CRLF/BOM을 견디는지 확인 필요(§5-3).

**D7. 읽기 경로가 상태를 만들지 않는다.** `insight_index.py:171-186` — *"읽기 경로가 상태를 만들면 '없는 것'과 '빈 것'이 구분되지 않는다."* 규율로만 채택(코퍼스 조회 경로에 `mkdir` 금지).

**D8. 테스트를 재는 자 — 좋지만 이번 범위 밖.**
`restorer.py:36`(`_ASSERT_RE`), `:49-50`(`_LITERAL_TRUE_RE`), `:153-228`(앵커 래칫: 스위트 이름 집합 소실 / 단언 수 감소 / `check(..., True)` 증가 / 판정 경로 축소를 각각 거부). 자를 측정당하는 쪽이 못 건드리는 트리에 둔 이유가 `:160-163`에, 실증이 `:196-203`에 있습니다.
**이것은 데이터 흡수가 아니라 CI 정책 변경입니다. 별도 제안으로 분리하십시오.**

**D9. 사용자 자산 불가침 / pinned 면제 — 유예.**
`curator.py:127-133, :297-298`. 논거가 좋습니다(`:124-126`): 병합을 통째로 스킵하면 고정한 자산에서만 재발 증거가 사라져 *"고정할수록 눈이 머는 역설"*. Zeus에는 사용자 소유 지식 개념 자체가 없으므로 지금은 불필요. 스키마에 `created_by`/`pinned` 자리만 비워 두십시오.

---

## 4. 독립 실행 가능한 상류 테스트

`docs/research-standard.md:78-82` — 실행한 테스트는 **정확한 argv 배열과 성공 실행 영수증**으로만 기록하고, 이름만 있는 것은 사유·후속과 함께 `tests_not_run`에 그대로 둡니다. 목록/읽기는 실행 증거가 아닙니다.

### 실행 가능(격리 성립)

| 테스트 | 격리 근거 | 주의 |
|---|---|---|
| `guardian/observed/tests/test_notify_relay_smoke.py` | 자체 `GUARDIAN_HOME`·`config.json` 생성(`:31-35`) | `watchdog.run()`이 `_probe_hook_chain`(`watchdog.py:99-125`)에서 없는 `guard_boot.py`로 **subprocess를 실제로 띄웁니다**(실패는 `:123-124`에서 잡힘). `webhook_url` 미설정이라 네트워크 없음(`notifier.py:25-27`) — 실행 전 재확인 |
| `guardian/observed/tests/test_watchdog_smoke.py` | 임시 `GUARDIAN_HOME`(`:41`, `:96`), 서브프로세스 실행(`:31`) | — |
| `guardian/observed/tests/test_recovery_smoke.py` | 임시 `GUARDIAN_HOME`(`:60-66`) | `:16` `GHOME_REAL = parents[1]` 사용처 확인 후 실행 |
| `baldrix/pinned/scripts/tests/test_jsonl_cache.py` | 순수 파일 IO | — |
| `baldrix/pinned/scripts/tests/test_reflection_recall.py` | 임시 `CLAUDE_HOME`(`:25-38`) | `lib.wonder.write_reflection`(`:45-47`) 스냅샷 실재 확인 필요 |
| `harness/pinned/tests/unit/test_recall_smoke.py` | 전부 tempdir(`:39-58`), db 주입(`:60`) | `_isolate.isolate()` 선행(`:8-10`) |
| `harness/pinned/tests/integration/test_recall_retrieval_canary.py` | 판정부는 고정 말뭉치(`:76-85`) 위 결정론 | `live_report()`(`:184-217`)가 **살아 있는 트리**(`:193-194`)를 읽습니다. 판정에 안 쓰이니 `:290` 호출을 빼고 돌리십시오 |

### 실행 불가 — `tests_not_run`

- **`guardian/observed/tests/test_restorer_smoke.py`** — `:250-252`가 라이브 `guardian/config.json`을 읽고 그 `harness_home` 아래 `scripts/lib/test_outcome.py`를 읽습니다. `config.json`은 흡수 인벤토리에 **없습니다**(`guardian/manifest.json`에 12경로뿐). 라이브 트리 접근이므로 금지 조건에 걸립니다.
- **롤링 해시 체인 축** — 상류에 테스트가 **존재하지 않습니다**(§2-6). "상류 미작성"으로 기록.
- **`harness/pinned/tests/integration/test_curator_smoke.py`** — `HARNESS_HOME`은 임시(`:50-52`)지만 원본 트리의 `config/paths.yaml`을 복사하고(`:51`), `engine.golden.gate()`(`curator.py:180-181`), `lib.params`·`lib.repro_probe`·`lib.overlap`·`lib.derive_state`·`lib.ledger`·`lib.ids`·`yaml` 의존이 걸립니다. 의존 실재 확인 전 not run.
- **`baldrix/.../test_insight_index.py`** — `_ALLOWED_WRITER_SOURCES`를 `scripts/tests/conftest.py`가 monkeypatch로 넓힌다고 소스가 적습니다(`insight_index.py:70`). conftest 실재 확인 필요.

---

## 5. 구현 후보 (파일:심볼)

### 새로 만들 것

1. `src/codex_harness/domain/experience.py` — 순수(표준 라이브러리만, `AGENTS.md:4`). 레코드 정규화, `identity_key`/`content_key` 산출, `check_admission(record) -> list[str]`(`asset_gate.check_asset` 이식 + 한국어 패턴 보강).
2. `src/codex_harness/application/experience.py` — `ingest(records)`, `retract(identity_key, reason)`, `lookup(query, *, limit, budget)`. **순서 고정: 툼스톤 로드 → 필터 → `content_key` dedup.** 충돌은 `(source, origin, path)` 키로 fail-closed.
3. `src/codex_harness/adapters/experience_import.py` — `.runtime/absorption/sources/*/manifest.json`을 읽어 pinned/observed를 각각 `FileArtifacts.put`으로 봉인, `origin`/`basis` 보존, `body_ref` → `source_body_path` 강등.
4. `src/codex_harness/resources/00X.sql` — `experience`, `experience_retractions`, `experience_rejections` 버킷.

### 기존을 고칠 것

5. `adapters/executor.py:114-127` — knowledge 주입을 역할 게이트 안으로. `_run`(`:85-87`)에 `corpus: bool = False` 추가. `:509`(리뷰/`diagnose`), `:497`(audit_review), `:503`(threshold_review)는 False 유지. **`workload` 축으로 게이트 금지**(`:516`이 `diagnose`를 `"design"`으로 부름).
6. `adapters/executor.py:106-127, 201-206` — 코퍼스 `ContextItem`에 별도 `priority`와 항목 수/바이트 상한, 그리고 그 상한 단언.
7. `domain/policy.py` — `experience_context_items`, `experience_item_bytes`, `experience_retention_days` 추가(런타임 한계는 policy에 산다 — `docs/research-standard.md:69`).
8. `docs/contracts.md` — 새 불변식. 초안:
   > **INV-EXPERIENCE-001** — 흡수된 경험은 출처(source, revision 또는 observed-basis, path)와 함께 내용주소로 봉인된다. 회수는 추가 전용이며 조회보다 먼저 적용된다. 상류의 trust/lifecycle/occurrences 라벨은 이전되지 않는다. 자문 검색은 설계·구현 실행에만 들어가고 진단·리뷰·판정 실행에는 들어가지 않는다.
9. `tests/` — `AGENTS.md:9`(재발 중복제거·오래된 쓰기·권한·컨텍스트 초과·승격 실패)에 맞춰: 툼스톤 고아, 다대일 붕괴, `(source, origin, path)` 충돌, 리뷰 경로 비주입, 예산 초과, `body_ref` 강등.

---

## 6. 명시적 기각

- `recall.py`의 SQLite FTS5 trigram 백엔드 — 상류 자신의 카나리아가 기각했고(`test_recall_retrieval_canary.py:13-19`) Zeus에 더 나은 것이 있습니다.
- `guardian/console.py`의 mutating 표면 전체(`:114-143`, `:518-537`).
- `guardian/restorer.py`의 자동 트리 복원 및 사후 추가 파일 삭제(`:274`, `:280-289`).
- 상류 `trust`/`occurrences`/`evidence` 라벨의 무변환 이전.
- watchdog 롤링 해시 체인(`observed/watchdog.py:351-411`) — Zeus에 동등 이상, 상류 미검증.
- 앵커 래칫(D8) — 유효하나 범위 밖. 별도 제안으로.

---

## 7. Codex가 코딩 전에 답해야 할 것

1. `adapters/embeddings.py`의 `LocalEmbeddings`가 결정론인가 — §1-5의 "결정론 검색" 전제.
2. `cli.py`의 `emit`이 한국어 Windows 콘솔에서 죽는가 — §2-4 적용 여부.
3. `adapters/skill_routing.py:23`의 frontmatter 파싱이 CRLF/BOM을 견디는가 — D6.
4. **코퍼스를 `knowledge_nodes`(pgvector)에 넣는가, 별도 버킷인가.** 전자면 `hybrid_query`(`knowledge.py:206-224`)가 자동으로 리뷰 경로에도 흘러 §1-4 게이트가 무력화됩니다. **별도 버킷 권고.**
5. 스냅샷의 의존 모듈 실재 — `lib.wonder`, `lib.paths`, `engine.golden`, `lib.params`, `lib.repro_probe`, `lib.overlap`, `scripts/tests/conftest.py`. §4의 실행 가능 목록이 여기 달려 있습니다.
6. `guardian/config.json` 부재(§4)가 영구 갭인지, 스냅샷 보강으로 해소할 것인지.
7. 라이선스/귀속 기록 — `docs/research-standard.md:36, :46`. 세 소스 모두 사용자 소유로 보이나 명시 기록이 필요합니다.

---

**종합 판정**: 제안하신 7개 항 중 5개(내용주소 코퍼스, 충돌 fail-closed, 리뷰 비주입, 경계된 핸들, 정책 비이전)는 방향이 옳으며 흡수를 권고합니다. **"툼스톤 먼저 → dedup"은 현재 형태로는 작동하지 않으므로**(§1-2) 이중 키로 재설계해야 하고, **"결정론 한/영 단기 검색"은 `recall.py` 이식이 아니라 Zeus의 기존 `query()` + 상류 카나리아 흡수로 다시 잡아야 합니다**(§1-5). 그리고 §2-1은 데이터 흡수 자체의 전제를 바꾸는 발견이니 구현 전에 반드시 논의합시다.