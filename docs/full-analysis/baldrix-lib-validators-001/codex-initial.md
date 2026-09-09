# Independent Codex validator review

Root read all five primary bodies (39,639 bytes) at Baldrix
`cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, partition
`baldrix:scripts/lib/validators:001`, scope
`472776938cb3976606c189d8a3817afc613c25029036b6a11f0fd390309c035b`, before
reading any Claude response for this partition. Fresh caller read: agent_outcome_audit.py
137–219. Its other ranges were read in the preceding observer work; this initial note
does not newly claim full caller coverage. Test filenames were discovered but their
bodies are not yet read. Original execution/import is zero at this checkpoint.

## Structural contract

Explicit ordered layers and separate schema/ref/tool errors are useful deterministic
guards. Integer/number predicates exclude bool and declared extra properties can be
rejected. However an absent/non-dict schema or allowlist disables checks; malformed
output/evidence/tool_calls can yield ok with no corresponding layer observations.
The result does not report skipped-layer denominators. Declared tool names are
self-reports, not actual runner-owned usage or capabilities.

The implementation is a documented JSON Schema subset, not a complete schema validator.
Unknown keywords are ignored; malformed items/enum can silently disable constraints.
additionalProperties=false only applies when properties is a dict. Python equality
in enum can equate bool and integer; number accepts nonfinite floats and NaN comparisons
do not reject bounds. Malformed unhashable types/required keys/allowlist elements and
mixed-key sorting can raise. Recursive depth/total items/errors have no explicit budget.
These are static candidates, not executed counterexamples here.

Referential checks inspect only top-level evidence, unlike the observer's nested fallback.
Permission/OSError becomes schema failure here rather than the observer's non-missing.
FileNotFoundError is labeled fabrication without source/time/environment identity.
Stat accepts directories/symlinks, ignores evidence ranges/content and uses process cwd.
NUL-path ValueError is outside its catches. D1/D2 are therefore not universally equivalent,
and both remain weaker than actual historical evidence authentication.

## Lexical and cross-file signals

semantic.check is deterministic token-set overlap, not semantic truth. ASCII regex has
a hard minimum of three characters even when min_token_chars is smaller; CJK bigrams
ignore that threshold and one-character runs are skipped despite conflicting comments.
Negation/order, paraphrase, normalization, task scope and importance are not modeled.
Every readable evidence file is compared against the whole summary; legitimate multi-file
division of responsibility can lower per-file overlap. Only a default 4KB head is read,
lossily decoded, without a content hash or exact evidence-span binding. The configurable
byte limit is not validated: negative reads can remove the cap; special files can block.
No aggregate path/read-time budget or capability boundary is established here.

SemanticResult retains errors and SKIPPED, valuable distinctions. Yet one clean readable
entry plus unreadable entries can return CLEAN with errors. Blank files add breakdown
rows without signal. Tokenless nonblank files can instead be strong suspicion. Labels
cannot replace checked denominators, raw bytes and authenticated scope.

cross_ref prompt overlap divides by unique SUMMARY tokens, not prompt coverage. Shared
vocabulary/legitimate quotations can score high; overlap does not prove copy-paste.
Consensus tests raw path count before storing ratios in a dict keyed by path. Repeated
same-path entries can satisfy the two-file precondition then collapse to a single strong
ratio, classified cherry-picked. One readable plus one unreadable path likewise lacks
actual multi-file evidence; two unrelated readable files can both score zero and yield
CLEAN. Rest_max only examines the second highest file, so other unrelated entries do not
change a two-high-file decision. Missing/empty/minimum-token scope must remain explicit.

## Boilerplate and consumer authority

Boilerplate flags filenames, license/generated markers and short heads. It cannot establish
that a file has no domain meaning: lockfiles, requirements, package entrypoints, generated
contracts and license review can be the actual user task. A header marker can be a quote.
Path basename follows host semantics; Windows paths on Linux are not equivalent. Small
max_file_bytes can itself create a short-file finding. Filename-only unreadable cases
retain errors and a weaker label, a useful guard rather than content corroboration.

The package forbids LLM/embedding and the bodies honor that local constraint; the term
semantic similarity in the package doc conflicts with its own deterministic lexical export
unless interpreted narrowly as an external model. Treat this as terminology/contract
clarification, not evidence of a hidden LLM invocation.

Fresh caller _resolve_verified_by gives ALL cross-ref suspicious labels priority over
boilerplate and semantic, rather than only strong cross-ref first as its ladder wording
suggests. LIKELY_BOILERPLATE has events but no distinct grade. D2 ok plus absent/skipped
later checks can get evidence_validator. These names do not prove independent verification.
_raw_event_emit suppresses append exceptions and taxonomy fallback can still emit raw;
actual event persistence and downstream calibration/Grafana consumers are not closed.

## Zeus direction and open work

Retain typed advisory findings, per-file errors and explicit deterministic scope. Bind
runner-owned tool usage, original artifact/source/environment identity, validated schema
version, checked/skipped/error denominators and raw observations. Lexical/name heuristics
can inform human review but must not authenticate fabrication, human SDD acceptance or
model qualification. Git defines policy; PG owns runtime attempts and decisions.
Read original tests/callers/config and compare actual Claude before adaptation. License,
OS, real user scenarios, process/file capabilities and adoption remain incomplete.
