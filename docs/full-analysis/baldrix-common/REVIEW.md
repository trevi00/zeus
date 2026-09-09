# Baldrix common skills — bounded semantic review checkpoint

Source: trevi00/baldrix, revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`.
Inventory: `.runtime/absorption/sources/baldrix/manifest.json`.
Read source root: `.runtime/absorption/sources/baldrix/pinned/`.
Historical pre-migration HEAD observed: `0548efaf1bc8833c750c80b242de03b5a73d7799` (working source reads, not a clean-tree attestation).

This checkpoint contains **98 / 98 common files semantically reviewed; 0 bodies remain unreviewed**.
The full denominator is 979,411 source bytes. `files.json` preserves all 98 entries,
individual source object IDs, manifest bytes, actual SHA-256 and explicit remaining work.
This is not full partition completion, full Baldrix analysis, implementation, adoption approval,
independent Claude review, complete test certification, deployment, or production verification.

`semantic-notes.json`, `additional-notes.json`, `distributed-notes.json` and
`operations-notes.json`, `review-governance-notes.json`, `design-notes.json`,
`api-operations-notes.json`, `data-notes.json` and `spec-release-notes.json` are
the authored per-file semantic records.
All 98 reviewed files were read completely as UTF-8, including frontmatter, body, examples,
Gotchas and Source sections. An initial default PowerShell decode produced mojibake and
truncated output; that attempt is **not** coverage. The six affected files were reread in
full with `-Encoding UTF8`. Search hits and manifest enumeration do not count as semantic reads.

## 최종 본문 검토 상태 — 2026-09-09

고정 revision의 98개 파일, 979,411바이트를 모두 읽고 파일별 의미·호출 가능성·의존성·운영체제 차이·Zeus 대응·결정·미해결을 기록했다. 모든 source SHA-256과 크기가 manifest와 일치한다. `files.json`과 `status.json`은 98/98, `remaining.txt`는 빈 목록이다. 본문 전수 검토를 완료한 것이며, 모든 의존 구현·라이선스·외부 원문·테스트를 검증하거나 채택을 승인했다는 뜻은 아니다. 따라서 `body_coverage_complete=true`, `partition_complete=false`, `adoption_ready=false`를 구분해 유지한다.

81개 이후 기록은 `diagnosis-notes.json`, `skill-pipeline-notes.json`, `rubric-convention-notes.json`, `craft-security-notes.json`, `pattern-catalog-notes.json`에 있다. 마지막 두 문서는 구간을 이어 전문을 읽은 뒤 기록했다. 아래의 이전 checkpoint 서술과 역사적 테스트 영수증은 당시 증거를 설명한다.

### 주요 발견

- 트리거 평가기의 `precision`은 실제로 TN/(TN+FP), 즉 특이도다. 이를 정밀도라고 부른 F1도 표준 F1과 다르다. 오프라인 평가의 후보 수집·동률·예산 조건도 실제 matcher와 달라 결과를 라이브 정확도로 옮길 수 없다.
- 품질 검사의 heading·substring·인용 모양 검사는 내용의 정확성과 원문 검증이 아니다. 비어 있는 검사 집합의 PASS, 출력된 FAIL과 프로세스 성공 종료를 구별해야 한다. spec bundle의 빈 요구/TODO 통과와 Zeus SDD 준비단계의 인수·배포 차단은 `spec-bundle-zeus-comparison.md`에 별도로 대조했다.
- 과거 개인 프로젝트의 성공 횟수·commit 인용·토론 합의는 현재 승인이나 실행 증거가 아니다. 설계 snapshot의 canonical hash와 구현 의미의 동등성도 다르다. V19의 필수 4세대와 1·2세대 성공 예시, V20의 3개 crate 기준과 예외가 서로 맞지 않는다.
- nested `_common/mock-prototype/SKILL.md`는 일반 immediate tree 라우팅에 수집되지 않는다. fallback 재귀 스캔 가능성과 실제 pipeline 등록은 별개의 문제다. 문서의 +3 점수 설명만으로 호출 가능하다고 볼 수 없다.
- 디자인 문서의 글자 크기·광학 정렬·격자·숫자 스타일 지침이 상충하며, OKLCH 밝기 값이나 고정 폰트 규칙은 접근성·대비 검증을 대신하지 않는다. 실제 렌더링과 사용자 요구 확인이 남았다.
- pattern detector는 검색 recipe와 조언 문서다. 검색 결과 0은 호출자·저장 경로·관대한 문자열 비교가 없다는 증명이 아니다. 신규 모듈·짧은 함수·컴파일 통과·atomic commit은 회귀 위험 0을 보장하지 않는다.

### 실제 테스트와 남은 검증

실제 upstream 실행은 기존 Linux 격리 영수증의 tech-stack 테스트 17개 PASS뿐이다. 별도 reviewer probe 1회는 YAML inline-comment 결함을 재현했다. 두 논리 실행과 최초 인코딩 오염 capture/재실행 원시 증거를 보존했다. 이 파티션에서 추가 source 실행, native Windows 실행, 전체 hook/session/운영 실행은 하지 않았다. 부모 작업의 Windows/Linux CI 성공은 별도 Zeus 증거이며 upstream 98개 파일의 테스트 성공으로 합산하지 않는다.

`supporting-evidence.json`은 실제 전문/부분 읽기 범위를 구분한다. event_store 및 미완료 의존 구현, 추가 lint/surgery·trigger/quality/convergence 테스트, mock pipeline 등록, 외부 Rust 구현·개인 commit·원본 라이선스·원격 링크는 여전히 미확인이다. 검색 hit는 전수 검토로 올리지 않았다. 파일별 `remaining`은 이 후속 검증과 독립 검토·채택 결정을 유지한다. 새 구현이나 자동 채택으로 진행하지 않고 이 98개 범위에서 중지한다.

### 경로 이전과 증거 보존

81개 checkpoint 이후 작업은 독립 저장소 `C:/Users/rudtn/zeus`에서 수행했다. 이전 경로가 담긴 원시 영수증과 역사적 checkpoint는 변경하지 않았다. `checkpoint98.json`의 receipt SHA-256은 현재 원시 바이트 보존 확인값이다. 소스·설정·credentials·운영 상태·구현 코드·commit/push는 이 검토에서 수정하거나 실행하지 않았다.

## Actual activation and body consumption

Read in full: `scripts/handlers/prompt/skill_match.py`, `scripts/lib/frontmatter.py`,
`scripts/lib/frontmatter_norm.py`, `scripts/lib/skill_score.py`,
`scripts/lib/skill_token_budget.py`, `scripts/lib/tech_stack.py`.

The UserPromptSubmit handler exits on empty or system reinvocation prompts, resolves
`USERPROFILE/.claude/skills`, loads `.claude/tech-stack.yaml` from cwd, collects candidates,
parses frontmatter and computes prompt score. Pipeline selection may force a match with
+3 but full bodies still need base score >= threshold (default 3), top 3 selection and
budgeting. This is plain-text advisory injection, not executable enforcement of each guide.
Installed Claude hook configuration and actual sessions were not exercised by this review.

Tree mode collects only immediate `.md` files in active directories, skipping underscore
basenames. Therefore `_template.md` and YAML are not candidates. Nested
`_common/mock-prototype/SKILL.md` is absent in ordinary `_common` tree mode (its body is now fully reviewed). Fallback recursive scanning can collect it. `_common always active`
means eligible candidate set, not every guide included or every nested skill accessible.

The parser accepts UTF-8 BOM and raw key:value strings, but validates no required schema.
List normalization splits inline bracket lists; it does not fully parse YAML quoting.
Scoring uses keyword/intent/path/pattern only; `name`, `description`, `phase`, `requires`,
`tech-stack` do not create per-file activation guards. Seven high-document-frequency
Korean intents score +1, not template +2. File-pattern reads can read prompt-mentioned
host paths with `read_file_head`; no project authorization boundary is enforced there.
Zeus already bounds evidence to pinned tracked regular files instead.

Body budget is 4000 Unicode characters, per-body target 3000, top 3, pointers max 8.
The handler's comments that top body ignores budget are stale: library `fit_top_skill`
does bound it. The subsequent handler cap may select an overlong level-2 decision tree
without another <=3000 check, so that per-body comment is not a reliable hard bound.
Truncation preserves only decision-tree/Gotchas headings and can omit material constraints
elsewhere (e.g. JSON verdict contract, evaluator bounds, reviewer separation). Full source
retrieval is necessary before treating an abbreviated pointer/body as complete authority.

`tech_stack._parse_yaml` supports a small indentation subset and **does not remove inline
comments**. The provided tech-stack template includes such comments on routing values.
Candidate strings are then wrong when copied verbatim. `load_tech_stack` returns None for
missing/no-language config, which causes broad fallback scanning rather than fail-closed
selection. Extensions/path traversal constraints require further review before adoption.

## Traced implementation versus prose-only claims

`scripts/handlers/stop/learner.py` read in full: recurring-error sensor uses threshold 3,
reads all history lines then selects last 300, logs candidates and conditionally writes
insight_index. It additionally emits routine work-unit digests with separate correlation ID
and watermark. It does not write learned skill files. Transitive insight_index/work_unit_store
implementations and Stop registration are not fully traced here and remain explicit work.

`agents/harness-tracer.md` and `agents/harness-document-specialist.md` read completely.
They substantiate role prose for trace/external-context; both declare free_text outputs.
They do not supply runtime JSON validation or prove available Agent/Task registrations.
`.claude-plugin/plugin.json` read fully: plugin name khaness, version 0.1.0, author trevi00;
it is not proof that all described commands/tools exist.

Source-code searches across scripts/agents/commands for wiki_ingest/wiki_query,
ultraqa-state/autoresearch/visual-verdict/skillify/deepinit/ai-slop-cleaner found no dedicated
implementations. This records absence from the searched code surfaces, not a proof that
no external or unreviewed integration exists. Markdown guides can still be injected through
the generic matcher. Slash spelling in prose is not a verified callable Claude command.

## Zeus overlap and boundary

Read completely: `src/codex_harness/adapters/skill_routing.py`,
`src/codex_harness/domain/skill_admission.py`, `src/codex_harness/domain/skill_guidance.py`.
The native router uses exact Git revision evidence, rejects absolute/traversal/linked inputs,
identifies skills by full path, records content refs and pre-budget body length, and preserves
retrievable pointers. It caps individual bodies before total allocation. Guidance is
advisory-only with capability-specific tool text and one-hop already-eligible cross-references.
No `.claude` source policy or inline command can supersede authorization or read-only tasks.

Per-file `zeus_modules` in files.json distinguish this confirmed common ingestion overlap
from proposed domain/executor/research/context counterparts, whose feature equivalence has
not been established. Git owns approved definitions; PostgreSQL owns runtime records;
immutable artifacts own evidence. Task/reviewer assignments must use six-W contracts and
lease/generation fencing. Local wiki, autoresearch and ultraqa state files are not extra SSOTs.
Ontology/topology needs explicit source-to-skill/module/dependency edges and unresolved link
nodes. The semantic prose is an adaptation proposal only, pending whole-source coverage,
independent Codex/Claude decisions and primary implementation/review/promotion gates.

## Test evidence and limits

Tests read in full (only the first subsequently executed, as detailed below):

- Upstream `scripts/tests/test_tech_stack.py`: flat/nested stack order, candidate variants,
  extensions and missing-language fallback. Does not test inline-comment template copy.
- Upstream `scripts/tests/test_skill_match_scan_root.py`: fake home/no cwd/no marker/home
  exclusion, ancestor root detection and project-type integration. Top-level imports may
  resolve threshold/live paths; executing source on host is forbidden.
- Zeus `tests/test_skill_routing.py`: concept dedupe/Korean boundary, path evidence,
  invalid score, top-body cap, Git-bound routing tiers, pointers and malformed fences.
- Zeus `tests/test_skill_guidance.py`: phase/tool advice, one-hop eligibility, unresolved
  ambiguity/traversal, packaged alias, external reference tail and artifact provenance.

During the initial 33-file checkpoint no upstream test/script was executed. A later bounded
continuation executed the isolated tech-stack test and defect probe below. No installer,
network request, MCP configuration action, DB query, live service action, credentials access
or ArtifactHub upload was executed. Inert reads, hash comparisons and review-artifact
generation are not upstream execution receipts.
Required follow-up: isolated no-network read-only-source tests with scratch fixtures,
exact argv/exit/output receipts; copied template comments and nested collection regressions;
per-skill matching/truncation fixtures; visual/evaluator schema checks; source-specific
failure cases in the per-file notes. Until executions and unknowns are resolved, research
standard blocks adoption even for the 55 text-reviewed files.

## Second checkpoint: review/governance and design source

New source files (22) have complete authored entries in `review-governance-notes.json`
(12) and `design-notes.json` (10). In addition read completely:
`agents/kha-code-reviewer.md`, `agents/harness-git-master.md`,
`scripts/validators/git_flow.py`, `scripts/tests/test_git_flow.py`,
`scripts/lib/git_flow_override.py`, `.github/workflows/ci.yml`,
`scripts/tests/test_skill_token_budget.py`, `scripts/validators/design_slop_a11y.py`,
`agents/harness-design-critic.md`, `scripts/tests/test_design_slop_a11y.py`,
`scripts/validators/__init__.py`, `scripts/lib/__init__.py`.
Only lines 1-195 of `scripts/lib/guard_patterns.py` were read; the rest is not claimed.
`scripts/handlers/pre_tool/guard.py` was searched for callback/override points but its body
was not fully read, so live guard wiring is still an explicit trace gap.

Code-review guide requests performance/architecture coverage while default reviewer
excludes performance; quick mode only searches patterns. Agent reviewer filters lock and
generated files and prohibits AGENTS reads, so it cannot satisfy this research standard's
full-source coverage unmodified. Inline same-agent fallback is not independent review.
Git validator emits FAIL text with process exit0, and overrides support explicit company
or solo fields, not arbitrary company names. Main push regex has solo override contrary to
the absolute common guide. The CI lacks explicit permissions, uses moving action tags,
Linux-only runner and path filters that omit skills-only/brain-only changes.

Design validator is an advisory regex checker, not full accessibility or state verification.
In a clean Git working tree `_git_changed` returns empty list, and `find_findings` only
falls back when it returns None; the docstring's 'nothing changed fallback' is false.
Missing files/UTF8 errors skip silently, normal scans have no source-byte size cap,
fallback traversal can still walk large excluded directories before filtering and has
400 accepted-file cap, output truncates200 findings. Generic-link regex also matches
non-link element text. Any `:focus-visible` anywhere in a file suppresses all outline
removal findings there; JSX dynamic/tabIndex and multiline attributes can evade line regex.
It does not calculate contrast, accessible names, keyboard behavior, all states or render.
Graduate status is dynamically imported through validators/__init__→lib.graduation, whose
transitive implementation is unreviewed here, so no full validator tests were executed.
Critic allows code-only low-confidence assessment whereas the UI gate forbids PASS without
render evidence; that missing evidence must remain a gate gap. UI tooltip guidance conflicts
with disabled-controls warnings in motion. Token mandatory3tier conflicts with its own
defer-until-second-variant rule; HEX fallback conflicts with blanket no-hex lint. These
are adaptation decisions, not automatic stylesheet mutations.

## Actual isolated test and defect probe

`test-tech-stack-receipt.json`: actual upstream `python -B tests/test_tech_stack.py`
completed exit0 with **17 tests passed** in preexisting immutable image
`sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a`
(Python3.13 Alpine). All direct source/dependencies were read first. Container had
network none, read-only root, dropped capabilities, no-new-privileges, nonroot65534,
bounded CPU/memory/PIDs, tmpfs scratch, and only pinned scripts mounted read-only.
No image pull occurred. This is Linux source verification, not Windows or live hook proof.

`template-inline-comment-probe.json`: actual reviewer-created isolated assertion of the
copied template/parser defect, with the same restrictions and additionally only the pinned
template mounted read-only. It confirms parsed language includes comment text and expected
`java/springboot-3.2` candidate is absent. Exit0 means the **defect reproduction assertion
passed**, not that template routing is correct. First capture's Korean stdout had replacement
characters; it is preserved as `template-inline-comment-probe-first-capture.json` and
superseded for Unicode evidence by an ASCII-escaped JSON rerun with raw base64/SHA output.

Both current receipts record exact argv/image/time/returncode/output. The earlier malformed
capture is retained, not counted as another distinct logical test. These are honest reviewer
execution records, **not Zeus fenced audit-runner authority receipts**, and cannot bypass
its approval contract. `files.json` associates the two logical executions only with
tech-stack-template.yaml; other source workflows/tests remain not run. The successful clean
value fixture suite does not detect template inline-comment corruption, demonstrating the
remaining coverage gap directly.

Additional complete Zeus implementation reads: `application/workflow.py` (durable task
submit identity, dependency admission, ownership/lease/generation, complete/outbox, failure,
cancellation and report deduplication), `application/scheduling.py` (slot/generation
dedupe, prior unfinished task gate and adoption recheck), `application/monitoring.py`
(unknown stale health and explicit review/release stage projection). Only
`application/service.py:196-228` was read for session CAS/flush_outbox; the whole file is not
claimed reviewed. `flush_outbox` publishes inside a transaction and acknowledges possible
post-publish crash redelivery; consumer identity dedupe is still needed. A first proposed
`domain/workflow.py` path proved nonexistent and is corrected to application/workflow.py.
Additional complete Zeus test reads, not run: `tests/test_dispatch_fairness.py` (task and
decision queue fairness), `tests/test_monitoring.py` (unknown progress, stale health,
lease expiration, credential redaction and local read-only HTTP surface).

Additional upstream complete reads: `scripts/validators/mutation_safety.py` and
`scripts/tests/test_mutation_safety.py`. The validator scans markdown destructive regexes
but any safety token within +/-10 lines suppresses a finding, including generic example,
migration or WHERE text. Single-file rm -f is intentionally excluded; DELETE FROM is in the
docstring but not the implemented patterns. Default findings are WARN with exit0; --strict
changes exit status. Telemetry writes occur on findings. Tests assert proximity suppression
and selected regexes but do not establish safe shell execution. No validator was run.

## Licensing, duplication and external references

No reviewed file is designated generated/duplicate. Similar Boilerplate/Gotchas/quality-axis
structure is not byte-equivalence, and OMC/superpowers ancestry claims require original and
generator comparison. `verification-before-completion.md` claims superpowers MIT/Jesse Vincent;
the upstream original and license text were not inspected. No LICENSE/COPYING path surfaced
in pinned file-name search; this is not legal clearance or a conclusion that no license exists.
Every Source URL in reviewed guides was read as text but its remote page was **not fetched**.
Version/default/performance/compatibility claims therefore remain unverified and are not
endorsed technical recommendations. Private impl/debate/memory references are likewise
unverified unless a read implementation is named above.

## Continuation

98개 본문 검토는 완료되어 `remaining.txt`는 비어 있다. 후속 작업은 각 파일의
`unverified`와 의존 코드·설정·테스트·출처의 미해결을 해소하는 것이다. 본문 검토
완료를 하위 시스템 검증이나 흡수 승인으로 승격하지 않는다. 추가 실행 결과는
실제 영수증으로 결속하고 기존 원시 증거를 보존한다.
