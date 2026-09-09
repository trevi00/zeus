# Codex independent implementation review

Pinned Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`; partition
`baldrix:get-shit-done/bin:002`, eight primary files, 195529 bytes. All eight
primary bodies read before opening the actual Claude initial review. These are
static findings, not observed upstream execution, verified fixes, adoption or
whole subsystem completion. Caller/config/test closure is still pending.

## init.cjs (1–1522)

- Initializers assemble filesystem/config/model metadata, not acceptance evidence.
  Execute/plan validation imports cmdStateValidate but never invokes it: the local
  count check is narrower (143–168, 268–291). A ROADMAP fallback can report
  phase_found with a null directory. Model names do not establish qualification.
- Quick IDs (448–504) use local date and two-second time blocks without a shared
  counter, lease or collision check; equal times produce equal IDs. Reported date
  uses UTC while the ID uses local time. Description/branch templates are not
  branch ownership or revision binding. Resume reads an agent-ID file (506–536),
  without a live process/lease observation.
- Verify-work (538–586) returns no uat_path; phase-op (588–697) can return it.
  Phase-op explicitly prefers the current ROADMAP over an archived directory,
  a useful defense not uniformly repeated in every initializer.
- Milestone-op (758–817) calls any phase with at least one SUMMARY completed,
  whereas manager (915) and progress (1177) compare counts. Manager can override
  disk status from ROADMAP checkbox (938–944). None binds actual tests or human QA.
- Manager activity is file mtime under five minutes, including future mtimes
  (922–934); dependency parsing drops letter suffixes (979). Unparseable textual
  dependencies yield an empty list whose every() is true. Partial phases are
  treated as active regardless of age (1064–1067), but receive no execute action
  in 1019–1043. Self is not excluded in the dependency-only concurrency filter;
  this is not an execution lease. Flag sanitization is a real restricted-token
  defense (1088–1099), not a role/policy authorization check.
- Progress sorts with parseInt (1157–1162, 1224), losing decimal/letter order;
  current/next selections occur before the final combined sort. Read failures can
  leave partial or empty inventories without a distinct unknown status.
- Workspace detection (1276–1429) catches Git status failure and can report clean;
  git --version alone establishes worktree_available. Removal *initialization*
  builds a path from an unvalidated name and parses whitespace-free table cells;
  it does not itself delete workspaces. Destructive downstream behavior needs
  direct caller evidence. Skills block uses validatePath and SKILL.md existence
  (1443–1480); the helper's containment/symlink semantics require inspection.

## intel.cjs (1–660)

- Five derived JSON indexes are searched textually. Missing, malformed and failed
  reads often collapse to null/disabled rather than explicit incomplete evidence.
  Metadata age is not source-revision freshness; an invalid truthy date produces
  NaN and evades the older-than threshold. File hashes are over UTF-8 decoded text,
  not original bytes. Snapshot hashes cover the five indexes, not source coverage.
- Update returns an action describing agent spawning; it does not spawn an agent.
  Snapshot and metadata/export helpers are not all gated like query/status.
  Snapshot writes can report saved with no indexed files. Metadata patch refreshes
  the timestamp without verifying the index and lacks a strict version schema.
- Validation checks existence and heuristics, not full schemas or source identity;
  null entries can throw and relative path checks depend on process cwd. Export
  extraction is regex/brace counting, not a language parser: inline CommonJS
  members, comments/strings, aliases and re-exports need explicit qualification.
  No assertion is made that these limitations were reproduced in a Node runtime.

## learnings.cjs (1–378)

- Store defaults to the importing process home .gsd/knowledge; records are files,
  not the PostgreSQL runtime authority required for Zeus. Dedup hashes learning
  text plus source project, and trusts persisted hashes without recomputation.
  Check-then-write with random IDs has no atomic uniqueness constraint or CAS.
- JSON parse success is not typed schema/provenance validity. Failed reads are
  excluded; malformed dates/tags have ambiguous behavior. ID validation is a real
  filename traversal defense, but does not establish symlink/ownership guarantees.
- Markdown copying splits on headings without fence awareness, derives project
  identity from a basename, and does not bind tests or review to the experience.
  Prune is an unversioned age deletion, not validated retirement of knowledge.
  A stored experience is not an automatically qualified improvement.

## merge-back.cjs (1–267)

- opts.expectedBase is documented (209) but unused. All worktrees other than cwd
  are candidates (212–264), without task owner/branch allowlist. Sorting makes
  iteration deterministic but does not establish which work belongs to this task.
- Useful defenses: detached-HEAD ancestry check, fresh pre-merge HEAD per worktree,
  fresh reconciliation commit instead of amending, and CRLF drift handling.
  SUMMARY-at-tip resolution peels one planning-only commit, not an evidence chain.
- Several Git results are ignored: rollback, artifact cleanup/restoration, and
  reconcile staging. Reconcile commit failure can leave null yet proceed to
  forced worktree removal/branch deletion; missing SUMMARY/PLAN flags do not block
  merged:true. Deletion ownership, recovery and preservation must be redesigned.
- Failure is collected per worktree while other merges continue; global false can
  coexist with partial successful mutations and a reported commit. Listing failure
  can collapse to no_worktrees. No original Git command was executed in this review.

## milestone.cjs (1–282)

- Requirements completion performs text replacement, not test/human acceptance.
  Missing IDs are reported but there is no exact-revision transition contract.
- Complete creates/overwrites archives and Shipped history from available files;
  missing inputs or summary-read failures do not establish complete coverage.
  Multi-file writes/moves have no rollback journal or revision compare-and-swap.
  Version is required but not a constrained archive identifier in this function.
- If archive renaming fails mid-loop, some phases may already have moved while
  phasesArchived remains false (assignment occurs only after the whole loop).
  Existence booleans can describe old artifacts, not this operation's verified work.
- Clear requires --confirm when directories exist, a useful explicit guard, but
  then recursively deletes every directory except /^999(?:\.|$)/ matches. This
  differs from a general 999-prefix exclusion: 999-name is not excluded. No
  archive/current-work/acceptance check is present in this function. Not executed.

## model-profiles.cjs (1–70)

- Static role-to-model alias table with quality/balanced/budget/adaptive profiles;
  VALID_PROFILES is derived from the first role. This is routing configuration,
  not evidence that Astra work has been reproducibly transferred to Sol/Terra.
- Helper formatting assumes complete valid string mappings. Profile names,
  model overrides and effective CLI behavior need core/router trace. No cost cap,
  model skill qualification or actual provider execution is proved by this file.

## phase.cjs (1–931)

- Listing returns early if live phases are missing even when archives are requested;
  archive names are later joined to the live path when type-filtering (11–85).
  Plan index matches SUMMARY basenames (236–289), which is stronger than a mere
  count but still not acceptance. Wave defaults to 1 and autonomous to true.
- Add/insert use withPlanningLock, but directory creation precedes ROADMAP write;
  a lock is not a filesystem transaction. Custom IDs/project prefix need path
  validation. Insert checks the current milestone then searches raw ROADMAP for
  placement (407–469), potentially selecting an earlier reused phase header.
- Remove deletes before renaming and catches rename failure (612–625), then edits
  ROADMAP and decrements STATE. It can decrement without finding a directory.
  Renaming handles narrower IDs than creation; filenames change without updating
  their contents. Text renumbering descends 99 to the removed number and repeatedly
  replaces newly produced values (569–580): a higher phase reference can cascade
  more than once. This is a static derivation requiring original runtime evidence.
- Complete only warns about pending/blocked UAT and human_needed/gaps_found
  verification (673–692); bare UAT.md/VERIFICATION.md are not included in those
  substring filters. No minimum plan or matched-summary gate precedes writes.
  Completion of an already completed phase can increment Completed Phases again
  (876–895). No idempotent transition identity is checked here.
- Creation writes **Requirements**: (366,448), completion expects
  **Requirements:** (764), a concrete producer/consumer format disagreement.
  Lock-protected ROADMAP/REQUIREMENTS writes (694–788) are sequential, and STATE
  is outside that lock scope. The comment 'atomically' overstates the shown code.
  Missing read evidence should prevent adoption, not be converted to complete.

## profile-output.cjs (1–1048)

- Eight questionnaire dimensions map to instructions; answers have finite-option
  validation and self-report confidence MEDIUM/LOW. The regression instruction
  says to run tests mentally (165), which cannot meet Zeus's real acceptance rule.
- write-profile redacts only dimensions[*].evidence quote/example/signal
  (497–537), whereas rendering prefers evidence_quotes (603); other rendered
  fields remain outside this pass. Default output is global .claude. Actual
  secret transmission/collection was not performed or observed (FA032 scope).
- Instruction/profile generation includes LOW/UNSCORED dimensions (743–759,
  830–847) and untrusted claude_instruction without qualification/consent receipts.
  Multiple outputs directly write files with no shared schema/redaction boundary,
  CAS/ownership check or durable previous-generation recovery.
- Managed section marker parsing uses first start/end independently, without
  ordering/uniqueness checks (225–261, 878–899). 'auto' compares current body with
  newly generated content, not last generated content, so upstream changes can be
  classified as manual edits (973–991). profile_status can be already_present
  when no profile marker exists (1007–1017). These labels need stricter contracts.
- Skill discovery's gs d-prefix exclusion (actual literal `gsd-`, 404) is narrower
  than an installation manifest. Name-only dedup is not content identity. Its
  YAML-like parser retains quote/block markers; architecture summarization keeps
  fence lines but can omit their ordinary body lines (364–370). Generated context
  can lose meaning; it needs visual/human review and source binding.

## Required next evidence

Trace direct CLI routing, core locks/config/model/path helpers, producer/caller
workflows and relevant actual tests. Compare independent actual Claude findings
without treating either model verdict as execution evidence. Node/Git originals
remain unexecuted in this batch; no Windows/Linux/WSL acceptance claim. Adopt ideas
only after whole analysis, license/dependency review and qualified Zeus-specific
implementation, tests, independent approval and promotion.
