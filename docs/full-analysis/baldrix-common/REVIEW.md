# Baldrix common skills — bounded semantic review checkpoint

Source: trevi00/baldrix, revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`.
Inventory: `.runtime/absorption/sources/baldrix/manifest.json`.
Read source root: `.runtime/absorption/sources/baldrix/pinned/`.
Zeus HEAD observed: `0548efaf1bc8833c750c80b242de03b5a73d7799` (working source reads, not a clean-tree attestation).

This checkpoint contains **81 / 98 common files semantically reviewed; 17 remain unreviewed**.
The full denominator is 979,411 source bytes. `files.json` preserves all 98 entries,
individual source object IDs, manifest bytes, actual SHA-256 and explicit remaining work.
This is not full partition completion, full Baldrix analysis, implementation, adoption approval,
independent Claude review, complete test certification, deployment, or production verification.

`semantic-notes.json`, `additional-notes.json`, `distributed-notes.json` and
`operations-notes.json`, `review-governance-notes.json`, `design-notes.json`,
`api-operations-notes.json`, `data-notes.json` and `spec-release-notes.json` are
the authored per-file semantic records.
All 81 reviewed files were read completely as UTF-8, including frontmatter, body, examples,
Gotchas and Source sections. An initial default PowerShell decode produced mojibake and
truncated output; that attempt is **not** coverage. The six affected files were reread in
full with `-Encoding UTF8`. Search hits and manifest enumeration do not count as semantic reads.

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
`_common/mock-prototype/SKILL.md` is absent in ordinary `_common` tree mode (its **body
remains unreviewed**). Fallback recursive scanning can collect it. `_common always active`
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

Read each path in `remaining.txt` completely in bounded UTF-8 batches. Trace material
callers/validators/tests, including private/reference availability, before moving that file
to semantically_reviewed. Add authored notes, regenerate the 98-entry ledger and preserve
existing evidence. Do not promote inventory/hash verification into semantic completion.
Large abstraction-first/pattern-auto-detector/security/doc-verify files need multiple
contiguous line ranges; no heading/AST summary can replace them.
