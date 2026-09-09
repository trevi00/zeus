# Joint resolution: lifecycle, model and profile implementation

Actual Claude session `9f1e16e8-7416-4047-9ccd-8ed25b9a39cd` completed an
independent initial review and a resumed discussion. Raw prompts, JSON, stderr and
receipts are retained. The initial call took 235.37788677215576 seconds and reported
$2.6137610000000002; discussion took 222.77057790756226 seconds and reported $1.196198.
These are CLI-reported costs, not independently reconciled billing. Both returned
exit 0 and is_error false. Root's independent eight-file read preceded opening
Claude's findings. Claude's scope does not include the 42 delegated workflow files.

Root and Claude agree on the principal static findings:

- expectedBase is accepted and unused, and worktrees are selected without task
  ownership. Main advancement is deliberately supported by the non-FF test, so a
  proposed fix must distinguish ancestry, ownership and current revision fencing.
  Simply requiring expectedBase == HEAD would break that supported behavior.
- Reconcile/cleanup failures and partial archive/phase mutations need explicit
  recoverable outcomes. An existence flag is not an operation receipt. The
  milestones_updated literal follows a normal-path write: neither reviewer should
  claim it is returned after that write throws. Retain original evidence and errors.
- Planning lock timeout runs the callback without reacquiring; pathname-only
  unlink and callback EEXIST handling can undermine ownership and single execution.
  No race/crash was reproduced. loadConfig can write on a nominal read path.
- Phase completion permits verification debt as warnings, can count the same
  completion twice, and expects a Requirements format different from add/insert.
  SUMMARY count is not matched tests or actual human acceptance.
- Profile redaction misses preferred evidence_quotes and other rendered values;
  other generators insert raw directives with no equivalent redaction. Managed
  auto update compares against new source content instead of a historical digest.
  No live user sessions, credentials, profile collection or transmission were used.
- Quick IDs, mtimes, role aliases and file installation checks cannot establish
  unique task ownership, process liveness or Astra/Sol/Terra qualification.

## Final root corrections to both model records

1. There are exactly **13 declared tests: 12 nonempty-worktree scenarios and one
   no-worktree scenario**. That descriptive split is legitimate; the root followup
   and Claude discussion over-corrected the initial phrase '12 non-trivial'. All
   13 invocation sites pass expectedBase. **Zero were run here**. Claude's final
   priority text saying a suite 'passed it 13 times' is not execution evidence;
   it means the flag appears in 13 source calls. No test-suite PASS is accepted.
2. The phase text-renumber cascade is restricted to matching text and loop values
   through 99. For example, removing 5 can turn matching 'Phase 7' into 'Phase 5'
   through two replacements. Claude's 'every phase number above' is too broad:
   values above 99, unmatched formats, letter/custom IDs and regex delimiters need
   separate treatment. This is static control-flow reasoning, not a Node result.
3. The manager filter fails to explicitly exclude self, but does **not normally
   filter out its own action**: in an acyclic graph reaches(self,self) is false,
   so the shown dependency-only filter permits it. Claude's claimed self-blocking
   consequence is withdrawn. The actual concern is that mtime plus dependency
   reachability is not an execution lease and may permit duplicate self-dispatch;
   cycles require their own qualification. Root did not execute a scheduler.
4. The clear exclusion is exactly /^999(?:\.|$)/ on directory names: 999.1-name
   is excluded, 999-name is not. The workflows003 summary's generic '999 prefix'
   wording is too broad. Original reports remain historical; use this narrower
   statement alongside the primary milestone code and root initial review.
5. Actual command dispatch is established by the reviewed router intervals.
   Wider natural-language workflow reachability and transitive closure are
   incomplete, rather than every primary path being entirely unreachable/unknown.
6. Literal 'gsd-' is the prefix in profile skill discovery; the spaced spelling in
   root-initial prose is a typo, not an additional prefix. Source identity controls.

## Adaptation decisions and outstanding verification

Adapt the real temporary-Git test design, checked conflict/artifact fields,
per-worktree premerge snapshot, non-amend reconciliation, CRLF blob comparison,
finite questionnaire options and partial-state visibility. Preserve real local
defenses such as argv arrays, exclusive create and validated path segments while
replacing unsupported global guarantees with typed outcomes and runtime evidence.

Do not directly adopt age-based ownership, global file stores as runtime authority,
automatic human acceptance, inferred preference as an instruction grant, output
existence as success, or unconsumed safety parameters. Additional confirmation
dialogs are not the remedy for every operation: honor existing task authorization,
bind precise ownership/scope and retain recoverable evidence. Real human QA remains
necessary for the user's specified experience and financial-flow acceptance.

Required follow-up: qualify a Node/Git immutable offline executor; run the original
13 tests without importing source on the host; retain failure/skip denominators;
exercise actual wrong-base/ownership/partial-failure/renumber/config/profile
counterexamples in isolated scratch; finish all callers, tests, licenses and OS
validation. No new source execution or fake service/model acceptance occurred.
All eight primary records remain body_reviewed_call_test_trace_pending, with no
adoption or whole-analysis approval. Zeus runtime implementation and activation
were not changed by this review; related issues stay unresolved.
